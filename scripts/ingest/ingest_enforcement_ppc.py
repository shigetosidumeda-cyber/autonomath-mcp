#!/usr/bin/env python3
"""Ingest PPC (個人情報保護委員会) enforcement actions into autonomath.db.

Scope (2026-04-25):
    PPC publishes 行政上の対応 / 指導 / 勧告 / 命令 / 注意喚起 via 報道発表
    at https://www.ppc.go.jp/news/press/{YYYY}/. The fiscal year (令和) index
    page lists each item as <li>YYYY年MM月DD日 タイトル</li> with an anchor
    pointing to the detail page /news/press/{YYYY}/{slug}/. The HTML detail
    page is sparse — most of the substantive text (法人番号, 法第X条, 違反
    事実, 漏えい件数) lives in the linked PDF (typically /files/pdf/{slug}.pdf).

    We walk indexes 2014..2026 (令和元年度 = 2019, 令和8年度 = 2026), classify
    each title against KIND_ORDER, fetch the detail HTML for sparse meta, then
    optionally fetch the first PDF for body text. We extract the 法人番号
    (13-digit) and 法第X条 references via regex.

    Pre-2017 PPC handled mainly マイナンバー指導 (older PIPA enforcement was at
    METI/MHLW until 2017-04). We do NOT walk meti.go.jp/policy/it_policy/
    privacy/ here — that site times out from this network and the PPC corpus
    alone is sufficient for the M&A DD use case.

Source license:
    PDL v1.0 (公共データ利用規約 第1.0版). Attribution:
        出典: 個人情報保護委員会ホームページ (https://www.ppc.go.jp/)
    Aggregators (biz.stayway, prtimes, nikkei) are BANNED per CLAUDE.md.

Schema mapping (am_enforcement_detail.enforcement_kind enum):
    指導                 → business_improvement
    勧告                 → business_improvement
    命令                 → business_improvement
    行政上の対応 (汎用)  → business_improvement
    注意喚起             → other
    公表                 → other

Dedup key:
    (issuing_authority='個人情報保護委員会', issuance_date, target_name).
    Plus canonical_id uniqueness on
        enforcement:ppc:{issuance_date}:{slug}.

CLI:
    python scripts/ingest/ingest_enforcement_ppc.py
    python scripts/ingest/ingest_enforcement_ppc.py --years 2018,2019,2020,2021,2022,2023,2024,2025,2026
    python scripts/ingest/ingest_enforcement_ppc.py --max-inserts 200
    python scripts/ingest/ingest_enforcement_ppc.py --dry-run -v
"""

from __future__ import annotations

import argparse
import io
import json
import logging
import re
import sqlite3
import sys
import time
import unicodedata
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

try:
    import requests  # type: ignore
    from bs4 import BeautifulSoup  # type: ignore
except ImportError as exc:  # pragma: no cover
    print(
        f"missing dep: {exc}. pip install requests beautifulsoup4",
        file=sys.stderr,
    )
    sys.exit(1)

try:
    import pdfplumber  # type: ignore

    _HAVE_PDFPLUMBER = True
except ImportError:  # pragma: no cover
    _HAVE_PDFPLUMBER = False

_LOG = logging.getLogger("autonomath.ingest_ppc")

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_DB = REPO_ROOT / "autonomath.db"

USER_AGENT = "AutonoMath/0.1.0 (+https://bookyou.net) ingest-ppc (contact=ops@jpcite.com)"
BASE = "https://www.ppc.go.jp"
HTTP_TIMEOUT = 60
RATE_SLEEP = 1.2  # be polite — PPC is small site behind CloudFront

# Fiscal-year indexes. PPC was est. 2016 but news/press/ goes back to 2014.
# The Mission targets 2017+ but we walk back to 2014 for any back-catalog
# 指導/行政上の対応 we missed.
DEFAULT_YEARS = [
    "2014",
    "2015",
    "2016",
    "2017",
    "2018",
    "2019",
    "2020",
    "2021",
    "2022",
    "2023",
    "2024",
    "2025",
    "2026",
]

# Title keyword → enforcement_kind. Order matters — checked top-down.
# 命令/勧告/指導 are clearly enforcement; 行政上の対応 covers all of them; 注意
# 喚起 is softer; pure 公表 events are tagged as 'other'.
KIND_ORDER: tuple[tuple[str, str, str], ...] = (
    ("命令", "命令", "business_improvement"),
    ("勧告", "勧告", "business_improvement"),
    ("指導", "指導", "business_improvement"),
    ("行政上の対応", "行政上の対応", "business_improvement"),
    ("注意喚起", "注意喚起", "other"),
)

KIND_LABEL = {
    "business_improvement": "指導/勧告/命令/行政上の対応",
    "other": "注意喚起/公表",
}

# Patterns
WAREKI_RE = re.compile(
    r"(令和|平成)\s*(元|[0-9０-９]+)\s*年\s*"
    r"([0-9０-９]+)\s*月\s*([0-9０-９]+)\s*日"
)
SEIREKI_RE = re.compile(r"([0-9０-９]{4})\s*年\s*([0-9０-９]{1,2})\s*月\s*([0-9０-９]{1,2})\s*日")
HOUJIN_RE = re.compile(r"\b([0-9]{13})\b")
# 法第X条 / 法第X条第Y項 / 法第X条第Y項第Z号. We list the FULL law-name
# alternatives explicitly, plus standalone "法" preceded by a non-CJK boundary
# (so "保険業法" doesn't match — the "法" inside that compound has a CJK left
# context). The match must not be immediately preceded by another 漢字 of a
# law-name compound.
ARTICLE_RE = re.compile(
    r"(?P<law>個人情報の保護に関する法律|個人情報保護法|"
    r"行政手続における特定の個人を識別するための番号の利用等に関する法律|"
    r"番号法|マイナンバー法|(?<![一-鿿々])法)"
    r"\s*第\s*(?P<art>[0-9０-９]+)\s*条"
    r"(?:\s*第\s*(?P<para>[0-9０-９]+)\s*項)?"
    r"(?:\s*第\s*(?P<item>[0-9０-９]+)\s*号)?"
)
# Leak count: "対象者数 1,234 人" / "1,234 人分" / "約X件" patterns
LEAK_COUNT_RE = re.compile(r"([0-9０-９,，]{2,12})\s*(?:件|名|人|人分)")
# 漏えい等
LEAK_KEYWORDS = ("漏えい", "漏洩", "流出", "紛失", "誤交付", "不正持ち出し")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "")
    return re.sub(r"\s+", " ", text).strip()


