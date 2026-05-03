"""REST handlers for the 16 jpcite am_* tools (the 6.8GB autonomath.db layer).

Paired with the @mcp.tool decorated functions in jpintel_mcp/mcp/autonomath_tools/.
Each route is a thin FastAPI wrapper around the underlying Python function —
we don't duplicate SQL or validation logic. The underlying functions are
already `_safe_tool`-wrapped, so they return an error envelope
(`{error: {code, message, hint}, …}`) rather than raising on DB faults.

Naming: all paths live under `/v1/am/*` to disambiguate from the flat
jpintel.db `programs` / `enforcement_cases` / `loan_programs` / etc.
surfaces. Tool names in MCP carry an `_am` suffix for the same reason;
the REST prefix `am/` mirrors that convention.

Billing: every endpoint calls `log_usage()` with `ctx` from `ApiContextDep`.
Anonymous callers (no X-API-Key / Bearer) pass through because require_key()
constructs a `tier='free'` context when the header is absent. The router
is mounted with `AnonIpLimitDep` in api/main.py so anonymous 3/day
IP quota applies uniformly. Authenticated paid tier is metered ¥3/req.
"""
from __future__ import annotations

import contextlib
import sqlite3
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Body, HTTPException, Path, Query, Request, status
from fastapi.responses import JSONResponse

from jpintel_mcp.api._envelope import StandardResponse, wants_envelope_v2
from jpintel_mcp.api._error_envelope import safe_request_id
from jpintel_mcp.api._health_deep import get_deep_health
from jpintel_mcp.api._response_models import (
    AMActiveAtResponse,
    AMAnnotationsResponse,
    AMByLawResponse,
    AMEnforcementCheckResponse,
    AMEnumValuesResponse,
    AMIntentResponse,
    AMLawArticleResponse,
    AMLoanSearchResponse,
    AMOpenProgramsResponse,
    AMProvenanceResponse,
    AMReasonResponse,
    AMRelatedResponse,
    AMSearchResponse,
    AMSimpleSearchResponse,
    AMTaxRuleResponse,
    AMValidateResponse,
    DeepHealthResponse,
    ExampleProfileDetail,
    ExampleProfileList,
    StaticResourceDetail,
    StaticResourceList,
    TemplateMetadataResponse,
    TemplateRenderResponse,
)
from jpintel_mcp.api.deps import ApiContextDep, DbDep, log_usage
from jpintel_mcp.cache.l4 import canonical_cache_key, get_or_compute
from jpintel_mcp.config import settings
from jpintel_mcp.mcp.autonomath_tools import (
    annotation_tools,
    autonomath_wrappers,
    industry_packs,
    provenance_tools,
    static_resources,
    tax_rule_tool,
    tools,
    validation_tools,
)
from jpintel_mcp.templates.saburoku_kyotei import (
    TemplateError,
    render_36_kyotei,
)
from jpintel_mcp.templates.saburoku_kyotei import (
    get_required_fields as get_36_kyotei_required,
)
from jpintel_mcp.templates.saburoku_kyotei import (
    get_template_metadata as get_36_kyotei_metadata,
)

# Mirrors `_DRAFT_DISCLAIMER` in mcp/autonomath_tools/template_tool.py — the
# 36協定 REST + MCP surfaces share the same option-B disclaimer text. Negation
# context (「保証しません」) is INV-22-safe.
_SABUROKU_DISCLAIMER = (
    "本テンプレートは draft です。労基署提出前に必ず社労士確認を行ってください。"
    "jpcite は generation accuracy について保証しません。"
)

# 税理士法 §52 fence for /v1/am/tax_incentives + /v1/am/tax_rule. Mirrors
# api/tax_rulesets.py:_TAX_DISCLAIMER. Every tax-related REST response
# surfaces this in the `_disclaimer` envelope key so consumer LLMs do not
# relay our output as 税務助言. We provide DOC-level information (制度名 /
# 根拠条文 / 計算例 from public 国税庁・財務省・e-Gov sources) — never advice.
_TAX_DISCLAIMER = (
    "本情報は税務助言ではありません。jpcite は公的機関が公表する税制・補助金・"
    "法令情報を検索・整理して提供するサービスで、税理士法 §52 に基づき個別具体的な"
    "税務判断・申告書作成代行は行いません。個別案件は資格を有する税理士に必ずご相談"
    "ください。本サービスの情報利用により生じた損害について、当社は一切の責任を負いません。"
)

# 36協定 REST endpoints are 503-gated when AUTONOMATH_36_KYOTEI_ENABLED is not
# truthy. 36協定 is a 労基法 §36 + 社労士法 regulated obligation — incorrect
# generation can expose the operator to legal liability and brand damage. The
# gate keeps the REST surface dark until the operator completes a legal review
# (社労士 supervision arrangement + customer-facing disclaimer alignment),
# mirroring the MCP-side gate in mcp/autonomath_tools/template_tool.py. See
# docs/_internal/saburoku_kyotei_gate_decision_2026-04-25.md.
_SABUROKU_DISABLED_BODY = {
    "error": {
        "code": "feature_disabled",
        "message": (
            "36協定 template endpoints are disabled (AUTONOMATH_36_KYOTEI_ENABLED=0). "
            "Operator must complete legal review (社労士 supervision arrangement) before enabling."
        ),
    }
}


router = APIRouter(prefix="/v1/am", tags=["autonomath"])

# Separate router for unbilled, unrate-limited heartbeat endpoints.
# Mounted in main.py without AnonIpLimitDep so production uptime monitors
# can poll without consuming the 3/day anonymous IP quota.
health_router = APIRouter(prefix="/v1/am", tags=["autonomath-health"])


# ---------------------------------------------------------------------------
# β2 wiring: response-envelope v2 hint enrichment for the REST endpoints.
#
# The raw tool returns are passed through ``_apply_envelope`` before they
# hit ``JSONResponse(content=...)``. That call additively merges the
# envelope's status / explanation / suggested_actions / meta.suggestions
# / meta.alternative_intents / meta.tips fields onto the result without
# overwriting any pre-existing key (e.g. tools that already publish
# meta.data_as_of / retrieval_note keep them verbatim).
#
# The MCP side gets the same enrichment via _with_mcp_telemetry in
# server.py, so MCP-tool / REST-endpoint consumers see the same hint
# vocabulary.
# ---------------------------------------------------------------------------
def _apply_envelope(
    tool_name: str,
    result: Any,
    *,
    query: str | None = None,
    extra_kwargs: dict[str, Any] | None = None,
) -> Any:
    """Run the response-envelope v2 merge on a tool's raw return value.

    Soft-fail: if the envelope_wrapper module is unavailable for any
    reason (sandboxed test, broken import) we return ``result`` as-is.
    Never raises. Never mutates ``result`` in place — returns a new dict.
    """
    if not isinstance(result, dict) and not isinstance(result, list):
        return result
    try:
        from jpintel_mcp.mcp.autonomath_tools.envelope_wrapper import (
            _coerce_results,
            build_envelope,
        )
    except Exception:
        return result

    extras = dict(extra_kwargs or {})
    err_obj: dict[str, Any] | None = None
    if isinstance(result, dict):
        err = result.get("error")
        if isinstance(err, dict) and ("code" in err or "message" in err):
            err_obj = err

    try:
        if err_obj is not None:
            envelope = build_envelope(
                tool_name=tool_name,
                results=[],
                query_echo=query or "",
                latency_ms=0.0,
                error=err_obj,
                router_query=query,
                tool_kwargs=extras,
                fields="standard",
            )
        else:
            results_list, legacy_extras = _coerce_results(result)
            envelope = build_envelope(
                tool_name=tool_name,
                results=results_list,
                query_echo=query or "",
                latency_ms=0.0,
                legacy_extras=legacy_extras,
                router_query=query,
                tool_kwargs=extras,
                fields="standard",
            )
    except Exception:
        return result

    if not isinstance(result, dict):
        return envelope

    merged: dict[str, Any] = dict(result)
    additive = (
        "status",
        "result_count",
        "explanation",
        "suggested_actions",
        "api_version",
        "tool_name",
        "query_echo",
        "evidence_source_count",
    )
    for k in additive:
        if k in envelope and k not in merged:
            merged[k] = envelope[k]
    env_meta = envelope.get("meta")
    if isinstance(env_meta, dict):
        existing_meta = merged.get("meta")
        if isinstance(existing_meta, dict):
            new_meta = dict(existing_meta)
            for k, v in env_meta.items():
                if k not in new_meta:
                    new_meta[k] = v
            merged["meta"] = new_meta
        else:
            merged["meta"] = dict(env_meta)
    return merged


