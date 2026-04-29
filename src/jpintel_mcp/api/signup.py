"""Email-only trial signup (POST /v1/signup, GET /v1/signup/verify).

Conversion-pathway audit, 2026-04-29
------------------------------------
The only path to a real API key today is Stripe Checkout (card required).
That loses dev evaluators who want to try N free trial calls before
committing — the OpenAI / Anthropic / Stripe norm is "email + verification
→ time-boxed trial → in-app prompt to add a card". 100% of anonymous
bouncers leave no contact info today; we cannot remarket, rescue, or
learn why they left.

This module implements that flow as a fully self-serve, zero-touch
mechanism (memory: `feedback_zero_touch_solo`):

    1.  POST /v1/signup            { "email": "..." }
        -> persists a trial_signups row (unverified)
        -> mails a magic-link to the address
        -> returns 202 Accepted

    2.  GET  /v1/signup/verify     ?token=<HMAC>&email=<addr>
        -> verifies the token (constant-time HMAC compare)
        -> issues a tier='trial' api_keys row via
           billing.keys.issue_trial_key (14d, 200 reqs hard cap, no card)
        -> redirects to /trial.html with the raw key in the URL fragment
           (#api_key=...) so the static page can reveal it once

    3.  Daily cron `scripts/cron/expire_trials.py` revokes any trial key
        past 14 days OR over 200 requests, fires a "your trial ended"
        mail, and the user can re-sign up via Stripe Checkout for a paid
        key (existing path) or fall back to anonymous 50/月 per-IP free.

Constraints (from the audit + memory):
    * Solo + zero-touch: NO operator approval. Email is the only gate.
    * No password — magic link is the auth.
    * 1 trial per email LIFETIME. Re-signup → 409 + Stripe Checkout link.
    * 1 signup per IP per 24h to prevent abuse-by-walking.
    * Email dedup is gmail-aware (dot/+ collapsed) + lowercased.
    * §52 disclaimer in the welcome email AND on trial.html.
    * ¥3/req structure preserved post-trial. Trial is NOT a "Free tier".
    * Stripe NOT involved during trial.

Why a separate router (not a method on me_router):
    /v1/signup is anonymous-accessible; /v1/me requires a session cookie
    bound to an existing api_key. Mounting under me_router would force a
    weird "anonymous me" path. A dedicated router with its own router-level
    deps is cleaner and matches the appi_disclosure pattern.
"""
from __future__ import annotations

import contextlib
import hashlib
import hmac
import logging
import re
import sqlite3
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, EmailStr, Field

from jpintel_mcp.api.deps import DbDep
from jpintel_mcp.config import settings

logger = logging.getLogger("jpintel.signup")

router = APIRouter(tags=["signup"])

# ---------------------------------------------------------------------------
# Trial-window constants. Defaults match the conversion-pathway audit; if a
# future reroll wants to tighten/loosen, change here only.
# ---------------------------------------------------------------------------

TRIAL_DURATION_DAYS = 14
TRIAL_REQUEST_CAP = 200
# Magic-link validity. Distinct from the trial's 14-day life — the LINK
# itself goes stale after 24h so a leaked email screenshot can't be
# replayed a week later to issue a key against an unverified address.
MAGIC_LINK_TTL_HOURS = 24
# Per-IP signup gate. 1 signup per IP per 24h is enough for a real evaluator
# (they'll rarely sign up twice) but starves a script walking the +tag
# namespace. Email-uniqueness is the harder gate — this is just a velocity
# brake to keep cost low.
PER_IP_WINDOW_HOURS = 24
PER_IP_LIMIT = 1

# Public landing page that reveals the issued raw API key. Same-origin to
# the API; the redirect carries the key in the URL fragment (#api_key=...)
# so it never reaches our access logs (browsers don't send fragments to
# the server).
TRIAL_LANDING_URL = "https://zeimu-kaikei.ai/trial.html"
# Shown in 409 response when the address has already used its lifetime
# trial — points at the existing paid-tier checkout path. Bug 3 fix
# (2026-04-29 funnel audit): previously pointed at /dashboard.html which
# is auth-gated, so an evaluator without a session cookie hit a wall.
# /pricing.html is anonymous-accessible and the ?from=trial query lets
# the trial-attribution banner fire on landing; the #api-paid hash
# positions the user at the paid-API card directly.
PAID_CHECKOUT_URL = "https://zeimu-kaikei.ai/pricing.html?from=trial#api-paid"


