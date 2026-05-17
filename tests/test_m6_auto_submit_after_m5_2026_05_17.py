"""M6 watcher gates after M5 terminal status.

The live watcher must submit M6 only when M5 completes. Failed or stopped
M5 jobs require operator inspection before any downstream submit.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys
from typing import TYPE_CHECKING, Any

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
def m6_watcher_module() -> types.ModuleType:
    return _load_script_module(
        "scripts/aws_credit_ops/sagemaker_m6_auto_submit_after_m5.py",
        "m6_auto_submit_after_m5_test",
    )


@pytest.mark.parametrize("status", ["Failed", "Stopped"])
def test_m6_watcher_aborts_after_unsuccessful_m5_terminal_status(
    m6_watcher_module: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    status: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    submit_calls: list[dict[str, Any]] = []

    monkeypatch.setattr(
        m6_watcher_module,
        "wait_until_terminal",
        lambda **_kwargs: (status, 300),
    )

    def fake_submit_m6(**kwargs: Any) -> int:
        submit_calls.append(kwargs)
        return 0

    monkeypatch.setattr(m6_watcher_module, "submit_m6", fake_submit_m6)

    rc = m6_watcher_module.main(["--commit", "--poll-interval", "1", "--max-wait", "1"])

    assert rc == 2
    assert submit_calls == []
    out = capsys.readouterr().out
    assert '"next": "abort"' in out
    assert "refusing to submit M6" in out


def test_m6_watcher_submits_after_completed_m5_only(
    m6_watcher_module: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    submit_calls: list[dict[str, Any]] = []

    monkeypatch.setattr(
        m6_watcher_module,
        "wait_until_terminal",
        lambda **_kwargs: ("Completed", 300),
    )

    def fake_submit_m6(**kwargs: Any) -> int:
        submit_calls.append(kwargs)
        return 0

    monkeypatch.setattr(m6_watcher_module, "submit_m6", fake_submit_m6)

    rc = m6_watcher_module.main(["--commit", "--poll-interval", "1", "--max-wait", "1"])

    assert rc == 0
    assert submit_calls == [
        {"commit": True, "region": "ap-northeast-1", "profile": "bookyou-recovery"}
    ]


def test_m6_watcher_timeout_does_not_submit(
    m6_watcher_module: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    submit_calls: list[dict[str, Any]] = []

    monkeypatch.setattr(
        m6_watcher_module,
        "wait_until_terminal",
        lambda **_kwargs: ("Timeout", 1),
    )

    def fake_submit_m6(**kwargs: Any) -> int:
        submit_calls.append(kwargs)
        return 0

    monkeypatch.setattr(m6_watcher_module, "submit_m6", fake_submit_m6)

    rc = m6_watcher_module.main(["--commit", "--poll-interval", "1", "--max-wait", "1"])

    assert rc == 3
    assert submit_calls == []
