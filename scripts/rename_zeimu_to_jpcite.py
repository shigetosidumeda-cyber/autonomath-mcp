#!/usr/bin/env python3
"""One-shot rename: zeimu-kaikei.ai → jpcite.com across src/ Python source.

Strategy (per launch persona walk 2026-04-30):
1. URL replacements globally:
   - https://zeimu-kaikei.ai            → https://jpcite.com
   - https://www.zeimu-kaikei.ai        → https://www.jpcite.com
   - https://api.zeimu-kaikei.ai        → https://api.jpcite.com
   - bare "zeimu-kaikei.ai" (no scheme) → "jpcite.com" (covers docstrings,
     log strings, etc.). Must run AFTER the scheme'd variants so we don't
     double-rewrite.
2. Email default `noreply@zeimu-kaikei.ai` → `noreply@jpcite.com`.
3. CORS allowlist in `config.py`: ADD jpcite origins ALONGSIDE the existing
   zeimu-kaikei origins (legacy must stay listed during transition).
4. Brand strings (e.g. `税務会計AI` user-facing copy in email templates) are
   NOT rewritten by this script — that's a separate copy-edit pass.

Don't touch:
- Comments containing the historical "previously zeimu-kaikei.ai" marker
  (none currently exist; reserved for future audits).
- Test files explicitly testing CORS for the legacy origin (handled in a
  separate test-suite pass).
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"

# Order matters: scheme'd variants first so the bare-domain pass at the end
# doesn't double-rewrite things like "https://jpcite.com.kaikei.ai".
URL_REPLACEMENTS: list[tuple[str, str]] = [
    ("https://api.zeimu-kaikei.ai", "https://api.jpcite.com"),
    ("https://www.zeimu-kaikei.ai", "https://www.jpcite.com"),
    ("https://zeimu-kaikei.ai", "https://jpcite.com"),
    # Bare domain (in docstrings, log lines, User-Agent strings, etc.)
    ("api.zeimu-kaikei.ai", "api.jpcite.com"),
    ("www.zeimu-kaikei.ai", "www.jpcite.com"),
    ("zeimu-kaikei.ai", "jpcite.com"),
    # Email defaults.
    ("noreply@jpcite.com", "noreply@jpcite.com"),  # noop, see below
]

# CORS allowlist append: file → (anchor_string, replacement_string).
# Anchor must be unique. We KEEP the zeimu-kaikei origins in place and ADD
# the jpcite mirrors right above the autonomath.ai entries so the apex+www+api
# triplet stays grouped.
CORS_FILE = SRC / "jpintel_mcp" / "config.py"
CORS_OLD_BLOCK = (
    '            "https://zeimu-kaikei.ai,"\n'
    '            "https://www.zeimu-kaikei.ai,"\n'
    '            "https://api.zeimu-kaikei.ai,"\n'
)
# After URL_REPLACEMENTS run first, the block above will already have been
# rewritten to jpcite.com. We then ADD the legacy zeimu-kaikei entries back
# alongside, so cross-domain redirects continue to work during the transition.
CORS_NEW_BLOCK = (
    '            "https://jpcite.com,"\n'
    '            "https://www.jpcite.com,"\n'
    '            "https://api.jpcite.com,"\n'
    '            "https://zeimu-kaikei.ai,"\n'
    '            "https://www.zeimu-kaikei.ai,"\n'
    '            "https://api.zeimu-kaikei.ai,"\n'
)


def main() -> int:
    targets = sorted(SRC.rglob("*"))
    py_targets = [
        p
        for p in targets
        if p.is_file()
        and p.suffix in {".py", ".html", ".txt"}
        and "zeimu-kaikei" in p.read_text(encoding="utf-8", errors="ignore")
    ]

    total_replacements = 0
    files_changed: list[tuple[str, int]] = []

    for path in py_targets:
        original = path.read_text(encoding="utf-8")
        updated = original
        per_file_count = 0
        for old, new in URL_REPLACEMENTS:
            if old == new:
                continue
            count = updated.count(old)
            if count:
                updated = updated.replace(old, new)
                per_file_count += count

        if updated != original:
            path.write_text(updated, encoding="utf-8")
            files_changed.append((str(path.relative_to(ROOT)), per_file_count))
            total_replacements += per_file_count

    # CORS allowlist: AFTER the URL replacement above, the original zeimu-kaikei
    # block has been transformed to jpcite. We now ADD the legacy zeimu-kaikei
    # origins back as transition-period CORS entries.
    cors_text = CORS_FILE.read_text(encoding="utf-8")
    cors_post_url_rewrite_anchor = (
        '            "https://jpcite.com,"\n'
        '            "https://www.jpcite.com,"\n'
        '            "https://api.jpcite.com,"\n'
    )
    if cors_post_url_rewrite_anchor in cors_text:
        new_cors = cors_text.replace(
            cors_post_url_rewrite_anchor,
            CORS_NEW_BLOCK,
            1,
        )
        if new_cors != cors_text:
            CORS_FILE.write_text(new_cors, encoding="utf-8")
            print(f"[CORS] Added 3 legacy zeimu-kaikei origins to {CORS_FILE.relative_to(ROOT)}")
    else:
        print(
            f"[CORS][WARN] Anchor not found in {CORS_FILE.relative_to(ROOT)} — manual review required"
        )

    print(f"\nTotal files changed: {len(files_changed)}")
    print(f"Total URL replacements: {total_replacements}")
    print("\nPer-file replacement counts:")
    for fname, count in files_changed:
        print(f"  {count:4d}  {fname}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
