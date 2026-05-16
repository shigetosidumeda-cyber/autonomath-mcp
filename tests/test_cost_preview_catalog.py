"""Tests for the cost preview + capability matrix artifacts.

These artifacts are static JSON files under ``site/.well-known/`` and
``site/releases/rc1-p0-bootstrap/``. They power agent discovery of jpcite's
pricing, free preview availability, daily caps, idempotency windows, and
the 169 MCP tools' free-vs-paid breakdown.

The tests verify:

  - Both cost preview catalogs (release-pinned + .well-known root) are
    well-formed and identical in content.
  - Every 14 paid outcome_contract_id from outcome_contract_catalog.json
    plus the 2 free controls (agent_routing_decision + cost_preview) are
    covered exactly once.
  - All prices live in the {0, 300, 600, 900} canonical band set.
  - Free outcomes carry ``estimated_price_jpy == 0`` and the 2 control
    outcomes match the free agent_routing_decision + cost_preview names.
  - ``pricing_or_cap_unconfirmed`` is the only allowed gap marker used
    when daily cap is null.
  - Each entry references ``jpcite_cost_jpy == 3``.
  - Capability matrix lists exactly 169 tools and reports a free + paid
    breakdown that sums to 169.
  - The cost preview path is published in
    ``site/.well-known/openapi-discovery.json`` for agent discovery.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

REPO_ROOT = Path(__file__).resolve().parent.parent

OUTCOME_CATALOG = (
    REPO_ROOT / "site" / "releases" / "rc1-p0-bootstrap" / "outcome_contract_catalog.json"
)
COST_PREVIEW_RELEASE = (
    REPO_ROOT / "site" / "releases" / "rc1-p0-bootstrap" / "cost_preview_catalog.json"
)
COST_PREVIEW_WELL_KNOWN = (
    REPO_ROOT / "site" / ".well-known" / "jpcite-cost-preview.json"
)
CAPABILITY_MATRIX = (
    REPO_ROOT / "site" / "releases" / "rc1-p0-bootstrap" / "capability_matrix.json"
)
OPENAPI_DISCOVERY = REPO_ROOT / "site" / ".well-known" / "openapi-discovery.json"
SCHEMA_REGISTRY = REPO_ROOT / "schemas" / "jpcir" / "_registry.json"
COST_PREVIEW_SCHEMA = (
    REPO_ROOT / "schemas" / "jpcir" / "cost_preview_catalog.schema.json"
)
MCP_SERVER = REPO_ROOT / "mcp-server.json"

CANONICAL_BANDS = {0, 300, 600, 900}
CANONICAL_GAP_ENUM = {
    "pricing_or_cap_unconfirmed",
    "source_freshness_unconfirmed",
    "coverage_thin",
    "schema_drift_possible",
    "approval_token_semantics_pending",
    "idempotency_window_provisional",
    "free_preview_endpoint_pending",
}
FREE_OUTCOMES = {"agent_routing_decision", "cost_preview"}


def _load(path: Path) -> dict[str, Any]:
    return cast("dict[str, Any]", json.loads(path.read_text()))


def _load_list(path: Path) -> list[dict[str, Any]]:
    return cast("list[dict[str, Any]]", json.loads(path.read_text()))


def test_cost_preview_release_catalog_is_well_formed_json() -> None:
    data = _load(COST_PREVIEW_RELEASE)
    assert isinstance(data, dict)
    assert data["schema_version"] == "jpcite.cost_preview_catalog.p0.v1"
    assert data["jpcite_cost_jpy_unit"] == 3
    assert data["price_bands"] == {"free": 0, "light": 300, "mid": 600, "heavy": 900}
    assert isinstance(data["entries"], list)
    assert len(data["entries"]) >= 1


def test_well_known_cost_preview_mirror_matches_release_pinned() -> None:
    """The .well-known root copy MUST be byte-identical to the release-pinned
    copy so agents that hit either URL see the same content."""
    release_body = COST_PREVIEW_RELEASE.read_text()
    well_known_body = COST_PREVIEW_WELL_KNOWN.read_text()
    assert release_body == well_known_body


def test_every_outcome_contract_has_cost_preview_entry() -> None:
    outcomes = _load_list(OUTCOME_CATALOG)
    preview = _load(COST_PREVIEW_RELEASE)

    outcome_ids = {o["outcome_contract_id"] for o in outcomes}
    preview_ids = {e["outcome_contract_id"] for e in preview["entries"]}

    missing = outcome_ids - preview_ids
    extra = preview_ids - outcome_ids
    assert not missing, f"cost_preview entries missing for outcomes: {missing}"
    assert not extra, f"cost_preview entries reference unknown outcomes: {extra}"


def test_no_duplicate_outcome_contract_ids_in_preview() -> None:
    preview = _load(COST_PREVIEW_RELEASE)
    ids = [e["outcome_contract_id"] for e in preview["entries"]]
    assert len(ids) == len(set(ids)), f"duplicate outcome_contract_id rows in cost preview: {ids}"


def test_all_prices_in_canonical_band() -> None:
    preview = _load(COST_PREVIEW_RELEASE)
    for entry in preview["entries"]:
        price = entry["estimated_price_jpy"]
        assert price in CANONICAL_BANDS, (
            f"{entry['outcome_contract_id']} price {price} not in {CANONICAL_BANDS}"
        )


def test_free_outcomes_have_zero_price_and_free_band() -> None:
    preview = _load(COST_PREVIEW_RELEASE)
    free_entries = {
        e["outcome_contract_id"]: e
        for e in preview["entries"]
        if e["outcome_contract_id"] in FREE_OUTCOMES
    }
    assert set(free_entries.keys()) == FREE_OUTCOMES, "the 2 free controls must both appear"
    for outcome_id, entry in free_entries.items():
        assert entry["cost_band"] == "free", outcome_id
        assert entry["estimated_price_jpy"] == 0, outcome_id
        assert entry["approval_token_required"] is False, outcome_id


def test_paid_outcomes_band_and_price_consistent() -> None:
    preview = _load(COST_PREVIEW_RELEASE)
    band_to_price = {"light": 300, "mid": 600, "heavy": 900}
    for entry in preview["entries"]:
        if entry["outcome_contract_id"] in FREE_OUTCOMES:
            continue
        band = entry["cost_band"]
        assert band in band_to_price, entry["outcome_contract_id"]
        assert entry["estimated_price_jpy"] == band_to_price[band], (
            f"{entry['outcome_contract_id']} band={band} price={entry['estimated_price_jpy']}"
        )


def test_all_entries_carry_jpcite_cost_jpy_3() -> None:
    preview = _load(COST_PREVIEW_RELEASE)
    for entry in preview["entries"]:
        assert entry["jpcite_cost_jpy"] == 3, entry["outcome_contract_id"]


def test_all_entries_have_free_preview_available_true() -> None:
    """Master plan requires a free preview endpoint for every paid packet."""
    preview = _load(COST_PREVIEW_RELEASE)
    for entry in preview["entries"]:
        assert entry["free_preview_available"] is True, (
            f"{entry['outcome_contract_id']} must expose a free cost preview"
        )
        if entry["preview_endpoint"] is not None:
            assert entry["preview_endpoint"].startswith(("/", "mcp:")), (
                f"{entry['outcome_contract_id']} preview_endpoint must be path or mcp: URI"
            )


def test_known_gaps_only_use_allowed_enum_values() -> None:
    preview = _load(COST_PREVIEW_RELEASE)
    for entry in preview["entries"]:
        for gap in entry["known_gaps"]:
            assert gap in CANONICAL_GAP_ENUM, (
                f"{entry['outcome_contract_id']} unknown gap marker: {gap}"
            )


def test_pricing_unconfirmed_gap_marks_null_cap_paid_entries() -> None:
    """When a paid outcome has null daily cap, the master plan §7 requires
    ``pricing_or_cap_unconfirmed`` so an agent can detect provisional pricing."""
    preview = _load(COST_PREVIEW_RELEASE)
    for entry in preview["entries"]:
        if entry["cost_band"] == "free":
            continue
        if entry["cap_per_day"] is None:
            assert "pricing_or_cap_unconfirmed" in entry["known_gaps"], (
                f"{entry['outcome_contract_id']} has null cap but no pricing_or_cap_unconfirmed gap"
            )


def test_idempotency_window_non_negative() -> None:
    preview = _load(COST_PREVIEW_RELEASE)
    for entry in preview["entries"]:
        assert entry["idempotency_window_seconds"] >= 0, entry["outcome_contract_id"]


def test_capability_matrix_has_exactly_169_tools() -> None:
    matrix = _load(CAPABILITY_MATRIX)
    assert matrix["tool_count"] == 169
    assert len(matrix["tools"]) == 169


def test_capability_matrix_free_paid_breakdown_sums_to_169() -> None:
    matrix = _load(CAPABILITY_MATRIX)
    breakdown = matrix["free_paid_breakdown"]
    assert breakdown["free"] + breakdown["paid"] == 169
    by_band = breakdown["by_band"]
    assert sum(by_band.values()) == 169
    assert by_band["free"] == breakdown["free"]


def test_capability_matrix_p0_facade_preserved() -> None:
    matrix = _load(CAPABILITY_MATRIX)
    assert matrix["full_catalog_default_visible"] is False
    assert set(matrix["p0_facade_tools"]) == {
        "jpcite_route",
        "jpcite_preview_cost",
        "jpcite_execute_packet",
        "jpcite_get_packet",
    }
    capabilities = {c["capability_id"]: c for c in matrix["capabilities"]}
    assert capabilities["jpcite_preview_cost"]["previewable"] is True
    assert capabilities["jpcite_execute_packet"]["billable"] is True
    assert capabilities["jpcite_route"]["billable"] is False


def test_capability_matrix_tool_entries_have_required_fields() -> None:
    matrix = _load(CAPABILITY_MATRIX)
    required = {
        "tool_id",
        "surface",
        "free_or_paid",
        "billing_units",
        "billable_unit_price_jpy",
        "cost_band",
        "estimated_price_jpy",
        "agent_handoff_kind",
    }
    for tool in matrix["tools"]:
        missing = required - set(tool.keys())
        assert not missing, f"{tool.get('tool_id')} missing fields: {missing}"
        assert tool["free_or_paid"] in {"free", "paid"}
        assert tool["cost_band"] in {"free", "light", "mid", "heavy"}
        assert tool["estimated_price_jpy"] in CANONICAL_BANDS
        assert tool["billable_unit_price_jpy"] in {0, 3}
        # The control facade (jpcite_route + cost_preview) MUST stay free.
        if tool["free_or_paid"] == "free":
            assert tool["billable_unit_price_jpy"] == 0
            assert tool["estimated_price_jpy"] == 0


def test_capability_matrix_tool_ids_match_mcp_server_json() -> None:
    matrix = _load(CAPABILITY_MATRIX)
    mcp = _load(MCP_SERVER)
    matrix_ids = {t["tool_id"] for t in matrix["tools"]}
    mcp_ids = {t["name"] for t in mcp["tools"]}
    assert matrix_ids == mcp_ids, (
        f"matrix/mcp drift: missing_in_matrix={mcp_ids - matrix_ids}, "
        f"extra_in_matrix={matrix_ids - mcp_ids}"
    )


def test_openapi_discovery_publishes_cost_preview_path() -> None:
    discovery = _load(OPENAPI_DISCOVERY)
    endpoints = discovery["discovery_endpoints"]
    assert "cost_preview_well_known" in endpoints
    assert endpoints["cost_preview_well_known"].endswith("/.well-known/jpcite-cost-preview.json")
    assert "cost_preview_release_pinned" in endpoints
    assert endpoints["cost_preview_release_pinned"].endswith(
        "/releases/rc1-p0-bootstrap/cost_preview_catalog.json"
    )
    assert "capability_matrix" in endpoints
    assert endpoints["capability_matrix"].endswith(
        "/releases/rc1-p0-bootstrap/capability_matrix.json"
    )


def test_cost_preview_schema_registered_in_jpcir_registry() -> None:
    registry = _load(SCHEMA_REGISTRY)
    names = {s["name"] for s in registry["schemas"]}
    assert "cost_preview_catalog" in names


def test_cost_preview_schema_is_well_formed() -> None:
    schema = _load(COST_PREVIEW_SCHEMA)
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["$id"].endswith("/cost_preview_catalog.schema.json")
    assert schema["title"] == "CostPreviewCatalog"
    # The schema MUST require the agent-discovery contract fields.
    required = set(schema["required"])
    assert {"catalog_id", "schema_version", "price_bands", "entries"} <= required


def test_subject_kind_is_canonical() -> None:
    preview = _load(COST_PREVIEW_RELEASE)
    allowed_kinds = {
        "program",
        "houjin",
        "invoice",
        "cohort",
        "watchlist",
        "query",
        "rule_change",
        "jurisdiction",
        "court",
        "statistic",
        "csv",
        "control",
    }
    for entry in preview["entries"]:
        assert entry["subject"]["kind"] in allowed_kinds, (
            f"{entry['outcome_contract_id']} bad subject.kind {entry['subject']['kind']}"
        )


def test_master_plan_contract_fields_present() -> None:
    """Master plan §1 requires every entry carry package_kind, subject,
    estimated_tokens_saved, source_count, known_gaps."""
    preview = _load(COST_PREVIEW_RELEASE)
    required_fields = {
        "package_kind",
        "subject",
        "estimated_tokens_saved",
        "source_count",
        "known_gaps",
    }
    for entry in preview["entries"]:
        missing = required_fields - set(entry.keys())
        assert not missing, f"{entry['outcome_contract_id']} missing: {missing}"


def test_agent_routing_decision_is_free_control_not_paid() -> None:
    """Master plan: agent_routing_decision MUST be a FREE control, never paid."""
    matrix = _load(CAPABILITY_MATRIX)
    route = next(
        (c for c in matrix["capabilities"] if c["capability_id"] == "jpcite_route"),
        None,
    )
    assert route is not None
    assert route["billable"] is False

    preview = _load(COST_PREVIEW_RELEASE)
    routing_entry = next(
        (e for e in preview["entries"] if e["outcome_contract_id"] == "agent_routing_decision"),
        None,
    )
    assert routing_entry is not None
    assert routing_entry["cost_band"] == "free"
    assert routing_entry["estimated_price_jpy"] == 0
