"""Pure JGrants detail-response mapping helpers.

This module intentionally contains no fetch, CLI, or database-write path. It
normalizes a JGrants-like detail JSON object that has already been obtained by
some other layer into auditable structured facts.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import date, datetime
from fractions import Fraction
from typing import Any
from urllib.parse import urlparse

GOV_STANDARD_LICENSE = "gov_standard_v2.0"
NETWORK_FETCH_PERFORMED = False
DB_MUTATION_PERFORMED = False

_EMPTY_STRINGS = {"", "-", "ー", "なし", "無し", "null", "none", "n/a"}
_ZENKAKU_TRANS = str.maketrans(
    "０１２３４５６７８９，．／％：－",
    "0123456789,./%:-",
)

_DEADLINE_KEYS = (
    "applicationDeadline",
    "application_deadline",
    "deadline",
    "submissionDeadline",
    "submission_deadline",
    "acceptanceDeadline",
    "acceptance_deadline",
    "acceptanceEndDate",
    "acceptance_end_date",
    "applicationEndDate",
    "application_end_date",
    "receptionEndDate",
    "reception_end_date",
    "publicOfferingEndDate",
    "public_offering_end_date",
    "kouboEndDate",
    "koubo_end_date",
    "endDate",
    "end_date",
    "endAt",
    "end_at",
    "end",
    "申請期限",
    "応募締切",
    "受付終了日",
    "募集終了日",
)
_AMOUNT_KEYS = (
    "maxAmount",
    "max_amount",
    "maxAmountYen",
    "max_amount_yen",
    "amountMaxYen",
    "amount_max_yen",
    "amountMaxManYen",
    "amount_max_man_yen",
    "subsidyMaxAmount",
    "subsidy_max_amount",
    "subsidyUpperLimit",
    "subsidy_upper_limit",
    "upperLimitAmount",
    "upper_limit_amount",
    "hojyoJougenKingaku",
    "limitAmount",
    "limit_amount",
    "amount",
    "補助上限額",
    "上限額",
)
_RATE_KEYS = (
    "subsidyRate",
    "subsidy_rate",
    "subsidyRateText",
    "subsidy_rate_text",
    "rate",
    "rateText",
    "rate_text",
    "grantRate",
    "grant_rate",
    "補助率",
    "助成率",
)
_CONTACT_KEYS = (
    "contact",
    "contacts",
    "contactInfo",
    "contact_info",
    "contactInformation",
    "contact_information",
    "inquiry",
    "inquiries",
    "inquiryInfo",
    "inquiry_info",
    "supportDesk",
    "support_desk",
    "helpdesk",
    "office",
    "お問い合わせ",
    "問合せ",
    "問い合わせ先",
)
_DOC_KEYS = (
    "requiredDocuments",
    "required_documents",
    "requiredDocs",
    "required_docs",
    "submissionDocuments",
    "submission_documents",
    "documentsRequired",
    "documents_required",
    "documents",
    "attachments",
    "necessaryDocuments",
    "necessary_documents",
    "提出書類",
    "必要書類",
)
_SOURCE_URL_KEYS = (
    "sourceUrl",
    "source_url",
    "detailUrl",
    "detail_url",
    "publicUrl",
    "public_url",
    "jgrantsUrl",
    "jgrants_url",
    "pageUrl",
    "page_url",
    "url",
)
_SOURCE_ID_KEYS = (
    "sourceId",
    "source_id",
    "subsidyId",
    "subsidy_id",
    "jgrantsId",
    "jgrants_id",
    "businessId",
    "business_id",
    "projectId",
    "project_id",
    "id",
)
_PHONE_KEYS = (
    "phone",
    "phoneNumber",
    "phone_number",
    "tel",
    "telephone",
    "電話番号",
    "電話",
)
_EMAIL_KEYS = (
    "email",
    "emailAddress",
    "email_address",
    "mail",
    "mailAddress",
    "mail_address",
    "メール",
)
_ORG_KEYS = (
    "organizationName",
    "organization_name",
    "organization",
    "officeName",
    "office_name",
    "contactName",
    "contact_name",
    "name",
    "agency",
    "authority",
    "機関名",
    "事務局",
)
_DEPARTMENT_KEYS = (
    "department",
    "departmentName",
    "department_name",
    "section",
    "division",
    "担当部署",
    "部署",
)
_PERSON_KEYS = (
    "person",
    "personName",
    "person_name",
    "representative",
    "担当者",
)
_DOC_NAME_KEYS = (
    "documentName",
    "document_name",
    "docName",
    "doc_name",
    "formName",
    "form_name",
    "fileName",
    "file_name",
    "name",
    "title",
    "label",
)


def normalize_jgrants_detail_response(
    detail: Mapping[str, Any] | Any,
    *,
    source_url: str | None = None,
    source_id: str | None = None,
) -> dict[str, Any]:
    """Normalize one already-fetched JGrants-like detail JSON object.

    The function is deliberately total: malformed or sparse payloads produce
    facts with ``None``/empty values plus confidence and reason metadata rather
    than raising parser errors.
    """

    payload: Mapping[str, Any]
    payload_error: str | None = None
    if isinstance(detail, Mapping):
        payload = detail
    else:
        payload = {}
        payload_error = f"payload is not a JSON object: {type(detail).__name__}"

    resolved_source_id = _clean_scalar(source_id) or _extract_source_id(payload)
    facts = {
        "deadline": _extract_deadline(payload),
        "max_amount": _extract_max_amount(payload),
        "subsidy_rate": _extract_subsidy_rate(payload),
        "contact": _extract_contact(payload),
        "required_docs": _extract_required_docs(payload),
        "source_url": _extract_source_url(payload, explicit_url=source_url),
        "license": GOV_STANDARD_LICENSE,
        "source_id": resolved_source_id,
    }
    facts["confidence"] = _overall_confidence(facts)
    validation = validate_jgrants_detail_facts(facts)
    if payload_error:
        validation["errors"].insert(0, payload_error)
        validation["valid"] = False
    facts["validation"] = validation
    return facts


def validate_jgrants_detail_facts(mapped: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the normalized fact shape without side effects."""

    errors: list[str] = []
    warnings: list[str] = []

    if mapped.get("license") != GOV_STANDARD_LICENSE:
        errors.append("license must be gov_standard_v2.0")

    source_url = _field_value(mapped, "source_url", "url")
    if not source_url:
        errors.append("source_url is missing")
    elif not _is_http_url(str(source_url)):
        errors.append(f"source_url is not an absolute http(s) URL: {source_url!r}")

    deadline = _field_value(mapped, "deadline", "value")
    if deadline and not _is_iso_date(str(deadline)):
        errors.append(f"deadline is not ISO date: {deadline!r}")

    max_amount = _field_value(mapped, "max_amount", "yen")
    if max_amount is not None:
        try:
            if int(max_amount) <= 0:
                errors.append("max_amount.yen must be positive when present")
        except (TypeError, ValueError):
            errors.append(f"max_amount.yen is not an integer: {max_amount!r}")

    percent = _field_value(mapped, "subsidy_rate", "percent")
    if percent is not None:
        try:
            percent_float = float(percent)
        except (TypeError, ValueError):
            errors.append(f"subsidy_rate.percent is not numeric: {percent!r}")
        else:
            if not 0 < percent_float <= 100:
                errors.append("subsidy_rate.percent must be within 0..100")

    missing_optional = (
        ("deadline", "value"),
        ("max_amount", "yen"),
        ("subsidy_rate", "normalized"),
        ("contact", "raw"),
        ("required_docs", "items"),
    )
    for field_name, value_key in missing_optional:
        value = _field_value(mapped, field_name, value_key)
        if value in (None, "") or value == []:
            warnings.append(f"{field_name} not found")

    return {"valid": not errors, "errors": errors, "warnings": warnings}


