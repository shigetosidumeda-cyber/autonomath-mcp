"""SHADOW FILE — DO NOT IMPORT.

The canonical Lane N8 implementation lives at
``jpintel_mcp.mcp.moat_lane_tools.moat_n8_recipe``. This file is an orphan
copy that pre-dates the moat_lane_tools migration; it is kept on disk per
the repository's destruction-free organization rule
(``feedback_destruction_free_organization`` — rm/mv forbidden; banner +
index for triage) so the audit trail stays intact, but importing it would
double-register the ``list_recipes`` / ``get_recipe`` MCP tools and break
the FastMCP server boot.

Anyone importing this module by mistake will hit the ``ImportError`` raised
at the bottom of this file, which is the explicit signal to switch to the
canonical path. No code in the repository imports this module — verified by
``grep -r 'autonomath_tools.moat_n8_recipe' src/ tests/ scripts/``
(only same-file self-references in the shadow file remain).

Canonical path: ``jpintel_mcp.mcp.moat_lane_tools.moat_n8_recipe``.
Audit reference: D1 design audit 2026-05-17 (commit f01d285aa)
                 + integration fix 2026-05-17 (this commit).
"""

from __future__ import annotations

raise ImportError(
    "jpintel_mcp.mcp.autonomath_tools.moat_n8_recipe is a SHADOW file. "
    "Use jpintel_mcp.mcp.moat_lane_tools.moat_n8_recipe instead. "
    "See the module docstring for the destruction-free rationale."
)
