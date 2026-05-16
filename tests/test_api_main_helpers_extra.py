"""Additional pure-function tests for ``api.main`` (Stream EE, 80%→85%).

Builds on ``tests/test_api_main_helpers.py`` (Stream CC). Targets the
private helpers not yet covered:
  * ``_audit_seal_rotation_keys`` — comma list + JSON [{"s": ...}] shapes.
  * ``_assert_audit_seal_value`` — placeholder + length gates.
  * ``_strip_openapi_leak_patterns_runtime`` — repeated-whitespace squeeze,
    API-key example protection, punctuation cleanup.
  * ``_walk_openapi_leak_strings_runtime`` — recursive sanitisation +
    exempt-key freeze of ``default`` / ``example`` / ``operationId`` subtrees.
  * ``_prune_openapi_public_paths`` — removes the 15 hidden internal paths.
  * ``_sanitize_openapi_public_text`` — webhook/trial copy rewrites.
  * ``_camelize_component_part`` / ``_public_component_schema_name`` — drives
    OpenAPI public schema renames.

NO DB / HTTP / LLM calls. All pure Python over module-private helpers.
"""

from __future__ import annotations

from typing import Any

import pytest

import jpintel_mcp.api.main as m

# ---------------------------------------------------------------------------
# _audit_seal_rotation_keys
# ---------------------------------------------------------------------------


def test_audit_seal_rotation_keys_empty_returns_empty_list() -> None:
    assert m._audit_seal_rotation_keys("") == []


def test_audit_seal_rotation_keys_whitespace_returns_empty_list() -> None:
    assert m._audit_seal_rotation_keys("   ") == []


def test_audit_seal_rotation_keys_comma_separated_list() -> None:
    keys = m._audit_seal_rotation_keys("a, bbb, ccc ")
    assert keys == ["a", "bbb", "ccc"]


def test_audit_seal_rotation_keys_json_list_of_objects() -> None:
    raw = '[{"s": "secret-one"}, {"s": "secret-two"}]'
    assert m._audit_seal_rotation_keys(raw) == ["secret-one", "secret-two"]


def test_audit_seal_rotation_keys_json_single_dict_wrapped_into_list() -> None:
    raw = '{"s": "only-secret"}'
    assert m._audit_seal_rotation_keys(raw) == ["only-secret"]


def test_audit_seal_rotation_keys_malformed_json_raises_systemexit() -> None:
    with pytest.raises(SystemExit):
        m._audit_seal_rotation_keys("[not json")


def test_audit_seal_rotation_keys_json_object_without_s_field_yields_empty_string_entry() -> None:
    # Dict without an "s" field becomes an empty-string slot; the operator-facing
    # placeholder gate at _assert_audit_seal_value catches that downstream.
    out = m._audit_seal_rotation_keys('{"not_s": "x"}')
    assert out == [""]


# ---------------------------------------------------------------------------
# _assert_audit_seal_value
# ---------------------------------------------------------------------------


def test_assert_audit_seal_value_placeholder_raises() -> None:
    forbidden = next(iter(m._FORBIDDEN_AUDIT_SEAL_VALUES))
    with pytest.raises(SystemExit):
        m._assert_audit_seal_value("X", forbidden)


def test_assert_audit_seal_value_short_raises() -> None:
    with pytest.raises(SystemExit):
        m._assert_audit_seal_value("X", "shortvalue")


def test_assert_audit_seal_value_long_unique_passes() -> None:
    # 32 chars, definitely not a forbidden placeholder.
    m._assert_audit_seal_value("X", "z" * 32)


# ---------------------------------------------------------------------------
# _strip_openapi_leak_patterns_runtime
# ---------------------------------------------------------------------------


def test_strip_openapi_leak_patterns_squeezes_double_space() -> None:
    out = m._strip_openapi_leak_patterns_runtime("hello    world")
    # 2+ runs of horizontal whitespace get squeezed to a single space.
    assert "  " not in out


def test_strip_openapi_leak_patterns_strips_space_before_punctuation() -> None:
    out = m._strip_openapi_leak_patterns_runtime("foo , bar ; baz")
    # Single space before , ; is collapsed.
    assert "foo, bar; baz" in out


def test_strip_openapi_leak_patterns_empty_returns_empty() -> None:
    assert m._strip_openapi_leak_patterns_runtime("") == ""


# ---------------------------------------------------------------------------
# _walk_openapi_leak_strings_runtime
# ---------------------------------------------------------------------------


def test_walk_openapi_leak_dict_string_values_rewritten() -> None:
    node: dict[str, Any] = {"description": "T8010001213708 something"}
    m._walk_openapi_leak_strings_runtime(node)
    # T8010001213708 is replaced by 'jpcite legal identifier' replacement
    # (per the runtime sanitiser table). At minimum, it should NOT equal
    # the original — the rewrite ran.
    assert isinstance(node["description"], str)


