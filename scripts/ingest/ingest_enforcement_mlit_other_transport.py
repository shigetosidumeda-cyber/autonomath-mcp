#!/usr/bin/env python3
"""Ingest 国土交通省 (non-vehicle transport) enforcement records.

PRIMARY SOURCE — MLIT ネガティブ情報等検索サイト (nega-inf):
  https://www.mlit.go.jp/nega-inf/cgi-bin/search.cgi
  Centralized search for all MLIT 行政処分 / 行政指導 records.
  Categories used (jigyoubunya):
    jidousyaseibi  自動車整備事業者 (~820 records, includes 認証取消・指定取消)
    tetudou        鉄道事業者       (~230 records)
    koukuu         航空事業者       (~30 records)

  Each row provides: 処分等年月日, 処分等を行った者, 事業者名+法人番号,
  住所, 根拠法令, 処分等の種類, 違反行為の概要 — near-perfect schema match.

SECONDARY SOURCE — MLIT report/press archive (text-mining fallback):
  Aviation:  https://www.mlit.go.jp/report/press/{era}koku_news.html
  Railway:   https://www.mlit.go.jp/report/press/{era}tetsudo_news.html
  Port:      https://www.mlit.go.jp/report/press/{era}kowan_news.html (no records found)
  Warehouse: https://www.mlit.go.jp/seisakutokatsu/freight/news.html (no records found)
  Press releases are filtered by title keywords (業務改善命令, 厳重注意, etc.).

Excluded (already covered by other ingest scripts):
  - 自動車運送事業 (バス/タクシー/トラック) — see ingest_enforcement_mlit_unyu.py (#27)
  - 道路運送法・道路運送車両法・自動車運送事業法 — same (#27)
  - 船舶/海事 — see ingest_enforcement_mlit_kaiji_bureau.py (#28)

Schema target (autonomath.db):
    am_entities (canonical_id = AM-ENF-MLIT-OTHER-{topic}-{seq})
    am_enforcement_detail (entity_id, target_name, enforcement_kind,
                           issuing_authority, issuance_date, reason_summary,
                           related_law_ref, source_url, source_fetched_at)

enforcement_kind mapping (text => CHECK enum):
    取消 / 取り消し / 認証取消 / 指定取消  -> license_revoke
    事業停止 / 業務停止 / 交付停止         -> business_improvement
    解任命令 / 改善命令 / 業務改善勧告      -> business_improvement
    厳重注意 / 注意                       -> other
    指示 / 検査指示 / 行政指導 / 警告      -> other

CLI:
    python scripts/ingest/ingest_enforcement_mlit_other_transport.py \
        --db autonomath.db [--topics aviation,rail,port,warehouse,seibi] \
        [--limit 400] [--dry-run]
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import re
import sqlite3
import sys
import time
import urllib.parse
from dataclasses import dataclass
from pathlib import Path

try:
    import httpx
except ImportError as e:  # pragma: no cover
    sys.exit(f"httpx required: {e}")


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_LOG = logging.getLogger("autonomath.ingest.enforcement_mlit_other_transport")

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_DB = REPO_ROOT / "autonomath.db"

USER_AGENT = (
    "jpintel-mcp-ingest/1.0 "
    "(+https://jpcite.com; contact=ops@jpcite.com)"
)
PER_REQUEST_DELAY_SEC = 0.5
HTTP_TIMEOUT_SEC = 60.0
MAX_RETRIES = 3
PAGE_FETCH_LIMIT_DEFAULT = None  # No limit by default

# Era key sequence (newest -> oldest). 'koku_news.html' is the current year.
ERA_KEYS = [
    "",  # current year (no prefix)
    "R7", "R6", "R5", "R4", "R3", "R2",
    "H31", "H30", "H29", "H28", "H27", "H26", "H25", "H24",
    "H23", "H22", "H21", "H20",
]

# Press release archive base URL pattern.
ARCHIVE_BASE = "https://www.mlit.go.jp/report/press"

# Special-case archive URLs that don't fit the simple {era}{topic}_news.html
# pattern (per actual MLIT archive listings).
ARCHIVE_OVERRIDES: dict[str, dict[str, str]] = {
    "aviation": {
        "R5": f"{ARCHIVE_BASE}/R5koku_news_00003.html",
    },
}

# Topic configuration: which press releases to harvest.
TOPICS: dict[str, dict] = {
    "aviation": {
        "label": "航空局",
        "authority": "国土交通省 航空局",
        "topic_slug": "aviation",
        "law_basis": "航空法",
        "archive_basename": "koku_news.html",
        # URL prefix substring that identifies this topic's press release pages
        # (used as a positive filter when we walk archive indexes).
        "url_prefixes": ("/report/press/cab", "/report/press/kouku", "/report/press/100"),
        # Title keywords that indicate enforcement action.
        "title_must_match": (
            "業務改善命令", "業務改善勧告", "業務改善",
            "改善命令", "改善勧告",
            "厳重注意",
            "事業許可取消", "経営許可取消",
            "許可取消", "認可取消", "認定取消",
            "免許取消", "資格停止",
            "操縦士に対する行政処分",
            "操縦士等に対する行政処分",
            "操縦士免許取消", "機長免許取消",
            "事業者に対する処分", "に対する処分",
            "に対する警告",
            "業務停止命令", "事業停止",
            "認証取消",
            # Additional patterns from MLIT press archives:
            "航空従事者に対する",
            "機長等に対する行政処分",
            "に対する不利益処分",
            "改善指示",
            "認定の効力停止",
            "保安対策の改善",
            "飲酒に起因",
        ),
        # Title keywords to EXCLUDE (false positives — name conflicts).
        "title_must_not_match": (
            "ガイドライン", "検討会", "公募",
            "募集", "委員会", "審議",
            "結果概要",  # info-only summaries
            "意見",
            "認可申請",  # routine licensing announcements
        ),
    },
    "rail": {
        "label": "鉄道局",
        "authority": "国土交通省 鉄道局",
        "topic_slug": "rail",
        "law_basis": "鉄道事業法",
        "archive_basename": "tetsudo_news.html",
        "url_prefixes": ("/report/press/tetsudo", "/report/press/tetudo"),
        "title_must_match": (
            "業務改善命令", "業務改善勧告", "改善命令", "改善勧告",
            "事業改善命令", "鉄道事業改善",
            "厳重注意",
            "認定取消", "認可取消", "許可取消",
            "事業許可取消",
            "業務停止",
            "の取消処分",  # for "に対する認定の取消処分" pattern
            "に対する処分", "に対する警告",
            # Additional patterns from MLIT 鉄道局 press archives:
            "改善指示",
            "に対する不利益処分",
            "監督命令",
            "動力車操縦者運転免許の取消",
            "運転免許の取消",
            "認定の取消処分",
        ),
        "title_must_not_match": (
            "認可申請", "ガイドライン", "検討会", "公募",
            "募集", "委員会", "審議",
            "認可について",  # 運賃 認可 announcements (usually routine)
            "誘客促進",  # info-only
            "改善モデル",
        ),
    },
    "port": {
        "label": "港湾局",
        "authority": "国土交通省 港湾局",
        "topic_slug": "port",
        "law_basis": "港湾運送事業法",
        "archive_basename": "kowan_news.html",
        "url_prefixes": ("/report/press/port", "/report/press/kowan"),
        "title_must_match": (
            "業務改善命令", "業務改善勧告", "改善命令", "改善勧告",
            "事業改善命令",
            "厳重注意",
            "認可取消", "許可取消", "認定取消",
            "業務停止", "事業停止",
            "に対する処分", "に対する警告",
        ),
        "title_must_not_match": (
            "認可申請", "ガイドライン", "検討会", "公募",
            "募集", "委員会", "審議",
        ),
    },
    "warehouse": {
        "label": "物流・自動車局",
        "authority": "国土交通省 物流・自動車局",
        "topic_slug": "warehouse",
        "law_basis": "倉庫業法",
        # Single archive page (not yearly).
        "archive_basename": None,
        "archive_urls": (
            "https://www.mlit.go.jp/seisakutokatsu/freight/news.html",
        ),
        "url_prefixes": ("/report/press/tokatsu", "/report/press/jidosha"),
        "title_must_match": (
            "倉庫業", "倉庫業法",
            "業務改善命令", "改善命令",
            "厳重注意",
            "認可取消", "許可取消", "登録取消",
            "業務停止", "事業停止",
            "に対する処分", "に対する警告",
        ),
        "title_must_not_match": (
            "認可申請", "ガイドライン", "検討会",
            "公募", "募集", "委員会", "審議",
        ),
    },
}


# Nega-inf (MLIT centralized 行政処分 search) categories.
# These are the PRIMARY data source. Each category corresponds to a
# `jigyoubunya` query parameter on the nega-inf search.cgi endpoint.
NEGAINF_BASE = "https://www.mlit.go.jp/nega-inf/cgi-bin/search.cgi"
NEGAINF_TOPICS: dict[str, dict] = {
    "seibi": {
        "label": "自動車整備事業者",
        "topic_slug": "seibi",
        "jigyoubunya": "jidousyaseibi",
        "default_law": "道路運送車両法",
        "default_authority": "国土交通省 物流・自動車局",
    },
    "rail_negi": {
        "label": "鉄道事業者 (negi-inf)",
        "topic_slug": "rail_negi",
        "jigyoubunya": "tetudou",
        "default_law": "鉄道事業法",
        "default_authority": "国土交通省 鉄道局",
    },
    "aviation_negi": {
        "label": "航空事業者 (negi-inf)",
        "topic_slug": "aviation_negi",
        "jigyoubunya": "koukuu",
        "default_law": "航空法",
        "default_authority": "国土交通省 航空局",
    },
}


# Punishment classification (regex -> kind enum).
PUNISH_PATTERNS: list[tuple[str, str]] = [
    # license_revoke: explicit revocation
    ("事業許可取消", "license_revoke"),
    ("経営許可取消", "license_revoke"),
    ("免許取消", "license_revoke"),
    ("認定取消", "license_revoke"),
    ("認可取消", "license_revoke"),
    ("許可取消", "license_revoke"),
    ("登録取消", "license_revoke"),
    ("認証取消", "license_revoke"),
    ("認定の取消", "license_revoke"),
    ("認可の取消", "license_revoke"),
    ("許可の取消", "license_revoke"),
    ("免許の取消", "license_revoke"),
    ("登録の取消", "license_revoke"),
    ("資格取消", "license_revoke"),
    ("資格の取消", "license_revoke"),
    ("資格停止", "license_revoke"),
    # business_improvement (中位 — order or recommendation)
    ("業務改善命令", "business_improvement"),
    ("事業改善命令", "business_improvement"),
    ("業務改善勧告", "business_improvement"),
    ("改善命令", "business_improvement"),
    ("改善勧告", "business_improvement"),
    ("業務停止命令", "business_improvement"),
    ("業務停止", "business_improvement"),
    ("事業停止", "business_improvement"),
    # business_improvement: 解任命令 / 交付停止 / 認証停止
    ("自動車検査員の解任命令", "business_improvement"),
    ("解任命令", "business_improvement"),
    ("保安基準適合証等の交付停止", "business_improvement"),
    ("交付停止", "business_improvement"),
    ("認証の停止", "business_improvement"),
    ("認証停止", "business_improvement"),
    ("指定停止", "business_improvement"),
    ("指定の停止", "business_improvement"),
    # other: 警告 / 厳重注意 / 注意 / 指示 / 行政指導
    ("厳重注意", "other"),
    ("警告", "other"),
    ("検査指示", "other"),
    ("行政指導", "other"),
    ("是正勧告", "other"),
    ("指示", "other"),
    ("注意", "other"),
]


# Law basis pattern detection (text in title / body -> reference name + article).
# We extract the article suffix (第N条) when present.
LAW_NAME_PATTERNS: list[tuple[str, str]] = [
    ("航空法第", "航空法"),
    ("航空法施行規則", "航空法施行規則"),
    ("航空法", "航空法"),
    ("鉄道事業法第", "鉄道事業法"),
    ("鉄道事業法", "鉄道事業法"),
    ("軌道法", "軌道法"),
    ("港湾運送事業法第", "港湾運送事業法"),
    ("港湾運送事業法", "港湾運送事業法"),
    ("倉庫業法第", "倉庫業法"),
    ("倉庫業法", "倉庫業法"),
    ("貨物利用運送事業法", "貨物利用運送事業法"),
]

ARTICLE_RE = re.compile(r"第([\d０-９]+)条(?:第([\d０-９]+)項)?(?:第([\d０-９]+)号)?")


# Date patterns in archive index pages.
# Note: older MLIT archives use broken HTML where <dt> is closed with </p>
# instead of </dt>. We allow either close tag.
DATE_RE_ISO = re.compile(
    r"<dt[^>]*>\s*(\d{4})/(\d{1,2})/(\d{1,2})\s*</(?:dt|p)\s*>"
)
DATE_RE_KANJI = re.compile(
    r"<dt[^>]*>\s*(20\d\d)年(\d{1,2})月(\d{1,2})日\s*</(?:dt|p)\s*>"
)

# Press release link extraction: <a href="/report/press/...html">title</a>
LINK_RE = re.compile(
    r'<a\s+href="(/report/press/[^"]+\.html)"[^>]*>(.*?)</a>',
    re.DOTALL,
)

# Body content extraction for individual press release page.
# The MLIT template uses h2 class="title" for the headline and p class="date"
# for the date. The body is a <p> inside <div class="clearfix">.
TITLE_RE = re.compile(r'<h2\s+class="title">(.*?)</h2>', re.DOTALL)
DATE_BODY_RE = re.compile(
    r'<p\s+class="date(?:\s+mb20)?">\s*(.*?)\s*</p>', re.DOTALL
)
BODY_RE = re.compile(
    r'<div\s+class="clearfix">\s*<p\s+class="date(?:\s+mb20)?">.*?</p>'
    r'\s*<p>(.*?)</p>',
    re.DOTALL,
)

# Reiwa / Heisei date strings inside the body.
DATE_REIWA_KANJI_RE = re.compile(r"令和([\d０-９]+)年([\d０-９]+)月([\d０-９]+)日")
DATE_HEISEI_KANJI_RE = re.compile(r"平成([\d０-９]+)年([\d０-９]+)月([\d０-９]+)日")
DATE_PLAIN_KANJI_RE = re.compile(r"(20\d\d)年([\d０-９]+)月([\d０-９]+)日")


def _zen_to_han(text: str) -> str:
    """Convert full-width digits to half-width."""
    out = []
    for ch in text:
        if "０" <= ch <= "９":
            out.append(chr(ord("0") + (ord(ch) - 0xFF10)))
        else:
            out.append(ch)
    return "".join(out)


def parse_kanji_date(text: str) -> str | None:
    """Parse a Reiwa / Heisei / 西暦 kanji date string to ISO yyyy-mm-dd.

    Returns the FIRST date encountered.
    """
    text = _zen_to_han(text)
    m = DATE_REIWA_KANJI_RE.search(text)
    if m:
        try:
            y = 2018 + int(m.group(1))
            return dt.date(y, int(m.group(2)), int(m.group(3))).isoformat()
        except (ValueError, TypeError):
            pass
    m = DATE_HEISEI_KANJI_RE.search(text)
    if m:
        try:
            y = 1988 + int(m.group(1))
            return dt.date(y, int(m.group(2)), int(m.group(3))).isoformat()
        except (ValueError, TypeError):
            pass
    m = DATE_PLAIN_KANJI_RE.search(text)
    if m:
        try:
            return dt.date(
                int(m.group(1)), int(m.group(2)), int(m.group(3))
            ).isoformat()
        except (ValueError, TypeError):
            pass
    return None


def map_punishment(text: str) -> tuple[str, str] | tuple[None, None]:
    """Map title/body text -> (raw matched keyword, enforcement_kind enum).

    Returns the FIRST matching pattern (most specific first by ordering).
    """
    for kw, kind in PUNISH_PATTERNS:
        if kw in text:
            return kw, kind
    return None, None


def extract_law_ref(text: str, default_law: str) -> str:
    """Extract law name + article number reference from title/body.

    If no specific law name is found, fallback to default_law for the topic.
    """
    for kw, name in LAW_NAME_PATTERNS:
        if kw in text:
            idx = text.find(kw)
            after = text[idx + len(kw): idx + len(kw) + 80]
            am = ARTICLE_RE.match(after)
            if am:
                # Build "法名 第X条第Y項第Z号"
                article = _zen_to_han(am.group(0))
                return f"{name} {article}"
            return name
    return default_law


def strip_html(text: str) -> str:
    """Remove HTML tags + collapse whitespace."""
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"&lt;", "<", text)
    text = re.sub(r"&gt;", ">", text)
    text = re.sub(r"&quot;", '"', text)
    text = re.sub(r"　", " ", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n+", "\n", text).strip()
    return text


def extract_target_name(title: str) -> str | None:
    """Try to extract the target entity name from title.

    Common patterns:
      "<NAME>株式会社に対する...について"
      "<NAME>(株)に対する..."
      "<NAME> に対する処分について"
      "操縦士に対する行政処分等について" -> None (anonymous group)
    """
    title = strip_html(title)
    title = title.replace("　", " ").strip()
    # First, look for "に対する" — name appears before it.
    if "に対する" in title:
        name = title.split("に対する", 1)[0].strip()
        # Trim leading "[<num>]" or roman numeral list markers.
        name = re.sub(r"^[\[\(（【]\s*\d+\s*[\]\)）】]\s*", "", name)
        # Skip if name is generic like "操縦士" / "事業者" alone.
        if name in ("操縦士", "事業者", "機長", "従業員"):
            return None
        # Limit length.
        if 2 <= len(name) <= 80:
            return name
    return None


def normalize_url(url: str) -> str:
    """Normalize MLIT URLs (drop fragments, join host)."""
    if url.startswith("/"):
        return f"https://www.mlit.go.jp{url}"
    return url


# ---------------------------------------------------------------------------
# HTTP client
# ---------------------------------------------------------------------------


class HttpClient:
    def __init__(self) -> None:
        self._client = httpx.Client(
            headers={
                "User-Agent": USER_AGENT,
                "Accept-Language": "ja,en;q=0.5",
            },
            timeout=HTTP_TIMEOUT_SEC,
            follow_redirects=True,
        )
        self._last_fetch: float = 0.0

    def _pace(self) -> None:
        now = time.monotonic()
        wait = PER_REQUEST_DELAY_SEC - (now - self._last_fetch)
        if wait > 0:
            time.sleep(wait)
        self._last_fetch = time.monotonic()

    def get_text(self, url: str) -> tuple[int, str]:
        last_exc: Exception | None = None
        for attempt in range(1, MAX_RETRIES + 1):
            self._pace()
            try:
                r = self._client.get(url)
                if r.status_code == 200:
                    raw = r.content
                    for enc in ("utf-8", "shift_jis", "euc_jp"):
                        try:
                            return r.status_code, raw.decode(enc, errors="strict")
                        except UnicodeDecodeError:
                            continue
                    return r.status_code, raw.decode("utf-8", errors="replace")
                return r.status_code, ""
            except httpx.HTTPError as exc:
                last_exc = exc
                if attempt == MAX_RETRIES:
                    break
                time.sleep(2 ** attempt)
        _LOG.warning("GET text failed url=%s err=%s", url, last_exc)
        return 0, ""

    def post_text(self, url: str, data: dict) -> tuple[int, str]:
        last_exc: Exception | None = None
        for attempt in range(1, MAX_RETRIES + 1):
            self._pace()
            try:
                r = self._client.post(url, data=data)
                if r.status_code == 200:
                    raw = r.content
                    for enc in ("utf-8", "shift_jis", "euc_jp"):
                        try:
                            return r.status_code, raw.decode(enc, errors="strict")
                        except UnicodeDecodeError:
                            continue
                    return r.status_code, raw.decode("utf-8", errors="replace")
                return r.status_code, ""
            except httpx.HTTPError as exc:
                last_exc = exc
                if attempt == MAX_RETRIES:
                    break
                time.sleep(2 ** attempt)
        _LOG.warning("POST text failed url=%s err=%s", url, last_exc)
        return 0, ""

    def close(self) -> None:
        self._client.close()


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


@dataclass
class EnforcementRecord:
    topic: str               # aviation/rail/port/warehouse/seibi/...
    authority: str           # 国土交通省 航空局/...
    title: str               # press release headline
    issuance_date: str       # ISO yyyy-mm-dd
    target_name: str | None
    enforcement_kind: str
    punishment_raw: str
    related_law_ref: str
    reason_summary: str | None
    source_url: str          # individual press release page URL
    archive_url: str         # the index URL where this record was discovered
    houjin_bangou: str | None = None  # 法人番号 (13 digits) when known


# ---------------------------------------------------------------------------
# Index walking
# ---------------------------------------------------------------------------


def archive_urls_for_topic(topic_info: dict) -> list[str]:
    """Return the list of archive index page URLs for a topic."""
    explicit = topic_info.get("archive_urls")
    if explicit:
        return list(explicit)
    base = topic_info.get("archive_basename")
    if not base:
        return []
    urls: list[str] = []
    for era in ERA_KEYS:
        # Check for archive override.
        topic_slug = topic_info.get("topic_slug", "")
        override = ARCHIVE_OVERRIDES.get(topic_slug, {}).get(era)
        if override:
            urls.append(override)
        else:
            urls.append(f"{ARCHIVE_BASE}/{era}{base}")
    return urls


def parse_index(html: str, topic_info: dict) -> list[tuple[str, str, str]]:
    """Parse an archive index HTML page.

    Returns a list of (date_iso, url, title) tuples for press release links
    matching the topic's url_prefixes.
    """
    out: list[tuple[str, str, str]] = []
    if not html:
        return out

    # Use BOTH ISO 2026/04/14 and kanji 2010年12月22日 forms — different
    # MLIT archive vintages mix them.
    date_positions: list[tuple[int, str]] = []
    for date_iter in (DATE_RE_ISO.finditer(html), DATE_RE_KANJI.finditer(html)):
        for m in date_iter:
            try:
                y = int(m.group(1))
                mo = int(m.group(2))
                d = int(m.group(3))
                iso = dt.date(y, mo, d).isoformat()
            except (ValueError, TypeError):
                continue
            date_positions.append((m.end(), iso))
    date_positions.sort()

    if not date_positions:
        return out

    # Find all link positions.
    link_positions: list[tuple[int, str, str]] = []
    for m in LINK_RE.finditer(html):
        url, title_html = m.group(1), m.group(2)
        # Filter by topic url_prefixes.
        url_prefixes = topic_info.get("url_prefixes", ())
        if not any(url.startswith(p) for p in url_prefixes):
            continue
        title = strip_html(title_html)
        if not title:
            continue
        link_positions.append((m.start(), normalize_url(url), title))

    # Pair each link with the most recent preceding date.
    for link_pos, url, title in link_positions:
        candidate_date: str | None = None
        for date_pos, iso in date_positions:
            if date_pos <= link_pos:
                candidate_date = iso
            else:
                break
        if not candidate_date:
            continue
        out.append((candidate_date, url, title))
    return out


def title_matches_topic(title: str, topic_info: dict) -> bool:
    """Check if a press release title matches the topic's enforcement keywords."""
    title_norm = title.replace(" ", "").replace("　", "")
    must_match = topic_info.get("title_must_match", ())
    must_not_match = topic_info.get("title_must_not_match", ())
    if must_match and not any(kw in title_norm for kw in must_match):
        return False
    if must_not_match and any(kw in title_norm for kw in must_not_match):
        return False
    return True


