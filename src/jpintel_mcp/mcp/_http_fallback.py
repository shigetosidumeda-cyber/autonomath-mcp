"""HTTP fallback for the AutonoMath MCP server (S3 launch blocker fix).

Background
----------
``uvx autonomath-mcp`` (Path B install via Claude Desktop) installs the
PyPI wheel, which **excludes** ``data/`` per ``pyproject.toml`` line 135.
``db.session.connect()`` therefore opens an empty SQLite file and registered
tools return 0 rows — silently broken.

This module routes tool calls to ``api.jpcite.com`` whenever the
local DB is missing data (row count of ``programs`` < 100). The MCP
process behaves identically from the caller's perspective: same JSON
shape, same metering (¥3/req), same anonymous 3 req/day quota — the
counting just happens server-side.

Design notes
------------
- One ``httpx.Client`` reused across calls (connection pooling).
- 10s timeout, 1 retry on connection / 5xx errors. Anything else is
  surfaced to the tool so the user sees the real error.
- ``JPCITE_API_KEY`` env passed as ``X-API-Key``. This is a jpcite REST/MCP
  key, not an LLM provider key. ``AUTONOMATH_API_KEY`` remains a legacy alias.
  Anonymous (no key) is allowed — the REST side gates the 3 req/day quota by IP.
- ``JPCITE_API_BASE`` env override (default ``https://api.jpcite.com``) for
  staging / local dev. ``AUTONOMATH_API_BASE`` remains a legacy alias.
- User-Agent carries the MCP package version so the REST side can
  segment fallback traffic in dashboards.
- We do **not** import ``httpx`` at module top — keep importing lazy
  so the (rare) DB-only path stays fast and never depends on httpx
  being installed at runtime.

Memory contract (project_autonomath_business_model.md):
- ¥3/req metered (税込 ¥3.30) — applies to fallback calls too.
- Anonymous 3 req/日 per IP — same quota.
- No Anthropic API call here. Inference happens client-side (Claude
  Desktop).
"""

from __future__ import annotations

import contextlib
import logging
import os
import sqlite3
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger("jpintel.mcp.http_fallback")

# --------------------------------------------------------------------------- #
# Environment knobs
# --------------------------------------------------------------------------- #

_DEFAULT_API_BASE = "https://api.jpcite.com"
_DEFAULT_TIMEOUT = 10.0
_DEFAULT_RETRY = 1

# Empty-DB threshold. The real DB carries 13,578 program rows; an
# uvx-installed wheel carries 0 (data/ excluded). We pick 1 so that
# an empty table flips fallback ON but any test fixture with seeded
# rows (typically 3-10) keeps the local-SQL path.
_PROGRAMS_FLOOR = 1


def _api_base() -> str:
    raw = (
        os.environ.get("JPCITE_API_BASE")
        or os.environ.get("AUTONOMATH_API_BASE")
        or _DEFAULT_API_BASE
    )
    return raw.rstrip("/")


def _api_key() -> str | None:
    env_key = os.environ.get("JPCITE_API_KEY") or os.environ.get("AUTONOMATH_API_KEY")
    if env_key:
        return env_key
    # Device-flow auth stores the issued jpcite key in the OS keychain.
    # Import lazily so the fallback path stays usable even when optional
    # keyring backends are not installed.
    with contextlib.suppress(Exception):
        from jpintel_mcp.mcp.auth import get_stored_token

        return get_stored_token()
    return None


def _user_agent() -> str:
    try:
        from importlib.metadata import version

        v = version("autonomath-mcp")
    except Exception:
        v = "unknown"
    return f"autonomath-mcp/{v} (http-fallback)"


# --------------------------------------------------------------------------- #
# Mode detection
# --------------------------------------------------------------------------- #

_HTTP_FALLBACK_MODE: bool | None = None
_HTTP_FALLBACK_MODE_AM: bool | None = None


def _is_api_server_context() -> bool:
    """Return True iff this process IS the API server (Fly prod).

    The HTTP fallback exists for *uvx end-user laptops* whose local DB
    is empty. The API server itself must NOT route fallback to itself —
    that creates a self-loop and makes /v1/am/* return 422 envelopes
    (because internal http_call adds `as_of`/`fields` params the REST
    layer rejects via strict_query). When `JPINTEL_ENV=prod` we ARE the
    fallback target, so honest path is to return data direct (or 503
    db_unavailable when DB missing).
    """
    import os

    return os.environ.get("JPINTEL_ENV", "").strip().lower() == "prod"


