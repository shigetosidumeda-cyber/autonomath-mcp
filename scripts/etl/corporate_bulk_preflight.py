#!/usr/bin/env python3
"""Offline preflight audit for B1/B3 corporate bulk data.

This script intentionally performs no network access and no ingest work. It
checks local SQLite state, local bulk artifacts, cache presence, and disk space
before a corporate bulk load/reload is attempted elsewhere.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_JPINTEL_DB = REPO_ROOT / "data" / "jpintel.db"
DEFAULT_AUTONOMATH_DB = REPO_ROOT / "autonomath.db"
DEFAULT_GBIZ_JSONL = Path("/Users/shigetoumeda/Autonomath/data/runtime/gbiz_enrichment.jsonl")
DEFAULT_INVOICE_CACHE_DIR = Path("/tmp/jpintel_invoice_registrants_cache")
DEFAULT_OUTPUT = REPO_ROOT / "analysis_wave18" / "corporate_bulk_preflight_2026-05-01.json"

MIN_FREE_BYTES = 2 * 1024 * 1024 * 1024

JPINTEL_REQUIRED_TABLES = ("houjin_master", "invoice_registrants")
JPINTEL_REQUIRED_INDEXES = {
    "houjin_master": (
        "idx_houjin_name",
        "idx_houjin_prefecture",
        "idx_houjin_ctype",
        "idx_houjin_active",
    ),
    "invoice_registrants": (
        "idx_invoice_registrants_houjin",
        "idx_invoice_registrants_name",
        "idx_invoice_registrants_prefecture",
        "idx_invoice_registrants_registered",
        "idx_invoice_registrants_active",
        "idx_invoice_registrants_kind",
        "idx_invoice_registrants_houjin_registered",
        "idx_invoice_registrants_prefecture_registered",
        "idx_invoice_registrants_last_updated",
    ),
}
AUTONOMATH_REQUIRED_TABLES = ("am_entities", "am_entity_facts", "am_source")
AUTONOMATH_REQUIRED_INDEXES = {
    "am_entities": (
        "idx_am_entities_kind",
        "ix_am_entities_kind_fetched",
    ),
    "am_entity_facts": (
        "idx_am_facts_entity",
        "idx_am_facts_field",
        "idx_am_efacts_source",
    ),
    "am_source": ("idx_am_source_license",),
}


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _readonly_connect(path: Path) -> sqlite3.Connection:
    uri = path.resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('table', 'view') AND name = ?",
        (table,),
    ).fetchone()
    return row is not None


def _index_exists(conn: sqlite3.Connection, index: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'index' AND name = ?",
        (index,),
    ).fetchone()
    return row is not None


def _count_rows(conn: sqlite3.Connection, table: str) -> int | None:
    if not _table_exists(conn, table):
        return None
    return int(conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])


def _count_where(conn: sqlite3.Connection, table: str, where_sql: str) -> int | None:
    if not _table_exists(conn, table):
        return None
    return int(conn.execute(f'SELECT COUNT(*) FROM "{table}" WHERE {where_sql}').fetchone()[0])


def _required_presence(
    conn: sqlite3.Connection,
    required_tables: tuple[str, ...],
    required_indexes: dict[str, tuple[str, ...]],
) -> dict[str, Any]:
    tables = {table: _table_exists(conn, table) for table in required_tables}
    indexes: dict[str, dict[str, bool]] = {}
    for table, names in required_indexes.items():
        indexes[table] = {name: _index_exists(conn, name) for name in names}
    return {"tables": tables, "indexes": indexes}


def _missing_required(presence: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    for table, exists in presence["tables"].items():
        if not exists:
            missing.append(f"table:{table}")
    for table, indexes in presence["indexes"].items():
        for index, exists in indexes.items():
            if not exists:
                missing.append(f"index:{table}.{index}")
    return missing


def audit_jpintel_db(path: Path) -> dict[str, Any]:
    result: dict[str, Any] = {
        "path": str(path),
        "exists": path.exists(),
        "size_bytes": path.stat().st_size if path.exists() else 0,
    }
    if not path.exists():
        result["error"] = "database file not found"
        return result

    with _readonly_connect(path) as conn:
        presence = _required_presence(conn, JPINTEL_REQUIRED_TABLES, JPINTEL_REQUIRED_INDEXES)
        houjin_total = _count_rows(conn, "houjin_master")
        houjin_last_updated = _count_where(
            conn,
            "houjin_master",
            "last_updated_nta IS NOT NULL AND trim(last_updated_nta) != ''",
        )
        invoice_total = _count_rows(conn, "invoice_registrants")
        invoice_last_updated = _count_where(
            conn,
            "invoice_registrants",
            "last_updated_nta IS NOT NULL AND trim(last_updated_nta) != ''",
        )

    coverage = None
    if houjin_total:
        coverage = round((houjin_last_updated or 0) / houjin_total, 6)

    result.update(
        {
            "required": presence,
            "missing_required": _missing_required(presence),
            "counts": {
                "houjin_master": houjin_total,
                "invoice_registrants": invoice_total,
                "invoice_registrants_with_last_updated_nta": invoice_last_updated,
            },
            "houjin_master_last_updated_nta": {
                "present": houjin_last_updated,
                "total": houjin_total,
                "coverage": coverage,
            },
        }
    )
    return result


def audit_autonomath_db(path: Path) -> dict[str, Any]:
    result: dict[str, Any] = {
        "path": str(path),
        "exists": path.exists(),
        "size_bytes": path.stat().st_size if path.exists() else 0,
    }
    if not path.exists():
        result["error"] = "database file not found"
        return result

    with _readonly_connect(path) as conn:
        presence = _required_presence(
            conn,
            AUTONOMATH_REQUIRED_TABLES,
            AUTONOMATH_REQUIRED_INDEXES,
        )
        result.update(
            {
                "required": presence,
                "missing_required": _missing_required(presence),
                "counts": {
                    "am_entities": _count_rows(conn, "am_entities"),
                    "am_entity_facts": _count_rows(conn, "am_entity_facts"),
                    "am_source": _count_rows(conn, "am_source"),
                    "corporate_entities": _count_where(
                        conn,
                        "am_entities",
                        "record_kind = 'corporate_entity'",
                    ),
                    "gbiz_fact_rows": _count_where(
                        conn,
                        "am_entity_facts",
                        "field_name LIKE 'corp.gbiz_%'",
                    ),
                    "houjin_bangou_fact_rows": _count_where(
                        conn,
                        "am_entity_facts",
                        "field_name = 'houjin_bangou'",
                    ),
                },
            }
        )
    return result


def audit_file(path: Path) -> dict[str, Any]:
    return {
        "path": str(path),
        "exists": path.exists(),
        "is_file": path.is_file(),
        "size_bytes": path.stat().st_size if path.exists() and path.is_file() else 0,
    }


def audit_cache_dir(path: Path) -> dict[str, Any]:
    result: dict[str, Any] = {
        "path": str(path),
        "exists": path.exists(),
        "is_dir": path.is_dir(),
        "file_count": 0,
        "total_bytes": 0,
    }
    if not path.is_dir():
        return result
    for child in path.rglob("*"):
        if child.is_file():
            result["file_count"] += 1
            result["total_bytes"] += child.stat().st_size
    return result


def audit_disk(path: Path) -> dict[str, Any]:
    target = path if path.exists() else path.parent
    while not target.exists() and target != target.parent:
        target = target.parent
    usage = shutil.disk_usage(target)
    return {
        "path": str(target),
        "free_bytes": usage.free,
        "total_bytes": usage.total,
        "required_free_bytes": MIN_FREE_BYTES,
        "ok": usage.free >= MIN_FREE_BYTES,
    }


def build_report(
    *,
    jpintel_db: Path,
    autonomath_db: Path,
    gbiz_jsonl: Path,
    invoice_cache_dir: Path,
    disk_path: Path,
) -> dict[str, Any]:
    jpintel = audit_jpintel_db(jpintel_db)
    autonomath = audit_autonomath_db(autonomath_db)
    gbiz = audit_file(gbiz_jsonl)
    invoice_cache = audit_cache_dir(invoice_cache_dir)
    disk = audit_disk(disk_path)

    issues: list[str] = []
    for label, db_report in (("jpintel_db", jpintel), ("autonomath_db", autonomath)):
        if not db_report.get("exists"):
            issues.append(f"{label}:missing")
        issues.extend(f"{label}:{item}" for item in db_report.get("missing_required", []))
    if not gbiz["exists"] or not gbiz["is_file"]:
        issues.append("gbiz_jsonl:missing")
    if (
        not invoice_cache["exists"]
        or not invoice_cache["is_dir"]
        or invoice_cache["file_count"] == 0
    ):
        issues.append("invoice_cache:missing_or_empty")
    if not disk["ok"]:
        issues.append("disk:free_bytes_below_threshold")

    return {
        "ok": not issues,
        "generated_at": _utc_now(),
        "scope": "B1/B3 corporate bulk preflight audit only; offline/no network",
        "issues": issues,
        "databases": {
            "jpintel": jpintel,
            "autonomath": autonomath,
        },
        "artifacts": {
            "gbiz_jsonl": gbiz,
            "invoice_cache": invoice_cache,
        },
        "disk": disk,
    }


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Offline B1/B3 corporate bulk preflight audit.",
    )
    parser.add_argument("--jpintel-db", type=Path, default=DEFAULT_JPINTEL_DB)
    parser.add_argument("--autonomath-db", type=Path, default=DEFAULT_AUTONOMATH_DB)
    parser.add_argument("--gbiz-jsonl", type=Path, default=DEFAULT_GBIZ_JSONL)
    parser.add_argument("--invoice-cache-dir", type=Path, default=DEFAULT_INVOICE_CACHE_DIR)
    parser.add_argument("--disk-path", type=Path, default=DEFAULT_JPINTEL_DB)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--no-write",
        action="store_true",
        help="print JSON only; do not write the --output file",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    report = build_report(
        jpintel_db=args.jpintel_db,
        autonomath_db=args.autonomath_db,
        gbiz_jsonl=args.gbiz_jsonl,
        invoice_cache_dir=args.invoice_cache_dir,
        disk_path=args.disk_path,
    )
    payload = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    print(payload)
    if not args.no_write:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
