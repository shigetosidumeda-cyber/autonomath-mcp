"""bind_i10 — 賃上げ / DX / GX 特化で使える制度.

Data sources (read-only):
  canonical  autonomath.db
             - am_entities record_kind='program' with theme keywords in
               primary_name / raw_json
             - am_entities record_kind='tax_measure' 149_corporate_tax_deep (50),
               12_tax_incentives (40) — 賃上げ促進税制 / GX / DX 税制
             - 08_loan_programs with target_conditions mentioning
               経営革新計画 / 設備投資 / DX
             - 15_environment_energy_programs (75 rows) for GX/省エネ theme
  precompute program_compat_closure / tax_measure_validity

Strategy
--------
Given slots["theme"] (enum: 賃上げ / DX / GX_脱炭素 / 省エネ / 人材育成 /
事業再構築 / 輸出 / 研究開発), we apply theme-specific keyword filters and
bucket results into:

  1. Subsidies (record_kind='program' filtered by theme kws)
  2. Tax measures (149_corporate_tax + 12_tax_incentives filtered + R7 拡充)
  3. Loans (08_loan_programs filtered)
  4. Expiring measures (application_period_to in 2026/令和8)
  5. R8 改正予告 from 07_new_program_candidates
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
# Theme filter definitions
# ---------------------------------------------------------------------------

THEME_FILTERS: Dict[str, Dict[str, Any]] = {
    "賃上げ": {
        "subsidy_kws": ["賃上げ", "キャリアアップ", "業務改善", "人材開発",
                        "人材確保"],
        "tax_kws": ["賃上げ促進税制", "所得拡大促進税制"],
        "loan_kws": ["賃上げ", "人材"],
        "env_topics": ["11_mhlw_employment_grants"],
        "compat_summary": (
            "- 賃上げ促進税制 × キャリアアップ助成金: 同一賃金引上げ実績で両適用可 "
            "(別経費カウント)\n"
            "- 業務改善助成金 × 賃上げ促進税制: 賃上げ実績で賃金部分は業務改善助成金、"
            "税額控除は別経費扱いで両取り可"
        ),
        "scoring_boost": "- 賃上げ実績は ものづくり補助金 / 事業再構築補助金 の加点要件",
    },
    "DX": {
        "subsidy_kws": ["IT導入", "DX", "ものづくり", "デジタル",
                        "ロボット", "サイバーセキュリティ"],
        "tax_kws": ["DX投資促進税制", "情報技術等事業"],
        "loan_kws": ["情報化", "IT", "DX"],
        "env_topics": ["41_cybersecurity_programs", "147_ai_regulation_strategy"],
        "compat_summary": (
            "- IT導入補助金 × 中小企業経営強化税制 A類型: 同一設備費の重複不可 "
            "(経費を分離すれば可)\n"
            "- DX投資促進税制 は 令和7年3月末で廃止済み — 後継は 戦略分野国内生産促進税制 等"
        ),
        "scoring_boost": "- DX認定 (経産省) はものづくり補助金 (DX枠) 加点要件",
    },
    "GX_脱炭素": {
        "subsidy_kws": ["GX", "脱炭素", "カーボン", "再エネ", "省エネ",
                        "CO2", "再生可能エネルギー", "太陽光", "風力"],
        "tax_kws": ["カーボンニュートラル投資促進税制", "GX", "脱炭素"],
        "loan_kws": ["環境", "脱炭素", "カーボン", "エネルギー"],
        "env_topics": ["15_environment_energy_programs", "145_wind_power_offshore_onshore",
                       "146_small_hydro_geothermal_biomass"],
        "compat_summary": (
            "- カーボンニュートラル投資促進税制 は 産業競争力強化法 事業適応計画 認定が前提\n"
            "- SII 省エネ補助 × CN税制 は 同一設備費不可 (経費分離要)"
        ),
        "scoring_boost": "- GX認定 / SBT認定 は省エネ補助金 加点要件",
    },
    "省エネ": {
        "subsidy_kws": ["省エネ", "エネルギー", "断熱", "高効率",
                        "LED", "ESCO"],
        "tax_kws": ["カーボンニュートラル投資促進税制", "省エネ"],
        "loan_kws": ["省エネ", "環境"],
        "env_topics": ["15_environment_energy_programs"],
        "compat_summary": (
            "- SII 省エネ補助 + 公庫 環境・エネルギー対策資金 (低利) の組合せ"
        ),
        "scoring_boost": "- 省エネ診断受診 (無料) が SII 補助の前提",
    },
    "人材育成": {
        "subsidy_kws": ["人材育成", "人材開発", "教育訓練", "キャリアアップ"],
        "tax_kws": ["賃上げ促進税制"],
        "loan_kws": ["人材"],
        "env_topics": ["11_mhlw_employment_grants"],
        "compat_summary": "- 人材開発支援助成金 × 賃上げ促進税制 の教育訓練費加算: 両取り可",
        "scoring_boost": "- 人材確保等支援助成金 は 中小企業労働環境向上 加点要件",
    },
    "事業再構築": {
        "subsidy_kws": ["事業再構築", "業態転換", "新事業進出"],
        "tax_kws": ["経営資源集約化税制"],
        "loan_kws": ["新事業", "再構築"],
        "env_topics": [],
        "compat_summary": "- 事業再構築補助金 は 他国補助金との重複不可",
        "scoring_boost": "- 経営革新計画 認定 → 加点",
    },
    "輸出": {
        "subsidy_kws": ["輸出", "海外展開", "JETRO", "海外"],
        "tax_kws": ["研究開発税制"],
        "loan_kws": ["海外", "輸出"],
        "env_topics": ["16_trade_export_programs", "106_jetro_overseas_ftafepa"],
        "compat_summary": "- JETRO の補助金 × 中小機構 海外展開 支援 は 役割分担",
        "scoring_boost": "-",
    },
    "研究開発": {
        "subsidy_kws": ["研究開発", "試験研究", "Go-Tech", "サポイン",
                        "NEDO", "JST"],
        "tax_kws": ["試験研究費", "研究開発税制"],
        "loan_kws": ["研究開発"],
        "env_topics": ["28_research_grants", "101_sti_basic_plan_csti_research"],
        "compat_summary": (
            "- 試験研究費税額控除 × 研究開発補助金 は 同一研究費重複不可 (経費分離必要)"
        ),
        "scoring_boost": "- 研究開発税制 × 中小企業経営強化税制 A類型 の組合せは設備費分離で両取り可",
    },
}


# ---------------------------------------------------------------------------
# Fetch helpers
# ---------------------------------------------------------------------------

def _fetch_subsidies(theme_kws: List[str], env_topics: List[str],
                      limit: int = 12) -> List[dict]:
    conn = get_canonical_conn()
    if conn is None:
        return []
    likes: List[str] = []
    params: List[str] = []
    for kw in theme_kws:
        likes.append("(e.primary_name LIKE ? OR e.raw_json LIKE ?)")
        params.extend([f"%{kw}%", f"%{kw}%"])
    if not likes:
        return []
    where_like = " OR ".join(likes)

    # Include env topics + generic program topics
    topics_to_include = set(env_topics) | {
        "06_prefecture_programs", "33_prefecture_programs_part2",
        "20_designated_city_programs", "67_business_succession_ma_deep",
        "11_mhlw_employment_grants",
    }
    topics_q = ",".join("?" * len(topics_to_include))

    rows = safe_rows(
        conn,
        f"""
        SELECT e.primary_name, e.raw_json, e.source_url, e.source_topic
        FROM am_entities e
        WHERE e.record_kind='program'
          AND (e.source_topic IN ({topics_q})
               OR e.primary_name LIKE '%補助金%'
               OR e.primary_name LIKE '%助成金%')
          AND ({where_like})
          AND e.primary_name NOT LIKE '% × %'
        LIMIT 100
        """,
        tuple(topics_to_include) + tuple(params),
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
            "application_window": (raw.get("application_window_2025")
                                    or raw.get("application_window")
                                    or raw.get("expected_2026_window")),
            "official_url": raw.get("official_url") or r["source_url"],
            "source_topic": r["source_topic"],
        })
        if len(out) >= limit:
            break
    return out


def _fetch_theme_taxes(theme_kws: List[str], limit: int = 10) -> List[dict]:
    conn = get_canonical_conn()
    if conn is None:
        return []
    likes: List[str] = []
    params: List[str] = []
    for kw in theme_kws:
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
            "status": raw.get("status"),
            "urgency": raw.get("urgency"),
            "official_url": raw.get("official_url") or raw.get("source_url") or r["source_url"],
            "source_topic": r["source_topic"],
            "description": (raw.get("description") or raw.get("source_excerpt") or "")[:120],
        })
        if len(out) >= limit:
            break
    return out


def _fetch_theme_loans(theme_kws: List[str], limit: int = 6) -> List[dict]:
    conn = get_canonical_conn()
    if conn is None:
        return []
    likes: List[str] = []
    params: List[str] = []
    for kw in theme_kws:
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
        LIMIT 20
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


def _fetch_r8_theme_signals(theme_kws: List[str]) -> List[dict]:
    """R8改正予告 from 07_new_program_candidates filtered by theme kws."""
    conn = get_canonical_conn()
    if conn is None:
        return []
    likes: List[str] = []
    params: List[str] = []
    for kw in theme_kws:
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
        WHERE e.source_topic='07_new_program_candidates' AND ({where_like})
        LIMIT 20
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
            "primary_name": raw.get("candidate_name") or r["primary_name"],
            "ministry": raw.get("ministry"),
            "expected_start": raw.get("expected_start"),
            "source_url": r["source_url"],
        })
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
    window = s.get("application_window") or "-"
    return (
        f"- {s['primary_name']} ({s.get('authority','-')}) — "
        f"最大 {amt} / 補助率 {rate} / 公募 {str(window)[:40]}\n"
        f"    根拠: {s.get('official_url','-')}"
    )


def _tax_bullet(t: dict) -> str:
    period = t.get("application_period_to") or "-"
    benefit = t.get("benefit") or "-"
    badge = ""
    urgency = t.get("urgency")
    status = t.get("status")
    if status == "abolished" or "廃止" in (t.get("primary_name") or ""):
        badge = " 🛑廃止"
    elif urgency == "FY2026_EXPIRING":
        badge = " 🔥FY2026期限"
    elif urgency == "EXPIRED":
        badge = " 🛑期限切れ"
    return (
        f"- {t['primary_name']}{badge} — 税額控除 {benefit} / 期限 {period}\n"
        f"    根拠法令: {t.get('root_law','-')[:50]}\n"
        f"    根拠: {t.get('official_url','-')}"
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
    theme = slots.get("theme") or "賃上げ"
    fiscal_year = slots.get("fiscal_year") or 2026
    target_size = slots.get("target_size")
    prefecture = slots.get("prefecture")
    notes: List[str] = []
    source_urls: List[str] = []

    profile = THEME_FILTERS.get(theme) or THEME_FILTERS["賃上げ"]

    subsidies = _fetch_subsidies(profile["subsidy_kws"], profile.get("env_topics", []))
    taxes = _fetch_theme_taxes(profile["tax_kws"])
    loans = _fetch_theme_loans(profile["loan_kws"])
    r8_signals = _fetch_r8_theme_signals(profile["subsidy_kws"] + profile["tax_kws"])

    for s in subsidies:
        if s.get("official_url"):
            source_urls.append(s["official_url"])
    for t in taxes:
        if t.get("official_url"):
            source_urls.append(t["official_url"])
    for ln in loans:
        if ln.get("official_url"):
            source_urls.append(ln["official_url"])
    for r in r8_signals:
        if r.get("source_url"):
            source_urls.append(r["source_url"])

    subsidy_bullets = "\n\n".join(_subsidy_bullet(s) for s in subsidies[:8]) \
        or "- (該当補助金 未収録)"
    tax_bullets = "\n\n".join(_tax_bullet(t) for t in taxes[:6]) \
        or "- (該当税制 未収録)"
    loan_bullets = "\n\n".join(_loan_bullet(ln) for ln in loans[:5]) \
        or "- (該当融資 未収録)"

    # Expiring measures - filter taxes whose to <= 2027 end
    expiring_lines: List[str] = []
    for t in taxes:
        to = str(t.get("application_period_to") or "")
        if t.get("status") == "abolished":
            expiring_lines.append(f"- 🛑 {t['primary_name']} (廃止) — 期限到達")
        elif t.get("urgency") in ("FY2026_EXPIRING", "EXPIRED"):
            expiring_lines.append(f"- 🔥 {t['primary_name']} 期限 {to[:40]}")
        elif "2026" in to or "2027" in to or "令和8" in to or "令和9" in to:
            expiring_lines.append(f"- {t['primary_name']} 期限 {to[:40]}")

    # R8 signals
    r8_bullets: List[str] = []
    for r in r8_signals[:5]:
        r8_bullets.append(
            f"- {r['primary_name'][:60]} (所管 {r.get('ministry','-')}, "
            f"開始予定 {r.get('expected_start','-')})\n    根拠: {r.get('source_url','-')}"
        )

    # Merge r8 signals into tax bullets footer if present
    tax_bullets_full = tax_bullets
    if r8_bullets:
        tax_bullets_full += "\n\n**令和8年度改正予告**:\n" + "\n".join(r8_bullets)

    ctx = {
        "theme": theme,
        "fiscal_year": str(fiscal_year),
        "target_size": target_size or "(未指定)",
        "prefecture": prefecture or "(未指定)",
        "top_n": str(min(len(subsidies), 8)),
        "subsidy_bullets": subsidy_bullets,
        "tax_bullets": tax_bullets_full,
        "loan_bullets": loan_bullets,
        "compat_summary": profile["compat_summary"],
        "stack_strategy_bullets": (
            "- 国補助金 + 税制優遇 + 県制度融資 の3層 (同一経費不可の原則を守る)\n"
            "- 認定計画 (経営革新/経営力向上) 取得で 加点 + 低利融資 の両取り"
        ),
        "prerequisite_certs": "- 経営革新計画 / 経営力向上計画 (多数の補助金の加点要件)",
        "scoring_boost_rules": profile["scoring_boost"],
        "expiring_measures": "\n".join(expiring_lines) or "- (該当期限切迫なし)",
        "citation_urls": "\n".join(f"- {u}" for u in list(dict.fromkeys(source_urls))[:12])
        or "- (URL 未ingest)",
    }

    notes.append(
        f"theme={theme} subsidies={len(subsidies)} taxes={len(taxes)} "
        f"loans={len(loans)} r8_signals={len(r8_signals)}"
    )

    bound_ok = bool(subsidies or taxes or loans)

    return {
        "bound_ok": bound_ok,
        "ctx": ctx,
        "source_urls": list(dict.fromkeys(source_urls))[:15],
        "notes": notes,
    }


register("i10_wage_dx_gx_themed", bind)
