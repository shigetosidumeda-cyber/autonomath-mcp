#!/usr/bin/env python3
"""§10.10 (4) Hallucination Guard — corpus-drift narrative detector.

Daily Fly cron. SQL-only — NO LLM call. Walks `am_amendment_diff` rows added
in the last 30 days (i.e. fields whose value changed) and `am_source` rows
whose `content_hash` changed since their previous fingerprint, then back-walks
to every narrative in `am_program_narrative` (and the four sibling tables)
that references the dirty entity. Each affected narrative is INSERTed into
`am_narrative_quarantine` with reason='corpus_drift' so the next operator
batch (Claude Code subagent) regenerates the body from the fresh facts.

Per `feedback_no_operator_llm_api`:
    * No anthropic / openai / google.generativeai / claude_agent_sdk import.
    * No regenerate-here. Quarantine only.

Cron:
    .github/workflows/narrative-drift-daily.yml (daily 04:00 JST on Fly).

Idempotency:
    The quarantine table has UNIQUE(narrative_id, narrative_table, detected_at).
    We bucket detected_at to the date string (YYYY-MM-DD) so re-running on the
    same day is a no-op — the second INSERT is harmlessly ignored.

Usage:
    python scripts/cron/narrative_drift_detect.py             # full daily pass
    python scripts/cron/narrative_drift_detect.py --dry-run   # log, no INSERT
"""

from __future__ import annotations

import argparse
import logging
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

# Allow running as a script without `pip install -e .`.
_REPO = Path(__file__).resolve().parent.parent.parent
_SRC = _REPO / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from jpintel_mcp.config import settings  # noqa: E402
from jpintel_mcp.observability import heartbeat  # noqa: E402

logger = logging.getLogger("autonomath.cron.narrative_drift_detect")

# Tables we walk for narrative -> entity back-resolution. The first column is
# the narrative table name, the second is the FK column that points at the
# canonical entity / program.id, and the third is the SQL JOIN clause.
_NARRATIVE_BACKLINKS: tuple[tuple[str, str], ...] = (
    # (narrative_table, JOIN clause that resolves narrative -> entity_id)
    (
        "am_program_narrative",
        "JOIN programs p ON p.id = nt.program_id "
        "WHERE p.canonical_id IN (SELECT entity_id FROM dirty)",
    ),
    (
        "am_houjin_360_narrative",
        "WHERE nt.entity_id IN (SELECT entity_id FROM dirty)",
    ),
    (
        "am_enforcement_summary",
        "WHERE nt.entity_id IN (SELECT entity_id FROM dirty)",
    ),
    (
        "am_case_study_narrative",
        "WHERE nt.entity_id IN (SELECT entity_id FROM dirty)",
    ),
    (
        "am_law_article_summary",
        "WHERE nt.entity_id IN (SELECT entity_id FROM dirty)",
    ),
)


def _configure_logging() -> None:
    root = logging.getLogger("autonomath.cron.narrative_drift_detect")
    root.setLevel(logging.INFO)
    for h in list(root.handlers):
        root.removeHandler(h)
    fmt = logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s")
    sh = logging.StreamHandler(stream=sys.stderr)
    sh.setFormatter(fmt)
    root.addHandler(sh)


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone()
    return row is not None


def _quarantine_via_amendment_diff(conn: sqlite3.Connection, *, dry_run: bool) -> int:
    """INSERT one quarantine row per narrative whose underlying entity_id
    appears in am_amendment_diff in the last 30 days.

    Returns the count of rows that WOULD be inserted (dry_run=True) or
    that ACTUALLY were inserted by INSERT OR IGNORE (dry_run=False).
    """
    if not _table_exists(conn, "am_amendment_diff"):
        logger.warning("amendment_diff_missing skip=true")
        return 0
    inserted = 0
    for narrative_table, join_clause in _NARRATIVE_BACKLINKS:
        if not _table_exists(conn, narrative_table):
            continue
        select_sql = (
            "WITH dirty AS ( "
            "  SELECT DISTINCT entity_id FROM am_amendment_diff "
            "  WHERE detected_at >= datetime('now','-30 days') "
            ") "
            f"SELECT nt.narrative_id FROM {narrative_table} nt "
            f"{join_clause}"
        )
        try:
            rows = conn.execute(select_sql).fetchall()
        except sqlite3.OperationalError as exc:
            logger.warning(
                "drift_select_failed table=%s err=%s",
                narrative_table,
                str(exc)[:160],
            )
            continue
        if not rows:
            continue
        bucket_at = datetime.now(UTC).strftime("%Y-%m-%dT00:00:00+00:00")
        for (nid,) in rows:
            if dry_run:
                inserted += 1
                continue
            try:
                cur = conn.execute(
                    "INSERT OR IGNORE INTO am_narrative_quarantine("
                    "  narrative_id, narrative_table, reason, match_rate, detected_at"
                    ") VALUES (?, ?, 'corpus_drift', NULL, ?)",
                    (int(nid), narrative_table, bucket_at),
                )
                if cur.rowcount > 0:
                    inserted += 1
            except sqlite3.OperationalError as exc:
                logger.warning(
                    "drift_quarantine_insert_failed table=%s nid=%d err=%s",
                    narrative_table,
                    int(nid),
                    str(exc)[:160],
                )
        logger.info(
            "drift_amendment_diff table=%s candidate_rows=%d",
            narrative_table,
            len(rows),
        )
    return inserted