def detect_fallback_mode(db_path: Path | None = None) -> bool:
    """Return True iff the **jpintel.db** local DB is empty / missing.

    Caches the result in module state so subsequent tool calls don't
    re-hit SQLite. Pass ``db_path`` for tests that want to override.

    Use ``detect_fallback_mode_autonomath()`` for autonomath.db-backed
    tools (search_tax_incentives / search_certifications etc.).
    """
    if _is_api_server_context():
        # Self-loop guard: the API server is the fallback target itself.
        return False
    global _HTTP_FALLBACK_MODE
    if _HTTP_FALLBACK_MODE is not None and db_path is None:
        return _HTTP_FALLBACK_MODE

    from jpintel_mcp.config import settings

    path = db_path or settings.db_path
    mode = _probe_db_empty(path, table="programs", floor=_PROGRAMS_FLOOR)
    if db_path is None:
        _HTTP_FALLBACK_MODE = mode
    _log_mode_decision("jpintel.db", mode)
    return mode


def detect_fallback_mode_autonomath(db_path: Path | None = None) -> bool:
    """Return True iff the **autonomath.db** entity DB is empty / missing.

    Used by search_tax_incentives / search_certifications / list_open_programs
    fallback shims. The threshold is ``am_entities < 1000`` (full DB carries
    503,930 rows; a wheel-only install carries 0).
    """
    if _is_api_server_context():
        # Self-loop guard: the API server is the fallback target itself.
        return False
    global _HTTP_FALLBACK_MODE_AM
    if _HTTP_FALLBACK_MODE_AM is not None and db_path is None:
        return _HTTP_FALLBACK_MODE_AM

    from jpintel_mcp.config import settings

    path = db_path or settings.autonomath_db_path
    mode = _probe_db_empty(path, table="am_entities", floor=1000)
    if db_path is None:
        _HTTP_FALLBACK_MODE_AM = mode
    _log_mode_decision("autonomath.db", mode)
    return mode


def _probe_db_empty(path: Path, *, table: str, floor: int) -> bool:
    """Return True iff ``path`` is missing, tiny, missing the table, or
    has fewer than ``floor`` rows in it."""
    try:
        if not path.exists() or path.stat().st_size < 4096:
            return True
        with sqlite3.connect(str(path)) as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=?",
                (table,),
            ).fetchone()
            if not row or row[0] == 0:
                return True
            cnt = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            return bool(cnt < floor)
    except sqlite3.DatabaseError:
        # Corrupt / partial file → treat as empty.
        return True


def _log_mode_decision(label: str, mode: bool) -> None:
    if mode:
        logger.warning(
            "http_fallback_enabled db=%s api_base=%s reason=local_db_empty_or_missing",
            label,
            _api_base(),
        )
    else:
        logger.info("http_fallback_disabled db=%s local_db_ok", label)


def reset_fallback_mode() -> None:
    """Test hook — clear cached mode so the next call re-detects."""
    global _HTTP_FALLBACK_MODE, _HTTP_FALLBACK_MODE_AM
    _HTTP_FALLBACK_MODE = None
    _HTTP_FALLBACK_MODE_AM = None


# --------------------------------------------------------------------------- #
# HTTP client
# --------------------------------------------------------------------------- #

_client: Any = None


def _get_client() -> Any:
    """Lazy-import httpx and reuse a single Client. Returns the Client."""
    global _client
    key = _api_key()
    if _client is not None:
        current_key = _client.headers.get("X-API-Key")
        # After device-flow checkout, the key appears in keychain while the
        # MCP process is still running. Rebuild the client so the next tool
        # call immediately becomes paid/authenticated.
        if current_key == key:
            return _client
        _close_client()
    import httpx  # local import — keeps DB-only path lightweight

    headers: dict[str, str] = {
        "User-Agent": _user_agent(),
        "Accept": "application/json",
    }
    if key:
        headers["X-API-Key"] = key
    _client = httpx.Client(
        base_url=_api_base(),
        timeout=_DEFAULT_TIMEOUT,
        headers=headers,
    )
    return _client


