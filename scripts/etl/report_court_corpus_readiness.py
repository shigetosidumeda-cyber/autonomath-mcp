#!/usr/bin/env python3
"""Read-only B5 courts corpus readiness/source-gap report.

This is an audit/preflight helper only. It opens local SQLite databases in
read-only/query-only mode, detects court_decisions/courts-like tables from
schema signals, and reports current official courts.go.jp coverage and
metadata gaps. It performs no crawling and never mutates source databases.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = REPO_ROOT / "autonomath.db"
DEFAULT_OUTPUT = REPO_ROOT / "analysis_wave18" / "court_corpus_readiness_2026-05-01.json"

B5_COURTS = "b5_courts"

COURT_TABLE_TOKENS = (
    "court",
    "courts",
    "hanrei",
    "saiban",
    "judgment",
    "judgement",
)
COURT_SCHEMA_TERMS = {
    "case_name",
    "case_number",
    "court",
    "court_name",
    "court_level",
    "decision_date",
    "decision_type",
    "judgment_date",
    "judgement_date",
    "hanrei_id",
    "docket_number",
}
EXCLUDED_TABLE_MARKERS = (
    "_fts",
    "_archive",
    "_embedding",
    "_vec",
)
EXCLUDED_TABLE_SUFFIXES = (
    "_config",
    "_data",
    "_docsize",
    "_idx",
)
SOURCE_URL_COLUMN_NAMES = {
    "source_url",
    "source_urls_json",
}
BODY_TEXT_COLUMN_NAMES = {
    "body_text",
    "decision_text",
    "full_text",
    "judgment_text",
    "judgement_text",
    "pdf_text",
    "raw_text",
    "text_body",
}
TAX_TERMS = (
    "租税",
    "税",
    "所得税",
    "法人税",
    "消費税",
    "相続税",
    "贈与税",
    "固定資産税",
    "国税",
    "地方税",
    "源泉",
    "青色申告",
    "課税",
    "更正",
    "滞納",
    "徴収",
    "加算税",
    "納税",
    "tax",
)
ADMIN_TERMS = (
    "行政",
    "行政事件",
    "行政訴訟",
    "処分",
    "取消",
    "不服",
    "審査請求",
    "国家賠償",
    "許可",
    "認可",
    "命令",
    "補助金",
    "会計検査",
    "情報公開",
    "生活保護",
    "公務員",
    "administrative",
)


@dataclass(frozen=True)
class ColumnInfo:
    name: str
    declared_type: str


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _connect_readonly(path: Path) -> sqlite3.Connection:
    if not path.exists():
        raise FileNotFoundError(path)
    conn = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = ON")
    return conn


def _quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _table_names(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        """
        SELECT name
          FROM sqlite_master
         WHERE type IN ('table', 'view')
         ORDER BY name
        """
    ).fetchall()
    return [str(row["name"]) for row in rows]


def _column_info(conn: sqlite3.Connection, table: str) -> list[ColumnInfo]:
    return [
        ColumnInfo(name=str(row["name"]), declared_type=str(row["type"] or ""))
        for row in conn.execute(f"PRAGMA table_info({_quote_ident(table)})")
    ]


def _is_excluded_table(table: str) -> bool:
    lower = table.lower()
    return (
        lower.startswith("sqlite_")
        or any(marker in lower for marker in EXCLUDED_TABLE_MARKERS)
        or any(lower.endswith(suffix) for suffix in EXCLUDED_TABLE_SUFFIXES)
    )


def _url_columns(columns: list[ColumnInfo]) -> list[str]:
    result: list[str] = []
    for col in columns:
        lower = col.name.lower()
        if "url" in lower or lower.endswith(("uri", "href", "link")):
            result.append(col.name)
    return result


def _source_url_columns(columns: list[ColumnInfo]) -> list[str]:
    return [col.name for col in columns if col.name.lower() in SOURCE_URL_COLUMN_NAMES]


def _source_excerpt_columns(columns: list[ColumnInfo]) -> list[str]:
    result: list[str] = []
    for col in columns:
        lower = col.name.lower()
        if lower in {"source_excerpt", "excerpt", "source_quote", "quote"} or "excerpt" in lower:
            result.append(col.name)
    return result


def _license_columns(columns: list[ColumnInfo]) -> list[str]:
    return [col.name for col in columns if "license" in col.name.lower()]


def _body_text_columns(columns: list[ColumnInfo]) -> list[str]:
    return [col.name for col in columns if col.name.lower() in BODY_TEXT_COLUMN_NAMES]


def _text_signal_columns(columns: list[ColumnInfo]) -> list[str]:
    result: list[str] = []
    for col in columns:
        declared = col.declared_type.upper()
        if any(token in declared for token in ("INT", "REAL", "NUM", "BLOB", "BOOL")):
            continue
        result.append(col.name)
    return result


def _is_court_like_table(table: str, columns: list[ColumnInfo]) -> bool:
    if _is_excluded_table(table):
        return False

    lower_table = table.lower()
    names = {col.name.lower() for col in columns}
    table_has_court_token = any(token in lower_table for token in COURT_TABLE_TOKENS)
    schema_hits = names & COURT_SCHEMA_TERMS
    has_url = bool(_url_columns(columns))
    has_case_signal = any("case" in name or "docket" in name for name in names)
    has_court_signal = any(
        name == "court" or "court_" in name or name.endswith("_court") for name in names
    )
    has_decision_signal = any(
        "decision" in name or "judgment" in name or "judgement" in name for name in names
    )

    if lower_table == "court_decisions":
        return True
    if table_has_court_token and (has_url or schema_hits or has_case_signal):
        return True
    if has_url and has_court_signal and (has_case_signal or has_decision_signal):
        return True
    return bool(has_url and len(schema_hits) >= 2)


def _pct(part: int, total: int) -> float:
    if total == 0:
        return 0.0
    return round((part / total) * 100, 2)


def _count_rows(
    conn: sqlite3.Connection,
    table: str,
    where_sql: str = "",
    params: tuple[str, ...] = (),
) -> int:
    row = conn.execute(
        f"SELECT COUNT(*) AS c FROM {_quote_ident(table)}{where_sql}",
        params,
    ).fetchone()
    return int(row["c"] or 0)


def _count_present(
    conn: sqlite3.Connection,
    table: str,
    columns: list[str],
    where_sql: str = "",
    params: tuple[str, ...] = (),
) -> int:
    if not columns:
        return 0
    present_expr = " OR ".join(
        (f"{_quote_ident(column)} IS NOT NULL AND TRIM(CAST({_quote_ident(column)} AS TEXT)) != ''")
        for column in columns
    )
    row = conn.execute(
        f"""
        SELECT COALESCE(SUM(CASE WHEN {present_expr} THEN 1 ELSE 0 END), 0) AS c
          FROM {_quote_ident(table)}{where_sql}
        """,
        params,
    ).fetchone()
    return int(row["c"] or 0)


def _metadata_family(
    conn: sqlite3.Connection,
    table: str,
    columns: list[str],
    row_count: int,
) -> dict[str, Any]:
    if not columns:
        return {
            "columns": [],
            "column_present": False,
            "present": None,
            "missing": None,
            "present_pct": None,
            "missing_pct": None,
        }

    present = _count_present(conn, table, columns)
    missing = row_count - present
    return {
        "columns": columns,
        "column_present": True,
        "present": present,
        "missing": missing,
        "present_pct": _pct(present, row_count),
        "missing_pct": _pct(missing, row_count),
    }


def _text_expr(columns: list[str]) -> str:
    if not columns:
        return "''"
    return " || ' ' || ".join(
        f"lower(COALESCE(CAST({_quote_ident(column)} AS TEXT), ''))" for column in columns
    )


def _terms_where(columns: list[str], terms: tuple[str, ...]) -> tuple[str, tuple[str, ...]]:
    if not columns or not terms:
        return "", ()
    expr = _text_expr(columns)
    return " OR ".join(f"{expr} LIKE ?" for _ in terms), tuple(
        f"%{term.lower()}%" for term in terms
    )


def _combined_where(
    *clauses: tuple[str, tuple[str, ...]],
    joiner: str = "AND",
) -> tuple[str, tuple[str, ...]]:
    sql_parts: list[str] = []
    params: list[str] = []
    for sql, sql_params in clauses:
        if not sql:
            continue
        sql_parts.append(f"({sql})")
        params.extend(sql_params)
    if not sql_parts:
        return "", ()
    return " WHERE " + f" {joiner} ".join(sql_parts), tuple(params)


def _official_courts_where(url_columns: list[str]) -> tuple[str, tuple[str, ...]]:
    if not url_columns:
        return "", ()
    parts = [
        f"lower(COALESCE(CAST({_quote_ident(column)} AS TEXT), '')) LIKE ?"
        for column in url_columns
    ]
    return " OR ".join(parts), tuple("%courts.go.jp%" for _ in parts)


def _count_matching_terms(
    conn: sqlite3.Connection,
    table: str,
    signal_columns: list[str],
    terms: tuple[str, ...],
) -> int:
    where, params = _terms_where(signal_columns, terms)
    where_sql, where_params = _combined_where((where, params))
    return _count_rows(conn, table, where_sql, where_params)


def _category_counts(
    conn: sqlite3.Connection,
    table: str,
    signal_columns: list[str],
) -> dict[str, Any]:
    tax_where, tax_params = _terms_where(signal_columns, TAX_TERMS)
    admin_where, admin_params = _terms_where(signal_columns, ADMIN_TERMS)
    union_where, union_params = _combined_where(
        (tax_where, tax_params),
        (admin_where, admin_params),
        joiner="OR",
    )
    both_where, both_params = _combined_where(
        (tax_where, tax_params),
        (admin_where, admin_params),
    )
    return {
        "likely_tax_rows": _count_matching_terms(conn, table, signal_columns, TAX_TERMS),
        "likely_administrative_rows": _count_matching_terms(
            conn,
            table,
            signal_columns,
            ADMIN_TERMS,
        ),
        "likely_tax_or_administrative_rows": _count_rows(
            conn,
            table,
            union_where,
            union_params,
        ),
        "likely_tax_and_administrative_rows": _count_rows(
            conn,
            table,
            both_where,
            both_params,
        ),
        "signal_columns": signal_columns,
        "terms_version": "2026-05-01-local-keywords",
    }


def _duplicate_urls_within_table(
    conn: sqlite3.Connection,
    table: str,
    url_columns: list[str],
    *,
    limit: int,
) -> tuple[int, list[dict[str, Any]]]:
    groups: list[dict[str, Any]] = []
    total_group_count = 0
    for column in url_columns:
        quoted = _quote_ident(column)
        count = int(
            conn.execute(
                f"""
                SELECT COUNT(*) AS c
                  FROM (
                    SELECT TRIM(CAST({quoted} AS TEXT)) AS url
                      FROM {_quote_ident(table)}
                     WHERE {quoted} IS NOT NULL
                       AND TRIM(CAST({quoted} AS TEXT)) != ''
                  GROUP BY url
                    HAVING COUNT(*) > 1
                  )
                """
            ).fetchone()["c"]
            or 0
        )
        total_group_count += count
        rows = conn.execute(
            f"""
            SELECT TRIM(CAST({quoted} AS TEXT)) AS url, COUNT(*) AS rows
              FROM {_quote_ident(table)}
             WHERE {quoted} IS NOT NULL
               AND TRIM(CAST({quoted} AS TEXT)) != ''
          GROUP BY url
            HAVING COUNT(*) > 1
          ORDER BY rows DESC, url
             LIMIT ?
            """,
            (limit,),
        ).fetchall()
        groups.extend(
            {
                "table": table,
                "column": column,
                "url": str(row["url"]),
                "rows": int(row["rows"]),
            }
            for row in rows
        )
    groups.sort(key=lambda row: (-int(row["rows"]), str(row["url"])))
    return total_group_count, groups[:limit]


def _domain_from_url(url: str) -> str:
    text = url.strip()
    if not text:
        return ""
    parsed = urlparse(text)
    if not parsed.netloc and text.startswith("www."):
        parsed = urlparse(f"https://{text}")
    return parsed.netloc.lower()


def _path_prefix_from_url(url: str) -> str:
    text = url.strip()
    if not text:
        return ""
    parsed = urlparse(text)
    if not parsed.netloc and text.startswith("www."):
        parsed = urlparse(f"https://{text}")
    parts = [part for part in (parsed.path or "/").split("/") if part]
    if not parts:
        return "/"
    if "." in parts[-1]:
        parts = parts[:-1]
    return "/" + "/".join(parts[:3]) + "/"


def _source_groups(
    conn: sqlite3.Connection,
    table: str,
    url_columns: list[str],
    *,
    limit: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not url_columns:
        return [], []

    select_cols = ", ".join(_quote_ident(column) for column in url_columns)
    rows = conn.execute(f"SELECT {select_cols} FROM {_quote_ident(table)}")
    domain_counts: Counter[str] = Counter()
    path_counts: Counter[tuple[str, str]] = Counter()
    for row in rows:
        first_url = ""
        for column in url_columns:
            value = row[column]
            if value is not None and str(value).strip():
                first_url = str(value)
                break
        domain = _domain_from_url(first_url)
        if not domain:
            continue
        domain_counts[domain] += 1
        path_counts[(domain, _path_prefix_from_url(first_url))] += 1

    domains = [
        {"domain": domain, "rows": rows} for domain, rows in domain_counts.most_common(limit)
    ]
    paths = [
        {"domain": domain, "path_prefix": path, "rows": rows}
        for (domain, path), rows in path_counts.most_common(limit)
    ]
    return domains, paths


def _dimension_counts(
    conn: sqlite3.Connection,
    table: str,
    columns: list[ColumnInfo],
    candidates: tuple[str, ...],
    *,
    limit: int,
) -> dict[str, Any] | None:
    names = {col.name.lower(): col.name for col in columns}
    column = next((names[candidate] for candidate in candidates if candidate in names), None)
    if column is None:
        return None
    rows = conn.execute(
        f"""
        SELECT COALESCE(NULLIF(TRIM(CAST({_quote_ident(column)} AS TEXT)), ''), '(missing)') AS bucket,
               COUNT(*) AS rows
          FROM {_quote_ident(table)}
      GROUP BY bucket
      ORDER BY rows DESC, bucket
         LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return {
        "column": column,
        "buckets": [{"value": str(row["bucket"]), "rows": int(row["rows"])} for row in rows],
    }


