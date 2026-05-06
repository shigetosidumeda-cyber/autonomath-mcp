#!/usr/bin/env python3
"""Read-only B11/B12 official-source preflight report.

B11/B12 are not ingests here. This helper opens local SQLite databases in
read-only/query-only mode, introspects available schemas, and reports current
coverage/gaps for GEPS/procurement rows and JFC/credit-guarantee finance rows.
It performs no crawling and does not mutate source databases.
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
DEFAULT_OUTPUT = REPO_ROOT / "analysis_wave18" / "official_finance_procurement_gaps_2026-05-01.json"

PROCUREMENT = "b11_procurement"
FINANCE_LOANS = "b12_finance_loans"

GEPS_TERMS = (
    "p-portal.go.jp",
    "geps",
    "政府電子調達",
    "調達ポータル",
)
LOAN_BASE_TERMS = (
    "loan",
    "融資",
    "貸付",
    "信用保証",
    "保証協会",
    "日本政策金融公庫",
    "日本公庫",
    "jfc.go.jp",
    "credit_guarantee",
    "chusho.meti.go.jp/kinyu",
    "zenshinhoren.or.jp",
)
JFC_TERMS = (
    "jfc.go.jp",
    "日本政策金融公庫",
    "日本公庫",
    "jfc",
)
CREDIT_GUARANTEE_TERMS = (
    "信用保証",
    "保証協会",
    "shinyo-hosho",
    "credit_guarantee",
    "chusho.meti.go.jp/kinyu",
    "zenshinhoren.or.jp",
    ".cgc-",
    "セーフティネット保証",
    "責任共有",
)
SOURCE_MANIFEST_TERMS = (
    "p-portal.go.jp",
    "geps",
    "maff.go.jp/j/supply",
    "jfc.go.jp",
    "chusho.meti.go.jp/kinyu",
    "zenshinhoren.or.jp",
    "信用保証",
)

FRESHNESS_EXACT_COLUMNS = {
    "fetched_at",
    "source_fetched_at",
    "retrieved_at",
    "downloaded_at",
    "refreshed_at",
    "last_verified",
    "verified_at",
    "ingested_at",
    "source_url_last_checked",
}
PROVENANCE_EXACT_COLUMNS = {
    "source_id",
    "source_key",
    "source",
    "source_url",
    "official_url",
    "official_source",
    "source_url_domain",
}
EXCLUDED_TABLE_MARKERS = (
    "_aggregator_purge",
    "_fts",
    "_purge",
    "_vec",
    "sqlite_",
)
EXCLUDED_TABLE_PREFIXES = (
    "pc_",
    "jpi_pc_",
    "mat_",
)


@dataclass(frozen=True)
class ColumnInfo:
    name: str
    declared_type: str


@dataclass(frozen=True)
class TablePlan:
    kind: str
    base_terms: tuple[str, ...] = ()


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


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('table', 'view') AND name = ?",
        (table,),
    ).fetchone()
    return row is not None


def _column_info(conn: sqlite3.Connection, table: str) -> list[ColumnInfo]:
    return [
        ColumnInfo(name=str(row["name"]), declared_type=str(row["type"] or ""))
        for row in conn.execute(f"PRAGMA table_info({_quote_ident(table)})")
    ]


def _is_excluded_table(table: str) -> bool:
    lower = table.lower()
    return any(marker in lower for marker in EXCLUDED_TABLE_MARKERS) or any(
        lower.startswith(prefix) for prefix in EXCLUDED_TABLE_PREFIXES
    )


def _url_columns(columns: list[ColumnInfo]) -> list[str]:
    return [
        col.name
        for col in columns
        if "url" in col.name.lower() or col.name.lower().endswith(("uri", "href"))
    ]


def _license_columns(columns: list[ColumnInfo]) -> list[str]:
    return [col.name for col in columns if "license" in col.name.lower()]


def _freshness_columns(columns: list[ColumnInfo]) -> list[str]:
    result: list[str] = []
    for col in columns:
        lower = col.name.lower()
        if lower in FRESHNESS_EXACT_COLUMNS:
            result.append(col.name)
            continue
        if any(token in lower for token in ("fetch", "retriev", "download", "refresh")):
            result.append(col.name)
    return result


def _provenance_columns(columns: list[ColumnInfo]) -> list[str]:
    result = set(_url_columns(columns))
    for col in columns:
        lower = col.name.lower()
        if lower in PROVENANCE_EXACT_COLUMNS or lower.startswith("source_"):
            result.add(col.name)
    return sorted(result)


def _text_signal_columns(columns: list[ColumnInfo]) -> list[str]:
    result: list[str] = []
    for col in columns:
        declared = col.declared_type.upper()
        if any(token in declared for token in ("INT", "REAL", "NUM", "BLOB")):
            continue
        result.append(col.name)
    return result


def _table_plan(table: str, columns: list[ColumnInfo]) -> TablePlan | None:
    if _is_excluded_table(table):
        return None

    lower_table = table.lower()
    names = {col.name.lower() for col in columns}
    has_url = bool(_url_columns(columns))

    procurement_signature = (
        any(token in lower_table for token in ("bid", "procurement", "geps", "tender"))
        or "bid_title" in names
        or "procuring_entity" in names
    )
    if procurement_signature and (has_url or names & {"bid_title", "procuring_entity"}):
        return TablePlan(PROCUREMENT)

    loan_table_signature = (
        "loan" in lower_table
        or "loan_program_kind" in names
        or "lender_entity_id" in names
        or ("program_name" in names and "provider" in names)
    )
    if loan_table_signature and (
        has_url or names & {"provider", "lender_entity_id", "program_name", "primary_name"}
    ):
        return TablePlan(FINANCE_LOANS)

    program_signature = lower_table in {"programs", "jpi_programs"} or (
        "program_kind" in names and "primary_name" in names and has_url
    )
    if program_signature:
        return TablePlan(FINANCE_LOANS, LOAN_BASE_TERMS)

    return None


def _text_expr(columns: list[str]) -> str:
    if not columns:
        return "''"
    return " || ' ' || ".join(
        f"lower(COALESCE(CAST({_quote_ident(column)} AS TEXT), ''))" for column in columns
    )


def _terms_where(columns: list[str], terms: tuple[str, ...]) -> tuple[str, tuple[str, ...]]:
    if not terms or not columns:
        return "", ()
    expr = _text_expr(columns)
    where = " OR ".join(f"{expr} LIKE ?" for _ in terms)
    return f"({where})", tuple(f"%{term.lower()}%" for term in terms)


def _combined_where(
    base_where: str,
    base_params: tuple[str, ...],
    extra_where: str = "",
    extra_params: tuple[str, ...] = (),
) -> tuple[str, tuple[str, ...]]:
    parts = [part for part in (base_where, extra_where) if part]
    if not parts:
        return "", ()
    return " WHERE " + " AND ".join(f"({part})" for part in parts), base_params + extra_params


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
    where_sql: str,
    params: tuple[str, ...],
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


def _count_matching_terms(
    conn: sqlite3.Connection,
    table: str,
    signal_columns: list[str],
    terms: tuple[str, ...],
    base_where: str,
    base_params: tuple[str, ...],
) -> int:
    extra_where, extra_params = _terms_where(signal_columns, terms)
    where_sql, params = _combined_where(base_where, base_params, extra_where, extra_params)
    return _count_rows(conn, table, where_sql, params)


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
    path = parsed.path or "/"
    parts = [part for part in path.split("/") if part]
    if not parts:
        return "/"
    if "." in parts[-1]:
        parts = parts[:-1]
    prefix_parts = parts[:3]
    return "/" + "/".join(prefix_parts) + "/"


def _source_group_counts(
    conn: sqlite3.Connection,
    table: str,
    url_columns: list[str],
    where_sql: str,
    params: tuple[str, ...],
    *,
    limit: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not url_columns:
        return [], []

    select_cols = ", ".join(_quote_ident(column) for column in url_columns)
    rows = conn.execute(f"SELECT {select_cols} FROM {_quote_ident(table)}{where_sql}", params)
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


def _scan_candidate_table(
    conn: sqlite3.Connection,
    *,
    database: Path,
    table: str,
    plan: TablePlan,
    columns: list[ColumnInfo],
    sample_limit: int,
) -> dict[str, Any]:
    column_names = [col.name for col in columns]
    signal_columns = _text_signal_columns(columns)
    url_columns = _url_columns(columns)
    provenance_columns = _provenance_columns(columns)
    license_columns = _license_columns(columns)
    freshness_columns = _freshness_columns(columns)
    base_where, base_params = _terms_where(signal_columns, plan.base_terms)
    where_sql, where_params = _combined_where(base_where, base_params)
    row_count = _count_rows(conn, table, where_sql, where_params)

    provenance_present = _count_present(
        conn,
        table,
        provenance_columns,
        where_sql,
        where_params,
    )
    license_present = _count_present(conn, table, license_columns, where_sql, where_params)
    freshness_present = _count_present(conn, table, freshness_columns, where_sql, where_params)
    source_domains, source_path_prefixes = _source_group_counts(
        conn,
        table,
        url_columns,
        where_sql,
        where_params,
        limit=sample_limit,
    )

    counts: dict[str, int] = {}
    if plan.kind == PROCUREMENT:
        counts = {
            "procurement_like_rows": row_count,
            "geps_like_rows": _count_matching_terms(
                conn,
                table,
                signal_columns,
                GEPS_TERMS,
                base_where,
                base_params,
            ),
        }
    elif plan.kind == FINANCE_LOANS:
        counts = {
            "loan_like_rows": row_count,
            "jfc_like_rows": _count_matching_terms(
                conn,
                table,
                signal_columns,
                JFC_TERMS,
                base_where,
                base_params,
            ),
            "credit_guarantee_like_rows": _count_matching_terms(
                conn,
                table,
                signal_columns,
                CREDIT_GUARANTEE_TERMS,
                base_where,
                base_params,
            ),
        }

    return {
        "database": str(database),
        "table": table,
        "kind": plan.kind,
        "base_filter": "all_rows" if not plan.base_terms else "loan_official_source_terms",
        "columns": column_names,
        "row_count": row_count,
        "counts": counts,
        "metadata": {
            "provenance_columns": provenance_columns,
            "provenance_present": provenance_present,
            "provenance_missing": row_count - provenance_present,
            "license_columns": license_columns,
            "license_present": license_present,
            "license_missing": row_count - license_present,
            "freshness_columns": freshness_columns,
            "freshness_present": freshness_present,
            "freshness_missing": row_count - freshness_present,
        },
        "source_domains": source_domains,
        "source_path_prefixes": source_path_prefixes,
    }


def _collect_source_manifest(
    conn: sqlite3.Connection,
    *,
    database: Path,
    sample_limit: int,
) -> dict[str, Any] | None:
    if not _table_exists(conn, "am_source"):
        return None

    columns = _column_info(conn, "am_source")
    names = {col.name for col in columns}
    if "source_url" not in names:
        return None

    signal_columns = _text_signal_columns(columns)
    where, params = _terms_where(signal_columns, SOURCE_MANIFEST_TERMS)
    where_sql, where_params = _combined_where(where, params)
    row_count = _count_rows(conn, "am_source", where_sql, where_params)
    license_columns = _license_columns(columns)
    freshness_columns = [
        column for column in _freshness_columns(columns) if column == "last_verified"
    ]
    hash_columns = [column for column in ("content_hash", "source_checksum") if column in names]
    source_domains, source_path_prefixes = _source_group_counts(
        conn,
        "am_source",
        ["source_url"],
        where_sql,
        where_params,
        limit=sample_limit,
    )
    license_present = _count_present(conn, "am_source", license_columns, where_sql, where_params)
    freshness_present = _count_present(
        conn, "am_source", freshness_columns, where_sql, where_params
    )
    hash_present = _count_present(conn, "am_source", hash_columns, where_sql, where_params)
    return {
        "database": str(database),
        "table": "am_source",
        "row_count": row_count,
        "metadata": {
            "license_columns": license_columns,
            "license_present": license_present,
            "license_missing": row_count - license_present,
            "freshness_columns": freshness_columns,
            "freshness_present": freshness_present,
            "freshness_missing": row_count - freshness_present,
            "content_hash_columns": hash_columns,
            "content_hash_present": hash_present,
            "content_hash_missing": row_count - hash_present,
        },
        "source_domains": source_domains,
        "source_path_prefixes": source_path_prefixes,
    }


def _scan_database(path: Path, *, sample_limit: int) -> dict[str, Any]:
    result: dict[str, Any] = {
        "path": str(path),
        "exists": path.exists(),
        "size_bytes": path.stat().st_size if path.exists() else 0,
        "tables": [],
        "source_manifest": None,
    }
    if not path.exists():
        result["error"] = "database file not found"
        return result

    with _connect_readonly(path) as conn:
        for table in _table_names(conn):
            if _is_excluded_table(table):
                continue
            columns = _column_info(conn, table)
            plan = _table_plan(table, columns)
            if plan is None:
                continue
            result["tables"].append(
                _scan_candidate_table(
                    conn,
                    database=path,
                    table=table,
                    plan=plan,
                    columns=columns,
                    sample_limit=sample_limit,
                )
            )
        result["source_manifest"] = _collect_source_manifest(
            conn,
            database=path,
            sample_limit=sample_limit,
        )
    return result


def _aggregate_counts(
    reports: list[dict[str, Any]],
    key: str,
) -> int:
    if not reports:
        return 0
    return max(int(report["counts"].get(key, 0)) for report in reports)


def _aggregate_source_domains(reports: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    counts: Counter[str] = Counter()
    for report in reports:
        for row in report["source_domains"]:
            counts[str(row["domain"])] += int(row["rows"])
    return [{"domain": domain, "rows": rows} for domain, rows in counts.most_common(limit)]


def _aggregate_source_paths(reports: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    counts: Counter[tuple[str, str]] = Counter()
    for report in reports:
        for row in report["source_path_prefixes"]:
            counts[(str(row["domain"]), str(row["path_prefix"]))] += int(row["rows"])
    return [
        {"domain": domain, "path_prefix": path_prefix, "rows": rows}
        for (domain, path_prefix), rows in counts.most_common(limit)
    ]


def _metadata_gap_totals(reports: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "provenance_missing": sum(
            int(report["metadata"]["provenance_missing"]) for report in reports
        ),
        "license_missing": sum(int(report["metadata"]["license_missing"]) for report in reports),
        "freshness_missing": sum(
            int(report["metadata"]["freshness_missing"]) for report in reports
        ),
    }


def _summarize_kind(
    *,
    kind: str,
    reports: list[dict[str, Any]],
    source_limit: int,
) -> dict[str, Any]:
    if not reports:
        return {
            "kind": kind,
            "candidate_table_count": 0,
            "physical_row_count": 0,
            "max_single_table_rows": 0,
            "source_table_with_max_rows": None,
            "counts": {},
            "metadata_gaps_physical": {
                "provenance_missing": 0,
                "license_missing": 0,
                "freshness_missing": 0,
            },
            "source_domains": [],
            "source_path_prefixes": [],
        }

    source_table = max(reports, key=lambda report: int(report["row_count"]))
    counts: dict[str, int]
    if kind == PROCUREMENT:
        counts = {
            "procurement_like_rows": _aggregate_counts(reports, "procurement_like_rows"),
            "geps_like_rows": _aggregate_counts(reports, "geps_like_rows"),
        }
    else:
        counts = {
            "loan_like_rows": _aggregate_counts(reports, "loan_like_rows"),
            "jfc_like_rows": _aggregate_counts(reports, "jfc_like_rows"),
            "credit_guarantee_like_rows": _aggregate_counts(
                reports,
                "credit_guarantee_like_rows",
            ),
        }

    return {
        "kind": kind,
        "candidate_table_count": len(reports),
        "physical_row_count": sum(int(report["row_count"]) for report in reports),
        "max_single_table_rows": int(source_table["row_count"]),
        "source_table_with_max_rows": {
            "database": source_table["database"],
            "table": source_table["table"],
            "base_filter": source_table["base_filter"],
        },
        "counts": counts,
        "metadata_gaps_physical": _metadata_gap_totals(reports),
        "source_domains": _aggregate_source_domains(reports, limit=source_limit),
        "source_path_prefixes": _aggregate_source_paths(reports, limit=source_limit),
    }


def _target_current_rows(
    reports: list[dict[str, Any]],
    *,
    domain: str,
    path_prefix: str,
) -> int:
    total = 0
    for report in reports:
        for row in report["source_path_prefixes"]:
            if row["domain"] == domain and str(row["path_prefix"]).startswith(path_prefix):
                total += int(row["rows"])
    return total


def _official_targets(
    procurement_reports: list[dict[str, Any]],
    finance_reports: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    geps_rows = _aggregate_counts(procurement_reports, "geps_like_rows")
    jfc_rows = _aggregate_counts(finance_reports, "jfc_like_rows")
    credit_rows = _aggregate_counts(finance_reports, "credit_guarantee_like_rows")
    return [
        {
            "task": "B11",
            "source_domain": "www.p-portal.go.jp",
            "source_path": "/pps-web-biz/",
            "label": "GEPS / government procurement portal notices",
            "current_rows": _target_current_rows(
                procurement_reports,
                domain="www.p-portal.go.jp",
                path_prefix="/pps-web-biz/",
            ),
            "reason": f"GEPS-like procurement rows currently detected: {geps_rows}",
            "network_fetch_performed": False,
        },
        {
            "task": "B11",
            "source_domain": "www.maff.go.jp",
            "source_path": "/j/supply/",
            "label": "Existing MAFF procurement pages",
            "current_rows": _target_current_rows(
                procurement_reports,
                domain="www.maff.go.jp",
                path_prefix="/j/supply/",
            ),
            "reason": "existing procurement rows are ministry-page based; normalize license/freshness",
            "network_fetch_performed": False,
        },
        {
            "task": "B12",
            "source_domain": "www.jfc.go.jp",
            "source_path": "/n/finance/search/",
            "label": "JFC finance product catalog",
            "current_rows": _target_current_rows(
                finance_reports,
                domain="www.jfc.go.jp",
                path_prefix="/n/finance/search/",
            ),
            "reason": f"JFC-like finance rows currently detected: {jfc_rows}",
            "network_fetch_performed": False,
        },
        {
            "task": "B12",
            "source_domain": "www.chusho.meti.go.jp",
            "source_path": "/kinyu/",
            "label": "SME Agency credit-guarantee policy pages",
            "current_rows": _target_current_rows(
                finance_reports,
                domain="www.chusho.meti.go.jp",
                path_prefix="/kinyu/",
            ),
            "reason": f"credit-guarantee-like finance rows currently detected: {credit_rows}",
            "network_fetch_performed": False,
        },
        {
            "task": "B12",
            "source_domain": "www.zenshinhoren.or.jp",
            "source_path": "/",
            "label": "National Federation of Credit Guarantee Corporations",
            "current_rows": _target_current_rows(
                finance_reports,
                domain="www.zenshinhoren.or.jp",
                path_prefix="/",
            ),
            "reason": "national credit-guarantee federation pages should backstop association data",
            "network_fetch_performed": False,
        },
        {
            "task": "B12",
            "source_domain": "*.cgc-*.or.jp",
            "source_path": "/",
            "label": "Prefectural credit guarantee association product pages",
            "current_rows": 0,
            "reason": "association-specific guarantee products are not represented as a normalized source family",
            "network_fetch_performed": False,
        },
    ]


def _findings(procurement: dict[str, Any], finance: dict[str, Any]) -> list[str]:
    findings: list[str] = []
    if procurement["counts"].get("geps_like_rows", 0) == 0:
        findings.append("B11: no GEPS/p-portal procurement rows detected in local candidate tables")
    if procurement["metadata_gaps_physical"]["license_missing"]:
        findings.append("B11: procurement rows are missing row-level license metadata")
    if finance["counts"].get("jfc_like_rows", 0) == 0:
        findings.append("B12: no JFC-like finance rows detected in local candidate tables")
    if finance["counts"].get("credit_guarantee_like_rows", 0) == 0:
        findings.append(
            "B12: no credit-guarantee-like finance rows detected in local candidate tables"
        )
    if finance["metadata_gaps_physical"]["license_missing"]:
        findings.append("B12: finance rows are missing row-level license metadata")
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
    procurement_reports = [table for table in table_reports if table["kind"] == PROCUREMENT]
    finance_reports = [table for table in table_reports if table["kind"] == FINANCE_LOANS]
    procurement = _summarize_kind(
        kind=PROCUREMENT,
        reports=procurement_reports,
        source_limit=sample_limit,
    )
    finance = _summarize_kind(
        kind=FINANCE_LOANS,
        reports=finance_reports,
        source_limit=sample_limit,
    )
    return {
        "ok": True,
        "complete": False,
        "generated_at": _utc_now(),
        "scope": "B11/B12 official-source preflight only; local SQLite, no crawling, no DB mutation",
        "read_mode": {
            "sqlite_only": True,
            "network_fetch_performed": False,
            "db_mutation_performed": False,
        },
        "databases": databases,
        "coverage": {
            PROCUREMENT: procurement,
            FINANCE_LOANS: finance,
        },
        "next_official_source_targets": _official_targets(procurement_reports, finance_reports),
        "findings": _findings(procurement, finance),
        "completion_status": {
            "B11": "preflight_only",
            "B12": "preflight_only",
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
        procurement = report["coverage"][PROCUREMENT]
        finance = report["coverage"][FINANCE_LOANS]
        print(f"b11_procurement_rows={procurement['counts'].get('procurement_like_rows', 0)}")
        print(f"b11_geps_like_rows={procurement['counts'].get('geps_like_rows', 0)}")
        print(f"b12_loan_like_rows={finance['counts'].get('loan_like_rows', 0)}")
        print(f"b12_jfc_like_rows={finance['counts'].get('jfc_like_rows', 0)}")
        print(
            "b12_credit_guarantee_like_rows="
            f"{finance['counts'].get('credit_guarantee_like_rows', 0)}"
        )
        print("complete=False")
        if not args.no_write:
            print(f"output={args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
