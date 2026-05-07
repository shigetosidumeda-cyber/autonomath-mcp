#!/usr/bin/env python3
"""Generate 47 都道府県 × 22 業種 = 1,034 SEO/GEO landing pages for jpcite.com.

Each page targets a specific (prefecture, industry) combination and surfaces:
  1. h1 — 「{都道府県} の {業種} 向け補助金・税制・認定制度 まとめ」
  2. summary — counts + last-updated (JST)
  3. 制度 list — programs filtered by (matched-pref OR national) ∩ industry
                 keyword regex; tier S/A first, top 20
  4. 法令 cross-link — 5 distinct laws referenced by the surfaced programs
                       (via program_law_refs ∩ laws)
  5. 通達 cross-link — 3 NTA tsutatsu rows joined from autonomath.db
                       nta_tsutatsu_index
  6. 採択事例 — case_studies WHERE prefecture=pref AND industry_jsic=major,
               most recent 5
  7. CTA — API/MCP integration link

Inputs
------
- data/jpintel.db   : programs, laws, program_law_refs, case_studies
- autonomath.db     : nta_tsutatsu_index (jpcite root path)

Outputs
-------
- site/audiences/{pref_slug}/{industry_slug}/index.html  — 1,034 pages
- site/audiences/index.html                              — 47 × 22 matrix grid
                                                            (preserves existing
                                                            12-audience cards)
- site/sitemap-audiences.xml                             — re-written with all
                                                            existing audience
                                                            URLs + 1,034 new

22 業種 (industry slugs)
-----------------------
JSIC majors A-T (20) + 2 cross-cutting verticals (gx-decarbon, dx-it). Fixed
order so output is reproducible. Slugs are stable English keys, names are JA.

Constraints
-----------
- 100% honest copy. When a (pref, industry) pair has 0 matched programs the
  page is still emitted with explicit "該当する制度を確認できていません" copy
  and a fallback link to the prefecture-wide index. No fabrication.
- Aggregator domains (noukaweb / hojyokin-portal / biz.stayway) are filtered
  upstream of the SQL `tier IN ('S','A')` (already excluded by the bulk
  exclusion table); this script does not need to re-filter them.
- 税理士法 §52 disclaimer in footer.
- Idempotent — `_write_if_changed` skips unchanged outputs.
- DB connections opened read-only via SQLite URI (`mode=ro`).

Usage
-----
    uv run python scripts/generate_geo_industry_pages.py

    # subset for smoke test:
    uv run python scripts/generate_geo_industry_pages.py --samples 10
"""

from __future__ import annotations

import argparse
import contextlib
import json
import logging
import re
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = REPO_ROOT / "data" / "jpintel.db"
DEFAULT_AUTONOMATH_DB = REPO_ROOT / "autonomath.db"
DEFAULT_OUT = REPO_ROOT / "site" / "audiences"
DEFAULT_INDEX = REPO_ROOT / "site" / "audiences" / "index.html"
DEFAULT_SITEMAP = REPO_ROOT / "site" / "sitemap-audiences.xml"
DEFAULT_DOMAIN = "jpcite.com"

_JST = timezone(timedelta(hours=9))

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    from _pref_slugs import PREFECTURES, REGIONS  # type: ignore
except ImportError:  # pragma: no cover
    sys.stderr.write("ERROR: scripts/_pref_slugs.py not found.\n")
    raise

LOG = logging.getLogger("generate_geo_industry_pages")


OPERATOR_NAME = "Bookyou株式会社"
OPERATOR_REP = "梅田茂利"
OPERATOR_EMAIL = "info@bookyou.net"


# ---------------------------------------------------------------------------
# 22 industries: 20 JSIC majors (A-T) + 2 cross-cutting verticals
# ---------------------------------------------------------------------------