def _quarantine_via_content_hash(conn: sqlite3.Connection, *, dry_run: bool) -> int:
    """INSERT one quarantine row per narrative whose source_url backed entity
    has a fresh content_hash row within the last 30 days.

    am_source.content_hash is the per-fetch fingerprint maintained by the
    refresh_sources cron. When it changes, the underlying primary-source
    document changed (typo, eligibility tweak, fee-table edit) and any
    narrative cached above that document is potentially stale.
    """
    if not _table_exists(conn, "am_source"):
        logger.warning("am_source_missing skip=true")
        return 0
    if not _table_exists(conn, "am_program_narrative"):
        return 0
    inserted = 0
    bucket_at = datetime.now(UTC).strftime("%Y-%m-%dT00:00:00+00:00")
    try:
        rows = conn.execute(
            "WITH dirty_src AS ( "
            "  SELECT DISTINCT s.source_id FROM am_source s "
            "  WHERE s.content_hash IS NOT NULL "
            "    AND s.last_verified IS NOT NULL "
            "    AND s.last_verified >= datetime('now','-30 days') "
            "    AND EXISTS ( "
            "      SELECT 1 FROM am_source s2 "
            "      WHERE s2.url = s.url AND s2.source_id < s.source_id "
            "        AND s2.content_hash IS NOT NULL "
            "        AND s2.content_hash <> s.content_hash "
            "    ) "
            ") "
            "SELECT DISTINCT npn.narrative_id "
            "FROM am_program_narrative npn "
            "JOIN am_entity_source aes "
            "  ON aes.entity_id IN ( "
            "    SELECT canonical_id FROM programs WHERE id = npn.program_id "
            "  ) "
            "WHERE aes.source_id IN (SELECT source_id FROM dirty_src)"
        ).fetchall()
    except sqlite3.OperationalError as exc:
        logger.warning("content_hash_select_failed err=%s", str(exc)[:160])
        return 0
    for (nid,) in rows:
        if dry_run:
            inserted += 1
            continue
        try:
            cur = conn.execute(
                "INSERT OR IGNORE INTO am_narrative_quarantine("
                "  narrative_id, narrative_table, reason, match_rate, detected_at"
                ") VALUES (?, 'am_program_narrative', 'corpus_drift', NULL, ?)",
                (int(nid), bucket_at),
            )
            if cur.rowcount > 0:
                inserted += 1
        except sqlite3.OperationalError as exc:
            logger.warning(
                "content_hash_quarantine_insert_failed nid=%d err=%s",
                int(nid),
                str(exc)[:160],
            )
    logger.info("drift_content_hash candidate_rows=%d", len(rows))
    return inserted


def run(*, db_path: Path, dry_run: bool) -> dict:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        a = _quarantine_via_amendment_diff(conn, dry_run=dry_run)
        b = _quarantine_via_content_hash(conn, dry_run=dry_run)
        if not dry_run:
            conn.commit()
        return {
            "quarantined_amendment_diff": a,
            "quarantined_content_hash": b,
            "total_quarantined": a + b,
            "dry_run": dry_run,
        }
    finally:
        conn.close()


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="§10.10 corpus-drift narrative quarantine cron")
    p.add_argument(
        "--am-db",
        type=Path,
        default=None,
        help="Path to autonomath.db (default: settings.autonomath_db_path)",
    )
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    _configure_logging()
    args = _parse_args(argv)
    db_path = args.am_db if args.am_db else Path(str(settings.autonomath_db_path))
    with heartbeat("narrative_drift_detect") as hb:
        try:
            counters = run(db_path=db_path, dry_run=bool(args.dry_run))
        except Exception as e:
            logger.exception("narrative_drift_detect_failed err=%s", e)
            return 1
        hb["rows_processed"] = int(counters.get("total_quarantined", 0) or 0)
        hb["metadata"] = counters
    logger.info("drift_done %s", counters)
    return 0


if __name__ == "__main__":
    sys.exit(main())
