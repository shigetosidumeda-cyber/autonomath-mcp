"""Moat M3 — Figure search MCP wrappers (2 tools).

Surfaces the upstream M3 figure search lane:

* ``search_figures_by_topic`` — topic / caption / OCR search.
* ``get_figure_caption`` — fetch the caption + provenance for one figure_id.

Both return a structural PENDING envelope until the upstream M3 lane lands.
"""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import Field

from jpintel_mcp.mcp.server import _READ_ONLY, mcp

from ._shared import pending_envelope


@mcp.tool(annotations=_READ_ONLY)
def search_figures_by_topic(
    query: Annotated[
        str,
        Field(min_length=1, max_length=512, description="Topic / caption / OCR query."),
    ],
    limit: Annotated[
        int,
        Field(ge=1, le=50, description="Max results."),
    ] = 10,
) -> dict[str, Any]:
    """[AUDIT] Moat M3 figure search over the jpcite figure corpus (captions + OCR
    + CLIP-Japanese embeddings). Returns a structural PENDING envelope until
    the upstream M3 lane lands.
    """
    return pending_envelope(
        tool_name="search_figures_by_topic",
        lane_id="M3",
        upstream_module="jpintel_mcp.moat.m3_figure_search",
        schema_version="moat.m3.v1",
        primary_input={"query": query[:128], "limit": limit},
    )


@mcp.tool(annotations=_READ_ONLY)
def get_figure_caption(
    figure_id: Annotated[
        str,
        Field(min_length=1, max_length=128, description="Canonical figure_id."),
    ],
) -> dict[str, Any]:
    """[AUDIT] Moat M3 fetch caption + provenance for a single figure_id.
    Returns a structural PENDING envelope until the upstream M3 lane lands.
    """
    return pending_envelope(
        tool_name="get_figure_caption",
        lane_id="M3",
        upstream_module="jpintel_mcp.moat.m3_figure_search",
        schema_version="moat.m3.v1",
        primary_input={"figure_id": figure_id},
    )
