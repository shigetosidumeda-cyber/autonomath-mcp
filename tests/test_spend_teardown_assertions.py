"""Roundtrip tests for the assertion-list + flip-authority fields.

Stream A added ``assertions_to_pass_state_true`` and
``pass_state_flip_authority`` to the spend / teardown JSON artifacts. The
Pydantic models live under ``extra="forbid"`` so the readiness-gate check
script needs the fields to be declared explicitly.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from jpintel_mcp.agent_runtime.contracts import (
    SpendSimulation,
    TeardownSimulation,
)


def _spend_base() -> dict[str, object]:
    return {
        "simulation_id": "test:spend",
        "control_spend_usd": 0.0,
        "queue_exposure_usd": 0.0,
        "service_tail_risk_usd": 0.0,
        "teardown_debt_usd": 0.0,
        "ineligible_charge_uncertainty_reserve_usd": 0.0,
        "pass_state": False,
    }


def _teardown_base() -> dict[str, object]:
    return {
        "simulation_id": "test:teardown",
        "all_resources_have_delete_recipe": False,
        "pass_state": False,
    }


def test_spend_simulation_accepts_assertions_list_roundtrip() -> None:
    payload = _spend_base() | {
        "assertions_to_pass_state_true": [
            "cash_bill_guard_enabled == true",
            "queue_exposure_usd == 0",
            "preflight_evidence_passed == true",
        ],
        "pass_state_flip_authority": "separate_task_not_this_artifact",
    }

    model = SpendSimulation.model_validate(payload)

    assert model.assertions_to_pass_state_true == (
        "cash_bill_guard_enabled == true",
        "queue_exposure_usd == 0",
        "preflight_evidence_passed == true",
    )
    assert model.pass_state_flip_authority == "separate_task_not_this_artifact"

    dumped = model.model_dump()
    assert isinstance(dumped["assertions_to_pass_state_true"], tuple)
    assert len(dumped["assertions_to_pass_state_true"]) == 3


def test_spend_simulation_defaults_when_fields_absent() -> None:
    model = SpendSimulation.model_validate(_spend_base())

    assert model.assertions_to_pass_state_true == ()
    assert model.pass_state_flip_authority == "separate_task_not_this_artifact"


def test_teardown_simulation_accepts_assertions_list_roundtrip() -> None:
    payload = _teardown_base() | {
        "assertions_to_pass_state_true": [
            "all_resources_have_delete_recipe == true",
            "post_teardown_cost_meter_review.lingering_charge_usd <= 1",
        ],
        "pass_state_flip_authority": "preflight_runner",
    }

    model = TeardownSimulation.model_validate(payload)

    assert model.assertions_to_pass_state_true == (
        "all_resources_have_delete_recipe == true",
        "post_teardown_cost_meter_review.lingering_charge_usd <= 1",
    )
    assert model.pass_state_flip_authority == "preflight_runner"


def test_teardown_simulation_defaults_when_fields_absent() -> None:
    model = TeardownSimulation.model_validate(_teardown_base())

    assert model.assertions_to_pass_state_true == ()
    assert model.pass_state_flip_authority == "separate_task_not_this_artifact"


def test_spend_simulation_rejects_unknown_flip_authority() -> None:
    payload = _spend_base() | {"pass_state_flip_authority": "self_flip"}

    with pytest.raises(ValidationError):
        SpendSimulation.model_validate(payload)


def test_teardown_simulation_rejects_unknown_flip_authority() -> None:
    payload = _teardown_base() | {"pass_state_flip_authority": "self_flip"}

    with pytest.raises(ValidationError):
        TeardownSimulation.model_validate(payload)


def test_operator_flip_authority_value_is_allowed() -> None:
    spend = SpendSimulation.model_validate(
        _spend_base() | {"pass_state_flip_authority": "operator"}
    )
    teardown = TeardownSimulation.model_validate(
        _teardown_base() | {"pass_state_flip_authority": "operator"}
    )

    assert spend.pass_state_flip_authority == "operator"
    assert teardown.pass_state_flip_authority == "operator"
