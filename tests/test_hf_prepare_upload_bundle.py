from __future__ import annotations

import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
_SCRIPTS = _ROOT / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import hf_prepare_upload_bundle as bundle  # noqa: E402


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_file(path: Path, payload: bytes) -> tuple[int, str]:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return len(payload), hashlib.sha256(payload).hexdigest()


def _create_safe_exports(dist_root: Path) -> None:
    laws_bytes, laws_sha = _write_file(dist_root / "hf-laws-jp" / "laws.parquet", b"laws")
    (dist_root / "hf-laws-jp" / "README.md").write_text("# laws\n", encoding="utf-8")
    _write_json(
        dist_root / "hf-laws-jp" / "manifest.json",
        {
            "dataset": "laws-jp",
            "generated_at": "2026-05-01T00:00:00Z",
            "exports": [
                {
                    "table": "laws",
                    "file": "laws.parquet",
                    "rows": 2,
                    "bytes": laws_bytes,
                    "sha256": laws_sha,
                    "license": "cc_by_4.0",
                    "safety_gate": "passed",
                }
            ],
        },
    )

    estat_bytes, estat_sha = _write_file(
        dist_root / "hf-statistics-estat" / "estat_statistics_facts.parquet",
        b"estat",
    )
    (dist_root / "hf-statistics-estat" / "README.md").write_text("# estat\n", encoding="utf-8")
    _write_json(
        dist_root / "hf-statistics-estat" / "manifest.json",
        {
            "schema_version": "hf_estat_statistics_export.v1",
            "dataset": "statistics-estat",
            "generated_at": "2026-05-01T00:00:00Z",
            "exports": [
                {
                    "table": "estat_statistics_facts",
                    "file": "estat_statistics_facts.parquet",
                    "rows": 3,
                    "bytes": estat_bytes,
                    "sha256": estat_sha,
                    "license_values": ["gov_standard_v2.0"],
                }
            ],
            "preview_only": False,
            "f3_full_publish_ready": True,
            "b9_provenance_complete": True,
            "safety_gate_status": "passed",
            "license_values": ["gov_standard_v2.0"],
        },
    )

    invoice_bytes, invoice_sha = _write_file(
        dist_root / "hf-aggregates-safe" / "invoice_registrants_by_prefecture.parquet",
        b"invoice",
    )
    enforcement_bytes, enforcement_sha = _write_file(
        dist_root / "hf-aggregates-safe" / "enforcement_cases_by_ministry.parquet",
        b"enforcement",
    )
    _write_json(
        dist_root / "hf-aggregates-safe" / "manifest.json",
        {
            "schema_version": "hf_safe_aggregate_exports.v1",
            "generated_at": "2026-05-01T00:00:00Z",
            "aggregate_only": True,
            "row_level_sensitive_data_exported": False,
            "datasets": [
                {
                    "dataset": "invoice_registrants_by_prefecture",
                    "path": "invoice_registrants_by_prefecture.parquet",
                    "rows": 1,
                    "bytes": invoice_bytes,
                    "sha256": invoice_sha,
                    "license": "pdl_v1.0",
                    "min_k": 5,
                    "min_exported_cell_count": 5,
                },
                {
                    "dataset": "enforcement_cases_by_ministry",
                    "path": "enforcement_cases_by_ministry.parquet",
                    "rows": 2,
                    "bytes": enforcement_bytes,
                    "sha256": enforcement_sha,
                    "license": "gov_standard_v2.0",
                    "min_k": 5,
                    "min_exported_cell_count": 6,
                },
            ],
        },
    )


