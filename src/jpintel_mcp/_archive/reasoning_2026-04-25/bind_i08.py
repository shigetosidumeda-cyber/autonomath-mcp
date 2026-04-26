"""bind_i08 — 類似自治体の制度.

Data sources (read-only):
  canonical  autonomath.db
             - 47_local_ordinance_benefits   (32 rows, ordinance-based benefits)
             - 06_prefecture_programs        (200 rows)
             - 33_prefecture_programs_part2  (190 rows)
             - 20_designated_city_programs   (205 rows)
  proactive  proactive/peer_muni_pairs.sqlite   -- Wave-6 exact-pop peer cache
             (built from am_region.population_exact; ±20% band, 37,696 pairs)

Strategy
--------
Wave-6 switch: population_band was catastrophically imprecise. We now use
population_exact (住基台帳 R7.1.1) via a precomputed peer pair cache:

  1. If source_municipality is specified, we look up up to 20 peer
     municipalities from peer_muni_pairs.sqlite (|pop_peer - pop_target|
     <= 20% or same tier fallback for very large cities). This is the
     authoritative peer roster.
  2. We then fetch programs for those peer municipalities from the 4
     ingested topics, filtered by program_category.
  3. muni_population_band is kept ONLY as a legacy slot-alias for queries
     that lack a source_municipality (e.g. '中核市 ふるさと納税 制度比較').
     In that path we still walk the cluster/category path (unchanged).
  4. program_category filters via raw.category (20_designated_city) or free-text
     match on primary_name/source_excerpt (47_local_ordinance).
  5. pref_cluster → prefecture list via static map.

Output: comparison table (muni | program | amount | eligibility | url)
        + similar_design bullets + template_ordinance URLs when available.
"""
from __future__ import annotations

import json
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from .bind_i01 import _fmt_yen
from .bind_registry import INFRA_ROOT, get_canonical_conn, register, safe_rows
from .precompute import PrecomputedCache


# ---------------------------------------------------------------------------
# Wave-6 peer pair cache (population_exact ±20%).
# ---------------------------------------------------------------------------

PEER_PAIRS_DB = INFRA_ROOT / "proactive" / "peer_muni_pairs.sqlite"
_peer_conn: Optional[sqlite3.Connection] = None


def _get_peer_conn() -> Optional[sqlite3.Connection]:
    """Open peer_muni_pairs.sqlite read-only. None if file missing."""
    global _peer_conn
    if _peer_conn is not None:
        return _peer_conn
    if not PEER_PAIRS_DB.exists():
        return None
    try:
        _peer_conn = sqlite3.connect(f"file:{PEER_PAIRS_DB}?mode=ro", uri=True)
        _peer_conn.row_factory = sqlite3.Row
    except sqlite3.DatabaseError:
        _peer_conn = None
    return _peer_conn


def _peers_by_muni_name(source_muni: str, limit: int = 20) -> List[dict]:
    """Return ranked peer rows for a source municipality name.

    Looks up by target_name (exact match). If multiple rows have the same
    name (e.g. 川崎町 appears in 宮城/福岡), we pick the largest-pop one —
    matches the intuition that the user meant the 政令市 / main city.

    Returns list of dicts: peer_code, peer_name, peer_pop, match_mode,
    pop_delta_pct, rank, pref_code, same_pref.
    """
    conn = _get_peer_conn()
    if conn is None:
        return []
    # Disambiguate same-name targets by keeping the row group with the
    # largest target_pop (e.g. 川崎市 over 川崎町).
    rows = conn.execute(
        """
        SELECT target_code, target_pop, peer_code, peer_name, peer_pop,
               pref_code, same_pref, pop_delta_pct, match_mode, rank
          FROM peer_pairs
         WHERE target_name = ?
         ORDER BY target_pop DESC, rank ASC
         LIMIT 200
        """,
        (source_muni,),
    ).fetchall()
    if not rows:
        return []
    # Keep only rows whose target_code matches the row group with the
    # largest target_pop (first target_code we see after the ORDER BY).
    top_target = rows[0]["target_code"]
    out = [dict(r) for r in rows if r["target_code"] == top_target]
    return out[:limit]


