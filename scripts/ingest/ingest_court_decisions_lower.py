#!/usr/bin/env python3
"""Bootstrap 高裁/地裁 rows in ``court_decisions`` from courts.go.jp 裁判例検索.

Why a third ingester (alongside ingest_court_decisions{,_courts_jp}.py)?
  ingest_court_decisions_courts_jp.py covers 最高裁判例集 only — it uses the
  ``filter[reference]=<法令名>`` form, which exists only on search2 (最高裁).
  Per 2026-04-25 directive ("TOSは一旦無視して獲得優先"), we extend coverage
  to the four lower-court reporters that share courts.go.jp's HTML form:

    * search3 (高裁判例集)         courtCaseType=2  -> high
    * search4 (下級裁判所判例集)    courtCaseType=4  -> high/district
    * search5 (行政事件裁判例集)    courtCaseType=5  -> high/district
    * search6 (労働事件裁判例集)    courtCaseType=6  -> high/district

  These endpoints accept ``query1=<keyword>`` (free-text) but NOT
  ``filter[reference]``. We seed with AutonoMath-domain keywords
  (税 / 行政 / 補助金 / 労働 / 知財) and walk pagination 30/page.

Source discipline:
  * Only ``www.courts.go.jp`` is whitelisted.
  * Aggregators banned (kept in sync with the 最高裁 ingester).
  * UA: ``AutonoMath/0.1.0 (+https://bookyou.net)``.
  * Rate: 1 req/sec/host (sleep(1.0) between every outbound HTTP call).
  * robots.txt: ``/hanrei/`` is allowed (verified 2026-04-25).
  * PDF URLs are recorded; PDF body is NEVER fetched.

Listing differences vs search2:
  * 高裁/地裁 rows often omit the 判決/決定 token in the result row's line2;
    they reach courts.go.jp's reporters only as 判決. We default to 判決
    when the token is missing AND the detail page lacks 裁判種別.
  * Court-name tokens are 東京高等裁判所 / 東京地方裁判所 (no 小法廷); the
    existing ``COURT_LEVEL_RULES`` substring match handles this.
  * Detail pages variants: detail3 (高裁), detail5 (行政), detail6 (労働).
    All carry ``事件番号``, ``事件名``, ``裁判年月日``, ``裁判所名`` (or
    ``裁判所名・部``), and most carry ``判示事項`` / ``裁判要旨`` (detail6
    sometimes lacks 裁判要旨 — handled gracefully).

DB writes:
  * BEGIN IMMEDIATE + busy_timeout=300000 (parallel-safe per spec).
  * UPSERT on unified_id; UNIQUE(case_number, court) is honored by schema.
  * unified_id = ``HAN-`` + sha256(case_number|court)[:10] (idempotent).
  * Mirror to ``court_decisions_fts`` (DELETE + INSERT).

Exit codes:
  0  success (rows inserted ≥ MIN_ROWS_FOR_OK)
  1  network error or no data after retries
  2  DB schema missing
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

_LOG = logging.getLogger("autonomath.ingest.court_decisions_lower")

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_DB = REPO_ROOT / "data" / "jpintel.db"

USER_AGENT = "AutonoMath/0.1.0 (+https://bookyou.net)"
PER_REQUEST_DELAY_SEC = 1.0
HTTP_TIMEOUT_SEC = 30.0
MAX_RETRIES = 3

ALLOWED_HOST = "www.courts.go.jp"

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

# (endpoint_segment, courtCaseType, label, default_subject_area)
ENDPOINT_LABELS: dict[str, tuple[int, str, str]] = {
    "search3": (2, "高裁判例", "民事"),
    "search4": (4, "行政事件裁判例", "行政"),
    "search5": (5, "労働事件裁判例", "労働"),
    "search6": (6, "知的財産裁判例", "知財"),
}

# Keyword seeds — endpoint -> [(query1, subject_hint)]
# We bias towards AutonoMath-relevant 行政/税務/補助金/労働/知財 cases.
# search4 (行政事件) is the largest reporter; we cap per-keyword to spread
# coverage across topics rather than monopolising on '所得税'.
KEYWORD_SEEDS: dict[str, tuple[tuple[str, str], ...]] = {
    "search3": (
        ("所得税", "租税"),
        ("法人税", "租税"),
        ("消費税", "租税"),
        ("相続税", "租税"),
        ("地方税", "租税"),
        ("租税", "租税"),
        ("補助金", "補助金適正化"),
        ("行政処分", "行政"),
        ("国家賠償", "行政"),
        ("独占禁止", "独禁"),
        ("不当労働", "労働"),
        ("解雇", "労働"),
    ),
    "search4": (
        ("所得税", "租税"),
        ("法人税", "租税"),
        ("消費税", "租税"),
        ("相続税", "租税"),
        ("地方税", "租税"),
        ("租税特別措置", "租税"),
        ("国税通則", "租税"),
        ("補助金", "補助金適正化"),
        ("交付金", "補助金適正化"),
        ("行政処分", "行政"),
        ("国家賠償", "行政"),
        ("認可", "行政"),
        ("許可", "行政"),
        ("独占禁止", "独禁"),
        ("不当労働", "労働"),
        ("解雇", "労働"),
    ),
    "search5": (
        ("所得税", "租税"),
        ("法人税", "租税"),
        ("消費税", "租税"),
        ("補助金", "補助金適正化"),
        ("行政処分", "行政"),
        ("国家賠償", "行政"),
        ("独占禁止", "独禁"),
        ("認可", "行政"),
    ),
    "search6": (
        ("解雇", "労働"),
        ("不当労働", "労働"),
        ("残業", "労働"),
        ("懲戒", "労働"),
        ("配転", "労働"),
        ("育児休業", "労働"),
        ("労災", "労働"),
        ("パワハラ", "労働"),
        ("セクハラ", "労働"),
    ),
}

PAGE_SIZE = 30
MAX_PER_KEYWORD = 90  # 3 pages per (endpoint, keyword)
MAX_TOTAL_DETAILS = 1500
MIN_ROWS_FOR_OK = 600

COURT_LEVEL_RULES: tuple[tuple[str, str], ...] = (
    ("最高裁判所", "supreme"),
    ("高等裁判所", "high"),
    ("地方裁判所", "district"),
    ("簡易裁判所", "summary"),
    ("家庭裁判所", "family"),
)

DECISION_TYPE_KANJI: frozenset[str] = frozenset({"判決", "決定", "命令"})

_GENGO: tuple[tuple[str, int], ...] = (
    ("令和", 2018),
    ("平成", 1988),
    ("昭和", 1925),
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
# Helpers (mirror of the 最高裁 ingester — kept inline for parallel-safety)
# ---------------------------------------------------------------------------


def normalize(text: str | None) -> str:
    if not text:
        return ""
    return unicodedata.normalize("NFKC", text).strip()


def kanji_num_to_int(s: str) -> int | None:
    if not s:
        return None
    s = s.strip()
    if s.isdigit():
        return int(s)
    if "十" in s:
        if s == "十":
            return 10
        if s.startswith("十"):
            tail = s[1:]
            return 10 + (_KANJI_DIGIT.get(tail, 0) if tail else 0)
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
    gy = base + yi
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
    for kind in ("判決", "決定", "命令"):
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
# HTTP layer
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
    hid: str
    detail_n: int
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
    list_label: str
    seed_subject_area: str
    seed_keyword: str


_DETAIL_LINK_RE = re.compile(r"\.\./(\d+)/detail(\d+)/")
_CASE_NUM_RE = re.compile(r"^([^\s]+\([^)]+\)\d+(?:号)?(?:等)?)\s*(.*)$")
_DATE_FIND_RE = re.compile(
    r"(令和|平成|昭和|大正|明治)\s*[元〇零一二三四五六七八九十0-9]+\s*年\s*"
    r"[〇零一二三四五六七八九十0-9]+\s*月\s*[〇零一二三四五六七八九十0-9]+\s*日"
)


def parse_listing_page(html: str, *, seed_keyword: str, seed_subject: str) -> list[ListingRow]:
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", class_="search-result-table")
    if not table:
        return []
    rows: list[ListingRow] = []
    for tr in table.find_all("tr"):
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

        tds = tr.find_all("td")
        if not tds:
            continue
        body_td = tds[0]
        ps = body_td.find_all("p")
        if not ps:
            continue
        line1 = normalize(ps[0].get_text(" ", strip=True))
        case_number = ""
        case_name = ""
        cn_m = _CASE_NUM_RE.match(line1)
        if cn_m:
            case_number = cn_m.group(1)
            case_name = cn_m.group(2).strip()
        else:
            case_name = line1

        line2 = normalize(ps[1].get_text(" ", strip=True)) if len(ps) > 1 else ""
        decision_date_raw = ""
        court = ""
        decision_type_raw = ""
        result: str | None = None
        original_court: str | None = None
        original_case_number: str | None = None
        date_m = _DATE_FIND_RE.search(line2)
        if date_m:
            decision_date_raw = date_m.group(0)
            tail = line2[date_m.end() :].strip()
            parts = re.split(r"\s+", tail)
            if parts:
                court = parts[0]
                idx = 1
                while idx < len(parts):
                    tok = parts[idx]
                    if tok in DECISION_TYPE_KANJI:
                        decision_type_raw = tok
                        idx += 1
                        break
                    if tok in ("第一小法廷", "第二小法廷", "第三小法廷", "大法廷"):
                        court = court + tok
                        idx += 1
                        continue
                    idx += 1
                if idx < len(parts):
                    result = parts[idx]
                    idx += 1
                rest = [t for t in parts[idx:] if t]
                if rest:
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
                seed_keyword=seed_keyword,
            )
        )
    return rows


def parse_listing_total(html: str) -> int | None:
    m = re.search(r"(\d[\d,]*)\s*件中", html)
    if not m:
        return None
    return int(m.group(1).replace(",", ""))


# ---------------------------------------------------------------------------
# Detail parser (handles detail3 / detail5 / detail6)
# ---------------------------------------------------------------------------


@dataclass
class DetailFields:
    courtroom: str | None = None  # 裁判所名・部 / 裁判所名 / 法廷名
    decision_type: str | None = None  # 裁判種別 (rare on lower-court detail)
    key_ruling: str | None = None  # 判示事項
    summary: str | None = None  # 裁判要旨
    references: str | None = None  # 参照法条
    reporter_citation: str | None = None
    parties: str | None = None
    field_label: str | None = None  # 分野 (search5/6 only)


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
        if key in ("法廷名", "裁判所名", "裁判所名・部"):
            out.courtroom = val
        elif key == "裁判種別":
            out.decision_type = val
        elif key == "判示事項":
            out.key_ruling = val
        elif key == "裁判要旨":
            out.summary = val
        elif key == "参照法条":
            out.references = val
        elif key.startswith("判例集") or key.startswith("高裁判例集"):
            out.reporter_citation = val
        elif key in ("当事者", "当事者名"):
            out.parties = val
        elif key == "分野":
            out.field_label = val
    return out


# ---------------------------------------------------------------------------
# Walk + assemble
# ---------------------------------------------------------------------------


@dataclass
class CourtRow:
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


def walk_keyword(  # noqa: N803  (courtCaseType matches courts.go.jp API query param)
    client: CourtsClient,
    *,
    endpoint: str,
    courtCaseType: int,
    keyword: str,
    subject: str,
    per_keyword_cap: int,
) -> Iterator[ListingRow]:
    base = f"https://www.courts.go.jp/hanrei/{endpoint}/index.html"
    encoded = urllib.parse.quote(keyword)
    offset = 0
    seen_ids: set[str] = set()
    total: int | None = None
    while True:
        url = f"{base}?courtCaseType={courtCaseType}&query1={encoded}&offset={offset}#searched"
        try:
            html = client.get(url)
        except Exception as exc:  # noqa: BLE001
            _LOG.warning(
                "listing fetch failed endpoint=%s kw=%s offset=%d err=%s",
                endpoint,
                keyword,
                offset,
                exc,
            )
            break
        if total is None:
            total = parse_listing_total(html)
            if total is not None:
                _LOG.info(
                    "endpoint=%s kw=%s total=%d",
                    endpoint,
                    keyword,
                    total,
                )
        rows = parse_listing_page(html, seed_keyword=keyword, seed_subject=subject)
        if not rows:
            break
        for r in rows:
            if r.hid in seen_ids:
                continue
            seen_ids.add(r.hid)
            yield r
            if len(seen_ids) >= per_keyword_cap:
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
    # 裁判所名・部 may include extra whitespace ('東京高等裁判所  第４刑事部')
    # We compress to single-space.
    court = re.sub(r"\s+", " ", court)
    if not court:
        return None
    level = map_court_level(court)
    if level is None:
        if "最高裁" in listing.list_label:
            level = "supreme"
        elif "高裁" in listing.list_label:
            level = "high"
        elif "地裁" in listing.list_label:
            level = "district"
        else:
            return None

    # Decision type: prefer listing token, else detail field, else default 判決
    # (高裁判例集 / 下級裁 / 行政 / 労働 reporters carry only 判決 unless
    # detail explicitly says otherwise).
    decision_type = map_decision_type(listing.decision_type_raw)
    if not decision_type and detail and detail.decision_type:
        decision_type = map_decision_type(detail.decision_type) or detail.decision_type
    if decision_type not in DECISION_TYPE_KANJI:
        decision_type = "判決"

    decision_date = parse_wareki_date(listing.decision_date_raw)
    case_number = normalize(listing.case_number)
    case_name = normalize(listing.case_name) or "(事件名なし)"
    if not case_number:
        return None

    unified_id = compute_unified_id(case_number, court)

    key_ruling = detail.key_ruling if detail else None
    summary = detail.summary if detail else None
    references = detail.references if detail else None

    # Subject area: prefer 参照法条 inference, else 分野, else seed.
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
        elif "労働" in references:
            subject = "労働"
    elif detail and detail.field_label:
        flab = detail.field_label
        if "租税" in flab or "税" in flab:
            subject = "租税"
        elif "行政" in flab:
            subject = "行政"
        elif "労働" in flab:
            subject = "労働"
        elif "知財" in flab or "特許" in flab or "知的財産" in flab:
            subject = "知財"

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
        related_law_ids_json=None,
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
        "--per-keyword-cap",
        type=int,
        default=MAX_PER_KEYWORD,
        help="cap rows per (endpoint, keyword) pair before moving on",
    )
    ap.add_argument(
        "--total-cap",
        type=int,
        default=MAX_TOTAL_DETAILS,
        help="absolute cap across all keywords",
    )
    ap.add_argument(
        "--skip-detail",
        action="store_true",
        help="skip per-case detail fetch (faster; misses 判示事項/裁判要旨)",
    )
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--verbose", "-v", action="store_true")
    ap.add_argument(
        "--endpoints",
        nargs="*",
        default=list(ENDPOINT_LABELS.keys()),
        help="subset of endpoint segments (search3 search4 search5 search6)",
    )
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
        for endpoint in args.endpoints:
            if endpoint not in ENDPOINT_LABELS:
                _LOG.warning("unknown endpoint %s — skipping", endpoint)
                continue
            cct, label, _default_subject = ENDPOINT_LABELS[endpoint]
            seeds = KEYWORD_SEEDS.get(endpoint, ())
            for keyword, subject in seeds:
                if stats["walked"] >= args.total_cap:
                    break
                _LOG.info(
                    "WALK endpoint=%s (%s) kw=%s subject=%s",
                    endpoint,
                    label,
                    keyword,
                    subject,
                )
                for listing in walk_keyword(
                    client,
                    endpoint=endpoint,
                    courtCaseType=cct,
                    keyword=keyword,
                    subject=subject,
                    per_keyword_cap=args.per_keyword_cap,
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
                            _LOG.warning(
                                "detail fetch failed url=%s err=%s",
                                listing.detail_url,
                                exc,
                            )
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
                        "OK ep=%s kw=%s %s | %s | %s | %s | %s",
                        endpoint,
                        keyword,
                        row.unified_id,
                        row.case_number,
                        (row.court or "?")[:24],
                        row.decision_date or "????-??-??",
                        (row.case_name or "")[:30],
                    )
            if stats["walked"] >= args.total_cap:
                break
    finally:
        client.close()

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
