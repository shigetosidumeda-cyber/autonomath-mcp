"""Graceful degradation envelope (Wave 43.3.7 — AX Resilience cell 7).

When an upstream sub-source (FTS shard, autonomath EAV table, am_amendment
chain, e-Gov fetch, JPO cache, NTA invoice rollup, …) fails inside a
multi-source route, the route can either:

  1. raise a 5xx — the agent / SDK sees an opaque failure and the rest of
     the response (which DID succeed) is thrown away, OR
  2. return what succeeded, mark the partial paths in ``warnings[]``, and
     stamp ``_meta.degraded=true`` so downstream agents can decide whether
     to retry or surface a soft warning to the human.

This module is the second path. Mirrors the §28.2 envelope (see
``_envelope.py``) in shape but is intentionally simpler — it operates on
an already-built result list and does NOT depend on Pydantic v2 / the
envelope models being imported. That keeps it usable from cron + ETL +
MCP tool surfaces too, not just FastAPI routes.

Contract::

    @degrade_on_partial("autonomath_facts", "amendment_diff")
    def my_route(...) -> dict:
        results = []
        with partial_source("autonomath_facts") as src:
            results.extend(fetch_facts(...))   # may raise
        with partial_source("amendment_diff") as src:
            results.extend(fetch_diff(...))    # may raise
        return {"results": results}

If both succeed → unchanged response. If one raises → response gets:

    {
      "results": [...],          # whatever DID succeed
      "warnings": [{"source": "...", "code": "PARTIAL_UPSTREAM_FAIL", ...}],
      "_meta": {"degraded": true, "failed_sources": [...], "ok_sources": [...]}
    }

NO LLM call, NO third-party deps, pure stdlib. Importable from
``scripts/cron`` and MCP tools without dragging the FastAPI stack.
"""

from __future__ import annotations

import contextlib
import functools
import logging
import time
from collections.abc import Callable, Iterator
from contextvars import ContextVar
from typing import Any, TypeVar

logger = logging.getLogger(__name__)

# Per-request scratch list of (source_name, status, error_class, latency_ms).
# Populated by ``partial_source(...)`` and drained by ``degrade_on_partial``.
_DEGRADATION_LEDGER: ContextVar[list[dict[str, Any]] | None] = ContextVar(
    "_DEGRADATION_LEDGER",
    default=None,
)

F = TypeVar("F", bound=Callable[..., Any])

# Canonical warning code so agents can pattern-match without parsing prose.
PARTIAL_UPSTREAM_CODE: str = "PARTIAL_UPSTREAM_FAIL"

# Hard cap on warnings emitted in one envelope — the route should be
# fan-out-bounded; if more than this fire we have a wider outage and
# should fall through to a 5xx upstream.
_MAX_WARNINGS: int = 16


@contextlib.contextmanager
def partial_source(name: str) -> Iterator[None]:
    """Mark a block as a degradable sub-source.

    Inside the block, raises are *swallowed* and recorded in the ledger.
    The outer route stays alive and finishes with whatever DID succeed.

    Outside ``degrade_on_partial`` this is a no-op safety net — exceptions
    propagate as usual. That keeps drop-in adoption safe in tests / ETL.
    """
    ledger = _DEGRADATION_LEDGER.get()
    started = time.monotonic()
    try:
        yield
    except Exception as exc:  # noqa: BLE001 — entire point is to capture broad
        elapsed_ms = int((time.monotonic() - started) * 1000)
        if ledger is None:
            # Outside the decorator, re-raise so dev / tests see the real error.
            raise
        ledger.append(
            {
                "source": name,
                "status": "fail",
                "error_class": type(exc).__name__,
                "error_message": str(exc)[:200],
                "latency_ms": elapsed_ms,
            }
        )
        logger.warning(
            "partial_source.fail name=%s err=%s msg=%s",
            name,
            type(exc).__name__,
            str(exc)[:200],
        )
    else:
        elapsed_ms = int((time.monotonic() - started) * 1000)
        if ledger is not None:
            ledger.append(
                {
                    "source": name,
                    "status": "ok",
                    "latency_ms": elapsed_ms,
                }
            )


def degrade_on_partial(*declared_sources: str) -> Callable[[F], F]:
    """Decorator wrapping a route fn so partial failures degrade gracefully.

    ``declared_sources`` is the *expected* fan-out — any source that
    appears in the ledger but NOT here will still surface in warnings
    (so the route author can't silently widen the contract).
    """

    def decorator(fn: F) -> F:
        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            token = _DEGRADATION_LEDGER.set([])
            try:
                result = fn(*args, **kwargs)
                ledger = _DEGRADATION_LEDGER.get() or []
            finally:
                _DEGRADATION_LEDGER.reset(token)
            return _apply_degradation_envelope(result, ledger, declared_sources)

        return wrapper  # type: ignore[return-value]

    return decorator


def _apply_degradation_envelope(
    result: Any,
    ledger: list[dict[str, Any]],
    declared: tuple[str, ...],
) -> Any:
    """Merge ledger into the response. Non-dict responses pass through."""
    if not isinstance(result, dict):
        return result
    if not ledger:
        return result

    fails = [r for r in ledger if r.get("status") == "fail"]
    oks = [r for r in ledger if r.get("status") == "ok"]
    if not fails:
        return result

    warnings = list(result.get("warnings") or [])
    for f in fails[:_MAX_WARNINGS]:
        warnings.append(
            {
                "code": PARTIAL_UPSTREAM_CODE,
                "source": f["source"],
                "error_class": f.get("error_class", "Exception"),
                "developer_message": f.get("error_message", ""),
                "latency_ms": f.get("latency_ms", 0),
                "declared": f["source"] in declared,
            }
        )

    meta = dict(result.get("_meta") or result.get("meta") or {})
    meta["degraded"] = True
    meta["failed_sources"] = [f["source"] for f in fails]
    meta["ok_sources"] = [r["source"] for r in oks]
    meta["partial_fanout"] = {
        "declared": list(declared),
        "fired": [r["source"] for r in ledger],
        "fail_count": len(fails),
        "ok_count": len(oks),
    }

    out = dict(result)
    out["warnings"] = warnings
    out["_meta"] = meta
    # Mirror to ``meta`` for legacy consumers that read the older key.
    if "meta" in result:
        out["meta"] = meta
    # Status hint: rich/sparse/empty/partial/error (§28.2).  We do not
    # overwrite an existing terminal status, only soften rich→partial.
    if out.get("status") == "rich" or "status" not in out:
        out["status"] = "partial"
    return out


def is_degraded(response: Any) -> bool:
    """Convenience for tests / smoke checks."""
    if not isinstance(response, dict):
        return False
    meta = response.get("_meta") or response.get("meta") or {}
    return bool(meta.get("degraded"))


__all__ = [
    "PARTIAL_UPSTREAM_CODE",
    "degrade_on_partial",
    "is_degraded",
    "partial_source",
]
