"""Moat M7 — KG completion MCP wrapper (1 tool).

Surfaces the upstream M7 KG completion lane as ``predict_related_entities``.
Returns a structural PENDING envelope until the upstream M7 lane lands.
"""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import Field

from jpintel_mcp.mcp.server import _READ_ONLY, mcp

from ._shared import pending_envelope


@mcp.tool(annotations=_READ_ONLY)
def predict_related_entities(
    entity_id: Annotated[
        str,
        Field(min_length=1, max_length=256, description="Canonical jpcite entity_id."),
    ],
    limit: Annotated[
        int,
        Field(ge=1, le=50, description="Max related entities."),
    ] = 10,
) -> dict[str, Any]:
    """[AUDIT] Moat M7 KG completion. Returns up to limit related entities for
    the given canonical entity_id using deterministic KG walks (NO LLM).
    Returns a structural PENDING envelope until the upstream M7 lane lands.
    """
    return pending_envelope(
        tool_name="predict_related_entities",
        lane_id="M7",
        upstream_module="jpintel_mcp.moat.m7_kg_completion",
        schema_version="moat.m7.v1",
        primary_input={"entity_id": entity_id, "limit": limit},
    )
