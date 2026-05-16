"""Runtime validation for math engine inputs.

The Pydantic models in ``_common.py`` cover shape + type validation.
The functions here add **algorithm-specific** semantic checks that
Pydantic cannot express in a single ``model_validator`` (e.g.
``parameter_dimensions`` must produce a non-empty cartesian product,
the request size must stay under the sweep latency budget).

Failing checks raise ``ValidationError`` — a local subclass of
``ValueError`` so callers can ``except ValueError:`` without leaking a
Pydantic-specific exception into the public surface.
"""

from __future__ import annotations

from math import isfinite
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from jpintel_mcp.services.math_engine._common import (
        MathEngineRequest,
        ParameterDimension,
    )


class ValidationError(ValueError):
    """Raised when a request fails algorithm-specific validation."""


def _range_cardinality(dim: ParameterDimension) -> int:
    """Number of points produced by a range dimension.

    Pydantic already guarantees ``min``, ``max``, ``step`` are non-None
    and ``step > 0``, ``min <= max`` for range dimensions, so the
    runtime branches here are belt-and-suspenders against future schema
    drift only.
    """

    if dim.min is None or dim.max is None or dim.step is None:
        raise ValidationError(f"range dimension {dim.name!r} missing bounds")
    if not (isfinite(dim.min) and isfinite(dim.max) and isfinite(dim.step)):
        raise ValidationError(f"range dimension {dim.name!r} has non-finite bound")
    # `int(...) + 1` because the sequence is inclusive of both endpoints.
    span = dim.max - dim.min
    return int(span / dim.step) + 1


def _dimension_cardinality(dim: ParameterDimension) -> int:
    """Number of values a single dimension contributes to the grid."""

    if dim.type == "enum":
        return len(dim.values)
    if dim.type == "boolean":
        return 2
    if dim.type == "range":
        return _range_cardinality(dim)
    # Defensive — Pydantic Literal narrows to the three above.
    raise ValidationError(f"unknown dimension type {dim.type!r}")


def grid_cardinality(request: MathEngineRequest) -> int:
    """Total points the full grid would enumerate, pre-truncation.

    Useful to surface ``summary_stats['grid_cardinality']`` for
    auditors and to short-circuit absurd inputs before we allocate
    arrays.
    """

    total = 1
    for dim in request.parameter_dimensions:
        card = _dimension_cardinality(dim)
        if card <= 0:
            raise ValidationError(f"dimension {dim.name!r} has non-positive cardinality {card}")
        total *= card
    return total


# Hard cap on grid enumeration. 10 million points × ~16 bytes per float
# score ≈ 160 MB worst case before truncation — well within Fly memory
# headroom, but a single request claiming 10M is almost certainly a
# misconfiguration. Tighter than ``MathEngineRequest.max_candidates``
# (which only caps the **returned** rows; this caps the **enumerated**
# rows).
GRID_CARDINALITY_HARD_CAP: int = 10_000_000


def validate_request(request: MathEngineRequest) -> None:
    """Algorithm-aware input validation.

    Raises ``ValidationError`` on the first failure. Idempotent — does
    not mutate ``request``.
    """

    if request.algorithm == "sweep":
        cardinality = grid_cardinality(request)
        if cardinality > GRID_CARDINALITY_HARD_CAP:
            raise ValidationError(
                f"sweep grid cardinality {cardinality} exceeds hard cap {GRID_CARDINALITY_HARD_CAP}"
            )
    # pareto / montecarlo paths land in later ticks; reserve the
    # discriminator branches so a misrouted request fails loudly.
    elif request.algorithm in ("pareto", "montecarlo"):
        # No additional checks beyond Pydantic in Wave 51 tick 1 — the
        # algorithm implementations themselves enforce their own
        # invariants when they land.
        return
    else:  # pragma: no cover — Pydantic Literal blocks this path
        raise ValidationError(f"unknown algorithm {request.algorithm!r}")
