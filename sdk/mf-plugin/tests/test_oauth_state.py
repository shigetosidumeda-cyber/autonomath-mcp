"""OAuth state CSRF + env 検証 + redirect URL の smoke test。

実 MF / 実 jpcite は叩かない (httpx.MockTransport で全モック化)。
"""

from __future__ import annotations

import os

import httpx
import pytest
from fastapi.testclient import TestClient


def _client():
    from app import create_app

    app = create_app()
    return TestClient(app)


# ---- env 検証 --------------------------------------------------------------


def test_load_settings_passes_with_full_env():
    from config import load_settings

    s = load_settings()
    assert s.mf_client_id == "test-client-id"
    assert s.mf_scope == "mfc/ac/data.read"
    assert s.redirect_uri == "https://mf-plugin.jpcite.com/oauth/callback"


def test_load_settings_accepts_legacy_api_env(monkeypatch):
    from config import load_settings

    monkeypatch.delenv("JPCITE_API_KEY", raising=False)
    monkeypatch.delenv("JPCITE_API_BASE", raising=False)
    monkeypatch.setenv("ZEIMU_KAIKEI_API_KEY", "legacy_key")
    monkeypatch.setenv("ZEIMU_KAIKEI_BASE_URL", "https://legacy-api.example.test")

    s = load_settings()
    assert s.jpcite_api_key == "legacy_key"
    assert s.jpcite_api_base == "https://legacy-api.example.test"


def test_load_settings_missing(monkeypatch):
    from config import load_settings

    monkeypatch.delenv("MF_CLIENT_ID", raising=False)
    with pytest.raises(RuntimeError, match="missing"):
        load_settings()


def test_load_settings_short_secret(monkeypatch):
    from config import load_settings

    monkeypatch.setenv("SESSION_SECRET", "too-short")
    with pytest.raises(RuntimeError, match=">= 32"):
        load_settings()


# ---- /oauth/authorize -------------------------------------------------------


def test_authorize_redirects_to_mf_with_state():
    c = _client()
    r = c.get("/oauth/authorize", follow_redirects=False)
    assert r.status_code == 302
    loc = r.headers["location"]
    assert loc.startswith("https://app.biz.moneyforward.com/oauth/authorize?")
    assert "client_id=test-client-id" in loc
    assert "scope=mfc%2Fac%2Fdata.read" in loc
    assert "state=" in loc
    # session cookie が立っている
    assert any(c.name == "jpcite_mf_sid" for c in c.cookies.jar)


def test_callback_rejects_bad_state():
    c = _client()
    # authorize を踏まずに直接 callback → state mismatch
    r = c.get("/oauth/callback?code=abc&state=fake", follow_redirects=False)
    assert r.status_code == 400


# ---- callback (token exchange mock) ----------------------------------------


def _make_mock_transport(token_response: dict, tenant_response: dict | None):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/oauth/token"):
            return httpx.Response(200, json=token_response)
        if request.url.path.endswith("/tenants"):
            return httpx.Response(200, json=tenant_response or {"data": []})
        if request.url.path.endswith("/oauth/revoke"):
            return httpx.Response(200, json={"ok": True})
        return httpx.Response(404, json={"error": "not_mocked", "path": request.url.path})

    return httpx.MockTransport(handler)


def test_callback_happy_path(monkeypatch):
    """authorize → callback の往復で session に access_token が入る。"""
    import oauth_callback as oc

    transport = _make_mock_transport(
        token_response={
            "access_token": "mf_access_xxx",
            "refresh_token": "mf_refresh_yyy",
            "expires_in": 3600,
            "scope": "mfc/ac/data.read",
            "token_type": "Bearer",
        },
        tenant_response={"data": [{"uid": "tenant-001", "name": "テスト株式会社"}]},
    )

    # httpx.AsyncClient を transport で差し替える
    real_async = httpx.AsyncClient

    class _Patched(real_async):
        def __init__(self, *a, **kw):
            kw["transport"] = transport
            super().__init__(*a, **kw)

    monkeypatch.setattr(oc.httpx, "AsyncClient", _Patched)

    c = _client()
    # 1) authorize で state を仕込む
    r1 = c.get("/oauth/authorize", follow_redirects=False)
    state = r1.headers["location"].split("state=")[1].split("&")[0]
    # 2) callback
    r2 = c.get(f"/oauth/callback?code=abc&state={state}", follow_redirects=False)
    assert r2.status_code == 302
    assert r2.headers["location"] == "/static/index.html"

    # 3) /mf-plugin/me で authed=True
    r3 = c.get("/mf-plugin/me")
    assert r3.status_code == 200
    body = r3.json()
    assert body["authed"] is True
    assert body["tenant_uid"] == "tenant-001"
    assert body["tenant_name"] == "テスト株式会社"
    # token は絶対に response に出さない
    assert "access_token" not in body
    assert "refresh_token" not in body


def test_callback_handles_user_denied():
    c = _client()
    # ユーザー拒否時は MF が ?error=access_denied で戻す
    r = c.get(
        "/oauth/callback?error=access_denied&error_description=User+denied&state=x&code=ignored",
        follow_redirects=False,
    )
    # state 不正だが error path が先に走る
    assert r.status_code == 302
    assert "auth_error=" in r.headers["location"]
