"""APPI §31 disclosure-request intake (POST /v1/privacy/disclosure_request).

Background
----------
APPI (個人情報の保護に関する法律) §31 grants the data subject the right to
request disclosure of personal data the operator holds about them. The P4
audit on 2026-04-25 flagged that several columns sourced from gBizINFO + NTA
can include information the data subject considers personal:

    - corp.representative   (5,904 rows)
    - corp.location         (121,881 rows)
    - corp.postal_code      (121,878 rows)
    - corp.company_url      (7,136 rows)

This endpoint records the disclosure request and notifies the operator
(info@bookyou.net) plus the requester. The actual disclosure (or 不開示
reason) is delivered out-of-band after manual identity verification — we
NEVER emit personal data from this endpoint. See
docs/_internal/privacy_appi_31.md for the operator runbook.

Posture
-------
- Anonymous-accessible (no X-API-Key required). APPI rights belong to the
  natural person whose data we hold, not to a paid customer relationship.
- Gated by env flag ``AUTONOMATH_APPI_ENABLED`` (default "1"). When the
  flag is "0", the route is unmounted and returns 404.
- Never raises on email failure. The DB row is the source of truth; the
  email is best-effort. A future operator cron also scans
  ``appi_disclosure_requests WHERE status='pending'`` so a missed mail is
  never the only signal.
- Duplicate requests from the same email + houjin_bangou are accepted.
  Each gets a fresh request_id; the operator dedupes on review (one human
  may legitimately resubmit if they didn't get the first acknowledgement).
"""
from __future__ import annotations

import logging
import os
import secrets
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, status
from pydantic import BaseModel, EmailStr, Field

from jpintel_mcp.api.deps import DbDep
from jpintel_mcp.config import settings

logger = logging.getLogger("jpintel.appi_disclosure")

router = APIRouter(prefix="/v1/privacy", tags=["privacy"])


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


# Identity verification methods we accept at intake. Closed enum so a typo
# cannot land in the DB. Operator confirms the actual document during manual
# review; this field is just the requester's stated method.
IdentityVerificationMethod = Literal[
    "drivers_license",       # 運転免許証
    "my_number_card",        # マイナンバーカード (表面のみ)
    "passport",              # 旅券
    "residence_card",        # 在留カード
    "health_insurance_card", # 健康保険証
    "other",                 # 自由記述 (operator manual review)
]


class DisclosureRequest(BaseModel):
    requester_email: EmailStr
    requester_legal_name: Annotated[str, Field(min_length=1, max_length=200)]
    # Optional — a data subject may not know the exact 法人番号 of the row
    # they're concerned about (e.g. sole proprietor). Operator searches by
    # name + email when blank.
    target_houjin_bangou: Annotated[str | None, Field(default=None, min_length=13, max_length=13)] = None
    identity_verification_method: IdentityVerificationMethod


class DisclosureResponse(BaseModel):
    request_id: str
    received_at: str
    expected_response_within_days: int = 14
    contact: str = "info@bookyou.net"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _gen_request_id() -> str:
    """32 hex chars + ``appi-`` prefix. Stable, opaque, log-safe."""
    return f"appi-{secrets.token_hex(16)}"


def _redact_email(addr: str) -> str:
    """Return ``a****@example.com`` — just enough for log correlation."""
    if "@" not in addr:
        return "***"
    local, _, domain = addr.partition("@")
    if len(local) <= 1:
        return f"*@{domain}"
    return f"{local[0]}***@{domain}"


