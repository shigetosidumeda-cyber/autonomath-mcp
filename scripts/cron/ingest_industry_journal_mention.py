#!/usr/bin/env python3
"""DEEP-40 monthly industry journal mention ingest.

Spec: tools/offline/_inbox/value_growth_dual/_deep_plan/DEEP_40_industry_journal_mention.md

Tracks 自然言及 of jpcite / Bookyou / AutonoMath (legacy decay observation)
across 8 業界誌 covering 4 業法 sensitive cohorts (税理士 / 公認会計士 /
司法書士 / 行政書士). 3-layer fallback fetch strategy:

  1. CiNii Articles API (公開、 認証不要、 ci.nii.ac.jp/openurl) — primary.
  2. J-STAGE API (一部誌のみ — 月刊監査研究 等の学会誌) — secondary.
  3. publisher 公式 site の目次 (TOC) HTML scrape — tertiary.

LLM call: 0. Pure stdlib + ``requests`` + regex grep. Snippet capped
at 50 chars (著作権法 §32 適法引用 fence). Paid 購読 NG: 公開 TOC のみ.

GHA cron fires monthly on day 15 06:00 JST = 21:00 UTC day 14
(.github/workflows/industry-journal-mention-monthly.yml). Idempotent
via UNIQUE(journal_name, issue_date, article_title, mention_keyword) +
INSERT OR IGNORE — re-running yields 0 new rows.

Operator: Bookyou株式会社 (T8010001213708).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sqlite3
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

try:
    import requests
except ImportError as exc:  # pragma: no cover — guarded at module load
    print(f"missing dep: {exc}. pip install requests", file=sys.stderr)
    sys.exit(1)

logger = logging.getLogger("jpintel.cron.industry_journal_mention")

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_DEFAULT_DB = Path(os.environ.get("AUTONOMATH_DB_PATH", str(_REPO_ROOT / "autonomath.db")))
_USER_AGENT = "jpcite-industry-journal-mention/1.0 (+https://jpcite.com/transparency)"
_RATE_SLEEP_SEC = 1.0  # polite to CiNii / J-STAGE / publisher TOC
_HTTP_TIMEOUT_SEC = 30
_SNIPPET_MAX = 50  # 著作権法 §32 適法引用 fence

# 8 業界誌 × cohort × source_url base. Public-only TOC.
JOURNAL_REGISTRY: list[dict[str, Any]] = [
    {
        "name": "税務通信",
        "cohort": "税理士",
        "publisher_toc": "https://www.zeiken.co.jp/news/",
        "jstage_id": None,
    },
    {
        "name": "月刊税務事例",
        "cohort": "税理士",
        "publisher_toc": "https://www.zaikeishoho.co.jp/category/zeimu-jirei/",
        "jstage_id": None,
    },
    {
        "name": "TKC会報",
        "cohort": "税理士",
        "publisher_toc": "https://www.tkc.jp/tkcnf/kaiho/",
        "jstage_id": None,
    },
    {
        "name": "会計人コース",
        "cohort": "公認会計士",
        "publisher_toc": "https://www.biz-book.jp/cat-mag-kaikeijin/",
        "jstage_id": None,
    },
    {
        "name": "月刊監査研究",
        "cohort": "公認会計士",
        "publisher_toc": "https://www.jaa.or.jp/journal/",
        "jstage_id": "monkan",  # J-STAGE 収録. Placeholder — refine on first run.
    },
    {
        "name": "登記研究",
        "cohort": "司法書士",
        "publisher_toc": "https://www.teihan.co.jp/kanko_zasshi/touki_kenkyu/",
        "jstage_id": None,
    },
    {
        "name": "月報司法書士",
        "cohort": "司法書士",
        "publisher_toc": "https://www.shiho-shoshi.or.jp/association/publication/",
        "jstage_id": None,
    },
    {
        "name": "月刊行政書士",
        "cohort": "行政書士",
        "publisher_toc": "https://www.gyosei.or.jp/information/publication/",
        "jstage_id": None,
    },
]

# Keyword set (regex; case + 半全角 normalization handled in _normalize).
KEYWORDS: list[str] = [
    "jpcite",
    "ジェイピーサイト",
    "Bookyou",
    "AutonoMath",
    "オートノマス",
    "T8010001213708",
]

# Self-author markers — author name 部分文字列 hit.
SELF_AUTHOR_MARKERS: tuple[str, ...] = ("梅田茂利", "Bookyou", "Umeda Shigetoshi")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _normalize(text: str) -> str:
    """Casefold + strip whitespace so half-width / full-width / case match.

    Whitespace is stripped because Japanese author rolls render the same
    name as both ``梅田茂利`` and ``梅田 茂利`` — the brand grep should
    treat them identically. Pure ASCII case-fold; no LLM, no NFKC import.
    """
    if not text:
        return ""
    # Drop ASCII spaces, tabs, newlines, and Japanese ideographic space.
    stripped = re.sub(r"[\s　]+", "", text)
    return stripped.lower()


def _grep_keywords(text: str) -> list[tuple[str, str]]:
    """Return list of (matched_keyword, snippet) tuples for any KEYWORDS hits.

    Snippet capped at _SNIPPET_MAX chars centered on the match (著作権 fence).
    Pure regex — NO LLM.
    """
    if not text:
        return []
    norm = _normalize(text)
    hits: list[tuple[str, str]] = []
    for kw in KEYWORDS:
        kw_norm = _normalize(kw)
        idx = norm.find(kw_norm)
        if idx == -1:
            continue
        # Center snippet on match; clip to _SNIPPET_MAX.
        half = max(1, (_SNIPPET_MAX - len(kw)) // 2)
        start = max(0, idx - half)
        end = min(len(text), idx + len(kw) + half)
        snippet = text[start:end].strip()
        if len(snippet) > _SNIPPET_MAX:
            snippet = snippet[:_SNIPPET_MAX]
        hits.append((kw, snippet))
    return hits


def _is_self_authored(authors: str | None) -> int:
    if not authors:
        return 0
    norm = _normalize(authors)
    for marker in SELF_AUTHOR_MARKERS:
        if _normalize(marker) in norm:
            return 1
    return 0


def _previous_yyyy_mm(today: datetime, months_back: int) -> str:
    """Return ISO YYYY-MM N months before ``today``."""
    y = today.year
    m = today.month - months_back
    while m <= 0:
        m += 12
        y -= 1
    return f"{y:04d}-{m:02d}"


def _safe_get(url: str, *, params: dict[str, Any] | None = None) -> str | None:
    """HTTP GET with polite timeout + user-agent. Returns text or None on error."""
    try:
        resp = requests.get(
            url,
            params=params,
            headers={"User-Agent": _USER_AGENT, "Accept-Language": "ja,en;q=0.5"},
            timeout=_HTTP_TIMEOUT_SEC,
        )
        if resp.status_code != 200:
            logger.warning("http_non_200 url=%s status=%d", url, resp.status_code)
            return None
        return resp.text
    except Exception as exc:  # noqa: BLE001 — never raise from a cron
        logger.warning("http_error url=%s err=%s", url, exc)
        return None


# ---------------------------------------------------------------------------
# Source layer 1: CiNii Articles API
# ---------------------------------------------------------------------------


def fetch_cinii(keyword: str, *, year_from: int, year_to: int) -> list[dict[str, Any]]:
    """Query CiNii Articles API for ``keyword`` in given year range.

    Returns list of {journal_name, issue_date, article_title, article_authors,
    source_url} dicts. CiNii's openurl endpoint returns RIS-ish text;
    we use a minimal regex parser since lxml is not guaranteed in the
    cron runner image.
    """
    url = "https://cir.nii.ac.jp/opensearch/all"
    params = {
        "q": keyword,
        "format": "json",
        "from": year_from,
        "to": year_to,
        "count": 100,
    }
    text = _safe_get(url, params=params)
    out: list[dict[str, Any]] = []
    if not text:
        return out
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return out
    items = data.get("@graph") or []
    if not isinstance(items, list):
        return out
    # CiNii's @graph is wrapped — first element holds the items list.
    for graph in items:
        if not isinstance(graph, dict):
            continue
        records = graph.get("items") or []
        if not isinstance(records, list):
            continue
        for rec in records:
            if not isinstance(rec, dict):
                continue
            title = (rec.get("title") or "").strip()
            if not title:
                continue
            journal = ""
            if isinstance(rec.get("dc:publisher"), list):
                journal = (rec["dc:publisher"][0] or "").strip() if rec["dc:publisher"] else ""
            elif isinstance(rec.get("prism:publicationName"), str):
                journal = rec["prism:publicationName"].strip()
            issued = (rec.get("prism:publicationDate") or rec.get("dc:date") or "").strip()
            issue_date = issued[:7] if len(issued) >= 7 else issued  # YYYY-MM
            authors = ""
            if isinstance(rec.get("dc:creator"), list):
                authors = "; ".join(str(a) for a in rec["dc:creator"] if a)
            elif isinstance(rec.get("dc:creator"), str):
                authors = rec["dc:creator"]
            link = (rec.get("@id") or rec.get("link") or "").strip()
            out.append(
                {
                    "journal_name": journal,
                    "issue_date": issue_date,
                    "article_title": title,
                    "article_authors": authors,
                    "source_url": link or url,
                }
            )
    return out


# ---------------------------------------------------------------------------
# Source layer 2: J-STAGE API
# ---------------------------------------------------------------------------


def fetch_jstage(jstage_id: str, keyword: str) -> list[dict[str, Any]]:
    """Query J-STAGE WebAPI for ``keyword`` in the given journal id.

    J-STAGE ``ws/articleList`` returns JSON. We search title/abstract for
    the keyword post-fetch (the API has limited query operators).
    """
    if not jstage_id:
        return []
    url = "https://api.jstage.jst.go.jp/searchapi/do"
    params = {
        "service": "3",
        "cdjournal": jstage_id,
        "text1": keyword,
    }
    text = _safe_get(url, params=params)
    out: list[dict[str, Any]] = []
    if not text:
        return out
    # API returns Atom XML. Minimal regex extraction (no lxml dependency).
    entries = re.findall(r"<entry>(.*?)</entry>", text, re.DOTALL)
    for entry in entries:
        title_match = re.search(r"<title[^>]*>(.*?)</title>", entry, re.DOTALL)
        title = (title_match.group(1) if title_match else "").strip()
        if not title:
            continue
        link_match = re.search(r'<link[^>]*href="([^"]+)"', entry)
        link = link_match.group(1) if link_match else ""
        authors_matches = re.findall(r"<name>(.*?)</name>", entry, re.DOTALL)
        authors = "; ".join(a.strip() for a in authors_matches if a.strip())
        date_match = re.search(r"<published>(\d{4}-\d{2})", entry)
        issue_date = date_match.group(1) if date_match else ""
        out.append(
            {
                "journal_name": "",  # filled by caller
                "issue_date": issue_date,
                "article_title": title,
                "article_authors": authors,
                "source_url": link or url,
            }
        )
    return out


# ---------------------------------------------------------------------------
# Source layer 3: Publisher TOC HTML
# ---------------------------------------------------------------------------


def fetch_publisher_toc(toc_url: str) -> list[dict[str, Any]]:
    """Fetch publisher TOC page and extract candidate article entries.

    Heuristic regex extraction over <a> + nearby text. lxml NOT required.
    Each return dict carries title + url + raw snippet for keyword grep.
    """
    text = _safe_get(toc_url)
    out: list[dict[str, Any]] = []
    if not text:
        return out
    # Extract <a href="..."> Title </a> pairs.
    for match in re.finditer(
        r'<a[^>]+href="([^"#]+)"[^>]*>\s*([^<]{2,200})\s*</a>',
        text,
        re.DOTALL,
    ):
        href = match.group(1).strip()
        title = re.sub(r"\s+", " ", match.group(2)).strip()
        if not title:
            continue
        # Skip nav / footer noise — require kanji or "号" / "巻" presence as a TOC heuristic.
        if not re.search(r"[一-龥]|号|巻|月号", title):
            continue
        out.append(
            {
                "journal_name": "",  # filled by caller
                "issue_date": "",  # filled by caller fallback
                "article_title": title,
                "article_authors": "",
                "source_url": href if href.startswith("http") else toc_url,
            }
        )
    return out


# ---------------------------------------------------------------------------
# DB upsert
# ---------------------------------------------------------------------------


def upsert_mention(
    conn: sqlite3.Connection,
    *,
    journal_name: str,
    cohort: str,
    issue_date: str,
    article_title: str,
    article_authors: str,
    mention_keyword: str,
    mention_context_snippet: str,
    is_self_authored: int,
    source_url: str,
    source_layer: str,
    retrieved_at: str,
) -> int:
    """INSERT OR IGNORE into industry_journal_mention. Returns 1 if new row."""
    cur = conn.execute(
        """
        INSERT OR IGNORE INTO industry_journal_mention(
            journal_name, cohort, issue_date, article_title, article_authors,
            mention_keyword, mention_context_snippet, is_self_authored,
            source_url, source_layer, retrieved_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            journal_name,
            cohort,
            issue_date,
            article_title,
            article_authors,
            mention_keyword,
            mention_context_snippet,
            int(is_self_authored),
            source_url,
            source_layer,
            retrieved_at,
        ),
    )
    return int(cur.rowcount or 0)