# ---------------------------------------------------------------------------
# O4 — am_amendment_snapshot lifecycle honesty
#
# Per CLAUDE.md "common gotchas": `am_amendment_snapshot` (14,596 rows /
# 7,298 entities × 2 versions) carries a uniform `eligibility_hash` across
# 100% of (v1, v2) pairs. The table is correctly shaped as a point-in-time
# snapshot but **cannot** be used as a real time-series — the per-version
# diff is meaningless. Every endpoint whose response surfaces amendment
# data MUST attach this caveat so downstream LLMs and dashboards do not
# present version_seq as eligibility drift evidence.
#
# Aligns with `feedback_no_fake_data.md` and `feedback_autonomath_fraud_risk.md`
# — silent staleness on a launch surface is a 詐欺-risk vector.
# ---------------------------------------------------------------------------
_LIFECYCLE_CAVEAT_TEXT = (
    "amendment_snapshot has uniform eligibility_hash; treat as point-in-time only"
)

# Structured form for machine consumers (AI agents, dashboards). Keeps the
# human-readable summary in `note` so a `"point-in-time" in str(caveat)` style
# check still works, while exposing the underlying counts so callers can
# program against them. Numbers reflect production state per CLAUDE.md /
# docs/api-reference.md (14,596 rows total; 144 with non-NULL temporal fields;
# remaining 82% carry an empty eligibility_hash).
_LIFECYCLE_CAVEAT: dict[str, Any] = {
    "data_quality": "partial",
    "rows_with_complete_temporal_data": 144,
    "total_rows": 14596,
    "note": (
        "82% of am_amendment_snapshot rows have empty eligibility_hash; "
        "historical diff is partial. Use effective_from for confirmed dates "
        "only — treat the snapshot as point-in-time, not a real time-series."
    ),
}


def _attach_lifecycle_caveat(body: Any) -> Any:
    """Inject `_lifecycle_caveat` into the response body if not already set.

    Idempotent — re-applying does not overwrite a caller-supplied caveat.
    Soft-fail: returns `body` unchanged if it isn't a dict.

    The caveat value is a structured dict (data_quality / row counts / note)
    so AI-agent consumers can program against it. The `note` field carries
    the human-readable summary for log lines and Markdown rendering.
    """
    if not isinstance(body, dict):
        return body
    if "_lifecycle_caveat" in body:
        return body
    # Return a fresh copy per call so callers cannot mutate the module-level
    # default by reference.
    body["_lifecycle_caveat"] = dict(_LIFECYCLE_CAVEAT)
    return body


# Enum literal types mirrored from tools.py / autonomath_wrappers.py so the
# OpenAPI schema advertises the same constraint set as the MCP tools. If a
# new value is added upstream, update the mirror here too (audit via grep).
_TAX_AUTHORITIES = Literal[
    "国税庁", "財務省", "経済産業省", "中小企業庁", "農林水産省", "総務省",
    "国土交通省", "厚生労働省", "自治体",
]
_TAX_ENTITY = Literal[
    "中小企業", "小規模事業者", "個人事業主", "大企業", "認定事業者",
    "青色申告者", "農業法人", "特定事業者等",
]
_CERT_AUTHORITIES = Literal[
    "経済産業省", "日本健康会議", "厚生労働省", "内閣府", "都道府県", "市町村",
    "農林水産省", "国土交通省", "その他",
]
_SIZE_VALUES = Literal["sole", "small", "sme", "mid", "large"]
_EnumName = Literal[
    "authority", "tier", "industry", "funding_purpose", "target_type",
    "region", "tax_category", "program_kind", "loan_type", "event_type",
    "ministry", "certification_authority",
]
_GxTheme = Literal[
    "ghg_reduction", "ev", "renewable", "zeb_zeh", "carbon_credit",
]
_GxCompanySize = Literal[
    "sme", "midsize", "large", "individual", "municipality", "farmer",
]
_LoanKind = Literal[
    "ippan", "trou", "seirei", "sanko", "sogyo",
    "rinsei", "saigai", "shingiseikyu", "kiki", "other",
]
_PlanKind = Literal[
    "retirement_mutual", "bankruptcy_mutual", "dc_pension", "db_pension",
    "industry_pension", "welfare_insurance", "health_insurance", "other",
]
_TaxDedType = Literal[
    "small_enterprise_deduction", "idekodc", "group_retirement",
    "corp_expense", "none",
]


# ---------------------------------------------------------------------------
# L4 cache wiring (Q4 perf diff 4 — Zipf-tail short-circuit at the API edge).
#
# tax_incentives is the only `/v1/am/*` route in the top-3 read endpoints
# (search_programs + get_program already wired in api/programs.py). 30 min
# TTL — `am_tax_rule` is amendment-snapshot data with daily-at-most churn,
# so 1800s is well within the freshness contract while absorbing the Zipf
# tail.
#
# Cache-key inputs MUST include every user-visible parameter that changes
# the response shape — including `ctx.tier` to avoid cross-tier poisoning
# on shared key-space.
#
# `log_usage(...)` is called OUTSIDE the cached compute so each request
# still bills + counts toward retention digests, even when the body comes
# from cache.
_L4_TTL_AM_TAX_INCENTIVES = 1800  # 30 min
_L4_TOOL_AM_TAX_INCENTIVES = "api.am.tax_incentives"


def _l4_get_or_compute_safe(
    cache_key: str,
    tool: str,
    params: dict[str, Any],
    compute: Any,  # Callable[[], dict[str, Any]]
    ttl: int,
) -> dict[str, Any]:
    """Wrap cache.l4.get_or_compute with a self-heal for missing l4_query_cache.

    Mirrors api/programs.py:_l4_get_or_compute_safe — kept local so the two
    routers don't grow a shared base module just for one helper.
    """
    try:
        return get_or_compute(
            cache_key=cache_key,
            tool=tool,
            params=params,
            compute=compute,
            ttl=ttl,
        )
    except sqlite3.OperationalError as exc:
        if "no such table" not in str(exc):
            raise
        from jpintel_mcp.api.stats import _ensure_l4_table

        _ensure_l4_table()
        return get_or_compute(
            cache_key=cache_key,
            tool=tool,
            params=params,
            compute=compute,
            ttl=ttl,
        )


