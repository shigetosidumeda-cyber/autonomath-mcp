#!/usr/bin/env python3
"""Backfill missing ``am_source.content_hash`` values.

The production corpus currently stores 16-hex-character SHA-256 prefixes for
``am_source.content_hash``.  Most rows hash the source URL directly; rows that
were derived from richer canonical payloads may differ, but still use the same
compact digest shape.  A4 only fills NULL rows, so this script preserves every
existing checksum and writes deterministic URL digests for missing rows.

No network. No LLM. Re-runnable.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterable

REPO_ROOT = Path(__file__).resolve().parents[2]
AUTONOMATH_DB = REPO_ROOT / "autonomath.db"
HASH_HEX_CHARS = 16


@dataclass(frozen=True)
class HashUpdate:
    source_id: int
    source_url: str
    content_hash: str


def _connect(path: Path) -> sqlite3.Connection:
    if not path.exists():
        raise FileNotFoundError(path)
    conn = sqlite3.connect(str(path), timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _verify_schema(conn: sqlite3.Connection) -> None:
    cols = {row[1] for row in conn.execute("PRAGMA table_info(am_source)").fetchall()}
    missing = {"id", "source_url", "content_hash"} - cols
    if missing:
        raise SystemExit(f"am_source missing expected columns: {sorted(missing)}")


def compute_source_content_hash(source_url: str) -> str:
    """Return the corpus convention: 16-char SHA-256 prefix of the URL."""
    return hashlib.sha256(source_url.strip().encode("utf-8")).hexdigest()[:HASH_HEX_CHARS]


def collect_missing_hash_updates(conn: sqlite3.Connection) -> list[HashUpdate]:
    """Collect deterministic updates for rows whose ``content_hash`` is NULL."""
    updates: list[HashUpdate] = []
    for row in conn.execute(
        """SELECT id, source_url
             FROM am_source
            WHERE content_hash IS NULL
         ORDER BY id"""
    ):
        source_url = str(row["source_url"] or "").strip()
        if not source_url:
            continue
        updates.append(
            HashUpdate(
                source_id=int(row["id"]),
                source_url=source_url,
                content_hash=compute_source_content_hash(source_url),
            )
        )
    return updates


def find_hash_collisions(
    conn: sqlite3.Connection,
    updates: Iterable[HashUpdate],
) -> list[dict[str, Any]]:
    """Return candidate digest collisions against existing non-NULL rows."""
    collisions: list[dict[str, Any]] = []
    for update in updates:
        row = conn.execute(
            """SELECT id, source_url
                 FROM am_source
                WHERE content_hash = ?
                  AND id != ?
                LIMIT 1""",
            (update.content_hash, update.source_id),
        ).fetchone()
        if row is not None:
            collisions.append(
                {
                    "content_hash": update.content_hash,
                    "source_id": update.source_id,
                    "source_url": update.source_url,
                    "colliding_source_id": row["id"],
                    "colliding_source_url": row["source_url"],
                }
            )
    return collisions


def backfill_content_hashes(
    conn: sqlite3.Connection,
    *,
    apply: bool,
) -> dict[str, Any]:
    _verify_schema(conn)
    before_null = conn.execute(
        "SELECT COUNT(*) FROM am_source WHERE content_hash IS NULL"
    ).fetchone()[0]
    before_non_null = conn.execute(
        "SELECT COUNT(*) FROM am_source WHERE content_hash IS NOT NULL"
    ).fetchone()[0]
    updates = collect_missing_hash_updates(conn)
    skipped_empty_url = before_null - len(updates)
    collisions = find_hash_collisions(conn, updates)
    if collisions:
        return {
            "mode": "apply" if apply else "dry_run",
            "status": "collision_blocked",
            "am_source_content_hash_null_before": before_null,
            "candidate_updates": len(updates),
            "collisions": collisions[:20],
        }

    updated_rows = 0
    if apply:
        with conn:
            for update in updates:
                cur = conn.execute(
                    """UPDATE am_source
                          SET content_hash = ?
                        WHERE id = ?
                          AND content_hash IS NULL""",
                    (update.content_hash, update.source_id),
                )
                updated_rows += cur.rowcount

    after_null = conn.execute(
        "SELECT COUNT(*) FROM am_source WHERE content_hash IS NULL"
    ).fetchone()[0]
    after_non_null = conn.execute(
        "SELECT COUNT(*) FROM am_source WHERE content_hash IS NOT NULL"
    ).fetchone()[0]
    sample_updates = [asdict(update) for update in updates[:10]]
    return {
        "mode": "apply" if apply else "dry_run",
        "status": "ok",
        "hash_algorithm": f"sha256(source_url)[:{HASH_HEX_CHARS}]",
        "am_source_content_hash_null_before": before_null,
        "am_source_content_hash_non_null_before": before_non_null,
        "candidate_updates": len(updates),
        "skipped_empty_source_url": skipped_empty_url,
        "updated_rows": updated_rows,
        "am_source_content_hash_null_after": after_null,
        "am_source_content_hash_non_null_after": after_non_null,
        "sample_updates": sample_updates,
        "generated_at": datetime.now(UTC).isoformat(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db",
        type=Path,
        default=AUTONOMATH_DB,
        help="SQLite DB path (default: repo-root autonomath.db).",
    )
    grp = parser.add_mutually_exclusive_group(required=True)
    grp.add_argument("--dry-run", action="store_true", help="Calculate updates only.")
    grp.add_argument("--apply", action="store_true", help="Write missing hashes.")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    args = parser.parse_args()

    with _connect(args.db) as conn:
        result = backfill_content_hashes(conn, apply=args.apply)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(
            "am_source.content_hash NULL: "
            f"{result['am_source_content_hash_null_before']} -> "
            f"{result['am_source_content_hash_null_after']}"
        )
        print(f"candidate_updates={result['candidate_updates']}")
        print(f"updated_rows={result['updated_rows']}")

    return 0 if result["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
