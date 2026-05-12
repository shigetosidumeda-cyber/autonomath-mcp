"""Hystrix-style circuit breaker (Wave 43.3.3 — AX Resilience cell 3).

When an upstream dependency (Stripe API, e-Gov pull, JPO cache, NTA
invoice rollup, autonomath EAV query) starts failing, blindly retrying
each call burns latency budget and amplifies the outage. A circuit
breaker watches the recent failure rate and SHORT-CIRCUITS calls in the
OPEN state, returning fast-fail without touching the dependency, until a
cooldown elapses; HALF_OPEN then sends a small probe to decide whether
to close again.

Same shape as ``_failover.py`` / ``_degradation.py`` — small dataclass +
context manager + decorator, pure stdlib, no third-party deps. NO LLM
call. Importable from MCP tools, cron, ETL alike.

State machine:

    closed ──[failure_threshold exceeded]──▶ open
       ▲                                       │
       │                                       │ cooldown elapsed
       │                                       ▼
    closed ◀──[success_threshold met]── half_open
                                            │
                                            └──[any failure]──▶ open

Contract::

    breaker = CircuitBreaker(name="stripe_charge")
    try:
        with breaker:
            response = call_stripe()
    except CircuitOpenError:
        # short-circuit path: degrade or 503
        ...

The decorator form is the common case::

    @circuit_breaker("egov_fetch")
    def fetch(article_id: str) -> bytes:
        ...
"""

from __future__ import annotations

import functools
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal, TypeVar

logger = logging.getLogger(__name__)

# Hystrix-style defaults, tuned for our typical upstream profiles:
#   * 5 consecutive failures → open (1s probe → 5s @ p99 latency budget)
#   * 30s cooldown before any half-open probe
#   * 2 successes in half-open → fully close
#   * fail-fast on any half-open failure → reopen immediately
DEFAULT_FAILURE_THRESHOLD: int = 5
DEFAULT_SUCCESS_THRESHOLD: int = 2
DEFAULT_COOLDOWN_SECONDS: float = 30.0
DEFAULT_HALF_OPEN_MAX_CALLS: int = 1

# When recording outcomes we keep at most this many recent ticks for
# rate-based exporters / dashboards. Strict O(1) memory.
_MAX_HISTORY: int = 64

StateType = Literal["closed", "open", "half_open"]

F = TypeVar("F", bound=Callable[..., Any])


class CircuitOpenError(RuntimeError):
    """Raised when a call is short-circuited because the breaker is open.

    Distinct from the underlying upstream error so callers can pattern-
    match: ``except CircuitOpenError: return degraded_response()``.
    """

    def __init__(self, name: str, opened_at: float, cooldown_seconds: float) -> None:
        self.name = name
        self.opened_at = opened_at
        self.cooldown_seconds = cooldown_seconds
        remaining = max(0.0, opened_at + cooldown_seconds - time.time())
        super().__init__(
            f"circuit '{name}' is open (retry in {remaining:.1f}s)"
        )


@dataclass
class CircuitState:
    """Snapshot of a breaker's internal counters at one instant."""

    name: str
    state: StateType
    failure_count: int
    success_count: int
    half_open_calls: int
    opened_at: float
    last_failure_at: float
    last_success_at: float
    total_calls: int
    total_failures: int
    total_short_circuits: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "state": self.state,
            "failure_count": self.failure_count,
            "success_count": self.success_count,
            "half_open_calls": self.half_open_calls,
            "opened_at": self.opened_at,
            "last_failure_at": self.last_failure_at,
            "last_success_at": self.last_success_at,
            "total_calls": self.total_calls,
            "total_failures": self.total_failures,
            "total_short_circuits": self.total_short_circuits,
        }


