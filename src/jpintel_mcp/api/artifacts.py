"""Customer-facing deterministic artifacts.

These endpoints wrap existing rule engines into copy-paste-ready artifacts.
They do not call an LLM and they do not change the underlying legacy endpoint
response contracts.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
from collections import Counter
from datetime import UTC, datetime
from typing import Any, cast

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from jpintel_mcp.api._corpus_snapshot import attach_corpus_snapshot
from jpintel_mcp.api.deps import ApiContextDep, DbDep, log_usage
from jpintel_mcp.api.funding_stack import FundingStackCheckRequest, _get_checker
from jpintel_mcp.api.intel_houjin_full import (
    _build_houjin_full,
    _is_empty_response,
    _normalize_houjin,
    _open_autonomath_ro,
    _parse_include_sections,
)
from jpintel_mcp.api.prescreen import PrescreenRequest, PrescreenResponse, run_prescreen
from jpintel_mcp.api.vocab import _normalize_industry_jsic, _normalize_prefecture

logger = logging.getLogger("jpintel.api.artifacts")

router = APIRouter(prefix="/v1/artifacts", tags=["artifacts"])


def _utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


class HoujinDdPackRequest(BaseModel):
    """Input for a deterministic corporate DD artifact."""

    houjin_bangou: str = Field(
        min_length=13,
        max_length=14,
        description="13-digit 法人番号. A leading T prefix is accepted and normalized.",
    )
    include_sections: list[str] | None = Field(
        default=None,
        description=(
            "Optional section names from houjin/full. Default returns meta, "
            "adoption_history, enforcement, invoice_status, peer_summary, "
            "jurisdiction, and watch_status."
        ),
    )
    max_per_section: int = Field(
        default=10,
        ge=1,
        le=50,
        description="Maximum rows per list-shaped section.",
    )


class CompanyPublicArtifactRequest(BaseModel):
    """Input for deterministic public company artifacts."""

    houjin_bangou: str = Field(
        min_length=13,
        max_length=14,
        description="13-digit 法人番号. A leading T prefix is accepted and normalized.",
    )
    include_sections: list[str] | None = Field(
        default=None,
        description=(
            "Optional section names from houjin/full. Default returns meta, "
            "adoption_history, enforcement, invoice_status, peer_summary, "
            "jurisdiction, and watch_status."
        ),
    )
    max_per_section: int = Field(
        default=10,
        ge=1,
        le=50,
        description="Maximum rows per list-shaped section.",
    )


class ApplicationStrategyPackRequest(BaseModel):
    """Input for a deterministic public-support application strategy artifact."""

    profile: PrescreenRequest = Field(
        default_factory=PrescreenRequest,
        description="Business profile used to rank public-support programs.",
    )
    max_candidates: int = Field(
        default=5,
        ge=1,
        le=10,
        description="Number of ranked candidate programs to include.",
    )
    compatibility_top_n: int = Field(
        default=5,
        ge=0,
        le=5,
        description=(
            "Top-N candidates to pass through the compatibility rule engine. "
            "0 disables the pairwise compatibility section."
        ),
    )


class ArtifactSourceReceipt(BaseModel):
    """Source receipt contract shared by deterministic artifacts."""

    model_config = ConfigDict(extra="allow")

    source_receipt_id: str | None = None
    source_url: str | None = None
    source_kind: str | None = None
    used_in: list[str] = Field(default_factory=list)
    source_fetched_at: str | None = None
    content_hash: str | None = None
    license: str | None = None


class ArtifactEvidence(BaseModel):
    """Machine-readable evidence coverage summary for artifact consumers."""

    model_config = ConfigDict(extra="allow")

    source_count: int | None = None
    source_refs: list[dict[str, Any]] = Field(default_factory=list)
    known_gap_count: int | None = None
    known_gap_refs: list[str] = Field(default_factory=list)
    claim_coverage: dict[str, int] = Field(default_factory=dict)
    source_receipt_completion: dict[str, Any] = Field(default_factory=dict)
    recommended_followup_count: int | None = None
    basis_fields: list[str] = Field(default_factory=list)


class ArtifactKnownGap(BaseModel):
    """Structured gap record that agents can route to follow-up work."""

    model_config = ConfigDict(extra="allow")

    gap_id: str | None = None
    severity: str = "review"
    message: str | None = None
    message_ja: str | None = None
    section: str | None = None
    source_fields: list[str] = Field(default_factory=list)


class ArtifactBillingAuditSeal(BaseModel):
    """Audit-seal status for billing metadata."""

    model_config = ConfigDict(extra="allow")

    authenticated_key_present: bool | None = None
    requested_for_metered_key: bool | None = None
    included_when_available: bool | None = None
    billing_metadata_covered_by_response_hash: bool | None = None
    seal_field_excluded_from_response_hash: bool | None = None


class ArtifactBillingMetadata(BaseModel):
    """Metering contract exposed in artifact responses."""

    model_config = ConfigDict(extra="allow")

    endpoint: str | None = None
    unit_type: str | None = None
    quantity: int | None = None
    result_count: int | None = None
    pair_count: int | None = None
    metered: bool | None = None
    strict_metering: bool | None = None
    pricing_note: str | None = None
    value_basis: list[str] = Field(default_factory=list)
    audit_seal: ArtifactBillingAuditSeal | None = None


class ArtifactRecommendedFollowupChannels(BaseModel):
    """Recommended next-step routing split by channel."""

    model_config = ConfigDict(extra="allow")

    use_jpcite_next: list[dict[str, Any]] = Field(default_factory=list)
    use_web_search_for: list[dict[str, Any]] = Field(default_factory=list)
    use_professional_review_for: list[dict[str, Any]] = Field(default_factory=list)


class ArtifactAgentRouting(BaseModel):
    """Agent guidance for when to use jpcite before broader research."""

    model_config = ConfigDict(extra="allow")

    call_jpcite_first_for: list[str] = Field(default_factory=list)
    use_web_search_after: list[str] = Field(default_factory=list)
    preserve_fields: list[str] = Field(default_factory=list)
    no_llm_called_by_jpcite: bool | None = None
    pricing_note: str | None = None


class ArtifactAuditSeal(BaseModel):
    """Customer-facing audit seal envelope for paid artifact responses."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    seal_id: str | None = None
    issued_at: str | None = None
    subject_hash: str | None = None
    key_hash_prefix: str | None = None
    corpus_snapshot_id: str | None = None
    verify_endpoint: str | None = None
    disclaimer: str | None = Field(default=None, alias="_disclaimer")
    call_id: str | None = None
    ts: str | None = None
    endpoint: str | None = None
    query_hash: str | None = None
    response_hash: str | None = None
    source_urls: list[str] = Field(default_factory=list)
    alg: str | None = None
    key_version: int | None = None
    hmac: str | None = None
    client_tag: str | None = None


