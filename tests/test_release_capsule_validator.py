import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest

from jpintel_mcp.agent_runtime.aws_execution_templates import (
    build_aws_execution_template_catalog,
)
from jpintel_mcp.agent_runtime.outcome_source_crosswalk import (
    build_outcome_source_crosswalk_shape,
)
from jpintel_mcp.agent_runtime.packet_skeletons import (
    build_public_packet_skeleton_catalog_shape,
)
from jpintel_mcp.services.packets.inline_registry import build_inline_packet_catalog_shape
from scripts.ops.validate_release_capsule import (
    ACCOUNTING_CSV_PROFILES_PATH,
    ALGORITHM_BLUEPRINTS_PATH,
    AWS_EXECUTION_TEMPLATES_PATH,
    AWS_SPEND_PROGRAM_PATH,
    CAPABILITY_MATRIX_PATH,
    INLINE_PACKETS_PATH,
    MANIFEST_PATH,
    OUTCOME_CATALOG_PATH,
    OUTCOME_SOURCE_CROSSWALK_PATH,
    P0_FACADE_PATH,
    PACKET_SKELETONS_PATH,
    PREFLIGHT_SCORECARD_PATH,
    PUBLIC_CATALOG_SURFACE_PATHS,
    PUBLIC_SOURCE_DOMAINS_PATH,
    RUNTIME_POINTER_PATH,
    WELL_KNOWN_RELEASE_PATH,
    validate_release_capsule,
)

CAPSULE_ID = "rc1-p0-bootstrap-2026-05-15"


