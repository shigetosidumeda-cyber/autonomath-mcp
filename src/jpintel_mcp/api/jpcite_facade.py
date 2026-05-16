"""REST P0 facade for agent-runtime packet planning.

This router is intentionally deterministic. It exposes only the four P0
facade tools and does not call AWS, billing, artifact creation, or any
request-time LLM.
"""

from __future__ import annotations

import hashlib
from typing import Annotated, Any

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from jpintel_mcp.agent_runtime.billing_contract import (
    BillingContractDecision,
    ScopedCapTokenParseError,
    authorize_execute,
    build_live_billing_readiness_gate,
    parse_scoped_cap_token,
)
from jpintel_mcp.agent_runtime.defaults import (
    build_agent_purchase_decision,
    build_bootstrap_bundle,
    build_p0_facade,
)
from jpintel_mcp.agent_runtime.facade_contract import (
    P0FacadeToolContract,
    build_p0_facade_contract,
    build_p0_facade_contract_shape,
)
from jpintel_mcp.agent_runtime.outcome_catalog import build_outcome_catalog
from jpintel_mcp.agent_runtime.outcome_routing import (
    outcome_metadata_for_entry,
    preview_for_outcome,
    resolve_outcome_entry,
)
from jpintel_mcp.agent_runtime.packet_skeletons import get_packet_skeleton
from jpintel_mcp.services.csv_intake_preview import preview_accounting_csv_text
from jpintel_mcp.services.packets.inline_registry import (
    compose_inline_packet,
    inline_packet_registry_shape,
)

router = APIRouter(prefix="/v1/jpcite", tags=["jpcite-facade"])

_CONTRACTS = {tool.name: tool for tool in build_p0_facade_contract()}
_SCHEMA_VERSION = "jpcite.rest_facade.p0.v1"
_HTTP_STATUS_BY_REJECT_REASON = {
    "missing_idempotency_key": 403,
    "missing_scoped_cap_token": 403,
    "token_input_scope_mismatch": 403,
    "token_outcome_scope_mismatch": 403,
    "amount_only_token_rejected": 403,
    "token_price_cap_exceeded": 402,
}
_EXECUTE_RESPONSES: dict[int | str, dict[str, Any]] = {
    400: {"description": "Invalid scoped cap token or unknown outcome contract."},
    402: {"description": "Scoped cap token or requested price cap is below price."},
    403: {"description": "Missing or rejected execute purchase guard."},
    409: {"description": "Execute guard accepted, but live artifact execution is not wired."},
}
_EXECUTE_OPENAPI_EXTRA = {
    "parameters": [
        {
            "name": "Idempotency-Key",
            "in": "header",
            "required": True,
            "schema": {"type": "string", "minLength": 1},
            "description": "Required execute idempotency key. Missing or blank keys fail closed.",
        },
        {
            "name": "X-Jpcite-Scoped-Cap-Token",
            "in": "header",
            "required": True,
            "schema": {"type": "string", "minLength": 1},
            "description": (
                "Required JSON or base64url JSON scoped cap token bound to "
                "execute_input_hash, outcome_contract_id, and max_price_jpy."
            ),
        },
    ]
}


class FacadeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str | None = Field(default=None, max_length=4000)
    input_kind: str | None = Field(default=None, max_length=128)
    outcome_contract_id: str | None = Field(default=None, max_length=128)
    max_price_jpy: int | None = Field(default=None, ge=0)


class ExecutePacketRequest(FacadeRequest):
    packet_type: str | None = Field(default=None, max_length=128)


class AccountingCsvPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    csv_text: str = Field(min_length=1, max_length=2_000_000)
    filename: str | None = Field(default=None, max_length=240)


def _contract(name: str) -> dict[str, Any]:
    tool = _CONTRACTS[name]
    return tool.to_dict() if isinstance(tool, P0FacadeToolContract) else dict(tool)


def _input_hash(payload: BaseModel) -> str:
    raw = payload.model_dump_json(exclude_none=True, by_alias=True)
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _outcome_catalog_metadata(
    payload: FacadeRequest,
    *,
    strict_outcome_contract_id: bool = False,
) -> dict[str, Any] | None:
    entry = resolve_outcome_entry(
        input_kind=payload.input_kind,
        query=payload.query,
        outcome_contract_id=payload.outcome_contract_id,
        strict_outcome_contract_id=strict_outcome_contract_id,
    )
    if entry is None:
        return None
    return outcome_metadata_for_entry(entry, max_price_jpy=payload.max_price_jpy)


