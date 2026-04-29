"""Stripe self-serve billing endpoints (pure metered ¥3/req).

Flow:
  - POST /v1/billing/checkout          -> Stripe Checkout URL (single metered Price)
  - POST /v1/billing/portal            -> Stripe Customer Portal URL
  - POST /v1/billing/webhook           -> handles subscription.created /
                                           invoice.paid / payment_failed /
                                           subscription.updated / deleted
  - POST /v1/billing/keys/from-checkout-> returns new raw key once after
                                           Checkout completion

Pricing model (see `project_autonomath_business_model.md` memory, 2026-04-23):
  Anonymous Free (50 req/month per IP) → metered via Stripe usage_records
  at ¥3/req 税別 / ¥3.30 税込 (lookup_key=per_request_v3). No tiers,
  no subscription cancellation distinct from card removal.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Annotated

import stripe
from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request, status
from pydantic import BaseModel

from jpintel_mcp.api._advisory_lock import LockNotAcquired, advisory_lock
from jpintel_mcp.api.deps import DbDep  # noqa: TC001 (runtime for FastAPI Depends resolution)
from jpintel_mcp.billing.keys import (
    issue_key,
    resolve_tier_from_price,
    revoke_subscription,
    update_subscription_status,
    update_subscription_status_by_id,
    update_tier_by_subscription,
)
from jpintel_mcp.config import settings
from jpintel_mcp.db.session import connect as _db_connect
from jpintel_mcp.email import get_client as _get_email_client

if TYPE_CHECKING:
    import types


logger = logging.getLogger("jpintel.billing")

router = APIRouter(prefix="/v1/billing", tags=["billing"])

# Sentry capture is best-effort: tests / CI without sentry_sdk installed
# must still exercise the webhook path. Guarding the import here keeps
# `_capture` callable even when the SDK is absent so handler bodies stay
# linear instead of `if "sentry_sdk" in sys.modules` everywhere.
try:
    import sentry_sdk as _sentry_sdk  # noqa: TC003 (runtime guard)
    _SENTRY_AVAILABLE = True
except ImportError:  # pragma: no cover — exercised only on minimal installs
    _SENTRY_AVAILABLE = False


def _capture(exc: BaseException) -> None:
    """Forward an exception to Sentry iff the SDK is loaded.

    Webhook handlers swallow errors by design (idempotency > visibility) but
    silent failures translate directly to silent revenue loss — a Stripe
    invoice.paid that quietly raises means a customer pays but never gets a
    key. Every swallow site that touches money / DB writes / external APIs
    forwards via this helper so Sentry sees the truth even when the
    response stays 200.
    """
    if _SENTRY_AVAILABLE:
        try:
            _sentry_sdk.capture_exception(exc)
        except Exception:  # pragma: no cover — last-defence
            # Sentry transport itself blew up — never raise back into the
            # webhook handler. The structured log line at the call site
            # remains the second line of defence.
            logger.debug("sentry_capture_failed", exc_info=True)


def _send_dunning_safe(
    *,
    conn,
    to: str | None,
    sub_id: str | None,
    attempt_count: int,
    next_retry_epoch: int | None,
) -> None:
    """Fire-and-forget dunning notice. NEVER raises into the webhook.

    Triggered from `invoice.payment_failed`. Carries:
      * key_last4 — looked up from `api_keys` by stripe_subscription_id so
        the customer can recognise which key is impacted
      * portal_url — Stripe Customer Portal entry point (operator-hosted
        passthrough at /v1/billing/portal would require a customer_id +
        return_url round-trip, so we send the static dashboard pointer
        which already links to portal creation server-side)
      * next_retry_at — best-effort JST string from the Stripe-supplied
        `next_payment_attempt` epoch; absent in rare manual-collection
        cases.

    Failure modes (all swallowed, all logged):
      * to=None — abandoned cart / B2B no-email customer
      * Postmark down — internal layer already non-raising
      * DB miss for key_last4 — render with "????" placeholder rather
        than skip; the customer still benefits from the notice.
    """
    if not to:
        return
    try:
        last4 = "????"
        if sub_id:
            row = conn.execute(
                "SELECT key_last4 FROM api_keys "
                "WHERE stripe_subscription_id = ? AND revoked_at IS NULL "
                "LIMIT 1",
                (sub_id,),
            ).fetchone()
            if row and row[0]:
                last4 = row[0]
        next_retry_at = ""
        if next_retry_epoch:
            try:
                from datetime import datetime as _dt
                from datetime import timedelta as _td
                from datetime import timezone as _tz
                _jst = _tz(_td(hours=9))
                next_retry_at = _dt.fromtimestamp(
                    int(next_retry_epoch), tz=_jst
                ).strftime("%Y-%m-%d %H:%M JST")
            except Exception:
                next_retry_at = ""
        portal_url = "https://zeimu-kaikei.ai/billing/portal"
        _get_email_client().send_dunning(
            to=to,
            attempt_count=attempt_count,
            portal_url=portal_url,
            key_last4=last4,
            next_retry_at=next_retry_at,
        )
    except Exception as e:
        # Postmark API call failed — capture to Sentry so a sustained
        # transport outage surfaces. Webhook still 200s (idempotency).
        _capture(e)
        logger.warning(
            "dunning email failed sub=%s attempt=%d",
            sub_id,
            attempt_count,
            exc_info=True,
        )


def _send_welcome_safe(*, to: str | None, raw_key: str, tier: str) -> None:
    """Fire-and-forget welcome mail. Never raises back into the caller.

    D+0 welcome on key issuance lives in two paths (see issue_from_checkout
    and the subscription.created / invoice.paid webhooks). Email is NOT a
    critical path — a dead Postmark must never leave a paid invoice
    un-acknowledged. The email layer already handles test-mode / missing-
    token / transport errors internally; this wrapper catches the
    ImportError path + any last-defence bug so a regression here does not
    500 Stripe.

    D+0 is the ONE mail that contains the raw API key. It is sent here
    synchronously — NOT via `email.scheduler` — because rows in the
    `email_schedule` table persist the key hash only, and the customer
    needs to see the raw key exactly once at issuance. The scheduler
    picks up at D+1 (`onboarding-day1` alias; see
    `src/jpintel_mcp/email/scheduler.py::ALL_KINDS`).

    The Postmark alias used here is `welcome`. The richer on-disk
    template at `src/jpintel_mcp/email/templates/onboarding_day0.{html,txt}`
    carries `{{email}}` / `{{api_key}}` placeholders and can replace the
    live `welcome` alias once the Postmark UI copy is updated — call
    `onboarding.send_day0_welcome(to=..., api_key=raw_key, tier=...)`
    instead of `send_welcome` after the alias flip.
    """
    if not to:
        return
    try:
        _get_email_client().send_welcome(
            to=to,
            key_last4=raw_key[-4:] if raw_key else "????",
            tier=tier,
        )
    except Exception as e:
        # Postmark welcome failure is the loudest possible silent revenue
        # event: customer paid, key issued, customer never sees the key.
        # Capture so a Postmark outage during launch hour is visible within
        # the 5-min Sentry alert window.
        _capture(e)
        logger.warning("welcome email failed tier=%s", tier, exc_info=True)


def _extract_subscription_state(obj: dict) -> tuple[str | None, int | None, bool | None]:
    """Extract (status, current_period_end_epoch, cancel_at_period_end) from a Stripe subscription dict.

    Used by the webhook handler to populate api_keys.stripe_subscription_*
    columns (migration 052). Returns (None, None, None) for any missing
    field — the caller passes only the present values to update_subscription_status.
    """
    status_val = obj.get("status") if isinstance(obj, dict) else None
    cpe = obj.get("current_period_end") if isinstance(obj, dict) else None
    cancel_flag = (
        obj.get("cancel_at_period_end") if isinstance(obj, dict) else None
    )
    cpe_int: int | None = int(cpe) if cpe is not None else None
    cancel_bool: bool | None = bool(cancel_flag) if cancel_flag is not None else None
    return status_val, cpe_int, cancel_bool


def _refresh_subscription_status_from_stripe(
    conn, sub_id: str
) -> None:
    """Best-effort live-fetch of a Stripe Subscription to refresh the cache.

    Called from invoice.paid where the payload itself does not carry the
    Subscription's `status` / `current_period_end` / `cancel_at_period_end`.
    Failure is logged but never raised — webhook idempotency wins over a
    stale-by-a-few-seconds cache.

    P1 race fix (audit a23909ea8a7d67d64, 2026-04-25): wrapped in an
    app-level advisory lock keyed by subscription_id. Two refreshes for
    the same sub (webhook + bg_task_queue worker, or invoice.paid +
    subscription.updated arriving back-to-back) would otherwise race the
    UPDATE on `api_keys.stripe_subscription_status` — whichever writer's
    stale-by-a-few-ms read of Stripe wins last. With the lock, the
    contender raises LockNotAcquired and short-circuits; the holder will
    write a fresh-enough state for both.
    """
    try:
        with advisory_lock(conn, f"subscription:{sub_id}", ttl_s=30):
            sub = stripe.Subscription.retrieve(sub_id)
            # Stripe SDK objects behave like dicts.
            sub_dict = dict(sub) if not isinstance(sub, dict) else sub
            status_val, cpe_int, cancel_bool = _extract_subscription_state(sub_dict)
            if status_val:
                update_subscription_status(
                    conn,
                    sub_id,
                    status=status_val,
                    current_period_end=cpe_int,
                    cancel_at_period_end=cancel_bool,
                )
    except LockNotAcquired:
        # Another holder is already refreshing this subscription. The
        # other holder will write the fresh state; nothing for us to do.
        # Logged at info because contention is expected under bursty
        # webhook + bg_task_queue dispatch.
        logger.info(
            "subscription_status_refresh_skipped_locked sub=%s",
            sub_id,
        )
    except Exception as e:
        # Stripe API call inside the webhook failed. Capture: a sustained
        # subscription.retrieve outage means the dashboard dunning banner
        # goes stale across all paid customers — needs operator visibility.
        _capture(e)
        logger.warning(
            "subscription_status_refresh_failed sub=%s",
            sub_id,
            exc_info=True,
        )


def _refresh_subscription_status_from_stripe_bg(sub_id: str) -> None:
    """Background-task variant: opens its own DB connection.

    The request-scoped connection from DbDep is closed by the time
    BackgroundTasks fire (FastAPI runs them after the response is sent),
    so we MUST NOT capture `conn` from the request scope. Each background
    invocation owns its own short-lived connection.
    """
    conn = None
    try:
        conn = _db_connect()
        _refresh_subscription_status_from_stripe(conn, sub_id)
    except Exception as e:
        # BG-task variant: failures here run after response is sent so the
        # webhook caller cannot observe them. Sentry is the only signal.
        _capture(e)
        logger.warning(
            "subscription_status_refresh_bg_failed sub=%s",
            sub_id,
            exc_info=True,
        )
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def _send_dunning_safe_bg(
    *,
    to: str | None,
    sub_id: str | None,
    attempt_count: int,
    next_retry_epoch: int | None,
) -> None:
    """Background-task variant of _send_dunning_safe with its own DB conn.

    The dunning helper looks up key_last4 by sub_id; that lookup needs a
    DB connection. The original signature takes `conn` from the request
    scope — unsafe in BackgroundTasks because the request conn is closed
    by then. Mint a fresh one here.
    """
    conn = None
    try:
        conn = _db_connect()
        _send_dunning_safe(
            conn=conn,
            to=to,
            sub_id=sub_id,
            attempt_count=attempt_count,
            next_retry_epoch=next_retry_epoch,
        )
    except Exception as e:
        # BG-task variant: post-response failures are invisible to caller.
        _capture(e)
        logger.warning(
            "dunning_bg_failed sub=%s",
            sub_id,
            exc_info=True,
        )
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def _stripe() -> types.ModuleType:  # returns configured stripe module
    if not settings.stripe_secret_key:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Stripe not configured")
    stripe.api_key = settings.stripe_secret_key
    # Pin to 2024-11-20.acacia so legacy metered (usage_records) still works.
    # Newer versions require a Meter object we cannot create with the
    # current restricted-key permission set.
    if settings.stripe_api_version:
        stripe.api_version = settings.stripe_api_version
    return stripe


def _check_b2b_tax_id_safe(customer_id: str | None) -> None:
    """INV-23: warn if a B2B customer subscribed without supplying a tax_id.

    インボイス制度 compliance: 仕入税額控除 を取りたい B2B 買い手は適格請求書に
    自社の登録番号 (T-号) が印字されている必要がある。Stripe Checkout 側で
    `tax_id_collection={"enabled": True}` を有効にしているので、法人 (会社名 in
    customer.name) で `tax_ids` が空のまま subscribe してきたケースは
    「個人事業主 / 免税事業者」か「収集失敗」のいずれか。後者なら来月の請求書
    発行時に operator が能動的にフォローアップする。

    Idempotent / never raises:
      * Stripe API failure → log only, webhook still 200
      * customer_id None → no-op
      * 個人 (会社名のヒューリスティック miss) → no-op
    """
    if not customer_id:
        return
    try:
        cust = stripe.Customer.retrieve(customer_id, expand=["tax_ids"])
    except Exception as e:
        # Stripe Customer.retrieve failed inside the webhook. Capture so a
        # restricted-key permission drop (rak_customer_read missing) is
        # spotted before invoice issuance silently misses tax_id checks.
        _capture(e)
        logger.warning(
            "tax_id_check failed customer=%s",
            customer_id,
            exc_info=True,
        )
        return

    # Stripe SDK returns either a dict or a StripeObject — handle both.
    if isinstance(cust, dict):
        name = cust.get("name") or ""
        tax_ids_obj = cust.get("tax_ids") or {}
        tax_ids_data = tax_ids_obj.get("data") if isinstance(tax_ids_obj, dict) else []
    else:
        name = getattr(cust, "name", "") or ""
        tax_ids_obj = getattr(cust, "tax_ids", None)
        tax_ids_data = getattr(tax_ids_obj, "data", []) if tax_ids_obj is not None else []
    tax_ids_data = tax_ids_data or []

    # B2B ヒューリスティック: 会社名に「株式会社」「有限会社」「合同会社」等が入る
    b2b_hints = (
        "株式会社", "有限会社", "合同会社", "合資会社", "合名会社",
        "社団法人", "財団法人", "医療法人", "学校法人",
        "Inc.", "LLC", "Corp", "Co., Ltd", "K.K.", "Ltd.",
    )
    is_b2b = any(h in name for h in b2b_hints)
    if not is_b2b:
        return

    if not tax_ids_data:
        # B2B customer without tax_id collected. Log warn so operator can
        # follow up before the first 適格請求書 prints. No throw — the
        # subscription must still succeed (receipt-only B2B is legal).
        logger.warning(
            "inv23_b2b_no_tax_id customer=%s name=%s — Stripe Checkout "
            "tax_id_collection enabled but customer.tax_ids is empty. "
            "Operator review needed before first 適格請求書 issuance.",
            customer_id,
            name,
        )
    else:
        logger.info(
            "inv23_b2b_tax_id_present customer=%s count=%d",
            customer_id,
            len(tax_ids_data),
        )


def _apply_invoice_metadata_safe(customer_id: str | None) -> None:
    """Apply 適格請求書 (qualified invoice) footer + 登録番号 to a Stripe Customer.

    インボイス制度 (2023-10-01 ~) requires the issuer to print:
      * 適格請求書発行事業者の氏名又は名称及び登録番号 (T-号)
      * 軽減税率対象品目の有無 (デジタルサービスは標準10%、軽減対象なし)
      * 税率ごとの対価の額・適用税率 (Stripe Tax + tax_behavior=exclusive で自動)

    We attach the operator block at Customer level via
    `invoice_settings.custom_fields` (max 4 fields, each name<=30 / value<=30
    chars) and a free-form `footer` so it appears on EVERY future Invoice +
    その PDF + Hosted Invoice URL + email receipt that Stripe sends to the
    customer (charge.receipt_email経由 fallback も同じ Customer object 経由).

    Idempotent — Stripe accepts the same payload repeatedly. Skips silently if:
      * customer_id is None (e.g. webhook obj missing it)
      * INVOICE_REGISTRATION_NUMBER is empty (dev/CI; production-only pattern
        per env-gating spec — empty env == feature off, no footer)
      * Stripe call fails (logged but never breaks webhook idempotency)

    Operator: Bookyou株式会社 (T8010001213708). See memory
    `project_bookyou_invoice` for entity binding.
    """
    if not customer_id:
        return
    reg_no = settings.invoice_registration_number
    footer = settings.invoice_footer_ja
    # Empty env → feature OFF (production-only pattern). Both being empty is
    # the dev/CI default, and we never want a half-empty footer in prod, so
    # require BOTH to be set before sending.
    if not reg_no or not footer:
        # R1 from Stripe audit: in prod a missing T番号 is a 適格請求書発行事業者
        # compliance breach (令和7年5月12日, T8010001213708). The Sentry alert
        # rule `invoice_missing_tnumber` (monitoring/sentry_alert_rules.yml)
        # fires on `message:"invoice missing tnumber" level:error`; without
        # this emitter the rule would silently never fire. Dev/CI is exempted
        # because empty env vars are the documented "feature off" path there.
        if settings.env == "prod":
            try:
                from jpintel_mcp.observability import safe_capture_message

                safe_capture_message(
                    "invoice missing tnumber",
                    level="error",
                    customer_id=customer_id,
                    reg_no_set=bool(reg_no),
                    footer_set=bool(footer),
                )
            except Exception:  # noqa: BLE001 — observability cannot raise
                logger.debug("sentry_capture_failed", exc_info=True)
        return
    try:
        # Stripe `invoice_settings.custom_fields` constraints (2024-11-20.acacia):
        #   * max 4 entries
        #   * `name` <= 30 chars, `value` <= 30 chars
        # We use 2 slots (登録番号 + 発行事業者) to keep room for future
        # additions (e.g. お問い合わせ窓口) without breaking this format.
        # Field values are kept ASCII-safe enough for Stripe's PDF renderer
        # (CJK works in 2024-11-20.acacia, verified via stripe_jct_setup.md).
        stripe.Customer.modify(
            customer_id,
            invoice_settings={
                "custom_fields": [
                    {"name": "登録番号", "value": reg_no},
                    {"name": "発行事業者", "value": "Bookyou株式会社"},
                ],
                # `footer` is a free-form string (max 500 chars in
                # 2024-11-20.acacia) printed at the bottom of every Invoice
                # PDF. Carries the 軽減税率対象なし notice + ToS pointer.
                "footer": footer,
            },
        )
        logger.info("invoice_metadata_applied customer=%s reg_no=%s", customer_id, reg_no)
    except Exception as e:
        # NEVER raise: webhook idempotency must hold even if Stripe rejects
        # the modify call (e.g. Customer deleted, restricted key missing
        # `rak_customer_write`). Footer absence is cosmetic, not legal —
        # the 登録番号 also lives in static site copy + receipt_email link.
        # Capture: a sustained `rak_customer_write` revocation would silently
        # strip 適格請求書 footers from every new customer.
        _capture(e)
        logger.warning(
            "apply_invoice_metadata failed customer=%s",
            customer_id,
            exc_info=True,
        )


class CheckoutRequest(BaseModel):
    success_url: str
    cancel_url: str
    customer_email: str | None = None


class CheckoutResponse(BaseModel):
    url: str
    session_id: str


@router.post("/checkout", response_model=CheckoutResponse)
def create_checkout(payload: CheckoutRequest) -> CheckoutResponse:
    s = _stripe()
    price_id = settings.stripe_price_per_request
    if not price_id:
        # Operator-side mis-configuration (Fly secret unset). Was 400, but
        # the caller did nothing wrong — this is a service-availability
        # condition. 503 maps cleanly to the canonical envelope's
        # `service_unavailable` code (see _http_exception_handler in
        # api/main.py) so an LLM caller reading `error.code` sees an
        # actionable retry signal instead of a misleading client-error tag.
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "billing not configured",
        )

    # Stripe Tax + インボイス制度 wiring (see `research/stripe_jct_setup.md`,
    # `docs/stripe_tax_setup.md`):
    #   * automatic_tax — Stripe calculates 消費税 10% and prints the
    #     per-rate table on the 適格請求書. Requires origin=JP + the Price
    #     to have `tax_behavior=exclusive` (external 外税) set.
    #   * tax_id_collection — lets JP B2B buyers enter their own T-号
    #     (jp_trn) so it appears on the 適格請求書 for 仕入税額控除.
    #   * billing_address_collection=required — Stripe Tax needs the
    #     buyer's country to pick JP 10% vs 輸出 0%.
    # Gated on STRIPE_TAX_ENABLED so pre-launch dev/CI without a live tax
    # registration can still exercise Checkout.
    extra: dict = {}
    if settings.stripe_tax_enabled:
        extra["automatic_tax"] = {"enabled": True}
        extra["tax_id_collection"] = {"enabled": True}
        extra["billing_address_collection"] = "required"

    # mode="subscription" with a metered Price (no quantity at checkout time —
    # Stripe bills per reported usage). `line_items[*].quantity` must be
    # omitted for metered prices in 2024-11-20.acacia; sending quantity=1
    # would 400.
    # ToS/Privacy 同意は custom_text.submit.message で submit ボタン直下に
    # 表示する (2026-04-23 修正). 以前の ToS-required consent flag は Stripe
    # Dashboard 側 ToS URL 未設定だと live mode で 500 になるため撤去した
    # (research/data_expansion_design.md:243). リンク先 HTML は
    # https://zeimu-kaikei.ai/tos.html + /privacy.html.
    session = s.checkout.Session.create(
        mode="subscription",
        line_items=[{"price": price_id}],
        success_url=payload.success_url,
        cancel_url=payload.cancel_url,
        customer_email=payload.customer_email,
        allow_promotion_codes=True,
        locale="ja",
        custom_text={
            "submit": {
                "message": (
                    "ご登録により利用規約 (https://zeimu-kaikei.ai/tos.html) "
                    "およびプライバシーポリシー (https://zeimu-kaikei.ai/privacy.html) "
                    "に同意したものとみなされます。"
                )
            }
        },
        **extra,
    )
    return CheckoutResponse(url=session.url, session_id=session.id)


class PortalRequest(BaseModel):
    customer_id: str
    return_url: str


@router.post("/portal")
def create_portal(payload: PortalRequest) -> dict[str, str]:
    s = _stripe()
    portal_kwargs: dict[str, object] = {
        "customer": payload.customer_id,
        "return_url": payload.return_url,
    }
    if settings.stripe_billing_portal_config_id:
        portal_kwargs["configuration_id"] = settings.stripe_billing_portal_config_id
    session = s.billing_portal.Session.create(**portal_kwargs)
    return {"url": session.url}


class KeyIssueRequest(BaseModel):
    session_id: str


class KeyIssueResponse(BaseModel):
    api_key: str
    tier: str
    customer_id: str


@router.post("/keys/from-checkout", response_model=KeyIssueResponse)
def issue_from_checkout(payload: KeyIssueRequest, conn: DbDep) -> KeyIssueResponse:
    """Issue an API key after checkout completion.

    The client holds a session_id from Stripe Checkout. Metered subscriptions
    return `payment_status="no_payment_required"` at session completion (no
    upfront charge — Stripe bills the first invoice at the first cycle).
    Non-paid statuses (e.g. "unpaid") are rejected.
    """
    s = _stripe()
    session = s.checkout.Session.retrieve(payload.session_id)
    # Metered subs have no upfront charge → `no_payment_required`.
    # Non-metered flows would return "paid". Reject anything else so an
    # abandoned checkout cannot mint a key.
    if session.payment_status not in ("paid", "no_payment_required"):
        raise HTTPException(status.HTTP_402_PAYMENT_REQUIRED, "checkout session not paid")

    customer_id = session.customer
    sub_id = session.subscription
    sub = s.Subscription.retrieve(sub_id)
    price_id = sub["items"]["data"][0]["price"]["id"]
    tier = resolve_tier_from_price(price_id)

    existing = conn.execute(
        "SELECT key_hash FROM api_keys WHERE stripe_subscription_id = ? AND revoked_at IS NULL LIMIT 1",
        (sub_id,),
    ).fetchone()
    if existing:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "api key already issued for this subscription; use /v1/billing/portal to rotate",
        )

    # D+0 welcome. Email comes from Checkout's customer_details; fall back
    # to customer_email if the buyer used an existing Stripe Customer.
    _recipient = (
        getattr(session, "customer_details", None)
        and getattr(session.customer_details, "email", None)
    ) or getattr(session, "customer_email", None)
    raw = issue_key(
        conn,
        customer_id=customer_id,
        tier=tier,
        stripe_subscription_id=sub_id,
        customer_email=_recipient,
    )
    # Route the D+0 welcome through the durable queue with the SAME dedup_key
    # the webhook path uses (audit P0-2, 2026-04-26). The success.html POST
    # and the `customer.subscription.created` webhook race; without a shared
    # dedup table the inline send + queued send both fire and the customer
    # gets two welcome mails. The worker's send_welcome only emails
    # key_last4 (raw key is not transmitted via Postmark — only shown once
    # on success.html), so the queue payload omits the raw key entirely.
    from jpintel_mcp.api._bg_task_queue import enqueue as _bg_enqueue

    _bg_enqueue(
        conn,
        kind="welcome_email",
        payload={"to": _recipient, "key_last4": raw[-4:] if raw else "????", "tier": tier},
        dedup_key=f"welcome:{sub_id}",
    )
    return KeyIssueResponse(api_key=raw, tier=tier, customer_id=customer_id)


@router.post("/webhook")
async def webhook(
    request: Request,
    conn: DbDep,
    background_tasks: BackgroundTasks,
    stripe_signature: Annotated[str | None, Header(alias="stripe-signature")] = None,
) -> dict[str, str]:
    """Stripe webhook endpoint.

    P1 perf fix (audit a9fd80e134b538a32, 2026-04-25): outbound HTTP
    (Stripe.modify, Stripe.retrieve, Postmark sends) is scheduled via
    `BackgroundTasks` so it fires AFTER the 200 has been sent. Stripe
    expects 200 within 5s; the previous inline path could exceed that
    on Stripe API or Postmark slow-paths and trigger redelivery.

    Order on the request path (all fast, all in-process / SQLite):
      1. Content-Length guard
      2. Read body + signature verify
      3. Livemode guard
      4. Dedup INSERT into `stripe_webhook_events` (BEGIN IMMEDIATE)
      5. Synchronous DB writes (issue_key, update_tier, revoke_subscription,
         update_subscription_status_*) — all SQLite, sub-millisecond
      6. COMMIT
      7. Schedule slow ops via background_tasks (Stripe API + Postmark)
      8. Return 200

    Background tasks open their OWN DB connection where needed — the
    request-scoped `conn` is closed by FastAPI before BackgroundTasks
    fire.
    """
    _stripe()
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > 1_048_576:  # 1 MB
        raise HTTPException(
            status_code=413,
            detail={"error": "out_of_range", "message": "payload too large"},
        )
    body = await request.body()
    if not settings.stripe_webhook_secret:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "webhook secret unset")
    try:
        event = stripe.Webhook.construct_event(
            body, stripe_signature or "", settings.stripe_webhook_secret
        )
    except stripe.SignatureVerificationError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "bad signature") from None

    # P3.5 latent bug fix (2026-04-25): stripe 15.x returns Event objects
    # whose `.get(...)` is unreliable on attribute-style access — `event["id"]`
    # is the documented stable accessor across SDK versions. We still keep
    # the empty-string fallback for the construct_event-stub path used by the
    # dedup tests where a raw dict is fed in (the dict has the key by
    # construction, but a defensive `or ""` guards against pathological stubs
    # that omit it). Same treatment for `livemode`.
    etype = event["type"]
    obj = event["data"]["object"]
    try:
        event_id = event["id"] or ""
    except (KeyError, TypeError):
        event_id = ""
    try:
        event_livemode = bool(event["livemode"])
    except (KeyError, TypeError):
        event_livemode = False
    logger.info("stripe.event type=%s id=%s livemode=%s", etype, event_id, event_livemode)

    # ---- Fix 2: livemode mismatch guard -----------------------------------
    # Block accidental test→prod or prod→test routing. We compare the
    # event's `livemode` flag against `settings.env == "prod"`. Returning
    # 200 (not 400) tells Stripe to STOP retrying — a misrouted event will
    # never become valid by retrying.
    is_production = settings.env == "prod"
    if event_livemode != is_production:
        logger.error(
            "stripe.webhook.livemode_mismatch event_id=%s event_livemode=%s "
            "is_production=%s — refusing to process",
            event_id,
            event_livemode,
            is_production,
        )
        return {"status": "livemode_mismatch_ignored"}

    # ---- Fix 1: event-level idempotency dedup -----------------------------
    # Stripe retries each event up to 3 days. Subscription-level dedup
    # (api_keys.stripe_subscription_id) prevents double-issuance, but the
    # secondary side-effects (welcome email, live retrieve, status cache
    # writes) can still fire twice on retry. The dedup table short-circuits
    # before any handler runs.
    if event_id:
        existing = conn.execute(
            "SELECT 1 FROM stripe_webhook_events WHERE event_id = ?",
            (event_id,),
        ).fetchone()
        if existing:
            logger.info(
                "stripe.webhook.duplicate_ignored event_id=%s type=%s",
                event_id,
                etype,
            )
            return {"status": "duplicate_ignored"}
        # Record the event BEFORE dispatch. If the handler raises, the row
        # stays — the next retry short-circuits (the partial side-effects
        # already happened, retrying would compound them). Operators
        # diagnose failures via Sentry + logs, not via Stripe retries.
        # ---- Fix 3: BEGIN IMMEDIATE serialization -----------------------
        # session.connect() runs in autocommit (isolation_level=None).
        # Wrapping the dedup INSERT + dispatch body in BEGIN IMMEDIATE
        # acquires the SQLite RESERVED lock up-front so concurrent
        # webhook deliveries for the same customer (e.g. invoice.paid +
        # subscription.updated arriving in the same second) serialize
        # cleanly instead of racing on the api_keys writes.
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "INSERT INTO stripe_webhook_events"
                " (event_id, event_type, livemode, received_at)"
                " VALUES (?, ?, ?, datetime('now'))",
                (event_id, etype, 1 if event_livemode else 0),
            )
        except Exception as begin_exc:
            # If BEGIN fails (already in a transaction) or the INSERT
            # races a concurrent delivery to the unique event_id, fall
            # back to the duplicate path and re-check.
            try:
                conn.execute("ROLLBACK")
            except Exception:
                pass
            re_check = conn.execute(
                "SELECT 1 FROM stripe_webhook_events WHERE event_id = ?",
                (event_id,),
            ).fetchone()
            if re_check:
                logger.info(
                    "stripe.webhook.duplicate_ignored_race event_id=%s",
                    event_id,
                )
                return {"status": "duplicate_ignored"}
            # Real DB error (lock timeout under load, schema drift, disk
            # full) — not a duplicate race. P0: Stripe will retry, but
            # without Sentry capture an SQLite lock storm during launch
            # would silently drop key issuance until the operator
            # noticed via "where is my key" support traffic.
            _capture(begin_exc)
            logger.error(
                "stripe.webhook.dedup_insert_failed event_id=%s",
                event_id,
                exc_info=True,
            )
            raise

    # Wrap dispatch in try/except so a handler raise does NOT prevent the
    # dedup row from being COMMIT'd (P1, audit 2026-04-26). Without this,
    # an `update_tier_by_subscription` re-raising a transient sqlite error
    # rolls back the BEGIN IMMEDIATE, the dedup row never persists, Stripe
    # retries the same event_id within minutes, and every side-effect that
    # already succeeded (key issue, welcome enqueue, tax-id check) fires
    # again. Trade-off: we accept "one event lost on hard handler failure"
    # (visible in Sentry + logs) in exchange for "no re-fire storms" —
    # correct for solo ops where a 3-day Stripe retry window can compound
    # damage faster than the operator can intervene.
    _handler_exc: BaseException | None = None
    try:
        # Metered billing: `customer.subscription.created` fires immediately on
        # Checkout completion (before any invoice). That is the primary moment
        # to issue the API key so the customer can start calling /v1 without
        # waiting for the first billing cycle.
        if etype == "customer.subscription.created":
            sub_id = obj.get("id")
            customer_id = obj.get("customer")
            if sub_id and customer_id:
                # Issue the key SYNCHRONOUSLY so a buyer hitting /v1 immediately
                # after Checkout has a row to authenticate against. Welcome
                # email is deferred via background_tasks (Postmark P95 too slow
                # for the 5s Stripe deadline).
                _issue_key_for_subscription(
                    conn,
                    sub_id=sub_id,
                    customer_id=customer_id,
                    obj=obj,
                    background_tasks=background_tasks,
                )
                # Cache subscription state for /v1/me dunning banner (migration
                # 052). The webhook payload carries `status`, `current_period_end`,
                # and `cancel_at_period_end` directly. Run AFTER _issue_key_for_subscription
                # so the new api_keys row exists and gets updated on the same call.
                status_val, cpe_int, cancel_bool = _extract_subscription_state(obj)
                if status_val:
                    update_subscription_status(
                        conn,
                        sub_id,
                        status=status_val,
                        current_period_end=cpe_int,
                        cancel_at_period_end=cancel_bool,
                    )
                # Stripe API calls (Customer.modify, Customer.retrieve) deferred
                # to BackgroundTasks — both are slow paths off the critical path.
                # `_apply_invoice_metadata_safe`: stamps 適格請求書 footer +
                # 登録番号 on the Customer. Stripe copies these to every future
                # Invoice at draft time, so applying once-per-event is fine.
                # `_check_b2b_tax_id_safe`: log-only INV-23 warning, never
                # blocks the customer.
                background_tasks.add_task(_apply_invoice_metadata_safe, customer_id)
                background_tasks.add_task(_check_b2b_tax_id_safe, customer_id)

        elif etype == "invoice.paid":
            # Safety net: if subscription.created was missed (webhook delivery
            # failure during the first seconds of the sub), the first
            # invoice.paid still issues the key.
            sub_id = obj.get("subscription")
            customer_id = obj.get("customer")
            if sub_id and customer_id:
                _issue_key_for_subscription(
                    conn,
                    sub_id=sub_id,
                    customer_id=customer_id,
                    obj=obj,
                    email_fallback=obj.get("customer_email"),
                    background_tasks=background_tasks,
                )
                # Un-suspend: if a prior payment_failed demoted the key to free,
                # restoring tier=paid here re-enables the ¥3/req metered path.
                # No-op when the key is already paid.
                n = update_tier_by_subscription(conn, sub_id, "paid")
                if n:
                    logger.info("key_unsuspended_on_paid sub=%s rows=%d", sub_id, n)
                # Re-apply invoice metadata defensively (Stripe API call) +
                # re-sync subscription_status from Stripe (Stripe API call) —
                # both deferred to BackgroundTasks. The status refresh uses
                # its own DB connection because the request-scoped conn is
                # closed by the time background tasks fire.
                background_tasks.add_task(_apply_invoice_metadata_safe, customer_id)
                # Durable enqueue (migration 060). The Stripe Subscription
                # retrieve is what actually populates the dashboard's dunning
                # banner (`api_keys.stripe_subscription_*`); a SIGTERM between
                # webhook commit and the retrieve would leave the cache stale
                # for every paid customer until the next dunning event.
                from jpintel_mcp.api._bg_task_queue import enqueue as _bg_enqueue

                _bg_enqueue(
                    conn,
                    kind="stripe_status_refresh",
                    payload={"sub_id": sub_id},
                    # Per-event dedup so a redelivered invoice.paid does not
                    # queue two refreshes; latest event_id wins.
                    dedup_key=f"stripe_status_refresh:{event_id}:{sub_id}",
                )
        elif etype == "customer.subscription.updated":
            sub_id = obj.get("id")
            # The outer `BEGIN IMMEDIATE` on `conn` (Fix 3 dedup
            # transaction) already holds the SQLite RESERVED writer
            # lock, so any concurrent `stripe_status_refresh` worker
            # opening a fresh connection is automatically serialized at
            # the SQLite level — there is no race the application code
            # can introduce. A previous version opened a SECOND
            # connection inside this branch and asked it to take an
            # advisory lock; that deadlocked the request against itself
            # (the second conn waited on the RESERVED lock held by the
            # request conn for the full 300s busy_timeout). Removing
            # the advisory_lock attempt is correct because:
            #   1. The outer BEGIN IMMEDIATE already serializes writers.
            #   2. The webhook payload IS the authoritative tier change
            #      source, so even if a concurrent refresh did sneak in
            #      between transactions, applying the webhook tier last
            #      wins — losing it (LockNotAcquired path before) was
            #      strictly worse than letting it execute under the
            #      regular SQLite writer-serialization.
            price_id = obj["items"]["data"][0]["price"]["id"]
            tier = resolve_tier_from_price(price_id)
            n = update_tier_by_subscription(conn, sub_id, tier)
            logger.info("tier-updated sub=%s tier=%s rows=%d", sub_id, tier, n)
            # Cache the new subscription state. The payload carries the
            # updated status / period_end / cancel flag, so no live
            # retrieve needed.
            status_val, cpe_int, cancel_bool = _extract_subscription_state(obj)
            if status_val:
                update_subscription_status(
                    conn,
                    sub_id,
                    status=status_val,
                    current_period_end=cpe_int,
                    cancel_at_period_end=cancel_bool,
                )
        elif etype == "customer.subscription.deleted":
            sub_id = obj.get("id")
            n = revoke_subscription(conn, sub_id)
            logger.info("revoked keys for sub=%s rows=%d", sub_id, n)
            # Mark the cached status as 'canceled' for any rows that still exist
            # (e.g. legacy double-keys). update_subscription_status only touches
            # rows with revoked_at IS NULL, so this is a near no-op after the
            # revoke_subscription call above — kept for completeness in case
            # the deletion arrives without the prior subscription.updated event.
            update_subscription_status_by_id(conn, sub_id, "canceled")
        elif etype == "invoice.payment_failed":
            sub_id = obj.get("subscription")
            customer_id = obj.get("customer")
            attempt = obj.get("attempt_count", 1)
            # Demote to free quota (rate_limit_free_per_day, daily cap) immediately
            # so a failing card cannot keep racking up metered usage during Stripe's
            # dunning window. Distinct from anon Free tier (50/month IP-based).
            # invoice.paid re-promotes to paid if the retry succeeds;
            # customer.subscription.deleted revokes entirely on final failure.
            n = 0
            if sub_id:
                n = update_tier_by_subscription(conn, sub_id, "free")
                # Cache 'past_due' for the dashboard dunning banner — but only
                # if the current cached status is not already worse (canceled /
                # unpaid). This avoids regressing 'canceled' back to 'past_due'
                # if Stripe delivers events out of order during the dunning
                # window.
                cur = conn.execute(
                    "SELECT stripe_subscription_status FROM api_keys "
                    "WHERE stripe_subscription_id = ? AND revoked_at IS NULL "
                    "LIMIT 1",
                    (sub_id,),
                ).fetchone()
                current_status = cur[0] if cur else None
                if current_status not in ("canceled", "unpaid"):
                    update_subscription_status_by_id(conn, sub_id, "past_due")
            logger.warning(
                "key_suspended_dunning sub=%s customer=%s attempt=%d rows=%d — "
                "demoted to free quota; Stripe dunning continues, "
                "full revoke on customer.subscription.deleted.",
                sub_id,
                customer_id,
                attempt,
                n,
            )
            # Send dunning notice to the affected customer. Stripe's own
            # subscription dunning emails are opt-in per Dashboard config; we
            # send our own so the recipient hears the same voice as onboarding
            # / receipts. Deferred via BackgroundTasks (Postmark API call off
            # the request path; helper opens its own DB connection because
            # the request-scoped conn is closed by then).
            # Durable enqueue (migration 060). Past-due dunning notice tells
            # the customer their card is failing — losing it on a process
            # restart while the customer's card stays declined burns the
            # 3-attempt Stripe dunning window without the customer ever knowing.
            # Dedup on `(sub_id, attempt)` so a Stripe redelivery of the same
            # invoice.payment_failed event does not double-mail.
            from jpintel_mcp.api._bg_task_queue import enqueue as _bg_enqueue

            _bg_enqueue(
                conn,
                kind="dunning_email",
                payload={
                    "to": obj.get("customer_email"),
                    "sub_id": sub_id,
                    "attempt_count": attempt,
                    "next_retry_epoch": obj.get("next_payment_attempt"),
                },
                dedup_key=f"dunning:{sub_id}:{attempt}",
            )
        elif etype == "charge.refunded":
            # A refund (full or partial) is a strong fraud / chargeback signal —
            # revoke the customer's API keys so a refunded request cannot keep
            # generating metered usage on top of the refund. We revoke ALL
            # active keys for the customer (rather than only the subscription
            # tied to the specific charge) because a refund usually accompanies
            # a closed account and lingering keys present credential-leak risk.
            # The Stripe `charge` object exposes the customer_id directly; the
            # subscription_id is reachable via `invoice` only when the charge
            # came from a sub invoice, so customer-scope is the safer key.
            customer_id = obj.get("customer")
            charge_id = obj.get("id")
            amount_refunded = obj.get("amount_refunded", 0)
            n = 0
            revoked_hashes: list[str] = []
            if customer_id:
                now = datetime.now(UTC).isoformat()
                # Capture the affected key_hashes BEFORE the UPDATE so we can
                # emit one audit_log row per key (P1, audit a4298e454aab2aa43).
                revoked_hashes = [
                    r["key_hash"]
                    for r in conn.execute(
                        "SELECT key_hash FROM api_keys "
                        "WHERE customer_id = ? AND revoked_at IS NULL",
                        (customer_id,),
                    ).fetchall()
                ]
                cur = conn.execute(
                    "UPDATE api_keys SET revoked_at = ? "
                    "WHERE customer_id = ? AND revoked_at IS NULL",
                    (now, customer_id),
                )
                n = cur.rowcount
            logger.warning(
                "key_revoked_on_refund customer=%s charge=%s amount=%s rows=%d",
                customer_id,
                charge_id,
                amount_refunded,
                n,
            )
            # P1 audit-log every revoked key (audit a4298e454aab2aa43). Inline
            # import keeps the webhook hot path free of extra import cost on the
            # 99% of events that aren't refunds.
            if revoked_hashes:
                from jpintel_mcp.api._audit_log import log_event

                for kh in revoked_hashes:
                    log_event(
                        conn,
                        event_type="key_revoke",
                        key_hash=kh,
                        customer_id=customer_id,
                        request=None,
                        reason="charge.refunded",
                        stripe_charge_id=charge_id,
                        amount_refunded=amount_refunded,
                    )

        elif etype in ("charge.dispute.created", "charge.dispute.closed"):
            # P3.5 edge case 2: chargeback / dispute. Operator notification
            # only — never auto-revokes. ``charge.refunded`` already handles
            # the lost-dispute downstream; this branch covers the
            # created/won lifecycle that lives outside the refund path.
            from jpintel_mcp.billing.stripe_edge_cases import handle_dispute_event

            handle_dispute_event(conn, etype, obj if isinstance(obj, dict) else {})
        elif etype == "customer.updated":
            # P3.5 edge case 3: tax-exempt customer detection. Operators
            # flip ``customer.metadata.tax_exempt`` from the Dashboard; we
            # mirror it into the first-class ``customer.tax_exempt`` field
            # so Stripe Tax suppresses 消費税 on the next invoice.
            from jpintel_mcp.billing.stripe_edge_cases import handle_tax_exempt_event

            handle_tax_exempt_event(conn, etype, obj if isinstance(obj, dict) else {})
        elif etype == "invoice.created":
            # P3.5 edge cases 3 + 4 (combined trigger): defensive tax-exempt
            # re-apply on every new draft invoice + non-JPY currency edge
            # detection. Both handlers are idempotent and non-raising.
            from jpintel_mcp.billing.stripe_edge_cases import (
                handle_currency_edge,
                handle_tax_exempt_event,
            )

            handle_tax_exempt_event(conn, etype, obj if isinstance(obj, dict) else {})
            handle_currency_edge(conn, etype, obj if isinstance(obj, dict) else {})
        elif etype in ("invoice.updated", "invoice.voided"):
            # P3.5 edge case 5: invoice modification / re-issuance audit
            # trail. Common operator path: void a wrong 適格請求書 + re-issue.
            from jpintel_mcp.billing.stripe_edge_cases import (
                handle_invoice_modification_event,
            )

            handle_invoice_modification_event(
                conn, etype, obj if isinstance(obj, dict) else {}
            )
        elif etype == "customer.subscription.trial_will_end":
            # Stripe fires this 3 days before a free-trial expires. We do NOT
            # currently use trial periods on the metered ¥3/req plan, but Stripe
            # may emit it for legacy / promo subscriptions. Audit-log only — the
            # email reminder is a future task; for now we just record receipt
            # so a future "where did my trial-end notice go" support ticket has
            # a forensic trail. No tier flip, no key revoke.
            sub_id = obj.get("id") if isinstance(obj, dict) else None
            customer_id = obj.get("customer") if isinstance(obj, dict) else None
            trial_end_epoch = obj.get("trial_end") if isinstance(obj, dict) else None
            try:
                from jpintel_mcp.api._audit_log import log_event

                log_event(
                    conn,
                    event_type="stripe.subscription.trial_will_end",
                    customer_id=customer_id,
                    request=None,
                    stripe_subscription_id=sub_id,
                    trial_end_epoch=trial_end_epoch,
                )
            except Exception as audit_exc:
                # Audit-log helper is already non-raising, but a missing import
                # path / schema drift on a partial migration must never 500
                # Stripe. Capture so a regression is visible in Sentry.
                _capture(audit_exc)
                logger.warning(
                    "trial_will_end_audit_failed sub=%s",
                    sub_id,
                    exc_info=True,
                )
            logger.info(
                "stripe.subscription.trial_will_end sub=%s customer=%s "
                "trial_end=%s — audit logged, no email yet (future task).",
                sub_id,
                customer_id,
                trial_end_epoch,
            )
    except Exception as handler_exc:  # noqa: BLE001
        # Hold the exception so we can still COMMIT the dedup row before
        # returning. We deliberately swallow all dispatch failures here —
        # returning 200 to Stripe with the dedup row persisted means the
        # event will not retry. The operator sees the failure in Sentry +
        # logs and can replay manually if needed (Stripe Dashboard supports
        # event re-send for any single event_id).
        _handler_exc = handler_exc
        _capture(handler_exc)
        logger.exception(
            "stripe.webhook.handler_failed event_id=%s type=%s — "
            "committing dedup row to suppress retry storm",
            event_id,
            etype,
        )

    # ---- Fix 3 (cont): commit the dedup transaction + mark processed -----
    # If we opened a BEGIN IMMEDIATE for this event (event_id non-empty),
    # mark it processed and COMMIT. The dispatch above is wrapped in a
    # try/except (P1, 2026-04-26) so a handler raise still reaches this
    # block — without that, the open BEGIN IMMEDIATE rolled back via
    # FastAPI's connection-close, the dedup row vanished, and Stripe
    # retried the same event_id (re-firing every successful side-effect).
    if event_id:
        try:
            conn.execute(
                "UPDATE stripe_webhook_events SET processed_at = datetime('now')"
                " WHERE event_id = ?",
                (event_id,),
            )
            conn.execute("COMMIT")
        except Exception as commit_exc:
            try:
                conn.execute("ROLLBACK")
            except Exception:
                pass
            # COMMIT failure means the dedup row + side-effects roll back,
            # Stripe retries the same event_id. Capture so a sustained
            # COMMIT failure pattern (disk full / WAL truncation) is
            # noticed before retry storms.
            _capture(commit_exc)
            raise
    return {"status": "received"}


def _issue_key_for_subscription(
    conn,
    *,
    sub_id: str,
    customer_id: str,
    obj: dict,
    email_fallback: str | None = None,
    background_tasks: BackgroundTasks | None = None,
) -> None:
    """Mint a key for a subscription iff none exists.

    Idempotent across duplicate webhook deliveries (Stripe retries up to 3
    days). Shared by `customer.subscription.created` and `invoice.paid` so
    a missed delivery of the former still recovers via the latter.

    When `background_tasks` is provided, the welcome email is scheduled via
    BackgroundTasks (fires after the response is sent) so the webhook can
    return 200 inside Stripe's 5s budget. When None (legacy callers like
    `issue_from_checkout`), the email sends inline.
    """
    has_key = conn.execute(
        "SELECT 1 FROM api_keys WHERE stripe_subscription_id = ? LIMIT 1",
        (sub_id,),
    ).fetchone()
    if has_key:
        return

    # subscription.created carries items[] directly; invoice.paid does not,
    # so we retrieve the Subscription to read the price id.
    items = obj.get("items") if isinstance(obj, dict) else None
    if items and items.get("data"):
        price_id = items["data"][0]["price"]["id"]
    else:
        sub = stripe.Subscription.retrieve(sub_id)
        price_id = sub["items"]["data"][0]["price"]["id"]

    tier = resolve_tier_from_price(price_id)

    # subscription.created has no customer_email field; we'd need to
    # retrieve the Customer to know the email. For now accept the
    # fallback (from invoice.paid) or None — key still issues.
    _recipient = email_fallback
    raw = issue_key(
        conn,
        customer_id=customer_id,
        tier=tier,
        stripe_subscription_id=sub_id,
        customer_email=_recipient,
    )
    logger.info(
        "issued api_key via webhook sub=%s tier=%s (key prefix=%s)",
        sub_id,
        tier,
        raw[:8],
    )
    if background_tasks is not None:
        # Defer Postmark call off the request path (P1 perf fix per audit
        # a9fd80e134b538a32) — but route through the durable bg_task_queue
        # (migration 060, P0 bg-task-durability) instead of in-memory
        # FastAPI BackgroundTasks. The welcome mail itself only carries
        # key_last4 (raw key is shown exactly once on success.html); the
        # queue payload therefore omits the raw key — storing it in
        # plaintext SQLite would be a credential-leak surface (P1, audit
        # 2026-04-26). Idempotent on `welcome:<sub_id>` so a Stripe webhook
        # redelivery (3-day retry window) does not double-mail.
        from jpintel_mcp.api._bg_task_queue import enqueue as _bg_enqueue

        _bg_enqueue(
            conn,
            kind="welcome_email",
            payload={"to": _recipient, "key_last4": raw[-4:] if raw else "????", "tier": tier},
            dedup_key=f"welcome:{sub_id}",
        )
    else:
        # Legacy non-webhook caller (no BackgroundTasks scope) — route
        # through the queue so we still hit the shared dedup gate.
        from jpintel_mcp.api._bg_task_queue import enqueue as _bg_enqueue

        _bg_enqueue(
            conn,
            kind="welcome_email",
            payload={"to": _recipient, "key_last4": raw[-4:] if raw else "????", "tier": tier},
            dedup_key=f"welcome:{sub_id}",
        )
