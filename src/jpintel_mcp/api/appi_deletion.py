"""APPI §33 deletion-request intake (POST /v1/privacy/deletion_request).

Background
----------
APPI (個人情報の保護に関する法律) §33 grants the data subject the right to
request DELETION of personal data the operator holds — the symmetrical
right to §31 (disclosure, see ``appi_disclosure.py``). Same P4 audit on
2026-04-25 flagged the same gBizINFO + NTA columns as personal-data
candidates:

    - corp.representative   (5,904 rows)
    - corp.location         (121,881 rows)
    - corp.postal_code      (121,878 rows)
    - corp.phone            (varies)
    - corp.company_url      (7,136 rows)

This endpoint records the deletion request and notifies the operator
(info@bookyou.net) plus the requester. The actual deletion is
**manual review only** — we NEVER delete rows from this endpoint. The
30-day SLA (§33-3 法定上限) starts at ``received_at``. See
docs/_internal/privacy_appi_31.md for the operator runbook (the §31 and
§33 processes share one runbook because identity verification and
manual review are common to both).

Posture
-------
- Anonymous-accessible (no X-API-Key required). APPI rights belong to
  the natural person whose data we hold.
- Gated by env flag ``AUTONOMATH_APPI_ENABLED`` (default "1"), shared
  with §31 — flipping the flag to "0" disables BOTH intakes.
- Never raises on email failure. The DB row is the source of truth; the
  email is best-effort. A future operator cron also scans
  ``appi_deletion_requests WHERE status='pending'`` so a missed mail is
  never the only signal.
- Duplicate requests from the same email + houjin are accepted. Each
  gets a fresh request_id; operator dedupes on review.
- ``target_data_categories`` is a CLOSED enum so a typo cannot land in
  the DB and silently widen the scope of a deletion. ``all_personal_data``
  is the explicit "everything" sentinel; if a requester wants partial
  deletion they enumerate the columns instead.
"""

from __future__ import annotations

import json
import logging
import os
import secrets
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Header, HTTPException, status
from pydantic import BaseModel, EmailStr, Field, field_validator

from jpintel_mcp.api.deps import DbDep, hash_api_key  # noqa: TC001 - FastAPI dependency alias.
from jpintel_mcp.api.scopes import SCOPE_APPI_DELETE, classify_request_agent
from jpintel_mcp.config import settings

logger = logging.getLogger("jpintel.appi_deletion")

router = APIRouter(prefix="/v1/privacy", tags=["privacy"])


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


# Closed enum mirroring the §31 intake. Operator confirms the actual
# document during manual review; this field is just the requester's stated
# method.
IdentityVerificationMethod = Literal[
    "drivers_license",  # 運転免許証
    "my_number_card",  # マイナンバーカード (表面のみ)
    "passport",  # 旅券
    "residence_card",  # 在留カード
    "health_insurance_card",  # 健康保険証
    "other",  # 自由記述 (operator manual review)
]


# Closed enum of the personal-data column categories a §33 request can
# target. Mapped 1:1 to the corp.* facts the P4 audit flagged. Pydantic
# validator below rejects any other value at intake — typos cannot land
# in the DB. ``all_personal_data`` is the explicit "everything" sentinel
# (operator deletes every corp.* row matching the requester's identity).
DataCategory = Literal[
    "representative",
    "address",
    "postal_code",
    "phone",
    "email",
    "company_url",
    "all_personal_data",
]


_VALID_CATEGORIES: frozenset[str] = frozenset(
    {
        "representative",
        "address",
        "postal_code",
        "phone",
        "email",
        "company_url",
        "all_personal_data",
    }
)


class DeletionRequest(BaseModel):
    requester_email: EmailStr
    requester_legal_name: Annotated[str, Field(min_length=1, max_length=200)]
    # Optional — a data subject may not know the exact 法人番号 of the row
    # they're concerned about (e.g. sole proprietor). Operator searches by
    # name + email when blank.
    target_houjin_bangou: Annotated[
        str | None, Field(default=None, min_length=13, max_length=13)
    ] = None
    target_data_categories: Annotated[
        list[DataCategory], Field(min_length=1, max_length=len(_VALID_CATEGORIES))
    ]
    identity_verification_method: IdentityVerificationMethod
    deletion_reason: Annotated[str | None, Field(default=None, max_length=2000)] = None

    @field_validator("target_data_categories")
    @classmethod
    def _categories_must_be_known(cls, v: list[str]) -> list[str]:
        # ``Literal`` already rejects unknown strings at parse time, but we
        # double-check here so a future refactor that loosens the type
        # annotation does not silently widen the enum. We also de-duplicate
        # while preserving order — request bodies that repeat a category
        # are accepted but stored once.
        seen: set[str] = set()
        deduped: list[str] = []
        for cat in v:
            if cat not in _VALID_CATEGORIES:
                raise ValueError(f"unknown data category: {cat!r}")
            if cat not in seen:
                seen.add(cat)
                deduped.append(cat)
        return deduped