# ---------------------------------------------------------------------------
# Email normalisation — the dedup key
# ---------------------------------------------------------------------------


_GMAIL_HOSTS = {"gmail.com", "googlemail.com"}
_PLUS_TAG_RE = re.compile(r"\+[^@]*$")


def _normalize_email(addr: str) -> str:
    """Return the lifetime-dedup form of `addr`.

    Rules:
        * lowercase the whole address
        * strip a +tag suffix from the local part ("foo+bar@x" -> "foo@x")
        * for gmail.com / googlemail.com, also collapse all dots in the
          local part ("f.o.o@gmail.com" -> "foo@gmail.com")
        * googlemail.com -> gmail.com (Google treats them as the same
          mailbox)

    These three rules together close the most common abuse vectors:
    "+anything" namespace walking and the gmail-dot trick. Other domains
    might also alias dots, but we don't generalise — false positives
    (rejecting two distinct addresses that happen to map together) are
    worse than false negatives (a determined attacker who rents 100
    distinct domains can still claim 100 trials, but at that point the
    economics don't work).
    """
    s = addr.strip().lower()
    if "@" not in s:
        return s
    local, _, domain = s.partition("@")
    # Strip plus-tag (everything from the first '+' to the '@').
    local = _PLUS_TAG_RE.sub("", local)
    if domain == "googlemail.com":
        domain = "gmail.com"
    if domain in _GMAIL_HOSTS:
        local = local.replace(".", "")
    return f"{local}@{domain}"


# ---------------------------------------------------------------------------
# Magic-link token (HMAC, no DB read needed at verify time beyond row lookup)
# ---------------------------------------------------------------------------


def _make_token(email_normalized: str, created_at_iso: str) -> str:
    """HMAC(api_key_salt, email_normalized || created_at_iso). Hex digest.

    Same recipe as api/subscribers.make_unsubscribe_token: a single salt,
    a stable input, a SHA-256 HMAC. The created_at_iso component means:
        * Tokens are bound to the specific signup attempt (a re-signup —
          which currently 409s anyway — would not collide).
        * `_verify_token(email, token)` recomputes from the row's stored
          created_at and constant-time compares. No raw token in DB; we
          store only `token_hash` for forensic logging (sha256 of the
          token itself), so a DB exfil can't replay magic links.
    """
    msg = f"{email_normalized}|{created_at_iso}".encode()
    return hmac.new(
        settings.api_key_salt.encode(), msg, hashlib.sha256
    ).hexdigest()


def _hash_token(token: str) -> str:
    """sha256(token) — what we persist on trial_signups.token_hash.

    NEVER store the raw token. The verify path computes the expected
    token from the row's email_normalized + created_at and constant-time
    compares the hash of the supplied token against this stored hash.
    Defense in depth: even an HMAC collision (cryptographically
    implausible) cannot replay if the stored hash doesn't match.
    """
    return hashlib.sha256(token.encode()).hexdigest()


def _client_ip(request: Request) -> str:
    """Extract the caller's IP. Mirror of api.anon_limit._client_ip."""
    fly_ip = request.headers.get("fly-client-ip")
    if fly_ip:
        return fly_ip.strip()
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"


def _hash_ip(ip: str) -> str:
    """HMAC(api_key_salt, ip). Hex digest. Stored in trial_signups.created_ip_hash.

    Reused at verify time only for telemetry; the per-IP velocity gate
    runs at POST /v1/signup time against this same hash.
    """
    return hmac.new(
        settings.api_key_salt.encode(),
        ip.encode(),
        hashlib.sha256,
    ).hexdigest()


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class SignupRequest(BaseModel):
    email: EmailStr = Field(
        description=(
            "Reachable email address — a magic-link verification mail is sent here. "
            "(連絡可能なメールアドレス。マジックリンクが届きます。)"
        ),
    )