def _extract_deadline(payload: Mapping[str, Any]) -> dict[str, Any]:
    candidate = _find_first(payload, _DEADLINE_KEYS)
    if candidate is None:
        return _fact(None, None, 0.0, "deadline key not found")

    path, raw = candidate
    value = _normalize_date(raw)
    if value is None:
        return _fact(None, raw, 0.25, f"found {path} but date could not be parsed")
    return _fact(value, raw, 0.9, f"found {path}")


def _extract_max_amount(payload: Mapping[str, Any]) -> dict[str, Any]:
    candidate = _find_first(payload, _AMOUNT_KEYS)
    if candidate is None:
        return {"yen": None, "raw": None, "confidence": 0.0, "reason": "max_amount key not found"}

    path, raw = candidate
    yen = _normalize_yen_amount(raw, path)
    if yen is None:
        return {
            "yen": None,
            "raw": raw,
            "confidence": 0.25,
            "reason": f"found {path} but amount could not be parsed",
        }
    return {"yen": yen, "raw": raw, "confidence": 0.88, "reason": f"found {path}"}


def _extract_subsidy_rate(payload: Mapping[str, Any]) -> dict[str, Any]:
    candidate = _find_first(payload, _RATE_KEYS)
    if candidate is None:
        return {
            "normalized": None,
            "percent": None,
            "raw": None,
            "confidence": 0.0,
            "reason": "subsidy_rate key not found",
        }

    path, raw = candidate
    normalized, percent = _normalize_rate(raw)
    if normalized is None and percent is None:
        return {
            "normalized": None,
            "percent": None,
            "raw": raw,
            "confidence": 0.25,
            "reason": f"found {path} but rate could not be parsed",
        }
    return {
        "normalized": normalized,
        "percent": percent,
        "raw": raw,
        "confidence": 0.88,
        "reason": f"found {path}",
    }


