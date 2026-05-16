"""Base abstractions for Wave 51 dim P composable tools.

This module defines the contract that every composed tool conforms to:

    ComposableTool        — abstract base for 1 composed tool.
    AtomicRegistry        — protocol of injected atomic callables.
    AtomicCallResult      — uniform shape returned by atomic shims.
    ComposedEnvelope      — canonical JPCIR-shaped return type.

The base intentionally has **no** dependency on the FastMCP server or the
FastAPI router. Composed tools are pure Python — they take an
:class:`AtomicRegistry`, invoke atomic callables in a declared order, and
emit a :class:`ComposedEnvelope`. This decoupling lets one composed tool
serve REST, MCP, ETL, and offline probes without reshaping its body.

All callables are synchronous. The composition layer is decision-tree
deterministic: each composed tool declares the atomic tools it depends
on up front in :attr:`ComposableTool.atomic_dependencies`. There is no
inference step at request time — order is fixed by the composed tool's
:meth:`compose` body. This satisfies the
``feedback_composable_tools_pattern`` "no LLM API, no aggregator" rule.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Final, Protocol

if TYPE_CHECKING:
    from jpintel_mcp.agent_runtime.contracts import (
        Evidence,
        OutcomeContract,
    )

#: Schema version emitted by every composed tool envelope. Bump when the
#: ``ComposedEnvelope`` wire shape gains a backwards-incompatible field.
COMPOSED_ENVELOPE_SCHEMA_VERSION: Final[str] = "composed.dim_p.v1"


class ComposedToolError(RuntimeError):
    """Raised when a composed tool cannot run.

    The composition layer raises before any partial side effects are
    committed — typically when the injected :class:`AtomicRegistry` is
    missing one of the declared atomic dependencies, or when a required
    argument is absent from ``kwargs``.
    """


@dataclass(frozen=True, slots=True)
class AtomicCallResult:
    """Uniform shape returned by every atomic callable shim.

    The atomic Python functions invoked by composed tools can have
    arbitrary internal shapes (some emit dicts of rows, some emit
    pydantic models, some emit ``StandardResponse``). The composed
    layer normalises everything through this lightweight dataclass so
    the composition body never branches on raw atomic shapes.

    Attributes
    ----------
    tool_name:
        Canonical atomic tool name (e.g. ``"apply_eligibility_chain_am"``).
    payload:
        Atomic tool's primary return body. Composed tools read fields
        out of this dict — the composed tool documents which keys it
        consumes from each atomic.
    citations:
        Primary-source citations emitted by the atomic tool, suitable
        for direct inclusion in the composed envelope's citation list.
    notes:
        Free-form warnings or staleness markers the atomic emitted.
    """

    tool_name: str
    payload: dict[str, Any]
    citations: tuple[dict[str, Any], ...] = ()
    notes: tuple[str, ...] = ()


class AtomicRegistry(Protocol):
    """Protocol implemented by the injected atomic-callable registry.

    Production usage wires this against the same Python functions the
    FastMCP tool wrappers ultimately call. Tests inject a deterministic
    fake — see ``tests/test_composable_tools.py`` for the canonical
    pattern.

    The registry is intentionally synchronous and pure-Python — composed
    tools never re-enter the MCP protocol, so there is no async hop.
    """

    def call(self, tool_name: str, /, **kwargs: Any) -> AtomicCallResult:
        """Invoke the atomic callable ``tool_name`` with ``kwargs``.

        Raises
        ------
        KeyError
            If ``tool_name`` is not registered. Composed tools call
            :meth:`ComposableTool.validate_registry` at construction
            time to surface this early.
        """
        ...

    def has(self, tool_name: str, /) -> bool:
        """Return True iff ``tool_name`` is registered."""
        ...


@dataclass(slots=True)
class ComposedEnvelope:
    """Return type emitted by every composed tool.

    The envelope wraps the canonical JPCIR ``Evidence`` model plus the
    citations and outcome contract a downstream agent needs to act on
    the composed result. It is **not** a new contract type — every
    field maps back to an existing canonical artifact in
    ``agent_runtime.contracts`` or ``api._envelope``.

    Attributes
    ----------
    composed_tool_name:
        Canonical composed-tool name (e.g. ``"eligibility_audit_workpaper"``).
    schema_version:
        Pinned to :data:`COMPOSED_ENVELOPE_SCHEMA_VERSION`.
    evidence:
        Canonical :class:`Evidence` justifying the composed result.
    outcome_contract:
        The :class:`OutcomeContract` the composed tool satisfies (e.g.
        the 税理士 audit pack contract).
    composed_steps:
        Ordered list of atomic tool names invoked. Mirrors
        :attr:`ComposableTool.atomic_dependencies` plus any optional
        atomic short-circuited at runtime.
    primary_result:
        The structured composed result — the main payload a downstream
        agent renders. Composed tools document the per-tool shape.
    citations:
        Aggregated citations from every atomic step. Duplicates may be
        deduplicated by the composed tool body.
    warnings:
        Soft warnings (atomic returned partial / stale / sparse data).
    compression_ratio:
        ``len(atomic_dependencies) / 1`` — the multiplier of "calls
        avoided" the agent gains by invoking the composed tool over
        chaining the atomic ones. Surfaced for billing / SDK debug.
    request_time_llm_call_performed:
        Always ``False`` — composed tools have no LLM hop. Mirrors the
        invariant on :class:`Evidence`.
    """

    composed_tool_name: str
    evidence: Evidence
    outcome_contract: OutcomeContract
    composed_steps: tuple[str, ...]
    primary_result: dict[str, Any]
    citations: tuple[dict[str, Any], ...] = ()
    warnings: tuple[str, ...] = ()
    schema_version: str = COMPOSED_ENVELOPE_SCHEMA_VERSION
    compression_ratio: int = field(default=1)
    request_time_llm_call_performed: bool = field(default=False, init=False)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable dict mirroring the wire shape.

        Used by REST / MCP wrappers that need a plain dict (no pydantic
        / dataclass coupling) — composed tools always emit a deterministic
        dict shape downstream consumers can pattern-match on.
        """
        return {
            "composed_tool_name": self.composed_tool_name,
            "schema_version": self.schema_version,
            "composed_steps": list(self.composed_steps),
            "compression_ratio": self.compression_ratio,
            "primary_result": dict(self.primary_result),
            "citations": [dict(c) for c in self.citations],
            "warnings": list(self.warnings),
            "evidence": self.evidence.model_dump(mode="json"),
            "outcome_contract": self.outcome_contract.model_dump(mode="json"),
            "request_time_llm_call_performed": self.request_time_llm_call_performed,
        }