def _write_json(root: Path, relative_path: Path, data: object) -> None:
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _valid_artifacts() -> dict[Path, object]:
    return {
        WELL_KNOWN_RELEASE_PATH: {
            "active_capsule_id": CAPSULE_ID,
            "active_capsule_manifest": "/releases/rc1-p0-bootstrap/release_capsule_manifest.json",
            "aws_runtime_dependency_allowed": False,
            "capsule_state": "candidate",
            "live_aws_commands_allowed": False,
            "manifest_path": "/releases/rc1-p0-bootstrap/release_capsule_manifest.json",
            "manifest_sha256": "",
            "p0_facade_path": "/releases/rc1-p0-bootstrap/agent_surface/p0_facade.json",
            "runtime_pointer_path": "/releases/current/runtime_pointer.json",
            "schema_version": "jpcite.well_known_release.p0.v1",
        },
        RUNTIME_POINTER_PATH: {
            "active_capsule_id": CAPSULE_ID,
            "active_capsule_manifest": "/releases/rc1-p0-bootstrap/release_capsule_manifest.json",
            "aws_runtime_dependency_allowed": False,
            "capsule_state": "candidate",
            "live_aws_commands_allowed": False,
            "schema_version": "jpcite.runtime_pointer.p0.v1",
        },
        MANIFEST_PATH: {
            "aws_runtime_dependency_allowed": False,
            "capability_matrix_path": "/releases/rc1-p0-bootstrap/capability_matrix.json",
            "capsule_id": CAPSULE_ID,
            "capsule_state": "candidate",
            "generated_surfaces": [
                "/releases/current/runtime_pointer.json",
                "/releases/rc1-p0-bootstrap/agent_surface/p0_facade.json",
                "/releases/rc1-p0-bootstrap/release_capsule_manifest.json",
                "/releases/rc1-p0-bootstrap/preflight_scorecard.json",
                "/releases/rc1-p0-bootstrap/outcome_catalog.json",
                "/releases/rc1-p0-bootstrap/accounting_csv_profiles.json",
                "/releases/rc1-p0-bootstrap/algorithm_blueprints.json",
                "/releases/rc1-p0-bootstrap/outcome_source_crosswalk.json",
                "/releases/rc1-p0-bootstrap/packet_skeletons.json",
                "/releases/rc1-p0-bootstrap/inline_packets.json",
                "/releases/rc1-p0-bootstrap/public_source_domains.json",
                "/releases/rc1-p0-bootstrap/aws_spend_program.json",
                "/releases/rc1-p0-bootstrap/aws_execution_templates.json",
                "/.well-known/jpcite-release.json",
            ],
            "real_csv_runtime_enabled": False,
            "request_time_llm_fact_generation_enabled": False,
        },
        P0_FACADE_PATH: {
            "aws_runtime_dependency_allowed": False,
            "capsule_id": CAPSULE_ID,
            "default_visibility": "p0_facade_only",
            "full_catalog_visible_by_default": False,
            "request_time_llm_fact_generation_enabled": False,
            "schema_version": "jpcite.agent_facade.p0.v1",
            "tools": [
                {"name": "jpcite_route"},
                {"name": "jpcite_preview_cost"},
                {"name": "jpcite_execute_packet"},
                {"name": "jpcite_get_packet"},
            ],
        },
        CAPABILITY_MATRIX_PATH: {
            "capabilities": [
                {"capability_id": "jpcite_route"},
                {"capability_id": "jpcite_preview_cost"},
                {"capability_id": "jpcite_execute_packet"},
                {"capability_id": "jpcite_get_packet"},
            ],
            "full_catalog_default_visible": False,
            "generated_from_capsule_id": CAPSULE_ID,
            "matrix_id": f"{CAPSULE_ID}:capability-matrix",
            "p0_facade_tools": [
                "jpcite_route",
                "jpcite_preview_cost",
                "jpcite_execute_packet",
                "jpcite_get_packet",
            ],
        },
        PREFLIGHT_SCORECARD_PATH: {
            "blocking_gates": [
                "policy_trust_csv_boundaries",
                "accepted_artifact_billing_contract",
                "aws_budget_cash_guard_canary",
                "spend_simulation_pass_state",
                "teardown_simulation_pass_state",
            ],
            "capsule_id": CAPSULE_ID,
            "cash_bill_guard_enabled": True,
            "live_aws_commands_allowed": False,
            "schema_version": "jpcite.preflight_scorecard.p0.v1",
            "state": "AWS_BLOCKED_PRE_FLIGHT",
            "target_credit_conversion_usd": 19490,
        },
        OUTCOME_CATALOG_PATH: {
            "schema_version": "jpcite.outcome_catalog.p0.v1",
            "request_time_llm_dependency": False,
            "live_network_dependency": False,
            "live_aws_dependency": False,
            "no_hit_semantics": "no_hit_not_absence",
            "deliverables": [
                {
                    "api_wiring_required": False,
                    "request_time_llm_dependency": False,
                    "live_network_dependency": False,
                    "live_aws_dependency": False,
                    "no_hit_semantics": "no_hit_not_absence",
                }
            ],
        },
        ACCOUNTING_CSV_PROFILES_PATH: {
            "schema_version": "jpcite.accounting_csv_profiles.p0.v1",
            "blocked_downstream_outputs": [
                "public_packet_claim",
                "public_source_receipt",
                "absence_or_completeness_claim",
                "certified_accounting_import_file",
                "row_level_export_without_consent",
            ],
            "profiles": [
                {
                    "account_category_policy": {
                        "derived_category_allowed": False,
                    },
                    "blocked_downstream_outputs": [
                        "public_packet_claim",
                        "public_source_receipt",
                        "absence_or_completeness_claim",
                        "certified_accounting_import_file",
                        "row_level_export_without_consent",
                    ],
                    "official_certification_claimed": False,
                }
            ],
        },
        ALGORITHM_BLUEPRINTS_PATH: {
            "schema_version": "jpcite.algorithm_blueprints.p0.v1",
            "llm_allowed": False,
            "network_allowed": False,
            "no_hit_semantics": "no_hit_not_absence",
            "blueprints": [
                {
                    "advice_boundary": {
                        "asserts_legal_or_accounting_advice": False,
                    },
                    "gap_handling": {
                        "absence_claim_enabled": False,
                        "no_hit_semantics": "no_hit_not_absence",
                    },
                    "llm_allowed": False,
                    "network_allowed": False,
                    "proof_handling": {
                        "private_csv_can_support_public_claims": False,
                    },
                }
            ],
        },
        OUTCOME_SOURCE_CROSSWALK_PATH: build_outcome_source_crosswalk_shape(),
        PACKET_SKELETONS_PATH: build_public_packet_skeleton_catalog_shape(),
        INLINE_PACKETS_PATH: build_inline_packet_catalog_shape(),
        PUBLIC_SOURCE_DOMAINS_PATH: {
            "schema_version": "jpcite.public_source_domains.p0.v1",
            "collection_enabled_initially": False,
            "playwright_screenshot_max_px": 1600,
            "catalog": [
                {
                    "bulk_resale_or_redistribution_allowed": False,
                    "collection_enabled_initially": False,
                    "pii_collection_allowed": False,
                    "playwright_screenshot_policy": {
                        "full_page_capture_allowed": False,
                        "max_bitmap_long_edge_px": 1600,
                    },
                    "robots_terms_posture": {
                        "robots_txt_must_be_checked": True,
                        "stop_on_disallow_or_terms_conflict": True,
                        "terms_must_be_reviewed": True,
                    },
                }
            ],
        },
        AWS_SPEND_PROGRAM_PATH: {
            "schema_version": "jpcite.aws_spend_program.p0.v1",
            "target_credit_spend_usd": 19490,
            "planned_target_sum_usd": 19490,
            "live_execution_allowed": False,
            "preflight_evidence_passed": False,
            "execution_mode": "offline_non_mutating_blueprint",
            "batches": [
                {
                    "aws_calls_allowed": False,
                    "execution_mode": "offline_non_mutating_blueprint",
                    "mutates_live_aws": False,
                    "network_calls_allowed": False,
                    "subprocess_allowed": False,
                }
            ],
        },
        AWS_EXECUTION_TEMPLATES_PATH: build_aws_execution_template_catalog(),
    }


