"""Read-only conflict metadata over ``am_entity_facts``.

The helper in this module is intentionally local to the normalized EAV table:
it does not write, does not call network/LLM services, and does not wire itself
into HTTP or MCP handlers. It groups facts by ``(entity_id, field_name)`` using
canonicalized EAV values and source attribution from ``source_id`` with a
``source_url`` fallback.
"""

from __future__ import annotations

import json
import re
import sqlite3
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import unquote, urlsplit, urlunsplit

DEFAULT_SINGLETON_FIELD_ALLOWLIST: frozenset[str] = frozenset(
    {
        "amount_max_yen",
        "amount_min_yen",
        "application_deadline",
        "authority_name",
        "authority_level",
        "canonical_status",
        "end_date",
        "grant_amount_max_yen",
        "grant_amount_min_yen",
        "loan_amount_max_yen",
        "loan_period_years_max",
        "opens_at",
        "prefecture",
        "primary_name",
        "program_kind",
        "record_kind",
        "source_topic",
        "start_date",
        "subsidy_rate",
        "tier",
    }
)

_WHITESPACE_RE = re.compile(r"\s+")


def compute_entity_conflict_metadata(
    conn: sqlite3.Connection,
    entity_id: str,
    *,
    singleton_fields: set[str] | frozenset[str] | None = None,
) -> dict[str, Any] | None:
    """Return per-field conflict metadata for one entity.

    Fields in ``singleton_fields`` are treated as scalar claims, so multiple
    distinct normalized values are reported as ``conflict``. Other fields may
    legitimately be multi-valued; multiple values there are labelled
    ``multiple_values`` instead.

    Returns ``None`` when ``am_entity_facts`` is unavailable or the entity has
    no non-null fact values.
    """
    columns = _table_columns(conn, "am_entity_facts")
    if not columns or not {"entity_id", "field_name"}.issubset(columns):
        return None

    row_id_expr = "id" if "id" in columns else "rowid"
    select_parts = [
        f"{row_id_expr} AS fact_id",
        "entity_id",
        "field_name",
        _nullable_select(columns, "field_value_text", "field_value_text"),
        _nullable_select(columns, "field_value_numeric", "field_value_numeric"),
        _nullable_select(columns, "field_value_json", "field_value_json"),
        _nullable_select(columns, "value", "legacy_value"),
        _nullable_select(columns, "source_id", "source_id"),
        _nullable_select(columns, "source_url", "source_url"),
    ]

    try:
        rows = conn.execute(
            f"SELECT {', '.join(select_parts)} "
            "FROM am_entity_facts "
            "WHERE entity_id = ? "
            "ORDER BY field_name ASC, fact_id ASC",
            (entity_id,),
        ).fetchall()
    except sqlite3.OperationalError:
        return None

    allowlist = (
        DEFAULT_SINGLETON_FIELD_ALLOWLIST
        if singleton_fields is None
        else frozenset(singleton_fields)
    )
    fields: dict[str, dict[str, Any]] = {}

    for row in rows:
        normalized = _normalized_fact_value(row)
        if normalized is None:
            continue

        field_name = row["field_name"]
        field = fields.setdefault(
            field_name,
            {
                "field_name": field_name,
                "is_singleton": field_name in allowlist,
                "values": {},
                "fact_count": 0,
            },
        )
        field["fact_count"] += 1

        value_key, display_value = normalized
        value_bucket = field["values"].setdefault(
            value_key,
            {
                "normalized_value": value_key,
                "display_value": display_value,
                "fact_ids": [],
                "_sources": {},
            },
        )
        value_bucket["fact_ids"].append(int(row["fact_id"]))

        source_key, source_payload = _source_identity(row)
        if source_key is not None:
            value_bucket["_sources"][source_key] = source_payload

    if not fields:
        return None

    fields_out = [_finalize_field(field) for field in fields.values()]
    fields_out.sort(
        key=lambda f: (
            0 if f["status"] == "conflict" else 1 if f["status"] == "multiple_values" else 2,
            f["field_name"],
        )
    )

    conflict_count = sum(1 for field in fields_out if field["status"] == "conflict")
    multiple_values_count = sum(1 for field in fields_out if field["status"] == "multiple_values")
    return {
        "entity_id": entity_id,
        "summary": {
            "fields_checked": len(fields_out),
            "conflict_count": conflict_count,
            "multiple_values_count": multiple_values_count,
            "has_conflicts": conflict_count > 0,
        },
        "fields": fields_out,
    }


