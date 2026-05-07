#!/usr/bin/env python3
"""Offline B2 NTA invoice bulk acquisition/reconcile plan.

This script is intentionally report-only. It opens local SQLite databases in
read-only mode, inspects local workflow/cache/log metadata, and emits future
operator commands as inert strings. It performs no network access, no downloads,
and no database writes.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_JPINTEL_DB = REPO_ROOT / "data" / "jpintel.db"
DEFAULT_AUTONOMATH_DB = REPO_ROOT / "autonomath.db"
DEFAULT_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "nta-bulk-monthly.yml"
DEFAULT_OUTPUT = REPO_ROOT / "analysis_wave18" / "nta_invoice_bulk_plan_2026-05-01.json"
DEFAULT_LOCAL_CACHE_DIR = Path("/tmp/jpintel_invoice_registrants_cache")
DEFAULT_PROD_CACHE_DIR = Path("/data/_cache/nta_invoice")
DEFAULT_LOCAL_LOAD_LOG = REPO_ROOT / "data" / "invoice_load_log.jsonl"
DEFAULT_PROD_LOAD_LOG = Path("/data/invoice_load_log.jsonl")
DEFAULT_ARTIFACT_ROOT = REPO_ROOT / "data" / "bulk" / "nta_invoice"

REPORT_DATE = "2026-05-01"
FULL_POPULATION_ESTIMATE = 4_000_000
MIN_FREE_BYTES_FULL = 2 * 1024 * 1024 * 1024
SOURCE_ROOT = "https://www.invoice-kohyo.nta.go.jp/"
SOURCE_DOWNLOAD = "https://www.invoice-kohyo.nta.go.jp/download/"
SOURCE_ZENKEN = "https://www.invoice-kohyo.nta.go.jp/download/zenken"
SOURCE_SABUN = "https://www.invoice-kohyo.nta.go.jp/download/sabun"


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _qident(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _connect_readonly(path: Path) -> sqlite3.Connection:
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


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    if not _table_exists(conn, table):
        return set()
    return {str(row["name"]) for row in conn.execute(f"PRAGMA table_info({_qident(table)})")}


def _count_rows(
    conn: sqlite3.Connection,
    table: str,
    where_sql: str | None = None,
) -> int | None:
    if not _table_exists(conn, table):
        return None
    sql = f"SELECT COUNT(*) AS c FROM {_qident(table)}"
    if where_sql:
        sql += f" WHERE {where_sql}"
    try:
        row = conn.execute(sql).fetchone()
    except sqlite3.OperationalError:
        return None
    return int(row["c"] or 0)


def _group_counts(
    conn: sqlite3.Connection,
    table: str,
    column: str,
) -> dict[str, int]:
    if column not in _columns(conn, table):
        return {}
    rows = conn.execute(
        f"""
        SELECT COALESCE(NULLIF(TRIM(CAST({_qident(column)} AS TEXT)), ''), '(missing)') AS k,
               COUNT(*) AS c
          FROM {_qident(table)}
         GROUP BY k
         ORDER BY c DESC, k ASC
        """
    ).fetchall()
    return {str(row["k"]): int(row["c"] or 0) for row in rows}


def _single_value(
    conn: sqlite3.Connection,
    table: str,
    expression: str,
) -> Any:
    if not _table_exists(conn, table):
        return None
    try:
        row = conn.execute(f"SELECT {expression} AS v FROM {_qident(table)}").fetchone()
    except sqlite3.OperationalError:
        return None
    return row["v"] if row is not None else None


def _db_base(path: Path) -> dict[str, Any]:
    return {
        "path": str(path),
        "exists": path.exists(),
        "size_bytes": path.stat().st_size if path.exists() else 0,
        "open_mode": "sqlite_uri_mode_ro_query_only",
    }


def collect_jpintel_invoice_counts(path: Path) -> dict[str, Any]:
    report = _db_base(path)
    if not path.exists():
        report.update({"table_exists": False, "counts": {}, "error": "database file not found"})
        return report

    with _connect_readonly(path) as conn:
        table_exists = _table_exists(conn, "invoice_registrants")
        columns = _columns(conn, "invoice_registrants")
        counts: dict[str, Any] = {
            "invoice_registrants": _count_rows(conn, "invoice_registrants"),
            "by_registrant_kind": _group_counts(
                conn,
                "invoice_registrants",
                "registrant_kind",
            ),
        }
        if "houjin_bangou" in columns:
            counts["with_houjin_bangou"] = _count_rows(
                conn,
                "invoice_registrants",
                "houjin_bangou IS NOT NULL AND TRIM(houjin_bangou) <> ''",
            )
            total = counts["invoice_registrants"]
            linked = counts["with_houjin_bangou"]
            if isinstance(total, int) and isinstance(linked, int):
                counts["without_houjin_bangou"] = total - linked
        if "last_updated_nta" in columns:
            counts["with_last_updated_nta"] = _count_rows(
                conn,
                "invoice_registrants",
                "last_updated_nta IS NOT NULL AND TRIM(last_updated_nta) <> ''",
            )
            counts["max_last_updated_nta"] = _single_value(
                conn,
                "invoice_registrants",
                "MAX(last_updated_nta)",
            )
        if "registered_date" in columns:
            counts["min_registered_date"] = _single_value(
                conn,
                "invoice_registrants",
                "MIN(registered_date)",
            )
            counts["max_registered_date"] = _single_value(
                conn,
                "invoice_registrants",
                "MAX(registered_date)",
            )
        if "revoked_date" in columns:
            counts["revoked_rows"] = _count_rows(
                conn,
                "invoice_registrants",
                "revoked_date IS NOT NULL AND TRIM(revoked_date) <> ''",
            )
        if "expired_date" in columns:
            counts["expired_rows"] = _count_rows(
                conn,
                "invoice_registrants",
                "expired_date IS NOT NULL AND TRIM(expired_date) <> ''",
            )

    current = counts.get("invoice_registrants")
    remaining = None
    coverage_pct = None
    if isinstance(current, int):
        remaining = max(FULL_POPULATION_ESTIMATE - current, 0)
        coverage_pct = round((current / FULL_POPULATION_ESTIMATE) * 100, 4)
    report.update(
        {
            "table_exists": table_exists,
            "columns": sorted(columns),
            "counts": counts,
            "full_population_estimate": FULL_POPULATION_ESTIMATE,
            "remaining_rows_estimate": remaining,
            "coverage_pct_estimate": coverage_pct,
        }
    )
    return report


def collect_autonomath_invoice_counts(path: Path) -> dict[str, Any]:
    report = _db_base(path)
    if not path.exists():
        report.update({"invoice_tables": {}, "counts": {}, "error": "database file not found"})
        return report

    with _connect_readonly(path) as conn:
        tables = {
            "jpi_invoice_registrants": _table_exists(conn, "jpi_invoice_registrants"),
            "invoice_registrants": _table_exists(conn, "invoice_registrants"),
            "am_entities": _table_exists(conn, "am_entities"),
        }
        counts: dict[str, Any] = {
            "jpi_invoice_registrants": _count_rows(conn, "jpi_invoice_registrants"),
            "invoice_registrants": _count_rows(conn, "invoice_registrants"),
        }
        entity_columns = _columns(conn, "am_entities")
        if "record_kind" in entity_columns:
            counts["am_entities_invoice_registrant"] = _count_rows(
                conn,
                "am_entities",
                "record_kind = 'invoice_registrant'",
            )

    report.update({"invoice_tables": tables, "counts": counts})
    return report


def _cache_dir_report(path: Path) -> dict[str, Any]:
    report: dict[str, Any] = {
        "path": str(path),
        "exists": path.exists(),
        "is_dir": path.is_dir(),
        "file_count": 0,
        "total_bytes": 0,
        "sample_files": [],
    }
    if not path.is_dir():
        return report
    sample_files: list[str] = []
    for child in sorted(path.rglob("*")):
        if not child.is_file():
            continue
        report["file_count"] += 1
        report["total_bytes"] += child.stat().st_size
        if len(sample_files) < 10:
            sample_files.append(str(child))
    report["sample_files"] = sample_files
    return report


def _load_log_report(path: Path) -> dict[str, Any]:
    report: dict[str, Any] = {
        "path": str(path),
        "exists": path.exists(),
        "is_file": path.is_file(),
        "size_bytes": path.stat().st_size if path.is_file() else 0,
        "line_count": 0,
        "latest_entry": None,
    }
    if not path.is_file():
        return report
    latest = ""
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if line.strip():
                report["line_count"] += 1
                latest = line.strip()
    if latest:
        try:
            report["latest_entry"] = json.loads(latest)
        except json.JSONDecodeError:
            report["latest_entry"] = {"raw": latest, "parse_error": True}
    return report


def _disk_report(path: Path) -> dict[str, Any]:
    target = path if path.exists() else path.parent
    while not target.exists() and target != target.parent:
        target = target.parent
    usage = shutil.disk_usage(target)
    return {
        "path": str(target),
        "free_bytes": usage.free,
        "total_bytes": usage.total,
        "required_free_bytes_full": MIN_FREE_BYTES_FULL,
        "local_ok_for_full_estimate": usage.free >= MIN_FREE_BYTES_FULL,
    }


def _extract_workflow_status(path: Path) -> dict[str, Any]:
    report: dict[str, Any] = {
        "path": str(path),
        "exists": path.exists(),
        "name": None,
        "github_enabled_status": "not_checked_offline",
        "schedule_crons": [],
        "workflow_dispatch": False,
        "timeout_minutes": None,
        "concurrency_group": None,
        "monthly_full_cron_wired": False,
        "daily_delta_cron_wired": False,
        "driver_script_referenced": False,
        "prod_db_path_referenced": False,
        "prod_cache_dir_referenced": False,
        "prod_load_log_referenced": False,
        "cron_status": "missing_local_yaml",
    }
    if not path.exists():
        return report

    text = path.read_text(encoding="utf-8")
    name_match = re.search(r"(?m)^name:\s*(.+?)\s*$", text)
    if name_match:
        report["name"] = name_match.group(1).strip().strip("\"'")
    report["schedule_crons"] = re.findall(r"cron:\s*[\"']([^\"']+)[\"']", text)
    report["workflow_dispatch"] = "workflow_dispatch:" in text
    timeout_match = re.search(r"(?m)^\s*timeout-minutes:\s*(\d+)\s*$", text)
    if timeout_match:
        report["timeout_minutes"] = int(timeout_match.group(1))
    group_match = re.search(r"(?m)^\s*group:\s*(.+?)\s*$", text)
    if group_match:
        report["concurrency_group"] = group_match.group(1).strip().strip("\"'")

    report["driver_script_referenced"] = "scripts/cron/ingest_nta_invoice_bulk.py" in text
    report["prod_db_path_referenced"] = "--db /data/jpintel.db" in text
    report["prod_cache_dir_referenced"] = "--cache-dir /data/_cache/nta_invoice" in text
    report["prod_load_log_referenced"] = "--log-file /data/invoice_load_log.jsonl" in text
    crons = set(report["schedule_crons"])
    report["monthly_full_cron_wired"] = (
        "0 18 1 * *" in crons
        and report["driver_script_referenced"]
        and report["prod_db_path_referenced"]
    )
    # Dispatch supports delta mode, but there is no scheduled daily delta job in
    # the local workflow file.
    report["daily_delta_cron_wired"] = False
    if report["monthly_full_cron_wired"]:
        report["cron_status"] = "monthly_full_yaml_wired_offline"
    else:
        report["cron_status"] = "local_yaml_present_but_monthly_full_not_wired"
    report["schedule_notes"] = [
        {
            "cron": cron,
            "interpretation": (
                "18:00 UTC on day 1; 03:00 JST on day 2"
                if cron == "0 18 1 * *"
                else "not interpreted by this offline parser"
            ),
        }
        for cron in report["schedule_crons"]
    ]
    return report


def _rel(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _command_strings(
    *,
    jpintel_db: Path,
    autonomath_db: Path,
    local_cache_dir: Path,
    prod_cache_dir: Path,
    prod_load_log: Path,
) -> dict[str, list[str]]:
    return {
        "local_read_only_counts": [
            (
                f"sqlite3 'file:{_rel(jpintel_db)}?mode=ro' "
                '"SELECT COUNT(*) FROM invoice_registrants;"'
            ),
            (
                f"sqlite3 'file:{_rel(jpintel_db)}?mode=ro' "
                '"SELECT registrant_kind, COUNT(*) FROM invoice_registrants '
                'GROUP BY registrant_kind ORDER BY COUNT(*) DESC;"'
            ),
            (
                f"sqlite3 'file:{_rel(autonomath_db)}?mode=ro' "
                '"SELECT COUNT(*) FROM jpi_invoice_registrants;"'
            ),
        ],
        "operator_preflight_no_download": [
            'flyctl ssh console -a autonomath-api -C "df -h /data"',
            (
                "flyctl ssh console -a autonomath-api -C "
                "\"sqlite3 'file:/data/jpintel.db?mode=ro' "
                "'SELECT COUNT(*) FROM invoice_registrants;'\""
            ),
            (
                "flyctl ssh console -a autonomath-api -C "
                f"\"test -d '{prod_cache_dir}' && du -sh '{prod_cache_dir}' || true\""
            ),
            (
                "flyctl ssh console -a autonomath-api -C "
                f"\"test -f '{prod_load_log}' && tail -n 3 '{prod_load_log}' || true\""
            ),
        ],
        "local_smoke_dry_run_deferred": [
            (
                "python scripts/cron/ingest_nta_invoice_bulk.py "
                f"--db '{_rel(jpintel_db)}' --mode full --format csv --dry-run "
                f"--limit 100000 --cache-dir '{local_cache_dir}'"
            ),
        ],
        "prod_full_acquisition_deferred": [
            (
                "flyctl ssh console -a autonomath-api -C "
                '"/app/.venv/bin/python /app/scripts/cron/ingest_nta_invoice_bulk.py '
                "--db /data/jpintel.db --mode full --format csv "
                "--cache-dir /data/_cache/nta_invoice "
                '--log-file /data/invoice_load_log.jsonl --batch-size 10000"'
            ),
        ],
        "post_load_reconcile_deferred": [
            (
                "flyctl ssh console -a autonomath-api -C "
                "\"sqlite3 'file:/data/jpintel.db?mode=ro' "
                "'SELECT COUNT(*) FROM invoice_registrants;'\""
            ),
            (
                f"sqlite3 'file:{_rel(jpintel_db)}?mode=ro' "
                '"SELECT registrant_kind, COUNT(*) FROM invoice_registrants '
                'GROUP BY registrant_kind ORDER BY COUNT(*) DESC;"'
            ),
            (
                f"sqlite3 'file:{_rel(autonomath_db)}?mode=ro' "
                '"SELECT COUNT(*) FROM jpi_invoice_registrants;"'
            ),
        ],
    }


def _expected_artifacts(
    *,
    jpintel_db: Path,
    autonomath_db: Path,
    artifact_root: Path,
    local_cache_dir: Path,
    prod_cache_dir: Path,
    local_load_log: Path,
    prod_load_log: Path,
) -> dict[str, Any]:
    return {
        "source_urls": {
            "root": SOURCE_ROOT,
            "download_landing": SOURCE_DOWNLOAD,
            "full_index": SOURCE_ZENKEN,
            "delta_index": SOURCE_SABUN,
            "delivery_shape": (
                "https://www.invoice-kohyo.nta.go.jp/download/{zenken|sabun}/"
                "dlfile?dlFilKanriNo=<opaque>&type=<01|02|03>"
            ),
        },
        "local_paths": {
            "jpintel_db_table": f"{jpintel_db}:invoice_registrants",
            "autonomath_mirror_table": f"{autonomath_db}:jpi_invoice_registrants",
            "cache_dir": str(local_cache_dir),
            "cache_file_template": str(local_cache_dir / "nta_<dlFilKanriNo>_csv.zip"),
            "load_log": str(local_load_log),
            "artifact_root": str(artifact_root),
            "full_index_snapshot": str(artifact_root / "zenken_index_${YYYYMMDD}.html"),
            "full_snapshot_dir_template": str(artifact_root / "zenken" / "${YYYYMMDD}"),
        },
        "prod_paths": {
            "jpintel_db": "/data/jpintel.db",
            "cache_dir": str(prod_cache_dir),
            "cache_file_template": str(prod_cache_dir / "nta_<dlFilKanriNo>_csv.zip"),
            "load_log": str(prod_load_log),
        },
    }


def _privacy_and_aggregation_constraints() -> list[dict[str, Any]]:
    return [
        {
            "code": "bulk_download_only",
            "constraint": "Use NTA bulk download endpoints only; do not scrape the public web search UI.",
            "applies_to": ["acquisition", "refresh"],
        },
        {
            "code": "pdl_v1_attribution",
            "constraint": "Every surface exposing invoice rows must preserve source attribution and edit notice.",
            "source": SOURCE_ROOT,
            "applies_to": ["api", "mcp", "exports", "logs"],
        },
        {
            "code": "sole_proprietor_personal_data",
            "constraint": (
                "The full feed includes sole-proprietor rows; publish privacy/takedown handling "
                "before broad full-population mirroring."
            ),
            "applies_to": ["publication", "support", "retention"],
        },
        {
            "code": "aggregate_public_reporting",
            "constraint": (
                "Public progress reports should use aggregate counts only; suppress or bucket any "
                "derived slices below five rows."
            ),
            "applies_to": ["reporting", "analytics"],
        },
        {
            "code": "no_public_bulk_dump",
            "constraint": "Do not expose a customer-facing full dump; point bulk users to NTA's official source.",
            "applies_to": ["api", "exports"],
        },
    ]


def _plan_steps() -> list[dict[str, Any]]:
    return [
        {
            "step": 1,
            "name": "offline_inventory",
            "status": "done_by_this_report",
            "notes": "Local SQLite counts, workflow YAML, cache/log metadata, and disk headroom inspected.",
        },
        {
            "step": 2,
            "name": "prod_preflight",
            "status": "deferred",
            "notes": "Verify Fly volume headroom, DB count, cache dir, and latest load log before any fetch.",
        },
        {
            "step": 3,
            "name": "smoke_dry_run",
            "status": "deferred",
            "notes": "Run full-mode dry run with a row limit in an operator window; dry run may fetch cache bytes.",
        },
        {
            "step": 4,
            "name": "monthly_full_bulk",
            "status": "deferred",
            "notes": "Run the cron driver on Fly against /data/jpintel.db with /data/_cache/nta_invoice.",
        },
        {
            "step": 5,
            "name": "reconcile_counts",
            "status": "deferred",
            "notes": "Compare jpintel invoice count, kind distribution, load log rows_after, and autonomath mirror count.",
        },
        {
            "step": 6,
            "name": "privacy_release_gate",
            "status": "deferred",
            "notes": "Confirm attribution, edit notice, takedown path, aggregate reporting, and no public dump.",
        },
    ]


def _blocker(
    code: str,
    message: str,
    *,
    severity: str = "blocker",
    fail_closed: bool = True,
) -> dict[str, Any]:
    return {
        "code": code,
        "severity": severity,
        "message": message,
        "fail_closed": fail_closed,
    }


def _build_blockers(
    *,
    jpintel: dict[str, Any],
    autonomath: dict[str, Any],
    workflow: dict[str, Any],
    local_log: dict[str, Any],
    disk: dict[str, Any],
) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    if not jpintel.get("exists"):
        blockers.append(_blocker("jpintel_db:missing", f"missing DB: {jpintel['path']}"))
    elif not jpintel.get("table_exists"):
        blockers.append(
            _blocker(
                "invoice_registrants:missing",
                "jpintel.db does not expose invoice_registrants",
            )
        )

    current = jpintel.get("counts", {}).get("invoice_registrants")
    if isinstance(current, int) and current < FULL_POPULATION_ESTIMATE:
        blockers.append(
            _blocker(
                "full_snapshot:not_acquired",
                (
                    f"current invoice_registrants count is {current}; "
                    f"target full-population estimate is {FULL_POPULATION_ESTIMATE}"
                ),
            )
        )
    if current is None and jpintel.get("exists"):
        blockers.append(
            _blocker("invoice_registrants:count_unavailable", "could not count invoice rows")
        )

    mirror = autonomath.get("counts", {}).get("jpi_invoice_registrants")
    if isinstance(current, int) and isinstance(mirror, int) and current != mirror:
        blockers.append(
            _blocker(
                "autonomath_mirror:count_mismatch",
                f"jpintel invoice count {current} differs from jpi mirror count {mirror}",
            )
        )
    if not workflow.get("exists"):
        blockers.append(_blocker("workflow:missing", f"missing workflow: {workflow['path']}"))
    elif not workflow.get("monthly_full_cron_wired"):
        blockers.append(
            _blocker(
                "workflow:monthly_full_not_wired",
                "local workflow does not wire the monthly full NTA invoice ingest",
            )
        )
    if not workflow.get("daily_delta_cron_wired"):
        blockers.append(
            _blocker(
                "workflow:daily_delta_not_scheduled",
                "daily delta mode is dispatch-capable but not scheduled in the local workflow",
                severity="followup",
                fail_closed=False,
            )
        )
    if not local_log.get("exists"):
        blockers.append(
            _blocker(
                "load_log:not_present_locally",
                "data/invoice_load_log.jsonl is not present locally; no completed full run log synced",
                severity="followup",
                fail_closed=False,
            )
        )
    if disk.get("local_ok_for_full_estimate") is False:
        blockers.append(
            _blocker(
                "local_disk:below_full_threshold",
                "local disk free space is below the full-load estimate threshold",
            )
        )
    blockers.append(
        _blocker(
            "privacy:takedown_path_required",
            "full B2 completion requires privacy/takedown readiness for sole-proprietor rows",
        )
    )
    blockers.append(
        _blocker(
            "operator:prod_preflight_required",
            "production disk/cache/log checks were not executed by this offline no-download report",
        )
    )
    return blockers


def _reconcile_summary(jpintel: dict[str, Any], autonomath: dict[str, Any]) -> dict[str, Any]:
    current = jpintel.get("counts", {}).get("invoice_registrants")
    mirror = autonomath.get("counts", {}).get("jpi_invoice_registrants")
    return {
        "jpintel_invoice_registrants": current,
        "autonomath_jpi_invoice_registrants": mirror,
        "autonomath_invoice_entities": autonomath.get("counts", {}).get(
            "am_entities_invoice_registrant"
        ),
        "count_match": (isinstance(current, int) and isinstance(mirror, int) and current == mirror),
        "mode": "aggregate_count_only_no_row_export",
        "post_load_policy": (
            "After full load, reconcile counts and kind distribution before any "
            "mirror expansion into autonomath.db."
        ),
    }


def build_report(
    *,
    jpintel_db: Path,
    autonomath_db: Path,
    workflow_path: Path,
    local_cache_dir: Path,
    prod_cache_dir: Path,
    local_load_log: Path,
    prod_load_log: Path,
    artifact_root: Path,
    report_date: str = REPORT_DATE,
) -> dict[str, Any]:
    jpintel = collect_jpintel_invoice_counts(jpintel_db)
    autonomath = collect_autonomath_invoice_counts(autonomath_db)
    workflow = _extract_workflow_status(workflow_path)
    local_cache = _cache_dir_report(local_cache_dir)
    prod_cache = _cache_dir_report(prod_cache_dir)
    local_log = _load_log_report(local_load_log)
    prod_log = _load_log_report(prod_load_log)
    disk = _disk_report(jpintel_db)
    commands = _command_strings(
        jpintel_db=jpintel_db,
        autonomath_db=autonomath_db,
        local_cache_dir=local_cache_dir,
        prod_cache_dir=prod_cache_dir,
        prod_load_log=prod_load_log,
    )
    blockers = _build_blockers(
        jpintel=jpintel,
        autonomath=autonomath,
        workflow=workflow,
        local_log=local_log,
        disk=disk,
    )
    command_count = sum(len(group) for group in commands.values())
    current = jpintel.get("counts", {}).get("invoice_registrants")
    remaining = max(FULL_POPULATION_ESTIMATE - current, 0) if isinstance(current, int) else None
    return {
        "ok": False,
        "generated_at": _utc_now(),
        "report_date": report_date,
        "scope": "B2 NTA invoice bulk acquisition/reconcile plan; no downloads/no DB mutations",
        "completion_status": {
            "B2": "plan_only",
            "complete": False,
            "reason": "acquisition and reconcile commands are deferred strings only",
        },
        "read_mode": {
            "sqlite_mode_ro": True,
            "workflow_text_only": True,
            "cache_metadata_only": True,
            "network_fetch_performed": False,
            "download_performed": False,
            "db_mutation_performed": False,
            "commands_are_strings_only": True,
        },
        "current_invoice_registrant_count": current,
        "target_full_population_estimate": FULL_POPULATION_ESTIMATE,
        "remaining_rows_estimate": remaining,
        "local_counts": {
            "jpintel": jpintel,
            "autonomath": autonomath,
        },
        "reconcile": _reconcile_summary(jpintel, autonomath),
        "expected_artifacts": _expected_artifacts(
            jpintel_db=jpintel_db,
            autonomath_db=autonomath_db,
            artifact_root=artifact_root,
            local_cache_dir=local_cache_dir,
            prod_cache_dir=prod_cache_dir,
            local_load_log=local_load_log,
            prod_load_log=prod_load_log,
        ),
        "artifact_status": {
            "local_cache": local_cache,
            "prod_cache_local_mount_view": prod_cache,
            "local_load_log": local_log,
            "prod_load_log_local_mount_view": prod_log,
        },
        "workflow_cron_status": workflow,
        "disk": disk,
        "privacy_aggregation_constraints": _privacy_and_aggregation_constraints(),
        "plan_steps": _plan_steps(),
        "commands": commands,
        "blockers": blockers,
        "report_counts": {
            "blocker_count": len(blockers),
            "fail_closed_blocker_count": sum(1 for row in blockers if row["fail_closed"]),
            "command_count": command_count,
            "privacy_constraint_count": len(_privacy_and_aggregation_constraints()),
        },
    }


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Offline B2 NTA invoice bulk acquisition/reconcile plan.",
    )
    parser.add_argument("--jpintel-db", type=Path, default=DEFAULT_JPINTEL_DB)
    parser.add_argument("--autonomath-db", type=Path, default=DEFAULT_AUTONOMATH_DB)
    parser.add_argument("--workflow", type=Path, default=DEFAULT_WORKFLOW)
    parser.add_argument("--local-cache-dir", type=Path, default=DEFAULT_LOCAL_CACHE_DIR)
    parser.add_argument("--prod-cache-dir", type=Path, default=DEFAULT_PROD_CACHE_DIR)
    parser.add_argument("--local-load-log", type=Path, default=DEFAULT_LOCAL_LOAD_LOG)
    parser.add_argument("--prod-load-log", type=Path, default=DEFAULT_PROD_LOAD_LOG)
    parser.add_argument("--artifact-root", type=Path, default=DEFAULT_ARTIFACT_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report-date", default=REPORT_DATE)
    parser.add_argument(
        "--no-write",
        action="store_true",
        help="print JSON only; do not write the --output file",
    )
    parser.add_argument(
        "--fail-on-blockers",
        action="store_true",
        help="return 1 when fail-closed blockers are present",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    report = build_report(
        jpintel_db=args.jpintel_db,
        autonomath_db=args.autonomath_db,
        workflow_path=args.workflow,
        local_cache_dir=args.local_cache_dir,
        prod_cache_dir=args.prod_cache_dir,
        local_load_log=args.local_load_log,
        prod_load_log=args.prod_load_log,
        artifact_root=args.artifact_root,
        report_date=args.report_date,
    )
    payload = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    print(payload)
    if not args.no_write:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")
    if args.fail_on_blockers and report["report_counts"]["fail_closed_blocker_count"]:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
