#!/usr/bin/env python3
"""Generate per-program static HTML pages for jpcite.com.

Input:  data/jpintel.db (SQLite programs table)
Output: site/programs/{slug}.html (one per indexable row; slug = hepburn romaji + sha1-6)
        site/sitemap-programs.xml (regenerated; split into multiple files if >50k URLs)

Indexable row = excluded=0 AND tier in (S,A,B,C) AND source_url IS NOT NULL
                AND authority_name NOT LIKE '%noukaweb%'

As of 2026-04-23 snapshot: ~6,658 rows.

Design references
-----------------
- docs/seo_technical_audit.md  (option 'a', skeleton, 2026-04-23 upgrade)
- docs/json_ld_strategy.md     (JSON-LD mapping, @graph expansion)
- site/_templates/program.html (Jinja2 template)

SEO/LLM 2026 target (16-point audit in spec):
- canonical + no hreflang (Japanese monolingual)
- @graph JSON-LD (GovernmentService/LoanOrCredit + optional MonetaryGrant + FAQPage + BreadcrumbList + Organization)
- TL;DR block, author byline, primary source link, related-programs
- hepburn slug via pykakasi, sha1-6 suffix for collision-free URLs
- idempotent write (skip if identical content)

Usage
-----
    uv run python scripts/generate_program_pages.py \
        --db data/jpintel.db \
        --out site/programs \
        --domain jpcite.com \
        [--limit 3] [--samples-dir site/programs/_samples] [--sample-ids UNI-...,UNI-...]

Exit codes
----------
0 success (possibly with per-row errors logged)
1 fatal (db missing, template missing, pykakasi not installed)
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sqlite3
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

# JST = UTC+9. Sitemap <lastmod> is dated in JST so the operator timezone
# matches every other date surfaced on jpcite.com (consistent with
# CLAUDE.md "anonymous quota resets at JST midnight" baseline).
_JST = timezone(timedelta(hours=9))
_RESERVED_PROGRAM_HTML = frozenset({"index.html", "share.html"})


def _today_jst_iso() -> str:
    return datetime.now(_JST).date().isoformat()


if TYPE_CHECKING:
    from collections.abc import Iterable

try:
    from jinja2 import Environment, FileSystemLoader, select_autoescape
except ImportError:  # pragma: no cover
    sys.stderr.write("ERROR: jinja2 is required. `uv pip install jinja2` or add to pyproject.\n")
    raise

try:
    import pykakasi  # type: ignore
except ImportError:  # pragma: no cover
    sys.stderr.write(
        "ERROR: pykakasi is required for hepburn romaji slugs. "
        "`uv pip install pykakasi` or `pip install -e .[site]`.\n"
    )
    raise

# Canonical 47 prefecture JA-name → ASCII-slug mapping. Reused from the
# prefecture-page generator so that internal /prefectures/{slug}.html backlinks
# from per-program pages resolve. Without this import, the breadcrumb +
# `<dt>地域</dt>` row would have no slug and degrade to a plain text label.
sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    from _pref_slugs import JA_TO_SLUG as _PREF_JA_TO_SLUG  # type: ignore
except ImportError:  # pragma: no cover
    _PREF_JA_TO_SLUG = {}
try:
    from static_bad_urls import load_static_bad_urls  # type: ignore
except ImportError:  # pragma: no cover

    def load_static_bad_urls() -> set[str]:
        return set()


LOG = logging.getLogger("generate_program_pages")

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = REPO_ROOT / "data" / "jpintel.db"
# Acceptance-rate facts live in autonomath.db (am_acceptance_stat). We open a
# *separate* read-only connection — CLAUDE.md forbids ATTACH / cross-DB JOIN
# between jpintel.db and autonomath.db. The bulk pre-load below builds an
# in-memory unified_id → stats map so per-row rendering stays sync.
DEFAULT_AUTONOMATH_DB = REPO_ROOT / "autonomath.db"
DEFAULT_TEMPLATE_DIR = REPO_ROOT / "site" / "_templates"
DEFAULT_OUT = REPO_ROOT / "site" / "programs"
DEFAULT_SAMPLES = REPO_ROOT / "site" / "programs" / "_samples"
DEFAULT_SITEMAP = REPO_ROOT / "site" / "sitemap-programs.xml"
DEFAULT_SITEMAP_INDEX = REPO_ROOT / "site" / "sitemap-index.xml"
DEFAULT_STRUCTURED_DIR = REPO_ROOT / "site" / "structured"
DEFAULT_SITEMAP_STRUCTURED = REPO_ROOT / "site" / "sitemap-structured.xml"

SITEMAP_URL_CAP = 50_000  # sitemap.org spec
DEFAULT_DOMAIN = "jpcite.com"

# Bookyou株式会社 facts — operator entity referenced from every page's JSON-LD.
OPERATOR_NAME = "Bookyou株式会社"
OPERATOR_CORPORATE_NUMBER = "T8010001213708"
OPERATOR_REP = "梅田茂利"
OPERATOR_EMAIL = "info@bookyou.net"
OPERATOR_ADDRESS_JP = "東京都文京区小日向2-22-1"

BANNED_SOURCE_SQL = """
  AND LOWER(COALESCE(source_url, '')) NOT LIKE '%//smart-hojokin.jp%'
  AND LOWER(COALESCE(source_url, '')) NOT LIKE '%//www.smart-hojokin.jp%'
  AND LOWER(COALESCE(source_url, '')) NOT LIKE '%//noukaweb.jp%'
  AND LOWER(COALESCE(source_url, '')) NOT LIKE '%//www.noukaweb.jp%'
  AND LOWER(COALESCE(source_url, '')) NOT LIKE '%//hojyokin-portal.jp%'
  AND LOWER(COALESCE(source_url, '')) NOT LIKE '%//www.hojyokin-portal.jp%'
  AND LOWER(COALESCE(source_url, '')) NOT LIKE '%//biz.stayway.jp%'
  AND LOWER(COALESCE(source_url, '')) NOT LIKE '%//www.biz.stayway.jp%'
  AND LOWER(COALESCE(source_url, '')) NOT LIKE '%//stayway.jp%'
  AND LOWER(COALESCE(source_url, '')) NOT LIKE '%//www.stayway.jp%'
  AND LOWER(COALESCE(source_url, '')) NOT LIKE '%//prtimes.jp%'
  AND LOWER(COALESCE(source_url, '')) NOT LIKE '%//www.prtimes.jp%'
  AND LOWER(COALESCE(source_url, '')) NOT LIKE '%//wikipedia.org%'
  AND LOWER(COALESCE(source_url, '')) NOT LIKE '%//www.wikipedia.org%'
"""


# ---------------------------------------------------------------------------
# Query
# ---------------------------------------------------------------------------

INDEXABLE_SQL_TEMPLATE = """
SELECT
    unified_id,
    primary_name,
    aliases_json,
    authority_level,
    authority_name,
    prefecture,
    municipality,
    program_kind,
    official_url,
    amount_max_man_yen,
    amount_min_man_yen,
    subsidy_rate,
    tier,
    target_types_json,
    funding_purpose_json,
    source_url,
    source_fetched_at,
    updated_at
FROM programs
WHERE excluded = 0
  AND tier IN ({tier_in})
  AND source_url IS NOT NULL
  AND source_url <> ''
  AND COALESCE(source_url_status, '') NOT IN ('broken', 'dead')
  AND COALESCE(source_last_check_status, 0) NOT IN (403, 404, 410)
  AND (authority_name IS NULL OR authority_name NOT LIKE '%noukaweb%')
  {banned_source_sql}
ORDER BY
    CASE tier WHEN 'S' THEN 0 WHEN 'A' THEN 1 WHEN 'B' THEN 2 ELSE 3 END,
    unified_id
"""

# Default kept for backwards compat with internal helpers / tests that still
# reference INDEXABLE_SQL directly. _iter_rows builds the actual query from
# the runtime --tiers selection (default: S+A only after the 2026-04-29 SEO
# AI-feel reduction; was S/A/B/C).
INDEXABLE_SQL = INDEXABLE_SQL_TEMPLATE.format(
    tier_in="'S','A','B','C'", banned_source_sql=BANNED_SOURCE_SQL
)

SAMPLE_BY_ID_SQL = """
SELECT
    unified_id, primary_name, aliases_json, authority_level, authority_name,
    prefecture, municipality, program_kind, official_url,
    amount_max_man_yen, amount_min_man_yen, subsidy_rate,
    tier, target_types_json, funding_purpose_json,
    source_url, source_fetched_at, updated_at
