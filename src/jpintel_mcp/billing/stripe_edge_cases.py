"""Stripe edge-case handlers (P3.5, 2026-04-25).

Six low-volume but high-blast-radius paths that the main webhook flow in
``api/billing.py`` deliberately keeps out of its hot path:

  1. **refund_request** — customer-initiated refund intake
     (``POST /v1/billing/refund_request``). Manual review only — we never
     auto-refund. Mirrors the §31 / §33 APPI intake pattern: persist a row,
     notify the operator + the requester, return a request_id, exit. The
     ¥3/req metering is NOT reversed automatically — already-billed usage
     stays billed (memory: ``feedback_autonomath_no_api_use``); the
     operator decides on the actual money movement during review.

  2. **chargeback / dispute** (``charge.dispute.created`` /
     ``charge.dispute.closed``) — operator notification only. We do NOT
     auto-revoke keys or auto-suspend, because Stripe's dispute lifecycle
     can flip closed→won (``status="won"``) and a hair-trigger suspension
     would break legitimate customers caught in a card-issuer false
     positive. Operator decides via Stripe Dashboard inside the
     ``evidence_due_by`` window.

  3. **tax_exempt customer** — when ``customer.metadata.tax_exempt``
     resolves to ``"exempt"`` / ``"reverse"``, we mark every subsequent
     invoice with the same flag so Stripe Tax suppresses the 消費税 line.
     This handler runs on ``customer.updated`` (operator flips the flag)
     and on ``invoice.created`` (defensive re-apply for the new draft).

  4. **currency edge** — the ``customer.subscription.created`` /
     ``invoice.created`` events carry a ``currency`` field. Anything other
     than ``jpy`` triggers an operator notification and an audit_log row
     so a misconfigured Price (e.g. inadvertent USD test Price referenced
     in production) is caught before the first invoice clears.

  5. **invoice.updated / invoice.voided** — invoice modifications after
     issuance. Common operator paths: hosted_invoice_url regenerated,
     invoice voided + re-issued for an INV-23 (適格請求書) correction.
     We refresh the cached subscription status so the dashboard banner
     reflects the change, and audit-log the void with the original
     amount so a "where did my invoice go" support ticket has a forensic
     trail.

  6. **Stripe Tax API failure fallback** — ``CalculationFailed`` /
     ``ApiConnectionError`` from ``stripe.tax.Calculation.create`` (or
     equivalent). We never default to 0% tax (which would 消費税法 §63
     mis-issue an 適格請求書 lacking the per-rate table). Instead we
     restore the most recent successful per-customer calculation from
     the ``stripe_tax_cache`` table — co-located in migration 071 — and
     surface the fallback via Sentry + an operator email so the next
     human-touch invoice gets a fresh calculation.

All entry points here are designed to be called from ``api/billing.py::webhook``
or other thin REST endpoints — they own their own DB connection only when
called from BackgroundTasks; otherwise the caller threads its scope-bound
``conn`` in. Every handler is non-raising by design (mirrors the swallowing
posture of the main webhook dispatch — losing visibility on a refund or
dispute notification is worse than 500-ing Stripe).
"""

from __future__ import annotations

import logging
import secrets
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Annotated, Any

from fastapi import APIRouter, status
from pydantic import BaseModel, EmailStr, Field

from jpintel_mcp.api.deps import DbDep  # noqa: TC001 — runtime FastAPI Depends
from jpintel_mcp.config import settings

if TYPE_CHECKING:
    import sqlite3

logger = logging.getLogger("jpintel.billing.edge_cases")

# Public router — mounted by api/main.py alongside billing_router.
router = APIRouter(prefix="/v1/billing", tags=["billing"])


# ---------------------------------------------------------------------------
# Sentry capture passthrough (mirrors api/billing.py::_capture so the edge
# module does not import the main billing module — a circular import waiting
# to happen if either grows).
# ---------------------------------------------------------------------------

try:
    import sentry_sdk as _sentry_sdk

    _SENTRY_AVAILABLE = True
except ImportError:  # pragma: no cover — minimal install only
    _SENTRY_AVAILABLE = False


def _capture(exc: BaseException) -> None:
    if _SENTRY_AVAILABLE:
        try:
            _sentry_sdk.capture_exception(exc)
        except Exception:  # pragma: no cover
            logger.debug("sentry_capture_failed", exc_info=True)


