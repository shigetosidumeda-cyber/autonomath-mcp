"""Healthcare V3 MCP tool stubs — 6 tools, scaffolding only.

Each tool returns the sentinel envelope::

    {"status": "not_implemented_until_T+90d", "results": []}

so callers can wire integration tests / contract tests now and pick up
the real SQL implementation without re-shipping. The real query bodies
land in W4 (T+90d = 2026-08-04) right before the V3 healthcare cohort
launch. See ``docs/healthcare_v3_plan.md`` for the schedule.

The stub envelope is intentionally distinct from the canonical
``{total, limit, offset, results, ...}`` shape so an LLM agent that
silently dispatches to one of these tools in production gets a clear
``status`` field flagging "not yet implemented" rather than mistaking
``total=0`` for a confirmed empty result set.

Backing tables (DDL already live, see ``scripts/migrations/039_healthcare_schema.sql``):
  * ``medical_institutions``  — 医療法人 / 介護施設 / 薬局 (institution_type 6 値 enum)
  * ``care_subsidies``        — 介護報酬加算 + 自治体補助 (law_basis enum,
                                tier S-A-B-C-X)
  * ``laws``                  — 薬機法 / 医療法 / 介護保険法 (W2 ingest target)
  * ``enforcement_cases``     — 既存 1,185 行政処分 (W4 で healthcare 系 filter 追加)

Gated by ``AUTONOMATH_HEALTHCARE_ENABLED`` (default ``False``); see
``src/jpintel_mcp/mcp/healthcare_tools/__init__.py`` for registration
contract.
"""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import Field

from jpintel_mcp.mcp.server import _READ_ONLY, mcp

# Sentinel returned by every stub. Callers / contract tests should treat
# the presence of this exact ``status`` value as "implementation pending"
# and avoid asserting on ``total`` / ``results``.
_NOT_IMPL: dict[str, Any] = {
    "status": "not_implemented_until_T+90d",
    "results": [],
}


@mcp.tool(annotations=_READ_ONLY)
def search_healthcare_programs(
    query: Annotated[
        str | None,
        Field(
            description=(
                "Free-text search across 薬機法 / 医療法 / 介護保険法 関連 "
                "program names + description. 3+ chars recommended (FTS5 "
                "trigram). Example: '介護報酬加算' / '薬局機能強化' / "
                "'認知症対応型'."
            )
        ),
    ] = None,
    prefecture: Annotated[
        str | None,
        Field(
            description=(
                "都道府県 filter (e.g. '東京都', '大阪府'). Prefer full "
                "name; '全国' / 'national' filters to nationwide programs."
            )
        ),
    ] = None,
    law_basis: Annotated[
        str | None,
        Field(
            description=(
                "Root law filter. Valid: '薬機法' / '医療法' / "
                "'介護保険法' / '健康増進法'. Empty = no filter."
            )
        ),
    ] = None,
    limit: Annotated[
        int,
        Field(ge=1, le=100, description="Max rows (default 10, max 100)."),
    ] = 10,
    offset: Annotated[
        int,
        Field(ge=0, description="Pagination offset (default 0)."),
    ] = 0,
) -> dict[str, Any]:
    """薬機法 / 医療法 / 介護保険法 関連 program 全文検索.

    **実装予定: T+90d (2026-08-04)、現在は scaffolding。**
    Returns ``{"status": "not_implemented_until_T+90d", "results": []}``;
    do not surface this tool to end users until the SQL body lands.
    Gated by ``AUTONOMATH_HEALTHCARE_ENABLED`` (default ``False``) so
    runtime callers see the tool only when the flag is flipped post-W4.
    """
    # T+90d (2026-08-04): FTS5 query against `care_subsidies` +
    # `programs` joined on `program_law_refs`. Filter law_basis via
    # `laws.law_short` IN ('薬機法','医療法','介護保険法'). Apply
    # tier IN ('S','A','B','C') quarantine guard. Honor prefecture vs
    # 'national' bucket. See docs/healthcare_v3_plan.md §W4.
    return dict(_NOT_IMPL)


