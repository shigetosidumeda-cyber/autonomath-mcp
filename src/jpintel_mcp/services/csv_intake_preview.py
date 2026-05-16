"""Pure accounting CSV intake preview helpers.

This module parses caller-supplied CSV content only to compute an aggregate
preview. It must not persist raw rows, echo raw cell values, call networks, use
AWS, or create public source receipts from private CSV content.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import unicodedata
from typing import Any

from jpintel_mcp.agent_runtime.accounting_csv_profiles import (
    BLOCKED_PUBLIC_OUTPUTS,
    CERTIFICATION_NOTICE,
    GROUNDING_RULES,
    build_downstream_output_contract,
    detect_accounting_csv_profile,
    evaluate_accounting_csv_headers,
    summarize_period_coverage,
)

SCHEMA_VERSION = "jpcite.accounting_csv_intake_preview.p0.v1"
MAX_PREVIEW_ROWS = 10000
PAYROLL_OR_BANK_HEADER_TERMS = (
    "bank",
    "accountnumber",
    "address",
    "email",
    "phone",
    "employee",
    "payroll",
    "salary",
    "iban",
    "swift",
    "銀行",
    "口座",
    "住所",
    "メール",
    "電話",
    "従業員",
    "給与",
    "給料",
    "賞与",
    "個人番号",
    "マイナンバー",
)
FORMULA_PREFIXES = ("=", "+", "-", "@")


def preview_accounting_csv_text(
    csv_text: str,
    *,
    filename: str | None = None,
    max_preview_rows: int = MAX_PREVIEW_ROWS,
) -> dict[str, Any]:
    """Return a no-raw-values preview for accounting CSV content."""

    rows, parse_warnings = _parse_csv_text(csv_text, max_preview_rows=max_preview_rows)
    headers = tuple(rows[0]) if rows else ()
    data_rows = rows[1:] if rows else []
    normalized_headers = tuple(_normalize_header(header) for header in headers)
    header_hash = _hash_json(normalized_headers)
    detection = detect_accounting_csv_profile(headers)
    profile_key = detection.profile_key

    header_evaluation = None
    period_coverage = None
    downstream_contract = None
    if profile_key is not None:
        header_evaluation = evaluate_accounting_csv_headers(profile_key, headers).to_dict()
        period_rows = _rows_as_header_dicts(headers, data_rows)
        period_coverage = summarize_period_coverage(profile_key, period_rows).to_dict()
        downstream_contract = build_downstream_output_contract(profile_key, headers).to_dict()

    sensitive_headers = _sensitive_headers(headers)
    formula_like_cell_count = _formula_like_cell_count(data_rows)
    row_count = len(data_rows)
    column_count = len(headers)
    accepted_for_private_overlay = (
        profile_key is not None
        and not sensitive_headers
        and not (header_evaluation or {}).get("missing_required_fields")
    )
    blocked_reason_codes = []
    if profile_key is None:
        blocked_reason_codes.append("csv_provider_unknown_or_ambiguous")
    if sensitive_headers:
        blocked_reason_codes.append("payroll_or_bank_rejected")
    if (header_evaluation or {}).get("missing_required_fields"):
        blocked_reason_codes.append("csv_mapping_required")
    if formula_like_cell_count:
        blocked_reason_codes.append("csv_formula_escaped")
    if row_count > max_preview_rows:
        blocked_reason_codes.append("csv_preview_row_limit_exceeded")

    return {
        "schema_version": SCHEMA_VERSION,
        "status": "preview_ready" if accepted_for_private_overlay else "blocked_or_limited",
        "billable": False,
        "charge_status": "not_charged",
        "accepted_artifact_created": False,
        "raw_csv_retained": False,
        "raw_csv_logged": False,
        "raw_rows_returned": False,
        "raw_cell_values_returned": False,
        "public_source_receipt_compatible": False,
        "public_claim_support": False,
        "official_certification_claimed": False,
        "certification_notice": CERTIFICATION_NOTICE,
        "filename_present": bool((filename or "").strip()),
        "file_label_hash": _hash_text(filename or "") if filename else None,
        "row_count": row_count,
        "column_count": column_count,
        "header_fingerprint_hash": header_hash,
        "normalized_header_keys": list(normalized_headers),
        "profile_detection": detection.to_dict(),
        "header_evaluation": header_evaluation,
        "period_coverage": period_coverage
        or {
            "mode": "unknown",
            "period_start": None,
            "period_end": None,
            "evidence_fields": (),
            "limitation": "Period cannot be summarized until a provider profile is detected.",
        },
        "privacy_review": {
            "sensitive_header_count": len(sensitive_headers),
            "sensitive_header_hashes": [_hash_text(header) for header in sensitive_headers],
            "formula_like_cell_count": formula_like_cell_count,
            "formula_like_cell_count_bucket": _count_bucket(formula_like_cell_count),
            "payroll_or_bank_rejected": bool(sensitive_headers),
            "private_input_minimized": True,
        },
        "downstream_contract": downstream_contract
        or {
            "allowed_downstream_outputs": (),
            "blocked_downstream_outputs": BLOCKED_PUBLIC_OUTPUTS,
            "grounding_rules": GROUNDING_RULES,
            "public_claim_support": False,
            "source_receipt_compatible": False,
            "row_level_export_allowed_without_consent": False,
            "official_certification_claimed": False,
        },
        "routing": {
            "recommended_outcome_contract_ids": (
                [
                    "csv_overlay_public_check",
                    "cashbook_csv_subsidy_fit_screen",
                ]
                if accepted_for_private_overlay
                else []
            ),
            "requires_user_csv_consent": True,
            "requires_accepted_artifact_before_charge": True,
            "preview_only": True,
        },
        "known_gaps": tuple(blocked_reason_codes),
        "parse_warnings": tuple(parse_warnings),
        "no_hit_semantics": {
            "mode": "no_hit_not_absence",
            "absence_claim_enabled": False,
        },
    }


def preview_accounting_csv_bytes(
    csv_bytes: bytes,
    *,
    filename: str | None = None,
    max_preview_rows: int = MAX_PREVIEW_ROWS,
) -> dict[str, Any]:
    """Decode bytes conservatively and return a no-raw-values preview."""

    text, encoding = _decode_csv_bytes(csv_bytes)
    preview = preview_accounting_csv_text(
        text,
        filename=filename,
        max_preview_rows=max_preview_rows,
    )
    preview["decoded_encoding"] = encoding
    return preview


def _decode_csv_bytes(value: bytes) -> tuple[str, str]:
    for encoding in ("utf-8-sig", "cp932", "shift_jis"):
        try:
            return value.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    return value.decode("utf-8", errors="replace"), "utf-8-replace"


def _parse_csv_text(
    csv_text: str,
    *,
    max_preview_rows: int,
) -> tuple[list[tuple[str, ...]], list[str]]:
    warnings: list[str] = []
    normalized_text = csv_text.lstrip("\ufeff")
    reader = csv.reader(io.StringIO(normalized_text))
    rows: list[tuple[str, ...]] = []
    width = None
    for index, row in enumerate(reader):
        if index > max_preview_rows:
            warnings.append("csv_preview_row_limit_exceeded")
            break
        cleaned = tuple(_clean_header_or_cell(value) for value in row)
        if index == 0:
            width = len(cleaned)
        elif width is not None and len(cleaned) != width:
            warnings.append("csv_ragged_row_detected")
        rows.append(cleaned)
    if not rows:
        warnings.append("csv_empty")
    elif not any(rows[0]):
        warnings.append("csv_header_empty")
    return rows, warnings


def _rows_as_header_dicts(
    headers: tuple[str, ...],
    rows: list[tuple[str, ...]],
) -> list[dict[str, object]]:
    output: list[dict[str, object]] = []
    for row in rows:
        padded = (*row, *("" for _ in range(max(0, len(headers) - len(row)))))
        output.append(dict(zip(headers, padded, strict=False)))
    return output


def _formula_like_cell_count(rows: list[tuple[str, ...]]) -> int:
    count = 0
    for row in rows:
        for value in row:
            text = str(value).lstrip()
            if text.startswith(FORMULA_PREFIXES):
                count += 1
    return count


def _sensitive_headers(headers: tuple[str, ...]) -> tuple[str, ...]:
    sensitive = []
    for header in headers:
        normalized = _normalize_header(header)
        if any(term in normalized for term in PAYROLL_OR_BANK_HEADER_TERMS):
            sensitive.append(header)
    return tuple(sensitive)


def _normalize_header(header: object) -> str:
    text = unicodedata.normalize("NFKC", str(header)).strip().lower()
    return "".join(text.split())


def _clean_header_or_cell(value: object) -> str:
    return unicodedata.normalize("NFKC", str(value)).strip()


def _hash_text(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _hash_json(value: object) -> str:
    raw = json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return _hash_text(raw)


def _count_bucket(value: int) -> str:
    if value == 0:
        return "0"
    if value <= 9:
        return "1-9"
    if value <= 99:
        return "10-99"
    return "100+"


__all__ = [
    "MAX_PREVIEW_ROWS",
    "SCHEMA_VERSION",
    "preview_accounting_csv_bytes",
    "preview_accounting_csv_text",
]
