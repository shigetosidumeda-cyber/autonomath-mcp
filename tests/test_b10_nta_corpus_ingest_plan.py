from __future__ import annotations

import json
import os
import shlex
import sys
from pathlib import Path
from typing import Any

import pytest

_ETL = Path(__file__).resolve().parent.parent / "scripts" / "etl"
if str(_ETL) not in sys.path:
    sys.path.insert(0, str(_ETL))

import generate_nta_corpus_ingest_plan as generator  # noqa: E402


def _write_coverage(tmp_path: Path, report: dict[str, Any]) -> Path:
    path = tmp_path / "nta_corpus_coverage.json"
    path.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    return path


def _write_ingest_source(tmp_path: Path) -> Path:
    path = tmp_path / "ingest_nta_corpus.py"
    path.write_text(
        "\n".join(
            [
                'SHITSUGI_CATEGORIES = ["shotoku", "gensen", "hojin"]',
                'BUNSHO_CATEGORIES = [("shotoku", "02"), ("shohi", "09")]',
                "",
            ]
        ),
        encoding="utf-8",
    )
    return path


def _coverage_report() -> dict[str, Any]:
    return {
        "generated_at": "2026-05-01T00:00:00+00:00",
        "totals": {
            "rows": 16,
            "source_url_missing": 0,
            "license_missing": 0,
        },
        "duplicates": {
            "within_table_count": 2,
            "across_table_count": 0,
            "within_table": [
                {
                    "table": "nta_tsutatsu_index",
                    "source_url": "https://www.nta.go.jp/law/example.htm",
                    "rows": 3,
                }
            ],
            "across_table": [],
        },
        "tables": {
            "nta_shitsugi": {
                "exists": True,
                "metadata_completeness": {
                    "total_rows": 2,
                    "source_url_missing": 0,
                    "license_missing": 0,
                    "license_column_present": True,
                },
                "counts_by_dimension": [{"category": "shotoku", "rows": 2}],
            },
            "nta_bunsho_kaitou": {
                "exists": True,
                "metadata_completeness": {
                    "total_rows": 4,
                    "source_url_missing": 0,
                    "license_missing": 0,
                    "license_column_present": True,
                },
                "counts_by_dimension": [{"category": "shohi", "rows": 4}],
            },
            "nta_saiketsu": {
                "exists": True,
                "metadata_completeness": {
                    "total_rows": 3,
                    "source_url_missing": 0,
                    "license_missing": 0,
                    "license_column_present": True,
                },
                "counts_by_dimension": [
                    {"tax_type": "所得税", "rows": 2},
                    {"tax_type": "たばこ税", "rows": 1},
                ],
            },
            "nta_tsutatsu_index": {
                "exists": True,
                "metadata_completeness": {
                    "total_rows": 7,
                    "source_url_missing": 0,
                    "license_missing": None,
                    "license_column_present": False,
                },
                "counts_by_dimension": [
                    {"tax_type": "law:hojin-zei-tsutatsu", "rows": 7}
                ],
            },
        },
    }


def test_generate_ingest_plan_writes_runbook_and_target_shards(tmp_path: Path) -> None:
    coverage_input = _write_coverage(tmp_path, _coverage_report())
    ingest_source = _write_ingest_source(tmp_path)
    output = tmp_path / "analysis" / "nta_corpus_ingest_plan.json"
    output_dir = tmp_path / "runs"
    log_dir = tmp_path / "logs"
    repo_root = tmp_path / "repo"

    plan = generator.generate_ingest_plan(
        coverage_input=coverage_input,
        output=output,
        output_dir=output_dir,
        repo_root=repo_root,
        log_dir=log_dir,
        run_date="2026-05-01",
        max_minutes=12,
        autonomath_db=Path("autonomath.db"),
        jpintel_db=Path("data/jpintel.db"),
        python_bin=".venv/bin/python",
        ingest_source=ingest_source,
        generated_at="2026-05-01T00:00:00+00:00",
    )

    assert json.loads(output.read_text(encoding="utf-8")) == plan
    assert plan["complete"] is False
    assert plan["network_used"] is False
    assert plan["shard_count"] == 3
    assert plan["target_category_count"] == 7
    assert plan["zero_row_category_count"] == 3
    assert plan["current_counts"]["totals"]["rows"] == 16
    assert plan["duplicate_source_issue"] == {
        "severity": "blocker",
        "within_table_group_count": 2,
        "across_table_group_count": 0,
        "description": (
            "Coverage shows duplicate source_url groups. Most current samples are in "
            "nta_tsutatsu_index, whose schema keys by code rather than source_url."
        ),
        "top_groups": [
            {
                "table": "nta_tsutatsu_index",
                "source_url": "https://www.nta.go.jp/law/example.htm",
                "rows": 3,
            }
        ],
    }
    assert {item["id"] for item in plan["blockers"]} >= {
        "category-boundaries-advisory",
        "duplicate-source-url-groups",
        "tsutatsu-not-in-cron",
    }
    assert any(
        query["name"] == "nta_duplicate_source_url_groups"
        for query in plan["acceptance_queries"]
    )

    shitsugi = next(shard for shard in plan["shards"] if shard["target"] == "shitsugi")
    assert shitsugi["current_rows"] == 2
    assert shitsugi["category_count"] == 3
    assert shitsugi["zero_row_category_count"] == 2
    assert [item["category"] for item in shitsugi["category_queue"][:2]] == [
        "gensen",
        "hojin",
    ]
    assert "scripts/cron/ingest_nta_corpus_incremental.py" in shitsugi["command"]
    assert "--target shitsugi" in shitsugi["command"]
    assert "--max-minutes 12" in shitsugi["command"]
    assert "--log-file" in shitsugi["command"]
    assert "--dry-run" in shitsugi["dry_run_command"]

    script_path = output_dir / "nta_corpus_shitsugi_2026-05-01.sh"
    assert os.access(script_path, os.X_OK)
    script_text = script_path.read_text(encoding="utf-8")
    assert "set -euo pipefail" in script_text
    assert f"cd {shlex.quote(str(repo_root))}" in script_text
    assert "category_queue=gensen:0, hojin:0, shotoku:2" in script_text
    assert "scripts/cron/ingest_nta_corpus_incremental.py" in script_text
    assert "--target shitsugi" in script_text
    assert "--max-minutes 12" in script_text
    assert "CRON_JSONL_LOG=" in script_text

    assert not (output_dir / "nta_corpus_tsutatsu_idx_2026-05-01.sh").exists()


def test_max_minutes_must_stay_inside_safe_boundary(tmp_path: Path) -> None:
    coverage_input = _write_coverage(tmp_path, _coverage_report())
    ingest_source = _write_ingest_source(tmp_path)

    with pytest.raises(ValueError, match="between 1 and 20"):
        generator.generate_ingest_plan(
            coverage_input=coverage_input,
            output=tmp_path / "plan.json",
            output_dir=tmp_path / "runs",
            max_minutes=30,
            ingest_source=ingest_source,
        )


def test_no_scripts_mode_only_writes_plan_json(tmp_path: Path) -> None:
    coverage_input = _write_coverage(tmp_path, _coverage_report())
    ingest_source = _write_ingest_source(tmp_path)
    output_dir = tmp_path / "runs"

    plan = generator.generate_ingest_plan(
        coverage_input=coverage_input,
        output=tmp_path / "plan.json",
        output_dir=output_dir,
        max_minutes=5,
        ingest_source=ingest_source,
        write_scripts=False,
    )

    assert plan["shard_count"] == 3
    assert not output_dir.exists()
