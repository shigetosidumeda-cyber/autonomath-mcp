#!/usr/bin/env python3
"""Fail-closed safety checks for public HuggingFace dataset exports."""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

REDISTRIBUTABLE_LICENSES = frozenset(
    {
        "pdl_v1.0",
        "gov_standard",
        "gov_standard_v2.0",
        "cc_by_4.0",
        "public_domain",
    }
)
BLOCKED_LICENSES = frozenset({"proprietary", "unknown"})
MIN_SAFE_AGGREGATE_ROWS = 5

_AGGREGATE_COUNT_COLUMNS = frozenset(
    {
        "count",
        "row_count",
        "rows",
        "n",
        "total",
        "registrant_count",
        "adoption_count",
        "enforcement_count",
        "five_year_count",
        "case_count",
        "recipient_count",
        "company_count",
    }
)
_AGGREGATE_QUERY_TOKENS = (" group by ", " count(", " sum(", " avg(", " min(", " max(")
_SENSITIVE_TABLES = frozenset(
    {
        "invoice_registrants",
        "jpi_invoice_registrants",
        "adoption_records",
        "jpi_adoption_records",
        "case_studies",
        "enforcement_cases",
        "jpi_enforcement_cases",
        "am_enforcement_detail",
    }
)
_SENSITIVE_IDENTIFIER_COLUMNS = frozenset(
    {
        "address_normalized",
        "case_id",
        "case_summary",
        "case_title",
        "company_name",
        "company_name_raw",
        "enforcement_id",
        "houjin_bangou",
        "id",
        "intermediate_recipient",
        "invoice_registration_number",
        "legal_basis",
        "normalized_name",
        "project_title",
        "reason_excerpt",
        "recipient_houjin_bangou",
        "recipient_name",
        "source_excerpt",
        "source_pdf_page",
        "source_section",
        "source_title",
        "source_url",
        "target_name",
        "trade_name",
    }
)


@dataclass(frozen=True)
class HfExport:
    table: str
    query: str


@dataclass(frozen=True)
class HfSafetyIssue:
    table: str
    code: str
    detail: str

    def format(self) -> str:
        return f"{self.table}: {self.code}: {self.detail}"


class HfExportSafetyError(RuntimeError):
    """Raised when an HF export plan cannot be proven safe."""

    def __init__(self, issues: Iterable[HfSafetyIssue]) -> None:
        self.issues = tuple(issues)
        detail = "\n".join(f"  - {issue.format()}" for issue in self.issues)
        super().__init__(f"HF export safety gate failed:\n{detail}")


def _clean_query(query: str) -> str:
    return query.strip().rstrip(";")


def _redistributable_license_sql() -> str:
    return ", ".join(f"'{license_name}'" for license_name in sorted(REDISTRIBUTABLE_LICENSES))


def _columns_for_query(conn: sqlite3.Connection, query: str) -> list[str]:
    cur = conn.execute(f"SELECT * FROM ({_clean_query(query)}) AS hf_export_gate LIMIT 0")
    return [str(col[0]) for col in cur.description or ()]


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('table', 'view') AND name = ?",
        (table,),
    ).fetchone()
    return row is not None


def _sample_license_values(conn: sqlite3.Connection, query: str, column: str) -> list[str]:
    rows = conn.execute(
        f"""
        SELECT COALESCE(CAST({column} AS TEXT), '<NULL>') AS license_value,
               COUNT(*) AS row_count
          FROM ({_clean_query(query)}) AS export_rows
         WHERE {column} IS NULL
            OR LOWER(TRIM(CAST({column} AS TEXT))) NOT IN ({_redistributable_license_sql()})
            OR TRIM(CAST({column} AS TEXT)) = ''
      GROUP BY license_value
      ORDER BY row_count DESC, license_value
         LIMIT 5
        """
    ).fetchall()
    return [f"{row[0]}={row[1]}" for row in rows]


