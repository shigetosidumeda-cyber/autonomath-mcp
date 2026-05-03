from __future__ import annotations

from typing import TYPE_CHECKING

from jpintel_mcp.api.openapi_agent import AGENT_SAFE_PATHS

if TYPE_CHECKING:
    from fastapi.testclient import TestClient


def test_agent_openapi_exposes_only_evidence_safe_paths(client: TestClient) -> None:
    response = client.get("/v1/openapi.agent.json")
    assert response.status_code == 200, response.text
    body = response.json()

    assert set(body["paths"]) == set(AGENT_SAFE_PATHS)
    assert body.get("security") == []
    assert "/v1/billing/checkout" not in body["paths"]
    assert "/v1/billing/webhook" not in body["paths"]
    assert "/v1/oauth/google/start" not in body["paths"]

    operation = body["paths"]["/v1/evidence/packets/query"]["post"]
    assert operation["x-jpcite-agent-safe"] is True
    assert operation["security"] == [{"ApiKeyAuth": []}, {}]