def _write_valid_tree(root: Path) -> dict[Path, object]:
    artifacts = deepcopy(_valid_artifacts())
    for relative_path, data in artifacts.items():
        _write_json(root, relative_path, data)
    well_known = artifacts[WELL_KNOWN_RELEASE_PATH]
    assert isinstance(well_known, dict)
    well_known["manifest_sha256"] = hashlib.sha256((root / MANIFEST_PATH).read_bytes()).hexdigest()
    _write_json(root, WELL_KNOWN_RELEASE_PATH, well_known)
    return artifacts


def test_checked_in_release_capsule_passes_static_pointer_validation() -> None:
    repo_root = Path(__file__).resolve().parents[1]

    assert validate_release_capsule(repo_root) == []


def test_missing_required_file_fails_closed(tmp_path: Path) -> None:
    _write_valid_tree(tmp_path)
    (tmp_path / P0_FACADE_PATH).unlink()

    errors = validate_release_capsule(tmp_path)

    assert any("missing file" in error and str(P0_FACADE_PATH) in error for error in errors)


def test_runtime_pointer_rejects_live_aws_enabled(tmp_path: Path) -> None:
    artifacts = _write_valid_tree(tmp_path)
    pointer = artifacts[RUNTIME_POINTER_PATH]
    assert isinstance(pointer, dict)
    pointer["live_aws_commands_allowed"] = True
    _write_json(tmp_path, RUNTIME_POINTER_PATH, pointer)

    errors = validate_release_capsule(tmp_path)

    assert any("live_aws_commands_allowed=false" in error for error in errors)


def test_manifest_rejects_llm_and_real_csv_runtime(tmp_path: Path) -> None:
    artifacts = _write_valid_tree(tmp_path)
    manifest = artifacts[MANIFEST_PATH]
    assert isinstance(manifest, dict)
    manifest["request_time_llm_fact_generation_enabled"] = True
    manifest["real_csv_runtime_enabled"] = True
    _write_json(tmp_path, MANIFEST_PATH, manifest)

    errors = validate_release_capsule(tmp_path)

    assert any("request_time_llm_fact_generation_enabled=false" in error for error in errors)
    assert any("real_csv_runtime_enabled=false" in error for error in errors)


