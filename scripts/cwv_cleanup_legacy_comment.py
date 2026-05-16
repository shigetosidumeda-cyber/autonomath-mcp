#!/usr/bin/env python3
"""One-shot cleanup: removes the `legacy CDN font` HTML audit comments inserted
by an early run of `cwv_hardening_patch.py`. The CDN link itself is already
replaced — only the comment-marker line remains, and that line still matches
`grep -c "fonts.googleapis" site/*.html`, which the audit relies on. The
canonical hardening patch no longer inserts this comment going forward
(`scripts/cwv_hardening_patch.py` was updated to drop the marker).
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SITE = REPO / "site"

# Matches the audit-comment line including the trailing newline. The inner
# <link> tag contains `>` characters, so we use a non-greedy `.*?` with DOTALL.
COMMENT_RE = re.compile(
    r"<!-- legacy CDN font \(kept for audit, self-host below\):.*?-->\n?",
    re.DOTALL,
)


def main() -> int:
    targets = []
    targets.extend(sorted(SITE.glob("*.html")))
    for sub in (
        "_templates",
        "blog",
        "cases",
        "integrations",
        "audiences",
        "industries",
        "prefectures",
        "programs",
        "cross",
        "qa",
        "news",
        "compare",
    ):
        sd = SITE / sub
        if sd.is_dir():
            targets.extend(sorted(sd.rglob("*.html")))
    n_cleaned = 0
    for path in targets:
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        new = COMMENT_RE.sub("", text)
        if new != text:
            path.write_text(new, encoding="utf-8")
            n_cleaned += 1
    print(f"cleaned {n_cleaned} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