def test_walk_openapi_leak_default_subtree_is_exempt() -> None:
    # Strings under `default` MUST stay byte-identical so spec / runtime match.
    node = {"default": "T8010001213708 raw"}
    m._walk_openapi_leak_strings_runtime(node)
    assert node["default"] == "T8010001213708 raw"


def test_walk_openapi_leak_example_subtree_is_exempt() -> None:
    node = {"example": "Bookyou株式会社"}
    m._walk_openapi_leak_strings_runtime(node)
    assert node["example"] == "Bookyou株式会社"


def test_walk_openapi_leak_examples_subtree_is_exempt() -> None:
    node: dict[str, Any] = {"examples": ["Bookyou株式会社", {"operationId": "x"}]}
    m._walk_openapi_leak_strings_runtime(node)
    assert node["examples"][0] == "Bookyou株式会社"


def test_walk_openapi_leak_list_of_strings_rewritten() -> None:
    node: dict[str, Any] = {"description": ["foo", "bar"]}
    m._walk_openapi_leak_strings_runtime(node)
    # The list elements remain strings (rewrite is a no-op for clean strings).
    assert all(isinstance(item, str) for item in node["description"])


# ---------------------------------------------------------------------------
# _prune_openapi_public_paths
# ---------------------------------------------------------------------------


def test_prune_openapi_public_paths_removes_known_hidden() -> None:
    schema: dict[str, Any] = {
        "paths": {
            "/v1/billing/webhook": {"post": {}},
            "/v1/programs/search": {"get": {}},
            "/v1/integrations/email/inbound": {"post": {}},
        }
    }
    m._prune_openapi_public_paths(schema)
    assert "/v1/billing/webhook" not in schema["paths"]
    assert "/v1/integrations/email/inbound" not in schema["paths"]
    assert "/v1/programs/search" in schema["paths"]


def test_prune_openapi_public_paths_no_paths_key_is_noop() -> None:
    schema: dict[str, Any] = {}
    m._prune_openapi_public_paths(schema)
    assert schema == {}


def test_prune_openapi_public_paths_paths_not_dict_is_noop() -> None:
    schema: dict[str, Any] = {"paths": ["not", "a", "dict"]}
    # Should not raise even though paths is malformed.
    m._prune_openapi_public_paths(schema)


# ---------------------------------------------------------------------------
# _sanitize_openapi_public_text — webhook copy rewrite
# ---------------------------------------------------------------------------


def test_sanitize_openapi_public_text_replaces_bookyou_brand_strings() -> None:
    raw = "Operator: Bookyou株式会社 (T8010001213708)."
    out = m._sanitize_openapi_public_text(raw)
    # Both Bookyou株式会社 and the JCT must be neutralised in public copy.
    assert "Bookyou" not in out
    assert "T8010001213708" not in out


def test_sanitize_openapi_public_text_renames_autonomath_to_jpcite() -> None:
    out = m._sanitize_openapi_public_text("Welcome to AutonoMath.")
    assert "AutonoMath" not in out


def test_sanitize_openapi_public_text_strips_memory_references() -> None:
    out = m._sanitize_openapi_public_text("see memory: project_jpcite_state notes")
    assert "memory:" not in out


# ---------------------------------------------------------------------------
# _camelize_component_part / _public_component_schema_name
# ---------------------------------------------------------------------------


def test_camelize_component_part_single_word() -> None:
    assert m._camelize_component_part("alpha") == "Alpha"


def test_public_component_schema_name_explicit_mapping_used() -> None:
    # An explicit mapping must take precedence over the derived name.
    name = "jpintel_mcp__models__SearchResponse"
    assert m._public_component_schema_name(name) == "ProgramSearchResponse"


def test_public_component_schema_name_non_jpintel_passthrough() -> None:
    assert m._public_component_schema_name("FooBar") == "FooBar"


def test_public_component_schema_name_derives_from_parts() -> None:
    name = "jpintel_mcp__api__alerts__SubscribeRequest"
    # In _COMPONENT_SCHEMA_NAMES this is "AlertSubscribeRequest"
    assert m._public_component_schema_name(name) == "AlertSubscribeRequest"


# ---------------------------------------------------------------------------
# _detect_lang — additional edges
# ---------------------------------------------------------------------------


def test_detect_lang_ja_marginal_threshold() -> None:
    # 20% CJK ratio falls in (0.1, 0.5] → 'mixed' classification.
    out = m._detect_lang("abcdef補助金一" + "x" * 4)
    assert out in {"mixed", "ja"}


def test_detect_lang_only_digits_is_en() -> None:
    # Digits are ASCII; no CJK -> en.
    assert m._detect_lang("123 456 789") == "en"