def _wareki_to_iso(text: str) -> str | None:
    """Convert 令和X年Y月Z日 / 平成X年Y月Z日 / YYYY年Y月Z日 to ISO yyyy-mm-dd."""
    if not text:
        return None
    text = unicodedata.normalize("NFKC", text)
    m = WAREKI_RE.search(text)
    if m:
        era, yr, mo, dy = m.group(1), m.group(2), m.group(3), m.group(4)
        yr_i = 1 if yr == "元" else int(yr)
        if era == "令和":
            year = 2018 + yr_i
        elif era == "平成":
            year = 1988 + yr_i
        else:
            return None
        try:
            return f"{year:04d}-{int(mo):02d}-{int(dy):02d}"
        except ValueError:
            return None
    m = SEIREKI_RE.search(text)
    if m:
        try:
            return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
        except ValueError:
            return None
    return None


def _slugify(text: str, max_len: int = 60) -> str:
    text = unicodedata.normalize("NFKC", text or "")
    text = re.sub(r"\s+", "-", text)
    text = re.sub(r"[^0-9A-Za-z_\-぀-ヿ一-鿿々]", "", text)
    return text[:max_len] or "unknown"


def _classify_kind(title: str) -> tuple[str, str] | None:
    """Return (kind_token_jp, enforcement_kind) or None when not enforcement."""
    for token, label, kind in KIND_ORDER:
        if token in title:
            return label, kind
    return None


def _extract_target_name(title: str) -> str | None:
    """Pull defendant from press-release title.

    Title forms include:
        '株式会社FOOに対する個人情報の保護に関する法律に基づく行政上の対応について'
        '埼玉県所沢市における保有個人情報の取扱いについての行政上の対応について'
        '個人情報の保護に関する法律に基づく指導について（平成30年10月22日）' (no name)
        'BIPROGY 株式会社に対する個人情報の保護に関する法律に基づく…'
        'LINEヤフー株式会社への勧告等に対する改善状況の概要…' → strip 'への勧告等'
    """
    if not title:
        return None
    # Drop trailing 日付 prefix in parens.
    t = re.sub(r"（.*?）", "", title).strip()
    t = re.sub(r"\(.*?\)", "", t).strip()
    # Pattern A: "Xに対する..." (most common). Greedy match — then we strip
    # trailing 'への勧告等' / 'への対応' suffixes so multi-press-release titles
    # ('LINEヤフー株式会社への勧告等に対する改善状況...') yield the company
    # name without the procedural suffix.
    m = re.match(r"^(.+?)に対する", t)
    if m:
        candidate = m.group(1).strip()
        candidate = re.sub(
            r"(への勧告等|への勧告|への指導|への命令|への対応|への注意喚起)$",
            "",
            candidate,
        ).strip()
        if candidate:
            return candidate[:255]
    # Pattern B: "Xへの勧告等..." standalone (B1=immediate kind, B2=lawful action)
    m = re.match(r"^(.+?)への(勧告|指導|命令|対応|注意喚起)", t)
    if m:
        return m.group(1).strip()[:255]
    # B2: "Xへの個人情報の保護に関する法律に基づく行政上の対応..." style
    m = re.match(r"^(.+?)への個人情報", t)
    if m:
        return m.group(1).strip()[:255]
    # Pattern C: "Xにおける..." (geographic/agency cases)
    m = re.match(r"^(.+?)における", t)
    if m:
        return m.group(1).strip()[:255]
    # Pattern D: "X等に対する..."
    m = re.match(r"^(.+?等)に対する", t)
    if m:
        return m.group(1).strip()[:255]
    return None


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------


class HttpClient:
    def __init__(self, *, user_agent: str = USER_AGENT) -> None:
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": user_agent})
        self._last: float = 0.0

    def _wait(self) -> None:
        delta = time.monotonic() - self._last
        if delta < RATE_SLEEP:
            time.sleep(RATE_SLEEP - delta)

    def get(self, url: str) -> requests.Response | None:
        self._wait()
        last_err: Exception | None = None
        for attempt in range(3):
            try:
                resp = self.session.get(
                    url,
                    timeout=HTTP_TIMEOUT,
                    allow_redirects=True,
                )
                self._last = time.monotonic()
                if resp.status_code == 200:
                    return resp
                if resp.status_code in (404, 410):
                    return None
                last_err = RuntimeError(f"{resp.status_code} for {url}")
            except requests.RequestException as exc:
                last_err = exc
            time.sleep(2**attempt)
        _LOG.warning("fetch failed after retries: %s: %s", url, last_err)
        return None

    def get_bytes(self, url: str) -> bytes | None:
        self._wait()
        for attempt in range(3):
            try:
                resp = self.session.get(
                    url,
                    timeout=HTTP_TIMEOUT,
                    allow_redirects=True,
                )
                self._last = time.monotonic()
                if resp.status_code == 200:
                    return resp.content
                if resp.status_code in (404, 410):
                    return None
            except requests.RequestException:
                pass
            time.sleep(2**attempt)
        return None


# ---------------------------------------------------------------------------
# Listing parser
# ---------------------------------------------------------------------------


@dataclass
class ListingEntry:
    issuance_date: str  # ISO yyyy-mm-dd
    title: str  # title without date prefix
    raw_label: str  # full anchor / li text
    detail_url: str
    kind_label: str  # 命令 / 勧告 / 指導 / 行政上の対応 / 注意喚起
    enforcement_kind: str
    fy: str  # fiscal-year folder e.g. '2024'