class SignupResponse(BaseModel):
    """202 Accepted body.

    We deliberately do NOT echo the email back — it's already in the
    request. Returning a stable shape with a request_id-equivalent makes
    it easy for the homepage form to confirm "we got it" without leaking
    the dedup state (a 409 vs 202 distinction would let an attacker probe
    for whether a given address has already used its trial).
    """

    accepted: bool = True
    detail: str = (
        "メールに記載されたリンクをクリックすると API キーが発行されます。"
        "リンクの有効期限は 24 時間です。"
    )


# ---------------------------------------------------------------------------
# Email side-effect (best-effort; mirrors appi_disclosure pattern)
# ---------------------------------------------------------------------------


def _send_magic_link_email(
    *,
    to: str,
    magic_link_url: str,
    expires_at_iso: str,
) -> None:
    """Fire the magic-link email. NEVER raises into the caller.

    Uses the Postmark Template Alias `trial-magic-link`, mirroring the
    existing `welcome` / `dunning` / `key-rotated` shape from
    email/postmark.py. TemplateModel keys:
        - magic_link_url (str)
        - expires_at (str, ISO 8601 — formatted by the template)
        - duration_days (int)
        - request_cap (int)
    """
    try:
        from jpintel_mcp.email.postmark import (
            STREAM_TRANSACTIONAL,
            get_client,
        )

        client = get_client()
        # Postmark client's _send swallows transport / API errors and
        # short-circuits in test mode. We just need to call it.
        client._send(
            to=to,
            template_alias="trial-magic-link",
            template_model={
                "magic_link_url": magic_link_url,
                "expires_at": expires_at_iso,
                "duration_days": TRIAL_DURATION_DAYS,
                "request_cap": TRIAL_REQUEST_CAP,
            },
            message_stream=STREAM_TRANSACTIONAL,
            tag="trial-magic-link",
        )
    except Exception:
        logger.warning("trial.signup.magic_link_email_failed", exc_info=True)


def _enqueue_trial_welcome(
    conn: sqlite3.Connection,
    *,
    to: str,
    api_key_hash: str,
    expires_at_iso: str,
) -> None:
    """Durably enqueue the post-activation welcome (D+0) and the day-11
    "your trial ends in 3 days" nudge.

    Both go through `_bg_task_queue` (migration 060) so a process restart
    between issuance and the first send cannot drop them. The welcome
    fires immediately (`run_at=None`); the day-11 nudge is deferred to
    `created_at + 11d` so the worker picks it up automatically.

    A day-30 "tell us why you didn't convert" follow-up is intentionally
    NOT enqueued here — it's an A/B-able touch best driven by the existing
    `email_schedule` cron (or a future iteration) where the operator can
    pause/resume the rule without redeploying. Keeping the trial flow
    surface small reduces the chance the welcome path ever 5xx's.
    """
    try:
        from jpintel_mcp.api._bg_task_queue import enqueue as _bg_enqueue

        _bg_enqueue(
            conn,
            kind="welcome_email_trial",
            payload={
                "to": to,
                "key_last4": api_key_hash[-4:],
                "expires_at": expires_at_iso,
                "duration_days": TRIAL_DURATION_DAYS,
                "request_cap": TRIAL_REQUEST_CAP,
            },
            dedup_key=f"trial_welcome:{api_key_hash}",
        )
        # Day-11 (3-day-warning) — runs `created_at + 11d`.
        run_at = datetime.now(UTC) + timedelta(days=11)
        _bg_enqueue(
            conn,
            kind="trial_day11_warning",
            payload={
                "to": to,
                "key_last4": api_key_hash[-4:],
                "expires_at": expires_at_iso,
                "checkout_url": PAID_CHECKOUT_URL,
            },
            dedup_key=f"trial_day11:{api_key_hash}",
            run_at=run_at,
        )
    except Exception:
        logger.warning("trial.signup.welcome_enqueue_failed", exc_info=True)


