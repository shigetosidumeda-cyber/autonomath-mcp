"""Tests for the preview / roadmap endpoints.

Two contract-only scaffolds (legal / accounting) mounted behind
`settings.enable_preview_endpoints`. The original third scaffold (calendar)
graduated to a first-class endpoint; its coverage now lives in
`tests/test_calendar.py`. Covers:

  (a) default (flag off) — routes are not mounted at all, so a call 404s.
      This is what production ships: clean OpenAPI, no hints of half-built
      features.

  (b) flag on — routes are mounted and deliberately return HTTP 501 with a
      roadmap body (`detail`, `eta`). That is the signal to SDK generators
      and partners that the contract is final but the implementation is
      pending.

Body assertions only match the `detail` + `eta` keys — not timestamps or
derived data — so flipping target dates in the router code is a one-file
change, not a brittle test fix.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

if TYPE_CHECKING:
    from collections.abc import Iterator


@pytest.fixture()
def preview_client(seeded_db, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """Build a fresh TestClient with `enable_preview_endpoints=True`.

    The flag is read at app-construction time inside `create_app()`, so we
    flip the setting before calling it. Using `monkeypatch.setattr` on the
    live `settings` singleton keeps every other Settings value intact for
    this test module.
    """
    from jpintel_mcp.api import main as main_module
    from jpintel_mcp.config import settings

    monkeypatch.setattr(settings, "enable_preview_endpoints", True)
    app = main_module.create_app()
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# Flag off -> 404 (default behaviour; the `client` fixture in conftest.py
# builds the app with the flag at its default False).
# ---------------------------------------------------------------------------


def test_legal_items_404_when_flag_off(client: TestClient) -> None:
    r = client.get("/v1/legal/items", params={"law": "労働基準法", "article": "15"})
    assert r.status_code == 404, r.text


def test_accounting_invoice_validate_404_when_flag_off(client: TestClient) -> None:
    r = client.post(
        "/v1/accounting/invoice-validate",
        json={"invoice_number": "T1234567890123"},
    )
    assert r.status_code == 404, r.text


# ---------------------------------------------------------------------------
# Flag on -> 501 with the roadmap body shape.
# ---------------------------------------------------------------------------


def test_legal_items_501_when_flag_on(preview_client: TestClient) -> None:
    r = preview_client.get("/v1/legal/items", params={"law": "労働基準法", "article": "15"})
    assert r.status_code == 501, r.text
    body = r.json()
    # HTTPException with a dict detail nests the payload under `detail`.
    assert body["detail"] == {
        "detail": "endpoint under development, target W6",
        "eta": "2026-05-27",
    }


def test_accounting_invoice_validate_501_when_flag_on(
    preview_client: TestClient,
) -> None:
    r = preview_client.post(
        "/v1/accounting/invoice-validate",
        json={"invoice_number": "T1234567890123"},
    )
    assert r.status_code == 501, r.text
    body = r.json()
    assert body["detail"] == {
        "detail": "endpoint under development, target W7",
        "eta": "2026-06-10",
    }


# Note: the original calendar preview stub (`GET /v1/calendar/deadlines`) has
# shipped as a first-class endpoint. Coverage moved to `tests/test_calendar.py`.
# Only the preview-gated endpoints (legal items, invoice validate) remain here.
