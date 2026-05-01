#!/usr/bin/env python3
"""Generate an offline B4 e-Gov law full-text saturation plan.

This report is read-only. It opens the local jpintel SQLite database in
query-only mode, reads the existing incremental law loader/workflow defaults
from local files, and emits future operator commands only as strings. It does
not crawl, call e-Gov, or mutate SQLite.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sqlite3
from collections import Counter
from datetime import UTC, datetime
from math import ceil
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

REPO_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_DB = REPO_ROOT / "data" / "jpintel.db"
DEFAULT_DRIVER = REPO_ROOT / "scripts" / "cron" / "incremental_law_fulltext.py"
DEFAULT_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "incremental-law-load.yml"
DEFAULT_OUTPUT = REPO_ROOT / "analysis_wave18" / "egov_law_fulltext_plan_2026-05-01.json"

REPORT_DATE = "2026-05-01"
ACCEPTANCE_BODY_TEXT_TARGET = 5_000
FALLBACK_BATCH_LIMIT = 600
EGOV_DOMAIN_SUFFIX = ".e-gov.go.jp"


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _rel(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _readonly_connect(path: Path) -> sqlite3.Connection:
    if not path.exists():
        raise FileNotFoundError(path)
    conn = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = ON")
    return conn


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('table', 'view') AND name = ?",
        (table,),
    ).fetchone()
    return row is not None


def _column_names(conn: sqlite3.Connection, table: str) -> set[str]:
    if not _table_exists(conn, table):
        return set()
    return {
        str(row["name"])
        for row in conn.execute(f"PRAGMA table_info({_quote_ident(table)})")
    }


def _count_rows(
    conn: sqlite3.Connection,
    table: str,
    where_sql: str | None = None,
) -> int:
    sql = f"SELECT COUNT(*) AS c FROM {_quote_ident(table)}"
    if where_sql:
        sql += f" WHERE {where_sql}"
    row = conn.execute(sql).fetchone()
    return int(row["c"] or 0)


def _present_where(column: str) -> str:
    quoted = _quote_ident(column)
    return f"{quoted} IS NOT NULL AND TRIM(CAST({quoted} AS TEXT)) <> ''"


def _pct(part: int | None, total: int) -> float | None:
    if part is None:
        return None
    if total == 0:
        return 100.0
    return round((part / total) * 100, 2)


def _metadata_completeness(
    conn: sqlite3.Connection,
    table: str,
    columns: set[str],
    column: str,
    total: int,
) -> dict[str, Any]:
    if column not in columns:
        return {
            "column_present": False,
            "present": None,
            "missing": None,
            "present_pct": None,
        }
    present = _count_rows(conn, table, _present_where(column))
    return {
        "column_present": True,
        "present": present,
        "missing": total - present,
        "present_pct": _pct(present, total),
    }


def _body_text_completeness(
    conn: sqlite3.Connection,
    table: str,
    columns: set[str],
    total: int,
) -> dict[str, Any]:
    if "body_text" not in columns:
        return {
            "column_present": False,
            "present": 0,
            "missing": total,
            "present_pct": _pct(0, total),
            "missing_pct": _pct(total, total),
        }
    present = _count_rows(conn, table, _present_where("body_text"))
    missing = total - present
    return {
        "column_present": True,
        "present": present,
        "missing": missing,
        "present_pct": _pct(present, total),
        "missing_pct": _pct(missing, total),
    }


def _normalize_domain(url: str) -> str:
    parsed = urlparse(url)
    if not parsed.netloc and "://" not in url:
        parsed = urlparse("//" + url)
    return parsed.netloc.lower()


def _domain_counts(
    conn: sqlite3.Connection,
    table: str,
    columns: set[str],
    column: str,
) -> list[dict[str, Any]]:
    if column not in columns:
        return []
    rows = conn.execute(
        f"""
        SELECT TRIM(CAST({_quote_ident(column)} AS TEXT)) AS url, COUNT(*) AS rows
          FROM {_quote_ident(table)}
         WHERE {_present_where(column)}
      GROUP BY TRIM(CAST({_quote_ident(column)} AS TEXT))
        """,
    ).fetchall()
    counts: Counter[str] = Counter()
    invalid = 0
    for row in rows:
        domain = _normalize_domain(str(row["url"]))
        if domain:
            counts[domain] += int(row["rows"] or 0)
        else:
            invalid += int(row["rows"] or 0)
    output = [
        {"domain": domain, "rows": rows}
        for domain, rows in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    ]
    if invalid:
        output.append({"domain": "(invalid_or_relative_url)", "rows": invalid})
    return output


def _group_counts(
    conn: sqlite3.Connection,
    table: str,
    columns: set[str],
    column: str,
    *,
    limit: int = 25,
) -> list[dict[str, Any]]:
    if column not in columns:
        return []
    rows = conn.execute(
        f"""
        SELECT COALESCE(NULLIF(TRIM(CAST({_quote_ident(column)} AS TEXT)), ''), '(missing)')
               AS value,
               COUNT(*) AS rows
          FROM {_quote_ident(table)}
      GROUP BY value
      ORDER BY rows DESC, value ASC
         LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [{"value": str(row["value"]), "rows": int(row["rows"] or 0)} for row in rows]


