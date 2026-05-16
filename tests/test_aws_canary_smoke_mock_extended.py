"""AWS canary smoke test — extended mock surface (Stream W unlock paths).

Extension of ``tests/test_aws_canary_smoke_mock.py`` (tick 11, 18 tests
landed) covering 12 additional scenarios that exercise the Stream W
"scorecard promote concern separation" path: pre-unlock state, token-gated
flip to ``live_aws=True``, missing-token exit code, scorecard preservation
across unlock, 4-guard budget thresholds with explicit values, batch job
definition routing, Cost Explorer envelope, the 4-tier threshold action
fan-out (watch / slowdown / no-new-work / absolute_stop), and
token-gated emergency kill switch terminating all jobs.

Every scenario uses ``unittest.mock.MagicMock`` only — boto3, botocore,
aiohttp, httpx, requests, socket, subprocess, and urllib are forbidden
by an AST guard mirroring the tick 11 module + ``test_aws_execution_templates.py``.

Wave 50 Stream W (tick 12+) supplement (2026-05-16).
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

# ----------------------------------------------------------------------------
# Module-level guard: forbid boto3 / subprocess / network in this test file.
# Mirrors tick 11 (test_aws_canary_smoke_mock.py) + test_aws_execution_templates.py.
# ----------------------------------------------------------------------------


_THIS_FILE = Path(__file__).resolve()


def test_no_real_aws_or_network_imports_in_canary_smoke_extended() -> None:
    """AST scan: this extended test file must not import boto3/subprocess/network."""

    forbidden_imports = {
        "aiohttp",
        "boto3",
        "botocore",
        "httpx",
        "requests",
        "socket",
        "subprocess",
        "urllib",
        "urllib3",
    }
    forbidden_attr_calls = {
        ("os", "system"),
        ("subprocess", "Popen"),
        ("subprocess", "call"),
        ("subprocess", "run"),
        ("subprocess", "check_call"),
        ("subprocess", "check_output"),
    }

    tree = ast.parse(_THIS_FILE.read_text(encoding="utf-8"))

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                assert root not in forbidden_imports, (
                    f"forbidden import {alias.name!r} in canary mock extended test"
                )
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                root = node.module.split(".")[0]
                assert root not in forbidden_imports, (
                    f"forbidden from-import {node.module!r} in canary mock extended test"
                )
        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
                pair = (func.value.id, func.attr)
                assert pair not in forbidden_attr_calls, (
                    f"forbidden subprocess-style call {pair!r} in canary mock extended test"
                )


# ----------------------------------------------------------------------------
# Mock factories — mirrors tick 11 module's MagicMock + in-memory state pattern.
# ----------------------------------------------------------------------------


def _make_mock_budgets() -> MagicMock:
    """Budgets mock with create_budget/describe_budgets/delete_budget surface."""

    client = MagicMock(name="budgets")
    client._budgets: dict[str, dict[str, Any]] = {}

    def _create(account_id: str, budget: dict[str, Any], **_kwargs: Any) -> dict[str, Any]:
        name = budget["BudgetName"]
        client._budgets[name] = budget
        return {"ResponseMetadata": {"HTTPStatusCode": 200}}

    def _describe(account_id: str, **_kwargs: Any) -> dict[str, Any]:
        return {"Budgets": list(client._budgets.values())}

    client.create_budget.side_effect = _create
    client.describe_budgets.side_effect = _describe
    return client


def _make_mock_batch() -> MagicMock:
    """Batch mock: submit_job / describe_jobs / terminate_job / list_jobs."""

    client = MagicMock(name="batch")
    client._jobs: dict[str, dict[str, Any]] = {}

    def _submit(jobName: str, jobQueue: str, jobDefinition: str, **_kwargs: Any) -> dict[str, Any]:
        job_id = f"job-{len(client._jobs):04d}"
        client._jobs[job_id] = {
            "jobId": job_id,
            "jobName": jobName,
            "jobQueue": jobQueue,
            "jobDefinition": jobDefinition,
            "status": "SUBMITTED",
        }
        return {"jobId": job_id, "jobName": jobName, "jobDefinition": jobDefinition}

    def _terminate(jobId: str, reason: str = "canary teardown", **_kwargs: Any) -> dict[str, Any]:
        if jobId in client._jobs:
            client._jobs[jobId]["status"] = "TERMINATED"
        return {"ResponseMetadata": {"HTTPStatusCode": 200}}

    client.submit_job.side_effect = _submit
    client.terminate_job.side_effect = _terminate
    return client


def _make_mock_ce(spend_usd: float = 0.42) -> MagicMock:
    """Cost Explorer mock returning a configurable blended-cost envelope."""

    client = MagicMock(name="ce")
    client._spend_usd = spend_usd

    def _get_cost(**_kwargs: Any) -> dict[str, Any]:
        return {
            "ResultsByTime": [
                {
                    "Total": {
                        "BlendedCost": {"Amount": f"{client._spend_usd:.4f}", "Unit": "USD"},
                        "UnblendedCost": {"Amount": f"{client._spend_usd:.4f}", "Unit": "USD"},
                    },
                    "TimePeriod": {"Start": "2026-05-16", "End": "2026-05-17"},
                }
            ]
        }

    client.get_cost_and_usage.side_effect = _get_cost
    return client


# ----------------------------------------------------------------------------
# Stream W unlock state machine — scorecard + token-gated live_aws flip.
# ----------------------------------------------------------------------------


class ScorecardState:
    """Preflight scorecard with Stream W unlock concern-separation."""

    EXIT_CODE_MISSING_TOKEN = 64

    def __init__(self) -> None:
        # Stream A 5/5 READY but scorecard.state remains AWS_BLOCKED until unlock
        self.state = "AWS_BLOCKED_PRE_FLIGHT"
        self.live_aws_commands_allowed = False  # ABSOLUTE — false unless unlock applied
        self.preflight_ready = 5
        self.preflight_total = 5
        self.unlock_history: list[dict[str, Any]] = []
        # canary side-effect state
        self.jobs: dict[str, dict[str, Any]] = {}

    def unlock_live_aws(self, token: str | None) -> int:
        """Apply Stream W ``--unlock-live-aws-commands`` flag.

        Returns process exit code. Token absent => exit 64 (sysexits.h
        EX_USAGE) and ``live_aws_commands_allowed`` stays False.
        """

        if not token:
            return self.EXIT_CODE_MISSING_TOKEN
        self.live_aws_commands_allowed = True
        self.state = "AWS_CANARY_READY"
        self.unlock_history.append({"token_present": True, "result": "unlocked"})
        return 0

    def fire_action(self, threshold_usd: int) -> str:
        """4-tier action fan-out per `aws_canary_execution_checklist.yaml`."""

        action_map = {
            17000: "watch",
            18300: "slowdown",
            18900: "no_new_work",
            19300: "absolute_stop",
        }
        return action_map.get(threshold_usd, "unknown")

    def emergency_kill_all_jobs(self, token: str | None, batch_mock: MagicMock) -> int:
        """Token-gated emergency kill: terminates all running batch jobs."""

        if not token:
            return self.EXIT_CODE_MISSING_TOKEN
        for job_id, meta in list(batch_mock._jobs.items()):
            if meta.get("status") in {"SUBMITTED", "RUNNING"}:
                batch_mock.terminate_job(jobId=job_id, reason="emergency kill")
        return 0


@pytest.fixture
def scorecard() -> ScorecardState:
    return ScorecardState()


# ----------------------------------------------------------------------------
# 12 additional tests
# ----------------------------------------------------------------------------


def test_canary_pre_unlock_state_aws_blocked(scorecard: ScorecardState) -> None:
    """Pre-unlock: scorecard state is AWS_BLOCKED, live_aws flag = False."""

    assert scorecard.state == "AWS_BLOCKED_PRE_FLIGHT"
    assert scorecard.live_aws_commands_allowed is False
    assert scorecard.preflight_ready == 5
    assert scorecard.preflight_total == 5
    assert scorecard.unlock_history == []


def test_canary_unlock_with_token_flips_live_aws_true(scorecard: ScorecardState) -> None:
    """Stream W: providing operator token flips live_aws to True + state to READY."""

    rc = scorecard.unlock_live_aws(token="operator-uuid-mock-1234")
    assert rc == 0
    assert scorecard.live_aws_commands_allowed is True
    assert scorecard.state == "AWS_CANARY_READY"
    assert len(scorecard.unlock_history) == 1
    assert scorecard.unlock_history[0]["result"] == "unlocked"


def test_canary_unlock_without_token_exits_64(scorecard: ScorecardState) -> None:
    """Missing token => exit 64 (EX_USAGE), live_aws stays False."""

    rc = scorecard.unlock_live_aws(token=None)
    assert rc == 64
    assert scorecard.live_aws_commands_allowed is False
    assert scorecard.state == "AWS_BLOCKED_PRE_FLIGHT"

    rc_empty = scorecard.unlock_live_aws(token="")
    assert rc_empty == 64
    assert scorecard.live_aws_commands_allowed is False


def test_canary_unlock_preserves_scorecard_state(scorecard: ScorecardState) -> None:
    """Unlock must NOT mutate the 5/5 preflight READY counters."""

    pre_ready = scorecard.preflight_ready
    pre_total = scorecard.preflight_total

    scorecard.unlock_live_aws(token="operator-uuid-mock-1234")

    assert scorecard.preflight_ready == pre_ready
    assert scorecard.preflight_total == pre_total
    assert scorecard.preflight_ready == 5
    assert scorecard.preflight_total == 5


def test_canary_budget_create_4_guards_with_correct_thresholds() -> None:
    """4 budget guards: 17K / 18.3K / 18.9K / 19.3K with explicit USD values."""

    budgets = _make_mock_budgets()
    account_id = "993693061769"

    spec = [
        ("jpcite-watch-17000", 17000),
        ("jpcite-slowdown-18300", 18300),
        ("jpcite-no-new-work-18900", 18900),
        ("jpcite-absolute-19300", 19300),
    ]
    for name, limit in spec:
        budgets.create_budget(
            account_id=account_id,
            budget={
                "BudgetName": name,
                "BudgetLimit": {"Amount": str(limit), "Unit": "USD"},
                "TimeUnit": "MONTHLY",
                "BudgetType": "COST",
            },
        )

    described = budgets.describe_budgets(account_id=account_id)
    assert len(described["Budgets"]) == 4

    by_name = {b["BudgetName"]: b for b in described["Budgets"]}
    assert int(by_name["jpcite-watch-17000"]["BudgetLimit"]["Amount"]) == 17000
    assert int(by_name["jpcite-slowdown-18300"]["BudgetLimit"]["Amount"]) == 18300
    assert int(by_name["jpcite-no-new-work-18900"]["BudgetLimit"]["Amount"]) == 18900
    assert int(by_name["jpcite-absolute-19300"]["BudgetLimit"]["Amount"]) == 19300


def test_canary_batch_submit_with_correct_job_definition() -> None:
    """Batch submit routes to the canary job definition + queue."""

    batch = _make_mock_batch()

    resp = batch.submit_job(
        jobName="jpcite-canary-1m",
        jobQueue="jpcite-canary-q",
        jobDefinition="jpcite-canary-1m",
    )
    assert resp["jobId"] == "job-0000"
    assert resp["jobDefinition"] == "jpcite-canary-1m"

    submitted = batch._jobs["job-0000"]
    assert submitted["jobName"] == "jpcite-canary-1m"
    assert submitted["jobQueue"] == "jpcite-canary-q"
    assert submitted["jobDefinition"] == "jpcite-canary-1m"
    assert submitted["status"] == "SUBMITTED"
    batch.submit_job.assert_called_once()


def test_canary_observe_cost_explorer_returns_blended_cost() -> None:
    """Cost Explorer mock returns blended USD cost matching configured spend."""

    ce = _make_mock_ce(spend_usd=0.4275)

    result = ce.get_cost_and_usage(
        TimePeriod={"Start": "2026-05-16", "End": "2026-05-17"},
        Granularity="DAILY",
        Metrics=["BlendedCost", "UnblendedCost"],
    )

    by_time = result["ResultsByTime"][0]
    blended = float(by_time["Total"]["BlendedCost"]["Amount"])
    unblended = float(by_time["Total"]["UnblendedCost"]["Amount"])

    assert blended == pytest.approx(0.4275, abs=1e-4)
    assert unblended == pytest.approx(0.4275, abs=1e-4)
    assert by_time["Total"]["BlendedCost"]["Unit"] == "USD"
    assert by_time["TimePeriod"]["Start"] == "2026-05-16"


def test_canary_threshold_17K_fires_watch_action(scorecard: ScorecardState) -> None:
    """Threshold 17000 fires action='watch'."""

    action = scorecard.fire_action(17000)
    assert action == "watch"


def test_canary_threshold_18_3K_fires_slowdown_action(scorecard: ScorecardState) -> None:
    """Threshold 18300 fires action='slowdown'."""

    action = scorecard.fire_action(18300)
    assert action == "slowdown"


def test_canary_threshold_18_9K_fires_no_new_work_action(scorecard: ScorecardState) -> None:
    """Threshold 18900 fires action='no_new_work'."""

    action = scorecard.fire_action(18900)
    assert action == "no_new_work"


def test_canary_threshold_19_3K_fires_absolute_stop_action(scorecard: ScorecardState) -> None:
    """Threshold 19300 fires action='absolute_stop' (4th-tier fan-out)."""

    action = scorecard.fire_action(19300)
    assert action == "absolute_stop"


def test_canary_emergency_kill_with_token_terminates_all_jobs(
    scorecard: ScorecardState,
) -> None:
    """Emergency kill (token-gated) terminates every SUBMITTED/RUNNING job."""

    batch = _make_mock_batch()

    # Arm 3 jobs across SUBMITTED + RUNNING states
    batch.submit_job(
        jobName="jpcite-canary-1m-a",
        jobQueue="jpcite-canary-q",
        jobDefinition="jpcite-canary-1m",
    )
    batch.submit_job(
        jobName="jpcite-canary-1m-b",
        jobQueue="jpcite-canary-q",
        jobDefinition="jpcite-canary-1m",
    )
    job_c = batch.submit_job(
        jobName="jpcite-canary-1m-c",
        jobQueue="jpcite-canary-q",
        jobDefinition="jpcite-canary-1m",
    )
    # Promote one job to RUNNING to assert kill covers both states
    batch._jobs[job_c["jobId"]]["status"] = "RUNNING"

    # Missing-token path: no jobs terminated
    rc_miss = scorecard.emergency_kill_all_jobs(token=None, batch_mock=batch)
    assert rc_miss == 64
    assert all(j["status"] in {"SUBMITTED", "RUNNING"} for j in batch._jobs.values())

    # With token: all jobs terminated
    rc_ok = scorecard.emergency_kill_all_jobs(
        token="operator-emergency-uuid-mock", batch_mock=batch
    )
    assert rc_ok == 0
    assert len(batch._jobs) == 3
    assert all(j["status"] == "TERMINATED" for j in batch._jobs.values())
    assert batch.terminate_job.call_count == 3


# ----------------------------------------------------------------------------
# Real-AWS-call zero verification: every client in this module is MagicMock.
# ----------------------------------------------------------------------------


def test_extended_mocks_record_no_real_aws_io() -> None:
    """All clients used in extended scenarios are MagicMock (zero real API call)."""

    budgets = _make_mock_budgets()
    batch = _make_mock_batch()
    ce = _make_mock_ce()

    for client in (budgets, batch, ce):
        assert isinstance(client, MagicMock)
        assert client.__class__.__name__ == "MagicMock"
        # MagicMock does NOT inherit from any boto3 / botocore base
        assert not any(
            base.__module__.startswith(("boto3", "botocore"))
            for base in type(client).__mro__
            if hasattr(base, "__module__")
        )
