#!/usr/bin/env python3
"""check_fence_count: strict fence-count drift detector across site/** + docs/**.

LLM 呼出ゼロ。Scans for `N業法` patterns where N ∈ {5,6,7,8} (and the literal
`5+1業法` variant) and flags any occurrence where N != guards.fence_count_canonical.
Public surface (site/) is already covered by check_publish_text.py; this script
applies the same canonical check to docs/ as well, so internal handoff copy
does not contradict the registry.

Wave 46 tick5 (2026-05-12): canonical bumped 7→8 to align with the
8-fence inventory (税理士法/弁護士法/公認会計士法/司法書士法/行政書士法/
社労士法/弁理士法/労働基準法 §36) in `data/fence_registry.json`. The script
now honors the registry's `fence_count_allow_in_context_path_prefix` list
(same allowlist already used by `check_publish_text.py`) plus a
`fence_count_context_allow_substrings` ±60-char window — historical handoff
copy that legitimately references prior `5/6/7 業法` counts stays out of the
drift list without forcing surface rewrites. Operator-internal handoff under
`docs/_internal/`, `docs/research/`, `docs/audit/`, `docs/announce/`,
`docs/competitive/`, `docs/learn/`, `docs/pricing/`, `docs/publication/` is
also exempt — that copy describes fence-count evolution + publication drafts
that intentionally cite earlier counts as legacy.
"""

from __future__ import annotations

import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
REGISTRY = ROOT / "data" / "facts_registry.json"

PATTERN = re.compile(r"(5\s*\+\s*1|[5-8])\s*業法")

# Operator-internal + publication-draft scopes that legitimately cite
# historical counts (5/6/7 業法) when describing fence evolution. These
# never reach the public surface — exempting them keeps drift detection
# focused on user-visible copy.
_INTERNAL_DOC_PREFIXES = (
    "docs/_internal/",
    "docs/research/",
    "docs/audit/",
    "docs/announce/",
    "docs/competitive/",
    "docs/learn/",
    "docs/pricing/",
    "docs/publication/",
    "docs/distribution/",
    "docs/geo/",
    "docs/cookbook/",
)


def main() -> int:
    reg = json.loads(REGISTRY.read_text("utf-8"))
    guards = reg["guards"]
    canon = guards["fence_count_canonical"]
    fence_path_prefixes: list[str] = guards.get("fence_count_allow_in_context_path_prefix", [])
    fence_ctx_substrs: list[str] = guards.get("fence_count_context_allow_substrings", [])

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
        rel_posix = rel.as_posix()

        # Skip operator-internal handoff + publication drafts: those
        # legitimately reference legacy 5/6/7 業法 counts when describing
        # fence evolution. User-facing surface remains in scope.
        if any(rel_posix.startswith(p) for p in _INTERNAL_DOC_PREFIXES):
            continue

        # Skip registry-listed user-facing copy that intentionally enumerates
        # the legacy counts (e.g. site/legal-fence.html historical refs,
        # site/trust/* attribution table). Same allowlist as
        # check_publish_text.py.
        if any(rel_posix.startswith(p) for p in fence_path_prefixes):
            continue

        for m in PATTERN.finditer(text):
            raw = m.group(1)
            # Normalize "5+1" to 6.
            if "+" in raw:
                n = 6
                token = "5+1業法"
            else:
                n = int(raw)
                token = f"{n}業法"
            if n == canon:
                continue
            window = text[max(0, m.start() - 60) : m.end() + 60]
            if fence_ctx_substrs and any(sub in window for sub in fence_ctx_substrs):
                continue
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
