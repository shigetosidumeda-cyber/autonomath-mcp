"""Tests for ``scripts/aws_credit_ops/aggregate_run_ledger.py``.

The aggregator is mocked against an in-memory ``FakeS3Client`` +
``FakeCostExplorerClient`` so the tests never touch real AWS. The module
itself defers ``boto3`` import to ``main()`` so ``import
aggregate_run_ledger`` works without the SDK installed.

Coverage targets (~15 tests):

* helpers (hash / line-count / parse) — pure functions
* known_gaps histogram (7-enum)
* gap_penalty cap at 0.30
* coverage_score grade thresholds
* per-source-family bucketing
* S3 prefix discovery with missing prefixes
* fetch_artifact_payload handles missing keys gracefully
* aggregate_for_job round-trips fixtures into a PerJobLedger
* build_ledger sums account-wide totals
* Cost Explorer best-effort behavior
* CLI parsing + DRY_RUN default
* Optional --upload flow + put_object payload contents
* Parquet/derived export flag wiring

Wave 50 Stream supplement (2026-05-16). ``[lane:solo]``.
"""

from __future__ import annotations

import importlib.util
import io
import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

# Load the script as a module (it lives under scripts/, not in the
# package import path).
_REPO_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT_PATH = _REPO_ROOT / "scripts" / "aws_credit_ops" / "aggregate_run_ledger.py"
_SPEC = importlib.util.spec_from_file_location(
    "aggregate_run_ledger",
    _SCRIPT_PATH,
)
assert _SPEC is not None
assert _SPEC.loader is not None
agg = importlib.util.module_from_spec(_SPEC)
sys.modules["aggregate_run_ledger"] = agg
_SPEC.loader.exec_module(agg)


# ---------------------------------------------------------------------------
# Fixtures: in-memory S3 + Cost Explorer
# ---------------------------------------------------------------------------


class _FakeS3NoSuchKeyError(Exception):
    """Botocore-shaped NoSuchKey exception used by ``FakeS3Client``."""

    response = {"Error": {"Code": "NoSuchKey"}}


class FakeS3Client:
    """Minimal boto3-shaped S3 client backed by an in-memory dict."""

    def __init__(self, objects: dict[str, bytes]) -> None:
        # objects maps "bucket/key" -> bytes
        self.objects = dict(objects)
        self.put_calls: list[dict[str, Any]] = []

    def list_objects_v2(  # noqa: N803 -- boto3-shaped kwargs
        self,
        *,
        Bucket: str,
        Prefix: str,
        Delimiter: str = "/",
        MaxKeys: int = 1000,
    ) -> dict[str, Any]:
        prefixes: set[str] = set()
        contents: list[dict[str, Any]] = []
        for full_key in self.objects:
            if not full_key.startswith(f"{Bucket}/"):
                continue
            key = full_key[len(Bucket) + 1 :]
            if not key.startswith(Prefix):
                continue
            remainder = key[len(Prefix) :]
            if Delimiter and Delimiter in remainder:
                head = remainder.split(Delimiter, 1)[0]
                prefixes.add(f"{Prefix}{head}{Delimiter}")
            else:
                contents.append({"Key": key})
        response: dict[str, Any] = {}
        if contents[:MaxKeys]:
            response["Contents"] = contents[:MaxKeys]
        if prefixes:
            response["CommonPrefixes"] = [
                {"Prefix": p} for p in sorted(prefixes)
            ]
        return response

    def get_object(self, *, Bucket: str, Key: str) -> dict[str, Any]:  # noqa: N803
        full = f"{Bucket}/{Key}"
        if full not in self.objects:
            raise _FakeS3NoSuchKeyError(f"NoSuchKey: {full}")
        return {"Body": io.BytesIO(self.objects[full])}

    def put_object(  # noqa: N803 -- boto3-shaped kwargs
        self,
        *,
        Bucket: str,
        Key: str,
        Body: bytes,
        ContentType: str = "",
        ServerSideEncryption: str = "",
    ) -> dict[str, Any]:
        full = f"{Bucket}/{Key}"
        self.objects[full] = Body
        self.put_calls.append(
            {
                "Bucket": Bucket,
                "Key": Key,
                "Body": Body,
                "ContentType": ContentType,
                "ServerSideEncryption": ServerSideEncryption,
            }
        )
        return {}


