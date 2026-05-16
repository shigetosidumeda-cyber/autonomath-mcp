"""Wave 51 dim R — Federated-MCP recommendation MCP wrapper.

One MCP tool (``recommend_partner_for_gap``) that exposes the
deterministic capability-keyword matcher in
``jpintel_mcp.federated_mcp`` (Wave 51 dim R). The agent passes a
free-form gap query (e.g. "freee の請求書 #1234 が必要" or "look up
the pull request title on github") and the tool returns up to 3
curated partner MCP rows (freee / mf / notion / slack / github / linear).

The matcher is pure-Python substring + alias lookup — no LLM
inference, no HTTP, no embedding. The match runs in microseconds.

Hard constraints (CLAUDE.md):

* NO LLM call. Pure substring + alias lookup.
* No HTTP / partner proxying. Agents call partners directly using
  the official_url + mcp_endpoint_status fields returned.
* No self-reference (jpcite / jpintel / autonomath slugs rejected at
  registry load time).
* 1 ¥3/billable unit per tool call.
* §52 / §47条の2 / §72 / §1 non-substitution disclaimer envelope.
"""

from __future__ import annotations

import datetime as _dt
import logging
import os
from typing import Annotated, Any

from pydantic import Field

from jpintel_mcp.agent_runtime.contracts import Evidence, OutcomeContract
from jpintel_mcp.config import settings
from jpintel_mcp.federated_mcp import load_default_registry, recommend_handoff
from jpintel_mcp.mcp.server import _READ_ONLY, mcp

from .error_envelope import make_error

logger = logging.getLogger("jpintel.mcp.autonomath.wave51_dim_r_federated")

_ENABLED = os.environ.get("AUTONOMATH_WAVE51_DIM_R_ENABLED", "1") in (
    "1",
    "true",
    "True",
    "yes",
    "on",
)

_DISCLAIMER = (
    "本 response は Wave 51 dim R federated MCP 推薦の決定的キーワード照合結果 "
    "です。jpcite が答えられない gap query に対し、curated 6 partner shortlist "
    "(freee/mf/notion/slack/github/linear) から該当 partner を返します。"
    "agent は returned partner の MCP / REST を直接呼び出し、jpcite は proxy "
    "しません。税理士法 §52 / 公認会計士法 §47条の2 / 弁護士法 §72 / 行政書士法 §1 "
    "の代替ではありません。"
)


def _today_iso_utc() -> str:
    return _dt.datetime.now(tz=_dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _recommend_partner_for_gap_impl(
    query_gap: str,
    max_results: int,
) -> dict[str, Any]:
    """Match a gap query against the curated 6-partner federation."""
    if not query_gap or not query_gap.strip():
        return make_error(
            code="missing_required_arg",
            message="query_gap is required.",
            field="query_gap",
            hint="Pass a free-form gap description e.g. 'freee の請求書 #1234'.",
        )
    if max_results < 1 or max_results > 6:
        return make_error(
            code="out_of_range",
            message="max_results must be in [1, 6].",
            field="max_results",
        )

    try:
        partners = recommend_handoff(query_gap, max_results=max_results)
    except ValueError as exc:
        return make_error(
            code="invalid_argument",
            message=str(exc),
            field="query_gap",
        )

    rows: list[dict[str, Any]] = []
    for p in partners:
        # PartnerMcp HttpUrl fields need string conversion for JSON.
        rows.append(
            {
                "partner_id": p.partner_id,
                "name": p.name,
                "official_url": str(p.official_url),
                "mcp_endpoint_status": p.mcp_endpoint_status,
                "mcp_endpoint_url": (
                    str(p.mcp_endpoint) if p.mcp_endpoint else None
                ),
                "capabilities": list(p.capabilities),
            }
        )

    registry = load_default_registry()
    support_state = "supported" if rows else "absent"
    evidence_type = "absence_observation" if support_state == "absent" else "derived_inference"

    primary: dict[str, Any] = {
        "query_gap": query_gap,
        "max_results": max_results,
        "partners": rows,
        "total_hits": len(rows),
        "federation_size": len(registry),
    }

    evidence = Evidence(
        evidence_id="dim_r_recommend_partner_evidence",
        claim_ref_ids=("dim_r_recommend_partner_claim",),
        receipt_ids=(f"dim_r_recommend_{len(rows)}_of_{len(registry)}",),
        evidence_type=evidence_type,
        support_state=support_state,
        temporal_envelope=f"{_dt.date.today().isoformat()}/observed",
        observed_at=_today_iso_utc(),
    )
    outcome = OutcomeContract(
        outcome_contract_id="dim_r_recommend_partner_for_gap",
        display_name="Wave 51 dim R — federated MCP recommend partner for gap",
        packet_ids=("packet_dim_r_recommend_partner_for_gap",),
        billable=True,
    )

    return {
        "tool_name": "recommend_partner_for_gap",
        "schema_version": "wave51.dim_r.v1",
        "primary_result": primary,
        "evidence": evidence.model_dump(mode="json"),
        "outcome_contract": outcome.model_dump(mode="json"),
        "citations": [],
        "results": rows,
        "total": len(rows),
        "limit": max_results,
        "offset": 0,
        "_billing_unit": 1,
        "_disclaimer": _DISCLAIMER,
    }


if _ENABLED and settings.autonomath_enabled:

    @mcp.tool(annotations=_READ_ONLY)
    def recommend_partner_for_gap(
        query_gap: Annotated[
            str,
            Field(
                min_length=1,
                max_length=512,
                description=(
                    "Free-form gap query. Example: 'freee の請求書 #1234 が必要' "
                    "or 'look up the pull request title on github'. Japanese "
                    "or English; lowercased + tokenised against capability tags "
                    "and partner-specific alias map."
                ),
            ),
        ],
        max_results: Annotated[
            int,
            Field(
                ge=1,
                le=6,
                description="Maximum number of partners to return (1-6).",
            ),
        ] = 3,
    ) -> dict[str, Any]:
        """[AUDIT, SENSITIVE — §52/§47条の2/§72/§1] Wave 51 dim R federated MCP recommendation. Deterministic substring + alias matcher over the curated 6-partner federation (freee/mf/notion/slack/github/linear). Returns up to max_results partners with partner_id + name + official_url + mcp_endpoint_status + capabilities. Score-tied partners ordered by canonical partner_id ASC. NEVER includes a self-reference (jpcite/jpintel/autonomath rejected at registry load). NO LLM, no HTTP, single ¥3 unit."""
        return _recommend_partner_for_gap_impl(
            query_gap=query_gap,
            max_results=max_results,
        )


__all__ = ["_recommend_partner_for_gap_impl"]
