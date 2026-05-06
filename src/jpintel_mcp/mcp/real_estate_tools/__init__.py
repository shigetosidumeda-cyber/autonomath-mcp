"""AutonoMath Real Estate V5 MCP tool package — scaffolding.

P6-F W4 prep (T+200d, 2026-11-22 launch target). Migration 042
(real_estate_programs + zoning_overlays) lives in jpintel.db, schema
applied by C7. Real query implementations land **right before** T+200d;
this package is registration-only stubs returning
``{"status": "not_implemented_until_T+200d", ...}`` so the tool surface
can be advertised, OpenAPI exported, and integration tests scaffolded
without leaking unfinished SQL onto the live API.

Importing this package triggers @mcp.tool registration of 5 stubs:

  tools.py    search_real_estate_programs
              get_zoning_overlay
              search_real_estate_compliance
              dd_property_am
              cross_check_zoning

Registration runs at import time — the submodule
``from jpintel_mcp.mcp.server import mcp, _READ_ONLY`` and decorates
its functions with that shared mcp instance. Side-effect only; no
symbols are re-exported.

Gated by ``settings.real_estate_enabled`` (env
``AUTONOMATH_REAL_ESTATE_ENABLED``, default False). With the flag
False the preview stubs stay out of the public surface; flip True to expose
the real-estate stubs for partner contract preview.
"""

from . import tools  # noqa: F401  — decorator side-effect (5 stubs)
