#!/usr/bin/env python3
"""ingest_edinet_daily.py — Daily EDINET full-text ingest cron.

Wave 31 Axis 1c. Populates `am_edinet_filings` (migration 227,
target_db=autonomath) with the full-text companion rows for the
existing `edinet_filing_signal_layer` (mig wave24_176, signal-only).

Source
------
EDINET API v2 — https://disclosure2.edinet-fsa.go.jp/

    * /api/v2/documents.json?date=YYYY-MM-DD&type=2
        — daily document list (type=2 = 提出書類一覧 + metadata)
    * /api/v2/documents/{docId}?type=1   — 提出本文(XBRL/PDF)
    * /api/v2/documents/{docId}?type=2   — PDF
    * /api/v2/documents/{docId}?type=5   — 添付文書

公式 API のみ。aggregator (有報読み / Strainer / kabuyoho 等) 禁止 per
memory feedback_no_fake_data.

Schedule
--------
    Daily 04:30 JST = 19:30 UTC (previous day). EDINET の 04:00 JST 公開
    タイミング後 30 分待機して取得。週末 / 祝日 でも空 list を fetch する
    だけなので running cost は最小。

Constraints
-----------
    * LLM call count: 0. lxml + sqlite3 + httpx + json + hashlib のみ。
      XBRL → plain text 変換 も pure lxml で済ませる。
    * Rate limit: 1 req/sec via asyncio.Semaphore(1) + sleep
      RATE_LIMIT_SECONDS.
    * Idempotent: INSERT OR REPLACE on doc_id. content_hash 一致時 は
      UPDATE skip (no-op).
    * R2 upload: full XBRL/PDF body は R2 にアップロードして `full_text_r2_url`
      に URL を保存する。R2 client は `scripts/cron/_r2_client.py` の
      既存 helper を経由する。R2 secret が無い CI 環境では upload step は
      no-op で進行し、`full_text_r2_url = NULL` に倒れる (excerpt のみ保存)。
    * Failure path: stderr + sys.exit(1) so the workflow alert fires.

Usage
-----
    python scripts/cron/ingest_edinet_daily.py
    python scripts/cron/ingest_edinet_daily.py --date 2026-05-11 --limit 100
    python scripts/cron/ingest_edinet_daily.py --dry-run

Exit codes
----------
    0 success
    1 fetch / IO failure
    2 schema missing (run migration 227 first)
    3 argument validation failure
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import os
import re
import sqlite3
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger("jpintel.cron.edinet_daily")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

EDINET_BASE = "https://disclosure2.edinet-fsa.go.jp"
EDINET_LIST = f"{EDINET_BASE}/api/v2/documents.json"
EDINET_DOWNLOAD = f"{EDINET_BASE}/api/v2/documents/{{doc_id}}"

RATE_LIMIT_SECONDS = 1.0
HTTPX_TIMEOUT = httpx.Timeout(60.0, connect=15.0)
USER_AGENT = "jpcite-edinet-daily-ingest/0.3.5 (+https://jpcite.com)"

DEFAULT_LIMIT = 100
EXCERPT_CHAR_CAP = 5120  # mirror migration 227 CHECK

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = _REPO_ROOT / "autonomath.db"


# ---------------------------------------------------------------------------
# Arg parsing
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    p.add_argument(
        "--date",
        default=None,
        help="Target submit date (YYYY-MM-DD). Defaults to yesterday JST.",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_LIMIT,
        help=f"Maximum filings to ingest per run (safety cap, default {DEFAULT_LIMIT}).",
    )
    p.add_argument(
        "--db",
        default=os.environ.get("AUTONOMATH_DB_PATH", str(DEFAULT_DB_PATH)),
        help="autonomath.db path (default: %(default)s).",
    )
    p.add_argument(
        "--api-key",
        default=os.environ.get("EDINET_API_KEY"),
        help="EDINET API v2 subscription key (or EDINET_API_KEY env).",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch + parse only; do not INSERT or upload to R2.",
    )
    p.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Verbose logging.",
    )
    return p.parse_args(argv)


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


def _open_db(path: str) -> sqlite3.Connection:
    """Open autonomath.db for read+write."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"autonomath.db missing: {p}")
    conn = sqlite3.connect(str(p), timeout=30.0)
    conn.execute("PRAGMA busy_timeout=300000")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.row_factory = sqlite3.Row
    return conn


