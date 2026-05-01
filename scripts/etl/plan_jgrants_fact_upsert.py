#!/usr/bin/env python3
"""Dry-run planner for future B8 JGrants mapped-fact upserts.

This module is deliberately local-only: it reads SQLite in read-only/query-only
mode, optionally reads locally supplied detail JSON, and writes a JSON plan. It
does not call the JGrants portal/API and has no insert/update/delete path.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

try:  # Use the local pure mapper when present.
    import jgrants_detail_mapping as detail_mapping
except ImportError:  # pragma: no cover - fallback only for isolated reuse.
    detail_mapping = None  # type: ignore[assignment]

try:  # Reuse the read-only B8 readiness detector when present.
    import report_jgrants_ingest_readiness as readiness
except ImportError:  # pragma: no cover - fallback only for isolated reuse.
    readiness = None  # type: ignore[assignment]


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = REPO_ROOT / "data" / "jpintel.db"
DEFAULT_READINESS = REPO_ROOT / "analysis_wave18" / "jgrants_ingest_readiness_2026-05-01.json"
DEFAULT_OUTPUT = REPO_ROOT / "analysis_wave18" / "jgrants_fact_upsert_plan_2026-05-01.json"

NETWORK_FETCH_PERFORMED = False
DB_MUTATION_PERFORMED = False
DEFAULT_LICENSE = "gov_standard_v2.0"

CONFLICT_POLICY = {
    "mode": "dry_run_no_write",
    "proposed_unique_key": [
        "entity_id",
        "field_name",
        "source_url",
        "COALESCE(field_value_text, field_value_json, field_value_numeric)",
    ],
    "on_existing_same_value": "noop",
    "on_existing_different_value": "conflict_review",
    "on_missing_source_id_or_license": "block_write_until_source_metadata_resolved",
}


@dataclass(frozen=True)
class FactTemplate:
    mapped_field: str
    target_field_name: str
    field_kind: str
    unit: str | None = None
    description: str = ""


@dataclass(frozen=True)
class SourceMetadata:
    source_url: str | None
    mapped_license: str | None
    source_table: str | None
    source_id: int | None
    source_license: str | None
    status: str
    blockers: tuple[str, ...]
    required_steps: tuple[str, ...]


FACT_TEMPLATES: tuple[FactTemplate, ...] = (
    FactTemplate(
        mapped_field="deadline",
        target_field_name="program.application_deadline",
        field_kind="date",
        description="application/submission close date parsed from JGrants detail",
    ),
    FactTemplate(
        mapped_field="max_amount",
        target_field_name="program.amount_max_yen",
        field_kind="amount",
        unit="JPY",
        description="maximum subsidy/grant amount in yen",
    ),
    FactTemplate(
        mapped_field="subsidy_rate",
        target_field_name="program.subsidy_rate",
        field_kind="ratio",
        unit="percent",
        description="normalized subsidy rate fraction and percent",
    ),
    FactTemplate(
        mapped_field="contact",
        target_field_name="program.contact",
        field_kind="json",
        description="contact desk/person/phone/email from JGrants detail",
    ),
    FactTemplate(
        mapped_field="required_docs",
        target_field_name="program.required_documents",
        field_kind="json",
        description="required application documents from JGrants detail",
    ),
    FactTemplate(
        mapped_field="source_url",
        target_field_name="program.jgrants_source_url",
        field_kind="url",
        description="JGrants detail or public source URL",
    ),
    FactTemplate(
        mapped_field="source_id",
        target_field_name="program.jgrants_source_id",
        field_kind="identifier",
        description="JGrants external subsidy/source identifier",
    ),
)


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _connect_readonly(path: Path) -> sqlite3.Connection:
    if not path.exists():
        raise FileNotFoundError(path)
    conn = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = ON")
    return conn


def _qident(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
    elif isinstance(value, int | float):
        text = str(value)
    else:
        return None
    return text or None


def _is_http_url(value: str | None) -> bool:
    if not value:
        return False
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _read_json_file(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def build_idempotency_key(
    *,
    entity_id: str,
    field_name: str,
    field_value_text: str | None,
    field_value_json: str | None,
    field_value_numeric: int | float | None,
    source_url: str | None,
    license_value: str | None,
) -> str:
    """Build a deterministic key for replay-safe future upsert planning."""
    payload = {
        "entity_id": entity_id,
        "field_name": field_name,
        "field_value_text": field_value_text,
        "field_value_json": field_value_json,
        "field_value_numeric": field_value_numeric,
        "source_url": source_url,
        "license": license_value,
    }
    digest = hashlib.sha256(_stable_json(payload).encode("utf-8")).hexdigest()[:32]
    return f"b8:jgrants_fact:{digest}"


def _template(mapped_field: str) -> FactTemplate:
    for template in FACT_TEMPLATES:
        if template.mapped_field == mapped_field:
            return template
    raise KeyError(mapped_field)


def _mapped_source_url(mapped: dict[str, Any]) -> str | None:
    source_url = mapped.get("source_url")
    if isinstance(source_url, dict):
        return _clean_text(source_url.get("url"))
    return None


def _mapped_license(mapped: dict[str, Any]) -> str | None:
    return _clean_text(mapped.get("license")) or DEFAULT_LICENSE


def _base_fact_row(
    *,
    entity_id: str,
    template: FactTemplate,
    source_metadata: SourceMetadata,
    jgrants_source_id: str | None,
    confidence: float | None,
) -> dict[str, Any]:
    return {
        "entity_id": entity_id,
        "field_name": template.target_field_name,
        "field_kind": template.field_kind,
        "unit": template.unit,
        "source_url": source_metadata.source_url,
        "source_id": source_metadata.source_id,
        "license": source_metadata.mapped_license,
        "source_license": source_metadata.source_license,
        "source_metadata_status": source_metadata.status,
        "jgrants_source_id": jgrants_source_id,
        "confidence": confidence,
        "conflict_policy": CONFLICT_POLICY,
        "source_blockers": list(source_metadata.blockers),
        "required_source_steps": list(source_metadata.required_steps),
    }


def mapped_detail_to_fact_rows(
    entity_id: str,
    mapped: dict[str, Any],
    *,
    source_metadata: SourceMetadata | None = None,
) -> list[dict[str, Any]]:
    """Convert a normalized JGrants detail mapping into proposed fact rows.

    This is pure and deterministic. It only returns rows shaped like
    ``am_entity_facts`` plus source/license/conflict metadata; it never queries
    or writes a database.
    """
    source_url = _mapped_source_url(mapped)
    metadata = source_metadata or SourceMetadata(
        source_url=source_url,
        mapped_license=_mapped_license(mapped),
        source_table=None,
        source_id=None,
        source_license=None,
        status="not_resolved",
        blockers=("source metadata not resolved",),
        required_steps=("resolve or create am_source row with source_url and license",),
    )
    jgrants_source_id = _clean_text(mapped.get("source_id"))
    rows: list[dict[str, Any]] = []

    deadline = mapped.get("deadline")
    if isinstance(deadline, dict) and _clean_text(deadline.get("value")):
        template = _template("deadline")
        row = _base_fact_row(
            entity_id=entity_id,
            template=template,
            source_metadata=metadata,
            jgrants_source_id=jgrants_source_id,
            confidence=_float_or_none(deadline.get("confidence")),
        )
        row.update(
            {
                "field_value_text": _clean_text(deadline.get("value")),
                "field_value_json": _json_text(
                    {"raw": deadline.get("raw"), "reason": deadline.get("reason")}
                ),
                "field_value_numeric": None,
            }
        )
        rows.append(_with_idempotency(row))

    max_amount = mapped.get("max_amount")
    if isinstance(max_amount, dict) and max_amount.get("yen") is not None:
        yen = int(max_amount["yen"])
        template = _template("max_amount")
        row = _base_fact_row(
            entity_id=entity_id,
            template=template,
            source_metadata=metadata,
            jgrants_source_id=jgrants_source_id,
            confidence=_float_or_none(max_amount.get("confidence")),
        )
        row.update(
            {
                "field_value_text": str(yen),
                "field_value_json": _json_text(
                    {"raw": max_amount.get("raw"), "reason": max_amount.get("reason")}
                ),
                "field_value_numeric": yen,
            }
        )
        rows.append(_with_idempotency(row))

    subsidy_rate = mapped.get("subsidy_rate")
    if isinstance(subsidy_rate, dict) and _clean_text(subsidy_rate.get("normalized")):
        template = _template("subsidy_rate")
        row = _base_fact_row(
            entity_id=entity_id,
            template=template,
            source_metadata=metadata,
            jgrants_source_id=jgrants_source_id,
            confidence=_float_or_none(subsidy_rate.get("confidence")),
        )
        row.update(
            {
                "field_value_text": _clean_text(subsidy_rate.get("normalized")),
                "field_value_json": _json_text(
                    {
                        "percent": subsidy_rate.get("percent"),
                        "raw": subsidy_rate.get("raw"),
                        "reason": subsidy_rate.get("reason"),
                    }
                ),
                "field_value_numeric": _float_or_none(subsidy_rate.get("percent")),
            }
        )
        rows.append(_with_idempotency(row))

    contact = mapped.get("contact")
    if isinstance(contact, dict) and _contact_has_value(contact):
        template = _template("contact")
        row = _base_fact_row(
            entity_id=entity_id,
            template=template,
            source_metadata=metadata,
            jgrants_source_id=jgrants_source_id,
            confidence=_float_or_none(contact.get("confidence")),
        )
        row.update(
            {
                "field_value_text": _contact_text(contact),
                "field_value_json": _json_text(contact),
                "field_value_numeric": None,
            }
        )
        rows.append(_with_idempotency(row))

    required_docs = mapped.get("required_docs")
    if isinstance(required_docs, dict) and required_docs.get("items"):
        items = [str(item) for item in required_docs["items"] if _clean_text(item)]
        if items:
            template = _template("required_docs")
            row = _base_fact_row(
                entity_id=entity_id,
                template=template,
                source_metadata=metadata,
                jgrants_source_id=jgrants_source_id,
                confidence=_float_or_none(required_docs.get("confidence")),
            )
            row.update(
                {
                    "field_value_text": "\n".join(items),
                    "field_value_json": _json_text(
                        {
                            "items": items,
                            "raw": required_docs.get("raw"),
                            "reason": required_docs.get("reason"),
                        }
                    ),
                    "field_value_numeric": None,
                }
            )
            rows.append(_with_idempotency(row))

    if source_url:
        template = _template("source_url")
        source_url_fact = mapped.get("source_url") if isinstance(mapped.get("source_url"), dict) else {}
        row = _base_fact_row(
            entity_id=entity_id,
            template=template,
            source_metadata=metadata,
            jgrants_source_id=jgrants_source_id,
            confidence=_float_or_none(source_url_fact.get("confidence")),
        )
        row.update(
            {
                "field_value_text": source_url,
                "field_value_json": _json_text(
                    {
                        "raw": source_url_fact.get("raw"),
                        "reason": source_url_fact.get("reason"),
                    }
                ),
                "field_value_numeric": None,
            }
        )
        rows.append(_with_idempotency(row))

    if jgrants_source_id:
        template = _template("source_id")
        row = _base_fact_row(
            entity_id=entity_id,
            template=template,
            source_metadata=metadata,
            jgrants_source_id=jgrants_source_id,
            confidence=1.0,
        )
        row.update(
            {
                "field_value_text": jgrants_source_id,
                "field_value_json": None,
                "field_value_numeric": None,
            }
        )
        rows.append(_with_idempotency(row))

    return rows


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _contact_has_value(contact: dict[str, Any]) -> bool:
    keys = ("organization", "department", "person", "phone", "email", "raw")
    return any(_clean_text(contact.get(key)) for key in keys)


def _contact_text(contact: dict[str, Any]) -> str | None:
    parts = [
        _clean_text(contact.get(key))
        for key in ("organization", "department", "person", "phone", "email")
    ]
    text = " ".join(part for part in parts if part)
    return text or _clean_text(contact.get("raw"))


def _with_idempotency(row: dict[str, Any]) -> dict[str, Any]:
    row["idempotency_key"] = build_idempotency_key(
        entity_id=str(row["entity_id"]),
        field_name=str(row["field_name"]),
        field_value_text=row.get("field_value_text"),
        field_value_json=row.get("field_value_json"),
        field_value_numeric=row.get("field_value_numeric"),
        source_url=row.get("source_url"),
        license_value=row.get("license"),
    )
    return row


def normalize_detail_for_program(
    detail: dict[str, Any],
    *,
    fallback_source_url: str | None = None,
) -> dict[str, Any]:
    """Normalize detail JSON through ``jgrants_detail_mapping`` when available."""
    if detail_mapping is None:
        raise RuntimeError("scripts/etl/jgrants_detail_mapping.py is not importable")
    return detail_mapping.normalize_jgrants_detail_response(
        detail,
        source_url=_clean_text(detail.get("source_url")) or fallback_source_url,
    )


def fact_templates_for_program(program: dict[str, Any]) -> list[dict[str, Any]]:
    """Return target fields and whether they would fill a current readiness gap."""
    missing = set(program.get("missing_fields") or [])
    field_sources = program.get("field_sources") or {}
    output: list[dict[str, Any]] = []
    readiness_key = {
        "deadline": "deadline",
        "max_amount": "amount",
        "subsidy_rate": "subsidy_rate",
        "contact": "contact",
        "required_docs": "required_docs",
        "source_url": "source_url",
        "source_id": "source_id",
    }
    for template in FACT_TEMPLATES:
        key = readiness_key[template.mapped_field]
        output.append(
            {
                **asdict(template),
                "readiness_field": key,
                "current_status": "missing" if key in missing else "present_or_not_tracked",
                "current_source": field_sources.get(key),
                "would_fill_if_detail_json_present": key in missing or key == "source_id",
                "requires_detail_json": True,
            }
        )
    return output


def _all_tables(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    return [str(row["name"]) for row in rows if not str(row["name"]).startswith("sqlite_")]


def _table_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    try:
        return [str(row["name"]) for row in conn.execute(f"PRAGMA table_info({_qident(table)})")]
    except sqlite3.OperationalError:
        return []


def _table_count(conn: sqlite3.Connection, table: str) -> int | None:
    try:
        return int(conn.execute(f"SELECT COUNT(*) FROM {_qident(table)}").fetchone()[0])
    except sqlite3.OperationalError:
        return None


def inspect_relevant_schema(conn: sqlite3.Connection) -> dict[str, Any]:
    """Read only the schema needed to plan a future fact/source upsert."""
    tables = set(_all_tables(conn))
    relevant = (
        "programs",
        "jpi_programs",
        "am_entities",
        "am_entity_facts",
        "am_source",
        "am_entity_source",
        "program_documents",
        "jpi_program_documents",
    )
    inspected: dict[str, Any] = {}
    for table in relevant:
        exists = table in tables
        inspected[table] = {
            "exists": exists,
            "columns": _table_columns(conn, table) if exists else [],
            "row_count": _table_count(conn, table) if exists else None,
        }
    return inspected


def load_readiness_report(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.exists():
        return None
    return _read_json_file(path)


def collect_jgrants_programs(conn: sqlite3.Connection, *, sample_limit: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Collect local JGrants-linked programs using the readiness helper."""
    if readiness is None:
        raise RuntimeError("scripts/etl/report_jgrants_ingest_readiness.py is not importable")
    report = readiness.collect_jgrants_ingest_readiness(
        conn,
        sample_limit=max(sample_limit, 100_000),
    )
    programs = list(report.get("samples", {}).get("jgrants_linked_programs", []))
    return programs, report


