"""Browser-side funnel breadcrumb endpoint (`POST /v1/funnel/event`).

§4-E (jpcite_user_value_execution_plan_2026-05-03.md). Captures discrete
client-side events (Playground success, pricing view, MCP install copy,
checkout start, dashboard sign-in, etc.) so the operator can answer:

* Did the visitor get past pricing before bouncing?
* Did the curl-quickstart copy actually fire, or did people walk away?
* How many playground successes happen before the first pricing view?

`analytics_events` only captures server-side traffic and only as URL
paths — it cannot distinguish "loaded /pricing.html" from "clicked the
checkout button on /pricing.html". This table closes that gap.

Posture:

* Closed enum of event names — we accept exactly the 10 events listed
  in §4-E. Anything else returns 400 (so a stray copy-paste from another
  property cannot poison the funnel with garbage event types).
* Anonymous-friendly. No auth required; we record `key_hash` only when
  the visitor is signed in (passes `Authorization: Bearer` to the
  dashboard, etc.).
* Bot-flagged. UA is classified via the same `_classify_user_agent` as
  the per-request analytics middleware. Bot rows are still inserted but
  flagged `is_bot=1`; downstream consumers `WHERE is_bot=0`.
* Properties capped at 512 chars JSON to keep rows compact.
* PII: raw IP NEVER stored — same daily-rotated hash as
  `analytics_events.anon_ip_hash`.
* Transport-tolerant. Browsers can post `application/json`, but anonymous
  `navigator.sendBeacon()` posts may use `text/plain` to avoid CORS
  preflight during navigation. The endpoint parses the raw body itself so
  both transports land identically.

This is intentionally NOT part of the public OpenAPI export
(`include_in_schema=False`): it is an internal collection sink, not a
customer-facing API contract.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from datetime import UTC, datetime
from typing import Annotated
from urllib.parse import urlsplit

from fastapi import APIRouter, Header, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from jpintel_mcp.api.anon_limit import _classify_user_agent, _client_ip
from jpintel_mcp.api.deps import DbDep, hash_api_key, hash_ip_for_telemetry
from jpintel_mcp.api.middleware.analytics_recorder import _classify_src
from jpintel_mcp.security.pii_redact import redact_pii

_log = logging.getLogger("jpintel.funnel_events")

router = APIRouter(prefix="/v1/funnel", tags=["funnel"], include_in_schema=False)


# Closed enum of accepted event names. Mirrors §4-E item 3 exactly +
# §4.6 (jpcite_ai_discovery_paid_adoption_plan_2026-05-04.md) AI-mediated
# detection events. Adding a new event requires editing this set AND
# landing the corresponding client-side fire site (Playground / pricing /
# MCP install / etc.).
_ALLOWED_EVENTS: frozenset[str] = frozenset(
    {
        "pricing_view",
        "cta_click",
        "playground_request",
        "playground_success",
        "playground_quota_exhausted",
        "quickstart_copy",
        "openapi_import_click",
        "mcp_install_copy",
        "checkout_start",
        "dashboard_signin_success",
        # §4.6 — AI-mediated detection events. Server-side fire sites:
        #   * `ai_client_install_detected` — analytics_recorder /
        #     anon_limit observe a known LLM-client UA pattern
        #     (Claude / Cursor / Cline / Continue / Windsurf) and POST
        #     this event with properties.client_kind = the bucket label.
        #   * `mcp_device_flow_completed` — `/v1/mcp/device/poll` returns
        #     200 with a freshly-issued key (i.e. the flow finished).
        #     Carries properties.flow_kind = "mcp_device".
        #   * `openapi_actions_setup_completed` — the first authenticated
        #     request from a User-Agent matching ChatGPT Actions /
        #     Custom GPT / OpenAI Agents SDK after a key was just issued.
        #     Carries properties.client_kind = "chatgpt_actions" |
        #     "gpt_custom" | "openai_agents".
        "ai_client_install_detected",
        "mcp_device_flow_completed",
        "openapi_actions_setup_completed",
    }
)

# Cap on the JSON-encoded properties payload to keep `funnel_events` compact.
_MAX_PROPERTIES_JSON_BYTES = 512
# Cap on the raw body accepted by the anonymous beacon sink. Legitimate
# browser breadcrumbs are tiny; reject oversized payloads before JSON parsing.
_MAX_BODY_BYTES = 4096
# Cap on the page path stored.
_MAX_PAGE_LEN = 256
# Cap on the session_id stored (clients send a 128-bit hex = 32 chars).
_MAX_SESSION_ID_LEN = 64
_LOCAL_PAGE_HOSTS: frozenset[str] = frozenset(
    {
        "jpcite.com",
        "www.jpcite.com",
        "api.jpcite.com",
        "autonomath.ai",
        "www.autonomath.ai",
    }
)


class FunnelEventIn(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    event: str = Field(
        ...,
        description=(
            "One of the 13 accepted event names (10 §4-E web funnel + 3 "
            "§4.6 AI-mediated detection events)."
        ),
    )
    page: str | None = Field(
        default=None,
        description=(
            "URL path where the event fired (query string stripped, PII "
            "redacted). Cap 256 chars."
        ),
    )
    session_id: str | None = Field(
        default=None,
        description=(
            "Client-side random hex (sessionStorage). Used to chain events "
            "into a single visit without persistent identifiers."
        ),
    )
    properties: dict | None = Field(
        default=None,
        description="Optional discriminator object. JSON-encoded cap 512 chars.",
    )
    src: str | None = Field(
        default=None,
        description=(
            "§4.6 distribution-channel attribution token. Validated "
            "against the closed allowlist in analytics_recorder. "
            "Unrecognised values are silently dropped (NULL stored)."
        ),
    )


class FunnelEventResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    accepted: bool
    is_bot: bool
    user_agent_class: str


def _extract_key_hash(authorization: str | None, x_api_key: str | None) -> str | None:
    raw = x_api_key
    if not raw and authorization:
        parts = authorization.split(None, 1)
        if len(parts) == 2 and parts[0].lower() == "bearer":
            raw = parts[1].strip()
    if not raw:
        return None
    try:
        return hash_api_key(raw)
    except Exception:  # noqa: BLE001 — defensive
        return None


def _normalise_page(page: str | None) -> str | None:
    if not page:
        return None
    try:
        parsed = urlsplit(page)
    except ValueError:
        return None
    if parsed.scheme or parsed.netloc:
        host = parsed.hostname.lower() if parsed.hostname else None
        # Keep the column path-only and avoid foreign-origin pollution.
        if host not in _LOCAL_PAGE_HOSTS:
            return None
        raw_path = parsed.path or "/"
    else:
        raw_path = parsed.path or page
    # Strip query / fragment, redact path-param values (T-numbers, law IDs).
    redacted = redact_pii(raw_path)
    return redacted[:_MAX_PAGE_LEN]


def _json_len(raw: object) -> int:
    return len(
        json.dumps(raw, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    )


def _normalise_properties(props: dict | None) -> str | None:
    if not props:
        return None
    try:
        encoded = json.dumps(props, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError):
        return None
    if len(encoded.encode("utf-8")) > _MAX_PROPERTIES_JSON_BYTES:
        compact: dict[str, object] = {"_truncated": True}
        for key, value in props.items():
            if not isinstance(key, str):
                continue
            if not isinstance(value, (str, int, float, bool, type(None))):
                continue
            next_value: object = value[:120] if isinstance(value, str) else value
            candidate = compact | {key[:64]: next_value}
            try:
                if _json_len(candidate) <= _MAX_PROPERTIES_JSON_BYTES:
                    compact = candidate
            except (TypeError, ValueError):
                continue
        try:
            return json.dumps(compact, ensure_ascii=False, separators=(",", ":"))
        except (TypeError, ValueError):
            return '{"_truncated":true}'
    return encoded


def _normalise_session_id(sid: str | None) -> str | None:
    if not sid:
        return None
    sid = sid.strip()
    if not sid:
        return None
    return sid[:_MAX_SESSION_ID_LEN]


def _normalise_referer(ref: str | None) -> str | None:
    if not ref:
        return None
    try:
        host = urlsplit(ref).hostname
    except ValueError:
        return None
    if not host:
        return None
    # Cap at 128 chars (RFC 1035 max is 253; 128 is plenty for hostnames
    # we'd want to keep around).
    return host[:128]


async def _parse_body(request: Request) -> FunnelEventIn:
    try:
        chunks: list[bytes] = []
        total = 0
        async for chunk in request.stream():
            total += len(chunk)
            if total > _MAX_BODY_BYTES:
                raise HTTPException(
                    status.HTTP_413_CONTENT_TOO_LARGE,
                    detail="funnel event payload too large",
                )
            chunks.append(chunk)
        raw = b"".join(chunks)
        payload = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
        return FunnelEventIn.model_validate(payload)
    except (UnicodeDecodeError, json.JSONDecodeError, ValidationError, TypeError) as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="invalid funnel event payload",
        ) from exc


def _record(
    *,
    conn: sqlite3.Connection,
    ts: str,
    event_name: str,
    page: str | None,
    properties_json: str | None,
    anon_ip_hash: str | None,
    session_id: str | None,
    key_hash: str | None,
    user_agent_class: str | None,
    is_bot: bool,
    is_anonymous: bool,
    referer_host: str | None,
    src: str | None,
) -> None:
    try:
        # Migration 124 column list (12 columns including src).
        conn.execute(
            "INSERT INTO funnel_events("
            "  ts, event_name, page, properties_json, anon_ip_hash,"
            "  session_id, key_hash, user_agent_class, is_bot,"
            "  is_anonymous, referer_host, src"
            ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                ts,
                event_name,
                page,
                properties_json,
                anon_ip_hash,
                session_id,
                key_hash,
                user_agent_class,
                1 if is_bot else 0,
                1 if is_anonymous else 0,
                referer_host,
                src,
            ),
        )
    except sqlite3.OperationalError as exc:
        # Migration 124 not yet applied — fall back to the 11-column INSERT
        # (drops src). Once 124 ships everywhere this branch is unreachable.
        if "no column named src" in str(exc).lower():
            conn.execute(
                "INSERT INTO funnel_events("
                "  ts, event_name, page, properties_json, anon_ip_hash,"
                "  session_id, key_hash, user_agent_class, is_bot,"
                "  is_anonymous, referer_host"
                ") VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    ts,
                    event_name,
                    page,
                    properties_json,
                    anon_ip_hash,
                    session_id,
                    key_hash,
                    user_agent_class,
                    1 if is_bot else 0,
                    1 if is_anonymous else 0,
                    referer_host,
                ),
            )
        else:
            raise
    conn.commit()


@router.post(
    "/event",
    response_model=FunnelEventResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def post_event(
    request: Request,
    conn: DbDep,
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
    user_agent: Annotated[str | None, Header(alias="User-Agent")] = None,
    referer: Annotated[str | None, Header(alias="Referer")] = None,
) -> FunnelEventResponse:
    """Record one funnel breadcrumb."""
    body = await _parse_body(request)
    event_name = body.event.strip().lower()
    if event_name not in _ALLOWED_EVENTS:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail=f"unknown event '{event_name}'",
        )

    ua_class = _classify_user_agent(user_agent)
    is_bot = ua_class.startswith("bot:")
    key_hash = _extract_key_hash(authorization, x_api_key)
    is_anonymous = key_hash is None

    anon_ip_hash: str | None = None
    if is_anonymous:
        try:
            anon_ip_hash = hash_ip_for_telemetry(_client_ip(request))
        except Exception:  # noqa: BLE001 — defensive, IP hash must never block
            anon_ip_hash = None

    page = _normalise_page(body.page)
    properties_json = _normalise_properties(body.properties)
    session_id = _normalise_session_id(body.session_id)
    referer_host = _normalise_referer(referer)
    # §4.6: prefer body.src; fall back to the ?src= carried in body.page so
    # the static-site beacon can simply forward `location.href` and have
    # the server pull the channel attribution out of the page URL.
    raw_src = body.src
    if raw_src is None and body.page:
        try:
            parsed = urlsplit(body.page)
            from urllib.parse import parse_qs as _parse_qs

            qs = _parse_qs(parsed.query)
            if "src" in qs and qs["src"]:
                raw_src = qs["src"][0]
        except (ValueError, KeyError, IndexError):
            raw_src = None
    src = _classify_src(raw_src)
    ts = datetime.now(UTC).isoformat()

    try:
        _record(
            conn=conn,
            ts=ts,
            event_name=event_name,
            page=page,
            properties_json=properties_json,
            anon_ip_hash=anon_ip_hash,
            session_id=session_id,
            key_hash=key_hash,
            user_agent_class=ua_class,
            is_bot=is_bot,
            is_anonymous=is_anonymous,
            referer_host=referer_host,
            src=src,
        )
    except sqlite3.OperationalError as exc:
        # Migration 123 not yet applied — log + return 503 with a hint so
        # the static-site beacon doesn't retry forever.
        _log.warning(
            "funnel_events insert failed (likely missing migration 123): %s", exc
        )
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="funnel_events table not provisioned",
        ) from exc

    return FunnelEventResponse(
        accepted=True,
        is_bot=is_bot,
        user_agent_class=ua_class,
    )


__all__ = ["router"]
