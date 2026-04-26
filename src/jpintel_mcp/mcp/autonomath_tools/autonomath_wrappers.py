"""@mcp.tool wrappers for the 6 per-domain AutonoMath functions.

The underlying modules (gx_tool, loan_tool, enforcement_tool, mutual_tool,
sib_tool, law_article_tool) expose plain functions with positional args.
FastMCP requires Annotated[…, Field(...)] parameters for schema generation,
so this file provides thin wrappers that declare the MCP surface while
delegating the SQL work to the original modules.

All tool names carry the `_am` suffix to disambiguate from prod server.py
tools that query the flat jpintel.db schema. The `_am` variants query the
EAV-shaped autonomath.db (am_entities + am_* structured tables).

Tools added here (5 active; sib_contracts disabled — see NOTE below):
    search_gx_programs_am       GX / 脱炭素 / 再エネ / ZEB
    search_loans_am              am_loan_product (3-axis guarantor split)
    check_enforcement_am         am_enforcement_detail (法人番号 lookup)
    search_mutual_plans_am       am_insurance_mutual (小規模企業共済 等)
    get_law_article_am           am_law_article (条文 exact lookup)

Total contribution: 10 (tools.py) + 1 (tax_rule_tool) + 5 (here) = 16
autonomath tools on top of the jpintel.db core tools (see CLAUDE.md for
the live core+autonomath total).
"""
from __future__ import annotations

import functools
import sqlite3
from typing import Annotated, Any, Callable, Literal

from pydantic import Field

from jpintel_mcp.mcp._error_helpers import safe_internal_message
from jpintel_mcp.mcp.server import mcp, _READ_ONLY, _with_mcp_telemetry

from . import enforcement_tool, gx_tool, law_article_tool, loan_tool, mutual_tool

_logger = __import__("logging").getLogger("jpintel.mcp.am.wrappers")

# NOTE: sib_tool (SIB / PFS contracts) is not wrapped — am_sib_contract table
# has not been created in the deployed DB yet. Re-enable once ingest lands.