class ArtifactResponse(BaseModel):
    """Stable public response contract for all deterministic artifact packs."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    artifact_id: str | None = None
    artifact_type: str | None = None
    artifact_version: str | None = None
    schema_version: str | None = None
    endpoint: str | None = None
    generated_at: str | None = None
    packet_id: str | None = None
    corpus_snapshot_id: str | None = None
    corpus_checksum: str | None = None
    summary: dict[str, Any] = Field(default_factory=dict)
    sections: list[dict[str, Any]] = Field(default_factory=list)
    sources: list[dict[str, Any]] = Field(default_factory=list)
    known_gaps: list[ArtifactKnownGap] = Field(default_factory=list)
    source_receipts: list[ArtifactSourceReceipt] = Field(default_factory=list)
    evidence: ArtifactEvidence | None = Field(default=None, alias="_evidence")
    billing_note: str | None = None
    billing_metadata: ArtifactBillingMetadata | None = None
    human_review_required: list[Any] = Field(default_factory=list)
    copy_paste_parts: list[dict[str, Any]] = Field(default_factory=list)
    recommended_followup: list[dict[str, Any]] = Field(default_factory=list)
    recommended_followup_by_channel: ArtifactRecommendedFollowupChannels | None = None
    agent_routing: ArtifactAgentRouting | None = None
    next_actions: list[dict[str, Any]] = Field(default_factory=list)
    disclaimer: str | None = Field(default=None, alias="_disclaimer")
    audit_seal: ArtifactAuditSeal | None = None
    seal_unavailable: bool | None = Field(default=None, alias="_seal_unavailable")
    markdown_display: str | None = None


def _stable_artifact_id(artifact_type: str, payload: dict[str, Any]) -> str:
    digest = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()[:16]
    return f"art_{artifact_type}_{digest}"


def _refresh_artifact_id(body: dict[str, Any]) -> None:
    """Bind artifact_id to the final artifact body, including corpus snapshot.

    Audit and cache consumers use artifact_id as a content identity. Exclude
    fields that are either the identity itself or paid-response-only seals.
    """
    artifact_type = str(body.get("artifact_type") or "artifact")
    material = {
        key: value
        for key, value in body.items()
        if key not in {"artifact_id", "audit_seal", "billing_metadata", "packet_id"}
    }
    body["artifact_id"] = _stable_artifact_id(artifact_type, material)


def _artifact_packet_id(body: dict[str, Any]) -> str:
    artifact_id = str(body.get("artifact_id") or "")
    if artifact_id.startswith("art_"):
        return f"pkt_{artifact_id[4:]}"
    artifact_type = str(body.get("artifact_type") or "artifact")
    return _stable_artifact_id(artifact_type, body).replace("art_", "pkt_", 1)


def _source_refs(body: dict[str, Any]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for source in body.get("sources") or []:
        if not isinstance(source, dict):
            continue
        source_url = source.get("source_url")
        if not isinstance(source_url, str) or not source_url:
            continue
        refs.append(
            {
                "source_url": source_url,
                "source_kind": source.get("source_kind") or source.get("kind"),
                "used_in": source.get("used_in") or [],
            }
        )
    return refs


_AUDIT_SOURCE_RECEIPT_REQUIRED_FIELDS = (
    "source_url",
    "source_fetched_at",
    "content_hash",
    "license",
    "used_in",
)
_SOURCE_RECEIPT_QUALITY_ARTIFACTS = {
    "application_strategy_pack",
    "compatibility_table",
    "company_public_baseline",
    "company_folder_brief",
    "company_public_audit_pack",
    "houjin_dd_pack",
}

_ARTIFACT_BILLING_NOTE = (
    "metered billable units; compatibility_table bills per pair, "
    "other artifact endpoints bill one unit per successful call"
)


def _build_billing_metadata(
    body: dict[str, Any],
    *,
    endpoint: str,
    unit_type: str,
    quantity: int,
    result_count: int,
    strict_metering: bool,
    metered: bool,
    authenticated: bool,
    pair_count: int | None = None,
) -> dict[str, Any]:
    """Expose the same metering basis as usage_events without leaking account data."""
    value_basis = [
        "deterministic_artifact",
        "source_linked_evidence",
        "corpus_snapshot",
        "no_llm_called_by_jpcite",
    ]
    if body.get("source_receipts"):
        value_basis.append("source_receipts")
    if authenticated:
        value_basis.append("authenticated_response_audit_seal")
    if metered:
        value_basis.append("metered_response_audit_seal")
    metadata: dict[str, Any] = {
        "endpoint": endpoint,
        "unit_type": unit_type,
        "quantity": int(quantity),
        "result_count": int(result_count),
        "metered": bool(metered),
        "strict_metering": bool(strict_metering),
        "pricing_note": _ARTIFACT_BILLING_NOTE,
        "value_basis": value_basis,
        "audit_seal": {
            "authenticated_key_present": bool(authenticated),
            "requested_for_metered_key": bool(metered),
            "included_when_available": bool(authenticated),
            "billing_metadata_covered_by_response_hash": bool(authenticated),
            "seal_field_excluded_from_response_hash": bool(authenticated),
        },
    }
    if pair_count is not None:
        metadata["pair_count"] = int(pair_count)
    return metadata


def _attach_billing_metadata(
    body: dict[str, Any],
    *,
    endpoint: str,
    unit_type: str,
    quantity: int,
    result_count: int,
    strict_metering: bool = True,
    metered: bool = False,
    authenticated: bool = False,
    pair_count: int | None = None,
) -> None:
    body["billing_metadata"] = _build_billing_metadata(
        body,
        endpoint=endpoint,
        unit_type=unit_type,
        quantity=quantity,
        result_count=result_count,
        strict_metering=strict_metering,
        metered=metered,
        authenticated=authenticated,
        pair_count=pair_count,
    )


def _mark_billing_metadata_seal_unavailable(body: dict[str, Any]) -> None:
    metadata = body.get("billing_metadata")
    if not isinstance(metadata, dict):
        return
    audit = metadata.get("audit_seal")
    if not isinstance(audit, dict):
        return
    audit["seal_unavailable"] = True
    audit["included_when_available"] = False
    audit["billing_metadata_covered_by_response_hash"] = False
    audit["seal_field_excluded_from_response_hash"] = False
    value_basis = metadata.get("value_basis")
    if isinstance(value_basis, list):
        metadata["value_basis"] = [
            item
            for item in value_basis
            if item not in {"authenticated_response_audit_seal", "metered_response_audit_seal"}
        ]


def _finalize_artifact_usage_and_seal(
    body: dict[str, Any],
    *,
    conn: Any,
    ctx: Any,
    endpoint: str,
    params: dict[str, Any],
    quantity: int,
    result_count: int,
) -> None:
    audit_seal = log_usage(
        conn,
        ctx,
        endpoint,
        params=params,
        quantity=quantity,
        result_count=result_count,
        response_body=body,
        issue_audit_seal=ctx.key_hash is not None,
        strict_metering=True,
        strict_audit_seal=True,
    )
    if ctx.key_hash is None:
        return
    if audit_seal is not None:
        body["audit_seal"] = audit_seal
        return
    body["_seal_unavailable"] = True
    _mark_billing_metadata_seal_unavailable(body)


def _source_receipts(body: dict[str, Any]) -> list[dict[str, Any]]:
    receipts: list[dict[str, Any]] = []
    for source in body.get("sources") or []:
        if not isinstance(source, dict):
            continue
        source_url = source.get("source_url")
        if not isinstance(source_url, str) or not source_url:
            continue
        digest = hashlib.sha256(source_url.encode("utf-8")).hexdigest()[:12]
        receipts.append(
            {
                "source_receipt_id": f"sr_{digest}",
                "source_url": source_url,
                "source_kind": source.get("source_kind") or source.get("kind"),
                "used_in": source.get("used_in") or [],
                "source_fetched_at": (
                    source.get("source_fetched_at")
                    or source.get("fetched_at")
                    or source.get("last_verified_at")
                ),
                "content_hash": source.get("content_hash") or source.get("source_checksum"),
                "license": source.get("license") or source.get("license_or_terms"),
            }
        )
    return receipts


def _receipt_field_has_value(receipt: dict[str, Any], field: str) -> bool:
    value = receipt.get(field)
    if field == "used_in":
        return isinstance(value, list) and any(bool(item) for item in value)
    if isinstance(value, str):
        return bool(value.strip())
    return value not in (None, "", [], {})


def _source_receipt_quality_gaps(receipts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not receipts:
        return [
            {
                "gap_id": "source_receipts_missing",
                "section": "source_receipts",
                "message": (
                    "source_receipts is empty even though audit workpaper "
                    "source receipts are required."
                ),
                "source_fields": ["source_receipts", "sources"],
            }
        ]

    gaps: list[dict[str, Any]] = []
    for idx, receipt in enumerate(receipts):
        missing_fields = [
            field
            for field in _AUDIT_SOURCE_RECEIPT_REQUIRED_FIELDS
            if not _receipt_field_has_value(receipt, field)
        ]
        if not missing_fields:
            continue
        gaps.append(
            {
                "gap_id": "source_receipt_missing_fields",
                "section": "source_receipts",
                "source_receipt_id": receipt.get("source_receipt_id"),
                "source_url": receipt.get("source_url"),
                "missing_fields": missing_fields,
                "message": (
                    "source_receipts entry is missing required audit fields: "
                    + ", ".join(missing_fields)
                ),
                "source_fields": [f"source_receipts[{idx}].{field}" for field in missing_fields],
            }
        )
    return gaps


def _source_receipt_completion(
    receipts: list[dict[str, Any]] | None,
) -> dict[str, int]:
    if not receipts:
        return {"total": 0, "complete": 0, "incomplete": 0}
    complete = 0
    for receipt in receipts:
        if all(
            _receipt_field_has_value(receipt, field)
            for field in _AUDIT_SOURCE_RECEIPT_REQUIRED_FIELDS
        ):
            complete += 1
    return {
        "total": len(receipts),
        "complete": complete,
        "incomplete": max(0, len(receipts) - complete),
    }


def _append_source_receipt_quality_gaps(
    body: dict[str, Any],
    receipts: list[dict[str, Any]],
) -> None:
    raw_existing_gaps = body.get("known_gaps")
    existing_gaps: list[Any] = (
        list(raw_existing_gaps) if isinstance(raw_existing_gaps, list) else []
    )
    known_keys = {
        (
            gap.get("gap_id"),
            gap.get("source_receipt_id"),
            gap.get("source_url"),
            tuple(gap.get("missing_fields") or []),
        )
        for gap in existing_gaps
        if isinstance(gap, dict)
    }
    new_gaps = []
    quality_gaps = _source_receipt_quality_gaps(receipts)
    for gap in quality_gaps:
        gap_key = (
            gap.get("gap_id"),
            gap.get("source_receipt_id"),
            gap.get("source_url"),
            tuple(gap.get("missing_fields") or []),
        )
        if gap_key not in known_keys:
            new_gaps.append(gap)
    if new_gaps:
        body["known_gaps"] = [*existing_gaps, *new_gaps]
    if quality_gaps:
        raw_existing_review = body.get("human_review_required")
        existing_review: list[Any] = (
            list(raw_existing_review) if isinstance(raw_existing_review, list) else []
        )
        receipt_review = [
            f"source_receipt_gap:{gap.get('source_receipt_id') or gap.get('gap_id')}"
            for gap in quality_gaps
        ]
        body["human_review_required"] = sorted({*existing_review, *receipt_review})


_KNOWN_GAP_SEVERITIES = frozenset({"info", "review", "warning", "blocking"})


def _gap_id_from_text(text: str) -> str:
    gap_id = text.split(":", 1)[0].strip()
    return gap_id or "known_gap"


def _normalize_source_fields(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if item not in (None, "")]
    if isinstance(value, str) and value:
        return [value]
    return []


def _normalize_known_gap(gap: Any) -> dict[str, Any]:
    if isinstance(gap, dict):
        normalized = dict(gap)
        gap_id = normalized.get("gap_id") or normalized.get("code") or normalized.get("id")
        normalized["gap_id"] = str(gap_id or "known_gap")
        severity = str(normalized.get("severity") or "review")
        normalized["severity"] = severity if severity in _KNOWN_GAP_SEVERITIES else "review"
        if normalized.get("message") in (None, "") and normalized.get("message_ja") in (None, ""):
            normalized["message"] = normalized["gap_id"]
        normalized["source_fields"] = _normalize_source_fields(normalized.get("source_fields"))
        return normalized

    message = str(gap)
    return {
        "gap_id": _gap_id_from_text(message),
        "severity": "review",
        "message": message,
        "source_fields": ["known_gaps"],
    }


def _normalize_known_gaps(body: dict[str, Any]) -> None:
    gaps = body.get("known_gaps")
    if not isinstance(gaps, list):
        body["known_gaps"] = []
        return
    body["known_gaps"] = [_normalize_known_gap(gap) for gap in gaps]


def _sync_known_gaps_to_sections(body: dict[str, Any]) -> None:
    gaps = body.get("known_gaps")
    if not isinstance(gaps, list):
        return
    sections = body.get("sections")
    if not isinstance(sections, list):
        return
    for section in sections:
        if not isinstance(section, dict) or section.get("section_id") != "risk_and_gap_register":
            continue
        rows = section.get("rows")
        if not isinstance(rows, list):
            continue
        for row in rows:
            if isinstance(row, dict):
                row["known_gaps"] = gaps


def _known_gap_ref(gap: Any) -> str:
    if isinstance(gap, str):
        return gap
    if isinstance(gap, dict):
        parts = [
            str(gap.get(key))
            for key in ("gap_id", "section", "table")
            if gap.get(key) not in (None, "")
        ]
        if parts:
            return ":".join(parts)
    return "unstructured_gap"


_CLAIM_SECTION_IDS = {
    "compatibility_pairs",
    "ranked_candidates",
}
_CLAIM_FIELD_NAMES = {
    "verdict",
    "recommendation",
    "match_reasons",
    "caveats",
    "claim",
    "claim_text",
    "basis",
}
_SOURCE_FIELD_NAMES = {
    "source_url",
    "primary_source_url",
    "source_urls",
    "rule_chain",
    "source_mentions",
}


def _row_ref(row: dict[str, Any], fallback: str) -> str:
    for key in ("row_id", "unified_id", "program_id", "question_id", "id"):
        value = row.get(key)
        if value not in (None, ""):
            return str(value)
    return fallback


def _row_claim_fields(row: dict[str, Any]) -> list[str]:
    return [
        key for key in _CLAIM_FIELD_NAMES if key in row and row.get(key) not in (None, "", [], {})
    ]


def _contains_http_url(value: Any) -> bool:
    if isinstance(value, str):
        return value.startswith(("http://", "https://"))
    if isinstance(value, dict):
        return any(_contains_http_url(child) for child in value.values())
    if isinstance(value, list):
        return any(_contains_http_url(child) for child in value)
    return False


def _row_has_source_hint(row: dict[str, Any]) -> bool:
    return any(_contains_http_url(row.get(key)) for key in _SOURCE_FIELD_NAMES)


def _source_used_in_covers_row(sources: list[Any], section_id: str, row_ref: str) -> bool:
    candidates = (
        f"{section_id}.{row_ref}",
        f"{section_id}.rows.{row_ref}",
        f"{section_id}.rows[].{row_ref}",
        row_ref,
    )
    for source in sources:
        if not isinstance(source, dict):
            continue
        used_in = source.get("used_in")
        if not isinstance(used_in, list):
            continue
        for ref in used_in:
            ref_text = str(ref)
            if any(candidate in ref_text for candidate in candidates):
                return True
    return False


def _existing_known_gap_keys(
    gaps: list[Any] | None,
) -> set[tuple[str, str | None, str | None]]:
    keys: set[tuple[str, str | None, str | None]] = set()
    if not gaps:
        return keys
    for gap in gaps:
        if isinstance(gap, str):
            gap_id = _gap_id_from_text(gap)
            row_ref = gap.split(":", 1)[1] if ":" in gap else None
            keys.add((gap_id, None, row_ref))
        elif isinstance(gap, dict):
            keys.add(
                (
                    str(gap.get("gap_id") or "known_gap"),
                    str(gap.get("section")) if gap.get("section") not in (None, "") else None,
                    str(gap.get("row_ref")) if gap.get("row_ref") not in (None, "") else None,
                )
            )
    return keys


def _claim_coverage(body: dict[str, Any]) -> dict[str, int]:
    claim_count = 0
    source_linked_claim_count = 0
    unsupported_claim_count = 0
    source_missing_claim_count = 0
    known_keys = _existing_known_gap_keys(
        body.get("known_gaps") if isinstance(body.get("known_gaps"), list) else []
    )
    for section in body.get("sections") or []:
        if not isinstance(section, dict) or section.get("section_id") not in _CLAIM_SECTION_IDS:
            continue
        rows = section.get("rows") or section.get("pairs") or []
        if not isinstance(rows, list):
            continue
        section_id = str(section.get("section_id"))
        for idx, row in enumerate(rows):
            if not isinstance(row, dict) or not _row_claim_fields(row):
                continue
            claim_count += 1
            row_ref = _row_ref(row, f"row_{idx + 1:03d}")
            if _row_has_source_hint(row) or _source_used_in_covers_row(
                body.get("sources") or [],
                section_id,
                row_ref,
            ):
                source_linked_claim_count += 1
            elif (
                section_id == "compatibility_pairs"
                or ("source_missing", section_id, row_ref) in known_keys
                or ("source_missing", None, row_ref) in known_keys
            ):
                source_missing_claim_count += 1
            else:
                unsupported_claim_count += 1
    return {
        "claim_count": claim_count,
        "source_linked_claim_count": source_linked_claim_count,
        "unsupported_claim_count": unsupported_claim_count,
        "source_missing_claim_count": source_missing_claim_count,
    }


def _append_source_claim_coverage_gaps(body: dict[str, Any]) -> None:
    raw_gaps = body.get("known_gaps")
    gaps: list[Any] = list(raw_gaps) if isinstance(raw_gaps, list) else []
    known_keys = _existing_known_gap_keys(gaps)
    new_gaps: list[dict[str, Any]] = []
    for section_idx, section in enumerate(body.get("sections") or []):
        if not isinstance(section, dict) or section.get("section_id") not in _CLAIM_SECTION_IDS:
            continue
        rows = section.get("rows") or section.get("pairs") or []
        if not isinstance(rows, list):
            continue
        section_id = str(section.get("section_id"))
        for row_idx, row in enumerate(rows):
            if not isinstance(row, dict):
                continue
            claim_fields = _row_claim_fields(row)
            if not claim_fields:
                continue
            row_ref = _row_ref(row, f"row_{row_idx + 1:03d}")
            if _row_has_source_hint(row) or _source_used_in_covers_row(
                body.get("sources") or [],
                section_id,
                row_ref,
            ):
                continue
            gap_id = (
                "source_missing" if section_id == "compatibility_pairs" else "unsupported_claim"
            )
            if gap_id == "unsupported_claim" and (
                ("source_missing", section_id, row_ref) in known_keys
                or ("source_missing", None, row_ref) in known_keys
            ):
                continue
            if (gap_id, section_id, row_ref) in known_keys or (gap_id, None, row_ref) in known_keys:
                continue
            new_gaps.append(
                {
                    "gap_id": gap_id,
                    "severity": "warning",
                    "section": section_id,
                    "row_ref": row_ref,
                    "claim_fields": claim_fields,
                    "message": "artifact claim has no linked source coverage",
                    "source_fields": [
                        f"sections[{section_idx}].rows[{row_idx}]",
                        "sources[].used_in",
                    ],
                }
            )
            known_keys.add((gap_id, section_id, row_ref))
    if new_gaps:
        body["known_gaps"] = [*gaps, *new_gaps]


def _build_artifact_evidence(body: dict[str, Any]) -> dict[str, Any]:
    refs = _source_refs(body)
    raw_gaps = body.get("known_gaps")
    gaps: list[Any] = list(raw_gaps) if isinstance(raw_gaps, list) else []
    raw_receipts = body.get("source_receipts")
    receipts: list[dict[str, Any]] = (
        [r for r in raw_receipts if isinstance(r, dict)] if isinstance(raw_receipts, list) else []
    )
    receipt_completion = _source_receipt_completion(receipts)
    return {
        "source_count": len(refs),
        "source_refs": refs[:20],
        "known_gap_count": len(gaps),
        "known_gap_refs": [_known_gap_ref(gap) for gap in gaps[:20]],
        "claim_coverage": _claim_coverage(body),
        "source_receipt_completion": receipt_completion,
        "basis_fields": ["sources", "known_gaps", "sections"],
    }


def _build_recommended_followup(body: dict[str, Any]) -> list[dict[str, Any]]:
    followup: list[dict[str, Any]] = []
    if body.get("sources"):
        followup.append(
            {
                "action_id": "verify_cited_sources",
                "priority": "high",
                "label_ja": "根拠URLを確認する",
                "source_fields": ["sources"],
            }
        )
    if body.get("known_gaps"):
        followup.append(
            {
                "action_id": "resolve_known_gaps",
                "priority": "high",
                "label_ja": "known_gapsを確認する",
                "source_fields": ["known_gaps"],
            }
        )
    if body.get("human_review_required"):
        followup.append(
            {
                "action_id": "route_human_review",
                "priority": "high",
                "label_ja": "要確認項目を担当者へ回す",
                "source_fields": ["human_review_required"],
            }
        )
    followup.append(
        {
            "action_id": "confirm_target_and_date",
            "priority": "medium",
            "label_ja": "対象IDと参照日を確認する",
            "source_fields": ["summary", "corpus_snapshot_id"],
        }
    )
    return followup


def _build_recommended_followup_channels(
    body: dict[str, Any],
    followup: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    artifact_type = str(body.get("artifact_type") or "artifact")
    use_jpcite_next: list[dict[str, Any]] = []
    if artifact_type == "company_public_baseline":
        use_jpcite_next.extend(
            [
                {
                    "endpoint": "/v1/artifacts/company_public_audit_pack",
                    "reason_ja": "監査・DD向けに evidence table と gap register を厚くする。",
                },
                {
                    "endpoint": "/v1/artifacts/company_folder_brief",
                    "reason_ja": "会社フォルダのREADME、質問、タスクへ変換する。",
                },
            ]
        )
    elif artifact_type == "company_folder_brief":
        use_jpcite_next.append(
            {
                "endpoint": "/v1/artifacts/company_public_audit_pack",
                "reason_ja": "フォルダ作成後に根拠台帳と確認範囲を残す。",
            }
        )
    elif artifact_type == "company_public_audit_pack":
        use_jpcite_next.append(
            {
                "endpoint": "/v1/artifacts/houjin_dd_pack",
                "reason_ja": "公開DDの初回論点をさらに深掘りする。",
            }
        )
    elif artifact_type == "application_strategy_pack":
        use_jpcite_next.append(
            {
                "endpoint": "/v1/artifacts/compatibility_table",
                "reason_ja": "候補制度の併用可否をpair単位で確認する。",
            }
        )

    use_web_search_for = [
        {
            "topic": "known_gaps_or_recent_private_context",
            "reason_ja": "jpciteのknown_gaps、非公的情報、直近ニュース、会社サイトはWeb検索で補う。",
        }
    ]
    if not body.get("known_gaps"):
        use_web_search_for[0]["reason_ja"] = (
            "会社サイト、直近ニュース、非公的な商談文脈だけをWeb検索で補う。"
        )

    use_professional_review_for = [
        {
            "topic": item.get("action_id") if isinstance(item, dict) else str(item),
            "reason_ja": "最終判断、税務・法務・監査・与信・申請可否は有資格者または担当者が確認する。",
        }
        for item in followup
        if isinstance(item, dict) and item.get("priority") == "high"
    ]
    if body.get("human_review_required") and not use_professional_review_for:
        use_professional_review_for.append(
            {
                "topic": "human_review_required",
                "reason_ja": "機械的な公開情報整理だけでは判断できない要確認項目がある。",
            }
        )

    return {
        "use_jpcite_next": use_jpcite_next,
        "use_web_search_for": use_web_search_for,
        "use_professional_review_for": use_professional_review_for,
    }


def _build_agent_routing(body: dict[str, Any]) -> dict[str, Any]:
    artifact_type = str(body.get("artifact_type") or "artifact")
    return {
        "call_jpcite_first_for": [
            "Japanese company public-record research",
            "company folder preparation",
            "counterparty public check",
            "audit or DD first-hop evidence gathering",
            "public benefit/risk angle discovery",
        ]
        if artifact_type.startswith("company_")
        else [
            "Japanese public program research",
            "source-linked eligibility or compatibility precheck",
        ],
        "use_web_search_after": [
            "known_gaps",
            "company website and non-public context",
            "very recent news outside the corpus",
        ],
        "preserve_fields": [
            "source_url",
            "source_fetched_at",
            "known_gaps",
            "human_review_required",
            "_disclaimer",
        ],
        "no_llm_called_by_jpcite": True,
        "pricing_note": _ARTIFACT_BILLING_NOTE,
    }


def _short_scalar(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, str | int | float | bool):
        text = str(value)
    elif isinstance(value, list):
        text = f"{len(value)} items"
    elif isinstance(value, dict):
        text = f"{len(value)} fields"
    else:
        text = str(value)
    return text[:160]


def _summary_markdown(summary: dict[str, Any] | None) -> list[str]:
    lines: list[str] = []
    if not summary:
        return lines
    for key, value in summary.items():
        if isinstance(value, dict | list):
            continue
        lines.append(f"- `{key}`: {_short_scalar(value)}")
    return lines


def _build_markdown_display(
    body: dict[str, Any],
    followup: list[dict[str, Any]],
    evidence: dict[str, Any],
) -> str:
    artifact_type = str(body.get("artifact_type") or "artifact")
    packet_id = str(body.get("packet_id") or "")
    summary = body.get("summary") if isinstance(body.get("summary"), dict) else {}
    lines = [f"# {artifact_type} `{packet_id}`", "", "## Summary"]
    summary_lines = _summary_markdown(summary)
    lines.extend(summary_lines or ["- Summary fields are not available."])
    lines.extend(
        [
            "",
            "## Evidence",
            f"- Source refs: {evidence.get('source_count', 0)}",
            f"- Known gaps: {evidence.get('known_gap_count', 0)}",
            "- Source receipts: "
            f"{(evidence.get('source_receipt_completion') or {}).get('complete', 0)} complete / "
            f"{(evidence.get('source_receipt_completion') or {}).get('total', 0)} total",
            f"- Human review: {len(body.get('human_review_required') or [])}",
            f"- Billing: {body.get('agent_routing', {}).get('pricing_note', 'metered request')}",
            "",
            "## Follow-up",
        ]
    )
    for item in followup[:6]:
        lines.append(f"- [{item.get('priority', 'medium')}] {item.get('action_id')}")
    return "\n".join(lines)


def _build_copy_paste_parts(
    body: dict[str, Any],
    followup: list[dict[str, Any]],
    evidence: dict[str, Any],
) -> list[dict[str, Any]]:
    artifact_type = str(body.get("artifact_type") or "artifact")
    raw_summary = body.get("summary")
    summary: dict[str, Any] = dict(raw_summary) if isinstance(raw_summary, dict) else {}
    headline_bits = [
        f"{key}={_short_scalar(value)}"
        for key, value in summary.items()
        if not isinstance(value, dict | list)
    ][:6]
    parts: list[dict[str, Any]] = []
    workflow_outputs = body.get("workflow_outputs")
    if isinstance(workflow_outputs, dict):
        for part_id, text in workflow_outputs.items():
            if isinstance(text, str) and text.strip():
                parts.append(
                    {
                        "part_id": part_id,
                        "title": part_id.replace("_", " ").title(),
                        "text": text.strip(),
                    }
                )

    parts.extend(
        [
            {
                "part_id": "summary",
                "title": "Summary",
                "text": f"{artifact_type}: " + "; ".join(headline_bits),
            },
            {
                "part_id": "evidence_status",
                "title": "Evidence status",
                "text": (
                    f"source_refs={evidence.get('source_count', 0)}; "
                    f"known_gaps={evidence.get('known_gap_count', 0)}; "
                    f"source_receipts={evidence.get('source_receipt_completion', {}).get('complete', 0)}/"
                    f"{evidence.get('source_receipt_completion', {}).get('total', 0)}; "
                    f"human_review={len(body.get('human_review_required') or [])}"
                ),
            },
            {
                "part_id": "followup",
                "title": "Follow-up",
                "text": "; ".join(str(item.get("action_id")) for item in followup[:6]),
            },
        ]
    )
    return parts


def _attach_common_artifact_envelope(body: dict[str, Any]) -> None:
    body.setdefault("artifact_version", "2026-05-06")
    body.setdefault("generated_at", _utc_now_iso())
    body.setdefault("sources", [])
    body.setdefault("known_gaps", [])
    body.setdefault("human_review_required", [])
    body["billing_note"] = _ARTIFACT_BILLING_NOTE
    body["packet_id"] = _artifact_packet_id(body)
    receipts = _source_receipts(body)
    body["source_receipts"] = receipts
    if body.get("artifact_type") in _SOURCE_RECEIPT_QUALITY_ARTIFACTS:
        _append_source_receipt_quality_gaps(body, receipts)
    _append_source_claim_coverage_gaps(body)
    _normalize_known_gaps(body)
    if body.get("artifact_type") in _SOURCE_RECEIPT_QUALITY_ARTIFACTS:
        _sync_known_gaps_to_sections(body)
    evidence = _build_artifact_evidence(body)
    followup = _build_recommended_followup(body)
    body["_evidence"] = evidence
    body["recommended_followup"] = followup
    body["recommended_followup_by_channel"] = _build_recommended_followup_channels(body, followup)
    body["agent_routing"] = _build_agent_routing(body)
    body["copy_paste_parts"] = _build_copy_paste_parts(body, followup, evidence)
    body["markdown_display"] = _build_markdown_display(body, followup, evidence)


def _step_urls(step: dict[str, Any]) -> list[str]:
    urls: list[str] = []
    raw_url = step.get("source_url")
    if isinstance(raw_url, str) and raw_url:
        urls.append(raw_url)
    raw_urls = step.get("source_urls")
    if isinstance(raw_urls, str) and raw_urls:
        urls.append(raw_urls)
    elif isinstance(raw_urls, list):
        urls.extend(url for url in raw_urls if isinstance(url, str) and url)
    return urls


def _compatibility_sources(
    rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    by_url: dict[str, dict[str, Any]] = {}
    known_gaps: list[str] = []
    for row in rows:
        row_id = row["row_id"]
        row_has_source = False
        for idx, step in enumerate(row.get("rule_chain") or []):
            if not isinstance(step, dict):
                continue
            urls = _step_urls(step)
            if urls:
                row_has_source = True
            if step.get("source") == "default":
                known_gaps.append(f"default_rule_used:{row_id}")
            if step.get("inferred_only") == 1:
                known_gaps.append(f"heuristic_rule_used:{row_id}")
            for url in urls:
                item = by_url.setdefault(
                    url,
                    {
                        "source_url": url,
                        "source_kind": step.get("source") or "unknown",
                        "used_in": [],
                    },
                )
                item["used_in"].append(f"compatibility_pairs.{row_id}.rule_chain[{idx}]")
        if row.get("verdict") == "unknown":
            known_gaps.append(f"unknown_verdict:{row_id}")
        if not row_has_source:
            known_gaps.append(f"source_missing:{row_id}")
    return list(by_url.values()), sorted(set(known_gaps))


def _build_compatibility_artifact(stack_body: dict[str, Any]) -> dict[str, Any]:
    pairs = list(stack_body.get("pairs") or [])
    rows: list[dict[str, Any]] = []
    verdict_counts: Counter[str] = Counter()
    for idx, pair in enumerate(pairs, start=1):
        row = dict(pair)
        row_id = f"pair_{idx:03d}"
        row["row_id"] = row_id
        rows.append(row)
        verdict = row.get("verdict")
        if isinstance(verdict, str):
            verdict_counts[verdict] += 1

    sources, known_gaps = _compatibility_sources(rows)
    all_pairs_status = stack_body.get("all_pairs_status")
    human_review_required: list[str] = []
    if all_pairs_status in {"incompatible", "requires_review", "unknown"}:
        human_review_required.append(f"all_pairs_status:{all_pairs_status}")
    for row in rows:
        if row.get("verdict") in {"incompatible", "requires_review", "unknown"}:
            human_review_required.append(
                f"{row['row_id']}:{row.get('program_a')}:{row.get('program_b')}"
            )

    artifact_type = "compatibility_table"
    artifact_id = _stable_artifact_id(
        artifact_type,
        {
            "program_ids": stack_body.get("program_ids") or [],
            "pairs": [
                {
                    "program_a": row.get("program_a"),
                    "program_b": row.get("program_b"),
                    "verdict": row.get("verdict"),
                    "confidence": row.get("confidence"),
                }
                for row in rows
            ],
        },
    )
    return {
        "artifact_id": artifact_id,
        "artifact_type": artifact_type,
        "schema_version": "v1",
        "endpoint": "artifacts.compatibility_table",
        "summary": {
            "program_count": len(stack_body.get("program_ids") or []),
            "total_pairs": int(stack_body.get("total_pairs") or len(rows)),
            "all_pairs_status": all_pairs_status,
            "verdict_counts": dict(sorted(verdict_counts.items())),
        },
        "sections": [
            {
                "section_id": "compatibility_pairs",
                "title": "Compatibility pairs",
                "rows": rows,
            },
            {
                "section_id": "blockers",
                "title": "Hard blockers",
                "rows": stack_body.get("blockers") or [],
            },
            {
                "section_id": "warnings",
                "title": "Warnings",
                "rows": stack_body.get("warnings") or [],
            },
        ],
        "sources": sources,
        "known_gaps": known_gaps,
        "next_actions": stack_body.get("next_actions") or [],
        "human_review_required": sorted(set(human_review_required)),
        "_disclaimer": stack_body.get("_disclaimer") or "",
    }


def _collect_sources(node: Any) -> list[dict[str, Any]]:
    by_url: dict[str, dict[str, Any]] = {}

    def attach_metadata(item: dict[str, Any], value: dict[str, Any]) -> None:
        for target, candidates in {
            "source_fetched_at": ("source_fetched_at", "fetched_at", "last_verified_at"),
            "content_hash": ("content_hash", "source_checksum"),
            "license": ("license", "license_or_terms"),
        }.items():
            if item.get(target):
                continue
            for candidate in candidates:
                found = value.get(candidate)
                if isinstance(found, str) and found:
                    item[target] = found
                    break

    def walk(value: Any, path: str) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                child_path = f"{path}.{key}" if path else key
                if key in {"source_url", "primary_source_url"} and isinstance(child, str):
                    if child.startswith(("http://", "https://")):
                        item = by_url.setdefault(child, {"source_url": child, "used_in": []})
                        item["used_in"].append(child_path)
                        attach_metadata(item, value)
                elif key == "source_urls" and isinstance(child, list):
                    for idx, url in enumerate(child):
                        if isinstance(url, str) and url.startswith(("http://", "https://")):
                            item = by_url.setdefault(url, {"source_url": url, "used_in": []})
                            item["used_in"].append(f"{child_path}[{idx}]")
                            attach_metadata(item, value)
                walk(child, child_path)
        elif isinstance(value, list):
            for idx, child in enumerate(value):
                walk(child, f"{path}[{idx}]")

    walk(node, "")
    return list(by_url.values())


def _risk_value(body: dict[str, Any], section: str, key: str) -> Any:
    decision_support = body.get("decision_support")
    if not isinstance(decision_support, dict):
        return None
    risk_summary = decision_support.get("risk_summary")
    if not isinstance(risk_summary, dict):
        return None
    section_value = risk_summary.get(section)
    if not isinstance(section_value, dict):
        return None
    return section_value.get(key)


def _decision_support(houjin_body: dict[str, Any]) -> dict[str, Any]:
    value = houjin_body.get("decision_support")
    return value if isinstance(value, dict) else {}


def _risk_summary(houjin_body: dict[str, Any]) -> dict[str, Any]:
    value = _decision_support(houjin_body).get("risk_summary")
    return value if isinstance(value, dict) else {"flags": []}


def _houjin_meta(houjin_body: dict[str, Any]) -> dict[str, Any]:
    value = houjin_body.get("houjin_meta")
    return value if isinstance(value, dict) else {}


def _invoice_status(houjin_body: dict[str, Any]) -> dict[str, Any]:
    value = houjin_body.get("invoice_status")
    return value if isinstance(value, dict) else {}


def _watch_status(houjin_body: dict[str, Any]) -> dict[str, Any]:
    value = houjin_body.get("watch_status")
    return value if isinstance(value, dict) else {}


def _dict_rows(houjin_body: dict[str, Any], key: str) -> list[dict[str, Any]]:
    return [row for row in houjin_body.get(key) or [] if isinstance(row, dict)]


def _houjin_known_gaps(
    houjin_body: dict[str, Any],
    *,
    unavailable_label: str = "company artifact",
) -> list[Any]:
    decision_support = _decision_support(houjin_body)
    known_gaps = list(decision_support.get("known_gaps") or [])
    raw_data_quality = houjin_body.get("data_quality")
    data_quality: dict[str, Any] = (
        dict(raw_data_quality) if isinstance(raw_data_quality, dict) else {}
    )
    for table in data_quality.get("missing_tables") or []:
        if isinstance(table, str):
            known_gaps.append(
                {
                    "gap_id": "missing_table",
                    "table": table,
                    "message": f"{table} was unavailable for this {unavailable_label}.",
                    "source_fields": ["data_quality.missing_tables"],
                }
            )
    return known_gaps


def _houjin_risk_flags(houjin_body: dict[str, Any]) -> list[str]:
    return [str(flag) for flag in _risk_summary(houjin_body).get("flags") or []]


def _company_review_items(houjin_body: dict[str, Any]) -> list[str]:
    flags = _houjin_risk_flags(houjin_body)
    known_gaps = _houjin_known_gaps(houjin_body, unavailable_label="DD artifact")
    return sorted(
        set(
            [f"risk_flag:{flag}" for flag in flags]
            + [
                f"known_gap:{gap.get('gap_id')}:{gap.get('section')}"
                for gap in known_gaps
                if isinstance(gap, dict)
            ]
            + [f"known_gap:{gap}" for gap in known_gaps if isinstance(gap, str)]
        )
    )


_DD_QUESTION_BY_ACTION: dict[str, str] = {
    "verify_enforcement_source": (
        "行政処分・改善命令・入札停止等の原典URLを確認し、処分内容、対象期間、"
        "再発防止策、現在の解消状況を相手先へ確認してください。"
    ),
    "review_invoice_status": (
        "インボイス登録番号、登録日、取消日・失効日の有無を確認し、支払・税務処理に"
        "影響する状態変更がないか確認してください。"
    ),
    "review_jurisdiction": (
        "登記所在地、インボイス所在地、採択・事業活動地域がずれている理由を確認し、"
        "実質的な事業拠点と契約主体が一致するか確認してください。"
    ),
    "monitor_changes": (
        "法人名・所在地・登録状態・行政処分・採択履歴の変更を継続監視し、前回確認時"
        "からの差分を取引判断前に再確認してください。"
    ),
}


def _build_dd_questions(decision_support: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for idx, action in enumerate(decision_support.get("next_actions") or [], start=1):
        if not isinstance(action, dict):
            continue
        action_id = str(action.get("action") or "")
        if not action_id or action_id in seen:
            continue
        seen.add(action_id)
        rows.append(
            {
                "question_id": f"ddq_{idx:03d}",
                "priority": action.get("priority") or "medium",
                "question_ja": _DD_QUESTION_BY_ACTION.get(
                    action_id,
                    "返却された根拠項目を一次資料で確認し、判断に必要な不足情報を相手先へ確認してください。",
                ),
                "basis_action": action_id,
                "source_fields": action.get("source_fields") or [],
            }
        )
    if not rows:
        rows.append(
            {
                "question_id": "ddq_001",
                "priority": "medium",
                "question_ja": (
                    "返却された各セクションが空でも安全性の証明ではありません。法人番号、"
                    "登録状態、処分履歴、所在地、主要取引・補助金履歴を一次資料で確認してください。"
                ),
                "basis_action": "baseline_public_dd",
                "source_fields": ["decision_support.known_gaps"],
            }
        )
    return rows


def _build_houjin_dd_pack_artifact(
    houjin_body: dict[str, Any],
    *,
    sections: list[str],
    request_payload: dict[str, Any],
) -> dict[str, Any]:
    decision_support = _decision_support(houjin_body)
    risk_summary = _risk_summary(houjin_body)
    meta = _houjin_meta(houjin_body)
    invoice = _invoice_status(houjin_body)
    watch = _watch_status(houjin_body)
    enforcement_records = _dict_rows(houjin_body, "enforcement_records")
    adoption_history = _dict_rows(houjin_body, "adoption_history")
    flags = _houjin_risk_flags(houjin_body)
    known_gaps = _houjin_known_gaps(houjin_body)

    artifact_type = "houjin_dd_pack"
    artifact_id = _stable_artifact_id(
        artifact_type,
        {
            "houjin_bangou": houjin_body.get("houjin_bangou"),
            "sections": sections,
            "risk_flags": flags,
            "request": request_payload,
        },
    )
    return {
        "artifact_id": artifact_id,
        "artifact_type": artifact_type,
        "schema_version": "v1",
        "endpoint": "artifacts.houjin_dd_pack",
        "summary": {
            "houjin_bangou": houjin_body.get("houjin_bangou"),
            "company_name": meta.get("name"),
            "invoice_status": _risk_value(houjin_body, "invoice_status", "status"),
            "enforcement_record_count": len(enforcement_records),
            "max_enforcement_severity": _risk_value(houjin_body, "enforcement", "max_severity"),
            "adoption_record_count": len(adoption_history),
            "jurisdiction_status": _risk_value(houjin_body, "jurisdiction", "status"),
            "watch_status": "watched" if watch.get("is_watched") else "not_watched",
            "risk_flags": flags,
        },
        "sections": [
            {
                "section_id": "corporate_profile",
                "title": "Corporate profile",
                "rows": [meta] if meta else [],
            },
            {
                "section_id": "public_risk_signals",
                "title": "Public risk signals",
                "rows": [
                    {
                        "signal": "enforcement",
                        "summary": risk_summary.get("enforcement"),
                        "records": enforcement_records,
                    },
                    {
                        "signal": "invoice_status",
                        "summary": risk_summary.get("invoice_status"),
                        "records": [invoice] if invoice else [],
                    },
                    {
                        "signal": "jurisdiction",
                        "summary": risk_summary.get("jurisdiction"),
                        "records": [houjin_body.get("jurisdiction_breakdown")]
                        if houjin_body.get("jurisdiction_breakdown")
                        else [],
                    },
                ],
            },
            {
                "section_id": "funding_and_peer_signals",
                "title": "Funding and peer signals",
                "rows": [
                    {"signal": "adoption_history", "records": adoption_history},
                    {
                        "signal": "peer_summary",
                        "records": [houjin_body.get("peer_summary")]
                        if houjin_body.get("peer_summary")
                        else [],
                    },
                ],
            },
            {
                "section_id": "dd_questions",
                "title": "DD questions",
                "rows": _build_dd_questions(decision_support),
            },
            {
                "section_id": "decision_support",
                "title": "Decision support",
                "rows": [
                    {
                        "risk_summary": risk_summary,
                        "decision_insights": decision_support.get("decision_insights") or [],
                    }
                ],
            },
        ],
        "sources": _collect_sources(houjin_body),
        "known_gaps": known_gaps,
        "next_actions": decision_support.get("next_actions") or [],
        "human_review_required": sorted(
            set(
                [f"risk_flag:{flag}" for flag in flags]
                + [
                    f"known_gap:{gap.get('gap_id')}:{gap.get('section')}"
                    for gap in known_gaps
                    if isinstance(gap, dict)
                ]
            )
        ),
        "_disclaimer": houjin_body.get("_disclaimer") or "",
    }


def _json_or(raw: Any, default: Any) -> Any:
    if raw in (None, ""):
        return default
    if not isinstance(raw, str):
        return default
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return default


def _table_columns(conn: Any, table: str) -> set[str]:
    try:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    except Exception:
        return set()
    columns: set[str] = set()
    for row in rows:
        try:
            columns.add(str(row["name"]))
        except (IndexError, KeyError, TypeError):
            columns.add(str(row[1]))
    return columns


def _program_table_columns(conn: Any) -> set[str]:
    return _table_columns(conn, "programs")


def _fetch_program_details(conn: Any, program_ids: list[str]) -> dict[str, dict[str, Any]]:
    if not program_ids:
        return {}
    available = _program_table_columns(conn)
    wanted = [
        "unified_id",
        "primary_name",
        "program_kind",
        "authority_level",
        "authority_name",
        "prefecture",
        "municipality",
        "amount_max_man_yen",
        "amount_min_man_yen",
        "subsidy_rate",
        "official_url",
        "source_url",
        "source_fetched_at",
        "source_checksum",
        "content_hash",
        "license",
        "license_or_terms",
        "application_window_json",
        "target_types_json",
        "funding_purpose_json",
        "source_mentions_json",
    ]
    cols = [col for col in wanted if col in available]
    if "unified_id" not in cols or "primary_name" not in cols:
        return {}
    placeholders = ",".join("?" for _ in program_ids)
    rows = conn.execute(
        f"SELECT {', '.join(cols)} FROM programs WHERE unified_id IN ({placeholders})",
        program_ids,
    ).fetchall()
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        item = {key: row[key] for key in cols}
        item["target_types"] = _json_or(item.get("target_types_json"), [])
        item["funding_purpose"] = _json_or(item.get("funding_purpose_json"), [])
        item["application_window"] = _json_or(item.get("application_window_json"), None)
        item["source_mentions"] = _json_or(item.get("source_mentions_json"), None)
        out[str(item["unified_id"])] = item
    return out


def _has_source_meta_value(value: Any) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    return value not in (None, "", [], {})


def _copy_missing_source_metadata(target: dict[str, Any], metadata: dict[str, Any]) -> None:
    for key in (
        "source_fetched_at",
        "content_hash",
        "source_checksum",
        "license",
        "license_or_terms",
        "source_kind",
        "publisher",
        "attribution_text",
    ):
        if _has_source_meta_value(target.get(key)):
            continue
        value = metadata.get(key)
        if _has_source_meta_value(value):
            target[key] = value
    if not _has_source_meta_value(target.get("license")) and _has_source_meta_value(
        target.get("license_or_terms")
    ):
        target["license"] = target["license_or_terms"]
    if not _has_source_meta_value(target.get("content_hash")) and _has_source_meta_value(
        target.get("source_checksum")
    ):
        target["content_hash"] = target["source_checksum"]


def _source_metadata_by_url(conn: Any, source_urls: list[str]) -> dict[str, dict[str, Any]]:
    urls = sorted({url for url in source_urls if url})
    if not urls:
        return {}
    metadata: dict[str, dict[str, Any]] = {}
    placeholders = ",".join("?" for _ in urls)

    source_document_cols = _table_columns(conn, "source_document")
    if {"source_url"} <= source_document_cols:
        wanted = [
            "source_url",
            "canonical_url",
            "license",
            "content_hash",
            "fetched_at",
            "last_verified_at",
            "document_kind",
            "publisher",
        ]
        cols = [col for col in wanted if col in source_document_cols]
        where = f"source_url IN ({placeholders})"
        params: list[Any] = list(urls)
        if "canonical_url" in cols:
            where = f"({where} OR canonical_url IN ({placeholders}))"
            params.extend(urls)
        order_cols = [
            col
            for col in ("last_verified_at", "fetched_at", "created_at", "source_url")
            if col in source_document_cols
        ]
        order_expr = f"COALESCE({', '.join(order_cols)})" if len(order_cols) > 1 else order_cols[0]
        rows = conn.execute(
            f"SELECT {', '.join(cols)} FROM source_document "
            f"WHERE {where} "
            f"ORDER BY {order_expr} DESC",
            params,
        ).fetchall()
        for row in rows:
            row_map = {key: row[key] for key in cols}
            target_urls = [row_map.get("source_url"), row_map.get("canonical_url")]
            item = {
                "license": row_map.get("license"),
                "content_hash": row_map.get("content_hash"),
                "source_fetched_at": row_map.get("fetched_at") or row_map.get("last_verified_at"),
                "source_kind": row_map.get("document_kind"),
                "publisher": row_map.get("publisher"),
            }
            for target_url in target_urls:
                if isinstance(target_url, str) and target_url in urls:
                    _copy_missing_source_metadata(
                        metadata.setdefault(target_url, {}),
                        item,
                    )

    source_catalog_cols = _table_columns(conn, "source_catalog")
    if {"source_url"} <= source_catalog_cols:
        wanted = [
            "source_url",
            "license_or_terms",
            "source_type",
            "official_owner",
            "attribution_text",
        ]
        cols = [col for col in wanted if col in source_catalog_cols]
        rows = conn.execute(
            f"SELECT {', '.join(cols)} FROM source_catalog WHERE source_url IN ({placeholders})",
            urls,
        ).fetchall()
        for row in rows:
            row_map = {key: row[key] for key in cols}
            source_url = row_map.get("source_url")
            if not isinstance(source_url, str) or source_url not in urls:
                continue
            item = {
                "license_or_terms": row_map.get("license_or_terms"),
                "license": row_map.get("license_or_terms"),
                "source_kind": row_map.get("source_type"),
                "publisher": row_map.get("official_owner"),
                "attribution_text": row_map.get("attribution_text"),
            }
            _copy_missing_source_metadata(metadata.setdefault(source_url, {}), item)

    return metadata


def _enrich_strategy_candidate_source_metadata(
    conn: Any,
    candidate_rows: list[dict[str, Any]],
) -> None:
    source_urls = [
        row["source_url"]
        for row in candidate_rows
        if isinstance(row.get("source_url"), str) and row.get("source_url")
    ]
    metadata = _source_metadata_by_url(conn, source_urls)
    for row in candidate_rows:
        source_url = row.get("source_url")
        if isinstance(source_url, str):
            _copy_missing_source_metadata(row, metadata.get(source_url, {}))


def _extract_application_deadline(application_window: Any) -> str | None:
    if not isinstance(application_window, dict):
        return None
    for key in ("end_date", "deadline", "application_deadline"):
        value = application_window.get(key)
        if isinstance(value, str) and len(value) >= 10:
            return value[:10]
    return None


def _normalize_strategy_profile(profile: PrescreenRequest, max_candidates: int) -> PrescreenRequest:
    return profile.model_copy(
        update={
            "prefecture": _normalize_prefecture(profile.prefecture),
            "industry_jsic": _normalize_industry_jsic(profile.industry_jsic),
            "limit": max_candidates,
        }
    )


def _candidate_recommendation(
    rank: int,
    caveats: list[str],
    amount_max: Any,
    planned_investment: float | None,
) -> str:
    if caveats:
        return "review_first"
    if planned_investment is not None and amount_max is not None:
        try:
            if float(amount_max) < float(planned_investment):
                return "combine_or_backup"
        except (TypeError, ValueError):
            pass
    if rank == 1:
        return "primary_candidate"
    if rank <= 3:
        return "backup_candidate"
    return "watch_candidate"


def _money_fit(amount_max: Any, planned_investment: float | None) -> dict[str, Any]:
    out: dict[str, Any] = {
        "amount_max_man_yen": amount_max,
        "planned_investment_man_yen": planned_investment,
        "coverage_ratio": None,
        "status": "unknown",
    }
    if planned_investment is None or planned_investment <= 0 or amount_max is None:
        return out
    try:
        ratio = float(amount_max) / float(planned_investment)
    except (TypeError, ValueError, ZeroDivisionError):
        return out
    out["coverage_ratio"] = round(ratio, 4)
    out["status"] = "covers_plan" if ratio >= 1 else "partial_cover"
    return out


def _build_strategy_candidate_rows(
    prescreen: PrescreenResponse,
    details: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    profile = prescreen.profile_echo
    planned_investment = profile.get("planned_investment_man_yen")
    rows: list[dict[str, Any]] = []
    for rank, match in enumerate(prescreen.results, start=1):
        row = match.model_dump()
        detail = details.get(match.unified_id, {})
        amount_max = detail.get("amount_max_man_yen", row.get("amount_max_man_yen"))
        caveats = [str(item) for item in row.get("caveats") or []]
        source_url = (
            detail.get("source_url") or detail.get("official_url") or row.get("official_url")
        )
        rows.append(
            {
                "rank": rank,
                "unified_id": match.unified_id,
                "primary_name": row.get("primary_name"),
                "recommendation": _candidate_recommendation(
                    rank,
                    caveats,
                    amount_max,
                    planned_investment,
                ),
                "fit_score": row.get("fit_score"),
                "match_reasons": row.get("match_reasons") or [],
                "caveats": caveats,
                "money_fit": _money_fit(amount_max, planned_investment),
                "program_kind": detail.get("program_kind") or row.get("program_kind"),
                "authority_level": detail.get("authority_level") or row.get("authority_level"),
                "authority_name": detail.get("authority_name"),
                "prefecture": detail.get("prefecture") or row.get("prefecture"),
                "target_types": detail.get("target_types") or [],
                "funding_purpose": detail.get("funding_purpose") or [],
                "application_deadline": _extract_application_deadline(
                    detail.get("application_window")
                ),
                "source_url": source_url,
                "source_fetched_at": detail.get("source_fetched_at"),
                "source_checksum": detail.get("source_checksum"),
                "content_hash": detail.get("content_hash") or detail.get("source_checksum"),
                "license": detail.get("license") or detail.get("license_or_terms"),
                "license_or_terms": detail.get("license_or_terms"),
                "source_mentions": detail.get("source_mentions") or [],
                "static_url": row.get("static_url"),
            }
        )
    return rows


def _build_program_compatibility_section(
    program_ids: list[str],
    top_n: int,
) -> tuple[dict[str, Any] | None, list[str]]:
    unique_ids = list(dict.fromkeys(program_ids))[:top_n]
    if top_n <= 0 or len(unique_ids) < 2:
        return None, []
    try:
        result = _get_checker().check_stack(unique_ids)
    except Exception as exc:
        logger.info("application_strategy_pack compatibility skipped: %s", exc)
        return None, ["compatibility_engine_unavailable"]
    stack_body = result.to_dict()
    artifact = _build_compatibility_artifact(stack_body)
    return (
        {
            "section_id": "compatibility_screen",
            "title": "Compatibility screen",
            "program_ids": unique_ids,
            "summary": artifact.get("summary") or {},
            "pairs": (artifact.get("sections") or [{}])[0].get("rows") or [],
            "blockers": (artifact.get("sections") or [{}, {}])[1].get("rows") or [],
            "warnings": (artifact.get("sections") or [{}, {}, {}])[2].get("rows") or [],
            "known_gaps": artifact.get("known_gaps") or [],
            "human_review_required": artifact.get("human_review_required") or [],
        },
        list(artifact.get("known_gaps") or []),
    )


def _build_application_next_actions(
    candidate_rows: list[dict[str, Any]],
    compatibility_section: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    top = candidate_rows[:3]
    if top:
        actions.append(
            {
                "action_id": "verify_primary_sources",
                "priority": "high",
                "message_ja": "上位候補の募集要領・公募要領・公式ページを確認する。",
                "target_program_ids": [row["unified_id"] for row in top],
                "source_fields": ["sections.ranked_candidates.rows[].source_url"],
            }
        )
    caveat_rows = [row for row in candidate_rows if row.get("caveats")]
    if caveat_rows:
        actions.append(
            {
                "action_id": "resolve_fit_caveats",
                "priority": "high",
                "message_ja": "対象者要件、前提認定、金額不足などの caveat を申請前に潰す。",
                "target_program_ids": [row["unified_id"] for row in caveat_rows[:5]],
                "source_fields": ["sections.ranked_candidates.rows[].caveats"],
            }
        )
    if compatibility_section and compatibility_section.get("human_review_required"):
        actions.append(
            {
                "action_id": "review_stack_conflicts",
                "priority": "high",
                "message_ja": "併用不可・要確認・不明の組み合わせを、最終候補化前に確認する。",
                "source_fields": ["sections.compatibility_screen"],
            }
        )
    actions.append(
        {
            "action_id": "prepare_application_memo",
            "priority": "medium",
            "message_ja": "上位候補ごとに、目的、対象経費、予定投資額、必要書類、締切を1枚にまとめる。",
            "source_fields": ["sections.ranked_candidates", "sections.application_questions"],
        }
    )
    return actions


def _build_application_questions(candidate_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for idx, row in enumerate(candidate_rows[:5], start=1):
        rows.append(
            {
                "question_id": f"appq_{idx:03d}",
                "program_id": row["unified_id"],
                "priority": "high" if row.get("caveats") else "medium",
                "question_ja": (
                    f"{row.get('primary_name')}について、対象経費、対象者区分、"
                    "締切、併用制限、必要書類が今回の計画に合うか確認してください。"
                ),
                "basis": {
                    "match_reasons": row.get("match_reasons") or [],
                    "caveats": row.get("caveats") or [],
                    "money_fit": row.get("money_fit") or {},
                },
            }
        )
    return rows


def _build_application_strategy_artifact(
    *,
    request_payload: dict[str, Any],
    prescreen: PrescreenResponse,
    candidate_rows: list[dict[str, Any]],
    compatibility_section: dict[str, Any] | None,
    compatibility_gaps: list[str],
) -> dict[str, Any]:
    known_gaps = list(compatibility_gaps)
    known_gaps.extend(
        f"source_missing:{row['unified_id']}" for row in candidate_rows if not row.get("source_url")
    )
    known_gaps.extend(
        f"deadline_missing:{row['unified_id']}"
        for row in candidate_rows
        if not row.get("application_deadline")
    )
    primary = candidate_rows[0] if candidate_rows else None
    compatibility_summary = (
        compatibility_section.get("summary") if isinstance(compatibility_section, dict) else None
    )
    artifact_type = "application_strategy_pack"
    artifact_id = _stable_artifact_id(
        artifact_type,
        {
            "request": request_payload,
            "program_ids": [row["unified_id"] for row in candidate_rows],
            "compatibility": compatibility_summary,
        },
    )
    sections: list[dict[str, Any]] = [
        {
            "section_id": "ranked_candidates",
            "title": "Ranked candidates",
            "rows": candidate_rows,
        },
        {
            "section_id": "application_questions",
            "title": "Application questions",
            "rows": _build_application_questions(candidate_rows),
        },
    ]
    if compatibility_section is not None:
        sections.append(compatibility_section)
    next_actions = _build_application_next_actions(candidate_rows, compatibility_section)
    human_review_required = [
        f"candidate_caveat:{row['unified_id']}" for row in candidate_rows if row.get("caveats")
    ]
    if compatibility_section:
        human_review_required.extend(compatibility_section.get("human_review_required") or [])
    return {
        "artifact_id": artifact_id,
        "artifact_type": artifact_type,
        "schema_version": "v1",
        "endpoint": "artifacts.application_strategy_pack",
        "summary": {
            "candidate_count": len(candidate_rows),
            "total_considered": prescreen.total_considered,
            "primary_candidate": primary["unified_id"] if primary else None,
            "primary_candidate_name": primary["primary_name"] if primary else None,
            "candidates_with_caveats": sum(1 for row in candidate_rows if row.get("caveats")),
            "compatibility_status": (compatibility_summary or {}).get("all_pairs_status"),
            "profile_echo": prescreen.profile_echo,
        },
        "sections": sections,
        "sources": _collect_sources({"sections": sections}),
        "known_gaps": sorted(set(known_gaps)),
        "next_actions": next_actions,
        "human_review_required": sorted(set(human_review_required)),
        "_disclaimer": (
            "本 artifact は公開データとルールエンジンに基づく申請戦略メモです。"
            "最終判断前に公募要領、対象経費、締切、併用制限、採択後義務を確認してください。"
        ),
    }


def _houjin_identity_exists(body: dict[str, Any]) -> bool:
    meta = body.get("houjin_meta")
    if isinstance(meta, dict) and meta:
        return True
    if body.get("adoption_history") or body.get("enforcement_records"):
        return True
    invoice = body.get("invoice_status")
    if isinstance(invoice, dict) and (invoice.get("registration_no") or invoice.get("registered")):
        return True
    peer = body.get("peer_summary")
    if isinstance(peer, dict) and peer.get("peer_count"):
        return True
    jurisdiction = body.get("jurisdiction_breakdown")
    if isinstance(jurisdiction, dict) and (
        jurisdiction.get("registered_pref")
        or jurisdiction.get("invoice_pref")
        or jurisdiction.get("operational_prefs")
    ):
        return True
    watch = body.get("watch_status")
    return bool(
        isinstance(watch, dict) and (watch.get("is_watched") or watch.get("last_amendment"))
    )


def _load_houjin_artifact_material(
    payload: HoujinDdPackRequest | CompanyPublicArtifactRequest,
    conn: Any,
) -> tuple[str, list[str], list[str], dict[str, Any]]:
    normalized = _normalize_houjin(payload.houjin_bangou)
    if normalized is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "error": "invalid_houjin_bangou",
                "field": "houjin_bangou",
                "message": "houjin_bangou must be 13 digits, with optional leading T.",
            },
        )

    requested_sections = _parse_include_sections(payload.include_sections)
    sections = list(requested_sections)
    if "meta" not in sections:
        sections.insert(0, "meta")
    am_conn = _open_autonomath_ro()
    try:
        houjin_body = _build_houjin_full(
            jpintel_conn=conn,
            am_conn=am_conn,
            houjin_id=normalized,
            sections=sections,
            max_per_section=payload.max_per_section,
        )
    finally:
        if am_conn is not None:
            with contextlib.suppress(Exception):
                am_conn.close()

    if _is_empty_response(houjin_body, sections) and not _houjin_identity_exists(houjin_body):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "houjin_not_found",
                "houjin_bangou": normalized,
                "message": "No public corporate DD data was found for this 法人番号.",
            },
        )
    return normalized, requested_sections, sections, houjin_body


def _company_request_payload(
    *,
    normalized: str,
    requested_sections: list[str],
    sections: list[str],
    max_per_section: int,
) -> dict[str, Any]:
    return {
        "houjin_bangou": normalized,
        "include_sections": requested_sections,
        "internal_sections": sections,
        "max_per_section": max_per_section,
    }


def _company_public_summary(houjin_body: dict[str, Any]) -> dict[str, Any]:
    meta = _houjin_meta(houjin_body)
    invoice = _invoice_status(houjin_body)
    watch = _watch_status(houjin_body)
    return {
        "houjin_bangou": houjin_body.get("houjin_bangou"),
        "company_name": meta.get("name"),
        "prefecture": meta.get("prefecture"),
        "address": meta.get("address"),
        "invoice_status": _risk_value(houjin_body, "invoice_status", "status"),
        "invoice_registration_no": invoice.get("registration_no"),
        "enforcement_record_count": len(_dict_rows(houjin_body, "enforcement_records")),
        "adoption_record_count": len(_dict_rows(houjin_body, "adoption_history")),
        "jurisdiction_status": _risk_value(houjin_body, "jurisdiction", "status"),
        "watch_status": "watched" if watch.get("is_watched") else "not_watched",
        "risk_flags": _houjin_risk_flags(houjin_body),
    }


def _company_identity_context(houjin_body: dict[str, Any]) -> dict[str, Any]:
    meta = _houjin_meta(houjin_body)
    return {
        "identity_confidence": "exact_houjin_bangou"
        if houjin_body.get("houjin_bangou")
        else "unknown",
        "houjin_bangou": houjin_body.get("houjin_bangou"),
        "company_name": meta.get("name"),
        "address": meta.get("address"),
        "prefecture": meta.get("prefecture"),
        "same_name_risk": "not_evaluated_by_this_artifact",
        "identity_note_ja": "法人番号で照合した公開情報です。会社名だけの同名法人検索結果ではありません。",
    }


def _company_benefit_angles(houjin_body: dict[str, Any]) -> list[dict[str, Any]]:
    angles: list[dict[str, Any]] = []
    invoice = _invoice_status(houjin_body)
    adoption_history = _dict_rows(houjin_body, "adoption_history")
    meta = _houjin_meta(houjin_body)
    if invoice.get("registered"):
        angles.append(
            {
                "angle_id": "invoice_registered_counterparty",
                "label_ja": "適格請求書発行事業者としての確認メモを作れる",
                "basis_fields": ["invoice_status"],
            }
        )
    if adoption_history:
        angles.append(
            {
                "angle_id": "public_support_history",
                "label_ja": "過去の採択・公的支援履歴を提案や稟議の文脈に使える",
                "basis_fields": ["adoption_history"],
            }
        )
    if meta.get("prefecture") or meta.get("jsic"):
        angles.append(
            {
                "angle_id": "regional_industry_program_screen",
                "label_ja": "所在地・業種を起点に制度候補の初回探索へ進める",
                "basis_fields": ["houjin_meta.prefecture", "houjin_meta.jsic"],
            }
        )
    if not angles:
        angles.append(
            {
                "angle_id": "first_hop_public_record_saved",
                "label_ja": "会社フォルダに公的確認の初回証跡を保存できる",
                "basis_fields": ["houjin_meta", "sources"],
            }
        )
    return angles


def _company_risk_angles(houjin_body: dict[str, Any]) -> list[dict[str, Any]]:
    angles: list[dict[str, Any]] = []
    risk_summary = _risk_summary(houjin_body)
    enforcement = risk_summary.get("enforcement") if isinstance(risk_summary, dict) else None
    if isinstance(enforcement, dict) and enforcement.get("status") == "detected":
        angles.append(
            {
                "angle_id": "public_enforcement_detected",
                "label_ja": "公表処分・改善命令等の原典確認が必要",
                "basis_fields": [
                    "enforcement_records",
                    "decision_support.risk_summary.enforcement",
                ],
            }
        )
    jurisdiction = risk_summary.get("jurisdiction") if isinstance(risk_summary, dict) else None
    if isinstance(jurisdiction, dict) and jurisdiction.get("status") == "mismatch":
        angles.append(
            {
                "angle_id": "jurisdiction_mismatch",
                "label_ja": "登記・インボイス・活動地域の不一致を確認する",
                "basis_fields": ["jurisdiction_breakdown"],
            }
        )
    if _houjin_known_gaps(houjin_body):
        angles.append(
            {
                "angle_id": "public_record_gap",
                "label_ja": "収録外・未取得の公的情報があるため、確認範囲を明記する",
                "basis_fields": ["known_gaps"],
            }
        )
    if not angles:
        angles.append(
            {
                "angle_id": "no_high_signal_public_risk_in_returned_sections",
                "label_ja": "返却範囲では強いリスク信号は薄いが、問題なしの証明ではない",
                "basis_fields": ["sections", "known_gaps"],
            }
        )
    return angles


def _company_questions_to_ask(houjin_body: dict[str, Any]) -> list[dict[str, Any]]:
    questions = [
        {
            "question_id": "confirm_identity",
            "question_ja": "この法人番号・商号・所在地が対象会社で間違いないですか。",
            "basis_fields": ["houjin_meta"],
        }
    ]
    if _invoice_status(houjin_body):
        questions.append(
            {
                "question_id": "confirm_invoice_status",
                "question_ja": "取引・請求で使う登録番号と現在のインボイス登録状態を確認してください。",
                "basis_fields": ["invoice_status"],
            }
        )
    if _dict_rows(houjin_body, "enforcement_records"):
        questions.append(
            {
                "question_id": "explain_public_enforcement",
                "question_ja": "公表処分等について、対象期間、原因、現在の解消状況を確認してください。",
                "basis_fields": ["enforcement_records"],
            }
        )
    if _dict_rows(houjin_body, "adoption_history"):
        questions.append(
            {
                "question_id": "confirm_public_support_history",
                "question_ja": "過去の採択・公的支援について、事業内容、入金時期、証憑の保存状況を確認してください。",
                "basis_fields": ["adoption_history"],
            }
        )
    return questions


def _company_folder_tasks(houjin_body: dict[str, Any]) -> list[dict[str, Any]]:
    tasks = [
        {
            "task_id": "save_public_baseline",
            "label_ja": "会社フォルダへ法人番号・商号・所在地・取得時点を保存する",
            "priority": "high",
            "basis_fields": ["summary", "corpus_snapshot_id"],
        },
        {
            "task_id": "save_source_receipts",
            "label_ja": "根拠URLと取得時点を証跡として保存する",
            "priority": "high",
            "basis_fields": ["source_receipts", "sources"],
        },
    ]
    if _houjin_known_gaps(houjin_body):
        tasks.append(
            {
                "task_id": "resolve_known_gaps",
                "label_ja": "known_gapsを相手先確認または追加調査で補う",
                "priority": "high",
                "basis_fields": ["known_gaps"],
            }
        )
    if _watch_status(houjin_body).get("is_watched"):
        tasks.append(
            {
                "task_id": "keep_watch_enabled",
                "label_ja": "公的情報の変更監視を継続する",
                "priority": "medium",
                "basis_fields": ["watch_status"],
            }
        )
    return tasks


def _company_watch_targets(houjin_body: dict[str, Any]) -> list[dict[str, Any]]:
    targets = [
        {
            "target_id": f"houjin:{houjin_body.get('houjin_bangou')}",
            "target_kind": "houjin",
            "reason_ja": "商号・所在地・登記由来の公開情報変更を追跡する。",
        }
    ]
    invoice = _invoice_status(houjin_body)
    if invoice.get("registration_no"):
        targets.append(
            {
                "target_id": invoice["registration_no"],
                "target_kind": "invoice_registration",
                "reason_ja": "適格請求書発行事業者登録の状態変更を確認する。",
            }
        )
    return targets


def _company_workflow_outputs(
    houjin_body: dict[str, Any],
    *,
    artifact_type: str,
) -> dict[str, str]:
    summary = _company_public_summary(houjin_body)
    name = summary.get("company_name") or summary.get("houjin_bangou") or "対象会社"
    gap_count = len(_houjin_known_gaps(houjin_body))
    source_count = len(_collect_sources(houjin_body))
    folder_readme = (
        f"{name} の公的情報初回確認メモです。法人番号、インボイス登録、"
        f"行政処分、採択履歴、所在地整合、監視状態を jpcite の公開情報で確認しました。"
        f"根拠URLは {source_count} 件、known_gaps は {gap_count} 件です。"
    )
    owner_questions = "\n".join(
        f"- {item['question_ja']}" for item in _company_questions_to_ask(houjin_body)
    )
    internal_note = (
        "このメモは公開情報の整理であり、取引可否、与信、監査意見、税務・法務判断を"
        "確定するものではありません。known_gaps と human_review_required を先に潰してください。"
    )
    if artifact_type == "company_public_audit_pack":
        internal_note = (
            "監査/DD調書へ転記する場合は、evidence_ledger/source_receipts/known_gaps/"
            "human_review_required を確認範囲として明記してください。"
        )
    return {
        "folder_readme": folder_readme,
        "owner_questions": owner_questions,
        "internal_review_note": internal_note,
    }


def _company_public_next_actions(houjin_body: dict[str, Any]) -> list[dict[str, Any]]:
    actions = list(_decision_support(houjin_body).get("next_actions") or [])
    actions.append(
        {
            "action_id": "verify_company_public_sources",
            "priority": "high",
            "message_ja": "法人番号、インボイス、行政処分、採択履歴の根拠URLを確認する。",
            "source_fields": ["sources", "sections"],
        }
    )
    if _houjin_known_gaps(houjin_body):
        actions.append(
            {
                "action_id": "resolve_company_known_gaps",
                "priority": "high",
                "message_ja": "known_gaps を一次資料または相手先確認で補う。",
                "source_fields": ["known_gaps"],
            }
        )
    return actions


def _build_company_public_baseline_artifact(
    houjin_body: dict[str, Any],
    *,
    request_payload: dict[str, Any],
) -> dict[str, Any]:
    meta = _houjin_meta(houjin_body)
    invoice = _invoice_status(houjin_body)
    enforcement_records = _dict_rows(houjin_body, "enforcement_records")
    adoption_history = _dict_rows(houjin_body, "adoption_history")
    risk_summary = _risk_summary(houjin_body)
    artifact_type = "company_public_baseline"
    return {
        "artifact_id": _stable_artifact_id(
            artifact_type,
            {"request": request_payload, "summary": _company_public_summary(houjin_body)},
        ),
        "artifact_type": artifact_type,
        "schema_version": "v1",
        "endpoint": "artifacts.company_public_baseline",
        "summary": _company_public_summary(houjin_body),
        "subject": _company_identity_context(houjin_body),
        "public_conditions": {
            "invoice_status": invoice,
            "enforcement_record_count": len(enforcement_records),
            "adoption_record_count": len(adoption_history),
            "jurisdiction": risk_summary.get("jurisdiction"),
        },
        "benefit_angles": _company_benefit_angles(houjin_body),
        "risk_angles": _company_risk_angles(houjin_body),
        "questions_to_ask": _company_questions_to_ask(houjin_body),
        "folder_tasks": _company_folder_tasks(houjin_body),
        "watch_targets": _company_watch_targets(houjin_body),
        "workflow_outputs": _company_workflow_outputs(
            houjin_body,
            artifact_type=artifact_type,
        ),
        "sections": [
            {
                "section_id": "company_identity",
                "title": "Company identity",
                "rows": [meta] if meta else [],
            },
            {
                "section_id": "registration_status",
                "title": "Registration status",
                "rows": [invoice] if invoice else [],
            },
            {
                "section_id": "public_signals",
                "title": "Public signals",
                "rows": [
                    {
                        "signal": "enforcement",
                        "summary": risk_summary.get("enforcement"),
                        "records": enforcement_records,
                    },
                    {"signal": "adoption_history", "records": adoption_history},
                    {"signal": "jurisdiction", "summary": risk_summary.get("jurisdiction")},
                ],
            },
            {
                "section_id": "data_gaps",
                "title": "Data gaps",
                "rows": _houjin_known_gaps(houjin_body),
            },
        ],
        "sources": _collect_sources(houjin_body),
        "known_gaps": _houjin_known_gaps(houjin_body),
        "next_actions": _company_public_next_actions(houjin_body),
        "human_review_required": _company_review_items(houjin_body),
        "_disclaimer": houjin_body.get("_disclaimer") or "",
    }


def _build_company_folder_brief_artifact(
    houjin_body: dict[str, Any],
    *,
    request_payload: dict[str, Any],
) -> dict[str, Any]:
    meta = _houjin_meta(houjin_body)
    risk_summary = _risk_summary(houjin_body)
    artifact_type = "company_folder_brief"
    return {
        "artifact_id": _stable_artifact_id(
            artifact_type,
            {"request": request_payload, "summary": _company_public_summary(houjin_body)},
        ),
        "artifact_type": artifact_type,
        "schema_version": "v1",
        "endpoint": "artifacts.company_folder_brief",
        "summary": _company_public_summary(houjin_body),
        "subject": _company_identity_context(houjin_body),
        "questions_to_ask": _company_questions_to_ask(houjin_body),
        "folder_tasks": _company_folder_tasks(houjin_body),
        "watch_targets": _company_watch_targets(houjin_body),
        "workflow_outputs": _company_workflow_outputs(
            houjin_body,
            artifact_type=artifact_type,
        ),
        "sections": [
            {
                "section_id": "brief_header",
                "title": "Brief header",
                "rows": [_company_public_summary(houjin_body)],
            },
            {
                "section_id": "company_profile",
                "title": "Company profile",
                "rows": [meta] if meta else [],
            },
            {
                "section_id": "diligence_snapshot",
                "title": "Diligence snapshot",
                "rows": [
                    {
                        "risk_summary": risk_summary,
                        "enforcement_records": _dict_rows(houjin_body, "enforcement_records"),
                        "invoice_status": _invoice_status(houjin_body),
                        "jurisdiction_breakdown": houjin_body.get("jurisdiction_breakdown") or {},
                    }
                ],
            },
            {
                "section_id": "folder_checklist",
                "title": "Folder checklist",
                "rows": _company_folder_tasks(houjin_body),
            },
        ],
        "sources": _collect_sources(houjin_body),
        "known_gaps": _houjin_known_gaps(houjin_body),
        "next_actions": _company_public_next_actions(houjin_body),
        "human_review_required": _company_review_items(houjin_body),
        "_disclaimer": houjin_body.get("_disclaimer") or "",
    }


def _build_company_public_audit_pack_artifact(
    houjin_body: dict[str, Any],
    *,
    request_payload: dict[str, Any],
) -> dict[str, Any]:
    sources = _collect_sources(houjin_body)
    known_gaps = _houjin_known_gaps(houjin_body)
    artifact_type = "company_public_audit_pack"
    return {
        "artifact_id": _stable_artifact_id(
            artifact_type,
            {
                "request": request_payload,
                "summary": _company_public_summary(houjin_body),
                "source_count": len(sources),
            },
        ),
        "artifact_type": artifact_type,
        "schema_version": "v1",
        "endpoint": "artifacts.company_public_audit_pack",
        "summary": _company_public_summary(houjin_body),
        "subject": _company_identity_context(houjin_body),
        "source_receipt_expectation": {
            "required_for_workpaper": True,
            "fields": ["source_url", "source_fetched_at", "content_hash", "license", "used_in"],
        },
        "mismatch_flags": _houjin_risk_flags(houjin_body),
        "questions_to_ask": _company_questions_to_ask(houjin_body),
        "folder_tasks": _company_folder_tasks(houjin_body),
        "workflow_outputs": _company_workflow_outputs(
            houjin_body,
            artifact_type=artifact_type,
        ),
        "sections": [
            {
                "section_id": "audit_subject",
                "title": "Audit subject",
                "rows": [_company_public_summary(houjin_body)],
            },
            {
                "section_id": "evidence_ledger",
                "title": "Evidence ledger",
                "rows": sources,
            },
            {
                "section_id": "risk_and_gap_register",
                "title": "Risk and gap register",
                "rows": [{"risk_flags": _houjin_risk_flags(houjin_body), "known_gaps": known_gaps}],
            },
            {
                "section_id": "review_controls",
                "title": "Review controls",
                "rows": _company_public_next_actions(houjin_body),
            },
        ],
        "sources": sources,
        "known_gaps": known_gaps,
        "next_actions": _company_public_next_actions(houjin_body),
        "human_review_required": _company_review_items(houjin_body),
        "_disclaimer": houjin_body.get("_disclaimer") or "",
    }


def _create_company_public_artifact(
    *,
    payload: CompanyPublicArtifactRequest,
    conn: Any,
    ctx: Any,
    artifact_type: str,
    builder: Any,
) -> dict[str, Any]:
    normalized, requested_sections, sections, houjin_body = _load_houjin_artifact_material(
        payload,
        conn,
    )
    request_payload = _company_request_payload(
        normalized=normalized,
        requested_sections=requested_sections,
        sections=sections,
        max_per_section=payload.max_per_section,
    )
    body = builder(houjin_body, request_payload=request_payload)
    endpoint = f"artifacts.{artifact_type}"
    attach_corpus_snapshot(body, conn)
    _refresh_artifact_id(body)
    _attach_common_artifact_envelope(body)
    _attach_billing_metadata(
        body,
        endpoint=endpoint,
        unit_type="artifact_call",
        quantity=1,
        result_count=len(sections),
        strict_metering=True,
        metered=ctx.metered,
        authenticated=ctx.key_hash is not None,
    )
    _finalize_artifact_usage_and_seal(
        body,
        conn=conn,
        ctx=ctx,
        endpoint=endpoint,
        params={
            "houjin_bangou_present": True,
            "section_count": len(sections),
            "max_per_section": payload.max_per_section,
        },
        quantity=1,
        result_count=len(sections),
    )
    return cast("dict[str, Any]", body)


@router.post(
    "/compatibility_table",
    response_model=ArtifactResponse,
    response_model_exclude_unset=True,
    summary="制度併用可否表 artifact (Compatibility Table — no LLM)",
    description=(
        "既存の funding stack rule engine を使い、制度併用可否を "
        "copy-paste-ready な artifact envelope として返す。既存 "
        "`/v1/funding_stack/check` のレスポンス形は変更しない。"
    ),
)
def create_compatibility_table(
    payload: FundingStackCheckRequest,
    conn: DbDep,
    ctx: ApiContextDep,
) -> dict[str, Any]:
    checker = _get_checker()
    result = checker.check_stack(payload.program_ids)
    if len(result.pairs) < 1:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "code": "too_few_unique_programs",
                "message": (
                    "併用可否の判定には重複を除いて 2 件以上の program_ids が必要です。"
                    "このリクエストは課金されません。"
                ),
            },
        )

    stack_body = result.to_dict()
    body = _build_compatibility_artifact(stack_body)
    quantity = len(result.pairs)
    attach_corpus_snapshot(body, conn)
    _refresh_artifact_id(body)
    _attach_common_artifact_envelope(body)
    _attach_billing_metadata(
        body,
        endpoint="artifacts.compatibility_table",
        unit_type="compatibility_pair",
        quantity=quantity,
        result_count=len(result.pairs),
        strict_metering=True,
        metered=ctx.metered,
        authenticated=ctx.key_hash is not None,
        pair_count=len(result.pairs),
    )
    _finalize_artifact_usage_and_seal(
        body,
        conn=conn,
        ctx=ctx,
        endpoint="artifacts.compatibility_table",
        params={
            "program_count": len(result.program_ids),
            "pair_count": len(result.pairs),
        },
        quantity=quantity,
        result_count=len(result.pairs),
    )
    return body


@router.post(
    "/application_strategy_pack",
    response_model=ArtifactResponse,
    response_model_exclude_unset=True,
    summary="制度申請 strategy pack artifact (prescreen + compatibility — no LLM)",
    description=(
        "既存 `/v1/programs/prescreen` の候補理由に、制度詳細、金額フィット、"
        "併用可否の一次スクリーニング、確認質問、次アクションを加え、"
        "申請戦略メモとしてそのまま使える artifact envelope にする。NO LLM。"
    ),
)
def create_application_strategy_pack(
    payload: ApplicationStrategyPackRequest,
    conn: DbDep,
    ctx: ApiContextDep,
) -> dict[str, Any]:
    if payload.profile.company_url:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "invalid_input", "message": "company_url must be empty."},
        )

    normalized_profile = _normalize_strategy_profile(payload.profile, payload.max_candidates)
    prescreen = run_prescreen(conn, normalized_profile)
    program_ids = [match.unified_id for match in prescreen.results]
    details = _fetch_program_details(conn, program_ids)
    candidate_rows = _build_strategy_candidate_rows(prescreen, details)
    _enrich_strategy_candidate_source_metadata(conn, candidate_rows)
    compatibility_section, compatibility_gaps = _build_program_compatibility_section(
        program_ids,
        min(payload.compatibility_top_n, payload.max_candidates),
    )
    request_payload = {
        "profile": normalized_profile.model_dump(),
        "max_candidates": payload.max_candidates,
        "compatibility_top_n": payload.compatibility_top_n,
    }
    body = _build_application_strategy_artifact(
        request_payload=request_payload,
        prescreen=prescreen,
        candidate_rows=candidate_rows,
        compatibility_section=compatibility_section,
        compatibility_gaps=compatibility_gaps,
    )
    attach_corpus_snapshot(body, conn)
    _refresh_artifact_id(body)
    _attach_common_artifact_envelope(body)
    _attach_billing_metadata(
        body,
        endpoint="artifacts.application_strategy_pack",
        unit_type="artifact_call",
        quantity=1,
        result_count=len(candidate_rows),
        strict_metering=True,
        metered=ctx.metered,
        authenticated=ctx.key_hash is not None,
    )
    _finalize_artifact_usage_and_seal(
        body,
        conn=conn,
        ctx=ctx,
        endpoint="artifacts.application_strategy_pack",
        params={
            "candidate_count": len(candidate_rows),
            "compatibility_top_n": payload.compatibility_top_n,
            "profile_fields": [
                key
                for key, value in normalized_profile.model_dump().items()
                if value not in (None, "", [], {})
            ],
        },
        quantity=1,
        result_count=len(candidate_rows),
    )
    return body


# ── R8 BUGHUNT 2026-05-07: parallel-agent merge residue ─────────────────────
# /v1/artifacts/{company_public_baseline,company_folder_brief,
# company_public_audit_pack} are now the always-on canonical surface in
# `jpintel_mcp.api.company_public_packs` (mounted unconditionally in
# `api/main.py`). Round 2 parallel agents shipped the same three routes here
# inside `artifacts.py`, which is gated behind AUTONOMATH_EXPERIMENTAL_API_ENABLED.
# When that flag is ON in production, FastAPI registers both copies and emits
# `Duplicate Operation ID` warnings (observed in tests/test_openapi_agent.py).
# The three blocks below are intentionally commented out — kept inline as
# audit residue per the destruction-free organization rule (no rm/mv). Builders
# `_build_company_public_baseline_artifact`, `_build_company_folder_brief_artifact`,
# and `_build_company_public_audit_pack_artifact` remain live; only the local
# `@router.post(...)` decorations are deactivated. To re-home them in this
# module, first remove `company_public_packs.py` from the always-on wiring.
# ─────────────────────────────────────────────────────────────────────────────
# @router.post(
#     "/company_public_baseline",
#     response_model=ArtifactResponse,
#     response_model_exclude_unset=True,
#     summary="会社 public baseline artifact (法人番号公開情報ベースライン — no LLM)",
#     description=(
#         "既存 `/v1/intel/houjin/{houjin_id}/full` と同じ公開情報素材を取得し、"
#         "会社の公開情報ベースライン、根拠URL、known gaps、次アクションを "
#         "artifact envelope として返す。NO LLM。"
#     ),
# )
# def create_company_public_baseline(
#     payload: CompanyPublicArtifactRequest,
#     conn: DbDep,
#     ctx: ApiContextDep,
# ) -> dict[str, Any]:
#     return _create_company_public_artifact(
#         payload=payload,
#         conn=conn,
#         ctx=ctx,
#         artifact_type="company_public_baseline",
#         builder=_build_company_public_baseline_artifact,
#     )
#
#
# @router.post(
#     "/company_folder_brief",
#     response_model=ArtifactResponse,
#     response_model_exclude_unset=True,
#     summary="会社 folder brief artifact (社内フォルダ用公開情報ブリーフ — no LLM)",
#     description=(
#         "既存 `/v1/intel/houjin/{houjin_id}/full` と同じ公開情報素材を取得し、"
#         "社内フォルダへ貼れる会社概要、DD snapshot、確認チェックリストを "
#         "artifact envelope として返す。NO LLM。"
#     ),
# )
# def create_company_folder_brief(
#     payload: CompanyPublicArtifactRequest,
#     conn: DbDep,
#     ctx: ApiContextDep,
# ) -> dict[str, Any]:
#     return _create_company_public_artifact(
#         payload=payload,
#         conn=conn,
#         ctx=ctx,
#         artifact_type="company_folder_brief",
#         builder=_build_company_folder_brief_artifact,
#     )
#
#
# @router.post(
#     "/company_public_audit_pack",
#     response_model=ArtifactResponse,
#     response_model_exclude_unset=True,
#     summary="会社 public audit pack artifact (公開根拠監査パック — no LLM)",
#     description=(
#         "既存 `/v1/intel/houjin/{houjin_id}/full` と同じ公開情報素材を取得し、"
#         "監査・レビュー向けの対象、根拠台帳、risk/gap register、review controls を "
#         "artifact envelope として返す。NO LLM。"
#     ),
# )
# def create_company_public_audit_pack(
#     payload: CompanyPublicArtifactRequest,
#     conn: DbDep,
#     ctx: ApiContextDep,
# ) -> dict[str, Any]:
#     return _create_company_public_artifact(
#         payload=payload,
#         conn=conn,
#         ctx=ctx,
#         artifact_type="company_public_audit_pack",
#         builder=_build_company_public_audit_pack_artifact,
#     )


@router.post(
    "/houjin_dd_pack",
    response_model=ArtifactResponse,
    response_model_exclude_unset=True,
    summary="法人DD pack artifact (public-source corporate diligence — no LLM)",
    description=(
        "法人番号・インボイス・行政処分・採択履歴などの公開情報名寄せ結果を、"
        "稟議・DDメモへ貼りやすい artifact envelope に変換する。法人番号、"
        "インボイス、行政処分、採択履歴、所在地整合、監視状態、known gaps、"
        "確認質問を1つの完成物として返す。NO LLM。"
    ),
)
def create_houjin_dd_pack(
    payload: HoujinDdPackRequest,
    conn: DbDep,
    ctx: ApiContextDep,
) -> dict[str, Any]:
    normalized, requested_sections, sections, houjin_body = _load_houjin_artifact_material(
        payload,
        conn,
    )
    request_payload = _company_request_payload(
        normalized=normalized,
        requested_sections=requested_sections,
        sections=sections,
        max_per_section=payload.max_per_section,
    )
    body = _build_houjin_dd_pack_artifact(
        houjin_body,
        sections=sections,
        request_payload=request_payload,
    )
    attach_corpus_snapshot(body, conn)
    _refresh_artifact_id(body)
    _attach_common_artifact_envelope(body)
    _attach_billing_metadata(
        body,
        endpoint="artifacts.houjin_dd_pack",
        unit_type="artifact_call",
        quantity=1,
        result_count=len(sections),
        strict_metering=True,
        metered=ctx.metered,
        authenticated=ctx.key_hash is not None,
    )
    _finalize_artifact_usage_and_seal(
        body,
        conn=conn,
        ctx=ctx,
        endpoint="artifacts.houjin_dd_pack",
        params={
            "houjin_bangou_present": True,
            "section_count": len(sections),
            "max_per_section": payload.max_per_section,
        },
        quantity=1,
        result_count=len(sections),
    )
    return body


__all__ = ["router"]
