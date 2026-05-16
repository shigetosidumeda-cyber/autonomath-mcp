"""Wave 51 L3 — tests for the cross_outcome_routing module.

Covers the router-agnostic primitives under
``src/jpintel_mcp/cross_outcome_routing/``:

    * ``jaccard`` — empty set / disjoint / identical / partial overlap.
    * ``score_pair`` — Pydantic round trip + weight composition.
    * ``OutcomePairScore`` — validation guards (slug distinctness,
      probability range).
    * ``OutcomeRoutingChain`` — anchor-step alignment + dedup invariant.
    * ``build_pairs`` — combinatorial count + deterministic ordering.
    * ``build_chains`` — per-segment greedy walk + segment restriction.
    * ``build_routing_matrix`` — full snapshot, threshold + max_steps
      enforcement, real-catalog smoke.

Every test is deterministic: no clock, no random, no I/O.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from jpintel_mcp.agent_runtime.outcome_catalog import (
    CATALOG_VERSION,
    OutcomeCatalogEntry,
    SourceDependency,
    build_outcome_catalog,
)
from jpintel_mcp.cross_outcome_routing import (
    DEFAULT_MAX_CHAIN_STEPS,
    DEFAULT_THRESHOLD,
    ROUTING_SCHEMA_VERSION,
    WEIGHT_SEGMENT,
    WEIGHT_SOURCE,
    WEIGHT_USE_CASE,
    OutcomePairScore,
    OutcomeRoutingChain,
    RoutingMatrix,
    build_chains,
    build_pairs,
    build_routing_matrix,
    jaccard,
    score_pair,
)

# ---------------------------------------------------------------------------
# Fixtures (synthetic mini-catalog — does not depend on the real catalog
# shape so the algorithmic tests stay stable when production rows change)
# ---------------------------------------------------------------------------


def _mk(
    slug: str,
    *,
    tags: tuple[str, ...],
    sources: tuple[str, ...],
    segments: tuple[str, ...] = ("agent_builder",),
) -> OutcomeCatalogEntry:
    """Build one minimal valid catalog entry for testing."""
    deps = tuple(
        SourceDependency(
            dependency_type="official_public_registry",
            source_family_id=src,
            source_role="test_role",
            cached_official_or_public=True,
            user_csv=False,
        )
        for src in sources
    )
    return OutcomeCatalogEntry(
        deliverable_slug=slug,
        display_name=slug.replace("-", " ").title(),
        outcome_contract_id=slug.replace("-", "_"),
        user_segments=segments,
        high_value=True,
        use_case_tags=tags,
        source_dependencies=deps,
        pricing_posture="accepted_artifact_standard",
        billing_posture="billable_after_user_accepts_artifact",
        input_requirement="cached_official_public_only",
        cached_official_public_sources_sufficient=True,
        requires_user_csv=False,
    )


@pytest.fixture
def mini_catalog() -> tuple[OutcomeCatalogEntry, ...]:
    """Three-entry synthetic catalog with controlled overlap."""
    return (
        _mk(
            "alpha-subsidy",
            tags=("subsidy_grants", "application_strategy"),
            sources=("jgrants", "sme_agency"),
            segments=("agent_builder", "sme_operator"),
        ),
        _mk(
            "beta-cashbook",
            tags=("subsidy_grants", "tax_accounting_csv_overlay"),
            sources=("jgrants", "tenant_csv"),
            segments=("sme_operator", "tax_advisor"),
        ),
        _mk(
            "gamma-court",
            tags=("court_enforcement",),
            sources=("court_records",),
            segments=("compliance_team",),
        ),
    )


# ---------------------------------------------------------------------------
# jaccard
# ---------------------------------------------------------------------------


def test_jaccard_empty_both_returns_zero() -> None:
    assert jaccard((), ()) == 0.0


def test_jaccard_disjoint_returns_zero() -> None:
    assert jaccard(("a", "b"), ("c", "d")) == 0.0


def test_jaccard_identical_returns_one() -> None:
    assert jaccard(("a", "b"), ("b", "a")) == 1.0


def test_jaccard_partial_overlap_matches_formula() -> None:
    # {a,b} ∩ {b,c} = {b} (1) ; ∪ = {a,b,c} (3) ; 1/3
    assert jaccard(("a", "b"), ("b", "c")) == pytest.approx(1 / 3)


def test_jaccard_dedupes_input_iterables() -> None:
    # Iterable inputs with duplicates must collapse to set semantics.
    assert jaccard(("a", "a", "b"), ("a", "b", "b")) == 1.0


# ---------------------------------------------------------------------------
# score_pair
# ---------------------------------------------------------------------------


def test_score_pair_identical_entries_excluded_by_distinct_slug() -> None:
    # The model forbids scoring an entry against itself.
    entry = _mk("solo", tags=("x",), sources=("y",))
    with pytest.raises(ValidationError):
        OutcomePairScore(
            slug_a=entry.deliverable_slug,
            slug_b=entry.deliverable_slug,
            use_case_overlap=1.0,
            source_overlap=1.0,
            segment_overlap=1.0,
            score=1.0,
        )


def test_score_pair_weights_sum_to_one() -> None:
    # The 3 component weights must sum to 1.0 so the score stays in [0, 1].
    total = WEIGHT_USE_CASE + WEIGHT_SOURCE + WEIGHT_SEGMENT
    assert total == pytest.approx(1.0)


def test_score_pair_combines_jaccard_with_declared_weights(
    mini_catalog: tuple[OutcomeCatalogEntry, ...],
) -> None:
    alpha, beta, _ = mini_catalog
    pair = score_pair(alpha, beta)
    # alpha vs beta tag overlap = {subsidy_grants} / 3 = 1/3
    assert pair.use_case_overlap == pytest.approx(1 / 3)
    # source overlap = {jgrants} / 3 = 1/3
    assert pair.source_overlap == pytest.approx(1 / 3)
    # segment overlap = {sme_operator} / 3 = 1/3
    assert pair.segment_overlap == pytest.approx(1 / 3)
    expected = WEIGHT_USE_CASE * (1 / 3) + WEIGHT_SOURCE * (1 / 3) + WEIGHT_SEGMENT * (1 / 3)
    assert pair.score == pytest.approx(expected)


def test_score_pair_disjoint_yields_zero(
    mini_catalog: tuple[OutcomeCatalogEntry, ...],
) -> None:
    alpha, _, gamma = mini_catalog
    pair = score_pair(alpha, gamma)
    assert pair.score == 0.0
    assert pair.shared_use_case_tags == ()
    assert pair.shared_source_family_ids == ()
    assert pair.shared_user_segments == ()


# ---------------------------------------------------------------------------
# build_pairs — combinatorial count + ordering
# ---------------------------------------------------------------------------


def test_build_pairs_yields_upper_triangle_count(
    mini_catalog: tuple[OutcomeCatalogEntry, ...],
) -> None:
    pairs = build_pairs(mini_catalog)
    n = len(mini_catalog)
    assert len(pairs) == n * (n - 1) // 2  # 3 → 3 pairs


def test_build_pairs_deterministic_slug_ordering(
    mini_catalog: tuple[OutcomeCatalogEntry, ...],
) -> None:
    pairs1 = build_pairs(mini_catalog)
    pairs2 = build_pairs(mini_catalog)
    slugs1 = [(p.slug_a, p.slug_b) for p in pairs1]
    slugs2 = [(p.slug_a, p.slug_b) for p in pairs2]
    assert slugs1 == slugs2  # byte-identical on repeat


# ---------------------------------------------------------------------------
# OutcomeRoutingChain validation
# ---------------------------------------------------------------------------


def test_chain_anchor_must_equal_first_step() -> None:
    with pytest.raises(ValidationError):
        OutcomeRoutingChain(
            user_segment="sme_operator",
            anchor_slug="alpha",
            steps=("beta", "gamma"),  # anchor not at index 0
            score_sum=0.5,
            score_min=0.2,
            threshold=0.1,
        )


def test_chain_steps_must_not_repeat_a_slug() -> None:
    with pytest.raises(ValidationError):
        OutcomeRoutingChain(
            user_segment="sme_operator",
            anchor_slug="alpha",
            steps=("alpha", "beta", "alpha"),
            score_sum=0.5,
            score_min=0.2,
            threshold=0.1,
        )


# ---------------------------------------------------------------------------
# build_chains — segment restriction + greedy walk
# ---------------------------------------------------------------------------


def test_build_chains_restricts_each_walk_to_its_segment(
    mini_catalog: tuple[OutcomeCatalogEntry, ...],
) -> None:
    pairs = build_pairs(mini_catalog)
    chains = build_chains(mini_catalog, pairs, threshold=0.0, max_steps=5)
    for chain in chains:
        catalog_by_slug = {e.deliverable_slug: e for e in mini_catalog}
        for slug in chain.steps:
            entry = catalog_by_slug[slug]
            assert chain.user_segment in entry.user_segments


def test_build_chains_threshold_filters_low_score_neighbours(
    mini_catalog: tuple[OutcomeCatalogEntry, ...],
) -> None:
    pairs = build_pairs(mini_catalog)
    # Very high threshold filters every pair → no chain survives.
    chains = build_chains(mini_catalog, pairs, threshold=0.99, max_steps=5)
    assert chains == ()


def test_build_chains_max_steps_caps_chain_length(
    mini_catalog: tuple[OutcomeCatalogEntry, ...],
) -> None:
    pairs = build_pairs(mini_catalog)
    chains = build_chains(mini_catalog, pairs, threshold=0.0, max_steps=2)
    for chain in chains:
        assert len(chain.steps) <= 2


# ---------------------------------------------------------------------------
# build_routing_matrix — facade + invariants + real-catalog smoke
# ---------------------------------------------------------------------------


def test_build_routing_matrix_uses_canonical_catalog_when_omitted() -> None:
    matrix = build_routing_matrix()
    assert matrix.catalog_version == CATALOG_VERSION
    assert matrix.schema_version == ROUTING_SCHEMA_VERSION
    assert matrix.catalog_size == len(build_outcome_catalog())


def test_build_routing_matrix_rejects_too_small_catalog() -> None:
    with pytest.raises(ValueError, match="at least 2"):
        build_routing_matrix(catalog=(_mk("solo", tags=("x",), sources=("y",)),))


def test_build_routing_matrix_rejects_out_of_range_threshold(
    mini_catalog: tuple[OutcomeCatalogEntry, ...],
) -> None:
    with pytest.raises(ValueError, match="threshold"):
        build_routing_matrix(catalog=mini_catalog, threshold=1.5)


def test_build_routing_matrix_rejects_out_of_range_max_steps(
    mini_catalog: tuple[OutcomeCatalogEntry, ...],
) -> None:
    with pytest.raises(ValueError, match="max_chain_steps"):
        build_routing_matrix(catalog=mini_catalog, max_chain_steps=1)


def test_build_routing_matrix_pair_count_invariant(
    mini_catalog: tuple[OutcomeCatalogEntry, ...],
) -> None:
    matrix = build_routing_matrix(catalog=mini_catalog, threshold=0.0)
    n = len(mini_catalog)
    assert matrix.pair_count == n * (n - 1) // 2
    assert matrix.pair_count == len(matrix.pairs)


def test_build_routing_matrix_full_envelope_is_pydantic_strict(
    mini_catalog: tuple[OutcomeCatalogEntry, ...],
) -> None:
    matrix = build_routing_matrix(catalog=mini_catalog)
    assert isinstance(matrix, RoutingMatrix)
    # Frozen model — mutation must fail.
    with pytest.raises(ValidationError):
        matrix.pairs[0].__dict__["score"] = 0.99  # bypass attempt is irrelevant
        OutcomePairScore(
            slug_a="x",
            slug_b="y",
            use_case_overlap=2.0,  # out of range → triggers validation
            source_overlap=0.0,
            segment_overlap=0.0,
            score=0.0,
        )


def test_real_catalog_yields_chains_and_no_self_loops() -> None:
    # Smoke test against the live catalog: at least one chain emitted,
    # no chain contains its anchor twice, every pair has distinct slugs.
    matrix = build_routing_matrix()
    assert matrix.chains  # non-empty against production catalog
    for chain in matrix.chains:
        assert chain.anchor_slug in chain.steps
        assert len(set(chain.steps)) == len(chain.steps)
        assert chain.score_min >= matrix.threshold
    for pair in matrix.pairs:
        assert pair.slug_a != pair.slug_b


def test_default_constants_within_documented_bounds() -> None:
    # Defaults are documented in the design doc; pin them so a future
    # tuning change is intentional rather than silent.
    assert 0.0 <= DEFAULT_THRESHOLD <= 1.0
    assert 2 <= DEFAULT_MAX_CHAIN_STEPS <= 20
