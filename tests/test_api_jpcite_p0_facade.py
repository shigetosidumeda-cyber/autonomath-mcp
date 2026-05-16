import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from jpintel_mcp.agent_runtime.defaults import CAPSULE_ID
from jpintel_mcp.agent_runtime.facade_contract import build_p0_facade_contract_shape
from jpintel_mcp.agent_runtime.outcome_catalog import build_outcome_catalog
from jpintel_mcp.agent_runtime.pricing_policy import build_execute_input_hash
from jpintel_mcp.api.jpcite_facade import router


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _scoped_cap_token_for(
    payload: dict[str, object],
    *,
    outcome_contract_id: str = "company_public_baseline",
    max_price_jpy: int = 600,
    input_hash: str | None = None,
) -> str:
    payload_max_price = payload.get("max_price_jpy")
    execute_max_price = payload_max_price if isinstance(payload_max_price, int) else None
    token = {
        "token_kind": "scoped_cap_token",
        "input_hash": input_hash
        or build_execute_input_hash(outcome_contract_id, execute_max_price),
        "outcome_contract_id": outcome_contract_id,
        "max_price_jpy": max_price_jpy,
        "idempotency_key_required": True,
        "amount_only_token": False,
    }
    return json.dumps(token, separators=(",", ":"))


def _json_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        keys = set(value)
        for child in value.values():
            keys.update(_json_keys(child))
        return keys
    if isinstance(value, list):
        keys: set[str] = set()
        for child in value:
            keys.update(_json_keys(child))
        return keys
    return set()


def test_route_and_preview_cost_align_with_facade_contract() -> None:
    client = _client()
    contract = {tool["name"]: tool for tool in build_p0_facade_contract_shape()["tools"]}
    catalog_count = len(build_outcome_catalog())

    route_response = client.post("/v1/jpcite/route", json={"query": "tokyo subsidy"})
    assert route_response.status_code == 200
    route_body = route_response.json()
    assert route_body["tool"] == contract["jpcite_route"]
    assert route_body["charged"] is False
    assert route_body["accepted_artifact_created"] is False
    assert route_body["request_time_llm_call_performed"] is False
    assert route_body["aws_runtime_dependency_allowed"] is False
    route = route_body["route"]
    assert route["status"] == "route_ready"
    assert route["recommended_tool"] == "jpcite_preview_cost"
    assert route["deliverable_slug"] == "subsidy-grant-candidate-pack"
    assert route["recommended_outcome_contract_id"] == "application_strategy"
    assert route["preview"]["outcome_contract_id"] == "application_strategy"
    assert route["preview"]["status"] == "preview_ready"
    assert route["requires_user_csv"] is False
    assert route["catalog_count"] == catalog_count
    assert route["execute_input_hash"] == build_execute_input_hash("application_strategy", None)
    assert route["free_inline_packets"]["billable"] is False
    assert "outcome_catalog_summary" in route["free_inline_packets"]["packet_ids"]
    assert "source_receipt_ledger" in route["free_inline_packets"]["packet_ids"]
    assert "evidence_answer" in route["free_inline_packets"]["packet_ids"]
    assert route["outcome_catalog"]["catalog_count"] == catalog_count
    assert route["outcome_catalog"]["deliverable_slug"] == route["deliverable_slug"]
    assert "official_program_guideline" in route["evidence_dependency_types"]

    preview_response = client.post(
        "/v1/jpcite/preview_cost",
        json={
            "query": "csv counterparty check",
            "outcome_contract_id": "csv_overlay_public_check",
        },
    )
    assert preview_response.status_code == 200
    preview_body = preview_response.json()
    assert preview_body["tool"] == contract["jpcite_preview_cost"]
    cost_preview = preview_body["cost_preview"]
    assert cost_preview["status"] == "preview_ready"
    assert cost_preview["charge_status"] == "not_charged"
    assert cost_preview["free_preflight"] is True
    assert cost_preview["predicted_total_jpy"] == 0
    assert cost_preview["estimated_price_jpy"] == 900
    assert cost_preview["max_price_jpy"] is None
    assert cost_preview["cap_passed"] is True
    assert cost_preview["execute_input_hash"] == build_execute_input_hash(
        "csv_overlay_public_check",
        None,
    )
    assert cost_preview["free_inline_packets"]["charge_status"] == "not_charged"
    assert cost_preview["free_inline_packets"]["paid_packet_body_materialized"] is False
    assert cost_preview["deliverable_slug"] == "accounting-csv-public-counterparty-check"
    assert cost_preview["outcome_contract_id"] == "csv_overlay_public_check"
    assert cost_preview["requires_user_csv"] is True
    assert cost_preview["catalog_count"] == catalog_count
    assert cost_preview["outcome_catalog"]["catalog_count"] == catalog_count
    assert cost_preview["outcome_catalog"]["deliverable_slug"] == cost_preview["deliverable_slug"]
    assert "tenant_private_csv_overlay" in cost_preview["evidence_dependency_types"]
    assert preview_body["charged"] is False


