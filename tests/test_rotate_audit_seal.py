"""Secret-leak mitigations for ``tools/offline/rotate_audit_seal.py``.

W2-9 H-2 hardening tests. Pinned invariants:

1. ``--output-file PATH`` writes the merged JSON to PATH with chmod 0600
   and emits NOTHING on stdout (so the secret never enters the operator's
   shell history / scrollback / tmux capture log).
2. ``--dry-run`` (with or without ``--output-file``) NEVER prints the
   merged JSON anywhere — the secret string must not appear in stdout
   nor in the file. Operator gets only a count + nudge on stderr.
3. ``--clear-old-keys-after N`` keeps at most N retired rows in the
   ``audit_seal_keys`` registry (active row always preserved).
4. The legacy stdout path still works (for ``| pbcopy`` pipelines) and
   prints a stderr WARNING reminding the operator to clear shell history.

We exercise the script as a subprocess so we cover the full argv +
``main()`` wiring (the dangerous surface). The rotate function itself is
imported once for the registry-sweep regression.
"""

from __future__ import annotations

import json
import os
import sqlite3
import stat
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "tools" / "offline" / "rotate_audit_seal.py"


def _make_registry_db(path: Path) -> None:
    """Create an empty ``audit_seal_keys`` registry table at ``path``."""
    conn = sqlite3.connect(str(path))
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS audit_seal_keys (
                key_version    INTEGER PRIMARY KEY,
                secret_argon2  TEXT,
                activated_at   TEXT NOT NULL,
                retired_at     TEXT,
                last_seen_at   TEXT,
                notes          TEXT
            );
            """
        )
        conn.commit()
    finally:
        conn.close()


def _run_script(*args: str, env_extra: dict | None = None) -> subprocess.CompletedProcess:
    """Invoke the rotation script as a subprocess.

    We deliberately drop ``JPINTEL_AUDIT_SEAL_KEYS`` from the inherited
    env so the test starts from the legacy single-key state — otherwise
    the rotation would carry over arbitrary developer-laptop secrets
    into the merged JSON the test inspects.
    """
    env = os.environ.copy()
    env.pop("JPINTEL_AUDIT_SEAL_KEYS", None)
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


@pytest.fixture
def fresh_db(tmp_path: Path) -> Path:
    db = tmp_path / "rotate.db"
    _make_registry_db(db)
    return db


# ---------------------------------------------------------------------------
# 1. --output-file writes 0600 file, stdout stays empty.
# ---------------------------------------------------------------------------
def test_output_file_creates_chmod_600_and_empty_stdout(fresh_db: Path, tmp_path: Path) -> None:
    out = tmp_path / "keys.json"
    proc = _run_script("--db", str(fresh_db), "--output-file", str(out))

    assert proc.returncode == 0, proc.stderr
    # Stdout must be COMPLETELY empty when --output-file is used; the
    # secret is sensitive and shells record stdout.
    assert proc.stdout == "", f"unexpected stdout: {proc.stdout!r}"

    # File exists with chmod 0600 (owner rw only).
    assert out.exists()
    mode = stat.S_IMODE(out.stat().st_mode)
    assert mode == 0o600, f"expected 0o600, got {oct(mode)}"

    # Content is the merged JSON array.
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert isinstance(payload, list) and len(payload) >= 1
    active = [k for k in payload if k.get("retired_at") is None]
    assert len(active) == 1, payload
    assert isinstance(active[0]["s"], str) and len(active[0]["s"]) >= 32

    # Stderr carries the operator instructions, not the secret itself.
    assert "chmod 600" in proc.stderr
    assert active[0]["s"] not in proc.stderr


# ---------------------------------------------------------------------------
# 2. --dry-run never emits secret material anywhere.
# ---------------------------------------------------------------------------
def test_dry_run_emits_no_secret_to_stdout(fresh_db: Path) -> None:
    proc = _run_script("--db", str(fresh_db), "--dry-run")
    assert proc.returncode == 0, proc.stderr
    # No JSON, no secret on stdout.
    assert proc.stdout == "", f"dry-run leaked stdout: {proc.stdout!r}"
    # Stderr summary is informational only.
    assert "dry-run" in proc.stderr
    assert "would be rotated" in proc.stderr
    # base64-urlsafe secret is 64 chars; ensure no obvious secret token
    # made it onto stderr (we check for "s\":\" JSON marker which would
    # appear if the merged array were dumped by mistake).
    assert '"s":' not in proc.stderr

    # And the registry must NOT have been mutated.
    conn = sqlite3.connect(str(fresh_db))
    try:
        rows = conn.execute("SELECT COUNT(*) FROM audit_seal_keys").fetchone()
    finally:
        conn.close()
    assert rows[0] == 0, "dry-run unexpectedly inserted a registry row"


def test_dry_run_with_output_file_still_writes_no_secret(fresh_db: Path, tmp_path: Path) -> None:
    """``--dry-run --output-file`` is a sharp-edge combination — secret
    must still NOT be written, otherwise dry-run would silently commit
    the secret to disk."""
    out = tmp_path / "should_not_exist.json"
    proc = _run_script("--db", str(fresh_db), "--dry-run", "--output-file", str(out))
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == ""
    # Either the file is absent or, if created, contains no secret —
    # the conservative contract is "absent".
    assert not out.exists(), f"dry-run wrote file: {out}"


# ---------------------------------------------------------------------------
# 3. Legacy stdout path still works + carries the warning.
# ---------------------------------------------------------------------------
def test_legacy_stdout_path_still_works_with_warning(fresh_db: Path) -> None:
    proc = _run_script("--db", str(fresh_db))
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout.strip())
    assert isinstance(payload, list) and len(payload) >= 1
    # The shell-history warning MUST land on stderr so it is visible
    # even when stdout is piped to pbcopy / a file.
    assert "WARNING" in proc.stderr
    assert "history" in proc.stderr.lower()


# ---------------------------------------------------------------------------
# 4. --clear-old-keys-after sweeps retired rows.
# ---------------------------------------------------------------------------
def test_clear_old_keys_after_sweeps_retired_rows(fresh_db: Path, tmp_path: Path) -> None:
    # Run rotation 4 times to build up retired rows.
    for i in range(4):
        out = tmp_path / f"keys_{i}.json"
        proc = _run_script("--db", str(fresh_db), "--output-file", str(out))
        assert proc.returncode == 0, proc.stderr

    conn = sqlite3.connect(str(fresh_db))
    try:
        before = conn.execute("SELECT COUNT(*) FROM audit_seal_keys").fetchone()[0]
    finally:
        conn.close()
    assert before == 4

    # 5th rotation with --clear-old-keys-after 1: keep 1 retired + the
    # newly-active row = 2 total.
    out = tmp_path / "keys_final.json"
    proc = _run_script(
        "--db",
        str(fresh_db),
        "--output-file",
        str(out),
        "--clear-old-keys-after",
        "1",
    )
    assert proc.returncode == 0, proc.stderr

    conn = sqlite3.connect(str(fresh_db))
    try:
        rows = conn.execute(
            "SELECT key_version, retired_at FROM audit_seal_keys ORDER BY key_version"
        ).fetchall()
    finally:
        conn.close()

    # The currently-active row (highest key_version) is always preserved.
    active = [r for r in rows if r[1] is None]
    retired = [r for r in rows if r[1] is not None]
    assert len(active) == 1, rows
    assert len(retired) == 1, rows
    # Sanity: total = 1 (kept retired) + 1 (active) = 2.
    assert len(rows) == 2


def test_clear_old_keys_after_rejects_zero(fresh_db: Path) -> None:
    proc = _run_script("--db", str(fresh_db), "--clear-old-keys-after", "0", "--dry-run")
    assert proc.returncode == 2, (proc.stdout, proc.stderr)
    assert "positive integer" in proc.stderr