FROM programs
WHERE unified_id = ?
"""


# ---------------------------------------------------------------------------
# Row normalisation
# ---------------------------------------------------------------------------

KIND_JA = {
    "subsidy": "補助金・交付金",
    "grant": "助成金・給付金",
    "loan": "融資 (政策金融)",
    "tax_credit": "税制優遇",
    "incentive": "奨励・インセンティブ制度",
    "certification": "認定制度",
    "training": "研修・人材育成",
}


def _parse_json_list(raw: Any) -> list[str]:
    if not raw:
        return []
    if isinstance(raw, list):
        return [str(x) for x in raw if x]
    try:
        val = json.loads(raw)
    except (TypeError, ValueError):
        return []
    if isinstance(val, list):
        return [str(x) for x in val if x]
    return []


def _amount_line(max_man: float | None, min_man: float | None) -> str | None:
    if max_man is None and min_man is None:
        return None
    if max_man is not None and min_man is not None and min_man > 0:
        return f"{int(min_man):,}万円 〜 {int(max_man):,}万円"
    if max_man is not None:
        return f"最大 {int(max_man):,}万円"
    if min_man is not None:
        return f"{int(min_man):,}万円〜"
    return None


def _max_amount_man(row: dict[str, Any]) -> str:
    v = row.get("amount_max_man_yen")
    if v is None:
        return "非公表"
    return f"{int(v):,}"


def _subsidy_rate_line(rate: Any) -> str | None:
    if rate is None:
        return None
    try:
        rate_f = float(rate)
    except (TypeError, ValueError):
        return None
    if rate_f <= 0:
        return None
    pct = int(round(rate_f * 100))
    return f"{pct}% (目安)"


_TARGET_TYPES_JA = {
    # ascii enum → JA
    "corporation": "法人",
    "sole_proprietor": "個人事業主",
    "smb": "中小企業",
    "sme": "中小企業",
    "small_business": "中小企業",
    "startup": "スタートアップ",
    "npo": "NPO法人",
    "NPO": "NPO法人・団体",
    "individual": "個人",
    "municipality": "地方自治体",
    "school": "学校法人",
    "farmer": "農業者",
    "certified_farmer": "認定農業者",
    "new_farmer": "新規就農者",
    "certified_new_farmer": "認定新規就農者",
    "agri_corporation": "農業法人",
    "agri_corp": "農業法人",
    "ag_corp": "農業法人",
    "employment_agri": "雇用就農者",
    "researcher": "研究者",
    "nonprofit": "非営利団体",
    "fishery": "漁業者",
    "forestry": "林業者",
    "corp": "法人",
    "group": "団体",
    "any": "全般",
    "aspiring_farmer": "就農希望者",
    "prospective_farmer": "就農希望者",
    "individual_farmer": "個人農業者",
    "individual_certified_farmer": "個人認定農業者",
    "individual_employee": "個人従業員",
    "young_farmer": "若手農業者",
    "succession": "事業承継",
    # JA → JA passthrough (suppresses warnings; values already in JA)
    "法人全般": "法人全般",
    "個人農業者": "個人農業者",
    "認定新規就農者": "認定新規就農者",
    "農業法人": "農業法人",
    "非農家": "非農家",
    "認定農業者": "認定農業者",
    "若手農業者": "若手農業者",
    "集落営農": "集落営農",
    "女性農業者": "女性農業者",
}


def _is_japanese(text: str) -> bool:
    """Return True if string contains any CJK / kana character."""
    for ch in text:
        code = ord(ch)
        # Hiragana, Katakana, CJK Unified Ideographs, CJK Compat, Half/Fullwidth
        if (
            0x3040 <= code <= 0x309F
            or 0x30A0 <= code <= 0x30FF
            or 0x4E00 <= code <= 0x9FFF
            or 0x3400 <= code <= 0x4DBF
            or 0xFF00 <= code <= 0xFFEF
        ):
            return True
    return False


def _target_type_label(t: str) -> str:
    """Map a single target_type value to its JA label.

    - Mapped values return the mapped JA.
    - Unmapped but already-JA values pass through silently.
    - Unmapped ascii values warn and render raw.
    """
    if t in _TARGET_TYPES_JA:
        return _TARGET_TYPES_JA[t]
    if _is_japanese(t):
        return t
    LOG.warning("target_types unmapped enum: %r (rendering raw)", t)
    return t


def _target_types_text(target_types: list[str]) -> str:
    if not target_types:
        return "公募要領で規定される対象"
    return "、".join(_target_type_label(t) for t in target_types)


def _target_types_list_ja(target_types: list[str]) -> list[str]:
    """Return per-item JA labels (same mapping as _target_types_text)."""
    return [_target_type_label(t) for t in target_types]


_PUBLIC_ID_PREFIX_RE = re.compile(r"^(?:MUN-\d{2,6}-\d{3}|PREF-\d{2,6}-\d{3})[_\s]+")
_BAD_PUBLIC_TITLES = {
    "このページの本文へ移動",
    "本文へ移動",
    "ページトップ",
    "page top",
    "詳しくはこちら",
    "詳細はこちら",
    "tiếng việt",
    "português",
}
_BAD_PUBLIC_TITLE_PATTERNS = (
    re.compile(r".*課$"),
    re.compile(r".*室$"),
    re.compile(r".*(?:更新しました|受付終了しました|募集終了|公募終了).*"),
    re.compile(r".*(?:pdf|PDF)[：:].*"),
    re.compile(r".*(?:様式|記入例|資料|パンフレット).*"),
)


def _public_program_name(name: str | None) -> str:
    """Hide ingest/internal prefixes from public page text."""
    cleaned = (name or "").strip()
    cleaned = _PUBLIC_ID_PREFIX_RE.sub("", cleaned)
    return re.sub(r"\s+", " ", cleaned)


def _is_public_title_quality_ok(name: str | None) -> bool:
    cleaned = _public_program_name(name).strip().lower()
    if not cleaned or cleaned in _BAD_PUBLIC_TITLES:
        return False
    if any(pattern.fullmatch(cleaned) for pattern in _BAD_PUBLIC_TITLE_PATTERNS):
        return False
    return not (len(cleaned) <= 3 and not _is_japanese(cleaned))


def _sanitize_aliases_for_public(aliases: list[str], primary_name: str) -> list[str]:
    out: list[str] = []
    seen: set[str] = {primary_name}
    for alias in aliases:
        cleaned = _public_program_name(alias)
        if not cleaned or cleaned in seen or not _is_public_title_quality_ok(cleaned):
            continue
        seen.add(cleaned)
        out.append(cleaned)
    return out


def _truncate(text: str, limit: int) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    # Try to cut at last natural boundary (。.、 or space) within the
    # 30-char window before the hard limit, to avoid mid-word truncation.
    head = text[: limit - 1]
    window_start = max(0, len(head) - 30)
    boundary = -1
    for ch in ("。", ".", "、", " "):
        idx = head.rfind(ch, window_start)
        if idx > boundary:
            boundary = idx
    if boundary >= window_start:
        return head[: boundary + 1].rstrip() + "…"
    # Hard cut fallback
    return head + "…"


# ---------------------------------------------------------------------------
# Slug (hepburn romaji + sha1-6 suffix)
# ---------------------------------------------------------------------------

_KKS = pykakasi.kakasi()


def slugify(name: str, unified_id: str) -> str:
    """Produce ``{hepburn-romaji}-{sha1-6}``.

    Thin wrapper around :func:`jpintel_mcp.utils.slug.program_static_slug`
    so the generator and the API runtime use a single derivation. Kept
    as a free function for back-compat with the rest of this script and
    for any downstream tooling importing from here.
    """
    # Local import keeps the script standalone-friendly: callers running
    # `python scripts/generate_program_pages.py` from a checkout without
    # `pip install -e .` still get a clear ImportError pointing at the
    # missing package, rather than a slug-derivation regression.
    from jpintel_mcp.utils.slug import program_static_slug

    return program_static_slug(name, unified_id)


# ---------------------------------------------------------------------------
# Era / date helpers
# ---------------------------------------------------------------------------

# 令和 started 2019-05-01; 令和 N 年 => 2018 + N
# 平成 1989-01-08; 平成 N 年 => 1988 + N
# 昭和 1926-12-25; 昭和 N 年 => 1925 + N
_ERA_OFFSET = {"令和": 2018, "平成": 1988, "昭和": 1925}
_ERA_PATTERN = re.compile(
    r"(令和|平成|昭和)\s*([元0-9一二三四五六七八九十]+)\s*年"
    r"(?:\s*([0-9一二三四五六七八九十]+)\s*月)?"
    r"(?:\s*([0-9一二三四五六七八九十]+)\s*日)?"
)
_KANJI_DIGITS = {
    "元": 1,
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
}


def _kanji_or_int(s: str) -> int | None:
    s = s.strip()
    if not s:
        return None
    if s.isdigit():
        return int(s)
    # tiny kanji parser: handles up to 99 (e.g. 二十三=23)
    total = 0
    prev = 0
    for ch in s:
        if ch == "十":
            prev = prev if prev else 1
            total += prev * 10
            prev = 0
        elif ch in _KANJI_DIGITS:
            prev = _KANJI_DIGITS[ch]
            if prev >= 10:
                total += prev
                prev = 0
    total += prev
    return total or None


def era_to_iso(text: str | None) -> str | None:
    """Convert 令和N年M月D日 (or 平成/昭和) to ISO 8601 YYYY-MM-DD.

    Returns None if no era marker found.
    """
    if not text:
        return None
    m = _ERA_PATTERN.search(text)
    if not m:
        return None
    era, y, mo, d = m.groups()
    yn = _kanji_or_int(y)
    if yn is None:
        return None
    year = _ERA_OFFSET[era] + yn
    mon = _kanji_or_int(mo) if mo else 1
    day = _kanji_or_int(d) if d else 1
    try:
        return date(year, mon or 1, day or 1).isoformat()
    except ValueError:
        return None


def _normalize_iso_date(raw: Any) -> str | None:
    if not raw:
        return None
    if isinstance(raw, str):
        # keep date part of ISO 8601, or try era conversion
        if "T" in raw:
            return raw.split("T", 1)[0]
        if re.match(r"^\d{4}-\d{2}-\d{2}", raw):
            return raw[:10]
        iso = era_to_iso(raw)
        if iso:
            return iso
    return str(raw)


def _last_updated_ja(row: dict[str, Any]) -> str:
    upd = row.get("updated_at") or row.get("source_fetched_at")
    iso = _normalize_iso_date(upd)
    if iso and re.match(r"^\d{4}-\d{2}-\d{2}$", iso):
        y, m, d = iso.split("-")
        return f"{int(y)}年{int(m)}月{int(d)}日"
    return datetime.now(_JST).date().strftime("%Y年%m月%d日").replace("0", "")  # graceful


# ---------------------------------------------------------------------------
# Summary / meta / TL;DR builders
# ---------------------------------------------------------------------------


def _source_domain(url: str | None) -> str:
    if not url:
        return ""
    try:
        host = urlparse(url).hostname or ""
    except Exception:
        return ""
    if host.startswith("www."):
        host = host[4:]
    return host


_PREF_HOST_JA = {
    "hokkaido": "北海道",
    "aomori": "青森県",
    "iwate": "岩手県",
    "miyagi": "宮城県",
    "akita": "秋田県",
    "yamagata": "山形県",
    "fukushima": "福島県",
    "ibaraki": "茨城県",
    "tochigi": "栃木県",
    "gunma": "群馬県",
    "saitama": "埼玉県",
    "chiba": "千葉県",
    "tokyo": "東京都",
    "kanagawa": "神奈川県",
    "niigata": "新潟県",
    "toyama": "富山県",
    "ishikawa": "石川県",
    "fukui": "福井県",
    "yamanashi": "山梨県",
    "nagano": "長野県",
    "gifu": "岐阜県",
    "shizuoka": "静岡県",
    "aichi": "愛知県",
    "mie": "三重県",
    "shiga": "滋賀県",
    "kyoto": "京都府",
    "osaka": "大阪府",
    "hyogo": "兵庫県",
    "nara": "奈良県",
    "wakayama": "和歌山県",
    "tottori": "鳥取県",
    "shimane": "島根県",
    "okayama": "岡山県",
    "hiroshima": "広島県",
    "yamaguchi": "山口県",
    "tokushima": "徳島県",
    "kagawa": "香川県",
    "ehime": "愛媛県",
    "kochi": "高知県",
    "fukuoka": "福岡県",
    "saga": "佐賀県",
    "nagasaki": "長崎県",
    "kumamoto": "熊本県",
    "oita": "大分県",
    "miyazaki": "宮崎県",
    "kagoshima": "鹿児島県",
    "okinawa": "沖縄県",
}


def _source_org_guess(domain: str) -> str | None:
    """Best-effort human name for the source authority from host suffix.

    Never returns a placeholder like "所管官公庁"; returns None if undetectable.
    """
    if not domain:
        return None
    # Central government mappings (most-specific first)
    mapping = [
        ("chusho.meti.go.jp", "中小企業庁"),
        ("maff.go.jp", "農林水産省"),
        ("meti.go.jp", "経済産業省"),
        ("mhlw.go.jp", "厚生労働省"),
        ("mlit.go.jp", "国土交通省"),
        ("env.go.jp", "環境省"),
        ("mext.go.jp", "文部科学省"),
        ("mof.go.jp", "財務省"),
        ("soumu.go.jp", "総務省"),
        ("jfc.go.jp", "日本政策金融公庫"),
        ("smrj.go.jp", "中小機構"),
        ("jeed.go.jp", "高齢・障害・求職者雇用支援機構"),
        ("nta.go.jp", "国税庁"),
    ]
    for key, name in mapping:
        if domain.endswith(key):
            return name
    # 東京都 special host
    if domain.endswith("metro.tokyo.lg.jp") or domain.endswith("metro.tokyo.jp"):
        return "東京都"
    # Prefecture sub-domains: pref.<name>.lg.jp (or legacy .jp)
    m = re.search(r"(?:^|\.)pref\.([a-z]+)\.(?:lg\.jp|jp)$", domain)
    if m:
        pref_key = m.group(1)
        pref_ja = _PREF_HOST_JA.get(pref_key)
        if pref_ja:
            return pref_ja
    # City sub-domains: city.<city>.<pref>.lg.jp or city.<city>.<pref>.jp
    m = re.search(r"(?:^|\.)city\.[a-z0-9-]+\.([a-z]+)\.(?:lg\.jp|jp)$", domain)
    if m:
        pref_key = m.group(1)
        pref_ja = _PREF_HOST_JA.get(pref_key)
        if pref_ja:
            return f"地方自治体 ({pref_ja})"
    # Any remaining .lg.jp
    if domain.endswith(".lg.jp"):
        return "地方自治体"
    return None


def _resolve_agency(row: dict[str, Any]) -> str | None:
    """Resolve a usable provider/agency name; never return a placeholder string.

    Order:
    1. explicit authority_name (if not noukaweb / placeholder)
    2. host-based guess from source_url
    3. None — callers must gracefully omit the field
    """
    auth = row.get("authority_name")
    if auth:
        auth_s = str(auth).strip()
        if auth_s and auth_s not in {"所管官公庁", "公開元", "不明"} and "noukaweb" not in auth_s:
            return auth_s
    src = row.get("source_url") or row.get("official_url") or ""
    host = _source_domain(src)
    guessed = _source_org_guess(host)
    if guessed:
        return guessed
    return None


def _tldr(row: dict[str, Any], target_types: list[str], aliases: list[str]) -> dict[str, str]:
    name = row["primary_name"]
    kind = KIND_JA.get(row.get("program_kind") or "subsidy", "公的支援制度")
    auth = _resolve_agency(row)
    amt = (
        _amount_line(row.get("amount_max_man_yen"), row.get("amount_min_man_yen"))
        or "金額は公募要領に依る"
    )
    who = _target_types_text(target_types)
    fetched = _normalize_iso_date(row.get("source_fetched_at")) or "公募要領を参照"
    what = f"{name} ({kind})" if not auth else f"{name} ({kind}, 提供: {auth})"
    return {
        "what": what,
        "who": who,
        "how_much": amt,
        "when": f"公募時期は一次情報を参照 (最新確認: {fetched})",
    }


def _summary_paragraph(row: dict[str, Any], aliases: list[str]) -> str:
    name = row["primary_name"]
    kind = KIND_JA.get(row.get("program_kind") or "subsidy", "公的支援制度")
    auth = _resolve_agency(row)
    pref = row.get("prefecture")
    pref_clause = f"({pref}) " if pref else ""
    alias_clause = f"別称「{aliases[0]}」としても知られています。" if aliases else ""
    amt = _amount_line(row.get("amount_max_man_yen"), row.get("amount_min_man_yen"))
    amt_clause = f"支援金額の目安は{amt}。" if amt else ""
    if auth:
        lead = f"「{name}」は {auth} {pref_clause}が運営する{kind}です。"
    else:
        lead = f"「{name}」は{pref_clause}公的機関が運営する{kind}です。"
    return (
        f"{lead}{alias_clause}"
        f"{amt_clause}"
        "本ページは jpcite が横断検索用に構造化したプレビューであり、"
        "最新の公募状況や詳細要件は一次情報を確認してください。"
    )


def _amount_paragraph(row: dict[str, Any]) -> str:
    amt = _amount_line(row.get("amount_max_man_yen"), row.get("amount_min_man_yen"))
    rate = _subsidy_rate_line(row.get("subsidy_rate"))
    parts = []
    if amt:
        parts.append(f"支援金額の目安は{amt}です。")
    else:
        parts.append("支援金額は公募要領に記載されています。")
    if rate:
        parts.append(f"補助率は{rate}です。")
    parts.append(
        "上限金額・補助率は年度や採択類型により変動することがあるため、必ず出典ページの最新公募要領をご確認ください。"
    )
    return "".join(parts)


def _deadline_paragraph(row: dict[str, Any]) -> str:
    fetched = _normalize_iso_date(row.get("source_fetched_at"))
    clause = (
        f"公募時期・締切は年度ごとに更新されます。jpcite の直近データ取得日は{fetched}です。"
        if fetched
        else "公募時期・締切は年度ごとに更新されます。"
    )
    return clause + "申請を検討される場合は、出典ページで現在の公募状況を必ずご確認ください。"


def _exclusion_paragraph(row: dict[str, Any]) -> str:
    return (
        "他の補助金・助成金との併用可否は制度ごとに異なります。同一経費に対する重複受給は原則不可、"
        "同一事業内でも他制度と併用が制限される場合があります。"
        "併用チェックは jpcite API の併用ルール機能でご確認いただけます。"
    )


def _meta_description(row: dict[str, Any], target_types: list[str]) -> str:
    """Compose a 150-160 char meta description.

    Format spec: `{summary_1sentence} 対象者: {target}. 上限額: {amount}. 公募時期: {timing}. 出典リンク: {source_domain}.`
    We pad with prefecture/authority details if the base string is < 150 chars,
    and truncate if it exceeds 160.
    """
    name = row["primary_name"]
    auth = _resolve_agency(row)
    pref = row.get("prefecture") or ""
    kind = KIND_JA.get(row.get("program_kind") or "subsidy", "公的支援制度")
    amt = (
        _amount_line(row.get("amount_max_man_yen"), row.get("amount_min_man_yen")) or "公募要領参照"
    )
    who = _target_types_text(target_types)
    domain = _source_domain(row.get("source_url"))
    fetched = _normalize_iso_date(row.get("source_fetched_at")) or "最新を参照"

    pref_clause = f"({pref})" if pref else ""
    if auth:
        summary_one = f"{name}は{auth}{pref_clause}が提供する{kind}です。"
    else:
        summary_one = f"{name}は{pref_clause}公的機関が提供する{kind}です。"
    parts = [
        summary_one,
        f"対象者: {who}.",
        f"上限額: {amt}.",
        f"公募時期: {fetched}.",
        f"出典リンク: {domain}." if domain else "",
    ]
    text = " ".join(p for p in parts if p)

    # Pad toward 150 with subsidy_rate / kind details if still short.
    rate_line = _subsidy_rate_line(row.get("subsidy_rate"))
    if len(text) < 150 and rate_line:
        text = text + f" 補助率: {rate_line}."
    if len(text) < 150:
        text = text + " 横断検索・併用チェックは jpcite API / MCP で提供。"
    if len(text) < 150:
        text = text + "最新の公募要領は出典ページをご確認ください。"

    return _truncate(text, 160)


def _page_title(row: dict[str, Any], target_types: list[str]) -> str:
    name = row["primary_name"]
    parts = [name]
    if target_types:
        tt_label = _target_type_label(target_types[0])
        if tt_label and tt_label != "公募要領参照":
            parts.append(f"対象{tt_label}")
    amt_val = row.get("amount_max_man_yen")
    if amt_val is not None:
        parts.append(f"最大{int(amt_val):,}万円")
    parts.append("jpcite")
    raw = " | ".join(parts)
    return _truncate(raw, 60)


# ---------------------------------------------------------------------------
# JSON-LD @graph builder
# ---------------------------------------------------------------------------

ORG_NODE_ID = "https://jpcite.com/#publisher"


def _org_node(domain: str) -> dict[str, Any]:
    # Single canonical Organization @id across ALL templates (publisher.@id reuses).
    return {
        "@type": "Organization",
        "@id": ORG_NODE_ID,
        "name": "jpcite",
        "url": f"https://{domain}/",
        # publisher.logo (required for Google rich-results / News).
        # 600x60 white-background PNG kept under /assets/.
        "logo": {
            "@type": "ImageObject",
            "url": f"https://{domain}/assets/logo.png",
            "width": 600,
            "height": 60,
        },
        # sameAs — official off-site presence. URLs marked TODO are not yet
        # established; emit empty array until real URLs land (do NOT publish
        # placeholder URLs, they would fail Google entity reconciliation).
        # TODO populate when LinkedIn / GitHub / X (Twitter) / Crunchbase
        # accounts for Bookyou株式会社 / AutonoMath are live.
        "sameAs": [],
    }


def _breadcrumb_node(row: dict[str, Any], slug: str, domain: str, kind_ja: str) -> dict[str, Any]:
    # Build sequentially so an optional prefecture level can be inserted between
    # 制度一覧 (position 2) and {kind} (position 3 or 4) — keeps the JSON-LD
    # BreadcrumbList in lock-step with the HTML breadcrumb in
    # site/_templates/program.html.
    items: list[dict[str, Any]] = [
        {"@type": "ListItem", "position": 1, "name": "ホーム", "item": f"https://{domain}/"},
        {
            "@type": "ListItem",
            "position": 2,
            "name": "制度一覧",
            "item": f"https://{domain}/programs/",
        },
    ]
    pref = row.get("prefecture")
    pref_slug = _PREF_JA_TO_SLUG.get(pref) if pref else None
    if pref and pref_slug:
        items.append(
            {
                "@type": "ListItem",
                "position": len(items) + 1,
                "name": pref,
                "item": f"https://{domain}/prefectures/{pref_slug}.html",
            }
        )
    items.append(
        {
            "@type": "ListItem",
            "position": len(items) + 1,
            "name": kind_ja,
            "item": f"https://{domain}/programs/?kind={row.get('program_kind') or 'subsidy'}",
        }
    )
    items.append(
        {
            "@type": "ListItem",
            "position": len(items) + 1,
            "name": row["primary_name"],
            "item": f"https://{domain}/programs/{slug}",
        }
    )
    return {"@type": "BreadcrumbList", "itemListElement": items}


# Kind → schema.org @type bucket. Anything not listed falls back to GovernmentService.
# - subsidy / grant / tax_credit / incentive / etc → GovernmentService
# - loan (any variant) → LoanOrCredit (with FinancialProduct co-type)
# - certification / training / qualification → EducationalOccupationalProgram
_LOAN_KINDS = {
    "loan",
    "loan_zero_interest_newcomer",
    "loan_zero_interest_innovation",
    "loan_long_term_core_farmer",
    "loan_management_stabilization",
    "loan_management_development",
    "loan_low_interest",
    "loan_high_level_management",
    "loan_short_term_working_capital",
    "loan_preferred_rate",
    "loan_jfc_fisheries",
    "loan_international_regulation",
    "loan_interest_subsidy",
    "loan_modernization",
    "loan_reconstruction",
    "loan_coastal_interest_free",
    "loan_equity",
    "scholarship_loan",
    "commercialization_loan",
    "financial_loan_modernization",
    "融資",
}
_EDUCATION_KINDS = {
    "training",
    "certification",
    "certification_meta",
    "certification_smart_agri",
    "certification_new_farmer",
    "certification_eu_haccp",
    "certification_environmental",
    "certification_core_farmer",
    "certification_6th_industry",
    "certification_with_tax_benefit",
    "certification_service",
    "certification_incentive",
    "qualification",
    "national_qualification",
    "skill_examination",
    "national_exam",
    "language_examination",
    "vocational_training_school",
    "subsidy_new_entrant_training",
    "subsidy_training_support",
    "subsidy_manpower_training_recruitment",
    "training_program_free",
    "internship_support",
    "fellowship",
    "フェローシップ",
}
_TAX_KINDS = {
    "tax_credit",
    "tax_deduction",
    "tax_incentive",
    "tax_incentive_donor_side",
    "tax_incentive_expired",
    "tax_reduction_by_ordinance",
    "tax_special_depreciation",
    "tax_treatment",
    "tax_exemption",
    "tax_deferral_inheritance",
    "tax_deferral_inheritance_continuation",
    "tax_deferral_inheritance_forestry",
    "tax_deferral_gift",
    "tax_deduction_capital_gain",
    "tax_deduction_accumulation",
    "tax_deduction_forestry_income",
    "tax_benefit",
    "tax_benefit_donor",
    "tax_support",
    "fee_reduction",
    "税制優遇",
}


def _classify_kind(kind: str) -> str:
    """Bucket a raw program_kind into one of: loan / education / tax / subsidy."""
    if kind in _LOAN_KINDS or kind.startswith("loan_"):
        return "loan"
    if kind in _EDUCATION_KINDS:
        return "education"
    if kind in _TAX_KINDS or kind.startswith("tax_"):
        return "tax"
    return "subsidy"


def _service_node(
    row: dict[str, Any],
    slug: str,
    domain: str,
    aliases: list[str],
    target_types: list[str],
    funding_purposes: list[str],
) -> dict[str, Any]:
    kind = row.get("program_kind") or "subsidy"
    bucket = _classify_kind(kind)
    if bucket == "loan":
        typ: Any = ["FinancialProduct", "LoanOrCredit"]
    elif bucket == "education":
        typ = "EducationalOccupationalProgram"
    else:
        typ = "GovernmentService"

    node: dict[str, Any] = {
        "@type": typ,
        "@id": f"#service-{slug}",
        "identifier": row["unified_id"],
        "name": row["primary_name"],
        "inLanguage": "ja",
        "url": f"https://{domain}/programs/{slug}",
        "description": _meta_description(row, target_types),
        "publisher": {"@id": ORG_NODE_ID},
    }
    if aliases:
        node["alternateName"] = aliases

    resolved_agency = _resolve_agency(row)
    if resolved_agency:
        provider: dict[str, Any] = {
            "@type": "GovernmentOrganization",
            "name": resolved_agency,
        }
        if row.get("prefecture"):
            provider["areaServed"] = {"@type": "AdministrativeArea", "name": row["prefecture"]}
        else:
            provider["areaServed"] = {"@type": "Country", "name": "日本"}
        node["provider"] = provider

    # GovernmentService / LoanOrCredit / EducationalOccupationalProgram all
    # benefit from explicit areaServed at the service level (Google rich-results
    # for GovernmentService treats areaServed as recommended). Authority level
    # already resolved into the additionalProperty block; mirror it here as a
    # typed Place.
    auth_level = (row.get("authority_level") or "").lower()
    if auth_level in ("national", "country", "central", "中央"):
        node["areaServed"] = {"@type": "Country", "name": "JP"}
    elif row.get("prefecture"):
        node["areaServed"] = {"@type": "AdministrativeArea", "name": row["prefecture"]}
    else:
        # Default to JP if unknown — non-asserting but better than missing.
        node["areaServed"] = {"@type": "Country", "name": "JP"}

    if bucket == "loan":
        # LoanOrCredit canonical fields per https://schema.org/LoanOrCredit
        amt_max = row.get("amount_max_man_yen")
        if amt_max is not None:
            node["amount"] = {
                "@type": "MonetaryAmount",
                "currency": "JPY",
                "value": int(amt_max * 10_000),
                "maxValue": int(amt_max * 10_000),
            }
        else:
            node["amount"] = {"@type": "MonetaryAmount", "currency": "JPY"}
        # Default repayment schedule = monthly (LoanOrCredit hint, not legally binding)
        node["loanRepaymentSchedule"] = "月払い (詳細は公募要領を参照)"
        # Collateral requirement is unknown without per-row enrichment; default to
        # a non-asserting placeholder. requiredCollateral is a free-form Text/Thing
        # field on LoanOrCredit, so a JA explanatory string is valid.
        node["requiredCollateral"] = "公募要領に依る (担保・個人保証人の要否は要確認)"
    elif bucket == "education":
        # EducationalOccupationalProgram per https://schema.org/EducationalOccupationalProgram
        # Fields: programPrerequisites / educationalProgramMode / occupationalCredentialAwarded
        if target_types:
            audience_text = "、".join(_target_type_label(t) for t in target_types)
            node["programPrerequisites"] = audience_text
        node["educationalProgramMode"] = "blended"  # ja training is mostly blended
        # If the program looks like a certification → award the cert; else neutral
        if "certif" in kind or "qualification" in kind or "認定" in (row.get("primary_name") or ""):
            node["occupationalCredentialAwarded"] = row["primary_name"]
        # Google rich-result requires Offer.price as string. Use amount_max_man_yen
        # when known; fall back to "0" (= "contact / unknown" sentinel) so the
        # required-property gate stays green when amounts are not published.
        offers: dict[str, Any] = {"@type": "Offer", "priceCurrency": "JPY"}
        if row.get("amount_max_man_yen") is not None:
            offers["price"] = str(int(row["amount_max_man_yen"] * 10_000))
        else:
            offers["price"] = "0"
        node["offers"] = offers
        node["serviceType"] = kind
    else:
        # GovernmentService — also covers tax bucket; tax variants surface via
        # additionalProperty[subject=TaxIncentive] for downstream filtering.
        node["serviceType"] = kind
        offers = {"@type": "Offer", "priceCurrency": "JPY"}
        price_spec: dict[str, Any] = {"@type": "PriceSpecification", "priceCurrency": "JPY"}
        if row.get("amount_max_man_yen") is not None:
            price_spec["maxPrice"] = int(row["amount_max_man_yen"] * 10_000)
        if row.get("amount_min_man_yen") is not None and row["amount_min_man_yen"] > 0:
            price_spec["minPrice"] = int(row["amount_min_man_yen"] * 10_000)
        if len(price_spec) > 2:
            # Google rich-result requires Offer.price even when priceSpecification
            # carries finer-grained min/max. Use minPrice if present, else maxPrice
            # as the headline figure (subsidies pay UP TO maxPrice; min represents
            # programs with a floor). Render as string per Google's recommendation.
            headline = price_spec.get("minPrice") or price_spec.get("maxPrice")
            if headline is not None:
                offers["price"] = str(headline)
            offers["priceSpecification"] = price_spec
            node["offers"] = offers

    add_props = []
    if row.get("tier"):
        add_props.append({"@type": "PropertyValue", "name": "tier", "value": row["tier"]})
    if row.get("authority_level"):
        add_props.append(
            {"@type": "PropertyValue", "name": "authority_level", "value": row["authority_level"]}
        )
    if row.get("subsidy_rate") is not None:
        add_props.append(
            {"@type": "PropertyValue", "name": "subsidy_rate", "value": row["subsidy_rate"]}
        )
    if target_types:
        target_types_ja = [_target_type_label(t) for t in target_types]
        add_props.append(
            {"@type": "PropertyValue", "name": "target_types", "value": target_types_ja}
        )
    if funding_purposes:
        add_props.append(
            {"@type": "PropertyValue", "name": "funding_purpose", "value": funding_purposes}
        )
    # Tax bucket: surface a `subject=TaxIncentive` PropertyValue so AI crawlers /
    # filters can identify tax measures (no schema.org dedicated type for tax).
    if bucket == "tax":
        add_props.append({"@type": "PropertyValue", "name": "subject", "value": "TaxIncentive"})
    if add_props:
        node["additionalProperty"] = add_props

    if target_types:
        audience_text = "、".join(_target_type_label(t) for t in target_types)
        node["audience"] = {"@type": "Audience", "audienceType": audience_text}

    source_url = row.get("source_url")
    if source_url:
        node["isBasedOn"] = {"@type": "CreativeWork", "url": source_url}
        fetched = _normalize_iso_date(row.get("source_fetched_at"))
        if fetched:
            node["isBasedOn"]["dateAccessed"] = fetched

    mod = _normalize_iso_date(row.get("updated_at"))
    if mod:
        node["dateModified"] = mod

    return node


def _monetary_grant_node(
    row: dict[str, Any], slug: str, domain: str, target_types: list[str]
) -> dict[str, Any] | None:
    kind = row.get("program_kind") or "subsidy"
    if kind not in ("subsidy", "grant"):
        return None
    amt_max = row.get("amount_max_man_yen")
    if amt_max is None:
        return None
    resolved_agency = _resolve_agency(row)
    node: dict[str, Any] = {
        "@type": "MonetaryGrant",
        "@id": f"#grant-{slug}",
        "name": row["primary_name"],
        "url": f"https://{domain}/programs/{slug}",
        "inLanguage": "ja",
        "amount": {
            "@type": "MonetaryAmount",
            "currency": "JPY",
            "value": int(amt_max * 10_000),
        },
    }
    # funder = the government agency actually providing funds.
    # jpcite is the data publisher (referenced only as page publisher, not funder).
    if resolved_agency:
        node["funder"] = {"@type": "GovernmentOrganization", "name": resolved_agency}
    # sponsor duplicated intentionally for schema.org consumers that expect it.
    if resolved_agency:
        node["sponsor"] = {"@type": "GovernmentOrganization", "name": resolved_agency}
    if target_types:
        audience_ja = "、".join(_target_type_label(t) for t in target_types)
        node["audience"] = {"@type": "Audience", "audienceType": audience_ja}
    if row.get("source_url"):
        node["isBasedOn"] = {"@type": "CreativeWork", "url": row["source_url"]}
    return node


def _faq_node(
    row: dict[str, Any],
    slug: str,
    domain: str,
    target_types: list[str],
    kind_ja: str,
) -> dict[str, Any]:
    who = _target_types_text(target_types)
    amt = (
        _amount_line(row.get("amount_max_man_yen"), row.get("amount_min_man_yen"))
        or "公募要領に記載"
    )
    fetched = _normalize_iso_date(row.get("source_fetched_at")) or "最新を参照"
    apply_to = _resolve_agency(row) or "公募要領記載の申請窓口"
    exclusion = (
        "同一経費に対する重複受給は原則不可、同一事業内の他制度との併用も制限される場合があります。"
        "詳細は公募要領および jpcite 併用ルール API でご確認ください。"
    )
    qa = [
        ("対象者は誰ですか？", f"{who}が対象です。詳細要件は公募要領でご確認ください。"),
        ("金額上限はいくらですか？", f"{amt}です (目安)。年度や採択類型で変動します。"),
        (
            "締切はいつですか？",
            f"公募時期は年度ごとに更新されます。jpcite の最新取得日は{fetched}。出典ページで現在の公募状況をご確認ください。",
        ),
        (
            "申請先はどこですか？",
            f"申請先は{apply_to}です。申請窓口の詳細は公募要領に記載されています。",
        ),
        ("他の制度との併用はできますか？", exclusion),
    ]
    return {
        "@type": "FAQPage",
        "@id": f"#faq-{slug}",
        "inLanguage": "ja",
        "mainEntity": [
            {
                "@type": "Question",
                "name": q,
                "acceptedAnswer": {"@type": "Answer", "text": a},
            }
            for q, a in qa
        ],
    }


def build_json_ld(
    row: dict[str, Any],
    slug: str,
    domain: str,
    aliases: list[str],
    target_types: list[str],
    funding_purposes: list[str],
    kind_ja: str,
) -> dict[str, Any]:
    graph: list[dict[str, Any]] = [
        _org_node(domain),
        _breadcrumb_node(row, slug, domain, kind_ja),
        _service_node(row, slug, domain, aliases, target_types, funding_purposes),
    ]
    grant = _monetary_grant_node(row, slug, domain, target_types)
    if grant is not None:
        graph.append(grant)
    graph.append(_faq_node(row, slug, domain, target_types, kind_ja))
    return {"@context": "https://schema.org", "@graph": graph}


def build_standalone_json_ld(
    row: dict[str, Any],
    slug: str,
    domain: str,
    aliases: list[str],
    target_types: list[str],
    funding_purposes: list[str],
) -> dict[str, Any]:
    """Build a flat single-@type JSON-LD doc for site/structured/<unified_id>.jsonld.

    Aimed at AI training crawlers (GPTBot / ClaudeBot / etc): one @type per file,
    no @graph, no breadcrumb, no FAQ — only the canonical service node, with the
    public-URL `@id` per docs/_internal/json_ld_strategy.md §3-4.
    """
    node = _service_node(row, slug, domain, aliases, target_types, funding_purposes)
    # Re-key from in-page anchor to canonical structured-data URL.
    node["@id"] = f"https://{domain}/structured/{row['unified_id']}.jsonld"
    node["@context"] = "https://schema.org"
    # publisher reference must be self-contained (no @id ref outside the file)
    node["publisher"] = {
        "@type": "Organization",
        "@id": ORG_NODE_ID,
        "name": "jpcite",
        "url": f"https://{domain}/",
        "logo": {
            "@type": "ImageObject",
            "url": f"https://{domain}/assets/logo.png",
            "width": 600,
            "height": 60,
        },
    }
    # Move @context to top of dict for human-readable output
    out: dict[str, Any] = {"@context": node.pop("@context")}
    out.update(node)
    return out


# ---------------------------------------------------------------------------
# Related programs
# ---------------------------------------------------------------------------

RELATED_BY_TARGET_SQL = """
SELECT unified_id, primary_name, program_kind, amount_max_man_yen, amount_min_man_yen, prefecture
FROM programs
WHERE excluded = 0
  AND tier IN ('S','A','B','C')
  AND source_url IS NOT NULL AND source_url <> ''
  AND COALESCE(source_url_status, '') NOT IN ('broken', 'dead')
  AND COALESCE(source_last_check_status, 0) NOT IN (403, 404, 410)
  AND (authority_name IS NULL OR authority_name NOT LIKE '%noukaweb%')
  AND LOWER(COALESCE(source_url, '')) NOT LIKE '%//smart-hojokin.jp%'
  AND LOWER(COALESCE(source_url, '')) NOT LIKE '%//www.smart-hojokin.jp%'
  AND LOWER(COALESCE(source_url, '')) NOT LIKE '%//noukaweb.jp%'
  AND LOWER(COALESCE(source_url, '')) NOT LIKE '%//www.noukaweb.jp%'
  AND LOWER(COALESCE(source_url, '')) NOT LIKE '%//hojyokin-portal.jp%'
  AND LOWER(COALESCE(source_url, '')) NOT LIKE '%//www.hojyokin-portal.jp%'
  AND LOWER(COALESCE(source_url, '')) NOT LIKE '%//biz.stayway.jp%'
  AND LOWER(COALESCE(source_url, '')) NOT LIKE '%//www.biz.stayway.jp%'
  AND LOWER(COALESCE(source_url, '')) NOT LIKE '%//stayway.jp%'
  AND LOWER(COALESCE(source_url, '')) NOT LIKE '%//www.stayway.jp%'
  AND LOWER(COALESCE(source_url, '')) NOT LIKE '%//prtimes.jp%'
  AND LOWER(COALESCE(source_url, '')) NOT LIKE '%//www.prtimes.jp%'
  AND LOWER(COALESCE(source_url, '')) NOT LIKE '%//wikipedia.org%'
  AND LOWER(COALESCE(source_url, '')) NOT LIKE '%//www.wikipedia.org%'
  AND unified_id <> ?
  AND target_types_json IS NOT NULL
  AND target_types_json LIKE ?
