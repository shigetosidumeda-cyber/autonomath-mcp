"""Crosswalk from outcome deliverables to source, algorithm, CSV, and AWS stages.

The crosswalk is static metadata. It does not fetch source pages, inspect
tenant CSV rows, call AWS, or generate artifacts. Its job is to keep the
agent-facing outcome catalog connected to the public-source domain categories,
deterministic algorithm blueprints, accounting CSV compatibility profiles, and
offline AWS spend stages that would prepare the public evidence surface.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any

from jpintel_mcp.agent_runtime.accounting_csv_profiles import (
    build_accounting_csv_profiles,
)
from jpintel_mcp.agent_runtime.algorithm_blueprints import ALGORITHM_BLUEPRINT_IDS
from jpintel_mcp.agent_runtime.aws_spend_program import STAGED_NON_MUTATING_BATCHES
from jpintel_mcp.agent_runtime.outcome_catalog import (
    OutcomeCatalogEntry,
    build_outcome_catalog,
)
from jpintel_mcp.agent_runtime.public_source_domains import (
    build_public_source_domain_catalog,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

    from jpintel_mcp.agent_runtime.public_source_domains import SourceCategory

CATALOG_VERSION = "jpcite.outcome_source_crosswalk.p0.v1"

ACCOUNTING_CSV_PROFILE_KEYS = (
    "freee_transaction_rows",
    "freee_journal_rows",
    "money_forward_journal_rows",
    "yayoi_journal_rows",
    "tkc_general_journal_layout_v1",
)

STAGE_OFFICIAL_SOURCE_INVENTORY = "stage_01_official_source_inventory"
STAGE_PUBLIC_COLLECTION_CAPTURE = "stage_02_public_collection_capture"
STAGE_OCR_NORMALIZATION_SEARCH_BUILD = "stage_03_ocr_normalization_search_build"
STAGE_CLAIM_GRAPH_PACKET_FACTORY = "stage_04_claim_graph_packet_factory"
STAGE_QUALITY_EVAL_GAP_REVIEW = "stage_05_quality_eval_gap_review"
STAGE_RELEASE_ARTIFACT_PACKAGING = "stage_06_release_artifact_packaging"

PUBLIC_PACKET_AWS_STAGES = (
    STAGE_OFFICIAL_SOURCE_INVENTORY,
    STAGE_PUBLIC_COLLECTION_CAPTURE,
    STAGE_CLAIM_GRAPH_PACKET_FACTORY,
    STAGE_QUALITY_EVAL_GAP_REVIEW,
    STAGE_RELEASE_ARTIFACT_PACKAGING,
)
DOCUMENT_HEAVY_PUBLIC_PACKET_AWS_STAGES = (
    STAGE_OFFICIAL_SOURCE_INVENTORY,
    STAGE_PUBLIC_COLLECTION_CAPTURE,
    STAGE_OCR_NORMALIZATION_SEARCH_BUILD,
    STAGE_CLAIM_GRAPH_PACKET_FACTORY,
    STAGE_QUALITY_EVAL_GAP_REVIEW,
    STAGE_RELEASE_ARTIFACT_PACKAGING,
)

INTERNAL_NON_DOMAIN_DEPENDENCY_TYPES = frozenset(
    {
        "public_source_receipt_graph",
        "tenant_private_csv_overlay",
    }
)


@dataclass(frozen=True)
class SourceCategoryLink:
    """Outcome source families grouped under a public source domain category."""

    source_category: SourceCategory
    source_family_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.source_category:
            raise ValueError("source_category is required")
        if not self.source_family_ids:
            raise ValueError("source_family_ids are required")
        if any(not source_family_id.strip() for source_family_id in self.source_family_ids):
            raise ValueError("source_family_ids cannot be blank")
        if len(set(self.source_family_ids)) != len(self.source_family_ids):
            raise ValueError("source_family_ids must be unique within a category link")

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class OutcomeSourceCrosswalkEntry:
    """One deliverable row in the cross-catalog routing matrix."""

    deliverable_slug: str
    source_category_links: tuple[SourceCategoryLink, ...]
    algorithm_blueprint_ids: tuple[str, ...]
    aws_stage_ids: tuple[str, ...]
    accounting_csv_profile_keys: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.deliverable_slug:
            raise ValueError("deliverable_slug is required")
        if not self.source_category_links:
            raise ValueError(f"{self.deliverable_slug} must declare source categories")
        if not self.algorithm_blueprint_ids:
            raise ValueError(f"{self.deliverable_slug} must declare algorithm blueprints")
        if not self.aws_stage_ids:
            raise ValueError(f"{self.deliverable_slug} must declare AWS spend stages")
        _ensure_unique(
            self.algorithm_blueprint_ids,
            f"{self.deliverable_slug} algorithm_blueprint_ids",
        )
        _ensure_unique(self.aws_stage_ids, f"{self.deliverable_slug} aws_stage_ids")
        _ensure_unique(
            self.accounting_csv_profile_keys,
            f"{self.deliverable_slug} accounting_csv_profile_keys",
        )

    @property
    def public_source_categories(self) -> tuple[SourceCategory, ...]:
        """Return linked public source categories in first-seen order."""

        return _dedupe(link.source_category for link in self.source_category_links)

    @property
    def public_source_family_ids(self) -> tuple[str, ...]:
        """Return public source families represented by the source category links."""

        return _dedupe(
            source_family_id
            for link in self.source_category_links
            for source_family_id in link.source_family_ids
        )

    @property
    def requires_csv_overlay(self) -> bool:
        """Return whether this crosswalk row declares tenant CSV profile support."""

        return bool(self.accounting_csv_profile_keys)

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["public_source_categories"] = self.public_source_categories
        data["public_source_family_ids"] = self.public_source_family_ids
        data["requires_csv_overlay"] = self.requires_csv_overlay
        return data


def build_outcome_source_crosswalk() -> tuple[OutcomeSourceCrosswalkEntry, ...]:
    """Return the deterministic outcome/source/algorithm/stage crosswalk."""

    validate_outcome_source_crosswalk(_CROSSWALK)
    return _CROSSWALK


def build_outcome_source_crosswalk_shape() -> dict[str, object]:
    """Return a JSON-ready crosswalk shape for release artifacts and tests."""

    crosswalk = build_outcome_source_crosswalk()
    return {
        "schema_version": CATALOG_VERSION,
        "covered_deliverable_slugs": [entry.deliverable_slug for entry in crosswalk],
        "algorithm_blueprint_ids": list(ALGORITHM_BLUEPRINT_IDS),
        "accounting_csv_profile_keys": list(ACCOUNTING_CSV_PROFILE_KEYS),
        "aws_stage_ids": _known_aws_stage_ids(),
        "crosswalk": [entry.to_dict() for entry in crosswalk],
    }


def get_outcome_source_crosswalk_entry(deliverable_slug: str) -> OutcomeSourceCrosswalkEntry:
    """Return one crosswalk entry by deliverable slug."""

    for entry in build_outcome_source_crosswalk():
        if entry.deliverable_slug == deliverable_slug:
            return entry
    raise ValueError(f"unknown outcome source crosswalk slug: {deliverable_slug}")


def validate_outcome_source_crosswalk(
    crosswalk: tuple[OutcomeSourceCrosswalkEntry, ...],
) -> None:
    """Validate crosswalk references against the static catalogs it joins."""

    outcomes = {entry.deliverable_slug: entry for entry in build_outcome_catalog()}
    crosswalk_slugs = [entry.deliverable_slug for entry in crosswalk]
    _ensure_unique(crosswalk_slugs, "deliverable_slug")

    missing_slugs = sorted(set(outcomes).difference(crosswalk_slugs))
    extra_slugs = sorted(set(crosswalk_slugs).difference(outcomes))
    if missing_slugs or extra_slugs:
        raise ValueError(
            "crosswalk deliverable coverage mismatch: "
            f"missing={missing_slugs!r} extra={extra_slugs!r}"
        )

    known_categories: set[str] = {
        policy.source_category for policy in build_public_source_domain_catalog()
    }
    known_algorithms = set(ALGORITHM_BLUEPRINT_IDS)
    known_profile_keys = {profile.profile_key for profile in build_accounting_csv_profiles()}
    known_stage_ids = set(_known_aws_stage_ids())

    for entry in crosswalk:
        outcome = outcomes[entry.deliverable_slug]
        _validate_source_categories(entry, known_categories)
        _validate_public_source_family_links(entry, outcome)
        _validate_reference_set(
            entry.algorithm_blueprint_ids,
            known_algorithms,
            f"{entry.deliverable_slug} algorithm_blueprint_ids",
        )
        _validate_reference_set(
            entry.accounting_csv_profile_keys,
            known_profile_keys,
            f"{entry.deliverable_slug} accounting_csv_profile_keys",
        )
        _validate_reference_set(
            entry.aws_stage_ids,
            known_stage_ids,
            f"{entry.deliverable_slug} aws_stage_ids",
        )
        _validate_csv_profile_boundary(entry, outcome)


def _validate_source_categories(
    entry: OutcomeSourceCrosswalkEntry,
    known_categories: set[str],
) -> None:
    categories = entry.public_source_categories
    _ensure_unique(categories, f"{entry.deliverable_slug} public_source_categories")
    _validate_reference_set(
        categories,
        known_categories,
        f"{entry.deliverable_slug} public_source_categories",
    )


def _validate_public_source_family_links(
    entry: OutcomeSourceCrosswalkEntry,
    outcome: OutcomeCatalogEntry,
) -> None:
    required_source_families = {
        dependency.source_family_id
        for dependency in outcome.source_dependencies
        if dependency.dependency_type not in INTERNAL_NON_DOMAIN_DEPENDENCY_TYPES
    }
    represented_source_families = set(entry.public_source_family_ids)
    missing_source_families = sorted(
        required_source_families.difference(represented_source_families)
    )
    if missing_source_families:
        raise ValueError(
            f"{entry.deliverable_slug} missing public source family links: "
            f"{missing_source_families!r}"
        )


def _validate_csv_profile_boundary(
    entry: OutcomeSourceCrosswalkEntry,
    outcome: OutcomeCatalogEntry,
) -> None:
    if outcome.requires_user_csv and not entry.accounting_csv_profile_keys:
        raise ValueError(f"{entry.deliverable_slug} must map to accounting CSV profiles")
    if not outcome.requires_user_csv and entry.accounting_csv_profile_keys:
        raise ValueError(
            f"{entry.deliverable_slug} declares CSV profiles but outcome is public-only"
        )


def _validate_reference_set(
    references: tuple[str, ...],
    known_values: set[str],
    field_name: str,
) -> None:
    unknown = sorted(set(references).difference(known_values))
    if unknown:
        raise ValueError(f"{field_name} reference unknown values: {unknown!r}")


def _known_aws_stage_ids() -> list[str]:
    return [batch.stage_id for batch in STAGED_NON_MUTATING_BATCHES]


def _ensure_unique(values: tuple[str, ...] | list[str], field_name: str) -> None:
    duplicates = sorted({value for value in values if values.count(value) > 1})
    if duplicates:
        raise ValueError(f"{field_name} contains duplicates: {duplicates!r}")


def _dedupe(values: Iterable[Any]) -> tuple[Any, ...]:
    return tuple(dict.fromkeys(values))


def _categories(
    *links: tuple[SourceCategory, tuple[str, ...]],
) -> tuple[SourceCategoryLink, ...]:
    return tuple(
        SourceCategoryLink(source_category=category, source_family_ids=source_families)
        for category, source_families in links
    )


_CROSSWALK = (
    OutcomeSourceCrosswalkEntry(
        deliverable_slug="company-public-baseline",
        source_category_links=_categories(
            ("court_admin_guidance", ("gBizINFO", "edinet")),
            ("tax", ("nta_invoice",)),
        ),
        algorithm_blueprint_ids=(
            "evidence_join",
            "source_freshness_scoring",
            "no_hit_semantics",
        ),
        aws_stage_ids=PUBLIC_PACKET_AWS_STAGES,
    ),
    OutcomeSourceCrosswalkEntry(
        deliverable_slug="invoice-registrant-public-check",
        source_category_links=_categories(("tax", ("nta_invoice",))),
        algorithm_blueprint_ids=(
            "evidence_join",
            "source_freshness_scoring",
            "no_hit_semantics",
        ),
        aws_stage_ids=PUBLIC_PACKET_AWS_STAGES,
    ),
    OutcomeSourceCrosswalkEntry(
        deliverable_slug="subsidy-grant-candidate-pack",
        source_category_links=_categories(
            ("subsidies", ("jgrants", "sme_agency")),
            ("local_governments", ("local_government_notice",)),
        ),
        algorithm_blueprint_ids=(
            "evidence_join",
            "source_freshness_scoring",
            "subsidy_regulation_eligibility_triage_without_verdict",
            "deadline_risk_ranking",
            "no_hit_semantics",
        ),
        aws_stage_ids=DOCUMENT_HEAVY_PUBLIC_PACKET_AWS_STAGES,
    ),
    OutcomeSourceCrosswalkEntry(
        deliverable_slug="law-regulation-change-watch",
        source_category_links=_categories(
            ("laws_regulations", ("egov_law",)),
            ("court_admin_guidance", ("meti_notice", "mhlw_notice")),
        ),
        algorithm_blueprint_ids=(
            "evidence_join",
            "time_window_coverage_scoring",
            "source_freshness_scoring",
            "no_hit_semantics",
        ),
        aws_stage_ids=DOCUMENT_HEAVY_PUBLIC_PACKET_AWS_STAGES,
    ),
    OutcomeSourceCrosswalkEntry(
        deliverable_slug="local-government-permit-obligation-map",
        source_category_links=_categories(
            ("local_governments", ("local_government_notice",)),
            ("laws_regulations", ("egov_law",)),
        ),
        algorithm_blueprint_ids=(
            "evidence_join",
            "source_freshness_scoring",
            "subsidy_regulation_eligibility_triage_without_verdict",
            "no_hit_semantics",
        ),
        aws_stage_ids=DOCUMENT_HEAVY_PUBLIC_PACKET_AWS_STAGES,
    ),
    OutcomeSourceCrosswalkEntry(
        deliverable_slug="court-enforcement-citation-pack",
        source_category_links=_categories(
            (
                "court_admin_guidance",
                ("courts_jp", "meti_enforcement", "maff_enforcement"),
            ),
        ),
        algorithm_blueprint_ids=(
            "evidence_join",
            "source_freshness_scoring",
            "no_hit_semantics",
        ),
        aws_stage_ids=DOCUMENT_HEAVY_PUBLIC_PACKET_AWS_STAGES,
    ),
    OutcomeSourceCrosswalkEntry(
        deliverable_slug="public-statistics-market-context",
        source_category_links=_categories(
            ("statistics", ("estat", "prefecture_statistics")),
        ),
        algorithm_blueprint_ids=(
            "evidence_join",
            "time_window_coverage_scoring",
            "source_freshness_scoring",
            "no_hit_semantics",
        ),
        aws_stage_ids=DOCUMENT_HEAVY_PUBLIC_PACKET_AWS_STAGES,
    ),
    OutcomeSourceCrosswalkEntry(
        deliverable_slug="client-monthly-public-watchlist",
        source_category_links=_categories(
            ("court_admin_guidance", ("gBizINFO",)),
            ("tax", ("nta_invoice",)),
            ("subsidies", ("jgrants",)),
            ("laws_regulations", ("egov_law",)),
        ),
        algorithm_blueprint_ids=(
            "evidence_join",
            "source_freshness_scoring",
            "deadline_risk_ranking",
            "no_hit_semantics",
        ),
        aws_stage_ids=DOCUMENT_HEAVY_PUBLIC_PACKET_AWS_STAGES,
    ),
    OutcomeSourceCrosswalkEntry(
        deliverable_slug="accounting-csv-public-counterparty-check",
        source_category_links=_categories(
            ("tax", ("nta_invoice",)),
            ("court_admin_guidance", ("gBizINFO",)),
        ),
        algorithm_blueprint_ids=(
            "evidence_join",
            "csv_to_public_counterparty_matching",
            "source_freshness_scoring",
            "no_hit_semantics",
        ),
        aws_stage_ids=PUBLIC_PACKET_AWS_STAGES,
        accounting_csv_profile_keys=ACCOUNTING_CSV_PROFILE_KEYS,
    ),
    OutcomeSourceCrosswalkEntry(
        deliverable_slug="cashbook-csv-subsidy-fit-screen",
        source_category_links=_categories(
            ("subsidies", ("jgrants", "sme_agency")),
        ),
        algorithm_blueprint_ids=(
            "evidence_join",
            "source_freshness_scoring",
            "subsidy_regulation_eligibility_triage_without_verdict",
            "deadline_risk_ranking",
            "no_hit_semantics",
        ),
        aws_stage_ids=DOCUMENT_HEAVY_PUBLIC_PACKET_AWS_STAGES,
        accounting_csv_profile_keys=ACCOUNTING_CSV_PROFILE_KEYS,
    ),
    OutcomeSourceCrosswalkEntry(
        deliverable_slug="source-receipt-ledger",
        source_category_links=_categories(
            ("court_admin_guidance", ("gBizINFO",)),
            ("laws_regulations", ("egov_law",)),
        ),
        algorithm_blueprint_ids=(
            "evidence_join",
            "source_freshness_scoring",
            "no_hit_semantics",
        ),
        aws_stage_ids=PUBLIC_PACKET_AWS_STAGES,
    ),
    OutcomeSourceCrosswalkEntry(
        deliverable_slug="evidence-answer-citation-pack",
        source_category_links=_categories(
            ("laws_regulations", ("egov_law",)),
            ("court_admin_guidance", ("official_notice",)),
        ),
        algorithm_blueprint_ids=(
            "evidence_join",
            "source_freshness_scoring",
            "no_hit_semantics",
        ),
        aws_stage_ids=DOCUMENT_HEAVY_PUBLIC_PACKET_AWS_STAGES,
    ),
    OutcomeSourceCrosswalkEntry(
        deliverable_slug="foreign-investor-japan-public-entry-brief",
        source_category_links=_categories(
            ("court_admin_guidance", ("edinet", "meti_notice")),
            ("laws_regulations", ("egov_law",)),
        ),
        algorithm_blueprint_ids=(
            "evidence_join",
            "source_freshness_scoring",
            "no_hit_semantics",
        ),
        aws_stage_ids=DOCUMENT_HEAVY_PUBLIC_PACKET_AWS_STAGES,
    ),
    OutcomeSourceCrosswalkEntry(
        deliverable_slug="healthcare-regulatory-public-check",
        source_category_links=_categories(
            ("court_admin_guidance", ("mhlw_notice",)),
            ("laws_regulations", ("egov_law",)),
            ("local_governments", ("local_government_notice",)),
        ),
        algorithm_blueprint_ids=(
            "evidence_join",
            "source_freshness_scoring",
            "subsidy_regulation_eligibility_triage_without_verdict",
            "no_hit_semantics",
        ),
        aws_stage_ids=DOCUMENT_HEAVY_PUBLIC_PACKET_AWS_STAGES,
    ),
)