def _is_egov_domain(domain: str) -> bool:
    return domain == "e-gov.go.jp" or domain.endswith(EGOV_DOMAIN_SUFFIX)


def _official_domain_rows(domain_counts: list[dict[str, Any]]) -> int:
    return sum(
        int(row["rows"])
        for row in domain_counts
        if _is_egov_domain(str(row["domain"]))
    )


def collect_law_coverage(db_path: Path) -> dict[str, Any]:
    """Return current law/body-text/source coverage for the local DB."""
    if not db_path.exists():
        return {
            "database": str(db_path),
            "exists": False,
            "table": "laws",
            "table_exists": False,
            "total_laws": 0,
            "body_text": {
                "column_present": False,
                "present": 0,
                "missing": 0,
                "present_pct": 100.0,
                "missing_pct": 0.0,
            },
            "metadata_completeness": {},
            "source_domains": [],
            "full_text_domains": [],
            "group_counts": {},
        }

    with _readonly_connect(db_path) as conn:
        if not _table_exists(conn, "laws"):
            return {
                "database": str(db_path),
                "exists": True,
                "table": "laws",
                "table_exists": False,
                "total_laws": 0,
                "body_text": {
                    "column_present": False,
                    "present": 0,
                    "missing": 0,
                    "present_pct": 100.0,
                    "missing_pct": 0.0,
                },
                "metadata_completeness": {},
                "source_domains": [],
                "full_text_domains": [],
                "group_counts": {},
            }

        columns = _column_names(conn, "laws")
        total = _count_rows(conn, "laws")
        metadata_columns = (
            "source_url",
            "full_text_url",
            "source_checksum",
            "fetched_at",
            "updated_at",
        )
        source_domains = _domain_counts(conn, "laws", columns, "source_url")
        full_text_domains = _domain_counts(conn, "laws", columns, "full_text_url")
        metadata = {
            column: _metadata_completeness(conn, "laws", columns, column, total)
            for column in metadata_columns
        }
        metadata["source_url"]["official_egov_rows"] = _official_domain_rows(source_domains)
        metadata["source_url"]["official_egov_pct"] = _pct(
            int(metadata["source_url"]["official_egov_rows"]),
            total,
        )
        metadata["full_text_url"]["official_egov_rows"] = _official_domain_rows(
            full_text_domains
        )
        metadata["full_text_url"]["official_egov_pct"] = _pct(
            int(metadata["full_text_url"]["official_egov_rows"]),
            total,
        )

        return {
            "database": str(db_path),
            "exists": True,
            "table": "laws",
            "table_exists": True,
            "total_laws": total,
            "body_text": _body_text_completeness(conn, "laws", columns, total),
            "metadata_completeness": metadata,
            "source_domains": source_domains,
            "full_text_domains": full_text_domains,
            "group_counts": {
                "law_type": _group_counts(conn, "laws", columns, "law_type"),
                "revision_status": _group_counts(conn, "laws", columns, "revision_status"),
                "ministry": _group_counts(conn, "laws", columns, "ministry"),
            },
        }


