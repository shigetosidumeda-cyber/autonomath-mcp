"""jpcite_tools.cross_source_score_v2 — Wave 46.47.C re-export alias for autonomath_tools.cross_source_score_v2.

See `jpcite_tools.__init__` for the full rationale. This wrapper exists
so callers can write `from jpintel_mcp.mcp.jpcite_tools.cross_source_score_v2 import …`
during the brand migration without touching the canonical implementation.

Pattern: star-import only — zero side-effect of its own. Any `@mcp.tool`
registration that happens inside `autonomath_tools.cross_source_score_v2` runs once
at first import (driven by `autonomath_tools/__init__.py`); importing
this alias does NOT re-register tools because Python module cache makes
the underlying module import idempotent.
"""

from jpintel_mcp.mcp.autonomath_tools.cross_source_score_v2 import *  # noqa: F401, F403
