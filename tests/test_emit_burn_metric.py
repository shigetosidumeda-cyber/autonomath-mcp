"""Unit tests for ``scripts/aws_credit_ops/emit_burn_metric.py``.

Mocks Cost Explorer + CloudWatch + SNS with ``unittest.mock.MagicMock``
only — boto3, botocore, aiohttp, httpx, requests, socket, subprocess,
and urllib are forbidden, mirroring the AST guard used in
``tests/test_aws_canary_smoke_mock.py`` + ``tests/test_aws_execution_templates.py``.

Covers (~10 tests):

1. AST scan: no real-AWS / network imports in this test file.
2. Module import works without ``boto3`` being importable at module load.
3. ``_month_window`` returns ``(start, end, hours_elapsed)`` correctly.
4. ``_classify`` RAMP/SLOWDOWN/STOP threshold behaviour.
5. ``_classify`` hourly-stop override even when ratio is RAMP.
6. ``_parse_ce_response`` tolerates empty / malformed CE responses.
7. ``build_emission`` end-to-end on a low-spend RAMP envelope.
8. ``build_emission`` end-to-end on a high-spend STOP envelope.
9. ``emit`` dry-run does not call ``put_metric_data`` / ``publish``.
10. ``emit`` live path calls both ``put_metric_data`` and ``publish``.
11. ``emit`` skips SNS publish when no breach + no topic.
12. Lambda env defaults — ``_enabled`` is False without explicit opt-in.
"""

from __future__ import annotations

import ast
import datetime as dt
import importlib.util
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

# ----------------------------------------------------------------------------
# Module loader — emit_burn_metric.py lives under scripts/aws_credit_ops/
# which isn't on the default import path. Load it explicitly so the test
# file stays decoupled from any future package wrapper.
# ----------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT_PATH = _REPO_ROOT / "scripts" / "aws_credit_ops" / "emit_burn_metric.py"
_THIS_FILE = Path(__file__).resolve()