def test_prepare_bundle_hashes_safe_sources_and_excludes_legacy(tmp_path: Path) -> None:
    dist_root = tmp_path / "dist"
    bundle_dir = dist_root / "hf-upload-bundle"
    analysis_output = tmp_path / "analysis" / "hf_upload_bundle_2026-05-01.json"
    _create_safe_exports(dist_root)
    _write_file(dist_root / "hf-dataset" / "unsafe.parquet", b"unsafe")

    manifest = bundle.prepare_upload_bundle(
        dist_root=dist_root,
        bundle_dir=bundle_dir,
        analysis_output=analysis_output,
        repo_root=tmp_path,
        generated_at=datetime(2026, 5, 1, tzinfo=UTC),
    )

    assert manifest["publish_performed"] is False
    assert manifest["network_used"] is False
    assert manifest["upload_performed"] is False
    assert manifest["summary"] == {
        "safe_source_dir_count": 3,
        "source_dirs_ready_count": 3,
        "source_dirs_blocked_count": 0,
        "logical_output_count": 4,
        "data_file_count": 4,
        "source_file_count": 9,
        "source_file_bytes": sum(
            path.stat().st_size
            for source_dir in (
                dist_root / "hf-laws-jp",
                dist_root / "hf-statistics-estat",
                dist_root / "hf-aggregates-safe",
            )
            for path in source_dir.rglob("*")
            if path.is_file()
        ),
        "data_file_bytes": len(b"laws") + len(b"estat") + len(b"invoice") + len(b"enforcement"),
        "row_count": 8,
        "copied_small_file_count": 5,
        "excluded_source_count": 1,
        "publish_performed": False,
    }
    assert manifest["excluded_sources"] == [
        {
            "path": "dist/hf-dataset",
            "exists": True,
            "included_in_bundle": False,
            "reason": "Explicitly excluded unsafe legacy Hugging Face export.",
        }
    ]
    assert not any(
        "hf-dataset" in file_entry["path"]
        for source in manifest["sources_ready_local"]
        for file_entry in source["files"]
    )
    assert (bundle_dir / "manifest.json").exists()
    assert analysis_output.exists()
    assert json.loads((bundle_dir / "manifest.json").read_text(encoding="utf-8")) == manifest
    assert json.loads(analysis_output.read_text(encoding="utf-8")) == manifest

    checksum_text = (bundle_dir / "checksums.sha256").read_text(encoding="utf-8")
    assert "dist/hf-laws-jp/laws.parquet" in checksum_text
    assert "dist/hf-dataset" not in checksum_text
    assert (bundle_dir / "sources" / "hf-laws-jp" / "README.md").exists()
    assert (bundle_dir / "sources" / "hf-laws-jp" / "manifest.json").exists()
    assert (bundle_dir / "sources" / "hf-aggregates-safe" / "manifest.json").exists()
    assert not list(bundle_dir.rglob("*.parquet"))


def test_prepare_bundle_blocks_manifest_mismatches_and_preview_export(tmp_path: Path) -> None:
    dist_root = tmp_path / "dist"
    _create_safe_exports(dist_root)

    laws_manifest = dist_root / "hf-laws-jp" / "manifest.json"
    laws_value = json.loads(laws_manifest.read_text(encoding="utf-8"))
    laws_value["exports"][0]["bytes"] = 999
    _write_json(laws_manifest, laws_value)

    estat_manifest = dist_root / "hf-statistics-estat" / "manifest.json"
    estat_value = json.loads(estat_manifest.read_text(encoding="utf-8"))
    estat_value["preview_only"] = True
    estat_value["f3_full_publish_ready"] = False
    _write_json(estat_manifest, estat_value)

    aggregate_manifest = dist_root / "hf-aggregates-safe" / "manifest.json"
    aggregate_value = json.loads(aggregate_manifest.read_text(encoding="utf-8"))
    aggregate_value["datasets"][0]["min_exported_cell_count"] = 4
    _write_json(aggregate_manifest, aggregate_value)

    manifest = bundle.prepare_upload_bundle(
        dist_root=dist_root,
        bundle_dir=tmp_path / "bundle",
        analysis_output=tmp_path / "analysis.json",
        repo_root=tmp_path,
        generated_at=datetime(2026, 5, 1, tzinfo=UTC),
    )

    assert manifest["summary"]["source_dirs_ready_count"] == 0
    assert manifest["summary"]["source_dirs_blocked_count"] == 3
    blocked = {
        entry["dataset"]: " ".join(entry["blockers"]) for entry in manifest["sources_blocked"]
    }
    assert "manifest byte count does not match file size" in blocked["laws-jp"]
    assert "statistics-estat manifest is preview_only" in blocked["statistics-estat"]
    assert "f3_full_publish_ready=false" in blocked["statistics-estat"]
    assert "min cell 4 below k=5" in blocked["safe-aggregates"]
    assert manifest["operator_next_actions"][0].startswith("Do not publish")
    assert manifest["publish_performed"] is False


def test_main_writes_bundle_outputs_without_copying_metadata(tmp_path: Path) -> None:
    dist_root = tmp_path / "dist"
    bundle_dir = tmp_path / "bundle"
    analysis_output = tmp_path / "analysis" / "bundle.json"
    _create_safe_exports(dist_root)

    assert (
        bundle.main(
            [
                "--dist-root",
                str(dist_root),
                "--bundle-dir",
                str(bundle_dir),
                "--analysis-output",
                str(analysis_output),
                "--skip-copy-small-files",
            ]
        )
        == 0
    )

    manifest = json.loads((bundle_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["summary"]["copied_small_file_count"] == 0
    assert manifest["summary"]["source_dirs_ready_count"] == 3
    assert (bundle_dir / "checksums.sha256").exists()
    assert analysis_output.exists()
    assert not (bundle_dir / "sources").exists()
