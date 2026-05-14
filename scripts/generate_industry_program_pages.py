#!/usr/bin/env python3
"""Generate industry × program SEO crosspages for jpcite (jpcite.com).

This script complements /programs/{slug} (per-program) and /prefectures/{slug}.html
(per-prefecture) by creating a NEW orthogonal SEO axis: /industries/{jsic}/{slug}/
where {jsic} is the JSIC major-division code (A..T) from autonomath.db
am_industry_jsic, and {slug} is the same hepburn romaji + sha1-6 slug used by
generate_program_pages.py.

Each page asserts that a specific public program is relevant for businesses in
a specific JSIC major industry. The (industry, program) mapping is derived
honestly from concrete evidence: program target_types, authority/source domain,
and program-name keyword regex. Pages are NOT generated when evidence is weak.

Inputs
------
- data/jpintel.db        — programs (S/A/B tier, excluded=0, source_url present)
- autonomath.db          — am_industry_jsic (JSIC major+medium dictionary)

Outputs
-------
- site/industries/{jsic_code}/{slug}/index.html  (per industry × program)
- site/sitemap-industries-detail.xml             (detail-page sitemap shard;
                                                  pair with site/sitemap-industries.xml
                                                  owned by generate_industry_hub_pages.py)
- site/_headers                                  (gain /industries/* cache rule, in-place)

Constraints
-----------
- HONEST data only. If a program has no concrete evidence linking it to a JSIC
  major, do not emit a page for that pair. Skipped pairs are written to
  site/industries/_skipped.tsv for audit.
- Do NOT touch /cross/{prefecture}/{program}/ (geo×program agent territory).
- Do NOT touch /answers/, /qa/ (GEO agent territory).
- Do NOT touch /legal/, /tos/, /privacy/, /tokushoho/ (§52 agent territory).
- Aggregator sources (noukaweb / hojyokin-portal / biz.stayway) are banned per
  CLAUDE.md.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import sqlite3
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

try:
    from jinja2 import Environment, FileSystemLoader, select_autoescape
except ImportError:  # pragma: no cover
    sys.stderr.write("ERROR: jinja2 is required. `uv pip install jinja2`.\n")
    raise

try:
    import pykakasi  # type: ignore
except ImportError:  # pragma: no cover
    sys.stderr.write("ERROR: pykakasi is required. `pip install -e .[site]`.\n")
    raise

LOG = logging.getLogger("generate_industry_program_pages")

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = REPO_ROOT / "data" / "jpintel.db"
DEFAULT_AUTONOMATH_DB = REPO_ROOT / "autonomath.db"
DEFAULT_TEMPLATE_DIR = REPO_ROOT / "site" / "_templates"
DEFAULT_OUT = REPO_ROOT / "site" / "industries"
# NOTE: writes sitemap-industries-detail.xml (NOT sitemap-industries.xml) to
# avoid the clobber race against generate_industry_hub_pages.py which owns
# sitemap-industries.xml (22 hub URLs). sitemap-index.xml references both
# files via scripts/sitemap_gen.py KNOWN_BASENAMES.
DEFAULT_SITEMAP = REPO_ROOT / "site" / "sitemap-industries-detail.xml"
DEFAULT_SITEMAP_INDEX = REPO_ROOT / "site" / "sitemap-index.xml"
DEFAULT_HEADERS = REPO_ROOT / "site" / "_headers"
DEFAULT_DOMAIN = "jpcite.com"

_JST = timezone(timedelta(hours=9))


def _today_jst_iso() -> str:
    return datetime.now(_JST).date().isoformat()


# ---------------------------------------------------------------------------
# Operator + KIND_JA reused from generate_program_pages.py to keep the cross
# axis on-brand. Inlined (rather than imported) so this script can run from a
# vanilla checkout without enabling generate_program_pages' heavyweight
# pykakasi cache before we need it.
# ---------------------------------------------------------------------------

OPERATOR_NAME = "Bookyou株式会社"
OPERATOR_CORPORATE_NUMBER = "T8010001213708"
OPERATOR_REP = "梅田茂利"
OPERATOR_EMAIL = "info@bookyou.net"
OPERATOR_ADDRESS_JP = "東京都文京区小日向2-22-1"

KIND_JA = {
    "subsidy": "補助金・交付金",
    "grant": "助成金・給付金",
    "loan": "融資 (政策金融)",
    "tax_credit": "税制優遇",
    "incentive": "奨励・インセンティブ制度",
    "certification": "認定制度",
    "training": "研修・人材育成",
}


# ---------------------------------------------------------------------------
# JSIC major matchers. The mapping is intentionally evidence-based: a program
# qualifies for JSIC major X iff at least one of:
#   1. target_types_json mentions a token explicitly mapped to X
#   2. source_url host or authority_name maps to X
#   3. program primary_name matches a regex with at least 2 keyword hits
#
# Pairs that fail all three signals are skipped (no page emitted).
#
# Construction principle: prefer false-negatives over false-positives. A
# silent skip is recoverable; a false page about "本制度は◯◯業向けです" when
# it actually isn't is a 詐欺 risk per CLAUDE.md "Data hygiene" + jpcite
# fraud-risk feedback. Keep the regexes narrow.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class JsicMatcher:
    code: str
    name_ja: str
    target_type_tokens: tuple[str, ...] = ()
    domain_keywords: tuple[str, ...] = ()
    authority_keywords: tuple[str, ...] = ()
    name_regex: re.Pattern[str] | None = None  # any-match (1 hit required)
    name_strong_regex: re.Pattern[str] | None = None  # strong-match (1 hit also OK)


def _re(*tokens: str) -> re.Pattern[str]:
    return re.compile("|".join(re.escape(t) for t in tokens))


# Keep these regexes JA-only — most program names are JA. ASCII tokens are
# dropped because "IT" matches every other program name accidentally; we
# only honor ASCII tokens via the name_strong_regex (anchored on word
# boundaries in JA punctuation).

JSIC_MATCHERS: dict[str, JsicMatcher] = {
    "A": JsicMatcher(
        code="A",
        name_ja="農業、林業",
        target_type_tokens=(
            "farmer",
            "certified_farmer",
            "new_farmer",
            "certified_new_farmer",
            "agri_corporation",
            "agri_corp",
            "ag_corp",
            "employment_agri",
            "aspiring_farmer",
            "prospective_farmer",
            "individual_farmer",
            "individual_certified_farmer",
            "young_farmer",
            "認定農業者",
            "認定新規就農者",
            "農業法人",
            "個人農業者",
            "若手農業者",
            "集落営農",
            "女性農業者",
            "新規就農者",
            "forestry",
            "林業",
        ),
        domain_keywords=("maff.go.jp",),
        authority_keywords=("農林水産省", "農政部", "農林部", "林野庁", "農業会議"),
        name_regex=_re(
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
    ),
    "B": JsicMatcher(
        code="B",
        name_ja="漁業",
        target_type_tokens=("fishery", "漁業者", "漁業"),
        domain_keywords=("jfa.maff.go.jp",),
        authority_keywords=("水産庁",),
        name_regex=_re(
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
    ),
    "C": JsicMatcher(
        code="C",
        name_ja="鉱業、採石業、砂利採取業",
        target_type_tokens=(),
        authority_keywords=("鉱山保安",),
        name_regex=_re("鉱業", "採石", "砂利", "採掘", "鉱山"),
    ),
    "D": JsicMatcher(
        code="D",
        name_ja="建設業",
        target_type_tokens=("建設業", "建設", "construction"),
        domain_keywords=(),
        authority_keywords=("国土交通省", "建設業課", "建築指導課", "住宅課"),
        name_regex=_re(
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
    ),
    "E": JsicMatcher(
        code="E",
        name_ja="製造業",
        target_type_tokens=(),
        domain_keywords=(),
        authority_keywords=("経済産業省", "中小企業庁", "産業技術総合研究所"),
        name_regex=_re(
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
    ),
    "F": JsicMatcher(
        code="F",
        name_ja="電気・ガス・熱供給・水道業",
        target_type_tokens=(),
        domain_keywords=(),
        authority_keywords=("資源エネルギー庁",),
        name_regex=_re(
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
    ),
    "G": JsicMatcher(
        code="G",
        name_ja="情報通信業",
        target_type_tokens=(),
        domain_keywords=("ipa.go.jp", "soumu.go.jp"),
        authority_keywords=("総務省", "情報処理推進機構"),
        name_regex=_re(
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
    ),
    "H": JsicMatcher(
        code="H",
        name_ja="運輸業、郵便業",
        target_type_tokens=(),
        domain_keywords=("mlit.go.jp",),
        authority_keywords=("国土交通省", "運輸局", "陸運局"),
        name_regex=_re(
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
    ),
    "I": JsicMatcher(
        code="I",
        name_ja="卸売業、小売業",
        target_type_tokens=(),
        authority_keywords=(),
        name_regex=_re(
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
    ),
    "J": JsicMatcher(
        code="J",
        name_ja="金融業、保険業",
        target_type_tokens=(),
        domain_keywords=("fsa.go.jp",),
        authority_keywords=("金融庁",),
        name_regex=_re(
            "金融業",
            "保険業",
            "信用金庫",
            "信用組合",
            "地域金融機関",
            "ファイナンス",
            "金融サービス",
        ),
    ),
    "K": JsicMatcher(
        code="K",
        name_ja="不動産業、物品賃貸業",
        target_type_tokens=(),
        authority_keywords=(),
        name_regex=_re(
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
    ),
    "L": JsicMatcher(
        code="L",
        name_ja="学術研究、専門・技術サービス業",
        target_type_tokens=("researcher", "大学・研究機関"),
        domain_keywords=("jsps.go.jp", "jst.go.jp", "amed.go.jp"),
        authority_keywords=(
            "科学技術振興機構",
            "学術振興会",
            "医療研究開発機構",
            "産業技術総合研究所",
            "新エネルギー・産業技術総合開発機構",
        ),
        name_regex=_re(
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
    ),
    "M": JsicMatcher(
        code="M",
        name_ja="宿泊業、飲食サービス業",
        target_type_tokens=(),
        authority_keywords=("観光庁",),
        name_regex=_re(
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
    ),
    "N": JsicMatcher(
        code="N",
        name_ja="生活関連サービス業、娯楽業",
        target_type_tokens=(),
        authority_keywords=(),
        name_regex=_re(
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
    ),
    "O": JsicMatcher(
        code="O",
        name_ja="教育、学習支援業",
        target_type_tokens=("school", "学校法人"),
        domain_keywords=("mext.go.jp",),
        authority_keywords=("文部科学省", "教育委員会"),
        name_regex=_re(
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
    ),
    "P": JsicMatcher(
        code="P",
        name_ja="医療、福祉",
        target_type_tokens=(),
        domain_keywords=("mhlw.go.jp", "amed.go.jp"),
        authority_keywords=(
            "厚生労働省",
            "保健福祉部",
            "医療政策課",
            "介護保険",
            "障害福祉",
        ),
        name_regex=_re(
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
    ),
    "Q": JsicMatcher(
        code="Q",
        name_ja="複合サービス事業",
        target_type_tokens=(),
        authority_keywords=(),
        name_regex=_re(
            "郵便局",
            "農業協同組合",
            "JA",
            "漁業協同組合",
            "森林組合",
            "事業協同組合",
            "中小企業組合",
            "協同組合",
        ),
    ),
    "R": JsicMatcher(
        code="R",
        name_ja="サービス業（他に分類されないもの）",
        target_type_tokens=(),
        authority_keywords=(),
        name_regex=_re(
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
    ),
    "S": JsicMatcher(
        code="S",
        name_ja="公務（他に分類されるものを除く）",
        target_type_tokens=("municipality", "地方自治体"),
        authority_keywords=(),
        name_regex=_re(
            "地方公共団体",
            "市町村",
            "公務員",
            "自治体",
            "地方自治",
            "地方創生交付金",
            "地方自治体向け",
        ),
    ),
    # T (分類不能) intentionally omitted — no honest signal exists for it.
}


# ---------------------------------------------------------------------------
# Slug — same algorithm as generate_program_pages.py (keeps deep links stable)
# ---------------------------------------------------------------------------

_KKS = pykakasi.kakasi()


def slugify(name: str, unified_id: str) -> str:
    try:
        parts = _KKS.convert(name or "")
        romaji = " ".join(p.get("hepburn", "") for p in parts)
    except Exception:  # pragma: no cover
        romaji = ""
    romaji = romaji.lower()
    ascii_only = re.sub(r"[^a-z0-9]+", "-", romaji).strip("-")
    if len(ascii_only) > 60:
        truncated = ascii_only[:60]
        if "-" in truncated:
            truncated = truncated.rsplit("-", 1)[0]
        ascii_only = truncated
    if not ascii_only:
        ascii_only = "program"
    suffix = hashlib.sha1(unified_id.encode("utf-8")).hexdigest()[:6]
    return f"{ascii_only}-{suffix}"


# ---------------------------------------------------------------------------
# Helpers (also reused from generate_program_pages.py — narrow inline copies)
# ---------------------------------------------------------------------------


def _parse_json_list(raw: Any) -> list[str]:
    if not raw:
        return []
    if isinstance(raw, list):
        return [str(x) for x in raw if x]
    try:
        val = json.loads(raw)
    except (TypeError, ValueError):
        return []
    if isinstance(val, list):
        return [str(x) for x in val if x]
    return []


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


def _subsidy_rate_line(rate: Any) -> str | None:
    if rate is None:
        return None
    try:
        rate_f = float(rate)
    except (TypeError, ValueError):
        return None
    if rate_f <= 0:
        return None
    return f"{int(round(rate_f * 100))}% (目安)"


_TARGET_TYPES_JA = {
    "corporation": "法人",
    "sole_proprietor": "個人事業主",
    "smb": "中小企業",
    "sme": "中小企業",
    "startup": "スタートアップ",
    "npo": "NPO法人",
    "individual": "個人",
    "municipality": "地方自治体",
    "school": "学校法人",
    "farmer": "農業者",
    "certified_farmer": "認定農業者",
    "new_farmer": "新規就農者",
    "certified_new_farmer": "認定新規就農者",
    "agri_corporation": "農業法人",
    "agri_corp": "農業法人",
    "ag_corp": "農業法人",
    "employment_agri": "雇用就農者",
    "researcher": "研究者",
    "nonprofit": "非営利団体",
    "fishery": "漁業者",
    "forestry": "林業者",
    "corp": "法人",
    "group": "団体",
    "any": "全般",
    "aspiring_farmer": "就農希望者",
    "prospective_farmer": "就農希望者",
    "individual_farmer": "個人農業者",
    "individual_certified_farmer": "個人認定農業者",
}


def _is_japanese(text: str) -> bool:
    for ch in text:
        code = ord(ch)
        if (
            0x3040 <= code <= 0x309F
            or 0x30A0 <= code <= 0x30FF
            or 0x4E00 <= code <= 0x9FFF
            or 0x3400 <= code <= 0x4DBF
            or 0xFF00 <= code <= 0xFFEF
        ):
            return True
    return False


def _target_type_label(t: str) -> str:
    if t in _TARGET_TYPES_JA:
        return _TARGET_TYPES_JA[t]
    if _is_japanese(t):
        return t
    return t


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


_AUTHORITY_FROM_DOMAIN = [
    ("chusho.meti.go.jp", "中小企業庁"),
    ("maff.go.jp", "農林水産省"),
    ("meti.go.jp", "経済産業省"),
    ("mhlw.go.jp", "厚生労働省"),
    ("mlit.go.jp", "国土交通省"),
    ("env.go.jp", "環境省"),
    ("mext.go.jp", "文部科学省"),
    ("mof.go.jp", "財務省"),
    ("soumu.go.jp", "総務省"),
    ("jfc.go.jp", "日本政策金融公庫"),
    ("smrj.go.jp", "中小機構"),
    ("nta.go.jp", "国税庁"),
    ("ipa.go.jp", "情報処理推進機構"),
    ("jsps.go.jp", "日本学術振興会"),
    ("jst.go.jp", "科学技術振興機構"),
    ("amed.go.jp", "日本医療研究開発機構"),
    ("nedo.go.jp", "新エネルギー・産業技術総合開発機構"),
]


def _resolve_agency(row: dict[str, Any]) -> str | None:
    auth = row.get("authority_name")
    if auth:
        s = str(auth).strip()
        if s and s not in {"所管官公庁", "公開元", "不明"} and "noukaweb" not in s:
            return s
    domain = _source_domain(row.get("source_url") or "")
    for k, name in _AUTHORITY_FROM_DOMAIN:
        if domain.endswith(k):
            return name
    if domain.endswith(".lg.jp"):
        return "地方自治体"
    return None


def _truncate(text: str, limit: int) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    head = text[: limit - 1]
    window_start = max(0, len(head) - 30)
    boundary = -1
    for ch in ("。", ".", "、", " "):
        idx = head.rfind(ch, window_start)
        if idx > boundary:
            boundary = idx
    if boundary >= window_start:
        return head[: boundary + 1].rstrip() + "…"
    return head + "…"


# ---------------------------------------------------------------------------
# Mapping (the heart of the script — honest, evidence-based)
# ---------------------------------------------------------------------------


@dataclass
class MatchEvidence:
    target_match: list[str]  # tokens from target_types_json that hit
    domain_match: str | None  # domain that matched (empty if none)
    authority_match: list[str]  # authority_name substrings that hit
    name_hits: list[str]  # primary_name regex hits

    def is_strong_enough(self) -> bool:
        """Strict gate: at least one signal must fire AND the signal must be
        either explicit (target/domain/authority) or strong-keyword.

        Rules:
        - Any target_type token match → strong
        - Any domain match → strong
        - Any authority_keyword match → strong
        - Name keyword: requires >= 1 hit (regexes are tight; single match OK)
        """
        if self.target_match:
            return True
        if self.domain_match:
            return True
        if self.authority_match:
            return True
        return bool(self.name_hits)


def _match_one(
    matcher: JsicMatcher, row: dict[str, Any], target_tokens: list[str]
) -> MatchEvidence:
    name = row.get("primary_name") or ""
    domain = _source_domain(row.get("source_url") or "")
    authority = row.get("authority_name") or ""

    target_match = [t for t in target_tokens if t in matcher.target_type_tokens]

    domain_match: str | None = None
    for d in matcher.domain_keywords:
        if d in domain:
            domain_match = d
            break

    authority_match = [a for a in matcher.authority_keywords if a and a in authority]

    name_hits: list[str] = []
    if matcher.name_regex is not None:
        for m in matcher.name_regex.finditer(name):
            name_hits.append(m.group(0))

    return MatchEvidence(
        target_match=target_match,
        domain_match=domain_match,
        authority_match=authority_match,
        name_hits=name_hits,
    )


def _match_score(ev: MatchEvidence) -> float:
    """Score in [0, 1]. Used only to rank programs WITHIN a JSIC for "other
    programs" sidebar; not for emit-or-skip (which uses is_strong_enough)."""
    s = 0.0
    if ev.target_match:
        s += 0.5
    if ev.domain_match:
        s += 0.3
    if ev.authority_match:
        s += 0.2
    s += min(0.4, 0.1 * len(ev.name_hits))
    return min(1.0, s)


