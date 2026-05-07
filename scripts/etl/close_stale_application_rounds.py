#!/usr/bin/env python3
"""Close reviewed stale-open application rounds in ``autonomath.db``.

D1 is intentionally narrow: it updates only reviewed ``am_application_round``
rows whose close date has passed but still carry ``status='open'``.  Apply mode
is guarded by the current dry-run candidate set so unrelated stale rows are
reported instead of changed.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import date
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
AUTONOMATH_DB = REPO_ROOT / "autonomath.db"
EXPECTED_SAFE_ROUND_IDS = (810,)


def _connect(path: Path) -> sqlite3.Connection:
    if not path.exists():
        raise FileNotFoundError(path)
    conn = sqlite3.connect(str(path), timeout=30.0)
    conn.row_factory = sqlite3.Row
    return conn


def stale_open_rounds(conn: sqlite3.Connection, *, today: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT
            round_id,
            program_entity_id,
            round_label,
            application_open_date,
            application_close_date,
            status,
            source_url
          FROM am_application_round
         WHERE status = 'open'
           AND application_close_date IS NOT NULL
           AND application_close_date < ?
      ORDER BY application_close_date, round_id
        """,
        (today,),
    ).fetchall()
    return [dict(row) for row in rows]


def _candidate_ids(candidates: list[dict[str, Any]]) -> tuple[int, ...]:
    return tuple(int(row["round_id"]) for row in candidates)


def _safe_to_apply(
    candidates: list[dict[str, Any]],
    expected_round_ids: tuple[int, ...],
) -> bool:
    candidate_ids = _candidate_ids(candidates)
    return candidate_ids == expected_round_ids or candidate_ids == ()


def close_stale_application_rounds(
    conn: sqlite3.Connection,
    *,
    apply: bool,
    today: str | None = None,
    expected_round_ids: tuple[int, ...] = EXPECTED_SAFE_ROUND_IDS,
) -> dict[str, Any]:
    effective_today = today or date.today().isoformat()
    before = stale_open_rounds(conn, today=effective_today)
    safe_to_apply = _safe_to_apply(before, expected_round_ids)
    updated_rows = 0

    if apply and safe_to_apply and before:
        with conn:
            cur = conn.executemany(
                """
                UPDATE am_application_round
                   SET status = 'closed'
                 WHERE round_id = ?
                   AND status = 'open'
                   AND application_close_date IS NOT NULL
                   AND application_close_date < ?
                """,
                [(row["round_id"], effective_today) for row in before],
            )
            updated_rows = cur.rowcount

    after = stale_open_rounds(conn, today=effective_today)
    blocked_reason = None
    if apply and not safe_to_apply:
        blocked_reason = "stale-open candidate set does not match reviewed safe round IDs"

    return {
        "mode": "apply" if apply else "dry_run",
        "today": effective_today,
        "expected_round_ids": list(expected_round_ids),
        "candidate_round_ids": list(_candidate_ids(before)),
        "candidate_count": len(before),
        "candidates": before,
        "safe_to_apply": safe_to_apply,
        "blocked_reason": blocked_reason,
        "updated_rows": updated_rows,
        "remaining_stale_open_count": len(after),
        "remaining_stale_open_round_ids": list(_candidate_ids(after)),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=AUTONOMATH_DB)
    parser.add_argument("--today", default=None, help="Override today's ISO date for tests.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true")
    group.add_argument("--apply", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    with _connect(args.db) as conn:
        result = close_stale_application_rounds(
            conn,
            apply=args.apply,
            today=args.today,
        )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(f"mode={result['mode']}")
        print(f"today={result['today']}")
        print(f"candidate_count={result['candidate_count']}")
        print(f"candidate_round_ids={result['candidate_round_ids']}")
        print(f"safe_to_apply={result['safe_to_apply']}")
        print(f"updated_rows={result['updated_rows']}")
        print(f"remaining_stale_open_count={result['remaining_stale_open_count']}")
        if result["blocked_reason"]:
            print(f"blocked_reason={result['blocked_reason']}")
    return 1 if result["blocked_reason"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
