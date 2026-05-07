#!/usr/bin/env python3
"""One-shot patcher for the 5 URL-integrity blockers (B3 in LAUNCH_BLOCKERS.md).

The scan at ``scripts/url_integrity_scan.py`` flags 8 URLs across 5
``unified_id``\\s. Each is 本番 blocker under 景品表示法 4/5 条:

    1. UNI-e33d7b0613  栗原市 有機農業機械導入支援事業補助金
       source_url / official_url = ``https://www.example.com/kujihara_yuuki_shinseisho.pdf``
       (synthetic + fabricated filename)

    2. UNI-47b67cba4a  横浜町 合併処理浄化槽設置整備事業補助金
       source_url / official_url = ``https://www.town.yokohama.lg.jp/...``
       (placeholder `...`)

    3. UNI-b0b9565569  横浜町 合併処理浄化槽設置整備事業補助金 (noukaweb dupe)
       same placeholder; same municipal target page as (2).

    4. UNI-81c7fb2813  鳥取 就農条件整備事業
       enriched_json contains a truncated URL fragment ``https://w`` inside
       a nested ``_source_quotes`` entry. The row's source_url column is
       already correct (``https://www.pref.tottori.lg.jp/64862.htm``).

    5. UNI-d8aa2870e3  別海町 酪農就農・移住支援事業
       enriched_json excerpt contains a fullwidth slash URL
       ``http://betsukai-kenboku.jp／FOLLOW`` which ``urlparse`` rejects.
       The row's source_url column is already clean.

Verification performed 2026-04-23 before this patch was written:
    - kuriharacity.jp page title === 栗原市有機農業機械導入支援事業, FY2026.
    - town.yokohama.lg.jp page ``6,999,18,134,html`` titled
      '横浜町合併処理浄化槽設置整備事業補助金について' (walked from index).

Dry-run by default. ``--apply`` actually writes. All writes run in a single
transaction. After applying, rerun ``scripts/url_integrity_scan.py`` and it
should exit 0.
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import sqlite3
import sys
from typing import Any

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DB = os.path.join(REPO_ROOT, "data", "jpintel.db")


# ---------------------------------------------------------------------------
# Patch definitions — (unified_id, column, old_substring, new_substring)
# ---------------------------------------------------------------------------

COLUMN_PATCHES: list[tuple[str, str, str, str]] = [
    # UNI-e33d7b0613 — fabricated example.com. Replace both columns.
    (
        "UNI-e33d7b0613",
        "source_url",
        "https://www.example.com/kujihara_yuuki_shinseisho.pdf",
        "https://www.kuriharacity.jp/w018/030/030/yuukikikaisien/PAGE000000000000008075.html",
    ),
    (
        "UNI-e33d7b0613",
        "official_url",
        "https://www.example.com/kujihara_yuuki_shinseisho.pdf",
        "https://www.kuriharacity.jp/w018/030/030/yuukikikaisien/PAGE000000000000008075.html",
    ),
    # UNI-47b67cba4a — placeholder …
    (
        "UNI-47b67cba4a",
        "source_url",
        "https://www.town.yokohama.lg.jp/...",
        "https://www.town.yokohama.lg.jp/index.cfm/6,999,18,134,html",
    ),
    (
        "UNI-47b67cba4a",
        "official_url",
        "https://www.town.yokohama.lg.jp/...",
        "https://www.town.yokohama.lg.jp/index.cfm/6,999,18,134,html",
    ),
    # UNI-b0b9565569 — same 横浜町 program (noukaweb duplicate row). Same fix.
    (
        "UNI-b0b9565569",
        "source_url",
        "https://www.town.yokohama.lg.jp/...",
        "https://www.town.yokohama.lg.jp/index.cfm/6,999,18,134,html",
    ),
    (
        "UNI-b0b9565569",
        "official_url",
        "https://www.town.yokohama.lg.jp/...",
        "https://www.town.yokohama.lg.jp/index.cfm/6,999,18,134,html",
    ),
    # UNI-81c7fb2813 — truncated ``https://w`` inside enriched_json quote.
    # The raw bytes around the bad URL are: ``\"source\": \"https://w"`` —
    # backslash-escaped inner quotes around the source key, then an unescaped
    # ``"`` that terminates the outer "quote" value. The URL was truncated
    # mid-write. ``https://w"`` occurs exactly once in this row, so we splice
    # the verified source URL in and add the missing escaped closing ``\"``
    # so the nested string parses cleanly.
    (
        "UNI-81c7fb2813",
        "enriched_json",
        'https://w"',
        'https://www.pref.tottori.lg.jp/64862.htm\\"',
    ),
    # UNI-d8aa2870e3 — fullwidth slash in brochure excerpt. Normalize to
    # halfwidth slash + space so ``FOLLOW`` stays part of the surrounding
    # text instead of polluting the netloc.
    (
        "UNI-d8aa2870e3",
        "enriched_json",
        "http://betsukai-kenboku.jp／FOLLOW",
        "http://betsukai-kenboku.jp/ FOLLOW",
    ),
]


def _fetch_value(con: sqlite3.Connection, uid: str, column: str) -> Any:
    row = con.execute(f"SELECT {column} FROM programs WHERE unified_id = ?", (uid,)).fetchone()
    if row is None:
        return None
    return row[0]


def _column_exists(con: sqlite3.Connection, table: str, column: str) -> bool:
    rows = con.execute(f"PRAGMA table_info({table})").fetchall()
    return any(r[1] == column for r in rows)


def run(db_path: str, apply: bool) -> int:
    if not os.path.exists(db_path):
        print(f"ERROR: DB not found at {db_path}", file=sys.stderr)
        return 2

    mode = "rw" if apply else "ro"
    uri = f"file:{db_path}?mode={mode}"
    con = sqlite3.connect(uri, uri=True, isolation_level=None)

    corrected_at = dt.datetime.now(dt.UTC).isoformat(timespec="seconds")
    planned: list[tuple[str, str, str, str]] = []
    already_clean: list[tuple[str, str]] = []

    try:
        for uid, col, old, new in COLUMN_PATCHES:
            current = _fetch_value(con, uid, col)
            if current is None:
                print(
                    f"WARN: {uid} not found or column {col} is NULL — skipping",
                    file=sys.stderr,
                )
                continue
            if old not in current:
                already_clean.append((uid, col))
                continue
            preview_before = current[:400]
            new_value = current.replace(old, new)
            preview_after = new_value[:400]
            planned.append((uid, col, preview_before, preview_after))

        if not planned and not already_clean:
            print("Nothing to do — no rows matched the expected broken patterns.")
            return 0

        print(f"Planned column patches: {len(planned)}")
        print(f"Already clean (no match): {len(already_clean)}")
        print()
        for uid, col, before, after in planned:
            print(f"[{uid}] {col}")
            print(f"  before: {before[:180]}{'...' if len(before) >= 180 else ''}")
            print(f"  after : {after[:180]}{'...' if len(after) >= 180 else ''}")
            print()
        for uid, col in already_clean:
            print(f"[{uid}] {col} — already clean, no change needed")

        if not apply:
            print()
            print("DRY RUN. Re-run with --apply to commit these changes.")
            return 0

        # --apply path.
        con.execute("BEGIN;")
        try:
            # Bookkeeping column, idempotent.
            if not _column_exists(con, "programs", "source_url_corrected_at"):
                con.execute("ALTER TABLE programs ADD COLUMN source_url_corrected_at TEXT;")

            for uid, col, _before, _after in planned:
                current = _fetch_value(con, uid, col)
                # Re-compute under the lock to avoid racing with a concurrent
                # writer — planned[] was built under ``mode=ro`` before BEGIN.
                # We find-and-replace on the live value.
                # Only the patches in COLUMN_PATCHES are applied.
                #
                # (Simple linear scan here is fine — we only have 8 rows.)
                new_val = current
                for p_uid, p_col, p_old, p_new in COLUMN_PATCHES:
                    if p_uid == uid and p_col == col and p_old in new_val:
                        new_val = new_val.replace(p_old, p_new)
                con.execute(
                    f"UPDATE programs SET {col} = ?, "
                    "source_url_corrected_at = ? WHERE unified_id = ?",
                    (new_val, corrected_at, uid),
                )
            con.execute("COMMIT;")
        except Exception:
            con.execute("ROLLBACK;")
            raise

        print()
        print(f"APPLIED {len(planned)} patch(es). source_url_corrected_at = {corrected_at}")
        print("Next: run `uv run python scripts/url_integrity_scan.py` and confirm exit 0.")
        return 0
    finally:
        con.close()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default=DEFAULT_DB, help=f"DB path (default: {DEFAULT_DB})")
    ap.add_argument("--apply", action="store_true", help="Commit the changes")
    args = ap.parse_args(argv)
    return run(args.db, args.apply)


if __name__ == "__main__":
    sys.exit(main())
