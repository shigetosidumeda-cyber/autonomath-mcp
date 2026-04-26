#!/usr/bin/env python3
"""jpintel-mcp eval runner.

Loads `gold.yaml`, calls each MCP tool with the gold query's `tool_args`
against a real `data/jpintel.db`, computes precision@10, and prints a
table.

Exit code:
  0 — every query met its `min_precision_at_10` threshold.
  1 — at least one query failed.

Usage:

    # Run from repo root with the project venv active
    .venv/bin/python evals/run.py

    # Or with a different DB path
    JPINTEL_DB=/path/to/your.db .venv/bin/python evals/run.py

    # JSON output (CI-friendly)
    .venv/bin/python evals/run.py --json

    # Run a subset (substring match on id)
    .venv/bin/python evals/run.py --filter agri_

The runner does NOT mock the database. It hits the same code path that the
production stdio MCP server hits, so a regression in tool implementation
shows up here. See README.md for how to add a new gold query.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any

import yaml

# Make sure src/ is on the path so we import the live tool modules, not a
# stale wheel.
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "src"))

# Default DB path (override with JPINTEL_DB env var).
os.environ.setdefault("JPINTEL_DB", str(_REPO_ROOT / "data" / "jpintel.db"))

# Quieten the per-call telemetry logger so the table is readable.
logging.disable(logging.WARNING)

from jpintel_mcp.mcp import server as mcp_server  # noqa: E402

GOLD_YAML = Path(__file__).resolve().parent / "gold.yaml"


def _extract_ids(tool_name: str, results: list[dict[str, Any]]) -> list[str]:
    """Pull the comparable ID out of each result row.

    Different tools key on different columns:
      - search_programs / prescreen_programs → unified_id
      - search_case_studies                  → case_id
      - search_loan_programs                 → id (int → str)
      - search_tax_rules                     → unified_id ("TAX-...")
      - search_enforcement_cases             → case_id
      - search_invoice_registrants           → houjin_bangou
    """
    if tool_name == "search_loan_programs":
        return [str(r.get("id")) for r in results]
    if tool_name in ("search_case_studies", "search_enforcement_cases"):
        return [str(r.get("case_id")) for r in results]
    if tool_name == "search_invoice_registrants":
        return [
            str(r.get("houjin_bangou") or r.get("invoice_registration_number"))
            for r in results
        ]
    # search_programs, prescreen_programs, search_tax_rules,
    # search_laws, search_court_decisions, etc. — all use unified_id.
    return [str(r.get("unified_id")) for r in results]


def _run_tool(tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
    fn = getattr(mcp_server, tool_name, None)
    if fn is None:
        raise AttributeError(f"unknown MCP tool: {tool_name}")
    return fn(**args)


def precision_at_k(actual: list[str], expected: set[str], k: int = 10) -> float:
    if not actual:
        return 0.0
    top = actual[:k]
    if not top:
        return 0.0
    hits = sum(1 for a in top if a in expected)
    return hits / len(top)


def evaluate_query(query: dict[str, Any]) -> dict[str, Any]:
    """Run one gold query and produce a result row."""
    qid = query["id"]
    tool_name = query["tool_name"]
    tool_args = dict(query.get("tool_args") or {})
    expected = set(map(str, query.get("expected_ids") or []))
    forbidden = set(map(str, query.get("forbidden_ids") or []))
    min_precision = float(query.get("min_precision_at_10", 0.5))
    note = (query.get("note") or "").strip().splitlines()[0:1]

    t0 = time.perf_counter()
    try:
        payload = _run_tool(tool_name, tool_args)
    except Exception as exc:  # pragma: no cover — surfaced in result row
        return {
            "id": qid,
            "tool": tool_name,
            "status": "error",
            "error": f"{type(exc).__name__}: {exc}",
            "precision_at_10": 0.0,
            "min_required": min_precision,
            "passed": False,
            "latency_ms": int((time.perf_counter() - t0) * 1000),
            "note": note[0] if note else "",
        }
    elapsed = (time.perf_counter() - t0) * 1000

    # dd_profile_am returns a single object, not a `results` list — handled
    # specially: pass if the entity record came back populated.
    if tool_name == "dd_profile_am":
        ok = bool(payload.get("entity")) or bool(payload.get("adoptions"))
        return {
            "id": qid,
            "tool": tool_name,
            "status": "ok" if ok else "fail",
            "precision_at_10": 1.0 if ok else 0.0,
            "min_required": min_precision,
            "passed": ok or min_precision == 0.0,
            "actual_top": [],
            "expected_count": 0,
            "total": None,
            "latency_ms": int(elapsed),
            "note": note[0] if note else "",
        }

    results = payload.get("results") or []
    actual_ids = _extract_ids(tool_name, results)
    p10 = precision_at_k(actual_ids, expected, k=10)

    # Forbidden IDs trump everything: if any appear in top-K, the query
    # fails irrespective of precision.
    forbidden_hit = [aid for aid in actual_ids[:10] if aid in forbidden]

    # Special case: queries with `expected_ids: []` and `min_precision_at_10:
    # 0.0` are diagnostic queries (edge cases, dd_profile). They pass as
    # long as the tool didn't crash and didn't violate forbidden_ids.
    if not expected and min_precision == 0.0:
        passed = not forbidden_hit
    else:
        passed = p10 >= min_precision and not forbidden_hit

    # For edge_001 (unknown prefecture) we *also* want to verify the warning
    # shape — the runner reports it, but doesn't gate pass/fail on it.
    extra: dict[str, Any] = {}
    if payload.get("input_warnings"):
        extra["input_warnings_codes"] = [
            w.get("code") for w in payload["input_warnings"]
        ]

    return {
        "id": qid,
        "tool": tool_name,
        "status": "fail_forbidden" if forbidden_hit else ("pass" if passed else "fail"),
        "precision_at_10": round(p10, 3),
        "min_required": min_precision,
        "passed": passed,
        "forbidden_hit": forbidden_hit,
        "actual_top": actual_ids[:10],
        "expected_count": len(expected),
        "total": payload.get("total"),
        "latency_ms": int(elapsed),
        "note": note[0] if note else "",
        **extra,
    }


def _print_table(rows: list[dict[str, Any]]) -> None:
    headers = ["id", "tool", "p@10", "min", "total", "ms", "status"]
    widths = [
        max(len(str(r.get(h, ""))) for r in rows + [{h: h} for h in headers])
        for h in ["id", "tool", "precision_at_10", "min_required", "total", "latency_ms", "status"]
    ]
    # Cap a few columns
    widths[0] = max(widths[0], 30)
    widths[1] = max(widths[1], 22)

    def _fmt(values: list[str]) -> str:
        return "  ".join(v.ljust(w) for v, w in zip(values, widths))

    print(_fmt(headers))
    print(_fmt(["-" * w for w in widths]))
    for r in rows:
        print(
            _fmt(
                [
                    str(r["id"]),
                    str(r["tool"]),
                    f"{r['precision_at_10']:.2f}",
                    f"{r['min_required']:.2f}",
                    str(r.get("total") or ""),
                    str(r.get("latency_ms") or 0),
                    r["status"],
                ]
            )
        )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--gold",
        type=Path,
        default=GOLD_YAML,
        help="Path to gold.yaml (default: ./gold.yaml).",
    )
    p.add_argument(
        "--filter",
        type=str,
        default="",
        help="Substring filter on query id (e.g. 'agri_' / 'pref_').",
    )
    p.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON instead of a human table (one object per query + summary).",
    )
    p.add_argument(
        "--strict",
        action="store_true",
        help="Treat any failure as exit 1 (default: same).",
    )
    args = p.parse_args(argv)

    gold = yaml.safe_load(args.gold.read_text(encoding="utf-8"))
    queries = gold.get("queries") or []
    if args.filter:
        queries = [q for q in queries if args.filter in q.get("id", "")]

    if not queries:
        print(f"no queries matched filter '{args.filter}'", file=sys.stderr)
        return 2

    rows: list[dict[str, Any]] = []
    for q in queries:
        rows.append(evaluate_query(q))

    passed = sum(1 for r in rows if r["passed"])
    failed = len(rows) - passed
    summary = {
        "total": len(rows),
        "passed": passed,
        "failed": failed,
        "pass_rate": round(passed / len(rows), 3) if rows else 0.0,
        "db": os.environ.get("JPINTEL_DB"),
    }

    if args.json:
        print(json.dumps({"summary": summary, "results": rows}, ensure_ascii=False, indent=2))
    else:
        _print_table(rows)
        print()
        print(f"DB:           {summary['db']}")
        print(f"Total queries: {summary['total']}")
        print(f"Passed:        {summary['passed']}")
        print(f"Failed:        {summary['failed']}")
        print(f"Pass rate:     {summary['pass_rate']:.1%}")
        if failed:
            print()
            print("Failures:")
            for r in rows:
                if r["passed"]:
                    continue
                expected_count = r.get("expected_count", 0)
                actual = r.get("actual_top", [])
                print(
                    f"  - {r['id']:<32} p@10={r['precision_at_10']:.2f} "
                    f"(min={r['min_required']:.2f}) status={r['status']}"
                )
                if r.get("forbidden_hit"):
                    print(f"      forbidden_hit: {r['forbidden_hit']}")
                if r.get("error"):
                    print(f"      error: {r['error']}")
                if actual and expected_count:
                    print(f"      actual_top:    {actual[:5]}{'...' if len(actual) > 5 else ''}")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
