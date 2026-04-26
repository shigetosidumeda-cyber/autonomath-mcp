#!/usr/bin/env python3
"""Ingest METI gBizINFO enrichment data into ``am_entities`` + ``am_entity_facts``.

Source: METI gBizINFO bulk public dataset, exported to JSONL by the Autonomath
runtime fetcher at ``/Users/shigetoumeda/Autonomath/data/runtime/gbiz_enrichment.jsonl``.

License: gBizINFO は経済産業省 利用規約 (CC BY 4.0 互換) で再配布可。
出典: 経済産業省 gBizINFO (https://info.gbiz.go.jp/)

Coverage: 121,881 records, of which ~79,876 are houjin_bangou not yet present
in am_entities (record_kind='corporate_entity'). The remaining ~42,005 are
existing entities that get supplemental facts only (no new entity row).

Schema mapping
--------------
am_entities row (per gBiz record without an existing entity)
    canonical_id   : ``houjin:<corporate_number>``      -- matches existing pattern
    record_kind    : ``corporate_entity``
    primary_name   : ``name``
    source_url     : NTA houjin-bangou permalink for the bangou
    raw_json       : JSON of the gBiz record
    confidence     : 0.95 (METI primary, fully structured)

am_entity_facts rows (per attribute)
    field_name              field_kind  field_value_*           unit
    -----------             ----------  ------------------      -------
    houjin_bangou           text        text=corporate_number
    corp.legal_name         text        text=name
    corp.legal_name_kana    text        text=kana
    corp.legal_name_en      text        text=name_en
    corp.location           text        text=location           -- full address
    corp.postal_code        text        text=postal_code (zero-padded 7)
    corp.representative     text        text=representative_name
    corp.representative_position text   text=representative_position
    corp.business_summary   text        text=business_summary
    corp.business_items     list        json=business_items     -- METI 業種コード array
    corp.qualification_grade text       text=qualification_grade
    corp.capital_amount     amount      numeric=capital_stock   yen
    corp.employee_count     number      numeric=employee_number persons
    corp.employee_count_male number     numeric=company_size_male persons
    corp.employee_count_female number   numeric=company_size_female persons
    corp.founded_year       number      numeric=founding_year
    corp.date_of_establishment date     text=YYYY-MM-DD
    corp.close_date         date        text=YYYY-MM-DD
    corp.close_cause        text        text=close_cause
    corp.status             enum        text=status
    corp.company_url        url         text=company_url
    corp.gbiz_update_date   date        text=update_date         -- gbiz upstream
    corp.gbiz_fetched_at    date        text=fetched_at ISO

The ``field_name`` namespace ``corp.*`` already exists in the DB
(``corp.legal_name``, ``corp.prefecture``, ``corp.municipality``,
``corp.industry_raw``, ``corp.jsic_major``, ``corp.region_code``,
``houjin_bangou``). New names introduced by this script are listed
in ``NEW_FIELD_NAMES``; the ``field_kind`` column stays inside the
SQL CHECK enum (text/enum/list/url/number/bool/amount/date) — only
the more granular ``field_name`` strings are extended.

CLI:
    python scripts/ingest_gbiz_facts.py
        [--db PATH]                  default: /Users/shigetoumeda/jpintel-mcp/autonomath.db
        [--source PATH]              default: /Users/shigetoumeda/Autonomath/data/runtime/gbiz_enrichment.jsonl
        [--limit N]
        [--dry-run]
        [--batch-size 5000]
        [--skip-existing]            re-use existing entity_ids only, do not insert
                                     new am_entities rows; still upserts new facts
        [--verbose]

Idempotent. The UNIQUE index ``uq_am_facts_entity_field_text``
(entity_id, field_name, COALESCE(field_value_text, '')) is the natural
de-dup key, so re-runs are safe (INSERT OR IGNORE).
"""
from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_LOG = logging.getLogger("jpintel.ingest.gbiz_facts")

