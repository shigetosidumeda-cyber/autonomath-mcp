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
        "request_id": "<always a real 16-hex token; minted when missing>",
        "documentation": "https://jpcite.com/docs/...",
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
import re
import secrets
import time
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

_log = logging.getLogger("jpintel.error_envelope")

# Mirror of ``api.main._REQUEST_ID_RE`` so we can validate caller-supplied
# header values without importing ``api.main`` (which would create a cycle —
# the middleware imports back from this module). Inbound ids must match the
# same charset/length window as the ones we mint locally so log search can
# treat the field uniformly. ULID Crockford base32 (26 chars, [0-9A-HJKMNP-TV-Z])
# falls inside this window.
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9-]{8,64}$")

# Crockford base32 alphabet (no I, L, O, U). 32 chars, used by ULID.
_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def _mint_request_id() -> str:
    """Generate a fresh ULID-style request id.

    Returns a 26-character Crockford-base32 ULID (e.g.
    ``01KQ3XQ77RR7J8XWZ8C0YR2JN2``) — 48 bits of millisecond timestamp
    followed by 80 bits of cryptographic randomness. Lexicographic order
    matches creation time, which makes log search by id range trivially
    sortable. Implemented inline so we avoid the ``ulid-py`` /
    ``python-ulid`` dependency (J5 fix, no new wheels for the runtime
    image).

    The shape fits ``_REQUEST_ID_RE`` (``[A-Za-z0-9-]{8,64}``) so caller-
    supplied ids and locally-minted ids share one validation regex
    throughout the stack. Falls back to ``secrets.token_hex(16)`` only
    if the ULID encode somehow raises — this branch is unreachable in
    normal Python and exists for absolute defense in depth.
    """
    try:
        # 48-bit millisecond timestamp + 80 bits of randomness = 128 bits.
        ts_ms = int(time.time() * 1000) & ((1 << 48) - 1)
        rand_bits = secrets.randbits(80)
        # Pack into one 128-bit integer, then encode as 26 base32 chars
        # (5 bits per char × 26 = 130 bits; ULID drops the top 2 bits to
        # land at 128, which Crockford encoding expresses as 26 chars).
        n = (ts_ms << 80) | rand_bits
        out = []
        for _ in range(26):
            out.append(_CROCKFORD[n & 0x1F])
            n >>= 5
        return "".join(reversed(out))
    except Exception:  # pragma: no cover — defensive
        return secrets.token_hex(16)

#: Public documentation anchor base. Each code uses
#: ``f"{DOC_URL}#{code}"`` to point at its specific section.
DOC_URL = "https://jpcite.com/docs/error_handling"

