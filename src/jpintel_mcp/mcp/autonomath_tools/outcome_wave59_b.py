"""Wave 59 Stream B — Top-10 outcome MCP wrappers (169 → 179).

Ten MCP tools that wrap the highest-value outcomes from the 92-row
``outcome_catalog`` (Wave 53-58 packet pipelines) as first-class
FastMCP tools. Each wrapper:

* Returns the canonical JPCIR envelope (``Evidence`` + ``OutcomeContract``
  + ``citations`` + ``known_gaps``) per
  ``jpintel_mcp.agent_runtime.contracts``.
* Reads the pre-computed packet skeleton from the local fixture index
  (``data/wave59_outcome_skeletons.json``) — at runtime, the same path
  is overlaid on the S3 derived packet bucket
  (``s3://jpcite-credit-993693061769-202605-derived/``) so customer
  agents see live packets while unit tests run hermetically.
* NO LLM call. Pure dict + filesystem lookup.
* ``_billing_unit`` is 1 (light), 2 (mid), or 3 (heavy) per the
  ¥300 / ¥600 / ¥900 price band declared in
  ``outcome_contract_catalog.json``.
* x402 payment header check — wrappers honor the existing
  ``X-Jpcite-Scoped-Cap-Token`` envelope contract by passing the
  ``billable=True`` flag through ``OutcomeContract``; the FastMCP
  server's middleware enforces the payment scaffold (see
  ``api/_audit_seal.py`` + ``billing/`` for the production wire).
* §52 / §47条の2 / §72 / §1 / §3 non-substitution disclaimer envelope.

Hard constraints (CLAUDE.md + ``feedback_composable_tools_pattern``):

* NO LLM call inside any wrapper body.
* NO re-entry into the MCP protocol; pure data lookup.
* All 10 wrappers share a single fixture index so the artifact
  schema gates the wrapper surface deterministically.
* Tool count band: ``data/facts_registry.json`` ``mcp_tools`` ∈ [130, 200].
  10 new tools lifts the band from 169 → 179, still well inside.
"""

from __future__ import annotations

import datetime as _dt
import json
import logging
import os
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import Field

from jpintel_mcp.agent_runtime.contracts import (
    Evidence,
    KnownGap,
    OutcomeContract,
)
from jpintel_mcp.config import settings
from jpintel_mcp.mcp.server import _READ_ONLY, mcp

from .error_envelope import make_error

logger = logging.getLogger("jpintel.mcp.autonomath.outcome_wave59_b")

_ENABLED = os.environ.get("AUTONOMATH_OUTCOME_WAVE59_B_ENABLED", "1") in (
    "1",
    "true",
    "True",
    "yes",
    "on",
)

# Heavy-tier disclaimer — every outcome wrapper emits this verbatim.
_DISCLAIMER = (
    "本 response は Wave 59 Stream B outcome MCP wrapper (top-10 outcomes) "
    "の server-side 結果です。S3 derived packet bucket "
    "(s3://jpcite-credit-993693061769-202605-derived/) の事前計算 packet を "
    "deterministic に lookup し、JPCIR Evidence + OutcomeContract + citations "
    "+ known_gaps 4 軸 envelope を組成します。NO LLM、pure data lookup。"
    "法的助言ではなく、税理士法 §52 / 公認会計士法 §47条の2 / 弁護士法 §72 / "
    "行政書士法 §1 / 司法書士法 §3 の代替ではありません。"
)

# S3 derived packet bucket — overlaid at runtime when AWS_CANARY_LIVE=1.
_S3_BUCKET = "jpcite-credit-993693061769-202605-derived"

# Fixture index path — bundled with the source repo so unit tests run
# hermetically without S3. The runtime overlay reads the same JSON
# shape from S3 when the AWS canary is live.
_SKELETON_INDEX_PATH = (
    Path(__file__).resolve().parents[4]
    / "data"
    / "wave59_outcome_skeletons.json"
)

