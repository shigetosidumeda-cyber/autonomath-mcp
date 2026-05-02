"""bind_i04 — 税制特例の適用期限.

Data sources (read-only):
  canonical  autonomath.db
             - am_entities record_kind='tax_measure' (282 rows across
               12_tax_incentives / 139_invoice_consumption_tax /
               140_income_tax_individual_deep / 149_corporate_tax_deep /
               150_local_taxes_detail / 26_agri_tax_deep / 84_inheritance_gift_tax_deep /
               67_business_succession_ma_deep)
             - raw_json has application_period_from/to, abolition_note,
               urgency, status, applicable_period (free text)
  precompute tax_measure_validity (legacy 12_tax_incentives only — 40 rows)

Strategy
--------
Wave-2 legacy precompute only covered 12_tax_incentives. This full implementation
scans all record_kind='tax_measure' rows and builds a validity window on the fly:

  1. Direct ISO fields: application_period_from / application_period_to
  2. Free text applicable_period (e.g. "令和7年4月1日〜令和9年3月31日開始事業年度")
     parsed via regex for 令和N年M月 / YYYY-MM-DD / YYYY年M月
  3. Fallback abolition_note / status=abolished / urgency=EXPIRED

Tax category facet is derived from tax_category field + root_law substring
(法人税 / 所得税 / 消費税 / 地方税 / 相続税・贈与税).

R8 改正大綱 signal from 07_new_program_candidates topic (same mechanism as i03).
"""
from __future__ import annotations

import json
import re
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

from .bind_registry import get_canonical_conn, register, safe_rows
from .precompute import PrecomputedCache, canonical_program_id


TODAY = date(2026, 4, 23)


# ---------------------------------------------------------------------------
# Tax category classifier (based on root_law / tax_category / source_topic)
# ---------------------------------------------------------------------------

_TAX_CATEGORY_RULES: List[Tuple[str, List[str]]] = [
    ("法人税", ["法人税", "租税特別措置法 第42条", "149_corporate_tax_deep"]),
    ("所得税", ["所得税", "140_income_tax_individual_deep", "措法第41"]),
    ("消費税", ["消費税", "139_invoice_consumption_tax", "インボイス"]),
    ("地方税", ["地方税", "固定資産税", "150_local_taxes_detail", "事業税", "住民税"]),
    ("相続税・贈与税", ["相続税", "贈与税", "84_inheritance_gift_tax_deep",
                      "事業承継税制", "67_business_succession_ma_deep"]),
    ("農業税制", ["26_agri_tax_deep", "農地所有適格法人"]),
]


def _classify_tax_category(raw: dict, source_topic: str) -> str:
    t = raw.get("tax_category") or ""
    if t:
        return t
    haystack = " ".join([
        str(raw.get("root_law") or ""),
        str(raw.get("statutory_basis") or ""),
        str(raw.get("category") or ""),
        str(source_topic or ""),
    ])
    for label, kws in _TAX_CATEGORY_RULES:
        for kw in kws:
            if kw in haystack:
                return label
    return "(税目未判別)"


# ---------------------------------------------------------------------------
# Date parsing — handles ISO, 令和N年M月D日, YYYY年M月D日, YYYY-MM-DD
# ---------------------------------------------------------------------------

_ISO_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
_REIWA_RE = re.compile(r"令和\s*(\d+)\s*年\s*(\d+)?\s*月?\s*(\d+)?")
_WESTERN_RE = re.compile(r"(\d{4})\s*年\s*(\d+)?\s*月?\s*(\d+)?")


def _to_date(s: Any) -> Optional[date]:
    if s in (None, ""):
        return None
    s = str(s)
    m = _ISO_RE.search(s)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except (ValueError, TypeError):
            pass
    m = _REIWA_RE.search(s)
    if m:
        try:
            r = int(m.group(1))
            month = int(m.group(2)) if m.group(2) else 1
            day = int(m.group(3)) if m.group(3) else 1
            # 令和1=2019 -> year = 2018 + r
            return date(2018 + r, month, day)
        except (ValueError, TypeError):
            pass
    m = _WESTERN_RE.search(s)
    if m:
        try:
            year = int(m.group(1))
            month = int(m.group(2)) if m.group(2) else 1
            day = int(m.group(3)) if m.group(3) else 1
            if 1900 <= year <= 2100:
                return date(year, month, day)
        except (ValueError, TypeError):
            pass
    return None