def _scan_candidate_table(
    conn: sqlite3.Connection,
    *,
    database: Path,
    table: str,
    columns: list[ColumnInfo],
    sample_limit: int,
) -> dict[str, Any]:
    column_names = [col.name for col in columns]
    row_count = _count_rows(conn, table)
    url_columns = _url_columns(columns)
    official_where, official_params = _official_courts_where(url_columns)
    official_sql, official_sql_params = _combined_where((official_where, official_params))
    official_rows = _count_rows(conn, table, official_sql, official_sql_params)
    duplicate_count, duplicate_groups = _duplicate_urls_within_table(
        conn,
        table,
        url_columns,
        limit=sample_limit,
    )
    source_domains, source_paths = _source_groups(
        conn,
        table,
        url_columns,
        limit=sample_limit,
    )

    return {
        "database": str(database),
        "table": table,
        "columns": column_names,
        "row_count": row_count,
        "official_courts_go_jp_rows": official_rows,
        "non_official_or_missing_official_url_rows": row_count - official_rows,
        "metadata": {
            "source_url": _metadata_family(conn, table, _source_url_columns(columns), row_count),
            "source_excerpt": _metadata_family(
                conn,
                table,
                _source_excerpt_columns(columns),
                row_count,
            ),
            "license": _metadata_family(conn, table, _license_columns(columns), row_count),
            "body_text": _metadata_family(conn, table, _body_text_columns(columns), row_count),
        },
        "duplicates": {
            "duplicate_url_group_count": duplicate_count,
            "duplicate_url_groups": duplicate_groups,
        },
        "category_counts": _category_counts(conn, table, _text_signal_columns(columns)),
        "dimensions": {
            "subject_area": _dimension_counts(
                conn,
                table,
                columns,
                ("subject_area", "category", "case_category"),
                limit=sample_limit,
            ),
            "court_level": _dimension_counts(
                conn,
                table,
                columns,
                ("court_level", "court", "court_name"),
                limit=sample_limit,
            ),
        },
        "source_domains": source_domains,
        "source_path_prefixes": source_paths,
    }


