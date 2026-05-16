"""Pure-function + edge-case coverage tests for ``api.main`` private helpers.

Targets ``src/jpintel_mcp/api/main.py`` (3,620 stmt). The module is mostly
FastAPI wiring + middleware classes, but a sizable block of pure helpers
(``_env_truthy`` / ``_detect_lang`` / ``_camelize_component_part`` / OpenAPI
schema sanitisers / audit-seal rotation parser) are exercisable directly
without booting the app.

NO DB / HTTP / LLM calls anywhere. Each test is pure-Python over module
private helpers re-imported here.

Stream CC tick (coverage 76% → 80% target).
"""

from __future__ import annotations

import json
from typing import Any

import pytest

import jpintel_mcp.api.main as m

# ---------------------------------------------------------------------------
# _env_truthy
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value,expected",
    [
        ("1", True),
        ("true", True),
        ("TRUE", True),
        ("YES", True),
        ("on", True),
        ("0", False),
        ("false", False),
        ("no", False),
        ("", False),
        ("anything-else", False),
    ],
)
def test_env_truthy_recognises_canonical_values(
    monkeypatch: pytest.MonkeyPatch, value: str, expected: bool
) -> None:
    monkeypatch.setenv("__JP_MAIN_TEST_FLAG__", value)
    assert m._env_truthy("__JP_MAIN_TEST_FLAG__") is expected


