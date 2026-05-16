"""Deterministic catalog of agent-facing precomputed deliverables.

The catalog is deliberately static. It describes what an agent may route to
before live execution exists: user segments, deliverable slugs, source
dependencies, pricing posture, and whether cached official/public sources are
sufficient or a tenant CSV overlay is required.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

CATALOG_VERSION = "jpcite.outcome_catalog.p0.v1"
NO_HIT_SEMANTICS: Literal["no_hit_not_absence"] = "no_hit_not_absence"

UserSegment = Literal[
    "agent_builder",
    "accounting_firm",
    "compliance_team",
    "financial_institution",
    "foreign_investor",
    "healthcare_operator",
    "judicial_scrivener",
    "local_government_vendor",
    "sme_operator",
    "tax_advisor",
]

EvidenceDependencyType = Literal[
    "official_court_record",
    "official_disclosure",
    "official_law_regulation",
    "official_program_guideline",
    "official_public_notice",
    "official_public_registry",
    "official_public_statistics",
    "public_source_receipt_graph",
    "tenant_private_csv_overlay",
]

PricingPosture = Literal[
    "free_preview",
    "accepted_artifact_low",
    "accepted_artifact_standard",
    "accepted_artifact_premium",
    "accepted_artifact_csv_overlay",
]

BillingPosture = Literal[
    "not_billable_preview_only",
    "billable_after_user_accepts_artifact",
    "billable_after_csv_consent_and_artifact_acceptance",
]

InputRequirement = Literal[
    "cached_official_public_only",
    "cached_public_plus_user_csv",
]


@dataclass(frozen=True)
class SourceDependency:
    """Source family needed before a deliverable can make public claims."""

    dependency_type: EvidenceDependencyType
    source_family_id: str
    source_role: str
    cached_official_or_public: bool
    user_csv: bool = False

    def __post_init__(self) -> None:
        if not self.source_family_id:
            raise ValueError("source_family_id is required")
        if not self.source_role:
            raise ValueError("source_role is required")
        if self.dependency_type == "tenant_private_csv_overlay" and not self.user_csv:
            raise ValueError("tenant private CSV dependencies must set user_csv")
        if self.user_csv and self.cached_official_or_public:
            raise ValueError("user CSV dependencies cannot be public-source cached")

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class OutcomeCatalogEntry:
    """One precomputed deliverable contract visible to AI agents."""

    deliverable_slug: str
    display_name: str
    outcome_contract_id: str
    user_segments: tuple[UserSegment, ...]
    high_value: bool
    use_case_tags: tuple[str, ...]
    source_dependencies: tuple[SourceDependency, ...]
    pricing_posture: PricingPosture
    billing_posture: BillingPosture
    input_requirement: InputRequirement
    cached_official_public_sources_sufficient: bool
    requires_user_csv: bool
    precomputed_output: Literal[True] = True
    agent_facing: Literal[True] = True
    request_time_llm_dependency: Literal[False] = False
    live_network_dependency: Literal[False] = False
    live_aws_dependency: Literal[False] = False
    api_wiring_required: Literal[False] = False
    no_hit_semantics: Literal["no_hit_not_absence"] = NO_HIT_SEMANTICS

    def __post_init__(self) -> None:
        _validate_slug(self.deliverable_slug)
        if not self.display_name:
            raise ValueError("display_name is required")
        if not self.outcome_contract_id:
            raise ValueError("outcome_contract_id is required")
        if not self.user_segments:
            raise ValueError(f"{self.deliverable_slug} must declare user segments")
        if not self.use_case_tags:
            raise ValueError(f"{self.deliverable_slug} must declare use cases")
        if self.high_value and not self.source_dependencies:
            raise ValueError(f"{self.deliverable_slug} high-value deliverables need sources")
        if self.high_value and self.billing_posture == "not_billable_preview_only":
            raise ValueError(f"{self.deliverable_slug} high-value deliverables need billing")
        if (
            self.pricing_posture == "free_preview"
            and self.billing_posture != "not_billable_preview_only"
        ):
            raise ValueError("free preview pricing cannot be billable")
        if self.requires_user_csv != any(dep.user_csv for dep in self.source_dependencies):
            raise ValueError(f"{self.deliverable_slug} CSV requirement does not match sources")
        if self.requires_user_csv:
            if self.cached_official_public_sources_sufficient:
                raise ValueError(f"{self.deliverable_slug} cannot be cached-only and CSV-required")
            if self.input_requirement != "cached_public_plus_user_csv":
                raise ValueError(f"{self.deliverable_slug} must declare CSV input requirement")
            if self.billing_posture != "billable_after_csv_consent_and_artifact_acceptance":
                raise ValueError(
                    f"{self.deliverable_slug} CSV deliverables need CSV billing posture"
                )
        if not self.requires_user_csv and self.input_requirement != "cached_official_public_only":
            raise ValueError(f"{self.deliverable_slug} non-CSV deliverables must be cached-only")
        if not self.cached_official_public_sources_sufficient and not self.requires_user_csv:
            raise ValueError(f"{self.deliverable_slug} needs an explicit input source")
        if self.request_time_llm_dependency:
            raise ValueError("request-time LLM dependency is not allowed")
        if self.live_network_dependency:
            raise ValueError("live network dependency is not allowed")
        if self.live_aws_dependency:
            raise ValueError("live AWS dependency is not allowed")
        if self.api_wiring_required:
            raise ValueError("API wiring is not part of this catalog")

    @property
    def evidence_dependency_types(self) -> tuple[EvidenceDependencyType, ...]:
        """Return dependency types in first-seen order for agent routing."""

        seen: set[EvidenceDependencyType] = set()
        ordered: list[EvidenceDependencyType] = []
        for dependency in self.source_dependencies:
            if dependency.dependency_type in seen:
                continue
            seen.add(dependency.dependency_type)
            ordered.append(dependency.dependency_type)
        return tuple(ordered)

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["evidence_dependency_types"] = self.evidence_dependency_types
        return data


def build_outcome_catalog() -> tuple[OutcomeCatalogEntry, ...]:
    """Build the deterministic deliverable catalog in stable slug order."""

    catalog = (
        OutcomeCatalogEntry(
            deliverable_slug="company-public-baseline",
            display_name="Company public baseline",
            outcome_contract_id="company_public_baseline",
            user_segments=(
                "agent_builder",
                "tax_advisor",
                "financial_institution",
                "foreign_investor",
            ),
            high_value=True,
            use_case_tags=(
                "japanese_public_official_info",
                "company_registry",
                "invoice_registry",
                "public_disclosure",
            ),
            source_dependencies=(
                _source("official_public_registry", "gBizINFO", "corporate identity"),
                _source("official_public_registry", "nta_invoice", "invoice status"),
                _source("official_disclosure", "edinet", "securities disclosure context"),
            ),
            pricing_posture="accepted_artifact_standard",
            billing_posture="billable_after_user_accepts_artifact",
            input_requirement="cached_official_public_only",
            cached_official_public_sources_sufficient=True,
            requires_user_csv=False,
        ),
        OutcomeCatalogEntry(
            deliverable_slug="invoice-registrant-public-check",
            display_name="Invoice registrant public check",
            outcome_contract_id="invoice_registrant_public_check",
            user_segments=("tax_advisor", "accounting_firm", "sme_operator"),
            high_value=True,
            use_case_tags=(
                "japanese_public_official_info",
                "invoice_registry",
                "tax_compliance",
            ),
            source_dependencies=(
                _source("official_public_registry", "nta_invoice", "qualified invoice status"),
            ),
            pricing_posture="accepted_artifact_low",
            billing_posture="billable_after_user_accepts_artifact",
            input_requirement="cached_official_public_only",
            cached_official_public_sources_sufficient=True,
            requires_user_csv=False,
        ),
        OutcomeCatalogEntry(
            deliverable_slug="subsidy-grant-candidate-pack",
            display_name="Subsidy and grant candidate pack",
            outcome_contract_id="application_strategy",
            user_segments=(
                "tax_advisor",
                "accounting_firm",
                "sme_operator",
                "financial_institution",
            ),
            high_value=True,
            use_case_tags=(
                "japanese_public_official_info",
                "subsidy_grants",
                "application_strategy",
                "deadline_watch",
            ),
            source_dependencies=(
                _source("official_program_guideline", "jgrants", "program listing"),
                _source("official_program_guideline", "sme_agency", "program guideline"),
                _source("official_public_notice", "local_government_notice", "local programs"),
            ),
            pricing_posture="accepted_artifact_premium",
            billing_posture="billable_after_user_accepts_artifact",
            input_requirement="cached_official_public_only",
            cached_official_public_sources_sufficient=True,
            requires_user_csv=False,
        ),
        OutcomeCatalogEntry(
            deliverable_slug="law-regulation-change-watch",
            display_name="Law and regulation change watch",
            outcome_contract_id="regulation_change_watch",
            user_segments=("agent_builder", "tax_advisor", "compliance_team"),
            high_value=True,
            use_case_tags=(
                "japanese_public_official_info",
                "law_regulation",
                "change_watch",
                "public_comment",
            ),
            source_dependencies=(
                _source("official_law_regulation", "egov_law", "current law text"),
                _source("official_public_notice", "meti_notice", "policy notices"),
                _source("official_public_notice", "mhlw_notice", "labor and health notices"),
            ),
            pricing_posture="accepted_artifact_standard",
            billing_posture="billable_after_user_accepts_artifact",
            input_requirement="cached_official_public_only",
            cached_official_public_sources_sufficient=True,
            requires_user_csv=False,
        ),
        OutcomeCatalogEntry(
            deliverable_slug="local-government-permit-obligation-map",
            display_name="Local government permit and obligation map",
            outcome_contract_id="local_government_permit_obligation_map",
            user_segments=(
                "sme_operator",
                "tax_advisor",
                "local_government_vendor",
                "compliance_team",
            ),
            high_value=True,
            use_case_tags=(
                "japanese_public_official_info",
                "local_government",
                "permits",
                "law_regulation",
            ),
            source_dependencies=(
                _source("official_public_notice", "local_government_notice", "local rules"),
                _source("official_law_regulation", "egov_law", "national rule baseline"),
            ),
            pricing_posture="accepted_artifact_premium",
            billing_posture="billable_after_user_accepts_artifact",
            input_requirement="cached_official_public_only",
            cached_official_public_sources_sufficient=True,
            requires_user_csv=False,
        ),
        OutcomeCatalogEntry(
            deliverable_slug="court-enforcement-citation-pack",
            display_name="Court and enforcement citation pack",
            outcome_contract_id="court_enforcement_citation_pack",
            user_segments=("judicial_scrivener", "compliance_team", "agent_builder"),
            high_value=True,
            use_case_tags=(
                "japanese_public_official_info",
                "court_enforcement",
                "citation_pack",
            ),
            source_dependencies=(
                _source("official_court_record", "courts_jp", "published decisions"),
                _source("official_public_notice", "meti_enforcement", "agency enforcement"),
                _source("official_public_notice", "maff_enforcement", "agency enforcement"),
            ),
            pricing_posture="accepted_artifact_standard",
            billing_posture="billable_after_user_accepts_artifact",
            input_requirement="cached_official_public_only",
            cached_official_public_sources_sufficient=True,
            requires_user_csv=False,
        ),
        OutcomeCatalogEntry(
            deliverable_slug="public-statistics-market-context",
            display_name="Public statistics market context",
            outcome_contract_id="public_statistics_market_context",
            user_segments=(
                "foreign_investor",
                "financial_institution",
                "sme_operator",
                "agent_builder",
            ),
            high_value=True,
            use_case_tags=(
                "japanese_public_official_info",
                "public_statistics",
                "market_context",
            ),
            source_dependencies=(
                _source("official_public_statistics", "estat", "national statistics"),
                _source("official_public_statistics", "prefecture_statistics", "local statistics"),
            ),
            pricing_posture="accepted_artifact_standard",
            billing_posture="billable_after_user_accepts_artifact",
            input_requirement="cached_official_public_only",
            cached_official_public_sources_sufficient=True,
            requires_user_csv=False,
        ),
        OutcomeCatalogEntry(
            deliverable_slug="client-monthly-public-watchlist",
            display_name="Client monthly public watchlist",
            outcome_contract_id="client_monthly_review",
            user_segments=("tax_advisor", "accounting_firm"),
            high_value=True,
            use_case_tags=(
                "japanese_public_official_info",
                "monthly_review",
                "invoice_registry",
                "subsidy_grants",
                "law_regulation",
            ),
            source_dependencies=(
                _source("official_public_registry", "gBizINFO", "client identity"),
                _source("official_public_registry", "nta_invoice", "invoice watch"),
                _source("official_program_guideline", "jgrants", "program watch"),
                _source("official_law_regulation", "egov_law", "legal change watch"),
            ),
            pricing_posture="accepted_artifact_premium",
            billing_posture="billable_after_user_accepts_artifact",
            input_requirement="cached_official_public_only",
            cached_official_public_sources_sufficient=True,
            requires_user_csv=False,
        ),
        OutcomeCatalogEntry(
            deliverable_slug="accounting-csv-public-counterparty-check",
            display_name="Accounting CSV public counterparty check",
            outcome_contract_id="csv_overlay_public_check",
            user_segments=("tax_advisor", "accounting_firm", "sme_operator"),
            high_value=True,
            use_case_tags=(
                "japanese_public_official_info",
                "tax_accounting_csv_overlay",
                "invoice_registry",
                "company_registry",
            ),
            source_dependencies=(
                _csv("accounting_csv", "counterparty and transaction shape"),
                _source("official_public_registry", "nta_invoice", "public invoice match"),
                _source("official_public_registry", "gBizINFO", "public company match"),
            ),
            pricing_posture="accepted_artifact_csv_overlay",
            billing_posture="billable_after_csv_consent_and_artifact_acceptance",
            input_requirement="cached_public_plus_user_csv",
            cached_official_public_sources_sufficient=False,
            requires_user_csv=True,
        ),
        OutcomeCatalogEntry(
            deliverable_slug="cashbook-csv-subsidy-fit-screen",
            display_name="Cashbook CSV subsidy fit screen",
            outcome_contract_id="cashbook_csv_subsidy_fit_screen",
            user_segments=("tax_advisor", "accounting_firm", "sme_operator"),
            high_value=True,
            use_case_tags=(
                "japanese_public_official_info",
                "tax_accounting_csv_overlay",
                "subsidy_grants",
                "application_strategy",
            ),
            source_dependencies=(
                _csv("cashbook_csv", "expense categories and timing"),
                _source("official_program_guideline", "jgrants", "program listing"),
                _source("official_program_guideline", "sme_agency", "eligible expense rules"),
            ),
            pricing_posture="accepted_artifact_csv_overlay",
            billing_posture="billable_after_csv_consent_and_artifact_acceptance",
            input_requirement="cached_public_plus_user_csv",
            cached_official_public_sources_sufficient=False,
            requires_user_csv=True,
        ),
        OutcomeCatalogEntry(
            deliverable_slug="source-receipt-ledger",
            display_name="Source receipt ledger",
            outcome_contract_id="source_receipt_ledger",
            user_segments=("agent_builder", "compliance_team", "financial_institution"),
            high_value=True,
            use_case_tags=(
                "japanese_public_official_info",
                "source_receipts",
                "claim_graph",
            ),
            source_dependencies=(
                _source("public_source_receipt_graph", "source_receipt_ledger", "claim receipts"),
                _source("official_public_registry", "gBizINFO", "registry receipt"),
                _source("official_law_regulation", "egov_law", "law receipt"),
            ),
            pricing_posture="accepted_artifact_standard",
            billing_posture="billable_after_user_accepts_artifact",
            input_requirement="cached_official_public_only",
            cached_official_public_sources_sufficient=True,
            requires_user_csv=False,
        ),
        OutcomeCatalogEntry(
            deliverable_slug="evidence-answer-citation-pack",
            display_name="Evidence answer citation pack",
            outcome_contract_id="evidence_answer",
            user_segments=("agent_builder", "tax_advisor", "compliance_team"),
            high_value=True,
            use_case_tags=(
                "japanese_public_official_info",
                "evidence_answer",
                "law_regulation",
                "citation_pack",
            ),
            source_dependencies=(
                _source("official_law_regulation", "egov_law", "primary authority"),
                _source("official_public_notice", "official_notice", "agency context"),
                _source("public_source_receipt_graph", "source_receipt_ledger", "claim receipts"),
            ),
            pricing_posture="accepted_artifact_standard",
            billing_posture="billable_after_user_accepts_artifact",
            input_requirement="cached_official_public_only",
            cached_official_public_sources_sufficient=True,
            requires_user_csv=False,
        ),
        OutcomeCatalogEntry(
            deliverable_slug="foreign-investor-japan-public-entry-brief",
            display_name="Foreign investor Japan public entry brief",
            outcome_contract_id="foreign_investor_japan_public_entry_brief",
            user_segments=("foreign_investor", "financial_institution", "agent_builder"),
            high_value=True,
            use_case_tags=(
                "japanese_public_official_info",
                "foreign_investment",
                "public_disclosure",
                "law_regulation",
            ),
            source_dependencies=(
                _source("official_disclosure", "edinet", "disclosure context"),
                _source("official_law_regulation", "egov_law", "legal baseline"),
                _source("official_public_notice", "meti_notice", "investment policy context"),
            ),
            pricing_posture="accepted_artifact_premium",
            billing_posture="billable_after_user_accepts_artifact",
            input_requirement="cached_official_public_only",
            cached_official_public_sources_sufficient=True,
            requires_user_csv=False,
        ),
        OutcomeCatalogEntry(
            deliverable_slug="healthcare-regulatory-public-check",
            display_name="Healthcare regulatory public check",
            outcome_contract_id="healthcare_regulatory_public_check",
            user_segments=("healthcare_operator", "compliance_team", "agent_builder"),
            high_value=True,
            use_case_tags=(
                "japanese_public_official_info",
                "healthcare_regulation",
                "law_regulation",
                "local_government",
            ),
            source_dependencies=(
                _source("official_public_notice", "mhlw_notice", "healthcare notices"),
                _source("official_law_regulation", "egov_law", "statutory baseline"),
                _source("official_public_notice", "local_government_notice", "local notices"),
            ),
            pricing_posture="accepted_artifact_standard",
            billing_posture="billable_after_user_accepts_artifact",
            input_requirement="cached_official_public_only",
            cached_official_public_sources_sufficient=True,
            requires_user_csv=False,
        ),
    )
    validate_outcome_catalog(catalog)
    return catalog


def build_outcome_catalog_shape() -> dict[str, object]:
    """Return a JSON-ready catalog shape for release artifacts and tests."""

    # Local import to avoid a circular import between outcome_catalog and
    # pricing_policy (pricing_policy imports PricingPosture from this module
    # under TYPE_CHECKING and at runtime the catalog needs the JPY price
    # mapping to embed estimated_price_jpy in the public JSON shape).
    from jpintel_mcp.agent_runtime.pricing_policy import (  # noqa: PLC0415
        price_for_pricing_posture,
    )

    catalog = build_outcome_catalog()
    deliverables: list[dict[str, object]] = []
    for entry in catalog:
        entry_shape = entry.to_dict()
        price_jpy = price_for_pricing_posture(entry.pricing_posture)
        if price_jpy is None:
            raise ValueError(
                f"unknown pricing posture for {entry.deliverable_slug}: {entry.pricing_posture}"
            )
        entry_shape["estimated_price_jpy"] = price_jpy
        deliverables.append(entry_shape)
    return {
        "schema_version": CATALOG_VERSION,
        "no_hit_semantics": NO_HIT_SEMANTICS,
        "request_time_llm_dependency": False,
        "live_network_dependency": False,
        "live_aws_dependency": False,
        "api_wiring_required": False,
        "deliverables": deliverables,
    }


def get_outcome_by_slug(deliverable_slug: str) -> OutcomeCatalogEntry:
    """Return a catalog entry by deliverable slug."""

    for entry in build_outcome_catalog():
        if entry.deliverable_slug == deliverable_slug:
            return entry
    raise ValueError(f"unknown outcome deliverable slug: {deliverable_slug}")


def high_value_deliverables() -> tuple[OutcomeCatalogEntry, ...]:
    """Return deliverables intended to be paid accepted artifacts."""

    return tuple(entry for entry in build_outcome_catalog() if entry.high_value)


def validate_outcome_catalog(catalog: tuple[OutcomeCatalogEntry, ...]) -> None:
    """Validate cross-entry catalog invariants."""

    slugs = [entry.deliverable_slug for entry in catalog]
    duplicate_slugs = sorted({slug for slug in slugs if slugs.count(slug) > 1})
    if duplicate_slugs:
        raise ValueError(f"duplicate deliverable slugs: {', '.join(duplicate_slugs)}")


def _source(
    dependency_type: EvidenceDependencyType,
    source_family_id: str,
    source_role: str,
) -> SourceDependency:
    return SourceDependency(
        dependency_type=dependency_type,
        source_family_id=source_family_id,
        source_role=source_role,
        cached_official_or_public=True,
    )


def _csv(source_family_id: str, source_role: str) -> SourceDependency:
    return SourceDependency(
        dependency_type="tenant_private_csv_overlay",
        source_family_id=source_family_id,
        source_role=source_role,
        cached_official_or_public=False,
        user_csv=True,
    )


def _validate_slug(slug: str) -> None:
    if not slug:
        raise ValueError("deliverable_slug is required")
    allowed_chars = set("abcdefghijklmnopqrstuvwxyz0123456789-")
    if slug != slug.lower() or not set(slug) <= allowed_chars:
        raise ValueError(f"invalid deliverable slug: {slug}")
    if slug.startswith("-") or slug.endswith("-") or "--" in slug:
        raise ValueError(f"invalid deliverable slug: {slug}")
