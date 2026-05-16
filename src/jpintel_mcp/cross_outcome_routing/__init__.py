"""Wave 51 L3 — cross-outcome routing (AX Layer 6 input).

This package implements the deterministic pairwise scorer + per-segment
greedy chain walker that produces the canonical
``cross_outcome_routing`` artifact described in
``docs/_internal/WAVE51_L3_L4_L5_DESIGN.md``::

    cron 名 / 役割: cross_outcome_routing
    14 outcome 間の関連性を pairwise score 化。
    e.g., 「補助金 → 取引先 → 法令」の chain 推薦
    daily 03:00 JST (Wave 51 L3 / AX Layer 6)

The module is **router-agnostic** so the same primitives serve:

* MCP tool surface (a future ``recommend_outcome_chain`` family tool).
* REST surface (a future ``/v1/routing/outcome_chain`` router).
* AX Layer 6 cron (``scripts/cron/ax_layer_6_cross_outcome_routing.py``).
* Tests, without spinning up FastMCP / FastAPI / DB handles.

Hard constraints (enforced structurally, not by convention):

- **No LLM SDK import**: no ``anthropic`` / ``openai`` /
  ``google.generativeai`` / ``claude_agent_sdk``. The pairwise scorer
  is a Jaccard-style feature combination; no inference, no embedding
  lookup. CI guard ``tests/test_no_llm_in_production.py`` enforces.
- **No live HTTP / DB**: the catalog is sourced from the in-process
  ``agent_runtime.outcome_catalog`` registry. Nothing here opens a
  socket or a database handle.
- **Pure / deterministic**: the same catalog input always produces the
  same :class:`RoutingMatrix` output. No clock, no random, no env-var.

See ``routing.py`` for the scorer + walker, and ``models.py`` for the
Pydantic envelopes.

Public surface
--------------
    OutcomePairScore        — Pydantic, one directed pairwise score row.
    OutcomeRoutingChain     — Pydantic, one segment-restricted chain walk.
    RoutingMatrix           — Pydantic, full artifact envelope.
    score_pair              — Pairwise scorer (atomic helper).
    jaccard                 — Set Jaccard index helper.
    build_pairs             — Full upper-triangle pair list builder.
    build_chains            — Per-segment chain walker.
    build_routing_matrix    — One-shot facade returning a ``RoutingMatrix``.
    WEIGHT_USE_CASE         — Pairwise weight on use-case-tag overlap.
    WEIGHT_SOURCE           — Pairwise weight on source-family overlap.
    WEIGHT_SEGMENT          — Pairwise weight on user-segment overlap.
    DEFAULT_THRESHOLD       — Default pair-score filter threshold.
    DEFAULT_MAX_CHAIN_STEPS — Default max greedy chain length.
    ROUTING_SCHEMA_VERSION  — Schema-version literal pinned on RoutingMatrix.
"""

from __future__ import annotations

from jpintel_mcp.cross_outcome_routing.models import (
    ROUTING_SCHEMA_VERSION,
    OutcomePairScore,
    OutcomeRoutingChain,
    RoutingMatrix,
)
from jpintel_mcp.cross_outcome_routing.routing import (
    DEFAULT_MAX_CHAIN_STEPS,
    DEFAULT_THRESHOLD,
    WEIGHT_SEGMENT,
    WEIGHT_SOURCE,
    WEIGHT_USE_CASE,
    build_chains,
    build_pairs,
    build_routing_matrix,
    jaccard,
    score_pair,
)

__all__ = [
    "DEFAULT_MAX_CHAIN_STEPS",
    "DEFAULT_THRESHOLD",
    "ROUTING_SCHEMA_VERSION",
    "WEIGHT_SEGMENT",
    "WEIGHT_SOURCE",
    "WEIGHT_USE_CASE",
    "OutcomePairScore",
    "OutcomeRoutingChain",
    "RoutingMatrix",
    "build_chains",
    "build_pairs",
    "build_routing_matrix",
    "jaccard",
    "score_pair",
]