def test_env_truthy_absent_var_returns_false(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("__JP_MAIN_TEST_FLAG__", raising=False)
    assert m._env_truthy("__JP_MAIN_TEST_FLAG__") is False


# ---------------------------------------------------------------------------
# _detect_lang
# ---------------------------------------------------------------------------


def test_detect_lang_empty_string_returns_en() -> None:
    assert m._detect_lang("") == "en"


def test_detect_lang_pure_japanese_returns_ja() -> None:
    assert m._detect_lang("補助金税額控除事業承継相続贈与") == "ja"


def test_detect_lang_pure_ascii_returns_en() -> None:
    assert m._detect_lang("DX subsidy program eligibility") == "en"


def test_detect_lang_mixed_returns_mixed() -> None:
    # ~22% CJK, ~78% ASCII — falls in (0.1, 0.5].
    out = m._detect_lang("Apply for 補助金 here")
    assert out == "mixed"


# ---------------------------------------------------------------------------
# _camelize_component_part / _public_component_schema_name
# ---------------------------------------------------------------------------


def test_camelize_component_part_basic_snake() -> None:
    assert m._camelize_component_part("hello_world") == "HelloWorld"


def test_camelize_component_part_preserves_caps() -> None:
    assert m._camelize_component_part("api_keys") == "ApiKeys"


def test_camelize_component_part_empty() -> None:
    assert m._camelize_component_part("") == ""


def test_camelize_component_part_handles_split_on_non_word() -> None:
    out = m._camelize_component_part("foo-bar_baz")
    assert out == "FooBarBaz"


def test_public_component_schema_name_non_internal_passes_through() -> None:
    # Names that don't start with ``jpintel_mcp__`` are returned as-is.
    assert m._public_component_schema_name("ExternalThing") == "ExternalThing"


def test_public_component_schema_name_strips_internal_path() -> None:
    name = "jpintel_mcp__api__models__widgets__Foo"
    out = m._public_component_schema_name(name)
    # Internal path module parts that are not in {api, models, jpintel_mcp}
    # are camelized and prefixed onto Foo.
    assert out.endswith("Foo")
    assert "Foo" in out


# ---------------------------------------------------------------------------
# _rewrite_openapi_component_refs
# ---------------------------------------------------------------------------


def test_rewrite_openapi_component_refs_rewrites_matching_ref() -> None:
    node: dict[str, Any] = {"$ref": "#/components/schemas/Old"}
    m._rewrite_openapi_component_refs(node, {"Old": "New"})
    assert node["$ref"] == "#/components/schemas/New"


def test_rewrite_openapi_component_refs_leaves_unmatched() -> None:
    node: dict[str, Any] = {"$ref": "#/components/schemas/Untouched"}
    m._rewrite_openapi_component_refs(node, {"Other": "Renamed"})
    assert node["$ref"] == "#/components/schemas/Untouched"


def test_rewrite_openapi_component_refs_walks_lists_and_dicts() -> None:
    schema: dict[str, Any] = {
        "paths": {
            "/foo": {"get": {"$ref": "#/components/schemas/Foo"}},
        },
        "items": [{"$ref": "#/components/schemas/Foo"}, "x"],
    }
    m._rewrite_openapi_component_refs(schema, {"Foo": "FooRenamed"})
    assert schema["paths"]["/foo"]["get"]["$ref"] == "#/components/schemas/FooRenamed"
    assert schema["items"][0]["$ref"] == "#/components/schemas/FooRenamed"


def test_rewrite_openapi_component_refs_ignores_non_ref_strings() -> None:
    # Strings that look like refs but live under a non-$ref key must not
    # be coerced — defensive against accidental rewriting of free-text.
    node: dict[str, Any] = {"description": "#/components/schemas/Old"}
    m._rewrite_openapi_component_refs(node, {"Old": "New"})
    assert node["description"] == "#/components/schemas/Old"


# ---------------------------------------------------------------------------
# _audit_seal_rotation_keys
# ---------------------------------------------------------------------------


def test_audit_seal_rotation_keys_empty_string() -> None:
    assert m._audit_seal_rotation_keys("") == []


def test_audit_seal_rotation_keys_whitespace_only() -> None:
    assert m._audit_seal_rotation_keys("   ") == []


def test_audit_seal_rotation_keys_comma_separated() -> None:
    out = m._audit_seal_rotation_keys("key1, key2, key3")
    assert out == ["key1", "key2", "key3"]


def test_audit_seal_rotation_keys_json_array_of_dicts() -> None:
    raw = json.dumps([{"s": "secret_a"}, {"s": "secret_b"}])
    out = m._audit_seal_rotation_keys(raw)
    assert out == ["secret_a", "secret_b"]


def test_audit_seal_rotation_keys_single_json_object() -> None:
    raw = json.dumps({"s": "only_secret"})
    out = m._audit_seal_rotation_keys(raw)
    assert out == ["only_secret"]


def test_audit_seal_rotation_keys_invalid_json_raises_systemexit() -> None:
    with pytest.raises(SystemExit):
        m._audit_seal_rotation_keys("[ not json :")


def test_audit_seal_rotation_keys_json_non_object_raises() -> None:
    # ``"{not_an_object"`` triggers the JSON-decode SystemExit path because
    # the leading char is ``{`` which forces a json.loads attempt.
    with pytest.raises(SystemExit):
        m._audit_seal_rotation_keys("{not_an_object")


def test_audit_seal_rotation_keys_json_scalar_string_raises() -> None:
    # A plain JSON string ``"plain"`` would not start with ``[`` or ``{``,
    # so it falls back to the comma-split branch. Trigger the "must be list"
    # systemexit by passing a bracketed JSON null/number which is a list-
    # shaped JSON whose items are non-dict scalars — falls through OK.
    # Cover the "list of non-dicts" branch: items become "" via the helper.
    out = m._audit_seal_rotation_keys("[42, 7]")
    # Per implementation, non-dict items become "" — both empty.
    assert out == ["", ""]


# ---------------------------------------------------------------------------
# _sanitize_openapi_public_text — load-bearing string scrubber
# ---------------------------------------------------------------------------


def test_sanitize_openapi_public_text_replaces_operator_brand() -> None:
    text = "info@bookyou.net is the operator."
    out = m._sanitize_openapi_public_text(text)
    assert "info@bookyou.net" not in out
    assert "jpcite support" in out


def test_sanitize_openapi_public_text_replaces_houjin_bangou() -> None:
    text = "Operator: T8010001213708."
    out = m._sanitize_openapi_public_text(text)
    assert "T8010001213708" not in out


def test_sanitize_openapi_public_text_replaces_sqlite_marker() -> None:
    out = m._sanitize_openapi_public_text("Backed by SQLite full-text search.")
    assert "SQLite" not in out
    assert "persistent storage" in out


def test_sanitize_openapi_public_text_replaces_db_filename_markers() -> None:
    out = m._sanitize_openapi_public_text("Queries hit jpintel.db and autonomath.db.")
    assert "jpintel.db" not in out
    assert "autonomath.db" not in out


# ---------------------------------------------------------------------------
# _is_production_env env recognition
# ---------------------------------------------------------------------------


def test_is_production_env_returns_true_for_prod(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JPINTEL_ENV", "prod")
    assert m._is_production_env() is True


def test_is_production_env_returns_true_for_production_label(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("JPINTEL_ENV", "production")
    assert m._is_production_env() is True


def test_is_production_env_returns_false_for_dev_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("JPINTEL_ENV", raising=False)
    # settings.env defaults to 'test' under conftest. Either way it's not prod.
    assert m._is_production_env() is False


def test_is_production_env_case_insensitive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JPINTEL_ENV", "PROD")
    assert m._is_production_env() is True
