"""Tests for JPCIR internal-field exemption in ``forbidden_claim`` scanner.

The forbidden-claim scanner scans every text-bearing leaf of a JPCIR envelope
for forbidden English wording (``safe`` / ``eligible`` / ``trustworthy`` etc.)
and Japanese equivalents. Internal contract metadata fields like
``privacy_class`` carry slug-style enum values
(``public_safe`` / ``aggregate_safe`` / ``tenant_private_aggregate``) that
collide with the forbidden substring ``safe`` even though they are NOT
agent-facing claims.

These tests pin the exemption: the named internal fields must NOT trigger
``forbidden_english_wording`` even when their values contain a forbidden
substring; user-facing fields (records / sections / summary / claim text)
must still be scanned exactly as before.
"""

from __future__ import annotations

from typing import Any

from jpintel_mcp.safety_scanners import (
    JPCIR_INTERNAL_FIELDS,
    scan_forbidden_claims,
)

# ---------------------------------------------------------------------------
# Field-name registry pin
# ---------------------------------------------------------------------------


def test_jpcir_internal_fields_pins_13_names() -> None:
    """The exemption list pins exactly the 13 internal field names."""
    expected = {
        "claim_kind",
        "content_type",
        "data_class",
        "freshness_bucket",
        "gap_code",
        "license_boundary",
        "policy_state",
        "privacy_class",
        "receipt_kind",
        "retention_class",
        "severity",
        "subject_kind",
        "support_level",
    }
    assert expected == JPCIR_INTERNAL_FIELDS


# ---------------------------------------------------------------------------
# Each internal field is exempted from forbidden English wording
# ---------------------------------------------------------------------------


def test_privacy_class_public_safe_is_exempted() -> None:
    """``privacy_class="public_safe"`` is the real-world false positive."""
    envelope: dict[str, Any] = {"privacy_class": "public_safe"}
    assert scan_forbidden_claims(envelope) == []


def test_privacy_class_aggregate_safe_is_exempted() -> None:
    envelope: dict[str, Any] = {"privacy_class": "aggregate_safe"}
    assert scan_forbidden_claims(envelope) == []


def test_retention_class_safe_substring_is_exempted() -> None:
    envelope: dict[str, Any] = {"retention_class": "repo_candidate_safe"}
    assert scan_forbidden_claims(envelope) == []


def test_content_type_eligible_substring_is_exempted() -> None:
    """English substrings in ``content_type`` are exempt slugs, not claims."""
    envelope: dict[str, Any] = {"content_type": "application/eligible+json"}
    assert scan_forbidden_claims(envelope) == []


def test_license_boundary_trustworthy_substring_is_exempted() -> None:
    envelope: dict[str, Any] = {"license_boundary": "trustworthy_derived"}
    assert scan_forbidden_claims(envelope) == []


def test_freshness_bucket_is_exempted() -> None:
    envelope: dict[str, Any] = {"freshness_bucket": "within_7d_safe"}
    assert scan_forbidden_claims(envelope) == []


def test_support_level_is_exempted() -> None:
    envelope: dict[str, Any] = {"support_level": "direct_safe"}
    assert scan_forbidden_claims(envelope) == []


def test_receipt_kind_is_exempted() -> None:
    envelope: dict[str, Any] = {"receipt_kind": "positive_safe_source"}
    assert scan_forbidden_claims(envelope) == []


def test_claim_kind_is_exempted() -> None:
    envelope: dict[str, Any] = {"claim_kind": "candidate_eligible_subject"}
    assert scan_forbidden_claims(envelope) == []


def test_severity_is_exempted() -> None:
    envelope: dict[str, Any] = {"severity": "safe_review"}
    assert scan_forbidden_claims(envelope) == []


# ---------------------------------------------------------------------------
# Real S3 row shape — sanity check against the J01 object_manifest format
# ---------------------------------------------------------------------------


def test_full_object_manifest_row_no_violation() -> None:
    """A canonical J01 ``object_manifest`` row must NOT trigger any violation.

    Shape mirrors the actual S3 row at
    ``s3://jpcite-credit-993693061769-202605-raw/J01_source_profile/
    object_manifest.jsonl`` (the bug source).
    """
    row: dict[str, Any] = {
        "artifact_id": "art_6b2ce2e076c146b2",
        "artifact_kind": "source_document_manifest",
        "data_class": "public_official",
        "privacy_class": "public_safe",
        "license_boundary": "derived_fact",
        "retention_class": "repo_candidate_public",
        "extras": {"content_type": "text/html; charset=UTF-8"},
        "quality": {
            "gate_status": "pass",
            "blocking_issue_count": 0,
            "warning_count": 0,
        },
        "schema_version": "2026-05-15",
    }
    assert scan_forbidden_claims(row) == []


# ---------------------------------------------------------------------------
# User-facing fields are still scanned (regression guard)
# ---------------------------------------------------------------------------


def test_records_field_still_scanned_for_safe() -> None:
    """``records[].summary="...is safe..."`` must still be flagged."""
    envelope: dict[str, Any] = {
        "records": [{"summary": "this program is safe to apply"}],
    }
    violations = scan_forbidden_claims(envelope)
    codes = [v.code for v in violations]
    assert "forbidden_english_wording" in codes


def test_sections_body_still_scanned_for_eligible() -> None:
    envelope: dict[str, Any] = {
        "sections": [{"body": "you are eligible for this benefit"}],
    }
    violations = scan_forbidden_claims(envelope)
    codes = [v.code for v in violations]
    assert "forbidden_english_wording" in codes


def test_summary_field_still_scanned_for_trustworthy() -> None:
    envelope: dict[str, Any] = {"summary": "the result is trustworthy"}
    violations = scan_forbidden_claims(envelope)
    codes = [v.code for v in violations]
    assert "forbidden_english_wording" in codes


def test_claim_text_still_scanned_for_no_violation() -> None:
    envelope: dict[str, Any] = {"claim_text": "there is no violation here"}
    violations = scan_forbidden_claims(envelope)
    codes = [v.code for v in violations]
    assert "forbidden_english_wording" in codes


# ---------------------------------------------------------------------------
# Japanese wording in internal fields is still a defect
# ---------------------------------------------------------------------------


def test_internal_field_with_japanese_still_flagged() -> None:
    """Japanese in an internal enum field is itself a defect (ASCII-slug only).

    Identifier and JPCIR-internal exemptions only suppress *English* hits —
    Japanese forbidden phrases must still produce a violation so a defective
    upstream emitter cannot smuggle ``問題ありません`` in via ``severity``.
    """
    envelope: dict[str, Any] = {"severity": "問題ありません"}
    violations = scan_forbidden_claims(envelope)
    codes = [v.code for v in violations]
    assert "forbidden_japanese_wording" in codes


# ---------------------------------------------------------------------------
# Nested manifest row — privacy_class deep inside list must be exempted too
# ---------------------------------------------------------------------------


def test_nested_object_manifest_rows_exempted() -> None:
    """A list of object_manifest rows (the validator's actual call shape).

    The validator wraps each JSONL row as ``$.row[N].privacy_class`` —
    confirm the exemption travels through list + nested dict.
    """
    rows = [
        {"privacy_class": "public_safe"},
        {"privacy_class": "aggregate_safe"},
        {"privacy_class": "tenant_private_aggregate"},
    ]
    envelope: dict[str, Any] = {"rows": rows}
    assert scan_forbidden_claims(envelope) == []