def _ast_constant_from_assign(path: Path, name: str) -> Any | None:
    if not path.exists():
        return None
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:
        return None
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == name:
                return ast.literal_eval(node.value)
    return None


def _regex_int(pattern: str, text: str) -> int | None:
    match = re.search(pattern, text)
    if not match:
        return None
    return int(match.group(1))


def inspect_incremental_loader(driver_path: Path, workflow_path: Path) -> dict[str, Any]:
    """Read local loader/workflow defaults without importing or executing them."""
    driver_default = _ast_constant_from_assign(driver_path, "_DEFAULT_LIMIT")
    rate_sleep = _ast_constant_from_assign(driver_path, "_RATE_SLEEP_SEC")
    workflow_text = workflow_path.read_text(encoding="utf-8") if workflow_path.exists() else ""
    workflow_default = _regex_int(r'default:\s*["\']?(\d+)["\']?', workflow_text)
    shell_default = _regex_int(r'INPUT_LIMIT:-(\d+)', workflow_text)
    timeout_minutes = _regex_int(r"timeout-minutes:\s*(\d+)", workflow_text)
    effective_limit = next(
        (
            value
            for value in (driver_default, shell_default, workflow_default, FALLBACK_BATCH_LIMIT)
            if isinstance(value, int)
        ),
        FALLBACK_BATCH_LIMIT,
    )
    return {
        "driver_path": str(driver_path),
        "workflow_path": str(workflow_path),
        "driver_exists": driver_path.exists(),
        "workflow_exists": workflow_path.exists(),
        "driver_default_limit": driver_default,
        "workflow_dispatch_default_limit": workflow_default,
        "workflow_shell_default_limit": shell_default,
        "effective_batch_limit": effective_limit,
        "rate_sleep_sec": rate_sleep,
        "workflow_timeout_minutes": timeout_minutes,
        "default_limit_consistent": (
            driver_default == workflow_default == shell_default
            if all(isinstance(v, int) for v in (driver_default, workflow_default, shell_default))
            else False
        ),
    }


def build_batch_estimate(
    coverage: dict[str, Any],
    batch_limit: int,
    acceptance_target: int = ACCEPTANCE_BODY_TEXT_TARGET,
) -> dict[str, Any]:
    body_text = coverage["body_text"]
    current_present = int(body_text["present"] or 0)
    total_laws = int(coverage["total_laws"] or 0)
    missing = int(body_text["missing"] or 0)
    needed_for_acceptance = max(acceptance_target - current_present, 0)
    return {
        "batch_limit": batch_limit,
        "acceptance_target_body_text": acceptance_target,
        "current_body_text_present": current_present,
        "body_text_needed_for_acceptance": needed_for_acceptance,
        "batches_to_acceptance": ceil(needed_for_acceptance / batch_limit)
        if batch_limit > 0
        else None,
        "total_missing_body_text": missing,
        "batches_to_saturate_current_laws": ceil(missing / batch_limit)
        if batch_limit > 0
        else None,
        "acceptance_reachable_with_current_law_count": total_laws >= acceptance_target,
        "current_saturation_pct": body_text["present_pct"],
    }


def acceptance_sql(acceptance_target: int = ACCEPTANCE_BODY_TEXT_TARGET) -> str:
    return (
        "SELECT CASE WHEN COUNT(*) >= "
        f"{acceptance_target} THEN 'PASS' ELSE 'FAIL' END AS b4_body_text_acceptance, "
        "COUNT(*) AS laws_with_body_text FROM laws "
        "WHERE body_text IS NOT NULL AND TRIM(CAST(body_text AS TEXT)) <> '';"
    )


def count_body_text_sql() -> str:
    return (
        "SELECT COUNT(*) AS laws_with_body_text FROM laws "
        "WHERE body_text IS NOT NULL AND TRIM(CAST(body_text AS TEXT)) <> '';"
    )


