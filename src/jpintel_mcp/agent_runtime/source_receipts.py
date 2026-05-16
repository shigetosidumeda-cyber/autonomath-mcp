"""Pure source-receipt contract helpers for P0 packet shapes.

This module checks already-built packet dictionaries. It does not fetch,
hydrate, score, or summarize sources; it only proves that public claims are
explicitly tied to source receipts or represented as known gaps.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Literal

SOURCE_RECEIPT_LEDGER_SCHEMA_VERSION = "jpcite.source_receipt_ledger.p0.v1"
DEFAULT_OBSERVED_AT = "2026-05-15T00:00:00+09:00"

REQUIRED_CLAIM_FIELDS = (
    "claim_id",
    "text",
    "visibility",
    "support_state",
    "receipt_ids",
)
REQUIRED_RECEIPT_FIELDS = (
    "receipt_id",
    "source_family_id",
    "source_url",
    "observed_at",
    "access_method",
    "support_state",
)
REQUIRED_GAP_FIELDS = ("gap_id", "gap_type", "gap_status", "explanation")
PUBLIC_CLAIM_VISIBILITY = "public"
SUPPORTED_CLAIM_STATE = "supported"
GAP_CLAIM_STATE = "gap"
DIRECT_RECEIPT_STATE = "direct"
GAP_RECEIPT_STATE = "gap"

IssueSeverity = Literal["low", "medium", "high"]


def public_claim(
    claim_id: str,
    text: str,
    receipt_ids: tuple[str, ...],
    *,
    visibility: str = PUBLIC_CLAIM_VISIBILITY,
    support_state: str = SUPPORTED_CLAIM_STATE,
) -> dict[str, Any]:
    """Build the public claim shape used by P0 packet skeletons."""

    claim = {
        "claim_id": claim_id,
        "text": text,
        "visibility": visibility,
        "support_state": support_state,
        "receipt_ids": list(receipt_ids),
    }
    issues = source_receipt_contract_issues(
        {
            "outcome_contract_id": "claim_shape_check",
            "claims": [claim],
            "source_receipts": [
                source_receipt(receipt_id, "placeholder_source", "metadata:shape-check")
                for receipt_id in receipt_ids
            ],
            "known_gaps": [known_gap("gap_shape_check", "shape_check", "shape check")],
        }
    )
    if issues:
        raise ValueError(f"invalid public claim: {issues[0]['code']}")
    return claim


def source_receipt(
    receipt_id: str,
    source_family_id: str,
    source_url: str,
    *,
    observed_at: str = DEFAULT_OBSERVED_AT,
    access_method: str = "metadata_only",
    support_state: str = DIRECT_RECEIPT_STATE,
) -> dict[str, str]:
    """Build the source receipt shape used by P0 packet skeletons."""

    receipt = {
        "receipt_id": receipt_id,
        "source_family_id": source_family_id,
        "source_url": source_url,
        "observed_at": observed_at,
        "access_method": access_method,
        "support_state": support_state,
    }
    missing = [field for field in REQUIRED_RECEIPT_FIELDS if not _has_value(receipt[field])]
    if missing:
        raise ValueError(f"source receipt missing required field: {missing[0]}")
    return receipt


def known_gap(
    gap_id: str,
    gap_type: str,
    explanation: str,
    *,
    gap_status: str = "known_gap",
) -> dict[str, str]:
    """Build the known gap shape used by P0 packet skeletons."""

    gap = {
        "gap_id": gap_id,
        "gap_type": gap_type,
        "gap_status": gap_status,
        "explanation": explanation,
    }
    missing = [field for field in REQUIRED_GAP_FIELDS if not _has_value(gap[field])]
    if missing:
        raise ValueError(f"known gap missing required field: {missing[0]}")
    return gap


def assert_claim_receipt_links(
    claims: Sequence[Mapping[str, Any]],
    source_receipts: Sequence[Mapping[str, Any]],
) -> None:
    """Raise when claims refer to unknown or duplicated receipt IDs."""

    receipt_ids = [_text(receipt.get("receipt_id")) for receipt in source_receipts]
    duplicate_ids = sorted(
        {receipt_id for receipt_id in receipt_ids if receipt_ids.count(receipt_id) > 1}
    )
    if duplicate_ids:
        raise ValueError(f"duplicate source receipt id: {duplicate_ids[0]}")
    known_receipt_ids = set(receipt_ids)
    for claim in claims:
        claim_id = _text(claim.get("claim_id")) or "unknown_claim"
        for receipt_id in _string_list(claim.get("receipt_ids")):
            if receipt_id not in known_receipt_ids:
                raise ValueError(f"unknown source receipt id for {claim_id}: {receipt_id}")


def build_source_receipt_ledger(packet: Mapping[str, Any]) -> dict[str, Any]:
    """Return a deterministic receipt ledger and contract report for a packet."""

    claims = _records(packet.get("claims"))
    receipts = _records(packet.get("source_receipts"))
    known_gaps = _records(packet.get("known_gaps"))
    receipt_ids = _receipt_ids(receipts)
    gap_ids = _gap_ids(known_gaps)
    issues: list[dict[str, Any]] = []

    _append_shape_issues(issues, "claim", claims, REQUIRED_CLAIM_FIELDS)
    _append_shape_issues(issues, "source_receipt", receipts, REQUIRED_RECEIPT_FIELDS)
    _append_shape_issues(issues, "known_gap", known_gaps, REQUIRED_GAP_FIELDS)
    _append_duplicate_id_issues(issues, "source_receipt", receipts, "receipt_id")
    _append_duplicate_id_issues(issues, "known_gap", known_gaps, "gap_id")

    claim_graph: list[dict[str, Any]] = []
    for index, claim in enumerate(claims):
        claim_id = _text(claim.get("claim_id")) or f"claim_index_{index}"
        claim_receipt_ids = _string_list(claim.get("receipt_ids"))
        missing_receipt_ids = [
            receipt_id for receipt_id in claim_receipt_ids if receipt_id not in receipt_ids
        ]
        support_state = _text(claim.get("support_state"))
        visibility = _text(claim.get("visibility"))
        gap_statement_allowed = (
            support_state == GAP_CLAIM_STATE and bool(claim_receipt_ids) and not missing_receipt_ids
        )
        public_claim_export_allowed = (
            visibility == PUBLIC_CLAIM_VISIBILITY
            and support_state == SUPPORTED_CLAIM_STATE
            and bool(claim_receipt_ids)
            and not missing_receipt_ids
        )
        if not claim_receipt_ids:
            issues.append(
                _issue(
                    code="claim_missing_receipt_ids",
                    severity="high",
                    subject_type="claim",
                    subject_id=claim_id,
                    message="public claim has no source receipt ids",
                )
            )
        if missing_receipt_ids:
            issues.append(
                _issue(
                    code="claim_unknown_receipt_id",
                    severity="high",
                    subject_type="claim",
                    subject_id=claim_id,
                    message="claim references receipt ids not present in source_receipts",
                    missing_receipt_ids=missing_receipt_ids,
                )
            )
        if visibility != PUBLIC_CLAIM_VISIBILITY:
            issues.append(
                _issue(
                    code="claim_not_public_visibility",
                    severity="high",
                    subject_type="claim",
                    subject_id=claim_id,
                    message="P0 packet skeleton claims must be public or omitted",
                )
            )
        if support_state == GAP_CLAIM_STATE and not gap_ids:
            issues.append(
                _issue(
                    code="gap_claim_without_known_gap",
                    severity="medium",
                    subject_type="claim",
                    subject_id=claim_id,
                    message="gap-state claim should be accompanied by a known gap",
                )
            )

        claim_graph.append(
            {
                "claim_id": claim_id,
                "receipt_ids": claim_receipt_ids,
                "missing_receipt_ids": missing_receipt_ids,
                "support_state": support_state,
                "visibility": visibility,
                "public_claim_export_allowed": public_claim_export_allowed,
                "gap_statement_allowed": gap_statement_allowed,
            }
        )

    receipt_inventory = []
    for index, receipt in enumerate(receipts):
        receipt_id = _text(receipt.get("receipt_id")) or f"receipt_index_{index}"
        support_state = _text(receipt.get("support_state"))
        if support_state not in {DIRECT_RECEIPT_STATE, GAP_RECEIPT_STATE}:
            issues.append(
                _issue(
                    code="receipt_unknown_support_state",
                    severity="medium",
                    subject_type="source_receipt",
                    subject_id=receipt_id,
                    message="source receipt support_state is not a recognized P0 value",
                )
            )
        receipt_inventory.append(
            {
                "receipt_id": receipt_id,
                "source_family_id": _text(receipt.get("source_family_id")),
                "source_url": _text(receipt.get("source_url")),
                "support_state": support_state,
                "claim_ids": [
                    edge["claim_id"] for edge in claim_graph if receipt_id in edge["receipt_ids"]
                ],
            }
        )

    no_hit = packet.get("no_hit_semantics")
    absence_claim_enabled = (
        bool(no_hit.get("absence_claim_enabled")) if isinstance(no_hit, Mapping) else False
    )
    if absence_claim_enabled:
        issues.append(
            _issue(
                code="absence_claim_enabled",
                severity="high",
                subject_type="no_hit_semantics",
                subject_id="no_hit_semantics",
                message="P0 no-hit semantics cannot enable absence claims",
            )
        )

    return {
        "schema_version": SOURCE_RECEIPT_LEDGER_SCHEMA_VERSION,
        "outcome_contract_id": _text(packet.get("outcome_contract_id")),
        "claim_count": len(claims),
        "source_receipt_count": len(receipts),
        "known_gap_count": len(known_gaps),
        "public_claims_release_allowed": not any(issue["severity"] == "high" for issue in issues),
        "claim_graph": claim_graph,
        "receipt_inventory": receipt_inventory,
        "known_gap_ids": sorted(gap_ids),
        "issues": issues,
        "no_hit_semantics": packet.get("no_hit_semantics"),
    }


def source_receipt_contract_issues(packet: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
    """Return receipt contract issues for callers that only need validation."""

    return tuple(build_source_receipt_ledger(packet)["issues"])


def source_receipt_contract_passed(packet: Mapping[str, Any]) -> bool:
    """Return whether every public claim has acceptable receipt backing."""

    return not source_receipt_contract_issues(packet)


def _records(value: Any) -> list[Mapping[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _append_shape_issues(
    issues: list[dict[str, Any]],
    subject_type: str,
    records: list[Mapping[str, Any]],
    required_fields: tuple[str, ...],
) -> None:
    if not records:
        issues.append(
            _issue(
                code=f"{subject_type}_missing",
                severity="high",
                subject_type=subject_type,
                subject_id=subject_type,
                message=f"{subject_type} records are required",
            )
        )
        return
    for index, record in enumerate(records):
        subject_id = (
            _text(record.get("claim_id") or record.get("receipt_id") or record.get("gap_id"))
            or f"{subject_type}_index_{index}"
        )
        for field in required_fields:
            if _has_value(record.get(field)):
                continue
            issues.append(
                _issue(
                    code=f"{subject_type}_missing_{field}",
                    severity="high",
                    subject_type=subject_type,
                    subject_id=subject_id,
                    message=f"{subject_type} is missing required field {field}",
                )
            )


def _append_duplicate_id_issues(
    issues: list[dict[str, Any]],
    subject_type: str,
    records: list[Mapping[str, Any]],
    id_field: str,
) -> None:
    seen: set[str] = set()
    for record in records:
        record_id = _text(record.get(id_field))
        if not record_id:
            continue
        if record_id in seen:
            issues.append(
                _issue(
                    code=f"duplicate_{id_field}",
                    severity="high",
                    subject_type=subject_type,
                    subject_id=record_id,
                    message=f"duplicate {id_field} in packet",
                )
            )
        seen.add(record_id)


def _receipt_ids(receipts: list[Mapping[str, Any]]) -> set[str]:
    return {
        _text(receipt.get("receipt_id")) for receipt in receipts if _text(receipt.get("receipt_id"))
    }


def _gap_ids(known_gaps: list[Mapping[str, Any]]) -> set[str]:
    return {_text(gap.get("gap_id")) for gap in known_gaps if _text(gap.get("gap_id"))}


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [_text(item) for item in value if _text(item)]


def _has_value(value: Any) -> bool:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return bool(value)
    return bool(_text(value))


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _issue(
    *,
    code: str,
    severity: IssueSeverity,
    subject_type: str,
    subject_id: str,
    message: str,
    **extra: Any,
) -> dict[str, Any]:
    issue = {
        "code": code,
        "severity": severity,
        "subject_type": subject_type,
        "subject_id": subject_id,
        "message": message,
    }
    issue.update(extra)
    return issue


__all__ = [
    "DIRECT_RECEIPT_STATE",
    "DEFAULT_OBSERVED_AT",
    "GAP_CLAIM_STATE",
    "GAP_RECEIPT_STATE",
    "PUBLIC_CLAIM_VISIBILITY",
    "REQUIRED_CLAIM_FIELDS",
    "REQUIRED_GAP_FIELDS",
    "REQUIRED_RECEIPT_FIELDS",
    "SOURCE_RECEIPT_LEDGER_SCHEMA_VERSION",
    "SUPPORTED_CLAIM_STATE",
    "assert_claim_receipt_links",
    "build_source_receipt_ledger",
    "known_gap",
    "public_claim",
    "source_receipt",
    "source_receipt_contract_issues",
    "source_receipt_contract_passed",
]
