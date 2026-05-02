"""bind_i09 — 事業承継 / 廃業時の制度.

Data sources (read-only):
  canonical  autonomath.db
             - 67_business_succession_ma_deep (20 rows) - M&A 補助金、承継税制
             - 84_inheritance_gift_tax_deep (40 rows) - 相続税/贈与税 特例
             - 22_mirasapo_cases (2,286 rows) filtered by 承継/廃業 kws
             - 08_loan_programs (109 rows) filtered by succession-related target
             - record_kind='tax_measure' where name contains 事業承継/相続/贈与
  precompute tax_measure_validity, program_compat_closure

Strategy
--------
Given slots["lifecycle_stage"] (親族内承継 / 第三者承継_MA買手 / MA売手 /
従業員承継 / 廃業_再チャレンジ / 廃業_清算のみ), we filter across all three
sources and emit bucketed bullets:

  1. Subsidies: 67 + 22_mirasapo + precompute.compat keywords
  2. Tax measures: 67 + 84 + tax_measure_validity filtered by 事業承継/相続/贈与
     NB: 事業承継税制 特例措置 is a HARD 令和9年度末 deadline (令和9=2027).
  3. Loans: 08_loan_programs where target_conditions mentions 承継/事業引継
  4. Advisor recommendations: lifecycle-specific

Stacking pattern + advisor window + 期限切れ迫る制度 are tailored to lifecycle.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List

from .bind_registry import get_canonical_conn, register, safe_rows
from .precompute import PrecomputedCache


# ---------------------------------------------------------------------------
# Lifecycle -> keyword filter + advisory text
# ---------------------------------------------------------------------------

LIFECYCLE_FILTERS: Dict[str, Dict[str, Any]] = {
    "親族内承継": {
        "subsidy_kws": ["事業承継", "引継ぎ", "承継"],
        "tax_kws": ["事業承継税制", "贈与税", "相続税", "納税猶予"],
        "loan_kws": ["事業承継", "引継ぎ"],
        "advisor": "- 税理士 (贈与税/相続税申告) + 司法書士 (株式名義変更/登記)\n- 中小機構 事業承継相談窓口 (無料)",
        "stack_example": (
            "- 事業承継・M&A補助金 事業承継促進枠 (¥800万〜1000万) + "
            "法人版事業承継税制 (特例措置: 贈与税・相続税 100%猶予/免除)"
        ),
        "timing_warning": (
            "- 法人版事業承継税制 特例措置: 令和9年度末 (2027-03-31) までに "
            "特例承継計画 提出必須。提出遅れ = 特例不適用"
        ),
    },
    "第三者承継_MA買手": {
        "subsidy_kws": ["事業承継", "M&A", "引継ぎ", "買い手"],
        "tax_kws": ["経営資源集約化税制", "事業再編", "損失準備金",
                    "中小企業事業再編投資損失準備金"],
        "loan_kws": ["M&A", "買収", "事業譲受"],
        "advisor": "- 税理士 + 弁護士 (M&A契約) + 金融機関 + M&Aアドバイザー",
        "stack_example": (
            "- 事業承継・M&A補助金 専門家活用枠 買い手 (¥600万, DD費用+200万) "
            "+ 中小企業事業再編投資損失準備金 (70%損金算入) + 制度融資"
        ),
        "timing_warning": (
            "- DD費用 (財務/法務) は補助対象 + 損金算入可能。M&A実行前に"
            "事業承継・M&A補助金 申請必須 (事後申請不可)"
        ),
    },
    "第三者承継_MA売手": {
        "subsidy_kws": ["事業承継", "M&A", "引継ぎ", "売り手"],
        "tax_kws": ["譲渡所得", "個人版事業承継税制"],
        "loan_kws": ["M&A", "売却"],
        "advisor": "- 税理士 (譲渡所得課税) + M&A仲介 + 金融機関",
        "stack_example": (
            "- 事業承継・M&A補助金 専門家活用枠 売り手 (¥600万) "
            "+ 廃業費併用 (+¥300万) は M&A成立後の売り手清算コストに充当可"
        ),
        "timing_warning": (
            "- クロージング未成立時は補助上限 ¥300万 へ減額 (DD費のみ対象)"
        ),
    },
    "従業員承継": {
        "subsidy_kws": ["従業員承継", "EBO", "事業承継"],
        "tax_kws": ["経営承継円滑化法", "事業承継税制"],
        "loan_kws": ["従業員承継", "EBO"],
        "advisor": "- 税理士 + 金融機関 (従業員株買取資金) + 弁護士",
        "stack_example": (
            "- 事業承継・M&A補助金 専門家活用枠 + 経営承継円滑化法 認定 "
            "→ 遺留分特例 + 金融支援 (低利融資/信用保証別枠)"
        ),
        "timing_warning": (
            "- 従業員への株式移転は分割実行が通常 → 各段階の贈与税・所得税に注意"
        ),
    },
    "廃業_再チャレンジ": {
        "subsidy_kws": ["廃業", "再チャレンジ"],
        "tax_kws": ["廃業"],
        "loan_kws": ["廃業", "再挑戦", "再チャレンジ"],
        "advisor": "- 税理士 (解散・清算税務) + 中小機構 再生支援 + ハローワーク (従業員離職)",
        "stack_example": (
            "- 事業承継・M&A補助金 廃業・再チャレンジ枠 (¥150万〜800万) "
            "+ 日本公庫 再挑戦支援資金 (低利)"
        ),
        "timing_warning": (
            "- 廃業・再チャレンジ枠は M&A成立と同時の廃業 (売手) にも使える"
        ),
    },
    "廃業_清算のみ": {
        "subsidy_kws": ["廃業"],
        "tax_kws": ["清算所得", "清算"],
        "loan_kws": ["セーフティネット", "倒産"],
        "advisor": "- 税理士 (清算所得申告) + 弁護士 (解散登記) + 社労士 (従業員)",
        "stack_example": (
            "- 補助金原則不可 (再挑戦前提でないため)。税務処理 + 法人解散登記が中心"
        ),
        "timing_warning": (
            "- 清算所得の確定申告 (解散事業年度末 + 各期間) 遅延=重加算"
        ),
    },
}


# ---------------------------------------------------------------------------
# Fetch helpers
# ---------------------------------------------------------------------------

def _fetch_subsidies(lifecycle_kws: List[str], limit: int = 12) -> List[dict]:
    conn = get_canonical_conn()
    if conn is None:
        return []
    likes: List[str] = []
    params: List[str] = []
    for kw in lifecycle_kws:
        likes.append("e.primary_name LIKE ?")
        params.append(f"%{kw}%")
    if not likes:
        return []
    where_like = " OR ".join(likes)
    rows = safe_rows(
        conn,
        f"""
        SELECT e.primary_name, e.raw_json, e.source_url, e.source_topic
        FROM am_entities e
        WHERE e.record_kind='program'
          AND (e.source_topic IN ('67_business_succession_ma_deep','03_exclusion_rules',
                                  '06_prefecture_programs','33_prefecture_programs_part2',
                                  '08_loan_programs')
               OR e.source_topic LIKE '%business_succession%')
          AND ({where_like})
          AND e.primary_name NOT LIKE '% × %'
        LIMIT 60
        """,
        tuple(params),
    )
    out: List[dict] = []
    for r in rows:
        try:
            raw = json.loads(r["raw_json"] or "{}")
        except Exception:
            raw = {}
        out.append({
            "primary_name": r["primary_name"],
            "authority": raw.get("authority") or "-",
            "amount_max_yen": raw.get("amount_max_yen"),
            "subsidy_rate": raw.get("subsidy_rate"),
            "target_entity": raw.get("target_entity"),
            "official_url": raw.get("official_url") or r["source_url"],
            "source_topic": r["source_topic"],
            "excerpt": (raw.get("source_excerpt") or "")[:100],
        })
        if len(out) >= limit:
            break
    return out


def _fetch_tax_measures(lifecycle_kws: List[str], limit: int = 12) -> List[dict]:
    conn = get_canonical_conn()
    if conn is None:
        return []
    likes: List[str] = []
    params: List[str] = []
    for kw in lifecycle_kws:
        likes.append("e.primary_name LIKE ?")
        params.append(f"%{kw}%")
    if not likes:
        return []
    where_like = " OR ".join(likes)
    rows = safe_rows(
        conn,
        f"""
        SELECT e.primary_name, e.raw_json, e.source_url, e.source_topic
        FROM am_entities e
        WHERE e.record_kind='tax_measure' AND ({where_like})
        LIMIT 30
        """,
        tuple(params),
    )
    out: List[dict] = []
    for r in rows:
        try:
            raw = json.loads(r["raw_json"] or "{}")
        except Exception:
            raw = {}
        out.append({
            "primary_name": r["primary_name"],
            "root_law": raw.get("root_law") or raw.get("statutory_basis") or "-",
            "benefit": raw.get("benefit_amount") or raw.get("rate") or "-",
            "application_period_from": raw.get("application_period_from"),
            "application_period_to": raw.get("application_period_to")
                or raw.get("applicable_period"),
            "abolition_note": raw.get("abolition_note"),
            "official_url": raw.get("official_url") or raw.get("source_url") or r["source_url"],
            "source_topic": r["source_topic"],
        })
        if len(out) >= limit:
            break
    return out


def _fetch_loans(lifecycle_kws: List[str], limit: int = 8) -> List[dict]:
    conn = get_canonical_conn()
    if conn is None:
        return []
    likes: List[str] = []
    params: List[str] = []
    for kw in lifecycle_kws:
        likes.append("(e.primary_name LIKE ? OR e.raw_json LIKE ?)")
        params.extend([f"%{kw}%", f"%{kw}%"])
    if not likes:
        return []
    where_like = " OR ".join(likes)
    rows = safe_rows(
        conn,
        f"""
        SELECT e.primary_name, e.raw_json, e.source_url
        FROM am_entities e
        WHERE e.source_topic='08_loan_programs' AND ({where_like})
        LIMIT 40
        """,
        tuple(params),
    )
    out: List[dict] = []
    for r in rows:
        try:
            raw = json.loads(r["raw_json"] or "{}")
        except Exception:
            raw = {}
        out.append({
            "primary_name": r["primary_name"],
            "provider": raw.get("provider") or "-",
            "amount_max_yen": raw.get("amount_max_yen"),
            "interest_rate_base_annual": raw.get("interest_rate_base_annual"),
            "interest_rate_special_annual": raw.get("interest_rate_special_annual"),
            "loan_period_years_max": raw.get("loan_period_years_max"),
            "official_url": raw.get("official_url") or r["source_url"],
        })
        if len(out) >= limit:
            break
    return out


def _fetch_mirasapo_succession_cases(limit: int = 5) -> List[dict]:
    conn = get_canonical_conn()
    if conn is None:
        return []
    # 22_mirasapo_cases primary_name has 事業承継/引継ぎ/廃業 hits already counted.
    # NB: '承継' alone is 2 chars and cannot use trigram FTS; keep LIKE-only
    # here to preserve equivalence for rows like '承継した/第三者承継'.
    rows = safe_rows(
        conn,
        """
        SELECT e.primary_name, e.raw_json
        FROM am_entities e
        WHERE e.source_topic='22_mirasapo_cases'
          AND (e.primary_name LIKE '%事業承継%' OR e.primary_name LIKE '%引継ぎ%'
               OR e.primary_name LIKE '%承継%' OR e.primary_name LIKE '%廃業%')
        LIMIT 30
        """,
    )
    out: List[dict] = []
    for r in rows:
        try:
            raw = json.loads(r["raw_json"] or "{}")
        except Exception:
            raw = {}
        out.append({
            "primary_name": r["primary_name"],
            "company_name": raw.get("company_name"),
            "prefecture": raw.get("prefecture"),
            "case_title": raw.get("case_title"),
            "source_url": raw.get("source_url"),
        })
        if len(out) >= limit:
            break
    return out


# ---------------------------------------------------------------------------
# Formatters
# ---------------------------------------------------------------------------

def _fmt_amt(yen: Any) -> str:
    if yen in (None, ""):
        return "-"
    try:
        v = float(yen)
        if v >= 1_000_000:
            return f"¥{v / 10000:.0f}万"
        return f"¥{int(v)}万"
    except (TypeError, ValueError):
        return str(yen)


def _subsidy_bullet(s: dict) -> str:
    amt = _fmt_amt(s.get("amount_max_yen"))
    rate = s.get("subsidy_rate") or "-"
    return (
        f"- {s['primary_name']} ({s.get('authority','-')}) — "
        f"最大 {amt} / 補助率 {rate}\n    根拠: {s.get('official_url','-')}"
    )


def _tax_bullet(t: dict) -> str:
    period = t.get("application_period_to") or "-"
    benefit = t.get("benefit") or "-"
    return (
        f"- {t['primary_name']} ({t.get('root_law','-')[:40]}) — "
        f"給付内容 {benefit} / 期限 {period}\n    根拠: {t.get('official_url','-')}"
    )


def _loan_bullet(ln: dict) -> str:
    amt = _fmt_amt(ln.get("amount_max_yen"))
    base = ln.get("interest_rate_base_annual")
    special = ln.get("interest_rate_special_annual")
    rate_txt = f"基準 {base*100:.2f}%" if isinstance(base, (int, float)) else "-"
    if isinstance(special, (int, float)):
        rate_txt += f" / 特別 {special*100:.2f}%"
    return (
        f"- {ln['primary_name']} ({ln.get('provider','-')}) — "
        f"上限 {amt} / 金利 {rate_txt} / 期間最大 {ln.get('loan_period_years_max','-')}年\n"
        f"    根拠: {ln.get('official_url','-')}"
    )


# ---------------------------------------------------------------------------
# Bind entrypoint
# ---------------------------------------------------------------------------

def bind(slots: Dict[str, Any], cache: PrecomputedCache) -> Dict[str, Any]:
    lifecycle = slots.get("lifecycle_stage") or "第三者承継_MA買手"
    target_role = slots.get("target_role")
    budget_range = slots.get("budget_range_yen")
    notes: List[str] = []
    source_urls: List[str] = []

    profile = LIFECYCLE_FILTERS.get(lifecycle) or LIFECYCLE_FILTERS["第三者承継_MA買手"]

    subsidies = _fetch_subsidies(profile["subsidy_kws"])
    taxes = _fetch_tax_measures(profile["tax_kws"])
    loans = _fetch_loans(profile["loan_kws"])
    mirasapo = _fetch_mirasapo_succession_cases()

    for s in subsidies:
        if s.get("official_url"):
            source_urls.append(s["official_url"])
    for t in taxes:
        if t.get("official_url"):
            source_urls.append(t["official_url"])
    for ln in loans:
        if ln.get("official_url"):
            source_urls.append(ln["official_url"])

    subsidy_bullets = "\n\n".join(_subsidy_bullet(s) for s in subsidies[:8]) \
        or "- (該当補助金なし)"
    tax_bullets = "\n\n".join(_tax_bullet(t) for t in taxes[:6]) \
        or "- (該当税制なし)"
    loan_bullets = "\n\n".join(_loan_bullet(ln) for ln in loans[:5]) \
        or "- (該当融資なし)"

    # Expiring measures — 事業承継税制 特例措置 is a hard 2027-03-31 deadline
    expiring_lines: List[str] = []
    for t in taxes:
        to = str(t.get("application_period_to") or "")
        if "2027" in to or "令和9" in to:
            expiring_lines.append(
                f"- {t['primary_name']} 期限 {to} 特例措置 (2027年3月末)"
            )
        elif "2026" in to or "令和8" in to:
            expiring_lines.append(f"- {t['primary_name']} 期限 {to}")
    # Always include the hard-coded 特例承継計画 deadline for succession paths
    if "承継" in lifecycle:
        expiring_lines.append(
            "- 法人版事業承継税制 特例措置 特例承継計画 提出期限: 2027-03-31 (令和9年3月末) — 厳守"
        )

    # Budget label
    budget_label = "(未指定)"
    if budget_range:
        if isinstance(budget_range, (tuple, list)) and len(budget_range) == 2:
            lo, hi = budget_range
            budget_label = f"{int(lo)//10000:,}万 - {int(hi)//10000:,}万"
        else:
            budget_label = str(budget_range)

    # Prerequisite certs by lifecycle
    prereq_certs = {
        "親族内承継": "- 特例承継計画 (都道府県提出, 2027-03-31 まで必須)\n- 経営承継円滑化法 認定",
        "第三者承継_MA買手": "- 経営力向上計画 + 経営資源集約化 (税制優遇対象化)",
        "第三者承継_MA売手": "- 登録M&A支援機関 経由のDDが補助要件",
        "従業員承継": "- 経営承継円滑化法 認定 (遺留分特例 / 金融支援)",
        "廃業_再チャレンジ": "- 再チャレンジ枠は 再挑戦計画 添付必須",
        "廃業_清算のみ": "- 特記なし (補助金非適用)",
    }

    ctx = {
        "lifecycle_stage": lifecycle,
        "target_role": target_role or "(未指定)",
        "budget_range_label": budget_label,
        "subsidy_bullets": subsidy_bullets,
        "tax_measure_bullets": tax_bullets,
        "loan_bullets": loan_bullets,
        "prerequisite_certs": prereq_certs.get(lifecycle, "- 経営革新計画 / 経営力向上計画"),
        "stack_pattern_example": profile["stack_example"],
        "timing_warnings": profile["timing_warning"],
        "advisor_recommendations": profile["advisor"],
        "expiring_measures": "\n".join(expiring_lines) or "- (期限切迫 該当なし)",
        "citation_urls": "\n".join(f"- {u}" for u in list(dict.fromkeys(source_urls))[:12])
        or "- (URL 未ingest)",
    }

    notes.append(
        f"lifecycle={lifecycle} subsidies={len(subsidies)} taxes={len(taxes)} "
        f"loans={len(loans)} mirasapo={len(mirasapo)}"
    )

    bound_ok = bool(subsidies or taxes or loans)

    return {
        "bound_ok": bound_ok,
        "ctx": ctx,
        "source_urls": list(dict.fromkeys(source_urls))[:15],
        "notes": notes,
    }


register("i09_succession_closure", bind)