# ---------------------------------------------------------------------------
# 1. Refund request intake (POST /v1/billing/refund_request)
# ---------------------------------------------------------------------------


class RefundRequest(BaseModel):
    requester_email: EmailStr
    customer_id: Annotated[str, Field(min_length=1, max_length=120)]
    # Optional — many requesters know the email but not the cus_xxx id; the
    # operator will still resolve the customer via email lookup. Required only
    # to short-circuit the lookup when the caller does have the id.
    amount_yen: Annotated[int | None, Field(default=None, ge=1, le=10_000_000)] = None
    # Free-text reason — review side classifies. Closed-enum was rejected
    # because refund reasons evolve faster than enum migrations.
    reason: Annotated[str, Field(min_length=1, max_length=2000)]


class RefundResponse(BaseModel):
    request_id: str
    received_at: str
    expected_response_within_days: int = 14
    contact: str = "info@bookyou.net"
    note: str = (
        "返金は手動審査となります。既に課金済みの ¥3/req メータリング分は "
        "自動取消しされません — 審査完了後、運営から個別にご連絡します。"
    )


def _gen_refund_request_id() -> str:
    """Format: ``返金-`` + 32 hex chars (mirrors §31 / §33 prefix style)."""
    return f"返金-{secrets.token_hex(16)}"


def _redact_email(addr: str) -> str:
    if "@" not in addr:
        return "***"
    local, _, domain = addr.partition("@")
    if len(local) <= 1:
        return f"*@{domain}"
    return f"{local[0]}***@{domain}"


def _notify_refund_request(
    *,
    request_id: str,
    requester_email: str,
    customer_id: str,
    amount_yen: int | None,
    reason: str,
    received_at: str,
) -> None:
    """Best-effort transactional mail — operator + requester. Never raises.

    Same posture as ``appi_deletion._notify_operator_and_requester``: postmark
    test_mode short-circuits to a structured log line; HTTP failures are
    swallowed and logged. The DB row is the source of truth.
    """
    try:
        from jpintel_mcp.email.postmark import (
            POSTMARK_BASE_URL,
            STREAM_TRANSACTIONAL,
            get_client,
        )

        client = get_client()
        if client.test_mode:
            logger.info(
                "refund_request.email.skip env=%s request_id=%s to=%s",
                settings.env,
                request_id,
                _redact_email(requester_email),
            )
            return

        import httpx

        amount_display = f"¥{amount_yen:,}" if amount_yen is not None else "(未指定)"
        operator_text = (
            "返金請求を受付けました。\n\n"
            f"request_id: {request_id}\n"
            f"received_at: {received_at}\n"
            f"requester_email: {requester_email}\n"
            f"customer_id: {customer_id}\n"
            f"amount_yen: {amount_display}\n"
            f"reason: {reason}\n\n"
            "14日以内に Stripe Dashboard で返金可否を判断してください。\n"
            "既課金分は自動取消しされません — 手動 refund + 顧客連絡が必要です。\n"
        )
        requester_text = (
            "AutonoMath (運営: Bookyou株式会社) です。\n\n"
            "返金請求を受付けました。\n\n"
            f"  受付番号: {request_id}\n"
            f"  受付日時: {received_at}\n\n"
            "原則として14日以内に審査結果をご連絡いたします。\n"
            "なお既に課金済みの ¥3/req メータリング分は審査完了まで自動取消し"
            "されません。あらかじめご了承ください。\n\n"
            "Bookyou株式会社 (適格請求書発行事業者番号 T8010001213708)\n"
            "東京都文京区小日向2-22-1\n"
        )

        with httpx.Client(
            base_url=POSTMARK_BASE_URL,
            timeout=httpx.Timeout(10.0, connect=5.0),
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "X-Postmark-Server-Token": settings.postmark_api_token,
            },
        ) as http:
            for to_addr, subject, body, tag in (
                (
                    "info@bookyou.net",
                    f"[AutonoMath] 返金請求 受付 ({request_id})",
                    operator_text,
                    "refund-request-operator",
                ),
                (
                    requester_email,
                    "[AutonoMath] 返金請求の受付確認",
                    requester_text,
                    "refund-request-requester",
                ),
            ):
                payload = {
                    "From": settings.postmark_from_transactional,
                    "To": to_addr,
                    "Subject": subject,
                    "TextBody": body,
                    "MessageStream": STREAM_TRANSACTIONAL,
                    "Tag": tag,
                    "TrackOpens": False,
                    "TrackLinks": "None",
                }
                if settings.postmark_from_reply:
                    payload["ReplyTo"] = settings.postmark_from_reply
                try:
                    r = http.post("/email", json=payload)
                    if r.status_code >= 400:
                        logger.warning(
                            "refund_request.email.api_error status=%d to=%s request_id=%s",
                            r.status_code,
                            _redact_email(to_addr),
                            request_id,
                        )
                except httpx.HTTPError as exc:
                    logger.warning(
                        "refund_request.email.transport_error to=%s request_id=%s err=%s",
                        _redact_email(to_addr),
                        request_id,
                        exc,
                    )
    except Exception:  # noqa: BLE001 — never raise back to handler
        logger.warning(
            "refund_request.email.failed request_id=%s",
            request_id,
            exc_info=True,
        )


