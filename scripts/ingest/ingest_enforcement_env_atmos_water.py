#!/usr/bin/env python3
"""Ingest 大気汚染防止法 + 水質汚濁防止法 + 土壌汚染対策法 + 騒音規制法 +
振動規制法 + 悪臭防止法 + ダイオキシン類対策特別措置法 違反 行政処分 公表
into ``am_enforcement_detail`` + ``am_entities``.

Background:
    環境基本法系の 6 主要法 (大防法・水濁法・土対法・騒音・振動・悪臭) +
    ダイオ特措法 に基づく行政処分 (改善命令 / 一時停止命令 / 計画変更命令 /
    措置命令 / 報告徴求 / 排出基準超過 等) は、都道府県知事 / 政令市市長 が
    発動する。環境省は毎年「施行状況」を都道府県別 PDF で公表する (個別
    事業者名は通常マスクされ、自治体・年度・件数・違反種別の集計形式)。

    本 ingest は env.go.jp 公開 PDF (令和6年度水質汚濁防止法施行状況、
    令和5年度大気汚染防止法施行状況、令和6年度土壌汚染対策法施行状況、
    令和5年度ダイオキシン類対策特別措置法施行状況) を一次資料として取り込む。
    各 (自治体, 法, 違反種別, 件数) を、件数 N に応じて N 行展開し、
    1 行 = 1 件の処分実例として登録する (集計→個別ロウ展開、
    target_name は "自治体名 法令違反処分 (FY{YY} 件{n}/{N})" で識別)。

    既存 am_enforcement_detail に環境法 row はゼロ (2026-04-25 確認済)。
    廃棄物処理法系 (env_sanpai #22) とは別 layer。

Strategy:
    1. SEED_AGGREGATES — 環境省 施行状況 PDF を pdftotext で展開済の
       (authority, fy, law, kind, count, source_url, summary) tuples を
       手書き埋め込み (curated 2026-04-25)。
    2. SEED_NAMED — 報道発表 / プレスリリースで個別事業者名が公表されて
       いる事案 (アスベスト解体業者書類送検 等)。
    3. Insert with BEGIN IMMEDIATE + busy_timeout=300000 (parallel-safe).

Schema mapping:
    enforcement_kind:
      "改善命令"                            → 'business_improvement'
      "一時停止命令" / "使用停止命令"        → 'contract_suspend'
      "計画変更命令" / "計画廃止命令"        → 'business_improvement'
      "措置命令"                            → 'business_improvement'
      "報告徴求"                            → 'investigation'
      "排出基準違反 告発" / "罰金"          → 'fine'
      "立入検査・口頭/文書指導"            → 'other'
    issuing_authority: '{都道府県}' or '{政令指定都市}'
    related_law_ref:   法令名 + 条文 (例: '大気汚染防止法 第18条の11')
    amount_yen:        NULL

License: 環境省・自治体ウェブサイトの著作物（出典明記で転載引用可）.

Parallel-safe:
    - BEGIN IMMEDIATE + PRAGMA busy_timeout=300000.
    - 1 commit per all-rows batch.

CLI:
    python scripts/ingest/ingest_enforcement_env_atmos_water.py
        [--db autonomath.db] [--dry-run] [--verbose]
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import logging
import sqlite3
import sys
import unicodedata
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

_LOG = logging.getLogger("autonomath.ingest.env_atmos_water")

DEFAULT_DB = REPO_ROOT / "autonomath.db"


# ---------------------------------------------------------------------------
# Row dataclass
# ---------------------------------------------------------------------------


@dataclass
class EnfRow:
    target_name: str
    issuance_date: str
    issuing_authority: str
    enforcement_kind: str  # see CHECK enum in am_enforcement_detail
    reason_summary: str
    related_law_ref: str
    source_url: str
    extras: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Law constants
# ---------------------------------------------------------------------------

LAW_TAIKI = "大気汚染防止法"
LAW_SUITAKU = "水質汚濁防止法"
LAW_DOJOSEN = "土壌汚染対策法"
LAW_SOUON = "騒音規制法"
LAW_SHINDOU = "振動規制法"
LAW_AKUSHU = "悪臭防止法"
LAW_DIOXIN = "ダイオキシン類対策特別措置法"


# ---------------------------------------------------------------------------
# SEED_AGGREGATES — derived from env.go.jp PDFs (2026-04-25 fetch)
#
# Source PDFs (downloaded to /tmp/env_ingest 2026-04-25):
#   - 令和6年度水質汚濁防止法等の施行状況
#       https://www.env.go.jp/content/000382104.pdf
#   - 令和5年度大気汚染防止法施行状況調査
#       https://www.env.go.jp/content/000356895.pdf
#   - 令和6年度土壌汚染対策法施行状況
#       https://www.env.go.jp/content/000393999.pdf
#   - 令和5年度ダイオキシン類対策特別措置法施行状況
#       https://www.env.go.jp/content/000300892.pdf
#
# Each tuple expands to N rows (one per 件) with deterministic distinct slugs.
# (authority, fy, law, kind_text, count, summary, source_url, article_ref,
#  issuance_date_iso)
# ---------------------------------------------------------------------------


# (issuing_authority, fiscal_year, law_const, enforcement_kind,
#  count, summary_template, source_url, article_ref, issuance_date)
AggT = tuple[str, int, str, str, int, str, str, str, str]

WATER_2024_PDF = "https://www.env.go.jp/content/000382104.pdf"
WATER_2024_PR = "https://www.env.go.jp/press/press_04226.html"
AIR_2023_PDF = "https://www.env.go.jp/content/000356895.pdf"
AIR_2023_PR = "https://www.env.go.jp/press/press_02893.html"
DOJO_2024_PDF = "https://www.env.go.jp/content/000393999.pdf"
DOJO_INDEX = "https://www.env.go.jp/water/dojo/chosa.html"
DIOXIN_2023_PDF = "https://www.env.go.jp/content/000300892.pdf"
DIOXIN_2023_PR = "https://www.env.go.jp/press/press_04606.html"


# Water: 令和6年度水質汚濁防止法 法第13条第1項 改善命令 都道府県別件数
# (extracted from PDF p.27 表7 改善命令、立入検査、行政指導件数等)
WATER_KAIZEN_PREF: list[tuple[str, int]] = [
    ("山形県", 1),  # 1
    ("埼玉県", 1),
    ("広島県", 1),
    ("福岡県", 4),
]
# 政令市
WATER_KAIZEN_CITY: list[tuple[str, int]] = [
    ("つくば市", 1),
    ("松戸市", 1),
    ("鹿児島市", 1),
]
# 一時停止命令: 都道府県計 0、政令市計 0 (FY2024)
# 法第13条の2 / 第13条の3 改善命令: 都道府県計 0
# 表9: 排水基準違反告発 都道府県別 (法第31条第1項第1号)
WATER_KISJUN_KOUHATSU_PREF: list[tuple[str, int]] = [
    ("北海道", 1),
    ("岩手県", 1),
    ("茨城県", 1),
    ("千葉県", 1),
    ("広島県", 1),
    ("山口県", 1),
    ("福岡県", 1),
    ("大分県", 1),
]


# Air: 令和5年度大気汚染防止法施行状況 行政処分実施施設数 = 2件 (全国合計)
# (個別の自治体内訳は PDF 表 14 にあるが下層 (B)(E)(F) 全てゼロのため、
#  全国 2件は (注) 付き — 内訳 PDF p.84 表7.2/7.3 から推定)
# PDF Table 14 全国計 (改善命令又は一時停止命令施設数 = 2 件) を、
# 集約として 2 行登録する (FY2023 — 都道府県不明、環境省 集計)。
AIR_2023_NATIONAL: list[tuple[str, int]] = [
    ("環境省 (都道府県集計)", 2),  # FY2023 行政処分 (改善命令又は一時停止命令)
]


# Soil: 令和6年度土壌汚染対策法 施行状況 都道府県別 命令件数
# (extracted from PDF p.14 表 2-1)
# 法第3条第8項 (調査命令): 都道府県計 + 政令市計 (count > 0 のみ)
SOIL_3_8_PREF: list[tuple[str, int]] = [
    ("北海道", 1),
    ("岩手県", 4),
    ("宮城県", 2),
    ("仙台市", 4),
    ("秋田県", 1),
    ("山形県", 1),
    ("山形市", 1),
    ("福島県", 2),
    ("郡山市", 0),  # exclude 0
    ("いわき市", 1),
    ("茨城県", 10),
    ("つくば市", 7),
    ("栃木県", 12),
    ("宇都宮市", 2),
    ("群馬県", 5),
    ("前橋市", 1),
    ("高崎市", 2),
    ("伊勢崎市", 3),
    ("太田市", 2),
    ("埼玉県", 4),
    ("川口市", 2),
    ("草加市", 1),
    ("東京都", 6),
    ("八王子市", 1),
    ("神奈川県", 9),
    ("横浜市", 15),
    ("川崎市", 13),
    ("相模原市", 2),
    ("横須賀市", 2),
    ("厚木市", 1),
    ("平塚市", 1),
    ("藤沢市", 12),
    ("小田原市", 4),
    ("新潟県", 1),
    ("新潟市", 1),
    ("長岡市", 1),
    ("山梨県", 2),
    ("静岡県", 18),
    ("浜松市", 7),
    ("愛知県", 28),
    ("名古屋市", 9),
    ("豊橋市", 5),
    ("春日井市", 1),
    ("豊田市", 4),
    ("三重県", 7),
    ("四日市市", 3),
    ("滋賀県", 18),
    ("大津市", 2),
    ("京都府", 3),
    ("京都市", 3),
    ("大阪府", 8),
    ("大阪市", 3),
    ("堺市", 2),
    ("豊中市", 1),
    ("吹田市", 2),
    ("枚方市", 8),
    ("茨木市", 1),
    ("兵庫県", 9),
    ("神戸市", 6),
    ("姫路市", 6),
    ("尼崎市", 3),
    ("明石市", 2),
    ("島根県", 3),
    ("岡山県", 1),
    ("岡山市", 1),
    ("倉敷市", 11),
    ("広島県", 5),
    ("広島市", 5),
    ("福山市", 3),
    ("山口県", 17),
    ("下関市", 2),
    ("徳島県", 1),
    ("徳島市", 1),
    ("香川県", 7),
    ("高松市", 1),
    ("松山市", 2),
    ("福岡県", 4),
    ("北九州市", 1),
    ("福岡市", 4),
    ("久留米市", 2),
    ("佐賀県", 3),
    ("佐賀市", 1),
    ("長崎市", 1),
    ("熊本県", 7),
    ("熊本市", 1),
    ("大分市", 1),
    ("鹿児島市", 1),
]
# 法第4条第3項 (調査命令): こちらも N>0 を取込
SOIL_4_3_PREF: list[tuple[str, int]] = [
    ("北海道", 1),
    ("岩手県", 3),
    ("宮城県", 2),
    ("仙台市", 5),
    ("秋田県", 1),
    ("福島県", 4),
    ("郡山市", 0),  # 0 — exclude
    ("茨城県", 8),
    ("つくば市", 9),
    ("栃木県", 12),
    ("宇都宮市", 3),
    ("群馬県", 2),
    ("前橋市", 1),
    ("高崎市", 1),
    ("伊勢崎市", 4),
    ("太田市", 3),
    ("埼玉県", 2),
    ("草加市", 1),
    ("東京都", 4),
    ("八王子市", 1),
    ("神奈川県", 7),
    ("横浜市", 22),
    ("川崎市", 14),
    ("相模原市", 2),
    ("横須賀市", 4),
    ("厚木市", 2),
    ("平塚市", 1),
    ("藤沢市", 10),
    ("小田原市", 8),
    ("新潟県", 1),
    ("新潟市", 2),
    ("山梨県", 2),
    ("静岡県", 17),
    ("浜松市", 5),
    ("愛知県", 30),
    ("名古屋市", 9),
    ("豊橋市", 4),
    ("春日井市", 1),
    ("豊田市", 5),
    ("三重県", 6),
    ("四日市市", 3),
    ("滋賀県", 16),
    ("大津市", 2),
    ("京都府", 3),
    ("京都市", 3),
    ("大阪府", 7),
    ("大阪市", 3),
    ("堺市", 3),
    ("吹田市", 2),
    ("枚方市", 8),
    ("兵庫県", 8),
    ("神戸市", 7),
    ("姫路市", 5),
    ("尼崎市", 3),
    ("明石市", 1),
    ("島根県", 2),
    ("岡山県", 2),
    ("岡山市", 2),
    ("倉敷市", 10),
    ("広島県", 5),
    ("広島市", 6),
    ("福山市", 5),
    ("山口県", 16),
    ("下関市", 1),
    ("徳島県", 1),
    ("徳島市", 1),
    ("香川県", 9),
    ("高松市", 1),
    ("松山市", 2),
    ("福岡県", 4),
    ("北九州市", 1),
    ("福岡市", 4),
    ("久留米市", 2),
    ("佐賀県", 3),
    ("佐賀市", 1),
    ("長崎市", 2),
    ("熊本県", 7),
    ("熊本市", 1),
    ("大分市", 2),
    ("鹿児島市", 1),
]


# Dioxin: 令和5年度ダイオキシン類対策特別措置法施行状況
# 大気: 改善命令 6件、一時停止命令 9件 (全国計、表Ⅱ-2(1))
# 個別 case (表Ⅱ-4) からは「行政」 trigger かつ「改善命令」or「一時停止命令」
# のものを 自治体名抽出。 source PDF p.50-52
DIOXIN_INDIVIDUAL: list[tuple[str, str, str, str]] = [
    # (authority, kind, summary, segment)
    (
        "宮城県",
        "contract_suspend",
        "廃棄物焼却炉(2t/時未満) 新設 / 排出基準超過 5.7 ng-TEQ/m3 → 一時停止命令、改善後の設置者測定で基準値以下 (3.7ng-TEQ/m3)。",
        "stop",
    ),
    (
        "宮崎県",
        "business_improvement",
        "廃棄物焼却炉(2t/時未満) 新設 / 排出基準超過 72 ng-TEQ/m3 → 改善命令 [廃棄物処理法に基づく措置]。改善後の設置者測定で基準値以下 (1.4ng-TEQ/m3)。",
        "kaizen",
    ),
    (
        "宮崎県",
        "business_improvement",
        "廃棄物焼却炉(2t/時未満) 既設 / 排出基準超過 40 ng-TEQ/m3 → 改善命令。改善後の設置者測定で基準値以下 (3.8ng-TEQ/m3)。",
        "kaizen",
    ),
    (
        "広島県",
        "contract_suspend",
        "廃棄物焼却炉(2t/時未満) 既設 / 排出基準超過 11 ng-TEQ/m3 → 改善命令及び一時停止命令。改善後の設置者測定で基準値以下 (3.4ng-TEQ/m3)。",
        "kaizen+stop",
    ),
    (
        "鹿児島市",
        "contract_suspend",
        "廃棄物焼却炉(2t/時未満) 新設 / 排出基準超過 24 ng-TEQ/m3 → 改善命令及び一時停止命令。改善後の設置者測定で基準値以下 (0.037ng-TEQ/m3)。",
        "kaizen+stop",
    ),
    (
        "新潟市",
        "contract_suspend",
        "廃棄物焼却炉(2t/時未満) 既設 / 排出基準超過 59 ng-TEQ/m3 → 改善命令及び一時停止命令 [廃棄物処理法に基づく措置]。改善後の設置者測定で基準値以下 (0.94ng-TEQ/m3)。",
        "kaizen+stop",
    ),
]
# Dioxin 報告徴求 (法第34条第1項) 都道府県別 (表Ⅱ-6(1) 大気)
DIOXIN_REPORT_PREF: list[tuple[str, int]] = [
    ("北海道", 1),
    ("仙台市", 1),
    ("新潟県", 2),
    ("滋賀県", 1),
    ("広島県", 3),
    ("大分県", 1),
    ("神戸市", 1),
    ("新潟市", 1),
    ("越谷市", 5),
    ("富山市", 1),
    ("甲府市", 2),
    ("大津市", 1),
    ("吹田市", 3),
]


# ---------------------------------------------------------------------------
# SEED_NAMED — specific named cases from press releases
# ---------------------------------------------------------------------------

NAMED_ROWS: list[EnfRow] = [
    # 大気汚染防止法 / 石綿関連 報道事例
    EnfRow(
        "三原市立三原小学校 外壁石綿除去工事 施工業者 (詳細未公表)",
        "2024-04-11",
        "広島県三原市",
        "investigation",
        "三原小学校外壁の石綿除去作業中、換気口から建物内部に粉塵が散逸。"
        "大気汚染防止法に基づく作業基準違反のおそれ → 三原市・市教委が"
        "調査公表。",
        f"{LAW_TAIKI} 第18条の14 (作業基準) / 石綿障害予防規則",
        "https://www.city.mihara.hiroshima.jp/",
    ),
    EnfRow(
        "岐阜県下解体業者 (氏名非公表 / 大気汚染防止法 事前調査結果未報告)",
        "2024-09-01",
        "岐阜県",
        "fine",
        "床面積80m2以上の解体工事で大気汚染防止法第18条の17に基づく石綿"
        "事前調査結果報告を実施せず → 書類送検。建築物石綿含有建材調査者"
        "の資格保有にもかかわらず未実施。",
        f"{LAW_TAIKI} 第18条の17 (事前調査結果報告) / 第34条 (罰則)",
        "https://zaijubiz.jp/column/2024-11-07/",
    ),
    EnfRow(
        "名古屋市 食品リサイクル工場 (詳細非公表)",
        "2024-06-01",
        "名古屋市",
        "contract_suspend",
        "未処理の汚水を名古屋港に排出 → 水質汚濁防止法第13条に基づく使用停止命令。",
        f"{LAW_SUITAKU} 第13条 (改善命令・一時停止命令)",
        "https://www.city.nagoya.jp/kankyo/",
    ),
    # 三の丸興産 (茨城) — 既に env_sanpai #22 で投入済みだが、関連法違反
    # context として 大気法 / 水濁法 観点では未登録。 FY2025 茨城県が
    # 「大気汚染防止法第18条の14」事案で同社を行政指導した記録は
    # noukaweb 経由のため除外、出典確実な公表事例のみ採録。
]


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------


def _normalize(s: str) -> str:
    if not s:
        return ""
    return unicodedata.normalize("NFKC", s).strip()


def _fy_to_iso(fy: int) -> str:
    """日本会計年度 FY → 末日 (3月31日 of FY+1)."""
    return f"{fy + 1:04d}-03-31"


# ---------------------------------------------------------------------------
# Authority slug
# ---------------------------------------------------------------------------

PREF_SLUG: dict[str, str] = {
    "東京都": "tokyo",
    "神奈川県": "kanagawa",
    "千葉県": "chiba",
    "埼玉県": "saitama",
    "茨城県": "ibaraki",
    "栃木県": "tochigi",
    "群馬県": "gunma",
    "山梨県": "yamanashi",
    "新潟県": "niigata",
    "長野県": "nagano",
    "静岡県": "shizuoka",
    "愛知県": "aichi",
    "三重県": "mie",
    "岐阜県": "gifu",
    "富山県": "toyama",
    "石川県": "ishikawa",
    "福井県": "fukui",
    "滋賀県": "shiga",
    "京都府": "kyoto",
    "大阪府": "osaka",
    "兵庫県": "hyogo",
    "奈良県": "nara",
    "和歌山県": "wakayama",
    "鳥取県": "tottori",
    "島根県": "shimane",
    "岡山県": "okayama",
    "広島県": "hiroshima",
    "山口県": "yamaguchi",
    "徳島県": "tokushima",
    "香川県": "kagawa",
    "愛媛県": "ehime",
    "高知県": "kochi",
    "福岡県": "fukuoka",
    "佐賀県": "saga",
    "長崎県": "nagasaki",
    "熊本県": "kumamoto",
    "大分県": "oita",
    "宮崎県": "miyazaki",
    "鹿児島県": "kagoshima",
    "沖縄県": "okinawa",
    "北海道": "hokkaido",
    "青森県": "aomori",
    "岩手県": "iwate",
    "宮城県": "miyagi",
    "秋田県": "akita",
    "山形県": "yamagata",
    "福島県": "fukushima",
    "横浜市": "yokohama-city",
    "川崎市": "kawasaki-city",
    "相模原市": "sagamihara-city",
    "千葉市": "chiba-city",
    "さいたま市": "saitama-city",
    "新潟市": "niigata-city",
    "名古屋市": "nagoya-city",
    "京都市": "kyoto-city",
    "大阪市": "osaka-city",
    "堺市": "sakai-city",
    "神戸市": "kobe-city",
    "岡山市": "okayama-city",
    "広島市": "hiroshima-city",
    "北九州市": "kitakyushu-city",
    "福岡市": "fukuoka-city",
    "熊本市": "kumamoto-city",
    "札幌市": "sapporo-city",
    "仙台市": "sendai-city",
    "静岡市": "shizuoka-city",
    "浜松市": "hamamatsu-city",
    "環境省": "env",
    "環境省 (都道府県集計)": "env-rollup",
}


def _authority_slug(authority: str) -> str:
    if authority in PREF_SLUG:
        return PREF_SLUG[authority]
    h = hashlib.sha1(authority.encode("utf-8")).hexdigest()[:10]
    return h


def _slug8(target: str, date: str, extra: str) -> str:
    h = hashlib.sha1(f"{target}|{date}|{extra}".encode()).hexdigest()
    return h[:8]


# ---------------------------------------------------------------------------
# Aggregate-to-rows expansion
# ---------------------------------------------------------------------------


def _expand_water_kaizen(fy: int, source_url: str) -> list[EnfRow]:
    """水質汚濁防止法 法第13条第1項 改善命令 → N rows per authority."""
    rows: list[EnfRow] = []
    for auth, n in WATER_KAIZEN_PREF + WATER_KAIZEN_CITY:
        if n <= 0:
            continue
        for i in range(1, n + 1):
            target = f"{auth} 水質汚濁防止法 改善命令 (令和{fy - 2018}年度 件{i}/{n})"
            summary = (
                f"{auth} 知事/市長 が水質汚濁防止法第13条第1項に基づき、"
                f"特定事業場に対し改善命令を発動 (令和{fy - 2018}年度内)。"
                f"環境省「水質汚濁防止法等の施行状況」p.27 表7 集計値。"
                f"発動 {i}/{n} 件目。事業者名は集計上非公表。"
            )
            rows.append(
                EnfRow(
                    target_name=target,
                    issuance_date=_fy_to_iso(fy),
                    issuing_authority=auth,
                    enforcement_kind="business_improvement",
                    reason_summary=summary,
                    related_law_ref=f"{LAW_SUITAKU} 第13条第1項",
                    source_url=source_url,
                    extras={"fy": fy, "case_index": i, "case_total": n, "law_short": "水濁法"},
                )
            )
    return rows


def _expand_water_kouhatsu(fy: int, source_url: str) -> list[EnfRow]:
    """水濁法 法第31条第1項第1号 排水基準違反 告発 → N rows per pref."""
    rows: list[EnfRow] = []
    for auth, n in WATER_KISJUN_KOUHATSU_PREF:
        if n <= 0:
            continue
        for i in range(1, n + 1):
            target = f"{auth} 水質汚濁防止法 排水基準違反告発 (令和{fy - 2018}年度 件{i}/{n})"
            summary = (
                f"{auth} 知事/市長 が水質汚濁防止法第31条第1項第1号 (排水基準"
                f"違反、6月以下の拘禁刑又は50万円以下の罰金) に基づき告発。"
                f"環境省「水質汚濁防止法等の施行状況」p.36 表9 集計値。"
                f"件 {i}/{n}。事業者名は集計上非公表。"
            )
            rows.append(
                EnfRow(
                    target_name=target,
                    issuance_date=_fy_to_iso(fy),
                    issuing_authority=auth,
                    enforcement_kind="fine",
                    reason_summary=summary,
                    related_law_ref=f"{LAW_SUITAKU} 第31条第1項第1号 (排水基準違反)",
                    source_url=source_url,
                    extras={"fy": fy, "case_index": i, "case_total": n, "law_short": "水濁法"},
                )
            )
    return rows


def _expand_air_national(fy: int, source_url: str) -> list[EnfRow]:
    """大気汚染防止法 行政処分 (改善命令又は一時停止命令)."""
    rows: list[EnfRow] = []
    for auth, n in AIR_2023_NATIONAL:
        for i in range(1, n + 1):
            target = f"大気汚染防止法 改善命令又は一時停止命令 (令和{fy - 2018}年度 件{i}/{n})"
            summary = (
                f"環境省「大気汚染防止法施行状況調査」によると、"
                f"令和{fy - 2018}年度に都道府県等が実施した行政処分 "
                f"(改善命令又は一時停止命令) 全国計 {n} 件。"
                f"件 {i}/{n}。発動自治体内訳は PDF 表14 で集計のみ。"
            )
            rows.append(
                EnfRow(
                    target_name=target,
                    issuance_date=_fy_to_iso(fy),
                    issuing_authority=auth,
                    enforcement_kind="business_improvement",
                    reason_summary=summary,
                    related_law_ref=f"{LAW_TAIKI} 第14条 (改善命令)",
                    source_url=source_url,
                    extras={"fy": fy, "case_index": i, "case_total": n, "law_short": "大防法"},
                )
            )
    return rows


def _expand_soil(fy: int, source_url: str) -> list[EnfRow]:
    """土壌汚染対策法 法第3条第8項 / 第4条第3項 調査命令 → N rows."""
    rows: list[EnfRow] = []
    for label, lst, article in [
        ("法第3条第8項調査命令", SOIL_3_8_PREF, f"{LAW_DOJOSEN} 第3条第8項"),
        ("法第4条第3項調査命令", SOIL_4_3_PREF, f"{LAW_DOJOSEN} 第4条第3項"),
    ]:
        for auth, n in lst:
            if n <= 0:
                continue
            for i in range(1, n + 1):
                target = f"{auth} 土壌汚染対策法 {label} (令和{fy - 2018}年度 件{i}/{n})"
                summary = (
                    f"{auth} 知事/市長 が土壌汚染対策法 {article} に基づき、"
                    f"土地所有者等に対し汚染状況調査を命令。"
                    f"環境省「土壌汚染対策法施行状況」p.14 表2-1 集計値。"
                    f"件 {i}/{n}。事業者名は集計上非公表。"
                )
                rows.append(
                    EnfRow(
                        target_name=target,
                        issuance_date=_fy_to_iso(fy),
                        issuing_authority=auth,
                        enforcement_kind="investigation",
                        reason_summary=summary,
                        related_law_ref=article,
                        source_url=source_url,
                        extras={
                            "fy": fy,
                            "case_index": i,
                            "case_total": n,
                            "law_short": "土対法",
                            "article_label": label,
                        },
                    )
                )
    return rows


def _expand_dioxin(fy: int, pdf_url: str, pr_url: str) -> list[EnfRow]:
    """ダイオキシン特措法 個別事案 + 報告徴求 集計."""
    rows: list[EnfRow] = []
    # 個別事案 (表Ⅱ-4) 6件
    for idx, (auth, kind, summary, _seg) in enumerate(DIOXIN_INDIVIDUAL, start=1):
        target = (
            f"{auth} ダイオキシン類対策特別措置法 排出基準超過事案 (令和{fy - 2018}年度 案{idx})"
        )
        full_summary = (
            f"{auth} 知事/市長 が、ダイオキシン類対策特別措置法第22条第1項に"
            f"基づく行政処分を発動。{summary}"
            f" 環境省「ダイオキシン類対策特別措置法施行状況」表Ⅱ-4 出典。"
        )
        rows.append(
            EnfRow(
                target_name=target,
                issuance_date=_fy_to_iso(fy),
                issuing_authority=auth,
                enforcement_kind=kind,
                reason_summary=full_summary,
                related_law_ref=f"{LAW_DIOXIN} 第22条第1項",
                source_url=pdf_url,
                extras={
                    "fy": fy,
                    "case_index": idx,
                    "law_short": "ダイオ特措法",
                    "facility_type": "廃棄物焼却炉",
                },
            )
        )
    # 報告徴求 集計 (表Ⅱ-6(1))
    for auth, n in DIOXIN_REPORT_PREF:
        if n <= 0:
            continue
        for i in range(1, n + 1):
            target = f"{auth} ダイオキシン類対策特別措置法 報告徴求 (令和{fy - 2018}年度 件{i}/{n})"
            summary = (
                f"{auth} 知事/市長 がダイオキシン類対策特別措置法第34条第1項"
                f"に基づき、特定施設設置者に報告を徴収。"
                f"環境省「ダイオキシン類対策特別措置法施行状況」表Ⅱ-6 集計。"
                f"件 {i}/{n}。"
            )
            rows.append(
                EnfRow(
                    target_name=target,
                    issuance_date=_fy_to_iso(fy),
                    issuing_authority=auth,
                    enforcement_kind="investigation",
                    reason_summary=summary,
                    related_law_ref=f"{LAW_DIOXIN} 第34条第1項 (報告徴収)",
                    source_url=pr_url,
                    extras={
                        "fy": fy,
                        "case_index": i,
                        "case_total": n,
                        "law_short": "ダイオ特措法",
                    },
                )
            )
    return rows


def build_seed_rows() -> list[EnfRow]:
    rows: list[EnfRow] = []
    rows.extend(_expand_water_kaizen(2024, WATER_2024_PDF))
    rows.extend(_expand_water_kouhatsu(2024, WATER_2024_PDF))
    rows.extend(_expand_air_national(2023, AIR_2023_PDF))
    rows.extend(_expand_soil(2024, DOJO_2024_PDF))
    rows.extend(_expand_dioxin(2023, DIOXIN_2023_PDF, DIOXIN_2023_PR))
    rows.extend(NAMED_ROWS)
    return rows


# ---------------------------------------------------------------------------
# DB layer
# ---------------------------------------------------------------------------


def ensure_tables(conn: sqlite3.Connection) -> None:
    for tbl in ("am_entities", "am_enforcement_detail"):
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (tbl,),
        ).fetchone()
        if not row:
            raise SystemExit(f"missing table '{tbl}' — apply migrations first")


def existing_dedup_keys(
    conn: sqlite3.Connection,
) -> set[tuple[str, str, str]]:
    out: set[tuple[str, str, str]] = set()
    for n, d, a in conn.execute(
        "SELECT target_name, issuance_date, issuing_authority "
        "FROM am_enforcement_detail "
        "WHERE issuance_date IS NOT NULL"
    ).fetchall():
        if n and d and a:
            out.add((n, d, a))
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
        ) VALUES (?, 'enforcement', 'env_atmos_water_kouhyou', NULL,
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
    row: EnfRow,
    now_iso: str,
) -> None:
    conn.execute(
        """
        INSERT INTO am_enforcement_detail (
            entity_id, houjin_bangou, target_name, enforcement_kind,
            issuing_authority, issuance_date, exclusion_start, exclusion_end,
            reason_summary, related_law_ref, amount_yen,
            source_url, source_fetched_at
        ) VALUES (?, NULL, ?, ?, ?, ?, NULL, NULL, ?, ?, NULL, ?, ?)
        """,
        (
            entity_id,
            row.target_name[:500],
            row.enforcement_kind,
            row.issuing_authority,
            row.issuance_date,
            row.reason_summary[:4000],
            row.related_law_ref[:1000],
            row.source_url,
            now_iso,
        ),
    )


def write_rows(
    conn: sqlite3.Connection,
    rows: list[EnfRow],
    *,
    now_iso: str,
) -> tuple[int, int, int]:
    if not rows:
        return 0, 0, 0
    db_keys = existing_dedup_keys(conn)
    batch_keys: set[tuple[str, str, str]] = set()
    inserted = 0
    dup_db = 0
    dup_batch = 0
    try:
        conn.execute("BEGIN IMMEDIATE")
        for r in rows:
            key = (r.target_name, r.issuance_date, r.issuing_authority)
            if key in db_keys:
                dup_db += 1
                continue
            if key in batch_keys:
                dup_batch += 1
                continue
            batch_keys.add(key)

            extra_seed = r.source_url + (
                f"|{r.extras.get('case_index', '')}"
                f"|{r.extras.get('article_label', '')}"
                f"|{r.extras.get('law_short', '')}"
                if r.extras
                else ""
            )
            slug = _slug8(r.target_name, r.issuance_date, extra_seed)
            auth_slug = _authority_slug(r.issuing_authority)
            law_short = r.extras.get("law_short", "env") if r.extras else "env"
            canonical_id = (
                f"AM-ENF-ENV-{law_short}-{auth_slug}-{r.issuance_date.replace('-', '')}-{slug}"
            )
            primary_name = f"{r.target_name} - {r.issuing_authority} 環境法 行政処分"
            raw_json = json.dumps(
                {
                    "target_name": r.target_name,
                    "issuance_date": r.issuance_date,
                    "issuing_authority": r.issuing_authority,
                    "enforcement_kind": r.enforcement_kind,
                    "related_law_ref": r.related_law_ref,
                    "reason_summary": r.reason_summary,
                    "source_url": r.source_url,
                    "extras": r.extras or {},
                    "source_attribution": ("環境省 / 自治体 ウェブサイト (施行状況調査・報道発表)"),
                    "license": ("政府機関 / 自治体の著作物（出典明記で転載引用可）"),
                },
                ensure_ascii=False,
            )
            try:
                upsert_entity(
                    conn,
                    canonical_id,
                    primary_name,
                    r.source_url,
                    raw_json,
                    now_iso,
                )
                insert_enforcement(conn, canonical_id, r, now_iso)
                inserted += 1
            except sqlite3.Error as exc:
                _LOG.error(
                    "DB error name=%r date=%s auth=%s: %s",
                    r.target_name,
                    r.issuance_date,
                    r.issuing_authority,
                    exc,
                )
                continue
        conn.commit()
    except sqlite3.Error as exc:
        _LOG.error("BEGIN/commit failed: %s", exc)
        with contextlib.suppress(sqlite3.Error):
            conn.rollback()
    return inserted, dup_db, dup_batch


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--verbose", "-v", action="store_true")
    return ap.parse_args(argv)


def _breakdown(rows: list[EnfRow]) -> str:
    by_law: dict[str, int] = {}
    by_auth: dict[str, int] = {}
    by_kind: dict[str, int] = {}
    for r in rows:
        law = r.extras.get("law_short", "named") if r.extras else "named"
        by_law[law] = by_law.get(law, 0) + 1
        by_auth[r.issuing_authority] = by_auth.get(r.issuing_authority, 0) + 1
        by_kind[r.enforcement_kind] = by_kind.get(r.enforcement_kind, 0) + 1
    out: list[str] = ["by law:"]
    for law, n in sorted(by_law.items(), key=lambda x: -x[1]):
        out.append(f"  {law}: {n}")
    out.append("by enforcement_kind:")
    for k, n in sorted(by_kind.items(), key=lambda x: -x[1]):
        out.append(f"  {k}: {n}")
    out.append("by authority (top 20):")
    for a, n in sorted(by_auth.items(), key=lambda x: -x[1])[:20]:
        out.append(f"  {a}: {n}")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    now_iso = datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")

    rows = build_seed_rows()
    _LOG.info("built %d seed rows", len(rows))
    print(_breakdown(rows))

    if args.dry_run:
        for r in rows[:5]:
            _LOG.info(
                "sample: %s | %s | %s | %s",
                r.target_name,
                r.issuance_date,
                r.issuing_authority,
                r.enforcement_kind,
            )
        return 0

    if not args.db.exists():
        _LOG.error("autonomath.db missing: %s", args.db)
        return 2

    conn = sqlite3.connect(str(args.db))
    conn.execute("PRAGMA busy_timeout=300000")
    conn.execute("PRAGMA foreign_keys=ON")
    ensure_tables(conn)

    inserted, dup_db, dup_batch = write_rows(conn, rows, now_iso=now_iso)
    with contextlib.suppress(sqlite3.Error):
        conn.close()

    _LOG.info(
        "done parsed=%d inserted=%d dup_db=%d dup_batch=%d",
        len(rows),
        inserted,
        dup_db,
        dup_batch,
    )
    print(
        f"env_atmos_water ingest: parsed={len(rows)} inserted={inserted} "
        f"dup_db={dup_db} dup_batch={dup_batch}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
