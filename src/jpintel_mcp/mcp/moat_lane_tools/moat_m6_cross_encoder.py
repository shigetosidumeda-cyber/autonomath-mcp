"""Moat M6 — Cross-encoder reranker MCP wrapper (1 tool).

Surfaces the upstream M6 cross-encoder rerank lane as ``rerank_results``.
Returns a structural PENDING envelope until the upstream M6 lane lands.
"""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import Field

from jpintel_mcp.mcp.server import _READ_ONLY, mcp

from ._shared import pending_envelope


@mcp.tool(annotations=_READ_ONLY)
def rerank_results(
    query: Annotated[
        str,
        Field(min_length=1, max_length=512, description="Query text for cross-encoder."),
    ],
    candidates: Annotated[
        list[str],
        Field(min_length=1, max_length=100, description="Candidate passages to rerank."),
    ],
) -> dict[str, Any]:
    """[AUDIT] Moat M6 cross-encoder reranker. Pairs (query, candidate) are scored
    by a local cross-encoder; NO LLM call. Returns a structural PENDING envelope
    until the upstream M6 lane lands.
    """
    return pending_envelope(
        tool_name="rerank_results",
        lane_id="M6",
        upstream_module="jpintel_mcp.moat.m6_cross_encoder",
        schema_version="moat.m6.v1",
        primary_input={"query": query[:128], "n_candidates": len(candidates)},
    )
