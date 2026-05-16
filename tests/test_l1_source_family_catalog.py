"""Tests for Wave 51 L1 source family catalog registry.

The registry is static metadata only — no I/O, no LLM, no DB. These tests
assert structural integrity (count, uniqueness, priority distribution,
segmented pairing, no forbidden imports) and the public lookup surface.
"""

from __future__ import annotations

import importlib
from typing import get_args

import pytest
from pydantic import ValidationError

from jpintel_mcp.l1_source_family import (
    SOURCE_FAMILY_REGISTRY,
    AccessMode,
    Category,
    LicenseTag,
    Ministry,
    Priority,
    RefreshFrequency,
    SourceFamily,
    get_source_family,
    list_source_families,
    list_source_families_by_priority,
)

# ---------------------------------------------------------------------------
# Registry size + integrity
# ---------------------------------------------------------------------------


def test_registry_has_exactly_37_families() -> None:
    """WAVE51_L1_SOURCE_FAMILY_CATALOG.md § 1 mandates 37 families
    (32 original + 4 J12-J15 extensions landed 2026-05-16:
    kokkai_diet_minutes / edinet_xbrl_full / jpo_patent_gazette_full /
    env_ministry_data + 1 J16 extension same day:
    canonical_pdf_corpus — direct 公的 PDF URL acquisition, post J06
    HTML walk 0 PDFs incident)."""
    assert len(SOURCE_FAMILY_REGISTRY) == 37
    assert len(list_source_families()) == 37


def test_registry_family_ids_are_unique() -> None:
    ids = [row.family_id for row in list_source_families()]
    assert len(ids) == len(set(ids))


def test_registry_is_immutable_mapping() -> None:
    # MappingProxyType disallows item assignment / deletion.
    with pytest.raises(TypeError):
        SOURCE_FAMILY_REGISTRY["new_family"] = list_source_families()[0]  # type: ignore[index]


def test_source_family_instances_are_frozen() -> None:
    row = list_source_families()[0]
    with pytest.raises(ValidationError):
        row.family_id = "mutated_id"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Priority distribution (§ 1: P0=6 / P1=17 / P2=8 / P2_restricted=1)
# ---------------------------------------------------------------------------


def test_priority_distribution_matches_spec() -> None:
    p0 = list_source_families_by_priority("P0")
    p1 = list_source_families_by_priority("P1")
    p2 = list_source_families_by_priority("P2")
    pr = list_source_families_by_priority("P2_restricted")
    assert len(p0) == 6
    assert len(p1) == 17
    # P2 extended from 8 → 12 on 2026-05-16 with J12-J15 (kokkai_diet_minutes,
    # edinet_xbrl_full, jpo_patent_gazette_full, env_ministry_data),
    # then 12 → 13 same day with J16 (canonical_pdf_corpus — direct 公的
    # PDF URL acquisition, introduced after J06 HTML walk captured 0 PDFs).
    assert len(p2) == 13
    assert len(pr) == 1
    assert len(p0) + len(p1) + len(p2) + len(pr) == 37


def test_p0_family_ids_match_spec() -> None:
    """§ 2.1 enumerates exactly these 6 P0 families."""
    expected = {
        "egov_laws_regulations",
        "nta_invoice_publication",
        "gbizinfo_houjin",
        "edinet_disclosure",
        "jgrants_subsidy_portal",
        "sangyo_houjin_registry",
    }
    actual = {row.family_id for row in list_source_families_by_priority("P0")}
    assert actual == expected


def test_p2_restricted_is_only_nta_pdb_personal() -> None:
    pr = list_source_families_by_priority("P2_restricted")
    assert len(pr) == 1
    assert pr[0].family_id == "nta_pdb_personal"
    assert pr[0].license_tag == "restricted"
    assert pr[0].access_mode == "private_api"
    assert pr[0].refresh_frequency == "private"


# ---------------------------------------------------------------------------
# Segmented wrappers (pref_47 / muni_800)
# ---------------------------------------------------------------------------


def test_segmented_families_pair_dimension_correctly() -> None:
    pref = get_source_family("pref_47_municipal")
    muni = get_source_family("muni_800_segments")
    assert pref.is_segmented is True
    assert pref.segment_dimension == "prefecture_code"
    assert muni.is_segmented is True
    assert muni.segment_dimension == "municipality_code"


def test_non_segmented_families_have_no_dimension() -> None:
    for row in list_source_families():
        if not row.is_segmented:
            assert row.segment_dimension is None, row.family_id


def test_only_two_segmented_families() -> None:
    segmented = [row for row in list_source_families() if row.is_segmented]
    assert len(segmented) == 2


# ---------------------------------------------------------------------------
# Lookup API
# ---------------------------------------------------------------------------


def test_get_source_family_returns_correct_row() -> None:
    row = get_source_family("egov_laws_regulations")
    assert row.family_id == "egov_laws_regulations"
    assert row.ministry == "e_gov"
    assert row.license_tag == "cc_by_4_0"
    assert row.priority == "P0"


