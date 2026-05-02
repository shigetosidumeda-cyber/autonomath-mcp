"""Natural-language query -> tool routing for AutonoMath Layer 7.

Pipeline:
    raw_query (JP natural language)
        -> synonym pre-normalization  (e.g. "もの補助" -> "ものづくり補助金",
                                       "令和6年度" -> "令和6年度 2024年度")
        -> intent classification       (reuse match.classify_intent)
        -> tool routing                (intent -> preferred MCP tool + fallbacks)
        -> empty-result explanation    (generated even when confidence=0)

Public API
----------
    route(query: str) -> RouteDecision
    RouteDecision.tool             -- preferred MCP tool name
    RouteDecision.fallbacks        -- ordered fallback tool list
    RouteDecision.intent_id        -- chosen intent id (i01..i10)
    RouteDecision.confidence       -- classifier confidence 0..1
    RouteDecision.normalized_query -- synonym-expanded query
    RouteDecision.explain_empty    -- human-readable explanation when
                                      confidence is below the threshold

Design notes
------------
Fallback order follows the doctrine:
    特化 tool (intent-specific)  ->  reason_answer (generic)
                                 ->  FTS+vec (search_programs_fts)
                                 ->  explain-empty text
When no intent fires strongly, the router does NOT route to an arbitrary
"default" — it routes to reason_answer with explain_empty filled in so
the caller can choose to either try the generic tool or surface the
explanation directly to the user.
"""
from __future__ import annotations

import datetime as _dt
import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from . import match as _match
from synonyms.expand import load_dicts

# ---------------------------------------------------------------------------
# Intent -> MCP tool mapping.
# Names match the public tools exposed from mcp_new (see mcp_new/server.py).
# If a tool does not exist yet, the fallback order still fires.
# ---------------------------------------------------------------------------
INTENT_TOOL_MAP: Dict[str, Dict[str, object]] = {
    "i01_filter_programs_by_profile": {
        "primary": "filter_programs_by_profile",
        "fallbacks": ["search_programs_fts", "reason_answer"],
    },
    "i02_program_deadline_documents": {
        "primary": "get_program_deadline",
        "fallbacks": ["get_program_documents", "reason_answer"],
    },
    "i03_program_successor_revision": {
        "primary": "get_program_revision_chain",
        "fallbacks": ["reason_answer", "search_programs_fts"],
    },
    "i04_tax_measure_sunset": {
        "primary": "get_tax_rule",
        "fallbacks": ["reason_answer", "search_programs_fts"],
    },
    "i05_certification_howto": {
        "primary": "get_certification_howto",
        "fallbacks": ["reason_answer", "search_programs_fts"],
    },
    "i06_compat_incompat_stacking": {
        "primary": "check_program_compatibility",
        "fallbacks": ["reason_answer"],
    },
    "i07_adoption_cases": {
        "primary": "list_adoption_cases",
        "fallbacks": ["search_programs_fts", "reason_answer"],
    },
    "i08_similar_municipality_programs": {
        "primary": "list_peer_muni_programs",
        "fallbacks": ["search_programs_fts", "reason_answer"],
    },
    "i09_succession_closure": {
        "primary": "list_succession_programs",
        "fallbacks": ["get_tax_rule", "reason_answer"],
    },
    "i10_wage_dx_gx_themed": {
        "primary": "list_programs_by_theme",
        "fallbacks": ["search_programs_fts", "reason_answer"],
    },
}

# ---------------------------------------------------------------------------
# Known tool-aliasing mistakes (from Wave 7 customer walk). Callers using a
# legacy name are silently redirected to the canonical one.
# ---------------------------------------------------------------------------
TOOL_ALIASES: Dict[str, str] = {
    "search_tax_incentives": "get_tax_rule",
    "search_tax_rules": "get_tax_rule",
    "tax_incentive_search": "get_tax_rule",
    "find_tax_rule": "get_tax_rule",
    "fts_search": "search_programs_fts",
    "search_fts": "search_programs_fts",
}

