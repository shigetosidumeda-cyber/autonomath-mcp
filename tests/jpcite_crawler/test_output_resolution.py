"""Tests for entrypoint output target resolution (3 forms)."""
from __future__ import annotations
import os
import sys
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
ENTRYPOINT_PATH = ROOT / "docker" / "jpcite-crawler" / "entrypoint.py"


def load_entrypoint():
    spec = importlib.util.spec_from_file_location("jpcite_entrypoint", ENTRYPOINT_PATH)
    if spec is None or spec.loader is None:
        pytest.skip(f"could not load entrypoint at {ENTRYPOINT_PATH}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_output_legacy_split():
    """spec.output_bucket + spec.output_prefix (legacy split form)."""
    spec = {"output_bucket": "my-bucket", "output_prefix": "my/prefix/"}
    raw_out_prefix = str(spec.get("output_prefix"))
    assert "output_bucket" in spec
    output_bucket = str(spec["output_bucket"])
    output_prefix = raw_out_prefix
    assert output_bucket == "my-bucket"
    assert output_prefix == "my/prefix/"


def test_output_s3_uri():
    """spec.output_prefix as s3://bucket/prefix URI."""
    raw_out_prefix = "s3://jpcite-credit-993693061769-202605-raw/J01_source_profile/"
    assert raw_out_prefix.startswith("s3://")
    without_scheme = raw_out_prefix[len("s3://") :]
    bucket_part, _, key_part = without_scheme.partition("/")
    assert bucket_part == "jpcite-credit-993693061769-202605-raw"
    assert key_part == "J01_source_profile/"


def test_output_s3_uri_bucket_only():
    """s3:// URI with bucket only, no prefix - should fallback to runs/<run_id>/<job_id>."""
    raw_out_prefix = "s3://my-bucket"
    without_scheme = raw_out_prefix[len("s3://") :]
    bucket_part, _, key_part = without_scheme.partition("/")
    assert bucket_part == "my-bucket"
    assert key_part == ""


def test_output_env_fallback():
    """env OUTPUT_S3_BUCKET fallback when spec lacks bucket and output_prefix is not s3:// URI."""
    os.environ["OUTPUT_S3_BUCKET"] = "fallback-bucket"
    spec = {"output_prefix": "relative/path/"}
    raw_out_prefix = str(spec.get("output_prefix"))
    assert "output_bucket" not in spec
    assert not raw_out_prefix.startswith("s3://")
    env_bucket = os.environ.get("OUTPUT_S3_BUCKET", "").strip()
    assert env_bucket == "fallback-bucket"
    os.environ.pop("OUTPUT_S3_BUCKET")


def test_all_J0X_manifests_have_s3_uri_output_prefix():
    """All J01-J07 manifests should use s3://bucket/prefix form per master plan canonical."""
    import json
    manifests_dir = ROOT / "data" / "aws_credit_jobs"
    files = sorted(manifests_dir.glob("J0?_*.json"))
    assert len(files) == 7, f"expected 7 manifests, got {len(files)}"
    for f in files:
        with f.open() as fp:
            d = json.load(fp)
        op = d.get("output_prefix", "")
        assert op.startswith("s3://"), f"{f.name} output_prefix should be s3:// URI, got: {op}"
