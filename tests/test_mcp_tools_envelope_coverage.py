"""Coverage tests for small MCP tool helpers.

Targets at baseline:

- ``mcp/autonomath_tools/error_envelope.py`` 91% → 100% (cover extra kwargs).
- ``mcp/autonomath_tools/static_resources.py`` 59% → exercise list/get +
  ResourceNotFoundError branches without touching MCP server boot.
- Adds smoke imports of ``health_tool`` / ``template_tool`` so plain import
  coverage lines (gating + module-level constants) light up.

All paths are pure-function deterministic (no DB, no network, no LLM).
"""

from __future__ import annotations

import pytest

from jpintel_mcp.mcp.autonomath_tools.error_envelope import (
    DOC_URL,
    ERROR_CODES,
    is_error,
    make_error,
)
from jpintel_mcp.mcp.autonomath_tools.static_resources import (
    EXAMPLE_DIR,
    STATIC_DIR,
    ResourceNotFoundError,
    _load_json,
    get_example_profile,
    get_static_resource,
    list_example_profiles,
    list_static_resources,
)

# ---------------------------------------------------------------------------
# error_envelope.make_error — uncovered branches
# ---------------------------------------------------------------------------


def test_make_error_carries_retry_with_when_provided() -> None:
    env = make_error(
        "no_matching_records",
        "no rows",
        retry_with=["search_programs", "active_programs_at"],
    )
    assert env["error"]["retry_with"] == ["search_programs", "active_programs_at"]


def test_make_error_carries_suggested_tools_when_provided() -> None:
    env = make_error(
        "ambiguous_query",
        "query matches multiple kinds",
        suggested_tools=["enum_values"],
    )
    assert env["error"]["suggested_tools"] == ["enum_values"]


def test_make_error_carries_retry_args_when_provided() -> None:
    env = make_error(
        "invalid_argument",
        "unknown region",
        retry_args={"region": "関東"},
    )
    assert env["error"]["retry_args"] == {"region": "関東"}


def test_make_error_carries_field_when_provided() -> None:
    env = make_error("missing_required_arg", "missing", field="query")
    assert env["error"]["field"] == "query"


def test_make_error_extra_merges_into_error_dict() -> None:
    env = make_error(
        "seed_not_found",
        "seed missing",
        extra={"seed_name": "prog-XYZ"},
    )
    assert env["error"]["seed_name"] == "prog-XYZ"


def test_make_error_unknown_code_coerces_to_internal() -> None:
    # mypy will complain about the type, but runtime path matters.
    env = make_error("not_a_real_code", "bogus")  # type: ignore[arg-type]
    assert env["error"]["code"] == "internal"


def test_make_error_includes_documentation_anchor() -> None:
    env = make_error("db_locked", "locked")
    assert env["error"]["documentation"] == f"{DOC_URL}#db_locked"


def test_make_error_clamps_limit_and_offset_inside_envelope() -> None:
    env_high = make_error("internal", "x", limit=500, offset=-1)
    assert env_high["limit"] == 100
    assert env_high["offset"] == 0
    env_low = make_error("internal", "x", limit=0, offset=10)
    assert env_low["limit"] == 1
    assert env_low["offset"] == 10


def test_make_error_strips_message_whitespace() -> None:
    env = make_error("internal", "   trim me   ")
    assert env["error"]["message"] == "trim me"


def test_make_error_falls_back_to_summary_when_message_empty() -> None:
    env = make_error("internal", "")
    assert env["error"]["message"] == ERROR_CODES["internal"]["summary"]


def test_is_error_returns_true_for_valid_envelope() -> None:
    env = make_error("no_matching_records", "x")
    assert is_error(env) is True


def test_is_error_returns_false_for_non_dict() -> None:
    assert is_error("string") is False
    assert is_error(None) is False
    assert is_error([1, 2]) is False


def test_is_error_returns_false_when_code_missing() -> None:
    assert is_error({"error": {"message": "x"}}) is False


def test_is_error_returns_false_for_unknown_code() -> None:
    assert is_error({"error": {"code": "not_real"}}) is False


# ---------------------------------------------------------------------------
# static_resources
# ---------------------------------------------------------------------------


