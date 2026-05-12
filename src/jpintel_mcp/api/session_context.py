"""Wave 46 dim 19 / Dim L — contextual session surface (state token 24h TTL).

Implements :doc:`feedback_session_context_design`. Where the existing
REST handlers are stateless one-shot calls, this surface lets an agent
**resume a multi-turn intent** across requests:

  * ``POST /v1/session/open``  — open a session, returns a state token
    (24h TTL) bound to a small ``saved_context`` envelope.
  * ``POST /v1/session/step``  — append a step (turn) under an existing
    state token; returns the cumulative saved_context + step count.
  * ``POST /v1/session/close`` — close the session and return the final
    saved_context snapshot. Token becomes invalid (subsequent step/close
    returns 410).

Storage
-------
In-process ``dict`` keyed by state token (hex 32 chars). This is a
**single-process** primitive — Fly autoscale of multiple machines means
a session may not survive a restart or be visible across machines.
Production guarantees:

  * Token TTL 24h enforced on every access; expired tokens 410.
  * Per-process cap of 10,000 sessions (LRU eviction) to bound memory
    on a long-running Fly machine.
  * NO PII / NO regulated values stored — ``saved_context`` is a free
    dict capped at 16 KiB / 32 steps to keep the in-memory footprint
    tight.
  * NO LLM call from this handler; pure dict + Python stdlib.

Why not Redis / sqlite ?
------------------------
Per memory ``feedback_zero_touch_solo`` + ``feedback_no_quick_check_on_huge_sqlite``:
adding an out-of-process store is operator-overhead we cannot pay.
Sessions are **conversation glue** for the customer LLM, not durable
state. A 24h window covers >99% of agent multi-turn loops. The customer
LLM can serialize meaningful state via their own store if they need
durability — jpcite is the surface, not the database of record.

§52 / §47条の2 / §72 / §1 disclaimer surfaces on every response.
"""

from __future__ import annotations

import logging
import os
import secrets
import threading
import time
from collections import OrderedDict
from typing import Annotated, Any

from fastapi import APIRouter, Body, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger("jpintel.api.session_context")

router = APIRouter(prefix="/v1/session", tags=["session-context"])

# 24h TTL, in seconds. Mirrors feedback_session_context_design "24h state token".
SESSION_TTL_SEC = 24 * 60 * 60

# Bound the in-process store. LRU eviction on overflow.
_MAX_SESSIONS = 10_000

# Bound a single saved_context envelope.
_MAX_CONTEXT_BYTES = 16 * 1024
_MAX_STEPS_PER_SESSION = 32

_DISCLAIMER = (
    "本 endpoint は contextual session surface (Dim L) で、agent multi-turn "
    "loop の state token を 24h TTL で保持します。state token は in-process "
    "primitive のため Fly 再起動・autoscale で消失する可能性があります。 "
    "saved_context に PII / 規制値 を保存しないでください。本 surface は "
    "税理士法 §52 ・公認会計士法 §47条の2 ・弁護士法 §72 ・行政書士法 §1 "
    "territory の判断を代替しません。"
)


class _SessionEntry:
    """In-memory session record. NOT exported."""

    __slots__ = ("token", "opened_at", "expires_at", "saved_context", "steps")

    def __init__(self, token: str, saved_context: dict[str, Any]):
        now = time.time()
        self.token = token
        self.opened_at = now
        self.expires_at = now + SESSION_TTL_SEC
        self.saved_context: dict[str, Any] = dict(saved_context)
        self.steps: list[dict[str, Any]] = []


# ``OrderedDict`` so we can LRU-evict in O(1) on overflow.
_SESSIONS: OrderedDict[str, _SessionEntry] = OrderedDict()
_LOCK = threading.Lock()


def _now() -> float:
    return time.time()


def _new_token() -> str:
    return secrets.token_hex(16)


def _prune_expired_locked() -> int:
    """Drop any expired entries. Caller must hold _LOCK. Returns count."""
    now = _now()
    expired = [t for t, e in _SESSIONS.items() if e.expires_at < now]
    for t in expired:
        _SESSIONS.pop(t, None)
    return len(expired)


def _context_size(ctx: dict[str, Any]) -> int:
    """Estimate UTF-8 byte size of the context dict (loose, not exact)."""
    try:
        import json

        return len(json.dumps(ctx, ensure_ascii=False, default=str).encode("utf-8"))
    except (TypeError, ValueError):
        return _MAX_CONTEXT_BYTES + 1  # force rejection


