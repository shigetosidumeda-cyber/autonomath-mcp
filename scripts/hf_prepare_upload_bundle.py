#!/usr/bin/env python3
"""Prepare a local Hugging Face upload bundle manifest and checksums.

This script is intentionally offline. It reads only these local safe export
directories:

  - dist/hf-laws-jp
  - dist/hf-statistics-estat
  - dist/hf-aggregates-safe

It explicitly excludes dist/hf-dataset, writes local manifests/checksums, and
does not upload, publish, push, or call external APIs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DIST_ROOT = REPO_ROOT / "dist"
DEFAULT_BUNDLE_DIR = DEFAULT_DIST_ROOT / "hf-upload-bundle"
DEFAULT_ANALYSIS_OUTPUT = REPO_ROOT / "analysis_wave18" / "hf_upload_bundle_2026-05-01.json"
SCHEMA_VERSION = "hf_upload_bundle.v1"
DEFAULT_MAX_COPY_BYTES = 256 * 1024
SMALL_METADATA_NAMES = {"README.md", "manifest.json"}


@dataclass(frozen=True)
class SafeSource:
    dataset: str
    dir_name: str
    repo_id: str


SAFE_SOURCES: tuple[SafeSource, ...] = (
    SafeSource(dataset="laws-jp", dir_name="hf-laws-jp", repo_id="bookyou/laws-jp"),
    SafeSource(
        dataset="statistics-estat",
        dir_name="hf-statistics-estat",
        repo_id="bookyou/statistics-estat",
    ),
    SafeSource(
        dataset="safe-aggregates",
        dir_name="hf-aggregates-safe",
        repo_id="bookyou/safe-aggregates",
    ),
)

EXCLUDED_SOURCE_DIRS = ("hf-dataset",)


def _rel(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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


def _licenses_from_entry(entry: dict[str, Any], manifest: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for source in (entry, manifest):
        for key in ("license", "licenses"):
            raw = source.get(key)
            if isinstance(raw, str):
                values.append(raw)
            elif isinstance(raw, list):
                values.extend(str(item) for item in raw if item)
        for key in ("license_values", "license_counts"):
            raw = source.get(key)
            if isinstance(raw, list):
                values.extend(str(item) for item in raw if item)
            elif isinstance(raw, dict):
                values.extend(str(item) for item in raw)
    return _unique(values)


def _file_kind(path: Path) -> str:
    if path.name == "README.md":
        return "readme"
    if path.name == "manifest.json":
        return "manifest"
    if path.suffix == ".parquet":
        return "data"
    return "metadata"


def _safe_child(source_dir: Path, file_name: str) -> Path | None:
    if not file_name:
        return None
    candidate = Path(file_name)
    if candidate.is_absolute() or ".." in candidate.parts:
        return None
    source_resolved = source_dir.resolve()
    target = (source_dir / candidate).resolve()
    if not target.is_relative_to(source_resolved):
        return None
    return target


def _expected_outputs(
    source: SafeSource, manifest: dict[str, Any], source_dir: Path, repo_root: Path
) -> tuple[list[dict[str, Any]], list[str]]:
    blockers: list[str] = []
    expected: list[dict[str, Any]] = []

    if source.dataset == "safe-aggregates":
        datasets = manifest.get("datasets")
        if not isinstance(datasets, list) or not datasets:
            return [], ["aggregate manifest datasets must be a nonempty list"]
        if manifest.get("aggregate_only") is not True:
            blockers.append("aggregate manifest does not set aggregate_only=true")
        if manifest.get("row_level_sensitive_data_exported") is not False:
            blockers.append("aggregate manifest does not prove row_level_sensitive_data_exported=false")

        for dataset in datasets:
            if not isinstance(dataset, dict):
                blockers.append("aggregate dataset entry is not an object")
                continue
            file_name = str(dataset.get("path") or "")
            expected_path = _safe_child(source_dir, file_name)
            if expected_path is None:
                blockers.append(f"aggregate dataset entry has unsafe path: {file_name!r}")
                continue
            rows = _as_int(dataset.get("rows"))
            if rows is None:
                blockers.append(f"aggregate dataset {file_name} missing integer rows")
                rows = 0
            min_k = _as_int(dataset.get("min_k"))
            min_cell = _as_int(dataset.get("min_exported_cell_count"))
            if min_k is not None and min_cell is not None and min_cell < min_k:
                blockers.append(f"aggregate dataset {file_name} has min cell {min_cell} below k={min_k}")
            expected.append(
                {
                    "logical_dataset": str(dataset.get("dataset") or source.dataset),
                    "path": expected_path,
                    "rows": rows,
                    "manifest_bytes": _as_int(dataset.get("bytes")),
                    "manifest_sha256": dataset.get("sha256"),
                    "licenses": _licenses_from_entry(dataset, manifest),
                }
            )
        return expected, blockers

    exports = manifest.get("exports")
    if not isinstance(exports, list) or not exports:
        return [], ["manifest exports must be a nonempty list"]

    if source.dataset == "statistics-estat":
        if manifest.get("safety_gate_status") != "passed":
            blockers.append("statistics-estat safety_gate_status is not passed")
        if manifest.get("preview_only") is True:
            blockers.append("statistics-estat manifest is preview_only")
        if manifest.get("f3_full_publish_ready") is False:
            blockers.append("statistics-estat manifest says f3_full_publish_ready=false")
        if manifest.get("b9_provenance_complete") is False:
            blockers.append("statistics-estat manifest says b9_provenance_complete=false")

    for export in exports:
        if not isinstance(export, dict):
            blockers.append("manifest export entry is not an object")
            continue
        file_name = str(export.get("file") or "")
        expected_path = _safe_child(source_dir, file_name)
        if expected_path is None:
            blockers.append(f"manifest export entry has unsafe file path: {file_name!r}")
            continue
        rows = _as_int(export.get("rows"))
        if rows is None:
            blockers.append(f"manifest export {file_name} missing integer rows")
            rows = 0
        if source.dataset == "laws-jp" and export.get("safety_gate") != "passed":
            blockers.append(f"laws-jp export {file_name} safety_gate is not passed")
        expected.append(
            {
                "logical_dataset": str(export.get("table") or source.dataset),
                "path": expected_path,
                "rows": rows,
                "manifest_bytes": _as_int(export.get("bytes")),
                "manifest_sha256": export.get("sha256"),
                "licenses": _licenses_from_entry(export, manifest),
            }
        )
    return expected, blockers


def _scan_source_files(source_dir: Path, repo_root: Path) -> tuple[list[dict[str, Any]], list[str]]:
    files: list[dict[str, Any]] = []
    blockers: list[str] = []
    if not source_dir.exists():
        return files, [f"missing safe source directory: {_rel(source_dir, repo_root)}"]
    if not source_dir.is_dir():
        return files, [f"safe source path is not a directory: {_rel(source_dir, repo_root)}"]

    for path in sorted(source_dir.rglob("*")):
        if path.is_symlink():
            blockers.append(f"symlink is not allowed in upload source: {_rel(path, repo_root)}")
            continue
        if not path.is_file():
            continue
        files.append(
            {
                "path": _rel(path, repo_root),
                "name": path.name,
                "kind": _file_kind(path),
                "bytes": path.stat().st_size,
                "sha256": _sha256_file(path),
                "copied_to_bundle": False,
                "bundle_path": None,
            }
        )
    return files, blockers


def _validate_expected_outputs(
    expected_outputs: list[dict[str, Any]],
    scanned_files_by_path: dict[str, dict[str, Any]],
    repo_root: Path,
) -> tuple[list[dict[str, Any]], list[str]]:
    logical_outputs: list[dict[str, Any]] = []
    blockers: list[str] = []
    for expected in expected_outputs:
        path = expected["path"]
        path_rel = _rel(path, repo_root)
        actual = scanned_files_by_path.get(path_rel)
        output_blockers: list[str] = []
        actual_bytes = None
        actual_sha256 = None

        if actual is None:
            output_blockers.append(f"missing expected data file: {path_rel}")
        else:
            actual_bytes = int(actual["bytes"])
            actual_sha256 = str(actual["sha256"])
            manifest_bytes = expected["manifest_bytes"]
            if manifest_bytes is not None and manifest_bytes != actual_bytes:
                output_blockers.append(
                    f"manifest byte count does not match file size for {path_rel}: "
                    f"{manifest_bytes} != {actual_bytes}"
                )
            manifest_sha256 = expected["manifest_sha256"]
            if manifest_sha256 and str(manifest_sha256) != actual_sha256:
                output_blockers.append(f"manifest sha256 does not match file checksum for {path_rel}")

        if int(expected["rows"]) < 0:
            output_blockers.append(f"negative row count in manifest for {path_rel}")
        if not expected["licenses"]:
            output_blockers.append(f"missing license metadata in manifest for {path_rel}")

        blockers.extend(output_blockers)
        logical_outputs.append(
            {
                "logical_dataset": expected["logical_dataset"],
                "path": path_rel,
                "rows": int(expected["rows"]),
                "manifest_bytes": expected["manifest_bytes"],
                "actual_bytes": actual_bytes,
                "manifest_sha256": expected["manifest_sha256"],
                "actual_sha256": actual_sha256,
                "licenses": expected["licenses"],
                "blockers": output_blockers,
            }
        )
    return logical_outputs, blockers


def _copy_small_metadata(
    *,
    files: list[dict[str, Any]],
    source_dir_name: str,
    bundle_dir: Path,
    repo_root: Path,
    max_copy_bytes: int,
) -> int:
    copied = 0
    for file_entry in files:
        if file_entry["name"] not in SMALL_METADATA_NAMES:
            continue
        if int(file_entry["bytes"]) > max_copy_bytes:
            continue
        source_path = repo_root / str(file_entry["path"])
        if not source_path.exists():
            continue
        destination = bundle_dir / "sources" / source_dir_name / str(file_entry["name"])
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, destination)
        file_entry["copied_to_bundle"] = True
        file_entry["bundle_path"] = _rel(destination, repo_root)
        copied += 1
    return copied


def _operator_next_action(
    *,
    source: SafeSource,
    source_dir: Path,
    blockers: list[str],
    bundle_dir: Path,
    repo_root: Path,
) -> str:
    if blockers:
        return (
            "Do not publish this dataset. Resolve the blockers, regenerate the safe local export, "
            "then rerun scripts/hf_prepare_upload_bundle.py."
        )
    return (
        "Local bundle only. Review "
        f"{_rel(bundle_dir / 'checksums.sha256', repo_root)} and the copied manifests; "
        "only after separate operator approval and HF write-token authentication, upload "
        f"{_rel(source_dir, repo_root)} to {source.repo_id}. Never upload dist/hf-dataset."
    )


def _build_source_entry(
    *,
    source: SafeSource,
    dist_root: Path,
    bundle_dir: Path,
    repo_root: Path,
    copy_small_files: bool,
    max_copy_bytes: int,
) -> dict[str, Any]:
    source_dir = dist_root / source.dir_name
    manifest_path = source_dir / "manifest.json"
    blockers: list[str] = []
    manifest: dict[str, Any] = {}
    expected_outputs: list[dict[str, Any]] = []

    files, scan_blockers = _scan_source_files(source_dir, repo_root)
    blockers.extend(scan_blockers)

    if source_dir.exists() and source_dir.is_dir():
        if not manifest_path.exists():
            blockers.append(f"missing safe source manifest: {_rel(manifest_path, repo_root)}")
        else:
            manifest = _load_json(manifest_path)
            expected_outputs, expected_blockers = _expected_outputs(
                source, manifest, source_dir, repo_root
            )
            blockers.extend(expected_blockers)

    scanned_by_path = {str(file_entry["path"]): file_entry for file_entry in files}
    logical_outputs, output_blockers = _validate_expected_outputs(
        expected_outputs, scanned_by_path, repo_root
    )
    blockers.extend(output_blockers)

    copied_count = 0
    if copy_small_files:
        copied_count = _copy_small_metadata(
            files=files,
            source_dir_name=source.dir_name,
            bundle_dir=bundle_dir,
            repo_root=repo_root,
            max_copy_bytes=max_copy_bytes,
        )

    data_files = [file_entry for file_entry in files if file_entry["kind"] == "data"]
    rows = sum(int(output["rows"]) for output in logical_outputs if not output["blockers"])
    data_bytes = sum(int(output["actual_bytes"] or 0) for output in logical_outputs)
    source_bytes = sum(int(file_entry["bytes"]) for file_entry in files)
    licenses = _unique(
        [license_ for output in logical_outputs for license_ in output.get("licenses", [])]
    )

    return {
        "dataset": source.dataset,
        "repo_id": source.repo_id,
        "source_dir": _rel(source_dir, repo_root),
        "manifest_path": _rel(manifest_path, repo_root) if manifest_path.exists() else None,
        "manifest_generated_at": manifest.get("generated_at"),
        "publish_performed": False,
        "file_count": len(files),
        "source_bytes": source_bytes,
        "data_file_count": len(data_files),
        "data_bytes": data_bytes,
        "logical_output_count": len(logical_outputs),
        "row_count": rows,
        "licenses": licenses,
        "copied_small_file_count": copied_count,
        "blockers": blockers,
        "operator_next_action": _operator_next_action(
            source=source,
            source_dir=source_dir,
            blockers=blockers,
            bundle_dir=bundle_dir,
            repo_root=repo_root,
        ),
        "logical_outputs": logical_outputs,
        "files": files,
    }


def _excluded_sources(dist_root: Path, repo_root: Path) -> list[dict[str, Any]]:
    excluded: list[dict[str, Any]] = []
    for dir_name in EXCLUDED_SOURCE_DIRS:
        source_dir = dist_root / dir_name
        excluded.append(
            {
                "path": _rel(source_dir, repo_root),
                "exists": source_dir.exists(),
                "included_in_bundle": False,
                "reason": "Explicitly excluded unsafe legacy Hugging Face export.",
            }
        )
    return excluded


def _checksum_lines(source_entries: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    for source_entry in source_entries:
        for file_entry in source_entry["files"]:
            lines.append(f"{file_entry['sha256']}  {file_entry['path']}")
    return sorted(lines)


def _top_level_actions(manifest: dict[str, Any]) -> list[str]:
    if manifest["summary"]["source_dirs_blocked_count"]:
        return [
            "Do not publish. Resolve blocked source directories and rerun the bundle generator.",
            "Do not upload dist/hf-dataset.",
        ]
    return [
        "Review dist/hf-upload-bundle/manifest.json and dist/hf-upload-bundle/checksums.sha256.",
        "Verify the copied source manifests/READMEs against the source export directories.",
        "After separate approval and HF write-token authentication, upload only the safe source directories.",
        "Do not upload dist/hf-dataset.",
    ]


def prepare_upload_bundle(
    *,
    dist_root: Path = DEFAULT_DIST_ROOT,
    bundle_dir: Path = DEFAULT_BUNDLE_DIR,
    analysis_output: Path = DEFAULT_ANALYSIS_OUTPUT,
    repo_root: Path = REPO_ROOT,
    generated_at: datetime | None = None,
    copy_small_files: bool = True,
    max_copy_bytes: int = DEFAULT_MAX_COPY_BYTES,
) -> dict[str, Any]:
    generated_source = generated_at or datetime.now().astimezone()
    generated = generated_source.astimezone(UTC).replace(microsecond=0)

    bundle_dir.mkdir(parents=True, exist_ok=True)
    source_entries = [
        _build_source_entry(
            source=source,
            dist_root=dist_root,
            bundle_dir=bundle_dir,
            repo_root=repo_root,
            copy_small_files=copy_small_files,
            max_copy_bytes=max_copy_bytes,
        )
        for source in SAFE_SOURCES
    ]

    ready = [entry for entry in source_entries if not entry["blockers"]]
    blocked = [entry for entry in source_entries if entry["blockers"]]
    checksum_lines = _checksum_lines(source_entries)
    checksums_path = bundle_dir / "checksums.sha256"
    checksums_path.write_text("\n".join(checksum_lines) + ("\n" if checksum_lines else ""), encoding="utf-8")

    summary = {
        "safe_source_dir_count": len(source_entries),
        "source_dirs_ready_count": len(ready),
        "source_dirs_blocked_count": len(blocked),
        "logical_output_count": sum(int(entry["logical_output_count"]) for entry in source_entries),
        "data_file_count": sum(int(entry["data_file_count"]) for entry in source_entries),
        "source_file_count": sum(int(entry["file_count"]) for entry in source_entries),
        "source_file_bytes": sum(int(entry["source_bytes"]) for entry in source_entries),
        "data_file_bytes": sum(int(entry["data_bytes"]) for entry in source_entries),
        "row_count": sum(int(entry["row_count"]) for entry in ready),
        "copied_small_file_count": sum(int(entry["copied_small_file_count"]) for entry in source_entries),
        "excluded_source_count": len(EXCLUDED_SOURCE_DIRS),
        "publish_performed": False,
    }
    manifest: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated.isoformat().replace("+00:00", "Z"),
        "publish_performed": False,
        "network_used": False,
        "upload_performed": False,
        "bundle_dir": _rel(bundle_dir, repo_root),
        "analysis_output": _rel(analysis_output, repo_root),
        "checksums_path": _rel(checksums_path, repo_root),
        "source_scope": [_rel(dist_root / source.dir_name, repo_root) for source in SAFE_SOURCES],
        "excluded_sources": _excluded_sources(dist_root, repo_root),
        "summary": summary,
        "sources_ready_local": ready,
        "sources_blocked": blocked,
        "operator_next_actions": [],
        "notes": [
            "Local bundle/checksum preparation only; no Hugging Face publish was performed.",
            "Only the three safe export directories were read for source files.",
            "dist/hf-dataset is explicitly excluded and must not be uploaded.",
            "Small README.md and manifest.json files may be copied into the bundle for review.",
        ],
    }
    manifest["operator_next_actions"] = _top_level_actions(manifest)

    manifest_path = bundle_dir / "manifest.json"
    payload = json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    manifest_path.write_text(payload, encoding="utf-8")
    analysis_output.parent.mkdir(parents=True, exist_ok=True)
    analysis_output.write_text(payload, encoding="utf-8")
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist-root", type=Path, default=DEFAULT_DIST_ROOT)
    parser.add_argument("--bundle-dir", type=Path, default=DEFAULT_BUNDLE_DIR)
    parser.add_argument("--analysis-output", type=Path, default=DEFAULT_ANALYSIS_OUTPUT)
    parser.add_argument(
        "--skip-copy-small-files",
        action="store_true",
        help="Do not copy README.md or manifest.json files into the bundle.",
    )
    parser.add_argument(
        "--max-copy-bytes",
        type=int,
        default=DEFAULT_MAX_COPY_BYTES,
        help=f"Maximum README/manifest size to copy (default: {DEFAULT_MAX_COPY_BYTES}).",
    )
    args = parser.parse_args(argv)

    try:
        manifest = prepare_upload_bundle(
            dist_root=args.dist_root,
            bundle_dir=args.bundle_dir,
            analysis_output=args.analysis_output,
            copy_small_files=not args.skip_copy_small_files,
            max_copy_bytes=args.max_copy_bytes,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    summary = manifest["summary"]
    print(f"Wrote {args.bundle_dir / 'manifest.json'}")
    print(f"Wrote {args.bundle_dir / 'checksums.sha256'}")
    print(f"Wrote {args.analysis_output}")
    print(
        "Ready local source dirs: "
        f"{summary['source_dirs_ready_count']}/{summary['safe_source_dir_count']} "
        f"({summary['logical_output_count']} outputs, "
        f"{summary['source_file_count']} files, {summary['source_file_bytes']:,} bytes)"
    )
    print(f"Copied small metadata files: {summary['copied_small_file_count']}")
    print("Publish performed: false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