def _sqlite_command(db_path: Path, sql: str) -> str:
    return f"sqlite3 '{_rel(db_path)}' \"{sql}\""


def command_strings(
    *,
    db_path: Path,
    driver_path: Path,
    workflow_path: Path,
    output_path: Path,
    batch_limit: int,
    acceptance_target: int,
) -> dict[str, list[str]]:
    workflow_name = workflow_path.name
    return {
        "report_only": [
            (
                "python scripts/etl/report_egov_law_fulltext_plan.py "
                f"--db '{_rel(db_path)}' "
                f"--driver '{_rel(driver_path)}' "
                f"--workflow '{_rel(workflow_path)}' "
                f"--output '{_rel(output_path)}' "
                "--write-report"
            ),
        ],
        "incremental_loader_future_run": [
            (
                "python scripts/cron/incremental_law_fulltext.py "
                f"--db /data/autonomath.db --limit {batch_limit} "
                "--log-file /data/law_load_log.jsonl --print-priority"
            ),
            (
                "python scripts/cron/incremental_law_fulltext.py "
                f"--db /data/autonomath.db --limit {batch_limit} "
                "--log-file /data/law_load_log.jsonl --dry-run"
            ),
            (
                "python scripts/cron/incremental_law_fulltext.py "
                f"--db /data/autonomath.db --limit {batch_limit} "
                "--log-file /data/law_load_log.jsonl"
            ),
            f"gh workflow run {workflow_name} -f limit={batch_limit} -f dry_run=true",
            f"gh workflow run {workflow_name} -f limit={batch_limit} -f dry_run=false",
        ],
        "acceptance": [
            _sqlite_command(db_path, count_body_text_sql()),
            _sqlite_command(db_path, acceptance_sql(acceptance_target)),
        ],
    }


def _readiness_gaps(coverage: dict[str, Any], loader: dict[str, Any]) -> list[dict[str, Any]]:
    gaps: list[dict[str, Any]] = []
    if not coverage.get("exists"):
        gaps.append(
            {
                "code": "jpintel_db:missing",
                "severity": "blocker",
                "message": f"local database not found: {coverage['database']}",
            }
        )
    if coverage.get("exists") and not coverage.get("table_exists"):
        gaps.append(
            {
                "code": "laws_table:missing",
                "severity": "blocker",
                "message": "local database does not contain a laws table",
            }
        )
    if coverage.get("table_exists") and not coverage["body_text"]["column_present"]:
        gaps.append(
            {
                "code": "laws.body_text:missing_column",
                "severity": "schema_gap",
                "message": "local laws table has no body_text column, so B4 is not complete",
            }
        )
    if loader["effective_batch_limit"] != FALLBACK_BATCH_LIMIT:
        gaps.append(
            {
                "code": "batch_limit:not_600",
                "severity": "warning",
                "message": "incremental loader default differs from the B4 600-law plan",
            }
        )
    if not loader["default_limit_consistent"]:
        gaps.append(
            {
                "code": "batch_limit:inconsistent_defaults",
                "severity": "warning",
                "message": "driver/workflow default limits are not fully consistent",
            }
        )
    return gaps


def _plan_steps(coverage: dict[str, Any], estimate: dict[str, Any]) -> list[dict[str, Any]]:
    body_column_status = (
        "ready" if coverage["body_text"]["column_present"] else "needs_schema_or_ingest_target"
    )
    return [
        {
            "step": "confirm_body_text_storage",
            "status": body_column_status,
            "detail": "B4 acceptance counts laws.body_text rows in local jpintel.db.",
        },
        {
            "step": "run_incremental_batches",
            "status": "pending_operator_run",
            "batch_limit": estimate["batch_limit"],
            "batches_to_acceptance": estimate["batches_to_acceptance"],
            "batches_to_saturate_current_laws": estimate["batches_to_saturate_current_laws"],
        },
        {
            "step": "verify_acceptance",
            "status": "pending",
            "target": f">={estimate['acceptance_target_body_text']} laws.body_text rows",
        },
    ]