# ---------------------------------------------------------------------------
# Main run loop
# ---------------------------------------------------------------------------


def run(
    db_path: Path,
    *,
    months_back: int = 13,
    sleep_sec: float = _RATE_SLEEP_SEC,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Top-level orchestration. Returns summary counters."""
    counters: dict[str, Any] = {
        "scanned_journals": 0,
        "articles_examined": 0,
        "mentions_inserted": 0,
        "mentions_skipped_dup": 0,
        "errors": 0,
        "by_layer": {"cinii": 0, "jstage": 0, "publisher_html": 0},
        "self_vs_other": {"self": 0, "other": 0},
    }
    if not db_path.is_file():
        logger.error("db_missing path=%s", db_path)
        counters["errors"] = 1
        return counters

    now = datetime.now(UTC)
    retrieved_at = now.isoformat()
    year_to = now.year
    year_from = (now - timedelta(days=months_back * 31)).year

    conn = sqlite3.connect(db_path, timeout=300)
    conn.execute("PRAGMA busy_timeout = 300000")
    try:
        # --- Layer 1: CiNii (single query per keyword across all journals) ---
        cinii_records: list[dict[str, Any]] = []
        for kw in KEYWORDS:
            recs = fetch_cinii(kw, year_from=year_from, year_to=year_to)
            cinii_records.extend(recs)
            time.sleep(sleep_sec)
        logger.info("cinii_fetched n=%d", len(cinii_records))

        for rec in cinii_records:
            counters["articles_examined"] += 1
            blob = " ".join(
                [
                    rec.get("article_title", ""),
                    rec.get("article_authors", ""),
                    rec.get("journal_name", ""),
                ]
            )
            hits = _grep_keywords(blob)
            if not hits:
                continue
            # Match journal_name to registry — fuzzy substring match.
            matched_journal: dict[str, Any] | None = None
            for j in JOURNAL_REGISTRY:
                if j["name"] in (rec.get("journal_name") or ""):
                    matched_journal = j
                    break
            if matched_journal is None:
                continue  # not one of our 8 業界誌
            self_flag = _is_self_authored(rec.get("article_authors"))
            for kw, snippet in hits:
                if not dry_run:
                    n = upsert_mention(
                        conn,
                        journal_name=matched_journal["name"],
                        cohort=matched_journal["cohort"],
                        issue_date=rec.get("issue_date") or "",
                        article_title=rec.get("article_title", ""),
                        article_authors=rec.get("article_authors", "") or "",
                        mention_keyword=kw,
                        mention_context_snippet=snippet,
                        is_self_authored=self_flag,
                        source_url=rec.get("source_url") or "",
                        source_layer="cinii",
                        retrieved_at=retrieved_at,
                    )
                else:
                    n = 1
                if n:
                    counters["mentions_inserted"] += 1
                    counters["by_layer"]["cinii"] += 1
                    counters["self_vs_other"]["self" if self_flag else "other"] += 1
                else:
                    counters["mentions_skipped_dup"] += 1

        # --- Layer 2 + 3: per-journal J-STAGE + publisher TOC ---
        for j in JOURNAL_REGISTRY:
            counters["scanned_journals"] += 1
            jname = j["name"]
            cohort = j["cohort"]
            # Layer 2: J-STAGE (only for journals carrying jstage_id).
            if j.get("jstage_id"):
                for kw in KEYWORDS:
                    js_records = fetch_jstage(j["jstage_id"], kw)
                    time.sleep(sleep_sec)
                    for rec in js_records:
                        counters["articles_examined"] += 1
                        blob = " ".join(
                            [rec.get("article_title", ""), rec.get("article_authors", "")]
                        )
                        hits = _grep_keywords(blob)
                        if not hits:
                            continue
                        self_flag = _is_self_authored(rec.get("article_authors"))
                        for hit_kw, snippet in hits:
                            if not dry_run:
                                n = upsert_mention(
                                    conn,
                                    journal_name=jname,
                                    cohort=cohort,
                                    issue_date=rec.get("issue_date") or "",
                                    article_title=rec.get("article_title", ""),
                                    article_authors=rec.get("article_authors", "") or "",
                                    mention_keyword=hit_kw,
                                    mention_context_snippet=snippet,
                                    is_self_authored=self_flag,
                                    source_url=rec.get("source_url") or "",
                                    source_layer="jstage",
                                    retrieved_at=retrieved_at,
                                )
                            else:
                                n = 1
                            if n:
                                counters["mentions_inserted"] += 1
                                counters["by_layer"]["jstage"] += 1
                                counters["self_vs_other"]["self" if self_flag else "other"] += 1
                            else:
                                counters["mentions_skipped_dup"] += 1
            # Layer 3: publisher TOC HTML grep.
            toc_url = j.get("publisher_toc")
            if toc_url:
                time.sleep(sleep_sec)
                toc_records = fetch_publisher_toc(toc_url)
                for rec in toc_records:
                    counters["articles_examined"] += 1
                    hits = _grep_keywords(rec.get("article_title", ""))
                    if not hits:
                        continue
                    self_flag = 0  # TOC text 単体では author 名 are not 直接出ないので保守側 0
                    for hit_kw, snippet in hits:
                        if not dry_run:
                            n = upsert_mention(
                                conn,
                                journal_name=jname,
                                cohort=cohort,
                                issue_date=_previous_yyyy_mm(now, 0),
                                article_title=rec.get("article_title", ""),
                                article_authors="",
                                mention_keyword=hit_kw,
                                mention_context_snippet=snippet,
                                is_self_authored=self_flag,
                                source_url=rec.get("source_url") or toc_url,
                                source_layer="publisher_html",
                                retrieved_at=retrieved_at,
                            )
                        else:
                            n = 1
                        if n:
                            counters["mentions_inserted"] += 1
                            counters["by_layer"]["publisher_html"] += 1
                            counters["self_vs_other"]["other"] += 1
                        else:
                            counters["mentions_skipped_dup"] += 1
        if not dry_run:
            conn.commit()
    except Exception as exc:  # noqa: BLE001 — never raise from a cron
        logger.exception("ingest_industry_journal_mention top-level error: %s", exc)
        counters["errors"] += 1
    finally:
        conn.close()

    return counters


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="DEEP-40 monthly industry journal mention ingest (LLM 0).",
    )
    p.add_argument(
        "--db", type=Path, default=_DEFAULT_DB, help=f"SQLite path (default: {_DEFAULT_DB})"
    )
    p.add_argument(
        "--month",
        type=str,
        default="",
        help="Target YYYY-MM (informational; spec retains 13mo lookback).",
    )
    p.add_argument(
        "--months-back", type=int, default=13, help="Lookback window in months (default 13)."
    )
    p.add_argument(
        "--sleep",
        type=float,
        default=_RATE_SLEEP_SEC,
        help=f"Per-request sleep sec (default {_RATE_SLEEP_SEC}).",
    )
    p.add_argument("--dry-run", action="store_true", help="Fetch + grep, do not write to DB.")
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        stream=sys.stderr,
    )

    # Heartbeat is best-effort — module import may fail in lean test envs.
    try:
        from jpintel_mcp.observability.cron_heartbeat import heartbeat  # type: ignore

        with heartbeat("ingest_industry_journal_mention") as hb:
            counters = run(
                db_path=args.db,
                months_back=args.months_back,
                sleep_sec=args.sleep,
                dry_run=args.dry_run,
            )
            hb["rows_processed"] = int(counters.get("mentions_inserted", 0) or 0)
            hb["rows_skipped"] = int(counters.get("mentions_skipped_dup", 0) or 0)
            hb["metadata"] = {
                "scanned_journals": counters.get("scanned_journals"),
                "articles_examined": counters.get("articles_examined"),
                "by_layer": counters.get("by_layer"),
                "self_vs_other": counters.get("self_vs_other"),
                "errors": counters.get("errors"),
                "dry_run": bool(args.dry_run),
            }
    except ImportError:
        counters = run(
            db_path=args.db,
            months_back=args.months_back,
            sleep_sec=args.sleep,
            dry_run=args.dry_run,
        )

    print(json.dumps(counters, indent=2, ensure_ascii=False))
    logger.info(
        "industry_journal_mention.done inserted=%d dup_skipped=%d examined=%d errors=%d",
        counters["mentions_inserted"],
        counters["mentions_skipped_dup"],
        counters["articles_examined"],
        counters["errors"],
    )
    return 1 if counters["errors"] > 0 else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = [
    "JOURNAL_REGISTRY",
    "KEYWORDS",
    "SELF_AUTHOR_MARKERS",
    "_grep_keywords",
    "_is_self_authored",
    "_previous_yyyy_mm",
    "fetch_cinii",
    "fetch_jstage",
    "fetch_publisher_toc",
    "main",
    "run",
    "upsert_mention",
]