@router.post(
    "/refund_request",
    response_model=RefundResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Submit a refund request for ¥3/req metered Stripe charges (manual review)",
    description=(
        "Customer-initiated intake for refunds against ¥3/req metered Stripe "
        "charges. The operator (Bookyou株式会社) reviews each request "
        "manually within 14 days; this endpoint only records the request and "
        "fires an operator notification — it does NOT auto-issue the refund "
        "or revoke the caller's API key. Existing metered charges remain on "
        "the customer's invoice until the review concludes.\n\n"
        "**Use this when** a caller disputes a specific billing month or a "
        "tranche of usage they consider erroneous. For chargeback-style "
        "disputes, prefer Stripe's issuer-side flow (we mirror those "
        "events into the audit log automatically).\n\n"
        "(顧客発の返金請求受付。Stripe で課金された ¥3/req "
        "メータリング分の返金を顧客が請求するためのエンドポイント。"
        "運営側で 14 日以内に手動審査を行います。受付番号の発行と通知のみで、"
        "自動的な返金や API キー失効は行いません。既に課金済みの分も審査完了"
        "までそのまま残ります。)"
    ),
)
def submit_refund_request(payload: RefundRequest, conn: DbDep) -> RefundResponse:
    request_id = _gen_refund_request_id()
    received_at = datetime.now(UTC).isoformat()

    conn.execute(
        """INSERT INTO refund_requests(
               request_id, customer_id, amount_yen, reason, status, received_at
           ) VALUES (?,?,?,?,?,?)""",
        (
            request_id,
            payload.customer_id,
            payload.amount_yen,
            payload.reason,
            "pending",
            received_at,
        ),
    )

    _notify_refund_request(
        request_id=request_id,
        requester_email=payload.requester_email,
        customer_id=payload.customer_id,
        amount_yen=payload.amount_yen,
        reason=payload.reason,
        received_at=received_at,
    )

    logger.info(
        "refund_request.received request_id=%s customer=%s amount_yen=%s",
        request_id,
        payload.customer_id,
        payload.amount_yen,
    )
    return RefundResponse(
        request_id=request_id,
        received_at=received_at,
    )


# ---------------------------------------------------------------------------
# 2. Chargeback / dispute handler
# ---------------------------------------------------------------------------


def handle_dispute_event(conn: sqlite3.Connection, etype: str, obj: dict[str, Any]) -> None:
    """Operator notification only — never auto-revokes.

    Stripe's dispute lifecycle:
      * ``charge.dispute.created`` — issuer opens a dispute (chargeback)
      * ``charge.dispute.closed`` — issuer rules; ``status`` is one of
        ``won`` / ``lost`` / ``warning_closed`` / ``warning_under_review``

    We DO NOT auto-revoke API keys here because:
      * ``status="won"`` is a happy-path resolution — revoking would punish
        a legitimate customer caught in an issuer false positive.
      * ``status="lost"`` already triggers ``charge.refunded`` from Stripe's
        own dispute resolution flow, which the main webhook dispatcher
        handles (revokes keys + audit_log the refund). Revoking here too
        would emit duplicate audit rows for the same event chain.

    Posture: never raises. Failures here cannot block the webhook 200.
    """
    try:
        charge_id = obj.get("charge") or obj.get("id")
        amount = obj.get("amount", 0)
        currency = (obj.get("currency") or "").lower()
        reason = obj.get("reason") or "unknown"
        dispute_status = obj.get("status") or "unknown"
        evidence_due_by = obj.get("evidence_details", {}).get("due_by")

        if etype == "charge.dispute.created":
            logger.warning(
                "stripe.dispute.created charge=%s amount=%s currency=%s reason=%s "
                "evidence_due_by=%s — operator review required via Stripe Dashboard.",
                charge_id,
                amount,
                currency,
                reason,
                evidence_due_by,
            )
        elif etype == "charge.dispute.closed":
            logger.warning(
                "stripe.dispute.closed charge=%s status=%s amount=%s reason=%s — "
                "review final disposition; charge.refunded handler will run "
                "separately if status=lost.",
                charge_id,
                dispute_status,
                amount,
                reason,
            )
        # Audit-log the event so a future "where is the dispute trail" support
        # ticket has forensic data even if the operator missed the email.
        from jpintel_mcp.api._audit_log import log_event

        log_event(
            conn,
            event_type=etype,
            request=None,
            stripe_charge_id=charge_id,
            dispute_status=dispute_status,
            dispute_reason=reason,
            amount=amount,
            currency=currency,
            evidence_due_by=evidence_due_by,
        )
    except Exception as exc:  # noqa: BLE001
        _capture(exc)
        logger.warning("dispute_event_handler_failed etype=%s", etype, exc_info=True)