def _exact_pop_by_muni_name(source_muni: str) -> Optional[Tuple[str, int]]:
    """Return (region_code, population_exact) for the largest region_code
    matching this name. None if not found. Uses the peer cache."""
    conn = _get_peer_conn()
    if conn is None:
        return None
    row = conn.execute(
        """
        SELECT DISTINCT target_code, target_pop
          FROM peer_pairs
         WHERE target_name = ?
         ORDER BY target_pop DESC
         LIMIT 1
        """,
        (source_muni,),
    ).fetchone()
    if not row:
        return None
    return (row["target_code"], int(row["target_pop"]))


# ---------------------------------------------------------------------------
# Pref cluster -> prefecture set
# ---------------------------------------------------------------------------

PREF_CLUSTERS: Dict[str, List[str]] = {
    "北海道東北": ["北海道", "青森県", "岩手県", "宮城県", "秋田県", "山形県", "福島県"],
    "関東": ["茨城県", "栃木県", "群馬県", "埼玉県", "千葉県", "東京都", "神奈川県"],
    "北陸甲信越": ["新潟県", "富山県", "石川県", "福井県", "山梨県", "長野県"],
    "東海": ["岐阜県", "静岡県", "愛知県", "三重県"],
    "近畿": ["滋賀県", "京都府", "大阪府", "兵庫県", "奈良県", "和歌山県"],
    "中国四国": ["鳥取県", "島根県", "岡山県", "広島県", "山口県",
               "徳島県", "香川県", "愛媛県", "高知県"],
    "九州沖縄": ["福岡県", "佐賀県", "長崎県", "熊本県", "大分県",
               "宮崎県", "鹿児島県", "沖縄県"],
}

# ---------------------------------------------------------------------------
# Category -> raw.category values (20_designated_city uses enum'd values) +
# free-text keywords (47_local_ordinance uses free-form descriptions)
# ---------------------------------------------------------------------------

CATEGORY_ENUM_MAP: Dict[str, List[str]] = {
    "空家対策": ["空家", "空き家"],
    "結婚新生活": ["結婚", "新生活"],
    "子育て": ["子育て", "子ども"],
    "移住定住": ["移住", "定住"],
    "省エネ": ["省エネ", "省エネルギー", "脱炭素", "カーボン", "再エネ", "グリーン", "太陽光"],
    "地域振興": ["地域振興", "commercial_district"],
    "商店街": ["商店街", "commercial_district"],
    "農業": ["農業"],
    "水道PFI": ["PFI", "水道"],
    "消防": ["消防"],
    "ふるさと納税": ["ふるさと納税"],
}

DESIGNATED_CITY_CATEGORY_TAG: Dict[str, Set[str]] = {
    "商店街": {"commercial_district"},
    "地域振興": {"commercial_district", "tourism"},
    "省エネ": {"environment"},
    "移住定住": {"startup"},
    # no dedicated enum for 農業 in DC; skip DC path to avoid false hits
}


def _prefs_for_cluster(cluster: Optional[str]) -> Set[str]:
    if not cluster:
        return set()
    return set(PREF_CLUSTERS.get(cluster, []))


def _category_kws(category: str) -> List[str]:
    return CATEGORY_ENUM_MAP.get(category, [category])


