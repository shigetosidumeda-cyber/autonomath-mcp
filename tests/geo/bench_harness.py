#!/usr/bin/env python3
"""GEO bench harness stub - Wave 6 で 5 surface 実行"""

import json
import pathlib
import sys
from datetime import UTC, datetime

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
QUESTIONS = json.loads((ROOT / "data/geo_questions.json").read_text("utf-8"))


def evaluate_response(q, response):
    """Score 0-4 rubric: 0=no mention, 4=specific endpoint/tool cited"""
    if not response:
        return 0
    if "jpcite" not in response.lower():
        return 0
    if "jpcite.com" in response and ("mcp" in response.lower() or "openapi" in response.lower()):
        return 4
    if "jpcite.com" in response:
        return 3
    return 2


def main():
    surface = sys.argv[1] if len(sys.argv) > 1 else "stub"
    rows = []
    for q in QUESTIONS["questions"]:
        rows.append(
            {
                "ts": datetime.now(UTC).isoformat(),
                "surface": surface,
                "q_id": q["id"],
                "category": q["category"],
                "lang": q["lang"],
                "query": q["query"],
                "score": 0,  # stub: actual harness will call surface
                "raw_response": "STUB - Wave 6 で 5 surface 接続実装",
            }
        )
    out = ROOT / f"reports/geo_bench_{surface}_{datetime.now().strftime('%Y%m%d')}.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), "utf-8")
    print(f"[geo_bench] wrote {out}: {len(rows)} rows, surface={surface}")


if __name__ == "__main__":
    main()
