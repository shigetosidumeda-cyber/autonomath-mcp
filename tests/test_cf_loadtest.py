"""Unit tests for ``scripts/aws_credit_ops/cf_loadtest_runner.py``.

AST scan forbids boto3 / botocore / aiohttp / httpx / requests / urllib
imports in this test file so the suite stays offline + deterministic
(mirrors ``tests/test_emit_burn_metric.py``).

Covers ~12 tests:

1. AST scan: no real-AWS / network imports in this test file.
2. Module loads without boto3.
3. ``project_transfer_cost`` returns expected envelope.
4. ``project_transfer_cost`` clamps negative inputs to zero.
5. ``sample_keys`` is deterministic given a seed.
6. ``sample_keys`` on empty corpus returns empty list.
7. ``build_urls`` joins domain + key correctly + strips leading slash.
8. ``build_urls`` rejects empty distribution domain.
9. ``load_manifest_keys`` reads newline-delimited file.
10. ``load_manifest_keys`` reads JSON-list file.
11. ``classify`` returns DRY_RUN / BLOCKED_FLAG / BLOCKED_BUDGET / LIVE.
12. ``build_envelope`` produces stable schema version.
13. ``main`` exits 0 with DRY_RUN envelope on stdout (no HTTP).
"""

from __future__ import annotations

import ast
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT_PATH = _REPO_ROOT / "scripts" / "aws_credit_ops" / "cf_loadtest_runner.py"
_THIS_FILE = Path(__file__).resolve()