ORDER BY
    (CASE WHEN prefecture IS NOT NULL AND prefecture = ? THEN 0 ELSE 1 END),
    CASE tier WHEN 'S' THEN 0 WHEN 'A' THEN 1 WHEN 'B' THEN 2 ELSE 3 END,
    unified_id
LIMIT 20
"""

RELATED_BY_KIND_SQL = """
SELECT unified_id, primary_name, program_kind, amount_max_man_yen, amount_min_man_yen, prefecture
FROM programs
WHERE excluded = 0
  AND tier IN ('S','A','B','C')
  AND source_url IS NOT NULL AND source_url <> ''
  AND COALESCE(source_url_status, '') NOT IN ('broken', 'dead')
  AND COALESCE(source_last_check_status, 0) NOT IN (403, 404, 410)
  AND (authority_name IS NULL OR authority_name NOT LIKE '%noukaweb%')
  AND LOWER(COALESCE(source_url, '')) NOT LIKE '%//smart-hojokin.jp%'
  AND LOWER(COALESCE(source_url, '')) NOT LIKE '%//www.smart-hojokin.jp%'
  AND LOWER(COALESCE(source_url, '')) NOT LIKE '%//noukaweb.jp%'
  AND LOWER(COALESCE(source_url, '')) NOT LIKE '%//www.noukaweb.jp%'
  AND LOWER(COALESCE(source_url, '')) NOT LIKE '%//hojyokin-portal.jp%'
  AND LOWER(COALESCE(source_url, '')) NOT LIKE '%//www.hojyokin-portal.jp%'
  AND LOWER(COALESCE(source_url, '')) NOT LIKE '%//biz.stayway.jp%'
  AND LOWER(COALESCE(source_url, '')) NOT LIKE '%//www.biz.stayway.jp%'
  AND LOWER(COALESCE(source_url, '')) NOT LIKE '%//stayway.jp%'
  AND LOWER(COALESCE(source_url, '')) NOT LIKE '%//www.stayway.jp%'
  AND LOWER(COALESCE(source_url, '')) NOT LIKE '%//prtimes.jp%'
  AND LOWER(COALESCE(source_url, '')) NOT LIKE '%//www.prtimes.jp%'
  AND LOWER(COALESCE(source_url, '')) NOT LIKE '%//wikipedia.org%'
  AND LOWER(COALESCE(source_url, '')) NOT LIKE '%//www.wikipedia.org%'
  AND unified_id <> ?
  AND program_kind = ?
