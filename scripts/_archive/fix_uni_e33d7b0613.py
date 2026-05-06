#!/usr/bin/env python3
"""Fix the fabricated ``source_url`` on ``UNI-e33d7b0613``.

Blocker referenced in ``research/data_quality_report.md`` and the scan output
from ``scripts/url_integrity_scan.py``: the row carries
``source_url = https://www.example.com/kujihara_yuuki_shinseisho.pdf``, which
is fabricated (``example.com`` is the IANA reserved synthetic domain) and
therefore 不当表示 under 景品表示法 4/5 条.

This script is **dry-run by default**. It does NOT call ``UPDATE`` until
invoked with ``--apply``. Expected workflow:

    1. Owner finds the real primary source via
       `MAFF / 自治体サイト / JFC` for the program that
       ``UNI-e33d7b0613`` refers to (see step 2 below — the script prints
       the primary_name it is about to patch so the owner can verify).
    2. Pass the verified URL via ``--new-url`` and run with ``--apply``.
    3. Re-run ``scripts/url_integrity_scan.py`` to confirm the row no longer
       flags, then commit the updated data snapshot / backup.

No DB writes happen in dry-run mode. In ``--apply`` mode the script wraps
the update in a single transaction, adds a ``source_url_corrected_at``
TEXT column if it does not already exist, and refuses to run unless a
non-placeholder ``--new-url`` is supplied.
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import sqlite3
import sys
from urllib.parse import urlparse

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DB = os.path.join(REPO_ROOT, "data", "jpintel.db")

TARGET_UNIFIED_ID = "UNI-e33d7b0613"
FABRICATED_URL = "https://www.example.com/kujihara_yuuki_shinseisho.pdf"
SYNTHETIC_HOSTS = {
    "example.com",
    "example.jp",
    "example.org",
    "example.net",
    "localhost",
    "test.com",
    "test.jp",
}


def _column_exists(con: sqlite3.Connection, table: str, column: str) -> bool:
    rows = con.execute(f"PRAGMA table_info({table})").fetchall()
    return any(r[1] == column for r in rows)


def _validate_new_url(url: str) -> None:
    """Raise if *url* is empty, synthetic, or missing a real host/TLD."""
    if not url:
        raise ValueError("--new-url is required when --apply is set")
    parsed = urlparse(url)
    scheme = (parsed.scheme or "").lower()
    if scheme not in ("http", "https"):
        raise ValueError(f"--new-url must be http(s), got {scheme!r}")
    host = (parsed.hostname or "").lower()
    if not host:
        raise ValueError("--new-url has no host")
    if host in SYNTHETIC_HOSTS or any(
        host == base or host.endswith("." + base) for base in SYNTHETIC_HOSTS
    ):
        raise ValueError(f"--new-url points at a synthetic host: {host}")
    if "." not in host:
        raise ValueError(f"--new-url host has no TLD: {host}")


def _fetch_current_state(con: sqlite3.Connection) -> dict[str, str | None]:
    row = con.execute(
        "SELECT unified_id, primary_name, source_url, official_url "
        "FROM programs WHERE unified_id = ?",
        (TARGET_UNIFIED_ID,),
    ).fetchone()
    if row is None:
        raise LookupError(
            f"{TARGET_UNIFIED_ID} not found in programs — was it renamed? "
            "Investigate before forcing an update."
        )
    return {
        "unified_id": row[0],
        "primary_name": row[1],
        "source_url": row[2],
        "official_url": row[3],
    }


def run(db_path: str, new_url: str | None, apply: bool) -> int:
    if not os.path.exists(db_path):
        print(f"ERROR: DB not found at {db_path}", file=sys.stderr)
        return 2

    mode = "rw" if apply else "ro"
    uri = f"file:{db_path}?mode={mode}"
    con = sqlite3.connect(uri, uri=True, isolation_level=None)
    try:
        state = _fetch_current_state(con)
        corrected_at = dt.datetime.now(dt.UTC).isoformat(timespec="seconds")

        print(f"Target unified_id : {state['unified_id']}")
        print(f"Target primary_name: {state['primary_name']}")
        print(f"Current source_url : {state['source_url']}")
        print(f"Current official_url: {state['official_url']}")
        print(f"Planned source_url : {new_url or '(not supplied yet)'}")
        print(f"Planned corrected_at: {corrected_at}")
        print()

        # Owner sanity: warn loudly if the stored source_url no longer
        # matches the known-fabricated value (someone may have already
        # patched it, or the row was overwritten by a re-ingest).
        if state["source_url"] != FABRICATED_URL:
            print(
                "WARNING: current source_url does not match the originally "
                f"reported fabricated value ({FABRICATED_URL!r}). Verify the "
                "row still needs a correction before re-running with --apply."
            )
            print()

        column_exists = _column_exists(con, "programs", "source_url_corrected_at")
        add_column_sql = "ALTER TABLE programs ADD COLUMN source_url_corrected_at TEXT;"
        update_sql = (
            "UPDATE programs "
            "SET source_url = :new_url, "
            "    source_url_corrected_at = :corrected_at "
            "WHERE unified_id = :uid;"
        )

        print("Planned SQL:")
        if not column_exists:
            print(f"  {add_column_sql}")
        else:
            print("  -- source_url_corrected_at column already present; no ALTER TABLE needed")
        print(f"  {update_sql}")
        print(
            f"  -- params: uid={state['unified_id']!r}, "
            f"new_url={new_url!r}, corrected_at={corrected_at!r}"
        )
        print()

        if not apply:
            print("DRY RUN — apply with --apply")
            return 0

        # --apply path beyond this point.
        try:
            _validate_new_url(new_url or "")
        except ValueError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2

        con.execute("BEGIN;")
        try:
            if not column_exists:
                con.execute(add_column_sql)
            con.execute(
                update_sql,
                {
                    "new_url": new_url,
                    "corrected_at": corrected_at,
                    "uid": state["unified_id"],
                },
            )
            con.execute("COMMIT;")
        except Exception:
            con.execute("ROLLBACK;")
            raise

        # Verify post-state so the operator gets proof in the log.
        after = _fetch_current_state(con)
        print("APPLIED. Post-update state:")
        print(f"  source_url          : {after['source_url']}")
        print(f"  source_url_corrected_at: {corrected_at}")
        print()
        print(
            "Next: re-run `python scripts/url_integrity_scan.py` and confirm "
            "the UNI-e33d7b0613 row no longer appears."
        )
        return 0
    finally:
        con.close()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--db",
        default=DEFAULT_DB,
        help=f"Path to sqlite DB (default: {DEFAULT_DB}).",
    )
    ap.add_argument(
        "--new-url",
        default=None,
        help=(
            "The verified primary-source URL for UNI-e33d7b0613. Must be a "
            "real http(s) URL on a real TLD; synthetic / placeholder hosts "
            "are rejected."
        ),
    )
    ap.add_argument(
        "--apply",
        action="store_true",
        help=(
            "Actually run the UPDATE. Without this flag the script is a "
            "dry run and prints the planned SQL only."
        ),
    )
    args = ap.parse_args(argv)
    return run(args.db, args.new_url, args.apply)


if __name__ == "__main__":
    sys.exit(main())
