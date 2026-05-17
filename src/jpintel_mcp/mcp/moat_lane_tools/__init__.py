"""Moat Lane MCP wrappers (M1-M11 + N1-N9 surface).

Auto-registers per-submodule MCP tools on import. Each submodule guards
itself with its own environment flag (default ON when the parent
``JPCITE_MOAT_LANES_ENABLED`` is also on). Importing this package is
the single seam ``server.py`` uses to surface the moat lane tools.

The package is intentionally a thin facade — only submodules that exist
at runtime are imported. Submodules absent from disk are silently
skipped so partial-progress checkouts do not break MCP server boot.
"""

from __future__ import annotations

import importlib
import logging

logger = logging.getLogger("jpintel.mcp.moat_lane_tools")

# Canonical submodule registry. Order is the natural moat-lane order
# (Mn = model-driven lanes / Nn = niche surface lanes). Each entry is a
# submodule whose import side-effect registers MCP tools via the
# ``@mcp.tool`` decorator.
_SUBMODULES: tuple[str, ...] = (
    "moat_m1_kg",
    "moat_m2_case",
    "moat_m3_figure",
    "moat_m4_law_embed",
    "moat_m5_simcse",
    "moat_m6_cross_encoder",
    "moat_m7_kg_completion",
    "moat_m8_citation",
    "moat_m9_chunks",
    "moat_m10_opensearch",
    "moat_m11_multitask",
    "moat_n1_artifact",
    "moat_n2_portfolio",
    "moat_n3_reasoning",
    "moat_n4_window",
    "moat_n5_synonym",
    "moat_n6_alert",
    "moat_n7_segment",
    "moat_n8_recipe",
    "moat_n9_placeholder",
    "he1_full_context",
    "he2_workpaper",
    "he3_briefing_pack",
    "he4_orchestrate",
    "cohort_lora_router",
    # _he_cohort_bootstrap reads ``he_cohort_fragment.yaml`` and discovers
    # HE-5 / HE-6 cohort-specific packages. [GG1 2026-05-17]
    "_he_cohort_bootstrap",
)

for _name in _SUBMODULES:
    try:
        importlib.import_module(f"{__name__}.{_name}")
    except ModuleNotFoundError:
        # Partial checkout — skip missing submodules silently.
        logger.debug("moat_lane_tools: skipping missing submodule %s", _name)
    except ImportError as exc:
        # Real import error inside a present submodule; surface it.
        logger.warning("moat_lane_tools: failed to import %s: %s", _name, exc)
