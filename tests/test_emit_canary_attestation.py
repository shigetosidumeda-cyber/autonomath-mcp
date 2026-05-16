"""Unit tests for ``scripts/aws_credit_ops/emit_canary_attestation.py``
and ``infra/aws/lambda/jpcite_credit_canary_attestation.py``.

Mocks Batch + Cost Explorer + S3 with ``unittest.mock.MagicMock`` only —
boto3, botocore, aiohttp, httpx, requests, socket, subprocess, and urllib
are forbidden, mirroring the AST guard pattern used in
``tests/test_emit_burn_metric.py``.

Covers (~16 tests):

1. AST scan: no real-AWS / network imports in this test file.
2. Source module: no top-level ``import boto3`` (lazy import inside
   ``_build_boto3_clients``).
3. ``poll_batch_jobs`` returns canonical rollup by status group.
4. ``poll_batch_jobs`` paginates via ``nextToken``.
5. ``poll_batch_jobs`` client-side prefix re-filter strips foreign jobs.
6. ``poll_cost_explorer`` returns ``(amount, start_iso, end_iso)``.
7. ``poll_cost_explorer`` tolerates malformed CE response shapes.
8. ``_count_objects`` paginates and reports ``sampled`` correctly.
9. ``build_attestation`` composes a canonical envelope shape.
10. ``attestation_filename`` sanitises slashes and colons.
11. ``write_attestation`` dry-run does not touch the filesystem.
12. ``write_attestation`` commit path writes a UTF-8 JSON file.
13. ``upload_attestation`` dry-run does not call ``put_object``.
14. ``upload_attestation`` live path calls ``put_object`` with tagging.
15. Lambda handler returns an envelope with the expected top-level keys.
16. Lambda handler short-circuits cleanly when boto3 calls raise.
"""

from __future__ import annotations

import ast
import datetime as dt
import importlib.util
import json
import sys
import types
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

# ----------------------------------------------------------------------------
# Module loaders — both source files live outside the default import path.
# ----------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[1]
_EMIT_PATH = _REPO_ROOT / "scripts" / "aws_credit_ops" / "emit_canary_attestation.py"
_LAMBDA_PATH = _REPO_ROOT / "infra" / "aws" / "lambda" / "jpcite_credit_canary_attestation.py"
_THIS_FILE = Path(__file__).resolve()


def _load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


emit_mod = _load_module("emit_canary_attestation_under_test", _EMIT_PATH)


# ----------------------------------------------------------------------------
# Test 1: AST guard — no boto3 / network imports in this file.
# ----------------------------------------------------------------------------


def test_no_real_aws_or_network_imports_in_attestation_tests() -> None:
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
                assert root not in forbidden_imports, alias.name
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                root = node.module.split(".")[0]
                assert root not in forbidden_imports, node.module
        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
                pair = (func.value.id, func.attr)
                assert pair not in forbidden_attr_calls, pair


# ----------------------------------------------------------------------------
# Test 2: emit_canary_attestation.py must not top-level-import boto3.
# ----------------------------------------------------------------------------


