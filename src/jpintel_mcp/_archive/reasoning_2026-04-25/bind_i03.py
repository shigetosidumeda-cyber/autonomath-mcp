"""bind_i03 — ある制度の後継制度・改正内容.

Data sources (read-only):
  graph      graph.sqlite   (am_relation where relation_type='replaces')
  canonical  autonomath.db
             - am_entities source_topic='07_new_program_candidates' (令和8税制改正)
             - am_entities record_kind='tax_measure' (abolition_note)
             - am_entity_facts relation.N.kind/to_name_raw
             - am_entity_facts raw.application_period_to (for sunset)
  precompute tax_measure_validity (status/abolition_note)

Strategy
--------
The graph DB has ``replaces`` edges (successor -> predecessor). When asked
about a program_id:
  1. Look up ``successor_of`` (reverse ``replaces`` — something replaces ME).
  2. Look up ``predecessor_of`` (forward ``replaces`` — I replace someone).
  3. Scan am_entity_facts for ``relation.N.to_name_raw`` where kind mentions
     廃止/後継/統合 — catches the 03_exclusion_rules-style narrative edges.
  4. For tax measures, surface validity_index.status + abolition_note.
  5. 07_new_program_candidates gives us 令和8年度 改正 proposed items.

The revision_chain table isn't ingested yet (P1 gap), so we assemble a
best-effort chain from whatever links we find and honestly flag incompleteness.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from .bind_registry import (
    get_canonical_conn,
    get_graph_conn,
    register,
    safe_rows,
)
from .precompute import PrecomputedCache, canonical_program_id


def _graph_successor_chain(program_id: str) -> Dict[str, List[str]]:
    """Return {'successor': [...], 'predecessor': [...]} via the graph DB."""
    conn = get_graph_conn()
    out: Dict[str, List[str]] = {"successor": [], "predecessor": []}
    if conn is None or not program_id:
        return out
    node_id_direct = f"program:{program_id}"

    # First, resolve fuzzy node id via LIKE (display_name contains)
    name_rows = safe_rows(
        conn,
        "SELECT node_id FROM am_node WHERE kind='program' AND display_name LIKE ? LIMIT 50",
        (f"%{program_id}%",),
    )
    node_ids = {r["node_id"] for r in name_rows}
    node_ids.add(node_id_direct)

    for nid in node_ids:
        # I replace X  (successor_of X)
        for r in safe_rows(
            conn,
            "SELECT target_id FROM am_relation WHERE source_id=? AND relation_type='replaces'",
            (nid,),
        ):
            out["predecessor"].append(r["target_id"])
        # X replaces me (I am predecessor_of X)
        for r in safe_rows(
            conn,
            "SELECT source_id FROM am_relation WHERE target_id=? AND relation_type='replaces'",
            (nid,),
        ):
            out["successor"].append(r["source_id"])
    # dedupe
    out["successor"] = sorted(set(out["successor"]))
    out["predecessor"] = sorted(set(out["predecessor"]))
    return out


def _narrative_relation_hits(program_id: str) -> List[dict]:
    """Scan am_entity_facts for relation.N.to_name_raw mentioning 廃止/後継/統合
    where the parent entity name contains program_id."""
    conn = get_canonical_conn()
    if conn is None or not program_id:
        return []
    rows = safe_rows(
        conn,
        """
        SELECT e.primary_name, f.field_name, f.field_value_text, e.source_url
        FROM am_entity_facts f
        JOIN am_entities e ON f.entity_id = e.canonical_id
        WHERE e.primary_name LIKE ?
          AND f.field_name LIKE 'relation.%.to_name_raw'
        LIMIT 50
        """,
        (f"%{program_id}%",),
    )
    hits: List[dict] = []
    for r in rows:
        txt = r["field_value_text"] or ""
        if any(k in txt for k in ("廃止", "後継", "統合", "統合後", "改称", "旧")):
            hits.append(dict(r))
    return hits


def _abolition_note_from_facts(program_id: str) -> List[dict]:
    conn = get_canonical_conn()
    if conn is None or not program_id:
        return []
    rows = safe_rows(
        conn,
        """
        SELECT e.primary_name, e.raw_json, e.source_url, e.source_topic
        FROM am_entities e
        WHERE e.primary_name LIKE ?
          AND e.record_kind IN ('tax_measure','program')
        LIMIT 40
        """,
        (f"%{program_id}%",),
    )
    out: List[dict] = []
    for r in rows:
        try:
            raw = json.loads(r["raw_json"] or "{}")
        except Exception:
            raw = {}
        if raw.get("abolition_note"):
            out.append({
                "primary_name": r["primary_name"],
                "abolition_note": raw.get("abolition_note"),
                "application_period_to": raw.get("application_period_to"),
                "source_url": r["source_url"],
                "source_topic": r["source_topic"],
            })
    return out


def _r8_tax_reform_candidates(fiscal_year: Optional[int]) -> List[dict]:
    conn = get_canonical_conn()
    if conn is None:
        return []
    rows = safe_rows(
        conn,
        """
        SELECT e.primary_name, e.raw_json, e.source_url
        FROM am_entities e
        WHERE e.source_topic='07_new_program_candidates'
        LIMIT 100
        """,
    )
    out: List[dict] = []
    for r in rows:
        try:
            raw = json.loads(r["raw_json"] or "{}")
        except Exception:
            raw = {}
        display = raw.get("candidate_name") or r["primary_name"]
        out.append({
            "primary_name": display,
            "ministry": raw.get("ministry"),
            "expected_start": raw.get("expected_start"),
            "mentioned_in": raw.get("mentioned_in"),
            "source_url": r["source_url"],
            "excerpt": (raw.get("policy_background_excerpt") or "")[:120],
        })
    return out


def bind(slots: Dict[str, Any], cache: PrecomputedCache) -> Dict[str, Any]:
    program_id = slots.get("program_id")
    fiscal_year = slots.get("fiscal_year")
    notes: List[str] = []
    source_urls: List[str] = []

    if not program_id and not fiscal_year:
        return {
            "bound_ok": False,
            "ctx": {
                "program_name": "(未指定)",
                "revision_table": "- (program_id / law_id / fiscal_year いずれも未指定)",
            },
            "source_urls": [],
            "notes": ["no program_id / fiscal_year"],
        }

    successor_chain = _graph_successor_chain(program_id) if program_id else {"successor": [], "predecessor": []}
    narrative = _narrative_relation_hits(program_id) if program_id else []
    abol = _abolition_note_from_facts(program_id) if program_id else []
    r8 = _r8_tax_reform_candidates(fiscal_year)

    # precompute validity_index (tax measures)
    pid_canon = canonical_program_id(program_id) if program_id else ""
    vidx = None
    for mid, v in cache.tax_measure_validity.items():
        nm = v.get("name") or ""
        if program_id and (program_id in nm or nm in program_id or pid_canon in nm):
            vidx = v
            break

    # Build the revision_table (best effort markdown)
    rows_md: List[str] = ["| 年度 | 種別 | 概要 | 出典 |", "|---|---|---|---|"]
    if successor_chain["successor"]:
        for n in successor_chain["successor"][:5]:
            nm = n.replace("program:", "")
            rows_md.append(f"| (後継) | 後継制度 | {nm} が現制度を置き換え | graph.replaces |")
    if successor_chain["predecessor"]:
        for n in successor_chain["predecessor"][:5]:
            nm = n.replace("program:", "")
            rows_md.append(f"| (先行) | 先行制度 | この制度は {nm} の後継 | graph.replaces |")
    for n in narrative[:5]:
        summary = (n.get("field_value_text") or "")[:80]
        rows_md.append(f"| - | 関係記述 | {summary} | {n.get('source_url','-')} |")
        if n.get("source_url"):
            source_urls.append(n["source_url"])
    for a in abol[:5]:
        rows_md.append(
            f"| - | 廃止/期限 | {a['abolition_note'][:80]} (期限 {a.get('application_period_to','-')}) "
            f"| {a.get('source_url','-')} |"
        )
        if a.get("source_url"):
            source_urls.append(a["source_url"])
    # 令和8年度税制改正 候補 (always append — if fiscal_year matches it's the primary)
    if fiscal_year == 2026 or "令和8" in (program_id or ""):
        for r in r8[:8]:
            rows_md.append(
                f"| 令和8年度 | 新設/改正 | {r['primary_name'][:60]} (所管 {r.get('ministry','-')}) "
                f"| {r.get('source_url','-')} |"
            )
            if r.get("source_url"):
                source_urls.append(r["source_url"])

    successor_name = "-"
    if successor_chain["successor"]:
        successor_name = successor_chain["successor"][0].replace("program:", "")
    predecessor_name = "-"
    if successor_chain["predecessor"]:
        predecessor_name = successor_chain["predecessor"][0].replace("program:", "")
    if predecessor_name == "-" and narrative:
        # Fall back to the first narrative 後継 mention
        for n in narrative:
            t = n.get("field_value_text") or ""
            if "統合後" in t or "後継" in t:
                predecessor_name = t[:60]
                break

    latest_change = "-"
    latest_change_type = "-"
    effective_date = "-"
    transition = "-"
    if abol:
        a = abol[0]
        latest_change = a.get("abolition_note") or "-"
        latest_change_type = "廃止/期限"
        effective_date = a.get("application_period_to") or "-"
    elif vidx and vidx.get("status") in ("expired", "sunset_soon"):
        latest_change = f"status={vidx.get('status')}"
        latest_change_type = "適用期限"
        effective_date = vidx.get("application_period_to") or "-"

    ctx = {
        "program_name": program_id or "-",
        "program_id": program_id or "-",
        "revision_table": "\n".join(rows_md),
        "latest_fy": str(fiscal_year or 2026),
        "latest_change_type": latest_change_type,
        "latest_change_summary": latest_change,
        "effective_date": effective_date,
        "transition_period": transition,
        "predecessor_name": predecessor_name,
        "successor_name": successor_name,
        "coexistence_window": "-",
        "client_impact_checklist": (
            "- 既採択顧客の申請期限・交付決定日の再確認\n"
            "- 後継制度への申請切替タイミング\n"
            "- 経過措置 (e-Gov 法令原文で要検証)"
        ),
        "citation_urls": "\n".join(f"- {u}" for u in list(dict.fromkeys(source_urls))[:10])
        or "- (canonical source_url 未 ingest / revision_chain P1 未整備)",
    }

    bound_ok = bool(
        successor_chain["successor"]
        or successor_chain["predecessor"]
        or narrative
        or abol
        or (fiscal_year == 2026 and r8)
    )
    notes.append(
        f"graph(successor={len(successor_chain['successor'])}, "
        f"predecessor={len(successor_chain['predecessor'])}) "
        f"narrative={len(narrative)} abol={len(abol)} r8_candidates={len(r8)}"
    )

    return {
        "bound_ok": bound_ok,
        "ctx": ctx,
        "source_urls": list(dict.fromkeys(source_urls))[:20],
        "notes": notes,
    }


register("i03_program_successor_revision", bind)
