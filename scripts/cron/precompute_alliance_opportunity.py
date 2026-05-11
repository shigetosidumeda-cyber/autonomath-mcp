#!/usr/bin/env python3
"""Weekly precompute of am_alliance_opportunity (Wave 34 Axis 4d).

houjin x alliance_partner top 10 候補 with 0-100 score. NO LLM, pure SQL.
"""

from __future__ import annotations

import argparse
import json
import logging
import math
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

LOG = logging.getLogger("precompute_alliance_opportunity")

DEFAULT_DB = os.environ.get("AUTONOMATH_DB_PATH", str(_REPO / "autonomath.db"))
DEFAULT_TOP_N = 10
DEFAULT_MAX_HOUJIN = 50_000

INDUSTRY_CHAIN_PAIRS = {
    ("E", "I"): 25, ("D", "M"): 25, ("J", "G"): 25, ("E", "G"): 25,
    ("K", "I"): 22, ("F", "E"): 22, ("L", "G"): 22, ("E", "K"): 18,
    ("H", "I"): 18, ("P", "Q"): 18,
}

ADJACENT_PREFECTURES = {
    "tokyo": {"kanagawa", "saitama", "chiba", "yamanashi"},
    "osaka": {"kyoto", "hyogo", "nara", "wakayama"},
    "aichi": {"shizuoka", "nagano", "gifu", "mie"},
    "fukuoka": {"saga", "kumamoto", "oita"},
}


