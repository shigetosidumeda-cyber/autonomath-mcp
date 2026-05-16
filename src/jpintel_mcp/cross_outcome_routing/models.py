"""Pydantic models for the Wave 51 L3 cross-outcome routing layer.

Three canonical envelopes:

* :class:`OutcomePairScore` — a single directed (or undirected) pairwise
  score between two outcome deliverables, with the deterministic features
  that produced the score.
* :class:`OutcomeRoutingChain` — an ordered chain of N >= 2 outcomes
  surfaced as a recommended "handoff" sequence for one user segment.
* :class:`RoutingMatrix` — the full pairwise matrix snapshot plus the
  derived per-segment chain set. This is the artifact consumed by
  ``ax_layer_6_cross_outcome_routing`` and is the canonical envelope
  returned by :func:`build_routing_matrix`.

The models follow the same strict-by-default contract used elsewhere in
``agent_runtime.contracts`` (``extra='forbid'`` + ``frozen=True``) so a
typo in an ETL/cron payload fails loudly at the boundary rather than
silently corrupting the routing artifact.

Non-goals
---------
* **No live HTTP.** This package never imports ``httpx`` / ``requests``
  / ``aiohttp``. The routing layer is pure metadata transformation;
  delivery is a downstream cron concern.
* **No LLM inference.** No ``anthropic`` / ``openai`` /
  ``google.generativeai`` / ``claude_agent_sdk`` import. The pairwise
  score is a deterministic Jaccard-style feature combination — no
  inference, no embedding lookup.
* **No DB.** The catalog source is the in-process Python module
  ``agent_runtime.outcome_catalog``.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

#: Schema version of the routing matrix artifact. Bumped on shape changes.
ROUTING_SCHEMA_VERSION: Literal["jpcite.cross_outcome_routing.v1"] = (
    "jpcite.cross_outcome_routing.v1"
)


class _StrictModel(BaseModel):
    """Forbid extra fields and freeze attribute mutation by default."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class OutcomePairScore(_StrictModel):
    """Pairwise routing affinity between two outcome deliverables.

    The score is in [0.0, 1.0] and is computed deterministically from the
    overlap of three feature families (``use_case_tags``,
    ``source_dependencies``, ``user_segments``). See
    :func:`jpintel_mcp.cross_outcome_routing.routing.score_pair`.

    Attributes are intentionally minimal: a downstream consumer (cron or
    MCP wrapper) can join back to the full :class:`OutcomeCatalogEntry`
    via ``slug_a`` / ``slug_b`` to recover display names, billing
    posture, and source dependency provenance.
    """

    slug_a: str = Field(min_length=1)
    slug_b: str = Field(min_length=1)
    use_case_overlap: float = Field(ge=0.0, le=1.0)
    source_overlap: float = Field(ge=0.0, le=1.0)
    segment_overlap: float = Field(ge=0.0, le=1.0)
    score: float = Field(ge=0.0, le=1.0)
    shared_use_case_tags: tuple[str, ...] = ()
    shared_source_family_ids: tuple[str, ...] = ()
    shared_user_segments: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _slugs_distinct(self) -> OutcomePairScore:
        if self.slug_a == self.slug_b:
            raise ValueError("slug_a and slug_b must be distinct")
        return self


class OutcomeRoutingChain(_StrictModel):
    """Ordered N-step handoff chain recommended for one user segment.

    A chain is a deterministic greedy walk through the pairwise score
    matrix starting from one anchor outcome. Each step picks the highest
    unused neighbour that (a) shares the same user segment and (b) has
    a pairwise score >= ``threshold``. The walk terminates when no
    qualifying neighbour remains, or ``max_steps`` is reached.

    The chain is the L3 ``cross_outcome_routing`` deliverable: "if a
    customer in segment X is interested in deliverable Y, also surface
    deliverables Z1 → Z2 → ...".
    """

    user_segment: str = Field(min_length=1)
    anchor_slug: str = Field(min_length=1)
    steps: tuple[str, ...] = Field(min_length=2)
    score_sum: float = Field(ge=0.0)
    score_min: float = Field(ge=0.0, le=1.0)
    threshold: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _anchor_is_first_step(self) -> OutcomeRoutingChain:
        if self.steps[0] != self.anchor_slug:
            raise ValueError("steps[0] must equal anchor_slug")
        if len(set(self.steps)) != len(self.steps):
            raise ValueError("steps must not repeat a slug")
        return self


class RoutingMatrix(_StrictModel):
    """Full snapshot of the cross-outcome routing artifact.

    Returned by :func:`jpintel_mcp.cross_outcome_routing.routing.build_routing_matrix`.
    Consumers (cron, MCP wrapper, audit dump) read this single envelope
    rather than re-running the pairwise computation.
    """

    schema_version: Literal["jpcite.cross_outcome_routing.v1"] = ROUTING_SCHEMA_VERSION
    catalog_version: str = Field(min_length=1)
    catalog_size: int = Field(ge=2)
    pair_count: int = Field(ge=0)
    pairs: tuple[OutcomePairScore, ...]
    chains: tuple[OutcomeRoutingChain, ...]
    threshold: float = Field(ge=0.0, le=1.0)
    max_chain_steps: int = Field(ge=2, le=20)

    @model_validator(mode="after")
    def _pair_count_matches(self) -> RoutingMatrix:
        if self.pair_count != len(self.pairs):
            raise ValueError("pair_count must equal len(pairs)")
        n = self.catalog_size
        expected_max = n * (n - 1) // 2
        if self.pair_count > expected_max:
            raise ValueError(
                f"pair_count {self.pair_count} exceeds combinatorial max {expected_max}"
            )
        return self