def test_rest_route_and_preview_cover_all_14_outcome_catalog_deliverables() -> None:
    client = _client()

    for entry in build_outcome_catalog():
        route = client.post(
            "/v1/jpcite/route",
            json={"outcome_contract_id": entry.outcome_contract_id},
        ).json()["route"]
        preview = client.post(
            "/v1/jpcite/preview_cost",
            json={"outcome_contract_id": entry.deliverable_slug},
        ).json()["cost_preview"]

        assert route["recommended_tool"] == "jpcite_preview_cost"
        assert route["deliverable_slug"] == entry.deliverable_slug
        assert route["recommended_outcome_contract_id"] == entry.outcome_contract_id
        assert route["preview"]["packet_ids"]
        assert route["preview"]["billing_posture"] == entry.billing_posture
        assert route["preview"]["input_requirement"] == entry.input_requirement
        assert preview["status"] == "preview_ready"
        assert preview["deliverable_slug"] == entry.deliverable_slug
        assert preview["outcome_contract_id"] == entry.outcome_contract_id
        assert preview["requires_user_csv"] is entry.requires_user_csv
        assert preview["accepted_artifact_required_for_charge"] is True
        assert preview["no_hit_charge_requires_explicit_consent"] is True


def test_rest_route_uses_shared_aliases_for_japanese_agent_queries() -> None:
    client = _client()

    subsidy = client.post(
        "/v1/jpcite/route",
        json={"query": "補助金の候補を公的情報ベースで確認したい"},
    ).json()["route"]
    invoice = client.post(
        "/v1/jpcite/route",
        json={"query": "取引先のインボイス登録を確認したい"},
    ).json()["route"]
    healthcare = client.post(
        "/v1/jpcite/route",
        json={"query": "医療関連の規制や自治体通知を確認したい"},
    ).json()["route"]

    assert subsidy["recommended_outcome_contract_id"] == "application_strategy"
    assert invoice["recommended_outcome_contract_id"] == "invoice_registrant_public_check"
    assert healthcare["recommended_outcome_contract_id"] == ("healthcare_regulatory_public_check")


def test_preview_cost_unknown_outcome_fails_closed_without_fallback_or_charge() -> None:
    client = _client()

    response = client.post(
        "/v1/jpcite/preview_cost",
        json={"outcome_contract_id": "missing_outcome"},
    )

    assert response.status_code == 200
    preview = response.json()["cost_preview"]
    assert preview["status"] == "blocked_unknown_outcome_contract"
    assert preview["billable"] is False
    assert preview["charge_status"] == "not_charged"
    assert preview["outcome_contract_id"] == "missing_outcome"
    assert "company_public_baseline" in preview["available_outcome_contract_ids"]


def test_free_rest_facade_does_not_inline_heavy_release_catalogs() -> None:
    client = _client()

    route_body = client.post(
        "/v1/jpcite/route",
        json={"query": "company", "outcome_contract_id": "company_public_baseline"},
    ).json()
    preview_body = client.post(
        "/v1/jpcite/preview_cost",
        json={"query": "company", "outcome_contract_id": "company_public_baseline"},
    ).json()

    response_keys = _json_keys([route_body, preview_body])
    blocked_public_facade_keys = (
        "outcome_source_crosswalk",
        "aws_execution_templates",
        "packet_skeletons",
        "private_overlay",
        "claims",
    )
    for key in blocked_public_facade_keys:
        assert key not in response_keys


