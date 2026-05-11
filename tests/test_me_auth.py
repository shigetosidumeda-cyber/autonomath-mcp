import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from jpintel_mcp.api.me import login_request, login_verify


@pytest.fixture
def app(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("AUTONOMATH_DB_PATH", str(db_path))
    monkeypatch.setenv("JPCITE_SESSION_SECRET", "test-secret-12345")
    monkeypatch.delenv("BOOKYOU_SMTP_PASS", raising=False)
    a = FastAPI()
    a.include_router(login_request.router)
    a.include_router(login_verify.router)
    return a


@pytest.mark.asyncio
async def test_request_then_verify(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r1 = await c.post("/v1/me/login_request", json={"email": "user@example.com"})
        assert r1.status_code == 200
        assert r1.json()["sent"] is True
        # Wrong code
        r2 = await c.post("/v1/me/login_verify", json={"email": "user@example.com", "code": "000000"})
        assert r2.status_code == 401
        # Bad format
        r3 = await c.post("/v1/me/login_verify", json={"email": "user@example.com", "code": "abc"})
        assert r3.status_code in (400, 422)
