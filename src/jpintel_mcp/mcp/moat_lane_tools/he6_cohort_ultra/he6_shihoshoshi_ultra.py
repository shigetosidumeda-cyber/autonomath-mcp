"""HE-6 cohort ultra-deep — 司法書士 (shihoshoshi). D+-tier ¥100."""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import Field

from jpintel_mcp.mcp.server import _READ_ONLY, mcp

from ._core import build_he6_payload

_COHORT = "shihoshoshi"


@mcp.tool(annotations=_READ_ONLY)
def agent_cohort_ultra_shihoshoshi(
    query: Annotated[
        str,
        Field(min_length=1, max_length=512, description="司法書士 ultra-deep query."),
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
    """[AUDIT, SENSITIVE — §52/§47条の2/§72/§1/§3] Moat HE-6 cohort ultra — 司法書士.

    D+-tier ¥100 (33 units × ¥3). Returns 15 sections.

    Cost-saving claim: equivalent to ~21-turn Opus 4.7 multi-round
    reasoning (¥1,500). This endpoint: ¥100 = 1/15. Cohort: 司法書士.
    NO LLM inference. ``司法書士法 §3`` boundary enforced.
    """
    return build_he6_payload(
        cohort=_COHORT,
        query=query,
        entity_id=entity_id,
        context_token=context_token,
    )


__all__ = ["agent_cohort_ultra_shihoshoshi"]
