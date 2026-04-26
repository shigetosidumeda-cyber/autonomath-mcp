"""bind_i01 — 業種×地域×規模で使える補助金一覧.

Data sources (read-only):
  canonical  autonomath.db  (am_entities + am_entity_facts)
  graph      graph.sqlite   (available_in / applies_to_industry / applies_to_size)

Strategy
--------
The graph DB has the per-program edges already extracted by the graph agent:
  available_in     : program -> region
  applies_to_industry : program -> industry
  applies_to_size  : program -> target_size

We intersect those edge sets to get the applicable program_id list, then
join back to am_entities in the canonical DB for the authority / amount /
source_url row-shape values.

When the graph DB has no hit we fall back to the canonical DB's
``raw.prefecture`` fact — keeps the national-layer + prefecture-layer
queries working even if graph ingest hasn't reached a new topic yet.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Set, Tuple

from .bind_registry import (
    get_canonical_conn,
    get_graph_conn,
    register,
    safe_rows,
)
from .precompute import PrecomputedCache


# ---------------------------------------------------------------------------
# JSIC letter -> industry node name substrings (graph.industry nodes are free-text)
# ---------------------------------------------------------------------------

_JSIC_INDUSTRY_ALIASES = {
    "A": ["農業", "林業", "農林"],
    "B": ["漁業", "水産"],
    "C": ["鉱業"],
    "D": ["建設"],
    "E": ["製造業", "食品製造", "金属", "機械"],
    "F": ["電気", "ガス", "水道"],
    "G": ["情報通信", "IT", "ソフトウェア", "情報サービス"],
    "H": ["運輸", "物流"],
    "I": ["卸売", "小売"],
    "J": ["金融", "保険"],
    "K": ["不動産"],
    "L": ["学術研究", "専門技術"],
    "M": ["宿泊", "飲食"],
    "N": ["生活関連", "娯楽"],
    "O": ["教育", "学習支援"],
    "P": ["医療", "福祉"],
    "Q": ["複合サービス"],
    "R": ["サービス"],
}

_JSIC_LABELS = {
    "A": "農業・林業", "B": "漁業", "C": "鉱業", "D": "建設業", "E": "製造業",
    "F": "電気ガス熱供給水道", "G": "情報通信", "H": "運輸", "I": "卸売・小売",
    "J": "金融・保険", "K": "不動産", "L": "学術・専門技術",
    "M": "宿泊・飲食", "N": "生活関連・娯楽", "O": "教育・学習支援",
    "P": "医療・福祉", "Q": "複合サービス", "R": "サービス業",
}

_SIZE_TO_GRAPH_NODE = {
    "sole": "target_size:sole_proprietor",
    "small": "target_size:micro",
    "sme": "target_size:sme",
    "mid": "target_size:sme",     # mid overlaps sme; graph doesn't distinguish
    "large": "target_size:large",
}


# ---------------------------------------------------------------------------
# Core lookup helpers
# ---------------------------------------------------------------------------

def _programs_available_in_region(pref: Optional[str]) -> Set[str]:
    """Return the set of graph program_id values available in the given
    prefecture. If pref is None we do NOT constrain — meaning 'national layer'
    is included implicitly via the non-restricted path."""
    conn = get_graph_conn()
    if conn is None or not pref:
        return set()
    rows = safe_rows(
        conn,
        "SELECT source_id FROM am_relation "
        "WHERE relation_type='available_in' AND target_id = ?",
        (f"region:{pref}",),
    )
    return {r["source_id"] for r in rows}


def _programs_for_jsic(jsic_letter: Optional[str]) -> Set[str]:
    conn = get_graph_conn()
    if conn is None or not jsic_letter:
        return set()
    aliases = _JSIC_INDUSTRY_ALIASES.get(jsic_letter, [])
    if not aliases:
        return set()
    # Industry nodes are free-text strings; match any of our aliases via LIKE
    out: Set[str] = set()
    for al in aliases:
        rows = safe_rows(
            conn,
            "SELECT DISTINCT r.source_id "
            "FROM am_relation r JOIN am_node n ON n.node_id = r.target_id "
            "WHERE r.relation_type='applies_to_industry' "
            "  AND n.kind='industry' AND n.display_name LIKE ?",
            (f"%{al}%",),
        )
        out.update(r["source_id"] for r in rows)
    return out


def _programs_for_size(size: Optional[str]) -> Set[str]:
    conn = get_graph_conn()
    if conn is None or not size:
        return set()
    node = _SIZE_TO_GRAPH_NODE.get(size)
    if not node:
        return set()
    rows = safe_rows(
        conn,
        "SELECT source_id FROM am_relation "
        "WHERE relation_type='applies_to_size' AND target_id = ?",
        (node,),
    )
    return {r["source_id"] for r in rows}


def _program_ids_all() -> Set[str]:
    conn = get_graph_conn()
    if conn is None:
        return set()
    rows = safe_rows(conn, "SELECT node_id FROM am_node WHERE kind='program'")
    return {r["node_id"] for r in rows}


# ---------------------------------------------------------------------------
# Canonical DB row-shape backfill
# ---------------------------------------------------------------------------

def _normalize_for_match(s: str) -> str:
    """Strip parens and underscores so graph display_name
    ('事業承継支援助成金_東京都') matches canonical primary_name
    ('事業承継支援助成金(東京都)')."""
    if not s:
        return ""
    out = s
    for ch in ("(", ")", "（", "）", "_", " ", "・", ",", "、"):
        out = out.replace(ch, "")
    return out


def _fetch_program_rows(program_display_names: List[str]) -> Dict[str, dict]:
    """For each graph display_name, return the best-matching canonical row.
    Matching strategy: look up candidate primary_names via LIKE on the main
    content words, then pick the row whose normalize() equals the normalized
    display_name."""
    conn = get_canonical_conn()
    if conn is None or not program_display_names:
        return {}
    result: Dict[str, dict] = {}
    for dn in program_display_names:
        stem = dn.split("_")[0]  # e.g. '知財戦略導入助成事業' for '知財戦略導入助成事業_外国特許出願'
        if not stem:
            continue
        rows = safe_rows(
            conn,
            """
            SELECT e.canonical_id, e.primary_name, e.source_url, e.source_topic,
                   e.authority_canonical
            FROM am_entities e
            WHERE e.record_kind='program' AND e.primary_name LIKE ?
            LIMIT 30
            """,
            (f"%{stem}%",),
        )
        dn_norm = _normalize_for_match(dn)
        best = None
        for r in rows:
            pn_norm = _normalize_for_match(r["primary_name"])
            if pn_norm == dn_norm:
                best = dict(r)
                break
        # fallback: if no exact norm match, take the first row
        if best is None and rows:
            best = dict(rows[0])
        if not best:
            continue
        # Attach facts
        fr = safe_rows(
            conn,
            """
            SELECT field_name, field_value_text
            FROM am_entity_facts
            WHERE entity_id = ?
              AND field_name IN (
                'amount_max_yen','raw.subsidy_rate','raw.authority_level',
                'raw.prefecture','authority_raw','raw.application_deadline'
              )
            """,
            (best["canonical_id"],),
        )
        for fk in fr:
            best[fk["field_name"].replace("raw.", "").replace("authority_raw", "authority_raw")] = fk["field_value_text"]
        # Harmonize keys expected by _row_bullet
        best["amount_max_yen"] = best.get("amount_max_yen")
        best["subsidy_rate"] = best.get("subsidy_rate")
        best["authority_level"] = best.get("authority_level")
        best["prefecture"] = best.get("prefecture")
        best["authority_raw"] = best.get("authority_raw")
        best["deadline"] = best.get("application_deadline")
        result[dn] = best
    return result


def _display_name_from_node_id(node_id: str) -> str:
    if node_id.startswith("program:"):
        return node_id[len("program:"):]
    return node_id


# ---------------------------------------------------------------------------
# Row shape formatting
# ---------------------------------------------------------------------------

def _fmt_yen(val: Any) -> str:
    """The skeleton row_shape already appends '万' — we must return a pure
    number here. canonical DB stores amount_max_yen heterogeneously:
    - most 06/20/33 rows: 万-yen units (e.g. 2000 = 2千万, 100000 = 10億)
    - some rows (notably 08_loan + a few muni rows): raw yen
    Heuristic: v >= 1_000_000 likely raw yen (divide by 10_000).
    Values in [10_000, 1_000_000) are ambiguous — we keep as-is (万-yen
    assumption) since most catalog rows use 万-yen."""
    if val in (None, ""):
        return "-"
    try:
        v = float(val)
        if v >= 1_000_000:
            return f"{v / 10000:.0f}"
        return str(int(v))
    except (TypeError, ValueError):
        return str(val)


def _row_bullet(display_name: str, row: Optional[dict]) -> str:
    if row is None:
        return f"- {display_name} (詳細未ingest)"
    auth = row.get("authority_raw") or row.get("authority_canonical") or "-"
    level = row.get("authority_level") or "-"
    amt = _fmt_yen(row.get("amount_max_yen"))
    rate = row.get("subsidy_rate") or "-"
    deadline = row.get("deadline") or "-"
    url = row.get("source_url") or "-"
    return (
        f"- {display_name} ({level} / {auth}) — 上限 ¥{amt}万 / 補助率 {rate} "
        f"/ 締切 {deadline}\n    根拠: {url}"
    )


# ---------------------------------------------------------------------------
# Bind entrypoint
# ---------------------------------------------------------------------------

def bind(slots: Dict[str, Any], cache: PrecomputedCache) -> Dict[str, Any]:
    pref = slots.get("prefecture")
    jsic = slots.get("jsic_industry")
    size = slots.get("business_size")
    notes: List[str] = []
    source_urls: List[str] = []

    region_set = _programs_available_in_region(pref) if pref else None
    industry_set = _programs_for_jsic(jsic) if jsic else None
    size_set = _programs_for_size(size) if size else None

    # Build candidate sets per authority layer. Strict intersect gives 0 rows
    # because graph coverage per-program-per-dimension is still partial
    # (Wave-2 ingest ongoing). We use a *cascading* intersection: we start
    # with the most-selective non-empty filter, then intersect additional
    # filters only when the intersect is still non-empty. Dimensions that
    # empty the candidate set are noted but dropped from the constraint.
    if region_set is None and industry_set is None and size_set is None:
        notes.append("slots empty: no prefecture/industry/size — skipping heavy scan")
        candidates: Set[str] = set()
    else:
        national_set = _programs_available_in_region("全国") if pref else set()
        # Order of preference: region (hardest), then industry, then size.
        filters: List[tuple] = []
        if region_set is not None:
            effective_region = region_set | national_set
            filters.append(("region", effective_region))
        if industry_set is not None:
            filters.append(("industry", industry_set))
        if size_set is not None:
            filters.append(("size", size_set))

        candidates = set()
        dropped: List[str] = []
        for name, s in filters:
            if not candidates:
                candidates = set(s)
                continue
            next_cand = candidates & s
            if next_cand:
                candidates = next_cand
            else:
                dropped.append(name)
                notes.append(
                    f"dimension {name} intersect would empty set — ignoring "
                    f"(coverage gap). kept {len(candidates)} candidates"
                )
        if dropped:
            notes.append(f"cascading intersect dropped: {dropped}")

    # Node id -> display name
    node_ids = sorted(candidates)
    display_names = [_display_name_from_node_id(nid) for nid in node_ids]

    # Join back to canonical DB for authority / amount / url
    program_rows = _fetch_program_rows(display_names)

    # Split into national / prefecture / municipality buckets using
    # raw.authority_level fact (canonical DB). Unknown defaults to 'national'.
    national: List[str] = []
    pref_list: List[str] = []
    muni: List[str] = []
    for dn in display_names:
        row = program_rows.get(dn)
        lvl = (row or {}).get("authority_level")
        bullet = _row_bullet(dn, row)
        if lvl == "prefecture":
            pref_list.append(bullet)
        elif lvl == "municipality":
            muni.append(bullet)
        else:
            national.append(bullet)
        url = (row or {}).get("source_url")
        if url:
            source_urls.append(url)

    # cap at 20 per bucket to keep skeleton readable
    LIMIT = 20
    ctx = {
        "industry_label": _JSIC_LABELS.get(jsic or "", "(JSIC大分類未指定)"),
        "municipality": slots.get("municipality") or "(未指定)",
        "national_count": str(len(national)),
        "prefecture_count": str(len(pref_list)),
        "municipality_count": str(len(muni)),
        "national_bullets": "\n".join(national[:LIMIT]) or "- (該当なし)",
        "prefecture_bullets": "\n".join(pref_list[:LIMIT]) or "- (該当なし)",
        "municipality_bullets": "\n".join(muni[:LIMIT]) or "- (該当なし)",
        "certification_prereqs": "- 経営力向上計画 / 経営革新計画 / 先端設備等導入計画 (制度加点要件で頻出)",
        "urgent_deadlines": "(締切日詳細は i02 で program_id 指定 → 取得)",
        "incompat_roster": "(上乗せ判定は i06 で program_ids 指定 → 取得)",
        "scoring_boost_certs": "- 経営革新計画 (多くの補助金の加点要件)",
        "citation_urls": "\n".join(f"- {u}" for u in sorted(set(source_urls))[:10])
        or "- (canonical source_url 未 ingest)",
    }

    bound_ok = bool(national or pref_list or muni)
    if not bound_ok:
        notes.append(
            f"graph miss — slots={{pref={pref} jsic={jsic} size={size}}} "
            f"region_set={len(region_set or [])} industry_set={len(industry_set or [])} "
            f"size_set={len(size_set or [])}"
        )

    return {
        "bound_ok": bound_ok,
        "ctx": ctx,
        "source_urls": list(dict.fromkeys(source_urls))[:20],
        "notes": notes,
    }


register("i01_filter_programs_by_profile", bind)