def _load_emit_module() -> Any:
    spec = importlib.util.spec_from_file_location("emit_burn_metric_under_test", _SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


emit_burn_metric = _load_emit_module()


# ----------------------------------------------------------------------------
# Test 1: AST guard — no boto3 / network imports in this file.
# ----------------------------------------------------------------------------


def test_no_real_aws_or_network_imports_in_burn_metric_tests() -> None:
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
# Test 2: module imports cleanly even when boto3 is not importable yet.
# ----------------------------------------------------------------------------


def test_module_imports_without_boto3() -> None:
    # The module under test must not have a top-level ``import boto3`` that
    # would crash in a no-boto3 environment. boto3 is only imported inside
    # ``_build_boto3_clients`` at runtime.
    source = _SCRIPT_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    top_level_boto3 = False
    for node in tree.body:
        if isinstance(node, ast.Import):
            top_level_boto3 = top_level_boto3 or any(a.name.startswith("boto3") for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("boto3"):
            top_level_boto3 = True
    assert not top_level_boto3, "boto3 must be imported lazily inside _build_boto3_clients"


# ----------------------------------------------------------------------------
# Test 3: _month_window math
# ----------------------------------------------------------------------------


def test_month_window_returns_canonical_iso_dates_and_hours_elapsed() -> None:
    # Fix the clock to 2026-05-16 12:00 UTC — 15.5 days into May.
    now = dt.datetime(2026, 5, 16, 12, 0, 0, tzinfo=dt.UTC)
    start, end, hours = emit_burn_metric._month_window(now)
    assert start == "2026-05-01"
    assert end == "2026-05-17"
    # 15 days × 24 + 12 = 372 hours
    assert hours == pytest.approx(372.0, abs=0.1)


def test_month_window_handles_naive_datetime() -> None:
    naive = dt.datetime(2026, 5, 1, 0, 30, 0)  # 30 minutes into May
    start, end, hours = emit_burn_metric._month_window(naive)
    assert start == "2026-05-01"
    assert end == "2026-05-02"
    assert hours == pytest.approx(0.5, abs=0.01)


# ----------------------------------------------------------------------------
# Test 4-5: _classify thresholds
# ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("consumed", "target", "hourly", "hourly_stop", "expected"),
    [
        (1000.0, 18300.0, 10.0, 500.0, "RAMP"),          # 5% — RAMP
        (15555.0, 18300.0, 10.0, 500.0, "SLOWDOWN"),     # 85% — SLOWDOWN
        (17385.0, 18300.0, 10.0, 500.0, "STOP"),         # 95% — STOP
        (100.0, 18300.0, 600.0, 500.0, "STOP"),          # hourly stop override
        (0.0, 18300.0, 0.0, 500.0, "RAMP"),              # cold start
    ],
)
def test_classify_thresholds(
    consumed: float, target: float, hourly: float, hourly_stop: float, expected: str
) -> None:
    assert emit_burn_metric._classify(consumed, target, hourly, hourly_stop) == expected


def test_classify_zero_target_consumed_returns_stop() -> None:
    # Defensive: target=0 must not divide-by-zero; positive consumed => STOP.
    assert emit_burn_metric._classify(100.0, 0.0, 0.0, 500.0) == "STOP"
    assert emit_burn_metric._classify(0.0, 0.0, 0.0, 500.0) == "RAMP"


# ----------------------------------------------------------------------------
# Test 6: _parse_ce_response tolerates malformed shapes
# ----------------------------------------------------------------------------


def test_parse_ce_response_handles_malformed_shapes() -> None:
    parse = emit_burn_metric._parse_ce_response
    assert parse({}) == 0.0
    assert parse({"ResultsByTime": []}) == 0.0
    assert parse({"ResultsByTime": [{"Total": {}}]}) == 0.0
    assert parse({"ResultsByTime": [{"Total": {"UnblendedCost": {}}}]}) == 0.0
    # Float as string is the canonical CE format.
    canonical = {
        "ResultsByTime": [{"Total": {"UnblendedCost": {"Amount": "1234.5678", "Unit": "USD"}}}]
    }
    assert parse(canonical) == pytest.approx(1234.5678)
    # BlendedCost fallback when UnblendedCost is missing.
    blended_only = {"ResultsByTime": [{"Total": {"BlendedCost": {"Amount": "42.0"}}}]}
    assert parse(blended_only) == pytest.approx(42.0)


# ----------------------------------------------------------------------------
# Test 7-8: build_emission end-to-end on RAMP + STOP envelopes
# ----------------------------------------------------------------------------


def _mock_ce(amount: str) -> MagicMock:
    client = MagicMock(name="ce")
    client.get_cost_and_usage.return_value = {
        "ResultsByTime": [
            {
                "Total": {"UnblendedCost": {"Amount": amount, "Unit": "USD"}},
                "TimePeriod": {"Start": "2026-05-01", "End": "2026-05-17"},
            }
        ]
    }
    return client


def test_build_emission_ramp_envelope() -> None:
    now = dt.datetime(2026, 5, 16, 12, 0, 0, tzinfo=dt.UTC)  # 372 h into month
    ce = _mock_ce("1860.0")  # 372 h × 5 USD/hr  → exactly $5/hr RAMP
    emission = emit_burn_metric.build_emission(ce, now=now, target_usd=18300.0)

    assert emission.consumed_usd == pytest.approx(1860.0)
    assert emission.target_usd == 18300.0
    assert emission.remaining_usd == pytest.approx(16440.0)
    assert emission.hours_elapsed == pytest.approx(372.0, abs=0.1)
    assert emission.hourly_burn_usd == pytest.approx(5.0, abs=0.01)
    assert emission.classification == "RAMP"
    assert emission.breached_hourly_alert is False
    assert emission.breached_hourly_stop is False
    # CE call shape verified
    ce.get_cost_and_usage.assert_called_once_with(
        TimePeriod={"Start": "2026-05-01", "End": "2026-05-17"},
        Granularity="MONTHLY",
        Metrics=["UnblendedCost"],
    )


def test_build_emission_stop_envelope_via_hourly_burn() -> None:
    now = dt.datetime(2026, 5, 16, 12, 0, 0, tzinfo=dt.UTC)  # 372 h
    # 372 h × 600 USD/hr  = 223,200  — well above the $500/hr STOP line
    ce = _mock_ce("223200.0")
    emission = emit_burn_metric.build_emission(
        ce, now=now, target_usd=18300.0, hourly_stop_usd=500.0
    )
    assert emission.classification == "STOP"
    assert emission.breached_hourly_alert is True
    assert emission.breached_hourly_stop is True
    # Metric payloads carry the Classification dimension
    payloads = emission.metric_payloads()
    assert {p["MetricName"] for p in payloads} == {"GrossSpendUSD", "HourlyBurnRate"}
    for p in payloads:
        assert p["Dimensions"] == [{"Name": "Classification", "Value": "STOP"}]


# ----------------------------------------------------------------------------
# Test 9-11: emit() dry-run vs live, SNS-on-breach
# ----------------------------------------------------------------------------


def _make_emission(
    *,
    classification: str = "RAMP",
    breached_alert: bool = False,
    namespace: str = "jpcite/credit",
) -> Any:
    return emit_burn_metric.BurnEmission(
        consumed_usd=1860.0,
        target_usd=18300.0,
        remaining_usd=16440.0,
        hours_elapsed=372.0,
        hourly_burn_usd=5.0,
        hourly_stop_usd=500.0,
        hourly_alert_usd=500.0,
        classification=classification,
        breached_hourly_alert=breached_alert,
        breached_hourly_stop=breached_alert,
        namespace=namespace,
        metric_region="ap-northeast-1",
        ce_region="us-east-1",
        timestamp="2026-05-16T12:00:00+00:00",
        period_start="2026-05-01",
        period_end="2026-05-17",
    )


def test_emit_dry_run_does_not_call_aws() -> None:
    cw = MagicMock(name="cloudwatch")
    sns = MagicMock(name="sns")
    emission = _make_emission(breached_alert=True)  # would breach but live=False
    result = emit_burn_metric.emit(
        emission,
        cw_client=cw,
        sns_client=sns,
        sns_topic_arn="arn:aws:sns:us-east-1:993693061769:jpcite-credit-cost-alerts",
        live=False,
    )
    assert cw.put_metric_data.call_count == 0
    assert sns.publish.call_count == 0
    assert result["live"] is False
    assert any(a["action"] == "put_metric_data" and a["live"] is False for a in result["actions"])
    assert any(a["action"] == "sns_publish" and a["live"] is False for a in result["actions"])


def test_emit_live_calls_put_metric_data_and_sns_publish_on_breach() -> None:
    cw = MagicMock(name="cloudwatch")
    sns = MagicMock(name="sns")
    emission = _make_emission(classification="STOP", breached_alert=True)
    result = emit_burn_metric.emit(
        emission,
        cw_client=cw,
        sns_client=sns,
        sns_topic_arn="arn:aws:sns:us-east-1:993693061769:jpcite-credit-cost-alerts",
        live=True,
    )
    cw.put_metric_data.assert_called_once()
    call_kwargs = cw.put_metric_data.call_args.kwargs
    assert call_kwargs["Namespace"] == "jpcite/credit"
    assert len(call_kwargs["MetricData"]) == 2
    sns.publish.assert_called_once()
    sns_kwargs = sns.publish.call_args.kwargs
    assert sns_kwargs["TopicArn"].endswith(":jpcite-credit-cost-alerts")
    assert sns_kwargs["Subject"] == "jpcite-credit-burn-metric alert"
    assert "hourly_burn_usd" in sns_kwargs["Message"]
    assert result["live"] is True


def test_emit_live_skips_sns_when_no_breach() -> None:
    cw = MagicMock(name="cloudwatch")
    sns = MagicMock(name="sns")
    emission = _make_emission(classification="RAMP", breached_alert=False)
    result = emit_burn_metric.emit(
        emission,
        cw_client=cw,
        sns_client=sns,
        sns_topic_arn="arn:aws:sns:us-east-1:993693061769:jpcite-credit-cost-alerts",
        live=True,
    )
    cw.put_metric_data.assert_called_once()
    assert sns.publish.call_count == 0
    assert not any(a["action"] == "sns_publish" for a in result["actions"])


# ----------------------------------------------------------------------------
# Test 12: env-gate default — _enabled is False without explicit opt-in
# ----------------------------------------------------------------------------


def test_enabled_defaults_to_false(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("JPCITE_BURN_METRIC_ENABLED", raising=False)
    assert emit_burn_metric._enabled() is False
    monkeypatch.setenv("JPCITE_BURN_METRIC_ENABLED", "false")
    assert emit_burn_metric._enabled() is False
    monkeypatch.setenv("JPCITE_BURN_METRIC_ENABLED", "FALSE")
    assert emit_burn_metric._enabled() is False
    monkeypatch.setenv("JPCITE_BURN_METRIC_ENABLED", "yes")
    assert emit_burn_metric._enabled() is False
    monkeypatch.setenv("JPCITE_BURN_METRIC_ENABLED", "true")
    assert emit_burn_metric._enabled() is True
    monkeypatch.setenv("JPCITE_BURN_METRIC_ENABLED", "TRUE")
    assert emit_burn_metric._enabled() is True


def test_env_float_falls_back_on_invalid_input(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JPCITE_TEST_FLOAT", "not-a-number")
    assert emit_burn_metric._env_float("JPCITE_TEST_FLOAT", 42.0) == 42.0
    monkeypatch.setenv("JPCITE_TEST_FLOAT", "3.14")
    assert emit_burn_metric._env_float("JPCITE_TEST_FLOAT", 42.0) == pytest.approx(3.14)
    monkeypatch.delenv("JPCITE_TEST_FLOAT", raising=False)
    assert emit_burn_metric._env_float("JPCITE_TEST_FLOAT", 42.0) == 42.0