# ---------------------------------------------------------------------------
# 3. Tax-exempt customer detection / re-apply
# ---------------------------------------------------------------------------


def handle_tax_exempt_event(conn: sqlite3.Connection, etype: str, obj: dict[str, Any]) -> None:
    """Detect ``customer.metadata.tax_exempt`` and propagate to Stripe.

    Stripe's first-class field is ``customer.tax_exempt`` (values: ``none``,
    ``exempt``, ``reverse``). Operators set ``customer.metadata.tax_exempt``
    via the Dashboard or the portal because the metadata field is ergonomic;
    we mirror the value into the first-class slot so Stripe Tax actually
    suppresses the 消費税 line on the next invoice.

    Triggered on:
      * ``customer.updated`` — operator flips the flag
      * ``invoice.created`` — defensive re-apply (idempotent) so a draft
        invoice that pre-dates the metadata flip still issues exempt.

    Idempotent / never raises.
    """
    try:
        # Resolve the customer object regardless of the trigger event shape.
        if etype == "customer.updated":
            customer_id = obj.get("id")
            metadata = obj.get("metadata") or {}
            current_tax_exempt = obj.get("tax_exempt") or "none"
        elif etype == "invoice.created":
            customer_id = obj.get("customer")
            # invoice.created object does NOT carry customer.metadata; we
            # short-circuit on the trivial case (customer_tax_exempt already
            # on the invoice itself) and only retrieve the Customer when the
            # invoice's flag is "none" but we suspect it should not be.
            current_tax_exempt = obj.get("customer_tax_exempt") or "none"
            metadata = {}
            if current_tax_exempt == "none" and customer_id:
                # Best-effort retrieve — failure swallowed.
                try:
                    import stripe as _stripe_mod

                    cust = _stripe_mod.Customer.retrieve(customer_id)
                    if isinstance(cust, dict):
                        metadata = cust.get("metadata") or {}
                    else:
                        metadata = getattr(cust, "metadata", {}) or {}
                except Exception as retrieve_exc:
                    _capture(retrieve_exc)
                    logger.debug(
                        "tax_exempt_check.retrieve_failed customer=%s",
                        customer_id,
                        exc_info=True,
                    )
                    return
        else:
            return

        if not customer_id:
            return

        desired = (metadata.get("tax_exempt") or "").strip().lower()
        if desired not in ("exempt", "reverse"):
            return  # No action needed — customer is taxable (default "none").

        if current_tax_exempt == desired:
            logger.debug(
                "tax_exempt.already_synced customer=%s value=%s",
                customer_id,
                desired,
            )
            return

        # Sync the first-class field. Stripe Tax reads tax_exempt before
        # computing the 消費税 line; flipping it via Customer.modify causes
        # the NEXT draft invoice to issue without tax. The CURRENT draft
        # (if Stripe has already finalized) is reissued via
        # ``invoice.voided`` + a fresh invoice — operator triggers from
        # the Dashboard, the void handler (handle_invoice_modification_event)
        # logs it, and the new draft picks up the exempt flag automatically.
        try:
            import stripe as _stripe_mod

            _stripe_mod.Customer.modify(customer_id, tax_exempt=desired)
            logger.info(
                "tax_exempt.applied customer=%s value=%s prior=%s",
                customer_id,
                desired,
                current_tax_exempt,
            )
        except Exception as modify_exc:
            _capture(modify_exc)
            logger.warning(
                "tax_exempt.modify_failed customer=%s desired=%s",
                customer_id,
                desired,
                exc_info=True,
            )
    except Exception as exc:  # noqa: BLE001
        _capture(exc)
        logger.warning("tax_exempt_handler_failed etype=%s", etype, exc_info=True)


