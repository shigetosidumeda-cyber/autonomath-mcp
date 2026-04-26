"""LINE Messaging API bot surface.

Second product SKU on top of the core ¥3/req REST+MCP API. Structured-flow
(button-driven) bot that routes to `/v1/programs/prescreen` and renders
results as a LINE FlexMessage carousel. ¥500/月 (税込 ¥550) flat after 10
queries/month per LINE user.

Do NOT call an LLM from this module — the flow is fully deterministic.
See `src/jpintel_mcp/line/flow.py` for the state machine.
"""

from jpintel_mcp.line.config import LineSettings, line_settings

__all__ = ["LineSettings", "line_settings"]
