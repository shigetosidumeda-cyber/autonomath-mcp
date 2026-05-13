#!/usr/bin/env python3
"""Apply minimal canonical / hreflang / og:url repairs flagged by
`canonical_hreflang_audit.py`.

Reads the JSON report produced by:
    python3 scripts/ops/canonical_hreflang_audit.py --json /tmp/c.json

…and applies in-place fixes ONLY for the high-confidence violation codes:
    OG_URL_MISMATCH
    HREFLANG_JA_MISMATCH
    HREFLANG_EN_MISMATCH
    HREFLANG_XDEFAULT_MISMATCH
    HREFLANG_JA_NOT_CANONICAL
    HREFLANG_X_DEFAULT_NOT_CANONICAL

Each repair is a single occurrence-string-replace inside the file head
(byte-exact match required — bails out if the substring is ambiguous).

Refuses to touch:
    CANONICAL_PATH_MISMATCH         (judgment call, e.g. /artifact → /artifacts)
    CANONICAL_NOT_ABSOLUTE          (one file: getting-started.html — fix manually)
    HREFLANG_MISSING                (insertion, not rewrite — separate task)
    MISSING_CANONICAL               (insertion)
    SITEMAP_LOC_DRIFT               (sitemap-side fix, separate)
    LEGACY_BRAND_IN_*               (zero hits today)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

SITE_ROOT = Path(__file__).resolve().parents[2] / "site"

REWRITE_CODES = {
    "OG_URL_MISMATCH": "og_url_replace",
    "HREFLANG_JA_MISMATCH": "hreflang_ja_replace",
    "HREFLANG_EN_MISMATCH": "hreflang_en_replace",
    "HREFLANG_XDEFAULT_MISMATCH": "hreflang_xdefault_replace",
    "HREFLANG_JA_NOT_CANONICAL": "hreflang_ja_replace_to_canonical",
    "HREFLANG_X_DEFAULT_NOT_CANONICAL": "hreflang_xdefault_replace_to_canonical",
}


def build_replacement(violation: dict[str, Any]) -> tuple[str, str] | None:
    code = violation["code"]
    if code == "OG_URL_MISMATCH":
        # og:url = canonical
        old = violation["og_url"]
        new = violation["canonical"]
        return old, new
    if code in {
        "HREFLANG_JA_MISMATCH",
        "HREFLANG_EN_MISMATCH",
        "HREFLANG_XDEFAULT_MISMATCH",
    }:
        return violation["got"], violation["expected"]
    if code in {
        "HREFLANG_JA_NOT_CANONICAL",
        "HREFLANG_X_DEFAULT_NOT_CANONICAL",
    }:
        return violation["got"], violation["canonical"]
    return None


def apply_repairs(report_path: Path, dry_run: bool = False) -> tuple[int, int]:
    data = json.loads(report_path.read_text(encoding="utf-8"))
    repairs_by_path: dict[str, list[tuple[str, str]]] = {}
    for v in data["violations"]:
        if v["code"] not in REWRITE_CODES:
            continue
        repl = build_replacement(v)
        if repl is None or repl[0] == repl[1]:
            continue
        repairs_by_path.setdefault(v["path"], []).append(repl)

    files_touched = 0
    edits_applied = 0
    for rel, repairs in sorted(repairs_by_path.items()):
        path = SITE_ROOT / rel
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            print(f"[skip] {rel}: {exc}", file=sys.stderr)
            continue
        original = text
        # Apply each replacement; replace only the FIRST occurrence per pair
        # (the head should have at most one matching href value for each
        # hreflang / og:url tag). Skip duplicates if the substring no longer
        # exists after a previous swap.
        seen: set[tuple[str, str]] = set()
        for old, new in repairs:
            key = (old, new)
            if key in seen:
                continue
            seen.add(key)
            count = text.count(old)
            if count == 0:
                # Already fixed in a prior loop iteration (e.g. og:url and
                # hreflang both pointed to the same .html string).
                continue
            text = text.replace(old, new)
            edits_applied += 1
        if text != original:
            files_touched += 1
            if not dry_run:
                path.write_text(text, encoding="utf-8")
                print(f"[fix]  {rel}  edits={len(repairs)}")
            else:
                print(f"[dry]  {rel}  edits={len(repairs)}")
    return files_touched, edits_applied


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--report",
        type=Path,
        required=True,
        help="JSON report produced by canonical_hreflang_audit.py --json ...",
    )
    ap.add_argument("--dry-run", action="store_true", help="Don't write changes.")
    args = ap.parse_args()
    files, edits = apply_repairs(args.report, dry_run=args.dry_run)
    print(
        f"\n[repair] files touched: {files}, total edits: {edits} "
        f"({'DRY-RUN' if args.dry_run else 'WRITTEN'})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
