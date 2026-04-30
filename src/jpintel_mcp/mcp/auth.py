"""Device flow credential management for the MCP client side.

Solves the "click link → Apple Pay → auto-continue" UX goal: zero config
editing, zero copy-paste. Used by the stdio MCP server to:

  1. Read the stored api_key from the OS keychain on startup
     (`ensure_authenticated()`). If none is present we run in anonymous
     mode — the user's first request uses the 50/month free quota.

  2. On HTTP 429 from the REST API (anon quota exceeded) the tool wrapper
     calls `handle_quota_exceeded()`, which:
       - POSTs /v1/device/authorize to mint a device_code + user_code
       - returns a user-visible instruction string pointing at the
         verification URL. The MCP tool response shows the URL + short
         user_code in Claude; the user clicks, pays on the /go page via
         Stripe Checkout, and the page calls /v1/device/complete.
       - Spawns a daemon thread that polls /v1/device/token every 5s.
         On success, the raw api_key is stashed in the OS keychain via
         `set_stored_token()`. The NEXT tool call picks it up via
         `get_stored_token()` — no background thread glue into the live
         MCP call.

  3. The MCP tool wrapper then re-tries or returns "still waiting, try
     again in a moment" — whichever fits. Per the spec we go with the
     re-run model (simpler, no thread/state juggling across tool calls).

Keychain naming: SERVICE="autonomath", KEY_NAME="api_key". One slot per
user across all AutonoMath MCP invocations on that machine.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import platform
import threading
import time
from typing import Any
from urllib import error as urllib_error
from urllib import request as urllib_request

logger = logging.getLogger("jpintel.mcp.auth")

# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #

SERVICE = "autonomath"
KEY_NAME = "api_key"

# REST API base URL. Override via env for local dev / staging.
# Trailing slash stripped in _api() so path concatenation is consistent.
_DEFAULT_API_BASE = "https://api.jpcite.com"


def _api_base() -> str:
    base = os.environ.get("AUTONOMATH_API_BASE") or _DEFAULT_API_BASE
    return base.rstrip("/")


# Device flow timeouts (seconds). Bounded so we never block the MCP
# tool wrapper for more than a few HTTP round-trips.
_DEVICE_AUTHORIZE_TIMEOUT = 10
_DEVICE_TOKEN_POLL_TIMEOUT = 5

# Max time the background poller runs before giving up. The REST side
# expires the device_code at 15 min; we track the same ceiling locally.
_MAX_POLL_SECONDS = 15 * 60

# Default poll interval (seconds). The REST side returns `interval=5`
# per RFC 8628; we honor the server's value when present.
_DEFAULT_POLL_INTERVAL = 5

# Client id used for /v1/device/authorize. Bare string by convention —
# the REST side doesn't enforce a registry, it just echoes it back.
_CLIENT_ID = "autonomath-mcp"


# --------------------------------------------------------------------------- #
# Keychain shim
# --------------------------------------------------------------------------- #
# Prefer the `keyring` library (system keychain: Keychain / Credential
# Manager / Secret Service). Fall back to a plaintext file under
# $HOME/.config/autonomath/token ONLY when keyring is absent or broken —
# some Linux CI boxes lack a running Secret Service daemon. We warn loudly
# when the fallback is used.


def _home_token_path() -> str:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(
        os.path.expanduser("~"), ".config"
    )
    return os.path.join(base, "autonomath", "token")


def _read_fallback_token() -> str | None:
    path = _home_token_path()
    try:
        with open(path, encoding="utf-8") as fh:
            tok = fh.read().strip()
            return tok or None
    except FileNotFoundError:
        return None
    except OSError:
        logger.warning("fallback_token_read_failed path=%s", path, exc_info=True)
        return None


def _write_fallback_token(token: str) -> None:
    path = _home_token_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        # 0o600 = user read/write only.
        with open(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as fh:
            fh.write(token)
    except OSError:
        logger.error("fallback_token_write_failed path=%s", path, exc_info=True)


def get_stored_token() -> str | None:
    """Return the saved api_key, or None if never set / unavailable."""
    try:
        import keyring  # type: ignore[import-not-found]

        tok = keyring.get_password(SERVICE, KEY_NAME)
        if tok:
            return tok
    except Exception:
        logger.warning("keyring_read_failed; trying file fallback", exc_info=True)
    return _read_fallback_token()


def set_stored_token(token: str) -> None:
    """Persist the api_key in the system keychain (preferred) or file."""
    try:
        import keyring  # type: ignore[import-not-found]

        keyring.set_password(SERVICE, KEY_NAME, token)
        return
    except Exception:
        logger.warning(
            "keyring_write_failed; using plaintext fallback at %s",
            _home_token_path(),
            exc_info=True,
        )
    _write_fallback_token(token)


def clear_stored_token() -> None:
    """Remove the stored token (both keychain and fallback). Best-effort."""
    try:
        import keyring  # type: ignore[import-not-found]

        # Nothing to delete is fine; also tolerate keyring backend errors
        # (CI boxes without Secret Service, etc.).
        with contextlib.suppress(Exception):
            keyring.delete_password(SERVICE, KEY_NAME)
    except Exception:
        pass
    try:
        os.remove(_home_token_path())
    except FileNotFoundError:
        pass
    except OSError:
        logger.warning("fallback_token_delete_failed", exc_info=True)


# --------------------------------------------------------------------------- #
# HTTP helpers (stdlib only — no extra dependency for the MCP process)
# --------------------------------------------------------------------------- #


def _post_json(url: str, payload: dict[str, Any], timeout: float) -> tuple[int, dict[str, Any]]:
    """POST JSON, return (status_code, parsed body). Never raises for
    4xx/5xx — callers handle error payloads. Raises on network errors.
    """
    body = json.dumps(payload).encode("utf-8")
    req = urllib_request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": _client_user_agent(),
        },
    )
    try:
        with urllib_request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return resp.status, _loads_safe(raw)
    except urllib_error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
        return exc.code, _loads_safe(raw)


def _loads_safe(raw: str) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {"_raw": data}
    except json.JSONDecodeError:
        return {"_raw": raw}


def _client_user_agent() -> str:
    # Privacy-preserving UA: platform family + a short hostname hash equivalent
    # (just system() / release()). No hostname, no username.
    try:
        sysname = platform.system()
        release = platform.release()
    except Exception:
        sysname, release = "unknown", "unknown"
    return f"autonomath-mcp/device-flow ({sysname} {release})"


# --------------------------------------------------------------------------- #
# Device flow client
# --------------------------------------------------------------------------- #


def _authorize() -> dict[str, Any] | None:
    """POST /v1/device/authorize → device_code + user_code + interval."""
    url = f"{_api_base()}/v1/device/authorize"
    try:
        code, body = _post_json(
            url,
            {"client_id": _CLIENT_ID, "scope": "api:read api:metered"},
            timeout=_DEVICE_AUTHORIZE_TIMEOUT,
        )
    except (urllib_error.URLError, OSError) as exc:
        logger.warning("device_authorize_network_failed err=%s", exc)
        return None
    if code != 200:
        logger.warning("device_authorize_http_status status=%d body=%s", code, body)
        return None
    # Minimal shape check — absence of device_code means the server is off spec.
    if "device_code" not in body:
        logger.warning("device_authorize_bad_payload body=%s", body)
        return None
    return body


def _poll_token(device_code: str, interval: int) -> None:
    """Background thread: poll /v1/device/token until success / expiry.

    On success, stores the access_token via set_stored_token(). Never
    raises — logs and exits silently on any failure (the user can always
    re-run the auth from the MCP's next quota hit).
    """
    url = f"{_api_base()}/v1/device/token"
    payload = {
        "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
        "device_code": device_code,
        "client_id": _CLIENT_ID,
    }
    deadline = time.time() + _MAX_POLL_SECONDS
    cur_interval = max(1, int(interval or _DEFAULT_POLL_INTERVAL))

    while time.time() < deadline:
        try:
            code, body = _post_json(url, payload, timeout=_DEVICE_TOKEN_POLL_TIMEOUT)
        except (urllib_error.URLError, OSError) as exc:
            logger.warning("device_token_network_failed err=%s; retrying", exc)
            time.sleep(cur_interval)
            continue

        if code == 200 and "access_token" in body:
            token = str(body["access_token"])
            set_stored_token(token)
            logger.info(
                "device_flow_token_stored prefix=%s",
                token[:12] if token else "-",
            )
            return

        # RFC 8628 error payload: {"error": "<code>"}. FastAPI wraps
        # HTTPException.detail as {"detail": {"error": ...}} — handle both.
        err = _extract_error_code(body)
        if err == "authorization_pending":
            time.sleep(cur_interval)
            continue
        if err == "slow_down":
            cur_interval += 5
            time.sleep(cur_interval)
            continue
        if err in ("expired_token", "access_denied", "invalid_grant", "unsupported_grant_type"):
            logger.info("device_flow_terminal err=%s", err)
            return
        # Unknown error → back off conservatively and keep trying until
        # deadline; a transient 500 shouldn't abort the whole flow.
        logger.warning("device_token_unknown_err status=%d body=%s", code, body)
        time.sleep(cur_interval)

    logger.info("device_flow_poll_deadline_reached device_code_prefix=%s", device_code[:12])


def _extract_error_code(body: dict[str, Any]) -> str | None:
    if not body:
        return None
    err = body.get("error")
    if isinstance(err, str):
        return err
    detail = body.get("detail")
    if isinstance(detail, dict) and isinstance(detail.get("error"), str):
        return str(detail["error"])
    return None


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #


def ensure_authenticated() -> None:
    """Call at MCP startup. Currently a no-op if no token is present —
    anonymous mode is legal (50 req/month). We log the state so the
    operator can sanity-check whether the keychain handoff is working.
    """
    token = get_stored_token()
    if token:
        logger.info("mcp_auth_ready prefix=%s", token[:12])
    else:
        logger.info("mcp_auth_anonymous — no token stored; anon 50/month applies")


def handle_quota_exceeded() -> str:
    """Call on 429 from the REST API.

    Synchronous behaviour (per spec: "re-run model"):
      * POST /v1/device/authorize.
      * Spawn the poller as a daemon thread.
      * Return an instructional Japanese + English message for the
        MCP tool to surface to Claude. The user clicks the URL, pays,
        and re-asks their question in Claude. On the next tool call,
        get_stored_token() returns the freshly-stored token and the
        request succeeds.

    If authorize fails (network / 5xx) we return a fallback message so
    the tool call doesn't disappear into the void.
    """
    auth = _authorize()
    if not auth:
        return (
            "無料枠に到達しました。自動認証サーバーに接続できませんでした — "
            f"{_api_base()} への接続を確認し、しばらく待ってからもう一度お試しください。"
            "\n\n"
            "Free quota exceeded and automatic authentication server is "
            "unreachable. Check connectivity and retry in a moment."
        )

    device_code = str(auth.get("device_code", ""))
    user_code = str(auth.get("user_code", ""))
    verification_uri_complete = str(auth.get("verification_uri_complete", ""))
    verification_uri = str(auth.get("verification_uri", ""))
    interval = int(auth.get("interval", _DEFAULT_POLL_INTERVAL))
    expires_in = int(auth.get("expires_in", _MAX_POLL_SECONDS))

    # Fire the poller. daemon=True so it never blocks MCP shutdown.
    t = threading.Thread(
        target=_poll_token,
        args=(device_code, interval),
        daemon=True,
        name="autonomath-device-poller",
    )
    t.start()

    minutes = max(1, expires_in // 60)
    return (
        "無料枠 (50 req/月) に到達しました。\n\n"
        f"続けるには次の URL を開いて Apple Pay / Google Pay / カードでお支払いください "
        f"(約 {minutes} 分以内):\n\n"
        f"  {verification_uri_complete or verification_uri}\n\n"
        f"確認コード (URL が使えないときに手入力): {user_code}\n\n"
        "決済が完了したら、もう一度同じ質問を Claude にしてください — "
        "以降の課金 (¥3/req 税別) は自動的に紐付きます。設定ファイルの編集や "
        "再起動は不要です。\n\n"
        "---\n\n"
        f"Free quota exhausted (50 req/month). Open {verification_uri_complete or verification_uri} "
        f"to pay via Apple Pay / Google Pay / card (within ~{minutes} min). "
        f"Recovery code: {user_code}. Re-ask your question after payment — "
        "the MCP server picks up the new credentials automatically. No config "
        "editing or restart required."
    )


__all__ = [
    "SERVICE",
    "KEY_NAME",
    "clear_stored_token",
    "ensure_authenticated",
    "get_stored_token",
    "handle_quota_exceeded",
    "set_stored_token",
]