def _scan_database(path: Path, *, sample_limit: int) -> dict[str, Any]:
    result: dict[str, Any] = {
        "path": str(path),
        "exists": path.exists(),
        "size_bytes": path.stat().st_size if path.exists() else 0,
        "tables": [],
    }
    if not path.exists():
        result["error"] = "database file not found"
        return result

    with _connect_readonly(path) as conn:
        for table in _table_names(conn):
            if _is_excluded_table(table):
                continue
            try:
                columns = _column_info(conn, table)
            except sqlite3.Error as exc:
                if any(token in table.lower() for token in COURT_TABLE_TOKENS):
                    result["tables"].append(
                        {
                            "database": str(path),
                            "table": table,
                            "columns": [],
                            "error": f"schema introspection failed: {exc}",
                        }
                    )
                continue
            if not _is_court_like_table(table, columns):
                continue
            try:
                result["tables"].append(
                    _scan_candidate_table(
                        conn,
                        database=path,
                        table=table,
                        columns=columns,
                        sample_limit=sample_limit,
                    )
                )
            except sqlite3.Error as exc:
                result["tables"].append(
                    {
                        "database": str(path),
                        "table": table,
                        "columns": [col.name for col in columns],
                        "error": str(exc),
                    }
                )
    return result


def _sum_available_metadata(tables: list[dict[str, Any]], family: str, key: str) -> int:
    total = 0
    for table in tables:
        metadata = table.get("metadata", {}).get(family, {})
        value = metadata.get(key)
        if value is not None:
            total += int(value)
    return total


