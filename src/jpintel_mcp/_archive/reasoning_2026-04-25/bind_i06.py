"""bind_i06 — 併用可/不可の他制度.

Data sources (read-only):
  graph      graph.sqlite   (am_relation where relation_type in
                             compatible / incompatible / prerequisite)
  canonical  autonomath.db
             - 03_exclusion_rules (78 rows) - rule_type, excluded_programs,
               condition, source_url
             - 08_loan_programs (109 rows) - target_conditions often
               describes 経営革新計画 prereq or overlapping 補助金 etc.
             - record_kind='program' rows with raw.compatible_with /
               raw.incompatible_with inline fields (15 / 149 / 67 topics)
             - raw.requires_prerequisite
  precompute program_compat_closure / program_incompat_closure / program_prereq_closure
             (pair-wise transitive)

Strategy
--------
Given slots["program_ids"] (list, 0..8 items), produce:
  1. Pairwise N*N verdict matrix (violation / combine_ok / prerequisite / unknown)
     using precompute closures for transitive edges + canonical 03_exclusion_rules
     for source_url / condition.
  2. For single program: enumerate all compat/incompat/prereq partners.
  3. Impact assessment (返還要否 / 公表 / 認定取消) from exclusion rule condition
     free text — scan for 返還 / 公表 / 取消 / 取り消し.
  4. Source URLs from 03_exclusion_rules.source_url + fact URLs.

When program_ids has 0 items we surface a help message + an empty matrix.
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
from .precompute import PrecomputedCache, canonical_program_id


# ---------------------------------------------------------------------------
# Impact keywords (condition text -> violation impact)
# ---------------------------------------------------------------------------

_IMPACT_RULES: List[Tuple[str, List[str]]] = [
    ("補助金返還", ["返還", "返却", "refund"]),
    ("交付決定取消", ["取消", "取り消し", "中止"]),
    ("認定取消", ["認定取消"]),
    ("公表", ["公表", "報告"]),
    ("将来応募制限", ["今後", "制限", "応募できない"]),
]


def _classify_impact(condition: str) -> List[str]:
    out: List[str] = []
    for label, kws in _IMPACT_RULES:
        for kw in kws:
            if kw in condition:
                out.append(label)
                break
    return out


# ---------------------------------------------------------------------------
# Exclusion rule lookup (canonical)
# ---------------------------------------------------------------------------

def _fetch_exclusion_rules_for(program_name: str) -> List[dict]:
    conn = get_canonical_conn()
    if conn is None or not program_name:
        return []
    name_canon = canonical_program_id(program_name)
    rows = safe_rows(
        conn,
        """
        SELECT e.primary_name, e.raw_json, e.source_url
        FROM am_entities e
        WHERE e.source_topic='03_exclusion_rules'
          AND (e.primary_name LIKE ? OR e.raw_json LIKE ?)
        LIMIT 40
        """,
        (f"%{name_canon}%", f"%{name_canon}%"),
    )
    out: List[dict] = []
    for r in rows:
        try:
            raw = json.loads(r["raw_json"] or "{}")
        except Exception:
            raw = {}
        out.append({
            "program_name_a": raw.get("program_name_a"),
            "rule_type": raw.get("rule_type"),
            "excluded_programs": raw.get("excluded_programs") or [],
            "condition": raw.get("condition") or "",
            "source_url": r["source_url"] or raw.get("source_url"),
            "source_excerpt": (raw.get("source_excerpt") or "")[:150],
        })
    return out


def _fetch_inline_compat_for(program_name: str) -> dict:
    """For record_kind='program' rows that have inline
    raw.compatible_with / raw.incompatible_with / raw.requires_prerequisite."""
    conn = get_canonical_conn()
    if conn is None or not program_name:
        return {}
    name_canon = canonical_program_id(program_name)
    rows = safe_rows(
        conn,
        """
        SELECT e.primary_name, e.raw_json, e.source_url
        FROM am_entities e
        WHERE e.record_kind='program' AND e.primary_name LIKE ?
        LIMIT 10
        """,
        (f"%{name_canon}%",),
    )
    compat: Set[str] = set()
    incompat: Set[str] = set()
    prereq: Set[str] = set()
    urls: List[str] = []
    for r in rows:
        try:
            raw = json.loads(r["raw_json"] or "{}")
        except Exception:
            raw = {}
        for p in (raw.get("compatible_with") or []):
            compat.add(str(p))
        for p in (raw.get("incompatible_with") or []):
            incompat.add(str(p))
        for p in (raw.get("requires_prerequisite") or []):
            prereq.add(str(p))
        if r["source_url"]:
            urls.append(r["source_url"])
    return {
        "compat": sorted(compat),
        "incompat": sorted(incompat),
        "prereq": sorted(prereq),
        "source_urls": urls,
    }


# ---------------------------------------------------------------------------
# Graph DB probe (transitive)
# ---------------------------------------------------------------------------

def _graph_pair_verdict(a: str, b: str) -> Optional[str]:
    conn = get_graph_conn()
    if conn is None:
        return None
    a_canon = canonical_program_id(a)
    b_canon = canonical_program_id(b)
    if not a_canon or not b_canon:
        return None
    # Check direct edges both directions
    for (src, tgt) in ((a_canon, b_canon), (b_canon, a_canon)):
        for rt in ("incompatible", "compatible", "prerequisite"):
            rows = safe_rows(
                conn,
                """
                SELECT 1 FROM am_relation r JOIN am_node s ON s.node_id=r.source_id
                   JOIN am_node t ON t.node_id=r.target_id
                 WHERE r.relation_type=?
                   AND s.display_name LIKE ? AND t.display_name LIKE ?
                LIMIT 1
                """,
                (rt, f"%{src}%", f"%{tgt}%"),
            )
            if rows:
                return rt
    return None


# ---------------------------------------------------------------------------
# Pair verdict (precompute + graph + inline)
# ---------------------------------------------------------------------------

def _pair_verdict(a: str, b: str, cache: PrecomputedCache) -> dict:
    a_canon = canonical_program_id(a)
    b_canon = canonical_program_id(b)
    # precompute: direct or transitive closure membership
    if b in cache.program_incompat_closure.get(a, []) \
            or a in cache.program_incompat_closure.get(b, []) \
            or b_canon in cache.program_incompat_closure.get(a_canon, []) \
            or a_canon in cache.program_incompat_closure.get(b_canon, []):
        return {"verdict": "violation", "reason": "incompatible (closure)"}
    if b in cache.program_compat_closure.get(a, []) \
            or a in cache.program_compat_closure.get(b, []) \
            or b_canon in cache.program_compat_closure.get(a_canon, []) \
            or a_canon in cache.program_compat_closure.get(b_canon, []):
        return {"verdict": "combine_ok", "reason": "explicit combine_ok (closure)"}
    if b in cache.program_prereq_closure.get(a, []) \
            or b_canon in cache.program_prereq_closure.get(a_canon, []):
        return {"verdict": "prerequisite", "reason": "b is prerequisite of a"}
    # graph fallback
    graph_verdict = _graph_pair_verdict(a, b)
    if graph_verdict == "incompatible":
        return {"verdict": "violation", "reason": "graph incompatible edge"}
    if graph_verdict == "compatible":
        return {"verdict": "combine_ok", "reason": "graph compatible edge"}
    if graph_verdict == "prerequisite":
        return {"verdict": "prerequisite", "reason": "graph prerequisite edge"}
    return {"verdict": "unknown", "reason": "pair not in closure / graph / inline"}


# ---------------------------------------------------------------------------
# Enumerate partners of a single program
# ---------------------------------------------------------------------------

def _enumerate_partners(
    pid: str,
    cache: PrecomputedCache,
) -> Dict[str, List[str]]:
    pid_canon = canonical_program_id(pid)
    out: Dict[str, List[str]] = {
        "compat": sorted(set(cache.program_compat_closure.get(pid, [])
                             + cache.program_compat_closure.get(pid_canon, []))),
        "incompat": sorted(set(cache.program_incompat_closure.get(pid, [])
                               + cache.program_incompat_closure.get(pid_canon, []))),
        "prereq": sorted(set(cache.program_prereq_closure.get(pid, [])
                             + cache.program_prereq_closure.get(pid_canon, []))),
    }
    # Merge inline raw.* fields from canonical DB
    inline = _fetch_inline_compat_for(pid)
    for k in ("compat", "incompat", "prereq"):
        out[k] = sorted(set(out[k]) | set(inline.get(k, [])))
    return out


# ---------------------------------------------------------------------------
# Bind entrypoint
# ---------------------------------------------------------------------------

def bind(slots: Dict[str, Any], cache: PrecomputedCache) -> Dict[str, Any]:
    pids: List[str] = slots.get("program_ids") or []
    notes: List[str] = []
    source_urls: List[str] = []

    if not pids:
        return {
            "bound_ok": False,
            "ctx": {
                "program_list_bullets": "(制度未指定 — program_ids slot 空)",
                "overall_verdict": "unknown",
                "pair_matrix_table": "- (program_ids 未指定)",
                "violation_detail_bullets": "- (判定対象なし)",
                "suggested_stack_patterns": (
                    "- 国補助金 + 県制度融資 + 税制優遇 の3層 (同一経費重複不可)\n"
                    "- 経営革新計画 認定 → 多数の補助金で加点/特別利率"
                ),
                "citation_urls": "- (program_ids 未指定のため URL 未取得)",
            },
            "source_urls": [],
            "notes": ["program_ids empty"],
        }

    # Single-program enumeration
    if len(pids) == 1:
        pid = pids[0]
        partners = _enumerate_partners(pid, cache)
        rules = _fetch_exclusion_rules_for(pid)
        inline = _fetch_inline_compat_for(pid)
        for u in inline.get("source_urls", []):
            source_urls.append(u)
        for r in rules:
            if r.get("source_url"):
                source_urls.append(r["source_url"])

        tbl = ["| A | B | verdict | 根拠 |", "|---|---|---|---|"]
        for b in partners["incompat"][:20]:
            tbl.append(f"| {pid} | {b} | violation | exclusion_rules / closure |")
        for b in partners["compat"][:15]:
            tbl.append(f"| {pid} | {b} | combine_ok | combine_ok / tax.compatible_with |")
        for b in partners["prereq"][:15]:
            tbl.append(f"| {pid} | {b} | prerequisite | 認定前提 |")

        violation_bullets: List[str] = []
        for rule in rules[:10]:
            if rule.get("rule_type") == "exclude":
                cond = rule.get("condition") or ""
                impacts = _classify_impact(cond)
                imp = "/".join(impacts) if impacts else "(condition記載のみ)"
                excls = rule.get("excluded_programs") or []
                for e in excls[:3]:
                    violation_bullets.append(
                        f"- {pid} × {e}: 条件 `{cond[:80]}` → impact={imp}"
                    )

        overall = "mixed"
        if partners["incompat"] and not partners["compat"]:
            overall = "violation"
        elif partners["compat"] and not partners["incompat"]:
            overall = "combine_ok"
        elif not (partners["compat"] or partners["incompat"] or partners["prereq"]):
            overall = "unknown"

        ctx = {
            "program_list_bullets": (
                f"- {pid} (incompat={len(partners['incompat'])}, "
                f"compat={len(partners['compat'])}, prereq={len(partners['prereq'])})"
            ),
            "overall_verdict": overall,
            "pair_matrix_table": "\n".join(tbl),
            "violation_detail_bullets": "\n".join(violation_bullets) or "- (違反ペアなし)",
            "suggested_stack_patterns": (
                "- 国 (ものづくり補助金等) + 県 (制度融資) + 税制 (経営強化税制) の3層は"
                "同一経費でない限り典型的 stack\n"
                "- IT導入補助金 + 小規模事業者持続化補助金 は 同一経費重複不可 (逐次実施なら可)"
            ),
            "citation_urls": "\n".join(f"- {u}" for u in list(dict.fromkeys(source_urls))[:10])
            or "- (03_exclusion_rules source_url 未ingest)",
        }

        notes.append(
            f"single program={pid} incompat={len(partners['incompat'])} "
            f"compat={len(partners['compat'])} prereq={len(partners['prereq'])} "
            f"rules={len(rules)}"
        )

        return {
            "bound_ok": bool(partners["incompat"] or partners["compat"]
                             or partners["prereq"] or rules),
            "ctx": ctx,
            "source_urls": list(dict.fromkeys(source_urls))[:15],
            "notes": notes,
        }

    # Multi-program: pair-wise matrix
    pair_verdicts: List[dict] = []
    for i, a in enumerate(pids):
        for b in pids[i + 1:]:
            verdict = _pair_verdict(a, b, cache)
            pair_verdicts.append({"a": a, "b": b, **verdict})

    # Rules (union across all programs) for source_url + impact detail
    all_rules: List[dict] = []
    for pid in pids:
        all_rules.extend(_fetch_exclusion_rules_for(pid))
        inline = _fetch_inline_compat_for(pid)
        for u in inline.get("source_urls", []):
            source_urls.append(u)
    for rule in all_rules:
        if rule.get("source_url"):
            source_urls.append(rule["source_url"])

    # Overall verdict rollup
    vset = {p["verdict"] for p in pair_verdicts}
    if "violation" in vset:
        overall = "violation"
    elif vset == {"unknown"}:
        overall = "unknown"
    elif "combine_ok" in vset and "unknown" not in vset:
        overall = "combine_ok"
    else:
        overall = "mixed"

    # Program_list_bullets
    pbullets: List[str] = []
    for pid in pids:
        partners = _enumerate_partners(pid, cache)
        pbullets.append(
            f"- {pid} (incompat={len(partners['incompat'])}, "
            f"compat={len(partners['compat'])}, prereq={len(partners['prereq'])})"
        )

    # Matrix
    tbl = ["| A | B | verdict | reason |", "|---|---|---|---|"]
    for p in pair_verdicts:
        tbl.append(f"| {p['a']} | {p['b']} | {p['verdict']} | {p.get('reason','')} |")

    # Violation detail bullets (with impact)
    violation_bullets: List[str] = []
    for p in pair_verdicts:
        if p["verdict"] != "violation":
            continue
        # find matching rule(s)
        matching: List[dict] = []
        for r in all_rules:
            excls = r.get("excluded_programs") or []
            if r.get("rule_type") != "exclude":
                continue
            a_canon = canonical_program_id(p["a"])
            b_canon = canonical_program_id(p["b"])
            for e in excls:
                ec = canonical_program_id(str(e))
                if ec == b_canon or ec == a_canon or b_canon in ec or a_canon in ec:
                    matching.append(r)
                    break
        if not matching:
            violation_bullets.append(
                f"- {p['a']} × {p['b']}: {p.get('reason')} "
                "(exclusion_rules 未収録 — graph closure 判定)"
            )
        for r in matching[:2]:
            cond = r.get("condition") or ""
            impacts = _classify_impact(cond)
            imp = "/".join(impacts) if impacts else "(condition記載)"
            violation_bullets.append(
                f"- {p['a']} × {p['b']}: 条件 `{cond[:80]}` impact={imp}"
            )

    ctx = {
        "program_list_bullets": "\n".join(pbullets) or "(制度未指定)",
        "overall_verdict": overall,
        "pair_matrix_table": "\n".join(tbl),
        "violation_detail_bullets": "\n".join(violation_bullets) or "- (違反ペアなし)",
        "suggested_stack_patterns": (
            "- 国 (ものづくり補助金) + 県 (制度融資) + 税制 (中小企業経営強化税制) の3層は"
            "同一経費でない限り典型的 stack\n"
            "- IT導入補助金 + 小規模事業者持続化補助金 は 同一経費重複不可 (逐次実施なら可)"
        ),
        "citation_urls": "\n".join(f"- {u}" for u in list(dict.fromkeys(source_urls))[:10])
        or "- (03_exclusion_rules source_url 未 ingest)",
    }

    notes.append(
        f"pids={len(pids)} pairs={len(pair_verdicts)} "
        f"rules={len(all_rules)} overall={overall}"
    )

    return {
        "bound_ok": bool(pair_verdicts),
        "ctx": ctx,
        "source_urls": list(dict.fromkeys(source_urls))[:15],
        "notes": notes,
    }


register("i06_compat_incompat_stacking", bind)