def _base_response(name: str, payload: BaseModel) -> dict[str, Any]:
    facade = build_p0_facade()
    return {
        "schema_version": _SCHEMA_VERSION,
        "tool": _contract(name),
        "input_hash": _input_hash(payload),
        "request_time_llm_call_performed": False,
        "aws_runtime_dependency_allowed": facade["aws_runtime_dependency_allowed"],
        "request_time_llm_fact_generation_enabled": facade[
            "request_time_llm_fact_generation_enabled"
        ],
        "live_billing_wired": build_p0_facade_contract_shape()["live_billing_wired"],
        "charged": False,
        "accepted_artifact_created": False,
    }


def _require_non_empty_header(value: str | None, *, header_name: str, code: str) -> str:
    if value is None or not value.strip():
        raise HTTPException(
            status_code=403,
            detail={
                "error": code,
                "message": f"{header_name} is required for jpcite_execute_packet.",
                "charged": False,
                "accepted_artifact_created": False,
            },
        )
    return value.strip()


def _execution_payload(
    *,
    response: dict[str, Any],
    outcome_catalog: dict[str, Any],
    billing_authorization: BillingContractDecision | None = None,
    status: str = "blocked_not_wired",
    error: str = "accepted_artifact_execution_not_wired",
) -> dict[str, Any]:
    execution = {
        "status": status,
        "error": error,
        "billable": False,
        "charge_allowed": False,
        "requires_scoped_cap_token": True,
        "requires_idempotency_key": True,
        "charge_basis": "accepted_artifact",
        "accepted_artifact_required_for_charge": True,
        "no_hit_charge_requires_explicit_consent": True,
        "outcome_contract_id": outcome_catalog["outcome_contract_id"],
        "estimated_price_jpy": outcome_catalog["estimated_price_jpy"],
        "max_price_jpy": outcome_catalog["max_price_jpy"],
        "execute_input_hash": outcome_catalog["execute_input_hash"],
        "live_billing_readiness_gate": build_live_billing_readiness_gate().model_dump(mode="json"),
    }
    if billing_authorization is not None:
        execution["billing_authorization"] = billing_authorization.model_dump(mode="json")
    response["execution"] = execution
    return response


def _invalid_token_detail(message: str) -> dict[str, Any]:
    return {
        "error": "invalid_scoped_cap_token",
        "message": message,
        "charged": False,
        "accepted_artifact_created": False,
    }


def _unknown_outcome_detail(
    response: dict[str, Any],
    outcome_contract_id: str | None,
) -> dict[str, Any]:
    response["execution"] = {
        "status": "blocked_unknown_outcome_contract",
        "error": "unknown_outcome_contract",
        "billable": False,
        "charge_allowed": False,
        "outcome_contract_id": outcome_contract_id,
        "available_outcome_contract_ids": [
            entry.outcome_contract_id for entry in build_outcome_catalog()
        ],
    }
    return response


def _requested_cap_reject_detail(
    response: dict[str, Any],
    outcome_catalog: dict[str, Any],
) -> dict[str, Any]:
    response["execution"] = {
        "status": "blocked_requested_price_cap",
        "error": "requested_price_cap_exceeded",
        "billable": False,
        "charge_allowed": False,
        "outcome_contract_id": outcome_catalog["outcome_contract_id"],
        "estimated_price_jpy": outcome_catalog["estimated_price_jpy"],
        "max_price_jpy": outcome_catalog["max_price_jpy"],
        "charged": False,
        "accepted_artifact_created": False,
    }
    return response


def _compose_inline_packet(packet_id: str) -> dict[str, Any] | None:
    return compose_inline_packet(packet_id)


