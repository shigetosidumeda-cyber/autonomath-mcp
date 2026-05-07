"""Healthcare V3 stub tool tests — scaffolding contract (P6-D W4 prep).

Verifies that the 6 healthcare_* MCP tool stubs:

  1. Are NOT registered when AUTONOMATH_HEALTHCARE_ENABLED is unset / False
     (default). Total tool count must stay at 66 — this is the canonical
     public manifest as of 2026-04-25 (38 jpintel + 17 autonomath +
     4 V4 universal + 7 Phase A absorption).
  2. Are registered when AUTONOMATH_HEALTHCARE_ENABLED=1 is exported
     before importing the server module. Total tool count rises to 72.
  3. Each stub returns the sentinel envelope
     ``{"status": "not_implemented_until_T+90d", "results": []}``.
  4. Each stub's MCP tool object exposes a non-empty ``description`` /
     callable function with the expected ``Annotated``-typed parameters
     (light schema sanity check — full schema validation is W4 work).

Run order matters: the env-False case must fan out into a SUBPROCESS
because the module-level import of ``server`` is cached for the rest of
the pytest session, and we only want the env-True flag visible to the
True-branch test. Subprocess isolation keeps the assertions hermetic.
"""

from __future__ import annotations

import inspect
import os
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# Helper: run a small Python snippet under a controlled environment and
# return the stdout. Used to verify the env-gate without polluting the
# parent pytest process import cache.
# ---------------------------------------------------------------------------


def _run_in_subprocess(snippet: str, env_flag: str) -> str:
    env = os.environ.copy()
    if env_flag:
        env["AUTONOMATH_HEALTHCARE_ENABLED"] = env_flag
    else:
        env.pop("AUTONOMATH_HEALTHCARE_ENABLED", None)
    # Force a clean import of jpintel_mcp.mcp.server every subprocess.
    proc = subprocess.run(
        [sys.executable, "-c", snippet],
        env=env,
        capture_output=True,
        text=True,
        cwd=str(_REPO_ROOT),
        timeout=120,
    )
    if proc.returncode != 0:
        raise AssertionError(
            f"subprocess failed (rc={proc.returncode}):\n"
            f"STDOUT:\n{proc.stdout}\n"
            f"STDERR:\n{proc.stderr}"
        )
    return proc.stdout.strip()


# Names every test in this module checks for. Keep in sync with
# src/jpintel_mcp/mcp/healthcare_tools/tools.py and W4 plan in
# docs/healthcare_v3_plan.md.
_HEALTHCARE_TOOL_NAMES: list[str] = [
    "search_healthcare_programs",
    "get_medical_institution",
    "search_healthcare_compliance",
    "check_drug_approval",
    "search_care_subsidies",
    "dd_medical_institution_am",
]


# ---------------------------------------------------------------------------
# 1. env-False → 6 stubs NOT registered, total stays 66.
# ---------------------------------------------------------------------------


def test_healthcare_tools_not_registered_when_disabled() -> None:
    """Default env (flag unset) — 6 healthcare stubs are absent.

    The total tool count drifts as new tools land (89 at the time of
    this test write, after Wave 22 + NTA corpus + 会計士 audit tools);
    we therefore assert ONLY that none of the healthcare names leak,
    not a fixed integer.  The post-Wave-22 manifest is the canonical
    source — see `len(mcp._tool_manager.list_tools())`.
    """
    snippet = (
        "from jpintel_mcp.mcp import server;"
        "names=set(server.mcp._tool_manager._tools.keys());"
        f"expected={_HEALTHCARE_TOOL_NAMES!r};"
        "leaked=[n for n in expected if n in names];"
        "print(f'count={len(names)};leaked={leaked}')"
    )
    out = _run_in_subprocess(snippet, env_flag="")
    assert "leaked=[]" in out, f"healthcare tools leaked into default env: {out}"


# ---------------------------------------------------------------------------
# 2. env-True → 6 stubs registered, total = 77.
# ---------------------------------------------------------------------------