def test_facade_and_matrix_reject_full_catalog_default_visibility(tmp_path: Path) -> None:
    artifacts = _write_valid_tree(tmp_path)
    facade = artifacts[P0_FACADE_PATH]
    matrix = artifacts[CAPABILITY_MATRIX_PATH]
    assert isinstance(facade, dict)
    assert isinstance(matrix, dict)
    facade["full_catalog_visible_by_default"] = True
    matrix["full_catalog_default_visible"] = True
    _write_json(tmp_path, P0_FACADE_PATH, facade)
    _write_json(tmp_path, CAPABILITY_MATRIX_PATH, matrix)

    errors = validate_release_capsule(tmp_path)

    assert any("full_catalog_visible_by_default=false" in error for error in errors)
    assert any("full_catalog_default_visible=false" in error for error in errors)


def test_rejects_p0_tool_mismatch(tmp_path: Path) -> None:
    artifacts = _write_valid_tree(tmp_path)
    matrix = artifacts[CAPABILITY_MATRIX_PATH]
    assert isinstance(matrix, dict)
    matrix["p0_facade_tools"] = ["jpcite_preview_cost"]
    _write_json(tmp_path, CAPABILITY_MATRIX_PATH, matrix)

    errors = validate_release_capsule(tmp_path)

    assert any("capability matrix P0 tools mismatch" in error for error in errors)


def test_manifest_rejects_generated_surface_missing_on_disk(tmp_path: Path) -> None:
    artifacts = _write_valid_tree(tmp_path)
    manifest = artifacts[MANIFEST_PATH]
    assert isinstance(manifest, dict)
    manifest["generated_surfaces"] = [
        *manifest["generated_surfaces"],
        "/releases/rc1-p0-bootstrap/missing_surface.json",
    ]
    _write_json(tmp_path, MANIFEST_PATH, manifest)

    errors = validate_release_capsule(tmp_path)

    assert any("generated_surfaces path does not exist" in error for error in errors)


@pytest.mark.parametrize("public_surface_path", PUBLIC_CATALOG_SURFACE_PATHS)
def test_manifest_rejects_missing_new_public_generated_surface(
    tmp_path: Path,
    public_surface_path: str,
) -> None:
    artifacts = _write_valid_tree(tmp_path)
    manifest = artifacts[MANIFEST_PATH]
    assert isinstance(manifest, dict)
    manifest["generated_surfaces"] = [
        surface for surface in manifest["generated_surfaces"] if surface != public_surface_path
    ]
    _write_json(tmp_path, MANIFEST_PATH, manifest)

    errors = validate_release_capsule(tmp_path)

    assert any(
        f"manifest generated_surfaces missing {public_surface_path}" in error for error in errors
    )


@pytest.mark.parametrize(
    "surface_path",
    [
        OUTCOME_CATALOG_PATH,
        ACCOUNTING_CSV_PROFILES_PATH,
        ALGORITHM_BLUEPRINTS_PATH,
        OUTCOME_SOURCE_CROSSWALK_PATH,
        PACKET_SKELETONS_PATH,
        PUBLIC_SOURCE_DOMAINS_PATH,
        AWS_SPEND_PROGRAM_PATH,
        AWS_EXECUTION_TEMPLATES_PATH,
    ],
)
def test_new_public_surface_missing_file_fails_closed(
    tmp_path: Path,
    surface_path: Path,
) -> None:
    _write_valid_tree(tmp_path)
    (tmp_path / surface_path).unlink()

    errors = validate_release_capsule(tmp_path)

    assert any("missing file" in error and str(surface_path) in error for error in errors)


def test_rejects_p0_tool_semantics_mismatch_when_present(tmp_path: Path) -> None:
    artifacts = _write_valid_tree(tmp_path)
    facade = artifacts[P0_FACADE_PATH]
    assert isinstance(facade, dict)
    tools = facade["tools"]
    assert isinstance(tools, list)
    for tool, semantics in zip(tools, ["route", "preview", "execute", "get"], strict=True):
        tool["semantics"] = semantics
    tools[1]["semantics"] = "cost_preview"
    _write_json(tmp_path, P0_FACADE_PATH, facade)

    errors = validate_release_capsule(tmp_path)

    assert any("P0 facade tool semantics mismatch" in error for error in errors)


def test_rejects_preflight_target_credit_conversion_mismatch(tmp_path: Path) -> None:
    artifacts = _write_valid_tree(tmp_path)
    preflight = artifacts[PREFLIGHT_SCORECARD_PATH]
    assert isinstance(preflight, dict)
    preflight["target_credit_conversion_usd"] = 19000
    _write_json(tmp_path, PREFLIGHT_SCORECARD_PATH, preflight)

    errors = validate_release_capsule(tmp_path)

    assert any("target_credit_conversion_usd" in error for error in errors)