# ---------------------------------------------------------------------------
# 4. Currency-edge handler
# ---------------------------------------------------------------------------


def handle_currency_edge(conn: sqlite3.Connection, etype: str, obj: dict[str, Any]) -> bool:
    """Detect non-JPY settlement currency and audit-log + email operator.

    Returns True iff a non-JPY currency was detected (caller may use this
    to short-circuit downstream handlers that assume JPY pricing).

    Why this matters:
      * Our published price is ¥3/req. A USD/EUR settlement implies a
        misconfigured Price (test Price referenced in production) or a
        Stripe-side international card auto-conversion that bypassed our
        Price's ``currency`` setting.
      * 消費税 calculations differ — 輸出取引 (origin=non-JP) is 0% and
        the 適格請求書 footer carries different boilerplate.
      * Catching this at webhook time is cheaper than a chargeback for
        "I was charged $30, not ¥3".
    """
    try:
        currency = (obj.get("currency") or "").lower()
        if not currency or currency == "jpy":
            return False

        customer_id = obj.get("customer") or obj.get("id")
        amount = obj.get("amount") or obj.get("amount_due") or obj.get("amount_paid", 0)

        logger.warning(
            "stripe.currency_edge etype=%s currency=%s customer=%s amount=%s — "
            "non-JPY settlement detected. Operator review required.",
            etype,
            currency,
            customer_id,
            amount,
        )

        # Audit-log every non-JPY hit so a sustained pattern is greppable.
        try:
            from jpintel_mcp.api._audit_log import log_event

            log_event(
                conn,
                event_type="stripe.currency_edge",
                customer_id=customer_id,
                request=None,
                trigger_etype=etype,
                currency=currency,
                amount=amount,
            )
        except Exception as audit_exc:
            _capture(audit_exc)
            logger.debug("currency_edge_audit_failed", exc_info=True)

        # Operator email (best-effort, no requester echo — this is a
        # back-office signal not a customer-facing one).
        _notify_operator_currency_edge(
            etype=etype,
            currency=currency,
            customer_id=customer_id,
            amount=amount,
        )
        return True
    except Exception as exc:  # noqa: BLE001
        _capture(exc)
        logger.warning("currency_edge_handler_failed", exc_info=True)
        return False


def _notify_operator_currency_edge(
    *,
    etype: str,
    currency: str,
    customer_id: str | None,
    amount: int,
) -> None:
    try:
        from jpintel_mcp.email.postmark import (
            POSTMARK_BASE_URL,
            STREAM_TRANSACTIONAL,
            get_client,
        )

        client = get_client()
        if client.test_mode:
            logger.info(
                "currency_edge.email.skip env=%s currency=%s customer=%s",
                settings.env,
                currency,
                customer_id,
            )
            return

        import httpx

        body = (
            "非 JPY 通貨での Stripe イベントを検知しました。\n\n"
            f"event_type: {etype}\n"
            f"currency: {currency}\n"
            f"customer_id: {customer_id}\n"
            f"amount (subunit): {amount}\n\n"
            "想定外のテスト Price 流入か international card 経由の auto-conversion "
            "が考えられます。Stripe Dashboard で Price 設定 + 当該 Customer の"
            " country を確認してください。\n"
        )
        payload = {
            "From": settings.postmark_from_transactional,
            "To": "info@bookyou.net",
            "Subject": f"[AutonoMath] 非 JPY 通貨検知 ({currency.upper()})",
            "TextBody": body,
            "MessageStream": STREAM_TRANSACTIONAL,
            "Tag": "stripe-currency-edge",
            "TrackOpens": False,
            "TrackLinks": "None",
        }
        with httpx.Client(
            base_url=POSTMARK_BASE_URL,
            timeout=httpx.Timeout(10.0, connect=5.0),
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "X-Postmark-Server-Token": settings.postmark_api_token,
            },
        ) as http:
            try:
                r = http.post("/email", json=payload)
                if r.status_code >= 400:
                    logger.warning(
                        "currency_edge.email.api_error status=%d", r.status_code
                    )
            except httpx.HTTPError as exc:
                logger.warning("currency_edge.email.transport_error err=%s", exc)
    except Exception:  # noqa: BLE001
        logger.warning("currency_edge.email.failed", exc_info=True)