def parse_year_index(
    html: str,
    *,
    fy: str,
    base_url: str,
) -> list[ListingEntry]:
    soup = BeautifulSoup(html, "html.parser")
    out: list[ListingEntry] = []
    seen_urls: set[str] = set()
    # Each item is in an <li> with text "YYYY年M月D日 Title" and an inner <a>.
    for li in soup.find_all("li"):
        a = li.find("a", href=True)
        if not a:
            continue
        href = a["href"].strip()
        if not href:
            continue
        # Restrict to detail pages within this FY folder.
        if f"/news/press/{fy}/" not in href:
            continue
        absurl = urljoin(base_url, href)
        # Skip the FY index itself.
        if absurl.rstrip("/").endswith(f"/news/press/{fy}"):
            continue
        if absurl in seen_urls:
            continue
        text = _normalize(li.get_text(" ", strip=True))
        if not text:
            continue
        date_iso = _wareki_to_iso(text)
        if not date_iso:
            continue
        # Title = text after date span. Drop the date prefix.
        title = re.sub(
            r"^[^年]*?(平成|令和|[0-9]{4})\s*[元0-9０-９]*\s*年\s*"
            r"[0-9０-９]+\s*月\s*[0-9０-９]+\s*日\s*",
            "",
            text,
        ).strip()
        if not title:
            title = _normalize(a.get_text(" ", strip=True))
        kind = _classify_kind(title)
        if not kind:
            continue
        kind_label, enf = kind
        seen_urls.add(absurl)
        out.append(
            ListingEntry(
                issuance_date=date_iso,
                title=title,
                raw_label=text,
                detail_url=absurl,
                kind_label=kind_label,
                enforcement_kind=enf,
                fy=fy,
            )
        )
    return out


# ---------------------------------------------------------------------------
# Detail parser
# ---------------------------------------------------------------------------


@dataclass
class DetailInfo:
    body_text: str = ""
    pdf_urls: list[str] = field(default_factory=list)
    pdf_text: str = ""
    houjin_bangous: list[str] = field(default_factory=list)
    article_refs: list[str] = field(default_factory=list)
    leak_count: int | None = None
    has_leak_keyword: bool = False
    # Multi-defendant breakout: list of (entity_name, houjin_bangou or None).
    # Populated when the title is a multi-party form e.g. "X、Y、Z及びWに対する...".
    extra_defendants: list[tuple[str, str | None]] = field(default_factory=list)


def _extract_articles(text: str, *, max_refs: int = 6) -> list[str]:
    refs: list[str] = []
    seen: set[str] = set()
    for m in ARTICLE_RE.finditer(text):
        full_law = m.group("law")
        if (
            "番号" in full_law
            or "マイナンバー" in full_law
            or "行政手続における特定の個人を識別" in full_law
        ):
            law = "番号法"
        else:
            law = "個人情報保護法"
        article_no = unicodedata.normalize("NFKC", m.group("art") or "")
        clause_no = unicodedata.normalize("NFKC", m.group("para") or "")
        item_no = unicodedata.normalize("NFKC", m.group("item") or "")
        ref = f"{law}第{article_no}条"
        if clause_no:
            ref += f"第{clause_no}項"
        if item_no:
            ref += f"第{item_no}号"
        if ref in seen:
            continue
        seen.add(ref)
        refs.append(ref)
        if len(refs) >= max_refs:
            break
    return refs


def _extract_leak_count(text: str) -> int | None:
    if not text:
        return None
    # Look near 漏えい / 流出 keywords first
    for kw in LEAK_KEYWORDS:
        idx = text.find(kw)
        if idx == -1:
            continue
        window = text[idx : idx + 400]
        m = LEAK_COUNT_RE.search(window)
        if m:
            digits = re.sub(r"[^0-9]", "", unicodedata.normalize("NFKC", m.group(1)))
            if digits and 2 <= len(digits) <= 9:
                try:
                    n = int(digits)
                    if 1 <= n <= 1_000_000_000:
                        return n
                except ValueError:
                    pass
    return None


def _pdf_text(pdf_bytes: bytes, *, max_pages: int = 6) -> str:
    if not _HAVE_PDFPLUMBER:
        return ""
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            chunks: list[str] = []
            for page in pdf.pages[:max_pages]:
                try:
                    t = page.extract_text() or ""
                except Exception:
                    t = ""
                if t:
                    chunks.append(t)
            text = "\n".join(chunks)
            # Reconnect intra-CJK soft line breaks. PDF text extraction often
            # splits a Japanese company name across two lines; we want to
            # rejoin "保険\nジャパン" → "保険ジャパン" so name-extraction can
            # match the full token. Only join when both sides of the newline
            # are CJK / latin name-chars.
            text = re.sub(
                r"([一-鿿々ぁ-ゖァ-ヺーA-Za-z0-9])\s*\n\s*([一-鿿々ぁ-ゖァ-ヺーA-Za-z0-9])",
                r"\1\2",
                text,
            )
            # Collapse single-space joints between ASCII (e.g., "NTT") and CJK
            # in name-like positions. PDFs often output "NTT ビジネス" but the
            # legal name has no space.
            text = re.sub(r"([A-Za-z0-9])[ \t]+([一-鿿々ぁ-ゖァ-ヺー])", r"\1\2", text)
            text = re.sub(r"([一-鿿々ぁ-ゖァ-ヺー])[ \t]+([A-Za-z0-9])", r"\1\2", text)
            return _normalize(text)
    except Exception as exc:  # pragma: no cover
        _LOG.debug("pdf parse failed: %s", exc)
        return ""


def parse_detail_page(
    html: str,
    source_url: str,
    *,
    http: HttpClient | None,
    fetch_pdf: bool = True,
) -> DetailInfo:
    soup = BeautifulSoup(html, "html.parser")
    info = DetailInfo()
    # PPC detail HTML wraps body in main / div.area_main / article. Fall back
    # to body.
    body_el = (
        soup.select_one("main")
        or soup.select_one("article")
        or soup.select_one("div.area_main")
        or soup.body
    )
    body_text = _normalize(body_el.get_text(" ", strip=True)) if body_el else ""
    info.body_text = body_text[:6000]

    # Collect PDF urls within this detail page.
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.lower().endswith(".pdf"):
            info.pdf_urls.append(urljoin(source_url, href))
    info.pdf_urls = info.pdf_urls[:8]

    # Pull PDF text from the first PDF (the rest are attachments / copies).
    if fetch_pdf and info.pdf_urls and http is not None:
        first_pdf = info.pdf_urls[0]
        pdf_bytes = http.get_bytes(first_pdf)
        if pdf_bytes:
            info.pdf_text = _pdf_text(pdf_bytes)

    haystack = "\n".join((info.body_text, info.pdf_text))
    # 法人番号
    seen: set[str] = set()
    for m in HOUJIN_RE.finditer(haystack):
        b = m.group(1)
        if b in seen:
            continue
        seen.add(b)
        info.houjin_bangous.append(b)
        if len(info.houjin_bangous) >= 8:
            break
    # 法第X条 references
    info.article_refs = _extract_articles(haystack)
    # Leak count
    info.leak_count = _extract_leak_count(haystack)
    info.has_leak_keyword = any(kw in haystack for kw in LEAK_KEYWORDS)
    # Extract extra defendants when PDF body lists multiple companies in a
    # single 'X、Y、Z及びWに対し' opening sentence.
    info.extra_defendants = _extract_extra_defendants(info.pdf_text or info.body_text)
    return info