# ---------------------------------------------------------------------------
# Query
# ---------------------------------------------------------------------------

INDEXABLE_SQL = """
SELECT
    unified_id, primary_name, aliases_json, authority_level, authority_name,
    prefecture, municipality, program_kind, official_url,
    amount_max_man_yen, amount_min_man_yen, subsidy_rate, tier,
    target_types_json, funding_purpose_json,
    source_url, source_fetched_at, updated_at
FROM programs
WHERE excluded = 0
  AND tier IN ('S','A','B')
  AND source_url IS NOT NULL
  AND source_url <> ''
  AND (authority_name IS NULL OR authority_name NOT LIKE '%noukaweb%')
ORDER BY
    CASE tier WHEN 'S' THEN 0 WHEN 'A' THEN 1 WHEN 'B' THEN 2 ELSE 3 END,
    unified_id
"""


# ---------------------------------------------------------------------------
# JSON-LD
# ---------------------------------------------------------------------------

ORG_NODE_ID = "https://jpcite.com/#publisher"


def _org_node(domain: str) -> dict[str, Any]:
    # Single canonical Organization @id — matches generate_program_pages.py and
    # generate_geo_citation_pages.py so the @graph cross-references resolve to
    # the same entity across all SEO axes.
    return {
        "@type": "Organization",
        "@id": ORG_NODE_ID,
        "name": "jpcite",
        "alternateName": ["jpcite", "Bookyou株式会社"],
        "url": f"https://{domain}/",
        "logo": {
            "@type": "ImageObject",
            "url": f"https://{domain}/assets/logo-v2.svg",
            "width": 600,
            "height": 60,
        },
        # TODO populate when LinkedIn / GitHub / X / Crunchbase live.
        "sameAs": [],
    }


