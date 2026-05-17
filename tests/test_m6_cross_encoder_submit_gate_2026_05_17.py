"""M6 cross-encoder direct submit live-gate tests."""

from __future__ import annotations

import importlib.util
import pathlib
import sys
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    import types

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
def m6_submit_module() -> types.ModuleType:
    return _load_script_module(
        "scripts/aws_credit_ops/sagemaker_cross_encoder_finetune_2026_05_17.py",
        "m6_cross_encoder_submit_gate_test",
    )


def test_m6_direct_submit_live_gate_requires_commit_and_dry_run_zero(
    m6_submit_module: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    no_commit = m6_submit_module._parse_args([])
    monkeypatch.setenv("DRY_RUN", "0")
    assert m6_submit_module._resolve_dry_run(no_commit) is True

    with_commit = m6_submit_module._parse_args(["--commit"])
    monkeypatch.delenv("DRY_RUN", raising=False)
    assert m6_submit_module._resolve_dry_run(with_commit) is True
    monkeypatch.setenv("DRY_RUN", "1")
    assert m6_submit_module._resolve_dry_run(with_commit) is True
    monkeypatch.setenv("DRY_RUN", "0")
    assert m6_submit_module._resolve_dry_run(with_commit) is False
