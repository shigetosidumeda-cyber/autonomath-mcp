"""DB-fixture-based coverage push for ``src/jpintel_mcp/api/main.py``.

Stream LL 2026-05-16 — push coverage 85% → 90% via tmp_path-backed minimal
schemas. NO touch of the 9.7 GB production autonomath.db (memory:
``feedback_no_quick_check_on_huge_sqlite``). Pure-helper paths only —
every test in this file imports ``jpintel_mcp.api.main`` once and exercises
private helpers without booting the FastAPI app.

Targets (lines 296-302 / 316-344 / 829-852 / 1369-1461 / 421 / 478-567):
  * ``_params_shape`` over a synthetic ``Request`` instance.
  * ``_emit_query_log`` — happy path + redact_pii branch.
  * ``_audit_seal_rotation_keys`` — JSON / CSV / dict shapes.
  * ``_assert_audit_seal_value`` — placeholder + short reject.
  * ``_resolve_mcp_server_manifest_path`` over tmp_path env.
  * ``_normalize_openapi_component_schema_names`` over synthetic schema.
  * ``_rewrite_openapi_component_refs`` deep walk.
  * ``_sanitize_openapi_public_text`` regex rewrites.
  * ``_prune_openapi_public_paths`` removes hidden paths.
  * ``_walk_openapi_leak_strings_runtime`` recursion + exempt key.

Constraints (memory: ``feedback_no_quick_check_on_huge_sqlite``):
  * tmp_path-only, never touch /Users/shigetoumeda/jpcite/autonomath.db.
  * No source change, no fixture mutation outside this file.
  * No LLM calls (memory: ``feedback_autonomath_no_api_use``).
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

import jpintel_mcp.api.main as M

# ---------------------------------------------------------------------------
# Tmp_path minimal schema (synthetic mcp-server.json for manifest resolver)
# ---------------------------------------------------------------------------


@pytest.fixture()
def tmp_manifest(tmp_path: Path) -> Path:
    """Write a tiny mcp-server.json into tmp_path for manifest resolution."""
    p = tmp_path / "mcp-server.json"
    p.write_text(
        json.dumps({"name": "test", "version": "0.0.0", "servers": []}),
        encoding="utf-8",
    )
    return p


@pytest.fixture()
def tmp_sqlite_db(tmp_path: Path) -> Path:
    """Empty sqlite file for tests that ONLY need a real file path (not data)."""
    db = tmp_path / "fixture.db"
    conn = sqlite3.connect(db)
    # Minimal seed so the file exists and is non-zero.
    conn.executescript("CREATE TABLE _probe (id INTEGER PRIMARY KEY);")
    conn.commit()
    conn.close()
    return db


# ---------------------------------------------------------------------------
# _resolve_mcp_server_manifest_path — env_path / cwd / parents[3]
# ---------------------------------------------------------------------------


def test_resolve_mcp_server_manifest_path_env_var(
    tmp_manifest: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MCP_SERVER_MANIFEST_PATH", str(tmp_manifest))
    out = M._resolve_mcp_server_manifest_path()
    assert out is not None
    assert out.resolve() == tmp_manifest.resolve()


def test_resolve_mcp_server_manifest_path_env_var_missing_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Env var points to a non-existent file; resolver should fall through
    # to other candidates (it may find the real repo's manifest or return
    # None — either way it MUST NOT crash).
    monkeypatch.setenv("MCP_SERVER_MANIFEST_PATH", str(tmp_path / "missing.json"))
    out = M._resolve_mcp_server_manifest_path()
    assert out is None or isinstance(out, Path)


# ---------------------------------------------------------------------------
# _params_shape — synthesises a Request without HTTP I/O
# ---------------------------------------------------------------------------


class _FakeQueryParams:
    def __init__(self, mapping: dict[str, str]) -> None:
        self._m = mapping

    def __iter__(self) -> Any:
        return iter(self._m)

    def get(self, key: str, default: Any = None) -> Any:
        return self._m.get(key, default)


class _FakeRequest:
    def __init__(self, params: dict[str, str]) -> None:
        self.query_params = _FakeQueryParams(params)


def test_params_shape_empty_returns_empty_dict() -> None:
    out = M._params_shape(_FakeRequest({}))
    assert out == {}


def test_params_shape_keys_marked_true_no_values() -> None:
    out = M._params_shape(_FakeRequest({"limit": "10", "offset": "0"}))
    assert out == {"limit": True, "offset": True}


def test_params_shape_q_adds_len_and_lang() -> None:
    out = M._params_shape(_FakeRequest({"q": "補助金税額控除"}))
    assert out["q"] is True
    assert out["q_len"] == len("補助金税額控除")
    assert out["q_lang"] == "ja"


# ---------------------------------------------------------------------------
# _emit_query_log — happy + redact branch — should never raise
# ---------------------------------------------------------------------------


def test_emit_query_log_happy_path_returns_none(caplog: pytest.LogCaptureFixture) -> None:
    # Function emits a JSON log line through 'autonomath.query' and returns None.
    out = M._emit_query_log(
        channel="rest",
        endpoint="/v1/programs/search",
        params_shape={"q": True, "limit": True},
        result_count=5,
        latency_ms=42,
        status=200,
        error_class=None,
        request_id="01KR0Q-test",
    )
    assert out is None


def test_emit_query_log_swallow_exception_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # If the underlying logger raises, the function must swallow + return.
    def _explode(*a: Any, **kw: Any) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(M._query_log, "info", _explode)
    out = M._emit_query_log(
        channel="rest",
        endpoint="/v1/programs/search",
        params_shape={"x": True},
        result_count=0,
        latency_ms=0,
        status="error",
        error_class="RuntimeError",
    )
    assert out is None


# ---------------------------------------------------------------------------
# _audit_seal_rotation_keys — JSON list / dict / CSV
# ---------------------------------------------------------------------------


def test_audit_seal_rotation_keys_empty_returns_empty() -> None:
    assert M._audit_seal_rotation_keys("") == []
    assert M._audit_seal_rotation_keys("   ") == []


def test_audit_seal_rotation_keys_csv_split() -> None:
    out = M._audit_seal_rotation_keys("aaa,bbb, ccc ")
    assert out == ["aaa", "bbb", "ccc"]


def test_audit_seal_rotation_keys_json_list_passthrough() -> None:
    out = M._audit_seal_rotation_keys(json.dumps(["k1", "k2"]))
    assert out == ["k1", "k2"]


def test_audit_seal_rotation_keys_json_dict_wrapped_as_list() -> None:
    out = M._audit_seal_rotation_keys(json.dumps({"s": "secret-32-bytes-padding-padding"}))
    assert out == ["secret-32-bytes-padding-padding"]


def test_audit_seal_rotation_keys_json_list_of_dicts() -> None:
    out = M._audit_seal_rotation_keys(json.dumps([{"s": "v1"}, {"s": "v2"}]))
    assert out == ["v1", "v2"]


def test_audit_seal_rotation_keys_malformed_json_raises_systemexit() -> None:
    with pytest.raises(SystemExit):
        M._audit_seal_rotation_keys("[not valid json")


# ---------------------------------------------------------------------------
# _assert_audit_seal_value — forbidden placeholder + length gate
# ---------------------------------------------------------------------------


def test_assert_audit_seal_value_forbidden_placeholder_systemexit() -> None:
    with pytest.raises(SystemExit) as excinfo:
        M._assert_audit_seal_value("X", "dev-audit-seal-salt")
    assert "BOOT FAIL" in str(excinfo.value)


def test_assert_audit_seal_value_short_value_systemexit() -> None:
    with pytest.raises(SystemExit):
        M._assert_audit_seal_value("X", "too-short")


def test_assert_audit_seal_value_long_value_passes() -> None:
    M._assert_audit_seal_value("X", "a" * 40)


# ---------------------------------------------------------------------------
# _camelize_component_part / _public_component_schema_name — additional cov
# ---------------------------------------------------------------------------


def test_public_component_schema_name_non_jpintel_passthrough() -> None:
    out = M._public_component_schema_name("PlainName")
    assert out == "PlainName"


def test_public_component_schema_name_jpintel_split_assemble() -> None:
    out = M._public_component_schema_name("jpintel_mcp__api__programs__SearchResult")
    # Module parts squashed: "programs" (last 2 after dropping reserved words)
    # so the public name carries a CamelCased prefix + tail.
    assert out.endswith("SearchResult")
    assert "_" not in out


# ---------------------------------------------------------------------------
# _normalize_openapi_component_schema_names — full rename round trip
# ---------------------------------------------------------------------------


def test_normalize_openapi_component_schema_names_basic_rename() -> None:
    schema: dict[str, Any] = {
        "components": {
            "schemas": {
                "jpintel_mcp__api__programs__SearchResult": {"type": "object"},
                "PlainName": {"type": "string"},
            }
        },
        "paths": {
            "/v1/x": {
                "get": {
                    "responses": {
                        "200": {
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "$ref": (
                                            "#/components/schemas/"
                                            "jpintel_mcp__api__programs__SearchResult"
                                        )
                                    }
                                }
                            }
                        }
                    }
                }
            }
        },
    }
    M._normalize_openapi_component_schema_names(schema)
    schemas = schema["components"]["schemas"]
    # The legacy long key should have been renamed to a Camel public name.
    assert "jpintel_mcp__api__programs__SearchResult" not in schemas
    # The $ref should have been rewritten to the new name.
    ref = schema["paths"]["/v1/x"]["get"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]["$ref"]
    assert ref.startswith("#/components/schemas/")
    assert "jpintel_mcp__" not in ref


def test_normalize_openapi_component_schema_names_no_components_noop() -> None:
    # When `components` is absent the function must be a no-op (not crash).
    schema = {"paths": {}}
    M._normalize_openapi_component_schema_names(schema)
    assert schema == {"paths": {}}


def test_normalize_openapi_component_schema_names_no_schemas_noop() -> None:
    schema: dict[str, Any] = {"components": {}}
    M._normalize_openapi_component_schema_names(schema)
    assert schema == {"components": {}}


# ---------------------------------------------------------------------------
# _rewrite_openapi_component_refs — leaf rewrite + nested list / dict
# ---------------------------------------------------------------------------


def test_rewrite_openapi_component_refs_dict_leaf() -> None:
    node: dict[str, Any] = {
        "$ref": "#/components/schemas/OldName",
        "child": {"$ref": "#/components/schemas/Other"},
    }
    M._rewrite_openapi_component_refs(node, {"OldName": "NewName"})
    assert node["$ref"] == "#/components/schemas/NewName"
    # `Other` is not in the rename map so it stays put.
    assert node["child"]["$ref"] == "#/components/schemas/Other"


def test_rewrite_openapi_component_refs_in_list() -> None:
    node = [
        {"$ref": "#/components/schemas/A"},
        {"items": {"$ref": "#/components/schemas/A"}},
    ]
    M._rewrite_openapi_component_refs(node, {"A": "B"})
    assert node[0]["$ref"] == "#/components/schemas/B"
    assert node[1]["items"]["$ref"] == "#/components/schemas/B"


# ---------------------------------------------------------------------------
# _sanitize_openapi_public_text — multi-pattern rewrite
# ---------------------------------------------------------------------------


def test_sanitize_openapi_public_text_billing_event_rewrite() -> None:
    text = "Stripe webhook endpoint. Persist signed event."
    out = M._sanitize_openapi_public_text(text)
    assert out == "Billing event endpoint."


def test_sanitize_openapi_public_text_passthrough_unrelated() -> None:
    text = "Plain search endpoint description."
    out = M._sanitize_openapi_public_text(text)
    assert out == text


def test_sanitize_openapi_public_text_operator_token_rewrite() -> None:
    text = "info@bookyou.net and Bookyou株式会社 and T8010001213708"
    out = M._sanitize_openapi_public_text(text)
    assert "info@bookyou.net" not in out
    assert "Bookyou株式会社" not in out
    assert "T8010001213708" not in out


def test_sanitize_openapi_public_text_db_rename() -> None:
    text = "Read jpintel.db then autonomath.db then SQLite."
    out = M._sanitize_openapi_public_text(text)
    assert "jpintel.db" not in out
    assert "autonomath.db" not in out
    assert "SQLite" not in out


# ---------------------------------------------------------------------------
# _prune_openapi_public_paths — removes hidden paths
# ---------------------------------------------------------------------------


def test_prune_openapi_public_paths_removes_billing_webhook() -> None:
    schema = {
        "paths": {
            "/v1/billing/webhook": {"get": {}},
            "/v1/programs/search": {"get": {}},
        }
    }
    M._prune_openapi_public_paths(schema)
    assert "/v1/billing/webhook" not in schema["paths"]
    assert "/v1/programs/search" in schema["paths"]


def test_prune_openapi_public_paths_missing_paths_noop() -> None:
    schema: dict[str, Any] = {"components": {}}
    M._prune_openapi_public_paths(schema)
    assert "paths" not in schema


# ---------------------------------------------------------------------------
# _walk_openapi_leak_strings_runtime — exempt key freezes subtree
# ---------------------------------------------------------------------------


def test_walk_openapi_leak_strings_runtime_recursion() -> None:
    # The runtime walker rewrites table-name leaks (am_*/jpi_*/jpintel.db
    # /autonomath.db) and Wave/migration markers; it leaves operator
    # identity markers to the public-schema sanitiser.
    node: dict[str, Any] = {
        "info": {"description": "Read am_entities from jpintel.db"},
        "items": [{"description": "See migration 087 in scripts/migrations/087_foo.sql"}],
    }
    M._walk_openapi_leak_strings_runtime(node)
    serialized = json.dumps(node, ensure_ascii=False)
    assert "am_entities" not in serialized
    assert "jpintel.db" not in serialized
    assert "scripts/migrations/" not in serialized


def test_walk_openapi_leak_strings_runtime_exempt_key_subtree() -> None:
    # Exempt keys must NOT rewrite (default / example are byte-identical to
    # runtime echoes — protected by the runtime walker contract).
    node: dict[str, Any] = {
        "default": "am_entities sample",
        "example": "jpintel.db stays",
        "operationId": "search_am_entities",
    }
    M._walk_openapi_leak_strings_runtime(node)
    assert node["default"] == "am_entities sample"
    assert node["example"] == "jpintel.db stays"
    assert node["operationId"] == "search_am_entities"


# ---------------------------------------------------------------------------
# _env_truthy edge cases (negative / mixed-case)
# ---------------------------------------------------------------------------


def test_env_truthy_handles_whitespace_around_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("__JP_MAIN_TEST_FLAG_LL__", "  TRUE  ")
    assert M._env_truthy("__JP_MAIN_TEST_FLAG_LL__") is True


def test_env_truthy_disallowed_word_returns_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("__JP_MAIN_TEST_FLAG_LL__", "maybe")
    assert M._env_truthy("__JP_MAIN_TEST_FLAG_LL__") is False
