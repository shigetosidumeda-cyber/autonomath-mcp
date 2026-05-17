"""Moat M9 — Document chunk search MCP wrapper (1 tool).

Surfaces the upstream M9 chunk search lane as ``search_chunks``. Returns
a structural PENDING envelope until the upstream M9 lane lands.
"""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import Field

from jpintel_mcp.mcp.server import _READ_ONLY, mcp

from ._shared import pending_envelope


@mcp.tool(annotations=_READ_ONLY)
def search_chunks(
    query: Annotated[
        str,
        Field(min_length=1, max_length=512, description="Chunk query text."),
    ],
    limit: Annotated[
        int,
        Field(ge=1, le=100, description="Max chunk hits."),
    ] = 10,
) -> dict[str, Any]:
    """[AUDIT] Moat M9 document chunk search over the unified jpcite chunk store
    (programs / laws / cases / 通達 / 採択事例). NO LLM call. Returns a structural
    PENDING envelope until the upstream M9 lane lands.
    """
    return pending_envelope(
        tool_name="search_chunks",
        lane_id="M9",
        upstream_module="jpintel_mcp.moat.m9_chunks",
        schema_version="moat.m9.v1",
        primary_input={"query": query[:128], "limit": limit},
    )
