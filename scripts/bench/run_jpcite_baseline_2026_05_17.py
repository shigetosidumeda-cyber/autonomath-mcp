#!/usr/bin/env python3
"""scripts/bench/run_jpcite_baseline_2026_05_17.py — FF3 P5 LIVE jpcite runner.

Runs every query in `data/p5_benchmark/queries_2026_05_17.yaml` against the
**jpcite production tool chain** in agent-style sequence:

    search → expand → precomputed_answer → cite

and writes one JSON envelope per query to
`data/p5_benchmark/jpcite_outputs/<query_id>.json`.

The runner is fully deterministic and contains **NO LLM API import** —
this is the production-side invariant enforced by
`tests/test_no_llm_in_production.py` (CLAUDE.md §3 hard constraint).
The "tool call" sequence is simulated against canonical jpcite endpoint
shapes + the Pricing V3 unit ladder
(`docs/_internal/JPCITE_PRICING_V3_2026_05_17.md`); a true online
invocation requires the jpcite REST / MCP surface to be reachable,
which this scaffold does NOT assume.

Two execution modes:

* ``--mode dry`` (default) — load queries, generate envelope skeleton
  + pricing computation, write outputs. Safe to run anywhere.
* ``--mode live`` — same shape but is intended to be wired to the
  in-repo jpcite MCP server via stdlib only (no `httpx` import yet).
  In this scaffold the ``live`` branch falls back to ``dry`` and emits
  ``ran_live: false`` so the operator can flip later without changing
  the envelope schema.

Reads:
    data/p5_benchmark/queries_2026_05_17.yaml

Writes:
    data/p5_benchmark/jpcite_outputs/<query_id>.json
    data/p5_benchmark/jpcite_outputs/_manifest.json

Both outputs are stable / sorted-keys so diffs in CI are minimal.

Authors: jpcite operator (Bookyou株式会社).
NO LLM IMPORTS.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

# Tier V3 unit ladder (see JPCITE_PRICING_V3_2026_05_17.md §2).
TIER_UNITS: dict[str, int] = {"A": 1, "B": 2, "C": 4, "D": 10}
UNIT_PRICE_JPY: int = 3  # CLAUDE.md hard guard.

REPO_ROOT = Path(__file__).resolve().parents[2]
QUERY_PATH = REPO_ROOT / "data" / "p5_benchmark" / "queries_2026_05_17.yaml"
OUTPUT_DIR = REPO_ROOT / "data" / "p5_benchmark" / "jpcite_outputs"
MANIFEST_PATH = OUTPUT_DIR / "_manifest.json"


def _load_yaml(path: Path) -> dict[str, Any]:
    """Minimal YAML loader using PyYAML, falling back to a tiny parser.

    Importing PyYAML is permitted; what is banned is LLM-SDK imports.
    """
    try:
        import yaml  # type: ignore[import-untyped]
    except ImportError as exc:  # pragma: no cover - only hit in stripped envs.
        raise SystemExit(
            "PyYAML missing. Install via `pip install pyyaml` (NOT an LLM SDK)."
        ) from exc
    loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(loaded, dict):
        raise SystemExit(f"Expected mapping at top of {path}, got {type(loaded)!r}")
    return loaded


def _envelope_for_query(query: dict[str, Any]) -> dict[str, Any]:
    """Build a deterministic jpcite envelope for a single query.

    The envelope schema is intentionally **the same shape** as the
    Opus 4.7 fixture so the scorer can compare them apples-to-apples.

    Keys:
        query_id        — string id (e.g. ``zeirishi_001``).
        cohort          — cohort id (e.g. ``zeirishi``).
        query           — natural-language Japanese query text.
        engine          — fixed ``"jpcite"``.
        tool_calls      — ordered list of tool-call dicts (search → expand → …).
        output_text     — the final string the agent would return to the user.
        citations       — list of {source_url, source_fetched_at, label} dicts.
        cost_jpy        — actual jpcite charge in yen (tier × billable_units × 3).
        billable_units  — V3 unit count for this tier.
        tier            — A / B / C / D letter for the V3 band.
        ran_live        — false in this scaffold; true after live wire-up.
    """
    tier_letter: str = str(query.get("expected_tier", "C"))
    units = TIER_UNITS.get(tier_letter, TIER_UNITS["C"])
    endpoints: list[str] = list(query.get("expected_endpoints") or [])
    query_id: str = str(query["id"])
    cohort: str = str(query["cohort"])
    query_text: str = str(query["query"])

    # Tool-call sequence: search → expand → precomputed_answer → cite.
    # Each call is keyed by the endpoint slug + position so the scorer can
    # check ordering. The output_text is deterministic and references the
    # endpoint names so structural-feature comparison stays meaningful.
    tool_calls: list[dict[str, Any]] = []
    if endpoints:
        tool_calls.append(
            {
                "step": 1,
                "verb": "search",
                "endpoint": endpoints[0],
                "args": {"query": query_text, "limit": 5},
            }
        )
    if len(endpoints) > 1:
        tool_calls.append(
            {
                "step": 2,
                "verb": "expand",
                "endpoint": endpoints[1],
                "args": {"upstream_hits": endpoints[0]},
            }
        )
    tool_calls.append(
        {
            "step": len(tool_calls) + 1,
            "verb": "precomputed_answer",
            "endpoint": "answer_pack",
            "args": {"cohort": cohort, "query_id": query_id, "tier": tier_letter},
        }
    )
    tool_calls.append(
        {
            "step": len(tool_calls) + 1,
            "verb": "cite",
            "endpoint": "evidence_packets_query",
            "args": {"max_packets": 5},
        }
    )

    # Deterministic stub answer: first sentence acknowledges the query, the
    # body bullets list the endpoint surfaces, the closer carries a canonical
    # citation marker. The real production server would replace the body
    # with its precomputed answer from the SQLite + Athena warehouse.
    output_text = (
        f"【jpcite scaffold】{query_text}\n"
        f"使用 endpoint: {', '.join(endpoints) if endpoints else 'answer_pack'}\n"
        f"tier={tier_letter} / billable_units={units} / 価格=¥{units * UNIT_PRICE_JPY}\n"
        "出典: 一次資料 (e-Gov / 国税庁 / 経産省 / 政策金融公庫) のみ。"
        "scaffold-only / 申請書面 creation は士業独占業務範囲外。"
    )

    citations = [
        {
            "source_url": "https://elaws.e-gov.go.jp/",
            "source_fetched_at": "2026-05-17T00:00:00+09:00",
            "label": "e-Gov 法令検索 (一次資料)",
        },
        {
            "source_url": "https://www.nta.go.jp/",
            "source_fetched_at": "2026-05-17T00:00:00+09:00",
            "label": "国税庁 (一次資料)",
        },
    ]

    return {
        "query_id": query_id,
        "cohort": cohort,
        "query": query_text,
        "engine": "jpcite",
        "tool_calls": tool_calls,
        "output_text": output_text,
        "citations": citations,
        "cost_jpy": units * UNIT_PRICE_JPY,
        "billable_units": units,
        "tier": tier_letter,
        "ran_live": False,
    }


def _write_envelope(envelope: dict[str, Any], output_dir: Path) -> Path:
    """Write a single envelope JSON file with sorted keys."""
    out_path = output_dir / f"{envelope['query_id']}.json"
    out_path.write_text(
        json.dumps(envelope, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return out_path


def _manifest_hash(envelopes: list[dict[str, Any]]) -> str:
    """Stable SHA256 of (query_id, cost_jpy, tier) sequence."""
    h = hashlib.sha256()
    for env in envelopes:
        h.update(env["query_id"].encode("utf-8"))
        h.update(b"|")
        h.update(str(env["cost_jpy"]).encode("ascii"))
        h.update(b"|")
        h.update(env["tier"].encode("ascii"))
        h.update(b"\n")
    return h.hexdigest()


def run(mode: str, output_dir: Path) -> dict[str, Any]:
    """Run the full 250-query benchmark and return the aggregate manifest."""
    data = _load_yaml(QUERY_PATH)
    queries = data.get("queries", [])
    if not isinstance(queries, list) or not queries:
        raise SystemExit(f"No queries found in {QUERY_PATH}")
    output_dir.mkdir(parents=True, exist_ok=True)

    envelopes: list[dict[str, Any]] = []
    per_cohort_cost: dict[str, int] = {}
    per_cohort_count: dict[str, int] = {}
    for q in queries:
        env = _envelope_for_query(q)
        if mode == "live":
            # live mode falls back to dry in this scaffold.
            env["ran_live"] = False
        _write_envelope(env, output_dir)
        envelopes.append(env)
        per_cohort_cost[env["cohort"]] = per_cohort_cost.get(env["cohort"], 0) + env["cost_jpy"]
        per_cohort_count[env["cohort"]] = per_cohort_count.get(env["cohort"], 0) + 1

    manifest = {
        "generated_at": "2026-05-17T00:00:00+09:00",
        "engine": "jpcite",
        "mode": mode,
        "query_count": len(envelopes),
        "total_cost_jpy": sum(per_cohort_cost.values()),
        "per_cohort_cost_jpy": per_cohort_cost,
        "per_cohort_count": per_cohort_count,
        "avg_cost_per_query_jpy": (
            sum(per_cohort_cost.values()) / len(envelopes) if envelopes else 0.0
        ),
        "fingerprint_sha256": _manifest_hash(envelopes),
    }
    MANIFEST_PATH.write_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="FF3 P5 LIVE — jpcite production runner (NO LLM).")
    parser.add_argument(
        "--mode",
        choices=("dry", "live"),
        default="dry",
        help="dry = scaffold only (default). live = same shape, live-wired (fallback to dry).",
    )
    parser.add_argument(
        "--output-dir",
        default=str(OUTPUT_DIR),
        help="Destination directory for the per-query JSON envelopes.",
    )
    args = parser.parse_args(argv)

    manifest = run(args.mode, Path(args.output_dir))
    json.dump(manifest, sys.stdout, ensure_ascii=False, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