ORDER BY
    (CASE WHEN prefecture IS NOT NULL AND prefecture = ? THEN 0 ELSE 1 END),
    CASE tier WHEN 'S' THEN 0 WHEN 'A' THEN 1 WHEN 'B' THEN 2 ELSE 3 END,
    unified_id
LIMIT 20
"""


def _related_programs(
    conn: sqlite3.Connection,
    row: dict[str, Any],
    target_types: list[str],
    limit: int = 8,
    publishable_slugs: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Return up to `limit` related programs, target_types match first, then program_kind.

    Overfetches, then dedups any cluster of 3+ entries sharing the same
    first-6-char primary_name prefix (drops the trailing duplicates of the
    cluster) to avoid e.g. 4 nearly-identical wave variants. Final 5-8.
    """
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    cur_pref = row.get("prefecture")
    # Overfetch ~3x so post-dedup we can still hit `limit`.
    overfetch_cap = max(limit * 3, 24)

    # target_types match (LIKE '%type%')
    for tt in target_types[:3]:  # query top 3 types only
        if len(out) >= overfetch_cap:
            break
        pattern = f"%{tt}%"
        for r in conn.execute(RELATED_BY_TARGET_SQL, (row["unified_id"], pattern, cur_pref)):
            d = dict(r)
            uid = d["unified_id"]
            if uid in seen:
                continue
            seen.add(uid)
            out.append(d)
            if len(out) >= overfetch_cap:
                break

    # fallback: same program_kind
    if len(out) < overfetch_cap and row.get("program_kind"):
        for r in conn.execute(
            RELATED_BY_KIND_SQL, (row["unified_id"], row["program_kind"], cur_pref)
        ):
            d = dict(r)
            uid = d["unified_id"]
            if uid in seen:
                continue
            seen.add(uid)
            out.append(d)
            if len(out) >= overfetch_cap:
                break

    # Dedup clusters: 3+ entries sharing first-6-char prefix → keep first 2.
    prefix_counts: dict[str, int] = {}
    deduped: list[dict[str, Any]] = []
    # First pass: count
    for d in out:
        prefix = (d.get("primary_name") or "")[:6]
        prefix_counts[prefix] = prefix_counts.get(prefix, 0) + 1
    # Second pass: keep up to 2 per cluster when cluster is 3+
    kept_per_prefix: dict[str, int] = {}
    for d in out:
        prefix = (d.get("primary_name") or "")[:6]
        cap = 2 if prefix_counts.get(prefix, 0) >= 3 else prefix_counts.get(prefix, 0)
        if kept_per_prefix.get(prefix, 0) < cap:
            deduped.append(d)
            kept_per_prefix[prefix] = kept_per_prefix.get(prefix, 0) + 1

    shaped = []
    for d in deduped:
        public_name = _public_program_name(d["primary_name"])
        if not _is_public_title_quality_ok(public_name):
            continue
        rp_slug = slugify(d["primary_name"] or "", d["unified_id"])
        if publishable_slugs is not None and rp_slug not in publishable_slugs:
            continue
        shaped.append(
            {
                "slug": rp_slug,
                "name": public_name,
                "kind_ja": KIND_JA.get(d.get("program_kind") or "subsidy", "公的支援制度"),
                "amount_line": _amount_line(
                    d.get("amount_max_man_yen"), d.get("amount_min_man_yen")
                ),
            }
        )
        if len(shaped) >= limit:
            break
    return shaped


