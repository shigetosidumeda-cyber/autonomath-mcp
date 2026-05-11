#!/usr/bin/env python3
"""Dim I per-fact cross-source agreement refresher (migration 265).

Sister cron of `scripts/cron/cross_source_check.py`. Where the legacy
sibling refreshes ``am_entity_facts.confirming_source_count`` (a single
integer), this cron writes a per-fact materialization into the new
``am_fact_source_agreement`` table (migration 265, Wave 43.2.9). Each row
carries ``agreement_ratio`` (0.0..1.0 = sources_agree / sources_total),
canonical_value (the mode across distinct sources), per-source canonical
values (egov / nta / meti / other), and a JSON breakdown.

Why split from `cross_source_check.py`
--------------------------------------
The legacy cron carries a delicate baseline gate (migration 107) and a
fragile correction_log emit guard. Adding the per-fact upsert there
risks regressing the existing safety properties. This cron is **purely
additive**: it reads from `am_entity_facts` + `am_source`, writes to
`am_fact_source_agreement` + `am_fact_source_agreement_run_log`, and
never touches the legacy regression / correction_log path.

Source classification buckets
-----------------------------
Every am_source row is bucketed into one of four kinds based on host:
  * e-Gov: `e-gov.go.jp`, `elaws.e-gov.go.jp`
  * NTA  : `nta.go.jp`, `houjin-bangou.nta.go.jp`, `invoice-kohyo.nta.go.jp`
  * METI : `meti.go.jp`, `smrj.go.jp`
  * other: every other first-party government host (MAFF / MOF / MOFA /
            自治体 lg.jp / 公庫 / etc.). Aggregator hosts are banned at
            ingest time and never appear here.

Cron cadence
------------
Hourly (chained after `cross_source_check.py`). Each run upserts up to
``--limit`` rows (default 100,000), ordered by descending distinct-source
count so high-value cross-confirmed facts refresh first. The full 6.12M
fact universe amortizes over many runs.

NO LLM / NO auto-translate
--------------------------
Pure SQL + Python aggregation. The mode (Counter.most_common(1)) is the
canonical_value; no on-the-fly translation, no LLM rewording.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

logger = logging.getLogger("autonomath.cron.cross_source_agreement_check")

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_SRC = _REPO_ROOT / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
from jpintel_mcp.observability import heartbeat  # noqa: E402

_DEFAULT_DB = Path(
    os.environ.get("AUTONOMATH_DB_PATH", str(_REPO_ROOT / "autonomath.db"))
)


def _open_rw(path: Path) -> sqlite3.Connection:
    if not path.exists():
        raise SystemExit(f"autonomath.db missing at {path}")
    conn = sqlite3.connect(str(path), timeout=30.0, isolation_level=None)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    return conn


def _classify_source(url: str | None, domain: str | None) -> str:
    """Map an am_source row to one of e-Gov / NTA / METI / other buckets."""
    host = ""
    if domain:
        host = domain.lower().strip()
    elif url:
        try:
            host = (urlparse(url).hostname or "").lower()
        except (ValueError, TypeError):
            host = ""
    if not host:
        return "other"
    if "e-gov.go.jp" in host or "elaws.e-gov.go.jp" in host:
        return "egov"
    if (
        "nta.go.jp" in host
        or "houjin-bangou.nta.go.jp" in host
        or "invoice-kohyo.nta.go.jp" in host
    ):
        return "nta"
    if "meti.go.jp" in host or "smrj.go.jp" in host:
        return "meti"
    return "other"


def _fact_canonical_value(rows: list[sqlite3.Row]) -> str | None:
    """Return the mode (most-frequent value) across a fact's source rows."""
    values: list[str] = []
    for r in rows:
        text = r["field_value_text"] if "field_value_text" in r.keys() else None
        num = (
            r["field_value_numeric"]
            if "field_value_numeric" in r.keys()
            else None
        )
        js = r["field_value_json"] if "field_value_json" in r.keys() else None
        if text is not None and str(text).strip():
            values.append(str(text).strip())
        elif num is not None:
            values.append(str(num))
        elif js is not None and str(js).strip():
            values.append(str(js).strip())
    if not values:
        return None
    counter = Counter(values)
    mode_value, _ = counter.most_common(1)[0]
    return mode_value