# ---------------------------------------------------------------------------
# Per-IP velocity gate
# ---------------------------------------------------------------------------


def _per_ip_recent_count(
    conn: sqlite3.Connection, ip_hash: str, window_hours: int = PER_IP_WINDOW_HOURS
) -> int:
    """Number of trial_signups rows from this ip_hash in the last `window_hours`.

    Uses the partial index idx_trial_signups_ip_recent(created_ip_hash,
    created_at). Counted via SQLite's datetime arithmetic so the cutoff
    is server-time, not client-supplied.
    """
    cutoff = (datetime.now(UTC) - timedelta(hours=window_hours)).isoformat()
    row = conn.execute(
        "SELECT COUNT(*) FROM trial_signups "
        "WHERE created_ip_hash = ? AND created_at >= ?",
        (ip_hash, cutoff),
    ).fetchone()
    if row is None:
        return 0
    try:
        return int(row[0])
    except (TypeError, IndexError, ValueError):
        return 0


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post(
    "/v1/signup",
    response_model=SignupResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="メール認証だけで 14 日 / 200 req のトライアル鍵を発行",
)
def submit_signup(
    payload: SignupRequest,
    request: Request,
    conn: DbDep,
    background_tasks: BackgroundTasks,
) -> SignupResponse:
    """Persist a trial_signups row + mail a magic link. Always 202 Accepted.

    Posture: we always return 202 even when:
        * the email already used its lifetime trial (409 in body would
          leak account-existence; a uniform 202 with the magic link only
          mailed when the row insert succeeds keeps the response shape
          opaque). Re-signup attempts hit the UNIQUE on email_normalized
          which we swallow as IntegrityError — no email is sent.
        * the IP has exceeded its 24h gate. We DO surface this as 429
          because an evaluator typing their email twice should see WHY
          their second click bounced.

    Stripe is NEVER involved. tier='trial' rows have no customer_id, no
    subscription, and the metered branch in deps._enforce_quota /
    ApiContext.metered checks `tier == 'paid'`.
    """
    email = payload.email.strip()
    email_normalized = _normalize_email(email)
    ip = _client_ip(request)
    ip_hash = _hash_ip(ip)

    # Per-IP velocity gate. Run BEFORE the DB lookup so a script walking
    # the +tag space from one IP gets bounced cheaply.
    recent = _per_ip_recent_count(conn, ip_hash)
    if recent >= PER_IP_LIMIT:
        retry_after = int(timedelta(hours=PER_IP_WINDOW_HOURS).total_seconds())
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "error": "signup_rate_limited",
                "message": (
                    "同一 IP アドレスからのトライアル登録は "
                    f"{PER_IP_WINDOW_HOURS} 時間に "
                    f"{PER_IP_LIMIT} 件までです。"
                ),
                "retry_after": retry_after,
            },
            headers={"Retry-After": str(retry_after)},
        )

    now_iso = datetime.now(UTC).isoformat()
    token = _make_token(email_normalized, now_iso)
    token_hash = _hash_token(token)

    try:
        conn.execute(
            """INSERT INTO trial_signups(
                   email, email_normalized, token_hash, created_at,
                   created_ip_hash
               ) VALUES (?, ?, ?, ?, ?)""",
            (email, email_normalized, token_hash, now_iso, ip_hash),
        )
    except sqlite3.IntegrityError:
        # Lifetime UNIQUE on email_normalized was hit. We do NOT 409 —
        # a uniform 202 keeps the response shape opaque to anyone probing
        # for "is this email already a customer". The downside is a real
        # user clicking twice gets a silent no-op for the second click;
        # we mitigate by tagging the log line so the operator can spot
        # the legitimate-vs-malicious pattern.
        logger.info(
            "trial.signup.duplicate email_norm_prefix=%s",
            email_normalized[:3] + "***",
        )
        return SignupResponse(
            accepted=True,
            detail=(
                "リクエストを受け付けました。"
                "既に登録済みの場合は新しいリンクは発行されません。"
                f"未受信の場合は {PAID_CHECKOUT_URL} から有料プランをご利用ください。"
            ),
        )

    # Magic-link URL. We pass `email` (verbatim, not normalized) and the
    # token. /v1/signup/verify normalises again on receipt — the URL
    # carries the user-typed form so the trail in inbox URLs / paste
    # buffers is human-readable.
    api_origin = _api_origin(request)
    from urllib.parse import urlencode

    qs = urlencode({"email": email, "token": token})
    magic_link_url = f"{api_origin}/v1/signup/verify?{qs}"
    expires_at_iso = (
        datetime.now(UTC) + timedelta(hours=MAGIC_LINK_TTL_HOURS)
    ).isoformat()

    # Schedule email AFTER response flush via BackgroundTasks. Postmark is
    # ~200ms latency; doing it inline doubles the perceived signup time.
    background_tasks.add_task(
        _send_magic_link_email,
        to=email,
        magic_link_url=magic_link_url,
        expires_at_iso=expires_at_iso,
    )

    logger.info(
        "trial.signup.created email_norm_prefix=%s ip_hash_prefix=%s",
        email_normalized[:3] + "***",
        ip_hash[:8],
    )
    return SignupResponse()


