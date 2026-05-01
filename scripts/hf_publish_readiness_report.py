#!/usr/bin/env python3
"""Build a local Hugging Face publish-readiness manifest.

This script is intentionally offline. It reads only the generated safe export
manifests and parquet file metadata under:

  - dist/hf-laws-jp
  - dist/hf-statistics-estat
  - dist/hf-aggregates-safe

It does not read source databases, contact Hugging Face, publish, push, upload,
or call external APIs.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DIST_ROOT = REPO_ROOT / "dist"
DEFAULT_OUTPUT = REPO_ROOT / "analysis_wave18" / "hf_publish_readiness_2026-05-01.json"
SCHEMA_VERSION = "hf_publish_readiness_report.v1"

SAFE_EXPORT_DIRS = {
    "laws-jp": "hf-laws-jp",
    "statistics-estat": "hf-statistics-estat",
    "safe-aggregates": "hf-aggregates-safe",
}

LEGACY_UNSAFE_DIR = "hf-dataset"


@dataclass(frozen=True)
class FileCheck:
    path: str
    rows: int
    manifest_bytes: int | None
    actual_bytes: int | None
    licenses: list[str]
    blockers: list[str]


def _rel(path: Path, base: Path) -> str:
    try:
        return path.relative_to(base).as_posix()
    except ValueError:
        return path.as_posix()


def _load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as fh:
        value = json.load(fh)
    if not isinstance(value, dict):
        raise ValueError(f"expected object JSON at {path}")
    return value


def _as_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _unique(values: list[str]) -> list[str]:
    return sorted({value for value in values if value})


def _licenses_from_export(export: dict[str, Any], manifest: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for key in ("license", "licenses"):
        raw = export.get(key)
        if isinstance(raw, str):
            values.append(raw)
        elif isinstance(raw, list):
            values.extend(str(item) for item in raw if item)

    raw_values = export.get("license_values")
    if isinstance(raw_values, list):
        values.extend(str(item) for item in raw_values if item)

    raw_counts = export.get("license_counts")
    if isinstance(raw_counts, dict):
        values.extend(str(item) for item in raw_counts)

    for key in ("license_values", "license_counts"):
        raw = manifest.get(key)
        if isinstance(raw, list):
            values.extend(str(item) for item in raw if item)
        elif isinstance(raw, dict):
            values.extend(str(item) for item in raw)

    return _unique(values)


def _check_file(
    *,
    export_dir: Path,
    repo_root: Path,
    file_name: str,
    rows: int,
    manifest_bytes: int | None,
    licenses: list[str],
) -> FileCheck:
    path = export_dir / file_name
    blockers: list[str] = []
    actual_bytes: int | None = None
    if not path.exists():
        blockers.append(f"missing parquet file: {_rel(path, repo_root)}")
    elif not path.is_file():
        blockers.append(f"parquet path is not a file: {_rel(path, repo_root)}")
    else:
        actual_bytes = path.stat().st_size
        if actual_bytes <= 0:
            blockers.append(f"parquet file is empty: {_rel(path, repo_root)}")
        if manifest_bytes is not None and actual_bytes != manifest_bytes:
            blockers.append(
                "manifest byte count does not match parquet file size: "
                f"{manifest_bytes} != {actual_bytes}"
            )

    if rows < 0:
        blockers.append(f"negative row count in manifest for {file_name}")
    if not licenses:
        blockers.append(f"missing license metadata in manifest for {file_name}")

    return FileCheck(
        path=_rel(path, repo_root),
        rows=rows,
        manifest_bytes=manifest_bytes,
        actual_bytes=actual_bytes,
        licenses=licenses,
        blockers=blockers,
    )


def _publish_command(repo_id: str, export_dir: str, dataset: str, report_date: str) -> str:
    return (
        f'.venv/bin/huggingface-cli upload {repo_id} {export_dir}/ . '
        f'--repo-type dataset --commit-message "Publish {dataset} safe export {report_date}"'
    )


def _next_action(
    *,
    dataset: str,
    export_dir: str,
    blockers: list[str],
    report_date: str,
) -> str:
    if blockers:
        return (
            "Do not publish. Resolve the blockers, regenerate the local safe export, "
            "then rerun scripts/hf_publish_readiness_report.py."
        )

    repo_slug = dataset.replace("_", "-")
    repo_id = f"bookyou/{repo_slug}"
    command = _publish_command(repo_id, export_dir, dataset, report_date)
    return (
        "Operator only after HF write-token authentication: run "
        f"`{command}`. Do not upload dist/hf-dataset."
    )


def _dataset_entry(
    *,
    dataset: str,
    export_dir: Path,
    manifest_path: Path,
    manifest: dict[str, Any],
    files: list[FileCheck],
    safety_gate_status: str,
    repo_root: Path,
    report_date: str,
    extra_blockers: list[str] | None = None,
) -> dict[str, Any]:
    blockers = list(extra_blockers or [])
    for file_check in files:
        blockers.extend(file_check.blockers)

    row_count = sum(file_check.rows for file_check in files)
    actual_bytes_values = [file_check.actual_bytes for file_check in files]
    if all(value is not None for value in actual_bytes_values):
        byte_count = sum(int(value) for value in actual_bytes_values)
    else:
        byte_count = None
    licenses = _unique([license_ for file_check in files for license_ in file_check.licenses])
    if safety_gate_status != "passed":
        blockers.append(f"safety gate status is {safety_gate_status!r}")

    export_dir_rel = _rel(export_dir, repo_root)
    return {
        "dataset": dataset,
        "export_dir": export_dir_rel,
        "manifest_path": _rel(manifest_path, repo_root),
        "manifest_generated_at": manifest.get("generated_at"),
        "row_count": row_count,
        "bytes": byte_count,
        "licenses": licenses,
        "safety_gate_status": safety_gate_status,
        "publish_performed": False,
        "blockers": blockers,
        "operator_next_action": _next_action(
            dataset=dataset,
            export_dir=export_dir_rel,
            blockers=blockers,
            report_date=report_date,
        ),
        "files": [
            {
                "path": file_check.path,
                "rows": file_check.rows,
                "manifest_bytes": file_check.manifest_bytes,
                "actual_bytes": file_check.actual_bytes,
                "licenses": file_check.licenses,
                "blockers": file_check.blockers,
            }
            for file_check in files
        ],
    }


def _missing_entry(
    *,
    dataset: str,
    export_dir: Path,
    repo_root: Path,
    report_date: str,
) -> dict[str, Any]:
    blockers = [f"missing safe export manifest: {_rel(export_dir / 'manifest.json', repo_root)}"]
    return {
        "dataset": dataset,
        "export_dir": _rel(export_dir, repo_root),
        "manifest_path": _rel(export_dir / "manifest.json", repo_root),
        "manifest_generated_at": None,
        "row_count": 0,
        "bytes": None,
        "licenses": [],
        "safety_gate_status": "missing",
        "publish_performed": False,
        "blockers": blockers,
        "operator_next_action": _next_action(
            dataset=dataset,
            export_dir=_rel(export_dir, repo_root),
            blockers=blockers,
            report_date=report_date,
        ),
        "files": [],
    }


def _read_laws_export(dist_root: Path, repo_root: Path, report_date: str) -> dict[str, Any]:
    export_dir = dist_root / SAFE_EXPORT_DIRS["laws-jp"]
    manifest_path = export_dir / "manifest.json"
    if not manifest_path.exists():
        return _missing_entry(
            dataset="laws-jp",
            export_dir=export_dir,
            repo_root=repo_root,
            report_date=report_date,
        )

    manifest = _load_json(manifest_path)
    files: list[FileCheck] = []
    blockers: list[str] = []
    exports = manifest.get("exports")
    if not isinstance(exports, list) or not exports:
        blockers.append("manifest exports must be a nonempty list")
    else:
        for export in exports:
            if not isinstance(export, dict):
                blockers.append("manifest export entry is not an object")
                continue
            file_name = str(export.get("file") or "")
            rows = _as_int(export.get("rows"))
            if not file_name:
                blockers.append("manifest export entry missing file")
                continue
            if rows is None:
                blockers.append(f"manifest export {file_name} missing integer rows")
                rows = 0
            files.append(
                _check_file(
                    export_dir=export_dir,
                    repo_root=repo_root,
                    file_name=file_name,
                    rows=rows,
                    manifest_bytes=_as_int(export.get("bytes")),
                    licenses=_licenses_from_export(export, manifest),
                )
            )

    statuses = set()
    if isinstance(exports, list):
        statuses = {
            str(export.get("safety_gate"))
            for export in exports
            if isinstance(export, dict) and export.get("safety_gate")
        }
    safety_gate_status = "passed" if statuses == {"passed"} else "unknown"
    return _dataset_entry(
        dataset=str(manifest.get("dataset") or "laws-jp"),
        export_dir=export_dir,
        manifest_path=manifest_path,
        manifest=manifest,
        files=files,
        safety_gate_status=safety_gate_status,
        repo_root=repo_root,
        report_date=report_date,
        extra_blockers=blockers,
    )


def _read_estat_export(dist_root: Path, repo_root: Path, report_date: str) -> dict[str, Any]:
    export_dir = dist_root / SAFE_EXPORT_DIRS["statistics-estat"]
    manifest_path = export_dir / "manifest.json"
    if not manifest_path.exists():
        return _missing_entry(
            dataset="statistics-estat",
            export_dir=export_dir,
            repo_root=repo_root,
            report_date=report_date,
        )

    manifest = _load_json(manifest_path)
    files: list[FileCheck] = []
    blockers: list[str] = []
    exports = manifest.get("exports")
    if not isinstance(exports, list) or not exports:
        blockers.append("manifest exports must be a nonempty list")
    else:
        for export in exports:
            if not isinstance(export, dict):
                blockers.append("manifest export entry is not an object")
                continue
            file_name = str(export.get("file") or "")
            rows = _as_int(export.get("rows"))
            if not file_name:
                blockers.append("manifest export entry missing file")
                continue
            if rows is None:
                blockers.append(f"manifest export {file_name} missing integer rows")
                rows = 0
            files.append(
                _check_file(
                    export_dir=export_dir,
                    repo_root=repo_root,
                    file_name=file_name,
                    rows=rows,
                    manifest_bytes=_as_int(export.get("bytes")),
                    licenses=_licenses_from_export(export, manifest),
                )
            )

    if manifest.get("preview_only") is True:
        blockers.append("statistics-estat manifest is preview_only; full F3 readiness incomplete")
    if manifest.get("f3_full_publish_ready") is False:
        blockers.append("statistics-estat manifest says f3_full_publish_ready=false")
    if manifest.get("b9_provenance_complete") is False:
        blockers.append("statistics-estat manifest says b9_provenance_complete=false")

    safety_gate_status = str(manifest.get("safety_gate_status") or "unknown")
    return _dataset_entry(
        dataset=str(manifest.get("dataset") or "statistics-estat"),
        export_dir=export_dir,
        manifest_path=manifest_path,
        manifest=manifest,
        files=files,
        safety_gate_status=safety_gate_status,
        repo_root=repo_root,
        report_date=report_date,
        extra_blockers=blockers,
    )


def _aggregate_safety_status(manifest: dict[str, Any], dataset: dict[str, Any]) -> str:
    if manifest.get("aggregate_only") is not True:
        return "failed"
    if manifest.get("row_level_sensitive_data_exported") is not False:
        return "failed"
    min_k = _as_int(dataset.get("min_k"))
    min_cell = _as_int(dataset.get("min_exported_cell_count"))
    rows = _as_int(dataset.get("rows")) or 0
    if min_k is not None and min_cell is not None and min_cell < min_k:
        return "failed"
    if rows > 0 and min_k is not None and min_cell is None:
        return "unknown"
    return "passed"


def _read_aggregate_exports(dist_root: Path, repo_root: Path, report_date: str) -> list[dict[str, Any]]:
    export_dir = dist_root / SAFE_EXPORT_DIRS["safe-aggregates"]
    manifest_path = export_dir / "manifest.json"
    if not manifest_path.exists():
        return [
            _missing_entry(
                dataset="safe-aggregates",
                export_dir=export_dir,
                repo_root=repo_root,
                report_date=report_date,
            )
        ]

    manifest = _load_json(manifest_path)
    datasets = manifest.get("datasets")
    if not isinstance(datasets, list) or not datasets:
        blockers = ["aggregate manifest datasets must be a nonempty list"]
        return [
            _dataset_entry(
                dataset="safe-aggregates",
                export_dir=export_dir,
                manifest_path=manifest_path,
                manifest=manifest,
                files=[],
                safety_gate_status="unknown",
                repo_root=repo_root,
                report_date=report_date,
                extra_blockers=blockers,
            )
        ]

    entries: list[dict[str, Any]] = []
    for dataset in datasets:
        if not isinstance(dataset, dict):
            entries.append(
                _dataset_entry(
                    dataset="safe-aggregates",
                    export_dir=export_dir,
                    manifest_path=manifest_path,
                    manifest=manifest,
                    files=[],
                    safety_gate_status="unknown",
                    repo_root=repo_root,
                    report_date=report_date,
                    extra_blockers=["aggregate dataset entry is not an object"],
                )
            )
            continue

        file_name = str(dataset.get("path") or "")
        rows = _as_int(dataset.get("rows"))
        blockers: list[str] = []
        if not file_name:
            blockers.append("aggregate dataset entry missing path")
        if rows is None:
            blockers.append("aggregate dataset entry missing integer rows")
            rows = 0
        if manifest.get("aggregate_only") is not True:
            blockers.append("aggregate manifest does not set aggregate_only=true")
        if manifest.get("row_level_sensitive_data_exported") is not False:
            blockers.append("aggregate manifest does not prove row_level_sensitive_data_exported=false")

        min_k = _as_int(dataset.get("min_k"))
        min_cell = _as_int(dataset.get("min_exported_cell_count"))
        if min_k is not None and min_cell is not None and min_cell < min_k:
            blockers.append(f"minimum exported cell count {min_cell} is below k={min_k}")

        files: list[FileCheck] = []
        if file_name:
            files.append(
                _check_file(
                    export_dir=export_dir,
                    repo_root=repo_root,
                    file_name=file_name,
                    rows=rows,
                    manifest_bytes=_as_int(dataset.get("bytes")),
                    licenses=_licenses_from_export(dataset, manifest),
                )
            )

        entries.append(
            _dataset_entry(
                dataset=str(dataset.get("dataset") or "safe-aggregates"),
                export_dir=export_dir,
                manifest_path=manifest_path,
                manifest=manifest,
                files=files,
                safety_gate_status=_aggregate_safety_status(manifest, dataset),
                repo_root=repo_root,
                report_date=report_date,
                extra_blockers=blockers,
            )
        )
    return entries


def _legacy_unsafe_entry(dist_root: Path, repo_root: Path) -> dict[str, Any] | None:
    legacy_dir = dist_root / LEGACY_UNSAFE_DIR
    if not legacy_dir.exists():
        return None
    blocker = (
        "dist/hf-dataset is a stale legacy export and is unsafe for publish: "
        "scripts/hf_dataset_export.py safety gate fails on the current DB."
    )
    return {
        "dataset": "legacy-hf-dataset",
        "export_dir": _rel(legacy_dir, repo_root),
        "manifest_path": None,
        "manifest_generated_at": None,
        "row_count": None,
        "bytes": None,
        "licenses": [],
        "safety_gate_status": "failed_current_db",
        "publish_performed": False,
        "blockers": [blocker],
        "operator_next_action": (
            "Do not publish or upload dist/hf-dataset. Ignore or remove it, and use only "
            "the safe export directories listed in datasets_ready_local."
        ),
        "files": [],
    }


def build_report(
    *,
    dist_root: Path = DEFAULT_DIST_ROOT,
    repo_root: Path = REPO_ROOT,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    generated_source = generated_at or datetime.now().astimezone()
    report_date = generated_source.astimezone().date().isoformat()
    generated = generated_source.astimezone(UTC).replace(microsecond=0)

    datasets = [
        _read_laws_export(dist_root, repo_root, report_date),
        _read_estat_export(dist_root, repo_root, report_date),
        *_read_aggregate_exports(dist_root, repo_root, report_date),
    ]
    unsafe_exports = []
    legacy = _legacy_unsafe_entry(dist_root, repo_root)
    if legacy is not None:
        unsafe_exports.append(legacy)

    ready = [dataset for dataset in datasets if not dataset["blockers"]]
    blocked = [dataset for dataset in datasets if dataset["blockers"]]
    total_rows = sum(int(dataset["row_count"] or 0) for dataset in ready)
    total_bytes = sum(int(dataset["bytes"] or 0) for dataset in ready)

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated.isoformat().replace("+00:00", "Z"),
        "publish_performed": False,
        "network_used": False,
        "source_scope": [
            _rel(dist_root / SAFE_EXPORT_DIRS["laws-jp"] / "manifest.json", repo_root),
            _rel(dist_root / SAFE_EXPORT_DIRS["statistics-estat"] / "manifest.json", repo_root),
            _rel(dist_root / SAFE_EXPORT_DIRS["safe-aggregates"] / "manifest.json", repo_root),
        ],
        "summary": {
            "safe_dataset_count": len(datasets),
            "datasets_ready_local_count": len(ready),
            "datasets_blocked_count": len(blocked),
            "unsafe_or_stale_export_count": len(unsafe_exports),
            "ready_local_rows": total_rows,
            "ready_local_bytes": total_bytes,
            "publish_performed": False,
        },
        "datasets_ready_local": ready,
        "datasets_blocked": blocked,
        "unsafe_or_stale_exports": unsafe_exports,
        "notes": [
            "This is local readiness only; no Hugging Face publish was performed.",
            "Only manifests and parquet file stats from the three safe export directories were read.",
            "dist/hf-dataset is explicitly unsafe/stale when present and must not be uploaded.",
        ],
    }


def write_report(report: dict[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist-root", type=Path, default=DEFAULT_DIST_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)

    try:
        report = build_report(dist_root=args.dist_root, repo_root=REPO_ROOT)
        write_report(report, args.output)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    summary = report["summary"]
    print(f"Wrote {args.output}")
    print(
        "Ready local datasets: "
        f"{summary['datasets_ready_local_count']}/{summary['safe_dataset_count']} "
        f"({summary['ready_local_rows']:,} rows, {summary['ready_local_bytes']:,} bytes)"
    )
    if report["unsafe_or_stale_exports"]:
        print("Unsafe/stale exports flagged: " f"{len(report['unsafe_or_stale_exports'])}")
    print("Publish performed: false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