@dataclass
class CircuitBreaker:
    """Hystrix-style breaker. Construct once, share across call sites.

    Thread-safe via a single lock — at our request rates the contention
    is negligible compared to the upstream latency it protects.
    """

    name: str
    failure_threshold: int = DEFAULT_FAILURE_THRESHOLD
    success_threshold: int = DEFAULT_SUCCESS_THRESHOLD
    cooldown_seconds: float = DEFAULT_COOLDOWN_SECONDS
    half_open_max_calls: int = DEFAULT_HALF_OPEN_MAX_CALLS
    # Caller can pass an iterable of exception classes that should NOT
    # trip the breaker (e.g. ``ValueError`` for client bugs that are not
    # an upstream outage signal). Default = all exceptions count.
    excluded_exceptions: tuple[type[BaseException], ...] = field(
        default_factory=tuple
    )

    _state: StateType = field(default="closed", init=False)
    _failure_count: int = field(default=0, init=False)
    _success_count: int = field(default=0, init=False)
    _half_open_calls: int = field(default=0, init=False)
    _opened_at: float = field(default=0.0, init=False)
    _last_failure_at: float = field(default=0.0, init=False)
    _last_success_at: float = field(default=0.0, init=False)
    _total_calls: int = field(default=0, init=False)
    _total_failures: int = field(default=0, init=False)
    _total_short_circuits: int = field(default=0, init=False)
    _lock: threading.RLock = field(default_factory=threading.RLock, init=False)

    # ------------------------------------------------------------------
    # State queries
    # ------------------------------------------------------------------

    @property
    def state(self) -> StateType:
        """Best-effort current state — may transition open→half_open here."""
        with self._lock:
            self._maybe_half_open()
            return self._state

    def snapshot(self) -> CircuitState:
        with self._lock:
            self._maybe_half_open()
            return CircuitState(
                name=self.name,
                state=self._state,
                failure_count=self._failure_count,
                success_count=self._success_count,
                half_open_calls=self._half_open_calls,
                opened_at=self._opened_at,
                last_failure_at=self._last_failure_at,
                last_success_at=self._last_success_at,
                total_calls=self._total_calls,
                total_failures=self._total_failures,
                total_short_circuits=self._total_short_circuits,
            )

    # ------------------------------------------------------------------
    # Outcome recording — used by context manager + decorator
    # ------------------------------------------------------------------

    def record_success(self) -> None:
        with self._lock:
            self._last_success_at = time.time()
            if self._state == "half_open":
                self._success_count += 1
                if self._success_count >= self.success_threshold:
                    self._close()
            elif self._state == "closed":
                # Reset consecutive failure counter on any success.
                self._failure_count = 0

    def record_failure(self, exc: BaseException | None = None) -> None:
        if exc is not None and self.excluded_exceptions and isinstance(
            exc, self.excluded_exceptions
        ):
            # Client-bug-like exceptions don't count.
            return
        with self._lock:
            self._last_failure_at = time.time()
            self._total_failures += 1
            if self._state == "half_open":
                # Any failure in half_open → reopen with full cooldown.
                self._open()
                return
            if self._state == "closed":
                self._failure_count += 1
                if self._failure_count >= self.failure_threshold:
                    self._open()

    # ------------------------------------------------------------------
    # Public entry points
    # ------------------------------------------------------------------

    def __enter__(self) -> CircuitBreaker:
        with self._lock:
            self._maybe_half_open()
            self._total_calls += 1
            if self._state == "open":
                self._total_short_circuits += 1
                raise CircuitOpenError(
                    self.name, self._opened_at, self.cooldown_seconds
                )
            if self._state == "half_open":
                if self._half_open_calls >= self.half_open_max_calls:
                    self._total_short_circuits += 1
                    raise CircuitOpenError(
                        self.name, self._opened_at, self.cooldown_seconds
                    )
                self._half_open_calls += 1
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        if exc_type is None:
            self.record_success()
        else:
            self.record_failure(exc_val)
        return False  # never swallow the exception

    def reset(self) -> None:
        """Force the breaker back to closed (test / admin operation)."""
        with self._lock:
            self._close()
            self._failure_count = 0
            self._success_count = 0
            self._half_open_calls = 0

    # ------------------------------------------------------------------
    # Internal state transitions — caller MUST hold the lock
    # ------------------------------------------------------------------

    def _open(self) -> None:
        if self._state != "open":
            logger.warning(
                "circuit_breaker.open name=%s failures=%s",
                self.name,
                self._failure_count,
            )
        self._state = "open"
        self._opened_at = time.time()
        self._success_count = 0
        self._half_open_calls = 0

    def _close(self) -> None:
        if self._state != "closed":
            logger.info("circuit_breaker.close name=%s", self.name)
        self._state = "closed"
        self._failure_count = 0
        self._success_count = 0
        self._half_open_calls = 0

    def _half_open(self) -> None:
        if self._state != "half_open":
            logger.info("circuit_breaker.half_open name=%s", self.name)
        self._state = "half_open"
        self._success_count = 0
        self._half_open_calls = 0

    def _maybe_half_open(self) -> None:
        """If open + cooldown elapsed → transition to half_open."""
        if self._state != "open":
            return
        if time.time() >= self._opened_at + self.cooldown_seconds:
            self._half_open()


