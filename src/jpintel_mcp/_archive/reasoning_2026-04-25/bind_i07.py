"""bind_i07 — 採択事例・過去実績.

Data sources (read-only):
  canonical  autonomath.db
             - 05_adoption_additional (105,341 rows) record_kind='adoption'
               facts: raw.prefecture, raw.industry_raw, raw.round_number, etc.
             - 22_mirasapo_cases (2,286 rows) record_kind='program' source_topic
               raw_json has full profile (employees/capital/houjin_bangou)
             - 01_meti_acceptance_stats / 02_maff_acceptance_stats — aggregate
               applicants/accepted/acceptance_rate per round

Strategy
--------
Given a program_id hint we:
  1. Lookup adoption records via raw.program_id_hint (jigyou_saikouchiku,
     monodukuri, jizokuka_ippan/sogyo, it_dounyu).
  2. Apply optional filters: round, prefecture, industry_jsic.
  3. Produce:
       - representative case bullets (top 8 by project title length / non-null)
       - prefecture histogram
       - industry histogram
       - acceptance_rate_pct from 01_meti_acceptance_stats if matching round
  4. Also surface 22_mirasapo_cases rows matching prefecture+industry even when
     they're not tied to a specific program (rich profile data is valuable).
"""
from __future__ import annotations

import json
from collections import Counter
from typing import Any, Dict, List, Optional

from .bind_registry import get_canonical_conn, register, safe_rows
from .precompute import PrecomputedCache


# Canonical program_id hint mapping (from raw.program_id_hint)
_HINT_MAP = {
    "ものづくり補助金": "monodukuri",
    "事業再構築補助金": "jigyou_saikouchiku",
    "中小企業等事業再構築促進補助金": "jigyou_saikouchiku",
    "小規模事業者持続化補助金": "jizokuka_ippan",  # ippan is the bigger bucket
    "IT導入補助金": "it_dounyu",
    "持続化補助金": "jizokuka_ippan",
}


def _resolve_hint(program_id: str) -> Optional[str]:
    if not program_id:
        return None
    for k, v in _HINT_MAP.items():
        if k in program_id or program_id in k:
            return v
    return None


def _fetch_adoption_facts(hint: str, filters: Dict[str, Any], limit: int = 500) -> List[dict]:
    """Join am_entities (adoption) with their facts, apply filters on
    prefecture / industry_raw / round_number."""
    conn = get_canonical_conn()
    if conn is None or not hint:
        return []

    # We bucket the relevant facts via pivot-like query.
    # First identify candidate entity_ids by program_id_hint.
    cand_rows = safe_rows(
        conn,
        """
        SELECT entity_id
        FROM am_entity_facts
        WHERE field_name='raw.program_id_hint' AND field_value_text = ?
        LIMIT 10000
        """,
        (hint,),
    )
    cand_ids = [r["entity_id"] for r in cand_rows]
    if not cand_ids:
        return []

    # Fetch relevant facts for those ids
    results: List[dict] = []
    CHUNK = 500
    for i in range(0, len(cand_ids), CHUNK):
        batch = cand_ids[i : i + CHUNK]
        qmarks = ",".join("?" * len(batch))
        rows = safe_rows(
            conn,
            f"""
            SELECT e.canonical_id, e.raw_json
            FROM am_entities e
            WHERE e.canonical_id IN ({qmarks})
            """,
            tuple(batch),
        )
        for r in rows:
            try:
                raw = json.loads(r["raw_json"] or "{}")
            except Exception:
                raw = {}
            if not raw:
                continue
            # filter
            if filters.get("round"):
                if raw.get("round_number") != filters["round"]:
                    continue
            if filters.get("prefecture"):
                pref_raw = raw.get("prefecture")
                if pref_raw != filters["prefecture"]:
                    continue
            if filters.get("industry_raw"):
                if filters["industry_raw"] not in (raw.get("industry_raw") or ""):
                    continue
            results.append(raw)
            if len(results) >= limit:
                return results
    return results


