"""法令改正アラート (Compliance Alerts) REST endpoints.

Mounts at `/v1/compliance/*`. A subscription email product: users register
with email + optional houjin_bangou + industry codes + prefecture + a list
of areas_of_interest, then receive either:

    * Daily real-time alerts (plan='paid', ¥500/月 via Stripe), triggered
      by `scripts/compliance_cron.py` at 08:00 JST.
    * Monthly digest (plan='free') on the 1st of the month — same cron.

This module only handles the signup / verify / unsubscribe / Stripe
plumbing. Composition of the email body lives in
`jpintel_mcp.email.compliance_templates`; the daily scan + dispatch lives
in the cron script.

Endpoints (no auth, public — rate-limited at the service layer by the
anon-IP limiter already mounted globally for discovery routers):

    POST /v1/compliance/subscribe
    GET  /v1/compliance/verify/{verification_token}
    POST /v1/compliance/unsubscribe/{unsubscribe_token}
    POST /v1/compliance/stripe-checkout
    POST /v1/compliance/stripe-webhook

Privacy + abuse posture:
    * Double opt-in: POST /subscribe inserts a row with
      `verification_token` set and `verified_at=NULL`. Only verified rows
      are picked by the cron. Unverified rows age out at 30d (maintenance
      script, not implemented here).
    * Duplicate signup returns the same success envelope as a first
      signup so we never leak "this email is already subscribed" to an
      enumerator.
    * Unsubscribe token is 32 hex chars (128 bits of entropy) — safe
      against guessing.
"""

from __future__ import annotations

import json
import logging
import re
import secrets
import sqlite3
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, Header, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, EmailStr, Field, field_validator

from jpintel_mcp._lazy_stripe import stripe
from jpintel_mcp.api.billing import validate_jpcite_service_redirect_url
from jpintel_mcp.api.deps import DbDep  # noqa: TC001 (runtime for FastAPI Depends resolution)
from jpintel_mcp.config import settings
from jpintel_mcp.email.compliance_templates import (
    AREAS_SUPPORTED,
    render_verification_email,
)

logger = logging.getLogger("jpintel.api.compliance")

router = APIRouter(prefix="/v1/compliance", tags=["compliance"])


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Stripe product/price lookup_key for the ¥500/月 alert subscription.
# scripts/setup_stripe_compliance_product.py creates a Price with this key
# so Stripe checkout can be wired without baking a price_id into env.
STRIPE_LOOKUP_KEY = "compliance_alerts_monthly_v1"
# Metadata tag we apply to the Stripe Product so the setup script can
# find it on subsequent runs (idempotency).
STRIPE_PRODUCT_METADATA_TAG = {"autonomath_product": "compliance_alerts"}

# 47 都道府県 — canonical Japanese names. The landing form constrains the
# dropdown to this list so we never see "Tokyo"/"TOKYO"/"東京".
PREFECTURES: tuple[str, ...] = (
    "北海道",
    "青森県",
    "岩手県",
    "宮城県",
    "秋田県",
    "山形県",
    "福島県",
    "茨城県",
    "栃木県",
    "群馬県",
    "埼玉県",
    "千葉県",
    "東京都",
    "神奈川県",
    "新潟県",
    "富山県",
    "石川県",
    "福井県",
    "山梨県",
    "長野県",
    "岐阜県",
    "静岡県",
    "愛知県",
    "三重県",
    "滋賀県",
    "京都府",
    "大阪府",
    "兵庫県",
    "奈良県",
    "和歌山県",
    "鳥取県",
    "島根県",
    "岡山県",
    "広島県",
    "山口県",
    "徳島県",
    "香川県",
    "愛媛県",
    "高知県",
    "福岡県",
    "佐賀県",
    "長崎県",
    "熊本県",
    "大分県",
    "宮崎県",
    "鹿児島県",
    "沖縄県",
)