def build_report(
    *,
    db_path: Path,
    driver_path: Path,
    workflow_path: Path,
    output_path: Path,
    acceptance_target: int = ACCEPTANCE_BODY_TEXT_TARGET,
) -> dict[str, Any]:
    coverage = collect_law_coverage(db_path)
    loader = inspect_incremental_loader(driver_path, workflow_path)
    batch_limit = int(loader["effective_batch_limit"] or FALLBACK_BATCH_LIMIT)
    estimate = build_batch_estimate(coverage, batch_limit, acceptance_target)
    commands = command_strings(
        db_path=db_path,
        driver_path=driver_path,
        workflow_path=workflow_path,
        output_path=output_path,
        batch_limit=batch_limit,
        acceptance_target=acceptance_target,
    )
    readiness_gaps = _readiness_gaps(coverage, loader)
    command_count = sum(len(group) for group in commands.values())
    return {
        "ok": coverage.get("exists", False) and coverage.get("table_exists", False),
        "generated_at": _utc_now(),
        "report_date": REPORT_DATE,
        "scope": "B4 e-Gov law full-text saturation plan; offline/no crawling/no DB mutation",
        "read_mode": {
            "sqlite_only": True,
            "local_incremental_script_read": loader["driver_exists"],
            "local_incremental_workflow_read": loader["workflow_exists"],
            "network_fetch_performed": False,
            "download_performed": False,
            "db_mutation_performed": False,
            "commands_are_strings_only": True,
        },
        "completion_status": {"B4": "plan_only", "complete": False},
        "inputs": {
            "db": str(db_path),
            "driver": str(driver_path),
            "workflow": str(workflow_path),
            "output": str(output_path),
        },
        "incremental_loader": loader,
        "law_coverage": coverage,
        "batch_estimate": estimate,
        "acceptance": {
            "target": f">={acceptance_target} laws.body_text rows",
            "requires_column": "laws.body_text",
            "count_query": count_body_text_sql(),
            "threshold_query": acceptance_sql(acceptance_target),
            "command": _sqlite_command(db_path, acceptance_sql(acceptance_target)),
            "current_schema_column_present": coverage["body_text"]["column_present"],
        },
        "sources": [
            {
                "source_id": "EGOV_LAWS",
                "official": True,
                "source_domains": ["laws.e-gov.go.jp", "elaws.e-gov.go.jp"],
                "local_table": f"{db_path}:laws",
                "license_assumption": {
                    "label": "e-gov_law_search_terms",
                    "attribution_required": True,
                    "review_required": False,
                },
            }
        ],
        "commands": commands,
        "readiness_gaps": readiness_gaps,
        "plan": _plan_steps(coverage, estimate),
        "report_counts": {
            "command_count": command_count,
            "readiness_gap_count": len(readiness_gaps),
            "source_count": 1,
        },
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
    parser.add_argument("--driver", type=Path, default=DEFAULT_DRIVER)
    parser.add_argument("--workflow", type=Path, default=DEFAULT_WORKFLOW)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--acceptance-target", type=int, default=ACCEPTANCE_BODY_TEXT_TARGET)
    parser.add_argument("--write-report", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    report = build_report(
        db_path=args.db,
        driver_path=args.driver,
        workflow_path=args.workflow,
        output_path=args.output,
        acceptance_target=args.acceptance_target,
    )

    if args.write_report:
        write_report(report, args.output)

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        coverage = report["law_coverage"]
        estimate = report["batch_estimate"]
        print(f"laws_total={coverage['total_laws']}")
        print(f"body_text_present={coverage['body_text']['present']}")
        print(f"body_text_missing={coverage['body_text']['missing']}")
        print(f"batch_limit={estimate['batch_limit']}")
        print(f"batches_to_acceptance={estimate['batches_to_acceptance']}")
        print(f"batches_to_saturate_current_laws={estimate['batches_to_saturate_current_laws']}")
        if args.write_report:
            print(f"output={args.output}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
