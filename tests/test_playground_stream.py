"""Test playground SSE stream."""


import pytest
from httpx import ASGITransport, AsyncClient

from jpintel_mcp.api.playground_stream import router


@pytest.fixture
def app():
    from fastapi import FastAPI

    a = FastAPI()
    a.include_router(router)
    return a


@pytest.mark.asyncio
async def test_evidence3_stream_step1(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        async with c.stream(
            "GET", "/v1/playground/evidence3/stream?step=1&houjin_bangou=1010001000001"
        ) as resp:
            assert resp.status_code == 200
            assert "text/event-stream" in resp.headers["content-type"]
            events = []
            async for line in resp.aiter_lines():
                events.append(line)
                if len(events) > 30:
                    break
            joined = "\n".join(events)
            assert "event: status" in joined
            assert "event: section" in joined
            assert "event: done" in joined


@pytest.mark.asyncio
async def test_evidence3_stream_invalid_step(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/v1/playground/evidence3/stream?step=99&houjin_bangou=1010001000001")
        assert resp.status_code == 422


@pytest.mark.asyncio
async def test_evidence3_stream_invalid_houjin(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/v1/playground/evidence3/stream?step=1&houjin_bangou=invalid")
        assert resp.status_code == 422