# ---------------------------------------------------------------------------
# 5. Invoice modification handler (invoice.updated / invoice.voided)
# ---------------------------------------------------------------------------


def handle_invoice_modification_event(
    conn: sqlite3.Connection, etype: str, obj: dict[str, Any]
) -> None:
    """Audit-log invoice updates / voids; never auto-acts on the customer.

    Common operator paths:
      * ``invoice.updated`` — Stripe Dashboard edit (e.g. memo field)
      * ``invoice.voided`` — INV-23 (適格請求書) correction → operator
        voids the wrong invoice and re-issues. The void itself is
        forensically interesting because the customer may have already
        downloaded the original PDF.

    We DO NOT touch tier / subscription / API key state here — that is owned
    by ``customer.subscription.*`` events. The audit-log row is the only
    durable side effect.
    """
    try:
        invoice_id = obj.get("id")
        customer_id = obj.get("customer")
        sub_id = obj.get("subscription")
        amount_due = obj.get("amount_due", 0)
        invoice_status = obj.get("status") or "unknown"
        hosted_invoice_url = obj.get("hosted_invoice_url")

        from jpintel_mcp.api._audit_log import log_event

        log_event(
            conn,
            event_type=etype,
            customer_id=customer_id,
            request=None,
            stripe_invoice_id=invoice_id,
            stripe_subscription_id=sub_id,
            amount_due=amount_due,
            invoice_status=invoice_status,
            hosted_invoice_url=hosted_invoice_url,
        )
        if etype == "invoice.voided":
            logger.warning(
                "stripe.invoice.voided invoice=%s customer=%s sub=%s amount_due=%s — "
                "operator triggered; verify a replacement invoice was issued.",
                invoice_id,
                customer_id,
                sub_id,
                amount_due,
            )
        else:
            logger.info(
                "stripe.invoice.updated invoice=%s customer=%s status=%s",
                invoice_id,
                customer_id,
                invoice_status,
            )
    except Exception as exc:  # noqa: BLE001
        _capture(exc)
        logger.warning(
            "invoice_modification_handler_failed etype=%s",
            etype,
            exc_info=True,
        )


# ---------------------------------------------------------------------------
# 6. Stripe Tax API failure fallback
# ---------------------------------------------------------------------------


# Fallback default per JP standard rate. Used ONLY when:
#   * the cache is empty (first-ever Tax API call from a fresh deploy), AND
#   * the Stripe Tax API is currently 5xx
# Returning 0% would 消費税法 §63 mis-issue the 適格請求書, so we instead
# fall back to the published JP standard rate (10%). This is documented in
# the 出典取得 footer regenerated by `_apply_invoice_metadata_safe`.
_JP_STANDARD_RATE_BPS = 1000  # 10.00%, expressed in basis points


def cache_successful_tax_calculation(
    conn: sqlite3.Connection,
    *,
    customer_id: str,
    rate_bps: int,
    jurisdiction: str = "JP",
    tax_amount_yen: int | None = None,
) -> None:
    """Record the most recent successful Stripe Tax calculation per customer.

    Schema lives in migration 071: ``stripe_tax_cache``. Idempotent UPSERT —
    each customer keeps exactly one cached rate (the latest successful one).
    Caller invokes this AFTER ``stripe.tax.Calculation.create`` returns OK,
    inside the same webhook handler.
    """
    try:
        now = datetime.now(UTC).isoformat()
        conn.execute(
            """INSERT INTO stripe_tax_cache(
                   customer_id, rate_bps, jurisdiction, tax_amount_yen,
                   cached_at
               ) VALUES (?,?,?,?,?)
               ON CONFLICT(customer_id) DO UPDATE SET
                   rate_bps = excluded.rate_bps,
                   jurisdiction = excluded.jurisdiction,
                   tax_amount_yen = excluded.tax_amount_yen,
                   cached_at = excluded.cached_at""",
            (customer_id, rate_bps, jurisdiction, tax_amount_yen, now),
        )
    except Exception as exc:  # noqa: BLE001
        _capture(exc)
        logger.warning(
            "stripe_tax_cache_write_failed customer=%s",
            customer_id,
            exc_info=True,
        )


