"""Tests for ``scripts/ops/sync_release_manifest_sha.py`` (Stream O, Wave 50).

The script is responsible for keeping ``manifest_sha256`` inside
``site/.well-known/jpcite-release.json`` in lock-step with the actual
sha256 of ``site/releases/rc1-p0-bootstrap/release_capsule_manifest.json``
and for never mutating any other field in the well-known JSON.

These tests run the script as a subprocess against a temporary working
tree to avoid touching the real repo state.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "ops" / "sync_release_manifest_sha.py"
MANIFEST_REL = Path("site/releases/rc1-p0-bootstrap/release_capsule_manifest.json")
WELL_KNOWN_REL = Path("site/.well-known/jpcite-release.json")


@pytest.fixture()
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Build a minimal tree mirroring the real repo layout the script needs."""

    (tmp_path / MANIFEST_REL.parent).mkdir(parents=True, exist_ok=True)
    (tmp_path / WELL_KNOWN_REL.parent).mkdir(parents=True, exist_ok=True)
    # Copy the script under tmp_path/scripts/ops keeping the parents[2] relation.
    script_target = tmp_path / "scripts" / "ops" / SCRIPT_PATH.name
    script_target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SCRIPT_PATH, script_target)
    return tmp_path


def _write_manifest(tmp_root: Path, payload: dict) -> str:
    path = tmp_root / MANIFEST_REL
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    path.write_text(text, encoding="utf-8")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_well_known(tmp_root: Path, payload: dict) -> None:
    path = tmp_root / WELL_KNOWN_REL
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _run(tmp_root: Path, *extra_args: str) -> subprocess.CompletedProcess[str]:
    script = tmp_root / "scripts" / "ops" / SCRIPT_PATH.name
    return subprocess.run(
        [sys.executable, str(script), *extra_args],
        check=False,
        capture_output=True,
        text=True,
        cwd=tmp_root,
        env={"JPCITE_NO_VENV_REEXEC": "1", "PATH": "/usr/bin:/bin"},
    )


def _baseline_well_known(manifest_sha: str) -> dict:
    return {
        "active_capsule_id": "rc1-p0-bootstrap-2026-05-15",
        "active_capsule_manifest": "/releases/rc1-p0-bootstrap/release_capsule_manifest.json",
        "aws_runtime_dependency_allowed": False,
        "capsule_state": "candidate",
        "live_aws_commands_allowed": False,
        "manifest_path": "/releases/rc1-p0-bootstrap/release_capsule_manifest.json",
        "manifest_sha256": manifest_sha,
        "next_resume_doc": "docs/_internal/execution/rc1-p0-bootstrap/README.md",
        "p0_facade_path": "/releases/rc1-p0-bootstrap/agent_surface/p0_facade.json",
        "runtime_pointer_path": "/releases/current/runtime_pointer.json",
        "schema_version": "jpcite.well_known_release.p0.v1",
    }


def test_apply_writes_correct_sha_when_drifted(workspace: Path) -> None:
    real_sha = _write_manifest(workspace, {"capsule_id": "rc1-p0-bootstrap-2026-05-15", "n": 21})
    stale = _baseline_well_known("deadbeef" * 8)
    _write_well_known(workspace, stale)

    result = _run(workspace)

    assert result.returncode == 0, result.stderr
    plan = json.loads(result.stdout)
    assert plan["status"] == "synced"
    assert plan["new_sha"] == real_sha
    assert plan["previous_sha"] == "deadbeef" * 8
    assert plan["changed"] is True

    after = json.loads((workspace / WELL_KNOWN_REL).read_text(encoding="utf-8"))
    assert after["manifest_sha256"] == real_sha


def test_apply_is_idempotent_when_already_synced(workspace: Path) -> None:
    real_sha = _write_manifest(workspace, {"capsule_id": "rc1-p0-bootstrap-2026-05-15"})
    _write_well_known(workspace, _baseline_well_known(real_sha))

    # First run -- already synced because we wrote the right sha
    first = _run(workspace)
    assert first.returncode == 0
    plan = json.loads(first.stdout)
    assert plan["status"] == "already_synced"
    assert plan["changed"] is False

    # Second run -- still already synced, byte-equal output
    second = _run(workspace)
    assert second.returncode == 0
    assert json.loads(second.stdout)["status"] == "already_synced"


