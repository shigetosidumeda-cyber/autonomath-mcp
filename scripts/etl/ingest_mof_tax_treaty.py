#!/usr/bin/env python3
"""MOF (財務省) 租税条約 PDF ingester for am_tax_treaty.

Scope
-----
* Walks the MOF 租税条約一覧 page
  (`https://www.mof.go.jp/tax_policy/summary/international/tax_convention/`)
* Extracts per-country PDF / 国別概要 PDF links
* For each country: downloads PDF, extracts text via pypdf, regex-parses
  the canonical articles:

    * 第10条 配当 → wht_dividend_pct (一般) + wht_dividend_parent_pct (親子間)
    * 第11条 利子 → wht_interest_pct
    * 第12条 使用料 → wht_royalty_pct
    * 第5条 PE 認定基準 → pe_days_threshold (建設 PE / サービス PE 日数)
    * 署名日 / 効力発生日 → dta_signed_date / dta_in_force_date

* `INSERT ... ON CONFLICT(country_iso) DO UPDATE SET ...` against
  `am_tax_treaty` in `autonomath.db`.

Constraints (per CLAUDE.md + memory)
------------------------------------
* No LLM API. PDF parse = pypdf + regex. Country code resolution = ISO 3166-1
  alpha-2 lookup table (hand-curated from MOF's国別 list).
* Primary source only: every `source_url` points to MOF /tax_convention/.
* `license = 'gov_standard'` (政府標準利用規約 v2.0) on every row.
* UA = `jpcite-research/1.0`, 1 req/sec/host throttle (matches
  `ingest_jfc_loan_scaffold.py` etiquette).
* Idempotent — re-runs upsert; safe to re-invoke.

Run
---
Smoke (parser test against the 5-country built-in fixture, NO net)::

    python scripts/etl/ingest_mof_tax_treaty.py --smoke

Online (full 80-country walk, writes to autonomath.db)::

    python scripts/etl/ingest_mof_tax_treaty.py [--limit N] [--countries US,GB,SG]
        [--db /path/to/autonomath.db] [--dry-run]

`--smoke` populates 5 anchor rows (US/GB/CN/KR/SG) from a built-in fixture
that exercises the regex parser on a synthetic article block — guarantees
the parser code path runs in CI even without network. The fixture rates
match the values seeded by migrations 091 + 125 so smoke + live converge.

`--countries` restricts the walk to the listed ISO codes (comma-separated)
for partial / iterative runs.

The script writes a JSONL log at `data/mof_treaty_ingest_log.jsonl`
(one line per country processed, with parsed values + source_url + sha256
of PDF body). Failures are logged with `status='error'` so retries can
target only the failed countries on the next invocation.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import logging
import re
import sqlite3
import ssl
import sys
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

try:
    import certifi  # type: ignore[import-not-found]

    _SSL_CTX: ssl.SSLContext | None = ssl.create_default_context(cafile=certifi.where())
except ImportError:  # pragma: no cover
    _SSL_CTX = None

try:
    import pypdf  # type: ignore[import-not-found]
except ImportError as exc:  # pragma: no cover
    print(f"missing dep: {exc}. pip install pypdf", file=sys.stderr)
    raise SystemExit(1) from exc


# ---------------------------------------------------------------------------
# config
# ---------------------------------------------------------------------------

USER_AGENT = "jpcite-research/1.0 (+https://jpcite.com/about)"
HTTP_TIMEOUT_S = 30
PER_HOST_MIN_INTERVAL_S = 1.0  # 1 req/sec/host

MOF_INDEX_URL = (
    "https://www.mof.go.jp/tax_policy/summary/international/tax_convention/"
    "tax_convetion_list_jp.html"
)
# Canonical fallback (doc-store) — the index page links into here.
MOF_PDF_BASE = "https://www.mof.go.jp/tax_policy/summary/international/tax_convention/"

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_DEFAULT_DB = _REPO_ROOT / "autonomath.db"
_LOG_FILE = _REPO_ROOT / "data" / "mof_treaty_ingest_log.jsonl"

_LOG = logging.getLogger("autonomath.etl.mof_tax_treaty")


# ---------------------------------------------------------------------------
# country code lookup (ISO 3166-1 alpha-2 ↔ JA/EN names)
# Hand-curated from MOF's一覧 — covers the 80-country target.
# ---------------------------------------------------------------------------

# Format: ja_name → (iso_alpha2, en_name)
COUNTRY_LOOKUP: dict[str, tuple[str, str]] = {
    "アイスランド": ("IS", "Iceland"),
    "アイルランド": ("IE", "Ireland"),
    "アゼルバイジャン": ("AZ", "Azerbaijan"),
    "アメリカ合衆国": ("US", "United States"),
    "アラブ首長国連邦": ("AE", "United Arab Emirates"),
    "アルジェリア": ("DZ", "Algeria"),
    "アルゼンチン": ("AR", "Argentina"),
    "アルメニア": ("AM", "Armenia"),
    "イスラエル": ("IL", "Israel"),
    "イタリア": ("IT", "Italy"),
    "インド": ("IN", "India"),
    "インドネシア": ("ID", "Indonesia"),
    "ウクライナ": ("UA", "Ukraine"),
    "ウズベキスタン": ("UZ", "Uzbekistan"),
    "ウルグアイ": ("UY", "Uruguay"),
    "英国": ("GB", "United Kingdom"),
    "エクアドル": ("EC", "Ecuador"),
    "エジプト": ("EG", "Egypt"),
    "エストニア": ("EE", "Estonia"),
    "オーストラリア": ("AU", "Australia"),
    "オーストリア": ("AT", "Austria"),
    "オマーン": ("OM", "Oman"),
    "オランダ": ("NL", "Netherlands"),
    "カザフスタン": ("KZ", "Kazakhstan"),
    "カタール": ("QA", "Qatar"),
    "カナダ": ("CA", "Canada"),
    "韓国": ("KR", "Republic of Korea"),
    "ガーンジー": ("GG", "Guernsey"),
    "ケイマン諸島": ("KY", "Cayman Islands"),
    "キルギス": ("KG", "Kyrgyzstan"),
    "クウェート": ("KW", "Kuwait"),
    "クロアチア": ("HR", "Croatia"),
    "コロンビア": ("CO", "Colombia"),
    "サウジアラビア": ("SA", "Saudi Arabia"),
    "ザンビア": ("ZM", "Zambia"),
    "ジャージー": ("JE", "Jersey"),
    "ジャマイカ": ("JM", "Jamaica"),
    "ジョージア": ("GE", "Georgia"),
    "シンガポール": ("SG", "Singapore"),
    "スイス": ("CH", "Switzerland"),
    "スウェーデン": ("SE", "Sweden"),
    "スペイン": ("ES", "Spain"),
    "スリランカ": ("LK", "Sri Lanka"),
    "スロバキア": ("SK", "Slovakia"),
    "スロベニア": ("SI", "Slovenia"),
    "セルビア": ("RS", "Serbia"),
    "タイ": ("TH", "Thailand"),
    "タジキスタン": ("TJ", "Tajikistan"),
    "台湾": ("TW", "Taiwan"),
    "チェコ": ("CZ", "Czech Republic"),
    "チリ": ("CL", "Chile"),
    "中国": ("CN", "China"),
    "デンマーク": ("DK", "Denmark"),
    "ドイツ": ("DE", "Germany"),
    "トルクメニスタン": ("TM", "Turkmenistan"),
    "トルコ": ("TR", "Turkey"),
    "ニュージーランド": ("NZ", "New Zealand"),
    "ノルウェー": ("NO", "Norway"),
    "パキスタン": ("PK", "Pakistan"),
    "パナマ": ("PA", "Panama"),
    "バーミューダ": ("BM", "Bermuda"),
    "バハマ": ("BS", "Bahamas"),
    "バングラデシュ": ("BD", "Bangladesh"),
    "ハンガリー": ("HU", "Hungary"),
    "フィジー": ("FJ", "Fiji"),
    "フィリピン": ("PH", "Philippines"),
    "フィンランド": ("FI", "Finland"),
    "ブラジル": ("BR", "Brazil"),
    "フランス": ("FR", "France"),
    "ブルガリア": ("BG", "Bulgaria"),
    "ブルネイ": ("BN", "Brunei"),
    "ベラルーシ": ("BY", "Belarus"),
    "ベトナム": ("VN", "Vietnam"),
    "ベルギー": ("BE", "Belgium"),
    "ペルー": ("PE", "Peru"),
    "ポーランド": ("PL", "Poland"),
    "ポルトガル": ("PT", "Portugal"),
    "香港": ("HK", "Hong Kong"),
    "マカオ": ("MO", "Macao"),
    "マレーシア": ("MY", "Malaysia"),
    "マン島": ("IM", "Isle of Man"),
    "南アフリカ": ("ZA", "South Africa"),
    "メキシコ": ("MX", "Mexico"),
    "モルドバ": ("MD", "Moldova"),
    "モロッコ": ("MA", "Morocco"),
    "ラトビア": ("LV", "Latvia"),
    "リトアニア": ("LT", "Lithuania"),
    "リヒテンシュタイン": ("LI", "Liechtenstein"),
    "ルクセンブルク": ("LU", "Luxembourg"),
    "ルーマニア": ("RO", "Romania"),
    "ロシア": ("RU", "Russia"),
}


# ---------------------------------------------------------------------------
# data classes
# ---------------------------------------------------------------------------


@dataclass
class TreatyRow:
    country_iso: str
    country_name_ja: str
    country_name_en: str
    treaty_kind: str = "comprehensive"
    dta_signed_date: str | None = None
    dta_in_force_date: str | None = None
    wht_dividend_pct: float | None = None
    wht_dividend_parent_pct: float | None = None
    wht_interest_pct: float | None = None
    wht_royalty_pct: float | None = None
    pe_days_threshold: int | None = None
    info_exchange: str = "standard"
    moaa_arbitration: int = 0
    notes: str | None = None
    source_url: str = MOF_INDEX_URL
    source_fetched_at: str = field(
        default_factory=lambda: datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    )
    license: str = "gov_standard"
    # extraction metadata (logged, NOT inserted)
    pdf_url: str | None = None
    pdf_sha256: str | None = None
    parse_status: str = "ok"
    parse_warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

_HOST_LAST_HIT: dict[str, float] = {}


def _throttle(host: str) -> None:
    last = _HOST_LAST_HIT.get(host, 0.0)
    delta = time.monotonic() - last
    if delta < PER_HOST_MIN_INTERVAL_S:
        time.sleep(PER_HOST_MIN_INTERVAL_S - delta)
    _HOST_LAST_HIT[host] = time.monotonic()


def _http_get(url: str) -> bytes:
    host = urlparse(url).hostname or ""
    _throttle(host)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_S, context=_SSL_CTX) as resp:  # nosec B310 - operator-config https endpoint, no file:/ schemes
        return resp.read()


# ---------------------------------------------------------------------------
# MOF index parsing — pulls per-country PDF links
# ---------------------------------------------------------------------------


class _MofLinkParser(HTMLParser):
    """Walks <a href="..."> on the MOF list page.

    The MOF page is a plain table — every per-country entry is an <a>
    pointing at a /tax_convention/<country>/... PDF or per-country .htm.
    We capture (link_text, href) pairs and downstream code resolves them
    to ISO codes via COUNTRY_LOOKUP.
    """

    def __init__(self) -> None:
        super().__init__()
        self.pairs: list[tuple[str, str]] = []
        self._current_href: str | None = None
        self._current_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "a":
            attrs_d = dict(attrs)
            self._current_href = attrs_d.get("href")
            self._current_text = []

    def handle_data(self, data: str) -> None:
        if self._current_href is not None:
            self._current_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "a" and self._current_href is not None:
            text = "".join(self._current_text).strip()
            if text and self._current_href:
                self.pairs.append((text, self._current_href))
            self._current_href = None
            self._current_text = []


def discover_country_pdfs(index_url: str = MOF_INDEX_URL) -> dict[str, str]:
    """Return dict[country_iso → pdf_url] discovered from the MOF index."""
    body = _http_get(index_url).decode("utf-8", errors="replace")
    parser = _MofLinkParser()
    parser.feed(body)

    out: dict[str, str] = {}
    for text, href in parser.pairs:
        # Normalise whitespace
        norm = re.sub(r"\s+", "", text)
        # Try to match country name (longest first to avoid 韓国/北朝鮮 collisions)
        for ja_name in sorted(COUNTRY_LOOKUP, key=len, reverse=True):
            if ja_name in norm:
                iso, _ = COUNTRY_LOOKUP[ja_name]
                # Prefer PDF; otherwise keep the .htm as a fallback
                full_url = urljoin(index_url, href)
                if iso not in out or full_url.lower().endswith(".pdf"):
                    out[iso] = full_url
                break
    return out


# ---------------------------------------------------------------------------
# PDF text extraction
# ---------------------------------------------------------------------------


def extract_pdf_text(pdf_bytes: bytes) -> str:
    """Extract concatenated text from all PDF pages (pypdf, no LLM)."""
    reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
    parts: list[str] = []
    for page in reader.pages:
        try:
            parts.append(page.extract_text() or "")
        except Exception as exc:  # noqa: BLE001
            _LOG.warning("pypdf page extract failed: %s", exc)
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Article regex parsing
# ---------------------------------------------------------------------------

# 配当 — captures both 一般 (general) and 親子間 (parent-sub) %
# Tolerates half-width / full-width digits and varied ordering.
_RE_DIVIDEND = re.compile(
    r"(?:第\s*10\s*条|配当)[\s\S]{0,800}?" r"(?P<rate1>\d{1,2}(?:\.\d{1,2})?)\s*[%％]",
    re.MULTILINE,
)
# The reduced parent-sub rate appears AFTER the holding-threshold clause:
#   「議決権の 10% 以上を直接に所有する法人である場合には、5% を超えない」
# We therefore anchor on `場合には` (the rate-applies clause) rather than
# the holding-threshold keyword, so the captured rate is the rate, not
# the threshold percentage.
_RE_DIVIDEND_PARENT = re.compile(
    r"(?:親子間|親会社|持分|議決権|保有)[\s\S]{0,200}?"
    r"場合(?:に)?(?:は)?(?:[、,])?[\s\S]{0,80}?"
    r"(?P<rate>\d{1,2}(?:\.\d{1,2})?)\s*[%％]",
)
_RE_INTEREST = re.compile(
    r"(?:第\s*11\s*条|利子)[\s\S]{0,800}?" r"(?P<rate>\d{1,2}(?:\.\d{1,2})?)\s*[%％]",
)
_RE_ROYALTY = re.compile(
    r"(?:第\s*12\s*条|使用料|ロイヤリティ)[\s\S]{0,800}?"
    r"(?P<rate>\d{1,2}(?:\.\d{1,2})?)\s*[%％]",
)
_RE_PE_DAYS = re.compile(
    r"(?:第\s*5\s*条|恒久的施設|PE)[\s\S]{0,1200}?" r"(?P<days>\d{2,3})\s*(?:日|か月|箇月|月)",
)
# Bidirectional date regex: matches either
#   「2003年11月6日に署名された」  (date BEFORE keyword)
# or
#   「署名 2003年11月6日」          (keyword BEFORE date)
_RE_SIGNED = re.compile(
    r"(?P<y>\d{4})\s*年\s*(?P<m>\d{1,2})\s*月\s*(?P<d>\d{1,2})\s*日"
    r"[^。\n]{0,40}?(?:署名|締結)"
    r"|"
    r"(?:署名|締結)[^。\n]{0,80}?"
    r"(?P<y2>\d{4})\s*年\s*(?P<m2>\d{1,2})\s*月\s*(?P<d2>\d{1,2})\s*日"
)
_RE_IN_FORCE = re.compile(
    r"(?P<y>\d{4})\s*年\s*(?P<m>\d{1,2})\s*月\s*(?P<d>\d{1,2})\s*日"
    r"[^。\n]{0,40}?(?:発効|効力(?:を)?(?:生じ|生ずる)|効力発生)"
    r"|"
    r"(?:発効|効力(?:を)?(?:生じ|生ずる)|効力発生)[^。\n]{0,80}?"
    r"(?P<y2>\d{4})\s*年\s*(?P<m2>\d{1,2})\s*月\s*(?P<d2>\d{1,2})\s*日"
)


def _norm_digits(text: str) -> str:
    """Convert full-width digits / percent / period to half-width."""
    trans = str.maketrans(
        "0123456789.%",
        "0123456789.%",
    )
    return text.translate(trans)


def parse_treaty_text(text: str) -> dict[str, Any]:
    """Run the article regex pack on the PDF text. Returns a dict with
    None for any field that didn't match — caller decides how to handle.
    """
    text = _norm_digits(text)
    out: dict[str, Any] = {
        "wht_dividend_pct": None,
        "wht_dividend_parent_pct": None,
        "wht_interest_pct": None,
        "wht_royalty_pct": None,
        "pe_days_threshold": None,
        "dta_signed_date": None,
        "dta_in_force_date": None,
        "warnings": [],
    }

    m = _RE_DIVIDEND.search(text)
    if m:
        out["wht_dividend_pct"] = float(m.group("rate1"))
    else:
        out["warnings"].append("dividend_rate_not_matched")

    # Parent-subsidiary rate is harder; look in the same window as 第10条
    if m:
        window = text[m.start() : m.start() + 1200]
        pm = _RE_DIVIDEND_PARENT.search(window)
        if pm:
            parent_rate = float(pm.group("rate"))
            general_rate = out["wht_dividend_pct"] or 0.0
            # Parent-sub rate is by treaty design ≤ general rate; if regex
            # captured the same number as the general rate, treat as N/A.
            if parent_rate < general_rate:
                out["wht_dividend_parent_pct"] = parent_rate

    im = _RE_INTEREST.search(text)
    if im:
        out["wht_interest_pct"] = float(im.group("rate"))
    else:
        out["warnings"].append("interest_rate_not_matched")

    rm = _RE_ROYALTY.search(text)
    if rm:
        out["wht_royalty_pct"] = float(rm.group("rate"))
    else:
        out["warnings"].append("royalty_rate_not_matched")

    pm = _RE_PE_DAYS.search(text)
    if pm:
        with contextlib.suppress(ValueError):
            out["pe_days_threshold"] = int(pm.group("days"))

    def _pick_ymd(m: re.Match[str] | None) -> str | None:
        if m is None:
            return None
        # Bidirectional regex: try the primary group set first, else fallback
        y = m.group("y") or m.group("y2")
        mo = m.group("m") or m.group("m2")
        d = m.group("d") or m.group("d2")
        if not (y and mo and d):
            return None
        try:
            return f"{int(y):04d}-{int(mo):02d}-{int(d):02d}"
        except ValueError:
            return None

    out["dta_signed_date"] = _pick_ymd(_RE_SIGNED.search(text))
    out["dta_in_force_date"] = _pick_ymd(_RE_IN_FORCE.search(text))
    return out


# ---------------------------------------------------------------------------
# DB upsert
# ---------------------------------------------------------------------------

_UPSERT_SQL = """
INSERT INTO am_tax_treaty (
    country_iso, country_name_ja, country_name_en,
    treaty_kind, dta_signed_date, dta_in_force_date,
    wht_dividend_pct, wht_dividend_parent_pct,
    wht_interest_pct, wht_royalty_pct,
    pe_days_threshold, info_exchange, moaa_arbitration,
    notes, source_url, source_fetched_at, license,
    updated_at
) VALUES (
    :country_iso, :country_name_ja, :country_name_en,
    :treaty_kind, :dta_signed_date, :dta_in_force_date,
    :wht_dividend_pct, :wht_dividend_parent_pct,
    :wht_interest_pct, :wht_royalty_pct,
    :pe_days_threshold, :info_exchange, :moaa_arbitration,
    :notes, :source_url, :source_fetched_at, :license,
    datetime('now')
)
ON CONFLICT(country_iso) DO UPDATE SET
    country_name_ja        = excluded.country_name_ja,
    country_name_en        = excluded.country_name_en,
    treaty_kind            = excluded.treaty_kind,
    dta_signed_date        = COALESCE(excluded.dta_signed_date, am_tax_treaty.dta_signed_date),
    dta_in_force_date      = COALESCE(excluded.dta_in_force_date, am_tax_treaty.dta_in_force_date),
    wht_dividend_pct       = COALESCE(excluded.wht_dividend_pct, am_tax_treaty.wht_dividend_pct),
    wht_dividend_parent_pct= COALESCE(excluded.wht_dividend_parent_pct, am_tax_treaty.wht_dividend_parent_pct),
    wht_interest_pct       = COALESCE(excluded.wht_interest_pct, am_tax_treaty.wht_interest_pct),
    wht_royalty_pct        = COALESCE(excluded.wht_royalty_pct, am_tax_treaty.wht_royalty_pct),
    pe_days_threshold      = COALESCE(excluded.pe_days_threshold, am_tax_treaty.pe_days_threshold),
    info_exchange          = excluded.info_exchange,
    moaa_arbitration       = excluded.moaa_arbitration,
    notes                  = COALESCE(excluded.notes, am_tax_treaty.notes),
    source_url             = excluded.source_url,
    source_fetched_at      = excluded.source_fetched_at,
    license                = excluded.license,
    updated_at             = datetime('now');
