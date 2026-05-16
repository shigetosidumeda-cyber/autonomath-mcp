"""AWS canary smoke test (mock simulation only).

This module simulates the 7-step canary sequence documented in
``docs/_internal/aws_canary_execution_checklist.yaml`` **without** invoking
any real AWS API. ``boto3`` / ``botocore`` / ``aiohttp`` / ``requests`` /
``subprocess`` / ``socket`` / ``urllib`` are forbidden inside the test
module by an AST guard mirroring ``test_aws_execution_templates.py``.

Mock surface (8 AWS services exercised via ``unittest.mock.MagicMock``):

* STS ``GetCallerIdentity``
* Budgets ``CreateBudget`` / ``DescribeBudgets`` / ``DeleteBudget``
* Batch ``SubmitJob`` / ``DescribeJobs`` / ``TerminateJob``
* ECS ``CreateService`` / ``UpdateService``
* Bedrock ``CreateProvisionedModelThroughput``
* S3 ``PutObject`` / ``DeleteObject`` / ``ListBuckets``
* Cost Explorer ``GetCostAndUsage``
* OpenSearch / EC2 / RDS / Lambda / EventBridge probes for teardown

Each scenario is a pure in-memory simulation. No environment variable
manipulation reaches the real shell; no file under
``site/releases/rc1-p0-bootstrap/`` is touched.

Wave 50 Stream I supplement (2026-05-16).
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

# ----------------------------------------------------------------------------
# Module-level guard: forbid boto3 / subprocess / network in this test file.
# Mirrors test_aws_execution_templates.py to keep the "no real AWS call"
# invariant verifiable from CI without grep heuristics.
# ----------------------------------------------------------------------------


_THIS_FILE = Path(__file__).resolve()


def test_no_real_aws_or_network_imports_in_canary_smoke_mock() -> None:
    """AST scan: this test file must not import boto3 / subprocess / network."""

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
                    f"forbidden import {alias.name!r} in canary mock test"
                )
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                root = node.module.split(".")[0]
                assert root not in forbidden_imports, (
                    f"forbidden from-import {node.module!r} in canary mock test"
                )
        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
                pair = (func.value.id, func.attr)
                assert pair not in forbidden_attr_calls, (
                    f"forbidden subprocess-style call {pair!r} in canary mock test"
                )


# ----------------------------------------------------------------------------
# Mock AWS clients factory
# ----------------------------------------------------------------------------


def _make_mock_sts() -> MagicMock:
    """Return STS mock whose get_caller_identity returns the canary identity."""

    client = MagicMock(name="sts")
    client.get_caller_identity.return_value = {
        "UserId": "AIDAEXAMPLECANARY",
        "Account": "993693061769",
        "Arn": "arn:aws:iam::993693061769:user/bookyou-recovery-preflight",
        "ResponseMetadata": {"HTTPStatusCode": 200},
    }
    return client


def _make_mock_budgets() -> MagicMock:
    """Budgets mock with 4-budget describe + create/delete idempotent surface."""

    client = MagicMock(name="budgets")
    client._budgets: dict[str, dict[str, Any]] = {}

    def _create(account_id: str, budget: dict[str, Any], **_kwargs: Any) -> dict[str, Any]:
        name = budget["BudgetName"]
        client._budgets[name] = budget
        return {"ResponseMetadata": {"HTTPStatusCode": 200}}

    def _describe(account_id: str, **_kwargs: Any) -> dict[str, Any]:
        return {
            "Budgets": list(client._budgets.values()),
            "ResponseMetadata": {"HTTPStatusCode": 200},
        }

    def _delete(account_id: str, budget_name: str, **_kwargs: Any) -> dict[str, Any]:
        client._budgets.pop(budget_name, None)
        return {"ResponseMetadata": {"HTTPStatusCode": 200}}

    client.create_budget.side_effect = _create
    client.describe_budgets.side_effect = _describe
    client.delete_budget.side_effect = _delete
    return client


def _make_mock_batch() -> MagicMock:
    """Batch mock that submits / describes / terminates a single canary job."""

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
        return {"jobId": job_id, "jobName": jobName}

    def _describe(jobs: list[str], **_kwargs: Any) -> dict[str, Any]:
        return {"jobs": [client._jobs[j] for j in jobs if j in client._jobs]}

    def _terminate(jobId: str, reason: str = "canary teardown", **_kwargs: Any) -> dict[str, Any]:
        if jobId in client._jobs:
            client._jobs[jobId]["status"] = "TERMINATED"
        return {"ResponseMetadata": {"HTTPStatusCode": 200}}

    def _list(jobQueue: str, jobStatus: str = "RUNNING", **_kwargs: Any) -> dict[str, Any]:
        running = [j for j in client._jobs.values() if j.get("status") == jobStatus]
        return {"jobSummaryList": running}

    client.submit_job.side_effect = _submit
    client.describe_jobs.side_effect = _describe
    client.terminate_job.side_effect = _terminate
    client.list_jobs.side_effect = _list
    return client


def _make_mock_ecs() -> MagicMock:
    """ECS mock with create_service / update_service for scale-to-0 teardown."""

    client = MagicMock(name="ecs")
    client._services: dict[str, int] = {}

    def _create(cluster: str, serviceName: str, desiredCount: int = 1, **_kwargs: Any) -> dict[str, Any]:
        client._services[serviceName] = desiredCount
        return {"service": {"serviceName": serviceName, "desiredCount": desiredCount}}

    def _update(cluster: str, service: str, desiredCount: int, **_kwargs: Any) -> dict[str, Any]:
        client._services[service] = desiredCount
        return {"service": {"serviceName": service, "desiredCount": desiredCount}}

    def _list_clusters(**_kwargs: Any) -> dict[str, Any]:
        arns = [
            f"arn:aws:ecs:us-east-1:993693061769:cluster/jpcite-{name}"
            for name in client._services
        ]
        return {"clusterArns": arns}

    client.create_service.side_effect = _create
    client.update_service.side_effect = _update
    client.list_clusters.side_effect = _list_clusters
    return client


def _make_mock_bedrock() -> MagicMock:
    """Bedrock mock with create_provisioned_model_throughput + list/delete."""

    client = MagicMock(name="bedrock")
    client._provisioned: dict[str, dict[str, Any]] = {}

    def _create(provisionedModelName: str, modelUnits: int = 1, **_kwargs: Any) -> dict[str, Any]:
        arn = f"arn:aws:bedrock:us-east-1:993693061769:provisioned-model/{provisionedModelName}"
        client._provisioned[provisionedModelName] = {
            "provisionedModelName": provisionedModelName,
            "provisionedModelArn": arn,
            "modelUnits": modelUnits,
        }
        return {"provisionedModelArn": arn}

    def _list(**_kwargs: Any) -> dict[str, Any]:
        return {"provisionedModelSummaries": list(client._provisioned.values())}

    def _delete(provisionedModelId: str, **_kwargs: Any) -> dict[str, Any]:
        client._provisioned.pop(provisionedModelId, None)
        return {"ResponseMetadata": {"HTTPStatusCode": 200}}

    client.create_provisioned_model_throughput.side_effect = _create
    client.list_provisioned_model_throughputs.side_effect = _list
    client.delete_provisioned_model_throughput.side_effect = _delete
    return client


def _make_mock_s3() -> MagicMock:
    """S3 mock with put_object / delete_object / list_buckets surface."""

    client = MagicMock(name="s3")
    client._objects: dict[tuple[str, str], bytes] = {}
    client._buckets: set[str] = set()

    def _put(Bucket: str, Key: str, Body: bytes = b"", **_kwargs: Any) -> dict[str, Any]:
        client._buckets.add(Bucket)
        client._objects[(Bucket, Key)] = Body
        return {"ResponseMetadata": {"HTTPStatusCode": 200}}

    def _delete(Bucket: str, Key: str, **_kwargs: Any) -> dict[str, Any]:
        client._objects.pop((Bucket, Key), None)
        return {"ResponseMetadata": {"HTTPStatusCode": 204}}

    def _list_buckets(**_kwargs: Any) -> dict[str, Any]:
        return {"Buckets": [{"Name": name} for name in sorted(client._buckets)]}

    def _list_objects(Bucket: str, **_kwargs: Any) -> dict[str, Any]:
        keys = [k for (b, k) in client._objects if b == Bucket]
        return {"Contents": [{"Key": k} for k in keys]}

    client.put_object.side_effect = _put
    client.delete_object.side_effect = _delete
    client.list_buckets.side_effect = _list_buckets
    client.list_objects_v2.side_effect = _list_objects
    return client


def _make_mock_ce() -> MagicMock:
    """Cost Explorer mock that returns a configurable spend total."""

    client = MagicMock(name="ce")
    client._spend_usd = 0.42  # default canary spend < $1

    def _get_cost(**_kwargs: Any) -> dict[str, Any]:
        return {
            "ResultsByTime": [
                {
                    "Total": {
                        "BlendedCost": {"Amount": f"{client._spend_usd:.4f}", "Unit": "USD"},
                        "UnblendedCost": {"Amount": f"{client._spend_usd:.4f}", "Unit": "USD"},
                    }
                }
            ]
        }

    client.get_cost_and_usage.side_effect = _get_cost
    return client


def _make_mock_zero_residual_clients() -> dict[str, MagicMock]:
    """Build mocks for verify_zero_aws teardown probes (all empty)."""

    opensearch = MagicMock(name="opensearch")
    opensearch.list_domain_names.return_value = {"DomainNames": []}

    ec2 = MagicMock(name="ec2")
    ec2.describe_instances.return_value = {"Reservations": []}

    rds = MagicMock(name="rds")
    rds.describe_db_instances.return_value = {"DBInstances": []}

    lambda_client = MagicMock(name="lambda")
    lambda_client.list_functions.return_value = {"Functions": []}

    events = MagicMock(name="events")
    events.list_rules.return_value = {"Rules": []}

    return {
        "opensearch": opensearch,
        "ec2": ec2,
        "rds": rds,
        "lambda": lambda_client,
        "events": events,
    }


# ----------------------------------------------------------------------------
# Canary state machine (pure Python, no AWS)
# ----------------------------------------------------------------------------


class CanaryState:
    """In-memory state for the 7-step canary simulation."""

    def __init__(self) -> None:
        self.run_id = "rc1-p0-bootstrap"
        self.live_aws_unlock_token: str | None = None
        self.teardown_live_token: str | None = None
        self.emergency_token: str | None = None
        self.spend_usd = 0.0
        self.non_credit_exposure_usd = 0.0
        self.cash_bill_guard_enabled = True
        self.cash_bill_guard_fired = False
        self.budget_guards_fired: set[int] = set()
        self.kill_switch_fired = False
        self.aborted = False
        self.abort_reason: str | None = None
        self.steps_completed: list[int] = []

    def fire_budget(self, threshold_usd: int) -> None:
        self.budget_guards_fired.add(threshold_usd)

    def abort(self, reason: str) -> None:
        self.aborted = True
        self.abort_reason = reason


def _cash_bill_guard_check(state: CanaryState) -> None:
    """Simulate cash_bill_guard: fires if spend > $5 (canary mock threshold)."""

    if state.cash_bill_guard_enabled and state.spend_usd > 5.0:
        state.cash_bill_guard_fired = True
        state.abort("cash_bill_guard_fire spend>$5")


def _non_credit_exposure_check(state: CanaryState) -> None:
    """Simulate non-credit exposure: any positive value aborts."""

    if state.non_credit_exposure_usd > 0.0:
        state.abort(f"non_credit_exposure_detected={state.non_credit_exposure_usd}")


def _budget_thresholds_check(state: CanaryState) -> None:
    """Fire 4-tier budget guard at 17K / 18.3K / 18.9K / 19.3K."""

    thresholds = [17000, 18300, 18900, 19300]
    spend = state.spend_usd
    for t in thresholds:
        if spend >= t:
            state.fire_budget(t)


def _emergency_kill_switch(state: CanaryState, mode: str = "both") -> None:
    """Arm kill switch: ``both`` covers AWS + CF rollback per checklist."""

    state.kill_switch_fired = True
    state.emergency_token = "killswitch-uuid-mock"
    state.abort(f"emergency_kill_switch_mode={mode}")


# ----------------------------------------------------------------------------
# Step-level tests (7-step canary sequence)
# ----------------------------------------------------------------------------


@pytest.fixture
def state() -> CanaryState:
    return CanaryState()


def test_canary_step_1_identity_inventory_with_mock_sts(state: CanaryState) -> None:
    """Step 1: STS GetCallerIdentity (mock) returns expected account id."""

    sts = _make_mock_sts()

    identity = sts.get_caller_identity()
    assert identity["Account"] == "993693061769"
    assert identity["Arn"].endswith(":user/bookyou-recovery-preflight")
    sts.get_caller_identity.assert_called_once()

    state.steps_completed.append(1)
    assert not state.aborted


def test_canary_step_2_budget_create_with_mock_budgets(state: CanaryState) -> None:
    """Step 2: 4-budget live create via mock Budgets returns 4 on describe."""

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
            budget={"BudgetName": name, "BudgetLimit": {"Amount": str(limit), "Unit": "USD"}},
        )

    described = budgets.describe_budgets(account_id=account_id)
    assert len(described["Budgets"]) == 4
    names = {b["BudgetName"] for b in described["Budgets"]}
    assert names == {n for n, _ in spec}

    state.steps_completed.append(2)


def test_canary_step_3_smoke_job_submit_with_mock_batch(state: CanaryState) -> None:
    """Step 3: Batch SubmitJob (mock) yields a job in SUBMITTED state."""

    batch = _make_mock_batch()
    resp = batch.submit_job(
        jobName="jpcite-canary-1m",
        jobQueue="jpcite-canary-q",
        jobDefinition="jpcite-canary-1m",
    )
    assert resp["jobId"] == "job-0000"

    described = batch.describe_jobs(jobs=[resp["jobId"]])
    assert described["jobs"][0]["status"] == "SUBMITTED"

    state.spend_usd = 0.42  # canary spend well below $1
    state.steps_completed.append(3)
    assert state.spend_usd < 1.0


def test_canary_step_4_observe_with_mock_ce(state: CanaryState) -> None:
    """Step 4: Cost Explorer (mock) reports spend < $5, cash guard quiet."""

    ce = _make_mock_ce()
    ce._spend_usd = 0.42

    result = ce.get_cost_and_usage(
        TimePeriod={"Start": "2026-05-16", "End": "2026-05-17"},
        Granularity="DAILY",
        Metrics=["BlendedCost"],
    )
    blended = float(result["ResultsByTime"][0]["Total"]["BlendedCost"]["Amount"])
    state.spend_usd = blended
    state.non_credit_exposure_usd = 0.0

    _cash_bill_guard_check(state)
    _non_credit_exposure_check(state)
    assert not state.cash_bill_guard_fired
    assert not state.aborted
    state.steps_completed.append(4)


def test_canary_step_5_threshold_fire_simulation(state: CanaryState) -> None:
    """Step 5: spend reaches 17K then 18.3K -> 2 budget guards fired."""

    state.spend_usd = 17050.0
    _budget_thresholds_check(state)
    assert state.budget_guards_fired == {17000}

    state.spend_usd = 18305.0
    _budget_thresholds_check(state)
    assert state.budget_guards_fired == {17000, 18300}
    state.steps_completed.append(5)


def test_canary_step_5_all_four_thresholds_fire(state: CanaryState) -> None:
    """Step 5b: spend reaches 19.3K -> all 4 budget guards fire."""

    state.spend_usd = 19305.0
    _budget_thresholds_check(state)
    assert state.budget_guards_fired == {17000, 18300, 18900, 19300}


def test_canary_abort_on_cash_bill_guard_fire(state: CanaryState) -> None:
    """Abort trigger T-7: cash_bill_guard false-positive at spend > $5."""

    state.spend_usd = 6.42  # > $5 trips guard
    _cash_bill_guard_check(state)
    assert state.cash_bill_guard_fired
    assert state.aborted
    assert state.abort_reason is not None
    assert "cash_bill_guard_fire" in state.abort_reason


def test_canary_abort_on_spend_over_limit(state: CanaryState) -> None:
    """Abort trigger T-4: spend > $5 also fires cash_bill_guard path."""

    state.spend_usd = 5.01
    _cash_bill_guard_check(state)
    assert state.aborted


def test_canary_abort_on_non_credit_exposure(state: CanaryState) -> None:
    """Abort trigger T-5: any positive non-credit exposure aborts."""

    state.non_credit_exposure_usd = 0.01
    _non_credit_exposure_check(state)
    assert state.aborted
    assert state.abort_reason is not None
    assert "non_credit_exposure_detected" in state.abort_reason


def test_canary_step_6_threshold_behavior_verify(state: CanaryState) -> None:
    """Step 6: verify 4 thresholds are configured + remaining headroom calc."""

    budgets = _make_mock_budgets()
    account_id = "993693061769"
    for name, limit in [
        ("watch", 17000),
        ("slowdown", 18300),
        ("no_new_work", 18900),
        ("absolute_stop", 19300),
    ]:
        budgets.create_budget(
            account_id=account_id,
            budget={"BudgetName": name, "BudgetLimit": {"Amount": str(limit), "Unit": "USD"}},
        )

    assert len(budgets.describe_budgets(account_id=account_id)["Budgets"]) == 4
    target_credit = 19490
    smoke_spend = 0.42
    remaining = target_credit - smoke_spend
    assert remaining == pytest.approx(19489.58)


def test_canary_step_7_teardown_with_mock_cleanup(state: CanaryState) -> None:
    """Step 7: teardown sweep across batch / ecs / bedrock / s3 / budgets."""

    batch = _make_mock_batch()
    ecs = _make_mock_ecs()
    bedrock = _make_mock_bedrock()
    s3 = _make_mock_s3()
    budgets = _make_mock_budgets()

    # arm minimal residual state
    submitted = batch.submit_job(
        jobName="jpcite-canary-1m",
        jobQueue="jpcite-canary-q",
        jobDefinition="jpcite-canary-1m",
    )
    ecs.create_service(cluster="jpcite", serviceName="jpcite-api", desiredCount=2)
    bedrock.create_provisioned_model_throughput(provisionedModelName="jpcite-ocr", modelUnits=1)
    s3.put_object(Bucket="jpcite-canary", Key="rc1/spend.json", Body=b"{}")
    budgets.create_budget(
        account_id="993693061769",
        budget={"BudgetName": "jpcite-watch-17000"},
    )

    # teardown
    batch.terminate_job(jobId=submitted["jobId"], reason="canary teardown")
    ecs.update_service(cluster="jpcite", service="jpcite-api", desiredCount=0)
    bedrock.delete_provisioned_model_throughput(provisionedModelId="jpcite-ocr")
    s3.delete_object(Bucket="jpcite-canary", Key="rc1/spend.json")
    budgets.delete_budget(account_id="993693061769", budget_name="jpcite-watch-17000")

    # verify zero residual on each mock
    assert batch._jobs[submitted["jobId"]]["status"] == "TERMINATED"
    assert ecs._services["jpcite-api"] == 0
    assert bedrock._provisioned == {}
    assert s3._objects == {}
    assert budgets._budgets == {}
    state.steps_completed.append(7)


def test_emergency_kill_switch_both_mode(state: CanaryState) -> None:
    """Kill switch arms in `both` mode (AWS + CF rollback per checklist)."""

    _emergency_kill_switch(state, mode="both")
    assert state.kill_switch_fired
    assert state.emergency_token is not None
    assert state.aborted
    assert state.abort_reason == "emergency_kill_switch_mode=both"


def test_emergency_kill_switch_aws_only_mode(state: CanaryState) -> None:
    """Kill switch arms in `aws_only` mode (Batch + ECS + Bedrock stop)."""

    _emergency_kill_switch(state, mode="aws_only")
    assert state.kill_switch_fired
    assert state.abort_reason == "emergency_kill_switch_mode=aws_only"


def test_verify_zero_aws_post_teardown() -> None:
    """verify_zero_aws.sh equivalent: 8 service probes all empty after teardown."""

    s3 = _make_mock_s3()
    batch = _make_mock_batch()
    ecs = _make_mock_ecs()
    bedrock = _make_mock_bedrock()
    misc = _make_mock_zero_residual_clients()

    # probes
    assert s3.list_buckets()["Buckets"] == []
    assert batch.list_jobs(jobQueue="jpcite-canary-q", jobStatus="RUNNING")["jobSummaryList"] == []
    assert ecs.list_clusters()["clusterArns"] == []
    assert bedrock.list_provisioned_model_throughputs()["provisionedModelSummaries"] == []
    assert misc["opensearch"].list_domain_names()["DomainNames"] == []
    assert misc["ec2"].describe_instances()["Reservations"] == []
    assert misc["rds"].describe_db_instances()["DBInstances"] == []
    assert misc["lambda"].list_functions()["Functions"] == []
    assert misc["events"].list_rules()["Rules"] == []


def test_canary_full_sequence_happy_path(state: CanaryState) -> None:
    """End-to-end happy path: 7 steps complete with no abort."""

    sts = _make_mock_sts()
    budgets = _make_mock_budgets()
    batch = _make_mock_batch()
    ce = _make_mock_ce()
    ecs = _make_mock_ecs()
    bedrock = _make_mock_bedrock()
    s3 = _make_mock_s3()

    # Step 1
    assert sts.get_caller_identity()["Account"] == "993693061769"
    state.live_aws_unlock_token = "unlock-uuid-mock"
    state.teardown_live_token = "teardown-uuid-mock"
    state.steps_completed.append(1)

    # Step 2
    for name, limit in [
        ("watch-17000", 17000),
        ("slowdown-18300", 18300),
        ("no-new-work-18900", 18900),
        ("absolute-19300", 19300),
    ]:
        budgets.create_budget(
            account_id="993693061769",
            budget={"BudgetName": name, "BudgetLimit": {"Amount": str(limit), "Unit": "USD"}},
        )
    assert len(budgets.describe_budgets(account_id="993693061769")["Budgets"]) == 4
    state.steps_completed.append(2)

    # Step 3
    job = batch.submit_job(
        jobName="jpcite-canary-1m",
        jobQueue="jpcite-canary-q",
        jobDefinition="jpcite-canary-1m",
    )
    state.steps_completed.append(3)

    # Step 4
    ce._spend_usd = 0.42
    blended = float(
        ce.get_cost_and_usage(TimePeriod={"Start": "x", "End": "y"}, Granularity="DAILY", Metrics=["BlendedCost"])[
            "ResultsByTime"
        ][0]["Total"]["BlendedCost"]["Amount"]
    )
    state.spend_usd = blended
    _cash_bill_guard_check(state)
    _non_credit_exposure_check(state)
    state.steps_completed.append(4)

    # Step 5
    _budget_thresholds_check(state)
    assert state.budget_guards_fired == set()  # spend $0.42 fires none
    state.steps_completed.append(5)

    # Step 6
    state.steps_completed.append(6)

    # Step 7
    batch.terminate_job(jobId=job["jobId"])
    ecs.update_service(cluster="jpcite", service="jpcite-api", desiredCount=0)
    bedrock.list_provisioned_model_throughputs()
    s3.list_buckets()
    for name, _ in [("watch-17000", 0), ("slowdown-18300", 0), ("no-new-work-18900", 0), ("absolute-19300", 0)]:
        budgets.delete_budget(account_id="993693061769", budget_name=name)
    state.steps_completed.append(7)

    assert state.steps_completed == [1, 2, 3, 4, 5, 6, 7]
    assert not state.aborted
    assert state.spend_usd < 5.0


def test_canary_aborted_sequence_does_not_complete(state: CanaryState) -> None:
    """If cash_bill_guard fires mid-sequence, remaining steps are skipped."""

    state.spend_usd = 5.50
    _cash_bill_guard_check(state)
    assert state.aborted
    # subsequent steps must NOT advance
    if not state.aborted:
        state.steps_completed.append(5)
    assert 5 not in state.steps_completed


def test_mock_clients_record_no_network_io() -> None:
    """All mocks are MagicMock — they never touch a real socket / endpoint."""

    sts = _make_mock_sts()
    budgets = _make_mock_budgets()
    batch = _make_mock_batch()
    ecs = _make_mock_ecs()
    bedrock = _make_mock_bedrock()
    s3 = _make_mock_s3()
    ce = _make_mock_ce()

    for client in (sts, budgets, batch, ecs, bedrock, s3, ce):
        assert isinstance(client, MagicMock)
        # MagicMock does not inherit from any boto3 / botocore base
        assert client.__class__.__name__ == "MagicMock"