# ---------------------------------------------------------------------------
# 1. search_tax_incentives
# ---------------------------------------------------------------------------
@router.get(
    "/tax_incentives",
    response_model=AMSearchResponse,
    summary="Search 税制特例 (special depreciation, tax credits, NOL carryforward, exemptions)",
    description=(
        "FTS + structured filter across **285 税制特例** rows: 特別償却 "
        "(special depreciation), 税額控除 (tax credit), 繰越欠損金 (NOL "
        "carryforward), 非課税措置 (tax exemption). Backed by autonomath.db "
        "`am_entities` (record_kind='tax_measure') with provenance + "
        "amount conditions joined.\n\n"
        "**When to use:** caller asks 'what tax incentives apply to "
        "manufacturing CapEx in 2026?' — pass `target_year=2026` + "
        "`industry='製造業'` + `target_entity='sme'`. For broader "
        "consumption-tax / 適格請求書 ruleset queries (2割特例, 経過措置 80%) "
        "use `GET /v1/tax_rulesets/search` instead.\n\n"
        "**税理士法 §52 fence:** every response carries a `_disclaimer` "
        "envelope key declaring the output information retrieval, NOT "
        "税務助言. LLM agents MUST relay the disclaimer."
    ),
    responses={
        200: {
            "description": "AMSearchResponse + `_disclaimer` (税理士法 §52 fence).",
            "content": {
                "application/json": {
                    "example": {
                        "total": 1,
                        "limit": 20,
                        "offset": 0,
                        "results": [
                            {
                                "entity_id": "tax_measure_chusho_kvestigation_credit_2026",
                                "name": "中小企業投資促進税制 (税額控除7%)",
                                "authority": "国税庁",
                                "tax_kind": "corporate",
                                "incentive_type": "credit",
                                "rate": "7%",
                                "amount_cap_yen": 30000000,
                                "effective_from": "2025-04-01",
                                "effective_until": "2027-03-31",
                                "source_url": "https://www.nta.go.jp/...",
                            }
                        ],
                        "_disclaimer": (
                            "本情報は公開情報の検索結果であり、税務助言ではありません。"
                            "申告・適用判断は税理士にご確認ください。"
                        ),
                    }
                }
            },
        }
    },
)
def rest_search_tax_incentives(
    conn: DbDep,
    ctx: ApiContextDep,
    query: Annotated[str | None, Query(max_length=200)] = None,
    authority: Annotated[_TAX_AUTHORITIES | None, Query()] = None,
    industry: Annotated[str | None, Query(max_length=100)] = None,
    target_year: Annotated[int | None, Query(ge=1988, le=2099)] = None,
    target_entity: Annotated[_TAX_ENTITY | None, Query()] = None,
    natural_query: Annotated[str | None, Query(max_length=500)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> JSONResponse:
    """税制特例 (特別償却 / 税額控除 / 繰越欠損金 / 非課税措置) search across ~285 rows.

    Every response carries a ``_disclaimer`` envelope key (税理士法 §52 fence)
    declaring the output information retrieval, NOT 税務助言. Mirrors the
    36協定 render pattern.
    """
    # L4 cache key — every user-visible param + ctx.tier (poisoning guard).
    # Wraps the FTS scan + envelope build; logging stays outside.
    _l4_params: dict[str, Any] = {
        "query": query,
        "authority": authority,
        "industry": industry,
        "target_year": target_year,
        "target_entity": target_entity,
        "natural_query": natural_query,
        "limit": limit,
        "offset": offset,
        "ctx_tier": ctx.tier,
    }
    _l4_key = canonical_cache_key(_L4_TOOL_AM_TAX_INCENTIVES, _l4_params)

    def _do_search() -> dict[str, Any]:
        result = tools.search_tax_incentives(
            query=query,
            authority=authority,
            industry=industry,
            target_year=target_year,
            target_entity=target_entity,
            natural_query=natural_query,
            limit=limit,
            offset=offset,
        )
        return _apply_envelope(
            "search_tax_incentives", result, query=query or natural_query,
        )

    body = _l4_get_or_compute_safe(
        cache_key=_l4_key,
        tool=_L4_TOOL_AM_TAX_INCENTIVES,
        params=_l4_params,
        compute=_do_search,
        ttl=_L4_TTL_AM_TAX_INCENTIVES,
    )
    # 税理士法 §52 fence — inject after L4 cache so the disclaimer text
    # is always current, never stale-cached.
    if isinstance(body, dict):
        body = dict(body)
        body["_disclaimer"] = _TAX_DISCLAIMER
    log_usage(conn, ctx, "am.tax_incentives.search")
    return JSONResponse(content=body)


# ---------------------------------------------------------------------------
# 2. search_certifications
# ---------------------------------------------------------------------------
@router.get(
    "/certifications",
    response_model=AMSearchResponse,
    summary="Search 認定・認証制度 (健康経営, えるぼし, くるみん, 経営革新等支援機関 etc.)",
    description=(
        "Look up Japanese business certification programs across 66 "
        "認定・認証 schemes spanning labor (くるみん, えるぼし, ユース"
        "エール), management innovation (経営革新, 認定経営革新等支援機関), "
        "health (健康経営優良法人, 健康経営銘柄), sustainability (SDGs "
        "認証, ゼブラ企業), and information security (Pマーク, ISMS).\n\n"
        "**When to use:** caller asks 'which certifications can a 50-person "
        "manufacturing 株式会社 in 大阪 apply for?' — pass "
        "`size='medium'` + `industry='製造業'`. Many 補助金 cite these "
        "認定 as eligibility prerequisites — pair with "
        "`POST /v1/programs/prescreen` (`held_certifications=[...]`) to "
        "see which programs the certifications unlock.\n\n"
        "**Authority enum (`authority`):** 厚生労働省 / 経済産業省 / 内閣府 "
        "/ 中小企業庁 / 自治体 / その他."
    ),
    responses={
        200: {
            "description": "AMSearchResponse — paginated certification entities.",
            "content": {
                "application/json": {
                    "example": {
                        "total": 1,
                        "limit": 20,
                        "offset": 0,
                        "results": [
                            {
                                "entity_id": "cert_kurumin_2026",
                                "name": "くるみん認定 (子育てサポート企業)",
                                "authority": "厚生労働省",
                                "size_target": ["sme", "large"],
                                "industry_target": ["all"],
                                "issuance_basis": "次世代育成支援対策推進法",
                                "validity_years": 2,
                                "source_url": "https://www.mhlw.go.jp/general/seido/koyou/kurumin/",
                            }
                        ],
                    }
                }
            },
        }
    },
)
def rest_search_certifications(
    conn: DbDep,
    ctx: ApiContextDep,
    query: Annotated[str | None, Query(max_length=200)] = None,
    authority: Annotated[_CERT_AUTHORITIES | None, Query()] = None,
    size: Annotated[_SIZE_VALUES | None, Query()] = None,
    industry: Annotated[str | None, Query(max_length=100)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> JSONResponse:
    """認定・認証制度 (健康経営 / えるぼし / くるみん / SDGs / 経営革新 等) search."""
    result = tools.search_certifications(
        query=query,
        authority=authority,
        size=size,
        industry=industry,
        limit=limit,
        offset=offset,
    )
    log_usage(conn, ctx, "am.certifications.search")
    return JSONResponse(content=_apply_envelope(
        "search_certifications", result, query=query,
    ))


# ---------------------------------------------------------------------------
# 3. list_open_programs
# ---------------------------------------------------------------------------
@router.get("/open_programs", response_model=AMOpenProgramsResponse)
def rest_list_open_programs(
    conn: DbDep,
    ctx: ApiContextDep,
    on_date: Annotated[str | None, Query(max_length=10, description="ISO YYYY-MM-DD. Default = today.")] = None,
    region: Annotated[str | None, Query(max_length=100)] = None,
    industry: Annotated[str | None, Query(max_length=100)] = None,
    size: Annotated[_SIZE_VALUES | None, Query()] = None,
    natural_query: Annotated[str | None, Query(max_length=500)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> JSONResponse:
    """Currently-open (公募中) program rounds on a target date."""
    result = tools.list_open_programs(
        on_date=on_date,
        region=region,
        industry=industry,
        size=size,
        natural_query=natural_query,
        limit=limit,
    )
    log_usage(conn, ctx, "am.open_programs.list")
    return JSONResponse(content=_apply_envelope(
        "list_open_programs", result, query=natural_query,
    ))


# ---------------------------------------------------------------------------
# 4. enum_values_am
# ---------------------------------------------------------------------------
@router.get("/enums/{enum_name}", response_model=AMEnumValuesResponse)
def rest_enum_values(
    enum_name: _EnumName,
    conn: DbDep,
    ctx: ApiContextDep,
) -> JSONResponse:
    """List canonical enum values + frequency for a given enum_name."""
    result = tools.enum_values_am(enum_name=enum_name)
    log_usage(conn, ctx, "am.enum_values", params={"enum_name": enum_name})
    return JSONResponse(content=_apply_envelope(
        "enum_values", result, query=enum_name,
    ))


# ---------------------------------------------------------------------------
# 5. search_by_law
# ---------------------------------------------------------------------------
@router.get("/by_law", response_model=AMByLawResponse)
def rest_search_by_law(
    conn: DbDep,
    ctx: ApiContextDep,
    law_name: Annotated[str, Query(min_length=1, max_length=200)],
    article: Annotated[str | None, Query(max_length=40)] = None,
    amendment_date: Annotated[str | None, Query(max_length=10)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> JSONResponse:
    """Programs / tax rules / certifications linked to a specific law (fuzzy name match)."""
    result = tools.search_by_law(
        law_name=law_name,
        article=article,
        amendment_date=amendment_date,
        limit=limit,
        offset=offset,
    )
    # O4: surface amendment_snapshot point-in-time honesty caveat — even when
    # `amendment_date` is omitted, downstream callers may still join against
    # am_amendment_snapshot rows shipped in the response.
    result = _attach_lifecycle_caveat(result)
    log_usage(conn, ctx, "am.by_law.search")
    return JSONResponse(content=_apply_envelope(
        "search_by_law", result, query=law_name,
    ))


# ---------------------------------------------------------------------------
# 6. active_programs_at
# ---------------------------------------------------------------------------
@router.get("/active_at", response_model=AMActiveAtResponse)
def rest_active_programs_at(
    conn: DbDep,
    ctx: ApiContextDep,
    date: Annotated[str, Query(min_length=10, max_length=10, description="ISO YYYY-MM-DD")],
    region: Annotated[str | None, Query(max_length=100)] = None,
    industry: Annotated[str | None, Query(max_length=100)] = None,
    size: Annotated[_SIZE_VALUES | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> JSONResponse:
    """Point-in-time snapshot: programs whose effective window covered a given date."""
    result = tools.active_programs_at(
        date=date,
        region=region,
        industry=industry,
        size=size,
        limit=limit,
    )
    log_usage(conn, ctx, "am.active_at")
    return JSONResponse(content=_apply_envelope(
        "active_programs_at", result, query=date,
    ))


# ---------------------------------------------------------------------------
# 6b. programs_active_at_v2  (O4 — three-axis effective + application window)
# ---------------------------------------------------------------------------
#
# Backed by the SQL view `programs_active_at_v2` (migration 070). Surfaces
# THREE temporal axes in one round trip — without this endpoint the same
# question costs four chained calls (search + active_at + filter + verify).
#
# Honesty notes (per O4 analysis 2026-04-25):
#   - `am_amendment_snapshot.effective_from` is filled on only 140 / 14,596
#     rows. The view falls back to `am_entities.fetched_at` for the rest and
#     surfaces the choice via `effective_from_source`.
#   - `am_amendment_snapshot.eligibility_hash` is uniform across (v1, v2)
#     for 100% of pairs — the snapshot table CANNOT be used as a real
#     time-series. We therefore emit `_lifecycle_caveat` on every response
#     so downstream LLMs do not hallucinate version-by-version diffs.
def _validate_iso_or_none(value: str | None, *, name: str) -> str | None:
    if value is None:
        return None
    import datetime as _dt
    try:
        return _dt.date.fromisoformat(value).isoformat()
    except (TypeError, ValueError) as exc:
        from fastapi import HTTPException
        raise HTTPException(
            status_code=422,
            detail=f"{name} must be ISO-8601 YYYY-MM-DD ({exc})",
        ) from exc


@router.get("/programs/active_v2")
def rest_programs_active_at_v2(
    conn: DbDep,
    ctx: ApiContextDep,
    as_of: Annotated[
        str | None,
        Query(
            min_length=10,
            max_length=10,
            description="ISO YYYY-MM-DD. effective window pivot. Defaults to today (JST date as ISO).",
        ),
    ] = None,
    application_open_by: Annotated[
        str | None,
        Query(
            min_length=10,
            max_length=10,
            description="Filter to rounds whose application_open_date <= this date.",
        ),
    ] = None,
    application_close_by: Annotated[
        str | None,
        Query(
            min_length=10,
            max_length=10,
            description="Filter to rounds whose application_close_date >= this date (締切がこの日以降).",
        ),
    ] = None,
    prefecture: Annotated[
        str | None,
        Query(max_length=20, description="Optional prefecture filter (e.g. '東京都').")
    ] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> JSONResponse:
    """Three-axis active-at: effective window + application_open + application_close in one query.

    Backed by view `programs_active_at_v2`. Returns programs that:
      - are effective on `as_of` (effective_from <= as_of < effective_until,
        with `effective_from_source` provenance hint), AND
      - have an application round whose open_date <= `application_open_by`
        (when provided), AND
      - have an application round whose close_date >= `application_close_by`
        (when provided), AND
      - match `prefecture` (when provided).

    Caveat: `am_amendment_snapshot` carries a uniform `eligibility_hash`
    across all (v1, v2) pairs — the table is a point-in-time snapshot,
    not a real time-series. The response carries `_lifecycle_caveat` (a
    structured dict with `data_quality` / `rows_with_complete_temporal_data`
    / `total_rows` / `note`) so callers do not infer per-version eligibility
    drift. The same caveat is also emitted on `/v1/am/by_law` and
    `/v1/am/law_article` responses that surface amendment history.
    """
    as_of_iso = _validate_iso_or_none(as_of, name="as_of")
    open_by_iso = _validate_iso_or_none(application_open_by, name="application_open_by")
    close_by_iso = _validate_iso_or_none(application_close_by, name="application_close_by")

    from jpintel_mcp.mcp.autonomath_tools.db import connect_autonomath
    am_conn = connect_autonomath()

    # If `as_of` omitted, use today's date (UTC; lex-comparable against ISO).
    if as_of_iso is None:
        import datetime as _dt
        as_of_iso = _dt.date.today().isoformat()

    where_sql: list[str] = [
        # effective predicate using the view's source-aware columns.
        "(COALESCE(effective_from, ?) <= ?)",
        "(effective_until IS NULL OR effective_until > ?)",
    ]
    params: list[Any] = [as_of_iso, as_of_iso, as_of_iso]
    # ^ first ? = fallback so rows with NULL effective_from still pass when
    #   as_of >= as_of (always true) — i.e. fall back permissively, surface
    #   provenance via effective_from_source.

    if open_by_iso is not None:
        where_sql.append("application_open_date IS NOT NULL")
        where_sql.append("application_open_date <= ?")
        params.append(open_by_iso)
    if close_by_iso is not None:
        where_sql.append("application_close_date IS NOT NULL")
        where_sql.append("application_close_date >= ?")
        params.append(close_by_iso)
    if prefecture:
        where_sql.append("prefecture = ?")
        params.append(prefecture)

    sql = (
        "SELECT unified_id, primary_name, tier, prefecture, "
        "       authority_canonical, application_round_id, "
        "       application_round_label, application_open_date, "
        "       application_close_date, application_status, "
        "       amendment_snapshot_id, amendment_version_seq, "
        "       effective_from, effective_until, effective_from_source, "
        "       is_effective_now, is_application_open_now "
        "  FROM programs_active_at_v2 "
        " WHERE " + " AND ".join(where_sql) +
        " ORDER BY application_close_date ASC, primary_name ASC "
        " LIMIT ?"
    )
    params.append(int(limit))

    cur = am_conn.execute(sql, params)
    cols = [d[0] for d in cur.description]
    rows = [dict(zip(cols, r, strict=False)) for r in cur.fetchall()]

    body: dict[str, Any] = {
        "tool_name": "programs_active_at_v2",
        "as_of": as_of_iso,
        "application_open_by": open_by_iso,
        "application_close_by": close_by_iso,
        "prefecture": prefecture,
        "limit": int(limit),
        "result_count": len(rows),
        "results": rows,
    }
    body = _attach_lifecycle_caveat(body)
    log_usage(conn, ctx, "am.programs.active_v2")
    return JSONResponse(content=_apply_envelope(
        "programs_active_at_v2", body, query=as_of_iso,
    ))


# ---------------------------------------------------------------------------
# 7. related_programs
# ---------------------------------------------------------------------------
@router.get("/related/{program_id}", response_model=AMRelatedResponse)
def rest_related_programs(
    program_id: str,
    conn: DbDep,
    ctx: ApiContextDep,
    relation_types: Annotated[
        list[str] | None,
        Query(description="Filter edge types (prerequisite / compatible / incompatible / replaces / …)."),
    ] = None,
    depth: Annotated[int, Query(ge=1, le=3)] = 1,
    max_edges: Annotated[int, Query(ge=1, le=500)] = 100,
) -> JSONResponse:
    """Graph walk over am_relation (prerequisite / compatible / incompatible / replaces / amends / related / references_law etc.)."""
    result = tools.related_programs(
        program_id=program_id,
        relation_types=relation_types,
        depth=depth,
        max_edges=max_edges,
    )
    log_usage(conn, ctx, "am.related_programs", params={"program_id": program_id})
    return JSONResponse(content=_apply_envelope(
        "related_programs", result, query=program_id,
    ))


# ---------------------------------------------------------------------------
# 8. search_acceptance_stats_am
# ---------------------------------------------------------------------------
@router.get("/acceptance_stats", response_model=AMSearchResponse)
def rest_search_acceptance_stats(
    conn: DbDep,
    ctx: ApiContextDep,
    program_name: Annotated[str | None, Query(max_length=200)] = None,
    year: Annotated[int | None, Query(ge=1988, le=2099)] = None,
    region: Annotated[str | None, Query(max_length=100)] = None,
    industry: Annotated[str | None, Query(max_length=100)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> JSONResponse:
    """採択率 / 採択事例 statistics from am_entities (supersedes cross-DB acceptance_stats_tool)."""
    result = tools.search_acceptance_stats_am(
        program_name=program_name,
        year=year,
        region=region,
        industry=industry,
        limit=limit,
        offset=offset,
    )
    log_usage(conn, ctx, "am.acceptance_stats.search")
    return JSONResponse(content=_apply_envelope(
        "search_acceptance_stats", result, query=program_name,
    ))


# ---------------------------------------------------------------------------
# 9. intent_of
# ---------------------------------------------------------------------------
@router.get(
    "/intent",
    response_model=AMIntentResponse,
    include_in_schema=settings.autonomath_reasoning_enabled,
)
def rest_intent_of(
    conn: DbDep,
    ctx: ApiContextDep,
    query: Annotated[str, Query(min_length=1, max_length=500)],
) -> JSONResponse:
    """Route a natural-language query to the best-fit tool + extracted slots (query_rewrite layer)."""
    if not settings.autonomath_reasoning_enabled:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "reasoning tools disabled")
    result = tools.intent_of(query=query)
    log_usage(conn, ctx, "am.intent")
    return JSONResponse(content=_apply_envelope(
        "intent_of", result, query=query,
    ))


# ---------------------------------------------------------------------------
# 10. reason_answer
# ---------------------------------------------------------------------------
@router.get(
    "/reason",
    response_model=AMReasonResponse,
    include_in_schema=settings.autonomath_reasoning_enabled,
)
def rest_reason_answer(
    conn: DbDep,
    ctx: ApiContextDep,
    query: Annotated[str, Query(min_length=1, max_length=500)],
    persona: Annotated[str | None, Query(max_length=100)] = None,
) -> JSONResponse:
    """Return a citation-backed narrative answer (source_url + snippet per claim)."""
    if not settings.autonomath_reasoning_enabled:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "reasoning tools disabled")
    result = tools.reason_answer(query=query, persona=persona)
    log_usage(conn, ctx, "am.reason")
    return JSONResponse(content=_apply_envelope(
        "reason_answer", result, query=query,
    ))


# ---------------------------------------------------------------------------
# 11. get_am_tax_rule
# ---------------------------------------------------------------------------
@router.get("/tax_rule", response_model=AMTaxRuleResponse)
def rest_get_tax_rule(
    conn: DbDep,
    ctx: ApiContextDep,
    measure_name_or_id: Annotated[str, Query(min_length=1, max_length=200)],
    rule_type: Annotated[str | None, Query(max_length=60)] = None,
    as_of: Annotated[str | None, Query(max_length=10, description="ISO YYYY-MM-DD (default today)")] = None,
) -> JSONResponse:
    """Single tax measure lookup against am_tax_rule with root_law + rate + applicability window.

    Every response carries a ``_disclaimer`` envelope key (税理士法 §52 fence).
    Even when a single measure matches, the row payload is information
    retrieval — root_law / rate / applicability window all derive from
    public 国税庁・財務省 sources and require qualified 税理士 confirmation
    before any filing decision.
    """
    result = tax_rule_tool.get_am_tax_rule(
        measure_name_or_id=measure_name_or_id,
        rule_type=rule_type,
        as_of=as_of,
    )
    body = _apply_envelope(
        "get_am_tax_rule", result, query=measure_name_or_id,
    )
    if isinstance(body, dict):
        body = dict(body)
        body["_disclaimer"] = _TAX_DISCLAIMER
    log_usage(conn, ctx, "am.tax_rule.get")
    return JSONResponse(content=body)


# ---------------------------------------------------------------------------
# 12. search_gx_programs_am
# ---------------------------------------------------------------------------
@router.get("/gx_programs", response_model=AMSimpleSearchResponse)
def rest_search_gx_programs(
    conn: DbDep,
    ctx: ApiContextDep,
    theme: Annotated[_GxTheme, Query()] = "ghg_reduction",
    company_size: Annotated[_GxCompanySize | None, Query()] = None,
    region: Annotated[str | None, Query(max_length=100)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> JSONResponse:
    """GX / 脱炭素 / 再エネ / EV / ZEB-ZEH curated 補助金 programs."""
    result = autonomath_wrappers.search_gx_programs_am(
        theme=theme,
        company_size=company_size,
        region=region,
        limit=limit,
    )
    log_usage(conn, ctx, "am.gx_programs.search")
    return JSONResponse(content=_apply_envelope(
        "search_gx_programs_am", result, query=theme,
    ))


# ---------------------------------------------------------------------------
# 13. search_loans_am
# ---------------------------------------------------------------------------
@router.get(
    "/loans",
    response_model=AMLoanSearchResponse,
    summary="Search loan products (公庫 / 商工中金 / 自治体制度融資) with 3-axis risk filter",
    description=(
        "Loan-product search backed by `am_loan_product` (autonomath.db) "
        "covering 日本政策金融公庫 (JFC), 商工組合中央金庫, and 自治体制度融資 "
        "(prefecture / municipal credit guarantee programs). Filter "
        "independently along three risk axes:\n\n"
        "- `no_collateral=true` → 物的担保 not required\n"
        "- `no_personal_guarantor=true` → 代表者保証 / 経営者保証 not required\n"
        "- `no_third_party_guarantor=true` → 第三者保証 not required\n\n"
        "Free-text search via `name_query` (3+ char minimum). Lender "
        "narrowing via `lender_entity_id`. Amount band via "
        "`min_amount_yen` / `max_amount_yen` (in YEN, not 万円).\n\n"
        "**Note:** there is also `GET /v1/loan-programs/search` against "
        "the legacy `loan_programs` table (108 rows, jpintel.db). The "
        "`/v1/am/loans` route returns the unified autonomath view with "
        "richer entity provenance. Prefer this for new integrations."
    ),
    responses={
        200: {
            "description": "AMLoanSearchResponse — ranked loan products.",
            "content": {
                "application/json": {
                    "example": {
                        "total": 1,
                        "limit": 10,
                        "results": [
                            {
                                "entity_id": "loan_jfc_kokumin_shinki_kaigyou",
                                "name": "新規開業・スタートアップ支援資金",
                                "lender": "日本政策金融公庫 国民生活事業",
                                "loan_kind": "special_rate",
                                "amount_max_yen": 72000000,
                                "loan_period_years_max": 20,
                                "interest_rate_annual": 0.041,
                                "collateral_required": "negotiable",
                                "personal_guarantor_required": "negotiable",
                                "third_party_guarantor_required": "negotiable",
                                "source_url": "https://www.jfc.go.jp/n/finance/search/01_sinkikaigyou_m.html",
                            }
                        ],
                    }
                }
            },
        }
    },
)
def rest_search_loans(
    conn: DbDep,
    ctx: ApiContextDep,
    loan_kind: Annotated[_LoanKind | None, Query()] = None,
    no_collateral: Annotated[bool, Query()] = False,
    no_personal_guarantor: Annotated[bool, Query()] = False,
    no_third_party_guarantor: Annotated[bool, Query()] = False,
    max_amount_yen: Annotated[int | None, Query(ge=0)] = None,
    min_amount_yen: Annotated[int | None, Query(ge=0)] = None,
    lender_entity_id: Annotated[str | None, Query(max_length=100)] = None,
    name_query: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 10,
) -> JSONResponse:
    """am_loan_product query — 公庫 / 商工中金 / 自治体制度融資 with 3-axis guarantor filter."""
    result = autonomath_wrappers.search_loans_am(
        loan_kind=loan_kind,
        no_collateral=no_collateral,
        no_personal_guarantor=no_personal_guarantor,
        no_third_party_guarantor=no_third_party_guarantor,
        max_amount_yen=max_amount_yen,
        min_amount_yen=min_amount_yen,
        lender_entity_id=lender_entity_id,
        name_query=name_query,
        limit=limit,
    )
    log_usage(conn, ctx, "am.loans.search")
    return JSONResponse(content=_apply_envelope(
        "search_loans_am", result, query=name_query,
    ))


# ---------------------------------------------------------------------------
# 14. check_enforcement_am
# ---------------------------------------------------------------------------
@router.get(
    "/enforcement",
    response_model=AMEnforcementCheckResponse,
    summary="Check 行政処分 / 排除期間 status for a 法人番号 or 事業者名",
    description=(
        "Compliance / DD lookup: is this entity currently barred from "
        "補助金 / 助成金 receipt under 補助金等適正化法 §17 / 入札参加資格 "
        "停止 / その他 行政処分? Query by 13-digit `houjin_bangou` (preferred — "
        "exact match) or `target_name` (LIKE match against the published "
        "対象事業者名). Pass `as_of_date='YYYY-MM-DD'` to check status as "
        "of a historical date — 排除期間 windows are time-bounded so "
        "'today' vs '2024-06-01' can give different verdicts.\n\n"
        "**Backed by:** 1,185 行政処分 cases (会計検査院 + ministry "
        "公表) + `am_enforcement_detail` (22,258 rows; "
        "grant_refund / subsidy_exclude / fine breakdown).\n\n"
        "**Use this BEFORE awarding subsidies, before extending credit, "
        "before contracting with a vendor.** A clear-status response "
        "(`is_currently_barred=false`) lists past closed cases for "
        "reference; an active match returns the disclosed_until "
        "(排除期間 終了日) so the caller can plan timing."
    ),
    responses={
        200: {
            "description": "Enforcement status snapshot at `as_of_date`.",
            "content": {
                "application/json": {
                    "example": {
                        "houjin_bangou": "1234567890123",
                        "target_name_query": None,
                        "as_of_date": "2026-04-29",
                        "is_currently_barred": False,
                        "active_cases": [],
                        "past_cases": [
                            {
                                "case_id": "jbaudit_r03_2021-r03-0046-0_1",
                                "event_type": "clawback",
                                "ministry": "内閣府",
                                "disclosed_date": "2022-11-07",
                                "disclosed_until": "2027-11-06",
                                "amount_improper_grant_yen": 89073000,
                                "legal_basis": "補助金等に係る予算の執行の適正化に関する法律 第17条",
                                "source_url": "https://report.jbaudit.go.jp/org/r03/2021-r03-0046-0.htm",
                            }
                        ],
                    }
                }
            },
        }
    },
)
def rest_check_enforcement(
    conn: DbDep,
    ctx: ApiContextDep,
    houjin_bangou: Annotated[str | None, Query(max_length=20)] = None,
    target_name: Annotated[str | None, Query(max_length=200)] = None,
    as_of_date: Annotated[str, Query(max_length=10)] = "today",
) -> JSONResponse:
    """Is this entity currently barred from 補助金 / 助成金 (行政処分 排除期間 check)?"""
    result = autonomath_wrappers.check_enforcement_am(
        houjin_bangou=houjin_bangou,
        target_name=target_name,
        as_of_date=as_of_date,
    )
    log_usage(conn, ctx, "am.enforcement.check")
    return JSONResponse(content=_apply_envelope(
        "check_enforcement_am", result, query=target_name or houjin_bangou,
    ))


# ---------------------------------------------------------------------------
# 15. search_mutual_plans_am
# ---------------------------------------------------------------------------
@router.get(
    "/mutual_plans",
    response_model=AMLoanSearchResponse,
    summary="Search mutual-aid / pension / workers' comp plans (共済 / 年金 / 労災)",
    description=(
        "Cross-search across Japanese mutual-aid (共済), corporate / "
        "personal pension (年金), and workers' compensation special-membership "
        "(労災特別加入) plans. Covers 小規模企業共済 (small-enterprise mutual "
        "aid), iDeCo+ (iDeCo with employer contributions), DB / DC corporate "
        "pensions, industry-specific pensions, and 労災特別加入 schemes for "
        "代表者 / 一人親方.\n\n"
        "Filter by `plan_kind` (retirement_mutual / bankruptcy_mutual / "
        "dc_pension / db_pension / industry_pension / welfare_insurance / "
        "health_insurance / other), `premium_monthly_yen` ceiling, "
        "`tax_deduction_type` (small_enterprise_deduction / idekodc / "
        "group_retirement / corp_expense / none), or `provider_entity_id`.\n\n"
        "(共済 / 年金 / 労災 cross-search: 小規模企業共済 / iDeCo+ / "
        "DB / DC / 労災特別加入 等を横断検索.)"
    ),
)
def rest_search_mutual_plans(
    conn: DbDep,
    ctx: ApiContextDep,
    plan_kind: Annotated[_PlanKind | None, Query()] = None,
    premium_monthly_yen: Annotated[int | None, Query(ge=0)] = None,
    tax_deduction_type: Annotated[_TaxDedType | None, Query()] = None,
    provider_entity_id: Annotated[str | None, Query(max_length=100)] = None,
    name_query: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 10,
) -> JSONResponse:
    """Cross-search mutual-aid / pension / workers' compensation plans.

    共済 / 年金 / 労災 cross-search (小規模企業共済 / iDeCo+ / DB / DC /
    労災特別加入).
    """
    result = autonomath_wrappers.search_mutual_plans_am(
        plan_kind=plan_kind,
        premium_monthly_yen=premium_monthly_yen,
        tax_deduction_type=tax_deduction_type,
        provider_entity_id=provider_entity_id,
        name_query=name_query,
        limit=limit,
    )
    log_usage(conn, ctx, "am.mutual_plans.search")
    return JSONResponse(content=_apply_envelope(
        "search_mutual_plans_am", result, query=name_query,
    ))


# ---------------------------------------------------------------------------
# 16. get_law_article_am
# ---------------------------------------------------------------------------
@router.get("/law_article", response_model=AMLawArticleResponse)
def rest_get_law_article(
    conn: DbDep,
    ctx: ApiContextDep,
    law_name_or_canonical_id: Annotated[str, Query(min_length=1, max_length=200)],
    article_number: Annotated[str, Query(min_length=1, max_length=40)],
) -> JSONResponse:
    """Exact 条文 lookup: '租税特別措置法' + '41の19' → full article text + amendment history."""
    result = autonomath_wrappers.get_law_article_am(
        law_name_or_canonical_id=law_name_or_canonical_id,
        article_number=article_number,
    )
    # O4: response includes amendment_history; tag with snapshot caveat.
    result = _attach_lifecycle_caveat(result)
    log_usage(
        conn, ctx, "am.law_article.get",
        params={"law_name": law_name_or_canonical_id, "article": article_number},
    )
    return JSONResponse(content=_apply_envelope(
        "get_law_article_am", result, query=law_name_or_canonical_id,
    ))


# ---------------------------------------------------------------------------
# 17. get_annotations  (V4 Phase 4 universal annotation surface)
# ---------------------------------------------------------------------------
@router.get("/annotations/{entity_id}", response_model=AMAnnotationsResponse)
def rest_get_annotations(
    entity_id: Annotated[str, Path(min_length=1, max_length=200, description="Stable entity identifier.")],
    conn: DbDep,
    ctx: ApiContextDep,
    kinds: Annotated[
        list[str] | None,
        Query(description="Filter on annotation kind (examiner_warning / examiner_correction / quality_score / validation_failure / ml_inference / manual_note). Repeat the param to OR-combine."),
    ] = None,
    include_internal: Annotated[
        bool,
        Query(description="Include visibility='internal' rows (default False = public only). 'private' is never returned."),
    ] = False,
    include_superseded: Annotated[
        bool,
        Query(description="Include superseded / expired annotations (default False = currently-live only)."),
    ] = False,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
) -> JSONResponse:
    """Return annotations, review signals, and quality scores for one entity."""
    result = annotation_tools.get_annotations(
        entity_id=entity_id,
        kinds=kinds,
        include_internal=include_internal,
        include_superseded=include_superseded,
        limit=limit,
    )
    log_usage(conn, ctx, "am.annotations.get", params={"entity_id": entity_id})
    return JSONResponse(content=_apply_envelope(
        "get_annotations", result, query=entity_id,
    ))


# ---------------------------------------------------------------------------
# 18. validate  (V4 Phase 4 generic validation rule dispatcher)
# ---------------------------------------------------------------------------
@router.post("/validate", response_model=AMValidateResponse)
def rest_validate(
    conn: DbDep,
    ctx: ApiContextDep,
    applicant_data: Annotated[
        dict[str, Any],
        Body(
            embed=True,
            description=(
                "Applicant intake dict, e.g. "
                "{'plan': {'start_year': 2026, 'desired_amount_man_yen': 1500}, "
                "'identity': {'age': 42, 'birth_date': '1983-08-12'}, "
                "'behavioral': {'training_hours_per_year': 9000}}. "
                "Hashed via canonical JSON (sha256) for the result cache key."
            ),
        ),
    ],
    entity_id: Annotated[
        str | None,
        Body(
            embed=True,
            description=(
                "Optional am_entities.canonical_id. Filters rules pinned via "
                "scope_entity_id and is part of the cache key."
            ),
        ),
    ] = None,
    scope: Annotated[
        str,
        Body(
            embed=True,
            description=(
                "applies_to scope. Default 'intake' selects the 6 generic "
                "predicates ported from autonomath.intake_consistency_rules."
            ),
        ),
    ] = "intake",
) -> JSONResponse:
    """汎用 intake 検証 — am_validation_rule の active 述語を applicant_data に対して評価し
    rule 単位の passed/failed/deferred を返す (deferred = jpintel 内で評価できない外部依存述語)."""
    result = validation_tools._validate_impl(
        applicant_data=applicant_data,
        entity_id=entity_id,
        scope=scope,
    )
    log_usage(conn, ctx, "am.validate", params={"scope": scope, "entity_id": entity_id})
    return JSONResponse(content=_apply_envelope(
        "validate", result, query=entity_id,
    ))


# ---------------------------------------------------------------------------
# 19. get_provenance  (V4 Phase 4 universal source/license window)
# ---------------------------------------------------------------------------
@router.get("/provenance/{entity_id}", response_model=AMProvenanceResponse)
def rest_get_provenance(
    entity_id: Annotated[
        str,
        Path(min_length=1, max_length=200, description="am_entities.canonical_id (TEXT)"),
    ],
    conn: DbDep,
    ctx: ApiContextDep,
    include_facts: Annotated[
        bool,
        Query(
            description=(
                "If True, also return per-fact provenance via am_entity_facts.source_id "
                "(NULL on legacy rows pre-2026-04-25 — those facts are skipped). "
                "Default False = entity-level sources only."
            ),
        ),
    ] = False,
    fact_limit: Annotated[
        int,
        Query(ge=1, le=1000, description="Max facts when include_facts=True (default 200)."),
    ] = 200,
) -> JSONResponse:
    """am_entity_source × am_source 一括返却 — 出典 URL / license / role / fetched_at + license_summary を 1 コール (migration 049, 99.17% license filled)."""
    result = provenance_tools.get_provenance(
        entity_id=entity_id,
        include_facts=include_facts,
        fact_limit=fact_limit,
    )
    log_usage(conn, ctx, "am.provenance.get", params={"entity_id": entity_id})
    return JSONResponse(content=_apply_envelope(
        "get_provenance", result, query=entity_id,
    ))


# ---------------------------------------------------------------------------
# 20. get_provenance_for_fact  (single fact source lookup)
# ---------------------------------------------------------------------------
@router.get("/provenance/fact/{fact_id}", response_model=AMProvenanceResponse)
def rest_get_provenance_for_fact(
    fact_id: Annotated[int, Path(ge=1, description="am_entity_facts.id (INTEGER PK)")],
    conn: DbDep,
    ctx: ApiContextDep,
) -> JSONResponse:
    """am_entity_facts.source_id → am_source 1 件 (NULL なら entity-level am_entity_source の候補 list に fallback)."""
    result = provenance_tools.get_provenance_for_fact(fact_id=fact_id)
    log_usage(conn, ctx, "am.provenance.fact", params={"fact_id": fact_id})
    return JSONResponse(content=_apply_envelope(
        "get_provenance_for_fact", result, query=str(fact_id),
    ))


# ---------------------------------------------------------------------------
# 21–24. Static resources + example profiles  (Phase A)
# ---------------------------------------------------------------------------
@router.get("/static", response_model=StaticResourceList)
def rest_list_static_resources(
    conn: DbDep,
    ctx: ApiContextDep,
) -> JSONResponse:
    """List 8 curated jpcite taxonomies (seido / glossary / money_types / obligations / dealbreakers / sector_combos / crop_library / exclusion_rules)."""
    results = static_resources.list_static_resources()
    log_usage(conn, ctx, "am.static.list", params={})
    return JSONResponse(content=_apply_envelope(
        "list_static_resources",
        {"total": len(results), "results": results},
    ))


@router.get("/static/{resource_id}", response_model=StaticResourceDetail)
def rest_get_static_resource(
    resource_id: Annotated[
        str,
        Path(min_length=1, max_length=64, description="Resource id; see /v1/am/static for the catalog."),
    ],
    conn: DbDep,
    ctx: ApiContextDep,
) -> JSONResponse:
    """Load one taxonomy/lookup file. Returns full JSON content + license."""
    try:
        result = static_resources.get_static_resource(resource_id)
    except static_resources.ResourceNotFoundError as exc:
        log_usage(conn, ctx, "am.static.get", params={"resource_id": resource_id, "result": "no_matching_records"})
        return JSONResponse(status_code=404, content=_apply_envelope(
            "get_static_resource",
            {"error": {"code": "no_matching_records", "message": str(exc)}},
            query=resource_id,
        ))
    log_usage(conn, ctx, "am.static.get", params={"resource_id": resource_id})
    return JSONResponse(content=_apply_envelope(
        "get_static_resource", result, query=resource_id,
    ))


@router.get("/example_profiles", response_model=ExampleProfileList)
def rest_list_example_profiles(
    conn: DbDep,
    ctx: ApiContextDep,
) -> JSONResponse:
    """List 5 canonical client-intake example payloads (PII-clean)."""
    results = static_resources.list_example_profiles()
    log_usage(conn, ctx, "am.example_profiles.list", params={})
    return JSONResponse(content=_apply_envelope(
        "list_example_profiles",
        {"total": len(results), "results": results},
    ))


@router.get("/example_profiles/{profile_id}", response_model=ExampleProfileDetail)
def rest_get_example_profile(
    profile_id: Annotated[
        str,
        Path(min_length=1, max_length=64, description="Profile id; see /v1/am/example_profiles."),
    ],
    conn: DbDep,
    ctx: ApiContextDep,
) -> JSONResponse:
    """Return one canonical client profile JSON as a complete-payload example."""
    try:
        result = static_resources.get_example_profile(profile_id)
    except static_resources.ResourceNotFoundError as exc:
        log_usage(conn, ctx, "am.example_profiles.get", params={"profile_id": profile_id, "result": "no_matching_records"})
        return JSONResponse(status_code=404, content=_apply_envelope(
            "get_example_profile",
            {"error": {"code": "no_matching_records", "message": str(exc)}},
            query=profile_id,
        ))
    log_usage(conn, ctx, "am.example_profiles.get", params={"profile_id": profile_id})
    return JSONResponse(content=_apply_envelope(
        "get_example_profile", result, query=profile_id,
    ))


# ---------------------------------------------------------------------------
# 25–26. 36協定 template renderer  (Phase A)
#
# OpenAPI exposure is itself flag-gated: when `AUTONOMATH_36_KYOTEI_ENABLED`
# is falsy (default), `include_in_schema=False` keeps the two paths out of
# `/openapi.json` and the exported `docs/openapi/v1.json`. The route is
# still registered and the request handler still returns the existing
# 503 `feature_disabled` envelope when called directly — schema-hide is
# additive on top of the runtime gate, not a replacement for it. Without
# this, the public OpenAPI advertises a regulated 労基法 §36 + 社労士法
# surface that the operator has not yet approved (legal review pending —
# see `docs/_internal/saburoku_kyotei_gate_decision_2026-04-25.md`).
# ---------------------------------------------------------------------------
@router.get(
    "/templates/saburoku_kyotei/metadata",
    response_model=TemplateMetadataResponse,
    include_in_schema=settings.saburoku_kyotei_enabled,
)
def rest_get_36_kyotei_metadata(
    conn: DbDep,
    ctx: ApiContextDep,
) -> JSONResponse:
    """Return 36協定 template metadata: required fields, aliases, authority, license.

    Gated behind ``settings.saburoku_kyotei_enabled``
    (env: ``AUTONOMATH_36_KYOTEI_ENABLED``). Returns 503 when disabled.
    """
    if not settings.saburoku_kyotei_enabled:
        log_usage(
            conn, ctx, "am.template.metadata",
            params={"template_id": "saburoku_kyotei", "result": "feature_disabled"},
        )
        return JSONResponse(
            status_code=503,
            content=_apply_envelope("get_36_kyotei_metadata_am", _SABUROKU_DISABLED_BODY),
        )
    meta = get_36_kyotei_metadata()
    log_usage(conn, ctx, "am.template.metadata", params={"template_id": "saburoku_kyotei"})
    return JSONResponse(content=_apply_envelope(
        "get_36_kyotei_metadata_am",
        {
            "template_id": meta["template_id"],
            "obligation": meta["obligation"],
            "authority": meta["authority"],
            "license": meta["license"],
            "quality_grade": meta["quality_grade"],
            "method": meta["method"],
            "uses_llm": meta["uses_llm"],
            "required_fields": get_36_kyotei_required(),
            "_disclaimer": _SABUROKU_DISCLAIMER,
        },
    ))


@router.post(
    "/templates/saburoku_kyotei",
    response_model=TemplateRenderResponse,
    include_in_schema=settings.saburoku_kyotei_enabled,
)
def rest_render_36_kyotei(
    fields: Annotated[
        dict[str, Any],
        Body(description="Required field map for the 36協定 template (canonical or Japanese aliases — see /v1/am/templates/saburoku_kyotei/metadata)."),
    ],
    conn: DbDep,
    ctx: ApiContextDep,
) -> JSONResponse:
    """Render the 36協定 (時間外労働・休日労働協定届). Pure deterministic substitution — no LLM.

    Gated behind ``settings.saburoku_kyotei_enabled``
    (env: ``AUTONOMATH_36_KYOTEI_ENABLED``). Returns 503 when disabled. Even
    when enabled, every response carries a ``_disclaimer`` field declaring the
    output a draft requiring 社労士 confirmation.
    """
    if not settings.saburoku_kyotei_enabled:
        log_usage(
            conn, ctx, "am.template.render",
            params={"template_id": "saburoku_kyotei", "result": "feature_disabled"},
        )
        return JSONResponse(
            status_code=503,
            content=_apply_envelope("render_36_kyotei_am", _SABUROKU_DISABLED_BODY),
        )
    try:
        text = render_36_kyotei(fields)
    except TemplateError as exc:
        log_usage(conn, ctx, "am.template.render", params={"template_id": "saburoku_kyotei", "result": "missing_required_arg"})
        return JSONResponse(
            status_code=422,
            content=_apply_envelope(
                "render_36_kyotei_am",
                {"error": {"code": "missing_required_arg", "message": str(exc)}},
            ),
        )
    meta = get_36_kyotei_metadata()
    log_usage(conn, ctx, "am.template.render", params={"template_id": "saburoku_kyotei"})
    return JSONResponse(content=_apply_envelope(
        "render_36_kyotei_am",
        {
            "template_id": meta["template_id"],
            "obligation": meta["obligation"],
            "authority": meta["authority"],
            "license": meta["license"],
            "quality_grade": meta["quality_grade"],
            "method": meta["method"],
            "uses_llm": meta["uses_llm"],
            "rendered_text": text,
            "_disclaimer": _SABUROKU_DISCLAIMER,
        },
    ))


# ---------------------------------------------------------------------------
# 27. Deep health  (Phase A — 10-check aggregate)
# Mounted on health_router (no AnonIpLimitDep) so monitors don't burn quota.
# ---------------------------------------------------------------------------
@health_router.get("/health/deep", response_model=DeepHealthResponse)
def rest_deep_health(
    request: Request,
    force: bool = False,
    fail_on_unhealthy: bool = False,
    fail_on_degraded: bool = False,
) -> JSONResponse:
    """10-check aggregate health (db + freshness + license + provenance + bundle + WAL).

    Unbilled, unlogged, no anonymous-IP rate limit — heartbeat surface for
    uptime monitors. Returns ``status`` ∈ {ok, degraded, unhealthy}.

    Responses are cached for 30 seconds; pass ``?force=true`` to bypass for
    debugging or post-deploy verification. Monitors that only understand HTTP
    status can pass ``?fail_on_unhealthy=true`` to receive 503 for an
    unhealthy aggregate, or ``?fail_on_degraded=true`` to require exact
    ``status=ok``.
    """
    doc = get_deep_health(force=force)
    health_status = str(doc.get("status") or "unknown")
    status_code = (
        503
        if (
            (fail_on_unhealthy and health_status == "unhealthy")
            or (fail_on_degraded and health_status != "ok")
        )
        else 200
    )
    if wants_envelope_v2(request):
        with contextlib.suppress(Exception):
            request.state.envelope_v2_served = True
        if health_status == "ok":
            env = StandardResponse.sparse(
                [doc],
                request_id=safe_request_id(request),
                query_echo={
                    "normalized_input": {"force": force},
                    "applied_filters": {"force": force},
                    "unparsed_terms": [],
                },
                billable_units=0,
            )
        else:
            env = StandardResponse.partial(
                [doc],
                request_id=safe_request_id(request),
                warnings=[f"deep health status={health_status}"],
                query_echo={
                    "normalized_input": {"force": force},
                    "applied_filters": {
                        "force": force,
                        "fail_on_unhealthy": fail_on_unhealthy,
                        "fail_on_degraded": fail_on_degraded,
                    },
                    "unparsed_terms": [],
                },
                billable_units=0,
            )
        return JSONResponse(
            content=env.to_wire(),
            status_code=status_code,
            headers={"X-Envelope-Version": "v2"},
        )
    return JSONResponse(content=doc, status_code=status_code)


# ---------------------------------------------------------------------------
# Wave 23 (2026-04-29): Industry packs REST surface — pack_construction /
# pack_manufacturing / pack_real_estate. Mirror the @mcp.tool decorated
# variants in mcp/autonomath_tools/industry_packs.py. Audience HTML
# (site/audiences/{construction,manufacturing,real_estate}.html) embeds
# example URLs against these paths, so they must route. Single ¥3/req
# metered (NO LLM inside, pure SQLite assembly).
# ---------------------------------------------------------------------------
@router.get("/pack_construction")
def rest_pack_construction(
    conn: DbDep,
    ctx: ApiContextDep,
    prefecture: Annotated[str | None, Query(max_length=20)] = None,
    employee_count: Annotated[int | None, Query(ge=0)] = None,
    revenue_yen: Annotated[int | None, Query(ge=0)] = None,
) -> JSONResponse:
    """[INDUSTRY-PACK] 建設業 (JSIC D) cohort: top 10 programs + 5 saiketsu + 3 通達."""
    result = industry_packs._pack_construction_impl(
        prefecture=prefecture,
        employee_count=employee_count,
        revenue_yen=revenue_yen,
    )
    log_usage(conn, ctx, "am.pack_construction")
    return JSONResponse(content=_apply_envelope(
        "pack_construction", result, query=prefecture or "",
    ))


@router.get("/pack_manufacturing")
def rest_pack_manufacturing(
    conn: DbDep,
    ctx: ApiContextDep,
    prefecture: Annotated[str | None, Query(max_length=20)] = None,
    employee_count: Annotated[int | None, Query(ge=0)] = None,
    revenue_yen: Annotated[int | None, Query(ge=0)] = None,
) -> JSONResponse:
    """[INDUSTRY-PACK] 製造業 (JSIC E) cohort: top 10 programs + 5 saiketsu + 3 通達."""
    result = industry_packs._pack_manufacturing_impl(
        prefecture=prefecture,
        employee_count=employee_count,
        revenue_yen=revenue_yen,
    )
    log_usage(conn, ctx, "am.pack_manufacturing")
    return JSONResponse(content=_apply_envelope(
        "pack_manufacturing", result, query=prefecture or "",
    ))


@router.get("/pack_real_estate")
def rest_pack_real_estate(
    conn: DbDep,
    ctx: ApiContextDep,
    prefecture: Annotated[str | None, Query(max_length=20)] = None,
    employee_count: Annotated[int | None, Query(ge=0)] = None,
    revenue_yen: Annotated[int | None, Query(ge=0)] = None,
) -> JSONResponse:
    """[INDUSTRY-PACK] 不動産業 (JSIC K) cohort: top 10 programs + 5 saiketsu + 3 通達."""
    result = industry_packs._pack_real_estate_impl(
        prefecture=prefecture,
        employee_count=employee_count,
        revenue_yen=revenue_yen,
    )
    log_usage(conn, ctx, "am.pack_real_estate")
    return JSONResponse(content=_apply_envelope(
        "pack_real_estate", result, query=prefecture or "",
    ))