def test_healthcare_tools_registered_when_enabled() -> None:
    """AUTONOMATH_HEALTHCARE_ENABLED=1 registers all 6 healthcare stubs.

    We assert presence of each name rather than a fixed total — the
    canonical default-gate count keeps drifting upward as new tools land
    (89 at the time of writing post-Wave-22 / NTA / 会計士).
    """
    snippet = (
        "from jpintel_mcp.mcp import server;"
        "names=set(server.mcp._tool_manager._tools.keys());"
        f"expected={_HEALTHCARE_TOOL_NAMES!r};"
        "present=[n for n in expected if n in names];"
        "print(f'count={len(names)};present={present}')"
    )
    out = _run_in_subprocess(snippet, env_flag="1")
    for name in _HEALTHCARE_TOOL_NAMES:
        assert f"'{name}'" in out, f"healthcare tool {name!r} not registered: {out}"


# ---------------------------------------------------------------------------
# 3. Each stub returns the sentinel envelope.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "fn_name,call",
    [
        ("search_healthcare_programs", "fn(query='介護報酬', prefecture='東京都')"),
        ("get_medical_institution", "fn(canonical_id='mi_demo')"),
        (
            "search_healthcare_compliance",
            "fn(query='不当表示', law_basis='景表法')",
        ),
        ("check_drug_approval", "fn(drug_name='アスピリン')"),
        (
            "search_care_subsidies",
            "fn(prefecture='大阪府', institution_type_target='介護施設')",
        ),
        (
            "dd_medical_institution_am",
            "fn(corp_number='1234567890123')",
        ),
    ],
)
def test_healthcare_stub_returns_not_implemented(fn_name: str, call: str) -> None:
    """Every stub returns the sentinel envelope until W4 lands real SQL."""
    snippet = (
        "import os;os.environ.setdefault('AUTONOMATH_HEALTHCARE_ENABLED','1');"
        "from jpintel_mcp.mcp import server;"
        f"from jpintel_mcp.mcp.healthcare_tools.tools import {fn_name} as fn;"
        f"res={call};"
        "print(repr(res))"
    )
    out = _run_in_subprocess(snippet, env_flag="1")
    assert "'status': 'not_implemented_until_T+90d'" in out, (
        f"stub {fn_name!r} did not return sentinel envelope: {out}"
    )
    assert "'results': []" in out, (
        f"stub {fn_name!r} sentinel must include empty results list: {out}"
    )


# ---------------------------------------------------------------------------
# 4. Light schema sanity — each stub function has the expected parameters
#    with non-empty type annotations + each is callable.
# ---------------------------------------------------------------------------


_EXPECTED_PARAMS: dict[str, set[str]] = {
    "search_healthcare_programs": {"query", "prefecture", "law_basis", "limit", "offset"},
    "get_medical_institution": {"canonical_id"},
    "search_healthcare_compliance": {
        "query",
        "law_basis",
        "institution_type",
        "limit",
        "offset",
    },
    "check_drug_approval": {"drug_name", "approval_number", "limit"},
    "search_care_subsidies": {
        "prefecture",
        "institution_type_target",
        "authority_level",
        "tier",
        "limit",
        "offset",
    },
    "dd_medical_institution_am": {
        "corp_number",
        "include_enforcement",
        "include_subsidies",
        "include_loans",
    },
}


@pytest.mark.parametrize("fn_name", _HEALTHCARE_TOOL_NAMES)
def test_healthcare_stub_schema_shape(fn_name: str) -> None:
    """Each stub exposes the documented parameters with type annotations."""
    # Direct in-process import is fine here — we are only inspecting the
    # functions, never reading the global mcp tool registry. Importing
    # tools.py runs the @mcp.tool decorator but the assertion is on the
    # bare function objects, not on the registered set.
    from jpintel_mcp.mcp import server  # noqa: F401  — registers shared mcp
    from jpintel_mcp.mcp.healthcare_tools import tools as healthcare_tools

    fn = getattr(healthcare_tools, fn_name)
    assert callable(fn), f"{fn_name} is not callable"

    sig = inspect.signature(fn)
    actual = set(sig.parameters.keys())
    expected = _EXPECTED_PARAMS[fn_name]
    assert actual == expected, f"{fn_name} parameters mismatch: expected {expected}, got {actual}"
    # Every parameter must be type-annotated (Annotated[..., Field(...)])
    # — the Field carries the schema description used by FastMCP.
    for pname, p in sig.parameters.items():
        assert p.annotation is not inspect.Parameter.empty, (
            f"{fn_name}.{pname} has no type annotation"
        )
    # Docstring must be non-empty (FastMCP uses it as the tool description
    # when the decorator is bare).
    assert (inspect.getdoc(fn) or "").strip(), f"{fn_name} has empty docstring"
