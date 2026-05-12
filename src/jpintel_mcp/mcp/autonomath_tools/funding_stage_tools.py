"""funding_stage_tools — Funding stage program matcher (no LLM).

Single MCP tool ``match_programs_by_funding_stage_am`` (and a parallel REST
endpoint ``POST /v1/programs/by_funding_stage`` wired in
``api/funding_stage.py``) that answers the canonical jpcite question for
資金調達フェーズ:

    「私 ステージ X (シード / アーリー / グロース / IPO / 事業承継) で
     該当する制度はどれか?」

The 5 stage definitions + keyword fence + indicative band live in
``api/funding_stage._STAGES`` so the REST and MCP surfaces stay in sync —
this module imports the definitions and the matcher impl rather than
duplicating them.

NO LLM. Single ¥3/req billing event (one tool call = one usage_event).
§52 / §47条の2 / 行政書士法 §1 disclaimer envelope on every result —
output is information retrieval, not 申請代理 / 税務助言 / 経営判断.
"""

from __future__ import annotations

import contextlib
import logging
import sqlite3
from typing import Annotated, Any

from pydantic import Field

from jpintel_mcp._jpcite_env_bridge import get_flag
from jpintel_mcp.mcp.autonomath_tools.error_envelope import make_error
from jpintel_mcp.mcp.server import _READ_ONLY, mcp

logger = logging.getLogger("jpintel.mcp.autonomath.funding_stage")

# Env-gate: default ON, flip "0" to disable without a redeploy.
_ENABLED = get_flag("JPCITE_FUNDING_STAGE_ENABLED", "AUTONOMATH_FUNDING_STAGE_ENABLED", "1") == "1"


def _open_jpintel_ro() -> sqlite3.Connection | dict[str, Any]:
    """Open jpintel.db read-only via file URI.

    Tests inject ``JPINTEL_DB_PATH`` to a tmp seeded fixture; production
    boots with ``data/jpintel.db``. Soft-fail returns a make_error envelope
    when the file is missing — callers (REST + MCP) propagate as-is.
    """
    db_path = get_flag("JPCITE_DB_PATH", "JPINTEL_DB_PATH", "data/jpintel.db")
    try:
        conn = sqlite3.connect(
            f"file:{db_path}?mode=ro",
            uri=True,
            timeout=10.0,
            check_same_thread=False,
        )
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.Error as exc:
        return make_error(
            code="db_unavailable",
            message=f"jpintel.db open failed: {exc}",
            retry_with=["search_programs", "list_open_programs"],
        )


