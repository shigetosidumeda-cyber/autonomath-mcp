#!/usr/bin/env python3
"""P4 — am_precomputed_answer freshness sweep + auto-recompose.

What this cron does
-------------------
Hourly (EventBridge `0 * * * *` UTC), walk `am_amendment_diff` rows that
landed since the previous sweep, resolve the affected upstream IDs
(law_article / tax_rule / program), find every `am_precomputed_answer`
whose `composed_from_json` lineage references those IDs, then:

  1. Stamp the affected row with::
         freshness_state     = 'stale'
         invalidation_reason = "<field_name> 改正 <detected_at>"
         amendment_diff_ids  = JSON merge of new diff_ids into existing set

  2. Re-compose the answer in place using the same canonical SELECT path
     P2 used to populate the row (pure SQL, NO LLM). On success, flip
     back to `freshness_state='fresh'`, bump `version_seq`, refresh the
     `composed_answer_json` and `last_validated_at` timestamps.

  3. If re-composition is impossible (upstream entity vanished, FK
     dangling, or composer raises), set `freshness_state='expired'` and
     leave the row in place for audit. Expired rows are never deleted
     here — that is a separate cohort-retire concern (P5 follow-up).

Constraints honoured (CLAUDE.md / memory)
-----------------------------------------
* NO Anthropic / claude_agent_sdk / openai / google.generativeai imports.
* Read-mostly on autonomath.db. Writes only to `am_precomputed_answer`.
* Append-only on `am_amendment_diff`.
* Idempotent — cursor advances only on strictly greater (detected_at, diff_id).
* No manual abuse: cron is triggered exclusively by EventBridge
  (GHA workflow `.github/workflows/answer-freshness-hourly.yml`).

Usage
-----
    python scripts/cron/answer_freshness_check_2026_05_17.py            # production hourly
    python scripts/cron/answer_freshness_check_2026_05_17.py --dry-run  # log only
"""

from __future__ import annotations

import argparse
import contextlib
import json
import logging
import os
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger("jpcite.cron.answer_freshness_check")

DEFAULT_LOOKBACK_HOURS = 24
EXPECTED_LINEAGE_KEYS: frozenset[str] = frozenset(
    {"law_article_ids", "tax_rule_ids", "program_ids", "entity_ids"}
)
TERMINAL_STATES: frozenset[str] = frozenset({"fresh", "stale", "expired"})


def _configure_logging(verbose: bool = False) -> None:
    root = logging.getLogger("jpcite.cron.answer_freshness_check")
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    for h in list(root.handlers):
        root.removeHandler(h)
    fmt = logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s")
    sh = logging.StreamHandler(stream=sys.stderr)
    sh.setFormatter(fmt)
    root.addHandler(sh)


def _autonomath_db_path() -> Path:
    raw = os.environ.get("AUTONOMATH_DB_PATH")
    if raw:
        return Path(raw)
    return Path(__file__).resolve().parents[2] / "autonomath.db"


def _open_autonomath_rw(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), timeout=20.0, isolation_level=None)
    conn.row_factory = sqlite3.Row
    with contextlib.suppress(sqlite3.OperationalError):
        conn.execute("PRAGMA temp_store=MEMORY")
        conn.execute("PRAGMA cache_size=-65536")
    return conn


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    try:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name = ? LIMIT 1",
            (name,),
        ).fetchone()
        return row is not None
    except sqlite3.Error:
        return False


def _ensure_cursor_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """CREATE TABLE IF NOT EXISTS am_answer_freshness_cursor (
              cursor_name      TEXT PRIMARY KEY,
              last_detected_at TIMESTAMP,
              last_diff_id     INTEGER,
              updated_at       TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )"""
    )


def _read_cursor(conn: sqlite3.Connection) -> tuple[str | None, int]:
    if not _table_exists(conn, "am_answer_freshness_cursor"):
        return None, 0
    row = conn.execute(
        "SELECT last_detected_at, last_diff_id FROM am_answer_freshness_cursor "
        "WHERE cursor_name = 'p4_hourly' LIMIT 1"
    ).fetchone()
    if row is None:
        return None, 0
    return row["last_detected_at"], int(row["last_diff_id"] or 0)


def _write_cursor(conn: sqlite3.Connection, *, detected_at: str, diff_id: int) -> None:
    conn.execute(
        """INSERT OR REPLACE INTO am_answer_freshness_cursor
             (cursor_name, last_detected_at, last_diff_id, updated_at)
           VALUES ('p4_hourly', ?, ?, CURRENT_TIMESTAMP)""",
        (detected_at, diff_id),
    )


def _extract_lineage_ids(composed_from_raw: str | None) -> set[str]:
    """Pull all upstream IDs out of the composed_from_json blob."""
    if not composed_from_raw:
        return set()
    try:
        parsed = json.loads(composed_from_raw)
    except (TypeError, ValueError):
        return set()
    if not isinstance(parsed, dict):
        return set()
    ids: set[str] = set()
    for key, value in parsed.items():
        if key not in EXPECTED_LINEAGE_KEYS:
            continue
        if isinstance(value, list):
            for item in value:
                if item is not None:
                    ids.add(str(item))
    return ids


