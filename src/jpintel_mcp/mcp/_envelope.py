"""MCP-side adapter for the canonical v2 response envelope (§28.2).

Translates ``StandardResponse`` / ``StandardError`` into MCP 2025-06-18
``CallToolResult`` shape:

* Success → ``{"structuredContent": <wire>, "content": [{"type": "text", "text": <summary>}]}``
* Error   → ``{"isError": True, "structuredContent": <wire>, "content": [{"type": "text", "text": err.user_message}]}``

The MCP spec says hosts MAY use either ``structuredContent`` or ``content``;
we always populate both so that:

  - LLM hosts that read structured JSON (Claude Desktop / Cursor) ground
    on the canonical envelope.
  - LLM hosts that only render the `content[].text` array (older or
    minimal clients) still see a meaningful one-line summary.

The summary line format is deliberately short (≤ 120 chars) so context
windows don't blow up across hundreds of tool calls. Callers that want
a longer human-readable rendering should attach it as an additional
content block themselves before / after `wrap_for_mcp`.

Pure-Python; no LLM imports.
"""
from __future__ import annotations

from typing import Any

from jpintel_mcp.api._envelope import StandardError, StandardResponse


def _summary_text(env: StandardResponse) -> str:
    """Render a one-line human summary of a StandardResponse.

    Pattern:
      - rich:    "rich · 23 results"
      - sparse:  "sparse · 2 results · retry: broaden filters"
      - empty:   "empty · no_match · retry: drop prefecture filter"
      - partial: "partial · 5 results · 1 warning"
      - error:   handled by `wrap_for_mcp` (delegated to `_error_summary`)
    """
    n = len(env.results)
    if env.status == "rich":
        return f"rich · {n} result{'s' if n != 1 else ''}"
    if env.status == "sparse":
        hint = ""
        if env.retry_with:
            # Pull a short hint phrase if present.
            for k in ("hint", "broaden", "advice"):
                v = env.retry_with.get(k)
                if isinstance(v, str) and v:
                    hint = f" · retry: {v}"
                    break
        return f"sparse · {n} result{'s' if n != 1 else ''}{hint}"
    if env.status == "empty":
        reason = env.empty_reason or "no_match"
        hint = ""
        if env.retry_with:
            for k in ("hint", "broaden", "advice"):
                v = env.retry_with.get(k)
                if isinstance(v, str) and v:
                    hint = f" · retry: {v}"
                    break
        return f"empty · {reason}{hint}"
    if env.status == "partial":
        nw = len(env.warnings)
        return f"partial · {n} result{'s' if n != 1 else ''} · {nw} warning{'s' if nw != 1 else ''}"
    if env.status == "error":
        # Defensive — wrap_for_mcp normally peels error before we get here.
        if env.error:
            return f"error · {env.error.code}"
        return "error"
    return env.status  # forward-compat


def _error_summary(err: StandardError) -> str:
    """Short MCP-content summary for an error (≤120 chars)."""
    msg = err.user_message
    if len(msg) > 120:
        msg = msg[:117] + "…"
    return msg


def wrap_for_mcp(response: StandardResponse | StandardError) -> dict[str, Any]:
    """Convert a StandardResponse (or bare StandardError) into MCP CallToolResult shape.

    Successful (non-error) responses:

        {
          "structuredContent": <env.to_wire()>,
          "content": [{"type": "text", "text": "<one-line summary>"}]
        }

    Errors (either ``StandardResponse`` with status='error' OR a bare
    ``StandardError``):

        {
          "isError": true,
          "structuredContent": <wire>,
          "content": [{"type": "text", "text": err.user_message}]
        }

    Per MCP 2025-06-18, ``isError`` belongs at the result root (not inside
    ``structuredContent``). ``content`` is always a list of content
    blocks; we emit exactly one ``text`` block. Hosts may render that
    inline or expand the structured payload.
    """
    # Bare-StandardError path — wrap into a transient error envelope so
    # the wire shape stays uniform.
    if isinstance(response, StandardError):
        wire = {
            "error": response.model_dump(mode="json", exclude_none=True),
        }
        return {
            "isError": True,
            "structuredContent": wire,
            "content": [{"type": "text", "text": _error_summary(response)}],
        }

    wire = response.to_wire()

    if response.status == "error" and response.error is not None:
        return {
            "isError": True,
            "structuredContent": wire,
            "content": [
                {"type": "text", "text": _error_summary(response.error)},
            ],
        }

    return {
        "structuredContent": wire,
        "content": [{"type": "text", "text": _summary_text(response)}],
    }


__all__ = ["wrap_for_mcp"]
