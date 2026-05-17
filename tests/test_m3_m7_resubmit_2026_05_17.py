"""M3 + M7 re-submit fix gating tests — 2026-05-17.

Gates the two regression fixes landed in
``sagemaker_clip_figure_submit_2026_05_17.py`` (M3) and
``sagemaker_kg_completion_submit_2026_05_17.py`` (M7).

* M3: per-job code S3 sub-prefix layout so SageMaker mounts
  ``embed.py`` flat under ``/opt/ml/processing/input/code/``.
* M7: HyperParameter dict keys use dashes (``batch-size``,
  ``embedding-dim``, ``negative-samples``, ``learning-rate``) so
  SageMaker passes them to the PyKEEN argparse entrypoint as
  ``--batch-size 512``. The entrypoint also accepts underscore aliases
  to tolerate SageMaker / retry-ledger variants, and ConvE uses a
  conservative memory profile before re-submit.

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


@pytest.fixture(scope="module")
def m7_entry_module() -> types.ModuleType:
    return _load_script_module(
        "scripts/aws_credit_ops/kg_completion_train_entry.py",
        "m7_entry_alias_test",
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
    assert "torchvision==0.15.1" in m3_module.EMBEDDER_SCRIPT


def test_m3_embedder_uses_manual_torchvision_pixel_values(m3_module: types.ModuleType) -> None:
    """The live embedder must avoid unavailable processors or git packages."""
    assert "from transformers import AutoModel" in m3_module.EMBEDDER_SCRIPT
    assert "from torchvision import transforms" in m3_module.EMBEDDER_SCRIPT
    assert "pixel_values=pixel_values" in m3_module.EMBEDDER_SCRIPT
    assert "AutoImageProcessor" not in m3_module.EMBEDDER_SCRIPT
    assert "japanese_clip" not in m3_module.EMBEDDER_SCRIPT
    assert "git+https://github.com" not in m3_module.EMBEDDER_SCRIPT


def test_m3_embedder_passes_ledger_metadata_required_by_ingest(
    m3_module: types.ModuleType,
) -> None:
    """Embedding rows must remain ingestable without a second ledger join."""
    required_keys = {
        '"s3_key"',
        '"bbox_x"',
        '"bbox_y"',
        '"bbox_w"',
        '"bbox_h"',
        '"caption_quote_span"',
        '"figure_kind"',
    }
    for key in required_keys:
        assert key in m3_module.EMBEDDER_SCRIPT
    assert "missing ledger metadata" in m3_module.EMBEDDER_SCRIPT


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


def test_m7_live_gate_requires_flags_and_dry_run_zero(
    m7_module: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Live M7 submit must stay dry-run unless flags and DRY_RUN=0 are present."""
    args = m7_module._parse_args(["--commit", "--unlock-live-aws-commands"])
    monkeypatch.delenv("DRY_RUN", raising=False)
    assert m7_module._resolve_dry_run(args) is True
    monkeypatch.setenv("DRY_RUN", "1")
    assert m7_module._resolve_dry_run(args) is True
    monkeypatch.setenv("DRY_RUN", "0")
    assert m7_module._resolve_dry_run(args) is False
    no_unlock = m7_module._parse_args(["--commit"])
    assert m7_module._resolve_dry_run(no_unlock) is True
    no_commit = m7_module._parse_args(["--unlock-live-aws-commands"])
    assert m7_module._resolve_dry_run(no_commit) is True


def test_m7_docs_name_dry_run_zero_live_gate(m7_module: types.ModuleType) -> None:
    """The runbook must not imply flags alone submit live KG jobs."""
    script_doc = m7_module.__doc__ or ""
    runbook = (REPO_ROOT / "docs/_internal/AWS_SEVEN_DAY_BURN_RAMP_2026_05_17.md").read_text()
    assert "DRY_RUN=0" in script_doc
    assert (
        "DRY_RUN=0 .venv/bin/python -m scripts.aws_credit_ops.sagemaker_kg_completion_submit_2026_05_17"
        in runbook
    )


def test_m7_training_entry_accepts_dash_and_underscore_hyperparameters(
    m7_entry_module: types.ModuleType,
) -> None:
    """SageMaker retry ledgers may carry either CLI spelling; both stay valid."""
    assert (
        m7_entry_module._hp_value({"embedding-dim": "384"}, "embedding-dim", "embedding_dim", 500)
        == "384"
    )
    assert (
        m7_entry_module._hp_value({"embedding_dim": "256"}, "embedding-dim", "embedding_dim", 500)
        == "256"
    )
    source = (REPO_ROOT / "scripts/aws_credit_ops/kg_completion_train_entry.py").read_text()
    assert '"--embedding-dim",\n        "--embedding_dim"' in source
    assert '"--batch-size",\n        "--batch_size"' in source
    assert '"--negative-samples",\n        "--negative_samples"' in source
    assert '"--learning-rate",\n        "--learning_rate"' in source


def test_m7_submit_parser_accepts_dash_and_underscore_aliases(
    m7_module: types.ModuleType,
) -> None:
    """The submit wrapper should accept both retry-ledger spellings too."""
    args = m7_module._parse_args(
        [
            "--embedding_dim",
            "256",
            "--batch_size",
            "64",
            "--negative_samples",
            "32",
            "--learning_rate",
            "0.0001",
        ]
    )
    assert args.embedding_dim == 256
    assert args.batch_size == 64
    assert args.negative_samples == 32
    assert args.learning_rate == 0.0001


def test_m7_conve_profile_caps_memory_heavy_defaults(m7_module: types.ModuleType) -> None:
    """ConvE previously hit MemoryError at batch_size=512; profile caps it."""
    profiled = m7_module._profiled_hyperparameters(
        model="ConvE",
        embedding_dim=500,
        epochs=200,
        batch_size=512,
        negative_samples=256,
        learning_rate=1e-3,
    )
    assert profiled == {
        "embedding_dim": 200,
        "epochs": 200,
        "batch_size": 256,
        "negative_samples": 128,
        "learning_rate": 1e-3,
    }


def test_m7_profiles_do_not_increase_operator_smaller_values(m7_module: types.ModuleType) -> None:
    """Manual lower caps remain lower than the per-model profile."""
    profiled = m7_module._profiled_hyperparameters(
        model="ConvE",
        embedding_dim=128,
        epochs=100,
        batch_size=64,
        negative_samples=32,
        learning_rate=1e-4,
    )
    assert profiled == {
        "embedding_dim": 128,
        "epochs": 100,
        "batch_size": 64,
        "negative_samples": 32,
        "learning_rate": 1e-4,
    }


def test_m7_conve_profile_flows_into_dashed_spec_keys(m7_module: types.ModuleType) -> None:
    """The post-profile spec should carry ConvE's lower memory footprint."""
    profiled = m7_module._profiled_hyperparameters(
        model="ConvE",
        embedding_dim=500,
        epochs=200,
        batch_size=512,
        negative_samples=256,
        learning_rate=1e-3,
    )
    kwargs = {
        **_M7_SPEC_KWARGS,
        "model": "ConvE",
        "embedding_dim": int(profiled["embedding_dim"]),
        "epochs": int(profiled["epochs"]),
        "batch_size": int(profiled["batch_size"]),
        "negative_samples": int(profiled["negative_samples"]),
        "learning_rate": float(profiled["learning_rate"]),
    }
    hp = m7_module._spec(**kwargs)["HyperParameters"]
    assert hp["embedding-dim"] == "200"
    assert hp["batch-size"] == "256"
    assert hp["negative-samples"] == "128"
