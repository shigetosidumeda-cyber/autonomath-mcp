"""Tests for the always-emit `claim_refs.jsonl` contract.

Wave 53.x: `claim_refs.jsonl` is now a REQUIRED artifact so the Glue
`claim_refs` table is registered (Athena cross-source big queries fail
without it). The crawler emits a header-only file when no claim refs
were extracted; ETL drops the header row and writes an empty Parquet
partition so the Glue table still gets schema registration.
"""

from __future__ import annotations

import contextlib
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
ENTRYPOINT_PATH = ROOT / "docker" / "jpcite-crawler" / "entrypoint.py"
ETL_PATH = ROOT / "scripts" / "aws_credit_ops" / "etl_raw_to_derived.py"


def _load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        pytest.skip(f"could not load {name} at {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_etl_claim_refs_in_required_artifacts() -> None:
    """`claim_refs` is part of REQUIRED_ARTIFACTS."""
    etl = _load_module("jpcite_etl", ETL_PATH)
    assert "claim_refs" in etl.REQUIRED_ARTIFACTS
    assert "object_manifest" in etl.REQUIRED_ARTIFACTS


def test_etl_claim_refs_header_constant() -> None:
    """ETL exposes the canonical claim_refs header version."""
    etl = _load_module("jpcite_etl", ETL_PATH)
    assert etl._CLAIM_REFS_HEADER_VERSION == "jpcir.p0.v1"


class _FakeS3Body:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def read(self) -> bytes:
        return self._payload


class _FakeS3:
    """Tiny in-memory S3 stub. Stores PUTs for assertion + serves GETs."""

    def __init__(self, files: dict[tuple[str, str], bytes] | None = None) -> None:
        self.files: dict[tuple[str, str], bytes] = dict(files or {})
        self.puts: list[dict[str, Any]] = []

    def get_object(  # noqa: N802 (boto3 API)
        self,
        *,
        Bucket: str,  # noqa: N803 (boto3 API)
        Key: str,  # noqa: N803 (boto3 API)
    ) -> dict[str, Any]:
        key = (Bucket, Key)
        if key not in self.files:
            raise RuntimeError(f"NoSuchKey: s3://{Bucket}/{Key}")
        return {"Body": _FakeS3Body(self.files[key])}

    def put_object(
        self,
        *,
        Bucket: str,  # noqa: N803 (boto3 API)
        Key: str,  # noqa: N803 (boto3 API)
        Body: bytes,  # noqa: N803 (boto3 API)
        ContentType: str = "application/octet-stream",  # noqa: N803 (boto3 API)
    ) -> dict[str, Any]:
        self.puts.append(
            {
                "Bucket": Bucket,
                "Key": Key,
                "Body": Body,
                "ContentType": ContentType,
            }
        )
        self.files[(Bucket, Key)] = Body
        return {}


def test_etl_drops_claim_refs_header_row() -> None:
    """The header sentinel row never lands as a Parquet row."""
    etl = _load_module("jpcite_etl", ETL_PATH)
    payload = (
        json.dumps({"version": "jpcir.p0.v1"}) + "\n"
        + json.dumps(
            {
                "claim_id": "c1",
                "subject_kind": "program",
                "subject_id": "p123",
                "claim_kind": "amount_min",
                "value": "500000",
                "source_receipt_ids": ["sr1"],
                "confidence": "0.9",
            }
        )
        + "\n"
    )
    s3 = _FakeS3({("raw-bkt", "J01_x/claim_refs.jsonl"): payload.encode("utf-8")})
    rows, malformed = etl.read_jsonl_from_s3(
        bucket="raw-bkt", key="J01_x/claim_refs.jsonl", s3_client=s3
    )
    assert malformed == 0
    assert len(rows) == 1
    assert rows[0]["claim_id"] == "c1"


def test_etl_empty_claim_refs_writes_empty_partition() -> None:
    """Header-only claim_refs.jsonl writes an empty Parquet partition."""
    pytest.importorskip("pyarrow")
    etl = _load_module("jpcite_etl", ETL_PATH)
    payload = json.dumps({"version": "jpcir.p0.v1"}) + "\n"
    s3 = _FakeS3({("raw-bkt", "J01_x/claim_refs.jsonl"): payload.encode("utf-8")})
    rep = etl.etl_one_artifact(
        artifact_kind="claim_refs",
        job_prefix="J01_x",
        run_id="20260516T000000Z",
        raw_bucket="raw-bkt",
        derived_bucket="der-bkt",
        dry_run=False,
        s3_client=s3,
    )
    assert rep.status == "empty_partition_written"
    assert rep.derived_uri is not None
    assert "claim_refs/job_prefix=J01_x/run_id=" in rep.derived_uri
    # exactly one PUT to derived bucket for claim_refs
    puts = [p for p in s3.puts if p["Bucket"] == "der-bkt"]
    assert len(puts) == 1
    assert puts[0]["Key"].startswith("claim_refs/job_prefix=J01_x/run_id=")
    assert puts[0]["Key"].endswith("/data.parquet")


def test_etl_missing_claim_refs_writes_empty_partition() -> None:
    """When raw claim_refs.jsonl is truly absent, write an empty partition.

    Older crawler runs (pre-Wave-53.x) did not emit claim_refs.jsonl at
    all. The required-artifact contract now produces an empty partition
    so Glue table registration still succeeds for back-fills.
    """
    pytest.importorskip("pyarrow")
    etl = _load_module("jpcite_etl", ETL_PATH)
    s3 = _FakeS3({})
    rep = etl.etl_one_artifact(
        artifact_kind="claim_refs",
        job_prefix="J02_old",
        run_id="20260101T000000Z",
        raw_bucket="raw-bkt",
        derived_bucket="der-bkt",
        dry_run=False,
        s3_client=s3,
    )
    assert rep.status == "missing_in_raw_empty_partition_written"
    puts = [p for p in s3.puts if p["Bucket"] == "der-bkt"]
    assert len(puts) == 1
    assert puts[0]["Key"].startswith("claim_refs/job_prefix=J02_old/run_id=")


def test_etl_known_gaps_still_optional() -> None:
    """`known_gaps` remains optional — missing raw should not emit a partition."""
    etl = _load_module("jpcite_etl", ETL_PATH)
    assert "known_gaps" not in etl.REQUIRED_ARTIFACTS
    s3 = _FakeS3({})
    rep = etl.etl_one_artifact(
        artifact_kind="known_gaps",
        job_prefix="J03_x",
        run_id="r1",
        raw_bucket="raw-bkt",
        derived_bucket="der-bkt",
        dry_run=False,
        s3_client=s3,
    )
    assert rep.status == "missing_in_raw"
    assert s3.puts == []


def test_entrypoint_emits_empty_claim_refs(tmp_path: Path) -> None:
    """`_emit_artifacts` always writes claim_refs.jsonl with header line.

    Even when there are zero successful results and zero malformed
    targets, the file must exist on disk and contain the header.
    """
    # The docker entrypoint imports flat-style ``crawl`` / ``manifest``
    # because inside the container they live alongside in /app/.
    # Inject the docker dir on sys.path for the duration of the import.
    docker_dir = str(ENTRYPOINT_PATH.parent)
    inserted = False
    if docker_dir not in sys.path:
        sys.path.insert(0, docker_dir)
        inserted = True
    try:
        ep = _load_module("jpcite_entrypoint_for_claim_refs", ENTRYPOINT_PATH)
    finally:
        if inserted:
            with contextlib.suppress(ValueError):
                sys.path.remove(docker_dir)

    out_dir = tmp_path / "out"
    out_dir.mkdir()
    ctx = ep.manifest.JobContext(
        run_id="r1",
        job_id="j1",
        source_id="src1",
        output_bucket="out-bkt",
        output_prefix="runs/r1/j1",
    )
    policy = ep.crawl.SourcePolicy(
        source_id="src1",
        publisher="pub",
        license_boundary="derived_fact",
        respect_robots=True,
        user_agent="test/1.0",
        request_delay_seconds=0.0,
        max_retries=0,
        timeout_seconds=1.0,
    )

    summary = ep._emit_artifacts(ctx, policy, [], out_dir, malformed_targets=None)
    assert "accepted_count" in summary

    claim_refs = out_dir / "claim_refs.jsonl"
    assert claim_refs.is_file(), "claim_refs.jsonl must always be emitted"
    contents = claim_refs.read_text(encoding="utf-8").splitlines()
    assert len(contents) == 1
    parsed = json.loads(contents[0])
    assert parsed == {"version": "jpcir.p0.v1"}