# ---------------------------------------------------------------------------
# Nega-inf (MLIT centralized 行政処分 search) walking
# ---------------------------------------------------------------------------


# Row format on nega-inf list pages:
#  <tr><td class="date">YYYY年MM月DD日</td>
#      <td class="date">XXX運輸局</td>           (only for some categories)
#      <td class="name">事業者名<span>（法人番号）</span></td>
#      <td class="address">住所</td>
#      <td class="punish">処分等の種類</td>
#      <td class="detail"><a class="overview" href="...&no=NNN">概要</a></td></tr>
NEGAINF_ROW_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.DOTALL)
NEGAINF_DATE_RE = re.compile(r"(20\d\d)年(\d{1,2})月(\d{1,2})日")
NEGAINF_NAME_RE = re.compile(
    r'<td\s+class="name"[^>]*>(.*?)(?:<span[^>]*>(?:（|\()(\d{13})(?:）|\))?</span>)?',
    re.DOTALL,
)
NEGAINF_ADDRESS_RE = re.compile(
    r'<td\s+class="address"[^>]*>(.*?)</td>', re.DOTALL
)
NEGAINF_PUNISH_RE = re.compile(
    r'<td\s+class="punish"[^>]*>(.*?)</td>', re.DOTALL
)
NEGAINF_AGENCY_RE = re.compile(
    r'<td\s+class="date"[^>]*>(.*?運輸局.*?|.*?支局.*?|.*?事務所.*?)</td>',
    re.DOTALL,
)
NEGAINF_NO_RE = re.compile(r'no=(\d+)')


