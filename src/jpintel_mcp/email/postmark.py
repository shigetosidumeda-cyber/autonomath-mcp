"""Postmark REST client — transactional mail only.

Why this shape:
    - We call Postmark's **Template Alias** endpoint (`/email/withTemplate`)
      so marketing / ops can iterate template HTML inside Postmark's UI
      without a code deploy. Python stays in charge of *which* template to
      fire and *what* `TemplateModel` variables to hand it.
    - Failures never raise. The welcome email runs inside the Stripe webhook
      handler; a Postmark 500 must not mark the invoice as un-processed
      (Stripe would then retry and issue a second API key). Failures log +
      `sentry_sdk.capture_exception` when Sentry is configured.
    - Test mode — empty token OR `settings.env == "test"` — short-circuits
      to a structured log line so unit tests can assert *what we would have
      sent* without any HTTP traffic.

Template aliases (created inside Postmark's UI; alias strings are stable):
    - `welcome`         — fires on first API-key issuance (D+0)
    - `weekly-digest`   — fires on W7 retention cron (see retention_digest.md)
    - `receipt`         — optional: forwards a Stripe hosted-invoice URL
    - `password-reset`  — placeholder for the future passwordless dashboard
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from jpintel_mcp.config import settings

logger = logging.getLogger("jpintel.email")

POSTMARK_BASE_URL = "https://api.postmarkapp.com"
# Postmark's bulk endpoint accepts up to 500 messages / call. We never hit
# that from transactional paths (single-recipient sends), so only the
# `/email/withTemplate` endpoint is wired. The digest cron (W7) will call
# `/email/batchWithTemplates` through a separate helper once it lands.
SEND_WITH_TEMPLATE_PATH = "/email/withTemplate"

# Message streams. Postmark requires every send to declare a stream; mixing
# transactional and broadcast on the same stream hurts deliverability. We use
# Postmark's default stream names so a fresh server works out of the box.
STREAM_TRANSACTIONAL = "outbound"
STREAM_BROADCAST = "broadcast"


class PostmarkClient:
    """Thin wrapper around Postmark's `/email/withTemplate` endpoint.

    A single instance is held per-process (`get_client()` below). Tests
    inject a custom `httpx.Client` via the `_http` constructor arg so we do
    not have to monkeypatch the global `httpx.post`.
    """

    def __init__(
        self,
        *,
        api_token: str | None = None,
        from_transactional: str | None = None,
        from_reply: str | None = None,
        env: str | None = None,
        _http: httpx.Client | None = None,
    ) -> None:
        # All four settings are resolved at construction. Tests that flip
        # `settings.env` mid-suite MUST re-create the client (or call
        # `get_client.cache_clear()` below).
        self._token = api_token if api_token is not None else settings.postmark_api_token
        self._from = (
            from_transactional
            if from_transactional is not None
            else settings.postmark_from_transactional
        )
        self._reply_to = from_reply if from_reply is not None else settings.postmark_from_reply
        self._env = env if env is not None else settings.env
        # Caller-supplied http lets tests pass an `httpx.Client(transport=
        # httpx.MockTransport(...))`. In production we lazy-init a real one
        # the first time we actually need to send.
        self._http = _http

    # ------------------------------------------------------------------ helpers

    @property
    def test_mode(self) -> bool:
        """True when we must NOT make a real HTTP call.

        The token guard matters on dev laptops (no `.env` populated) and on
        CI (pytest sets `JPINTEL_ENV=test`). Either path means: log the
        payload, return a stub response, never reach Postmark.
        """
        return not self._token or self._env == "test"

    def _client(self) -> httpx.Client:
        """Lazily build the real httpx client. Only called outside test mode."""
        if self._http is None:
            self._http = httpx.Client(
                base_url=POSTMARK_BASE_URL,
                timeout=httpx.Timeout(10.0, connect=5.0),
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    "X-Postmark-Server-Token": self._token,
                },
            )
        return self._http

    def _send(
        self,
        *,
        to: str,
        template_alias: str,
        template_model: dict[str, Any],
        message_stream: str = STREAM_TRANSACTIONAL,
        tag: str | None = None,
    ) -> dict[str, Any]:
        """Fire one Postmark `/email/withTemplate` request.

        Returns Postmark's JSON response (or a `{"skipped": true}` stub in
        test mode). NEVER raises — errors are logged and reported to Sentry
        if configured. This is deliberate: the welcome email lives inside
        the Stripe invoice.paid webhook and we would rather drop a
        notification than re-process a paid invoice.
        """
        payload: dict[str, Any] = {
            "From": self._from,
            "To": to,
            "TemplateAlias": template_alias,
            "TemplateModel": template_model,
            "MessageStream": message_stream,
            "TrackOpens": True,
            "TrackLinks": "HtmlAndText",
        }
        if self._reply_to:
            payload["ReplyTo"] = self._reply_to
        if tag:
            payload["Tag"] = tag

        if self.test_mode:
            # Structured log so test assertions can read it. DO NOT log the
            # full TemplateModel — it may contain key_last4 / invoice_url /
            # PII-adjacent strings. Log shape, not contents.
            logger.info(
                "postmark.skip env=%s template=%s to=%s keys=%s",
                self._env,
                template_alias,
                _redact_email(to),
                sorted(template_model.keys()),
            )
            return {"skipped": True, "reason": "test_mode"}

        try:
            r = self._client().post(SEND_WITH_TEMPLATE_PATH, json=payload)
        except httpx.HTTPError as exc:
            logger.warning(
                "postmark.transport_error template=%s to=%s err=%s",
                template_alias,
                _redact_email(to),
                exc,
            )
            _report_sentry(exc, template_alias=template_alias)
            return {"error": "transport", "detail": str(exc)}

        if r.status_code >= 400:
            # Postmark returns JSON with ErrorCode / Message on 4xx/5xx.
            # Log the ErrorCode but not the full body — it can echo the
            # recipient address back.
            body = _safe_json(r)
            logger.warning(
                "postmark.api_error status=%d template=%s to=%s code=%s",
                r.status_code,
                template_alias,
                _redact_email(to),
                body.get("ErrorCode"),
            )
            _report_sentry(
                RuntimeError(f"postmark {r.status_code} code={body.get('ErrorCode')}"),
                template_alias=template_alias,
            )
            return {"error": "api", "status": r.status_code, "body": body}

        return _safe_json(r)

    # ------------------------------------------------------------------- sends

    def send_welcome(self, *, to: str, key_last4: str, tier: str) -> dict[str, Any]:
        """D+0 welcome email, fired from the Stripe invoice.paid webhook.

        `key_last4` is the last 4 chars of the newly-issued raw API key. We
        NEVER email the full key; the customer gets it once from the
        checkout success page. This mail is the paper-trail / tier
        confirmation.
        """
        return self._send(
            to=to,
            template_alias="welcome",
            template_model={
                "key_last4": key_last4,
                "tier": tier,
                # Dashboard / docs links are baked into the template so the
                # `TemplateModel` payload stays minimal.
            },
            tag="welcome",
        )

    def send_digest(
        self,
        *,
        to: str,
        programs: list[dict[str, Any]],
        unsub_token: str,
    ) -> dict[str, Any]:
        """Weekly digest — fired by the W7 cron (`scripts/send_digest.py`).

        `programs` is a list of `{unified_id, name, prefecture, amount_max,
        subsidy_rate, url}` dicts. `unsub_token` is the HMAC token from
        `api.subscribers.make_unsubscribe_token(email)` so the footer link
        needs no DB lookup to verify.

        Uses the `broadcast` message stream so Postmark applies the digest's
        reputation separately from the transactional stream.
        """
        return self._send(
            to=to,
            template_alias="weekly-digest",
            template_model={
                "programs": programs,
                "unsub_token": unsub_token,
                "email": to,
            },
            message_stream=STREAM_BROADCAST,
            tag="digest",
        )

    def send_dunning(
        self,
        *,
        to: str,
        attempt_count: int,
        portal_url: str,
        key_last4: str,
        customer_name: str | None = None,
        next_retry_at: str | None = None,
    ) -> dict[str, Any]:
        """Payment-failed dunning notice — fired from the Stripe
        `invoice.payment_failed` webhook in `api/billing.py`.

        Subject (template alias `dunning` in Postmark UI):
            "[AutonoMath] お支払い更新のお願い"

        TemplateModel keys:
            - customer_name (str | None) — greeting line override
            - attempt_count (int) — Stripe's `invoice.attempt_count`
            - portal_url (str) — Stripe Customer Portal URL for card update
            - key_last4 (str) — last 4 chars of the affected API key
            - next_retry_at (str | None) — human-readable next-attempt
              timestamp (e.g. "2026-05-02 頃")

        Uses the transactional stream because dunning is a
        billing-relationship notice (CAN-SPAM / 特商法 transactional
        category). Failures NEVER raise — webhook returns 200 even when
        Postmark is down so Stripe does not retry the same invoice
        indefinitely.
        """
        return self._send(
            to=to,
            template_alias="dunning",
            template_model={
                "customer_name": customer_name or "",
                "attempt_count": attempt_count,
                "portal_url": portal_url,
                "key_last4": key_last4,
                "next_retry_at": next_retry_at or "",
            },
            tag="dunning",
        )

    def send_key_rotated(
        self,
        *,
        to: str,
        old_suffix: str,
        new_suffix: str,
        ip: str,
        user_agent: str,
        ts_jst: str,
    ) -> dict[str, Any]:
        """API-key rotation security notice — fired from `api/me.py::rotate_key`.

        P1 hardening from key-rotation audit a4298e454aab2aa43: a rotation
        without an out-of-band notification is indistinguishable from an
        attacker who exfiltrated a session cookie and silently rotated the
        legitimate user's key. Email gives the customer an audit trail
        ("〇〇:〇〇 JST に API キーがローテーションされました") with the
        IP / User-Agent / key suffixes the harness saw at rotation time.

        Subject (template alias `key-rotated` in Postmark UI):
            "[AutonoMath] API キーがローテーションされました"

        TemplateModel keys (all required):
            - old_suffix (str) — last 4 chars of the revoked key
            - new_suffix (str) — last 4 chars of the freshly-issued key
            - ip (str) — caller IP from X-Forwarded-For / request.client.host
            - user_agent (str) — caller User-Agent header (truncated upstream)
            - ts_jst (str) — JST-formatted rotation timestamp ("YYYY-MM-DD
              HH:MM JST"), pre-rendered so the template stays DB-free.

        Uses the transactional stream because this is a security-relationship
        notice (取引関連メール category — no `{{{pm:unsubscribe}}}` footer).
        Failures NEVER raise — rotation must succeed even when Postmark is
        down; the wrapper at the call site swallows + Sentry-captures.
        """
        return self._send(
            to=to,
            template_alias="key-rotated",
            template_model={
                "old_suffix": old_suffix,
                "new_suffix": new_suffix,
                "ip": ip,
                "user_agent": user_agent,
                "ts_jst": ts_jst,
            },
            tag="key-rotated",
        )

    def send_receipt(self, *, to: str, invoice_url: str) -> dict[str, Any]:
        """Forward a Stripe hosted-invoice URL.

        We do NOT generate invoice HTML here — Stripe already produces the
        compliant 適格請求書 (when STRIPE_TAX_ENABLED + invoice registration
        number are set per research/stripe_jct_setup.md). This mail is just
        a pointer so the customer does not have to log into Stripe.
        """
        return self._send(
            to=to,
            template_alias="receipt",
            template_model={"invoice_url": invoice_url},
            tag="receipt",
        )


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------


_client: PostmarkClient | None = None


def get_client() -> PostmarkClient:
    """Return the process-wide client. Tests reset via `reset_client()`.

    We intentionally DO NOT use `functools.lru_cache` because Settings can
    be mutated between tests (the conftest purges `jpintel_mcp.*` modules
    and re-imports with fresh env vars).
    """
    global _client
    if _client is None:
        _client = PostmarkClient()
    return _client


def reset_client() -> None:
    """Drop the singleton. Test-only helper."""
    global _client
    _client = None


# ---------------------------------------------------------------------------
# Small private utilities
# ---------------------------------------------------------------------------


def _safe_json(r: httpx.Response) -> dict[str, Any]:
    """Parse Postmark's JSON body, falling back to {} on malformed input.

    Postmark does return JSON for every 2xx / 4xx but the bytes might be
    empty on some 5xx paths (proxy timeouts). Swallowing the error is fine;
    the caller only reads `ErrorCode` out of this.
    """
    try:
        body = r.json()
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


def _redact_email(addr: str) -> str:
    """Return `a****@example.com` — just enough for log correlation."""
    if "@" not in addr:
        return "***"
    local, _, domain = addr.partition("@")
    if len(local) <= 1:
        return f"*@{domain}"
    return f"{local[0]}***@{domain}"


def _report_sentry(exc: Exception, *, template_alias: str) -> None:
    """Forward to Sentry if configured, silently no-op otherwise."""
    try:
        import sentry_sdk  # type: ignore[import-not-found]
    except ImportError:
        return
    try:
        # sentry-sdk 2.x: prefer the new scope API; fall back to push_scope
        # on older releases so we stay compatible with either version.
        new_scope = getattr(sentry_sdk, "new_scope", None)
        if new_scope is not None:
            with new_scope() as scope:  # type: ignore[misc]
                scope.set_tag("component", "email.postmark")
                scope.set_tag("template_alias", template_alias)
                sentry_sdk.capture_exception(exc)
        else:
            with sentry_sdk.push_scope() as scope:  # type: ignore[attr-defined]
                scope.set_tag("component", "email.postmark")
                scope.set_tag("template_alias", template_alias)
                sentry_sdk.capture_exception(exc)
    except Exception:
        # Sentry errors must not mask the original problem.
        logger.debug("sentry forwarding failed", exc_info=True)


__all__ = [
    "PostmarkClient",
    "POSTMARK_BASE_URL",
    "SEND_WITH_TEMPLATE_PATH",
    "STREAM_BROADCAST",
    "STREAM_TRANSACTIONAL",
    "get_client",
    "reset_client",
]
