#!/usr/bin/env python3
"""Annotate composite-vs-naive benchmark rows with result provenance.

The benchmark intentionally mixes three row classes:

* ``real``: at least one live API call returned 200 and contributed wall-clock data.
* ``synth``: modeled composite endpoint rows that are not live routes yet.
* ``fallback``: real-route rows whose HTTP timing fell back to calibrated latency.

Token and USD columns are deterministic estimates, so their column-level
``*_kind`` fields are ``synth`` even when the row has a live timing sample.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RESULTS = ROOT / "benchmarks" / "composite_vs_naive" / "results.jsonl"

SYNTH_COMPOSITE_SCENARIOS = {
    "eligibility_lookup",
    "amendment_diff",
    "similar_programs",
    "citation_pack",
}


def _row_result_kind(row: dict[str, Any]) -> str:
    if int(row.get("real_calls") or 0) > 0:
        return "real"
    if row.get("mode") == "composite" and row.get("scenario") in SYNTH_COMPOSITE_SCENARIOS:
        return "synth"
    return "fallback"


def annotate_row(row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    result_kind = _row_result_kind(out)
    out["result_kind"] = result_kind
    out["wall_ms_kind"] = "real" if result_kind == "real" else "synth"
    out["tokens_kind"] = "synth"
    out["cost_kind"] = "synth"
    return out


def annotate_file(path: Path) -> dict[str, int]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rows.append(annotate_row(json.loads(line)))

    counts = {"real": 0, "synth": 0, "fallback": 0}
    for row in rows:
        counts[str(row["result_kind"])] += 1

    body = "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=False) for row in rows)
    path.write_text(body + ("\n" if body else ""), encoding="utf-8")
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--results",
        type=Path,
        default=DEFAULT_RESULTS,
        help="Path to benchmarks/composite_vs_naive/results.jsonl.",
    )
    args = parser.parse_args()

    counts = annotate_file(args.results)
    print(
        "[annotate_composite_result_kind] "
        f"real={counts['real']} synth={counts['synth']} fallback={counts['fallback']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
