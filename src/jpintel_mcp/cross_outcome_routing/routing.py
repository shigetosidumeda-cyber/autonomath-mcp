"""Wave 51 L3 — cross-outcome routing scorer + matrix builder.

This module implements the **deterministic** pairwise scorer and the
per-segment greedy chain walker that together produce a
:class:`RoutingMatrix` snapshot. The single public entry point is
:func:`build_routing_matrix`.

Algorithmic contract
--------------------
* **Pure function.** ``build_routing_matrix(catalog, ...)`` is referentially
  transparent over its inputs. Same catalog tuple → byte-identical
  artifact (modulo Pydantic dump ordering, which is itself stable).
* **No clock / no random.** No ``time.time()`` / ``datetime.now()`` /
  ``random`` import. The scorer is fully driven by the catalog content.
* **No LLM, no DB, no HTTP.** Same hard constraints as the other Wave 51
  dim modules.

Pairwise score formula
----------------------
Given two :class:`OutcomeCatalogEntry` rows ``a`` and ``b``::

    use_case_overlap = jaccard(a.use_case_tags,         b.use_case_tags)
    source_overlap   = jaccard(a.source_family_ids,     b.source_family_ids)
    segment_overlap  = jaccard(a.user_segments,         b.user_segments)
    score = 0.45 * use_case_overlap
          + 0.30 * source_overlap
          + 0.25 * segment_overlap

The weights are *deliberate*: use-case overlap is the strongest signal
for "customer who wants A will also want B", followed by source family
reuse (same upstream ETL → cheaper composition), and finally segment
overlap (same audience).

The constants live as module-level ``WEIGHT_*`` so a test (or a future
sensitivity sweep) can re-derive the score with alternative weights
without monkey-patching internals.

Per-segment greedy chain walker
-------------------------------
For each :class:`UserSegment`, the walker:

1. enumerates all catalog entries that include that segment;
2. for each such entry, runs a greedy walk: at each step, pick the
   highest-scoring unused neighbour whose pair score is ``>=`` the
   ``threshold``;
3. stops when no neighbour qualifies, or ``max_steps`` is reached;
4. emits the chain only if at least one handoff step survived.

Determinism notes
-----------------
* Catalog iteration order is preserved (Python dict preserves insertion
  order). Pairs are emitted in ``(i, j)`` order with ``i < j`` so the
  same catalog input always yields the same pair sequence.
* Ties between candidate next-steps are broken by ``slug`` ASCII order
  so the chain selection is fully reproducible.

Public surface
--------------
    score_pair      — internal-grade helper, exported for diagnostics + tests.
    jaccard         — set helper, exported for diagnostics + tests.
    build_pairs     — emit the full upper-triangle pair list.
    build_chains    — emit per-segment chains from a pair list.
    build_routing_matrix — single-call full snapshot facade.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from jpintel_mcp.agent_runtime.outcome_catalog import (
    CATALOG_VERSION,
    OutcomeCatalogEntry,
    build_outcome_catalog,
)

if TYPE_CHECKING:
    from collections.abc import Iterable
from jpintel_mcp.cross_outcome_routing.models import (
    OutcomePairScore,
    OutcomeRoutingChain,
    RoutingMatrix,
)

#: Weight on the use-case-tag Jaccard overlap component.
WEIGHT_USE_CASE: float = 0.45
#: Weight on the source-family Jaccard overlap component.
WEIGHT_SOURCE: float = 0.30
#: Weight on the user-segment Jaccard overlap component.
WEIGHT_SEGMENT: float = 0.25

#: Default pair-score threshold below which two outcomes do not get
#: routed together. Conservative default; cron may override.
DEFAULT_THRESHOLD: float = 0.10

#: Default maximum chain length (anchor + N-1 handoffs).
DEFAULT_MAX_CHAIN_STEPS: int = 5


def jaccard(a: Iterable[str], b: Iterable[str]) -> float:
    """Return the Jaccard index of two iterables of strings.

    Empty ∩ empty → 0.0 (rather than the undefined 0/0). A pair that
    shares nothing returns 0.0; an identical pair returns 1.0.
    """
    set_a = set(a)
    set_b = set(b)
    if not set_a and not set_b:
        return 0.0
    union = set_a | set_b
    if not union:
        return 0.0
    return len(set_a & set_b) / len(union)


def _source_family_ids(entry: OutcomeCatalogEntry) -> tuple[str, ...]:
    """Extract the ordered tuple of ``source_family_id`` strings."""
    return tuple(dep.source_family_id for dep in entry.source_dependencies)


def score_pair(a: OutcomeCatalogEntry, b: OutcomeCatalogEntry) -> OutcomePairScore:
    """Compute the deterministic pairwise routing score for ``a`` ↔ ``b``.

    Returns a fully populated :class:`OutcomePairScore`. The caller is
    expected to canonicalise the (slug_a, slug_b) ordering before
    persistence; this helper does NOT swap slugs.
    """
    a_tags = set(a.use_case_tags)
    b_tags = set(b.use_case_tags)
    a_sources = set(_source_family_ids(a))
    b_sources = set(_source_family_ids(b))
    a_segments = set(a.user_segments)
    b_segments = set(b.user_segments)

    use_case_overlap = jaccard(a_tags, b_tags)
    source_overlap = jaccard(a_sources, b_sources)
    segment_overlap = jaccard(a_segments, b_segments)

    raw = (
        WEIGHT_USE_CASE * use_case_overlap
        + WEIGHT_SOURCE * source_overlap
        + WEIGHT_SEGMENT * segment_overlap
    )
    # Clamp to [0.0, 1.0] in case of float drift at the boundary.
    score = max(0.0, min(1.0, raw))

    return OutcomePairScore(
        slug_a=a.deliverable_slug,
        slug_b=b.deliverable_slug,
        use_case_overlap=use_case_overlap,
        source_overlap=source_overlap,
        segment_overlap=segment_overlap,
        score=score,
        shared_use_case_tags=tuple(sorted(a_tags & b_tags)),
        shared_source_family_ids=tuple(sorted(a_sources & b_sources)),
        shared_user_segments=tuple(sorted(a_segments & b_segments)),
    )


def build_pairs(
    catalog: tuple[OutcomeCatalogEntry, ...],
) -> tuple[OutcomePairScore, ...]:
    """Emit the full upper-triangle pair list.

    For ``N`` catalog entries, returns ``N * (N - 1) // 2`` pairs in the
    order ``(catalog[i], catalog[j])`` for ``i < j``. Pairs with
    ``score == 0.0`` are *not* filtered out at this layer — the caller
    decides whether to threshold.
    """
    pairs: list[OutcomePairScore] = []
    n = len(catalog)
    for i in range(n):
        for j in range(i + 1, n):
            pairs.append(score_pair(catalog[i], catalog[j]))
    return tuple(pairs)


def _neighbours_of(
    slug: str,
    pairs: tuple[OutcomePairScore, ...],
    threshold: float,
) -> list[tuple[str, float]]:
    """Return ``(neighbour_slug, score)`` for ``slug`` above ``threshold``.

    Sorted by ``(-score, neighbour_slug)`` so ties break deterministically
    on ASCII order, descending by score.
    """
    out: list[tuple[str, float]] = []
    for pair in pairs:
        if pair.score < threshold:
            continue
        if pair.slug_a == slug:
            out.append((pair.slug_b, pair.score))
        elif pair.slug_b == slug:
            out.append((pair.slug_a, pair.score))
    out.sort(key=lambda x: (-x[1], x[0]))
    return out


def _walk_chain(
    anchor: OutcomeCatalogEntry,
    segment: str,
    catalog_by_slug: dict[str, OutcomeCatalogEntry],
    pairs: tuple[OutcomePairScore, ...],
    threshold: float,
    max_steps: int,
) -> OutcomeRoutingChain | None:
    """Greedy walk one segment-restricted chain from ``anchor``.

    Returns ``None`` when no neighbour above ``threshold`` shares the
    segment (i.e., the anchor is isolated for this segment).
    """
    visited: set[str] = {anchor.deliverable_slug}
    steps: list[str] = [anchor.deliverable_slug]
    step_scores: list[float] = []
    current = anchor.deliverable_slug

    while len(steps) < max_steps:
        candidates = _neighbours_of(current, pairs, threshold)
        next_slug: str | None = None
        next_score: float | None = None
        for cand_slug, cand_score in candidates:
            if cand_slug in visited:
                continue
            cand_entry = catalog_by_slug.get(cand_slug)
            if cand_entry is None:
                continue
            if segment not in cand_entry.user_segments:
                continue
            next_slug = cand_slug
            next_score = cand_score
            break

        if next_slug is None or next_score is None:
            break

        steps.append(next_slug)
        step_scores.append(next_score)
        visited.add(next_slug)
        current = next_slug

    if not step_scores:
        return None

    return OutcomeRoutingChain(
        user_segment=segment,
        anchor_slug=anchor.deliverable_slug,
        steps=tuple(steps),
        score_sum=float(sum(step_scores)),
        score_min=min(step_scores),
        threshold=threshold,
    )


def build_chains(
    catalog: tuple[OutcomeCatalogEntry, ...],
    pairs: tuple[OutcomePairScore, ...],
    threshold: float = DEFAULT_THRESHOLD,
    max_steps: int = DEFAULT_MAX_CHAIN_STEPS,
) -> tuple[OutcomeRoutingChain, ...]:
    """Emit the per-segment greedy chain set.

    For every (segment, anchor) pair where ``anchor`` belongs to
    ``segment``, walk one chain. Anchors that yield zero qualifying
    handoffs are dropped silently — the artifact only carries chains
    that actually surface at least one recommended next step.
    """
    catalog_by_slug: dict[str, OutcomeCatalogEntry] = {
        entry.deliverable_slug: entry for entry in catalog
    }
    all_segments: set[str] = set()
    for entry in catalog:
        all_segments.update(entry.user_segments)

    chains: list[OutcomeRoutingChain] = []
    # Stable ordering: segment ASCII, then anchor catalog insertion order.
    for segment in sorted(all_segments):
        for entry in catalog:
            if segment not in entry.user_segments:
                continue
            chain = _walk_chain(
                anchor=entry,
                segment=segment,
                catalog_by_slug=catalog_by_slug,
                pairs=pairs,
                threshold=threshold,
                max_steps=max_steps,
            )
            if chain is not None:
                chains.append(chain)
    return tuple(chains)


def build_routing_matrix(
    catalog: tuple[OutcomeCatalogEntry, ...] | None = None,
    *,
    threshold: float = DEFAULT_THRESHOLD,
    max_chain_steps: int = DEFAULT_MAX_CHAIN_STEPS,
) -> RoutingMatrix:
    """Compute the full :class:`RoutingMatrix` snapshot.

    When ``catalog`` is ``None``, the canonical catalog is loaded from
    :func:`build_outcome_catalog` so the function can be called without
    threading the catalog through every caller.

    Raises ``ValueError`` (via Pydantic) when fewer than 2 catalog
    entries are supplied — pair scoring is undefined for ``N < 2``.
    """
    if catalog is None:
        catalog = build_outcome_catalog()
    if len(catalog) < 2:
        raise ValueError("routing matrix requires at least 2 catalog entries")
    if not 0.0 <= threshold <= 1.0:
        raise ValueError("threshold must be in [0.0, 1.0]")
    if not 2 <= max_chain_steps <= 20:
        raise ValueError("max_chain_steps must be in [2, 20]")

    pairs = build_pairs(catalog)
    chains = build_chains(
        catalog=catalog,
        pairs=pairs,
        threshold=threshold,
        max_steps=max_chain_steps,
    )
    return RoutingMatrix(
        catalog_version=CATALOG_VERSION,
        catalog_size=len(catalog),
        pair_count=len(pairs),
        pairs=pairs,
        chains=chains,
        threshold=threshold,
        max_chain_steps=max_chain_steps,
    )
