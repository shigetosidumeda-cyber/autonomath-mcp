#!/usr/bin/env python3
"""Generate an offline B1/B3 official bulk-source acquisition runbook.

This report intentionally performs no network access, no downloads, and no
ingest work. It reads local preflight output when present, opens local SQLite
databases read-only for current counts, and emits operator commands only as
strings for a later manual run.
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
DEFAULT_PREFLIGHT = REPO_ROOT / "analysis_wave18" / "corporate_bulk_preflight_2026-05-01.json"
DEFAULT_OUTPUT = REPO_ROOT / "analysis_wave18" / "corporate_bulk_acquisition_plan_2026-05-01.json"
DEFAULT_GBIZ_JSONL = Path("/Users/shigetoumeda/Autonomath/data/runtime/gbiz_enrichment.jsonl")
DEFAULT_INVOICE_CACHE_DIR = Path("/tmp/jpintel_invoice_registrants_cache")
DEFAULT_ARTIFACT_ROOT = REPO_ROOT / "data" / "bulk"

REPORT_DATE = "2026-05-01"
MIN_FREE_BYTES_FULL = 2 * 1024 * 1024 * 1024
INVOICE_FULL_TARGET_ROWS_ESTIMATE = 4_000_000


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _qident(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _readonly_connect(path: Path) -> sqlite3.Connection:
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


def _count_grouped(
    conn: sqlite3.Connection,
    table: str,
    column: str,
    *,
    limit: int = 20,
) -> dict[str, int]:
    if column not in _column_names(conn, table):
        return {}
    rows = conn.execute(
        f"""
        SELECT COALESCE(CAST({_qident(column)} AS TEXT), '') AS key, COUNT(*) AS c
          FROM {_qident(table)}
         GROUP BY COALESCE(CAST({_qident(column)} AS TEXT), '')
         ORDER BY c DESC, key ASC
         LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return {str(row["key"]): int(row["c"] or 0) for row in rows}


def _db_report(path: Path, counts: dict[str, Any]) -> dict[str, Any]:
    return {
        "path": str(path),
        "exists": path.exists(),
        "size_bytes": path.stat().st_size if path.exists() else 0,
        "counts": counts,
    }


def collect_jpintel_counts(path: Path) -> dict[str, Any]:
    if not path.exists():
        return _db_report(path, {})
    with _readonly_connect(path) as conn:
        houjin_columns = _column_names(conn, "houjin_master")
        invoice_columns = _column_names(conn, "invoice_registrants")
        counts: dict[str, Any] = {
            "houjin_master": _count_rows(conn, "houjin_master"),
            "invoice_registrants": _count_rows(conn, "invoice_registrants"),
        }
        if "last_updated_nta" in houjin_columns:
            counts["houjin_master_with_last_updated_nta"] = _count_rows(
                conn,
                "houjin_master",
                "last_updated_nta IS NOT NULL AND TRIM(last_updated_nta) != ''",
            )
        if "last_updated_nta" in invoice_columns:
            counts["invoice_registrants_with_last_updated_nta"] = _count_rows(
                conn,
                "invoice_registrants",
                "last_updated_nta IS NOT NULL AND TRIM(last_updated_nta) != ''",
            )
        if "houjin_bangou" in invoice_columns:
            counts["invoice_registrants_with_houjin_bangou"] = _count_rows(
                conn,
                "invoice_registrants",
                "houjin_bangou IS NOT NULL AND TRIM(houjin_bangou) != ''",
            )
        counts["invoice_registrants_by_kind"] = _count_grouped(
            conn,
            "invoice_registrants",
            "registrant_kind",
        )
    return _db_report(path, counts)


def collect_autonomath_counts(path: Path) -> dict[str, Any]:
    if not path.exists():
        return _db_report(path, {})
    with _readonly_connect(path) as conn:
        counts: dict[str, Any] = {
            "am_entities": _count_rows(conn, "am_entities"),
            "am_entity_facts": _count_rows(conn, "am_entity_facts"),
            "am_source": _count_rows(conn, "am_source"),
        }
        if "record_kind" in _column_names(conn, "am_entities"):
            counts["corporate_entities"] = _count_rows(
                conn,
                "am_entities",
                "record_kind = 'corporate_entity'",
            )
        fact_columns = _column_names(conn, "am_entity_facts")
        if "field_name" in fact_columns:
            counts["gbiz_fact_rows"] = _count_rows(
                conn,
                "am_entity_facts",
                "field_name LIKE 'corp.gbiz_%'",
            )
            counts["houjin_bangou_fact_rows"] = _count_rows(
                conn,
                "am_entity_facts",
                "field_name = 'houjin_bangou'",
            )
    return _db_report(path, counts)