def _safe_envelope(retry_with: list[str]) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorator: convert uncaught exceptions (DB errors / bad input) into the
    canonical autonomath envelope with hint + retry_with. Agents 7/10 finding:
    bare `raise` made LLMs give up on 1 error; envelopes let them retry with
    an alternative tool.
    """
    def deco(fn: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(fn)
        def _wrap(*args: Any, **kwargs: Any) -> Any:
            try:
                return fn(*args, **kwargs)
            except sqlite3.OperationalError as e:
                # SQLite OperationalError messages can include table/column
                # names, SQL snippets, and file paths — all are internal
                # implementation detail and must not leak to the client.
                # Sanitize via incident id; ops can grep logs for details.
                msg, _incident = safe_internal_message(
                    e, logger=_logger, tool_name=fn.__name__
                )
                return {
                    "total": 0,
                    "results": [],
                    "error": {
                        "code": "db_unavailable",
                        "message": msg,
                        "hint": (
                            "DB snapshot may be missing a required table/column. "
                            "Try the fallback tool, or re-run later with a fresher snapshot."
                        ),
                        "retry_with": retry_with,
                    },
                }
            except (ValueError, KeyError) as e:
                # ValueError / KeyError messages typically include the user-
                # supplied value (e.g. "unknown loan_kind: foo"). That's
                # caller-originating data, safe to forward — but trim to
                # avoid accidental leak from validators that f-string in
                # internal context.
                raw = str(e)
                if len(raw) > 120:
                    raw = raw[:117] + "..."
                return {
                    "total": 0,
                    "results": [],
                    "error": {
                        "code": "invalid_enum",
                        "message": f"{type(e).__name__}: {raw}",
                        "hint": "check param spelling / enum values; retry with broader filters.",
                        "retry_with": retry_with,
                    },
                }
        return _wrap
    return deco


def _empty_state_hint(
    query_args: dict[str, Any],
    query_keys: tuple[str, ...] = ("query", "name_query", "target_name"),
    fallback_tools: tuple[str, ...] = ("list_open_programs", "enum_values_am"),
) -> str:
    """Build a Japanese suggestion based on which filters narrowed the result to 0.

    Priority order matches the empty_state_hint spec:
      1. Query string is 1-2 chars   -> 「クエリが短すぎる…」
      2. ≥2 narrow filters set       -> 「フィルタを 1 つ削減してください」
      3. No filter / no query at all -> 「list_open_programs / enum_values_am で…」
      4. Generic fallback            -> 「別のキーワードまたは関連 tool …」
    """
    text_q = ""
    for k in query_keys:
        v = query_args.get(k)
        if isinstance(v, str) and v.strip():
            text_q = v.strip()
            break

    non_query_filters = [
        (k, v) for k, v in query_args.items()
        if v not in (None, "", False) and k not in query_keys + ("limit", "offset")
    ]

    if 0 < len(text_q) <= 2:
        return "クエリが短すぎる可能性があります。3 文字以上で再試行してください。"
    if len(non_query_filters) >= 2:
        sample_key, sample_val = non_query_filters[0]
        return (
            f"フィルタを 1 つ削減してください。例: {sample_key}='{sample_val}' "
            "を外して再検索。"
        )
    if not text_q and not non_query_filters:
        names = " / ".join(fallback_tools)
        return f"{names} で利用可能な値を確認してください。"
    return "別のキーワードまたは関連 tool を試してください。"


# ---------------------------------------------------------------------------
# GX / 脱炭素
# ---------------------------------------------------------------------------
_GxTheme = Literal["ghg_reduction", "ev", "renewable", "zeb_zeh", "carbon_credit"]
_CompanySize = Literal["sme", "midsize", "large", "individual", "municipality", "farmer"]


@mcp.tool(annotations=_READ_ONLY)
@_with_mcp_telemetry
@_safe_envelope(retry_with=["search_programs", "search_tax_incentives"])
def search_gx_programs_am(
    theme: Annotated[
        _GxTheme,
        Field(description="GX theme: ghg_reduction / ev / renewable / zeb_zeh / carbon_credit."),
    ] = "ghg_reduction",
    company_size: Annotated[
        _CompanySize | None,
        Field(description="Applicant size filter (intersect target_types)."),
    ] = None,
    region: Annotated[
        str | None,
        Field(description="Region code (forward-compat; most GX programs are nationwide)."),
    ] = None,
    limit: Annotated[
        int,
        Field(ge=1, le=100, description="Max rows (default 20, max 100)."),
    ] = 20,
) -> dict[str, Any]:
    """DISCOVER (GX/Green): Search Green Transformation subsidies — emissions reduction, renewable energy, EV adoption, ZEB/ZEH (net-zero buildings), carbon credits. Returns curated programs with eligibility summaries.

    [DISCOVER-GX] 脱炭素 / 再エネ / EV / ZEB-ZEH / carbon_credit の curated 補助金を一覧 — theme×company_size で 「うち 中小企業が狙える EV 補助金」 を一発抽出 (am_entities の program:gx:% rows).

    WHAT: am_entities rows with canonical_id matching 'program:gx:%', joined
    with am_application_round for currently_open_rounds[]. eligibility_quick_summary
    is a 1-line string mashing target_types + rate + amount for LLM fast-scan.

    WHEN:
      - 「GX 脱炭素補助金で SME が使えるものは?」
      - 「ZEB-ZEH 補助金の公募中 round は?」
      - 「EV 法人購入補助金の一覧」

    WHEN NOT:
      - Non-GX themes (DX / 生産性 / 創業) → search_programs instead.
      - 税制ベースの脱炭素インセンティブ → search_tax_incentives / get_am_tax_rule.

    RETURN: {total, results[{canonical_id, program_name, theme, agency, program_kind,
             amount_max_yen, subsidy_rate, currently_open_rounds, past_rounds_count,
             target_types, eligibility_quick_summary, source_url, references_law[]}]}

    0 件の場合は `hint` (再検索の提案) と `retry_with` (関連 tool 候補) を返します。
    """
    rows = gx_tool.search_gx_programs(
        theme=theme, region=region, company_size=company_size, limit=limit,
    )
    if not rows:
        return {
            "total": 0,
            "results": [],
            "hint": _empty_state_hint(
                {
                    "theme": theme,
                    "company_size": company_size,
                    "region": region,
                },
                query_keys=(),
                fallback_tools=("list_open_programs", "search_tax_incentives"),
            ),
            "retry_with": ["list_open_programs", "search_tax_incentives"],
        }
    return {"total": len(rows), "results": rows}


# ---------------------------------------------------------------------------
# 融資
# ---------------------------------------------------------------------------
_LoanKind = Literal[
    "ippan", "trou", "seirei", "sanko", "sogyo",
    "rinsei", "saigai", "shingiseikyu", "kiki", "other",
]


@mcp.tool(annotations=_READ_ONLY)
@_with_mcp_telemetry
@_safe_envelope(retry_with=["search_loan_programs", "search_programs"])
def search_loans_am(
    loan_kind: Annotated[
        _LoanKind | None,
        Field(description="Loan kind: ippan/trou/seirei/sanko/sogyo/rinsei/saigai/shingiseikyu/kiki/other."),
    ] = None,
    no_collateral: Annotated[
        bool,
        Field(description="Filter for collateral_required='not_required' (無担保)."),
    ] = False,
    no_personal_guarantor: Annotated[
        bool,
        Field(description="Filter for personal_guarantor='not_required' (個人保証不要)."),
    ] = False,
    no_third_party_guarantor: Annotated[
        bool,
        Field(description="Filter for third_party_guarantor='not_required' (第三者保証不要)."),
    ] = False,
    max_amount_yen: Annotated[
        int | None,
        Field(ge=0, description="Exclude products whose limit_yen < this (need is covered)."),
    ] = None,
    min_amount_yen: Annotated[
        int | None,
        Field(ge=0, description="Require limit_yen >= this (minimum ceiling)."),
    ] = None,
    lender_entity_id: Annotated[
        str | None,
        Field(description="FK am_authority.canonical_id (e.g. 'authority:jfc')."),
    ] = None,
    name_query: Annotated[
        str | None,
        Field(description="LIKE %q% against primary_name."),
    ] = None,
    limit: Annotated[
        int,
        Field(ge=1, le=100, description="Max rows (default 10, max 100)."),
    ] = 10,
) -> dict[str, Any]:
    """[DISCOVER-LOAN] am_loan_product を 3 軸独立 (担保 / 個人保証 / 第三者保証) で 絞って 融資商品を列挙 — 無担保・無保証 の組合せ一発検索, 公庫 / 自治体制度融資を横断.

    WHAT: am_loan_product rows. Each row has 3-axis structured flags:
    collateral_required / personal_guarantor / third_party_guarantor ∈
    {required, not_required, case_by_case, exception, unknown}. ResponseRow
    also exposes `flags{no_collateral, no_personal_guarantor, no_third_party_guarantor}`
    so LLMs can reason without re-checking the enum.

    WHEN:
      - 「無担保・無保証人で借りられる公庫融資は?」
      - 「災害融資 で 担保不要 の制度」
      - 「中小企業庁 セーフティネット 4号 の限度額」

    WHEN NOT:
      - prod search_loan_programs (jpintel.loan_programs 108 rows) covers a
        different subset — the am table is broader (公庫 + 自治体制度融資 +
        商工中金) but overlaps。迷ったら両方叩いて diff 見て OK.

    RETURN: {result_count, results[{canonical_id, primary_name, lender_entity_id,
             loan_program_kind, limit_yen, limit_yen_special, interest_rate_base_pct,
             interest_rate_special_pct, term_years_max, grace_period_months,
             collateral_required, personal_guarantor, third_party_guarantor,
             eligibility_cond{…}, flags{no_collateral, no_personal_guarantor,
             no_third_party_guarantor}, source_url}]}

    0 件の場合は `hint` (再検索の提案) と `retry_with` (関連 tool 候補) を返します。
    """
    args = {
        "loan_kind": loan_kind,
        "no_collateral": no_collateral,
        "no_personal_guarantor": no_personal_guarantor,
        "no_third_party_guarantor": no_third_party_guarantor,
        "max_amount_yen": max_amount_yen,
        "min_amount_yen": min_amount_yen,
        "lender_entity_id": lender_entity_id,
        "name_query": name_query,
        "limit": limit,
    }
    payload = loan_tool.handle_tool_call(args)
    if int(payload.get("total", 0) or 0) == 0 and "error" not in payload:
        payload["hint"] = _empty_state_hint(
            args,
            query_keys=("name_query",),
            fallback_tools=("search_tax_incentives", "list_open_programs"),
        )
        payload["retry_with"] = ["search_tax_incentives", "list_open_programs"]
    return payload


# ---------------------------------------------------------------------------
# 行政処分
# ---------------------------------------------------------------------------


@mcp.tool(annotations=_READ_ONLY)
@_with_mcp_telemetry
@_safe_envelope(retry_with=["search_enforcement_cases"])
def check_enforcement_am(
    houjin_bangou: Annotated[
        str | None,
        Field(description="13-digit 法人番号 (fullwidth / hyphens stripped)."),
    ] = None,
    target_name: Annotated[
        str | None,
        Field(description="企業名 / 屋号 (space-normalized, exact-match after strip)."),
    ] = None,
    as_of_date: Annotated[
        str,
        Field(description="ISO date or 'today'. Controls active_exclusions window."),
    ] = "today",
) -> dict[str, Any]:
    """[ENFORCEMENT] 法人番号 or 企業名 から am_enforcement_detail を叩いて 「今この会社は補助金排除中か」 を即判定 — 営業前の デューデリ 必須チェック (補助金詐欺 / 二重請求 / 命令違反 の currently_excluded フラグ + 過去 5 年 history).

    WHAT: am_enforcement_detail (structured 行政処分 ledger). Either houjin
    or target_name required. Returns:
      - currently_excluded: bool  (排除期間内か at as_of_date)
      - active_exclusions: list[row] (いま効いている排除)
      - recent_history:    list[row] (past 5 years regardless of active)
      - all_count:         int

    WHEN:
      - 「この法人は今補助金を受給できる状態か?」(due diligence before 商談)
      - 「○○株式会社 の 行政処分 履歴」
      - 「名前で検索 (法人番号が手元に無い)」

    WHEN NOT:
      - prod search_enforcement_cases covers a different 独禁法 / 景表法 slice
        — use it for 広告表示違反 / 排除措置命令 一覧. Use this tool specifically
        for 補助金 / 助成金 排除期間 判定.

    RETURN: {queried{houjin_bangou, target_name, as_of_date}, found, currently_excluded,
             active_exclusions[…], recent_history[…], all_count}.
             When found=False, the canonical envelope is returned with
             ``error.code`` = ``no_matching_records`` (or ``invalid_input``
             for missing identifiers); ``error.coverage_scope`` echoes the
             1,185-row corpus scope so DD agents don't read absence as 与信.

    0 件の場合は `hint` (再検索の提案) と `retry_with` (関連 tool 候補) を返します。
    """
    return enforcement_tool.check_enforcement(
        houjin_bangou=houjin_bangou,
        target_name=target_name,
        as_of_date=as_of_date,
    )


# ---------------------------------------------------------------------------
# 共済 / 年金 / 労災
# ---------------------------------------------------------------------------
_PlanKind = Literal[
    "retirement_mutual", "bankruptcy_mutual", "dc_pension", "db_pension",
    "industry_pension", "welfare_insurance", "health_insurance", "other",
]
_TaxDedType = Literal[
    "small_enterprise_deduction", "idekodc", "group_retirement", "corp_expense", "none",
]


@mcp.tool(annotations=_READ_ONLY)
@_with_mcp_telemetry
@_safe_envelope(retry_with=["get_am_tax_rule", "search_tax_incentives"])
def search_mutual_plans_am(
    plan_kind: Annotated[
        _PlanKind | None,
        Field(description="Plan family: retirement_mutual / bankruptcy_mutual / dc_pension / etc."),
    ] = None,
    premium_monthly_yen: Annotated[
        int | None,
        Field(ge=0, description="Caller's intended monthly premium — rows accept if min<=budget<=max."),
    ] = None,
    tax_deduction_type: Annotated[
        _TaxDedType | None,
        Field(description="Tax-deduction class (small_enterprise_deduction / idekodc / etc.)."),
    ] = None,
    provider_entity_id: Annotated[
        str | None,
        Field(
            description=(
                "提供主体 (am_authority.canonical_id) で絞り込む FK. "
                "例: 'authority:smrj' (中小機構), 'authority:nta' (国税庁), "
                "'authority:mhlw:kosei' (厚労省年金局). "
                "enum_values_am('authority') の出力からコピー. None = 全 provider."
            ),
        ),
    ] = None,
    name_query: Annotated[
        str | None,
        Field(description="LIKE %q% against primary_name."),
    ] = None,
    limit: Annotated[
        int,
        Field(ge=1, le=100, description="Max rows (default 10, max 100)."),
    ] = 10,
) -> dict[str, Any]:
    """[DISCOVER-MUTUAL] 共済 / 年金 / 労災 を横断 — 小規模企業共済 / 倒産防止共済 / iDeCo+/DB/DC/労災特別加入 の掛金レンジ × 所得控除タイプ × 事業者区分 で抽出, 掛金月額を入れれば「この予算で入れる制度」を返す.

    WHAT: am_insurance_mutual structured ledger, joined with am_tax_rule via
    heuristic linking (tax_deduction_type → tax_measure canonical_id). Each
    row carries eligibility_cond JSON + linked_tax_rules list.

    WHEN:
      - 「小規模企業共済 と 倒産防止共済 の違い」
      - 「月 3 万 で入れる退職金 共済」
      - 「iDeCo+ の対象従業員要件」

    WHEN NOT:
      - 単独 税制だけ知りたい → get_am_tax_rule.
      - 助成金 (雇用関連) → search_programs.

    RETURN: {result_count, results[{canonical_id, primary_name, provider_entity_id,
             plan_kind, premium_min_yen, premium_max_yen, tax_deduction_type,
             benefit_type, eligibility_cond{…}, linked_tax_rules[…], source_url}]}.

    0 件の場合は `hint` (再検索の提案) と `retry_with` (関連 tool 候補) を返します。
    """
    args = {
        "plan_kind": plan_kind,
        "premium_monthly_yen": premium_monthly_yen,
        "tax_deduction_type": tax_deduction_type,
        "provider_entity_id": provider_entity_id,
        "name_query": name_query,
        "limit": limit,
    }
    payload = mutual_tool.handle_tool_call(args)
    if int(payload.get("total", 0) or 0) == 0 and "error" not in payload:
        payload["hint"] = _empty_state_hint(
            args,
            query_keys=("name_query",),
            fallback_tools=("search_loans_am", "list_static_resources_am"),
        )
        payload["retry_with"] = ["search_loans_am", "list_static_resources_am"]
    return payload


# ---------------------------------------------------------------------------
# 条文 exact lookup
# ---------------------------------------------------------------------------


@mcp.tool(annotations=_READ_ONLY)
@_with_mcp_telemetry
@_safe_envelope(retry_with=["search_laws", "get_law"])
def get_law_article_am(
    law_name_or_canonical_id: Annotated[
        str,
        Field(
            min_length=1,
            max_length=200,
            description="法律名 (canonical / short / 部分), または canonical_id ('law:…').",
        ),
    ],
    article_number: Annotated[
        str,
        Field(
            min_length=1,
            max_length=40,
            description="条番号 — '第41条の19' / '41の19' / '41-19' 等。空白除去後に canonical 形へ正規化。",
        ),
    ],
) -> dict[str, Any]:
    """[LAW-ARTICLE] 法律名+条番号 で am_law_article の 条文本文 を一発取得 — '租税特別措置法 第41条の19' のような 自然表記 を受け付けて canonical 形へ正規化して検索, 改正履歴 (last_amended) と source_url まで返す.

    WHAT: am_law_article structured ledger. Law resolution order:
      1. canonical_id ('law:sozei-tokubetsu')
      2. Exact canonical_name or short_name
      3. LIKE fallback on name (shortest match wins)

    Article normalization: '41の19' / '41-19' / '41.19' → '第41条の19'.

    WHEN:
      - 「租税特別措置法 第41条の19 の条文」
      - 「法人税法 施行令 5条 の本文」
      - 「措置法 41 条の 19 (原本)」

    WHEN NOT:
      - 全条文の横断 検索 → search_laws (prod).
      - 法律 メタ (施行日 / 最終改正) だけ → get_law (prod).

    RETURN: {found, law{canonical_id, canonical_name}, article_id, article_number,
             article_number_sort, title, text_summary, text_full, effective_from,
             effective_until, last_amended, source_url, source_fetched_at}.
             When not found, the canonical envelope is returned with
             ``error.code`` ∈ {seed_not_found, no_matching_records,
             missing_required_arg} and ``error.queried`` echoing the input.
    """
    return law_article_tool.get_law_article(
        law_name_or_canonical_id=law_name_or_canonical_id,
        article_number=article_number,
    )
