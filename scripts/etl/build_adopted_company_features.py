#!/usr/bin/env python3
"""Populate `am_adopted_company_features` from jpi_adoption_records and
related corpora (jpi_houjin_master / jpi_invoice_registrants /
jpi_enforcement_cases / jpi_loan_programs).

Why this exists:
    Pre-aggregated per-houjin signature backing
    `score_application_probability` precision uplift and the
    `find_adopted_company_signature` rule chain. Customer-LLMs read this
    table by PRIMARY KEY (houjin_bangou) — the join logic + dominant-mode
    selection runs once here, not on every request.

Read sources (all on autonomath.db):
    * jpi_adoption_records — adoption_count, distinct_program_count,
      first/last adoption, dominant JSIC major + prefecture.
    * jpi_houjin_master — normalized_name (used to bridge enforcement
      records that lack houjin_bangou).
    * jpi_invoice_registrants — T-number presence flag.
    * jpi_enforcement_cases — enforcement_count via
      recipient_name = normalized_name (recipient_houjin_bangou is 0%
      populated as of 2026-05-04, so name-bridge is the only path).
    * jpi_loan_programs — per-company linkage table NOT YET INGESTED;
      loan_count is set to 0 across the board until per-recipient loan
      records land. Documented honest gap, not a code defect.

Write target:
    am_adopted_company_features — INSERT OR REPLACE keyed on
    houjin_bangou. Idempotent and safe to re-run.

credibility_score formula:
    base    = adoption_count / 100.0, capped at 1.0
    penalty = 1 - log10(enforcement_count + 1) / log10(10)
            = 1 - log10(enforcement_count + 1)
    score   = max(0.0, base * penalty)
    NULL    iff adoption_count = 0 (defensive; should never arise here
            because we only INSERT rows with adoption_count >= 1).

Distribution report (printed to stdout at end):
    * 採択 1+ 回 unique houjin
    * 採択 5+ 回 (heavy adopter)
    * 採択あり + 行政処分あり (yellow flag)
    * 採択あり + 適格事業者登録あり ratio
    * Top 20 high-credibility houjin (実名表示, 公開情報のみ)

Non-LLM: pure SQL aggregation + Python dict reduction.
"""

from __future__ import annotations

import argparse
import math
import os
import sqlite3
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = REPO_ROOT / "autonomath.db"


def open_db(path: Path) -> sqlite3.Connection:
    if not path.exists():
        sys.stderr.write(f"ERROR: autonomath.db not found at {path}\n")
        sys.exit(2)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA temp_store = MEMORY;")
    conn.execute("PRAGMA cache_size = -200000;")  # 200 MB page cache
    return conn


def ensure_table(conn: sqlite3.Connection) -> None:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='am_adopted_company_features';"
    ).fetchone()
    if row is None:
        sys.stderr.write(
            "ERROR: am_adopted_company_features missing — apply "
            "scripts/migrations/wave24_157_am_adopted_company_features.sql first.\n"
        )
        sys.exit(3)


def compute_credibility(adoption_count: int, enforcement_count: int) -> float:
    """credibility_score = (1 - log10(enforcement_count+1)) * (adoption_count/100, capped 1.0)."""
    if adoption_count <= 0:
        return 0.0
    base = min(1.0, adoption_count / 100.0)
    penalty = 1.0 - math.log10(enforcement_count + 1)
    score = base * penalty
    if score < 0.0:
        return 0.0
    if score > 1.0:
        return 1.0
    return score


def aggregate_adoptions(conn: sqlite3.Connection) -> dict[str, dict]:
    """Single sweep over jpi_adoption_records to compute per-houjin
    adoption_count, distinct_program_count, first/last adoption_at,
    and per-houjin Counters for jsic_major + prefecture."""
    print("[1/5] aggregating jpi_adoption_records ...", flush=True)
    t0 = time.time()
    sql = """
        SELECT houjin_bangou,
               program_id,
               program_id_hint,
               announced_at,
               industry_jsic_medium,
               prefecture
          FROM jpi_adoption_records
         WHERE houjin_bangou IS NOT NULL
           AND houjin_bangou != ''
    """
    feats: dict[str, dict] = {}
    rows_seen = 0
    for row in conn.execute(sql):
        rows_seen += 1
        h = row["houjin_bangou"]
        f = feats.get(h)
        if f is None:
            f = {
                "adoption_count": 0,
                "programs": set(),
                "first": None,
                "last": None,
                "jsic": Counter(),
                "pref": Counter(),
            }
            feats[h] = f
        f["adoption_count"] += 1
        prog_key = row["program_id"] or row["program_id_hint"]
        if prog_key:
            f["programs"].add(prog_key)
        a = row["announced_at"]
        if a:
            if f["first"] is None or a < f["first"]:
                f["first"] = a
            if f["last"] is None or a > f["last"]:
                f["last"] = a
        j = row["industry_jsic_medium"]
        if j:
            f["jsic"][j] += 1
        p = row["prefecture"]
        if p:
            f["pref"][p] += 1
    print(
        f"  rows={rows_seen:,} houjin={len(feats):,} ({time.time() - t0:.1f}s)",
        flush=True,
    )
    return feats