@mcp.tool(annotations=_READ_ONLY)
def get_medical_institution(
    canonical_id: Annotated[
        str,
        Field(
            description=(
                "Canonical institution ID (PK on `medical_institutions`). "
                "Format: 'mi_<uuid>'. Use search_healthcare_programs / "
                "dd_medical_institution_am first to discover IDs."
            ),
            min_length=1,
        ),
    ],
) -> dict[str, Any]:
    """医療法人 / 介護施設 / 薬局 PK lookup.

    **実装予定: T+90d (2026-08-04)、現在は scaffolding。**
    Returns the not_implemented sentinel envelope; gated by
    ``AUTONOMATH_HEALTHCARE_ENABLED`` so prod tools/list never advertises
    this until the SQL implementation ships.
    """
    # T+90d (2026-08-04): SELECT * FROM medical_institutions WHERE canonical_id = ?
    # plus optional JOIN to enforcement_cases / care_subsidies for the full
    # entity envelope. Returns 404 envelope on miss (see make_error pattern in
    # autonomath_tools.error_envelope).
    return dict(_NOT_IMPL)


@mcp.tool(annotations=_READ_ONLY)
def search_healthcare_compliance(
    query: Annotated[
        str | None,
        Field(
            description=(
                "Free-text across 行政処分 / 違反事例 (景表法 + 個情法 + "
                "薬機法 横断). Example: '不当表示' / '個人情報漏洩' / "
                "'未承認医薬品'."
            )
        ),
    ] = None,
    law_basis: Annotated[
        str | None,
        Field(
            description=(
                "Root law filter. Valid: '景表法' / '個情法' / '薬機法' / "
                "'医療法'. Empty = cross-law sweep."
            )
        ),
    ] = None,
    institution_type: Annotated[
        str | None,
        Field(
            description=(
                "Filter by institution_type (`medical_institutions` enum). "
                "Valid: '医療法人' / '介護施設' / '薬局' / "
                "'歯科医院' / '訪問介護' / 'その他'."
            )
        ),
    ] = None,
    limit: Annotated[
        int,
        Field(ge=1, le=100, description="Max rows (default 10, max 100)."),
    ] = 10,
    offset: Annotated[
        int,
        Field(ge=0, description="Pagination offset (default 0)."),
    ] = 0,
) -> dict[str, Any]:
    """景表法 + 個情法 + 薬機法 横断 compliance / 違反 search.

    **実装予定: T+90d (2026-08-04)、現在は scaffolding。**
    Returns the not_implemented sentinel envelope; gated by
    ``AUTONOMATH_HEALTHCARE_ENABLED`` (default False).
    """
    # T+90d (2026-08-04): SELECT enforcement_cases JOIN medical_institutions on
    # corp_number, filter root_law IN (景表法,個情法,薬機法,医療法). Use
    # FTS5 trigram on enforcement_cases.summary + violation_type. Honor
    # institution_type filter via the medical_institutions JOIN.
    return dict(_NOT_IMPL)


@mcp.tool(annotations=_READ_ONLY)
def check_drug_approval(
    drug_name: Annotated[
        str | None,
        Field(
            description=(
                "Drug 一般名 / 販売名 (PMDA approval ledger). 3+ chars "
                "recommended; PMDA does not expose surrogate IDs publicly "
                "so name-based lookup is the canonical path."
            )
        ),
    ] = None,
    approval_number: Annotated[
        str | None,
        Field(
            description=(
                "PMDA 承認番号 (format: '22XXXAMXXXXXX'). When present, "
                "drug_name is ignored — exact-match takes priority."
            )
        ),
    ] = None,
    limit: Annotated[
        int,
        Field(ge=1, le=50, description="Max rows (default 10, max 50)."),
    ] = 10,
) -> dict[str, Any]:
    """PMDA 承認医薬品 lookup.

    **実装予定: T+90d (2026-08-04)、現在は scaffolding。**
    Returns the not_implemented sentinel envelope; gated by
    ``AUTONOMATH_HEALTHCARE_ENABLED`` (default False). PMDA bulk ingest
    table (`pmda_drug_approvals`) is itself W3-pending.
    """
    # T+90d (2026-08-04): hit a `pmda_drug_approvals` table (DDL pending W3 ingest).
    # If approval_number provided, SELECT WHERE approval_number = ?. Otherwise
    # FTS5 over generic_name + brand_name. Surface approval_status enum:
    # ('承認','承認取消','承認整理','製造販売中止').
    return dict(_NOT_IMPL)


