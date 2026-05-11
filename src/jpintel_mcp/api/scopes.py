"""Scope definitions + agent/browser request classifier (Wave 18 AX).

This module centralises two concerns that previously lived implicitly in
individual route handlers:

1. **Scope identifiers** (string constants) that route guards check against
   ``api_keys.scope`` to decide whether a token may invoke a given action.
   APPI personal-data intake adds two scopes:

   - ``appi:read``   — read-only intake (POST /v1/privacy/disclosure_request)
   - ``appi:delete`` — deletion intake (POST /v1/privacy/deletion_request)

   These are additive to the historical ``api:read`` / ``api:metered`` set
   minted by the device-code flow; a paid metered key does NOT
   automatically carry ``appi:*`` — operators grant them out-of-band so
   one-off agent integrations can not accidentally fire §31 / §33 intake
   noise.

2. **Agent-vs-browser classifier** used by APPI routes to pick the right
   auth path. The ax_smart_guide §4 anti-pattern forbids gating an
   agent-callable endpoint on a browser-only challenge. The same route
   still needs a browser-only spam-protect challenge for the static-site
   form POST, so we keep both branches behind one handler: agent UA →
   require X-API-Key + scope, browser UA → require the browser spam
   token (see ``jpintel_mcp.security.spam_protect``).

The classifier is intentionally conservative: a request is treated as a
browser request unless it carries an explicit X-API-Key header **or** a
recognised agent UA marker. This means a hostile browser cannot bypass
the spam token by sending a fake UA — without a valid key the agent
branch 401s before we ever invoke the browser spam-protect helper.
"""

from __future__ import annotations

from typing import Final

# ---------------------------------------------------------------------------
# Scope identifiers
# ---------------------------------------------------------------------------

#: Read-side APPI scope. Required for POST /v1/privacy/disclosure_request
#: when the request is agent-classified (X-API-Key present or agent UA).
SCOPE_APPI_READ: Final[str] = "appi:read"

#: Delete-side APPI scope. Required for POST /v1/privacy/deletion_request
#: when the request is agent-classified.
SCOPE_APPI_DELETE: Final[str] = "appi:delete"

#: All APPI scopes — used by docs / introspection.
APPI_SCOPES: Final[frozenset[str]] = frozenset({SCOPE_APPI_READ, SCOPE_APPI_DELETE})


# ---------------------------------------------------------------------------
# Agent UA classifier
# ---------------------------------------------------------------------------

# Lower-cased substring markers. If any of these appear in the request's
# User-Agent header, the request is treated as an agent request even when
# X-API-Key is absent (in which case the handler 401s on the agent branch
# rather than falling through to the browser spam-protect branch).
#
# Keep this list short and stable — we are NOT trying to enumerate every
# bot in existence, only the ones that are likely to call our APPI
# endpoints (curl-script integrations + MCP clients + the major LLM
# Actions runtimes). Anything not on this list still passes through to
# the browser branch, which gracefully degrades to "require browser
# spam-protect token".
_AGENT_UA_MARKERS: Final[tuple[str, ...]] = (
    "curl/",
    "httpx",
    "python-requests",
    "axios",
    "node-fetch",
    "go-http-client",
    "okhttp",
    "anthropic-",  # claude-agent-sdk + Anthropic client libs
    "openai/",  # ChatGPT Actions runtime
    "openai-python",
    "cursor/",
    "claude-code/",
    "mcp-",  # generic MCP client UA prefix
)


def has_api_key_header(x_api_key: str | None) -> bool:
    """Return True iff the caller sent a non-empty X-API-Key header.

    Whitespace-only values count as absent so an empty header from a
    misconfigured client does NOT route the request through the agent
    branch (where it would 401 instead of 401-via-spam-protect).
    """
    return bool(x_api_key and x_api_key.strip())


def classify_request_agent(*, x_api_key: str | None, user_agent: str | None) -> bool:
    """Decide whether a request should be served via the agent (token) path.

    Returns True when EITHER:
      - ``X-API-Key`` is present (caller has chosen the token path), OR
      - The User-Agent matches one of the known agent markers.

    Returns False otherwise — the caller will hit the browser path, which
    requires a browser spam-protect token when the deployment secret is set.

    The classifier is non-strict on UA in both directions: a misconfigured
    browser without a UA still goes to the browser path (the spam-protect
    helper will challenge it), and an agent without an X-API-Key still
    goes to the agent path (it will 401 with a "missing scope" detail,
    which is the correct DX feedback — silently dropping into the browser
    path would mask the integration error).
    """
    if has_api_key_header(x_api_key):
        return True
    if not user_agent:
        return False
    ua_low = user_agent.lower()
    return any(marker in ua_low for marker in _AGENT_UA_MARKERS)


__all__ = [
    "APPI_SCOPES",
    "SCOPE_APPI_DELETE",
    "SCOPE_APPI_READ",
    "classify_request_agent",
    "has_api_key_header",
]
