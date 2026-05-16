"""Catalog-driven routing helpers for the P0 jpcite facade.

The REST and MCP facades must choose, preview, and describe the same
deliverables. Keep this module pure: no network, database, AWS, billing
provider, clock, or request-time LLM dependency.
"""

from __future__ import annotations

from typing import Any

from jpintel_mcp.agent_runtime.outcome_catalog import (
    OutcomeCatalogEntry,
    build_outcome_catalog,
)
from jpintel_mcp.agent_runtime.pricing_policy import (
    build_execute_input_hash,
    cap_passes,
    normalize_price_cap,
    price_for_pricing_posture,
)

DEFAULT_OUTCOME_CONTRACT_ID = "evidence_answer"

INPUT_KIND_ROUTE_TERMS: dict[str, tuple[str, ...]] = {
    "company": ("company_public_baseline", "company_registry", "corporate_identity"),
    "corporate": ("company_public_baseline", "company_registry", "corporate_identity"),
    "houjin": ("company_public_baseline", "company_registry", "corporate_identity"),
    "court": ("court_enforcement", "official_court_record"),
    "csv": ("tax_accounting_csv_overlay", "tenant_private_csv_overlay"),
    "csv_counterparty": (
        "tax_accounting_csv_overlay",
        "invoice_registry",
        "company_registry",
    ),
    "csv_overlay": ("tax_accounting_csv_overlay", "tenant_private_csv_overlay"),
    "csv_subsidy": (
        "tax_accounting_csv_overlay",
        "subsidy_grants",
        "application_strategy",
    ),
    "evidence": ("evidence_answer", "citation_pack"),
    "foreign_investor": ("foreign_investor", "foreign_investment"),
    "healthcare": ("healthcare_regulation", "healthcare_operator"),
    "invoice": ("invoice_registry", "tax_compliance"),
    "local_government": ("local_government", "permits"),
    "monthly_review": ("monthly_review",),
    "regulation": ("law_regulation", "change_watch"),
    "regulation_watch": ("change_watch", "public_comment"),
    "source_receipt": ("source_receipt_ledger", "source_receipts", "claim_graph"),
    "source_receipts": ("source_receipt_ledger", "source_receipts", "claim_graph"),
    "statistics": ("public_statistics", "market_context"),
    "subsidy": ("subsidy_grants", "application_strategy"),
    "会計": ("tax_accounting_csv_overlay", "tenant_private_csv_overlay"),
    "会社": ("company_public_baseline", "company_registry", "corporate_identity"),
    "規制": ("law_regulation", "change_watch"),
    "許認可": ("local_government", "permits"),
    "裁判": ("court_enforcement", "official_court_record"),
    "自治体": ("local_government", "permits"),
    "助成金": ("subsidy_grants", "application_strategy"),
    "統計": ("public_statistics", "market_context"),
    "補助金": ("subsidy_grants", "application_strategy"),
    "法人": ("company_public_baseline", "company_registry", "corporate_identity"),
    "法令": ("law_regulation", "change_watch"),
    "医療": ("healthcare_regulation", "healthcare_operator"),
    "適格請求書": ("invoice_registry", "tax_compliance"),
}

QUERY_ROUTE_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("cashbook", ("tax_accounting_csv_overlay", "subsidy_grants")),
    ("counterparty", ("company_public_baseline", "company_registry", "invoice_registry")),
    ("csv", ("tax_accounting_csv_overlay", "tenant_private_csv_overlay")),
    ("jgrants", ("subsidy_grants", "application_strategy")),
    ("grant", ("subsidy_grants", "application_strategy")),
    ("subsidy", ("subsidy_grants", "application_strategy")),
    ("invoice", ("invoice_registrant_public_check", "invoice_registry", "tax_compliance")),
    ("corporate", ("company_public_baseline", "company_registry")),
    ("company", ("company_public_baseline", "company_registry")),
    ("houjin", ("company_public_baseline", "company_registry")),
    ("regulation", ("law_regulation", "change_watch")),
    ("law", ("law_regulation", "change_watch")),
    ("permit", ("local_government", "permits")),
    ("local government", ("local_government", "permits")),
    ("court", ("court_enforcement", "official_court_record")),
    ("statistics", ("public_statistics", "market_context")),
    ("market", ("public_statistics", "market_context")),
    ("healthcare", ("healthcare_regulation", "healthcare_operator")),
    ("foreign investor", ("foreign_investor", "foreign_investment")),
    ("monthly", ("monthly_review",)),
    ("source receipt", ("source_receipt_ledger", "source_receipts", "claim_graph")),
    ("会計", ("tax_accounting_csv_overlay", "tenant_private_csv_overlay")),
    ("仕訳", ("tax_accounting_csv_overlay", "tenant_private_csv_overlay")),
    ("取引先", ("company_registry",)),
    ("補助金", ("subsidy_grants", "application_strategy")),
    ("助成金", ("subsidy_grants", "application_strategy")),
    ("インボイス", ("invoice_registrant_public_check", "invoice_registry", "tax_compliance")),
    ("適格請求書", ("invoice_registrant_public_check", "invoice_registry", "tax_compliance")),
    ("法人", ("company_public_baseline", "company_registry")),
    ("会社", ("company_public_baseline", "company_registry")),
    ("法令", ("law_regulation", "change_watch")),
    ("規制", ("law_regulation", "change_watch")),
    ("許認可", ("local_government", "permits")),
    ("自治体", ("local_government", "permits")),
    ("裁判", ("court_enforcement", "official_court_record")),
    ("統計", ("public_statistics", "market_context")),
    ("市場", ("public_statistics", "market_context")),
    ("医療", ("healthcare_regulation", "healthcare_operator")),
    ("海外投資家", ("foreign_investor", "foreign_investment")),
    ("外国投資家", ("foreign_investor", "foreign_investment")),
    ("月次", ("monthly_review",)),
    ("source_receipt", ("source_receipt_ledger", "source_receipts", "claim_graph")),
    ("出典", ("source_receipt_ledger", "source_receipts", "claim_graph")),
)


