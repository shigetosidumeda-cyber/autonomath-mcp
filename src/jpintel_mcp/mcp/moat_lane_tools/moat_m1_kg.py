"""Moat M1 — Knowledge graph extraction MCP wrappers (2 tools).

Surfaces the upstream M1 KG extraction lane:

* ``extract_kg_from_text`` — extract canonical entities + relations from text.
* ``get_entity_relations`` — fetch outgoing/incoming relations for an entity.

Both return a structural PENDING envelope until the upstream M1 lane lands.
"""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import Field

from jpintel_mcp.mcp.server import _READ_ONLY, mcp

from ._shared import pending_envelope


@mcp.tool(annotations=_READ_ONLY)
def extract_kg_from_text(
    text: Annotated[
        str,
        Field(min_length=1, max_length=8192, description="Source text to KG-extract."),
    ],
    lang: Annotated[
        str,
        Field(pattern="^(ja|en)$", description="Language tag (ja / en)."),
    ] = "ja",
) -> dict[str, Any]:
    """[AUDIT, SENSITIVE — §52/§47条の2/§72/§1] Moat M1 KG extraction. Extract canonical
    entities + relations + facts from input text using the jpcite KG pipeline.
    Returns a structural PENDING envelope until the upstream M1 lane lands.
    """
    return pending_envelope(
        tool_name="extract_kg_from_text",
        lane_id="M1",
        upstream_module="jpintel_mcp.moat.m1_kg_extraction",
        schema_version="moat.m1.v1",
        primary_input={"text_len": len(text), "lang": lang},
    )


@mcp.tool(annotations=_READ_ONLY)
def get_entity_relations(
    entity_id: Annotated[
        str,
        Field(min_length=1, max_length=256, description="Canonical jpcite entity_id."),
    ],
    limit: Annotated[
        int,
        Field(ge=1, le=200, description="Max edges."),
    ] = 50,
) -> dict[str, Any]:
    """[AUDIT] Moat M1 KG edge lookup. Returns outgoing + incoming relations for
    the given canonical entity_id. Pure index walk (NO LLM). Returns a structural
    PENDING envelope until the upstream M1 lane lands.
    """
    return pending_envelope(
        tool_name="get_entity_relations",
        lane_id="M1",
        upstream_module="jpintel_mcp.moat.m1_kg_extraction",
        schema_version="moat.m1.v1",
        primary_input={"entity_id": entity_id, "limit": limit},
    )