def _publishable_program_slugs(rows: list[dict[str, Any]]) -> set[str]:
    """Return slugs that this generator run can emit as static program pages."""
    slugs: set[str] = set()
    for row in rows:
        if not _is_public_title_quality_ok(row.get("primary_name")):
            continue
        slugs.add(slugify(row.get("primary_name") or "", row["unified_id"]))
    return slugs


# ---------------------------------------------------------------------------
# Acceptance-rate stats (am_acceptance_stat)
# ---------------------------------------------------------------------------


# `am_acceptance_stat.program_entity_id` is the autonomath canonical id; the
# format varies (e.g. `program:base:<10-hex>`, `program:saikouchiku:meti:...`,
# `program:gx:meti-enecho:...`). We bridge to jpintel `programs.unified_id` via
# the `entity_id_map` view (88 jpi_unified_id → 69 am_canonical_id mappings
# established by the cross-domain entity resolution job). CLAUDE.md forbids
# ATTACH / cross-DB JOIN, so we open a *separate* read-only connection.

ACCEPTANCE_STATS_SQL = """
SELECT
    s.program_entity_id  AS am_canonical_id,
    s.round_label,
    s.application_date,
    s.applied_count,
    s.accepted_count,
    s.acceptance_rate_pct,
    m.jpi_unified_id     AS jpi_unified_id
FROM am_acceptance_stat s
LEFT JOIN entity_id_map m
       ON m.am_canonical_id = s.program_entity_id
WHERE s.acceptance_rate_pct IS NOT NULL
ORDER BY s.program_entity_id, s.application_date DESC, s.round_label DESC
"""