@router.post("/route")
def route(payload: FacadeRequest) -> dict[str, Any]:
    response = _base_response("jpcite_route", payload)
    decision = build_agent_purchase_decision().model_dump(mode="json")
    outcome_catalog = _outcome_catalog_metadata(payload)
    if outcome_catalog is None:
        raise AssertionError("route outcome fallback should always resolve")
    preview = preview_for_outcome(
        outcome_catalog["outcome_contract_id"],
        payload.max_price_jpy,
    )
    recommended_tool = (
        "jpcite_preview_cost" if preview["status"] == "preview_ready" else "jpcite_route"
    )
    response["route"] = {
        "status": "route_ready",
        "billable": False,
        "charge_status": "not_charged",
        "input_kind": payload.input_kind or "evidence",
        "recommended_tool": recommended_tool,
        "recommended_action": decision["recommended_action"],
        "cheapest_sufficient_route": decision["cheapest_sufficient_route"],
        "deliverable_slug": outcome_catalog["deliverable_slug"],
        "outcome_contract_id": outcome_catalog["outcome_contract_id"],
        "recommended_outcome_contract_id": outcome_catalog["outcome_contract_id"],
        "estimated_price_jpy": outcome_catalog["estimated_price_jpy"],
        "execute_input_hash": outcome_catalog["execute_input_hash"],
        "requires_user_csv": outcome_catalog["requires_user_csv"],
        "evidence_dependency_types": outcome_catalog["evidence_dependency_types"],
        "catalog_count": outcome_catalog["catalog_count"],
        "reason_to_buy": decision["reason_to_buy"],
        "reason_not_to_buy": decision["reason_not_to_buy"],
        "known_gaps_before_purchase": decision["known_gaps_before_purchase"],
        "anti_upsell_gate_passed": True,
        "no_hit_caveat": decision["no_hit_caveat"],
        "scoped_cap_token_required": decision["scoped_cap_token_required"],
        "free_inline_packets": inline_packet_registry_shape(),
        "preview": preview,
        "next_action": (
            "call_jpcite_preview_cost"
            if recommended_tool == "jpcite_preview_cost"
            else "adjust_price_or_scope"
        ),
        "outcome_catalog": outcome_catalog,
    }
    return response


@router.post("/preview_cost")
def preview_cost(payload: FacadeRequest) -> dict[str, Any]:
    response = _base_response("jpcite_preview_cost", payload)
    decision = build_agent_purchase_decision().model_dump(mode="json")
    candidate = (payload.outcome_contract_id or "").strip()
    outcome_catalog = _outcome_catalog_metadata(
        payload,
        strict_outcome_contract_id=bool(candidate),
    )
    if outcome_catalog is None:
        preview = preview_for_outcome(candidate, payload.max_price_jpy)
        preview["free_inline_packets"] = inline_packet_registry_shape()
        response["cost_preview"] = preview
        return response

    preview = preview_for_outcome(
        outcome_catalog["outcome_contract_id"],
        payload.max_price_jpy,
    )
    response["cost_preview"] = {
        **preview,
        "billable": False,
        "free_preflight": True,
        "predicted_total_jpy": 0,
        "max_price_jpy": outcome_catalog["max_price_jpy"],
        "estimated_price_jpy": outcome_catalog["estimated_price_jpy"],
        "cap_passed": outcome_catalog["cap_passed"],
        "execute_input_hash": outcome_catalog["execute_input_hash"],
        "deliverable_slug": outcome_catalog["deliverable_slug"],
        "outcome_contract_id": outcome_catalog["outcome_contract_id"],
        "requires_user_csv": outcome_catalog["requires_user_csv"],
        "evidence_dependency_types": outcome_catalog["evidence_dependency_types"],
        "catalog_count": outcome_catalog["catalog_count"],
        "coverage_roi_curve": decision["coverage_roi_curve"],
        "known_gaps_before_purchase": decision["known_gaps_before_purchase"],
        "no_hit_caveat": decision["no_hit_caveat"],
        "accepted_artifact_required_for_charge": True,
        "free_inline_packets": inline_packet_registry_shape(),
        "outcome_catalog": outcome_catalog,
    }
    return response


@router.post("/preview_accounting_csv")
def preview_accounting_csv(payload: AccountingCsvPreviewRequest) -> dict[str, Any]:
    response = _base_response("jpcite_preview_cost", payload)
    response["csv_intake_preview"] = preview_accounting_csv_text(
        payload.csv_text,
        filename=payload.filename,
    )
    return response