def _notify_operator_and_requester(
    *,
    request_id: str,
    requester_email: str,
    requester_legal_name: str,
    target_houjin_bangou: str | None,
    identity_verification_method: str,
    received_at: str,
) -> None:
    """Best-effort transactional mail to operator + requester.

    Never raises. Both sends go through Postmark's `/email` endpoint
    (low-level, since we don't want to add new template aliases for an
    intake we expect to handle a handful of times per year). In test mode
    (no token / env=="test") both calls short-circuit to a structured log
    line — see the postmark client docstring.
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
                "appi_disclosure.email.skip env=%s request_id=%s to=%s",
                settings.env,
                request_id,
                _redact_email(requester_email),
            )
            return

        import httpx

        # Operator inbox: full payload so review can start without DB lookup.
        operator_text = (
            "APPI §31 個人情報開示請求を受付けました。\n\n"
            f"request_id: {request_id}\n"
            f"received_at: {received_at}\n"
            f"requester_email: {requester_email}\n"
            f"requester_legal_name: {requester_legal_name}\n"
            f"target_houjin_bangou: {target_houjin_bangou or '(未指定)'}\n"
            f"identity_verification_method: {identity_verification_method}\n\n"
            "14日以内に本人確認を経て対応してください。"
            " runbook: docs/_internal/privacy_appi_31.md\n"
        )
        # Requester acknowledgement: NO personal data echoed — only the
        # request_id + the 14-day SLA. This is a 取引関連メール.
        requester_text = (
            "AutonoMath (運営: Bookyou株式会社) です。\n\n"
            "個人情報の保護に関する法律 第31条 に基づく開示請求を受付けました。\n\n"
            f"  受付番号: {request_id}\n"
            f"  受付日時: {received_at}\n\n"
            "原則として14日以内に、ご本人確認のうえ対応結果をご連絡いたします。"
            "ご不明点は info@bookyou.net までご返信ください。\n\n"
            "Bookyou株式会社 (法人番号 T8010001213708)\n"
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
                    f"[AutonoMath] APPI §31 開示請求 受付 ({request_id})",
                    operator_text,
                    "appi-disclosure-operator",
                ),
                (
                    requester_email,
                    "[AutonoMath] 個人情報開示請求の受付確認",
                    requester_text,
                    "appi-disclosure-requester",
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
                            "appi_disclosure.email.api_error status=%d to=%s request_id=%s",
                            r.status_code,
                            _redact_email(to_addr),
                            request_id,
                        )
                except httpx.HTTPError as exc:
                    logger.warning(
                        "appi_disclosure.email.transport_error to=%s request_id=%s err=%s",
                        _redact_email(to_addr),
                        request_id,
                        exc,
                    )
    except Exception:  # noqa: BLE001 — never raise back to handler
        logger.warning(
            "appi_disclosure.email.failed request_id=%s",
            request_id,
            exc_info=True,
        )


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


def _appi_enabled() -> bool:
    """Read the env flag at request time so tests can monkeypatch."""
    return os.getenv("AUTONOMATH_APPI_ENABLED", "1") not in ("0", "false", "False")


@router.post(
    "/disclosure_request",
    response_model=DisclosureResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Submit an APPI Article 31 personal-data disclosure request",
    description=(
        "Intake for disclosure requests under the Act on the Protection of "
        "Personal Information (個人情報の保護に関する法律 / APPI), Article 31. "
        "This endpoint only records the request and notifies the operator "
        "(Bookyou株式会社) — the actual disclosure is performed within 14 "
        "days after operator-side identity verification, out-of-band. "
        "Personal data itself is **never** returned in this response; the "
        "body carries only the receipt number, expected response window, "
        "and the operator contact (info@bookyou.net).\n\n"
        "**Use this when** a data subject (typically a 13-digit 法人番号 "
        "holder whose record we mirror) wants to know which of their "
        "fields are stored. Identity verification methods accepted: "
        "personal-seal certificate (印鑑証明), driver's licence, individual "
        "number card (マイナンバーカード). The operator may refuse with a "
        "reason code under §31-2 (e.g. would jeopardise a third party).\n\n"
        "(個人情報の保護に関する法律 第31条 に基づく開示請求を受付けます。"
        "受付番号の発行と運営宛通知のみを行い、実際の開示は 14 日以内に"
        "運営側で本人確認の上で別途対応します。個人情報そのものは"
        "このレスポンスでは返却しません。)"
    ),
)
def submit_disclosure_request(
    payload: DisclosureRequest,
    conn: DbDep,
) -> DisclosureResponse:
    if not _appi_enabled():
        # Match the shape the global StarletteHTTPException handler emits;
        # the service-unavailable code is the right signal because the
        # legal intake itself is intentionally turned off — not a bug.
        from fastapi import HTTPException

        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "APPI disclosure intake disabled",
        )

    request_id = _gen_request_id()
    received_at = datetime.now(UTC).isoformat()

    # INSERT first, email second. If the email layer crashes the row is
    # still durable and the operator cron will surface it. Conversely, if
    # the INSERT fails we never email a stale acknowledgement.
    conn.execute(
        """INSERT INTO appi_disclosure_requests(
               request_id, requester_email, requester_legal_name,
               target_houjin_bangou, identity_verification_method,
               received_at, status
           ) VALUES (?,?,?,?,?,?,?)""",
        (
            request_id,
            payload.requester_email,
            payload.requester_legal_name,
            payload.target_houjin_bangou,
            payload.identity_verification_method,
            received_at,
            "pending",
        ),
    )

    _notify_operator_and_requester(
        request_id=request_id,
        requester_email=payload.requester_email,
        requester_legal_name=payload.requester_legal_name,
        target_houjin_bangou=payload.target_houjin_bangou,
        identity_verification_method=payload.identity_verification_method,
        received_at=received_at,
    )

    return DisclosureResponse(
        request_id=request_id,
        received_at=received_at,
        expected_response_within_days=14,
        contact="info@bookyou.net",
    )


__all__ = [
    "DisclosureRequest",
    "DisclosureResponse",
    "router",
]
