"""Preview endpoint: GET /v1/legal/items (future, W6).

Contract-only scaffold. Resolves a 法令名 + 条文 into the canonical 法律条文
text plus its last revision date by querying the e-Gov 法令 API
(https://elaws.e-gov.go.jp/api/1/).

Intent is to publish the route shape **before** the implementation lands so
frontend SDKs, MCP configs, and partner integrations can code against the
final contract. While `settings.enable_preview_endpoints` is False (default),
this router is not mounted and callers get 404. Once the flag is flipped, the
route responds with HTTP 501 + a roadmap body — that is the signal
"advertised but not yet implemented".

Target ship: W6 (2026-05-27). See `docs/preview_endpoints.md`.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict

router = APIRouter(prefix="/v1/legal", tags=["legal (preview)"])


class LegalItemResponse(BaseModel):
    """Canonical legal article lookup result (future shape)."""

    model_config = ConfigDict(frozen=True)

    law_name: str
    law_number: str
    article_number: str
    article_text: str
    revision_date: str
    source_url: str
    fetched_at: str


@router.get(
    "/items",
    response_model=LegalItemResponse,
    responses={
        501: {
            "description": "Endpoint scaffolded, implementation pending.",
            "content": {
                "application/json": {
                    "example": {
                        "detail": "endpoint under development, target W6",
                        "eta": "2026-05-27",
                    }
                }
            },
        }
    },
)
def get_legal_item(
    law: str = Query(..., description="法令名 (例: 労働基準法)", max_length=200),
    article: str = Query(..., description="条文番号 (例: 15, 15-1)", max_length=40),
    subject: str | None = Query(
        default=None, description="任意の subject filter (例: 賃金)", max_length=200
    ),
) -> LegalItemResponse:
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail={
            "detail": "endpoint under development, target W6",
            "eta": "2026-05-27",
        },
    )
