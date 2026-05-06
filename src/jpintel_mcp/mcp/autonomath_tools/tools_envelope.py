"""Envelope v2 adapter for AutonoMath MCP tools (Wave 11 Agent #6).

This module applies the `@with_envelope` decorator to each of the 10
tools in ``tools.py`` WITHOUT modifying the original file. Import this
module when you want customer-LLM-friendly v2 envelopes; import
``tools`` directly for raw legacy envelopes.

Tools wrapped (10):
  1. search_tax_incentives
  2. search_certifications
  3. list_open_programs
  4. search_by_law
  5. active_programs_at
  6. related_programs
  7. search_acceptance_stats
  8. enum_values
  9. intent_of
 10. reason_answer

Each wrapper preserves the original signature via functools.wraps so
that Pydantic-driven MCP tool discovery still sees the correct param
names and Annotated[...] metadata. The decorator is applied by
re-binding the symbol to a fresh decorated version — ``tools.py``
itself is untouched and remains backward-compatible.
"""

from __future__ import annotations

import sys
from pathlib import Path

# mcp_new/ is the import root for the package; make sure we can find it.
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from . import tools as _raw  # noqa: E402  (legacy tools module)
from .envelope_wrapper import with_envelope  # noqa: E402

# ---------------------------------------------------------------------------
# Wrapped tool bindings.
# The `query_arg` parameter tells the wrapper which kwarg to echo and
# feed to the router for empty-explanation. For non-query tools
# (enum_values, related_programs, active_programs_at) we point at the
# most query-like kwarg available so that `query_echo` is still useful.
# ---------------------------------------------------------------------------

search_tax_incentives = with_envelope("search_tax_incentives", query_arg="query")(
    _raw.search_tax_incentives
)

search_certifications = with_envelope("search_certifications", query_arg="query")(
    _raw.search_certifications
)

list_open_programs = with_envelope("list_open_programs", query_arg="query")(_raw.list_open_programs)

search_by_law = with_envelope("search_by_law", query_arg="law_name")(_raw.search_by_law)

active_programs_at = with_envelope("active_programs_at", query_arg="query")(_raw.active_programs_at)

related_programs = with_envelope("related_programs", query_arg="program_id")(_raw.related_programs)

search_acceptance_stats = with_envelope("search_acceptance_stats", query_arg="program_name")(
    _raw.search_acceptance_stats_am
)

enum_values = with_envelope("enum_values", query_arg="enum_name")(_raw.enum_values_am)

intent_of = with_envelope("intent_of", query_arg="query")(_raw.intent_of)

reason_answer = with_envelope("reason_answer", query_arg="query")(_raw.reason_answer)


# Keep the MCP app handle available for servers that want to register
# the wrapped tools on a fresh FastMCP instance at merge time.
mcp = getattr(_raw, "mcp", None)


WRAPPED_TOOL_NAMES = [
    "search_tax_incentives",
    "search_certifications",
    "list_open_programs",
    "search_by_law",
    "active_programs_at",
    "related_programs",
    "search_acceptance_stats",
    "enum_values",
    "intent_of",
    "reason_answer",
]


__all__ = WRAPPED_TOOL_NAMES + ["mcp", "WRAPPED_TOOL_NAMES"]
