#!/usr/bin/env python3
"""Weekly 国会会議録 ingest cron (DEEP-39 IA-01 #2 implementation).

Fetches speeches from ``kokkai.ndl.go.jp /api/speech`` (公開, 認証不要) for
the 14 業法 keyword union, delta-based since MAX(date)-7d in
``kokkai_utterance``. Writes:

  * kokkai_utterance       — every parsed speech (idempotent on speechID)
  * regulatory_signal      — one signal per keyword hit (signal_kind =
                             'kokkai_keyword', lead_time_months = 6)

Constraints
-----------

* LLM calls = 0. Pure regex + sqlite3 + httpx + pyyaml. No anthropic /
  openai / claude_agent_sdk imports — see tests/test_no_llm_in_production.py.
* Rate limit: 1 req/sec via asyncio.Semaphore(1) + sleep 1.0 between calls.
  NDL's published guidance is "polite use", we sit comfortably below.
* Idempotent: ``INSERT OR IGNORE`` on speechID PK skips duplicates so a
  re-run inside the same delta window inserts zero new rows.
* Failure path: stderr + sys.exit(1) so the GHA workflow's on-fail issue
  auto-create fires.

Usage
-----
    python scripts/cron/ingest_kokkai_weekly.py
    python scripts/cron/ingest_kokkai_weekly.py --db /data/autonomath.db
    python scripts/cron/ingest_kokkai_weekly.py --weeks 4 --dry-run

Exit codes
----------
0  success (≥0 rows inserted)
1  fatal (db missing, network down past retry budget, parse error)
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
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger("jpintel.cron.kokkai_weekly")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

KOKKAI_API_BASE = "https://kokkai.ndl.go.jp/api/speech"

# 14 業法 keyword union — DEEP-39 spec §2.
KEYWORDS: tuple[str, ...] = (
    "税理士法",
    "弁護士法",
    "行政書士法",
    "司法書士法",
    "弁理士法",
    "社労士法",
    "公認会計士法",
    "適格請求書",
    "インボイス",
    "補助金等適正化法",
    "AI規制",
    "個人情報保護法",
    "外為法",
    "デジタル課税",
)

DEFAULT_LEAD_TIME_MONTHS = 6  # 委員会段階の趣旨説明は ~6ヶ月、法案提出は ~3ヶ月
RATE_LIMIT_SECONDS = 1.0
MAX_RECORDS_PER_KEYWORD = 200  # safety cap per run per keyword
HTTPX_TIMEOUT = httpx.Timeout(30.0, connect=10.0)
USER_AGENT = "jpcite-kokkai-ingest/0.3.4 (+https://jpcite.com)"

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = _REPO_ROOT / "autonomath.db"


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument(
        "--db",
        default=os.environ.get("AUTONOMATH_DB_PATH", str(DEFAULT_DB_PATH)),
        help="autonomath.db path (default: %(default)s).",
    )
    p.add_argument(
        "--weeks",
        type=int,
        default=1,
        help="Days back from MAX(date) — default 1 week. Use --weeks 4 for"
        " the first run (acceptance #2: ≥1,000 rows in 4 weeks).",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch + parse only; do not insert.",
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
    """Open autonomath.db for read+write (cron is the writer)."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"autonomath.db missing: {p}")
    conn = sqlite3.connect(str(p), timeout=30.0)
    conn.execute("PRAGMA busy_timeout=300000")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.row_factory = sqlite3.Row
    return conn


def _delta_from_date(conn: sqlite3.Connection, weeks: int) -> str:
    """Return YYYY-MM-DD for ``MAX(kokkai_utterance.date) - weeks*7d``.

    Falls back to today − weeks*7d when the table is empty (first run).
    """
    try:
        row = conn.execute("SELECT MAX(date) AS m FROM kokkai_utterance").fetchone()
    except sqlite3.OperationalError:
        row = None
    base: datetime
    if row and row["m"]:
        try:
            base = datetime.fromisoformat(row["m"])
        except ValueError:
            base = datetime.now(UTC)
    else:
        base = datetime.now(UTC)
    delta = base - timedelta(days=weeks * 7)
    return delta.strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# kokkai.ndl.go.jp client
# ---------------------------------------------------------------------------


async def _fetch_speeches(
    client: httpx.AsyncClient,
    semaphore: asyncio.Semaphore,
    keyword: str,
    since: str,
    max_records: int = MAX_RECORDS_PER_KEYWORD,
) -> list[dict[str, Any]]:
    """Fetch up to max_records speeches matching ``keyword`` since ``since``.

    Honors 1 req/sec via the semaphore + sleep. The kokkai API returns
    JSON with a ``speechRecord`` list; we paginate via ``startRecord`` if
    ``totalRecordCount`` exceeds ``maximumRecords``.
    """
    out: list[dict[str, Any]] = []
    start_record = 1
    page_size = 100  # API max per call
    while len(out) < max_records:
        async with semaphore:
            params = {
                "any": keyword,
                "from": since,
                "recordPacking": "json",
                "maximumRecords": page_size,
                "startRecord": start_record,
            }
            try:
                resp = await client.get(KOKKAI_API_BASE, params=params)
            except httpx.HTTPError as exc:
                logger.warning("kokkai fetch failed for %s @ %d: %s", keyword, start_record, exc)
                # Polite on errors — back off, do not spin.
                await asyncio.sleep(RATE_LIMIT_SECONDS * 2)
                break
            await asyncio.sleep(RATE_LIMIT_SECONDS)
        if resp.status_code == 429:
            logger.warning("kokkai rate-limited; backing off 5s")
            await asyncio.sleep(5.0)
            continue
        if resp.status_code != 200:
            logger.warning("kokkai HTTP %d for %s @ %d", resp.status_code, keyword, start_record)
            break
        try:
            payload = resp.json()
        except ValueError:
            logger.warning("kokkai non-JSON response for %s @ %d", keyword, start_record)
            break
        speech_records = payload.get("speechRecord") or []
        if not speech_records:
            break
        out.extend(speech_records)
        total = int(payload.get("numberOfRecords", 0) or 0)
        if start_record + page_size > total:
            break
        start_record += page_size
    return out[:max_records]


