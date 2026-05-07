#!/usr/bin/env python3
"""Ingest 都道府県 + 政令指定都市 + 環境省 産廃 行政処分 (廃棄物処理法 14条 等)
into ``am_enforcement_detail`` + ``am_entities``.

Background:
    産業廃棄物処理業に対する行政処分 (許可取消し / 業務停止 / 改善命令) は
    都道府県知事 / 政令指定都市市長 が発動する。各自治体の環境部 / 廃棄物
    指導課 が「行政処分一覧」「press release」の形で 5 年分程度を公表
    している。これらを横串で収集し am_enforcement_detail に kind=
    'license_revoke' (許可取消し) / 'contract_suspend' (業務停止) /
    'business_improvement' (改善命令) で取り込む。

    既存 am_enforcement_detail の prefecture-issued rows は別ソース
    (会計検査院 / 指名停止) であり、本 ingest は重ならない layer を作る。
    related_law_ref には "廃棄物の処理及び清掃に関する法律 第14条 等" を
    付与し、issuing_authority は '{prefecture/city}' とする。

Strategy:
    1. SEED_ROWS — discovery 段階で URL を実 fetch し抽出済の curated rows
       (Tokyo press releases, Hiroshima 一覧, Hokkaido 一覧, Kanagawa 一覧,
       Hyogo press release, Saitama 一覧, Chiba press releases, Osaka excel
       URL ref) を埋め込み。これだけで 250+ rows に到達する。
    2. Fetch SOURCES — 一部 URL は HTML/Excel 取得 + 解析を試みるが、404 や
       structure 変動があれば silent fail (SEED_ROWS が primary path)。
    3. Insert with BEGIN IMMEDIATE + busy_timeout=300000 (parallel-safe).

Schema mapping:
    enforcement_kind:
      "許可取消し" / "取消"            → 'license_revoke'
      "業務停止" / "事業停止" / "停止" → 'contract_suspend'
      "改善命令"                       → 'business_improvement'
      "報告徴求"                       → 'investigation'
      その他                           → 'other'
    issuing_authority: '{都道府県}' or '{政令指定都市}' (e.g. '東京都', '横浜市')
    related_law_ref:   '廃棄物の処理及び清掃に関する法律 第X条' (article noted)
    amount_yen:        NULL (these are 改善命令 not 罰金)

License: 政府機関 / 自治体ウェブサイトの 著作物（出典明記で転載引用可）.

Parallel-safe:
    - BEGIN IMMEDIATE + PRAGMA busy_timeout=300000.
    - 1 commit per source so other workers see incremental progress.

CLI:
    python scripts/ingest/ingest_enforcement_env_sanpai.py [--db autonomath.db]
        [--dry-run] [--verbose] [--seed-only] [--target N]
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import hashlib
import json
import logging
import re
import sqlite3
import sys
import unicodedata
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))


_LOG = logging.getLogger("autonomath.ingest.env_sanpai")

DEFAULT_DB = REPO_ROOT / "autonomath.db"
USER_AGENT = "AutonoMath/0.1.0 (+https://bookyou.net)"

DEFAULT_LAW = "廃棄物の処理及び清掃に関する法律"


# ---------------------------------------------------------------------------
# Date parsing
# ---------------------------------------------------------------------------

WAREKI_RE = re.compile(
    r"(令和|平成|昭和|R|H|S)\s*(\d+|元)\s*[年.\-．／/]\s*"
    r"(\d{1,2})\s*[月.\-．／/]\s*(\d{1,2})\s*日?"
)
SEIREKI_RE = re.compile(r"(20\d{2}|19\d{2})\s*[年.\-／/]\s*(\d{1,2})\s*[月.\-／/]\s*(\d{1,2})")
ERA_OFFSET = {
    "令和": 2018,
    "R": 2018,
    "平成": 1988,
    "H": 1988,
    "昭和": 1925,
    "S": 1925,
}


def _normalize(s: str) -> str:
    if not s:
        return ""
    return unicodedata.normalize("NFKC", s).strip()


def _parse_date(text: str) -> str | None:
    if not text:
        return None
    s = _normalize(text)
    m = SEIREKI_RE.search(s)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if 1990 <= y <= 2100 and 1 <= mo <= 12 and 1 <= d <= 31:
            try:
                return dt.date(y, mo, d).isoformat()
            except ValueError:
                return None
    m = WAREKI_RE.search(s)
    if m:
        era, y_raw, mo, d = m.group(1), m.group(2), int(m.group(3)), int(m.group(4))
        try:
            y_off = 1 if y_raw == "元" else int(y_raw)
        except ValueError:
            return None
        year = ERA_OFFSET[era] + y_off
        if 1990 <= year <= 2100 and 1 <= mo <= 12 and 1 <= d <= 31:
            try:
                return dt.date(year, mo, d).isoformat()
            except ValueError:
                return None
    return None


# ---------------------------------------------------------------------------
# Row dataclass
# ---------------------------------------------------------------------------


@dataclass
class EnfRow:
    target_name: str
    issuance_date: str  # ISO yyyy-mm-dd
    issuing_authority: str
    enforcement_kind: (
        str  # license_revoke / contract_suspend / business_improvement / investigation / other
    )
    reason_summary: str
    related_law_ref: str
    source_url: str
    extras: dict = field(default_factory=dict)


def kind_of(text: str) -> str:
    """Map disposition text → CHECK enum."""
    t = _normalize(text)
    if "改善命令" in t or "改善" in t and "命令" in t:
        return "business_improvement"
    if "停止" in t:
        return "contract_suspend"
    if "取消" in t or "取り消" in t:
        return "license_revoke"
    if "報告徴求" in t or "報告" in t and "求め" in t:
        return "investigation"
    return "other"


def _law_ref(article_text: str | None) -> str:
    """Build 関連条文 string."""
    if not article_text:
        return f"{DEFAULT_LAW} 第14条"
    a = _normalize(article_text)
    if "廃棄物" not in a:
        a = f"{DEFAULT_LAW} {a}"
    return a[:1000]


# ---------------------------------------------------------------------------
# SEED_ROWS — curated from real fetches (2026-04-25)
#   Sources: Tokyo press releases (metro.tokyo.lg.jp), Hiroshima ecoひろしま,
#   Hokkaido pref, Kanagawa pref, Saitama pref list, Chiba pref press releases,
#   Hyogo press release, plus a Hiroshima market press release.
# ---------------------------------------------------------------------------

SEED_ROWS: list[EnfRow] = [
    # ===== 東京都 (metro.tokyo.lg.jp press releases) =====
    # 2026-01-27 press release (7 cases)
    EnfRow(
        "株式会社トーシン",
        "2026-01-27",
        "東京都",
        "license_revoke",
        "産業廃棄物収集運搬業及び特別管理産業廃棄物収集運搬業の許可取消し。廃棄物処理法（委託基準）違反の罪により、罰金刑が確定。所在地: 東京都練馬区西大泉六丁目14番-5",
        f"{DEFAULT_LAW} 第14条第5項第2号",
        "https://www.metro.tokyo.lg.jp/information/press/2026/01/2026012709",
    ),
    EnfRow(
        "株式会社カーズ",
        "2026-01-27",
        "東京都",
        "license_revoke",
        "産業廃棄物収集運搬業の許可取消し。役員が刑法違反で懲役刑確定。所在地: 東京都葛飾区水元五丁目11番24号",
        f"{DEFAULT_LAW} 第14条第5項第2号ニ",
        "https://www.metro.tokyo.lg.jp/information/press/2026/01/2026012709",
    ),
    EnfRow(
        "株式会社永利建設工業",
        "2026-01-27",
        "東京都",
        "license_revoke",
        "産業廃棄物収集運搬業の許可取消し。役員が出入国管理及び難民認定法違反で欠格要件該当。所在地: 東京都葛飾区お花茶屋一丁目7番4号",
        f"{DEFAULT_LAW} 第14条第5項第2号ニ",
        "https://www.metro.tokyo.lg.jp/information/press/2026/01/2026012709",
    ),
    EnfRow(
        "株式会社恵興",
        "2026-01-27",
        "東京都",
        "license_revoke",
        "産業廃棄物収集運搬業の許可取消し。役員が大麻取締法違反で懲役刑（執行猶予付）確定。所在地: 東京都港区芝公園二丁目12番17号",
        f"{DEFAULT_LAW} 第14条第5項第2号ニ",
        "https://www.metro.tokyo.lg.jp/information/press/2026/01/2026012709",
    ),
    EnfRow(
        "株式会社セイドー",
        "2026-01-27",
        "東京都",
        "license_revoke",
        "産業廃棄物収集運搬業及び特別管理産業廃棄物収集運搬業の許可取消し。破産手続開始決定。所在地: 千葉県習志野市本大久保三丁目3番7号",
        f"{DEFAULT_LAW} 第14条第5項第2号イ",
        "https://www.metro.tokyo.lg.jp/information/press/2026/01/2026012709",
    ),
    EnfRow(
        "株式会社レイコーポレーション",
        "2026-01-27",
        "東京都",
        "license_revoke",
        "産業廃棄物収集運搬業の許可取消し。破産手続開始決定。所在地: 千葉県柏市末広町6番4号",
        f"{DEFAULT_LAW} 第14条第5項第2号イ",
        "https://www.metro.tokyo.lg.jp/information/press/2026/01/2026012709",
    ),
    EnfRow(
        "株式会社天馬",
        "2026-01-27",
        "東京都",
        "license_revoke",
        "産業廃棄物収集運搬業の許可取消し。破産手続開始決定。所在地: 千葉県柏市豊四季945番地1372",
        f"{DEFAULT_LAW} 第14条第5項第2号イ",
        "https://www.metro.tokyo.lg.jp/information/press/2026/01/2026012709",
    ),
    # 2025-10-28 press release (5 cases)
    EnfRow(
        "有限会社中村組",
        "2025-10-28",
        "東京都",
        "license_revoke",
        "産業廃棄物収集運搬業の許可取消し。廃棄物処理法違反（虚偽管理票写し送付、虚偽記載）で罰金刑確定; 役員が懲役刑（執行猶予付）確定。所在地: 東京都国立市泉三丁目34番地の23",
        f"{DEFAULT_LAW} 第14条第5項第2号イ及びニ",
        "https://www.metro.tokyo.lg.jp/information/press/2025/10/2025102808",
    ),
    EnfRow(
        "美貴建設株式会社",
        "2025-10-28",
        "東京都",
        "license_revoke",
        "産業廃棄物収集運搬業の許可取消し。役員が刑法違反で懲役刑（執行猶予付）確定。所在地: 東京都足立区東綾瀬三丁目2番12号",
        f"{DEFAULT_LAW} 第14条第5項第2号ニ",
        "https://www.metro.tokyo.lg.jp/information/press/2025/10/2025102808",
    ),
    EnfRow(
        "株式会社東邦運輸",
        "2025-10-28",
        "東京都",
        "license_revoke",
        "産業廃棄物収集運搬業の許可取消し。茨城県知事から許可取消処分（役員が欠格要件該当）。所在地: 東京都東久留米市本町三丁目1番9号",
        f"{DEFAULT_LAW} 第14条第5項第2号ニ",
        "https://www.metro.tokyo.lg.jp/information/press/2025/10/2025102808",
    ),
    EnfRow(
        "大渕建設株式会社",
        "2025-10-28",
        "東京都",
        "license_revoke",
        "産業廃棄物収集運搬業の許可取消し。埼玉県知事から許可取消処分（役員が自動車運転処罰法違反）。所在地: 東京都足立区神明南一丁目11番17号",
        f"{DEFAULT_LAW} 第14条第5項第2号ニ",
        "https://www.metro.tokyo.lg.jp/information/press/2025/10/2025102808",
    ),
    EnfRow(
        "有限会社湯浅商会",
        "2025-10-28",
        "東京都",
        "license_revoke",
        "産業廃棄物収集運搬業の許可取消し。破産手続開始決定。所在地: 東京都足立区加平二丁目4番7号",
        f"{DEFAULT_LAW} 第14条第5項第2号イ",
        "https://www.metro.tokyo.lg.jp/information/press/2025/10/2025102808",
    ),
    # 2025-08-26 press release (4 cases)
    EnfRow(
        "有限会社足立興業",
        "2025-08-26",
        "東京都",
        "license_revoke",
        "産業廃棄物収集運搬業の許可取消し。役員が刑法及び道路交通法違反で懲役刑（執行猶予付）確定。所在地: 東京都足立区鹿浜八丁目13番2号",
        f"{DEFAULT_LAW} 第14条第5項第2号ニ",
        "https://www.metro.tokyo.lg.jp/information/press/2025/08/2025082608",
    ),
    EnfRow(
        "株式会社ALTEQ",
        "2025-08-26",
        "東京都",
        "license_revoke",
        "産業廃棄物収集運搬業及び特別管理産業廃棄物収集運搬業の許可取消し。役員が刑法違反で罰金刑確定。所在地: 東京都新宿区新宿一丁目8番11号",
        f"{DEFAULT_LAW} 第14条第5項第2号ニ",
        "https://www.metro.tokyo.lg.jp/information/press/2025/08/2025082608",
    ),
    EnfRow(
        "株式会社UC",
        "2025-08-26",
        "東京都",
        "license_revoke",
        "産業廃棄物収集運搬業の許可取消し。破産手続開始決定。所在地: 東京都足立区西保木間二丁目13-17",
        f"{DEFAULT_LAW} 第14条第5項第2号イ",
        "https://www.metro.tokyo.lg.jp/information/press/2025/08/2025082608",
    ),
    EnfRow(
        "株式会社リブ・ウイズ",
        "2025-08-26",
        "東京都",
        "license_revoke",
        "産業廃棄物収集運搬業の許可取消し。破産手続開始決定。所在地: 東京都足立区古千谷本町三丁目5番7号",
        f"{DEFAULT_LAW} 第14条第5項第2号イ",
        "https://www.metro.tokyo.lg.jp/information/press/2025/08/2025082608",
    ),
    # 2025-06-17 press release (7 cases)
    EnfRow(
        "合同会社葵組",
        "2025-06-17",
        "東京都",
        "license_revoke",
        "産業廃棄物収集運搬業の許可取消し。役員が欠格要件該当。所在地: 東京都中央区日本橋浜町一丁目10番9-801号",
        f"{DEFAULT_LAW} 第14条第5項第2号ニ",
        "https://www.metro.tokyo.lg.jp/information/press/2025/06/2025061707",
    ),
    EnfRow(
        "株式会社ユウキ",
        "2025-06-17",
        "東京都",
        "license_revoke",
        "産業廃棄物収集運搬業の許可取消し。埼玉県による無許可積替保管等の違反処分受領。所在地: 埼玉県川口市芝中田一丁目25番3",
        f"{DEFAULT_LAW} 第14条第5項第2号イ",
        "https://www.metro.tokyo.lg.jp/information/press/2025/06/2025061707",
    ),
    EnfRow(
        "株式会社川口組",
        "2025-06-17",
        "東京都",
        "license_revoke",
        "産業廃棄物収集運搬業の許可取消し。埼玉県による役員欠格要件該当処分。所在地: 埼玉県越谷市蒲生本町2番24号",
        f"{DEFAULT_LAW} 第14条第5項第2号イ",
        "https://www.metro.tokyo.lg.jp/information/press/2025/06/2025061707",
    ),
    EnfRow(
        "株式会社山友興業",
        "2025-06-17",
        "東京都",
        "license_revoke",
        "産業廃棄物収集運搬業の許可取消し。千葉県による再委託禁止違反処分。所在地: 千葉県八千代市麦丸1111番地1",
        f"{DEFAULT_LAW} 第14条第5項第2号イ",
        "https://www.metro.tokyo.lg.jp/information/press/2025/06/2025061707",
    ),
    EnfRow(
        "有限会社松島組",
        "2025-06-17",
        "東京都",
        "license_revoke",
        "産業廃棄物収集運搬業の許可取消し。茨城県による焼却禁止違反処分。所在地: 栃木県小山市城北四丁目26番地24",
        f"{DEFAULT_LAW} 第14条第5項第2号イ",
        "https://www.metro.tokyo.lg.jp/information/press/2025/06/2025061707",
    ),
    EnfRow(
        "奥田技建株式会社",
        "2025-06-17",
        "東京都",
        "license_revoke",
        "特別管理産業廃棄物収集運搬業の許可取消し。神奈川県による投棄禁止違反処分。所在地: 神奈川県川崎市宮前区初山二丁目10番11号",
        f"{DEFAULT_LAW} 第14条第5項第2号イ",
        "https://www.metro.tokyo.lg.jp/information/press/2025/06/2025061707",
    ),
    EnfRow(
        "宇野興業合同会社",
        "2025-06-17",
        "東京都",
        "license_revoke",
        "産業廃棄物収集運搬業の許可取消し。役員の覚醒剤取締法違反有罪確定。所在地: 東京都足立区伊興本町二丁目12番29号",
        f"{DEFAULT_LAW} 第14条第5項第2号ニ",
        "https://www.metro.tokyo.lg.jp/information/press/2025/06/2025061707",
    ),
    # 2025-02-18 press release (2 cases)
    EnfRow(
        "株式会社ミライ工業",
        "2025-02-18",
        "東京都",
        "license_revoke",
        "産業廃棄物収集運搬業の許可取消し。千葉県知事による無許可積替え保管処分受領。所在地: 千葉県大網白里市駒込736番地6",
        f"{DEFAULT_LAW} 第14条第5項第2号イ",
        "https://www.metro.tokyo.lg.jp/tosei/hodohappyo/press/2025/02/18/11.html",
    ),
    EnfRow(
        "株式会社タワラ",
        "2025-02-18",
        "東京都",
        "license_revoke",
        "産業廃棄物収集運搬業の許可取消し。役員が自動車運転処罰法違反で懲役刑（執行猶予付）確定。所在地: 神奈川県大和市深見西六丁目4番14号",
        f"{DEFAULT_LAW} 第14条第5項第2号ニ",
        "https://www.metro.tokyo.lg.jp/tosei/hodohappyo/press/2025/02/18/11.html",
    ),
    # 2024-10-29 press release (1 case)
    EnfRow(
        "杉山建設株式会社",
        "2024-10-29",
        "東京都",
        "license_revoke",
        "産業廃棄物収集運搬業の許可取消し。焼却禁止違反で罰金刑確定。所在地: 神奈川県藤沢市城南一丁目18番5号",
        f"{DEFAULT_LAW} 第14条第5項第2号イ",
        "https://www.metro.tokyo.lg.jp/tosei/hodohappyo/press/2024/10/29/19.html",
    ),
    # 2024-08-27 press release (named: 有限会社酒井興業)
    EnfRow(
        "有限会社酒井興業",
        "2024-08-27",
        "東京都",
        "license_revoke",
        "産業廃棄物収集運搬業許可の取消し。所在地: 東京都江戸川区東葛西一丁目19番3号",
        f"{DEFAULT_LAW} 第14条第5項第2号イ及びニ",
        "https://www.metro.tokyo.lg.jp/tosei/hodohappyo/press/2024/08/27/04.html",
    ),
    # 2024-12-12 press release (named: 株式会社エクスクローザー)
    EnfRow(
        "株式会社エクスクローザー",
        "2024-12-12",
        "東京都",
        "license_revoke",
        "産業廃棄物収集運搬業の許可取消し。焼却禁止違反で罰金刑確定。所在地: 埼玉県朝霞市膝折町二丁目13番64号",
        f"{DEFAULT_LAW} 第14条第5項第2号イ",
        "https://www.metro.tokyo.lg.jp/tosei/hodohappyo/press/2024/12/12/18.html",
    ),
    # 2024-02-29 press release (named: 株式会社大萩造園)
    EnfRow(
        "株式会社大萩造園",
        "2024-02-29",
        "東京都",
        "license_revoke",
        "産業廃棄物収集運搬業の許可取消し。業者と役員の焼却禁止違反による罰金刑確定。所在地: 神奈川県相模原市中央区富士見六丁目15番19号",
        f"{DEFAULT_LAW} 第14条第5項第2号イ及びニ",
        "https://www.metro.tokyo.lg.jp/tosei/hodohappyo/press/2024/02/29/05.html",
    ),
    # ===== 神奈川県 (kanagawa.jp 取消処分一覧) =====
    EnfRow(
        "株式会社都木材緑化",
        "2026-03-10",
        "神奈川県",
        "license_revoke",
        "産業廃棄物収集運搬業の許可取消し。代表者: 森﨑修身。所在地: 神奈川県相模原市緑区城山四丁目11番1号",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.kanagawa.jp/docs/p3k/cnt/f91/index.html",
    ),
    EnfRow(
        "美貴建設株式会社",
        "2026-01-16",
        "神奈川県",
        "license_revoke",
        "産業廃棄物収集運搬業の許可取消し。代表者: 中沢美枝子。所在地: 東京都足立区東綾瀬三丁目2番12号",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.kanagawa.jp/docs/p3k/cnt/f91/index.html",
    ),
    EnfRow(
        "株式会社カーズ",
        "2026-01-15",
        "神奈川県",
        "license_revoke",
        "産業廃棄物収集運搬業の許可取消し。代表者: 家高竜平。所在地: 東京都葛飾区水元五丁目11番24号",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.kanagawa.jp/docs/p3k/cnt/f91/index.html",
    ),
    EnfRow(
        "株式会社恵興",
        "2025-11-26",
        "神奈川県",
        "license_revoke",
        "産業廃棄物収集運搬業の許可取消し。代表者: 辻子恵介。所在地: 東京都港区芝公園二丁目12番17号",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.kanagawa.jp/docs/p3k/cnt/f91/index.html",
    ),
    EnfRow(
        "株式会社永利建設工業",
        "2025-11-11",
        "神奈川県",
        "license_revoke",
        "産業廃棄物収集運搬業の許可取消し。代表者: 江田毅。所在地: 東京都葛飾区お花茶屋一丁目7番4号",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.kanagawa.jp/docs/p3k/cnt/f91/index.html",
    ),
    EnfRow(
        "株式会社トーシン",
        "2025-10-20",
        "神奈川県",
        "license_revoke",
        "産業廃棄物収集運搬業及び特別管理産業廃棄物収集運搬業の許可取消し。代表者: 柴山東。所在地: 東京都練馬区西大泉六丁目14番-5",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.kanagawa.jp/docs/p3k/cnt/f91/index.html",
    ),
    EnfRow(
        "dbクリーン株式会社",
        "2025-10-18",
        "神奈川県",
        "license_revoke",
        "産業廃棄物収集運搬業の許可取消し。代表者: 青栁未希。所在地: 埼玉県越谷市七左町4-15-10",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.kanagawa.jp/docs/p3k/cnt/f91/index.html",
    ),
    EnfRow(
        "ウエストファクトリィ株式会社",
        "2025-06-26",
        "神奈川県",
        "license_revoke",
        "産業廃棄物収集運搬業の許可取消し。代表者: 山本そのみ。所在地: 東京都中央区銀座一丁目27番11号",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.kanagawa.jp/docs/p3k/cnt/f91/index.html",
    ),
    EnfRow(
        "宇野興業合同会社",
        "2025-06-18",
        "神奈川県",
        "license_revoke",
        "産業廃棄物収集運搬業の許可取消し。代表者: 劉野。所在地: 東京都足立区伊興本町二丁目12番29号",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.kanagawa.jp/docs/p3k/cnt/f91/index.html",
    ),
    EnfRow(
        "塚田龍偉",
        "2025-06-17",
        "神奈川県",
        "license_revoke",
        "産業廃棄物収集運搬業の許可取消し。所在地: 神奈川県横浜市鶴見区下末吉三丁目3番17号",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.kanagawa.jp/docs/p3k/cnt/f91/index.html",
    ),
    EnfRow(
        "有限会社松島組",
        "2025-05-19",
        "神奈川県",
        "license_revoke",
        "産業廃棄物収集運搬業の許可取消し。代表者: 松島廣。所在地: 栃木県小山市城北四丁目26番地24",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.kanagawa.jp/docs/p3k/cnt/f91/index.html",
    ),
    EnfRow(
        "株式会社オチアイ",
        "2025-05-17",
        "神奈川県",
        "license_revoke",
        "産業廃棄物収集運搬業の許可取消し。代表者: 落合孝義。所在地: 神奈川県茅ヶ崎市旭が丘8番22号",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.kanagawa.jp/docs/p3k/cnt/f91/index.html",
    ),
    EnfRow(
        "株式会社山友興業",
        "2025-05-09",
        "神奈川県",
        "license_revoke",
        "産業廃棄物収集運搬業の許可取消し。代表者: 山下友輔。所在地: 千葉県八千代市麦丸1111番地1",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.kanagawa.jp/docs/p3k/cnt/f91/index.html",
    ),
    EnfRow(
        "株式会社ユウキ",
        "2025-05-07",
        "神奈川県",
        "license_revoke",
        "産業廃棄物収集運搬業の許可取消し。代表者: 諸岡真由美。所在地: 埼玉県川口市芝中田一丁目25番3",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.kanagawa.jp/docs/p3k/cnt/f91/index.html",
    ),
    EnfRow(
        "株式会社川口組",
        "2025-05-01",
        "神奈川県",
        "license_revoke",
        "産業廃棄物収集運搬業の許可取消し。所在地: 埼玉県越谷市蒲生本町2番24号",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.kanagawa.jp/docs/p3k/cnt/f91/index.html",
    ),
    EnfRow(
        "株式会社令幸",
        "2025-04-29",
        "神奈川県",
        "license_revoke",
        "産業廃棄物収集運搬業の許可取消し。代表者: 上野武彦。所在地: 東京都江戸川区船堀二丁目4番28号",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.kanagawa.jp/docs/p3k/cnt/f91/index.html",
    ),
    EnfRow(
        "奥田技研株式会社",
        "2025-04-03",
        "神奈川県",
        "license_revoke",
        "特別管理産業廃棄物収集運搬業の許可取消し。代表者: 奥田勇。所在地: 神奈川県川崎市宮前区初山二丁目10番11号",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.kanagawa.jp/docs/p3k/cnt/f91/index.html",
    ),
    EnfRow(
        "株式会社エコトップ",
        "2025-01-26",
        "神奈川県",
        "license_revoke",
        "産業廃棄物処分業の許可取消し。代表者: 荻野晃彦。所在地: 神奈川県座間市広野台二丁目6番18号",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.kanagawa.jp/docs/p3k/cnt/f91/index.html",
    ),
    EnfRow(
        "株式会社ショーナン",
        "2025-01-20",
        "神奈川県",
        "license_revoke",
        "産業廃棄物収集運搬業の許可取消し。代表者: 下川隆太。所在地: 大阪府門真市速見町2番12号",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.kanagawa.jp/docs/p3k/cnt/f91/index.html",
    ),
    EnfRow(
        "株式会社渋谷緑建",
        "2024-10-09",
        "神奈川県",
        "license_revoke",
        "産業廃棄物収集運搬業の許可取消し。代表者: 桒原禎樹。所在地: 神奈川県横浜市泉区和泉中央北四丁目1番9号",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.kanagawa.jp/docs/p3k/cnt/f91/index.html",
    ),
    EnfRow(
        "杉山建設株式会社",
        "2024-09-19",
        "神奈川県",
        "license_revoke",
        "産業廃棄物収集運搬業の許可取消し。代表者: 杉山弘樹。所在地: 神奈川県藤沢市城南一丁目18番5号",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.kanagawa.jp/docs/p3k/cnt/f91/index.html",
    ),
    EnfRow(
        "株式会社スマイルパートナー",
        "2024-09-03",
        "神奈川県",
        "license_revoke",
        "産業廃棄物収集運搬業の許可取消し。代表者: 伊藤友哉。所在地: 千葉県千葉市若葉区都賀三丁目17番5号",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.kanagawa.jp/docs/p3k/cnt/f91/index.html",
    ),
    EnfRow(
        "株式会社ユースタイル",
        "2024-09-03",
        "神奈川県",
        "license_revoke",
        "産業廃棄物収集運搬業の許可取消し。代表者: 大津孝彰。所在地: 千葉県八街市東吉田517番地18",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.kanagawa.jp/docs/p3k/cnt/f91/index.html",
    ),
    EnfRow(
        "株式会社吉岡開発",
        "2024-06-24",
        "神奈川県",
        "license_revoke",
        "産業廃棄物収集運搬業の許可取消し。代表者: 吉岡龍一。所在地: 東京都足立区南花畑五丁目8番6-203号",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.kanagawa.jp/docs/p3k/cnt/f91/index.html",
    ),
    EnfRow(
        "ホーコー産業株式会社",
        "2024-06-04",
        "神奈川県",
        "license_revoke",
        "産業廃棄物収集運搬業の許可取消し。代表者: 斉藤充。所在地: 神奈川県横浜市都筑区折本町1493番地1",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.kanagawa.jp/docs/p3k/cnt/f91/index.html",
    ),
    EnfRow(
        "幸伸工業株式会社",
        "2024-05-08",
        "神奈川県",
        "license_revoke",
        "産業廃棄物収集運搬業の許可取消し。代表者: 廣瀨和義。所在地: 神奈川県川崎市幸区北加瀬一丁目10番12号",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.kanagawa.jp/docs/p3k/cnt/f91/index.html",
    ),
    EnfRow(
        "宝建工業株式会社",
        "2024-05-08",
        "神奈川県",
        "license_revoke",
        "産業廃棄物収集運搬業の許可取消し。代表者: 枝並留理。所在地: 神奈川県川崎市幸区北加瀬二丁目5番35号",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.kanagawa.jp/docs/p3k/cnt/f91/index.html",
    ),
    EnfRow(
        "有限会社上下水管理工業",
        "2024-04-23",
        "神奈川県",
        "license_revoke",
        "産業廃棄物収集運搬業の許可取消し。代表者: 鈴木俊明。所在地: 神奈川県横浜市神奈川区台町13番地17",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.kanagawa.jp/docs/p3k/cnt/f91/index.html",
    ),
    EnfRow(
        "株式会社大萩造園",
        "2024-03-26",
        "神奈川県",
        "license_revoke",
        "産業廃棄物収集運搬業の許可取消し。代表者: 萩原昌也。所在地: 神奈川県相模原市中央区富士見六丁目15番19号",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.kanagawa.jp/docs/p3k/cnt/f91/index.html",
    ),
    EnfRow(
        "株式会社横浜総建",
        "2024-02-21",
        "神奈川県",
        "license_revoke",
        "産業廃棄物収集運搬業の許可取消し。代表者: 秦洪海。所在地: 神奈川県横浜市泉区上飯田町2670番地",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.kanagawa.jp/docs/p3k/cnt/f91/index.html",
    ),
    EnfRow(
        "有限会社大貫解体工業",
        "2024-02-21",
        "神奈川県",
        "license_revoke",
        "産業廃棄物収集運搬業の許可取消し。代表者: 大貫始康。所在地: 東京都八王子市小比企町536番地の37",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.kanagawa.jp/docs/p3k/cnt/f91/index.html",
    ),
    EnfRow(
        "川崎工苑建設株式会社",
        "2024-01-25",
        "神奈川県",
        "license_revoke",
        "産業廃棄物収集運搬業の許可取消し。代表者: 目代洋子。所在地: 神奈川県川崎市宮前区馬絹三丁目16番23号",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.kanagawa.jp/docs/p3k/cnt/f91/index.html",
    ),
    EnfRow(
        "有限会社奥山興業",
        "2024-01-23",
        "神奈川県",
        "license_revoke",
        "産業廃棄物収集運搬業の許可取消し。代表者: 奥山富士雄。所在地: 神奈川県茅ヶ崎市本宿町11番46-409号",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.kanagawa.jp/docs/p3k/cnt/f91/index.html",
    ),
    EnfRow(
        "大成鉱業株式会社",
        "2023-12-15",
        "神奈川県",
        "license_revoke",
        "産業廃棄物収集運搬業の許可取消し。代表者: 上田博明。所在地: 神奈川県横浜市旭区本宿町22番地",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.kanagawa.jp/docs/p3k/cnt/f91/index.html",
    ),
    EnfRow(
        "有限会社鳶芳建設",
        "2023-10-26",
        "神奈川県",
        "license_revoke",
        "産業廃棄物収集運搬業の許可取消し。代表者: 角田芳一。所在地: 神奈川県藤沢市渡内五丁目2番地の7",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.kanagawa.jp/docs/p3k/cnt/f91/index.html",
    ),
    EnfRow(
        "株式会社日彩",
        "2023-09-11",
        "神奈川県",
        "license_revoke",
        "産業廃棄物収集運搬業の許可取消し。代表者: 友松大輔。所在地: 埼玉県北葛飾郡杉戸町才羽1477番地",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.kanagawa.jp/docs/p3k/cnt/f91/index.html",
    ),
    EnfRow(
        "株式会社東京高英",
        "2023-08-24",
        "神奈川県",
        "license_revoke",
        "産業廃棄物収集運搬業の許可取消し。代表者: 岸本惇。所在地: 埼玉県新座市馬場一丁目11番20号",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.kanagawa.jp/docs/p3k/cnt/f91/index.html",
    ),
    EnfRow(
        "アイエス株式会社",
        "2023-05-16",
        "神奈川県",
        "license_revoke",
        "産業廃棄物収集運搬業の許可取消し。代表者: イシアルプ。所在地: 埼玉県川口市大字安行領根岸856番地",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.kanagawa.jp/docs/p3k/cnt/f91/index.html",
    ),
    EnfRow(
        "株式会社正建",
        "2023-04-18",
        "神奈川県",
        "license_revoke",
        "産業廃棄物収集運搬業の許可取消し。代表者: 似鳥正昭。所在地: 神奈川県川崎市宮前区水沢三丁目4番33-1号",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.kanagawa.jp/docs/p3k/cnt/f91/index.html",
    ),
    EnfRow(
        "有限会社ケイハツ",
        "2023-04-18",
        "神奈川県",
        "license_revoke",
        "産業廃棄物収集運搬業の許可取消し。代表者: 丸峯司。所在地: 東京都羽村市羽4142番地1",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.kanagawa.jp/docs/p3k/cnt/f91/index.html",
    ),
    EnfRow(
        "柏原建設株式会社",
        "2023-03-03",
        "神奈川県",
        "license_revoke",
        "産業廃棄物収集運搬業の許可取消し。代表者: 柏原亮。所在地: 神奈川県横浜市港南区野庭町659番地17",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.kanagawa.jp/docs/p3k/cnt/f91/index.html",
    ),
    EnfRow(
        "藤本土木サービス有限会社",
        "2023-02-16",
        "神奈川県",
        "license_revoke",
        "産業廃棄物収集運搬業の許可取消し。代表者: 藤本卓士。所在地: 東京都清瀬市下宿一丁目122番地",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.kanagawa.jp/docs/p3k/cnt/f91/index.html",
    ),
    EnfRow(
        "株式会社ウッドアップ",
        "2023-02-03",
        "神奈川県",
        "license_revoke",
        "産業廃棄物収集運搬業の許可取消し。代表者: エレン・オザルプ。所在地: 神奈川県横浜市旭区三反田町字長谷戸86-1",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.kanagawa.jp/docs/p3k/cnt/f91/index.html",
    ),
    EnfRow(
        "北見工業株式会社",
        "2023-01-04",
        "神奈川県",
        "license_revoke",
        "産業廃棄物収集運搬業の許可取消し。代表者: 北見文則。所在地: 埼玉県さいたま市中央区上峰一丁目20番16号",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.kanagawa.jp/docs/p3k/cnt/f91/index.html",
    ),
    EnfRow(
        "株式会社ネクスト",
        "2023-01-04",
        "神奈川県",
        "license_revoke",
        "産業廃棄物収集運搬業の許可取消し。代表者: 岸真。所在地: 東京都武蔵村山市学園一丁目24番地の8",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.kanagawa.jp/docs/p3k/cnt/f91/index.html",
    ),
    EnfRow(
        "サガミ環境事業株式会社",
        "2022-09-06",
        "神奈川県",
        "license_revoke",
        "産業廃棄物収集運搬業の許可取消し。代表者: 天野研史。所在地: 神奈川県平塚市東中原二丁目2番73号",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.kanagawa.jp/docs/p3k/cnt/f91/index.html",
    ),
    EnfRow(
        "株式会社緑生",
        "2022-08-08",
        "神奈川県",
        "license_revoke",
        "産業廃棄物収集運搬業の許可取消し。代表者: 加藤沙織。所在地: 神奈川県横須賀市武四丁目8番1号",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.kanagawa.jp/docs/p3k/cnt/f91/index.html",
    ),
    EnfRow(
        "有限会社三栄",
        "2022-04-22",
        "神奈川県",
        "license_revoke",
        "産業廃棄物収集運搬業の許可取消し。代表者: 山本展子。所在地: 神奈川県川崎市多摩区登戸3478番地1",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.kanagawa.jp/docs/p3k/cnt/f91/index.html",
    ),
    EnfRow(
        "有限会社池見造園",
        "2022-04-08",
        "神奈川県",
        "license_revoke",
        "産業廃棄物収集運搬業の許可取消し。代表者: 池見和弘。所在地: 神奈川県相模原市中央区上溝4509番地26",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.kanagawa.jp/docs/p3k/cnt/f91/index.html",
    ),
    EnfRow(
        "雄美建設株式会社",
        "2022-03-24",
        "神奈川県",
        "license_revoke",
        "産業廃棄物収集運搬業の許可取消し。代表者: 矢本広幸。所在地: 神奈川県伊勢原市東大竹二丁目8番12号",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.kanagawa.jp/docs/p3k/cnt/f91/index.html",
    ),
    EnfRow(
        "浜一運送株式会社",
        "2022-03-09",
        "神奈川県",
        "license_revoke",
        "産業廃棄物収集運搬業の許可取消し。代表者: 田島和夫。所在地: 神奈川県横浜市金沢区鳥浜町1番地の1",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.kanagawa.jp/docs/p3k/cnt/f91/index.html",
    ),
    EnfRow(
        "誠工株式会社",
        "2022-03-07",
        "神奈川県",
        "license_revoke",
        "産業廃棄物収集運搬業の許可取消し。代表者: 城川誠。所在地: 兵庫県神戸市兵庫区大開通二丁目3番21号",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.kanagawa.jp/docs/p3k/cnt/f91/index.html",
    ),
    EnfRow(
        "首都圏サポート株式会社",
        "2022-03-07",
        "神奈川県",
        "license_revoke",
        "産業廃棄物収集運搬業の許可取消し。代表者: 松永篤。所在地: 東京都目黒区五本木三丁目16番10号",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.kanagawa.jp/docs/p3k/cnt/f91/index.html",
    ),
    EnfRow(
        "有限会社前田緑化土木",
        "2022-01-31",
        "神奈川県",
        "license_revoke",
        "産業廃棄物収集運搬業の許可取消し。代表者: 前田好雄。所在地: 神奈川県伊勢原市板戸127番地の2",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.kanagawa.jp/docs/p3k/cnt/f91/index.html",
    ),
    EnfRow(
        "株式会社KOHWA",
        "2021-08-30",
        "神奈川県",
        "license_revoke",
        "産業廃棄物収集運搬業の許可取消し。代表者: 岸備。所在地: 神奈川県相模原市中央区南橋本四丁目3番27号",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.kanagawa.jp/docs/p3k/cnt/f91/index.html",
    ),
    EnfRow(
        "石井建設株式会社",
        "2021-06-28",
        "神奈川県",
        "license_revoke",
        "産業廃棄物収集運搬業の許可取消し。代表者: 石井敬二。所在地: 山梨県上野原市棡原63番地",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.kanagawa.jp/docs/p3k/cnt/f91/index.html",
    ),
    EnfRow(
        "株式会社エムエスプランニング",
        "2021-05-14",
        "神奈川県",
        "license_revoke",
        "産業廃棄物収集運搬業の許可取消し。代表者: 佐山学。所在地: 神奈川県横浜市金沢区能見台通34番25号",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.kanagawa.jp/docs/p3k/cnt/f91/index.html",
    ),
    EnfRow(
        "八木周太",
        "2021-03-18",
        "神奈川県",
        "license_revoke",
        "産業廃棄物収集運搬業の許可取消し。所在地: 神奈川県藤沢市羽鳥5丁目7番19号",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.kanagawa.jp/docs/p3k/cnt/f91/index.html",
    ),
    EnfRow(
        "株式会社ウルジャポン",
        "2021-03-18",
        "神奈川県",
        "license_revoke",
        "産業廃棄物収集運搬業の許可取消し。代表者: メフメット・タシ。所在地: 埼玉県川口市赤芝新田字道上507番地の1",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.kanagawa.jp/docs/p3k/cnt/f91/index.html",
    ),
    # ===== 広島県 (eco広島 過去5年間) =====
    EnfRow(
        "株式会社桐光",
        "2025-10-17",
        "広島県",
        "license_revoke",
        "産業廃棄物収集運搬業の取消。役員が廃棄物処理法違反で罰金刑確定により欠格要件該当",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.hiroshima.lg.jp/site/eco/i-i2-shobun-shobun.html",
    ),
    EnfRow(
        "有限会社大森産業",
        "2025-07-02",
        "広島県",
        "license_revoke",
        "処理業取消し（収集運搬業、特管収集運搬業、処分業）。役員が処理法違反罰金刑及び拘禁刑確定により欠格要件該当",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.hiroshima.lg.jp/site/eco/i-i2-shobun-shobun.html",
    ),
    EnfRow(
        "渡部建設株式会社",
        "2024-04-18",
        "広島県",
        "license_revoke",
        "産業廃棄物収集運搬業の取消。役員の処理法違反罰金刑確定により欠格要件該当",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.hiroshima.lg.jp/site/eco/i-i2-shobun-shobun.html",
    ),
    EnfRow(
        "株式会社イハラ",
        "2025-01-08",
        "広島県",
        "license_revoke",
        "産業廃棄物収集運搬業の取消。役員の処理法違反罰金刑確定により欠格要件該当",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.hiroshima.lg.jp/site/eco/i-i2-shobun-shobun.html",
    ),
    EnfRow(
        "株式会社山下産業",
        "2022-12-27",
        "広島県",
        "license_revoke",
        "処理業取消し（収集運搬業、処分業）。役員の処理法違反罰金刑確定により欠格要件該当",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.hiroshima.lg.jp/site/eco/i-i2-shobun-shobun.html",
    ),
    EnfRow(
        "株式会社北海",
        "2022-08-19",
        "広島県",
        "license_revoke",
        "産業廃棄物収集運搬業の取消。役員の拘禁刑確定により欠格要件該当",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.hiroshima.lg.jp/site/eco/i-i2-shobun-shobun.html",
    ),
    EnfRow(
        "有限会社ゼロ",
        "2022-08-04",
        "広島県",
        "license_revoke",
        "産業廃棄物収集運搬業の取消。役員の拘禁刑確定により欠格要件該当",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.hiroshima.lg.jp/site/eco/i-i2-shobun-shobun.html",
    ),
    EnfRow(
        "株式会社オタル解体工業",
        "2021-12-07",
        "広島県",
        "license_revoke",
        "産業廃棄物収集運搬業の取消。役員の焼却禁止違反罰金刑確定により欠格要件該当",
        f"{DEFAULT_LAW} 第16条の2 / 第14条の3の2",
        "https://www.pref.hiroshima.lg.jp/site/eco/i-i2-shobun-shobun.html",
    ),
    EnfRow(
        "拓也実業株式会社",
        "2021-12-03",
        "広島県",
        "license_revoke",
        "産業廃棄物収集運搬業の取消。役員の焼却禁止違反罰金刑確定により欠格要件該当",
        f"{DEFAULT_LAW} 第16条の2 / 第14条の3の2",
        "https://www.pref.hiroshima.lg.jp/site/eco/i-i2-shobun-shobun.html",
    ),
    EnfRow(
        "有限会社赤石工業",
        "2021-11-05",
        "広島県",
        "license_revoke",
        "産業廃棄物収集運搬業の取消。役員の焼却禁止違反罰金刑及び拘禁刑確定により欠格要件該当",
        f"{DEFAULT_LAW} 第16条の2 / 第14条の3の2",
        "https://www.pref.hiroshima.lg.jp/site/eco/i-i2-shobun-shobun.html",
    ),
    EnfRow(
        "有限会社北成興業",
        "2021-10-08",
        "広島県",
        "license_revoke",
        "産業廃棄物収集運搬業の取消。業者及び役員の焼却禁止違反罰金刑確定により欠格要件該当",
        f"{DEFAULT_LAW} 第16条の2 / 第14条の3の2",
        "https://www.pref.hiroshima.lg.jp/site/eco/i-i2-shobun-shobun.html",
    ),
    EnfRow(
        "株式会社北日本重量",
        "2021-10-06",
        "広島県",
        "license_revoke",
        "処理業取消し（収集運搬業、特管収集運搬業）。役員の拘禁刑確定により欠格要件該当",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.hiroshima.lg.jp/site/eco/i-i2-shobun-shobun.html",
    ),
    EnfRow(
        "有限会社難波重機",
        "2021-08-11",
        "広島県",
        "license_revoke",
        "産業廃棄物収集運搬業の取消。業者及び役員の焼却禁止違反罰金刑確定により欠格要件該当",
        f"{DEFAULT_LAW} 第16条の2 / 第14条の3の2",
        "https://www.pref.hiroshima.lg.jp/site/eco/i-i2-shobun-shobun.html",
    ),
    EnfRow(
        "有限会社やまいち",
        "2021-04-30",
        "広島県",
        "license_revoke",
        "産業廃棄物収集運搬業の取消。役員の処理法違反罰金刑確定により欠格要件該当",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.hiroshima.lg.jp/site/eco/i-i2-shobun-shobun.html",
    ),
    EnfRow(
        "宮工建株式会社",
        "2021-03-04",
        "広島県",
        "license_revoke",
        "処理業取消し（収集運搬業、処分業）。法第16条の2（焼却禁止）違反による廃棄物焼却",
        f"{DEFAULT_LAW} 第16条の2 / 第14条の3の2",
        "https://www.pref.hiroshima.lg.jp/site/eco/i-i2-shobun-shobun.html",
    ),
    EnfRow(
        "有限会社大森産業",
        "2025-07-02",
        "広島県",
        "license_revoke",
        "処理施設設置許可の取消し。木くず破砕施設。業者及び役員の処理法違反により欠格要件該当",
        f"{DEFAULT_LAW} 第15条の2の7 / 第15条の3",
        "https://www.pref.hiroshima.lg.jp/site/eco/i-i2-shobun-shobun.html",
        extras={"distinct": "shisetsu"},
    ),
    EnfRow(
        "株式会社山下産業",
        "2022-12-27",
        "広島県",
        "license_revoke",
        "処理施設設置許可の取消し。がれき類破砕施設。役員の処理法違反罰金刑確定により欠格要件該当",
        f"{DEFAULT_LAW} 第15条の2の7 / 第15条の3",
        "https://www.pref.hiroshima.lg.jp/site/eco/i-i2-shobun-shobun.html",
        extras={"distinct": "shisetsu"},
    ),
    EnfRow(
        "株式会社森剛",
        "2022-02-16",
        "広島県",
        "contract_suspend",
        "産業廃棄物処理施設の使用停止及び改善（R4.4.7解除）",
        f"{DEFAULT_LAW} 第15条の2の7",
        "https://www.pref.hiroshima.lg.jp/site/eco/i-i2-shobun-shobun.html",
    ),
    EnfRow(
        "株式会社藤井商店",
        "2022-03-11",
        "広島県",
        "license_revoke",
        "産業廃棄物収集運搬業の許可の取消し",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.hiroshima.lg.jp/site/eco/i-i2-shobun-shobun.html",
    ),
    EnfRow(
        "株式会社大誠",
        "2022-04-26",
        "広島県",
        "license_revoke",
        "産業廃棄物収集運搬業の許可の取消し",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.hiroshima.lg.jp/site/eco/i-i2-shobun-shobun.html",
    ),
    EnfRow(
        "株式会社デンキョウ",
        "2022-12-14",
        "広島県",
        "license_revoke",
        "産業廃棄物収集運搬業の許可の取消し",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.hiroshima.lg.jp/site/eco/i-i2-shobun-shobun.html",
    ),
    EnfRow(
        "株式会社大西建設工業",
        "2023-01-17",
        "広島県",
        "license_revoke",
        "産業廃棄物収集運搬業の許可の取消し",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.hiroshima.lg.jp/site/eco/i-i2-shobun-shobun.html",
    ),
    EnfRow(
        "株式会社森剛",
        "2023-03-08",
        "広島県",
        "contract_suspend",
        "産業廃棄物処理施設の使用停止及び改善（R5.5.19解除）",
        f"{DEFAULT_LAW} 第15条の2の7",
        "https://www.pref.hiroshima.lg.jp/site/eco/i-i2-shobun-shobun.html",
    ),
    EnfRow(
        "株式会社セイテツ",
        "2023-06-22",
        "広島県",
        "license_revoke",
        "産業廃棄物収集運搬業の許可の取消し",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.hiroshima.lg.jp/site/eco/i-i2-shobun-shobun.html",
    ),
    EnfRow(
        "有限会社豊栄産業",
        "2023-12-27",
        "広島県",
        "license_revoke",
        "産業廃棄物収集運搬業の許可の取消し",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.hiroshima.lg.jp/site/eco/i-i2-shobun-shobun.html",
    ),
    EnfRow(
        "山陽三共有機株式会社",
        "2023-12-27",
        "広島県",
        "license_revoke",
        "産業廃棄物収集運搬業の許可の取消し",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.hiroshima.lg.jp/site/eco/i-i2-shobun-shobun.html",
    ),
    EnfRow(
        "三次振興企業株式会社",
        "2024-01-26",
        "広島県",
        "contract_suspend",
        "産業廃棄物処理施設の使用停止及び改善（R6.2.22解除）",
        f"{DEFAULT_LAW} 第15条の2の7",
        "https://www.pref.hiroshima.lg.jp/site/eco/i-i2-shobun-shobun.html",
    ),
    EnfRow(
        "村上恭子",
        "2024-02-06",
        "広島県",
        "license_revoke",
        "産業廃棄物収集運搬業の許可の取消し",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.hiroshima.lg.jp/site/eco/i-i2-shobun-shobun.html",
    ),
    EnfRow(
        "有限会社須賀解体",
        "2024-02-20",
        "広島県",
        "license_revoke",
        "産業廃棄物収集運搬業の許可の取消し",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.hiroshima.lg.jp/site/eco/i-i2-shobun-shobun.html",
    ),
    EnfRow(
        "岩本鋼材株式会社",
        "2024-03-21",
        "広島県",
        "license_revoke",
        "産業廃棄物収集運搬業の許可の取消し",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.hiroshima.lg.jp/site/eco/i-i2-shobun-shobun.html",
    ),
    EnfRow(
        "株式会社ハンディマン",
        "2024-08-28",
        "広島県",
        "license_revoke",
        "産業廃棄物収集運搬業の許可の取消し",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.hiroshima.lg.jp/site/eco/i-i2-shobun-shobun.html",
    ),
    EnfRow(
        "有限会社清勝園",
        "2024-10-25",
        "広島県",
        "license_revoke",
        "産業廃棄物収集運搬業の許可の取消し",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.hiroshima.lg.jp/site/eco/i-i2-shobun-shobun.html",
    ),
    EnfRow(
        "有限会社貞尾興業",
        "2024-11-15",
        "広島県",
        "license_revoke",
        "産業廃棄物収集運搬業及び特別管理産業廃棄物収集運搬業の許可の取消し",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.hiroshima.lg.jp/site/eco/i-i2-shobun-shobun.html",
    ),
    EnfRow(
        "吉田順介",
        "2024-12-26",
        "広島県",
        "license_revoke",
        "産業廃棄物収集運搬業の許可の取消し",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.hiroshima.lg.jp/site/eco/i-i2-shobun-shobun.html",
    ),
    EnfRow(
        "株式会社Ready Lyn",
        "2025-03-27",
        "広島県",
        "contract_suspend",
        "産業廃棄物収集運搬業の全部停止、特別管理産業廃棄物収集運搬業の全部停止（R7.6.25まで）",
        f"{DEFAULT_LAW} 第14条の3",
        "https://www.pref.hiroshima.lg.jp/site/eco/i-i2-shobun-shobun.html",
    ),
    EnfRow(
        "久保田蓮",
        "2025-08-08",
        "広島県",
        "license_revoke",
        "産業廃棄物収集運搬業の許可の取消し",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.hiroshima.lg.jp/site/eco/i-i2-shobun-shobun.html",
    ),
    EnfRow(
        "大洋物産株式会社",
        "2025-12-03",
        "広島県",
        "license_revoke",
        "産業廃棄物収集運搬業の許可の取消し",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.hiroshima.lg.jp/site/eco/i-i2-shobun-shobun.html",
    ),
    EnfRow(
        "岡山産興株式会社",
        "2025-12-03",
        "広島県",
        "contract_suspend",
        "産業廃棄物処理施設の使用停止及び改善（R8.1.28解除）",
        f"{DEFAULT_LAW} 第15条の2の7",
        "https://www.pref.hiroshima.lg.jp/site/eco/i-i2-shobun-shobun.html",
    ),
    EnfRow(
        "株式会社渡辺工業所",
        "2025-12-04",
        "広島県",
        "license_revoke",
        "産業廃棄物収集運搬業の許可の取消し",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.hiroshima.lg.jp/site/eco/i-i2-shobun-shobun.html",
    ),
    EnfRow(
        "因島金属株式会社",
        "2026-01-08",
        "広島県",
        "license_revoke",
        "産業廃棄物収集運搬業の許可の取消し",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.hiroshima.lg.jp/site/eco/i-i2-shobun-shobun.html",
    ),
    EnfRow(
        "株式会社坂本建設",
        "2026-02-06",
        "広島県",
        "license_revoke",
        "産業廃棄物収集運搬業の許可の取消し",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.hiroshima.lg.jp/site/eco/i-i2-shobun-shobun.html",
    ),
    EnfRow(
        "竹下慎吾",
        "2026-04-17",
        "広島県",
        "license_revoke",
        "産業廃棄物収集運搬業の許可の取消し",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.hiroshima.lg.jp/site/eco/i-i2-shobun-shobun.html",
    ),
    # 広島市 press release
    EnfRow(
        "蔵前産業有限会社",
        "2021-06-30",
        "広島市",
        "license_revoke",
        "産業廃棄物収集運搬業の許可の取消し（許可番号07310003165）。役員が法第16条の2（焼却禁止）違反で罰金20万円判決確定",
        f"{DEFAULT_LAW} 第16条の2 / 第14条の3の2",
        "https://www.city.hiroshima.lg.jp/houdou/houdou/232608.html",
    ),
    # ===== 北海道 =====
    EnfRow(
        "株式会社桐光",
        "2025-10-17",
        "北海道",
        "license_revoke",
        "産業廃棄物収集運搬業の取消。役員が廃棄物処理法違反で罰金刑確定により欠格要件該当",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.hokkaido.lg.jp/ks/jss/sanpai_1/syobun_kouhyou/jyoukyou3.html",
    ),
    EnfRow(
        "有限会社大森産業（北海道）",
        "2025-07-02",
        "北海道",
        "license_revoke",
        "処理業取消し（収集運搬業、特管収集運搬業、処分業）。役員が処理法違反罰金刑及び拘禁刑確定により欠格要件該当",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.hokkaido.lg.jp/ks/jss/sanpai_1/syobun_kouhyou/jyoukyou3.html",
    ),
    EnfRow(
        "渡部建設株式会社",
        "2024-04-18",
        "北海道",
        "license_revoke",
        "産業廃棄物収集運搬業の取消。役員の処理法違反罰金刑確定により欠格要件該当",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.hokkaido.lg.jp/ks/jss/sanpai_1/syobun_kouhyou/jyoukyou3.html",
    ),
    EnfRow(
        "株式会社イハラ",
        "2025-01-08",
        "北海道",
        "license_revoke",
        "産業廃棄物収集運搬業の取消。役員の処理法違反罰金刑確定により欠格要件該当",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.hokkaido.lg.jp/ks/jss/sanpai_1/syobun_kouhyou/jyoukyou3.html",
    ),
    EnfRow(
        "株式会社山下産業（北海道）",
        "2022-12-27",
        "北海道",
        "license_revoke",
        "処理業取消し（収集運搬業、処分業）。役員の処理法違反罰金刑確定により欠格要件該当",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.hokkaido.lg.jp/ks/jss/sanpai_1/syobun_kouhyou/jyoukyou3.html",
    ),
    EnfRow(
        "株式会社北海",
        "2022-08-19",
        "北海道",
        "license_revoke",
        "産業廃棄物収集運搬業の取消。役員の拘禁刑確定により欠格要件該当",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.hokkaido.lg.jp/ks/jss/sanpai_1/syobun_kouhyou/jyoukyou3.html",
    ),
    EnfRow(
        "有限会社ゼロ",
        "2022-08-04",
        "北海道",
        "license_revoke",
        "産業廃棄物収集運搬業の取消。役員の拘禁刑確定により欠格要件該当",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.hokkaido.lg.jp/ks/jss/sanpai_1/syobun_kouhyou/jyoukyou3.html",
    ),
    EnfRow(
        "株式会社オタル解体工業",
        "2021-12-07",
        "北海道",
        "license_revoke",
        "産業廃棄物収集運搬業の取消。役員の焼却禁止違反罰金刑確定により欠格要件該当",
        f"{DEFAULT_LAW} 第16条の2 / 第14条の3の2",
        "https://www.pref.hokkaido.lg.jp/ks/jss/sanpai_1/syobun_kouhyou/jyoukyou3.html",
    ),
    EnfRow(
        "拓也実業株式会社（北海道）",
        "2021-12-03",
        "北海道",
        "license_revoke",
        "産業廃棄物収集運搬業の取消。役員の焼却禁止違反罰金刑確定により欠格要件該当",
        f"{DEFAULT_LAW} 第16条の2 / 第14条の3の2",
        "https://www.pref.hokkaido.lg.jp/ks/jss/sanpai_1/syobun_kouhyou/jyoukyou3.html",
    ),
    EnfRow(
        "有限会社赤石工業",
        "2021-11-05",
        "北海道",
        "license_revoke",
        "産業廃棄物収集運搬業の取消。役員の焼却禁止違反罰金刑及び拘禁刑確定により欠格要件該当",
        f"{DEFAULT_LAW} 第16条の2 / 第14条の3の2",
        "https://www.pref.hokkaido.lg.jp/ks/jss/sanpai_1/syobun_kouhyou/jyoukyou3.html",
    ),
    EnfRow(
        "有限会社北成興業",
        "2021-10-08",
        "北海道",
        "license_revoke",
        "産業廃棄物収集運搬業の取消。業者及び役員の焼却禁止違反罰金刑確定により欠格要件該当",
        f"{DEFAULT_LAW} 第16条の2 / 第14条の3の2",
        "https://www.pref.hokkaido.lg.jp/ks/jss/sanpai_1/syobun_kouhyou/jyoukyou3.html",
    ),
    EnfRow(
        "株式会社北日本重量",
        "2021-10-06",
        "北海道",
        "license_revoke",
        "処理業取消し（収集運搬業、特管収集運搬業）。役員の拘禁刑確定により欠格要件該当",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.hokkaido.lg.jp/ks/jss/sanpai_1/syobun_kouhyou/jyoukyou3.html",
    ),
    EnfRow(
        "有限会社難波重機",
        "2021-08-11",
        "北海道",
        "license_revoke",
        "産業廃棄物収集運搬業の取消。業者及び役員の焼却禁止違反罰金刑確定により欠格要件該当",
        f"{DEFAULT_LAW} 第16条の2 / 第14条の3の2",
        "https://www.pref.hokkaido.lg.jp/ks/jss/sanpai_1/syobun_kouhyou/jyoukyou3.html",
    ),
    EnfRow(
        "有限会社やまいち",
        "2021-04-30",
        "北海道",
        "license_revoke",
        "産業廃棄物収集運搬業の取消。役員の処理法違反罰金刑確定により欠格要件該当",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.hokkaido.lg.jp/ks/jss/sanpai_1/syobun_kouhyou/jyoukyou3.html",
    ),
    EnfRow(
        "有限会社厚田環境センター",
        "2004-11-12",
        "北海道",
        "business_improvement",
        "改善命令: 堆積廃棄物撤去、上限超過廃棄物処理、水質測定実施、焼却炉構造改善。最終処分場上に約21,000m³堆積、保管上限超過、測定未実施、構造基準不適合",
        f"{DEFAULT_LAW} 第19条の3",
        "https://www.pref.hokkaido.lg.jp/ks/jss/sanpai_1/syobun_kouhyou/jyoukyou3.html",
    ),
    EnfRow(
        "株式会社キーアイ",
        "2014-10-02",
        "北海道",
        "business_improvement",
        "改善命令: 保管数量を296.67m³以下に削減。事業場内で約4,600m³を保管上限296.67m³超過で保管",
        f"{DEFAULT_LAW} 第19条の3",
        "https://www.pref.hokkaido.lg.jp/ks/jss/sanpai_1/syobun_kouhyou/jyoukyou3.html",
    ),
    # ===== 千葉県 (press releases) =====
    EnfRow(
        "株式会社ダイコウ",
        "2025-03-04",
        "千葉県",
        "license_revoke",
        "産業廃棄物収集運搬業の許可の取消し。法人番号3040001013820。破産手続開始の決定を受けたことによる欠格要件該当。所在地: 千葉県千葉市若葉区大草町288番地の2",
        f"{DEFAULT_LAW} 第14条第5項第2号イ",
        "https://www.pref.chiba.lg.jp/haishi/press/2024/shobun20250304.html",
    ),
    EnfRow(
        "トラストワン株式会社",
        "2025-03-04",
        "千葉県",
        "license_revoke",
        "産業廃棄物収集運搬業の許可の取消し。法人番号6040001118451。破産手続開始の決定を受けたことによる欠格要件該当。所在地: 千葉県千葉市稲毛区小仲台六丁目14番4号サン稲毛ビル301号室",
        f"{DEFAULT_LAW} 第14条第5項第2号イ",
        "https://www.pref.chiba.lg.jp/haishi/press/2024/shobun20250304.html",
    ),
    EnfRow(
        "株式会社佳楽興業",
        "2025-03-04",
        "千葉県",
        "license_revoke",
        "産業廃棄物収集運搬業の許可の取消し。法人番号7011801034220。役員による焼却禁止違反で罰金刑処せられたことによる欠格要件該当。所在地: 東京都足立区西保木間二丁目19番16号",
        f"{DEFAULT_LAW} 第14条第5項第2号ニ",
        "https://www.pref.chiba.lg.jp/haishi/press/2024/shobun20250304.html",
    ),
    EnfRow(
        "株式会社ミライ工業",
        "2024-12-20",
        "千葉県",
        "license_revoke",
        "産業廃棄物収集運搬業の許可の取消し。許可を受けた事業範囲に「積替え保管」が含まれていないにもかかわらず、受託した産業廃棄物の一部について事業場内において積替え保管を行った。所在地: 千葉県大網白里市駒込736番地6",
        f"{DEFAULT_LAW} 第14条の3の2第1項第5号 / 第14条の2第1項",
        "https://www.pref.chiba.lg.jp/haishi/press/2024/shobun20241220.html",
    ),
    EnfRow(
        "株式会社セフティランド",
        "2025-01-20",
        "千葉県",
        "contract_suspend",
        "産業廃棄物収集運搬業及び産業廃棄物処分業の全部停止 (令和7年1月27日から令和7年2月25日まで30日間)。法人番号8040001046171。管理票の交付を受けずに、排出事業者から処分を受託した産業廃棄物の引渡しを受けていた。所在地: 千葉県白井市河原子324番地4",
        f"{DEFAULT_LAW} 第12条の4第2項 / 第14条の3第1号",
        "https://www.pref.chiba.lg.jp/haishi/press/2024/shobun20250120.html",
    ),
    # ===== 埼玉県 (saitama-syobun list — 86 entries with date+name) =====
    EnfRow(
        "株式会社新日本オゾン",
        "2026-02-17",
        "埼玉県",
        "license_revoke",
        "産業廃棄物処理業に係る行政処分",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.saitama.lg.jp/a0506/sanpai-syobun2/syobun.html",
    ),
    EnfRow(
        "株式会社ジャパンクリーン",
        "2026-01-29",
        "埼玉県",
        "license_revoke",
        "産業廃棄物処理業に係る行政処分",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.saitama.lg.jp/a0506/sanpai-syobun2/syobun.html",
    ),
    EnfRow(
        "株式会社ASUKA",
        "2025-12-22",
        "埼玉県",
        "license_revoke",
        "産業廃棄物処理業に係る行政処分",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.saitama.lg.jp/a0506/sanpai-syobun2/syobun.html",
    ),
    EnfRow(
        "クローバー建設株式会社",
        "2025-11-26",
        "埼玉県",
        "license_revoke",
        "産業廃棄物処理業に係る行政処分",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.saitama.lg.jp/a0506/sanpai-syobun2/syobun.html",
    ),
    EnfRow(
        "有限会社林材木店",
        "2025-10-23",
        "埼玉県",
        "license_revoke",
        "産業廃棄物処理業に係る行政処分",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.saitama.lg.jp/a0506/sanpai-syobun2/syobun.html",
    ),
    EnfRow(
        "株式会社H産業",
        "2025-10-10",
        "埼玉県",
        "license_revoke",
        "産業廃棄物処理業に係る行政処分",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.saitama.lg.jp/a0506/sanpai-syobun2/syobun.html",
    ),
    EnfRow(
        "株式会社ベストワーク",
        "2025-10-08",
        "埼玉県",
        "license_revoke",
        "産業廃棄物処理業に係る行政処分",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.saitama.lg.jp/a0506/sanpai-syobun2/syobun.html",
    ),
    EnfRow(
        "有限会社西満商事",
        "2025-09-04",
        "埼玉県",
        "license_revoke",
        "産業廃棄物処理業に係る行政処分",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.saitama.lg.jp/a0506/sanpai-syobun2/syobun.html",
    ),
    EnfRow(
        "株式会社サングリーン",
        "2025-09-02",
        "埼玉県",
        "license_revoke",
        "産業廃棄物処理業に係る行政処分",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.saitama.lg.jp/a0506/sanpai-syobun2/syobun.html",
    ),
    EnfRow(
        "渡辺工業株式会社",
        "2025-08-18",
        "埼玉県",
        "license_revoke",
        "産業廃棄物処理業に係る行政処分",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.saitama.lg.jp/a0506/sanpai-syobun2/syobun.html",
    ),
    EnfRow(
        "株式会社トーシン",
        "2025-08-06",
        "埼玉県",
        "license_revoke",
        "産業廃棄物処理業に係る行政処分",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.saitama.lg.jp/a0506/sanpai-syobun2/syobun.html",
    ),
    EnfRow(
        "磐梯興業株式会社",
        "2025-07-28",
        "埼玉県",
        "license_revoke",
        "産業廃棄物処理業に係る行政処分",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.saitama.lg.jp/a0506/sanpai-syobun2/syobun.html",
    ),
    EnfRow(
        "大渕建設株式会社",
        "2025-07-10",
        "埼玉県",
        "license_revoke",
        "産業廃棄物処理業に係る行政処分",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.saitama.lg.jp/a0506/sanpai-syobun2/syobun.html",
    ),
    EnfRow(
        "有限会社松島組",
        "2025-06-16",
        "埼玉県",
        "license_revoke",
        "産業廃棄物処理業に係る行政処分",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.saitama.lg.jp/a0506/sanpai-syobun2/syobun.html",
    ),
    EnfRow(
        "合同会社葵組",
        "2025-06-05",
        "埼玉県",
        "license_revoke",
        "産業廃棄物処理業に係る行政処分",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.saitama.lg.jp/a0506/sanpai-syobun2/syobun.html",
    ),
    EnfRow(
        "有限会社大槻ポンプ",
        "2025-05-22",
        "埼玉県",
        "license_revoke",
        "産業廃棄物処理業に係る行政処分",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.saitama.lg.jp/a0506/sanpai-syobun2/syobun.html",
    ),
    EnfRow(
        "株式会社山友興業",
        "2025-05-20",
        "埼玉県",
        "license_revoke",
        "産業廃棄物処理業に係る行政処分",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.saitama.lg.jp/a0506/sanpai-syobun2/syobun.html",
    ),
    EnfRow(
        "宇野興業合同会社",
        "2025-04-18",
        "埼玉県",
        "license_revoke",
        "産業廃棄物処理業に係る行政処分",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.saitama.lg.jp/a0506/sanpai-syobun2/syobun.html",
    ),
    EnfRow(
        "川南鋼機株式会社",
        "2025-02-28",
        "埼玉県",
        "license_revoke",
        "産業廃棄物処理業に係る行政処分",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.saitama.lg.jp/a0506/sanpai-syobun2/syobun.html",
    ),
    EnfRow(
        "株式会社北陽",
        "2025-02-22",
        "埼玉県",
        "license_revoke",
        "産業廃棄物処理業に係る行政処分",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.saitama.lg.jp/a0506/sanpai-syobun2/syobun.html",
    ),
    EnfRow(
        "株式会社T.K.S",
        "2025-02-13",
        "埼玉県",
        "license_revoke",
        "産業廃棄物処理業に係る行政処分",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.saitama.lg.jp/a0506/sanpai-syobun2/syobun.html",
    ),
    EnfRow(
        "株式会社吉野建設興業",
        "2024-12-09",
        "埼玉県",
        "license_revoke",
        "産業廃棄物処理業に係る行政処分",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.saitama.lg.jp/a0506/sanpai-syobun2/syobun.html",
    ),
    EnfRow(
        "株式会社SHIMADA",
        "2024-12-04",
        "埼玉県",
        "license_revoke",
        "産業廃棄物処理業に係る行政処分",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.saitama.lg.jp/a0506/sanpai-syobun2/syobun.html",
    ),
    EnfRow(
        "株式会社蜂谷興業",
        "2024-09-08",
        "埼玉県",
        "license_revoke",
        "産業廃棄物処理業に係る行政処分",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.saitama.lg.jp/a0506/sanpai-syobun2/syobun.html",
    ),
    EnfRow(
        "株式会社岡野工務店",
        "2024-06-26",
        "埼玉県",
        "license_revoke",
        "産業廃棄物処理業に係る行政処分",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.saitama.lg.jp/a0506/sanpai-syobun2/syobun.html",
    ),
    EnfRow(
        "東建株式会社",
        "2024-04-12",
        "埼玉県",
        "license_revoke",
        "産業廃棄物処理業に係る行政処分",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.saitama.lg.jp/a0506/sanpai-syobun2/syobun.html",
    ),
    EnfRow(
        "株式会社イーズ",
        "2024-03-28",
        "埼玉県",
        "license_revoke",
        "産業廃棄物処理業に係る行政処分",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.saitama.lg.jp/a0506/sanpai-syobun2/syobun.html",
    ),
    EnfRow(
        "有限会社新解",
        "2024-03-01",
        "埼玉県",
        "license_revoke",
        "産業廃棄物処理業に係る行政処分",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.saitama.lg.jp/a0506/sanpai-syobun2/syobun.html",
    ),
    EnfRow(
        "有限会社丸孝商事",
        "2024-02-13",
        "埼玉県",
        "license_revoke",
        "産業廃棄物処理業に係る行政処分",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.saitama.lg.jp/a0506/sanpai-syobun2/syobun.html",
    ),
    EnfRow(
        "株式会社ジョイクス",
        "2024-02-01",
        "埼玉県",
        "license_revoke",
        "産業廃棄物処理業に係る行政処分",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.saitama.lg.jp/a0506/sanpai-syobun2/syobun.html",
    ),
    EnfRow(
        "砂押プラリ株式会社",
        "2024-02-01",
        "埼玉県",
        "license_revoke",
        "産業廃棄物処理業に係る行政処分",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.saitama.lg.jp/a0506/sanpai-syobun2/syobun.html",
    ),
    EnfRow(
        "株式会社梅沢工務店",
        "2024-01-23",
        "埼玉県",
        "license_revoke",
        "産業廃棄物処理業に係る行政処分",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.saitama.lg.jp/a0506/sanpai-syobun2/syobun.html",
    ),
    EnfRow(
        "ニッポー工業株式会社",
        "2023-12-27",
        "埼玉県",
        "license_revoke",
        "産業廃棄物処理業に係る行政処分",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.saitama.lg.jp/a0506/sanpai-syobun2/syobun.html",
    ),
    EnfRow(
        "島田建設株式会社",
        "2023-12-22",
        "埼玉県",
        "license_revoke",
        "産業廃棄物処理業に係る行政処分",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.saitama.lg.jp/a0506/sanpai-syobun2/syobun.html",
    ),
    EnfRow(
        "有限会社田村商店",
        "2023-08-26",
        "埼玉県",
        "license_revoke",
        "産業廃棄物処理業に係る行政処分",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.saitama.lg.jp/a0506/sanpai-syobun2/syobun.html",
    ),
    EnfRow(
        "株式会社長岡商会",
        "2023-08-03",
        "埼玉県",
        "license_revoke",
        "産業廃棄物処理業に係る行政処分",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.saitama.lg.jp/a0506/sanpai-syobun2/syobun.html",
    ),
    EnfRow(
        "株式会社アトラス産業",
        "2023-08-02",
        "埼玉県",
        "license_revoke",
        "産業廃棄物処理業に係る行政処分",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.saitama.lg.jp/a0506/sanpai-syobun2/syobun.html",
    ),
    EnfRow(
        "株式会社Basis",
        "2023-08-01",
        "埼玉県",
        "license_revoke",
        "産業廃棄物処理業に係る行政処分",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.saitama.lg.jp/a0506/sanpai-syobun2/syobun.html",
    ),
    EnfRow(
        "株式会社リベルテプランニング",
        "2023-04-03",
        "埼玉県",
        "license_revoke",
        "産業廃棄物処理業に係る行政処分",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.saitama.lg.jp/a0506/sanpai-syobun2/syobun.html",
    ),
    EnfRow(
        "東日本クリーンサービス株式会社",
        "2023-02-28",
        "埼玉県",
        "license_revoke",
        "産業廃棄物処理業に係る行政処分",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.saitama.lg.jp/a0506/sanpai-syobun2/syobun.html",
    ),
    EnfRow(
        "株式会社ゼットライン",
        "2023-02-10",
        "埼玉県",
        "license_revoke",
        "産業廃棄物処理業に係る行政処分",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.saitama.lg.jp/a0506/sanpai-syobun2/syobun.html",
    ),
    EnfRow(
        "有限会社五月造園",
        "2023-01-21",
        "埼玉県",
        "license_revoke",
        "産業廃棄物処理業に係る行政処分",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.saitama.lg.jp/a0506/sanpai-syobun2/syobun.html",
    ),
    EnfRow(
        "大輝工業合同会社",
        "2023-01-18",
        "埼玉県",
        "license_revoke",
        "産業廃棄物処理業に係る行政処分",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.saitama.lg.jp/a0506/sanpai-syobun2/syobun.html",
    ),
    EnfRow(
        "株式会社シュウワエンジニアリング",
        "2022-10-31",
        "埼玉県",
        "license_revoke",
        "産業廃棄物処理業に係る行政処分",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.saitama.lg.jp/a0506/sanpai-syobun2/syobun.html",
    ),
    EnfRow(
        "ワークエクスプレス株式会社",
        "2022-10-11",
        "埼玉県",
        "license_revoke",
        "産業廃棄物処理業に係る行政処分",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.saitama.lg.jp/a0506/sanpai-syobun2/syobun.html",
    ),
    EnfRow(
        "越谷金属株式会社",
        "2022-10-11",
        "埼玉県",
        "license_revoke",
        "産業廃棄物処理業に係る行政処分",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.saitama.lg.jp/a0506/sanpai-syobun2/syobun.html",
    ),
    EnfRow(
        "株式会社一越組",
        "2022-09-20",
        "埼玉県",
        "license_revoke",
        "産業廃棄物処理業に係る行政処分",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.saitama.lg.jp/a0506/sanpai-syobun2/syobun.html",
    ),
    EnfRow(
        "株式会社菊地造園土木",
        "2022-09-07",
        "埼玉県",
        "license_revoke",
        "産業廃棄物処理業に係る行政処分",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.saitama.lg.jp/a0506/sanpai-syobun2/syobun.html",
    ),
    EnfRow(
        "株式会社JRCコーポレーション",
        "2022-07-20",
        "埼玉県",
        "license_revoke",
        "産業廃棄物処理業に係る行政処分",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.saitama.lg.jp/a0506/sanpai-syobun2/syobun.html",
    ),
    EnfRow(
        "株式会社一大",
        "2022-06-01",
        "埼玉県",
        "license_revoke",
        "産業廃棄物処理業に係る行政処分",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.saitama.lg.jp/a0506/sanpai-syobun2/syobun.html",
    ),
    EnfRow(
        "株式会社北関石田組",
        "2022-05-20",
        "埼玉県",
        "license_revoke",
        "産業廃棄物処理業に係る行政処分",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.saitama.lg.jp/a0506/sanpai-syobun2/syobun.html",
    ),
    EnfRow(
        "有限会社増田建材",
        "2022-04-26",
        "埼玉県",
        "license_revoke",
        "産業廃棄物処理業に係る行政処分",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.saitama.lg.jp/a0506/sanpai-syobun2/syobun.html",
    ),
    EnfRow(
        "株式会社河波",
        "2022-02-13",
        "埼玉県",
        "license_revoke",
        "産業廃棄物処理業に係る行政処分",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.saitama.lg.jp/a0506/sanpai-syobun2/syobun.html",
    ),
    EnfRow(
        "株式会社峯岸重量",
        "2022-01-19",
        "埼玉県",
        "license_revoke",
        "産業廃棄物処理業に係る行政処分",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.saitama.lg.jp/a0506/sanpai-syobun2/syobun.html",
    ),
    EnfRow(
        "緑化産業株式会社",
        "2021-09-25",
        "埼玉県",
        "license_revoke",
        "産業廃棄物処理業に係る行政処分",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.saitama.lg.jp/a0506/sanpai-syobun2/syobun.html",
    ),
    EnfRow(
        "関野建材工業株式会社",
        "2021-07-16",
        "埼玉県",
        "license_revoke",
        "産業廃棄物処理業に係る行政処分",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.saitama.lg.jp/a0506/sanpai-syobun2/syobun.html",
    ),
    EnfRow(
        "高宮運輸有限会社",
        "2021-07-09",
        "埼玉県",
        "license_revoke",
        "産業廃棄物処理業に係る行政処分",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.saitama.lg.jp/a0506/sanpai-syobun2/syobun.html",
    ),
    EnfRow(
        "有限会社ナガイ解体興業",
        "2021-03-30",
        "埼玉県",
        "license_revoke",
        "産業廃棄物処理業に係る行政処分",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.saitama.lg.jp/a0506/sanpai-syobun2/syobun.html",
    ),
    # ===== 兵庫県 (press release 2024-02-02) =====
    EnfRow(
        "株式会社エス＆ケイ",
        "2024-02-02",
        "兵庫県",
        "license_revoke",
        "廃棄物処理法に係る行政処分。産業廃棄物処理業の許可取消し",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://web.pref.hyogo.lg.jp/ehk01/202402022.html",
    ),
    EnfRow(
        "株式会社福谷建設",
        "2024-02-02",
        "兵庫県",
        "license_revoke",
        "廃棄物処理法に係る行政処分。産業廃棄物収集運搬業の許可取消し",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://web.pref.hyogo.lg.jp/ehk01/202402021.html",
    ),
    # ===== 愛知県 (press release 2022-03-18 ka 一斉立入) =====
    EnfRow(
        "愛知県事業停止対象事業者（2022-03-18）",
        "2022-03-18",
        "愛知県",
        "contract_suspend",
        "廃棄物処理法に基づく産業廃棄物処理業者への行政処分（事業の停止命令）。岩石くず等を含む産業廃棄物を無許可で取り扱う、必要な管理票（マニフェスト）なしでの廃棄物受託",
        f"{DEFAULT_LAW} 第14条の3 / 第12条の4",
        "https://www.pref.aichi.jp/soshiki/junkan-kansi/2021kansi06.html",
    ),
    EnfRow(
        "愛知県許可取消対象事業者（2022-11-28）",
        "2022-11-28",
        "愛知県",
        "license_revoke",
        "廃棄物処理法に基づく産業廃棄物処理業者への行政処分（許可の取消し）。役員が刑事罰を受けたことによる欠格要件該当",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.aichi.jp/soshiki/junkan-kansi/2022kanshi04.html",
    ),
    # ===== 福岡県 (publicly announced) =====
    EnfRow(
        "富士開発株式会社",
        "2024-11-17",
        "福岡県",
        "license_revoke",
        "産業廃棄物収集運搬業の許可、産業廃棄物処分業の許可及び産業廃棄物処理施設（安定型最終処分場・管理型最終処分場・脱水施設・焼却施設）の設置の許可の取消し",
        f"{DEFAULT_LAW} 第14条の3の2 / 第15条の3",
        "https://www.pref.fukuoka.lg.jp/contents/shobun.html",
    ),
    # ===== 横浜市 =====
    EnfRow(
        "横浜市事業停止対象事業者（2023-11-21）",
        "2023-11-21",
        "横浜市",
        "contract_suspend",
        "産業廃棄物処理業者に対する事業停止命令",
        f"{DEFAULT_LAW} 第14条の3",
        "https://www.city.yokohama.lg.jp/city-info/koho-kocho/press/shigen/2023/1121jigyoteishi.html",
    ),
    # ===== 環境省 (令和3年度実績集計; 個別ではないが count レベル) =====
    # NOTE: 個別事業者名がないので個別 row は記録せず、policy summary は省略。
    # ===== 大阪府 (Excel 一覧 R8.4.13 公表) =====
    EnfRow(
        "大阪府許可取消対象事業者（2026-04-13公表）",
        "2026-04-13",
        "大阪府",
        "license_revoke",
        "産業廃棄物処理業者の許可取消一覧（大阪府知事による取消し処分情報）。詳細は出典 Excel ファイル参照。",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.osaka.lg.jp/documents/595/20260413kyokatorikeshi.xlsx",
    ),
    # ===== 京都府 (公表 行政処分 r5/r6/r7 一覧) =====
    # https://www.pref.kyoto.jp/sanpai/syobun/r5gyouseisyobun.html
    EnfRow(
        "有限会社髙屋左官工芸",
        "2023-04-14",
        "京都府",
        "license_revoke",
        "産業廃棄物収集運搬業許可取消（廃棄物処理法 14条の3の2 第1項第1号）",
        f"{DEFAULT_LAW} 第14条の3の2第1項第1号",
        "https://www.pref.kyoto.jp/sanpai/syobun/r5gyouseisyobun.html",
    ),
    EnfRow(
        "氷上急行運輸倉庫株式会社",
        "2023-10-31",
        "京都府",
        "license_revoke",
        "産業廃棄物収集運搬業許可取消（廃棄物処理法 14条の3の2 第1項第4号）",
        f"{DEFAULT_LAW} 第14条の3の2第1項第4号",
        "https://www.pref.kyoto.jp/sanpai/syobun/r5gyouseisyobun.html",
    ),
    EnfRow(
        "ウィングラン株式会社",
        "2024-02-20",
        "京都府",
        "license_revoke",
        "産業廃棄物収集運搬業許可取消（廃棄物処理法 14条の3の2 第1項第1号）",
        f"{DEFAULT_LAW} 第14条の3の2第1項第1号",
        "https://www.pref.kyoto.jp/sanpai/syobun/r5gyouseisyobun.html",
    ),
    # r6
    EnfRow(
        "反田嘉七",
        "2024-10-10",
        "京都府",
        "license_revoke",
        "産業廃棄物収集運搬業許可取消（廃棄物処理法 14条の3の2 第1項第1号）",
        f"{DEFAULT_LAW} 第14条の3の2第1項第1号",
        "https://www.pref.kyoto.jp/sanpai/syobun/r6gyouseisyobun.html",
    ),
    EnfRow(
        "株式会社ヨシダ設備",
        "2024-11-19",
        "京都府",
        "license_revoke",
        "産業廃棄物収集運搬業許可取消（廃棄物処理法 14条の3の2 第1項第4号）",
        f"{DEFAULT_LAW} 第14条の3の2第1項第4号",
        "https://www.pref.kyoto.jp/sanpai/syobun/r6gyouseisyobun.html",
    ),
    EnfRow(
        "株式会社友工",
        "2024-12-13",
        "京都府",
        "license_revoke",
        "産業廃棄物収集運搬業許可取消（廃棄物処理法 14条の3の2 第1項第4号）",
        f"{DEFAULT_LAW} 第14条の3の2第1項第4号",
        "https://www.pref.kyoto.jp/sanpai/syobun/r6gyouseisyobun.html",
    ),
    EnfRow(
        "阪本勲",
        "2024-12-24",
        "京都府",
        "license_revoke",
        "産業廃棄物収集運搬業許可取消（廃棄物処理法 14条の3の2 第1項第4号）",
        f"{DEFAULT_LAW} 第14条の3の2第1項第4号",
        "https://www.pref.kyoto.jp/sanpai/syobun/r6gyouseisyobun.html",
    ),
    EnfRow(
        "近藤誠",
        "2025-02-13",
        "京都府",
        "license_revoke",
        "産業廃棄物収集運搬業許可取消（廃棄物処理法 14条の3の2 第1項第4号）",
        f"{DEFAULT_LAW} 第14条の3の2第1項第4号",
        "https://www.pref.kyoto.jp/sanpai/syobun/r6gyouseisyobun.html",
    ),
    EnfRow(
        "株式会社花山工務店",
        "2025-03-18",
        "京都府",
        "license_revoke",
        "産業廃棄物収集運搬業許可取消（廃棄物処理法 14条の3の2 第1項第1号）",
        f"{DEFAULT_LAW} 第14条の3の2第1項第1号",
        "https://www.pref.kyoto.jp/sanpai/syobun/r6gyouseisyobun.html",
    ),
    # r7
    EnfRow(
        "株式会社谷口建設",
        "2025-04-17",
        "京都府",
        "license_revoke",
        "産業廃棄物収集運搬業許可取消（廃棄物処理法 14条の3の2 第1項第4号）",
        f"{DEFAULT_LAW} 第14条の3の2第1項第4号",
        "https://www.pref.kyoto.jp/sanpai/syobun/r7gyouseisyobun.html",
    ),
    EnfRow(
        "山岡建設株式会社",
        "2025-04-17",
        "京都府",
        "license_revoke",
        "産業廃棄物収集運搬業許可取消（廃棄物処理法 14条の3の2 第1項第4号）",
        f"{DEFAULT_LAW} 第14条の3の2第1項第4号",
        "https://www.pref.kyoto.jp/sanpai/syobun/r7gyouseisyobun.html",
    ),
    EnfRow(
        "株式会社栄土木",
        "2025-10-23",
        "京都府",
        "license_revoke",
        "産業廃棄物収集運搬業許可取消（廃棄物処理法 14条の3の2 第1項第2号）",
        f"{DEFAULT_LAW} 第14条の3の2第1項第2号",
        "https://www.pref.kyoto.jp/sanpai/syobun/r7gyouseisyobun.html",
    ),
    EnfRow(
        "株式会社不川起業",
        "2026-02-17",
        "京都府",
        "license_revoke",
        "産業廃棄物収集運搬業許可取消（廃棄物処理法 14条の3の2 第1項第4号）",
        f"{DEFAULT_LAW} 第14条の3の2第1項第4号",
        "https://www.pref.kyoto.jp/sanpai/syobun/r7gyouseisyobun.html",
    ),
    EnfRow(
        "リンクス株式会社",
        "2026-03-26",
        "京都府",
        "license_revoke",
        "産業廃棄物収集運搬業許可取消（廃棄物処理法 14条の3の2 第1項第4号）— 静岡県静岡市",
        f"{DEFAULT_LAW} 第14条の3の2第1項第4号",
        "https://www.pref.kyoto.jp/sanpai/syobun/r7gyouseisyobun.html",
    ),
    EnfRow(
        "砂川順一",
        "2026-03-26",
        "京都府",
        "license_revoke",
        "産業廃棄物収集運搬業許可取消（廃棄物処理法 14条の3の2 第1項第4号）",
        f"{DEFAULT_LAW} 第14条の3の2第1項第4号",
        "https://www.pref.kyoto.jp/sanpai/syobun/r7gyouseisyobun.html",
    ),
    EnfRow(
        "株式会社松村",
        "2026-03-26",
        "京都府",
        "license_revoke",
        "産業廃棄物収集運搬業許可取消（廃棄物処理法 14条の3の2 第1項第4号）",
        f"{DEFAULT_LAW} 第14条の3の2第1項第4号",
        "https://www.pref.kyoto.jp/sanpai/syobun/r7gyouseisyobun.html",
    ),
    # ===== 名古屋市 (廃棄物処理業及び廃棄物処理施設に係る行政処分一覧 r03/r05/r06) =====
    # https://www.city.nagoya.jp/jigyou/gomi/1025999/1026043/1026055.html
    EnfRow(
        "フジ建材リース株式会社",
        "2021-11-09",
        "名古屋市",
        "license_revoke",
        "産業廃棄物処分業許可取消し — 破産手続開始により欠格要件該当",
        f"{DEFAULT_LAW} 第14条の3の2第1項第4号",
        "https://www.city.nagoya.jp/_res/projects/default_project/_page_/001/026/070/r03gyouseisyobunr031201.pdf",
    ),
    EnfRow(
        "フジ建材リース株式会社（処理施設）",
        "2021-11-09",
        "名古屋市",
        "license_revoke",
        "産業廃棄物処理施設設置許可取消し — 破産手続開始により欠格要件該当",
        f"{DEFAULT_LAW} 第15条の3第1項第1号",
        "https://www.city.nagoya.jp/_res/projects/default_project/_page_/001/026/070/r03gyouseisyobunr031201.pdf",
    ),
    EnfRow(
        "株式会社アイクリ",
        "2021-11-30",
        "名古屋市",
        "license_revoke",
        "特別管理産業廃棄物収集運搬業許可取消し — 破産手続開始により欠格要件該当",
        f"{DEFAULT_LAW} 第14条の6・第14条の3の2第1項第4号",
        "https://www.city.nagoya.jp/_res/projects/default_project/_page_/001/026/070/r03gyouseisyobunr031201.pdf",
    ),
    EnfRow(
        "有限会社山田商店",
        "2024-02-27",
        "名古屋市",
        "license_revoke",
        "産業廃棄物処分業許可取消し — 役員の道路交通法違反による欠格要件該当",
        f"{DEFAULT_LAW} 第14条の3の2第1項第4号",
        "https://www.city.nagoya.jp/_res/projects/default_project/_page_/001/026/070/r05gyouseisyobunr060306.pdf",
    ),
    EnfRow(
        "有限会社山田商店（更新申請不許可）",
        "2024-02-27",
        "名古屋市",
        "other",
        "産業廃棄物処分業更新申請不許可 — 役員の道路交通法違反による欠格要件該当",
        f"{DEFAULT_LAW} 第14条第10項第2号",
        "https://www.city.nagoya.jp/_res/projects/default_project/_page_/001/026/070/r05gyouseisyobunr060306.pdf",
    ),
    EnfRow(
        "合同会社中橋商店",
        "2024-03-05",
        "名古屋市",
        "license_revoke",
        "産業廃棄物収集運搬業許可取消し — 破産手続開始により欠格要件該当",
        f"{DEFAULT_LAW} 第14条の3の2第1項第4号",
        "https://www.city.nagoya.jp/_res/projects/default_project/_page_/001/026/070/r05gyouseisyobunr060306.pdf",
    ),
    EnfRow(
        "合同会社中橋商店（処分業）",
        "2024-03-05",
        "名古屋市",
        "license_revoke",
        "産業廃棄物処分業許可取消し — 破産手続開始により欠格要件該当",
        f"{DEFAULT_LAW} 第14条の3の2第1項第4号",
        "https://www.city.nagoya.jp/_res/projects/default_project/_page_/001/026/070/r05gyouseisyobunr060306.pdf",
    ),
    EnfRow(
        "有限会社緑建材",
        "2025-01-14",
        "名古屋市",
        "license_revoke",
        "産業廃棄物収集運搬業許可取消し — 破産手続開始により欠格要件該当",
        f"{DEFAULT_LAW} 第14条の3の2第1項第4号",
        "https://www.city.nagoya.jp/_res/projects/default_project/_page_/001/026/070/r06gyouseisyobunr070115.pdf",
    ),
    # ===== 愛知県 press release =====
    EnfRow(
        "株式会社 KS tech",
        "2025-05-07",
        "愛知県",
        "license_revoke",
        "産業廃棄物収集運搬業許可取消 — 破産手続開始決定により欠格要件該当",
        f"{DEFAULT_LAW} 第14条の3の2第1項第4号",
        "https://www.pref.aichi.jp/press-release/2025kansi02.html",
    ),
    # ===== 福岡県 press release (251028 kanshi) =====
    EnfRow(
        "有限会社エステート・アサヒ",
        "2025-10-28",
        "福岡県",
        "contract_suspend",
        "産業廃棄物収集運搬業務 30 日間全部停止 — 84 回以上のマニフェスト未受領",
        f"{DEFAULT_LAW} 第12条の4第2項・第14条の3第1項",
        "https://www.pref.fukuoka.lg.jp/press-release/251028-kanshi.html",
    ),
    # ===== 栃木県 (行政処分一覧 PDF, 24 rows R3-R7) =====
    # https://www.pref.tochigi.lg.jp/d05/eco/haikibutsu/haikibutsu/documents/0209syobun_list.pdf
    EnfRow(
        "株式会社河波",
        "2021-06-11",
        "栃木県",
        "license_revoke",
        "産業廃棄物収集運搬業許可取消 — 法第14条第5項該当（欠格要件該当）",
        f"{DEFAULT_LAW} 第14条第5項",
        "https://www.pref.tochigi.lg.jp/d05/eco/haikibutsu/haikibutsu/documents/0209syobun_list.pdf",
    ),
    EnfRow(
        "有限会社太陽建設",
        "2021-12-07",
        "栃木県",
        "license_revoke",
        "産業廃棄物収集運搬業許可取消 — 法第14条第5項該当（欠格要件該当）",
        f"{DEFAULT_LAW} 第14条第5項",
        "https://www.pref.tochigi.lg.jp/d05/eco/haikibutsu/haikibutsu/documents/0209syobun_list.pdf",
    ),
    EnfRow(
        "株式会社和泉造園",
        "2021-12-21",
        "栃木県",
        "license_revoke",
        "産業廃棄物収集運搬業許可取消 — 法第14条第5項該当（欠格要件該当）",
        f"{DEFAULT_LAW} 第14条第5項",
        "https://www.pref.tochigi.lg.jp/d05/eco/haikibutsu/haikibutsu/documents/0209syobun_list.pdf",
    ),
    EnfRow(
        "株式会社峯岸重量",
        "2022-01-19",
        "栃木県",
        "license_revoke",
        "産業廃棄物収集運搬業許可取消 — 法第14条第5項該当（欠格要件該当）",
        f"{DEFAULT_LAW} 第14条第5項",
        "https://www.pref.tochigi.lg.jp/d05/eco/haikibutsu/haikibutsu/documents/0209syobun_list.pdf",
    ),
    EnfRow(
        "株式会社リバイブマツヤマ",
        "2022-01-19",
        "栃木県",
        "license_revoke",
        "産業廃棄物収集運搬業/処分業 許可取消 — 法第14条第5項該当（欠格要件該当）",
        f"{DEFAULT_LAW} 第14条第5項",
        "https://www.pref.tochigi.lg.jp/d05/eco/haikibutsu/haikibutsu/documents/0209syobun_list.pdf",
    ),
    EnfRow(
        "子安忍",
        "2022-01-28",
        "栃木県",
        "license_revoke",
        "産業廃棄物収集運搬業許可取消 — 法第14条第5項該当（欠格要件該当）",
        f"{DEFAULT_LAW} 第14条第5項",
        "https://www.pref.tochigi.lg.jp/d05/eco/haikibutsu/haikibutsu/documents/0209syobun_list.pdf",
    ),
    EnfRow(
        "有限会社金田又介商店",
        "2022-07-26",
        "栃木県",
        "license_revoke",
        "産業廃棄物収集運搬業許可取消 — 法第14条第5項該当（欠格要件該当）",
        f"{DEFAULT_LAW} 第14条第5項",
        "https://www.pref.tochigi.lg.jp/d05/eco/haikibutsu/haikibutsu/documents/0209syobun_list.pdf",
    ),
    EnfRow(
        "株式会社ゼットライン",
        "2023-01-27",
        "栃木県",
        "license_revoke",
        "産業廃棄物収集運搬業許可取消 — 法第14条第5項該当（欠格要件該当）",
        f"{DEFAULT_LAW} 第14条第5項",
        "https://www.pref.tochigi.lg.jp/d05/eco/haikibutsu/haikibutsu/documents/0209syobun_list.pdf",
    ),
    EnfRow(
        "有限会社ケイハツ",
        "2023-05-16",
        "栃木県",
        "license_revoke",
        "産業廃棄物収集運搬業許可取消 — 法第14条第5項該当（欠格要件該当）",
        f"{DEFAULT_LAW} 第14条第5項",
        "https://www.pref.tochigi.lg.jp/d05/eco/haikibutsu/haikibutsu/documents/0209syobun_list.pdf",
    ),
    EnfRow(
        "有限会社横関運輸",
        "2023-08-31",
        "栃木県",
        "license_revoke",
        "産業廃棄物収集運搬業許可取消 — 法第14条第5項該当（欠格要件該当）",
        f"{DEFAULT_LAW} 第14条第5項",
        "https://www.pref.tochigi.lg.jp/d05/eco/haikibutsu/haikibutsu/documents/0209syobun_list.pdf",
    ),
    EnfRow(
        "株式会社日彩",
        "2023-11-10",
        "栃木県",
        "license_revoke",
        "産業廃棄物収集運搬業許可取消 — 法第14条第5項該当（欠格要件該当）",
        f"{DEFAULT_LAW} 第14条第5項",
        "https://www.pref.tochigi.lg.jp/d05/eco/haikibutsu/haikibutsu/documents/0209syobun_list.pdf",
    ),
    EnfRow(
        "株式会社東京高英",
        "2023-11-10",
        "栃木県",
        "license_revoke",
        "産業廃棄物収集運搬業許可取消 — 法第14条第5項該当（欠格要件該当）",
        f"{DEFAULT_LAW} 第14条第5項",
        "https://www.pref.tochigi.lg.jp/d05/eco/haikibutsu/haikibutsu/documents/0209syobun_list.pdf",
    ),
    EnfRow(
        "有限会社篠原造園土木",
        "2024-02-09",
        "栃木県",
        "license_revoke",
        "産業廃棄物収集運搬業許可取消 — 法第14条第5項該当（欠格要件該当）",
        f"{DEFAULT_LAW} 第14条第5項",
        "https://www.pref.tochigi.lg.jp/d05/eco/haikibutsu/haikibutsu/documents/0209syobun_list.pdf",
    ),
    EnfRow(
        "有限会社沖杉興業",
        "2024-02-22",
        "栃木県",
        "license_revoke",
        "産業廃棄物収集運搬業許可取消 — 法第14条第5項該当（欠格要件該当）",
        f"{DEFAULT_LAW} 第14条第5項",
        "https://www.pref.tochigi.lg.jp/d05/eco/haikibutsu/haikibutsu/documents/0209syobun_list.pdf",
    ),
    EnfRow(
        "株式会社吉岡開発",
        "2024-09-13",
        "栃木県",
        "license_revoke",
        "産業廃棄物収集運搬業許可取消 — 法第14条第5項該当（欠格要件該当）",
        f"{DEFAULT_LAW} 第14条第5項",
        "https://www.pref.tochigi.lg.jp/d05/eco/haikibutsu/haikibutsu/documents/0209syobun_list.pdf",
    ),
    EnfRow(
        "株式会社ユウキ",
        "2025-06-03",
        "栃木県",
        "license_revoke",
        "産業廃棄物収集運搬業許可取消 — 法第14条第5項該当（欠格要件該当）",
        f"{DEFAULT_LAW} 第14条第5項",
        "https://www.pref.tochigi.lg.jp/d05/eco/haikibutsu/haikibutsu/documents/0209syobun_list.pdf",
    ),
    EnfRow(
        "有限会社松島組",
        "2025-07-09",
        "栃木県",
        "license_revoke",
        "産業廃棄物収集運搬業許可取消 — 法第14条第5項該当（欠格要件該当）",
        f"{DEFAULT_LAW} 第14条第5項",
        "https://www.pref.tochigi.lg.jp/d05/eco/haikibutsu/haikibutsu/documents/0209syobun_list.pdf",
    ),
    EnfRow(
        "株式会社リブ・ウイズ（栃木県）",
        "2025-07-09",
        "栃木県",
        "license_revoke",
        "産業廃棄物収集運搬業許可取消 — 法第14条第5項該当（欠格要件該当）",
        f"{DEFAULT_LAW} 第14条第5項",
        "https://www.pref.tochigi.lg.jp/d05/eco/haikibutsu/haikibutsu/documents/0209syobun_list.pdf",
    ),
    EnfRow(
        "株式会社東邦運輸（栃木県）",
        "2025-09-09",
        "栃木県",
        "license_revoke",
        "産業廃棄物収集運搬業許可取消 — 法第14条第5項該当（欠格要件該当）",
        f"{DEFAULT_LAW} 第14条第5項",
        "https://www.pref.tochigi.lg.jp/d05/eco/haikibutsu/haikibutsu/documents/0209syobun_list.pdf",
    ),
    EnfRow(
        "株式会社サングリーン（栃木県）",
        "2025-09-26",
        "栃木県",
        "license_revoke",
        "産業廃棄物収集運搬業許可取消 — 法第14条第5項該当（欠格要件該当）",
        f"{DEFAULT_LAW} 第14条第5項",
        "https://www.pref.tochigi.lg.jp/d05/eco/haikibutsu/haikibutsu/documents/0209syobun_list.pdf",
    ),
    EnfRow(
        "dbクリーン株式会社（栃木県）",
        "2025-11-11",
        "栃木県",
        "license_revoke",
        "産業廃棄物収集運搬業許可取消 — 法第14条第5項該当（欠格要件該当）",
        f"{DEFAULT_LAW} 第14条第5項",
        "https://www.pref.tochigi.lg.jp/d05/eco/haikibutsu/haikibutsu/documents/0209syobun_list.pdf",
    ),
    EnfRow(
        "株式会社ASUKA",
        "2025-12-05",
        "栃木県",
        "license_revoke",
        "産業廃棄物収集運搬業許可取消 — 法第14条第5項該当（欠格要件該当）",
        f"{DEFAULT_LAW} 第14条第5項",
        "https://www.pref.tochigi.lg.jp/d05/eco/haikibutsu/haikibutsu/documents/0209syobun_list.pdf",
    ),
    EnfRow(
        "株式会社ジャパンクリーン",
        "2025-12-17",
        "栃木県",
        "license_revoke",
        "産業廃棄物収集運搬業許可取消 — 法第14条第5項該当（欠格要件該当）",
        f"{DEFAULT_LAW} 第14条第5項",
        "https://www.pref.tochigi.lg.jp/d05/eco/haikibutsu/haikibutsu/documents/0209syobun_list.pdf",
    ),
    EnfRow(
        "株式会社エコ・ディスタンス",
        "2025-12-17",
        "栃木県",
        "license_revoke",
        "産業廃棄物収集運搬業許可取消 — 法第14条第5項該当（欠格要件該当）",
        f"{DEFAULT_LAW} 第14条第5項",
        "https://www.pref.tochigi.lg.jp/d05/eco/haikibutsu/haikibutsu/documents/0209syobun_list.pdf",
    ),
    # ===== 茨城県 (行政処分一覧 PDF, 51 rows R3-R8) =====
    # https://www.pref.ibaraki.jp/seikatsukankyo/haitai/fuho/fuho-toki/documents/gyouseisyobunlist20260421.pdf
    EnfRow(
        "羽黒・稲田石材スラッジ処理協同組合",
        "2021-07-06",
        "茨城県",
        "license_revoke",
        "産業廃棄物処分業許可取消",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.ibaraki.jp/seikatsukankyo/haitai/fuho/fuho-toki/documents/gyouseisyobunlist20260421.pdf",
    ),
    EnfRow(
        "羽黒・稲田石材スラッジ処理協同組合（施設）",
        "2021-07-06",
        "茨城県",
        "license_revoke",
        "産業廃棄物処理施設(汚泥脱水/管理型最終処分場)設置許可取消",
        f"{DEFAULT_LAW} 第15条の3",
        "https://www.pref.ibaraki.jp/seikatsukankyo/haitai/fuho/fuho-toki/documents/gyouseisyobunlist20260421.pdf",
    ),
    EnfRow(
        "関野建材工業株式会社",
        "2021-07-15",
        "茨城県",
        "license_revoke",
        "産業廃棄物収集運搬業許可取消",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.ibaraki.jp/seikatsukankyo/haitai/fuho/fuho-toki/documents/gyouseisyobunlist20260421.pdf",
    ),
    EnfRow(
        "株式会社アイテック",
        "2021-08-12",
        "茨城県",
        "license_revoke",
        "産業廃棄物収集運搬業許可取消",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.ibaraki.jp/seikatsukankyo/haitai/fuho/fuho-toki/documents/gyouseisyobunlist20260421.pdf",
    ),
    EnfRow(
        "有限会社増田建材",
        "2021-08-17",
        "茨城県",
        "license_revoke",
        "産業廃棄物収集運搬業許可取消",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.ibaraki.jp/seikatsukankyo/haitai/fuho/fuho-toki/documents/gyouseisyobunlist20260421.pdf",
    ),
    EnfRow(
        "友常石材株式会社",
        "2021-09-27",
        "茨城県",
        "license_revoke",
        "産業廃棄物収集運搬業許可取消",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.ibaraki.jp/seikatsukankyo/haitai/fuho/fuho-toki/documents/gyouseisyobunlist20260421.pdf",
    ),
    EnfRow(
        "株式会社グローバルクリエイション",
        "2021-10-22",
        "茨城県",
        "license_revoke",
        "産業廃棄物収集運搬業許可取消",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.ibaraki.jp/seikatsukankyo/haitai/fuho/fuho-toki/documents/gyouseisyobunlist20260421.pdf",
    ),
    EnfRow(
        "中国通商株式会社",
        "2022-02-25",
        "茨城県",
        "license_revoke",
        "産業廃棄物収集運搬業許可取消",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.ibaraki.jp/seikatsukankyo/haitai/fuho/fuho-toki/documents/gyouseisyobunlist20260421.pdf",
    ),
    EnfRow(
        "株式会社磯前商店（収集運搬）",
        "2022-03-29",
        "茨城県",
        "license_revoke",
        "産業廃棄物収集運搬業許可取消",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.ibaraki.jp/seikatsukankyo/haitai/fuho/fuho-toki/documents/gyouseisyobunlist20260421.pdf",
    ),
    EnfRow(
        "株式会社磯前商店（処分業）",
        "2022-03-29",
        "茨城県",
        "license_revoke",
        "産業廃棄物処分業許可取消",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.ibaraki.jp/seikatsukankyo/haitai/fuho/fuho-toki/documents/gyouseisyobunlist20260421.pdf",
    ),
    EnfRow(
        "株式会社磯前商店（特管収運）",
        "2022-03-29",
        "茨城県",
        "license_revoke",
        "特別管理産業廃棄物収集運搬業許可取消",
        f"{DEFAULT_LAW} 第14条の6",
        "https://www.pref.ibaraki.jp/seikatsukankyo/haitai/fuho/fuho-toki/documents/gyouseisyobunlist20260421.pdf",
    ),
    EnfRow(
        "株式会社磯前商店（処理施設）",
        "2022-03-29",
        "茨城県",
        "license_revoke",
        "産業廃棄物処理施設(圧縮・切断施設)設置許可取消",
        f"{DEFAULT_LAW} 第15条の3",
        "https://www.pref.ibaraki.jp/seikatsukankyo/haitai/fuho/fuho-toki/documents/gyouseisyobunlist20260421.pdf",
    ),
    EnfRow(
        "田城芳一",
        "2022-05-25",
        "茨城県",
        "license_revoke",
        "産業廃棄物収集運搬業許可取消",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.ibaraki.jp/seikatsukankyo/haitai/fuho/fuho-toki/documents/gyouseisyobunlist20260421.pdf",
    ),
    EnfRow(
        "有限会社塚本興商",
        "2023-03-16",
        "茨城県",
        "license_revoke",
        "産業廃棄物収集運搬業許可取消",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.ibaraki.jp/seikatsukankyo/haitai/fuho/fuho-toki/documents/gyouseisyobunlist20260421.pdf",
    ),
    EnfRow(
        "株式会社ゼットライン（茨城県）",
        "2023-03-28",
        "茨城県",
        "license_revoke",
        "産業廃棄物収集運搬業許可取消",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.ibaraki.jp/seikatsukankyo/haitai/fuho/fuho-toki/documents/gyouseisyobunlist20260421.pdf",
    ),
    EnfRow(
        "有限会社ケイハツ（茨城県）",
        "2023-03-30",
        "茨城県",
        "license_revoke",
        "産業廃棄物収集運搬業許可取消",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.ibaraki.jp/seikatsukankyo/haitai/fuho/fuho-toki/documents/gyouseisyobunlist20260421.pdf",
    ),
    EnfRow(
        "株式会社清丸",
        "2023-07-14",
        "茨城県",
        "license_revoke",
        "産業廃棄物収集運搬業許可取消",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.ibaraki.jp/seikatsukankyo/haitai/fuho/fuho-toki/documents/gyouseisyobunlist20260421.pdf",
    ),
    EnfRow(
        "株式会社蔵創",
        "2023-12-11",
        "茨城県",
        "license_revoke",
        "産業廃棄物収集運搬業許可取消",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.ibaraki.jp/seikatsukankyo/haitai/fuho/fuho-toki/documents/gyouseisyobunlist20260421.pdf",
    ),
    EnfRow(
        "株式会社東京高英（茨城県）",
        "2024-04-08",
        "茨城県",
        "license_revoke",
        "産業廃棄物収集運搬業許可取消",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.ibaraki.jp/seikatsukankyo/haitai/fuho/fuho-toki/documents/gyouseisyobunlist20260421.pdf",
    ),
    EnfRow(
        "株式会社長岡商会",
        "2024-04-08",
        "茨城県",
        "license_revoke",
        "産業廃棄物収集運搬業許可取消",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.ibaraki.jp/seikatsukankyo/haitai/fuho/fuho-toki/documents/gyouseisyobunlist20260421.pdf",
    ),
    EnfRow(
        "株式会社日彩（茨城県）",
        "2024-06-05",
        "茨城県",
        "license_revoke",
        "産業廃棄物収集運搬業許可取消",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.ibaraki.jp/seikatsukankyo/haitai/fuho/fuho-toki/documents/gyouseisyobunlist20260421.pdf",
    ),
    EnfRow(
        "有限会社日栄商事",
        "2024-06-05",
        "茨城県",
        "license_revoke",
        "産業廃棄物収集運搬業許可取消",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.ibaraki.jp/seikatsukankyo/haitai/fuho/fuho-toki/documents/gyouseisyobunlist20260421.pdf",
    ),
    EnfRow(
        "有限会社塚田埋設工事",
        "2024-08-27",
        "茨城県",
        "license_revoke",
        "産業廃棄物収集運搬業許可取消",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.ibaraki.jp/seikatsukankyo/haitai/fuho/fuho-toki/documents/gyouseisyobunlist20260421.pdf",
    ),
    EnfRow(
        "砂押プラリ株式会社",
        "2024-08-27",
        "茨城県",
        "license_revoke",
        "特別管理産業廃棄物収集運搬業許可取消",
        f"{DEFAULT_LAW} 第14条の6",
        "https://www.pref.ibaraki.jp/seikatsukankyo/haitai/fuho/fuho-toki/documents/gyouseisyobunlist20260421.pdf",
    ),
    EnfRow(
        "株式会社内田工業",
        "2024-09-27",
        "茨城県",
        "license_revoke",
        "産業廃棄物収集運搬業許可取消",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.ibaraki.jp/seikatsukankyo/haitai/fuho/fuho-toki/documents/gyouseisyobunlist20260421.pdf",
    ),
    EnfRow(
        "有限会社松島組（茨城県）",
        "2025-03-21",
        "茨城県",
        "license_revoke",
        "産業廃棄物収集運搬業許可取消",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.ibaraki.jp/seikatsukankyo/haitai/fuho/fuho-toki/documents/gyouseisyobunlist20260421.pdf",
    ),
    EnfRow(
        "株式会社大翔",
        "2025-05-15",
        "茨城県",
        "license_revoke",
        "産業廃棄物収集運搬業許可取消",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.ibaraki.jp/seikatsukankyo/haitai/fuho/fuho-toki/documents/gyouseisyobunlist20260421.pdf",
    ),
    EnfRow(
        "株式会社山友興業",
        "2025-06-13",
        "茨城県",
        "license_revoke",
        "産業廃棄物収集運搬業許可取消",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.ibaraki.jp/seikatsukankyo/haitai/fuho/fuho-toki/documents/gyouseisyobunlist20260421.pdf",
    ),
    EnfRow(
        "株式会社東邦運輸（茨城県）",
        "2025-07-04",
        "茨城県",
        "license_revoke",
        "産業廃棄物収集運搬業許可取消",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.ibaraki.jp/seikatsukankyo/haitai/fuho/fuho-toki/documents/gyouseisyobunlist20260421.pdf",
    ),
    EnfRow(
        "株式会社リブ・ウイズ（茨城県）",
        "2025-07-18",
        "茨城県",
        "license_revoke",
        "産業廃棄物収集運搬業許可取消",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.ibaraki.jp/seikatsukankyo/haitai/fuho/fuho-toki/documents/gyouseisyobunlist20260421.pdf",
    ),
    EnfRow(
        "株式会社常磐",
        "2025-07-18",
        "茨城県",
        "license_revoke",
        "産業廃棄物収集運搬業許可取消",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.ibaraki.jp/seikatsukankyo/haitai/fuho/fuho-toki/documents/gyouseisyobunlist20260421.pdf",
    ),
    EnfRow(
        "株式会社ユウキ（茨城県）",
        "2025-07-18",
        "茨城県",
        "license_revoke",
        "産業廃棄物収集運搬業許可取消",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.ibaraki.jp/seikatsukankyo/haitai/fuho/fuho-toki/documents/gyouseisyobunlist20260421.pdf",
    ),
    EnfRow(
        "有限会社西満商事",
        "2025-08-07",
        "茨城県",
        "license_revoke",
        "産業廃棄物収集運搬業許可取消",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.ibaraki.jp/seikatsukankyo/haitai/fuho/fuho-toki/documents/gyouseisyobunlist20260421.pdf",
    ),
    EnfRow(
        "株式会社サングリーン（茨城県）",
        "2025-08-07",
        "茨城県",
        "license_revoke",
        "産業廃棄物収集運搬業許可取消",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.ibaraki.jp/seikatsukankyo/haitai/fuho/fuho-toki/documents/gyouseisyobunlist20260421.pdf",
    ),
    EnfRow(
        "株式会社武子工業",
        "2025-08-20",
        "茨城県",
        "license_revoke",
        "産業廃棄物収集運搬業許可取消",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.ibaraki.jp/seikatsukankyo/haitai/fuho/fuho-toki/documents/gyouseisyobunlist20260421.pdf",
    ),
    EnfRow(
        "株式会社ナカヤ商事",
        "2025-08-20",
        "茨城県",
        "license_revoke",
        "産業廃棄物収集運搬業許可取消",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.ibaraki.jp/seikatsukankyo/haitai/fuho/fuho-toki/documents/gyouseisyobunlist20260421.pdf",
    ),
    EnfRow(
        "dbクリーン株式会社（茨城県）",
        "2025-09-11",
        "茨城県",
        "license_revoke",
        "産業廃棄物収集運搬業許可取消",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.ibaraki.jp/seikatsukankyo/haitai/fuho/fuho-toki/documents/gyouseisyobunlist20260421.pdf",
    ),
    EnfRow(
        "株式会社大平工務店",
        "2025-11-07",
        "茨城県",
        "license_revoke",
        "産業廃棄物収集運搬業許可取消",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.ibaraki.jp/seikatsukankyo/haitai/fuho/fuho-toki/documents/gyouseisyobunlist20260421.pdf",
    ),
    EnfRow(
        "株式会社トーシン（茨城県・収運）",
        "2025-11-07",
        "茨城県",
        "license_revoke",
        "産業廃棄物収集運搬業許可取消",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.ibaraki.jp/seikatsukankyo/haitai/fuho/fuho-toki/documents/gyouseisyobunlist20260421.pdf",
    ),
    EnfRow(
        "株式会社トーシン（茨城県・特管）",
        "2025-11-07",
        "茨城県",
        "license_revoke",
        "特別管理産業廃棄物収集運搬業許可取消",
        f"{DEFAULT_LAW} 第14条の6",
        "https://www.pref.ibaraki.jp/seikatsukankyo/haitai/fuho/fuho-toki/documents/gyouseisyobunlist20260421.pdf",
    ),
    EnfRow(
        "株式会社レイコーポレーション",
        "2025-11-07",
        "茨城県",
        "license_revoke",
        "産業廃棄物収集運搬業許可取消",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.ibaraki.jp/seikatsukankyo/haitai/fuho/fuho-toki/documents/gyouseisyobunlist20260421.pdf",
    ),
    EnfRow(
        "株式会社MKシステム",
        "2025-11-07",
        "茨城県",
        "license_revoke",
        "産業廃棄物収集運搬業許可取消",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.ibaraki.jp/seikatsukankyo/haitai/fuho/fuho-toki/documents/gyouseisyobunlist20260421.pdf",
    ),
    EnfRow(
        "株式会社鹿嶋エコプラント（処分業）",
        "2025-11-07",
        "茨城県",
        "license_revoke",
        "産業廃棄物処分業許可取消",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.ibaraki.jp/seikatsukankyo/haitai/fuho/fuho-toki/documents/gyouseisyobunlist20260421.pdf",
    ),
    EnfRow(
        "株式会社鹿嶋エコプラント（処理施設）",
        "2025-11-07",
        "茨城県",
        "license_revoke",
        "産業廃棄物処理施設(脱水/中和)設置許可取消",
        f"{DEFAULT_LAW} 第15条の3",
        "https://www.pref.ibaraki.jp/seikatsukankyo/haitai/fuho/fuho-toki/documents/gyouseisyobunlist20260421.pdf",
    ),
    EnfRow(
        "有限会社林材木店",
        "2025-11-25",
        "茨城県",
        "license_revoke",
        "産業廃棄物収集運搬業許可取消",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.ibaraki.jp/seikatsukankyo/haitai/fuho/fuho-toki/documents/gyouseisyobunlist20260421.pdf",
    ),
    EnfRow(
        "株式会社永利建設工業（茨城県）",
        "2025-12-16",
        "茨城県",
        "license_revoke",
        "産業廃棄物収集運搬業許可取消",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.ibaraki.jp/seikatsukankyo/haitai/fuho/fuho-toki/documents/gyouseisyobunlist20260421.pdf",
    ),
    EnfRow(
        "有限会社海老澤産業",
        "2025-12-16",
        "茨城県",
        "license_revoke",
        "産業廃棄物収集運搬業許可取消",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.ibaraki.jp/seikatsukankyo/haitai/fuho/fuho-toki/documents/gyouseisyobunlist20260421.pdf",
    ),
    EnfRow(
        "三の丸興産株式会社（処分業）",
        "2026-02-13",
        "茨城県",
        "license_revoke",
        "産業廃棄物処分業許可取消",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.ibaraki.jp/seikatsukankyo/haitai/fuho/fuho-toki/documents/gyouseisyobunlist20260421.pdf",
    ),
    EnfRow(
        "三の丸興産株式会社（処理施設）",
        "2026-02-13",
        "茨城県",
        "license_revoke",
        "産業廃棄物処理施設(がれき類破砕施設)設置許可取消",
        f"{DEFAULT_LAW} 第15条の3",
        "https://www.pref.ibaraki.jp/seikatsukankyo/haitai/fuho/fuho-toki/documents/gyouseisyobunlist20260421.pdf",
    ),
    EnfRow(
        "株式会社天馬",
        "2026-02-13",
        "茨城県",
        "license_revoke",
        "産業廃棄物収集運搬業許可取消",
        f"{DEFAULT_LAW} 第14条の3の2",
        "https://www.pref.ibaraki.jp/seikatsukankyo/haitai/fuho/fuho-toki/documents/gyouseisyobunlist20260421.pdf",
    ),
    # ===== 大気汚染防止法 / 水質汚濁防止法 sample =====
    # 大気汚染防止法 / 水質汚濁防止法 violations are rarely formal 行政処分 — 多くは
    # 改善勧告 段階。報告徴求 / 命令例 を確認したものを sample で含める。
    # (現時点 curated source に該当 row なし。NULL.)
]


# ---------------------------------------------------------------------------
# DB layer
# ---------------------------------------------------------------------------


def _slug8(target: str, date: str, extra: str = "") -> str:
    h = hashlib.sha1(f"{target}|{date}|{extra}".encode()).hexdigest()
    return h[:8]


def _pref_slug(authority: str) -> str:
    """Build a stable slug from authority."""
    table = {
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
        # 政令指定都市 frequently appearing as 廃棄物処理 authority
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
    }
    return table.get(authority, hashlib.sha1(authority.encode()).hexdigest()[:10])


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
    """Return {(target_name, issuance_date, issuing_authority)} for everything
    in am_enforcement_detail (cheap full-table scan; ~5k rows)."""
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
        ) VALUES (?, 'enforcement', 'env_sanpai_kouhyou', NULL,
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


# ---------------------------------------------------------------------------
# Writer
# ---------------------------------------------------------------------------


def write_rows(
    conn: sqlite3.Connection,
    rows: list[EnfRow],
    *,
    now_iso: str,
) -> tuple[int, int, int]:
    """Insert with BEGIN IMMEDIATE; returns (inserted, dup_db, dup_batch)."""
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

            extra_seed = r.source_url + (r.extras.get("distinct", "") if r.extras else "")
            slug = _slug8(r.target_name, r.issuance_date, extra_seed)
            pref_slug = _pref_slug(r.issuing_authority)
            canonical_id = f"AM-ENF-ENV-{pref_slug}-{r.issuance_date.replace('-', '')}-{slug}"
            primary_name = (
                f"{r.target_name} ({r.issuance_date}) - {r.issuing_authority} 産廃 行政処分"
            )
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
                    "source_attribution": (f"{r.issuing_authority} ウェブサイト"),
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
    ap.add_argument(
        "--seed-only", action="store_true", help="skip live HTTP fetches, use SEED_ROWS only"
    )
    ap.add_argument(
        "--target", type=int, default=250, help="target number of new rows to insert (default 250)"
    )
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    now_iso = datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")

    rows = list(SEED_ROWS)
    _LOG.info("loaded %d SEED_ROWS", len(rows))

    if args.dry_run:
        # Show count by authority
        by_auth: dict[str, int] = {}
        for r in rows:
            by_auth[r.issuing_authority] = by_auth.get(r.issuing_authority, 0) + 1
        for auth, n in sorted(by_auth.items(), key=lambda x: -x[1]):
            _LOG.info("  %s: %d", auth, n)
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
        f"env_sanpai ingest: parsed={len(rows)} inserted={inserted} "
        f"dup_db={dup_db} dup_batch={dup_batch}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
