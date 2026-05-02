"""Targeted regression tests for the committed OpenAPI export."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_openapi_export_matches_committed_spec(tmp_path: Path) -> None:
    out = tmp_path / "openapi.json"
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"

    subprocess.run(
        [sys.executable, "scripts/export_openapi.py", "--out", str(out)],
        cwd=REPO_ROOT,
        env=env,
        check=True,
        text=True,
        capture_output=True,
    )

    assert out.read_text(encoding="utf-8") == (
        REPO_ROOT / "docs" / "openapi" / "v1.json"
    ).read_text(encoding="utf-8")


def test_openapi_version_matches_pyproject() -> None:
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    expected = pyproject["project"]["version"]
    schema = json.loads((REPO_ROOT / "docs" / "openapi" / "v1.json").read_text(encoding="utf-8"))

    assert schema["info"]["version"] == expected


def test_evidence_prefetch_openapi_has_non_empty_response_schema() -> None:
    schema = json.loads(
        (REPO_ROOT / "docs" / "openapi" / "v1.json").read_text(encoding="utf-8")
    )
    targets = [
        ("post", "/v1/evidence/packets/query"),
        ("get", "/v1/evidence/packets/{subject_kind}/{subject_id}"),
        ("get", "/v1/intelligence/precomputed/query"),
    ]

    for method, path in targets:
        operation = schema["paths"][path][method]
        response_schema = operation["responses"]["200"]["content"][
            "application/json"
        ]["schema"]
        assert response_schema, f"{method.upper()} {path} has empty 200 schema"
        assert operation["responses"]["200"]["content"]["application/json"][
            "example"
        ]


def test_evidence_prefetch_openapi_describes_context_estimate_limits() -> None:
    schema = json.loads(
        (REPO_ROOT / "docs" / "openapi" / "v1.json").read_text(encoding="utf-8")
    )
    query_desc = schema["paths"]["/v1/evidence/packets/query"]["post"][
        "description"
    ]
    intelligence_desc = schema["paths"]["/v1/intelligence/precomputed/query"][
        "get"
    ]["description"]

    assert "GPT" in query_desc
    assert "Claude" in query_desc
    assert "PDF" in query_desc
    assert "not external provider billing guarantees" in query_desc
    assert "LLM context prefetch" in intelligence_desc
    assert "without live web search" in intelligence_desc


def test_evidence_prefetch_openapi_marks_core_fields_required() -> None:
    schema = json.loads(
        (REPO_ROOT / "docs" / "openapi" / "v1.json").read_text(encoding="utf-8")
    )
    components = schema["components"]["schemas"]
    envelope_required = set(components["EvidencePacketEnvelope"]["required"])
    precomputed_required = set(
        components["PrecomputedIntelligenceBundle"]["required"]
    )

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
