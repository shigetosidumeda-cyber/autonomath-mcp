"""
MCP stdio tool: batch_execute.

Thin wrapper over api.batch_handler so MCP clients can send 50 sub-requests
in one frame. Same validation, same whitelist, same recursion guard.

NOTE: This module does NOT call any Anthropic API. Tool handlers are pure
in-process functions; the client's LLM agent is the one doing reasoning.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# Path shim so MCP process can import sibling api/ package
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from .batch_handler import (  # noqa: E402
    FORBIDDEN_TOOLS,
    MAX_ITEMS,
    QuotaState,
    ToolRegistry,
    handle_batch,
)


TOOL_SCHEMA = {
    "name": "batch_execute",
    "description": (
        "Execute up to 50 sub-tool-calls in one MCP frame. Returns per-id "
        "results. Partial failure is expected; check each response's status."
    ),
    "input_schema": {
        "type": "object",
        "required": ["requests"],
        "properties": {
            "requests": {
                "type": "array",
                "maxItems": MAX_ITEMS,
                "items": {
                    "type": "object",
                    "required": ["id", "tool", "params"],
                    "properties": {
                        "id": {"type": "string", "maxLength": 128},
                        "tool": {"type": "string"},
                        "params": {"type": "object"},
                    },
                },
            }
        },
    },
}


async def batch_execute(
    requests: list[dict],
    *,
    registry: ToolRegistry,
    quota: QuotaState,
) -> dict:
    """
    MCP-side entry. Mirrors REST /v1/batch semantics.

    Raises nothing to the client — all errors surface inside responses[] or
    in the top-level error field. Same recursion guard: batch_execute itself
    is in FORBIDDEN_TOOLS so it cannot be nested.
    """
    # Guard: MCP frames are objects, not raw lists. Wrap into envelope.
    body = {"requests": requests}

    # Double-check recursion guard (also enforced inside handler).
    for i, item in enumerate(requests or []):
        if isinstance(item, dict) and item.get("tool") in FORBIDDEN_TOOLS:
            return {
                "total": len(requests),
                "succeeded": 0,
                "billed": 0,
                "responses": [],
                "error": {
                    "code": "recursion_forbidden",
                    "message": f"requests[{i}].tool is self-reference",
                },
            }

    status, response = await handle_batch(body, registry, quota)
    response["_http_status_equivalent"] = status
    return response


def batch_execute_sync(
    requests: list[dict],
    *,
    registry: ToolRegistry,
    quota: QuotaState,
) -> dict:
    """Synchronous wrapper for MCP stdio transports that don't speak asyncio."""
    return asyncio.run(batch_execute(requests, registry=registry, quota=quota))


__all__ = ["batch_execute", "batch_execute_sync", "TOOL_SCHEMA"]
