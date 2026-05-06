"""Operator review CLI for alias_candidates_queue (mig 112).

The cron `scripts/cron/alias_dict_expansion.py` mines empty_search_log
weekly and lands proposals in `alias_candidates_queue`. This CLI is the
ONLY production-write surface for the alias dictionary — Plan §8.7 says
"production write 必ず review 後", so the cron itself never touches
`am_alias`.

Usage:
    python -m jpintel_mcp.loops.alias_review --list
    python -m jpintel_mcp.loops.alias_review --approve <id>
    python -m jpintel_mcp.loops.alias_review --reject <id>

`--approve` writes a row into `am_alias` (autonomath.db) and updates the
queue row's status. `--reject` only updates status. Both are idempotent
when run twice on the same id (no double-INSERT into am_alias because
the queue status check short-circuits the second call).

LLM use: NONE. Pure SQL.

Environment:
    * JPINTEL_DB_PATH       — defaults to ./data/jpintel.db
    * AUTONOMATH_DB_PATH    — defaults to ./autonomath.db
    * ALIAS_REVIEW_REVIEWER — reviewer label written to queue row
                              (default: 'operator').
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import sqlite3
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from jpintel_mcp.config import settings

if TYPE_CHECKING:
    from pathlib import Path


def _connect_jpintel(db_path: Path | None = None) -> sqlite3.Connection:
    p = db_path if db_path is not None else settings.db_path
    conn = sqlite3.connect(p, isolation_level=None)
    conn.row_factory = sqlite3.Row
    return conn


def _connect_autonomath(db_path: Path | None = None) -> sqlite3.Connection:
    p = db_path if db_path is not None else settings.autonomath_db_path
    conn = sqlite3.connect(p, isolation_level=None)
    conn.row_factory = sqlite3.Row
    return conn


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _ensure_queue_table(conn: sqlite3.Connection) -> None:
    """Belt-and-suspenders: tests + dev DBs may need this on the fly."""
    conn.execute(
        """CREATE TABLE IF NOT EXISTS alias_candidates_queue (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              candidate_alias TEXT NOT NULL,
              canonical_term TEXT NOT NULL,
              match_score REAL NOT NULL,
              empty_query_count INTEGER NOT NULL,
              first_seen TIMESTAMP NOT NULL,
              last_seen TIMESTAMP NOT NULL,
              status TEXT DEFAULT 'pending'
                CHECK(status IN ('pending','approved','rejected')),
              reviewed_at TIMESTAMP,
              reviewer TEXT,
              UNIQUE(candidate_alias, canonical_term)
          )"""
    )


def list_pending(
    *,
    jpintel_db: Path | None = None,
    limit: int = 100,
    status: str = "pending",
) -> list[dict[str, Any]]:
    """Return queue rows of the given status, newest-last_seen first."""
    conn = _connect_jpintel(jpintel_db)
    try:
        _ensure_queue_table(conn)
        cur = conn.execute(
            """SELECT id, candidate_alias, canonical_term, match_score,
                      empty_query_count, first_seen, last_seen, status,
                      reviewed_at, reviewer
                 FROM alias_candidates_queue
                WHERE status=?
                ORDER BY empty_query_count DESC, match_score DESC, id ASC
                LIMIT ?""",
            (status, int(limit)),
        )
        return [dict(row) for row in cur]
    finally:
        with contextlib.suppress(Exception):
            conn.close()


def _classify_canonical(canonical_term: str) -> tuple[str, str]:
    """Best-effort guess of (entity_table, alias_kind) from canonical_term.

    The vocab.py constants emit short canonicals: '東京都' (kanji
    prefecture), 'A'..'T' (single-letter JSIC), 'national' / 'prefecture' /
    'municipality' / 'financial' (authority levels). Program anchors emit
    long unified_id strings ('program:base:abc123').

    Returns ('am_entities' or 'am_region' or 'am_industry_jsic' or
    'am_authority', 'partial' / 'kana' / 'misc').
    """
    if not canonical_term:
        return ("am_entities", "misc")
    if len(canonical_term) == 1 and canonical_term.isalpha():
        # Single-letter JSIC code.
        return ("am_industry_jsic", "partial")
    if canonical_term in {"national", "prefecture", "municipality", "financial"}:
        return ("am_authority", "partial")
    if (
        any(canonical_term.endswith(suffix) for suffix in ("都", "道", "府", "県"))
        or canonical_term == "全国"
    ):
        return ("am_region", "partial")
    if ":" in canonical_term:
        return ("am_entities", "partial")
    return ("am_entities", "misc")


def approve(
    queue_id: int,
    *,
    reviewer: str = "operator",
    jpintel_db: Path | None = None,
    autonomath_db: Path | None = None,
) -> dict[str, Any]:
    """Approve a queue row -> INSERT into am_alias + flip queue status.

    Idempotent: on re-call against an already-approved row, returns
    `{op: 'noop', ...}` without touching am_alias.
    """
    j_conn = _connect_jpintel(jpintel_db)
    try:
        _ensure_queue_table(j_conn)
        row = j_conn.execute(
            "SELECT * FROM alias_candidates_queue WHERE id=?",
            (int(queue_id),),
        ).fetchone()
        if row is None:
            return {"op": "not_found", "id": int(queue_id)}
        if row["status"] != "pending":
            return {
                "op": "noop",
                "id": int(queue_id),
                "current_status": row["status"],
                "reason": "already reviewed",
            }
        canonical = row["canonical_term"]
        alias = row["candidate_alias"]
        entity_table, alias_kind = _classify_canonical(canonical)
        # Write am_alias row in autonomath.db.
        a_conn = _connect_autonomath(autonomath_db)
        try:
            try:
                a_conn.execute(
                    "INSERT INTO am_alias("
                    "  entity_table, canonical_id, alias, alias_kind, "
                    "  created_at, language"
                    ") VALUES (?, ?, ?, ?, ?, 'ja')",
                    (entity_table, str(canonical), str(alias), alias_kind, _now_iso()),
                )
                am_op = "inserted"
            except sqlite3.IntegrityError:
                # Some am_alias schemas carry a UNIQUE on (entity_table,
                # canonical_id, alias) — treat the existing row as ok.
                am_op = "exists"
            except sqlite3.OperationalError as exc:
                # am_alias table may not exist in tests / fresh dev.
                am_op = f"error:{exc}"
        finally:
            with contextlib.suppress(Exception):
                a_conn.close()
        # Flip queue status whether am_alias write succeeded or already-existed
        # — operator decision is recorded either way. A real `error:...` from
        # OperationalError leaves the queue row pending so the CLI can be
        # re-run after the schema is fixed.
        if am_op.startswith("error:"):
            return {
                "op": "am_alias_error",
                "id": int(queue_id),
                "error": am_op,
            }
        j_conn.execute(
            "UPDATE alias_candidates_queue "
            "SET status='approved', reviewed_at=?, reviewer=? "
            "WHERE id=?",
            (_now_iso(), reviewer, int(queue_id)),
        )
        return {
            "op": "approved",
            "id": int(queue_id),
            "candidate_alias": alias,
            "canonical_term": canonical,
            "entity_table": entity_table,
            "alias_kind": alias_kind,
            "am_alias_op": am_op,
        }
    finally:
        with contextlib.suppress(Exception):
            j_conn.close()


def reject(
    queue_id: int,
    *,
    reviewer: str = "operator",
    jpintel_db: Path | None = None,
) -> dict[str, Any]:
    """Reject a queue row — flip status only. NEVER touches am_alias."""
    conn = _connect_jpintel(jpintel_db)
    try:
        _ensure_queue_table(conn)
        row = conn.execute(
            "SELECT id, status FROM alias_candidates_queue WHERE id=?",
            (int(queue_id),),
        ).fetchone()
        if row is None:
            return {"op": "not_found", "id": int(queue_id)}
        if row["status"] != "pending":
            return {
                "op": "noop",
                "id": int(queue_id),
                "current_status": row["status"],
                "reason": "already reviewed",
            }
        conn.execute(
            "UPDATE alias_candidates_queue "
            "SET status='rejected', reviewed_at=?, reviewer=? "
            "WHERE id=?",
            (_now_iso(), reviewer, int(queue_id)),
        )
        return {"op": "rejected", "id": int(queue_id)}
    finally:
        with contextlib.suppress(Exception):
            conn.close()


def _format_table(rows: list[dict[str, Any]]) -> str:
    """Render a small table for --list. Avoids pulling in tabulate."""
    if not rows:
        return "(no rows)"
    header = ("id", "alias", "canonical", "score", "count", "last_seen")
    lines = ["\t".join(header)]
    for r in rows:
        lines.append(
            "\t".join(
                [
                    str(r["id"]),
                    str(r["candidate_alias"])[:40],
                    str(r["canonical_term"])[:30],
                    f"{r['match_score']:.2f}",
                    str(r["empty_query_count"]),
                    str(r["last_seen"])[:19],
                ]
            )
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Operator review CLI for alias_candidates_queue.",
    )
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--list", action="store_true", help="List pending queue rows.")
    g.add_argument(
        "--approve", type=int, metavar="ID", help="Approve queue row -> INSERT into am_alias."
    )
    g.add_argument("--reject", type=int, metavar="ID", help="Reject queue row.")
    p.add_argument(
        "--status",
        default="pending",
        choices=("pending", "approved", "rejected"),
        help="Filter for --list (default pending).",
    )
    p.add_argument("--limit", type=int, default=100, help="--list row cap (default 100).")
    p.add_argument(
        "--reviewer",
        default=os.environ.get("ALIAS_REVIEW_REVIEWER", "operator"),
        help="Reviewer label written to queue row.",
    )
    p.add_argument("--json", action="store_true", help="Emit JSON instead of tabular output.")
    args = p.parse_args(argv)

    if args.list:
        rows = list_pending(limit=args.limit, status=args.status)
        if args.json:
            print(json.dumps(rows, indent=2, ensure_ascii=False))
        else:
            print(_format_table(rows))
        return 0

    if args.approve is not None:
        out = approve(args.approve, reviewer=args.reviewer)
    else:
        out = reject(args.reject, reviewer=args.reviewer)
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0 if out.get("op") in {"approved", "rejected", "noop"} else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = [
    "approve",
    "list_pending",
    "main",
    "reject",
]