# Multi-defendant extraction. We look for company tokens of the form
# "XYZ株式会社", "XYZ有限会社", etc. (suffix-style), or "株式会社XYZ"
# (prefix-style). To avoid pulling spans of running prose, we anchor on the
# suffix and walk left for at most 30 chars, breaking at any particle /
# punctuation / known boundary token.
_COMPANY_SUFFIXES = (
    "株式会社",
    "有限会社",
    "合同会社",
    "合資会社",
    "一般社団法人",
    "公益社団法人",
    "一般財団法人",
    "公益財団法人",
    "社団法人",
    "財団法人",
    "医療法人",
    "学校法人",
    "社会福祉法人",
    "宗教法人",
    "独立行政法人",
    "国立大学法人",
    "公立大学法人",
    "事業協同組合",
    "農業協同組合",
)
# Allowed name characters. NO Japanese hiragana particles. Real Japanese
# company names overwhelmingly use kanji / katakana / latin / digits (with
# the partial exception of names like "ぐるなび"). We therefore allow
# hiragana but rely on stop-words to bound the prefix.
_NAME_CHAR = r"[一-鿿々ぁ-ゖァ-ヺー〇A-Za-z0-9・・\-－&'’\.]"
# Particles / connectors that, if encountered while walking left, should
# terminate the prefix (we keep everything to the RIGHT of the particle).
_LEFT_STOP_TOKENS = (
    "の",
    "が",
    "は",
    "を",
    "に",
    "へ",
    "と",
    "で",
    "や",
    "も",
    "から",
    "まで",
    "より",
    "ため",
    "また",
    "及び",
    "並びに",
    "対し",
    "対する",
    "対して",
    "対しては",
    "について",
    "とともに",
    "とも",
    "とも称",
    "について",
    "については",
    "委託先である",
    "委託元である",
    "提供する",
    "運営する",
    "提供している",
    "運営している",
)
# Static suffix matcher: we use this to find suffix anchors quickly.
_SUFFIX_RE = re.compile("(" + "|".join(_COMPANY_SUFFIXES) + ")")


def _walk_left_for_name(text: str, suffix_start: int, *, max_len: int = 30) -> str | None:
    """Given a text and the start index of a company suffix, walk left and
    capture the company-name prefix. Returns the prefix string OR None when
    the prefix doesn't look like a real company name.
    """
    # Build the longest legal-char prefix (cap at max_len).
    i = suffix_start - 1
    chars: list[str] = []
    while i >= 0 and len(chars) < max_len:
        ch = text[i]
        if not re.match(_NAME_CHAR, ch):
            break
        chars.append(ch)
        i -= 1
    prefix = "".join(reversed(chars))
    if len(prefix) < 2:
        return None
    # Walk for stop tokens — drop everything up to and including the latest
    # stop token. Use the LONGEST match wins approach so "の委託先である" wins
    # over "の".
    cursor = 0
    while cursor < len(prefix):
        # Find the earliest stop token; cut after it.
        earliest_idx = -1
        earliest_len = 0
        for tok in _LEFT_STOP_TOKENS:
            j = prefix.find(tok, cursor)
            if j == -1:
                continue
            if (
                earliest_idx == -1
                or j < earliest_idx
                or (j == earliest_idx and len(tok) > earliest_len)
            ):
                earliest_idx = j
                earliest_len = len(tok)
        if earliest_idx == -1:
            break
        cursor = earliest_idx + earliest_len
    prefix = prefix[cursor:]
    if not prefix:
        return None
    return prefix


def _split_on_conjunctions(text: str) -> list[str]:
    """Split a chunk of body text on Japanese list conjunctions and commas
    so we can pick out individual company names from a longer recitation.
    """
    if not text:
        return []
    # Insert a separator on these tokens, then split by separator.
    out = re.sub(r"(及び|並びに|並び|又は|若しくは|、|，|,|。)", "", text)
    return [s.strip() for s in out.split("") if s.strip()]


_STRIP_LEFT_PREFIXES = (
    "個人情報保護委員会",
    "当委員会",
    "委員会",
    "金融庁",
    "総務省",
    "厚生労働省",
    "経済産業省",
    "本日",
    "について",
)
# Soft prefixes that should be peeled off ANY candidate (e.g. verb stems,
# date prefixes, descriptor pronouns) before the row enters the result list.
_SOFT_LEFT_STRIPS = (
    "委託された",
    "委託を受けた",
    "委託元である",
    "委託先である",
    "受託した",
    "受託している",
    "受けた",
    "受け",
    "ある",
    "当該",
    "ある一",
    "ある１",
    "委託している",
    "委託する",
)
_BLOCK_NAME_FRAGMENTS = (
    "について",
    "に対する",
    "に対し",
    "における",
    "に基づく",
    "の規定",
    "に係る",
    "に関する",
    "を通じて",
    "が実施",
    "が運営",
    "が提供",
    "が利用",
    "を行った",
    "を行う",
)
# Reject names where the prefix is one of these tokens — they are sentence
# fragments, not company-name leads.
_BLOCK_NAME_PREFIXES = (
    "受け",
    "委託",
    "ある",
    "ーグリッド",
    "電トナー",
    "ホールディングス",  # alone (should be 〜株式会社ホールディングス but that's PREFIX-style)
    "及び",
)
_GENERIC_DESCRIPTOR_SUFFIX_PREFIXES = (
    "損害保険会社",
    "保険代理店",
    "保険会社",
    "事業者",
    "送配電事業者",
    "電気事業者",
    "鉄道事業者",
    "親会社",
    "子会社",
    "関係会社",
    "委託先",
    "委託元",
    "再委託先",
    "再委託元",
    "他",
    "当該",
    "当社",
    "他社",
    "者",
    "本人",
    "会員",
    "顧客",
    "個人",
)
# Leading-junk regex: strip date prefixes ("令和5年2月17日"), numbered list
# markers ("1.", "①", "(1)"), and similar before evaluating the candidate.
_LEAD_JUNK_RE = re.compile(
    r"^(?:"
    r"令和\s*[0-9０-９]+\s*年\s*[0-9０-９]+\s*月\s*[0-9０-９]+\s*日|"
    r"平成\s*[0-9０-９]+\s*年\s*[0-9０-９]+\s*月\s*[0-9０-９]+\s*日|"
    r"令和\s*[0-9０-９]+\s*年|平成\s*[0-9０-９]+\s*年|"
    r"[0-9０-９]+\s*[\.．]|[①②③④⑤⑥⑦⑧⑨⑩]|"
    r"\([0-9０-９]+\)|（[0-9０-９]+）"
    r")\s*"
)