def catalog_by_outcome_contract_id() -> dict[str, OutcomeCatalogEntry]:
    """Return the outcome catalog keyed by stable contract id."""

    return {entry.outcome_contract_id: entry for entry in build_outcome_catalog()}


def catalog_by_deliverable_slug() -> dict[str, OutcomeCatalogEntry]:
    """Return the outcome catalog keyed by public deliverable slug."""

    return {entry.deliverable_slug: entry for entry in build_outcome_catalog()}


def outcome_contract_ids() -> tuple[str, ...]:
    """Return stable outcome contract ids in catalog order."""

    return tuple(entry.outcome_contract_id for entry in build_outcome_catalog())


def normalize_route_token(value: str) -> str:
    """Normalize user/API routing hints for deterministic matching."""

    return "_".join(value.strip().lower().replace("-", "_").split())


def entry_route_values(entry: OutcomeCatalogEntry) -> set[str]:
    """Return normalized searchable tokens for one outcome entry."""

    values = {
        entry.deliverable_slug,
        entry.display_name,
        entry.outcome_contract_id,
        entry.input_requirement,
        entry.pricing_posture,
        entry.billing_posture,
        *entry.user_segments,
        *entry.use_case_tags,
        *entry.evidence_dependency_types,
    }
    for dependency in entry.source_dependencies:
        values.update(
            {
                dependency.dependency_type,
                dependency.source_family_id,
                dependency.source_role,
            }
        )
    return {normalize_route_token(value) for value in values if value}


def route_score(entry: OutcomeCatalogEntry, terms: tuple[str, ...], input_kind: str) -> int:
    """Score a catalog entry for a routing request."""

    route_values = entry_route_values(entry)
    score = 0
    for term in terms:
        normalized_term = normalize_route_token(term)
        if not normalized_term:
            continue
        if normalized_term in route_values:
            score += 4
        elif any(normalized_term in value for value in route_values):
            score += 1

    normalized_input_kind = normalize_route_token(input_kind)
    if "csv" in normalized_input_kind:
        score += 2 if entry.requires_user_csv else -1
    elif entry.requires_user_csv:
        score -= 1
    return score


def resolve_outcome_entry(
    *,
    input_kind: str | None = None,
    query: str | None = None,
    outcome_contract_id: str | None = None,
    strict_outcome_contract_id: bool = False,
) -> OutcomeCatalogEntry | None:
    """Resolve a routing request to a catalog entry.

    ``outcome_contract_id`` also accepts a public deliverable slug so agents can
    use whichever id they discovered from the public catalog. In strict mode,
    an unknown non-empty id fails closed instead of falling back.
    """

    candidate = (outcome_contract_id or "").strip()
    by_contract_id = catalog_by_outcome_contract_id()
    by_slug = catalog_by_deliverable_slug()

    if candidate in by_contract_id:
        return by_contract_id[candidate]
    if candidate in by_slug:
        return by_slug[candidate]
    if candidate and strict_outcome_contract_id:
        return None

    route_input = input_kind or query or "evidence"
    normalized_kind = normalize_route_token(route_input)
    terms = INPUT_KIND_ROUTE_TERMS.get(normalized_kind)
    if terms is None:
        route_text = f"{route_input} {query or ''}".strip().lower()
        keyword_terms: list[str] = []
        for keyword, mapped_terms in QUERY_ROUTE_KEYWORDS:
            if keyword.lower() in route_text:
                keyword_terms.extend(mapped_terms)
        terms = tuple(
            token
            for token in (
                *keyword_terms,
                *normalize_route_token(route_input).split("_"),
                *normalize_route_token(query or "").split("_"),
            )
            if token
        )

    best_score = 0
    best_entry = by_contract_id[DEFAULT_OUTCOME_CONTRACT_ID]
    for entry in build_outcome_catalog():
        score = route_score(entry, terms, normalized_kind)
        if score > best_score:
            best_score = score
            best_entry = entry
    return best_entry


