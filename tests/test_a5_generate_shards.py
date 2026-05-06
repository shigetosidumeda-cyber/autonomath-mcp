from __future__ import annotations

import csv
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

import generate_source_verification_shards as generator  # noqa: E402

CSV_FIELDS = [
    "shard_id",
    "shard_domain_count",
    "shard_unverified_http_rows",
    "domain",
    "unverified_http_rows",
    "min_id",
    "max_id",
    "lower_bound_seconds_at_1_req_per_sec",
    "dry_run_command",
    "apply_command",
]


def _apply_command(domain: str, *, limit: int) -> str:
    return (
        ".venv/bin/python scripts/etl/backfill_am_source_last_verified.py "
        f"--db autonomath.db --domain {domain} --limit {limit} "
        "--per-host-delay-sec 1.0 --json --apply"
    )


def _row(
    *,
    shard_id: int,
    domain: str,
    unverified_http_rows: int,
    limit: int | None = None,
) -> dict[str, str]:
    limit = unverified_http_rows if limit is None else limit
    return {
        "shard_id": str(shard_id),
        "shard_domain_count": "1",
        "shard_unverified_http_rows": str(unverified_http_rows),
        "domain": domain,
        "unverified_http_rows": str(unverified_http_rows),
        "min_id": "1",
        "max_id": str(unverified_http_rows),
        "lower_bound_seconds_at_1_req_per_sec": str(unverified_http_rows),
        "dry_run_command": "",
        "apply_command": _apply_command(domain, limit=limit),
    }


def _write_inputs(
    tmp_path: Path,
    *,
    rows: list[dict[str, str]],
    threshold: int = 50,
    shards: list[dict[str, Any]] | None = None,
) -> tuple[Path, Path]:
    csv_path = tmp_path / "quick_domains.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    if shards is None:
        grouped: dict[int, list[str]] = {}
        for row in rows:
            grouped.setdefault(int(row["shard_id"]), []).append(row["domain"])
        shards = [
            {"shard_id": shard_id, "domains": domains}
            for shard_id, domains in sorted(grouped.items())
        ]

    json_path = tmp_path / "quick_domains.json"
    json_path.write_text(
        json.dumps(
            {
                "selection": {
                    "threshold_unverified_http_rows_per_domain": threshold,
                },
                "shards": shards,
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return json_path, csv_path


def test_generate_shards_from_temp_csv_json_writes_four_scripts(tmp_path: Path) -> None:
    json_path, csv_path = _write_inputs(
        tmp_path,
        rows=[
            _row(shard_id=1, domain="a.example", unverified_http_rows=2),
            _row(shard_id=1, domain="too-big.example", unverified_http_rows=51),
            _row(shard_id=2, domain="b.example", unverified_http_rows=3),
            _row(shard_id=4, domain="c.example", unverified_http_rows=1),
        ],
    )
    output_dir = tmp_path / "runs"
    repo_root = tmp_path / "repo"

    summary = generator.generate_shard_scripts(
        json_input=json_path,
        csv_input=csv_path,
        output_dir=output_dir,
        repo_root=repo_root,
        generated_at="2026-05-01T00:00:00+00:00",
    )

    assert summary["script_count"] == 4
    assert summary["domain_count"] == 3
    assert summary["unverified_http_rows"] == 6
    assert summary["excluded_over_threshold_domain_count"] == 1

    script_1 = output_dir / "source_verification_shard_1_2026-05-01.sh"
    script_2 = output_dir / "source_verification_shard_2_2026-05-01.sh"
    script_3 = output_dir / "source_verification_shard_3_2026-05-01.sh"
    script_4 = output_dir / "source_verification_shard_4_2026-05-01.sh"

    assert os.access(script_1, os.X_OK)
    text_1 = script_1.read_text(encoding="utf-8")
    assert "set -euo pipefail" in text_1
    assert f"cd {shlex.quote(str(repo_root))}" in text_1
    assert (
        "exec > >(tee analysis_wave18/source_verification_shard_1_2026-05-01.log) 2>&1"
    ) in text_1
    assert "--domain a.example" in text_1
    assert "--limit 2" in text_1
    assert "too-big.example" not in text_1
    assert "--dry-run" not in text_1

    assert "--domain b.example" in script_2.read_text(encoding="utf-8")
    assert "backfill_am_source_last_verified.py" not in script_3.read_text(encoding="utf-8")
    assert "--domain c.example" in script_4.read_text(encoding="utf-8")


def test_duplicate_csv_domain_is_rejected_to_keep_shards_disjoint(
    tmp_path: Path,
) -> None:
    json_path, csv_path = _write_inputs(
        tmp_path,
        rows=[
            _row(shard_id=1, domain="dup.example", unverified_http_rows=2),
            _row(shard_id=2, domain="dup.example", unverified_http_rows=3),
        ],
        shards=[],
    )

    with pytest.raises(ValueError, match="duplicate domain"):
        generator.generate_shard_scripts(
            json_input=json_path,
            csv_input=csv_path,
            output_dir=tmp_path / "runs",
        )


def test_apply_command_limit_must_cover_domain_rows(tmp_path: Path) -> None:
    json_path, csv_path = _write_inputs(
        tmp_path,
        rows=[
            _row(
                shard_id=1,
                domain="short-limit.example",
                unverified_http_rows=5,
                limit=4,
            ),
        ],
    )

    with pytest.raises(ValueError, match="less than unverified_http_rows 5"):
        generator.generate_shard_scripts(
            json_input=json_path,
            csv_input=csv_path,
            output_dir=tmp_path / "runs",
        )


def test_json_csv_shard_mismatch_is_rejected(tmp_path: Path) -> None:
    json_path, csv_path = _write_inputs(
        tmp_path,
        rows=[
            _row(shard_id=2, domain="mismatch.example", unverified_http_rows=1),
        ],
        shards=[{"shard_id": 1, "domains": ["mismatch.example"]}],
    )

    with pytest.raises(ValueError, match="does not match JSON shard_id 1"):
        generator.generate_shard_scripts(
            json_input=json_path,
            csv_input=csv_path,
            output_dir=tmp_path / "runs",
        )