def load_acceptance_stats(db_path: Path) -> dict[str, dict[str, Any]]:
    """Pre-load all am_acceptance_stat rows into a unified_id-keyed dict.

    Returns mapping: unified_id ('UNI-xxxxxxxxxx') -> {
        'rounds': int,
        'min_pct': '16.97',
        'max_pct': '67.15',
        'avg_pct': '48.29',
        'recent': [
            {'round_label': str, 'application_date': str|None,
             'applied_count': int|None, 'accepted_count': int|None,
             'rate_pct': '67.15'},
            ...   (up to 5 most-recent rounds)
        ],
    }

    Bridge order: (1) `entity_id_map` view (canonical), (2) bare-hex fallback
    where `program:base:<hex>` directly mirrors `UNI-<hex>` for older rows
    that haven't been re-resolved into the map yet. A missing program is
    simply absent — the template renders "採択率公表データなし" for it.
    Returns {} if the DB is missing.
    """
    if not db_path.exists():
        LOG.warning(
            "autonomath.db not found at %s — acceptance stats disabled "
            "(template will render '採択率公表データなし' for all programs)",
            db_path,
        )
        return {}

    out: dict[str, dict[str, Any]] = {}
    # Read-only URI guards against accidental writes (autonomath.db is 8.3 GB
    # and we never want a stray INSERT here).
    uri = f"file:{db_path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        conn.row_factory = sqlite3.Row
        for row in conn.execute(ACCEPTANCE_STATS_SQL):
            am_id = row["am_canonical_id"] or ""
            unified_id = row["jpi_unified_id"]
            if not unified_id and am_id.startswith("program:base:"):
                # Fallback: legacy 1:1 hex mirror.
                unified_id = "UNI-" + am_id[len("program:base:") :]
            if not unified_id:
                continue
            slot = out.setdefault(
                unified_id,
                {
                    "rounds": 0,
                    "_rates": [],
                    "recent": [],
                },
            )
            rate = row["acceptance_rate_pct"]
            slot["rounds"] += 1
            slot["_rates"].append(float(rate))
            if len(slot["recent"]) < 5:
                slot["recent"].append(
                    {
                        "round_label": row["round_label"],
                        "application_date": row["application_date"],
                        "applied_count": row["applied_count"],
                        "accepted_count": row["accepted_count"],
                        "rate_pct": f"{float(rate):.2f}",
                    }
                )
    finally:
        conn.close()

    # Finalise aggregates and drop the working list.
    for stats in out.values():
        rates = stats.pop("_rates")
        stats["min_pct"] = f"{min(rates):.2f}"
        stats["max_pct"] = f"{max(rates):.2f}"
        stats["avg_pct"] = f"{sum(rates) / len(rates):.2f}"

    LOG.info("loaded acceptance stats for %d programs", len(out))
    return out


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------


@dataclass
class RenderContext:
    env: Environment
    template_name: str = "program.html"

    def render(self, **ctx: Any) -> str:
        tmpl = self.env.get_template(self.template_name)
        return tmpl.render(**ctx)


def _build_env(template_dir: Path) -> Environment:
    return Environment(
        loader=FileSystemLoader(str(template_dir)),
        autoescape=select_autoescape(enabled_extensions=("html", "xml"), default=True),
        trim_blocks=False,
        lstrip_blocks=False,
    )


# ---------------------------------------------------------------------------
# Program → QA crossref (deterministic mapping; matches QA topic_slug values
# defined in scripts/generate_geo_citation_pages.py).
# ---------------------------------------------------------------------------

# Topic slug → (label, list of [(qa_slug, h1)]). 3-5 entries each.
# Each (qa_slug, h1) corresponds to a real /qa/{topic_slug}/{qa_slug}.html page
# emitted by generate_geo_citation_pages.py. Keep in sync when QA pages move.
_QA_TOPICS: dict[str, dict[str, Any]] = {
    "it-subsidy": {
        "label": "IT導入補助金",
        "entries": [
            ("overview", "IT導入補助金とは何か"),
            ("application-method", "IT導入補助金の申請方法"),
            ("schedule", "IT導入補助金の公募スケジュール"),
            ("invoice-frame", "IT導入補助金 インボイス対応類型"),
        ],
    },
    "monozukuri-subsidy": {
        "label": "ものづくり補助金",
        "entries": [
            ("application-method", "ものづくり補助金の申請方法"),
            ("acceptance-rate", "ものづくり補助金の採択率"),
            ("frames", "ものづくり補助金の申請枠"),
            ("chinage-youken", "ものづくり補助金の賃上げ要件"),
        ],
    },
    "jizokuka-subsidy": {
        "label": "小規模事業者持続化補助金",
        "entries": [
            ("application-method", "持続化補助金の申請方法"),
            ("frames", "持続化補助金の申請枠"),
        ],
    },
    "restructuring-subsidy": {
        "label": "事業再構築補助金",
        "entries": [
            ("overview", "事業再構築補助金とは何か"),
            ("frames", "事業再構築補助金の申請枠"),
        ],
    },
    "chinage-tax": {
        "label": "賃上げ促進税制",
        "entries": [
            ("overview", "賃上げ促進税制とは何か"),
            ("calc", "賃上げ促進税制の控除額計算"),
        ],
    },
    "rd-tax": {
        "label": "研究開発税制",
        "entries": [
            ("overview", "研究開発税制とは何か"),
        ],
    },
    "shotoku-kojo": {
        "label": "所得拡大促進税制",
        "entries": [
            ("overview", "所得拡大促進税制とは何か"),
        ],
    },
    "toushi-tax": {
        "label": "中小企業投資促進税制",
        "entries": [
            ("overview", "中小企業投資促進税制とは何か"),
        ],
    },
    "keieikyoka-tax": {
        "label": "経営強化税制",
        "entries": [
            ("overview", "経営強化税制とは何か"),
        ],
    },
    "invoice": {
        "label": "インボイス制度",
        "entries": [
            ("overview", "インボイス制度とは何か"),
            ("registration", "インボイス制度の登録手続き"),
        ],
    },
    "dencho": {
        "label": "電子帳簿保存法",
        "entries": [
            ("overview", "電子帳簿保存法とは何か"),
        ],
    },
    "jfc": {
        "label": "日本政策金融公庫融資",
        "entries": [
            ("overview", "日本政策金融公庫の融資制度"),
        ],
    },
    "hojin-tax": {
        "label": "法人税",
        "entries": [
            ("overview", "法人税の基礎"),
        ],
    },
    "shouhi-tax": {
        "label": "消費税",
        "entries": [
            ("overview", "消費税の基礎"),
        ],
    },
    "shoukei": {
        "label": "事業承継",
        "entries": [
            ("overview", "事業承継とは何か"),
        ],
    },
    "gx": {
        "label": "GX関連",
        "entries": [
            ("overview", "GX関連制度の概要"),
        ],
    },
    "law": {
        "label": "中小企業関連法",
        "entries": [
            ("overview", "中小企業関連法の概要"),
        ],
    },
}


def _static_public_path_exists(site_root: Path, public_path: str) -> bool:
    target = site_root / public_path.lstrip("/")
    return (
        target.exists()
        or (target.suffix == "" and target.with_suffix(".html").exists())
        or (target / "index.html").exists()
    )


def _related_qa_for_program(
    row: dict[str, Any], site_root: Path = REPO_ROOT / "site"
) -> list[dict[str, str]]:
    """Pick 3-5 deterministic QA links based on program_kind + primary_name keywords.

    Returns a list of {topic_slug, qa_slug, label, h1, url} dicts. Empty if no
    confident match — the template tolerates that.
    """
    kind = (row.get("program_kind") or "").lower()
    name = row.get("primary_name") or ""

    # Name-keyword routing first (more specific than program_kind).
    routes: list[str] = []
    if "IT導入" in name or "it導入" in name.lower():
        routes.append("it-subsidy")
    if "ものづくり" in name:
        routes.append("monozukuri-subsidy")
    if "持続化" in name or "小規模事業者" in name:
        routes.append("jizokuka-subsidy")
    if "事業再構築" in name or "再構築" in name:
        routes.append("restructuring-subsidy")
    if "賃上げ" in name:
        routes.append("chinage-tax")
    if "研究開発" in name and "税" in name:
        routes.append("rd-tax")
    if "投資促進" in name and "税" in name:
        routes.append("toushi-tax")
    if "経営強化" in name and "税" in name:
        routes.append("keieikyoka-tax")
    if "インボイス" in name or "適格請求書" in name:
        routes.append("invoice")
    if "電子帳簿" in name:
        routes.append("dencho")
    if "事業承継" in name:
        routes.append("shoukei")
    if "公庫" in name or "JFC" in name.upper():
        routes.append("jfc")
    if "GX" in name.upper() or "脱炭素" in name or "省エネ" in name:
        routes.append("gx")

    # Fallback by kind bucket.
    if not routes:
        bucket = _classify_kind(kind)
        if bucket == "loan":
            routes.append("jfc")
        elif kind in ("subsidy", "grant"):
            # Generic subsidy → most-cited QA topic
            routes.append("monozukuri-subsidy")
        elif "tax" in kind or kind in ("tax_credit", "tax_incentive"):
            routes.append("hojin-tax")
        elif "certification" in kind or "認定" in name:
            routes.append("law")

    if not routes:
        return []

    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for topic_slug in routes:
        topic = _QA_TOPICS.get(topic_slug)
        if topic is None:
            continue
        for qa_slug, h1 in topic["entries"]:
            key = f"{topic_slug}/{qa_slug}"
            if key in seen:
                continue
            url = f"/qa/{topic_slug}/{qa_slug}.html"
            if not _static_public_path_exists(site_root, url):
                continue
            seen.add(key)
            out.append(
                {
                    "topic_slug": topic_slug,
                    "topic_label": topic["label"],
                    "qa_slug": qa_slug,
                    "h1": h1,
                    "url": url,
                }
            )
            if len(out) >= 5:
                return out
    return out


