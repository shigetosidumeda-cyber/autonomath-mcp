"""Moat M10 — OpenSearch hybrid search MCP wrapper (PENDING-only stub).

The canonical M10 tool ``opensearch_hybrid_search`` is already shipped LIVE
through ``jpintel_mcp.mcp.autonomath_tools.opensearch_hybrid_tools``. This
module is a no-op placeholder so the moat lane catalogue stays uniform; the
``@mcp.tool`` registration intentionally happens in the autonomath_tools
sibling so this file does NOT register anything.

Importing this module is a deliberate no-op — the FastMCP server picks up
the LIVE registration first and ignores any subsequent duplicate.
"""

from __future__ import annotations

# Intentional no-op. The LIVE wrapper lives at:
#   jpintel_mcp.mcp.autonomath_tools.opensearch_hybrid_tools.opensearch_hybrid_search
#
# Keeping this file in the package preserves the lane catalogue order so the
# init.py / docs / tests can keep enumerating M1..M11 + N1..N9 contiguously
# without a hole at M10.
