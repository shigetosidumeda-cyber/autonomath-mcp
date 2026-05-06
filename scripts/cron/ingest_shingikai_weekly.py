#!/usr/bin/env python3
"""Weekly 12 council 議事録 ingest cron (DEEP-39 IA-04 #1-2 implementation).

For each council in ``data/autonomath/shingikai_sources.yml``:
  1. Fetch the index_url.
  2. Extract PDF anchors via the council's ``pdf_url_pattern``.
  3. Fetch each PDF, extract text via pdfplumber (fallback: skip + log).
  4. Insert one ``shingikai_minutes`` row per PDF (idempotent on PK).
  5. If 議題 / body_text matches any 業法 keyword, emit a
     ``regulatory_signal`` row (signal_kind = 'shingikai_topic',
     lead_time_months = 12 — heuristic for 9-18 month median 中央値).

Constraints
-----------

* LLM calls = 0. Pure regex + pdfplumber + httpx + sqlite3 + pyyaml.
* Rate limit: 2 req/sec via asyncio.Semaphore + sleep 0.5.
* Body persistence: extract-only. PDF binary is NOT stored. Text capped
  at 200 KB / row to keep autonomath.db growth bounded (DEEP-39 §3
  estimate: 24 GB raw → 3-5 GB extracted).
* Per-council try/except: one DOM change does not halt the other 11.
* Idempotent: ``INSERT OR IGNORE`` on PK.

Usage
-----
    python scripts/cron/ingest_shingikai_weekly.py
    python scripts/cron/ingest_shingikai_weekly.py --max-pdfs 3
    python scripts/cron/ingest_shingikai_weekly.py --council cao_kisei_kaikaku

Exit codes
----------
0  success
1  fatal (db missing, config missing, all 12 councils failed)
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import logging
import os
import re
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import httpx

logger = logging.getLogger("jpintel.cron.shingikai_weekly")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = _REPO_ROOT / "autonomath.db"
DEFAULT_CONFIG = _REPO_ROOT / "data" / "autonomath" / "shingikai_sources.yml"

DEFAULT_LEAD_TIME_MONTHS = 12  # 審議会段階は 9-18ヶ月の中央値
RATE_LIMIT_SECONDS = 0.5  # 2 req/sec
MAX_PDFS_PER_COUNCIL = 5  # safety cap per run per council
MAX_BODY_BYTES = 200_000  # cap stored body_text at 200 KB / row
HTTPX_TIMEOUT = httpx.Timeout(60.0, connect=10.0)
USER_AGENT = "jpcite-shingikai-ingest/0.3.4 (+https://jpcite.com)"


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument(
        "--db",
        default=os.environ.get("AUTONOMATH_DB_PATH", str(DEFAULT_DB_PATH)),
    )
    p.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG),
        help="YAML path with the 12 council list (default: %(default)s).",
    )
    p.add_argument(
        "--council",
        default=None,
        help="Run only this council id (filter; default: all 12).",
    )
    p.add_argument(
        "--max-pdfs",
        type=int,
        default=MAX_PDFS_PER_COUNCIL,
        help="Max PDFs per council per run (default: %(default)s).",
    )
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("-v", "--verbose", action="store_true")
    return p.parse_args(argv)


# ---------------------------------------------------------------------------
# Config loader
# ---------------------------------------------------------------------------


def _load_config(path: str) -> dict[str, Any]:
    """Load council YAML config with defensive fallbacks."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"shingikai config missing: {p}")
    try:
        import yaml  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError("pyyaml required for shingikai cron; pip install pyyaml") from exc
    with p.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise ValueError(f"shingikai config root must be a mapping: {p}")
    return data


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


def _open_db(path: str) -> sqlite3.Connection:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"autonomath.db missing: {p}")
    conn = sqlite3.connect(str(p), timeout=30.0)
    conn.execute("PRAGMA busy_timeout=300000")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.row_factory = sqlite3.Row
    return conn


# ---------------------------------------------------------------------------
# PDF extraction
# ---------------------------------------------------------------------------


def _extract_pdf_text(pdf_bytes: bytes) -> str:
    """Run pdfplumber over PDF bytes, returning concatenated text.

    Returns an "OCR_NEEDED" marker when the PDF has zero text-bearing pages
    (image-only PDFs). pdfplumber is imported lazily so the rest of the
    cron still runs in environments without it installed.
    """
    try:
        import pdfplumber  # type: ignore[import-untyped]
    except ImportError:
        logger.warning("pdfplumber not installed; cannot extract PDFs")
        return ""
    import io

    parts: list[str] = []
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages:
                txt = page.extract_text() or ""
                if txt:
                    parts.append(txt)
    except Exception as exc:  # pdfplumber raises broad PDF exceptions
        logger.warning("pdf extract failed: %s", exc)
        return ""
    body = "\n".join(parts).strip()
    if not body:
        return "OCR_NEEDED"
    return body[:MAX_BODY_BYTES]


# ---------------------------------------------------------------------------
# PDF URL discovery
# ---------------------------------------------------------------------------


async def _fetch_index_pdfs(
    client: httpx.AsyncClient,
    semaphore: asyncio.Semaphore,
    council: dict[str, Any],
) -> list[str]:
    """Return absolute PDF URLs found on the council's index page."""
    index_url = council["index_url"]
    pattern = council.get("pdf_url_pattern", r'href="([^"]+\.pdf)"')
    async with semaphore:
        try:
            resp = await client.get(index_url)
        except httpx.HTTPError as exc:
            logger.warning("council %s index fetch failed: %s", council["id"], exc)
            return []
        await asyncio.sleep(RATE_LIMIT_SECONDS)
    if resp.status_code != 200:
        logger.warning("council %s index HTTP %d", council["id"], resp.status_code)
        return []
    raw_urls: list[str] = re.findall(pattern, resp.text)
    abs_urls: list[str] = []
    seen: set[str] = set()
    for u in raw_urls:
        absolute = urljoin(index_url, u)
        if absolute in seen:
            continue
        seen.add(absolute)
        abs_urls.append(absolute)
    return abs_urls


