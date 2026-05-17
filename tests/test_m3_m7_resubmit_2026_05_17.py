"""M3 + M7 re-submit fix gating tests — 2026-05-17.

Gates the two regression fixes landed in
``sagemaker_clip_figure_submit_2026_05_17.py`` (M3) and
``sagemaker_kg_completion_submit_2026_05_17.py`` (M7).

* M3: per-job code S3 sub-prefix layout so SageMaker mounts
  ``embed.py`` flat under ``/opt/ml/processing/input/code/``.
* M7: HyperParameter dict keys use dashes (``batch-size``,
  ``embedding-dim``, ``negative-samples``, ``learning-rate``) so
  SageMaker passes them to the PyKEEN argparse entrypoint as
  ``--batch-size 512`` rather than the rejected
  ``--batch_size 512``.

NO live AWS — every assertion runs against in-process module imports,
generated dicts, and tar archive metadata.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys
import types
from typing import Any

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]


def _load_script_module(rel_path: str, alias: str) -> types.ModuleType:
    """Import a standalone script as a module under ``alias``."""
    path = REPO_ROOT / rel_path
    spec = importlib.util.spec_from_file_location(alias, path)
    assert spec is not None
    assert spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[alias] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def m3_module() -> types.ModuleType:
    return _load_script_module(
        "scripts/aws_credit_ops/sagemaker_clip_figure_submit_2026_05_17.py",
        "m3_resubmit_fix_test",
    )


@pytest.fixture(scope="module")
def m7_module() -> types.ModuleType:
    return _load_script_module(
        "scripts/aws_credit_ops/sagemaker_kg_completion_submit_2026_05_17.py",
        "m7_resubmit_fix_test",
    )


# ---------- M3 fix gating ---------------------------------------------------


def test_m3_stamp_job_name_carries_jp_marker(m3_module: types.ModuleType) -> None:
    """Re-submitted Japanese-CLIP jobs must carry the ``-jp-`` marker."""
    name = m3_module._stamp_job_name()
    assert name.startswith("jpcite-figure-clip-jp-"), name
    assert "jpcite-figure-clip-jp-2026" in name


def test_m3_default_model_is_japanese_clip(m3_module: types.ModuleType) -> None:
    """Default CLIP model id pins the rinna Japanese ViT-B/16 release."""
    assert m3_module.DEFAULT_MODEL == "rinna/japanese-clip-vit-b-16"
    assert "rinna/japanese-clip-vit-b-16" in m3_module.ALLOW_MODELS
    assert m3_module.ALLOW_MODELS["rinna/japanese-clip-vit-b-16"]["dim"] == 512


def test_m3_upload_code_channel_returns_per_job_prefix(m3_module: types.ModuleType) -> None:
    """The upload helper must surface the per-job S3 sub-prefix in meta."""
    args = types.SimpleNamespace(
        derived_bucket="jpcite-credit-993693061769-202605-derived",
        code_prefix="figure_embeddings_code/",
        profile="bookyou-recovery",
        region="ap-northeast-1",
    )
    code_key, meta = m3_module._upload_code_channel(args, "fake-job-2026", commit=False)
    assert code_key.endswith("/fake-job-2026/embed.py"), code_key
    assert meta["code_s3_prefix"] == "figure_embeddings_code/fake-job-2026/"
    # The code key sits flat under the per-job sub-prefix root.
    assert code_key == meta["code_s3_prefix"] + "embed.py"


def test_m3_build_processing_inputs_uses_per_job_code_prefix(
    m3_module: types.ModuleType,
) -> None:
    """ProcessingInputs `code` channel must point at the per-job sub-prefix."""
    args = types.SimpleNamespace(
        derived_bucket="jpcite-credit-993693061769-202605-derived",
        input_prefix="figures_raw/",
        code_prefix="figure_embeddings_code/",
    )
    inputs = m3_module._build_processing_inputs(
        args,
        "s3://jpcite-credit-993693061769-202605-derived/figure_embeddings_code/ledger/",
        "figure_embeddings_code/fake-job-2026/",
    )
    code_input = next(i for i in inputs if i["InputName"] == "code")
    assert code_input["S3Input"]["S3Uri"] == (
        "s3://jpcite-credit-993693061769-202605-derived/figure_embeddings_code/fake-job-2026/"
    ), code_input["S3Input"]["S3Uri"]
    assert code_input["S3Input"]["LocalPath"] == "/opt/ml/processing/input/code"


def test_m3_app_spec_entrypoint_flat_embed_py(m3_module: types.ModuleType) -> None:
    """ContainerEntrypoint must expect ``embed.py`` flat under the mount root."""
    args = types.SimpleNamespace()
    spec = m3_module._build_app_spec(args)
    assert spec["ContainerEntrypoint"] == [
        "python3",
        "/opt/ml/processing/input/code/embed.py",
    ]


def test_m3_embedder_pins_transformers_compatible_with_torch_2_0(
    m3_module: types.ModuleType,
) -> None:
    """The inline embedder must pin transformers to a torch-2.0-compatible release."""
    assert "transformers==4.36.2" in m3_module.EMBEDDER_SCRIPT
    assert "torchvision==0.15.2" in m3_module.EMBEDDER_SCRIPT


# ---------- M7 fix gating ---------------------------------------------------


_M7_SPEC_KWARGS: dict[str, Any] = {
    "job_name": "test-job",
    "bucket": "jpcite-credit-993693061769-202605-derived",
    "role_arn": "arn:aws:iam::993693061769:role/jpcite-sagemaker-execution-role",
    "region": "ap-northeast-1",
    "train_uri": "s3://bucket/train.jsonl",
    "val_uri": "s3://bucket/val.jsonl",
    "test_uri": "s3://bucket/test.jsonl",
    "output_prefix": "models/v1/transe",
    "source_uri": "s3://bucket/source.tar.gz",
    "model": "TransE",
    "embedding_dim": 500,
    "epochs": 200,
    "batch_size": 512,
    "negative_samples": 256,
    "learning_rate": 1e-3,
    "max_runtime": 86400,
    "instance_type": "ml.g4dn.2xlarge",
}


def test_m7_hyperparameters_use_dashed_keys(m7_module: types.ModuleType) -> None:
    """User-facing hyperparameter keys must be dashed for argparse compatibility."""
    spec = m7_module._spec(**_M7_SPEC_KWARGS)
    hp = spec["HyperParameters"]
    # Dashed user-facing keys
    assert "embedding-dim" in hp
    assert "batch-size" in hp
    assert "negative-samples" in hp
    assert "learning-rate" in hp
    # Old underscore variants must be absent — those are the failure mode.
    assert "embedding_dim" not in hp
    assert "batch_size" not in hp
    assert "negative_samples" not in hp
    assert "learning_rate" not in hp


def test_m7_sagemaker_meta_keys_keep_underscores(m7_module: types.ModuleType) -> None:
    """SageMaker framework keys are consumed directly and stay underscored."""
    spec = m7_module._spec(**_M7_SPEC_KWARGS)
    hp = spec["HyperParameters"]
    assert hp["sagemaker_program"] == "kg_completion_train_entry.py"
    assert hp["sagemaker_submit_directory"].startswith("s3://")
    assert hp["sagemaker_container_log_level"] == "20"
    assert hp["sagemaker_region"] == "ap-northeast-1"


def test_m7_supports_all_four_pykeen_models(m7_module: types.ModuleType) -> None:
    """The ensemble must cover the canonical PyKEEN 4-tuple."""
    assert m7_module.MODELS == ("TransE", "RotatE", "ComplEx", "ConvE")


def test_m7_spec_model_value_flows_through(m7_module: types.ModuleType) -> None:
    """The ``model`` hyperparameter must echo the requested model name."""
    for model_name in m7_module.MODELS:
        kwargs = {**_M7_SPEC_KWARGS, "model": model_name}
        spec = m7_module._spec(**kwargs)
        assert spec["HyperParameters"]["model"] == model_name
        assert spec["TrainingJobName"] == "test-job"


def test_m7_hardstop_under_never_reach(m7_module: types.ModuleType) -> None:
    """The 5-line preflight hard-stop must sit under the $19,490 Never-Reach."""
    assert m7_module.HARD_STOP_USD == 18000.0
    assert m7_module.HARD_STOP_USD < 19490.0