def _extract_extra_defendants(text: str) -> list[tuple[str, str | None]]:
    """Find named corporate defendants in the first ~1800 chars. Used for
    multi-party cases (大手損保４社, 一般送配電事業者, etc.). Returns
    de-duplicated list of (name, None) — houjin lookups happen separately
    because the PDF rarely lists a 法人番号 per defendant in the lede.

    Strategy:
        Walk the text scanning for company suffixes (株式会社, 有限会社, …).
        For each suffix anchor, capture the prefix to the LEFT by walking
        char-by-char until we hit a non-name character or a known stop token.
        This avoids the over-capture problem of greedy regex matching across
        running prose.
    """
    if not text:
        return []
    head = text[:1800]
    raw: list[str] = []

    def _starts_with_descriptor(p: str) -> bool:
        """Return True only if the prefix is the descriptor itself OR the
        descriptor followed by a non-name boundary. This prevents '個人' from
        falsely matching '個人情報保護委員会...'."""
        for d in _GENERIC_DESCRIPTOR_SUFFIX_PREFIXES:
            if not p.startswith(d):
                continue
            after = p[len(d) :]
            if not after:
                return True
            # If the next char continues a Japanese-name-like compound, it's
            # not the descriptor, just a coincidental prefix.
            if re.match(r"[一-鿿々]", after[0]):
                continue
            return True
        return False

    # Suffix-style: prefix + 株式会社
    for m in _SUFFIX_RE.finditer(head):
        suffix = m.group(1)
        suffix_start = m.start(1)
        prefix = _walk_left_for_name(head, suffix_start, max_len=30)
        if not prefix:
            continue
        # Special: 株式会社 can appear as PREFIX-style ("株式会社XYZ"). If
        # the suffix is 株式会社 AND the right-walk produces a longer span
        # AND the left prefix is a generic descriptor, prefer prefix-style.
        if suffix == "株式会社":
            j = m.end(1)
            right_chars: list[str] = []
            while j < len(head) and len(right_chars) < 30:
                ch = head[j]
                if not re.match(_NAME_CHAR, ch):
                    break
                right_chars.append(ch)
                j += 1
            right_str = "".join(right_chars)
            if len(right_str) >= 3 and _starts_with_descriptor(prefix):
                name = "株式会社" + right_str
                raw.append(name)
                continue
        if _starts_with_descriptor(prefix):
            continue
        name = prefix + suffix
        raw.append(name)
    # Filter / dedup.
    out: list[tuple[str, str | None]] = []
    seen: set[str] = set()
    for name in raw:
        name = name.strip().rstrip("、,。.")
        # Strip explicit junk left-prefixes (e.g., "個人情報保護委員会").
        for _ in range(3):
            stripped = name
            # Hard prefixes (authority names — always strip).
            for prefix in _STRIP_LEFT_PREFIXES:
                if stripped.startswith(prefix):
                    stripped = stripped[len(prefix) :].lstrip("、,。.（()「『 　")
            # Date / numbered-list / verb-stem soft junk.
            mlj = _LEAD_JUNK_RE.match(stripped)
            if mlj:
                stripped = stripped[mlj.end() :]
            for soft in _SOFT_LEFT_STRIPS:
                if stripped.startswith(soft):
                    rest = stripped[len(soft) :]
                    if not rest:
                        continue
                    # Only strip if remainder still has a real corporate
                    # suffix at the tail (else the soft-strip eats the body).
                    if rest.endswith(_COMPANY_SUFFIXES):
                        stripped = rest.lstrip("、,。.（()「『 　")
            if stripped == name:
                break
            name = stripped
        if not name or len(name) < 4:
            continue
        # Reject when the leading 4 chars are a known fragment marker.
        if any(name.startswith(p) for p in _BLOCK_NAME_PREFIXES):
            continue
        if any(tok in name for tok in _BLOCK_NAME_FRAGMENTS):
            continue
        if re.search(r"(が|の|を|に|で|と|や|から|まで|より|は|へ)$", name):
            continue
        if not name.endswith(_COMPANY_SUFFIXES):
            continue
        # Reject names that don't have at least one CJK or katakana char in
        # the body (i.e., 4+ chars but only 株式会社/有限会社 style suffix).
        body = name
        for sfx in _COMPANY_SUFFIXES:
            if body.endswith(sfx):
                body = body[: -len(sfx)]
                break
        if not body or len(body) < 2:
            continue
        # Body must start with a real corporate-name char (CJK / katakana /
        # latin / digit). Reject when it starts with hiragana — those are
        # always sentence fragments.
        if re.match(r"^[ぁ-ゖ]", body):
            continue
        if name in seen:
            continue
        seen.add(name)
        out.append((name, None))
        if len(out) >= 8:
            break

    # Suppress "shorter that is a body-substring of a longer name". This kills
    # fragments produced by PDF column breaks (e.g., 'ーグリッド株式会社' is a
    # tail of '東京電力パワーグリッド株式会社'; 'ホールディングス株式会社' is a
    # tail of '東京電力ホールディングス株式会社').
    def _body(n: str) -> str:
        for sfx in _COMPANY_SUFFIXES:
            if n.endswith(sfx):
                return n[: -len(sfx)]
        return n

    bodies = [(name, _body(name)) for name, _ in out]
    long_bodies = [b for _, b in bodies if len(b) >= 8]

    def _is_chimera(body: str, long_set: list[str]) -> bool:
        """A name body is a chimera when it can be split into A+B such that
        A is a prefix of some long body and B is a suffix of some (possibly
        different) long body, while body itself is NOT a substring of any
        long body. This catches PDF-column-merge artifacts like
        '東京電トナー' (split into 東京電 prefix-of-東京電力* and トナー
        suffix-of-*パートナー)."""
        if any(body in lb for lb in long_set):
            return False
        if len(body) < 4:
            return False
        for k in range(2, len(body) - 1):
            a, b = body[:k], body[k:]
            if any(lb.startswith(a) for lb in long_set) and any(lb.endswith(b) for lb in long_set):
                return True
        return False

    keep_idx: set[int] = set()
    for i, (n_i, b_i) in enumerate(bodies):
        is_proper_substring = False
        for j, (n_j, b_j) in enumerate(bodies):
            if i == j:
                continue
            # If this body is a tail-substring of a longer one, it's a tail
            # fragment.
            if len(b_i) < len(b_j) and (b_j.endswith(b_i) or b_j.startswith(b_i)):
                is_proper_substring = True
                break
        if is_proper_substring:
            continue
        # Reject chimeras (only against longer-than-self bodies).
        longer = [b for k, (_, b) in enumerate(bodies) if k != i and len(b) > len(b_i)]
        if _is_chimera(b_i, longer):
            continue
        keep_idx.add(i)
    out = [out[i] for i in sorted(keep_idx)]
    return out


