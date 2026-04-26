#!/usr/bin/env python3
"""ingest_jcci_programs.py — Ingest JCCI + 主要商工会議所 + 持続化補助金事務局 programs.

Source recon: analysis_wave18/data_collection_log/p5_recon_jcci.md
Target: >= 60 programs inserted/updated.

Strategy:
  - Curated program list derived from primary-source recon (no aggregator).
  - Per-URL HTTP verify (HEAD/GET) at 1 req/sec, UA AutonoMath/0.1.0.
  - Shift_JIS aware decode (try utf-8, then sjis, then iconv).
  - BEGIN IMMEDIATE + busy_timeout=300000 for parallel-write safety.
  - Dedup by (source_url, primary_name) before insert.
  - UNI-ext-<10hex> namespace via deterministic SHA-1 of (name, source_url).
  - Tier:
      S = primary HTTP 200 + open public window now
      A = primary HTTP 200 + open within 90 days
      B = otherwise (URL reachable but window unclear / closed / pure portal)
  - TOS compliance: facts only (name/dates/amounts/authority). No body copy.
    Attribution via source_url column (per CLAUDE.md "every row must cite a primary source").

NO Anthropic API. NO claude CLI. urllib + requests + BeautifulSoup only.

Usage:
    .venv/bin/python scripts/ingest/ingest_jcci_programs.py
    .venv/bin/python scripts/ingest/ingest_jcci_programs.py --dry-run
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sqlite3
import subprocess
import sys
import time
from datetime import UTC, date, datetime
from pathlib import Path

try:
    import requests
except ImportError as exc:
    print(f"missing dep: {exc}. pip install requests", file=sys.stderr)
    sys.exit(1)

_LOG = logging.getLogger("ingest_jcci_programs")

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_DB = REPO_ROOT / "data" / "jpintel.db"

USER_AGENT = "AutonoMath/0.1.0 (+https://bookyou.net)"
HTTP_TIMEOUT = 30
RATE_DELAY = 1.0  # 1 req/sec

# Today (used for tier S/A window checks). Frozen at module load — fine for one-shot ingest.
TODAY = date.today()


# ---------------------------------------------------------------------------
# Curated program list (sourced from p5_recon_jcci.md)
# ---------------------------------------------------------------------------
# Each row: name, authority_level, authority_name, prefecture, municipality,
#           program_kind, source_url, amount_max_man_yen, window_start (ISO date or None),
#           window_end (ISO date or None), notes (None — we don't copy body text).

PROGRAMS: list[dict] = [
    # --- 2-A. JCCI 受託・主導 国費系 (10 件) ---
    {
        "primary_name": "小規模事業者持続化補助金 一般型 通常枠 (第19回)",
        "authority_level": "national",
        "authority_name": "中小企業庁 / 日本商工会議所 (事務局)",
        "prefecture": None,
        "municipality": None,
        "program_kind": "subsidy",
        "source_url": "https://r6.jizokukahojokin.info/",
        "amount_max_man_yen": 50.0,
        "window_start": "2026-03-06",
        "window_end": "2026-04-30",
    },
    {
        "primary_name": "小規模事業者持続化補助金 創業型",
        "authority_level": "national",
        "authority_name": "中小企業庁 / 日本商工会議所 (事務局)",
        "prefecture": None,
        "municipality": None,
        "program_kind": "subsidy",
        "source_url": "https://r6.jizokukahojokin.info/sogyo/",
        "amount_max_man_yen": 200.0,
        "window_start": None,
        "window_end": None,
    },
    {
        "primary_name": "小規模事業者持続化補助金 共同事業型",
        "authority_level": "national",
        "authority_name": "中小企業庁 / 日本商工会議所 (事務局)",
        "prefecture": None,
        "municipality": None,
        "program_kind": "subsidy",
        "source_url": "https://www.jizokukahojokin.info/kyodo/",
        "amount_max_man_yen": None,
        "window_start": None,
        "window_end": None,
    },
    {
        "primary_name": "小規模事業者持続化補助金 災害支援型 (能登半島地震)",
        "authority_level": "national",
        "authority_name": "中小企業庁 / 日本商工会議所 (事務局)",
        "prefecture": None,
        "municipality": None,
        "program_kind": "subsidy",
        "source_url": "https://www.jizokukahojokin.info/",
        "amount_max_man_yen": None,
        "window_start": None,
        "window_end": None,
    },
    {
        "primary_name": "マル経融資 (小規模事業者経営改善資金)",
        "authority_level": "national",
        "authority_name": "日本政策金融公庫 / 商工会議所 (推薦)",
        "prefecture": None,
        "municipality": None,
        "program_kind": "loan",
        "source_url": "https://www.jcci.or.jp/support/financing/",
        "amount_max_man_yen": 2000.0,
        "window_start": None,
        "window_end": None,
    },
    {
        "primary_name": "経営発達支援計画 (商工会議所法 第7条の5 認定)",
        "authority_level": "national",
        "authority_name": "中小企業庁 / 日本商工会議所",
        "prefecture": None,
        "municipality": None,
        "program_kind": "certification",
        "source_url": "https://www.jcci.or.jp/support/",
        "amount_max_man_yen": None,
        "window_start": None,
        "window_end": None,
    },
    {
        "primary_name": "事業支援計画書 (様式4) 発行支援",
        "authority_level": "national",
        "authority_name": "日本商工会議所",
        "prefecture": None,
        "municipality": None,
        "program_kind": "support",
        "source_url": "https://www.jcci.or.jp/support/financing/",
        "amount_max_man_yen": None,
        "window_start": None,
        "window_end": None,
    },
    {
        "primary_name": "被災中小企業復興支援リース補助事業",
        "authority_level": "national",
        "authority_name": "日本商工会議所",
        "prefecture": None,
        "municipality": None,
        "program_kind": "subsidy",
        "source_url": "https://www.jcci.or.jp/support/information/fukkolease/",
        "amount_max_man_yen": None,
        "window_start": None,
        "window_end": None,
    },
    {
        "primary_name": "健康経営優良法人 認定支援",
        "authority_level": "national",
        "authority_name": "日本商工会議所",
        "prefecture": None,
        "municipality": None,
        "program_kind": "certification",
        "source_url": "https://www.jcci.or.jp/support/information/ccikenkoukeiei/",
        "amount_max_man_yen": None,
        "window_start": None,
        "window_end": None,
    },
    {
        "primary_name": "海外展開支援施策 (JCCI/METI/JETRO 連携)",
        "authority_level": "national",
        "authority_name": "日本商工会議所",
        "prefecture": None,
        "municipality": None,
        "program_kind": "support",
        "source_url": "https://www.jcci.or.jp/support/international/expansion/",
        "amount_max_man_yen": None,
        "window_start": None,
        "window_end": None,
    },
    {
        "primary_name": "貿易証明 (Certificate of Origin / 商事証明)",
        "authority_level": "national",
        "authority_name": "日本商工会議所",
        "prefecture": None,
        "municipality": None,
        "program_kind": "certification",
        "source_url": "https://www.jcci.or.jp/support/international/",
        "amount_max_man_yen": None,
        "window_start": None,
        "window_end": None,
    },
    {
        "primary_name": "輸出管理体制構築支援",
        "authority_level": "national",
        "authority_name": "日本商工会議所",
        "prefecture": None,
        "municipality": None,
        "program_kind": "support",
        "source_url": "https://www.jcci.or.jp/support/international/outreach/",
        "amount_max_man_yen": None,
        "window_start": None,
        "window_end": None,
    },
    {
        "primary_name": "電子認証サービス (JCCI)",
        "authority_level": "national",
        "authority_name": "日本商工会議所",
        "prefecture": None,
        "municipality": None,
        "program_kind": "certification",
        "source_url": "https://www.jcci.or.jp/support/other/",
        "amount_max_man_yen": None,
        "window_start": None,
        "window_end": None,
    },
    {
        "primary_name": "パートナーシップ構築宣言 (登録支援)",
        "authority_level": "national",
        "authority_name": "中小企業庁 / 日本商工会議所",
        "prefecture": None,
        "municipality": None,
        "program_kind": "certification",
        "source_url": "https://www.jcci.or.jp/support/information/partnership/",
        "amount_max_man_yen": None,
        "window_start": None,
        "window_end": None,
    },
    # --- 2-C. 主要 CCI 集約 (東商) ---
    {
        "primary_name": "東商 小規模事業者持続化補助金 (申請支援)",
        "authority_level": "prefecture",
        "authority_name": "東京商工会議所",
        "prefecture": "東京都",
        "municipality": None,
        "program_kind": "support",
        "source_url": "https://www.tokyo-cci.or.jp/jizokuka/",
        "amount_max_man_yen": 200.0,
        "window_start": None,
        "window_end": None,
    },
    {
        "primary_name": "東商 マル経融資 (推薦)",
        "authority_level": "prefecture",
        "authority_name": "東京商工会議所",
        "prefecture": "東京都",
        "municipality": None,
        "program_kind": "loan",
        "source_url": "https://www.tokyo-cci.or.jp/marukei/",
        "amount_max_man_yen": 2000.0,
        "window_start": None,
        "window_end": None,
    },
    {
        "primary_name": "東商 国・東京都の主な補助金・助成金 集約",
        "authority_level": "prefecture",
        "authority_name": "東京商工会議所",
        "prefecture": "東京都",
        "municipality": None,
        "program_kind": "support",
        "source_url": "https://www.tokyo-cci.or.jp/measures_info/",
        "amount_max_man_yen": None,
        "window_start": None,
        "window_end": None,
    },
    {
        "primary_name": "東商 ビジネスサポートデスク (BSD)",
        "authority_level": "prefecture",
        "authority_name": "東京商工会議所",
        "prefecture": "東京都",
        "municipality": None,
        "program_kind": "consulting",
        "source_url": "https://www.tokyo-cci.or.jp/bsd/",
        "amount_max_man_yen": None,
        "window_start": None,
        "window_end": None,
    },
    {
        "primary_name": "東商 創業・起業支援",
        "authority_level": "prefecture",
        "authority_name": "東京商工会議所",
        "prefecture": "東京都",
        "municipality": None,
        "program_kind": "support",
        "source_url": "https://www.tokyo-cci.or.jp/entre/",
        "amount_max_man_yen": None,
        "window_start": None,
        "window_end": None,
    },
    {
        "primary_name": "東商 事業承継ポータル",
        "authority_level": "prefecture",
        "authority_name": "東京商工会議所",
        "prefecture": "東京都",
        "municipality": None,
        "program_kind": "support",
        "source_url": "https://www.tokyo-cci.or.jp/jigyoshoukeiportal/",
        "amount_max_man_yen": None,
        "window_start": None,
        "window_end": None,
    },
    {
        "primary_name": "東商 価格転嫁支援",
        "authority_level": "prefecture",
        "authority_name": "東京商工会議所",
        "prefecture": "東京都",
        "municipality": None,
        "program_kind": "support",
        "source_url": "https://www.tokyo-cci.or.jp/kakaku-support/",
        "amount_max_man_yen": None,
        "window_start": None,
        "window_end": None,
    },
    {
        "primary_name": "東商 海外ビジネス相談",
        "authority_level": "prefecture",
        "authority_name": "東京商工会議所",
        "prefecture": "東京都",
        "municipality": None,
        "program_kind": "consulting",
        "source_url": "https://www.tokyo-cci.or.jp/soudan/globalsupport/",
        "amount_max_man_yen": None,
        "window_start": None,
        "window_end": None,
    },
    {
        "primary_name": "東商 都・区などの中小企業向けお知らせ",
        "authority_level": "prefecture",
        "authority_name": "東京商工会議所",
        "prefecture": "東京都",
        "municipality": None,
        "program_kind": "support",
        "source_url": "https://www.tokyo-cci.or.jp/support_measures/",
        "amount_max_man_yen": None,
        "window_start": None,
        "window_end": None,
    },
    # --- 2-C. 大商 ---
    {
        "primary_name": "大商 持続化補助金 一般型・通常枠 (申請支援)",
        "authority_level": "prefecture",
        "authority_name": "大阪商工会議所",
        "prefecture": "大阪府",
        "municipality": None,
        "program_kind": "support",
        "source_url": "https://www.osaka.cci.or.jp/emergency/ippan_skjj_hjk.pdf",
        "amount_max_man_yen": 50.0,
        "window_start": None,
        "window_end": None,
    },
    {
        "primary_name": "大商 持続化補助金 創業型 (申請支援)",
        "authority_level": "prefecture",
        "authority_name": "大阪商工会議所",
        "prefecture": "大阪府",
        "municipality": None,
        "program_kind": "support",
        "source_url": "https://www.osaka.cci.or.jp/emergency/sougyou_skjj_hjk.pdf",
        "amount_max_man_yen": 200.0,
        "window_start": None,
        "window_end": None,
    },
    {
        "primary_name": "大商 マル経融資 (推薦)",
        "authority_level": "prefecture",
        "authority_name": "大阪商工会議所",
        "prefecture": "大阪府",
        "municipality": None,
        "program_kind": "loan",
        "source_url": "https://www.osaka.cci.or.jp/pj/a/J01010000042.html",
        "amount_max_man_yen": 2000.0,
        "window_start": None,
        "window_end": None,
    },
    {
        "primary_name": "大商 生産性向上プロジェクト",
        "authority_level": "prefecture",
        "authority_name": "大阪商工会議所",
        "prefecture": "大阪府",
        "municipality": None,
        "program_kind": "support",
        "source_url": "https://www.osaka.cci.or.jp/itsupo/",
        "amount_max_man_yen": None,
        "window_start": None,
        "window_end": None,
    },
    {
        "primary_name": "大商 ビジネススクール",
        "authority_level": "prefecture",
        "authority_name": "大阪商工会議所",
        "prefecture": "大阪府",
        "municipality": None,
        "program_kind": "training",
        "source_url": "https://www.osaka.cci.or.jp/",
        "amount_max_man_yen": None,
        "window_start": None,
        "window_end": None,
    },
    {
        "primary_name": "大商 専門相談 (税務・法務・労務・知財)",
        "authority_level": "prefecture",
        "authority_name": "大阪商工会議所",
        "prefecture": "大阪府",
        "municipality": None,
        "program_kind": "consulting",
        "source_url": "https://www.osaka.cci.or.jp/",
        "amount_max_man_yen": None,
        "window_start": None,
        "window_end": None,
    },
    # --- 名商 ---
    {
        "primary_name": "名商 融資・補助金案内",
        "authority_level": "prefecture",
        "authority_name": "名古屋商工会議所",
        "prefecture": "愛知県",
        "municipality": "名古屋市",
        "program_kind": "support",
        "source_url": "https://www.nagoya-cci.or.jp/service_ichiran/shikin/",
        "amount_max_man_yen": None,
        "window_start": None,
        "window_end": None,
    },
    {
        "primary_name": "名商 マル経融資 (推薦)",
        "authority_level": "prefecture",
        "authority_name": "名古屋商工会議所",
        "prefecture": "愛知県",
        "municipality": "名古屋市",
        "program_kind": "loan",
        "source_url": "https://www.nagoya-cci.or.jp/shikin/yushi_maru.html",
        "amount_max_man_yen": 2000.0,
        "window_start": None,
        "window_end": None,
    },
    {
        "primary_name": "名商 各種補助金申請支援",
        "authority_level": "prefecture",
        "authority_name": "名古屋商工会議所",
        "prefecture": "愛知県",
        "municipality": "名古屋市",
        "program_kind": "support",
        "source_url": "https://www.nagoya-cci.or.jp/corona/hojokinpage20200422/",
        "amount_max_man_yen": None,
        "window_start": None,
        "window_end": None,
    },
    # --- 横浜商工会議所 ---
    {
        "primary_name": "横浜商工会議所 マル経融資 (推薦)",
        "authority_level": "prefecture",
        "authority_name": "横浜商工会議所",
        "prefecture": "神奈川県",
        "municipality": "横浜市",
        "program_kind": "loan",
        "source_url": "https://www.yokohama-cci.or.jp/executive/maru/",
        "amount_max_man_yen": 2000.0,
        "window_start": None,
        "window_end": None,
    },
    {
        "primary_name": "横浜商工会議所 9金融機関連携融資",
        "authority_level": "prefecture",
        "authority_name": "横浜商工会議所",
        "prefecture": "神奈川県",
        "municipality": "横浜市",
        "program_kind": "loan",
        "source_url": "https://www.yokohama-cci.or.jp/executive/9cooperation/",
        "amount_max_man_yen": None,
        "window_start": None,
        "window_end": None,
    },
    {
        "primary_name": "横浜商工会議所 創業支援融資【創業特例】",
        "authority_level": "prefecture",
        "authority_name": "横浜商工会議所",
        "prefecture": "神奈川県",
        "municipality": "横浜市",
        "program_kind": "loan",
        "source_url": "https://www.yokohama-cci.or.jp/executive/foundation_support/",
        "amount_max_man_yen": None,
        "window_start": None,
        "window_end": None,
    },
    {
        "primary_name": "横浜商工会議所 各種補助金情報提供",
        "authority_level": "prefecture",
        "authority_name": "横浜商工会議所",
        "prefecture": "神奈川県",
        "municipality": "横浜市",
        "program_kind": "support",
        "source_url": "https://www.yokohama-cci.or.jp/executive/smaller/",
        "amount_max_man_yen": None,
        "window_start": None,
        "window_end": None,
    },
    {
        "primary_name": "横浜商工会議所 経営革新等支援機関",
        "authority_level": "prefecture",
        "authority_name": "横浜商工会議所",
        "prefecture": "神奈川県",
        "municipality": "横浜市",
        "program_kind": "consulting",
        "source_url": "https://www.yokohama-cci.or.jp/executive/support_organizations/",
        "amount_max_man_yen": None,
        "window_start": None,
        "window_end": None,
    },
    # --- 神戸商工会議所 ---
    {
        "primary_name": "神戸商工会議所 マル経融資 (推薦)",
        "authority_level": "prefecture",
        "authority_name": "神戸商工会議所",
        "prefecture": "兵庫県",
        "municipality": "神戸市",
        "program_kind": "loan",
        "source_url": "https://www.kobe-cci.or.jp/support/marukeiyuusi/",
        "amount_max_man_yen": 2000.0,
        "window_start": None,
        "window_end": None,
    },
    {
        "primary_name": "神戸商工会議所 国・兵庫県・神戸市 中小企業向け融資",
        "authority_level": "prefecture",
        "authority_name": "神戸商工会議所",
        "prefecture": "兵庫県",
        "municipality": "神戸市",
        "program_kind": "loan",
        "source_url": "https://www.kobe-cci.or.jp/support/kouseidoyuusi/",
        "amount_max_man_yen": None,
        "window_start": None,
        "window_end": None,
    },
    {
        "primary_name": "神戸商工会議所 メンバーズ融資",
        "authority_level": "prefecture",
        "authority_name": "神戸商工会議所",
        "prefecture": "兵庫県",
        "municipality": "神戸市",
        "program_kind": "loan",
        "source_url": "https://www.kobe-cci.or.jp/support/kccimemyuusi/",
        "amount_max_man_yen": None,
        "window_start": None,
        "window_end": None,
    },
    # --- 福岡商工会議所 (13 件 — 福岡経由のみ) ---
    {
        "primary_name": "福岡商工会議所 持続化補助金 一般型 通常枠 (申請支援)",
        "authority_level": "prefecture",
        "authority_name": "福岡商工会議所",
        "prefecture": "福岡県",
        "municipality": "福岡市",
        "program_kind": "support",
        "source_url": "https://www.fukunet.or.jp/keieisodan/subsidy",
        "amount_max_man_yen": 50.0,
        "window_start": None,
        "window_end": None,
    },
    {
        "primary_name": "福岡商工会議所 持続化補助金 創業型 (申請支援)",
        "authority_level": "prefecture",
        "authority_name": "福岡商工会議所",
        "prefecture": "福岡県",
        "municipality": "福岡市",
        "program_kind": "support",
        "source_url": "https://www.fukunet.or.jp/keieisodan/subsidy",
        "amount_max_man_yen": 200.0,
        "window_start": None,
        "window_end": None,
    },
    {
        "primary_name": "福岡商工会議所 小規模事業者賃上げ稼ぐ力強化支援補助金 (案内)",
        "authority_level": "prefecture",
        "authority_name": "福岡商工会議所",
        "prefecture": "福岡県",
        "municipality": "福岡市",
        "program_kind": "support",
        "source_url": "https://www.fukunet.or.jp/keieisodan/subsidy",
        "amount_max_man_yen": None,
        "window_start": None,
        "window_end": None,
    },
    {
        "primary_name": "福岡商工会議所 デジタル化・AI 導入補助金 (案内)",
        "authority_level": "prefecture",
        "authority_name": "福岡商工会議所",
        "prefecture": "福岡県",
        "municipality": "福岡市",
        "program_kind": "support",
        "source_url": "https://www.fukunet.or.jp/keieisodan/subsidy",
        "amount_max_man_yen": 450.0,
        "window_start": None,
        "window_end": None,
    },
    {
        "primary_name": "福岡商工会議所 福岡県 IT 導入・賃上げ緊急支援補助金 (案内)",
        "authority_level": "prefecture",
        "authority_name": "福岡商工会議所",
        "prefecture": "福岡県",
        "municipality": "福岡市",
        "program_kind": "support",
        "source_url": "https://www.fukunet.or.jp/keieisodan/subsidy",
        "amount_max_man_yen": None,
        "window_start": None,
        "window_end": None,
    },
    {
        "primary_name": "福岡商工会議所 中小企業省力化投資補助金 一般型 (案内)",
        "authority_level": "prefecture",
        "authority_name": "福岡商工会議所",
        "prefecture": "福岡県",
        "municipality": "福岡市",
        "program_kind": "support",
        "source_url": "https://www.fukunet.or.jp/keieisodan/subsidy",
        "amount_max_man_yen": 10000.0,
        "window_start": None,
        "window_end": None,
    },
    {
        "primary_name": "福岡商工会議所 中小企業新事業進出促進補助金 (案内)",
        "authority_level": "prefecture",
        "authority_name": "福岡商工会議所",
        "prefecture": "福岡県",
        "municipality": "福岡市",
        "program_kind": "support",
        "source_url": "https://www.fukunet.or.jp/keieisodan/subsidy",
        "amount_max_man_yen": None,
        "window_start": None,
        "window_end": None,
    },
    {
        "primary_name": "福岡商工会議所 中小企業経営革新・賃上げ緊急支援補助金 (案内)",
        "authority_level": "prefecture",
        "authority_name": "福岡商工会議所",
        "prefecture": "福岡県",
        "municipality": "福岡市",
        "program_kind": "support",
        "source_url": "https://www.fukunet.or.jp/keieisodan/subsidy",
        "amount_max_man_yen": 135.0,
        "window_start": None,
        "window_end": None,
    },
    {
        "primary_name": "福岡商工会議所 事業再構築補助金 (案内)",
        "authority_level": "prefecture",
        "authority_name": "福岡商工会議所",
        "prefecture": "福岡県",
        "municipality": "福岡市",
        "program_kind": "support",
        "source_url": "https://www.fukunet.or.jp/keieisodan/subsidy",
        "amount_max_man_yen": None,
        "window_start": None,
        "window_end": None,
    },
    {
        "primary_name": "福岡商工会議所 ものづくり補助金 (案内)",
        "authority_level": "prefecture",
        "authority_name": "福岡商工会議所",
        "prefecture": "福岡県",
        "municipality": "福岡市",
        "program_kind": "support",
        "source_url": "https://www.fukunet.or.jp/keieisodan/subsidy",
        "amount_max_man_yen": None,
        "window_start": None,
        "window_end": None,
    },
    {
        "primary_name": "福岡商工会議所 業務改善助成金 (案内)",
        "authority_level": "prefecture",
        "authority_name": "福岡商工会議所",
        "prefecture": "福岡県",
        "municipality": "福岡市",
        "program_kind": "support",
        "source_url": "https://www.fukunet.or.jp/keieisodan/subsidy",
        "amount_max_man_yen": 600.0,
        "window_start": None,
        "window_end": None,
    },
    {
        "primary_name": "福岡商工会議所 J-Net21 補助金・助成金ポータル (案内)",
        "authority_level": "prefecture",
        "authority_name": "福岡商工会議所",
        "prefecture": "福岡県",
        "municipality": "福岡市",
        "program_kind": "portal_information",
        "source_url": "https://www.fukunet.or.jp/keieisodan/subsidy",
        "amount_max_man_yen": None,
        "window_start": None,
        "window_end": None,
    },
    {
        "primary_name": "福岡商工会議所 福岡労働局 助成金一覧 (案内)",
        "authority_level": "prefecture",
        "authority_name": "福岡商工会議所",
        "prefecture": "福岡県",
        "municipality": "福岡市",
        "program_kind": "portal_information",
        "source_url": "https://www.fukunet.or.jp/keieisodan/subsidy",
        "amount_max_man_yen": None,
        "window_start": None,
        "window_end": None,
    },
    # --- 京都商工会議所 ---
    {
        "primary_name": "京都商工会議所 マル経融資 (推薦)",
        "authority_level": "prefecture",
        "authority_name": "京都商工会議所",
        "prefecture": "京都府",
        "municipality": "京都市",
        "program_kind": "loan",
        "source_url": "https://www.kyo.or.jp/kyoto/finance/marukei.html",
        "amount_max_man_yen": 2000.0,
        "window_start": None,
        "window_end": None,
    },
    {
        "primary_name": "京都商工会議所 資金調達・融資案内",
        "authority_level": "prefecture",
        "authority_name": "京都商工会議所",
        "prefecture": "京都府",
        "municipality": "京都市",
        "program_kind": "loan",
        "source_url": "https://www.kyo.or.jp/kyoto/management/index_shikin.html",
        "amount_max_man_yen": None,
        "window_start": None,
        "window_end": None,
    },
    {
        "primary_name": "京都商工会議所 中小企業応援隊",
        "authority_level": "prefecture",
        "authority_name": "京都商工会議所",
        "prefecture": "京都府",
        "municipality": "京都市",
        "program_kind": "consulting",
        "source_url": "https://www.kyo.or.jp/kyoto/finance/support.html",
        "amount_max_man_yen": None,
        "window_start": None,
        "window_end": None,
    },
    {
        "primary_name": "京都商工会議所 補助金情報集約",
        "authority_level": "prefecture",
        "authority_name": "京都商工会議所",
        "prefecture": "京都府",
        "municipality": "京都市",
        "program_kind": "portal_information",
        "source_url": "https://www.kyo.or.jp/s/121346",
        "amount_max_man_yen": None,
        "window_start": None,
        "window_end": None,
    },
    # --- 札幌商工会議所 ---
    {
        "primary_name": "札幌商工会議所 経営相談・資金支援",
        "authority_level": "prefecture",
        "authority_name": "札幌商工会議所",
        "prefecture": "北海道",
        "municipality": "札幌市",
        "program_kind": "consulting",
        "source_url": "https://www.sapporo-cci.or.jp/web/purpose/04/",
        "amount_max_man_yen": None,
        "window_start": None,
        "window_end": None,
    },
    # --- 仙台商工会議所 ---
    {
        "primary_name": "仙台商工会議所 持続化補助金 (案内)",
        "authority_level": "prefecture",
        "authority_name": "仙台商工会議所",
        "prefecture": "宮城県",
        "municipality": "仙台市",
        "program_kind": "support",
        "source_url": "https://www.sendaicci.or.jp/news/2020/04/post-235.html",
        "amount_max_man_yen": 50.0,
        "window_start": None,
        "window_end": None,
    },
    {
        "primary_name": "仙台商工会議所 補助金支援サマリー",
        "authority_level": "prefecture",
        "authority_name": "仙台商工会議所",
        "prefecture": "宮城県",
        "municipality": "仙台市",
        "program_kind": "portal_information",
        "source_url": "https://www.sendaicci.or.jp/subsidy-support/",
        "amount_max_man_yen": None,
        "window_start": None,
        "window_end": None,
    },
    {
        "primary_name": "仙台商工会議所 商談展示会出展補助",
        "authority_level": "prefecture",
        "authority_name": "仙台商工会議所",
        "prefecture": "宮城県",
        "municipality": "仙台市",
        "program_kind": "subsidy",
        "source_url": "https://www.sendaicci.or.jp/exhibitionfee-subsidy.html",
        "amount_max_man_yen": None,
        "window_start": None,
        "window_end": None,
    },
    # --- 広島商工会議所 ---
    {
        "primary_name": "広島商工会議所 融資相談",
        "authority_level": "prefecture",
        "authority_name": "広島商工会議所",
        "prefecture": "広島県",
        "municipality": "広島市",
        "program_kind": "loan",
        "source_url": "https://www.hiroshimacci.or.jp/",
        "amount_max_man_yen": None,
        "window_start": None,
        "window_end": None,
    },
    # --- 持続化補助金事務局 (集約 / メニュー) ---
    {
        "primary_name": "持続化補助金事務局 メニューサイト (歴代回 + 特別対応型 集約)",
        "authority_level": "national",
        "authority_name": "持続化補助金事務局 (日本商工会議所 受託)",
        "prefecture": None,
        "municipality": None,
        "program_kind": "portal_information",
        "source_url": "https://www.jizokukahojokin.info/",
        "amount_max_man_yen": None,
        "window_start": None,
        "window_end": None,
    },
    {
        "primary_name": "持続化補助金 アーカイブ集約 (1〜16回 + 過去災害)",
        "authority_level": "national",
        "authority_name": "持続化補助金事務局 (日本商工会議所 受託)",
        "prefecture": None,
        "municipality": None,
        "program_kind": "portal_information",
        "source_url": "https://matome.jizokukahojokin.info/",
        "amount_max_man_yen": None,
        "window_start": None,
        "window_end": None,
    },
    {
        "primary_name": "持続化補助金 第14-16回 (過去) 案内",
        "authority_level": "national",
        "authority_name": "持続化補助金事務局 (日本商工会議所 受託)",
        "prefecture": None,
        "municipality": None,
        "program_kind": "portal_information",
        "source_url": "https://s23.jizokukahojokin.info/",
        "amount_max_man_yen": None,
        "window_start": None,
        "window_end": None,
    },
    # --- JCCI ハブ (情報カテゴリ起源 program 化可能) ---
    {
        "primary_name": "JCCI 経営相談ハブ",
        "authority_level": "national",
        "authority_name": "日本商工会議所",
        "prefecture": None,
        "municipality": None,
        "program_kind": "consulting",
        "source_url": "https://www.jcci.or.jp/support/soudan/",
        "amount_max_man_yen": None,
        "window_start": None,
        "window_end": None,
    },
    {
        "primary_name": "JCCI 融資制度・補助金ハブ",
        "authority_level": "national",
        "authority_name": "日本商工会議所",
        "prefecture": None,
        "municipality": None,
        "program_kind": "portal_information",
        "source_url": "https://www.jcci.or.jp/support/financing/",
        "amount_max_man_yen": None,
        "window_start": None,
        "window_end": None,
    },
    {
        "primary_name": "JCCI 保険・共済ハブ",
        "authority_level": "national",
        "authority_name": "日本商工会議所",
        "prefecture": None,
        "municipality": None,
        "program_kind": "insurance",
        "source_url": "https://www.jcci.or.jp/support/insurance/",
        "amount_max_man_yen": None,
        "window_start": None,
        "window_end": None,
    },
    {
        "primary_name": "JCCI 検定試験ハブ",
        "authority_level": "national",
        "authority_name": "日本商工会議所",
        "prefecture": None,
        "municipality": None,
        "program_kind": "examination",
        "source_url": "https://www.jcci.or.jp/support/examination/",
        "amount_max_man_yen": None,
        "window_start": None,
        "window_end": None,
    },
    {
        "primary_name": "JCCI ビジネス交流ハブ",
        "authority_level": "national",
        "authority_name": "日本商工会議所",
        "prefecture": None,
        "municipality": None,
        "program_kind": "support",
        "source_url": "https://www.jcci.or.jp/support/meetup/",
        "amount_max_man_yen": None,
        "window_start": None,
        "window_end": None,
    },
    {
        "primary_name": "JCCI 海外ビジネス・貿易証明ハブ",
        "authority_level": "national",
        "authority_name": "日本商工会議所",
        "prefecture": None,
        "municipality": None,
        "program_kind": "support",
        "source_url": "https://www.jcci.or.jp/support/international/",
        "amount_max_man_yen": None,
        "window_start": None,
        "window_end": None,
    },
    {
        "primary_name": "JCCI 情報提供・広報ハブ",
        "authority_level": "national",
        "authority_name": "日本商工会議所",
        "prefecture": None,
        "municipality": None,
        "program_kind": "portal_information",
        "source_url": "https://www.jcci.or.jp/support/information/",
        "amount_max_man_yen": None,
        "window_start": None,
        "window_end": None,
    },
    {
        "primary_name": "JCCI 知財支援 (情報提供)",
        "authority_level": "national",
        "authority_name": "日本商工会議所",
        "prefecture": None,
        "municipality": None,
        "program_kind": "support",
        "source_url": "https://www.jcci.or.jp/support/information/chizai/",
        "amount_max_man_yen": None,
        "window_start": None,
        "window_end": None,
    },
    {
        "primary_name": "JCCI 販路開拓支援 (情報提供)",
        "authority_level": "national",
        "authority_name": "日本商工会議所",
        "prefecture": None,
        "municipality": None,
        "program_kind": "support",
        "source_url": "https://www.jcci.or.jp/support/information/hanrokakudai/",
        "amount_max_man_yen": None,
        "window_start": None,
        "window_end": None,
    },
    {
        "primary_name": "JCCI DX/デジタル支援 (情報提供)",
        "authority_level": "national",
        "authority_name": "日本商工会議所",
        "prefecture": None,
        "municipality": None,
        "program_kind": "support",
        "source_url": "https://www.jcci.or.jp/support/information/digital/",
        "amount_max_man_yen": None,
        "window_start": None,
        "window_end": None,
    },
    {
        "primary_name": "JCCI 事業承継・引継ぎ支援 (情報提供)",
        "authority_level": "national",
        "authority_name": "日本商工会議所",
        "prefecture": None,
        "municipality": None,
        "program_kind": "support",
        "source_url": "https://www.jcci.or.jp/support/information/hikitsugi/",
        "amount_max_man_yen": None,
        "window_start": None,
        "window_end": None,
    },
    {
        "primary_name": "JCCI 多様な人材活躍 (情報提供)",
        "authority_level": "national",
        "authority_name": "日本商工会議所",
        "prefecture": None,
        "municipality": None,
        "program_kind": "support",
        "source_url": "https://www.jcci.or.jp/support/information/diversity/",
        "amount_max_man_yen": None,
        "window_start": None,
        "window_end": None,
    },
    {
        "primary_name": "JCCI 税制関連 (情報提供)",
        "authority_level": "national",
        "authority_name": "日本商工会議所",
        "prefecture": None,
        "municipality": None,
        "program_kind": "support",
        "source_url": "https://www.jcci.or.jp/support/information/taxreform/",
        "amount_max_man_yen": None,
        "window_start": None,
        "window_end": None,
    },
    {
        "primary_name": "JCCI 雇用・労働 (情報提供)",
        "authority_level": "national",
        "authority_name": "日本商工会議所",
        "prefecture": None,
        "municipality": None,
        "program_kind": "support",
        "source_url": "https://www.jcci.or.jp/support/information/labor/",
        "amount_max_man_yen": None,
        "window_start": None,
        "window_end": None,
    },
    {
        "primary_name": "JCCI エネルギー・環境 (情報提供)",
        "authority_level": "national",
        "authority_name": "日本商工会議所",
        "prefecture": None,
        "municipality": None,
        "program_kind": "support",
        "source_url": "https://www.jcci.or.jp/support/information/eco/",
        "amount_max_man_yen": None,
        "window_start": None,
        "window_end": None,
    },
    {
        "primary_name": "JCCI まちづくり支援 (情報提供)",
        "authority_level": "national",
        "authority_name": "日本商工会議所",
        "prefecture": None,
        "municipality": None,
        "program_kind": "support",
        "source_url": "https://www.jcci.or.jp/support/information/town/",
        "amount_max_man_yen": None,
        "window_start": None,
        "window_end": None,
    },
    {
        "primary_name": "JCCI 観光振興 (情報提供)",
        "authority_level": "national",
        "authority_name": "日本商工会議所",
        "prefecture": None,
        "municipality": None,
        "program_kind": "support",
        "source_url": "https://www.jcci.or.jp/support/information/tourism/",
        "amount_max_man_yen": None,
        "window_start": None,
        "window_end": None,
    },
    {
        "primary_name": "JCCI ものづくり支援 (情報提供)",
        "authority_level": "national",
        "authority_name": "日本商工会議所",
        "prefecture": None,
        "municipality": None,
        "program_kind": "support",
        "source_url": "https://www.jcci.or.jp/support/information/manufacturing/",
        "amount_max_man_yen": None,
        "window_start": None,
        "window_end": None,
    },
    {
        "primary_name": "JCCI 地域ブランド支援 (情報提供)",
        "authority_level": "national",
        "authority_name": "日本商工会議所",
        "prefecture": None,
        "municipality": None,
        "program_kind": "support",
        "source_url": "https://www.jcci.or.jp/support/information/localbland/",
        "amount_max_man_yen": None,
        "window_start": None,
        "window_end": None,
    },
    {
        "primary_name": "JCCI 経営者保証ガイドライン (情報提供)",
        "authority_level": "national",
        "authority_name": "日本商工会議所",
        "prefecture": None,
        "municipality": None,
        "program_kind": "support",
        "source_url": "https://www.jcci.or.jp/support/information/assurance/",
        "amount_max_man_yen": None,
        "window_start": None,
        "window_end": None,
    },
    {
        "primary_name": "JCCI 中小企業会計 (情報提供)",
        "authority_level": "national",
        "authority_name": "日本商工会議所",
        "prefecture": None,
        "municipality": None,
        "program_kind": "support",
        "source_url": "https://www.jcci.or.jp/support/information/accounting/",
        "amount_max_man_yen": None,
        "window_start": None,
        "window_end": None,
    },
    {
        "primary_name": "JCCI インボイス対応支援 (情報提供)",
        "authority_level": "national",
        "authority_name": "日本商工会議所",
        "prefecture": None,
        "municipality": None,
        "program_kind": "support",
        "source_url": "https://www.jcci.or.jp/support/information/invoice/",
        "amount_max_man_yen": None,
        "window_start": None,
        "window_end": None,
    },
    {
        "primary_name": "JCCI 価格交渉・転嫁支援 (情報提供)",
        "authority_level": "national",
        "authority_name": "日本商工会議所",
        "prefecture": None,
        "municipality": None,
        "program_kind": "support",
        "source_url": "https://www.jcci.or.jp/support/information/kakaku/",
        "amount_max_man_yen": None,
        "window_start": None,
        "window_end": None,
    },
    {
        "primary_name": "JCCI 能登半島地震 復興支援 (r6noto)",
        "authority_level": "national",
        "authority_name": "日本商工会議所",
        "prefecture": "石川県",
        "municipality": None,
        "program_kind": "support",
        "source_url": "https://www.jcci.or.jp/support/information/r6noto/",
        "amount_max_man_yen": None,
        "window_start": None,
        "window_end": None,
    },
]


# ---------------------------------------------------------------------------
# HTTP / decoding helpers
# ---------------------------------------------------------------------------


def _decode_response(resp: requests.Response) -> str:
    """Decode HTTP response with Shift_JIS fallback (per CLAUDE memory)."""
    raw = resp.content
    # Try declared encoding first
    if resp.encoding:
        try:
            return raw.decode(resp.encoding, errors="strict")
        except (UnicodeDecodeError, LookupError):
            pass
    # Try utf-8
    try:
        return raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        pass
    # Try shift_jis / cp932
    for enc in ("shift_jis", "cp932", "euc_jp"):
        try:
            return raw.decode(enc, errors="strict")
        except UnicodeDecodeError:
            continue
    # Last resort: iconv via subprocess (per memory feedback_shiftjis_encoding.md)
    try:
        out = subprocess.run(
            ["iconv", "-f", "SHIFT_JIS", "-t", "UTF-8", "-c"],
            input=raw,
            capture_output=True,
            timeout=10,
        )
        if out.returncode == 0:
            return out.stdout.decode("utf-8", errors="replace")
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return raw.decode("utf-8", errors="replace")


def verify_url(url: str, *, timeout: int = HTTP_TIMEOUT) -> tuple[int, str]:
    """Probe URL. Return (status_code, fetched_at_iso). Status 0 = network error."""
    headers = {"User-Agent": USER_AGENT}
    try:
        # GET (HEAD often blocked on Japanese gov sites)
        resp = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
        # Touch decode to exercise SJIS path / surface garbled body but we don't store it
        if resp.status_code == 200:
            _ = _decode_response(resp)
        return resp.status_code, datetime.now(UTC).isoformat()
    except requests.RequestException as exc:
        _LOG.warning("verify_fail url=%s err=%s", url, exc)
        return 0, datetime.now(UTC).isoformat()


# ---------------------------------------------------------------------------
# Tier classification
# ---------------------------------------------------------------------------


def classify_tier(status: int, window_start: str | None, window_end: str | None) -> str:
    """S: 200 + open now. A: 200 + open within 90 days. B: otherwise."""
    if status != 200:
        return "B"
    today = TODAY
    start = _parse_iso_date(window_start)
    end = _parse_iso_date(window_end)
    # Open now?
    if start and end and start <= today <= end:
        return "S"
    if start and not end and start <= today:
        return "S"
    if end and not start and today <= end:
        return "S"
    # Opens within 90 days?
    if start and start > today and (start - today).days <= 90:
        return "A"
    return "B"


def _parse_iso_date(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Insert / UPSERT
# ---------------------------------------------------------------------------


def ext_unified_id(name: str, source_url: str) -> str:
    blob = f"jcci|{name}|{source_url}".encode("utf-8")
    digest = hashlib.sha1(blob).hexdigest()[:10]
    return f"UNI-ext-{digest}"


def open_db(db_path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(str(db_path), isolation_level=None, timeout=300.0)
    con.execute("PRAGMA busy_timeout = 300000")
    con.execute("PRAGMA journal_mode = WAL")
    con.row_factory = sqlite3.Row
    return con


def upsert_program(
    con: sqlite3.Connection,
    prog: dict,
    status: int,
    fetched_at: str,
    now_iso: str,
) -> str:
    """Insert or refresh row. Returns 'insert' / 'update' / 'skip'."""
    name = prog["primary_name"]
    src = prog["source_url"]
    uid = ext_unified_id(name, src)
    tier = classify_tier(status, prog.get("window_start"), prog.get("window_end"))

    application_window: dict[str, str] = {}
    if prog.get("window_start"):
        application_window["start_date"] = prog["window_start"]
    if prog.get("window_end"):
        application_window["end_date"] = prog["window_end"]
    aw_json = json.dumps(application_window, ensure_ascii=False) if application_window else None

    enriched = {
        "_meta": {
            "ingest": "ingest_jcci_programs.py",
            "wave": "p5_jcci",
            "fetched_at": fetched_at,
            "http_status": status,
            "attribution": "出典: 日本商工会議所/各商工会議所/持続化補助金事務局 公式ページ",
        },
    }
    enriched_json = json.dumps(enriched, ensure_ascii=False)

    checksum = hashlib.sha1(f"{name}|{src}|{status}".encode("utf-8")).hexdigest()[:16]

    con.execute("BEGIN IMMEDIATE")
    try:
        prev = con.execute(
            "SELECT excluded FROM programs WHERE unified_id = ?", (uid,)
        ).fetchone()

        if prev is None:
            con.execute(
                """INSERT INTO programs (
                    unified_id, primary_name, aliases_json,
                    authority_level, authority_name, prefecture, municipality,
                    program_kind, official_url,
                    amount_max_man_yen, amount_min_man_yen, subsidy_rate,
                    trust_level, tier, coverage_score, gap_to_tier_s_json, a_to_j_coverage_json,
                    excluded, exclusion_reason,
                    crop_categories_json, equipment_category,
                    target_types_json, funding_purpose_json,
                    amount_band, application_window_json,
                    enriched_json, source_mentions_json,
                    source_url, source_fetched_at, source_checksum,
                    source_last_check_status, source_fail_count,
                    updated_at
                ) VALUES (
                    ?,?,?, ?,?,?,?, ?,?, ?,?,?,
                    ?,?,?,?,?,
                    ?,?,
                    ?,?,
                    ?,?,
                    ?,?,
                    ?,?,
                    ?,?,?,
                    ?,?,
                    ?
                )""",
                (
                    uid,
                    name,
                    None,
                    prog.get("authority_level"),
                    prog.get("authority_name"),
                    prog.get("prefecture"),
                    prog.get("municipality"),
                    prog.get("program_kind"),
                    src,  # official_url
                    prog.get("amount_max_man_yen"),
                    None,  # amount_min_man_yen
                    None,  # subsidy_rate
                    None,  # trust_level
                    tier,
                    None,  # coverage_score
                    None,  # gap_to_tier_s_json
                    None,  # a_to_j_coverage_json
                    0,  # excluded
                    None,  # exclusion_reason
                    None,  # crop_categories_json
                    None,  # equipment_category
                    None,  # target_types_json
                    None,  # funding_purpose_json
                    None,  # amount_band
                    aw_json,
                    enriched_json,
                    None,  # source_mentions_json
                    src,
                    fetched_at,
                    checksum,
                    status,
                    0,
                    now_iso,
                ),
            )
            # FTS row
            try:
                con.execute(
                    "INSERT INTO programs_fts(unified_id, primary_name, aliases, enriched_text) VALUES (?,?,?,?)",
                    (uid, name, "", name),
                )
            except sqlite3.OperationalError as e:
                _LOG.warning("fts_insert_skip uid=%s err=%s", uid, e)
            con.execute("COMMIT")
            return "insert"

        if prev["excluded"]:
            con.execute("ROLLBACK")
            return "skip"

        # Refresh source/tier/status
        con.execute(
            """UPDATE programs SET
                source_url = ?, source_fetched_at = ?, source_checksum = ?,
                source_last_check_status = ?,
                tier = ?, enriched_json = ?, application_window_json = COALESCE(application_window_json, ?),
                updated_at = ?
                WHERE unified_id = ?""",
            (src, fetched_at, checksum, status, tier, enriched_json, aw_json, now_iso, uid),
        )
        con.execute("COMMIT")
        return "update"
    except Exception:
        con.execute("ROLLBACK")
        raise


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def dedup(programs: list[dict]) -> list[dict]:
    seen: set[tuple[str, str]] = set()
    out: list[dict] = []
    for p in programs:
        key = (p["source_url"], p["primary_name"])
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--rate", type=float, default=RATE_DELAY)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    db_path = Path(args.db)
    if not db_path.exists() and not args.dry_run:
        _LOG.error("db not found: %s", db_path)
        return 1

    rows = dedup(PROGRAMS)
    _LOG.info("curated %d programs (post-dedup)", len(rows))

    now_iso = datetime.now(UTC).isoformat()

    if args.dry_run:
        for p in rows:
            print(p["primary_name"], "->", p["source_url"])
        print(f"total={len(rows)} (dry-run, no HTTP)")
        return 0

    con = open_db(db_path)
    counts = {"insert": 0, "update": 0, "skip": 0, "error": 0}
    tier_dist: dict[str, int] = {}

    for i, prog in enumerate(rows, 1):
        url = prog["source_url"]
        _LOG.info("[%d/%d] verify %s", i, len(rows), url)
        status, fetched_at = verify_url(url)
        tier_pre = classify_tier(status, prog.get("window_start"), prog.get("window_end"))
        tier_dist[tier_pre] = tier_dist.get(tier_pre, 0) + 1
        try:
            outcome = upsert_program(con, prog, status, fetched_at, now_iso)
        except Exception as exc:
            _LOG.exception("upsert_fail name=%s err=%s", prog["primary_name"], exc)
            counts["error"] += 1
        else:
            counts[outcome] = counts.get(outcome, 0) + 1
        # rate limit (skip last)
        if i < len(rows):
            time.sleep(args.rate)

    con.close()

    _LOG.info("done counts=%s tier_dist=%s", counts, tier_dist)
    print(json.dumps({"counts": counts, "tier_dist": tier_dist, "total_curated": len(rows)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
