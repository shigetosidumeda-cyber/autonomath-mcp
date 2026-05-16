"""L2 math engine — Wave 51 deterministic scoring + forecast primitives.

This package implements the **NO LLM** math layer described in
``docs/_internal/WAVE51_L2_MATH_ENGINE_API_SPEC.md``. Every public
callable is a pure function over `MathEngineRequest` → `MathEngineResult`,
backed by numpy / scipy primitives only.

Hard contract (enforced by `tests/test_no_llm_in_production.py`):

- No `anthropic` / `openai` / `google.generativeai` / `claude_agent_sdk`
  / `langchain*` / `mistralai` / `cohere` / `groq` / `replicate` /
  `together` / `vertexai` / `bedrock_runtime` imports anywhere in this
  package, including transitive imports.
- All reasoning surfaces as ``RankedCandidate.reasoning_path`` — an
  ordered tuple of ``rule_id`` strings + parameter trace fragments. No
  natural-language summary generation. Free-text rationale belongs in
  Wave 52+ copilot scaffold (out of scope here).
- ``MathEngineResult.request_time_llm_call_performed`` is a
  ``Literal[False]`` constant. The type system itself rejects a future
  drift that would set it ``True``.

Wave 51 tick 1 lands the **sweep** algorithm as the foundational module.
``pareto`` and ``montecarlo`` follow in subsequent ticks per
``WAVE51_IMPLEMENTATION_ROADMAP.md`` Day 1-7 schedule.
"""

from __future__ import annotations

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
    validate_request,
)
from jpintel_mcp.services.math_engine.sweep import run_sweep

__all__ = [
    "MATH_ENGINE_SCHEMA_VERSION",
    "MathEngineRequest",
    "MathEngineResult",
    "ObjectiveAxis",
    "ParameterDimension",
    "RankedCandidate",
    "ValidationError",
    "run_sweep",
    "validate_request",
]
