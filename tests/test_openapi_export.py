"""Targeted regression tests for the committed OpenAPI export."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

_COMPANY_ARTIFACT_PATHS = {
    "/v1/artifacts/company_public_baseline",
    "/v1/artifacts/company_folder_brief",
    "/v1/artifacts/company_public_audit_pack",
}

_AGENT_OPENAPI_PATHS = [
    REPO_ROOT / "docs" / "openapi" / "agent.json",
    REPO_ROOT / "site" / "openapi.agent.json",
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
