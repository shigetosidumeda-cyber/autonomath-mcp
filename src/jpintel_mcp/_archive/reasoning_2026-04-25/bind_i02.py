"""bind_i02 — ある制度の申請締切・必要書類.

Data sources (read-only):
  canonical  autonomath.db
             - am_entities where source_topic='04_program_documents'
               -> form_url_direct / form_name / form_type / signature_required
             - am_entity_facts raw.application_deadline / raw.application_period
             - am_entity_facts raw.required_documents
  precompute precompute.program_prereq_closure, program_incompat_closure

Strategy
--------
program_id is the canonical program-name string (e.g. "ものづくり補助金").
We fuzzy-lookup all primary_name rows containing that substring (so '23次締切'
and '第13回' variants all come in) and bucket them:
  - 04_program_documents rows -> doc bullets + form URLs
  - any row with raw.application_deadline -> schedule
  - any row with raw.required_documents  -> required doc list (free text)

We never invent a URL. When 04_program_documents has no hit we say so.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from .bind_registry import get_canonical_conn, register, safe_rows
from .precompute import PrecomputedCache


_DOC_TYPE_KEYWORDS = {
    "公募要領": ["公募要領"],
    "申請様式": ["様式", "申請書"],
    "QA": ["QA", "Q&A", "質疑"],
    "記入例": ["記入例", "参考様式"],
    "完了報告書": ["完了報告"],
    "交付規程": ["交付規程"],
}


def _canonical_match_rows(program_id: str) -> List[dict]:
    """Best-effort: return all am_entities where primary_name contains the
    program_id, attached with their facts (schedule, required docs).
    Excludes exclusion_rules rows whose primary_name is a '× exclude' label
    rather than the program itself."""
    conn = get_canonical_conn()
    if conn is None or not program_id:
        return []
    rows = safe_rows(
        conn,
        """
        SELECT e.canonical_id, e.primary_name, e.source_topic, e.source_url,
               e.raw_json
        FROM am_entities e
        WHERE e.primary_name LIKE ?
          AND e.primary_name NOT LIKE '% × %'
          AND e.source_topic NOT IN ('03_exclusion_rules')
        ORDER BY e.source_topic, e.canonical_id
        LIMIT 200
        """,
        (f"%{program_id}%",),
    )
    return [dict(r) for r in rows]


def _fetch_facts_bulk(entity_ids: List[str]) -> Dict[str, Dict[str, str]]:
    """Return {entity_id: {field_name: field_value_text}} for the given ids."""
    conn = get_canonical_conn()
    if conn is None or not entity_ids:
        return {}
    chunks: Dict[str, Dict[str, str]] = {}
    # Chunk to avoid SQLite's 999-parameter limit
    CHUNK = 500
    for i in range(0, len(entity_ids), CHUNK):
        batch = entity_ids[i : i + CHUNK]
        qmarks = ",".join("?" * len(batch))
        rows = safe_rows(
            conn,
            f"""
            SELECT entity_id, field_name, field_value_text
            FROM am_entity_facts
            WHERE entity_id IN ({qmarks})
              AND field_name IN (
                'raw.application_deadline', 'raw.application_period',
                'raw.application_period_r7', 'raw.application_window',
                'raw.application_window_r7', 'raw.application_window_2025',
                'raw.required_documents', 'raw.application_url',
                'amount_max_yen', 'raw.subsidy_rate',
                'authority_raw', 'raw.authority_level', 'raw.prefecture',
                'raw.round_label', 'raw.round_number'
              )
            """,
            tuple(batch),
        )
        for r in rows:
            chunks.setdefault(r["entity_id"], {})[r["field_name"]] = r["field_value_text"]
    return chunks


def _doc_bullet_from_raw(raw: dict) -> Optional[str]:
    """Given a raw_json for a 04_program_documents row, render the doc line."""
    form_name = raw.get("form_name")
    if not form_name:
        return None
    form_type = raw.get("form_type") or ""
    form_format = raw.get("form_format") or ""
    pages = raw.get("pages")
    url = raw.get("form_url_direct") or raw.get("source_url") or ""
    sig = raw.get("signature_required")
    sig_txt = "true" if sig else "false"
    # pick a doc_type label
    dt = "その他"
    for label, kws in _DOC_TYPE_KEYWORDS.items():
        if any(k in form_name for k in kws):
            dt = label
            break
    pages_txt = f"{pages}p" if pages else ""
    return (
        f"- [{dt}] {form_name} ({form_format}{', ' + pages_txt if pages_txt else ''}, "
        f"形式={form_type}, 署名要={sig_txt})\n    URL: {url}"
    )


def _first_non_null(*vals: Any) -> Optional[str]:
    for v in vals:
        if v:
            return str(v)
    return None


def bind(slots: Dict[str, Any], cache: PrecomputedCache) -> Dict[str, Any]:
    program_id = slots.get("program_id")
    requested_round = slots.get("round")
    requested_doctype = slots.get("doc_type")

    notes: List[str] = []
    source_urls: List[str] = []

    if not program_id:
        return {
            "bound_ok": False,
            "ctx": {
                "program_name": "(未解決)",
                "round_label": "(回次未指定)",
                "doc_bullets": "- (program_id 未指定 — DB 検索不可)",
                "form_urls": "- (同上)",
            },
            "source_urls": [],
            "notes": ["program_id empty"],
        }

    rows = _canonical_match_rows(program_id)
    ent_ids = [r["canonical_id"] for r in rows]
    facts = _fetch_facts_bulk(ent_ids)

    # Bucket 04_program_documents rows vs others
    doc_rows: List[dict] = []
    meta_rows: List[dict] = []
    for r in rows:
        if r["source_topic"] == "04_program_documents":
            doc_rows.append(r)
        else:
            meta_rows.append(r)

    # ---- Documents ----
    doc_bullets: List[str] = []
    form_urls: List[str] = []
    for r in doc_rows:
        try:
            raw = json.loads(r["raw_json"] or "{}")
        except Exception:
            raw = {}
        bullet = _doc_bullet_from_raw(raw)
        if bullet:
            doc_bullets.append(bullet)
        u = raw.get("form_url_direct")
        if u:
            form_urls.append(u)
        if r["source_url"]:
            source_urls.append(r["source_url"])

    # Doc-type filter
    if requested_doctype:
        keep = [b for b in doc_bullets if f"[{requested_doctype}]" in b]
        if keep:
            doc_bullets = keep

    # ---- Schedule + required_documents from meta rows ----
    deadline = None
    period = None
    required_docs_text = None
    authority = None
    authority_level = None
    prefecture = None
    round_label = None
    chosen_meta_url = None
    for r in meta_rows:
        f = facts.get(r["canonical_id"], {})
        deadline = deadline or f.get("raw.application_deadline")
        period = period or _first_non_null(
            f.get("raw.application_window_r7"),
            f.get("raw.application_period_r7"),
            f.get("raw.application_window_2025"),
            f.get("raw.application_window"),
            f.get("raw.application_period"),
        )
        required_docs_text = required_docs_text or f.get("raw.required_documents")
        authority = authority or f.get("authority_raw")
        authority_level = authority_level or f.get("raw.authority_level")
        prefecture = prefecture or f.get("raw.prefecture")
        rl = f.get("raw.round_label")
        if rl and not round_label:
            round_label = rl
        if r["source_url"] and not chosen_meta_url:
            chosen_meta_url = r["source_url"]
            source_urls.append(r["source_url"])

    # precompute closures (prereq / incompat)
    # canonicalize via precompute helper
    from .precompute import canonical_program_id
    pid_canon = canonical_program_id(program_id)
    prereq = cache.program_prereq_closure.get(pid_canon, []) or cache.program_prereq_closure.get(program_id, [])
    incompat = cache.program_incompat_closure.get(pid_canon, []) or cache.program_incompat_closure.get(program_id, [])

    # ---- Final ctx ----
    ctx = {
        "program_name": program_id,
        "round_label": (
            f"第{requested_round}回" if requested_round
            else (round_label or "(回次未指定)")
        ),
        "authority": authority or "(authority 未 ingest)",
        "authority_level": authority_level or "(未分類)",
        "root_law": "(根拠法令は law_ref fact 経由 — i03 で探索)",
        "window_start": "(公募開始日 未 ingest)",
        "window_end": deadline or "(締切未 ingest)",
        "days_left": "(締切日 ingest 待ち — window_end が確定次第 自動算出)",
        "award_date": "(採択発表予定 未 ingest)",
        "grant_date": "(交付決定 未 ingest)",
        "doc_bullets": "\n".join(doc_bullets) or "- (04_program_documents に該当行なし)",
        "form_urls": "\n".join(f"- {u}" for u in dict.fromkeys(form_urls)) or "- (form_url_direct 未 ingest)",
        "prev_round": "(前回回次 未 ingest)",
        "diff_from_prev_round": "- (revision_history[] 未整備)",
        "prerequisite_certifications": "\n".join(f"- {c}" for c in prereq) or "- (前提認定なし)",
        "citation_urls": "\n".join(f"- {u}" for u in list(dict.fromkeys(source_urls))[:10])
        or "- (canonical source_url 未 ingest)",
    }

    # Extra raw-text facts that are user-useful (not in the skeleton but
    # exposed via notes for LLM readability)
    if required_docs_text:
        ctx["doc_bullets"] = (
            ctx["doc_bullets"]
            + "\n\n  [am_entity_facts.raw.required_documents 抜粋]\n  "
            + required_docs_text
        )
    if period:
        ctx["window_start"] = period  # raw text span - LLM can parse
    if incompat:
        ctx["incompat_roster"] = "\n".join(f"  - {p}" for p in incompat[:10])

    bound_ok = bool(doc_bullets or deadline or period or required_docs_text)
    if not bound_ok:
        notes.append(f"no canonical hit for program_id={program_id}")
    else:
        notes.append(
            f"doc_rows={len(doc_rows)} meta_rows={len(meta_rows)} "
            f"prereq={len(prereq)} incompat={len(incompat)}"
        )

    return {
        "bound_ok": bound_ok,
        "ctx": ctx,
        "source_urls": list(dict.fromkeys(source_urls))[:20],
        "notes": notes,
    }


register("i02_program_deadline_documents", bind)
