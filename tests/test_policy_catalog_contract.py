from pathlib import Path

import pytest

from jpintel_mcp.agent_runtime.policy_catalog import (
    NO_HIT_CAVEAT,
    PolicyCatalogEntry,
    build_policy_catalog,
    build_policy_catalog_shape,
    compile_public_policy_catalog,
    summarize_private_csv_overlay_shape,
)

SYNTHETIC_HEADERS = ("取引日", "摘要", "勘定科目", "金額")


def test_policy_catalog_has_deterministic_contract_states() -> None:
    catalog = build_policy_catalog()

    assert [entry.catalog_key for entry in catalog] == [
        "public_source_allow",
        "public_source_blocked_terms_unknown",
        "private_csv_overlay",
        "no_hit_caveat",
    ]
    assert [entry.to_policy_decision().policy_state for entry in catalog] == [
        "allow",
        "blocked_terms_unknown",
        "allow_internal_only",
        "gap_artifact_only",
    ]


def test_blocked_terms_unknown_and_private_csv_fail_closed_for_public_compile() -> None:
    catalog = {entry.catalog_key: entry for entry in build_policy_catalog()}

    blocked = catalog["public_source_blocked_terms_unknown"]
    private = catalog["private_csv_overlay"]

    assert blocked.public_compile_allowed is False
    assert blocked.blocked_reason_codes == ("terms_unknown",)
    assert "public_packet" in blocked.blocked_surfaces

    assert private.public_compile_allowed is False
    assert private.privacy_taint_level == "tenant_private"
    assert "source_receipt" in private.blocked_surfaces
    assert "not_source_receipt_compatible" in private.blocked_reason_codes


def test_public_compile_catalog_excludes_blocked_and_private_states() -> None:
    decisions = compile_public_policy_catalog()

    assert [decision.policy_state for decision in decisions] == [
        "allow",
        "gap_artifact_only",
    ]
    assert all(decision.public_compile_allowed for decision in decisions)


def test_no_hit_caveat_never_becomes_absence_claim() -> None:
    shape = build_policy_catalog_shape()
    no_hit = next(entry for entry in shape["catalog"] if entry["catalog_key"] == "no_hit_caveat")

    assert shape["no_hit_caveat"] == NO_HIT_CAVEAT
    assert shape["absence_claim_enabled"] is False
    assert no_hit["no_hit_semantics"] == NO_HIT_CAVEAT
    assert no_hit["absence_claim_enabled"] is False
    assert "absence_claim" in no_hit["blocked_surfaces"]


def test_private_csv_overlay_summary_is_metadata_only_and_deterministic() -> None:
    direct = summarize_private_csv_overlay_shape(
        SYNTHETIC_HEADERS,
        row_count=2,
        provider_family="freee",
    )
    catalog = {
        entry.catalog_key: entry
        for entry in build_policy_catalog(
            private_csv_overlay_headers=SYNTHETIC_HEADERS,
            private_csv_overlay_row_count=2,
            private_csv_provider_family="freee",
        )
    }

    assert direct.provider_family == "freee"
    assert direct.row_count_bucket == "1-99"
    assert direct.column_fingerprint_hash.startswith("sha256:")
    assert direct.raw_csv_retained is False
    assert direct.raw_csv_logged is False
    assert direct.raw_csv_sent_to_aws is False
    assert direct.public_surface_export_allowed is False
    assert direct.source_receipt_compatible is False
    assert catalog["private_csv_overlay"].private_csv_overlay == direct


def test_catalog_rejects_blocked_or_private_public_compile() -> None:
    with pytest.raises(ValueError, match="blocked policy states"):
        PolicyCatalogEntry(
            catalog_key="bad_blocked",
            display_name="Bad blocked",
            policy_state="blocked_terms_unknown",
            source_terms_contract_id="terms",
            administrative_info_class="public_web",
            privacy_taint_level="none",
            allowed_surfaces=("public_packet",),
            blocked_surfaces=(),
            blocked_reason_codes=("terms_unknown",),
            public_compile_allowed=True,
        )

    with pytest.raises(ValueError, match="private policy states"):
        PolicyCatalogEntry(
            catalog_key="bad_private",
            display_name="Bad private",
            policy_state="allow_internal_only",
            source_terms_contract_id="tenant-private-csv-overlay",
            administrative_info_class="tenant_private_csv",
            privacy_taint_level="tenant_private",
            allowed_surfaces=("public_packet",),
            blocked_surfaces=(),
            blocked_reason_codes=("tenant_private",),
            public_compile_allowed=True,
        )


def test_policy_catalog_has_no_aws_network_or_db_dependencies() -> None:
    module_source = Path("src/jpintel_mcp/agent_runtime/policy_catalog.py").read_text()

    forbidden_tokens = (
        "boto3",
        "botocore",
        "httpx",
        "requests",
        "urllib",
        "sqlite3",
        "import csv",
        "open(",
    )
    assert not any(token in module_source for token in forbidden_tokens)
