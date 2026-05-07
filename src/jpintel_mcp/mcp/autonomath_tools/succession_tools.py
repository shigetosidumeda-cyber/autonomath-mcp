"""succession_tools — M&A / 事業承継 制度 matcher MCP tools.

Mirrors ``api/succession.py`` (REST companion) so MCP clients can hit the
same surface without scraping HTTP. Two tools:

  * ``match_succession_am``  — POST /v1/succession/match equivalent
  * ``succession_playbook_am`` — GET /v1/succession/playbook equivalent

Both are pure SQLite + Python — NO LLM call. The corpus is jpintel.db
(`programs` + `laws`) read-only. ``_disclaimer`` is required on every
result (税理士法 §52 / 弁護士法 §72 fence).

Cohort context: 後継者問題 / M&A consider する 中小企業. Pairs with
``houjin_watch`` (mig 088) on the M&A pillar of the cohort revenue model.
"""

from __future__ import annotations

import logging
import os
import sqlite3
from typing import Annotated, Any

from pydantic import Field

from jpintel_mcp.api.succession import (
    _CLIFF_DATES,
    _DISCLAIMER,
    _MAX_PROGRAMS,
    _OWNER_AGE_HIGH_RISK,
    _PLAYBOOK_PRIMARY_SOURCES,
    _PLAYBOOK_STEPS,
    _SCENARIOS,
    _TAX_LEVERS_BY_SCENARIO,
    _build_next_steps,
    _classify_chusho,
    _query_related_laws,
    _query_succession_programs,
)
from jpintel_mcp.config import settings
from jpintel_mcp.mcp.server import _READ_ONLY, mcp

from .error_envelope import make_error

logger = logging.getLogger("jpintel.mcp.autonomath.succession")

# Env gate matches sibling autonomath_tools modules. Default ON.
_ENABLED = os.environ.get("AUTONOMATH_SUCCESSION_ENABLED", "1") == "1"


def _open_jpintel_ro() -> sqlite3.Connection | dict[str, Any]:
    """Open jpintel.db read-only. Soft-fail to error envelope."""
    db_path = os.environ.get("JPINTEL_DB_PATH", "data/jpintel.db")
    try:
        conn = sqlite3.connect(
            f"file:{db_path}?mode=ro",
            uri=True,
            timeout=5.0,
            check_same_thread=False,
        )
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.Error as exc:
        return make_error(
            code="db_unavailable",
            message=f"jpintel.db open failed: {exc}",
            retry_with=["search_programs"],
        )


def _match_succession_impl(
    *,
    scenario: str,
    current_revenue: int,
    employee_count: int,
    owner_age: int,
) -> dict[str, Any]:
    """Pure-Python core. Lets tests call without going through the
    @mcp.tool wrapper.
    """

    if scenario not in _SCENARIOS:
        return make_error(
            code="invalid_enum",
            message=(
                f"scenario must be one of: {', '.join(sorted(_SCENARIOS))}; got {scenario!r}."
            ),
            field="scenario",
        )

    if current_revenue < 0 or current_revenue > 10_000_000_000_000:
        return make_error(
            code="out_of_range",
            message="current_revenue must be 0 ≤ value ≤ 10兆円.",
            field="current_revenue",
        )
    if employee_count < 0 or employee_count > 1_000_000:
        return make_error(
            code="out_of_range",
            message="employee_count must be 0 ≤ value ≤ 1,000,000.",
            field="employee_count",
        )
    if owner_age < 18 or owner_age > 120:
        return make_error(
            code="out_of_range",
            message="owner_age must be 18 ≤ value ≤ 120.",
            field="owner_age",
        )

    conn = _open_jpintel_ro()
    if isinstance(conn, dict):
        return conn

    try:
        spec = _SCENARIOS[scenario]
        is_chusho = _classify_chusho(current_revenue, employee_count)
        early_advised = owner_age >= _OWNER_AGE_HIGH_RISK

        programs = _query_succession_programs(conn, list(spec["key_keywords"]), _MAX_PROGRAMS)
        laws = _query_related_laws(conn)
    finally:
        conn.close()

    tax_levers = _TAX_LEVERS_BY_SCENARIO.get(scenario, [])
    next_steps = _build_next_steps(
        scenario=scenario,
        is_chusho=is_chusho,
        early_advised=early_advised,
        program_count=len(programs),
    )

    return {
        "scenario": scenario,
        "scenario_label_ja": spec["label_ja"],
        "cohort_summary": {
            "current_revenue_jpy": current_revenue,
            "employee_count": employee_count,
            "owner_age": owner_age,
        },
        "is_chusho_kigyo": is_chusho,
        "early_succession_advised": early_advised,
        "primary_levers": list(spec["primary_levers"]),
        "programs": programs,
        "tax_levers": tax_levers,
        "legal_support": laws,
        "next_steps": next_steps,
        "provenance": {
            "data_origin": ("中小企業庁 + 国税庁 + e-Gov + 都道府県 + 日本政策金融公庫"),
            "program_corpus_size": len(programs),
            "law_corpus_size": len(laws),
            "tax_lever_count": len(tax_levers),
            "primary_source_root": "https://www.chusho.meti.go.jp/zaimu/shoukei/",
        },
        "_disclaimer": _DISCLAIMER,
    }