def _breadcrumb_node(
    jsic_code: str, jsic_name_ja: str, primary_name: str, slug: str, domain: str
) -> dict[str, Any]:
    return {
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "ホーム", "item": f"https://{domain}/"},
            {
                "@type": "ListItem",
                "position": 2,
                "name": "業種別",
                "item": f"https://{domain}/industries/",
            },
            {
                "@type": "ListItem",
                "position": 3,
                "name": jsic_name_ja,
                "item": f"https://{domain}/industries/{jsic_code}/",
            },
            {
                "@type": "ListItem",
                "position": 4,
                "name": primary_name,
                "item": f"https://{domain}/industries/{jsic_code}/{slug}/",
            },
        ],
    }


def _article_node(
    row: dict[str, Any],
    jsic_code: str,
    jsic_name_ja: str,
    slug: str,
    domain: str,
    program_slug_full: str,
    target_types: list[str],
) -> dict[str, Any]:
    """Schema.org `Article` with about=GovernmentService, audience=Audience(JSIC).

    Per spec: "GovernmentService + Industry (use schema.org/IndustrialPark or
    freebase.com/business/industry as Type approximation, or use Article with
    about/keywords)". We pick `Article` because it is the most semantically
    correct for an industry-x-program crossreference page (the page is *about*
    the program *for* an industry, not *is* the program). The `about` node
    points back to the canonical /programs/{slug} GovernmentService.
    """
    audience_text = f"{jsic_name_ja} (JSIC {jsic_code}) 事業者"

    # Inline GovernmentService (about=) — propagate serviceType + areaServed
    # from row context so the about-graph carries the same machine-readable
    # facets the canonical /programs/{slug} GovernmentService node carries.
    about_node: dict[str, Any] = {
        "@type": "GovernmentService",
        "name": row["primary_name"],
        "identifier": row["unified_id"],
        "url": f"https://{domain}/programs/{program_slug_full}",
        "serviceType": row.get("program_kind") or "subsidy",
    }
    agency = _resolve_agency(row)
    if agency:
        about_node["provider"] = {"@type": "GovernmentOrganization", "name": agency}

    auth_level = (row.get("authority_level") or "").lower()
    if auth_level in ("national", "country", "central", "中央"):
        about_node["areaServed"] = {"@type": "Country", "name": "JP"}
    elif row.get("prefecture"):
        about_node["areaServed"] = {"@type": "AdministrativeArea", "name": row["prefecture"]}
    else:
        about_node["areaServed"] = {"@type": "Country", "name": "JP"}

    # Article required-properties for Google rich-results:
    # datePublished / dateModified / image / author
    # - datePublished: source_fetched_at (when jpcite first observed the source)
    # - dateModified: build timestamp (current generator run, JST date)
    # - image: site default OG card (1200x630 PNG)
    # - author: same publisher Org (single-author crossref)
    fetched_iso = _normalize_iso_date(row.get("source_fetched_at"))
    today_iso = datetime.now(_JST).date().isoformat()

    return {
        "@type": "Article",
        "@id": f"#article-{jsic_code}-{slug}",
        "name": f"{jsic_name_ja}における{row['primary_name']}の活用方法",
        "headline": f"{jsic_name_ja}における{row['primary_name']}の活用方法",
        "inLanguage": "ja",
        "url": f"https://{domain}/industries/{jsic_code}/{slug}/",
        "publisher": {"@id": ORG_NODE_ID},
        "author": {"@id": ORG_NODE_ID},
        "datePublished": fetched_iso or today_iso,
        "dateModified": today_iso,
        "image": {
            "@type": "ImageObject",
            "url": f"https://{domain}/assets/og.png",
            "width": 1200,
            "height": 630,
        },
        "audience": {"@type": "Audience", "audienceType": audience_text},
        "about": about_node,
        "keywords": [jsic_name_ja, row["primary_name"], f"JSIC {jsic_code}"],
    }


