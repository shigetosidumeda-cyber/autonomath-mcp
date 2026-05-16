#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_DIR = ROOT / "schemas" / "jpcir"
FIXTURE_DIR = ROOT / "tests" / "fixtures" / "jpcir"


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _check_generated_schemas() -> int:
    schema_paths = sorted(SCHEMA_DIR.glob("*.schema.json"))
    if not schema_paths:
        raise AssertionError("no generated JPCIR schemas found")

    try:
        from jsonschema import Draft202012Validator
    except ImportError:
        return len(schema_paths)

    for path in schema_paths:
        schema = _load_json(path)
        if schema.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
            raise AssertionError(f"{path} is not a Draft 2020-12 schema")
        Draft202012Validator.check_schema(schema)
    return len(schema_paths)


def _validate_private_fact_capsule(instance: dict[str, Any]) -> None:
    schema = _load_json(SCHEMA_DIR / "private_fact_capsule.schema.json")
    try:
        from jsonschema import Draft202012Validator
    except ImportError:
        sys.path.insert(0, str(ROOT / "src"))
        from jpintel_mcp.agent_runtime.contracts import PrivateFactCapsule

        PrivateFactCapsule.model_validate(instance)
        return

    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(instance)


def _assert_private_fact_capsule_guards() -> None:
    schema = _load_json(SCHEMA_DIR / "private_fact_capsule.schema.json")
    properties = schema["properties"]
    record_properties = schema["$defs"]["PrivateFactCapsuleRecord"]["properties"]
    guard_paths = {
        "public_surface_export_allowed": properties["public_surface_export_allowed"],
        "source_receipt_compatible": properties["source_receipt_compatible"],
        "records[].public_claim_support": record_properties["public_claim_support"],
        "records[].source_receipt_compatible": record_properties["source_receipt_compatible"],
    }
    for field_path, field_schema in guard_paths.items():
        if field_schema.get("const") is not False:
            raise AssertionError(f"{field_path} must keep const false")


def _check_golden() -> int:
    checked = 0
    fixture_paths = sorted((FIXTURE_DIR / "golden" / "private_fact_capsule").glob("*.json"))
    for path in fixture_paths:
        _validate_private_fact_capsule(_load_json(path))
        checked += 1
    if checked == 0:
        raise AssertionError("no private_fact_capsule golden fixtures found")
    return checked


def _check_negative() -> int:
    checked = 0
    fixture_paths = sorted((FIXTURE_DIR / "negative" / "private_fact_capsule").glob("*.json"))
    for path in fixture_paths:
        try:
            _validate_private_fact_capsule(_load_json(path))
        except Exception:  # noqa: BLE001 - jsonschema and pydantic raise different types.
            checked += 1
            continue
        raise AssertionError(f"negative fixture unexpectedly validated: {path}")
    if checked == 0:
        raise AssertionError("no private_fact_capsule negative fixtures found")
    return checked


def main() -> int:
    schema_count = _check_generated_schemas()
    _assert_private_fact_capsule_guards()
    golden_count = _check_golden()
    negative_count = _check_negative()
    print(
        "JPCIR schema fixtures ok: "
        f"{schema_count} schemas, {golden_count} golden, {negative_count} negative"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
