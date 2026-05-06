#!/usr/bin/env python3
"""Ingest 介護保険法・障害者総合支援法 指定取消・効力停止 公表 records.

Sources (primary, all 都道府県/政令市 1次資料):

  PRIMARY HIGH-YIELD PDFS (multi-row tables):
    1. 大阪府 障害福祉 取消し事業者一覧 (4 PDFs ~150 rows total)
       - https://www.pref.osaka.lg.jp/documents/63674/c-03.pdf
       - https://www.pref.osaka.lg.jp/documents/4970/b-05torikesizigyousya.pdf
       - https://www.pref.osaka.lg.jp/documents/4861/a620torikeshiichiran.pdf
       - https://www.pref.osaka.lg.jp/documents/4941/c2-siteitorikesiitiran.pdf
       - https://www.pref.osaka.lg.jp/documents/5106/c-03.pdf
    2. 枚方市 取消し事業者一覧 (PDF, ~32 rows)
       - https://www.city.hirakata.osaka.jp/cmsfiles/contents/0000049/49163/syaC-4.pdf
    3. 東京都福祉局 廃止・取消事業所一覧 cumulative (PDF, 6 rows)
       - https://www.fukushi.metro.tokyo.lg.jp/documents/d/fukushi/241225_torikesi_itiran-pdf

  HTML PAGES (single-row press releases, walked individually):
    - 福島県 障害 (3 PDFs)
    - 沖縄県 障害 (8 PDFs)
    - 東大阪市 介護 (~14 PDFs)
    - 東京都 個別 press release (~5 PDFs)

Schema target: am_enforcement_detail
  - enforcement_kind: license_revoke | business_improvement | other
  - issuing_authority: '大阪府', '東京都', '枚方市', '東大阪市', etc.
  - related_law_ref: '介護保険法 第77条' / '障害者総合支援法 第50条' etc.

Idempotent dedup key: (issuing_authority, issuance_date, target_name).

Parallel-safe (BEGIN IMMEDIATE + busy_timeout=300000).

CLI:
    python scripts/ingest/ingest_enforcement_kaigo_shogai.py [--db autonomath.db]
        [--limit N] [--dry-run] [--verbose]
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

_LOG = logging.getLogger("autonomath.ingest.kaigo_shogai")

DEFAULT_DB = REPO_ROOT / "autonomath.db"
USER_AGENT = "AutonoMath/0.1.0 (+https://bookyou.net)"


# ---------------------------------------------------------------------------
# Source list — multi-row PDFs (highest yield)
# ---------------------------------------------------------------------------

# Each entry: dict with keys
#   slug: short id used for canonical_id
#   authority: 都道府県 or 政令市 name (issuing_authority)
#   url: PDF/HTML URL
#   format: 'osaka_pref_pdf' | 'tokyo_cumulative_pdf' | 'tokyo_press_pdf' |
#           'fukushima_pdf' | 'html_press' | 'okinawa_pdf' | 'higashiosaka_pdf'
#   default_law: optional default 関連法 if not parsed from text

MULTIROW_SOURCES: list[dict[str, str]] = [
    # 大阪府 障害福祉 取消し事業者一覧 — 4 cumulative PDFs (mostly 障害)
    {
        "slug": "osaka-pref-c03-2021",
        "authority": "大阪府",
        "url": "https://www.pref.osaka.lg.jp/documents/63674/c-03.pdf",
        "format": "osaka_pref_pdf",
        "default_law": "障害者総合支援法",
    },
    {
        "slug": "osaka-pref-b05-h28",
        "authority": "大阪府",
        "url": "https://www.pref.osaka.lg.jp/documents/4970/b-05torikesizigyousya.pdf",
        "format": "osaka_pref_pdf",
        "default_law": "障害者総合支援法",
    },
    {
        "slug": "osaka-pref-a620",
        "authority": "大阪府",
        "url": "https://www.pref.osaka.lg.jp/documents/4861/a620torikeshiichiran.pdf",
        "format": "osaka_pref_pdf",
        "default_law": "障害者総合支援法",
    },
    {
        "slug": "osaka-pref-c2",
        "authority": "大阪府",
        "url": "https://www.pref.osaka.lg.jp/documents/4941/c2-siteitorikesiitiran.pdf",
        "format": "osaka_pref_pdf",
        "default_law": "障害者総合支援法",
    },
    {
        "slug": "osaka-pref-c03-5106",
        "authority": "大阪府",
        "url": "https://www.pref.osaka.lg.jp/documents/5106/c-03.pdf",
        "format": "osaka_pref_pdf",
        "default_law": "障害者総合支援法",
    },
    # 枚方市 取消し事業者一覧
    {
        "slug": "hirakata-syaC4",
        "authority": "枚方市",
        "url": "https://www.city.hirakata.osaka.jp/cmsfiles/contents/0000049/49163/syaC-4.pdf",
        "format": "osaka_pref_pdf",  # same format
        "default_law": "障害者総合支援法",
    },
    # 東京都福祉局 廃止・取消事業所一覧 cumulative
    {
        "slug": "tokyo-cumul-241225",
        "authority": "東京都",
        "url": "https://www.fukushi.metro.tokyo.lg.jp/documents/d/fukushi/241225_torikesi_itiran-pdf",
        "format": "tokyo_cumulative_pdf",
        "default_law": "介護保険法",
    },
]

# 個別 press release / single-event PDFs (1 row each, but additive)
SINGLE_EVENT_PDFS: list[dict[str, str]] = [
    # 東京都 press releases
    {
        "slug": "tokyo-press-r3-5",
        "authority": "東京都",
        "url": "https://www.fukushi.metro.tokyo.lg.jp/documents/d/fukushi/torikesiitiranR3_5",
        "format": "tokyo_press_pdf",
        "default_law": "介護保険法",
    },
    {
        "slug": "tokyo-press-r3-10",
        "authority": "東京都",
        "url": "https://www.fukushi.metro.tokyo.lg.jp/documents/d/fukushi/torikesi_press0310",
        "format": "tokyo_press_pdf",
        "default_law": "介護保険法",
    },
    {
        "slug": "tokyo-press-r4-6",
        "authority": "東京都",
        "url": "https://www.fukushi.metro.tokyo.lg.jp/documents/d/fukushi/R040614press",
        "format": "tokyo_press_pdf",
        "default_law": "介護保険法",
    },
    {
        "slug": "tokyo-press-r6-10",
        "authority": "東京都",
        "url": "https://www.fukushi.metro.tokyo.lg.jp/documents/d/fukushi/20241001_press",
        "format": "tokyo_press_pdf",
        "default_law": "介護保険法",
    },
    {
        "slug": "tokyo-press-r6-12",
        "authority": "東京都",
        "url": "https://www.fukushi.metro.tokyo.lg.jp/documents/d/fukushi/241225_press",
        "format": "tokyo_press_pdf",
        "default_law": "介護保険法",
    },
    # 福島県 障害福祉
    {
        "slug": "fukushima-shogai-r7-12",
        "authority": "福島県",
        "url": "https://www.pref.fukushima.lg.jp/uploaded/attachment/719183.pdf",
        "format": "press_pdf",
        "default_law": "障害者総合支援法",
    },
    {
        "slug": "fukushima-shogai-r6-5",
        "authority": "福島県",
        "url": "https://www.pref.fukushima.lg.jp/uploaded/attachment/630361.pdf",
        "format": "press_pdf",
        "default_law": "障害者総合支援法",
    },
    {
        "slug": "fukushima-shogai-r5-3",
        "authority": "福島県",
        "url": "https://www.pref.fukushima.lg.jp/uploaded/attachment/566132.pdf",
        "format": "press_pdf",
        "default_law": "障害者総合支援法",
    },
    # 沖縄県 障害福祉 — 8 PDFs
    {
        "slug": "okinawa-260325",
        "authority": "沖縄県",
        "url": "https://www.pref.okinawa.lg.jp/_res/projects/default_project/_page_/001/007/833/260325syobun.pdf",
        "format": "press_pdf",
        "default_law": "障害者総合支援法",
    },
    {
        "slug": "okinawa-251017",
        "authority": "沖縄県",
        "url": "https://www.pref.okinawa.lg.jp/_res/projects/default_project/_page_/001/007/833/251017press.pdf",
        "format": "press_pdf",
        "default_law": "障害者総合支援法",
    },
    {
        "slug": "okinawa-250421",
        "authority": "沖縄県",
        "url": "https://www.pref.okinawa.lg.jp/_res/projects/default_project/_page_/001/007/833/250421shiteitorikeshi.pdf",
        "format": "press_pdf",
        "default_law": "障害者総合支援法",
    },
    {
        "slug": "okinawa-20250225",
        "authority": "沖縄県",
        "url": "https://www.pref.okinawa.lg.jp/_res/projects/default_project/_page_/001/007/833/20250225_torikeshi.pdf",
        "format": "press_pdf",
        "default_law": "障害者総合支援法",
    },
    {
        "slug": "okinawa-20241111",
        "authority": "沖縄県",
        "url": "https://www.pref.okinawa.lg.jp/_res/projects/default_project/_page_/001/007/833/20241111_torikesi.pdf",
        "format": "press_pdf",
        "default_law": "障害者総合支援法",
    },
    {
        "slug": "okinawa-27060203",
        "authority": "沖縄県",
        "url": "https://www.pref.okinawa.lg.jp/_res/projects/default_project/_page_/001/007/833/27060203cancel.pdf",
        "format": "press_pdf",
        "default_law": "障害者総合支援法",
    },
    {
        "slug": "okinawa-261001",
        "authority": "沖縄県",
        "url": "https://www.pref.okinawa.lg.jp/_res/projects/default_project/_page_/001/007/833/261001cancel.pdf",
        "format": "press_pdf",
        "default_law": "障害者総合支援法",
    },
    {
        "slug": "okinawa-siteitorikesi",
        "authority": "沖縄県",
        "url": "https://www.pref.okinawa.lg.jp/_res/projects/default_project/_page_/001/007/833/siteitorikesi.pdf",
        "format": "press_pdf",
        "default_law": "障害者総合支援法",
    },
    # 東大阪市 個別 取消通知
    {
        "slug": "higashiosaka-R70901",
        "authority": "東大阪市",
        "url": "https://www.city.higashiosaka.lg.jp/cmsfiles/contents/0000014/14691/R70901.pdf",
        "format": "press_pdf",
        "default_law": "介護保険法",
    },
    {
        "slug": "higashiosaka-R70801",
        "authority": "東大阪市",
        "url": "https://www.city.higashiosaka.lg.jp/cmsfiles/contents/0000014/14691/R70801.pdf",
        "format": "press_pdf",
        "default_law": "介護保険法",
    },
    {
        "slug": "higashiosaka-R60701",
        "authority": "東大阪市",
        "url": "https://www.city.higashiosaka.lg.jp/cmsfiles/contents/0000014/14691/R60701.pdf",
        "format": "press_pdf",
        "default_law": "介護保険法",
    },
    {
        "slug": "higashiosaka-R51101",
        "authority": "東大阪市",
        "url": "https://www.city.higashiosaka.lg.jp/cmsfiles/contents/0000014/14691/R51101.pdf",
        "format": "press_pdf",
        "default_law": "介護保険法",
    },
    {
        "slug": "higashiosaka-R20801",
        "authority": "東大阪市",
        "url": "https://www.city.higashiosaka.lg.jp/cmsfiles/contents/0000014/14691/R20801torikesi.pdf",
        "format": "press_pdf",
        "default_law": "介護保険法",
    },
    {
        "slug": "higashiosaka-011201",
        "authority": "東大阪市",
        "url": "https://www.city.higashiosaka.lg.jp/cmsfiles/contents/0000014/14691/011201-torikesi.pdf",
        "format": "press_pdf",
        "default_law": "介護保険法",
    },
    {
        "slug": "higashiosaka-300101",
        "authority": "東大阪市",
        "url": "https://www.city.higashiosaka.lg.jp/cmsfiles/contents/0000014/14691/300101torikeshi.pdf",
        "format": "press_pdf",
        "default_law": "介護保険法",
    },
    {
        "slug": "higashiosaka-291231",
        "authority": "東大阪市",
        "url": "https://www.city.higashiosaka.lg.jp/cmsfiles/contents/0000014/14691/291231torikesi.pdf",
        "format": "press_pdf",
        "default_law": "介護保険法",
    },
    {
        "slug": "higashiosaka-290201",
        "authority": "東大阪市",
        "url": "https://www.city.higashiosaka.lg.jp/cmsfiles/contents/0000014/14691/290201torikeshi.pdf",
        "format": "press_pdf",
        "default_law": "介護保険法",
    },
    {
        "slug": "higashiosaka-280331",
        "authority": "東大阪市",
        "url": "https://www.city.higashiosaka.lg.jp/cmsfiles/contents/0000014/14691/280331torikeshi.pdf",
        "format": "press_pdf",
        "default_law": "介護保険法",
    },
    {
        "slug": "higashiosaka-270717",
        "authority": "東大阪市",
        "url": "https://www.city.higashiosaka.lg.jp/cmsfiles/contents/0000014/14691/270717torikeshishiryou.pdf",
        "format": "press_pdf",
        "default_law": "介護保険法",
    },
    {
        "slug": "higashiosaka-270131",
        "authority": "東大阪市",
        "url": "https://www.city.higashiosaka.lg.jp/cmsfiles/contents/0000014/14691/270131torikeshishiryou.pdf",
        "format": "press_pdf",
        "default_law": "介護保険法",
    },
    {
        "slug": "higashiosaka-R61001-stop",
        "authority": "東大阪市",
        "url": "https://www.city.higashiosaka.lg.jp/cmsfiles/contents/0000014/14691/R61001.pdf",
        "format": "press_pdf",
        "default_law": "介護保険法",
    },
    {
        "slug": "higashiosaka-R30201-stop",
        "authority": "東大阪市",
        "url": "https://www.city.higashiosaka.lg.jp/cmsfiles/contents/0000014/14691/R30201.pdf",
        "format": "press_pdf",
        "default_law": "介護保険法",
    },
    {
        "slug": "higashiosaka-300101-stop",
        "authority": "東大阪市",
        "url": "https://www.city.higashiosaka.lg.jp/cmsfiles/contents/0000014/14691/300101zennbukouryoku.pdf",
        "format": "press_pdf",
        "default_law": "介護保険法",
    },
]


# ---------------------------------------------------------------------------
# Date / law parsing
# ---------------------------------------------------------------------------

WAREKI_RE = re.compile(
    r"(令和|平成|昭和|R|H|S)\s*(\d+|元)\s*[年.\-．／]?\s*(\d{1,2})\s*[月.\-．／]?\s*(\d{1,2})\s*日?"
)
SEIREKI_RE = re.compile(r"(20\d{2}|19\d{2})\s*[年.\-／/]\s*(\d{1,2})\s*[月.\-／/]\s*(\d{1,2})")
ERA_OFFSET = {"令和": 2018, "R": 2018, "平成": 1988, "H": 1988, "昭和": 1925, "S": 1925}

# Law article extraction
KAIGO_ARTICLE_RE = re.compile(
    r"介護保険法[^第。]{0,8}第\s*(\d+)\s*条(?:[^第。]{0,3}第\s*\d+\s*項)?"
)
SHOGAI_ARTICLE_RE = re.compile(
    r"(?:障害者総合支援法|障害者の日常生活|障害者自立支援法)[^第。]{0,12}第\s*(\d+)\s*条(?:[^第。]{0,3}第\s*\d+\s*項)?"
)
SHOGAI_DIRECT_ARTICLE_RE = re.compile(
    r"第\s*(\d+)\s*条第\s*(\d+)\s*項"
)  # in "（障害者総合支援法第５０条第１項第２号）"


def _to_hankaku_digits(s: str) -> str:
    """Convert full-width digits to half-width."""
    return s.translate(str.maketrans("０１２３４５６７８９", "0123456789"))


def _normalize(s: str) -> str:
    if not s:
        return ""
    return unicodedata.normalize("NFKC", s).strip()


def _parse_date(text: str) -> str | None:
    if not text:
        return None
    s = _to_hankaku_digits(_normalize(text))
    m = WAREKI_RE.search(s)
    if m:
        era, y_raw, mo, d = m.group(1), m.group(2), int(m.group(3)), int(m.group(4))
        try:
            y_off = 1 if y_raw == "元" else int(y_raw)
        except ValueError:
            return None
        if era not in ERA_OFFSET:
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


def _extract_law_ref(text: str, default_law: str | None) -> str | None:
    if not text:
        return default_law
    s = _to_hankaku_digits(_normalize(text))
    parts: list[str] = []
    m = KAIGO_ARTICLE_RE.search(s)
    if m:
        parts.append(f"介護保険法 第{m.group(1)}条")
    m = SHOGAI_ARTICLE_RE.search(s)
    if m:
        parts.append(f"障害者総合支援法 第{m.group(1)}条")
    if not parts:
        # Try inferring article from "第N条第M項" alone within parens.
        if default_law and "障害" in default_law:
            m = SHOGAI_DIRECT_ARTICLE_RE.search(s)
            if m:
                parts.append(f"障害者総合支援法 第{m.group(1)}条")
        if default_law and "介護" in default_law:
            m = SHOGAI_DIRECT_ARTICLE_RE.search(s)
            if m:
                parts.append(f"介護保険法 第{m.group(1)}条")
    if parts:
        return " / ".join(parts)
    return default_law


def _classify_kind(text: str) -> str:
    """Map disposition text to enforcement_kind enum."""
    if not text:
        return "other"
    s = _normalize(text)
    if "指定取消" in s or "指定の取消" in s or "指定取り消し" in s or "取消処分" in s:
        return "license_revoke"
    if (
        "効力の停止" in s
        or "効力停止" in s
        or "業務停止" in s
        or "受入停止" in s
        or "受入れ停止" in s
    ):
        return "business_improvement"
    if "改善命令" in s or "改善勧告" in s:
        return "business_improvement"
    if "公表" in s and "不正" in s:
        return "license_revoke"  # "指定取消相当" 公表
    return "other"


def _extract_amount(text: str) -> int | None:
    """Extract 不正受給額 / 返還額 in yen from text. Best-effort."""
    if not text:
        return None
    s = _to_hankaku_digits(_normalize(text))
    # Look for patterns like "1,234,567円" or "約100万円" etc.
    m = re.search(r"(\d[\d,]{3,15})\s*円", s)
    if m:
        try:
            return int(m.group(1).replace(",", ""))
        except ValueError:
            return None
    m = re.search(r"約?\s*(\d+(?:\.\d+)?)\s*万円", s)
    if m:
        try:
            return int(float(m.group(1)) * 10000)
        except ValueError:
            return None
    m = re.search(r"約?\s*(\d+(?:\.\d+)?)\s*千万円", s)
    if m:
        try:
            return int(float(m.group(1)) * 10_000_000)
        except ValueError:
            return None
    m = re.search(r"約?\s*(\d+(?:\.\d+)?)\s*億円", s)
    if m:
        try:
            return int(float(m.group(1)) * 100_000_000)
        except ValueError:
            return None
    return None


# ---------------------------------------------------------------------------
# Row dataclass + parsers
# ---------------------------------------------------------------------------


@dataclass
class EnfRow:
    target_name: str
    location: str | None
    issuance_date: str
    related_law_ref: str | None
    reason_summary: str | None
    enforcement_kind: str
    amount_yen: int | None
    extras: dict[str, str] | None  # raw fields


def _clean(c: str | None) -> str:
    if c is None:
        return ""
    return _normalize(c.replace("\n", " "))


def parse_osaka_pref_pdf(pdf_bytes: bytes, *, authority: str, default_law: str) -> list[EnfRow]:
    """Parse 大阪府/枚方市 4-column PDF: [date, location, service, reason+law]."""
    rows: list[EnfRow] = []
    seen_in_pdf: set[tuple[str, str, str]] = set()
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            # Track the last partial row's date+location for continuation rows.
            current_date: str | None = None
            current_loc: str | None = None
            current_service: str | None = None
            current_reason: list[str] = []
            current_kind: str = "license_revoke"

            def _flush() -> None:
                nonlocal current_date, current_loc, current_service, current_reason, current_kind
                if current_date and (current_loc or current_service):
                    reason_text = " ".join(current_reason).strip() or None
                    law = _extract_law_ref(reason_text or "", default_law)
                    # Build unique target name: location + service + 8-char reason hash
                    # so that multiple events on same day in same city stay distinct.
                    reason_hash = (
                        hashlib.sha1((reason_text or "x").encode("utf-8")).hexdigest()[:6]
                        if reason_text
                        else "noinfo"
                    )
                    target_name = (
                        f"{current_loc or '不詳'} {current_service or ''} 事業者 [{reason_hash}]"
                    ).strip()
                    target_name = target_name[:200]
                    key = (target_name, current_date)
                    if key not in seen_in_pdf:
                        seen_in_pdf.add(key)
                        rows.append(
                            EnfRow(
                                target_name=target_name,
                                location=current_loc,
                                issuance_date=current_date,
                                related_law_ref=law,
                                reason_summary=(reason_text or "")[:4000] or None,
                                enforcement_kind=current_kind,
                                amount_yen=_extract_amount(reason_text or ""),
                                extras={
                                    "service_type": current_service or "",
                                    "format": "osaka_pref_pdf",
                                },
                            )
                        )
                current_date = None
                current_loc = None
                current_service = None
                current_reason = []
                current_kind = "license_revoke"

            for page in pdf.pages:
                try:
                    tables = page.extract_tables() or []
                except Exception as exc:  # noqa: BLE001
                    _LOG.debug("page extract err: %s", exc)
                    continue
                for tbl in tables:
                    for raw in tbl:
                        if not raw or len(raw) < 2:
                            continue
                        cols = [_clean(c) for c in raw]
                        # Drop the header row.
                        if cols and ("処分日" in cols[0] or "公表日" in cols[0]):
                            continue
                        # Pad
                        cols += [""] * (4 - len(cols))
                        date_cell = cols[0]
                        # If date_cell parses to a date → start new row.
                        date_iso = _parse_date(date_cell)
                        if date_iso:
                            _flush()
                            current_date = date_iso
                            current_loc = cols[1] or None
                            current_service = cols[2] or None
                            current_reason = [cols[3]] if cols[3] else []
                            # Detect kind from any cell
                            blob = " ".join(cols)
                            current_kind = _classify_kind(blob)
                        else:
                            # Continuation row (date column empty) — append to reason
                            if current_date and cols[3]:
                                current_reason.append(cols[3])
                            elif current_date and any(cols):
                                # All cols empty? skip
                                non_empty = " ".join(c for c in cols if c).strip()
                                if non_empty:
                                    current_reason.append(non_empty)
            _flush()
    except Exception as exc:  # noqa: BLE001
        _LOG.warning("osaka pdf parse failed: %s", exc)
    return rows


def parse_tokyo_cumulative_pdf(pdf_bytes: bytes, *, default_law: str) -> list[EnfRow]:
    """Parse 東京都福祉局 cumulative table:
    [年度, 申請者名称, 申請者住所, 事業所番号, 事業種別, 事業所名称, 事業所所在地,
     公表年月日, 指定取消日等, 処分等の内容, 処分事由・公表内容,
     指定年月日, 代表者職種, 代表者名]
    """
    rows: list[EnfRow] = []
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages:
                try:
                    tables = page.extract_tables() or []
                except Exception as exc:  # noqa: BLE001
                    _LOG.debug("page extract err: %s", exc)
                    continue
                for tbl in tables:
                    for raw in tbl:
                        if not raw or len(raw) < 11:
                            continue
                        cols = [_clean(c) for c in raw]
                        if "申請者名称" in cols[1] or cols[0] == "年度":
                            continue
                        target_name = cols[1]
                        if not target_name or len(target_name) > 200:
                            continue
                        # 公表年月日 (col 7)
                        date_iso = _parse_date(cols[7]) if len(cols) > 7 else None
                        if not date_iso:
                            continue
                        addr = cols[2] if len(cols) > 2 else ""
                        service_type = cols[4] if len(cols) > 4 else ""
                        facility_name = cols[5] if len(cols) > 5 else ""
                        facility_addr = cols[6] if len(cols) > 6 else ""
                        disposition = cols[9] if len(cols) > 9 else ""
                        reason = cols[10] if len(cols) > 10 else ""
                        torikeshi_date = cols[8] if len(cols) > 8 else ""
                        kind = _classify_kind(disposition)
                        full_reason = (
                            f"[{disposition}] {reason} (事業所={facility_name}, 種別={service_type}, "
                            f"事業所所在地={facility_addr})"
                        )
                        rows.append(
                            EnfRow(
                                target_name=target_name,
                                location=facility_addr or addr or None,
                                issuance_date=date_iso,
                                related_law_ref=_extract_law_ref(
                                    reason or disposition, default_law
                                ),
                                reason_summary=full_reason[:4000],
                                enforcement_kind=kind,
                                amount_yen=_extract_amount(reason),
                                extras={
                                    "facility_name": facility_name,
                                    "service_type": service_type,
                                    "disposition_text": disposition,
                                    "torikeshi_date": torikeshi_date,
                                    "format": "tokyo_cumulative_pdf",
                                },
                            )
                        )
    except Exception as exc:  # noqa: BLE001
        _LOG.warning("tokyo cumulative pdf parse failed: %s", exc)
    return rows


def parse_press_pdf(
    pdf_bytes: bytes, *, authority: str, default_law: str, source_url: str
) -> list[EnfRow]:
    """Parse single-event press release PDF.

    Heuristic: find provider name (after "名称" or "申請(開設)者名"),
    issuance date (top of page), disposition, reason. Extract first
    occurrence for each.
    """
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            text_parts: list[str] = []
            for page in pdf.pages:
                t = page.extract_text() or ""
                text_parts.append(t)
            full_text = "\n".join(text_parts)
    except Exception as exc:  # noqa: BLE001
        _LOG.warning("press pdf %s open failed: %s", source_url, exc)
        return []

    if not full_text.strip():
        return []

    norm = _to_hankaku_digits(unicodedata.normalize("NFKC", full_text))

    # Issuance date: try first 5 lines (often "令和N年M月D日").
    head = "\n".join(norm.splitlines()[:8])
    issuance = _parse_date(head)
    if not issuance:
        # Fallback: scan for any date.
        m = WAREKI_RE.search(norm) or SEIREKI_RE.search(norm)
        if m:
            issuance = _parse_date(m.group(0))
    if not issuance:
        _LOG.debug("press pdf %s: no date found", source_url)
        return []

    # Provider name: priority order
    target_name: str | None = None
    name_patterns = [
        # 法人名 (most common in 東大阪市 PDFs)
        re.compile(r"法\s*人\s*名[\s　:：]*([^\n（(]{2,80})"),
        # 申請(開設)者名
        re.compile(r"申請\(開設\)者名[\s　:：]*([^\n（(]{2,80})"),
        # 申請者名称
        re.compile(r"申請者名称[\s　:：]*([^\n（(]{2,80})"),
        # (1)名称 ... / (1) 名称 株式会社... — used by 東京都 press
        # Catch when 名称 is preceded by a paren-numbered marker.
        re.compile(r"[(（][1１][)）][\s　]*名\s*称[\s　:：]*\n?([^\n（(]{2,80})"),
        # Generic 名 称 on its own line
        re.compile(r"(?:^|\n)\s*名\s*称[\s　:：]*\n?([^\n（(]{2,80})"),
        # 事業者名
        re.compile(r"事業者名[\s　:：]*([^\n（(]{2,80})"),
    ]
    for pat in name_patterns:
        m = pat.search(norm)
        if m:
            cand = m.group(1).strip()
            # Strip trailing noise
            cand = re.split(r"[（(]|代表者|事業所|所在地|住所|の取消|処分", cand)[0].strip()
            # Strip leading punctuation/numbers
            cand = re.sub(r"^[、。．・\s　:：]+", "", cand).strip()
            if 2 <= len(cand) <= 100 and not cand.startswith(("、", "。", "・")):
                target_name = cand
                break

    if not target_name:
        # Fallback: first occurrence of a 法人 prefix anywhere.
        m = re.search(
            r"(株式会社|合同会社|有限会社|社会福祉法人|医療法人|一般社団法人|公益社団法人|"
            r"合資会社|協同組合|社会医療法人|特定非営利活動法人|NPO法人)[^\s\n、。（）()]{1,40}",
            norm,
        )
        if m:
            target_name = m.group(0).strip()

    if not target_name:
        _LOG.debug("press pdf %s: no provider name found", source_url)
        return []

    # Disposition + reason: scan first 1500 chars.
    head_text = norm[:2500]
    kind = _classify_kind(head_text)

    # Try to extract a 1-line summary
    reason_summary = head_text.replace("\n", " ")[:600]

    # Extract amount (返還額 / 不正請求額)
    amount = None
    amt_section = re.search(r"(?:返還[^。]{0,20}|不正請求[^。]{0,20}|介護給付費[^。]{0,20})", norm)
    if amt_section:
        # search for 円 in vicinity
        sec_text = norm[amt_section.start() : amt_section.start() + 400]
        amount = _extract_amount(sec_text)
    if amount is None:
        amount = _extract_amount(norm[:3000])

    return [
        EnfRow(
            target_name=target_name[:200],
            location=None,
            issuance_date=issuance,
            related_law_ref=_extract_law_ref(norm[:3000], default_law),
            reason_summary=reason_summary[:4000],
            enforcement_kind=kind,
            amount_yen=amount,
            extras={
                "format": "press_pdf",
                "source_url": source_url,
            },
        )
    ]


# ---------------------------------------------------------------------------
# DB
# ---------------------------------------------------------------------------


def _slug8(name: str, date: str) -> str:
    h = hashlib.sha1(f"{name}|{date}".encode()).hexdigest()
    return h[:8]


def _entity_canonical_id(
    authority: str, target_name: str, issuance_date: str, law: str | None
) -> str:
    """Build canonical_id = AM-ENF-KAIGO-{pref-slug}-{seq} or AM-ENF-SHOGAI-{...}."""
    # Pref slug: roman or romaji-ish stub (best-effort: use authority hash).
    auth_slug = hashlib.sha1(authority.encode("utf-8")).hexdigest()[:6]
    if law and "障害" in law:
        prefix = "AM-ENF-SHOGAI"
    else:
        prefix = "AM-ENF-KAIGO"
    seq = _slug8(target_name, issuance_date)
    return f"{prefix}-{auth_slug}-{seq}"


def ensure_tables(conn: sqlite3.Connection) -> None:
    for tbl in ("am_entities", "am_enforcement_detail"):
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (tbl,),
        ).fetchone()
        if not row:
            raise SystemExit(f"missing table '{tbl}' — apply migrations first")


def existing_dedup_keys(conn: sqlite3.Connection, authority: str) -> set[tuple[str, str]]:
    """{(target_name, issuance_date)} already in DB for this authority."""
    out: set[tuple[str, str]] = set()
    for n, d in conn.execute(
        "SELECT target_name, issuance_date FROM am_enforcement_detail WHERE issuing_authority=?",
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
        ) VALUES (?, 'enforcement', 'kaigo_shogai_torikeshi', NULL,
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
    *,
    entity_id: str,
    target_name: str,
    issuance_date: str,
    issuing_authority: str,
    enforcement_kind: str,
    reason_summary: str | None,
    related_law_ref: str | None,
    amount_yen: int | None,
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
        ) VALUES (?, NULL, ?, ?, ?, ?, NULL, NULL, ?, ?, ?, ?, ?)
        """,
        (
            entity_id,
            target_name[:500],
            enforcement_kind,
            issuing_authority,
            issuance_date,
            (reason_summary or "")[:4000] or None,
            (related_law_ref or "")[:1000] or None,
            amount_yen,
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
    ap.add_argument("--limit", type=int, default=None, help="cap total inserts (debugging)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--verbose", "-v", action="store_true")
    return ap.parse_args(argv)


def fetch_and_parse(http: HttpClient, src: dict[str, str]) -> list[EnfRow]:
    url = src["url"]
    fmt = src["format"]
    res = http.get(url, max_bytes=15 * 1024 * 1024)
    if not res.ok:
        _LOG.warning("[%s] fetch failed status=%s", src["slug"], res.status)
        return []
    body = res.body
    default_law = src.get("default_law") or "介護保険法"
    authority = src["authority"]
    if fmt == "osaka_pref_pdf":
        return parse_osaka_pref_pdf(body, authority=authority, default_law=default_law)
    if fmt == "tokyo_cumulative_pdf":
        return parse_tokyo_cumulative_pdf(body, default_law=default_law)
    if fmt in ("tokyo_press_pdf", "press_pdf"):
        return parse_press_pdf(body, authority=authority, default_law=default_law, source_url=url)
    _LOG.warning("[%s] unknown format=%s", src["slug"], fmt)
    return []


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

    stats = {
        "sources_fetched": 0,
        "sources_failed": 0,
        "rows_parsed": 0,
        "rows_inserted": 0,
        "rows_dup_in_db": 0,
        "rows_dup_in_batch": 0,
    }
    by_law: dict[str, int] = {}
    by_authority: dict[str, int] = {}
    sample_rows: list[dict[str, str | int | None]] = []

    sources: list[dict[str, str]] = MULTIROW_SOURCES + SINGLE_EVENT_PDFS

    # Per-authority dedup cache: load once when authority first seen.
    auth_dedup_cache: dict[str, set[tuple[str, str]]] = {}

    # Group sources by authority for batched commits.
    for src in sources:
        if args.limit and stats["rows_inserted"] >= args.limit:
            _LOG.info("limit reached: %d", args.limit)
            break

        authority = src["authority"]
        slug = src["slug"]

        rows = fetch_and_parse(http, src)
        if not rows:
            stats["sources_failed"] += 1
            _LOG.info("[%s] no rows parsed", slug)
            continue
        stats["sources_fetched"] += 1
        stats["rows_parsed"] += len(rows)
        _LOG.info("[%s] parsed=%d (authority=%s)", slug, len(rows), authority)

        if conn is None:
            # Dry run: just sample
            for r in rows[:2]:
                sample_rows.append(
                    {
                        "authority": authority,
                        "target_name": r.target_name,
                        "issuance_date": r.issuance_date,
                        "kind": r.enforcement_kind,
                        "law": r.related_law_ref,
                        "amount": r.amount_yen,
                    }
                )
            continue

        if authority not in auth_dedup_cache:
            auth_dedup_cache[authority] = existing_dedup_keys(conn, authority)
        db_keys = auth_dedup_cache[authority]
        batch_keys: set[tuple[str, str]] = set()

        try:
            conn.execute("BEGIN IMMEDIATE")
            for r in rows:
                if args.limit and stats["rows_inserted"] >= args.limit:
                    break
                key = (r.target_name, r.issuance_date)
                if key in db_keys:
                    stats["rows_dup_in_db"] += 1
                    continue
                if key in batch_keys:
                    stats["rows_dup_in_batch"] += 1
                    continue
                batch_keys.add(key)
                db_keys.add(key)

                canonical_id = _entity_canonical_id(
                    authority, r.target_name, r.issuance_date, r.related_law_ref
                )
                primary_name = (
                    f"{r.target_name} ({r.issuance_date}) — {authority} {r.enforcement_kind}"
                )
                raw_json = json.dumps(
                    {
                        "authority": authority,
                        "source_slug": slug,
                        "target_name": r.target_name,
                        "location": r.location,
                        "issuance_date": r.issuance_date,
                        "related_law_ref": r.related_law_ref,
                        "reason_summary": r.reason_summary,
                        "enforcement_kind": r.enforcement_kind,
                        "amount_yen": r.amount_yen,
                        "source_url": src["url"],
                        "source_attribution": f"{authority}ウェブサイト",
                        "license": "政府機関の著作物（出典明記で転載引用可）",
                        "extras": r.extras or {},
                    },
                    ensure_ascii=False,
                )
                try:
                    upsert_entity(conn, canonical_id, primary_name, src["url"], raw_json, now_iso)
                    insert_enforcement(
                        conn=conn,
                        entity_id=canonical_id,
                        target_name=r.target_name,
                        issuance_date=r.issuance_date,
                        issuing_authority=authority,
                        enforcement_kind=r.enforcement_kind,
                        reason_summary=r.reason_summary,
                        related_law_ref=r.related_law_ref,
                        amount_yen=r.amount_yen,
                        source_url=src["url"],
                        source_fetched_at=now_iso,
                    )
                    stats["rows_inserted"] += 1
                    # Update breakdown
                    law_key = (
                        "障害福祉"
                        if (r.related_law_ref and "障害" in r.related_law_ref)
                        else "介護保険"
                    )
                    by_law[law_key] = by_law.get(law_key, 0) + 1
                    by_authority[authority] = by_authority.get(authority, 0) + 1
                    if len(sample_rows) < 3:
                        sample_rows.append(
                            {
                                "authority": authority,
                                "target_name": r.target_name,
                                "issuance_date": r.issuance_date,
                                "kind": r.enforcement_kind,
                                "law": r.related_law_ref,
                                "amount": r.amount_yen,
                                "reason": (r.reason_summary or "")[:120],
                            }
                        )
                except sqlite3.Error as exc:
                    _LOG.error(
                        "[%s] DB error name=%r date=%s: %s",
                        slug,
                        r.target_name,
                        r.issuance_date,
                        exc,
                    )
                    continue
            conn.commit()
        except sqlite3.Error as exc:
            _LOG.error("[%s] BEGIN/commit failed: %s", slug, exc)
            try:
                conn.rollback()
            except sqlite3.Error:
                pass
            continue

    http.close()
    if conn is not None:
        try:
            conn.close()
        except sqlite3.Error:
            pass

    _LOG.info(
        "done sources_ok=%d sources_fail=%d parsed=%d inserted=%d dup_db=%d dup_batch=%d",
        stats["sources_fetched"],
        stats["sources_failed"],
        stats["rows_parsed"],
        stats["rows_inserted"],
        stats["rows_dup_in_db"],
        stats["rows_dup_in_batch"],
    )
    _LOG.info("by_law=%s", by_law)
    _LOG.info("by_authority=%s", by_authority)
    print("=== SUMMARY ===")
    print(f"total_inserted: {stats['rows_inserted']}")
    print(f"by_law: {by_law}")
    print(f"by_authority: {by_authority}")
    print(f"samples ({len(sample_rows)}):")
    for s in sample_rows:
        print(f"  - {s}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
