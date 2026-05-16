"""Tests for ``scripts.aws_credit_ops.sagemaker_embed_batch``.

All boto3 + SageMaker calls are mocked. No live AWS, no real S3 access.
The tests cover:

* Model allow-list validation (known models accepted, unknown rejected).
* IAM execution role ARN shape validation.
* SageMaker model name shape validation.
* Budget gate (warn / stop, projected spend rollup).
* DRY_RUN path (no SageMaker call, no S3 manifest write).
* Real-path SageMaker drive (mocked ``create_transform_job``).
* Run manifest write (mocked S3 PUT).
* Transform job spec rendering (canonical CreateTransformJob shape).
* CLI argument parsing + main() return codes.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from scripts.aws_credit_ops.sagemaker_embed_batch import (
    ALLOWED_MODELS,
    DEFAULT_BUDGET_USD,
    DEFAULT_INSTANCE_TYPE,
    DEFAULT_PER_ROW_USD,
    DEFAULT_WARN_THRESHOLD,
    RunReport,
    S3Uri,
    SagemakerEmbedBatchError,
    _parse_args,
    build_transform_job_spec,
    main,
    projected_spend,
    run_batch,
    should_stop,
    should_warn,
    validate_model,
    validate_model_name,
    validate_role_arn,
    write_run_manifest,
)

_GOOD_ROLE = "arn:aws:iam::993693061769:role/jpcite-sagemaker-embed-role"
_GOOD_MODEL_NAME = "jpcite-embed-allminilm-v1"


class _FakeS3:
    def __init__(self) -> None:
        self.put_calls: list[dict[str, Any]] = []

    def put_object(self, **kwargs: Any) -> dict[str, Any]:
        self.put_calls.append(kwargs)
        return {"ETag": "x"}


class _FakeSagemaker:
    def __init__(self, arn: str = "arn:aws:sagemaker:ap-northeast-1:993693061769:transform-job/test") -> None:
        self._arn = arn
        self.calls: list[dict[str, Any]] = []

    def create_transform_job(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        return {"TransformJobArn": self._arn}


# ---------------------------------------------------------------------------
# Model allow-list
# ---------------------------------------------------------------------------


def test_validate_model_accepts_minilm() -> None:
    meta = validate_model("sentence-transformers/all-MiniLM-L6-v2")
    assert meta["dim"] == 384
    assert meta["license"] == "apache-2.0"


def test_validate_model_accepts_mpnet() -> None:
    meta = validate_model("sentence-transformers/all-mpnet-base-v2")
    assert meta["dim"] == 768


def test_validate_model_accepts_multilingual() -> None:
    meta = validate_model(
        "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    )
    assert meta["dim"] == 384


def test_validate_model_rejects_unknown() -> None:
    with pytest.raises(SagemakerEmbedBatchError, match="allow-list"):
        validate_model("openai/text-embedding-3-large")


def test_allowed_models_have_required_keys() -> None:
    for name, meta in ALLOWED_MODELS.items():
        assert {"dim", "size_mb", "license", "rationale"} <= set(meta), name
        assert isinstance(meta["dim"], int)


# ---------------------------------------------------------------------------
# Role / model name validation
# ---------------------------------------------------------------------------


def test_validate_role_arn_accepts_canonical() -> None:
    assert validate_role_arn(_GOOD_ROLE) == _GOOD_ROLE


def test_validate_role_arn_rejects_placeholder() -> None:
    with pytest.raises(SagemakerEmbedBatchError, match="placeholder"):
        validate_role_arn("arn:aws:iam::123456789012:role/REPLACE_ME")


def test_validate_role_arn_rejects_malformed() -> None:
    with pytest.raises(SagemakerEmbedBatchError, match="arn:aws:iam::"):
        validate_role_arn("not-an-arn")


def test_validate_model_name_accepts_canonical() -> None:
    assert validate_model_name(_GOOD_MODEL_NAME) == _GOOD_MODEL_NAME


def test_validate_model_name_rejects_invalid_chars() -> None:
    with pytest.raises(SagemakerEmbedBatchError):
        validate_model_name("bad name with spaces")


# ---------------------------------------------------------------------------
# Budget gate
# ---------------------------------------------------------------------------


def test_projected_spend_scales_linearly() -> None:
    assert projected_spend(10_000, 0.0001) == pytest.approx(1.0)


def test_should_stop_at_or_above_budget() -> None:
    assert should_stop(100.0, 100.0)
    assert not should_stop(99.999, 100.0)


def test_should_warn_at_threshold() -> None:
    assert should_warn(80.0, 100.0, 0.8)
    assert not should_warn(79.999, 100.0, 0.8)


# ---------------------------------------------------------------------------
# Transform job spec
# ---------------------------------------------------------------------------


def test_build_transform_job_spec_canonical_shape() -> None:
    spec = build_transform_job_spec(
        job_name="job-1",
        sagemaker_model_name=_GOOD_MODEL_NAME,
        input_uri=S3Uri.parse("s3://in/p/"),
        output_uri=S3Uri.parse("s3://out/q/"),
        instance_type=DEFAULT_INSTANCE_TYPE,
    )
    assert spec["TransformJobName"] == "job-1"
    assert spec["ModelName"] == _GOOD_MODEL_NAME
    assert spec["TransformInput"]["ContentType"] == "application/jsonlines"
    assert spec["TransformInput"]["DataSource"]["S3DataSource"]["S3Uri"].startswith(
        "s3://in/"
    )
    assert spec["TransformOutput"]["S3OutputPath"].startswith("s3://out/")
    assert spec["TransformResources"]["InstanceType"] == DEFAULT_INSTANCE_TYPE


# ---------------------------------------------------------------------------
# DRY_RUN drive
# ---------------------------------------------------------------------------


def test_run_batch_dry_run_does_not_call_sagemaker() -> None:
    fake_sm = _FakeSagemaker()
    fake_s3 = _FakeS3()
    report = run_batch(
        input_prefix="s3://in/J04/",
        output_prefix="s3://out/embed/",
        estimated_rows=50_000,
        dry_run=True,
        sagemaker_client=fake_sm,
        s3_client=fake_s3,
    )
    assert report.dry_run is True
    assert fake_sm.calls == []
    # No PUT to S3 in dry-run.
    assert fake_s3.put_calls == []
    assert report.transform_job_arn is None
    # 50k rows * 0.0001 = USD 5.0
    assert report.projected_spend_usd == pytest.approx(5.0)


def test_run_batch_dry_run_stops_on_budget_overflow() -> None:
    report = run_batch(
        input_prefix="s3://in/",
        output_prefix="s3://out/",
        estimated_rows=100_000_000,  # cost 10_000 USD, default budget 3_000
        dry_run=True,
    )
    assert report.stopped is True
    assert "budget" in (report.stop_reason or "")


def test_run_batch_dry_run_emits_warn() -> None:
    # Budget 100, per-row 0.01, rows 8500 -> spend 85 (> 80% warn line).
    report = run_batch(
        input_prefix="s3://in/",
        output_prefix="s3://out/",
        estimated_rows=8500,
        budget_usd=100.0,
        per_row_usd=0.01,
        dry_run=True,
    )
    assert report.warn_emitted is True
    assert report.stopped is False


# ---------------------------------------------------------------------------
# Real-path drive (mocked)
# ---------------------------------------------------------------------------


def test_run_batch_commit_calls_create_transform_job() -> None:
    fake_sm = _FakeSagemaker()
    fake_s3 = _FakeS3()
    report = run_batch(
        input_prefix="s3://in/",
        output_prefix="s3://out/",
        estimated_rows=1000,
        execution_role_arn=_GOOD_ROLE,
        dry_run=False,
        sagemaker_client=fake_sm,
        s3_client=fake_s3,
    )
    assert len(fake_sm.calls) == 1
    submitted = fake_sm.calls[0]
    assert submitted["ModelName"] == _GOOD_MODEL_NAME
    assert report.transform_job_arn is not None
    assert report.transform_job_arn.startswith("arn:aws:sagemaker:")
    # run_manifest.json should have been written.
    assert any("run_manifest.json" in c["Key"] for c in fake_s3.put_calls)


def test_run_batch_commit_rejects_unset_role() -> None:
    with pytest.raises(SagemakerEmbedBatchError, match="placeholder|unset"):
        run_batch(
            input_prefix="s3://in/",
            output_prefix="s3://out/",
            estimated_rows=100,
            execution_role_arn="",
            dry_run=False,
            sagemaker_client=_FakeSagemaker(),
            s3_client=_FakeS3(),
        )


def test_run_batch_commit_does_not_call_when_stopped() -> None:
    fake_sm = _FakeSagemaker()
    report = run_batch(
        input_prefix="s3://in/",
        output_prefix="s3://out/",
        estimated_rows=100_000_000,
        execution_role_arn=_GOOD_ROLE,
        dry_run=False,
        sagemaker_client=fake_sm,
        s3_client=_FakeS3(),
    )
    assert report.stopped is True
    assert fake_sm.calls == []


def test_run_batch_records_correct_embedding_dim_for_mpnet() -> None:
    report = run_batch(
        input_prefix="s3://in/",
        output_prefix="s3://out/",
        model="sentence-transformers/all-mpnet-base-v2",
        estimated_rows=100,
        dry_run=True,
    )
    assert report.embedding_dim == 768


# ---------------------------------------------------------------------------
# Run manifest
# ---------------------------------------------------------------------------


def test_write_run_manifest_round_trip() -> None:
    fake_s3 = _FakeS3()
    report = RunReport(
        job_run_id="r-1",
        input_prefix="s3://in/",
        output_prefix="s3://out/",
        model="sentence-transformers/all-MiniLM-L6-v2",
        embedding_dim=384,
        instance_type=DEFAULT_INSTANCE_TYPE,
        estimated_rows=100,
        budget_usd=DEFAULT_BUDGET_USD,
        per_row_usd=DEFAULT_PER_ROW_USD,
        warn_threshold=DEFAULT_WARN_THRESHOLD,
        dry_run=True,
    )
    write_run_manifest(report, output_uri=S3Uri.parse("s3://out/"), s3_client=fake_s3)
    body = fake_s3.put_calls[0]["Body"].decode("utf-8")
    loaded = json.loads(body)
    assert loaded["job_run_id"] == "r-1"
    assert loaded["embedding_dim"] == 384


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_parse_args_minimum() -> None:
    args = _parse_args(
        [
            "--input-prefix",
            "s3://in/",
            "--output-prefix",
            "s3://out/",
        ]
    )
    assert args.budget_usd == DEFAULT_BUDGET_USD
    assert args.per_row_usd == DEFAULT_PER_ROW_USD
    assert args.commit is False


def test_main_dry_run_returns_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run_batch(**kwargs: Any) -> RunReport:
        return RunReport(
            job_run_id="r",
            input_prefix=kwargs["input_prefix"],
            output_prefix=kwargs["output_prefix"],
            model=kwargs.get("model", "sentence-transformers/all-MiniLM-L6-v2"),
            embedding_dim=384,
            instance_type=DEFAULT_INSTANCE_TYPE,
            estimated_rows=int(kwargs.get("estimated_rows", 0)),
            budget_usd=DEFAULT_BUDGET_USD,
            per_row_usd=DEFAULT_PER_ROW_USD,
            warn_threshold=DEFAULT_WARN_THRESHOLD,
            dry_run=True,
        )

    monkeypatch.setattr(
        "scripts.aws_credit_ops.sagemaker_embed_batch.run_batch", fake_run_batch
    )
    rc = main(["--input-prefix", "s3://in/", "--output-prefix", "s3://out/"])
    assert rc == 0


def test_main_stop_returns_two(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run_batch(**kwargs: Any) -> RunReport:
        rep = RunReport(
            job_run_id="r",
            input_prefix=kwargs["input_prefix"],
            output_prefix=kwargs["output_prefix"],
            model="sentence-transformers/all-MiniLM-L6-v2",
            embedding_dim=384,
            instance_type=DEFAULT_INSTANCE_TYPE,
            estimated_rows=0,
            budget_usd=DEFAULT_BUDGET_USD,
            per_row_usd=DEFAULT_PER_ROW_USD,
            warn_threshold=DEFAULT_WARN_THRESHOLD,
            dry_run=True,
        )
        rep.stopped = True
        rep.stop_reason = "budget"
        return rep

    monkeypatch.setattr(
        "scripts.aws_credit_ops.sagemaker_embed_batch.run_batch", fake_run_batch
    )
    rc = main(["--input-prefix", "s3://in/", "--output-prefix", "s3://out/"])
    assert rc == 2


def test_main_invalid_model_returns_two(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run_batch(**kwargs: Any) -> RunReport:
        raise SagemakerEmbedBatchError("model not in allow-list")

    monkeypatch.setattr(
        "scripts.aws_credit_ops.sagemaker_embed_batch.run_batch", fake_run_batch
    )
    rc = main(
        [
            "--input-prefix",
            "s3://in/",
            "--output-prefix",
            "s3://out/",
            "--model",
            "novel-embeddings/foo",
        ]
    )
    assert rc == 2


# ---------------------------------------------------------------------------
# S3Uri smoke
# ---------------------------------------------------------------------------


def test_s3uri_parse_with_prefix() -> None:
    u = S3Uri.parse("s3://b/k/")
    assert u.bucket == "b" and u.key_prefix == "k/"


def test_s3uri_parse_rejects_https() -> None:
    with pytest.raises(ValueError, match="s3://"):
        S3Uri.parse("https://example.com/")