def _faq_node(
    row: dict[str, Any],
    jsic_name_ja: str,
    qa_pairs: list[dict[str, str]],
    slug: str,
    jsic_code: str,
) -> dict[str, Any]:
    return {
        "@type": "FAQPage",
        "@id": f"#faq-{jsic_code}-{slug}",
        "inLanguage": "ja",
        "mainEntity": [
            {
                "@type": "Question",
                "name": qa["q"],
                "acceptedAnswer": {"@type": "Answer", "text": qa["a"]},
            }
            for qa in qa_pairs
        ],
    }


def build_json_ld(
    row: dict[str, Any],
    jsic_code: str,
    jsic_name_ja: str,
    slug: str,
    domain: str,
    program_slug_full: str,
    target_types: list[str],
    qa_pairs: list[dict[str, str]],
) -> dict[str, Any]:
    return {
        "@context": "https://schema.org",
        "@graph": [
            _org_node(domain),
            _breadcrumb_node(jsic_code, jsic_name_ja, row["primary_name"], slug, domain),
            _article_node(
                row, jsic_code, jsic_name_ja, slug, domain, program_slug_full, target_types
            ),
            _faq_node(row, jsic_name_ja, qa_pairs, slug, jsic_code),
        ],
    }


# ---------------------------------------------------------------------------
# Body content (Q&A + paragraphs)
# ---------------------------------------------------------------------------


def _normalize_iso_date(raw: Any) -> str | None:
    if not raw:
        return None
    if isinstance(raw, str):
        if "T" in raw:
            return raw.split("T", 1)[0]
        if re.match(r"^\d{4}-\d{2}-\d{2}", raw):
            return raw[:10]
    return None


def _last_updated_ja(row: dict[str, Any]) -> str:
    iso = _normalize_iso_date(row.get("updated_at") or row.get("source_fetched_at"))
    if iso and re.match(r"^\d{4}-\d{2}-\d{2}$", iso):
        y, m, d = iso.split("-")
        return f"{int(y)}年{int(m)}月{int(d)}日"
    return datetime.now(_JST).strftime("%Y年%m月%d日")


