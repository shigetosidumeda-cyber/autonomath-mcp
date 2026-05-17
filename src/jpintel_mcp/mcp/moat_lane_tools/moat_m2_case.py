"""Moat M2 — Case extraction MCP wrappers (2 tools).

Surfaces the upstream M2 case extraction lane:

* ``search_case_facts`` — FTS / semantic search over the case fact bank.
* ``get_case_extraction`` — fetch the canonical extraction for one case_id.

Both return a structural PENDING envelope until the upstream M2 lane lands.
"""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import Field

from jpintel_mcp.mcp.server import _READ_ONLY, mcp

from ._shared import pending_envelope


@mcp.tool(annotations=_READ_ONLY)
def search_case_facts(
    query: Annotated[
        str,
        Field(min_length=1, max_length=512, description="Case-fact query text."),
    ],
    limit: Annotated[
        int,
        Field(ge=1, le=100, description="Max hits."),
    ] = 20,
) -> dict[str, Any]:
    """[AUDIT, SENSITIVE — §52/§72] Moat M2 case-fact search over the unified
    案件 corpus (裁決 + 判例 + 行政処分). Returns a structural PENDING envelope
    until the upstream M2 lane lands.
    """
    return pending_envelope(
        tool_name="search_case_facts",
        lane_id="M2",
        upstream_module="jpintel_mcp.moat.m2_case_extraction",
        schema_version="moat.m2.v1",
        primary_input={"query": query[:128], "limit": limit},
    )


@mcp.tool(annotations=_READ_ONLY)
def get_case_extraction(
    case_id: Annotated[
        str,
        Field(min_length=1, max_length=128, description="Canonical jpcite case_id."),
    ],
) -> dict[str, Any]:
    """[AUDIT, SENSITIVE — §52/§72] Moat M2 fetch the canonical extraction
    (parties / issues / holdings / citations) for a single case_id. NO LLM.
    Returns a structural PENDING envelope until the upstream M2 lane lands.
    """
    return pending_envelope(
        tool_name="get_case_extraction",
        lane_id="M2",
        upstream_module="jpintel_mcp.moat.m2_case_extraction",
        schema_version="moat.m2.v1",
        primary_input={"case_id": case_id},
    )
