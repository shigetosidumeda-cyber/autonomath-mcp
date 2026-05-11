#!/usr/bin/env python3
"""publish_text guard: banned terms + numeric out-of-range + fence count drift.

LLM 呼出ゼロ。pure static analysis over site/**/*.html + site/**/*.txt + README.md.
Reads guards from data/facts_registry.json.
Exits 1 on any violation (CI BLOCK).
"""
from __future__ import annotations

import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
REGISTRY = ROOT / "data" / "facts_registry.json"


def main() -> int:
    registry = json.loads(REGISTRY.read_text("utf-8"))
    guards = registry["guards"]
    banned = guards["banned_terms"]
    ranges = guards["numeric_ranges"]
    fence_canon = guards["fence_count_canonical"]

    violations: list[str] = []
    targets = (
        list((ROOT / "site").rglob("*.html"))
        + list((ROOT / "site").rglob("*.txt"))
        + [ROOT / "README.md"]
    )

    for f in targets:
        if not f.exists() or not f.is_file():
            continue
        try:
            text = f.read_text("utf-8", errors="ignore")
        except OSError:
            continue
        rel = f.relative_to(ROOT)

        for item in banned:
            # Backward-compat: accept plain string entries, but new form is
            # {"pattern": "<regex>", "reason": "<label>"} with negative
            # lookbehind/lookahead-aware regex that survives legitimate uses
            # (完全従量, 必ず…ご確認, 個人保証人, No.1 を謳いません, ...).
            if isinstance(item, str):
                pattern = re.escape(item)
                reason = "legacy"
            else:
                pattern = item["pattern"]
                reason = item.get("reason", "banned")
            for m in re.finditer(pattern, text):
                ctx = text[max(0, m.start() - 30) : m.end() + 30].replace("\n", " ")
                violations.append(
                    f"{rel}:{m.start()} BANNED[{reason}] {m.group(0)!r} ctx={ctx!r}"
                )

        for key, (lo, hi) in ranges.items():
            for m in re.finditer(rf"{re.escape(key)}\D{{0,8}}(\d[\d,]+)", text):
                v = int(m.group(1).replace(",", ""))
                if not lo <= v <= hi:
                    violations.append(
                        f"{rel}:{m.start()} NUMERIC {key}={v} not in [{lo},{hi}]"
                    )

        for m in re.finditer(r"([5-8])\s*業法", text):
            n = int(m.group(1))
            if n != fence_canon:
                violations.append(
                    f"{rel}:{m.start()} FENCE {n}業法 != canonical {fence_canon}"
                )

    if violations:
        for v in violations[:50]:
            print("FAIL", v)
        if len(violations) > 50:
            print(f"... and {len(violations) - 50} more")
        print(f"\n{len(violations)} publish_text violations")
        return 1
    print("OK: no publish_text violations")
    return 0


if __name__ == "__main__":
    sys.exit(main())
