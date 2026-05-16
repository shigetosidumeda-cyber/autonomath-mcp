from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = ROOT / "schemas" / "jpcir"
FIXTURE_DIR = ROOT / "tests" / "fixtures" / "jpcir"


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _schema_for(schema_name: str) -> dict[str, Any]:
    return _load_json(SCHEMA_DIR / f"{schema_name}.schema.json")


def _check_schema(schema: dict[str, Any]) -> None:
    try:
        from jsonschema import Draft202012Validator
    except ImportError:
        return

    Draft202012Validator.check_schema(schema)


def _validate_private_fact_capsule(instance: dict[str, Any]) -> None:
    schema = _schema_for("private_fact_capsule")
    try:
        from jsonschema import Draft202012Validator
    except ImportError:
        from jpintel_mcp.agent_runtime.contracts import PrivateFactCapsule

        PrivateFactCapsule.model_validate(instance)
        return

    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(instance)


def _validation_error_message(instance: dict[str, Any]) -> str:
    try:
        _validate_private_fact_capsule(instance)
    except Exception as exc:  # noqa: BLE001 - test accepts jsonschema or pydantic.
        return str(exc)
    raise AssertionError("fixture unexpectedly validated")


def _private_fact_capsule_schema_field(name: str) -> dict[str, Any]:
    return _schema_for("private_fact_capsule")["properties"][name]


def _private_fact_capsule_record_schema_field(name: str) -> dict[str, Any]:
    record_schema = _schema_for("private_fact_capsule")["$defs"]["PrivateFactCapsuleRecord"]
    return record_schema["properties"][name]


def test_private_fact_capsule_schema_keeps_private_export_guards() -> None:
    assert _private_fact_capsule_schema_field("public_surface_export_allowed")["const"] is False
    assert _private_fact_capsule_schema_field("source_receipt_compatible")["const"] is False
    assert _private_fact_capsule_record_schema_field("public_claim_support")["const"] is False
    assert _private_fact_capsule_record_schema_field("source_receipt_compatible")["const"] is False


def test_generated_jpcir_schemas_are_valid_draft_2020_12() -> None:
    schema_paths = sorted(SCHEMA_DIR.glob("*.schema.json"))

    assert schema_paths
    for path in schema_paths:
        schema = _load_json(path)
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        _check_schema(schema)


@pytest.mark.parametrize(
    "fixture_path",
    sorted((FIXTURE_DIR / "golden" / "private_fact_capsule").glob("*.json")),
    ids=lambda path: path.name,
)
def test_private_fact_capsule_golden_fixtures_match_schema(
    fixture_path: Path,
) -> None:
    _validate_private_fact_capsule(_load_json(fixture_path))


@pytest.mark.parametrize(
    ("fixture_path", "expected_fragment"),
    [
        (
            FIXTURE_DIR
            / "negative"
            / "private_fact_capsule"
            / "public_surface_export_allowed_true.json",
            "False",
        ),
        (
            FIXTURE_DIR
            / "negative"
            / "private_fact_capsule"
            / "source_receipt_compatible_true.json",
            "False",
        ),
    ],
    ids=lambda item: item.name if isinstance(item, Path) else item,
)
def test_private_fact_capsule_negative_fixtures_reject_public_or_receipt_use(
    fixture_path: Path,
    expected_fragment: str,
) -> None:
    error_message = _validation_error_message(_load_json(fixture_path))

    assert expected_fragment in error_message


def test_private_fact_capsule_fixture_sets_are_not_empty() -> None:
    assert list((FIXTURE_DIR / "golden" / "private_fact_capsule").glob("*.json"))
    assert list((FIXTURE_DIR / "negative" / "private_fact_capsule").glob("*.json"))