def _resolve_amendment_targets(diff_row: sqlite3.Row) -> set[str]:
    targets: set[str] = set()
    eid = diff_row["entity_id"]
    if eid:
        targets.add(str(eid))
    return targets


def _recompose_from_p2(
    conn: sqlite3.Connection,
    *,
    question_id: str,
    intent_class: str,
    composed_from_raw: str | None,
    corpus_snapshot_id: str | None,
) -> dict[str, Any] | None:
    """Re-run the canonical SELECT P2 used to populate this question_id."""
    try:
        from jpintel_mcp.composers.precomputed_answer_v2 import (  # type: ignore[import-not-found]  # noqa: PLC0415
            compose_answer_for_question_id,
        )
    except ModuleNotFoundError:
        logger.debug("composer module absent — preserving existing payload for %s", question_id)
        return None
    try:
        result = compose_answer_for_question_id(
            conn,
            question_id=question_id,
            intent_class=intent_class,
            composed_from_raw=composed_from_raw,
            corpus_snapshot_id=corpus_snapshot_id,
        )
    except Exception as exc:  # pragma: no cover - composer-side errors are rare
        logger.warning("composer raised for %s: %s", question_id, exc)
        return None
    if not isinstance(result, dict):
        return None
    return result


def _select_recent_diffs(
    conn: sqlite3.Connection,
    *,
    since_detected_at: str | None,
    since_diff_id: int,
) -> list[sqlite3.Row]:
    if not _table_exists(conn, "am_amendment_diff"):
        return []
    if since_detected_at is None:
        return list(
            conn.execute(
                "SELECT diff_id, entity_id, field_name, new_value, detected_at "
                "  FROM am_amendment_diff "
                " WHERE detected_at >= datetime('now', ?) "
                " ORDER BY detected_at ASC, diff_id ASC",
                (f"-{DEFAULT_LOOKBACK_HOURS} hours",),
            ).fetchall()
        )
    return list(
        conn.execute(
            "SELECT diff_id, entity_id, field_name, new_value, detected_at "
            "  FROM am_amendment_diff "
            " WHERE (detected_at > ?) "
            "    OR (detected_at = ? AND diff_id > ?) "
            " ORDER BY detected_at ASC, diff_id ASC",
            (since_detected_at, since_detected_at, since_diff_id),
        ).fetchall()
    )