def _fetch_ordinance_rows(category: str, prefs: Set[str]) -> List[dict]:
    conn = get_canonical_conn()
    if conn is None:
        return []
    kws = _category_kws(category)
    # Build OR-chain of LIKE on primary_name / source_excerpt
    params: List[str] = []
    likes: List[str] = []
    for k in kws:
        likes.append("(e.primary_name LIKE ? OR e.raw_json LIKE ?)")
        params.extend([f"%{k}%", f"%{k}%"])
    if not likes:
        return []
    where_like = " OR ".join(likes)
    rows = safe_rows(
        conn,
        f"""
        SELECT e.primary_name, e.raw_json, e.source_url, e.source_topic
        FROM am_entities e
        WHERE e.source_topic='47_local_ordinance_benefits' AND ({where_like})
        LIMIT 120
        """,
        tuple(params),
    )
    out: List[dict] = []
    for r in rows:
        try:
            raw = json.loads(r["raw_json"] or "{}")
        except Exception:
            raw = {}
        pref = raw.get("prefecture") or ""
        if prefs and pref not in prefs:
            continue
        out.append({
            "muni_name": raw.get("municipality") or pref,
            "pref": pref,
            "program_name": raw.get("program_name") or r["primary_name"],
            "program_kind": raw.get("program_kind"),
            "benefit_amount": raw.get("benefit_amount"),
            "duration_years": raw.get("duration_years"),
            "source_url": raw.get("official_url") or r["source_url"],
            "source_topic": r["source_topic"],
            "excerpt": raw.get("source_excerpt"),
        })
    return out


def _fetch_dc_rows(category: str, prefs: Set[str]) -> List[dict]:
    conn = get_canonical_conn()
    if conn is None:
        return []
    tags = DESIGNATED_CITY_CATEGORY_TAG.get(category) or set()
    kws = _category_kws(category)

    rows = safe_rows(
        conn,
        """
        SELECT e.primary_name, e.raw_json, e.source_url
        FROM am_entities e
        WHERE e.source_topic='20_designated_city_programs'
        LIMIT 300
        """,
    )
    out: List[dict] = []
    for r in rows:
        try:
            raw = json.loads(r["raw_json"] or "{}")
        except Exception:
            continue
        cat = (raw.get("category") or "").lower()
        nm = (raw.get("program_name") or "") + " " + (raw.get("source_excerpt") or "")
        ok = (cat in tags) or any(k in nm for k in kws)
        if not ok:
            continue
        pref = raw.get("prefecture") or ""
        if prefs and pref not in prefs:
            continue
        out.append({
            "muni_name": raw.get("municipality") or raw.get("authority_name") or pref,
            "pref": pref,
            "program_name": raw.get("program_name") or r["primary_name"],
            "amount_max_yen": raw.get("amount_max_yen"),
            "subsidy_rate": raw.get("subsidy_rate"),
            "target_types": raw.get("target_types"),
            "category_enum": raw.get("category"),
            "source_url": raw.get("official_url") or r["source_url"],
            "excerpt": raw.get("source_excerpt"),
        })
    return out


_CATEGORY_EXTRA_TOPICS: Dict[str, List[str]] = {
    "水道PFI": ["143_water_wide_area_pfi_detail", "77_water_business_infrastructure"],
    "消防": ["119_fire_prevention_emergency_hazmat"],
    "子育て": ["36_women_childcare_support", "128_afterschool_kids_club_childcare"],
    "農業": ["26_agri_tax_deep", "95_food_security_maff_deep"],
    "省エネ": ["15_environment_energy_programs"],
    "商店街": ["91_wholesale_market_distribution"],
    # Fall-back data sources for categories where 4 main tables have no rows.
    # These surface adoption cases, cross-fund, adjacent programs for peer walk.
    "結婚新生活": ["05_adoption_additional", "22_mirasapo_cases",
               "36_women_childcare_support", "116_funeral_bridal_end_of_life"],
    "ふるさと納税": ["05_adoption_additional", "48_crowdfunding_matching_funds",
               "150_local_taxes_detail"],
    "地域振興": ["81_regional_business_brand_gi", "22_mirasapo_cases"],
    "観光": ["81_regional_business_brand_gi"],
    "創業": ["22_mirasapo_cases"],
}