def join_invoice(conn: sqlite3.Connection, feats: dict[str, dict]) -> int:
    """Set invoice_registered=1 for every houjin_bangou that appears in
    jpi_invoice_registrants (any registration row, not just active)."""
    print("[2/5] joining jpi_invoice_registrants ...", flush=True)
    t0 = time.time()
    sql = """
        SELECT DISTINCT houjin_bangou
          FROM jpi_invoice_registrants
         WHERE houjin_bangou IS NOT NULL
           AND houjin_bangou != ''
    """
    hits = 0
    for row in conn.execute(sql):
        h = row["houjin_bangou"]
        f = feats.get(h)
        if f is not None:
            f["invoice"] = 1
            hits += 1
    print(f"  invoice-registered houjin matched={hits:,} ({time.time() - t0:.1f}s)", flush=True)
    return hits


def join_enforcement(conn: sqlite3.Connection, feats: dict[str, dict]) -> int:
    """Bridge enforcement to houjin_bangou via houjin_master.normalized_name
    (recipient_houjin_bangou is unpopulated). Aggregate enforcement_count
    per houjin_bangou."""
    print("[3/5] joining jpi_enforcement_cases via houjin_master.normalized_name ...", flush=True)
    t0 = time.time()
    # Build name → houjin_bangou map only for adopted houjin (saves memory).
    adopted = set(feats.keys())
    print(f"  building name index (adopted houjin = {len(adopted):,}) ...", flush=True)
    name_to_hb: dict[str, str] = {}
    name_sql = """
        SELECT houjin_bangou, normalized_name
          FROM jpi_houjin_master
         WHERE normalized_name IS NOT NULL
           AND normalized_name != ''
    """
    for row in conn.execute(name_sql):
        h = row["houjin_bangou"]
        if h not in adopted:
            continue
        name_to_hb[row["normalized_name"]] = h
    print(f"  adopted-houjin name index size={len(name_to_hb):,}", flush=True)

    enf_counter: dict[str, int] = defaultdict(int)
    enf_sql = """
        SELECT recipient_name
          FROM jpi_enforcement_cases
         WHERE recipient_name IS NOT NULL
           AND recipient_name != ''
    """
    matched = 0
    total_enf = 0
    for row in conn.execute(enf_sql):
        total_enf += 1
        h = name_to_hb.get(row["recipient_name"])
        if h is not None:
            enf_counter[h] += 1
            matched += 1
    for h, c in enf_counter.items():
        feats[h]["enforcement"] = c
    print(
        f"  enforcement rows scanned={total_enf:,} matched={matched:,} "
        f"distinct-houjin-with-enforcement={len(enf_counter):,} "
        f"({time.time() - t0:.1f}s)",
        flush=True,
    )
    return len(enf_counter)


def lookup_dominant(c: Counter) -> str | None:
    if not c:
        return None
    # Counter.most_common is deterministic on ties by insertion order; since
    # Counter has no insertion-order tie-break guarantee across runs, we add
    # an explicit secondary key (alphabetic) to make this reproducible.
    items = sorted(c.items(), key=lambda kv: (-kv[1], kv[0]))
    return items[0][0]