#: Closed-enum mapping of error codes to default user copy + severity.
#: The ``user_message`` field is shown verbatim to end users / agent
#: callers when the call site does not override it.  Keep ≤200 chars
#: and keep the language plain (no ASCII-art tables, no stack traces).
#:
#: All 20 docs/error_handling.md codes are present so make_error() never
#: silently coerces a doc-listed code to "internal_error" when a caller
#: forgets to pass an override message.
ERROR_CODES: dict[str, dict[str, str]] = {
    # --- Input validation (4xx) ------------------------------------
    "missing_required_arg": {
        "severity": "hard",
        "user_message_ja": (
            "必須パラメータが欠落しています。field_errors の loc 配列で欠落フィールドを確認し、付与して再送してください。"
        ),
        "user_message_en": (
            "Required parameter is missing. See field_errors[].loc for the missing field path, then resubmit with it set."
        ),
    },
    "invalid_enum": {
        "severity": "hard",
        "user_message_ja": (
            "値が許可一覧にありません。field_errors[].expected の許可値から選び直して再送してください。"
        ),
        "user_message_en": (
            "Value is not in the allowed list. Choose a value from field_errors[].expected and resubmit."
        ),
    },
    "invalid_date_format": {
        "severity": "hard",
        "user_message_ja": (
            "日付形式が不正です。ISO 8601 (YYYY-MM-DD、例: 2026-04-26) で指定してください。"
        ),
        "user_message_en": (
            "Invalid date format. Use ISO 8601 (YYYY-MM-DD, e.g. 2026-04-26)."
        ),
    },
    "out_of_range": {
        "severity": "hard",
        "user_message_ja": (
            "値が範囲外です。field/min/max を確認し、min ≤ 値 ≤ max の範囲で再送してください。"
        ),
        "user_message_en": (
            "Value out of range. See field/min/max and resubmit with min ≤ value ≤ max."
        ),
    },
    "unknown_query_parameter": {
        "severity": "hard",
        "user_message_ja": (
            "未定義のクエリパラメータが含まれています。expected 配列の許可値のみを指定して再送してください。"
        ),
        "user_message_en": (
            "Unknown query parameter(s). Resubmit using only the names listed in expected[]."
        ),
    },
    # --- Data lookup (4xx) -----------------------------------------
    "no_matching_records": {
        "severity": "soft",
        "user_message_ja": (
            "該当データが 0 件です。条件を緩めるか (broaden_query)、別表記を試してください (try_alias)。"
        ),
        "user_message_en": (
            "No matching records. Try broaden_query (loosen filters) or try_alias (alternate spellings)."
        ),
    },
    "ambiguous_query": {
        "severity": "soft",
        "user_message_ja": (
            "クエリが複数の record に等しく一致しました。都道府県・業種・法人番号などの絞り込みを追加して再送してください。"
        ),
        "user_message_en": (
            "Query matched multiple records equally. Add a disambiguator (prefecture, industry, corporate number) and retry."
        ),
    },
    "seed_not_found": {
        "severity": "soft",
        "user_message_ja": (
            "指定 seed_id が DB にありません。search_programs などで正規化された ID を取得してから再送してください。"
        ),
        "user_message_en": (
            "seed_id not found. Resolve a canonical id via search_programs first, then retry."
        ),
    },
    # --- Auth + quota (4xx) ----------------------------------------
    "auth_required": {
        "severity": "hard",
        "user_message_ja": (
            "API キーが必要です。https://jpcite.com/dashboard で発行し、X-API-Key ヘッダで送信してください。"
        ),
        "user_message_en": (
            "API key required. Issue one at https://jpcite.com/dashboard and send it via the X-API-Key header."
        ),
    },
    "auth_invalid": {
        "severity": "hard",
        "user_message_ja": (
            "API キーが無効か失効しています。ダッシュボードの me/rotate-key で再発行してください。"
        ),
        "user_message_en": (
            "API key is invalid or revoked. Re-issue via me/rotate-key on the dashboard."
        ),
    },
    "rate_limit_exceeded": {
        "severity": "hard",
        "user_message_ja": (
            "レート制限を超過しました。Retry-After ヘッダの秒数だけ待ってから再試行してください。匿名利用枠の場合は X-API-Key を発行すると解除されます。"
        ),
        "user_message_en": (
            "Rate limit exceeded. Wait the seconds shown in the Retry-After header before retrying. Anonymous callers can lift the limit by issuing an X-API-Key."
        ),
    },
    "cap_reached": {
        "severity": "hard",
        "user_message_ja": (
            "月次利用上限 (顧客設定) に達しました。me/cap で上限を引き上げるか、JST 月初 00:00 のリセットをお待ちください。"
        ),
        "user_message_en": (
            "Monthly metered cap reached. Raise the cap via me/cap or wait for the reset at 00:00 JST on the 1st."
        ),
    },
    # --- Routing (4xx) ---------------------------------------------
    "route_not_found": {
        "severity": "hard",
        "user_message_ja": (
            "指定パスは存在しません。https://api.jpcite.com/v1/openapi.json で有効なパス一覧を確認してください。"
        ),
        "user_message_en": (
            "Route not found. List valid paths at https://api.jpcite.com/v1/openapi.json."
        ),
    },
    "method_not_allowed": {
        "severity": "hard",
        "user_message_ja": (
            "このパスでは指定 HTTP メソッドは使えません。Allow レスポンスヘッダで許可されているメソッドを確認してください。"
        ),
        "user_message_en": (
            "HTTP method not allowed on this path. Check the Allow response header for accepted methods."
        ),
    },
    # --- Database / infrastructure (5xx) ---------------------------
    "db_locked": {
        "severity": "soft",
        "user_message_ja": (
            "DB が一時的にロック中です。Retry-After ヘッダの秒数 (通常 5-30 秒) だけ待って再試行してください。"
        ),
        "user_message_en": (
            "Database is temporarily locked. Retry after the seconds shown in Retry-After (typically 5-30s)."
        ),
    },
    "db_unavailable": {
        "severity": "hard",
        "user_message_ja": (
            "DB が利用不可です (ファイル不在 / mount 失敗)。Retry-After 秒 (既定 300s) 待って再試行してください。継続する場合は request_id を添えて info@bookyou.net まで連絡してください。"
        ),
        "user_message_en": (
            "Database unavailable (file missing / mount failure). Retry after Retry-After seconds (default 300s). If it persists, email info@bookyou.net with the request_id."
        ),
    },
    "subsystem_unavailable": {
        "severity": "hard",
        "user_message_ja": (
            "補助サブシステムが起動していません。同じリクエストを 1-2 分後に再試行してください。継続する場合は request_id を添えて info@bookyou.net まで連絡してください。"
        ),
        "user_message_en": (
            "Subsystem prerequisite is unavailable. Retry the same request in 1-2 minutes. If it persists, email info@bookyou.net with the request_id."
        ),
    },
    "service_unavailable": {
        "severity": "soft",
        "user_message_ja": (
            "サービスが一時的に利用できません。Retry-After ヘッダの秒数だけ待ってから再試行してください。"
        ),
        "user_message_en": (
            "Service temporarily unavailable. Retry after the seconds indicated by Retry-After."
        ),
    },
    # --- Bug / abnormal (5xx) --------------------------------------
    "internal": {
        "severity": "hard",
        "user_message_ja": (
            "内部エラーが発生しました。数秒後に同じリクエストを再試行してください。継続する場合は error.request_id を添えて info@bookyou.net まで連絡してください。"
        ),
        "user_message_en": (
            "Internal error. Retry the same request in a few seconds. If it persists, email info@bookyou.net with error.request_id."
        ),
    },
    "internal_error": {
        "severity": "hard",
        "user_message_ja": (
            "内部エラーが発生しました。数秒後に同じリクエストを再試行してください。継続する場合は error.request_id を添えて info@bookyou.net まで連絡してください。"
        ),
        "user_message_en": (
            "Internal error. Retry the same request in a few seconds. If it persists, email info@bookyou.net with error.request_id."
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
        Echoed under ``error.request_id``. ``None`` falls back to a
        freshly-minted ``secrets.token_hex(8)`` value so the wire shape
        always carries a usable correlation id. Pre-fix this fell back
        to the literal ``"unset"`` (and earlier the literal ``"unknown"``
        — J5), which gave callers no actionable handle. Production
        handlers MUST still pass ``safe_request_id(request)`` so the
        envelope id matches the response ``x-request-id`` header and
        the structured log lines for the same request.
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
        # Defensive fallback: callers SHOULD pass ``safe_request_id(request)``,
        # but a unit-test or programmatic consumer can still call
        # ``make_error`` with no request context. Mint a real id rather than
        # leaking the literal ``"unset"`` (the bug this commit fixes).
        "request_id": request_id or _mint_request_id(),
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
      2. ``x-request-id`` header (caller-supplied) — only when it matches
         ``_REQUEST_ID_RE`` so a malicious caller cannot inject SQL, log-
         injection sequences, or absurdly long strings into our logs.
      3. A freshly-minted ``secrets.token_hex(8)`` value, ALSO stamped onto
         ``request.state.request_id`` so subsequent calls on the same
         request return the SAME id (envelope, response header,
         downstream log lines all match).

    The pre-fix fallback was the literal string ``"unset"`` (J5 / current
    bug): every 422 emitted from ``StrictQueryMiddleware`` (which runs
    OUTSIDE ``_RequestContextMiddleware`` in the LIFO middleware stack)
    surfaced ``error.request_id == "unset"`` even though log lines for
    that same request carried a real id. Customer agents pattern-matching
    on the envelope had no actionable correlation handle.  We now mint
    here so the contract holds even on the short-circuit paths.
    """
    # 1. Re-use whatever the context middleware (or a prior ``safe_request_id``
    #    call within the same request) already stamped.
    try:
        rid = getattr(request.state, "request_id", None)
        if rid and rid != "unset":
            return str(rid)
    except Exception:  # pragma: no cover — defensive
        pass

    # 2. Trust a caller-supplied ``x-request-id`` header only when it
    #    passes the same regex the context middleware enforces. Anything
    #    else is treated as missing and triggers a fresh mint below.
    hdr: str | None = None
    try:
        hdr = request.headers.get("x-request-id")
    except Exception:  # pragma: no cover — defensive
        hdr = None
    if hdr and _REQUEST_ID_RE.fullmatch(hdr):
        rid_val = hdr
    else:
        # 3. Mint. ``secrets.token_hex(8)`` mirrors the context-middleware
        #    fallback so log search treats both id streams uniformly.
        rid_val = _mint_request_id()

    # Stamp onto request.state so anyone else who calls safe_request_id on
    # the same request gets the SAME id. Without this, the strict-query 422
    # body and the response ``x-request-id`` header could disagree (each
    # call site would mint independently), breaking the correlation
    # contract just as surely as the literal "unset" did.
    try:
        request.state.request_id = rid_val
    except Exception:  # pragma: no cover — defensive
        pass
    return rid_val


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
    present in production (``make_error`` defaults to a freshly-minted
    ``secrets.token_hex(8)`` value when no upstream id can be resolved)
    but is marked optional here so SDK generators emit a nullable type.

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
            "Echoed `x-request-id`. Always populated server-side with a "
            "real 16-char hex token; freshly minted when no upstream id "
            "can be resolved (never the literal `'unset'`)."
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