def _fetch_pref_rows(category: str, prefs: Set[str]) -> List[dict]:
    conn = get_canonical_conn()
    if conn is None:
        return []
    kws = _category_kws(category)
    params: List[str] = []
    likes: List[str] = []
    for k in kws:
        likes.append("(e.primary_name LIKE ? OR e.raw_json LIKE ?)")
        params.extend([f"%{k}%", f"%{k}%"])
    where_like = " OR ".join(likes) if likes else "1=0"

    topics = ["06_prefecture_programs", "33_prefecture_programs_part2"]
    topics.extend(_CATEGORY_EXTRA_TOPICS.get(category, []))
    tq = ",".join("?" * len(topics))

    # Perf: 05_adoption_additional (69k rows) triggers slow raw_json LIKE scans
    # (40-250 ms p95). When that heavy topic is in scope AND all category kws
    # are >= 3 chars (trigram minimum) AND the kw list is short (<=2 so FTS
    # selectivity stays high), pre-narrow via FTS5 trigram CTE. LIKE is
    # preserved as verifier so equivalence is unchanged.
    _heavy_topics = {"05_adoption_additional"}
    fts_eligible = (
        bool(kws)
        and all(len(k) >= 3 for k in kws)
        and len(kws) <= 2
        and any(t in _heavy_topics for t in topics)
    )
    if fts_eligible:
        fts_query = " OR ".join(f'"{k}"' for k in kws)
        rows = safe_rows(
            conn,
            f"""
            WITH kw AS (
              SELECT canonical_id FROM am_entities_fts
              WHERE am_entities_fts MATCH ?
            )
            SELECT e.primary_name, e.raw_json, e.source_url, e.source_topic
            FROM am_entities e
            JOIN kw ON kw.canonical_id = e.canonical_id
            WHERE e.source_topic IN ({tq})
              AND ({where_like})
            LIMIT 200
            """,
            (fts_query,) + tuple(topics) + tuple(params),
        )
    else:
        rows = safe_rows(
            conn,
            f"""
            SELECT e.primary_name, e.raw_json, e.source_url, e.source_topic
            FROM am_entities e
            WHERE e.source_topic IN ({tq})
              AND ({where_like})
            LIMIT 200
            """,
            tuple(topics) + tuple(params),
        )
    out: List[dict] = []
    for r in rows:
        try:
            raw = json.loads(r["raw_json"] or "{}")
        except Exception:
            continue
        pref = raw.get("prefecture") or ""
        # Some extra topics (143_water_wide_area_pfi_detail) lack prefecture;
        # we accept them when no cluster filter is active.
        if prefs and pref and pref not in prefs:
            continue
        muni = raw.get("municipality") or raw.get("operator") or pref or r["source_topic"]
        prog_name = (
            raw.get("program_name") or raw.get("title") or r["primary_name"]
        )
        out.append({
            "muni_name": muni,
            "pref": pref or "-",
            "program_name": prog_name,
            "amount_max_yen": raw.get("amount_max_yen"),
            "subsidy_rate": raw.get("subsidy_rate"),
            "target_types": raw.get("target_types"),
            "source_url": raw.get("official_url") or raw.get("source_url") or r["source_url"],
            "excerpt": raw.get("source_excerpt") or raw.get("overview"),
        })
    return out