def test_rejects_active_aws_pointer(tmp_path: Path) -> None:
    artifacts = _write_valid_tree(tmp_path)
    pointer = artifacts[RUNTIME_POINTER_PATH]
    assert isinstance(pointer, dict)
    pointer["active_aws_pointer"] = "/releases/aws/live.json"
    _write_json(tmp_path, RUNTIME_POINTER_PATH, pointer)

    errors = validate_release_capsule(tmp_path)

    assert any("active AWS pointer" in error for error in errors)


def test_rejects_private_csv_public_source_leakage_tokens(tmp_path: Path) -> None:
    artifacts = _write_valid_tree(tmp_path)
    facade = artifacts[P0_FACADE_PATH]
    assert isinstance(facade, dict)
    facade["public_source_receipt_hint"] = "raw_csv"
    _write_json(tmp_path, P0_FACADE_PATH, facade)

    errors = validate_release_capsule(tmp_path)

    assert any("forbidden private CSV/public source token" in error for error in errors)


def test_allows_csv_profile_catalog_boundary_terms(tmp_path: Path) -> None:
    artifacts = _write_valid_tree(tmp_path)
    profiles = artifacts[ACCOUNTING_CSV_PROFILES_PATH]
    assert isinstance(profiles, dict)
    profiles["boundary_terms"] = [
        "tenant_private",
        "source_receipt_compatible",
        "private_csv",
    ]
    _write_json(tmp_path, ACCOUNTING_CSV_PROFILES_PATH, profiles)

    errors = validate_release_capsule(tmp_path)

    assert errors == []


def test_rejects_aws_spend_program_target_drift(tmp_path: Path) -> None:
    artifacts = _write_valid_tree(tmp_path)
    spend_program = artifacts[AWS_SPEND_PROGRAM_PATH]
    assert isinstance(spend_program, dict)
    spend_program["planned_target_sum_usd"] = 19491
    _write_json(tmp_path, AWS_SPEND_PROGRAM_PATH, spend_program)

    errors = validate_release_capsule(tmp_path)

    assert any("planned_target_sum_usd" in error for error in errors)


def test_rejects_outcome_catalog_fail_closed_flag_drift(tmp_path: Path) -> None:
    artifacts = _write_valid_tree(tmp_path)
    outcome_catalog = artifacts[OUTCOME_CATALOG_PATH]
    assert isinstance(outcome_catalog, dict)
    outcome_catalog["live_network_dependency"] = True
    outcome_catalog["deliverables"][0]["request_time_llm_dependency"] = True
    _write_json(tmp_path, OUTCOME_CATALOG_PATH, outcome_catalog)

    errors = validate_release_capsule(tmp_path)

    assert any(
        "outcome catalog must set live_network_dependency=false" in error for error in errors
    )
    assert any(
        "outcome catalog deliverables[0] must set request_time_llm_dependency=false" in error
        for error in errors
    )


def test_rejects_accounting_csv_profile_fail_closed_flag_drift(tmp_path: Path) -> None:
    artifacts = _write_valid_tree(tmp_path)
    profiles = artifacts[ACCOUNTING_CSV_PROFILES_PATH]
    assert isinstance(profiles, dict)
    profiles["blocked_downstream_outputs"].remove("public_source_receipt")
    profiles["profiles"][0]["official_certification_claimed"] = True
    profiles["profiles"][0]["account_category_policy"]["derived_category_allowed"] = True
    _write_json(tmp_path, ACCOUNTING_CSV_PROFILES_PATH, profiles)

    errors = validate_release_capsule(tmp_path)

    assert any("public_source_receipt" in error for error in errors)
    assert any("official_certification_claimed=false" in error for error in errors)
    assert any("derived_category_allowed=false" in error for error in errors)