# ---------------------------------------------------------------------------
# Heuristic rules that sidestep the keyword-scorer when they fire.
# Ordered: the first hit wins. These handle cases the 10-intent scorer
# cannot disambiguate on pure keyword length.
# ---------------------------------------------------------------------------
HEURISTIC_RULES: List[Tuple[str, re.Pattern, str]] = [
    # --- Limited-eligibility entities ------------------------------------
    (
        "town_council_limited",
        re.compile(r"(町内会|自治会|町会|地縁団体)"),
        "i01_filter_programs_by_profile",
    ),
    (
        "freelancer_tax",
        re.compile(r"フリーランス.*(税|控除|節税|優遇|経費)"),
        "i04_tax_measure_sunset",
    ),
    # --- Tax with date window -------------------------------------------
    (
        "tax_sunset_date",
        re.compile(r"(税制|特例|控除|NISA|インボイス).*(いつまで|適用期限|使える|延長)"),
        "i04_tax_measure_sunset",
    ),
    # --- Deadline inquiries ----------------------------------------------
    (
        "deadline_generic",
        re.compile(
            r"(締切|しめきり|〆切|公募要領|必要書類|申請書類|申請様式|書類|記入例)"
        ),
        "i02_program_deadline_documents",
    ),
    # --- Adoption / acceptance rate --------------------------------------
    (
        "adoption_rate",
        re.compile(r"(採択率|採択件数|採択企業|採択事例|過去.{0,3}(実績|採択))"),
        "i07_adoption_cases",
    ),
    # --- Succession markers (must fire before revision_chain so 「後継者」
    # routes to i09, not i03; 「後継制度」 still lands on i03 via keyword scorer)
    (
        "succession_no_successor",
        re.compile(r"(後継者不在|後継者がいない|後継者.{0,2}いない|後継者.{0,2}M&A|後継者.{0,2}MA|後継者支援)"),
        "i09_succession_closure",
    ),
    # --- Successor / revision --------------------------------------------
    (
        "revision_chain",
        re.compile(r"(後継制度|後継 制度|改正|改正前後|廃止|差分|diff|(R|令和)\d+.{0,4}変更)"),
        "i03_program_successor_revision",
    ),
    # --- Compat / stacking -----------------------------------------------
    (
        "stacking",
        re.compile(r"(併用|併給|重複|stack|上乗せ|国.*県|県.*市|同時適用)"),
        "i06_compat_incompat_stacking",
    ),
    # --- Certification -> unlocked programs ------------------------------
    (
        "cert_unlock",
        re.compile(
            r"(認定|認証).*(取っ|取得|もらっ|持っ).*(補助|使え|該当|対象)"
        ),
        "i05_certification_howto",
    ),
    # --- Succession / closure -------------------------------------------
    (
        "succession",
        re.compile(
            r"(事業承継|後継者|M&A|MA|廃業|引継ぎ|親族内承継|親族承継|従業員承継)"
        ),
        "i09_succession_closure",
    ),
    # --- Peer-muni comparison --------------------------------------------
    (
        "peer_muni",
        re.compile(r"(類似自治体|他自治体|同規模|同じ規模|人口\s*\d+\s*万|中核市)"),
        "i08_similar_municipality_programs",
    ),
    # --- Theme-driven ----------------------------------------------------
    (
        "theme_dx_gx",
        re.compile(r"^(?=.*(DX|GX|賃上げ|省エネ|脱炭素|再エネ))(?=.*(補助|使え|制度|税制))"),
        "i10_wage_dx_gx_themed",
    ),
]

CONFIDENCE_THRESHOLD = 0.15  # below this, we prefix explain_empty output


# ---------------------------------------------------------------------------
# Date normalization (令和N年 <-> 西暦)
# ---------------------------------------------------------------------------
_ERA_BASE = {"令和": 2018, "平成": 1988, "昭和": 1925}
_YEAR_RE = re.compile(r"(令和|平成|昭和)\s*(元|[0-9]+)\s*年")


def _era_to_ce(era: str, year: str) -> Optional[int]:
    base = _ERA_BASE.get(era)
    if base is None:
        return None
    y = 1 if year == "元" else int(year)
    return base + y


def _normalize_era_dates(q: str) -> str:
    """Expand 令和N年 -> '令和N年 20XX年' so downstream matchers win."""

    def repl(m: re.Match) -> str:
        era, yr = m.group(1), m.group(2)
        ce = _era_to_ce(era, yr)
        if ce is None:
            return m.group(0)
        return f"{m.group(0)} {ce}年"

    return _YEAR_RE.sub(repl, q)


