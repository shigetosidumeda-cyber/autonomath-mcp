#!/usr/bin/env python3
"""Ingest 児童福祉法・子ども子育て支援法 enforcement records.

Scope (per directive 2026-04-25):
  - 認可外保育施設 業務改善命令 / 事業停止命令 / 施設閉鎖命令 (児童福祉法 第59条)
  - 認定こども園 確認の取消し (子ども・子育て支援法 第43条)
  - 認可保育所 改善命令 / 認可取消 (児童福祉法 第35条 / 第46条 / 第58条)
  - 障害児通所支援 (児童発達支援 / 放課後等デイ) 指定取消 / 効力停止
    (児童福祉法 第21条の5の24)
  - 児童養護施設・乳児院 改善命令 / 措置停止 (児童福祉法 第45条 / 第46条)

Sources walked (top 15+ 都道府県/政令市 press-release PDFs + cumulative tables):
  PRIMARY MULTI-ROW PDFs (high yield):
    1. 大阪府 障害児通所支援 個別処分 PDF aggregator (29 PDFs at /documents/4810/)
    2. 大阪府 a620torikeshiichiran.pdf (cumulative; 児童福祉法 rows extracted)
    3. 福岡市 060827shiteitorikeshi.pdf (障害児通所支援 一覧)
    4. 東京都福祉局 廃止・取消事業所一覧 (241225_torikesi_itiran)
    5. 京都市 放課後等デイ 公表 PDF (333359 page)
  PRESS-RELEASE PDFs / HTML (single events, additive):
    6. 埼玉県 株式会社MOM 取消 (news2024090601)
    7. 東京都 ファミリエ つむぎ 取消 (2024071904 PDF)
    8. 横浜市 0328syogaiji + 1028syogaiji
    9. 福岡市 4siteisyougaiji241126
    10. 鹿児島市 r6_gyouseishobun (NPO ジョイキッズ)
    11. 柏市 r06032502
    12. 新潟市 個別 PDF (5本)
    13. 青森県 05_r6sidou.pdf
    14. 福島県 認可外/障害児 PDF
    15. 沖縄県 障害児 PDF (kaigo_shogai と重複しないもの)

Schema mapping (am_enforcement_detail):
  - enforcement_kind:
      "指定取消" / "認可取消" / "確認の取消" → 'license_revoke'
      "業務停止" / "効力停止" / "事業停止" / "施設閉鎖" → 'business_improvement'
      "改善命令" / "業務改善命令" → 'business_improvement'
      "改善勧告" → 'other'
  - issuing_authority: '東京都' / '大阪府' / '横浜市' / '福岡市' etc.
  - related_law_ref: '児童福祉法 第N条' / '子ども・子育て支援法 第43条' format
  - amount_yen: NULL except 不正請求/返還 cases → integer yen

Idempotent dedup key: (issuing_authority, issuance_date, target_name).
Parallel-safe: BEGIN IMMEDIATE + busy_timeout=300000.

CLI:
    python scripts/ingest/ingest_enforcement_child_welfare.py
        [--db autonomath.db] [--limit N] [--dry-run] [--verbose]
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

_LOG = logging.getLogger("autonomath.ingest.child_welfare")

DEFAULT_DB = REPO_ROOT / "autonomath.db"
USER_AGENT = "AutonoMath/0.1.0 (+https://bookyou.net)"


# ---------------------------------------------------------------------------
# Source list
# ---------------------------------------------------------------------------
#
# Each entry has:
#   slug       : short id for canonical_id seeding
#   authority  : 都道府県 / 政令市 (issuing_authority)
#   url        : PDF or HTML URL
#   format     : 'osaka_press_pdf' | 'osaka_cumulative_pdf' | 'fukuoka_table_pdf' |
#                'tokyo_cumulative_pdf' | 'press_pdf' | 'html_press'
#   default_law: '児童福祉法' (most), '子ども・子育て支援法' (認定こども園)
#
# Source picks favor PDFs that yield 多数行 — 大阪府の個別PDFは1-3行ずつだが
# 29本あるため total ~50+ rows、cumulative PDFは100+ rows いきなり来る。

OSAKA_PRESS_PDFS: list[dict[str, str]] = [
    # 大阪府 障害児通所支援 個別 行政処分 PDF (~29 PDFs at /documents/4810/)
    {"slug": "osaka-press-20250714", "authority": "大阪府",
     "url": "https://www.pref.osaka.lg.jp/documents/4810/20250714gyouseisyobunn_1.pdf",
     "format": "press_pdf", "default_law": "児童福祉法"},
    {"slug": "osaka-press-250326", "authority": "大阪府",
     "url": "https://www.pref.osaka.lg.jp/documents/4810/250326gyouseisyobun.pdf",
     "format": "press_pdf", "default_law": "児童福祉法"},
    {"slug": "osaka-press-doremifa", "authority": "大阪府",
     "url": "https://www.pref.osaka.lg.jp/documents/4810/zi-doremifasoraizufcikeda.pdf",
     "format": "press_pdf", "default_law": "児童福祉法"},
    {"slug": "osaka-press-tenton", "authority": "大阪府",
     "url": "https://www.pref.osaka.lg.jp/documents/4810/tenton1.pdf",
     "format": "press_pdf", "default_law": "児童福祉法"},
    {"slug": "osaka-press-wandafuru", "authority": "大阪府",
     "url": "https://www.pref.osaka.lg.jp/documents/4810/031224wandafuru.pdf",
     "format": "press_pdf", "default_law": "児童福祉法"},
    {"slug": "osaka-press-ikiiki-suta", "authority": "大阪府",
     "url": "https://www.pref.osaka.lg.jp/documents/4810/03927ikiikisutadexi.pdf",
     "format": "press_pdf", "default_law": "児童福祉法"},
    {"slug": "osaka-press-ikiiki-jr", "authority": "大阪府",
     "url": "https://www.pref.osaka.lg.jp/documents/4810/03927ikiikijunia.pdf",
     "format": "press_pdf", "default_law": "児童福祉法"},
    {"slug": "osaka-press-aozora", "authority": "大阪府",
     "url": "https://www.pref.osaka.lg.jp/documents/4810/03092420aozorasagyousyo.pdf",
     "format": "press_pdf", "default_law": "児童福祉法"},
    {"slug": "osaka-press-huziki", "authority": "大阪府",
     "url": "https://www.pref.osaka.lg.jp/documents/4810/03910huzikikaku.pdf",
     "format": "press_pdf", "default_law": "児童福祉法"},
    {"slug": "osaka-press-rkea", "authority": "大阪府",
     "url": "https://www.pref.osaka.lg.jp/documents/4810/030831rkeasabisu.pdf",
     "format": "press_pdf", "default_law": "児童福祉法"},
    {"slug": "osaka-press-yuuka", "authority": "大阪府",
     "url": "https://www.pref.osaka.lg.jp/documents/4810/020930yuuka.pdf",
     "format": "press_pdf", "default_law": "児童福祉法"},
    {"slug": "osaka-press-furennzu", "authority": "大阪府",
     "url": "https://www.pref.osaka.lg.jp/documents/4810/020531furennzu.pdf",
     "format": "press_pdf", "default_law": "児童福祉法"},
    {"slug": "osaka-press-undouhiroba", "authority": "大阪府",
     "url": "https://www.pref.osaka.lg.jp/documents/4810/020529undouhiroba.pdf",
     "format": "press_pdf", "default_law": "児童福祉法"},
    {"slug": "osaka-press-tunagu", "authority": "大阪府",
     "url": "https://www.pref.osaka.lg.jp/documents/4810/020529tunagu.pdf",
     "format": "press_pdf", "default_law": "児童福祉法"},
    {"slug": "osaka-press-gonse", "authority": "大阪府",
     "url": "https://www.pref.osaka.lg.jp/documents/4810/020331gonse.pdf",
     "format": "press_pdf", "default_law": "児童福祉法"},
    {"slug": "osaka-press-ami", "authority": "大阪府",
     "url": "https://www.pref.osaka.lg.jp/documents/4810/020131ami.pdf",
     "format": "press_pdf", "default_law": "児童福祉法"},
    {"slug": "osaka-press-kopan", "authority": "大阪府",
     "url": "https://www.pref.osaka.lg.jp/documents/4810/020131kopan20.pdf",
     "format": "press_pdf", "default_law": "児童福祉法"},
    {"slug": "osaka-press-011129", "authority": "大阪府",
     "url": "https://www.pref.osaka.lg.jp/documents/4810/011129kouryokuteisi20.pdf",
     "format": "press_pdf", "default_law": "児童福祉法"},
    {"slug": "osaka-press-r11108", "authority": "大阪府",
     "url": "https://www.pref.osaka.lg.jp/documents/4810/r11108kouryokuteisi20.pdf",
     "format": "press_pdf", "default_law": "児童福祉法"},
    {"slug": "osaka-press-011031", "authority": "大阪府",
     "url": "https://www.pref.osaka.lg.jp/documents/4810/011031siteitorikesi.pdf",
     "format": "press_pdf", "default_law": "児童福祉法"},
    {"slug": "osaka-press-010920", "authority": "大阪府",
     "url": "https://www.pref.osaka.lg.jp/documents/4810/010920kouryokuteisi20.pdf",
     "format": "press_pdf", "default_law": "児童福祉法"},
    {"slug": "osaka-press-cyucyu", "authority": "大阪府",
     "url": "https://www.pref.osaka.lg.jp/documents/4810/310315cyucyu.pdf",
     "format": "press_pdf", "default_law": "児童福祉法"},
    {"slug": "osaka-press-310308", "authority": "大阪府",
     "url": "https://www.pref.osaka.lg.jp/documents/4810/310308siteitorikesi.pdf",
     "format": "press_pdf", "default_law": "児童福祉法"},
    {"slug": "osaka-press-310228", "authority": "大阪府",
     "url": "https://www.pref.osaka.lg.jp/documents/4810/310228siteitorikesi.pdf",
     "format": "press_pdf", "default_law": "児童福祉法"},
    {"slug": "osaka-press-310222", "authority": "大阪府",
     "url": "https://www.pref.osaka.lg.jp/documents/4810/310222kouryokuteisi20.pdf",
     "format": "press_pdf", "default_law": "児童福祉法"},
    {"slug": "osaka-press-301219", "authority": "大阪府",
     "url": "https://www.pref.osaka.lg.jp/documents/4810/301219kouryokuteisi20.pdf",
     "format": "press_pdf", "default_law": "児童福祉法"},
    {"slug": "osaka-press-300910", "authority": "大阪府",
     "url": "https://www.pref.osaka.lg.jp/documents/4810/300910kouryokuteisi20.pdf",
     "format": "press_pdf", "default_law": "児童福祉法"},
    {"slug": "osaka-press-300309", "authority": "大阪府",
     "url": "https://www.pref.osaka.lg.jp/documents/4810/300309kouryokuteisi20.pdf",
     "format": "press_pdf", "default_law": "児童福祉法"},
    {"slug": "osaka-press-280318", "authority": "大阪府",
     "url": "https://www.pref.osaka.lg.jp/documents/4810/280318houkagotoudeisa-bisu.pdf",
     "format": "press_pdf", "default_law": "児童福祉法"},
]

CUMULATIVE_PDFS: list[dict[str, str]] = [
    # 福岡市 障害児通所支援 一覧 (multi-row table)
    {"slug": "fukuoka-city-060827", "authority": "福岡市",
     "url": "https://www.city.fukuoka.lg.jp/kodomo-mirai/shogaijishien/health/syogaij-sien/documents/060827shiteitorikeshi.pdf",
     "format": "fukuoka_table_pdf", "default_law": "児童福祉法"},
    # 福岡市 障害児通所支援 取消 (4siteisyougaiji241126.pdf)
    {"slug": "fukuoka-city-241126", "authority": "福岡市",
     "url": "https://www.city.fukuoka.lg.jp/shisei/kouhou-hodo/hodo-happyo/2024/documents/4siteisyougaiji241126.pdf",
     "format": "press_pdf", "default_law": "児童福祉法"},
    # 青森県 R6 障害福祉/障害児行政処分事例集 (multi-row PDF)
    {"slug": "aomori-r6-sidou", "authority": "青森県",
     "url": "https://www.pref.aomori.lg.jp/soshiki/kenko/syofuku/files/05_r6sidou.pdf",
     "format": "aomori_slide_pdf", "default_law": "児童福祉法"},
]

# 個別 press release PDFs (1 row each)
SINGLE_PRESS_PDFS: list[dict[str, str]] = [
    # 埼玉県 株式会社MOM (こどもプラス東松山教室 + 坂戸教室)
    {"slug": "saitama-mom-258270", "authority": "埼玉県",
     "url": "https://www.pref.saitama.lg.jp/documents/258270/news2024090601.pdf",
     "format": "press_pdf", "default_law": "児童福祉法"},
    # 東京都 ファミリエ つむぎ 取消
    {"slug": "tokyo-press-04-01-528", "authority": "東京都",
     "url": "https://www.metro.tokyo.lg.jp/documents/d/tosei/04_01_528",
     "format": "press_pdf", "default_law": "児童福祉法"},
    # 横浜市 障害児通所支援 取消 (2025-03-28 PDF)
    {"slug": "yokohama-0001-20250326", "authority": "横浜市",
     "url": "https://www.city.yokohama.lg.jp/city-info/koho-kocho/press/kodomo/2024/0328syogaiji.files/0001_20250326.pdf",
     "format": "press_pdf", "default_law": "児童福祉法"},
    # 横浜市 障害児通所支援 取消 (2024-10-28 PDF; href 推定)
    {"slug": "yokohama-1028", "authority": "横浜市",
     "url": "https://www.city.yokohama.lg.jp/city-info/koho-kocho/press/kodomo/2024/1028syogaiji.files/0001.pdf",
     "format": "press_pdf", "default_law": "児童福祉法"},
    # 鹿児島市 ジョイキッズ
    {"slug": "kagoshima-r6-jpk", "authority": "鹿児島市",
     "url": "https://www.city.kagoshima.lg.jp/kenkofukushi/fukushi/syofuku/kenko/fukushi/shogai/r6_gyouseishobun.html",
     "format": "html_press", "default_law": "児童福祉法"},
    # 柏市 障害児通所支援 行政処分
    {"slug": "kashiwa-r06032502", "authority": "柏市",
     "url": "https://www.city.kashiwa.lg.jp/koho/pressrelease/r5houdou/3gatsu/r06032502.html",
     "format": "html_press", "default_law": "児童福祉法"},
    # 新潟市 個別 PDFs
    {"slug": "niigata-20220228", "authority": "新潟市",
     "url": "https://www.city.niigata.lg.jp/iryo/shofuku/syogaiservice/gyoseishobun.files/20220228.pdf",
     "format": "press_pdf", "default_law": "児童福祉法"},
    {"slug": "niigata-torikeshi07", "authority": "新潟市",
     "url": "https://www.city.niigata.lg.jp/iryo/shofuku/syogaiservice/gyoseishobun.files/torikeshi07.pdf",
     "format": "press_pdf", "default_law": "児童福祉法"},
    {"slug": "niigata-torikeshi04", "authority": "新潟市",
     "url": "https://www.city.niigata.lg.jp/iryo/shofuku/syogaiservice/gyoseishobun.files/torikeshi04.pdf",
     "format": "press_pdf", "default_law": "児童福祉法"},
    {"slug": "niigata-torikeshi03", "authority": "新潟市",
     "url": "https://www.city.niigata.lg.jp/iryo/shofuku/syogaiservice/gyoseishobun.files/torikeshi03.pdf",
     "format": "press_pdf", "default_law": "児童福祉法"},
    {"slug": "niigata-20171215", "authority": "新潟市",
     "url": "https://www.city.niigata.lg.jp/iryo/shofuku/syogaiservice/gyoseishobun.files/20171215gyoseishobun.pdf",
     "format": "press_pdf", "default_law": "児童福祉法"},
    # 横浜市 2021 障害児通所支援 指定取消
    {"slug": "yokohama-0006-20210721", "authority": "横浜市",
     "url": "https://www.city.yokohama.lg.jp/city-info/koho-kocho/press/kodomo/2021/gyouseisyobun.files/0006_20210721.pdf",
     "format": "press_pdf", "default_law": "児童福祉法"},
    # 千葉県 2020 わたぼうし (社福博和会)
    {"slug": "chiba-watabousi-2020", "authority": "千葉県",
     "url": "https://www.pref.chiba.lg.jp/shoji/press/2020/watabousi_jidou.html",
     "format": "html_press", "default_law": "児童福祉法"},
    # 千葉県 2020 みつば (株式会社GoodDay)
    {"slug": "chiba-mituba-2020", "authority": "千葉県",
     "url": "https://www.pref.chiba.lg.jp/shoji/press/2020/mituba.html",
     "format": "html_press", "default_law": "児童福祉法"},
    # 千葉県 2018 障害児通所支援 (HTML)
    {"slug": "chiba-syobun2-2018", "authority": "千葉県",
     "url": "https://www.pref.chiba.lg.jp/shoji/ryouiku/syobun2.html",
     "format": "html_press", "default_law": "児童福祉法"},
    # 千葉県 2019 障害児通所支援 (HTML)
    {"slug": "chiba-syobun-2019", "authority": "千葉県",
     "url": "https://www.pref.chiba.lg.jp/shoji/ryouiku/syobun.html",
     "format": "html_press", "default_law": "児童福祉法"},
    # 茨城県 認可外保育施設 事業停止命令 (キッズスペースnino, 古河の託児所ピコ)
    {"slug": "ibaraki-nino-2021", "authority": "茨城県",
     "url": "https://www.pref.ibaraki.jp/hokenfukushi/kodomo/hoiku/20210816press_release.html",
     "format": "html_press", "default_law": "児童福祉法"},
    {"slug": "ibaraki-pico-2022", "authority": "茨城県",
     "url": "https://www.pref.ibaraki.jp/hokenfukushi/kodomo/hoiku/r3ninkagai_kouhyou2.html",
     "format": "html_press", "default_law": "児童福祉法"},
    {"slug": "ibaraki-yuyuu-2022", "authority": "茨城県",
     "url": "https://www.pref.ibaraki.jp/hokenfukushi/kodomo/hoiku/r4ninkagai_jigyouteishi.html",
     "format": "html_press", "default_law": "児童福祉法"},
    {"slug": "ibaraki-nino-pubonly", "authority": "茨城県",
     "url": "https://www.pref.ibaraki.jp/hokenfukushi/kodomo/hoiku/ninkagai_kouhyou.html",
     "format": "html_press", "default_law": "児童福祉法"},
    # 岐阜県 R1 合同会社日野 (このき羽島校)
    {"slug": "gifu-hino-r1", "authority": "岐阜県",
     "url": "https://www.pref.gifu.lg.jp/uploaded/attachment/151604.pdf",
     "format": "press_pdf", "default_law": "児童福祉法"},
]


# ---------------------------------------------------------------------------
# Date / law / kind parsing
# ---------------------------------------------------------------------------

WAREKI_RE = re.compile(
    r"(令和|平成|昭和|R|H|S)\s*(\d+|元)\s*[年.\-．／]?\s*(\d{1,2})\s*[月.\-．／]?\s*(\d{1,2})\s*日?"
)
SEIREKI_RE = re.compile(r"(20\d{2}|19\d{2})\s*[年.\-／/]\s*(\d{1,2})\s*[月.\-／/]\s*(\d{1,2})")
ERA_OFFSET = {"令和": 2018, "R": 2018, "平成": 1988, "H": 1988, "昭和": 1925, "S": 1925}

# 児童福祉法 第N条(の M の K) 第P項 第Q号
# 児童福祉法 第21条の5の24第1項第6号 のような形式が多いので、
# 条 の後の "の5の24" 部分は別グループで拾う。
JIDOU_ARTICLE_RE = re.compile(
    r"児童福祉法[^第。]{0,12}第\s*(\d+)\s*条((?:の\d+)*)"
    r"(?:[^第。]{0,3}第\s*(\d+)\s*項)?(?:[^第。]{0,3}第\s*(\d+)\s*号)?"
)
KOSODATE_ARTICLE_RE = re.compile(
    r"子ども\s*[・･]?\s*子育て支援法[^第。]{0,12}第\s*(\d+)\s*条((?:の\d+)*)"
)
ARTICLE_NEAR_RE = re.compile(
    r"第\s*(\d+)\s*条((?:の\d+)*)"
    r"(?:[^第。]{0,3}第\s*(\d+)\s*項)?(?:[^第。]{0,3}第\s*(\d+)\s*号)?"
)


def _to_hankaku_digits(s: str) -> str:
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
    m = JIDOU_ARTICLE_RE.search(s)
    if m:
        art = f"児童福祉法 第{m.group(1)}条"
        if m.group(2):  # の5の24 等
            art += m.group(2)
        if m.group(3):
            art += f"第{m.group(3)}項"
        if m.group(4):
            art += f"第{m.group(4)}号"
        parts.append(art)
    m = KOSODATE_ARTICLE_RE.search(s)
    if m:
        art = f"子ども・子育て支援法 第{m.group(1)}条"
        if m.group(2):
            art += m.group(2)
        parts.append(art)
    if not parts:
        if default_law and (
            "保育" in s or "児童" in s or "こども" in s or "子ども" in s
        ):
            m = ARTICLE_NEAR_RE.search(s)
            if m:
                art = f"{default_law} 第{m.group(1)}条"
                if m.group(2):
                    art += m.group(2)
                if m.group(3):
                    art += f"第{m.group(3)}項"
                if m.group(4):
                    art += f"第{m.group(4)}号"
                parts.append(art)
    if parts:
        return " / ".join(parts)
    return default_law


def _classify_kind(text: str) -> str:
    """Map disposition text → enforcement_kind enum."""
    if not text:
        return "other"
    s = _normalize(text)
    # 取消 系列
    if any(k in s for k in (
        "指定取消", "指定の取消", "指定取り消し", "認可取消", "認可の取消",
        "確認取消", "確認の取消", "認定取消", "認定の取消"
    )):
        return "license_revoke"
    # 停止 / 閉鎖 / 改善 系列
    if any(k in s for k in (
        "効力の停止", "効力停止", "業務停止", "事業停止",
        "施設閉鎖", "閉鎖命令", "業務改善命令", "改善命令",
        "受入停止", "受入れ停止"
    )):
        return "business_improvement"
    if "改善勧告" in s or "公表" in s and "改善" in s:
        return "other"
    return "other"


def _extract_amount(text: str) -> int | None:
    """Extract 不正受給/不正請求/返還額 in yen. Best effort."""
    if not text:
        return None
    s = _to_hankaku_digits(_normalize(text))
    # 数字+カンマ+円
    m = re.search(r"(\d[\d,]{3,15})\s*円", s)
    if m:
        try:
            return int(m.group(1).replace(",", ""))
        except ValueError:
            return None
    # 約○万円 / ○千万円 / ○億円
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
# Row dataclass
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
    facility_name: str | None
    extras: dict[str, str] | None


def _clean(c: str | None) -> str:
    if c is None:
        return ""
    return _normalize(c.replace("\n", " "))


# ---------------------------------------------------------------------------
# Press PDF parser (single-event)
# ---------------------------------------------------------------------------


def parse_press_pdf(
    pdf_bytes: bytes, *, authority: str, default_law: str, source_url: str
) -> list[EnfRow]:
    """Parse a single-event 報道発表 / 個別処分 PDF."""
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

    # Issuance date — try header first 8 lines, then fallback scan.
    head = "\n".join(norm.splitlines()[:10])
    issuance = _parse_date(head)
    if not issuance:
        m = WAREKI_RE.search(norm) or SEIREKI_RE.search(norm)
        if m:
            issuance = _parse_date(m.group(0))
    if not issuance:
        _LOG.debug("press pdf %s: no date", source_url)
        return []

    # Provider name — 児童福祉法系の press は法人名 / 名称 / 申請者名 の prefix が多様
    target_name: str | None = None
    name_patterns = [
        re.compile(r"法\s*人\s*名(?:\s*等)?[\s　:：]*([^\n（(]{2,80})"),
        re.compile(r"事業者(?:名|の名称)[\s　:：]*([^\n（(]{2,80})"),
        re.compile(r"申請者(?:名|名称)[\s　:：]*([^\n（(]{2,80})"),
        re.compile(r"設置者(?:名|の名称)[\s　:：]*([^\n（(]{2,80})"),
        re.compile(r"運営法人[\s　:：]*([^\n（(]{2,80})"),
        re.compile(r"[(（][1１][)）][\s　]*名\s*称[\s　:：]*\n?([^\n（(]{2,80})"),
        re.compile(r"(?:^|\n)\s*名\s*称[\s　:：]*\n?([^\n（(]{2,80})"),
    ]
    for pat in name_patterns:
        m = pat.search(norm)
        if m:
            cand = m.group(1).strip()
            cand = re.split(
                r"[（(]|代表者|事業所|所在地|住所|の取消|処分|事業所所在地|電話",
                cand,
            )[0].strip()
            cand = re.sub(r"^[、。．・\s　:：]+", "", cand).strip()
            if 2 <= len(cand) <= 100 and not cand.startswith(("、", "。", "・")):
                target_name = cand
                break

    if not target_name:
        # Fallback: 法人 prefix anywhere in text
        m = re.search(
            r"(株式会社|合同会社|有限会社|社会福祉法人|医療法人|"
            r"一般社団法人|公益社団法人|合資会社|協同組合|"
            r"社会医療法人|特定非営利活動法人|NPO法人|学校法人)"
            r"[^\s\n、。（）()【】「」]{1,40}",
            norm,
        )
        if m:
            target_name = m.group(0).strip()

    if not target_name:
        _LOG.debug("press pdf %s: no provider name", source_url)
        return []

    # Facility name (best effort)
    facility_name: str | None = None
    for pat in (
        re.compile(r"事業所(?:の)?名称[\s　:：]*([^\n（(]{2,80})"),
        re.compile(r"施設(?:の)?名称[\s　:：]*([^\n（(]{2,80})"),
    ):
        m = pat.search(norm)
        if m:
            cand = m.group(1).strip()
            cand = re.split(
                r"[（(]|事業所所在地|住所|電話|代表者|及び所在地|及び住所",
                cand,
            )[0].strip()
            # Drop generic placeholder phrases.
            if cand in {"及び所在地", "等", "及び", "の名称"}:
                continue
            if 2 <= len(cand) <= 80:
                facility_name = cand
                break

    # Disposition + reason from first 2500 chars
    head_text = norm[:2500]
    kind = _classify_kind(head_text)
    reason_summary = head_text.replace("\n", " ")[:600]

    # Amount: priority sections
    amount: int | None = None
    for keyword in ("不正請求", "返還額", "不正受給", "過大請求", "加算返還"):
        idx = norm.find(keyword)
        if idx != -1:
            amount = _extract_amount(norm[idx: idx + 400])
            if amount is not None:
                break
    if amount is None:
        amount = _extract_amount(norm[:3000])

    law_ref = _extract_law_ref(norm[:3000], default_law)

    # Build target_name with facility suffix to avoid collisions when same 法人
    # has multiple 事業所 in the same announcement (saitama MOM example).
    final_name = target_name
    if facility_name and len(target_name) + len(facility_name) <= 180:
        # Only append if facility_name distinct enough (not contained in target).
        if facility_name not in target_name:
            final_name = f"{target_name} / {facility_name}"

    return [EnfRow(
        target_name=final_name[:200],
        location=None,
        issuance_date=issuance,
        related_law_ref=law_ref,
        reason_summary=reason_summary[:4000],
        enforcement_kind=kind,
        amount_yen=amount,
        facility_name=facility_name,
        extras={
            "format": "press_pdf",
            "source_url": source_url,
        },
    )]


# ---------------------------------------------------------------------------
# Fukuoka cumulative table PDF (multi-row, structured columns)
# ---------------------------------------------------------------------------


def parse_fukuoka_table_pdf(
    pdf_bytes: bytes, *, authority: str, default_law: str, source_url: str
) -> list[EnfRow]:
    """Parse 福岡市 060827 形式 9-col table:
    [行政処分, 指定取消年月日, 事業所の名称, 事業所の所在地, サービスの種類,
     事業所番号, 事業者の名称, 事業者の所在地, 代表者氏名]"""
    rows: list[EnfRow] = []
    seen_in_pdf: set[tuple[str, str]] = set()
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
                        if not raw or len(raw) < 7:
                            continue
                        cols = [_clean(c) for c in raw]
                        joined = " ".join(cols)
                        # Skip header
                        if "指定取消年月日" in joined or "事業所の名称" in joined:
                            continue
                        # Disposition kind in col 0, date in col 1
                        kind_text = cols[0]
                        date_iso = _parse_date(cols[1])
                        if not date_iso:
                            continue
                        facility = cols[2] if len(cols) > 2 else ""
                        loc = cols[3] if len(cols) > 3 else ""
                        service = cols[4] if len(cols) > 4 else ""
                        provider = cols[6] if len(cols) > 6 else ""
                        provider_addr = cols[7] if len(cols) > 7 else ""
                        if not (facility or provider):
                            continue
                        if provider and len(provider) >= 2:
                            tn = provider
                            if facility and facility not in provider:
                                tn = f"{provider} / {facility}"
                        else:
                            tn = facility or "不詳"
                        tn = tn[:200]
                        key = (tn, date_iso)
                        if key in seen_in_pdf:
                            continue
                        seen_in_pdf.add(key)
                        reason_blob = (
                            f"[{kind_text}] サービス={service} / "
                            f"事業所={facility} / 所在地={loc}"
                        )
                        rows.append(EnfRow(
                            target_name=tn,
                            location=loc or provider_addr or None,
                            issuance_date=date_iso,
                            related_law_ref=_extract_law_ref(
                                kind_text + " " + service, default_law
                            ),
                            reason_summary=reason_blob[:4000],
                            enforcement_kind=_classify_kind(kind_text),
                            amount_yen=None,
                            facility_name=facility or None,
                            extras={
                                "format": "fukuoka_table_pdf",
                                "service_type": service,
                                "provider_addr": provider_addr,
                                "kind_text": kind_text,
                            },
                        ))
    except Exception as exc:  # noqa: BLE001
        _LOG.warning("fukuoka table pdf parse failed %s: %s", source_url, exc)
    return rows


def parse_aomori_slide_pdf(
    pdf_bytes: bytes, *, authority: str, default_law: str, source_url: str
) -> list[EnfRow]:
    """Parse 青森県 R6 行政処分事例 slide deck. Each case starts with a
    line like "平成31年2月処分／放課後等デイサービス／指定取消" and is
    followed by 法令違反条文 + 不正請求額."""
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            text_parts = [(p.extract_text() or "") for p in pdf.pages]
    except Exception as exc:  # noqa: BLE001
        _LOG.warning("aomori pdf %s open failed: %s", source_url, exc)
        return []
    full = _to_hankaku_digits(unicodedata.normalize("NFKC", "\n".join(text_parts)))
    if not full.strip():
        return []
    # Split per page header pattern: "平成|令和N年M月処分／…／…"
    case_re = re.compile(
        r"(?:平成|令和)\s*\d+\s*年\s*\d+\s*月\s*処分\s*[／/]"
        r"\s*([^／/\n]+)\s*[／/]\s*(指定取消|効力停止|業務停止|改善命令|改善勧告)"
    )
    rows: list[EnfRow] = []
    seen: set[tuple[str, str]] = set()
    matches = list(case_re.finditer(full))
    for idx, m in enumerate(matches):
        seg_start = m.start()
        seg_end = matches[idx + 1].start() if idx + 1 < len(matches) else len(full)
        seg = full[seg_start: seg_end]
        # Date (era-based, just at the matched header) — use header date
        head_date_m = re.search(
            r"(平成|令和)\s*(\d+|元)\s*年\s*(\d+)\s*月", seg[:80]
        )
        if not head_date_m:
            continue
        era = head_date_m.group(1)
        y_raw = head_date_m.group(2)
        try:
            y_off = 1 if y_raw == "元" else int(y_raw)
        except ValueError:
            continue
        if era not in ERA_OFFSET:
            continue
        year = ERA_OFFSET[era] + y_off
        month = int(head_date_m.group(3))
        if not (1990 <= year <= 2100 and 1 <= month <= 12):
            continue
        # Use first day of the month as proxy issuance date.
        issuance = f"{year:04d}-{month:02d}-01"
        service = m.group(1).strip()
        kind_text = m.group(2).strip()
        # Look for 不正請求額 within segment
        amount = None
        for kw in ("不正請求額", "返還額", "過大請求", "不正受給"):
            i = seg.find(kw)
            if i != -1:
                amount = _extract_amount(seg[i: i + 200])
                if amount is not None:
                    break
        # Skip cases that don't reference 児童福祉法 (本ingestのscope外).
        # 障害者総合支援法 only cases belong in 介護/障害 ingest.
        if "児童福祉法" not in seg:
            continue
        # Provider name attempt — Aomori slides 上記事例で法人名が匿名化されている
        # ことが多い。コロン後の値を厳密に取る (タイトル文字列が prefix なし
        # で混入するのを避ける)。
        prov_m = re.search(
            r"(?:事業者(?:名)?|法\s*人\s*名)\s*[:：][\s　]*([^\n（(]{2,80})", seg
        )
        target: str | None = None
        if prov_m:
            cand = prov_m.group(1).strip()
            cand = re.split(r"[（(]|住所|所在地|代表者", cand)[0].strip()
            if 2 <= len(cand) <= 100 and not cand.startswith(("等", "の", "に", "及び")):
                target = cand
        if target is None:
            # Anonymized — generate stable stub. Avoid collisions by
            # including service+date+segment-hash.
            seg_hash = hashlib.sha1(seg.encode("utf-8")).hexdigest()[:6]
            target = f"青森県 (匿名) {service} 事業者 [{seg_hash}]"
        target = target[:200]
        key = (target, issuance)
        if key in seen:
            continue
        seen.add(key)
        law_ref = _extract_law_ref(seg, default_law)
        # If no 児童福祉法 article extracted, the segment talks about 児童福祉法
        # somewhere but the regex didn't fire — keep '児童福祉法' bare.
        reason = seg.replace("\n", " ")[:600]
        rows.append(EnfRow(
            target_name=target,
            location=None,
            issuance_date=issuance,
            related_law_ref=law_ref,
            reason_summary=reason[:4000],
            enforcement_kind=_classify_kind(kind_text),
            amount_yen=amount,
            facility_name=None,
            extras={
                "format": "aomori_slide_pdf",
                "service_type": service,
                "kind_text": kind_text,
            },
        ))
    return rows


# ---------------------------------------------------------------------------
# HTML press release parser
# ---------------------------------------------------------------------------


def parse_html_press(
    html: str, *, authority: str, default_law: str, source_url: str
) -> list[EnfRow]:
    """Parse a 報道発表 HTML page that holds the disposition info inline."""
    if not html:
        return []
    try:
        soup = BeautifulSoup(html, "html.parser")
    except Exception:  # noqa: BLE001
        return []
    text = _to_hankaku_digits(unicodedata.normalize("NFKC", soup.get_text("\n", strip=True)))
    if not text.strip():
        return []

    issuance = _parse_date("\n".join(text.splitlines()[:15]))
    if not issuance:
        m = WAREKI_RE.search(text) or SEIREKI_RE.search(text)
        if m:
            issuance = _parse_date(m.group(0))
    if not issuance:
        return []

    target_name: str | None = None
    name_patterns = [
        re.compile(r"法\s*人\s*名(?:\s*等)?[\s　:：]*([^\n（(]{2,80})"),
        re.compile(r"事業者(?:名|の名称)[\s　:：]*([^\n（(]{2,80})"),
        re.compile(r"運営法人[\s　:：]*([^\n（(]{2,80})"),
        re.compile(r"設置者(?:名|の名称)?[\s　:：\n]*([^\n（(]{2,80})"),
        re.compile(r"申請者(?:名|名称)?[\s　:：]*([^\n（(]{2,80})"),
    ]
    for pat in name_patterns:
        m = pat.search(text)
        if m:
            cand = m.group(1).strip()
            cand = re.split(
                r"[（(]|代表者|事業所|所在地|電話|住所|事業停止|事業の停止|施設|の名称",
                cand,
            )[0].strip()
            # Reject pure-label leakage / name-only stubs ("光山" w/o suffix)
            if cand in {"等", "の名称", "及び", "及び所在地"}:
                continue
            if 2 <= len(cand) <= 100:
                target_name = cand
                break
    if not target_name:
        m = re.search(
            r"(株式会社|合同会社|有限会社|社会福祉法人|医療法人|"
            r"一般社団法人|特定非営利活動法人|NPO法人|学校法人)"
            r"[^\s\n、。（）()【】「」]{1,40}",
            text,
        )
        if m:
            target_name = m.group(0).strip()

    if not target_name:
        return []

    # Facility name
    facility: str | None = None
    for pat in (
        re.compile(r"事業所(?:名|の名称)[\s　:：]*([^\n（(]{2,80})"),
        re.compile(r"施設(?:の)?名(?:称)?[\s　:：]*([^\n（(]{2,80})"),
    ):
        m = pat.search(text)
        if m:
            facility = re.split(
                r"[（(]|住所|所在地|サービスの種類|事業所番号|代表者|電話",
                m.group(1).strip(),
            )[0].strip()
            if facility in {"等", "及び", "の名称", "及び所在地", "サービスの種類"}:
                facility = None
                continue
            if facility and len(facility) <= 80:
                break
            facility = None

    head_text = text[:3000]
    kind = _classify_kind(head_text)
    reason_summary = head_text.replace("\n", " ")[:600]

    amount: int | None = None
    for keyword in ("不正請求", "返還額", "不正受給", "過大請求"):
        idx = text.find(keyword)
        if idx != -1:
            amount = _extract_amount(text[idx: idx + 400])
            if amount is not None:
                break
    if amount is None:
        amount = _extract_amount(text[:3000])

    law_ref = _extract_law_ref(head_text, default_law)
    final_name = target_name
    if facility and facility not in target_name and len(target_name) + len(facility) <= 180:
        final_name = f"{target_name} / {facility}"

    return [EnfRow(
        target_name=final_name[:200],
        location=None,
        issuance_date=issuance,
        related_law_ref=law_ref,
        reason_summary=reason_summary[:4000],
        enforcement_kind=kind,
        amount_yen=amount,
        facility_name=facility,
        extras={"format": "html_press"},
    )]


# ---------------------------------------------------------------------------
# DB
# ---------------------------------------------------------------------------


def _slug8(name: str, date: str, extra: str = "") -> str:
    h = hashlib.sha1(f"{name}|{date}|{extra}".encode("utf-8")).hexdigest()
    return h[:8]


def _entity_canonical_id(authority: str, target_name: str, issuance_date: str) -> str:
    """AM-ENF-CHILD-{auth-slug}-{seq8}."""
    auth_slug = hashlib.sha1(authority.encode("utf-8")).hexdigest()[:6]
    seq = _slug8(target_name, issuance_date)
    return f"AM-ENF-CHILD-{auth_slug}-{seq}"


def ensure_tables(conn: sqlite3.Connection) -> None:
    for tbl in ("am_entities", "am_enforcement_detail"):
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (tbl,),
        ).fetchone()
        if not row:
            raise SystemExit(
                f"missing table '{tbl}' — apply migrations first"
            )


def existing_dedup_keys(
    conn: sqlite3.Connection, authority: str
) -> set[tuple[str, str]]:
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
        ) VALUES (?, 'enforcement', 'child_welfare_jidouhukushi', NULL,
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
    ap.add_argument("--limit", type=int, default=None,
                    help="cap total inserts (debugging)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--verbose", "-v", action="store_true")
    ap.add_argument("--max-sources", type=int, default=None,
                    help="cap number of sources walked (debugging)")
    return ap.parse_args(argv)


def fetch_and_parse(
    http: HttpClient, src: dict[str, str]
) -> list[EnfRow]:
    url = src["url"]
    fmt = src["format"]
    res = http.get(url, max_bytes=15 * 1024 * 1024)
    if not res.ok:
        _LOG.warning("[%s] fetch fail status=%s url=%s",
                     src["slug"], res.status, url)
        return []
    body = res.body
    default_law = src.get("default_law") or "児童福祉法"
    authority = src["authority"]
    if fmt == "press_pdf":
        return parse_press_pdf(body, authority=authority,
                               default_law=default_law, source_url=url)
    if fmt == "fukuoka_table_pdf":
        return parse_fukuoka_table_pdf(body, authority=authority,
                                       default_law=default_law, source_url=url)
    if fmt == "aomori_slide_pdf":
        return parse_aomori_slide_pdf(body, authority=authority,
                                      default_law=default_law, source_url=url)
    if fmt == "html_press":
        return parse_html_press(res.text, authority=authority,
                                default_law=default_law, source_url=url)
    _LOG.warning("[%s] unknown format=%s", src["slug"], fmt)
    return []


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    http = HttpClient(user_agent=USER_AGENT)
    now_iso = datetime.now(UTC).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )

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
    by_authority: dict[str, int] = {}
    by_law: dict[str, int] = {}
    sample_rows: list[dict[str, str | int | None]] = []

    sources: list[dict[str, str]] = (
        OSAKA_PRESS_PDFS + CUMULATIVE_PDFS + SINGLE_PRESS_PDFS
    )
    if args.max_sources:
        sources = sources[: args.max_sources]

    auth_dedup_cache: dict[str, set[tuple[str, str]]] = {}

    for src in sources:
        if args.limit and stats["rows_inserted"] >= args.limit:
            _LOG.info("limit reached: %d", args.limit)
            break

        authority = src["authority"]
        slug = src["slug"]

        rows = fetch_and_parse(http, src)
        if not rows:
            stats["sources_failed"] += 1
            _LOG.info("[%s] no rows (authority=%s url=%s)",
                      slug, authority, src["url"])
            continue
        stats["sources_fetched"] += 1
        stats["rows_parsed"] += len(rows)
        _LOG.info("[%s] parsed=%d (authority=%s)",
                  slug, len(rows), authority)

        if conn is None:
            for r in rows[:3]:
                sample_rows.append({
                    "authority": authority,
                    "target_name": r.target_name,
                    "issuance_date": r.issuance_date,
                    "kind": r.enforcement_kind,
                    "law": r.related_law_ref,
                    "amount": r.amount_yen,
                    "reason": (r.reason_summary or "")[:120],
                })
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
                    authority, r.target_name, r.issuance_date
                )
                primary_name = (
                    f"{r.target_name} ({r.issuance_date}) — "
                    f"{authority} {r.enforcement_kind}"
                )
                raw_json = json.dumps(
                    {
                        "authority": authority,
                        "source_slug": slug,
                        "target_name": r.target_name,
                        "facility_name": r.facility_name,
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
                    upsert_entity(conn, canonical_id, primary_name,
                                  src["url"], raw_json, now_iso)
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
                    by_authority[authority] = by_authority.get(authority, 0) + 1
                    if r.related_law_ref:
                        primary_law = r.related_law_ref.split(" /")[0].split(" 第")[0]
                    else:
                        primary_law = "(unknown)"
                    by_law[primary_law] = by_law.get(primary_law, 0) + 1
                    if len(sample_rows) < 5:
                        sample_rows.append({
                            "authority": authority,
                            "target_name": r.target_name,
                            "issuance_date": r.issuance_date,
                            "kind": r.enforcement_kind,
                            "law": r.related_law_ref,
                            "amount": r.amount_yen,
                            "reason": (r.reason_summary or "")[:140],
                        })
                except sqlite3.Error as exc:
                    _LOG.error(
                        "[%s] DB error name=%r date=%s: %s",
                        slug, r.target_name, r.issuance_date, exc,
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
        "done sources_ok=%d sources_fail=%d parsed=%d inserted=%d "
        "dup_db=%d dup_batch=%d",
        stats["sources_fetched"], stats["sources_failed"],
        stats["rows_parsed"], stats["rows_inserted"],
        stats["rows_dup_in_db"], stats["rows_dup_in_batch"],
    )
    print("=== SUMMARY ===")
    print(f"total_inserted: {stats['rows_inserted']}")
    print(f"by_authority: {by_authority}")
    print(f"by_law: {by_law}")
    print(f"samples ({len(sample_rows)}):")
    for s in sample_rows:
        print(f"  - {s}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