# ---------------------------------------------------------------------------
# Process-level registry — so multiple call sites share the same breaker
# ---------------------------------------------------------------------------

_REGISTRY: dict[str, CircuitBreaker] = {}
_REGISTRY_LOCK = threading.Lock()


def get_breaker(
    name: str,
    *,
    failure_threshold: int = DEFAULT_FAILURE_THRESHOLD,
    success_threshold: int = DEFAULT_SUCCESS_THRESHOLD,
    cooldown_seconds: float = DEFAULT_COOLDOWN_SECONDS,
    half_open_max_calls: int = DEFAULT_HALF_OPEN_MAX_CALLS,
    excluded_exceptions: tuple[type[BaseException], ...] = (),
) -> CircuitBreaker:
    """Return the shared breaker for ``name`` (creating it on first call)."""
    with _REGISTRY_LOCK:
        existing = _REGISTRY.get(name)
        if existing is not None:
            return existing
        breaker = CircuitBreaker(
            name=name,
            failure_threshold=failure_threshold,
            success_threshold=success_threshold,
            cooldown_seconds=cooldown_seconds,
            half_open_max_calls=half_open_max_calls,
            excluded_exceptions=excluded_exceptions,
        )
        _REGISTRY[name] = breaker
        return breaker


def circuit_breaker(
    name: str,
    *,
    failure_threshold: int = DEFAULT_FAILURE_THRESHOLD,
    success_threshold: int = DEFAULT_SUCCESS_THRESHOLD,
    cooldown_seconds: float = DEFAULT_COOLDOWN_SECONDS,
    half_open_max_calls: int = DEFAULT_HALF_OPEN_MAX_CALLS,
    excluded_exceptions: tuple[type[BaseException], ...] = (),
) -> Callable[[F], F]:
    """Decorator form — wrap a callable in the registry-shared breaker."""

    def decorator(fn: F) -> F:
        breaker = get_breaker(
            name,
            failure_threshold=failure_threshold,
            success_threshold=success_threshold,
            cooldown_seconds=cooldown_seconds,
            half_open_max_calls=half_open_max_calls,
            excluded_exceptions=excluded_exceptions,
        )

        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            with breaker:
                return fn(*args, **kwargs)

        return wrapper  # type: ignore[return-value]

    return decorator


def all_breakers() -> dict[str, CircuitState]:
    """Snapshot every registered breaker — used by status-page exporter."""
    with _REGISTRY_LOCK:
        return {name: b.snapshot() for name, b in _REGISTRY.items()}


def reset_all_breakers() -> None:
    """Test helper — drop every breaker so a new test starts clean."""
    with _REGISTRY_LOCK:
        for b in _REGISTRY.values():
            b.reset()
        _REGISTRY.clear()


__all__ = [
    "DEFAULT_COOLDOWN_SECONDS",
    "DEFAULT_FAILURE_THRESHOLD",
    "DEFAULT_HALF_OPEN_MAX_CALLS",
    "DEFAULT_SUCCESS_THRESHOLD",
    "CircuitBreaker",
    "CircuitOpenError",
    "CircuitState",
    "all_breakers",
    "circuit_breaker",
    "get_breaker",
    "reset_all_breakers",
]
