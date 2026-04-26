"""Canonical REST error envelope (δ2, group δ).

Background
----------
Pre-launch audit (J5) found five distinct error envelope shapes
emitted across the REST surface:

1. FastAPI default ``{"detail": "..."}``
2. Anon-rate-limit flat body ``{"detail", "limit", "resets_at", ...}``
3. Custom 500 handler ``{"detail": "internal server error",
   "request_id": "..."}``
4. Pydantic validation ``{"detail": [{"loc", "msg", ...}],
   "detail_summary_ja": "..."}``
5. Cap-reached body ``{"detail", "cap_reached": true, ...}``

Customer agents that pattern-match on ``response.json()["error"]``
silently break across half of these shapes; ones that pattern-match
on ``response.json()["detail"]`` catch some, miss others, and have to
parse free-form prose for a code.

This module promotes the MCP tool envelope's ``make_error`` semantics
to the REST layer so every 4xx / 5xx that we *control* emits one
shape:

    {
      "error": {
        "code": "<closed-enum>",
        "user_message": "<plain-Japanese, ≤200 chars>",
        "user_message_en": "<English, optional>",
        "request_id": "<echoed or 'unset'>",
        "documentation": "https://autonomath.ai/docs/...",
        ... (per-code extras: retry_after, retry_with, field_errors)
      }
    }

Differences from ``mcp/autonomath_tools/error_envelope.py``
-----------------------------------------------------------
The MCP envelope adds ``{total, limit, offset, results}`` so tool
consumers can treat error and success shape uniformly.  The REST
envelope omits those because HTTP 4xx/5xx responses don't have a
result list at the protocol level — clients differentiate by status
code first and ``error.code`` second. Keeping the REST shape strictly
``{"error": {...}}`` avoids confusing partial-result situations.

Codes
-----
The closed enum lives in :data:`ERROR_CODES`. Adding a new code
requires updating the Japanese / English copy and the documentation
anchor.  Customer-facing reference: ``docs/error_handling.md``.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

_log = logging.getLogger("jpintel.error_envelope")

#: Public documentation anchor base. Each code uses
#: ``f"{DOC_URL}#{code}"`` to point at its specific section.
DOC_URL = "https://autonomath.ai/docs/error_handling"

#: Closed-enum mapping of error codes to default user copy + severity.
#: The ``user_message`` field is shown verbatim to end users / agent
#: callers when the call site does not override it.  Keep ≤200 chars
#: and keep the language plain (no ASCII-art tables, no stack traces).
ERROR_CODES: dict[str, dict[str, str]] = {
    # --- Client errors ---------------------------------------------
    "unknown_query_parameter": {
        "severity": "hard",
        "user_message_ja": (
            "未定義のクエリパラメータが含まれています。許可されているパラメータのみを指定してください。"
        ),
        "user_message_en": (
            "Unknown query parameter(s). Use only declared parameters."
        ),
    },
    "invalid_enum": {
        "severity": "hard",
        "user_message_ja": (
            "入力検証に失敗しました。各フィールドのエラー内容を確認してください。"
        ),
        "user_message_en": "Input validation failed. See field_errors for details.",
    },
    "auth_required": {
        "severity": "hard",
        "user_message_ja": (
            "API キーが必要です。https://autonomath.ai/dashboard で取得してください。"
        ),
        "user_message_en": (
            "API key required. Obtain one at https://autonomath.ai/dashboard."
        ),
    },
    "auth_invalid": {
        "severity": "hard",
        "user_message_ja": (
            "API キーが無効または失効しています。ダッシュボードで再発行してください。"
        ),
        "user_message_en": (
            "API key is invalid or revoked. Re-issue from the dashboard."
        ),
    },
    "rate_limit_exceeded": {
        "severity": "hard",
        "user_message_ja": (
            "レート制限を超過しました。Retry-After ヘッダの秒数だけ待ってから再試行してください。"
        ),
        "user_message_en": (
            "Rate limit exceeded. Retry after the seconds indicated by Retry-After."
        ),
    },
    "route_not_found": {
        "severity": "hard",
        "user_message_ja": (
            "そのパスは存在しません。/v1/openapi.json で利用可能なエンドポイントを確認してください。"
        ),
        "user_message_en": (
            "Route not found. See /v1/openapi.json for the catalogue of available endpoints."
        ),
    },
    "method_not_allowed": {
        "severity": "hard",
        "user_message_ja": (
            "そのパスでは指定された HTTP メソッドは許可されていません。Allow ヘッダを参照してください。"
        ),
        "user_message_en": (
            "HTTP method not allowed on this path. Check the Allow response header."
        ),
    },
    # --- Server errors ---------------------------------------------
    "internal_error": {
        "severity": "hard",
        "user_message_ja": (
            "内部エラーが発生しました。同じリクエストを数秒後に再試行してください。"
            "解決しない場合は request_id を添えて support に連絡してください。"
        ),
        "user_message_en": (
            "Internal error. Retry in a few seconds; "
            "if it persists, contact support with the request_id."
        ),
    },
    "service_unavailable": {
        "severity": "soft",
        "user_message_ja": (
            "サービスが一時的に利用できません。Retry-After ヘッダの秒数だけ待ってから再試行してください。"
        ),
        "user_message_en": (
            "Service temporarily unavailable. "
            "Retry after the seconds indicated by Retry-After."
        ),
    },
    # --- Customer-cap (P3-W) ---------------------------------------
    "cap_reached": {
        "severity": "hard",
        "user_message_ja": (
            "今月の利用上限に達しました。ダッシュボードで上限を変更するか、来月までお待ちください。"
        ),
        "user_message_en": (
            "Monthly cap reached. Increase the cap in the dashboard or wait until reset."
        ),
    },
}


def make_error(
    code: str,
    user_message: str | None = None,
    *,
    user_message_en: str | None = None,
    request_id: str | None = None,
    **extras: Any,
) -> dict[str, Any]:
    """Build the canonical REST error envelope.

    Parameters
    ----------
    code
        Closed-enum identifier (see :data:`ERROR_CODES`). An unknown
        code is coerced to ``"internal_error"`` defensively.
    user_message
        Plain-Japanese, end-user-readable message. Falls back to the
        default copy in :data:`ERROR_CODES` when ``None``.
    user_message_en
        English mirror, optional. Falls back to default English copy.
    request_id
        Echoed under ``error.request_id``. ``None`` becomes the literal
        string ``"unset"`` (NEVER ``"unknown"`` — that string was the
        J5 bug we are explicitly fixing). Test/middleware layers should
        pass ``request.state.request_id`` or the inbound
        ``x-request-id`` header.
    **extras
        Arbitrary per-code fields merged into ``error``: e.g.
        ``retry_after=30`` for 503, ``field_errors=[...]`` for 422,
        ``unknown=[...]`` + ``expected=[...]`` for unknown_query_parameter,
        ``suggested_paths=[...]`` for route_not_found.

    Returns
    -------
    dict
        ``{"error": {...}}`` — directly serialisable as the JSON body
        of a 4xx / 5xx response.
    """
    if code not in ERROR_CODES:
        _log.warning("make_error called with unknown code=%s; coercing", code)
        code = "internal_error"

    spec = ERROR_CODES[code]
    err: dict[str, Any] = {
        "code": code,
        "user_message": (user_message or spec["user_message_ja"]).strip(),
        "user_message_en": (
            (user_message_en or spec.get("user_message_en") or "").strip()
            or None
        ),
        "request_id": request_id or "unset",
        "severity": spec.get("severity", "hard"),
        "documentation": f"{DOC_URL}#{code}",
    }
    # Drop None values so the wire shape is compact.
    if err.get("user_message_en") is None:
        err.pop("user_message_en", None)

    # Merge per-call extras last so callers can override defaults if
    # needed (rarely used; mostly just additive).
    for k, v in extras.items():
        if v is None:
            continue
        err[k] = v

    return {"error": err}


def safe_request_id(request) -> str:
    """Pull a stable request id off a Starlette request.

    Order of preference:
      1. ``request.state.request_id`` (set by ``_RequestContextMiddleware``).
      2. ``x-request-id`` header (caller-supplied).
      3. The literal ``"unset"`` (NEVER ``"unknown"``).

    Used by the global exception handlers in ``api.main`` so they
    don't have to repeat the same fallback chain.
    """
    try:
        rid = getattr(request.state, "request_id", None)
        if rid:
            return str(rid)
    except Exception:  # pragma: no cover — defensive
        pass
    hdr = None
    try:
        hdr = request.headers.get("x-request-id")
    except Exception:  # pragma: no cover — defensive
        pass
    return hdr or "unset"


def is_strict_query_disabled() -> bool:
    """Mirror of ``strict_query.ENV_DISABLE`` for handlers that need to
    know whether the gate is on (currently only used by tests). Lives
    here so the error layer doesn't import the middleware.
    """
    return os.getenv("JPINTEL_STRICT_QUERY_DISABLED", "").strip() == "1"


# ---------------------------------------------------------------------------
# Pydantic models for OpenAPI components.schemas
# ---------------------------------------------------------------------------
#
# These mirror the wire shape produced by ``make_error`` so
# ``responses={4xx/5xx: {"model": ErrorEnvelope}}`` on every route generates a
# rich ErrorEnvelope schema reference instead of an empty / opaque blob in
# OpenAPI. Pre-launch audit (a901f6696316d1d11) flagged 0% example coverage on
# response bodies AND that the error shape was not declared as a Pydantic
# model referenced from ``components.schemas``; this fix closes both gaps.
#
# We keep the closed-enum `code` field as a Literal of every code we emit
# today (the 11 canonical codes from ``ERROR_CODES`` plus the closely-related
# audit-name aliases the task brief enumerates). ``model_config = extra=
# "allow"`` means per-code extras (retry_after, suggested_paths, field_errors)
# are tolerated without breaking the closed-enum contract on `code`.
# ---------------------------------------------------------------------------


# Closed enum exactly mirroring the task brief; covers both the runtime
# ERROR_CODES keys above AND the audit-spec canonical codes that the data
# layer / tools emit (missing_required_arg, invalid_date_format, …). These
# are the *only* values an agent should ever see in `error.code` on a 4xx /
# 5xx response.
ErrorCode = Literal[
    # --- Audit-spec canonical codes (used by tools / data layer) -----------
    "missing_required_arg",
    "invalid_enum",
    "invalid_date_format",
    "out_of_range",
    "no_matching_records",
    "ambiguous_query",
    "seed_not_found",
    "db_locked",
    "db_unavailable",
    "subsystem_unavailable",
    "internal",
    # --- REST-layer envelope codes (used by api.main exception handlers) ---
    "unknown_query_parameter",
    "auth_required",
    "auth_invalid",
    "rate_limit_exceeded",
    "route_not_found",
    "method_not_allowed",
    "internal_error",
    "service_unavailable",
    "cap_reached",
]


class ErrorBody(BaseModel):
    """Body of the canonical error envelope.

    Required fields are ``code`` + ``message``. ``request_id`` is always
    present in production (``make_error`` defaults to the literal ``"unset"``
    when no request id can be resolved) but is marked optional here so SDK
    generators emit a nullable type.

    Extras (``retry_after``, ``suggested_paths``, ``field_errors``,
    ``severity``, ``documentation``, ``user_message_en``) are tolerated via
    ``extra="allow"`` so the OpenAPI schema can stay a stable minimum
    contract without needing to enumerate per-code keys.
    """

    model_config = ConfigDict(
        extra="allow",
        json_schema_extra={
            "examples": [
                {
                    "code": "no_matching_records",
                    "message": "No rows matched the supplied filters.",
                    "request_id": "a3f12c7b9e8d4501",
                    "details": {
                        "queried": {"prefecture": "宮城県", "tier": ["S"]},
                        "hint": "Try removing prefecture or expanding tier to ['S','A','B'].",
                    },
                }
            ]
        },
    )

    code: ErrorCode = Field(
        ...,
        description=(
            "Closed-enum machine-readable error code. Agents should branch on "
            "this rather than parsing `message`."
        ),
    )
    message: str = Field(
        ...,
        description=(
            "Plain-Japanese end-user-readable message. ≤200 chars. "
            "Mirrored in `user_message` extra for legacy clients that read that key."
        ),
    )
    details: Optional[dict[str, Any]] = Field(
        default=None,
        description=(
            "Per-code extras: e.g. `retry_after` seconds for 503, "
            "`field_errors` for 422, `suggested_paths` for 404."
        ),
    )
    request_id: Optional[str] = Field(
        default=None,
        description=(
            "Echoed `x-request-id`. Always populated server-side; literal "
            "`'unset'` is used when no upstream id can be resolved."
        ),
    )


class ErrorEnvelope(BaseModel):
    """Top-level wrapper. The JSON body of every 4xx / 5xx is `{ "error": {...} }`.

    Note: legacy 5xx bodies also include a back-compat `detail` field at the
    top level alongside `error`; that is documented separately on the route
    docs and is intentionally omitted from the strict schema so callers
    migrate to reading `error.code`.
    """

    model_config = ConfigDict(
        extra="allow",
        json_schema_extra={
            "examples": [
                {
                    "error": {
                        "code": "rate_limit_exceeded",
                        "message": (
                            "レート制限を超過しました。"
                            "Retry-After ヘッダの秒数だけ待ってから再試行してください。"
                        ),
                        "request_id": "a3f12c7b9e8d4501",
                        "details": {"retry_after": 30},
                    }
                }
            ]
        },
    )

    error: ErrorBody = Field(..., description="Error body — see ErrorBody.")


# ---------------------------------------------------------------------------
# Shared `responses=` map for every route decorator.
# ---------------------------------------------------------------------------
#
# Use as ``responses={**COMMON_ERROR_RESPONSES, 200: {...}}`` on each route.
# Hoisted out so adding a new shared status or tweaking copy is one edit.
# ---------------------------------------------------------------------------


COMMON_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    400: {
        "model": ErrorEnvelope,
        "description": "Validation error — `code` ∈ {invalid_enum, invalid_date_format, missing_required_arg, out_of_range, ambiguous_query}.",
    },
    401: {
        "model": ErrorEnvelope,
        "description": "Authentication required — `code='auth_required'`. Send `X-API-Key`.",
    },
    404: {
        "model": ErrorEnvelope,
        "description": "Not found — `code` ∈ {no_matching_records, seed_not_found, route_not_found}.",
    },
    422: {
        "model": ErrorEnvelope,
        "description": "Unprocessable entity — Pydantic validation failure (`code='invalid_enum'`).",
    },
    429: {
        "model": ErrorEnvelope,
        "description": "Rate limit — `code='rate_limit_exceeded'`. Honour `Retry-After`.",
    },
    500: {
        "model": ErrorEnvelope,
        "description": "Internal error — `code` ∈ {internal, internal_error, db_locked, db_unavailable}.",
    },
    503: {
        "model": ErrorEnvelope,
        "description": "Subsystem unavailable — `code` ∈ {subsystem_unavailable, service_unavailable, cap_reached}.",
    },
}


__all__ = [
    "DOC_URL",
    "ERROR_CODES",
    "make_error",
    "safe_request_id",
    "is_strict_query_disabled",
    "ErrorCode",
    "ErrorBody",
    "ErrorEnvelope",
    "COMMON_ERROR_RESPONSES",
]