def _succession_playbook_impl() -> dict[str, Any]:
    """Pure-Python playbook accessor."""
    return {
        "overview_ja": (
            "中小企業の事業承継は (1) 現状把握 → (2) 承継方針決定 → "
            "(3) 経営承継円滑化法 認定 → (4) M&A仲介 / 後継者選定 → "
            "(5) 補助金申請 → (6) 株式・資産移転実行 → (7) PMI の 7 段階で"
            "標準化されています (中小企業庁 事業承継ガイドライン準拠)。"
        ),
        "typical_horizon_years": "5〜10 年 (早期着手推奨、法人は 7 年中央値)",
        "advisor_chain": [
            "認定経営革新等支援機関 (税理士・公認会計士)",
            "弁護士",
            "司法書士",
            "登録 M&A支援機関 (該当時)",
            "都道府県 事業承継・引継ぎ支援センター",
        ],
        "steps": list(_PLAYBOOK_STEPS),
        "cliff_dates": list(_CLIFF_DATES),
        "primary_sources": list(_PLAYBOOK_PRIMARY_SOURCES),
        "_disclaimer": _DISCLAIMER,
    }


# ---------------------------------------------------------------------------
# MCP tool registration
# ---------------------------------------------------------------------------


if _ENABLED and settings.autonomath_enabled:

    @mcp.tool(annotations=_READ_ONLY)
    def match_succession_am(
        scenario: Annotated[
            str,
            Field(
                description=(
                    "承継 scenario: 'child_inherit' (親族内), 'm_and_a' "
                    "(第三者承継・M&A), 'employee_buy_out' (役員・従業員 / EBO)."
                ),
            ),
        ],
        current_revenue: Annotated[
            int,
            Field(
                ge=0,
                le=10_000_000_000_000,
                description=("現在の年間売上 (税抜・概算 JPY)。中小企業判定の粗い目安。"),
            ),
        ],
        employee_count: Annotated[
            int,
            Field(
                ge=0,
                le=1_000_000,
                description="フルタイム換算 従業員数。中小企業者該当性 判定の目安。",
            ),
        ],
        owner_age: Annotated[
            int,
            Field(
                ge=18,
                le=120,
                description=("現オーナー (代表取締役) の年齢。70 歳以上で早期承継 advisory。"),
            ),
        ],
    ) -> dict[str, Any]:
        """[SUCCESSION-MATCH] M&A / 事業承継 制度 matcher: scenario (親族内 / 第三者M&A / 役員従業員) と 売上 / 従業員数 / 代表者年齢 から、適用候補となる 補助金・税制 (事業承継税制 / 相続税精算課税)・法令支援 (経営承継円滑化法) を返す。Pure SQL + Python, NO LLM. 1 unit = 1 call. §52 / §72 envelope.

        WHEN:
          - 「後継者問題を抱える中小企業はどの制度を使えるか?」
          - 「親が会社を子に渡したい時の税制は?」
          - 「M&Aで第三者承継する場合の補助金は?」
          - 「役員に株式を譲渡する EBO の支援策は?」

        WHEN NOT:
          - 個別の相続税・贈与税 の申告計算 → 税理士へ
          - 経営承継円滑化法 認定申請の代行 → 認定経営革新等支援機関へ
          - 特定 M&A案件 の評価 → FA / M&A仲介機関へ
          - 単一制度の探索 → search_programs

        RETURNS (envelope):
          {
            scenario, scenario_label_ja,
            cohort_summary: { current_revenue_jpy, employee_count, owner_age },
            is_chusho_kigyo: bool,
            early_succession_advised: bool,
            primary_levers: [str],
            programs: [{unified_id, name, tier, source_url, ...}],
            tax_levers: [{name, summary, primary_source_url, applicability_note}],
            legal_support: [{unified_id, law_title, source_url, ...}],
            next_steps: [str],
            provenance: { data_origin, program_corpus_size, ... },
            _disclaimer: str (mandatory)
          }
        """
        return _match_succession_impl(
            scenario=scenario,
            current_revenue=current_revenue,
            employee_count=employee_count,
            owner_age=owner_age,
        )

    @mcp.tool(annotations=_READ_ONLY)
    def succession_playbook_am() -> dict[str, Any]:
        """[SUCCESSION-PLAYBOOK] 標準 事業承継 playbook (7 step) + advisor chain (税理士 + M&A仲介 + 認定支援機関 + 司法書士 + 弁護士) + cliff dates (特例承継計画 提出期限 / 特例措置 適用期限). NO LLM. 1 unit. §52 envelope.

        WHEN:
          - 「事業承継ってまず何から始めればいい?」
          - 「税理士・M&A仲介・弁護士・司法書士の役割分担は?」
          - 「特例承継計画 の提出期限はいつ?」

        WHEN NOT:
          - scenario 別 制度マッチ → match_succession_am
          - 個別案件の advisory → 認定経営革新等支援機関へ

        RETURNS (envelope):
          {
            overview_ja, typical_horizon_years, advisor_chain: [str],
            steps: [{step_no, label_ja, advisor_kind, horizon, deliverables, primary_sources}],
            cliff_dates: [{date, label_ja, note}],
            primary_sources: [{name, url}],
            _disclaimer: str (mandatory)
          }
        """
        return _succession_playbook_impl()


__all__ = [
    "_match_succession_impl",
    "_succession_playbook_impl",
]
