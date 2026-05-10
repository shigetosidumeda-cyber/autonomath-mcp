#!/usr/bin/env python3
"""scan_publish_surface: publish surface numeric facts drift detector.

LLM 呼出ゼロ。For each publishable numeric fact in data/facts_registry.json,
scan site/**/*.html for occurrences of <key><non-digit><number>, and if any
occurrence's value disagrees with the registry value AND falls outside the
declared numeric_range, report a drift.
"""
from __future__ import annotations

import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
REGISTRY = ROOT / "data" / "facts_registry.json"


def main() -> int:
    reg = json.loads(REGISTRY.read_text("utf-8"))
    ranges = reg["guards"]["numeric_ranges"]
    facts_by_key = {f["key"]: f for f in reg["facts"] if f.get("publishable")}

    targets = list((ROOT / "site").rglob("*.html"))
    drifts: list[str] = []

    for f in targets:
        if not f.is_file():
            continue
        try:
            text = f.read_text("utf-8", errors="ignore")
        except OSError:
            continue
        rel = f.relative_to(ROOT)
        for key, fact in facts_by_key.items():
            expected = fact.get("value")
            if not isinstance(expected, (int, float)):
                continue
            for m in re.finditer(rf"{re.escape(key)}\D{{0,8}}(\d[\d,]+)", text):
                got = int(m.group(1).replace(",", ""))
                rng = ranges.get(key)
                in_range = rng is None or (rng[0] <= got <= rng[1])
                if got != int(expected) and not in_range:
                    drifts.append(
                        f"{rel}:{m.start()} {key} got={got} registry={expected} range={rng}"
                    )

    if drifts:
        for d in drifts[:50]:
            print("DRIFT", d)
        print(f"\n{len(drifts)} publish_surface drifts")
        return 1
    print("OK: no publish_surface drifts")
    return 0


if __name__ == "__main__":
    sys.exit(main())