def _table_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    try:
        return {row["name"] for row in conn.execute(f"PRAGMA table_info({table_name})")}
    except (KeyError, sqlite3.OperationalError):
        return set()


def _nullable_select(columns: set[str], column: str, alias: str) -> str:
    if column in columns:
        return f"{column} AS {alias}"
    return f"NULL AS {alias}"


def _normalized_fact_value(row: sqlite3.Row) -> tuple[str, Any] | None:
    json_value = _clean_text(row["field_value_json"])
    if json_value is not None:
        try:
            parsed = json.loads(json_value)
        except json.JSONDecodeError:
            collapsed = _collapse_text(json_value)
            return f"json_text:{collapsed}", collapsed
        return _canonical_json(parsed), parsed

    numeric_value = row["field_value_numeric"]
    if numeric_value is not None:
        normalized = _canonical_number(numeric_value)
        if normalized is not None:
            return normalized, _numeric_display(normalized)

    text_value = _clean_text(row["field_value_text"])
    if text_value is not None:
        collapsed = _collapse_text(text_value)
        return collapsed, collapsed

    legacy_value = _clean_text(row["legacy_value"])
    if legacy_value is not None:
        collapsed = _collapse_text(legacy_value)
        return collapsed, collapsed

    return None


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _collapse_text(value: str) -> str:
    return _WHITESPACE_RE.sub(" ", value.strip())


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _canonical_number(value: Any) -> str | None:
    try:
        decimal_value = Decimal(str(value))
    except InvalidOperation:
        return None
    if not decimal_value.is_finite():
        return None
    normalized = decimal_value.normalize()
    if normalized == 0:
        return "0"
    return format(normalized, "f")


def _numeric_display(normalized: str) -> int | float:
    decimal_value = Decimal(normalized)
    if decimal_value == decimal_value.to_integral_value():
        return int(decimal_value)
    return float(decimal_value)


def _source_identity(row: sqlite3.Row) -> tuple[str | None, dict[str, Any] | None]:
    source_id = row["source_id"]
    source_url = _clean_text(row["source_url"])
    if source_id is not None:
        return (
            f"source_id:{int(source_id)}",
            {"source_id": int(source_id), "source_url": source_url},
        )
    if source_url is None:
        return None, None
    normalized_url = _normalize_source_url(source_url)
    return (
        f"source_url:{normalized_url}",
        {"source_id": None, "source_url": source_url},
    )


def _normalize_source_url(source_url: str) -> str:
    parsed = urlsplit(source_url.strip())
    scheme = parsed.scheme.lower()
    netloc = parsed.netloc.lower()
    path = unquote(parsed.path)
    if path != "/":
        path = path.rstrip("/")
    return urlunsplit((scheme, netloc, path, parsed.query, ""))


def _finalize_field(field: dict[str, Any]) -> dict[str, Any]:
    values = []
    source_keys: set[str] = set()
    for value in field["values"].values():
        sources_by_key = value.pop("_sources")
        source_keys.update(sources_by_key)
        value["sources"] = [
            sources_by_key[key]
            for key in sorted(
                sources_by_key,
                key=lambda k: (
                    0 if k.startswith("source_id:") else 1,
                    k,
                ),
            )
        ]
        value["source_count"] = len(value["sources"])
        values.append(value)

    values.sort(key=lambda v: v["normalized_value"])
    distinct_value_count = len(values)
    if distinct_value_count <= 1:
        status = "consistent"
    elif field["is_singleton"]:
        status = "conflict"
    else:
        status = "multiple_values"

    return {
        "field_name": field["field_name"],
        "status": status,
        "is_singleton": field["is_singleton"],
        "fact_count": field["fact_count"],
        "distinct_value_count": distinct_value_count,
        "source_count": len(source_keys),
        "values": values,
    }


__all__ = [
    "DEFAULT_SINGLETON_FIELD_ALLOWLIST",
    "compute_entity_conflict_metadata",
]