def test_execute_packet_fails_closed_without_scoped_cap_token() -> None:
    client = _client()

    response = client.post(
        "/v1/jpcite/execute_packet",
        headers={"Idempotency-Key": "idem-1"},
        json={"query": "tokyo subsidy"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == {
        "error": "scoped_cap_token_required",
        "message": "X-Jpcite-Scoped-Cap-Token is required for jpcite_execute_packet.",
        "charged": False,
        "accepted_artifact_created": False,
    }


def test_execute_packet_fails_closed_without_idempotency_key() -> None:
    client = _client()

    response = client.post(
        "/v1/jpcite/execute_packet",
        headers={"X-Jpcite-Scoped-Cap-Token": "cap-1"},
        json={"query": "tokyo subsidy"},
    )

    assert response.status_code == 403
    assert response.json()["detail"]["error"] == "idempotency_key_required"
    assert response.json()["detail"]["charged"] is False
    assert response.json()["detail"]["accepted_artifact_created"] is False


def test_execute_packet_rejects_blank_purchase_guards() -> None:
    client = _client()

    blank_token = client.post(
        "/v1/jpcite/execute_packet",
        headers={"Idempotency-Key": "idem-1", "X-Jpcite-Scoped-Cap-Token": "  "},
        json={"query": "tokyo subsidy"},
    )
    blank_idempotency = client.post(
        "/v1/jpcite/execute_packet",
        headers={"Idempotency-Key": "  ", "X-Jpcite-Scoped-Cap-Token": "cap-1"},
        json={"query": "tokyo subsidy"},
    )

    assert blank_token.status_code == 403
    assert blank_token.json()["detail"]["error"] == "scoped_cap_token_required"
    assert blank_token.json()["detail"]["charged"] is False
    assert blank_idempotency.status_code == 403
    assert blank_idempotency.json()["detail"]["error"] == "idempotency_key_required"
    assert blank_idempotency.json()["detail"]["charged"] is False


def test_execute_packet_with_required_guards_still_does_not_charge_or_create() -> None:
    client = _client()
    payload = {
        "query": "company",
        "outcome_contract_id": "company_public_baseline",
        "packet_type": "company_profile",
        "max_price_jpy": 600,
    }

    response = client.post(
        "/v1/jpcite/execute_packet",
        headers={
            "Idempotency-Key": "idem-1",
            "X-Jpcite-Scoped-Cap-Token": _scoped_cap_token_for(payload),
        },
        json=payload,
    )

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["tool"]["name"] == "jpcite_execute_packet"
    assert detail["tool"]["requires_scoped_cap_token"] is True
    assert detail["tool"]["requires_idempotency_key"] is True
    assert detail["charged"] is False
    assert detail["accepted_artifact_created"] is False
    assert detail["live_billing_wired"] is False
    assert detail["execution"]["status"] == "blocked_not_wired"
    assert detail["execution"]["billable"] is False
    assert detail["execution"]["charge_allowed"] is False
    assert detail["execution"]["charge_basis"] == "accepted_artifact"
    assert detail["execution"]["accepted_artifact_required_for_charge"] is True
    assert detail["execution"]["no_hit_charge_requires_explicit_consent"] is True
    assert detail["execution"]["estimated_price_jpy"] == 600
    authorization = detail["execution"]["billing_authorization"]
    assert authorization["action"] == "authorize_execute"
    assert authorization["charge_allowed"] is False
    assert authorization["charge_jpy"] == 0
    gate = detail["execution"]["live_billing_readiness_gate"]
    assert gate["target_tool"] == "jpcite_execute_packet"
    assert gate["status"] == "blocked"
    assert gate["gate_passed"] is False
    assert gate["live_billing_wired"] is False


def test_execute_packet_accepts_scoped_token_from_rest_preview_hash() -> None:
    client = _client()
    preview_payload = {
        "query": "company",
        "outcome_contract_id": "company_public_baseline",
        "max_price_jpy": 600,
    }
    preview = client.post("/v1/jpcite/preview_cost", json=preview_payload).json()["cost_preview"]
    execute_payload = {**preview_payload, "packet_type": "company_profile"}

    response = client.post(
        "/v1/jpcite/execute_packet",
        headers={
            "Idempotency-Key": "idem-preview-token",
            "X-Jpcite-Scoped-Cap-Token": _scoped_cap_token_for(
                execute_payload,
                input_hash=preview["execute_input_hash"],
            ),
        },
        json=execute_payload,
    )

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["execution"]["billing_authorization"]["action"] == "authorize_execute"
    assert detail["execution"]["execute_input_hash"] == preview["execute_input_hash"]
    assert detail["charged"] is False
    assert detail["accepted_artifact_created"] is False


def test_execute_packet_rejects_invalid_scoped_cap_token_without_charge() -> None:
    client = _client()

    response = client.post(
        "/v1/jpcite/execute_packet",
        headers={
            "Idempotency-Key": "idem-1",
            "X-Jpcite-Scoped-Cap-Token": "cap-1",
        },
        json={"query": "company", "outcome_contract_id": "company_public_baseline"},
    )

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert detail["error"] == "invalid_scoped_cap_token"
    assert detail["charged"] is False
    assert detail["accepted_artifact_created"] is False


def test_execute_packet_rejects_token_scope_mismatches_without_charge() -> None:
    client = _client()
    payload = {
        "query": "company",
        "outcome_contract_id": "company_public_baseline",
        "packet_type": "company_profile",
        "max_price_jpy": 600,
    }

    input_mismatch = client.post(
        "/v1/jpcite/execute_packet",
        headers={
            "Idempotency-Key": "idem-1",
            "X-Jpcite-Scoped-Cap-Token": _scoped_cap_token_for(
                payload,
                input_hash="sha256:other-request",
            ),
        },
        json=payload,
    )
    outcome_mismatch = client.post(
        "/v1/jpcite/execute_packet",
        headers={
            "Idempotency-Key": "idem-1",
            "X-Jpcite-Scoped-Cap-Token": _scoped_cap_token_for(
                payload,
                outcome_contract_id="source_receipt_ledger",
            ),
        },
        json=payload,
    )

    assert input_mismatch.status_code == 403
    assert input_mismatch.json()["detail"]["execution"]["error"] == ("token_input_scope_mismatch")
    assert input_mismatch.json()["detail"]["charged"] is False
    assert outcome_mismatch.status_code == 403
    assert outcome_mismatch.json()["detail"]["execution"]["error"] == (
        "token_outcome_scope_mismatch"
    )
    assert outcome_mismatch.json()["detail"]["accepted_artifact_created"] is False


def test_execute_packet_rejects_price_above_token_cap_without_charge() -> None:
    client = _client()
    payload = {
        "query": "company",
        "outcome_contract_id": "company_public_baseline",
        "packet_type": "company_profile",
        "max_price_jpy": 600,
    }

    response = client.post(
        "/v1/jpcite/execute_packet",
        headers={
            "Idempotency-Key": "idem-1",
            "X-Jpcite-Scoped-Cap-Token": _scoped_cap_token_for(
                payload,
                max_price_jpy=300,
            ),
        },
        json=payload,
    )

    assert response.status_code == 402
    detail = response.json()["detail"]
    assert detail["execution"]["error"] == "token_price_cap_exceeded"
    assert detail["execution"]["billing_authorization"]["action"] == "reject"
    assert detail["charged"] is False
    assert detail["accepted_artifact_created"] is False


def test_execute_packet_rejects_unknown_outcome_before_authorization() -> None:
    client = _client()
    payload = {
        "query": "company",
        "outcome_contract_id": "missing_outcome",
        "packet_type": "company_profile",
        "max_price_jpy": 600,
    }

    response = client.post(
        "/v1/jpcite/execute_packet",
        headers={
            "Idempotency-Key": "idem-1",
            "X-Jpcite-Scoped-Cap-Token": _scoped_cap_token_for(
                payload,
                outcome_contract_id="missing_outcome",
            ),
        },
        json=payload,
    )

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert detail["execution"]["status"] == "blocked_unknown_outcome_contract"
    assert "billing_authorization" not in detail["execution"]
    assert detail["charged"] is False
    assert detail["accepted_artifact_created"] is False


def test_execute_packet_rejects_zero_requested_cap_for_paid_outcome() -> None:
    client = _client()
    payload = {
        "query": "company",
        "outcome_contract_id": "company_public_baseline",
        "packet_type": "company_profile",
        "max_price_jpy": 0,
    }

    response = client.post(
        "/v1/jpcite/execute_packet",
        headers={
            "Idempotency-Key": "idem-1",
            "X-Jpcite-Scoped-Cap-Token": _scoped_cap_token_for(
                payload,
                max_price_jpy=600,
            ),
        },
        json=payload,
    )

    assert response.status_code == 402
    detail = response.json()["detail"]
    assert detail["execution"]["error"] == "requested_price_cap_exceeded"
    assert detail["execution"]["max_price_jpy"] == 0
    assert detail["charged"] is False


def test_execute_packet_openapi_documents_required_guards_and_fail_closed_codes() -> None:
    app = FastAPI()
    app.include_router(router)

    operation = app.openapi()["paths"]["/v1/jpcite/execute_packet"]["post"]

    parameters = {parameter["name"]: parameter for parameter in operation["parameters"]}
    assert parameters["Idempotency-Key"]["required"] is True
    assert parameters["X-Jpcite-Scoped-Cap-Token"]["required"] is True
    assert {"400", "402", "403", "409"} <= set(operation["responses"])


def test_get_packet_is_deterministic_not_found_without_artifact_store() -> None:
    client = _client()

    response = client.get("/v1/jpcite/get_packet/packet-1")

    assert response.status_code == 404
    detail = response.json()["detail"]
    assert detail["tool"]["name"] == "jpcite_get_packet"
    assert detail["packet"]["status"] == "packet_not_found_or_not_materialized"
    assert detail["packet"]["known_gaps"] == ["packet_store_not_live_until_accepted_artifact_gate"]
    assert detail["charged"] is False
    assert detail["accepted_artifact_created"] is False


def test_get_packet_can_return_bootstrap_capsule_contract() -> None:
    client = _client()

    response = client.get(f"/v1/jpcite/get_packet/{CAPSULE_ID}")

    assert response.status_code == 200
    packet_wrapper = response.json()["packet"]
    assert packet_wrapper["status"] == "capsule_contract_packet"
    assert packet_wrapper["billable"] is False
    assert packet_wrapper["packet"]["preflight_scorecard"]["state"] == ("AWS_BLOCKED_PRE_FLIGHT")


def test_get_packet_can_return_inline_static_source_receipt_ledger() -> None:
    client = _client()

    response = client.get("/v1/jpcite/get_packet/source_receipt_ledger")

    assert response.status_code == 200
    body = response.json()
    assert body["tool"]["name"] == "jpcite_get_packet"
    assert body["charged"] is False
    assert body["accepted_artifact_created"] is False
    packet_wrapper = body["packet"]
    assert packet_wrapper["status"] == "inline_static_packet"
    assert packet_wrapper["billable"] is False
    assert packet_wrapper["charge_status"] == "not_charged"
    assert packet_wrapper["paid_packet_body_materialized"] is False
    packet = packet_wrapper["packet"]
    assert packet["packet_kind"] == "source_receipt_ledger"
    assert packet["receipt_ledger"]["public_claims_release_allowed"] is True
    assert packet["receipt_ledger"]["issues"] == []


def test_get_packet_can_return_inline_static_outcome_catalog_summary() -> None:
    client = _client()

    response = client.get("/v1/jpcite/get_packet/outcome_catalog_summary")

    assert response.status_code == 200
    packet = response.json()["packet"]["packet"]
    assert packet["packet_kind"] == "outcome_catalog_summary"
    assert packet["billable"] is False
    assert packet["accepted_artifact_created"] is False
    assert packet["deliverable_count"] == len(build_outcome_catalog())
    assert packet["receipt_ledger"]["public_claims_release_allowed"] is True


def test_get_packet_can_return_inline_static_evidence_answer() -> None:
    client = _client()

    response = client.get("/v1/jpcite/get_packet/evidence_answer")

    assert response.status_code == 200
    packet = response.json()["packet"]["packet"]
    assert packet["packet_kind"] == "evidence_answer"
    assert packet["billable"] is False
    assert packet["accepted_artifact_created"] is False
    assert packet["request_time_llm_call_performed"] is False
    assert packet["live_source_fetch_performed"] is False


def test_get_packet_can_return_static_skeleton_by_outcome_id_or_slug() -> None:
    client = _client()

    by_id = client.get("/v1/jpcite/get_packet/company_public_baseline")
    by_slug = client.get("/v1/jpcite/get_packet/company-public-baseline")

    for response in (by_id, by_slug):
        assert response.status_code == 200
        wrapper = response.json()["packet"]
        assert wrapper["status"] == "static_packet_skeleton"
        assert wrapper["billable"] is False
        assert wrapper["charge_status"] == "not_charged"
        assert wrapper["accepted_artifact_created"] is False
        assert wrapper["paid_packet_body_materialized"] is False
        assert wrapper["outcome_contract_id"] == "company_public_baseline"
        assert wrapper["deliverable_slug"] == "company-public-baseline"
        assert wrapper["packet"]["schema_version"] == "jpcite.packet_skeleton.p0.v1"
        assert wrapper["packet"]["claims"]
        assert wrapper["known_gaps"] == ["paid_artifact_body_not_materialized"]


def test_facade_router_is_mounted_in_main_app() -> None:
    from jpintel_mcp.api.main import create_app

    paths = {
        route.path
        for route in create_app().routes
        if getattr(route, "path", "").startswith("/v1/jpcite/")
    }

    assert {
        "/v1/jpcite/route",
        "/v1/jpcite/preview_cost",
        "/v1/jpcite/preview_accounting_csv",
        "/v1/jpcite/execute_packet",
        "/v1/jpcite/get_packet/{packet_id}",
    }.issubset(paths)
