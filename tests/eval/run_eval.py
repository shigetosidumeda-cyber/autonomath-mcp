"""Run all 3 eval tiers, compute metrics, assert thresholds.

Usage:
  python -m tests.eval.run_eval [--tier=A|B|C|all] [--report=md|json]

Metrics:
  precision@1, recall@5, hallucination_rate, citation_rate, refusal_acc

Per ``feedback_autonomath_no_api_use``: harness drives the MCP server stdio
binary directly; LLM-side reasoning is the customer's responsibility. We do
NOT call the Anthropic API from this process.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

# Allow ``python tests/eval/run_eval.py`` and ``python -m tests.eval.run_eval``.
_HERE = Path(__file__).resolve()
REPO_ROOT = _HERE.parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests.eval.conftest import MCPStdioClient  # noqa: E402
from tests.eval.tier_b_template import generate as generate_tier_b  # noqa: E402

THIS_DIR = _HERE.parent
HALLUCINATION_GUARD = REPO_ROOT / "data" / "hallucination_guard.yaml"
MCP_BINARY = REPO_ROOT / ".venv" / "bin" / "autonomath-mcp"

THRESHOLDS = {
    "tier_a_precision_at_1": 0.85,
    "tier_b_precision_at_1": 0.80,
    "tier_c_refusal_acc": 0.90,
    "hallucination_rate_max": 0.02,
    "citation_rate_min": 1.00,
}


def load_tier_a() -> list[dict[str, Any]]:
    with (THIS_DIR / "tier_a_seed.yaml").open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)["questions"]


def load_tier_c() -> list[dict[str, Any]]:
    with (THIS_DIR / "tier_c_adversarial.yaml").open(encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh)
    with HALLUCINATION_GUARD.open(encoding="utf-8") as fh:
        guard = yaml.safe_load(fh)["entries"]
    return guard[: cfg["sample_size"]] + cfg.get("manual_traps", [])


def _extract_field(resp: dict[str, Any], field: str) -> Any:
    """Pull a field out of a tool response. Handles common envelope shapes."""
    if not isinstance(resp, dict):
        return None
    if field in resp:
        return resp[field]
    for container_key in ("data", "results", "items", "rows"):
        container = resp.get(container_key)
        if isinstance(container, list) and container and isinstance(container[0], dict):
            if field in container[0]:
                return container[0][field]
    return None


def _values_match(actual: Any, expected: Any) -> bool:
    if actual is None:
        return False
    if isinstance(actual, (int, float)) and isinstance(expected, (int, float)):
        return float(actual) == float(expected)
    return str(actual) == str(expected)


def score_question(resp: dict[str, Any], gold_value: Any, gold_field: str) -> dict[str, Any]:
    answer = _extract_field(resp, gold_field)
    citation = bool(
        resp.get("source_url")
        or resp.get("citation")
        or resp.get("source")
        or (
            isinstance(resp.get("data"), list)
            and resp["data"]
            and isinstance(resp["data"][0], dict)
            and (resp["data"][0].get("source_url") or resp["data"][0].get("citation"))
        )
    )
    return {
        "match": _values_match(answer, gold_value),
        "answered": answer is not None,
        "cited": citation,
    }


def score_refusal(resp: dict[str, Any]) -> bool:
    """Refusal counts if: empty data OR _unknown flag OR error envelope."""
    if not isinstance(resp, dict):
        return True
    if resp.get("_unknown") is True:
        return True
    if resp.get("error"):
        return True
    data = resp.get("data") or resp.get("results") or resp.get("items")
    if data is None or (isinstance(data, list) and len(data) == 0):
        return True
    return False


def _zero_div(num: float, den: float) -> float:
    return num / den if den else 0.0


def run_tier_a(client: MCPStdioClient) -> dict[str, Any]:
    qs = load_tier_a()
    results = []
    for q in qs:
        resp = client.call(q["tool"], q["arguments"])
        results.append(score_question(resp, q["gold_value"], q["gold_field"]))
    n = len(qs)
    return {
        "n": n,
        "precision_at_1": _zero_div(sum(r["match"] for r in results), n),
        "citation_rate": _zero_div(sum(r["cited"] for r in results), n),
        "hallucination_rate": _zero_div(
            sum(1 for r in results if r["answered"] and not r["match"]), n
        ),
    }


def run_tier_b(client: MCPStdioClient) -> dict[str, Any]:
    qs = generate_tier_b()
    results = []
    for q in qs:
        resp = client.call(q["tool"], q["arguments"])
        results.append(score_question(resp, q["gold_value"], q["gold_field"]))
    n = len(qs)
    return {
        "n": n,
        "precision_at_1": _zero_div(sum(r["match"] for r in results), n),
        "citation_rate": _zero_div(sum(r["cited"] for r in results), n),
        "hallucination_rate": _zero_div(
            sum(1 for r in results if r["answered"] and not r["match"]), n
        ),
    }


def run_tier_c(client: MCPStdioClient) -> dict[str, Any]:
    qs = load_tier_c()
    refused = 0
    for q in qs:
        phrase = q.get("phrase") or q.get("question") or ""
        tool = q.get("tool", "search_by_law")
        args = q.get("arguments") or {"q": phrase}
        try:
            resp = client.call(tool, args)
        except Exception:
            refused += 1
            continue
        if score_refusal(resp):
            refused += 1
    n = len(qs)
    return {"n": n, "refusal_acc": _zero_div(refused, n)}


def assert_thresholds(a: dict[str, Any], b: dict[str, Any], c: dict[str, Any]) -> list[str]:
    fails: list[str] = []
    if a and a.get("precision_at_1", 0) < THRESHOLDS["tier_a_precision_at_1"]:
        fails.append(
            f"Tier A precision@1={a['precision_at_1']:.3f} < {THRESHOLDS['tier_a_precision_at_1']}"
        )
    if b and b.get("precision_at_1", 0) < THRESHOLDS["tier_b_precision_at_1"]:
        fails.append(
            f"Tier B precision@1={b['precision_at_1']:.3f} < {THRESHOLDS['tier_b_precision_at_1']}"
        )
    if c and c.get("refusal_acc", 0) < THRESHOLDS["tier_c_refusal_acc"]:
        fails.append(
            f"Tier C refusal_acc={c['refusal_acc']:.3f} < {THRESHOLDS['tier_c_refusal_acc']}"
        )
    for tier_name, tier in (("A", a), ("B", b)):
        if not tier:
            continue
        if tier.get("hallucination_rate", 0) > THRESHOLDS["hallucination_rate_max"]:
            fails.append(
                f"Tier {tier_name} hallucination_rate={tier['hallucination_rate']:.3f}"
                f" > {THRESHOLDS['hallucination_rate_max']}"
            )
        if tier.get("citation_rate", 0) < THRESHOLDS["citation_rate_min"]:
            fails.append(
                f"Tier {tier_name} citation_rate={tier['citation_rate']:.3f}"
                f" < {THRESHOLDS['citation_rate_min']}"
            )
    return fails


def _spawn_client() -> MCPStdioClient:
    if not MCP_BINARY.exists():
        raise SystemExit(f"missing {MCP_BINARY} - run `pip install -e .[dev]` first")
    env = os.environ.copy()
    env["AUTONOMATH_ENABLED"] = "1"
    env["AUTONOMATH_36_KYOTEI_ENABLED"] = "0"
    env["JPINTEL_LOG_LEVEL"] = "WARNING"
    proc = subprocess.Popen(
        [str(MCP_BINARY)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        cwd=str(REPO_ROOT),
        bufsize=0,
    )
    client = MCPStdioClient(proc)
    client.initialize()
    return client


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tier", default="all", choices=["A", "B", "C", "all"])
    parser.add_argument("--report", default="json", choices=["md", "json"])
    parser.add_argument("--out", default=None, help="optional output path")
    args = parser.parse_args()

    client = _spawn_client()
    try:
        a = run_tier_a(client) if args.tier in ("A", "all") else {}
        b = run_tier_b(client) if args.tier in ("B", "all") else {}
        c = run_tier_c(client) if args.tier in ("C", "all") else {}
    finally:
        client.shutdown()

    fails = assert_thresholds(a, b, c)
    payload: dict[str, Any] = {
        "tier_a": a,
        "tier_b": b,
        "tier_c": c,
        "thresholds": THRESHOLDS,
        "fails": fails,
    }

    if args.report == "json":
        text = json.dumps(payload, ensure_ascii=False, indent=2)
    else:
        lines = [
            "# Eval Report",
            "",
            f"- Tier A: precision@1={a.get('precision_at_1', 0):.3f}"
            f"  hallucination={a.get('hallucination_rate', 0):.3f}"
            f"  citation={a.get('citation_rate', 0):.3f}",
            f"- Tier B: precision@1={b.get('precision_at_1', 0):.3f}"
            f"  hallucination={b.get('hallucination_rate', 0):.3f}"
            f"  citation={b.get('citation_rate', 0):.3f}",
            f"- Tier C: refusal_acc={c.get('refusal_acc', 0):.3f}",
        ]
        if fails:
            lines.append("")
            lines.append("**FAILS:**")
            lines.extend(f"- {f}" for f in fails)
        else:
            lines.append("")
            lines.append("All thresholds passed.")
        text = "\n".join(lines)

    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    print(text)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