def _tldr_paragraph(
    row: dict[str, Any],
    jsic_code: str,
    jsic_name_ja: str,
    target_types: list[str],
) -> str:
    name = row["primary_name"]
    kind = KIND_JA.get(row.get("program_kind") or "subsidy", "公的支援制度")
    agency = _resolve_agency(row)
    amt = _amount_line(row.get("amount_max_man_yen"), row.get("amount_min_man_yen"))
    fetched = _normalize_iso_date(row.get("source_fetched_at")) or "公募要領を参照"

    parts = [
        f"業種コード {jsic_code} ({jsic_name_ja}) における {name} の機械可読データを jpcite が集約しました。"
    ]
    amt_phrase = f"最大支援金額は{amt}です。" if amt else "支援金額は公募要領に記載されています。"
    if agency:
        parts.append(f"本制度は {agency} が運営する{kind}で、{amt_phrase}")
    else:
        parts.append(f"本制度は公的機関が運営する{kind}で、{amt_phrase}")
    parts.append(f"jpcite による直近の出典取得は {fetched} です。")
    parts.append(
        f"本ページは {jsic_name_ja} 事業者が本制度を活用する観点でのクロスリファレンスであり、申請可否は公募要領で必ずご確認ください。"
    )
    return "".join(parts)


def _industry_match_paragraph(
    row: dict[str, Any],
    jsic_name_ja: str,
    evidence: MatchEvidence,
    target_types: list[str],
) -> str:
    """Compose an honest paragraph describing WHY this program is relevant to
    this industry, based ONLY on concrete evidence we hold. No speculation."""
    name = row["primary_name"]
    bits: list[str] = []
    if evidence.target_match:
        ja = "、".join(_target_type_label(t) for t in evidence.target_match[:3])
        bits.append(
            f"本制度の対象者には「{ja}」が含まれており、{jsic_name_ja}事業者が直接の対象に含まれます。"
        )
    if evidence.domain_match:
        bits.append(
            f"出典ドメイン ({evidence.domain_match}) は {jsic_name_ja} を所管する省庁・機関のものです。"
        )
    if evidence.authority_match:
        a = "、".join(evidence.authority_match[:2])
        bits.append(
            f"運営主体に「{a}」が含まれ、{jsic_name_ja}向けの政策パッケージの一部であることが裏付けられます。"
        )
    if evidence.name_hits:
        ja_hits = "、".join(sorted(set(evidence.name_hits))[:3])
        bits.append(
            f"制度名に「{ja_hits}」というキーワードが含まれており、{jsic_name_ja}に直接関連します。"
        )
    if not bits:
        # is_strong_enough() should have filtered this out, but defensive.
        bits.append(f"{name} は {jsic_name_ja} 向けに活用される可能性のある制度です。")
    bits.append(
        f"なお、本制度の最終的な適用可否は、業種だけでなく事業計画・経費区分・地理要件・他制度との併用可否など複数の要素で決まります。{jsic_name_ja}事業者であっても、公募要領の個別要件を満たさない場合は対象外となる点にご注意ください。"
    )
    return "".join(bits)


def _qa_pairs(
    row: dict[str, Any],
    jsic_code: str,
    jsic_name_ja: str,
    target_types: list[str],
) -> list[dict[str, str]]:
    """5 Q&A pairs for LLM citation per spec."""
    name = row["primary_name"]
    agency = _resolve_agency(row) or "公募要領記載の申請窓口"
    fetched = _normalize_iso_date(row.get("source_fetched_at")) or "最新を参照"
    rate = _subsidy_rate_line(row.get("subsidy_rate"))
    target_text = (
        "、".join(_target_type_label(t) for t in target_types)
        if target_types
        else "公募要領の規定に従う"
    )
    rate_clause = f"補助率は{rate}が目安です。" if rate else ""

    return [
        {
            "q": f"{jsic_name_ja}事業者の採択率はどのくらいですか？",
            "a": (
                f"{name} の業種別採択率は公募要領または採択結果公表ページで確認できます。"
                f"jpcite では業種コード {jsic_code} ({jsic_name_ja}) の採択事例を集約していますが、"
                "全体採択率を業種別に按分する公式データは多くの制度で公開されておらず、"
                "推計値の提示は避けています。直近の採択率は jpcite API "
                f'`search_acceptance_stats_am(program_id="{row["unified_id"]}")` '
                "または出典欄の公式ページでご確認ください。"
            ),
        },
        {
            "q": f"{jsic_name_ja}事業者が申請する際に必要な書類は何ですか？",
            "a": (
                f"{name} の標準的な必要書類は、公募要領（応募申請書）・事業計画書・直近2-3期の決算書・"
                "見積書（補助対象経費分）・登記事項証明書（法人）または開業届の写し（個人事業主）・"
                f"納税証明書です。{jsic_name_ja}固有の書類として、業界団体の会員証・営業許可証・"
                "業種別の認定証等が追加で必要になることがあります。最新の必要書類リストは"
                f"出典欄 ({_source_domain(row.get('source_url') or '')}) の公式ページでご確認ください。"
            ),
        },
        {
            "q": "公募回数は年に何回ですか？",
            "a": (
                f"jpcite が直近に出典を取得した日付は {fetched} です。"
                f"{name} の年間公募回数は制度・年度により異なります（複数次公募、随時受付、"
                "通年受付などのパターンがあります）。締切と公募回数は出典欄の公式ページで"
                "現在の状況を必ずご確認ください。"
            ),
        },
        {
            "q": f"{jsic_name_ja}に特有の要件はありますか？",
            "a": (
                f"本制度の対象者は「{target_text}」と公募要領に記載されています。"
                f"{jsic_name_ja}事業者の場合、業種コード {jsic_code} に該当することが要件となる"
                "ことがありますが、個別の事業計画・経費区分・地理要件・他制度との併用可否は"
                "業種要件と独立に審査されます。業種以外の要件は公募要領の対象要件・"
                "対象経費・対象事業の各セクションでご確認ください。"
            ),
        },
        {
            "q": "申請の典型的な失敗パターンは何ですか？",
            "a": (
                "jpcite が把握している典型的な失敗パターンは、(1) 公募要領記載の対象経費"
                "区分に該当しない経費を計上、(2) 同一経費に対する他制度との併用受給、"
                "(3) 事業計画書の数値根拠が不十分、(4) 提出期限直前の駆け込み申請による書類不備、"
                "(5) 申請窓口の取り違え（中央 vs 都道府県 vs 市町村） — の5パターンです。"
                f"申請先の確認は {agency} までお問い合わせください。"
                f"{rate_clause}"
                "申請可否の最終判断は必ず有資格者（税理士・社労士・中小企業診断士・行政書士）"
                "の助言を得てください。"
            ),
        },
    ]


