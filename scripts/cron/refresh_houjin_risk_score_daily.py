#!/usr/bin/env python3
"""Daily refresh of am_houjin_risk_score (Wave 34 Axis 4b).

0-100 composite risk: 40 enforcement + 30 invoice + 15 adoption + 15 credit_age.
NO LLM. Pure SQL + Python rule engine.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO / "src"))

LOG = logging.getLogger("refresh_houjin_risk_score_daily")

DEFAULT_DB = os.environ.get("AUTONOMATH_DB_PATH", str(_REPO / "autonomath.db"))
DEFAULT_MAX_HOUJIN = 200_000

ENF_WEIGHTS = {"grant_refund": 12, "subsidy_exclude": 10, "fine": 8}
ENF_DEFAULT_WEIGHT = 4
ENF_CAP = 40
ADOPTION_WEIGHTS = {"revoked": 8, "returned": 8, "partial_return": 4}
ADOPTION_CAP = 15


def _connect(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA temp_store = MEMORY")
    conn.execute("PRAGMA mmap_size = 268435456")
    return conn


def _ensure_tables(conn):
    sql_path = _REPO / "scripts" / "migrations" / "236_am_houjin_risk_score.sql"
    if sql_path.exists():
        with sql_path.open(encoding="utf-8") as f:
            conn.executescript(f.read())


def _bucket(score):
    if score >= 80:
        return "critical"
    if score >= 60:
        return "high"
    if score >= 30:
        return "medium"
    return "low"


def _cohort_houjin(conn, max_houjin):
    seen = set()
    candidates = []
    queries = (
        (
            "am_enforcement_detail",
            "SELECT DISTINCT houjin_bangou FROM am_enforcement_detail WHERE houjin_bangou IS NOT NULL",
        ),
        (
            "jpi_invoice_registrants",
            "SELECT DISTINCT houjin_bangou FROM jpi_invoice_registrants WHERE houjin_bangou IS NOT NULL",
        ),
        (
            "jpi_adoption_records",
            "SELECT DISTINCT houjin_bangou FROM jpi_adoption_records WHERE houjin_bangou IS NOT NULL",
        ),
    )
    for label, sql in queries:
        try:
            for row in conn.execute(sql):
                hb = row[0]
                if hb and hb not in seen:
                    seen.add(hb)
                    candidates.append(hb)
        except sqlite3.Error as exc:
            LOG.warning("%s walk failed (%s)", label, exc)
        if len(candidates) >= max_houjin:
            break
    if candidates:
        return candidates[:max_houjin]
    try:
        return [
            row[0]
            for row in conn.execute(
                "SELECT canonical_id FROM am_entities WHERE record_kind = 'corporate_entity' "
                "ORDER BY canonical_id LIMIT ?",
                (max_houjin,),
            )
        ]
    except sqlite3.Error:
        return []


def _enforcement_subscore(conn, houjin):
    try:
        rows = list(
            conn.execute(
                "SELECT record_kind, occurred_at FROM am_enforcement_detail WHERE houjin_bangou = ?",
                (houjin,),
            )
        )
    except sqlite3.Error:
        return 0, 0
    if not rows:
        return 0, 0
    now = datetime.now(UTC)
    score = 0
    count_5y = 0
    for r in rows:
        weight = ENF_WEIGHTS.get(r["record_kind"], ENF_DEFAULT_WEIGHT)
        occurred = r["occurred_at"]
        recency_factor = 1.0
        if occurred:
            try:
                dt = datetime.fromisoformat(occurred.replace("Z", "+00:00"))
                age_years = (now - dt).days / 365.25
                if age_years > 5:
                    recency_factor = 0.5
                else:
                    count_5y += 1
            except (ValueError, TypeError):
                count_5y += 1
        else:
            count_5y += 1
        score += int(weight * recency_factor)
    return min(score, ENF_CAP), count_5y


def _invoice_subscore(conn, houjin):
    try:
        row = conn.execute(
            "SELECT status FROM jpi_invoice_registrants WHERE houjin_bangou = ? "
            "ORDER BY status_at DESC LIMIT 1",
            (houjin,),
        ).fetchone()
    except sqlite3.Error:
        return 0, None
    if row is None or not row["status"]:
        return 0, None
    status = row["status"]
    if status == "deregistered":
        return 30, status
    if status == "updated":
        return 10, status
    return 0, status


def _adoption_subscore(conn, houjin):
    try:
        rows = list(
            conn.execute(
                "SELECT adoption_status FROM jpi_adoption_records "
                "WHERE houjin_bangou = ? AND adoption_status IS NOT NULL",
                (houjin,),
            )
        )
    except sqlite3.Error:
        return 0, 0
    score = 0
    revoked = 0
    for r in rows:
        status = r["adoption_status"]
        if status in ("revoked", "returned"):
            revoked += 1
        score += ADOPTION_WEIGHTS.get(status, 0)
    return min(score, ADOPTION_CAP), revoked


def _credit_age_subscore(conn, houjin):
    for table in ("jpi_houjin_master", "houjin_master"):
        try:
            row = conn.execute(
                f"SELECT established_year FROM {table} WHERE houjin_bangou = ?",
                (houjin,),
            ).fetchone()
        except sqlite3.Error:
            continue
        if row is None or row["established_year"] is None:
            continue
        try:
            year = int(row["established_year"])
        except (ValueError, TypeError):
            return 0, None
        age = datetime.now(UTC).year - year
        if age < 1:
            return 15, year
        if age < 3:
            return 8, year
        if age < 5:
            return 4, year
        return 0, year
    return 0, None


def refresh(db_path, *, dry_run=False, max_houjin=DEFAULT_MAX_HOUJIN):
    refresh_id = f"rs_{uuid.uuid4().hex[:12]}"
    started_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%fZ")
    LOG.info("refresh_houjin_risk_score_daily start id=%s db=%s", refresh_id, db_path)
    conn = _connect(db_path)
    _ensure_tables(conn)

    if not dry_run:
        conn.execute(
            "INSERT OR REPLACE INTO am_houjin_risk_score_refresh_log "
            "(refresh_id, started_at, houjin_count) VALUES (?, ?, 0)",
            (refresh_id, started_at),
        )
        conn.commit()

    cohort = _cohort_houjin(conn, max_houjin)
    LOG.info("cohort houjin=%d", len(cohort))

    t0 = time.time()
    high_count = 0
    critical_count = 0
    refreshed_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%fZ")

    for hi, houjin in enumerate(cohort):
        enf_score, enf_count = _enforcement_subscore(conn, houjin)
        inv_score, inv_status = _invoice_subscore(conn, houjin)
        adp_score, adp_revoked = _adoption_subscore(conn, houjin)
        age_score, est_year = _credit_age_subscore(conn, houjin)
        composite = enf_score + inv_score + adp_score + age_score
        composite = min(100, max(0, composite))
        bucket = _bucket(composite)
        if bucket == "high":
            high_count += 1
        if bucket == "critical":
            critical_count += 1
        signals = {
            "enforcement_5y_count": enf_count,
            "invoice_status": inv_status,
            "adoption_revoked": adp_revoked,
            "credit_age_year": est_year,
        }
        if dry_run:
            if hi < 5:
                LOG.info(
                    "dry-run houjin=%s score=%d bucket=%s signals=%s",
                    houjin,
                    composite,
                    bucket,
                    signals,
                )
            continue
        conn.execute(
            "INSERT OR REPLACE INTO am_houjin_risk_score "
            "(houjin_bangou, risk_score_0_100, enforcement_subscore, invoice_subscore, "
            " adoption_subscore, credit_age_subscore, risk_bucket, signals_json, "
            " enforcement_count_5y, invoice_status, adoption_revoked_count, "
            " established_year, refreshed_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                houjin,
                composite,
                enf_score,
                inv_score,
                adp_score,
                age_score,
                bucket,
                json.dumps(signals, ensure_ascii=False),
                enf_count,
                inv_status,
                adp_revoked,
                est_year,
                refreshed_at,
            ),
        )
        if (hi + 1) % 5000 == 0:
            conn.commit()
            LOG.info("progress %d/%d elapsed=%.1fs", hi + 1, len(cohort), time.time() - t0)

    if not dry_run:
        conn.commit()
        conn.execute(
            "UPDATE am_houjin_risk_score_refresh_log SET finished_at = ?, "
            "  houjin_count = ?, high_risk_count = ?, critical_risk_count = ? "
            "WHERE refresh_id = ?",
            (
                datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%fZ"),
                len(cohort),
                high_count,
                critical_count,
                refresh_id,
            ),
        )
        conn.commit()
    conn.close()
    LOG.info(
        "refresh_houjin_risk_score_daily done houjin=%d high=%d crit=%d",
        len(cohort),
        high_count,
        critical_count,
    )
    return {"houjin": len(cohort), "high": high_count, "critical": critical_count}


def _parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--autonomath-db", default=DEFAULT_DB)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--max-houjin", type=int, default=DEFAULT_MAX_HOUJIN)
    p.add_argument("--log-level", default="INFO")
    return p.parse_args(argv)


def main(argv=None):
    args = _parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    result = refresh(args.autonomath_db, dry_run=args.dry_run, max_houjin=args.max_houjin)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