# ---------------------------------------------------------------------------
# Relative-time normalization ("今年度" / "来年度" / "年度末")
# ---------------------------------------------------------------------------
def _fiscal_year(today: _dt.date) -> int:
    """Japanese fiscal year (apr-mar): 4/1 onward is the new year."""
    return today.year if today.month >= 4 else today.year - 1


def _normalize_relative_time(q: str, today: Optional[_dt.date] = None) -> str:
    today = today or _dt.date.today()
    fy = _fiscal_year(today)
    out = q
    # 今年度 / 当年度
    if "今年度" in out or "当年度" in out:
        out += f" {fy}年度"
    if "来年度" in out or "次年度" in out or "翌年度" in out:
        out += f" {fy + 1}年度"
    if "昨年度" in out or "前年度" in out:
        out += f" {fy - 1}年度"
    if "年度末" in out:
        out += f" {fy + 1}-03-31"
    if "秋募集" in out:
        out += " 9月 10月 11月"
    if "春募集" in out:
        out += " 4月 5月"
    return out


# ---------------------------------------------------------------------------
# Synonym pre-expansion -> returns a larger string containing all aliases.
# We don't replace the original — we append aliases so the keyword scorer
# still sees both colloquial AND canonical tokens.
# ---------------------------------------------------------------------------
_SYN_CACHE: Optional[object] = None


def _synonym_index():
    global _SYN_CACHE
    if _SYN_CACHE is None:
        _SYN_CACHE = load_dicts()
    return _SYN_CACHE


def normalize_query(query: str, today: Optional[_dt.date] = None) -> str:
    """Synonym-expand + date-normalize a raw query.

    The output string is a superset of the original — no information is lost.
    """
    q = _normalize_era_dates(query)
    q = _normalize_relative_time(q, today=today)

    idx = _synonym_index()
    seen = {w for w in q.split()}
    additions: List[str] = []
    # Substring-scan every group member; if ANY member appears in the query,
    # emit the group's canonical seed (and all synonyms) as append-tokens.
    q_cf = q.casefold()
    for g in idx.groups:
        for syn in g.synonyms:
            if not syn:
                continue
            if syn.casefold() in q_cf:
                for s in g.synonyms:
                    if s and s not in seen:
                        seen.add(s)
                        additions.append(s)
                break
    if additions:
        q = q + " " + " ".join(additions)
    return q


# ---------------------------------------------------------------------------
# Routing data class
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class RouteDecision:
    tool: str
    fallbacks: List[str]
    intent_id: str
    confidence: float
    normalized_query: str
    explain_empty: str
    heuristic_fired: Optional[str] = None


# ---------------------------------------------------------------------------
# Empty-result explanation strings — per-intent boilerplate that tells the
# user *which* Layer-7 knowledge bucket the router reached for.
# ---------------------------------------------------------------------------
EMPTY_EXPLAIN: Dict[str, str] = {
    "i01_filter_programs_by_profile": (
        "業種・地域・規模の組合せから使える制度を列挙するレイヤに問合せたが、"
        "該当する制度が DB に格納されていない。業種 (JSIC) / 都道府県 / 従業員数 の "
        "指定を再確認するか、search_programs_fts で自由語検索を試してほしい。"
    ),
    "i02_program_deadline_documents": (
        "特定制度の申請締切・書類レイヤに問合せたが、制度名が DB で特定できなかった。"
        "制度の正式名称 (例: 『ものづくり・商業・サービス生産性向上促進補助金』) を"
        "指定するか、search_programs_fts で制度探索してから再問合せしてほしい。"
    ),
    "i03_program_successor_revision": (
        "制度の後継・改正履歴レイヤに問合せたが、該当制度の revision_chain が未登録。"
        "制度 ID が分かる場合は get_program_revision_chain に直接 ID を渡してほしい。"
    ),
    "i04_tax_measure_sunset": (
        "税制特例の適用期限レイヤに問合せたが、該当 tax_measure が DB 未登録。"
        "国税庁・中小企業庁の一次資料でサンセット日を要確認。"
    ),
    "i05_certification_howto": (
        "認定の取得方法レイヤに問合せたが、該当 certification が未登録。"
        "主要 14 認定 (経営革新計画・先端設備等導入計画 等) から名称を特定して再問合せ。"
    ),
    "i06_compat_incompat_stacking": (
        "制度の併用可否レイヤに問合せたが、compat_closure に該当ペアが未登録。"
        "公募要領の『他補助金との重複不可』節を直接参照する必要がある。"
    ),
    "i07_adoption_cases": (
        "採択事例レイヤに問合せたが、該当制度・該当回次の採択結果が DB 未登録。"
        "採択者発表 PDF の一次資料 URL が必要。"
    ),
    "i08_similar_municipality_programs": (
        "類似自治体比較レイヤに問合せたが、peer_cluster または該当カテゴリが未整備。"
        "自治体名・人口帯を明示して再問合せしてほしい。"
    ),
    "i09_succession_closure": (
        "事業承継・廃業時に使える制度レイヤに問合せたが、lifecycle_index に該当が無い。"
        "税制 (事業承継税制) + 補助金 (事業承継・引継ぎ補助金) の両面を個別問合せ推奨。"
    ),
    "i10_wage_dx_gx_themed": (
        "テーマ特化レイヤ (賃上げ/DX/GX) に問合せたが、theme_index に該当が無い。"
        "DX/GX/省エネ 等の正式テーマ名か、関連制度 ID を指定して再問合せ。"
    ),
}