INDUSTRIES: list[dict[str, Any]] = [
    {
        "slug": "agriculture-forestry",
        "code": "A",
        "name_ja": "農業・林業",
        "regex_terms": (
            "農業",
            "林業",
            "就農",
            "農林",
            "農地",
            "担い手",
            "農産",
            "畜産",
            "酪農",
            "畑作",
            "稲作",
            "果樹",
            "野菜",
            "花き",
            "茶業",
            "養鶏",
            "養豚",
            "肉牛",
            "乳牛",
            "農機",
            "スマート農業",
            "6次産業",
            "六次産業",
            "中山間",
            "鳥獣",
            "森林",
            "造林",
            "間伐",
            "木材",
        ),
        "law_seed_keywords": ("農業", "林業", "森林"),
        "tsutatsu_law_canonical": ("law:shotoku-zei-tsutatsu", "law:hojin-zei-tsutatsu"),
    },
    {
        "slug": "fisheries",
        "code": "B",
        "name_ja": "漁業",
        "regex_terms": (
            "漁業",
            "水産",
            "養殖",
            "漁協",
            "沿岸漁業",
            "遠洋漁業",
            "種苗",
            "藻場",
            "魚礁",
            "漁港",
            "漁船",
        ),
        "law_seed_keywords": ("漁業", "水産"),
        "tsutatsu_law_canonical": ("law:shotoku-zei-tsutatsu",),
    },
    {
        "slug": "mining",
        "code": "C",
        "name_ja": "鉱業・採石業・砂利採取業",
        "regex_terms": ("鉱業", "採石", "砂利", "採掘", "鉱山"),
        "law_seed_keywords": ("鉱業", "鉱山"),
        "tsutatsu_law_canonical": ("law:hojin-zei-tsutatsu",),
    },
    {
        "slug": "construction",
        "code": "D",
        "name_ja": "建設業",
        "regex_terms": (
            "建設業",
            "建築",
            "建築物",
            "公共工事",
            "住宅取得",
            "住宅改修",
            "住宅リフォーム",
            "省エネ住宅",
            "耐震改修",
            "耐震診断",
            "空き家",
            "既存住宅",
            "木造住宅",
            "建設業退職金",
            "解体",
            "造成",
        ),
        "law_seed_keywords": ("建設業", "建築", "住宅"),
        "tsutatsu_law_canonical": ("law:hojin-zei-tsutatsu", "law:shouhi-zei-tsutatsu"),
    },
    {
        "slug": "manufacturing",
        "code": "E",
        "name_ja": "製造業",
        "regex_terms": (
            "製造業",
            "ものづくり",
            "ものづくり補助金",
            "工場",
            "工業",
            "サポイン",
            "Go-Tech",
            "先端設備",
            "設備投資",
            "食品製造",
            "食品加工",
            "食料品製造",
            "食品関連",
            "繊維工業",
            "繊維",
            "金属製品",
            "金属加工",
            "電子部品",
            "電気機械",
            "情報通信機械",
            "鉄鋼業",
            "化学工業",
            "プラスチック",
            "ゴム",
            "窯業",
            "木材加工",
            "紙パルプ",
            "印刷",
            "輸送機械",
            "自動車部品",
            "産業機械",
            "精密機械",
            "伝統工芸",
        ),
        "law_seed_keywords": ("製造", "ものづくり", "中小企業"),
        "tsutatsu_law_canonical": ("law:hojin-zei-tsutatsu", "law:shotoku-zei-tsutatsu"),
    },
    {
        "slug": "energy-utility",
        "code": "F",
        "name_ja": "電気・ガス・熱供給・水道業",
        "regex_terms": (
            "電気事業",
            "ガス事業",
            "熱供給",
            "水道事業",
            "再エネ",
            "再生可能",
            "太陽光発電",
            "風力発電",
            "地熱",
            "水力発電",
            "バイオマス発電",
            "電力小売",
        ),
        "law_seed_keywords": ("電気", "ガス", "再生可能"),
        "tsutatsu_law_canonical": ("law:hojin-zei-tsutatsu",),
    },
    {
        "slug": "ict",
        "code": "G",
        "name_ja": "情報通信業",
        "regex_terms": (
            "情報通信",
            "情報サービス",
            "ソフトウェア開発",
            "システム開発",
            "ITベンダー",
            "通信業",
            "デジタルコンテンツ",
            "クラウドサービス",
            "サイバーセキュリティ",
            "情報セキュリティ",
            "AI開発",
            "ソフトウェア産業",
            "情報処理",
            "IoT技術",
            "DX推進",
        ),
        "law_seed_keywords": ("情報通信", "電気通信"),
        "tsutatsu_law_canonical": ("law:hojin-zei-tsutatsu",),
    },
    {
        "slug": "transport-postal",
        "code": "H",
        "name_ja": "運輸業・郵便業",
        "regex_terms": (
            "運輸業",
            "貨物運送",
            "旅客運送",
            "トラック運送",
            "バス事業",
            "タクシー事業",
            "倉庫業",
            "物流",
            "海運",
            "港湾",
            "鉄道事業",
            "航空運送",
            "宅配便",
            "配送業",
        ),
        "law_seed_keywords": ("運輸", "貨物", "物流"),
        "tsutatsu_law_canonical": ("law:hojin-zei-tsutatsu",),
    },
    {
        "slug": "wholesale-retail",
        "code": "I",
        "name_ja": "卸売業・小売業",
        "regex_terms": (
            "卸売業",
            "小売業",
            "商店街",
            "商業振興",
            "商工振興",
            "商業近代化",
            "商業集積",
            "店舗改装",
            "店舗改修",
            "シャッター街",
            "中心市街地",
            "店舗",
            "EC事業",
            "EC化",
            "通信販売",
            "ネット販売",
            "販路開拓",
        ),
        "law_seed_keywords": ("卸売", "小売", "商業"),
        "tsutatsu_law_canonical": ("law:shouhi-zei-tsutatsu", "law:hojin-zei-tsutatsu"),
    },
    {
        "slug": "finance-insurance",
        "code": "J",
        "name_ja": "金融業・保険業",
        "regex_terms": (
            "金融業",
            "保険業",
            "信用金庫",
            "信用組合",
            "地域金融機関",
            "ファイナンス",
            "金融サービス",
        ),
        "law_seed_keywords": ("金融", "保険", "信用"),
        "tsutatsu_law_canonical": ("law:hojin-zei-tsutatsu",),
    },
    {
        "slug": "real-estate",
        "code": "K",
        "name_ja": "不動産業・物品賃貸業",
        "regex_terms": (
            "不動産業",
            "不動産取引",
            "宅建",
            "宅地建物取引",
            "物品賃貸",
            "リース業",
            "レンタル業",
            "不動産仲介",
            "賃貸住宅",
        ),
        "law_seed_keywords": ("不動産", "宅地", "宅建"),
        "tsutatsu_law_canonical": ("law:shotoku-zei-tsutatsu", "law:souzoku-zei-tsutatsu"),
    },
    {
        "slug": "research-professional",
        "code": "L",
        "name_ja": "学術研究・専門・技術サービス業",
        "regex_terms": (
            "学術研究",
            "学術",
            "科学研究",
            "研究開発",
            "研究助成",
            "学術振興",
            "技術士",
            "中小企業診断士",
            "弁理士",
            "公認会計士",
            "税理士",
            "社会保険労務士",
            "行政書士",
            "司法書士",
            "建築士",
            "経営コンサルタント",
            "シンクタンク",
        ),
        "law_seed_keywords": ("研究", "学術", "技術"),
        "tsutatsu_law_canonical": ("law:hojin-zei-tsutatsu",),
    },
    {
        "slug": "hospitality-restaurant",
        "code": "M",
        "name_ja": "宿泊業・飲食サービス業",
        "regex_terms": (
            "宿泊業",
            "宿泊事業",
            "飲食業",
            "飲食店",
            "観光業",
            "観光振興",
            "ホテル",
            "旅館",
            "民宿",
            "民泊",
            "レストラン",
            "食堂",
            "居酒屋",
            "カフェ",
            "インバウンド",
            "観光地域",
        ),
        "law_seed_keywords": ("旅館", "飲食", "観光"),
        "tsutatsu_law_canonical": ("law:shouhi-zei-tsutatsu", "law:hojin-zei-tsutatsu"),
    },
    {
        "slug": "lifestyle-entertainment",
        "code": "N",
        "name_ja": "生活関連サービス業・娯楽業",
        "regex_terms": (
            "生活関連",
            "理美容",
            "美容業",
            "理容業",
            "クリーニング",
            "銭湯",
            "公衆浴場",
            "結婚式場",
            "葬儀",
            "冠婚葬祭",
            "娯楽業",
            "映画館",
            "スポーツ施設",
            "フィットネス",
            "観光協会",
        ),
        "law_seed_keywords": ("生活衛生", "公衆浴場"),
        "tsutatsu_law_canonical": ("law:hojin-zei-tsutatsu",),
    },
    {
        "slug": "education",
        "code": "O",
        "name_ja": "教育・学習支援業",
        "regex_terms": (
            "教育機関",
            "学校教育",
            "学習支援",
            "学校法人",
            "幼稚園",
            "保育園",
            "認定こども園",
            "学習塾",
            "予備校",
            "専修学校",
            "各種学校",
            "高等学校",
            "大学",
            "私立学校",
            "教員",
        ),
        "law_seed_keywords": ("学校", "教育"),
        "tsutatsu_law_canonical": ("law:hojin-zei-tsutatsu",),
    },
    {
        "slug": "medical-welfare",
        "code": "P",
        "name_ja": "医療・福祉",
        "regex_terms": (
            "医療業",
            "医療法人",
            "病院",
            "診療所",
            "クリニック",
            "歯科",
            "薬局",
            "在宅医療",
            "訪問看護",
            "介護事業",
            "介護施設",
            "介護保険",
            "障害福祉",
            "障害者就労",
            "保育所",
            "児童福祉",
            "高齢者福祉",
            "認知症",
            "地域包括",
            "看護師",
            "医師確保",
        ),
        "law_seed_keywords": ("医療", "介護", "福祉"),
        "tsutatsu_law_canonical": ("law:hojin-zei-tsutatsu",),
    },
    {
        "slug": "compound-services",
        "code": "Q",
        "name_ja": "複合サービス事業",
        "regex_terms": (
            "郵便局",
            "農業協同組合",
            "JA",
            "漁業協同組合",
            "森林組合",
            "事業協同組合",
            "中小企業組合",
            "協同組合",
        ),
        "law_seed_keywords": ("協同組合", "中小企業組合"),
        "tsutatsu_law_canonical": ("law:hojin-zei-tsutatsu",),
    },
    {
        "slug": "other-services",
        "code": "R",
        "name_ja": "サービス業（他に分類されないもの）",
        "regex_terms": (
            "サービス業",
            "対事業所サービス",
            "経営コンサルティング",
            "人材紹介",
            "労働者派遣",
            "ビルメンテナンス",
            "警備業",
            "廃棄物処理",
            "リサイクル",
            "産業廃棄物",
        ),
        "law_seed_keywords": ("廃棄物", "労働者派遣"),
        "tsutatsu_law_canonical": ("law:hojin-zei-tsutatsu",),
    },
    {
        "slug": "public-service",
        "code": "S",
        "name_ja": "公務（他に分類されるものを除く）",
        "regex_terms": (
            "地方公共団体",
            "市町村",
            "公務員",
            "自治体",
            "地方自治",
            "地方創生交付金",
            "地方自治体向け",
        ),
        "law_seed_keywords": ("地方自治", "地方創生"),
        "tsutatsu_law_canonical": ("law:hojin-zei-tsutatsu",),
    },
    {
        "slug": "unclassified",
        "code": "T",
        "name_ja": "全業種共通（横断）",
        # T (分類不能) repurposed as "all-industry / cross-cutting" so the page
        # is useful instead of empty. Honest copy in body explains the scope.
        "regex_terms": (
            "中小企業",
            "事業者支援",
            "地域経済",
            "創業",
            "起業",
            "スタートアップ",
            "雇用",
            "人材確保",
            "人材育成",
            "事業承継",
            "M&A",
            "海外展開",
        ),
        "law_seed_keywords": ("中小企業", "創業"),
        "tsutatsu_law_canonical": ("law:hojin-zei-tsutatsu",),
    },
    # +2 cross-cutting verticals to reach 22
    {
        "slug": "gx-decarbon",
        "code": "GX",
        "name_ja": "GX・脱炭素",
        "regex_terms": (
            "GX",
            "脱炭素",
            "カーボンニュートラル",
            "省エネ",
            "省エネルギー",
            "再生可能エネルギー",
            "太陽光",
            "蓄電池",
            "水素",
            "EV",
            "ゼロエミッション",
            "温室効果ガス",
            "森林吸収",
            "J-クレジット",
        ),
        "law_seed_keywords": ("省エネ", "再生可能", "温暖化"),
        "tsutatsu_law_canonical": ("law:hojin-zei-tsutatsu",),
    },
    {
        "slug": "dx-it",
        "code": "DX",
        "name_ja": "DX・IT導入",
        "regex_terms": (
            "DX",
            "IT導入",
            "デジタル化",
            "電子化",
            "クラウド化",
            "AI導入",
            "RPA",
            "業務効率化",
            "デジタル人材",
            "リスキリング",
        ),
        "law_seed_keywords": ("情報通信", "電子計算機"),
        "tsutatsu_law_canonical": ("law:hojin-zei-tsutatsu",),
    },
]

