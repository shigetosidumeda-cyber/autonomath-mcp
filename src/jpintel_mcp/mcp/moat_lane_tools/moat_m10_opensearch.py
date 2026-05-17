"""Moat M10 — OpenSearch hybrid search MCP wrapper (PENDING-only stub).

The canonical M10 tool ``opensearch_hybrid_search`` is already shipped LIVE
through ``jpintel_mcp.mcp.autonomath_tools.opensearch_hybrid_tools``. This
module is a no-op placeholder so the moat lane catalogue stays uniform; the
``@mcp.tool`` registration intentionally happens in the autonomath_tools
sibling so this file does NOT register anything.

Importing this module is a deliberate no-op — the FastMCP server picks up
the LIVE registration first and ignores any subsequent duplicate.

Compile-time guard
------------------
Importing the FastMCP ``mcp`` symbol here is forbidden (it would let a
future edit attach ``@mcp.tool`` and silently double-register the M10
surface). The assertion below fails fast at import time if a future commit
ever brings the symbol into this module's namespace; the canonical
registration MUST stay at
``jpintel_mcp.mcp.autonomath_tools.opensearch_hybrid_tools``.
"""

from __future__ import annotations

# Intentional no-op. The LIVE wrapper lives at:
#   jpintel_mcp.mcp.autonomath_tools.opensearch_hybrid_tools.opensearch_hybrid_search
#
# Keeping this file in the package preserves the lane catalogue order so the
# init.py / docs / tests can keep enumerating M1..M11 + N1..N9 contiguously
# without a hole at M10.

# Compile-time guard: the @mcp.tool decorator MUST NOT be used in this stub.
# A future edit that imports ``mcp`` here would silently double-register the
# M10 surface and break the FastMCP boot. Assert at import time that the
# symbol is absent from this module's namespace.
assert "mcp" not in globals(), (
    "moat_m10_opensearch.py is a no-op stub — do NOT import the FastMCP "
    "`mcp` symbol here. Canonical M10 registration lives at "
    "jpintel_mcp.mcp.autonomath_tools.opensearch_hybrid_tools."
)
