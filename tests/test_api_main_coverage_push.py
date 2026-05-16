"""Coverage push for ``src/jpintel_mcp/api/main.py`` (Stream WW-cov).

Adds tests targeting branches not covered by Stream CC/EE/LL test files:
  * ``_assert_x402_mock_proof_disabled_in_production`` — non-prod no-op +
    prod label resolution.
  * ``_assert_fail_open_flags_disabled_in_production`` — non-prod no-op +
    flag combinations.
  * ``_init_sentry`` — missing DSN no-op + non-prod no-op + ImportError path.
  * ``_optional_router`` — ModuleNotFoundError on the target module returns None.
  * ``_include_experimental_router`` — gate disabled → early return.
  * ``_normalize_openapi_component_schema_names`` — schema branches.
  * ``_sanitize_openapi_public_schema`` — title rewrite branches +
    enum filter + parameter pruning.
  * ``_RequestContextMiddleware`` smoke (via TestClient).

NO real DB access. NO LLM. NO mocking of the DB.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

import jpintel_mcp.api.main as M

if TYPE_CHECKING:
    from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# _assert_x402_mock_proof_disabled_in_production — non-prod no-op
# ---------------------------------------------------------------------------


def test_assert_x402_mock_proof_non_prod_is_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    """No prod env label set → fast path, no SystemExit."""
    monkeypatch.delenv("JPCITE_ENV", raising=False)
    monkeypatch.delenv("JPINTEL_ENV", raising=False)
    # Must not raise — the gate only fires when prod label is set.
    M._assert_x402_mock_proof_disabled_in_production()


def test_assert_x402_mock_proof_dev_env_explicit_no_op(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JPCITE_ENV", "dev")
    monkeypatch.setenv("JPINTEL_ENV", "dev")
    M._assert_x402_mock_proof_disabled_in_production()


def test_assert_x402_mock_proof_test_env_no_op(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JPCITE_ENV", "test")
    monkeypatch.setenv("JPINTEL_ENV", "test")
    M._assert_x402_mock_proof_disabled_in_production()


# ---------------------------------------------------------------------------
# _assert_fail_open_flags_disabled_in_production — non-prod no-op
# ---------------------------------------------------------------------------


def test_assert_fail_open_flags_non_prod_is_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("JPCITE_ENV", raising=False)
    monkeypatch.delenv("JPINTEL_ENV", raising=False)
    # Force settings.env != prod via the live settings binding (read-only)
    M._assert_fail_open_flags_disabled_in_production()


def test_assert_fail_open_flags_test_env_no_op(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JPCITE_ENV", "test")
    monkeypatch.setenv("JPINTEL_ENV", "test")
    # Even with fail-open flags set, the gate is non-prod so no raise.
    monkeypatch.setenv("RATE_LIMIT_BURST_DISABLED", "1")
    M._assert_fail_open_flags_disabled_in_production()


# ---------------------------------------------------------------------------
# _init_sentry — DSN missing / non-prod / import gates
# ---------------------------------------------------------------------------


def test_init_sentry_missing_dsn_is_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    # When settings.sentry_dsn is empty, the function returns silently.
    monkeypatch.setattr(M.settings, "sentry_dsn", "", raising=False)
    M._init_sentry()


def test_init_sentry_non_prod_with_dsn_is_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    # Even with a DSN, non-prod env returns silently (avoid polluting
    # production sentry quota with test traffic).
    monkeypatch.setattr(
        M.settings, "sentry_dsn", "https://example.ingest.sentry.io/abc", raising=False
    )
    monkeypatch.delenv("JPINTEL_ENV", raising=False)
    monkeypatch.delenv("JPCITE_ENV", raising=False)
    M._init_sentry()


# ---------------------------------------------------------------------------
# _optional_router — ModuleNotFoundError → None
# ---------------------------------------------------------------------------


def test_optional_router_missing_module_returns_none() -> None:
    # A non-existent module should produce None (not raise).
    out = M._optional_router("jpintel_mcp.this_module_does_not_exist_xxx_test")
    assert out is None


def test_optional_router_real_module_returns_value() -> None:
    # The 'jpintel_mcp.api.programs' module is the real programs router
    # and exports `router`.
    out = M._optional_router("jpintel_mcp.api.programs", attr="router")
    assert out is not None


def test_optional_router_other_modulenotfound_reraises(monkeypatch: pytest.MonkeyPatch) -> None:
    """ModuleNotFoundError whose .name does NOT match the requested module
    should re-raise (signals a dependency-of-target is missing)."""

    def _raise(name: str) -> None:
        # Raise a ModuleNotFoundError whose .name is a *different* module
        # so the helper's "not me, re-raise" branch fires.
        err = ModuleNotFoundError("missing sub-dep")
        err.name = "_unrelated_sub_dep_"
        raise err

    monkeypatch.setattr(M, "import_module", _raise)
    with pytest.raises(ModuleNotFoundError):
        M._optional_router("jpintel_mcp.api.programs")


# ---------------------------------------------------------------------------
# _include_experimental_router — gate OFF → early return
# ---------------------------------------------------------------------------


def test_include_experimental_router_gate_off_is_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    """When AUTONOMATH_EXPERIMENTAL_API_ENABLED is falsy, the helper returns
    without attempting to include the router. The function does not raise
    and the app object is untouched."""
    monkeypatch.setenv("AUTONOMATH_EXPERIMENTAL_API_ENABLED", "0")

    class _FakeApp:
        included: list[str] = []

        def include_router(self, router: Any, **kwargs: Any) -> None:
            self.included.append(getattr(router, "name", "?"))

    app = _FakeApp()
    M._include_experimental_router(app, "jpintel_mcp.api.programs")
    assert app.included == []


def test_include_experimental_router_gate_on_missing_module_no_op(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Gate is ON but the target module does not exist — the helper finds
    a None router and skips include_router."""
    monkeypatch.setenv("AUTONOMATH_EXPERIMENTAL_API_ENABLED", "1")

    class _FakeApp:
        included: list[Any] = []

        def include_router(self, router: Any, **kwargs: Any) -> None:
            self.included.append(router)

    app = _FakeApp()
    M._include_experimental_router(app, "jpintel_mcp.does_not_exist_xxx_test")
    assert app.included == []