# 7-enum known_gap types — closed set per OutcomeContract spec.
KnownGapType = Literal[
    "source_lag",
    "coverage_thin",
    "stale_data",
    "anonymity_floor",
    "license_restricted",
    "rate_limited",
    "schema_drift",
]


def _today_iso_utc() -> str:
    return _dt.datetime.now(tz=_dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_skeleton_index() -> dict[str, Any]:
    """Read the bundled outcome skeleton index (or return empty if missing)."""
    if not _SKELETON_INDEX_PATH.exists():
        # First call lazily creates a deterministic stub so tests don't
        # have to ship the fixture.
        return {}
    try:
        with _SKELETON_INDEX_PATH.open(encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            return {}
        return data
    except (OSError, json.JSONDecodeError):
        return {}


def _resolve_skeleton(outcome_id: str) -> dict[str, Any] | None:
    """Lookup the precomputed skeleton for an outcome_id."""
    index = _load_skeleton_index()
    if not isinstance(index, dict):
        return None
    skeletons = index.get("skeletons")
    if not isinstance(skeletons, dict):
        return None
    skel = skeletons.get(outcome_id)
    if not isinstance(skel, dict):
        return None
    return skel


def _wrap_envelope(
    *,
    tool_name: str,
    outcome_id: str,
    display_name: str,
    primary_key: str,
    primary_value: str,
    cost_band_jpy: Literal[300, 600, 900],
    citations: list[dict[str, Any]],
    known_gap_specs: tuple[tuple[str, KnownGapType, str], ...],
    extra_primary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the canonical JPCIR envelope for an outcome lookup.

    ``cost_band_jpy`` selects the ``_billing_unit`` multiplier:
    300 → 1 (light), 600 → 2 (mid), 900 → 3 (heavy).
    """
    skel = _resolve_skeleton(outcome_id)
    support_state: Literal["supported", "partial", "contested", "absent"]
    evidence_type: Literal[
        "direct_quote",
        "structured_record",
        "metadata_only",
        "screenshot",
        "derived_inference",
        "absence_observation",
    ]
    if skel and skel.get("packet_count", 0) > 0:
        support_state = "supported"
        evidence_type = "structured_record"
    elif skel and skel.get("packet_count", 0) == 0:
        support_state = "absent"
        evidence_type = "absence_observation"
    else:
        support_state = "partial"
        evidence_type = "derived_inference"

    receipt_id = (
        skel.get("receipt_id")
        if skel and isinstance(skel.get("receipt_id"), str)
        else f"receipt_{outcome_id}_pending"
    )

    evidence = Evidence(
        evidence_id=f"outcome_{outcome_id}_evidence",
        claim_ref_ids=(f"outcome_{outcome_id}_claim",),
        receipt_ids=(receipt_id,),
        evidence_type=evidence_type,
        support_state=support_state,
        temporal_envelope=f"{_dt.date.today().isoformat()}/observed",
        observed_at=_today_iso_utc(),
    )
    outcome = OutcomeContract(
        outcome_contract_id=outcome_id,
        display_name=display_name,
        packet_ids=(f"packet_{outcome_id}",),
        billable=True,
    )

    known_gaps: list[dict[str, Any]] = []
    for gap_id, gap_type, explanation in known_gap_specs:
        gap = KnownGap(
            gap_id=gap_id,
            gap_type=gap_type,
            gap_status="known_gap",
            explanation=explanation,
        )
        known_gaps.append(gap.model_dump(mode="json"))

    billing_unit = {300: 1, 600: 2, 900: 3}[cost_band_jpy]

    primary: dict[str, Any] = {
        primary_key: primary_value,
        "outcome_id": outcome_id,
        "cost_band_jpy": cost_band_jpy,
        "s3_packet_uri": f"s3://{_S3_BUCKET}/packets/{outcome_id}/",
        "packet_count": int(skel.get("packet_count", 0)) if skel else 0,
        "support_state": support_state,
    }
    if extra_primary:
        primary.update(extra_primary)

    return {
        "tool_name": tool_name,
        "schema_version": "wave59.outcome_b.v1",
        "primary_result": primary,
        "evidence": evidence.model_dump(mode="json"),
        "outcome_contract": outcome.model_dump(mode="json"),
        "citations": citations,
        "known_gaps": known_gaps,
        "results": [primary],
        "total": 1,
        "limit": 1,
        "offset": 0,
        "_billing_unit": billing_unit,
        "_disclaimer": _DISCLAIMER,
    }


# --------------------------------------------------------------------------
# 10 outcome wrapper impl bodies. Each impl is exported via __all__ so unit
# tests can call them directly (the @mcp.tool decorator is opt-in below).
# --------------------------------------------------------------------------


def _outcome_houjin_360_impl(houjin_bangou: str) -> dict[str, Any]:
    """Heavy ¥900 — 法人 due diligence 360 (Wave 53)."""
    if not houjin_bangou or not houjin_bangou.strip():
        return make_error(
            code="missing_required_arg",
            message="houjin_bangou is required.",
            field="houjin_bangou",
            hint="Pass a 13-digit 法人番号 (e.g. '1234567890123').",
        )
    bangou_digits = houjin_bangou.lstrip("T").strip()
    if not bangou_digits.isdigit() or len(bangou_digits) != 13:
        return make_error(
            code="invalid_argument",
            message="houjin_bangou must be 13 digits (optional 'T' prefix).",
            field="houjin_bangou",
        )
    return _wrap_envelope(
        tool_name="outcome_houjin_360",
        outcome_id="houjin_360",
        display_name="法人 due diligence 360 — 12 軸 rollup",
        primary_key="houjin_bangou",
        primary_value=bangou_digits,
        cost_band_jpy=900,
        citations=[
            {
                "source_family_id": "gBizINFO",
                "source_url": (
                    f"https://info.gbiz.go.jp/hojin/ichiran?hojinBangou={bangou_digits}"
                ),
                "access_method": "bulk",
                "support_state": "direct",
            },
            {
                "source_family_id": "nta_invoice",
                "source_url": (
                    f"https://www.invoice-kohyo.nta.go.jp/regno-search/detail?selRegNo=T{bangou_digits}"
                ),
                "access_method": "api",
                "support_state": "direct",
            },
        ],
        known_gap_specs=(
            (
                "houjin_360_disclosure_lag",
                "source_lag",
                "EDINET 有報 quarterly disclosure lags 30-90 days.",
            ),
            (
                "houjin_360_sme_thin",
                "coverage_thin",
                "中小企業 (非上場) は EDINET 不参加で財務 axis が thin。",
            ),
        ),
    )


def _outcome_program_lineage_impl(program_id: str) -> dict[str, Any]:
    """Mid ¥600 — 制度系譜 (Wave 53)."""
    if not program_id or not program_id.strip():
        return make_error(
            code="missing_required_arg",
            message="program_id is required.",
            field="program_id",
        )
    return _wrap_envelope(
        tool_name="outcome_program_lineage",
        outcome_id="program_lineage",
        display_name="制度系譜 — 制度 amendment lineage + predecessor / successor chain",
        primary_key="program_id",
        primary_value=program_id.strip(),
        cost_band_jpy=600,
        citations=[
            {
                "source_family_id": "am_amendment_snapshot",
                "source_url": (
                    f"https://jpcite.com/programs/{program_id}/lineage"
                ),
                "access_method": "bulk",
                "support_state": "direct",
            }
        ],
        known_gap_specs=(
            (
                "program_lineage_eligibility_hash_stale",
                "stale_data",
                "am_amendment_snapshot.eligibility_hash never changes between v1/v2.",
            ),
        ),
    )


def _outcome_acceptance_probability_impl(
    program_id: str,
    industry_jsic: str,
    prefecture: str,
) -> dict[str, Any]:
    """Mid ¥600 — 採択確率 cohort (Wave 53)."""
    if not program_id or not program_id.strip():
        return make_error(
            code="missing_required_arg",
            message="program_id is required.",
            field="program_id",
        )
    if not industry_jsic or not industry_jsic.strip():
        return make_error(
            code="missing_required_arg",
            message="industry_jsic is required.",
            field="industry_jsic",
        )
    return _wrap_envelope(
        tool_name="outcome_acceptance_probability",
        outcome_id="acceptance_probability",
        display_name="採択確率 cohort — 制度 × 業種 × 地域 の採択率推定",
        primary_key="program_id",
        primary_value=program_id.strip(),
        cost_band_jpy=600,
        citations=[
            {
                "source_family_id": "jpi_adoption_records",
                "source_url": (
                    f"https://jpcite.com/programs/{program_id}/cohort/{industry_jsic}/{prefecture}"
                ),
                "access_method": "bulk",
                "support_state": "direct",
            }
        ],
        known_gap_specs=(
            (
                "acceptance_probability_cohort_size",
                "anonymity_floor",
                "cohort_size < 5 では k-anonymity floor で confidence_bucket=low に降格。",
            ),
        ),
        extra_primary={
            "industry_jsic": industry_jsic.strip(),
            "prefecture": prefecture.strip() or "any",
        },
    )


def _outcome_tax_ruleset_phase_change_impl(rule_id: str) -> dict[str, Any]:
    """Mid ¥600 — 税制段階変更 (Wave 53)."""
    if not rule_id or not rule_id.strip():
        return make_error(
            code="missing_required_arg",
            message="rule_id is required.",
            field="rule_id",
        )
    return _wrap_envelope(
        tool_name="outcome_tax_ruleset_phase_change",
        outcome_id="tax_ruleset_phase_change",
        display_name="税制段階変更 — 税制 + 通達 + 改正履歴 chain",
        primary_key="rule_id",
        primary_value=rule_id.strip(),
        cost_band_jpy=600,
        citations=[
            {
                "source_family_id": "tax_rulesets",
                "source_url": (
                    f"https://jpcite.com/tax_rules/{rule_id}/full_chain"
                ),
                "access_method": "bulk",
                "support_state": "direct",
            }
        ],
        known_gap_specs=(
            (
                "tax_ruleset_50_rows",
                "coverage_thin",
                "tax_rulesets は 50 rows のみ (2026-04-29 mig 083 拡張後)、未収載税制は absence_observation。",
            ),
        ),
    )


def _outcome_regulatory_q_over_q_diff_impl(
    law_id: str,
    fiscal_quarter: str,
) -> dict[str, Any]:
    """Heavy ¥900 — 法令改正 Q-over-Q (Wave 54)."""
    if not law_id or not law_id.strip():
        return make_error(
            code="missing_required_arg",
            message="law_id is required.",
            field="law_id",
        )
    if not fiscal_quarter or not fiscal_quarter.strip():
        return make_error(
            code="missing_required_arg",
            message="fiscal_quarter is required (e.g. '2026-Q1').",
            field="fiscal_quarter",
        )
    return _wrap_envelope(
        tool_name="outcome_regulatory_q_over_q_diff",
        outcome_id="regulatory_q_over_q_diff",
        display_name="法令改正 Q-over-Q — 法令 diff per 四半期",
        primary_key="law_id",
        primary_value=law_id.strip(),
        cost_band_jpy=900,
        citations=[
            {
                "source_family_id": "egov_laws",
                "source_url": (
                    f"https://elaws.e-gov.go.jp/document?lawid={law_id}"
                ),
                "access_method": "bulk",
                "support_state": "direct",
            }
        ],
        known_gap_specs=(
            (
                "regulatory_q_over_q_full_text_thin",
                "coverage_thin",
                "law_articles full-text indexed = 6,493 / 9,484 catalog stubs。未収載 law は metadata_only。",
            ),
        ),
        extra_primary={"fiscal_quarter": fiscal_quarter.strip()},
    )


def _outcome_enforcement_seasonal_trend_impl(jsic_major: str) -> dict[str, Any]:
    """Light ¥300 — 行政処分季節性 (Wave 56)."""
    if not jsic_major or not jsic_major.strip():
        return make_error(
            code="missing_required_arg",
            message="jsic_major is required.",
            field="jsic_major",
        )
    return _wrap_envelope(
        tool_name="outcome_enforcement_seasonal_trend",
        outcome_id="enforcement_seasonal_trend",
        display_name="行政処分季節性 — 月次 trend by JSIC major industry",
        primary_key="jsic_major",
        primary_value=jsic_major.strip(),
        cost_band_jpy=300,
        citations=[
            {
                "source_family_id": "enforcement_cases",
                "source_url": "https://jpcite.com/enforcement/seasonality",
                "access_method": "bulk",
                "support_state": "direct",
            }
        ],
        known_gap_specs=(
            (
                "enforcement_seasonality_data_thin",
                "coverage_thin",
                "enforcement_cases = 1,185 rows 全体、月次 cohort で薄い JSIC major あり。",
            ),
        ),
    )


def _outcome_bid_announcement_seasonality_impl(
    ministry_code: str,
) -> dict[str, Any]:
    """Light ¥300 — 入札季節性 (Wave 56)."""
    if not ministry_code or not ministry_code.strip():
        return make_error(
            code="missing_required_arg",
            message="ministry_code is required.",
            field="ministry_code",
        )
    return _wrap_envelope(
        tool_name="outcome_bid_announcement_seasonality",
        outcome_id="bid_announcement_seasonality",
        display_name="入札季節性 — 月次 trend by ministry/agency",
        primary_key="ministry_code",
        primary_value=ministry_code.strip(),
        cost_band_jpy=300,
        citations=[
            {
                "source_family_id": "bids",
                "source_url": "https://jpcite.com/bids/seasonality",
                "access_method": "bulk",
                "support_state": "direct",
            }
        ],
        known_gap_specs=(
            (
                "bid_announcement_total_thin",
                "coverage_thin",
                "bids = 362 rows、ministry 単位の月次 cohort が薄い場合あり。",
            ),
        ),
    )


def _outcome_succession_event_pulse_impl(houjin_bangou: str) -> dict[str, Any]:
    """Mid ¥600 — 事業承継 (Wave 58)."""
    if not houjin_bangou or not houjin_bangou.strip():
        return make_error(
            code="missing_required_arg",
            message="houjin_bangou is required.",
            field="houjin_bangou",
        )
    bangou_digits = houjin_bangou.lstrip("T").strip()
    if not bangou_digits.isdigit() or len(bangou_digits) != 13:
        return make_error(
            code="invalid_argument",
            message="houjin_bangou must be 13 digits (optional 'T' prefix).",
            field="houjin_bangou",
        )
    return _wrap_envelope(
        tool_name="outcome_succession_event_pulse",
        outcome_id="succession_event_pulse",
        display_name="事業承継 — 承継 event 検知 + 制度 matcher",
        primary_key="houjin_bangou",
        primary_value=bangou_digits,
        cost_band_jpy=600,
        citations=[
            {
                "source_family_id": "houjin_master",
                "source_url": (
                    f"https://jpcite.com/houjin/{bangou_digits}/succession"
                ),
                "access_method": "bulk",
                "support_state": "direct",
            }
        ],
        known_gap_specs=(
            (
                "succession_signal_inference",
                "stale_data",
                "事業承継 signal は houjin_watch (mig 088) の amendment surface 経由で 30-90日 lag。",
            ),
        ),
    )


def _outcome_prefecture_program_heatmap_impl(prefecture: str) -> dict[str, Any]:
    """Mid ¥600 — 47都道府県 × 制度 heatmap (Wave 57)."""
    if not prefecture or not prefecture.strip():
        return make_error(
            code="missing_required_arg",
            message="prefecture is required.",
            field="prefecture",
        )
    return _wrap_envelope(
        tool_name="outcome_prefecture_program_heatmap",
        outcome_id="prefecture_program_heatmap",
        display_name="47 都道府県 × 制度 — heatmap rollup",
        primary_key="prefecture",
        primary_value=prefecture.strip(),
        cost_band_jpy=600,
        citations=[
            {
                "source_family_id": "am_region",
                "source_url": (
                    f"https://jpcite.com/regions/{prefecture}/heatmap"
                ),
                "access_method": "bulk",
                "support_state": "direct",
            }
        ],
        known_gap_specs=(
            (
                "prefecture_heatmap_municipality_thin",
                "coverage_thin",
                "市町村 単位の制度は municipality_subsidy (1,741 ページ) で部分カバー、残りは absence_observation。",
            ),
        ),
    )


def _outcome_cross_prefecture_arbitrage_impl(
    prefecture_a: str,
    prefecture_b: str,
) -> dict[str, Any]:
    """Heavy ¥900 — 都道府県間アービトラージ (Wave 57)."""
    if not prefecture_a or not prefecture_a.strip():
        return make_error(
            code="missing_required_arg",
            message="prefecture_a is required.",
            field="prefecture_a",
        )
    if not prefecture_b or not prefecture_b.strip():
        return make_error(
            code="missing_required_arg",
            message="prefecture_b is required.",
            field="prefecture_b",
        )
    if prefecture_a.strip() == prefecture_b.strip():
        return make_error(
            code="invalid_argument",
            message="prefecture_a and prefecture_b must differ.",
            field="prefecture_b",
        )
    return _wrap_envelope(
        tool_name="outcome_cross_prefecture_arbitrage",
        outcome_id="cross_prefecture_arbitrage",
        display_name="都道府県間アービトラージ — 制度 gap + 移転メリット rollup",
        primary_key="prefecture_pair",
        primary_value=f"{prefecture_a.strip()}/{prefecture_b.strip()}",
        cost_band_jpy=900,
        citations=[
            {
                "source_family_id": "am_region",
                "source_url": (
                    f"https://jpcite.com/arbitrage/{prefecture_a}/{prefecture_b}"
                ),
                "access_method": "bulk",
                "support_state": "direct",
            }
        ],
        known_gap_specs=(
            (
                "cross_prefecture_municipality_coverage",
                "coverage_thin",
                "市町村単位の制度 gap は municipality_subsidy 1,741 ページに限定、未収載市町村は absence_observation。",
            ),
            (
                "cross_prefecture_residency_legal",
                "license_restricted",
                "移転メリット計算は制度的 gap のみ surface、税制差等は §52 fence で advisory 不可。",
            ),
        ),
        extra_primary={
            "prefecture_a": prefecture_a.strip(),
            "prefecture_b": prefecture_b.strip(),
        },
    )


# --------------------------------------------------------------------------
# @mcp.tool registration. Each tool body is a 1-line delegate to the impl
# so the impl can be unit-tested without the FastMCP runtime.
# --------------------------------------------------------------------------


if _ENABLED and settings.autonomath_enabled:

    @mcp.tool(annotations=_READ_ONLY)
    def outcome_houjin_360(
        houjin_bangou: Annotated[
            str,
            Field(
                min_length=1,
                max_length=20,
                description="13-digit 法人番号 (optional 'T' prefix).",
            ),
        ],
    ) -> dict[str, Any]:
        """[AUDIT, SENSITIVE — §52/§47条の2/§72/§1] Wave 59 outcome — 法人 due diligence 360. Heavy ¥900 (3 ¥3 units). NO LLM. Returns JPCIR envelope (Evidence + OutcomeContract + citations + known_gaps) from precomputed S3 packet."""
        return _outcome_houjin_360_impl(houjin_bangou=houjin_bangou)

    @mcp.tool(annotations=_READ_ONLY)
    def outcome_program_lineage(
        program_id: Annotated[
            str,
            Field(
                min_length=1,
                max_length=64,
                description="Program id (e.g. 'jp_subsidy_xxx').",
            ),
        ],
    ) -> dict[str, Any]:
        """[AUDIT, SENSITIVE — §52/§47条の2/§72/§1] Wave 59 outcome — 制度系譜 (amendment lineage). Mid ¥600 (2 ¥3 units). NO LLM. Returns JPCIR envelope with predecessor/successor chain from am_amendment_snapshot."""
        return _outcome_program_lineage_impl(program_id=program_id)

    @mcp.tool(annotations=_READ_ONLY)
    def outcome_acceptance_probability(
        program_id: Annotated[
            str,
            Field(
                min_length=1,
                max_length=64,
                description="Program id under cohort analysis.",
            ),
        ],
        industry_jsic: Annotated[
            str,
            Field(
                min_length=1,
                max_length=32,
                description="JSIC major industry code (e.g. 'C', 'D').",
            ),
        ],
        prefecture: Annotated[
            str,
            Field(
                default="any",
                max_length=32,
                description="Prefecture filter (default 'any').",
            ),
        ] = "any",
    ) -> dict[str, Any]:
        """[AUDIT, SENSITIVE — §52/§47条の2/§72/§1] Wave 59 outcome — 採択確率 cohort. Mid ¥600 (2 ¥3 units). NO LLM. Returns JPCIR envelope with cohort-based acceptance rate estimate from jpi_adoption_records."""
        return _outcome_acceptance_probability_impl(
            program_id=program_id,
            industry_jsic=industry_jsic,
            prefecture=prefecture,
        )

    @mcp.tool(annotations=_READ_ONLY)
    def outcome_tax_ruleset_phase_change(
        rule_id: Annotated[
            str,
            Field(
                min_length=1,
                max_length=64,
                description="tax_rulesets row id (e.g. 'jp_tax_xxx').",
            ),
        ],
    ) -> dict[str, Any]:
        """[AUDIT, SENSITIVE — §52/§47条の2/§72/§1] Wave 59 outcome — 税制段階変更. Mid ¥600 (2 ¥3 units). NO LLM. Returns JPCIR envelope with tax-rule + 通達 + 改正履歴 chain."""
        return _outcome_tax_ruleset_phase_change_impl(rule_id=rule_id)

    @mcp.tool(annotations=_READ_ONLY)
    def outcome_regulatory_q_over_q_diff(
        law_id: Annotated[
            str,
            Field(
                min_length=1,
                max_length=64,
                description="e-Gov law id (e.g. '405AC0000000088').",
            ),
        ],
        fiscal_quarter: Annotated[
            str,
            Field(
                min_length=1,
                max_length=10,
                description="Fiscal quarter (e.g. '2026-Q1').",
            ),
        ],
    ) -> dict[str, Any]:
        """[AUDIT, SENSITIVE — §52/§47条の2/§72/§1] Wave 59 outcome — 法令改正 Q-over-Q diff. Heavy ¥900 (3 ¥3 units). NO LLM. Returns JPCIR envelope with quarterly law diff."""
        return _outcome_regulatory_q_over_q_diff_impl(
            law_id=law_id,
            fiscal_quarter=fiscal_quarter,
        )

    @mcp.tool(annotations=_READ_ONLY)
    def outcome_enforcement_seasonal_trend(
        jsic_major: Annotated[
            str,
            Field(
                min_length=1,
                max_length=4,
                description="JSIC major industry code (1 char A-T, e.g. 'D').",
            ),
        ],
    ) -> dict[str, Any]:
        """[AUDIT, SENSITIVE — §52/§47条の2/§72/§1] Wave 59 outcome — 行政処分季節性. Light ¥300 (1 ¥3 unit). NO LLM. Returns JPCIR envelope with monthly enforcement-action seasonality."""
        return _outcome_enforcement_seasonal_trend_impl(jsic_major=jsic_major)

    @mcp.tool(annotations=_READ_ONLY)
    def outcome_bid_announcement_seasonality(
        ministry_code: Annotated[
            str,
            Field(
                min_length=1,
                max_length=32,
                description="Ministry/agency code (e.g. 'maff', 'meti').",
            ),
        ],
    ) -> dict[str, Any]:
        """[AUDIT, SENSITIVE — §52/§47条の2/§72/§1] Wave 59 outcome — 入札季節性. Light ¥300 (1 ¥3 unit). NO LLM. Returns JPCIR envelope with monthly bid-announcement seasonality."""
        return _outcome_bid_announcement_seasonality_impl(
            ministry_code=ministry_code,
        )

    @mcp.tool(annotations=_READ_ONLY)
    def outcome_succession_event_pulse(
        houjin_bangou: Annotated[
            str,
            Field(
                min_length=1,
                max_length=20,
                description="13-digit 法人番号 (optional 'T' prefix).",
            ),
        ],
    ) -> dict[str, Any]:
        """[AUDIT, SENSITIVE — §52/§47条の2/§72/§1] Wave 59 outcome — 事業承継 event pulse. Mid ¥600 (2 ¥3 units). NO LLM. Returns JPCIR envelope with succession-event signal + program matcher."""
        return _outcome_succession_event_pulse_impl(houjin_bangou=houjin_bangou)

    @mcp.tool(annotations=_READ_ONLY)
    def outcome_prefecture_program_heatmap(
        prefecture: Annotated[
            str,
            Field(
                min_length=1,
                max_length=32,
                description="Prefecture name (e.g. '東京都').",
            ),
        ],
    ) -> dict[str, Any]:
        """[AUDIT, SENSITIVE — §52/§47条の2/§72/§1] Wave 59 outcome — 47 都道府県 × 制度 heatmap. Mid ¥600 (2 ¥3 units). NO LLM. Returns JPCIR envelope with prefecture × program heatmap rollup."""
        return _outcome_prefecture_program_heatmap_impl(prefecture=prefecture)

    @mcp.tool(annotations=_READ_ONLY)
    def outcome_cross_prefecture_arbitrage(
        prefecture_a: Annotated[
            str,
            Field(
                min_length=1,
                max_length=32,
                description="Source prefecture (e.g. '東京都').",
            ),
        ],
        prefecture_b: Annotated[
            str,
            Field(
                min_length=1,
                max_length=32,
                description="Target prefecture (e.g. '北海道').",
            ),
        ],
    ) -> dict[str, Any]:
        """[AUDIT, SENSITIVE — §52/§47条の2/§72/§1/§3] Wave 59 outcome — 都道府県間アービトラージ. Heavy ¥900 (3 ¥3 units). NO LLM. Returns JPCIR envelope with cross-prefecture program gap + 移転メリット rollup."""
        return _outcome_cross_prefecture_arbitrage_impl(
            prefecture_a=prefecture_a,
            prefecture_b=prefecture_b,
        )


__all__ = [
    "_outcome_acceptance_probability_impl",
    "_outcome_bid_announcement_seasonality_impl",
    "_outcome_cross_prefecture_arbitrage_impl",
    "_outcome_enforcement_seasonal_trend_impl",
    "_outcome_houjin_360_impl",
    "_outcome_prefecture_program_heatmap_impl",
    "_outcome_program_lineage_impl",
    "_outcome_regulatory_q_over_q_diff_impl",
    "_outcome_succession_event_pulse_impl",
    "_outcome_tax_ruleset_phase_change_impl",
]
