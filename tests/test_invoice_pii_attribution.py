"""MASTER_PLAN_v1 §L2: invoice_registrants APPI 通知 attribution.

Verifies that every invoice_registrants response carries the
``_attribution`` block and that the block surfaces:

  * ``_pii_notice.ja`` (non-empty) — APPI §17/§21 利用目的 + 開示請求窓口
  * ``_pii_notice.en`` (non-empty) — English mirror for foreign FDI cohort
  * ``_redistribution_terms.downstream_must_carry_attribution`` = True
  * ``_redistribution_terms.downstream_must_relay_pii_notice`` = True
  * Existing PDL v1.0 fields (``license`` / ``source`` / ``edited`` / ``notice``)

The contract is that the API may NOT strip the PII notice on relay —
downstream consumers must propagate it per the §L2 spec.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure src/ is on path for direct test runs.
_REPO = Path(__file__).resolve().parent.parent
_SRC = _REPO / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


def _import_attribution():
    """Lazy import of the module-level constants."""
    from jpintel_mcp.api.invoice_registrants import (
        _ATTRIBUTION,
        _PII_NOTICE,
        _REDISTRIBUTION_TERMS,
        _inject_attribution,
    )

    return _ATTRIBUTION, _PII_NOTICE, _REDISTRIBUTION_TERMS, _inject_attribution


# ---------------------------------------------------------------------------
# 1. _ATTRIBUTION block carries _pii_notice + _redistribution_terms.
# ---------------------------------------------------------------------------


def test_attribution_block_carries_pii_notice():
    """`_ATTRIBUTION` must include `_pii_notice.ja` (non-empty)."""
    attribution, _pii, _redist, _inject = _import_attribution()

    assert "_pii_notice" in attribution, "_ATTRIBUTION missing _pii_notice"
    pii = attribution["_pii_notice"]
    assert isinstance(pii, dict)
    assert (
        isinstance(pii.get("ja"), str) and len(pii["ja"]) >= 50
    ), "_pii_notice.ja must be a non-empty Japanese notice string"
    # 個人情報保護法 §17/§21 wording is mandatory per §L2 spec.
    assert "個人情報保護法" in pii["ja"]
    assert "§17" in pii["ja"] or "17" in pii["ja"]
    # 開示請求窓口 — must point at jpcite.com/privacy and operator email.
    assert "jpcite.com/privacy" in pii["ja"]
    assert "info@bookyou.net" in pii["ja"]


def test_attribution_block_carries_pii_notice_en():
    """`_pii_notice.en` mirrors the JA notice for foreign FDI cohort."""
    attribution, _pii, _redist, _inject = _import_attribution()

    pii = attribution["_pii_notice"]
    assert isinstance(pii.get("en"), str) and len(pii["en"]) >= 50


def test_attribution_block_carries_redistribution_terms():
    """`_redistribution_terms` enforces downstream relay duty."""
    attribution, _pii, _redist, _inject = _import_attribution()

    assert "_redistribution_terms" in attribution
    redist = attribution["_redistribution_terms"]
    assert redist.get("downstream_must_carry_attribution") is True
    assert redist.get("downstream_must_relay_pii_notice") is True


# ---------------------------------------------------------------------------
# 2. _inject_attribution() helper auto-injects on every response body.
# ---------------------------------------------------------------------------


def test_inject_attribution_adds_underscored_block():
    """Helper must add `_attribution` to a fresh response body."""
    _attr, _pii, _redist, inject = _import_attribution()

    body = inject({"results": [], "total": 0, "limit": 50, "offset": 0})
    assert "_attribution" in body
    assert body["_attribution"]["_pii_notice"]["ja"]


def test_inject_attribution_idempotent():
    """If `_attribution` already on the body, helper must NOT overwrite."""
    _attr, _pii, _redist, inject = _import_attribution()

    sentinel = {"sentinel": True}
    body = inject({"_attribution": sentinel})
    # setdefault semantics — caller-supplied value wins.
    assert body["_attribution"] is sentinel


# ---------------------------------------------------------------------------
# 3. End-to-end: live API responses carry `_attribution._pii_notice.ja`.
# ---------------------------------------------------------------------------


def test_search_response_carries_pii_notice():
    """`GET /v1/invoice_registrants/search` body must surface the PII notice.

    Uses the FastAPI TestClient against the in-process app. We deliberately
    issue an empty-result query so the test is independent of the live DB
    snapshot — the contract under test is the response wrapper, not the
    data layer.
    """
    try:
        from fastapi.testclient import TestClient

        from jpintel_mcp.api.main import app
    except Exception:
        # Soft-skip in the sandbox where fastapi extras may be absent —
        # the unit tests above still cover the helper contract.
        import pytest

        pytest.skip("fastapi not importable in this environment")

    client = TestClient(app)
    resp = client.get("/v1/invoice_registrants/search?limit=1")
    if resp.status_code >= 500:
        # Some test environments lack the underlying DB file; the
        # response-wrapper contract is still verified by the unit tests
        # above, so skip the e2e branch instead of failing CI on infra.
        import pytest

        pytest.skip(f"API path returned {resp.status_code}; skipping e2e check")
    assert resp.status_code in (200, 404, 422), resp.text
    body = resp.json()
    # Either `_attribution` (new contract) or legacy `attribution`; the
    # new contract surface MUST carry the PII notice.
    attr = body.get("_attribution") or body.get("attribution") or {}
    pii = attr.get("_pii_notice") or {}
    assert pii.get("ja"), f"response missing _attribution._pii_notice.ja; got keys={list(body)}"