def test_apply_preserves_all_other_fields(workspace: Path) -> None:
    real_sha = _write_manifest(workspace, {"capsule_id": "x", "expanded": True})
    stale = _baseline_well_known("0" * 64)
    # Deliberately add an unknown field that the schema should not touch.
    stale["custom_marker"] = "do-not-touch"
    _write_well_known(workspace, stale)

    result = _run(workspace)
    assert result.returncode == 0

    after = json.loads((workspace / WELL_KNOWN_REL).read_text(encoding="utf-8"))
    # sha256 was rewritten...
    assert after["manifest_sha256"] == real_sha
    # ...and absolutely nothing else changed.
    for key, expected in stale.items():
        if key == "manifest_sha256":
            continue
        assert after[key] == expected, f"field {key!r} mutated"
    assert set(after.keys()) == set(stale.keys()), "no field added/removed"


def test_dry_run_reports_drift_without_writing(workspace: Path) -> None:
    real_sha = _write_manifest(workspace, {"capsule_id": "x"})
    stale = _baseline_well_known("1" * 64)
    _write_well_known(workspace, stale)
    before_text = (workspace / WELL_KNOWN_REL).read_text(encoding="utf-8")

    result = _run(workspace, "--dry-run")
    assert result.returncode == 0
    plan = json.loads(result.stdout)
    assert plan["status"] == "drift_detected"
    assert plan["in_sync"] is False
    assert plan["expected_sha"] == real_sha
    assert plan["current_sha"] == "1" * 64

    after_text = (workspace / WELL_KNOWN_REL).read_text(encoding="utf-8")
    assert after_text == before_text, "dry-run mutated the well-known"


def test_dry_run_reports_already_synced(workspace: Path) -> None:
    real_sha = _write_manifest(workspace, {"capsule_id": "x"})
    _write_well_known(workspace, _baseline_well_known(real_sha))

    result = _run(workspace, "--dry-run")
    assert result.returncode == 0
    plan = json.loads(result.stdout)
    assert plan["status"] == "already_synced"
    assert plan["in_sync"] is True


def test_check_exits_nonzero_on_drift(workspace: Path) -> None:
    _write_manifest(workspace, {"capsule_id": "x"})
    _write_well_known(workspace, _baseline_well_known("a" * 64))

    result = _run(workspace, "--check")
    assert result.returncode == 2, result.stderr
    plan = json.loads(result.stdout)
    assert plan["status"] == "drift_detected"


def test_check_exits_zero_when_in_sync(workspace: Path) -> None:
    real_sha = _write_manifest(workspace, {"capsule_id": "x"})
    _write_well_known(workspace, _baseline_well_known(real_sha))

    result = _run(workspace, "--check")
    assert result.returncode == 0
    assert json.loads(result.stdout)["status"] == "already_synced"


def test_refreshes_surface_sha_map_when_present(workspace: Path) -> None:
    # Add a referenced surface artifact under site/releases/rc1-p0-bootstrap/.
    surface_local = (
        workspace / "site" / "releases" / "rc1-p0-bootstrap" / "accounting_csv_profiles.json"
    )
    surface_local.write_text(json.dumps({"version": 2}), encoding="utf-8")
    actual_surface_sha = hashlib.sha256(surface_local.read_bytes()).hexdigest()

    manifest_payload = {
        "capsule_id": "rc1-p0-bootstrap-2026-05-15",
        "surface_sha256": {
            "/releases/rc1-p0-bootstrap/accounting_csv_profiles.json": "stalestalestale",
        },
    }
    _write_manifest(workspace, manifest_payload)
    _write_well_known(workspace, _baseline_well_known("0" * 64))

    result = _run(workspace)
    assert result.returncode == 0, result.stderr
    plan = json.loads(result.stdout)
    assert plan["surface_sha_refreshed"] is True

    refreshed = json.loads((workspace / MANIFEST_REL).read_text(encoding="utf-8"))
    assert (
        refreshed["surface_sha256"]["/releases/rc1-p0-bootstrap/accounting_csv_profiles.json"]
        == actual_surface_sha
    )


def test_missing_manifest_returns_error(workspace: Path) -> None:
    # only well-known exists -- manifest is missing on purpose
    _write_well_known(workspace, _baseline_well_known("0" * 64))
    result = _run(workspace)
    assert result.returncode == 1
    err = json.loads(result.stderr)
    assert err["status"] == "error"
    assert err["reason"] == "manifest_missing"