def _meta_description(
    row: dict[str, Any],
    jsic_code: str,
    jsic_name_ja: str,
) -> str:
    name = row["primary_name"]
    kind = KIND_JA.get(row.get("program_kind") or "subsidy", "公的支援制度")
    agency = _resolve_agency(row)
    amt = (
        _amount_line(row.get("amount_max_man_yen"), row.get("amount_min_man_yen")) or "公募要領参照"
    )
    fetched = _normalize_iso_date(row.get("source_fetched_at")) or "最新を参照"
    domain = _source_domain(row.get("source_url"))

    parts = [
        f"{jsic_name_ja} (JSIC {jsic_code}) 事業者が {name} を活用する方法。",
    ]
    if agency:
        parts.append(f"提供: {agency}.")
    parts.append(f"上限: {amt}.")
    parts.append(f"区分: {kind}.")
    parts.append(f"出典取得: {fetched}.")
    if domain:
        parts.append(f"一次資料: {domain}.")
    text = " ".join(parts)
    return _truncate(text, 160)


def _page_title(row: dict[str, Any], jsic_name_ja: str) -> str:
    name = row["primary_name"]
    raw = f"{jsic_name_ja}における{name}の活用方法 | 採択事例 | jpcite"
    return _truncate(raw, 70)


# ---------------------------------------------------------------------------
# Sibling JSIC selection
# ---------------------------------------------------------------------------


# Each major has an empirically meaningful "sibling" set — codes whose
# audiences plausibly overlap. We surface 3-5 of these where the SAME program
# also passes is_strong_enough for them. This drives crawl depth without
# fabricating relations.
JSIC_SIBLINGS: dict[str, tuple[str, ...]] = {
    "A": ("B", "Q", "E"),  # 農林 → 漁 / 農協 / 食品製造
    "B": ("A", "Q", "E"),
    "C": ("D", "E"),
    "D": ("E", "K", "L"),  # 建設 → 製造 / 不動産 / 建築士
    "E": ("D", "G", "I", "L"),
    "F": ("E", "G"),
    "G": ("L", "E", "R"),
    "H": ("D", "I"),
    "I": ("M", "N", "G", "E"),
    "J": ("R", "K"),
    "K": ("D", "J", "R"),
    "L": ("E", "G", "P", "O"),
    "M": ("I", "N", "P"),
    "N": ("M", "I", "P"),
    "O": ("L", "P"),
    "P": ("L", "O", "N"),
    "Q": ("A", "B", "I"),
    "R": ("L", "G", "I", "N"),
    "S": ("L", "R"),
}


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------


def _build_env(template_dir: Path) -> Environment:
    return Environment(
        loader=FileSystemLoader(str(template_dir)),
        autoescape=select_autoescape(enabled_extensions=("html", "xml"), default=True),
        trim_blocks=False,
        lstrip_blocks=False,
    )


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


def _load_jsic_dictionary(autonomath_db: Path) -> dict[str, str]:
    """Return {code: name_ja} from am_industry_jsic (major + medium)."""
    if not autonomath_db.exists():
        LOG.warning(
            "autonomath.db not found at %s; falling back to embedded JSIC dict", autonomath_db
        )
        return {code: m.name_ja for code, m in JSIC_MATCHERS.items()}
    out: dict[str, str] = {}
    try:
        con = sqlite3.connect(str(autonomath_db))
        con.row_factory = sqlite3.Row
        for r in con.execute("SELECT jsic_code, jsic_name_ja FROM am_industry_jsic"):
            out[r["jsic_code"]] = r["jsic_name_ja"]
        con.close()
    except Exception as exc:  # noqa: BLE001
        LOG.warning("failed to read am_industry_jsic: %s — falling back", exc)
        return {code: m.name_ja for code, m in JSIC_MATCHERS.items()}
    return out


@dataclass
class IndexableProgram:
    row: dict[str, Any]
    target_types: list[str]
    program_slug: str  # full slug (with sha1-6) used in /programs/ and /industries/


def _build_program_index(conn: sqlite3.Connection) -> list[IndexableProgram]:
    progs: list[IndexableProgram] = []
    for r in conn.execute(INDEXABLE_SQL):
        d = dict(r)
        tts = _parse_json_list(d.get("target_types_json"))
        slug = slugify(d.get("primary_name") or "", d["unified_id"])
        progs.append(IndexableProgram(row=d, target_types=tts, program_slug=slug))
    return progs


def _build_matches(
    progs: list[IndexableProgram],
) -> dict[str, list[tuple[IndexableProgram, MatchEvidence, float]]]:
    """Return {jsic_code: [(prog, evidence, score)] sorted desc by (tier asc, score desc)}."""
    by_jsic: dict[str, list[tuple[IndexableProgram, MatchEvidence, float]]] = defaultdict(list)
    tier_order = {"S": 0, "A": 1, "B": 2}
    for code, matcher in JSIC_MATCHERS.items():
        for ip in progs:
            ev = _match_one(matcher, ip.row, ip.target_types)
            if not ev.is_strong_enough():
                continue
            score = _match_score(ev)
            by_jsic[code].append((ip, ev, score))
        # Sort: tier asc (S first), score desc, unified_id asc
        by_jsic[code].sort(
            key=lambda x: (
                tier_order.get((x[0].row.get("tier") or "B").upper(), 9),
                -x[2],
                x[0].row.get("unified_id") or "",
            )
        )
    return by_jsic


def _kind_ja(row: dict[str, Any]) -> str:
    return KIND_JA.get(row.get("program_kind") or "subsidy", "公的支援制度")


def _select_other_programs(
    by_jsic: dict[str, list[tuple[IndexableProgram, MatchEvidence, float]]],
    jsic_code: str,
    current_unified_id: str,
    cap: int = 5,
) -> list[dict[str, Any]]:
    items = by_jsic.get(jsic_code, [])
    out: list[dict[str, Any]] = []
    seen_prefix: set[str] = set()
    for ip, _ev, _score in items:
        uid = ip.row.get("unified_id")
        if uid == current_unified_id:
            continue
        # de-cluster identical 6-char prefixes (wave variants)
        prefix = (ip.row.get("primary_name") or "")[:6]
        if prefix in seen_prefix:
            continue
        seen_prefix.add(prefix)
        out.append(
            {
                "slug": ip.program_slug,
                "name": ip.row["primary_name"],
                "kind_ja": _kind_ja(ip.row),
            }
        )
        if len(out) >= cap:
            break
    return out


