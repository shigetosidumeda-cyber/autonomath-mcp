"""Preview endpoint: POST /v1/accounting/invoice-validate (future, W7).

Contract-only scaffold. Validates an インボイス適格請求書発行事業者登録番号
(invoice registration number) against the 国税庁 public Web-API
(https://www.invoice-kohyo.nta.go.jp/web-api/), returning registration state
plus cached company identity.

Intent is to publish the route shape **before** the implementation lands so
frontend SDKs, MCP configs, and partner integrations can code against the
final contract. While `settings.enable_preview_endpoints` is False (default),
this router is not mounted and callers get 404. Once the flag is flipped, the
route responds with HTTP 501 + a roadmap body — that is the signal
"advertised but not yet implemented".

Target ship: W7 (2026-06-10). See `docs/preview_endpoints.md`.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

router = APIRouter(prefix="/v1/accounting", tags=["accounting (preview)"])


class InvoiceValidateRequest(BaseModel):
    """Body for POST /v1/accounting/invoice-validate."""

    model_config = ConfigDict(frozen=True)

    invoice_number: Annotated[
        str,
        Field(
            min_length=14,
            max_length=14,
            description="T + 13桁の適格請求書発行事業者登録番号 (例: T1234567890123)",
        ),
    ]


class InvoiceValidateResponse(BaseModel):
    """Invoice validation result (future shape)."""

    model_config = ConfigDict(frozen=True)

    invoice_number: str
    is_registered: bool
    registration_date: str | None
    company_name: str | None
    company_kana: str | None
    address: str | None
    last_synced: str


@router.post(
    "/invoice-validate",
    response_model=InvoiceValidateResponse,
    responses={
        501: {
            "description": "Endpoint scaffolded, implementation pending.",
            "content": {
                "application/json": {
                    "example": {
                        "detail": "endpoint under development, target W7",
                        "eta": "2026-06-10",
                    }
                }
            },
        }
    },
)
def validate_invoice(payload: InvoiceValidateRequest) -> InvoiceValidateResponse:
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail={
            "detail": "endpoint under development, target W7",
            "eta": "2026-06-10",
        },
    )