# ---------------------------------------------------------------------------
# Council walker
# ---------------------------------------------------------------------------


async def _process_council(
    client: httpx.AsyncClient,
    semaphore: asyncio.Semaphore,
    conn: sqlite3.Connection,
    council: dict[str, Any],
    keyword_union: tuple[str, ...],
    max_pdfs: int,
    dry_run: bool,
) -> tuple[int, int]:
    """Walk one council's PDF index, returning (minutes_added, signals_added)."""
    minutes_added = 0
    signals_added = 0
    pdfs = await _fetch_index_pdfs(client, semaphore, council)
    pdfs = pdfs[:max_pdfs]
    logger.info("council %s: %d PDFs to process", council["id"], len(pdfs))
    for pdf_url in pdfs:
        async with semaphore:
            try:
                resp = await client.get(pdf_url)
            except httpx.HTTPError as exc:
                logger.warning("council %s pdf fetch failed: %s — %s", council["id"], pdf_url, exc)
                await asyncio.sleep(RATE_LIMIT_SECONDS)
                continue
            await asyncio.sleep(RATE_LIMIT_SECONDS)
        if resp.status_code != 200:
            logger.warning("council %s pdf HTTP %d: %s", council["id"], resp.status_code, pdf_url)
            continue
        body_text = _extract_pdf_text(resp.content)
        if not body_text:
            continue
        sha256 = hashlib.sha256(resp.content).hexdigest()
        rid = f"{council['id']}:{sha256[:16]}"
        retrieved_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        # Heuristic 'date' from URL or today.
        date_match = re.search(r"(20\d{2})[-/]?(\d{1,2})[-/]?(\d{1,2})", pdf_url)
        if date_match:
            iso_date = f"{date_match.group(1)}-{int(date_match.group(2)):02d}-{int(date_match.group(3)):02d}"
        else:
            iso_date = datetime.now(UTC).strftime("%Y-%m-%d")
        # Agenda heuristic: first non-empty line of body_text.
        agenda_lines = [ln.strip() for ln in body_text.splitlines() if ln.strip()]
        agenda = agenda_lines[0][:200] if agenda_lines else None
        if dry_run:
            continue
        try:
            cur = conn.execute(
                """
                INSERT OR IGNORE INTO shingikai_minutes
                    (id, ministry, council, date, agenda, body_text, pdf_url,
                     retrieved_at, sha256)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    rid,
                    council["ministry"],
                    council["council"],
                    iso_date,
                    agenda,
                    body_text,
                    pdf_url,
                    retrieved_at,
                    sha256,
                ),
            )
            if cur.rowcount > 0:
                minutes_added += 1
        except sqlite3.Error as exc:
            logger.warning("council %s DB insert failed: %s", council["id"], exc)
            continue
        # Signal emission: every keyword hit in (agenda + body_text).
        haystack = (agenda or "") + " " + body_text
        for kw in keyword_union:
            if kw not in haystack:
                continue
            sig_id = f"shingikai:{rid}:{kw}"
            try:
                cur = conn.execute(
                    """
                    INSERT OR IGNORE INTO regulatory_signal
                        (id, signal_kind, law_target, lead_time_months,
                         evidence_url, detected_at)
                    VALUES (?, 'shingikai_topic', ?, ?, ?, ?)
                    """,
                    (
                        sig_id,
                        kw,
                        DEFAULT_LEAD_TIME_MONTHS,
                        pdf_url,
                        retrieved_at,
                    ),
                )
                if cur.rowcount > 0:
                    signals_added += 1
            except sqlite3.Error:
                continue
    if not dry_run:
        conn.commit()
    return minutes_added, signals_added


# ---------------------------------------------------------------------------
# Main async driver
# ---------------------------------------------------------------------------


async def run(args: argparse.Namespace) -> int:
    config = _load_config(args.config)
    councils = config.get("councils") or []
    if args.council:
        councils = [c for c in councils if c.get("id") == args.council]
    if not councils:
        logger.error("no councils to process (filter=%s)", args.council)
        return 1
    keyword_union = tuple(config.get("keyword_union") or [])
    conn = _open_db(args.db)
    semaphore = asyncio.Semaphore(2)
    total_minutes = 0
    total_signals = 0
    success_councils = 0
    async with httpx.AsyncClient(
        timeout=HTTPX_TIMEOUT,
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT},
    ) as client:
        for council in councils:
            try:
                m, s = await _process_council(
                    client,
                    semaphore,
                    conn,
                    council,
                    keyword_union,
                    args.max_pdfs,
                    args.dry_run,
                )
                total_minutes += m
                total_signals += s
                success_councils += 1
                logger.info("council %s done: minutes=+%d signals=+%d", council["id"], m, s)
            except Exception:
                logger.exception("council %s failed; continuing", council["id"])
                continue
    conn.close()
    logger.info(
        "shingikai weekly cron done: councils_ok=%d/%d minutes=+%d signals=+%d",
        success_councils,
        len(councils),
        total_minutes,
        total_signals,
    )
    if success_councils == 0:
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    try:
        return asyncio.run(run(args))
    except FileNotFoundError as exc:
        print(f"FATAL: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 1
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("shingikai weekly cron failed")
        print(f"FATAL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
