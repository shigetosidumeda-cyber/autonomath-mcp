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

import generate_tier_bc_liveness_shards as generator  # noqa: E402


def _write_plan(tmp_path: Path, plan: dict[str, Any]) -> Path:
    path = tmp_path / "tier_bc_liveness_plan.json"
    path.write_text(json.dumps(plan, sort_keys=True), encoding="utf-8")
    return path


def _plan(
    *,
    shards: list[dict[str, Any]] | None = None,
    domain_counts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if domain_counts is None:
        domain_counts = [
            {"domain": "a.example", "row_count": 2},
            {"domain": "b.example", "row_count": 3},
            {"domain": "c.example", "row_count": 1},
        ]
    if shards is None:
        shards = [
            {
                "shard_id": "tier-bc-liveness-01",
                "domain_count": 2,
                "row_count": 5,
                "domains": ["a.example", "b.example"],
            },
            {
                "shard_id": "tier-bc-liveness-02",
                "domain_count": 1,
                "row_count": 1,
                "domains": ["c.example"],
            },
        ]
    return {
        "domain_counts": domain_counts,
        "safe_batching_plan": {
            "domain_exclusive": True,
            "shards": shards,
        },
    }


def test_generate_liveness_shards_from_plan_writes_domain_disjoint_scripts(
    tmp_path: Path,
) -> None:
    plan_input = _write_plan(tmp_path, _plan())
    output_dir = tmp_path / "runs"
    result_dir = tmp_path / "results"
    log_dir = tmp_path / "logs"
    repo_root = tmp_path / "repo"

    summary = generator.generate_shard_scripts(
        plan_input=plan_input,
        output_dir=output_dir,
        repo_root=repo_root,
        db_path=Path("data/jpintel.db"),
        result_dir=result_dir,
        log_dir=log_dir,
        generated_at="2026-05-01T00:00:00+00:00",
    )

    assert summary["script_count"] == 2
    assert summary["domain_count"] == 3
    assert summary["candidate_rows"] == 6
    assert summary["domain_exclusive"] is True
    assert summary["complete"] is False
    assert summary["network_used"] is False
    assert not result_dir.exists()

    script_1 = output_dir / "tier_bc_liveness_shard_01_2026-05-01.sh"
    script_2 = output_dir / "tier_bc_liveness_shard_02_2026-05-01.sh"

    assert os.access(script_1, os.X_OK)
    assert os.access(script_2, os.X_OK)

    text_1 = script_1.read_text(encoding="utf-8")
    assert "set -euo pipefail" in text_1
    assert f"cd {shlex.quote(str(repo_root))}" in text_1
    assert "scripts/etl/scan_program_url_liveness.py" in text_1
    assert '--domain "$domain"' in text_1
    assert '--limit "$limit"' in text_1
    assert "--per-host-delay-sec 1.0" in text_1
    assert "run_domain a.example 2 domain_001.csv.tmp" in text_1
    assert "run_domain b.example 3 domain_002.csv.tmp" in text_1
    assert "tail -n +2" in text_1
    assert 'rm -f "$tmp_csv"' in text_1
    assert "c.example" not in text_1
    assert (
        f"LOG_PATH={shlex.quote(str(log_dir / 'tier_bc_liveness_shard_01_2026-05-01.log'))}"
        in text_1
    )
    assert f"RESULT_DIR={shlex.quote(str(result_dir / 'shard_01'))}" in text_1

    text_2 = script_2.read_text(encoding="utf-8")
    assert "run_domain c.example 1 domain_001.csv.tmp" in text_2
    assert "a.example" not in text_2
    assert "b.example" not in text_2


def test_duplicate_domain_across_shards_is_rejected(tmp_path: Path) -> None:
    plan_input = _write_plan(
        tmp_path,
        _plan(
            shards=[
                {
                    "shard_id": "tier-bc-liveness-01",
                    "domain_count": 1,
                    "row_count": 2,
                    "domains": ["dup.example"],
                },
                {
                    "shard_id": "tier-bc-liveness-02",
                    "domain_count": 1,
                    "row_count": 2,
                    "domains": ["dup.example"],
                },
            ],
            domain_counts=[{"domain": "dup.example", "row_count": 2}],
        ),
    )

    with pytest.raises(ValueError, match="appears in both"):
        generator.generate_shard_scripts(
            plan_input=plan_input,
            output_dir=tmp_path / "runs",
        )


def test_shard_domain_must_exist_in_domain_counts(tmp_path: Path) -> None:
    plan_input = _write_plan(
        tmp_path,
        _plan(
            shards=[
                {
                    "shard_id": "tier-bc-liveness-01",
                    "domain_count": 1,
                    "row_count": 1,
                    "domains": ["missing.example"],
                },
            ],
            domain_counts=[{"domain": "other.example", "row_count": 1}],
        ),
    )

    with pytest.raises(ValueError, match="missing from domain_counts"):
        generator.generate_shard_scripts(
            plan_input=plan_input,
            output_dir=tmp_path / "runs",
        )


def test_per_host_delay_must_not_exceed_one_request_per_second(tmp_path: Path) -> None:
    plan_input = _write_plan(tmp_path, _plan())

    with pytest.raises(ValueError, match="<= 1.0"):
        generator.generate_shard_scripts(
            plan_input=plan_input,
            output_dir=tmp_path / "runs",
            per_host_delay_sec=1.1,
        )
