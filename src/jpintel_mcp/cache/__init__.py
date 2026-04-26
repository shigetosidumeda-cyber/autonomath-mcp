"""L4 query-result cache helpers (v8 P5-ε++ / 4-Layer cache architecture).

Public surface:
    cache.l4.get_or_compute(cache_key, tool, params, compute, ttl=86400)

The cache is a single SQLite table (`l4_query_cache`, migration 043) keyed
by sha256(tool_name + canonical_json(params)). Sits ABOVE the L3 reasoner
layer and serves the Zipf-shaped tail of identical-param queries directly
from a serialized blob.
"""
from jpintel_mcp.cache.l4 import (
    canonical_cache_key,
    canonical_params,
    get_or_compute,
    invalidate,
    invalidate_tool,
    sweep_expired,
)

__all__ = [
    "canonical_cache_key",
    "canonical_params",
    "get_or_compute",
    "invalidate",
    "invalidate_tool",
    "sweep_expired",
]