def render_row(
    row: dict[str, Any],
    ctx: RenderContext,
    domain: str,
    related: list[dict[str, Any]],
    acceptance_stats: dict[str, Any] | None = None,
    site_root: Path = REPO_ROOT / "site",
) -> tuple[str, str, dict[str, Any]]:
    """Return (slug, html, standalone_json_ld_doc)."""
    original_name = row.get("primary_name") or ""
    slug = slugify(original_name, row["unified_id"])
    row = dict(row)
    row["primary_name"] = _public_program_name(original_name)
    aliases = _sanitize_aliases_for_public(
        _parse_json_list(row.get("aliases_json")), row["primary_name"]
    )
    target_types = _parse_json_list(row.get("target_types_json"))
    funding_purposes = _parse_json_list(row.get("funding_purpose_json"))
    kind_ja = KIND_JA.get(row.get("program_kind") or "subsidy", "公的支援制度")

    source_url = row.get("source_url") or row.get("official_url") or ""
    source_domain = _source_domain(source_url)
    resolved_agency = _resolve_agency(row)
    source_org = resolved_agency  # may be None; template must tolerate

    tldr = _tldr(row, target_types, aliases)

    json_ld = build_json_ld(row, slug, domain, aliases, target_types, funding_purposes, kind_ja)
    standalone_jsonld = build_standalone_json_ld(
        row, slug, domain, aliases, target_types, funding_purposes
    )

    related_public: list[dict[str, Any]] = []
    for item in related:
        item_public = dict(item)
        item_public["name"] = _public_program_name(item_public.get("name"))
        related_public.append(item_public)

    html = ctx.render(
        DOMAIN=domain,
        unified_id=row["unified_id"],
        slug=slug,
        primary_name=row["primary_name"],
        page_title=_page_title(row, target_types),
        meta_description=_meta_description(row, target_types),
        aliases=aliases,
        tier=row.get("tier"),
        authority_name=row.get("authority_name"),
        resolved_agency=resolved_agency,
        prefecture=row.get("prefecture"),
        prefecture_slug=_PREF_JA_TO_SLUG.get(row.get("prefecture") or ""),
        program_kind=row.get("program_kind") or "subsidy",
        kind_ja=kind_ja,
        amount_line=_amount_line(row.get("amount_max_man_yen"), row.get("amount_min_man_yen")),
        subsidy_rate_line=_subsidy_rate_line(row.get("subsidy_rate")),
        target_types=target_types,
        target_types_ja=_target_types_list_ja(target_types),
        target_types_text=_target_types_text(target_types),
        funding_purposes=funding_purposes,
        tldr_what=tldr["what"],
        tldr_who=tldr["who"],
        tldr_how_much=tldr["how_much"],
        tldr_when=tldr["when"],
        summary_paragraph=_summary_paragraph(row, aliases),
        amount_paragraph=_amount_paragraph(row),
        deadline_paragraph=_deadline_paragraph(row),
        exclusion_paragraph=_exclusion_paragraph(row),
        fetched_at_ja=_last_updated_ja(row),
        fetched_at=_normalize_iso_date(row.get("source_fetched_at")),
        source_url=source_url,
        source_domain=source_domain,
        source_org=source_org,
        related_programs=related_public,
        related_qa=_related_qa_for_program(row, site_root=site_root),
        acceptance_stats=acceptance_stats,
        json_ld_pretty=json.dumps(json_ld, ensure_ascii=False, indent=2).replace("</", "<\\/"),
    )
    return slug, html, standalone_jsonld


# ---------------------------------------------------------------------------
# Write helpers (idempotent)
# ---------------------------------------------------------------------------


def _write_if_changed(path: Path, content: str) -> bool:
    """Return True if file was written (differed or absent), False if unchanged."""
    if path.exists():
        try:
            existing = path.read_text(encoding="utf-8")
        except OSError:
            existing = None
        if existing == content:
            return False
    path.write_text(content, encoding="utf-8")
    return True


# ---------------------------------------------------------------------------
# Sitemap
# ---------------------------------------------------------------------------


# Per-tier sitemap hints. SEO crawlers use changefreq as a hint (not a contract)
# to budget recrawl frequency. Higher-confidence tiers refresh in our pipeline
# more often, so we surface that signal honestly.
#   S/A — current-active, frequently re-verified → weekly
#   B   — known-active, periodic verification     → monthly
#   C   — long-tail, low-frequency verification   → quarterly (yearly per spec)
# Tier X is excluded by INDEXABLE_SQL upstream (CLAUDE.md gotcha).
_TIER_CHANGEFREQ = {
    "S": "weekly",
    "A": "weekly",
    "B": "monthly",
    "C": "yearly",
}
_TIER_PRIORITY = {
    "S": "0.9",
    "A": "0.8",
    "B": "0.6",
    "C": "0.4",
}


def _sitemap_entry(slug: str, lastmod: str, tier: str = "C") -> list[str]:
    cf = _TIER_CHANGEFREQ.get(tier, "monthly")
    pr = _TIER_PRIORITY.get(tier, "0.6")
    return [
        "  <url>",
        f"    <loc>https://{{domain}}/programs/{slug}</loc>".replace("{domain}", "__D__"),
        f"    <lastmod>{lastmod}</lastmod>",
        f"    <changefreq>{cf}</changefreq>",
        f"    <priority>{pr}</priority>",
        "  </url>",
    ]


def write_sitemap(
    entries: list[tuple[str, str, str]],  # [(slug, lastmod_iso, tier), ...]
    path: Path,
    domain: str,
    sitemap_index_path: Path | None = None,
) -> list[Path]:
    """Write sitemap(s). Split into sitemap-programs-{N}.xml when > SITEMAP_URL_CAP.

    Each entry is `(slug, lastmod_iso, tier)`. `tier` drives `<changefreq>` and
    `<priority>` (S/A=weekly/0.9-0.8, B=monthly/0.6, C=yearly/0.4).
    `lastmod` should be derived from `source_fetched_at` (the day we last pulled
    the primary source) so the SEO signal matches data-currency reality, with
    `updated_at` as a secondary fallback.

    Returns list of files written.
    """
    if not entries:
        return []

    written: list[Path] = []
    header = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        "<!-- Program sitemap shard for jpcite.com. -->",
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]
    footer = ["</urlset>"]

    def _dump(chunk: list[tuple[str, str, str]], out_path: Path) -> None:
        lines = list(header)
        for slug, lastmod, tier in chunk:
            cf = _TIER_CHANGEFREQ.get(tier, "monthly")
            pr = _TIER_PRIORITY.get(tier, "0.6")
            lines.append("  <url>")
            lines.append(f"    <loc>https://{domain}/programs/{slug}</loc>")
            lines.append(f"    <lastmod>{lastmod}</lastmod>")
            lines.append(f"    <changefreq>{cf}</changefreq>")
            lines.append(f"    <priority>{pr}</priority>")
            lines.append("  </url>")
        lines.extend(footer)
        body = "\n".join(lines) + "\n"
        _write_if_changed(out_path, body)
        written.append(out_path)

    if len(entries) <= SITEMAP_URL_CAP:
        _dump(entries, path)
        return written

    # split
    parent = path.parent
    base = path.stem  # e.g. "sitemap-programs"
    # pop any pre-existing split files to rewrite deterministically
    chunks = [entries[i : i + SITEMAP_URL_CAP] for i in range(0, len(entries), SITEMAP_URL_CAP)]
    for idx, chunk in enumerate(chunks, start=1):
        _dump(chunk, parent / f"{base}-{idx}.xml")

    # write a local programs-sitemap index referencing the shards.
    # Per-shard <lastmod> = max(source_fetched_at) across that shard, so the
    # index is also data-driven (not a uniform `today` sentinel).
    index_path = path  # reuse sitemap-programs.xml as the shard index
    today = _today_jst_iso()
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        "<!-- Program sitemap index for jpcite.com. -->",
        '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]
    for idx, chunk in enumerate(chunks, start=1):
        shard_lastmod = max((lm for _s, lm, _t in chunk), default=today)
        lines.append("  <sitemap>")
        lines.append(f"    <loc>https://{domain}/{base}-{idx}.xml</loc>")
        lines.append(f"    <lastmod>{shard_lastmod}</lastmod>")
        lines.append("  </sitemap>")
    lines.append("</sitemapindex>")
    _write_if_changed(index_path, "\n".join(lines) + "\n")
    written.append(index_path)
    return written


# ---------------------------------------------------------------------------
# Top-level generation
# ---------------------------------------------------------------------------


def _iter_rows(
    conn: sqlite3.Connection,
    limit: int | None,
    tiers: tuple[str, ...] = ("S", "A", "B", "C"),
    bad_urls: set[str] | None = None,
) -> Iterable[dict[str, Any]]:
    """Yield indexable program rows. ``tiers`` controls the WHERE filter.

    The 2026-04-29 SEO AI-feel reduction collapsed the published HTML pages
    from tier S/A/B/C (~11k pages) to S/A only (~1.4k). B/C tier rows are
    still searchable via the API + dashboard (`/programs/?id=UNI-...`); only
    the static SSG pages are dropped.
    """
    safe_tiers = [t for t in tiers if t in ("S", "A", "B", "C")] or ["S", "A"]
    tier_in = ",".join(f"'{t}'" for t in safe_tiers)
    sql = INDEXABLE_SQL_TEMPLATE.format(tier_in=tier_in, banned_source_sql=BANNED_SOURCE_SQL)
    if limit is not None and limit > 0:
        sql = sql + f"\nLIMIT {limit}"
    denied = bad_urls or set()
    for row in conn.execute(sql):
        row_d = dict(row)
        if row_d.get("source_url") in denied:
            continue
        yield row_d


def _prune_stale_generated_files(
    *,
    out_dir: Path,
    expected_html: set[Path],
    structured_dir: Path | None,
    expected_jsonld: set[Path],
) -> None:
    """Remove generated pages whose rows are no longer publishable."""
    if out_dir.exists():
        for path in out_dir.glob("*.html"):
            if path.name in _RESERVED_PROGRAM_HTML:
                continue
            if path not in expected_html:
                path.unlink(missing_ok=True)
    if structured_dir and structured_dir.exists():
        for path in structured_dir.glob("*.jsonld"):
            if path not in expected_jsonld:
                path.unlink(missing_ok=True)


def _write_structured_sitemap(
    entries: list[tuple[str, str, str]],  # [(unified_id, lastmod_iso, tier), ...]
    path: Path,
    domain: str,
) -> None:
    """Write site/sitemap-structured.xml — one entry per .jsonld file.

    Mirrors per-tier changefreq from the HTML sitemap so JSON-LD docs share the
    same recrawl-budget signal. `priority` stays lower (these are alt-format
    duplicates of the HTML pages, not primary content).
    """
    if not entries:
        return
    structured_priority = {"S": "0.5", "A": "0.4", "B": "0.3", "C": "0.2"}
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        "<!-- Program structured-data sitemap shard for jpcite.com. -->",
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]
    for uid, lastmod, tier in entries:
        cf = _TIER_CHANGEFREQ.get(tier, "monthly")
        pr = structured_priority.get(tier, "0.3")
        lines.append("  <url>")
        lines.append(f"    <loc>https://{domain}/structured/{uid}.jsonld</loc>")
        lines.append(f"    <lastmod>{lastmod}</lastmod>")
        lines.append(f"    <changefreq>{cf}</changefreq>")
        lines.append(f"    <priority>{pr}</priority>")
        lines.append("  </url>")
    lines.append("</urlset>")
    _write_if_changed(path, "\n".join(lines) + "\n")