"""


def upsert_row(conn: sqlite3.Connection, row: TreatyRow) -> None:
    payload: dict[str, Any] = {
        k: v
        for k, v in asdict(row).items()
        if k not in ("pdf_url", "pdf_sha256", "parse_status", "parse_warnings")
    }
    conn.execute(_UPSERT_SQL, payload)


# ---------------------------------------------------------------------------
# Logging helper
# ---------------------------------------------------------------------------


def append_log(record: dict[str, Any]) -> None:
    _LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with _LOG_FILE.open("a", encoding="utf-8") as fp:
        fp.write(json.dumps(record, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------
# Smoke fixture (5 anchor countries, used when --smoke)
# Values match migrations 091 + 125 so smoke + production converge on the
# same wht_*_pct / dta_*_date set. PDF text is synthetic but exercises
# every regex in the parse pack.
# ---------------------------------------------------------------------------

_SMOKE_FIXTURE_TEXT_US = """
所得に対する租税に関する二重課税の回避及び脱税の防止のための条約

第5条 恒久的施設
建設工事現場、組立工事又はこれらに関連する監督活動は、12箇月を超える
期間継続する場合に限り、恒久的施設を構成する。

第10条 配当
締約国の居住者である会社が他方の締約国の居住者に支払う配当に対しては、
当該他方の締約国においても、その源泉地国の法令に従って租税を課する
ことができる。ただし、その租税は、配当の受益者がその他方の締約国の
居住者である場合には、配当の額の10%を超えないものとする。
ただし、配当の受益者が、当該配当の支払を受ける者の議決権のある株式の
10%以上を直接に所有する法人である場合には、5%を超えないものとする。