def _parse_period_text(txt: Optional[str]) -> Tuple[Optional[date], Optional[date]]:
    """Parse 'X年M月〜Y年N月' or 'X年度以後' -> (from, to)."""
    if not txt:
        return None, None
    # Split on common separators
    # "令和7年4月1日〜令和9年3月31日開始事業年度"
    m = re.search(r"(.*?)[〜~ー—−–]\s*(.+)", txt)
    if m:
        a = _to_date(m.group(1))
        b = _to_date(m.group(2))
        return a, b
    # Single-end phrases like "令和9年3月31日まで"
    if "まで" in txt or "末まで" in txt:
        b = _to_date(txt)
        return None, b
    # "令和7年4月1日以後開始事業年度"  -> start only
    if "以後" in txt or "以降" in txt:
        a = _to_date(txt)
        return a, None
    return None, None


# ---------------------------------------------------------------------------
# Status + days_remaining derivation
# ---------------------------------------------------------------------------

def _derive_status(
    frm: Optional[date],
    to: Optional[date],
    raw: dict,
    as_of: date = TODAY,
) -> Tuple[str, Optional[int]]:
    # honour explicit status/urgency fields first
    status_hint = (raw.get("status") or "").lower()
    urgency = (raw.get("urgency") or "").upper()
    if status_hint == "abolished" or urgency == "EXPIRED" or "廃止" in (raw.get("name") or ""):
        return "expired", 0
    if to and as_of > to:
        return "expired", 0
    if frm and as_of < frm:
        return "not_yet_active", (frm - as_of).days
    if frm and to:
        return "active", (to - as_of).days
    if to:
        # from unknown, to known -> assume active if in future
        if as_of <= to:
            return "active", (to - as_of).days
        return "expired", 0
    if frm:
        return "active", None
    return "unknown", None


# ---------------------------------------------------------------------------
# Row fetch + selection
# ---------------------------------------------------------------------------

_TAX_TOPICS = (
    "12_tax_incentives",
    "139_invoice_consumption_tax",
    "140_income_tax_individual_deep",
    "149_corporate_tax_deep",
    "150_local_taxes_detail",
    "26_agri_tax_deep",
    "84_inheritance_gift_tax_deep",
    "67_business_succession_ma_deep",
)


def _fetch_candidates(measure_id_hint: Optional[str]) -> List[dict]:
    conn = get_canonical_conn()
    if conn is None:
        return []
    topics_q = ",".join("?" * len(_TAX_TOPICS))
    if measure_id_hint:
        rows = safe_rows(
            conn,
            f"""
            SELECT e.canonical_id, e.primary_name, e.source_url, e.source_topic, e.raw_json
            FROM am_entities e
            WHERE e.record_kind='tax_measure'
              AND e.source_topic IN ({topics_q})
              AND e.primary_name LIKE ?
            LIMIT 40
            """,
            tuple(_TAX_TOPICS) + (f"%{measure_id_hint}%",),
        )
    else:
        rows = safe_rows(
            conn,
            f"""
            SELECT e.canonical_id, e.primary_name, e.source_url, e.source_topic, e.raw_json
            FROM am_entities e
            WHERE e.record_kind='tax_measure'
              AND e.source_topic IN ({topics_q})
            LIMIT 400
            """,
            tuple(_TAX_TOPICS),
        )
    out: List[dict] = []
    for r in rows:
        try:
            raw = json.loads(r["raw_json"] or "{}")
        except Exception:
            raw = {}
        out.append({
            "canonical_id": r["canonical_id"],
            "primary_name": r["primary_name"],
            "source_url": r["source_url"],
            "source_topic": r["source_topic"],
            "raw": raw,
        })
    return out


def _pick_best(candidates: List[dict], query_hint: Optional[str]) -> Optional[dict]:
    if not candidates:
        return None
    if not query_hint:
        return candidates[0]
    q = query_hint
    # Score = len of substring match, prefer non-廃止
    scored: List[Tuple[int, dict]] = []
    for c in candidates:
        nm = c["primary_name"] or ""
        score = 0
        stripped_q = canonical_program_id(q)
        if stripped_q and stripped_q in nm:
            score += len(stripped_q) * 2
        if q in nm:
            score += len(q)
        # penalize 廃止 rows (user likely wants the current measure)
        if "廃止" in nm or (c["raw"].get("status") or "") == "abolished":
            score -= 5
        scored.append((score, c))
    scored.sort(key=lambda t: -t[0])
    return scored[0][1] if scored[0][0] > 0 else candidates[0]


# ---------------------------------------------------------------------------
# R8 改正大綱 signal
# ---------------------------------------------------------------------------