def test_emit_module_does_not_top_level_import_boto3() -> None:
    source = _EMIT_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    top_level_boto3 = False
    for node in tree.body:
        if isinstance(node, ast.Import):
            top_level_boto3 = top_level_boto3 or any(a.name.startswith("boto3") for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("boto3"):
            top_level_boto3 = True
    assert not top_level_boto3, "boto3 must be imported lazily inside _build_boto3_clients"


# ----------------------------------------------------------------------------
# Test 3-5: poll_batch_jobs rollup + pagination + prefix re-filter.
# ----------------------------------------------------------------------------


def test_poll_batch_jobs_rollup_by_status_group() -> None:
    client = MagicMock(name="batch")

    def fake_list_jobs(**kwargs: Any) -> dict[str, Any]:
        status = kwargs["jobStatus"]
        if status == "SUCCEEDED":
            return {
                "jobSummaryList": [
                    {"jobName": "jpcite-credit-J01"},
                    {"jobName": "jpcite-credit-J02"},
                    {"jobName": "jpcite-credit-J03"},
                ],
                "nextToken": None,
            }
        if status == "FAILED":
            return {
                "jobSummaryList": [{"jobName": "jpcite-credit-J04"}],
                "nextToken": None,
            }
        if status == "RUNNING":
            return {
                "jobSummaryList": [
                    {"jobName": "jpcite-credit-J05"},
                    {"jobName": "jpcite-credit-J06"},
                ],
                "nextToken": None,
            }
        return {"jobSummaryList": [], "nextToken": None}

    client.list_jobs.side_effect = fake_list_jobs
    rollup = emit_mod.poll_batch_jobs(client, job_queue="q", job_name_prefix="jpcite-credit-")
    assert rollup.succeeded == 3
    assert rollup.failed == 1
    assert rollup.running == 2
    assert rollup.by_status["SUCCEEDED"] == 3
    assert rollup.by_status["FAILED"] == 1
    assert rollup.by_status["RUNNING"] == 2


def test_poll_batch_jobs_paginates_via_nexttoken() -> None:
    client = MagicMock(name="batch")
    calls: list[dict[str, Any]] = []

    def fake_list_jobs(**kwargs: Any) -> dict[str, Any]:
        calls.append(dict(kwargs))
        status = kwargs["jobStatus"]
        token = kwargs.get("nextToken")
        if status == "SUCCEEDED" and token is None:
            return {
                "jobSummaryList": [{"jobName": "jpcite-credit-A"}],
                "nextToken": "TOK1",
            }
        if status == "SUCCEEDED" and token == "TOK1":
            return {
                "jobSummaryList": [{"jobName": "jpcite-credit-B"}],
                "nextToken": None,
            }
        return {"jobSummaryList": [], "nextToken": None}

    client.list_jobs.side_effect = fake_list_jobs
    rollup = emit_mod.poll_batch_jobs(client, job_queue="q")
    assert rollup.succeeded == 2
    # Pagination produced at least 2 calls for SUCCEEDED.
    succ_calls = [c for c in calls if c["jobStatus"] == "SUCCEEDED"]
    assert len(succ_calls) >= 2


def test_poll_batch_jobs_client_side_prefix_refilter() -> None:
    client = MagicMock(name="batch")
    client.list_jobs.return_value = {
        "jobSummaryList": [
            {"jobName": "jpcite-credit-J01"},
            {"jobName": "OTHER-account-job"},  # foreign prefix — must drop.
            {"jobName": "jpcite-credit-J02"},
        ],
        "nextToken": None,
    }
    rollup = emit_mod.poll_batch_jobs(client, job_queue="q", job_name_prefix="jpcite-credit-")
    # Only the 2 jpcite-credit-* count, regardless of status group.
    total = sum(rollup.by_status.values())
    assert total == len(emit_mod.BATCH_JOB_STATUSES) * 2


# ----------------------------------------------------------------------------
# Test 6-7: poll_cost_explorer happy path + malformed-response tolerance.
# ----------------------------------------------------------------------------


def test_poll_cost_explorer_returns_amount_and_window() -> None:
    client = MagicMock(name="ce")
    client.get_cost_and_usage.return_value = {
        "ResultsByTime": [
            {"Total": {"UnblendedCost": {"Amount": "123.45", "Unit": "USD"}}},
        ]
    }
    now = dt.datetime(2026, 5, 16, 12, 0, 0, tzinfo=dt.UTC)
    amount, start, end = emit_mod.poll_cost_explorer(client, now=now)
    assert amount == pytest.approx(123.45)
    assert start == "2026-05-01"
    assert end == "2026-05-17"


def test_poll_cost_explorer_tolerates_malformed_shapes() -> None:
    client = MagicMock(name="ce")
    client.get_cost_and_usage.return_value = {"ResultsByTime": []}
    now = dt.datetime(2026, 5, 16, 12, 0, 0, tzinfo=dt.UTC)
    amount, _, _ = emit_mod.poll_cost_explorer(client, now=now)
    assert amount == 0.0


# ----------------------------------------------------------------------------
# Test 8: _count_objects pagination + sampled flag.
# ----------------------------------------------------------------------------


def test_count_objects_paginates_and_reports_sampled() -> None:
    client = MagicMock(name="s3")
    pages: list[dict[str, Any]] = [
        {"KeyCount": 1000, "IsTruncated": True, "NextContinuationToken": "T1"},
        {"KeyCount": 1000, "IsTruncated": True, "NextContinuationToken": "T2"},
        {"KeyCount": 250, "IsTruncated": False},
    ]
    client.list_objects_v2.side_effect = pages
    total, sampled = emit_mod._count_objects(client, bucket="b")
    assert total == 2250
    assert sampled is False


def test_count_objects_caps_at_max_pages_and_returns_sampled_true() -> None:
    client = MagicMock(name="s3")

    def make_page(i: int) -> dict[str, Any]:
        return {
            "KeyCount": 1000,
            "IsTruncated": True,
            "NextContinuationToken": f"T{i}",
        }

    client.list_objects_v2.side_effect = [make_page(i) for i in range(80)]
    total, sampled = emit_mod._count_objects(client, bucket="b", max_pages=3)
    assert sampled is True
    assert total >= 3000


# ----------------------------------------------------------------------------
# Test 9-10: build_attestation envelope + filename sanitisation.
# ----------------------------------------------------------------------------


def test_build_attestation_canonical_envelope() -> None:
    jobs = emit_mod.BatchJobsRollup(
        succeeded=10, failed=1, running=2, by_status={"SUCCEEDED": 10, "FAILED": 1, "RUNNING": 2}
    )
    artifacts = emit_mod.ArtifactCounts(
        raw_objects=42,
        derived_objects=7,
        raw_bucket="raw",
        derived_bucket="der",
        sampled=False,
    )
    started_at = dt.datetime(2026, 5, 16, 11, 30, 0, tzinfo=dt.UTC)
    now = dt.datetime(2026, 5, 16, 12, 0, 0, tzinfo=dt.UTC)
    att = emit_mod.build_attestation(
        run_id="canary-20260516T120000Z",
        started_at=started_at,
        jobs=jobs,
        cost=(1860.0, "2026-05-01", "2026-05-17"),
        artifacts=artifacts,
        now=now,
        current_status="IN_PROGRESS",
        live_aws_commands_executed=False,
    )
    payload = json.loads(att.to_json())
    assert payload["schema_version"] == emit_mod.SCHEMA_VERSION
    assert payload["run_id"] == "canary-20260516T120000Z"
    assert payload["started_at"] == "2026-05-16T11:30:00+00:00"
    assert payload["emitted_at"] == "2026-05-16T12:00:00+00:00"
    assert payload["current_status"] == "IN_PROGRESS"
    assert payload["jobs"]["succeeded"] == 10
    assert payload["jobs"]["failed"] == 1
    assert payload["jobs"]["running"] == 2
    assert payload["cost_consumed_usd"] == pytest.approx(1860.0)
    assert payload["live_aws_commands_executed"] is False


def test_attestation_filename_sanitises_unsafe_chars() -> None:
    assert (
        emit_mod.attestation_filename("canary/2026/05/16:abc")
        == "aws_canary_attestation_canary_2026_05_16_abc.json"
    )
    assert (
        emit_mod.attestation_filename("plain-id")
        == "aws_canary_attestation_plain-id.json"
    )


# ----------------------------------------------------------------------------
# Test 11-12: write_attestation dry-run vs commit.
# ----------------------------------------------------------------------------


def _stub_attestation(run_id: str = "canary-X") -> Any:
    return emit_mod.build_attestation(
        run_id=run_id,
        started_at=dt.datetime(2026, 5, 16, 11, 30, 0, tzinfo=dt.UTC),
        jobs=emit_mod.BatchJobsRollup.empty(),
        cost=(0.0, "2026-05-01", "2026-05-17"),
        artifacts=emit_mod.ArtifactCounts(
            raw_objects=0,
            derived_objects=0,
            raw_bucket="r",
            derived_bucket="d",
            sampled=False,
        ),
        now=dt.datetime(2026, 5, 16, 12, 0, 0, tzinfo=dt.UTC),
    )


def test_write_attestation_dry_run_does_not_touch_filesystem(tmp_path: Path) -> None:
    att = _stub_attestation()
    out = tmp_path / "nowhere"
    target = emit_mod.write_attestation(att, output_dir=out, commit=False)
    assert not out.exists()
    assert target.name.startswith("aws_canary_attestation_")


def test_write_attestation_commit_writes_utf8_json(tmp_path: Path) -> None:
    att = _stub_attestation()
    target = emit_mod.write_attestation(att, output_dir=tmp_path, commit=True)
    assert target.exists()
    raw = target.read_text(encoding="utf-8")
    parsed = json.loads(raw)
    assert parsed["schema_version"] == emit_mod.SCHEMA_VERSION


# ----------------------------------------------------------------------------
# Test 13-14: upload_attestation dry-run vs live.
# ----------------------------------------------------------------------------


def test_upload_attestation_dry_run_does_not_call_put_object() -> None:
    att = _stub_attestation()
    client = MagicMock(name="s3")
    log = emit_mod.upload_attestation(att, s3_client=client, bucket="b", live=False)
    client.put_object.assert_not_called()
    assert log["live"] is False
    assert log["bucket"] == "b"


def test_upload_attestation_live_calls_put_object_with_tagging() -> None:
    att = _stub_attestation()
    client = MagicMock(name="s3")
    log = emit_mod.upload_attestation(att, s3_client=client, bucket="reports", live=True)
    client.put_object.assert_called_once()
    kwargs = client.put_object.call_args.kwargs
    assert kwargs["Bucket"] == "reports"
    assert kwargs["Key"].startswith("attestations/aws_canary_attestation_")
    assert kwargs["ContentType"] == "application/json"
    assert "Project=jpcite" in kwargs["Tagging"]
    assert log["live"] is True


# ----------------------------------------------------------------------------
# Test 15-16: Lambda handler envelope + boto3 failure tolerance.
# ----------------------------------------------------------------------------


def _install_synthetic_boto3() -> None:
    """Provide a fake ``boto3`` module so ``lambda_function.py`` imports it."""

    if "boto3" in sys.modules:
        return
    fake = types.ModuleType("boto3")

    def fake_client(name: str, *_: Any, **__: Any) -> MagicMock:
        return MagicMock(name=f"boto3.client[{name}]")

    fake.client = fake_client  # type: ignore[attr-defined]
    sys.modules["boto3"] = fake


def _load_lambda_module(monkeypatch: pytest.MonkeyPatch) -> Any:
    _install_synthetic_boto3()
    # Ensure the emit_canary_attestation module is importable by name from the
    # lambda module's sys.path bootstrap.
    monkeypatch.syspath_prepend(str(_EMIT_PATH.parent))
    sys.modules["emit_canary_attestation"] = emit_mod
    monkeypatch.setenv("AWS_REGION", "ap-northeast-1")
    monkeypatch.setenv("JPCITE_CANARY_ATTESTATION_ENABLED", "false")
    monkeypatch.setenv("JPCITE_CANARY_LIVE_UPLOAD", "false")
    return _load_module("jpcite_credit_canary_attestation_under_test", _LAMBDA_PATH)


def test_lambda_handler_returns_canonical_envelope(monkeypatch: pytest.MonkeyPatch) -> None:
    mod = _load_lambda_module(monkeypatch)
    # Patch out the read-only AWS pollers so we exercise the handler path
    # without depending on the synthetic boto3 client surface.
    monkeypatch.setattr(
        emit_mod,
        "poll_batch_jobs",
        lambda *_args, **_kwargs: emit_mod.BatchJobsRollup(
            succeeded=2, failed=0, running=1, by_status={"SUCCEEDED": 2, "RUNNING": 1}
        ),
    )
    monkeypatch.setattr(
        emit_mod,
        "poll_cost_explorer",
        lambda *_args, **_kwargs: (12.34, "2026-05-01", "2026-05-17"),
    )
    monkeypatch.setattr(
        emit_mod,
        "poll_artifact_counts",
        lambda *_args, **_kwargs: emit_mod.ArtifactCounts(
            raw_objects=5,
            derived_objects=1,
            raw_bucket="r",
            derived_bucket="d",
            sampled=False,
        ),
    )

    payload = mod.lambda_handler(
        {"run_id": "canary-smoke-001", "current_status": "IN_PROGRESS"},
        context=None,
    )
    assert payload["lambda"] == "jpcite-credit-canary-attestation-emitter"
    assert payload["mode"] == "dry_run"
    assert payload["run_id"] == "canary-smoke-001"
    assert payload["succeeded"] == 2
    assert payload["failed"] == 0
    assert payload["running"] == 1
    assert payload["cost_usd"] == pytest.approx(12.34)
    assert payload["raw_objects"] == 5
    assert payload["derived_objects"] == 1
    assert payload["upload_action"]["live"] is False
    assert payload["safety_env"]["JPCITE_CANARY_ATTESTATION_ENABLED"] == "false"
    assert payload["safety_env"]["JPCITE_CANARY_LIVE_UPLOAD"] == "false"


def test_lambda_handler_recovers_from_poller_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    mod = _load_lambda_module(monkeypatch)

    def boom(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("simulated AWS failure")

    monkeypatch.setattr(emit_mod, "poll_batch_jobs", boom)
    monkeypatch.setattr(emit_mod, "poll_cost_explorer", boom)
    monkeypatch.setattr(emit_mod, "poll_artifact_counts", boom)

    payload = mod.lambda_handler({}, context=None)
    # Empty rollup + zero cost + zero artifacts when all pollers fail.
    assert payload["succeeded"] == 0
    assert payload["failed"] == 0
    assert payload["running"] == 0
    assert payload["cost_usd"] == 0.0
    assert payload["raw_objects"] == 0
    assert payload["derived_objects"] == 0
    assert payload["mode"] == "dry_run"