def _license_issues(
    conn: sqlite3.Connection, export: HfExport, columns: set[str]
) -> list[HfSafetyIssue]:
    if "license" in columns:
        blocked = _sample_license_values(conn, export.query, "license")
        if blocked:
            return [
                HfSafetyIssue(
                    export.table,
                    "blocked_license",
                    "non-redistributable, blank, or missing license values: " + ", ".join(blocked),
                )
            ]
        return []

    if "source_url" in columns and _table_exists(conn, "am_source"):
        rows = conn.execute(
            f"""
            SELECT COALESCE(s.license, '<MISSING>') AS license_value,
                   COUNT(*) AS row_count
              FROM ({_clean_query(export.query)}) AS export_rows
             LEFT JOIN am_source s ON s.source_url = export_rows.source_url
             WHERE s.license IS NULL
                OR LOWER(TRIM(CAST(s.license AS TEXT))) NOT IN ({_redistributable_license_sql()})
                OR TRIM(CAST(s.license AS TEXT)) = ''
          GROUP BY license_value
          ORDER BY row_count DESC, license_value
             LIMIT 5
            """
        ).fetchall()
        if rows:
            samples = ", ".join(f"{row[0]}={row[1]}" for row in rows)
            return [
                HfSafetyIssue(
                    export.table,
                    "blocked_source_license",
                    "source_url rows resolve to non-redistributable or missing "
                    f"am_source license: {samples}",
                )
            ]
        return []

    return [
        HfSafetyIssue(
            export.table,
            "missing_license_metadata",
            "export rows must include a license column or source_url joinable to am_source",
        )
    ]


def _is_sensitive_export(export: HfExport) -> bool:
    table = export.table.lower()
    query = f" {re.sub(r'[^a-z0-9_]+', ' ', _clean_query(export.query).lower())} "
    return table in _SENSITIVE_TABLES or any(f" {name} " in query for name in _SENSITIVE_TABLES)


def _count_columns(columns: set[str]) -> list[str]:
    out: list[str] = []
    for column in sorted(columns):
        lower = column.lower()
        if lower in _AGGREGATE_COUNT_COLUMNS or lower.endswith("_count"):
            out.append(column)
    return out


def _aggregate_query_is_obvious(export: HfExport) -> bool:
    if export.table.lower().startswith("pc_"):
        return True
    query = f" {_clean_query(export.query).lower()} "
    return any(token in query for token in _AGGREGATE_QUERY_TOKENS)


def _sensitive_row_issues(
    conn: sqlite3.Connection,
    export: HfExport,
    columns: set[str],
) -> list[HfSafetyIssue]:
    if not _is_sensitive_export(export):
        return []

    identifier_columns = sorted(columns & _SENSITIVE_IDENTIFIER_COLUMNS)
    if identifier_columns:
        return [
            HfSafetyIssue(
                export.table,
                "row_level_deanonymization_risk",
                "sensitive invoice/adoption/enforcement export exposes identifiers: "
                + ", ".join(identifier_columns[:12]),
            )
        ]

    count_columns = _count_columns(columns)
    if not count_columns:
        return [
            HfSafetyIssue(
                export.table,
                "unsafe_aggregation",
                "sensitive export must expose an aggregate count column",
            )
        ]

    if not _aggregate_query_is_obvious(export):
        return [
            HfSafetyIssue(
                export.table,
                "unsafe_aggregation",
                "sensitive export must be a clear aggregate query or precomputed aggregate table",
            )
        ]

    count_expr = " OR ".join(
        f"COALESCE(CAST({column} AS INTEGER), 0) < {MIN_SAFE_AGGREGATE_ROWS}"
        for column in count_columns
    )
    low_count_rows = conn.execute(
        f"""
        SELECT COUNT(*)
          FROM ({_clean_query(export.query)}) AS export_rows
         WHERE {count_expr}
        """
    ).fetchone()[0]
    if int(low_count_rows or 0) > 0:
        return [
            HfSafetyIssue(
                export.table,
                "small_aggregate_cell",
                f"{low_count_rows} aggregate row(s) below k={MIN_SAFE_AGGREGATE_ROWS}",
            )
        ]

    return []


def collect_hf_export_safety_issues(
    conn: sqlite3.Connection,
    exports: Iterable[HfExport | tuple[str, str]],
) -> list[HfSafetyIssue]:
    issues: list[HfSafetyIssue] = []
    for item in exports:
        export = item if isinstance(item, HfExport) else HfExport(table=item[0], query=item[1])
        try:
            columns = {column.lower() for column in _columns_for_query(conn, export.query)}
        except sqlite3.Error as exc:
            issues.append(HfSafetyIssue(export.table, "invalid_export_query", str(exc)))
            continue
        issues.extend(_license_issues(conn, export, columns))
        issues.extend(_sensitive_row_issues(conn, export, columns))
    return issues


def assert_hf_export_safe(
    conn: sqlite3.Connection,
    exports: Iterable[HfExport | tuple[str, str]],
) -> None:
    issues = collect_hf_export_safety_issues(conn, exports)
    if issues:
        raise HfExportSafetyError(issues)
