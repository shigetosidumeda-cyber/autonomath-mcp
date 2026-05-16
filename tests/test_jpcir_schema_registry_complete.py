"""Stream B: the jpcir schema registry must enumerate every published schema.

This test guards against silent registry drift: any new ``schemas/jpcir/*.schema.json``
file must be registered in ``_registry.json`` with a matching ``public_id`` and
relative ``path``. The Stream B addition (Evidence + 7 previously-missing
contracts) brings the registered set to 20 schemas.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = ROOT / "schemas" / "jpcir"
REGISTRY_PATH = SCHEMA_DIR / "_registry.json"

EXPECTED_SCHEMA_COUNT = 20

REQUIRED_SCHEMA_NAMES = frozenset(
    {
        "accepted_artifact_pricing",
        "agent_purchase_decision",
        "aws_noop_command_plan",
        "capability_matrix",
        "claim_ref",
        "consent_envelope",
        "evidence",
        "execution_graph",
        "gap_coverage_entry",
        "jpcir_header",
        "known_gap",
        "no_hit_lease",
        "outcome_contract",
        "policy_decision",
        "private_fact_capsule",
        "release_capsule_manifest",
        "scoped_cap_token",
        "source_receipt",
        "spend_simulation",
        "teardown_simulation",
    }
)


def _load_registry() -> dict[str, object]:
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def test_registry_capsule_id_and_schema_version_are_pinned() -> None:
    registry = _load_registry()

    assert registry["capsule_id"]
    assert registry["schema_version"] == "jpcite.jpcir_schema_registry.p0.v1"


def test_registry_lists_all_published_schema_files() -> None:
    registry = _load_registry()
    registered_names = {entry["name"] for entry in registry["schemas"]}

    on_disk_names = {
        path.name.removesuffix(".schema.json") for path in SCHEMA_DIR.glob("*.schema.json")
    }

    assert on_disk_names == REQUIRED_SCHEMA_NAMES, (
        "schemas on disk drifted from REQUIRED_SCHEMA_NAMES; "
        f"missing={REQUIRED_SCHEMA_NAMES - on_disk_names} "
        f"unexpected={on_disk_names - REQUIRED_SCHEMA_NAMES}"
    )
    assert registered_names == REQUIRED_SCHEMA_NAMES, (
        "registry entries drifted from REQUIRED_SCHEMA_NAMES; "
        f"missing={REQUIRED_SCHEMA_NAMES - registered_names} "
        f"unexpected={registered_names - REQUIRED_SCHEMA_NAMES}"
    )


def test_registry_has_exactly_twenty_entries() -> None:
    registry = _load_registry()
    assert len(registry["schemas"]) == EXPECTED_SCHEMA_COUNT


def test_registry_entries_are_internally_consistent() -> None:
    registry = _load_registry()

    for entry in registry["schemas"]:
        name = entry["name"]
        path = entry["path"]
        public_id = entry["public_id"]

        assert path == f"schemas/jpcir/{name}.schema.json"
        assert public_id == f"https://jpcite.com/schemas/jpcir/{name}.schema.json"
        assert (ROOT / path).is_file()


def test_each_registered_schema_uses_draft_2020_12_and_forbids_additional_properties() -> None:
    registry = _load_registry()

    for entry in registry["schemas"]:
        schema_path = ROOT / entry["path"]
        schema = json.loads(schema_path.read_text(encoding="utf-8"))

        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        assert schema["additionalProperties"] is False
        assert schema["$id"] == entry["public_id"]


def test_new_stream_b_schemas_are_present_on_disk() -> None:
    new_schemas = {
        "source_receipt",
        "claim_ref",
        "known_gap",
        "gap_coverage_entry",
        "no_hit_lease",
        "policy_decision",
        "accepted_artifact_pricing",
        "evidence",
    }

    for name in new_schemas:
        path = SCHEMA_DIR / f"{name}.schema.json"
        assert path.is_file(), f"missing schema file: {path}"
