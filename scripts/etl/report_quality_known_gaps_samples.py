#!/usr/bin/env python3
"""A8 report-only sampler for quality known gaps.

This script samples local program, statistic, and source records from SQLite,
runs ``services.quality_gaps.build_known_gaps`` over the sampled evidence/facts,
and writes a JSON report of gap categories plus the remaining evidence-packet
integration work.

It performs no network fetches, no LLM calls, and no database mutation.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from jpintel_mcp.services.quality_gaps import (  # noqa: E402
    REQUIRED_FACT_ALIASES,
    build_known_gaps,
)

DEFAULT_AUTONOMATH_DB = REPO_ROOT / "autonomath.db"
DEFAULT_JPINTEL_DB = REPO_ROOT / "data" / "jpintel.db"
DEFAULT_OUTPUT = REPO_ROOT / "analysis_wave18" / "quality_known_gaps_samples_2026-05-01.json"
DEFAULT_AS_OF = "2026-05-01"

DEFAULT_PROGRAM_LIMIT = 12
DEFAULT_STATISTIC_LIMIT = 8
DEFAULT_SOURCE_LIMIT = 10

PROGRAM_TABLES = ("jpi_programs", "programs")
PROGRAM_ID_COLUMNS = ("unified_id", "canonical_id", "program_id", "id")
PROGRAM_NAME_COLUMNS = ("primary_name", "program_name", "name", "title")
PROGRAM_SOURCE_COLUMNS = ("source_url", "official_url", "url")
PROGRAM_AMOUNT_COLUMNS = (
    "amount_max_man_yen",
    "amount_max_yen",
    "max_amount_yen",
    "grant_amount_max_yen",
)

STATISTIC_TABLES = (
    "am_acceptance_stat",
    "pc_acceptance_stats_by_program",
    "industry_stats",
)
STATISTIC_ID_COLUMNS = ("id", "program_entity_id", "program_id")
STATISTIC_SOURCE_COLUMNS = ("source_url", "official_url", "url")
STATISTIC_REQUIRED_FACT_ALIASES: dict[str, tuple[str, ...]] = {
    "stat_value": (
        "accepted_count",
        "acceptance_rate",
        "acceptance_rate_pct",
        "applied_count",
        "employee_count_total",
        "establishment_count",
    ),
    "stat_context": (
        "fiscal_year",
        "program_entity_id",
        "program_id",
        "round_label",
        "statistic_source",
    ),
}

SOURCE_TABLE = "am_source"
SOURCE_ID_COLUMNS = ("id", "source_id")
SOURCE_URL_COLUMNS = ("source_url", "url")
SOURCE_LICENSE_COLUMNS = ("license", "license_id", "license_status", "rights")
SOURCE_VERIFIED_COLUMNS = ("last_verified", "last_verified_at", "verified_at")
SOURCE_STATUS_COLUMNS = ("canonical_status", "verification_status", "source_status", "status")


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


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('table', 'view') AND name = ?",
        (table,),
    ).fetchone()
    return row is not None


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    try:
        return {str(row["name"]) for row in conn.execute(f"PRAGMA table_info({_qident(table)})")}
    except sqlite3.OperationalError:
        return set()


def _choose_column(columns: set[str], candidates: Iterable[str]) -> str | None:
    for candidate in candidates:
        if candidate in columns:
            return candidate
    return None


def _select_expr(columns: set[str], candidates: Iterable[str], alias: str) -> str:
    column = _choose_column(columns, candidates)
    if column is None:
        return f"NULL AS {_qident(alias)}"
    return f"{_qident(column)} AS {_qident(alias)}"


def _present(value: object) -> bool:
    return value is not None and str(value).strip() != ""


def _pct(part: int, total: int) -> float:
    if total == 0:
        return 0.0
    return round(part / total, 4)


def _trim(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _json_loads(value: object) -> Any:
    if not _present(value):
        return None
    try:
        return json.loads(str(value))
    except (TypeError, ValueError):
        return None


def _source_url_key(value: object) -> str | None:
    return _trim(value)


def _source_table_available(conn: sqlite3.Connection) -> bool:
    return _table_exists(conn, SOURCE_TABLE) and bool(
        _choose_column(_columns(conn, SOURCE_TABLE), SOURCE_URL_COLUMNS)
    )


def _source_row_from_sql(row: sqlite3.Row, *, table_ref: str) -> dict[str, Any]:
    return {
        "source_id": row["source_id"],
        "source_url": row["source_url"],
        "license": row["license"],
        "last_verified_at": row["last_verified_at"],
        "verification_status": row["verification_status"],
        "source_type": row["source_type"],
        "domain": row["domain"],
        "table_ref": table_ref,
    }


def _load_source_index(
    conn_pairs: Iterable[tuple[str, sqlite3.Connection]],
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    for label, conn in conn_pairs:
        if not _source_table_available(conn):
            continue
        columns = _columns(conn, SOURCE_TABLE)
        id_column = _choose_column(columns, SOURCE_ID_COLUMNS)
        if id_column is None:
            continue
        exprs = [
            f"{_qident(id_column)} AS {_qident('source_id')}",
            _select_expr(columns, SOURCE_URL_COLUMNS, "source_url"),
            _select_expr(columns, SOURCE_LICENSE_COLUMNS, "license"),
            _select_expr(columns, SOURCE_VERIFIED_COLUMNS, "last_verified_at"),
            _select_expr(columns, SOURCE_STATUS_COLUMNS, "verification_status"),
            _select_expr(columns, ("source_type",), "source_type"),
            _select_expr(columns, ("domain",), "domain"),
        ]
        table_ref = f"{label}.{SOURCE_TABLE}"
        rows = conn.execute(
            f"SELECT {', '.join(exprs)} FROM {_qident(SOURCE_TABLE)} ORDER BY {_qident(id_column)}"
        )
        source_index: dict[str, dict[str, Any]] = {}
        row_count = 0
        for row in rows:
            row_count += 1
            key = _source_url_key(row["source_url"])
            if key and key not in source_index:
                source_index[key] = _source_row_from_sql(row, table_ref=table_ref)
        return source_index, {
            "source_index_table": table_ref,
            "source_index_rows": row_count,
            "source_index_url_keys": len(source_index),
        }
    return {}, {
        "source_index_table": None,
        "source_index_rows": 0,
        "source_index_url_keys": 0,
    }


def _source_lookup(
    source_index: Mapping[str, dict[str, Any]],
    source_url: object,
) -> dict[str, Any] | None:
    key = _source_url_key(source_url)
    if key is None:
        return None
    return source_index.get(key)


def _evidence_from_source(
    source: Mapping[str, Any] | None,
    *,
    fallback_url: object,
) -> dict[str, Any]:
    if source is not None:
        return {
            "source_id": source.get("source_id"),
            "source_url": source.get("source_url"),
            "license": source.get("license"),
            "last_verified_at": source.get("last_verified_at"),
            "verification_status": source.get("verification_status"),
        }
    return {
        "source_id": None,
        "source_url": _trim(fallback_url),
        "license": None,
        "last_verified_at": None,
        "verification_status": None,
    }


def _fact_value_key(value: object) -> str:
    if isinstance(value, int | float) and not isinstance(value, bool):
        return "field_value_numeric"
    if isinstance(value, list | dict):
        return "field_value_json"
    return "field_value_text"


def _make_fact(
    *,
    record_ref: str,
    field_name: str,
    value: object,
    source: Mapping[str, Any] | None,
    fallback_url: object,
) -> dict[str, Any] | None:
    if not _present(value) and not isinstance(value, (int, float)):
        return None
    fact: dict[str, Any] = {
        "fact_id": f"{record_ref}:{field_name}",
        "field_name": field_name,
        "source_id": source.get("source_id") if source is not None else None,
        "source_url": source.get("source_url") if source is not None else _trim(fallback_url),
    }
    fact[_fact_value_key(value)] = value
    return fact


def _extract_deadline(application_window_json: object, enriched_json: object) -> str | None:
    for payload in (_json_loads(application_window_json), _json_loads(enriched_json)):
        if not isinstance(payload, dict):
            continue
        direct = payload.get("end_date") or payload.get("deadline")
        if _present(direct):
            return str(direct)
        schedule = payload.get("schedule")
        if isinstance(schedule, dict):
            scheduled = schedule.get("end_date") or schedule.get("deadline")
            if _present(scheduled):
                return str(scheduled)
        windows = payload.get("windows")
        if isinstance(windows, list):
            for window in windows:
                if not isinstance(window, dict):
                    continue
                window_end = window.get("end_date") or window.get("deadline")
                if _present(window_end):
                    return str(window_end)
    return None


def _extract_contact(enriched_json: object) -> str | None:
    payload = _json_loads(enriched_json)
    if not isinstance(payload, dict):
        return None
    contacts = payload.get("contacts")
    if not isinstance(contacts, list):
        return None
    for contact in contacts:
        if not isinstance(contact, dict):
            continue
        for key in ("email", "contact_email", "phone", "office_name"):
            value = contact.get(key)
            if _present(value):
                return str(value)
    return None


def _pick_balanced(
    candidates: list[dict[str, Any]],
    bucket_targets: list[tuple[str, int]],
    *,
    limit: int,
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    selected_ids: set[str] = set()
    for bucket, target in bucket_targets:
        if target <= 0:
            continue
        for candidate in candidates:
            if candidate["selection_reason"] != bucket:
                continue
            sample_id = candidate["sample_id"]
            if sample_id in selected_ids:
                continue
            selected.append(candidate)
            selected_ids.add(sample_id)
            if sum(1 for row in selected if row["selection_reason"] == bucket) >= target:
                break
        if len(selected) >= limit:
            break

    if len(selected) < limit:
        for candidate in candidates:
            sample_id = candidate["sample_id"]
            if sample_id in selected_ids:
                continue
            selected.append(candidate)
            selected_ids.add(sample_id)
            if len(selected) >= limit:
                break
    return selected[:limit]


def _sample_with_gaps(
    *,
    sample_id: str,
    record_type: str,
    table_ref: str,
    record_ref: object,
    label: object,
    source_url: object,
    source: Mapping[str, Any] | None,
    facts: list[dict[str, Any]],
    selection_reason: str,
    as_of: str,
    required_fact_aliases: Mapping[str, Iterable[str]],
) -> dict[str, Any]:
    evidence = _evidence_from_source(source, fallback_url=source_url)
    gaps = build_known_gaps(
        evidence=[evidence],
        facts=facts,
        as_of=as_of,
        required_fact_aliases=required_fact_aliases,
    )
    return {
        "sample_id": sample_id,
        "record_type": record_type,
        "table": table_ref,
        "record_ref": record_ref,
        "label": label,
        "source_url": _trim(source_url),
        "source_id": evidence.get("source_id"),
        "selection_reason": selection_reason,
        "facts_checked": [fact["field_name"] for fact in facts],
        "known_gaps": gaps,
        "gap_codes": sorted({str(gap["code"]) for gap in gaps}),
        "gap_count": len(gaps),
        "has_known_gap": bool(gaps),
    }


def _collect_program_candidates(
    label: str,
    conn: sqlite3.Connection,
    *,
    source_index: Mapping[str, dict[str, Any]],
    as_of: str,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for table in PROGRAM_TABLES:
        if not _table_exists(conn, table):
            continue
        columns = _columns(conn, table)
        id_column = _choose_column(columns, PROGRAM_ID_COLUMNS)
        name_column = _choose_column(columns, PROGRAM_NAME_COLUMNS)
        if id_column is None or name_column is None:
            continue
        exprs = [
            f"{_qident(id_column)} AS {_qident('record_id')}",
            f"{_qident(name_column)} AS {_qident('name')}",
            _select_expr(columns, PROGRAM_SOURCE_COLUMNS, "source_url"),
            _select_expr(columns, PROGRAM_AMOUNT_COLUMNS, "amount"),
            _select_expr(columns, ("application_window_json",), "application_window_json"),
            _select_expr(columns, ("enriched_json",), "enriched_json"),
        ]
        table_ref = f"{label}.{table}"
        rows = conn.execute(
            f"SELECT {', '.join(exprs)} FROM {_qident(table)} ORDER BY {_qident(id_column)}"
        )
        for row in rows:
            record_ref = str(row["record_id"])
            source = _source_lookup(source_index, row["source_url"])
            if not _present(row["source_url"]):
                selection_reason = "program_missing_source_url"
            elif source is None:
                selection_reason = "program_source_not_indexed"
            else:
                selection_reason = "program_source_indexed"

            facts: list[dict[str, Any]] = []
            for field_name, value in (
                ("primary_name", row["name"]),
                ("amount_max_man_yen", row["amount"]),
                (
                    "application_deadline",
                    _extract_deadline(row["application_window_json"], row["enriched_json"]),
                ),
                ("contact", _extract_contact(row["enriched_json"])),
            ):
                fact = _make_fact(
                    record_ref=record_ref,
                    field_name=field_name,
                    value=value,
                    source=source,
                    fallback_url=row["source_url"],
                )
                if fact is not None:
                    facts.append(fact)

            candidates.append(
                _sample_with_gaps(
                    sample_id=f"program:{record_ref}",
                    record_type="program",
                    table_ref=table_ref,
                    record_ref=record_ref,
                    label=row["name"],
                    source_url=row["source_url"],
                    source=source,
                    facts=facts,
                    selection_reason=selection_reason,
                    as_of=as_of,
                    required_fact_aliases=REQUIRED_FACT_ALIASES,
                )
            )
        if candidates:
            return candidates
    return candidates


def _collect_program_samples(
    conn_pairs: Iterable[tuple[str, sqlite3.Connection]],
    *,
    source_index: Mapping[str, dict[str, Any]],
    limit: int,
    as_of: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    for label, conn in conn_pairs:
        candidates = _collect_program_candidates(
            label,
            conn,
            source_index=source_index,
            as_of=as_of,
        )
        if not candidates:
            continue
        samples = _pick_balanced(
            candidates,
            [
                ("program_source_indexed", max(1, limit // 3)),
                ("program_source_not_indexed", max(1, limit // 3)),
                ("program_missing_source_url", max(1, limit // 6)),
            ],
            limit=limit,
        )
        return samples, {
            "program_table": samples[0]["table"] if samples else None,
            "program_candidate_rows": len(candidates),
        }
    return [], {"program_table": None, "program_candidate_rows": 0}


def _stat_fact_fields(row: sqlite3.Row) -> list[tuple[str, object]]:
    return [
        ("program_entity_id", row["program_entity_id"]),
        ("program_id", row["program_id"]),
        ("round_label", row["round_label"]),
        ("fiscal_year", row["fiscal_year"]),
        ("statistic_source", row["statistic_source"]),
        ("applied_count", row["applied_count"]),
        ("accepted_count", row["accepted_count"]),
        ("acceptance_rate_pct", row["acceptance_rate_pct"]),
        ("acceptance_rate", row["acceptance_rate"]),
        ("establishment_count", row["establishment_count"]),
        ("employee_count_total", row["employee_count_total"]),
    ]


def _collect_statistic_candidates(
    label: str,
    conn: sqlite3.Connection,
    *,
    source_index: Mapping[str, dict[str, Any]],
    as_of: str,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for table in STATISTIC_TABLES:
        if not _table_exists(conn, table):
            continue
        columns = _columns(conn, table)
        if not columns:
            continue
        exprs = [
            _select_expr(columns, STATISTIC_ID_COLUMNS, "record_id"),
            _select_expr(columns, ("program_entity_id",), "program_entity_id"),
            _select_expr(columns, ("program_id",), "program_id"),
            _select_expr(columns, ("round_label",), "round_label"),
            _select_expr(columns, ("fiscal_year", "statistic_year"), "fiscal_year"),
            _select_expr(columns, ("statistic_source",), "statistic_source"),
            _select_expr(columns, ("applied_count",), "applied_count"),
            _select_expr(columns, ("accepted_count",), "accepted_count"),
            _select_expr(columns, ("acceptance_rate_pct",), "acceptance_rate_pct"),
            _select_expr(columns, ("acceptance_rate",), "acceptance_rate"),
            _select_expr(columns, ("establishment_count",), "establishment_count"),
            _select_expr(columns, ("employee_count_total",), "employee_count_total"),
            _select_expr(columns, STATISTIC_SOURCE_COLUMNS, "source_url"),
        ]
        order_column = _choose_column(columns, STATISTIC_ID_COLUMNS) or "rowid"
        order_expr = _qident(order_column) if order_column != "rowid" else "rowid"
        table_ref = f"{label}.{table}"
        rows = conn.execute(
            f"SELECT {', '.join(exprs)} FROM {_qident(table)} ORDER BY {order_expr}"
        )
        for index, row in enumerate(rows, start=1):
            record_ref = str(row["record_id"] or f"{table}:{index}")
            source = _source_lookup(source_index, row["source_url"])
            if not _present(row["source_url"]):
                selection_reason = "statistic_missing_source_url"
            elif source is None:
                selection_reason = "statistic_source_not_indexed"
            else:
                selection_reason = "statistic_source_indexed"

            facts = []
            for field_name, value in _stat_fact_fields(row):
                fact = _make_fact(
                    record_ref=record_ref,
                    field_name=field_name,
                    value=value,
                    source=source,
                    fallback_url=row["source_url"],
                )
                if fact is not None:
                    facts.append(fact)

            label_text = row["program_entity_id"] or row["program_id"] or row["statistic_source"]
            candidates.append(
                _sample_with_gaps(
                    sample_id=f"statistic:{table}:{record_ref}",
                    record_type="statistic",
                    table_ref=table_ref,
                    record_ref=record_ref,
                    label=label_text,
                    source_url=row["source_url"],
                    source=source,
                    facts=facts,
                    selection_reason=selection_reason,
                    as_of=as_of,
                    required_fact_aliases=STATISTIC_REQUIRED_FACT_ALIASES,
                )
            )
        if candidates:
            return candidates
    return candidates


def _collect_statistic_samples(
    conn_pairs: Iterable[tuple[str, sqlite3.Connection]],
    *,
    source_index: Mapping[str, dict[str, Any]],
    limit: int,
    as_of: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    for label, conn in conn_pairs:
        candidates = _collect_statistic_candidates(
            label,
            conn,
            source_index=source_index,
            as_of=as_of,
        )
        if not candidates:
            continue
        samples = _pick_balanced(
            candidates,
            [
                ("statistic_source_indexed", max(1, limit // 2)),
                ("statistic_source_not_indexed", max(1, limit // 3)),
                ("statistic_missing_source_url", max(1, limit // 6)),
            ],
            limit=limit,
        )
        return samples, {
            "statistic_table": samples[0]["table"] if samples else None,
            "statistic_candidate_rows": len(candidates),
        }
    return [], {"statistic_table": None, "statistic_candidate_rows": 0}


def _source_selection_reason(source: Mapping[str, Any]) -> str:
    license_value = str(source.get("license") or "").strip().lower()
    if license_value in {"blocked", "copyright_blocked", "license_blocked", "proprietary"}:
        return "source_license_blocked"
    if license_value in {"", "none", "null", "unknown", "unlicensed", "unspecified"}:
        return "source_license_unknown"
    if not _present(source.get("last_verified_at")):
        return "source_unverified"
    return "source_clean"


def _collect_source_candidates(
    label: str,
    conn: sqlite3.Connection,
    *,
    as_of: str,
) -> list[dict[str, Any]]:
    if not _source_table_available(conn):
        return []
    columns = _columns(conn, SOURCE_TABLE)
    id_column = _choose_column(columns, SOURCE_ID_COLUMNS)
    if id_column is None:
        return []
    exprs = [
        f"{_qident(id_column)} AS {_qident('source_id')}",
        _select_expr(columns, SOURCE_URL_COLUMNS, "source_url"),
        _select_expr(columns, SOURCE_LICENSE_COLUMNS, "license"),
        _select_expr(columns, SOURCE_VERIFIED_COLUMNS, "last_verified_at"),
        _select_expr(columns, SOURCE_STATUS_COLUMNS, "verification_status"),
        _select_expr(columns, ("source_type",), "source_type"),
        _select_expr(columns, ("domain",), "domain"),
    ]
    table_ref = f"{label}.{SOURCE_TABLE}"
    rows = conn.execute(
        f"SELECT {', '.join(exprs)} FROM {_qident(SOURCE_TABLE)} ORDER BY {_qident(id_column)}"
    )
    candidates = []
    for row in rows:
        source = _source_row_from_sql(row, table_ref=table_ref)
        record_ref = str(source["source_id"])
        selection_reason = _source_selection_reason(source)
        candidates.append(
            _sample_with_gaps(
                sample_id=f"source:{record_ref}",
                record_type="source",
                table_ref=table_ref,
                record_ref=record_ref,
                label=source["domain"] or source["source_url"],
                source_url=source["source_url"],
                source=source,
                facts=[],
                selection_reason=selection_reason,
                as_of=as_of,
                required_fact_aliases={},
            )
        )
    return candidates


def _collect_source_samples(
    conn_pairs: Iterable[tuple[str, sqlite3.Connection]],
    *,
    limit: int,
    as_of: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    for label, conn in conn_pairs:
        candidates = _collect_source_candidates(label, conn, as_of=as_of)
        if not candidates:
            continue
        samples = _pick_balanced(
            candidates,
            [
                ("source_license_unknown", max(1, limit // 3)),
                ("source_unverified", max(1, limit // 3)),
                ("source_clean", max(1, limit // 3)),
                ("source_license_blocked", 1),
            ],
            limit=limit,
        )
        return samples, {
            "source_table": samples[0]["table"] if samples else None,
            "source_candidate_rows": len(candidates),
        }
    return [], {"source_table": None, "source_candidate_rows": 0}


def _gap_category_summary(samples: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    by_code: dict[str, dict[str, Any]] = {}
    affected: dict[str, set[str]] = defaultdict(set)
    for sample in samples:
        for gap in sample["known_gaps"]:
            code = str(gap["code"])
            affected[code].add(str(sample["sample_id"]))
            item = by_code.setdefault(
                code,
                {
                    "gap_occurrences": 0,
                    "affected_samples": 0,
                    "severity_counts": Counter(),
                    "subject_counts": Counter(),
                },
            )
            item["gap_occurrences"] += 1
            item["severity_counts"][str(gap.get("severity", "unknown"))] += 1
            item["subject_counts"][str(gap.get("subject", "unknown"))] += 1

    normalized: dict[str, dict[str, Any]] = {}
    for code, item in sorted(by_code.items()):
        normalized[code] = {
            "gap_occurrences": item["gap_occurrences"],
            "affected_samples": len(affected[code]),
            "severity_counts": dict(sorted(item["severity_counts"].items())),
            "subject_counts": dict(sorted(item["subject_counts"].items())),
        }
    return normalized


def _counter_dict(counter: Counter[str]) -> dict[str, int]:
    return dict(sorted(counter.items()))


def _integration_needs() -> list[dict[str, str]]:
    return [
        {
            "need": "Evidence packet output needs a stable known_gaps field.",
            "status": "not_wired_here",
            "reason": "This task is report-only and evidence_packet.py is protected.",
        },
        {
            "need": "EvidencePacketComposer needs to pass per-record evidence rows into build_known_gaps.",
            "status": "pending_protected_integration",
            "reason": "The sampler proves the helper contract without editing packet composition.",
        },
        {
            "need": "Fact rows need source_id/source_url propagation before packet serialization.",
            "status": "pending_protected_integration",
            "reason": "missing_source_id gaps remain visible until packet facts carry source IDs.",
        },
        {
            "need": "Conflict metadata should be supplied to build_known_gaps when packet facts disagree.",
            "status": "pending_protected_integration",
            "reason": "This report samples local rows but does not compute cross-source conflicts.",
        },
    ]


def collect_quality_known_gaps_samples(
    autonomath_conn: sqlite3.Connection,
    jpintel_conn: sqlite3.Connection | None = None,
    *,
    as_of: str = DEFAULT_AS_OF,
    program_limit: int = DEFAULT_PROGRAM_LIMIT,
    statistic_limit: int = DEFAULT_STATISTIC_LIMIT,
    source_limit: int = DEFAULT_SOURCE_LIMIT,
) -> dict[str, Any]:
    """Collect representative quality-gap samples without mutating SQLite."""
    jp_conn = jpintel_conn or autonomath_conn
    conn_pairs = [("autonomath", autonomath_conn)]
    if jp_conn is not autonomath_conn:
        conn_pairs.append(("jpintel", jp_conn))

    source_index, source_index_meta = _load_source_index(conn_pairs)
    program_samples, program_meta = _collect_program_samples(
        conn_pairs,
        source_index=source_index,
        limit=program_limit,
        as_of=as_of,
    )
    statistic_samples, statistic_meta = _collect_statistic_samples(
        conn_pairs,
        source_index=source_index,
        limit=statistic_limit,
        as_of=as_of,
    )
    source_samples, source_meta = _collect_source_samples(
        conn_pairs,
        limit=source_limit,
        as_of=as_of,
    )

    samples = [*program_samples, *statistic_samples, *source_samples]
    sample_counts = Counter(str(sample["record_type"]) for sample in samples)
    selection_counts = Counter(str(sample["selection_reason"]) for sample in samples)
    records_with_gaps = sum(1 for sample in samples if sample["has_known_gap"])
    records_without_gaps = len(samples) - records_with_gaps
    gap_counts_by_type: Counter[str] = Counter()
    for sample in samples:
        gap_counts_by_type[str(sample["record_type"])] += int(sample["gap_count"])

    return {
        "ok": True,
        "complete": False,
        "generated_at": _utc_now(),
        "as_of": as_of,
        "scope": (
            "A8 report-only sample of local program/statistic/source rows using "
            "services.quality_gaps.build_known_gaps; no evidence_packet wiring"
        ),
        "read_mode": {
            "sqlite_only": True,
            "network_fetch_performed": False,
            "llm_call_performed": False,
            "db_mutation_performed": False,
        },
        "input_tables": {
            **source_index_meta,
            **program_meta,
            **statistic_meta,
            **source_meta,
        },
        "requested_sample_limits": {
            "program": program_limit,
            "statistic": statistic_limit,
            "source": source_limit,
            "total": program_limit + statistic_limit + source_limit,
        },
        "sample_counts": {
            "program": sample_counts.get("program", 0),
            "statistic": sample_counts.get("statistic", 0),
            "source": sample_counts.get("source", 0),
            "total": len(samples),
        },
        "selection_counts": _counter_dict(selection_counts),
        "gap_coverage": {
            "sampled_records": len(samples),
            "records_with_known_gaps": records_with_gaps,
            "records_without_known_gaps": records_without_gaps,
            "gap_coverage_ratio": _pct(records_with_gaps, len(samples)),
        },
        "gap_counts_by_record_type": _counter_dict(gap_counts_by_type),
        "known_gap_categories": _gap_category_summary(samples),
        "evidence_packet_integration_still_needs": _integration_needs(),
        "completion_status": {
            "A8": "report_only",
            "complete": False,
            "reason": (
                "quality_gaps helper is exercised on samples, but evidence_packet.py "
                "integration is intentionally not wired because it is protected."
            ),
        },
        "samples": samples,
    }


def write_report(report: Mapping[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--autonomath-db", type=Path, default=DEFAULT_AUTONOMATH_DB)
    parser.add_argument("--jpintel-db", type=Path, default=DEFAULT_JPINTEL_DB)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--as-of", default=DEFAULT_AS_OF)
    parser.add_argument("--program-limit", type=int, default=DEFAULT_PROGRAM_LIMIT)
    parser.add_argument("--statistic-limit", type=int, default=DEFAULT_STATISTIC_LIMIT)
    parser.add_argument("--source-limit", type=int, default=DEFAULT_SOURCE_LIMIT)
    parser.add_argument("--json", action="store_true", help="print full JSON report")
    parser.add_argument("--no-write", action="store_true", help="do not write --output")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    with _connect_readonly(args.autonomath_db) as autonomath_conn:
        if args.jpintel_db.resolve() == args.autonomath_db.resolve():
            report = collect_quality_known_gaps_samples(
                autonomath_conn,
                autonomath_conn,
                as_of=args.as_of,
                program_limit=args.program_limit,
                statistic_limit=args.statistic_limit,
                source_limit=args.source_limit,
            )
        else:
            with _connect_readonly(args.jpintel_db) as jpintel_conn:
                report = collect_quality_known_gaps_samples(
                    autonomath_conn,
                    jpintel_conn,
                    as_of=args.as_of,
                    program_limit=args.program_limit,
                    statistic_limit=args.statistic_limit,
                    source_limit=args.source_limit,
                )

    report["inputs"] = {
        "autonomath_db": str(args.autonomath_db),
        "jpintel_db": str(args.jpintel_db),
    }

    if not args.no_write:
        write_report(report, args.output)

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        counts = report["sample_counts"]
        coverage = report["gap_coverage"]
        categories = report["known_gap_categories"]
        print(f"sampled_records={counts['total']}")
        print(f"program_samples={counts['program']}")
        print(f"statistic_samples={counts['statistic']}")
        print(f"source_samples={counts['source']}")
        print(f"records_with_known_gaps={coverage['records_with_known_gaps']}")
        print(f"gap_coverage_ratio={coverage['gap_coverage_ratio']:.4f}")
        print(f"known_gap_categories={','.join(categories) if categories else '(none)'}")
        print("complete=False")
        if not args.no_write:
            print(f"output={args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