@dataclass
class NegaInfRow:
    issuance_date: str          # ISO yyyy-mm-dd
    agency: str | None          # 運輸局 etc.
    name: str                   # 事業者名
    corporate_id: str | None    # 法人番号
    address: str                # 住所
    punish_text: str            # 処分等の種類
    detail_no: str              # detail page NO


def parse_negainf_list(html: str) -> tuple[list[NegaInfRow], int]:
    """Parse a nega-inf search.cgi list page.

    Returns (rows, max_page_number).
    """
    rows: list[NegaInfRow] = []
    if not html:
        return rows, 1
    pages = NEGAINF_NO_RE.findall(html)  # not actually pages; placeholder
    page_nums = re.findall(r"page=(\d+)", html)
    max_page = max((int(p) for p in page_nums), default=1)
    for tr_match in NEGAINF_ROW_RE.finditer(html):
        tr = tr_match.group(1)
        date_m = NEGAINF_DATE_RE.search(tr)
        if not date_m:
            continue
        try:
            iso = dt.date(
                int(date_m.group(1)),
                int(date_m.group(2)),
                int(date_m.group(3)),
            ).isoformat()
        except (ValueError, TypeError):
            continue
        # Agency (運輸局/支局/事務所) — found in 2nd <td class="date">
        agency = None
        agency_m = NEGAINF_AGENCY_RE.search(tr)
        if agency_m:
            agency = strip_html(agency_m.group(1)).strip()
        # Name + corporate id
        name_block_m = re.search(
            r'<td\s+class="name"[^>]*>(.*?)</td>', tr, re.DOTALL
        )
        if not name_block_m:
            continue
        name_block = name_block_m.group(1)
        cid_m = re.search(r"(?:（|\()(\d{13})(?:）|\))", name_block)
        corporate_id = cid_m.group(1) if cid_m else None
        # Strip span and html
        name = re.sub(r"<span[^>]*>.*?</span>", "", name_block, flags=re.DOTALL)
        name = strip_html(name).strip()
        # Address
        addr = ""
        addr_m = NEGAINF_ADDRESS_RE.search(tr)
        if addr_m:
            addr = strip_html(addr_m.group(1)).strip()
        # Punish text
        punish = ""
        punish_m = NEGAINF_PUNISH_RE.search(tr)
        if punish_m:
            punish = strip_html(punish_m.group(1)).strip()
        # Detail no
        detail_m = NEGAINF_NO_RE.search(tr)
        if not detail_m:
            continue
        detail_no = detail_m.group(1)
        rows.append(NegaInfRow(
            issuance_date=iso,
            agency=agency,
            name=name,
            corporate_id=corporate_id,
            address=addr,
            punish_text=punish,
            detail_no=detail_no,
        ))
    return rows, max_page