第11条 利子
締約国内において生ずる利子であって他方の締約国の居住者が受益者である
ものに対しては、当該他方の締約国においても、源泉地国の法令に従って
租税を課することができる。ただし、その租税は、利子の額の10%を
超えないものとする。

第12条 使用料
締約国内において生ずる使用料であって他方の締約国の居住者が受益者で
あるものに対しては、源泉地国においては免税とする。すなわち、税率は
0%とする。

この条約は、2003年11月6日に署名された。
この条約は、2004年3月30日にその効力を生ずる。
"""

_SMOKE_FIXTURES: list[tuple[str, str, str, str, str]] = [
    # (iso, ja, en, pdf_url, pdf_text)
    (
        "US",
        "米国",
        "United States",
        "https://www.mof.go.jp/tax_policy/summary/international/tax_convention/usa_jp.pdf",
        _SMOKE_FIXTURE_TEXT_US,
    ),
    (
        "GB",
        "英国",
        "United Kingdom",
        "https://www.mof.go.jp/tax_policy/summary/international/tax_convention/gbr_jp.pdf",
        _SMOKE_FIXTURE_TEXT_US.replace("10%", "10%")
        .replace("2003年11月6日", "2006年2月2日")
        .replace("2004年3月30日", "2006年10月12日")
        .replace("5%", "0%"),  # parent-sub 0% per 2014 protocol
    ),
    (
        "CN",
        "中国",
        "China",
        "https://www.mof.go.jp/tax_policy/summary/international/tax_convention/chn_jp.pdf",
        _SMOKE_FIXTURE_TEXT_US.replace("10%", "10%")
        .replace("0%", "10%")  # royalty 10%
        .replace("5%", "10%")  # parent rate same as general (no reduction)
        .replace("2003年11月6日", "1983年9月6日")
        .replace("2004年3月30日", "1984年6月26日"),
    ),
    (
        "KR",
        "韓国",
        "Republic of Korea",
        "https://www.mof.go.jp/tax_policy/summary/international/tax_convention/kor_jp.pdf",
        _SMOKE_FIXTURE_TEXT_US.replace("10%", "15%")  # general dividend 15%
        .replace("0%", "10%")  # royalty 10%
        .replace("5%", "5%")  # parent 5%
        .replace("2003年11月6日", "1998年10月8日")
        .replace("2004年3月30日", "1999年11月22日"),
    ),
    (
        "SG",
        "シンガポール",
        "Singapore",
        "https://www.mof.go.jp/tax_policy/summary/international/tax_convention/sgp_jp.pdf",
        _SMOKE_FIXTURE_TEXT_US.replace("10%", "15%")
        .replace("0%", "10%")  # royalty 10%
        .replace("5%", "5%")
        .replace("2003年11月6日", "1994年4月9日")
        .replace("2004年3月30日", "1995年4月28日"),
    ),
]


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


def process_one(
    iso: str,
    ja: str,
    en: str,
    pdf_url: str,
    pdf_bytes: bytes,
) -> TreatyRow:
    text = extract_pdf_text(pdf_bytes)
    parsed = parse_treaty_text(text)

    notes_parts: list[str] = []
    if parsed["warnings"]:
        notes_parts.append("regex warnings: " + ", ".join(parsed["warnings"]))
    notes_parts.append(f"parsed from PDF ({len(text)} chars extracted)")

    row = TreatyRow(
        country_iso=iso,
        country_name_ja=ja,
        country_name_en=en,
        treaty_kind="comprehensive",
        dta_signed_date=parsed["dta_signed_date"],
        dta_in_force_date=parsed["dta_in_force_date"],
        wht_dividend_pct=parsed["wht_dividend_pct"],
        wht_dividend_parent_pct=parsed["wht_dividend_parent_pct"],
        wht_interest_pct=parsed["wht_interest_pct"],
        wht_royalty_pct=parsed["wht_royalty_pct"],
        pe_days_threshold=parsed["pe_days_threshold"],
        info_exchange="standard",
        moaa_arbitration=0,
        notes="; ".join(notes_parts),
        source_url=pdf_url,
        pdf_url=pdf_url,
        pdf_sha256=hashlib.sha256(pdf_bytes).hexdigest(),
        parse_status="ok" if not parsed["warnings"] else "partial",
        parse_warnings=parsed["warnings"],
    )
    return row


def run_smoke(conn: sqlite3.Connection, dry_run: bool = False) -> int:
    """Process the 5-fixture pack — exercises parser + upsert without net."""
    n_ok = 0
    for iso, ja, en, pdf_url, pdf_text in _SMOKE_FIXTURES:
        # The fixture supplies text directly (no real PDF bytes); we feed
        # it into parse_treaty_text and synthesise the SHA256 from the
        # text so the log has a meaningful provenance digest.
        parsed = parse_treaty_text(pdf_text)
        notes_parts = []
        if parsed["warnings"]:
            notes_parts.append("regex warnings: " + ", ".join(parsed["warnings"]))
        notes_parts.append("smoke fixture (no real PDF fetch)")
        row = TreatyRow(
            country_iso=iso,
            country_name_ja=ja,
            country_name_en=en,
            treaty_kind="comprehensive",
            dta_signed_date=parsed["dta_signed_date"],
            dta_in_force_date=parsed["dta_in_force_date"],
            wht_dividend_pct=parsed["wht_dividend_pct"],
            wht_dividend_parent_pct=parsed["wht_dividend_parent_pct"],
            wht_interest_pct=parsed["wht_interest_pct"],
            wht_royalty_pct=parsed["wht_royalty_pct"],
            pe_days_threshold=parsed["pe_days_threshold"],
            info_exchange="standard",
            moaa_arbitration=0,
            notes="; ".join(notes_parts),
            source_url=pdf_url,
            pdf_url=pdf_url,
            pdf_sha256=hashlib.sha256(pdf_text.encode("utf-8")).hexdigest(),
            parse_status="ok" if not parsed["warnings"] else "partial",
            parse_warnings=parsed["warnings"],
        )
        if not dry_run:
            upsert_row(conn, row)
        append_log(
            {
                "iso": iso,
                "mode": "smoke",
                "parsed": {k: v for k, v in asdict(row).items() if k not in ("parse_warnings",)},
                "warnings": row.parse_warnings,
                "ts": datetime.now(UTC).isoformat(),
            }
        )
        n_ok += 1
        _LOG.info(
            "[smoke] %s wht_div=%s wht_int=%s wht_roy=%s signed=%s in_force=%s warnings=%d",
            iso,
            row.wht_dividend_pct,
            row.wht_interest_pct,
            row.wht_royalty_pct,
            row.dta_signed_date,
            row.dta_in_force_date,
            len(row.parse_warnings),
        )
    if not dry_run:
        conn.commit()
    return n_ok


def run_online(
    conn: sqlite3.Connection,
    countries: set[str] | None = None,
    limit: int | None = None,
    dry_run: bool = False,
) -> int:
    """Walk MOF index → fetch PDFs → parse → upsert."""
    _LOG.info("discovering per-country PDF links from %s", MOF_INDEX_URL)
    discovered = discover_country_pdfs()
    _LOG.info("discovered %d country links from MOF index", len(discovered))

    if countries:
        discovered = {iso: url for iso, url in discovered.items() if iso in countries}
        _LOG.info("filtered to %d countries: %s", len(discovered), sorted(countries))

    n_ok = 0
    n_err = 0
    iso_ja_lookup = {iso: (ja, en) for ja, (iso, en) in COUNTRY_LOOKUP.items()}

    for i, (iso, pdf_url) in enumerate(discovered.items()):
        if limit is not None and i >= limit:
            break
        ja, en = iso_ja_lookup.get(iso, (iso, iso))
        try:
            _LOG.info("fetching %s (%s) ← %s", iso, ja, pdf_url)
            pdf_bytes = _http_get(pdf_url)
            # If we landed on .htm, skip — only PDFs are parseable here.
            if not pdf_url.lower().endswith(".pdf"):
                _LOG.warning("%s: link is not a PDF (%s); skipping", iso, pdf_url)
                append_log(
                    {
                        "iso": iso,
                        "mode": "online",
                        "status": "skip_non_pdf",
                        "url": pdf_url,
                        "ts": datetime.now(UTC).isoformat(),
                    }
                )
                continue
            row = process_one(iso, ja, en, pdf_url, pdf_bytes)
            if not dry_run:
                upsert_row(conn, row)
            append_log(
                {
                    "iso": iso,
                    "mode": "online",
                    "status": row.parse_status,
                    "parsed": {
                        k: v for k, v in asdict(row).items() if k not in ("parse_warnings",)
                    },
                    "warnings": row.parse_warnings,
                    "ts": datetime.now(UTC).isoformat(),
                }
            )
            n_ok += 1
        except (urllib.error.URLError, urllib.error.HTTPError, OSError, ValueError) as exc:
            _LOG.error("%s: fetch/parse failed: %s", iso, exc)
            append_log(
                {
                    "iso": iso,
                    "mode": "online",
                    "status": "error",
                    "error": str(exc),
                    "url": pdf_url,
                    "ts": datetime.now(UTC).isoformat(),
                }
            )
            n_err += 1

    if not dry_run:
        conn.commit()
    _LOG.info("online run done: ok=%d err=%d", n_ok, n_err)
    return n_ok


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--smoke", action="store_true", help="run 5-country fixture (no net)")
    p.add_argument("--countries", default=None, help="comma-separated ISO codes (e.g. US,GB,SG)")
    p.add_argument("--limit", type=int, default=None, help="cap number of countries (debug)")
    p.add_argument("--db", type=Path, default=_DEFAULT_DB, help="autonomath.db path")
    p.add_argument("--dry-run", action="store_true", help="parse + log only, no DB writes")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if not args.db.exists():
        _LOG.error("DB not found at %s", args.db)
        return 2

    conn = sqlite3.connect(args.db)
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA busy_timeout=30000;")
        # Verify schema exists
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='am_tax_treaty';"
        )
        if cur.fetchone() is None:
            _LOG.error("am_tax_treaty table missing — run migration 091 first")
            return 3

        if args.smoke:
            n = run_smoke(conn, dry_run=args.dry_run)
            _LOG.info("smoke complete: %d rows upserted", n)
        else:
            countries = (
                {c.strip().upper() for c in args.countries.split(",") if c.strip()}
                if args.countries
                else None
            )
            n = run_online(
                conn,
                countries=countries,
                limit=args.limit,
                dry_run=args.dry_run,
            )
            _LOG.info("online complete: %d rows upserted", n)

        # Report final state
        total = conn.execute("SELECT COUNT(*) FROM am_tax_treaty;").fetchone()[0]
        _LOG.info("am_tax_treaty total rows now: %d", total)
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
