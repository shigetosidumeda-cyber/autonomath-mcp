"""Anonymous-quota response headers (S3 friction removal, 2026-04-25)
plus in-response soft-warning body injection (CRO Fix 5a, 2026-04-29).

Every successful anonymous response (no X-API-Key, no Authorization: Bearer)
carries three response headers so an LLM caller — or its human-in-the-loop —
sees the remaining free quota and the conversion path **before** the 3 req/日
ceiling triggers a 429:

* ``X-Anon-Quota-Remaining`` — integer, calls left this JST calendar day.
* ``X-Anon-Quota-Reset``     — ISO 8601 timestamp of next JST 翌日 00:00.
* ``X-Anon-Upgrade-Url``     — public landing for API-key issuance.

Why headers (not body wrapping):

The product has zero UI; the value is the API + MCP + static docs. We do
not own the calling client's render layer, so a body-level wrapper would
fight every existing JSON consumer. Headers are non-invasive: callers that
ignore them keep working, callers that read them (claude.ai's MCP host,
operator dashboards, curl scripts, custom Python clients) get the upgrade
hint surfaced naturally.

Why anonymous-only:

The 429 path covers the hard ceiling. These headers cover the *soft*
runway — the calls before the daily ceiling — to convert traffic that
otherwise would silently churn at request 4. Authenticated callers
already know the upgrade URL (they used it once); spamming it on every
paid response is noise.

CRO Fix 5a — in-response soft-warning (2026-04-29):

When the anonymous caller is in the last 20% of their daily runway, we
additionally inject
``_meta.upgrade_hint`` into the JSON response body. Headers alone aren't
enough: many MCP hosts and curl scripts surface the body to the user but
swallow response headers. The hint is a single human-readable string and
sits under ``_meta`` so it never collides with a top-level result key.

Body injection rules:

- 200..399 only (4xx/5xx already carry their own envelopes; the 429
  refusal envelope from ``anon_limit.py`` is the canonical conversion
  surface for the hard-stop case).
- Content-Type must start with ``application/json``.
- Body must parse as a JSON object (``dict``). Arrays / scalars / NDJSON
  / streaming responses are skipped — there is no safe place to inject.
- If the body already carries ``_meta.upgrade_hint``, we do not overwrite
  (downstream code may want to set its own).
- Skipped silently (no exception bubbles to the client) on any parse,
  re-serialize, or content-length update failure — the hint is a soft
  conversion lever, never a 500 amplifier.

Quota state source:

``enforce_anon_ip_limit`` (router-level dep, ``api/anon_limit.py``) writes
``request.state.anon_quota`` after its INSERT/UPDATE so the count is
authoritative for *this* request — no second SELECT here. If the dep was
not attached to the route (whitelisted endpoint like ``/healthz``), no
``anon_quota`` is set and we leave the response alone.

Failure posture:

A missing ``request.state.anon_quota`` is the normal "this route is not
anon-quota-gated" signal — silent skip. Any other exception is logged at
WARN and swallowed; broken header injection must never become a 500
amplifier.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from jpintel_mcp.api.anon_limit import UPGRADE_URL_BASE

if TYPE_CHECKING:
    from collections.abc import Callable

    from fastapi import Request

_log = logging.getLogger("jpintel.anon_quota_header")

# Public landing for the soft-warning conversion path. The hard 429 path
# already uses ``UPGRADE_URL_FROM_429`` (?from=429); the soft warning
# uses the bare ``/upgrade`` URL so funnel analytics can distinguish
# preventive conversions from forced ones.
_SOFT_UPGRADE_URL = "https://jpcite.com/upgrade"

# Routes whose JSON contract is strict-shape: every key is part of a
# documented Program / ProgramDetail / SearchResponse schema, and tests
# assert exact key sets (minimal whitelist, full key guarantee, parity
# between two consecutive calls). Body injection of ``_meta.upgrade_hint``
# would silently add an extra key to the response — breaking minimal-
# whitelist exclusivity and producing differing payloads across calls
# because the ``remaining`` counter advances. For these prefixes we
# stamp the X-Anon-Quota-* headers (header-level CRO surface) but skip
# the body inject. Conversion callers that read JSON only still see the
# upgrade signal via ``X-Anon-Upgrade-Url`` + ``X-Anon-Quota-Remaining``.
_BODY_INJECT_DENYLIST_PREFIXES = ("/v1/programs/",)


def _is_anonymous(request: Request) -> bool:
    """Same anon-detection rule as ``enforce_anon_ip_limit``.

    A request is "claiming auth" if it sends ``X-API-Key`` or an
    ``Authorization: Bearer ...`` header. Whether the key is *valid* is
    not our concern — bogus keys hit the 401 path elsewhere; the anon
    bucket is untouched for that request, so we should not stamp anon
    headers either.
    """
    if request.headers.get("x-api-key"):
        return False
    auth = request.headers.get("authorization", "")
    return not (auth and auth.split(None, 1)[0].lower() == "bearer")


def _build_upgrade_hint(remaining: int, reset_at: str) -> str:
    """Build the human-readable soft-warning string.

    Format aligns with the 429 body's ``cta_text_ja`` voice — terse,
    actionable, includes the concrete remaining count + the JST reset
    cue + the upgrade URL. ``reset_at`` is accepted for parity with
    ``X-Anon-Quota-Reset`` but is intentionally not interpolated: the
    next-day-start phrase ("JST 翌日 00:00 reset") is calendar-stable and
    reads more naturally than an ISO timestamp inline.
    """
    del reset_at  # see docstring — kept in signature for symmetry / future use
    # Copy reflects the 2026-04-30 monthly→daily switch (see anon_limit.py
    # module docstring): cap is 3 req/日 with JST 翌日 00:00 reset, NOT
    # the legacy monthly copy with 月初 reset. Stale copy was caught by the 2026-05-01
    # conversion-friction audit (analysis_wave18/conversion_friction_audit_2026-05-01.md).
    return (
        f"残 {remaining} req。 Free 3 req/日、 JST 翌日 00:00 reset。 "
        f"{_SOFT_UPGRADE_URL} で API キー発行で即時再開"
    )


def _looks_streaming(response: Response) -> bool:
    """Best-effort detection of true SSE / chunked streams.

    Note: ``BaseHTTPMiddleware`` wraps every downstream response as a
    ``_StreamingResponse`` with a ``body_iterator``, so the presence of
    that attribute alone does NOT mean the route is genuinely streaming.
    Real streams declare themselves via ``Content-Type: text/event-stream``
    or ``Transfer-Encoding: chunked``; bytes-buffered JSON responses
    (FastAPI ``JSONResponse`` / ``ORJSONResponse``) just happen to be
    delivered as a one-shot iterator under ``BaseHTTPMiddleware``.
    """
    ctype = response.headers.get("content-type", "").lower()
    if "text/event-stream" in ctype:
        return True
    # If the upstream explicitly opted into chunked transfer we leave it
    # alone — content-length recomputation is unsafe in that mode.
    return response.headers.get("transfer-encoding", "").lower() == "chunked"


async def _drain_body(response: Response) -> bytes | None:
    """Best-effort drain of a ``BaseHTTPMiddleware`` streaming response.

    BaseHTTPMiddleware always returns a ``_StreamingResponse`` with a
    ``body_iterator`` (even for one-shot JSON responses). To inject into
    the body we must consume that iterator and rebuild a fresh
    ``Response``. Returns the concatenated bytes on success, or ``None``
    if the response is not a streaming wrapper (in which case the caller
    falls back to ``getattr(response, 'body', None)``).
    """
    body_iter = getattr(response, "body_iterator", None)
    if body_iter is None:
        return None
    chunks: list[bytes] = []
    async for chunk in body_iter:
        if isinstance(chunk, str):
            chunk = chunk.encode("utf-8")
        chunks.append(chunk)
    return b"".join(chunks)


async def _maybe_inject_upgrade_hint(
    response: Response,
    remaining: int,
    reset_at: str,
) -> Response:
    """Inject ``_meta.upgrade_hint`` into the JSON response body.

    Returns the response (possibly a new ``Response`` instance with the
    rewritten body) on success, or the original ``response`` on any
    skip / error condition. Never raises.

    Skip conditions (silent):
      - Status >= 400 (the 429 envelope is the canonical hard-stop surface).
      - Streaming / SSE / chunked transfer.
      - Content-Type is not ``application/json`` (Pydantic JSON, FastAPI
        ``JSONResponse``, and ``ORJSONResponse`` all set this).
      - Body fails to parse as a JSON object (arrays / scalars / NDJSON
        skip — there is no safe insertion point).
      - Body already carries ``_meta.upgrade_hint`` (don't overwrite a
        downstream-set hint).

    If we drain the body iterator to inspect it but then decide NOT to
    inject (e.g. the payload is a list), we still must return a fresh
    ``Response`` carrying those drained bytes — the iterator is
    one-shot and the original wrapper is now empty. ``_passthrough``
    handles that rebuild.
    """
    try:
        if response.status_code >= 400:
            return response
        if _looks_streaming(response):
            return response

        ctype = response.headers.get("content-type", "")
        # Match application/json and application/json; charset=utf-8 etc.
        # but NOT application/jsonl or application/x-ndjson.
        ctype_main = ctype.split(";", 1)[0].strip().lower()
        if ctype_main != "application/json":
            return response

        # BaseHTTPMiddleware wraps every response in a streaming iterator,
        # so direct .body access returns None / empty. Drain the iterator
        # ourselves; if drain returns None, fall back to the (rare)
        # buffered-body case.
        body_bytes = await _drain_body(response)
        if body_bytes is None:
            body_bytes = getattr(response, "body", None)
        if not body_bytes:
            return response

        # Helper: rebuild a passthrough Response when we drained the body
        # but won't inject. Keeps the wire format identical to what the
        # caller would have received without this middleware.
        def _passthrough() -> Response:
            new_headers = dict(response.headers)
            new_headers["content-length"] = str(len(body_bytes))
            return Response(
                content=body_bytes,
                status_code=response.status_code,
                headers=new_headers,
                media_type=response.media_type,
            )

        try:
            payload = json.loads(body_bytes)
        except (ValueError, TypeError):
            return _passthrough()

        if not isinstance(payload, dict):
            # Lists / scalars / null — no safe injection point.
            return _passthrough()

        existing_meta = payload.get("_meta")
        if isinstance(existing_meta, dict) and "upgrade_hint" in existing_meta:
            # A downstream layer already set the hint; do not overwrite.
            return _passthrough()

        hint = _build_upgrade_hint(remaining=remaining, reset_at=reset_at)
        if isinstance(existing_meta, dict):
            # Preserve any other _meta keys the response already carries.
            new_meta = dict(existing_meta)
            new_meta["upgrade_hint"] = hint
        else:
            # Either missing or a non-dict value (e.g. None, a string).
            # We only inject when there is no conflicting non-dict value;
            # if _meta is set to something non-dict we leave it alone to
            # avoid breaking that contract.
            if existing_meta is not None:
                return _passthrough()
            new_meta = {"upgrade_hint": hint}
        payload["_meta"] = new_meta

        # Re-serialize. ``ensure_ascii=False`` keeps the Japanese hint
        # readable on the wire (matches the 429 envelope's encoding).
        new_body = json.dumps(payload, ensure_ascii=False).encode("utf-8")

        # Rebuild a Response with the same status / headers. We MUST
        # update Content-Length (the original was for the smaller body)
        # and drop any Content-Encoding the upstream set: re-encoding
        # here means we ship plain UTF-8 JSON regardless of whether the
        # upstream had set ``br`` or ``gzip`` (Starlette's compression
        # middleware, if any, sits OUTSIDE this one and will recompress
        # if it cares).
        new_headers = dict(response.headers)
        new_headers["content-length"] = str(len(new_body))
        # If a content-encoding was set, our re-serialized body is not
        # encoded with it — strip the header so the client doesn't try
        # to decompress plain JSON.
        new_headers.pop("content-encoding", None)
        return Response(
            content=new_body,
            status_code=response.status_code,
            headers=new_headers,
            media_type=response.media_type,
        )
    except Exception:  # pragma: no cover — defensive, see module docstring
        _log.warning("anon_quota_header: failed to inject upgrade_hint", exc_info=True)
        return response


class AnonQuotaHeaderMiddleware(BaseHTTPMiddleware):
    """Stamp anon-quota response headers on every anonymous response.

    Also injects ``_meta.upgrade_hint`` into the JSON body when the
    caller is in the last 20% of their monthly runway (CRO Fix 5a,
    2026-04-29). See module docstring for body-injection rules.
    """

    async def dispatch(self, request: Request, call_next: Callable[..., Any]) -> Response:
        response: Response = await call_next(request)

        # Fast skip: authed callers don't get anon headers.
        try:
            if not _is_anonymous(request):
                return response
        except Exception:  # pragma: no cover — defensive
            return response

        # The router-level dep populated request.state.anon_quota when it
        # ran. Routes that don't carry the dep (e.g. /healthz, /readyz,
        # /v1/billing/webhook) have no quota state -> silent skip.
        quota = getattr(request.state, "anon_quota", None)
        if not isinstance(quota, dict):
            return response

        try:
            remaining = int(quota.get("remaining", 0))
            limit = int(quota.get("limit", 0) or 0)
            reset_at = str(quota.get("reset_at_jst", ""))
            if remaining < 0:
                remaining = 0
            response.headers.setdefault("X-Anon-Quota-Remaining", str(remaining))
            if reset_at:
                response.headers.setdefault("X-Anon-Quota-Reset", reset_at)
            response.headers.setdefault("X-Anon-Upgrade-Url", UPGRADE_URL_BASE)
        except Exception:  # pragma: no cover — defensive
            _log.warning("anon_quota_header: failed to stamp headers", exc_info=True)
            return response

        # Soft-warning body injection: only when the caller is at 80%+
        # consumption. Below the threshold the headers alone are enough.
        # Strict-shape routes (programs.{search,get_program,batch}) opt
        # out of body injection — their response contract enumerates an
        # exact key set. Headers stay on so the upgrade signal survives.
        path = request.url.path or ""
        body_inject_denied = any(
            path.startswith(prefix) for prefix in _BODY_INJECT_DENYLIST_PREFIXES
        )
        should_soft_warn = limit > 0 and remaining * 5 <= limit
        if should_soft_warn and not body_inject_denied:
            response = await _maybe_inject_upgrade_hint(
                response, remaining=remaining, reset_at=reset_at
            )

        return response


__all__ = ["AnonQuotaHeaderMiddleware"]
