"""
DEEP-61 stub tests for post_deploy_smoke.py.

Runs offline. No live API, no MCP server spawned — every test exercises the
script's structure, parsed inputs, exit codes, and the LLM-API guard. The
goal is to catch regressions in the runbook contract (240 sample, 17 sensitive,
exit-code surface, timing-log format) before the script ever touches a real
deploy.

Usage:
    .venv/bin/pytest test_post_deploy_smoke.py -q
"""

from __future__ import annotations

import argparse
import importlib.util
import io
import json
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
SCRIPT = REPO_ROOT / "scripts" / "ops" / "post_deploy_smoke.py"
ROUTES = HERE / "fixtures" / "240_routes_sample.txt"
SENSITIVE = HERE / "fixtures" / "17_sensitive_tools.json"


def _load_module():
    # Register in sys.modules BEFORE exec_module — required on Python 3.9
    # for `from __future__ import annotations` + @dataclass type resolution.
    name = "post_deploy_smoke_under_test"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# 1. Five module registry shape
# ---------------------------------------------------------------------------


def test_module_registry_has_exactly_5():
    mod = _load_module()
    assert set(mod.MODULES.keys()) == {"routes", "mcp", "disclaimer", "stripe", "health"}


# ---------------------------------------------------------------------------
# 2. 240 route sample list arity
# ---------------------------------------------------------------------------


def test_240_route_sample_list_arity():
    mod = _load_module()
    rows = mod._load_routes()
    assert len(rows) == 240, f"sample list arity drift: got {len(rows)}, want 240"
    assert all(p.startswith("/") for p in rows), "every sample row must start with '/'"


# ---------------------------------------------------------------------------
# 3. 17 sensitive tool envelope contract
# ---------------------------------------------------------------------------


def test_17_sensitive_tools_load_and_arity():
    mod = _load_module()
    table = mod._load_sensitive_tools()
    assert len(table) == 17
    seen_names = set()
    for row in table:
        for k in ("name", "law", "fence", "wave", "sample_arguments"):
            assert k in row, f"sensitive row missing {k!r}: {row}"
        assert row["name"] not in seen_names, f"duplicate sensitive tool: {row['name']}"
        seen_names.add(row["name"])
        assert isinstance(row["sample_arguments"], dict)


# ---------------------------------------------------------------------------
# 4. Timing log line format
# ---------------------------------------------------------------------------


def test_timing_log_line_format():
    mod = _load_module()
    r = mod.ModuleResult(name="routes_500_zero", ok=True, elapsed_s=1.234, summary="240/240")
    line = r.line()
    assert line.startswith("[PASS] routes_500_zero")
    assert "1.23s" in line
    bad = mod.ModuleResult(name="mcp_tools_list", ok=False, elapsed_s=9.99, summary="floor missed")
    assert bad.line().startswith("[FAIL] mcp_tools_list")


# ---------------------------------------------------------------------------
# 5. Exit code 0 path (all modules pass)
# ---------------------------------------------------------------------------


def test_exit_code_0_when_all_modules_pass():
    mod = _load_module()
    fake_results = [
        mod.ModuleResult(name="health_endpoints", ok=True, elapsed_s=0.4, summary="3/3"),
        mod.ModuleResult(name="routes_500_zero", ok=True, elapsed_s=58.1, summary="240/240"),
        mod.ModuleResult(name="mcp_tools_list", ok=True, elapsed_s=9.8, summary="142 tools"),
        mod.ModuleResult(name="disclaimer_emit_17", ok=True, elapsed_s=23.5, summary="17/17"),
        mod.ModuleResult(name="stripe_webhook", ok=True, elapsed_s=2.0, summary="ok"),
    ]
    with mock.patch.object(
        mod,
        "select_modules",
        return_value=[lambda args, r=r: r for r in fake_results],  # noqa: B023  (default-arg binds r per iteration)
    ):
        # patch select_modules to return a list of zero-arg lambdas that return the canned results
        # easier: patch each MODULE entry directly
        pass

    # Direct route: build a fake driver that injects the canned ModuleResult for each call
    fake_calls = iter(fake_results)

    def fake_fn(_args):
        return next(fake_calls)

    with mock.patch.object(mod, "select_modules", return_value=[fake_fn] * len(fake_results)):
        out = io.StringIO()
        err = io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = mod.main(["--base-url", "https://api.jpcite.com", "--module", "all"])
        assert code == 0
        payload = json.loads(out.getvalue().strip())
        assert payload == {
            "ok": True,
            "modules": [
                "health_endpoints",
                "routes_500_zero",
                "mcp_tools_list",
                "disclaimer_emit_17",
                "stripe_webhook",
            ],
        }