TOWN_COUNCIL_EXPLAIN = (
    "町内会・自治会 (地縁団体) は国の補助金対象として限定的。"
    "ほぼ全てが市区町村の地域振興・コミュニティ活性化枠であり、国制度は対象外が多い。"
    "『地方公共団体 + 地域振興 + 市町村』のスコープで search_programs_fts 再実行を推奨。"
)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------
def route(query: str, today: Optional[_dt.date] = None) -> RouteDecision:
    """Route a natural language query to an MCP tool + fallback chain."""
    normalized = normalize_query(query, today=today)

    # 1) Heuristic rules (fire first, high-precision)
    heuristic_fired: Optional[str] = None
    forced_intent: Optional[str] = None
    for name, pat, intent_id in HEURISTIC_RULES:
        if pat.search(query):
            heuristic_fired = name
            forced_intent = intent_id
            break

    # 2) Keyword scorer (run on normalized query so synonyms light it up)
    intent_id, confidence, _scores = _match.classify_intent(normalized)

    # 3) Heuristic override wins over weak keyword signal
    if forced_intent is not None:
        intent_id = forced_intent
        # Confidence: if heuristic fired, treat as strong signal
        confidence = max(confidence, 0.5)

    # 4) Look up tool mapping
    tool_entry = INTENT_TOOL_MAP.get(intent_id)
    if tool_entry is None:
        primary = "reason_answer"
        fallbacks = ["search_programs_fts"]
    else:
        primary = tool_entry["primary"]  # type: ignore[assignment]
        fallbacks = list(tool_entry["fallbacks"])  # type: ignore[arg-type]

    # 5) Empty-result explanation (always populated — the caller decides
    #    whether to surface it depending on whether the tool returned rows)
    explain = EMPTY_EXPLAIN.get(intent_id, "該当する制度レイヤが特定できませんでした。")
    if heuristic_fired == "town_council_limited":
        explain = TOWN_COUNCIL_EXPLAIN

    # 6) Low confidence -> append a meta-note about intent uncertainty
    if confidence < CONFIDENCE_THRESHOLD and heuristic_fired is None:
        explain = (
            "[low-confidence routing] " + explain +
            " 質問文の業種・制度名・時期の指定をより具体的にすると routing 精度が上がる。"
        )

    return RouteDecision(
        tool=str(primary),
        fallbacks=list(fallbacks),
        intent_id=intent_id,
        confidence=round(confidence, 3),
        normalized_query=normalized,
        explain_empty=explain,
        heuristic_fired=heuristic_fired,
    )


# ---------------------------------------------------------------------------
# Utility helpers for callers
# ---------------------------------------------------------------------------
def resolve_tool_alias(name: str) -> str:
    """Redirect deprecated / colloquial tool names to canonical."""
    return TOOL_ALIASES.get(name, name)


__all__ = [
    "RouteDecision",
    "route",
    "normalize_query",
    "resolve_tool_alias",
    "INTENT_TOOL_MAP",
    "TOOL_ALIASES",
    "HEURISTIC_RULES",
]
