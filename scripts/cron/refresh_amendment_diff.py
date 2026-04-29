#!/usr/bin/env python3
"""Append-only amendment diff refresher (Z3 — replace phantom moat).

What it does:
  Walks active programs in autonomath.db, recomputes a deterministic
  per-field hash from the LIVE `am_entity_facts` snapshot, and INSERTs
  one row into `am_amendment_diff` per (entity_id, field_name) where
  the new hash differs from the most-recent recorded hash.

Why this exists:
  Z3 audit (2026-04-28) confirmed `am_amendment_snapshot` advertises a
  per-program time-series of eligibility changes but 100% of v1/v2 pairs
  share the SAME `eligibility_hash` — the time-series is fake. This cron
  populates the real append-only diff log added by migration 075.

Idempotency contract:
  Running twice in a row when nothing changed => second run inserts ZERO
  rows. The first run on a fresh diff table inserts one row per
  (entity_id, field_name) with prev_hash=NULL (the initial baseline).

Field set (TRACKED_FIELDS):
  We track a deliberately narrow set of fields whose changes constitute
  meaningful eligibility movement:
    * 'amount_max_yen'                    (補助上限額)
    * 'subsidy_rate_max'                  (補助率上限)
    * 'program.target_entity'             (対象事業者)
    * 'program.target_business_size'      (対象事業規模)
    * 'program.application_period'        (申請期間)
    * 'program.application_period_r7'     (申請期間R7)
    * 'program.application_channel'       (申請窓口)
    * 'program.prerequisite'              (前提条件)
    * 'program.subsidy_rate'              (補助率本文)
    * 'eligibility_text'                  (合成: target_entity + prerequisite + target_business_size,
                                            for the X9 Hygiene moat layer)
  Cosmetic fields (record_kind_original_guess, doc.form_url_direct,
  source_excerpt) are intentionally NOT tracked — they churn without
  representing any change in customer-visible eligibility.

Constraints:
  * No Anthropic / claude / SDK calls. Pure SQLite + standard library.
  * Append-only on am_amendment_diff: never UPDATE, never DELETE.
  * Single rw connection to autonomath.db (the diff table lives there
    alongside am_entity_facts, no cross-DB join needed).
  * Idempotent: re-running with no changes inserts 0 rows.

Usage:
    python scripts/cron/refresh_amendment_diff.py            # full run (active programs)
    python scripts/cron/refresh_amendment_diff.py --dry-run  # log only, no INSERT
    python scripts/cron/refresh_amendment_diff.py --limit 10 # first N programs (test mode)
"""
from __future__ import annotations

import argparse
import hashlib
import logging
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import sqlite3

# Allow running as a script without `pip install -e .`.
_REPO = Path(__file__).resolve().parent.parent.parent
_SRC = _REPO / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from jpintel_mcp.config import settings  # noqa: E402
from jpintel_mcp.db.session import connect  # noqa: E402
from jpintel_mcp.observability import heartbeat  # noqa: E402

logger = logging.getLogger("autonomath.cron.refresh_amendment_diff")


# ---------------------------------------------------------------------------
# Fields whose changes count as a meaningful amendment.
#
# Order matters for the synthetic 'eligibility_text' aggregate below — keep
# this list deterministic so re-runs hash identically.
# ---------------------------------------------------------------------------
TRACKED_FIELDS: tuple[str, ...] = (
    "amount_max_yen",
    "subsidy_rate_max",
    "program.target_entity",
    "program.target_business_size",
    "program.application_period",
    "program.application_period_r7",
    "program.application_channel",
    "program.prerequisite",
    "program.subsidy_rate",
)

# Components that synthesize 'eligibility_text' (the X9 Hygiene moat
# layer's headline field). These three concatenate (in order) into a
# single canonical string whose hash is the real eligibility fingerprint.
ELIGIBILITY_TEXT_COMPONENTS: tuple[str, ...] = (
    "program.target_entity",
    "program.target_business_size",
    "program.prerequisite",
)


def _configure_logging() -> None:
    root = logging.getLogger("autonomath.cron.refresh_amendment_diff")
    root.setLevel(logging.INFO)
    for h in list(root.handlers):
        root.removeHandler(h)
    fmt = logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s")
    sh = logging.StreamHandler(stream=sys.stderr)
    sh.setFormatter(fmt)
    root.addHandler(sh)


