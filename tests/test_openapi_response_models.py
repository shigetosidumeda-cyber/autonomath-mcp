"""Regression tests for generated OpenAPI response models."""

from __future__ import annotations

from typing import Any


def _schema_for_200(
    openapi_schema: dict[str, Any],
    method: str,
    path: str,
) -> dict[str, Any]:
    return openapi_schema["paths"][path][method]["responses"]["200"]["content"]["application/json"][
        "schema"
    ]


def _resolve_schema(
    openapi_schema: dict[str, Any],
    schema: dict[str, Any],
) -> dict[str, Any]:
    while "$ref" in schema:
        ref = schema["$ref"]
        name = ref.removeprefix("#/components/schemas/")
        schema = openapi_schema["components"]["schemas"][name]
    return schema


def _properties(
    openapi_schema: dict[str, Any],
    schema: dict[str, Any],
) -> dict[str, Any]:
    resolved = _resolve_schema(openapi_schema, schema)
    props = dict(resolved.get("properties", {}))
    for combinator in ("allOf", "anyOf", "oneOf"):
        for branch in resolved.get(combinator, []):
            props.update(_properties(openapi_schema, branch))
    return props


def _array_items_schema(
    openapi_schema: dict[str, Any],
    schema: dict[str, Any],
) -> dict[str, Any]:
    resolved = _resolve_schema(openapi_schema, schema)
    if resolved.get("type") == "array":
        return _resolve_schema(openapi_schema, resolved["items"])
    for combinator in ("anyOf", "oneOf", "allOf"):
        for branch in resolved.get(combinator, []):
            try:
                return _array_items_schema(openapi_schema, branch)
            except AssertionError:
                continue
    raise AssertionError(f"Expected array schema, got: {resolved}")


def test_generated_openapi_exposes_decision_insights_and_funding_stack_actions() -> None:
    from jpintel_mcp.api.main import create_app
    from jpintel_mcp.api.openapi_agent import build_agent_openapi_schema

    schema = create_app().openapi()
    components = schema["components"]["schemas"]

    envelope = components["EvidencePacketEnvelope"]
    assert "decision_insights" in envelope["properties"]
    assert "decision_insights" in envelope["example"]

    funding_response = components["FundingStackCheckResponse"]
    funding_pair = components["FundingStackPair"]
    assert "next_actions" in funding_response["properties"]
    assert "next_actions" in funding_pair["properties"]

    response_schema = schema["paths"]["/v1/funding_stack/check"]["post"]["responses"]["200"][
        "content"
    ]["application/json"]["schema"]
    assert response_schema["$ref"].endswith("/FundingStackCheckResponse")

    agent_schema = build_agent_openapi_schema(schema)
    agent_components = agent_schema["components"]["schemas"]
    assert "decision_insights" in agent_components["EvidencePacketEnvelope"]["properties"]
    assert "next_actions" in agent_components["FundingStackCheckResponse"]["properties"]
    assert "next_actions" in agent_components["FundingStackPair"]["properties"]


def test_generated_openapi_exposes_intel_value_response_fields() -> None:
    from jpintel_mcp.api.main import create_app

    schema = create_app().openapi()

    match_response = _schema_for_200(schema, "post", "/v1/intel/match")
    assert match_response, "POST /v1/intel/match has empty 200 schema"
    match_properties = _properties(schema, match_response)
    assert "matched_programs" in match_properties
    matched_program_items = _array_items_schema(
        schema,
        match_properties["matched_programs"],
    )
    matched_program_properties = _properties(schema, matched_program_items)
    assert {
        "next_questions",
        "eligibility_gaps",
        "document_readiness",
    } <= set(matched_program_properties)

    for method, path in (
        ("post", "/v1/intel/bundle/optimal"),
        ("get", "/v1/intel/houjin/{houjin_id}/full"),
    ):
        response_schema = _schema_for_200(schema, method, path)
        assert response_schema, f"{method.upper()} {path} has empty 200 schema"
        assert "decision_support" in _properties(schema, response_schema)


def test_generated_openapi_exposes_artifact_response_contract() -> None:
    from jpintel_mcp.api.main import create_app

    schema = create_app().openapi()

    for path in (
        "/v1/artifacts/compatibility_table",
        "/v1/artifacts/application_strategy_pack",
        "/v1/artifacts/houjin_dd_pack",
        "/v1/artifacts/company_public_baseline",
        "/v1/artifacts/company_folder_brief",
        "/v1/artifacts/company_public_audit_pack",
    ):
        response_schema = _schema_for_200(schema, "post", path)
        assert response_schema["$ref"].endswith("/ArtifactResponse")
        props = _properties(schema, response_schema)
        assert {
            "artifact_id",
            "artifact_type",
            "packet_id",
            "summary",
            "sections",
            "sources",
            "known_gaps",
            "source_receipts",
            "_evidence",
            "billing_note",
            "billing_metadata",
            "corpus_snapshot_id",
            "corpus_checksum",
            "next_actions",
            "_disclaimer",
            "recommended_followup_by_channel",
            "agent_routing",
            "audit_seal",
            "_seal_unavailable",
        } <= set(props)

    artifact_props = schema["components"]["schemas"]["ArtifactResponse"]["properties"]
    evidence_props = _properties(schema, artifact_props["_evidence"])
    assert {
        "source_count",
        "source_refs",
        "known_gap_count",
        "known_gap_refs",
        "claim_coverage",
        "source_receipt_completion",
        "basis_fields",
    } <= set(evidence_props)

    known_gap_items = _array_items_schema(schema, artifact_props["known_gaps"])
    known_gap_props = _properties(schema, known_gap_items)
    assert {
        "gap_id",
        "severity",
        "message",
        "message_ja",
        "section",
        "source_fields",
    } <= set(known_gap_props)

    routing_props = _properties(schema, artifact_props["agent_routing"])
    assert {
        "call_jpcite_first_for",
        "use_web_search_after",
        "preserve_fields",
        "no_llm_called_by_jpcite",
        "pricing_note",
    } <= set(routing_props)

    channel_props = _properties(schema, artifact_props["recommended_followup_by_channel"])
    assert {
        "use_jpcite_next",
        "use_web_search_for",
        "use_professional_review_for",
    } <= set(channel_props)

    seal_props = _properties(schema, artifact_props["audit_seal"])
    assert {
        "seal_id",
        "issued_at",
        "subject_hash",
        "key_hash_prefix",
        "corpus_snapshot_id",
        "verify_endpoint",
        "_disclaimer",
        "call_id",
        "ts",
        "endpoint",
        "query_hash",
        "response_hash",
        "source_urls",
        "alg",
        "key_version",
        "hmac",
    } <= set(seal_props)

    receipt_props = schema["components"]["schemas"]["ArtifactSourceReceipt"]["properties"]
    assert {
        "source_receipt_id",
        "source_url",
        "used_in",
        "source_fetched_at",
        "content_hash",
        "license",
    } <= set(receipt_props)

    billing_props = schema["components"]["schemas"]["ArtifactBillingMetadata"]["properties"]
    assert {
        "endpoint",
        "unit_type",
        "quantity",
        "result_count",
        "metered",
        "strict_metering",
        "pricing_note",
        "value_basis",
        "audit_seal",
    } <= set(billing_props)