class FakeCostExplorerClient:
    """Minimal Cost Explorer client returning a configured monthly cost."""

    def __init__(self, amounts: list[str] | None = None) -> None:
        self.amounts = amounts if amounts is not None else ["1234.56"]
        self.calls: list[dict[str, Any]] = []

    def get_cost_and_usage(  # noqa: N803 -- boto3-shaped kwargs
        self,
        *,
        TimePeriod: dict[str, str],
        Granularity: str,
        Metrics: list[str],
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "TimePeriod": TimePeriod,
                "Granularity": Granularity,
                "Metrics": Metrics,
            }
        )
        return {
            "ResultsByTime": [
                {
                    "TimePeriod": TimePeriod,
                    "Total": {
                        "NetUnblendedCost": {"Amount": amt, "Unit": "USD"},
                    },
                }
                for amt in self.amounts
            ],
        }


# ---------------------------------------------------------------------------
# Fixture builder for a job_id directory
# ---------------------------------------------------------------------------


def _make_job_fixture(
    *,
    bucket: str,
    job: str,
    run_manifest: dict[str, Any],
    source_receipts: list[dict[str, Any]],
    claim_refs: list[dict[str, Any]],
    known_gaps: list[dict[str, Any]],
    object_manifest: list[dict[str, Any]] | None = None,
    quarantine: list[dict[str, Any]] | None = None,
) -> dict[str, bytes]:
    """Return ``{bucket/key: bytes}`` for a full 6-file artifact set."""

    def _jsonl(rows: list[dict[str, Any]]) -> bytes:
        return ("\n".join(json.dumps(r) for r in rows) + "\n").encode("utf-8")

    base = f"{bucket}/{job}/"
    return {
        f"{base}run_manifest.json": json.dumps(run_manifest).encode("utf-8"),
        f"{base}object_manifest.jsonl": _jsonl(object_manifest or []),
        f"{base}source_receipts.jsonl": _jsonl(source_receipts),
        f"{base}claim_refs.jsonl": _jsonl(claim_refs),
        f"{base}known_gaps.jsonl": _jsonl(known_gaps),
        f"{base}quarantine.jsonl": _jsonl(quarantine or []),
    }


# ---------------------------------------------------------------------------
# Pure-function tests
# ---------------------------------------------------------------------------


