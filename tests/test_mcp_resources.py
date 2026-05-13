"""Tests for MCP `resources[]` registration (Phase A static resources).

Verifies that:
  - `mcp.list_resources()` returns the expected count
  - all 8 taxonomies are addressable via `autonomath://taxonomies/{slug}`
  - all 5 example profiles are addressable via `autonomath://example_profiles/{slug}`
  - all 9 cohort persona-kit resources are addressable via `autonomath://cohort/...`
  - the 36協定 template resource is gated by AUTONOMATH_36_KYOTEI_ENABLED
  - AUTONOMATH_ENABLED=0 hides every autonomath:// resource

These are MCP-level integration tests — they exercise the actual FastMCP
server singleton wired in `jpintel_mcp.mcp.server` and the
`register_resources` call inside `autonomath_tools/__init__.py`.

Existing tools (`list_static_resources_am` / `get_static_resource_am` / etc.)
are intentionally NOT removed — they remain registered for back-compat.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

# 15 schema/policy/list + 8 taxonomies + 5 example profiles + 9 cohort-kit
# resources = 37 baseline (gate OFF). With AUTONOMATH_36_KYOTEI_ENABLED=1
# the saburoku template adds one more -> 38.
EXPECTED_DEFAULT_RESOURCE_COUNT = 37
EXPECTED_SABUROKU_RESOURCE_COUNT = 38
EXPECTED_TAXONOMIES = {
    "seido",
    "glossary",
    "money_types",
    "obligations",
    "dealbreakers",
    "sector_combos",
    "crop_library",
    "exclusion_rules",
}
EXPECTED_PROFILES = {
    "ichigo_20a",
    "rice_200a",
    "new_corp",
    "dairy_100head",
    "minimal",
}
EXPECTED_COHORT_RESOURCES = {
    "autonomath://cohort/foreign_fdi.yaml",
    "autonomath://cohort/index.json",
    "autonomath://cohort/industry_pack.yaml",
    "autonomath://cohort/kaikeishi.yaml",
    "autonomath://cohort/ma_dd.yaml",
    "autonomath://cohort/shihoshoshi.yaml",
    "autonomath://cohort/smb_line.yaml",
    "autonomath://cohort/subsidy_consultant.yaml",
    "autonomath://cohort/tax_advisor.yaml",
}


def _purge_modules() -> None:
    """Drop cached modules so each test re-imports under fresh env."""
    for mod_name in list(sys.modules):
        if mod_name.startswith("jpintel_mcp") or mod_name == "jpintel_mcp":
            sys.modules.pop(mod_name, None)


@pytest.fixture
def fresh_mcp(monkeypatch):
    """Build a fresh FastMCP server each call so env-flag changes take effect."""
    monkeypatch.setenv("AUTONOMATH_ENABLED", "1")
    monkeypatch.delenv("AUTONOMATH_36_KYOTEI_ENABLED", raising=False)
    _purge_modules()
    from jpintel_mcp.mcp.server import mcp  # noqa: E402

    yield mcp
    _purge_modules()


@pytest.fixture
def fresh_mcp_saburoku_on(monkeypatch):
    monkeypatch.setenv("AUTONOMATH_ENABLED", "1")
    monkeypatch.setenv("AUTONOMATH_36_KYOTEI_ENABLED", "1")
    _purge_modules()
    from jpintel_mcp.mcp.server import mcp  # noqa: E402

    yield mcp
    _purge_modules()


@pytest.fixture
def fresh_mcp_disabled(monkeypatch):
    monkeypatch.setenv("AUTONOMATH_ENABLED", "0")
    monkeypatch.setenv("JPCITE_ENABLED", "0")
    monkeypatch.delenv("AUTONOMATH_36_KYOTEI_ENABLED", raising=False)
    monkeypatch.delenv("JPCITE_36_KYOTEI_ENABLED", raising=False)
    _purge_modules()
    from jpintel_mcp.mcp.server import mcp  # noqa: E402

    yield mcp
    _purge_modules()


def _list_resources(mcp) -> list:
    return asyncio.run(mcp.list_resources())


def _autonomath_uris(resources) -> set[str]:
    return {str(r.uri) for r in resources if str(r.uri).startswith("autonomath://")}


# ---------------------------------------------------------------------------
# Counts
# ---------------------------------------------------------------------------


def test_resource_count_default(fresh_mcp):
    """Default gate: 15 base + 8 taxonomies + 5 profiles + 9 cohorts = 37."""
    res = _list_resources(fresh_mcp)
    auton = _autonomath_uris(res)
    assert len(auton) == EXPECTED_DEFAULT_RESOURCE_COUNT, (
        f"expected {EXPECTED_DEFAULT_RESOURCE_COUNT} autonomath resources, "
        f"got {len(auton)}: {sorted(auton)}"
    )


def test_resource_count_saburoku_on(fresh_mcp_saburoku_on):
    """With AUTONOMATH_36_KYOTEI_ENABLED=1: 37 + saburoku = 38."""
    res = _list_resources(fresh_mcp_saburoku_on)
    auton = _autonomath_uris(res)
    assert len(auton) == EXPECTED_SABUROKU_RESOURCE_COUNT
    assert "autonomath://templates/saburoku_kyotei" in auton


def test_resource_count_autonomath_disabled(fresh_mcp_disabled):
    """AUTONOMATH_ENABLED=0 → no autonomath resources surface."""
    res = _list_resources(fresh_mcp_disabled)
    auton = _autonomath_uris(res)
    assert len(auton) == 0


# ---------------------------------------------------------------------------
# Coverage of the 8 taxonomies + 5 profiles
# ---------------------------------------------------------------------------


def test_all_taxonomies_registered(fresh_mcp):
    res = _list_resources(fresh_mcp)
    uris = _autonomath_uris(res)
    expected = {f"autonomath://taxonomies/{s}" for s in EXPECTED_TAXONOMIES}
    missing = expected - uris
    assert not missing, f"missing taxonomy resources: {missing}"


def test_all_example_profiles_registered(fresh_mcp):
    res = _list_resources(fresh_mcp)
    uris = _autonomath_uris(res)
    expected = {f"autonomath://example_profiles/{s}" for s in EXPECTED_PROFILES}
    missing = expected - uris
    assert not missing, f"missing example profile resources: {missing}"


def test_all_cohort_resources_registered(fresh_mcp):
    res = _list_resources(fresh_mcp)
    uris = _autonomath_uris(res)
    missing = EXPECTED_COHORT_RESOURCES - uris
    assert not missing, f"missing cohort resources: {missing}"


def test_taxonomies_use_json_mime(fresh_mcp):
    res = _list_resources(fresh_mcp)
    for r in res:
        if str(r.uri).startswith("autonomath://taxonomies/"):
            assert r.mimeType == "application/json", (
                f"{r.uri} has mimeType={r.mimeType!r}, expected application/json"
            )


def test_example_profiles_use_json_mime(fresh_mcp):
    res = _list_resources(fresh_mcp)
    for r in res:
        if str(r.uri).startswith("autonomath://example_profiles/"):
            assert r.mimeType == "application/json"


# ---------------------------------------------------------------------------
# Read individual resources via the registry-level read_resource() helper.
# (FastMCP's resources/read goes through ResourceManager.get_resource().read()
# which is harder to drive in-process; the registry helper is the canonical
# in-process test seam.)
# ---------------------------------------------------------------------------


def test_read_taxonomy_seido_returns_valid_json(fresh_mcp):
    from jpintel_mcp.mcp.autonomath_tools.resources import read_resource

    payload = read_resource("autonomath://taxonomies/seido")
    text = payload["contents"][0]["text"]
    assert payload["contents"][0]["mimeType"] == "application/json"
    parsed = json.loads(text)
    assert parsed, "seido.json parsed empty"


def test_read_example_profile_minimal_returns_valid_json(fresh_mcp):
    from jpintel_mcp.mcp.autonomath_tools.resources import read_resource

    payload = read_resource("autonomath://example_profiles/minimal")
    text = payload["contents"][0]["text"]
    parsed = json.loads(text)
    # minimal profile has _meta block with user_type field
    assert isinstance(parsed, dict)
    assert "_meta" in parsed or "ident" in parsed or len(parsed) > 0


def test_read_each_taxonomy_succeeds(fresh_mcp):
    """All 8 taxonomies must read successfully (file present, JSON valid)."""
    from jpintel_mcp.mcp.autonomath_tools.resources import read_resource

    for slug in EXPECTED_TAXONOMIES:
        uri = f"autonomath://taxonomies/{slug}"
        payload = read_resource(uri)
        text = payload["contents"][0]["text"]
        # Each one must be parseable JSON (the provider falls back to an
        # error stub on missing file; that stub is also valid JSON, so we
        # additionally assert it doesn't carry our error sentinel).
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            assert parsed.get("error") != "resource_file_missing", f"{uri} missing on disk"


def test_read_each_example_profile_succeeds(fresh_mcp):
    from jpintel_mcp.mcp.autonomath_tools.resources import read_resource

    for slug in EXPECTED_PROFILES:
        uri = f"autonomath://example_profiles/{slug}"
        payload = read_resource(uri)
        text = payload["contents"][0]["text"]
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            assert parsed.get("error") != "profile_file_missing"


def test_unknown_uri_raises(fresh_mcp):
    from jpintel_mcp.mcp.autonomath_tools.resources import read_resource

    with pytest.raises(KeyError):
        read_resource("autonomath://taxonomies/does_not_exist")


# ---------------------------------------------------------------------------
# Saburoku gate
# ---------------------------------------------------------------------------


def test_saburoku_template_hidden_when_gate_off(fresh_mcp):
    res = _list_resources(fresh_mcp)
    uris = _autonomath_uris(res)
    assert "autonomath://templates/saburoku_kyotei" not in uris


def test_saburoku_template_visible_when_gate_on(fresh_mcp_saburoku_on):
    res = _list_resources(fresh_mcp_saburoku_on)
    uris = _autonomath_uris(res)
    assert "autonomath://templates/saburoku_kyotei" in uris


def test_saburoku_template_read_when_gate_on(fresh_mcp_saburoku_on):
    from jpintel_mcp.mcp.autonomath_tools.resources import read_resource

    payload = read_resource("autonomath://templates/saburoku_kyotei")
    text = payload["contents"][0]["text"]
    assert payload["contents"][0]["mimeType"] == "text/plain"
    # The template carries the 厚生労働省 / 36協定届 marker text
    assert "36協定" in text or "時間外労働" in text


def test_saburoku_template_read_raises_when_gate_off(fresh_mcp):
    from jpintel_mcp.mcp.autonomath_tools.resources import read_resource

    with pytest.raises(KeyError):
        read_resource("autonomath://templates/saburoku_kyotei")


# ---------------------------------------------------------------------------
# Back-compat: legacy tools must still be registered (not deprecated yet).
# ---------------------------------------------------------------------------


def test_legacy_static_tools_still_registered(fresh_mcp):
    tool_names = {t.name for t in fresh_mcp._tool_manager.list_tools()}
    # All four legacy tools must remain (resources are an additive layer).
    for legacy in (
        "list_static_resources_am",
        "get_static_resource_am",
        "list_example_profiles_am",
        "get_example_profile_am",
    ):
        assert legacy in tool_names, f"legacy tool {legacy} accidentally removed"