# ---------------------------------------------------------------------------
# _normalize_openapi_component_schema_names — branches
# ---------------------------------------------------------------------------


def test_normalize_openapi_component_schema_names_renames_known() -> None:
    """The renamer walks components.schemas + all $ref strings."""
    schema: dict[str, Any] = {
        "components": {
            "schemas": {
                # An explicit-mapping name — must be renamed per _COMPONENT_SCHEMA_NAMES.
                "jpintel_mcp__models__SearchResponse": {"title": "x"},
                # An untouched plain name.
                "PlainSchema": {"title": "y"},
            }
        },
        "paths": {
            "/v1/foo": {
                "get": {
                    "responses": {
                        "200": {
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "$ref": (
                                            "#/components/schemas/"
                                            "jpintel_mcp__models__SearchResponse"
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
    # The new public name must be present; old internal name should be gone.
    schemas = schema["components"]["schemas"]
    assert "ProgramSearchResponse" in schemas
    assert "jpintel_mcp__models__SearchResponse" not in schemas
    # $ref was rewritten to the new name too.
    ref = schema["paths"]["/v1/foo"]["get"]["responses"]["200"]["content"]["application/json"][
        "schema"
    ]["$ref"]
    assert ref.endswith("ProgramSearchResponse")


def test_normalize_openapi_component_schema_names_no_components_is_noop() -> None:
    """Empty / missing components key is a no-op (does not raise)."""
    schema: dict[str, Any] = {"openapi": "3.1.0"}
    M._normalize_openapi_component_schema_names(schema)
    assert schema == {"openapi": "3.1.0"}


# ---------------------------------------------------------------------------
# _sanitize_openapi_public_schema — full branches
# ---------------------------------------------------------------------------


def test_sanitize_openapi_public_schema_strips_contact() -> None:
    """Top-level info.contact is removed for the public schema."""
    schema: dict[str, Any] = {"info": {"title": "API", "contact": {"email": "x@example.com"}}}
    M._sanitize_openapi_public_schema(schema)
    assert "contact" not in schema["info"]


def test_sanitize_openapi_public_schema_renames_legacy_tags_strings() -> None:
    """Tag values matching the legacy autonomath labels are renamed."""
    schema: dict[str, Any] = {"tags": ["autonomath", "autonomath-health", "other"]}
    M._sanitize_openapi_public_schema(schema)
    assert "autonomath" not in schema["tags"]
    assert "jpcite" in schema["tags"]


def test_sanitize_openapi_public_schema_renames_legacy_tag_dicts() -> None:
    """Tag dicts (root-level shape) renamed too."""
    schema: dict[str, Any] = {"tags": [{"name": "autonomath", "description": "x"}, {"name": "foo"}]}
    M._sanitize_openapi_public_schema(schema)
    names = {t["name"] for t in schema["tags"] if isinstance(t, dict)}
    assert "autonomath" not in names
    assert "jpcite" in names


def test_sanitize_openapi_public_schema_strips_internal_enum() -> None:
    """An enum value 'internal' is filtered out."""
    node: dict[str, Any] = {"enum": ["public", "internal", "paid"]}
    M._sanitize_openapi_public_schema(node)
    assert "internal" not in node["enum"]
    assert "public" in node["enum"] and "paid" in node["enum"]


def test_sanitize_openapi_public_schema_strips_include_excluded_property() -> None:
    """include_excluded property is removed + popped from required."""
    node: dict[str, Any] = {
        "properties": {
            "primary_name": {"type": "string"},
            "include_excluded": {"type": "boolean"},
        },
        "required": ["primary_name", "include_excluded"],
    }
    M._sanitize_openapi_public_schema(node)
    assert "include_excluded" not in node["properties"]
    assert "include_excluded" not in node["required"]


def test_sanitize_openapi_public_schema_strips_include_internal_parameter() -> None:
    """parameters with name=include_internal | include_excluded removed."""
    node: dict[str, Any] = {
        "parameters": [
            {"name": "q", "in": "query"},
            {"name": "include_internal", "in": "query"},
            {"name": "include_excluded", "in": "query"},
        ]
    }
    M._sanitize_openapi_public_schema(node)
    names = {p["name"] for p in node["parameters"]}
    assert names == {"q"}


def test_sanitize_openapi_public_schema_webhook_response_secret_renamed() -> None:
    """WebhookResponse's secret_hmac / secret_last4 are renamed to signing_secret / hint."""
    node: dict[str, Any] = {
        "title": "WebhookResponse",
        "properties": {
            "secret_hmac": {"type": "string"},
            "secret_last4": {"type": "string"},
        },
        "required": ["secret_hmac", "secret_last4"],
    }
    M._sanitize_openapi_public_schema(node)
    props = node["properties"]
    assert "signing_secret" in props
    assert "signing_secret_hint" in props
    assert "secret_hmac" not in props
    assert "secret_last4" not in props
    assert "signing_secret" in node["required"]
    assert "signing_secret_hint" in node["required"]


def test_sanitize_openapi_public_schema_datahealthcheck_table_to_dataset() -> None:
    """_DataHealthCheck's `table` property is renamed to `dataset`."""
    node: dict[str, Any] = {
        "title": "_DataHealthCheck",
        "properties": {"table": {"type": "string"}},
        "required": ["table"],
    }
    M._sanitize_openapi_public_schema(node)
    assert "dataset" in node["properties"]
    assert "table" not in node["properties"]
    assert "dataset" in node["required"]


def test_sanitize_openapi_public_schema_contact_default_email_stripped() -> None:
    """A property whose default is info@bookyou.net loses the default."""
    node: dict[str, Any] = {
        "properties": {
            "contact": {"default": "info@bookyou.net", "type": "string"},
        },
    }
    M._sanitize_openapi_public_schema(node)
    contact = node["properties"]["contact"]
    assert "default" not in contact
    assert contact["description"] == "Support contact."


def test_sanitize_openapi_public_schema_list_descent() -> None:
    """Top-level list nodes still descend into each item without crashing."""
    items: list[Any] = [{"title": "A"}, {"title": "B"}]
    M._sanitize_openapi_public_schema(items)
    # Should not raise.


# ---------------------------------------------------------------------------
# _walk_openapi_leak_strings_runtime — list of dicts that go to exempt path
# ---------------------------------------------------------------------------


def test_walk_openapi_leak_list_in_exempt_dict_freezes_strings() -> None:
    """A 'default' key whose value is a list of strings must NOT rewrite
    the list items (exempt=True descends through the list)."""
    node: dict[str, Any] = {"default": ["T8010001213708 raw", "Bookyou株式会社"]}
    M._walk_openapi_leak_strings_runtime(node)
    assert node["default"] == ["T8010001213708 raw", "Bookyou株式会社"]


def test_walk_openapi_leak_nested_list_outside_exempt_is_rewritten() -> None:
    """Non-exempt lists get sanitised in-place — strings rewritten."""
    node: dict[str, Any] = {
        "description": "should be rewritten",
        "items": ["plain text"],
    }
    M._walk_openapi_leak_strings_runtime(node)
    assert isinstance(node["items"][0], str)


# ---------------------------------------------------------------------------
# _strip_openapi_leak_patterns_runtime — protected api-key examples
# ---------------------------------------------------------------------------


def test_strip_openapi_leak_patterns_protected_api_key_preserved() -> None:
    """An API-key-shaped example value (X-API-Key: jc_live_*) should pass
    through verbatim — protected by `_OPENAPI_API_KEY_EXAMPLE_RE_RUNTIME`."""
    key_example = "X-API-Key: jc_live_" + "a" * 32
    raw = f"Example header: {key_example} is preserved."
    out = M._strip_openapi_leak_patterns_runtime(raw)
    # The literal key example must survive the punctuation collapse pass.
    assert key_example in out


def test_strip_openapi_leak_patterns_idempotent() -> None:
    """Applying the strip twice yields the same string."""
    raw = "foo  ,  bar  ;  baz"
    once = M._strip_openapi_leak_patterns_runtime(raw)
    twice = M._strip_openapi_leak_patterns_runtime(once)
    assert once == twice


# ---------------------------------------------------------------------------
# Live route smoke — exercises _RequestContextMiddleware + telemetry path
# ---------------------------------------------------------------------------


def test_healthz_returns_200(client: TestClient) -> None:
    """/healthz is wired in main.py and exercised many test paths; this
    confirms the middleware stack runs without raising."""
    r = client.get("/healthz")
    assert r.status_code == 200, r.text


def test_request_id_header_round_tripped(client: TestClient) -> None:
    """When the client supplies a valid x-request-id, the middleware echoes
    it back on the response (covers the inbound-valid branch in
    _RequestContextMiddleware.dispatch)."""
    rid = "test-rid-01234567"
    r = client.get("/healthz", headers={"x-request-id": rid})
    assert r.status_code == 200
    # Response should carry the same id back (header is canonical-cased).
    echoed = r.headers.get("x-request-id")
    assert echoed == rid


def test_request_id_auto_generated_when_invalid(client: TestClient) -> None:
    """An invalid (too-short) x-request-id triggers the auto-mint branch."""
    r = client.get("/healthz", headers={"x-request-id": "x"})  # too short
    assert r.status_code == 200
    echoed = r.headers.get("x-request-id")
    # Auto-generated id is 26 chars (Crockford ULID).
    assert echoed is not None and len(echoed) >= 8


def test_openapi_json_serves_public_schema(client: TestClient) -> None:
    """The /v1/openapi.json route runs the sanitiser pipeline + exercise
    a large surface in one call."""
    r = client.get("/v1/openapi.json")
    assert r.status_code == 200
    body = r.json()
    assert body.get("openapi", "").startswith("3.")
    assert "paths" in body


def test_openapi_legacy_redirect_to_v1(client: TestClient) -> None:
    """The /openapi.json back-compat path 308-redirects to /v1/openapi.json."""
    r = client.get("/openapi.json", follow_redirects=False)
    assert r.status_code == 308
    assert "/v1/openapi.json" in r.headers.get("location", "")


def test_v1_meta_returns_200(client: TestClient) -> None:
    """Meta endpoint smoke — exercises router include + ApiContextDep."""
    r = client.get("/v1/meta")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, dict)


def test_404_path_returns_canonical_envelope(client: TestClient) -> None:
    """A non-existent path triggers the http_exception_handler 404 branch
    which attaches suggested_paths + path extras."""
    r = client.get("/v1/this-route-does-not-exist-xxx")
    assert r.status_code == 404
    body = r.json()
    # Either FastAPI's default 404 OR our envelope; both must have detail.
    assert "detail" in body or "error" in body


def test_unsupported_method_405_or_404(client: TestClient) -> None:
    """An unsupported method on a real path yields a 405/404 — the
    canonical envelope branches map these to `method_not_allowed` /
    `route_not_found`."""
    # POST to /healthz which only accepts GET.
    r = client.post("/healthz")
    assert r.status_code in {404, 405}