def packet_ids_for_entry(entry: OutcomeCatalogEntry) -> tuple[str, ...]:
    """Return preview packet ids for an outcome entry."""

    packet_ids = [entry.deliverable_slug, "source_receipts", "known_gaps"]
    if entry.requires_user_csv:
        packet_ids.insert(1, "redacted_csv_overlay")
    return tuple(packet_ids)


def outcome_metadata_for_entry(
    entry: OutcomeCatalogEntry,
    *,
    max_price_jpy: int | None = None,
) -> dict[str, Any]:
    """Return JSON-ready metadata shared by REST and MCP facade responses."""

    estimated_price_jpy = price_for_pricing_posture(entry.pricing_posture)
    if estimated_price_jpy is None:
        raise ValueError(f"unknown pricing posture: {entry.pricing_posture}")
    return {
        "catalog_count": len(build_outcome_catalog()),
        "deliverable_slug": entry.deliverable_slug,
        "display_name": entry.display_name,
        "outcome_contract_id": entry.outcome_contract_id,
        "packet_ids": packet_ids_for_entry(entry),
        "pricing_posture": entry.pricing_posture,
        "billing_posture": entry.billing_posture,
        "input_requirement": entry.input_requirement,
        "estimated_price_jpy": estimated_price_jpy,
        "max_price_jpy": normalize_price_cap(max_price_jpy),
        "cap_passed": cap_passes(estimated_price_jpy, max_price_jpy),
        "execute_input_hash": build_execute_input_hash(
            entry.outcome_contract_id,
            max_price_jpy,
        ),
        "requires_user_csv": entry.requires_user_csv,
        "cached_official_public_sources_sufficient": (
            entry.cached_official_public_sources_sufficient
        ),
        "evidence_dependency_types": list(entry.evidence_dependency_types),
    }


def preview_for_outcome(
    outcome_contract_id: str,
    max_price_jpy: int | None = None,
) -> dict[str, Any]:
    """Return the shared deterministic free preview for one outcome id."""

    input_hash = build_execute_input_hash(outcome_contract_id, max_price_jpy)
    entry = catalog_by_outcome_contract_id().get(outcome_contract_id)
    if entry is None:
        return {
            "schema_version": "jpcite.p0.preview_cost.v1",
            "status": "blocked_unknown_outcome_contract",
            "billable": False,
            "charge_status": "not_charged",
            "outcome_contract_id": outcome_contract_id,
            "execute_input_hash": input_hash,
            "available_outcome_contract_ids": outcome_contract_ids(),
            "known_gaps": ("unknown_outcome_contract",),
            "no_hit_caveat": "no_hit_not_absence",
        }

    metadata = outcome_metadata_for_entry(entry, max_price_jpy=max_price_jpy)
    return {
        "schema_version": "jpcite.p0.preview_cost.v1",
        "status": "preview_ready" if metadata["cap_passed"] else "blocked_price_cap",
        "billable": False,
        "charge_status": "not_charged",
        "outcome_contract_id": metadata["outcome_contract_id"],
        "execute_input_hash": metadata["execute_input_hash"],
        "deliverable_slug": metadata["deliverable_slug"],
        "display_name": metadata["display_name"],
        "packet_ids": metadata["packet_ids"],
        "pricing_posture": metadata["pricing_posture"],
        "billing_posture": metadata["billing_posture"],
        "input_requirement": metadata["input_requirement"],
        "requires_user_csv": metadata["requires_user_csv"],
        "cached_official_public_sources_sufficient": (
            metadata["cached_official_public_sources_sufficient"]
        ),
        "evidence_dependency_types": tuple(metadata["evidence_dependency_types"]),
        "estimated_price_jpy": metadata["estimated_price_jpy"],
        "max_price_jpy": metadata["max_price_jpy"],
        "cap_passed": metadata["cap_passed"],
        "requires_user_consent": metadata["estimated_price_jpy"] > 0,
        "requires_scoped_cap_token": metadata["estimated_price_jpy"] > 0,
        "expected_charge_basis": "accepted_artifact",
        "accepted_artifact_required_for_charge": True,
        "no_hit_charge_requires_explicit_consent": True,
        "known_gaps": ("source_freshness_not_live_until_capsule_activation",),
        "no_hit_caveat": "no_hit_not_absence",
    }


__all__ = [
    "DEFAULT_OUTCOME_CONTRACT_ID",
    "INPUT_KIND_ROUTE_TERMS",
    "QUERY_ROUTE_KEYWORDS",
    "catalog_by_deliverable_slug",
    "catalog_by_outcome_contract_id",
    "entry_route_values",
    "normalize_route_token",
    "outcome_contract_ids",
    "outcome_metadata_for_entry",
    "packet_ids_for_entry",
    "preview_for_outcome",
    "resolve_outcome_entry",
    "route_score",
]