def _schema_required(conn: sqlite3.Connection) -> None:
    """Verify migration 227 schema is present, exit 2 otherwise."""
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='am_edinet_filings'"
    ).fetchone()
    if not row:
        logger.error("am_edinet_filings table missing — run migration 227 first")
        sys.exit(2)


def _existing_hash(conn: sqlite3.Connection, doc_id: str) -> str | None:
    """Return current content_hash for doc_id, or None if absent."""
    row = conn.execute(
        "SELECT content_hash FROM am_edinet_filings WHERE doc_id = ?",
        (doc_id,),
    ).fetchone()
    return row["content_hash"] if row else None


# ---------------------------------------------------------------------------
# EDINET API client
# ---------------------------------------------------------------------------


async def _fetch_document_list(
    client: httpx.AsyncClient,
    semaphore: asyncio.Semaphore,
    target_date: date,
    api_key: str | None,
) -> list[dict[str, Any]]:
    """Fetch EDINET documents.json for a single date.

    Returns the `results` list. Empty on no submissions.
    """
    params: dict[str, Any] = {
        "date": target_date.strftime("%Y-%m-%d"),
        "type": "2",
    }
    if api_key:
        params["Subscription-Key"] = api_key
    async with semaphore:
        try:
            resp = await client.get(EDINET_LIST, params=params)
        except httpx.HTTPError as exc:
            logger.warning("EDINET list fetch failed on %s: %s", target_date, exc)
            await asyncio.sleep(RATE_LIMIT_SECONDS * 2)
            return []
        await asyncio.sleep(RATE_LIMIT_SECONDS)
    if resp.status_code != 200:
        logger.warning("EDINET list HTTP %d on %s", resp.status_code, target_date)
        return []
    try:
        payload = resp.json()
    except (ValueError, json.JSONDecodeError):
        logger.warning("EDINET list non-JSON response on %s", target_date)
        return []
    return list(payload.get("results") or [])


async def _fetch_document_body(
    client: httpx.AsyncClient,
    semaphore: asyncio.Semaphore,
    doc_id: str,
    api_key: str | None,
) -> bytes | None:
    """Fetch the EDINET XBRL zip for a doc_id. Returns bytes or None."""
    params: dict[str, Any] = {"type": "1"}
    if api_key:
        params["Subscription-Key"] = api_key
    url = EDINET_DOWNLOAD.format(doc_id=doc_id)
    async with semaphore:
        try:
            resp = await client.get(url, params=params)
        except httpx.HTTPError as exc:
            logger.warning("EDINET body fetch failed for %s: %s", doc_id, exc)
            await asyncio.sleep(RATE_LIMIT_SECONDS * 2)
            return None
        await asyncio.sleep(RATE_LIMIT_SECONDS)
    if resp.status_code != 200:
        logger.warning("EDINET body HTTP %d for %s", resp.status_code, doc_id)
        return None
    return resp.content


# ---------------------------------------------------------------------------
# XBRL → plain text (lxml, no LLM)
# ---------------------------------------------------------------------------


_WHITESPACE_RE = re.compile(r"\s+")


def xbrl_zip_to_excerpt(zip_bytes: bytes) -> str:
    """Best-effort XBRL ZIP → plain text excerpt (≤ EXCERPT_CHAR_CAP chars).

    Walks the ZIP for any *.htm / *.xml / *.xbrl files, strips tags via lxml,
    collapses whitespace, concatenates, and truncates. Failure modes return "".
    """
    if not zip_bytes:
        return ""
    import io
    import zipfile

    try:
        from lxml import etree  # type: ignore[import-untyped]
    except ImportError:
        etree = None  # type: ignore[assignment]

    try:
        z = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except (zipfile.BadZipFile, OSError) as exc:
        logger.warning("XBRL zip invalid: %s", exc)
        return ""

    pieces: list[str] = []
    for name in sorted(z.namelist()):
        if not name.lower().endswith((".htm", ".html", ".xml", ".xbrl")):
            continue
        try:
            raw = z.read(name)
        except KeyError:
            continue
        text = ""
        if etree is not None:
            try:
                parser = etree.HTMLParser() if name.lower().endswith((".htm", ".html")) else etree.XMLParser(recover=True)
                root = etree.fromstring(raw, parser=parser)
                if root is not None:
                    text = "".join(root.itertext())
            except (etree.XMLSyntaxError, etree.ParserError, ValueError):
                text = ""
        if not text:
            # Naive fallback: strip tags via regex.
            try:
                decoded = raw.decode("utf-8", errors="replace")
            except UnicodeDecodeError:
                decoded = raw.decode("cp932", errors="replace")
            text = re.sub(r"<[^>]+>", " ", decoded)
        text = _WHITESPACE_RE.sub(" ", text).strip()
        if text:
            pieces.append(text)
        joined = " ".join(pieces)
        if len(joined) >= EXCERPT_CHAR_CAP:
            return joined[:EXCERPT_CHAR_CAP]
    return " ".join(pieces)[:EXCERPT_CHAR_CAP]


