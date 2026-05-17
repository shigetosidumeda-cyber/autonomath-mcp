"""Heavy-Output endpoint HE-4 — ``multi_tool_orchestrate`` server-side bundler.

Bundles N MCP tool calls into a single agent round trip. Internally
dispatches each ``tool_call`` against the live ``mcp._tool_manager``
registry via ``asyncio.gather``. Synchronous tool functions are pushed
to ``asyncio.to_thread`` so the event loop can interleave them with any
``async`` tools.

User directive (2026-05-17): "実は統合できるかもしれない" — surface a
single endpoint that lets a tax / accounting agent ask for multiple
parallel facts in **one** call (e.g. ``search_programs`` +
``get_houjin_360`` + ``find_filing_window`` + ``walk_reasoning_chain``)
instead of paying N agent ↔ server round trips.

Contract
--------

Inputs:
* ``tool_calls`` — list of ``{"tool": str, "args": dict}``. Tool names
  must already be registered on the MCP server (allowlist enforced).
* ``parallel`` — when ``True`` (default), all dispatched tools run via
  ``asyncio.gather``. ``False`` falls back to a serial loop (mostly for
  benchmark comparison; the agent network saving is the same either
  way).
* ``fail_strategy`` — ``"partial"`` returns per-call ``status`` markers,
  ``"all_or_nothing"`` raises on the first error and short-circuits the
  remaining calls.
* ``max_concurrent`` — bounded semaphore so a runaway agent cannot
  starve the host process. Default 10, hard-capped at 32.

Outputs:
* ``results`` — per-call envelope with ``tool_call_idx`` / ``tool`` /
  ``status`` (ok|error|rejected|skipped) / ``result`` (passthrough of
  the inner tool's envelope) / ``latency_ms``.
* ``summary`` — totals.
* ``billing`` — ¥3 × N (transparent: each dispatched call bills as a
  ¥3/req unit; the orchestrator itself does not double-bill).
* ``_disclaimer`` / ``_provenance`` — canonical envelope. NO LLM.

Hard constraints (CLAUDE.md):
* NO LLM inference inside this module.
* Dynamic dispatch is **allowlist-only** — the dispatched tool name
  must exist in ``mcp._tool_manager.list_tools()``. Anything else is
  rejected with ``status="rejected"`` and reason ``unknown_tool``.
* Tools whose names start with an underscore are treated as private
  and refused (defence-in-depth).
* ``orchestrate`` does not recurse — calling
  ``multi_tool_orchestrate`` from inside the bundle is refused to
  avoid stack-amplification attacks.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import time
from typing import Annotated, Any

from pydantic import Field

from jpintel_mcp.mcp.server import _READ_ONLY, mcp

from ._shared import DISCLAIMER, today_iso_utc

logger = logging.getLogger("jpintel.mcp.moat_lane_tools.he4_orchestrate")

_LANE_ID = "HE-4"
_SCHEMA_VERSION = "moat.he4.v1"
_UPSTREAM_MODULE = "jpintel_mcp.moat.he4_orchestrate"
_TOOL_NAME = "multi_tool_orchestrate"

# Defence-in-depth caps. Even with parallel=True, a single agent must
# not be able to fan out unbounded work.
_MAX_TOOL_CALLS = 32
_MAX_CONCURRENT_HARD_CAP = 32
_FAIL_STRATEGIES = ("partial", "all_or_nothing")

# Tools we refuse to self-dispatch through HE-4 (anti-recursion +
# reserved for explicit orchestration use).
_DENYLIST: frozenset[str] = frozenset({_TOOL_NAME})


def _envelope_error(
    *,
    rationale: str,
    tool_calls_input: list[Any],
    parallel: bool,
    fail_strategy: str,
    max_concurrent: int,
) -> dict[str, Any]:
    """Top-level error envelope (input rejected before any dispatch)."""
    return {
        "tool_name": _TOOL_NAME,
        "schema_version": _SCHEMA_VERSION,
        "primary_result": {
            "status": "rejected",
            "lane_id": _LANE_ID,
            "upstream_module": _UPSTREAM_MODULE,
            "rationale": rationale,
            "primary_input": {
                "tool_calls": tool_calls_input,
                "parallel": parallel,
                "fail_strategy": fail_strategy,
                "max_concurrent": max_concurrent,
            },
        },
        "results": [],
        "summary": {
            "total_calls": 0,
            "ok": 0,
            "error": 0,
            "rejected": 0,
            "skipped": 0,
            "total_latency_ms": 0,
        },
        "billing": {
            "unit": 0,
            "yen": 0,
            "_bundle_discount": "0 calls dispatched — no billing applied.",
        },
        "_disclaimer": DISCLAIMER,
        "_provenance": {
            "source_module": _UPSTREAM_MODULE,
            "lane_id": _LANE_ID,
            "wrap_kind": "moat_lane_he4_orchestrate",
            "observed_at": today_iso_utc(),
        },
    }


def _normalize_tool_calls(raw: Any) -> tuple[list[dict[str, Any]] | None, str | None]:
    """Validate the ``tool_calls`` list shape. Return (parsed, reason)."""
    if not isinstance(raw, list):
        return None, "tool_calls must be a JSON list."
    if not raw:
        return None, "tool_calls must contain at least one entry."
    if len(raw) > _MAX_TOOL_CALLS:
        return (
            None,
            f"tool_calls length {len(raw)} exceeds hard cap {_MAX_TOOL_CALLS}.",
        )
    out: list[dict[str, Any]] = []
    for idx, item in enumerate(raw):
        if not isinstance(item, dict):
            return None, f"tool_calls[{idx}] must be a JSON object."
        tool = item.get("tool")
        if not isinstance(tool, str) or not tool:
            return None, f"tool_calls[{idx}].tool must be a non-empty string."
        args = item.get("args", {})
        if args is None:
            args = {}
        if not isinstance(args, dict):
            return None, f"tool_calls[{idx}].args must be a JSON object or omitted."
        out.append({"tool": tool, "args": args})
    return out, None


def _list_allowed_tools() -> set[str]:
    """Snapshot of currently registered MCP tool names (allowlist)."""
    try:
        return {t.name for t in mcp._tool_manager.list_tools()}
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("he4: tool registry snapshot failed: %s", exc)
        return set()


async def _dispatch_one(
    *,
    idx: int,
    tool_call: dict[str, Any],
    allowed: set[str],
    semaphore: asyncio.Semaphore,
) -> dict[str, Any]:
    """Dispatch a single tool call. Always returns a per-call envelope."""
    tool_name = tool_call["tool"]
    args = tool_call["args"]
    started = time.perf_counter()

    # Allowlist + denylist (anti-recursion / anti-private).
    if tool_name.startswith("_"):
        return {
            "tool_call_idx": idx,
            "tool": tool_name,
            "status": "rejected",
            "error": "private tool name (leading underscore) refused.",
            "latency_ms": int((time.perf_counter() - started) * 1000),
        }
    if tool_name in _DENYLIST:
        return {
            "tool_call_idx": idx,
            "tool": tool_name,
            "status": "rejected",
            "error": "recursion into multi_tool_orchestrate is refused.",
            "latency_ms": int((time.perf_counter() - started) * 1000),
        }
    if tool_name not in allowed:
        return {
            "tool_call_idx": idx,
            "tool": tool_name,
            "status": "rejected",
            "error": "unknown_tool — not registered on this MCP server.",
            "latency_ms": int((time.perf_counter() - started) * 1000),
        }

    try:
        tool_obj = mcp._tool_manager.get_tool(tool_name)
    except Exception as exc:
        return {
            "tool_call_idx": idx,
            "tool": tool_name,
            "status": "rejected",
            "error": f"tool registry lookup failed: {exc!s}",
            "latency_ms": int((time.perf_counter() - started) * 1000),
        }
    if tool_obj is None:
        return {
            "tool_call_idx": idx,
            "tool": tool_name,
            "status": "rejected",
            "error": "tool registry returned None for known name.",
            "latency_ms": int((time.perf_counter() - started) * 1000),
        }
    fn = tool_obj.fn

    async with semaphore:
        try:
            if inspect.iscoroutinefunction(fn) or getattr(tool_obj, "is_async", False):
                result = await fn(**args)
            else:
                # Push synchronous tools off the event loop so they
                # actually run in parallel when ``parallel=True``.
                result = await asyncio.to_thread(fn, **args)
        except TypeError as exc:
            # Bad args — surface as error (not rejected) because the
            # tool name was valid but the call shape was wrong.
            return {
                "tool_call_idx": idx,
                "tool": tool_name,
                "status": "error",
                "error": f"bad args: {exc!s}",
                "latency_ms": int((time.perf_counter() - started) * 1000),
            }
        except Exception as exc:  # noqa: BLE001 — orchestrator must never crash
            return {
                "tool_call_idx": idx,
                "tool": tool_name,
                "status": "error",
                "error": f"{type(exc).__name__}: {exc!s}",
                "latency_ms": int((time.perf_counter() - started) * 1000),
            }

    return {
        "tool_call_idx": idx,
        "tool": tool_name,
        "status": "ok",
        "result": result,
        "latency_ms": int((time.perf_counter() - started) * 1000),
    }


async def _orchestrate_async(
    *,
    tool_calls: list[dict[str, Any]],
    parallel: bool,
    fail_strategy: str,
    max_concurrent: int,
) -> tuple[list[dict[str, Any]], int]:
    """Run every call (parallel or serial). Returns (results, total_ms)."""
    allowed = _list_allowed_tools()
    # Bounded semaphore — even when parallel=False, the semaphore is a
    # cheap no-op (1 permit). When parallel=True, this caps fan-out.
    sem = asyncio.Semaphore(max_concurrent if parallel else 1)
    started = time.perf_counter()

    if parallel:
        # asyncio.gather preserves input order; we don't need
        # return_exceptions because _dispatch_one swallows all errors.
        coros = [
            _dispatch_one(idx=i, tool_call=tc, allowed=allowed, semaphore=sem)
            for i, tc in enumerate(tool_calls)
        ]
        if fail_strategy == "all_or_nothing":
            # Run sequentially-aware: schedule all, but short-circuit
            # the remaining tasks as soon as any one fails. We
            # accomplish that by awaiting one at a time in order and
            # marking the rest as "skipped".
            results: list[dict[str, Any]] = []
            tasks = [asyncio.create_task(c) for c in coros]
            failed = False
            for i, task in enumerate(tasks):
                if failed:
                    task.cancel()
                    results.append(
                        {
                            "tool_call_idx": i,
                            "tool": tool_calls[i]["tool"],
                            "status": "skipped",
                            "error": "skipped due to all_or_nothing short-circuit.",
                            "latency_ms": 0,
                        }
                    )
                    continue
                try:
                    res = await task
                except asyncio.CancelledError:
                    res = {
                        "tool_call_idx": i,
                        "tool": tool_calls[i]["tool"],
                        "status": "skipped",
                        "error": "cancelled (all_or_nothing).",
                        "latency_ms": 0,
                    }
                results.append(res)
                if res["status"] in ("error", "rejected"):
                    failed = True
            total_ms = int((time.perf_counter() - started) * 1000)
            return results, total_ms

        results = await asyncio.gather(*coros)
    else:
        # Serial path (mostly for benchmarks vs parallel).
        results = []
        for i, tc in enumerate(tool_calls):
            res = await _dispatch_one(idx=i, tool_call=tc, allowed=allowed, semaphore=sem)
            results.append(res)
            if fail_strategy == "all_or_nothing" and res["status"] in ("error", "rejected"):
                # Mark remaining as skipped.
                for j in range(i + 1, len(tool_calls)):
                    results.append(
                        {
                            "tool_call_idx": j,
                            "tool": tool_calls[j]["tool"],
                            "status": "skipped",
                            "error": "skipped due to all_or_nothing short-circuit.",
                            "latency_ms": 0,
                        }
                    )
                break

    total_ms = int((time.perf_counter() - started) * 1000)
    return results, total_ms


@mcp.tool(annotations=_READ_ONLY)
def multi_tool_orchestrate(
    tool_calls: Annotated[
        list[dict[str, Any]],
        Field(
            description=(
                "List of tool calls to dispatch in parallel. Each entry is "
                "{'tool': <name>, 'args': {<kwargs>}}. Tool names must "
                "already be registered on this MCP server. Hard cap 32."
            ),
            min_length=1,
            max_length=_MAX_TOOL_CALLS,
        ),
    ],
    parallel: Annotated[
        bool,
        Field(
            description=(
                "When True (default), all tools dispatch concurrently via "
                "asyncio.gather. When False, falls back to serial — useful "
                "for benchmark / debug only."
            ),
        ),
    ] = True,
    fail_strategy: Annotated[
        str,
        Field(
            pattern=r"^(partial|all_or_nothing)$",
            description=(
                "partial: continue on per-call errors, mark each with "
                "status. all_or_nothing: stop on first error and mark "
                "remaining calls as skipped."
            ),
        ),
    ] = "partial",
    max_concurrent: Annotated[
        int,
        Field(
            ge=1,
            le=_MAX_CONCURRENT_HARD_CAP,
            description=(
                f"Bounded concurrency cap (1..{_MAX_CONCURRENT_HARD_CAP}). "
                "Default 10. Only relevant when parallel=True."
            ),
        ),
    ] = 10,
) -> dict[str, Any]:
    """[AUDIT, SENSITIVE - SS52/SS47-2/SS72/SS1/SS3] HE-4 server-side bundler:
    dispatch N MCP tool calls in one round trip. Per-call billing (¥3 each)
    is transparent — the bundle discount is in network round trips, not in
    ¥. NO LLM inference. Dispatched tool names must be allowlisted (i.e.
    already registered on this MCP server). Use this when an agent has
    independent parallel queries (e.g. search_programs + get_houjin_360 +
    find_filing_window) and wants 1 round trip instead of N.
    """
    # Input validation.
    parsed, reason = _normalize_tool_calls(tool_calls)
    if parsed is None:
        return _envelope_error(
            rationale=reason or "tool_calls validation failed.",
            tool_calls_input=tool_calls if isinstance(tool_calls, list) else [],
            parallel=parallel,
            fail_strategy=fail_strategy,
            max_concurrent=max_concurrent,
        )
    if fail_strategy not in _FAIL_STRATEGIES:
        return _envelope_error(
            rationale=f"fail_strategy must be one of {_FAIL_STRATEGIES}; got {fail_strategy!r}.",
            tool_calls_input=tool_calls,
            parallel=parallel,
            fail_strategy=fail_strategy,
            max_concurrent=max_concurrent,
        )
    if not isinstance(max_concurrent, int) or max_concurrent < 1:
        return _envelope_error(
            rationale="max_concurrent must be a positive int.",
            tool_calls_input=tool_calls,
            parallel=parallel,
            fail_strategy=fail_strategy,
            max_concurrent=max_concurrent,
        )
    if max_concurrent > _MAX_CONCURRENT_HARD_CAP:
        max_concurrent = _MAX_CONCURRENT_HARD_CAP

    # Drive the async orchestrator from a sync MCP tool entry point.
    # FastMCP supports async tools natively, but exposing a sync
    # signature here keeps the existing telemetry wrapper happy and
    # matches the rest of moat_lane_tools/* surface.
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop is not None and loop.is_running():
        # We are already in an event loop (rare for FastMCP tool path
        # under stdio, but the contract guarantees us correctness if
        # FastMCP later switches to async-dispatch). Use ``run_until``
        # via a private thread to avoid nested-loop errors.
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            future = ex.submit(
                asyncio.run,
                _orchestrate_async(
                    tool_calls=parsed,
                    parallel=parallel,
                    fail_strategy=fail_strategy,
                    max_concurrent=max_concurrent,
                ),
            )
            results, total_ms = future.result()
    else:
        results, total_ms = asyncio.run(
            _orchestrate_async(
                tool_calls=parsed,
                parallel=parallel,
                fail_strategy=fail_strategy,
                max_concurrent=max_concurrent,
            )
        )

    ok = sum(1 for r in results if r["status"] == "ok")
    errored = sum(1 for r in results if r["status"] == "error")
    rejected = sum(1 for r in results if r["status"] == "rejected")
    skipped = sum(1 for r in results if r["status"] == "skipped")

    # Billing: each dispatched call (ok + error) counts as a ¥3 unit.
    # Rejected (unknown tool / private) and skipped (short-circuited)
    # do not bill — they never reached the underlying tool.
    billable = ok + errored
    network_saved = max(len(parsed) - 1, 0)
    bundle_note = (
        f"1 round trip vs {len(parsed)} = ~{int(100 * network_saved / max(len(parsed), 1))}% "
        "agent ↔ server network saving (¥ price unchanged: ¥3 per dispatched call)."
    )

    return {
        "tool_name": _TOOL_NAME,
        "schema_version": _SCHEMA_VERSION,
        "primary_result": {
            "status": "ok",
            "lane_id": _LANE_ID,
            "upstream_module": _UPSTREAM_MODULE,
            "primary_input": {
                "tool_calls_count": len(parsed),
                "parallel": parallel,
                "fail_strategy": fail_strategy,
                "max_concurrent": max_concurrent,
            },
        },
        "results": results,
        "summary": {
            "total_calls": len(parsed),
            "ok": ok,
            "error": errored,
            "rejected": rejected,
            "skipped": skipped,
            "total_latency_ms": total_ms,
        },
        "billing": {
            "unit": billable,
            "yen": billable * 3,
            "_bundle_discount": bundle_note,
        },
        "_disclaimer": DISCLAIMER,
        "_provenance": {
            "source_module": _UPSTREAM_MODULE,
            "lane_id": _LANE_ID,
            "wrap_kind": "moat_lane_he4_orchestrate",
            "observed_at": today_iso_utc(),
            "registered_tool_count": len(_list_allowed_tools()),
        },
    }
