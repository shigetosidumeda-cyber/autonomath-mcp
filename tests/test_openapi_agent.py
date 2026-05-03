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
    assert body["paths"]["/v1/intelligence/precomputed/query"]["get"][
        "x-jpcite-agent-priority"
    ] == 1
    assert operation["x-jpcite-agent-priority"] == 2
    component_names = set(body.get("components", {}).get("schemas", {}))
    assert "AuthorizeRequest" not in component_names
    assert "BillingHistoryResponse" not in component_names
    assert "BillingPortalResponse" not in component_names


def test_agent_openapi_has_stable_operation_ids_and_stats_routes(
    client: TestClient,
) -> None:
    response = client.get("/v1/openapi.agent.json")
    assert response.status_code == 200, response.text
    body = response.json()

    expected_operation_ids = {
        ("get", "/v1/intelligence/precomputed/query"): "prefetchIntelligence",
        ("post", "/v1/evidence/packets/query"): "queryEvidencePacket",
        ("get", "/v1/programs/search"): "searchPrograms",
        ("get", "/v1/programs/{unified_id}"): "getProgram",
        ("get", "/v1/source_manifest/{program_id}"): "getSourceManifest",
        ("get", "/v1/meta/freshness"): "getMetaFreshness",
        ("get", "/v1/stats/coverage"): "getStatsCoverage",
        ("get", "/v1/stats/freshness"): "getStatsFreshness",
        ("post", "/v1/citations/verify"): "verifyCitations",
        ("post", "/v1/cost/preview"): "previewCost",
    }

    seen: list[str] = []
    for (method, path), operation_id in expected_operation_ids.items():
        operation = body["paths"][path][method]
        assert operation["operationId"] == operation_id
        assert operation["x-jpcite-agent-safe"] is True
        seen.append(operation["operationId"])

    assert len(seen) == len(set(seen))
    for path in ("/v1/stats/coverage", "/v1/stats/freshness"):
        operation = body["paths"][path]["get"]
        assert operation["security"] == [{"ApiKeyAuth": []}, {}]
        assert operation["x-jpcite-auth"] == "optional_x_api_key_for_paid_volume"