# ---------------------------------------------------------------------------
# DB
# ---------------------------------------------------------------------------


def ensure_tables(conn: sqlite3.Connection) -> None:
    for tbl in ("am_entities", "am_enforcement_detail", "am_authority"):
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (tbl,),
        ).fetchone()
        if not row:
            raise SystemExit(f"missing table '{tbl}' — apply migrations first")


def ensure_ppc_authority(cur: sqlite3.Cursor) -> str:
    cur.execute(
        "SELECT canonical_id FROM am_authority WHERE canonical_id=?",
        ("authority:ppc",),
    )
    row = cur.fetchone()
    if row:
        return row[0]
    cur.execute(
        """INSERT INTO am_authority
               (canonical_id, canonical_name, canonical_en, level, website)
           VALUES (?, ?, ?, ?, ?)""",
        (
            "authority:ppc",
            "個人情報保護委員会",
            "PPC",
            "agency",
            "https://www.ppc.go.jp/",
        ),
    )
    return "authority:ppc"


def existing_dedup_keys(cur: sqlite3.Cursor) -> set[tuple[str, str]]:
    cur.execute(
        "SELECT issuance_date, target_name FROM am_enforcement_detail WHERE issuing_authority=?",
        ("個人情報保護委員会",),
    )
    out: set[tuple[str, str]] = set()
    for iso_date, name in cur.fetchall():
        if iso_date and name:
            out.add((iso_date, _normalize(name)))
    return out


def existing_canonical_ids(cur: sqlite3.Cursor) -> set[str]:
    cur.execute(
        "SELECT canonical_id FROM am_entities WHERE record_kind='enforcement' "
        "AND authority_canonical=?",
        ("authority:ppc",),
    )
    return {row[0] for row in cur.fetchall()}


def build_canonical_id(
    issuance_date: str,
    title: str,
    detail_url: str,
) -> str:
    slug = _slugify(title, max_len=32)
    stem = detail_url.rstrip("/").rsplit("/", 1)[-1].split(".", 1)[0]
    stem_slug = _slugify(stem, max_len=24)
    base = f"enforcement:ppc:{issuance_date}:{slug}"
    if stem_slug and stem_slug != "unknown":
        base = f"{base}:{stem_slug}"
    return base[:255]