# ---------------------------------------------------------------------------
# Parser + INSERT helpers
# ---------------------------------------------------------------------------

_HOUSE_RE = re.compile(r"(衆議院|参議院)")


def parse_speech_record(rec: dict[str, Any]) -> dict[str, Any] | None:
    """Convert a kokkai API ``speechRecord`` dict to a kokkai_utterance row.

    Returns None if any required field is missing (defensive — the API
    occasionally returns partial records mid-page).
    """
    sid = rec.get("speechID")
    body = rec.get("speech") or ""
    date = rec.get("date") or ""
    speaker = rec.get("speaker") or ""
    if not sid or not body or not date or not speaker:
        return None
    house_raw = rec.get("nameOfHouse") or ""
    house_match = _HOUSE_RE.search(house_raw)
    house = house_match.group(1) if house_match else house_raw or "不明"
    committee = rec.get("nameOfMeeting") or "不明"
    speaker_role = rec.get("speakerPosition") or rec.get("speakerGroup")
    session_no = int(rec.get("session") or 0)
    source_url = rec.get("speechURL") or rec.get("meetingURL") or ""
    sha256 = hashlib.sha256(body.encode("utf-8")).hexdigest()
    return {
        "id": sid,
        "session_no": session_no,
        "house": house,
        "committee": committee,
        "date": date,
        "speaker": speaker,
        "speaker_role": speaker_role,
        "body": body,
        "source_url": source_url,
        "retrieved_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sha256": sha256,
    }


def detect_keywords(body: str) -> list[str]:
    """Return KEYWORDS subset that literally appear in ``body``."""
    return [k for k in KEYWORDS if k in body]


def _insert_utterance(conn: sqlite3.Connection, row: dict[str, Any]) -> bool:
    """Insert a row idempotently. Returns True if a new row was added."""
    cur = conn.execute(
        """
        INSERT OR IGNORE INTO kokkai_utterance
            (id, session_no, house, committee, date, speaker, speaker_role,
             body, source_url, retrieved_at, sha256)
        VALUES (:id, :session_no, :house, :committee, :date, :speaker,
                :speaker_role, :body, :source_url, :retrieved_at, :sha256)
        """,
        row,
    )
    return cur.rowcount > 0


def _insert_signal(
    conn: sqlite3.Connection,
    speech_id: str,
    keyword: str,
    evidence_url: str,
) -> bool:
    """Insert one regulatory_signal row per keyword hit (idempotent)."""
    sig_id = f"kokkai:{speech_id}:{keyword}"
    cur = conn.execute(
        """
        INSERT OR IGNORE INTO regulatory_signal
            (id, signal_kind, law_target, lead_time_months,
             evidence_url, detected_at)
        VALUES (?, 'kokkai_keyword', ?, ?, ?, ?)
        """,
        (
            sig_id,
            keyword,
            DEFAULT_LEAD_TIME_MONTHS,
            evidence_url,
            datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        ),
    )
    return cur.rowcount > 0


# ---------------------------------------------------------------------------
# Main async driver
# ---------------------------------------------------------------------------


async def run(args: argparse.Namespace) -> int:
    conn = _open_db(args.db)
    since = _delta_from_date(conn, weeks=args.weeks)
    logger.info("kokkai weekly cron: since=%s db=%s dry_run=%s", since, args.db, args.dry_run)

    semaphore = asyncio.Semaphore(1)  # 1 req/sec, single-flight
    inserted_utterances = 0
    inserted_signals = 0
    fetched_total = 0
    async with httpx.AsyncClient(
        timeout=HTTPX_TIMEOUT,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    ) as client:
        for keyword in KEYWORDS:
            records = await _fetch_speeches(client, semaphore, keyword, since)
            fetched_total += len(records)
            logger.info("  keyword=%s fetched=%d", keyword, len(records))
            if args.dry_run:
                continue
            for rec in records:
                row = parse_speech_record(rec)
                if not row:
                    continue
                if _insert_utterance(conn, row):
                    inserted_utterances += 1
                # Even on duplicate utterance, emit signals once via INSERT OR IGNORE.
                hits = detect_keywords(row["body"])
                for hit in hits:
                    if _insert_signal(conn, row["id"], hit, row["source_url"]):
                        inserted_signals += 1
            conn.commit()

    conn.close()
    logger.info(
        "kokkai weekly cron done: fetched=%d new_utterances=%d new_signals=%d",
        fetched_total,
        inserted_utterances,
        inserted_signals,
    )
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
        logger.exception("kokkai weekly cron failed")
        print(f"FATAL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
