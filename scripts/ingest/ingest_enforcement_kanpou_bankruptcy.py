#!/usr/bin/env python3
"""Ingest 倒産・解散・特別清算・民事再生・会社更生 from 官報 (kanpo.go.jp).

Scope (2026-04-25):
    The 官報 (Official Gazette of Japan, kanpo.go.jp) publishes daily 公告
    (public notices). Court-ordered insolvency proceedings — 破産, 特別清算,
    民事再生, 会社更生 — and corporate dissolution / merger / split notices
    appear in dedicated sections of every issue:

      - 公告 諸事項 裁判所  (Court bankruptcy notices)
      - 公告 会社その他    (Corporate dissolution / merger / split / capital reduction)

    The site is open: 直近90日 of issues are freely viewable as PDF, with the
    full HTML structure at:

        https://www.kanpo.go.jp/{YYYYMMDD}/{issue_id}/{issue_id}{NNNN}f.html

    where issue_id ∈ {YYYYMMDDh##### (本紙), YYYYMMDDg##### (号外), c (政府調達), t (特別号外)}.
    The body text is in PDF only:

        https://www.kanpo.go.jp/{YYYYMMDD}/{issue_id}/pdf/{issue_id}{NNNN}.pdf

    The PDFs use embedded CID fonts. Most pages extract well via pdfplumber
    with x_tolerance=10 / y_tolerance=10. A small fraction (the heavily
    vertical-text 破産手続開始 listings) extract sparsely; we accept that
    coverage gap rather than OCR all pages — the 解散公告 / 特別清算 / 民事再生
    pages alone yield 50-200 entries per issue, easily exceeding the +500-2000
    target with a 30-90 day walk.

Source license:
    官報 (国立印刷局) — public-domain government publication. No PDL declaration
    on kanpo.go.jp itself, but the Cabinet's オープンデータ basic policy and
    国立国会図書館's interpretation place 官報 in the public domain. We attribute:
        出典: 官報 (https://www.kanpo.go.jp/)
    Aggregators (帝国データバンク, 東京商工リサーチ, 倒産速報.com) are BANNED.

Schema mapping (am_enforcement_detail.enforcement_kind enum):
    破産手続開始 / 解散公告 / 清算結了公告      → license_revoke
    特別清算開始 / 特別清算終結 / 監督命令       → contract_suspend
    民事再生手続開始 / 再生計画認可             → business_improvement
    会社更生手続開始                          → other
    合併公告 / 吸収分割公告 / 新設分割公告       → other  (corporate restructure)
    資本金の額の減少公告 / 準備金の額の減少公告  → other  (capital reduction)
    組織変更公告 / 株式交換公告 / 株式移転公告   → other

Dedup key:
    canonical_id = enforcement:kanpou:{YYYYMMDD}:{section}:{slug}:{seq}
    Plus (issuance_date, target_name, issuing_authority='官報') unique.

CLI:
    python scripts/ingest/ingest_enforcement_kanpou_bankruptcy.py
    python scripts/ingest/ingest_enforcement_kanpou_bankruptcy.py --days 30
    python scripts/ingest/ingest_enforcement_kanpou_bankruptcy.py --max-inserts 2000
    python scripts/ingest/ingest_enforcement_kanpou_bankruptcy.py --dry-run -v
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
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

try:
    import requests  # type: ignore
    from bs4 import BeautifulSoup  # type: ignore
except ImportError as exc:
    print(
        f"missing dep: {exc}. pip install requests beautifulsoup4",
        file=sys.stderr,
    )
    sys.exit(1)

try:
    import pdfplumber  # type: ignore
    _HAVE_PDFPLUMBER = True
except ImportError:
    _HAVE_PDFPLUMBER = False

_LOG = logging.getLogger("autonomath.ingest_kanpou")

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_DB = REPO_ROOT / "autonomath.db"

USER_AGENT = (
    "AutonoMath/0.1.0 (+https://bookyou.net) "
    "ingest-kanpou-bankruptcy (contact=ops@autonomath.ai)"
)
BASE = "https://www.kanpo.go.jp"
HTTP_TIMEOUT = 60
RATE_SLEEP = 0.6  # be polite to NPB infra


# ---------------------------------------------------------------------------
# Section classification
# ---------------------------------------------------------------------------

# Section heading → (canonical label, enforcement_kind, law basis)
SECTION_MAP: dict[str, tuple[str, str, str]] = {
    # --- 裁判所 court bankruptcy ---
    "破産手続開始":           ("破産手続開始決定",   "license_revoke",      "破産法第30条"),
    "破産手続廃止":           ("破産手続廃止決定",   "license_revoke",      "破産法第217条"),
    "破産手続終結":           ("破産手続終結決定",   "license_revoke",      "破産法第220条"),
    "破産手続終結及び免責許可決定": ("破産手続終結決定", "license_revoke",  "破産法第220条"),
    "破産債権の届出期間":     ("破産債権届出期間",   "license_revoke",      "破産法第31条"),
    # 特別清算
    "特別清算開始":           ("特別清算開始命令",   "contract_suspend",    "会社法第511条"),
    "特別清算終結":           ("特別清算終結決定",   "contract_suspend",    "会社法第573条"),
    "特別清算協定認可":       ("特別清算協定認可",   "contract_suspend",    "会社法第569条"),
    "監督命令":               ("監督命令",          "contract_suspend",    "会社法第522条"),
    "監督命令取消":           ("監督命令取消",       "contract_suspend",    "会社法第522条"),
    # 民事再生
    "再生手続開始":           ("民事再生手続開始決定", "business_improvement", "民事再生法第33条"),
    "再生手続終結":           ("民事再生手続終結決定", "business_improvement", "民事再生法第188条"),
    "再生計画認可":           ("民事再生計画認可決定", "business_improvement", "民事再生法第174条"),
    "再生計画取消":           ("民事再生計画取消決定", "business_improvement", "民事再生法第189条"),
    "再生債権":               ("民事再生債権",       "business_improvement", "民事再生法第94条"),
    "小規模個人再生":         ("小規模個人再生手続開始", "business_improvement", "民事再生法第221条"),
    "給与所得者等再生":       ("給与所得者等再生手続開始", "business_improvement", "民事再生法第239条"),
    # 会社更生
    "会社更生手続開始":       ("会社更生手続開始決定", "other",            "会社更生法第41条"),
    "会社更生計画認可":       ("会社更生計画認可決定", "other",            "会社更生法第199条"),
    # --- 会社その他 corporate notices ---
    "解散公告":               ("解散公告",           "license_revoke",      "会社法第471条"),
    "清算結了公告":           ("清算結了公告",       "license_revoke",      "会社法第507条"),
    "合併公告":               ("合併公告",           "other",            "会社法第789条"),
    "吸収分割公告":           ("吸収分割公告",       "other",            "会社法第789条"),
    "新設分割公告":           ("新設分割公告",       "other",            "会社法第810条"),
    "株式交換公告":           ("株式交換公告",       "other",            "会社法第789条"),
    "株式移転公告":           ("株式移転公告",       "other",            "会社法第810条"),
    "組織変更公告":           ("組織変更公告",       "other",            "会社法第779条"),
    "事業譲渡公告":           ("事業譲渡公告",       "other",            "会社法第467条"),
    "資本金の額の減少公告":   ("資本金減少公告",     "other",            "会社法第449条"),
    "優先資本金の額の減少公告": ("優先資本金減少公告", "other",          "資産流動化法第109条"),
    "準備金の額の減少公告":   ("準備金減少公告",     "other",            "会社法第449条"),
    "資本準備金の額の減少公告": ("資本準備金減少公告", "other",          "会社法第449条"),
    "債権申出の催告":         ("債権申出の催告",     "other",            "確定給付企業年金法第83条"),
    "債権申出の公告":         ("債権申出の公告",     "other",            "確定給付企業年金法第83条"),
}

# Compiled section regex (longest first to prefer specific matches)
_SECTION_TOKENS = sorted(SECTION_MAP.keys(), key=len, reverse=True)
SECTION_RE = re.compile(r"(?P<section>" + "|".join(re.escape(t) for t in _SECTION_TOKENS) + r")")

# Patterns
WAREKI_RE = re.compile(
    r"令和\s*([0-9０-９元一二三四五六七八九十百〇]+)\s*年\s*"
    r"([0-9０-９一二三四五六七八九十〇]+)\s*月\s*"
    r"([0-9０-９一二三四五六七八九十〇]+)\s*日"
)
SEIREKI_RE = re.compile(
    r"([0-9０-９]{4})\s*年\s*([0-9０-９]{1,2})\s*月\s*([0-9０-９]{1,2})\s*日"
)
# Court name regex e.g. "東京地方裁判所民事第２０部" / "大阪地方裁判所第６民事部"
COURT_RE = re.compile(
    r"(?:[一-鿿々]{2,8})\s*(?:地方|高等|簡易|家庭)?裁判所"
    r"(?:\s*[一-鿿々]{1,4}支部)?"
    r"(?:\s*(?:民事|商事|破産|執行|再生)?第?[0-9０-９一二三四五六七八九十〇]{1,3}部)?"
)
# 法人 名 capture - must end in a recognized 法人 suffix
COMPANY_SUFFIXES = (
    "株式会社", "有限会社", "合同会社", "合資会社", "合名会社",
    "一般社団法人", "公益社団法人", "一般財団法人", "公益財団法人",
    "社団法人", "財団法人", "医療法人", "学校法人", "社会福祉法人",
    "宗教法人", "独立行政法人", "国立大学法人", "公立大学法人",
    "事業協同組合", "農業協同組合", "信用組合", "信用金庫",
    "特定目的会社", "投資法人",
)
# Case number: 令和X年（フ/ヒ/ヲ/ホ/ハ）第NNN号
CASE_RE = re.compile(
    r"令和\s*([0-9０-９元一二三四五六七八九十〇]+)\s*年\s*"
    r"[\(（]\s*([フヒヲホハミ再]+)\s*[\)）]\s*第\s*([0-9０-９,，]+)\s*号"
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "")
    return re.sub(r"[\s　]+", " ", text).strip()


_KANJI_DIGITS = {
    "〇": 0, "零": 0,
    "一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
    "六": 6, "七": 7, "八": 8, "九": 9,
    "十": 10, "百": 100, "千": 1000,
}


def _parse_kanji_int(s: str) -> int | None:
    """Parse Japanese kanji or arabic number string to int."""
    s = unicodedata.normalize("NFKC", s).strip()
    if not s:
        return None
    if s == "元":
        return 1
    if s.isdigit():
        return int(s)
    # Kanji digits
    val = 0
    section = 0
    for ch in s:
        if ch.isdigit():
            section = section * 10 + int(ch)
            continue
        d = _KANJI_DIGITS.get(ch)
        if d is None:
            return None
        if d >= 10:
            section = max(section, 1) * d
            val += section
            section = 0
        else:
            section = section * 10 + d
    val += section
    return val if val > 0 else None


def _wareki_to_iso(text: str) -> str | None:
    """Convert 令和X年Y月Z日 (mixed kanji+arabic) → ISO yyyy-mm-dd."""
    if not text:
        return None
    text = unicodedata.normalize("NFKC", text)
    m = WAREKI_RE.search(text)
    if m:
        yr = _parse_kanji_int(m.group(1))
        mo = _parse_kanji_int(m.group(2))
        dy = _parse_kanji_int(m.group(3))
        if yr and mo and dy and 1 <= mo <= 12 and 1 <= dy <= 31:
            year = 2018 + yr  # 令和元年 = 2019
            try:
                return f"{year:04d}-{mo:02d}-{dy:02d}"
            except ValueError:
                return None
    m = SEIREKI_RE.search(text)
    if m:
        try:
            return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
        except ValueError:
            return None
    return None


def _slugify(text: str, max_len: int = 40) -> str:
    text = unicodedata.normalize("NFKC", text or "")
    text = re.sub(r"\s+", "-", text)
    text = re.sub(r"[^0-9A-Za-z_\-぀-ヿ一-鿿々]", "", text)
    return text[:max_len] or "x"


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
                    url, timeout=HTTP_TIMEOUT, allow_redirects=True,
                )
                self._last = time.monotonic()
                if resp.status_code == 200:
                    return resp
                if resp.status_code in (404, 410):
                    return None
                last_err = RuntimeError(f"{resp.status_code} for {url}")
            except requests.RequestException as exc:
                last_err = exc
            time.sleep(2 ** attempt)
        _LOG.debug("fetch failed after retries: %s: %s", url, last_err)
        return None

    def get_bytes(self, url: str) -> bytes | None:
        self._wait()
        for attempt in range(3):
            try:
                resp = self.session.get(
                    url, timeout=HTTP_TIMEOUT, allow_redirects=True,
                )
                self._last = time.monotonic()
                if resp.status_code == 200:
                    return resp.content
                if resp.status_code in (404, 410):
                    return None
            except requests.RequestException:
                pass
            time.sleep(2 ** attempt)
        return None


# ---------------------------------------------------------------------------
# Issue discovery
# ---------------------------------------------------------------------------


@dataclass
class Issue:
    date: str       # YYYYMMDD
    issue_id: str   # e.g. 20260424h01694 or 20260424g00096
    kind: str       # 'h' (本紙), 'g' (号外), 'c' (政府調達), 't' (特別号外)
    page_count: int = 0


def discover_issues(http: HttpClient, days: int) -> list[Issue]:
    """Walk kanpo.go.jp homepage + archive index for recent issues.

    Strategy: kanpo.go.jp shows the most recent ~90 days on its homepage. For
    deeper archives the site expects you to know the date+id. We collect all
    issue IDs from the homepage HTML, then optionally extend by walking
    backward by date.
    """
    out: list[Issue] = []
    # Step 1: scrape homepage for visible issues
    home = http.get(BASE + "/")
    if not home:
        _LOG.error("failed to fetch kanpo.go.jp homepage")
        return out
    # Extract YYYYMMDD/<issue_id> patterns
    issue_re = re.compile(
        r'href="\.\/(?P<date>20\d{6})/(?P<id>20\d{6}[hgct]\d+)/'
    )
    seen: set[str] = set()
    for m in issue_re.finditer(home.text):
        iid = m.group("id")
        if iid in seen:
            continue
        seen.add(iid)
        out.append(Issue(date=m.group("date"), issue_id=iid, kind=iid[8]))
    _LOG.info("found %d issues on homepage", len(out))
    # Filter by days
    cutoff = (datetime.now(tz=UTC) - timedelta(days=days)).strftime("%Y%m%d")
    out = [i for i in out if i.date >= cutoff]
    _LOG.info("filtered to %d issues within last %d days", len(out), days)
    # Sort newest first
    out.sort(key=lambda i: (i.date, i.issue_id), reverse=True)
    return out


def fetch_page_count(http: HttpClient, issue: Issue) -> int:
    """Fetch the TOC page of an issue and parse total page count."""
    toc_url = f"{BASE}/{issue.date}/{issue.issue_id}/{issue.issue_id}0000f.html"
    resp = http.get(toc_url)
    if not resp:
        return 0
    m = re.search(r'class="pageAll"[^>]*>(\d+)<', resp.text)
    if m:
        return int(m.group(1))
    return 0


def candidate_court_pages(issue: Issue, page_count: int) -> list[int]:
    """Heuristic: which pages are likely to contain bankruptcy/company notices?

    For 本紙 (h): pages 8-32 typically (court + company)
    For 号外 (g): variable — solely a special edition, all pages may be
                 解散公告. We walk all pages.
    For 政府調達 (c) / 特別号外 (t): unlikely to contain bankruptcy notices.
    """
    if page_count <= 0:
        return []
    if issue.kind == "c":
        return []  # procurement only
    if issue.kind == "t":
        return []  # special editions, mostly tax/laws
    if issue.kind == "g":
        # 号外 — walk all pages
        return list(range(1, page_count + 1))
    # 本紙: middle and last sections
    start = max(1, min(8, page_count))
    return list(range(start, page_count + 1))


# ---------------------------------------------------------------------------
# PDF text extraction
# ---------------------------------------------------------------------------


def extract_page_text(pdf_bytes: bytes) -> str:
    """Extract text from a single-page kanpo PDF.

    The kanpo PDFs are vertical-text Japanese; pdfplumber's layout-aware text
    extraction with x_tolerance=10 / y_tolerance=10 gives good results for
    most pages. A fraction of pages embed CID-only fonts; for those we get
    very little text and accept the gap.
    """
    if not _HAVE_PDFPLUMBER:
        return ""
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            chunks: list[str] = []
            for page in pdf.pages:
                try:
                    t = page.extract_text(x_tolerance=10, y_tolerance=10) or ""
                except Exception:
                    t = ""
                if t:
                    chunks.append(t)
            return "\n".join(chunks)
    except Exception as exc:
        _LOG.debug("pdf parse failed: %s", exc)
        return ""


# ---------------------------------------------------------------------------
# Record extraction
# ---------------------------------------------------------------------------


@dataclass
class Record:
    issue_date: str          # ISO yyyy-mm-dd (掲載日)
    issue_id: str            # 20260424h01694 etc.
    page_no: int
    section: str             # canonical Japanese section label
    enforcement_kind: str    # mapped enum
    law_basis: str           # law article string
    target_name: str         # 法人名
    address: str | None      # 本店所在地
    decision_date: str | None  # 決定年月日 ISO
    case_number: str | None  # 令和X年（ヒ）第NNN号
    court: str | None        # 裁判所名
    representative: str | None  # 代表者
    raw_excerpt: str         # 200-1000 char excerpt
    source_url: str          # PDF URL
    source_page_url: str     # HTML detail URL
    source_topic: str        # e.g. 'kanpou_court' / 'kanpou_company'

    def slug(self) -> str:
        return _slugify(f"{self.section}-{self.target_name}", 32)


def _find_company_in_window(window: str) -> tuple[str | None, str | None]:
    """Find first 法人名 in a text window, return (name, address_hint).

    Look for any company name ending in a 法人 suffix from COMPANY_SUFFIXES.
    """
    # Try patterns like "（甲）会社名" / "（乙）会社名" / "債務者 会社名" /
    # "清算株式会社 会社名" / bare name.
    suffixes_alt = "|".join(re.escape(s) for s in COMPANY_SUFFIXES)
    # A: name + suffix at end
    pattern_a = re.compile(
        r"(?P<name>[一-鿿々ぁ-ゖァ-ヺー〇A-Za-zＡ-Ｚａ-ｚ0-9０-９・\-－&'’＆.\.,，、]{1,40}?(?:" + suffixes_alt + r"))"
    )
    # B: 株式会社 + name (株式会社が前置き)
    pattern_b = re.compile(
        r"(?P<name>株式会社[一-鿿々ぁ-ゖァ-ヺー〇A-Za-zＡ-Ｚａ-ｚ0-9０-９・\-－&'’＆.\.,，、]{1,40})"
    )
    # Try B first (higher specificity for 株式会社X form)
    found: list[tuple[int, str]] = []
    for m in pattern_b.finditer(window):
        found.append((m.start(), m.group("name")))
    for m in pattern_a.finditer(window):
        found.append((m.start(), m.group("name")))
    if not found:
        return None, None
    found.sort(key=lambda x: x[0])
    name = found[0][1].strip()
    # Address hint: text right after name
    rest = window[found[0][0] + len(name): found[0][0] + len(name) + 200]
    addr_m = re.search(
        r"((?:[一-鿿々]{2,4}(?:都|道|府|県))[一-鿿々ぁ-ゖァ-ヺー0-9０-９\-\s　A-Za-z丁目番地号]{4,80})",
        rest,
    )
    addr = addr_m.group(1).strip() if addr_m else None
    return name[:255], addr[:255] if addr else None


def _find_address(text: str) -> str | None:
    """Extract first Japanese address from a chunk."""
    m = re.search(
        r"((?:北海道|東京都|京都府|大阪府|[一-鿿]{2,3}県)"
        r"[一-鿿々ぁ-ゖァ-ヺー0-9０-９\-\.\s　A-Za-z丁目番地号Ⅰ-ⅩⅠ-Ⅹ]{3,80})",
        text,
    )
    return m.group(1).strip() if m else None


def _find_court(text: str) -> str | None:
    m = COURT_RE.search(text)
    return m.group(0).strip() if m else None


def _find_case_number(text: str) -> str | None:
    m = CASE_RE.search(text)
    if not m:
        return None
    return m.group(0).strip()


def _find_decision_date(text: str) -> str | None:
    """Find '決定年月日 令和X年Y月Z日' first, else any 令和 date in window."""
    m = re.search(r"決定年月日(?:時)?\s*[:：]?\s*(令和[^\n。、]{2,20})", text)
    if m:
        d = _wareki_to_iso(m.group(1))
        if d:
            return d
    return _wareki_to_iso(text)


def _find_representative(text: str) -> str | None:
    m = re.search(
        r"(?:代表取締役|代表清算人|代表社員|代表理事|理事長|清算人|破産管財人|"
        r"監督委員|管財人|代表執行役|代表者)\s*"
        r"(?:[一-鿿々]{1,8}\s*[一-鿿々ぁ-ゖァ-ヺー]{1,8})",
        text,
    )
    return m.group(0).strip()[:60] if m else None


def split_records_by_section(text: str) -> list[tuple[str, int, int]]:
    """Return list of (section, start_idx, end_idx) — chunks of text per record.

    The kanpo PDFs put each record bounded by a section heading and the next
    section heading or the page top/bottom. We walk SECTION_RE finditer and
    use the position of the next match as the end of the current chunk.
    """
    matches = list(SECTION_RE.finditer(text))
    out: list[tuple[str, int, int]] = []
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        # Each section heading is a record boundary; the body text BEFORE the
        # heading is the relevant content (vertical text reads bottom-up in
        # extracted form). So we take a window ~1500 chars before the next
        # section start (or until prior section end).
        out.append((m.group("section"), start, min(end, start + 1500)))
    return out


def extract_records(
    text: str,
    *,
    issue: Issue,
    page_no: int,
    issue_date_iso: str,
) -> list[Record]:
    """Parse all bankruptcy/dissolution/restructure records from a page."""
    text = _normalize(text)
    if len(text) < 80:
        return []
    chunks = split_records_by_section(text)
    out: list[Record] = []
    for i, (sec_token, start, end) in enumerate(chunks):
        if sec_token not in SECTION_MAP:
            continue
        canonical_section, enf_kind, law_basis = SECTION_MAP[sec_token]
        # Look for the company name in the body that follows this section
        # heading. The body extends from the next section back to the section
        # token. We look at the prev_window (text BEFORE the section heading)
        # because vertical-extracted text often puts the company info before
        # the section label.
        prev_start = chunks[i - 1][2] if i > 0 else 0
        body = text[prev_start:end]
        name, addr_hint = _find_company_in_window(body)
        if not name:
            continue
        # Skip generic words mistakenly captured
        if len(name) < 4 or name in ("株式会社", "有限会社", "合同会社"):
            continue
        # More fields
        addr = addr_hint or _find_address(body)
        decision_date = _find_decision_date(body)
        case_no = _find_case_number(body)
        court = _find_court(body)
        rep = _find_representative(body)
        # Best date: decision_date (if any) else issue_date
        eff_date = decision_date or issue_date_iso
        # Excerpt
        excerpt = body[:400].strip()
        # Determine source_topic
        if any(token in sec_token for token in ("公告", "減少公告")) and "裁判所" not in body:
            topic = "kanpou_company"
        else:
            topic = "kanpou_court"
        # Build URLs
        pdf_url = (
            f"{BASE}/{issue.date}/{issue.issue_id}/pdf/"
            f"{issue.issue_id}{page_no:04d}.pdf"
        )
        page_url = (
            f"{BASE}/{issue.date}/{issue.issue_id}/"
            f"{issue.issue_id}{page_no:04d}f.html"
        )
        out.append(Record(
            issue_date=issue_date_iso,
            issue_id=issue.issue_id,
            page_no=page_no,
            section=canonical_section,
            enforcement_kind=enf_kind,
            law_basis=law_basis,
            target_name=name,
            address=addr,
            decision_date=eff_date,
            case_number=case_no,
            court=court,
            representative=rep,
            raw_excerpt=excerpt,
            source_url=pdf_url,
            source_page_url=page_url,
            source_topic=topic,
        ))
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


def ensure_kanpou_authority(cur: sqlite3.Cursor) -> str:
    cur.execute(
        "SELECT canonical_id FROM am_authority WHERE canonical_id=?",
        ("authority:kanpou",),
    )
    if cur.fetchone():
        return "authority:kanpou"
    cur.execute(
        """INSERT INTO am_authority
               (canonical_id, canonical_name, canonical_en, level, website)
           VALUES (?, ?, ?, ?, ?)""",
        (
            "authority:kanpou",
            "官報 (国立印刷局)",
            "Official Gazette of Japan",
            "incorp_admin_agency",
            "https://www.kanpo.go.jp/",
        ),
    )
    return "authority:kanpou"


def existing_dedup_keys(cur: sqlite3.Cursor) -> set[tuple[str, str, str]]:
    cur.execute(
        "SELECT issuance_date, target_name, related_law_ref "
        "FROM am_enforcement_detail WHERE issuing_authority=?",
        ("官報",),
    )
    out: set[tuple[str, str, str]] = set()
    for d, n, r in cur.fetchall():
        if d and n:
            out.add((d, _normalize(n), (r or "")[:60]))
    return out


def existing_canonical_ids(cur: sqlite3.Cursor) -> set[str]:
    cur.execute(
        "SELECT canonical_id FROM am_entities WHERE record_kind='enforcement' "
        "AND authority_canonical=?",
        ("authority:kanpou",),
    )
    return {row[0] for row in cur.fetchall()}


def build_canonical_id(rec: Record, seq: int) -> str:
    base = (
        f"enforcement:kanpou:{rec.issue_date.replace('-', '')}:"
        f"{rec.issue_id}:{rec.section}:{rec.slug()}:{seq:03d}"
    )
    return base[:255]


def insert_one(
    cur: sqlite3.Cursor,
    *,
    canonical_id: str,
    rec: Record,
    now_iso: str,
) -> bool:
    raw = {
        "source": "kanpou:npb_go_jp",
        "issue_id": rec.issue_id,
        "page_no": rec.page_no,
        "section": rec.section,
        "enforcement_kind": rec.enforcement_kind,
        "law_basis": rec.law_basis,
        "target_name": rec.target_name,
        "address": rec.address,
        "decision_date": rec.decision_date,
        "case_number": rec.case_number,
        "court": rec.court,
        "representative": rec.representative,
        "issue_date": rec.issue_date,
        "issuing_authority": "官報",
        "authority_canonical": "authority:kanpou",
        "license": "public_domain (gov publication)",
        "attribution": "出典: 官報 (https://www.kanpo.go.jp/)",
        "source_url": rec.source_url,
        "source_page_url": rec.source_page_url,
        "fetched_at": now_iso,
        "raw_excerpt": rec.raw_excerpt,
    }
    cur.execute(
        """INSERT OR IGNORE INTO am_entities
               (canonical_id, record_kind, source_topic, source_record_index,
                primary_name, authority_canonical, confidence, source_url,
                source_url_domain, fetched_at, raw_json,
                canonical_status, citation_status)
           VALUES (?, 'enforcement', ?, NULL, ?, 'authority:kanpou', ?, ?, ?, ?,
                   ?, 'active', 'ok')""",
        (
            canonical_id,
            rec.source_topic,
            rec.target_name[:255],
            0.85,
            rec.source_url,
            "kanpo.go.jp",
            now_iso,
            json.dumps(raw, ensure_ascii=False),
        ),
    )
    if cur.rowcount == 0:
        return False
    # The reason_summary: combine section + court + decision date + case number
    summary_parts = [f"[{rec.section}]"]
    if rec.case_number:
        summary_parts.append(f"事件番号: {rec.case_number}")
    if rec.court:
        summary_parts.append(f"裁判所: {rec.court}")
    if rec.address:
        summary_parts.append(f"所在地: {rec.address}")
    if rec.representative:
        summary_parts.append(rec.representative)
    summary_parts.append(rec.raw_excerpt[:200])
    summary = " / ".join(summary_parts)[:2000]
    issuance_authority = rec.court if rec.court else "官報"
    cur.execute(
        """INSERT INTO am_enforcement_detail
               (entity_id, houjin_bangou, target_name, enforcement_kind,
                issuing_authority, issuance_date, reason_summary,
                related_law_ref, amount_yen, source_url, source_fetched_at)
           VALUES (?, NULL, ?, ?, ?, ?, ?, ?, NULL, ?, ?)""",
        (
            canonical_id,
            rec.target_name[:255],
            rec.enforcement_kind,
            issuance_authority[:100] if issuance_authority else "官報",
            rec.decision_date or rec.issue_date,
            summary,
            rec.law_basis[:255],
            rec.source_url,
            now_iso,
        ),
    )
    return True


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


def process_issue(
    http: HttpClient,
    issue: Issue,
) -> list[Record]:
    """Fetch all candidate pages of an issue and return parsed records."""
    if not issue.page_count:
        issue.page_count = fetch_page_count(http, issue)
    if issue.page_count <= 0:
        _LOG.debug("no page count for %s", issue.issue_id)
        return []
    pages = candidate_court_pages(issue, issue.page_count)
    if not pages:
        return []
    issue_date_iso = (
        f"{issue.date[:4]}-{issue.date[4:6]}-{issue.date[6:]}"
    )
    records: list[Record] = []
    for p in pages:
        pdf_url = (
            f"{BASE}/{issue.date}/{issue.issue_id}/pdf/"
            f"{issue.issue_id}{p:04d}.pdf"
        )
        pdf_bytes = http.get_bytes(pdf_url)
        if not pdf_bytes:
            continue
        text = extract_page_text(pdf_bytes)
        if len(text) < 100:
            continue  # CID-only page, skip
        page_records = extract_records(
            text, issue=issue, page_no=p, issue_date_iso=issue_date_iso,
        )
        records.extend(page_records)
    _LOG.info(
        "[issue] %s/%s -> %d records (pages=%d)",
        issue.date, issue.issue_id, len(records), len(pages),
    )
    return records


def run(
    db_path: Path,
    *,
    days: int,
    max_inserts: int,
    dry_run: bool,
    verbose: bool,
) -> int:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    for noisy in ("pdfminer", "pdfplumber", "urllib3", "requests"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    now_iso = (
        datetime.now(tz=UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
    )

    http = HttpClient()

    # 1. Discover issues
    issues = discover_issues(http, days=days)
    if not issues:
        _LOG.error("no issues discovered")
        return 1

    if dry_run:
        # Process up to 2 issues for dry-run preview
        preview_records: list[Record] = []
        for issue in issues[:2]:
            preview_records.extend(process_issue(http, issue))
            if len(preview_records) >= 50:
                break
        sec_count: dict[str, int] = {}
        for r in preview_records:
            sec_count[r.section] = sec_count.get(r.section, 0) + 1
        print(json.dumps({
            "dry_run": True,
            "issues_discovered": len(issues),
            "preview_records": len(preview_records),
            "by_section": sec_count,
            "samples": [
                {
                    "section": r.section,
                    "target_name": r.target_name,
                    "decision_date": r.decision_date,
                    "case_number": r.case_number,
                    "court": r.court,
                    "law_basis": r.law_basis,
                    "issue_id": r.issue_id,
                }
                for r in preview_records[:10]
            ],
        }, ensure_ascii=False, indent=2))
        return 0

    # 2. Open DB
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
        ensure_kanpou_authority(cur)
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

    # 3. Walk issues, parse pages, insert per-record
    inserted = 0
    skipped_dup_db = 0
    skipped_dup_id = 0
    breakdown_kind: dict[str, int] = {}
    breakdown_section: dict[str, int] = {}
    breakdown_court: dict[str, int] = {}
    samples: list[dict[str, Any]] = []

    seq_per_section: dict[str, int] = {}

    try:
        for issue in issues:
            if inserted >= max_inserts:
                _LOG.info(
                    "reached --max-inserts=%d, stopping", max_inserts,
                )
                break
            try:
                records = process_issue(http, issue)
            except Exception as exc:
                _LOG.warning("process_issue %s failed: %s", issue.issue_id, exc)
                continue
            for rec in records:
                if inserted >= max_inserts:
                    break
                # Build canonical_id with seq counter scoped per (issue, section)
                seq_key = f"{issue.issue_id}:{rec.section}"
                seq = seq_per_section.get(seq_key, 0)
                seq_per_section[seq_key] = seq + 1
                canonical_id = build_canonical_id(rec, seq)
                if canonical_id in existing_ids:
                    skipped_dup_id += 1
                    continue
                key = (
                    rec.decision_date or rec.issue_date,
                    _normalize(rec.target_name),
                    rec.law_basis[:60],
                )
                if key in existing_keys:
                    skipped_dup_db += 1
                    continue
                try:
                    cur.execute("BEGIN IMMEDIATE")
                    ok = insert_one(
                        cur,
                        canonical_id=canonical_id,
                        rec=rec,
                        now_iso=now_iso,
                    )
                    con.commit()
                except sqlite3.IntegrityError as exc:
                    _LOG.debug("integrity error: %s", exc)
                    try:
                        con.rollback()
                    except sqlite3.Error:
                        pass
                    continue
                except sqlite3.Error as exc:
                    _LOG.error("DB error: %s", exc)
                    try:
                        con.rollback()
                    except sqlite3.Error:
                        pass
                    continue
                if ok:
                    inserted += 1
                    existing_ids.add(canonical_id)
                    existing_keys.add(key)
                    breakdown_kind[rec.enforcement_kind] = (
                        breakdown_kind.get(rec.enforcement_kind, 0) + 1
                    )
                    breakdown_section[rec.section] = (
                        breakdown_section.get(rec.section, 0) + 1
                    )
                    if rec.court:
                        breakdown_court[rec.court] = (
                            breakdown_court.get(rec.court, 0) + 1
                        )
                    if len(samples) < 8:
                        samples.append({
                            "canonical_id": canonical_id,
                            "section": rec.section,
                            "target_name": rec.target_name,
                            "decision_date": rec.decision_date,
                            "case_number": rec.case_number,
                            "court": rec.court,
                            "law_basis": rec.law_basis,
                            "address": rec.address,
                        })
                    if inserted % 25 == 0:
                        _LOG.info(
                            "progress inserted=%d (target=%d) latest=%s [%s] %s",
                            inserted, max_inserts,
                            rec.decision_date or rec.issue_date,
                            rec.section, rec.target_name[:30],
                        )
    finally:
        # Ensure final state queried even on early exit
        try:
            cur.execute(
                "SELECT COUNT(*) FROM am_enforcement_detail WHERE issuing_authority LIKE '官報%' OR source_url LIKE '%kanpo.go.jp%' OR related_law_ref LIKE '%破産%' OR related_law_ref LIKE '%清算%' OR related_law_ref LIKE '%再生%' OR related_law_ref LIKE '%更生%'"
            )
            after_kanpou = cur.fetchone()[0]
        except sqlite3.Error:
            after_kanpou = -1
        try:
            cur.execute("SELECT COUNT(*) FROM am_enforcement_detail")
            after_total = cur.fetchone()[0]
        except sqlite3.Error:
            after_total = -1
        try:
            con.close()
        except sqlite3.Error:
            pass

    _LOG.info(
        "done inserted=%d dup_db=%d dup_id=%d issues=%d",
        inserted, skipped_dup_db, skipped_dup_id, len(issues),
    )
    _LOG.info(
        "post-insert: kanpou_or_bankruptcy_rows=%d total_am_enforcement_detail=%d",
        after_kanpou, after_total,
    )

    print(json.dumps({
        "inserted": inserted,
        "breakdown_by_enforcement_kind": breakdown_kind,
        "breakdown_by_section": breakdown_section,
        "breakdown_by_court_top10": dict(
            sorted(breakdown_court.items(), key=lambda x: x[1], reverse=True)[:10]
        ),
        "skipped_dup_db": skipped_dup_db,
        "skipped_dup_canonical_id": skipped_dup_id,
        "issues_processed": len(issues),
        "post_kanpou_or_bankruptcy_rows": after_kanpou,
        "post_am_enforcement_detail_total": after_total,
        "samples": samples,
    }, ensure_ascii=False, indent=2))
    return inserted


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument(
        "--days", type=int, default=90,
        help="walk daily issues from the last N days (default 90)",
    )
    ap.add_argument(
        "--max-inserts", type=int, default=2500,
        help="stop after this many fresh inserts (default 2500)",
    )
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("-v", "--verbose", action="store_true")
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    inserted = run(
        args.db,
        days=args.days,
        max_inserts=args.max_inserts,
        dry_run=args.dry_run,
        verbose=args.verbose,
    )
    return 0 if (args.dry_run or inserted >= 0) else 1


if __name__ == "__main__":
    sys.exit(main())
