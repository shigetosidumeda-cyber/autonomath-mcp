"""Wave 46.C — jpcite.db ⇄ autonomath.db compatibility symlink tests.

The entrypoint section §1.4 is an *additive overlay*: it never deletes or
renames either file, only creates a symlink when the alias path is missing
(plan: `docs/_internal/W46_autonomath_to_jpcite_rename_plan.md` §3.2 / memory
`project_jpcite_internal_autonomath_rename`).

These tests do **not** invoke a real 8 GB database — per
`feedback_no_quick_check_on_huge_sqlite`, only inode-level ops are exercised
so the boot-time cost stays O(1).  The script is rewritten to point at a
tmp_path-rooted `/data` and run with `bash entrypoint.sh true` so §1.4
executes cleanly without touching the rest of the boot chain.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
ENTRYPOINT = REPO_ROOT / "entrypoint.sh"


# ---------- static text assertions (no subprocess) ---------- #


def test_w46c_block_present_in_entrypoint() -> None:
    text = ENTRYPOINT.read_text(encoding="utf-8")
    assert "# 1.4. jpcite ⇄ autonomath compatibility symlink (Wave 46.C)" in text
    assert 'JPCITE_DB="${JPCITE_DB_PATH:-/data/jpcite.db}"' in text
    assert 'AM_DB="${AUTONOMATH_DB_PATH:-/data/autonomath.db}"' in text


def test_w46c_block_uses_ln_sf_only_and_no_destructive_op() -> None:
    text = ENTRYPOINT.read_text(encoding="utf-8")
    # Extract just the §1.4 block.
    start = text.index("# 1.4. jpcite ⇄ autonomath compatibility symlink")
    end = text.index("# Helper: compute SHA256")
    block = text[start:end]
    assert "ln -sf" in block
    # Destruction-free contract: no rm / mv / DROP / unlink inside the block.
    for forbidden in ("rm ", " mv ", "unlink", "DROP", "DELETE FROM"):
        assert forbidden not in block, f"forbidden token {forbidden!r} in W46.C block"


def test_w46c_block_runs_before_seed_sync_and_r2_bootstrap() -> None:
    text = ENTRYPOINT.read_text(encoding="utf-8")
    w46c_index = text.index("# 1.4. jpcite ⇄ autonomath compatibility symlink")
    seed_index = text.index("# 1.5. Seed data sync")
    r2_index = text.index("# 2. R2 bootstrap")
    assert w46c_index < seed_index < r2_index


def test_w46c_block_has_no_quick_check_or_integrity_probe() -> None:
    """Per feedback_no_quick_check_on_huge_sqlite, §1.4 must not invoke any
    SQLite probe against the (9.7 GB) DB.  Comments may reference the rule
    by name, but the executable surface must contain zero probe calls."""
    text = ENTRYPOINT.read_text(encoding="utf-8")
    start = text.index("# 1.4. jpcite ⇄ autonomath compatibility symlink")
    end = text.index("# Helper: compute SHA256")
    block = text[start:end]
    # Strip comment-only lines before scanning for forbidden tokens.
    executable_lines = [
        line for line in block.splitlines() if line.strip() and not line.lstrip().startswith("#")
    ]
    executable = "\n".join(executable_lines)
    assert "PRAGMA" not in executable
    assert "quick_check" not in executable
    assert "integrity_check" not in executable
    assert "sqlite3" not in executable


# ---------- runtime subprocess assertions ---------- #


def _safe_entrypoint(tmp_path: Path) -> Path:
    """Rewrite entrypoint.sh so /data, /seed and /app/scripts resolve under tmp_path."""
    data_dir = tmp_path / "data"
    seed_dir = tmp_path / "seed"
    app_scripts_dir = tmp_path / "app" / "scripts"
    app_scripts_dir.mkdir(parents=True, exist_ok=True)
    seed_dir.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)
    script = tmp_path / "entrypoint.sh"
    text = ENTRYPOINT.read_text(encoding="utf-8")
    text = text.replace("/data", str(data_dir))
    text = text.replace("/seed", str(seed_dir))
    text = text.replace("/app/scripts", str(app_scripts_dir))
    text = text.replace("python ", f'"{sys.executable}" ')
    script.write_text(text, encoding="utf-8")
    script.chmod(0o755)
    return script


def _entrypoint_env(tmp_path: Path) -> dict[str, str]:
    env = os.environ.copy()
    for key in (
        "AUTONOMATH_DB_URL",
        "AUTONOMATH_DB_SHA256",
        "AUTONOMATH_BOOTSTRAP_MODE",
        "AUTONOMATH_ENABLED",
        "DATA_SEED_VERSION",
        "JPINTEL_FORCE_SEED_OVERWRITE",
        "JPCITE_DB_PATH",
    ):
        env.pop(key, None)
    env["AUTONOMATH_DB_PATH"] = str(tmp_path / "data" / "autonomath.db")
    env["JPCITE_DB_PATH"] = str(tmp_path / "data" / "jpcite.db")
    env["AUTONOMATH_BOOT_MIGRATION_MODE"] = "off"
    return env


def _run(script: Path, env: dict[str, str], *, timeout: float = 15.0) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(script), "true"],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )


def test_w46c_creates_jpcite_symlink_when_autonomath_present_and_jpcite_absent(tmp_path: Path) -> None:
    script = _safe_entrypoint(tmp_path)
    env = _entrypoint_env(tmp_path)
    am_db = Path(env["AUTONOMATH_DB_PATH"])
    am_db.write_bytes(b"fake-autonomath-db-content")
    jc_db = Path(env["JPCITE_DB_PATH"])
    assert not jc_db.exists()

    result = _run(script, env)

    assert result.returncode == 0, result.stderr
    assert jc_db.is_symlink()
    assert os.readlink(jc_db) == str(am_db)
    # Original file untouched.
    assert am_db.read_bytes() == b"fake-autonomath-db-content"
    assert "[W46.C] symlink created" in result.stdout


def test_w46c_creates_reverse_symlink_when_jpcite_present_and_autonomath_absent(tmp_path: Path) -> None:
    script = _safe_entrypoint(tmp_path)
    env = _entrypoint_env(tmp_path)
    jc_db = Path(env["JPCITE_DB_PATH"])
    jc_db.write_bytes(b"jpcite-canonical-content")
    am_db = Path(env["AUTONOMATH_DB_PATH"])
    assert not am_db.exists()

    result = _run(script, env)

    assert result.returncode == 0, result.stderr
    assert am_db.is_symlink()
    assert os.readlink(am_db) == str(jc_db)
    # Original file untouched.
    assert jc_db.read_bytes() == b"jpcite-canonical-content"
    assert "[W46.C] reverse symlink created" in result.stdout


def test_w46c_is_noop_when_both_paths_are_same_inode(tmp_path: Path) -> None:
    script = _safe_entrypoint(tmp_path)
    env = _entrypoint_env(tmp_path)
    am_db = Path(env["AUTONOMATH_DB_PATH"])
    jc_db = Path(env["JPCITE_DB_PATH"])
    am_db.write_bytes(b"shared")
    os.symlink(am_db, jc_db)
    # Sanity: same inode now.
    assert am_db.stat().st_ino == jc_db.stat().st_ino

    result = _run(script, env)

    assert result.returncode == 0, result.stderr
    # Symlink unchanged.
    assert jc_db.is_symlink()
    assert os.readlink(jc_db) == str(am_db)
    # Split-brain warning must NOT fire.
    assert "[W46.C] split-brain" not in result.stderr


def test_w46c_logs_split_brain_when_two_distinct_files(tmp_path: Path) -> None:
    script = _safe_entrypoint(tmp_path)
    env = _entrypoint_env(tmp_path)
    am_db = Path(env["AUTONOMATH_DB_PATH"])
    jc_db = Path(env["JPCITE_DB_PATH"])
    am_db.write_bytes(b"autonomath-canonical")
    jc_db.write_bytes(b"jpcite-different")
    assert am_db.stat().st_ino != jc_db.stat().st_ino

    result = _run(script, env)

    # Boot still succeeds (downstream defaults to AM_DB).
    assert result.returncode == 0, result.stderr
    assert "[W46.C] split-brain" in result.stderr
    # Neither file is deleted/rewritten.
    assert am_db.read_bytes() == b"autonomath-canonical"
    assert jc_db.read_bytes() == b"jpcite-different"


def test_w46c_is_noop_when_neither_path_exists(tmp_path: Path) -> None:
    """Cold-start case: §2 R2 bootstrap is responsible for creating $DB_PATH;
    §1.4 must not pre-create either path or fail when both are absent."""
    script = _safe_entrypoint(tmp_path)
    env = _entrypoint_env(tmp_path)
    am_db = Path(env["AUTONOMATH_DB_PATH"])
    jc_db = Path(env["JPCITE_DB_PATH"])
    assert not am_db.exists() and not jc_db.exists()

    result = _run(script, env)

    assert result.returncode == 0, result.stderr
    assert not am_db.exists()
    assert not jc_db.exists()
    # No symlink-created log line should appear.
    assert "[W46.C] symlink created" not in result.stdout
    assert "[W46.C] reverse symlink created" not in result.stdout


def test_w46c_block_boots_well_under_fly_grace_window(tmp_path: Path) -> None:
    """Per feedback_no_quick_check_on_huge_sqlite, §1.4 must add ~0s to boot.
    We run the rewritten entrypoint with both paths set up and assert wall
    clock < 10s on the test runner (Fly grace is 60s)."""
    import time

    script = _safe_entrypoint(tmp_path)
    env = _entrypoint_env(tmp_path)
    am_db = Path(env["AUTONOMATH_DB_PATH"])
    am_db.write_bytes(b"x" * 1024)  # tiny dummy; real prod DB is 9.7 GB

    t0 = time.monotonic()
    result = _run(script, env, timeout=15.0)
    elapsed = time.monotonic() - t0

    assert result.returncode == 0, result.stderr
    assert elapsed < 10.0, f"entrypoint §1.4 region took {elapsed:.2f}s (>10s budget)"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