def _select_sibling_jsic(
    by_jsic: dict[str, list[tuple[IndexableProgram, MatchEvidence, float]]],
    jsic_dict: dict[str, str],
    current_jsic: str,
    program_unified_id: str,
    cap: int = 5,
) -> list[dict[str, str]]:
    """Surface other JSIC majors where the SAME program also passes the
    is_strong_enough gate. Order: pre-defined sibling list first, then any
    other JSIC that also has the program. Limit to `cap`.
    """
    sib_codes_ordered = list(JSIC_SIBLINGS.get(current_jsic, ()))
    # Append any extra JSIC that also matches this program (for crawl depth).
    extras: list[str] = []
    for code, items in by_jsic.items():
        if code == current_jsic or code in sib_codes_ordered:
            continue
        for ip, _ev, _score in items:
            if ip.row.get("unified_id") == program_unified_id:
                extras.append(code)
                break
    out: list[dict[str, str]] = []
    for code in sib_codes_ordered + extras:
        if code not in by_jsic:
            continue
        # Only include if THIS jsic also hosts the same program (so the link
        # actually resolves to a generated page).
        if not any(ip.row.get("unified_id") == program_unified_id for ip, _ev, _ in by_jsic[code]):
            continue
        if code not in jsic_dict:
            continue
        out.append({"code": code, "name_ja": jsic_dict[code]})
        if len(out) >= cap:
            break
    return out


def render_page(
    env: Environment,
    domain: str,
    ip: IndexableProgram,
    evidence: MatchEvidence,
    jsic_code: str,
    jsic_name_ja: str,
    sibling_jsic: list[dict[str, str]],
    other_programs: list[dict[str, Any]],
) -> str:
    row = ip.row
    target_types = ip.target_types
    program_slug_full = ip.program_slug
    # The /industries/{jsic}/{slug}/ path uses the same slug as /programs/.
    cross_slug = ip.program_slug

    qa_pairs = _qa_pairs(row, jsic_code, jsic_name_ja, target_types)
    json_ld = build_json_ld(
        row,
        jsic_code,
        jsic_name_ja,
        cross_slug,
        domain,
        program_slug_full,
        target_types,
        qa_pairs,
    )

    target_types_ja = [_target_type_label(t) for t in target_types]
    tmpl = env.get_template("industry_program.html")
    return tmpl.render(
        DOMAIN=domain,
        unified_id=row["unified_id"],
        program_slug=cross_slug,
        program_slug_full=program_slug_full,
        primary_name=row["primary_name"],
        page_title=_page_title(row, jsic_name_ja),
        meta_description=_meta_description(row, jsic_code, jsic_name_ja),
        jsic_code=jsic_code,
        jsic_name_ja=jsic_name_ja,
        tier=row.get("tier"),
        prefecture=row.get("prefecture"),
        program_kind=row.get("program_kind") or "subsidy",
        kind_ja=_kind_ja(row),
        amount_line=_amount_line(row.get("amount_max_man_yen"), row.get("amount_min_man_yen")),
        subsidy_rate_line=_subsidy_rate_line(row.get("subsidy_rate")),
        target_types_ja=target_types_ja,
        resolved_agency=_resolve_agency(row),
        source_url=row.get("source_url") or "",
        source_domain=_source_domain(row.get("source_url")),
        source_org=_resolve_agency(row),
        fetched_at=_normalize_iso_date(row.get("source_fetched_at")),
        fetched_at_ja=_last_updated_ja(row),
        tldr_paragraph=_tldr_paragraph(row, jsic_code, jsic_name_ja, target_types),
        industry_match_paragraph=_industry_match_paragraph(
            row, jsic_name_ja, evidence, target_types
        ),
        qa_pairs=qa_pairs,
        sibling_jsic=sibling_jsic,
        other_programs=other_programs,
        json_ld_pretty=json.dumps(json_ld, ensure_ascii=False, indent=2).replace("</", "<\\/"),
    )


# ---------------------------------------------------------------------------
# Sitemap + _headers update
# ---------------------------------------------------------------------------


_TIER_CHANGEFREQ = {"S": "weekly", "A": "weekly", "B": "monthly"}
_TIER_PRIORITY = {"S": "0.7", "A": "0.6", "B": "0.5"}


def write_sitemap(entries: list[tuple[str, str, str, str]], path: Path, domain: str) -> bool:
    """entries: [(jsic, slug, lastmod_iso, tier)]. Returns True if written."""
    if not entries:
        return False
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        "<!-- Industry program sitemap shard for jpcite.com. -->",
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]
    for jsic, slug, lastmod, tier in entries:
        cf = _TIER_CHANGEFREQ.get(tier, "monthly")
        pr = _TIER_PRIORITY.get(tier, "0.5")
        lines.append("  <url>")
        lines.append(f"    <loc>https://{domain}/industries/{jsic}/{slug}/</loc>")
        lines.append(f"    <lastmod>{lastmod}</lastmod>")
        lines.append(f"    <changefreq>{cf}</changefreq>")
        lines.append(f"    <priority>{pr}</priority>")
        lines.append("  </url>")
    lines.append("</urlset>")
    return _write_if_changed(path, "\n".join(lines) + "\n")


def update_sitemap_index(index_path: Path, domain: str) -> bool:
    """Append <sitemap> entry for sitemap-industries-detail.xml if missing.

    Note: sitemap_gen.py KNOWN_BASENAMES is the canonical place to register
    discoverable sitemap fragments; this function is a defensive fallback
    when the master index is hand-tracked instead of regenerated.
    """
    if not index_path.exists():
        return False
    text = index_path.read_text(encoding="utf-8")
    if "/sitemap-industries-detail.xml" in text:
        return False
    entry = (
        "  <sitemap>\n"
        f"    <loc>https://{domain}/sitemap-industries-detail.xml</loc>\n"
        f"    <lastmod>{_today_jst_iso()}</lastmod>\n"
        "  </sitemap>\n"
    )
    new = text.replace("</sitemapindex>", entry + "</sitemapindex>")
    if new == text:
        return False
    index_path.write_text(new, encoding="utf-8")
    return True


_HEADERS_RULE = """
# Industry × program crosspages — same SEO fan-out as /programs/*, mostly
# read by crawlers, cache aggressively.
/industries/*
  Cache-Control: public, max-age=86400, stale-while-revalidate=604800
"""


def update_headers(headers_path: Path) -> bool:
    """Append /industries/* cache rule if missing."""
    if not headers_path.exists():
        return False
    text = headers_path.read_text(encoding="utf-8")
    if "/industries/*" in text:
        return False
    new = text.rstrip() + "\n" + _HEADERS_RULE
    headers_path.write_text(new, encoding="utf-8")
    return True


# ---------------------------------------------------------------------------
# Top-level
# ---------------------------------------------------------------------------