@router.post(
    "/execute_packet",
    responses=_EXECUTE_RESPONSES,
    openapi_extra=_EXECUTE_OPENAPI_EXTRA,
)
def execute_packet(
    payload: ExecutePacketRequest,
    idempotency_key: Annotated[
        str | None,
        Header(alias="Idempotency-Key", include_in_schema=False),
    ] = None,
    scoped_cap_token: Annotated[
        str | None,
        Header(alias="X-Jpcite-Scoped-Cap-Token", include_in_schema=False),
    ] = None,
) -> dict[str, Any]:
    scoped_cap_token = _require_non_empty_header(
        scoped_cap_token,
        header_name="X-Jpcite-Scoped-Cap-Token",
        code="scoped_cap_token_required",
    )
    idempotency_key = _require_non_empty_header(
        idempotency_key,
        header_name="Idempotency-Key",
        code="idempotency_key_required",
    )
    response = _base_response("jpcite_execute_packet", payload)
    outcome_catalog = _outcome_catalog_metadata(payload, strict_outcome_contract_id=True)
    if outcome_catalog is None:
        raise HTTPException(
            status_code=400,
            detail=_unknown_outcome_detail(response, payload.outcome_contract_id),
        )
    if not outcome_catalog["cap_passed"]:
        raise HTTPException(
            status_code=402,
            detail=_requested_cap_reject_detail(response, outcome_catalog),
        )

    try:
        token = parse_scoped_cap_token(scoped_cap_token)
    except ScopedCapTokenParseError as exc:
        raise HTTPException(
            status_code=400,
            detail=_invalid_token_detail(str(exc)),
        ) from exc

    billing_authorization = authorize_execute(
        scoped_cap_token=token,
        idempotency_key=idempotency_key,
        outcome_contract_id=outcome_catalog["outcome_contract_id"],
        input_hash=outcome_catalog["execute_input_hash"],
        price_jpy=outcome_catalog["estimated_price_jpy"],
    )
    if billing_authorization.action == "reject":
        detail = _execution_payload(
            response=response,
            outcome_catalog=outcome_catalog,
            billing_authorization=billing_authorization,
            status="blocked_purchase_guard_rejected",
            error=billing_authorization.reject_reason,
        )
        raise HTTPException(
            status_code=_HTTP_STATUS_BY_REJECT_REASON.get(
                billing_authorization.reject_reason,
                403,
            ),
            detail=detail,
        )

    raise HTTPException(
        status_code=409,
        detail=_execution_payload(
            response=response,
            outcome_catalog=outcome_catalog,
            billing_authorization=billing_authorization,
        ),
    )


@router.get("/get_packet/{packet_id}")
def get_packet(packet_id: str) -> dict[str, Any]:
    payload = FacadeRequest(query=None, outcome_contract_id=packet_id)
    response = _base_response("jpcite_get_packet", payload)
    bundle = build_bootstrap_bundle()
    if packet_id == bundle["release_capsule_manifest"]["capsule_id"]:
        response["packet"] = {
            "packet_id": packet_id,
            "status": "capsule_contract_packet",
            "billable": False,
            "charge_status": "not_charged",
            "packet": {
                "release_capsule_manifest": bundle["release_capsule_manifest"],
                "capability_matrix": bundle["capability_matrix"],
                "preflight_scorecard": bundle["preflight_scorecard"],
            },
            "no_hit_caveat": "no_hit_not_absence",
        }
        return response
    inline_packet = _compose_inline_packet(packet_id)
    if inline_packet is not None:
        response["packet"] = {
            "packet_id": packet_id,
            "status": "inline_static_packet",
            "billable": False,
            "charge_status": "not_charged",
            "accepted_artifact_created": False,
            "paid_packet_body_materialized": False,
            "packet": inline_packet,
        }
        return response
    skeleton_entry = resolve_outcome_entry(
        outcome_contract_id=packet_id,
        strict_outcome_contract_id=True,
    )
    if skeleton_entry is not None:
        response["packet"] = {
            "packet_id": packet_id,
            "status": "static_packet_skeleton",
            "billable": False,
            "charge_status": "not_charged",
            "accepted_artifact_created": False,
            "paid_packet_body_materialized": False,
            "outcome_contract_id": skeleton_entry.outcome_contract_id,
            "deliverable_slug": skeleton_entry.deliverable_slug,
            "packet": get_packet_skeleton(skeleton_entry.outcome_contract_id),
            "known_gaps": ("paid_artifact_body_not_materialized",),
            "no_hit_caveat": "no_hit_not_absence",
        }
        return response
    response["packet"] = {
        "packet_id": packet_id,
        "status": "packet_not_found_or_not_materialized",
        "reason": "accepted_artifact_store_not_wired",
        "known_gaps": ("packet_store_not_live_until_accepted_artifact_gate",),
        "no_hit_caveat": "no_hit_not_absence",
    }
    raise HTTPException(status_code=404, detail=response)


__all__ = ["router"]
