"""Per-IP MONTHLY rate limit for anonymous callers (no X-API-Key).

Free tier is 50 req/month per IP (revised 2026-04-23 from daily 100).
Bucket key stored in `anon_rate_limit.date` as YYYY-MM-01 in JST — first
day of the JST calendar month. Reset occurs at JST 月初 00:00.

Why a router-level dependency (not global middleware): a whitelist matters
here — /healthz, /readyz, /v1/billing/webhook (Stripe), the subscribers
unsubscribe link, and static dashboard routes must never burn anon quota.
A router-level dep attached only to the anonymous-accepting routers makes
that whitelist explicit by absence — much safer than a middleware that
pattern-matches the URL path and drifts as routes are added.

This dep also runs *after* _RequestContextMiddleware because FastAPI
resolves dependencies inside the handler call, which is after the outer
middleware stack — so x-request-id is always bound in structlog context
by the time we log a 429.

Fail-open posture: if the DB write fails we log and let the request through.
A broken rate limiter must not become a self-DoS vector; over-serving is
strictly better than 500s on every anon call.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import sqlite3
from datetime import UTC, datetime, timedelta, timezone

from fastapi import Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse

from jpintel_mcp.config import settings

# Public upgrade landing — single source of truth for the 429 body, the
# AnonQuotaHeaderMiddleware response header (X-Anon-Upgrade-Url), and any
# future surface that wants to point an LLM caller at the conversion path.
# `?from=429` lets the landing page distinguish friction-driven hits from
# organic traffic for funnel analysis.
#
# Both `UPGRADE_URL_BASE` (non-429 anon) and `UPGRADE_URL_FROM_429` (429
# envelope) now point at `/upgrade.html` — the plain landing page that
# explains the 50 req/月 cap, points at `pricing.html#api-paid`, and
# lists the `/go` device-flow as a tertiary "if you actually have a
# device code" option. Earlier versions sent non-429 anon callers to
# `/go` directly, but `/go.html` is the device-flow activation page that
# REQUIRES a `user_code` (e.g. ABCD-1234) — anon callers without a code
# bounced. /go/upgrade fix landed the redirect via `site/_redirects`
# (`/go/upgrade → /upgrade.html`); pointing the header straight at
# `/upgrade.html` skips the redirect hop entirely.
UPGRADE_URL_BASE = "https://jpcite.com/upgrade.html"
UPGRADE_URL_FROM_429 = "https://jpcite.com/upgrade.html?from=429"
CTA_TEXT_JA = "API key を発行して制限を解除"
CTA_TEXT_EN = "Get an API key to remove the limit"
# Conversion-pathway audit 2026-04-29: alongside the paid upgrade path we
# also surface the email-only trial. An evaluator who hit the anon cap and
# isn't ready to drop a card has a one-click alternative that captures their
# email so we can remarket / rescue / learn (vs the prior 100% silent bounce).
# The homepage form is the entry point for the trial; the anchor #trial
# scrolls them straight to it.
TRIAL_SIGNUP_URL_FROM_429 = "https://jpcite.com/?from=429#trial"
TRIAL_CTA_TEXT_JA = "カードなしで試す (14 日 / 200 req)"
TRIAL_CTA_TEXT_EN = "Try without a card (14 days / 200 requests)"


class _AnonRateLimitExceeded(HTTPException):
    """429 wrapper that serialises its detail dict at the TOP level, not
    nested under the FastAPI-default `{"detail": ...}` envelope.

    FastAPI renders HTTPException.detail via `{"detail": detail}`, which
    would produce `{"detail": {"detail": "...", ...}}` for a dict detail.
    The spec wants the fields at the root, so we carry the full body in
    `.body_dict` and let the exception handler emit it directly.
    """

    def __init__(self, body: dict, headers: dict[str, str]) -> None:
        super().__init__(
            status.HTTP_429_TOO_MANY_REQUESTS,
            detail=body["detail"],
            headers=headers,
        )
        self.body_dict = body


def anon_rate_limit_exception_handler(
    _request: Request, exc: Exception
) -> JSONResponse:
    assert isinstance(exc, _AnonRateLimitExceeded)  # guaranteed by add_exception_handler
    return JSONResponse(
        status_code=exc.status_code,
        content=exc.body_dict,
        headers=exc.headers or {},
    )

_log = logging.getLogger("jpintel.anon_limit")

# JST = UTC+9, fixed offset (no DST). datetime.timezone is enough — avoids
# a zoneinfo import and tzdata dep.
_JST = timezone(timedelta(hours=9))


def _jst_month_bucket(now: datetime | None = None) -> str:
    """Return YYYY-MM-01 for the current JST calendar month.

    Stored in `anon_rate_limit.date` (TEXT column) as a 10-char ISO date.
    Using first-of-month (YYYY-MM-01) rather than YYYY-MM keeps SQLite's
    built-in `date()` comparisons usable for the retention cleanup.
    """
    now = now or datetime.now(_JST)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    now_jst = now.astimezone(_JST)
    return now_jst.replace(day=1).strftime("%Y-%m-%d")


def _next_jst_month_start(now_jst: datetime) -> datetime:
    """Return the first instant (00:00 JST) of the next calendar month."""
    if now_jst.month == 12:
        return now_jst.replace(
            year=now_jst.year + 1, month=1, day=1,
            hour=0, minute=0, second=0, microsecond=0,
        )
    return now_jst.replace(
        month=now_jst.month + 1, day=1,
        hour=0, minute=0, second=0, microsecond=0,
    )


def _seconds_until_jst_month_start(now: datetime | None = None) -> int:
    """Seconds remaining until the next JST 月初 00:00 (quota reset)."""
    now = now or datetime.now(_JST)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    now_jst = now.astimezone(_JST)
    next_month = _next_jst_month_start(now_jst)
    return max(1, int((next_month - now_jst).total_seconds()))


def _jst_next_month_iso(now: datetime | None = None) -> str:
    """ISO8601 timestamp of the next JST 月初 (for the response body)."""
    now = now or datetime.now(_JST)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    now_jst = now.astimezone(_JST)
    return _next_jst_month_start(now_jst).isoformat()


def _client_ip(request: Request) -> str:
    """Extract the caller's IP.

    Priority: Fly-Client-IP (Fly.io's trusted proxy header) > X-Forwarded-For
    (first hop) > request.client.host. Fall back to 'unknown' so we still
    rate-limit a misconfigured deployment rather than skipping entirely.
    """
    fly_ip = request.headers.get("fly-client-ip")
    if fly_ip:
        return fly_ip.strip()
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"


def _normalize_ip_to_prefix(ip: str) -> str:
    """Reduce an IP to its rate-limit aggregation unit.

    - IPv4 -> full /32 (the address itself; one user typically == one /32).
    - IPv6 -> first 64 bits (/64). An ISP hands a single customer a whole
      /64; rate-limiting on the full /128 would trivially be bypassed by
      cycling through privacy extensions. Normalising to /64 aligns with
      how real-world abuse shows up.

    Returns the original string if it is neither v4 nor v6 — we let the
    HMAC hash whatever we got so the pipeline doesn't fail on odd inputs
    like 'unknown' or an IPv6 scope suffix we couldn't parse.
    """
    import ipaddress

    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return ip
    if isinstance(addr, ipaddress.IPv4Address):
        return str(addr)
    # IPv6 -> /64 network address, canonicalised.
    try:
        net = ipaddress.IPv6Network((addr, 64), strict=False)
        return str(net.network_address)
    except ValueError:
        return ip


# ---------------------------------------------------------------------------
# Behavioural fingerprint (P2.6.2, 2026-04-25)
# ---------------------------------------------------------------------------
#
# IP-only rate limiting (single axis: /32 v4, /64 v6, fail-open) leaks
# silently when:
#   * a single LLM caller rotates through CGNAT NAT pool (mobile carriers,
#     residential proxies, Tor exit nodes share /64 ranges)
#   * an attacker walks a /64 by cycling SLAAC privacy extensions
#   * a small VPN provider hands distinct /32s to the same logical user
#     across one session
#
# Goal is NOT bypass-proof — the spec is "silent leak ≤10%". We compose
# 4 cheap, header-derived axes alongside the IP into a single HMAC. Two
# requests with the same fingerprint but different IPs share a bucket;
# two requests with the same IP but different fingerprints stay separate
# (so a coffee-shop NAT with 5 distinct laptops still gets 5×50/月 not
# the limit collapsed to one).
#
# The four axes:
#   1. UA-class — User-Agent normalised to a stable class string
#      ("claude-desktop", "chatgpt", "cursor", "anthropic-sdk", "openai-sdk",
#      "curl", "browser:firefox", "browser:chrome", "unknown"). Rotating
#      the version suffix ("Cursor/1.2.3" → "Cursor/1.2.4") MUST NOT reset
#      the bucket — that's the most common "I'll just bump UA" bypass.
#   2. Accept-Language first tag (case-folded "ja", "en-us", etc).
#      Rotating between "ja" and "en" between requests is rare for a
#      legit caller; cycling here to evade limits is itself signal.
#   3. HTTP protocol family — "h2" vs "h1.1" vs "h3". Most browsers
#      and SDKs pick one and stick with it for the connection's lifetime.
#   4. JA3 hash — Cloudflare adds `cf-ja3-hash` upstream when CF MTLS
#      is on. JA3 is a TLS ClientHello fingerprint that survives both
#      IP rotation and UA spoofing. When absent (direct-to-Fly path,
#      local dev, tests), we fall back to the empty string and the
#      remaining 3 axes still compose a usable signal.
#
# Each axis falls back to "?" when missing. We don't gate the request
# on header presence — the fingerprint is purely additive.

# UA-class extraction. Order matters: more specific patterns first so
# "Claude Desktop" doesn't fall through to a generic browser bucket.
# Keep this list short and stable — every entry is a logical user
# population, not a UA string we want to enumerate.
_UA_PATTERNS: tuple[tuple[str, str], ...] = (
    # LLM clients (highest priority — explicit MCP / chat clients).
    ("claude-desktop", "claude desktop"),
    ("claude-code", "claude-code"),
    ("chatgpt", "chatgpt"),
    ("cursor", "cursor"),
    ("zed", "zed-editor"),
    ("cline", "cline"),
    ("continue", "continue.dev"),
    # Official SDKs (LLM provider HTTP signatures).
    ("anthropic-sdk", "anthropic"),
    ("openai-sdk", "openai"),
    ("google-genai", "google-genai"),
    ("mcp-client", "mcp/"),
    # Generic CLI / scripting.
    ("curl", "curl/"),
    ("wget", "wget/"),
    ("httpx", "python-httpx"),
    ("requests", "python-requests"),
    ("axios", "axios/"),
    # Browsers (lowest priority — fall through after specific clients).
    ("browser:firefox", "firefox/"),
    ("browser:safari", "safari/"),
    ("browser:edge", "edg/"),
    ("browser:chrome", "chrome/"),
)


def _classify_user_agent(ua: str | None) -> str:
    """Map a User-Agent string to a stable class label.

    The output deliberately strips version numbers — "Cursor/1.2.3" and
    "Cursor/1.2.4" both return "cursor" so a UA-rotation bypass attempt
    does NOT reset the bucket. Empty / missing UA returns "unknown",
    which itself is a signal (legitimate clients almost always send one).
    """
    if not ua:
        return "unknown"
    ua_low = ua.lower()
    for label, needle in _UA_PATTERNS:
        if needle in ua_low:
            return label
    return "other"


def _normalise_accept_language(al: str | None) -> str:
    """Return the first language tag in Accept-Language, lowercased.

    "ja,en-US;q=0.7,en;q=0.3" -> "ja". Missing header returns "?".
    Quality factor / fallback chain is discarded — we only care about
    the primary preference because it's the one users almost never change
    mid-session.
    """
    if not al:
        return "?"
    first = al.split(",", 1)[0].strip().lower()
    # Strip quality factor if it leaked into the first tag (malformed).
    first = first.split(";", 1)[0].strip()
    return first or "?"


def _http_version_label(request: Request) -> str:
    """Return a coarse HTTP protocol label: 'h2', 'h1.1', 'h3', or '?'.

    ASGI exposes the negotiated version on `request.scope['http_version']`
    as a string ('1.1', '2', '3'). We map these to short stable labels
    so the fingerprint string stays compact.
    """
    try:
        v = str(request.scope.get("http_version") or "").strip()
    except Exception:  # pragma: no cover — scope always present in ASGI
        return "?"
    if v == "2" or v == "2.0":
        return "h2"
    if v == "1.1":
        return "h1.1"
    if v == "3" or v == "3.0":
        return "h3"
    return v or "?"


def _ja3_hash(request: Request) -> str:
    """Return Cloudflare's TLS ClientHello (JA3) hash, or '?' when absent.

    Cloudflare sets `cf-ja3-hash` on requests proxied through them when
    the BotFight / TLS-fingerprint feature is on. We never compute JA3
    ourselves — Fly's edge does not expose the ClientHello bytes. When
    the header is absent (direct-to-Fly tests, local dev, customers
    bypassing Cloudflare), we fall through cleanly with "?".
    """
    h = request.headers.get("cf-ja3-hash")
    if not h:
        return "?"
    h = h.strip()
    # Cap absurd values defensively — JA3 is always 32 hex chars.
    if len(h) > 64:
        return h[:64]
    return h.lower()


def _fingerprint_components(request: Request) -> tuple[str, str, str, str]:
    """Return the 4-axis fingerprint tuple.

    Exposed as a separate function so tests can assert each axis in
    isolation rather than reverse-engineering the joined string.
    """
    ua_class = _classify_user_agent(request.headers.get("user-agent"))
    lang = _normalise_accept_language(request.headers.get("accept-language"))
    http_v = _http_version_label(request)
    ja3 = _ja3_hash(request)
    return ua_class, lang, http_v, ja3


def _fingerprint_string(request: Request) -> str:
    """Join the 4 axes into a stable canonical string for hashing.

    Pipe separator chosen because none of the axis values can contain
    one (UA-class is from a closed enum; lang is RFC 5646 with no '|';
    http_v is a literal short string; JA3 is hex). Position-stable so
    a missing axis doesn't shift the others — every component is always
    present (with "?" as the explicit absent marker).
    """
    ua, lang, http_v, ja3 = _fingerprint_components(request)
    return f"{ua}|{lang}|{http_v}|{ja3}"


def hash_ip(ip: str, request: Request | None = None) -> str:
    """HMAC-SHA256(normalized_ip [+ fingerprint], api_key_salt). Hex digest.

    `request` is optional for backward compatibility — callers that pass
    None get the legacy IP-only digest (used by tests asserting raw IP
    hash determinism). Production paths pass the request so the IP is
    composed with the 4-axis behavioural fingerprint, multiplying the
    bucket key space by ~UA_class × lang × http_v × JA3 ≈ 100s of
    distinct buckets per /32 — enough to make CGNAT rotation costly
    without breaking legitimate shared-NAT users (each NAT'd device
    has its own UA/lang fingerprint).

    Schema-stable: the `anon_rate_limit.ip_hash` column still holds a
    64-char hex digest — we just include more entropy in what we hash.
    No migration needed.
    """
    normalized = _normalize_ip_to_prefix(ip)
    if request is not None:
        composed = f"{normalized}#{_fingerprint_string(request)}"
    else:
        composed = normalized
    return hmac.new(
        settings.api_key_salt.encode("utf-8"),
        composed.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _try_increment(
    conn: sqlite3.Connection, ip_hash: str, month_bucket: str, now_iso: str
) -> int:
    """Atomically increment (or insert) the month row, return the NEW count.

    `month_bucket` is YYYY-MM-01 (first-of-month JST) — stored in the legacy
    `date` column whose name predates the 2026-04-23 daily→monthly switch.
    Two-statement pattern: INSERT OR IGNORE seeds the row with call_count=0
    if absent; UPDATE then bumps it to the new value. Both statements are
    indexed on (ip_hash, date) via the primary key, so no table-level lock
    contention beyond the WAL write. SQLite's connection is serialised
    within a process; no BEGIN needed.
    """
    conn.execute(
        "INSERT OR IGNORE INTO anon_rate_limit(ip_hash, date, call_count, first_seen, last_seen) "
        "VALUES (?, ?, 0, ?, ?)",
        (ip_hash, month_bucket, now_iso, now_iso),
    )
    conn.execute(
        "UPDATE anon_rate_limit SET call_count = call_count + 1, last_seen = ? "
        "WHERE ip_hash = ? AND date = ?",
        (now_iso, ip_hash, month_bucket),
    )
    (new_count,) = conn.execute(
        "SELECT call_count FROM anon_rate_limit WHERE ip_hash = ? AND date = ?",
        (ip_hash, month_bucket),
    ).fetchone()
    return int(new_count)


async def enforce_anon_ip_limit(request: Request) -> None:
    """Router-level dep: reject anon callers over the monthly per-IP quota.

    Bypasses: presence of X-API-Key / Authorization: Bearer header. We
    intentionally do NOT validate the key here — that happens in
    require_key() on the same request. The purpose of this dep is just
    "does the caller claim to be authed?". A bogus key reaches require_key
    and 401s there; the anon bucket is untouched for that request.
    """
    if not settings.anon_rate_limit_enabled:
        return

    # Claimed-auth bypass. Anon = neither header present.
    if request.headers.get("x-api-key"):
        return
    auth = request.headers.get("authorization")
    if auth and auth.split(None, 1)[0].lower() == "bearer":
        return

    # Independently open a connection so we do NOT share the DbDep cursor
    # used by the actual endpoint — keeps ordering simple and avoids the
    # dep-resolution injection tangle. Still uses the same config path.
    from jpintel_mcp.db.session import connect

    try:
        anon_conn = connect()
    except Exception:  # pragma: no cover — connect() is extremely reliable
        _log.exception("anon_rate_limit: connect() failed; failing open")
        return

    limit = settings.anon_rate_limit_per_month
    ip = _client_ip(request)
    # Fingerprint-aware hash: combines normalized IP with UA-class +
    # Accept-Language + HTTP version + JA3 so CGNAT / VPN rotation that
    # shares one fingerprint still aggregates to one bucket.
    ip_h = hash_ip(ip, request)
    month_bucket = _jst_month_bucket()
    now_iso = datetime.now(UTC).isoformat()

    new_count: int | None = None
    try:
        new_count = _try_increment(anon_conn, ip_h, month_bucket, now_iso)
    except sqlite3.Error:
        _log.exception(
            "anon_rate_limit: DB error on increment; failing open ip_hash=%s month=%s",
            ip_h[:12],
            month_bucket,
        )
    finally:
        import contextlib

        with contextlib.suppress(Exception):
            anon_conn.close()

    # Fail-open: if the write blew up, let the request through.
    if new_count is None:
        return

    if new_count > limit:
        resets_at = _jst_next_month_iso()
        retry_after = _seconds_until_jst_month_start()
        # Stash quota state on request.state so the 429 path's headers
        # (set inside _AnonRateLimitExceeded.headers) and any future
        # observer get the same remaining=0 view that the middleware
        # would have computed.
        try:
            request.state.anon_quota = {
                "remaining": 0,
                "limit": limit,
                "reset_at_jst": resets_at,
            }
        except Exception:  # pragma: no cover — request.state always present
            pass
        raise _AnonRateLimitExceeded(
            body={
                "detail": (
                    f"匿名リクエスト上限 ({limit}/月) に達しました。"
                    "X-API-Key ヘッダを設定するか、JST 翌月 1 日 00:00 にリセットされます。"
                ),
                "detail_en": (
                    f"Anonymous rate limit exceeded ({limit}/month). "
                    "Provide X-API-Key or wait for reset at 00:00 JST on the 1st."
                ),
                "retry_after": retry_after,
                "reset_at_jst": resets_at,
                "limit": limit,
                "resets_at": resets_at,
                # S3 friction removal: every 429 body carries a direct
                # upgrade link + bilingual CTA copy. An LLM caller that
                # ignores headers still surfaces the conversion path to
                # the human in the loop on the very first refusal.
                "upgrade_url": UPGRADE_URL_FROM_429,
                "cta_text_ja": CTA_TEXT_JA,
                "cta_text_en": CTA_TEXT_EN,
                # Conversion-pathway audit 2026-04-29: also surface the
                # email-only trial path. An evaluator who isn't ready to
                # drop a card has a one-click alternative that captures
                # their email so we can remarket / rescue / learn —
                # 100% of anon bouncers leave no contact info today.
                "trial_signup_url": TRIAL_SIGNUP_URL_FROM_429,
                "trial_cta_text_ja": TRIAL_CTA_TEXT_JA,
                "trial_cta_text_en": TRIAL_CTA_TEXT_EN,
                "trial_terms": {
                    "duration_days": 14,
                    "request_cap": 200,
                    "card_required": False,
                },
            },
            headers={
                "Retry-After": str(retry_after),
                # Mirror the body fields onto headers so HTTP-only clients
                # (curl scripts, monitoring) still see the upgrade hint.
                "X-Anon-Quota-Remaining": "0",
                "X-Anon-Quota-Reset": resets_at,
                "X-Anon-Upgrade-Url": UPGRADE_URL_FROM_429,
                "X-Anon-Trial-Url": TRIAL_SIGNUP_URL_FROM_429,
            },
        )

    # Successful (under-quota) anon path — record state for the response
    # header middleware. `remaining` is the post-increment count, so
    # remaining = limit - new_count. Clamp at 0 to avoid negative values
    # for the boundary call that crossed the threshold but still got a
    # 200 (limit exactly hit).
    try:
        request.state.anon_quota = {
            "remaining": max(0, limit - new_count),
            "limit": limit,
            "reset_at_jst": _jst_next_month_iso(),
        }
    except Exception:  # pragma: no cover
        pass


# Router-level dep alias — callers wire this as:
#     app.include_router(programs_router, dependencies=[AnonIpLimitDep])
AnonIpLimitDep = Depends(enforce_anon_ip_limit)


__all__ = [
    "AnonIpLimitDep",
    "CTA_TEXT_EN",
    "CTA_TEXT_JA",
    "TRIAL_CTA_TEXT_EN",
    "TRIAL_CTA_TEXT_JA",
    "TRIAL_SIGNUP_URL_FROM_429",
    "UPGRADE_URL_BASE",
    "UPGRADE_URL_FROM_429",
    "anon_rate_limit_exception_handler",
    "enforce_anon_ip_limit",
    "hash_ip",
    "_AnonRateLimitExceeded",
    "_classify_user_agent",
    "_fingerprint_components",
    "_fingerprint_string",
]