def _load_preflight(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return {
            "ok": False,
            "issues": [f"preflight_json:decode_error:{exc.msg}"],
            "error": str(exc),
        }


def _disk_report(path: Path, preflight: dict[str, Any] | None) -> dict[str, Any]:
    if preflight and isinstance(preflight.get("disk"), dict):
        return dict(preflight["disk"])
    target = path if path.exists() else path.parent
    while not target.exists() and target != target.parent:
        target = target.parent
    usage = shutil.disk_usage(target)
    return {
        "path": str(target),
        "free_bytes": usage.free,
        "total_bytes": usage.total,
        "required_free_bytes": MIN_FREE_BYTES_FULL,
        "ok": usage.free >= MIN_FREE_BYTES_FULL,
    }


def _preflight_artifact_path(
    preflight: dict[str, Any] | None,
    artifact: str,
    default: Path,
) -> Path:
    if preflight:
        artifacts = preflight.get("artifacts")
        if isinstance(artifacts, dict):
            entry = artifacts.get(artifact)
            if isinstance(entry, dict) and entry.get("path"):
                return Path(str(entry["path"]))
    return default


def _rel(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _command_strings(
    *,
    jpintel_db: Path,
    autonomath_db: Path,
    gbiz_jsonl: Path,
    invoice_cache_dir: Path,
    artifact_root: Path,
) -> dict[str, list[str]]:
    houjin_dir = artifact_root / "nta_houjin" / "zenken" / "${YYYYMMDD}"
    gbiz_dir = artifact_root / "gbizinfo"
    invoice_dir = artifact_root / "nta_invoice" / "zenken" / "${YYYYMMDD}"
    return {
        "b1_nta_houjin_acquisition": [
            f"mkdir -p {_rel(houjin_dir)}",
            (
                "curl -fL 'https://www.houjin-bangou.nta.go.jp/download/' "
                f"-o '{_rel(artifact_root / 'nta_houjin' / 'download_index_${YYYYMMDD}.html')}'"
            ),
            (
                "# after operator selects the official full-snapshot file from the index: "
                f"curl -fL '<official-houjin-zenken-url>' -o '{_rel(houjin_dir / 'houjin_zenken.zip')}'"
            ),
            f"sqlite3 '{_rel(jpintel_db)}' \"SELECT COUNT(*) FROM houjin_master;\"",
        ],
        "b1_gbizinfo_acquisition": [
            f"mkdir -p {_rel(gbiz_dir)}",
            (
                "curl -fL 'https://info.gbiz.go.jp/' "
                f"-o '{_rel(gbiz_dir / 'gbizinfo_source_landing_${YYYYMMDD}.html')}'"
            ),
            (
                f"python scripts/ingest_gbiz_facts.py --db '{_rel(autonomath_db)}' "
                f"--source '{gbiz_jsonl}' --dry-run --limit 1000"
            ),
            (
                f"python scripts/ingest_gbiz_facts.py --db '{_rel(autonomath_db)}' "
                f"--source '{gbiz_jsonl}' --batch-size 5000"
            ),
        ],
        "b3_invoice_acquisition": [
            f"mkdir -p '{invoice_cache_dir}' '{_rel(invoice_dir)}'",
            (
                "curl -fL 'https://www.invoice-kohyo.nta.go.jp/download/zenken' "
                f"-o '{_rel(artifact_root / 'nta_invoice' / 'zenken_index_${YYYYMMDD}.html')}'"
            ),
            (
                "python scripts/cron/ingest_nta_invoice_bulk.py "
                f"--db '{_rel(jpintel_db)}' --mode full --format csv --dry-run "
                f"--limit 100000 --cache-dir '{invoice_cache_dir}'"
            ),
            (
                "python scripts/cron/ingest_nta_invoice_bulk.py "
                f"--db '{_rel(jpintel_db)}' --mode full --format csv "
                f"--batch-size 10000 --cache-dir '{invoice_cache_dir}'"
            ),
            (f"sqlite3 '{_rel(jpintel_db)}' \"SELECT COUNT(*) FROM invoice_registrants;\""),
        ],
    }


def _source_plans(
    *,
    jpintel_db: Path,
    autonomath_db: Path,
    gbiz_jsonl: Path,
    invoice_cache_dir: Path,
    artifact_root: Path,
    local_counts: dict[str, Any],
    disk: dict[str, Any],
) -> list[dict[str, Any]]:
    invoice_rows = local_counts.get("jpintel", {}).get("counts", {}).get("invoice_registrants")
    invoice_remaining = None
    if isinstance(invoice_rows, int):
        invoice_remaining = max(INVOICE_FULL_TARGET_ROWS_ESTIMATE - invoice_rows, 0)

    return [
        {
            "source_id": "B1_NTA_HOUJIN",
            "buckets": ["B1"],
            "title": "NTA corporate number master full snapshot",
            "official": True,
            "source_urls": [
                "https://www.houjin-bangou.nta.go.jp/",
                "https://www.houjin-bangou.nta.go.jp/download/",
            ],
            "source_domains": ["www.houjin-bangou.nta.go.jp"],
            "expected_local_artifacts": {
                "raw_root": str(artifact_root / "nta_houjin"),
                "full_snapshot_dir_template": str(
                    artifact_root / "nta_houjin" / "zenken" / "${YYYYMMDD}"
                ),
                "local_table": f"{jpintel_db}:houjin_master",
            },
            "license_assumption": {
                "label": "public_data_use_terms_assumed",
                "basis": "local schema and docs identify NTA corporate-number data as official public data",
                "attribution_required": True,
                "review_required": True,
                "review_reason": "latest source-page terms were not re-verified by this offline generator",
            },
            "disk_estimate": {
                "status": "not_inferable_from_local_state",
                "current_rows": local_counts.get("jpintel", {})
                .get("counts", {})
                .get("houjin_master"),
            },
        },
        {
            "source_id": "B1_GBIZINFO",
            "buckets": ["B1"],
            "title": "METI gBizINFO corporate enrichment snapshot",
            "official": True,
            "source_urls": [
                "https://info.gbiz.go.jp/",
                "https://content.info.gbiz.go.jp/api/index.html",
            ],
            "source_domains": ["info.gbiz.go.jp", "content.info.gbiz.go.jp"],
            "expected_local_artifacts": {
                "jsonl_snapshot": str(gbiz_jsonl),
                "raw_root": str(artifact_root / "gbizinfo"),
                "local_tables": [
                    f"{autonomath_db}:am_entities",
                    f"{autonomath_db}:am_entity_facts",
                    f"{autonomath_db}:am_source",
                ],
            },
            "license_assumption": {
                "label": "cc_by_4_0_compatible_assumed",
                "basis": "local compliance docs and ingest script label gBizINFO as CC-BY-4.0-compatible",
                "attribution_required": True,
                "review_required": True,
                "review_reason": "local docs mention recent gBizINFO terms changes; operator must confirm current terms",
            },
            "disk_estimate": {
                "status": "infer_from_existing_jsonl_if_present",
                "jsonl_size_bytes": gbiz_jsonl.stat().st_size if gbiz_jsonl.is_file() else None,
                "current_corporate_entities": local_counts.get("autonomath", {})
                .get("counts", {})
                .get("corporate_entities"),
                "current_gbiz_fact_rows": local_counts.get("autonomath", {})
                .get("counts", {})
                .get("gbiz_fact_rows"),
            },
        },
        {
            "source_id": "B3_NTA_INVOICE",
            "buckets": ["B3"],
            "title": "NTA qualified invoice issuer full snapshot",
            "official": True,
            "source_urls": [
                "https://www.invoice-kohyo.nta.go.jp/",
                "https://www.invoice-kohyo.nta.go.jp/download/",
                "https://www.invoice-kohyo.nta.go.jp/download/zenken",
                "https://www.invoice-kohyo.nta.go.jp/download/sabun",
            ],
            "source_domains": ["www.invoice-kohyo.nta.go.jp"],
            "delivery_url_shape": (
                "https://www.invoice-kohyo.nta.go.jp/download/{zenken|sabun}/"
                "dlfile?dlFilKanriNo=<opaque>&type=<01|02|03>"
            ),
            "expected_local_artifacts": {
                "cache_dir": str(invoice_cache_dir),
                "cache_file_template": str(invoice_cache_dir / "nta_<dlFilKanriNo>_csv.zip"),
                "raw_root": str(artifact_root / "nta_invoice"),
                "full_snapshot_dir_template": str(
                    artifact_root / "nta_invoice" / "zenken" / "${YYYYMMDD}"
                ),
                "local_table": f"{jpintel_db}:invoice_registrants",
                "load_log": str(REPO_ROOT / "data" / "invoice_load_log.jsonl"),
            },
            "license_assumption": {
                "label": "pdl_v1_0",
                "basis": "local migration and ingest docs pin NTA invoice bulk to PDL v1.0",
                "attribution_required": True,
                "edit_notice_required": True,
                "review_required": False,
            },
            "privacy_review": {
                "review_required": True,
                "review_reason": "full B3 snapshot includes sole-proprietor rows; takedown/privacy path must be ready",
            },
            "disk_estimate": {
                "status": "inferred_from_local_runbook_and_current_counts",
                "current_rows": invoice_rows,
                "target_rows_estimate": INVOICE_FULL_TARGET_ROWS_ESTIMATE,
                "remaining_rows_estimate": invoice_remaining,
                "compressed_source_bytes_estimate": 500_000_000,
                "uncompressed_csv_bytes_estimate": 2_000_000_000,
                "sqlite_growth_bytes_estimate_range": [900_000_000, 1_400_000_000],
                "minimum_free_bytes_required": disk.get("required_free_bytes", MIN_FREE_BYTES_FULL),
                "current_free_bytes": disk.get("free_bytes"),
            },
        },
    ]


def _blocker(
    code: str,
    message: str,
    *,
    source_id: str | None = None,
    severity: str = "blocker",
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "code": code,
        "severity": severity,
        "message": message,
        "fail_closed": True,
    }
    if source_id:
        row["source_id"] = source_id
    return row


def _build_blockers(
    *,
    preflight_path: Path,
    preflight: dict[str, Any] | None,
    jpintel: dict[str, Any],
    autonomath: dict[str, Any],
    sources: list[dict[str, Any]],
    disk: dict[str, Any],
) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    if preflight is None:
        blockers.append(
            _blocker(
                "preflight:missing",
                f"local preflight report not found: {preflight_path}",
            )
        )
    else:
        for issue in preflight.get("issues", []):
            blockers.append(
                _blocker(
                    f"preflight:{issue}",
                    f"preflight issue must be cleared before acquisition: {issue}",
                )
            )
        if preflight.get("ok") is False and not preflight.get("issues"):
            blockers.append(
                _blocker(
                    "preflight:not_ok",
                    "preflight report is not ok but did not include issue details",
                )
            )

    if not jpintel.get("exists"):
        blockers.append(_blocker("jpintel_db:missing", f"missing DB: {jpintel['path']}"))
    if not autonomath.get("exists"):
        blockers.append(_blocker("autonomath_db:missing", f"missing DB: {autonomath['path']}"))

    if disk.get("ok") is False:
        blockers.append(
            _blocker(
                "disk:free_bytes_below_threshold",
                "available disk is below the full bulk acquisition threshold",
            )
        )

    for source in sources:
        license_assumption = source.get("license_assumption", {})
        if license_assumption.get("review_required"):
            blockers.append(
                _blocker(
                    f"license_review:{source['source_id']}",
                    str(license_assumption.get("review_reason") or "license review required"),
                    source_id=str(source["source_id"]),
                )
            )
        privacy_review = source.get("privacy_review", {})
        if privacy_review.get("review_required"):
            blockers.append(
                _blocker(
                    f"privacy_review:{source['source_id']}",
                    str(privacy_review.get("review_reason") or "privacy review required"),
                    source_id=str(source["source_id"]),
                )
            )
    return blockers


def _preflight_summary(preflight_path: Path, preflight: dict[str, Any] | None) -> dict[str, Any]:
    if preflight is None:
        return {"path": str(preflight_path), "present": False}
    return {
        "path": str(preflight_path),
        "present": True,
        "ok": preflight.get("ok"),
        "generated_at": preflight.get("generated_at"),
        "issues": list(preflight.get("issues", [])),
    }


def build_report(
    *,
    jpintel_db: Path,
    autonomath_db: Path,
    preflight_path: Path,
    gbiz_jsonl: Path,
    invoice_cache_dir: Path,
    artifact_root: Path,
) -> dict[str, Any]:
    preflight = _load_preflight(preflight_path)
    gbiz_jsonl = _preflight_artifact_path(preflight, "gbiz_jsonl", gbiz_jsonl)
    invoice_cache_dir = _preflight_artifact_path(preflight, "invoice_cache", invoice_cache_dir)
    local_counts = {
        "jpintel": collect_jpintel_counts(jpintel_db),
        "autonomath": collect_autonomath_counts(autonomath_db),
    }
    disk = _disk_report(jpintel_db, preflight)
    commands = _command_strings(
        jpintel_db=jpintel_db,
        autonomath_db=autonomath_db,
        gbiz_jsonl=gbiz_jsonl,
        invoice_cache_dir=invoice_cache_dir,
        artifact_root=artifact_root,
    )
    sources = _source_plans(
        jpintel_db=jpintel_db,
        autonomath_db=autonomath_db,
        gbiz_jsonl=gbiz_jsonl,
        invoice_cache_dir=invoice_cache_dir,
        artifact_root=artifact_root,
        local_counts=local_counts,
        disk=disk,
    )
    blockers = _build_blockers(
        preflight_path=preflight_path,
        preflight=preflight,
        jpintel=local_counts["jpintel"],
        autonomath=local_counts["autonomath"],
        sources=sources,
        disk=disk,
    )
    command_count = sum(len(group) for group in commands.values())
    review_required_count = sum(
        1
        for source in sources
        if source.get("license_assumption", {}).get("review_required")
        or source.get("privacy_review", {}).get("review_required")
    )
    return {
        "ok": not blockers,
        "generated_at": _utc_now(),
        "report_date": REPORT_DATE,
        "scope": (
            "B1/B3 official bulk source acquisition runbook generator; "
            "offline/no network/no downloads/no ingest"
        ),
        "read_mode": {
            "sqlite_only": True,
            "preflight_json_only": True,
            "network_fetch_performed": False,
            "download_performed": False,
            "ingest_performed": False,
            "commands_are_strings_only": True,
        },
        "completion_status": {
            "B1": "acquisition_plan_only",
            "B3": "acquisition_plan_only",
            "complete": False,
        },
        "inputs": {
            "jpintel_db": str(jpintel_db),
            "autonomath_db": str(autonomath_db),
            "preflight": str(preflight_path),
            "gbiz_jsonl": str(gbiz_jsonl),
            "invoice_cache_dir": str(invoice_cache_dir),
            "artifact_root": str(artifact_root),
        },
        "preflight": _preflight_summary(preflight_path, preflight),
        "local_counts": local_counts,
        "disk": disk,
        "sources": sources,
        "commands": commands,
        "blockers": blockers,
        "report_counts": {
            "source_count": len(sources),
            "blocker_count": len(blockers),
            "command_count": command_count,
            "review_required_source_count": review_required_count,
        },
    }


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Offline B1/B3 official bulk-source acquisition runbook generator.",
    )
    parser.add_argument("--jpintel-db", type=Path, default=DEFAULT_JPINTEL_DB)
    parser.add_argument("--autonomath-db", type=Path, default=DEFAULT_AUTONOMATH_DB)
    parser.add_argument("--preflight", type=Path, default=DEFAULT_PREFLIGHT)
    parser.add_argument("--gbiz-jsonl", type=Path, default=DEFAULT_GBIZ_JSONL)
    parser.add_argument("--invoice-cache-dir", type=Path, default=DEFAULT_INVOICE_CACHE_DIR)
    parser.add_argument("--artifact-root", type=Path, default=DEFAULT_ARTIFACT_ROOT)
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
        preflight_path=args.preflight,
        gbiz_jsonl=args.gbiz_jsonl,
        invoice_cache_dir=args.invoice_cache_dir,
        artifact_root=args.artifact_root,
    )
    payload = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    print(payload)
    if not args.no_write:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