# ---------------------------------------------------------------------------
# 6. Exit code 1 path (one module fails)
# ---------------------------------------------------------------------------


def test_exit_code_1_when_any_module_fails():
    mod = _load_module()
    bad = mod.ModuleResult(
        name="disclaimer_emit_17", ok=False, elapsed_s=4.0, summary="14/17 missing 3"
    )
    fake_calls = iter([bad])

    def fake_fn(_args):
        return next(fake_calls)

    with mock.patch.object(mod, "select_modules", return_value=[fake_fn]):
        out = io.StringIO()
        err = io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = mod.main(["--module", "disclaimer"])
        assert code == 1
        payload = json.loads(out.getvalue().strip())
        assert payload["ok"] is False


# ---------------------------------------------------------------------------
# 7. LLM API import budget = 0 (DEEP-61 hard constraint)
# ---------------------------------------------------------------------------


def test_no_llm_api_imports_in_script_source():
    text = SCRIPT.read_text(encoding="utf-8")
    forbidden = (
        "import anthropic",
        "import openai",
        "import google.generativeai",
        "import claude_agent_sdk",
        "from anthropic",
        "from openai",
    )
    for needle in forbidden:
        assert needle not in text, f"DEEP-61 violation: script source contains {needle!r}"


# ---------------------------------------------------------------------------
# 8. GHA-friendly stdout = single JSON line
# ---------------------------------------------------------------------------


def test_stdout_is_single_json_line():
    mod = _load_module()
    fake_calls = iter(
        [mod.ModuleResult(name="health_endpoints", ok=True, elapsed_s=0.1, summary="ok")]
    )

    def fake_fn(_args):
        return next(fake_calls)

    with mock.patch.object(mod, "select_modules", return_value=[fake_fn]):
        out = io.StringIO()
        with redirect_stdout(out), redirect_stderr(io.StringIO()):
            mod.main(["--module", "health"])
        body = out.getvalue().strip().splitlines()
        assert len(body) == 1
        json.loads(body[0])  # raises if not valid JSON


# ---------------------------------------------------------------------------
# 9. Per-module isolation — failure in one does not crash sibling
# ---------------------------------------------------------------------------


def test_per_module_isolation_via_timed_decorator():
    mod = _load_module()

    @mod._timed
    def boom(args):  # noqa: ANN001
        raise RuntimeError("synthetic")

    fake_args = argparse.Namespace(base_url="https://x", verbose=False)
    r = boom(fake_args)
    assert r.ok is False
    assert "synthetic" in r.summary
    assert r.elapsed_s >= 0


# ---------------------------------------------------------------------------
# 10. DEEP-25 verify-primitive cross-check (envelope shape parity)
# ---------------------------------------------------------------------------


def test_deep25_verify_primitive_envelope_shape():
    """The envelope-walking helper must accept all 3 envelope shapes DEEP-25 ships:
    (a) top-level result._disclaimer, (b) inline content[].text JSON,
    (c) inline content[]._disclaimer dict (FastMCP newer wrapping).
    """
    mod = _load_module()
    a = {"result": {"_disclaimer": {"laws": []}}}
    b = {
        "result": {"content": [{"type": "text", "text": json.dumps({"_disclaimer": {"laws": []}})}]}
    }
    c = {"result": {"content": [{"type": "text", "_disclaimer": {"laws": []}, "text": "{}"}]}}
    bad = {"result": {"content": [{"type": "text", "text": '{"_no_disclaimer": true}'}]}}
    assert mod._envelope_has_disclaimer(a)
    assert mod._envelope_has_disclaimer(b)
    assert mod._envelope_has_disclaimer(c)
    assert not mod._envelope_has_disclaimer(bad)