def _extract_contact(payload: Mapping[str, Any]) -> dict[str, Any]:
    candidate = _find_first(payload, _CONTACT_KEYS)
    if candidate is None:
        contact = _contact_from_scattered_fields(payload)
        if contact["raw"] is not None:
            contact["reason"] = "built from scattered contact fields"
            return contact
        return {
            "organization": None,
            "department": None,
            "person": None,
            "phone": None,
            "email": None,
            "raw": None,
            "confidence": 0.0,
            "reason": "contact key not found",
        }

    path, raw = candidate
    contact = _normalize_contact(raw)
    contact["reason"] = f"found {path}"
    return contact


def _extract_required_docs(payload: Mapping[str, Any]) -> dict[str, Any]:
    candidate = _find_first(payload, _DOC_KEYS)
    if candidate is None:
        return {
            "items": [],
            "raw": None,
            "confidence": 0.0,
            "reason": "required_docs key not found",
        }

    path, raw = candidate
    items = _normalize_required_docs(raw)
    confidence = 0.87 if items else 0.25
    reason = f"found {path}" if items else f"found {path} but no document names could be parsed"
    return {"items": items, "raw": raw, "confidence": confidence, "reason": reason}


def _extract_source_url(
    payload: Mapping[str, Any],
    *,
    explicit_url: str | None,
) -> dict[str, Any]:
    explicit = _clean_scalar(explicit_url)
    if explicit:
        confidence = 0.95 if _is_http_url(explicit) else 0.25
        return {
            "url": explicit,
            "raw": explicit_url,
            "confidence": confidence,
            "reason": "provided source_url argument",
        }

    candidate = _find_first(payload, _SOURCE_URL_KEYS)
    if candidate is None:
        return {"url": None, "raw": None, "confidence": 0.0, "reason": "source_url key not found"}

    path, raw = candidate
    url = _clean_scalar(raw)
    confidence = 0.95 if url and _is_http_url(url) else 0.25
    return {"url": url, "raw": raw, "confidence": confidence, "reason": f"found {path}"}


def _extract_source_id(payload: Mapping[str, Any]) -> str | None:
    candidate = _find_first(payload, _SOURCE_ID_KEYS)
    if candidate is None:
        return None
    return _clean_scalar(candidate[1])


def _contact_from_scattered_fields(payload: Mapping[str, Any]) -> dict[str, Any]:
    organization = _clean_scalar(_find_value(payload, _ORG_KEYS))
    department = _clean_scalar(_find_value(payload, _DEPARTMENT_KEYS))
    person = _clean_scalar(_find_value(payload, _PERSON_KEYS))
    phone = _clean_scalar(_find_value(payload, _PHONE_KEYS))
    email = _clean_scalar(_find_value(payload, _EMAIL_KEYS))
    raw_parts = [organization, department, person, phone, email]
    raw = " ".join(part for part in raw_parts if part) or None
    confidence = _contact_confidence(organization, department, person, phone, email)
    return {
        "organization": organization,
        "department": department,
        "person": person,
        "phone": phone,
        "email": email,
        "raw": raw,
        "confidence": confidence,
        "reason": "contact key not found",
    }