# ---------------------------------------------------------------------------
# R2 upload (best-effort)
# ---------------------------------------------------------------------------


def _maybe_upload_r2(zip_bytes: bytes, doc_id: str, *, dry_run: bool) -> str | None:
    """Upload XBRL ZIP to R2 under edinet/full/{doc_id}.zip; return URL or None.

    Best-effort: missing env / missing helper / upload failure all return None.
    """
    if dry_run or not zip_bytes:
        return None
    try:
        from scripts.cron import _r2_client  # type: ignore[import-not-found]
    except ImportError:
        logger.debug("_r2_client helper unavailable; skipping R2 upload")
        return None
    key = f"edinet/full/{doc_id}.zip"
    try:
        url = _r2_client.upload(key, zip_bytes, content_type="application/zip")  # type: ignore[attr-defined]
    except Exception as exc:  # noqa: BLE001 — upload is best-effort
        logger.warning("R2 upload failed for %s: %s", doc_id, exc)
        return None
    return str(url) if url else None


# ---------------------------------------------------------------------------
# Parsing + row build
# ---------------------------------------------------------------------------


def _normalize_houjin_bangou(raw: str | None) -> str | None:
    if not raw:
        return None
    s = re.sub(r"\D", "", str(raw))
    if len(s) == 13:
        return s
    return None


def _normalize_security_code(raw: str | None) -> str | None:
    if not raw:
        return None
    s = re.sub(r"\D", "", str(raw))
    if len(s) == 5:
        return s
    return None


def _normalize_edinet_code(raw: str | None) -> str | None:
    if not raw:
        return None
    s = str(raw).strip().upper()
    if s.startswith("E") and len(s) >= 6:
        return s
    return None


def _filing_id(doc_id: str, content_hash: str) -> str:
    """Deterministic PK for am_edinet_filings."""
    return hashlib.sha1(f"{doc_id}:{content_hash}".encode("utf-8")).hexdigest()