def resolve_source_metadata(
    conn: sqlite3.Connection,
    *,
    source_url: str | None,
    mapped_license: str | None,
) -> SourceMetadata:
    """Resolve local am_source metadata without creating or updating it."""
    if not _is_http_url(source_url):
        return SourceMetadata(
            source_url=source_url,
            mapped_license=mapped_license,
            source_table=None,
            source_id=None,
            source_license=None,
            status="blocked_invalid_or_missing_source_url",
            blockers=("source_url is missing or not absolute http(s)",),
            required_steps=("obtain a valid source_url from local detail JSON",),
        )

    schema = inspect_relevant_schema(conn)
    source_schema = schema["am_source"]
    if not source_schema["exists"]:
        return SourceMetadata(
            source_url=source_url,
            mapped_license=mapped_license,
            source_table=None,
            source_id=None,
            source_license=None,
            status="blocked_missing_source_table",
            blockers=("am_source table is missing",),
            required_steps=(
                "create or migrate am_source before any future fact upsert",
                "insert/reuse source row keyed by source_url with reviewed license",
            ),
        )

    columns = set(source_schema["columns"])
    if "source_url" not in columns or "license" not in columns:
        missing = sorted({"source_url", "license"} - columns)
        return SourceMetadata(
            source_url=source_url,
            mapped_license=mapped_license,
            source_table="am_source",
            source_id=None,
            source_license=None,
            status="blocked_source_schema_incomplete",
            blockers=(f"am_source missing columns: {', '.join(missing)}",),
            required_steps=("add/review am_source source_url and license columns",),
        )

    id_column = "id" if "id" in columns else "source_id" if "source_id" in columns else None
    select_cols = ["source_url", "license"]
    if id_column:
        select_cols.insert(0, id_column)
    sql = (
        "SELECT "
        + ", ".join(_qident(col) for col in select_cols)
        + " FROM am_source WHERE source_url = ? LIMIT 1"
    )
    row = conn.execute(sql, (source_url,)).fetchone()
    if row is None:
        return SourceMetadata(
            source_url=source_url,
            mapped_license=mapped_license,
            source_table="am_source",
            source_id=None,
            source_license=None,
            status="blocked_source_row_missing",
            blockers=("no local am_source row matches source_url",),
            required_steps=(
                "insert reviewed am_source row for source_url",
                "set am_source.license before linking proposed facts",
            ),
        )

    source_id = int(row[id_column]) if id_column and row[id_column] is not None else None
    source_license = _clean_text(row["license"])
    if source_id is None or not source_license:
        blockers: list[str] = []
        steps: list[str] = []
        if source_id is None:
            blockers.append("am_source row has no usable integer source id")
            steps.append("ensure am_source has a stable id/source_id for FK use")
        if not source_license:
            blockers.append("am_source row has empty license")
            steps.append("review and populate am_source.license")
        return SourceMetadata(
            source_url=source_url,
            mapped_license=mapped_license,
            source_table="am_source",
            source_id=source_id,
            source_license=source_license,
            status="blocked_source_metadata_incomplete",
            blockers=tuple(blockers),
            required_steps=tuple(steps),
        )

    return SourceMetadata(
        source_url=source_url,
        mapped_license=mapped_license,
        source_table="am_source",
        source_id=source_id,
        source_license=source_license,
        status="resolved",
        blockers=(),
        required_steps=(),
    )


