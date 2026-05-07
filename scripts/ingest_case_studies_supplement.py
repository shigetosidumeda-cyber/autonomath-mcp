#!/usr/bin/env python3
"""Ingest Autonomath adoption_supplement into jpintel-mcp jpi_adoption_records.

Source:
    /Users/shigetoumeda/Autonomath/data/adoption_index_desktop_supplement.jsonl
    (9,013 raw lines / ~8,934 unique adoption_id; per Round-1 audit ~1,312 are
    NEW vs the canonical adoption_index.jsonl already loaded into autonomath.db.
    Actual NEW count is verified by SELECT EXISTS dedup against current DB and
    reported in the dry-run summary.)

Target:
    autonomath.db / jpi_adoption_records   (199,944 rows pre-supplement)
    Schema (relevant cols):
        houjin_bangou TEXT NOT NULL  -- empty for sole proprietors
        program_id_hint TEXT         -- e.g. 'saikouchiku'
        program_name_raw TEXT
        company_name_raw TEXT
        round_label TEXT             -- e.g. '第08回'
        round_number INTEGER
        announced_at TEXT
        prefecture, municipality TEXT
        project_title TEXT
        industry_raw TEXT
        source_url TEXT NOT NULL
        fetched_at TEXT NOT NULL
        confidence REAL DEFAULT 0.85

    Note: a FOREIGN KEY (houjin_bangou) -> houjin_master(houjin_bangou) is
    declared on the table but PRAGMA foreign_keys is OFF by default in this
    DB (and the referenced table is jpi_houjin_master here, not houjin_master).
    INSERTs do not fail on missing parent rows.

Source registration:
    am_source row 'autonomath_adoption_supplement' (source_url sentinel
    'autonomath:adoption_supplement', source_type='secondary', license is
    captured implicitly via domain='autonomath' — the am_source schema does
    not carry an explicit license column; downstream attribution is handled
    by record-level source_url which we keep verbatim from the supplement
    payload, falling back to the sentinel when blank).

Duplicate detection:
    KEY = (houjin_bangou, program_id_hint, round_label, project_title[:60])
    Composite is necessary because:
      - houjin_bangou alone collides for multi-round adoptees
      - many supplement rows have empty houjin_bangou (sole proprietors)
      - title is truncated to 60 chars to absorb whitespace/PDF parse drift
    A row is INSERTed only when SELECT EXISTS returns 0 for the composite.

Usage:
    python3 scripts/ingest_case_studies_supplement.py --dry-run
    python3 scripts/ingest_case_studies_supplement.py --limit 500
    python3 scripts/ingest_case_studies_supplement.py
    python3 scripts/ingest_case_studies_supplement.py --target-table some_other

Exit codes:
    0  success
    1  fatal (source file missing, DB locked, schema mismatch)
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import time
from datetime import UTC, datetime

UTC = UTC
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = REPO_ROOT / "autonomath.db"
SOURCE_FILE = Path("/Users/shigetoumeda/Autonomath/data/adoption_index_desktop_supplement.jsonl")
DEFAULT_TABLE = "jpi_adoption_records"
SOURCE_TAG_URL = "autonomath:adoption_supplement"
SOURCE_TAG_DOMAIN = "autonomath"


# --- Round label parsing ----------------------------------------------------

_ROUND_RE = re.compile(r"(\d+)")


def parse_round_number(call_label: str, call_id: str) -> int | None:
    """Best-effort int round number from '第08回' / 'round_08'."""
    for s in (call_label, call_id):
        if not s:
            continue
        m = _ROUND_RE.search(s)
        if m:
            return int(m.group(1))
    return None


# --- DB helpers -------------------------------------------------------------


def open_db(read_only: bool, timeout: float = 30.0) -> sqlite3.Connection:
    if read_only:
        uri = f"file:{DB_PATH}?mode=ro"
        return sqlite3.connect(uri, uri=True, timeout=timeout)
    return sqlite3.connect(DB_PATH, timeout=timeout)


def ensure_am_source(conn: sqlite3.Connection) -> None:
    """Register the supplement as a secondary source. INSERT OR IGNORE."""
    conn.execute(
        """
        INSERT OR IGNORE INTO am_source
            (source_url, source_type, domain, is_pdf,
             first_seen, promoted_at, canonical_status)
        VALUES (?, 'secondary', ?, 0, datetime('now'), datetime('now'), 'active')
        """,
        (SOURCE_TAG_URL, SOURCE_TAG_DOMAIN),
    )


def table_exists(conn: sqlite3.Connection, name: str) -> bool:
    cur = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,))
    return cur.fetchone() is not None


def load_existing_keys(conn: sqlite3.Connection, table: str) -> set[tuple[str, str, str, str]]:
    """Build the dedup-key set from current rows in target table.

    The set is small enough (~200k rows of 4 short strings) to keep in RAM
    and gives us O(1) lookup vs row-by-row SELECT EXISTS.
    """
    cur = conn.execute(
        f"""
        SELECT houjin_bangou, program_id_hint, round_label, project_title
        FROM {table}
        """  # noqa: S608  -- table is from --target-table flag, validated below
    )
    keys: set[tuple[str, str, str, str]] = set()
    for hb, pid, rlabel, ptitle in cur:
        keys.add(
            (
                hb or "",
                pid or "",
                rlabel or "",
                (ptitle or "")[:60],
            )
        )
    return keys


# --- Record shaping ---------------------------------------------------------


def shape_record(d: dict) -> dict | None:
    """Map supplement JSON to jpi_adoption_records column dict.

    Returns None for malformed rows (missing both houjin and company name).
    """
    company = d.get("company", {}) or {}
    project = d.get("project", {}) or {}
    source = d.get("source", {}) or {}

    company_name = (company.get("name") or "").strip()
    if not company_name:
        return None

    src_url_raw = (source.get("url") or "").strip()
    # Supplement uses '(取得済PDF)' marker for files that were fetched offline.
    # We keep the marker verbatim so that record provenance survives intact;
    # the am_source sentinel is the registry-level pointer, not the per-row URL.
    if not src_url_raw or src_url_raw.endswith("(取得済PDF)"):
        # Keep the marker as-is when present — useful for forensic re-fetch later.
        source_url = src_url_raw or SOURCE_TAG_URL
    else:
        source_url = src_url_raw

    return {
        "houjin_bangou": (company.get("houjin_bangou") or "").strip(),
        "program_id_hint": (d.get("program_id") or "").strip() or None,
        "program_name_raw": (d.get("program_name") or "").strip() or None,
        "company_name_raw": company_name,
        "round_label": (d.get("call_label") or "").strip() or None,
        "round_number": parse_round_number(d.get("call_label", ""), d.get("call_id", "")),
        "announced_at": (d.get("announced_at") or "").strip() or None,
        "prefecture": (company.get("prefecture") or "").strip() or None,
        "municipality": (company.get("city") or "").strip() or None,
        "project_title": (project.get("title") or "").strip() or None,
        "industry_raw": (project.get("industry_raw") or project.get("industry") or "").strip()
        or None,
        "industry_jsic_medium": None,  # supplement has no JSIC code
        "amount_granted_yen": None,  # supplement does not publish amounts
        "amount_project_total_yen": None,
        "source_url": source_url,
        "source_pdf_page": None,
        "confidence": 0.80,  # below default 0.85 — supplement has no amount
    }


def dedup_key(rec: dict) -> tuple[str, str, str, str]:
    return (
        rec["houjin_bangou"] or "",
        rec["program_id_hint"] or "",
        rec["round_label"] or "",
        (rec["project_title"] or "")[:60],
    )


# --- Main -------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="report only, do not INSERT")
    ap.add_argument("--limit", type=int, default=None, help="cap supplement rows processed")
    ap.add_argument(
        "--target-table",
        default=DEFAULT_TABLE,
        help=f"override target table (default {DEFAULT_TABLE})",
    )
    ap.add_argument("--db", type=Path, default=DB_PATH, help="override DB path")
    ap.add_argument(
        "--source",
        type=Path,
        default=SOURCE_FILE,
        help="override supplement JSONL path",
    )
    args = ap.parse_args()

    if not args.source.exists():
        print(f"FATAL: source file not found: {args.source}", file=sys.stderr)
        return 1
    if not args.db.exists():
        print(f"FATAL: db not found: {args.db}", file=sys.stderr)
        return 1

    # Validate table name early — it ends up in an f-string SQL.
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", args.target_table):
        print(f"FATAL: invalid target-table name: {args.target_table!r}", file=sys.stderr)
        return 1

    t0 = time.monotonic()

    # --- Load supplement ----------------------------------------------------
    print(f"[1/5] reading {args.source}")
    raw_records: list[dict] = []
    seen_adoption_ids: set[str] = set()
    n_lines = 0
    n_dup_id = 0
    with args.source.open(encoding="utf-8") as fh:
        for line in fh:
            n_lines += 1
            if args.limit and len(raw_records) >= args.limit:
                break
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError as exc:
                print(f"   skip malformed line {n_lines}: {exc}", file=sys.stderr)
                continue
            aid = d.get("adoption_id")
            if aid and aid in seen_adoption_ids:
                n_dup_id += 1
                continue
            if aid:
                seen_adoption_ids.add(aid)
            raw_records.append(d)
    print(
        f"   loaded {len(raw_records)} unique records "
        f"({n_lines} lines, {n_dup_id} duplicate adoption_id)"
    )

    # --- Shape into target schema ------------------------------------------
    print("[2/5] shaping records to target schema")
    shaped: list[dict] = []
    n_drop = 0
    for d in raw_records:
        rec = shape_record(d)
        if rec is None:
            n_drop += 1
            continue
        shaped.append(rec)
    print(f"   shaped {len(shaped)} ({n_drop} dropped: missing company name)")

    # --- Open DB ------------------------------------------------------------
    print(f"[3/5] connecting to {args.db} (mode={'ro' if args.dry_run else 'rw'})")
    conn = open_db(read_only=args.dry_run)
    try:
        if not table_exists(conn, args.target_table):
            print(
                f"FATAL: target table {args.target_table!r} does not exist.\n"
                f"  Fallback proposal (NOT executed): write each shaped record into\n"
                f"    am_entities(record_kind='adoption', source_id=<am_source.id>)\n"
                f"  + am_entity_facts rows keyed by field_kind in:\n"
                f"    'applicant_name', 'houjin_bangou', 'program_id', 'round',\n"
                f"    'project_title', 'prefecture', 'municipality', 'industry'.\n"
                f"  Run with --target-table am_entities only after confirming\n"
                f"  the field_kind enum is registered in am_entity_facts.",
                file=sys.stderr,
            )
            return 1

        # --- Dedup ----------------------------------------------------------
        print(f"[4/5] loading existing keys from {args.target_table}")
        existing_keys = load_existing_keys(conn, args.target_table)
        print(f"   existing rows: {len(existing_keys)}")

        truly_new: list[dict] = []
        already_in_db = 0
        sup_internal_dup = 0
        seen_in_batch: set[tuple[str, str, str, str]] = set()
        for rec in shaped:
            key = dedup_key(rec)
            if key in existing_keys:
                already_in_db += 1
                continue
            if key in seen_in_batch:
                sup_internal_dup += 1
                continue
            seen_in_batch.add(key)
            truly_new.append(rec)
        print(
            f"   dedup result: {len(truly_new)} truly NEW, "
            f"{already_in_db} already in DB, "
            f"{sup_internal_dup} duplicate within supplement"
        )

        # --- Apply ----------------------------------------------------------
        if args.dry_run:
            print("[5/5] DRY-RUN — no INSERTs executed")
            print(f"   would INSERT into {args.target_table}: {len(truly_new)} rows")
            print(f"   would INSERT OR IGNORE am_source row: {SOURCE_TAG_URL!r}")
            if truly_new[:1]:
                print(f"   sample row: {truly_new[0]}")
        else:
            print(f"[5/5] inserting {len(truly_new)} rows into {args.target_table}")
            conn.execute("BEGIN")
            ensure_am_source(conn)
            fetched_at = datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
            cols = (
                "houjin_bangou",
                "program_id_hint",
                "program_name_raw",
                "company_name_raw",
                "round_label",
                "round_number",
                "announced_at",
                "prefecture",
                "municipality",
                "project_title",
                "industry_raw",
                "industry_jsic_medium",
                "amount_granted_yen",
                "amount_project_total_yen",
                "source_url",
                "source_pdf_page",
                "fetched_at",
                "confidence",
            )
            placeholders = ",".join("?" for _ in cols)
            sql = (
                f"INSERT INTO {args.target_table} "  # noqa: S608 -- validated above
                f"({','.join(cols)}) VALUES ({placeholders})"
            )
            inserted = 0
            for rec in truly_new:
                row = (
                    rec["houjin_bangou"],
                    rec["program_id_hint"],
                    rec["program_name_raw"],
                    rec["company_name_raw"],
                    rec["round_label"],
                    rec["round_number"],
                    rec["announced_at"],
                    rec["prefecture"],
                    rec["municipality"],
                    rec["project_title"],
                    rec["industry_raw"],
                    rec["industry_jsic_medium"],
                    rec["amount_granted_yen"],
                    rec["amount_project_total_yen"],
                    rec["source_url"],
                    rec["source_pdf_page"],
                    fetched_at,
                    rec["confidence"],
                )
                try:
                    conn.execute(sql, row)
                    inserted += 1
                except sqlite3.IntegrityError as exc:
                    print(
                        f"   skip integrity error: {exc} for {rec.get('company_name_raw')}",
                        file=sys.stderr,
                    )
            conn.commit()
            print(f"   inserted: {inserted}")
    finally:
        conn.close()

    elapsed = time.monotonic() - t0
    print(f"done in {elapsed:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
