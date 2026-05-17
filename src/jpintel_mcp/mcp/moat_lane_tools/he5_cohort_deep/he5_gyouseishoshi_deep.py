"""HE-5 cohort-specific deep — 行政書士 (gyouseishoshi). D-tier ¥30."""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import Field

from jpintel_mcp.mcp.server import _READ_ONLY, mcp

from ._core import build_he5_payload

_COHORT = "gyouseishoshi"


@mcp.tool(annotations=_READ_ONLY)
def agent_cohort_deep_gyouseishoshi(
    query: Annotated[
        str,
        Field(min_length=1, max_length=512, description="行政書士 free-text query."),
    ],
    entity_id: Annotated[
        str | None,
        Field(
            default=None,
            min_length=13,
            max_length=13,
            pattern=r"^\d{13}$",
            description="Optional 13-digit corporate number.",
        ),
    ] = None,
    context_token: Annotated[
        str | None,
        Field(
            default=None,
            min_length=8,
            max_length=128,
            description="Optional 24h-TTL session token.",
        ),
    ] = None,
) -> dict[str, Any]:
    """[AUDIT, SENSITIVE — §52/§47条の2/§72/§1/§3] Moat HE-5 cohort deep — 行政書士.

    D-tier ¥30 (10 units × ¥3). Returns 8 sections.

    Cost-saving claim: equivalent to ~7-turn Opus 4.7 reasoning with
    cohort-specific persona (¥500-700). This endpoint: ¥30 = 1/17-1/24.
    Cohort: 行政書士 (gyouseishoshi). NO LLM inference. ``行政書士法 §1``
    boundary enforced — scaffold + 一次 URL のみ.
    """
    return build_he5_payload(
        cohort=_COHORT,
        query=query,
        entity_id=entity_id,
        context_token=context_token,
    )


__all__ = ["agent_cohort_deep_gyouseishoshi"]
