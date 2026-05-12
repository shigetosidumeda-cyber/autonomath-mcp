"""Dim S — copilot_scaffold REST endpoint tests (Wave 46 dim 19 SFGH).

Covers ``src/jpintel_mcp/api/copilot_scaffold.py`` (Wave 46 dim 19 SFGH)
which ships:

  * ``GET /v1/copilot/scaffold/partners``  partner whitelist discovery
  * ``GET /v1/copilot/scaffold/{partner}``  scaffold envelope per partner

Posture (feedback_copilot_scaffold_only_no_llm):

  * **NO LLM call.** The whole point of dim S is that jpcite ships
    scaffold-only — no Anthropic / OpenAI import in production code.
    Test asserts this at module-import time.
  * Pure unit test — no DB fixture, no live network. We mount the
    router under a tiny ``FastAPI()`` and exercise via TestClient.
  * Schemas are pydantic only, no migration dependency.
"""

from __future__ import annotations

import importlib

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client() -> TestClient:
    """Tiny FastAPI app with only the copilot scaffold router."""
    from jpintel_mcp.api.copilot_scaffold import router

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_partners_endpoint_returns_whitelist(client: TestClient) -> None:
    """GET /v1/copilot/scaffold/partners returns 4 partners + no_llm=true."""
    resp = client.get("/v1/copilot/scaffold/partners")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 4
    assert sorted(body["partners"]) == ["freee", "mf", "notion", "slack"]
    assert body["no_llm"] is True
    assert "disclaimer" in body


@pytest.mark.parametrize("partner", ["freee", "mf", "notion", "slack"])
def test_each_partner_scaffold_renders(client: TestClient, partner: str) -> None:
    """GET /v1/copilot/scaffold/{partner} returns deterministic scaffold."""
    resp = client.get(f"/v1/copilot/scaffold/{partner}")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["partner"] == partner
    assert body["no_llm"] is True
    assert body["billing_unit"] == 1
    # widget skeleton is a static HTML string, not LLM output
    assert body["widget_html_skeleton"].startswith("<div id=")
    assert 'data-no-llm="true"' in body["widget_html_skeleton"]
    assert body["mcp_proxy_url"].startswith("https://")
    assert body["oauth_bridge_url"].startswith("https://")
    assert body["asset_bundle_url"].startswith("https://")


def test_unknown_partner_returns_404(client: TestClient) -> None:
    """Non-whitelisted partner returns 404 with helpful error."""
    resp = client.get("/v1/copilot/scaffold/gusto")
    assert resp.status_code == 404
    detail = resp.json()["detail"]
    assert "unknown partner" in detail.lower()
    # error includes the allowed list — helps discovery
    assert "freee" in detail


def test_scaffold_widget_skeleton_is_deterministic(client: TestClient) -> None:
    """Calling the same partner twice yields byte-identical scaffold.

    This is the dim S invariant: no LLM = no stochastic output. The
    scaffold MUST be reproducible across calls.
    """
    r1 = client.get("/v1/copilot/scaffold/notion").json()
    r2 = client.get("/v1/copilot/scaffold/notion").json()
    assert r1["widget_html_skeleton"] == r2["widget_html_skeleton"]
    assert r1["mcp_proxy_url"] == r2["mcp_proxy_url"]


def test_no_llm_imports_in_copilot_module() -> None:
    """Hard guard: copilot_scaffold module must not import an LLM SDK.

    Mirrors the pattern from test_no_llm_in_production.py at the
    per-module granularity. This is THE dim S invariant.
    """
    import jpintel_mcp.api.copilot_scaffold as mod

    src = importlib.import_module(mod.__name__).__file__
    assert src is not None
    with open(src, encoding="utf-8") as f:
        text = f.read()
    # Banned SDK roots — these MUST NOT appear as imports in the module
    banned_imports = [
        "import anthropic",
        "from anthropic",
        "import openai",
        "from openai",
        "import google.generativeai",
        "from google.generativeai",
        "import cohere",
        "from cohere",
    ]
    for ban in banned_imports:
        assert ban not in text, f"banned LLM import found in copilot_scaffold: {ban}"


def test_verify_no_llm_imports_helper() -> None:
    """The module-level smoke helper reports no leaked LLM imports."""
    from jpintel_mcp.api.copilot_scaffold import _verify_no_llm_imports

    report = _verify_no_llm_imports()
    assert report["no_llm_verified"] is True
    assert report["leaked_imports"] == []