def _sha256(value: str | None) -> str | None:
    """sha256 of a value, or None when value is None.

    NOT lowercased, NOT trimmed beyond what the caller did. The caller is
    responsible for canonicalization — we only hash. This keeps the hash
    deterministic across cron runs as long as the canonicalization is.
    """
    if value is None:
        return None
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _canonical_value(rows: list[sqlite3.Row]) -> str | None:
    """Canonicalize a set of fact rows into a single deterministic string.

    Multiple rows for the same (entity_id, field_name) are joined with a
    sentinel separator after sorting. Missing field => return None (the
    field disappeared / was never set).
    """
    if not rows:
        return None
    parts: list[str] = []
    for r in rows:
        if r["field_value_text"] is not None:
            parts.append(str(r["field_value_text"]))
        elif r["field_value_numeric"] is not None:
            # Render numerics deterministically — avoid '1.0' vs '1' drift.
            n = r["field_value_numeric"]
            if n == int(n):
                parts.append(str(int(n)))
            else:
                parts.append(repr(n))
        else:
            parts.append("")
    parts.sort()
    return "\x1e".join(parts)


def _read_field_value(
    conn: sqlite3.Connection, entity_id: str, field_name: str
) -> str | None:
    """Pull all am_entity_facts rows for (entity_id, field_name) and canonicalize."""
    rows = conn.execute(
        """
        SELECT field_value_text, field_value_numeric
          FROM am_entity_facts
         WHERE entity_id = ? AND field_name = ?
        """,
        (entity_id, field_name),
    ).fetchall()
    return _canonical_value(rows)


def _read_eligibility_text(conn: sqlite3.Connection, entity_id: str) -> str | None:
    """Synthesize the headline 'eligibility_text' from component fields.

    Concatenates target_entity + target_business_size + prerequisite (in
    fixed order). When all three are absent we return None — the program
    has no recorded eligibility, which is itself a meaningful signal but
    one we represent as field-absent rather than empty-string.
    """
    parts: list[str] = []
    any_present = False
    for component in ELIGIBILITY_TEXT_COMPONENTS:
        v = _read_field_value(conn, entity_id, component)
        if v is not None:
            any_present = True
            parts.append(v)
        else:
            parts.append("")
    if not any_present:
        return None
    return "\x1f".join(parts)


def _last_recorded_hash(
    conn: sqlite3.Connection, entity_id: str, field_name: str
) -> str | None:
    """Most recent new_hash for (entity_id, field_name) in am_amendment_diff.

    Returns None when the field has never been recorded — the cron treats
    that as "first observation" and inserts a baseline row with prev_hash
    = NULL.
    """
    row = conn.execute(
        """
        SELECT new_hash
          FROM am_amendment_diff
         WHERE entity_id = ? AND field_name = ?
         ORDER BY detected_at DESC, diff_id DESC
         LIMIT 1
        """,
        (entity_id, field_name),
    ).fetchone()
    return row["new_hash"] if row else None


def _last_recorded_value(
    conn: sqlite3.Connection, entity_id: str, field_name: str
) -> str | None:
    """Most recent new_value alongside _last_recorded_hash. Used for prev_value."""
    row = conn.execute(
        """
        SELECT new_value
          FROM am_amendment_diff
         WHERE entity_id = ? AND field_name = ?
         ORDER BY detected_at DESC, diff_id DESC
         LIMIT 1
        """,
        (entity_id, field_name),
    ).fetchone()
    return row["new_value"] if row else None


def _select_active_programs(
    conn: sqlite3.Connection, limit: int | None
) -> list[sqlite3.Row]:
    """Active programs in autonomath.db, with the source_url for provenance."""
    sql = """
        SELECT canonical_id, source_url
          FROM am_entities
         WHERE record_kind = 'program'
           AND canonical_status = 'active'
         ORDER BY canonical_id
    """
    if limit is not None:
        sql += f" LIMIT {int(limit)}"
    return conn.execute(sql).fetchall()