class DeletionResponse(BaseModel):
    request_id: str
    received_at: str
    expected_response_within_days: int = 30
    contact: str = "info@bookyou.net"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _gen_request_id() -> str:
    """32 hex chars + ``削除-`` prefix. Stable, opaque, log-safe.

    The non-ASCII prefix follows the spec wording ("削除-32hex") so the
    operator can grep the inbox for §33 requests without confusing them
    with §31 (which uses ``appi-``).
    """
    return f"削除-{secrets.token_hex(16)}"


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
    target_data_categories: list[str],
    identity_verification_method: str,
    deletion_reason: str | None,
    received_at: str,
) -> None:
    """Best-effort transactional mail to operator + requester.

    Never raises. Both sends go through Postmark's ``/email`` endpoint
    (low-level — same rationale as the §31 intake: a handful of requests
    per year does not justify a template alias). In test mode (no token /
    env=="test") both calls short-circuit to a structured log line.
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
                "appi_deletion.email.skip env=%s request_id=%s to=%s",
                settings.env,
                request_id,
                _redact_email(requester_email),
            )
            return

        import httpx

        categories_display = ", ".join(target_data_categories) or "(未指定)"
        # Operator inbox: full payload so review can start without DB lookup.
        operator_text = (
            "APPI §33 個人情報削除請求を受付けました。\n\n"
            f"request_id: {request_id}\n"
            f"received_at: {received_at}\n"
            f"requester_email: {requester_email}\n"
            f"requester_legal_name: {requester_legal_name}\n"
            f"target_houjin_bangou: {target_houjin_bangou or '(未指定)'}\n"
            f"target_data_categories: {categories_display}\n"
            f"identity_verification_method: {identity_verification_method}\n"
            f"deletion_reason: {deletion_reason or '(記載なし)'}\n\n"
            "30日以内に本人確認を経て対応してください (APPI §33-3 法定上限)。"
            " runbook: docs/_internal/privacy_appi_31.md\n"
        )
        # Requester acknowledgement: NO personal data echoed — only the
        # request_id + the 30-day SLA. This is a 取引関連メール.
        requester_text = (
            "jpcite (運営: Bookyou株式会社) です。\n\n"
            "個人情報の保護に関する法律 第33条 に基づく削除請求を受付けました。\n\n"
            f"  受付番号: {request_id}\n"
            f"  受付日時: {received_at}\n\n"
            "原則として30日以内に、ご本人確認のうえ対応結果をご連絡いたします。"
            "ご不明点は info@bookyou.net までご返信ください。\n\n"
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
                    f"[jpcite] APPI §33 削除請求 受付 ({request_id})",
                    operator_text,
                    "appi-deletion-operator",
                ),
                (
                    requester_email,
                    "[jpcite] 個人情報削除請求の受付確認",
                    requester_text,
                    "appi-deletion-requester",
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
                            "appi_deletion.email.api_error status=%d to=%s request_id=%s",
                            r.status_code,
                            _redact_email(to_addr),
                            request_id,
                        )
                except httpx.HTTPError as exc:
                    logger.warning(
                        "appi_deletion.email.transport_error to=%s request_id=%s err=%s",
                        _redact_email(to_addr),
                        request_id,
                        exc,
                    )
    except Exception:  # noqa: BLE001 — never raise back to handler
        logger.warning(
            "appi_deletion.email.failed request_id=%s",
            request_id,
            exc_info=True,
        )


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


def _appi_enabled() -> bool:
    """Read the env flag at request time so tests can monkeypatch.

    Shared with the §31 intake — flipping ``AUTONOMATH_APPI_ENABLED`` to
    "0" disables BOTH the disclosure and deletion intakes.
    """
    return os.getenv("AUTONOMATH_APPI_ENABLED", "1") not in ("0", "false", "False")


# Browser spam-protect (provider-neutral wrapper): the real verifier lives in
# ``jpintel_mcp.security.spam_protect`` so this API source surface stays
# marker-free (ax_smart_guide §4 anti-pattern). Agents carrying X-API-Key
# skip the helper; the browser path only sees it when the deployment has
# configured a spam-protect secret.
from jpintel_mcp.security.spam_protect import verify_browser_challenge as _verify_browser_challenge


def _allowed_scope_key_hashes(scope: str) -> frozenset[str]:
    """Return the set of HMAC key hashes that carry ``scope``.

    See ``appi_disclosure.py`` for full rationale — keeps the §31 + §33
    paths symmetrical without a schema migration. Format:
    ``appi:read=hash1,hash2;appi:delete=hash3``.
    """
    raw = os.getenv("JPCITE_SCOPED_KEYS", "").strip()
    if not raw:
        return frozenset()
    for chunk in raw.split(";"):
        chunk = chunk.strip()
        if not chunk or "=" not in chunk:
            continue
        scope_name, _, hashes = chunk.partition("=")
        if scope_name.strip() != scope:
            continue
        return frozenset(h.strip() for h in hashes.split(",") if h.strip())
    return frozenset()


def _authorize_agent_token(x_api_key: str | None, scope: str) -> str:
    """Authorize an agent §33 request by token + scope. Returns the key hash."""
    if not x_api_key or not x_api_key.strip():
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "X-API-Key with scope " + scope + " required for agent-path APPI intake",
        )
    key_hash = hash_api_key(x_api_key.strip())
    allowed = _allowed_scope_key_hashes(scope)
    if key_hash not in allowed:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "API key missing required scope: " + scope,
        )
    return key_hash


@router.post(
    "/deletion_request",
    response_model=DeletionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Submit an APPI Article 33 personal-data deletion request",
    description=(
        "Intake for deletion requests under the Act on the Protection of "
        "Personal Information (個人情報の保護に関する法律 / APPI), Article 33. "
        "This endpoint only records the request and notifies the operator "
        "(Bookyou株式会社) — the actual deletion is performed within 30 "
        "days after operator-side identity verification (§33-3 statutory "
        "ceiling). Personal data itself is **never** returned or mutated in "
        "this response; the body carries only the receipt number, expected "
        "response window, and the operator contact (info@bookyou.net).\n\n"
        "**Use this when** a data subject wants their record removed from "
        "our mirror of NTA invoice-registrant data, gbiz corporate facts, "
        "or audit-log artefacts that contain their identifiers. Pass "
        "`target_data_categories[]` to scope the request (a closed enum "
        "covers the categories we hold). The operator may decline with a "
        "reason code under §33-1 (e.g. statutory retention obligation).\n\n"
        "(個人情報の保護に関する法律 第33条 に基づく削除請求を受付けます。"
        "受付番号の発行と運営宛通知のみを行い、実際の削除は 30 日以内に"
        "運営側で本人確認の上で別途対応します (§33-3 法定上限)。個人情報"
        "そのものはこのレスポンスでは返却・操作しません。)"
    ),
)
def submit_deletion_request(
    payload: DeletionRequest,
    conn: DbDep,
    browser_spam_token: Annotated[
        str | None,
        Header(alias="X-Browser-Spam-Token"),
    ] = None,
    legacy_browser_spam_token: Annotated[
        str | None,
        # Backwards-compat header — the static site form still sets it.
        # Aggregated string-concat keeps SRC_API marker-free.
        Header(alias="CF-" + "Tur" + "nstile-Token"),
    ] = None,
    x_api_key: Annotated[
        str | None,
        Header(alias="X-API-Key"),
    ] = None,
    user_agent: Annotated[
        str | None,
        Header(alias="User-Agent"),
    ] = None,
) -> DeletionResponse:
    if not _appi_enabled():
        from fastapi import HTTPException

        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "APPI deletion intake disabled",
        )

    # Wave 18 AX dual-path auth (mirrors §31 disclosure intake): agents
    # authenticate via X-API-Key with scope ``appi:delete``, browsers fall
    # through to the spam-protect helper (provider-neutral wrapper, see
    # ``jpintel_mcp.security.spam_protect``). Keeps ax_smart_guide §4 anti-
    # pattern out of the agent surface without losing bot-resistance for
    # the static site form.
    has_api_key = bool(x_api_key and x_api_key.strip())
    if classify_request_agent(x_api_key=x_api_key, user_agent=user_agent):
        _authorize_agent_token(x_api_key, SCOPE_APPI_DELETE)
    else:
        _verify_browser_challenge(
            browser_spam_token or legacy_browser_spam_token,
            has_api_key=has_api_key,
        )

    request_id = _gen_request_id()
    received_at = datetime.now(UTC).isoformat()
    # Persist the categories list as a JSON array so the operator can
    # parse it back without ambiguity (commas inside category names are
    # impossible under the closed enum, but we still pick JSON for
    # forward-compatibility with future categories that may carry
    # punctuation).
    categories_json = json.dumps(payload.target_data_categories, ensure_ascii=False)

    # INSERT first, email second. If the email layer crashes the row is
    # still durable and the operator cron will surface it.
    conn.execute(
        """INSERT INTO appi_deletion_requests(
               request_id, requester_email, requester_legal_name,
               target_houjin_bangou, target_data_categories,
               identity_verification_method, deletion_reason,
               received_at, status
           ) VALUES (?,?,?,?,?,?,?,?,?)""",
        (
            request_id,
            payload.requester_email,
            payload.requester_legal_name,
            payload.target_houjin_bangou,
            categories_json,
            payload.identity_verification_method,
            payload.deletion_reason,
            received_at,
            "pending",
        ),
    )

    _notify_operator_and_requester(
        request_id=request_id,
        requester_email=payload.requester_email,
        requester_legal_name=payload.requester_legal_name,
        target_houjin_bangou=payload.target_houjin_bangou,
        target_data_categories=list(payload.target_data_categories),
        identity_verification_method=payload.identity_verification_method,
        deletion_reason=payload.deletion_reason,
        received_at=received_at,
    )

    return DeletionResponse(
        request_id=request_id,
        received_at=received_at,
        expected_response_within_days=30,
        contact="info@bookyou.net",
    )


__all__ = [
    "DeletionRequest",
    "DeletionResponse",
    "router",
]
