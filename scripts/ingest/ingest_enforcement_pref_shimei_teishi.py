#!/usr/bin/env python3
"""Ingest 都道府県 (+ 政令指定都市) 指名停止 措置業者 一覧 into
``am_entities`` + ``am_enforcement_detail``.

Sources (primary only — aggregators BANNED):
    pref.{slug}.jp / pref.{slug}.lg.jp
    metro.tokyo.lg.jp / city.{slug}.lg.jp

Existing am_enforcement_detail prefecture rows are JBAUDIT 会計検査院 references
(report.jbaudit.go.jp/...) — those are *not* 都道府県発 指名停止 measures.
This ingest creates an entirely new layer with `enforcement_kind='contract_suspend'`
and `issuing_authority='{prefecture name}'`.

Strategy:
- Curated SOURCES table per prefecture (URL + format hint + parser hint).
- Format-aware parsers:
    pdf  -> pdftotext -layout, regex-based row extraction
    xls  -> xlrd (CDF binary)
    xlsx -> openpyxl
    html -> regex-based row extraction (HTML tables)
- Common shape: one row = (target_name, period_start, period_end,
  reason_summary, source_url).

Schema target (autonomath.db):
  * am_entities(canonical_id = 'enforcement:pref:<slug>:<sha1[:16]>',
                record_kind='enforcement', source_topic='pref_shimei_teishi',
                primary_name=target_name, source_url, raw_json)
  * am_enforcement_detail(entity_id, target_name,
                          enforcement_kind='contract_suspend',
                          issuing_authority='{県/都/府/道}', issuance_date,
                          exclusion_start, exclusion_end, reason_summary,
                          source_url)

dedup key: (target_name, issuance_date, issuing_authority).
  When a 業者 has multiple rows on the same date in the same authority's list,
  we keep the first.

CLI:
    python scripts/ingest/ingest_enforcement_pref_shimei_teishi.py \\
        --db autonomath.db \\
        [--prefectures hokkaido,aichi,...]    # default: all curated
        [--limit-per-source 200]              # smoke-test cap
        [--dry-run]
        [--log-file analysis_wave18/data_collection_log/2026-04-25.md]

Exit codes:
    0 success
    1 network / parse failure (script-level)
    2 DB lock / missing schema
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import logging
import re
import sqlite3
import subprocess
import sys
import time
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from scripts.lib.http import HttpClient  # noqa: E402

try:
    import xlrd  # type: ignore
except ImportError:  # pragma: no cover
    xlrd = None  # type: ignore

try:
    import openpyxl  # type: ignore
except ImportError:  # pragma: no cover
    openpyxl = None  # type: ignore


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_LOG = logging.getLogger("autonomath.ingest.enforcement_pref")

DEFAULT_DB = REPO_ROOT / "autonomath.db"
PDF_MAX_BYTES = 20 * 1024 * 1024  # 20MB cap for PDFs
HTML_MAX_BYTES = 4 * 1024 * 1024


# ---------------------------------------------------------------------------
# Source definitions
# ---------------------------------------------------------------------------


@dataclass
class Source:
    prefecture: str  # 北海道 / 東京都 / 大阪府 / 愛知県 / ...
    slug: str  # hokkaido / tokyo / osaka / aichi / ...
    url: str
    fmt: str  # 'pdf' | 'xls' | 'xlsx' | 'html'
    parser: str  # parser hint; e.g. 'aichi_pdf' | 'hokkaido_xls' | 'generic_pdf'
    note: str = ""


# Curated source list. URL discovery is via primary-source 公式サイト;
# aggregators are banned (no noukaweb / hojyokin-portal / wikipedia).
SOURCES: list[Source] = [
    # ===== XLS =====
    Source(
        "北海道",
        "hokkaido",
        "https://www.pref.hokkaido.lg.jp/fs/1/3/1/2/8/4/4/3/_/shimeiteishi_R8.4.22.xls",
        "xls",
        "hokkaido_xls",
    ),
    # ===== PDF: Aichi-style (序号 / 名 / 所在地 / 自 / 至 / 月数 / 理由 / 発注機関 / 条項) =====
    Source(
        "愛知県",
        "aichi",
        "https://www.pref.aichi.jp/uploaded/attachment/610657.pdf",
        "pdf",
        "aichi_pdf",
        note="令和7年度",
    ),
    Source(
        "愛知県",
        "aichi",
        "https://www.pref.aichi.jp/uploaded/attachment/562153.pdf",
        "pdf",
        "aichi_pdf",
        note="令和6年度",
    ),
    Source(
        "愛知県",
        "aichi",
        "https://www.pref.aichi.jp/uploaded/attachment/614388.pdf",
        "pdf",
        "aichi_pdf",
        note="令和8年度",
    ),
    # ===== PDF: Chiba-style (№ / 理由 / 業者名 / 措置期間 / 決定年月日 / 適用条項 / 概要) =====
    Source(
        "千葉県",
        "chiba",
        "https://www.pref.chiba.lg.jp/kanzai/nyuu-kei/buppin-itaku/sankashikaku/documents/r07-bi-simeiteisi.pdf",
        "pdf",
        "chiba_pdf",
        note="令和7年度 物品",
    ),
    Source(
        "千葉県",
        "chiba",
        "https://www.pref.chiba.lg.jp/kanzai/nyuu-kei/buppin-itaku/sankashikaku/documents/r06-bi-simeiteisi.pdf",
        "pdf",
        "chiba_pdf",
        note="令和6年度 物品",
    ),
    Source(
        "千葉県",
        "chiba",
        "https://www.pref.chiba.lg.jp/kanzai/nyuu-kei/buppin-itaku/sankashikaku/documents/r04-bi-simeiteisi.pdf",
        "pdf",
        "chiba_pdf",
        note="令和4年度 物品",
    ),
    # ===== PDF: Saitama-style (業者名 / 許可番号 / 業者番号 / 所在地 / 期間 / 理由) =====
    Source(
        "埼玉県",
        "saitama",
        "https://www.pref.saitama.lg.jp/documents/27690/hp-list080422.pdf",
        "pdf",
        "saitama_pdf",
        note="現在分",
    ),
    # ===== PDF: Niigata-style (名簿区分 / 許可番号 / 業者名 / 所在地 / 期間 / 理由 / 条項) =====
    Source(
        "新潟県",
        "niigata",
        "https://www.pref.niigata.lg.jp/uploaded/attachment/485171.pdf",
        "pdf",
        "niigata_pdf",
        note="令和7年度 1",
    ),
    Source(
        "新潟県",
        "niigata",
        "https://www.pref.niigata.lg.jp/uploaded/attachment/473552.pdf",
        "pdf",
        "niigata_pdf",
        note="令和7年度 2",
    ),
    Source(
        "新潟県",
        "niigata",
        "https://www.pref.niigata.lg.jp/uploaded/attachment/464589.pdf",
        "pdf",
        "niigata_pdf",
        note="令和7年度 3",
    ),
    Source(
        "新潟県",
        "niigata",
        "https://www.pref.niigata.lg.jp/uploaded/attachment/437080.pdf",
        "pdf",
        "niigata_pdf",
        note="令和6年度 1",
    ),
    Source(
        "新潟県",
        "niigata",
        "https://www.pref.niigata.lg.jp/uploaded/attachment/401306.pdf",
        "pdf",
        "niigata_pdf",
        note="令和6年度 2",
    ),
    Source(
        "新潟県",
        "niigata",
        "https://www.pref.niigata.lg.jp/uploaded/attachment/429420.pdf",
        "pdf",
        "niigata_pdf",
        note="令和6年度 3",
    ),
    # ===== PDF: Miyagi-style =====
    Source(
        "宮城県",
        "miyagi",
        "https://www.pref.miyagi.jp/documents/14009/st_r80219.pdf",
        "pdf",
        "miyagi_pdf",
    ),
    # ===== PDF: Kyoto-style (主たる営業所の所在地 / 商号 / 期間 / 理由 / 条項) =====
    Source(
        "京都府",
        "kyoto",
        "https://www.pref.kyoto.jp/shingikai/nyusatu-01/documents/r706siryou2-5.pdf",
        "pdf",
        "kyoto_pdf",
        note="工事 R7",
    ),
    Source(
        "京都府",
        "kyoto",
        "https://www.pref.kyoto.jp/shingikai/nyusatu-01/documents/r61024kannsi1-5.pdf",
        "pdf",
        "kyoto_pdf",
        note="工事 R6",
    ),
    # ===== HTML: Shizuoka-style (table 内に直接) — fallback to generic HTML parser =====
    Source(
        "静岡県",
        "shizuoka",
        "https://www.pref.shizuoka.jp/kensei/nyusatsukobai/nyusatsukoji/1003485/1071495.html",
        "html",
        "gunma_html",
        note="令和7年度",
    ),
    Source(
        "静岡県",
        "shizuoka",
        "https://www.pref.shizuoka.jp/kensei/nyusatsukobai/nyusatsukoji/1003485/1063417.html",
        "html",
        "gunma_html",
        note="令和6年度",
    ),
    Source(
        "静岡県",
        "shizuoka",
        "https://www.pref.shizuoka.jp/kensei/nyusatsukobai/nyusatsukoji/1003485/1053625.html",
        "html",
        "gunma_html",
        note="令和5年度",
    ),
    Source(
        "静岡県",
        "shizuoka",
        "https://www.pref.shizuoka.jp/kensei/nyusatsukobai/nyusatsukoji/1003485/1028935.html",
        "html",
        "gunma_html",
        note="令和4年度",
    ),
    Source(
        "静岡県",
        "shizuoka",
        "https://www.pref.shizuoka.jp/kensei/nyusatsukobai/nyusatsukoji/1003485/1028960.html",
        "html",
        "gunma_html",
        note="令和3年度",
    ),
    # ===== HTML: Gunma (proper <tr><td> tables) =====
    Source(
        "群馬県",
        "gunma",
        "https://www.pref.gunma.jp/site/nyuusatsu/640195.html",
        "html",
        "gunma_html",
        note="建設工事",
    ),
    Source(
        "群馬県",
        "gunma",
        "https://www.pref.gunma.jp/site/nyuusatsu/701418.html",
        "html",
        "gunma_html",
        note="物品・役務",
    ),
    # ===== HTML: Toyama (HTML embedded press release table) =====
    Source(
        "富山県",
        "toyama",
        "https://www.pref.toyama.jp/1500/sangyou/nyuusatsu/koukyoukouji/kj00018221/20260113shimeiteishi.html",
        "html",
        "gunma_html",
        note="令和8年1月13日",
    ),
    # ===== PDF: Iwate =====
    Source(
        "岩手県",
        "iwate",
        "https://www.pref.iwate.jp/_res/projects/default_project/_page_/001/010/559/20260424_simeiteisiitiran.pdf",
        "pdf",
        "kyoto_pdf",
        note="建設関連業務 R8.4.24",
    ),
    Source(
        "岩手県",
        "iwate",
        "https://www.pref.iwate.jp/_res/projects/default_project/_page_/001/010/644/simeiteisi080117.pdf",
        "pdf",
        "kyoto_pdf",
        note="物品 R8.1.17",
    ),
    # ===== PDF: Yamagata =====
    Source(
        "山形県",
        "yamagata",
        "https://www.pref.yamagata.jp/documents/3885/20260420_shimeiteishir8itiran.pdf",
        "pdf",
        "kyoto_pdf",
        note="建設工事 R8 一覧",
    ),
    Source(
        "山形県",
        "yamagata",
        "https://www.pref.yamagata.jp/documents/3885/20251225_shimeiteishiitiran.pdf",
        "pdf",
        "kyoto_pdf",
        note="建設工事 R7 一覧",
    ),
    # ===== PDF: Fukushima individual measure summaries =====
    Source(
        "福島県",
        "fukushima",
        "https://www.pref.fukushima.lg.jp/uploaded/attachment/726809.pdf",
        "pdf",
        "kyoto_pdf",
        note="運用状況一覧 R7.8月期",
    ),
    Source(
        "福島県",
        "fukushima",
        "https://www.pref.fukushima.lg.jp/uploaded/attachment/634460.pdf",
        "pdf",
        "kyoto_pdf",
        note="運用状況一覧 R6.2月期",
    ),
    Source(
        "福島県",
        "fukushima",
        "https://www.pref.fukushima.lg.jp/uploaded/attachment/613047.pdf",
        "pdf",
        "kyoto_pdf",
        note="運用状況一覧 R5.9月期",
    ),
    # ===== PDF: Mie =====
    Source(
        "三重県",
        "mie",
        "https://www.pref.mie.lg.jp/common/content/001250729.pdf",
        "pdf",
        "kyoto_pdf",
        note="現在 R8.4.8",
    ),
    # ===== PDF: Hyogo (個別 PDFs — many) =====
    Source(
        "兵庫県",
        "hyogo",
        "https://web.pref.hyogo.lg.jp/ks02/documents/nishiyo.pdf",
        "pdf",
        "kyoto_pdf",
        note="R8 nishiyo",
    ),
    Source(
        "兵庫県",
        "hyogo",
        "https://web.pref.hyogo.lg.jp/ks02/documents/daruma.pdf",
        "pdf",
        "kyoto_pdf",
        note="R8 daruma",
    ),
    Source(
        "兵庫県",
        "hyogo",
        "https://web.pref.hyogo.lg.jp/ks02/documents/water.pdf",
        "pdf",
        "kyoto_pdf",
        note="R8 water",
    ),
    Source(
        "兵庫県",
        "hyogo",
        "https://web.pref.hyogo.lg.jp/ks02/documents/kanayama.pdf",
        "pdf",
        "kyoto_pdf",
        note="R7 kanayama",
    ),
    Source(
        "兵庫県",
        "hyogo",
        "https://web.pref.hyogo.lg.jp/ks02/documents/shinsei.pdf",
        "pdf",
        "kyoto_pdf",
        note="R7 shinsei",
    ),
    Source(
        "兵庫県",
        "hyogo",
        "https://web.pref.hyogo.lg.jp/ks02/documents/daisin.pdf",
        "pdf",
        "kyoto_pdf",
        note="R7 daisin",
    ),
    Source(
        "兵庫県",
        "hyogo",
        "https://web.pref.hyogo.lg.jp/ks02/documents/terada.pdf",
        "pdf",
        "kyoto_pdf",
        note="R7 terada",
    ),
    Source(
        "兵庫県",
        "hyogo",
        "https://web.pref.hyogo.lg.jp/ks02/documents/maruto.pdf",
        "pdf",
        "kyoto_pdf",
        note="R7 maruto",
    ),
    # ===== PDF: Kochi =====
    Source(
        "高知県",
        "kochi",
        "https://www.pref.kochi.lg.jp/doc/shimeiteishi_list/file_contents/file_2026424134651_1.pdf",
        "pdf",
        "kyoto_pdf",
        note="2026.4.24",
    ),
    Source(
        "高知県",
        "kochi",
        "https://www.pref.kochi.lg.jp/doc/shimeiteishi_list/file_contents/file_202648319819_1.pdf",
        "pdf",
        "kyoto_pdf",
        note="2026.4.8",
    ),
    Source(
        "高知県",
        "kochi",
        "https://www.pref.kochi.lg.jp/doc/shimeiteishi_list/file_contents/file_20261132151453_1.pdf",
        "pdf",
        "kyoto_pdf",
        note="2026.1.13",
    ),
    Source(
        "高知県",
        "kochi",
        "https://www.pref.kochi.lg.jp/doc/shimeiteishi_list/file_contents/file_20251225420117_1.pdf",
        "pdf",
        "kyoto_pdf",
        note="2025.12.25",
    ),
    Source(
        "高知県",
        "kochi",
        "https://www.pref.kochi.lg.jp/doc/shimeiteishi_list/file_contents/file_20251216217183_1.pdf",
        "pdf",
        "kyoto_pdf",
        note="2025.12.16",
    ),
    Source(
        "高知県",
        "kochi",
        "https://www.pref.kochi.lg.jp/doc/shimeiteishi_list/file_contents/file_20251120418241_1.pdf",
        "pdf",
        "kyoto_pdf",
        note="2025.11.20",
    ),
    Source(
        "高知県",
        "kochi",
        "https://www.pref.kochi.lg.jp/doc/shimeiteishi_list/file_contents/file_202511182174432_1.pdf",
        "pdf",
        "kyoto_pdf",
        note="2025.11.18",
    ),
    Source(
        "高知県",
        "kochi",
        "https://www.pref.kochi.lg.jp/doc/shimeiteishi_list/file_contents/file_202510315103039_1.pdf",
        "pdf",
        "kyoto_pdf",
        note="2025.10.31",
    ),
    Source(
        "高知県",
        "kochi",
        "https://www.pref.kochi.lg.jp/doc/shimeiteishi_list/file_contents/file_20251014293017_1.pdf",
        "pdf",
        "kyoto_pdf",
        note="2025.10.14",
    ),
    Source(
        "高知県",
        "kochi",
        "https://www.pref.kochi.lg.jp/doc/shimeiteishi_list/file_contents/file_2025108391239_1.pdf",
        "pdf",
        "kyoto_pdf",
        note="2025.10.8",
    ),
    Source(
        "高知県",
        "kochi",
        "https://www.pref.kochi.lg.jp/doc/shimeiteishi_list/file_contents/file_2025102419018_1.pdf",
        "pdf",
        "kyoto_pdf",
        note="2025.10.24",
    ),
    Source(
        "高知県",
        "kochi",
        "https://www.pref.kochi.lg.jp/doc/shimeiteishi_list/file_contents/file_20259254212532_1.pdf",
        "pdf",
        "kyoto_pdf",
        note="2025.9.25",
    ),
    Source(
        "高知県",
        "kochi",
        "https://www.pref.kochi.lg.jp/doc/shimeiteishi_list/file_contents/file_20258192103740_1.pdf",
        "pdf",
        "kyoto_pdf",
        note="2025.8.19",
    ),
    Source(
        "高知県",
        "kochi",
        "https://www.pref.kochi.lg.jp/doc/shimeiteishi_list/file_contents/file_20257163103041_1.pdf",
        "pdf",
        "kyoto_pdf",
        note="2025.7.16",
    ),
    Source(
        "高知県",
        "kochi",
        "https://www.pref.kochi.lg.jp/doc/shimeiteishi_list/file_contents/file_202579383636_1.pdf",
        "pdf",
        "kyoto_pdf",
        note="2025.7.9",
    ),
    Source(
        "高知県",
        "kochi",
        "https://www.pref.kochi.lg.jp/doc/shimeiteishi_list/file_contents/file_20256102103222_1.pdf",
        "pdf",
        "kyoto_pdf",
        note="2025.6.10",
    ),
    Source(
        "高知県",
        "kochi",
        "https://www.pref.kochi.lg.jp/doc/shimeiteishi_list/file_contents/file_20255951346_1.pdf",
        "pdf",
        "kyoto_pdf",
        note="2025.5.9",
    ),
    Source(
        "高知県",
        "kochi",
        "https://www.pref.kochi.lg.jp/doc/shimeiteishi_list/file_contents/file_2025445143034_1.pdf",
        "pdf",
        "kyoto_pdf",
        note="2025.4.4",
    ),
    Source(
        "高知県",
        "kochi",
        "https://www.pref.kochi.lg.jp/doc/shimeiteishi_list/file_contents/file_20253274103219_1.pdf",
        "pdf",
        "kyoto_pdf",
        note="2025.3.27",
    ),
    # ===== PDF: Oita =====
    Source(
        "大分県",
        "oita",
        "https://www.pref.oita.jp/uploaded/attachment/2237632.pdf",
        "pdf",
        "kyoto_pdf",
        note="令和6年度",
    ),
    Source(
        "大分県",
        "oita",
        "https://www.pref.oita.jp/uploaded/attachment/2263998.pdf",
        "pdf",
        "kyoto_pdf",
        note="令和7年度",
    ),
    # ===== PDF: Kagoshima =====
    Source(
        "鹿児島県",
        "kagoshima",
        "https://www.pref.kagoshima.jp/ah01/infra/tochi-kensetu/nyusatu/documents/11071_20251224161015-1.pdf",
        "pdf",
        "kyoto_pdf",
        note="R7 12月",
    ),
    Source(
        "鹿児島県",
        "kagoshima",
        "https://www.pref.kagoshima.jp/ah01/infra/tochi-kensetu/nyusatu/documents/11071_20251007091609-1.pdf",
        "pdf",
        "kyoto_pdf",
        note="R7 10月",
    ),
    Source(
        "鹿児島県",
        "kagoshima",
        "https://www.pref.kagoshima.jp/ah01/infra/tochi-kensetu/nyusatu/documents/11071_20240826131102-1.pdf",
        "pdf",
        "kyoto_pdf",
        note="R6",
    ),
    # ===== PDF: Yamanashi =====
    Source(
        "山梨県",
        "yamanashi",
        "https://www.pref.yamanashi.jp/documents/7899/r611shimeiteishiitiran.pdf",
        "pdf",
        "kyoto_pdf",
        note="R6.11.29 物品",
    ),
    # ===== PDF: Fukui =====
    Source(
        "福井県",
        "fukui",
        "https://www.pref.fukui.lg.jp/gyosei/tetuduki/cat4503/simeiteisi_d/fil/1.pdf",
        "pdf",
        "kyoto_pdf",
        note="R8.4.17",
    ),
]


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------

# Reiwa-format: R7.4.24 / R7.12.25 / R8.5.7
_R_DATE = re.compile(r"(?:R|令和)\s*(\d+)[\s.年]\s*(\d{1,2})[\s.月]\s*(\d{1,2})[\s.日]?")
# Heisei: H30.3.27
_H_DATE = re.compile(r"H\s*(\d+)[\s.]\s*(\d{1,2})[\s.]\s*(\d{1,2})[\s.]?")
# Plain ISO: 2025-04-24
_ISO_DATE = re.compile(r"(\d{4})[-./](\d{1,2})[-./](\d{1,2})")


def reiwa_to_iso(y: int, mo: int, d: int) -> str | None:
    year = 2018 + y
    try:
        return dt.date(year, mo, d).isoformat()
    except ValueError:
        return None


def heisei_to_iso(y: int, mo: int, d: int) -> str | None:
    year = 1988 + y
    try:
        return dt.date(year, mo, d).isoformat()
    except ValueError:
        return None


def excel_serial_to_iso(v: Any) -> str | None:
    """Excel 1900-base or python date/datetime → ISO yyyy-mm-dd."""
    if v is None or v == "":
        return None
    if isinstance(v, dt.datetime):
        return v.date().isoformat()
    if isinstance(v, dt.date):
        return v.isoformat()
    if isinstance(v, (int, float)):
        try:
            base = dt.date(1899, 12, 30)
            return (base + dt.timedelta(days=int(v))).isoformat()
        except Exception:
            return None
    if isinstance(v, str):
        s = v.strip()
        m = _R_DATE.search(s)
        if m:
            return reiwa_to_iso(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        m = _H_DATE.search(s)
        if m:
            return heisei_to_iso(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        m = _ISO_DATE.search(s)
        if m:
            try:
                return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
            except ValueError:
                return None
    return None


def find_dates_in_text(s: str) -> list[str]:
    """Return all unique dates (ISO) found in s, in order of appearance."""
    out: list[str] = []
    for m in _R_DATE.finditer(s):
        iso = reiwa_to_iso(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if iso and iso not in out:
            out.append(iso)
    for m in _H_DATE.finditer(s):
        iso = heisei_to_iso(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if iso and iso not in out:
            out.append(iso)
    for m in _ISO_DATE.finditer(s):
        try:
            iso = dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
        except ValueError:
            continue
        if iso not in out:
            out.append(iso)
    return out


# ---------------------------------------------------------------------------
# Row container
# ---------------------------------------------------------------------------


@dataclass
class PrefRow:
    """One normalized 都道府県 指名停止 row."""

    prefecture: str
    target_name: str
    address: str | None
    issuance_date: str  # ISO
    period_start: str | None  # ISO
    period_end: str | None  # ISO
    reason_summary: str | None
    related_law_ref: str | None
    source_url: str
    raw_text: str | None = None

    def canonical_id(self) -> str:
        key = f"{self.prefecture}|{self.target_name}|{self.issuance_date}|{self.period_start or ''}|{self.period_end or ''}"
        digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]
        return f"enforcement:pref:{self.prefecture}:{digest}"


# ---------------------------------------------------------------------------
# Target-name cleaning
# ---------------------------------------------------------------------------

# Keep full-width parentheses intact when they contain 株 / 有 markers like
# "（株）" / "(株)" — don't strip those.
# Strip leading list markers (digits with brackets) and trailing whitespace.
_LIST_PREFIX = re.compile(r"^\s*[\d０-９]+\s*[\.．、]?\s*")
_BANNED_NAMES = {
    # Common misparses we want to drop.
    "業者名",
    "商号又は氏名",
    "商号",
    "氏名",
    "名称",
    "事業者名",
    "業者",
    "事業者",
    "請負業者",
    "事業所",
    "団体名",
    "なし",
    "該当なし",
    "－",
    "ー",
    "---",
}


def clean_target_name(s: str) -> str:
    """Trim list prefix + collapse whitespace; return cleaned 業者名."""
    s = s.strip()
    s = _LIST_PREFIX.sub("", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip(" 　")


def is_company_name(s: str) -> bool:
    if not s:
        return False
    if s in _BANNED_NAMES:
        return False
    if len(s) < 2:
        return False
    # Reject pure-numeric or pure-symbol.
    if re.fullmatch(r"[\d\s\.\-]+", s):
        return False
    # Reject 法令 references / column headers
    if "別表" in s or "適用条項" in s or "概要" in s or "備考" in s:
        return False
    return True


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------


def parse_hokkaido_xls(body: bytes, source: Source) -> list[PrefRow]:
    """北海道 XLS: 一覧表（R{N}年度）sheet, columns:
    A=商号, B=所在地, C=始期, D=終期, E=期間, F=該当事項, G=該当条項, H=摘要"""
    if xlrd is None:
        _LOG.error("xlrd not installed; cannot parse %s", source.url)
        return []
    import io

    try:
        wb = xlrd.open_workbook(file_contents=body)
    except Exception as exc:  # noqa: BLE001
        _LOG.error("xlrd open failed %s: %s", source.url, exc)
        return []

    rows: list[PrefRow] = []
    for ws in wb.sheets():
        if "一覧" not in ws.name and "R" not in ws.name and "年度" not in ws.name:
            continue
        # Find header row by looking for cell containing 商号
        header_row: int | None = None
        for r in range(min(ws.nrows, 10)):
            line = " ".join(str(ws.cell_value(r, c)) for c in range(ws.ncols))
            if "商号" in line and ("始期" in line or "期間" in line):
                header_row = r
                break
        if header_row is None:
            continue
        for r in range(header_row + 1, ws.nrows):
            try:
                shogo = str(ws.cell_value(r, 0)).strip()
                shozai = str(ws.cell_value(r, 1)).strip() if ws.ncols > 1 else None
                shiki = ws.cell_value(r, 2) if ws.ncols > 2 else None
                shuki = ws.cell_value(r, 3) if ws.ncols > 3 else None
                gaitou = str(ws.cell_value(r, 5)).strip() if ws.ncols > 5 else None
                jyou = str(ws.cell_value(r, 6)).strip() if ws.ncols > 6 else None
                tekiyou = str(ws.cell_value(r, 7)).strip() if ws.ncols > 7 else None
            except IndexError:
                continue
            shogo = clean_target_name(shogo)
            if not is_company_name(shogo):
                continue
            start_iso = excel_serial_to_iso(shiki)
            end_iso = excel_serial_to_iso(shuki)
            if not start_iso:
                continue
            reason = "; ".join(x for x in [gaitou, tekiyou] if x and x != "None") or None
            rows.append(
                PrefRow(
                    prefecture=source.prefecture,
                    target_name=shogo,
                    address=shozai or None,
                    issuance_date=start_iso,
                    period_start=start_iso,
                    period_end=end_iso,
                    reason_summary=reason,
                    related_law_ref=jyou or None,
                    source_url=source.url,
                    raw_text=None,
                )
            )
    return rows


def _pdftotext_layout(body: bytes) -> str:
    """Run `pdftotext -layout - -` via stdin/stdout."""
    try:
        proc = subprocess.run(
            ["pdftotext", "-layout", "-enc", "UTF-8", "-", "-"],
            input=body,
            capture_output=True,
            check=False,
            timeout=60,
        )
    except FileNotFoundError:
        _LOG.error("pdftotext not on PATH (poppler)")
        return ""
    except subprocess.TimeoutExpired:
        _LOG.error("pdftotext timeout")
        return ""
    if proc.returncode != 0:
        _LOG.warning("pdftotext non-zero rc=%d stderr=%s", proc.returncode, proc.stderr[:200])
    return proc.stdout.decode("utf-8", errors="replace")


# 業者名 detection. Allowed name chars: katakana / kanji / alphanumeric /
# 中黒 / dash / single-stroke hiragana (only when surrounded by other chars).
# Reject hiragana particles (が/を/に/で/と/へ/から/まで) which signal sentence
# fragments, not company names.
_NAME_CORE = r"[A-Za-z0-9Ａ-Ｚａ-ｚ０-９ー・\-゠-ヿ一-鿿]"  # no hiragana
_COMPANY_RE = re.compile(
    rf"((?:株式会社|有限会社|合同会社|合資会社|合名会社|"
    rf"一般社団法人|公益社団法人|一般財団法人|公益財団法人|"
    rf"学校法人|医療法人|社会福祉法人|特定非営利活動法人|"
    rf"独立行政法人|地方独立行政法人|国立大学法人|"
    rf"協同組合|事業協同組合|農業協同組合)"
    rf"{_NAME_CORE}{{1,40}}|"
    rf"{_NAME_CORE}{{1,40}}"
    rf"(?:株式会社|有限会社|合同会社|（株）|\(株\)|（有）|\(有\)|（資）|（名）))"
)
# Address prefix words that should NOT be company names.
_ADDR_PREFIX = re.compile(
    r"^(?:北海道|青森県|岩手県|宮城県|秋田県|山形県|福島県|茨城県|栃木県|群馬県|"
    r"埼玉県|千葉県|東京都|神奈川県|新潟県|富山県|石川県|福井県|山梨県|長野県|"
    r"岐阜県|静岡県|愛知県|三重県|滋賀県|京都府|大阪府|兵庫県|奈良県|和歌山県|"
    r"鳥取県|島根県|岡山県|広島県|山口県|徳島県|香川県|愛媛県|高知県|福岡県|"
    r"佐賀県|長崎県|熊本県|大分県|宮崎県|鹿児島県|沖縄県)"
)


def find_company_in_text(s: str) -> str | None:
    """Find first plausible company name; reject pure address tokens."""
    for m in _COMPANY_RE.finditer(s):
        candidate = m.group(1)
        if _ADDR_PREFIX.match(candidate):
            continue
        cleaned = clean_target_name(candidate)
        if is_company_name(cleaned):
            return cleaned
    return None


def parse_aichi_pdf(body: bytes, source: Source) -> list[PrefRow]:
    """愛知県 PDF: numbered rows, "R7.5.10  R7.8.9" pattern.

    Structure: 番号 | 業者名 | 所在地 | 自 | 至 | 月数 | 理由 | 発注機関 | 条項.
    A single 業者 row spans 4-7 PDF lines (text wraps within columns).
    Block boundary: a line starting with `\\s*\\d+` (序号) at column 0-3.
    """
    text = _pdftotext_layout(body)
    lines = text.split("\n")
    blocks: list[list[str]] = []
    cur: list[str] = []
    for line in lines:
        # Block starts when leading 序号 appears AND the line has a Reiwa date.
        if re.match(r"^\s*\d+\s+\S", line) and re.search(r"R\d+\.\d+\.\d+", line):
            if cur:
                blocks.append(cur)
            cur = [line]
        elif cur:
            cur.append(line)
    if cur:
        blocks.append(cur)

    rows: list[PrefRow] = []
    for blk in blocks:
        joined = " ".join(blk)
        # First two reiwa dates are 自 / 至.
        date_matches = list(_R_DATE.finditer(joined))
        if len(date_matches) < 2:
            continue
        start_iso = reiwa_to_iso(
            int(date_matches[0].group(1)),
            int(date_matches[0].group(2)),
            int(date_matches[0].group(3)),
        )
        end_iso = reiwa_to_iso(
            int(date_matches[1].group(1)),
            int(date_matches[1].group(2)),
            int(date_matches[1].group(3)),
        )
        if not start_iso or not end_iso:
            continue
        # Find company name across full block (covers wrap).
        target = find_company_in_text(joined)
        if not target:
            # Fallback: first line after 序号, first 2-column-aware token.
            first = blk[0]
            m = re.match(r"^\s*\d+\s+(\S{2,40})", first)
            if not m:
                continue
            cand = clean_target_name(m.group(1))
            if not is_company_name(cand) or _ADDR_PREFIX.match(cand):
                continue
            target = cand
        reason = re.sub(r"\s+", " ", joined)[:1500]
        rows.append(
            PrefRow(
                prefecture=source.prefecture,
                target_name=target,
                address=None,
                issuance_date=start_iso,
                period_start=start_iso,
                period_end=end_iso,
                reason_summary=reason,
                related_law_ref=None,
                source_url=source.url,
                raw_text=joined[:2000],
            )
        )
    return rows


def parse_chiba_pdf(body: bytes, source: Source) -> list[PrefRow]:
    """千葉県 PDF: №/理由/業者名/期間/決定年月日/条項/概要 with
    "令和N年X月Y日から...まで" period. Also reused by Saitama, Niigata, Miyagi, Kyoto."""
    text = _pdftotext_layout(body)
    return _parse_period_block_pdf(text, source)


def _parse_period_block_pdf(text: str, source: Source) -> list[PrefRow]:
    """Generic numbered-row PDF parser. Splits on Reiwa-period anchors.

    A 業者 row is identified by a contiguous text region that contains:
      - at least 2 Reiwa/Heisei dates (start + end of 措置期間)
      - a recognizable 業者名 (contains 株式会社/有限会社/etc)

    We split text into atomic 'rows' by detecting period anchors of the form:
      令和N年X月Y日 (から|～|〜) 令和N年X月Y日 (まで)?
    Each match becomes one row; we look back/forward up to 600 chars to
    find a company name AND a 決定年月日 (extra reiwa date).
    """
    # Niigata/Chiba/Yamagata/Iwate: start-date and end-date often split across
    # lines with company/address/reason text in between. Variants:
    #   令和N年M月D日 から <stuff> 令和N年M月D日 まで       (Yamagata, Chiba)
    #   令和N年M月D日 \n <stuff> ～ 令和N年M月D日           (Niigata)
    #   令和N年M月D日 ～ 令和N年M月D日                       (adjacent)
    # We require BOTH start and end dates to be explicit 令和X年Y月Z日 strings,
    # AND require a 'から/～/〜/~/まで' separator somewhere between them
    # (within 400 chars).
    period_re = re.compile(
        r"(令和\s*\d+\s*年\s*\d+\s*月\s*\d+\s*日)"
        r"[\s\S]{0,400}?"
        r"(?:から|～|〜|~|まで)"
        r"[\s\S]{0,200}?"
        r"(令和\s*\d+\s*年\s*\d+\s*月\s*\d+\s*日)"
    )
    # Mie-style: R8.1.8 ～ R8.7.7 (no Reiwa kanji, ASCII period)
    period_re2 = re.compile(
        r"(R\s*\d+\s*\.\s*\d+\s*\.\s*\d+)"
        r"[\s\S]{0,200}?"
        r"(?:から|～|〜|~|まで)?"
        r"[\s\S]{0,100}?"
        r"(R\s*\d+\s*\.\s*\d+\s*\.\s*\d+)"
    )
    period_re3 = period_re  # alias retained for legacy reference
    rows: list[PrefRow] = []
    # Pre-compute all company match positions globally so we can pick the
    # CLOSEST one to each period anchor (instead of the first-in-window).
    company_hits: list[tuple[int, int, str]] = []  # (start, end, name)
    for cm in _COMPANY_RE.finditer(text):
        cand = cm.group(1)
        if _ADDR_PREFIX.match(cand):
            continue
        cleaned = clean_target_name(cand)
        if is_company_name(cleaned):
            company_hits.append((cm.start(), cm.end(), cleaned))

    def _nearest_company(period_pos: int) -> str | None:
        # Prefer companies BEFORE the period start (within 800 chars), else
        # AFTER (within 400). Closest wins.
        best: tuple[int, str] | None = None  # (distance, name)
        for cs, ce, name in company_hits:
            if ce <= period_pos:
                dist = period_pos - ce
                window_cap = 800
            elif cs >= period_pos:
                dist = cs - period_pos
                window_cap = 400
            else:
                # straddles — skip
                continue
            if dist > window_cap:
                continue
            if best is None or dist < best[0]:
                best = (dist, name)
        return best[1] if best else None

    seen_periods: set[tuple[int, int]] = set()  # de-dup overlapping period matches

    def _try(match_iter, *, both_full_dates: bool = True):
        for m in match_iter:
            # Avoid overlapping period matches finding the same anchor twice.
            anchor = (m.start(1), m.end())
            if anchor in seen_periods:
                continue
            seen_periods.add(anchor)
            start_str = m.group(1)
            sm = _R_DATE.search(start_str) or _H_DATE.search(start_str)
            if not sm:
                continue
            if both_full_dates:
                end_str = m.group(2)
                em = _R_DATE.search(end_str) or _H_DATE.search(end_str)
                if not em:
                    continue
                start_iso = (
                    reiwa_to_iso(int(sm.group(1)), int(sm.group(2)), int(sm.group(3)))
                    if "令和" in start_str
                    else heisei_to_iso(int(sm.group(1)), int(sm.group(2)), int(sm.group(3)))
                )
                end_iso = (
                    reiwa_to_iso(int(em.group(1)), int(em.group(2)), int(em.group(3)))
                    if "令和" in end_str or "R" in end_str
                    else heisei_to_iso(int(em.group(1)), int(em.group(2)), int(em.group(3)))
                )
            else:
                start_iso = reiwa_to_iso(int(sm.group(1)), int(sm.group(2)), int(sm.group(3)))
                end_iso = reiwa_to_iso(int(m.group(2)), int(m.group(3)), int(m.group(4)))
            if not start_iso or not end_iso:
                continue
            if start_iso > end_iso:
                continue
            target = _nearest_company(m.start())
            if not target:
                continue
            # 決定年月日: prefer a reiwa date AFTER the period match (within
            # 400 chars) and within [start, end]; else fall back to start_iso.
            tail = text[m.end() : m.end() + 400]
            issuance = start_iso
            for dm in _R_DATE.finditer(tail):
                cand = reiwa_to_iso(int(dm.group(1)), int(dm.group(2)), int(dm.group(3)))
                if cand and start_iso <= cand <= end_iso and cand != end_iso:
                    issuance = cand
                    break
            lo = max(0, m.start() - 200)
            hi = min(len(text), m.end() + 400)
            window = text[lo:hi]
            reason = re.sub(r"\s+", " ", window)[:1500]
            rows.append(
                PrefRow(
                    prefecture=source.prefecture,
                    target_name=target,
                    address=None,
                    issuance_date=issuance,
                    period_start=start_iso,
                    period_end=end_iso,
                    reason_summary=reason,
                    related_law_ref=None,
                    source_url=source.url,
                    raw_text=window[:2000],
                )
            )

    _try(period_re.finditer(text), both_full_dates=True)
    _try(period_re2.finditer(text), both_full_dates=True)

    # Final dedup: same (target, period_start, period_end) → keep first.
    seen_keys: set[tuple[str, str, str]] = set()
    out: list[PrefRow] = []
    for r in rows:
        key = (r.target_name, r.period_start or "", r.period_end or "")
        if key in seen_keys:
            continue
        seen_keys.add(key)
        out.append(r)
    return out


def parse_saitama_pdf(body: bytes, source: Source) -> list[PrefRow]:
    """埼玉県 PDF: 業者名 / 登録名簿 / 許可番号 / 業者番号 / 所在地 / 期間 / 理由"""
    return parse_chiba_pdf(body, source)


def parse_niigata_pdf(body: bytes, source: Source) -> list[PrefRow]:
    """新潟県 PDF: numbered rows with start/end dates and 業者名."""
    return parse_chiba_pdf(body, source)


def parse_miyagi_pdf(body: bytes, source: Source) -> list[PrefRow]:
    """宮城県 PDF: similar tabular shape."""
    return parse_chiba_pdf(body, source)


def parse_kyoto_pdf(body: bytes, source: Source) -> list[PrefRow]:
    """京都府 PDF: similar shape."""
    return parse_chiba_pdf(body, source)


def parse_shizuoka_html(body: bytes, source: Source) -> list[PrefRow]:
    """静岡県 HTML: a single <table> with rows; each row is 3 <td> cells:
       (1) <td>...<a>業者名 (PDF...)</a>...</td>
       (2) <td>条項</td>
       (3) <td>令和X年Y月Z日から令和X年Y月Z日まで...</td>
    Some rows have a 4th cell ※期間変更. Cells alternate (no <tr> wrapping
    in the served HTML — they're loose <td>). We pair every 3 consecutive
    <td> blocks.
    """
    text = body.decode("utf-8", errors="replace")
    text = re.sub(r"<script\b[^>]*>.*?</script>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style\b[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
    rows: list[PrefRow] = []
    seen: set[tuple[str, str]] = set()
    cells = re.findall(
        r"<td\b[^>]*>(.*?)</td>",
        text,
        flags=re.DOTALL | re.IGNORECASE,
    )
    cells = [_strip_html(c) for c in cells]
    # Walk in steps of 3.
    i = 0
    while i < len(cells) - 2:
        c1 = cells[i]
        c3 = cells[i + 2]
        if "から" in c3 or "～" in c3 or "〜" in c3:
            dates = find_dates_in_text(c3)
            if len(dates) >= 2:
                start_iso, end_iso = dates[0], dates[1]
                target = find_company_in_text(c1)
                if not target:
                    # Try take a chunk before "（PDF" marker.
                    cand = re.split(r"（PDF|\(PDF", c1)[0]
                    cand = cand.strip()
                    cand = clean_target_name(cand)
                    if is_company_name(cand) and not _ADDR_PREFIX.match(cand):
                        target = cand
                if target and (target, start_iso) not in seen:
                    seen.add((target, start_iso))
                    reason = " ".join(cells[i : i + 3])[:1500]
                    rows.append(
                        PrefRow(
                            prefecture=source.prefecture,
                            target_name=target,
                            address=None,
                            issuance_date=start_iso,
                            period_start=start_iso,
                            period_end=end_iso,
                            reason_summary=reason,
                            related_law_ref=cells[i + 1] or None,
                            source_url=source.url,
                            raw_text=" | ".join(cells[i : i + 3])[:2000],
                        )
                    )
                i += 3
                # Skip the optional ※期間変更 cell if present
                if i < len(cells) and "期間変更" in cells[i]:
                    i += 1
                continue
        i += 1
    return rows


def parse_gunma_html(body: bytes, source: Source) -> list[PrefRow]:
    """Generic HTML <tr><td>...</td></tr> table parser. Identifies the column
    layout heuristically per row by looking for a date pair in any cell.

    Works for: Gunma 建設工事 / 物品, Toyama press release table.
    Header columns vary (番号|業者名|所在地|期間|理由) but order is consistent."""
    text = body.decode("utf-8", errors="replace")
    text = re.sub(r"<script\b[^>]*>.*?</script>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style\b[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
    rows: list[PrefRow] = []
    seen: set[tuple[str, str]] = set()

    # Extract <tr>...</tr> blocks across the whole document.
    for tr_m in re.finditer(r"<tr\b[^>]*>(.*?)</tr>", text, flags=re.DOTALL | re.IGNORECASE):
        tr_html = tr_m.group(1)
        tds = re.findall(r"<td\b[^>]*>(.*?)</td>", tr_html, flags=re.DOTALL | re.IGNORECASE)
        if len(tds) < 3:
            continue
        cells = [_strip_html(c) for c in tds]
        # Find the cell with a period (date pair).
        period_cell = None
        for c in cells:
            if ("から" in c or "～" in c or "〜" in c or "~" in c) and len(
                find_dates_in_text(c)
            ) >= 2:
                period_cell = c
                break
        if period_cell is None:
            continue
        dates = find_dates_in_text(period_cell)
        start_iso, end_iso = dates[0], dates[1]
        if start_iso > end_iso:
            continue
        # Find company name in earlier cells.
        target: str | None = None
        for c in cells:
            if c == period_cell:
                break
            cand = find_company_in_text(c)
            if cand:
                target = cand
                break
        if not target:
            # 2nd column heuristic for tables that put the name there.
            if len(cells) >= 2:
                cand = clean_target_name(cells[1])
                if is_company_name(cand) and not _ADDR_PREFIX.match(cand):
                    target = cand
        if not target:
            continue
        # Reason cell — last cell typically.
        reason = cells[-1] if cells[-1] != period_cell else (cells[-2] if len(cells) >= 2 else "")
        if (target, start_iso) in seen:
            continue
        seen.add((target, start_iso))
        rows.append(
            PrefRow(
                prefecture=source.prefecture,
                target_name=target,
                address=None,
                issuance_date=start_iso,
                period_start=start_iso,
                period_end=end_iso,
                reason_summary=(reason or "")[:1500],
                related_law_ref=None,
                source_url=source.url,
                raw_text=" | ".join(cells)[:2000],
            )
        )
    return rows


def _strip_html(s: str) -> str:
    s = re.sub(r"<[^>]+>", "", s)
    s = re.sub(r"&nbsp;", " ", s)
    s = re.sub(r"&amp;", "&", s)
    s = re.sub(r"&lt;", "<", s)
    s = re.sub(r"&gt;", ">", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


# Parser dispatch table.
PARSERS: dict[str, Callable[[bytes, Source], list[PrefRow]]] = {
    "hokkaido_xls": parse_hokkaido_xls,
    "aichi_pdf": parse_aichi_pdf,
    "chiba_pdf": parse_chiba_pdf,
    "saitama_pdf": parse_saitama_pdf,
    "niigata_pdf": parse_niigata_pdf,
    "miyagi_pdf": parse_miyagi_pdf,
    "kyoto_pdf": parse_kyoto_pdf,
    "shizuoka_html": parse_shizuoka_html,
    "gunma_html": parse_gunma_html,
}


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


def load_existing_dedup(
    conn: sqlite3.Connection,
    prefectures: list[str],
) -> set[tuple[str, str, str]]:
    """Preload (target_name, issuance_date, issuing_authority) for the prefs
    we're about to ingest, plus the *generic* set across the whole table."""
    placeholders = ",".join(["?"] * len(prefectures))
    sql = (
        "SELECT IFNULL(target_name,''), issuance_date, IFNULL(issuing_authority,'') "
        f"FROM am_enforcement_detail WHERE issuing_authority IN ({placeholders})"
    )
    out: set[tuple[str, str, str]] = set()
    for r in conn.execute(sql, prefectures):
        out.add((r[0], r[1], r[2]))
    return out


def upsert_pref_row(
    conn: sqlite3.Connection,
    row: PrefRow,
    fetched_at: str,
) -> str:
    """Insert am_entities + am_enforcement_detail. Returns 'insert'|'skip'."""
    canonical_id = row.canonical_id()
    raw_json: dict[str, Any] = {
        "prefecture": row.prefecture,
        "target_name": row.target_name,
        "address": row.address,
        "issuance_date": row.issuance_date,
        "period_start": row.period_start,
        "period_end": row.period_end,
        "reason_summary": row.reason_summary,
        "related_law_ref": row.related_law_ref,
        "source_url": row.source_url,
        "fetched_at": fetched_at,
        "source": "pref_shimei_teishi",
    }
    if row.raw_text:
        raw_json["raw_text"] = row.raw_text

    src_domain = urllib.parse.urlparse(row.source_url).netloc
    cur = conn.execute(
        """INSERT OR IGNORE INTO am_entities (
            canonical_id, record_kind, source_topic, primary_name,
            confidence, source_url, source_url_domain, fetched_at, raw_json
        ) VALUES (?, 'enforcement', 'pref_shimei_teishi', ?, ?, ?, ?, ?, ?)
        """,
        (
            canonical_id,
            row.target_name,
            0.92,
            row.source_url,
            src_domain,
            fetched_at,
            json.dumps(raw_json, ensure_ascii=False, separators=(",", ":")),
        ),
    )
    entity_inserted = cur.rowcount > 0

    # Skip if a detail row with the same entity_id already exists (idempotent).
    existing = conn.execute(
        "SELECT enforcement_id FROM am_enforcement_detail WHERE entity_id = ?",
        (canonical_id,),
    ).fetchone()
    if existing:
        return "skip"

    conn.execute(
        """INSERT INTO am_enforcement_detail (
            entity_id, target_name, enforcement_kind,
            issuing_authority, issuance_date, exclusion_start, exclusion_end,
            reason_summary, related_law_ref, source_url, source_fetched_at
        ) VALUES (?, ?, 'contract_suspend', ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            canonical_id,
            row.target_name,
            row.prefecture,
            row.issuance_date,
            row.period_start,
            row.period_end,
            row.reason_summary,
            row.related_law_ref,
            row.source_url,
            fetched_at,
        ),
    )
    return "insert" if entity_inserted else "update"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument(
        "--prefectures", type=str, default="", help="comma-separated slugs (default: all)"
    )
    ap.add_argument("--limit-per-source", type=int, default=None)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--log-file", type=Path, default=None)
    ap.add_argument("--verbose", "-v", action="store_true")
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    selected_slugs = {s.strip() for s in args.prefectures.split(",") if s.strip()}
    if selected_slugs:
        sources = [s for s in SOURCES if s.slug in selected_slugs]
    else:
        sources = list(SOURCES)
    if not sources:
        _LOG.error("no sources selected")
        return 2

    fetched_at = dt.datetime.now(dt.UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
    http = HttpClient()

    # Phase 1: open DB briefly to load dedup keys, then close so other
    # writers (mlit / mhlw bulks) aren't blocked during long HTTP fetches.
    dedup: set[tuple[str, str, str]] = set()
    if not args.dry_run:
        conn0 = open_db(args.db)
        try:
            prefs_in_run = sorted({s.prefecture for s in sources})
            dedup = load_existing_dedup(conn0, prefs_in_run)
            _LOG.info("preload dedup keys=%d (prefs=%s)", len(dedup), prefs_in_run)
        finally:
            conn0.close()

    stats: dict[str, dict[str, int]] = {}
    total_built = 0
    total_inserted = 0
    total_skipped_dup = 0

    # Phase 2: fetch + parse everything, queue rows for a single short
    # write transaction at the end.
    pending: list[tuple[str, dict[str, int], "PrefRow"]] = []  # (cat_key, cat_stats, row)

    try:
        for source in sources:
            cat_key = f"{source.prefecture}|{source.note}|{source.url[-40:]}"
            cat_stats = {"fetched": 0, "built": 0, "inserted": 0, "skipped_dup": 0}
            stats[cat_key] = cat_stats

            _LOG.info("fetching pref=%s url=%s", source.prefecture, source.url)
            cap = PDF_MAX_BYTES if source.fmt in {"pdf", "xls", "xlsx"} else HTML_MAX_BYTES
            res = http.get(source.url, max_bytes=cap)
            if not res.ok or not res.body:
                _LOG.warning(
                    "fetch failed pref=%s url=%s status=%s reason=%s",
                    source.prefecture,
                    source.url,
                    res.status,
                    res.skip_reason,
                )
                continue
            cat_stats["fetched"] = 1

            parser_fn = PARSERS.get(source.parser)
            if parser_fn is None:
                _LOG.warning("no parser for hint=%s", source.parser)
                continue
            try:
                rows = parser_fn(res.body, source)
            except Exception as exc:  # noqa: BLE001
                _LOG.exception("parser %s failed: %s", source.parser, exc)
                continue
            if args.limit_per_source:
                rows = rows[: args.limit_per_source]
            cat_stats["built"] = len(rows)
            total_built += len(rows)
            _LOG.info(
                "parsed pref=%s n=%d (parser=%s)",
                source.prefecture,
                len(rows),
                source.parser,
            )

            if args.dry_run:
                for r in rows[:5]:
                    _LOG.info(
                        "DRY %s | %s | %s..%s | %s",
                        r.prefecture,
                        r.target_name,
                        r.period_start,
                        r.period_end,
                        (r.reason_summary or "")[:80],
                    )
                continue

            for r in rows:
                key = (r.target_name, r.issuance_date, r.prefecture)
                if key in dedup:
                    cat_stats["skipped_dup"] += 1
                    total_skipped_dup += 1
                    continue
                dedup.add(key)
                pending.append((cat_key, cat_stats, r))

    finally:
        http.close()

    # Phase 3: short write transaction. busy_timeout=300s + retry loop
    # absorbs concurrent writers. BEGIN IMMEDIATE only here.
    if not args.dry_run and pending:
        last_err: Exception | None = None
        for write_attempt in range(6):
            conn = open_db(args.db)
            try:
                conn.execute("BEGIN IMMEDIATE")
                batch_inserted = 0
                for cat_key, cat_stats, r in pending:
                    try:
                        verdict = upsert_pref_row(conn, r, fetched_at)
                    except sqlite3.Error as exc:
                        _LOG.error("DB insert failed: %s (target=%s)", exc, r.target_name)
                        continue
                    if verdict == "insert":
                        cat_stats["inserted"] += 1
                        batch_inserted += 1
                        if (batch_inserted % 100) == 0:
                            conn.commit()
                            conn.execute("BEGIN IMMEDIATE")
                    else:
                        cat_stats["skipped_dup"] += 1
                conn.commit()
                total_inserted += batch_inserted
                last_err = None
                break
            except sqlite3.OperationalError as exc:
                last_err = exc
                wait = 5 * (write_attempt + 1)
                _LOG.warning(
                    "write lock contention attempt=%d wait=%ds err=%s", write_attempt, wait, exc
                )
                time.sleep(wait)
                continue
            finally:
                conn.close()
        if last_err is not None:
            raise last_err

    _LOG.info(
        "SUMMARY built=%d inserted=%d skipped_dup=%d sources=%d",
        total_built,
        total_inserted,
        total_skipped_dup,
        len(sources),
    )

    if args.log_file is not None:
        # Aggregate per-prefecture for compact log entry.
        per_pref: dict[str, dict[str, int]] = {}
        for k, v in stats.items():
            pref = k.split("|", 1)[0]
            agg = per_pref.setdefault(
                pref, {"sources": 0, "built": 0, "inserted": 0, "skipped_dup": 0}
            )
            agg["sources"] += 1
            agg["built"] += v["built"]
            agg["inserted"] += v["inserted"]
            agg["skipped_dup"] += v["skipped_dup"]
        with open(args.log_file, "a", encoding="utf-8") as f:
            f.write(
                f"\n## {fetched_at} 都道府県 指名停止 enforcement ingest\n"
                f"  script: scripts/ingest/ingest_enforcement_pref_shimei_teishi.py\n"
                f"  sources={len(sources)} built={total_built} inserted={total_inserted} "
                f"skipped_dup={total_skipped_dup}\n"
                f"  per_prefecture={json.dumps(per_pref, ensure_ascii=False)}\n"
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
