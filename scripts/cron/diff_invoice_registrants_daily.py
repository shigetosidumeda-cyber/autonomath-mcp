#!/usr/bin/env python3
"""Axis 3e — invoice 適格事業者公表 daily diff cron (replaces monthly 4M bulk).

The existing ``ingest_nta_invoice_bulk.py`` workflow lands a full ~4M-row
zenken snapshot on the 1st of each month (≈920 MB DB growth). This cron
runs *daily* against the 国税庁 適格請求書発行事業者公表 API ``/since-cursor``
endpoint, pulling only the rows that changed since the previous run, so:

  * NEW 登録   → INSERT OR IGNORE into invoice_registrants
  * UPDATED   → UPDATE existing row + record delta hash
  * DELETED   → set ``invoice_registrants.is_active = 0`` (soft delete flag —
                NTA 適格請求書 公表 API does not physically delete rows; we
                mirror their 失効済 marker)

The since-cursor is held in a per-DB ``invoice_diff_state`` mini-table
(autonomath.db) so re-runs only fetch the delta. PDL v1.0 attribution is
preserved (memory `project_nta_invoice_api_blocker`).

Constraints
-----------
* LLM call = 0. Pure httpx + sqlite3.
* Only ``api.invoice.nta.go.jp`` (official endpoint, PDL v1.0 redistribution OK).
* Idempotent upsert pattern; safe to re-run within same window.
* No full-table scan — every read is ``WHERE houjin_bangou = ?``.

Usage
-----
    python scripts/cron/diff_invoice_registrants_daily.py
    python scripts/cron/diff_invoice_registrants_daily.py --since-cursor 2026-05-11T00:00:00
    python scripts/cron/diff_invoice_registrants_daily.py --dry-run

Exit codes
----------
0  success
1  fatal (db missing, API 5xx past retry budget)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sqlite3
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

logger = logging.getLogger("jpcite.cron.invoice_diff")

# ---------------------------------------------------------------------------
# Config — NTA API only
# ---------------------------------------------------------------------------

NTA_INVOICE_API_BASE = "https://api.invoice.nta.go.jp/v1/h-num"
NTA_INVOICE_API_HOST_SUFFIX = ".nta.go.jp"
RATE_LIMIT_SECONDS = 1.0
PAGE_SIZE = 100
MAX_PAGES_PER_RUN = 200  # 20,000 row daily ceiling
HTTPX_TIMEOUT = httpx.Timeout(30.0, connect=10.0)
USER_AGENT = "jpcite-invoice-diff-daily/0.3.5 (+https://jpcite.com)"

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = _REPO_ROOT / "autonomath.db"

PDL_LICENSE = "PDL_v1.0"
PDL_NOTICE = "Source: NTA 適格請求書発行事業者公表 (Public Domain License v1.0)"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    p.add_argument(
        "--db",
        default=os.environ.get("AUTONOMATH_DB_PATH", str(DEFAULT_DB_PATH)),
    )
    p.add_argument(
        "--since-cursor",
        default=None,
        help="ISO-8601 timestamp; overrides the stored cursor.",
    )
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("-v", "--verbose", action="store_true")
    return p.parse_args(argv)


# ---------------------------------------------------------------------------
# DB
# ---------------------------------------------------------------------------


def _open(path: str) -> sqlite3.Connection:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"db missing: {p}")
    conn = sqlite3.connect(str(p), timeout=30.0)
    conn.execute("PRAGMA busy_timeout=300000")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_tables(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS invoice_registrants (
            houjin_bangou       TEXT PRIMARY KEY,
            registration_no     TEXT,
            name                TEXT,
            address             TEXT,
            prefecture          TEXT,
            registered_at       TEXT,
            withdrawn_at        TEXT,
            is_active           INTEGER NOT NULL DEFAULT 1
                                  CHECK(is_active IN (0,1)),
            row_hash            TEXT,
            license             TEXT,
            license_notice      TEXT,
            retrieved_at        TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS ix_invoice_registrants_active
            ON invoice_registrants(is_active);
        CREATE INDEX IF NOT EXISTS ix_invoice_registrants_pref
            ON invoice_registrants(prefecture);

        CREATE TABLE IF NOT EXISTS invoice_diff_state (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        """
    )
    conn.commit()