def annotate_existing_fact_status(
    conn: sqlite3.Connection,
    proposed_row: dict[str, Any],
) -> dict[str, Any]:
    """Annotate a proposed row with read-only existing-row/conflict status."""
    schema = inspect_relevant_schema(conn)
    facts_schema = schema["am_entity_facts"]
    if not facts_schema["exists"]:
        return {
            **proposed_row,
            "dry_run_action": "blocked_missing_am_entity_facts_table",
            "existing_fact_ids": [],
        }

    columns = set(facts_schema["columns"])
    required = {"entity_id", "field_name"}
    if not required.issubset(columns):
        return {
            **proposed_row,
            "dry_run_action": "blocked_am_entity_facts_schema_incomplete",
            "existing_fact_ids": [],
            "schema_missing_columns": sorted(required - columns),
        }

    select_cols = [col for col in ("id", "field_value_text", "field_value_json", "field_value_numeric") if col in columns]
    if not select_cols:
        select_cols = ["entity_id", "field_name"]
    sql = (
        "SELECT "
        + ", ".join(_qident(col) for col in select_cols)
        + " FROM am_entity_facts WHERE entity_id = ? AND field_name = ? LIMIT 20"
    )
    rows = list(
        conn.execute(
            sql,
            (proposed_row["entity_id"], proposed_row["field_name"]),
        )
    )
    if not rows:
        if proposed_row.get("source_blockers"):
            return {
                **proposed_row,
                "dry_run_action": "blocked_source_metadata",
                "existing_fact_ids": [],
            }
        return {**proposed_row, "dry_run_action": "would_insert", "existing_fact_ids": []}

    same_ids: list[int | str] = []
    other_ids: list[int | str] = []
    for row in rows:
        row_keys = set(row.keys())
        row_id: int | str = row["id"] if "id" in row_keys else "<no-id-column>"
        if _same_fact_value(row, proposed_row):
            same_ids.append(row_id)
        else:
            other_ids.append(row_id)

    if same_ids:
        return {
            **proposed_row,
            "dry_run_action": "noop_existing_same_value",
            "existing_fact_ids": same_ids,
        }
    return {
        **proposed_row,
        "dry_run_action": "conflict_review_existing_different_value",
        "existing_fact_ids": other_ids,
    }


