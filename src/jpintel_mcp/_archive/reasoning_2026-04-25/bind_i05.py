"""bind_i05 — ある認定の取得方法・要件.

Data sources (read-only):
  canonical  autonomath.db  (am_entities record_kind='certification' raw_json has
                             requirements / benefits / linked_subsidies / fee / days)
  precompute certification_unlocks (cert -> programs)

Strategy
--------
09_certification_programs is already well-structured in raw_json. For the user's
certification_id (keyword match), we just parse the raw_json and surface:
  - requirements      -> 要件確認 bullets
  - benefits_after... -> 認定取得で開くドア (税制/融資/保証)
  - linked_subsidies  -> unlocked programs (also available via precompute)
  - application_fee_yen / processing_days_median
  - certifying_org / authority / root_law
"""
from __future__ import annotations

import json
from typing import Any, Dict, List

from .bind_registry import get_canonical_conn, register, safe_rows
from .precompute import PrecomputedCache, canonical_program_id


def _cert_rows(cert_name: str) -> List[dict]:
    conn = get_canonical_conn()
    if conn is None or not cert_name:
        return []
    rows = safe_rows(
        conn,
        """
        SELECT e.canonical_id, e.primary_name, e.source_url, e.raw_json
        FROM am_entities e
        WHERE e.record_kind='certification'
          AND (e.primary_name LIKE ? OR e.raw_json LIKE ?)
        LIMIT 20
        """,
        (f"%{cert_name}%", f"%{cert_name}%"),
    )
    out: List[dict] = []
    for r in rows:
        # Filter obvious false positives: organization names (bank/accounting firm)
        # that are misclassified as record_kind='certification' during ingest.
        name = r["primary_name"] or ""
        if any(suffix in name for suffix in ("株式会社", "有限会社", "監査法人")) \
                and not any(kw in name for kw in ("認定", "認証", "認可", "計画")):
            continue
        out.append(dict(r))
    return out


def _parse_raw(raw_json: str) -> dict:
    try:
        return json.loads(raw_json or "{}") or {}
    except Exception:
        return {}


def _fmt_list(vals: Any, bullet: str = "-") -> str:
    if not vals:
        return f"{bullet} (記載なし)"
    if isinstance(vals, str):
        vals = [vals]
    return "\n  ".join(f"{bullet} {v}" for v in vals[:20])


