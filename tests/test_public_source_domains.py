from pathlib import Path

import pytest

from jpintel_mcp.agent_runtime.public_source_domains import (
    ALLOWED_COLLECTION_METHODS,
    OFFICIAL_OWNER_CATEGORIES,
    PLAYWRIGHT_SCREENSHOT_MAX_PX,
    REQUIRED_SOURCE_CATEGORIES,
    PlaywrightScreenshotPolicy,
    build_public_source_domain_catalog,
    build_public_source_domain_catalog_shape,
    is_first_party_official_domain_pattern,
    is_public_source_domain_allowed,
)


def test_public_source_catalog_contains_required_official_categories() -> None:
    catalog = build_public_source_domain_catalog()
    categories = {policy.source_category for policy in catalog}

    assert categories == set(REQUIRED_SOURCE_CATEGORIES)
    assert [policy.source_family_id for policy in catalog] == [
        "egov_laws_regulations",
        "tax_agency_guidance",
        "subsidy_program_portals",
        "local_government_public_sources",
        "statistics_open_data",
        "government_procurement",
        "court_decisions",
        "ministry_admin_guidance",
    ]


def test_sources_are_first_party_official_category_only() -> None:
    catalog = build_public_source_domain_catalog()

    for policy in catalog:
        assert policy.first_party_official_source is True
        assert policy.official_owner_category in OFFICIAL_OWNER_CATEGORIES
        assert policy.domain_patterns
        assert all(
            is_first_party_official_domain_pattern(domain_pattern)
            for domain_pattern in policy.domain_patterns
        )
        assert all(
            not domain_pattern.endswith((".com", ".co.jp", ".or.jp", ".net"))
            for domain_pattern in policy.domain_patterns
        )


def test_every_category_has_collection_methods_and_artifact_use_cases() -> None:
    catalog = build_public_source_domain_catalog()

    for category in REQUIRED_SOURCE_CATEGORIES:
        category_policies = [policy for policy in catalog if policy.source_category == category]
        category_methods = {
            method for policy in category_policies for method in policy.allowed_collection_methods
        }
        category_use_cases = {
            use_case for policy in category_policies for use_case in policy.artifact_use_cases
        }

        assert category_policies
        assert set(ALLOWED_COLLECTION_METHODS).issubset(category_methods)
        assert category_use_cases
        assert all(policy.artifact_use_cases for policy in category_policies)


def test_robots_terms_pii_and_resale_posture_fail_closed() -> None:
    shape = build_public_source_domain_catalog_shape()
    catalog = build_public_source_domain_catalog()

    assert shape["collection_enabled_initially"] is False

    for policy in catalog:
        posture = policy.robots_terms_posture

        assert policy.robots_posture == "check_and_obey_before_collection"
        assert policy.terms_posture == "review_and_block_on_conflict"
        assert posture.robots_txt_must_be_checked is True
        assert posture.robots_txt_must_be_obeyed is True
        assert posture.terms_must_be_reviewed is True
        assert posture.stop_on_disallow_or_terms_conflict is True
        assert posture.user_agent_contact_required is True

        assert policy.pii_collection_allowed is False
        assert policy.excluded_pii_subjects
        assert "individual" in policy.pii_exclusion_policy
        assert policy.bulk_resale_or_redistribution_allowed is False
        assert "bulk-redistribute" in policy.resale_redistribution_caution
        assert policy.collection_enabled_initially is False
        assert policy.aws_collection_scope == "future_public_aws_collection_candidate"


def test_playwright_screenshot_use_is_constrained_to_1600px() -> None:
    catalog = build_public_source_domain_catalog()
    screenshot_policies = [
        policy for policy in catalog if "playwright_screenshot" in policy.allowed_collection_methods
    ]

    assert screenshot_policies
    for policy in screenshot_policies:
        screenshot = policy.playwright_screenshot_policy

        assert screenshot.enabled is True
        assert screenshot.max_viewport_width_px <= PLAYWRIGHT_SCREENSHOT_MAX_PX
        assert screenshot.max_bitmap_long_edge_px <= PLAYWRIGHT_SCREENSHOT_MAX_PX
        assert screenshot.full_page_capture_allowed is False
        assert screenshot.pii_redaction_required is True
        assert screenshot.human_review_required_before_public_use is True

    with pytest.raises(ValueError, match="viewport width exceeds 1600px"):
        PlaywrightScreenshotPolicy(enabled=True, max_viewport_width_px=1601)

    with pytest.raises(ValueError, match="bitmap long edge exceeds 1600px"):
        PlaywrightScreenshotPolicy(enabled=True, max_bitmap_long_edge_px=1601)

    with pytest.raises(ValueError, match="full-page Playwright screenshots"):
        PlaywrightScreenshotPolicy(enabled=True, full_page_capture_allowed=True)


def test_static_domain_lookup_stays_inside_official_scope() -> None:
    assert is_public_source_domain_allowed("www.nta.go.jp") is True
    assert is_public_source_domain_allowed("invoice-kohyo.nta.go.jp") is True
    assert is_public_source_domain_allowed("www.city.osaka.lg.jp") is True
    assert is_public_source_domain_allowed("subdomain.city.example.lg.jp") is True

    assert is_public_source_domain_allowed("example.com") is False
    assert is_public_source_domain_allowed("unofficial-tax-guide.co.jp") is False
    assert is_first_party_official_domain_pattern("https://www.nta.go.jp/") is False


def test_public_source_domains_module_has_no_network_scraping_or_aws_dependencies() -> None:
    module_source = Path("src/jpintel_mcp/agent_runtime/public_source_domains.py").read_text(
        encoding="utf-8"
    )

    forbidden_tokens = (
        "boto3",
        "botocore",
        "httpx",
        "requests",
        "urllib",
        "selenium",
        "sync_playwright",
        "async_playwright",
        "import csv",
        "open(",
    )
    assert not any(token in module_source for token in forbidden_tokens)