_HOUJIN_BANGOU_RE = re.compile(r"^\d{13}$")
# JSIC codes are 1-4 character strings (letter + digits in the real
# standard, but a permissive match keeps us compatible with partial
# selections from the landing page).
_JSIC_RE = re.compile(r"^[A-Z0-9]{1,4}$")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _gen_token() -> str:
    """32 hex chars = 128 bits of entropy. Safe against guessing."""
    return secrets.token_hex(16)


def _configure_stripe() -> None:
    """Bind Stripe SDK to the configured key + API version.

    Raises HTTPException(503) on missing key so endpoint handlers that
    need Stripe can surface a clear error rather than an opaque
    AttributeError at first call.
    """
    if not settings.stripe_secret_key:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Stripe not configured")
    stripe.api_key = settings.stripe_secret_key
    if settings.stripe_api_version:
        stripe.api_version = settings.stripe_api_version


def _get_alert_price_id() -> str:
    """Resolve the alert Price id by `lookup_key=STRIPE_LOOKUP_KEY`.

    Cached implicitly by stripe-python's default behaviour — this helper
    hits Stripe at most once per checkout call. Returns the Price id or
    raises 503 if not found (setup script not yet run).
    """
    _configure_stripe()
    prices = stripe.Price.list(lookup_keys=[STRIPE_LOOKUP_KEY], expand=["data.product"], limit=1)
    if not prices.data:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            f"Stripe price not configured (lookup_key={STRIPE_LOOKUP_KEY}). "
            "Run scripts/setup_stripe_compliance_product.py first.",
        )
    return str(prices.data[0].id)


def _verification_url(token: str) -> str:
    """Public URL the verification mail points at.

    Matches the router prefix below — change both or neither.
    """
    return f"https://jpcite.com/v1/compliance/verify/{token}"


def _send_verification_email(email: str, verify_token: str, unsub_token: str) -> None:
    """Fire-and-forget: render + hand off to Postmark.

    The Postmark `PostmarkClient._send` call expects a `template_alias`,
    but our alert emails use rendered-in-process HTML/text. We go out
    through the transactional outbound stream via a low-level sendEmail
    call rather than a template alias.

    Never raises — email failure must not fail the signup endpoint.
    """
    try:
        from jpintel_mcp.email.postmark import (
            POSTMARK_BASE_URL,
            STREAM_TRANSACTIONAL,
            get_client,
        )

        client = get_client()
        body = render_verification_email(
            email=email,
            verify_url=_verification_url(verify_token),
            unsubscribe_token=unsub_token,
        )
        if client.test_mode:
            logger.info(
                "compliance.verify.skip env=%s to=%s",
                settings.env,
                _redact_email(email),
            )
            return
        # Go direct against Postmark `/email` (not `/email/withTemplate`)
        # because the body is pre-rendered. Same token/from as the
        # transactional stream so deliverability stays consistent.
        import httpx

        with httpx.Client(
            base_url=POSTMARK_BASE_URL,
            timeout=httpx.Timeout(10.0, connect=5.0),
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "X-Postmark-Server-Token": settings.postmark_api_token,
            },
        ) as http:
            payload = {
                "From": settings.postmark_from_transactional,
                "To": email,
                "Subject": body["subject"],
                "HtmlBody": body["html"],
                "TextBody": body["text"],
                "MessageStream": STREAM_TRANSACTIONAL,
                "Tag": "compliance-verify",
                "TrackOpens": True,
                "TrackLinks": "HtmlAndText",
            }
            if settings.postmark_from_reply:
                payload["ReplyTo"] = settings.postmark_from_reply
            r = http.post("/email", json=payload)
            if r.status_code >= 400:
                logger.warning(
                    "compliance.verify.api_error status=%d to=%s",
                    r.status_code,
                    _redact_email(email),
                )
    except Exception:  # noqa: BLE001 — never raise back to handler
        logger.warning("compliance.verify.failed to=%s", _redact_email(email), exc_info=True)


