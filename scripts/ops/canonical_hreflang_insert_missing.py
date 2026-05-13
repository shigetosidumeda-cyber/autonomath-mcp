#!/usr/bin/env python3
"""Insert missing `hreflang="ja"` + `hreflang="x-default"` `<link rel="alternate">`
tags into pages flagged by `canonical_hreflang_audit.py` as HREFLANG_MISSING.

Only handles the simple case:
    canonical present, no /en/ peer, no hreflang at all → insert ja + x-default
    both pointing at canonical, immediately after the canonical <link>.

Refuses to touch files that already have any hreflang attribute (some pages
may have a non-canonical hreflang we don't want to silently augment).

Usage:
    python3 scripts/ops/canonical_hreflang_insert_missing.py \
        --report /tmp/canonical_audit.json [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

SITE_ROOT = Path(__file__).resolve().parents[2] / "site"

CANONICAL_RE = re.compile(r'<link\s+rel=["\']canonical["\']\s+href=["\']([^"\']+)["\']\s*/?>')
HREFLANG_RE = re.compile(r'<link[^>]+rel=["\']alternate["\'][^>]*hreflang=')


def insert_for(rel: str, canonical: str | None) -> tuple[bool, str | None]:
    """Returns (changed, reason_if_skip)."""
    full = SITE_ROOT / rel
    try:
        text = full.read_text(encoding="utf-8")
    except OSError as exc:
        return False, f"read_error: {exc}"

    # Only handle the "no hreflang at all" case to avoid clashing with
    # partial-hreflang pages.
    if HREFLANG_RE.search(text):
        return False, "has_some_hreflang"

    m = CANONICAL_RE.search(text)
    if not m:
        return False, "no_canonical_match"
    canon_url = m.group(1)
    # Use the canonical actually present in the file (in case audit drift).
    insertion = (
        f'\n<link rel="alternate" hreflang="ja" href="{canon_url}">'
        f'\n<link rel="alternate" hreflang="x-default" href="{canon_url}">'
    )
    new_text = text[: m.end()] + insertion + text[m.end() :]
    full.write_text(new_text, encoding="utf-8")
    return True, None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--report", type=Path, required=True)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    data = json.loads(args.report.read_text(encoding="utf-8"))

    targets: list[tuple[str, str | None]] = []
    for v in data["violations"]:
        if v["code"] != "HREFLANG_MISSING":
            continue
        if v.get("has_en_peer"):
            continue
        present = v.get("present") or []
        if present:
            # already has some hreflang, skip (insertion not safe).
            continue
        targets.append((v["path"], None))

    inserted = 0
    skipped: dict[str, int] = {}
    for rel, _ in targets:
        if args.dry_run:
            full = SITE_ROOT / rel
            try:
                text = full.read_text(encoding="utf-8")
            except OSError:
                skipped["read_error"] = skipped.get("read_error", 0) + 1
                continue
            if HREFLANG_RE.search(text):
                skipped["has_some_hreflang"] = skipped.get("has_some_hreflang", 0) + 1
                continue
            if not CANONICAL_RE.search(text):
                skipped["no_canonical"] = skipped.get("no_canonical", 0) + 1
                continue
            inserted += 1
            print(f"[dry]  {rel}")
            continue
        changed, reason = insert_for(rel, None)
        if changed:
            inserted += 1
            print(f"[ins]  {rel}")
        else:
            skipped[reason or "unknown"] = skipped.get(reason or "unknown", 0) + 1

    print(
        f"\n[insert] candidates={len(targets)} "
        f"inserted={inserted} skipped={skipped} "
        f"({'DRY-RUN' if args.dry_run else 'WRITTEN'})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
