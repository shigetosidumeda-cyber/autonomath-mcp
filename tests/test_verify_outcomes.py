"""Unit tests for ``scripts/verify_outcomes.py``.

Covers:
* loader — reads + validates assertion JSON files into ``AssertionSpec``.
* runner — verifies sampled packets against a mocked S3 client.
* ledger — JSON-Lines format with metadata + summary + per-packet rows.

All tests run **offline** — boto3 is fully mocked. No LLM, no network.

``[lane:solo]`` marker per CLAUDE.md dual-CLI lane convention.
"""

from __future__ import annotations

import importlib.util
import io
import json
import random
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_verify_outcomes_module() -> Any:
    """Import ``scripts/verify_outcomes.py`` as a module."""

    path = REPO_ROOT / "scripts" / "verify_outcomes.py"
    spec = importlib.util.spec_from_file_location("verify_outcomes", path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    # Register in sys.modules BEFORE exec_module so dataclass(frozen=True)
    # can resolve ``cls.__module__`` for KW_ONLY type checks.
    sys.modules["verify_outcomes"] = module
    spec.loader.exec_module(module)
    return module


verify_outcomes = _load_verify_outcomes_module()


def _good_envelope(
    *,
    package_id: str = "company_public_baseline_v1:0100001221097",
    package_kind: str = "company_public_baseline_v1",
    extra_size_padding: int = 0,
    fresh_days_ago: int = 1,
) -> dict[str, Any]:
    """Build a JPCIR envelope that passes all 5 assertions."""

    generated_at = (
        datetime.now(tz=UTC) - timedelta(days=fresh_days_ago)
    ).isoformat(timespec="seconds")
    envelope: dict[str, Any] = {
        "object_id": package_id,
        "object_type": "packet",
        "created_at": generated_at,
        "producer": "jpcite-ai-execution-control-plane",
        "request_time_llm_call_performed": False,
        "schema_version": "jpcir.p0.v1",
        "package_id": package_id,
        "package_kind": package_kind,
        "generated_at": generated_at,
        "extracted_at": generated_at,
        "cohort_definition": {"cohort_id": "demo"},
        "metrics": {"x": 1},
        "sources": [
            {
                "source_url": "https://www.nta.go.jp/example",
                "source_fetched_at": generated_at,
                "publisher": "国税庁",
                "license": "pdl_v1.0",
            }
        ],
        "known_gaps": [
            {
                "code": "professional_review_required",
                "description": "scaffold only",
            }
        ],
        "jpcite_cost_jpy": 0,
        "disclaimer": "no LLM inference.",
    }
    if extra_size_padding > 0:
        envelope["padding"] = "x" * extra_size_padding
    return envelope


class FakeS3Client:
    """Minimal in-memory boto3 S3 client replacement."""

    def __init__(self, objects: dict[str, bytes]) -> None:
        self.objects = objects

    def get_paginator(self, op_name: str) -> FakeS3Paginator:
        assert op_name == "list_objects_v2"
        return FakeS3Paginator(self.objects)

    def download_fileobj(self, bucket: str, key: str, buf: io.BytesIO) -> None:
        assert bucket == "fake-bucket"
        buf.write(self.objects[key])


class FakeS3Paginator:
    def __init__(self, objects: dict[str, bytes]) -> None:
        self.objects = objects

    def paginate(self, *, Bucket: str, Prefix: str) -> Any:  # noqa: N803
        contents = [
            {"Key": key} for key in self.objects if key.startswith(Prefix)
        ]
        yield {"Contents": contents}


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


def test_loader_reads_all_top10_assertions() -> None:
    specs = verify_outcomes.load_assertion_specs(
        REPO_ROOT / "data" / "outcome_assertions"
    )
    assert len(specs) == 10
    ids = sorted(s.outcome_id for s in specs)
    assert "application_strategy" in ids
    assert "evidence_answer" in ids
    assert "source_receipt_ledger" in ids
    # every spec must have the 5-assertion DSL
    for spec in specs:
        assert len(spec.assertions) == 5
        assert spec.expected_price_jpy in {300, 600, 900}


def test_loader_raises_on_missing_dir(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        verify_outcomes.load_assertion_specs(tmp_path / "does-not-exist")


# ---------------------------------------------------------------------------
# Runner — mocked S3
# ---------------------------------------------------------------------------


def _build_packets(
    prefix: str, n: int = 12, *, all_good: bool = True
) -> dict[str, bytes]:
    out: dict[str, bytes] = {}
    for i in range(n):
        env = _good_envelope(
            package_id=f"{prefix.rstrip('/')}:demo-{i:04d}",
            package_kind=prefix.rstrip("/"),
        )
        if not all_good and i == 0:
            # poison one envelope so the failure path is exercised
            env["request_time_llm_call_performed"] = True
        out[f"{prefix}{prefix.rstrip('/')}:demo-{i:04d}.json"] = json.dumps(
            env, ensure_ascii=False
        ).encode("utf-8")
    return out


def test_runner_all_pass_against_mock_s3() -> None:
    spec = verify_outcomes.AssertionSpec(
        outcome_id="application_strategy",
        assertions=(
            "schema_present",
            "known_gaps_valid",
            "packet_size_within_band",
            "citation_uri_valid",
            "packet_freshness",
        ),
        expected_price_jpy=900,
    )
    packets = _build_packets("application_strategy_v1/", n=12, all_good=True)
    s3 = FakeS3Client(packets)
    report, verifications = verify_outcomes.verify_outcome(
        spec=spec,
        s3_client=s3,
        bucket="fake-bucket",
        sample_size=10,
        list_cap=100,
        rng=random.Random(7),
    )
    assert report.sampled == 10
    assert report.failed == 0
    assert report.passed == 10
    assert report.skipped is False
    assert report.all_passed is True
    assert all(v.all_passed for v in verifications)


def test_runner_detects_failure() -> None:
    spec = verify_outcomes.AssertionSpec(
        outcome_id="application_strategy",
        assertions=(
            "schema_present",
            "known_gaps_valid",
            "packet_size_within_band",
            "citation_uri_valid",
            "packet_freshness",
        ),
        expected_price_jpy=900,
    )
    packets = _build_packets("application_strategy_v1/", n=12, all_good=False)
    s3 = FakeS3Client(packets)
    # seed=0 ensures the poisoned key (index 0) is in the sample of 10
    report, _verifications = verify_outcomes.verify_outcome(
        spec=spec,
        s3_client=s3,
        bucket="fake-bucket",
        sample_size=12,  # take all → poisoned packet guaranteed sampled
        list_cap=100,
        rng=random.Random(0),
    )
    assert report.sampled == 12
    assert report.failed >= 1
    assert report.all_passed is False


def test_runner_skips_unmapped_outcome() -> None:
    spec = verify_outcomes.AssertionSpec(
        outcome_id="evidence_answer",
        assertions=(
            "schema_present",
            "known_gaps_valid",
            "packet_size_within_band",
            "citation_uri_valid",
            "packet_freshness",
        ),
        expected_price_jpy=600,
    )
    report, verifications = verify_outcomes.verify_outcome(
        spec=spec,
        s3_client=FakeS3Client({}),
        bucket="fake-bucket",
        sample_size=10,
        list_cap=100,
        rng=random.Random(1),
    )
    assert report.skipped is True
    assert report.skip_reason == "no_prefix_mapped"
    assert verifications == []


def test_runner_skips_source_receipt_parquet() -> None:
    spec = verify_outcomes.AssertionSpec(
        outcome_id="source_receipt_ledger",
        assertions=(
            "schema_present",
            "known_gaps_valid",
            "packet_size_within_band",
            "citation_uri_valid",
            "packet_freshness",
        ),
        expected_price_jpy=600,
    )
    report, _verifications = verify_outcomes.verify_outcome(
        spec=spec,
        s3_client=FakeS3Client({}),
        bucket="fake-bucket",
        sample_size=10,
        list_cap=100,
        rng=random.Random(2),
    )
    assert report.skipped is True
    assert "parquet" in report.skip_reason


def test_runner_skips_when_no_packets_in_prefix() -> None:
    spec = verify_outcomes.AssertionSpec(
        outcome_id="application_strategy",
        assertions=("schema_present",),
        expected_price_jpy=900,
    )
    report, _ = verify_outcomes.verify_outcome(
        spec=spec,
        s3_client=FakeS3Client({}),
        bucket="fake-bucket",
        sample_size=10,
        list_cap=100,
        rng=random.Random(3),
    )
    assert report.skipped is True
    assert report.skip_reason == "no_packets_in_prefix"


# ---------------------------------------------------------------------------
# Ledger format
# ---------------------------------------------------------------------------


def test_ledger_writes_metadata_summary_and_packet_rows(tmp_path: Path) -> None:
    spec = verify_outcomes.AssertionSpec(
        outcome_id="application_strategy",
        assertions=(
            "schema_present",
            "known_gaps_valid",
            "packet_size_within_band",
            "citation_uri_valid",
            "packet_freshness",
        ),
        expected_price_jpy=900,
    )
    packets = _build_packets("application_strategy_v1/", n=3, all_good=True)
    s3 = FakeS3Client(packets)
    report, verifications = verify_outcomes.verify_outcome(
        spec=spec,
        s3_client=s3,
        bucket="fake-bucket",
        sample_size=3,
        list_cap=100,
        rng=random.Random(11),
    )
    out_path = tmp_path / "ledger.jsonl"
    verify_outcomes.write_ledger(
        out_path=out_path,
        reports=[report],
        verifications=verifications,
        run_metadata={
            "timestamp_utc": datetime.now(tz=UTC).isoformat(),
            "bucket": "fake-bucket",
            "sample_size": 3,
            "dry_run": False,
            "specs_count": 1,
        },
    )
    lines = out_path.read_text(encoding="utf-8").splitlines()
    # 1 metadata + 1 outcome_summary + 3 packet_verification rows
    assert len(lines) == 5
    rows = [json.loads(line) for line in lines]
    assert rows[0]["row_kind"] == "metadata"
    assert rows[0]["bucket"] == "fake-bucket"
    assert rows[1]["row_kind"] == "outcome_summary"
    assert rows[1]["outcome_id"] == "application_strategy"
    assert rows[1]["sampled"] == 3
    assert rows[1]["all_passed"] is True
    for row in rows[2:]:
        assert row["row_kind"] == "packet_verification"
        assert row["outcome_id"] == "application_strategy"
        assert row["all_passed"] is True
        assert isinstance(row["results"], list)
        assert len(row["results"]) == 5


def test_dry_run_main_writes_skipped_ledger(tmp_path: Path) -> None:
    out_dir = tmp_path / "out"
    rc = verify_outcomes.main(
        [
            "--assertion-dir",
            str(REPO_ROOT / "data" / "outcome_assertions"),
            "--out-dir",
            str(out_dir),
            "--bucket",
            "fake-bucket",
            "--sample-size",
            "5",
            "--dry-run",
            "--quiet",
        ]
    )
    assert rc == 0
    ledgers = sorted(out_dir.glob("outcome_verifier_ledger_*.jsonl"))
    assert len(ledgers) == 1
    lines = ledgers[0].read_text(encoding="utf-8").splitlines()
    assert lines, "dry-run ledger should not be empty"
    head = json.loads(lines[0])
    assert head["row_kind"] == "metadata"
    assert head["dry_run"] is True
    # all 10 outcomes appear as skipped(reason=dry_run) summaries
    summary_rows = [
        json.loads(line)
        for line in lines
        if json.loads(line)["row_kind"] == "outcome_summary"
    ]
    assert len(summary_rows) == 10
    assert all(row["skipped"] for row in summary_rows)
    assert all(row["skip_reason"] == "dry_run" for row in summary_rows)
