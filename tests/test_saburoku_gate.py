"""Tests for 36協定 (`render_36_kyotei_am`) launch gate.

Decision doc: docs/_internal/saburoku_kyotei_gate_decision_2026-04-25.md.

The gate is module-level — `if settings.saburoku_kyotei_enabled:` wraps the
two `@mcp.tool` decorators in
`src/jpintel_mcp/mcp/autonomath_tools/template_tool.py`. Because the module
runs the decorator at import time, env-flag flips after import are no-ops:
the only way to exercise both branches is to run each test in a fresh
Python process via `subprocess`, so the env var is observed at module load.

This matches how the rest of the launch gates (`AUTONOMATH_HEALTHCARE_ENABLED`,
`AUTONOMATH_REAL_ESTATE_ENABLED`) would be tested at the registration layer.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pytest

# Tools we expect to disappear / reappear behind the gate.
_GATED_TOOLS = ("render_36_kyotei_am", "get_36_kyotei_metadata_am")


def _run_with_env(env_value: str, snippet: str) -> dict:
    """Spawn a fresh Python process so module-level gating is observed.

    Returns the JSON-parsed stdout of `snippet`. The snippet must
    `print(json.dumps({...}))` exactly once.
    """
    env = os.environ.copy()
    env["AUTONOMATH_36_KYOTEI_ENABLED"] = env_value
    # Belt-and-suspenders: ensure AUTONOMATH_ENABLED is truthy so the
    # autonomath_tools package import path runs at all.
    env.setdefault("AUTONOMATH_ENABLED", "1")
    # Use the same DB the conftest seeds — the gate logic does not touch
    # the DB, but importing `jpintel_mcp.mcp.server` does init_db().
    env.setdefault("JPINTEL_DB_PATH", env.get("JPINTEL_DB_PATH", ":memory:"))

    proc = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(snippet)],
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, (
        f"subprocess failed (env_value={env_value!r}):\n"
        f"--- stdout ---\n{proc.stdout}\n"
        f"--- stderr ---\n{proc.stderr}"
    )
    # Grab the last non-empty stdout line (logging may emit before).
    last = [line for line in proc.stdout.splitlines() if line.strip()][-1]
    return json.loads(last)


def _list_tools_snippet() -> str:
    """Snippet that imports the MCP server + autonomath_tools and prints
    the registered tool names from `mcp._tool_manager`."""
    return """
        import json
        from jpintel_mcp.mcp import server  # registers core tools
        # Force the autonomath_tools package import (server.py only runs it
        # when settings.autonomath_enabled — covered by the env above).
        from jpintel_mcp.mcp import autonomath_tools  # noqa: F401
        names = sorted(server.mcp._tool_manager.list_tools(), key=lambda t: t.name)
        print(json.dumps({"tools": [t.name for t in names]}))
    """


def _render_snippet() -> str:
    """Snippet that calls `render_36_kyotei_am` with valid fields and prints
    the result. Only meaningful when the gate is True."""
    return """
        import json
        from jpintel_mcp.mcp import server  # noqa: F401
        from jpintel_mcp.mcp import autonomath_tools  # noqa: F401
        from jpintel_mcp.mcp.autonomath_tools.template_tool import render_36_kyotei_am
        # FastMCP wraps tool functions — call the underlying function via the
        # registered Tool's fn attribute. Fallback: call render_36_kyotei_am.fn
        # if the decorator returned a Tool wrapper, else the function directly.
        target = render_36_kyotei_am
        for attr in ("fn", "func", "_func", "__wrapped__"):
            if hasattr(target, attr):
                target = getattr(target, attr)
                break
        result = target({
            "company_name": "Bookyou株式会社",
            "address": "東京都文京区小日向2-22-1",
            "representative": "梅田茂利",
            "industry": "情報通信業",
            "employee_count": "10",
            "agreement_period_start": "令和8年4月1日",
            "agreement_period_end": "令和9年3月31日",
            "max_overtime_hours_per_month": "45",
            "max_overtime_hours_per_year": "360",
            "holiday_work_days_per_month": "2",
        })
        print(json.dumps(result, ensure_ascii=False))
    """


# ----------------------------------------------------------------------
# 1. Default (env=False / unset) — both tools must disappear.
# ----------------------------------------------------------------------


def test_default_disabled_tools_absent():
    """`AUTONOMATH_36_KYOTEI_ENABLED=0` (default) — both tools MUST NOT
    appear in `mcp._tool_manager` registry."""
    out = _run_with_env("0", _list_tools_snippet())
    names = set(out["tools"])
    for t in _GATED_TOOLS:
        assert t not in names, (
            f"{t} leaked into the registry with the gate disabled — the launch gate is broken."
        )


def test_default_disabled_other_tools_present():
    """Sanity: the gate disables ONLY the two 36協定 tools; sibling Phase A
    tools (`deep_health_am`, `list_static_resources_am`) must still appear."""
    out = _run_with_env("0", _list_tools_snippet())
    names = set(out["tools"])
    # Surrounding Phase A tools must still register — i.e. we did not
    # accidentally break the package import.
    assert "deep_health_am" in names, (
        f"deep_health_am missing — package import may be broken. Got: {sorted(names)}"
    )
    assert "list_static_resources_am" in names, (
        f"list_static_resources_am missing — package import may be broken. Got: {sorted(names)}"
    )


# ----------------------------------------------------------------------
# 2. Enabled (env=True) — both tools reappear.
# ----------------------------------------------------------------------


def test_enabled_tools_present():
    """`AUTONOMATH_36_KYOTEI_ENABLED=1` — both tools MUST appear."""
    out = _run_with_env("1", _list_tools_snippet())
    names = set(out["tools"])
    for t in _GATED_TOOLS:
        assert t in names, (
            f"{t} missing with gate enabled — registration is broken. Got: {sorted(names)}"
        )


def test_enabled_render_returns_disclaimer():
    """When enabled, `render_36_kyotei_am` MUST attach `_disclaimer` (option B)."""
    result = _run_with_env("1", _render_snippet())
    assert "_disclaimer" in result, (
        f"render_36_kyotei_am response missing _disclaimer — option B is broken. "
        f"Keys: {sorted(result.keys())}"
    )
    msg = result["_disclaimer"]
    # Required fragments (must reference draft + 社労士 confirmation +
    # negation-context "保証しません" — INV-22-safe).
    assert "draft" in msg, f"disclaimer missing 'draft': {msg!r}"
    assert "社労士" in msg, f"disclaimer missing '社労士': {msg!r}"
    assert "保証しません" in msg, f"disclaimer missing '保証しません' (negation context): {msg!r}"
    # Affirmative INV-22 violations must NOT appear (the response_sanitizer
    # affirmative regex set keys on these phrases).
    assert "保証します" not in msg
    assert "必ず採択" not in msg


# ----------------------------------------------------------------------
# 3. Tool-count diff (env=False vs env=True must differ by exactly 2).
# ----------------------------------------------------------------------


def test_gate_toggles_exactly_two_tools():
    """The diff between disabled and enabled tool sets must be exactly the
    two 36協定 tools — nothing else should depend on this flag."""
    disabled = set(_run_with_env("0", _list_tools_snippet())["tools"])
    enabled = set(_run_with_env("1", _list_tools_snippet())["tools"])
    diff = enabled - disabled
    assert diff == set(_GATED_TOOLS), (
        f"gate flipped unexpected tools. expected diff={set(_GATED_TOOLS)}, got diff={diff}"
    )
    # No tool should disappear when the gate flips on.
    regression = disabled - enabled
    assert regression == set(), f"tools disappeared when gate enabled (regression): {regression}"


# ----------------------------------------------------------------------
# 4. Settings smoke (cheap, in-process) — config field is wired correctly.
# ----------------------------------------------------------------------


def test_settings_default_is_false():
    """Default value must be False (operator must opt-in after legal review)."""
    from jpintel_mcp.config import Settings

    s = Settings(_env_file=None)
    assert s.saburoku_kyotei_enabled is False


def test_settings_alias_and_truthy_parse(monkeypatch: pytest.MonkeyPatch):
    """`AUTONOMATH_36_KYOTEI_ENABLED=1` resolves to True via the alias."""
    monkeypatch.setenv("AUTONOMATH_36_KYOTEI_ENABLED", "1")
    from jpintel_mcp.config import Settings

    s = Settings(_env_file=None)
    assert s.saburoku_kyotei_enabled is True


# ----------------------------------------------------------------------
# 5. REST OpenAPI schema gate.
#
# The `include_in_schema=settings.saburoku_kyotei_enabled` argument on the
# two `@router` decorators in `src/jpintel_mcp/api/autonomath.py` is
# evaluated at import time, so we again need a fresh subprocess per
# polarity to observe the effect. Even when the schema hides them, the
# routes themselves remain registered and return 503 — so the runtime
# gate (`if not settings.saburoku_kyotei_enabled:` in the handler body)
# is intentionally redundant with the schema-hide. That is the safety
# property: a misconfigured deploy that re-includes the schema must
# still get a 503 instead of a draft 36協定 leaking out.
# ----------------------------------------------------------------------


_OPENAPI_PATH_METADATA = "/v1/am/templates/saburoku_kyotei/metadata"
_OPENAPI_PATH_RENDER = "/v1/am/templates/saburoku_kyotei"


def _openapi_paths_snippet() -> str:
    """Snippet that builds the FastAPI app and prints the path keys + the
    HTTP status returned by hitting the metadata endpoint via TestClient."""
    return """
        import json
        from fastapi.testclient import TestClient
        from jpintel_mcp.api.main import create_app
        app = create_app()
        schema = app.openapi()
        paths = sorted(schema.get("paths", {}).keys())
        client = TestClient(app, raise_server_exceptions=False)
        # Two probes: GET metadata, POST render with empty body.
        m = client.get("/v1/am/templates/saburoku_kyotei/metadata")
        r = client.post("/v1/am/templates/saburoku_kyotei", json={})
        print(json.dumps({
            "paths": paths,
            "metadata_status": m.status_code,
            "render_status": r.status_code,
        }))
    """


def test_openapi_hides_saburoku_when_disabled():
    """env=false (default) — both saburoku paths MUST be absent from
    `/openapi.json`. This is the regulated-surface leak fix."""
    out = _run_with_env("0", _openapi_paths_snippet())
    paths = set(out["paths"])
    assert _OPENAPI_PATH_METADATA not in paths, (
        f"{_OPENAPI_PATH_METADATA} leaked into OpenAPI schema with gate disabled — "
        "regulated 労基法 §36 surface MUST be hidden until legal review completes."
    )
    assert _OPENAPI_PATH_RENDER not in paths, (
        f"{_OPENAPI_PATH_RENDER} leaked into OpenAPI schema with gate disabled — "
        "regulated 労基法 §36 surface MUST be hidden until legal review completes."
    )


def test_openapi_exposes_saburoku_when_enabled():
    """env=true — both saburoku paths MUST appear in `/openapi.json` so
    paid callers can discover the contract once legal review is signed off."""
    out = _run_with_env("1", _openapi_paths_snippet())
    paths = set(out["paths"])
    assert _OPENAPI_PATH_METADATA in paths, (
        f"{_OPENAPI_PATH_METADATA} missing from OpenAPI schema with gate enabled — "
        f"include_in_schema wiring is broken. Got: {sorted(paths)[:20]}…"
    )
    assert _OPENAPI_PATH_RENDER in paths, (
        f"{_OPENAPI_PATH_RENDER} missing from OpenAPI schema with gate enabled — "
        f"include_in_schema wiring is broken. Got: {sorted(paths)[:20]}…"
    )


def test_request_returns_503_when_disabled():
    """env=false — even though the schema hides them, the routes remain
    registered and the handler MUST return the existing 503 envelope.
    This guards against a misconfigured deploy that flips the schema flag
    without flipping the runtime flag."""
    out = _run_with_env("0", _openapi_paths_snippet())
    assert out["metadata_status"] == 503, (
        f"GET {_OPENAPI_PATH_METADATA} expected 503 with gate disabled, got "
        f"{out['metadata_status']} — runtime gate may have regressed."
    )
    assert out["render_status"] == 503, (
        f"POST {_OPENAPI_PATH_RENDER} expected 503 with gate disabled, got "
        f"{out['render_status']} — runtime gate may have regressed."
    )