def _load_module() -> Any:
    spec = importlib.util.spec_from_file_location("cf_loadtest_runner_under_test", _SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


cf_loadtest_runner = _load_module()


# Test 1 ----------------------------------------------------------------------


def test_ast_no_real_aws_or_network_imports() -> None:
    """Forbid boto3 / aiohttp / httpx / requests / urllib in this test file."""

    src = _THIS_FILE.read_text(encoding="utf-8")
    tree = ast.parse(src)
    banned = {"boto3", "botocore", "aiohttp", "httpx", "requests", "urllib"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                assert root not in banned, f"banned import: {alias.name}"
        elif isinstance(node, ast.ImportFrom):
            mod = (node.module or "").split(".")[0]
            assert mod not in banned, f"banned from import: {node.module}"


# Test 2 ----------------------------------------------------------------------


def test_module_loads() -> None:
    assert hasattr(cf_loadtest_runner, "project_transfer_cost")
    assert hasattr(cf_loadtest_runner, "sample_keys")
    assert hasattr(cf_loadtest_runner, "build_urls")
    assert hasattr(cf_loadtest_runner, "classify")
    assert hasattr(cf_loadtest_runner, "build_envelope")
    assert cf_loadtest_runner.SCHEMA_VERSION == "jpcite.cf_loadtest_envelope.v1"


# Test 3 ----------------------------------------------------------------------


def test_project_transfer_cost_basic() -> None:
    p = cf_loadtest_runner.project_transfer_cost(10_000, 2_000)
    assert p["requests"] == 10_000.0
    assert p["avg_object_bytes"] == 2_000.0
    assert p["total_bytes"] == 10_000 * 2_000
    # 20 MB = 0.0186264... GiB → ~0.00212 USD transfer at 0.114 USD/GiB.
    assert 0.001 < p["transfer_usd"] < 0.005
    # 10_000 req at 0.012 USD / 10k = 0.012 USD.
    assert abs(p["request_usd"] - 0.012) < 1e-9
    assert p["total_usd"] == round(p["transfer_usd"] + p["request_usd"], 6)


# Test 4 ----------------------------------------------------------------------


def test_project_transfer_cost_clamps_negative() -> None:
    p = cf_loadtest_runner.project_transfer_cost(-5, -100)
    assert p["requests"] == 0.0
    assert p["avg_object_bytes"] == 0.0
    assert p["total_bytes"] == 0.0
    assert p["transfer_usd"] == 0.0
    assert p["request_usd"] == 0.0
    assert p["total_usd"] == 0.0


# Test 5 ----------------------------------------------------------------------


def test_sample_keys_deterministic() -> None:
    keys = ["a", "b", "c", "d", "e"]
    s1 = cf_loadtest_runner.sample_keys(keys, 50, seed=42)
    s2 = cf_loadtest_runner.sample_keys(keys, 50, seed=42)
    assert s1 == s2
    assert len(s1) == 50
    s3 = cf_loadtest_runner.sample_keys(keys, 50, seed=43)
    assert s1 != s3


# Test 6 ----------------------------------------------------------------------


def test_sample_keys_empty_corpus() -> None:
    assert cf_loadtest_runner.sample_keys([], 100) == []


# Test 7 ----------------------------------------------------------------------


def test_build_urls_joins_correctly() -> None:
    urls = cf_loadtest_runner.build_urls("d1234.cloudfront.net", ["a/b.json", "/c/d.json"])
    assert urls == [
        "https://d1234.cloudfront.net/a/b.json",
        "https://d1234.cloudfront.net/c/d.json",
    ]


# Test 8 ----------------------------------------------------------------------


def test_build_urls_rejects_empty_domain() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        cf_loadtest_runner.build_urls("", ["x"])


# Test 9 ----------------------------------------------------------------------


def test_load_manifest_keys_newline(tmp_path: Path) -> None:
    p = tmp_path / "keys.txt"
    p.write_text("a/b.json\n c/d.json \n\ne/f.json\n", encoding="utf-8")
    assert cf_loadtest_runner.load_manifest_keys(p) == ["a/b.json", "c/d.json", "e/f.json"]


# Test 10 ---------------------------------------------------------------------


def test_load_manifest_keys_json(tmp_path: Path) -> None:
    p = tmp_path / "keys.json"
    p.write_text(json.dumps(["a/b.json", "c/d.json"]), encoding="utf-8")
    assert cf_loadtest_runner.load_manifest_keys(p) == ["a/b.json", "c/d.json"]


# Test 11 ---------------------------------------------------------------------


def test_classify_states() -> None:
    plan = cf_loadtest_runner.LoadTestPlan(
        distribution_domain="d.example.cloudfront.net",
        requests=10_000,
        concurrency=64,
        avg_object_bytes=2_000,
        manifest_path="/tmp/missing",
        seed=0,
        budget_usd=100.0,
        commit=False,
        unlock_live=False,
    )
    proj = cf_loadtest_runner.project_transfer_cost(10_000, 2_000)
    assert cf_loadtest_runner.classify(plan, proj) == "DRY_RUN"

    plan_commit = cf_loadtest_runner.dataclasses.replace(plan, commit=True, unlock_live=False)
    assert cf_loadtest_runner.classify(plan_commit, proj) == "BLOCKED_FLAG"

    plan_live = cf_loadtest_runner.dataclasses.replace(plan, commit=True, unlock_live=True)
    assert cf_loadtest_runner.classify(plan_live, proj) == "LIVE"

    proj_huge = cf_loadtest_runner.project_transfer_cost(10_000_000_000, 2_000)
    assert cf_loadtest_runner.classify(plan_live, proj_huge) == "BLOCKED_BUDGET"


# Test 12 ---------------------------------------------------------------------


def test_build_envelope_schema() -> None:
    plan = cf_loadtest_runner.LoadTestPlan(
        distribution_domain="d.example.cloudfront.net",
        requests=100,
        concurrency=8,
        avg_object_bytes=2_000,
        manifest_path="/tmp/missing",
        seed=0,
        budget_usd=10.0,
        commit=False,
        unlock_live=False,
    )
    proj = cf_loadtest_runner.project_transfer_cost(100, 2_000)
    env = cf_loadtest_runner.build_envelope(plan, keys_total=50, projection=proj)
    assert env["schema_version"] == "jpcite.cf_loadtest_envelope.v1"
    assert env["classification"] == "DRY_RUN"
    assert env["plan"]["requests"] == 100
    assert env["projection"]["total_bytes"] == 200_000
    assert env["budget_usd"] == 10.0


# Test 13 ---------------------------------------------------------------------


def test_main_dry_run(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    manifest = tmp_path / "keys.txt"
    manifest.write_text("a/b.json\nc/d.json\n", encoding="utf-8")
    rc = cf_loadtest_runner.main(
        [
            "--distribution-domain",
            "d1234.cloudfront.net",
            "--manifest-path",
            str(manifest),
            "--requests",
            "100",
            "--concurrency",
            "8",
            "--budget-usd",
            "1.0",
        ]
    )
    assert rc == 0
    captured = capsys.readouterr()
    env = json.loads(captured.out)
    assert env["classification"] == "DRY_RUN"
    assert env["plan"]["requests"] == 100
    assert env["keys_total_in_manifest"] == 2
    assert isinstance(env.get("sample_urls"), list)
    assert env["sample_urls"][0].startswith("https://d1234.cloudfront.net/")