def generate(
    db_path: Path,
    autonomath_db: Path,
    out_dir: Path,
    template_dir: Path,
    domain: str,
    sitemap_path: Path | None,
    sitemap_index_path: Path | None,
    headers_path: Path | None,
    cap_per_jsic: int,
    sample_only: bool = False,
    sample_count: int = 5,
) -> tuple[int, int, int, list[tuple[str, str, str]]]:
    """Returns (written, skipped, errors, sample_paths). `sample_paths` is the
    list of (jsic, unified_id, file_path) for sample-mode calls.
    """
    if not db_path.exists():
        LOG.error("jpintel.db not found: %s", db_path)
        raise SystemExit(1)
    if not (template_dir / "industry_program.html").exists():
        LOG.error("template not found at %s", template_dir / "industry_program.html")
        raise SystemExit(1)

    out_dir.mkdir(parents=True, exist_ok=True)
    env = _build_env(template_dir)

    jsic_dict = _load_jsic_dictionary(autonomath_db)

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    progs = _build_program_index(conn)
    LOG.info("indexable programs: %d", len(progs))

    by_jsic = _build_matches(progs)
    for code in sorted(by_jsic.keys()):
        LOG.info(
            "  JSIC %s (%s): %d candidate programs",
            code,
            jsic_dict.get(code, "?"),
            len(by_jsic[code]),
        )

    sitemap_entries: list[tuple[str, str, str, str]] = []
    skipped: list[tuple[str, str, str]] = []  # (jsic, unified_id, reason) for audit
    written = 0
    errors = 0
    sample_paths: list[tuple[str, str, str]] = []

    # Track which (jsic, unified_id) pairs we emit so skipped audit reflects
    # the cap_per_jsic truncation as well.
    emitted_pairs: set[tuple[str, str]] = set()

    for code, items in by_jsic.items():
        jsic_name_ja = jsic_dict.get(code, JSIC_MATCHERS[code].name_ja)
        # Cap to top-N per JSIC (per spec: ~250 to land near 5,000 pages, but
        # honest data usually < 250 for most majors).
        capped = items[:cap_per_jsic]
        for ip, ev, _score in capped:
            row = ip.row
            uid = row["unified_id"]
            try:
                # Pre-compute sibling + other lists
                sibling_jsic = _select_sibling_jsic(by_jsic, jsic_dict, code, uid, cap=5)
                other_programs = _select_other_programs(by_jsic, code, uid, cap=5)
                html = render_page(
                    env,
                    domain,
                    ip,
                    ev,
                    code,
                    jsic_name_ja,
                    sibling_jsic,
                    other_programs,
                )
                page_path = out_dir / code / ip.program_slug / "index.html"
                if sample_only and len(sample_paths) >= sample_count:
                    continue
                _write_if_changed(page_path, html)
                written += 1
                emitted_pairs.add((code, uid))
                lastmod = (
                    _normalize_iso_date(row.get("source_fetched_at"))
                    or _normalize_iso_date(row.get("updated_at"))
                    or _today_jst_iso()
                )
                tier = (row.get("tier") or "B").upper()
                sitemap_entries.append((code, ip.program_slug, lastmod, tier))
                if sample_only:
                    sample_paths.append((code, uid, str(page_path)))
                    if len(sample_paths) >= sample_count:
                        break
            except Exception as exc:  # noqa: BLE001
                LOG.exception("render failed for %s × %s: %s", code, uid, exc)
                errors += 1
        if sample_only and len(sample_paths) >= sample_count:
            break

    # Skipped audit: pairs that PASSED is_strong_enough but were truncated by
    # the cap, plus a coarse per-jsic count of programs that FAILED the gate.
    for code, items in by_jsic.items():
        for ip, _ev, _score in items[cap_per_jsic:]:
            uid = ip.row.get("unified_id") or ""
            skipped.append((code, uid, "cap_per_jsic"))
    # Programs that failed the gate entirely (NOT in by_jsic): counted but not
    # individually listed (would explode the file). We log a summary.
    total_progs = len(progs)
    total_emit_pairs = len(emitted_pairs) + len(skipped)
    weak_pairs = (total_progs * len(JSIC_MATCHERS)) - total_emit_pairs
    LOG.info("weak (jsic, program) pairs filtered out by gate: %d", weak_pairs)

    if not sample_only:
        if sitemap_path is not None:
            wrote_sm = write_sitemap(sitemap_entries, sitemap_path, domain)
            LOG.info(
                "sitemap written: %s (%d entries)",
                sitemap_path if wrote_sm else "unchanged",
                len(sitemap_entries),
            )
        if sitemap_index_path is not None:
            wrote_idx = update_sitemap_index(sitemap_index_path, domain)
            LOG.info("sitemap-index updated: %s", "yes" if wrote_idx else "already present")
        if headers_path is not None:
            wrote_h = update_headers(headers_path)
            LOG.info("_headers updated: %s", "yes" if wrote_h else "already present")
        # Persist skipped audit
        skipped_path = out_dir / "_skipped.tsv"
        body = (
            "jsic\tunified_id\treason\n" + "\n".join(f"{j}\t{u}\t{r}" for j, u, r in skipped) + "\n"
        )
        _write_if_changed(skipped_path, body)
        LOG.info("skipped audit: %d pairs → %s", len(skipped), skipped_path)

    return written, len(skipped), errors, sample_paths


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db", default=str(DEFAULT_DB), type=Path)
    p.add_argument("--autonomath-db", default=str(DEFAULT_AUTONOMATH_DB), type=Path)
    p.add_argument("--out", default=str(DEFAULT_OUT), type=Path)
    p.add_argument("--template-dir", default=str(DEFAULT_TEMPLATE_DIR), type=Path)
    p.add_argument("--domain", default=DEFAULT_DOMAIN)
    p.add_argument("--sitemap", default=str(DEFAULT_SITEMAP), type=Path)
    p.add_argument("--sitemap-index", default=str(DEFAULT_SITEMAP_INDEX), type=Path)
    p.add_argument("--headers", default=str(DEFAULT_HEADERS), type=Path)
    p.add_argument("--cap-per-jsic", type=int, default=250)
    p.add_argument(
        "--sample",
        action="store_true",
        help="emit only --sample-count pages, skip sitemap/_headers",
    )
    p.add_argument("--sample-count", type=int, default=5)
    p.add_argument("--verbose", "-v", action="store_true")
    return p.parse_args()


def main() -> int:
    args = _parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    written, skipped, errors, sample_paths = generate(
        db_path=args.db,
        autonomath_db=args.autonomath_db,
        out_dir=args.out,
        template_dir=args.template_dir,
        domain=args.domain,
        sitemap_path=args.sitemap,
        sitemap_index_path=args.sitemap_index,
        headers_path=args.headers,
        cap_per_jsic=args.cap_per_jsic,
        sample_only=args.sample,
        sample_count=args.sample_count,
    )
    LOG.info(
        "done: written=%d skipped=%d errors=%d (sample=%d)",
        written,
        skipped,
        errors,
        len(sample_paths),
    )
    if sample_paths:
        for j, u, p in sample_paths:
            LOG.info("  sample: %s × %s → %s", j, u, p)
    return 0 if errors == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
