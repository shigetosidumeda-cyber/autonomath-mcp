"""Real Estate V5 stub tool tests — scaffolding contract (P6-F W4 prep).

Verifies that the 5 real_estate_* MCP tool stubs:

  1. Are NOT registered when AUTONOMATH_REAL_ESTATE_ENABLED is unset / False
     (default). Total tool count must stay at 55 — this is the canonical
     public manifest as of 2026-04-25 (38 jpintel + 17 autonomath).
  2. Are registered when AUTONOMATH_REAL_ESTATE_ENABLED=1 is exported
     before importing the server module. Total tool count rises to 60.
  3. Each stub returns the sentinel envelope
     ``{"status": "not_implemented_until_T+200d", ...}`` with the
     canonical preview shape (paginated tools also expose
     ``total=0`` + ``results=[]``).
  4. Each stub's MCP tool function exposes the documented ``Annotated``-
     typed parameter set + a non-empty docstring (FastMCP tool description).

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
        env["AUTONOMATH_REAL_ESTATE_ENABLED"] = env_flag
    else:
        env.pop("AUTONOMATH_REAL_ESTATE_ENABLED", None)
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
# src/jpintel_mcp/mcp/real_estate_tools/tools.py and W4 plan in
# docs/real_estate_v5_plan.md.
_REAL_ESTATE_TOOL_NAMES: list[str] = [
    "search_real_estate_programs",
    "get_zoning_overlay",
    "search_real_estate_compliance",
    "dd_property_am",
    "cross_check_zoning",
]


# ---------------------------------------------------------------------------
# 1. env-False → 5 stubs NOT registered, total stays 55.
# ---------------------------------------------------------------------------


def test_real_estate_tools_not_registered_when_disabled() -> None:
    """Default env (flag unset) — 5 real-estate stubs are absent.

    We assert ONLY no-leak rather than a fixed total — see the matching
    note in `test_healthcare_tools.py`; canonical default-gate count
    drifts as new tools land.
    """
    snippet = (
        "from jpintel_mcp.mcp import server;"
        "names=set(server.mcp._tool_manager._tools.keys());"
        f"expected={_REAL_ESTATE_TOOL_NAMES!r};"
        "leaked=[n for n in expected if n in names];"
        "print(f'count={len(names)};leaked={leaked}')"
    )
    out = _run_in_subprocess(snippet, env_flag="")
    assert "leaked=[]" in out, f"real estate tools leaked into default env: {out}"


# ---------------------------------------------------------------------------
# 2. env-True → 5 stubs registered, total = 76.
# ---------------------------------------------------------------------------


def test_real_estate_tools_registered_when_enabled() -> None:
    """AUTONOMATH_REAL_ESTATE_ENABLED=1 registers all 5 stubs.

    Presence-only assertion — see matching note in
    `test_healthcare_tools.py` for the rationale.
    """
    snippet = (
        "from jpintel_mcp.mcp import server;"
        "names=set(server.mcp._tool_manager._tools.keys());"
        f"expected={_REAL_ESTATE_TOOL_NAMES!r};"
        "present=[n for n in expected if n in names];"
        "print(f'count={len(names)};present={present}')"
    )
    out = _run_in_subprocess(snippet, env_flag="1")
    for name in _REAL_ESTATE_TOOL_NAMES:
        assert f"'{name}'" in out, f"real estate tool {name!r} not registered: {out}"


# ---------------------------------------------------------------------------
# 3. Each stub returns the sentinel envelope.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "fn_name,call",
    [
        (
            "search_real_estate_programs",
            "fn(q='耐震改修', prefecture='東京都', program_kind='subsidy')",
        ),
        (
            "get_zoning_overlay",
            "fn(prefecture='東京都', city='千代田区', district='丸の内一丁目')",
        ),
        (
            "search_real_estate_compliance",
            "fn(q='処分', law_basis='宅地建物取引業法', prefecture='大阪府')",
        ),
        (
            "dd_property_am",
            "fn(prefecture='神奈川県', city='横浜市西区', owner_corporate_number='1234567890123')",
        ),
        (
            "cross_check_zoning",
            "fn(prefecture='東京都', city='港区', "
            "planned_kenpei_pct=70.0, planned_yoseki_pct=400.0, "
            "planned_height_m=31.0)",
        ),
    ],
)
def test_real_estate_stub_returns_not_implemented(fn_name: str, call: str) -> None:
    """Every stub returns the sentinel envelope until T+200d lands real SQL."""
    snippet = (
        "import os;os.environ.setdefault('AUTONOMATH_REAL_ESTATE_ENABLED','1');"
        "from jpintel_mcp.mcp import server;"
        f"from jpintel_mcp.mcp.real_estate_tools.tools import {fn_name} as fn;"
        f"res={call};"
        "print(repr(res))"
    )
    out = _run_in_subprocess(snippet, env_flag="1")
    assert (
        "'status': 'not_implemented_until_T+200d'" in out
    ), f"stub {fn_name!r} did not return sentinel envelope: {out}"
    assert (
        "'launch_target': '2026-11-22'" in out
    ), f"stub {fn_name!r} sentinel must carry launch_target: {out}"
    assert (
        "'filter_applied':" in out
    ), f"stub {fn_name!r} sentinel must echo filter_applied for traceability: {out}"


# ---------------------------------------------------------------------------
# 3b. Paginated stubs also expose total/results envelope keys.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "fn_name,call",
    [
        (
            "search_real_estate_programs",
            "fn(q='耐震', prefecture='東京都')",
        ),
        (
            "search_real_estate_compliance",
            "fn(q='違反', law_basis='建設業法')",
        ),
    ],
)
def test_real_estate_paginated_stub_envelope(fn_name: str, call: str) -> None:
    """Paginated search_* stubs must surface total=0 + empty results list."""
    snippet = (
        "import os;os.environ.setdefault('AUTONOMATH_REAL_ESTATE_ENABLED','1');"
        "from jpintel_mcp.mcp import server;"
        f"from jpintel_mcp.mcp.real_estate_tools.tools import {fn_name} as fn;"
        f"res={call};"
        "print(repr(res))"
    )
    out = _run_in_subprocess(snippet, env_flag="1")
    assert "'total': 0" in out, f"paginated stub {fn_name!r} must report total=0: {out}"
    assert (
        "'results': []" in out
    ), f"paginated stub {fn_name!r} must return empty results list: {out}"


# ---------------------------------------------------------------------------
# 4. Light schema sanity — each stub function has the expected parameters
#    with non-empty type annotations + each is callable.
# ---------------------------------------------------------------------------


_EXPECTED_PARAMS: dict[str, set[str]] = {
    "search_real_estate_programs": {
        "q",
        "program_kind",
        "law_basis",
        "prefecture",
        "property_type_target",
        "tier",
        "limit",
        "offset",
    },
    "get_zoning_overlay": {"prefecture", "city", "district", "zoning_type"},
    "search_real_estate_compliance": {
        "q",
        "law_basis",
        "prefecture",
        "corporate_number",
        "days_back",
        "limit",
        "offset",
    },
    "dd_property_am": {
        "prefecture",
        "city",
        "district",
        "owner_corporate_number",
        "property_type",
    },
    "cross_check_zoning": {
        "prefecture",
        "city",
        "district",
        "planned_kenpei_pct",
        "planned_yoseki_pct",
        "planned_height_m",
    },
}


@pytest.mark.parametrize("fn_name", _REAL_ESTATE_TOOL_NAMES)
def test_real_estate_stub_schema_shape(fn_name: str) -> None:
    """Each stub exposes the documented parameters with type annotations."""
    # Direct in-process import is fine here — we are only inspecting the
    # functions, never reading the global mcp tool registry. Importing
    # tools.py runs the @mcp.tool decorator but the assertion is on the
    # bare function objects, not on the registered set.
    from jpintel_mcp.mcp import server  # noqa: F401  — registers shared mcp
    from jpintel_mcp.mcp.real_estate_tools import tools as real_estate_tools

    fn = getattr(real_estate_tools, fn_name)
    assert callable(fn), f"{fn_name} is not callable"

    sig = inspect.signature(fn)
    actual = set(sig.parameters.keys())
    expected = _EXPECTED_PARAMS[fn_name]
    assert actual == expected, f"{fn_name} parameters mismatch: expected {expected}, got {actual}"
    # Every parameter must be type-annotated (Annotated[..., Field(...)])
    # — the Field carries the schema description used by FastMCP.
    for pname, p in sig.parameters.items():
        assert (
            p.annotation is not inspect.Parameter.empty
        ), f"{fn_name}.{pname} has no type annotation"
    # Docstring must be non-empty (FastMCP uses it as the tool description
    # when the decorator is bare).
    assert (inspect.getdoc(fn) or "").strip(), f"{fn_name} has empty docstring"
