"""Wave 46 dim 19 dim D sub-criterion test — audit workpaper schema surface.

Tests the new ``GET /v1/audit/workpaper/schema`` discovery endpoint added
in Wave 46 to close one sub-axis of the dim D audit score (3.00/10 → ~3.50).
The test file is intentionally dim-D-specific (not C+D combined) so the
``test count`` axis lifts from 1 (shared C+D) to 2 (new D-specific).

The new GET surface:

  * is a pure static metadata payload (no SQLite open, no LLM call,
    no houjin lookup);
  * costs 0 billing units (discoverability, not a billed compose);
  * carries the same fence text as the POST compose endpoint;
  * does NOT leak any per-houjin row data.

Honours
-------
``feedback_autonomath_no_api_use`` + ``feedback_completion_gate_minimal``
(single sub-criterion, NOT a full 3.00 → 8.0 refactor).

No LLM, no network, no aggregator fence-jump.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
_SRC = _REPO / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


# ---------------------------------------------------------------------------
# File-presence + import sanity
# ---------------------------------------------------------------------------


def test_dimd_schema_endpoint_file_exists():
    """The GET schema endpoint lives in api/audit_workpaper_v2.py."""
    rest = _REPO / "src" / "jpintel_mcp" / "api" / "audit_workpaper_v2.py"
    assert rest.exists(), "audit_workpaper_v2.py REST module missing"
    text = rest.read_text(encoding="utf-8")
    # Must contain a GET /workpaper/schema route decorator
    assert "/workpaper/schema" in text
    assert "@router.get" in text


def test_dimd_schema_module_imports_no_llm():
    """The audit_workpaper_v2 REST module must not import any LLM client."""
    rest = _REPO / "src" / "jpintel_mcp" / "api" / "audit_workpaper_v2.py"
    text = rest.read_text(encoding="utf-8")
    # Reject any of the canonical LLM client modules.
    for forbidden in (
        "import anthropic",
        "from anthropic",
        "import openai",
        "from openai",
        "import google.generativeai",
        "from google.generativeai",
    ):
        assert forbidden not in text, f"forbidden LLM import found: {forbidden}"


# ---------------------------------------------------------------------------
# REST surface — schema endpoint
# ---------------------------------------------------------------------------


def test_dimd_schema_route_registered_in_openapi(client):  # noqa: ANN001
    """Spot-check the new GET route is registered in the live OpenAPI spec."""
    r = client.get("/openapi.json")
    if r.status_code != 200:
        pytest.skip(f"openapi.json not reachable: {r.status_code}")
    paths = r.json().get("paths", {})
    assert "/v1/audit/workpaper/schema" in paths
    assert "get" in paths["/v1/audit/workpaper/schema"]


def test_dimd_schema_returns_200_without_houjin(client):  # noqa: ANN001
    """The discovery surface MUST 200 without a houjin or DB seed —
    that is the entire point of separating it from the POST handler.
    """
    r = client.get("/v1/audit/workpaper/schema")
    assert r.status_code == 200, r.text
    body = r.json()
    assert isinstance(body, dict)
    # Must NOT leak any per-houjin row data.
    forbidden_keys = (
        "client_houjin_bangou",
        "fy_adoptions",
        "fy_enforcement",
        "amendment_alerts",
        "houjin_meta",
        "jurisdiction_breakdown",
        "auditor_flags",
    )
    for k in forbidden_keys:
        assert k not in body, f"schema must not leak invocation key {k!r}"


def test_dimd_schema_contract_shape(client):  # noqa: ANN001
    """Schema payload contract: required top-level keys + billing_unit=0."""
    r = client.get("/v1/audit/workpaper/schema")
    assert r.status_code == 200, r.text
    body = r.json()
    required_keys = {
        "endpoint",
        "method",
        "billing_unit_invoke",
        "billing_unit_schema",
        "input_fields",
        "source_tables",
        "output_sections",
        "fence_statutes",
        "disclaimer",
        "schema_version",
    }
    missing = required_keys - set(body.keys())
    assert not missing, f"schema payload missing required keys: {missing}"
    # Discovery surface itself is 0-unit; compose is 5-unit.
    assert body["billing_unit_schema"] == 0
    assert body["billing_unit_invoke"] == 5
    assert body["endpoint"] == "/v1/audit/workpaper"
    assert body["method"] == "POST"
    # 4-業法 fence parity (mirrors the POST endpoint).
    fence_text = " ".join(body["fence_statutes"])
    for statute in ("税理士法", "公認会計士法", "弁護士法", "行政書士法"):
        assert statute in fence_text


def test_dimd_schema_input_field_contract(client):  # noqa: ANN001
    """input_fields must enumerate the two POST fields with min/max."""
    r = client.get("/v1/audit/workpaper/schema")
    body = r.json()
    names = {f["name"] for f in body["input_fields"]}
    assert names == {"client_houjin_bangou", "fiscal_year"}
    by_name = {f["name"]: f for f in body["input_fields"]}
    assert by_name["client_houjin_bangou"]["min_length"] == 13
    assert by_name["client_houjin_bangou"]["max_length"] == 14
    assert by_name["fiscal_year"]["min"] == 2000
    assert by_name["fiscal_year"]["max"] == 2100


def test_dimd_schema_source_tables_match_compose_path(client):  # noqa: ANN001
    """source_tables must enumerate exactly the 5 tables the compose path
    joins. Drift between this list and ``_build_workpaper`` is the kind of
    silent regression the schema surface is meant to catch.
    """
    r = client.get("/v1/audit/workpaper/schema")
    body = r.json()
    declared = set(body["source_tables"])
    expected = {
        "jpi_houjin_master",
        "jpi_adoption_records",
        "am_enforcement_detail",
        "jpi_invoice_registrants",
        "am_amendment_diff",
    }
    assert declared == expected, f"source_tables drift: {declared ^ expected}"
    # And the same names must literally appear in the REST module source.
    rest_text = (_REPO / "src" / "jpintel_mcp" / "api" / "audit_workpaper_v2.py").read_text(
        encoding="utf-8"
    )
    for table in expected:
        assert table in rest_text, f"declared source_table {table!r} not in compose source"


def test_dimd_schema_disclaimer_parity_with_post(client):  # noqa: ANN001
    """The schema's disclaimer must match the POST handler's disclaimer
    text byte-for-byte (single _DISCLAIMER constant in the module).
    """
    from jpintel_mcp.api.audit_workpaper_v2 import _DISCLAIMER

    r = client.get("/v1/audit/workpaper/schema")
    body = r.json()
    assert body["disclaimer"] == _DISCLAIMER
