"""Targeted regression tests for the committed OpenAPI export."""

from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_export_openapi_module():
    """Import scripts/export_openapi.py as a module so tests can call the
    sanitizer helpers directly."""
    path = REPO_ROOT / "scripts" / "export_openapi.py"
    spec = importlib.util.spec_from_file_location("_test_export_openapi", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

_COMPANY_ARTIFACT_PATHS = {
    "/v1/artifacts/company_public_baseline",
    "/v1/artifacts/company_folder_brief",
    "/v1/artifacts/company_public_audit_pack",
}

_AGENT_OPENAPI_PATHS = [
    REPO_ROOT / "docs" / "openapi" / "agent.json",
    REPO_ROOT / "site" / "openapi.agent.json",
    REPO_ROOT / "site" / "openapi" / "agent.json",
    REPO_ROOT / "site" / "docs" / "openapi" / "agent.json",
]


def _stable_env() -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["AUTONOMATH_EXPERIMENTAL_API_ENABLED"] = "0"
    return env


def test_openapi_export_matches_committed_spec(tmp_path: Path) -> None:
    out = tmp_path / "openapi.json"
    site_out = tmp_path / "site-openapi.json"
    env = _stable_env()

    subprocess.run(
        [
            sys.executable,
            "scripts/export_openapi.py",
            "--out",
            str(out),
            "--site-out",
            str(site_out),
        ],
        cwd=REPO_ROOT,
        env=env,
        check=True,
        text=True,
        capture_output=True,
    )

    assert out.read_text(encoding="utf-8") == (
        REPO_ROOT / "docs" / "openapi" / "v1.json"
    ).read_text(encoding="utf-8")
    assert site_out.read_text(encoding="utf-8") == out.read_text(encoding="utf-8")


def test_served_openapi_json_matches_committed_stable_spec(monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from jpintel_mcp.api.main import create_app

    monkeypatch.setenv("AUTONOMATH_EXPERIMENTAL_API_ENABLED", "0")
    client = TestClient(create_app())
    response = client.get("/v1/openapi.json")
    assert response.status_code == 200, response.text
    committed = json.loads((REPO_ROOT / "docs" / "openapi" / "v1.json").read_text(encoding="utf-8"))
    assert response.json() == committed


def test_static_agent_openapi_matches_dynamic_stable_projection(monkeypatch) -> None:
    from jpintel_mcp.api.main import create_app
    from jpintel_mcp.api.openapi_agent import build_agent_openapi_schema

    monkeypatch.setenv("AUTONOMATH_EXPERIMENTAL_API_ENABLED", "0")
    dynamic_schema = build_agent_openapi_schema(create_app().openapi())

    for path in _AGENT_OPENAPI_PATHS:
        committed = json.loads(path.read_text(encoding="utf-8"))
        assert committed == dynamic_schema, path.relative_to(REPO_ROOT)


def test_dynamic_openapi_exposes_company_public_artifacts(tmp_path: Path) -> None:
    out = tmp_path / "openapi.json"
    site_out = tmp_path / "site-openapi.json"
    env = _stable_env()

    subprocess.run(
        [
            sys.executable,
            "scripts/export_openapi.py",
            "--out",
            str(out),
            "--site-out",
            str(site_out),
        ],
        cwd=REPO_ROOT,
        env=env,
        check=True,
        text=True,
        capture_output=True,
    )

    schema = json.loads(out.read_text(encoding="utf-8"))
    for path in _COMPANY_ARTIFACT_PATHS:
        operation = schema["paths"][path]["post"]
        assert operation["tags"] == ["artifacts"]
        assert "artifact" in operation["summary"]


def test_openapi_version_matches_pyproject() -> None:
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    expected = pyproject["project"]["version"]
    schema = json.loads((REPO_ROOT / "docs" / "openapi" / "v1.json").read_text(encoding="utf-8"))

    assert schema["info"]["version"] == expected


def test_evidence_prefetch_openapi_has_non_empty_response_schema() -> None:
    schema = json.loads((REPO_ROOT / "docs" / "openapi" / "v1.json").read_text(encoding="utf-8"))
    targets = [
        ("post", "/v1/evidence/packets/query"),
        ("get", "/v1/evidence/packets/{subject_kind}/{subject_id}"),
        ("get", "/v1/intelligence/precomputed/query"),
    ]

    for method, path in targets:
        operation = schema["paths"][path][method]
        response_schema = operation["responses"]["200"]["content"]["application/json"]["schema"]
        assert response_schema, f"{method.upper()} {path} has empty 200 schema"
        assert operation["responses"]["200"]["content"]["application/json"]["example"]


def test_experimental_openapi_export_exposes_value_pack_artifacts(tmp_path: Path) -> None:
    out = tmp_path / "openapi-experimental.json"
    site_out = tmp_path / "site-openapi-experimental.json"
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["AUTONOMATH_EXPERIMENTAL_API_ENABLED"] = "1"

    subprocess.run(
        [
            sys.executable,
            "scripts/export_openapi.py",
            "--out",
            str(out),
            "--site-out",
            str(site_out),
        ],
        cwd=REPO_ROOT,
        env=env,
        check=True,
        text=True,
        capture_output=True,
    )

    schema = json.loads(out.read_text(encoding="utf-8"))
    houjin = schema["paths"]["/v1/artifacts/houjin_dd_pack"]["post"]
    strategy = schema["paths"]["/v1/artifacts/application_strategy_pack"]["post"]

    assert houjin["tags"] == ["artifacts"]
    assert "法人DD pack artifact" in houjin["summary"]
    assert strategy["tags"] == ["artifacts"]
    assert "制度申請 strategy pack artifact" in strategy["summary"]
    assert site_out.read_text(encoding="utf-8") == out.read_text(encoding="utf-8")


def test_evidence_prefetch_openapi_describes_context_estimate_limits() -> None:
    schema = json.loads((REPO_ROOT / "docs" / "openapi" / "v1.json").read_text(encoding="utf-8"))
    query_desc = schema["paths"]["/v1/evidence/packets/query"]["post"]["description"]
    intelligence_desc = schema["paths"]["/v1/intelligence/precomputed/query"]["get"]["description"]

    assert "GPT" in query_desc
    assert "Claude" in query_desc
    assert "PDF" in query_desc
    assert "caller-supplied input-context baselines" in query_desc
    assert "LLM context prefetch" in intelligence_desc
    assert "without live web search" in intelligence_desc


def test_evidence_prefetch_openapi_marks_core_fields_required() -> None:
    schema = json.loads((REPO_ROOT / "docs" / "openapi" / "v1.json").read_text(encoding="utf-8"))
    components = schema["components"]["schemas"]
    envelope_required = set(components["EvidencePacketEnvelope"]["required"])
    precomputed_required = set(components["PrecomputedIntelligenceBundle"]["required"])

    assert {"records", "quality", "verification"} <= envelope_required
    assert {
        "bundle_kind",
        "bundle_id",
        "answer_basis",
        "records_returned",
        "precomputed_record_count",
        "precomputed",
        "usage",
    } <= precomputed_required

    example = components["PrecomputedIntelligenceBundle"]["example"]
    assert example["bundle_kind"] == "precomputed_intelligence"
    assert example["precomputed"]["available"] is True
    assert example["usage"]["web_search_required"] is False


def test_evidence_packet_openapi_snapshots_include_value_guidance_fields() -> None:
    schema = json.loads((REPO_ROOT / "docs" / "openapi" / "v1.json").read_text(encoding="utf-8"))
    envelope = schema["components"]["schemas"]["EvidencePacketEnvelope"]
    properties = envelope["properties"]

    assert "evidence_value" in properties
    assert "decision_insights" in properties

    example = envelope["example"]
    assert "evidence_value" in example
    assert example["decision_insights"]["schema_version"] == "v1"
    assert example["decision_insights"]["why_review"]
    assert example["decision_insights"]["next_checks"]

    for method, path in (
        ("post", "/v1/evidence/packets/query"),
        ("get", "/v1/evidence/packets/{subject_kind}/{subject_id}"),
    ):
        response_schema = schema["paths"][path][method]["responses"]["200"]["content"][
            "application/json"
        ]["schema"]
        assert response_schema == {"$ref": "#/components/schemas/EvidencePacketEnvelope"}


# ---------------------------------------------------------------------------
# A3-style leak sanitizer regression tests.
# ---------------------------------------------------------------------------


_LEAK_SAMPLE_DESCRIPTION = (
    "Looks up am_compat_matrix + am_entity_facts joined with houjin_watch "
    "for the M&A cohort. Backed by autonomath.db (was jpintel.db). "
    "Wave 22 / migration 088 — see CLAUDE.md and scripts/cron/dispatch_webhooks.py "
    "for the operator pipeline. Aggregates usage_events for billing and "
    "cost_ledger for spend roll-up; uses idempotency_cache to dedupe retries. "
    "Joins am_amendment_diff, am_amendment_snapshot, am_law_article, "
    "am_loan_product, am_enforcement_detail, am_amount_condition, am_tax_treaty, "
    "am_industry_jsic, am_application_round, am_entities, am_relation, am_source."
)


def test_sanitizer_strips_all_denylisted_table_names():
    mod = _load_export_openapi_module()
    cleaned = mod._strip_openapi_leak_patterns(_LEAK_SAMPLE_DESCRIPTION)
    for forbidden in (
        "am_compat_matrix",
        "am_entity_facts",
        "am_entities",
        "am_relation",
        "am_source",
        "am_loan_product",
        "am_law_article",
        "am_enforcement_detail",
        "am_amount_condition",
        "am_tax_treaty",
        "am_industry_jsic",
        "am_application_round",
        "am_amendment_snapshot",
        "am_amendment_diff",
        "houjin_watch",
        "usage_events",
        "cost_ledger",
        "idempotency_cache",
        "jpintel.db",
        "autonomath.db",
        "CLAUDE.md",
        "scripts/cron/",
    ):
        assert forbidden not in cleaned, f"leak pattern {forbidden!r} survived sanitizer"
    # Wave / migration markers are stripped (number disappears with the marker).
    assert not re.search(r"\bWave\s+22\b", cleaned)
    assert not re.search(r"\bmigration\s+088\b", cleaned, flags=re.IGNORECASE)
    # Replacement copy uses public-friendly vocabulary instead.
    assert "compatibility-matrix corpus" in cleaned
    assert "entity-fact corpus" in cleaned
    assert "corporate watch list" in cleaned
    assert "primary corpus database" in cleaned


def test_sanitizer_walks_full_openapi_schema_dict():
    """Walker scrubs description/summary leaks but exempts example payloads.

    Per E11 audit, `example` / `examples` / `default` / `operationId` are
    runtime-echoed slots that MUST stay byte-identical to the runtime response.
    The walker therefore scrubs description / summary leaks (verified per
    field) but leaves the `example` payload verbatim — that is the new contract
    and the previous "all-strings-scrubbed" expectation was the E5 drift bug.
    """
    mod = _load_export_openapi_module()
    schema = {
        "openapi": "3.1.0",
        "info": {"title": "leak test", "description": _LEAK_SAMPLE_DESCRIPTION},
        "paths": {
            "/v1/example": {
                "post": {
                    "summary": "Pair lookup over am_compat_matrix",
                    "description": "Wave 21 cohort backed by houjin_watch.",
                    "responses": {
                        "200": {
                            "description": "Returns am_entity_facts joined with am_relation.",
                            "content": {
                                "application/json": {
                                    "example": {
                                        "source": "am_compat_matrix",
                                        "notes": [
                                            "Backed by autonomath.db",
                                            "see scripts/cron/dispatch_webhooks.py",
                                        ],
                                    }
                                }
                            },
                        }
                    },
                }
            }
        },
    }
    mod.sanitize_openapi_schema_leaks(schema)
    op = schema["paths"]["/v1/example"]["post"]
    # 1) Description / summary text MUST be scrubbed.
    for cleaned_text in (
        schema["info"]["description"],
        op["summary"],
        op["description"],
        op["responses"]["200"]["description"],
    ):
        for forbidden in (
            "am_compat_matrix",
            "am_entity_facts",
            "am_relation",
            "houjin_watch",
            "autonomath.db",
            "scripts/cron/",
            "Wave 21",
        ):
            assert forbidden not in cleaned_text, (
                f"{forbidden!r} survived description-level scrub: {cleaned_text!r}"
            )
    # 2) example payload MUST be preserved verbatim (runtime echoes it back).
    response_example = (
        op["responses"]["200"]["content"]["application/json"]["example"]
    )
    assert response_example["source"] == "am_compat_matrix"
    assert response_example["notes"] == [
        "Backed by autonomath.db",
        "see scripts/cron/dispatch_webhooks.py",
    ]


def test_assert_no_openapi_leaks_raises_on_residual_leak():
    mod = _load_export_openapi_module()
    payload_clean = '{"description": "uses entity-fact corpus and corporate watch list"}'
    mod.assert_no_openapi_leaks(payload_clean, label="test-clean")  # must not raise

    payload_leak = '{"description": "joins am_compat_matrix and houjin_watch"}'
    with pytest.raises(SystemExit) as excinfo:
        mod.assert_no_openapi_leaks(payload_leak, label="test-leak")
    message = str(excinfo.value)
    assert "test-leak" in message
    assert "am_compat_matrix" in message or "houjin_watch" in message


def test_committed_specs_contain_no_banned_leak_patterns():
    """Validation gate: every committed spec passes the leak scan.

    Per E11 audit the leak scan exempts JSON-pointer subtrees that the runtime
    echoes back verbatim (`default` / `example` / `examples` / `operationId`).
    We use `assert_no_openapi_leaks`, which applies the same exemption, so
    description / summary leaks still trip but legitimate runtime literals
    inside exempt slots are accepted.
    """
    mod = _load_export_openapi_module()
    targets = (
        REPO_ROOT / "docs" / "openapi" / "v1.json",
        REPO_ROOT / "docs" / "openapi" / "agent.json",
        REPO_ROOT / "site" / "openapi.agent.json",
        REPO_ROOT / "site" / "openapi.agent.gpt30.json",
        REPO_ROOT / "site" / "docs" / "openapi" / "v1.json",
        REPO_ROOT / "site" / "docs" / "openapi" / "agent.json",
    )
    for path in targets:
        if not path.exists():
            continue
        payload = path.read_text(encoding="utf-8")
        mod.assert_no_openapi_leaks(payload, label=str(path.relative_to(REPO_ROOT)))


# ---------------------------------------------------------------------------
# E11 audit follow-up: sanitizer must NOT rewrite spec values that the runtime
# echoes back verbatim. Tracking JSON-pointer-derived contexts:
#   * components.schemas.*.properties.*.default
#   * paths.*.*.responses.*.content.*.example / examples.*.value
#   * paths.*.*.requestBody.content.*.example / examples.*.value
#   * operationId  (route-derived identifier, must stay stable)
# Description / summary leaks must STILL be scrubbed in the same payload.
# ---------------------------------------------------------------------------


def test_sanitizer_exempts_pydantic_default_preserving_runtime_literal():
    """`components.schemas.*.properties.*.default` must stay verbatim — the
    runtime returns the same literal, so the spec must not be rewritten."""
    mod = _load_export_openapi_module()
    schema = {
        "components": {
            "schemas": {
                "EnforcementDetailSearchResponse": {
                    "type": "object",
                    "description": (
                        "Backed by am_enforcement_detail; leaks here MUST be scrubbed."
                    ),
                    "properties": {
                        "source_table": {
                            "type": "string",
                            "default": "am_enforcement_detail",
                            "description": "Internal hint over am_enforcement_detail.",
                        },
                    },
                }
            }
        }
    }
    mod.sanitize_openapi_schema_leaks(schema)
    schema_obj = schema["components"]["schemas"]["EnforcementDetailSearchResponse"]
    # default literal preserved
    assert (
        schema_obj["properties"]["source_table"]["default"] == "am_enforcement_detail"
    )
    # description scrubbed
    assert "am_enforcement_detail" not in schema_obj["description"]
    assert "am_enforcement_detail" not in schema_obj["properties"]["source_table"]["description"]
    assert "enforcement-detail corpus" in schema_obj["description"]


def test_sanitizer_exempts_response_example_payload():
    """`responses.*.content.*.example` payloads echo the runtime response —
    they must not be rewritten by the leak walker."""
    mod = _load_export_openapi_module()
    schema = {
        "paths": {
            "/v1/example": {
                "post": {
                    "description": (
                        "Pair lookup over am_compat_matrix; description MUST be scrubbed."
                    ),
                    "responses": {
                        "200": {
                            "description": "Returns am_compat_matrix joined records.",
                            "content": {
                                "application/json": {
                                    "example": {
                                        "source": "am_compat_matrix",
                                        "notes": ["row joined from am_compat_matrix"],
                                    },
                                    "examples": {
                                        "happy_path": {
                                            "value": {
                                                "source": "am_compat_matrix",
                                            }
                                        }
                                    },
                                }
                            },
                        }
                    },
                }
            }
        }
    }
    mod.sanitize_openapi_schema_leaks(schema)
    op = schema["paths"]["/v1/example"]["post"]
    response_content = op["responses"]["200"]["content"]["application/json"]
    # example payload preserved
    assert response_content["example"]["source"] == "am_compat_matrix"
    assert response_content["example"]["notes"] == ["row joined from am_compat_matrix"]
    assert (
        response_content["examples"]["happy_path"]["value"]["source"]
        == "am_compat_matrix"
    )
    # description scrubbed
    assert "am_compat_matrix" not in op["description"]
    assert "am_compat_matrix" not in op["responses"]["200"]["description"]


def test_sanitizer_exempts_request_body_example():
    """`requestBody.content.*.example` payloads echo the runtime contract."""
    mod = _load_export_openapi_module()
    schema = {
        "paths": {
            "/v1/example": {
                "post": {
                    "summary": "writes am_compat_matrix rows; summary MUST be scrubbed",
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "example": {"source": "am_compat_matrix"},
                                "examples": {
                                    "default_request": {
                                        "value": {"source": "am_compat_matrix"}
                                    }
                                },
                            }
                        }
                    },
                }
            }
        }
    }
    mod.sanitize_openapi_schema_leaks(schema)
    op = schema["paths"]["/v1/example"]["post"]
    body_content = op["requestBody"]["content"]["application/json"]
    assert body_content["example"]["source"] == "am_compat_matrix"
    assert (
        body_content["examples"]["default_request"]["value"]["source"]
        == "am_compat_matrix"
    )
    # summary scrubbed
    assert "am_compat_matrix" not in op["summary"]


