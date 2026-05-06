"""Pure helpers for surfacing honest quality gaps.

This module deliberately has no API/MCP wiring and no network or LLM calls. It
turns already-collected evidence/source/fact metadata into a deterministic
``known_gaps`` list that callers can attach to richer response payloads later.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import UTC, date, datetime
from typing import Any

DEFAULT_STALE_AFTER_DAYS = 180

UNKNOWN_LICENSE_VALUES: frozenset[str] = frozenset(
    {
        "",
        "none",
        "null",
        "unknown",
        "unlicensed",
        "unspecified",
    }
)
BLOCKED_LICENSE_VALUES: frozenset[str] = frozenset(
    {
        "blocked",
        "copyright_blocked",
        "license_blocked",
        "not_redistributable",
        "proprietary",
        "restricted",
    }
)

REQUIRED_FACT_ALIASES: dict[str, tuple[str, ...]] = {
    "deadline": (
        "application_deadline",
        "deadline",
        "deadline_date",
        "end_date",
    ),
    "amount": (
        "amount",
        "amount_max_man_yen",
        "amount_max_yen",
        "amount_yen",
        "grant_amount_max_yen",
        "loan_amount_max_yen",
        "max_amount_yen",
    ),
    "contact": (
        "contact",
        "contact_email",
        "contact_phone",
        "contacts",
        "contacts_v3",
        "inquiry_contact",
    ),
}

_FACT_VALUE_KEYS = (
    "field_value_text",
    "field_value_numeric",
    "field_value_json",
    "value",
    "display_value",
    "normalized_value",
)


def build_known_gaps(
    *,
    evidence: Iterable[Mapping[str, Any]] | Mapping[str, Any] | None = None,
    facts: Iterable[Mapping[str, Any]] | Mapping[str, Any] | None = None,
    conflict_metadata: Mapping[str, Any] | None = None,
    as_of: date | datetime | str | None = None,
    stale_after_days: int = DEFAULT_STALE_AFTER_DAYS,
    required_fact_aliases: Mapping[str, Iterable[str]] = REQUIRED_FACT_ALIASES,
) -> list[dict[str, Any]]:
    """Return deterministic quality gaps from evidence/fact metadata.

    ``evidence`` and ``facts`` accept either a single mapping or an iterable of
    mappings. ``facts`` also accepts a plain field-name-to-value mapping for
    already-flattened records.
    """
    check_date = _coerce_date(as_of) or datetime.now(UTC).date()
    gaps: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()

    sources = _as_records(evidence)
    fact_records = _as_fact_records(facts)

    for source in sources:
        _append_source_id_gap(gaps, seen, source, subject="source")
        _append_license_gap(gaps, seen, source)
        _append_verification_gap(
            gaps,
            seen,
            source,
            as_of=check_date,
            stale_after_days=stale_after_days,
        )

    for fact in fact_records:
        _append_source_id_gap(gaps, seen, fact, subject="fact")

    _append_conflict_gaps(gaps, seen, conflict_metadata)
    _append_missing_required_fact_gaps(gaps, seen, fact_records, required_fact_aliases)
    return gaps


def _append_source_id_gap(
    gaps: list[dict[str, Any]],
    seen: set[tuple[Any, ...]],
    record: Mapping[str, Any],
    *,
    subject: str,
) -> None:
    if subject == "fact" and "source_id" not in record:
        return
    if _has_value(record.get("source_id")):
        return

    field_name = _clean_text(record.get("field_name"))
    key = ("missing_source_id", subject, _record_ref(record), field_name)
    gap = {
        "code": "missing_source_id",
        "severity": "medium",
        "subject": subject,
        "message": f"{subject} is missing source_id",
    }
    _add_optional(gap, "field_name", field_name)
    _add_optional(gap, "source_url", _clean_text(record.get("source_url")))
    _add_optional(gap, "record_ref", _record_ref(record))
    _append_once(gaps, seen, key, gap)


def _append_license_gap(
    gaps: list[dict[str, Any]],
    seen: set[tuple[Any, ...]],
    source: Mapping[str, Any],
) -> None:
    raw_license = _clean_text(
        source.get("license")
        or source.get("license_id")
        or source.get("license_status")
        or source.get("rights")
    )
    normalized = (raw_license or "").lower()
    if normalized in BLOCKED_LICENSE_VALUES:
        code = "license_blocked"
        severity = "high"
        message = "source license blocks reuse"
    elif normalized in UNKNOWN_LICENSE_VALUES:
        code = "license_unknown"
        severity = "medium"
        message = "source license is unknown"
    else:
        return

    key = (code, _source_ref(source))
    gap = {
        "code": code,
        "severity": severity,
        "subject": "source",
        "message": message,
        "license": raw_license,
    }
    _add_optional(gap, "source_id", source.get("source_id"))
    _add_optional(gap, "source_url", _clean_text(source.get("source_url")))
    _append_once(gaps, seen, key, gap)


def _append_verification_gap(
    gaps: list[dict[str, Any]],
    seen: set[tuple[Any, ...]],
    source: Mapping[str, Any],
    *,
    as_of: date,
    stale_after_days: int,
) -> None:
    status = _clean_text(
        source.get("verification_status") or source.get("source_status") or source.get("status")
    )
    normalized_status = (status or "").lower()
    verified_at = _coerce_date(
        source.get("last_verified_at")
        or source.get("verified_at")
        or source.get("verification_checked_at")
    )

    if normalized_status in {"unverified", "never_verified"} or verified_at is None:
        key = ("source_unverified", _source_ref(source))
        gap: dict[str, Any] = {
            "code": "source_unverified",
            "severity": "medium",
            "subject": "source",
            "message": "source has not been verified",
        }
        _add_optional(gap, "source_id", source.get("source_id"))
        _add_optional(gap, "source_url", _clean_text(source.get("source_url")))
        _append_once(gaps, seen, key, gap)
        return

    age_days = (as_of - verified_at).days
    if normalized_status == "stale" or age_days > stale_after_days:
        key = ("source_stale", _source_ref(source))
        gap = {
            "code": "source_stale",
            "severity": "medium",
            "subject": "source",
            "message": "source verification is stale",
            "last_verified_at": verified_at.isoformat(),
            "age_days": age_days,
            "stale_after_days": stale_after_days,
        }
        _add_optional(gap, "source_id", source.get("source_id"))
        _add_optional(gap, "source_url", _clean_text(source.get("source_url")))
        _append_once(gaps, seen, key, gap)


def _append_conflict_gaps(
    gaps: list[dict[str, Any]],
    seen: set[tuple[Any, ...]],
    conflict_metadata: Mapping[str, Any] | None,
) -> None:
    if not conflict_metadata:
        return

    for field in conflict_metadata.get("fields", []):
        if not isinstance(field, Mapping):
            continue
        status = _clean_text(field.get("status"))
        if status not in {"conflict", "multiple_values"}:
            continue
        field_name = _clean_text(field.get("field_name"))
        key = (status, field_name)
        gap = {
            "code": status,
            "severity": "high" if status == "conflict" else "medium",
            "subject": "fact",
            "message": f"fact field has {status}",
            "field_name": field_name,
            "distinct_value_count": field.get("distinct_value_count"),
            "source_count": field.get("source_count"),
        }
        if "values" in field:
            gap["values"] = field["values"]
        _append_once(gaps, seen, key, gap)


def _append_missing_required_fact_gaps(
    gaps: list[dict[str, Any]],
    seen: set[tuple[Any, ...]],
    facts: list[Mapping[str, Any]],
    required_fact_aliases: Mapping[str, Iterable[str]],
) -> None:
    present = {_clean_text(fact.get("field_name")) for fact in facts if _fact_has_value(fact)}
    for required_name, aliases in required_fact_aliases.items():
        alias_set = {required_name, *aliases}
        if present.intersection(alias_set):
            continue
        key = ("missing_required_fact", required_name)
        gap = {
            "code": f"missing_{required_name}",
            "severity": "medium",
            "subject": "fact",
            "message": f"required {required_name} fact is missing",
            "field_group": required_name,
            "accepted_fields": sorted(alias_set),
        }
        _append_once(gaps, seen, key, gap)


def _as_records(
    records: Iterable[Mapping[str, Any]] | Mapping[str, Any] | None,
) -> list[Mapping[str, Any]]:
    if records is None:
        return []
    if isinstance(records, Mapping):
        if _looks_like_single_record(records):
            return [records]
        return [
            {"field_name": str(key), "value": value}
            for key, value in records.items()
            if not isinstance(value, Mapping)
        ]
    return [record for record in records if isinstance(record, Mapping)]


def _as_fact_records(
    facts: Iterable[Mapping[str, Any]] | Mapping[str, Any] | None,
) -> list[Mapping[str, Any]]:
    if facts is None:
        return []
    if isinstance(facts, Mapping) and not _looks_like_single_record(facts):
        return [{"field_name": str(key), "value": value} for key, value in facts.items()]
    return _as_records(facts)


def _looks_like_single_record(record: Mapping[str, Any]) -> bool:
    record_keys = set(record)
    return bool(
        record_keys.intersection(
            {
                "field_name",
                "source_id",
                "source_url",
                "license",
                "last_verified_at",
                "verified_at",
            }
        )
    )


def _fact_has_value(fact: Mapping[str, Any]) -> bool:
    return any(_has_value(fact.get(key)) for key in _FACT_VALUE_KEYS)


def _has_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, set, dict)):
        return bool(value)
    return True


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _coerce_date(value: date | datetime | str | Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        normalized = text.removesuffix("Z")
        try:
            return datetime.fromisoformat(normalized).date()
        except ValueError:
            try:
                return date.fromisoformat(normalized[:10])
            except ValueError:
                return None
    return None


def _source_ref(source: Mapping[str, Any]) -> Any:
    return source.get("source_id") or _clean_text(source.get("source_url")) or _record_ref(source)


def _record_ref(record: Mapping[str, Any]) -> Any:
    for key in ("fact_id", "id", "rowid", "source_url"):
        value = record.get(key)
        if _has_value(value):
            return value
    return None


def _add_optional(target: dict[str, Any], key: str, value: Any) -> None:
    if _has_value(value):
        target[key] = value


def _append_once(
    gaps: list[dict[str, Any]],
    seen: set[tuple[Any, ...]],
    key: tuple[Any, ...],
    gap: dict[str, Any],
) -> None:
    if key in seen:
        return
    seen.add(key)
    gaps.append(gap)


__all__ = [
    "BLOCKED_LICENSE_VALUES",
    "DEFAULT_STALE_AFTER_DAYS",
    "REQUIRED_FACT_ALIASES",
    "UNKNOWN_LICENSE_VALUES",
    "build_known_gaps",
]