def _same_fact_value(existing: sqlite3.Row, proposed: dict[str, Any]) -> bool:
    keys = set(existing.keys())
    if "field_value_text" in keys and existing["field_value_text"] == proposed.get("field_value_text"):
        return True
    if "field_value_json" in keys and existing["field_value_json"] == proposed.get("field_value_json"):
        return True
    if "field_value_numeric" in keys:
        old = existing["field_value_numeric"]
        new = proposed.get("field_value_numeric")
        if old is not None and new is not None and float(old) == float(new):
            return True
    return False


def load_detail_payloads(path: Path | None) -> dict[str, dict[str, Any]]:
    """Load optional local detail JSON keyed by program/source identifiers."""
    if path is None:
        return {}
    if not path.exists():
        raise FileNotFoundError(path)

    payloads: dict[str, dict[str, Any]] = {}
    if path.is_dir():
        for child in sorted(path.glob("*.json")):
            _add_detail_payload(payloads, _read_json_file(child), fallback_key=child.stem)
        return payloads

    _add_detail_payload(payloads, _read_json_file(path), fallback_key=path.stem)
    return payloads


def _add_detail_payload(
    payloads: dict[str, dict[str, Any]],
    raw: Any,
    *,
    fallback_key: str,
) -> None:
    if isinstance(raw, list):
        for index, item in enumerate(raw):
            _add_detail_payload(payloads, item, fallback_key=f"{fallback_key}:{index}")
        return
    if not isinstance(raw, dict):
        return

    if "details" in raw and isinstance(raw["details"], list):
        for index, item in enumerate(raw["details"]):
            _add_detail_payload(payloads, item, fallback_key=f"{fallback_key}:{index}")
        return

    if "detail" in raw and isinstance(raw["detail"], dict):
        detail = raw["detail"]
        keys = _detail_keys(raw, fallback_key=fallback_key)
        keys.extend(_detail_keys(detail, fallback_key=""))
    else:
        detail = raw
        keys = _detail_keys(raw, fallback_key=fallback_key)

    for key in keys:
        if key:
            payloads[key] = detail


