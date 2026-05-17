"""M11 multi-task SageMaker submit S3 input preflight tests.

The submitter must fail locally when train/val S3 prefixes are empty, before
uploading source code or creating an expensive training job.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    import types
    from collections.abc import Iterable

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]


def _load_script_module(rel_path: str, alias: str) -> types.ModuleType:
    path = REPO_ROOT / rel_path
    spec = importlib.util.spec_from_file_location(alias, path)
    assert spec is not None
    assert spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[alias] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def m11_submit_module() -> types.ModuleType:
    return _load_script_module(
        "scripts/aws_credit_ops/sagemaker_multitask_finetune_2026_05_17.py",
        "m11_multitask_submit_preflight_test",
    )


class FakeS3:
    def __init__(self, present_keys: Iterable[tuple[str, str]]) -> None:
        self.present_keys = set(present_keys)
        self.calls: list[tuple[str, str, str]] = []

    def list_objects_v2(self, **kwargs: Any) -> dict[str, Any]:
        bucket = str(kwargs["Bucket"])
        prefix = str(kwargs["Prefix"])
        max_keys = int(kwargs["MaxKeys"])
        self.calls.append(("list_objects_v2", bucket, prefix))
        assert max_keys == 1
        if any(
            existing_bucket == bucket and key.startswith(prefix)
            for existing_bucket, key in self.present_keys
        ):
            return {"Contents": [{"Key": prefix, "Size": 1}]}
        return {}


def test_parse_s3_uri_accepts_bucket_and_prefix(m11_submit_module: types.ModuleType) -> None:
    parsed = m11_submit_module.parse_s3_uri("s3://bucket/path/to/train.jsonl")
    assert parsed.bucket == "bucket"
    assert parsed.key_prefix == "path/to/train.jsonl"


@pytest.mark.parametrize("uri", ["bucket/path", "s3://", "s3://bucket", "s3:///key"])
def test_parse_s3_uri_rejects_malformed(
    m11_submit_module: types.ModuleType,
    uri: str,
) -> None:
    with pytest.raises(ValueError):
        m11_submit_module.parse_s3_uri(uri)


def test_preflight_training_inputs_accepts_present_train_and_val(
    m11_submit_module: types.ModuleType,
) -> None:
    s3 = FakeS3(
        {
            ("bucket", "finetune_corpus_multitask/train.jsonl"),
            ("bucket", "finetune_corpus_multitask/val.jsonl"),
        }
    )
    m11_submit_module.preflight_training_inputs_exist(
        s3,
        train_uri="s3://bucket/finetune_corpus_multitask/train.jsonl",
        val_uri="s3://bucket/finetune_corpus_multitask/val.jsonl",
    )
    assert s3.calls == [
        ("list_objects_v2", "bucket", "finetune_corpus_multitask/train.jsonl"),
        ("list_objects_v2", "bucket", "finetune_corpus_multitask/val.jsonl"),
    ]


def test_preflight_training_inputs_rejects_missing_val(
    m11_submit_module: types.ModuleType,
) -> None:
    s3 = FakeS3({("bucket", "finetune_corpus_multitask/train.jsonl")})
    with pytest.raises(RuntimeError, match="val"):
        m11_submit_module.preflight_training_inputs_exist(
            s3,
            train_uri="s3://bucket/finetune_corpus_multitask/train.jsonl",
            val_uri="s3://bucket/finetune_corpus_multitask/val.jsonl",
        )
    assert s3.calls == [
        ("list_objects_v2", "bucket", "finetune_corpus_multitask/train.jsonl"),
        ("list_objects_v2", "bucket", "finetune_corpus_multitask/val.jsonl"),
    ]


def test_m11_live_gate_requires_commit_and_dry_run_zero(
    m11_submit_module: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    no_commit = m11_submit_module._parse_args([])
    monkeypatch.setenv("DRY_RUN", "0")
    assert m11_submit_module._resolve_dry_run(no_commit) is True

    with_commit = m11_submit_module._parse_args(["--commit"])
    monkeypatch.delenv("DRY_RUN", raising=False)
    assert m11_submit_module._resolve_dry_run(with_commit) is True
    monkeypatch.setenv("DRY_RUN", "1")
    assert m11_submit_module._resolve_dry_run(with_commit) is True
    monkeypatch.setenv("DRY_RUN", "0")
    assert m11_submit_module._resolve_dry_run(with_commit) is False


def test_main_commit_checks_s3_before_source_upload(
    m11_submit_module: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
) -> None:
    events: list[str] = []
    s3 = FakeS3(
        {
            ("bucket", "finetune_corpus_multitask/train.jsonl"),
            ("bucket", "finetune_corpus_multitask/val.jsonl"),
        }
    )
    entry = tmp_path / "entry.py"
    entry.write_text("print('ok')\n")

    def fake_preflight_cost(_region: str, _profile: str) -> float:
        events.append("cost")
        return 0.0

    def fake_boto3(service: str, _region: str, _profile: str) -> Any:
        events.append(f"boto3:{service}")
        assert service == "s3"
        return s3

    def fake_upload_source_tar(
        _s3: Any,
        *,
        bucket: str,
        key: str,
        body: bytes,
    ) -> str:
        events.append("upload")
        assert bucket == "bucket"
        assert key.endswith("sourcedir-m11-test.tar.gz")
        assert body
        return "s3://bucket/source/sourcedir-m11-test.tar.gz"

    def fake_submit(**_kwargs: Any) -> dict[str, Any]:
        events.append("submit")
        return {"dry_run": False, "spec": {}}

    monkeypatch.setattr(m11_submit_module, "preflight_cost", fake_preflight_cost)
    monkeypatch.setattr(m11_submit_module, "_boto3", fake_boto3)
    monkeypatch.setattr(m11_submit_module, "upload_source_tar", fake_upload_source_tar)
    monkeypatch.setattr(m11_submit_module, "submit", fake_submit)
    monkeypatch.setenv("DRY_RUN", "0")

    rc = m11_submit_module.main(
        [
            "--commit",
            "--bucket",
            "bucket",
            "--job-name",
            "m11-test",
            "--train-uri",
            "s3://bucket/finetune_corpus_multitask/train.jsonl",
            "--val-uri",
            "s3://bucket/finetune_corpus_multitask/val.jsonl",
            "--entry-file",
            str(entry),
            "--requirements",
            "",
        ]
    )
    assert rc == 0
    assert events == ["cost", "boto3:s3", "upload", "submit"]
    assert s3.calls == [
        ("list_objects_v2", "bucket", "finetune_corpus_multitask/train.jsonl"),
        ("list_objects_v2", "bucket", "finetune_corpus_multitask/val.jsonl"),
    ]


def test_main_commit_aborts_before_upload_when_val_missing(
    m11_submit_module: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
) -> None:
    events: list[str] = []
    s3 = FakeS3({("bucket", "finetune_corpus_multitask/train.jsonl")})
    entry = tmp_path / "entry.py"
    entry.write_text("print('ok')\n")

    monkeypatch.setattr(m11_submit_module, "preflight_cost", lambda *_args: 0.0)
    monkeypatch.setattr(m11_submit_module, "_boto3", lambda *_args: s3)
    monkeypatch.setenv("DRY_RUN", "0")

    def fail_upload_source_tar(*_args: Any, **_kwargs: Any) -> str:
        events.append("upload")
        return "s3://bucket/source.tar.gz"

    def fail_submit(**_kwargs: Any) -> dict[str, Any]:
        events.append("submit")
        return {"dry_run": False}

    monkeypatch.setattr(m11_submit_module, "upload_source_tar", fail_upload_source_tar)
    monkeypatch.setattr(m11_submit_module, "submit", fail_submit)

    rc = m11_submit_module.main(
        [
            "--commit",
            "--bucket",
            "bucket",
            "--job-name",
            "m11-test",
            "--train-uri",
            "s3://bucket/finetune_corpus_multitask/train.jsonl",
            "--val-uri",
            "s3://bucket/finetune_corpus_multitask/val.jsonl",
            "--entry-file",
            str(entry),
            "--requirements",
            "",
        ]
    )
    assert rc == 2
    assert events == []
    assert s3.calls == [
        ("list_objects_v2", "bucket", "finetune_corpus_multitask/train.jsonl"),
        ("list_objects_v2", "bucket", "finetune_corpus_multitask/val.jsonl"),
    ]
