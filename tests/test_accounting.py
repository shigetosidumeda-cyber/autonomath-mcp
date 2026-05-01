"""Happy-path tests for `api/accounting.py`.

The current implementation is a contract-only preview scaffold:
`POST /v1/accounting/invoice-validate` is gated behind
`settings.enable_preview_endpoints` and intentionally returns HTTP 501 with
a roadmap body when mounted. This file documents the happy-path of
"contract is published, body returns expected roadmap shape".

If/when the route ships a real implementation (target W7, 2026-06-10),
the 501 assertion below should be replaced with a real-shape assertion.
Until then, this is the meaningful happy-path: the request body validates,
routes correctly, and returns the documented roadmap response.
"""
from __future__ import annotations

import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


_REPO = Path(__file__).resolve().parent.parent
_SRC = _REPO / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


@pytest.fixture()
def preview_client(
    seeded_db, monkeypatch: pytest.MonkeyPatch
) -> Iterator[TestClient]:
    """TestClient with `enable_preview_endpoints=True` — mounts the router."""
    from jpintel_mcp.api import main as main_module
    from jpintel_mcp.config import settings

    monkeypatch.setattr(settings, "enable_preview_endpoints", True)
    app = main_module.create_app()
    with TestClient(app) as c:
        yield c


def test_invoice_validate_request_model_accepts_valid_t_number():
    """Pydantic body validates a 14-char T-prefix invoice number."""
    from jpintel_mcp.api.accounting import InvoiceValidateRequest

    req = InvoiceValidateRequest(invoice_number="T8010001213708")
    assert req.invoice_number == "T8010001213708"


def test_invoice_validate_returns_roadmap_when_enabled(preview_client: TestClient):
    """Flag on → router mounted → 501 + roadmap body (target W7 contract).

    The route advertises a finalized contract before its implementation
    lands. SDK generators / partners must see HTTP 501 + an `eta` key so
    their codegen can plan around it.
    """
    resp = preview_client.post(
        "/v1/accounting/invoice-validate",
        json={"invoice_number": "T8010001213708"},
    )
    assert resp.status_code == 501, resp.text
    body = resp.json()
    # HTTPException with dict detail nests payload under `detail`.
    assert "detail" in body
    inner = body["detail"]
    assert isinstance(inner, dict)
    assert inner.get("eta") == "2026-06-10"


def test_invoice_validate_404_when_flag_off(client: TestClient):
    """Flag off (default) → router not mounted → 404."""
    resp = client.post(
        "/v1/accounting/invoice-validate",
        json={"invoice_number": "T8010001213708"},
    )
    assert resp.status_code == 404
