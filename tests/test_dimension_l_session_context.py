"""Tests for Dim L contextual session surface (Wave 46 dim 19).

Closes the Wave 46 dim 19 / dim L gap: stateless → multi-turn turn-around
via 3-endpoint state-token surface (open / step / close, 24h TTL).

Covers:
  * file existence + router prefix + tag
  * NO LLM SDK import (5-axis CI guard parity)
  * §52 / §47条の2 / §72 / §1 disclaimer present
  * open → step → close happy path
  * state_token shape (32 hex chars)
  * unknown / expired token → 410
  * step cap (32 entries) → 413
  * close invalidates token (second close → 410)
"""

from __future__ import annotations

import importlib.util
import pathlib
import re
import sys
import time

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = REPO_ROOT / "src" / "jpintel_mcp" / "api" / "session_context.py"


def _import_session_context():
    spec = importlib.util.spec_from_file_location("_session_test_mod", SRC)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_session_test_mod"] = mod
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Module-load tests
# ---------------------------------------------------------------------------


def test_file_exists() -> None:
    assert SRC.exists(), "src/jpintel_mcp/api/session_context.py is required"
    src = SRC.read_text(encoding="utf-8")
    assert 'router = APIRouter(prefix="/v1/session"' in src
    assert 'tags=["session-context"]' in src


def test_no_llm_imports() -> None:
    src = SRC.read_text(encoding="utf-8")
    banned = (
        "anthropic",
        "openai",
        "google.generativeai",
        "claude_agent_sdk",
    )
    for needle in banned:
        pattern = rf"^\s*(import|from)\s+{re.escape(needle)}\b"
        assert not re.search(pattern, src, re.MULTILINE), f"LLM SDK import detected: {needle}"


def test_disclaimer_present() -> None:
    src = SRC.read_text(encoding="utf-8")
    assert "税理士法" in src and "52" in src
    assert "公認会計士法" in src and "47条の2" in src
    assert "弁護士法" in src and "72" in src
    assert "行政書士法" in src


def test_24h_ttl_constant() -> None:
    mod = _import_session_context()
    assert mod.SESSION_TTL_SEC == 24 * 60 * 60


# ---------------------------------------------------------------------------
# Functional tests
# ---------------------------------------------------------------------------


def _make_app():
    from fastapi import FastAPI

    mod = _import_session_context()
    app = FastAPI()
    app.include_router(mod.router)
    return app, mod


@pytest.fixture
def client():
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    app, mod = _make_app()
    # Reset in-process store between tests.
    mod._SESSIONS.clear()
    return TestClient(app), mod


def test_open_step_close_happy_path(client) -> None:
    c, _ = client
    r = c.post("/v1/session/open", json={"saved_context": {"intent": "discover"}})
    assert r.status_code == 200, r.text
    body = r.json()
    token = body["state_token"]
    assert isinstance(token, str)
    assert re.fullmatch(r"[0-9a-f]{32}", token), token
    assert body["steps"] == 0
    assert body["saved_context"] == {"intent": "discover"}
    assert "_disclaimer" in body and "_billing_unit" in body

    r2 = c.post("/v1/session/step", json={"state_token": token, "step": {"q": "hello"}})
    assert r2.status_code == 200, r2.text
    body2 = r2.json()
    assert body2["steps"] == 1
    assert body2["state_token"] == token

    r3 = c.post("/v1/session/close", json={"state_token": token})
    assert r3.status_code == 200, r3.text
    body3 = r3.json()
    assert body3["steps"] == 1
    assert len(body3["step_log"]) == 1
    assert body3["step_log"][0]["data"] == {"q": "hello"}

    # Second close → 410 (token invalidated).
    r4 = c.post("/v1/session/close", json={"state_token": token})
    assert r4.status_code == 410


def test_unknown_token_returns_410(client) -> None:
    c, _ = client
    bogus = "0" * 32
    r = c.post("/v1/session/step", json={"state_token": bogus, "step": {"x": 1}})
    assert r.status_code == 410


def test_expired_token_returns_410(client) -> None:
    c, mod = client
    r = c.post("/v1/session/open", json={"saved_context": {}})
    token = r.json()["state_token"]
    # Force expiry by rewinding expires_at.
    entry = mod._SESSIONS[token]
    entry.expires_at = time.time() - 1
    r2 = c.post("/v1/session/step", json={"state_token": token, "step": {}})
    assert r2.status_code == 410


def test_step_cap_returns_413(client) -> None:
    c, mod = client
    r = c.post("/v1/session/open", json={"saved_context": {}})
    token = r.json()["state_token"]
    # Manually push entries to cap (avoid 32 HTTP roundtrips).
    entry = mod._SESSIONS[token]
    entry.steps.extend([{"at": int(time.time()), "data": {"i": i}} for i in range(32)])
    r2 = c.post("/v1/session/step", json={"state_token": token, "step": {"q": "fail"}})
    assert r2.status_code == 413
    assert r2.json()["detail"]["code"] == "step_cap_exceeded"


def test_oversize_saved_context_returns_413(client) -> None:
    c, _ = client
    huge = {"big": "x" * (17 * 1024)}  # > 16 KiB
    r = c.post("/v1/session/open", json={"saved_context": huge})
    assert r.status_code == 413
    assert r.json()["detail"]["code"] == "saved_context_too_large"


def test_state_token_length_validation(client) -> None:
    c, _ = client
    # state_token min_length=32 / max_length=32 — anything else → 422
    r = c.post("/v1/session/step", json={"state_token": "short", "step": {}})
    assert r.status_code == 422


def test_store_stats_introspection() -> None:
    mod = _import_session_context()
    mod._SESSIONS.clear()
    stats = mod._store_stats()
    assert stats["session_count"] == 0
    assert stats["ttl_sec"] == 24 * 60 * 60