def _normalize_contact(raw: Any) -> dict[str, Any]:
    if isinstance(raw, list):
        for item in raw:
            if not _is_blank(item):
                return _normalize_contact(item)
        raw_text = None
        organization = department = person = phone = email = None
    elif isinstance(raw, Mapping):
        organization = _clean_scalar(_find_value(raw, _ORG_KEYS))
        department = _clean_scalar(_find_value(raw, _DEPARTMENT_KEYS))
        person = _clean_scalar(_find_value(raw, _PERSON_KEYS))
        phone = _clean_scalar(_find_value(raw, _PHONE_KEYS))
        email = _clean_scalar(_find_value(raw, _EMAIL_KEYS))
        raw_text = _to_text(raw)
        phone = phone or _extract_phone(raw_text)
        email = email or _extract_email(raw_text)
    else:
        raw_text = _clean_scalar(raw)
        organization = _guess_contact_label(raw_text)
        department = None
        person = None
        phone = _extract_phone(raw_text)
        email = _extract_email(raw_text)

    confidence = _contact_confidence(organization, department, person, phone, email)
    return {
        "organization": organization,
        "department": department,
        "person": person,
        "phone": phone,
        "email": email,
        "raw": raw,
        "confidence": confidence,
        "reason": "contact normalized",
    }


def _normalize_required_docs(raw: Any) -> list[str]:
    docs: list[str] = []
    if isinstance(raw, Mapping):
        nested = _find_value(raw, _DOC_NAME_KEYS)
        if nested is not None:
            docs.extend(_normalize_required_docs(nested))
        for value in raw.values():
            if isinstance(value, list):
                docs.extend(_normalize_required_docs(value))
    elif isinstance(raw, list):
        for item in raw:
            if isinstance(item, Mapping):
                name = _clean_scalar(_find_value(item, _DOC_NAME_KEYS))
                if name:
                    docs.append(name)
            else:
                text = _clean_scalar(item)
                if text:
                    docs.extend(_split_doc_text(text))
    else:
        text = _clean_scalar(raw)
        if text:
            docs.extend(_split_doc_text(text))

    return _dedupe(_clean_doc_name(doc) for doc in docs if _clean_doc_name(doc))


def _normalize_date(raw: Any) -> str | None:
    if isinstance(raw, datetime):
        return raw.date().isoformat()
    if isinstance(raw, date):
        return raw.isoformat()

    text = _to_text(raw).translate(_ZENKAKU_TRANS)
    if _is_blank(text):
        return None

    era_match = re.search(
        r"(令和|平成|昭和|大正|明治)\s*(元|\d+)年\s*(\d{1,2})月\s*(\d{1,2})日?", text
    )
    if era_match:
        era, year_text, month_text, day_text = era_match.groups()
        era_year = 1 if year_text == "元" else int(year_text)
        offsets = {"令和": 2018, "平成": 1988, "昭和": 1925, "大正": 1911, "明治": 1867}
        return _safe_iso_date(offsets[era] + era_year, int(month_text), int(day_text))

    western_match = re.search(r"(\d{4})[-/.年](\d{1,2})[-/.月](\d{1,2})", text)
    if western_match:
        year_text, month_text, day_text = western_match.groups()
        return _safe_iso_date(int(year_text), int(month_text), int(day_text))

    compact_match = re.search(r"\b(\d{4})(\d{2})(\d{2})\b", text)
    if compact_match:
        year_text, month_text, day_text = compact_match.groups()
        return _safe_iso_date(int(year_text), int(month_text), int(day_text))

    return None