def test_rejects_algorithm_blueprint_fail_closed_flag_drift(tmp_path: Path) -> None:
    artifacts = _write_valid_tree(tmp_path)
    blueprints = artifacts[ALGORITHM_BLUEPRINTS_PATH]
    assert isinstance(blueprints, dict)
    blueprints["blueprints"][0]["llm_allowed"] = True
    blueprints["blueprints"][0]["gap_handling"]["absence_claim_enabled"] = True
    blueprints["blueprints"][0]["advice_boundary"]["asserts_legal_or_accounting_advice"] = True
    blueprints["blueprints"][0]["proof_handling"]["private_csv_can_support_public_claims"] = True
    _write_json(tmp_path, ALGORITHM_BLUEPRINTS_PATH, blueprints)

    errors = validate_release_capsule(tmp_path)

    assert any(
        "algorithm blueprints blueprints[0] must set llm_allowed=false" in error for error in errors
    )
    assert any("absence_claim_enabled=false" in error for error in errors)
    assert any("asserts_legal_or_accounting_advice=false" in error for error in errors)
    assert any("private_csv_can_support_public_claims=false" in error for error in errors)


def test_rejects_public_source_domain_fail_closed_flag_drift(tmp_path: Path) -> None:
    artifacts = _write_valid_tree(tmp_path)
    domains = artifacts[PUBLIC_SOURCE_DOMAINS_PATH]
    assert isinstance(domains, dict)
    domains["catalog"][0]["collection_enabled_initially"] = True
    domains["catalog"][0]["pii_collection_allowed"] = True
    domains["catalog"][0]["robots_terms_posture"]["stop_on_disallow_or_terms_conflict"] = False
    _write_json(tmp_path, PUBLIC_SOURCE_DOMAINS_PATH, domains)

    errors = validate_release_capsule(tmp_path)

    assert any(
        "public source domains catalog[0] must set collection_enabled_initially=false" in error
        for error in errors
    )
    assert any(
        "public source domains catalog[0] must set pii_collection_allowed=false" in error
        for error in errors
    )
    assert any("stop_on_disallow_or_terms_conflict=true" in error for error in errors)


def test_rejects_aws_spend_batch_fail_closed_flag_drift(tmp_path: Path) -> None:
    artifacts = _write_valid_tree(tmp_path)
    spend_program = artifacts[AWS_SPEND_PROGRAM_PATH]
    assert isinstance(spend_program, dict)
    spend_program["preflight_evidence_passed"] = True
    spend_program["batches"][0]["aws_calls_allowed"] = True
    spend_program["batches"][0]["network_calls_allowed"] = True
    spend_program["batches"][0]["subprocess_allowed"] = True
    _write_json(tmp_path, AWS_SPEND_PROGRAM_PATH, spend_program)

    errors = validate_release_capsule(tmp_path)

    assert any(
        "AWS spend program must set preflight_evidence_passed=false" in error for error in errors
    )
    assert any(
        "AWS spend program batches[0] must set aws_calls_allowed=false" in error for error in errors
    )
    assert any(
        "AWS spend program batches[0] must set network_calls_allowed=false" in error
        for error in errors
    )
    assert any(
        "AWS spend program batches[0] must set subprocess_allowed=false" in error
        for error in errors
    )


def test_rejects_well_known_release_manifest_hash_drift(tmp_path: Path) -> None:
    artifacts = _write_valid_tree(tmp_path)
    well_known = artifacts[WELL_KNOWN_RELEASE_PATH]
    assert isinstance(well_known, dict)
    well_known["manifest_sha256"] = "0" * 64
    _write_json(tmp_path, WELL_KNOWN_RELEASE_PATH, well_known)

    errors = validate_release_capsule(tmp_path)

    assert any("well-known release manifest_sha256" in error for error in errors)


def test_rejects_well_known_release_pointer_path_drift(tmp_path: Path) -> None:
    artifacts = _write_valid_tree(tmp_path)
    well_known = artifacts[WELL_KNOWN_RELEASE_PATH]
    assert isinstance(well_known, dict)
    well_known["p0_facade_path"] = "/releases/rc1-p0-bootstrap/agent_surface/full_catalog.json"
    _write_json(tmp_path, WELL_KNOWN_RELEASE_PATH, well_known)

    errors = validate_release_capsule(tmp_path)

    assert any("well-known release p0_facade_path" in error for error in errors)
