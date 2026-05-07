"""Canonical response + error envelope (§28.2 Agent Contract, 2026-04-30).

Source-of-truth for the v2 wire shape that customer agents (Cursor / Cline /
Continue / Claude Desktop / Zapier / Make / RPA) pattern-match against.
Adoption is opt-in for the compatibility period so legacy consumers (`results: [...]`
vs `data: [...]` vs raw arrays) keep working untouched. Routes opt in via:

    Accept: application/vnd.jpcite.v2+json  # explicit media type for SDKs

Pre-existing prior art:

* `api/_error_envelope.py`  — REST 4xx/5xx unification post-J5 (`make_error`,
  `ERROR_CODES`, `safe_request_id`, `ErrorEnvelope`). The new envelope reuses
  those legacy codes through `LEGACY_ERROR_CODE_TO_CANONICAL` rather than
  introducing a parallel namespace.
* `mcp/autonomath_tools/envelope_wrapper.py` — autonomath-side envelope merge.
  The new envelope is **shape-compatible** with that one for the overlapping
  fields (`status`, `query_echo`, `suggested_actions`, `meta`).

The spec (`docs/_internal/value_maximization_plan_no_llm_api.md` §28.2):

    {
      "status": "rich | sparse | empty | partial | error",
      "query_echo": {"normalized_input": {}, "applied_filters": {}, "unparsed_terms": []},
      "results": [],
      "citations": [],
      "warnings": [],
      "suggested_actions": [],
      "meta": {"request_id", "api_version", "latency_ms", "billable_units", "client_tag"}
    }

    {
      "error": {
        "code", "user_message", "developer_message",
        "retryable", "retry_after", "documentation"
      },
      "request_id"
    }

Pure Pydantic v2. Never imports anthropic / openai / google.generativeai
(launch CI guard `tests/test_no_llm_in_production.py`). Never raises on
untyped input — helpers coerce or short-circuit, mirroring `make_error`.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Constants (single source of truth for status + code enums).
# ---------------------------------------------------------------------------

#: API version stamped onto every v2 envelope. Bump when the wire shape
#: gains a backwards-incompatible change. Reflected in `Accept` header
#: media type (`application/vnd.jpcite.v2+json` ↔ `api_version="v2"`).
ENVELOPE_API_VERSION: str = "v2"

#: 5-state status enum. Spec: rich | sparse | empty | partial | error.
#: - rich:    response carries N≥THRESHOLD results, no apology needed
#: - sparse:  response carries 1..N-1 results, agent should consider broaden
#: - empty:   zero results — `empty_reason` + `retry_with` MUST be set
#: - partial: results returned but a sub-source failed; `warnings[]` set
#: - error:   no results, `error` envelope present, `results=[]`
StatusType = Literal["rich", "sparse", "empty", "partial", "error"]

#: 9 canonical error codes per §28.2. Mapped to legacy
#: `_error_envelope.ERROR_CODES` via `LEGACY_ERROR_CODE_TO_CANONICAL` so
#: existing routes can graduate without code-rename churn.
ErrorCode = Literal[
    "RATE_LIMITED",
    "UNAUTHORIZED",
    "FORBIDDEN",
    "NOT_FOUND",
    "VALIDATION_ERROR",
    "LICENSE_GATE_BLOCKED",
    "QUOTA_EXCEEDED",
    "INTEGRITY_ERROR",
    "INTERNAL_ERROR",
]

#: Mapping from the legacy lowercase code namespace
#: (`api/_error_envelope.py:ERROR_CODES`) to the spec's UPPER_SNAKE codes.
#: The legacy codes are still emitted on the legacy shape; the v2 envelope
#: surfaces the canonical code only.
LEGACY_ERROR_CODE_TO_CANONICAL: dict[str, ErrorCode] = {
    # rate limiting / quota
    "rate_limit_exceeded": "RATE_LIMITED",
    "cap_reached": "QUOTA_EXCEEDED",
    # auth
    "auth_required": "UNAUTHORIZED",
    "auth_invalid": "UNAUTHORIZED",
    # routing / not found
    "route_not_found": "NOT_FOUND",
    "no_matching_records": "NOT_FOUND",
    "seed_not_found": "NOT_FOUND",
    "method_not_allowed": "VALIDATION_ERROR",
    # validation
    "missing_required_arg": "VALIDATION_ERROR",
    "invalid_enum": "VALIDATION_ERROR",
    "invalid_date_format": "VALIDATION_ERROR",
    "out_of_range": "VALIDATION_ERROR",
    "unknown_query_parameter": "VALIDATION_ERROR",
    "ambiguous_query": "VALIDATION_ERROR",
    # infra
    "db_locked": "INTERNAL_ERROR",
    "db_unavailable": "INTERNAL_ERROR",
    "subsystem_unavailable": "INTERNAL_ERROR",
    "service_unavailable": "INTERNAL_ERROR",
    "internal": "INTERNAL_ERROR",
    "internal_error": "INTERNAL_ERROR",
}

#: Documentation anchor base. Per-code anchor: `f"{DOC_URL}#{code.lower()}"`.
DOC_URL: str = "https://jpcite.com/docs/api-reference/response_envelope"

#: Default plain-Japanese user copy per canonical code. Mirrors
#: `api/_error_envelope.py:ERROR_CODES` user_message_ja for the analogous
#: legacy code so the migration is copy-stable.
_DEFAULT_USER_MESSAGE: dict[ErrorCode, str] = {
    "RATE_LIMITED": (
        "レート制限を超過しました。Retry-After ヘッダの秒数だけ待ってから再試行してください。"
    ),
    "UNAUTHORIZED": (
        "API キーが必要、または無効です。https://jpcite.com/dashboard で発行・再発行してください。"
    ),
    "FORBIDDEN": (
        "このリソースには現在のキーではアクセスできません。料金プランまたは権限を確認してください。"
    ),
    "NOT_FOUND": ("該当データが見つかりませんでした。条件を緩めるか、別表記を試してください。"),
    "VALIDATION_ERROR": (
        "リクエストパラメータが不正です。details を確認し、許可値で再送してください。"
    ),
    "LICENSE_GATE_BLOCKED": (
        "ライセンス上、現在のキーには返却できないデータです。?license= で再配布可能 license を絞ってください。"
    ),
    "QUOTA_EXCEEDED": (
        "月次利用上限に達しました。me/cap で上限を引き上げるか、JST 月初 00:00 のリセットをお待ちください。"
    ),
    "INTEGRITY_ERROR": (
        "データ整合性エラーを検出しました。同じリクエストを数秒後に再試行してください。"
    ),
    "INTERNAL_ERROR": (
        "内部エラーが発生しました。数秒後に同じリクエストを再試行してください。継続する場合は request_id を添えて info@bookyou.net まで連絡してください。"
    ),
}

#: English mirror of `_DEFAULT_USER_MESSAGE` for the 9 canonical codes.
#: Strings are NOT new prose — every entry reuses the existing English copy
#: from `api/_error_envelope.py:ERROR_CODES.user_message_en` (mapped via
#: `LEGACY_ERROR_CODE_TO_CANONICAL`) or the structural docstring text on the
#: corresponding StandardError.<class_method> below. This keeps the en/ja
#: parity invariant (every code has both languages) without introducing any
#: machine-translated content. The R8 i18n audit (2026-05-07) flagged the
#: `_DEFAULT_USER_MESSAGE_EN` gap as the highest-impact trivial fix in the
#: error envelope path.
_DEFAULT_USER_MESSAGE_EN: dict[ErrorCode, str] = {
    "RATE_LIMITED": (
        "Rate limit exceeded. Wait the seconds shown in the Retry-After header before retrying. "
        "Anonymous callers can lift the limit by issuing an X-API-Key."
    ),
    "UNAUTHORIZED": (
        "API key required or invalid. Issue/re-issue one at https://jpcite.com/dashboard and "
        "send it via the X-API-Key header."
    ),
    "FORBIDDEN": (
        "Action not permitted with the current API key. Check the subscription plan or key scope."
    ),
    "NOT_FOUND": (
        "No matching records. Try broaden_query (loosen filters) or try_alias (alternate spellings)."
    ),
    "VALIDATION_ERROR": (
        "Bad request — body, signature, or required header is malformed. "
        "See `detail` for the specific cause and `documentation` for recovery steps."
    ),
    "LICENSE_GATE_BLOCKED": (
        "Source domain carries a non-redistributable license; drop the row or rerun with "
        "?license=proprietary explicit."
    ),
    "QUOTA_EXCEEDED": (
        "Monthly metered cap reached. Raise the cap via me/cap or wait for the reset at "
        "00:00 JST on the 1st."
    ),
    "INTEGRITY_ERROR": (
        "Data integrity check failed. Retry the same request in a few seconds."
    ),
    "INTERNAL_ERROR": (
        "Internal error. Retry the same request in a few seconds. If it persists, email "
        "info@bookyou.net with error.request_id."
    ),
}

#: Default `retryable` flag per code — agents branch on this to decide
#: whether to back off and retry vs. hard-fail.
_DEFAULT_RETRYABLE: dict[ErrorCode, bool] = {
    "RATE_LIMITED": True,
    "UNAUTHORIZED": False,
    "FORBIDDEN": False,
    "NOT_FOUND": False,
    "VALIDATION_ERROR": False,
    "LICENSE_GATE_BLOCKED": False,
    "QUOTA_EXCEEDED": False,
    "INTEGRITY_ERROR": True,
    "INTERNAL_ERROR": True,
}

#: Sparse-vs-rich threshold — anything ≥ this is "rich", below is "sparse".
#: Tuned for search endpoints today (programs.search returns up to 100 rows;
#: 5 is the median useful agent-facing result count).
_RICH_THRESHOLD: int = 5


# ---------------------------------------------------------------------------
# Pydantic models.
# ---------------------------------------------------------------------------


class QueryEcho(BaseModel):
    """Echo of the caller's input as the server understood it.

    `normalized_input` shows post-NFKC / post-trim values (so the agent
    can confirm `q="株式会社 ABC"` is the same string we ran the FTS on).
    `applied_filters` captures the structured filters that survived
    validation (caller-supplied tier=['Z'] would be dropped here, not
    silently).
    `unparsed_terms` lists tokens we couldn't route into the index — e.g.
    a free-text query that mixed industry + prefecture but only
    industry resolved.
    """

    model_config = ConfigDict(extra="allow")

    normalized_input: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Caller's input after server-side normalization (NFKC, trim, "
            "alias expansion). Empty when the route accepts no input."
        ),
    )
    applied_filters: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Structured filters the server applied. Differs from "
            "normalized_input when validation dropped invalid values."
        ),
    )
    unparsed_terms: list[str] = Field(
        default_factory=list,
        description=(
            "Tokens we could not route into a structured filter — e.g. "
            "free-text query fragments that did not match any alias."
        ),
    )


class Citation(BaseModel):
    """A single primary-source citation. Mirrors §28.2 citation table.

    Empty/None fields are tolerated — different surfaces fill different
    subsets (e.g. search results carry source_url + publisher; provenance
    queries also carry checksum + verification_status).
    """

    model_config = ConfigDict(extra="allow")

    source_id: str | None = Field(
        default=None, description="Join key into am_source / source-of-truth tables."
    )
    source_url: str | None = Field(default=None, description="Direct URL to the primary source.")
    publisher: str | None = Field(
        default=None, description="Issuing body (METI, NTA, prefecture, etc)."
    )
    title: str | None = Field(default=None, description="Document title.")
    fetched_at: str | None = Field(default=None, description="ISO-8601 fetch timestamp.")
    checksum: str | None = Field(default=None, description="sha256 hex of the fetched body.")
    license: str | None = Field(
        default=None,
        description="License (pdl_v1.0 / cc_by_4.0 / gov_standard_v2.0 / public_domain / proprietary / unknown).",
    )
    field_paths: list[str] | None = Field(
        default=None,
        description="JSON pointer paths into `results[]` that this citation justifies.",
    )
    excerpt: str | None = Field(default=None, description="Short verbatim excerpt for spot-check.")
    page_ref: str | None = Field(
        default=None, description="Page / section reference within the source."
    )
    verification_status: Literal["verified", "inferred", "stale", "unknown"] | None = Field(
        default=None, description="Operator verification state of this citation."
    )
    citation_text_ja: str | None = Field(
        default=None, description="One-line Japanese citation suitable for Slack / 稟議書."
    )
    citation_markdown: str | None = Field(
        default=None, description="Markdown citation suitable for docs / report bodies."
    )


def default_user_message_for(code: ErrorCode, request: Any = None) -> str:
    """Pick the language-resolved default user_message copy for a code.

    Reads ``request.state.lang`` (set by ``LanguageResolverMiddleware``)
    when ``request`` is supplied. Falls back to Japanese for any of:

      * No ``request`` argument (legacy / unit-test call sites).
      * ``request.state.lang`` missing or unrecognised.
      * Catalog gap (the en mirror is hand-curated; if a future code
        lands ja-only, callers transparently degrade to ja rather than
        emitting the bare error code as text).

    Used by the ``StandardError.<class_method>`` constructors to pick
    between :data:`_DEFAULT_USER_MESSAGE` and :data:`_DEFAULT_USER_MESSAGE_EN`
    based on the caller's resolved language. Public so tests can assert
    the resolution table directly.
    """
    lang = "ja"
    if request is not None:
        try:
            stamped = getattr(request.state, "lang", None)
            if stamped in ("ja", "en"):
                lang = str(stamped)
        except Exception:  # pragma: no cover — defensive
            lang = "ja"
    if lang == "en":
        en_copy = _DEFAULT_USER_MESSAGE_EN.get(code)
        if en_copy:
            return en_copy
    return _DEFAULT_USER_MESSAGE[code]


class ResponseMeta(BaseModel):
    """Per-response metadata. `request_id` is always populated server-side.

    `billable_units` is the ¥3/req multiplier — a search returning 100
    rows still bills 1 unit, but a bulk evaluator can stamp 5 here when
    the call did 5 logical operations. Agents that pre-budget should
    read this rather than assume every call = 1 unit.
    """

    model_config = ConfigDict(extra="allow")

    request_id: str = Field(
        ..., description="Echoed `x-request-id`. ULID-style 26-char or hex 16-char."
    )
    api_version: str = Field(
        default=ENVELOPE_API_VERSION, description="Envelope schema version (currently `v2`)."
    )
    latency_ms: int = Field(default=0, ge=0, description="Server-measured wall time, milliseconds.")
    billable_units: int = Field(
        default=1,
        ge=0,
        description="Units charged for this call. Anonymous tier deducts from the 3/日 IP quota.",
    )
    client_tag: str | None = Field(
        default=None,
        description="Echoed `X-Client-Tag` for 顧問先 attribution (税理士 fan-out cohort).",
    )


class StandardError(BaseModel):
    """Canonical error envelope per §28.2.

    Wire shape:

        {
          "error": {
            "code": "RATE_LIMITED",
            "user_message": "...",
            "developer_message": "...",
            "retryable": true,
            "retry_after": 60,
            "documentation": "..."
          },
          "request_id": "..."
        }

    Always serialised via `model_dump(mode='json', exclude_none=True)` —
    None-valued optional fields are omitted from the wire (compact for
    agent context windows).
    """

    model_config = ConfigDict(extra="allow")

    code: ErrorCode = Field(..., description="Closed-enum machine-readable error code.")
    user_message: str = Field(..., description="Plain-Japanese end-user message. ≤200 chars.")
    developer_message: str | None = Field(
        default=None,
        description="English/structured detail for the integrating developer (stack hints, trace-id pointers).",
    )
    retryable: bool = Field(
        ..., description="Whether a naive client should retry this exact request."
    )
    retry_after: int | None = Field(
        default=None,
        ge=0,
        description="Seconds to wait before retrying. Mirrors the Retry-After header.",
    )
    documentation: str = Field(
        default=DOC_URL, description="Public docs anchor for this error code."
    )

    # ----- Class-method constructors (one per common 4xx/5xx) ---------------

    @classmethod
    def rate_limited(
        cls,
        retry_after: int,
        *,
        user_message: str | None = None,
        developer_message: str | None = None,
    ) -> StandardError:
        """429 — Retry-After in seconds. Used by anonymous IP limit + paid throttle."""
        return cls(
            code="RATE_LIMITED",
            user_message=user_message or _DEFAULT_USER_MESSAGE["RATE_LIMITED"],
            developer_message=developer_message,
            retryable=True,
            retry_after=int(retry_after),
            documentation=f"{DOC_URL}#rate_limited",
        )

    @classmethod
    def unauthorized(
        cls,
        *,
        user_message: str | None = None,
        developer_message: str | None = None,
    ) -> StandardError:
        """401 — missing/invalid X-API-Key. Not retryable until the caller rotates the key."""
        return cls(
            code="UNAUTHORIZED",
            user_message=user_message or _DEFAULT_USER_MESSAGE["UNAUTHORIZED"],
            developer_message=developer_message,
            retryable=False,
            documentation=f"{DOC_URL}#unauthorized",
        )

    @classmethod
    def forbidden(
        cls,
        *,
        user_message: str | None = None,
        developer_message: str | None = None,
    ) -> StandardError:
        """403 — auth ok but the action is not permitted (license-gate is separate)."""
        return cls(
            code="FORBIDDEN",
            user_message=user_message or _DEFAULT_USER_MESSAGE["FORBIDDEN"],
            developer_message=developer_message,
            retryable=False,
            documentation=f"{DOC_URL}#forbidden",
        )

    @classmethod
    def not_found(
        cls,
        resource: str,
        identifier: str | int | None = None,
        *,
        user_message: str | None = None,
        developer_message: str | None = None,
    ) -> StandardError:
        """404 — resource lookup miss. `resource` is the table/route family."""
        if developer_message is None:
            developer_message = f"{resource} not found" + (
                f" for id={identifier!r}" if identifier is not None else ""
            )
        return cls(
            code="NOT_FOUND",
            user_message=user_message or _DEFAULT_USER_MESSAGE["NOT_FOUND"],
            developer_message=developer_message,
            retryable=False,
            documentation=f"{DOC_URL}#not_found",
        )

    @classmethod
    def bad_request(
        cls,
        field: str,
        reason: str,
        *,
        user_message: str | None = None,
        developer_message: str | None = None,
    ) -> StandardError:
        """400/422 — validation failure on a single named field."""
        if developer_message is None:
            developer_message = f"field={field!r}: {reason}"
        return cls(
            code="VALIDATION_ERROR",
            user_message=user_message or _DEFAULT_USER_MESSAGE["VALIDATION_ERROR"],
            developer_message=developer_message,
            retryable=False,
            documentation=f"{DOC_URL}#validation_error",
        )

    @classmethod
    def license_gate_blocked(
        cls,
        domain: str | None = None,
        *,
        user_message: str | None = None,
        developer_message: str | None = None,
    ) -> StandardError:
        """403 sub-case — `?license=` filter dropped every row, OR the route refused proprietary data."""
        if developer_message is None and domain is not None:
            developer_message = (
                f"source domain {domain!r} carries a non-redistributable license; "
                "drop the row or rerun with ?license=proprietary explicit."
            )
        return cls(
            code="LICENSE_GATE_BLOCKED",
            user_message=user_message or _DEFAULT_USER_MESSAGE["LICENSE_GATE_BLOCKED"],
            developer_message=developer_message,
            retryable=False,
            documentation=f"{DOC_URL}#license_gate_blocked",
        )

    @classmethod
    def quota_exceeded(
        cls,
        *,
        user_message: str | None = None,
        developer_message: str | None = None,
        retry_after: int | None = None,
    ) -> StandardError:
        """429 sub-case — monthly cap (anonymous 3/日 OR paid customer-set cap)."""
        return cls(
            code="QUOTA_EXCEEDED",
            user_message=user_message or _DEFAULT_USER_MESSAGE["QUOTA_EXCEEDED"],
            developer_message=developer_message,
            retryable=False,
            retry_after=retry_after,
            documentation=f"{DOC_URL}#quota_exceeded",
        )

    @classmethod
    def integrity_error(
        cls,
        *,
        user_message: str | None = None,
        developer_message: str | None = None,
    ) -> StandardError:
        """500 sub-case — DB integrity check, FK violation, or cross-source mismatch detected mid-request."""
        return cls(
            code="INTEGRITY_ERROR",
            user_message=user_message or _DEFAULT_USER_MESSAGE["INTEGRITY_ERROR"],
            developer_message=developer_message,
            retryable=True,
            documentation=f"{DOC_URL}#integrity_error",
        )

    @classmethod
    def internal(
        cls,
        *,
        user_message: str | None = None,
        developer_message: str | None = None,
    ) -> StandardError:
        """500 — catch-all unexpected exception. `developer_message` should carry the trace pointer."""
        return cls(
            code="INTERNAL_ERROR",
            user_message=user_message or _DEFAULT_USER_MESSAGE["INTERNAL_ERROR"],
            developer_message=developer_message,
            retryable=True,
            documentation=f"{DOC_URL}#internal_error",
        )


class StandardResponse(BaseModel):
    """Canonical success / non-error response envelope per §28.2.

    Wire shape:

        {
          "status": "rich | sparse | empty | partial | error",
          "query_echo": {...},
          "results": [...],
          "citations": [...],
          "warnings": [...],
          "suggested_actions": [...],
          "meta": {...},
          # optional, status-specific:
          "empty_reason": "...",
          "retry_with": {...},
          "error": {...}        # only when status='error'
        }

    Always serialise via `model_dump(mode='json', exclude_none=True)` so
    None-valued optional fields stay off the wire.
    """

    model_config = ConfigDict(extra="allow")

    status: StatusType = Field(..., description="One of rich / sparse / empty / partial / error.")
    query_echo: QueryEcho = Field(
        default_factory=QueryEcho, description="Server-side echo of caller input."
    )
    results: list[Any] = Field(
        default_factory=list, description="Result rows. Empty for status='empty' / 'error'."
    )
    citations: list[Citation] = Field(
        default_factory=list,
        description="Primary-source citations backing `results`. May be empty when sources are inline on each row.",
    )
    warnings: list[str] = Field(
        default_factory=list,
        description="Soft warnings: deprecation notice, sub-source partial failure, snapshot staleness.",
    )
    suggested_actions: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Deterministic follow-up calls. Each item: {tool|endpoint, args, reason?}.",
    )
    meta: ResponseMeta = Field(
        ..., description="Per-response metadata (request_id, latency, billable_units)."
    )

    # Status-specific optional fields ---------------------------------------

    empty_reason: (
        Literal["no_match", "filters_too_narrow", "source_unavailable", "license_blocked"] | None
    ) = Field(
        default=None,
        description="When status='empty': which of the four cases applies.",
    )
    retry_with: dict[str, Any] | None = Field(
        default=None,
        description="When status='empty' or 'sparse': a concrete next-call hint (broaden filters, alt query).",
    )
    error: StandardError | None = Field(
        default=None,
        description="When status='error': the canonical error envelope. None otherwise.",
    )

    # ----- Class-method constructors ---------------------------------------

    @classmethod
    def rich(
        cls,
        results: list[Any],
        *,
        request_id: str,
        citations: list[Citation] | list[dict[str, Any]] | None = None,
        query_echo: QueryEcho | dict[str, Any] | None = None,
        warnings: list[str] | None = None,
        suggested_actions: list[dict[str, Any]] | None = None,
        latency_ms: int = 0,
        billable_units: int = 1,
        client_tag: str | None = None,
    ) -> StandardResponse:
        """Build a rich response (N≥5 results, no apology needed).

        `results` < 5 falls through to `sparse(...)` so the caller can use
        `rich(...)` unconditionally and the envelope self-classifies.
        """
        return cls._build_success(
            status_override=None,
            results=results,
            request_id=request_id,
            citations=citations,
            query_echo=query_echo,
            warnings=warnings,
            suggested_actions=suggested_actions,
            latency_ms=latency_ms,
            billable_units=billable_units,
            client_tag=client_tag,
        )

    @classmethod
    def sparse(
        cls,
        results: list[Any],
        *,
        request_id: str,
        citations: list[Citation] | list[dict[str, Any]] | None = None,
        query_echo: QueryEcho | dict[str, Any] | None = None,
        retry_with: dict[str, Any] | None = None,
        warnings: list[str] | None = None,
        suggested_actions: list[dict[str, Any]] | None = None,
        latency_ms: int = 0,
        billable_units: int = 1,
        client_tag: str | None = None,
    ) -> StandardResponse:
        """Build a sparse response (1..N-1 results). `retry_with` hint encouraged."""
        env = cls._build_success(
            status_override="sparse",
            results=results,
            request_id=request_id,
            citations=citations,
            query_echo=query_echo,
            warnings=warnings,
            suggested_actions=suggested_actions,
            latency_ms=latency_ms,
            billable_units=billable_units,
            client_tag=client_tag,
        )
        if retry_with is not None:
            env.retry_with = retry_with
        return env

    @classmethod
    def empty(
        cls,
        *,
        request_id: str,
        empty_reason: Literal[
            "no_match", "filters_too_narrow", "source_unavailable", "license_blocked"
        ] = "no_match",
        retry_with: dict[str, Any] | None = None,
        query_echo: QueryEcho | dict[str, Any] | None = None,
        warnings: list[str] | None = None,
        suggested_actions: list[dict[str, Any]] | None = None,
        latency_ms: int = 0,
        billable_units: int = 1,
        client_tag: str | None = None,
    ) -> StandardResponse:
        """Zero results. `empty_reason` MUST be set (default 'no_match')."""
        env = cls._build_success(
            status_override="empty",
            results=[],
            request_id=request_id,
            citations=None,
            query_echo=query_echo,
            warnings=warnings,
            suggested_actions=suggested_actions,
            latency_ms=latency_ms,
            billable_units=billable_units,
            client_tag=client_tag,
        )
        env.empty_reason = empty_reason
        env.retry_with = retry_with
        return env

    @classmethod
    def partial(
        cls,
        results: list[Any],
        *,
        request_id: str,
        warnings: list[str],
        citations: list[Citation] | list[dict[str, Any]] | None = None,
        query_echo: QueryEcho | dict[str, Any] | None = None,
        suggested_actions: list[dict[str, Any]] | None = None,
        latency_ms: int = 0,
        billable_units: int = 1,
        client_tag: str | None = None,
    ) -> StandardResponse:
        """Some sub-source failed. `warnings` MUST be non-empty."""
        if not warnings:
            warnings = ["partial result: at least one sub-source failed"]
        return cls._build_success(
            status_override="partial",
            results=results,
            request_id=request_id,
            citations=citations,
            query_echo=query_echo,
            warnings=warnings,
            suggested_actions=suggested_actions,
            latency_ms=latency_ms,
            billable_units=billable_units,
            client_tag=client_tag,
        )

    @classmethod
    def from_error(
        cls,
        err: StandardError,
        *,
        request_id: str,
        query_echo: QueryEcho | dict[str, Any] | None = None,
        latency_ms: int = 0,
        billable_units: int = 0,
        client_tag: str | None = None,
    ) -> StandardResponse:
        """Wrap a ``StandardError`` into the response envelope. ``results=[]``.

        Named ``from_error`` (not ``error``) to avoid pydantic v2's
        classmethod-vs-field name collision: the wire shape carries an
        ``error`` field, and pydantic re-binds field names onto the
        class so a same-named classmethod becomes unreachable.
        """
        env = cls._build_success(
            status_override="error",
            results=[],
            request_id=request_id,
            citations=None,
            query_echo=query_echo,
            warnings=None,
            suggested_actions=None,
            latency_ms=latency_ms,
            billable_units=billable_units,
            client_tag=client_tag,
        )
        env.error = err
        return env

    # ----- Internal builder ------------------------------------------------

    @classmethod
    def _build_success(
        cls,
        *,
        status_override: StatusType | None,
        results: list[Any],
        request_id: str,
        citations: list[Citation] | list[dict[str, Any]] | None,
        query_echo: QueryEcho | dict[str, Any] | None,
        warnings: list[str] | None,
        suggested_actions: list[dict[str, Any]] | None,
        latency_ms: int,
        billable_units: int,
        client_tag: str | None,
    ) -> StandardResponse:
        # Coerce query_echo dicts into the model.
        if isinstance(query_echo, dict):
            qe = QueryEcho(**query_echo)
        elif isinstance(query_echo, QueryEcho):
            qe = query_echo
        else:
            qe = QueryEcho()

        # Coerce citation dicts into models.
        cit_models: list[Citation] = []
        if citations:
            for c in citations:
                if isinstance(c, Citation):
                    cit_models.append(c)
                elif isinstance(c, dict):
                    cit_models.append(Citation(**c))
                # silently drop other shapes — never raise on telemetry data

        # Auto-classify when caller didn't override.
        if status_override is None:
            status: StatusType = (
                "rich" if len(results) >= _RICH_THRESHOLD else ("sparse" if results else "empty")
            )
        else:
            status = status_override

        meta = ResponseMeta(
            request_id=request_id,
            api_version=ENVELOPE_API_VERSION,
            latency_ms=max(0, int(latency_ms)),
            billable_units=max(0, int(billable_units)),
            client_tag=client_tag,
        )
        return cls(
            status=status,
            query_echo=qe,
            results=list(results),
            citations=cit_models,
            warnings=list(warnings or []),
            suggested_actions=list(suggested_actions or []),
            meta=meta,
        )

    # ----- Wire serialisation --------------------------------------------

    def to_wire(self) -> dict[str, Any]:
        """Return a JSON-serialisable dict with None values dropped.

        FastAPI's `JSONResponse(content=...)` auto-jsonifies pydantic
        models, but we usually want the dict form so optional None values
        are dropped consistently. Always prefer this over `.model_dump()`
        to avoid leaking None into JSON.
        """
        return self.model_dump(mode="json", exclude_none=True)


# ---------------------------------------------------------------------------
# Opt-in detection helper.
# ---------------------------------------------------------------------------

#: Media type for the `Accept` header opt-in. Vendor tree per RFC 6838.
ENVELOPE_V2_MEDIA_TYPE: str = "application/vnd.jpcite.v2+json"


def wants_envelope_v2(request: Any) -> bool:
    """Return True when the caller opted into the v2 envelope.

    Opt-in is negotiated through the ``Accept`` header containing
    ``application/vnd.jpcite.v2+json``. Query-param negotiation was removed
    before launch because strict routes reject unknown query parameters and
    public docs now advertise one canonical path.

    Soft-fail: any AttributeError on the duck-typed `request` returns
    False (the route falls back to the legacy shape). Never raises.
    """
    try:
        accept = request.headers.get("accept", "")
        if isinstance(accept, str) and ENVELOPE_V2_MEDIA_TYPE in accept.lower():
            return True
    except Exception:  # noqa: BLE001
        pass

    return False


__all__ = [
    "DOC_URL",
    "ENVELOPE_API_VERSION",
    "ENVELOPE_V2_MEDIA_TYPE",
    "ErrorCode",
    "LEGACY_ERROR_CODE_TO_CANONICAL",
    "QueryEcho",
    "Citation",
    "ResponseMeta",
    "StandardError",
    "StandardResponse",
    "StatusType",
    "wants_envelope_v2",
]