def _fetch_r8_signals(measure_name: str) -> List[dict]:
    """Look for matching 07_new_program_candidates or 149 rows that mention
    令和8 / R8 amendment concerning this measure."""
    conn = get_canonical_conn()
    if conn is None or not measure_name:
        return []
    # Perf: narrow candidate set via FTS5 trigram on the measure_name prefix
    # before applying the topical + raw_json LIKE filters. LIKE is preserved
    # as a verifier so set equivalence is unchanged. For measure_name shorter
    # than 3 chars we keep the legacy LIKE-only path (trigram can't tokenize).
    kw = measure_name[:10]
    if len(kw) >= 3:
        rows = safe_rows(
            conn,
            """
            WITH kw AS (
              SELECT canonical_id FROM am_entities_fts
              WHERE am_entities_fts MATCH ?
            )
            SELECT e.primary_name, e.raw_json, e.source_url, e.source_topic
            FROM am_entities e
            JOIN kw ON kw.canonical_id = e.canonical_id
            WHERE (e.source_topic='07_new_program_candidates'
                   OR e.raw_json LIKE '%令和8年度税制改正%'
                   OR e.raw_json LIKE '%令和8年度改正%')
              AND (e.primary_name LIKE ? OR e.raw_json LIKE ?)
            LIMIT 20
            """,
            (f'"{kw}"', f"%{kw}%", f"%{kw}%"),
        )
    else:
        rows = safe_rows(
            conn,
            """
            SELECT e.primary_name, e.raw_json, e.source_url, e.source_topic
            FROM am_entities e
            WHERE (e.source_topic='07_new_program_candidates'
                   OR e.raw_json LIKE '%令和8年度税制改正%'
                   OR e.raw_json LIKE '%令和8年度改正%')
              AND (e.primary_name LIKE ? OR e.raw_json LIKE ?)
            LIMIT 20
            """,
            (f"%{kw}%", f"%{kw}%"),
        )
    out: List[dict] = []
    for r in rows:
        try:
            raw = json.loads(r["raw_json"] or "{}")
        except Exception:
            raw = {}
        out.append({
            "primary_name": r["primary_name"],
            "excerpt": (raw.get("description") or raw.get("policy_background_excerpt")
                        or raw.get("source_excerpt") or "")[:120],
            "source_url": r["source_url"],
            "source_topic": r["source_topic"],
        })
    return out


# ---------------------------------------------------------------------------
# Extract dates from a chosen candidate
# ---------------------------------------------------------------------------

def _extract_dates(raw: dict) -> Tuple[Optional[date], Optional[date], str, str]:
    """Return (from, to, from_raw_text, to_raw_text)."""
    frm_txt = raw.get("application_period_from") or ""
    to_txt = raw.get("application_period_to") or ""
    frm = _to_date(frm_txt)
    to = _to_date(to_txt)
    if frm or to:
        return frm, to, str(frm_txt), str(to_txt)

    # Fall back to applicable_period free text
    ap = raw.get("applicable_period") or raw.get("application_period") or ""
    a, b = _parse_period_text(ap)
    return a, b, ap, ap


# ---------------------------------------------------------------------------
# Bind entrypoint
# ---------------------------------------------------------------------------

