"""proxy_endpoints のテスト: 認可チェック / API key 転送 / token 漏洩防止 / 入力検証。"""

from __future__ import annotations

import base64
import json

import httpx
import itsdangerous
from fastapi.testclient import TestClient


def _client():
    from app import create_app

    return TestClient(create_app())


def _seed_session_cookie(client: TestClient, mf_session: dict) -> None:
    """SessionMiddleware (starlette) と同じ署名方式で cookie を仕込む。

    starlette は base64(json) を itsdangerous.TimestampSigner で署名。
    """
    secret = "0" * 48  # conftest.py の SESSION_SECRET と一致
    signer = itsdangerous.TimestampSigner(secret)
    payload = {"mf": mf_session}
    raw = base64.b64encode(json.dumps(payload).encode("utf-8"))
    signed = signer.sign(raw).decode("utf-8")
    client.cookies.set("jpcite_mf_sid", signed)


def test_proxy_requires_auth():
    c = _client()
    r = c.post("/mf-plugin/search-subsidies", json={"keyword": "省エネ"})
    assert r.status_code == 401
    assert r.json()["detail"] == "mf_not_authorized"


def test_invoice_number_validation():
    """T+13 桁以外は 400。session を持っていなくても入力検証で先に弾ける形が
    望ましいが、実装は session 検証→入力検証の順。session を仕込んだ上で
    検証する。"""
    c = _client()
    _seed_session_cookie(
        c,
        {
            "access_token": "fake-access",
            "refresh_token": "fake-refresh",
            "tenant_uid": "tenant-001",
            "tenant_name": "テスト株式会社",
            "scope": "mfc/ac/data.read",
            "expires_in": 3600,
        },
    )

    bad_inputs = ["", "T123", "X1234567890123", "T12345678901234", "12345678901234"]
    for raw in bad_inputs:
        r = c.post("/mf-plugin/check-invoice-registrant", json={"registration_number": raw})
        assert r.status_code == 400, f"expected 400 for {raw!r}, got {r.status_code}"


def test_proxy_forwards_api_key_not_token(monkeypatch):
    """upstream への request に X-API-Key が乗り、
    MF access_token は載らない (情報漏洩防止)。"""
    import proxy_endpoints as pe

    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["headers"] = dict(request.headers)
        captured["url"] = str(request.url)
        return httpx.Response(
            200,
            json={
                "items": [
                    {"title": "テスト補助金", "tier": "S", "source_url": "https://example.gov.jp/x"}
                ]
            },
        )

    transport = httpx.MockTransport(handler)
    real_async = httpx.AsyncClient

    class _Patched(real_async):
        def __init__(self, *a, **kw):
            kw["transport"] = transport
            super().__init__(*a, **kw)

    monkeypatch.setattr(pe.httpx, "AsyncClient", _Patched)

    c = _client()
    _seed_session_cookie(
        c,
        {
            "access_token": "SECRET_ACCESS_DO_NOT_LEAK",
            "refresh_token": "SECRET_REFRESH_DO_NOT_LEAK",
            "tenant_uid": "tenant-001",
            "tenant_name": "テスト",
            "scope": "mfc/ac/data.read",
        },
    )
    r = c.post("/mf-plugin/search-subsidies", json={"keyword": "省エネ"})
    assert r.status_code == 200, r.text

    # X-API-Key が付与されている
    headers_lower = {k.lower(): v for k, v in captured.get("headers", {}).items()}
    assert headers_lower.get("x-api-key") == "jpcite_test_dummy_value_xyz"
    assert headers_lower.get("x-mf-tenant-uid") == "tenant-001"
    assert headers_lower.get("x-plugin-source") == "mf-cloud"

    # MF token が upstream に絶対漏れていない
    raw = " ".join(f"{k}={v}" for k, v in captured.get("headers", {}).items())
    assert "SECRET_ACCESS_DO_NOT_LEAK" not in raw
    assert "SECRET_REFRESH_DO_NOT_LEAK" not in raw

    # response に _disclaimer が付与されている
    body = r.json()
    assert "_disclaimer" in body
    assert "税理士法" in body["_disclaimer"]


def test_proxy_input_validation_keyword_required():
    c = _client()
    _seed_session_cookie(c, {"access_token": "x", "tenant_uid": "t1"})
    for path in (
        "/mf-plugin/search-subsidies",
        "/mf-plugin/search-tax-incentives",
        "/mf-plugin/search-laws",
        "/mf-plugin/search-court-decisions",
    ):
        r = c.post(path, json={"keyword": ""})
        assert r.status_code == 400, f"{path} returned {r.status_code}"
        assert r.json()["detail"] == "keyword_required"


def test_health_endpoint_no_auth_required():
    c = _client()
    r = c.get("/healthz")
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_csp_frame_ancestors_includes_mf_hosts():
    c = _client()
    r = c.get("/healthz")
    csp = r.headers.get("content-security-policy", "")
    assert "frame-ancestors" in csp
    assert "https://app.biz.moneyforward.com" in csp
    assert "https://accounting.biz.moneyforward.com" in csp