class ComposableTool(ABC):
    """Abstract base for one composed tool.

    Subclasses declare:

    * :attr:`composed_tool_name` — canonical user-facing name.
    * :attr:`atomic_dependencies` — ordered tuple of atomic tool names
      this composed tool will invoke.
    * :attr:`outcome_contract` — the :class:`OutcomeContract` the tool
      satisfies.
    * :meth:`compose` — body that invokes the atomic registry and
      returns a :class:`ComposedEnvelope`.

    The base provides:

    * :meth:`validate_registry` — early-fail when an atomic dependency
      is missing.
    * :meth:`run` — public entry point that performs the validation
      then delegates to :meth:`compose`.

    Composed tools never call out to LLMs or aggregators (Dim P rule).
    """

    @property
    @abstractmethod
    def composed_tool_name(self) -> str:
        """Canonical user-facing name. MUST be stable across releases."""

    @property
    @abstractmethod
    def atomic_dependencies(self) -> tuple[str, ...]:
        """Ordered atomic tool names this composed tool invokes.

        Order matters — the registry validates names but not call
        ordering. The :meth:`compose` body invokes them in any order
        the composition logic requires (often sequential, sometimes
        with short-circuit on intermediate fail).
        """

    @property
    @abstractmethod
    def outcome_contract(self) -> OutcomeContract:
        """The :class:`OutcomeContract` this composed tool satisfies."""

    def validate_registry(self, registry: AtomicRegistry) -> None:
        """Verify every atomic dependency is registered.

        Called by :meth:`run` before any side effect. Raises
        :class:`ComposedToolError` with a developer-helpful message
        listing missing atomic tool names — avoids the silent
        degradation pattern of skipping the missing one.
        """
        missing = [name for name in self.atomic_dependencies if not registry.has(name)]
        if missing:
            raise ComposedToolError(
                f"composed tool {self.composed_tool_name!r} missing atomic "
                f"dependencies: {missing!r}. Composition cannot run — register "
                "every atomic before constructing the composed tool."
            )

    def run(self, registry: AtomicRegistry, /, **kwargs: Any) -> ComposedEnvelope:
        """Public entry point — validates registry, then composes.

        The wrapper does NOT swallow exceptions raised by
        :meth:`compose` — a composed tool that fails mid-flight bubbles
        the error so the caller can decide whether to retry or fall
        back to atomic call chaining.
        """
        self.validate_registry(registry)
        return self.compose(registry, **kwargs)

    @abstractmethod
    def compose(self, registry: AtomicRegistry, /, **kwargs: Any) -> ComposedEnvelope:
        """Invoke atomic tools in order, return composed envelope.

        Subclasses implement the composition logic here. They MUST
        return a :class:`ComposedEnvelope` — never raise on atomic
        partial result; surface those via ``warnings`` instead.
        """


__all__ = [
    "COMPOSED_ENVELOPE_SCHEMA_VERSION",
    "AtomicCallResult",
    "AtomicRegistry",
    "ComposableTool",
    "ComposedEnvelope",
    "ComposedToolError",
]
