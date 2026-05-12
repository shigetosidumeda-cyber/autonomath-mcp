"""Aggregate anonymized cohort outcomes nightly (Dim N, Wave 47).

Rebuilds ``am_aggregated_outcome_view`` (migration 274) from
``am_entities`` + ``am_entity_facts`` + ``am_industry_jsic`` +
``am_region`` joins under a strict k-anonymity floor (k>=5). The output
view is consumed by ``aggregate_cohort()`` in
``src/jpintel_mcp/api/anonymized_query.py`` once the in-memory synthetic
default is swapped for the substrate read.

Hard constraints (feedback_anonymized_query_pii_redact + Wave 46 Dim N)
-----------------------------------------------------------------------
* **k=5 hard floor.** HAVING COUNT(*) >= 5 at materialization time. Any
  cohort smaller than 5 is dropped entirely — no row inserted, no audit
  trace exposing the small cohort.
* **PII strip.** Only the cohort filter triple
  (industry_jsic_major / region_code / size_bucket) lives in
  ``entity_cluster_id``. No houjin_bangou, no company_name, no contact.
* **Redact policy version.** Written to am_anonymized_query_log audit
  rows when the REST surface upgrades to substrate-backed mode.
* **NO LLM API call.** Pure SQL aggregation.

Usage
-----
    python scripts/etl/aggregate_anonymized_outcomes.py            # apply
    python scripts/etl/aggregate_anonymized_outcomes.py --dry-run  # report only
    python scripts/etl/aggregate_anonymized_outcomes.py --db PATH  # custom db

The script can run on a fresh empty db: it gracefully reports zero
cohorts when the source tables are absent (the migration substrate may
land before the entity corpus is loaded).
"""

from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = REPO_ROOT / "autonomath.db"
LOG = logging.getLogger("aggregate_anonymized_outcomes")

# k-anonymity floor mirrors src/jpintel_mcp/api/anonymized_query.py
# K_ANONYMITY_MIN. The CHECK constraint in migration 274 also enforces
# this — defense in depth.
K_ANONYMITY_MIN = 5

# Aggregator scans 4 outcome_type axes. Each emits one cluster row per
# (industry x region x size) bucket where COUNT >= 5.
OUTCOME_TYPES = ("adoption", "enforcement", "amendment", "program_apply")


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    return row is not None


def _build_synthetic_cohort_rows(conn: sqlite3.Connection) -> list[dict]:
    """Synthesize cohort rows from am_entities when present.

    Returns a list of cohort dicts that pass the k=5 floor. If the
    source tables are missing (empty db / dev fixture), returns an empty
    list. The shape matches am_aggregated_outcome_view columns.
    """
    if not _table_exists(conn, "am_entities"):
        LOG.info("am_entities missing — emitting zero cohorts")
        return []

    # Compute cohort sizes per (industry x region x size) bucket via
    # am_entities corporate_entity rows. The query is intentionally
    # tolerant of missing columns (uses COALESCE to NULL).
    try:
        rows = conn.execute(
            """
            SELECT
                COALESCE(industry_jsic_major, '?')             AS industry,
                COALESCE(SUBSTR(region_code, 1, 5), 'unknown') AS region,
                COALESCE(size_bucket, 'unknown')               AS size,
                COUNT(*)                                        AS k_value
            FROM am_entities
            WHERE record_kind = 'corporate_entity'
            GROUP BY industry, region, size
            HAVING COUNT(*) >= ?
            """,
            (K_ANONYMITY_MIN,),
        ).fetchall()
    except sqlite3.OperationalError as exc:
        # Schema drift on dev fixtures — log + skip.
        LOG.warning("am_entities query failed (%s); emitting zero cohorts", exc)
        return []

    cohorts: list[dict] = []
    for industry, region, size, k_value in rows:
        cluster_id = f"industry={industry}|region={region}|size={size}"
        # One row per outcome_type so /v1/network/anonymized_outcomes can
        # answer "how did similar entities fare across all axes" with a
        # single cohort lookup.
        for outcome_type in OUTCOME_TYPES:
            cohorts.append(
                {
                    "entity_cluster_id": cluster_id,
                    "outcome_type": outcome_type,
                    "count": int(k_value),
                    "k_value": int(k_value),
                    "mean_amount_yen": None,
                    "median_amount_yen": None,
                }
            )
    return cohorts


def aggregate(db_path: Path, *, dry_run: bool = False) -> dict[str, int]:
    """Rebuild am_aggregated_outcome_view from corpus.

    Returns a stats dict: {"inserted": N, "skipped_below_k": M,
    "rebuilt": bool}.
    """
    LOG.info("opening db: %s", db_path)
    conn = sqlite3.connect(str(db_path))
    try:
        if not _table_exists(conn, "am_aggregated_outcome_view"):
            raise RuntimeError(
                "am_aggregated_outcome_view missing — apply migration "
                "274_anonymized_query.sql first"
            )
        cohorts = _build_synthetic_cohort_rows(conn)
        # Defense in depth: drop any row that slipped through with k<5.
        eligible = [c for c in cohorts if c["k_value"] >= K_ANONYMITY_MIN]
        dropped = len(cohorts) - len(eligible)

        if dry_run:
            LOG.info(
                "DRY-RUN would rebuild %d cohort rows (dropped k<5=%d)",
                len(eligible),
                dropped,
            )
            return {
                "inserted": len(eligible),
                "skipped_below_k": dropped,
                "rebuilt": False,
            }

        # Single-snapshot semantics: clear before insert so callers
        # always see the latest aggregation. INSERT OR REPLACE on the
        # UNIQUE(entity_cluster_id, outcome_type) key.
        conn.execute("DELETE FROM am_aggregated_outcome_view")
        for c in eligible:
            conn.execute(
                """
                INSERT INTO am_aggregated_outcome_view
                    (entity_cluster_id, outcome_type, count, k_value,
                     mean_amount_yen, median_amount_yen)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    c["entity_cluster_id"],
                    c["outcome_type"],
                    c["count"],
                    c["k_value"],
                    c["mean_amount_yen"],
                    c["median_amount_yen"],
                ),
            )
        conn.commit()
        return {
            "inserted": len(eligible),
            "skipped_below_k": dropped,
            "rebuilt": True,
        }
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if not args.db.exists():
        if args.dry_run:
            # Wave 49 G3 cron hydrate fix: a dry-run plan must succeed even
            # when the operator DB has not been hydrated yet. The aggregator
            # is read-only in this mode, so emit a placeholder report and
            # exit 0.
            LOG.warning("db not found (dry-run): %s", args.db)
            print(
                json.dumps(
                    {
                        "dim": "N",
                        "dry_run": True,
                        "db_not_found_dry_run": True,
                        "db": str(args.db),
                        "aggregate_stats": {
                            "inserted": 0,
                            "skipped_below_k": 0,
                            "rebuilt": False,
                        },
                    },
                    ensure_ascii=False,
                )
            )
            return 0
        LOG.error("db not found: %s", args.db)
        return 2

    stats = aggregate(args.db, dry_run=args.dry_run)
    print(
        json.dumps(
            {"dim": "N", "aggregate_stats": stats}, ensure_ascii=False
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