def _diff_one_program(
    conn: sqlite3.Connection,
    entity_id: str,
    source_url: str | None,
    dry_run: bool,
) -> int:
    """Compare current facts to last recorded hashes; INSERT diff rows.

    Returns the number of diff rows inserted (or that would be inserted in
    dry-run mode).
    """
    inserted = 0

    # Build the (field_name, current_canonical_value) list for this program.
    current_values: list[tuple[str, str | None]] = []
    for field_name in TRACKED_FIELDS:
        current_values.append((field_name, _read_field_value(conn, entity_id, field_name)))
    current_values.append(("eligibility_text", _read_eligibility_text(conn, entity_id)))

    for field_name, new_value in current_values:
        new_hash = _sha256(new_value)
        prev_hash = _last_recorded_hash(conn, entity_id, field_name)

        if prev_hash is None:
            # First observation — only record a baseline if the field is
            # actually present. Inserting a NULL/NULL row would just be
            # noise; an absent field with no history simply hasn't been
            # observed and stays out of the log until it appears.
            if new_hash is None:
                continue
            prev_value = None
        else:
            if new_hash == prev_hash:
                # No meaningful change. Idempotent skip — this is the path
                # a same-day re-run takes for every untouched program.
                continue
            prev_value = _last_recorded_value(conn, entity_id, field_name)

        if dry_run:
            logger.info(
                "would_insert entity=%s field=%s prev_hash=%s new_hash=%s",
                entity_id,
                field_name,
                (prev_hash or "")[:12],
                (new_hash or "")[:12],
            )
            inserted += 1
            continue

        conn.execute(
            """
            INSERT INTO am_amendment_diff (
                entity_id, field_name,
                prev_value, new_value,
                prev_hash, new_hash,
                source_url
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (entity_id, field_name, prev_value, new_value, prev_hash, new_hash, source_url),
        )
        inserted += 1

    return inserted


def run(
    am_db_path: Path,
    limit: int | None,
    dry_run: bool,
) -> dict[str, int]:
    """Iterate active programs, refresh diffs, return counters.

    Counters:
      * programs_scanned          — number of programs visited
      * diff_rows_inserted        — number of rows written (or "would_insert" in dry-run)
      * programs_with_change      — number of programs that produced >=1 diff row
    """
    if not am_db_path.is_file():
        logger.error("am_db_missing path=%s", am_db_path)
        return {"programs_scanned": 0, "diff_rows_inserted": 0, "programs_with_change": 0}

    conn = connect(am_db_path)
    try:
        # Confirm the diff table exists. If migration 075 hasn't been
        # applied yet, fail loudly rather than silently no-op.
        exists = conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name='am_amendment_diff'"
        ).fetchone()
        if exists is None:
            logger.error(
                "am_amendment_diff_missing path=%s "
                "did_you_apply_migration=075_am_amendment_diff.sql",
                am_db_path,
            )
            return {"programs_scanned": 0, "diff_rows_inserted": 0, "programs_with_change": 0}

        programs = _select_active_programs(conn, limit)
        logger.info(
            "diff_refresh_start db=%s programs=%d limit=%s dry_run=%s",
            am_db_path,
            len(programs),
            limit,
            dry_run,
        )

        total_inserted = 0
        with_change = 0

        if not dry_run:
            conn.execute("BEGIN")
        try:
            for p in programs:
                n = _diff_one_program(
                    conn=conn,
                    entity_id=p["canonical_id"],
                    source_url=p["source_url"],
                    dry_run=dry_run,
                )
                if n > 0:
                    with_change += 1
                    total_inserted += n
            if not dry_run:
                conn.execute("COMMIT")
        except Exception:
            if not dry_run:
                conn.execute("ROLLBACK")
            raise

        counters = {
            "programs_scanned": len(programs),
            "diff_rows_inserted": total_inserted,
            "programs_with_change": with_change,
        }
        logger.info(
            "diff_refresh_done programs=%d inserts=%d with_change=%d",
            counters["programs_scanned"],
            counters["diff_rows_inserted"],
            counters["programs_with_change"],
        )
        return counters
    finally:
        conn.close()


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Append-only amendment diff refresher (Z3 phantom-moat fix)"
    )
    p.add_argument(
        "--am-db",
        type=Path,
        default=None,
        help="Path to autonomath.db (default: settings.autonomath_db_path)",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Process only the first N active programs (test mode)",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Log diffs but do not INSERT",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    _configure_logging()
    args = _parse_args(argv)

    am_db_path = args.am_db if args.am_db else settings.autonomath_db_path

    with heartbeat("refresh_amendment_diff") as hb:
        try:
            counters = run(
                am_db_path=am_db_path,
                limit=args.limit,
                dry_run=bool(args.dry_run),
            )
        except Exception as e:
            logger.exception("amendment_diff_refresh_failed err=%s", e)
            return 1
        hb["rows_processed"] = int(counters.get("diff_rows_inserted", 0) or 0)
        hb["rows_skipped"] = int(
            (counters.get("programs_scanned", 0) or 0)
            - (counters.get("programs_with_change", 0) or 0)
        )
        hb["metadata"] = {
            "programs_scanned": counters.get("programs_scanned"),
            "programs_with_change": counters.get("programs_with_change"),
            "dry_run": bool(args.dry_run),
        }
    return 0


if __name__ == "__main__":
    sys.exit(main())