def test_sanitizer_exempts_operation_id():
    """`operationId` is the route-derived identifier — must stay stable even
    if it embeds an `am_*` literal."""
    mod = _load_export_openapi_module()
    schema = {
        "paths": {
            "/v1/example": {
                "get": {
                    "operationId": "list_am_compat_matrix_rows_v1_example_get",
                    "description": (
                        "List rows of am_compat_matrix; description MUST be scrubbed."
                    ),
                }
            }
        }
    }
    mod.sanitize_openapi_schema_leaks(schema)
    op = schema["paths"]["/v1/example"]["get"]
    assert op["operationId"] == "list_am_compat_matrix_rows_v1_example_get"
    assert "am_compat_matrix" not in op["description"]


def test_assert_no_openapi_leaks_allows_exempt_subtrees():
    """The post-export leak gate also exempts the same JSON-pointer slots —
    an `am_*` literal inside a `default` / `example` / `operationId` must NOT
    trip the gate, but the same literal inside a `description` must."""
    mod = _load_export_openapi_module()
    clean_schema = {
        "paths": {
            "/v1/example": {
                "get": {
                    "operationId": "list_am_compat_matrix_v1_example_get",
                    "description": "Public lookup over compatibility-matrix corpus.",
                    "responses": {
                        "200": {
                            "description": "Result page.",
                            "content": {
                                "application/json": {
                                    "example": {"source": "am_compat_matrix"}
                                }
                            },
                        }
                    },
                }
            }
        },
        "components": {
            "schemas": {
                "Resp": {
                    "type": "object",
                    "properties": {
                        "source_table": {
                            "type": "string",
                            "default": "am_enforcement_detail",
                        }
                    },
                }
            }
        },
    }
    payload_clean = json.dumps(clean_schema)
    # Must NOT raise — leaks are inside exempt slots.
    mod.assert_no_openapi_leaks(payload_clean, label="test-exempt-clean")

    leak_schema = {
        "paths": {
            "/v1/example": {
                "get": {
                    "description": "joins am_compat_matrix in the description",
                }
            }
        }
    }
    payload_leak = json.dumps(leak_schema)
    with pytest.raises(SystemExit):
        mod.assert_no_openapi_leaks(payload_leak, label="test-exempt-leak")


