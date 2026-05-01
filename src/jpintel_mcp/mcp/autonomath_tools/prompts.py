"""AutonoMath MCP prompts — pre-designed query templates (MCP 2025-06-18).

Wave-17 Agent-2 addition (2026-04-24).

The MCP `prompts` capability lets a server publish **named, argument-parameterized
templates** a client LLM can request. The client then fills the template
and executes the resulting message, usually composed with tool calls.

This file defines **12 prompt templates**. They are *instruction blobs* —
not direct SQL. Each returns a populated `messages` array the client LLM
feeds to its next completion, orchestrating a multi-tool workflow
(search_programs + search_tax_incentives + list_open_programs, etc.).

Design intent
-------------

  * Prompts encode **our expert opinion** about the right tool sequence.
    A naive LLM facing "find me grants" would try one keyword search;
    our `check_eligibility` prompt says "call search_programs with these
    4 filters, then call `search_tax_incentives` for combined package,
    then cross-reference with `search_enforcement` to flag risk".
  * Prompts are **self-disclosing** — the first line of each template
    tells the LLM "you are following the AutonoMath `<name>` playbook;
    cite source_url for every claim".
  * Prompts accept **typed arguments** via a JSON Schema (see
    `PromptArg`); invalid arguments are rejected server-side, not
    template-ed into the LLM.

Template engine: plain f-strings + small substitution helper. We avoid
Jinja2 to keep dependencies minimal.

Transport-agnostic wiring: this module exposes a pure Python registry
(`list_prompts`, `get_prompt`). FastMCP glue is in `register_prompts()`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PromptArg:
    """One argument for a prompt template."""

    name: str
    description: str
    required: bool = True
    type: str = "string"  # "string" | "integer" | "number" | "boolean"
    default: Any = None


@dataclass(frozen=True)
class PromptMeta:
    """Metadata for a single MCP prompt."""

    name: str
    description: str
    arguments: tuple[PromptArg, ...]
    template: str
    # Optional role override; default is "user".
    role: str = "user"

    def arguments_payload(self) -> list[dict[str, Any]]:
        return [
            {
                "name": a.name,
                "description": a.description,
                "required": a.required,
            }
            for a in self.arguments
        ]

    def validate(self, args: dict[str, Any]) -> dict[str, Any]:
        """Validate & coerce arguments. Raises ValueError on bad input."""
        merged: dict[str, Any] = {}
        for arg in self.arguments:
            if arg.name in args:
                v = args[arg.name]
                # Type coerce (best-effort; MCP clients pass strings).
                if arg.type == "integer":
                    try:
                        v = int(v)
                    except (TypeError, ValueError) as e:
                        raise ValueError(
                            f"argument '{arg.name}' must be integer, got {v!r}"
                        ) from e
                elif arg.type == "number":
                    try:
                        v = float(v)
                    except (TypeError, ValueError) as e:
                        raise ValueError(
                            f"argument '{arg.name}' must be number, got {v!r}"
                        ) from e
                elif arg.type == "boolean":
                    v = str(v).lower() in ("1", "true", "yes", "on")
                else:
                    v = str(v)
                merged[arg.name] = v
            elif arg.required:
                raise ValueError(f"missing required argument: {arg.name}")
            elif arg.default is not None:
                merged[arg.name] = arg.default
        # Reject unknown args (fail closed).
        extra = set(args) - {a.name for a in self.arguments}
        if extra:
            raise ValueError(f"unknown argument(s): {sorted(extra)}")
        return merged

    def render(self, args: dict[str, Any]) -> str:
        """Render template with validated arguments."""
        validated = self.validate(args)
        return _render(self.template, validated)


def _render(template: str, args: dict[str, Any]) -> str:
    """Minimal ``{name}``-style substitution. Leaves unmatched braces as-is,
    so any literal JSON examples in the template survive."""

    def _sub(match: re.Match[str]) -> str:
        key = match.group(1)
        if key in args:
            return str(args[key])
        return match.group(0)

    return re.sub(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}", _sub, template)


# ---------------------------------------------------------------------------
# Common preamble
# ---------------------------------------------------------------------------


_PREAMBLE = (
    "You are following the AutonoMath `{name}` playbook. Rules:\n"
    "  1. Call only tools listed in the playbook steps.\n"
    "  2. Cite every claim with the `source_url` from the envelope.\n"
    "  3. If a step returns zero results, say so; never fabricate.\n"
    "  4. Respect `autonomath://policy/no_hallucination`.\n"
    "  5. Primary-source policy: `autonomath://policy/primary_source`.\n"
)


def _wrap(name: str, body: str) -> str:
    return _PREAMBLE.replace("{name}", name) + "\n" + body


# ---------------------------------------------------------------------------
# 12 prompt templates
# ---------------------------------------------------------------------------


_PROMPTS: list[PromptMeta] = [
    PromptMeta(
        name="check_eligibility",
        description=(
            "Given a business profile, return the top-10 programs the business "
            "is most likely eligible for, with a confidence note and a cited "
            "source URL per row."
        ),
        arguments=(
            PromptArg(
                "business_profile",
                "Free-form text: 法人種別 / 所在都道府県 / 業種 / 従業員数 / 売上 / 直近の投資計画",
            ),
        ),
        template=_wrap(
            "check_eligibility",
            "Business profile:\n{business_profile}\n\n"
            "Steps:\n"
            "  1. Extract: prefecture_code (JIS 2-digit), industry_jsic,\n"
            "     size_bucket (sole/SME/large), investment_purpose.\n"
            "  2. Call search_programs with those 4 filters, limit=30.\n"
            "  3. Call list_open_programs with the same filters — discard\n"
            "     already-closed rows from step 2.\n"
            "  4. For each remaining row, fetch related_programs to surface\n"
            "     prerequisites and incompatibilities.\n"
            "  5. Rank by (amount_max desc, deadline asc); return top 10.\n"
            "  6. Output a markdown table: name | authority | amount_max |\n"
            "     deadline | confidence | source_url.\n"
            "  7. Add a one-line caveat for any row where key fields are\n"
            "     null.",
        ),
    ),
    PromptMeta(
        name="compare_rounds",
        description=(
            "Compare the last N rounds of a program: deadlines, cap amounts, "
            "acceptance rate, eligible size buckets."
        ),
        arguments=(
            PromptArg("program_name", "Program canonical name or id"),
            PromptArg("count", "Number of rounds to compare (default 3)",
                      required=False, type="integer", default=3),
        ),
        template=_wrap(
            "compare_rounds",
            "Target program: {program_name}\n"
            "Rounds to compare: {count}\n\n"
            "Steps:\n"
            "  1. Call search_programs(name={program_name}) to resolve canonical_id.\n"
            "  2. Call reason_answer(intent='i03', program_id=<id>, rounds={count}).\n"
            "  3. Build a table: round | deadline | amount_cap | acceptance_rate | "
            "target_size | source_url.\n"
            "  4. Flag any round where acceptance_rate dropped > 20 points vs. "
            "prior round.\n"
            "  5. If fewer than {count} rounds exist, say so explicitly.",
        ),
    ),
    PromptMeta(
        name="trace_program_history",
        description="Timeline of amendments to a program / underlying law.",
        arguments=(
            PromptArg("program_name", "Program canonical name or id"),
        ),
        template=_wrap(
            "trace_program_history",
            "Program: {program_name}\n\n"
            "Steps:\n"
            "  1. Resolve canonical_id via search_programs.\n"
            "  2. Call reason_answer(intent='i04', program_id=<id>).\n"
            "  3. For each `amends` / `replaces` edge returned, follow the\n"
            "     edge back once (not recursively) to get prior versions.\n"
            "  4. Output a chronological table: date | change_type\n"
            "     (amend/replace/new) | summary | source_url.\n"
            "  5. If the program `references_law` any law, include those\n"
            "     law amendment dates too (label them `law_amend`).",
        ),
    ),
    PromptMeta(
        name="audit_exclusions",
        description=(
            "Given a 法人番号 (corporate number), check whether the entity has "
            "any enforcement / 返還 / 処分 history that would exclude them from "
            "future programs."
        ),
        arguments=(
            PromptArg("houjin_bangou", "13-digit 法人番号 (e.g., 8010001213708)"),
        ),
        template=_wrap(
            "audit_exclusions",
            "法人番号: {houjin_bangou}\n\n"
            "Steps:\n"
            "  1. Call search_enforcement(houjin_bangou={houjin_bangou}).\n"
            "  2. If zero rows, output 'クリーン: 処分履歴なし (DB検索時点)' with\n"
            "     the snapshot date from `autonomath://stats/freshness`.\n"
            "  3. If rows exist, output one per line: date | authority |\n"
            "     type | amount_returned | source_url.\n"
            "  4. Add a risk note: 'Some programs require 5y no-enforcement\n"
            "     history; see each program's eligibility section.'",
        ),
    ),
    PromptMeta(
        name="deadline_brief",
        description=(
            "Programs open / deadlines within N days for a given prefecture + "
            "industry."
        ),
        arguments=(
            PromptArg("prefecture", "JIS 2-digit prefecture code (see autonomath://list/prefectures)"),
            PromptArg("industry", "JSIC industry code or keyword"),
            PromptArg("days", "Deadline horizon in days (default 30)",
                      required=False, type="integer", default=30),
        ),
        template=_wrap(
            "deadline_brief",
            "Prefecture: {prefecture}\n"
            "Industry:   {industry}\n"
            "Horizon:    {days} days\n\n"
            "Steps:\n"
            "  1. Call list_open_programs(prefecture={prefecture},\n"
            "     industry={industry}, days_until_deadline={days}, limit=50).\n"
            "  2. Sort by deadline asc.\n"
            "  3. Output a weekly-bucket digest:\n"
            "       ## 今週 (0-7d)   <rows>\n"
            "       ## 来週 (8-14d)  <rows>\n"
            "       ## 3週以内 (15-21d) <rows>\n"
            "       ## 30日以内 (22-{days}d) <rows>\n"
            "  4. Each row: name | amount_cap | authority | source_url.\n"
            "  5. Add a 'preparation lead-time' note for any row whose\n"
            "     deadline is <14d.",
        ),
    ),
    PromptMeta(
        name="tax_savings_analysis",
        description=(
            "For a given company profile, estimate annual tax savings available "
            "under current tax_measure records."
        ),
        arguments=(
            PromptArg("company_profile",
                      "Free-form: industry, annual_revenue_yen, planned_capex_yen, "
                      "planned_rd_spend_yen, hiring_plan."),
        ),
        template=_wrap(
            "tax_savings_analysis",
            "Company profile:\n{company_profile}\n\n"
            "Steps:\n"
            "  1. Extract: industry_jsic, capex_yen, rd_spend_yen, hiring_plan.\n"
            "  2. Call search_tax_incentives(industry=<x>, planned_investment=<capex>).\n"
            "  3. Call reason_answer(intent='i07', company=<profile>).\n"
            "  4. For each tax_measure row, compute a *ranged* savings\n"
            "     estimate (low = base rate, high = full bonus). Never\n"
            "     give a single point estimate.\n"
            "  5. Output a table: measure | statute | applicable_amount |\n"
            "     est_savings_yen (low..high) | deadline | source_url.\n"
            "  6. Append a disclaimer: 'Estimate only; consult a tax\n"
            "     accountant. AutonoMath has no affiliate relationship.'",
        ),
    ),
    PromptMeta(
        name="peer_benchmark",
        description=(
            "Compare the target municipality's program availability and uptake "
            "against 3 peer municipalities of similar population band."
        ),
        arguments=(
            PromptArg("municipality_code", "5-digit JIS municipality code"),
        ),
        template=_wrap(
            "peer_benchmark",
            "Municipality code: {municipality_code}\n\n"
            "Steps:\n"
            "  1. Call reason_answer(intent='i08', municipality={municipality_code}).\n"
            "  2. The envelope will include the target row + 3 peer rows\n"
            "     selected by population band + region cluster.\n"
            "  3. Output a 4-column table: metric | target | peer_avg |\n"
            "     delta.  Metrics: program_count, open_program_count,\n"
            "     total_amount_available, acceptance_rate.\n"
            "  4. Flag any metric where target is <70% of peer_avg.\n"
            "  5. Cite source_url from each peer row.",
        ),
    ),
    PromptMeta(
        name="grant_application_advisor",
        description=(
            "Given a program_id, output a structured application-writing guide "
            "(eligibility echo, required documents, common scoring criteria, "
            "deadline calendar)."
        ),
        arguments=(
            PromptArg("program_id", "canonical_id of the program"),
        ),
        template=_wrap(
            "grant_application_advisor",
            "Program id: {program_id}\n\n"
            "Steps:\n"
            "  1. Call reason_answer(intent='i09', program_id={program_id}).\n"
            "  2. Output four sections:\n"
            "     ### 1. Eligibility echo\n"
            "         Re-print the eligibility criteria verbatim (do not\n"
            "         paraphrase; applicants will use this checklist).\n"
            "     ### 2. Required documents\n"
            "         One row per document, with a note on whether the\n"
            "         authority specified a template.\n"
            "     ### 3. Scoring criteria\n"
            "         If the authority published weights, reproduce them.\n"
            "         Otherwise mark 'unpublished'.\n"
            "     ### 4. Deadline calendar\n"
            "         Application open / pre-consult / submission /\n"
            "         adoption announcement / performance report dates.\n"
            "  3. Every section must end with a `source_url`. No inference.",
        ),
    ),
    PromptMeta(
        name="combined_package_suggestion",
        description=(
            "Suggest a combined package (subsidy + tax + loan) that fits a "
            "business goal. Flags incompatibilities via graph edges."
        ),
        arguments=(
            PromptArg("business_goal",
                      "One sentence, e.g., '省エネ設備を2000万円導入して3名雇用したい'."),
        ),
        template=_wrap(
            "combined_package_suggestion",
            "Business goal:\n{business_goal}\n\n"
            "Steps:\n"
            "  1. Call reason_answer(intent='i10', goal={business_goal}).\n"
            "  2. The tool returns 3 suggested packages.  For each:\n"
            "     - List its programs (subsidy / tax / loan components).\n"
            "     - Show total_benefit estimate (ranged).\n"
            "     - For every pair of components, call related_programs\n"
            "       to check for `incompatible` edges; abort the package\n"
            "       if any exist.\n"
            "  3. Output three packages (or fewer, with an explanation).\n"
            "  4. Rank by (feasibility desc, total_benefit desc).\n"
            "  5. Always include a 'single-component fallback' row so the\n"
            "     applicant has a minimum-viable plan.",
        ),
    ),
    PromptMeta(
        name="japan_expansion_for_foreign_startup",
        description=(
            "Package a Japan-expansion briefing for a foreign startup: JETRO "
            "grants, tax exemptions, and regional incentives scaled to the "
            "declared budget."
        ),
        arguments=(
            PromptArg("industry", "Industry keyword (English OK — will be normalized)"),
            PromptArg("budget_yen", "JPY budget for Year-1 Japan entry", type="integer"),
        ),
        template=_wrap(
            "japan_expansion_for_foreign_startup",
            "Industry: {industry}\n"
            "Budget JPY: {budget_yen}\n\n"
            "Steps:\n"
            "  1. Normalize industry to JSIC via search_programs keyword lookup.\n"
            "  2. Call search_programs(authority='JETRO', industry=<jsic>).\n"
            "  3. Call search_tax_incentives(industry=<jsic>, scope='inbound').\n"
            "  4. Call search_programs(region_cluster='foreign_investment_zone').\n"
            "  5. Combine results, filter by min_investment <= {budget_yen}.\n"
            "  6. Output three sections:\n"
            "     ## Year-1 grants (JETRO + MOFA)\n"
            "     ## Tax exemptions (corporate tax + tariff)\n"
            "     ## Regional FDI zones (prefecture-level incentives)\n"
            "  7. Cite source_url per row; flag any program whose English\n"
            "     documentation is missing.",
        ),
    ),
    PromptMeta(
        name="law_to_programs",
        description=(
            "For a given e-Gov law id, list all programs that cite this law and "
            "summarize the citation context."
        ),
        arguments=(
            PromptArg("law_id", "e-Gov law id (e.g., 411AC0000000049 for 補助金適正化法)"),
        ),
        template=_wrap(
            "law_to_programs",
            "Law id: {law_id}\n\n"
            "Steps:\n"
            "  1. Call search_by_law(law_id={law_id}).\n"
            "  2. For each returned program, quote the 1-2 article numbers\n"
            "     cited (from the `references_law` edge metadata).\n"
            "  3. Output a table: program | cited_article | authority |\n"
            "     open_status | source_url.\n"
            "  4. End with a link to the e-Gov page for {law_id}.",
        ),
    ),
    PromptMeta(
        name="freshness_audit",
        description=(
            "Self-audit of AutonoMath's data freshness — useful when the client "
            "wants to know whether to re-query or trust a cache."
        ),
        arguments=(),
        template=_wrap(
            "freshness_audit",
            "Steps:\n"
            "  1. Read `autonomath://stats/freshness`.\n"
            "  2. Read `autonomath://list/authorities` and cross-reference\n"
            "     against expected authority counts (should be > 50).\n"
            "  3. Output:\n"
            "     - Snapshot timestamp\n"
            "     - Row counts per record_kind\n"
            "     - Top-5 oldest `updated_at` record_kinds\n"
            "     - A traffic-light verdict (green / amber / red) with\n"
            "       rationale.\n"
            "  4. If red, recommend 'query again in 1 hour or contact\n"
            "     support@autonomath.app'.",
        ),
    ),
]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def list_prompts() -> list[dict[str, Any]]:
    """Return the MCP `prompts/list` payload."""
    return [
        {
            "name": p.name,
            "description": p.description,
            "arguments": p.arguments_payload(),
        }
        for p in _PROMPTS
    ]


def get_prompt(name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return the MCP `prompts/get` payload for a single prompt name."""
    arguments = arguments or {}
    for p in _PROMPTS:
        if p.name == name:
            rendered = p.render(arguments)
            return {
                "description": p.description,
                "messages": [
                    {
                        "role": p.role,
                        "content": {
                            "type": "text",
                            "text": rendered,
                        },
                    }
                ],
            }
    raise KeyError(f"unknown prompt: {name}")


def get_prompt_meta(name: str) -> PromptMeta:
    for p in _PROMPTS:
        if p.name == name:
            return p
    raise KeyError(name)


def register_prompts(mcp: Any) -> None:
    """Wire prompts into a FastMCP server instance at merge time."""
    try:
        for p in _PROMPTS:
            def _make_cb(prompt: PromptMeta) -> Callable[..., dict[str, Any]]:
                def _cb(**kwargs: Any) -> dict[str, Any]:
                    return get_prompt(prompt.name, kwargs)

                return _cb

            mcp.prompt(
                p.name,
                description=p.description,
            )(_make_cb(p))
    except AttributeError:
        pass