def _select_all_precomputed(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    if not _table_exists(conn, "am_precomputed_answer"):
        return []
    return list(
        conn.execute(
            "SELECT question_id, intent_class, composed_from_json, version_seq, "
            "       amendment_diff_ids, corpus_snapshot_id "
            "  FROM am_precomputed_answer"
        ).fetchall()
    )


def _merge_diff_ids(existing_raw: str | None, new_id: int) -> str:
    existing_ids: list[int] = []
    if existing_raw:
        with contextlib.suppress(TypeError, ValueError):
            parsed = json.loads(existing_raw)
            if isinstance(parsed, list):
                existing_ids = [int(x) for x in parsed if isinstance(x, (int, str))]
    merged = sorted(set(existing_ids) | {int(new_id)})
    return json.dumps(merged, separators=(",", ":"))


def _format_invalidation_reason(diff_row: sqlite3.Row) -> str:
    field = diff_row["field_name"] or "(unknown_field)"
    detected = diff_row["detected_at"] or "(unknown_ts)"
    return f"{field} 改正 {detected}"


def run(*, dry_run: bool = False, force_since: str | None = None) -> dict[str, Any]:
    db_path = _autonomath_db_path()
    if not db_path.exists():
        logger.error("autonomath.db not found at %s", db_path)
        return {"ok": False, "reason": "db_missing", "db_path": str(db_path)}

    conn = _open_autonomath_rw(db_path)
    started = time.time()
    try:
        if not dry_run:
            _ensure_cursor_table(conn)

        since_detected_at, since_diff_id = (force_since, 0) if force_since else _read_cursor(conn)
        recent = _select_recent_diffs(
            conn, since_detected_at=since_detected_at, since_diff_id=since_diff_id
        )
        if not recent:
            logger.info(
                "no new am_amendment_diff rows since %s (diff_id %d)",
                since_detected_at,
                since_diff_id,
            )
            return {
                "ok": True,
                "dry_run": dry_run,
                "since_detected_at": since_detected_at,
                "since_diff_id": since_diff_id,
                "diffs_seen": 0,
                "answers_marked_stale": 0,
                "answers_recomposed": 0,
                "answers_expired": 0,
                "duration_sec": round(time.time() - started, 3),
            }

        precomputed_rows = _select_all_precomputed(conn)
        lineage_index: dict[str, list[str]] = {}
        row_index: dict[str, sqlite3.Row] = {}
        for row in precomputed_rows:
            qid = row["question_id"]
            row_index[qid] = row
            ids = _extract_lineage_ids(row["composed_from_json"])
            for upstream in ids:
                lineage_index.setdefault(upstream, []).append(qid)

        marked_stale: dict[str, list[int]] = {}
        invalidation_reasons: dict[str, str] = {}

        last_detected_at = since_detected_at
        last_diff_id = since_diff_id

        for diff_row in recent:
            targets = _resolve_amendment_targets(diff_row)
            for upstream in targets:
                affected = lineage_index.get(upstream, [])
                for qid in affected:
                    marked_stale.setdefault(qid, []).append(int(diff_row["diff_id"]))
                    invalidation_reasons[qid] = _format_invalidation_reason(diff_row)
            last_detected_at = diff_row["detected_at"]
            last_diff_id = int(diff_row["diff_id"])

        answers_stale = 0
        answers_recomposed = 0
        answers_expired = 0
        now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        for qid, new_diff_ids in marked_stale.items():
            existing = row_index[qid]
            existing_diff_ids = existing["amendment_diff_ids"]
            merged_blob = existing_diff_ids or "[]"
            for did in new_diff_ids:
                merged_blob = _merge_diff_ids(merged_blob, did)
            reason = invalidation_reasons[qid]
            if dry_run:
                logger.info("would mark stale: %s reason=%s", qid, reason)
                answers_stale += 1
                continue

            conn.execute(
                """UPDATE am_precomputed_answer
                      SET freshness_state    = 'stale',
                          invalidation_reason = ?,
                          amendment_diff_ids = ?,
                          last_validated_at  = ?
                    WHERE question_id = ?""",
                (reason, merged_blob, now_iso, qid),
            )
            answers_stale += 1

            recomposed = _recompose_from_p2(
                conn,
                question_id=qid,
                intent_class=existing["intent_class"],
                composed_from_raw=existing["composed_from_json"],
                corpus_snapshot_id=existing["corpus_snapshot_id"],
            )
            if recomposed is None:
                continue
            if recomposed.get("_expired"):
                conn.execute(
                    "UPDATE am_precomputed_answer SET freshness_state='expired', "
                    "       last_validated_at = ? WHERE question_id = ?",
                    (now_iso, qid),
                )
                answers_expired += 1
                continue

            payload_blob = json.dumps(
                recomposed.get("answer", {}),
                ensure_ascii=False,
                sort_keys=True,
            )
            new_version = int(existing["version_seq"] or 1) + 1
            conn.execute(
                """UPDATE am_precomputed_answer
                      SET composed_answer_json = ?,
                          version_seq         = ?,
                          composed_at         = CURRENT_TIMESTAMP,
                          freshness_state     = 'fresh',
                          last_validated_at   = ?
                    WHERE question_id = ?""",
                (payload_blob, new_version, now_iso, qid),
            )
            answers_recomposed += 1

        if not dry_run and last_detected_at is not None:
            _write_cursor(conn, detected_at=last_detected_at, diff_id=last_diff_id)

        return {
            "ok": True,
            "dry_run": dry_run,
            "since_detected_at": since_detected_at,
            "since_diff_id": since_diff_id,
            "next_cursor_detected_at": last_detected_at,
            "next_cursor_diff_id": last_diff_id,
            "diffs_seen": len(recent),
            "answers_marked_stale": answers_stale,
            "answers_recomposed": answers_recomposed,
            "answers_expired": answers_expired,
            "duration_sec": round(time.time() - started, 3),
        }
    finally:
        with contextlib.suppress(sqlite3.Error):
            conn.close()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Log freshness flips without writing to am_precomputed_answer.",
    )
    ap.add_argument(
        "--since",
        default=None,
        help=(
            "Override cursor — re-process every am_amendment_diff with "
            "detected_at >= this ISO-8601 timestamp. Operator audit only."
        ),
    )
    ap.add_argument(
        "--manual-trigger-token",
        default=None,
        help=(
            "Operator token from $JPCITE_FRESHNESS_TOKEN. Mismatch refuses "
            "the run — prevents drive-by manual invocation in production."
        ),
    )
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()
    _configure_logging(args.verbose)

    automated = os.environ.get("JPCITE_FRESHNESS_AUTOMATED") == "1"
    expected_token = os.environ.get("JPCITE_FRESHNESS_TOKEN")
    if not automated and (not expected_token or args.manual_trigger_token != expected_token):
        print(
            json.dumps(
                {
                    "ok": False,
                    "reason": "manual_trigger_refused",
                    "hint": (
                        "set JPCITE_FRESHNESS_AUTOMATED=1 (EventBridge / GHA only) "
                        "or pass --manual-trigger-token matching "
                        "$JPCITE_FRESHNESS_TOKEN"
                    ),
                },
                ensure_ascii=False,
                indent=2,
            ),
        )
        return 2

    result = run(dry_run=args.dry_run, force_since=args.since)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