def bind(slots: Dict[str, Any], cache: PrecomputedCache) -> Dict[str, Any]:
    cert_id = slots.get("certification_id")
    notes: List[str] = []
    source_urls: List[str] = []

    if not cert_id:
        return {
            "bound_ok": False,
            "ctx": {"cert_name": "(未指定)"},
            "source_urls": [],
            "notes": ["no certification_id"],
        }

    rows = _cert_rows(cert_id)
    if not rows:
        # Partial keyword fallback for common mis-spellings
        for alt in ("計画", "認定", "優良法人"):
            rows = _cert_rows(alt) if cert_id in alt else []
            if rows:
                break

    # Ranking: prefer rows whose primary_name contains cert_id directly,
    # then shortest-title (most specific) among those; fallback to longest.
    def _rank(r: dict) -> tuple:
        name = r.get("primary_name") or ""
        exact_in_name = int(cert_id in name)
        # 1st key: exact-in-name (desc), 2nd key: shorter name (asc), 3rd: content size (desc)
        return (-exact_in_name, len(name), -len(r.get("raw_json") or ""))
    rows.sort(key=_rank)
    best = rows[0] if rows else None

    if not best:
        notes.append(f"no canonical row for cert={cert_id}")
        return {
            "bound_ok": False,
            "ctx": {"cert_name": cert_id},
            "source_urls": [],
            "notes": notes,
        }

    raw = _parse_raw(best["raw_json"])
    if best.get("source_url"):
        source_urls.append(best["source_url"])
    for key in ("official_url", "source_url", "asiagap_gfsi_url"):
        url = raw.get(key)
        if url:
            source_urls.append(url)

    # Primary schema (09_certification_programs: structured by Wave-1 ingest).
    requirements = raw.get("requirements") or []
    benefits = raw.get("benefits_after_certification") or []
    linked = raw.get("linked_subsidies") or []
    fee = raw.get("application_fee_yen")
    days = raw.get("processing_days_median")
    certifying_org = raw.get("certifying_org") or raw.get("authority") or raw.get("issuer")
    parent_ministry = raw.get("authority") or raw.get("parent_ministry") or raw.get("issuer")
    root_law = raw.get("root_law") or raw.get("legal_basis")

    # --- Alternate schema rescue (fallback-only; still rule-based, no LLM) ---
    # Some certification rows (GAP, えるぼし, くるみん, エコアクション21 etc.)
    # were ingested with `issuer`/`summary`/`certification_types` keys instead
    # of the structured requirements[] schema. We promote those to the expected
    # slots by regular expression over the summary text, so bound_ok turns True
    # for the broader cert catalogue.
    summary_text = raw.get("summary") or raw.get("source_excerpt") or raw.get("description") or ""
    if not requirements and summary_text:
        # Promote: look for 「要件」「対象」「基準」sentences from the summary.
        req_candidates: List[str] = []
        for marker in ("要件", "基準", "対象事業者", "対象者", "条件", "適用対象"):
            # find marker and the clause that follows until the next 。
            idx = summary_text.find(marker)
            if idx >= 0:
                tail = summary_text[idx: idx + 120]
                stop = tail.find("。")
                if stop > 0:
                    tail = tail[: stop + 1]
                req_candidates.append(tail.strip())
        # Also promote any certification_types keys (JGAP/ASIAGAP/...) as reqs
        cert_types = raw.get("certification_types") or {}
        if isinstance(cert_types, dict):
            for k, v in list(cert_types.items())[:6]:
                req_candidates.append(f"{k}: {v}")
        if req_candidates:
            requirements = req_candidates

    if not benefits and summary_text:
        # Promote "メリット/恩恵/ポイント" sentences
        ben_candidates: List[str] = []
        for marker in ("メリット", "恩恵", "インセンティブ", "加点", "税制優遇", "融資"):
            idx = summary_text.find(marker)
            if idx >= 0:
                tail = summary_text[idx: idx + 120]
                stop = tail.find("。")
                if stop > 0:
                    tail = tail[: stop + 1]
                ben_candidates.append(tail.strip())
        if ben_candidates:
            benefits = ben_candidates

    # Normalize None -> friendly default
    if not certifying_org:
        certifying_org = "(未記載)"
    if not parent_ministry:
        parent_ministry = "(上位省庁 未記載)"
    if not root_law:
        root_law = "(根拠法令 未記載)"

    # precompute unlocks — canonicalized name lookup
    pid_canon = canonical_program_id(best["primary_name"])
    unlocked_from_pre = cache.certification_unlocks.get(pid_canon, [])

    # Merge unlocked lists
    unlocked_merged: List[str] = []
    for v in list(linked) + list(unlocked_from_pre):
        s = str(v)
        if s not in unlocked_merged:
            unlocked_merged.append(s)

    ctx = {
        "cert_name": best["primary_name"],
        "root_law": root_law,
        "certifying_org": certifying_org,
        "parent_ministry": parent_ministry,
        "requirements_bullets": _fmt_list(requirements),
        "plan_pages": "(目安は認定ごとに異なる — 5〜15ページが目安)",
        "plan_sections": "(計画書記載項目は official_url の申請要領参照)",
        "pre_consult_window": f"{certifying_org} 窓口 / 地方経済産業局",
        "submission_target": certifying_org,
        "attached_docs": "(公募要領参照; 追加書類は i02 で program_id 指定)",
        "application_fee_yen": str(fee) if fee is not None else "不明",
        "processing_days_median": str(days) if days is not None else "不明",
        "validity_period": (
            raw.get("validity_period") or "(認定ごとに異なる — 3〜5年が目安)"
        ),
        "unlocked_programs_bullets": "\n".join(f"- {p}" for p in unlocked_merged[:15])
        or "- (linked_subsidies 未収録)",
        "parallel_certs": (
            "- 経営力向上計画 (中小機構) — 設備投資時に有効\n"
            "- 先端設備等導入計画 (市町村) — 固定資産税 3年間 1/2 以下"
        ),
        "renewal_rule": raw.get("renewal_rule") or "(更新規程は official_url 参照)",
        "citation_urls": "\n".join(f"- {u}" for u in list(dict.fromkeys(source_urls)))
        or "- (URL 未 ingest)",
    }

    notes.append(
        f"cert='{best['primary_name']}' req={len(requirements)} "
        f"benefits={len(benefits)} linked={len(linked)} "
        f"unlocks_pre={len(unlocked_from_pre)}"
    )

    return {
        "bound_ok": True,
        "ctx": ctx,
        "source_urls": list(dict.fromkeys(source_urls))[:10],
        "notes": notes,
    }


register("i05_certification_howto", bind)
