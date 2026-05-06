"""Wave 32 MCP wrapper registration tests.

The REST endpoint modules are owned by another worker and may not exist at
MCP-wrapper import time. These tests only assert the wrapper module imports
cleanly and registers the expected tool names on the shared FastMCP instance.
"""

from __future__ import annotations

import importlib


EXPECTED_TOOLS = {
    "intel_scenario_simulate",
    "intel_competitor_landscape",
    "intel_portfolio_heatmap",
    "intel_news_brief",
    "intel_onboarding_brief",
    "intel_refund_risk",
    "intel_cross_jurisdiction",
}


def test_intel_wave32_module_imports_after_server() -> None:
    from jpintel_mcp.mcp import server  # noqa: F401

    mod = importlib.import_module("jpintel_mcp.mcp.autonomath_tools.intel_wave32")

    assert set(mod._TOOL_SUFFIXES) == EXPECTED_TOOLS


def test_intel_wave32_tools_registered() -> None:
    from jpintel_mcp.mcp import server

    importlib.import_module("jpintel_mcp.mcp.autonomath_tools.intel_wave32")

    names = {tool.name for tool in server.mcp._tool_manager.list_tools()}
    assert EXPECTED_TOOLS <= names
