from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_SCRIPTS = _ROOT / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import hf_publish_readiness_report as report  # noqa: E402


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_file(path: Path, payload: bytes) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return len(payload)


def _create_safe_exports(dist_root: Path) -> None:
    laws_bytes = _write_file(dist_root / "hf-laws-jp" / "laws.parquet", b"laws parquet")
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
                    "license": "cc_by_4.0",
                    "safety_gate": "passed",
                }
            ],
        },
    )

    estat_bytes = _write_file(
        dist_root / "hf-statistics-estat" / "estat_statistics_facts.parquet",
        b"estat parquet",
    )
    _write_json(
        dist_root / "hf-statistics-estat" / "manifest.json",
        {
            "dataset": "statistics-estat",
            "generated_at": "2026-05-01T00:00:00Z",
            "exports": [
                {
                    "table": "estat_statistics_facts",
                    "file": "estat_statistics_facts.parquet",
                    "rows": 3,
                    "bytes": estat_bytes,
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

    invoice_bytes = _write_file(
        dist_root / "hf-aggregates-safe" / "invoice_registrants_by_prefecture.parquet",
        b"invoice aggregate",
    )
    enforcement_bytes = _write_file(
        dist_root / "hf-aggregates-safe" / "enforcement_cases_by_ministry.parquet",
        b"enforcement aggregate",
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
                    "license": "pdl_v1.0",
                    "min_k": 5,
                    "min_exported_cell_count": 5,
                },
                {
                    "dataset": "enforcement_cases_by_ministry",
                    "path": "enforcement_cases_by_ministry.parquet",
                    "rows": 2,
                    "bytes": enforcement_bytes,
                    "license": "gov_standard_v2.0",
                    "min_k": 5,
                    "min_exported_cell_count": 6,
                },
            ],
        },
    )


def test_build_report_summarizes_safe_exports_and_flags_legacy_dist(tmp_path: Path) -> None:
    dist_root = tmp_path / "dist"
    _create_safe_exports(dist_root)
    (dist_root / "hf-dataset").mkdir()

    readiness = report.build_report(
        dist_root=dist_root,
        repo_root=tmp_path,
        generated_at=datetime(2026, 5, 1, tzinfo=UTC),
    )

    assert readiness["publish_performed"] is False
    assert readiness["network_used"] is False
    assert readiness["summary"] == {
        "safe_dataset_count": 4,
        "datasets_ready_local_count": 4,
        "datasets_blocked_count": 0,
        "unsafe_or_stale_export_count": 1,
        "ready_local_rows": 8,
        "ready_local_bytes": 63,
        "publish_performed": False,
    }
    assert [dataset["dataset"] for dataset in readiness["datasets_ready_local"]] == [
        "laws-jp",
        "statistics-estat",
        "invoice_registrants_by_prefecture",
        "enforcement_cases_by_ministry",
    ]
    assert readiness["datasets_ready_local"][0]["licenses"] == ["cc_by_4.0"]
    assert readiness["datasets_ready_local"][0]["safety_gate_status"] == "passed"
    assert readiness["datasets_ready_local"][0]["operator_next_action"].startswith(
        "Operator only after HF write-token authentication"
    )
    assert "Do not publish or upload dist/hf-dataset" in (
        readiness["unsafe_or_stale_exports"][0]["operator_next_action"]
    )
    assert "safety gate fails on the current DB" in (
        readiness["unsafe_or_stale_exports"][0]["blockers"][0]
    )


def test_statistics_preview_manifest_is_blocked(tmp_path: Path) -> None:
    dist_root = tmp_path / "dist"
    _create_safe_exports(dist_root)
    estat_manifest = dist_root / "hf-statistics-estat" / "manifest.json"
    value = json.loads(estat_manifest.read_text(encoding="utf-8"))
    value["preview_only"] = True
    value["f3_full_publish_ready"] = False
    value["b9_provenance_complete"] = False
    _write_json(estat_manifest, value)

    readiness = report.build_report(
        dist_root=dist_root,
        repo_root=tmp_path,
        generated_at=datetime(2026, 5, 1, tzinfo=UTC),
    )

    blocked = {dataset["dataset"]: dataset for dataset in readiness["datasets_blocked"]}
    assert set(blocked) == {"statistics-estat"}
    assert blocked["statistics-estat"]["safety_gate_status"] == "passed"
    assert "full F3 readiness incomplete" in " ".join(blocked["statistics-estat"]["blockers"])
    assert "Do not publish. Resolve the blockers" in (
        blocked["statistics-estat"]["operator_next_action"]
    )
    assert readiness["summary"]["datasets_ready_local_count"] == 3


def test_file_byte_mismatch_blocks_dataset(tmp_path: Path) -> None:
    dist_root = tmp_path / "dist"
    _create_safe_exports(dist_root)
    laws_manifest = dist_root / "hf-laws-jp" / "manifest.json"
    value = json.loads(laws_manifest.read_text(encoding="utf-8"))
    value["exports"][0]["bytes"] = 999
    _write_json(laws_manifest, value)

    readiness = report.build_report(
        dist_root=dist_root,
        repo_root=tmp_path,
        generated_at=datetime(2026, 5, 1, tzinfo=UTC),
    )

    blocked = {dataset["dataset"]: dataset for dataset in readiness["datasets_blocked"]}
    assert set(blocked) == {"laws-jp"}
    assert blocked["laws-jp"]["bytes"] == len(b"laws parquet")
    assert "manifest byte count does not match parquet file size" in (
        blocked["laws-jp"]["blockers"][0]
    )


def test_main_writes_report_file(tmp_path: Path) -> None:
    dist_root = tmp_path / "dist"
    output = tmp_path / "analysis" / "readiness.json"
    _create_safe_exports(dist_root)

    assert report.main(["--dist-root", str(dist_root), "--output", str(output)]) == 0

    saved = json.loads(output.read_text(encoding="utf-8"))
    assert saved["schema_version"] == report.SCHEMA_VERSION
    assert saved["summary"]["safe_dataset_count"] == 4
    assert saved["summary"]["publish_performed"] is False