def test_runtime_sanitizer_exempts_same_paths_as_export():
    """The runtime mirror in `src/jpintel_mcp/api/main.py` must apply the same
    exemption — otherwise the served `/v1/openapi.json` and the committed
    export diverge again."""
    from jpintel_mcp.api.main import (
        _sanitize_openapi_public_schema,
        _walk_openapi_leak_strings_runtime,
    )

    schema = {
        "components": {
            "schemas": {
                "EnforcementDetailSearchResponse": {
                    "type": "object",
                    "description": "Backed by am_enforcement_detail.",
                    "properties": {
                        "source_table": {
                            "type": "string",
                            "default": "am_enforcement_detail",
                        }
                    },
                }
            }
        },
        "paths": {
            "/v1/example": {
                "get": {
                    "operationId": "list_am_compat_matrix_v1_example_get",
                    "description": "Joins am_compat_matrix.",
                    "responses": {
                        "200": {
                            "description": "ok",
                            "content": {
                                "application/json": {
                                    "example": {"source": "am_compat_matrix"}
                                }
                            },
                        }
                    },
                }
            }
        },
    }
    _sanitize_openapi_public_schema(schema)
    _walk_openapi_leak_strings_runtime(schema)
    schema_obj = schema["components"]["schemas"]["EnforcementDetailSearchResponse"]
    assert schema_obj["properties"]["source_table"]["default"] == "am_enforcement_detail"
    assert "am_enforcement_detail" not in schema_obj["description"]
    op = schema["paths"]["/v1/example"]["get"]
    assert op["operationId"] == "list_am_compat_matrix_v1_example_get"
    assert op["responses"]["200"]["content"]["application/json"]["example"]["source"] == "am_compat_matrix"
    assert "am_compat_matrix" not in op["description"]