def test_static_resources_dir_constants_are_paths() -> None:
    # Sanity: STATIC_DIR is always a Path even if missing on disk.
    assert STATIC_DIR.name == "autonomath_static"
    assert EXAMPLE_DIR.name == "example_profiles"


def test_list_static_resources_returns_list_of_manifests() -> None:
    out = list_static_resources()
    assert isinstance(out, list)
    # Every entry has the canonical keys.
    for entry in out:
        assert "id" in entry
        assert "filename" in entry
        assert "path_relative" in entry
        assert entry["path_relative"].startswith("jpcite/static/")
        assert isinstance(entry["size_bytes"], int)


def test_get_static_resource_unknown_id_raises_resource_not_found() -> None:
    with pytest.raises(ResourceNotFoundError) as exc:
        get_static_resource("does_not_exist_zzz")
    assert "unknown resource" in str(exc.value)


def test_get_static_resource_known_id_returns_data_payload() -> None:
    out = list_static_resources()
    if not out:
        pytest.skip("no static resources on disk in this env")
    rid = out[0]["id"]
    payload = get_static_resource(rid)
    assert payload["id"] == rid
    assert "data" in payload
    assert "license" in payload
    assert payload["source_origin"] == "jpcite reference data"


def test_list_example_profiles_returns_present_profiles_only() -> None:
    out = list_example_profiles()
    assert isinstance(out, list)
    for entry in out:
        assert "id" in entry
        assert "filename" in entry
        assert isinstance(entry["size_bytes"], int)


def test_get_example_profile_unknown_id_raises() -> None:
    with pytest.raises(ResourceNotFoundError) as exc:
        get_example_profile("not_a_profile_xyz")
    assert "unknown profile" in str(exc.value)


def test_get_example_profile_returns_payload_when_present() -> None:
    out = list_example_profiles()
    if not out:
        pytest.skip("no example profiles on disk in this env")
    pid = out[0]["id"]
    payload = get_example_profile(pid)
    assert payload["id"] == pid
    assert "profile" in payload
    assert payload["purpose"]
    assert payload["license"]


def test_load_json_caches_same_path_idempotently() -> None:
    # _load_json is lru_cache'd — two reads of the same path return the same object.
    out = list_static_resources()
    if not out:
        pytest.skip("no static resources on disk in this env")
    rid = out[0]["id"]
    # Trigger via the public helper twice — proves cache path is exercised.
    a = get_static_resource(rid)["data"]
    b = get_static_resource(rid)["data"]
    assert a is b


def test_load_json_directly_returns_parsed_object() -> None:
    out = list_static_resources()
    if not out:
        pytest.skip("no static resources on disk in this env")
    rid = out[0]["id"]
    # Recompute the path the same way get_static_resource does.
    from jpintel_mcp.mcp.autonomath_tools.static_resources import (
        _STATIC_RESOURCES,
    )

    path = STATIC_DIR / _STATIC_RESOURCES[rid]
    parsed = _load_json(path)
    # JSON files in this repo are dicts or lists.
    assert isinstance(parsed, (dict, list))


# ---------------------------------------------------------------------------
# Smoke imports — get coverage credit for module-level gating + constants.
# ---------------------------------------------------------------------------


def test_health_tool_module_imports_and_exposes_callable() -> None:
    from jpintel_mcp.mcp.autonomath_tools import health_tool

    assert hasattr(health_tool, "deep_health_am")


def test_template_tool_module_imports_without_error() -> None:
    # template_tool is gated on settings.saburoku_kyotei_enabled. Import path
    # must always succeed; tool surface differs but module body always executes.
    from jpintel_mcp.mcp.autonomath_tools import template_tool

    assert template_tool._DRAFT_DISCLAIMER  # noqa: SLF001


def test_tools_envelope_module_exposes_wrapped_tool_names() -> None:
    from jpintel_mcp.mcp.autonomath_tools.tools_envelope import (
        WRAPPED_TOOL_NAMES,
    )

    # All 10 wave-3 wrapped tool names are present.
    assert len(WRAPPED_TOOL_NAMES) == 10
    assert "search_tax_incentives" in WRAPPED_TOOL_NAMES
    assert "reason_answer" in WRAPPED_TOOL_NAMES
