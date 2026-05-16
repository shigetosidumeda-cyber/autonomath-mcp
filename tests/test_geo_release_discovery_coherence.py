from __future__ import annotations

import hashlib
import json
from pathlib import Path

from jpintel_mcp.agent_runtime.defaults import CAPSULE_ID, P0_FACADE_TOOLS
from jpintel_mcp.agent_runtime.facade_contract import (
    BANNED_P0_FACADE_ALIASES,
    build_p0_facade_contract_shape,
)
from scripts.ops.validate_release_capsule import (
    EXPECTED_AWS_SPEND_EXECUTION_MODE,
    EXPECTED_NO_HIT_SEMANTICS,
    PUBLIC_ACCOUNTING_CSV_PROFILES_PATH,
    PUBLIC_ALGORITHM_BLUEPRINTS_PATH,
    PUBLIC_AWS_EXECUTION_TEMPLATES_PATH,
    PUBLIC_AWS_SPEND_PROGRAM_PATH,
    PUBLIC_CATALOG_SURFACE_PATHS,
    PUBLIC_INLINE_PACKETS_PATH,
    PUBLIC_OUTCOME_CATALOG_PATH,
    PUBLIC_OUTCOME_SOURCE_CROSSWALK_PATH,
    PUBLIC_PACKET_SKELETONS_PATH,
    PUBLIC_PUBLIC_SOURCE_DOMAINS_PATH,
    PUBLIC_WELL_KNOWN_RELEASE_PATH,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
SITE = REPO_ROOT / "site"
CANONICAL_SITE = "https://jpcite.com"

P0_REST_FACADE = {
    "jpcite_route": ("post", "/v1/jpcite/route"),
    "jpcite_preview_cost": ("post", "/v1/jpcite/preview_cost"),
    "jpcite_execute_packet": ("post", "/v1/jpcite/execute_packet"),
    "jpcite_get_packet": ("get", "/v1/jpcite/get_packet/{packet_id}"),
}

MCP_TOOL_MANIFESTS = [
    REPO_ROOT / "mcp-server.json",
    REPO_ROOT / "mcp-server.full.json",
    SITE / "mcp-server.json",
    SITE / "mcp-server.full.json",
]

MCP_REGISTRY_MANIFESTS = [
    REPO_ROOT / "server.json",
    SITE / "server.json",
]


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _public_path_to_site_file(public_path: str) -> Path:
    assert public_path.startswith("/"), public_path
    assert ".." not in Path(public_path).parts, public_path
    return SITE / public_path.removeprefix("/")


def _tool_names(path: Path) -> list[str]:
    return [tool["name"] for tool in _load_json(path).get("tools", [])]


def _public_url(public_path: str) -> str:
    assert public_path.startswith("/"), public_path
    return f"{CANONICAL_SITE}{public_path}"


def test_well_known_release_pointer_matches_capsule_and_manifest_hash() -> None:
    release = _load_json(SITE / ".well-known" / "jpcite-release.json")
    runtime_pointer = _load_json(SITE / "releases" / "current" / "runtime_pointer.json")
    manifest_path = _public_path_to_site_file(release["manifest_path"])
    facade_path = _public_path_to_site_file(release["p0_facade_path"])
    runtime_pointer_path = _public_path_to_site_file(release["runtime_pointer_path"])

    manifest = _load_json(manifest_path)
    facade = _load_json(facade_path)

    assert release["schema_version"] == "jpcite.well_known_release.p0.v1"
    assert release["active_capsule_id"] == CAPSULE_ID
    assert release["active_capsule_id"] == runtime_pointer["active_capsule_id"]
    assert release["active_capsule_id"] == manifest["capsule_id"]
    assert release["active_capsule_id"] == facade["capsule_id"]
    assert release["active_capsule_manifest"] == release["manifest_path"]
    assert runtime_pointer_path == SITE / "releases" / "current" / "runtime_pointer.json"
    assert runtime_pointer_path.exists()
    assert facade_path.exists()

    actual_manifest_hash = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    assert release["manifest_sha256"] == actual_manifest_hash
    assert release["manifest_path"] in manifest["generated_surfaces"]
    assert release["p0_facade_path"] in manifest["generated_surfaces"]
    assert release["runtime_pointer_path"] in manifest["generated_surfaces"]
    assert "/.well-known/jpcite-release.json" in manifest["generated_surfaces"]


def test_release_manifest_lists_new_public_catalog_surfaces_fail_closed() -> None:
    manifest = _load_json(SITE / "releases" / "rc1-p0-bootstrap" / "release_capsule_manifest.json")
    generated_surfaces = set(manifest["generated_surfaces"])

    surface_payloads = {}
    for public_path in PUBLIC_CATALOG_SURFACE_PATHS:
        assert public_path in generated_surfaces
        surface_path = _public_path_to_site_file(public_path)
        assert surface_path.exists()
        surface_payloads[public_path] = _load_json(surface_path)

    outcome_catalog = surface_payloads[PUBLIC_OUTCOME_CATALOG_PATH]
    assert outcome_catalog["request_time_llm_dependency"] is False
    assert outcome_catalog["live_network_dependency"] is False
    assert outcome_catalog["live_aws_dependency"] is False
    assert outcome_catalog["no_hit_semantics"] == EXPECTED_NO_HIT_SEMANTICS
    for deliverable in outcome_catalog["deliverables"]:
        assert deliverable["api_wiring_required"] is False
        assert deliverable["request_time_llm_dependency"] is False
        assert deliverable["live_network_dependency"] is False
        assert deliverable["live_aws_dependency"] is False
        assert deliverable["no_hit_semantics"] == EXPECTED_NO_HIT_SEMANTICS

    accounting_csv_profiles = surface_payloads[PUBLIC_ACCOUNTING_CSV_PROFILES_PATH]
    blocked_outputs = set(accounting_csv_profiles["blocked_downstream_outputs"])
    assert "public_source_receipt" in blocked_outputs
    assert "public_packet_claim" in blocked_outputs
    for profile in accounting_csv_profiles["profiles"]:
        assert profile["official_certification_claimed"] is False
        assert profile["account_category_policy"]["derived_category_allowed"] is False
        assert "public_source_receipt" in profile["blocked_downstream_outputs"]

    algorithm_blueprints = surface_payloads[PUBLIC_ALGORITHM_BLUEPRINTS_PATH]
    assert algorithm_blueprints["llm_allowed"] is False
    assert algorithm_blueprints["network_allowed"] is False
    assert algorithm_blueprints["no_hit_semantics"] == EXPECTED_NO_HIT_SEMANTICS
    for blueprint in algorithm_blueprints["blueprints"]:
        assert blueprint["llm_allowed"] is False
        assert blueprint["network_allowed"] is False
        assert blueprint["gap_handling"]["absence_claim_enabled"] is False
        assert blueprint["gap_handling"]["no_hit_semantics"] == EXPECTED_NO_HIT_SEMANTICS
        assert blueprint["advice_boundary"]["asserts_legal_or_accounting_advice"] is False
        assert blueprint["proof_handling"]["private_csv_can_support_public_claims"] is False

    public_source_domains = surface_payloads[PUBLIC_PUBLIC_SOURCE_DOMAINS_PATH]
    assert public_source_domains["collection_enabled_initially"] is False
    assert public_source_domains["playwright_screenshot_max_px"] == 1600
    for source in public_source_domains["catalog"]:
        assert source["collection_enabled_initially"] is False
        assert source["bulk_resale_or_redistribution_allowed"] is False
        assert source["pii_collection_allowed"] is False
        assert source["playwright_screenshot_policy"]["full_page_capture_allowed"] is False
        assert source["playwright_screenshot_policy"]["max_bitmap_long_edge_px"] == 1600
        assert source["robots_terms_posture"]["robots_txt_must_be_checked"] is True
        assert source["robots_terms_posture"]["terms_must_be_reviewed"] is True
        assert source["robots_terms_posture"]["stop_on_disallow_or_terms_conflict"] is True

    aws_spend_program = surface_payloads[PUBLIC_AWS_SPEND_PROGRAM_PATH]
    assert aws_spend_program["live_execution_allowed"] is False
    assert aws_spend_program["preflight_evidence_passed"] is False
    assert aws_spend_program["execution_mode"] == EXPECTED_AWS_SPEND_EXECUTION_MODE
    for batch in aws_spend_program["batches"]:
        assert batch["aws_calls_allowed"] is False
        assert batch["network_calls_allowed"] is False
        assert batch["mutates_live_aws"] is False
        assert batch["subprocess_allowed"] is False
        assert batch["execution_mode"] == EXPECTED_AWS_SPEND_EXECUTION_MODE


def test_p0_facade_contract_is_identical_across_release_openapi_mcp_and_dxt() -> None:
    expected_tools = list(P0_FACADE_TOOLS)
    contract = {tool["name"]: tool for tool in build_p0_facade_contract_shape()["tools"]}
    static_facade = _load_json(
        SITE / "releases" / "rc1-p0-bootstrap" / "agent_surface" / "p0_facade.json"
    )

    assert [tool["name"] for tool in static_facade["tools"]] == expected_tools
    for tool in static_facade["tools"]:
        expected = contract[tool["name"]]
        assert tool["billable"] == expected["billable"]
        assert tool["requires_user_consent"] == expected["requires_user_consent"]

    for spec_path in [
        REPO_ROOT / "docs" / "openapi" / "v1.json",
        SITE / "docs" / "openapi" / "v1.json",
        SITE / "openapi" / "v1.json",
    ]:
        paths = _load_json(spec_path)["paths"]
        for tool_name, (method, rest_path) in P0_REST_FACADE.items():
            assert rest_path in paths, f"{spec_path.relative_to(REPO_ROOT)} missing {tool_name}"
            assert method in paths[rest_path], (
                f"{spec_path.relative_to(REPO_ROOT)} missing {method.upper()} {rest_path}"
            )

    dxt_names = _tool_names(REPO_ROOT / "dxt" / "manifest.json")
    mcp_names = _tool_names(SITE / "mcp-server.json")
    assert dxt_names == mcp_names
    assert [name for name in dxt_names if name in expected_tools] == expected_tools
    assert not [name for name in dxt_names if name in BANNED_P0_FACADE_ALIASES]

    for path in MCP_TOOL_MANIFESTS:
        payload = _load_json(path)
        names = [tool["name"] for tool in payload["tools"]]
        assert names == mcp_names
        assert [name for name in names if name in expected_tools] == expected_tools
        assert payload["_meta"]["tool_count"] == len(names)
        assert payload["_meta"]["io.modelcontextprotocol.registry/publisher-provided"][
            "tool_count"
        ] == len(names)

    for path in MCP_REGISTRY_MANIFESTS:
        payload = _load_json(path)
        publisher_meta = payload["_meta"]["io.modelcontextprotocol.registry/publisher-provided"]
        assert payload["_meta"]["tool_count"] == len(mcp_names)
        assert publisher_meta["tool_count"] == len(mcp_names)
        assert f"{len(mcp_names)} tools" in payload["description"]


def test_geo_discovery_surfaces_cross_link_the_same_public_entrypoints() -> None:
    agents = _load_json(SITE / ".well-known" / "agents.json")
    llms = _load_json(SITE / ".well-known" / "llms.json")
    discovery = _load_json(SITE / ".well-known" / "openapi-discovery.json")
    tiers = {tier["tier"]: tier for tier in discovery["tiers"]}

    assert discovery["discovery_endpoints"]["self"] == (
        f"{CANONICAL_SITE}/.well-known/openapi-discovery.json"
    )
    assert agents["openapi_discovery"] == discovery["discovery_endpoints"]["self"]
    assert discovery["discovery_endpoints"]["agents_json"] == (
        f"{CANONICAL_SITE}/.well-known/agents.json"
    )
    assert discovery["discovery_endpoints"]["llms_txt"] == llms["llms_txt"]["ja"]
    assert discovery["discovery_endpoints"]["mcp_server"] == llms["mcp"]["tool_manifest"]
    assert discovery["discovery_endpoints"]["server_json"] == llms["mcp"]["registry_manifest"]

    assert agents["rest_openapi"] == tiers["full"]["url"]
    assert agents["agent_openapi"] == tiers["agent"]["url"]
    assert agents["agent_openapi_slim_gpt30"] == tiers["gpt30"]["url"]
    assert llms["openapi"]["public_rest"] == tiers["full"]["url"]
    assert llms["openapi"]["agent_full"] == tiers["agent"]["url"]
    assert llms["openapi"]["agent_slim_gpt30"] == tiers["gpt30"]["url"]
    assert agents["llms_txt"] == llms["llms_txt"]["ja"]
    assert agents["llms_full_txt"] == llms["llms_txt"]["full_ja"]

    release_catalog_urls = {
        "jpcite_release": _public_url(PUBLIC_WELL_KNOWN_RELEASE_PATH),
        "outcome_catalog": _public_url(PUBLIC_OUTCOME_CATALOG_PATH),
        "outcome_source_crosswalk": _public_url(PUBLIC_OUTCOME_SOURCE_CROSSWALK_PATH),
        "packet_skeletons": _public_url(PUBLIC_PACKET_SKELETONS_PATH),
        "inline_packets": _public_url(PUBLIC_INLINE_PACKETS_PATH),
        "public_source_domains": _public_url(PUBLIC_PUBLIC_SOURCE_DOMAINS_PATH),
        "aws_spend_program": _public_url(PUBLIC_AWS_SPEND_PROGRAM_PATH),
        "aws_execution_templates": _public_url(PUBLIC_AWS_EXECUTION_TEMPLATES_PATH),
    }
    assert set(agents["release_catalog"]) == {*release_catalog_urls, "counts"}
    assert set(llms["release_catalog"]) == {*release_catalog_urls, "counts"}
    for key, expected_url in release_catalog_urls.items():
        assert agents["release_catalog"][key] == expected_url
        assert llms["release_catalog"][key] == expected_url

    expected_release_catalog_counts = {
        "outcome_catalog_deliverables": len(
            _load_json(_public_path_to_site_file(PUBLIC_OUTCOME_CATALOG_PATH))["deliverables"]
        ),
        "public_source_domain_families": len(
            _load_json(_public_path_to_site_file(PUBLIC_PUBLIC_SOURCE_DOMAINS_PATH))["catalog"]
        ),
        "aws_spend_program_batches": len(
            _load_json(_public_path_to_site_file(PUBLIC_AWS_SPEND_PROGRAM_PATH))["batches"]
        ),
        "outcome_source_crosswalk_entries": len(
            _load_json(_public_path_to_site_file(PUBLIC_OUTCOME_SOURCE_CROSSWALK_PATH))["crosswalk"]
        ),
        "packet_skeletons": len(
            _load_json(_public_path_to_site_file(PUBLIC_PACKET_SKELETONS_PATH))["skeletons"]
        ),
        "inline_packets": len(
            _load_json(_public_path_to_site_file(PUBLIC_INLINE_PACKETS_PATH))["packets"]
        ),
        "aws_execution_templates": len(
            _load_json(_public_path_to_site_file(PUBLIC_AWS_EXECUTION_TEMPLATES_PATH))[
                "execution_templates"
            ]
        ),
    }
    assert agents["release_catalog"]["counts"] == expected_release_catalog_counts
    assert llms["release_catalog"]["counts"] == expected_release_catalog_counts

    tool_count = len(_tool_names(SITE / "mcp-server.json"))
    assert agents["tools_count"]["public_default"] == tool_count
    assert agents["tools_count"]["runtime_verified"] == tool_count
    assert len(_tool_names(REPO_ROOT / "dxt" / "manifest.json")) == tool_count