def match_programs_by_funding_stage_impl(
    stage: str,
    *,
    annual_revenue_yen: int | None = None,
    employee_count: int | None = None,
    incorporation_year: int | None = None,
    prefecture: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    """Pure-Python core. Imported by tests + REST + MCP.

    Loads stage definitions lazily so the import graph stays acyclic
    (api -> mcp_tool -> api would otherwise be a circular import; we
    instead import inside the function body).
    """
    from jpintel_mcp.api.funding_stage import (
        _DISCLAIMER,
        _STAGE_BY_ID,
        _age_years_from_year,
        _match_programs_for_stage,
    )

    if not stage or stage not in _STAGE_BY_ID:
        return make_error(
            code="invalid_enum",
            message=(f"unknown stage {stage!r}. valid: {sorted(_STAGE_BY_ID.keys())}"),
            field="stage",
            hint=(
                "GET /v1/funding_stages/catalog で 5 stage の定義 "
                "(seed / early / growth / ipo / succession) を確認してください。"
            ),
        )

    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100

    if annual_revenue_yen is not None and annual_revenue_yen < 0:
        return make_error(
            code="out_of_range",
            message="annual_revenue_yen は 0 以上が必要です。",
            field="annual_revenue_yen",
        )
    if employee_count is not None and employee_count < 0:
        return make_error(
            code="out_of_range",
            message="employee_count は 0 以上が必要です。",
            field="employee_count",
        )
    if incorporation_year is not None and not (1900 <= incorporation_year <= 2100):
        return make_error(
            code="out_of_range",
            message="incorporation_year は 1900〜2100 が必要です (西暦)。",
            field="incorporation_year",
        )

    conn_or_err = _open_jpintel_ro()
    if isinstance(conn_or_err, dict):
        return conn_or_err
    conn = conn_or_err

    try:
        stage_def = _STAGE_BY_ID[stage]
        age_years = _age_years_from_year(incorporation_year)
        matched, axes_applied = _match_programs_for_stage(
            conn,
            stage=stage_def,
            annual_revenue_yen=annual_revenue_yen,
            employee_count=employee_count,
            age_years=age_years,
            prefecture=prefecture,
            limit=limit,
        )
    finally:
        with contextlib.suppress(sqlite3.Error):
            conn.close()

    return {
        "input": {
            "stage": stage,
            "annual_revenue_yen": annual_revenue_yen,
            "employee_count": employee_count,
            "incorporation_year": incorporation_year,
            "age_years": age_years,
            "prefecture": prefecture,
            "limit": limit,
        },
        "stage_definition": {
            "id": stage_def["id"],
            "ja_label": stage_def["ja_label"],
            "description": stage_def["description"],
            "age_min_years": stage_def["age_min_years"],
            "age_max_years": stage_def["age_max_years"],
            "capital_max_yen": stage_def["capital_max_yen"],
            "revenue_band_yen": stage_def["revenue_band_yen"],
            "keywords_any": list(stage_def["keywords_any"]),
            "keywords_avoid": list(stage_def["keywords_avoid"]),
        },
        "matched_programs": matched,
        "axes_applied": axes_applied,
        "summary": {
            "total_matched": len(matched),
            "amount_max_man_yen_top": (
                matched[0]["amount_max_man_yen"]
                if matched and matched[0].get("amount_max_man_yen") is not None
                else None
            ),
        },
        "total": len(matched),
        "limit": limit,
        "offset": 0,
        "results": matched,
        "_disclaimer": _DISCLAIMER,
        "_next_calls": [
            {
                "tool": "check_funding_stack_am",
                "args": {
                    "program_ids": ([p["unified_id"] for p in matched[:3]] if matched else []),
                },
                "rationale": (
                    "Top 3 stage-fit programs を 併用可否 マトリクスに渡す "
                    "(C(3, 2) = 3 pair = ¥9)。"
                ),
            },
            {
                "tool": "case_cohort_match_am",
                "args": {
                    "prefecture": prefecture,
                    "industry_jsic": None,
                    "limit": 20,
                },
                "rationale": (
                    "同 stage の他社採択事例を JSIC × 規模 × 地域 で当てる (stage 判定の補強)。"
                ),
            },
        ],
    }


# ---------------------------------------------------------------------------
# MCP tool registration
# ---------------------------------------------------------------------------
if _ENABLED:

    @mcp.tool(annotations=_READ_ONLY)
    def match_programs_by_funding_stage_am(
        stage: Annotated[
            str,
            Field(
                description=(
                    "Funding stage slug — one of: seed / early / growth / ipo / "
                    "succession. See `list_static_resources_am` and the public "
                    "catalog at GET /v1/funding_stages/catalog for the closed "
                    "definitions (keyword fence + age/capital/revenue bands)."
                ),
                examples=["growth"],
            ),
        ],
        annual_revenue_yen: Annotated[
            int | None,
            Field(
                ge=0,
                description=("年商 (yen). None = 開示しない (matcher は revenue 帯を緩和)。"),
            ),
        ] = None,
        employee_count: Annotated[
            int | None,
            Field(
                ge=0,
                description="従業員数。None = 開示しない。",
            ),
        ] = None,
        incorporation_year: Annotated[
            int | None,
            Field(
                ge=1900,
                le=2100,
                description=(
                    "設立年 (西暦)。None = 開示しない。年齢は (現年 - "
                    "incorporation_year) で算出し stage の age band に当て込む。"
                ),
            ),
        ] = None,
        prefecture: Annotated[
            str | None,
            Field(
                max_length=80,
                description=(
                    "都道府県 exact match (例: '東京都')。None = 全国 "
                    "(国 + 全都道府県 + 全市町村 を含む)。"
                ),
            ),
        ] = None,
        limit: Annotated[
            int,
            Field(
                ge=1,
                le=100,
                description="返却 programs の最大件数。Clamped to [1, 100]. Default 20.",
            ),
        ] = 20,
    ) -> dict[str, Any]:
        """[FUNDING-STAGE-AM] 資金調達ステージ別 (シード/アーリー/グロース/IPO/事業承継) program マッチャー。NO LLM, ¥3/req metered. `_disclaimer` 必須。

        WHAT: 5 stage (seed / early / growth / ipo / succession) の closed
        enum + keyword fence + age/capital/revenue indicative band で
        ``programs`` を篩い、`amount_max_man_yen × likelihood` 順に
        sort。stage 判定は heuristic — 日本の制度は『stage X 専用』タグを
        持たないため、keyword fence 公開定義に依拠。

        WHEN:
          - 「私 シード期 で 該当する補助金/融資/税制 list」
          - 「グロース期 (5-10 年目) の中堅企業向け制度を年商レンジで絞りたい」
          - 「事業承継 + M&A の補助金/税制を都道府県 X でフィルタ」

        WHEN NOT:
          - JSIC 業種 × 採択事例マッチ → case_cohort_match_am
          - 個別 program の探索 → search_programs / list_open_programs
          - 制度併用可否 → check_funding_stack_am
          - 法人別 360 view → get_houjin_360_am

        RETURNS (envelope):
          {
            input: {stage, annual_revenue_yen, employee_count,
                    incorporation_year, age_years, prefecture, limit},
            stage_definition: {id, ja_label, description,
                               age_min_years, age_max_years,
                               capital_max_yen, revenue_band_yen,
                               keywords_any, keywords_avoid},
            matched_programs: [
              {unified_id, primary_name, tier, program_kind,
               amount_max_man_yen, source_url, prefecture,
               likelihood, score, ...},
              ...
            ],
            axes_applied: {stage_keyword_filter, prefecture, age_filter,
                           revenue_filter, employee_filter},
            summary: {total_matched, amount_max_man_yen_top},
            total, limit, offset, results,
            _disclaimer, _next_calls
          }

        DATA QUALITY HONESTY: keyword fence は primary_name OR ladder のみ。
        本文/募集要項の text mining は行わない (FTS5 trigram の単漢字
        false-positive 回避のため)。stage の age/capital/revenue band は
        ranking の重み付けには使うが、ハード除外には使わない (data sparsity
        を踏まえた honest design)。

        BILLING: 1 tool call = 1 ¥3 課金単位。
        """

        return match_programs_by_funding_stage_impl(
            stage=stage,
            annual_revenue_yen=annual_revenue_yen,
            employee_count=employee_count,
            incorporation_year=incorporation_year,
            prefecture=prefecture,
            limit=limit,
        )


__all__ = [
    "match_programs_by_funding_stage_impl",
]