@router.get(
    "/v1/signup/verify",
    summary="マジックリンクを検証してトライアル API 鍵を発行 (1 回限りの reveal)",
    include_in_schema=True,
)
def verify_signup(
    request: Request,
    conn: DbDep,
    email: Annotated[str, Query(min_length=3, max_length=320)],
    token: Annotated[str, Query(min_length=32, max_length=128)],
) -> RedirectResponse:
    """Verify the magic-link token, issue a trial key, redirect to /trial.html.

    Behaviour:
        * Invalid / unknown email → redirect to /trial.html?status=invalid
        * Expired (>24h since signup) → redirect with ?status=expired
        * Already verified (key already issued) → redirect with ?status=already
        * OK → issue tier='trial' key, mark verified_at, link
          issued_api_key_hash, redirect to /trial.html with the raw key
          in the URL fragment.

    We deliberately use a 302 redirect rather than rendering JSON here
    so a click from the email client lands on the static page and the
    raw-key reveal flow matches the success.html paid-tier UX pattern.
    The fragment-only key is invisible to our access logs (browsers
    strip fragment before sending the request).
    """
    from jpintel_mcp.billing.keys import issue_trial_key

    email_clean = email.strip()
    email_normalized = _normalize_email(email_clean)

    row = conn.execute(
        "SELECT email, email_normalized, token_hash, created_at, "
        "verified_at, issued_api_key_hash "
        "FROM trial_signups WHERE email_normalized = ?",
        (email_normalized,),
    ).fetchone()
    if row is None:
        return _redirect_landing(status_kind="invalid")

    # Already verified → don't double-issue. The user landed on the link
    # twice (browser back, email forward, etc.) and we point them at the
    # dashboard to recover their key from inbox.
    if row["verified_at"] is not None and row["issued_api_key_hash"]:
        return _redirect_landing(status_kind="already")

    # Constant-time HMAC compare. We recompute the expected token from
    # the row's created_at, NOT from the URL — the URL is the suspect.
    expected_token = _make_token(row["email_normalized"], row["created_at"])
    # Defense in depth: also compare the stored hash of the supplied
    # token against the stored hash. Two paths must both pass.
    submitted_hash = _hash_token(token)
    if not (
        hmac.compare_digest(expected_token, token)
        and hmac.compare_digest(row["token_hash"], submitted_hash)
    ):
        logger.info(
            "trial.signup.verify.token_mismatch email_norm_prefix=%s",
            email_normalized[:3] + "***",
        )
        return _redirect_landing(status_kind="invalid")

    # 24h TTL on the magic link.
    try:
        created_at_dt = datetime.fromisoformat(row["created_at"])
        if created_at_dt.tzinfo is None:
            created_at_dt = created_at_dt.replace(tzinfo=UTC)
    except ValueError:
        return _redirect_landing(status_kind="invalid")

    if datetime.now(UTC) - created_at_dt > timedelta(hours=MAGIC_LINK_TTL_HOURS):
        return _redirect_landing(status_kind="expired")

    # Issue the trial key. Wrapped in BEGIN IMMEDIATE so the issuance +
    # the verified_at stamp + the issued_api_key_hash linkage all land
    # atomically. A crash between issuance and the trial_signups update
    # would otherwise leave us with a key that has no signup record;
    # subsequent re-clicks would 409 on the api_keys insert (HMAC
    # PRIMARY KEY) but the user would never see the key revealed.
    raw_key = ""
    api_key_hash = ""
    expires_at_iso = ""
    conn.execute("BEGIN IMMEDIATE")
    try:
        raw_key, api_key_hash = issue_trial_key(
            conn,
            trial_email=row["email"],
            duration_days=TRIAL_DURATION_DAYS,
            request_cap=TRIAL_REQUEST_CAP,
        )
        verified_iso = datetime.now(UTC).isoformat()
        conn.execute(
            "UPDATE trial_signups SET verified_at = ?, issued_api_key_hash = ? "
            "WHERE email_normalized = ?",
            (verified_iso, api_key_hash, email_normalized),
        )
        # Read back the trial_expires_at the issue function set so the
        # welcome mail carries the correct deadline.
        ek = conn.execute(
            "SELECT trial_expires_at FROM api_keys WHERE key_hash = ?",
            (api_key_hash,),
        ).fetchone()
        if ek is not None:
            expires_at_iso = ek["trial_expires_at"] or ""
        conn.execute("COMMIT")
    except Exception:
        with contextlib.suppress(Exception):
            conn.execute("ROLLBACK")
        logger.exception("trial.signup.verify.issue_failed")
        return _redirect_landing(status_kind="error")

    # Enqueue post-activation emails durably (D+0 welcome, D+11 nudge).
    # Done OUTSIDE the issuance transaction — a queue write failure must
    # NOT roll back the key issuance.
    _enqueue_trial_welcome(
        conn,
        to=row["email"],
        api_key_hash=api_key_hash,
        expires_at_iso=expires_at_iso,
    )

    # Redirect with the raw key in the FRAGMENT so it never reaches
    # access logs. Status query param is `ok`.
    from urllib.parse import quote

    fragment = (
        f"api_key={quote(raw_key)}"
        f"&expires_at={quote(expires_at_iso)}"
        f"&request_cap={TRIAL_REQUEST_CAP}"
        f"&duration_days={TRIAL_DURATION_DAYS}"
    )
    return RedirectResponse(
        url=f"{TRIAL_LANDING_URL}?status=ok#{fragment}",
        status_code=status.HTTP_302_FOUND,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _api_origin(request: Request) -> str:
    """Best-effort canonical API origin for the magic-link URL.

    In prod we live at https://api.zeimu-kaikei.ai; in dev / tests we
    fall back to whatever the request scheme + host says. We do NOT
    pull from cors_origins because that's a list of *callers*, not our
    own host.
    """
    fwd_proto = request.headers.get("x-forwarded-proto") or request.url.scheme
    fwd_host = request.headers.get("x-forwarded-host") or request.url.netloc
    if fwd_proto and fwd_host:
        return f"{fwd_proto.split(',', 1)[0].strip()}://{fwd_host.strip()}"
    return f"{request.url.scheme}://{request.url.netloc}"


def _redirect_landing(*, status_kind: str) -> RedirectResponse:
    """Redirect to /trial.html with a status query param.

    `status_kind` ∈ {ok, invalid, expired, already, error}. The static
    page renders Japanese copy keyed off the status.
    """
    return RedirectResponse(
        url=f"{TRIAL_LANDING_URL}?status={status_kind}",
        status_code=status.HTTP_302_FOUND,
    )


__all__ = [
    "MAGIC_LINK_TTL_HOURS",
    "PAID_CHECKOUT_URL",
    "TRIAL_DURATION_DAYS",
    "TRIAL_LANDING_URL",
    "TRIAL_REQUEST_CAP",
    "_normalize_email",
    "_make_token",
    "_hash_token",
    "router",
]
