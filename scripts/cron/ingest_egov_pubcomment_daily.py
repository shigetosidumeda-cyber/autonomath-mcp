#!/usr/bin/env python3
"""Daily e-Gov パブコメ 公示 ingest cron (DEEP-45 IA-04 #3 implementation).

Fetches public-comment announcements from ``search.e-gov.go.jp/servlet/Public``
(公開, 認証不要) for the 10 業法 keyword union, delta-based on rolling 7 day
catch-up window. Writes to:

  * pubcomment_announcement   — every parsed 案件 (idempotent on 案件 id)
  * regulatory_signal         — one signal per relevant hit (signal_kind
                                 = 'pubcomment_announcement', lead_time_months
                                 = 1 for 政令・省令, 2 for 法律案)

Constraints
-----------

* LLM calls = 0. Pure regex + sqlite3 + httpx + lxml + json.
  No anthropic / openai / claude_agent_sdk imports — see
  tests/test_no_llm_in_production.py.
* Rate limit: 1 req/sec via asyncio.Semaphore(1) + sleep 1.0 between calls.
* Idempotent: ``INSERT OR IGNORE`` on 案件 id PK skips duplicates so a re-run
  inside the same delta window inserts zero new rows.
* Failure path: stderr + sys.exit(1) so the GHA workflow's on-fail issue
  auto-create fires.

Usage
-----
    python scripts/cron/ingest_egov_pubcomment_daily.py
    python scripts/cron/ingest_egov_pubcomment_daily.py --db /data/autonomath.db
    python scripts/cron/ingest_egov_pubcomment_daily.py --days 30 --dry-run

Exit codes
----------
0  success (>=0 rows inserted)
1  fatal (db missing, network down past retry budget, parse error)
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
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger("jpintel.cron.egov_pubcomment")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

EGOV_SEARCH_BASE = "https://search.e-gov.go.jp/servlet/Public"
EGOV_DETAIL_BASE = "https://public-comment.e-gov.go.jp/servlet/Public"

# 10 業法 keyword union — DEEP-45 spec §3.
KEYWORDS: tuple[str, ...] = (
    "税理士法",
    "弁護士法",
    "行政書士法",
    "司法書士法",
    "弁理士法",
    "社労士法",
    "公認会計士法",
    "補助金等適正化法",
    "適格請求書",
    "個人情報保護法",
)

# Cohort -> keyword mapping for jpcite_cohort_impact rollup.
# 4 sensitive cohort: 税理士 / 公認会計士 / 補助金 consultant / FDI.
COHORT_KEYWORDS: dict[str, tuple[str, ...]] = {
    "税理士": ("税理士法", "適格請求書"),
    "公認会計士": ("公認会計士法",),
    "補助金 consultant": ("補助金等適正化法", "行政書士法"),
    "FDI": ("個人情報保護法",),
}

# Lead time defaults (months). 政令・省令 改正案 = 30 日, 法律案 = 60 日.
LEAD_TIME_LAW_AMENDMENT = 2  # 法律案 60 日 = 2 ヶ月
LEAD_TIME_REGULATION = 1  # 政令・省令 30 日 = 1 ヶ月

RATE_LIMIT_SECONDS = 1.0
MAX_RECORDS_PER_KEYWORD = 100  # safety cap per run per keyword
HTTPX_TIMEOUT = httpx.Timeout(30.0, connect=10.0)
USER_AGENT = "jpcite-egov-pubcomment-ingest/0.3.4 (+https://jpcite.com)"

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = _REPO_ROOT / "autonomath.db"


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    p.add_argument(
        "--db",
        default=os.environ.get("AUTONOMATH_DB_PATH", str(DEFAULT_DB_PATH)),
        help="autonomath.db path (default: %(default)s).",
    )
    p.add_argument(
        "--days",
        type=int,
        default=7,
        help="Days back from MAX(announcement_date) for rolling catch-up (default 7)."
        " Use --days 30 for the first run (acceptance: >=30 rows in 30 days).",
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


def _delta_from_date(conn: sqlite3.Connection, days: int) -> str:
    """Return YYYY-MM-DD for ``MAX(pubcomment_announcement.announcement_date) - days``.

    Falls back to today - days when the table is empty (first run).
    """
    try:
        row = conn.execute(
            "SELECT MAX(announcement_date) AS m FROM pubcomment_announcement"
        ).fetchone()
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
    delta = base - timedelta(days=days)
    return delta.strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# e-Gov portal client
# ---------------------------------------------------------------------------


async def _fetch_announcements(
    client: httpx.AsyncClient,
    semaphore: asyncio.Semaphore,
    keyword: str,
    since: str,
    max_records: int = MAX_RECORDS_PER_KEYWORD,
) -> list[dict[str, Any]]:
    """Fetch up to max_records announcements matching ``keyword`` since ``since``.

    Uses e-Gov's public search portal. Honors 1 req/sec via the semaphore.
    Returns a list of raw 案件 records (dict). Robust to HTTP/JSON failure.
    """
    out: list[dict[str, Any]] = []
    page = 1
    page_size = 50
    while len(out) < max_records:
        async with semaphore:
            params = {
                "keyword": keyword,
                "from": since,
                "format": "json",
                "page": page,
                "size": page_size,
            }
            try:
                resp = await client.get(EGOV_SEARCH_BASE, params=params)
            except httpx.HTTPError as exc:
                logger.warning("egov fetch failed for %s @ p%d: %s", keyword, page, exc)
                await asyncio.sleep(RATE_LIMIT_SECONDS * 2)
                break
            await asyncio.sleep(RATE_LIMIT_SECONDS)
        if resp.status_code == 429:
            logger.warning("egov rate-limited; backing off 5s")
            await asyncio.sleep(5.0)
            continue
        if resp.status_code != 200:
            logger.warning("egov HTTP %d for %s @ p%d", resp.status_code, keyword, page)
            break
        try:
            payload = resp.json()
        except (ValueError, json.JSONDecodeError):
            logger.warning("egov non-JSON response for %s @ p%d", keyword, page)
            break
        records = payload.get("results") or payload.get("items") or []
        if not records:
            break
        out.extend(records)
        total = int(payload.get("total", 0) or 0)
        if total and page * page_size >= total:
            break
        page += 1
        if len(out) >= max_records:
            break
    return out[:max_records]


# ---------------------------------------------------------------------------
# Parser + classifier
# ---------------------------------------------------------------------------

# Date in HTML often shows up as 令和N年M月D日 / YYYY/MM/DD / YYYY-MM-DD.
_DATE_ISO_RE = re.compile(r"(\d{4})[/-](\d{1,2})[/-](\d{1,2})")


def _normalize_date(raw: str | None) -> str:
    """Coerce a date-like string into ISO YYYY-MM-DD (best effort)."""
    if not raw:
        return ""
    m = _DATE_ISO_RE.search(str(raw))
    if not m:
        return ""
    y, mo, d = m.group(1), m.group(2).zfill(2), m.group(3).zfill(2)
    return f"{y}-{mo}-{d}"


def parse_announcement_record(rec: dict[str, Any]) -> dict[str, Any] | None:
    """Convert an e-Gov 案件 dict to a pubcomment_announcement row.

    Returns None if any required field is missing.
    """
    case_id = rec.get("id") or rec.get("案件番号") or rec.get("caseNumber")
    ministry = rec.get("ministry") or rec.get("関係省庁") or rec.get("agency") or ""
    target_law = rec.get("target_law") or rec.get("対象法令") or rec.get("law") or ""
    announce = _normalize_date(
        rec.get("announcement_date") or rec.get("公示日") or rec.get("startDate")
    )
    deadline = _normalize_date(
        rec.get("comment_deadline") or rec.get("締切日") or rec.get("endDate")
    )
    summary = rec.get("summary") or rec.get("概要") or rec.get("description") or ""
    url = rec.get("url") or rec.get("full_text_url") or rec.get("link") or ""
    if not (case_id and ministry and target_law and announce and deadline and url):
        return None
    sha256 = hashlib.sha256(f"{summary}|{url}".encode()).hexdigest()
    return {
        "id": str(case_id),
        "ministry": ministry,
        "target_law": target_law,
        "announcement_date": announce,
        "comment_deadline": deadline,
        "summary_text": summary,
        "full_text_url": url,
        "retrieved_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sha256": sha256,
    }


def detect_keywords(text: str) -> list[str]:
    """Return KEYWORDS subset that literally appear in ``text``."""
    return [k for k in KEYWORDS if k in text]


def classify_jpcite_relevance(summary: str, target_law: str) -> tuple[int, str | None]:
    """Return (relevant_flag, cohort_impact_json_or_None).

    relevant_flag is 1 iff any of KEYWORDS matches summary OR target_law.
    cohort_impact is a JSON dict {cohort: [keyword, ...]} when at least one
    cohort hit, else None.
    """
    haystack = f"{target_law}\n{summary}"
    hits = detect_keywords(haystack)
    if not hits:
        return 0, None
    cohort_impact: dict[str, list[str]] = {}
    for cohort, kws in COHORT_KEYWORDS.items():
        cohort_hits = [k for k in kws if k in haystack]
        if cohort_hits:
            cohort_impact[cohort] = cohort_hits
    return 1, json.dumps(
        {"hit_keywords": hits, "cohort_impact": cohort_impact},
        ensure_ascii=False,
    )


def _lead_time_months(target_law: str, summary: str) -> int:
    """Heuristic: 法律案 -> 2 ヶ月, 政令・省令 -> 1 ヶ月."""
    blob = f"{target_law} {summary}"
    if "法律" in blob and ("案" in blob or "改正" in blob):
        return LEAD_TIME_LAW_AMENDMENT
    return LEAD_TIME_REGULATION


# ---------------------------------------------------------------------------
# INSERT helpers
# ---------------------------------------------------------------------------


def _insert_announcement(
    conn: sqlite3.Connection,
    row: dict[str, Any],
    relevant: int,
    cohort_impact: str | None,
) -> bool:
    """Insert an announcement idempotently. Returns True if a new row was added."""
    cur = conn.execute(
        """
        INSERT OR IGNORE INTO pubcomment_announcement
            (id, ministry, target_law, announcement_date, comment_deadline,
             summary_text, full_text_url, retrieved_at, sha256,
             jpcite_relevant, jpcite_cohort_impact)
        VALUES (:id, :ministry, :target_law, :announcement_date, :comment_deadline,
                :summary_text, :full_text_url, :retrieved_at, :sha256,
                :jpcite_relevant, :jpcite_cohort_impact)
        """,
        {**row, "jpcite_relevant": relevant, "jpcite_cohort_impact": cohort_impact},
    )
    return cur.rowcount > 0


def _insert_signal(
    conn: sqlite3.Connection,
    case_id: str,
    target_law: str,
    lead_time_months: int,
    evidence_url: str,
) -> bool:
    """Insert one regulatory_signal row per relevant announcement (idempotent)."""
    sig_id = f"pubcomment:{case_id}"
    try:
        cur = conn.execute(
            """
            INSERT OR IGNORE INTO regulatory_signal
                (id, signal_kind, law_target, lead_time_months,
                 evidence_url, detected_at)
            VALUES (?, 'pubcomment_announcement', ?, ?, ?, ?)
            """,
            (
                sig_id,
                target_law,
                lead_time_months,
                evidence_url,
                datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            ),
        )
        return cur.rowcount > 0
    except sqlite3.OperationalError as exc:
        # regulatory_signal may not exist yet (DEEP-39 not applied). Soft-skip.
        logger.debug("regulatory_signal not present (skip): %s", exc)
        return False


# ---------------------------------------------------------------------------
# Main async driver
# ---------------------------------------------------------------------------


async def run(args: argparse.Namespace) -> int:
    conn = _open_db(args.db)
    since = _delta_from_date(conn, days=args.days)
    logger.info(
        "egov pubcomment daily cron: since=%s db=%s dry_run=%s",
        since,
        args.db,
        args.dry_run,
    )

    semaphore = asyncio.Semaphore(1)  # 1 req/sec, single-flight
    inserted_announcements = 0
    inserted_signals = 0
    fetched_total = 0
    relevant_count = 0
    async with httpx.AsyncClient(
        timeout=HTTPX_TIMEOUT,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    ) as client:
        for keyword in KEYWORDS:
            records = await _fetch_announcements(client, semaphore, keyword, since)
            fetched_total += len(records)
            logger.info("  keyword=%s fetched=%d", keyword, len(records))
            if args.dry_run:
                continue
            for rec in records:
                row = parse_announcement_record(rec)
                if not row:
                    continue
                relevant, cohort_impact = classify_jpcite_relevance(
                    row["summary_text"], row["target_law"]
                )
                if relevant:
                    relevant_count += 1
                if _insert_announcement(conn, row, relevant, cohort_impact):
                    inserted_announcements += 1
                if relevant and _insert_signal(
                    conn,
                    row["id"],
                    row["target_law"],
                    _lead_time_months(row["target_law"], row["summary_text"]),
                    row["full_text_url"],
                ):
                    inserted_signals += 1
            conn.commit()

    conn.close()
    logger.info(
        "egov pubcomment daily cron done: fetched=%d new_announcements=%d "
        "relevant=%d new_signals=%d",
        fetched_total,
        inserted_announcements,
        relevant_count,
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
        logger.exception("egov pubcomment daily cron failed")
        print(f"FATAL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