def _connect(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA temp_store = MEMORY")
    return conn


def _ensure_tables(conn):
    sql_path = _REPO / "scripts" / "migrations" / "238_am_alliance_opportunity.sql"
    if sql_path.exists():
        with sql_path.open(encoding="utf-8") as f:
            conn.executescript(f.read())


def _cohort_houjin(conn, max_houjin):
    try:
        rows = list(conn.execute(
            "SELECT houjin_bangou FROM jpi_adoption_records "
            "WHERE houjin_bangou IS NOT NULL AND houjin_bangou <> '' "
            "GROUP BY houjin_bangou ORDER BY COUNT(*) DESC LIMIT ?",
            (max_houjin,),
        ))
        if rows:
            return [r[0] for r in rows]
    except sqlite3.Error as exc:
        LOG.warning("adoption walk failed: %s", exc)
    try:
        return [r[0] for r in conn.execute(
            "SELECT canonical_id FROM am_entities WHERE record_kind = 'corporate_entity' "
            "ORDER BY canonical_id LIMIT ?", (max_houjin,)
        )]
    except sqlite3.Error:
        return []


def _co_adoption_partners(conn, houjin):
    try:
        rows = list(conn.execute(
            "SELECT p2.houjin_bangou AS partner, COUNT(*) AS n "
            "FROM jpi_adoption_records p1 "
            "JOIN jpi_adoption_records p2 ON p1.program_unified_id = p2.program_unified_id "
            "  AND p1.fiscal_year = p2.fiscal_year "
            "  AND p1.houjin_bangou <> p2.houjin_bangou "
            "WHERE p1.houjin_bangou = ? AND p2.houjin_bangou IS NOT NULL "
            "GROUP BY p2.houjin_bangou ORDER BY n DESC LIMIT 200",
            (houjin,),
        ))
        return {r["partner"]: r["n"] for r in rows if r["partner"]}
    except sqlite3.Error:
        return {}


def _houjin_attrs(conn, houjin):
    for table in ("jpi_houjin_master", "houjin_master"):
        try:
            row = conn.execute(
                f"SELECT primary_name, jsic_major, jsic_middle, prefecture, employee_count "
                f"FROM {table} WHERE houjin_bangou = ?",
                (houjin,),
            ).fetchone()
        except sqlite3.Error:
            continue
        if row:
            return dict(row)
    return {"primary_name": None, "jsic_major": None, "jsic_middle": None,
            "prefecture": None, "employee_count": None}


def _industry_chain_score(a_major, b_major):
    if not a_major or not b_major:
        return 0, ""
    key = (a_major, b_major)
    rev = (b_major, a_major)
    if key in INDUSTRY_CHAIN_PAIRS:
        return INDUSTRY_CHAIN_PAIRS[key], f"{a_major}x{b_major}"
    if rev in INDUSTRY_CHAIN_PAIRS:
        return INDUSTRY_CHAIN_PAIRS[rev], f"{a_major}x{b_major}"
    if a_major == b_major:
        return 15, f"{a_major}x{b_major}"
    return 8, f"{a_major}x{b_major}"


def _size_balance_score(emp_a, emp_b):
    if not emp_a or not emp_b or emp_a < 1 or emp_b < 1:
        return 5
    log_ratio = abs(math.log10(emp_a) - math.log10(emp_b))
    score = int(round(20 * max(0.0, 1.0 - log_ratio / 2.0)))
    return max(0, min(20, score))


def _region_proximity_score(pref_a, pref_b):
    if not pref_a or not pref_b:
        return 0
    if pref_a == pref_b:
        return 10
    if pref_b in ADJACENT_PREFECTURES.get(pref_a, set()):
        return 6
    if pref_a in ADJACENT_PREFECTURES.get(pref_b, set()):
        return 6
    return 0


def _compat_with_programs_score(conn, a, b):
    try:
        row = conn.execute(
            "SELECT COUNT(DISTINCT p1.program_unified_id) AS n "
            "FROM jpi_adoption_records p1 "
            "JOIN jpi_adoption_records p2 ON p1.program_unified_id = p2.program_unified_id "
            "WHERE p1.houjin_bangou = ? AND p2.houjin_bangou = ?",
            (a, b),
        ).fetchone()
    except sqlite3.Error:
        return 0
    n = row["n"] if row else 0
    if n >= 3:
        return 5
    if n >= 1:
        return 2
    return 0


def _co_adoption_score(count):
    if count <= 0:
        return 0
    return min(40, int(round(10 * math.log2(1 + count))))


def refresh(db_path, *, dry_run=False, max_houjin=DEFAULT_MAX_HOUJIN, top_n=DEFAULT_TOP_N):
    refresh_id = f"al_{uuid.uuid4().hex[:12]}"
    started_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%fZ")
    LOG.info("precompute_alliance_opportunity start id=%s db=%s", refresh_id, db_path)
    conn = _connect(db_path)
    _ensure_tables(conn)

    if not dry_run:
        conn.execute(
            "INSERT OR REPLACE INTO am_alliance_opportunity_refresh_log "
            "(refresh_id, started_at, houjin_count) VALUES (?, ?, 0)",
            (refresh_id, started_at),
        )
        conn.commit()

    cohort = _cohort_houjin(conn, max_houjin)
    LOG.info("cohort houjin=%d", len(cohort))

    pairs_written = 0
    skipped = 0
    t0 = time.time()
    refreshed_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%fZ")

    for hi, houjin in enumerate(cohort):
        partners = _co_adoption_partners(conn, houjin)
        if not partners:
            skipped += 1
            continue
        attrs_a = _houjin_attrs(conn, houjin)
        scored = []
        for partner, co_count in partners.items():
            attrs_b = _houjin_attrs(conn, partner)
            co_score = _co_adoption_score(co_count)
            ind_score, ind_pair = _industry_chain_score(attrs_a.get("jsic_major"), attrs_b.get("jsic_major"))
            size_score = _size_balance_score(attrs_a.get("employee_count"), attrs_b.get("employee_count"))
            region_score = _region_proximity_score(attrs_a.get("prefecture"), attrs_b.get("prefecture"))
            compat_score = _compat_with_programs_score(conn, houjin, partner)
            composite = co_score + ind_score + size_score + region_score + compat_score
            composite = max(0, min(100, composite))
            scored.append((composite, partner, {
                "co_score": co_score, "ind_score": ind_score, "size_score": size_score,
                "region_score": region_score, "compat_score": compat_score, "co_count": co_count,
            }, {"name_b": attrs_b.get("primary_name"), "ind_pair": ind_pair,
                "region_a": attrs_a.get("prefecture"), "region_b": attrs_b.get("prefecture")}))
        scored.sort(key=lambda t: (-t[0], t[1]))
        top = scored[:top_n]
        if not top:
            skipped += 1
            continue
        if dry_run:
            pairs_written += len(top)
            if hi < 3:
                LOG.info("dry-run houjin=%s top=%s", houjin, [(t[0], t[1]) for t in top])
            continue
        conn.execute("DELETE FROM am_alliance_opportunity WHERE houjin_bangou = ?", (houjin,))
        for rank, (score, partner, parts, meta) in enumerate(top, start=1):
            reason_json = json.dumps({"signals": parts}, ensure_ascii=False)
            conn.execute(
                "INSERT INTO am_alliance_opportunity "
                "(houjin_bangou, rank, partner_houjin_bangou, partner_primary_name, "
                " alliance_score_0_100, co_adoption_subscore, industry_chain_subscore, "
                " size_balance_subscore, region_proximity_subscore, compat_with_programs_subscore, "
                " co_adoption_count, industry_chain_pair, region_a, region_b, reason_json, refreshed_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    houjin, rank, partner, meta["name_b"], score,
                    parts["co_score"], parts["ind_score"], parts["size_score"],
                    parts["region_score"], parts["compat_score"], parts["co_count"],
                    meta["ind_pair"], meta["region_a"], meta["region_b"], reason_json, refreshed_at,
                ),
            )
            pairs_written += 1
        if (hi + 1) % 1000 == 0:
            conn.commit()

    if not dry_run:
        conn.commit()
        conn.execute(
            "UPDATE am_alliance_opportunity_refresh_log SET finished_at = ?, "
            "  houjin_count = ?, partner_pairs_written = ?, skipped_no_co_adoption = ? "
            "WHERE refresh_id = ?",
            (datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%fZ"), len(cohort), pairs_written, skipped, refresh_id),
        )
        conn.commit()
    conn.close()
    LOG.info("precompute_alliance_opportunity done houjin=%d pairs=%d", len(cohort), pairs_written)
    return {"houjin": len(cohort), "pairs": pairs_written, "skipped": skipped}


def _parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--autonomath-db", default=DEFAULT_DB)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--max-houjin", type=int, default=DEFAULT_MAX_HOUJIN)
    p.add_argument("--top-n", type=int, default=DEFAULT_TOP_N)
    p.add_argument("--log-level", default="INFO")
    return p.parse_args(argv)


def main(argv=None):
    args = _parse_args(argv)
    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.INFO),
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    result = refresh(args.autonomath_db, dry_run=args.dry_run,
                     max_houjin=args.max_houjin, top_n=args.top_n)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