def _run(
    db_path: Path,
    *,
    dry_run: bool = False,
    limit: int = 100_000,
) -> dict[str, int]:
    """Upsert per-fact agreement rows into am_fact_source_agreement.

    Returns counts of facts scanned + facts upserted + facts skipped.
    Best-effort: if `am_fact_source_agreement` table is absent (older
    builds), returns immediately with ``table_missing=1``.
    """
    out = {
        "fact_scanned": 0,
        "fact_upserted": 0,
        "fact_skipped": 0,
        "table_missing": 0,
    }
    conn = _open_rw(db_path)
    try:
        try:
            conn.execute(
                "SELECT 1 FROM am_fact_source_agreement LIMIT 1"
            ).fetchone()
        except sqlite3.OperationalError as exc:
            logger.info(
                "am_fact_source_agreement missing — Dim I refresh skipped (%s)",
                exc,
            )
            out["table_missing"] = 1
            return out

        now = datetime.now(UTC).isoformat()

        try:
            groups = conn.execute(
                "SELECT entity_id, field_name, "
                "       COUNT(DISTINCT source_id) AS distinct_source_count "
                "FROM am_entity_facts "
                "WHERE entity_id IS NOT NULL AND field_name IS NOT NULL "
                "GROUP BY entity_id, field_name "
                "ORDER BY distinct_source_count DESC "
                "LIMIT ?",
                (int(limit),),
            ).fetchall()
        except sqlite3.OperationalError as exc:
            logger.warning("am_entity_facts unreadable: %s", exc)
            return out

        for g in groups:
            entity_id = g["entity_id"]
            field_name = g["field_name"]
            out["fact_scanned"] += 1
            try:
                rows = conn.execute(
                    "SELECT f.id AS fact_id, f.field_value_text, "
                    "       f.field_value_numeric, f.field_value_json, "
                    "       f.source_id, s.source_url, s.domain "
                    "FROM am_entity_facts f "
                    "LEFT JOIN am_source s ON s.id = f.source_id "
                    "WHERE f.entity_id = ? AND f.field_name = ?",
                    (entity_id, field_name),
                ).fetchall()
            except sqlite3.OperationalError as exc:
                logger.warning("agreement scan: row fetch failed: %s", exc)
                out["fact_skipped"] += 1
                continue
            if not rows:
                out["fact_skipped"] += 1
                continue
            canonical = _fact_canonical_value(rows)
            bucket_values: dict[str, list[str]] = {}
            for r in rows:
                kind = _classify_source(r["source_url"], r["domain"])
                val_text = (
                    r["field_value_text"]
                    or (
                        str(r["field_value_numeric"])
                        if r["field_value_numeric"] is not None
                        else None
                    )
                    or r["field_value_json"]
                )
                if val_text is None or not str(val_text).strip():
                    continue
                bucket_values.setdefault(kind, []).append(str(val_text).strip())
            breakdown_counts = {k: len(v) for k, v in bucket_values.items()}
            sources_total = sum(1 for v in bucket_values.values() if v)
            sources_agree = 0
            per_bucket_canon: dict[str, str | None] = {}
            for k, v in bucket_values.items():
                if not v:
                    per_bucket_canon[k] = None
                    continue
                mode_v, _ = Counter(v).most_common(1)[0]
                per_bucket_canon[k] = mode_v
                if canonical is not None and mode_v == canonical:
                    sources_agree += 1
            ratio = (
                sources_agree / sources_total if sources_total > 0 else 0.0
            )
            fact_id = int(rows[0]["fact_id"])
            if dry_run:
                continue
            try:
                conn.execute(
                    "INSERT INTO am_fact_source_agreement("
                    "  fact_id, entity_id, field_name, agreement_ratio, "
                    "  sources_total, sources_agree, canonical_value, "
                    "  source_breakdown, egov_value, nta_value, meti_value, "
                    "  other_value, computed_at"
                    ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?) "
                    "ON CONFLICT(fact_id) DO UPDATE SET "
                    "  agreement_ratio = excluded.agreement_ratio, "
                    "  sources_total = excluded.sources_total, "
                    "  sources_agree = excluded.sources_agree, "
                    "  canonical_value = excluded.canonical_value, "
                    "  source_breakdown = excluded.source_breakdown, "
                    "  egov_value = excluded.egov_value, "
                    "  nta_value = excluded.nta_value, "
                    "  meti_value = excluded.meti_value, "
                    "  other_value = excluded.other_value, "
                    "  computed_at = excluded.computed_at",
                    (
                        fact_id,
                        entity_id,
                        field_name,
                        float(ratio),
                        int(sources_total),
                        int(sources_agree),
                        canonical,
                        json.dumps(
                            breakdown_counts,
                            ensure_ascii=False,
                            sort_keys=True,
                        ),
                        per_bucket_canon.get("egov"),
                        per_bucket_canon.get("nta"),
                        per_bucket_canon.get("meti"),
                        per_bucket_canon.get("other"),
                        now,
                    ),
                )
                out["fact_upserted"] += 1
            except sqlite3.OperationalError as exc:
                logger.warning(
                    "agreement upsert failed for fact_id=%s: %s", fact_id, exc
                )
                out["fact_skipped"] += 1
                continue

        if not dry_run:
            try:
                conn.execute(
                    "INSERT INTO am_fact_source_agreement_run_log("
                    "  started_at, finished_at, facts_scanned, "
                    "  facts_upserted, facts_skipped, errors_count"
                    ") VALUES (?,?,?,?,?,?)",
                    (
                        now,
                        datetime.now(UTC).isoformat(),
                        int(out["fact_scanned"]),
                        int(out["fact_upserted"]),
                        int(out["fact_skipped"]),
                        0,
                    ),
                )
            except sqlite3.OperationalError as exc:
                logger.debug("agreement run log write failed: %s", exc)
    finally:
        conn.close()
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=_DEFAULT_DB)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--limit",
        type=int,
        default=100_000,
        help=(
            "Max (entity, field) groups to upsert per run. Sorted by "
            "descending distinct-source count so high-value facts "
            "refresh first."
        ),
    )
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    with heartbeat("cross_source_agreement_check") as hb:
        res = _run(args.db, dry_run=args.dry_run, limit=int(args.limit))
        logger.info(
            "cross_source_agreement_check: scanned=%(fact_scanned)d "
            "upserted=%(fact_upserted)d skipped=%(fact_skipped)d "
            "table_missing=%(table_missing)d",
            res,
        )
        hb["rows_processed"] = int(res.get("fact_upserted", 0) or 0)
        hb["rows_skipped"] = int(res.get("fact_skipped", 0) or 0)
        hb["metadata"] = {
            "fact_scanned": res.get("fact_scanned"),
            "fact_upserted": res.get("fact_upserted"),
            "fact_skipped": res.get("fact_skipped"),
            "table_missing": res.get("table_missing"),
            "dry_run": bool(args.dry_run),
            "limit": int(args.limit),
        }
    return 0


if __name__ == "__main__":
    sys.exit(main())