def _load_cursor(conn: sqlite3.Connection) -> str:
    row = conn.execute("SELECT value FROM invoice_diff_state WHERE key = 'since_cursor'").fetchone()
    if row is None:
        return (datetime.now(UTC) - timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%S")
    return str(row["value"])


def _save_cursor(conn: sqlite3.Connection, cursor: str) -> None:
    conn.execute(
        """
        INSERT INTO invoice_diff_state(key, value) VALUES('since_cursor', ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """,
        (cursor,),
    )


# ---------------------------------------------------------------------------
# API fetch
# ---------------------------------------------------------------------------


def _allowed_host(url: str) -> bool:
    return urlparse(url).netloc.lower().endswith(NTA_INVOICE_API_HOST_SUFFIX)


def _fetch_page(client: httpx.Client, since: str, page: int) -> list[dict[str, Any]]:
    if not _allowed_host(NTA_INVOICE_API_BASE):
        return []
    params = {
        "type": "06",
        "from": since,
        "page": page,
        "size": PAGE_SIZE,
        "format": "json",
    }
    try:
        resp = client.get(
            f"{NTA_INVOICE_API_BASE}/diff",
            params=params,
            headers={"User-Agent": USER_AGENT},
        )
    except httpx.HTTPError as exc:
        logger.warning("invoice diff fetch failed page=%d err=%s", page, exc)
        return []
    if resp.status_code == 429:
        time.sleep(5.0)
        return []
    if resp.status_code != 200:
        logger.warning("invoice diff HTTP %d page=%d", resp.status_code, page)
        return []
    try:
        payload = resp.json()
    except (ValueError, json.JSONDecodeError):
        logger.warning("invoice diff non-JSON response page=%d", page)
        return []
    return list(payload.get("items") or payload.get("results") or [])


# ---------------------------------------------------------------------------
# Upsert + soft-delete
# ---------------------------------------------------------------------------


def _row_from_api(rec: dict[str, Any]) -> dict[str, Any] | None:
    houjin = rec.get("houjin_bangou") or rec.get("corporateNumber") or rec.get("hojinBangou")
    if not houjin:
        return None
    name = (rec.get("name") or rec.get("registrant_name") or "").strip()
    addr = (rec.get("address") or rec.get("registrant_address") or "").strip()
    reg_no = (rec.get("registration_no") or rec.get("registrationNumber") or "").strip()
    pref = (rec.get("prefecture") or rec.get("registrant_prefecture") or "").strip()
    registered_at = rec.get("registered_at") or rec.get("registrationDate") or ""
    withdrawn_at = rec.get("withdrawn_at") or rec.get("withdrawalDate")
    is_active = 0 if withdrawn_at else 1
    payload = json.dumps(rec, sort_keys=True, ensure_ascii=False)
    row_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return {
        "houjin_bangou": str(houjin),
        "registration_no": reg_no,
        "name": name,
        "address": addr,
        "prefecture": pref,
        "registered_at": registered_at,
        "withdrawn_at": withdrawn_at,
        "is_active": is_active,
        "row_hash": row_hash,
        "license": PDL_LICENSE,
        "license_notice": PDL_NOTICE,
        "retrieved_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def _upsert(conn: sqlite3.Connection, row: dict[str, Any]) -> tuple[int, int, int]:
    """Returns (inserted, updated, soft_deleted)."""
    existing = conn.execute(
        "SELECT row_hash, is_active FROM invoice_registrants WHERE houjin_bangou = ?",
        (row["houjin_bangou"],),
    ).fetchone()
    if existing is None:
        conn.execute(
            """
            INSERT INTO invoice_registrants(
                houjin_bangou, registration_no, name, address, prefecture,
                registered_at, withdrawn_at, is_active, row_hash, license,
                license_notice, retrieved_at
            ) VALUES (
                :houjin_bangou, :registration_no, :name, :address, :prefecture,
                :registered_at, :withdrawn_at, :is_active, :row_hash, :license,
                :license_notice, :retrieved_at
            )
            """,
            row,
        )
        soft_del = 1 if row["is_active"] == 0 else 0
        return (1, 0, soft_del)
    if existing["row_hash"] == row["row_hash"]:
        return (0, 0, 0)
    conn.execute(
        """
        UPDATE invoice_registrants
        SET registration_no = :registration_no,
            name = :name,
            address = :address,
            prefecture = :prefecture,
            registered_at = :registered_at,
            withdrawn_at = :withdrawn_at,
            is_active = :is_active,
            row_hash = :row_hash,
            license = :license,
            license_notice = :license_notice,
            retrieved_at = :retrieved_at
        WHERE houjin_bangou = :houjin_bangou
        """,
        row,
    )
    soft_del = 1 if (existing["is_active"] == 1 and row["is_active"] == 0) else 0
    return (0, 1, soft_del)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def run(db_path: Path, since_override: str | None, dry_run: bool) -> dict[str, int]:
    counters = {
        "fetched": 0,
        "inserted": 0,
        "updated": 0,
        "soft_deleted": 0,
        "pages": 0,
    }
    conn: sqlite3.Connection | None = None
    if not dry_run:
        conn = _open(str(db_path))
        _ensure_tables(conn)
    since = since_override
    if since is None and conn is not None:
        since = _load_cursor(conn)
    if since is None:
        since = (datetime.now(UTC) - timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%S")
    with httpx.Client(timeout=HTTPX_TIMEOUT) as client:
        for page in range(1, MAX_PAGES_PER_RUN + 1):
            items = _fetch_page(client, since, page)
            counters["pages"] = page
            if not items:
                break
            counters["fetched"] += len(items)
            for rec in items:
                row = _row_from_api(rec)
                if row is None:
                    continue
                if conn is None:
                    counters["inserted"] += 1
                    continue
                ins, upd, sdel = _upsert(conn, row)
                counters["inserted"] += ins
                counters["updated"] += upd
                counters["soft_deleted"] += sdel
            time.sleep(RATE_LIMIT_SECONDS)
    if conn is not None:
        # Advance cursor to now (next run will pick from here).
        new_cursor = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S")
        _save_cursor(conn, new_cursor)
        conn.commit()
        conn.close()
    return counters


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    try:
        counters = run(
            db_path=Path(args.db),
            since_override=args.since_cursor,
            dry_run=args.dry_run,
        )
    except FileNotFoundError as exc:
        logger.error("db_missing err=%s", exc)
        return 1
    except (httpx.HTTPError, sqlite3.DatabaseError) as exc:
        logger.error("fatal err=%s", exc)
        return 1
    logger.info("invoice_diff_done %s", json.dumps(counters))
    return 0


if __name__ == "__main__":
    sys.exit(main())
