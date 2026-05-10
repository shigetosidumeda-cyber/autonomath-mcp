#!/usr/bin/env python3
"""check_fence_count: strict fence-count drift detector across site/** + docs/**.

LLM 呼出ゼロ。Scans for `N業法` patterns where N ∈ {5,6,7,8} (and the literal
`5+1業法` variant) and flags any occurrence where N != guards.fence_count_canonical.
Public surface (site/) is already covered by check_publish_text.py; this script
applies the same canonical check to docs/ as well, so internal handoff copy
does not contradict the registry.
"""
from __future__ import annotations

import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
REGISTRY = ROOT / "data" / "facts_registry.json"

PATTERN = re.compile(r"(5\s*\+\s*1|[5-8])\s*業法")


def main() -> int:
    reg = json.loads(REGISTRY.read_text("utf-8"))
    canon = reg["guards"]["fence_count_canonical"]

    targets: list[pathlib.Path] = []
    for sub in ("site", "docs"):
        d = ROOT / sub
        if d.exists():
            targets.extend(d.rglob("*.html"))
            targets.extend(d.rglob("*.md"))
            targets.extend(d.rglob("*.txt"))

    drifts: list[str] = []
    for f in targets:
        if not f.is_file():
            continue
        try:
            text = f.read_text("utf-8", errors="ignore")
        except OSError:
            continue
        rel = f.relative_to(ROOT)
        for m in PATTERN.finditer(text):
            raw = m.group(1)
            # Normalize "5+1" to 6.
            if "+" in raw:
                n = 6
                token = "5+1業法"
            else:
                n = int(raw)
                token = f"{n}業法"
            if n != canon:
                ctx = text[max(0, m.start() - 20) : m.end() + 20].replace("\n", " ")
                drifts.append(f"{rel}:{m.start()} FENCE {token} != canonical {canon}業法 ctx={ctx!r}")

    if drifts:
        for d in drifts[:50]:
            print("FAIL", d)
        if len(drifts) > 50:
            print(f"... and {len(drifts) - 50} more")
        print(f"\n{len(drifts)} fence_count drifts (canonical={canon})")
        return 1
    print(f"OK: no fence_count drifts (canonical={canon})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
