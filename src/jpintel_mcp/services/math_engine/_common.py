"""Pydantic envelopes for the L2 math engine.

Spec: ``docs/_internal/WAVE51_L2_MATH_ENGINE_API_SPEC.md`` §1.

Five strict-extra-forbid models are defined here:

* ``ParameterDimension`` — single axis of the search space
* ``ObjectiveAxis`` — single optimization objective
* ``MathEngineRequest`` — full input envelope for sweep / pareto /
  montecarlo
* ``RankedCandidate`` — one ranked result row
* ``MathEngineResult`` — full output envelope

The class-level ``model_config`` mirrors the StrictModel pattern already
used in ``agent_runtime/contracts.py``: ``extra="forbid"`` rejects
unknown keys, ``frozen=True`` keeps round-trip equality deterministic so
``assert result_a == result_b`` works for seed-based reproducibility
checks.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

MATH_ENGINE_SCHEMA_VERSION: Literal["jpcite.math_engine.p0.v1"] = "jpcite.math_engine.p0.v1"


class _StrictModel(BaseModel):
    """Local StrictModel — extra forbidden, frozen for deterministic eq."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class ParameterDimension(_StrictModel):
    """One dimension of the parameter search space.

    The ``type`` discriminator chooses how ``values`` / ``min`` / ``max``
    / ``step`` are interpreted:

    - ``enum`` — ``values`` is the exhaustive list of allowed values
      (strings, ints, or other hashables).
    - ``range`` — ``min`` / ``max`` / ``step`` define an inclusive
      arithmetic sequence over floats; ``values`` MUST be empty.
    - ``boolean`` — sweeps ``(False, True)``; ``values`` MUST be empty.
    """

    name: str = Field(min_length=1)
    type: Literal["enum", "range", "boolean"]
    values: tuple[Any, ...] = Field(default=())
    min: float | None = None
    max: float | None = None
    step: float | None = None

    @model_validator(mode="after")
    def _check_shape(self) -> ParameterDimension:
        if self.type == "enum":
            if not self.values:
                raise ValueError("enum dimension requires non-empty values")
            if self.min is not None or self.max is not None or self.step is not None:
                raise ValueError("enum dimension must not set min/max/step")
        elif self.type == "range":
            if self.values:
                raise ValueError("range dimension must not set values")
            if self.min is None or self.max is None or self.step is None:
                raise ValueError("range dimension requires min, max, and step")
            if self.step <= 0:
                raise ValueError("range step must be > 0")
            if self.min > self.max:
                raise ValueError("range min must be <= max")
        elif self.type == "boolean":
            if self.values:
                raise ValueError("boolean dimension must not set values")
            if self.min is not None or self.max is not None or self.step is not None:
                raise ValueError("boolean dimension must not set min/max/step")
        return self


class ObjectiveAxis(_StrictModel):
    """One optimization objective.

    For sweep, every candidate's per-axis ``objective_scores`` value is
    combined into a single ranking score via weighted sum (after sign
    flip for ``minimize`` axes). ``distribution`` is unused by sweep and
    reserved for montecarlo's probabilistic sampling.
    """

    name: str = Field(min_length=1)
    direction: Literal["minimize", "maximize"]
    weight: float = 1.0
    distribution: Literal["empirical", "norm", "beta", "triangular"] | None = None

    @model_validator(mode="after")
    def _check_weight(self) -> ObjectiveAxis:
        if self.weight <= 0:
            raise ValueError("weight must be > 0")
        return self


class MathEngineRequest(_StrictModel):
    """Full input envelope for any of the three algorithms."""

    request_id: str = Field(min_length=1)
    algorithm: Literal["sweep", "pareto", "montecarlo"]
    outcome_contract_id: str = Field(min_length=1)
    parameter_dimensions: tuple[ParameterDimension, ...] = Field(min_length=1)
    objective_axes: tuple[ObjectiveAxis, ...] = Field(min_length=1)
    max_candidates: int = 200
    n_samples: int = 5000
    seed: int = 0
    as_of_date: str | None = None

    @model_validator(mode="after")
    def _check_bounds(self) -> MathEngineRequest:
        if self.max_candidates <= 0:
            raise ValueError("max_candidates must be > 0")
        if self.n_samples <= 0:
            raise ValueError("n_samples must be > 0")
        names = [dim.name for dim in self.parameter_dimensions]
        if len(set(names)) != len(names):
            raise ValueError("parameter_dimensions names must be unique")
        objective_names = [axis.name for axis in self.objective_axes]
        if len(set(objective_names)) != len(objective_names):
            raise ValueError("objective_axes names must be unique")
        return self


class RankedCandidate(_StrictModel):
    """One candidate row in the result.

    ``parameter_values`` is the literal point in the search space.
    ``objective_scores`` carries the per-axis raw score (pre-weighting).
    ``reasoning_path`` is the deterministic rule_id trace — never
    natural language.
    """

    candidate_id: str = Field(min_length=1)
    parameter_values: dict[str, Any]
    objective_scores: dict[str, float]
    rank: int = Field(ge=1)
    reasoning_path: tuple[str, ...] = Field(min_length=1)
    confidence_bucket: Literal["high", "medium", "low"]


class MathEngineResult(_StrictModel):
    """Full output envelope for any of the three algorithms."""

    schema_version: Literal["jpcite.math_engine.p0.v1"] = MATH_ENGINE_SCHEMA_VERSION
    request_id: str = Field(min_length=1)
    algorithm: Literal["sweep", "pareto", "montecarlo"]
    outcome_contract_id: str = Field(min_length=1)
    ranked_candidates: tuple[RankedCandidate, ...]
    pareto_front: tuple[RankedCandidate, ...] | None = None
    summary_stats: dict[str, float] = Field(default_factory=dict)
    computation_time_ms: float = Field(ge=0.0)
    request_time_llm_call_performed: Literal[False] = False