def _normalize_yen_amount(raw: Any, path: str) -> int | None:
    if isinstance(raw, Mapping):
        unit_text = _to_text(_find_value(raw, ("unit", "unitName", "unit_name", "単位")))
        value = _find_value(raw, ("value", "amount", "max", "maxAmount", "max_amount", "text"))
        if value is None:
            return None
        return _normalize_yen_amount(value, f"{path}.{unit_text}")

    if isinstance(raw, int | float):
        multiplier = _amount_multiplier_from_path(path)
        return int(round(float(raw) * multiplier))

    text = _to_text(raw).translate(_ZENKAKU_TRANS)
    if _is_blank(text) or re.search(r"上限なし|制限なし|設定なし", text):
        return None

    compact = re.sub(r"[,\s]", "", text)
    oku_match = re.search(r"(\d+(?:\.\d+)?)億(?:(\d+(?:\.\d+)?)万?)?円?", compact)
    if oku_match:
        oku = float(oku_match.group(1)) * 100_000_000
        man = float(oku_match.group(2) or 0) * 10_000
        return int(round(oku + man))

    man_match = re.search(r"(\d+(?:\.\d+)?)万円", compact)
    if man_match:
        return int(round(float(man_match.group(1)) * 10_000))

    thousand_match = re.search(r"(\d+(?:\.\d+)?)千円", compact)
    if thousand_match:
        return int(round(float(thousand_match.group(1)) * 1_000))

    yen_match = re.search(r"(\d+(?:\.\d+)?)円", compact)
    if yen_match:
        return int(round(float(yen_match.group(1))))

    numeric_match = re.search(r"\b(\d+(?:\.\d+)?)\b", compact)
    if numeric_match:
        return int(round(float(numeric_match.group(1)) * _amount_multiplier_from_path(path)))

    return None


def _normalize_rate(raw: Any) -> tuple[str | None, float | None]:
    if isinstance(raw, Mapping):
        value = _find_value(raw, ("normalized", "value", "rate", "text", "label"))
        if value is None:
            return None, None
        return _normalize_rate(value)

    if isinstance(raw, int | float):
        numeric = float(raw)
        if 0 < numeric <= 1:
            fraction = Fraction(numeric).limit_denominator(20)
            return f"{fraction.numerator}/{fraction.denominator}", round(numeric * 100, 3)
        if 1 < numeric <= 100:
            fraction = Fraction(numeric / 100).limit_denominator(20)
            return f"{fraction.numerator}/{fraction.denominator}", round(numeric, 3)
        return None, None

    text = _to_text(raw).translate(_ZENKAKU_TRANS)
    if _is_blank(text):
        return None, None

    fraction_match = re.search(r"(\d+)\s*/\s*(\d+)", text)
    if fraction_match:
        numerator, denominator = (int(fraction_match.group(1)), int(fraction_match.group(2)))
        return _fraction_result(numerator, denominator)

    japanese_fraction_match = re.search(r"(\d+)分の(\d+)", text)
    if japanese_fraction_match:
        denominator = int(japanese_fraction_match.group(1))
        numerator = int(japanese_fraction_match.group(2))
        return _fraction_result(numerator, denominator)

    percent_match = re.search(r"(\d+(?:\.\d+)?)\s*%", text)
    if percent_match:
        percent = float(percent_match.group(1))
        if 0 < percent <= 100:
            fraction = Fraction(percent / 100).limit_denominator(20)
            return f"{fraction.numerator}/{fraction.denominator}", round(percent, 3)

    return None, None


def _fraction_result(numerator: int, denominator: int) -> tuple[str | None, float | None]:
    if numerator <= 0 or denominator <= 0:
        return None, None
    fraction = Fraction(numerator, denominator)
    percent = round(float(fraction) * 100, 3)
    if percent > 100:
        return None, None
    return f"{fraction.numerator}/{fraction.denominator}", percent


def _amount_multiplier_from_path(path: str) -> int:
    path_key = _normalize_key(path)
    if "manyen" in path_key or "万円" in path:
        return 10_000
    if "thousandyen" in path_key or "千円" in path:
        return 1_000
    return 1


def _find_value(payload: Mapping[str, Any], aliases: tuple[str, ...]) -> Any:
    candidate = _find_first(payload, aliases)
    if candidate is None:
        return None
    return candidate[1]


def _find_first(payload: Mapping[str, Any], aliases: tuple[str, ...]) -> tuple[str, Any] | None:
    alias_keys = tuple(_normalize_key(alias) for alias in aliases)
    flattened = list(_walk(payload))
    for alias_key in alias_keys:
        for path_parts, value in flattened:
            if _is_blank(value):
                continue
            if _normalize_key(path_parts[-1]) == alias_key:
                return ".".join(path_parts), value
    return None


