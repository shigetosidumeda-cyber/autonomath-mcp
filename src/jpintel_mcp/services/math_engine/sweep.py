"""Deterministic grid sweep for the L2 math engine.

Algorithm (per ``WAVE51_L2_MATH_ENGINE_API_SPEC.md`` §1 + §4):

1. Validate input via ``_validators.validate_request``.
2. Enumerate the full cartesian product of ``parameter_dimensions``.
3. For each enumerated point, compute one score per ``objective_axis``
   using a deterministic, NO-LLM scoring function. Wave 51 tick 1 uses
   ``_default_objective_score`` — a transparent linear-projection scorer
   that hashes the parameter name into a fixed [0.0, 1.0) basis vector
   so callers can wire real outcome-specific scorers in subsequent ticks
   without breaking the shape of the result.
4. Combine per-axis scores into a single ranking score via
   direction-aware weighted sum: ``+score`` for ``maximize``, ``-score``
   for ``minimize``.
5. Sort descending by combined ranking score (stable by
   ``candidate_id`` for tie-break, so seed=0 → same order).
6. Truncate to ``max_candidates``, attach rank, ``reasoning_path``, and
   ``confidence_bucket``.

The scoring function is **intentionally deterministic and pure**: the
same ``(parameter_values, objective_axis)`` input always produces the
same float output, with no I/O, no LLM call, no clock read. This is the
property the round-trip test ``assert result_a == result_b`` relies on.
"""

from __future__ import annotations

import hashlib
import itertools
import time
from typing import Any, Literal

from jpintel_mcp.services.math_engine._common import (
    MATH_ENGINE_SCHEMA_VERSION,
    MathEngineRequest,
    MathEngineResult,
    ObjectiveAxis,
    ParameterDimension,
    RankedCandidate,
)
from jpintel_mcp.services.math_engine._validators import (
    ValidationError,
    grid_cardinality,
    validate_request,
)


def _enumerate_dimension(dim: ParameterDimension) -> list[Any]:
    """Materialize the list of points a single dimension contributes."""

    if dim.type == "enum":
        return list(dim.values)
    if dim.type == "boolean":
        return [False, True]
    if dim.type == "range":
        # Pydantic guarantees these are non-None for range.
        assert dim.min is not None
        assert dim.max is not None
        assert dim.step is not None
        out: list[Any] = []
        value = dim.min
        # The `+ 1e-9 * step` epsilon below absorbs float drift in the
        # last point; without it, ``min=0, max=1, step=0.1`` can drop
        # the ``1.0`` endpoint due to accumulated rounding.
        epsilon = 1e-9 * dim.step
        while value <= dim.max + epsilon:
            # Round to avoid leaking float noise into candidate_id hashes.
            out.append(round(value, 12))
            value += dim.step
        return out
    raise ValidationError(f"unknown dimension type {dim.type!r}")


def _candidate_id(request_id: str, parameter_values: dict[str, Any]) -> str:
    """Deterministic candidate identifier.

    Hashing the (request_id, sorted-by-name parameter_values) tuple
    means: same request + same point → same id, across runs and across
    machines. Strings are taken verbatim (no escaping) because the
    sorted dict-repr handles delimiter ambiguity for us.
    """

    body = repr((request_id, sorted(parameter_values.items())))
    return "cand-" + hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]


def _default_objective_score(
    parameter_values: dict[str, Any],
    axis: ObjectiveAxis,
    seed: int,
) -> float:
    """Deterministic placeholder scorer for Wave 51 tick 1.

    The score is computed as a sha256-based projection of the
    (axis.name, sorted parameter_values, seed) tuple into the [0, 1)
    interval. This produces:

    - A stable mapping from inputs to outputs (same input → same float).
    - A non-trivial distribution that surfaces sort + rank logic in
      tests (constants would mask bugs).
    - Zero coupling to LLMs, network, clocks, or files.

    Real outcome-specific scorers (e.g. subsidy expected-benefit,
    permit eligibility rate) wire in later ticks via a registry the
    spec calls ``_scorers/``. The shape of this function — pure,
    deterministic, three-arg — is the contract those real scorers must
    honor.
    """

    body = repr((axis.name, sorted(parameter_values.items()), seed))
    digest = hashlib.sha256(body.encode("utf-8")).digest()
    # Map the first 8 bytes of the digest into [0.0, 1.0).
    raw = int.from_bytes(digest[:8], byteorder="big", signed=False)
    return raw / 2**64


def _combined_score(
    objective_scores: dict[str, float],
    objective_axes: tuple[ObjectiveAxis, ...],
) -> float:
    """Direction-aware weighted sum.

    ``maximize`` axes contribute ``+weight * score``; ``minimize`` axes
    contribute ``-weight * score``. Higher combined score → better
    rank.
    """

    total = 0.0
    for axis in objective_axes:
        score = objective_scores[axis.name]
        sign = 1.0 if axis.direction == "maximize" else -1.0
        total += sign * axis.weight * score
    return total