def _content_hash(row_envelope: dict[str, Any]) -> str:
    """SHA-256 of canonical envelope fields for drift detection."""
    canonical = json.dumps(
        {
            "doc_id": row_envelope.get("doc_id", ""),
            "edinet_code": row_envelope.get("edinet_code", ""),
            "submit_date": row_envelope.get("submit_date", ""),
            "doc_type": row_envelope.get("doc_type", ""),
            "body_text_excerpt": row_envelope.get("body_text_excerpt", ""),
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def parse_edinet_record(
    rec: dict[str, Any], *, body_excerpt: str, full_text_r2_url: str | None
) -> dict[str, Any] | None:
    """Convert one EDINET API record into an `am_edinet_filings` row."""
    doc_id = (rec.get("docID") or rec.get("docId") or "").strip()
    if not doc_id:
        return None
    edinet_code = _normalize_edinet_code(rec.get("edinetCode"))
    if not edinet_code:
        return None
    submit_date = (rec.get("submitDateTime") or rec.get("submitDate") or "")[:10]
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", submit_date):
        return None
    doc_type = (rec.get("docTypeCode") or rec.get("docType") or "").strip()
    if not doc_type:
        doc_type = "unknown"
    security_code = _normalize_security_code(rec.get("secCode"))
    filer_houjin_bangou = _normalize_houjin_bangou(rec.get("JCN") or rec.get("filerCorporateNumber"))

    file_xbrl_url = (
        f"{EDINET_BASE}/api/v2/documents/{doc_id}?type=1"
        if (rec.get("xbrlFlag") in (1, "1", True))
        else None
    )
    file_pdf_url = (
        f"{EDINET_BASE}/api/v2/documents/{doc_id}?type=2"
        if (rec.get("pdfFlag") in (1, "1", True))
        else None
    )

    envelope = {
        "doc_id": doc_id,
        "edinet_code": edinet_code,
        "security_code": security_code,
        "submit_date": submit_date,
        "doc_type": doc_type,
        "filer_houjin_bangou": filer_houjin_bangou,
        "file_pdf_url": file_pdf_url,
        "file_xbrl_url": file_xbrl_url,
        "body_text_excerpt": (body_excerpt or "")[:EXCERPT_CHAR_CAP],
        "full_text_r2_url": full_text_r2_url,
    }
    envelope["content_hash"] = _content_hash(envelope)
    envelope["filing_id"] = _filing_id(doc_id, envelope["content_hash"])
    return envelope


# ---------------------------------------------------------------------------
# INSERT
# ---------------------------------------------------------------------------


def _insert_row(
    conn: sqlite3.Connection,
    row: dict[str, Any],
    *,
    dry_run: bool,
) -> bool:
    """Upsert one EDINET filing row. Returns True if a write occurred."""
    existing = _existing_hash(conn, row["doc_id"])
    if existing == row["content_hash"]:
        return False
    if dry_run:
        return True
    conn.execute(
        """INSERT OR REPLACE INTO am_edinet_filings (
            filing_id, doc_id, edinet_code, security_code, submit_date,
            doc_type, filer_houjin_bangou, file_pdf_url, file_xbrl_url,
            body_text_excerpt, full_text_r2_url, content_hash, ingested_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            row["filing_id"],
            row["doc_id"],
            row["edinet_code"],
            row["security_code"],
            row["submit_date"],
            row["doc_type"],
            row["filer_houjin_bangou"],
            row["file_pdf_url"],
            row["file_xbrl_url"],
            row["body_text_excerpt"],
            row["full_text_r2_url"],
            row["content_hash"],
            datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%fZ"),
        ),
    )
    return True


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


async def _run(args: argparse.Namespace) -> int:
    if args.date:
        try:
            target_date = datetime.strptime(args.date, "%Y-%m-%d").date()
        except ValueError:
            logger.error("invalid --date: %s", args.date)
            return 3
    else:
        target_date = (datetime.now(UTC) + timedelta(hours=9) - timedelta(days=1)).date()

    conn = _open_db(args.db)
    try:
        _schema_required(conn)
        headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
        async with httpx.AsyncClient(
            headers=headers, timeout=HTTPX_TIMEOUT, follow_redirects=True
        ) as client:
            semaphore = asyncio.Semaphore(1)
            records = await _fetch_document_list(
                client, semaphore, target_date, args.api_key
            )
            logger.info(
                "EDINET list returned %d records for %s", len(records), target_date
            )

            inserted = 0
            skipped = 0
            rejected = 0
            for raw in records[: args.limit]:
                doc_id = (raw.get("docID") or raw.get("docId") or "").strip()
                if not doc_id:
                    rejected += 1
                    continue

                zip_bytes: bytes | None = None
                if raw.get("xbrlFlag") in (1, "1", True):
                    zip_bytes = await _fetch_document_body(
                        client, semaphore, doc_id, args.api_key
                    )

                excerpt = xbrl_zip_to_excerpt(zip_bytes or b"")
                r2_url = _maybe_upload_r2(zip_bytes or b"", doc_id, dry_run=args.dry_run)
                row = parse_edinet_record(
                    raw,
                    body_excerpt=excerpt,
                    full_text_r2_url=r2_url,
                )
                if row is None:
                    rejected += 1
                    continue
                if _insert_row(conn, row, dry_run=args.dry_run):
                    inserted += 1
                else:
                    skipped += 1

        if not args.dry_run:
            conn.commit()

        logger.info(
            "summary date=%s inserted=%d skipped=%d rejected=%d dry_run=%s",
            target_date, inserted, skipped, rejected, args.dry_run,
        )
        return 0
    except sqlite3.Error as exc:
        logger.error("sqlite error: %s", exc)
        return 1
    except Exception as exc:  # noqa: BLE001 — top-level orchestrator
        logger.error("unexpected error: %s", exc, exc_info=True)
        return 1
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    return asyncio.run(_run(args))


if __name__ == "__main__":
    sys.exit(main())