def _missing_column_tables(tables: list[dict[str, Any]], family: str) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for table in tables:
        metadata = table.get("metadata", {}).get(family, {})
        if metadata and not metadata.get("column_present", False):
            result.append({"database": str(table["database"]), "table": str(table["table"])})
    return result


def _aggregate_source_domains(tables: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    counts: Counter[str] = Counter()
    for table in tables:
        for row in table.get("source_domains", []):
            counts[str(row["domain"])] += int(row["rows"])
    return [{"domain": domain, "rows": rows} for domain, rows in counts.most_common(limit)]


def _aggregate_source_paths(tables: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    counts: Counter[tuple[str, str]] = Counter()
    for table in tables:
        for row in table.get("source_path_prefixes", []):
            counts[(str(row["domain"]), str(row["path_prefix"]))] += int(row["rows"])
    return [
        {"domain": domain, "path_prefix": path, "rows": rows}
        for (domain, path), rows in counts.most_common(limit)
    ]


def _summarize_tables(tables: list[dict[str, Any]], *, sample_limit: int) -> dict[str, Any]:
    usable_tables = [table for table in tables if "error" not in table]
    if not usable_tables:
        return {
            "kind": B5_COURTS,
            "candidate_table_count": 0,
            "physical_row_count": 0,
            "official_courts_go_jp_rows": 0,
            "non_official_or_missing_official_url_rows": 0,
            "source_table_with_max_rows": None,
            "metadata_gaps_available": {
                "source_url_missing": 0,
                "source_excerpt_missing": 0,
                "license_missing": 0,
                "body_text_missing": 0,
            },
            "metadata_missing_column_tables": {
                "source_url": [],
                "source_excerpt": [],
                "license": [],
                "body_text": [],
            },
            "duplicate_url_group_count": 0,
            "likely_tax_rows": 0,
            "likely_administrative_rows": 0,
            "likely_tax_or_administrative_rows": 0,
            "source_domains": [],
            "source_path_prefixes": [],
        }

    source_table = max(usable_tables, key=lambda table: int(table["row_count"]))
    return {
        "kind": B5_COURTS,
        "candidate_table_count": len(usable_tables),
        "physical_row_count": sum(int(table["row_count"]) for table in usable_tables),
        "official_courts_go_jp_rows": sum(
            int(table["official_courts_go_jp_rows"]) for table in usable_tables
        ),
        "non_official_or_missing_official_url_rows": sum(
            int(table["non_official_or_missing_official_url_rows"]) for table in usable_tables
        ),
        "source_table_with_max_rows": {
            "database": str(source_table["database"]),
            "table": str(source_table["table"]),
            "rows": int(source_table["row_count"]),
        },
        "metadata_gaps_available": {
            "source_url_missing": _sum_available_metadata(usable_tables, "source_url", "missing"),
            "source_excerpt_missing": _sum_available_metadata(
                usable_tables,
                "source_excerpt",
                "missing",
            ),
            "license_missing": _sum_available_metadata(usable_tables, "license", "missing"),
            "body_text_missing": _sum_available_metadata(usable_tables, "body_text", "missing"),
        },
        "metadata_missing_column_tables": {
            "source_url": _missing_column_tables(usable_tables, "source_url"),
            "source_excerpt": _missing_column_tables(usable_tables, "source_excerpt"),
            "license": _missing_column_tables(usable_tables, "license"),
            "body_text": _missing_column_tables(usable_tables, "body_text"),
        },
        "duplicate_url_group_count": sum(
            int(table["duplicates"]["duplicate_url_group_count"]) for table in usable_tables
        ),
        "likely_tax_rows": sum(
            int(table["category_counts"]["likely_tax_rows"]) for table in usable_tables
        ),
        "likely_administrative_rows": sum(
            int(table["category_counts"]["likely_administrative_rows"]) for table in usable_tables
        ),
        "likely_tax_or_administrative_rows": sum(
            int(table["category_counts"]["likely_tax_or_administrative_rows"])
            for table in usable_tables
        ),
        "source_domains": _aggregate_source_domains(usable_tables, limit=sample_limit),
        "source_path_prefixes": _aggregate_source_paths(usable_tables, limit=sample_limit),
    }


def _official_backfill_plan(summary: dict[str, Any]) -> list[dict[str, Any]]:
    gaps = summary["metadata_gaps_available"]
    missing_columns = summary["metadata_missing_column_tables"]
    return [
        {
            "step": "normalize_official_source_urls",
            "source_domain": "www.courts.go.jp",
            "source_paths": ["/app/hanrei_jp/", "/hanrei/", "/assets/hanrei/"],
            "current_official_rows": summary["official_courts_go_jp_rows"],
            "current_non_official_or_missing_official_url_rows": summary[
                "non_official_or_missing_official_url_rows"
            ],
            "current_missing_source_url_rows_if_column_exists": gaps["source_url_missing"],
            "tables_missing_source_url_column": missing_columns["source_url"],
            "action": (
                "Backfill each court row to an official courts.go.jp detail URL in source_url "
                "when a local full_text_url/pdf_url/case identifier already proves the source; "
                "queue rows without an official URL for a later courts.go.jp-only ingest."
            ),
            "network_fetch_performed": False,
        },
        {
            "step": "backfill_source_excerpt_from_detail_pages",
            "source_domain": "www.courts.go.jp",
            "source_paths": ["/app/hanrei_jp/detail*/", "/hanrei/*/detail*/index.html"],
            "current_missing_source_excerpt_rows_if_column_exists": gaps["source_excerpt_missing"],
            "tables_missing_source_excerpt_column": missing_columns["source_excerpt"],
            "action": (
                "Populate source_excerpt from official detail-page labels such as 判示事項, "
                "裁判要旨, and 参照法条; preserve short quoted snippets for citation evidence."
            ),
            "network_fetch_performed": False,
        },
        {
            "step": "attach_license_metadata",
            "source_domain": "www.courts.go.jp",
            "current_missing_license_rows_if_column_exists": gaps["license_missing"],
            "tables_missing_license_column": missing_columns["license"],
            "action": (
                "Store courts.go.jp reuse/license metadata at row level or via am_source, "
                "including terms reference, last_verified, and content hash fields where present."
            ),
            "network_fetch_performed": False,
        },
        {
            "step": "backfill_body_text_from_official_text_or_pdf",
            "source_domain": "www.courts.go.jp",
            "source_paths": [
                "/assets/hanrei/hanrei-pdf-*.pdf",
                "/app/hanrei_jp/detail*/",
                "/hanrei/*/detail*/index.html",
            ],
            "current_missing_body_text_rows_if_column_exists": gaps["body_text_missing"],
            "tables_missing_body_text_column": missing_columns["body_text"],
            "action": (
                "If no body_text/full_text storage exists, add it before extraction; otherwise "
                "backfill missing body text from official courts.go.jp text/PDF assets only."
            ),
            "network_fetch_performed": False,
        },
        {
            "step": "deduplicate_official_urls",
            "current_duplicate_url_group_count": summary["duplicate_url_group_count"],
            "action": (
                "Collapse duplicate official URLs to one canonical court decision row, then "
                "preserve alternate local identifiers as aliases rather than duplicate records."
            ),
            "network_fetch_performed": False,
        },
        {
            "step": "expand_tax_and_administrative_coverage",
            "source_domain": "www.courts.go.jp",
            "current_likely_tax_rows": summary["likely_tax_rows"],
            "current_likely_administrative_rows": summary["likely_administrative_rows"],
            "current_likely_tax_or_administrative_rows": summary[
                "likely_tax_or_administrative_rows"
            ],
            "action": (
                "After provenance/body gaps are handled, seed official courts.go.jp searches "
                "for 租税/所得税/法人税/消費税 and 行政/処分取消/審査請求 terms, then ingest "
                "only official detail/PDF URLs."
            ),
            "network_fetch_performed": False,
        },
    ]


def _findings(summary: dict[str, Any]) -> list[str]:
    findings: list[str] = []
    gaps = summary["metadata_gaps_available"]
    missing_columns = summary["metadata_missing_column_tables"]
    if summary["candidate_table_count"] == 0:
        findings.append("B5: no court_decisions/courts-like tables detected in local SQLite")
    if summary["official_courts_go_jp_rows"] == 0 and summary["physical_row_count"] > 0:
        findings.append(
            "B5: court-like rows exist, but no courts.go.jp official URLs were detected"
        )
    if gaps["source_url_missing"]:
        findings.append("B5: source_url gaps remain in court-like tables")
    if gaps["source_excerpt_missing"] or missing_columns["source_excerpt"]:
        findings.append("B5: source_excerpt coverage is incomplete or lacks a storage column")
    if gaps["license_missing"] or missing_columns["license"]:
        findings.append("B5: license metadata is incomplete or lacks a storage column")
    if gaps["body_text_missing"] or missing_columns["body_text"]:
        findings.append("B5: body_text/full_text coverage is incomplete or lacks a storage column")
    if summary["duplicate_url_group_count"]:
        findings.append("B5: duplicate URL groups need canonicalization")
    if summary["likely_tax_rows"] == 0:
        findings.append("B5: no likely tax court rows detected from local text/schema")
    if summary["likely_administrative_rows"] == 0:
        findings.append("B5: no likely administrative court rows detected from local text/schema")
    return findings


def build_report(
    db_paths: list[Path],
    *,
    sample_limit: int = 20,
) -> dict[str, Any]:
    databases = [_scan_database(path, sample_limit=sample_limit) for path in db_paths]
    table_reports = [
        table
        for database in databases
        for table in database.get("tables", [])
        if int(table.get("row_count", 0)) >= 0
    ]
    summary = _summarize_tables(table_reports, sample_limit=sample_limit)
    return {
        "ok": True,
        "complete": False,
        "generated_at": _utc_now(),
        "scope": "B5 courts corpus readiness/source-gap report; local SQLite only; no crawling",
        "read_mode": {
            "sqlite_only": True,
            "network_fetch_performed": False,
            "db_mutation_performed": False,
        },
        "databases": databases,
        "coverage": {
            B5_COURTS: summary,
        },
        "official_source_ingestion_backfill_plan": _official_backfill_plan(summary),
        "findings": _findings(summary),
        "completion_status": {
            "B5": "readiness_only",
            "complete": False,
        },
    }


def write_report(report: dict[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db",
        action="append",
        type=Path,
        dest="dbs",
        help="SQLite database to inspect. Repeat for multiple DBs. Defaults to autonomath.db.",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--sample-limit", type=int, default=20)
    parser.add_argument("--json", action="store_true", help="print full JSON report")
    parser.add_argument("--no-write", action="store_true", help="do not write --output")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    db_paths = args.dbs if args.dbs else [DEFAULT_DB]
    report = build_report(db_paths, sample_limit=args.sample_limit)
    if not args.no_write:
        write_report(report, args.output)

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        coverage = report["coverage"][B5_COURTS]
        print(f"b5_candidate_table_count={coverage['candidate_table_count']}")
        print(f"b5_physical_row_count={coverage['physical_row_count']}")
        print(f"b5_official_courts_go_jp_rows={coverage['official_courts_go_jp_rows']}")
        print(f"b5_likely_tax_rows={coverage['likely_tax_rows']}")
        print(f"b5_likely_administrative_rows={coverage['likely_administrative_rows']}")
        print(f"b5_duplicate_url_group_count={coverage['duplicate_url_group_count']}")
        print("complete=False")
        if not args.no_write:
            print(f"output={args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
