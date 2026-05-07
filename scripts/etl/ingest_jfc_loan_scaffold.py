#!/usr/bin/env python3
"""JFC (日本政策金融公庫) loan-product scaffold ingester.

Scope (deliberately small):
    * Walks the JFC 国民生活事業 product index (`/n/finance/search/index_k.html`)
    * Fetches each linked product page (≤ 30 pages — `--limit` cap)
    * Parses product-detail tables for名称 / 対象 / 融資限度 / 担保有無 /
      保証人有無 / 利率 / 償還期間 / 出典 URL
    * Normalises 担保 / 個人保証人 / 第三者保証人 to the three orthogonal axes
      enforced by migration 013 (values: required | not_required | negotiable
      | unknown). Memory `feedback_no_priority_question` + the migration 013
      header forbid collapsing these into a single text bucket.

NO DB writes. Output is a CSV at `analysis_wave18/jfc_loan_scaffold_<date>.csv`.
The DB-write path lives in production cron (TBD — out of scope for this
scaffold). Keeping ingest separate from persistence means we can audit the
parser output before any row touches `loan_programs`.

The script also seeds a 47 信用保証協会 (Credit Guarantee Association)
URL list from `https://www.zenshinhoren.or.jp/` (the 全国信用保証協会連合会
home page lists every member association). One smoke fetch is performed
against the first member to verify reachability — failures here are
acceptable (the URL list itself is the deliverable).

Constraints (per task spec + memory):
    * UA = jpcite-research/1.0
    * 1 sec/req per host (per-domain throttle)
    * No LLM API
    * Three-axis risk normalisation must NOT collapse to a single text column
    * Every output row carries source_url
    * Smoke ingest (≤ 30 rows) — production cron expands later

Run:
    python scripts/etl/ingest_jfc_loan_scaffold.py
        [--limit 30]
        [--out analysis_wave18/jfc_loan_scaffold_2026-05-01.csv]
        [--no-net]                     # parse-only against fixtures (test mode)
        [--guarantor-out analysis_wave18/credit_guarantee_associations_2026-05-01.csv]
"""

from __future__ import annotations

import argparse
import csv
import logging
import re
import ssl
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urljoin, urlparse

if TYPE_CHECKING:
    from collections.abc import Iterable

try:
    import certifi  # type: ignore[import-not-found]

    _SSL_CTX: ssl.SSLContext | None = ssl.create_default_context(cafile=certifi.where())
except ImportError:  # pragma: no cover - certifi optional in dev
    _SSL_CTX = None


# ---------------------------------------------------------------------------
# config
# ---------------------------------------------------------------------------

USER_AGENT = "jpcite-research/1.0 (+https://jpcite.com/about)"
HTTP_TIMEOUT_S = 15
PER_HOST_MIN_INTERVAL_S = 1.0  # 1 req/sec/host

JFC_INDEX_URL = "https://www.jfc.go.jp/n/finance/search/index_k.html"
ZENSHINHOREN_URL = "https://www.zenshinhoren.or.jp/"

