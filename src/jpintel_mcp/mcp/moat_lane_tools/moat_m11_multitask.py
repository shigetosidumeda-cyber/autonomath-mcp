"""Moat M11 — Multi-task inference MCP wrapper (1 tool).

Surfaces the upstream M11 multi-task inference lane as ``multitask_predict``.
Returns a structural PENDING envelope until the upstream M11 lane lands.
"""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import Field

from jpintel_mcp.mcp.server import _READ_ONLY, mcp

from ._shared import pending_envelope


@mcp.tool(annotations=_READ_ONLY)
def multitask_predict(
    text: Annotated[
        str,
        Field(min_length=1, max_length=4096, description="Input text."),
    ],
    tasks: Annotated[
        list[str],
        Field(
            min_length=1,
            max_length=10,
            description="Task tags: e.g. ['ner', 'rel', 'rank'].",
        ),
    ],
) -> dict[str, Any]:
    """[AUDIT] Moat M11 multi-task inference — runs the requested NLP heads in a
    single pass over the unified jpcite multi-task model (NER / REL / RANK).
    NO LLM API call. Returns a structural PENDING envelope until the upstream
    M11 lane lands.
    """
    return pending_envelope(
        tool_name="multitask_predict",
        lane_id="M11",
        upstream_module="jpintel_mcp.moat.m11_multitask",
        schema_version="moat.m11.v1",
        primary_input={"text_len": len(text), "tasks": tasks[:10]},
    )
