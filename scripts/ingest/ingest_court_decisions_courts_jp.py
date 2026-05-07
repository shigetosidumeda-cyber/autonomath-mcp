#!/usr/bin/env python3
"""Bootstrap ``court_decisions`` from courts.go.jp 裁判例検索 (no PDF body fetch).

Why a second ingester (alongside ingest_court_decisions.py)?
  ingest_court_decisions.py drives the SPA via Playwright + pdfplumber so it
  can pull 判示事項 / 裁判要旨 / 参照条文 out of PDFs. Those deps are NOT
  installed (playwright/pdfplumber missing per pyproject.toml [ingest] gap),
  and the launch deadline is 2026-05-06.

  This script takes the requests + BeautifulSoup path: courts.go.jp's
  search2/search4 result list pages render server-side HTML (no JS), and
  each detail page (`/hanrei/{ID}/detail2/index.html`) is plain HTML with
  judgement metadata in a clean ``<dl>`` block. We capture metadata + the
  PDF URL but never fetch the PDF body — keeping bandwidth low and dodging
  the (ambiguous) commercial-redistribution gate on PDF content.

Source discipline (CLAUDE.md / migration 016):
  * Only ``www.courts.go.jp`` is whitelisted.
  * Aggregators (D1 Law / Westlaw JP / LEX-DB / TKC LEX) are banned.
  * UA: per-task spec ``AutonoMath/0.1.0 (+https://bookyou.net)``.
  * Rate: 1 req/sec (task spec) — implemented as a sleep(1.0) between
    every outbound HTTP call.
  * robots.txt: courts.go.jp disallows only ``/<court>/saiban/kozisotatu``
    paths (公示送達). ``/hanrei/`` and ``/assets/hanrei/`` are allowed
    (verified 2026-04-25).

Search strategy — 法条 (reference law) seeding:
  We do NOT use free-text query1 (search1 statistics page never renders
  results in HTML; it is XHR-fed). Instead we hit search2 (最高裁) +
  search4 (下級裁) with ``filter[reference]=<法令名>`` for each law in
  ``REFERENCE_LAWS``. Each yields server-side rendered result rows
  matching that 参照法条.

  Coverage focus = 税務 + 行政処分 + 補助金 関連:
    所得税法, 法人税法, 国税通則法, 消費税法, 租税特別措置法,
    相続税法, 地方税法, 国家賠償法, 行政事件訴訟法, 行政手続法,
    行政不服審査法, 補助金等に係る予算の執行の適正化に関する法律,
    独占禁止法, 地方自治法 (some hand-tuned for hit count).

Pagination:
  Result table caps at 30 rows/page, ``offset`` is in increments of 30.
  We walk until either (a) the result count for that law is exhausted,
  or (b) a per-law cap (``MAX_PER_LAW``) is hit. Total walk capped at
  ``MAX_TOTAL_DETAILS`` to keep run time bounded.

Detail extraction:
  Result rows already carry: case_number, case_name, decision_date,
  court, decision_type, judge_result, original_court info, pdf_url.
  We hit each detail page once to also collect: 法廷名, 判示事項,
  裁判要旨, 参照法条, 判例集等巻号頁. ``key_ruling`` = 判示事項;
  ``impact_on_business`` = 裁判要旨; ``subject_area`` = inferred
  from 参照法条 root (税務 / 行政 / 民事 etc.).

DB writes:
  * BEGIN IMMEDIATE + busy_timeout=300000 (parallel-safe per spec).
  * UPSERT on unified_id; UNIQUE(case_number, court) is honored by
    schema, but we compute unified_id deterministically from
    sha256(case_number|court) so re-runs are idempotent.
  * Mirror to ``court_decisions_fts`` (DELETE + INSERT — same pattern
    as the Playwright variant).

Exit codes:
  0  success (rows inserted ≥ MIN_ROWS_FOR_OK)
  1  network error or no data after retries
  2  DB schema missing (court_decisions table absent)
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as _dt
import hashlib
import logging
import re
import sqlite3
import sys
import time
import unicodedata
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import httpx
from bs4 import BeautifulSoup  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from collections.abc import Iterator

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_LOG = logging.getLogger("autonomath.ingest.court_decisions_courts_jp")

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_DB = REPO_ROOT / "data" / "jpintel.db"

USER_AGENT = "AutonoMath/0.1.0 (+https://bookyou.net)"
PER_REQUEST_DELAY_SEC = 1.0  # 1 req/sec/host per task spec
HTTP_TIMEOUT_SEC = 30.0
MAX_RETRIES = 3

ALLOWED_HOST = "www.courts.go.jp"
SEARCH2_URL = "https://www.courts.go.jp/hanrei/search2/index.html"
SEARCH4_URL = "https://www.courts.go.jp/hanrei/search4/index.html"
DETAIL_URL_TMPL = "https://www.courts.go.jp/hanrei/{hid}/detail{n}/index.html"
PDF_URL_TMPL = "https://www.courts.go.jp/assets/hanrei/hanrei-pdf-{hid}.pdf"

# Banned commercial aggregators — kept in sync with ingest_court_decisions.py.
BANNED_SOURCE_HOSTS: tuple[str, ...] = (
    "d1law",
    "westlaw",
    "lexis",
    "lex-db",
    "lexdb",
    "tkclex",
    "noukaweb",
    "hojyokin-portal",
    "biz.stayway",
    "hojo-navi",
    "mirai-joho",
)

# Reference-law seeds. (法令名, search-endpoint-key, subject_area_hint)
# search-endpoint-key picks search2 (最高裁) vs search4 (下級裁); both
# accept the same filter and tend to return overlapping sets, but search4
# also surfaces 高裁/地裁 cases for the same 参照法条.
REFERENCE_LAWS: tuple[tuple[str, str, str], ...] = (
    ("所得税法", "search2", "租税"),
    ("法人税法", "search2", "租税"),
    ("国税通則法", "search2", "租税"),
    ("消費税法", "search2", "租税"),
    ("租税特別措置法", "search2", "租税"),
    ("相続税法", "search2", "租税"),
    ("地方税法", "search2", "租税"),
    ("行政事件訴訟法", "search2", "行政"),
    ("行政手続法", "search2", "行政"),
    ("行政不服審査法", "search2", "行政"),
    ("国家賠償法", "search2", "行政"),
    ("補助金等に係る予算の執行の適正化に関する法律", "search2", "補助金適正化"),
    ("独占禁止法", "search2", "独禁"),
    ("地方自治法", "search2", "行政"),
    # 下級裁 supplement (search4) — same filter often surfaces additional
    # 高裁/地裁 rows in the result set.
    ("所得税法", "search4", "租税"),
    ("法人税法", "search4", "租税"),
    ("行政事件訴訟法", "search4", "行政"),
    ("国家賠償法", "search4", "行政"),
)

PAGE_SIZE = 30
MAX_PER_LAW = 240  # 8 pages
MAX_TOTAL_DETAILS = 600  # absolute cap across all laws
MIN_ROWS_FOR_OK = 200

# Court-level rules (substring -> level).
COURT_LEVEL_RULES: tuple[tuple[str, str], ...] = (
    ("最高裁判所", "supreme"),
    ("高等裁判所", "high"),
    ("地方裁判所", "district"),
    ("簡易裁判所", "summary"),
    ("家庭裁判所", "family"),
)

DECISION_TYPE_KANJI: frozenset[str] = frozenset({"判決", "決定", "命令"})

# Wareki -> Gregorian (years 1926..2026). Built once at import time.
_GENGO: tuple[tuple[str, int], ...] = (
    ("令和", 2018),  # 令和元年 = 2019 -> +1 below
    ("平成", 1988),  # 平成元年 = 1989
    ("昭和", 1925),  # 昭和元年 = 1926
    ("大正", 1911),
    ("明治", 1867),
)

_KANJI_DIGIT = {
    "〇": 0,
    "零": 0,
    "一": 1,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
    "元": 1,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def normalize(text: str | None) -> str:
    if not text:
        return ""
    return unicodedata.normalize("NFKC", text).strip()


def kanji_num_to_int(s: str) -> int | None:
    """Tiny wareki-grade kanji digit parser. Handles 元/一-九/十/二十一 etc."""
    if not s:
        return None
    s = s.strip()
    if s.isdigit():
        return int(s)
    # Mix of digits and kanji shouldn't happen post-NFKC.
    if "十" in s:
        # Patterns: 十, 二十, 十五, 二十一
        if s == "十":
            return 10
        if s.startswith("十"):
            tail = s[1:]
            return 10 + (_KANJI_DIGIT.get(tail, 0) if tail else 0)
        # else: tens "Ｎ十Ｍ"
        try:
            tens, _, ones = s.partition("十")
            return _KANJI_DIGIT[tens] * 10 + (_KANJI_DIGIT.get(ones, 0) if ones else 0)
        except KeyError:
            return None
    n = 0
    for ch in s:
        if ch not in _KANJI_DIGIT:
            return None
        n = n * 10 + _KANJI_DIGIT[ch]
    return n


_DATE_RE = re.compile(
    r"^(令和|平成|昭和|大正|明治)\s*([元〇零一二三四五六七八九十0-9]+)\s*年\s*"
    r"([〇零一二三四五六七八九十0-9]+)\s*月\s*([〇零一二三四五六七八九十0-9]+)\s*日"
)


def parse_wareki_date(text: str) -> str | None:
    """Convert '令和2年3月24日' -> '2020-03-24'. Returns None on parse miss."""
    if not text:
        return None
    m = _DATE_RE.match(text.strip())
    if not m:
        return None
    era, y, mo, d = m.group(1), m.group(2), m.group(3), m.group(4)
    yi = kanji_num_to_int(y)
    moi = kanji_num_to_int(mo)
    di = kanji_num_to_int(d)
    if yi is None or moi is None or di is None:
        return None
    base = dict(_GENGO).get(era)
    if base is None:
        return None
    # 令和元年 = 2019 (base=2018, +1). Same convention for 平成元 etc.
    # Both branches identical today; preserved for future era-specific overrides.
    gy = base + yi if era in ("令和", "平成", "昭和", "大正", "明治") else base + yi
    try:
        return f"{gy:04d}-{moi:02d}-{di:02d}"
    except Exception:
        return None


def map_court_level(court: str) -> str | None:
    if not court:
        return None
    for needle, level in COURT_LEVEL_RULES:
        if needle in court:
            return level
    return None


def map_decision_type(text: str) -> str | None:
    for kind in ("判決", "決定", "命令"):  # check order: 判決 first
        if kind in text:
            return kind
    return None


def map_precedent_weight(level: str) -> str:
    if level == "supreme":
        return "binding"
    if level == "high":
        return "persuasive"
    return "informational"


def compute_unified_id(case_number: str, court: str) -> str:
    key = f"{case_number}|{court}".encode()
    return "HAN-" + hashlib.sha256(key).hexdigest()[:10]


def url_is_safe(url: str) -> bool:
    if not url:
        return False
    parsed = urllib.parse.urlparse(url)
    if parsed.netloc.lower() != ALLOWED_HOST:
        return False
    low = url.lower()
    return not any(b in low for b in BANNED_SOURCE_HOSTS)


# ---------------------------------------------------------------------------
# HTTP layer (custom UA + 1 req/sec)
# ---------------------------------------------------------------------------


class CourtsClient:
    def __init__(self, *, timeout: float = HTTP_TIMEOUT_SEC) -> None:
        self._client = httpx.Client(
            timeout=timeout,
            headers={"User-Agent": USER_AGENT, "Accept-Language": "ja,en;q=0.5"},
            follow_redirects=True,
        )
        self._last_call: float = 0.0

    def _pace(self) -> None:
        delta = time.monotonic() - self._last_call
        if delta < PER_REQUEST_DELAY_SEC:
            time.sleep(PER_REQUEST_DELAY_SEC - delta)
        self._last_call = time.monotonic()

    def get(self, url: str) -> str:
        if not url_is_safe(url):
            raise ValueError(f"refused unsafe URL: {url}")
        last_exc: Exception | None = None
        for attempt in range(1, MAX_RETRIES + 1):
            self._pace()
            try:
                r = self._client.get(url)
                r.raise_for_status()
                return r.text
            except (httpx.HTTPError, httpx.TransportError) as exc:
                last_exc = exc
                if attempt < MAX_RETRIES:
                    sleep_for = 2**attempt
                    _LOG.warning(
                        "GET %s failed (%s); retry %d/%d after %ds",
                        url,
                        exc,
                        attempt,
                        MAX_RETRIES,
                        sleep_for,
                    )
                    time.sleep(sleep_for)
        assert last_exc is not None
        raise last_exc

    def close(self) -> None:
        self._client.close()


# ---------------------------------------------------------------------------
# Listing parser
# ---------------------------------------------------------------------------


@dataclass
class ListingRow:
    """One row out of search2/search4 result table."""

    hid: str  # courts.go.jp internal id (path segment)
    detail_n: int  # detail2/detail4/detail7/detail8 variant
    detail_url: str
    pdf_url: str | None
    case_number: str
    case_name: str
    decision_date_raw: str
    court: str
    decision_type_raw: str
    result: str | None
    original_court: str | None
    original_case_number: str | None
    list_label: str  # 最高裁判例 / 高裁判例 / etc.
    seed_subject_area: str
    seed_law: str


_DETAIL_LINK_RE = re.compile(r"\.\./(\d+)/detail(\d+)/")


def parse_listing_page(html: str, *, seed_law: str, seed_subject: str) -> list[ListingRow]:
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", class_="search-result-table")
    if not table:
        return []
    rows: list[ListingRow] = []
    for tr in table.find_all("tr"):
        # First <th> holds the type-label + detail link.
        th = tr.find("th")
        if not th:
            continue
        anchor = th.find("a", href=True)
        if not anchor:
            continue
        href = anchor["href"]
        m = _DETAIL_LINK_RE.search(href)
        if not m:
            continue
        hid, detail_n_str = m.group(1), m.group(2)
        try:
            detail_n = int(detail_n_str)
        except ValueError:
            continue
        list_label = normalize(anchor.get_text())

        # Body td has 3-4 <p> blocks: case_number+case_name, date+court+type+result+orig.
        tds = tr.find_all("td")
        if not tds:
            continue
        body_td = tds[0]
        ps = body_td.find_all("p")
        if not ps:
            continue
        line1 = normalize(ps[0].get_text(" ", strip=True))
        # line1 example: "平成30(行ヒ)422 所得税更正処分取消等請求事件"
        # Split on first whitespace after the case_number.
        case_number = ""
        case_name = ""
        # Case number pattern: <era><year>(<code>)<num>, e.g. 平成30(行ヒ)422
        cn_m = re.match(r"^([^\s]+\([^)]+\)\d+(?:号)?(?:等)?)\s*(.*)$", line1)
        if cn_m:
            case_number = cn_m.group(1)
            case_name = cn_m.group(2).strip()
        else:
            case_name = line1

        line2 = normalize(ps[1].get_text(" ", strip=True)) if len(ps) > 1 else ""
        # line2 example: "令和2年3月24日 最高裁判所第三小法廷 判決 破棄差戻 東京高等裁判所  平成29(行コ)283"
        decision_date_raw = ""
        court = ""
        decision_type_raw = ""
        result = None
        original_court = None
        original_case_number = None
        date_m = re.search(
            r"(令和|平成|昭和|大正|明治)\s*[元〇零一二三四五六七八九十0-9]+\s*年\s*"
            r"[〇零一二三四五六七八九十0-9]+\s*月\s*[〇零一二三四五六七八九十0-9]+\s*日",
            line2,
        )
        if date_m:
            decision_date_raw = date_m.group(0)
            tail = line2[date_m.end() :].strip()
            # Tokenise the rest with whitespace; first chunk = court (may include 部/小法廷).
            parts = re.split(r"\s+", tail)
            # court is a single token ending in 法廷|裁判所|支部.
            if parts:
                court = parts[0]
                idx = 1
                # Some lines have e.g. "最高裁判所第三小法廷" already merged.
                # Walk forward; decision type is in {判決,決定,命令}.
                while idx < len(parts):
                    tok = parts[idx]
                    if tok in DECISION_TYPE_KANJI:
                        decision_type_raw = tok
                        idx += 1
                        break
                    # Append to court if it looks like part of court name.
                    if tok in ("第一小法廷", "第二小法廷", "第三小法廷", "大法廷"):
                        court = court + tok
                        idx += 1
                        continue
                    idx += 1
                if idx < len(parts):
                    result = parts[idx]
                    idx += 1
                # Remaining tokens: original_court + original_case_number.
                rest = [t for t in parts[idx:] if t]
                if rest:
                    # Find first token that looks like 事件番号
                    orig_cn_idx = None
                    for j, t in enumerate(rest):
                        if re.match(r"^[^\s]+\([^)]+\)\d+", t):
                            orig_cn_idx = j
                            break
                    if orig_cn_idx is not None:
                        original_court = " ".join(rest[:orig_cn_idx]).strip() or None
                        original_case_number = rest[orig_cn_idx]
                    else:
                        original_court = " ".join(rest).strip() or None

        detail_url = f"https://www.courts.go.jp/hanrei/{hid}/detail{detail_n}/index.html"
        # PDF link in same row (file-col).
        pdf_url: str | None = None
        for td in tds:
            a = td.find("a", href=True)
            if a and a["href"].endswith(".pdf"):
                href_pdf = a["href"]
                if href_pdf.startswith("./") or href_pdf.startswith("../"):
                    href_pdf = urllib.parse.urljoin(
                        "https://www.courts.go.jp/hanrei/dummy/",
                        href_pdf,
                    )
                if url_is_safe(href_pdf):
                    pdf_url = href_pdf
                break

        if not case_number or not court:
            # Skip degenerate rows; we need both for unified_id + UNIQUE.
            continue
        rows.append(
            ListingRow(
                hid=hid,
                detail_n=detail_n,
                detail_url=detail_url,
                pdf_url=pdf_url,
                case_number=case_number,
                case_name=case_name,
                decision_date_raw=decision_date_raw,
                court=court,
                decision_type_raw=decision_type_raw,
                result=result,
                original_court=original_court,
                original_case_number=original_case_number,
                list_label=list_label,
                seed_subject_area=seed_subject,
                seed_law=seed_law,
            )
        )
    return rows


def parse_listing_total(html: str) -> int | None:
    """Extract '<N>件中' from a result page header. None if not found."""
    m = re.search(r"(\d[\d,]*)\s*件中", html)
    if not m:
        return None
    return int(m.group(1).replace(",", ""))


# ---------------------------------------------------------------------------
# Detail parser
# ---------------------------------------------------------------------------


@dataclass
class DetailFields:
    courtroom: str | None = None  # 法廷名 (上書き court)
    key_ruling: str | None = None  # 判示事項
    summary: str | None = None  # 裁判要旨
    references: str | None = None  # 参照法条
    reporter_citation: str | None = None  # 判例集等巻・号・頁
    parties: str | None = None  # 当事者 (rare in courts.go.jp HTML)


def parse_detail_page(html: str) -> DetailFields:
    soup = BeautifulSoup(html, "html.parser")
    out = DetailFields()
    for dl in soup.find_all("dl"):
        dt = dl.find("dt")
        dd = dl.find("dd")
        if not dt or not dd:
            continue
        key = normalize(dt.get_text())
        val = normalize(dd.get_text(" ", strip=True))
        if not val:
            continue
        if key == "法廷名":
            out.courtroom = val
        elif key == "判示事項":
            out.key_ruling = val
        elif key == "裁判要旨":
            out.summary = val
        elif key == "参照法条":
            out.references = val
        elif key.startswith("判例集"):
            out.reporter_citation = val
        elif key in ("当事者", "当事者名"):
            out.parties = val
    return out


# ---------------------------------------------------------------------------
# Walk + assemble
# ---------------------------------------------------------------------------


@dataclass
class CourtRow:
    """Final shape ready to UPSERT into court_decisions."""

    unified_id: str
    case_name: str
    case_number: str
    court: str
    court_level: str
    decision_date: str | None
    decision_type: str
    subject_area: str
    related_law_ids_json: str | None
    key_ruling: str | None
    parties_involved: str | None
    impact_on_business: str | None
    precedent_weight: str
    full_text_url: str
    pdf_url: str | None
    source_url: str
    source_excerpt: str | None
    source_checksum: str | None
    confidence: float
    fetched_at: str
    updated_at: str


def walk_law(
    client: CourtsClient,
    *,
    law: str,
    endpoint: str,
    subject: str,
    per_law_cap: int,
) -> Iterator[ListingRow]:
    base = SEARCH2_URL if endpoint == "search2" else SEARCH4_URL
    encoded = urllib.parse.quote(law)
    offset = 0
    seen_ids: set[str] = set()
    total: int | None = None
    while True:
        url = f"{base}?filter%5Breference%5D={encoded}&offset={offset}#searched"
        try:
            html = client.get(url)
        except Exception as exc:  # noqa: BLE001
            _LOG.warning("listing fetch failed law=%s offset=%d err=%s", law, offset, exc)
            break
        if total is None:
            total = parse_listing_total(html)
            if total is not None:
                _LOG.info("law=%s endpoint=%s total=%d", law, endpoint, total)
        rows = parse_listing_page(html, seed_law=law, seed_subject=subject)
        if not rows:
            break
        for r in rows:
            if r.hid in seen_ids:
                continue
            seen_ids.add(r.hid)
            yield r
            if len(seen_ids) >= per_law_cap:
                return
        offset += PAGE_SIZE
        if total is not None and offset >= total:
            break


def assemble(
    listing: ListingRow,
    detail: DetailFields | None,
    fetched_at: str,
) -> CourtRow | None:
    court = detail.courtroom if detail and detail.courtroom else listing.court
    court = normalize(court)
    if not court:
        return None
    level = map_court_level(court)
    if level is None:
        # Fall back from list label.
        if "最高裁" in listing.list_label:
            level = "supreme"
            court = court or "最高裁判所"
        elif "高裁" in listing.list_label:
            level = "high"
        elif "地裁" in listing.list_label:
            level = "district"
        else:
            return None

    decision_type = map_decision_type(listing.decision_type_raw)
    if not decision_type:
        # Try detail summary text fallback.
        return None

    decision_date = parse_wareki_date(listing.decision_date_raw)
    case_number = normalize(listing.case_number)
    case_name = normalize(listing.case_name) or "(事件名なし)"
    if not case_number:
        return None

    unified_id = compute_unified_id(case_number, court)

    key_ruling = detail.key_ruling if detail else None
    summary = detail.summary if detail else None
    references = detail.references if detail else None

    # Choose subject_area: prefer explicit code from references, else seed.
    subject = listing.seed_subject_area
    if references:
        if "税法" in references or "国税" in references or "租税" in references:
            subject = "租税"
        elif (
            "行政事件訴訟法" in references or "行政手続法" in references or "行政不服" in references
        ) or "国家賠償" in references:
            subject = "行政"
        elif "補助金" in references:
            subject = "補助金適正化"
        elif "独占禁止法" in references:
            subject = "独禁"
        elif "地方自治法" in references:
            subject = "行政"

    excerpt_parts: list[str] = []
    if key_ruling:
        excerpt_parts.append("【判示事項】" + key_ruling)
    if summary:
        excerpt_parts.append("【裁判要旨】" + summary)
    if references:
        excerpt_parts.append("【参照法条】" + references)
    excerpt = "\n".join(excerpt_parts)[:1500] if excerpt_parts else None

    return CourtRow(
        unified_id=unified_id,
        case_name=case_name,
        case_number=case_number,
        court=court,
        court_level=level,
        decision_date=decision_date,
        decision_type=decision_type,
        subject_area=subject,
        related_law_ids_json=None,  # reconciliation against laws table is out of scope here
        key_ruling=key_ruling,
        parties_involved=detail.parties if detail else None,
        impact_on_business=summary,
        precedent_weight=map_precedent_weight(level),
        full_text_url=listing.detail_url,
        pdf_url=listing.pdf_url,
        source_url=listing.detail_url,
        source_excerpt=excerpt,
        source_checksum=None,
        confidence=0.9,
        fetched_at=fetched_at,
        updated_at=fetched_at,
    )


# ---------------------------------------------------------------------------
# DB layer
# ---------------------------------------------------------------------------


def open_db(db_path: Path) -> sqlite3.Connection:
    if not db_path.exists():
        raise FileNotFoundError(f"DB missing: {db_path}")
    conn = sqlite3.connect(str(db_path), timeout=300)
    conn.execute("PRAGMA busy_timeout = 300000")
    conn.execute("PRAGMA foreign_keys = ON")
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='court_decisions'"
    ).fetchone()
    if not row:
        raise RuntimeError("court_decisions table missing — run migration 016 first")
    return conn


def upsert_row(conn: sqlite3.Connection, r: CourtRow) -> str:
    existed = (
        conn.execute(
            "SELECT 1 FROM court_decisions WHERE unified_id = ?", (r.unified_id,)
        ).fetchone()
        is not None
    )
    conn.execute(
        """INSERT INTO court_decisions (
            unified_id, case_name, case_number, court, court_level,
            decision_date, decision_type, subject_area, related_law_ids_json,
            key_ruling, parties_involved, impact_on_business, precedent_weight,
            full_text_url, pdf_url, source_url, source_excerpt,
            source_checksum, confidence, fetched_at, updated_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(unified_id) DO UPDATE SET
            case_name = excluded.case_name,
            case_number = COALESCE(excluded.case_number, case_number),
            court = COALESCE(excluded.court, court),
            court_level = excluded.court_level,
            decision_date = COALESCE(excluded.decision_date, decision_date),
            decision_type = excluded.decision_type,
            subject_area = COALESCE(excluded.subject_area, subject_area),
            related_law_ids_json = COALESCE(excluded.related_law_ids_json, related_law_ids_json),
            key_ruling = COALESCE(excluded.key_ruling, key_ruling),
            parties_involved = COALESCE(excluded.parties_involved, parties_involved),
            impact_on_business = COALESCE(excluded.impact_on_business, impact_on_business),
            precedent_weight = excluded.precedent_weight,
            full_text_url = COALESCE(excluded.full_text_url, full_text_url),
            pdf_url = COALESCE(excluded.pdf_url, pdf_url),
            source_url = excluded.source_url,
            source_excerpt = COALESCE(excluded.source_excerpt, source_excerpt),
            source_checksum = COALESCE(excluded.source_checksum, source_checksum),
            confidence = excluded.confidence,
            fetched_at = excluded.fetched_at,
            updated_at = excluded.updated_at
        """,
        (
            r.unified_id,
            r.case_name,
            r.case_number,
            r.court,
            r.court_level,
            r.decision_date,
            r.decision_type,
            r.subject_area,
            r.related_law_ids_json,
            r.key_ruling,
            r.parties_involved,
            r.impact_on_business,
            r.precedent_weight,
            r.full_text_url,
            r.pdf_url,
            r.source_url,
            r.source_excerpt,
            r.source_checksum,
            r.confidence,
            r.fetched_at,
            r.updated_at,
        ),
    )
    # FTS mirror.
    conn.execute("DELETE FROM court_decisions_fts WHERE unified_id = ?", (r.unified_id,))
    conn.execute(
        "INSERT INTO court_decisions_fts ("
        "unified_id, case_name, subject_area, key_ruling, impact_on_business"
        ") VALUES (?,?,?,?,?)",
        (r.unified_id, r.case_name, r.subject_area, r.key_ruling, r.impact_on_business),
    )
    return "update" if existed else "insert"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument(
        "--per-law-cap",
        type=int,
        default=MAX_PER_LAW,
        help="cap rows per (law, endpoint) pair before moving on",
    )
    ap.add_argument(
        "--total-cap",
        type=int,
        default=MAX_TOTAL_DETAILS,
        help="absolute cap across all laws",
    )
    ap.add_argument(
        "--skip-detail",
        action="store_true",
        help="skip per-case detail fetch (faster; misses 判示事項/裁判要旨/参照法条)",
    )
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--verbose", "-v", action="store_true")
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    fetched_at = _dt.datetime.now(_dt.UTC).isoformat(timespec="seconds").replace("+00:00", "Z")

    conn: sqlite3.Connection | None = None
    if not args.dry_run:
        try:
            conn = open_db(args.db)
        except FileNotFoundError as exc:
            _LOG.error("%s", exc)
            return 2
        except RuntimeError as exc:
            _LOG.error("%s", exc)
            return 2

    client = CourtsClient()
    stats = {
        "walked": 0,
        "built": 0,
        "inserted": 0,
        "updated": 0,
        "skipped": 0,
        "detail_fail": 0,
    }
    seen_unified: set[str] = set()
    rows_to_write: list[CourtRow] = []

    try:
        for law, endpoint, subject in REFERENCE_LAWS:
            if stats["walked"] >= args.total_cap:
                break
            for listing in walk_law(
                client,
                law=law,
                endpoint=endpoint,
                subject=subject,
                per_law_cap=args.per_law_cap,
            ):
                if stats["walked"] >= args.total_cap:
                    break
                stats["walked"] += 1
                detail: DetailFields | None = None
                if not args.skip_detail:
                    try:
                        detail_html = client.get(listing.detail_url)
                        detail = parse_detail_page(detail_html)
                    except Exception as exc:  # noqa: BLE001
                        _LOG.warning("detail fetch failed url=%s err=%s", listing.detail_url, exc)
                        stats["detail_fail"] += 1
                row = assemble(listing, detail, fetched_at)
                if not row:
                    stats["skipped"] += 1
                    continue
                if row.unified_id in seen_unified:
                    continue
                seen_unified.add(row.unified_id)
                rows_to_write.append(row)
                stats["built"] += 1
                _LOG.info(
                    "OK law=%s %s | %s | %s | %s | %s",
                    law,
                    row.unified_id,
                    row.case_number,
                    (row.court or "?")[:18],
                    row.decision_date or "????-??-??",
                    (row.case_name or "")[:30],
                )
    finally:
        client.close()

    # Single transaction write — keep it parallel-safe.
    if not args.dry_run and conn is not None and rows_to_write:
        try:
            conn.execute("BEGIN IMMEDIATE")
            for r in rows_to_write:
                v = upsert_row(conn, r)
                if v == "insert":
                    stats["inserted"] += 1
                else:
                    stats["updated"] += 1
            conn.commit()
        except sqlite3.Error as exc:
            _LOG.error("DB write failed: %s", exc)
            with contextlib.suppress(Exception):
                conn.rollback()
            return 1
        finally:
            conn.close()

    _LOG.info(
        "done walked=%d built=%d inserted=%d updated=%d skipped=%d detail_fail=%d",
        stats["walked"],
        stats["built"],
        stats["inserted"],
        stats["updated"],
        stats["skipped"],
        stats["detail_fail"],
    )
    if stats["built"] < MIN_ROWS_FOR_OK:
        _LOG.warning(
            "built (%d) below min target (%d) — non-zero exit so callers retry",
            stats["built"],
            MIN_ROWS_FOR_OK,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
