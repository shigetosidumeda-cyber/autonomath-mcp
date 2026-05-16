"""Deterministic policy/trust catalog for the agent runtime.

This module is intentionally local-only: no AWS, network, database, or request
time inspection. It classifies public-source, blocked-terms, private CSV overlay,
and no-hit caveat states before any public artifact compilation.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from typing import Literal

from jpintel_mcp.agent_runtime.contracts import PolicyDecision, PolicyState

NO_HIT_CAVEAT: Literal["no_hit_not_absence"] = "no_hit_not_absence"
PUBLIC_COMPILE_SURFACES = ("public_packet", "agent_answer", "source_receipt_ledger")
PRIVATE_BLOCKED_SURFACES = PUBLIC_COMPILE_SURFACES + ("source_receipt",)
CATALOG_VERSION = "jpcite.policy_catalog.p0.v1"


@dataclass(frozen=True)
class PrivateCsvOverlaySummary:
    """Metadata-only summary of a tenant CSV overlay."""

    provider_family: Literal["freee", "money_forward", "yayoi", "tkc", "unknown"]
    row_count_bucket: str
    column_fingerprint_hash: str
    raw_csv_retained: bool = False
    raw_csv_logged: bool = False
    raw_csv_sent_to_aws: bool = False
    public_surface_export_allowed: bool = False
    source_receipt_compatible: bool = False

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class PolicyCatalogEntry:
    """Single policy state with public-compilation guardrails."""

    catalog_key: str
    display_name: str
    policy_state: PolicyState
    source_terms_contract_id: str
    administrative_info_class: str
    privacy_taint_level: Literal["none", "low", "medium", "high", "tenant_private"]
    allowed_surfaces: tuple[str, ...]
    blocked_surfaces: tuple[str, ...]
    blocked_reason_codes: tuple[str, ...]
    public_compile_allowed: bool
    no_hit_semantics: Literal["no_hit_not_absence"] = NO_HIT_CAVEAT
    absence_claim_enabled: bool = False
    private_csv_overlay: PrivateCsvOverlaySummary | None = None

    def __post_init__(self) -> None:
        is_blocked = self.policy_state.startswith("blocked_") or self.policy_state in {
            "quarantine",
            "deny",
        }
        is_private = self.privacy_taint_level == "tenant_private" or self.private_csv_overlay

        if is_blocked and self.public_compile_allowed:
            raise ValueError("blocked policy states cannot compile to public surfaces")
        if is_private and self.public_compile_allowed:
            raise ValueError("private policy states cannot compile to public surfaces")
        if self.absence_claim_enabled:
            raise ValueError("no-hit entries cannot enable absence claims")

    def to_policy_decision(self) -> PolicyDecision:
        """Return the runtime contract model for this catalog entry."""

        return PolicyDecision(
            policy_decision_id=f"{CATALOG_VERSION}:{self.catalog_key}",
            policy_state=self.policy_state,
            source_terms_contract_id=self.source_terms_contract_id,
            administrative_info_class=self.administrative_info_class,
            privacy_taint_level=self.privacy_taint_level,
            allowed_surfaces=self.allowed_surfaces,
            blocked_surfaces=self.blocked_surfaces,
            blocked_reason_codes=self.blocked_reason_codes,
            public_compile_allowed=self.public_compile_allowed,
        )

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["policy_decision"] = self.to_policy_decision().model_dump(mode="json")
        return data


def summarize_private_csv_overlay_shape(
    headers: tuple[str, ...],
    row_count: int,
    *,
    provider_family: Literal["freee", "money_forward", "yayoi", "tkc", "unknown"] = "unknown",
) -> PrivateCsvOverlaySummary:
    """Summarize CSV shape metadata without receiving raw CSV rows."""

    normalized_headers = "\n".join(header.strip().lower() for header in headers)
    fingerprint = hashlib.sha256(normalized_headers.encode("utf-8")).hexdigest()

    return PrivateCsvOverlaySummary(
        provider_family=provider_family,
        row_count_bucket=_row_count_bucket(row_count),
        column_fingerprint_hash=f"sha256:{fingerprint}",
    )


def build_policy_catalog(
    *,
    private_csv_overlay_headers: tuple[str, ...] | None = None,
    private_csv_overlay_row_count: int = 0,
    private_csv_provider_family: Literal[
        "freee", "money_forward", "yayoi", "tkc", "unknown"
    ] = "unknown",
) -> tuple[PolicyCatalogEntry, ...]:
    """Build the deterministic policy/trust catalog in stable key order."""

    private_summary = (
        summarize_private_csv_overlay_shape(
            private_csv_overlay_headers,
            private_csv_overlay_row_count,
            provider_family=private_csv_provider_family,
        )
        if private_csv_overlay_headers is not None
        else None
    )

    return (
        PolicyCatalogEntry(
            catalog_key="public_source_allow",
            display_name="Public source with known terms",
            policy_state="allow",
            source_terms_contract_id="public-source-known-terms",
            administrative_info_class="public_web",
            privacy_taint_level="none",
            allowed_surfaces=PUBLIC_COMPILE_SURFACES,
            blocked_surfaces=(),
            blocked_reason_codes=(),
            public_compile_allowed=True,
        ),
        PolicyCatalogEntry(
            catalog_key="public_source_blocked_terms_unknown",
            display_name="Public source blocked until terms are known",
            policy_state="blocked_terms_unknown",
            source_terms_contract_id="public-source-terms-unknown",
            administrative_info_class="public_web",
            privacy_taint_level="none",
            allowed_surfaces=(),
            blocked_surfaces=PUBLIC_COMPILE_SURFACES,
            blocked_reason_codes=("terms_unknown",),
            public_compile_allowed=False,
        ),
        PolicyCatalogEntry(
            catalog_key="private_csv_overlay",
            display_name="Private CSV overlay metadata only",
            policy_state="allow_internal_only",
            source_terms_contract_id="tenant-private-csv-overlay",
            administrative_info_class="tenant_private_csv",
            privacy_taint_level="tenant_private",
            allowed_surfaces=("tenant_private_summary", "redacted_internal_check"),
            blocked_surfaces=PRIVATE_BLOCKED_SURFACES,
            blocked_reason_codes=("tenant_private", "not_source_receipt_compatible"),
            public_compile_allowed=False,
            private_csv_overlay=private_summary,
        ),
        PolicyCatalogEntry(
            catalog_key="no_hit_caveat",
            display_name="No-hit caveat, not an absence claim",
            policy_state="gap_artifact_only",
            source_terms_contract_id="public-source-known-terms",
            administrative_info_class="public_web",
            privacy_taint_level="none",
            allowed_surfaces=("known_gap", "agent_answer_caveat"),
            blocked_surfaces=("absence_claim",),
            blocked_reason_codes=("no_hit_not_absence",),
            public_compile_allowed=True,
        ),
    )


def compile_public_policy_catalog(
    catalog: tuple[PolicyCatalogEntry, ...] | None = None,
) -> tuple[PolicyDecision, ...]:
    """Return only entries allowed to compile to public surfaces."""

    entries = catalog if catalog is not None else build_policy_catalog()
    _validate_public_compile_guards(entries)
    return tuple(entry.to_policy_decision() for entry in entries if entry.public_compile_allowed)


def build_policy_catalog_shape(
    *,
    private_csv_overlay_headers: tuple[str, ...] | None = None,
    private_csv_overlay_row_count: int = 0,
    private_csv_provider_family: Literal[
        "freee", "money_forward", "yayoi", "tkc", "unknown"
    ] = "unknown",
) -> dict[str, object]:
    """Return a JSON-ready catalog shape for release artifacts and tests."""

    catalog = build_policy_catalog(
        private_csv_overlay_headers=private_csv_overlay_headers,
        private_csv_overlay_row_count=private_csv_overlay_row_count,
        private_csv_provider_family=private_csv_provider_family,
    )
    public_decisions = compile_public_policy_catalog(catalog)
    return {
        "schema_version": CATALOG_VERSION,
        "no_hit_caveat": NO_HIT_CAVEAT,
        "absence_claim_enabled": False,
        "catalog": [entry.to_dict() for entry in catalog],
        "public_compile_decisions": [
            decision.model_dump(mode="json") for decision in public_decisions
        ],
    }


def _validate_public_compile_guards(entries: tuple[PolicyCatalogEntry, ...]) -> None:
    for entry in entries:
        if not entry.public_compile_allowed:
            continue
        if entry.policy_state.startswith("blocked_") or entry.policy_state in {
            "quarantine",
            "deny",
        }:
            raise ValueError(f"{entry.catalog_key} is blocked but public compile is enabled")
        if entry.privacy_taint_level == "tenant_private" or entry.private_csv_overlay:
            raise ValueError(f"{entry.catalog_key} is private but public compile is enabled")


def _row_count_bucket(row_count: int) -> str:
    if row_count == 0:
        return "0"
    if row_count <= 99:
        return "1-99"
    if row_count <= 999:
        return "100-999"
    return "1000+"