def test_get_source_family_raises_keyerror_for_unknown() -> None:
    with pytest.raises(KeyError, match="unknown L1 source family_id"):
        get_source_family("not_a_real_family")


def test_list_source_families_returns_tuple_in_declaration_order() -> None:
    rows = list_source_families()
    assert isinstance(rows, tuple)
    # First row in declaration is the egov P0 anchor; last is the restricted entry.
    assert rows[0].family_id == "egov_laws_regulations"
    assert rows[-1].family_id == "nta_pdb_personal"


# ---------------------------------------------------------------------------
# License + access_mode coverage
# ---------------------------------------------------------------------------


def test_every_license_tag_value_is_in_literal_args() -> None:
    allowed = set(get_args(LicenseTag))
    for row in list_source_families():
        assert row.license_tag in allowed


def test_every_access_mode_value_is_in_literal_args() -> None:
    allowed = set(get_args(AccessMode))
    for row in list_source_families():
        assert row.access_mode in allowed


def test_every_refresh_frequency_value_is_in_literal_args() -> None:
    allowed = set(get_args(RefreshFrequency))
    for row in list_source_families():
        assert row.refresh_frequency in allowed


def test_every_ministry_value_is_in_literal_args() -> None:
    allowed = set(get_args(Ministry))
    for row in list_source_families():
        assert row.ministry in allowed


def test_every_category_value_is_in_literal_args() -> None:
    allowed = set(get_args(Category))
    for row in list_source_families():
        assert row.category in allowed


def test_priority_values_match_literal_args() -> None:
    allowed = set(get_args(Priority))
    for row in list_source_families():
        assert row.priority in allowed


# ---------------------------------------------------------------------------
# Pydantic model validators
# ---------------------------------------------------------------------------


def test_validator_rejects_segmented_without_dimension() -> None:
    with pytest.raises(ValidationError, match="segment_dimension"):
        SourceFamily(
            family_id="bad_segmented",
            ministry="pref_47_wrapper",
            category="local_subsidy",
            license_tag="per_municipality",
            access_mode="website",
            refresh_frequency="weekly",
            priority="P2",
            is_segmented=True,
            segment_dimension=None,
        )


def test_validator_rejects_dimension_without_segmented() -> None:
    with pytest.raises(ValidationError, match="segment_dimension"):
        SourceFamily(
            family_id="bad_unsegmented",
            ministry="meti",
            category="subsidy_general",
            license_tag="ogl_2_0",
            access_mode="website",
            refresh_frequency="weekly",
            priority="P1",
            is_segmented=False,
            segment_dimension="prefecture_code",
        )


def test_validator_rejects_restricted_license_with_wrong_priority() -> None:
    with pytest.raises(ValidationError, match="restricted"):
        SourceFamily(
            family_id="bad_restricted",
            ministry="nta",
            category="tax_personal",
            license_tag="restricted",
            access_mode="private_api",
            refresh_frequency="private",
            priority="P1",  # should be P2_restricted
        )


def test_validator_rejects_p2_restricted_without_restricted_license() -> None:
    with pytest.raises(ValidationError, match="P2_restricted"):
        SourceFamily(
            family_id="bad_priority",
            ministry="nta",
            category="tax_personal",
            license_tag="tos_only",  # should be restricted
            access_mode="private_api",
            refresh_frequency="private",
            priority="P2_restricted",
        )


def test_validator_rejects_invalid_family_id_pattern() -> None:
    with pytest.raises(ValidationError):
        SourceFamily(
            family_id="Bad-ID-With-Hyphens",
            ministry="meti",
            category="subsidy_general",
            license_tag="ogl_2_0",
            access_mode="website",
            refresh_frequency="weekly",
            priority="P1",
        )


def test_validator_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        SourceFamily(
            family_id="valid_id",
            ministry="meti",
            category="subsidy_general",
            license_tag="ogl_2_0",
            access_mode="website",
            refresh_frequency="weekly",
            priority="P1",
            unexpected_field="boom",  # type: ignore[call-arg]
        )


# ---------------------------------------------------------------------------
# Anti-pattern enforcement — no live I/O, no LLM imports
# ---------------------------------------------------------------------------


def test_catalog_module_does_not_import_http_or_llm_clients() -> None:
    """Re-import the module and inspect its globals for forbidden libs.

    This guard is in addition to the project-wide
    ``tests/test_no_llm_in_production.py`` walker — it ensures the L1
    source family module itself stays pure metadata.
    """
    mod = importlib.import_module("jpintel_mcp.l1_source_family.catalog")
    forbidden = {
        "anthropic",
        "openai",
        "google.generativeai",
        "claude_agent_sdk",
        "httpx",
        "requests",
        "urllib3",
        "playwright",
        "selenium",
    }
    for name in forbidden:
        top = name.split(".")[0]
        assert top not in mod.__dict__, (
            f"{name} must not be imported by l1_source_family.catalog"
        )


def test_catalog_version_constant_is_stable() -> None:
    from jpintel_mcp.l1_source_family.catalog import CATALOG_VERSION

    assert CATALOG_VERSION == "jpcite.l1_source_family.wave51.v1"
