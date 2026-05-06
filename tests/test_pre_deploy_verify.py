from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "ops" / "pre_deploy_verify.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("pre_deploy_verify", SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _completed(stdout_payload: Any, returncode: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=["python", "script.py"],
        returncode=returncode,
        stdout=json.dumps(stdout_payload),
        stderr="",
    )


def test_build_commands_uses_required_local_checks(tmp_path):
    module = _load_module()

    commands = module.build_commands(tmp_path)

    assert [command.name for command in commands] == [
        "release_readiness",
        "production_improvement_preflight",
        "perf_smoke",
    ]
    assert commands[0].argv[-1] == "--warn-only"
    assert commands[1].argv[-2:] == ["--warn-only", "--json"]
    assert commands[2].argv[-7:] == [
        "--samples",
        "1",
        "--warmups",
        "0",
        "--threshold-ms",
        "10000",
        "--json",
    ]


def test_build_commands_passes_preflight_db_and_migrations_dir(tmp_path):
    module = _load_module()

    db = tmp_path / "autonomath.db"
    migrations_dir = tmp_path / "migrations"
    commands = module.build_commands(
        tmp_path,
        preflight_db=db,
        preflight_migrations_dir=migrations_dir,
    )

    preflight = commands[1].argv
    assert preflight[-4:] == [
        "--db",
        str(db),
        "--migrations-dir",
        str(migrations_dir),
    ]


def test_build_report_passes_when_all_child_json_passes(monkeypatch, tmp_path):
    module = _load_module()
    payloads = [
        {"ok": True, "issues": []},
        {"ok": True, "issues": []},
        [{"name": "healthz", "passed": True}],
    ]
    calls: list[list[str]] = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        return _completed(payloads.pop(0))

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    report = module.build_report(tmp_path)

    assert report["ok"] is True
    assert report["summary"] == {"pass": 3, "fail": 0, "total": 3}
    assert report["issues"] == []
    assert len(calls) == 3


def test_build_report_collects_json_and_exit_failures(monkeypatch, tmp_path):
    module = _load_module()
    responses = [
        _completed({"ok": False, "issues": ["workflow_ruff_targets_synced"]}),
        _completed({"ok": True, "issues": []}, returncode=2),
        _completed([{"name": "meta", "passed": False}]),
    ]

    def fake_run(argv, **kwargs):
        return responses.pop(0)

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    report = module.build_report(tmp_path)

    assert report["ok"] is False
    assert report["summary"] == {"pass": 0, "fail": 3, "total": 3}
    assert report["issues"] == [
        {"name": "release_readiness", "issues": ["workflow_ruff_targets_synced"]},
        {"name": "production_improvement_preflight", "issues": ["exit_code:2"]},
        {"name": "perf_smoke", "issues": ["perf_smoke:endpoint_failed:meta"]},
    ]


def test_main_warn_only_exits_zero_on_failure(monkeypatch, tmp_path, capsys):
    module = _load_module()

    def fake_build_report(repo_root, *, preflight_db, preflight_migrations_dir):
        assert repo_root == tmp_path
        assert preflight_db == tmp_path / "autonomath.db"
        assert preflight_migrations_dir is None
        return {
            "ok": False,
            "issues": [{"name": "release_readiness", "issues": ["failed"]}],
        }

    monkeypatch.setattr(module, "build_report", fake_build_report)

    exit_code = module.main(
        [
            "--repo-root",
            str(tmp_path),
            "--preflight-db",
            str(tmp_path / "autonomath.db"),
            "--warn-only",
        ]
    )
    report = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert report["ok"] is False


def test_main_exits_nonzero_without_warn_only(monkeypatch, tmp_path, capsys):
    module = _load_module()
    monkeypatch.setattr(
        module,
        "build_report",
        lambda repo_root, *, preflight_db, preflight_migrations_dir: {
            "ok": False,
            "issues": [],
        },
    )

    exit_code = module.main(["--repo-root", str(tmp_path)])
    report = json.loads(capsys.readouterr().out)

    assert exit_code == 1
    assert report["ok"] is False
