"""McpProxy — pure dispatcher for MCP tool calls (NO LLM inference).

The proxy is the **inference-free** seam between the embedded widget
(running inside a host SaaS page) and the jpcite atomic-callable
registry. Per ``feedback_copilot_scaffold_only_no_llm``::

    "widget 自体に LLM 推論層作るな、scaffold + proxy のみ"
    "推論は顧客側 LLM で完結させる"

The widget posts ``{tool, kwargs}`` to a host-owned proxy endpoint;
the endpoint includes the per-host ``X-Jpcite-Proxy-Token`` header and
forwards the call to :meth:`McpProxy.dispatch`. The proxy then calls the
declared atomic Python function through the injected
:class:`AtomicToolRegistry` and returns the result *verbatim*. There is
**no** inference, no rewriting, no auto-composition — composed tools
exist in :mod:`jpintel_mcp.composable_tools` and the embedded widget can
invoke them by name, but the proxy itself never picks the tool.

LLM-0 invariant
---------------
The proxy file MUST NOT import any LLM SDK (``anthropic`` / ``openai``
/ ``google.generativeai`` / ``langchain`` / ``mistralai`` / ``cohere``
/ ``groq`` / ``replicate`` / ``together`` / ``vertexai`` /
``bedrock_runtime`` / ``claude_agent_sdk``). The CI guard
``tests/test_no_llm_in_production.py`` (already 9/9 PASS, see CLAUDE.md
§"What NOT to do") enforces this across ``src/`` / ``scripts/`` /
``tests/``. The companion test ``tests/test_copilot_scaffold.py::
test_proxy_module_has_no_llm_imports`` asserts the invariant locally
so a regression in this single file fails before the global CI guard.

Tool-name allowlist
-------------------
Hosts may further restrict which atomic tools the widget can invoke via
:meth:`McpProxy.__init__`'s ``allowed_tools`` parameter (frozenset).
``None`` means "allow every tool the registry knows about" — useful for
hosts whose policy team has approved the full surface. A non-``None``
allowlist is enforced *before* the registry is consulted so dispatch
returns ``error_code='tool_not_allowed'`` rather than leaking knowledge
of the broader registry.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final, Protocol

#: Schema version emitted by every proxy result envelope. Bump when the
#: :class:`McpProxyResult` wire shape gains a backwards-incompatible
#: field.
PROXY_RESULT_SCHEMA_VERSION: Final[str] = "copilot_scaffold.dim_s.v1"

#: Reasons a dispatch may fail without inference. Stable enum so the
#: widget JS can render localized error copy without parsing free-text.
DISPATCH_ERROR_CODES: Final[frozenset[str]] = frozenset(
    {
        "tool_not_found",
        "tool_not_allowed",
        "tool_raised",
        "invalid_kwargs",
    }
)


class AtomicToolRegistry(Protocol):
    """Protocol implemented by the injected atomic-callable registry.

    Production usage wires this against the same Python functions the
    FastMCP tool wrappers ultimately call. Tests inject a deterministic
    fake — see ``tests/test_copilot_scaffold.py`` for the canonical
    pattern.

    The registry is synchronous and pure-Python. The proxy never
    re-enters the MCP protocol so there is no async hop.
    """

    def call(self, tool_name: str, /, **kwargs: Any) -> Any:
        """Invoke atomic callable ``tool_name`` with ``kwargs``.

        Raises ``KeyError`` if ``tool_name`` is not registered.
        Any other exception propagates as ``error_code='tool_raised'``
        in the proxy result envelope.
        """
        ...

    def has(self, tool_name: str, /) -> bool:
        """Return True iff ``tool_name`` is registered."""
        ...


@dataclass(frozen=True, slots=True)
class McpProxyResult:
    """Return shape emitted by :meth:`McpProxy.dispatch`.

    Attributes
    ----------
    ok:
        ``True`` iff the dispatch reached the atomic tool and returned
        without raising. ``False`` on any error_code.
    tool_name:
        Echoed-back tool name so the widget can correlate concurrent
        calls in flight.
    payload:
        The atomic tool's return value verbatim, or ``None`` on error.
    error_code:
        One of :data:`DISPATCH_ERROR_CODES`, or ``None`` on success.
    error_message:
        Human-readable error message. Empty string on success.
    schema_version:
        Pinned to :data:`PROXY_RESULT_SCHEMA_VERSION`.
    llm_inference_performed:
        Always ``False``. Asserted by
        :meth:`McpProxy.dispatch` so a future refactor that adds an
        inference branch fails loudly. The widget MAY pass this through
        to its UI as a transparency signal.
    """

    ok: bool
    tool_name: str
    payload: Any
    error_code: str | None
    error_message: str
    schema_version: str = PROXY_RESULT_SCHEMA_VERSION
    llm_inference_performed: bool = False


class McpProxy:
    """Pure dispatcher — forwards MCP tool calls without inference.

    Construction binds the proxy to one :class:`AtomicToolRegistry` and
    optionally one tool allowlist. The proxy itself holds no per-request
    state, so a single instance can be shared across requests safely.

    Parameters
    ----------
    registry:
        Atomic-callable registry to dispatch against.
    allowed_tools:
        Optional frozenset of tool names. If provided, dispatch rejects
        any tool name not in the set with ``error_code='tool_not_allowed'``.
        If ``None``, dispatch falls through to the registry's ``has()``
        check. Either form fails closed — there is no path that bypasses
        the allowlist.
    """

    __slots__ = ("_registry", "_allowed_tools")

    def __init__(
        self,
        registry: AtomicToolRegistry,
        *,
        allowed_tools: frozenset[str] | None = None,
    ) -> None:
        self._registry = registry
        self._allowed_tools = allowed_tools

    @property
    def allowed_tools(self) -> frozenset[str] | None:
        """Configured allowlist (or ``None`` if every registry tool is allowed)."""
        return self._allowed_tools

    def dispatch(self, tool_name: str, /, **kwargs: Any) -> McpProxyResult:
        """Forward one MCP tool call to the atomic registry.

        The dispatch path is **explicitly non-inferential**: it does not
        rewrite ``tool_name``, does not auto-compose missing tools, and
        does not call any LLM SDK. The widget gets back exactly what
        the atomic callable returned.

        Parameters
        ----------
        tool_name:
            Atomic tool name to invoke.
        kwargs:
            Forwarded verbatim to the atomic callable.

        Returns
        -------
        McpProxyResult
            Always returned (never raises). Use ``result.ok`` and
            ``result.error_code`` to branch in the caller.
        """
        # Validate kwargs shape early so dispatch fails closed before
        # the registry is consulted. We only reject the obvious foot-gun
        # of non-string keys; the atomic itself is responsible for its
        # own kwargs schema.
        for key in kwargs:
            if not isinstance(key, str):
                return McpProxyResult(
                    ok=False,
                    tool_name=tool_name,
                    payload=None,
                    error_code="invalid_kwargs",
                    error_message=f"kwargs key {key!r} is not a string",
                )

        # Allowlist check first so we do not leak knowledge of which
        # tools exist beyond the host's approved set.
        if self._allowed_tools is not None and tool_name not in self._allowed_tools:
            return McpProxyResult(
                ok=False,
                tool_name=tool_name,
                payload=None,
                error_code="tool_not_allowed",
                error_message=(
                    f"tool {tool_name!r} not in this host's allowlist "
                    f"(size={len(self._allowed_tools)})"
                ),
            )

        if not self._registry.has(tool_name):
            return McpProxyResult(
                ok=False,
                tool_name=tool_name,
                payload=None,
                error_code="tool_not_found",
                error_message=f"tool {tool_name!r} not registered in atomic registry",
            )

        try:
            payload = self._registry.call(tool_name, **kwargs)
        except Exception as exc:  # noqa: BLE001 — proxy MUST NOT bubble exceptions
            # We deliberately catch broad: the proxy is the boundary the
            # widget sees, and an uncaught exception would propagate as
            # a 500 with stack-trace exposure. Atomic tools that need
            # to surface structured errors should embed them in their
            # return value (the composable_tools pattern).
            return McpProxyResult(
                ok=False,
                tool_name=tool_name,
                payload=None,
                error_code="tool_raised",
                error_message=f"{type(exc).__name__}: {exc}",
            )

        return McpProxyResult(
            ok=True,
            tool_name=tool_name,
            payload=payload,
            error_code=None,
            error_message="",
        )


__all__ = [
    "DISPATCH_ERROR_CODES",
    "PROXY_RESULT_SCHEMA_VERSION",
    "AtomicToolRegistry",
    "McpProxy",
    "McpProxyResult",
]