DEFAULT_DB = Path("/Users/shigetoumeda/jpintel-mcp/autonomath.db")
DEFAULT_SOURCE = Path("/Users/shigetoumeda/Autonomath/data/runtime/gbiz_enrichment.jsonl")

SOURCE_KEY = "https://info.gbiz.go.jp/"
SOURCE_TYPE = "primary"
SOURCE_DOMAIN = "info.gbiz.go.jp"
LICENSE = "cc_by_4.0"

NTA_PERMALINK_FMT = (
    "https://www.houjin-bangou.nta.go.jp/henkorireki-johoto.html?selHoujinNo={}"
)

CONFIDENCE = 0.95

# Existing field_name vocabulary observed in am_entity_facts for
# record_kind='corporate_entity'. New ones introduced by this script
# are appended below for tracking / log output.
EXISTING_CORP_FIELDS: set[str] = {
    "houjin_bangou",
    "corp.legal_name",
    "corp.prefecture",
    "corp.municipality",
    "corp.industry_raw",
    "corp.jsic_major",
    "corp.region_code",
}

NEW_FIELD_NAMES: list[str] = [
    "corp.legal_name_kana",
    "corp.legal_name_en",
    "corp.location",
    "corp.postal_code",
    "corp.representative",
    "corp.representative_position",
    "corp.business_summary",
    "corp.business_items",
    "corp.qualification_grade",
    "corp.capital_amount",
    "corp.employee_count",
    "corp.employee_count_male",
    "corp.employee_count_female",
    "corp.founded_year",
    "corp.date_of_establishment",
    "corp.close_date",
    "corp.close_cause",
    "corp.status",
    "corp.company_url",
    "corp.gbiz_update_date",
    "corp.gbiz_fetched_at",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(tz=UTC).strftime("%Y-%m-%d %H:%M:%S")


def _today_iso_date() -> str:
    return datetime.now(tz=UTC).strftime("%Y-%m-%d")


def _trim(value: Any) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    if not s or s == "-":
        return None
    return s


def _to_int(value: Any) -> int | None:
    if value is None or value == "" or value == "-":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _to_iso_date(value: Any) -> str | None:
    """Accept ISO-8601 timestamp, ``YYYY-MM-DD``, or epoch float; return YYYY-MM-DD."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value), tz=UTC).strftime("%Y-%m-%d")
        except (OverflowError, OSError, ValueError):
            return None
    s = str(value).strip()
    if not s or s == "-":
        return None
    # Already YYYY-MM-DD
    if len(s) >= 10 and s[4] == "-" and s[7] == "-":
        return s[:10]
    return None


def _normalise_postal(value: Any) -> str | None:
    s = _trim(value)
    if not s:
        return None
    digits = "".join(ch for ch in s if ch.isdigit())
    if not digits:
        return None
    return digits.zfill(7)[:7]


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _open_db(path: Path) -> sqlite3.Connection:
    if not path.exists():
        raise SystemExit(f"db not found: {path}")
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA cache_size = -200000")  # ~200 MB
    conn.execute("PRAGMA temp_store = MEMORY")
    return conn


def _ensure_source(conn: sqlite3.Connection, *, dry_run: bool) -> int:
    """Insert (or fetch) the gBizINFO source row, return its id.

    Note: ``am_source`` schema in this DB does not have a ``license`` column;
    the licence string is recorded in the script header / docs as policy.
    """
    cur = conn.execute("SELECT id FROM am_source WHERE source_url = ?", (SOURCE_KEY,))
    row = cur.fetchone()
    if row is not None:
        return int(row[0])
    if dry_run:
        _LOG.info("[dry-run] would INSERT am_source row for %s", SOURCE_KEY)
        return -1
    cur = conn.execute(
        """
        INSERT INTO am_source (source_url, source_type, domain, last_verified)
        VALUES (?, ?, ?, ?)
        """,
        (SOURCE_KEY, SOURCE_TYPE, SOURCE_DOMAIN, _now_iso()),
    )
    return int(cur.lastrowid)


def _fetch_existing_houjin_ids(conn: sqlite3.Connection) -> set[str]:
    """Return the set of corporate_numbers already in am_entities."""
    cur = conn.execute(
        """
        SELECT canonical_id
        FROM am_entities
        WHERE record_kind = 'corporate_entity'
          AND canonical_id LIKE 'houjin:%'
        """
    )
    out: set[str] = set()
    for (cid,) in cur:
        out.add(cid.split(":", 1)[1])
    return out


# ---------------------------------------------------------------------------
# Record -> facts
# ---------------------------------------------------------------------------

def _record_to_facts(rec: dict[str, Any]) -> list[dict[str, Any]]:
    """Map one gBiz JSONL record to a list of fact rows.

    Each returned dict has keys:
        field_name, field_kind, field_value_text, field_value_numeric,
        field_value_json, unit
    """
    facts: list[dict[str, Any]] = []

    def add(
        field_name: str,
        field_kind: str,
        *,
        text: str | None = None,
        numeric: float | int | None = None,
        json_value: Any = None,
        unit: str | None = None,
    ) -> None:
        if text is None and numeric is None and json_value is None:
            return
        if text is not None and not text:
            return
        facts.append(
            {
                "field_name": field_name,
                "field_kind": field_kind,
                "field_value_text": text,
                "field_value_numeric": float(numeric) if numeric is not None else None,
                "field_value_json": json.dumps(json_value, ensure_ascii=False)
                if json_value is not None
                else None,
                "unit": unit,
            }
        )

    cn = _trim(rec.get("corporate_number"))
    if cn:
        add("houjin_bangou", "text", text=cn)

    add("corp.legal_name", "text", text=_trim(rec.get("name")))
    add("corp.legal_name_kana", "text", text=_trim(rec.get("kana")))
    add("corp.legal_name_en", "text", text=_trim(rec.get("name_en")))
    add("corp.location", "text", text=_trim(rec.get("location")))
    add("corp.postal_code", "text", text=_normalise_postal(rec.get("postal_code")))
    add("corp.representative", "text", text=_trim(rec.get("representative_name")))
    add(
        "corp.representative_position",
        "text",
        text=_trim(rec.get("representative_position")),
    )
    add("corp.business_summary", "text", text=_trim(rec.get("business_summary")))

    business_items = rec.get("business_items")
    if isinstance(business_items, list) and business_items:
        clean = [str(x) for x in business_items if x is not None]
        if clean:
            add(
                "corp.business_items",
                "list",
                text=",".join(clean),
                json_value=clean,
            )

    add(
        "corp.qualification_grade",
        "text",
        text=_trim(rec.get("qualification_grade")),
    )

    cap = _to_int(rec.get("capital_stock"))
    if cap is not None and cap > 0:
        add("corp.capital_amount", "amount", numeric=cap, unit="yen", text=str(cap))

    emp = _to_int(rec.get("employee_number"))
    if emp is not None and emp >= 0:
        add(
            "corp.employee_count",
            "number",
            numeric=emp,
            unit="persons",
            text=str(emp),
        )
    emp_m = _to_int(rec.get("company_size_male"))
    if emp_m is not None and emp_m >= 0:
        add(
            "corp.employee_count_male",
            "number",
            numeric=emp_m,
            unit="persons",
            text=str(emp_m),
        )
    emp_f = _to_int(rec.get("company_size_female"))
    if emp_f is not None and emp_f >= 0:
        add(
            "corp.employee_count_female",
            "number",
            numeric=emp_f,
            unit="persons",
            text=str(emp_f),
        )

    founded_year = _to_int(rec.get("founding_year"))
    if founded_year and 1800 <= founded_year <= 2100:
        add(
            "corp.founded_year",
            "number",
            numeric=founded_year,
            text=str(founded_year),
        )

    doe = _to_iso_date(rec.get("date_of_establishment"))
    if doe:
        add("corp.date_of_establishment", "date", text=doe)
    cd = _to_iso_date(rec.get("close_date"))
    if cd:
        add("corp.close_date", "date", text=cd)
    add("corp.close_cause", "text", text=_trim(rec.get("close_cause")))

    status = _trim(rec.get("status"))
    if status:
        add("corp.status", "enum", text=status)

    url = _trim(rec.get("company_url"))
    if url:
        add("corp.company_url", "url", text=url)

    upd = _to_iso_date(rec.get("update_date"))
    if upd:
        add("corp.gbiz_update_date", "date", text=upd)
    fetched = _to_iso_date(rec.get("_fetched_at"))
    if fetched:
        add("corp.gbiz_fetched_at", "date", text=fetched)

    return facts


# ---------------------------------------------------------------------------
# Main ingest
# ---------------------------------------------------------------------------

def _entity_row(rec: dict[str, Any], cn: str) -> tuple[Any, ...]:
    """Build the parameter tuple for ``INSERT OR IGNORE INTO am_entities``."""
    canonical_id = f"houjin:{cn}"
    primary_name = _trim(rec.get("name")) or canonical_id
    source_url = NTA_PERMALINK_FMT.format(cn)
    raw_json = json.dumps(rec, ensure_ascii=False)
    fetched_at = _to_iso_date(rec.get("_fetched_at")) or _today_iso_date()
    now = _now_iso()
    return (
        canonical_id,
        "corporate_entity",
        "gbizinfo",
        None,  # source_record_index
        primary_name,
        None,  # authority_canonical
        CONFIDENCE,
        source_url,
        SOURCE_DOMAIN,
        fetched_at,
        raw_json,
        now,
        now,
    )


def _flush_entities(
    conn: sqlite3.Connection,
    rows: list[tuple[Any, ...]],
    *,
    dry_run: bool,
) -> int:
    if not rows:
        return 0
    if dry_run:
        return len(rows)
    cur = conn.executemany(
        """
        INSERT OR IGNORE INTO am_entities (
            canonical_id, record_kind, source_topic, source_record_index,
            primary_name, authority_canonical, confidence,
            source_url, source_url_domain, fetched_at, raw_json,
            created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    # rowcount on executemany with INSERT OR IGNORE returns the total
    # *attempted* inserts in SQLite when you use sqlite3.connect, so we
    # cannot rely on it for a precise inserted-count. Caller already
    # filters duplicates via existing_ids so attempted == inserted.
    return cur.rowcount if cur.rowcount and cur.rowcount > 0 else len(rows)


def _flush_facts(
    conn: sqlite3.Connection,
    rows: list[tuple[Any, ...]],
    *,
    dry_run: bool,
) -> int:
    if not rows:
        return 0
    if dry_run:
        return len(rows)
    cur = conn.executemany(
        """
        INSERT OR IGNORE INTO am_entity_facts (
            entity_id, field_name, field_value_text,
            field_value_json, field_value_numeric,
            field_kind, unit, source_url
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    return cur.rowcount if cur.rowcount and cur.rowcount > 0 else len(rows)


def ingest(
    *,
    db_path: Path,
    source_path: Path,
    limit: int | None,
    batch_size: int,
    dry_run: bool,
    skip_existing: bool,
) -> dict[str, int]:
    if not source_path.exists():
        raise SystemExit(f"source not found: {source_path}")

    conn = _open_db(db_path)
    source_id = _ensure_source(conn, dry_run=dry_run)
    _LOG.info("am_source.id for gbizinfo = %s", source_id)

    existing_ids = _fetch_existing_houjin_ids(conn)
    _LOG.info("existing corporate_entity houjin ids in DB = %d", len(existing_ids))

    new_entities = 0
    new_facts = 0
    skipped_no_houjin = 0
    skipped_existing_in_skip_mode = 0
    field_kinds_seen: set[str] = set()
    field_names_seen: set[str] = set()
    started = time.monotonic()

    entity_buffer: list[tuple[Any, ...]] = []
    fact_buffer: list[tuple[Any, ...]] = []

    def _flush(*, force: bool = False) -> None:
        nonlocal new_entities, new_facts, entity_buffer, fact_buffer
        if force or len(entity_buffer) >= batch_size:
            n = _flush_entities(conn, entity_buffer, dry_run=dry_run)
            new_entities += n
            entity_buffer = []
        if force or len(fact_buffer) >= batch_size * 6:
            n = _flush_facts(conn, fact_buffer, dry_run=dry_run)
            new_facts += n
            fact_buffer = []
        if force and not dry_run:
            conn.commit()

    processed = 0
    with source_path.open("r", encoding="utf-8") as fh:
        for raw_line in fh:
            line = raw_line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError as exc:
                _LOG.warning("skipping malformed JSONL line %d: %s", processed + 1, exc)
                continue

            cn = _trim(rec.get("corporate_number"))
            if not cn:
                skipped_no_houjin += 1
                processed += 1
                continue

            entity_id = f"houjin:{cn}"
            is_existing = cn in existing_ids

            if not is_existing:
                if skip_existing:
                    # In --skip-existing mode we ONLY touch facts on existing
                    # entities (do not add new entity rows or their facts).
                    skipped_existing_in_skip_mode += 1
                    processed += 1
                    continue
                entity_buffer.append(_entity_row(rec, cn))
                # Pretend it now exists so that within-batch dups don't double up
                existing_ids.add(cn)

            facts = _record_to_facts(rec)
            for f in facts:
                field_kinds_seen.add(f["field_kind"])
                field_names_seen.add(f["field_name"])
                fact_buffer.append(
                    (
                        entity_id,
                        f["field_name"],
                        f["field_value_text"],
                        f["field_value_json"],
                        f["field_value_numeric"],
                        f["field_kind"],
                        f["unit"],
                        SOURCE_KEY,
                    )
                )

            processed += 1
            if processed % 5000 == 0:
                _flush(force=True)
                rate = processed / max(time.monotonic() - started, 1e-9)
                _LOG.info(
                    "progress: %d records processed, %d entities, %d facts (%.0f rec/s)",
                    processed,
                    new_entities,
                    new_facts,
                    rate,
                )
            if limit and processed >= limit:
                break

    _flush(force=True)

    elapsed = time.monotonic() - started
    _LOG.info(
        "done. processed=%d new_entities=%d new_facts=%d skipped_no_houjin=%d "
        "skipped_existing_in_skip_mode=%d elapsed=%.1fs",
        processed,
        new_entities,
        new_facts,
        skipped_no_houjin,
        skipped_existing_in_skip_mode,
        elapsed,
    )
    _LOG.info("field_kinds used: %s", sorted(field_kinds_seen))
    new_field_names = sorted(field_names_seen - EXISTING_CORP_FIELDS)
    if new_field_names:
        _LOG.info(
            "field_names INTRODUCED by this script (count=%d): %s",
            len(new_field_names),
            new_field_names,
        )

    conn.close()
    return {
        "processed": processed,
        "new_entities": new_entities,
        "new_facts": new_facts,
        "skipped_no_houjin": skipped_no_houjin,
        "skipped_existing_in_skip_mode": skipped_existing_in_skip_mode,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Ingest METI gBizINFO -> am_entities/facts")
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    p.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--batch-size", type=int, default=5000)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument(
        "--skip-existing",
        action="store_true",
        help="do not insert new am_entities; only upsert facts on existing ids",
    )
    p.add_argument("--verbose", "-v", action="store_true")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s | %(message)s",
    )
    summary = ingest(
        db_path=args.db,
        source_path=args.source,
        limit=args.limit,
        batch_size=args.batch_size,
        dry_run=args.dry_run,
        skip_existing=args.skip_existing,
    )
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
