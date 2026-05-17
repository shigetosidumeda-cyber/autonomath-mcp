"""Moat M4 — Law embedding search MCP wrapper (1 tool).

Surfaces the upstream M4 law-embedding search lane as
``semantic_search_law_articles``. Returns a structural PENDING envelope
until the upstream M4 lane lands.
"""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import Field

from jpintel_mcp.mcp.server import _READ_ONLY, mcp

from ._shared import pending_envelope


@mcp.tool(annotations=_READ_ONLY)
def semantic_search_law_articles(
    query: Annotated[
        str,
        Field(min_length=1, max_length=512, description="Law / article query text."),
    ],
    limit: Annotated[
        int,
        Field(ge=1, le=50, description="Max law hits."),
    ] = 10,
) -> dict[str, Any]:
    """[AUDIT, SENSITIVE — §52/§47条の2/§72/§1] Moat M4 law-embedding semantic
    search. Hybrid FTS + e-Gov 法令 embedding over the 9,484-row law catalog +
    6,493 full-text law corpus. Returns a structural PENDING envelope until
    the upstream M4 lane lands.
    """
    return pending_envelope(
        tool_name="semantic_search_law_articles",
        lane_id="M4",
        upstream_module="jpintel_mcp.moat.m4_law_embedding",
        schema_version="moat.m4.v1",
        primary_input={"query": query[:128], "limit": limit},
    )
