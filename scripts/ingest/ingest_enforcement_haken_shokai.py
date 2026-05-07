#!/usr/bin/env python3
"""Ingest 厚労省 派遣事業 / 職業紹介事業 行政処分 (許可取消・事業停止・改善命令・告発)
into ``am_enforcement_detail`` + ``am_entities`` in autonomath.db.

Background:
    労働者派遣事業 / 職業紹介事業 は厚生労働大臣許可事業で、許可取消や事業停止
    などの 行政処分 が定期的に公表される。年間 50-100 件程度の規模で、社労士
    法人 / 内部統制部門からの問合せが多い重要 cluster だが、autonomath.db には
    現状 4 件しか入っていない (related_law_ref に '派遣法' / '職業安定' が付いた
    労働基準関係 row のみ)。本スクリプトで MHLW 中央 + 一覧 PDF と houdou
    press releases を walk して +150 row 以上を投入する。

Sources walked (一次資料のみ):
    - https://www.mhlw.go.jp/content/001679492.pdf
        労働者派遣事業に係る行政処分 (現在実施中の改善命令・事業停止・許可取消
        を 1 PDF にまとめたマスタ。令和8年3月30日現在)
    - https://www.mhlw.go.jp/content/001662885.pdf
        職業紹介事業等に係る行政処分 (同上、令和8年4月24日現在)
    - https://www.mhlw.go.jp/stf/houdou/bukyoku/syokuan.html
        職業安定局 報道発表 index。新しい順に 38 件の派遣/職紹 admin action
        page (newpage_*.html) が並ぶ。各 page から detail PDF
        (/content/11654000/*.pdf 形式) を fetch、別添表 / 別紙 表を解析。
        旧 0000xxx.html URL 形式は 404 を返すので除外。

Aggregator BAN は厳守: noukaweb / hojyokin-portal / biz.stayway / prtimes /
nikkei / wikipedia は 一切 fetch しない。

License: 厚生労働省ウェブサイト (政府機関の著作物、出典明記で転載引用可)。

Schema mapping (am_enforcement_detail.enforcement_kind enum):
    許可取消 / 許可の取消し / 事業廃止     → license_revoke
    事業停止                                → contract_suspend
    改善命令 / 業務改善命令                 → business_improvement
    告発                                    → investigation
    その他                                  → other

Authority labels:
    - 中央 (厚労大臣) 処分     → '厚生労働省'
    - 労働局 で実施した処分    → '厚生労働省 {pref}労働局'
    マスタ PDF の '実施労働局' 欄の都道府県情報を優先して使う。

Dedup key:
    (target_name, issuance_date) within issuing_authority. (issuing_authority,
    issuance_date, target_name) 三つ組で既存 row と canonical_id 衝突を避ける。

Parallel-safe (CLAUDE.md §5):
    - PRAGMA busy_timeout=300000 + BEGIN IMMEDIATE
    - per-bucket commits (PDF / per-detail page)。他 4 worker と衝突した場合
      は 5 分まで wait してリトライ。

CLI:
    python scripts/ingest/ingest_enforcement_haken_shokai.py
    python scripts/ingest/ingest_enforcement_haken_shokai.py --dry-run -v
    python scripts/ingest/ingest_enforcement_haken_shokai.py --limit-detail 5
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
import sys
import time
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urljoin

try:
    import pdfplumber  # type: ignore
    import requests  # type: ignore
    from bs4 import BeautifulSoup  # type: ignore
except ImportError as exc:  # pragma: no cover
    print(f"missing dep: {exc}. pip install pdfplumber requests beautifulsoup4", file=sys.stderr)
    sys.exit(1)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_DB = REPO_ROOT / "autonomath.db"

USER_AGENT = "AutonoMath/0.1.0 (+https://bookyou.net) ingest-haken-shokai (contact=ops@jpcite.com)"
HTTP_TIMEOUT = 60
RATE_SLEEP = 1.0  # 1 req/sec/host

INDEX_URL = "https://www.mhlw.go.jp/stf/houdou/bukyoku/syokuan.html"
MASTER_PDFS = [
    {
        "url": "https://www.mhlw.go.jp/content/001679492.pdf",
        "label": "労働者派遣事業に係る行政処分",
        "law_kind": "haken",  # 労働者派遣法
    },
    {
        "url": "https://www.mhlw.go.jp/content/001662885.pdf",
        "label": "職業紹介事業等に係る行政処分",
        "law_kind": "shokai",  # 職業安定法
    },
]

_LOG = logging.getLogger("autonomath.ingest_haken_shokai")

# ---------------------------------------------------------------------------
# Date / text helpers
# ---------------------------------------------------------------------------

WAREKI_RE = re.compile(
    r"(令和|平成|R|H)\s*(元|[0-9０-９]+)\s*年\s*" r"([0-9０-９]+)\s*月\s*([0-9０-９]+)\s*日"
)
WAREKI_SHORT_RE = re.compile(
    r"(令和|平成)\s*(元|[0-9０-９]+)\s*年" r"\s*([0-9０-９]+)\s*月\s*([0-9０-９]+)\s*日"
)
SEIREKI_RE = re.compile(r"(20[0-9]{2})\s*年\s*([0-9]+)\s*月\s*([0-9]+)\s*日")
ERA_OFFSET = {"令和": 2018, "R": 2018, "平成": 1988, "H": 1988}

# 許可番号 patterns
HAKEN_NUM_RE = re.compile(r"派\s*([0-9０-９]{1,3})\s*[\-－ｰー‐]\s*([0-9０-９]{4,7})")
SHOKAI_NUM_RE = re.compile(r"([0-9０-９]{1,3})\s*[\-－ｰー‐]\s*ユ\s*[\-－ｰー‐]\s*([0-9０-９]{4,7})")
# 特定労働者派遣事業 届出番号 (legacy 2013-2018, abolished 2018 reform)
TOKUTEI_NUM_RE = re.compile(r"特\s*([0-9０-９]{1,3})\s*[\-－ｰー‐]\s*([0-9０-９]{4,7})")

# 都道府県 → 労働局 label map
PREF_TO_BUREAU = {
    "01": "北海道",
    "02": "青森",
    "03": "岩手",
    "04": "宮城",
    "05": "秋田",
    "06": "山形",
    "07": "福島",
    "08": "茨城",
    "09": "栃木",
    "10": "群馬",
    "11": "埼玉",
    "12": "千葉",
    "13": "東京",
    "14": "神奈川",
    "15": "新潟",
    "16": "富山",
    "17": "石川",
    "18": "福井",
    "19": "山梨",
    "20": "長野",
    "21": "岐阜",
    "22": "静岡",
    "23": "愛知",
    "24": "三重",
    "25": "滋賀",
    "26": "京都",
    "27": "大阪",
    "28": "兵庫",
    "29": "奈良",
    "30": "和歌山",
    "31": "鳥取",
    "32": "島根",
    "33": "岡山",
    "34": "広島",
    "35": "山口",
    "36": "徳島",
    "37": "香川",
    "38": "愛媛",
    "39": "高知",
    "40": "福岡",
    "41": "佐賀",
    "42": "長崎",
    "43": "熊本",
    "44": "大分",
    "45": "宮崎",
    "46": "鹿児島",
    "47": "沖縄",
}

# 労働局名候補
BUREAU_LABELS = {f"{name}労働局" for name in PREF_TO_BUREAU.values()}

# Title keyword → enforcement_kind classification (for press release titles).
KIND_TITLE_RULES: list[tuple[str, str, str]] = [
    # (token, kind, default law_basis)
    ("許可を取り消し", "license_revoke", ""),
    ("許可取消", "license_revoke", ""),
    ("許可の取消し", "license_revoke", ""),
    ("事業廃止", "license_revoke", ""),
    ("事業停止命令", "contract_suspend", ""),
    ("業務改善命令", "business_improvement", ""),
    ("業務停止命令", "contract_suspend", ""),
    ("改善命令", "business_improvement", ""),
    ("告発", "investigation", ""),
    ("行政処分", "other", ""),
    ("公表", "other", ""),
]


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "")
    return re.sub(r"\s+", " ", text).strip()


def _wareki_to_iso(text: str) -> str | None:
    if not text:
        return None
    s = unicodedata.normalize("NFKC", text)
    m = WAREKI_RE.search(s)
    if m:
        era, yr, mo, dy = m.group(1), m.group(2), m.group(3), m.group(4)
        try:
            yr_i = 1 if yr == "元" else int(yr)
        except ValueError:
            return None
        if era in ("R", "令和"):
            year = 2018 + yr_i
        elif era in ("H", "平成"):
            year = 1988 + yr_i
        else:
            return None
        try:
            mo_i, dy_i = int(mo), int(dy)
            if not (1 <= mo_i <= 12 and 1 <= dy_i <= 31):
                return None
            return f"{year:04d}-{mo_i:02d}-{dy_i:02d}"
        except ValueError:
            return None
    m = SEIREKI_RE.search(s)
    if m:
        try:
            y, mo, dy = int(m.group(1)), int(m.group(2)), int(m.group(3))
            if 2000 <= y <= 2100 and 1 <= mo <= 12 and 1 <= dy <= 31:
                return f"{y:04d}-{mo:02d}-{dy:02d}"
        except ValueError:
            return None
    return None


def _bureau_from_haken_num(haken_num: str | None) -> str | None:
    """許可番号 (e.g. 派13-301234, 特21-300650, 13-ユ-300001) → 都道府県労働局 label."""
    if not haken_num:
        return None
    s = unicodedata.normalize("NFKC", haken_num)
    m = HAKEN_NUM_RE.search(s)
    if m:
        code = f"{int(m.group(1)):02d}"
        pref = PREF_TO_BUREAU.get(code)
        if pref:
            return f"{pref}労働局"
    m = SHOKAI_NUM_RE.search(s)
    if m:
        code = f"{int(m.group(1)):02d}"
        pref = PREF_TO_BUREAU.get(code)
        if pref:
            return f"{pref}労働局"
    m = TOKUTEI_NUM_RE.search(s)
    if m:
        code = f"{int(m.group(1)):02d}"
        pref = PREF_TO_BUREAU.get(code)
        if pref:
            return f"{pref}労働局"
    return None


def _slug8(name: str, date: str) -> str:
    h = hashlib.sha1(f"{name}|{date}".encode()).hexdigest()
    return h[:8]


def _slugify_jp(text: str, max_len: int = 32) -> str:
    text = unicodedata.normalize("NFKC", text or "")
    text = re.sub(r"\s+", "-", text)
    text = re.sub(r"[^0-9A-Za-z_\-぀-ヿ一-鿿々]", "", text)
    return text[:max_len] or "unknown"


def _classify_kind(title: str) -> str:
    """Return enforcement_kind for a press-release title."""
    s = title or ""
    for token, kind, _ in KIND_TITLE_RULES:
        if token in s:
            return kind
    return "other"


def _extract_haken_perm(text: str) -> str | None:
    s = unicodedata.normalize("NFKC", text or "")
    m = HAKEN_NUM_RE.search(s)
    if m:
        return f"派{int(m.group(1)):02d}-{m.group(2)}"
    # Fall back to legacy 特定労働者派遣 届出番号
    m2 = TOKUTEI_NUM_RE.search(s)
    if m2:
        return f"特{int(m2.group(1)):02d}-{m2.group(2)}"
    return None


def _extract_shokai_perm(text: str) -> str | None:
    s = unicodedata.normalize("NFKC", text or "")
    m = SHOKAI_NUM_RE.search(s)
    if not m:
        return None
    return f"{int(m.group(1)):02d}-ユ-{m.group(2)}"


# Header / fragment labels that must never appear as target_name.
# Confirmed garbage rows from old archive PDFs (2014-2018) where 単独 PDF
# parser falls back without a real 別添 list.
_BAD_NAME_LITERALS = frozenset(
    {
        "名称",
        "事業者の名称",
        "事業主の名称",
        "事業主名",
        "商号又は名称",
        "代表者",
        "代表者職氏名",
        "代 表 者",
        "代 表 者 職 氏 名",
        "所在地",
        "事業主の所在地",
        "事業者の所在地",
        "及び住所",
        "住所",
        "許可番号",
        "許可番号:",
        "許可年月日",
        "届出受理番号",
        "届出年月日",
        "番号",
        "事業所名称",
        "事業所所在地",
        "事業所",
        "事業者名",
        "二",
        "三",
        "四",
        "五",
        "六",
        "七",
        "八",
        "九",
        "十",
        "（１）",
        "（２）",
        "（３）",
        "（４）",
        "（５）",
        "(1)",
        "(2)",
        "(3)",
        "(4)",
        "(5)",
        "別紙",
        "別添",
        "別表",
        "一覧",
        "以下のとおり",
        "下記のとおり",
    }
)


def _is_valid_target_name(name: str | None) -> bool:
    """Reject header labels / single-char fragments / pure dates as target_name.

    Only true business names (≥3 chars, not a recognized label, not a date)
    pass. Returns False for clearly garbage values that leaked from PDF
    structural fragments.
    """
    if not name:
        return False
    s = _normalize(name).strip()
    if not s:
        return False
    if s in _BAD_NAME_LITERALS:
        return False
    # Single ASCII or single CJK char — reject if all-CJK and ≤2 chars.
    # Allow short names ONLY if they include ASCII letters (e.g. "AA")
    # or the recognized business suffix patterns; otherwise reject.
    if len(s) <= 2 and re.fullmatch(r"[一-龥ぁ-んァ-ヶ々]+", s):
        return False
    # Pure date strings like "1999-10-01" or "令和2年4月1日"
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        return False
    if (
        re.search(r"年.*月.*日", s)
        and not any(
            kw in s
            for kw in ("株式会社", "有限会社", "合同会社", "合資会社", "合名会社", "(株)", "(有)")
        )
        and re.fullmatch(r"[\d０-９年月日\s\.\-/平成令和元昭和大正]+", s)
    ):
        # If the entire candidate is essentially a date sentence, reject.
        return False
    # Fragments that start with characters indicating leftover label text
    if s.startswith(("及び", "並びに", "のとおり", "以下", "下記")):
        return False
    # Numeric-only or near-numeric-only
    return not re.fullmatch(r"[\d０-９\s\-/年月日]+", s)


# ---------------------------------------------------------------------------
# HTTP client (1 req/sec/host pacing, retries)
# ---------------------------------------------------------------------------


class HttpClient:
    def __init__(self, *, user_agent: str = USER_AGENT) -> None:
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": user_agent,
                "Accept-Language": "ja,en;q=0.5",
            }
        )
        self._last: float = 0.0

    def get(self, url: str, *, timeout: float = HTTP_TIMEOUT) -> requests.Response | None:
        delta = time.monotonic() - self._last
        if delta < RATE_SLEEP:
            time.sleep(RATE_SLEEP - delta)
        last_err: Exception | None = None
        for attempt in range(3):
            try:
                resp = self.session.get(url, timeout=timeout)
                self._last = time.monotonic()
                if resp.status_code == 200:
                    return resp
                if resp.status_code == 404:
                    return None
                last_err = RuntimeError(f"{resp.status_code} for {url}")
            except requests.RequestException as exc:
                last_err = exc
            time.sleep(2**attempt)
        _LOG.warning("fetch failed after retries: %s: %s", url, last_err)
        return None


# ---------------------------------------------------------------------------
# Source data structures
# ---------------------------------------------------------------------------


@dataclass
class EnfRow:
    target_name: str  # 事業者名
    issuance_date: str  # ISO yyyy-mm-dd
    enforcement_kind: (
        str  # license_revoke / contract_suspend / business_improvement / investigation / other
    )
    issuing_authority: str  # 厚生労働省 OR 厚生労働省 {pref}労働局
    related_law_ref: str  # 労働者派遣法第14条第1項第1号 etc.
    location: str | None = None
    permit_number_haken: str | None = None
    permit_number_shokai: str | None = None
    suspend_period: str | None = None
    reason_summary: str | None = None
    source_url: str = ""
    source_topic: str = "mhlw_haken_shokai"


@dataclass
class PressEntry:
    issuance_date: str | None
    title: str
    detail_url: str
    enforcement_kind: str  # title-derived


# ---------------------------------------------------------------------------
# Master PDF parser
# ---------------------------------------------------------------------------


def parse_master_haken_pdf(pdf_bytes: bytes, source_url: str) -> list[EnfRow]:
    """Parse 労働者派遣事業に係る行政処分 master PDF (3 sections:
    改善命令 / 事業停止命令 / 許可取消し)."""
    out: list[EnfRow] = []
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            # Section markers are extracted into headers when scanning each
            # table, so we don't need to track a per-page current_section
            # state across pages — header inspection of the per-table
            # extracted column names handles classification deterministically.
            for page in pdf.pages:
                tables = page.extract_tables() or []
                for table in tables:
                    if not table or len(table) < 2:
                        continue
                    header = [_normalize(c or "") for c in table[0]]
                    if not any(
                        "命令日" in h or "取消し日" in h or "許可の取消し通知日" in h
                        for h in header
                    ):
                        continue
                    is_revoke = any("許可の取消し" in h or "取消し日" in h for h in header)
                    is_suspend = any("事業停止期間" in h for h in header)
                    for raw in table[1:]:
                        cells = [_normalize((c or "").replace("\n", " ")) for c in raw]
                        if not cells or not any(cells):
                            continue
                        if is_revoke:
                            # cols: 通知日/取消し日 (line-broken), 名称[許可番号], 管轄労働局
                            if len(cells) < 3:
                                continue
                            date_cell = cells[0]
                            name_cell = cells[1]
                            bureau_cell = cells[2]
                            iso = _wareki_to_iso(date_cell)
                            if not iso:
                                continue
                            # 名前と許可番号を分離
                            name = name_cell
                            perm_haken = _extract_haken_perm(name_cell)
                            # remove [派xx-xxxxx] from name
                            name = re.sub(r"\[\s*派[^\]]+\]", "", name)
                            name = re.sub(r"［[^］]*派[^］]*］", "", name).strip()
                            if not _is_valid_target_name(name) or len(name) > 200:
                                continue
                            authority = "厚生労働省"
                            if bureau_cell:
                                authority = f"厚生労働省 {bureau_cell}"
                            out.append(
                                EnfRow(
                                    target_name=name,
                                    issuance_date=iso,
                                    enforcement_kind="license_revoke",
                                    issuing_authority=authority,
                                    related_law_ref="労働者派遣法第14条第1項",
                                    permit_number_haken=perm_haken,
                                    reason_summary=f"労働者派遣事業の許可取消し ({date_cell})",
                                    source_url=source_url,
                                    source_topic="mhlw_haken_master_revoke",
                                )
                            )
                        elif is_suspend:
                            # cols: 命令日, 名称, 事業停止期間, 実施労働局
                            if len(cells) < 4:
                                continue
                            iso = _wareki_to_iso(cells[0])
                            if not iso:
                                continue
                            name_cell = cells[1]
                            period_cell = cells[2]
                            bureau_cell = cells[3]
                            name = re.sub(r"\[\s*派[^\]]+\]", "", name_cell)
                            name = re.sub(r"［[^］]*派[^］]*］", "", name).strip()
                            name = re.sub(r"\(\s*※\s*\)", "", name).strip()
                            name = re.sub(r"（\s*※\s*）", "", name).strip()
                            perm_haken = _extract_haken_perm(name_cell)
                            if not _is_valid_target_name(name) or len(name) > 200:
                                continue
                            authority = f"厚生労働省 {bureau_cell}" if bureau_cell else "厚生労働省"
                            out.append(
                                EnfRow(
                                    target_name=name,
                                    issuance_date=iso,
                                    enforcement_kind="contract_suspend",
                                    issuing_authority=authority,
                                    related_law_ref="労働者派遣法第14条第2項",
                                    permit_number_haken=perm_haken,
                                    suspend_period=period_cell or None,
                                    reason_summary=(
                                        f"労働者派遣事業の事業停止命令 ({cells[0]})"
                                        + (f" 期間: {period_cell}" if period_cell else "")
                                    ),
                                    source_url=source_url,
                                    source_topic="mhlw_haken_master_suspend",
                                )
                            )
                        else:
                            # 改善命令: 命令日, 名称, 実施労働局
                            if len(cells) < 3:
                                continue
                            iso = _wareki_to_iso(cells[0])
                            if not iso:
                                continue
                            name_cell = cells[1]
                            bureau_cell = cells[2]
                            name = re.sub(r"\[\s*派[^\]]+\]", "", name_cell)
                            name = re.sub(r"［[^］]*派[^］]*］", "", name).strip()
                            name = re.sub(r"\(\s*※\s*\)", "", name).strip()
                            name = re.sub(r"（\s*※\s*）", "", name).strip()
                            perm_haken = _extract_haken_perm(name_cell)
                            if not _is_valid_target_name(name) or len(name) > 200:
                                continue
                            authority = f"厚生労働省 {bureau_cell}" if bureau_cell else "厚生労働省"
                            out.append(
                                EnfRow(
                                    target_name=name,
                                    issuance_date=iso,
                                    enforcement_kind="business_improvement",
                                    issuing_authority=authority,
                                    related_law_ref="労働者派遣法第49条第1項",
                                    permit_number_haken=perm_haken,
                                    reason_summary=f"労働者派遣事業改善命令 ({cells[0]})",
                                    source_url=source_url,
                                    source_topic="mhlw_haken_master_improvement",
                                )
                            )
    except Exception as exc:  # noqa: BLE001
        _LOG.warning("master haken PDF parse failed: %s", exc)
    return out


def parse_master_shokai_pdf(pdf_bytes: bytes, source_url: str) -> list[EnfRow]:
    """Parse 職業紹介事業等に係る行政処分 master PDF."""
    out: list[EnfRow] = []
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            # Per-table header inspection (is_revoke / is_suspend /
            # is_shut_down) classifies rows deterministically — no need to
            # track a per-page current_section state across pages.
            for page in pdf.pages:
                tables = page.extract_tables() or []
                for table in tables:
                    if not table or len(table) < 2:
                        continue
                    header = [_normalize(c or "") for c in table[0]]
                    is_revoke = any("許可の取消し" in h or "取消し日" in h for h in header)
                    is_suspend = any("事業停止期間" in h for h in header)
                    is_shut_down = any("廃止命令" in h for h in header)
                    for raw in table[1:]:
                        cells = [_normalize((c or "").replace("\n", " ")) for c in raw]
                        if not cells or not any(cells):
                            continue
                        if is_revoke:
                            if len(cells) < 3:
                                continue
                            iso = _wareki_to_iso(cells[0])
                            if not iso:
                                continue
                            name_cell = cells[1]
                            bureau_cell = cells[2]
                            perm_shokai = _extract_shokai_perm(name_cell)
                            name = re.sub(r"\[[^\]]*ユ[^\]]*\]", "", name_cell)
                            name = re.sub(r"［[^］]*ユ[^］]*］", "", name).strip()
                            if not _is_valid_target_name(name) or len(name) > 200:
                                continue
                            authority = f"厚生労働省 {bureau_cell}" if bureau_cell else "厚生労働省"
                            out.append(
                                EnfRow(
                                    target_name=name,
                                    issuance_date=iso,
                                    enforcement_kind="license_revoke",
                                    issuing_authority=authority,
                                    related_law_ref="職業安定法第32条の9第1項",
                                    permit_number_shokai=perm_shokai,
                                    reason_summary=f"有料職業紹介事業の許可取消し ({cells[0]})",
                                    source_url=source_url,
                                    source_topic="mhlw_shokai_master_revoke",
                                )
                            )
                        elif is_suspend:
                            if len(cells) < 4:
                                continue
                            iso = _wareki_to_iso(cells[0])
                            if not iso:
                                continue
                            name_cell = cells[1]
                            period_cell = cells[2]
                            bureau_cell = cells[3]
                            perm_shokai = _extract_shokai_perm(name_cell)
                            name = re.sub(r"\[[^\]]*ユ[^\]]*\]", "", name_cell)
                            name = re.sub(r"［[^］]*ユ[^］]*］", "", name).strip()
                            if not _is_valid_target_name(name) or len(name) > 200:
                                continue
                            authority = f"厚生労働省 {bureau_cell}" if bureau_cell else "厚生労働省"
                            out.append(
                                EnfRow(
                                    target_name=name,
                                    issuance_date=iso,
                                    enforcement_kind="contract_suspend",
                                    issuing_authority=authority,
                                    related_law_ref="職業安定法第32条の9第2項",
                                    permit_number_shokai=perm_shokai,
                                    suspend_period=period_cell or None,
                                    reason_summary=(
                                        f"有料職業紹介事業の事業停止命令 ({cells[0]})"
                                        + (f" 期間: {period_cell}" if period_cell else "")
                                    ),
                                    source_url=source_url,
                                    source_topic="mhlw_shokai_master_suspend",
                                )
                            )
                        elif is_shut_down:
                            if len(cells) < 3:
                                continue
                            iso = _wareki_to_iso(cells[0])
                            if not iso:
                                continue
                            name_cell = cells[1]
                            bureau_cell = cells[2]
                            name = re.sub(r"\[[^\]]*ユ[^\]]*\]", "", name_cell)
                            name = re.sub(r"［[^］]*ユ[^］]*］", "", name).strip()
                            if not _is_valid_target_name(name) or len(name) > 200:
                                continue
                            authority = f"厚生労働省 {bureau_cell}" if bureau_cell else "厚生労働省"
                            out.append(
                                EnfRow(
                                    target_name=name,
                                    issuance_date=iso,
                                    enforcement_kind="license_revoke",
                                    issuing_authority=authority,
                                    related_law_ref="職業安定法第33条の3第2項（第32条の9第1項準用）",
                                    reason_summary=f"無料職業紹介事業の事業廃止命令 ({cells[0]})",
                                    source_url=source_url,
                                    source_topic="mhlw_shokai_master_shutdown",
                                )
                            )
                        else:
                            # 改善命令: 命令日, 名称, 実施労働局
                            if len(cells) < 3:
                                continue
                            iso = _wareki_to_iso(cells[0])
                            if not iso:
                                continue
                            name_cell = cells[1]
                            bureau_cell = cells[2]
                            perm_shokai = _extract_shokai_perm(name_cell)
                            name = re.sub(r"\[[^\]]*ユ[^\]]*\]", "", name_cell)
                            name = re.sub(r"［[^］]*ユ[^］]*］", "", name).strip()
                            if not _is_valid_target_name(name) or len(name) > 200:
                                continue
                            authority = f"厚生労働省 {bureau_cell}" if bureau_cell else "厚生労働省"
                            out.append(
                                EnfRow(
                                    target_name=name,
                                    issuance_date=iso,
                                    enforcement_kind="business_improvement",
                                    issuing_authority=authority,
                                    related_law_ref="職業安定法第48条の3",
                                    permit_number_shokai=perm_shokai,
                                    reason_summary=f"有料職業紹介事業改善命令 ({cells[0]})",
                                    source_url=source_url,
                                    source_topic="mhlw_shokai_master_improvement",
                                )
                            )
    except Exception as exc:  # noqa: BLE001
        _LOG.warning("master shokai PDF parse failed: %s", exc)
    return out


# ---------------------------------------------------------------------------
# Press-release index parser
# ---------------------------------------------------------------------------

INC_KW = ["派遣", "職業紹介", "派遣元", "派遣先", "派遣事業", "労働者派遣法", "職業安定法"]
ACT_KW = [
    "行政処分",
    "許可取消",
    "許可を取り消し",
    "事業停止",
    "事業廃止",
    "改善命令",
    "業務改善命令",
    "告発",
    "違反",
]
EXCLUDE_TITLE_KW = ["ハローワーク", "障害者の就職件数", "職業紹介状況", "民間人材ビジネス実態"]


def parse_index_pages(html: str) -> list[PressEntry]:
    """Parse syokuan.html → list of admin-action pages.

    Includes both `/stf/newpage_*.html` (live) and `/stf/houdou/0000*.html`
    (archived 2013-2018) URLs. Old URLs are 404 on www.mhlw.go.jp directly
    but resolvable via web.archive.org snapshots — caller decides which
    transport to use.
    """
    soup = BeautifulSoup(html, "html.parser")
    out: list[PressEntry] = []
    seen: set[str] = set()
    for a in soup.find_all("a"):
        href = (a.get("href") or "").strip()
        if not href.endswith(".html"):
            continue
        is_newpage = href.startswith("/stf/newpage_")
        is_archive = bool(re.match(r"^/stf/houdou/0000\d+\.html$", href))
        if not (is_newpage or is_archive):
            continue
        title = _normalize(a.get_text(" ", strip=True))
        if not title:
            continue
        if not any(k in title for k in INC_KW):
            continue
        if not any(k in title for k in ACT_KW):
            continue
        if any(ex in title for ex in EXCLUDE_TITLE_KW):
            continue
        # Skip "差し替え" / "訂正" / "一部取消" notices — they reference a
        # previous disposition, not a new one (would create false positives).
        if any(k in title for k in ("差し替え", "訂正", "一部取消")):
            continue
        url = f"https://www.mhlw.go.jp{href}"
        if url in seen:
            continue
        seen.add(url)
        # Extract date prefix (e.g. "2026年4月24日 …")
        m = re.match(r"^\s*(20[0-9]{2})年\s*([0-9]+)月\s*([0-9]+)日", title)
        iso = None
        if m:
            try:
                y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
                iso = f"{y:04d}-{mo:02d}-{d:02d}"
            except ValueError:
                iso = None
        out.append(
            PressEntry(
                issuance_date=iso,
                title=title,
                detail_url=url,
                enforcement_kind=_classify_kind(title),
            )
        )
    return out


# ---------------------------------------------------------------------------
# Detail page parser (HTML + PDF)
# ---------------------------------------------------------------------------


def _wayback_url(orig_url: str) -> str:
    """Build a web.archive.org URL for an MHLW page. Uses 2018 snapshot which
    covers 2013-2018 content well; Wayback redirects to the closest snapshot.
    """
    return f"https://web.archive.org/web/2018/{orig_url}"


def _wayback_pdf_url(snapshot_pdf_url: str) -> str:
    """Normalize a wayback PDF URL: strip the /web/<timestamp>/ prefix to
    reveal the inner URL or pass through if already wayback-prefixed.
    """
    if snapshot_pdf_url.startswith("https://web.archive.org/"):
        return snapshot_pdf_url
    return f"https://web.archive.org/web/2018/{snapshot_pdf_url}"


def fetch_detail_pdfs(http: HttpClient, page_url: str) -> tuple[str, list[tuple[str, bytes]]]:
    """Fetch a press-release page and return (page_text, [(pdf_url, pdf_bytes), ...]).

    For old MHLW URLs (`/stf/houdou/0000xxx.html`) that 404 on the live site,
    automatically fall back to Wayback Machine snapshot.
    """
    is_archive = bool(re.search(r"/stf/houdou/0000\d+\.html$", page_url))
    fetch_url = page_url
    if is_archive:
        # Old URLs are dead on www.mhlw.go.jp — go straight to Wayback.
        fetch_url = _wayback_url(page_url)
    resp = http.get(fetch_url)
    if resp is None and not is_archive:
        # Even modern URLs occasionally 404 (e.g. moved); try Wayback as fallback.
        fetch_url = _wayback_url(page_url)
        resp = http.get(fetch_url)
    if resp is None:
        return "", []
    html = resp.text
    soup = BeautifulSoup(html, "html.parser")
    page_text = _normalize(soup.get_text(" ", strip=True))[:20000]

    # Pass 1: enumerate PDF candidates with their anchor text classification.
    cand: list[tuple[str, str, bool, bool]] = []  # (absurl, anchor, is_full, is_law_only)
    seen_urls: set[str] = set()
    # On Wayback the page-level <base> may be on archive.org, so urljoin uses
    # the resolved fetch URL (resp.url not page_url).
    base_url = getattr(resp, "url", page_url) or page_url
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href.lower().endswith(".pdf"):
            continue
        absurl = urljoin(base_url, href)
        # Accept both modern /content/ and legacy /file/ (archived) URLs.
        # Also allow web.archive.org wrapped versions of either.
        if "/content/" not in absurl and "/file/" not in absurl:
            continue
        # Drop banner/footer assets (e.g. accessibility logo)
        if any(k in absurl.lower() for k in ("logo", "icon", "footer", "header_")):
            continue
        if absurl in seen_urls:
            continue
        seen_urls.add(absurl)
        anchor = _normalize(a.get_text(" ", strip=True))
        is_full = ("全体版" in anchor) or ("資料全体" in anchor)
        is_law_only = ("条文" in anchor and "抜粋" in anchor) or ("関係条文" in anchor)
        cand.append((absurl, anchor, is_full, is_law_only))

    # If there's at least one non-"全体版" non-法令抜粋 PDF, the 全体版 PDF is
    # a dup wrapper — drop it. Otherwise we keep the 全体版 (it's the only PDF).
    has_body_only = any(not is_full and not law_only for _, _, is_full, law_only in cand)

    pdfs: list[tuple[str, bytes]] = []
    seen_hashes: set[str] = set()
    for absurl, _anchor, is_full, is_law_only in cand:
        if is_law_only:
            continue
        if is_full and has_body_only:
            continue
        pres = http.get(absurl)
        if pres is None:
            continue
        content_hash = hashlib.sha256(pres.content).hexdigest()
        if content_hash in seen_hashes:
            continue
        seen_hashes.add(content_hash)
        pdfs.append((absurl, pres.content))
    return page_text, pdfs


def parse_detail_pdf_for_entities(
    pdf_bytes: bytes,
    *,
    pdf_url: str,
    page_title: str,
    issuance_date_iso: str | None,
    title_kind: str,
) -> list[EnfRow]:
    """Parse a 報道発表 detail PDF into one or more EnfRows.

    Two patterns:
      A) 一覧 PDF (一覧 / 別紙) with table: 番号 / 許可番号 / 許可年月日 /
         事業者名 / 代表者 / 所在地. Multiple businesses, one disposition date.
      B) 単独 PDF: page text contains 名称, 所在地, 許可番号, 処分日.
         One business per PDF.
    """
    out: list[EnfRow] = []
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            full_text = "\n".join(p.extract_text() or "" for p in pdf.pages)
        full_text_norm = _normalize(full_text)

        # Determine disposition date (try title's iso first, then explicit
        # 処分日 / 取消し日 / 命令日 keywords in the body text. Avoid the bare
        # _wareki_to_iso(full_text_norm) fallback because old 一覧 PDFs include
        # 許可年月日 columns from the 1990s/2000s that mis-anchor the date.)
        disp_date = issuance_date_iso
        if not disp_date:
            m_disp = re.search(
                r"(?:許可(?:の)?取消し?(?:年月日)?|事業停止命令(?:日|年月日)?|改善命令(?:日|年月日)?|処分日|公表日)\s*[:：]?\s*"
                r"((?:令和|平成)\s*(?:元|[0-9０-９]+)\s*年\s*[0-9０-９]+\s*月\s*[0-9０-９]+\s*日)",
                full_text_norm,
            )
            if m_disp:
                disp_date = _wareki_to_iso(m_disp.group(1))

        # Determine related_law_ref
        related_law = _infer_law_basis(title_kind, full_text_norm)

        # Path A: 一覧 PDF (別紙 / 別添「一覧」)
        # Look for table with header row containing 名称 + 許可番号 etc.
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages:
                ptext = page.extract_text() or ""
                tables = page.extract_tables() or []
                for table in tables:
                    if not table or len(table) < 2:
                        continue
                    header = [_normalize(c or "") for c in table[0]]
                    # 一覧 PDF header: 番号 | 許可番号 | 許可年月日 | 事業者の名称 | 代表者 | 所在地
                    is_list_haken = any(
                        (
                            "派遣事業者" in h
                            or "事業者の名称" in h
                            or "事業者の名称" in h
                            or "派遣事業主" in h
                            or "派遣元事業主" in h
                        )
                        for h in header
                    ) and any("許可番号" in h for h in header)
                    is_list_shokai = any(
                        "事業者の名称" in h or "事業主" in h for h in header
                    ) and any("許可番号" in h for h in header)
                    if not is_list_haken and not is_list_shokai:
                        continue
                    # find name / perm / address columns
                    name_idx = perm_idx = addr_idx = -1
                    for i, h in enumerate(header):
                        if "名称" in h or "事業者" in h:
                            if name_idx == -1:
                                name_idx = i
                        elif "許可番号" in h:
                            perm_idx = i
                        elif "所在地" in h:
                            addr_idx = i
                    if name_idx < 0 or perm_idx < 0:
                        continue
                    # Disposition date: prefer the press-release page-level
                    # date (passed as issuance_date_iso → disp_date). Only fall
                    # back to scanning the PDF text when the title gave nothing,
                    # because 一覧 PDFs commonly contain 許可年月日 columns from
                    # the 1990s/2000s that would mis-anchor the disposition.
                    page_disp_iso = disp_date
                    if not page_disp_iso:
                        # Look for explicit 取消し / 命令 dates first.
                        m_disp = re.search(
                            r"(?:許可(?:の)?取消し?(?:年月日)?|事業停止命令(?:日|年月日)?|改善命令(?:日|年月日)?|処分日|公表日)\s*[:：]?\s*"
                            r"((?:令和|平成)\s*(?:元|[0-9０-９]+)\s*年\s*[0-9０-９]+\s*月\s*[0-9０-９]+\s*日)",
                            ptext,
                        )
                        if m_disp:
                            page_disp_iso = _wareki_to_iso(m_disp.group(1))
                        if not page_disp_iso:
                            page_disp_iso = _wareki_to_iso(ptext)
                    if not page_disp_iso:
                        continue
                    for raw in table[1:]:
                        cells = [_normalize((c or "").replace("\n", " ")) for c in raw]
                        if not cells or len(cells) <= max(name_idx, perm_idx):
                            continue
                        name = cells[name_idx]
                        if not _is_valid_target_name(name) or len(name) > 200:
                            continue
                        perm = cells[perm_idx] if perm_idx < len(cells) else ""
                        addr = cells[addr_idx] if 0 <= addr_idx < len(cells) else None
                        perm_haken = _extract_haken_perm(perm)
                        perm_shokai = _extract_shokai_perm(perm)
                        bureau_label = _bureau_from_haken_num(perm)
                        authority = f"厚生労働省 {bureau_label}" if bureau_label else "厚生労働省"
                        out.append(
                            EnfRow(
                                target_name=name,
                                issuance_date=page_disp_iso,
                                enforcement_kind=title_kind,
                                issuing_authority=authority,
                                related_law_ref=related_law,
                                location=addr,
                                permit_number_haken=perm_haken,
                                permit_number_shokai=perm_shokai,
                                reason_summary=(
                                    f"{page_title}（一覧 #{cells[0] if cells else ''}）"
                                )[:600],
                                source_url=pdf_url,
                                source_topic="mhlw_houdou_list",
                            )
                        )

        # Path B: 単独 PDF — extract single entity from full_text_norm.
        # Trigger only if Path A returned nothing for this PDF.
        if not out:
            single = _parse_single_business_pdf(
                full_text_norm,
                pdf_url=pdf_url,
                page_title=page_title,
                disp_date=disp_date,
                title_kind=title_kind,
                related_law=related_law,
            )
            out.extend(single)
    except Exception as exc:  # noqa: BLE001
        _LOG.warning("detail PDF parse failed url=%s err=%s", pdf_url, exc)
    return out


def _infer_law_basis(title_kind: str, body_text: str) -> str:
    """Return a related_law_ref hint based on title kind + body text."""
    if "労働者派遣法第14条第１項第１号" in body_text or "労働者派遣法第14条第1項第1号" in body_text:
        ref = "労働者派遣法第14条第1項第1号"
    elif (
        "労働者派遣法第14条第１項第４号" in body_text or "労働者派遣法第14条第1項第4号" in body_text
    ):
        ref = "労働者派遣法第14条第1項第4号"
    elif (
        "労働者派遣法第14条第１項第３号" in body_text or "労働者派遣法第14条第1項第3号" in body_text
    ):
        ref = "労働者派遣法第14条第1項第3号"
    elif "労働者派遣法第14条第２項" in body_text or "労働者派遣法第14条第2項" in body_text:
        ref = "労働者派遣法第14条第2項"
    elif "労働者派遣法第49条" in body_text:
        ref = "労働者派遣法第49条第1項"
    elif "職業安定法第32条の９第１項" in body_text or "職業安定法第32条の9第1項" in body_text:
        ref = "職業安定法第32条の9第1項"
    elif "職業安定法第32条の９第２項" in body_text or "職業安定法第32条の9第2項" in body_text:
        ref = "職業安定法第32条の9第2項"
    elif "職業安定法第48条" in body_text:
        ref = "職業安定法第48条の3"
    else:
        # Fallback by kind
        if title_kind == "license_revoke":
            ref = "労働者派遣法第14条第1項" if "派遣" in body_text else "職業安定法第32条の9第1項"
        elif title_kind == "contract_suspend":
            ref = "労働者派遣法第14条第2項"
        elif title_kind == "business_improvement":
            ref = "労働者派遣法第49条第1項"
        elif title_kind == "investigation":
            # 告発: 派遣法 → 第59条 / 職安法 → 第63条
            if "労働者派遣法" in body_text:
                ref = "労働者派遣法第59条"
            elif "職業安定法" in body_text:
                ref = "職業安定法第63条"
            else:
                ref = "労働者派遣法（告発）"
        else:
            ref = "労働者派遣法"
    return ref


_NAME_RE = re.compile(
    # Modern form: "名 称 株式会社XXX"
    # Legacy form: "事業主名 株式会社XXX" (used 2013-2018 PDFs)
    # Optional leading numbering like "（１）" or "(1)"
    r"(?:名\s*[\s　]*称|事業主名|事業者の名称|事業主の名称|商号又は名称)"
    r"[\s　]*[:：]?\s*([^\n　]+?)"
    r"(?=\s*代表|\s*所在|\s*許可|\s*届出|\s*事業の|\s*事業所|$)"
)
_LOC_RE = re.compile(
    r"(?:所\s*[\s　]*在\s*[\s　]*地|事業主の所在地|事業者の所在地)"
    r"[\s　]*[:：]?\s*([^\n]+?)"
    r"(?=\s*許可|\s*代表|\s*届出|\s*事業所|$)"
)
_PERM_DATE_RE = re.compile(r"許\s*可\s*年\s*月\s*日[\s　]*[:：]?\s*([^\n]+)")
_PERM_NUM_RE = re.compile(r"許\s*可\s*番\s*号[\s　]*[:：]?\s*([^\n]+?)(?=\s|$)")


def _parse_single_business_pdf(
    full_text: str,
    *,
    pdf_url: str,
    page_title: str,
    disp_date: str | None,
    title_kind: str,
    related_law: str,
) -> list[EnfRow]:
    """Extract a single-business EnfRow from a 単独 PDF body text."""
    out: list[EnfRow] = []
    name = None
    location = None
    perm_haken = None
    perm_shokai = None
    # 名称 → matches the "名 称 株式会社XXX" / "名称 XXX" patterns
    nm = _NAME_RE.search(full_text)
    if nm:
        candidate = _normalize(nm.group(1)).strip()
        # filter out artifacts (handle spaced forms like "代 表 者 職 氏 名")
        candidate = re.sub(r"代\s*表\s*者\s*職\s*氏\s*名.*$", "", candidate).strip()
        candidate = re.sub(r"代\s*表\s*者.*$", "", candidate).strip()
        candidate = re.sub(r"所\s*在\s*地.*$", "", candidate).strip()
        candidate = re.sub(r"許\s*可\s*番\s*号.*$", "", candidate).strip()
        candidate = re.sub(r"許\s*可\s*年\s*月\s*日.*$", "", candidate).strip()
        # strip trailing legal-numbering markers like " (2)" / " (3)"
        candidate = re.sub(r"\s*\(\d+\)\s*$", "", candidate).strip()
        # strip dangling open-paren artifact at the end
        candidate = re.sub(r"\s*\($", "", candidate).strip()
        # collapse internal redundant whitespace
        candidate = re.sub(r"\s+", " ", candidate).strip()
        # reject if the entire string is a header label, numbering, date,
        # or other PDF structural fragment.
        if not _is_valid_target_name(candidate):
            candidate = ""
        if candidate and len(candidate) <= 200:
            name = candidate
    lm = _LOC_RE.search(full_text)
    if lm:
        candidate = _normalize(lm.group(1)).strip()
        # filter out artifacts (handle spaced forms)
        candidate = re.sub(r"許\s*可\s*年\s*月\s*日.*$", "", candidate).strip()
        candidate = re.sub(r"許\s*可\s*番\s*号.*$", "", candidate).strip()
        candidate = re.sub(r"代\s*表\s*者.*$", "", candidate).strip()
        # strip trailing " (4)" 等
        candidate = re.sub(r"\s*\(\d+\)\s*$", "", candidate).strip()
        candidate = re.sub(r"\s+", " ", candidate).strip()
        if candidate and len(candidate) <= 300:
            location = candidate
    # Extract any 派NN-NNNNNN / NN-ユ-NNNNNN found anywhere
    perm_haken = _extract_haken_perm(full_text)
    perm_shokai = _extract_shokai_perm(full_text)
    if not name:
        return []
    if not disp_date:
        return []
    bureau_label = _bureau_from_haken_num(perm_haken or perm_shokai)
    authority = f"厚生労働省 {bureau_label}" if bureau_label else "厚生労働省"

    # Reason summary: 1st sentence of '処分理由' block
    reason = None
    rm = re.search(
        r"処\s*分\s*理\s*由(.+?)(?=処\s*分\s*内\s*容|別\s*紙|別\s*添|$)", full_text, re.DOTALL
    )
    if rm:
        snippet = re.split(r"。", _normalize(rm.group(1)), maxsplit=2)
        if snippet:
            reason = ("。".join(snippet[:2]) + "。")[:1200]
    if not reason:
        reason = page_title[:600]

    out.append(
        EnfRow(
            target_name=name,
            issuance_date=disp_date,
            enforcement_kind=title_kind,
            issuing_authority=authority,
            related_law_ref=related_law,
            location=location,
            permit_number_haken=perm_haken,
            permit_number_shokai=perm_shokai,
            reason_summary=reason,
            source_url=pdf_url,
            source_topic="mhlw_houdou_single",
        )
    )
    return out


# ---------------------------------------------------------------------------
# DB layer
# ---------------------------------------------------------------------------


def ensure_tables(conn: sqlite3.Connection) -> None:
    for tbl in ("am_entities", "am_enforcement_detail", "am_authority"):
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (tbl,),
        ).fetchone()
        if not row:
            raise SystemExit(f"missing table '{tbl}' — apply migrations first")


def ensure_authority(cur: sqlite3.Cursor, *, label: str) -> str:
    """Ensure am_authority row exists for the given issuing_authority label.

    For '厚生労働省' use authority:mhlw-shokuan (既存)。
    For '厚生労働省 {pref}労働局' use authority:generic-pref-labor-bureau
    (already exists as a pseudo umbrella) — we don't try to mint per-prefecture
    canonical_id since am_authority schema treats prefectures as 'prefecture'
    level, not bureau-of-MHLW level. The label in am_enforcement_detail.
    issuing_authority is what users see.
    """
    if label == "厚生労働省":
        return "authority:mhlw-shokuan"
    if "労働局" in label:
        # 既に am_authority に 'authority:generic-pref-labor-bureau' あり
        return "authority:generic-pref-labor-bureau"
    return "authority:mhlw"


def existing_dedup_keys(cur: sqlite3.Cursor) -> set[tuple[str, str]]:
    """Pre-load (target_name, issuance_date) for fast in-memory dedup."""
    cur.execute(
        "SELECT target_name, issuance_date FROM am_enforcement_detail "
        "WHERE issuing_authority LIKE '厚生労働省%'"
    )
    out: set[tuple[str, str]] = set()
    for n, d in cur.fetchall():
        if n and d:
            out.add((_normalize(n), d))
    return out


def existing_canonical_ids(cur: sqlite3.Cursor) -> set[str]:
    cur.execute(
        "SELECT canonical_id FROM am_entities "
        "WHERE record_kind='enforcement' "
        "AND source_topic LIKE 'mhlw_haken%' OR source_topic LIKE 'mhlw_shokai%' "
        "OR source_topic LIKE 'mhlw_houdou%'"
    )
    return {row[0] for row in cur.fetchall()}


def build_canonical_id(row: EnfRow) -> str:
    name_slug = _slugify_jp(row.target_name, max_len=24)
    iso = row.issuance_date.replace("-", "")
    h = _slug8(row.target_name, row.issuance_date)
    return f"enforcement:mhlw-haken-shokai:{iso}:{name_slug}:{h}"[:255]


def insert_one(
    cur: sqlite3.Cursor,
    row: EnfRow,
    *,
    now_iso: str,
) -> bool:
    canonical_id = build_canonical_id(row)
    authority_canonical = ensure_authority(cur, label=row.issuing_authority)
    raw = {
        "source": "mhlw_haken_shokai_admin_action",
        "target_name": row.target_name,
        "location": row.location,
        "issuance_date": row.issuance_date,
        "enforcement_kind": row.enforcement_kind,
        "issuing_authority": row.issuing_authority,
        "related_law_ref": row.related_law_ref,
        "permit_number_haken": row.permit_number_haken,
        "permit_number_shokai": row.permit_number_shokai,
        "suspend_period": row.suspend_period,
        "reason_summary": row.reason_summary,
        "source_url": row.source_url,
        "source_topic": row.source_topic,
        "license": "政府機関の著作物（出典明記で転載引用可）",
        "attribution": "出典: 厚生労働省ウェブサイト (https://www.mhlw.go.jp/)",
        "fetched_at": now_iso,
    }
    primary_name = (
        f"{row.target_name} ({row.issuance_date}) - {row.issuing_authority} {row.enforcement_kind}"
    )[:500]
    cur.execute(
        """INSERT OR IGNORE INTO am_entities
               (canonical_id, record_kind, source_topic, source_record_index,
                primary_name, authority_canonical, confidence, source_url,
                source_url_domain, fetched_at, raw_json,
                canonical_status, citation_status)
           VALUES (?, 'enforcement', ?, NULL, ?, ?, ?, ?, ?, ?, ?,
                   'active', 'ok')""",
        (
            canonical_id,
            row.source_topic,
            primary_name,
            authority_canonical,
            0.92,
            row.source_url,
            "mhlw.go.jp",
            now_iso,
            json.dumps(raw, ensure_ascii=False),
        ),
    )
    if cur.rowcount == 0:
        return False
    cur.execute(
        """INSERT INTO am_enforcement_detail
               (entity_id, houjin_bangou, target_name, enforcement_kind,
                issuing_authority, issuance_date, exclusion_start, exclusion_end,
                reason_summary, related_law_ref, amount_yen,
                source_url, source_fetched_at)
           VALUES (?, NULL, ?, ?, ?, ?, NULL, NULL, ?, ?, NULL, ?, ?)""",
        (
            canonical_id,
            row.target_name[:255],
            row.enforcement_kind,
            row.issuing_authority[:255],
            row.issuance_date,
            (row.reason_summary or "")[:2000] or None,
            row.related_law_ref[:255] if row.related_law_ref else None,
            row.source_url,
            now_iso,
        ),
    )
    return True


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument(
        "--limit-detail", type=int, default=None, help="cap number of detail pages to walk (debug)"
    )
    ap.add_argument("--no-master", action="store_true", help="skip master haken/shokai PDFs")
    ap.add_argument("--no-houdou", action="store_true", help="skip houdou press-release walk")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("-v", "--verbose", action="store_true")
    return ap.parse_args(argv)


def run(args: argparse.Namespace) -> int:
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    # Silence pdfminer / pdfplumber chatter even when our logger is DEBUG.
    for noisy in (
        "pdfminer",
        "pdfminer.pdfinterp",
        "pdfminer.pdfpage",
        "pdfminer.cmapdb",
        "pdfminer.converter",
        "pdfminer.layout",
        "pdfplumber",
        "PIL",
        "urllib3",
    ):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    now_iso = datetime.now(tz=UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
    http = HttpClient()

    all_rows: list[EnfRow] = []

    # --- Phase 1: master haken/shokai PDFs ---
    if not args.no_master:
        for entry in MASTER_PDFS:
            url = entry["url"]
            label = entry["label"]
            kind = entry["law_kind"]
            _LOG.info("[master] fetching %s (%s)", label, url)
            resp = http.get(url)
            if resp is None:
                _LOG.warning("[master] fetch failed: %s", url)
                continue
            if kind == "haken":
                rows = parse_master_haken_pdf(resp.content, url)
            else:
                rows = parse_master_shokai_pdf(resp.content, url)
            _LOG.info("[master] %s → %d rows", kind, len(rows))
            all_rows.extend(rows)

    # --- Phase 2: houdou press-release walk ---
    if not args.no_houdou:
        _LOG.info("[index] fetching syokuan.html")
        resp = http.get(INDEX_URL)
        if resp is None:
            _LOG.warning("[index] fetch failed")
            entries: list[PressEntry] = []
        else:
            entries = parse_index_pages(resp.text)
        _LOG.info("[index] candidate detail pages: %d", len(entries))
        if args.limit_detail is not None:
            entries = entries[: args.limit_detail]
        for i, entry in enumerate(entries):
            _LOG.info("[detail %d/%d] %s", i + 1, len(entries), entry.detail_url)
            page_text, pdfs = fetch_detail_pdfs(http, entry.detail_url)
            if not pdfs:
                _LOG.debug("  no PDFs at %s", entry.detail_url)
                continue
            for pdf_url, pdf_bytes in pdfs:
                rows = parse_detail_pdf_for_entities(
                    pdf_bytes,
                    pdf_url=pdf_url,
                    page_title=entry.title,
                    issuance_date_iso=entry.issuance_date,
                    title_kind=entry.enforcement_kind,
                )
                if rows:
                    _LOG.info("  pdf=%s rows=%d", pdf_url.rsplit("/", 1)[-1], len(rows))
                all_rows.extend(rows)

    _LOG.info("phase summary: total parsed rows = %d", len(all_rows))

    if args.dry_run or not all_rows:
        # Print all rows and breakdowns
        for r in all_rows:
            _LOG.info(
                "  CAND: %s | %s | %s | %s | %s",
                r.issuance_date,
                r.target_name[:40],
                r.enforcement_kind,
                r.issuing_authority,
                r.related_law_ref,
            )
        from collections import Counter

        by_kind = Counter(r.enforcement_kind for r in all_rows)
        by_auth = Counter(r.issuing_authority for r in all_rows)
        _LOG.info("dry-run: would attempt %d inserts", len(all_rows))
        _LOG.info("by enforcement_kind: %s", dict(by_kind))
        _LOG.info("by issuing_authority: %s", dict(by_auth))
        if args.dry_run:
            return 0

    # --- Phase 3: DB write ---
    if not args.db.exists():
        _LOG.error("autonomath.db missing: %s", args.db)
        return 2

    con = sqlite3.connect(str(args.db), timeout=300.0)
    try:
        con.execute("PRAGMA busy_timeout=300000")
        con.execute("PRAGMA foreign_keys=ON")
        ensure_tables(con)
        cur = con.cursor()
        cur.execute("BEGIN IMMEDIATE")
        existing_keys = existing_dedup_keys(cur)
        existing_ids = existing_canonical_ids(cur)
        con.commit()
    except sqlite3.Error as exc:
        _LOG.error("DB init failed: %s", exc)
        with contextlib.suppress(sqlite3.Error):
            con.close()
        return 2

    inserted = 0
    skipped_dup_db = 0
    skipped_dup_id = 0
    skipped_dup_batch = 0
    skipped_invalid = 0
    breakdown_kind: dict[str, int] = {}
    breakdown_authority: dict[str, int] = {}
    breakdown_law: dict[str, int] = {}

    batch_keys: set[tuple[str, str]] = set()
    pre_count = con.execute(
        "SELECT COUNT(*) FROM am_enforcement_detail "
        "WHERE related_law_ref LIKE '%派遣%' OR related_law_ref LIKE '%職業安定%'"
    ).fetchone()[0]
    pre_total = con.execute("SELECT COUNT(*) FROM am_enforcement_detail").fetchone()[0]

    # Batch commit every 50 rows
    batch_size = 50
    pending = 0

    try:
        cur.execute("BEGIN IMMEDIATE")
    except sqlite3.Error as exc:
        _LOG.error("DB BEGIN failed: %s", exc)
        with contextlib.suppress(sqlite3.Error):
            con.close()
        return 2

    for r in all_rows:
        if not r.target_name or not r.issuance_date:
            skipped_invalid += 1
            continue
        nm = _normalize(r.target_name)
        key = (nm, r.issuance_date)
        if key in existing_keys:
            skipped_dup_db += 1
            continue
        if key in batch_keys:
            skipped_dup_batch += 1
            continue
        cid = build_canonical_id(r)
        if cid in existing_ids:
            skipped_dup_id += 1
            continue
        try:
            ok = insert_one(cur, r, now_iso=now_iso)
        except sqlite3.IntegrityError as exc:
            _LOG.warning("integrity err for %s: %s", r.target_name, exc)
            continue
        except sqlite3.Error as exc:
            _LOG.error("DB error %s: %s", r.target_name, exc)
            continue
        if ok:
            inserted += 1
            batch_keys.add(key)
            existing_ids.add(cid)
            breakdown_kind[r.enforcement_kind] = breakdown_kind.get(r.enforcement_kind, 0) + 1
            breakdown_authority[r.issuing_authority] = (
                breakdown_authority.get(r.issuing_authority, 0) + 1
            )
            short_law = r.related_law_ref.split("第")[0] if r.related_law_ref else "(none)"
            breakdown_law[short_law] = breakdown_law.get(short_law, 0) + 1
            pending += 1
            if pending >= batch_size:
                try:
                    con.commit()
                    cur.execute("BEGIN IMMEDIATE")
                    pending = 0
                except sqlite3.Error as exc:
                    _LOG.error("commit failed: %s", exc)
                    return 2
        else:
            skipped_dup_id += 1

    try:
        con.commit()
    except sqlite3.Error as exc:
        _LOG.error("final commit failed: %s", exc)

    # Counts after
    post_count = con.execute(
        "SELECT COUNT(*) FROM am_enforcement_detail "
        "WHERE related_law_ref LIKE '%派遣%' OR related_law_ref LIKE '%職業安定%'"
    ).fetchone()[0]
    post_total = con.execute("SELECT COUNT(*) FROM am_enforcement_detail").fetchone()[0]
    with contextlib.suppress(sqlite3.Error):
        con.close()

    _LOG.info(
        "done parsed=%d inserted=%d dup_db=%d dup_id=%d dup_batch=%d invalid=%d",
        len(all_rows),
        inserted,
        skipped_dup_db,
        skipped_dup_id,
        skipped_dup_batch,
        skipped_invalid,
    )

    print(
        json.dumps(
            {
                "inserted": inserted,
                "parsed": len(all_rows),
                "skipped_dup_db": skipped_dup_db,
                "skipped_dup_id": skipped_dup_id,
                "skipped_dup_batch": skipped_dup_batch,
                "skipped_invalid": skipped_invalid,
                "pre_haken_shokai_count": pre_count,
                "post_haken_shokai_count": post_count,
                "delta_haken_shokai": post_count - pre_count,
                "pre_am_enforcement_total": pre_total,
                "post_am_enforcement_total": post_total,
                "breakdown_by_kind": breakdown_kind,
                "breakdown_by_authority": breakdown_authority,
                "breakdown_by_law_short": breakdown_law,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if inserted >= 0 else 1


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
