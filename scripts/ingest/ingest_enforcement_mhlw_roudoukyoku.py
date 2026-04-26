#!/usr/bin/env python3
"""Ingest 47 都道府県労働局 「労働基準関係法令違反に係る公表事案」 into
``am_enforcement_detail`` + ``am_entities``.

Background:
  既に am_enforcement_detail に厚生労働省由来の row が存在するが、それらは
  「雇用関係助成金等の不正受給」事案 (kind=subsidy_exclude) で、本来の
  「労働基準法 / 労働安全衛生法 違反 → 書類送検」公表事案とは別ソース。
  本スクリプトは後者 (kind=business_improvement) を 47 局分まとめて取り込む。

Sources:
  PRIMARY: 厚労省労働基準局監督課 全国まとめ PDF
    https://www.mhlw.go.jp/content/001684100.pdf  (令和8年3月31日掲載分,
    令和7年3月1日～令和8年2月28日 公表分, 46 都道府県, 459 件)
    — 1 PDF で 47 局分が prefecture header 付き表で並ぶので最も効率的。

  FALLBACK: jsite.mhlw.go.jp/{pref}-roudoukyoku/.../...pdf (per-prefecture)
    — 国pdf に未収載 (例: 島根) や より新しい更新がある場合に補填。

License: 厚生労働省ウェブサイト (政府機関の著作物、転載引用可、出典明記).

Strategy:
  1. 国 PDF を取得 → pdfplumber でページ毎に table 抽出 → prefecture header
     行 ('北海道労働局' 等) を境に row を分類。
  2. 既に ≥skip-threshold (デフォルト 50) row 入っている prefecture
     (大阪/千葉/東京/福岡) は skip 可。CLI flag で制御。
  3. 国 PDF に無い prefecture (島根) は per-prefecture PDF を fallback fetch。
  4. 公表日 (R7.6.3 / 令和8年3月15日 等) を ISO yyyy-mm-dd に変換。
  5. (target_name, issuance_date, issuing_authority) 三つ組で dedup
     (DB 既存 + batch 内)。
  6. am_entities に enforcement stub を upsert
     (canonical_id='enforcement:mhlw-{pref}-{YYYYMMDD}-{hash8}'),
     am_enforcement_detail に kind='business_improvement' で insert。

Parallel-safe:
  - BEGIN IMMEDIATE + PRAGMA busy_timeout=300000 (per CLAUDE.md §5)。
  - prefecture 単位の小コミットで他 worker との衝突を最小化。

Constraints:
  - NO Anthropic API. httpx + BeautifulSoup + pdfplumber。
  - 1 req/sec/host (HttpClient 標準)、UA "AutonoMath/0.1.0 (+https://bookyou.net)"。
  - 404/403/オフライン → 該当 prefecture skip + log only。

CLI:
    python scripts/ingest/ingest_enforcement_mhlw_roudoukyoku.py \
        [--db autonomath.db] [--limit-prefs N] [--dry-run] \
        [--no-national] [--no-fallback]
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import logging
import re
import sqlite3
import sys
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

try:
    import pdfplumber  # type: ignore
except ImportError as exc:  # pragma: no cover
    print(f"ERROR: pdfplumber not installed: {exc}", file=sys.stderr)
    raise

try:
    from bs4 import BeautifulSoup  # type: ignore
except ImportError as exc:  # pragma: no cover
    print(f"ERROR: beautifulsoup4 not installed: {exc}", file=sys.stderr)
    raise

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from scripts.lib.http import HttpClient  # noqa: E402

_LOG = logging.getLogger("autonomath.ingest.mhlw_roudoukyoku")

DEFAULT_DB = REPO_ROOT / "autonomath.db"
USER_AGENT = "AutonoMath/0.1.0 (+https://bookyou.net)"

NATIONAL_PDF_URL = "https://www.mhlw.go.jp/content/001684100.pdf"

# Prefecture jp-label → slug mapping (for canonical_id construction)
LABEL_TO_SLUG: dict[str, str] = {
    "北海道労働局": "hokkaido", "青森労働局": "aomori", "岩手労働局": "iwate",
    "宮城労働局": "miyagi", "秋田労働局": "akita", "山形労働局": "yamagata",
    "福島労働局": "fukushima", "茨城労働局": "ibaraki", "栃木労働局": "tochigi",
    "群馬労働局": "gunma", "埼玉労働局": "saitama", "千葉労働局": "chiba",
    "東京労働局": "tokyo", "神奈川労働局": "kanagawa", "新潟労働局": "niigata",
    "富山労働局": "toyama", "石川労働局": "ishikawa", "福井労働局": "fukui",
    "山梨労働局": "yamanashi", "長野労働局": "nagano", "岐阜労働局": "gifu",
    "静岡労働局": "shizuoka", "愛知労働局": "aichi", "三重労働局": "mie",
    "滋賀労働局": "shiga", "京都労働局": "kyoto", "大阪労働局": "osaka",
    "兵庫労働局": "hyogo", "奈良労働局": "nara", "和歌山労働局": "wakayama",
    "鳥取労働局": "tottori", "島根労働局": "shimane", "岡山労働局": "okayama",
    "広島労働局": "hiroshima", "山口労働局": "yamaguchi", "徳島労働局": "tokushima",
    "香川労働局": "kagawa", "愛媛労働局": "ehime", "高知労働局": "kochi",
    "福岡労働局": "fukuoka", "佐賀労働局": "saga", "長崎労働局": "nagasaki",
    "熊本労働局": "kumamoto", "大分労働局": "oita", "宮崎労働局": "miyazaki",
    "鹿児島労働局": "kagoshima", "沖縄労働局": "okinawa",
}

# ---------------------------------------------------------------------------
# 47 都道府県 → 公表事案ページ URL (recon 済, 2026-04-25 fetch)
#   "kind"="pdf" → 直接 PDF URL
#   "kind"="html" → 公表ページ HTML (中の PDF link を辿る)
# ---------------------------------------------------------------------------

PREFECTURES: list[dict[str, str]] = [
    # 既存 ≥50 row → 'skip' フラグ
    # (Hokkaido は 0 row なので新規収集対象)
    {"slug": "hokkaido", "label": "北海道労働局",
     "url": "https://jsite.mhlw.go.jp/hokkaido-roudoukyoku/jirei_toukei/Announcement.html",
     "kind": "html"},
    {"slug": "aomori", "label": "青森労働局",
     "url": "https://jsite.mhlw.go.jp/aomori-roudoukyoku/newpage_00205.html",
     "kind": "html"},
    {"slug": "iwate", "label": "岩手労働局",
     "url": "https://jsite.mhlw.go.jp/iwate-roudoukyoku/roudoukyoku/gyoumu_naiyou/kijunbu/kantoku/kantokukaosirase_00001.html",
     "kind": "html"},
    {"slug": "akita", "label": "秋田労働局",
     "url": "https://jsite.mhlw.go.jp/akita-roudoukyoku/jirei_toukei/_120559.html",
     "kind": "html"},
    {"slug": "yamagata", "label": "山形労働局",
     "url": "https://jsite.mhlw.go.jp/yamagata-roudoukyoku/content/contents/002615121.pdf",
     "kind": "pdf"},
    {"slug": "fukushima", "label": "福島労働局",
     "url": "https://jsite.mhlw.go.jp/fukushima-roudoukyoku/jirei_toukei/souken_jirei.html",
     "kind": "html"},
    {"slug": "tochigi", "label": "栃木労働局",
     "url": "https://jsite.mhlw.go.jp/tochigi-roudoukyoku/content/contents/002623424.pdf",
     "kind": "pdf"},
    {"slug": "gunma", "label": "群馬労働局",
     "url": "https://jsite.mhlw.go.jp/gunma-roudoukyoku/jirei_toukei/20170508-1.html",
     "kind": "html"},
    {"slug": "kanagawa", "label": "神奈川労働局",
     "url": "https://jsite.mhlw.go.jp/kanagawa-roudoukyoku/content/contents/000841861.pdf",
     "kind": "pdf"},
    {"slug": "niigata", "label": "新潟労働局",
     "url": "https://jsite.mhlw.go.jp/niigata-roudoukyoku/jirei_toukei.html",
     "kind": "html"},
    {"slug": "toyama", "label": "富山労働局",
     "url": "https://jsite.mhlw.go.jp/toyama-roudoukyoku/jirei_toukei/souken_jirei.html",
     "kind": "html"},
    {"slug": "ishikawa", "label": "石川労働局",
     "url": "https://jsite.mhlw.go.jp/ishikawa-roudoukyoku/jirei_toukei/souken_jirei.html",
     "kind": "html"},
    {"slug": "fukui", "label": "福井労働局",
     "url": "https://jsite.mhlw.go.jp/fukui-roudoukyoku/jirei_toukei/_120789.html",
     "kind": "html"},
    {"slug": "yamanashi", "label": "山梨労働局",
     "url": "https://jsite.mhlw.go.jp/yamanashi-roudoukyoku/jirei_toukei/souken_jirei.html",
     "kind": "html"},
    {"slug": "nagano", "label": "長野労働局",
     "url": "https://jsite.mhlw.go.jp/nagano-roudoukyoku/jirei_toukei/roudoukijun-houreiihan_kouhyoujian.html",
     "kind": "html"},
    {"slug": "shizuoka", "label": "静岡労働局",
     "url": "https://jsite.mhlw.go.jp/shizuoka-roudoukyoku/jirei_toukei/20120703.html",
     "kind": "html"},
    {"slug": "aichi", "label": "愛知労働局",
     "url": "https://jsite.mhlw.go.jp/aichi-roudoukyoku/jirei_toukei.html",
     "kind": "html"},
    {"slug": "mie", "label": "三重労働局",
     "url": "https://jsite.mhlw.go.jp/mie-roudoukyoku/jirei_toukei/mie_kouhyou.html",
     "kind": "html"},
    {"slug": "shiga", "label": "滋賀労働局",
     "url": "https://jsite.mhlw.go.jp/shiga-roudoukyoku/jirei_toukei/souken_jirei.html",
     "kind": "html"},
    {"slug": "kyoto", "label": "京都労働局",
     "url": "https://jsite.mhlw.go.jp/kyoto-roudoukyoku/jirei_toukei/souken_jirei.html",
     "kind": "html"},
    {"slug": "hyogo", "label": "兵庫労働局",
     "url": "https://jsite.mhlw.go.jp/hyogo-roudoukyoku/jirei_toukei/_122042.html",
     "kind": "html"},
    {"slug": "nara", "label": "奈良労働局",
     "url": "https://jsite.mhlw.go.jp/nara-roudoukyoku/jirei_toukei.html",
     "kind": "html"},
    {"slug": "wakayama", "label": "和歌山労働局",
     "url": "https://jsite.mhlw.go.jp/wakayama-roudoukyoku/jirei_toukei/souken_jirei.html",
     "kind": "html"},
    {"slug": "tottori", "label": "鳥取労働局",
     "url": "https://jsite.mhlw.go.jp/tottori-roudoukyoku/jirei_toukei.html",
     "kind": "html"},
    {"slug": "shimane", "label": "島根労働局",
     "url": "https://jsite.mhlw.go.jp/shimane-roudoukyoku/jirei_toukei.html",
     "kind": "html"},
    {"slug": "okayama", "label": "岡山労働局",
     "url": "https://jsite.mhlw.go.jp/okayama-roudoukyoku/content/contents/002411234.pdf",
     "kind": "pdf"},
    {"slug": "hiroshima", "label": "広島労働局",
     "url": "https://jsite.mhlw.go.jp/hiroshima-roudoukyoku/jirei_toukei/newpage_00001.html",
     "kind": "html"},
    {"slug": "yamaguchi", "label": "山口労働局",
     "url": "https://jsite.mhlw.go.jp/yamaguchi-roudoukyoku/jirei_toukei/_121193.html",
     "kind": "html"},
    {"slug": "tokushima", "label": "徳島労働局",
     "url": "https://jsite.mhlw.go.jp/tokushima-roudoukyoku/jirei_toukei/souken_jirei.html",
     "kind": "html"},
    {"slug": "kagawa", "label": "香川労働局",
     "url": "https://jsite.mhlw.go.jp/kagawa-roudoukyoku/jirei_toukei_00007.html",
     "kind": "html"},
    {"slug": "ehime", "label": "愛媛労働局",
     "url": "https://jsite.mhlw.go.jp/ehime-roudoukyoku/jirei_toukei/290510_001.html",
     "kind": "html"},
    {"slug": "kochi", "label": "高知労働局",
     "url": "https://jsite.mhlw.go.jp/kochi-roudoukyoku/newpage_00211.html",
     "kind": "html"},
    {"slug": "saga", "label": "佐賀労働局",
     "url": "https://jsite.mhlw.go.jp/saga-roudoukyoku/newpage_00138.html",
     "kind": "html"},
    {"slug": "nagasaki", "label": "長崎労働局",
     "url": "https://jsite.mhlw.go.jp/nagasaki-roudoukyoku/jirei_toukei/souken_jirei.html",
     "kind": "html"},
    {"slug": "kumamoto", "label": "熊本労働局",
     "url": "https://jsite.mhlw.go.jp/kumamoto-roudoukyoku/jirei_toukei/_120857.html",
     "kind": "html"},
    {"slug": "oita", "label": "大分労働局",
     "url": "https://jsite.mhlw.go.jp/oita-roudoukyoku/jirei_toukei/kouhyoujian.html",
     "kind": "html"},
    {"slug": "miyazaki", "label": "宮崎労働局",
     "url": "https://jsite.mhlw.go.jp/miyazaki-roudoukyoku/jirei_toukei/souken_jirei.html",
     "kind": "html"},
    {"slug": "kagoshima", "label": "鹿児島労働局",
     "url": "https://jsite.mhlw.go.jp/kagoshima-roudoukyoku/jirei_toukei.html",
     "kind": "html"},
    {"slug": "miyagi", "label": "宮城労働局",
     "url": "https://jsite.mhlw.go.jp/miyagi-roudoukyoku/jirei_toukei.html",
     "kind": "html"},
    {"slug": "gifu", "label": "岐阜労働局",
     "url": "https://jsite.mhlw.go.jp/gifu-roudoukyoku/riyousha_mokuteki_menu/mokuteki_naiyou/jirei_toukei.html",
     "kind": "html"},
    {"slug": "ibaraki", "label": "茨城労働局",
     "url": "https://jsite.mhlw.go.jp/ibaraki-roudoukyoku/content/contents/002618154.pdf",
     "kind": "pdf"},
    {"slug": "saitama", "label": "埼玉労働局",
     "url": "https://jsite.mhlw.go.jp/saitama-roudoukyoku/content/contents/002597705.pdf",
     "kind": "pdf"},
    {"slug": "shimane", "label": "島根労働局",
     "url": "https://jsite.mhlw.go.jp/shimane-roudoukyoku/content/contents/002615222.pdf",
     "kind": "pdf"},
    # 既に subsidy_exclude row 多数あり (大阪 207 / 千葉 100 / 東京 88 / 福岡 78
    # / 茨城 1 / 沖縄 1 / 埼玉 1)。
    # 国 PDF の方が違反公表事案 (送検) を扱うので衝突しないが、authority が
    # 同じ '厚生労働省 大阪労働局' になるため skip-threshold (default 50) で
    # 大阪/千葉/東京/福岡 をスキップする。茨城/沖縄/埼玉 は ≪50 row なので
    # 普通に取り込まれる。
]

ISSUING_AUTHORITY_FMT = "厚生労働省 {label}"

# ---------------------------------------------------------------------------
# Date parsing
# ---------------------------------------------------------------------------

WAREKI_RE = re.compile(r"(令和|平成|R|H)\s*(\d+|元)\s*[年.\-．／]\s*(\d{1,2})\s*[月.\-．／]\s*(\d{1,2})\s*日?")
SEIREKI_RE = re.compile(r"(20\d{2}|19\d{2})\s*[年.\-／/]\s*(\d{1,2})\s*[月.\-／/]\s*(\d{1,2})")
ERA_OFFSET = {"令和": 2018, "R": 2018, "平成": 1988, "H": 1988}


def _normalize(s: str) -> str:
    if not s:
        return ""
    return unicodedata.normalize("NFKC", s).strip()


def _parse_date(text: str) -> str | None:
    """R7.6.3 / 令和7年6月3日 / 2025/6/3 / R7.6.3送検 などを ISO yyyy-mm-dd に。"""
    if not text:
        return None
    s = _normalize(text)
    # Wareki (R7.6.3 or 令和7年6月3日)
    m = WAREKI_RE.search(s)
    if m:
        era, y_raw, mo, d = m.group(1), m.group(2), int(m.group(3)), int(m.group(4))
        try:
            y_off = 1 if y_raw == "元" else int(y_raw)
        except ValueError:
            return None
        year = ERA_OFFSET[era] + y_off
        if not (1990 <= year <= 2100 and 1 <= mo <= 12 and 1 <= d <= 31):
            return None
        return f"{year:04d}-{mo:02d}-{d:02d}"
    m = SEIREKI_RE.search(s)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if not (1990 <= y <= 2100 and 1 <= mo <= 12 and 1 <= d <= 31):
            return None
        return f"{y:04d}-{mo:02d}-{d:02d}"
    return None


# ---------------------------------------------------------------------------
# Row dataclass + parser
# ---------------------------------------------------------------------------


@dataclass
class EnfRow:
    target_name: str
    location: str | None
    issuance_date: str
    related_law_ref: str | None
    reason_summary: str | None
    extras: str | None  # 送検日 etc.


def _clean_cell(c: str | None) -> str:
    if c is None:
        return ""
    return _normalize(c.replace("\n", " "))


_LABEL_RE = re.compile(r"(\S+労働局)")


def parse_pdf_rows(
    pdf_bytes: bytes,
    *,
    fixed_label: str | None = None,
) -> list[tuple[str, EnfRow]]:
    """Extract (prefecture_label, EnfRow) tuples from a 公表事案 PDF.

    For per-prefecture PDFs, fixed_label is forced; for the national PDF,
    fixed_label=None and we track section headers ('北海道労働局' alone
    in row 0) to assign each data row to a prefecture.
    """
    rows: list[tuple[str, EnfRow]] = []
    current_label = fixed_label
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages:
                try:
                    tables = page.extract_tables() or []
                except Exception as exc:  # noqa: BLE001
                    _LOG.debug("page extract_tables err: %s", exc)
                    continue
                for tbl in tables:
                    for raw in tbl:
                        if not raw or len(raw) < 5:
                            continue
                        # Drop header / title rows.
                        first = _clean_cell(raw[0])
                        if not first:
                            continue
                        rest_empty = all(not _clean_cell(c) for c in raw[1:])
                        # Title-only or pref-only row → may be a section header.
                        if rest_empty:
                            m = _LABEL_RE.search(first)
                            if m:
                                cand = m.group(1)
                                if cand in LABEL_TO_SLUG:
                                    current_label = cand
                            continue
                        if "企業" in first and "事業" in first:
                            continue
                        if "労働基準関係法令違反" in first and rest_empty:
                            continue
                        # Heuristic: column 2 should be 公表日 (R7.x.x or 令和)
                        # Layout varies — find the date column.
                        # Standard 6-col layout:
                        #   0=name 1=loc 2=公表日 3=law 4=summary 5=extras
                        cols = [_clean_cell(c) for c in raw]
                        # Pad to 6 columns
                        cols += [""] * (6 - len(cols))
                        name = cols[0]
                        if not name or len(name) > 200:
                            continue
                        # Date column (usually 2nd or 3rd)
                        date_iso: str | None = None
                        date_col_idx = -1
                        for i in (2, 3, 1):
                            if i >= len(cols):
                                continue
                            if cols[i]:
                                d = _parse_date(cols[i])
                                if d:
                                    date_iso = d
                                    date_col_idx = i
                                    break
                        if not date_iso:
                            # Fallback: scan all columns for a date.
                            for i, c in enumerate(cols):
                                d = _parse_date(c)
                                if d:
                                    date_iso = d
                                    date_col_idx = i
                                    break
                        if not date_iso:
                            continue
                        # Decode remaining columns by relative offset
                        location = cols[1] if date_col_idx >= 2 else None
                        law_idx = date_col_idx + 1
                        sum_idx = date_col_idx + 2
                        ext_idx = date_col_idx + 3
                        law_ref = cols[law_idx] if law_idx < len(cols) else None
                        summary = cols[sum_idx] if sum_idx < len(cols) else None
                        extras = cols[ext_idx] if ext_idx < len(cols) else None
                        if not current_label:
                            # Try to infer from name cell as last resort.
                            continue
                        rows.append((current_label, EnfRow(
                            target_name=name,
                            location=location or None,
                            issuance_date=date_iso,
                            related_law_ref=law_ref or None,
                            reason_summary=summary or None,
                            extras=extras or None,
                        )))
    except Exception as exc:  # noqa: BLE001
        _LOG.warning("PDF parse failed: %s", exc)
    return rows


def parse_html_table_rows(html: str, fixed_label: str) -> list[tuple[str, EnfRow]]:
    """Extract rows from an HTML disclosure page that has an inline table."""
    rows: list[tuple[str, EnfRow]] = []
    soup = BeautifulSoup(html, "html.parser")
    for table in soup.find_all("table"):
        for tr in table.find_all("tr"):
            cells = [_normalize(td.get_text(" ", strip=True)) for td in tr.find_all(["td", "th"])]
            if len(cells) < 4:
                continue
            first = cells[0]
            if not first or "企業" in first and "事業" in first:
                continue
            if "労働基準関係法令違反" in first:
                continue
            # Guess columns
            date_iso = None
            date_col_idx = -1
            for i in range(min(len(cells), 4)):
                d = _parse_date(cells[i])
                if d:
                    date_iso = d
                    date_col_idx = i
                    break
            if not date_iso:
                continue
            name = cells[0]
            if not name or len(name) > 200:
                continue
            location = cells[1] if date_col_idx >= 2 else None
            law_idx = date_col_idx + 1
            sum_idx = date_col_idx + 2
            ext_idx = date_col_idx + 3
            law_ref = cells[law_idx] if law_idx < len(cells) else None
            summary = cells[sum_idx] if sum_idx < len(cells) else None
            extras = cells[ext_idx] if ext_idx < len(cells) else None
            rows.append((fixed_label, EnfRow(
                target_name=name,
                location=location or None,
                issuance_date=date_iso,
                related_law_ref=law_ref or None,
                reason_summary=summary or None,
                extras=extras or None,
            )))
    return rows


def find_pdf_links(html: str, page_url: str) -> list[str]:
    """Pull candidate PDF links from a 公表ページ HTML.

    Heuristic: any <a href="*.pdf"> whose anchor or surrounding text contains
    "労働基準" / "公表事案" / "送検" / "違反".
    """
    soup = BeautifulSoup(html, "html.parser")
    seen: set[str] = set()
    out: list[str] = []
    for a in soup.find_all("a"):
        href = (a.get("href") or "").strip()
        if not href.lower().endswith(".pdf"):
            continue
        # Build absolute URL.
        if href.startswith("//"):
            absurl = "https:" + href
        elif href.startswith("/"):
            absurl = "https://jsite.mhlw.go.jp" + href
        elif href.startswith("http"):
            absurl = href
        else:
            # Relative.
            base = page_url.rsplit("/", 1)[0] + "/"
            absurl = base + href
        text = a.get_text(" ", strip=True)
        # Pull the parent <li>/<p> text for context.
        parent = a.parent
        ctx = parent.get_text(" ", strip=True) if parent else ""
        haystack = f"{text} {ctx}"
        if any(k in haystack for k in ("労働基準", "公表事案", "送検", "違反")):
            if absurl not in seen:
                seen.add(absurl)
                out.append(absurl)
    return out


# ---------------------------------------------------------------------------
# DB layer
# ---------------------------------------------------------------------------


def _slug8(name: str, date: str) -> str:
    h = hashlib.sha1(f"{name}|{date}".encode("utf-8")).hexdigest()
    return h[:8]


def ensure_tables(conn: sqlite3.Connection) -> None:
    for tbl in ("am_entities", "am_enforcement_detail"):
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (tbl,),
        ).fetchone()
        if not row:
            raise SystemExit(f"missing table '{tbl}' — apply migrations first")


def existing_authorities_with_count(conn: sqlite3.Connection) -> dict[str, int]:
    """Return {authority_label: count} for existing 厚労省 rows."""
    out: dict[str, int] = {}
    for label, n in conn.execute(
        "SELECT issuing_authority, COUNT(*) FROM am_enforcement_detail "
        "WHERE issuing_authority LIKE '厚生労働省%' GROUP BY issuing_authority"
    ).fetchall():
        out[label] = n
    return out


def existing_dedup_keys(conn: sqlite3.Connection, authority: str) -> set[tuple[str, str]]:
    """Return {(target_name, issuance_date)} already in DB for this authority."""
    out: set[tuple[str, str]] = set()
    for n, d in conn.execute(
        "SELECT target_name, issuance_date FROM am_enforcement_detail "
        "WHERE issuing_authority=?",
        (authority,),
    ).fetchall():
        if n and d:
            out.add((n, d))
    return out


def upsert_entity(
    conn: sqlite3.Connection,
    canonical_id: str,
    primary_name: str,
    url: str,
    raw_json: str,
    now_iso: str,
) -> None:
    domain = urlparse(url).netloc or None
    conn.execute(
        """
        INSERT INTO am_entities (
            canonical_id, record_kind, source_topic, source_record_index,
            primary_name, authority_canonical, confidence,
            source_url, source_url_domain, fetched_at, raw_json,
            canonical_status, citation_status
        ) VALUES (?, 'enforcement', 'mhlw_roudoukyoku_kouhyou', NULL,
                  ?, NULL, 0.9, ?, ?, ?, ?, 'active', 'ok')
        ON CONFLICT(canonical_id) DO UPDATE SET
            primary_name      = excluded.primary_name,
            source_url        = excluded.source_url,
            source_url_domain = excluded.source_url_domain,
            fetched_at        = excluded.fetched_at,
            raw_json          = excluded.raw_json,
            updated_at        = datetime('now')
        """,
        (
            canonical_id,
            primary_name[:500],
            url,
            domain,
            now_iso,
            raw_json,
        ),
    )


def insert_enforcement(
    conn: sqlite3.Connection,
    entity_id: str,
    target_name: str,
    issuance_date: str,
    issuing_authority: str,
    reason_summary: str | None,
    related_law_ref: str | None,
    source_url: str,
    source_fetched_at: str,
) -> None:
    conn.execute(
        """
        INSERT INTO am_enforcement_detail (
            entity_id, houjin_bangou, target_name, enforcement_kind,
            issuing_authority, issuance_date, exclusion_start, exclusion_end,
            reason_summary, related_law_ref, amount_yen,
            source_url, source_fetched_at
        ) VALUES (?, NULL, ?, 'business_improvement', ?, ?, NULL, NULL, ?, ?, NULL, ?, ?)
        """,
        (
            entity_id,
            target_name[:500],
            issuing_authority,
            issuance_date,
            (reason_summary or "")[:4000] or None,
            (related_law_ref or "")[:1000] or None,
            source_url,
            source_fetched_at,
        ),
    )


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--limit-prefs", type=int, default=None,
                    help="cap number of prefectures walked (debugging)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--verbose", "-v", action="store_true")
    ap.add_argument("--skip-threshold", type=int, default=50,
                    help="skip prefecture already with this many rows (default 50)")
    ap.add_argument("--no-national", action="store_true",
                    help="skip national PDF, use per-prefecture URLs only")
    ap.add_argument("--no-fallback", action="store_true",
                    help="use national PDF only (skip per-prefecture fallback)")
    return ap.parse_args(argv)


def fetch_and_parse_prefecture(
    http: HttpClient, pref: dict[str, str],
) -> tuple[list[tuple[str, EnfRow]], str | None]:
    """Return (rows, effective_pdf_or_html_url). May skip silently on 404."""
    url = pref["url"]
    kind = pref["kind"]
    label = pref["label"]
    res = http.get(url, max_bytes=10 * 1024 * 1024)
    if not res.ok:
        _LOG.warning("[%s] fetch failed status=%s url=%s", pref["slug"], res.status, url)
        return [], None

    if kind == "pdf":
        rows = parse_pdf_rows(res.body, fixed_label=label)
        return rows, url

    # kind == "html"
    html = res.text
    # Try inline table first.
    rows = parse_html_table_rows(html, label)
    if rows:
        return rows, url
    # Else look for a PDF link on the page.
    pdf_urls = find_pdf_links(html, url)
    for pu in pdf_urls:
        pres = http.get(pu, max_bytes=10 * 1024 * 1024)
        if not pres.ok:
            _LOG.debug("[%s] PDF candidate fetch fail %s", pref["slug"], pu)
            continue
        sub_rows = parse_pdf_rows(pres.body, fixed_label=label)
        if sub_rows:
            return sub_rows, pu
    return [], url


def fetch_and_parse_national(http: HttpClient) -> tuple[dict[str, list[EnfRow]], str]:
    """Fetch the national consolidated PDF and return {pref_label: [EnfRow,...]}."""
    res = http.get(NATIONAL_PDF_URL, max_bytes=20 * 1024 * 1024)
    if not res.ok:
        _LOG.warning("national PDF fetch failed status=%s", res.status)
        return {}, NATIONAL_PDF_URL
    pairs = parse_pdf_rows(res.body, fixed_label=None)
    by_label: dict[str, list[EnfRow]] = {}
    for label, row in pairs:
        by_label.setdefault(label, []).append(row)
    _LOG.info("national PDF parsed: %d prefectures, %d rows total",
              len(by_label), sum(len(v) for v in by_label.values()))
    return by_label, NATIONAL_PDF_URL


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    http = HttpClient(user_agent=USER_AGENT)
    now_iso = datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")

    conn: sqlite3.Connection | None = None
    if not args.dry_run:
        if not args.db.exists():
            _LOG.error("autonomath.db missing: %s", args.db)
            return 2
        conn = sqlite3.connect(str(args.db))
        conn.execute("PRAGMA busy_timeout=300000")
        conn.execute("PRAGMA foreign_keys=ON")
        ensure_tables(conn)

    auth_counts = existing_authorities_with_count(conn) if conn else {}
    skip_threshold = args.skip_threshold

    stats = {
        "prefs_walked": 0,
        "prefs_skipped_existing": 0,
        "prefs_no_data": 0,
        "rows_parsed": 0,
        "rows_inserted": 0,
        "rows_dup_in_db": 0,
        "rows_dup_in_batch": 0,
    }
    covered: list[str] = []

    # Phase 1: parse the national PDF (primary source)
    national_by_label: dict[str, list[EnfRow]] = {}
    national_url = NATIONAL_PDF_URL
    if not args.no_national:
        national_by_label, national_url = fetch_and_parse_national(http)

    # Build the master per-prefecture row map
    # {label: [(EnfRow, source_url)]}
    pref_rows: dict[str, list[tuple[EnfRow, str]]] = {}
    for label, rows in national_by_label.items():
        pref_rows[label] = [(r, national_url) for r in rows]

    # Phase 2: per-prefecture fallback for any missing or extra detail.
    if not args.no_fallback:
        labels_have_data = set(pref_rows.keys())
        prefs_to_walk = PREFECTURES
        if args.limit_prefs:
            prefs_to_walk = prefs_to_walk[: args.limit_prefs]
        for pref in prefs_to_walk:
            label = pref["label"]
            # If national already gave ≥3 rows, skip the per-prefecture fetch
            # to save bandwidth (national is canonical & dedup later).
            if label in labels_have_data and len(pref_rows[label]) >= 3:
                continue
            authority = ISSUING_AUTHORITY_FMT.format(label=label)
            existing_n = auth_counts.get(authority, 0)
            if existing_n >= skip_threshold:
                continue
            sub_rows, eff_url = fetch_and_parse_prefecture(http, pref)
            if not sub_rows or not eff_url:
                continue
            for _ll, r in sub_rows:
                pref_rows.setdefault(label, []).append((r, eff_url))

    # Phase 3: write to DB per prefecture (small commits)
    for label, items in pref_rows.items():
        slug = LABEL_TO_SLUG.get(label)
        if not slug:
            _LOG.warning("unknown prefecture label: %s — skip", label)
            continue
        authority = ISSUING_AUTHORITY_FMT.format(label=label)

        existing_n = auth_counts.get(authority, 0)
        if existing_n >= skip_threshold:
            _LOG.info("[%s] skip — existing rows=%d (>= threshold %d)",
                      slug, existing_n, skip_threshold)
            stats["prefs_skipped_existing"] += 1
            continue

        stats["prefs_walked"] += 1
        stats["rows_parsed"] += len(items)
        _LOG.info("[%s] candidate rows=%d", slug, len(items))

        if conn is None:
            covered.append(f"{slug}:{len(items)}")
            continue

        # Dedup against DB + within batch
        db_keys = existing_dedup_keys(conn, authority)
        batch_keys: set[tuple[str, str]] = set()
        inserted = 0
        dup_db = 0
        dup_batch = 0

        try:
            conn.execute("BEGIN IMMEDIATE")
            for r, src_url in items:
                key = (r.target_name, r.issuance_date)
                if key in db_keys:
                    dup_db += 1
                    continue
                if key in batch_keys:
                    dup_batch += 1
                    continue
                batch_keys.add(key)

                canonical_id = (
                    f"enforcement:mhlw-{slug}-"
                    f"{r.issuance_date.replace('-', '')}-"
                    f"{_slug8(r.target_name, r.issuance_date)}"
                )
                primary_name = (
                    f"{r.target_name} ({r.issuance_date}) - {label} 公表事案"
                )
                raw_json = json.dumps(
                    {
                        "prefecture": label,
                        "slug": slug,
                        "target_name": r.target_name,
                        "location": r.location,
                        "issuance_date": r.issuance_date,
                        "related_law_ref": r.related_law_ref,
                        "reason_summary": r.reason_summary,
                        "extras": r.extras,
                        "issuing_authority": authority,
                        "source_url": src_url,
                        "source_attribution": "厚生労働省ウェブサイト",
                        "license": "政府機関の著作物（出典明記で転載引用可）",
                    },
                    ensure_ascii=False,
                )
                try:
                    upsert_entity(conn, canonical_id, primary_name,
                                  src_url, raw_json, now_iso)
                    insert_enforcement(
                        conn=conn,
                        entity_id=canonical_id,
                        target_name=r.target_name,
                        issuance_date=r.issuance_date,
                        issuing_authority=authority,
                        reason_summary=r.reason_summary,
                        related_law_ref=r.related_law_ref,
                        source_url=src_url,
                        source_fetched_at=now_iso,
                    )
                    inserted += 1
                except sqlite3.Error as exc:
                    _LOG.error("[%s] DB error name=%r date=%s: %s",
                               slug, r.target_name, r.issuance_date, exc)
                    continue
            conn.commit()
        except sqlite3.Error as exc:
            _LOG.error("[%s] BEGIN/commit failed: %s", slug, exc)
            try:
                conn.rollback()
            except sqlite3.Error:
                pass
            continue

        stats["rows_inserted"] += inserted
        stats["rows_dup_in_db"] += dup_db
        stats["rows_dup_in_batch"] += dup_batch
        if inserted:
            covered.append(f"{slug}:{inserted}")
        _LOG.info("[%s] inserted=%d (cand=%d, dup_db=%d, dup_batch=%d)",
                  slug, inserted, len(items), dup_db, dup_batch)

    http.close()
    if conn is not None:
        try:
            conn.close()
        except sqlite3.Error:
            pass

    _LOG.info(
        "done walked=%d skip_existing=%d no_data=%d parsed=%d inserted=%d "
        "dup_db=%d dup_batch=%d covered=%s",
        stats["prefs_walked"],
        stats["prefs_skipped_existing"],
        stats["prefs_no_data"],
        stats["rows_parsed"],
        stats["rows_inserted"],
        stats["rows_dup_in_db"],
        stats["rows_dup_in_batch"],
        ",".join(covered),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