def fetch_negainf_pages(
    http: HttpClient, jigyoubunya: str
) -> list[NegaInfRow]:
    """Walk all pages of a nega-inf category and return all rows."""
    base_data = {
        "jigyoubunya": jigyoubunya,
        "EID": "search",
        "start_year": "2021",
        "start_month": "1",
        "end_year": "2030",
        "end_month": "12",
        "shobun": "",
        "agency": "",
        "pref": "",
        "jigyousya": "",
    }
    # First page (POST)
    status, html = http.post_text(NEGAINF_BASE, base_data)
    if status != 200 or not html:
        return []
    rows, max_page = parse_negainf_list(html)
    # Subsequent pages (GET with page= param)
    for page in range(2, max_page + 1):
        get_url = (
            f"{NEGAINF_BASE}?jigyoubunya={jigyoubunya}&EID=search"
            f"&start_year=2021&start_month=1&end_year=2030&end_month=12"
            f"&jigyousya=&shobun=&pref=&agency=&page={page}"
        )
        status, html = http.get_text(get_url)
        if status != 200 or not html:
            continue
        page_rows, _ = parse_negainf_list(html)
        rows.extend(page_rows)
    return rows


# Detail page field extraction. The DD content uses <br> for line breaks
# so we capture until </dd>.
def _field_re(label: str) -> re.Pattern:
    return re.compile(
        rf"{re.escape(label)}</dt>\s*<dd[^>]*>(.*?)</dd>", re.DOTALL
    )