def test_hash_payload_returns_known_sha256() -> None:
    assert agg.hash_payload(b"") == (
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    )
    assert agg.hash_payload(b"abc") == (
        "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    )


def test_count_jsonl_lines_skips_blanks() -> None:
    assert agg.count_jsonl_lines(b"") == 0
    assert agg.count_jsonl_lines(b"\n\n") == 0
    payload = b'{"a":1}\n\n{"b":2}\n'
    assert agg.count_jsonl_lines(payload) == 2


def test_parse_jsonl_skips_blank_lines() -> None:
    payload = b'{"x":1}\n\n{"y":"z"}\n'
    rows = agg.parse_jsonl(payload)
    assert rows == [{"x": 1}, {"y": "z"}]


def test_known_gaps_histogram_seven_enum() -> None:
    rows = [
        {"code": "csv_input_not_evidence_safe"},
        {"code": "csv_input_not_evidence_safe"},
        {"code": "no_hit_not_absence"},
        {"code": "unknown_code_should_be_ignored"},
    ]
    counts = agg.known_gaps_histogram(rows)
    assert set(counts.keys()) == set(agg.KNOWN_GAP_CODES)
    assert counts["csv_input_not_evidence_safe"] == 2
    assert counts["no_hit_not_absence"] == 1
    assert counts["professional_review_required"] == 0


def test_gap_penalty_capped_at_thirty() -> None:
    huge = {
        "csv_input_not_evidence_safe": 100,
        "source_receipt_incomplete": 100,
        "identity_ambiguity_unresolved": 100,
    }
    assert agg.compute_gap_penalty(huge) == 0.30
    none = dict.fromkeys(agg.KNOWN_GAP_CODES, 0)
    assert agg.compute_gap_penalty(none) == 0.0


def test_grade_coverage_thresholds() -> None:
    assert agg.grade_coverage(0.95, 0) == "S"
    assert agg.grade_coverage(0.95, 1) == "A"  # critical gap demotes S->A
    assert agg.grade_coverage(0.85, 0) == "A"
    assert agg.grade_coverage(0.70, 0) == "B"
    assert agg.grade_coverage(0.50, 0) == "C"
    assert agg.grade_coverage(0.10, 0) == "D"


def test_bucket_for_source_routes_known_families() -> None:
    assert agg._bucket_for_source("egov_law") == "egov_law"
    assert agg._bucket_for_source("nta_invoice_publication") == "nta_invoice"
    assert agg._bucket_for_source("gbizinfo_houjin") == "gbizinfo"
    assert agg._bucket_for_source("jgrants_subsidy_portal") == "jgrants"
    assert agg._bucket_for_source("nta_houjin") == "nta_houjin"
    assert agg._bucket_for_source("mhlw_labor") == "ministry_pdf"
    assert agg._bucket_for_source("random_unmapped") == "other"


def test_compute_coverage_breakdown_high_quality_inputs() -> None:
    receipts = [
        {
            "verification_status": "verified",
            "sourced_fact_count": 10,
            "required_fact_count": 10,
            "observed_fact_count": 10,
            "age_days": 0,
        },
        {
            "verification_status": "verified",
            "sourced_fact_count": 8,
            "required_fact_count": 10,
            "observed_fact_count": 10,
            "age_days": 30,
        },
    ]
    claims = [{"source_receipt_id": "sr_1"}, {"source_url": "https://x"}]
    gaps: list[dict[str, Any]] = []
    manifest = {"accepted_artifact_count": 9, "total_artifact_count": 10}
    breakdown = agg.compute_coverage_breakdown(
        source_receipts=receipts,
        claim_refs=claims,
        known_gaps=gaps,
        run_manifest=manifest,
    )
    assert breakdown.coverage_grade in {"S", "A"}
    assert breakdown.coverage_score > 0.6
    assert breakdown.gap_penalty == 0.0
    assert 0.0 <= breakdown.fact_coverage_mean <= 1.0
    assert 0.0 <= breakdown.citation_coverage <= 1.0


# ---------------------------------------------------------------------------
# Adapter tests (S3 + Cost Explorer)
# ---------------------------------------------------------------------------


def test_list_job_prefixes_discovers_only_present_prefixes() -> None:
    bucket = "jpcite-credit-993693061769-202605-raw"
    objects = {
        f"{bucket}/J01/run_manifest.json": b"{}",
        f"{bucket}/J03/run_manifest.json": b"{}",
        f"{bucket}/J05/run_manifest.json": b"{}",
    }
    s3 = FakeS3Client(objects)
    prefixes = agg.list_job_prefixes(s3, raw_bucket=bucket)
    assert prefixes == ["J01/", "J03/", "J05/"]


def test_fetch_artifact_payload_returns_none_on_missing_key() -> None:
    bucket = "jpcite-credit-993693061769-202605-raw"
    objects = {f"{bucket}/J01/run_manifest.json": b'{"k":1}'}
    s3 = FakeS3Client(objects)
    assert agg.fetch_artifact_payload(
        s3, bucket=bucket, key="J01/run_manifest.json"
    ) == b'{"k":1}'
    assert (
        agg.fetch_artifact_payload(s3, bucket=bucket, key="J01/missing.jsonl")
        is None
    )


def test_aggregate_for_job_builds_per_job_ledger() -> None:
    bucket = "jpcite-credit-993693061769-202605-raw"
    objects = _make_job_fixture(
        bucket=bucket,
        job="J04",
        run_manifest={
            "accepted_artifact_count": 8,
            "total_artifact_count": 10,
        },
        source_receipts=[
            {
                "source_url": "https://elaws.e-gov.go.jp/document?lawid=1",
                "source_id": "egov_law",
                "verification_status": "verified",
                "sourced_fact_count": 5,
                "required_fact_count": 5,
                "age_days": 1,
            }
        ],
        claim_refs=[{"source_receipt_id": "sr_1"}],
        known_gaps=[
            {"code": "freshness_stale_or_unknown"},
            {"code": "no_hit_not_absence"},
        ],
        object_manifest=[
            {"source_url": "https://elaws.e-gov.go.jp/document?lawid=1"},
            {"source_url": "https://elaws.e-gov.go.jp/document?lawid=2"},
        ],
    )
    s3 = FakeS3Client(objects)
    rollup = agg.aggregate_for_job(s3, raw_bucket=bucket, job_prefix="J04/")
    assert rollup.job_id == "J04"
    assert rollup.prefix == "J04/"
    assert rollup.total_source_count == 2  # 2 distinct URLs in object_manifest
    assert rollup.total_claim_refs == 1
    assert rollup.total_known_gaps_by_code["freshness_stale_or_unknown"] == 1
    assert rollup.total_known_gaps_by_code["no_hit_not_absence"] == 1
    assert rollup.accepted_artifact_rate == pytest.approx(0.8)
    # Every artifact should be present.
    assert all(a.present for a in rollup.artifacts)
    # egov_law bucket should have a > 0 coverage_score.
    assert rollup.coverage_score_per_source_family["egov_law"] > 0


def test_aggregate_for_job_handles_missing_artifacts() -> None:
    bucket = "jpcite-credit-993693061769-202605-raw"
    # Only run_manifest present; all others missing.
    objects = {
        f"{bucket}/J05/run_manifest.json": json.dumps(
            {"accepted_artifact_count": 0, "total_artifact_count": 0}
        ).encode("utf-8"),
    }
    s3 = FakeS3Client(objects)
    rollup = agg.aggregate_for_job(s3, raw_bucket=bucket, job_prefix="J05/")
    present_files = {a.filename for a in rollup.artifacts if a.present}
    assert present_files == {"run_manifest.json"}
    missing_files = {a.filename for a in rollup.artifacts if not a.present}
    assert missing_files == {
        "object_manifest.jsonl",
        "source_receipts.jsonl",
        "claim_refs.jsonl",
        "known_gaps.jsonl",
        "quarantine.jsonl",
    }
    assert rollup.total_source_count == 0
    assert rollup.total_claim_refs == 0
    assert rollup.accepted_artifact_rate == 0.0


def test_fetch_cost_explorer_total_sums_daily_amounts() -> None:
    ce = FakeCostExplorerClient(amounts=["100.50", "250.25", "49.25"])
    total = agg.fetch_cost_explorer_total(ce, run_start_at="2026-05-15T00:00:00Z")
    assert total == pytest.approx(400.00)
    assert ce.calls[0]["TimePeriod"]["Start"] == "2026-05-15"
    assert ce.calls[0]["Metrics"] == ["NetUnblendedCost"]


def test_fetch_cost_explorer_total_swallows_exceptions() -> None:
    ce = MagicMock()
    ce.get_cost_and_usage.side_effect = RuntimeError("boom")
    total = agg.fetch_cost_explorer_total(ce, run_start_at="2026-05-15T00:00:00Z")
    assert total == 0.0


def test_build_ledger_sums_account_wide_rollups() -> None:
    bucket = "jpcite-credit-993693061769-202605-raw"
    objects: dict[str, bytes] = {}
    objects.update(
        _make_job_fixture(
            bucket=bucket,
            job="J01",
            run_manifest={
                "accepted_artifact_count": 5,
                "total_artifact_count": 5,
            },
            source_receipts=[
                {"source_url": "https://a", "source_id": "egov_law"},
            ],
            claim_refs=[{"source_receipt_id": "sr_a"}],
            known_gaps=[{"code": "no_hit_not_absence"}],
        )
    )
    objects.update(
        _make_job_fixture(
            bucket=bucket,
            job="J03",
            run_manifest={
                "accepted_artifact_count": 3,
                "total_artifact_count": 5,
            },
            source_receipts=[
                {"source_url": "https://b", "source_id": "nta_invoice"},
                {"source_url": "https://c", "source_id": "nta_invoice"},
            ],
            claim_refs=[
                {"source_receipt_id": "sr_b"},
                {"source_receipt_id": "sr_c"},
            ],
            known_gaps=[
                {"code": "freshness_stale_or_unknown"},
                {"code": "professional_review_required"},
            ],
        )
    )
    s3 = FakeS3Client(objects)
    ce = FakeCostExplorerClient(amounts=["1000.00"])
    ledger = agg.build_ledger(
        s3,
        ce,
        raw_bucket=bucket,
        reports_bucket="reports",
        run_start_at="2026-05-15T00:00:00Z",
    )
    assert len(ledger.jobs) == 2
    assert ledger.total_credit_consumed_usd == pytest.approx(1000.00)
    assert ledger.total_source_count_account_wide == 3
    assert ledger.total_claim_refs_account_wide == 3
    assert (
        ledger.total_known_gaps_by_code_account_wide["no_hit_not_absence"] == 1
    )
    assert (
        ledger.total_known_gaps_by_code_account_wide[
            "freshness_stale_or_unknown"
        ]
        == 1
    )
    assert ledger.account_id == agg.AWS_ACCOUNT_ID
    assert ledger.schema_version == agg.LEDGER_SCHEMA_VERSION
    # Average of 1.0 and 0.6 is 0.8.
    assert ledger.accepted_artifact_rate_account_wide == pytest.approx(0.8)


# ---------------------------------------------------------------------------
# CLI tests
# ---------------------------------------------------------------------------


def test_parse_args_defaults_to_dry_run() -> None:
    args = agg.parse_args([])
    assert args.upload is False
    assert args.export_parquet is False
    assert args.raw_bucket == agg.DEFAULT_RAW_BUCKET
    assert args.reports_bucket == agg.DEFAULT_REPORTS_BUCKET
    assert args.cost_explorer_region == "us-east-1"


def test_parse_args_accepts_upload_flag() -> None:
    args = agg.parse_args(["--upload", "--export-parquet"])
    assert args.upload is True
    assert args.export_parquet is True


def test_print_summary_writes_human_readable_lines() -> None:
    bucket = "raw"
    objects = _make_job_fixture(
        bucket=bucket,
        job="J02",
        run_manifest={
            "accepted_artifact_count": 4,
            "total_artifact_count": 5,
        },
        source_receipts=[{"source_url": "u", "source_id": "nta_houjin"}],
        claim_refs=[],
        known_gaps=[],
    )
    s3 = FakeS3Client(objects)
    ce = FakeCostExplorerClient(amounts=["42.00"])
    ledger = agg.build_ledger(
        s3,
        ce,
        raw_bucket=bucket,
        reports_bucket="reports",
        run_start_at="2026-05-15T00:00:00Z",
    )
    buf = io.StringIO()
    agg.print_summary(ledger, stream=buf)
    text = buf.getvalue()
    assert "jpcite credit-run ledger summary" in text
    assert "jobs_discovered        : 1" in text
    assert "total_credit_usd       : 42.00" in text
    assert "J02" in text


def test_main_dry_run_writes_local_ledger_without_upload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    bucket = "raw"
    objects = _make_job_fixture(
        bucket=bucket,
        job="J01",
        run_manifest={"accepted_artifact_count": 1, "total_artifact_count": 1},
        source_receipts=[{"source_url": "u", "source_id": "egov_law"}],
        claim_refs=[],
        known_gaps=[],
    )
    s3 = FakeS3Client(objects)
    ce = FakeCostExplorerClient(amounts=["7.00"])

    fake_boto3 = MagicMock()
    fake_boto3.client.side_effect = (
        lambda service, region_name=None: s3 if service == "s3" else ce
    )
    monkeypatch.setattr(agg, "_import_boto3", lambda: fake_boto3)

    out_path = tmp_path / "ledger.json"
    exit_code = agg.main(
        [
            "--raw-bucket",
            bucket,
            "--reports-bucket",
            "reports",
            "--out",
            str(out_path),
        ]
    )
    assert exit_code == 0
    assert out_path.exists()
    loaded = json.loads(out_path.read_text(encoding="utf-8"))
    assert loaded["schema_version"] == agg.LEDGER_SCHEMA_VERSION
    assert loaded["raw_bucket"] == bucket
    assert s3.put_calls == []  # DRY_RUN: no upload
    captured = capsys.readouterr()
    assert "jpcite credit-run ledger summary" in captured.out


def test_main_upload_pushes_to_reports_bucket(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bucket = "raw"
    objects = _make_job_fixture(
        bucket=bucket,
        job="J07",
        run_manifest={"accepted_artifact_count": 2, "total_artifact_count": 2},
        source_receipts=[
            {"source_url": "https://gbiz", "source_id": "gbizinfo_houjin"}
        ],
        claim_refs=[],
        known_gaps=[],
    )
    s3 = FakeS3Client(objects)
    ce = FakeCostExplorerClient(amounts=["11.00"])

    fake_boto3 = MagicMock()
    fake_boto3.client.side_effect = (
        lambda service, region_name=None: s3 if service == "s3" else ce
    )
    monkeypatch.setattr(agg, "_import_boto3", lambda: fake_boto3)

    out_path = tmp_path / "ledger.json"
    exit_code = agg.main(
        [
            "--raw-bucket",
            bucket,
            "--reports-bucket",
            "reports",
            "--out",
            str(out_path),
            "--upload",
            "--export-parquet",
            "--derived-bucket",
            "derived",
        ]
    )
    assert exit_code == 0
    upload_keys = [c["Key"] for c in s3.put_calls]
    assert "ledger/credit_run_ledger_2026_05.json" in upload_keys
    assert "derived/credit_run_ledger_2026_05_per_job.jsonl" in upload_keys
    # Ledger upload Bucket must be reports-bucket.
    ledger_call = next(
        c for c in s3.put_calls if c["Key"].startswith("ledger/")
    )
    assert ledger_call["Bucket"] == "reports"
    assert ledger_call["ContentType"] == "application/json"
    assert ledger_call["ServerSideEncryption"] == "AES256"
    payload = json.loads(ledger_call["Body"].decode("utf-8"))
    assert payload["schema_version"] == agg.LEDGER_SCHEMA_VERSION
    # Derived upload Bucket must be derived-bucket.
    derived_call = next(
        c for c in s3.put_calls if c["Key"].startswith("derived/")
    )
    assert derived_call["Bucket"] == "derived"
    assert derived_call["ContentType"] == "application/x-ndjson"
