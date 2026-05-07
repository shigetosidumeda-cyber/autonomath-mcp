#!/usr/bin/env python3
"""Auto-tag ``programs.jsic_majors`` from primary_name + funding_purpose +
target_types + crop_categories + enriched_json text body.

Migration 148 adds the ``programs.jsic_majors`` TEXT column (JSON array).
This script populates it deterministically (NO LLM) using a keyword
dictionary built from ``autonomath.db.am_industry_jsic`` (50 rows: 20
JSIC majors + 15 medium codes + 15 derivative entries).

Each program scores against every JSIC major and the top-2 are written
back as a JSON array (e.g. ``["E","G"]``). Programs with zero hits get
the safety fallback ``["T"]`` (分類不能の産業) so every row has at
least 1 tag — completion gate per the task spec.

Usage:
    python scripts/etl/auto_tag_program_jsic.py --dry-run
    python scripts/etl/auto_tag_program_jsic.py            # bulk UPDATE
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
JPINTEL_DB_DEFAULT = REPO_ROOT / "data" / "jpintel.db"
AUTONOMATH_DB_DEFAULT = REPO_ROOT / "autonomath.db"

JSIC_MAJOR_CODES: tuple[str, ...] = tuple("ABCDEFGHIJKLMNOPQRST")

# JSIC major fallback (分類不能の産業) — guarantees ≥ 1 tag per program.
FALLBACK_MAJOR = "T"

# Per-major synonym / derivative keyword bundle. Built ON TOP of am_industry_jsic
# 50 行 — adds the colloquial 公的補助金 言い回し that the JSIC official 名称
# alone misses (e.g. JSIC E manufacturing 「ものづくり」「設備投資」「省エネ」).
# Curated from src/jpintel_mcp/mcp/autonomath_tools/industry_packs.py
# fences (Wave 23) for D / E / K, plus equivalent fences for the other
# 17 majors. Each keyword scores +1; primary_name hits score +3.
_DERIVED_KEYWORDS: dict[str, tuple[str, ...]] = {
    "A": (
        "農業",
        "林業",
        "農林",
        "農家",
        "農地",
        "畜産",
        "酪農",
        "養豚",
        "養鶏",
        "果樹",
        "野菜",
        "稲作",
        "米作",
        "新規就農",
        "認定農業者",
        "農業法人",
        "森林",
        "林産",
        "木材",
        "間伐",
        "苗木",
        "植林",
        "農機",
        "農業機械",
        "ブルーベリー",
        "茶",
        "花き",
        "就農",
        "農村",
        "農協",
        "JA",
        "鳥獣被害",
        "電気柵",
        "獣害",
        "農地集積",
        "担い手",
        "圃場",
        "牧場",
        "オーガニック",
        "有機農業",
        "スマート農業",
        "麦",
        "大豆",
        "稲",
        "家畜",
        "防疫",
        "畜舎",
        "農産物",
        "農地流動化",
        "農業大学校",
        # W20-4 expansion
        "営農",
        "ほ場",
        "土壌",
        "堆肥",
        "肥料",
        "農薬",
        "種苗",
        "品種",
        "栽培",
        "収穫",
        "アグリ",
        "アグリチャレンジ",
        "産地交付金",
        "ゲタ",
        "水田",
        "畑作",
        "中干",
        "用排水",
        "浚渫",
        "耕作放棄",
        "農福",
        "森林経営",
        "里山",
        "獣害対策",
        "狩猟免許",
        "猟具",
        "わな猟",
        "鳥獣捕獲",
        "有害鳥獣",
        "アニマルウェルフェア",
        "飼養",
        "種苗法",
        "6次産業化",
        "地産地消",
        "みどりの食料システム",
        "アグリマイティ",
        "農産加工",
        "食料供給",
        "食品等持続的供給",
        "水稲",
        "農業共済",
        "農業者",
        "ほ場整備",
        "農業経営",
        "アグロフォレストリー",
        # W20-4 second pass
        "園芸",
        "市民農園",
        "貸し農園",
        "夢ある園芸",
        "園芸博覧会",
        "GREEN×EXPO",
        "農用地",
        "利子補給",
        "樹林",
        "野猪",
        "森林資源",
        "捕獲檻",
        "電気防護柵",
        "中干プロジェクト",
        "農業共済",
        "ナラシ",
        "収入減少",
        "農業GAP",
        "GAP",
    ),
    "B": (
        "漁業",
        "水産",
        "養殖",
        "漁港",
        "漁船",
        "漁協",
        "水産加工",
        "海面",
        "内水面",
        "養殖業",
        "海藻",
        "ノリ",
        "牡蠣",
        "真珠",
        "魚介",
        "漁村",
        "漁師",
        # W20-4 expansion
        "漁獲",
        "海洋",
        "MPA",
        "海洋保護区",
        "かき",
        "船員",
    ),
    "C": (
        "鉱業",
        "採石",
        "砂利",
        "採掘",
        "鉱山",
        "石材",
        "砂岩",
        "粘土",
        # W20-4 expansion
        "鉱害",
        "石油備蓄",
        "国家備蓄",
    ),
    "D": (
        "建設",
        "建築",
        "住宅",
        "空き家",
        "耐震",
        "改修",
        "リフォーム",
        "塗装",
        "工務",
        "土木",
        "解体",
        "リノベーション",
        "工事",
        "下請",
        "請負",
        "建設業",
        "施工",
        "舗装",
        "造園",
        "公共工事",
        "下水道",
        "上水道",
        "浄化槽",
        "都市計画",
        "土地区画整理",
        "再開発",
        "下水",
        # W20-4 expansion
        "経審",
        "経営事項審査",
        "宅地建物",
        "ZEH",
        "ZEB",
        "省エネ住宅",
        "建設業法",
        "建築基準",
        "建築士",
        "施工管理",
        "CCUS",
        "建設キャリア",
        "都市公園",
        "公園施設",
        "都市計画法",
        "建築物",
        "建設工事",
        "省CO2",
        "住宅政策",
        "住宅金融",
        "住宅供給",
        "公営住宅",
        "賃貸住宅",
        "マンション",
        "民有林",
        "造林",
        "拡大造林",
    ),
    "E": (
        "ものづくり",
        "製造",
        "設備投資",
        "省エネ",
        "GX",
        "脱炭素",
        "事業再構築",
        "工場",
        "生産",
        "技術開発",
        "製造業",
        "食料品",
        "飲料",
        "繊維",
        "金属",
        "機械",
        "electronics",
        "電気機械",
        "産業機械",
        "工業",
        "プラント",
        "成形",
        "精密",
        "省力化",
        "生産革新",
        "生産性向上",
        "ロボット",
        "半導体",
        "金型",
        "鋳造",
        "鍛造",
        "高付加価値化",
        "中堅・中小企業",
        "中堅",
        "TAKUMI",
        "伝統工芸",
        "ものづくり中核",
        # W20-4 expansion
        "化粧品",
        "医薬部外品",
        "食品表示",
        "食品衛生",
        "EV",
        "電気自動車",
        "クリーンエネルギー自動車",
        "CEV",
        "充電インフラ",
        "SAF",
        "Nadcap",
        "ISO9001",
        "ISO14001",
        "エコアクション",
        "QC",
        "暗号資産",
        "化学",
        "鉄鋼",
        "繊維製品",
        "産業育成",
        "産業振興",
        "新成長産業",
        "技術革新",
        "ぐんま技術革新",
        "事業適応計画",
        "カーボンニュートラル",
        "グリーン成長",
        "GX関連",
        "中小企業基盤",
        "ものづくり補助金",
        "新事業活動",
        "新事業創出",
        "新事業育成",
        "技術力強化",
        "技術開発",
        "イノベーション人材",
        "産業政策",
        "工業会",
    ),
    "F": (
        "電気事業",
        "ガス事業",
        "熱供給",
        "水道",
        "電力",
        "再生可能エネルギー",
        "再エネ",
        "太陽光",
        "風力",
        "水力",
        "発電",
        "送電",
        "新電力",
        "都市ガス",
        "LPガス",
        "水道事業",
        "下水処理",
        "電力会社",
        # W20-4 expansion
        "ユニバーサルサービス",
        "ブロードバンド",
        "ノンファーム",
        "コーポレートPPA",
        "PPA",
        "V2G",
        "Vehicle to Grid",
        "蓄電",
        "電力系統",
        "送配電",
        "ガス供給",
        "水素",
        "メタネーション",
        "供給構造高度化",
        "省CO2",
        # W20-4 second pass
        "V2H",
        "充放電設備",
        "外部給電",
        "配電",
        "配電事業",
        "エネルギーコスト",
        "Eツール",
        "業務用冷凍",
        "業務用冷蔵",
        "冷凍冷蔵機器",
        "気候変動",
        "気候変動適応",
        "適応法",
        "活火山",
        "活動火山",
    ),
    "G": (
        "情報通信",
        "IT",
        "ICT",
        "DX",
        "IT導入",
        "ソフトウェア",
        "システム開発",
        "情報サービス",
        "通信業",
        "インターネット",
        "クラウド",
        "AI",
        "データセンター",
        "5G",
        "サーバー",
        "アプリ開発",
        "デジタル",
        "デジタル化",
        "電子化",
        "ペーパーレス",
        "RPA",
        "IoT",
        "デジタル技術",
        "MaaS",
        "AIオンデマンド",
        "電子申請",
        "電子商取引",
        # W20-4 expansion
        "サイバーセキュリティ",
        "情報セキュリティ",
        "個人情報",
        "個人情報保護",
        "サイバー",
        "デジプラ",
        "データ",
        "プラットフォーマー",
        "オンラインモール",
        "Insurtech",
        "EC",
        "Eコマース",
        "電子帳簿",
        "ITコーディネータ",
        "情報処理",
        "情報処理支援機関",
        "スマートSME",
        "NTT",
        "情報通信業",
        "通信",
        "電話",
        # W20-4 second pass
        "セキュリティ",
        "セキュリティ・キャンプ",
        "BaaS",
        "Banking as a Service",
        "セキュリティトークン",
        "電子記録移転",
        "Fintech",
        "FinTech",
        "Japan Fintech",
        "マイナポータル",
        "ぴったりサービス",
        "V-Low",
        "マルチメディア放送",
        "情報インフラ",
        "メディア芸術",
        "アーカイブ推進",
        "GSAP",
        "テスト",
        "キーボード",
        "リテールマーケティング",
        "販売士",
    ),
    "H": (
        "運輸",
        "物流",
        "輸送",
        "郵便",
        "貨物",
        "宅配",
        "海運",
        "陸運",
        "鉄道",
        "バス事業",
        "タクシー",
        "トラック",
        "倉庫",
        "港湾",
        "航空",
        "航路",
        "海上輸送",
        "貨物自動車",
        "物流効率化",
        "運送業",
        "ドライバー",
        "自動車運送",
        # W20-4 expansion
        "空港",
        "航空法",
        "コンセッション",
        "セントレア",
        "関西国際空港",
        "羽田",
        "成田",
        "仙台空港",
        "高松空港",
        "福岡空港",
        "熊本空港",
        "広島空港",
        "首都圏空港",
        "国管理空港",
        "地方管理空港",
        "会社管理空港",
        "FAST TRAVEL",
        "道路交通法",
        "道路運送車両法",
        "自動運転",
        "ながら運転",
        "酒気帯び",
        "MICE",
        "MICE施設",
        "中古車",
        "USS",
        "中古車オークション",
        "自転車活用",
        # W20-4 second pass
        "船舶",
        "船舶産業",
        "省人化",
        "効率化",
        "公共交通",
        "交通機関",
        "地域交通",
        "交通利用環境",
        "無人運航船",
        "MEGURI2040",
        "二地域居住",
        "地域貢献",
        "自転車ヘルメット",
    ),
    "I": (
        "卸売",
        "小売",
        "商業",
        "商店",
        "商店街",
        "EC",
        "通信販売",
        "百貨店",
        "スーパー",
        "コンビニ",
        "店舗",
        "商業施設",
        "商人",
        "問屋",
        "販路開拓",
        "販路",
        "商店主",
        "市場開拓",
        "輸出支援",
        "海外展開",
        "首都圏販路",
        "アンテナショップ",
        # W20-4 expansion
        "牛丼チェーン",
        "ラーメンチェーン",
        "酒類",
        "酒類販売",
        "酒造業",
        "特定商取引",
        "訪問販売",
        "クーリング・オフ",
        "景品表示",
        "景表法",
        "景品類",
        "通信販売法",
        "ふるさと納税",
        "地場産品",
        "ふるさと名物",
        "EPA",
        "輸出",
        "海外販路",
        "アグリビジネス",
        "ガストロノミー",
        "食品ロス",
    ),
    "J": (
        "金融",
        "保険",
        "銀行",
        "信金",
        "信用金庫",
        "信用組合",
        "証券",
        "投資",
        "資金調達",
        "リース",
        "クレジット",
        "信用保証",
        "ファンド",
        "VC",
        "ベンチャーキャピタル",
        "クラウドファンディング",
        "預金保険",
        "ペイオフ",
        "エンジェル税制",
        "金融機関",
        "保証協会",
        "金融商品",
        "公庫",
        "政策金融公庫",
        "JFC",
        # W20-4 expansion
        "融資",
        "資金",
        "保証",
        "貸付",
        "貸金",
        "セーフティネット保証",
        "経営力強化保証",
        "セーフティネット",
        "経営者保証",
        "経営者保証ガイドライン",
        "事業資金",
        "経営継承",
        "再チャレンジ",
        "ソーシャルビジネス",
        "支援資金",
        "経営安定",
        "成長支援資金",
        "事業活動促進",
        "企業活力強化",
        "企業再建",
        "新事業育成",
        "経営体育成",
        "持続的供給促進",
        "短期運転資金",
        "手形割引",
        "当座貸越",
        "アグリチャレンジ・ゼロ",
        "あっせん融資",
        "REVIC",
        "地域経済活性化",
        "再生支援",
        "ファイナンス",
        "預金",
        "外国為替",
        "FX",
        "金融サービス",
        "iDeCo",
        "NISA",
        "確定拠出年金",
        "国民年金",
        "厚生年金",
        "障害年金",
        "遺族年金",
        "老齢基礎年金",
        "年金生活者",
        "年金",
        "原賠法",
        "原子力損害",
        "鉱害防止事業基金",
        "クレジットカード",
        # W20-4 second pass
        "シンジケートローン",
        "シンジケート",
        "本社機能等移転",
        "本社機能",
        "一時支援金",
        "支援金",
        "PFS",
        "Pay For Success",
        "成果連動型",
        "民間委託",
        "資金提供",
        "資金繰り",
    ),
    "K": (
        "不動産",
        "賃貸",
        "物品賃貸",
        "流通",
        "既存住宅",
        "住宅政策",
        "省エネ住宅",
        "宅地",
        "マンション",
        "テナント",
        "オフィス",
        "店舗賃貸",
        "貸付",
        "賃貸住宅",
        "不動産取引",
        # W20-4 expansion
        "空き家バンク",
        "宅建",
        "宅地建物取引",
        "土地",
        "土地取引",
        "土地区画",
        "土地利用",
    ),
    "L": (
        "学術研究",
        "研究開発",
        "R&D",
        "技術士",
        "弁理士",
        "公認会計士",
        "税理士",
        "司法書士",
        "行政書士",
        "社会保険労務士",
        "中小企業診断士",
        "コンサルタント",
        "デザイン",
        "広告",
        "建築設計",
        "技術サービス",
        "知的財産",
        "特許",
        "商標",
        "学術",
        "シンクタンク",
        "研究機関",
        "研究開発税制",
        "国際共同研究",
        "経済安全保障",
        "JST",
        "NEDO",
        "学術調査",
        "研究公募",
        # W20-4 expansion
        "研究助成",
        "研究提案",
        "研究公募",
        "研究推進",
        "研究費",
        "科研費",
        "科学技術",
        "科学技術研究",
        "学術助成",
        "助成金",
        "学術研究助成",
        "科学振興",
        "科学未来",
        "JCCI",
        "シンクタンク",
        "研究エリア",
        "知財",
        "弁護士",
        "監査法人",
        "監査",
        "経営支援",
        "経営計画",
        "経営改善計画",
        "経営革新計画",
        "経営力向上計画",
        "経営力向上",
        "経営戦略",
        "経営者",
        "経営相談",
        "経営指導",
        "コンサルティング",
        "アドバイザー",
        "事業計画",
        "プロジェクト推進",
        "SBIR",
        "STARTプログラム",
        "NEXUS",
        "F検",
        "ビジネス実務法務",
        "TNFD",
        "PMDA",
        "技術士法",
        "学術調査",
    ),
    "M": (
        "宿泊",
        "ホテル",
        "旅館",
        "民泊",
        "飲食",
        "レストラン",
        "居酒屋",
        "カフェ",
        "食堂",
        "観光宿泊",
        "宿泊業",
        "飲食店",
        "外食",
        "宴会",
        "ケータリング",
        "弁当",
        "酒類",
        "食品衛生",
    ),
    "N": (
        "理美容",
        "美容室",
        "理容",
        "クリーニング",
        "公衆浴場",
        "葬儀",
        "冠婚葬祭",
        "娯楽",
        "アミューズメント",
        "スポーツ",
        "フィットネス",
        "旅行業",
        "観光",
        "エンタメ",
        "ブライダル",
        "結婚支援",
        "結婚",
        "少子化対策",
        "子育て",
        "観光推進",
        "観光振興",
        "観光地",
        "ストーリー",
        "コミュニティ",
        # W20-4 expansion
        "サウナ",
        "JRA",
        "競馬",
        "競輪",
        "競艇",
        "ゴルフ場",
        "キャンプ場",
        "インバウンド",
        "MICE",
        "観光振興",
        "観光誘客",
        "誘客促進",
        "アート",
        "アートプロジェクト",
        "ふくいアート",
        "音楽配信",
        "音楽",
        "RIAJ",
        "JKA",
        "カラオケ",
        "映画",
        "劇映画",
        "映像企画",
        "JLOX",
        "プリプロダクション",
        "JRA",
        "婚活",
        "結婚新生活",
        "婚姻",
        "孤独",
        "孤立",
        "ひきこもり",
        "孤独・孤立",
        "男女共同参画",
        "ジェンダー",
        "女性活躍",
        "女性相談",
        "困難な問題を抱える女性",
        "アニマルウェルフェア",
        "MICE施設",
        "観光協会",
        # W20-4 second pass
        "和食",
        "ユネスコ",
        "無形文化遺産",
        "国際園芸博覧会",
        "GREEN×EXPO",
        "メディア芸術",
        "アーカイブ推進",
    ),
    "O": (
        "教育",
        "学習支援",
        "学校",
        "幼稚園",
        "保育園",
        "塾",
        "予備校",
        "スクール",
        "職業訓練",
        "リスキリング",
        "学び直し",
        "人材育成",
        "研修",
        "学習塾",
        "技能",
        "技能検定",
        "技能実習",
        "技能習得",
        "認定研修",
        "コミュニティ・スクール",
        "学校運営",
        "教員",
        "短期研修",
        "学校教育",
        # W20-4 expansion
        "私学",
        "私立学校",
        "国立大学",
        "大学",
        "短大",
        "高専",
        "大学院",
        "教育機関",
        "学校法人",
        "資格取得",
        "免許取得",
        "人材確保",
        "人材確保・定着",
        "若年層",
        "新卒",
        "就職",
        "就労支援",
        "就労定着",
        "就職氷河期",
        "後継者",
        "後継者人材",
        "人材バンク",
        "人材開発",
        "人材開発支援",
        "副業",
        "兼業",
        "学術調査",
        "学習指導",
        "産業人材",
        "認知症施策",
        "国際交流",
    ),
    "P": (
        "医療",
        "病院",
        "診療所",
        "クリニック",
        "歯科",
        "薬局",
        "薬剤師",
        "看護",
        "介護",
        "福祉",
        "保育",
        "障害者",
        "高齢者",
        "デイサービス",
        "訪問看護",
        "医療法人",
        "社会福祉法人",
        "ヘルスケア",
        "障害福祉",
        "BCP",
        "保健",
        "保健機能食品",
        "予防接種",
        "医療機関",
        "看護師",
        "介護士",
        "障害福祉従事者",
        "処遇改善",
        "両立支援",
        "ヘルプマーク",
        "産科",
        "助産",
        "高齢化",
        # W20-4 expansion
        "医師",
        "医師偏在",
        "勤務医",
        "薬剤",
        "薬機法",
        "PMDA",
        "副作用",
        "予防",
        "栄養成分",
        "栄養成分表示",
        "機能性表示食品",
        "健康増進",
        "健康経営",
        "母子保健",
        "母子",
        "子育て支援",
        "保育士",
        "ベビーシッター",
        "産後ケア",
        "障害福祉",
        "発達支援",
        "障害児",
        "認知症",
        "認知症施策",
        "相談支援",
        "生活困窮者",
        "自立相談",
        "自立支援",
        "マタニティマーク",
        "ワクチン",
        "感染症",
        "新型コロナ",
        "保健所",
        "保健機能",
        "在宅介護",
        "訪問介護",
        "障害者総合支援",
        "介護報酬",
        "医療費",
        "終末期",
        # W20-4 second pass
        "急患センター",
        "休日夜間",
        "急患",
        "救急",
        "救命",
        "特定疾患",
        "難病",
        "スモン",
        "肝炎",
        "膵炎",
        "健康企業",
        "健康企業宣言",
        "協会けんぽ",
        "子どもの居場所",
        "居場所づくり",
        "児童養護",
        "児童",
        "養護施設",
        "幼保",
        "登録販売",
        "リフィル処方箋",
        "処方箋",
    ),
    "Q": (
        "郵便局",
        "農業協同組合",
        "漁業協同組合",
        "複合サービス",
    ),
    "R": (
        "サービス業",
        "事業サービス",
        "派遣",
        "警備",
        "ビルメンテナンス",
        "清掃",
        "リサイクル",
        "廃棄物",
        "産業廃棄物",
        "環境対応",
        "中小企業",
        "小規模企業",
        "小規模事業者",
        "事業承継",
        "起業",
        "創業",
        "スタートアップ",
        "経営革新",
        "経営改善",
        "ベンチャー",
        "事業再生",
        "BCP",
        "ジョブ型",
        "雇用",
        "雇用助成",
        "賃上げ",
        "賃上げ促進",
        "両立支援",
        "働き方改革",
        "テレワーク",
        "外国人",
        "外国人材",
        "技能実習",
        "監理団体",
        "国際交流",
        "ODA",
        "JICA",
        "海外",
        "国際協力",
        "事業承継・集約",
        "中堅・中小企業",
        "事業所",
        "経営力向上",
        "事業者支援",
        "中小企業者",
        # W20-4 expansion
        "事業継続力強化",
        "BCP計画",
        "事業適応計画",
        "事業再編",
        "事業再構築",
        "事業継承",
        "後継者育成",
        "M&A",
        "PMI",
        "経営継続",
        "経営力強化",
        "中小企業診断",
        "経営診断",
        "中小企業基本法",
        "認定NPO",
        "公益法人",
        "公益財団",
        "公益社団",
        "NPO法人",
        "NPO",
        "認定支援機関",
        "経営革新等",
        "認定経営革新",
        "事業環境変化対応",
        "インボイス",
        "価格転嫁",
        "取引適正化",
        "下請け",
        "下請取引",
        "下請法",
        "独占禁止",
        "独禁法",
        "公正取引",
        "競争政策",
        "経営継承",
        "助成金",
        "雇用助成金",
        "労働",
        "労働組合",
        "労働基準",
        "労基法",
        "36協定",
        "ジョブカード",
        "労働条件",
        "賃金引上げ",
        "賃上げ促進税制",
        "社会保険",
        "社労士",
        "人材確保",
        "若手起業家",
        "VC育成",
        "アクセラレーター",
        "新興企業",
        "出前授業",
        "労務",
        "外国人雇用",
        "ハローワーク",
        "海のハローワーク",
        "在留資格",
        "永住許可",
        "人手不足",
        "人材",
        "ライフキャリア",
        "出産育児",
        "育休",
        "産休",
        "ハラスメント",
        "セクハラ",
        "パワハラ",
        "両立支援",
        "事業所内保育",
        "退職金共済",
        "中退共",
        "派遣事業",
        "職業安定",
        "ジョブ型雇用",
        "フリーランス",
        "フリーランス新法",
        "適格請求書",
        "経済団体",
        "商工会",
        "商工会議所",
        "商工労働",
        "商工政策",
        "中小機構",
        "RIETI",
        "犯罪収益移転防止",
        "犯収法",
        "Kerberos",
        "経営革新",
        # W20-4 second pass
        "JEED",
        "求人マッチング",
        "職場定着",
        "本社機能等移転",
        "本社機能",
        "立地促進",
        "企業立地",
        "立地支援",
        "誘致",
        "立地補助金",
        "中堅・中小",
        "補助金交付",
        "グループ補助金",
        "グループ化支援",
        "経営発展支援",
        "経営継続",
        "前橋市",
        "_",
        "_前橋",
        "_福井",
        "_松江",
        "_浜松",
        "_新潟",
        "経営計画実行",
        "事業拡張",
        "人財スキルアップ",
        "高知県",
        "兵庫県",
        "広島県",
        "茨城県",
        "新潟県",
        "徳島県",
        "群馬県",
        "人的資本経営",
        "人的資本",
        "ESG経営",
        "ダイバーシティ",
        "認証企業",
        "キャリア",
        "キャリアアップ",
        "スポットワーカー",
        "若年層",
        "認定企業",
        "セーフティネット",
        "雇用調整助成金",
        "就労支援",
        "就労",
        "国際化促進",
        "インターンシップ",
        "海外研修",
        "ネパール",
        "Tagalog",
        "Bahasa",
        "中文",
        "繁體",
        "外国人",
        "外国人材",
        "受入",
        "受入支援",
        "産地交付金",
        "ナラシ",
        "収入減少",
        "地域貢献",
        "コミュニティ",
        "エイジフレンドリー",
        "高齢者雇用",
        "経営発展支援事業",
        "発展支援",
    ),
    "S": (
        "公務",
        "自治体",
        "市町村",
        "都道府県",
        "国家公務",
        "地方公務",
        "地方創生",
        "地方創生起業",
        "公共施設",
        "庁舎",
        "選挙",
        "供託",
        "行政",
        "政府",
        "国土",
        "国土交通省",
        "総務省",
        "経産省",
        "厚労省",
        "農水省",
        "防災",
        "災害",
        "復興",
        "被災",
        "重要文化財",
        "文化財",
        "史跡",
        "天然記念物",
        "重要技術育成",
        # W20-4 expansion: tax/condition/government policy
        "税",
        "税制",
        "課税",
        "減税",
        "免税",
        "非課税",
        "控除",
        "税額控除",
        "所得控除",
        "租税",
        "租税特別措置",
        "措法",
        "贈与税",
        "相続税",
        "消費税",
        "法人税",
        "所得税",
        "事業税",
        "固定資産税",
        "都市計画税",
        "登録免許税",
        "印紙税",
        "酒税",
        "たばこ税",
        "ゴルフ場利用税",
        "国税",
        "地方税",
        "課徴金",
        "ふるさと納税",
        "ふるさと寄附",
        "寄附金控除",
        "配偶者控除",
        "ひとり親控除",
        "勤労学生控除",
        "寡婦控除",
        "外国税額控除",
        "簡易課税",
        "繰越控除",
        "新NISA",
        "NISA",
        # 法律/条例/政策
        "法律",
        "条例",
        "改正法",
        "改正",
        "ガイドライン",
        "基本計画",
        "基本方針",
        "基本法",
        "基準",
        "白書",
        "施策",
        "報告書",
        "通知",
        "通達",
        "答申",
        "審議会",
        "施行令",
        "施行規則",
        "政令",
        "省令",
        "告示",
        "通則",
        "解釈",
        "事務ガイドライン",
        "個人情報保護",
        "個人情報保護法",
        "APPI",
        "情報公表",
        "重点計画",
        "総合計画",
        "行動計画",
        "推進計画",
        "推進法",
        # 公共政策/制度
        "制度",
        "認定制度",
        "支援制度",
        "申請窓口",
        "相談窓口",
        "SHK制度",
        "在留資格",
        "永住",
        "選挙制度",
        "連座制",
        "補助金交付要綱",
        "交付要綱",
        "公募開始",
        "公募",
        "募集",
        "予算",
        "補正予算",
        "決算",
        "予算編成",
        # 行政施策レベル
        "国土交通",
        "総務",
        "経産",
        "厚生労働",
        "農林水産",
        "国交",
        "厚労",
        "農水",
        "経産省",
        "文科省",
        "文部科学",
        "外務",
        "防衛省",
        "デジタル庁",
        "環境省",
        "復興庁",
        "金融庁",
        "ふるさと再生",
        "地域再生",
        "地方創生",
        "地方",
        "地域づくり",
        "まちづくり",
        "地域支援",
        "地域活性化",
        "地域経済",
        "地域連携",
        "移住",
        "定住",
        "UIJターン",
        "関係人口",
        "田園回帰",
        "移住支援",
        "移住検討",
        "空き家バンク",
        # 防災・災害
        "防災",
        "災害",
        "復興",
        "被災",
        "地震",
        "豪雨",
        "津波",
        "原発事故",
        "能登半島地震",
        "災害支援",
        "防災・減災",
        "流域治水",
        # 政治・選挙
        "政治資金",
        "政治資金収支報告書",
        "選挙",
        "公職選挙",
        "政治資金監視委員会",
        # 公務的調査・統計
        "統計調査",
        "国勢調査",
        "経済センサス",
        "白書",
        "年次報告",
        "実態調査",
        "アンケート調査",
        "意識調査",
        # 国際/外交/防衛
        "外交",
        "国際協力",
        "ODA",
        "JICA",
        "EPA相談",
        "FTA",
        "経済連携",
        "防衛装備",
        "安全保障技術",
        "経済安全保障",
        "防衛省ファンディング",
        "重要物資",
        "経済安保",
        # 重複ガイドライン
        "経営者保証ガイドライン",
        "サイバーセキュリティ経営",
        "コーポレートガバナンス・コード",
        # W20-4 second pass: prefecture / generic site portals
        "都庁",
        "県ホームページ",
        "府ホームページ",
        "県／",
        "県公式",
        "ホームページ",
        "公式サイト",
        "美の国あきた",
        "とりネット",
        "なら県",
        "なら奈良",
        "ながさき",
        "ふくい",
        "やまがた",
        "戸別訪問禁止",
        "事前運動禁止",
        "文書図画規制",
        "選挙運動",
        "戸別訪問",
        "選挙制度",
        # 制度全般
        "国家試験",
        "国家資格",
        "司法試験",
        "予備試験",
        "試験",
        "登録販売者",
        "資格化",
        "国家資格化",
        "消費生活相談員",
        "消費者安全法",
        "消費生活",
        "消費者契約",
        "消費者基本法",
        "本社機能等移転",
        "本社機能等移転促進",
        "本社機能",
        "霊園",
        "都立霊園",
        "公営霊園",
        "合葬墓",
        "リフィル処方箋",
        "資源循環",
        "再資源化",
        "高度化法",
        "活火山",
        "気候変動適応",
        # 公共サービス基盤
        "PPP",
        "PFI",
        "民間活用",
        "官民連携",
        "コンセッション",
        "民間資金",
        "公共施設",
        "公共調達",
        "競争入札",
        "入札参加資格",
        "総合評価落札",
        "ユースエール",
        "プラチナ",
        # 文化財・公園
        "文化財保護",
        "天然記念物",
        "史跡",
        "国立公園",
        "自然公園",
        "公園施設長寿命化",
        "都市公園",
        "海洋保護区",
        "MPA",
        # 環境基準（行政制度として）
        "温室効果ガス",
        "排出量",
        "SHK",
        "カーボンフットプリント",
        "TNFD",
        "ESG",
        "サステナビリティ",
        "SDGs",
        "SDGs推進",
    ),
    "T": (
        # 分類不能 — fallback only, no positive keywords.
    ),
}


# ---------------------------------------------------------------------------
# Keyword dictionary build (am_industry_jsic + _DERIVED_KEYWORDS)
# ---------------------------------------------------------------------------


def _strip_paren(name: str) -> str:
    """Drop trailing parenthetical clauses for cleaner JSIC name keywords.

    Example: "サービス業（他に分類されないもの）" → "サービス業"
             "公務（他に分類されるものを除く）" → "公務"
             "鉱業、採石業、砂利採取業" → as-is (no paren)
    """
    cleaned = name
    for open_p, close_p in (("（", "）"), ("(", ")")):
        idx = cleaned.find(open_p)
        if idx != -1:
            close_idx = cleaned.find(close_p, idx)
            if close_idx != -1:
                cleaned = cleaned[:idx] + cleaned[close_idx + 1 :]
    return cleaned.strip()


def build_keyword_dict(am_conn: sqlite3.Connection) -> dict[str, set[str]]:
    """Return {jsic_major: set_of_keywords} from am_industry_jsic + derived.

    am_industry_jsic seeds the official JSIC name (split on 「、」 if needed).
    Medium codes are mapped to their parent major. _DERIVED_KEYWORDS adds
    colloquial 公的補助金 vocabulary (curated, not from upstream).
    """
    keywords: dict[str, set[str]] = {code: set() for code in JSIC_MAJOR_CODES}

    rows = am_conn.execute(
        "SELECT jsic_code, jsic_level, jsic_name_ja, parent_code FROM am_industry_jsic"
    ).fetchall()

    for row in rows:
        code = str(row["jsic_code"]).strip()
        level = str(row["jsic_level"]).strip()
        name = str(row["jsic_name_ja"]).strip()
        parent = str(row["parent_code"] or "").strip()

        if level == "major":
            major = code
        elif level == "medium" and parent in JSIC_MAJOR_CODES:
            major = parent
        else:
            continue

        if major not in keywords:
            continue

        cleaned = _strip_paren(name)
        # Split comma-separated names ("農業、林業" → ["農業", "林業"]).
        for chunk in cleaned.replace(",", "、").split("、"):
            piece = chunk.strip()
            if len(piece) >= 2:
                keywords[major].add(piece)

    # Layer derived keywords on top.
    for major, derived in _DERIVED_KEYWORDS.items():
        for kw in derived:
            if len(kw) >= 2:
                keywords[major].add(kw)

    return keywords


# ---------------------------------------------------------------------------
# Program text bundle — name + JSON arrays + enriched_json body
# ---------------------------------------------------------------------------


def _safe_json_text(value: Any) -> str:
    """Flatten a JSON-encoded list/dict column into a space-joined string."""
    if value is None:
        return ""
    if isinstance(value, str):
        text = value.strip()
        if not text or text in {"null", "[]", "{}"}:
            return ""
        try:
            decoded = json.loads(text)
        except (json.JSONDecodeError, ValueError):
            return text
    else:
        decoded = value

    if isinstance(decoded, list):
        return " ".join(_safe_json_text(item) for item in decoded)
    if isinstance(decoded, dict):
        return " ".join(_safe_json_text(v) for v in decoded.values())
    return str(decoded)


def _enriched_summary_text(enriched_json: str | None) -> str:
    """Return a compact text summary from enriched_json (truncated for speed).

    enriched_json blobs can be 50-200 KB. We only need string content for
    keyword match — pull primary_name + extraction.basic + extraction.target +
    extraction.purpose if present, else raw substring up to 8 KB.
    """
    if not enriched_json:
        return ""
    try:
        decoded = json.loads(enriched_json)
    except (json.JSONDecodeError, ValueError):
        return enriched_json[:8000]

    if not isinstance(decoded, dict):
        return str(decoded)[:8000]

    pieces: list[str] = []
    extraction = decoded.get("extraction") or {}
    if isinstance(extraction, dict):
        for section_key in (
            "basic",
            "target",
            "money",
            "purpose",
            "schedule",
            "summary",
            "abstract",
        ):
            section = extraction.get(section_key)
            if section is None:
                continue
            pieces.append(_safe_json_text(section))

    meta = decoded.get("_meta") or {}
    if isinstance(meta, dict):
        pieces.append(str(meta.get("program_name") or ""))

    text = " ".join(p for p in pieces if p)
    return text[:8000] if len(text) > 8000 else text


def build_program_text(
    primary_name: str,
    funding_purpose_json: str | None,
    target_types_json: str | None,
    crop_categories_json: str | None,
    enriched_json: str | None,
) -> tuple[str, str]:
    """Return (name_text, body_text) — name scored higher than body."""
    name_text = primary_name or ""
    body_pieces: list[str] = [
        _safe_json_text(funding_purpose_json),
        _safe_json_text(target_types_json),
        _safe_json_text(crop_categories_json),
        _enriched_summary_text(enriched_json),
    ]
    return name_text, " ".join(p for p in body_pieces if p)


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def score_program(
    name_text: str,
    body_text: str,
    keyword_dict: dict[str, set[str]],
) -> dict[str, int]:
    """Return {major: score}. name match scores +3, body match scores +1."""
    scores: dict[str, int] = {}
    for major, kws in keyword_dict.items():
        if not kws:
            continue
        score = 0
        for kw in kws:
            if kw in name_text:
                score += 3
            if kw in body_text:
                score += 1
        if score > 0:
            scores[major] = score
    return scores


def pick_top_majors(scores: dict[str, int], top_n: int = 2) -> list[str]:
    """Return up to top_n majors by score; ties broken by alphabetical code."""
    if not scores:
        return [FALLBACK_MAJOR]
    ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
    return [major for major, _ in ranked[:top_n]]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def _open_jpintel(path: Path, *, read_only: bool) -> sqlite3.Connection:
    if read_only:
        conn = sqlite3.connect(
            f"file:{path}?mode=ro",
            uri=True,
            timeout=30.0,
            check_same_thread=False,
        )
    else:
        conn = sqlite3.connect(str(path), timeout=30.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _open_autonomath_ro(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(
        f"file:{path}?mode=ro",
        uri=True,
        timeout=30.0,
        check_same_thread=False,
    )
    conn.row_factory = sqlite3.Row
    return conn


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__ or "")
    parser.add_argument(
        "--jpintel-db",
        type=Path,
        default=Path(os.environ.get("JPINTEL_DB_PATH", str(JPINTEL_DB_DEFAULT))),
        help="Path to jpintel.db (target).",
    )
    parser.add_argument(
        "--autonomath-db",
        type=Path,
        default=Path(os.environ.get("AUTONOMATH_DB_PATH", str(AUTONOMATH_DB_DEFAULT))),
        help="Path to autonomath.db (source of am_industry_jsic).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute distribution stats; do NOT bulk UPDATE programs.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Process at most N programs (0 = all). Useful for spot-check.",
    )
    parser.add_argument(
        "--include-excluded",
        action="store_true",
        help="Also tag rows with excluded=1 (default: skip them).",
    )
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    log = logging.getLogger("auto_tag_program_jsic")

    if not args.jpintel_db.exists():
        log.error("jpintel.db not found at %s", args.jpintel_db)
        return 2
    if not args.autonomath_db.exists():
        log.error("autonomath.db not found at %s", args.autonomath_db)
        return 2

    am_conn = _open_autonomath_ro(args.autonomath_db)
    keyword_dict = build_keyword_dict(am_conn)
    am_conn.close()

    keyword_total = sum(len(v) for v in keyword_dict.values())
    log.info(
        "keyword dictionary built: %d keywords across %d majors",
        keyword_total,
        sum(1 for v in keyword_dict.values() if v),
    )
    for major in JSIC_MAJOR_CODES:
        log.debug("  %s: %d keywords", major, len(keyword_dict[major]))

    # Verify migration 148 was applied.
    jp_conn = _open_jpintel(args.jpintel_db, read_only=False)
    cols = {row[1] for row in jp_conn.execute("PRAGMA table_info(programs)")}
    if "jsic_majors" not in cols:
        log.error(
            "programs.jsic_majors column missing — apply migration 148 first (scripts/migrate.py)."
        )
        jp_conn.close()
        return 3

    # Walk programs. Default skips quarantine + excluded.
    where_clauses = ["excluded = 0"] if not args.include_excluded else []
    where_sql = (" WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
    base_query = (
        "SELECT unified_id, primary_name, funding_purpose_json, "
        "       target_types_json, crop_categories_json, enriched_json "
        "FROM programs" + where_sql + " ORDER BY unified_id"
    )
    if args.limit:
        base_query += f" LIMIT {int(args.limit)}"

    rows = jp_conn.execute(base_query).fetchall()
    log.info("scanning %d programs", len(rows))

    distribution: Counter[str] = Counter()
    multi_tag_count = 0
    fallback_count = 0
    updates: list[tuple[str, str]] = []  # (jsic_majors_json, unified_id)

    for row in rows:
        name_text, body_text = build_program_text(
            primary_name=str(row["primary_name"] or ""),
            funding_purpose_json=row["funding_purpose_json"],
            target_types_json=row["target_types_json"],
            crop_categories_json=row["crop_categories_json"],
            enriched_json=row["enriched_json"],
        )
        scores = score_program(name_text, body_text, keyword_dict)
        majors = pick_top_majors(scores, top_n=2)

        for m in majors:
            distribution[m] += 1
        if len(majors) >= 2:
            multi_tag_count += 1
        if majors == [FALLBACK_MAJOR]:
            fallback_count += 1

        updates.append((json.dumps(majors, ensure_ascii=False), str(row["unified_id"])))

    # Distribution report.
    log.info("=" * 60)
    log.info("JSIC major distribution (program count, top-N tags counted):")
    name_lookup = {
        "A": "農業林業",
        "B": "漁業",
        "C": "鉱業",
        "D": "建設業",
        "E": "製造業",
        "F": "電気ガス水道",
        "G": "情報通信業",
        "H": "運輸郵便業",
        "I": "卸売小売業",
        "J": "金融保険業",
        "K": "不動産業",
        "L": "学術専門技術",
        "M": "宿泊飲食",
        "N": "生活サービス娯楽",
        "O": "教育学習支援",
        "P": "医療福祉",
        "Q": "複合サービス",
        "R": "サービス業他",
        "S": "公務",
        "T": "分類不能",
    }
    for major in JSIC_MAJOR_CODES:
        log.info(
            "  %s (%-12s): %5d programs",
            major,
            name_lookup[major],
            distribution[major],
        )
    log.info("-" * 60)
    log.info("multi-tag (≥2 majors): %d / %d", multi_tag_count, len(rows))
    log.info("fallback (T 分類不能 only): %d / %d", fallback_count, len(rows))
    log.info("=" * 60)

    if args.dry_run:
        log.info("DRY-RUN: no UPDATE applied. Re-run without --dry-run to commit.")
        jp_conn.close()
        return 0

    log.info("applying bulk UPDATE on %d rows ...", len(updates))
    jp_conn.execute("BEGIN")
    try:
        jp_conn.executemany(
            "UPDATE programs SET jsic_majors = ? WHERE unified_id = ?",
            updates,
        )
        jp_conn.commit()
    except sqlite3.Error as exc:
        jp_conn.rollback()
        log.error("bulk UPDATE failed: %s", exc)
        jp_conn.close()
        return 4

    # Verify ≥ 1 tag per touched row.
    if args.include_excluded:
        verify_filter = "jsic_majors IS NOT NULL"
        verify_total = "1=1"
    else:
        verify_filter = "excluded = 0 AND jsic_majors IS NOT NULL"
        verify_total = "excluded = 0"
    populated = jp_conn.execute(f"SELECT COUNT(*) FROM programs WHERE {verify_filter}").fetchone()[
        0
    ]
    total = jp_conn.execute(f"SELECT COUNT(*) FROM programs WHERE {verify_total}").fetchone()[0]
    log.info("verify: %d / %d programs have jsic_majors NOT NULL", populated, total)

    jp_conn.close()
    if populated < total:
        log.warning(
            "%d programs still NULL — investigate (likely race or filter mismatch)",
            total - populated,
        )
        return 5

    log.info("auto-tag complete at %s", datetime.now(UTC).isoformat())
    return 0


if __name__ == "__main__":
    sys.exit(main())