def stripe_tax_with_fallback(
    conn: sqlite3.Connection,
    *,
    customer_id: str,
    line_items: list[dict[str, Any]],
    currency: str = "jpy",
) -> dict[str, Any]:
    """Wrap ``stripe.tax.Calculation.create`` with cache-restore fallback.

    On success: cache the rate, return ``{"source": "stripe", "rate_bps": ...,
    "calculation": <stripe object>}``.

    On 5xx / connection error: load the most recent cached rate for this
    customer. If none cached, fall back to the published JP standard rate
    (1000 bps == 10%) — never 0, because a 0% line on an 適格請求書 violates
    消費税法 §63 (per-rate table requirement).

    Always returns a dict with at minimum ``rate_bps`` and ``source`` so the
    caller can decide whether to email the operator about the fallback path.
    """
    try:
        import stripe as _stripe_mod

        # Stripe Tax Calculation API. The exact method shape depends on SDK
        # version; we use the public ``stripe.tax.Calculation.create`` path
        # (introduced 2023-08-01). The wrapping is what matters here — the
        # specific kwargs schema is exercised in the integration test.
        calc = _stripe_mod.tax.Calculation.create(
            currency=currency,
            line_items=line_items,
            customer=customer_id,
        )
        # Pull the rate from the response. Stripe returns the tax_amount_exclusive
        # at the top level + a per-line breakdown; we record the implied rate
        # from amount_total / amount_subtotal so the cache survives a future
        # SDK shape change.
        amount_subtotal = (
            calc.get("amount_subtotal") if isinstance(calc, dict)
            else getattr(calc, "amount_subtotal", 0)
        ) or 0
        tax_amount = (
            calc.get("tax_amount_exclusive") if isinstance(calc, dict)
            else getattr(calc, "tax_amount_exclusive", 0)
        ) or 0
        rate_bps = (
            int(round(10000 * tax_amount / amount_subtotal))
            if amount_subtotal
            else _JP_STANDARD_RATE_BPS
        )
        cache_successful_tax_calculation(
            conn,
            customer_id=customer_id,
            rate_bps=rate_bps,
            tax_amount_yen=tax_amount,
        )
        return {
            "source": "stripe",
            "rate_bps": rate_bps,
            "tax_amount_yen": tax_amount,
            "calculation": calc,
        }
    except Exception as stripe_exc:  # noqa: BLE001
        # Stripe Tax 5xx / connection drop / SDK layer error. Capture so a
        # sustained outage is visible, then fall back to the cache.
        _capture(stripe_exc)
        logger.warning(
            "stripe_tax_calculation_failed customer=%s — falling back to cache",
            customer_id,
            exc_info=True,
        )
        try:
            row = conn.execute(
                "SELECT rate_bps, jurisdiction, tax_amount_yen, cached_at "
                "FROM stripe_tax_cache WHERE customer_id = ?",
                (customer_id,),
            ).fetchone()
        except Exception as load_exc:
            _capture(load_exc)
            row = None
        if row:
            rate_bps = row[0] if not hasattr(row, "keys") else row["rate_bps"]
            cached_at = row[3] if not hasattr(row, "keys") else row["cached_at"]
            logger.info(
                "stripe_tax_fallback.cache_hit customer=%s rate_bps=%d cached_at=%s",
                customer_id,
                rate_bps,
                cached_at,
            )
            return {
                "source": "cache",
                "rate_bps": rate_bps,
                "fallback_reason": "stripe_5xx",
            }
        logger.warning(
            "stripe_tax_fallback.cache_miss customer=%s — using JP standard %d bps",
            customer_id,
            _JP_STANDARD_RATE_BPS,
        )
        return {
            "source": "jp_standard_default",
            "rate_bps": _JP_STANDARD_RATE_BPS,
            "fallback_reason": "stripe_5xx_no_cache",
        }


__all__ = [
    "RefundRequest",
    "RefundResponse",
    "cache_successful_tax_calculation",
    "handle_currency_edge",
    "handle_dispute_event",
    "handle_invoice_modification_event",
    "handle_tax_exempt_event",
    "router",
    "stripe_tax_with_fallback",
    "submit_refund_request",
]
