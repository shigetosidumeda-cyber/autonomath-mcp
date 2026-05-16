"""Extended check tests for the static P0 release capsule validator.

These tests cover the 5 additional checks Stream H added on 2026-05-16:

1. schema parity between ``contracts.py`` and ``schemas/jpcir/*.schema.json``
2. ``outcome_catalog.json`` deliverables all carry ``estimated_price_jpy > 0``
3. ``inline_registry.INLINE_PACKET_ALIASES`` matches ``inline_packets.json``
4. ``preflight_scorecard.json`` blocking_gates is exactly 5
5. ``server.json`` / ``agents.json`` / ``llms.json`` tool counts agree

The original 12 checks remain green; ``test_release_capsule_validator.py``
exercises those. Here we focus exclusively on the new helpers + the integration
``validate_release_capsule`` wiring.
"""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from scripts.ops.validate_release_capsule import (  # noqa: E402
    AGENTS_JSON_PATH,
    CONTRACTS_PY_PATH,
    EXPECTED_OUTCOME_CATALOG_DELIVERABLE_COUNT,
    EXPECTED_PREFLIGHT_BLOCKING_GATE_COUNT,
    EXPECTED_SCHEMA_PARITY_COUNT,
    INLINE_PACKETS_PATH,
    INLINE_REGISTRY_PATH,
    LLMS_JSON_PATH,
    OUTCOME_CATALOG_PATH,
    PREFLIGHT_SCORECARD_PATH,
    SCHEMAS_DIR,
    SERVER_JSON_PATH,
    _camel_to_snake,
    _extract_agents_tool_count,
    _extract_llms_tool_count,
    _extract_server_tool_count,
    _parse_inline_alias_map,
    _validate_discovery_surface_parity,
    _validate_inline_packet_aliases,
    _validate_outcome_pricing_complete,
    _validate_preflight_gate_count,
    _validate_schema_parity,
    validate_release_capsule,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def _write_json(root: Path, relative_path: Path, data: object) -> None:
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# 1. schema parity
# ---------------------------------------------------------------------------


def test_camel_to_snake_conversion() -> None:
    assert _camel_to_snake("Evidence") == "evidence"
    assert _camel_to_snake("OutcomeContract") == "outcome_contract"
    assert _camel_to_snake("AwsNoopCommandPlan") == "aws_noop_command_plan"
    assert _camel_to_snake("JpcirHeader") == "jpcir_header"


def test_schema_parity_passes_on_real_tree() -> None:
    errors: list[str] = []
    _validate_schema_parity(REPO_ROOT, errors)
    assert errors == [], errors


def test_schema_parity_fails_when_schema_count_drifts(tmp_path: Path) -> None:
    # Stage a mini tree with one fewer schema than EXPECTED_SCHEMA_PARITY_COUNT.
    contracts_dst = tmp_path / CONTRACTS_PY_PATH
    contracts_dst.parent.mkdir(parents=True, exist_ok=True)
    contracts_dst.write_text(
        (REPO_ROOT / CONTRACTS_PY_PATH).read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    schemas_dst = tmp_path / SCHEMAS_DIR
    schemas_dst.mkdir(parents=True, exist_ok=True)
    real_schemas = sorted((REPO_ROOT / SCHEMAS_DIR).glob("*.schema.json"))
    # Copy all but the last schema to simulate drift.
    for schema in real_schemas[:-1]:
        (schemas_dst / schema.name).write_text(schema.read_text(encoding="utf-8"), encoding="utf-8")

    errors: list[str] = []
    _validate_schema_parity(tmp_path, errors)
    assert any("schema parity" in e and "schema files" in e for e in errors), errors


def test_schema_parity_skips_silently_when_source_tree_missing(tmp_path: Path) -> None:
    """Stub trees without source files should pass through without errors.

    Existing capsule fixtures in ``test_release_capsule_validator.py`` rely on
    this behaviour: they stage only the capsule JSON files under a tmp_path,
    and we must not regress them.
    """

    errors: list[str] = []
    _validate_schema_parity(tmp_path, errors)
    assert errors == [], errors


def test_schema_parity_fails_when_contracts_has_no_strict_models(tmp_path: Path) -> None:
    """If contracts.py exists but has zero StrictModel classes, fail closed."""

    contracts_dst = tmp_path / CONTRACTS_PY_PATH
    contracts_dst.parent.mkdir(parents=True, exist_ok=True)
    contracts_dst.write_text("# empty stub\n", encoding="utf-8")
    schemas_dst = tmp_path / SCHEMAS_DIR
    schemas_dst.mkdir(parents=True, exist_ok=True)
    (schemas_dst / "evidence.schema.json").write_text("{}", encoding="utf-8")
    errors: list[str] = []
    _validate_schema_parity(tmp_path, errors)
    assert any("no StrictModel classes" in e for e in errors), errors


def test_schema_parity_constant_matches_real_tree() -> None:
    schema_count = len(list((REPO_ROOT / SCHEMAS_DIR).glob("*.schema.json")))
    assert schema_count == EXPECTED_SCHEMA_PARITY_COUNT, (
        f"schema parity constant drifted: schemas={schema_count}, "
        f"expected={EXPECTED_SCHEMA_PARITY_COUNT}"
    )


# ---------------------------------------------------------------------------
# 2. outcome pricing complete
# ---------------------------------------------------------------------------


def _real_outcome_catalog() -> dict[str, Any]:
    return json.loads((REPO_ROOT / OUTCOME_CATALOG_PATH).read_text(encoding="utf-8"))


def test_outcome_pricing_complete_on_real_catalog() -> None:
    errors: list[str] = []
    _validate_outcome_pricing_complete(_real_outcome_catalog(), errors)
    assert errors == [], errors


def test_outcome_pricing_detects_zero_price() -> None:
    catalog = deepcopy(_real_outcome_catalog())
    catalog["deliverables"][0]["estimated_price_jpy"] = 0
    errors: list[str] = []
    _validate_outcome_pricing_complete(catalog, errors)
    assert any("missing estimated_price_jpy" in e for e in errors), errors


def test_outcome_pricing_detects_missing_price() -> None:
    catalog = deepcopy(_real_outcome_catalog())
    catalog["deliverables"][0].pop("estimated_price_jpy", None)
    errors: list[str] = []
    _validate_outcome_pricing_complete(catalog, errors)
    assert any("missing estimated_price_jpy" in e for e in errors), errors


def test_outcome_pricing_detects_wrong_count() -> None:
    catalog = deepcopy(_real_outcome_catalog())
    catalog["deliverables"] = catalog["deliverables"][:-1]
    errors: list[str] = []
    _validate_outcome_pricing_complete(catalog, errors)
    assert any("expected" in e and "deliverables" in e for e in errors), errors


def test_outcome_catalog_deliverable_count_matches_constant() -> None:
    catalog = _real_outcome_catalog()
    assert len(catalog["deliverables"]) == EXPECTED_OUTCOME_CATALOG_DELIVERABLE_COUNT


# ---------------------------------------------------------------------------
# 3. inline packet alias parity
# ---------------------------------------------------------------------------


def _real_inline_packets() -> dict[str, Any]:
    return json.loads((REPO_ROOT / INLINE_PACKETS_PATH).read_text(encoding="utf-8"))


def test_inline_alias_map_parses_from_real_registry() -> None:
    alias_map = _parse_inline_alias_map(REPO_ROOT)
    assert alias_map is not None
    assert "evidence_answer" in alias_map
    assert alias_map["p0_evidence_answer"] == "evidence_answer"
    assert alias_map["p0_source_receipt_ledger"] == "source_receipt_ledger"


def test_inline_packet_aliases_pass_on_real_capsule() -> None:
    errors: list[str] = []
    _validate_inline_packet_aliases(REPO_ROOT, _real_inline_packets(), errors)
    assert errors == [], errors


def test_inline_packet_aliases_detect_missing_alias_id() -> None:
    inline = deepcopy(_real_inline_packets())
    inline["alias_ids"] = [a for a in inline["alias_ids"] if a != "p0_evidence_answer"]
    errors: list[str] = []
    _validate_inline_packet_aliases(REPO_ROOT, inline, errors)
    assert any("alias_ids missing" in e for e in errors), errors


def test_inline_packet_aliases_detect_unknown_packet_id() -> None:
    inline = deepcopy(_real_inline_packets())
    inline["packet_ids"] = inline["packet_ids"] + ["bogus_packet"]
    errors: list[str] = []
    _validate_inline_packet_aliases(REPO_ROOT, inline, errors)
    assert any("packet_ids carries unknown entries" in e for e in errors), errors


def test_inline_packet_aliases_skip_silently_when_registry_missing(tmp_path: Path) -> None:
    """Missing source-side registry on a stub tree -> no errors."""

    errors: list[str] = []
    _validate_inline_packet_aliases(tmp_path, {}, errors)
    assert errors == [], errors


def test_inline_packet_aliases_fail_when_registry_unparseable(tmp_path: Path) -> None:
    """Registry present but ``INLINE_PACKET_ALIASES`` not found -> fail closed."""

    registry_dst = tmp_path / INLINE_REGISTRY_PATH
    registry_dst.parent.mkdir(parents=True, exist_ok=True)
    registry_dst.write_text("# no ALIASES here\n", encoding="utf-8")
    errors: list[str] = []
    _validate_inline_packet_aliases(tmp_path, {}, errors)
    assert any("could not parse INLINE_PACKET_ALIASES" in e for e in errors), errors


# ---------------------------------------------------------------------------
# 4. preflight gate count
# ---------------------------------------------------------------------------


def _real_preflight() -> dict[str, Any]:
    return json.loads((REPO_ROOT / PREFLIGHT_SCORECARD_PATH).read_text(encoding="utf-8"))


def test_preflight_gate_count_passes_on_real_scorecard() -> None:
    errors: list[str] = []
    _validate_preflight_gate_count(_real_preflight(), errors)
    assert errors == [], errors


def test_preflight_gate_count_detects_drift_below_five() -> None:
    pre = deepcopy(_real_preflight())
    pre["blocking_gates"] = pre["blocking_gates"][:-1]
    errors: list[str] = []
    _validate_preflight_gate_count(pre, errors)
    assert any(f"expected {EXPECTED_PREFLIGHT_BLOCKING_GATE_COUNT}" in e for e in errors), errors


def test_preflight_gate_count_detects_drift_above_five() -> None:
    pre = deepcopy(_real_preflight())
    pre["blocking_gates"] = pre["blocking_gates"] + ["extra_gate_oops"]
    errors: list[str] = []
    _validate_preflight_gate_count(pre, errors)
    assert any(f"expected {EXPECTED_PREFLIGHT_BLOCKING_GATE_COUNT}" in e for e in errors), errors


def test_preflight_gate_count_detects_duplicates() -> None:
    pre = deepcopy(_real_preflight())
    pre["blocking_gates"] = pre["blocking_gates"][:-1] + [pre["blocking_gates"][0]]
    errors: list[str] = []
    _validate_preflight_gate_count(pre, errors)
    assert any("must be unique" in e for e in errors), errors


# ---------------------------------------------------------------------------
# 5. discovery surface parity
# ---------------------------------------------------------------------------


def _real_server_json() -> dict[str, Any]:
    return json.loads((REPO_ROOT / SERVER_JSON_PATH).read_text(encoding="utf-8"))


def _real_agents_json() -> dict[str, Any]:
    return json.loads((REPO_ROOT / AGENTS_JSON_PATH).read_text(encoding="utf-8"))


def _real_llms_json() -> dict[str, Any]:
    return json.loads((REPO_ROOT / LLMS_JSON_PATH).read_text(encoding="utf-8"))


def test_discovery_surface_parity_extractors_return_ints() -> None:
    server_count = _extract_server_tool_count(_real_server_json())
    agents_count = _extract_agents_tool_count(_real_agents_json())
    llms_count = _extract_llms_tool_count(_real_llms_json())
    assert isinstance(server_count, int) and server_count > 0
    assert isinstance(agents_count, int) and agents_count > 0
    # llms.json may legitimately omit a count; if present it must be an int.
    assert llms_count is None or isinstance(llms_count, int)


def test_discovery_surface_parity_passes_on_real_tree() -> None:
    errors: list[str] = []
    _validate_discovery_surface_parity(
        _real_server_json(),
        _real_agents_json(),
        _real_llms_json(),
        errors,
    )
    assert errors == [], errors


def test_discovery_surface_parity_detects_mismatch() -> None:
    server_json = deepcopy(_real_server_json())
    server_json["_meta"]["io.modelcontextprotocol.registry/publisher-provided"]["tool_count"] = 999
    errors: list[str] = []
    _validate_discovery_surface_parity(
        server_json,
        _real_agents_json(),
        _real_llms_json(),
        errors,
    )
    assert any("tool count mismatch" in e for e in errors), errors


def test_discovery_surface_parity_handles_missing_count() -> None:
    errors: list[str] = []
    _validate_discovery_surface_parity(
        {"_meta": {}},
        {},
        {},
        errors,
    )
    assert any("server.json missing tool_count" in e for e in errors), errors
    assert any("agents.json missing tools_count.public_default" in e for e in errors), errors


# ---------------------------------------------------------------------------
# Integration: full validator run still green
# ---------------------------------------------------------------------------


def test_full_validator_on_real_repo_is_clean() -> None:
    """Sanity check that the 5 new helpers do not regress the 12 originals."""

    errors = validate_release_capsule(REPO_ROOT)
    assert errors == [], errors


@pytest.mark.parametrize(
    "constant_name,expected",
    [
        ("EXPECTED_SCHEMA_PARITY_COUNT", EXPECTED_SCHEMA_PARITY_COUNT),
        (
            "EXPECTED_OUTCOME_CATALOG_DELIVERABLE_COUNT",
            EXPECTED_OUTCOME_CATALOG_DELIVERABLE_COUNT,
        ),
        ("EXPECTED_PREFLIGHT_BLOCKING_GATE_COUNT", EXPECTED_PREFLIGHT_BLOCKING_GATE_COUNT),
    ],
)
def test_extended_check_constants_are_positive(constant_name: str, expected: int) -> None:
    assert expected > 0, f"{constant_name} must be > 0"