def write_features(conn: sqlite3.Connection, feats: dict[str, dict]) -> int:
    print(f"[4/5] writing am_adopted_company_features ({len(feats):,} rows) ...", flush=True)
    t0 = time.time()
    conn.execute("BEGIN;")
    conn.execute("DELETE FROM am_adopted_company_features;")
    insert_sql = """
        INSERT OR REPLACE INTO am_adopted_company_features (
            houjin_bangou, adoption_count, distinct_program_count,
            first_adoption_at, last_adoption_at,
            dominant_jsic_major, dominant_prefecture,
            enforcement_count, invoice_registered, loan_count,
            credibility_score, computed_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
    """
    written = 0
    BATCH = 5000  # noqa: N806  (local CONST sentinel, not loop-mut)
    batch: list[tuple] = []
    for h, f in feats.items():
        adoption_count = f["adoption_count"]
        enforcement_count = f.get("enforcement", 0)
        invoice_registered = f.get("invoice", 0)
        cred = compute_credibility(adoption_count, enforcement_count)
        batch.append(
            (
                h,
                adoption_count,
                len(f["programs"]),
                f["first"],
                f["last"],
                lookup_dominant(f["jsic"]),
                lookup_dominant(f["pref"]),
                enforcement_count,
                invoice_registered,
                0,  # loan_count: per-company loan corpus not yet ingested
                cred,
            )
        )
        if len(batch) >= BATCH:
            conn.executemany(insert_sql, batch)
            written += len(batch)
            batch.clear()
    if batch:
        conn.executemany(insert_sql, batch)
        written += len(batch)
    conn.execute("COMMIT;")
    print(f"  wrote {written:,} rows ({time.time() - t0:.1f}s)", flush=True)
    return written


def report(conn: sqlite3.Connection) -> None:
    print("[5/5] distribution report", flush=True)
    print("=" * 72)
    n1 = conn.execute(
        "SELECT COUNT(*) FROM am_adopted_company_features WHERE adoption_count >= 1;"
    ).fetchone()[0]
    n5 = conn.execute(
        "SELECT COUNT(*) FROM am_adopted_company_features WHERE adoption_count >= 5;"
    ).fetchone()[0]
    yellow = conn.execute(
        "SELECT COUNT(*) FROM am_adopted_company_features "
        "WHERE adoption_count >= 1 AND enforcement_count >= 1;"
    ).fetchone()[0]
    inv = conn.execute(
        "SELECT COUNT(*) FROM am_adopted_company_features "
        "WHERE adoption_count >= 1 AND invoice_registered = 1;"
    ).fetchone()[0]
    inv_ratio = (inv / n1) if n1 else 0.0

    print(f"  採択 1+ 回 unique houjin           : {n1:>9,}")
    print(f"  採択 5+ 回 heavy adopter           : {n5:>9,}")
    print(f"  採択 + 行政処分あり (yellow flag) : {yellow:>9,}")
    print(f"  採択 + 適格事業者登録あり          : {inv:>9,} (ratio {inv_ratio:.4f})")
    print()

    print("  Top 20 high-credibility houjin (公開情報):")
    print("  " + "-" * 70)
    print(
        f"  {'rank':>4}  {'houjin_bangou':<14}  {'adopt':>5}  "
        f"{'enf':>4}  {'inv':>3}  {'jsic':<5}  {'pref':<10}  cred"
    )
    print("  " + "-" * 70)
    top_sql = """
        SELECT f.houjin_bangou,
               h.normalized_name,
               f.adoption_count,
               f.enforcement_count,
               f.invoice_registered,
               f.dominant_jsic_major,
               f.dominant_prefecture,
               f.credibility_score
          FROM am_adopted_company_features f
          LEFT JOIN jpi_houjin_master h
            ON h.houjin_bangou = f.houjin_bangou
         WHERE f.credibility_score IS NOT NULL
         ORDER BY f.credibility_score DESC,
                  f.adoption_count DESC,
                  f.houjin_bangou ASC
         LIMIT 20;
    """
    for i, row in enumerate(conn.execute(top_sql), start=1):
        name = row["normalized_name"] or "(name unresolved)"
        jsic = row["dominant_jsic_major"] or "-"
        pref = row["dominant_prefecture"] or "-"
        print(
            f"  {i:>4}  {row['houjin_bangou']:<14}  "
            f"{row['adoption_count']:>5}  "
            f"{row['enforcement_count']:>4}  "
            f"{row['invoice_registered']:>3}  "
            f"{jsic:<5}  {pref[:10]:<10}  "
            f"{row['credibility_score']:.4f}  {name}"
        )
    print("=" * 72)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DB,
        help="path to autonomath.db (default: repo-root autonomath.db)",
    )
    args = ap.parse_args()
    db_path = args.db
    if not os.path.isabs(db_path):
        db_path = (REPO_ROOT / db_path).resolve()

    conn = open_db(db_path)
    try:
        ensure_table(conn)
        feats = aggregate_adoptions(conn)
        join_invoice(conn, feats)
        join_enforcement(conn, feats)
        write_features(conn, feats)
        report(conn)
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
