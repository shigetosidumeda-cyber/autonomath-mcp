"""
/v1/batch handler.

Design:
- Up to 50 sub-requests in one POST, executed concurrently via asyncio.gather
- Each sub-request gets its own 10s timeout, isolated failure
- Tool whitelist enforced at envelope level (unknown_tool = 400 batch, or per-item error)
- Size cap 256 KB (measured on JSON-serialised body)
- Recursion forbidden: batch_execute cannot appear inside a batch
- Billing: 1 JPY per succeeded sub-request
- Anonymous tier: one batch call consumes 50 quota regardless, partial
  success still charged per succeeded item. If quota runs out mid-batch
  we return partial responses for already-completed items.

This module deliberately imports NO anthropic SDK / claude CLI.
Handlers are pure in-process async; LLM reasoning happens client-side.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, FrozenSet, List, Optional, Set, Tuple

# -----------------------------------------------------------------------------
# Constants / whitelist
# -----------------------------------------------------------------------------

MAX_ITEMS = 50
MAX_BODY_BYTES = 256 * 1024  # 256 KB hard cap on serialised request
PER_ITEM_TIMEOUT_S = 10.0
ANON_BATCH_COST = 50  # anon tier: one batch call = 50 quota units

FORBIDDEN_TOOLS = frozenset({"batch_execute"})  # recursion guard

TOOL_WHITELIST = frozenset({
    "search_programs",
    "get_tax_rule",
    "check_enforcement",
    "get_program",
    "get_deadline",
    "list_authorities",
    "peer_compare",
    "resolve_entity",
})


# -----------------------------------------------------------------------------
# Envelope v2 helpers
# -----------------------------------------------------------------------------

def _ok(result: dict, elapsed_ms: int, rid: str) -> dict:
    return {
        "id": rid,
        "status": "ok",
        "result": result,
        "error": None,
        "elapsed_ms": elapsed_ms,
    }


def _err(rid: str, code: str, msg: str, elapsed_ms: int = 0, hint: str | None = None) -> dict:
    env = {"code": code, "message": msg}
    if hint:
        env["hint"] = hint
    return {
        "id": rid,
        "status": "error",
        "result": None,
        "error": env,
        "elapsed_ms": elapsed_ms,
    }


# -----------------------------------------------------------------------------
# Tool dispatcher
# -----------------------------------------------------------------------------

ToolHandler = Callable[[dict], Awaitable[dict]]


class ToolRegistry:
    """In-process tool dispatcher. Real impl wires each tool to its service."""

    def __init__(self) -> None:
        self._handlers: dict[str, ToolHandler] = {}

    def register(self, name: str, handler: ToolHandler) -> None:
        if name in FORBIDDEN_TOOLS:
            raise ValueError(f"tool name {name!r} reserved (recursion guard)")
        if name not in TOOL_WHITELIST:
            raise ValueError(f"tool name {name!r} not in whitelist")
        self._handlers[name] = handler

    def has(self, name: str) -> bool:
        return name in self._handlers

    async def invoke(self, name: str, params: dict) -> dict:
        return await self._handlers[name](params)


# -----------------------------------------------------------------------------
# Quota / billing stub (real impl backs onto quota store)
# -----------------------------------------------------------------------------

@dataclass
class QuotaState:
    tier: str                  # "anon" | "paid"
    remaining: int | None      # anon: int, paid: None (infinite on this path)

    def can_consume(self, cost: int) -> bool:
        if self.tier == "paid":
            return True
        return (self.remaining or 0) >= cost

    def consume(self, cost: int) -> None:
        if self.tier == "anon" and self.remaining is not None:
            self.remaining = max(0, self.remaining - cost)


# -----------------------------------------------------------------------------
# Validation
# -----------------------------------------------------------------------------

class BatchValidationError(Exception):
    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def _body_bytes(body: dict) -> int:
    return len(json.dumps(body, ensure_ascii=False).encode("utf-8"))


def validate_envelope(body: Any) -> list[dict]:
    """
    Returns the validated list of sub-requests.
    Raises BatchValidationError on envelope-level failures.
    Per-item tool validation is deferred to execution so one bad item
    doesn't poison the whole batch.
    """
    if not isinstance(body, dict):
        raise BatchValidationError("validation_failed", "body must be an object")

    # size cap (envelope-level, short-circuits huge payload)
    if _body_bytes(body) > MAX_BODY_BYTES:
        raise BatchValidationError(
            "size_cap_exceeded",
            f"request body exceeds {MAX_BODY_BYTES} bytes",
            status=413,
        )

    reqs = body.get("requests")
    if not isinstance(reqs, list) or not reqs:
        raise BatchValidationError("validation_failed", "requests[] required, non-empty")

    if len(reqs) > MAX_ITEMS:
        raise BatchValidationError(
            "validation_failed",
            f"max {MAX_ITEMS} sub-requests per batch, got {len(reqs)}",
        )

    seen_ids: set[str] = set()
    for i, item in enumerate(reqs):
        if not isinstance(item, dict):
            raise BatchValidationError("validation_failed", f"requests[{i}] must be object")
        rid = item.get("id")
        tool = item.get("tool")
        params = item.get("params")
        if not isinstance(rid, str) or not rid:
            raise BatchValidationError("validation_failed", f"requests[{i}].id required")
        if rid in seen_ids:
            raise BatchValidationError("validation_failed", f"duplicate id {rid!r}")
        seen_ids.add(rid)
        if not isinstance(tool, str) or not tool:
            raise BatchValidationError("validation_failed", f"requests[{i}].tool required")
        if tool in FORBIDDEN_TOOLS:
            raise BatchValidationError(
                "recursion_forbidden",
                f"tool {tool!r} cannot appear inside a batch",
            )
        if not isinstance(params, dict):
            raise BatchValidationError("validation_failed", f"requests[{i}].params must be object")

    return reqs


# -----------------------------------------------------------------------------
# Per-item execution
# -----------------------------------------------------------------------------

async def _execute_one(registry: ToolRegistry, item: dict) -> dict:
    rid = item["id"]
    tool = item["tool"]
    params = item["params"]
    t0 = time.monotonic()

    if not registry.has(tool):
        return _err(rid, "unknown_tool", f"tool {tool!r} not registered",
                    hint=f"whitelist={sorted(TOOL_WHITELIST)}")

    try:
        result = await asyncio.wait_for(
            registry.invoke(tool, params),
            timeout=PER_ITEM_TIMEOUT_S,
        )
    except asyncio.TimeoutError:
        elapsed = int((time.monotonic() - t0) * 1000)
        return _err(rid, "timeout",
                    f"sub-request exceeded {PER_ITEM_TIMEOUT_S}s",
                    elapsed_ms=elapsed)
    except Exception as e:
        elapsed = int((time.monotonic() - t0) * 1000)
        return _err(rid, "internal_error", f"{type(e).__name__}: {e}",
                    elapsed_ms=elapsed)

    elapsed = int((time.monotonic() - t0) * 1000)
    if not isinstance(result, dict):
        return _err(rid, "internal_error",
                    f"tool {tool!r} returned non-dict {type(result).__name__}",
                    elapsed_ms=elapsed)
    return _ok(result, elapsed, rid)


# -----------------------------------------------------------------------------
# Main handler
# -----------------------------------------------------------------------------

async def handle_batch(
    body: Any,
    registry: ToolRegistry,
    quota: QuotaState,
) -> tuple[int, dict]:
    """
    Returns (http_status, response_body).
    response_body follows BatchResponse schema (OpenAPI).
    """
    # 1. Envelope validation
    try:
        items = validate_envelope(body)
    except BatchValidationError as e:
        return e.status, {
            "total": 0,
            "succeeded": 0,
            "billed": 0,
            "quota_remaining": quota.remaining,
            "responses": [],
            "error": {"code": e.code, "message": e.message},
        }

    # 2. Anon quota gate (up-front, but partial success still charged).
    #    If quota can't even cover one item, return 402-semantic error envelope.
    if quota.tier == "anon":
        if (quota.remaining or 0) <= 0:
            return 402, {
                "total": len(items),
                "succeeded": 0,
                "billed": 0,
                "quota_remaining": 0,
                "responses": [],
                "error": {"code": "quota_exhausted",
                          "message": "anonymous tier exhausted"},
            }

    # 3. Execute concurrently. asyncio.gather isolates exceptions per task
    #    because each _execute_one catches internally.
    tasks = [_execute_one(registry, it) for it in items]
    responses = await asyncio.gather(*tasks)

    # 4. Billing + quota consume.
    #    Anon tier: batch consumes 50 "api quota units" regardless of content,
    #    and succeeded items are billed at 1 JPY each.
    succeeded = sum(1 for r in responses if r["status"] == "ok")
    billed_jpy = succeeded

    if quota.tier == "anon":
        # consume up to 50 units, but don't go negative
        cost = min(ANON_BATCH_COST, quota.remaining or 0)
        quota.consume(cost)
        # If anon quota was insufficient for a full 50 batch, items still
        # completed in-process; we already ran them. Mark overflow items
        # as skipped? No — spec says "partial success, bill completed".
        # We already did all items; no retroactive skip needed here.

    return 200, {
        "total": len(items),
        "succeeded": succeeded,
        "billed": billed_jpy,
        "quota_remaining": quota.remaining,
        "responses": responses,
    }