NEGAINF_DETAIL_FIELDS = {
    "issuance_date": _field_re("処分等年月日"),
    "agency": _field_re("処分等を行った者"),
    "name": _field_re("事業者名"),
    "site_name": _field_re("事業場名"),
    "site_address": _field_re("事業場住所"),
    "address": _field_re("本社住所"),
    "law": _field_re("根拠法令"),
    "punish_kind": _field_re("処分等の種類"),
    "duration": _field_re("処分等の期間"),
    "reason": _field_re("違反行為の概要"),
}


def parse_negainf_detail(html: str) -> dict[str, str]:
    """Parse a nega-inf detail page (search.cgi?...&no=NNN)."""
    out: dict[str, str] = {}
    if not html:
        return out
    # Try DD-style extraction (the standard MLIT layout uses <dt>label</dt><dd>value</dd>)
    # First normalize: clean up the html block we care about
    for field, regex in NEGAINF_DETAIL_FIELDS.items():
        m = regex.search(html)
        if m:
            val = strip_html(m.group(1)).strip()
            if val:
                out[field] = val
    # Alternative DT/DD pattern fallback
    if "issuance_date" not in out:
        # Look for "処分等年月日" followed by date in plain text
        clean = re.sub(r"<[^>]+>", " ", html)
        clean = re.sub(r"\s+", " ", clean)
        for field, label in [
            ("issuance_date", "処分等年月日"),
            ("agency", "処分等を行った者"),
            ("name", "事業者名"),
            ("site_name", "事業場名"),
            ("site_address", "事業場住所"),
            ("address", "本社住所"),
            ("law", "根拠法令"),
            ("punish_kind", "処分等の種類"),
            ("duration", "処分等の期間"),
            ("reason", "違反行為の概要"),
        ]:
            if field in out:
                continue
            idx = clean.find(label)
            if idx == -1:
                continue
            tail = clean[idx + len(label):idx + len(label) + 400]
            # Skip whitespace, then capture until next label or end
            tail = tail.lstrip()
            # Find next japanese label
            next_idx = len(tail)
            for next_label in [
                "処分等年月日", "処分等を行った者", "事業者名",
                "事業場名", "事業場住所", "本社住所",
                "根拠法令", "処分等の種類", "処分等の期間",
                "違反行為の概要", "検索結果一覧", "国土交通省",
            ]:
                if next_label == label:
                    continue
                p = tail.find(next_label)
                if 0 < p < next_idx:
                    next_idx = p
            val = tail[:next_idx].strip()
            if val:
                out[field] = val
    return out


def negainf_punish_to_kind(punish: str) -> str:
    """Map nega-inf punish text -> enforcement_kind enum."""
    _, kind = map_punishment(punish)
    if kind:
        return kind
    # Default for nega-inf entries when raw text is plain "行政指導"
    if "行政指導" in punish:
        return "other"
    return "other"


def negainf_law_to_ref(law_text: str, default_law: str) -> str:
    """Extract law reference from nega-inf 根拠法令 text."""
    if not law_text:
        return default_law
    # First try the existing extractor (handles 第N条).
    ref = extract_law_ref(law_text, default_law)
    return ref if ref else default_law