def _walk(value: Any, path: tuple[str, ...] = ()) -> list[tuple[tuple[str, ...], Any]]:
    rows: list[tuple[tuple[str, ...], Any]] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            child_path = (*path, str(key))
            rows.append((child_path, child))
            rows.extend(_walk(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            child_path = (*path, str(index))
            rows.append((child_path, child))
            rows.extend(_walk(child, child_path))
    return rows


def _field_value(mapped: Mapping[str, Any], field_name: str, value_key: str) -> Any:
    value = mapped.get(field_name)
    if isinstance(value, Mapping):
        return value.get(value_key)
    return None


def _overall_confidence(facts: Mapping[str, Any]) -> float:
    fields = ("deadline", "max_amount", "subsidy_rate", "contact", "required_docs", "source_url")
    confidences: list[float] = []
    for field_name in fields:
        field = facts.get(field_name)
        if isinstance(field, Mapping):
            confidences.append(float(field.get("confidence", 0.0)))
    if not confidences:
        return 0.0
    return round(sum(confidences) / len(confidences), 3)


def _fact(value: str | None, raw: Any, confidence: float, reason: str) -> dict[str, Any]:
    return {"value": value, "raw": raw, "confidence": confidence, "reason": reason}


def _contact_confidence(
    organization: str | None,
    department: str | None,
    person: str | None,
    phone: str | None,
    email: str | None,
) -> float:
    present = sum(1 for value in (organization, department, person, phone, email) if value)
    if present >= 3:
        return 0.86
    if present >= 1 and (phone or email):
        return 0.72
    if present:
        return 0.45
    return 0.0


def _split_doc_text(text: str) -> list[str]:
    text = re.sub(r"(提出書類|必要書類|添付書類|書類)[:：]?", "\n", text)
    parts = re.split(r"[\n\r;；]+", text)
    if len(parts) == 1:
        parts = re.split(r"[、,]", text)
    return [part for part in parts if _clean_doc_name(part)]


def _clean_doc_name(text: str) -> str:
    cleaned = _to_text(text).strip()
    cleaned = re.sub(r"^[\s・\-*○●①-⑳\d０-９]+[.)．、\s]*", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ：:")
    return "" if _is_blank(cleaned) else cleaned


def _extract_phone(text: str | None) -> str | None:
    if not text:
        return None
    match = re.search(r"0\d{1,4}[-－]\d{1,4}[-－]\d{3,4}", text)
    if not match:
        return None
    return match.group(0).replace("－", "-")


def _extract_email(text: str | None) -> str | None:
    if not text:
        return None
    match = re.search(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", text)
    if not match:
        return None
    return match.group(0)


def _guess_contact_label(text: str | None) -> str | None:
    if not text:
        return None
    label = _extract_email(text)
    without_email = text.replace(label, "") if label else text
    phone = _extract_phone(without_email)
    without_phone = without_email.replace(phone, "") if phone else without_email
    cleaned = re.sub(r"\s+", " ", without_phone).strip(" :：")
    return cleaned or None


def _dedupe(values: Any) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        text = _clean_scalar(value)
        if text and text not in seen:
            seen.add(text)
            out.append(text)
    return out


def _clean_scalar(value: Any) -> str | None:
    if isinstance(value, str):
        text = value.strip()
    elif isinstance(value, int | float):
        text = str(value)
    else:
        return None
    return None if _is_blank(text) else text


def _to_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, int | float):
        return str(value)
    if isinstance(value, Mapping):
        return " ".join(_to_text(child) for child in value.values() if not _is_blank(child))
    if isinstance(value, list):
        return " ".join(_to_text(child) for child in value if not _is_blank(child))
    return str(value).strip()


def _is_blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip().casefold() in _EMPTY_STRINGS
    if isinstance(value, Mapping | list):
        return len(value) == 0
    return False


def _normalize_key(key: str) -> str:
    return re.sub(r"[\s_\-./()[\]{}（）:：]+", "", key).casefold()


def _safe_iso_date(year: int, month: int, day: int) -> str | None:
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None


def _is_iso_date(value: str) -> bool:
    return _safe_iso_date_from_match(re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", value))


def _safe_iso_date_from_match(match: re.Match[str] | None) -> bool:
    if match is None:
        return False
    return _safe_iso_date(int(match.group(1)), int(match.group(2)), int(match.group(3))) is not None


def _is_http_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


__all__ = [
    "DB_MUTATION_PERFORMED",
    "GOV_STANDARD_LICENSE",
    "NETWORK_FETCH_PERFORMED",
    "normalize_jgrants_detail_response",
    "validate_jgrants_detail_facts",
]