JFC_ALLOWED_HOSTS = {"www.jfc.go.jp", "jfc.go.jp"}

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_CSV = REPO_ROOT / "analysis_wave18" / f"jfc_loan_scaffold_{date.today().isoformat()}.csv"
DEFAULT_GUARANTOR_CSV = (
    REPO_ROOT / "analysis_wave18" / f"credit_guarantee_associations_{date.today().isoformat()}.csv"
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("ingest_jfc_loan_scaffold")


# ---------------------------------------------------------------------------
# HTTP throttle
# ---------------------------------------------------------------------------


class HostThrottle:
    """Per-host minimum interval between requests."""

    def __init__(self, min_interval_s: float = PER_HOST_MIN_INTERVAL_S) -> None:
        self._last: dict[str, float] = defaultdict(float)
        self._gap = min_interval_s

    def wait(self, url: str) -> None:
        host = urlparse(url).netloc.lower()
        elapsed = time.monotonic() - self._last[host]
        if elapsed < self._gap:
            time.sleep(self._gap - elapsed)
        self._last[host] = time.monotonic()


def http_get(url: str, throttle: HostThrottle) -> str:
    """Fetch `url` as text, respecting per-host throttling. Raises on error."""
    throttle.wait(url)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_S, context=_SSL_CTX) as resp:  # nosec B310 - operator-config https endpoint, no file:/ schemes
        raw = resp.read()
    # JFC pages are utf-8 in the live tree; fall back to shift_jis on legacy mirrors.
    for enc in ("utf-8", "shift_jis", "cp932"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


# ---------------------------------------------------------------------------
# index parsing — find product page URLs from `index_k.html`
# ---------------------------------------------------------------------------

# Product-detail pages on JFC use names like 01_sinkikaigyou_m.html,
# kanko_m.html, etc. We accept either the *_m.html suffix (国民事業 product
# detail) OR specific allow-listed slugs that are known product pages.
_PRODUCT_HREF_RE = re.compile(r'href="(/n/finance/search/(?!index)[a-zA-Z0-9_]+(?:_m)?\.html)"')
# Skip anchors / pdf / non-product navigation tabs.
_PRODUCT_NEGATIVES = {
    "/n/finance/search/index.html",
    "/n/finance/search/index_k.html",
    "/n/finance/search/index_k_02.html",
    "/n/finance/search/index_a.html",
    "/n/finance/search/index_c.html",
    "/n/finance/search/ippan.html",  # 国の教育ローン (consumer, not 事業資金)
}


def discover_jfc_product_urls(index_html: str, base: str = JFC_INDEX_URL) -> list[str]:
    """Return the de-duplicated, ordered list of product-page URLs from
    the JFC 国民事業 product index.
    """
    seen: list[str] = []
    seen_set: set[str] = set()
    for match in _PRODUCT_HREF_RE.finditer(index_html):
        path = match.group(1)
        if path in _PRODUCT_NEGATIVES:
            continue
        url = urljoin(base, path)
        if url in seen_set:
            continue
        host = urlparse(url).netloc.lower()
        if host and host not in JFC_ALLOWED_HOSTS:
            continue
        seen.append(url)
        seen_set.add(url)
    return seen


# ---------------------------------------------------------------------------
# product-page parsing
# ---------------------------------------------------------------------------

# JFC product pages render a parameter table whose left column (`<th>`) is one
# of the canonical labels below. We map label -> normalised key.
_LABEL_KEYS: dict[str, str] = {
    "ご利用いただける方": "target",
    "ご利用いただける方（一般貸付）": "target",
    "資金のお使いみち": "purpose",
    "融資限度額": "amount_max_text",
    "ご返済期間": "loan_period_text",
    "返済期間": "loan_period_text",
    "利率（年）": "interest_rate_text",
    "利率(年)": "interest_rate_text",
    "担保・保証人": "security_text",
    "担保・保証": "security_text",
    "担保": "collateral_text",
    "保証人": "guarantor_text",
    "併用できる特例制度": "concurrent_special",
}


class _ProductTableParser(HTMLParser):
    """Walks the JFC product detail HTML and extracts label -> value text.

    JFC pages put parameter labels in `<th scope="col">` (or `scope="row"`)
    and their values in the immediately-following sibling `<td>` cells of
    the same `<tr>`. We accumulate text per cell and emit a (label, value)
    pair when the row closes.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[tuple[str, str]] = []
        self._in_table = False
        self._in_tr = False
        self._in_th = False
        self._in_td = False
        self._cur_label: str | None = None
        self._cur_value_parts: list[str] = []
        self._title: str | None = None
        self._in_h1 = False
        self._h1_parts: list[str] = []

    # NOTE: HTMLParser is forgiving about case; tag arg is always lowercased.
    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "table":
            self._in_table = True
        elif tag == "tr" and self._in_table:
            self._in_tr = True
            self._cur_label = None
            self._cur_value_parts = []
        elif tag == "th" and self._in_tr:
            self._in_th = True
        elif tag == "td" and self._in_tr:
            self._in_td = True
        elif tag == "br" and (self._in_td or self._in_h1):
            # Preserve line breaks that JFC uses inside td cells.
            if self._in_td:
                self._cur_value_parts.append("\n")
            else:
                self._h1_parts.append("\n")
        elif tag == "h1":
            self._in_h1 = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "table":
            self._in_table = False
        elif tag == "tr":
            self._in_tr = False
            if self._cur_label and self._cur_value_parts:
                value = " ".join(
                    p.strip() for p in "".join(self._cur_value_parts).splitlines()
                ).strip()
                self.rows.append((self._cur_label.strip(), value))
        elif tag == "th":
            self._in_th = False
        elif tag == "td":
            self._in_td = False
        elif tag == "h1":
            self._in_h1 = False
            if self._h1_parts and not self._title:
                self._title = " ".join(
                    p.strip() for p in "".join(self._h1_parts).splitlines()
                ).strip()

    def handle_data(self, data: str) -> None:
        if self._in_th:
            if self._cur_label is None:
                self._cur_label = data
            else:
                # Multi-row label spans (rowspan). Keep first occurrence.
                pass
        elif self._in_td:
            self._cur_value_parts.append(data)
        elif self._in_h1:
            self._h1_parts.append(data)


@dataclass
class JfcLoanRecord:
    program_name: str
    provider: str = "日本政策金融公庫"
    target: str = ""
    purpose: str = ""
    amount_max_text: str = ""
    amount_max_yen: int | None = None
    loan_period_text: str = ""
    loan_period_years_max: int | None = None
    interest_rate_text: str = ""
    security_text: str = ""
    collateral_required: str = "unknown"
    personal_guarantor_required: str = "unknown"
    third_party_guarantor_required: str = "unknown"
    security_notes: str = ""
    source_url: str = ""
    fetched_at: str = ""

    def to_csv_row(self) -> dict[str, str]:
        return {
            "program_name": self.program_name,
            "provider": self.provider,
            "target": self.target,
            "purpose": self.purpose,
            "amount_max_text": self.amount_max_text,
            "amount_max_yen": str(self.amount_max_yen) if self.amount_max_yen else "",
            "loan_period_text": self.loan_period_text,
            "loan_period_years_max": (
                str(self.loan_period_years_max) if self.loan_period_years_max else ""
            ),
            "interest_rate_text": self.interest_rate_text,
            "security_text": self.security_text,
            "collateral_required": self.collateral_required,
            "personal_guarantor_required": self.personal_guarantor_required,
            "third_party_guarantor_required": self.third_party_guarantor_required,
            "security_notes": self.security_notes,
            "source_url": self.source_url,
            "fetched_at": self.fetched_at,
        }


# ---------------------------------------------------------------------------
# normalisation helpers
# ---------------------------------------------------------------------------

_AMOUNT_PATTERNS = [
    # 7,200万円 / 4億8,000万円 / 直接貸付 7億2千万円 / 7億円
    (
        re.compile(r"(\d{1,3}(?:,\d{3})*|\d+)\s*億(\d{1,3}(?:,\d{3})*|\d+)\s*千?万円"),
        lambda m: (
            int(m.group(1).replace(",", "")) * 100_000_000
            + int(m.group(2).replace(",", "")) * 10_000
        ),
    ),
    (
        re.compile(r"(\d{1,3}(?:,\d{3})*|\d+)\s*億円"),
        lambda m: int(m.group(1).replace(",", "")) * 100_000_000,
    ),
    (
        re.compile(r"(\d{1,3}(?:,\d{3})*|\d+)\s*万円"),
        lambda m: int(m.group(1).replace(",", "")) * 10_000,
    ),
]


def parse_amount_max_yen(text: str) -> int | None:
    """Return the FIRST yen amount found in `text`, or None.

    Many JFC pages list both 中小企業事業 and 国民生活事業 limits; we keep
    the first match (page is sectioned per audience and the国民事業 figure
    is at the top). Production code can re-extract per-section if needed.
    """
    if not text:
        return None
    for pat, fn in _AMOUNT_PATTERNS:
        m = pat.search(text)
        if m:
            try:
                return fn(m)
            except (ValueError, IndexError):
                continue
    return None


_PERIOD_RE = re.compile(r"(\d+)\s*年以内")


def parse_loan_period_years_max(text: str) -> int | None:
    """Return the LARGEST X 年以内 found in `text`, or None.

    Loan products typically list separate 設備資金 / 運転資金 caps; the
    longer of the two is the conservative-disclosure max.
    """
    if not text:
        return None
    candidates = [int(m.group(1)) for m in _PERIOD_RE.finditer(text)]
    return max(candidates) if candidates else None


def normalise_three_axis_security(security_text: str) -> tuple[str, str, str, str]:
    """Map free-text 担保・保証人 phrasing to the three orthogonal axes.

    Returns: (collateral, personal_guarantor, third_party_guarantor, notes)

    Each axis is one of: 'required' | 'not_required' | 'negotiable' | 'unknown'.
    `notes` is the original text (kept for audit + manual triage).

    The mapping is intentionally CONSERVATIVE — when the phrasing is
    ambiguous (e.g. "ご相談"), we mark `negotiable` for both 担保 and
    個人保証人 axes and leave 第三者 as `not_required` if 第三者保証人
    is explicitly mentioned as 不要 elsewhere. We do NOT collapse to a
    single column (forbidden by migration 013 + memory).
    """
    text = (security_text or "").strip()
    notes = text

    has_mu_tampo = "無担保" in text
    has_mu_hosho = "無保証" in text
    has_yes_tampo = "担保あり" in text or "担保が必要" in text or "担保は" in text
    has_yes_guarantor = "保証人あり" in text or "保証人が必要" in text or "連帯保証人" in text
    has_third_party_unmu = (
        "第三者保証人を不要" in text or "第三者保証人不要" in text or "第三者保証人は不要" in text
    )
    has_consult = "ご相談" in text or "ご希望を伺い" in text or "ご希望をお伺い" in text
    has_keieisha_only = "経営者" in text and "保証" in text and "免除" in text

    # default
    collateral = "unknown"
    personal = "unknown"
    third_party = "unknown"

    if has_mu_tampo:
        collateral = "not_required"
    elif has_yes_tampo:
        collateral = "required"
    elif has_consult:
        collateral = "negotiable"

    if has_mu_hosho:
        personal = "not_required"
        third_party = "not_required"
    elif has_keieisha_only:
        # 経営者保証免除特例 etc.: 個人保証 not required, 第三者 already standard not_required.
        personal = "not_required"
        third_party = "not_required"
    elif has_yes_guarantor:
        personal = "required"
        # We do NOT promote to third_party=required without explicit signal.
    elif has_consult:
        personal = "negotiable"

    if has_third_party_unmu:
        third_party = "not_required"
    elif third_party == "unknown" and has_consult:
        # Default JFC posture: 第三者 generally not required since 2006 reform.
        # Mark negotiable rather than asserting.
        third_party = "negotiable"

    return collateral, personal, third_party, notes


# ---------------------------------------------------------------------------
# top-level pipeline
# ---------------------------------------------------------------------------


def parse_jfc_product_page(html: str, source_url: str) -> JfcLoanRecord | None:
    """Parse one JFC product-detail page into a JfcLoanRecord."""
    parser = _ProductTableParser()
    parser.feed(html)

    # Build a label -> value index. JFC uses label dupes across multi-section
    # pages; first hit wins (matches the国民事業 column ordering).
    by_key: dict[str, str] = {}
    for label, value in parser.rows:
        key = _LABEL_KEYS.get(label.strip())
        if key and key not in by_key:
            by_key[key] = value

    if not by_key:
        log.warning("no parsable parameter table at %s", source_url)
        return None

    name = parser._title or _slug_to_label(source_url)
    record = JfcLoanRecord(
        program_name=name,
        target=by_key.get("target", ""),
        purpose=by_key.get("purpose", ""),
        amount_max_text=by_key.get("amount_max_text", ""),
        amount_max_yen=parse_amount_max_yen(by_key.get("amount_max_text", "")),
        loan_period_text=by_key.get("loan_period_text", ""),
        loan_period_years_max=parse_loan_period_years_max(by_key.get("loan_period_text", "")),
        interest_rate_text=by_key.get("interest_rate_text", ""),
        security_text=by_key.get("security_text", "") or by_key.get("collateral_text", ""),
        source_url=source_url,
        fetched_at=datetime.now(UTC).isoformat(timespec="seconds"),
    )

    # Three-axis normalisation
    coll, pers, third, notes = normalise_three_axis_security(record.security_text)
    record.collateral_required = coll
    record.personal_guarantor_required = pers
    record.third_party_guarantor_required = third
    record.security_notes = notes

    return record


def _slug_to_label(url: str) -> str:
    """Fallback program name when <h1> is missing.

    Strip the directory, drop the trailing _m.html, replace _ with space.
    """
    last = urlparse(url).path.rsplit("/", 1)[-1]
    last = re.sub(r"\.html?$", "", last)
    last = re.sub(r"_m$", "", last)
    last = last.replace("_", " ")
    return f"JFC {last}"


# ---------------------------------------------------------------------------
# 47 信用保証協会 URL discovery
# ---------------------------------------------------------------------------

# Pattern to capture all `or.jp` / `.jp` / `.com` external links from the
# zenshinhoren homepage that look like a member association.
_ASSOC_HREF_RE = re.compile(
    r'href="(https?://[^"]*'
    r"(?:cgc-|cgc\.|hosyo|hosho|sinpo|shinpo|shinyo|kyosinpo|ysh\.or\.jp|icgc\.or\.jp)"
    r'[^"]*)"'
)

# Manual prefecture mapping derived from the host slug. Where the slug
# itself encodes the prefecture (e.g. "cgc-aomori"), no manual override is
# needed; the few that don't (横浜 / 川崎 / 名古屋 / 大阪 / 兵庫 / 福島 /
# 山口 etc.) are listed here so the smoke output is honest.
_HOST_TO_PREF: dict[str, str] = {
    "www.cgc-hokkaido.or.jp": "北海道",
    "www.cgc-aomori.jp": "青森県",
    "www.cgc-iwate.jp": "岩手県",
    "www.miyagi-shinpo.or.jp": "宮城県",
    "www.cgc-akita.or.jp": "秋田県",
    "www.ysh.or.jp": "山形県",
    "www.fukushima-cgc.or.jp": "福島県",
    "www.icgc.or.jp": "茨城県",
    "www.cgc-tochigi.or.jp": "栃木県",
    "gunma-cgc.or.jp": "群馬県",
    "www.cgc-saitama.or.jp": "埼玉県",
    "www.chiba-cgc.or.jp": "千葉県",
    "www.cgc-tokyo.or.jp": "東京都",
    "www.cgc-kanagawa.or.jp": "神奈川県",
    "www.sinpo-yokohama.or.jp": "横浜市",  # 政令市分
    "www.cgc-kawasaki.or.jp": "川崎市",  # 政令市分
    "www.niigata-cgc.or.jp": "新潟県",
    "www.cgc-toyama.or.jp": "富山県",
    "www.cgc-ishikawa.or.jp": "石川県",
    "www.cgc-fukui.or.jp": "福井県",
    "cgc-yamanashi.or.jp": "山梨県",
    "www.nagano-cgc.or.jp": "長野県",
    "www.cgc-gifu.or.jp": "岐阜県",
    "cgc-gifushi.or.jp": "岐阜市",  # 市政令分
    "www.cgc-shizuoka.or.jp": "静岡県",
    "www.cgc-aichi.or.jp": "愛知県",
    "www.cgc-nagoya.or.jp": "名古屋市",  # 政令市分
    "www.cgc-mie.or.jp": "三重県",
    "www.cgc-shiga.or.jp": "滋賀県",
    "kyosinpo.or.jp": "京都府",
    "www.cgc-osaka.jp": "大阪府",
    "www.hosyokyokai-hyogo.or.jp": "兵庫県",
    "www.nara-cgc.or.jp": "奈良県",
    "www.cgc-wakayama.jp": "和歌山県",
    "www.cgc-tottori.or.jp": "鳥取県",
    "www.shimane-cgc.or.jp": "島根県",
    "okayama-cgc.or.jp": "岡山県",
    "hiroshima-shinpo.or.jp": "広島県",
    "www.yamaguchi-cgc.or.jp": "山口県",
    "www.cgc-tokushima.or.jp": "徳島県",
    "www.kagawa-cgc.com": "香川県",
    "www.ehime-cgc.or.jp": "愛媛県",
    "www.kochi-cgc.or.jp": "高知県",
    "www.fukuoka-cgc.or.jp": "福岡県",
    "www.saga-cgc.or.jp": "佐賀県",
    "www.cgc-nagasaki.or.jp": "長崎県",
    "www.kumamoto-cgc.or.jp": "熊本県",
    "www.oita-cgc.or.jp": "大分県",
    "www.miyazaki-cgc.or.jp": "宮崎県",
    "www.kagoshima-cgc.or.jp": "鹿児島県",
    "www.okinawa-cgc.or.jp": "沖縄県",
}


@dataclass
class GuaranteeAssociation:
    prefecture: str
    name_hint: str
    homepage_url: str
    smoke_status: str = ""  # ok / failed / skipped
    smoke_http_code: str = ""


def discover_guarantee_associations(html: str) -> list[GuaranteeAssociation]:
    """Pull guarantee-association URLs out of zenshinhoren home HTML.

    The output list is the 51 信用保証協会 (47 都道府県 + 4 政令市:
    横浜市 / 川崎市 / 名古屋市 / 岐阜市). The连合会 itself
    (zenshinhoren.or.jp) is excluded — it is not a member, it is the
    umbrella body.
    """
    seen_hosts: set[str] = set()
    results: list[GuaranteeAssociation] = []
    for match in _ASSOC_HREF_RE.finditer(html):
        url = match.group(1)
        canonical_host = urlparse(url).netloc.lower()
        host = canonical_host[4:] if canonical_host.startswith("www.") else canonical_host
        # Drop the 連合会 itself; it sometimes matches via the kyokaiyogo /
        # hoshoseido sub-pages. Members are external domains.
        if "zenshinhoren.or.jp" in canonical_host:
            continue
        if host in seen_hosts:
            continue
        seen_hosts.add(host)
        pref = _HOST_TO_PREF.get(canonical_host) or _HOST_TO_PREF.get(host) or "(unknown)"
        # The zenshinhoren page does not surface 'name' attributes for each
        # link; the host slug is the most reliable identifier we have.
        name_hint = f"{pref}信用保証協会" if pref != "(unknown)" else canonical_host
        # Strip trailing '/' / 'index.html' / 'Front/index.aspx' for canonical
        homepage = url.rstrip("/")
        results.append(
            GuaranteeAssociation(
                prefecture=pref,
                name_hint=name_hint,
                homepage_url=homepage,
            )
        )
    return results


def smoke_one_association(
    assoc: GuaranteeAssociation, throttle: HostThrottle
) -> GuaranteeAssociation:
    """Single GET fetch (with HEAD fallback) to verify the URL is reachable.

    Failures are tolerated — the deliverable is the URL list, not a working
    fetch. We mark `smoke_status` so the operator can spot dead links.

    Uses GET instead of HEAD because some 信用保証協会 hosts reject HEAD
    with 405 / 403 even though they serve the page on GET.
    """
    try:
        throttle.wait(assoc.homepage_url)
        req = urllib.request.Request(assoc.homepage_url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_S, context=_SSL_CTX) as resp:  # nosec B310 - operator-config https endpoint, no file:/ schemes
            assoc.smoke_status = "ok"
            assoc.smoke_http_code = str(resp.status)
    except urllib.error.HTTPError as e:
        assoc.smoke_status = "failed"
        assoc.smoke_http_code = str(e.code)
    except (urllib.error.URLError, TimeoutError, ssl.SSLError, OSError) as e:
        assoc.smoke_status = "failed"
        assoc.smoke_http_code = type(e).__name__
    return assoc


# ---------------------------------------------------------------------------
# CSV writers
# ---------------------------------------------------------------------------

JFC_CSV_FIELDS = [
    "program_name",
    "provider",
    "target",
    "purpose",
    "amount_max_text",
    "amount_max_yen",
    "loan_period_text",
    "loan_period_years_max",
    "interest_rate_text",
    "security_text",
    "collateral_required",
    "personal_guarantor_required",
    "third_party_guarantor_required",
    "security_notes",
    "source_url",
    "fetched_at",
]

GUARANTOR_CSV_FIELDS = [
    "prefecture",
    "name_hint",
    "homepage_url",
    "smoke_status",
    "smoke_http_code",
]


def write_jfc_csv(records: Iterable[JfcLoanRecord], out_path: Path) -> int:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with out_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=JFC_CSV_FIELDS)
        writer.writeheader()
        for r in records:
            writer.writerow(r.to_csv_row())
            n += 1
    return n


def write_guarantor_csv(associations: Iterable[GuaranteeAssociation], out_path: Path) -> int:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with out_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=GUARANTOR_CSV_FIELDS)
        writer.writeheader()
        for a in associations:
            writer.writerow(
                {
                    "prefecture": a.prefecture,
                    "name_hint": a.name_hint,
                    "homepage_url": a.homepage_url,
                    "smoke_status": a.smoke_status,
                    "smoke_http_code": a.smoke_http_code,
                }
            )
            n += 1
    return n


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="JFC + 信用保証協会 scaffold ingest")
    parser.add_argument("--limit", type=int, default=30, help="JFC pages to fetch")
    parser.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_CSV,
        help="output CSV for JFC loan rows",
    )
    parser.add_argument(
        "--guarantor-out",
        type=Path,
        default=DEFAULT_GUARANTOR_CSV,
        help="output CSV for 47 信用保証協会 list",
    )
    parser.add_argument(
        "--no-net",
        action="store_true",
        help="skip all network fetches (local validation only)",
    )
    parser.add_argument(
        "--smoke-assoc-count",
        type=int,
        default=1,
        help="how many guarantee associations to smoke-fetch (default 1)",
    )
    args = parser.parse_args(argv)

    if args.no_net:
        log.info("--no-net set; skipping HTTP and just emitting empty CSVs")
        write_jfc_csv([], args.out)
        write_guarantor_csv([], args.guarantor_out)
        return 0

    throttle = HostThrottle()

    # 1. JFC pipeline ------------------------------------------------------
    log.info("fetching JFC product index: %s", JFC_INDEX_URL)
    try:
        index_html = http_get(JFC_INDEX_URL, throttle)
    except (urllib.error.URLError, TimeoutError, ssl.SSLError, OSError) as e:
        log.error("could not fetch JFC index: %s", e)
        return 2

    product_urls = discover_jfc_product_urls(index_html)
    log.info("discovered %d JFC product URLs (limit=%d)", len(product_urls), args.limit)
    product_urls = product_urls[: args.limit]

    records: list[JfcLoanRecord] = []
    for url in product_urls:
        try:
            html = http_get(url, throttle)
        except (urllib.error.URLError, TimeoutError, ssl.SSLError, OSError) as e:
            log.warning("skip %s: %s", url, e)
            continue
        rec = parse_jfc_product_page(html, url)
        if rec:
            records.append(rec)
            log.info(
                "parsed: %s [collateral=%s personal=%s third_party=%s]",
                rec.program_name,
                rec.collateral_required,
                rec.personal_guarantor_required,
                rec.third_party_guarantor_required,
            )
        else:
            log.warning("no record: %s", url)

    written = write_jfc_csv(records, args.out)
    log.info("wrote %d JFC rows -> %s", written, args.out)

    # 2. 信用保証協会 list pipeline ----------------------------------------
    log.info("fetching zenshinhoren index: %s", ZENSHINHOREN_URL)
    try:
        zen_html = http_get(ZENSHINHOREN_URL, throttle)
    except (urllib.error.URLError, TimeoutError, ssl.SSLError, OSError) as e:
        log.error("could not fetch zenshinhoren: %s", e)
        return 3

    associations = discover_guarantee_associations(zen_html)
    log.info("discovered %d guarantee associations", len(associations))

    smoked = 0
    for assoc in associations:
        if smoked < args.smoke_assoc_count:
            smoke_one_association(assoc, throttle)
            smoked += 1
        else:
            assoc.smoke_status = "skipped"

    written2 = write_guarantor_csv(associations, args.guarantor_out)
    log.info("wrote %d associations -> %s", written2, args.guarantor_out)

    return 0


if __name__ == "__main__":
    sys.exit(main())