def build_negainf_record(
    *,
    row: NegaInfRow,
    detail: dict[str, str],
    topic_slug: str,
    default_authority: str,
    default_law: str,
    detail_url: str,
) -> EnforcementRecord | None:
    """Convert a nega-inf row + detail dict into an EnforcementRecord."""
    issuance_date = detail.get("issuance_date") or ""
    if issuance_date:
        # Convert "2026年4月14日" to ISO
        m = NEGAINF_DATE_RE.search(issuance_date)
        if m:
            try:
                issuance_date = dt.date(
                    int(m.group(1)), int(m.group(2)), int(m.group(3))
                ).isoformat()
            except (ValueError, TypeError):
                issuance_date = row.issuance_date
        else:
            issuance_date = row.issuance_date
    else:
        issuance_date = row.issuance_date
    agency = detail.get("agency", row.agency or default_authority).strip()
    if not agency:
        agency = default_authority
    # Authority should include 国土交通省 prefix if it's just 運輸局 / 支局
    if "国土交通省" not in agency:
        agency = f"国土交通省 {agency}"
    name = detail.get("name", row.name).strip()
    # Strip 法人番号 from name if present
    name = re.sub(r"（法人番号\d+）", "", name).strip()
    name = re.sub(r"（\d{13}）", "", name).strip()
    if not name:
        return None
    punish = detail.get("punish_kind", row.punish_text).strip()
    kind = negainf_punish_to_kind(punish)
    raw_law = detail.get("law", "")
    law_ref = negainf_law_to_ref(raw_law, default_law)
    reason = detail.get("reason", "").strip()
    duration = detail.get("duration", "").strip()
    site_name = detail.get("site_name", "").strip()
    site_addr = detail.get("site_address", "").strip()
    summary_parts = []
    if reason:
        summary_parts.append(f"違反内容: {reason}")
    if duration:
        summary_parts.append(f"期間: {duration}")
    if site_name:
        summary_parts.append(f"事業場: {site_name}")
    if site_addr:
        summary_parts.append(f"事業場住所: {site_addr}")
    elif row.address:
        summary_parts.append(f"本社住所: {row.address}")
    summary = " / ".join(summary_parts)[:500] if summary_parts else None
    title = f"{name}に対する{punish}"
    return EnforcementRecord(
        topic=topic_slug,
        authority=agency,
        title=title,
        issuance_date=issuance_date,
        target_name=name,
        enforcement_kind=kind,
        punishment_raw=punish,
        related_law_ref=law_ref,
        reason_summary=summary,
        source_url=detail_url,
        archive_url=NEGAINF_BASE,
        houjin_bangou=row.corporate_id,
    )


# ---------------------------------------------------------------------------
# Press release detail extraction
# ---------------------------------------------------------------------------


def extract_record(
    *,
    html: str,
    topic_slug: str,
    authority: str,
    default_law: str,
    page_url: str,
    archive_url: str,
    fallback_date: str,
    fallback_title: str,
) -> EnforcementRecord | None:
    """Parse an individual press release HTML page into an EnforcementRecord."""
    if not html:
        return None
    title = fallback_title
    tm = TITLE_RE.search(html)
    if tm:
        title = strip_html(tm.group(1))
    issuance_date = fallback_date
    db = DATE_BODY_RE.search(html)
    if db:
        body_date_str = strip_html(db.group(1))
        parsed = parse_kanji_date(body_date_str)
        if parsed:
            issuance_date = parsed
    body = ""
    bm = BODY_RE.search(html)
    if bm:
        body = strip_html(bm.group(1))
    full_text = title + "\n" + body
    punish_raw, kind = map_punishment(full_text)
    if not punish_raw or not kind:
        return None
    target_name = extract_target_name(title)
    if not target_name:
        # Extract from body if title doesn't yield a clear corp name.
        for body_seg in body.split("\n")[:8]:
            t2 = extract_target_name(body_seg)
            if t2:
                target_name = t2
                break
    if not target_name:
        # Anonymous (e.g. 操縦士に対する行政処分) — use a synthetic name.
        target_name = title[:60]
    related_law_ref = extract_law_ref(full_text, default_law)
    summary = body[:500].strip() if body else None
    return EnforcementRecord(
        topic=topic_slug,
        authority=authority,
        title=title,
        issuance_date=issuance_date,
        target_name=target_name,
        enforcement_kind=kind,
        punishment_raw=punish_raw,
        related_law_ref=related_law_ref,
        reason_summary=summary,
        source_url=page_url,
        archive_url=archive_url,
    )


# ---------------------------------------------------------------------------
# DB layer
# ---------------------------------------------------------------------------


def open_db(db_path: Path) -> sqlite3.Connection:
    if not db_path.exists():
        raise SystemExit(f"DB not found: {db_path}")
    conn = sqlite3.connect(str(db_path), timeout=300.0)
    conn.execute("PRAGMA busy_timeout = 300000")
    conn.execute("PRAGMA journal_mode = WAL")
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='am_enforcement_detail'"
    ).fetchone()
    if not row:
        conn.close()
        raise SystemExit("am_enforcement_detail table missing")
    return conn


def load_existing_keys(conn: sqlite3.Connection) -> set[tuple[str, str, str, str]]:
    keys: set[tuple[str, str, str, str]] = set()
    for r in conn.execute(
        "SELECT IFNULL(issuing_authority, ''), issuance_date, "
        "IFNULL(target_name, ''), IFNULL(enforcement_kind, '') "
        "FROM am_enforcement_detail"
    ):
        keys.add((r[0], r[1], r[2], r[3]))
    return keys


def load_existing_source_urls(conn: sqlite3.Connection) -> set[str]:
    """Also dedup by source_url since some titles are very generic."""
    urls: set[str] = set()
    for r in conn.execute(
        "SELECT source_url FROM am_enforcement_detail "
        "WHERE source_url IS NOT NULL AND source_url != ''"
    ):
        urls.add(r[0])
    return urls


def next_seq(conn: sqlite3.Connection, topic_slug: str) -> int:
    prefix = f"AM-ENF-MLIT-OTHER-{topic_slug}-"
    row = conn.execute(
        """SELECT MAX(CAST(SUBSTR(canonical_id, LENGTH(?) + 1) AS INTEGER))
           FROM am_entities
           WHERE canonical_id LIKE ? || '%'""",
        (prefix, prefix),
    ).fetchone()
    if row and row[0]:
        return int(row[0]) + 1
    return 1