def bind(slots: Dict[str, Any], cache: PrecomputedCache) -> Dict[str, Any]:
    measure_id = slots.get("measure_id")
    as_of = TODAY
    notes: List[str] = []
    source_urls: List[str] = []

    # Build a hint string. measure_id may be:
    #   - a precompute.tax_measure_validity key (e.g. "tax_011")
    #   - a canonical display name
    #   - None (keyword fallback in match.extract_slots)
    hint_name: Optional[str] = None
    precomp = cache.tax_measure_validity.get(measure_id or "") or {}
    if precomp.get("name"):
        hint_name = precomp["name"]

    candidates = _fetch_candidates(hint_name)
    best = _pick_best(candidates, hint_name)

    if not best:
        # Broaden: query-like keyword fallback via the precompute index
        candidates = _fetch_candidates(None)
        if hint_name:
            best = _pick_best(candidates, hint_name)
        else:
            best = None

    if not best:
        return {
            "bound_ok": False,
            "ctx": {
                "measure_name": "(未解決)",
                "tax_category": "(税目未判別)",
                "root_law": "(未指定)",
                "period_from": "-",
                "period_to": "-",
                "status": "unknown",
                "period_to_label": "期間データ欠落",
                "days_remaining": "-",
                "abolition_date": "(廃止情報なし)",
                "successor_measure": "(後継制度情報未ingest)",
                "transition_rule": "(経過措置 未ingest)",
                "latest_fy": "8",
                "latest_revision_note": "(R8改正大綱signal未検出)",
                "extension_signal": "(延長公表なし / scrape未)",
                "proactive_warnings": "- measure_id 未解決 → 候補名 指定推奨",
                "citation_urls": "- (DB hit なし)",
            },
            "source_urls": [],
            "notes": ["no tax_measure candidate matched"],
        }

    raw = best["raw"]
    frm, to, frm_txt, to_txt = _extract_dates(raw)
    status, days_remaining = _derive_status(frm, to, raw, as_of)

    if best.get("source_url"):
        source_urls.append(best["source_url"])
    if raw.get("official_url"):
        source_urls.append(raw["official_url"])
    if raw.get("source_url"):
        source_urls.append(raw["source_url"])

    root_law = raw.get("root_law") or raw.get("statutory_basis") or "-"
    tax_category = _classify_tax_category(raw, best["source_topic"])

    # abolition signal
    abolition_date = raw.get("abolition_note") or "-"
    if not abolition_date or abolition_date == "-":
        if to and as_of > to:
            abolition_date = f"(適用期限 {to.isoformat()} 到達済み)"
        elif "廃止" in (best["primary_name"] or ""):
            abolition_date = "(廃止と名称に明記)"
        else:
            abolition_date = "(廃止予定なし/未公表)"

    # R8 改正大綱 signals
    r8_signals = _fetch_r8_signals(best["primary_name"])
    r8_bullets: List[str] = []
    for s in r8_signals[:3]:
        r8_bullets.append(f"  - {s['primary_name'][:50]}: {s['excerpt']}")
        if s.get("source_url"):
            source_urls.append(s["source_url"])
    latest_revision_note = "\n".join(r8_bullets) or "(R8改正大綱 該当記載未検出)"

    # Extension signal: urgency + explicit 延長 wording in description
    desc = (raw.get("description") or raw.get("source_excerpt") or "")
    extension_signal = "(延長公表なし)"
    if "延長" in desc:
        extension_signal = "延長言及あり (description/source_excerpt)"
    elif raw.get("urgency") == "FY2026_EXPIRING":
        extension_signal = "FY2026_EXPIRING — 延長/廃止判断待ち"
    elif raw.get("urgency") == "EXPIRED":
        extension_signal = "既に期限到達 (EXPIRED)"

    # Proactive warnings
    warnings: List[str] = []
    if status == "active" and isinstance(days_remaining, int) and days_remaining < 365:
        warnings.append(f"🔥 期限まで残 {days_remaining} 日 — 駆込み対応の準備")
    if abolition_date not in ("(廃止予定なし/未公表)", "-") and abolition_date:
        warnings.append(f"⚠ 廃止メモ: {abolition_date}")
    if status == "expired":
        warnings.append("🛑 既に期限切れ — 後継制度または延長の確認必要")
    if status == "not_yet_active":
        warnings.append(f"⏳ 開始 {days_remaining} 日後 — 施行待ち")
    if raw.get("urgency"):
        warnings.append(f"📅 urgency={raw['urgency']}")

    ctx = {
        "measure_name": best["primary_name"],
        "tax_category": tax_category,
        "root_law": root_law,
        "period_from": frm_txt or (frm.isoformat() if frm else "-"),
        "period_to": to_txt or (to.isoformat() if to else "-"),
        "status": status,
        "period_to_label": {
            "active": "現在適用中",
            "expired": "期限切れ",
            "not_yet_active": "未開始",
            "unknown": "期間データ欠落",
        }.get(status, status),
        "days_remaining": str(days_remaining) if days_remaining is not None else "-",
        "abolition_date": abolition_date,
        "successor_measure": (
            "廃止: 後継なし (戦略分野国内生産促進税制等が一部代替)"
            if "廃止" in (best["primary_name"] or "") and "DX" in (best["primary_name"] or "")
            else "(後継情報 i03 で確認推奨)"
        ),
        "transition_rule": raw.get("transition_rule") or raw.get("経過措置") or "(経過措置 未ingest)",
        "latest_fy": "8",
        "latest_revision_note": latest_revision_note,
        "extension_signal": extension_signal,
        "proactive_warnings": "\n".join(f"- {w}" for w in warnings) or "- 特記事項なし",
        "citation_urls": "\n".join(f"- {u}" for u in list(dict.fromkeys(source_urls))[:10])
        or "- (URL未ingest)",
    }

    notes.append(
        f"candidates={len(candidates)} picked='{best['primary_name']}' "
        f"status={status} days_remaining={days_remaining} r8_signals={len(r8_signals)} "
        f"tax_category={tax_category}"
    )

    return {
        "bound_ok": True,
        "ctx": ctx,
        "source_urls": list(dict.fromkeys(source_urls))[:10],
        "notes": notes,
    }


register("i04_tax_measure_sunset", bind)