assert len(INDUSTRIES) == 22, f"INDUSTRIES must have 22 entries, got {len(INDUSTRIES)}"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _today_jst_iso() -> str:
    return datetime.now(_JST).date().isoformat()


def _today_jst_ja() -> str:
    return datetime.now(_JST).date().strftime("%Y年%m月%d日")


def _normalize_iso_date(raw: Any) -> str | None:
    if not raw:
        return None
    s = str(raw)
    if "T" in s:
        return s.split("T", 1)[0]
    if re.match(r"^\d{4}-\d{2}-\d{2}", s):
        return s[:10]
    return s


def _last_updated_ja(iso: str | None) -> str:
    if iso and re.match(r"^\d{4}-\d{2}-\d{2}$", iso):
        y, m, d = iso.split("-")
        return f"{int(y)}年{int(m)}月{int(d)}日"
    return _today_jst_ja()


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


def _yen_label(yen: int | None) -> str | None:
    if yen is None:
        return None
    try:
        v = int(yen)
    except (TypeError, ValueError):
        return None
    if v <= 0:
        return None
    if v >= 100_000_000:
        return f"{v / 100_000_000:.1f}億円"
    if v >= 10_000:
        return f"{v // 10_000:,}万円"
    return f"{v:,}円"


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


KIND_JA = {
    "subsidy": "補助金・交付金",
    "grant": "助成金・給付金",
    "loan": "融資 (政策金融)",
    "tax_credit": "税制優遇",
    "incentive": "奨励・インセンティブ制度",
    "certification": "認定制度",
    "training": "研修・人材育成",
}


def _kind_ja(kind: str | None) -> str:
    return KIND_JA.get(kind or "subsidy", "公的支援制度")


# ---------------------------------------------------------------------------
# DB queries (read-only)
# ---------------------------------------------------------------------------


def _ro_connect(path: Path) -> sqlite3.Connection:
    """Open a read-only SQLite connection. Falls back to a regular connection
    on environments where mode=ro URIs are not supported (we still only run
    SELECT queries, so the file is never modified)."""
    try:
        uri = f"file:{path.resolve()}?mode=ro&immutable=1"
        conn = sqlite3.connect(uri, uri=True)
    except sqlite3.OperationalError:
        conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    return conn


# Pull all programs that are S/A tier, indexable, with a real source_url.
# We do prefecture and industry filtering in Python since prefectures are
# stored as JA (e.g. '東京都') and industry filtering is regex-based on
# primary_name (jsic_major column on programs is not backfilled at the
# moment).
PROGRAM_POOL_SQL = """
SELECT
    p.unified_id,
    p.primary_name,
    p.authority_level,
    p.authority_name,
    p.prefecture,
    p.municipality,
    p.program_kind,
    p.official_url,
    p.amount_max_man_yen,
    p.amount_min_man_yen,
    p.subsidy_rate,
    p.tier,
    p.source_url,
    p.source_fetched_at,
    p.updated_at
FROM programs p
WHERE p.excluded = 0
  AND p.tier IN ('S','A')
  AND p.source_url IS NOT NULL AND p.source_url <> ''
  AND (p.authority_name IS NULL OR p.authority_name NOT LIKE '%noukaweb%')
"""


