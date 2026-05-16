"""Test scaffolding for the Cloudflare Pages rollback shell scripts.

These tests are intentionally lightweight: they assert the scripts exist,
are executable, pass `bash -n` syntax check, and (for the rollback script)
that running the embedded Python rewrite block against a fixture pointer
produces a valid JSON file with the expected fields.

No network, no real production pointer mutation — the rollback test
operates entirely on a tmp_path copy of runtime_pointer.json.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_OPS = REPO_ROOT / "scripts" / "ops"
ROLLBACK_SCRIPT = SCRIPTS_OPS / "rollback_capsule.sh"
LIST_SCRIPT = SCRIPTS_OPS / "list_capsules.sh"
SMOKE_SCRIPT = SCRIPTS_OPS / "post_deploy_smoke.sh"
LIVE_POINTER = REPO_ROOT / "site" / "releases" / "current" / "runtime_pointer.json"


@pytest.mark.parametrize("script", [ROLLBACK_SCRIPT, LIST_SCRIPT, SMOKE_SCRIPT])
def test_script_exists(script: Path) -> None:
    assert script.is_file(), f"missing script: {script}"


@pytest.mark.parametrize("script", [ROLLBACK_SCRIPT, LIST_SCRIPT, SMOKE_SCRIPT])
def test_script_bash_syntax_check(script: Path) -> None:
    """`bash -n` does a no-exec syntax pass — catches obvious parser errors."""
    result = subprocess.run(
        ["bash", "-n", str(script)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"bash -n failed for {script}: stderr={result.stderr}"


@pytest.mark.parametrize("script", [ROLLBACK_SCRIPT, LIST_SCRIPT, SMOKE_SCRIPT])
def test_script_has_shebang(script: Path) -> None:
    first_line = script.read_text(encoding="utf-8").splitlines()[0]
    assert first_line.startswith("#!"), f"missing shebang: {script}"
    assert "bash" in first_line, f"shebang is not bash: {script} -> {first_line}"


def test_rollback_script_rejects_missing_arg() -> None:
    """No capsule id => exit 2."""
    result = subprocess.run(
        ["bash", str(ROLLBACK_SCRIPT)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2, (
        f"expected exit 2 when no arg given, got {result.returncode}; stderr={result.stderr}"
    )


def test_rollback_script_rewrites_pointer_against_tmp_copy(tmp_path: Path) -> None:
    """End-to-end rewrite on a copy of the live pointer.

    We replicate the repo layout under tmp_path so the script's own
    REPO_ROOT resolution still works, and verify the rewritten JSON.
    """
    if not LIVE_POINTER.is_file():
        pytest.skip("live runtime_pointer.json not present in checkout")

    tmp_repo = tmp_path / "repo"
    tmp_scripts = tmp_repo / "scripts" / "ops"
    tmp_releases_current = tmp_repo / "site" / "releases" / "current"
    tmp_scripts.mkdir(parents=True)
    tmp_releases_current.mkdir(parents=True)
    shutil.copy2(ROLLBACK_SCRIPT, tmp_scripts / "rollback_capsule.sh")
    os.chmod(
        tmp_scripts / "rollback_capsule.sh",
        os.stat(tmp_scripts / "rollback_capsule.sh").st_mode
        | stat.S_IXUSR
        | stat.S_IXGRP
        | stat.S_IXOTH,
    )
    shutil.copy2(LIVE_POINTER, tmp_releases_current / "runtime_pointer.json")

    target_id = "rc0-rollback-test-2026-05-15"
    result = subprocess.run(
        ["bash", str(tmp_scripts / "rollback_capsule.sh"), target_id],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        f"rollback script failed: stdout={result.stdout} stderr={result.stderr}"
    )

    rewritten = json.loads(
        (tmp_releases_current / "runtime_pointer.json").read_text(encoding="utf-8")
    )
    assert rewritten["active_capsule_id"] == target_id
    assert (
        rewritten["active_capsule_manifest"]
        == "/releases/rc0-rollback-test/release_capsule_manifest.json"
    )
    # Safety flags must remain locked closed regardless of input.
    assert rewritten["aws_runtime_dependency_allowed"] is False
    assert rewritten["live_aws_commands_allowed"] is False

    # Backup must exist for one-step recovery.
    bak = tmp_releases_current / "runtime_pointer.json.bak"
    assert bak.is_file(), "rollback script must leave a .bak file"
    bak_doc = json.loads(bak.read_text(encoding="utf-8"))
    # The backup is the pre-rewrite content, so it should NOT carry the
    # new target_id (unless the live pointer already happened to match).
    assert bak_doc.get("active_capsule_id") != target_id
