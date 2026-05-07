#!/usr/bin/env python3
"""Precompute /v1/stats/data_quality snapshot (W14-4 latent concern fix).

What this fixes
---------------
The /v1/stats/data_quality handler aggregated `am_uncertainty_view`
(migration 069) and the 97k+ row `am_source` table inline on every
request. On the 9.4 GB autonomath.db production volume that walk
exceeds the Fly grace 60 s window — same failure mode as the
2026-05-03 SQLite quick_check incident captured in memory
`feedback_no_quick_check_on_huge_sqlite`.

This script computes the rollup once per day and parks one row in
`am_data_quality_snapshot` (migration wave24_145). The handler then
serves the cached row via a single-row SELECT in ~1 ms regardless of
upstream growth.

Why a precompute (not request-time)
-----------------------------------
* Aggregation is read-only and only changes meaningfully day-to-day
  (license fill from ingest cron, freshness drift from `first_seen`
  ageing). Daily granularity is plenty for a transparency surface.
* The existing am_uncertainty_view + am_source fallback logic is
  preserved verbatim — we just move it from the request thread to a
  background cron so request latency never depends on autonomath.db
  size.
* Per CLAUDE.md and `feedback_autonomath_no_api_use`, NO LLM SDK calls
  are made here. Pure SQLite + standard library, same posture as the
  other precompute crons.

Invocation
----------
    python scripts/cron/precompute_data_quality.py
    python scripts/cron/precompute_data_quality.py --dry-run
    python scripts/cron/precompute_data_quality.py --am-db /path/to/autonomath.db

Schedule
--------
.github/workflows/precompute-data-quality-daily.yml runs at 05:05 JST
(20:05 UTC) — 5 minutes off the 0500 JST analytics-cron slot.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import logging
import sqlite3
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Allow running as a script without `pip install -e .`.
_REPO = Path(__file__).resolve().parent.parent.parent
_SRC = _REPO / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from jpintel_mcp.api.uncertainty import score_fact  # noqa: E402
from jpintel_mcp.config import settings  # noqa: E402

logger = logging.getLogger("autonomath.cron.precompute_data_quality")


# Mirror of api/stats.py::_FRESHNESS_BUCKETS so the cron and the handler
# always agree on label names. Tuples are (label, max_inclusive_days).
_FRESHNESS_BUCKETS: list[tuple[str, int | None]] = [
    ("<=30d", 30),
    ("31-180d", 180),
    ("181-365d", 365),
    (">365d", None),
]

# Source-URL freshness threshold (days). Matches the trust-signal copy
# on the dashboard ("fetched within last 30 days").
_FRESH_PCT_WINDOW_DAYS = 30


def _freshness_bucket_for(days: int | None) -> str:
    if days is None or days < 0:
        return "unknown"
    for label, upper in _FRESHNESS_BUCKETS:
        if upper is None:
            return label
        if days <= upper:
            return label
    return ">365d"


def _compute_snapshot(am_conn: sqlite3.Connection) -> dict[str, Any]:
    """Build the rollup payload that mirrors the handler's response shape.

    Returns a dict with the exact keys persisted into
    `am_data_quality_snapshot`. The handler reads them back unchanged.
    """
    label_hist: dict[str, int] = {"high": 0, "medium": 0, "low": 0, "unknown": 0}
    license_hist: dict[str, int] = {}
    fresh_hist: dict[str, int] = {label: 0 for label, _ in _FRESHNESS_BUCKETS}
    fresh_hist["unknown"] = 0
    kind_acc: dict[str, dict[str, float]] = {}

    fact_count = 0
    score_sum = 0.0
    n_pairs_multi = 0
    n_pairs_agree = 0
    fallback_reason: str | None = None
    fallback_total_sources: int | None = None

    # 1) Walk am_uncertainty_view (migration 069). On volumes where the
    # view is missing we fall through to the am_source-only aggregation
    # below — exact mirror of the legacy handler logic.
    try:
        cursor = am_conn.execute(
            "SELECT field_kind, license, days_since_fetch, "
            "       n_sources, agreement "
            "  FROM am_uncertainty_view"
        )
        for row in cursor:
            try:
                field_kind = row["field_kind"]
                license_value = row["license"]
                days_since_fetch = row["days_since_fetch"]
                n_sources = row["n_sources"]
                agreement = row["agreement"]
            except (TypeError, IndexError):
                field_kind, license_value, days_since_fetch, n_sources, agreement = (
                    row[0],
                    row[1],
                    row[2],
                    row[3],
                    row[4],
                )
            unc = score_fact(
                field_kind=field_kind,
                license_value=license_value,
                days_since_fetch=(int(days_since_fetch) if days_since_fetch is not None else None),
                n_sources=int(n_sources or 0),
                agreement=int(agreement or 0),
            )
            fact_count += 1
            score_sum += float(unc["score"])
            label_hist[unc["label"]] = label_hist.get(unc["label"], 0) + 1
            lic_key = license_value or "null_source"
            license_hist[lic_key] = license_hist.get(lic_key, 0) + 1
            fresh_label = _freshness_bucket_for(
                int(days_since_fetch) if days_since_fetch is not None else None
            )
            fresh_hist[fresh_label] = fresh_hist.get(fresh_label, 0) + 1
            kk = field_kind or "unknown"
            bucket = kind_acc.setdefault(kk, {"count": 0.0, "sum": 0.0})
            bucket["count"] += 1
            bucket["sum"] += float(unc["score"])
            if int(n_sources or 0) >= 2:
                n_pairs_multi += 1
                if int(agreement or 0) == 1:
                    n_pairs_agree += 1
    except sqlite3.OperationalError:
        fallback_reason = "am_uncertainty_view_missing"

    # 2) Fallback aggregation directly off am_source. Same shape as the
    # legacy `_am_source_fallback_aggregates` helper.
    if fact_count == 0:
        try:
            license_rows = am_conn.execute(
                "SELECT COALESCE(license, 'null_source') AS lic, "
                "       COUNT(*) AS n "
                "  FROM am_source "
                " GROUP BY COALESCE(license, 'null_source')"
            ).fetchall()
            # Index by position so we don't depend on the row factory
            # supporting key lookup (sqlite3.Row vs plain tuple).
            license_hist = {str(r[0]): int(r[1]) for r in license_rows}
            fallback_total_sources = sum(license_hist.values())

            fresh_hist = {label: 0 for label, _ in _FRESHNESS_BUCKETS}
            fresh_hist["unknown"] = 0
            today = datetime.now(UTC).date()
            for row in am_conn.execute("SELECT first_seen FROM am_source"):
                try:
                    first_seen = row["first_seen"]
                except (TypeError, IndexError):
                    first_seen = row[0]
                days: int | None = None
                if first_seen:
                    try:
                        seen_date = datetime.fromisoformat(
                            str(first_seen).replace("Z", "+00:00")
                        ).date()
                        days = (today - seen_date).days
                    except (ValueError, TypeError):
                        days = None
                label = _freshness_bucket_for(days)
                fresh_hist[label] = fresh_hist.get(label, 0) + 1

            if fallback_reason is None:
                fallback_reason = "am_uncertainty_view_empty"
        except sqlite3.OperationalError:
            if fallback_reason is None:
                fallback_reason = "am_source_missing"

    # 3) Source URL freshness percentage — share of am_source rows whose
    # first_seen falls within the last _FRESH_PCT_WINDOW_DAYS days. Used
    # by the trust-signal page; cron computes once and parks it here.
    source_url_freshness_pct: float | None = None
    source_count = 0
    try:
        row = am_conn.execute("SELECT COUNT(*) FROM am_source").fetchone()
        source_count = int(row[0]) if row else 0
        if source_count > 0:
            row = am_conn.execute(
                "SELECT COUNT(*) FROM am_source "
                " WHERE first_seen IS NOT NULL "
                "   AND julianday('now') - julianday(first_seen) <= ?",
                (_FRESH_PCT_WINDOW_DAYS,),
            ).fetchone()
            fresh_n = int(row[0]) if row else 0
            source_url_freshness_pct = round(fresh_n / source_count, 4)
    except sqlite3.OperationalError:
        pass

    kind_breakdown: dict[str, dict[str, Any]] = {}
    for k, agg in kind_acc.items():
        count = int(agg["count"])
        mean = (agg["sum"] / count) if count > 0 else 0.0
        kind_breakdown[k] = {"count": count, "mean_score": round(mean, 4)}

    agreement_rate = (n_pairs_agree / n_pairs_multi) if n_pairs_multi > 0 else 0.0

    fallback_note: str | None = None
    if fallback_reason is not None:
        fallback_note = (
            "am_uncertainty_view did not yield per-fact rows on this "
            "DB volume; license_breakdown + freshness_buckets are "
            "computed directly from am_source as an honest fallback "
            "so trust-signal callers do not see all-zeros. "
            "mean_score / label_histogram / cross_source_agreement "
            "remain at 0 because per-fact scoring needs the view. "
            "See /v1/am/data-freshness for the per-dataset breakdown."
        )

    return {
        "source_count": source_count,
        "fact_count_total": fact_count,
        "mean_score": (round(score_sum / fact_count, 4) if fact_count > 0 else None),
        "label_histogram": label_hist,
        "license_breakdown": license_hist,
        "freshness_buckets": fresh_hist,
        "field_kind_breakdown": kind_breakdown,
        "cross_source_agreement": {
            "facts_with_n_sources_>=2": n_pairs_multi,
            "facts_with_consistent_value": n_pairs_agree,
            "agreement_rate": round(agreement_rate, 4),
        },
        "source_url_freshness_pct": source_url_freshness_pct,
        "fallback_source": fallback_reason,
        "fallback_note": fallback_note,
        "am_source_total_rows": fallback_total_sources,
        "model": "beta_posterior_v1",
    }


def _persist(am_conn: sqlite3.Connection, payload: dict[str, Any], compute_ms: int) -> str:
    """Insert one snapshot row and return the snapshot_at timestamp."""
    snapshot_at = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    am_conn.execute(
        """
        INSERT INTO am_data_quality_snapshot (
            snapshot_at, source_count, fact_count_total, mean_score,
            label_histogram_json, license_breakdown_json,
            freshness_buckets_json, field_kind_breakdown_json,
            cross_source_agreement_json, source_url_freshness_pct,
            fallback_source, fallback_note, am_source_total_rows,
            model, compute_ms
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(snapshot_at) DO UPDATE SET
            source_count = excluded.source_count,
            fact_count_total = excluded.fact_count_total,
            mean_score = excluded.mean_score,
            label_histogram_json = excluded.label_histogram_json,
            license_breakdown_json = excluded.license_breakdown_json,
            freshness_buckets_json = excluded.freshness_buckets_json,
            field_kind_breakdown_json = excluded.field_kind_breakdown_json,
            cross_source_agreement_json = excluded.cross_source_agreement_json,
            source_url_freshness_pct = excluded.source_url_freshness_pct,
            fallback_source = excluded.fallback_source,
            fallback_note = excluded.fallback_note,
            am_source_total_rows = excluded.am_source_total_rows,
            model = excluded.model,
            compute_ms = excluded.compute_ms
        """,
        (
            snapshot_at,
            int(payload["source_count"]),
            int(payload["fact_count_total"]),
            payload["mean_score"],
            json.dumps(payload["label_histogram"], ensure_ascii=False),
            json.dumps(payload["license_breakdown"], ensure_ascii=False),
            json.dumps(payload["freshness_buckets"], ensure_ascii=False),
            json.dumps(payload["field_kind_breakdown"], ensure_ascii=False),
            json.dumps(payload["cross_source_agreement"], ensure_ascii=False),
            payload["source_url_freshness_pct"],
            payload["fallback_source"],
            payload["fallback_note"],
            payload["am_source_total_rows"],
            payload["model"],
            int(compute_ms),
        ),
    )
    am_conn.commit()
    return snapshot_at


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--am-db",
        type=Path,
        default=None,
        help="Path to autonomath.db (default: settings.autonomath_db_path).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute the snapshot but do not write it.",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        help="Python logging level (default: INFO).",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=args.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    am_db = args.am_db if args.am_db else settings.autonomath_db_path
    if not Path(am_db).exists():
        logger.error("autonomath.db not found at %s", am_db)
        return 2

    am_conn = sqlite3.connect(str(am_db))
    am_conn.row_factory = sqlite3.Row
    try:
        t0 = time.monotonic()
        payload = _compute_snapshot(am_conn)
        compute_ms = int((time.monotonic() - t0) * 1000)
        logger.info(
            "computed data_quality snapshot in %d ms (facts=%d, sources=%d, fallback=%s)",
            compute_ms,
            payload["fact_count_total"],
            payload["source_count"],
            payload["fallback_source"],
        )

        if args.dry_run:
            logger.info("dry-run: snapshot=%s", json.dumps(payload, ensure_ascii=False))
            return 0

        snapshot_at = _persist(am_conn, payload, compute_ms)
        logger.info("persisted snapshot at %s", snapshot_at)
    finally:
        with contextlib.suppress(Exception):
            am_conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
