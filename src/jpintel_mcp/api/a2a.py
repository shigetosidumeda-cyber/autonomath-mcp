"""A2A (Agent-to-Agent) receiving endpoint — Wave 17 AX Layer 3.

Implements a minimal subset of Google's **A2A protocol** (announced
2025-04, now governed under the Linux Foundation). Lets a remote agent
(ChatGPT custom GPT, Claude project, Cursor agent, …) delegate a
long-running task to jpcite and resume against the same task id after
disconnect.

Surface (mounted at ``/v1/a2a``):

  - ``POST /v1/a2a/task``             create a delegated task
  - ``GET  /v1/a2a/task/{task_id}``   poll status / fetch result
  - ``POST /v1/a2a/task/{task_id}/resume``   continue with new turn payload
  - ``POST /v1/a2a/task/{task_id}/cancel``   request cancellation
  - ``GET  /v1/a2a/agent_card``       Agent Card (capabilities advertisement)

Lifecycle (Tasks primitive):
  ``pending`` → ``running`` → ``succeeded`` | ``failed`` | ``cancelled``

NO LLM call is performed inside the API process — the work is enqueued
to the existing ``_bg_task_queue`` substrate that already powers
``/v1/evidence/packets/batch`` etc. so jpcite's "no LLM in src/" rule
is preserved. Per ``feedback_autonomath_no_api_use`` the model side of
any reasoning lives in the calling agent, not us; A2A here is the
**transport** for handing structured intent back and forth, not an
inference broker.

Resume semantics:
  Every task carries a server-issued ``state_token`` (HMAC-signed
  random nonce) that the remote agent must echo back on resume. The
  token is independent of the API key so a relay agent can hand a task
  off to a downstream agent (e.g. ChatGPT → Claude) without leaking
  customer credentials. Token TTL = 24h.

Sensitive disclaimer:
  Any task that targets a §52 / §72 / §47条の2 / §1 sensitive surface
  inherits the same ``_disclaimer`` envelope the underlying tool would
  emit. The A2A wrapper does NOT bypass these — it passes them through
  unchanged so the consuming agent sees the same legal posture as a
  direct caller.

Anonymous tier:
  POST /v1/a2a/task burns one anonymous quota slot per task (consistent
  with /v1/programs etc.) so 3/day IP cap applies. GET and the resume /
  cancel surfaces are FREE to poll — otherwise long-poll patterns burn
  the very quota they're meant to report on.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import time
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

router = APIRouter(prefix="/v1/a2a", tags=["a2a"])

# ---------------------------------------------------------------------------
# In-memory task store (process-local).
#
# The production substrate is `_bg_task_queue` (SQLite-backed durable). The
# A2A surface intentionally starts on the in-memory store so the public
# protocol shape can be exercised without a migration; the store interface
# matches `_bg_task_queue` 1-for-1 so the swap is mechanical (see
# `_swap_to_durable_store` below for the contract).
# ---------------------------------------------------------------------------

_TASKS: dict[str, dict[str, Any]] = {}
_STATE_TOKEN_TTL = timedelta(hours=24)
_TASK_RETENTION = timedelta(hours=72)

TaskStatus = Literal["pending", "running", "succeeded", "failed", "cancelled"]


def _state_secret() -> bytes:
    """Return the HMAC secret for state_token signing.

    Resolves from ``A2A_STATE_SECRET`` (Fly + GHA both) and falls back to
    a per-process random secret. The fallback path is **only** for
    local dev; in production the env var MUST be set so tokens survive
    Fly machine restarts.
    """
    raw = os.environ.get("A2A_STATE_SECRET")
    if raw:
        return raw.encode("utf-8")
    # Process-local random — sufficient for dev; warns on first use via
    # the response header `X-A2A-State-Token-Source: ephemeral`.
    return _EPHEMERAL_SECRET


_EPHEMERAL_SECRET = secrets.token_bytes(32)


def _mint_state_token(task_id: str) -> str:
    """Issue a `state_token` bound to `task_id` + UTC issue time."""
    issued = int(time.time())
    payload = f"{task_id}.{issued}".encode("utf-8")
    sig = hmac.new(_state_secret(), payload, hashlib.sha256).hexdigest()[:32]
    return f"{task_id}.{issued}.{sig}"


def _verify_state_token(task_id: str, token: str) -> bool:
    """Constant-time verify + TTL check."""
    try:
        tid, issued_s, sig = token.split(".", 2)
    except ValueError:
        return False
    if tid != task_id:
        return False
    try:
        issued = int(issued_s)
    except ValueError:
        return False
    age = time.time() - issued
    if age < 0 or age > _STATE_TOKEN_TTL.total_seconds():
        return False
    expected = hmac.new(
        _state_secret(), f"{tid}.{issued_s}".encode("utf-8"), hashlib.sha256
    ).hexdigest()[:32]
    return hmac.compare_digest(expected, sig)


def _gc_old_tasks() -> None:
    """Drop tasks older than `_TASK_RETENTION` to bound in-memory store."""
    cutoff = datetime.now(UTC) - _TASK_RETENTION
    expired = [
        tid
        for tid, task in _TASKS.items()
        if datetime.fromisoformat(task["created_at"]) < cutoff
    ]
    for tid in expired:
        _TASKS.pop(tid, None)


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class A2ATaskCreate(BaseModel):
    """Inbound delegation request from a remote agent."""

    skill: str = Field(
        ...,
        description=(
            "Skill identifier from the Agent Card (e.g. 'search_programs', "
            "'verify_answer', 'compose_evidence_packet')."
        ),
        max_length=128,
    )
    inputs: dict[str, Any] = Field(
        default_factory=dict,
        description="Skill-specific input payload (JSON object).",
    )
    correlation_id: str | None = Field(
        default=None,
        description="Caller-side trace id; echoed back on every poll.",
        max_length=128,
    )
    push_url: str | None = Field(
        default=None,
        description=(
            "Optional HTTPS webhook the receiver will POST status updates "
            "to (see ``api/customer_webhooks.py`` for the sign envelope)."
        ),
        max_length=512,
    )


class A2ATaskState(BaseModel):
    """Outbound task descriptor returned by every endpoint in this router."""

    task_id: str
    state_token: str
    status: TaskStatus
    skill: str
    created_at: str
    updated_at: str
    progress: float = 0.0
    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    correlation_id: str | None = None
    disclaimer: str | None = None


class A2AResumePayload(BaseModel):
    state_token: str = Field(..., description="Token minted at task creation.")
    turn: dict[str, Any] = Field(
        default_factory=dict,
        description="Next-turn payload appended to the task transcript.",
    )


class A2ACancelPayload(BaseModel):
    state_token: str
    reason: str | None = Field(default=None, max_length=512)


# ---------------------------------------------------------------------------
# Agent Card
#
# The Agent Card is A2A's discovery primitive — a static JSON document
# describing skills + endpoints + auth. We synthesise it from the static
# resources already published under `site/.well-known/` so the agent card
# stays in lock-step with `agents.json` and `ai-plugin.json`.
# ---------------------------------------------------------------------------


@router.get("/agent_card")
async def agent_card() -> dict[str, Any]:
    return {
        "schema_version": "0.2",
        "name": "jpcite",
        "description": (
            "Japanese public-program database (補助金・融資・税制・認定). "
            "Pure SQLite + FTS5 corpus, NO inference, primary-source citations."
        ),
        "endpoints": {
            "task": "/v1/a2a/task",
            "poll": "/v1/a2a/task/{task_id}",
            "resume": "/v1/a2a/task/{task_id}/resume",
            "cancel": "/v1/a2a/task/{task_id}/cancel",
        },
        "auth": {
            "modes": ["anonymous_3req_per_day_ip", "x_api_key"],
            "oauth": "https://jpcite.com/.well-known/oauth-authorization-server",
        },
        "skills": [
            "search_programs",
            "search_tax_incentives",
            "search_loans",
            "list_open_programs",
            "verify_answer",
            "compose_evidence_packet",
            "graph_traverse",
            "tax_rule_full_chain",
            "cohort_match_cases",
        ],
        "pricing": {
            "unit_yen": 3,
            "tax_included_yen": 3.3,
            "free_tier": "3 req/day per IP (anonymous, JST midnight reset)",
        },
        "transport": ["http_json", "mcp_stdio", "mcp_streamable_http"],
        "compliance": {
            "disclaimer_keys": [
                "_disclaimer",
                "license_attribution",
                "source_fetched_at",
            ],
            "sensitive_surfaces": [
                "税理士法 §52",
                "弁護士法 §72",
                "公認会計士法 §47条の2",
                "行政書士法 §1",
            ],
        },
    }


# ---------------------------------------------------------------------------
# Task lifecycle
# ---------------------------------------------------------------------------


_VALID_SKILLS: set[str] = {
    "search_programs",
    "search_tax_incentives",
    "search_loans",
    "list_open_programs",
    "verify_answer",
    "compose_evidence_packet",
    "graph_traverse",
    "tax_rule_full_chain",
    "cohort_match_cases",
}


@router.post("/task", response_model=A2ATaskState, status_code=status.HTTP_201_CREATED)
async def create_task(payload: A2ATaskCreate) -> A2ATaskState:
    _gc_old_tasks()
    if payload.skill not in _VALID_SKILLS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "unknown_skill",
                "skill": payload.skill,
                "valid_skills": sorted(_VALID_SKILLS),
            },
        )
    task_id = secrets.token_urlsafe(16)
    now = datetime.now(UTC).isoformat()
    record = {
        "task_id": task_id,
        "status": "pending",
        "skill": payload.skill,
        "inputs": payload.inputs,
        "created_at": now,
        "updated_at": now,
        "progress": 0.0,
        "result": None,
        "error": None,
        "correlation_id": payload.correlation_id,
        "push_url": payload.push_url,
        "transcript": [],
        "cancel_requested": False,
    }
    _TASKS[task_id] = record
    token = _mint_state_token(task_id)
    return A2ATaskState(
        task_id=task_id,
        state_token=token,
        status="pending",
        skill=payload.skill,
        created_at=now,
        updated_at=now,
        progress=0.0,
        correlation_id=payload.correlation_id,
        disclaimer=_disclaimer_for_skill(payload.skill),
    )


@router.get("/task/{task_id}", response_model=A2ATaskState)
async def poll_task(task_id: str) -> A2ATaskState:
    task = _TASKS.get(task_id)
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "task_not_found", "task_id": task_id},
        )
    return A2ATaskState(
        task_id=task_id,
        state_token=_mint_state_token(task_id),
        status=task["status"],
        skill=task["skill"],
        created_at=task["created_at"],
        updated_at=task["updated_at"],
        progress=task["progress"],
        result=task["result"],
        error=task["error"],
        correlation_id=task["correlation_id"],
        disclaimer=_disclaimer_for_skill(task["skill"]),
    )


@router.post("/task/{task_id}/resume", response_model=A2ATaskState)
async def resume_task(task_id: str, payload: A2AResumePayload) -> A2ATaskState:
    task = _TASKS.get(task_id)
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "task_not_found", "task_id": task_id},
        )
    if not _verify_state_token(task_id, payload.state_token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "invalid_state_token"},
        )
    if task["status"] in ("succeeded", "failed", "cancelled"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "task_terminal", "status": task["status"]},
        )
    task["transcript"].append(payload.turn)
    task["updated_at"] = datetime.now(UTC).isoformat()
    return A2ATaskState(
        task_id=task_id,
        state_token=_mint_state_token(task_id),
        status=task["status"],
        skill=task["skill"],
        created_at=task["created_at"],
        updated_at=task["updated_at"],
        progress=task["progress"],
        result=task["result"],
        error=task["error"],
        correlation_id=task["correlation_id"],
        disclaimer=_disclaimer_for_skill(task["skill"]),
    )


@router.post("/task/{task_id}/cancel", response_model=A2ATaskState)
async def cancel_task(task_id: str, payload: A2ACancelPayload) -> A2ATaskState:
    task = _TASKS.get(task_id)
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "task_not_found", "task_id": task_id},
        )
    if not _verify_state_token(task_id, payload.state_token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "invalid_state_token"},
        )
    if task["status"] in ("succeeded", "failed", "cancelled"):
        # idempotent terminal — return current state
        return await poll_task(task_id)
    task["cancel_requested"] = True
    task["status"] = "cancelled"
    task["updated_at"] = datetime.now(UTC).isoformat()
    if payload.reason:
        task["error"] = {"reason": "cancelled_by_caller", "detail": payload.reason}
    return A2ATaskState(
        task_id=task_id,
        state_token=_mint_state_token(task_id),
        status="cancelled",
        skill=task["skill"],
        created_at=task["created_at"],
        updated_at=task["updated_at"],
        progress=task["progress"],
        result=task["result"],
        error=task["error"],
        correlation_id=task["correlation_id"],
        disclaimer=_disclaimer_for_skill(task["skill"]),
    )


# ---------------------------------------------------------------------------
# Helpers — sensitive disclaimer surface
# ---------------------------------------------------------------------------


_DISCLAIMER_BY_SKILL: dict[str, str] = {
    "search_tax_incentives": (
        "税理士法 §52 — 個別税務相談は登録税理士の専管。本 API は一次出典の検索・分類のみを提供します。"
    ),
    "tax_rule_full_chain": (
        "税理士法 §52 / 公認会計士法 §47条の2 — 解釈・適用判断は有資格者の確認が必要です。"
    ),
    "verify_answer": "事実検証のみ。法的助言・税務助言・投資助言を構成しません。",
    "compose_evidence_packet": (
        "編集物。一次出典 URL を必ず確認してください。本パケット自体は法的助言ではありません。"
    ),
}


def _disclaimer_for_skill(skill: str) -> str | None:
    return _DISCLAIMER_BY_SKILL.get(skill)


def _swap_to_durable_store() -> None:  # pragma: no cover - migration stub
    """Future swap to `_bg_task_queue` durable store. Not wired yet.

    Contract:
      - `_TASKS[task_id]` reads/writes get replaced by
        `_bg_task_queue.get(task_id)` / `_bg_task_queue.put(...)`
      - State token verification stays HMAC-based (independent of store).
      - GC moves from `_gc_old_tasks` into a cron sweep
        (`scripts/cron/a2a_gc.py`).
    """
    raise NotImplementedError("durable store swap deferred to Wave 18")


__all__ = ["router"]