def _detail_keys(raw: dict[str, Any], *, fallback_key: str) -> list[str]:
    keys = [fallback_key]
    for field in (
        "program_id",
        "unified_id",
        "entity_id",
        "source_id",
        "sourceId",
        "subsidy_id",
        "subsidyId",
        "jgrants_id",
        "jgrantsId",
        "id",
    ):
        value = _clean_text(raw.get(field))
        if value:
            keys.append(value)
    return list(dict.fromkeys(key for key in keys if key))


def _detail_for_program(
    program: dict[str, Any],
    detail_payloads: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    for key in (
        program.get("program_id"),
        program.get("unified_id"),
        program.get("source_id"),
        program.get("primary_name"),
    ):
        clean = _clean_text(key)
        if clean and clean in detail_payloads:
            return detail_payloads[clean]
    return None


def build_program_fact_plan(
    conn: sqlite3.Connection,
    program: dict[str, Any],
    *,
    detail_payload: dict[str, Any] | None,
) -> dict[str, Any]:
    program_id = str(program.get("program_id") or program.get("unified_id") or "")
    fallback_source_url = _clean_text(program.get("source_url")) or _clean_text(program.get("official_url"))
    blockers: list[str] = []
    proposed_rows: list[dict[str, Any]] = []
    mapped: dict[str, Any] | None = None

    if detail_payload is None:
        blockers.append("detail_json_missing")
    else:
        mapped = normalize_detail_for_program(detail_payload, fallback_source_url=fallback_source_url)
        source_metadata = resolve_source_metadata(
            conn,
            source_url=_mapped_source_url(mapped),
            mapped_license=_mapped_license(mapped),
        )
        rows = mapped_detail_to_fact_rows(
            program_id,
            mapped,
            source_metadata=source_metadata,
        )
        proposed_rows = [annotate_existing_fact_status(conn, row) for row in rows]
        if source_metadata.blockers:
            blockers.extend(f"source_metadata:{blocker}" for blocker in source_metadata.blockers)
        validation = mapped.get("validation")
        if isinstance(validation, dict) and not validation.get("valid", False):
            blockers.extend(f"mapping_validation:{error}" for error in validation.get("errors", []))

    return {
        "program_id": program_id,
        "primary_name": program.get("primary_name"),
        "authority_name": program.get("authority_name"),
        "official_url": program.get("official_url"),
        "source_url": program.get("source_url"),
        "link_reasons": program.get("link_reasons", []),
        "current_missing_fields": program.get("missing_fields", []),
        "current_field_sources": program.get("field_sources", {}),
        "detail_json_status": "present" if detail_payload is not None else "missing",
        "candidate_fact_templates": fact_templates_for_program(program),
        "mapped_validation": mapped.get("validation") if mapped else None,
        "proposed_fact_rows": proposed_rows,
        "blockers": blockers,
    }


def build_jgrants_fact_upsert_plan(
    conn: sqlite3.Connection,
    *,
    detail_payloads: dict[str, dict[str, Any]] | None = None,
    readiness_path: Path | None = DEFAULT_READINESS,
    sample_limit: int = 100_000,
    database_label: str | None = None,
) -> dict[str, Any]:
    detail_payloads = detail_payloads or {}
    schema = inspect_relevant_schema(conn)
    readiness_file = load_readiness_report(readiness_path)
    programs, computed_readiness = collect_jgrants_programs(conn, sample_limit=sample_limit)
    program_plans = [
        build_program_fact_plan(
            conn,
            program,
            detail_payload=_detail_for_program(program, detail_payloads),
        )
        for program in programs
    ]
    action_counts = Counter(
        row.get("dry_run_action", "no_rows")
        for program in program_plans
        for row in program["proposed_fact_rows"]
    )
    field_counts = Counter(
        row["field_name"]
        for program in program_plans
        for row in program["proposed_fact_rows"]
    )
    blockers = _global_blockers(schema, computed_readiness)
    blockers.extend(
        sorted(
            {
                blocker
                for program in program_plans
                for blocker in program["blockers"]
                if blocker != "detail_json_missing"
            }
        )
    )

    return {
        "report": "b8_jgrants_fact_upsert_plan",
        "generated_at": _utc_now(),
        "database": database_label,
        "dry_run": True,
        "report_only": True,
        "mutates_db": False,
        "external_api_calls": False,
        "network_fetch_performed": NETWORK_FETCH_PERFORMED,
        "db_mutation_performed": DB_MUTATION_PERFORMED,
        "mapping_module": {
            "present": detail_mapping is not None,
            "network_fetch_performed": bool(
                getattr(detail_mapping, "NETWORK_FETCH_PERFORMED", False)
            )
            if detail_mapping is not None
            else None,
            "db_mutation_performed": bool(getattr(detail_mapping, "DB_MUTATION_PERFORMED", False))
            if detail_mapping is not None
            else None,
        },
        "readiness_report": {
            "path": str(readiness_path) if readiness_path else None,
            "present": readiness_file is not None,
            "file_generated_at": readiness_file.get("generated_at") if readiness_file else None,
            "file_totals": readiness_file.get("totals") if readiness_file else None,
            "computed_totals": computed_readiness.get("totals", {}),
            "computed_blockers": computed_readiness.get("blockers", []),
        },
        "schema": schema,
        "conflict_policy": CONFLICT_POLICY,
        "required_source_id_license_steps": required_source_id_license_steps(schema),
        "fact_templates": [asdict(template) for template in FACT_TEMPLATES],
        "counts": {
            "jgrants_linked_programs": len(program_plans),
            "programs_with_detail_json": sum(
                1 for program in program_plans if program["detail_json_status"] == "present"
            ),
            "programs_missing_detail_json": sum(
                1 for program in program_plans if program["detail_json_status"] == "missing"
            ),
            "candidate_fact_slots_if_all_details_present": len(program_plans) * len(FACT_TEMPLATES),
            "proposed_fact_rows": sum(
                len(program["proposed_fact_rows"]) for program in program_plans
            ),
            "action_counts": dict(sorted(action_counts.items())),
            "field_counts": dict(sorted(field_counts.items())),
        },
        "blockers": blockers,
        "programs": program_plans,
    }


def _global_blockers(schema: dict[str, Any], computed_readiness: dict[str, Any]) -> list[str]:
    blockers: list[str] = []
    if not schema["am_entity_facts"]["exists"]:
        blockers.append("am_entity_facts table is missing; proposed rows are shape-only")
    if not schema["am_source"]["exists"]:
        blockers.append("am_source table is missing; source_id/license cannot be resolved locally")
    else:
        columns = set(schema["am_source"]["columns"])
        if "license" not in columns:
            blockers.append("am_source.license column is missing")
        if "source_url" not in columns:
            blockers.append("am_source.source_url column is missing")
    if not computed_readiness.get("totals", {}).get("jgrants_linked_program_rows"):
        blockers.append("no local JGrants-linked programs detected")
    return blockers


def required_source_id_license_steps(schema: dict[str, Any]) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = [
        {
            "step": "local_detail_json",
            "required": True,
            "status": "pending",
            "reason": "JGrants detail payload must be acquired by a separate reviewed local fetch path",
        }
    ]
    source_schema = schema["am_source"]
    if not source_schema["exists"]:
        steps.append(
            {
                "step": "source_table",
                "required": True,
                "status": "blocked",
                "reason": "am_source table is absent in this DB",
            }
        )
    else:
        columns = set(source_schema["columns"])
        steps.append(
            {
                "step": "source_row",
                "required": True,
                "status": "review_required",
                "required_columns": ["source_url", "license", "id"],
                "present_columns": sorted(columns),
            }
        )
    steps.append(
        {
            "step": "license_review",
            "required": True,
            "status": "review_required",
            "reason": (
                "Do not link facts until the JGrants source URL has reviewed "
                "license terms stored locally"
            ),
        }
    )
    steps.append(
        {
            "step": "fact_upsert_apply",
            "required": True,
            "status": "not_implemented",
            "reason": "B8 only produces this dry-run plan; no apply path exists",
        }
    )
    return steps


def write_plan(plan: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--readiness", type=Path, default=DEFAULT_READINESS)
    parser.add_argument("--details", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--sample-limit", type=int, default=100_000)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    detail_payloads = load_detail_payloads(args.details)
    with _connect_readonly(args.db) as conn:
        plan = build_jgrants_fact_upsert_plan(
            conn,
            detail_payloads=detail_payloads,
            readiness_path=args.readiness,
            sample_limit=args.sample_limit,
            database_label=str(args.db),
        )
    write_plan(plan, args.output)
    summary = {
        "output": str(args.output),
        "jgrants_linked_programs": plan["counts"]["jgrants_linked_programs"],
        "programs_with_detail_json": plan["counts"]["programs_with_detail_json"],
        "proposed_fact_rows": plan["counts"]["proposed_fact_rows"],
        "blockers": len(plan["blockers"]),
    }
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2 if args.json else None))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
