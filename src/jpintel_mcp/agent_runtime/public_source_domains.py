"""Static official-source domain policy catalog for future AWS collection.

The catalog is intentionally declarative. It does not fetch robots.txt, inspect
terms pages, resolve domains, call AWS, or perform scraping. Collection remains
disabled until a future runtime verifies robots/terms posture per source.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Literal

CATALOG_VERSION = "jpcite.public_source_domains.p0.v1"
PLAYWRIGHT_SCREENSHOT_MAX_PX = 1600

CollectionMethod = Literal[
    "http_fetch",
    "sitemap",
    "playwright_screenshot",
    "pdf_text_extraction",
]
SourceCategory = Literal[
    "laws_regulations",
    "tax",
    "subsidies",
    "local_governments",
    "statistics",
    "procurement",
    "court_admin_guidance",
]
OfficialOwnerCategory = Literal[
    "national_government",
    "local_government",
    "court",
    "incorporated_admin_agency",
]

ALLOWED_COLLECTION_METHODS: tuple[CollectionMethod, ...] = (
    "http_fetch",
    "sitemap",
    "playwright_screenshot",
    "pdf_text_extraction",
)
REQUIRED_SOURCE_CATEGORIES: tuple[SourceCategory, ...] = (
    "laws_regulations",
    "tax",
    "subsidies",
    "local_governments",
    "statistics",
    "procurement",
    "court_admin_guidance",
)
OFFICIAL_OWNER_CATEGORIES: tuple[OfficialOwnerCategory, ...] = (
    "national_government",
    "local_government",
    "court",
    "incorporated_admin_agency",
)
OFFICIAL_DOMAIN_SUFFIXES = (".go.jp", ".lg.jp")


@dataclass(frozen=True)
class PlaywrightScreenshotPolicy:
    """Guardrails for official-page visual evidence capture."""

    enabled: bool
    max_viewport_width_px: int = PLAYWRIGHT_SCREENSHOT_MAX_PX
    max_bitmap_long_edge_px: int = PLAYWRIGHT_SCREENSHOT_MAX_PX
    full_page_capture_allowed: bool = False
    pii_redaction_required: Literal[True] = True
    human_review_required_before_public_use: Literal[True] = True

    def __post_init__(self) -> None:
        if self.max_viewport_width_px > PLAYWRIGHT_SCREENSHOT_MAX_PX:
            raise ValueError("Playwright screenshot viewport width exceeds 1600px")
        if self.max_bitmap_long_edge_px > PLAYWRIGHT_SCREENSHOT_MAX_PX:
            raise ValueError("Playwright screenshot bitmap long edge exceeds 1600px")
        if self.enabled and self.full_page_capture_allowed:
            raise ValueError("full-page Playwright screenshots are not allowed")

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class RobotsTermsPosture:
    """Required preflight posture before any future collection job runs."""

    robots_txt_must_be_checked: Literal[True] = True
    robots_txt_must_be_obeyed: Literal[True] = True
    terms_must_be_reviewed: Literal[True] = True
    stop_on_disallow_or_terms_conflict: Literal[True] = True
    user_agent_contact_required: Literal[True] = True

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class PublicSourceDomainPolicy:
    """First-party public source family and collection boundaries."""

    source_family_id: str
    display_name: str
    source_category: SourceCategory
    official_owner_category: OfficialOwnerCategory
    publisher_name: str
    domain_patterns: tuple[str, ...]
    canonical_entrypoints: tuple[str, ...]
    allowed_collection_methods: tuple[CollectionMethod, ...]
    artifact_use_cases: tuple[str, ...]
    robots_terms_posture: RobotsTermsPosture = field(default_factory=RobotsTermsPosture)
    playwright_screenshot_policy: PlaywrightScreenshotPolicy = field(
        default_factory=lambda: PlaywrightScreenshotPolicy(enabled=False)
    )
    robots_posture: Literal["check_and_obey_before_collection"] = "check_and_obey_before_collection"
    terms_posture: Literal["review_and_block_on_conflict"] = "review_and_block_on_conflict"
    pii_collection_allowed: Literal[False] = False
    pii_exclusion_policy: str = (
        "Exclude direct personal identifiers, raw personal-case facts, and "
        "individual proprietor details from public artifacts."
    )
    excluded_pii_subjects: tuple[str, ...] = (
        "natural_person_names",
        "home_addresses",
        "phone_numbers",
        "email_addresses",
        "individual_taxpayer_identifiers",
    )
    resale_redistribution_caution: str = (
        "Use as source receipts, metadata, short excerpts, and derived analysis only; "
        "do not resell or bulk-redistribute mirrored source content."
    )
    bulk_resale_or_redistribution_allowed: Literal[False] = False
    first_party_official_source: Literal[True] = True
    aws_collection_scope: Literal["future_public_aws_collection_candidate"] = (
        "future_public_aws_collection_candidate"
    )
    collection_enabled_initially: Literal[False] = False

    def __post_init__(self) -> None:
        if not self.source_family_id.strip():
            raise ValueError("source_family_id is required")
        if not self.domain_patterns:
            raise ValueError(f"{self.source_family_id} must declare domain patterns")
        if not self.canonical_entrypoints:
            raise ValueError(f"{self.source_family_id} must declare entrypoints")
        if not self.allowed_collection_methods:
            raise ValueError(f"{self.source_family_id} must declare collection methods")
        if not self.artifact_use_cases:
            raise ValueError(f"{self.source_family_id} must declare artifact use cases")
        if not self.first_party_official_source:
            raise ValueError(f"{self.source_family_id} must be first-party official")
        if self.official_owner_category not in OFFICIAL_OWNER_CATEGORIES:
            raise ValueError(f"{self.source_family_id} has non-official owner category")
        unknown_methods = set(self.allowed_collection_methods).difference(
            ALLOWED_COLLECTION_METHODS
        )
        if unknown_methods:
            raise ValueError(f"{self.source_family_id} has unknown methods: {unknown_methods}")
        for domain_pattern in self.domain_patterns:
            if not is_first_party_official_domain_pattern(domain_pattern):
                raise ValueError(
                    f"{self.source_family_id} has non-official domain: {domain_pattern}"
                )
        if "playwright_screenshot" in self.allowed_collection_methods:
            if not self.playwright_screenshot_policy.enabled:
                raise ValueError(
                    f"{self.source_family_id} allows screenshots without screenshot policy"
                )
        elif self.playwright_screenshot_policy.enabled:
            raise ValueError(f"{self.source_family_id} enables screenshot policy without method")
        if self.pii_collection_allowed:
            raise ValueError(f"{self.source_family_id} cannot allow PII collection")
        if self.bulk_resale_or_redistribution_allowed:
            raise ValueError(f"{self.source_family_id} cannot allow bulk resale")
        if self.collection_enabled_initially:
            raise ValueError(f"{self.source_family_id} cannot enable live collection")

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def build_public_source_domain_catalog() -> tuple[PublicSourceDomainPolicy, ...]:
    """Return the deterministic public-source domain policy catalog."""

    screenshot_policy = PlaywrightScreenshotPolicy(enabled=True)

    return (
        PublicSourceDomainPolicy(
            source_family_id="egov_laws_regulations",
            display_name="e-Gov laws, regulations, and public comment sources",
            source_category="laws_regulations",
            official_owner_category="national_government",
            publisher_name="Digital Agency and responsible ministries",
            domain_patterns=(
                "elaws.e-gov.go.jp",
                "www.e-gov.go.jp",
                "public-comment.e-gov.go.jp",
                "japaneselawtranslation.go.jp",
            ),
            canonical_entrypoints=(
                "https://elaws.e-gov.go.jp/",
                "https://public-comment.e-gov.go.jp/",
            ),
            allowed_collection_methods=ALLOWED_COLLECTION_METHODS,
            artifact_use_cases=(
                "law_article_source_receipts",
                "amendment_change_diff",
                "regulatory_context_packets",
            ),
            playwright_screenshot_policy=screenshot_policy,
        ),
        PublicSourceDomainPolicy(
            source_family_id="tax_agency_guidance",
            display_name="National and local tax agency guidance",
            source_category="tax",
            official_owner_category="national_government",
            publisher_name="National Tax Agency and local tax authorities",
            domain_patterns=(
                "nta.go.jp",
                "www.nta.go.jp",
                "invoice-kohyo.nta.go.jp",
                "eltax.lta.go.jp",
            ),
            canonical_entrypoints=(
                "https://www.nta.go.jp/",
                "https://invoice-kohyo.nta.go.jp/",
                "https://www.eltax.lta.go.jp/",
            ),
            allowed_collection_methods=ALLOWED_COLLECTION_METHODS,
            artifact_use_cases=(
                "tax_rule_source_receipts",
                "invoice_system_status_checks",
                "tax_measure_sunset_watch",
            ),
            playwright_screenshot_policy=screenshot_policy,
        ),
        PublicSourceDomainPolicy(
            source_family_id="subsidy_program_portals",
            display_name="Official subsidy and grant program portals",
            source_category="subsidies",
            official_owner_category="incorporated_admin_agency",
            publisher_name="Government grant portals and SME support bodies",
            domain_patterns=(
                "jgrants-portal.go.jp",
                "www.jgrants-portal.go.jp",
                "hojyokin-portal.go.jp",
                "www.hojyokin-portal.go.jp",
                "mirasapo-plus.go.jp",
                "j-net21.smrj.go.jp",
            ),
            canonical_entrypoints=(
                "https://www.jgrants-portal.go.jp/",
                "https://www.hojyokin-portal.go.jp/",
                "https://mirasapo-plus.go.jp/",
            ),
            allowed_collection_methods=ALLOWED_COLLECTION_METHODS,
            artifact_use_cases=(
                "grant_eligibility_packets",
                "deadline_document_checklists",
                "program_successor_revision_watch",
            ),
            playwright_screenshot_policy=screenshot_policy,
        ),
        PublicSourceDomainPolicy(
            source_family_id="local_government_public_sources",
            display_name="Prefecture and municipality official domains",
            source_category="local_governments",
            official_owner_category="local_government",
            publisher_name="Japanese prefectures and municipalities",
            domain_patterns=(
                "*.lg.jp",
                "www.metro.tokyo.lg.jp",
                "www.city.yokohama.lg.jp",
                "www.city.osaka.lg.jp",
            ),
            canonical_entrypoints=(
                "https://www.metro.tokyo.lg.jp/",
                "https://www.city.yokohama.lg.jp/",
                "https://www.city.osaka.lg.jp/",
            ),
            allowed_collection_methods=ALLOWED_COLLECTION_METHODS,
            artifact_use_cases=(
                "local_subsidy_source_receipts",
                "permit_requirement_packets",
                "regional_deadline_watch",
            ),
            playwright_screenshot_policy=screenshot_policy,
        ),
        PublicSourceDomainPolicy(
            source_family_id="statistics_open_data",
            display_name="Official statistics and open-data portals",
            source_category="statistics",
            official_owner_category="national_government",
            publisher_name="Statistics Bureau and government open-data programs",
            domain_patterns=(
                "e-stat.go.jp",
                "www.e-stat.go.jp",
                "stat.go.jp",
                "www.stat.go.jp",
                "data.e-gov.go.jp",
                "resas.go.jp",
            ),
            canonical_entrypoints=(
                "https://www.e-stat.go.jp/",
                "https://www.stat.go.jp/",
                "https://www.data.e-gov.go.jp/",
            ),
            allowed_collection_methods=ALLOWED_COLLECTION_METHODS,
            artifact_use_cases=(
                "regional_statistics_receipts",
                "market_size_baselines",
                "geo_comparison_packets",
            ),
            playwright_screenshot_policy=screenshot_policy,
        ),
        PublicSourceDomainPolicy(
            source_family_id="government_procurement",
            display_name="Government procurement and tender notice sources",
            source_category="procurement",
            official_owner_category="national_government",
            publisher_name="Government procurement systems",
            domain_patterns=(
                "p-portal.go.jp",
                "www.p-portal.go.jp",
                "geps.go.jp",
                "www.geps.go.jp",
                "www.chotatujoho.geps.go.jp",
            ),
            canonical_entrypoints=(
                "https://www.p-portal.go.jp/",
                "https://www.geps.go.jp/",
                "https://www.chotatujoho.geps.go.jp/",
            ),
            allowed_collection_methods=ALLOWED_COLLECTION_METHODS,
            artifact_use_cases=(
                "procurement_notice_receipts",
                "vendor_opportunity_packets",
                "bid_deadline_watch",
            ),
            playwright_screenshot_policy=screenshot_policy,
        ),
        PublicSourceDomainPolicy(
            source_family_id="court_decisions",
            display_name="Court decisions and court notices",
            source_category="court_admin_guidance",
            official_owner_category="court",
            publisher_name="Courts in Japan",
            domain_patterns=(
                "courts.go.jp",
                "www.courts.go.jp",
            ),
            canonical_entrypoints=("https://www.courts.go.jp/",),
            allowed_collection_methods=ALLOWED_COLLECTION_METHODS,
            artifact_use_cases=(
                "court_decision_source_receipts",
                "dispute_context_packets",
                "court_notice_watch",
            ),
            playwright_screenshot_policy=screenshot_policy,
        ),
        PublicSourceDomainPolicy(
            source_family_id="ministry_admin_guidance",
            display_name="Ministry administrative guidance and enforcement notices",
            source_category="court_admin_guidance",
            official_owner_category="national_government",
            publisher_name="Ministry administrative guidance publishers",
            domain_patterns=(
                "moj.go.jp",
                "www.moj.go.jp",
                "meti.go.jp",
                "www.meti.go.jp",
                "mhlw.go.jp",
                "www.mhlw.go.jp",
                "fsa.go.jp",
                "www.fsa.go.jp",
            ),
            canonical_entrypoints=(
                "https://www.moj.go.jp/",
                "https://www.meti.go.jp/",
                "https://www.mhlw.go.jp/",
                "https://www.fsa.go.jp/",
            ),
            allowed_collection_methods=ALLOWED_COLLECTION_METHODS,
            artifact_use_cases=(
                "administrative_guidance_packets",
                "regulatory_faq_source_receipts",
                "enforcement_context_watch",
            ),
            playwright_screenshot_policy=screenshot_policy,
        ),
    )


def build_public_source_domain_catalog_shape(
    catalog: tuple[PublicSourceDomainPolicy, ...] | None = None,
) -> dict[str, object]:
    """Return a JSON-ready catalog shape for release artifacts and tests."""

    policies = catalog if catalog is not None else build_public_source_domain_catalog()
    category_index = {
        category: [
            policy.source_family_id for policy in policies if policy.source_category == category
        ]
        for category in REQUIRED_SOURCE_CATEGORIES
    }

    return {
        "schema_version": CATALOG_VERSION,
        "aws_collection_scope": "future_public_aws_collection_candidate",
        "collection_enabled_initially": False,
        "allowed_collection_methods": ALLOWED_COLLECTION_METHODS,
        "playwright_screenshot_max_px": PLAYWRIGHT_SCREENSHOT_MAX_PX,
        "official_domain_suffixes": OFFICIAL_DOMAIN_SUFFIXES,
        "required_source_categories": REQUIRED_SOURCE_CATEGORIES,
        "category_index": category_index,
        "catalog": [policy.to_dict() for policy in policies],
    }


def is_first_party_official_domain_pattern(domain_pattern: str) -> bool:
    """Return True when a policy pattern stays inside official JP domains."""

    domain = _normalize_domain_pattern(domain_pattern)
    if not domain:
        return False
    if "/" in domain or ":" in domain:
        return False
    if "*" in domain_pattern and not domain_pattern.startswith("*."):
        return False
    return any(
        domain == suffix.removeprefix(".") or domain.endswith(suffix)
        for suffix in OFFICIAL_DOMAIN_SUFFIXES
    )


def is_public_source_domain_allowed(
    domain: str,
    catalog: tuple[PublicSourceDomainPolicy, ...] | None = None,
) -> bool:
    """Check whether a domain is covered by the static official-source catalog."""

    lookup_domain = _normalize_domain_pattern(domain)
    if not lookup_domain:
        return False
    policies = catalog if catalog is not None else build_public_source_domain_catalog()
    return any(
        _domain_matches_pattern(lookup_domain, pattern)
        for policy in policies
        for pattern in policy.domain_patterns
    )


def _domain_matches_pattern(domain: str, pattern: str) -> bool:
    normalized_pattern = _normalize_domain_pattern(pattern)
    if pattern.startswith("*."):
        return domain == normalized_pattern or domain.endswith(f".{normalized_pattern}")
    return domain == normalized_pattern


def _normalize_domain_pattern(domain_pattern: str) -> str:
    return domain_pattern.strip().lower().removeprefix("*.").removeprefix("www.")