def insert_one(
    cur: sqlite3.Cursor,
    *,
    canonical_id: str,
    listing: ListingEntry,
    detail: DetailInfo,
    chosen_target: str,
    houjin_bangou: str | None,
    related_law_ref: str | None,
    reason_summary: str,
    now_iso: str,
) -> bool:
    raw = {
        "source": "ppc:news_press",
        "fy": listing.fy,
        "title": listing.title,
        "raw_label": listing.raw_label,
        "kind_label": listing.kind_label,
        "enforcement_kind": listing.enforcement_kind,
        "detail_url": listing.detail_url,
        "issuance_date": listing.issuance_date,
        "houjin_bangous": detail.houjin_bangous,
        "article_refs": detail.article_refs,
        "leak_count": detail.leak_count,
        "has_leak_keyword": detail.has_leak_keyword,
        "pdf_urls": detail.pdf_urls,
        "issuing_authority": "個人情報保護委員会",
        "authority_canonical": "authority:ppc",
        "license": "PDL v1.0",
        "attribution": ("出典: 個人情報保護委員会ホームページ (https://www.ppc.go.jp/)"),
        "fetched_at": now_iso,
    }
    cur.execute(
        """INSERT OR IGNORE INTO am_entities
               (canonical_id, record_kind, source_topic, source_record_index,
                primary_name, authority_canonical, confidence, source_url,
                source_url_domain, fetched_at, raw_json,
                canonical_status, citation_status)
           VALUES (?, 'enforcement', ?, NULL, ?, 'authority:ppc', ?, ?, ?, ?,
                   ?, 'active', 'ok')""",
        (
            canonical_id,
            f"ppc_press_{listing.fy}",
            chosen_target[:255],
            0.92,
            listing.detail_url,
            "ppc.go.jp",
            now_iso,
            json.dumps(raw, ensure_ascii=False),
        ),
    )
    if cur.rowcount == 0:
        return False
    cur.execute(
        """INSERT INTO am_enforcement_detail
               (entity_id, houjin_bangou, target_name, enforcement_kind,
                issuing_authority, issuance_date, reason_summary,
                related_law_ref, amount_yen, source_url, source_fetched_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            canonical_id,
            houjin_bangou,
            chosen_target[:255],
            listing.enforcement_kind,
            "個人情報保護委員会",
            listing.issuance_date,
            reason_summary[:2000] if reason_summary else None,
            related_law_ref[:255] if related_law_ref else None,
            None,  # PPC does not impose 課徴金
            listing.detail_url,
            now_iso,
        ),
    )
    return True


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


def collect_listings(
    http: HttpClient,
    years: list[str],
) -> list[ListingEntry]:
    out: list[ListingEntry] = []
    for fy in years:
        url = f"{BASE}/news/press/{fy}/"
        resp = http.get(url)
        if resp is None:
            _LOG.debug("FY index missing %s", url)
            continue
        try:
            html = resp.text
        except Exception as exc:
            _LOG.warning("decode FY %s: %s", fy, exc)
            continue
        entries = parse_year_index(html, fy=fy, base_url=url)
        if entries:
            _LOG.info(
                "[list] FY%s -> %d enforcement-tagged entries",
                fy,
                len(entries),
            )
        out.extend(entries)
    _LOG.info("total listings (pre-dedup): %d", len(out))
    out.sort(key=lambda e: e.issuance_date, reverse=True)
    return out


def choose_target_name(
    listing: ListingEntry,
    detail: DetailInfo,
) -> tuple[str, str | None]:
    """Return (target_name, houjin_bangou).

    Strategy:
        1. Title regex (most reliable for PPC).
        2. Fallback to title verbatim (without 〜について suffix).
    """
    derived = _extract_target_name(listing.title)
    if derived:
        # Houjin bangou -> first found in detail.
        houjin = detail.houjin_bangous[0] if detail.houjin_bangous else None
        return derived, houjin
    cleaned = re.sub(r"について(\s*\(.*?\))?$", "", listing.title).strip()
    cleaned = re.sub(r"（.*?）", "", cleaned).strip()
    if not cleaned:
        cleaned = listing.title
    return cleaned[:255], (detail.houjin_bangous[0] if detail.houjin_bangous else None)


def build_reason_summary(
    listing: ListingEntry,
    detail: DetailInfo,
) -> str:
    parts: list[str] = [f"[{listing.kind_label}]"]
    src = detail.pdf_text or detail.body_text or ""
    if src:
        # Trim navigation / boilerplate header
        body = src
        for marker in ("公表資料 News Release", "報道発表資料"):
            if marker in body:
                body = body.split(marker, 1)[-1]
                break
        # Take first 600 chars after first 。
        first_period = body.find("。")
        if 0 < first_period < 600:
            snippet = body[: first_period + 1]
        else:
            snippet = body[:600]
        parts.append(snippet.strip())
    parts.append(f"件名: {listing.title}")
    if detail.leak_count:
        parts.append(f"漏えい件数: {detail.leak_count:,} 件相当")
    if detail.has_leak_keyword:
        parts.append("[漏えい等事案]")
    return " ".join(parts).strip()


def derive_law_ref(
    listing: ListingEntry,
    detail: DetailInfo,
) -> str | None:
    if detail.article_refs:
        return "; ".join(detail.article_refs[:4])
    # Fallback by kind.
    if listing.kind_label == "命令":
        return "個人情報保護法第148条第3項"
    if listing.kind_label == "勧告":
        return "個人情報保護法第148条第1項"
    if listing.kind_label == "指導":
        return "個人情報保護法第147条"
    if listing.kind_label == "行政上の対応":
        return "個人情報保護法 第147条/第148条"
    if listing.kind_label == "注意喚起":
        return "個人情報保護法"
    return "個人情報保護法"


def run(
    db_path: Path,
    *,
    years: list[str],
    max_inserts: int,
    skip_pdf: bool,
    dry_run: bool,
    verbose: bool,
) -> int:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    # Silence noisy 3rd-party DEBUG loggers (pdfminer/pdfplumber emit
    # tens of thousands of lines per PDF when root level is DEBUG).
    for noisy in ("pdfminer", "pdfplumber", "urllib3", "requests"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    now_iso = datetime.now(tz=UTC).isoformat(timespec="seconds").replace("+00:00", "Z")

    http = HttpClient()

    # 1. Walk year indexes.
    listings = collect_listings(http, years)

    if dry_run:
        _LOG.info(
            "dry-run: %d candidate listings (would attempt %d inserts max)",
            len(listings),
            max_inserts,
        )
        for e in listings[:15]:
            _LOG.info(
                "  cand %s [%s] %s -> %s",
                e.issuance_date,
                e.kind_label,
                e.title[:60],
                e.detail_url,
            )
        print(
            json.dumps(
                {
                    "candidate_listings": len(listings),
                    "by_kind": {
                        k: sum(1 for e in listings if e.kind_label == k)
                        for k in {x.kind_label for x in listings}
                    },
                    "by_fy": {
                        fy: sum(1 for e in listings if e.fy == fy)
                        for fy in sorted({x.fy for x in listings})
                    },
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    # 2. Open DB.
    if not db_path.exists():
        _LOG.error("autonomath.db missing: %s", db_path)
        return 2
    con = sqlite3.connect(str(db_path), timeout=300.0)
    try:
        con.execute("PRAGMA busy_timeout=300000")
        con.execute("PRAGMA foreign_keys=ON")
        ensure_tables(con)
        cur = con.cursor()
        cur.execute("BEGIN IMMEDIATE")
        ensure_ppc_authority(cur)
        existing_keys = existing_dedup_keys(cur)
        existing_ids = existing_canonical_ids(cur)
        con.commit()
    except sqlite3.Error as exc:
        _LOG.error("DB init failed: %s", exc)
        try:
            con.close()
        except sqlite3.Error:
            pass
        return 2

    # 3. Walk listings, fetch detail+PDF, write per-row transaction.
    inserted = 0
    skipped_dup_db = 0
    skipped_dup_id = 0
    skipped_no_data = 0
    breakdown_kind: dict[str, int] = {}
    breakdown_law: dict[str, int] = {}
    samples: list[dict[str, Any]] = []

    for entry in listings:
        if inserted >= max_inserts:
            _LOG.info("reached --max-inserts=%d, stopping", max_inserts)
            break

        canonical_id = build_canonical_id(
            entry.issuance_date,
            entry.title,
            entry.detail_url,
        )
        # We do not pre-check `canonical_id in existing_ids` here because in
        # multi-defendant mode the row-level canonical_id is augmented with
        # a per-defendant suffix; the dedup check happens inside the per-row
        # loop below.

        resp = http.get(entry.detail_url)
        if resp is None:
            _LOG.debug("detail fetch missing %s", entry.detail_url)
            skipped_no_data += 1
            continue
        detail = parse_detail_page(
            resp.text,
            entry.detail_url,
            http=http,
            fetch_pdf=not skip_pdf,
        )
        target_name, houjin = choose_target_name(entry, detail)

        related_law_ref = derive_law_ref(entry, detail)
        reason_summary = build_reason_summary(entry, detail)

        # Build the list of (target_name, houjin, suffix) rows to insert. For
        # single-defendant cases this is just one row; for multi-defendant
        # cases (e.g. 大手損保４社) we emit one row per named company.
        multi_targets: list[tuple[str, str | None, str]] = []
        # Always emit the title-derived primary first.
        multi_targets.append((target_name, houjin, ""))
        # Add extra defendants from PDF body when the title looks generic
        # (loss insurance, multiple companies). We use the title pattern:
        # if the title contains '及び' or '等' or starts with a category noun
        # like '損害保険会社', '一般送配電事業者', etc., the body is the source
        # of truth for company names.
        looks_multi = any(
            tok in entry.title
            for tok in (
                "及び",
                "等に対する",
                "等における",
                "事業者",
                "会社及び",
                "保険会社",
                "送配電事業者",
                "鉄道事業者",
                "業者",
                "団体",
                "共済",
                "代理店",
            )
        )
        if looks_multi and detail.extra_defendants:
            for ed_name, ed_houjin in detail.extra_defendants[:8]:
                if ed_name == target_name:
                    continue
                # Suffix for canonical_id uniqueness per defendant.
                multi_targets.append((ed_name, ed_houjin, _slugify(ed_name, 20)))

        any_inserted_this_listing = False
        for ix, (t_name, t_houjin, suffix) in enumerate(multi_targets):
            row_canonical_id = canonical_id
            if suffix:
                row_canonical_id = f"{canonical_id}:co{ix:02d}:{suffix}"[:255]
            if row_canonical_id in existing_ids:
                skipped_dup_id += 1
                continue
            row_key = (entry.issuance_date, _normalize(t_name))
            if row_key in existing_keys:
                skipped_dup_db += 1
                continue
            try:
                cur.execute("BEGIN IMMEDIATE")
                ok = insert_one(
                    cur,
                    canonical_id=row_canonical_id,
                    listing=entry,
                    detail=detail,
                    chosen_target=t_name,
                    houjin_bangou=t_houjin,
                    related_law_ref=related_law_ref,
                    reason_summary=reason_summary,
                    now_iso=now_iso,
                )
                con.commit()
            except sqlite3.IntegrityError as exc:
                _LOG.warning("integrity error for %s: %s", row_canonical_id, exc)
                try:
                    con.rollback()
                except sqlite3.Error:
                    pass
                continue
            except sqlite3.Error as exc:
                _LOG.error("DB error for %s: %s", row_canonical_id, exc)
                try:
                    con.rollback()
                except sqlite3.Error:
                    pass
                continue

            if ok:
                inserted += 1
                any_inserted_this_listing = True
                existing_keys.add(row_key)
                existing_ids.add(row_canonical_id)
                breakdown_kind[entry.kind_label] = breakdown_kind.get(entry.kind_label, 0) + 1
                top_law = (
                    detail.article_refs[0]
                    if detail.article_refs
                    else (
                        related_law_ref.split(";")[0].strip()
                        if related_law_ref
                        else "個人情報保護法"
                    )
                )
                breakdown_law[top_law] = breakdown_law.get(top_law, 0) + 1
                if len(samples) < 5:
                    samples.append(
                        {
                            "canonical_id": row_canonical_id,
                            "issuance_date": entry.issuance_date,
                            "kind_label": entry.kind_label,
                            "enforcement_kind": entry.enforcement_kind,
                            "target_name": t_name,
                            "houjin_bangou": t_houjin,
                            "related_law_ref": related_law_ref,
                            "leak_count": detail.leak_count,
                            "source_url": entry.detail_url,
                        }
                    )
                if inserted % 10 == 0:
                    _LOG.info(
                        "progress inserted=%d (target=%d) latest=%s [%s] %s",
                        inserted,
                        max_inserts,
                        entry.issuance_date,
                        entry.kind_label,
                        t_name[:30],
                    )
            else:
                skipped_dup_id += 1
            if inserted >= max_inserts:
                break

        if not any_inserted_this_listing:
            # All targets were dups — already accounted for above.
            pass

    # 4. Final summary.
    cur.execute(
        "SELECT COUNT(*) FROM am_enforcement_detail WHERE issuing_authority=?",
        ("個人情報保護委員会",),
    )
    after_ppc = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM am_enforcement_detail")
    after_total = cur.fetchone()[0]
    try:
        con.close()
    except sqlite3.Error:
        pass

    _LOG.info(
        "done inserted=%d dup_db=%d dup_id=%d no_data=%d listings=%d",
        inserted,
        skipped_dup_db,
        skipped_dup_id,
        skipped_no_data,
        len(listings),
    )
    _LOG.info(
        "post-insert: ppc_rows=%d total_am_enforcement_detail=%d",
        after_ppc,
        after_total,
    )

    print(
        json.dumps(
            {
                "inserted": inserted,
                "breakdown_by_kind_label": breakdown_kind,
                "breakdown_by_top_law_ref": breakdown_law,
                "skipped_dup_db": skipped_dup_db,
                "skipped_dup_canonical_id": skipped_dup_id,
                "skipped_no_data": skipped_no_data,
                "candidate_listings": len(listings),
                "post_ppc_total": after_ppc,
                "post_am_enforcement_detail_total": after_total,
                "samples": samples,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return inserted


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument(
        "--years",
        type=str,
        default=",".join(DEFAULT_YEARS),
        help=(
            "comma-separated FY folders (default: 2014..2026). Note these "
            "are the FY-folder names, which contain entries for the "
            "subsequent calendar year as well."
        ),
    )
    ap.add_argument(
        "--max-inserts",
        type=int,
        default=300,
        help="stop after this many fresh inserts (default 300)",
    )
    ap.add_argument(
        "--skip-pdf",
        action="store_true",
        help="do not fetch linked PDFs (faster but less accurate 法人番号 and article extraction)",
    )
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("-v", "--verbose", action="store_true")
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    years = [y.strip() for y in args.years.split(",") if y.strip()]
    inserted = run(
        args.db,
        years=years,
        max_inserts=args.max_inserts,
        skip_pdf=args.skip_pdf,
        dry_run=args.dry_run,
        verbose=args.verbose,
    )
    return 0 if (args.dry_run or inserted >= 0) else 1


if __name__ == "__main__":
    sys.exit(main())