def bind(slots: Dict[str, Any], cache: PrecomputedCache) -> Dict[str, Any]:
    source_muni = slots.get("source_municipality")
    pop_band = slots.get("muni_population_band")  # legacy alias; kept for queries without muni name
    category = slots.get("program_category")
    cluster = slots.get("pref_cluster")

    notes: List[str] = []
    source_urls: List[str] = []

    # ---- Wave-6: peer roster from population_exact cache (authoritative) ----
    peer_rows: List[dict] = []
    peer_muni_names: List[str] = []
    target_pop: Optional[int] = None
    if source_muni:
        peer_rows = _peers_by_muni_name(source_muni, limit=20)
        if peer_rows:
            peer_muni_names = [r["peer_name"] for r in peer_rows]
            # Grab target_pop for display from the first row.
            target_pop = peer_rows[0].get("target_pop")
            # Override cluster with peer-pref if not already set: infer prefecture
            # from target_code's first 2 digits and use that to seed pref filter.
            if not cluster and peer_rows:
                # Derive cluster from majority peer pref_code (best-effort).
                pref_counter = Counter(r.get("pref_code") for r in peer_rows)
                # (no enum mapping here; we still allow empty cluster so
                # downstream category walk stays national)

    # Fallback: if program_category is empty BUT we have a source_municipality
    # or pop band, run a broad pref + designated city sweep so peer comparison
    # still returns something useful (instead of refusing).
    if not category:
        if source_muni or pop_band or cluster:
            category = "地域振興"  # trigger broad walk
            notes.append("category fallback=地域振興 (from source_muni/pop_band)")
        else:
            return {
                "bound_ok": False,
                "ctx": {
                    "source_municipality": source_muni or "(未指定)",
                    "muni_population_band": pop_band or "(未指定)",
                    "pref_cluster": cluster or "(未指定)",
                    "program_category": "(未指定)",
                    "peer_roster": "- (program_category 未指定 — 絞り込みできず)",
                    "comparison_table": "- (program_category 未指定)",
                },
                "source_urls": [],
                "notes": ["program_category empty"],
            }

    prefs = _prefs_for_cluster(cluster)

    ordinance_rows = _fetch_ordinance_rows(category, prefs)
    dc_rows = _fetch_dc_rows(category, prefs)
    pref_rows = _fetch_pref_rows(category, prefs)

    all_rows = ordinance_rows + dc_rows + pref_rows

    # Wave-6 ranking: prioritise rows whose muni_name matches a peer from
    # the population_exact cache. Move them to the front of all_rows.
    if peer_muni_names and all_rows:
        peer_set = set(peer_muni_names)
        peer_boosted: List[dict] = []
        others: List[dict] = []
        for r in all_rows:
            mn = r.get("muni_name") or ""
            if any(p and p in mn for p in peer_set):
                peer_boosted.append(r)
            else:
                others.append(r)
        if peer_boosted:
            all_rows = peer_boosted + others
            notes.append(f"peer_boosted={len(peer_boosted)}")

    # Legacy name-boost: surface rows that mention source_municipality even
    # when no peer match (kept for i07/i08 backward compat).
    if source_muni and all_rows:
        boosted: List[dict] = []
        others: List[dict] = []
        for r in all_rows:
            muni_name = r.get("muni_name") or ""
            excerpt = r.get("excerpt") or ""
            if source_muni in muni_name or source_muni in excerpt:
                boosted.append(r)
            else:
                others.append(r)
        if boosted:
            all_rows = boosted + others
            notes.append(f"source_muni match count={len(boosted)}")
    # Collect URLs
    for r in all_rows:
        if r.get("source_url"):
            source_urls.append(r["source_url"])

    # ---- Comparison table ----
    tbl_lines = [
        "| 自治体 | 制度名 | 上限/内容 | 対象 | URL |",
        "|---|---|---|---|---|",
    ]
    for r in all_rows[:30]:
        muni = f"{r.get('muni_name','-')} ({r.get('pref','-')})"
        name = r.get("program_name") or "-"
        amt_raw = r.get("amount_max_yen")
        if amt_raw is not None:
            amt = f"¥{_fmt_yen(amt_raw)}万"
        else:
            amt = r.get("benefit_amount") or "-"
        targets = r.get("target_types") or []
        if isinstance(targets, list):
            targets = "/".join(targets[:3]) or "-"
        elif not targets:
            targets = "-"
        url = r.get("source_url") or "-"
        tbl_lines.append(f"| {muni} | {name} | {amt} | {targets} | {url} |")
    if len(all_rows) > 30:
        tbl_lines.append(f"| ... 他 {len(all_rows) - 30} 件 | | | | |")

    # ---- Peer roster ----
    # Wave-6: prefer exact-pop peer roster (authoritative). Fallback to
    # distinct muni_name from fetched rows.
    muni_set: List[str] = []
    if peer_rows:
        for r in peer_rows:
            mode = r.get("match_mode") or "exact"
            delta_pct = r.get("pop_delta_pct") or 0.0
            muni_set.append(
                f"{r.get('peer_name')} "
                f"(人口 {r.get('peer_pop'):,}, ±{delta_pct*100:.1f}%, {mode})"
            )
        peer_roster = "\n".join(f"- {m}" for m in muni_set[:15])
    else:
        seen: Set[str] = set()
        for r in all_rows:
            mn = f"{r.get('muni_name','-')} ({r.get('pref','-')})"
            if mn not in seen:
                seen.add(mn)
                muni_set.append(mn)
        peer_roster = "\n".join(f"- {m}" for m in muni_set[:15]) or "- (該当ピア未検出)"

    # ---- Similar design bullets (top 5 by prefix match of name) ----
    similar = [
        f"- {r.get('program_name','-')} ({r.get('muni_name','-')} / {r.get('pref','-')}): "
        f"{(r.get('excerpt') or '')[:80]}"
        for r in all_rows[:5]
    ]

    # ---- Template ordinance URLs: prefer 47_local_ordinance (root_ordinance) ----
    tmpl_urls: List[str] = []
    for r in ordinance_rows[:6]:
        if r.get("source_url"):
            tmpl_urls.append(f"- {r.get('pref','-')}: {r['source_url']}")
    tmpl_text = "\n".join(tmpl_urls) or "- (テンプレート条例 URL 未 ingest)"

    # ---- Coverage % — honest ----
    # 1788 total municipalities, ~200 DC rows present: coverage ~11%
    muni_coverage_pct = "11"

    # ---- Uncovered peers note ----
    uncovered = (
        "- 1,788市町村の網羅率約11% (20+06+33+47 の合算; 残 ~1,500 は P1 未整備)\n"
        "- 同人口帯 peer cluster は未構築 — 10_municipality_master + 総務省人口 CSV の join が必要"
    )

    # Target pop display (for Wave-6 transparency).
    if target_pop:
        target_pop_str = f"{target_pop:,}人 (住基台帳 R7.1.1)"
    else:
        target_pop_str = pop_band or "(未指定)"

    ctx = {
        "source_municipality": source_muni or "(未指定)",
        "muni_population_band": pop_band or "(未指定)",
        "source_muni_pop_exact": target_pop_str,
        "pref_cluster": cluster or "(未指定)",
        "program_category": category,
        "peer_count": str(len(muni_set)),
        "peer_roster": peer_roster,
        "comparison_table": "\n".join(tbl_lines),
        "top_n": str(min(len(all_rows), 5)),
        "similar_design_bullets": "\n".join(similar) or "- (該当なし)",
        "template_ordinance_urls": tmpl_text,
        "uncovered_peers_note": uncovered,
        "muni_coverage_pct": muni_coverage_pct,
        "citation_urls": "\n".join(f"- {u}" for u in list(dict.fromkeys(source_urls))[:10])
        or "- (URL 未 ingest)",
    }

    notes.append(
        f"ordinance={len(ordinance_rows)} dc={len(dc_rows)} pref={len(pref_rows)} "
        f"prefs_filter={len(prefs)} peers_exact={len(peer_rows)}"
    )
    # Wave-6: bound_ok if we got either program rows OR a non-trivial peer roster.
    bound_ok = bool(all_rows) or bool(peer_rows)

    return {
        "bound_ok": bound_ok,
        "ctx": ctx,
        "source_urls": list(dict.fromkeys(source_urls))[:15],
        "notes": notes,
    }


register("i08_similar_municipality_programs", bind)