def _envelope_error(
    code: str,
    message: str,
    *,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a §I canonical-envelope error response.

    Every HTTP fallback error path goes through this helper so the
    MASTER_PLAN §I 6-key contract is honoured uniformly:

      - ``results`` = []
      - ``total`` / ``limit`` / ``offset`` = 0
      - ``_billing_unit`` = 0 (errors never bill)
      - ``_next_calls`` = [] (no compound walk on error)
      - ``error`` is a dict with ``code`` + ``message`` + any extras

    ``extra`` is merged into the ``error`` block so caller-supplied keys
    (status_code, path, upgrade_url, etc.) cannot accidentally clobber
    the top-level envelope invariants. The W9-3 finding is that earlier
    code wrote the extras at the top level which corrupted ``results`` /
    ``_billing_unit`` checks downstream.
    """
    err: dict[str, Any] = {"code": code, "message": message}
    if extra:
        # Merge extras into the error block (NOT the envelope).
        for k, v in extra.items():
            err[k] = v
    return {
        "results": [],
        "total": 0,
        "limit": 0,
        "offset": 0,
        "_billing_unit": 0,
        "_next_calls": [],
        "error": err,
    }


def _quota_exceeded_payload(data: dict[str, Any], path: str) -> dict[str, Any]:
    """Return an MCP-friendly 429 envelope with conversion instructions."""
    message = ""
    with contextlib.suppress(Exception):
        from jpintel_mcp.mcp.auth import handle_quota_exceeded

        message = handle_quota_exceeded()
    if not message:
        upgrade_url = data.get("direct_checkout_url") or data.get("upgrade_url")
        message = (
            "無料枠に到達しました。続けるには jpcite API キーを発行してください: "
            f"{upgrade_url or 'https://jpcite.com/pricing.html#api-paid'}"
        )
    return _envelope_error(
        "quota_exceeded",
        message,
        extra={
            "status_code": 429,
            "detail": data,
            "path": path,
            "upgrade_url": data.get("upgrade_url"),
            "direct_checkout_url": data.get("direct_checkout_url"),
            "trial_signup_url": data.get("trial_signup_url"),
        },
    )


def _close_client() -> None:
    global _client
    if _client is not None:
        with contextlib.suppress(Exception):
            _client.close()
        _client = None


def http_call(
    path: str,
    *,
    method: str = "GET",
    params: dict[str, Any] | None = None,
    json_body: dict[str, Any] | None = None,
    retry: int = _DEFAULT_RETRY,
) -> dict[str, Any]:
    """Issue one REST call and return parsed JSON.

    On network / 5xx errors we retry up to ``retry`` times, then return
    a structured ``error`` dict (never raise) so MCP tool wrappers can
    surface it without crashing the stdio loop.
    """
    import httpx

    client = _get_client()
    last_exc: Exception | None = None
    for attempt in range(retry + 1):
        try:
            resp = client.request(
                method,
                path,
                params=params,
                json=json_body,
            )
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            last_exc = exc
            logger.warning(
                "http_fallback_network_error attempt=%d path=%s err=%s",
                attempt,
                path,
                exc,
            )
            continue

        # 5xx → retry. 4xx → surface immediately (caller may need 401/429
        # to trigger the device-flow auth path in mcp/auth.py).
        if resp.status_code >= 500 and attempt < retry:
            logger.warning(
                "http_fallback_5xx attempt=%d path=%s status=%d",
                attempt,
                path,
                resp.status_code,
            )
            continue

        try:
            data = resp.json()
        except Exception:
            data = {"_raw": resp.text}

        if resp.status_code >= 400:
            if resp.status_code == 429 and isinstance(data, dict):
                return _quota_exceeded_payload(data, path)
            return _envelope_error(
                "remote_http_error",
                f"upstream returned HTTP {resp.status_code}",
                extra={
                    "status_code": resp.status_code,
                    "detail": data,
                    "path": path,
                },
            )
        return data if isinstance(data, dict) else {"data": data}

    return _envelope_error(
        "remote_unreachable",
        "all retries exhausted",
        extra={
            "detail": (f"{type(last_exc).__name__}: {last_exc}" if last_exc else "unknown"),
            "path": path,
        },
    )


# --------------------------------------------------------------------------- #
# "remote-only" placeholder for the 56 tools we don't fallback-route yet
# --------------------------------------------------------------------------- #


def remote_only_error(tool_name: str, rest_path: str | None = None) -> dict[str, Any]:
    """§I-canonical envelope for tools that don't have a fallback path yet.

    Surfaces the REST URL inside the ``error`` block so the user can hit
    it directly. Re-uses the ``_envelope_error`` helper so the 6-key
    contract (``results / total / limit / offset / _billing_unit /
    _next_calls``) is honoured.
    """
    base = _api_base()
    rest_url = f"{base}{rest_path}" if rest_path else base
    msg = (
        f"Tool '{tool_name}' is not yet supported in MCP HTTP-fallback "
        f"mode. Local DB is empty (likely uvx install). Use the REST "
        f"API directly: {rest_url}"
    )
    return _envelope_error(
        "remote_only_via_REST_API",
        msg,
        extra={
            "tool": tool_name,
            "rest_api_base": base,
            "rest_url_hint": rest_url,
            "remediation": (
                "Either (a) install with full DB by cloning the repo, or "
                "(b) call the REST endpoint directly. Search-style tools "
                "(search_programs / get_program / search_case_studies / "
                "search_loan_programs / search_enforcement_cases / "
                "search_tax_incentives / search_certifications / "
                "list_open_programs / dd_profile_am / rule_engine_check) "
                "are wired and work transparently."
            ),
        },
    )


__all__ = [
    "detect_fallback_mode",
    "detect_fallback_mode_autonomath",
    "reset_fallback_mode",
    "http_call",
    "remote_only_error",
    "_envelope_error",
]
