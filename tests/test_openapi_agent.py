from __future__ import annotations

from typing import TYPE_CHECKING

from jpintel_mcp.api.openapi_agent import AGENT_SAFE_PATHS, build_agent_openapi_schema

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
    funding_billing = body["paths"]["/v1/funding_stack/check"]["post"]["x-jpcite-billing"]
    assert funding_billing["billing_quantity_basis"] == "evaluated_compatibility_pair_count"
    assert funding_billing["billing_unit_type"] == "compatibility_pair"
    assert funding_billing["billing_units_per_successful_call"] == "pair_count"
    assert "total_pairs" in funding_billing["billing_quantity_response_fields"]
    compatibility_operation = body["paths"]["/v1/artifacts/compatibility_table"]["post"]
    compatibility_billing = compatibility_operation["x-jpcite-billing"]
    assert compatibility_billing["billing_quantity_basis"] == "compatibility_pair"
    assert compatibility_billing["billing_unit_type"] == "compatibility_pair"
    assert compatibility_billing["billing_units_per_successful_call"] == "pair_count"
    assert "C(unique_program_count, 2)" in compatibility_billing["billing_units_formula"]
    assert "billing_metadata.quantity" in compatibility_billing["billing_quantity_response_fields"]
    assert "5制度なら10 pairs" in compatibility_billing["plain_ja"]
    first_hop = body["info"]["x-jpcite-first-hop-policy"]
    assert first_hop["first_call"] == "createCompanyPublicBaseline"
    assert "source_url" in first_hop["must_preserve_fields"]
    assert "known_gaps" in first_hop["web_search_after_jpcite_only_for"]
    assert (
        body["paths"]["/v1/intelligence/precomputed/query"]["get"]["x-jpcite-agent-priority"] == 1
    )
    company_operation = body["paths"]["/v1/artifacts/company_public_baseline"]["post"]
    assert company_operation["x-jpcite-agent-priority"] == 1
    assert company_operation["x-jpcite-route-purpose"] == "japanese_company_first_hop"
    assert "source_url" in company_operation["x-jpcite-must-preserve-fields"]
    assert "credit_safe" in company_operation["x-jpcite-must-not-claim"]
    assert "known_gaps" in company_operation["x-jpcite-web-search-after"]
    strategy_operation = body["paths"]["/v1/artifacts/application_strategy_pack"]["post"]
    assert strategy_operation["x-jpcite-agent-priority"] == 1
    assert strategy_operation["x-jpcite-route-purpose"] == "public_support_application_strategy"
    assert strategy_operation["x-jpcite-billing"]["billing_quantity_basis"] == "successful_call"
    assert strategy_operation["x-jpcite-billing"]["billing_unit_type"] == "api_call"
    assert strategy_operation["x-jpcite-billing"]["billing_units_per_successful_call"] == 1
    assert (
        "preparing_subsidy_loan_or_tax_incentive_options"
        in strategy_operation["x-jpcite-recommended-when"]
    )
    assert "subsidy_or_loan_approved" in strategy_operation["x-jpcite-must-not-claim"]
    prescreen_operation = body["paths"]["/v1/programs/prescreen"]["post"]
    assert prescreen_operation["x-jpcite-agent-priority"] == 2
    assert prescreen_operation["x-jpcite-route-purpose"] == "program_candidate_prescreen"
    assert "fit_score" in prescreen_operation["x-jpcite-must-preserve-fields"]
    assert "final_eligibility_confirmed" in prescreen_operation["x-jpcite-must-not-claim"]
    predicate_operation = body["paths"]["/v1/programs/{program_id}/eligibility_predicate"]["get"]
    assert predicate_operation["x-jpcite-agent-priority"] == 2
    assert predicate_operation["x-jpcite-route-purpose"] == "machine_readable_program_eligibility"
    assert "predicate_json" in predicate_operation["x-jpcite-must-preserve-fields"]
    assert "missing_axis_means_no_requirement" in predicate_operation["x-jpcite-must-not-claim"]
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
        (
            "post",
            "/v1/artifacts/application_strategy_pack",
        ): "createApplicationStrategyPack",
        ("post", "/v1/artifacts/houjin_dd_pack"): "createHoujinDdPack",
        (
            "post",
            "/v1/artifacts/company_public_baseline",
        ): "createCompanyPublicBaseline",
        ("post", "/v1/artifacts/company_folder_brief"): "createCompanyFolderBrief",
        (
            "post",
            "/v1/artifacts/company_public_audit_pack",
        ): "createCompanyPublicAuditPack",
        ("post", "/v1/programs/prescreen"): "prescreenPrograms",
        (
            "get",
            "/v1/programs/{program_id}/eligibility_predicate",
        ): "getProgramEligibilityPredicate",
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


def test_agent_openapi_preserves_evidence_packet_value_guidance_schema(
    client: TestClient,
) -> None:
    response = client.get("/v1/openapi.agent.json")
    assert response.status_code == 200, response.text
    body = response.json()

    envelope = body["components"]["schemas"]["EvidencePacketEnvelope"]
    properties = envelope["properties"]
    assert "evidence_value" in properties
    assert "decision_insights" in properties

    response_schema = body["paths"]["/v1/evidence/packets/query"]["post"]["responses"]["200"][
        "content"
    ]["application/json"]["schema"]
    assert response_schema == {"$ref": "#/components/schemas/EvidencePacketEnvelope"}


def test_agent_openapi_omits_first_hop_policy_when_artifact_backend_is_absent() -> None:
    schema = build_agent_openapi_schema(
        {
            "openapi": "3.1.0",
            "info": {"title": "full", "version": "test"},
            "paths": {
                "/v1/evidence/packets/query": {
                    "post": {
                        "responses": {
                            "200": {
                                "description": "OK",
                                "content": {
                                    "application/json": {
                                        "schema": {"type": "object"},
                                    },
                                },
                            },
                        },
                    },
                },
            },
        }
    )

    assert "x-jpcite-first-hop-policy" not in schema["info"]
    assert "createCompanyPublicBaseline" not in schema["info"]["description"]
    assert "/v1/evidence/packets/query" in schema["paths"]
    assert not any(path.startswith("/v1/artifacts/") for path in schema["paths"])
