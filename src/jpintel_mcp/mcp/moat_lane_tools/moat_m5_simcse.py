"""Moat M5 — jpcite-BERT-v1 encode MCP wrapper (1 tool).

Surfaces the upstream M5 SimCSE / jpcite-BERT-v1 encoder lane as
``jpcite_bert_v1_encode``. Returns a structural PENDING envelope until the
upstream M5 lane lands.
"""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import Field

from jpintel_mcp.mcp.server import _READ_ONLY, mcp

from ._shared import pending_envelope


@mcp.tool(annotations=_READ_ONLY)
def jpcite_bert_v1_encode(
    text: Annotated[
        str,
        Field(min_length=1, max_length=2048, description="Text to encode."),
    ],
) -> dict[str, Any]:
    """[AUDIT] Moat M5 jpcite-BERT-v1 encode. Returns the SimCSE embedding vector
    for the provided text. Local CPU encoder, NO LLM API. Returns a structural
    PENDING envelope until the upstream M5 lane lands.
    """
    return pending_envelope(
        tool_name="jpcite_bert_v1_encode",
        lane_id="M5",
        upstream_module="jpintel_mcp.moat.m5_simcse",
        schema_version="moat.m5.v1",
        primary_input={"text_len": len(text)},
    )
