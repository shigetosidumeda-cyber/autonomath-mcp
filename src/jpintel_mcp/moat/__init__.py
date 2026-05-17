"""jpintel_mcp.moat — Niche Moat Lane upstream implementations.

This package hosts the LIVE backends that the
``jpintel_mcp.mcp.moat_lane_tools.*`` MCP wrappers can dispatch into
once a lane is landed. The wrappers still expose the canonical PENDING
envelope contract today; the LIVE modules here are pure functions that
agent-internal call sites can invoke without going through the MCP
boundary.

Currently shipped:

* :mod:`jpintel_mcp.moat.m1_kg_extraction` — regex / dictionary-based
  Japanese government PDF entity + relation extractor. No LLM inference.
"""

from __future__ import annotations