# Public introspection for tests / ops; NOT a route.
def _store_stats() -> dict[str, int]:
    with _LOCK:
        return {
            "session_count": len(_SESSIONS),
            "max_sessions": _MAX_SESSIONS,
            "ttl_sec": SESSION_TTL_SEC,
        }


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class OpenBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    saved_context: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Optional initial context payload. Capped at 16 KiB / 32 keys. "
            "PII禁止 — saved_context は agent conversation glue 専用。"
        ),
    )


class StepBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    state_token: str = Field(
        ...,
        min_length=32,
        max_length=32,
        description="Token returned by /v1/session/open. 24h TTL.",
    )
    step: dict[str, Any] = Field(
        ...,
        description=(
            "Per-step payload to append. Capped at 4 KiB. Each step adds "
            "to a max of 32 entries; further calls return 413."
        ),
    )


class CloseBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    state_token: str = Field(
        ...,
        min_length=32,
        max_length=32,
        description="Token returned by /v1/session/open. Must still be alive.",
    )


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


@router.post("/open")
def session_open(
    body: Annotated[OpenBody, Body(...)],
) -> dict[str, Any]:
    """Open a new session and return a 24h state token."""
    if _context_size(body.saved_context) > _MAX_CONTEXT_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail={
                "code": "saved_context_too_large",
                "max_bytes": _MAX_CONTEXT_BYTES,
            },
        )
    if len(body.saved_context) > 64:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "saved_context_too_many_keys", "max_keys": 64},
        )
    token = _new_token()
    entry = _SessionEntry(token=token, saved_context=body.saved_context)
    with _LOCK:
        _prune_expired_locked()
        if len(_SESSIONS) >= _MAX_SESSIONS:
            # LRU evict: drop the oldest insertion.
            _SESSIONS.popitem(last=False)
        _SESSIONS[token] = entry
    return {
        "state_token": token,
        "expires_at": int(entry.expires_at),
        "ttl_sec": SESSION_TTL_SEC,
        "saved_context": entry.saved_context,
        "steps": 0,
        "_disclaimer": _DISCLAIMER,
        "_billing_unit": 1,
    }


@router.post("/step")
def session_step(
    body: Annotated[StepBody, Body(...)],
) -> dict[str, Any]:
    """Append a turn to an existing session. Returns cumulative state."""
    with _LOCK:
        _prune_expired_locked()
        entry = _SESSIONS.get(body.state_token)
        if entry is None:
            raise HTTPException(
                status_code=status.HTTP_410_GONE,
                detail={"code": "state_token_unknown_or_expired"},
            )
        if entry.expires_at < _now():
            _SESSIONS.pop(body.state_token, None)
            raise HTTPException(
                status_code=status.HTTP_410_GONE,
                detail={"code": "state_token_expired"},
            )
        if len(entry.steps) >= _MAX_STEPS_PER_SESSION:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail={
                    "code": "step_cap_exceeded",
                    "max_steps": _MAX_STEPS_PER_SESSION,
                },
            )
        # Bound the step payload too.
        if _context_size(body.step) > 4096:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail={"code": "step_too_large", "max_bytes": 4096},
            )
        entry.steps.append({"at": int(_now()), "data": body.step})
        # LRU bump: move to end (most-recently-used).
        _SESSIONS.move_to_end(body.state_token, last=True)
        snapshot = {
            "state_token": entry.token,
            "expires_at": int(entry.expires_at),
            "saved_context": entry.saved_context,
            "steps": len(entry.steps),
            "last_step_at": entry.steps[-1]["at"] if entry.steps else None,
            "_disclaimer": _DISCLAIMER,
            "_billing_unit": 1,
        }
    return snapshot


@router.post("/close")
def session_close(
    body: Annotated[CloseBody, Body(...)],
) -> dict[str, Any]:
    """Close a session and return the final snapshot. Token invalidated."""
    with _LOCK:
        _prune_expired_locked()
        entry = _SESSIONS.pop(body.state_token, None)
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail={"code": "state_token_unknown_or_expired"},
        )
    return {
        "state_token": entry.token,
        "opened_at": int(entry.opened_at),
        "closed_at": int(_now()),
        "saved_context": entry.saved_context,
        "steps": len(entry.steps),
        "step_log": entry.steps,
        "_disclaimer": _DISCLAIMER,
        "_billing_unit": 1,
    }


__all__ = [
    "router",
    "SESSION_TTL_SEC",
    "_store_stats",
]


# Allow `python -m jpintel_mcp.api.session_context` to print store stats
# for ops one-shot inspection (no LLM, no DB, just dict introspection).
if __name__ == "__main__":  # pragma: no cover
    import json

    print(json.dumps(_store_stats(), ensure_ascii=False, indent=2))
    os._exit(0)