def _fetch_acceptance_stats(program_id: str, round_number: Optional[int]) -> List[dict]:
    """Pull 01_meti_acceptance_stats / 02_maff_acceptance_stats rows whose
    program_name matches program_id."""
    conn = get_canonical_conn()
    if conn is None or not program_id:
        return []
    rows = safe_rows(
        conn,
        """
        SELECT e.raw_json, e.source_url, e.source_topic
        FROM am_entities e
        WHERE e.source_topic IN ('01_meti_acceptance_stats','02_maff_acceptance_stats')
          AND e.primary_name LIKE ?
        LIMIT 60
        """,
        (f"%{program_id}%",),
    )
    out: List[dict] = []
    for r in rows:
        try:
            raw = json.loads(r["raw_json"] or "{}")
        except Exception:
            raw = {}
        if round_number is not None and raw.get("round_number") != round_number:
            continue
        raw["_source_url"] = r["source_url"]
        out.append(raw)
    return out


def _fetch_mirasapo_cases(prefecture: Optional[str], industry_jsic: Optional[str],
                          limit: int = 10) -> List[dict]:
    conn = get_canonical_conn()
    if conn is None:
        return []
    rows = safe_rows(
        conn,
        """
        SELECT e.raw_json
        FROM am_entities e
        WHERE e.source_topic='22_mirasapo_cases'
        LIMIT 3000
        """,
    )
    out: List[dict] = []
    for r in rows:
        try:
            raw = json.loads(r["raw_json"] or "{}")
        except Exception:
            continue
        if prefecture and raw.get("prefecture") != prefecture:
            continue
        if industry_jsic:
            ij = raw.get("industry_jsic") or ""
            if not ij.startswith(industry_jsic):
                continue
        out.append(raw)
        if len(out) >= limit:
            return out
    return out


def _industry_raw_filter(jsic_letter: Optional[str]) -> Optional[str]:
    """Map JSIC letter to a substring likely to appear in raw.industry_raw."""
    if not jsic_letter:
        return None
    mp = {
        "A": "農業", "B": "漁業", "D": "建設", "E": "製造",
        "F": "電気", "G": "情報通信", "H": "運輸", "I": "小売",
        "J": "金融", "K": "不動産", "M": "宿泊", "P": "医療",
    }
    return mp.get(jsic_letter)


