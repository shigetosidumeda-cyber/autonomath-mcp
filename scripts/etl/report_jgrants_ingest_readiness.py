#!/usr/bin/env python3
"""Report-only B8 JGrants detail-ingest readiness checker.

This helper is intentionally local-only. It opens SQLite in read-only mode,
inspects the available schema, finds locally known JGrants-linked programs, and
reports which detail fields are already structured enough for a safe ingest.
It does not call JGrants, Digital Agency docs, or any other external service.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = REPO_ROOT / "data" / "jpintel.db"
DEFAULT_OUTPUT = REPO_ROOT / "analysis_wave18" / "jgrants_ingest_readiness_2026-05-01.json"
INGEST_TIER_PATH = REPO_ROOT / "scripts" / "ingest_tier.py"

JGRANTS_DOMAIN = "jgrants-portal.go.jp"
JGRANTS_GENERIC_SUBSIDY_URL = "https://www.jgrants-portal.go.jp/subsidy/subsidy"
REPORT_FIELDS = (
    "deadline",
    "amount",
    "subsidy_rate",
    "contact",
    "required_docs",
    "source_url",
    "license",
)
DEFAULT_SAMPLE_LIMIT = 20


class SchemaSelectionError(RuntimeError):
    """Raised when the local SQLite DB has no usable program table."""


@dataclass(frozen=True)
class ProgramSchema:
    table: str
    id_column: str
    name_column: str
    columns: tuple[str, ...]


@dataclass(frozen=True)
class RoundSchema:
    table: str
    program_id_column: str
    label_column: str | None
    open_column: str | None
    close_column: str | None
    status_column: str | None
    source_url_column: str | None
    columns: tuple[str, ...]


@dataclass(frozen=True)
class DocumentSchema:
    table: str
    program_name_column: str
    name_column: str | None
    url_column: str | None
    source_url_column: str | None
    columns: tuple[str, ...]


@dataclass(frozen=True)
class SourceSchema:
    table: str
    source_url_column: str
    license_column: str | None
    domain_column: str | None
    columns: tuple[str, ...]


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _connect_readonly(path: Path) -> sqlite3.Connection:
    if not path.exists():
        raise FileNotFoundError(path)
    conn = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = ON")
    return conn


def _qident(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _all_tables(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    return [str(row["name"]) for row in rows if not str(row["name"]).startswith("sqlite_")]


def _table_columns(conn: sqlite3.Connection, table: str) -> tuple[str, ...]:
    try:
        return tuple(
            str(row["name"]) for row in conn.execute(f"PRAGMA table_info({_qident(table)})")
        )
    except sqlite3.OperationalError:
        return ()


def _table_row_count(conn: sqlite3.Connection, table: str) -> int:
    try:
        row = conn.execute(f"SELECT COUNT(*) FROM {_qident(table)}").fetchone()
    except sqlite3.OperationalError:
        return 0
    return int(row[0] or 0) if row is not None else 0


def _choose_column(columns: set[str], candidates: tuple[str, ...]) -> str | None:
    for candidate in candidates:
        if candidate in columns:
            return candidate
    return None


def _skip_internal_table(table: str) -> bool:
    return bool(
        table.endswith(
            ("_fts", "_fts_config", "_fts_content", "_fts_data", "_fts_docsize", "_fts_idx")
        )
        or table.startswith("_")
    )


def inspect_program_schema(conn: sqlite3.Connection) -> ProgramSchema:
    """Select the nonempty program table from the actual local schema."""
    best: tuple[int, str, tuple[str, ...], str, str] | None = None
    for table in _all_tables(conn):
        if _skip_internal_table(table):
            continue
        columns = _table_columns(conn, table)
        column_set = set(columns)
        id_column = _choose_column(
            column_set,
            ("unified_id", "program_id", "canonical_id", "id"),
        )
        name_column = _choose_column(
            column_set,
            ("primary_name", "program_name", "name", "title"),
        )
        if id_column is None or name_column is None:
            continue

        row_count = _table_row_count(conn, table)
        score = 0
        if table == "programs":
            score += 200
        elif table == "jpi_programs":
            score += 190
        elif "program" in table:
            score += 30
        score += 100 if row_count > 0 else 0
        score += sum(
            5
            for c in (
                "official_url",
                "source_url",
                "application_window_json",
                "enriched_json",
                "amount_max_man_yen",
                "subsidy_rate",
            )
            if c in column_set
        )
        if best is None or score > best[0]:
            best = (score, table, columns, id_column, name_column)

    if best is None:
        raise SchemaSelectionError("no program-like table with id/name columns found")
    _, table, columns, id_column, name_column = best
    return ProgramSchema(table=table, id_column=id_column, name_column=name_column, columns=columns)


def inspect_round_schema(conn: sqlite3.Connection) -> RoundSchema | None:
    best: tuple[int, str, tuple[str, ...], str] | None = None
    for table in _all_tables(conn):
        if _skip_internal_table(table):
            continue
        if "round" not in table:
            continue
        columns = _table_columns(conn, table)
        column_set = set(columns)
        program_id_column = _choose_column(
            column_set,
            ("program_entity_id", "program_id", "program_unified_id", "unified_id"),
        )
        close_column = _choose_column(
            column_set,
            (
                "application_close_date",
                "application_deadline",
                "close_date",
                "end_date",
                "deadline",
            ),
        )
        open_column = _choose_column(
            column_set,
            ("application_open_date", "open_date", "start_date", "announced_date"),
        )
        if program_id_column is None or (close_column is None and open_column is None):
            continue
        row_count = _table_row_count(conn, table)
        score = 0
        if table == "am_application_round":
            score += 200
        elif "round" in table:
            score += 40
        score += 100 if row_count > 0 else 0
        if best is None or score > best[0]:
            best = (score, table, columns, program_id_column)

    if best is None:
        return None
    _, table, columns, program_id_column = best
    column_set = set(columns)
    return RoundSchema(
        table=table,
        program_id_column=program_id_column,
        label_column=_choose_column(column_set, ("round_label", "label", "name")),
        open_column=_choose_column(
            column_set,
            ("application_open_date", "open_date", "start_date", "announced_date"),
        ),
        close_column=_choose_column(
            column_set,
            (
                "application_close_date",
                "application_deadline",
                "close_date",
                "end_date",
                "deadline",
            ),
        ),
        status_column=_choose_column(column_set, ("status", "round_status")),
        source_url_column=_choose_column(column_set, ("source_url", "url")),
        columns=columns,
    )


def inspect_document_schema(conn: sqlite3.Connection) -> DocumentSchema | None:
    best: tuple[int, str, tuple[str, ...], str] | None = None
    for table in _all_tables(conn):
        if _skip_internal_table(table):
            continue
        columns = _table_columns(conn, table)
        column_set = set(columns)
        program_name_column = _choose_column(
            column_set,
            ("program_name", "primary_name", "program_title"),
        )
        name_column = _choose_column(column_set, ("form_name", "document_name", "name", "title"))
        url_column = _choose_column(
            column_set,
            ("form_url_direct", "template_url", "document_url", "url"),
        )
        if program_name_column is None or (name_column is None and url_column is None):
            continue
        row_count = _table_row_count(conn, table)
        score = 0
        if table in {"program_documents", "jpi_program_documents"}:
            score += 200
        elif "document" in table:
            score += 40
        score += 100 if row_count > 0 else 0
        if table == "jpi_program_documents":
            score += 5
        if best is None or score > best[0]:
            best = (score, table, columns, program_name_column)

    if best is None:
        return None
    _, table, columns, program_name_column = best
    column_set = set(columns)
    return DocumentSchema(
        table=table,
        program_name_column=program_name_column,
        name_column=_choose_column(column_set, ("form_name", "document_name", "name", "title")),
        url_column=_choose_column(
            column_set,
            ("form_url_direct", "template_url", "document_url", "url"),
        ),
        source_url_column=_choose_column(column_set, ("source_url", "source")),
        columns=columns,
    )


def inspect_source_schema(conn: sqlite3.Connection) -> SourceSchema | None:
    best: tuple[int, str, tuple[str, ...], str] | None = None
    for table in _all_tables(conn):
        if _skip_internal_table(table):
            continue
        if "source" not in table:
            continue
        columns = _table_columns(conn, table)
        column_set = set(columns)
        source_url_column = _choose_column(column_set, ("source_url", "url"))
        if source_url_column is None or "license" not in column_set:
            continue
        score = 0
        if table == "am_source":
            score += 220
        elif "source" in table:
            score += 30
        if "license" in column_set:
            score += 100
        score += 20 if _table_row_count(conn, table) > 0 else 0
        if best is None or score > best[0]:
            best = (score, table, columns, source_url_column)

    if best is None:
        return None
    _, table, columns, source_url_column = best
    column_set = set(columns)
    return SourceSchema(
        table=table,
        source_url_column=source_url_column,
        license_column=_choose_column(column_set, ("license", "license_id", "terms")),
        domain_column=_choose_column(column_set, ("domain", "source_domain")),
        columns=columns,
    )


def _json_load(raw: Any) -> Any:
    if raw is None:
        return None
    if isinstance(raw, (dict, list)):
        return raw
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def _truthy_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _truthy_number(value: Any) -> bool:
    if value is None:
        return False
    try:
        return float(value) != 0.0
    except (TypeError, ValueError):
        return False


def _iter_json_paths(value: Any, prefix: str = "") -> list[tuple[str, Any]]:
    out: list[tuple[str, Any]] = []
    if isinstance(value, dict):
        for key, item in value.items():
            child = f"{prefix}.{key}" if prefix else str(key)
            out.append((child, item))
            out.extend(_iter_json_paths(item, child))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            child = f"{prefix}[{index}]"
            out.append((child, item))
            out.extend(_iter_json_paths(item, child))
    return out


def _json_has_path_value(value: Any, path_regex: str) -> tuple[bool, str | None]:
    pattern = re.compile(path_regex, re.IGNORECASE)
    for path, item in _iter_json_paths(value):
        if not pattern.search(path):
            continue
        if isinstance(item, list) and item:
            return True, path
        if isinstance(item, dict) and item:
            return True, path
        if _truthy_text(item) or _truthy_number(item):
            return True, path
    return False, None


def _json_has_deadline(value: Any) -> tuple[bool, str | None]:
    return _json_has_path_value(
        value,
        r"(^|\.)(schedule_v3|application_window|deadline|end_date|close_date|application_deadline|windows)(\.|$|\[)",
    )


def _json_has_amount(value: Any) -> tuple[bool, str | None]:
    return _json_has_path_value(
        value,
        r"(amount|money|budget|subsidy_max|grant_max|補助額|上限額)",
    )


def _json_has_subsidy_rate(value: Any) -> tuple[bool, str | None]:
    return _json_has_path_value(value, r"(subsidy_rate|rate|補助率)")


def _json_has_contact(value: Any) -> tuple[bool, str | None]:
    return _json_has_path_value(
        value, r"(contacts_v3|contact|office_name|helpdesk|phone|email|問い合わせ)"
    )


def _json_has_documents(value: Any) -> tuple[bool, str | None]:
    return _json_has_path_value(
        value,
        r"(documents_v3|documents|required_docs|form_name|template_url|申請書|添付書類)",
    )


def _select_columns(schema: ProgramSchema) -> list[str]:
    wanted = (
        schema.id_column,
        schema.name_column,
        "authority_name",
        "official_url",
        "source_url",
        "source_mentions_json",
        "enriched_json",
        "application_window_json",
        "amount_max_man_yen",
        "amount_min_man_yen",
        "amount_band",
        "subsidy_rate",
        "subsidy_rate_text",
        "updated_at",
        "source_fetched_at",
        "source_checksum",
    )
    seen: set[str] = set()
    cols: list[str] = []
    for col in wanted:
        if col in schema.columns and col not in seen:
            seen.add(col)
            cols.append(col)
    return cols


def _program_rows(conn: sqlite3.Connection, schema: ProgramSchema) -> list[sqlite3.Row]:
    cols = _select_columns(schema)
    sql = (
        "SELECT "
        + ", ".join(f"{_qident(col)} AS {_qident(col)}" for col in cols)
        + f" FROM {_qident(schema.table)}"
    )
    return list(conn.execute(sql))


def _jgrants_link_reasons(row: sqlite3.Row, schema: ProgramSchema) -> list[str]:
    keys = set(row.keys())
    checks = (
        ("authority_name", "authority_name"),
        (schema.name_column, "program_name"),
        ("official_url", "official_url"),
        ("source_url", "source_url"),
        ("source_mentions_json", "source_mentions_json"),
        ("enriched_json", "enriched_json"),
    )
    reasons: list[str] = []
    for column, label in checks:
        if column not in keys:
            continue
        value = row[column]
        text = str(value or "")
        lower = text.lower()
        if JGRANTS_DOMAIN in lower:
            reasons.append(f"{label}:domain")
        elif (
            "jgrants" in lower
            or "jグランツ" in lower
            or "jグラント" in lower
            or "ｊグランツ" in lower
            or "Jグランツ" in text
        ):
            reasons.append(f"{label}:text")
    return reasons


def _load_round_presence(
    conn: sqlite3.Connection,
    schema: RoundSchema | None,
    program_ids: set[str],
) -> dict[str, dict[str, Any]]:
    if schema is None or not program_ids:
        return {}
    cols = [schema.program_id_column]
    for col in (
        schema.label_column,
        schema.open_column,
        schema.close_column,
        schema.status_column,
        schema.source_url_column,
    ):
        if col and col not in cols:
            cols.append(col)
    placeholders = ",".join("?" for _ in program_ids)
    sql = (
        "SELECT "
        + ", ".join(_qident(col) for col in cols)
        + f" FROM {_qident(schema.table)}"
        + f" WHERE {_qident(schema.program_id_column)} IN ({placeholders})"
    )
    out: dict[str, dict[str, Any]] = {}
    for row in conn.execute(sql, tuple(program_ids)):
        program_id = str(row[schema.program_id_column])
        row_keys = set(row.keys())
        has_date = bool(
            (schema.close_column and _truthy_text(row[schema.close_column]))
            or (schema.open_column and _truthy_text(row[schema.open_column]))
        )
        entry = out.setdefault(program_id, {"count": 0, "has_deadline": False, "samples": []})
        entry["count"] += 1
        entry["has_deadline"] = bool(entry["has_deadline"] or has_date)
        if len(entry["samples"]) < 3:
            entry["samples"].append({col: row[col] for col in cols if col in row_keys})
    return out


def _load_document_presence(
    conn: sqlite3.Connection,
    schema: DocumentSchema | None,
    program_names: set[str],
) -> dict[str, dict[str, Any]]:
    if schema is None or not program_names:
        return {}
    cols = [schema.program_name_column]
    for col in (schema.name_column, schema.url_column, schema.source_url_column):
        if col and col not in cols:
            cols.append(col)
    placeholders = ",".join("?" for _ in program_names)
    sql = (
        "SELECT "
        + ", ".join(_qident(col) for col in cols)
        + f" FROM {_qident(schema.table)}"
        + f" WHERE {_qident(schema.program_name_column)} IN ({placeholders})"
    )
    out: dict[str, dict[str, Any]] = {}
    for row in conn.execute(sql, tuple(program_names)):
        program_name = str(row[schema.program_name_column])
        row_keys = set(row.keys())
        has_doc = bool(
            (schema.name_column and _truthy_text(row[schema.name_column]))
            or (schema.url_column and _truthy_text(row[schema.url_column]))
        )
        entry = out.setdefault(program_name, {"count": 0, "has_docs": False, "samples": []})
        entry["count"] += 1
        entry["has_docs"] = bool(entry["has_docs"] or has_doc)
        if len(entry["samples"]) < 3:
            entry["samples"].append({col: row[col] for col in cols if col in row_keys})
    return out


def _load_source_license_presence(
    conn: sqlite3.Connection,
    schema: SourceSchema | None,
    urls: set[str],
) -> dict[str, dict[str, Any]]:
    if schema is None or schema.license_column is None or not urls:
        return {}
    cols = [schema.source_url_column, schema.license_column]
    if schema.domain_column:
        cols.append(schema.domain_column)
    placeholders = ",".join("?" for _ in urls)
    sql = (
        "SELECT "
        + ", ".join(_qident(col) for col in cols)
        + f" FROM {_qident(schema.table)}"
        + f" WHERE {_qident(schema.source_url_column)} IN ({placeholders})"
    )
    out: dict[str, dict[str, Any]] = {}
    for row in conn.execute(sql, tuple(urls)):
        url = str(row[schema.source_url_column])
        license_value = row[schema.license_column]
        out[url] = {
            "license": license_value,
            "has_license": _truthy_text(license_value),
            "domain": row[schema.domain_column] if schema.domain_column else None,
        }
    return out


def _program_field_status(
    row: sqlite3.Row,
    *,
    schema: ProgramSchema,
    rounds: dict[str, dict[str, Any]],
    documents: dict[str, dict[str, Any]],
    sources: dict[str, dict[str, Any]],
    source_schema: SourceSchema | None,
) -> dict[str, dict[str, Any]]:
    keys = set(row.keys())
    program_id = str(row[schema.id_column])
    program_name = str(row[schema.name_column])
    enriched = _json_load(row["enriched_json"]) if "enriched_json" in keys else None
    window = (
        _json_load(row["application_window_json"]) if "application_window_json" in keys else None
    )

    field_status: dict[str, dict[str, Any]] = {}

    window_has_deadline, window_path = _json_has_deadline(window)
    enriched_has_deadline, enriched_deadline_path = _json_has_deadline(enriched)
    round_entry = rounds.get(program_id, {})
    deadline_source = None
    if window_has_deadline:
        deadline_source = f"program.{window_path}"
    elif round_entry.get("has_deadline"):
        deadline_source = f"{round_entry.get('count', 0)} application round row(s)"
    elif enriched_has_deadline:
        deadline_source = f"enriched.{enriched_deadline_path}"
    field_status["deadline"] = {
        "present": bool(deadline_source),
        "source": deadline_source,
    }

    amount_source = None
    if "amount_max_man_yen" in keys and _truthy_number(row["amount_max_man_yen"]):
        amount_source = "program.amount_max_man_yen"
    elif "amount_min_man_yen" in keys and _truthy_number(row["amount_min_man_yen"]):
        amount_source = "program.amount_min_man_yen"
    elif "amount_band" in keys and _truthy_text(row["amount_band"]):
        amount_source = "program.amount_band"
    else:
        enriched_has_amount, amount_path = _json_has_amount(enriched)
        if enriched_has_amount:
            amount_source = f"enriched.{amount_path}"
    field_status["amount"] = {"present": bool(amount_source), "source": amount_source}

    rate_source = None
    if "subsidy_rate" in keys and _truthy_number(row["subsidy_rate"]):
        rate_source = "program.subsidy_rate"
    elif "subsidy_rate_text" in keys and _truthy_text(row["subsidy_rate_text"]):
        rate_source = "program.subsidy_rate_text"
    else:
        enriched_has_rate, rate_path = _json_has_subsidy_rate(enriched)
        if enriched_has_rate:
            rate_source = f"enriched.{rate_path}"
    field_status["subsidy_rate"] = {"present": bool(rate_source), "source": rate_source}

    has_contact, contact_path = _json_has_contact(enriched)
    field_status["contact"] = {
        "present": bool(has_contact),
        "source": f"enriched.{contact_path}" if contact_path else None,
    }

    doc_entry = documents.get(program_name, {})
    enriched_has_docs, doc_path = _json_has_documents(enriched)
    doc_source = None
    if doc_entry.get("has_docs"):
        doc_source = f"{doc_entry.get('count', 0)} document row(s)"
    elif enriched_has_docs:
        doc_source = f"enriched.{doc_path}"
    field_status["required_docs"] = {"present": bool(doc_source), "source": doc_source}

    source_url = row["source_url"] if "source_url" in keys else None
    official_url = row["official_url"] if "official_url" in keys else None
    url_source = None
    if _truthy_text(source_url):
        url_source = "program.source_url"
    elif _truthy_text(official_url):
        url_source = "program.official_url"
    field_status["source_url"] = {"present": bool(url_source), "source": url_source}

    license_source = None
    license_value = None
    for url in (source_url, official_url):
        if not _truthy_text(url):
            continue
        source_entry = sources.get(str(url))
        if source_entry and source_entry.get("has_license"):
            license_source = f"{source_schema.table}.license" if source_schema else "source.license"
            license_value = source_entry.get("license")
            break
    field_status["license"] = {
        "present": bool(license_source),
        "source": license_source,
        "value": license_value,
    }

    return field_status


def _program_sample(
    row: sqlite3.Row,
    schema: ProgramSchema,
    link_reasons: list[str],
    field_status: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    keys = set(row.keys())
    missing = [field for field in REPORT_FIELDS if not field_status[field]["present"]]
    return {
        "program_id": row[schema.id_column],
        "primary_name": row[schema.name_column],
        "authority_name": row["authority_name"] if "authority_name" in keys else None,
        "official_url": row["official_url"] if "official_url" in keys else None,
        "source_url": row["source_url"] if "source_url" in keys else None,
        "link_reasons": link_reasons,
        "missing_fields": missing,
        "field_sources": {
            field: field_status[field].get("source")
            for field in REPORT_FIELDS
            if field_status[field]["present"]
        },
    }


def _count_jgrants_generic_url(rows: list[sqlite3.Row]) -> int:
    count = 0
    for row in rows:
        keys = set(row.keys())
        urls = [str(row[col] or "") for col in ("official_url", "source_url") if col in keys]
        if any(url.rstrip("/") == JGRANTS_GENERIC_SUBSIDY_URL for url in urls):
            count += 1
    return count


def inspect_local_jgrants_code(path: Path = INGEST_TIER_PATH) -> dict[str, Any]:
    """Summarize local JGrants ingest code without importing or executing it."""
    if not path.exists():
        return {"path": str(path.relative_to(REPO_ROOT)), "present": False}
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    hits: list[dict[str, Any]] = []
    for index, line in enumerate(lines, start=1):
        if "Jグランツ" in line or "jgrants" in line.lower() or "_fetch_jgrants" in line:
            hits.append({"line": index, "text": line.strip()})
    fetcher_stub = "_fetch_jgrants" in text and "return iter(())" in text
    uses_http_allowlist = "api.jgrants-portal.go.jp" in text and "www.jgrants-portal.go.jp" in text
    return {
        "path": str(path.relative_to(REPO_ROOT)),
        "present": True,
        "jgrants_hits": hits[:20],
        "fetcher_status": "stub_returns_no_rows" if fetcher_stub else "implemented_or_unknown",
        "http_allowlist_mentions_jgrants": uses_http_allowlist,
        "notes": [
            "Local code only: scripts/ingest_tier.py has a JGrants authority spec and _fetch_jgrants dispatch.",
            "No external docs or robots checks were performed by this report.",
        ],
    }


def _schema_dict(value: Any) -> dict[str, Any] | None:
    return asdict(value) if value is not None else None


def _program_insert_columns(schema: ProgramSchema) -> list[str]:
    required = [schema.id_column, schema.name_column]
    optional = [
        "aliases_json",
        "authority_level",
        "authority_name",
        "prefecture",
        "municipality",
        "program_kind",
        "official_url",
        "amount_max_man_yen",
        "amount_min_man_yen",
        "subsidy_rate",
        "subsidy_rate_text",
        "trust_level",
        "tier",
        "coverage_score",
        "gap_to_tier_s_json",
        "a_to_j_coverage_json",
        "excluded",
        "exclusion_reason",
        "target_types_json",
        "funding_purpose_json",
        "amount_band",
        "application_window_json",
        "enriched_json",
        "source_mentions_json",
        "source_url",
        "source_fetched_at",
        "source_checksum",
        "updated_at",
        "valid_from",
        "valid_until",
    ]
    columns: list[str] = []
    for col in [*required, *optional]:
        if col in schema.columns and col not in columns:
            columns.append(col)
    return columns


def build_schema_safe_upsert_plan(
    *,
    program_schema: ProgramSchema,
    round_schema: RoundSchema | None,
    document_schema: DocumentSchema | None,
    source_schema: SourceSchema | None,
    has_fts: bool,
) -> list[dict[str, Any]]:
    update_cols = [
        col
        for col in (
            "official_url",
            "source_url",
            "application_window_json",
            "amount_max_man_yen",
            "amount_min_man_yen",
            "subsidy_rate",
            "subsidy_rate_text",
            "enriched_json",
            "source_mentions_json",
            "source_fetched_at",
            "source_checksum",
            "updated_at",
            "valid_from",
        )
        if col in program_schema.columns
    ]
    program_update_sql = None
    if update_cols:
        program_update_sql = (
            f"UPDATE {_qident(program_schema.table)} SET "
            + ", ".join(f"{_qident(col)} = ?" for col in update_cols)
            + f" WHERE {_qident(program_schema.id_column)} = ?;"
        )
    insert_cols = _program_insert_columns(program_schema)
    program_insert_sql = (
        f"INSERT INTO {_qident(program_schema.table)} ("
        + ", ".join(_qident(col) for col in insert_cols)
        + ") VALUES ("
        + ", ".join("?" for _ in insert_cols)
        + ") "
        + f"ON CONFLICT({_qident(program_schema.id_column)}) DO UPDATE SET "
        + ", ".join(
            f"{_qident(col)} = excluded.{_qident(col)}"
            for col in insert_cols
            if col != program_schema.id_column
        )
        + ";"
    )
    plan: list[dict[str, Any]] = [
        {
            "target": program_schema.table,
            "operation": "upsert base program detail only after source payload is locally fetched and checksumed",
            "key": program_schema.id_column,
            "update_columns_present": update_cols,
            "insert_columns_present": insert_cols,
            "update_sql_preview": program_update_sql,
            "insert_sql_preview": insert_cols and program_insert_sql,
            "safety": "no DELETE; compare source_checksum before write; preserve existing source_fetched_at when checksum unchanged",
        }
    ]

    if round_schema is not None:
        round_cols = [
            col
            for col in (
                round_schema.program_id_column,
                round_schema.label_column,
                round_schema.open_column,
                round_schema.close_column,
                round_schema.status_column,
                round_schema.source_url_column,
            )
            if col
        ]
        conflict_cols = [
            round_schema.program_id_column,
            round_schema.label_column,
        ]
        conflict_cols = [col for col in conflict_cols if col]
        plan.append(
            {
                "target": round_schema.table,
                "operation": "upsert application windows when the table exists; otherwise keep deadline in application_window_json",
                "key": conflict_cols,
                "columns_present": round_cols,
                "sql_preview": (
                    f"INSERT INTO {_qident(round_schema.table)} ("
                    + ", ".join(_qident(col) for col in round_cols)
                    + ") VALUES ("
                    + ", ".join("?" for _ in round_cols)
                    + ") ON CONFLICT("
                    + ", ".join(_qident(col) for col in conflict_cols)
                    + ") DO UPDATE SET "
                    + ", ".join(
                        f"{_qident(col)} = excluded.{_qident(col)}"
                        for col in round_cols
                        if col not in conflict_cols
                    )
                    + ";"
                )
                if conflict_cols and len(conflict_cols) == 2
                else "table has no detected compound UNIQUE key; use guarded UPDATE then INSERT in one transaction",
            }
        )
    else:
        plan.append(
            {
                "target": program_schema.table,
                "operation": "store deadline in application_window_json",
                "available": "application_window_json" in program_schema.columns,
                "blocker_if_false": "no application round table and no application_window_json column",
            }
        )

    if document_schema is not None:
        doc_cols = [
            col
            for col in (
                document_schema.program_name_column,
                document_schema.name_column,
                document_schema.url_column,
                document_schema.source_url_column,
                "form_type" if "form_type" in document_schema.columns else None,
                "form_format" if "form_format" in document_schema.columns else None,
                "fetched_at" if "fetched_at" in document_schema.columns else None,
                "confidence" if "confidence" in document_schema.columns else None,
            )
            if col
        ]
        conflict_cols = [document_schema.program_name_column]
        if document_schema.url_column:
            conflict_cols.append(document_schema.url_column)
        plan.append(
            {
                "target": document_schema.table,
                "operation": "upsert required document/form rows",
                "key": conflict_cols,
                "columns_present": doc_cols,
                "sql_preview": (
                    f"INSERT INTO {_qident(document_schema.table)} ("
                    + ", ".join(_qident(col) for col in doc_cols)
                    + ") VALUES ("
                    + ", ".join("?" for _ in doc_cols)
                    + ") ON CONFLICT("
                    + ", ".join(_qident(col) for col in conflict_cols)
                    + ") DO UPDATE SET "
                    + ", ".join(
                        f"{_qident(col)} = excluded.{_qident(col)}"
                        for col in doc_cols
                        if col not in conflict_cols
                    )
                    + ";"
                )
                if len(conflict_cols) == 2
                else "document table lacks a detected URL key; use reviewed append-only insert",
            }
        )
    else:
        plan.append(
            {
                "target": "program_documents",
                "operation": "required docs cannot be normalized into a side table",
                "available": False,
            }
        )

    if source_schema is not None and source_schema.license_column is not None:
        source_cols = [
            col
            for col in (
                source_schema.source_url_column,
                source_schema.domain_column,
                source_schema.license_column,
            )
            if col
        ]
        plan.append(
            {
                "target": source_schema.table,
                "operation": "upsert source metadata/license before linking program fields",
                "key": source_schema.source_url_column,
                "columns_present": source_cols,
                "sql_preview": (
                    f"INSERT INTO {_qident(source_schema.table)} ("
                    + ", ".join(_qident(col) for col in source_cols)
                    + ") VALUES ("
                    + ", ".join("?" for _ in source_cols)
                    + f") ON CONFLICT({_qident(source_schema.source_url_column)}) DO UPDATE SET "
                    + ", ".join(
                        f"{_qident(col)} = excluded.{_qident(col)}"
                        for col in source_cols
                        if col != source_schema.source_url_column
                    )
                    + ";"
                ),
            }
        )
    else:
        plan.append(
            {
                "target": "source license",
                "operation": "license cannot be persisted in this DB shape",
                "available": False,
                "blocker": "no source table with both source_url and license columns",
            }
        )

    if has_fts:
        plan.append(
            {
                "target": f"{program_schema.table}_fts"
                if program_schema.table != "jpi_programs"
                else "programs_fts",
                "operation": "refresh one FTS row after a changed program upsert",
                "sql_preview": "DELETE existing FTS row by program id, then INSERT primary_name / aliases / flattened enriched text",
            }
        )
    return plan


def collect_jgrants_ingest_readiness(
    conn: sqlite3.Connection,
    *,
    sample_limit: int = DEFAULT_SAMPLE_LIMIT,
) -> dict[str, Any]:
    program_schema = inspect_program_schema(conn)
    round_schema = inspect_round_schema(conn)
    document_schema = inspect_document_schema(conn)
    source_schema = inspect_source_schema(conn)
    tables = set(_all_tables(conn))
    has_fts = "programs_fts" in tables or f"{program_schema.table}_fts" in tables

    all_rows = _program_rows(conn, program_schema)
    linked_rows: list[tuple[sqlite3.Row, list[str]]] = []
    direct_url_rows = 0
    text_reference_rows = 0
    for row in all_rows:
        reasons = _jgrants_link_reasons(row, program_schema)
        if not reasons:
            continue
        linked_rows.append((row, reasons))
        if any(reason in {"official_url:domain", "source_url:domain"} for reason in reasons):
            direct_url_rows += 1
        if any(reason.endswith(":text") for reason in reasons):
            text_reference_rows += 1

    program_ids = {str(row[program_schema.id_column]) for row, _ in linked_rows}
    program_names = {str(row[program_schema.name_column]) for row, _ in linked_rows}
    urls: set[str] = set()
    for row, _ in linked_rows:
        keys = set(row.keys())
        for col in ("source_url", "official_url"):
            if col in keys and _truthy_text(row[col]):
                urls.add(str(row[col]))

    rounds = _load_round_presence(conn, round_schema, program_ids)
    documents = _load_document_presence(conn, document_schema, program_names)
    sources = _load_source_license_presence(conn, source_schema, urls)

    field_missing: dict[str, list[dict[str, Any]]] = {field: [] for field in REPORT_FIELDS}
    field_present_counts = dict.fromkeys(REPORT_FIELDS, 0)
    samples: list[dict[str, Any]] = []

    for row, reasons in linked_rows:
        row_keys = set(row.keys())
        field_status = _program_field_status(
            row,
            schema=program_schema,
            rounds=rounds,
            documents=documents,
            sources=sources,
            source_schema=source_schema,
        )
        sample = _program_sample(row, program_schema, reasons, field_status)
        if len(samples) < sample_limit:
            samples.append(sample)
        for field in REPORT_FIELDS:
            if field_status[field]["present"]:
                field_present_counts[field] += 1
            elif len(field_missing[field]) < sample_limit:
                field_missing[field].append(
                    # Keep missing samples compact; source columns are optional
                    # across the temp/test and local production schemas.
                    {
                        "program_id": row[program_schema.id_column],
                        "primary_name": row[program_schema.name_column],
                        "source_url": row["source_url"] if "source_url" in row_keys else None,
                        "official_url": row["official_url"] if "official_url" in row_keys else None,
                        "link_reasons": reasons,
                    }
                )

    linked_count = len(linked_rows)
    missing_structured_fields = {
        field: {
            "present": field_present_counts[field],
            "missing": linked_count - field_present_counts[field],
            "missing_pct": round(
                ((linked_count - field_present_counts[field]) / linked_count * 100.0)
                if linked_count
                else 0.0,
                2,
            ),
        }
        for field in REPORT_FIELDS
    }
    rows_missing_any = 0
    for sample_like_row, _reasons in linked_rows:
        field_status = _program_field_status(
            sample_like_row,
            schema=program_schema,
            rounds=rounds,
            documents=documents,
            sources=sources,
            source_schema=source_schema,
        )
        if any(not field_status[field]["present"] for field in REPORT_FIELDS):
            rows_missing_any += 1

    blockers: list[str] = []
    if linked_count == 0:
        blockers.append("no local JGrants-linked programs detected")
    if source_schema is None or source_schema.license_column is None:
        blockers.append(
            "no source table with a license column; license readiness cannot be proven locally"
        )
    elif missing_structured_fields["license"]["missing"]:
        blockers.append("JGrants-linked source URLs do not have complete local license rows")
    if document_schema is None:
        blockers.append("no program document table detected for normalized required_docs")
    elif missing_structured_fields["required_docs"]["missing"]:
        blockers.append("required_docs are missing for at least one JGrants-linked program")
    if missing_structured_fields["deadline"]["missing"]:
        blockers.append(
            "deadline/application window is missing for at least one JGrants-linked program"
        )
    if missing_structured_fields["contact"]["missing"]:
        blockers.append("contact is missing for at least one JGrants-linked program")
    if inspect_local_jgrants_code().get("fetcher_status") == "stub_returns_no_rows":
        blockers.append("scripts/ingest_tier.py _fetch_jgrants is still a no-row stub")

    upsert_plan = build_schema_safe_upsert_plan(
        program_schema=program_schema,
        round_schema=round_schema,
        document_schema=document_schema,
        source_schema=source_schema,
        has_fts=has_fts,
    )

    return {
        "report": "b8_jgrants_ingest_readiness",
        "generated_at": _utc_now(),
        "report_only": True,
        "mutates_db": False,
        "external_api_calls": False,
        "external_api_policy": (
            "local-only default; JGrants API/portal must not be called until robots/"
            "official documentation and terms are separately confirmed"
        ),
        "schema": {
            "program": _schema_dict(program_schema),
            "application_round": _schema_dict(round_schema),
            "document": _schema_dict(document_schema),
            "source": _schema_dict(source_schema),
            "has_programs_fts": has_fts,
        },
        "code_usage": inspect_local_jgrants_code(),
        "totals": {
            "program_rows": len(all_rows),
            "jgrants_linked_program_rows": linked_count,
            "jgrants_direct_url_rows": direct_url_rows,
            "jgrants_text_reference_rows": text_reference_rows,
            "jgrants_generic_subsidy_url_rows": _count_jgrants_generic_url(
                [row for row, _ in linked_rows]
            ),
            "rows_missing_any_required_field": rows_missing_any,
        },
        "missing_structured_fields": missing_structured_fields,
        "samples": {
            "jgrants_linked_programs": samples,
            "missing_by_field": field_missing,
        },
        "blockers": blockers,
        "schema_safe_upsert_plan": upsert_plan,
    }


def write_report(report: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--sample-limit", type=int, default=DEFAULT_SAMPLE_LIMIT)
    args = parser.parse_args(argv)

    with _connect_readonly(args.db) as conn:
        report = collect_jgrants_ingest_readiness(conn, sample_limit=args.sample_limit)
    report["database"] = str(args.db)
    write_report(report, args.output)
    summary = {
        "output": str(args.output),
        "jgrants_linked_program_rows": report["totals"]["jgrants_linked_program_rows"],
        "rows_missing_any_required_field": report["totals"]["rows_missing_any_required_field"],
        "blockers": len(report["blockers"]),
    }
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