def _confidence_bucket(rank: int, total_returned: int) -> Literal["high", "medium", "low"]:
    """Map ``rank`` (1-indexed) to a tri-state confidence bucket.

    Top tercile = high, middle = medium, bottom = low. With
    ``total_returned <= 2``, every row falls in the top bucket — fine
    for unit tests, and the actual scorers will narrow this in later
    ticks anyway.
    """

    if total_returned <= 0:
        return "low"
    fraction = (rank - 1) / total_returned
    if fraction < 1.0 / 3.0:
        return "high"
    if fraction < 2.0 / 3.0:
        return "medium"
    return "low"


def _reasoning_path(
    parameter_values: dict[str, Any],
    objective_axes: tuple[ObjectiveAxis, ...],
    request: MathEngineRequest,
) -> tuple[str, ...]:
    """Build the rule_id + parameter trace for a candidate.

    Output is a tuple of short tokens, NOT natural language. Format:

    ``("rule:sweep.v1", "outcome:<id>", "seed:<int>",
       "param:<name>=<value>", ..., "axis:<name>:<direction>", ...)``

    This is the audit substrate the AI-agent consumer reads to justify
    a citation, per ``feedback_explainable_fact_design``.
    """

    parts: list[str] = [
        "rule:sweep.v1",
        f"outcome:{request.outcome_contract_id}",
        f"seed:{request.seed}",
    ]
    for name in sorted(parameter_values):
        parts.append(f"param:{name}={parameter_values[name]!r}")
    for axis in objective_axes:
        parts.append(f"axis:{axis.name}:{axis.direction}")
    return tuple(parts)


def run_sweep(request: MathEngineRequest) -> MathEngineResult:
    """Execute a deterministic grid sweep.

    Raises ``ValidationError`` on bad inputs.

    Determinism: for the same ``MathEngineRequest`` instance (including
    the same ``seed`` and ``request_id``), this function returns equal
    ``MathEngineResult`` instances modulo ``computation_time_ms``. The
    test suite asserts equality of the ``ranked_candidates`` tuple to
    avoid coupling to wall-clock noise.
    """

    if request.algorithm != "sweep":
        raise ValidationError(
            f"run_sweep called with algorithm={request.algorithm!r}; expected 'sweep'"
        )
    validate_request(request)

    started_ns = time.perf_counter_ns()

    cardinality = grid_cardinality(request)
    dimension_values: list[list[Any]] = [
        _enumerate_dimension(dim) for dim in request.parameter_dimensions
    ]
    dimension_names: list[str] = [dim.name for dim in request.parameter_dimensions]

    # Materialize the cartesian product once. cardinality is bounded by
    # ``GRID_CARDINALITY_HARD_CAP`` so this is safe.
    scored: list[tuple[float, dict[str, Any], dict[str, float]]] = []
    for point in itertools.product(*dimension_values):
        parameter_values: dict[str, Any] = dict(zip(dimension_names, point, strict=True))
        objective_scores: dict[str, float] = {
            axis.name: _default_objective_score(parameter_values, axis, request.seed)
            for axis in request.objective_axes
        }
        combined = _combined_score(objective_scores, request.objective_axes)
        scored.append((combined, parameter_values, objective_scores))

    # Stable sort: primary key = descending combined score, secondary
    # key = ascending candidate_id (so ties resolve identically across
    # runs without depending on hash insertion order).
    scored_with_ids: list[tuple[float, str, dict[str, Any], dict[str, float]]] = [
        (combined, _candidate_id(request.request_id, params), params, scores)
        for combined, params, scores in scored
    ]
    scored_with_ids.sort(key=lambda row: (-row[0], row[1]))

    truncated = scored_with_ids[: request.max_candidates]
    total_returned = len(truncated)

    ranked: list[RankedCandidate] = []
    for rank_index, (_, candidate_id, params, scores) in enumerate(truncated):
        rank = rank_index + 1
        ranked.append(
            RankedCandidate(
                candidate_id=candidate_id,
                parameter_values=params,
                objective_scores=scores,
                rank=rank,
                reasoning_path=_reasoning_path(params, request.objective_axes, request),
                confidence_bucket=_confidence_bucket(rank, total_returned),
            )
        )

    elapsed_ms = (time.perf_counter_ns() - started_ns) / 1_000_000.0

    return MathEngineResult(
        schema_version=MATH_ENGINE_SCHEMA_VERSION,
        request_id=request.request_id,
        algorithm="sweep",
        outcome_contract_id=request.outcome_contract_id,
        ranked_candidates=tuple(ranked),
        pareto_front=None,
        summary_stats={
            "grid_cardinality": float(cardinality),
            "candidates_returned": float(total_returned),
            "truncated": 1.0 if cardinality > total_returned else 0.0,
        },
        computation_time_ms=elapsed_ms,
        request_time_llm_call_performed=False,
    )