def load_program_pool(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return [dict(r) for r in conn.execute(PROGRAM_POOL_SQL)]


def _is_applicable_to_pref(row: dict[str, Any], pref_ja: str) -> bool:
    """A program is applicable to pref_ja iff it is national/no-pref OR its
    prefecture matches exactly. Other-prefecture rows are excluded."""
    auth = (row.get("authority_level") or "").lower()
    program_pref = row.get("prefecture") or ""
    if not program_pref:
        # No prefecture set — treat as national/all-prefecture.
        return True
    if auth in ("national", "国"):
        return True
    return program_pref == pref_ja


def _industry_match_score(row: dict[str, Any], terms: tuple[str, ...]) -> int:
    name = row.get("primary_name") or ""
    return sum(1 for t in terms if t in name)


def filter_programs(
    pool: list[dict[str, Any]],
    pref_ja: str,
    industry: dict[str, Any],
    top_n: int = 20,
) -> list[dict[str, Any]]:
    out = []
    for row in pool:
        if not _is_applicable_to_pref(row, pref_ja):
            continue
        score = _industry_match_score(row, industry["regex_terms"])
        if score == 0:
            continue
        r = dict(row)
        r["_industry_score"] = score
        out.append(r)
    # Tier S first, then by industry-keyword density, then by max amount, then name.
    out.sort(
        key=lambda r: (
            0 if r.get("tier") == "S" else 1,
            -int(r.get("_industry_score") or 0),
            -float(r.get("amount_max_man_yen") or 0),
            r.get("primary_name") or "",
        )
    )
    return out[:top_n]


LAW_LOOKUP_SQL = """
SELECT DISTINCT l.unified_id, l.law_title, l.law_short_title, l.ministry,
       l.full_text_url, l.source_url
FROM program_law_refs r
JOIN laws l ON l.unified_id = r.law_unified_id
WHERE r.program_unified_id IN ({placeholders})
ORDER BY l.law_title
LIMIT 5
"""


def lookup_laws(conn: sqlite3.Connection, program_ids: list[str]) -> list[dict[str, Any]]:
    if not program_ids:
        return []
    placeholders = ",".join("?" * len(program_ids))
    sql = LAW_LOOKUP_SQL.format(placeholders=placeholders)
    return [dict(r) for r in conn.execute(sql, program_ids)]


LAW_FALLBACK_SQL = """
SELECT unified_id, law_title, law_short_title, ministry, full_text_url, source_url
FROM laws
WHERE law_title LIKE ?
  AND revision_status = 'current'
ORDER BY enforced_date DESC NULLS LAST
LIMIT 5
"""


def lookup_laws_by_keyword(
    conn: sqlite3.Connection, keywords: tuple[str, ...]
) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for kw in keywords:
        cur = conn.execute(LAW_FALLBACK_SQL, (f"%{kw}%",))
        for r in cur:
            row = dict(r)
            uid = row["unified_id"]
            if uid in seen:
                continue
            seen.add(uid)
            out.append(row)
            if len(out) >= 5:
                return out
    return out


TSUTATSU_SQL = """
SELECT code, law_canonical_id, article_number, title, body_excerpt, source_url
FROM nta_tsutatsu_index
WHERE law_canonical_id IN ({placeholders})
ORDER BY law_canonical_id, article_number
LIMIT 3
"""


def lookup_tsutatsu(
    conn: sqlite3.Connection | None, law_canonicals: tuple[str, ...]
) -> list[dict[str, Any]]:
    if not conn or not law_canonicals:
        return []
    placeholders = ",".join("?" * len(law_canonicals))
    sql = TSUTATSU_SQL.format(placeholders=placeholders)
    try:
        return [dict(r) for r in conn.execute(sql, law_canonicals)]
    except sqlite3.OperationalError:
        return []


CASE_STUDIES_SQL = """
SELECT case_id, company_name, case_title, case_summary, industry_jsic,
       industry_name, total_subsidy_received_yen, source_url, publication_date
FROM case_studies
WHERE prefecture = ?
  AND (industry_jsic = ? OR industry_jsic LIKE ?)
ORDER BY publication_date DESC NULLS LAST, case_id
LIMIT 5
"""


def lookup_case_studies(
    conn: sqlite3.Connection, pref_ja: str, jsic_code: str
) -> list[dict[str, Any]]:
    if not pref_ja or not jsic_code or jsic_code in ("GX", "DX"):
        return []
    return [dict(r) for r in conn.execute(CASE_STUDIES_SQL, (pref_ja, jsic_code, f"{jsic_code}%"))]


# ---------------------------------------------------------------------------
# HTML rendering (no jinja2 dependency — single template inlined for speed)
# ---------------------------------------------------------------------------


def _esc(s: str) -> str:
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _truncate(text: str, limit: int) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def page_title(pref_ja: str, industry_ja: str) -> str:
    raw = f"{pref_ja} の {industry_ja} 向け補助金・税制まとめ | jpcite"
    return _truncate(raw, 60)


def meta_description(
    pref_ja: str,
    industry_ja: str,
    program_count: int,
    case_count: int,
    last_iso: str | None,
) -> str:
    last = _last_updated_ja(last_iso) if last_iso else _today_jst_ja()
    parts = [
        f"{pref_ja} の {industry_ja} 事業者向けに、補助金・融資・税制優遇・認定制度を ",
        f"{program_count} 件集約。",
        f"採択事例 {case_count} 件 + 関連法令・国税庁通達もまとめて確認。",
        f"出典は中央省庁・自治体の一次資料に限定。最終更新 {last}。",
    ]
    return _truncate("".join(parts), 160)


def build_json_ld(
    pref_slug: str,
    pref_ja: str,
    industry_slug: str,
    industry_ja: str,
    programs: list[dict[str, Any]],
    domain: str,
    last_iso: str | None,
) -> str:
    item_list = []
    for i, p in enumerate(programs, 1):
        item_list.append(
            {
                "@type": "ListItem",
                "position": i,
                "name": p.get("primary_name") or "",
                "url": p.get("source_url") or p.get("official_url") or "",
            }
        )

    graph: list[dict[str, Any]] = [
        {
            "@type": "Organization",
            "@id": "#jpcite-org",
            "name": "jpcite",
            "url": f"https://{domain}/",
            "contactPoint": {
                "@type": "ContactPoint",
                "email": OPERATOR_EMAIL,
                "contactType": "customer support",
            },
        },
        {
            "@type": "AdministrativeArea",
            "@id": f"#place-{pref_slug}",
            "name": pref_ja,
            "addressCountry": "JP",
        },
        {
            "@type": "BreadcrumbList",
            "itemListElement": [
                {
                    "@type": "ListItem",
                    "position": 1,
                    "name": "ホーム",
                    "item": f"https://{domain}/",
                },
                {
                    "@type": "ListItem",
                    "position": 2,
                    "name": "利用者層",
                    "item": f"https://{domain}/audiences/",
                },
                {
                    "@type": "ListItem",
                    "position": 3,
                    "name": pref_ja,
                    "item": f"https://{domain}/audiences/{pref_slug}/",
                },
                {
                    "@type": "ListItem",
                    "position": 4,
                    "name": industry_ja,
                    "item": f"https://{domain}/audiences/{pref_slug}/{industry_slug}/",
                },
            ],
        },
        {
            "@type": "ItemList",
            "name": f"{pref_ja} {industry_ja} 向け制度一覧",
            "itemListElement": item_list,
        },
    ]

    if last_iso:
        graph.append(
            {
                "@type": "Dataset",
                "name": f"{pref_ja} × {industry_ja} 制度集約",
                "description": (
                    f"{pref_ja} の {industry_ja} 事業者向けに集約した公的制度データセット。"
                ),
                "publisher": {"@id": "#jpcite-org"},
                "dateModified": last_iso,
                "url": f"https://{domain}/audiences/{pref_slug}/{industry_slug}/",
                "license": "https://jpcite.com/license.html",
            }
        )

    obj = {"@context": "https://schema.org", "@graph": graph}
    return json.dumps(obj, ensure_ascii=False, indent=2).replace("</", "<\\/")


def render_page(
    pref_slug: str,
    pref_ja: str,
    industry: dict[str, Any],
    programs: list[dict[str, Any]],
    laws: list[dict[str, Any]],
    tsutatsu: list[dict[str, Any]],
    cases: list[dict[str, Any]],
    domain: str,
) -> str:
    industry_slug = industry["slug"]
    industry_ja = industry["name_ja"]

    last_iso: str | None = None
    for p in programs:
        d = _normalize_iso_date(p.get("source_fetched_at") or p.get("updated_at"))
        if d and (last_iso is None or d > last_iso):
            last_iso = d

    title = page_title(pref_ja, industry_ja)
    desc = meta_description(pref_ja, industry_ja, len(programs), len(cases), last_iso)
    canonical = f"https://{domain}/audiences/{pref_slug}/{industry_slug}/"
    json_ld = build_json_ld(
        pref_slug, pref_ja, industry_slug, industry_ja, programs, domain, last_iso
    )

    # ---- programs section ----
    if programs:
        program_intro = (
            f"<p>{_esc(pref_ja)} の {_esc(industry_ja)} 事業者が利用できる補助金・融資・"
            f"税制優遇・認定制度を <strong>{len(programs)} 件</strong>集約しています "
            f"(tier S / A、出典は一次資料に限定)。"
            "金額・補助率は公募要領の最新版で必ず確認してください。</p>"
        )
        items = []
        for p in programs:
            name = _esc(p.get("primary_name") or "")
            kind = _esc(_kind_ja(p.get("program_kind")))
            amt = _amount_line(p.get("amount_max_man_yen"), p.get("amount_min_man_yen"))
            amt_html = f'<span class="amount">{_esc(amt)}</span>' if amt else ""
            tier = _esc(p.get("tier") or "")
            authority = _esc(p.get("authority_name") or "")
            pref_meta = _esc(p.get("prefecture") or "全国")
            src = p.get("source_url") or p.get("official_url") or ""
            src_dom = _esc(_source_domain(src))
            src_link = (
                f'<a href="{_esc(src)}" rel="external nofollow noopener">{src_dom}</a>'
                if src
                else ""
            )
            items.append(
                f"""<li class="program-card">
   <h3>{name}</h3>
   <p class="program-meta">
     <span class="kind">{kind}</span>
     <span class="tier">tier {tier}</span>
     <span class="pref">{pref_meta}</span>
     {amt_html}
   </p>
   <p class="program-authority">{authority}</p>
   <p class="program-source">出典: {src_link}</p>
 </li>"""
            )
        programs_html = program_intro + '<ul class="program-list">\n' + "\n".join(items) + "\n</ul>"
    else:
        programs_html = (
            f"<p>{_esc(pref_ja)} の {_esc(industry_ja)} 事業者向けに、tier S / A "
            f"の制度は jpcite データベース上では <strong>確認できていません</strong> "
            "(該当する制度なし)。これは制度カバレッジの未到達領域、もしくは {pref} 限定で "
            "該当業種特化の制度が薄いことを示します。"
            f'代わりに <a href="/prefectures/{pref_slug}.html">{_esc(pref_ja)} 全業種の '
            "制度一覧</a> をご覧ください。</p>"
        ).format(pref=pref_ja)

    # ---- laws section ----
    if laws:
        law_items = []
        for l in laws:
            t = _esc(l.get("law_title") or "")
            ministry = _esc(l.get("ministry") or "")
            url = l.get("full_text_url") or l.get("source_url") or ""
            link = (
                f'<a href="{_esc(url)}" rel="external nofollow noopener">e-Gov 全文</a>'
                if url
                else ""
            )
            law_items.append(
                f'<li><strong>{t}</strong> <span class="muted">{ministry}</span> {link}</li>'
            )
        laws_html = (
            "<p>本ページに掲載した制度の根拠法令・関連法令のうち、jpcite が突合できた "
            f"上位 {len(law_items)} 件を以下に示します。条文単位の参照は API / MCP からも取得できます。</p>"
            f'<ul class="law-list">\n{"".join(law_items)}\n</ul>'
        )
    else:
        laws_html = (
            "<p>本ページの制度群について、jpcite データベース上で突合できた根拠法令はありません "
            "(掲載 0 件)。e-Gov 法令検索で業種関連法令を直接ご確認ください。</p>"
        )

    # ---- tsutatsu section ----
    if tsutatsu:
        ts_items = []
        for t in tsutatsu:
            code = _esc(t.get("code") or "")
            ttitle = _esc(t.get("title") or "")
            excerpt = _esc((t.get("body_excerpt") or "")[:140])
            url = t.get("source_url") or ""
            link = (
                f'<a href="{_esc(url)}" rel="external nofollow noopener">国税庁通達</a>'
                if url
                else ""
            )
            ts_items.append(
                f'<li><strong>{code}</strong> {ttitle} {link}<br><span class="muted">{excerpt}…</span></li>'
            )
        tsutatsu_html = (
            "<p>関連する国税庁通達 (法基通 / 所基通 / 消基通 等) のうち、本業種に関連性の高い "
            f"上位 {len(ts_items)} 件を以下に示します。実際の課税判断は税理士にご相談ください。</p>"
            f'<ul class="tsutatsu-list">\n{"".join(ts_items)}\n</ul>'
        )
    else:
        tsutatsu_html = (
            "<p>本業種に直接該当する国税庁通達は jpcite データベース上では確認できていません。"
            '<a href="https://www.nta.go.jp/law/tsutatsu/" rel="external nofollow noopener">'
            "国税庁 法令解釈通達</a> ページで直接ご確認ください。</p>"
        )

    # ---- cases section ----
    if cases:
        case_items = []
        for c in cases:
            title_t = _esc(c.get("case_title") or c.get("company_name") or c.get("case_id") or "")
            ind = _esc(c.get("industry_name") or "")
            amt = _yen_label(c.get("total_subsidy_received_yen"))
            amt_html = f'<span class="amount">受給額: {_esc(amt)}</span>' if amt else ""
            summary = _esc((c.get("case_summary") or "")[:180])
            url = c.get("source_url") or ""
            link = (
                f'<a href="{_esc(url)}" rel="external nofollow noopener">一次資料</a>'
                if url
                else ""
            )
            case_items.append(
                f"""<li class="case-card">
   <strong>{title_t}</strong>
   <span class="case-industry muted">{ind}</span>
   {amt_html}
   <p class="case-summary">{summary}…</p>
   <p class="case-source">{link}</p>
 </li>"""
            )
        cases_html = (
            f"<p>{_esc(pref_ja)} 所在の {_esc(industry_ja)} 事業者の採択事例を "
            f"<strong>{len(case_items)} 件</strong>掲載しています "
            "(jpcite データベース上で確認できたもの)。</p>"
            f'<ul class="case-list">\n{"".join(case_items)}\n</ul>'
        )
    else:
        cases_html = (
            f"<p>{_esc(pref_ja)} 所在の {_esc(industry_ja)} 事業者の採択事例は jpcite "
            "データベース上では確認できていません (該当する事例なし)。"
            "事例公表が薄い領域であるか、業種分類 (JSIC) が一次データ側で別カテゴリに "
            "割り振られている可能性があります。</p>"
        )

    # ---- final HTML ----
    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#ffffff">
<title>{_esc(title)}</title>
<meta name="description" content="{_esc(desc)}">
<meta name="author" content="jpcite">
<meta name="publisher" content="jpcite">
<meta name="robots" content="index, follow, max-image-preview:large">

<meta property="og:title" content="{_esc(title)}">
<meta property="og:description" content="{_esc(desc)}">
<meta property="og:type" content="article">
<meta property="og:url" content="{canonical}">
<meta property="og:image" content="https://{domain}/assets/og.png">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta property="og:locale" content="ja_JP">
<meta property="og:site_name" content="jpcite">

<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{_esc(title)}">
<meta name="twitter:description" content="{_esc(desc)}">
<meta name="twitter:image" content="https://{domain}/assets/og-twitter.png">

<link rel="canonical" href="{canonical}">
<link rel="alternate" hreflang="ja" href="{canonical}">
<link rel="alternate" hreflang="x-default" href="{canonical}">
<link rel="icon" href="/assets/favicon-v2.svg" type="image/svg+xml">
<link rel="stylesheet" href="/styles.css?v=20260428a">

<script type="application/ld+json">
{json_ld}
</script>
</head>
<body>
<a href="#main" class="skip-link">本文へスキップ</a>

<header class="site-header" role="banner">
 <div class="container header-inner">
 <a class="brand" href="/" aria-label="jpcite ホーム">jpcite</a>
 <nav class="site-nav" aria-label="主要ナビゲーション">
 <a href="/about.html">運営について</a>
 <a href="/products.html">プロダクト</a>
 <a href="/docs/">ドキュメント</a>
 <a href="/pricing.html">料金</a>
 <a href="/audiences/" aria-current="page">利用者層</a>
 </nav>
 </div>
</header>

<main id="main" class="audience-page">
 <div class="container">

 <nav class="breadcrumb" aria-label="パンくずリスト">
 <a href="/">ホーム</a> &rsaquo;
 <a href="/audiences/">利用者層</a> &rsaquo;
 <a href="/prefectures/{pref_slug}.html">{_esc(pref_ja)}</a> &rsaquo;
 <span aria-current="page">{_esc(industry_ja)}</span>
 </nav>

 <article>
 <header class="audience-header">
 <h1>{_esc(pref_ja)} の {_esc(industry_ja)} 向け補助金・税制・認定制度 まとめ</h1>
 <p class="byline">
 <span class="updated">出典取得: {_esc(_last_updated_ja(last_iso))}</span>
 <span class="sep">/</span>
 <span class="author">jpcite</span>
 </p>
 </header>

 <section class="summary" aria-labelledby="summary-title">
 <h2 id="summary-title">サマリー</h2>
 <ul>
 <li><strong>都道府県:</strong> {_esc(pref_ja)}</li>
 <li><strong>業種:</strong> {_esc(industry_ja)} (JSIC {_esc(industry["code"])})</li>
 <li><strong>該当制度数:</strong> {len(programs)} 件 (tier S / A)</li>
 <li><strong>関連法令:</strong> {len(laws)} 件</li>
 <li><strong>関連通達:</strong> {len(tsutatsu)} 件</li>
 <li><strong>採択事例:</strong> {len(cases)} 件</li>
 <li><strong>最終更新:</strong> {_esc(_last_updated_ja(last_iso))}</li>
 </ul>
 </section>

 <section aria-labelledby="programs-title">
 <h2 id="programs-title">{_esc(pref_ja)} × {_esc(industry_ja)} 制度一覧</h2>
 {programs_html}
 </section>

 <section aria-labelledby="laws-title">
 <h2 id="laws-title">関連法令</h2>
 {laws_html}
 </section>

 <section aria-labelledby="tsutatsu-title">
 <h2 id="tsutatsu-title">関連通達 (国税庁)</h2>
 {tsutatsu_html}
 </section>

 <section aria-labelledby="cases-title">
 <h2 id="cases-title">{_esc(pref_ja)} の {_esc(industry_ja)} 採択事例</h2>
 {cases_html}
 </section>

 <section aria-labelledby="api-title">
 <h2 id="api-title">API / MCP で取得する</h2>
 <p>本ページに掲載した制度・法令・通達・事例データは、jpcite の REST API および MCP サーバーから機械可読な形式で取得できます。Claude Desktop / Cursor / Cline などの MCP クライアント、または ChatGPT Custom GPT の OpenAPI Actions から呼び出せます。</p>
 <pre class="code-block"><code>curl -H "X-API-Key: YOUR_API_KEY" \\
 "https://api.{domain}/v1/programs?prefecture={_esc(pref_ja)}&amp;industry={_esc(industry["code"])}&amp;limit=20"</code></pre>
 <p class="api-cta-line">無料 3 リクエスト/日。<a href="/pricing.html">料金体系</a> ・ <a href="/dashboard.html">API キー発行</a></p>
 </section>

 <p class="disclaimer">本ページは jpcite が一次情報を集約・構造化したプレビューであり、税理士法 §52 が禁ずる税務代理・税務書類作成・税務相談に該当する助言を構成するものではありません。法的助言・税務助言・申請代行を必要とされる場合は、税理士・社労士・中小企業診断士等の有資格者にご相談ください。制度の最新内容・申請可否・併用可否は所管官公庁・自治体の一次情報で必ず確認してください。集約サイトは出典源から除外しています。</p>
 </article>

 </div>
</main>

<footer class="site-footer" role="contentinfo">
 <div class="container footer-inner">
 <div class="footer-col">
 <p class="footer-brand">jpcite</p>
 <p class="footer-tag">日本の制度 API</p>
 </div>
 <nav class="footer-nav" aria-label="フッター 法務・連絡">
 <a href="/tos.html">利用規約</a>
 <a href="/privacy.html">プライバシー</a>
 <a href="/tokushoho.html">特定商取引法</a>
 <a href="/docs/faq/">ヘルプ</a>
 </nav>
 <p class="footer-entity">運営: {_esc(OPERATOR_NAME)} · <a href="mailto:{_esc(OPERATOR_EMAIL)}">{_esc(OPERATOR_EMAIL)}</a></p>
 <p class="footer-copy">&copy; 2026 {_esc(OPERATOR_NAME)}</p>
 <p class="footer-disclaimer muted">本サイトは税理士法 §52 が規定する税務代理・税務書類作成・税務相談の提供を行いません。個別の税務判断は税理士・社労士・中小企業診断士等の有資格者にご相談ください。</p>
 </div>
</footer>

</body>
</html>
"""


# ---------------------------------------------------------------------------
# Index page (47 × 22 matrix)
# ---------------------------------------------------------------------------

EXISTING_INDEX_PRESERVED_MARKER = "<!-- BEGIN AUTO-GEO-MATRIX -->"


def render_index(domain: str, total_pages: int) -> str:
    """Build the audiences/index.html with the existing 12 audience cards
    PRESERVED at top and a new 47-prefecture × 22-industry matrix below."""
    # Build region grids
    region_blocks = []
    for region_name, slugs in REGIONS:
        pref_links = []
        for slug in slugs:
            ja = next((n for s, n in PREFECTURES if s == slug), slug)
            pref_links.append(f'<a class="pref-chip" href="/audiences/{slug}/">{_esc(ja)}</a>')
        region_blocks.append(
            f'<div class="region-block">'
            f"<h3>{_esc(region_name)}</h3>"
            f'<div class="pref-chips">{"".join(pref_links)}</div>'
            f"</div>"
        )

    # Industry chip list
    industry_chips = []
    for ind in INDUSTRIES:
        industry_chips.append(
            f'<a class="industry-chip" href="#industry-{ind["slug"]}">{_esc(ind["name_ja"])}</a>'
        )

    # The full 47×22 matrix as a table-like grid (sectioned by industry).
    matrix_blocks = []
    for ind in INDUSTRIES:
        rows = []
        for slug, ja in PREFECTURES:
            url = f"/audiences/{slug}/{ind['slug']}/"
            rows.append(f'<a class="cell" href="{url}">{_esc(ja)} × {_esc(ind["name_ja"])}</a>')
        matrix_blocks.append(
            f'<section class="matrix-industry" id="industry-{_esc(ind["slug"])}">'
            f'<h3>{_esc(ind["name_ja"])} <span class="muted">(JSIC {_esc(ind["code"])})</span></h3>'
            f'<div class="matrix-grid">{"".join(rows)}</div>'
            f"</section>"
        )

    # Try to preserve existing content. We assume the existing index has the
    # 12 audience cards. We append our matrix at the end of the <main> block.
    # If existing file does not exist or markers are missing, fall back to a
    # full-page render that still contains the 12 audiences manually.
    existing = ""
    with contextlib.suppress(OSError):
        existing = DEFAULT_INDEX.read_text(encoding="utf-8")

    matrix_html = f"""
{EXISTING_INDEX_PRESERVED_MARKER}
<section class="features audience-matrix" aria-labelledby="matrix-title">
 <div class="container">
 <h2 id="matrix-title" class="section-title">47 都道府県 × 22 業種 マトリクス</h2>
 <p class="muted">{total_pages:,} 通りの (都道府県 × 業種) ページから、ご利用シーンに合うものを選択してください。各ページは jpcite データベースの該当補助金・関連法令・国税庁通達・採択事例を集約しています。</p>

 <details class="industry-jump" open>
 <summary>業種一覧 (22 種) — 名前をタップで該当セクションへ</summary>
 <p class="industry-chip-list">{"".join(industry_chips)}</p>
 </details>

 <details class="pref-jump" open>
 <summary>都道府県別アクセス — 都道府県名をタップで「全業種」ページへ</summary>
 {"".join(region_blocks)}
 </details>

 {"".join(matrix_blocks)}

 </div>
</section>
"""

    if existing and "</main>" in existing:
        # Strip any previous auto-generated section to keep idempotency.
        if EXISTING_INDEX_PRESERVED_MARKER in existing:
            head, _ = existing.split(EXISTING_INDEX_PRESERVED_MARKER, 1)
            # remove anything between marker and </main> in the head's tail
            existing = head.rstrip()
            # head still ends mid-page; we need to restore </main>...</body>
            # Easier: re-derive the original by reading freshly without our
            # injection — but at this point head has lost the closing tags.
            # Strategy: read again, then split at marker + closing block.
            raw = DEFAULT_INDEX.read_text(encoding="utf-8")
            head2, rest = raw.split(EXISTING_INDEX_PRESERVED_MARKER, 1)
            # rest contains our previous block + </section> + everything until
            # </main>. Drop everything up to next </main>:
            try:
                _, tail = rest.split("</main>", 1)
                tail = "</main>" + tail
            except ValueError:
                tail = "\n</main>\n"
            existing = head2.rstrip() + "\n"
            existing = existing + matrix_html + "\n" + tail
            return existing
        # Inject just before </main>
        head, sep, tail = existing.rpartition("</main>")
        return head + matrix_html + sep + tail

    # Fallback: render a self-contained index from scratch (rare path).
    return _render_index_fallback(domain, matrix_html)


def _render_index_fallback(domain: str, matrix_html: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>利用者層 — jpcite</title>
<meta name="description" content="47 都道府県 × 22 業種の制度マトリクス。jpcite が一次資料から集約。">
<link rel="canonical" href="https://{domain}/audiences/">
<link rel="stylesheet" href="/styles.css?v=20260428a">
</head>
<body>
<header class="site-header"><div class="container"><a class="brand" href="/">jpcite</a></div></header>
<main id="main">
 <section class="hero"><div class="container"><h1>利用者層</h1></div></section>
 {matrix_html}
</main>
<footer class="site-footer"><div class="container"><p>&copy; 2026 {_esc(OPERATOR_NAME)}</p></div></footer>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Sitemap
# ---------------------------------------------------------------------------


def write_sitemap(
    entries: list[tuple[str, str]],
    domain: str,
    out_path: Path,
) -> None:
    """`entries` is a list of (loc_url, lastmod_iso). The 12 existing
    audience pages are preserved alongside the 1,034 new ones."""
    existing_legacy = [
        ("/audiences/", "0.85"),
        ("/audiences/tax-advisor.html", "0.8"),
        ("/audiences/admin-scrivener.html", "0.8"),
        ("/audiences/subsidy-consultant.html", "0.8"),
        ("/audiences/smb.html", "0.8"),
        ("/audiences/vc.html", "0.8"),
        ("/audiences/dev.html", "0.8"),
        ("/audiences/construction.html", "0.8"),
        ("/audiences/manufacturing.html", "0.8"),
        ("/audiences/real_estate.html", "0.8"),
        ("/audiences/journalist.html", "0.8"),
        ("/audiences/shinkin.html", "0.8"),
        ("/audiences/shokokai.html", "0.8"),
    ]
    today = _today_jst_iso()
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        "<!--",
        "  Audience landing sitemap shard for jpcite.com.",
        "  Auto-(re)generated by scripts/generate_geo_industry_pages.py.",
        f"  Total URLs: {len(existing_legacy) + len(entries)}",
        "  - 13 legacy audience pages (index + 12 audience landings)",
        f"  - {len(entries)} (prefecture × industry) landings",
        "-->",
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]
    for path, prio in existing_legacy:
        lines += [
            "  <url>",
            f"    <loc>https://{domain}{path}</loc>",
            f"    <lastmod>{today}</lastmod>",
            "    <changefreq>monthly</changefreq>",
            f"    <priority>{prio}</priority>",
            "  </url>",
        ]
    for loc, lastmod in entries:
        lines += [
            "  <url>",
            f"    <loc>{loc}</loc>",
            f"    <lastmod>{lastmod}</lastmod>",
            "    <changefreq>monthly</changefreq>",
            "    <priority>0.6</priority>",
            "  </url>",
        ]
    lines.append("</urlset>")
    _write_if_changed(out_path, "\n".join(lines) + "\n")


# ---------------------------------------------------------------------------
# Idempotent write
# ---------------------------------------------------------------------------


def _write_if_changed(path: Path, content: str) -> bool:
    if path.exists():
        try:
            existing = path.read_text(encoding="utf-8")
        except OSError:
            existing = None
        if existing == content:
            return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return True


# ---------------------------------------------------------------------------
# Top-level orchestration
# ---------------------------------------------------------------------------


def generate(
    db_path: Path,
    autonomath_db_path: Path | None,
    out_dir: Path,
    index_path: Path,
    sitemap_path: Path,
    domain: str,
    samples: int | None,
) -> tuple[int, int, int, int]:
    """Returns (written, skipped, errors, generated_pages)."""
    if not db_path.exists():
        LOG.error("DB not found: %s", db_path)
        raise SystemExit(1)

    out_dir.mkdir(parents=True, exist_ok=True)
    conn = _ro_connect(db_path)

    am_conn: sqlite3.Connection | None = None
    if autonomath_db_path and autonomath_db_path.exists():
        try:
            am_conn = _ro_connect(autonomath_db_path)
            LOG.info("autonomath DB connected: %s", autonomath_db_path)
        except sqlite3.OperationalError as e:
            LOG.warning("autonomath DB open failed (%s) — tsutatsu lookup disabled", e)
            am_conn = None
    else:
        LOG.warning("autonomath DB not found at %s — tsutatsu lookup disabled", autonomath_db_path)

    LOG.info("loading program pool ...")
    pool = load_program_pool(conn)
    LOG.info("program pool size: %d", len(pool))

    pairs: list[tuple[str, str, dict[str, Any]]] = []
    for slug, ja in PREFECTURES:
        for ind in INDUSTRIES:
            pairs.append((slug, ja, ind))

    if samples is not None and samples > 0:
        pairs = pairs[:samples]

    written = 0
    skipped = 0
    errors = 0
    sitemap_entries: list[tuple[str, str]] = []

    for pref_slug, pref_ja, ind in pairs:
        try:
            programs = filter_programs(pool, pref_ja, ind, top_n=20)
            program_ids = [p["unified_id"] for p in programs]
            laws = lookup_laws(conn, program_ids)
            if not laws:
                laws = lookup_laws_by_keyword(conn, ind["law_seed_keywords"])
            tsutatsu = lookup_tsutatsu(am_conn, ind["tsutatsu_law_canonical"])
            cases = lookup_case_studies(conn, pref_ja, ind["code"])

            html = render_page(
                pref_slug=pref_slug,
                pref_ja=pref_ja,
                industry=ind,
                programs=programs,
                laws=laws,
                tsutatsu=tsutatsu,
                cases=cases,
                domain=domain,
            )

            out_path = out_dir / pref_slug / ind["slug"] / "index.html"
            if _write_if_changed(out_path, html):
                written += 1
            else:
                skipped += 1

            last_iso: str | None = None
            for p in programs:
                d = _normalize_iso_date(p.get("source_fetched_at") or p.get("updated_at"))
                if d and (last_iso is None or d > last_iso):
                    last_iso = d
            loc = f"https://{domain}/audiences/{pref_slug}/{ind['slug']}/"
            sitemap_entries.append((loc, last_iso or _today_jst_iso()))

        except Exception as exc:  # noqa: BLE001
            LOG.exception(
                "render failed for pref=%s industry=%s: %s",
                pref_slug,
                ind["slug"],
                exc,
            )
            errors += 1

    # Write index page (preserve existing audience cards + new matrix).
    if samples is None:
        index_html = render_index(domain, total_pages=len(sitemap_entries))
        _write_if_changed(index_path, index_html)
        # Sitemap (rewrite full audiences sitemap with legacy + new entries).
        write_sitemap(sitemap_entries, domain, sitemap_path)

    if am_conn:
        am_conn.close()
    conn.close()

    return written, skipped, errors, len(pairs)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db", default=str(DEFAULT_DB), type=Path)
    p.add_argument("--autonomath-db", default=str(DEFAULT_AUTONOMATH_DB), type=Path)
    p.add_argument("--out", default=str(DEFAULT_OUT), type=Path)
    p.add_argument("--index", default=str(DEFAULT_INDEX), type=Path)
    p.add_argument("--sitemap", default=str(DEFAULT_SITEMAP), type=Path)
    p.add_argument("--domain", default=DEFAULT_DOMAIN)
    p.add_argument(
        "--samples",
        type=int,
        default=None,
        help="if set, generate only the first N (pref, industry) pairs",
    )
    p.add_argument("--verbose", "-v", action="store_true")
    return p.parse_args()


def main() -> int:
    args = _parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    written, skipped, errors, total = generate(
        db_path=args.db,
        autonomath_db_path=args.autonomath_db,
        out_dir=args.out,
        index_path=args.index,
        sitemap_path=args.sitemap,
        domain=args.domain,
        samples=args.samples,
    )
    LOG.info(
        "done. written=%d skipped=%d errors=%d total_pairs=%d",
        written,
        skipped,
        errors,
        total,
    )
    return 0 if errors == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
