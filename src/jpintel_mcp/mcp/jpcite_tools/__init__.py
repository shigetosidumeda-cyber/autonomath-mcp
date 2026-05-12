"""jpcite_tools — file-path-level alias for autonomath_tools (Wave 46.47.C).

Brand rename strategy: the `autonomath` legacy file-path namespace stays
in tree as the canonical implementation; `jpcite_tools` is a thin alias
package that re-exports it so callers can migrate to the new brand name
without import path churn.

Per memory anchors:

* `project_jpcite_internal_autonomath_rename` — internal rename from the
  legacy autonomath brand to the canonical jpcite brand. Additive only.
* `feedback_destruction_free_organization` — never `rm`/`mv` the legacy
  package; only overlay with a new namespace.
* `feedback_dual_cli_lane_atomic` — re-export wrapper only, no duplicate
  registration (importing `jpcite_tools` does NOT re-run any `@mcp.tool`
  decorators because the submodules just re-export symbols rather than
  importing the live `autonomath_tools` modules a second time — Python
  module cache guarantees idempotent registration).

Pattern: this `__init__` re-exports everything from
`jpintel_mcp.mcp.autonomath_tools` via star-import. The 73 sibling
modules (one per `.py` in the legacy package, except the experimental
`intel_wave31`/`intel_wave32`/`cross_source_score_v2` files that are
gated by `AUTONOMATH_EXPERIMENTAL_MCP_ENABLED`) each star-import their
matched module so `jpcite_tools.<name>` is a drop-in alias for
`autonomath_tools.<name>` at every level.

Note on `__all__`: the legacy `autonomath_tools.__init__` does not
define `__all__`; the star-import here therefore re-exports whatever
public (non-underscore) symbols Python's default star-import rules
expose. Direct submodule access (`jpcite_tools.tools.foo`) works
because of the sibling re-export wrappers.

NO LLM / no brand rewrite of payloads. AUTONOMATH_* env vars and
am_* DB tables/views are unchanged — this is a file-path-only alias.
"""

# Re-export every public symbol from the legacy package. The sibling
# re-export wrappers (annotation_tools.py, audit_workpaper_v2.py, ...)
# handle module-level access; this star-import covers package-level
# attribute access (e.g. `from jpintel_mcp.mcp import jpcite_tools` then
# `jpcite_tools.<symbol>`).
from jpintel_mcp.mcp.autonomath_tools import *  # noqa: F401, F403