def _write_jsonld_doc(out_path: Path, doc: dict[str, Any]) -> bool:
    body = json.dumps(doc, ensure_ascii=False, indent=2) + "\n"
    return _write_if_changed(out_path, body)


def generate(
    db_path: Path,
    out_dir: Path,
    template_dir: Path,
    domain: str,
    limit: int | None,
    samples_dir: Path | None,
    sample_ids: list[str] | None,
    sitemap_path: Path | None,
    structured_dir: Path | None = None,
    sitemap_structured_path: Path | None = None,
    autonomath_db_path: Path | None = None,
    tiers: tuple[str, ...] = ("S", "A", "B", "C"),
) -> tuple[int, int, int]:
    """Returns (written, skipped, errors).

    `written` and `skipped` count HTML pages only (one per row), to keep parity
    with the historical contract. JSON-LD writes are logged but not counted.
    """
    if not db_path.exists():
        LOG.error("database not found: %s", db_path)
        raise SystemExit(1)
    if not (template_dir / "program.html").exists():
        LOG.error("template not found: %s/program.html", template_dir)
        raise SystemExit(1)

    out_dir.mkdir(parents=True, exist_ok=True)
    if samples_dir:
        samples_dir.mkdir(parents=True, exist_ok=True)
    if structured_dir:
        structured_dir.mkdir(parents=True, exist_ok=True)

    env = _build_env(template_dir)
    ctx = RenderContext(env=env)

    # Pre-load acceptance stats from autonomath.db (separate connection — no
    # ATTACH / cross-DB JOIN per CLAUDE.md). 522 rows / ~70 programs total,
    # safe to keep entirely in memory.
    acceptance_map: dict[str, dict[str, Any]] = (
        load_acceptance_stats(autonomath_db_path) if autonomath_db_path is not None else {}
    )

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    written = 0
    skipped = 0
    errors = 0
    sitemap_entries: list[tuple[str, str, str]] = []
    structured_entries: list[tuple[str, str, str]] = []
    expected_html: set[Path] = set()
    expected_jsonld: set[Path] = set()
    jsonld_count = 0
    bad_urls = load_static_bad_urls()
    if bad_urls:
        LOG.info("loaded static bad-url denylist: %d urls", len(bad_urls))

    # --- sample mode
    if sample_ids and samples_dir:
        existing_program_slugs = {
            path.stem
            for path in out_dir.glob("*.html")
            if path.name not in _RESERVED_PROGRAM_HTML
        }
        for sid in sample_ids:
            cur = conn.execute(SAMPLE_BY_ID_SQL, (sid,))
            row = cur.fetchone()
            if row is None:
                LOG.warning("sample id not found in db: %s", sid)
                continue
            row_d = dict(row)
            try:
                tts = _parse_json_list(row_d.get("target_types_json"))
                related = _related_programs(
                    conn, row_d, tts, limit=8, publishable_slugs=existing_program_slugs
                )
                slug, html, standalone = render_row(
                    row_d,
                    ctx,
                    domain,
                    related,
                    acceptance_stats=acceptance_map.get(row_d.get("unified_id") or ""),
                )
                changed = _write_if_changed(samples_dir / f"{slug}.html", html)
                if changed:
                    written += 1
                else:
                    skipped += 1
                if structured_dir:
                    _write_jsonld_doc(structured_dir / f"{row_d['unified_id']}.jsonld", standalone)
                    jsonld_count += 1
            except Exception as exc:  # noqa: BLE001
                LOG.exception("sample render failed for %s: %s", sid, exc)
                errors += 1
        if structured_dir:
            LOG.info("samples: %d HTML + %d standalone JSON-LD", written, jsonld_count)
        return written, skipped, errors

    # --- bulk mode
    rows = list(_iter_rows(conn, limit, tiers=tiers, bad_urls=bad_urls))
    publishable_slugs = _publishable_program_slugs(rows)
    for row in rows:
        try:
            if not _is_public_title_quality_ok(row.get("primary_name")):
                LOG.info(
                    "skip low-quality public title uid=%s name=%r",
                    row.get("unified_id"),
                    row.get("primary_name"),
                )
                continue
            tts = _parse_json_list(row.get("target_types_json"))
            related = _related_programs(
                conn, row, tts, limit=8, publishable_slugs=publishable_slugs
            )
            slug, html, standalone = render_row(
                row,
                ctx,
                domain,
                related,
                acceptance_stats=acceptance_map.get(row.get("unified_id") or ""),
            )
            path = out_dir / f"{slug}.html"
            expected_html.add(path)
            changed = _write_if_changed(path, html)
            if changed:
                written += 1
            else:
                skipped += 1
            # Sitemap <lastmod> is the day we last *fetched* the primary
            # source — `source_fetched_at`. This is the SEO-honest signal
            # crawlers expect (when did the underlying content last change
            # from our perspective). Fall back to `updated_at` (DB row touch)
            # then today's JST date as a last-resort sentinel.
            # CLAUDE.md gotcha: many `source_fetched_at` values are a uniform
            # bulk-rewrite sentinel — that's the actual day we last pulled the
            # source for that row, which is what we want here.
            lastmod = (
                _normalize_iso_date(row.get("source_fetched_at"))
                or _normalize_iso_date(row.get("updated_at"))
                or _today_jst_iso()
            )
            tier = (row.get("tier") or "C").upper()
            sitemap_entries.append((slug, lastmod, tier))
            if structured_dir:
                jsonld_path = structured_dir / f"{row['unified_id']}.jsonld"
                expected_jsonld.add(jsonld_path)
                _write_jsonld_doc(jsonld_path, standalone)
                jsonld_count += 1
                structured_entries.append((row["unified_id"], lastmod, tier))
        except Exception as exc:  # noqa: BLE001
            LOG.exception("render failed for %s: %s", row.get("unified_id"), exc)
            errors += 1

    if sitemap_path is not None and sitemap_entries:
        write_sitemap(sitemap_entries, sitemap_path, domain)
    if sitemap_structured_path is not None and structured_entries:
        _write_structured_sitemap(structured_entries, sitemap_structured_path, domain)
    if structured_dir:
        LOG.info("standalone JSON-LD docs written: %d", jsonld_count)
    if limit is None:
        _prune_stale_generated_files(
            out_dir=out_dir,
            expected_html=expected_html,
            structured_dir=structured_dir,
            expected_jsonld=expected_jsonld,
        )

    return written, skipped, errors


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db", default=str(DEFAULT_DB), type=Path)
    p.add_argument(
        "--autonomath-db",
        default=str(DEFAULT_AUTONOMATH_DB),
        type=Path,
        help=(
            "path to autonomath.db (am_acceptance_stat lives here); pass empty "
            "string to disable acceptance-rate enrichment"
        ),
    )
    p.add_argument("--out", default=str(DEFAULT_OUT), type=Path)
    p.add_argument("--template-dir", default=str(DEFAULT_TEMPLATE_DIR), type=Path)
    p.add_argument(
        "--domain",
        default=os.environ.get("JPINTEL_DOMAIN", DEFAULT_DOMAIN),
        help=f"domain used in canonical URLs; default {DEFAULT_DOMAIN}",
    )
    p.add_argument("--limit", type=int, default=None, help="cap rows (debug)")
    p.add_argument(
        "--tiers",
        default="S,A,B,C",
        help=(
            "comma-separated tier filter (default: S,A — the 2026-04-29 SEO "
            "AI-feel reduction). Pass 'S,A,B,C' to render the legacy 10k+ pages."
        ),
    )
    p.add_argument("--samples-dir", type=Path, default=DEFAULT_SAMPLES)
    p.add_argument(
        "--sample-ids",
        type=str,
        default=None,
        help="comma-separated unified_id list; render only these to samples-dir",
    )
    p.add_argument(
        "--sitemap",
        type=Path,
        default=DEFAULT_SITEMAP,
        help="sitemap file to (over)write; pass empty string to skip",
    )
    p.add_argument(
        "--structured-dir",
        type=Path,
        default=None,
        help=(
            "DEPRECATED 2026-05-03: directory for site/structured/<unified_id>.jsonld."
            " JSON-LD is now inlined in /programs/<slug>.html (one"
            " <script type='application/ld+json'> per page) so this opt-in surface"
            " is no longer shipped to Cloudflare Pages. Pass an explicit path to"
            " regenerate the local cache for inspection only."
        ),
    )
    p.add_argument(
        "--sitemap-structured",
        type=Path,
        default=None,
        help=("DEPRECATED 2026-05-03: sitemap-structured.xml path. See --structured-dir."),
    )
    p.add_argument(
        "--no-structured",
        action="store_true",
        default=True,
        help=(
            "DEPRECATED 2026-05-03: now the default — site/structured/*.jsonld is"
            " no longer emitted. Retained as a no-op for callers that still pass it."
        ),
    )
    p.add_argument("--verbose", "-v", action="store_true")
    return p.parse_args()


def main() -> int:
    args = _parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    sample_ids = (
        [s.strip() for s in args.sample_ids.split(",") if s.strip()] if args.sample_ids else None
    )
    sitemap_path = args.sitemap if (args.sitemap and str(args.sitemap) != "") else None
    if sample_ids:
        sitemap_path = None  # sample mode doesn't touch sitemap

    # 2026-05-03: structured/ shards retired by default — JSON-LD is now inlined
    # in every /programs/<slug>.html page. The --structured-dir / --sitemap-structured
    # flags are retained as opt-in escape hatches for local inspection only;
    # passing an explicit path resurrects the legacy behavior for that one run.
    structured_dir = (
        args.structured_dir if (args.structured_dir and str(args.structured_dir) != "") else None
    )
    sitemap_structured_path = (
        args.sitemap_structured
        if (args.sitemap_structured and str(args.sitemap_structured) != "")
        else None
    )
    if sample_ids:
        sitemap_structured_path = None  # sample mode skips sitemap

    autonomath_db = (
        args.autonomath_db if (args.autonomath_db and str(args.autonomath_db) != "") else None
    )

    tiers_tuple = tuple(t.strip().upper() for t in str(args.tiers).split(",") if t.strip())
    if not tiers_tuple:
        tiers_tuple = ("S", "A")

    written, skipped, errors = generate(
        db_path=args.db,
        out_dir=args.out,
        template_dir=args.template_dir,
        domain=args.domain,
        limit=args.limit,
        samples_dir=args.samples_dir,
        sample_ids=sample_ids,
        sitemap_path=sitemap_path,
        structured_dir=structured_dir,
        sitemap_structured_path=sitemap_structured_path,
        autonomath_db_path=autonomath_db,
        tiers=tiers_tuple,
    )
    LOG.info("written=%d skipped=%d errors=%d", written, skipped, errors)
    return 0


if __name__ == "__main__":
    sys.exit(main())