def _redact_email(addr: str) -> str:
    if "@" not in addr:
        return "***"
    local, _, domain = addr.partition("@")
    if len(local) <= 1:
        return f"*@{domain}"
    return f"{local[0]}***@{domain}"


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class SubscribeRequest(BaseModel):
    email: EmailStr
    houjin_bangou: str | None = Field(default=None, min_length=13, max_length=13)
    industry_codes: list[str] = Field(default_factory=list, max_length=12)
    areas_of_interest: list[str] = Field(min_length=1, max_length=len(AREAS_SUPPORTED))
    prefecture: str | None = Field(default=None, max_length=16)
    plan: Literal["free", "paid"] = "free"
    source_lang: Literal["ja", "en"] = "ja"

    @field_validator("houjin_bangou")
    @classmethod
    def _check_houjin(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if not _HOUJIN_BANGOU_RE.match(v):
            raise ValueError("houjin_bangou must be 13 digits")
        return v

    @field_validator("industry_codes")
    @classmethod
    def _check_industry(cls, v: list[str]) -> list[str]:
        out: list[str] = []
        for code in v:
            code = code.strip().upper()
            if not code:
                continue
            if not _JSIC_RE.match(code):
                raise ValueError(f"invalid JSIC code: {code!r}")
            out.append(code)
        return out

    @field_validator("areas_of_interest")
    @classmethod
    def _check_areas(cls, v: list[str]) -> list[str]:
        unknown = [a for a in v if a not in AREAS_SUPPORTED]
        if unknown:
            raise ValueError(f"unsupported areas: {unknown!r}. allowed: {list(AREAS_SUPPORTED)}")
        # De-dupe while preserving order.
        seen: set[str] = set()
        out: list[str] = []
        for a in v:
            if a not in seen:
                seen.add(a)
                out.append(a)
        return out

    @field_validator("prefecture")
    @classmethod
    def _check_prefecture(cls, v: str | None) -> str | None:
        if v is None or not v.strip():
            return None
        v = v.strip()
        if v not in PREFECTURES:
            raise ValueError(f"unknown prefecture: {v!r}")
        return v


class SubscribeResponse(BaseModel):
    subscriber_id: int
    next_step: Literal["verify", "checkout"]
    checkout_url: str | None = None


class CheckoutRequest(BaseModel):
    subscriber_id: int
    success_url: str = "https://jpcite.com/alerts.html?status=ok"
    cancel_url: str = "https://jpcite.com/alerts.html?status=canceled"


class CheckoutResponse(BaseModel):
    url: str
    session_id: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


_HTML_OK_TEMPLATE = """<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
  body {{ font-family: -apple-system, 'Hiragino Sans', sans-serif; max-width: 560px; margin: 80px auto; padding: 0 20px; color: #111; line-height: 1.7; }}
  h1 {{ font-size: 24px; margin: 0 0 12px; }}
  p {{ color: #555; }}
  a {{ color: #1e3a8a; }}
</style>
</head>
<body>
  <h1>{title}</h1>
  <p>{body}</p>
  <p><a href="https://jpcite.com/">&larr; ホームへ</a></p>
</body>
</html>
"""


def _html_ok(title: str, body: str, status_code: int = 200) -> HTMLResponse:
    return HTMLResponse(
        _HTML_OK_TEMPLATE.format(title=title, body=body),
        status_code=status_code,
    )


@router.post(
    "/subscribe",
    response_model=SubscribeResponse,
    status_code=status.HTTP_201_CREATED,
)
def subscribe(payload: SubscribeRequest, conn: DbDep) -> SubscribeResponse:
    """Create a new pending subscription + send verification email.

    Flow:
        1. Insert row with `verification_token` set, `verified_at=NULL`.
        2. Send verification email (async best-effort via Postmark).
        3. If plan='paid', return `next_step='checkout'` + a placeholder
           response — the caller should then POST /stripe-checkout.
           (The caller must verify FIRST; the verify GET redirects to
           the checkout for paid plans — see below.)
        4. If plan='free', return `next_step='verify'`.

    Duplicate email behaviour: we return the SAME response shape whether
    this is a fresh signup or an already-existing email — no enumeration
    leak. A second subscribe with the same email re-sends the verification
    mail (an attacker cannot see `verified_at` from the endpoint; worst
    case they can DoS our Postmark budget, which the anon rate limit
    covers).
    """
    email_norm = payload.email.strip().lower()
    now = _now_iso()
    unsub_token = _gen_token()
    verify_token = _gen_token()

    try:
        cur = conn.execute(
            """INSERT INTO compliance_subscribers(
                 email, houjin_bangou, industry_codes_json, areas_of_interest_json,
                 prefecture, plan, subscribed_at, unsubscribe_token,
                 verification_token, source_lang, created_at, updated_at
               ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                email_norm,
                payload.houjin_bangou,
                json.dumps(payload.industry_codes, ensure_ascii=False),
                json.dumps(payload.areas_of_interest, ensure_ascii=False),
                payload.prefecture,
                payload.plan,
                now,
                unsub_token,
                verify_token,
                payload.source_lang,
                now,
                now,
            ),
        )
        subscriber_id = int(cur.lastrowid or 0)
    except sqlite3.IntegrityError:
        # UNIQUE(email, unsubscribe_token) — token is fresh random each
        # call so this path means something else (e.g. a retry with the
        # same explicit token). Treat as duplicate-email silent success.
        row = conn.execute(
            "SELECT id, unsubscribe_token, verification_token FROM compliance_subscribers "
            "WHERE email = ? ORDER BY id DESC LIMIT 1",
            (email_norm,),
        ).fetchone()
        if row is None:
            raise HTTPException(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                "subscribe failed (unknown)",
            ) from None
        subscriber_id = int(row["id"])
        verify_token = row["verification_token"] or verify_token
        unsub_token = row["unsubscribe_token"]

    _send_verification_email(email_norm, verify_token, unsub_token)

    # For plan=paid, the user still has to verify first. The verify page
    # redirects to checkout (see GET /verify below). Return the
    # `next_step='verify'` + attach a checkout hint so the landing page
    # can show the right "check your inbox" copy.
    next_step: Literal["verify", "checkout"] = "verify"
    checkout_url: str | None = None

    return SubscribeResponse(
        subscriber_id=subscriber_id,
        next_step=next_step,
        checkout_url=checkout_url,
    )


@router.get("/verify/{verification_token}", response_class=HTMLResponse)
def verify(verification_token: str, conn: DbDep) -> HTMLResponse:
    """Mark a subscriber as verified. Renders a minimal HTML page.

    A valid token flips `verified_at = now()` and clears
    `verification_token`. Idempotent — a second click shows the same
    success page (we look up by email after the clear, so the row is
    still findable by unsubscribe_token but not by verification_token).

    For paid subscribers, the page nudges the user to the Stripe checkout
    page (link to `/alerts.html#checkout`).
    """
    if not verification_token or len(verification_token) != 32:
        return _html_ok(
            "リンクが無効です",
            "この確認リンクは期限切れか、改ざんされている可能性があります。",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    row = conn.execute(
        "SELECT id, email, plan, verified_at FROM compliance_subscribers "
        "WHERE verification_token = ?",
        (verification_token,),
    ).fetchone()
    if row is None:
        # Could be an already-verified token (cleared to NULL) — fail
        # closed with a generic message; no enumeration leak.
        return _html_ok(
            "リンクが無効または既に確認済みです",
            "心当たりのあるメールアドレスで再度登録してください。",
            status_code=status.HTTP_404_NOT_FOUND,
        )

    if row["verified_at"] is None:
        now = _now_iso()
        conn.execute(
            "UPDATE compliance_subscribers SET verified_at = ?, "
            "verification_token = NULL, updated_at = ? WHERE id = ?",
            (now, now, int(row["id"])),
        )

    if row["plan"] == "paid":
        return _html_ok(
            "メールアドレスを確認しました",
            "次に決済をお済ませください: "
            f"<a href='https://jpcite.com/alerts.html?subscriber_id={int(row['id'])}&checkout=1'>決済に進む</a>",
        )
    return _html_ok(
        "メールアドレスを確認しました",
        "月次ダイジェストを配信します。ご登録ありがとうございます。",
    )


@router.post("/unsubscribe/{unsubscribe_token}", response_class=HTMLResponse)
def unsubscribe(unsubscribe_token: str, conn: DbDep) -> HTMLResponse:
    """Cancel the subscription.

    - For `plan='paid'`: also cancels the Stripe subscription (best-effort;
      if Stripe is down we still mark canceled_at locally so no more
      emails go out).
    - For `plan='free'`: just marks `canceled_at`.
    Returns HTML so the static unsubscribe landing page can call this
    via fetch + show the body.
    """
    if not unsubscribe_token or len(unsubscribe_token) != 32:
        return _html_ok(
            "リンクが無効です",
            "この解除リンクは期限切れか、改ざんされている可能性があります。",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    row = conn.execute(
        "SELECT id, email, plan, stripe_subscription_id, canceled_at "
        "FROM compliance_subscribers WHERE unsubscribe_token = ?",
        (unsubscribe_token,),
    ).fetchone()
    if row is None:
        # Same anti-enumeration posture as api/subscribers.py — always
        # render success so an attacker can't tell whether a token was
        # valid.
        return _html_ok(
            "配信を停止しました",
            "今後このメールアドレスへアラートを送信することはありません。",
        )

    if row["canceled_at"] is None:
        now = _now_iso()
        # Best-effort Stripe cancel for paid subs.
        sub_id = row["stripe_subscription_id"]
        if row["plan"] == "paid" and sub_id:
            try:
                _configure_stripe()
                stripe.Subscription.delete(sub_id)
            except Exception:  # noqa: BLE001 — local cancel still applies
                logger.warning(
                    "compliance.unsubscribe.stripe_cancel_failed sub=%s", sub_id, exc_info=True
                )
        conn.execute(
            "UPDATE compliance_subscribers SET canceled_at = ?, updated_at = ? WHERE id = ?",
            (now, now, int(row["id"])),
        )

    return _html_ok(
        "配信を停止しました",
        "今後このメールアドレスへアラートを送信することはありません。",
    )


@router.post("/stripe-checkout", response_model=CheckoutResponse)
def stripe_checkout(payload: CheckoutRequest, conn: DbDep) -> CheckoutResponse:
    """Create a Stripe Checkout Session for a verified paid subscriber.

    Requires the subscriber row to already exist and be verified. The
    session's `client_reference_id` is the subscriber_id so the webhook
    can tie the Stripe subscription back to our row.
    """
    row = conn.execute(
        "SELECT id, email, plan, verified_at, canceled_at, stripe_customer_id "
        "FROM compliance_subscribers WHERE id = ?",
        (payload.subscriber_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "subscriber not found")
    if row["verified_at"] is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "email not verified — click the confirmation link first",
        )
    if row["canceled_at"] is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "subscription canceled; re-subscribe from the landing page",
        )
    if row["plan"] != "paid":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "free-plan subscribers do not use Stripe checkout",
        )

    _configure_stripe()
    price_id = _get_alert_price_id()

    extra: dict[str, Any] = {}
    if settings.stripe_tax_enabled:
        extra["automatic_tax"] = {"enabled": True}
        extra["tax_id_collection"] = {"enabled": True}
        extra["billing_address_collection"] = "required"

    success_url = validate_jpcite_service_redirect_url(payload.success_url, kind="success")
    cancel_url = validate_jpcite_service_redirect_url(payload.cancel_url, kind="cancel")

    session = stripe.checkout.Session.create(  # type: ignore[call-arg,unused-ignore]
        mode="subscription",
        line_items=[{"price": price_id, "quantity": 1}],
        success_url=success_url,
        cancel_url=cancel_url,
        customer_email=row["email"],
        client_reference_id=str(int(row["id"])),
        allow_promotion_codes=True,
        locale="ja",
        branding_settings={"display_name": "jpcite"},
        custom_text={
            "submit": {
                "message": (
                    "ご登録により利用規約 (https://jpcite.com/tos.html) "
                    "およびプライバシーポリシー (https://jpcite.com/privacy.html) "
                    "に同意したものとみなされます。"
                )
            }
        },
        **extra,
    )
    return CheckoutResponse(url=session.url or "", session_id=session.id)


@router.post("/stripe-webhook")
async def stripe_webhook(
    request: Request,
    conn: DbDep,
    stripe_signature: str | None = Header(default=None, alias="stripe-signature"),
) -> dict[str, str]:
    """Handle customer.subscription.created/.deleted for the alert product.

    On `created` we persist stripe_customer_id / stripe_subscription_id +
    flip plan to 'paid' if it wasn't already.
    On `deleted` we mark canceled_at (same effect as a customer clicking
    the unsubscribe link — Stripe Customer Portal cancel path).
    """
    _configure_stripe()
    if not settings.stripe_webhook_secret:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "webhook secret unset")
    body = await request.body()
    try:
        event = stripe.Webhook.construct_event(
            body,
            stripe_signature or "",
            settings.stripe_webhook_secret,
            tolerance=300,
        )
    except stripe.SignatureVerificationError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "bad signature") from None

    etype = event["type"]
    obj = event["data"]["object"]
    logger.info("compliance.stripe.event type=%s id=%s", etype, event.get("id"))

    if etype == "customer.subscription.created":
        # We locate our subscriber via `client_reference_id` that we put on
        # the Checkout Session. Stripe propagates it onto the subscription
        # metadata via Checkout, but for safety we also fall back to
        # `customer.email`.
        sub_id = obj.get("id")
        customer_id = obj.get("customer")
        ref = None
        # Pull client_reference_id if present on the originating Session.
        # The subscription.created event body doesn't carry it directly,
        # so we retrieve the Session via the latest_invoice -> metadata
        # path when needed. For the MVP we look up by stripe_customer_id
        # OR unverified fallback by email.
        if customer_id:
            try:
                cust = stripe.Customer.retrieve(customer_id)
                ref = (
                    cust.get("metadata", {}).get("compliance_subscriber_id")
                    if isinstance(cust, dict)
                    else None
                )
                email = cust.get("email") if isinstance(cust, dict) else None
            except Exception:  # noqa: BLE001
                email = None
        else:
            email = None

        row = None
        if ref:
            row = conn.execute(
                "SELECT id FROM compliance_subscribers WHERE id = ?",
                (int(ref),),
            ).fetchone()
        if row is None and email:
            row = conn.execute(
                "SELECT id FROM compliance_subscribers "
                "WHERE email = ? AND canceled_at IS NULL "
                "ORDER BY id DESC LIMIT 1",
                (email.strip().lower(),),
            ).fetchone()

        if row is not None and sub_id:
            now = _now_iso()
            conn.execute(
                "UPDATE compliance_subscribers SET "
                "stripe_customer_id = ?, stripe_subscription_id = ?, "
                "plan = 'paid', updated_at = ? WHERE id = ?",
                (customer_id, sub_id, now, int(row["id"])),
            )
            logger.info(
                "compliance.sub_linked subscriber=%s stripe_sub=%s",
                int(row["id"]),
                sub_id,
            )
        else:
            logger.warning(
                "compliance.sub_unmatched stripe_sub=%s customer=%s",
                sub_id,
                customer_id,
            )
    elif etype == "customer.subscription.deleted":
        sub_id = obj.get("id")
        if sub_id:
            now = _now_iso()
            conn.execute(
                "UPDATE compliance_subscribers SET canceled_at = ?, updated_at = ? "
                "WHERE stripe_subscription_id = ? AND canceled_at IS NULL",
                (now, now, sub_id),
            )
            logger.info("compliance.sub_canceled stripe_sub=%s", sub_id)

    return {"status": "received"}


__all__ = ["router"]