def bind(slots: Dict[str, Any], cache: PrecomputedCache) -> Dict[str, Any]:
    program_id = slots.get("program_id")
    round_ = slots.get("round")
    prefecture = slots.get("prefecture")
    industry_jsic = slots.get("industry_jsic")
    notes: List[str] = []
    source_urls: List[str] = []

    hint = _resolve_hint(program_id or "")
    filters = {
        "round": round_,
        "prefecture": prefecture,
        "industry_raw": _industry_raw_filter(industry_jsic),
    }

    adoption = _fetch_adoption_facts(hint, filters) if hint else []
    stats = _fetch_acceptance_stats(program_id or "", round_)
    mirasapo = _fetch_mirasapo_cases(prefecture, industry_jsic) if (prefecture or industry_jsic) else []

    # ---- Case bullets (top 8) ----
    case_bullets: List[str] = []
    for raw in adoption[:8]:
        company = raw.get("company_name") or "(社名不明)"
        houjin = raw.get("houjin_bangou") or "-"
        pref = raw.get("prefecture") or "-"
        ind = raw.get("industry_raw") or "-"
        theme = raw.get("project_title") or "-"
        amt = raw.get("amount_granted_yen")
        amt_str = "不明" if amt is None else f"{int(amt) // 10000}万" if isinstance(amt, (int, float)) else str(amt)
        url = raw.get("source_url") or "-"
        if url not in ("-", ""):
            source_urls.append(url)
        employees = raw.get("employees") or "-"
        case_bullets.append(
            f"- {company} ({houjin}) / {pref} / {ind} / 従業員{employees}名\n"
            f"    採択額 ¥{amt_str} / 事業: {theme[:80]}\n"
            f"    根拠: {url}"
        )

    # ---- Mirasapo cases (richer profile data) ----
    similar_bullets: List[str] = []
    for raw in mirasapo[:5]:
        similar_bullets.append(
            f"- {raw.get('company_name','-')} ({raw.get('prefecture','-')} / "
            f"{raw.get('industry_name','-')} / 従業員{raw.get('employees','-')}名) — "
            f"{(raw.get('case_title') or '-')[:60]}\n    出典: {raw.get('source_url','-')}"
        )
        if raw.get("source_url"):
            source_urls.append(raw["source_url"])

    # ---- Histograms ----
    pref_counter = Counter(r.get("prefecture") or "不明" for r in adoption)
    ind_counter = Counter(r.get("industry_raw") or "不明" for r in adoption)
    pref_hist = "\n".join(
        f"- {k}: {v} 件" for k, v in pref_counter.most_common(10)
    ) or "- (該当なし)"
    ind_hist = "\n".join(
        f"- {k}: {v} 件" for k, v in ind_counter.most_common(10)
    ) or "- (該当なし)"

    # ---- Acceptance rate ----
    acceptance_rate_pct = "-"
    total_for_round = "-"
    hit_count_note = ""
    if stats:
        # pick the row matching round first if round was provided
        pick = None
        if round_:
            for s in stats:
                if s.get("round_number") == round_:
                    pick = s
                    break
        pick = pick or stats[0]
        ar = pick.get("acceptance_rate")
        if isinstance(ar, (int, float)):
            acceptance_rate_pct = f"{ar * 100:.1f}"
        total_for_round = str(pick.get("accepted") or pick.get("applicants") or "-")
        if pick.get("_source_url"):
            source_urls.append(pick["_source_url"])
        hit_count_note = (
            f"第{pick.get('round_number','?')}次 応募{pick.get('applicants','?')} "
            f"採択{pick.get('accepted','?')}"
        )

    # ---- Null amount warning ----
    null_amount_frac = 0.0
    if adoption:
        null_amount_frac = sum(1 for r in adoption if r.get("amount_granted_yen") is None) / len(adoption)

    ratio_pct = "-"
    if adoption and stats:
        total = stats[0].get("accepted")
        if isinstance(total, int) and total > 0:
            ratio_pct = f"{len(adoption) / total * 100:.1f}"

    ctx = {
        "program_name": program_id or "-",
        "round": str(round_) if round_ else "(未指定)",
        "prefecture": prefecture or "(未指定)",
        "industry_jsic": industry_jsic or "(未指定)",
        "employee_range": "(未指定)",
        "hit_count": str(len(adoption)),
        "total_for_round": total_for_round,
        "ratio_pct": ratio_pct,
        "acceptance_rate_pct": acceptance_rate_pct,
        "top_n": str(min(len(adoption), 8)),
        "case_bullets": "\n\n".join(case_bullets) or "- (05_adoption_additional に該当なし)",
        "prefecture_histogram": pref_hist,
        "industry_histogram": ind_hist,
        "similar_cases": "\n\n".join(similar_bullets) or "- (22_mirasapo_cases に該当なし)",
        "jsic_coverage_pct": "15",  # honest: most rows lack industry_jsic
        "citation_urls": "\n".join(f"- {u}" for u in list(dict.fromkeys(source_urls))[:10])
        or "- (canonical source_url 未 ingest)",
    }

    notes.append(
        f"hint={hint} adoption={len(adoption)} stats={len(stats)} mirasapo={len(mirasapo)} "
        f"null_amount={null_amount_frac:.0%}"
    )

    bound_ok = bool(adoption or stats or mirasapo)

    return {
        "bound_ok": bound_ok,
        "ctx": ctx,
        "source_urls": list(dict.fromkeys(source_urls))[:15],
        "notes": notes,
    }


register("i07_adoption_cases", bind)