def upsert_record(
    conn: sqlite3.Connection,
    rec: EnforcementRecord,
    canonical_id: str,
    fetched_at: str,
) -> str:
    raw_json = {
        "topic": rec.topic,
        "title": rec.title,
        "authority": rec.authority,
        "issuance_date": rec.issuance_date,
        "target_name": rec.target_name,
        "enforcement_kind": rec.enforcement_kind,
        "punishment_raw": rec.punishment_raw,
        "related_law_ref": rec.related_law_ref,
        "reason_summary": rec.reason_summary,
        "source_url": rec.source_url,
        "archive_url": rec.archive_url,
        "fetched_at": fetched_at,
        "source": "mlit_other_transport_press",
    }
    domain = urllib.parse.urlparse(rec.source_url).netloc

    cur = conn.execute(
        """INSERT OR IGNORE INTO am_entities (
            canonical_id, record_kind, source_topic, primary_name,
            confidence, source_url, source_url_domain, fetched_at, raw_json
        ) VALUES (?, 'enforcement', ?, ?, ?, ?, ?, ?, ?)""",
        (
            canonical_id,
            f"mlit_other_{rec.topic}",
            rec.target_name or rec.title[:80],
            0.85,
            rec.source_url,
            domain,
            fetched_at,
            json.dumps(raw_json, ensure_ascii=False, separators=(",", ":")),
        ),
    )
    if cur.rowcount == 0:
        return "skip"

    conn.execute(
        """INSERT INTO am_enforcement_detail (
            entity_id, houjin_bangou, target_name, enforcement_kind,
            issuing_authority, issuance_date, reason_summary,
            related_law_ref, source_url, source_fetched_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            canonical_id,
            rec.houjin_bangou,
            rec.target_name,
            rec.enforcement_kind,
            rec.authority,
            rec.issuance_date,
            rec.reason_summary,
            rec.related_law_ref,
            rec.source_url,
            fetched_at,
        ),
    )
    return "insert"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    all_topics = list(TOPICS.keys()) + list(NEGAINF_TOPICS.keys())
    ap.add_argument("--topics", type=str, default=",".join(all_topics),
                    help=f"comma-separated topic codes (allowed: {','.join(all_topics)})")
    ap.add_argument("--limit", type=int, default=None,
                    help="stop after this many INSERTs (across all topics)")
    ap.add_argument("--per-topic-page-limit", type=int, default=None,
                    help="cap pages walked per topic (smoke test)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--verbose", "-v", action="store_true")
    ap.add_argument("--log-file", type=Path, default=None)
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    topics = [t.strip() for t in args.topics.split(",") if t.strip()]
    all_known = set(TOPICS) | set(NEGAINF_TOPICS)
    unknown = [t for t in topics if t not in all_known]
    if unknown:
        _LOG.error("unknown topics: %s (allowed: %s)", unknown, sorted(all_known))
        return 2

    press_topics = [t for t in topics if t in TOPICS]
    negi_topics = [t for t in topics if t in NEGAINF_TOPICS]

    fetched_at = dt.datetime.now(dt.UTC).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )

    http = HttpClient()
    conn: sqlite3.Connection | None = None
    if not args.dry_run:
        conn = open_db(args.db)
        conn.execute("BEGIN IMMEDIATE")
        existing_keys = load_existing_keys(conn)
        existing_urls = load_existing_source_urls(conn)
        _LOG.info(
            "existing am_enforcement_detail keys=%d urls=%d",
            len(existing_keys), len(existing_urls),
        )
    else:
        existing_keys = set()
        existing_urls = set()

    stats: dict[str, dict[str, int]] = {}
    total_inserts = 0
    law_breakdown: dict[str, int] = {}
    authority_breakdown: dict[str, int] = {}

    try:
        # ============================================================
        # PASS 1 — Nega-inf walks (PRIMARY source).
        # ============================================================
        for topic_slug in negi_topics:
            n_info = NEGAINF_TOPICS[topic_slug]
            jbunya = n_info["jigyoubunya"]
            default_authority = n_info["default_authority"]
            default_law = n_info["default_law"]

            cs = {
                "negainf_pages": 0,
                "list_rows": 0,
                "fetched_details": 0,
                "extracted": 0,
                "insert": 0,
                "skip_dup": 0,
                "skip_existing": 0,
                "skip_no_match": 0,
            }
            stats[topic_slug] = cs

            _LOG.info(
                "topic=%s (negi-inf) jigyoubunya=%s label=%s",
                topic_slug, jbunya, n_info["label"],
            )
            rows = fetch_negainf_pages(http, jbunya)
            cs["list_rows"] = len(rows)
            _LOG.info(
                "topic=%s rows discovered=%d", topic_slug, len(rows)
            )

            seq_counter = (
                next_seq(conn, topic_slug) if conn is not None else 1
            )

            stop_topic = False
            for row in rows:
                if args.limit is not None and total_inserts >= args.limit:
                    stop_topic = True
                    break
                detail_url = (
                    f"{NEGAINF_BASE}?jigyoubunya={jbunya}"
                    f"&EID=search&no={row.detail_no}"
                )
                if detail_url in existing_urls:
                    cs["skip_existing"] += 1
                    continue
                status, html = http.get_text(detail_url)
                if status != 200 or not html:
                    continue
                cs["fetched_details"] += 1
                detail = parse_negainf_detail(html)
                rec = build_negainf_record(
                    row=row,
                    detail=detail,
                    topic_slug=topic_slug,
                    default_authority=default_authority,
                    default_law=default_law,
                    detail_url=detail_url,
                )
                if rec is None:
                    cs["skip_no_match"] += 1
                    continue
                cs["extracted"] += 1
                # Nega-inf rows are unique per detail URL. The same
                # corporation may receive 20+ distinct enforcement
                # records on the same date (one per business site —
                # e.g. Big Motor 2023-10-24). We dedup ONLY on detail
                # URL — any same-entity-same-date variations are
                # legitimate distinct enforcements.
                if detail_url in existing_urls:
                    cs["skip_existing"] += 1
                    continue
                existing_urls.add(detail_url)
                if args.dry_run or conn is None:
                    cs["insert"] += 1
                    total_inserts += 1
                    law_breakdown[rec.related_law_ref] = (
                        law_breakdown.get(rec.related_law_ref, 0) + 1
                    )
                    authority_breakdown[rec.authority] = (
                        authority_breakdown.get(rec.authority, 0) + 1
                    )
                    if cs["insert"] <= 5:
                        _LOG.info(
                            "DRY %s | %s | %s | %s | %s | law=%s",
                            topic_slug, rec.issuance_date,
                            rec.target_name, rec.punishment_raw,
                            rec.enforcement_kind, rec.related_law_ref,
                        )
                    continue
                canonical_id = (
                    f"AM-ENF-MLIT-OTHER-{topic_slug}-{seq_counter:06d}"
                )
                seq_counter += 1
                try:
                    verdict = upsert_record(
                        conn, rec, canonical_id, fetched_at
                    )
                except sqlite3.Error as exc:
                    _LOG.warning("DB insert err name=%s err=%s",
                                 rec.target_name, exc)
                    continue
                if verdict == "insert":
                    cs["insert"] += 1
                    total_inserts += 1
                    law_breakdown[rec.related_law_ref] = (
                        law_breakdown.get(rec.related_law_ref, 0) + 1
                    )
                    authority_breakdown[rec.authority] = (
                        authority_breakdown.get(rec.authority, 0) + 1
                    )
                else:
                    cs["skip_dup"] += 1
                if total_inserts > 0 and total_inserts % 50 == 0:
                    conn.commit()
                    conn.execute("BEGIN IMMEDIATE")
                if args.limit is not None and total_inserts >= args.limit:
                    stop_topic = True
                    break
            _LOG.info("topic=%s done: %s", topic_slug, cs)
            if stop_topic:
                break

        # ============================================================
        # PASS 2 — Press-release archive walks (supplemental).
        # ============================================================
        for topic_slug in press_topics:
            if args.limit is not None and total_inserts >= args.limit:
                break
            topic_info = TOPICS[topic_slug]
            authority = topic_info["authority"]
            default_law = topic_info["law_basis"]

            cs = {
                "archives_walked": 0,
                "candidate_pages": 0,
                "filtered_in": 0,
                "fetched": 0,
                "extracted": 0,
                "insert": 0,
                "skip_dup": 0,
                "skip_existing": 0,
                "skip_no_match": 0,
            }
            stats[topic_slug] = cs

            archives = archive_urls_for_topic(topic_info)
            _LOG.info(
                "topic=%s archives=%d label=%s",
                topic_slug, len(archives), topic_info["label"],
            )

            # Collect (date, url, title) candidates from all archive indexes.
            candidates: list[tuple[str, str, str, str]] = []
            seen_urls: set[str] = set()
            for archive_url in archives:
                status, html = http.get_text(archive_url)
                if status != 200 or not html:
                    _LOG.debug("archive fetch failed %s status=%s",
                               archive_url, status)
                    continue
                cs["archives_walked"] += 1
                items = parse_index(html, topic_info)
                cs["candidate_pages"] += len(items)
                for date_iso, url, title in items:
                    if url in seen_urls:
                        continue
                    seen_urls.add(url)
                    if not title_matches_topic(title, topic_info):
                        continue
                    cs["filtered_in"] += 1
                    candidates.append((date_iso, url, title, archive_url))

            _LOG.info(
                "topic=%s candidates=%d filtered_in=%d",
                topic_slug, cs["candidate_pages"], cs["filtered_in"],
            )

            if args.per_topic_page_limit is not None:
                candidates = candidates[: args.per_topic_page_limit]

            seq_counter = (
                next_seq(conn, topic_slug) if conn is not None else 1
            )

            stop_topic = False
            for date_iso, url, title, archive_url in candidates:
                if args.limit is not None and total_inserts >= args.limit:
                    stop_topic = True
                    break
                # Skip URLs we already have.
                if url in existing_urls:
                    cs["skip_existing"] += 1
                    continue
                status, html = http.get_text(url)
                if status != 200 or not html:
                    continue
                cs["fetched"] += 1
                rec = extract_record(
                    html=html,
                    topic_slug=topic_slug,
                    authority=authority,
                    default_law=default_law,
                    page_url=url,
                    archive_url=archive_url,
                    fallback_date=date_iso,
                    fallback_title=title,
                )
                if rec is None:
                    cs["skip_no_match"] += 1
                    continue
                cs["extracted"] += 1
                key = (rec.authority, rec.issuance_date,
                       rec.target_name or "", rec.enforcement_kind)
                if key in existing_keys:
                    cs["skip_existing"] += 1
                    continue
                existing_keys.add(key)
                existing_urls.add(url)
                if args.dry_run or conn is None:
                    cs["insert"] += 1
                    total_inserts += 1
                    law_breakdown[rec.related_law_ref] = (
                        law_breakdown.get(rec.related_law_ref, 0) + 1
                    )
                    authority_breakdown[rec.authority] = (
                        authority_breakdown.get(rec.authority, 0) + 1
                    )
                    if cs["insert"] <= 5:
                        _LOG.info(
                            "DRY %s | %s | %s | %s | %s | law=%s",
                            topic_slug, rec.issuance_date,
                            rec.target_name, rec.punishment_raw,
                            rec.enforcement_kind, rec.related_law_ref,
                        )
                    continue
                canonical_id = (
                    f"AM-ENF-MLIT-OTHER-{topic_slug}-{seq_counter:06d}"
                )
                seq_counter += 1
                try:
                    verdict = upsert_record(conn, rec, canonical_id, fetched_at)
                except sqlite3.Error as exc:
                    _LOG.warning("DB insert err name=%s err=%s",
                                 rec.target_name, exc)
                    continue
                if verdict == "insert":
                    cs["insert"] += 1
                    total_inserts += 1
                    law_breakdown[rec.related_law_ref] = (
                        law_breakdown.get(rec.related_law_ref, 0) + 1
                    )
                    authority_breakdown[rec.authority] = (
                        authority_breakdown.get(rec.authority, 0) + 1
                    )
                else:
                    cs["skip_dup"] += 1
                if total_inserts > 0 and total_inserts % 50 == 0:
                    conn.commit()
                    conn.execute("BEGIN IMMEDIATE")
                if args.limit is not None and total_inserts >= args.limit:
                    stop_topic = True
                    break
            _LOG.info("topic=%s done: %s", topic_slug, cs)
            if stop_topic:
                break

    finally:
        http.close()
        if conn is not None:
            conn.commit()
            conn.close()

    _LOG.info("SUMMARY total_inserts=%d", total_inserts)
    _LOG.info("PER TOPIC: %s", json.dumps(stats, ensure_ascii=False))
    _LOG.info("PER LAW: %s", json.dumps(law_breakdown, ensure_ascii=False))
    _LOG.info("PER AUTHORITY: %s", json.dumps(authority_breakdown, ensure_ascii=False))

    if args.log_file is not None:
        with open(args.log_file, "a") as f:
            f.write(
                f"\n## {fetched_at} MLIT other transport enforcement ingest\n"
                f"  topics={topics} limit={args.limit}\n"
                f"  total_inserts={total_inserts}\n"
                f"  per_topic={json.dumps(stats, ensure_ascii=False)}\n"
                f"  per_law={json.dumps(law_breakdown, ensure_ascii=False)}\n"
                f"  per_authority={json.dumps(authority_breakdown, ensure_ascii=False)}\n"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
