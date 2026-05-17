"""Moat M8 — Citation cross-lookup MCP wrappers (2 tools).

Surfaces the upstream M8 citation lane as two read-only MCP tools:

* ``find_cases_citing_law`` — cases citing a given law article.
* ``find_laws_cited_by_case`` — laws cited by a given case.

Both return a structural PENDING envelope until the upstream M8 lane lands.
"""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import Field

from jpintel_mcp.mcp.server import _READ_ONLY, mcp

from ._shared import pending_envelope


@mcp.tool(annotations=_READ_ONLY)
def find_cases_citing_law(
    law_id: Annotated[
        str,
        Field(min_length=1, max_length=128, description="e-Gov law_id or article id."),
    ],
    limit: Annotated[
        int,
        Field(ge=1, le=100, description="Max cases."),
    ] = 20,
) -> dict[str, Any]:
    """[AUDIT, SENSITIVE — §72/§52] Moat M8 citation lookup — return cases citing the
    given law article. Returns a structural PENDING envelope until the upstream
    M8 lane lands.
    """
    return pending_envelope(
        tool_name="find_cases_citing_law",
        lane_id="M8",
        upstream_module="jpintel_mcp.moat.m8_citation",
        schema_version="moat.m8.v1",
        primary_input={"law_id": law_id, "limit": limit},
    )


@mcp.tool(annotations=_READ_ONLY)
def find_laws_cited_by_case(
    case_id: Annotated[
        str,
        Field(min_length=1, max_length=128, description="jpcite canonical case_id."),
    ],
    limit: Annotated[
        int,
        Field(ge=1, le=100, description="Max laws."),
    ] = 20,
) -> dict[str, Any]:
    """[AUDIT, SENSITIVE — §72/§52] Moat M8 citation lookup — return laws cited by the
    given case. Returns a structural PENDING envelope until the upstream M8 lane
    lands.
    """
    return pending_envelope(
        tool_name="find_laws_cited_by_case",
        lane_id="M8",
        upstream_module="jpintel_mcp.moat.m8_citation",
        schema_version="moat.m8.v1",
        primary_input={"case_id": case_id, "limit": limit},
    )