@mcp.tool(annotations=_READ_ONLY)
def search_care_subsidies(
    prefecture: Annotated[
        str | None,
        Field(
            description=(
                "都道府県 filter (e.g. '東京都'). 'national' = 国 (厚労省) "
                "原資 のみ。Empty = both 国 + 自治体."
            )
        ),
    ] = None,
    institution_type_target: Annotated[
        str | None,
        Field(
            description=(
                "Target institution. Valid: '介護施設' / '薬局' / "
                "'医療法人' / '訪問介護'. Empty = all."
            )
        ),
    ] = None,
    authority_level: Annotated[
        str | None,
        Field(
            description=(
                "Subsidy origin. Valid: '国' / '都道府県' / '市区町村' / "
                "'医療保険者'. Empty = all levels."
            )
        ),
    ] = None,
    tier: Annotated[
        str | None,
        Field(
            description=(
                "Quality tier filter. Valid: 'S' / 'A' / 'B' / 'C'. "
                "'X' (excluded) is always filtered out. Default = all "
                "non-X tiers."
            )
        ),
    ] = None,
    limit: Annotated[
        int,
        Field(ge=1, le=100, description="Max rows (default 10, max 100)."),
    ] = 10,
    offset: Annotated[
        int,
        Field(ge=0, description="Pagination offset (default 0)."),
    ] = 0,
) -> dict[str, Any]:
    """介護施設 / 薬局 / 医療法人 向け 補助金 検索.

    **実装予定: T+90d (2026-08-04)、現在は scaffolding。**
    Returns the not_implemented sentinel envelope; gated by
    ``AUTONOMATH_HEALTHCARE_ENABLED`` (default False).
    """
    # T+90d (2026-08-04): SELECT * FROM care_subsidies WHERE excluded=0 AND
    # tier IN ('S','A','B','C') with optional AND institution_type_target = ?
    # AND authority_level = ? AND prefecture = ?. ORDER BY tier, deadline_at.
    # Return canonical envelope {total, limit, offset, results}.
    return dict(_NOT_IMPL)


@mcp.tool(annotations=_READ_ONLY)
def dd_medical_institution_am(
    corp_number: Annotated[
        str,
        Field(
            description=(
                "13-digit 法人番号 (国税庁). Used to fan out across "
                "medical_institutions, enforcement_cases (行政処分), "
                "case_studies (採択事例), loan_programs (融資). "
                "Single-shot due-diligence envelope."
            ),
            pattern=r"^\d{13}$",
        ),
    ],
    include_enforcement: Annotated[
        bool,
        Field(description="Include 行政処分 history (default True)."),
    ] = True,
    include_subsidies: Annotated[
        bool,
        Field(description="Include 採択 + 補助 history (default True)."),
    ] = True,
    include_loans: Annotated[
        bool,
        Field(description="Include 融資 history (default False)."),
    ] = False,
) -> dict[str, Any]:
    """法人番号 1-shot due-diligence (cert + 行政処分 + 採択 + 融資).

    **実装予定: T+90d (2026-08-04)、現在は scaffolding。**
    Returns the not_implemented sentinel envelope; gated by
    ``AUTONOMATH_HEALTHCARE_ENABLED`` (default False).
    """
    # T+90d (2026-08-04): four parallel SELECTs:
    #   1) medical_institutions WHERE corp_number = ?
    #   2) enforcement_cases WHERE corp_number = ? (if include_enforcement)
    #   3) case_studies WHERE recipient_corp_number = ? (if include_subsidies)
    #   4) loan_programs JOIN am_loan_product on borrower_corp_number
    #      (if include_loans, autonomath.db cross-DB)
    # Bundle into a single envelope mirroring dd_profile_am shape.
    return dict(_NOT_IMPL)
