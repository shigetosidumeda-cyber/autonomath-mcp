"""Wave 48 tick#2 — entrypoint.sh §4.x x402 endpoint prod seed runner.

Contract guarded by this file
-----------------------------
1.  The entrypoint must invoke ``scripts/etl/seed_x402_endpoints.py`` against
    the autonomath DB after schema_guard (so the seeder operates on a
    structurally-valid schema), and must DO SO IDEMPOTENTLY — re-running
    boot a second time is a no-op for already-seeded rows.
2.  The seed block must be best-effort: a seeder failure logs (``err``) but
    does NOT ``exit 1``. Production stays alive serving the rest of the API,
    /v1/* x402-gated routes degrade to 404 until the next boot.
3.  The seed block must be skipped when autonomath.db is absent (fresh
    volume / R2 bootstrap still in flight) — the seeder requires the
    ``am_x402_endpoint_config`` table.
4.  No PRAGMA quick_check / integrity_check is added by the new block (per
    ``feedback_no_quick_check_on_huge_sqlite`` — boot must stay under the
    Fly 60s health-check grace; the seeder is O(5 SELECT + ≤5 INSERT)).
5.  The seed runner must be wired BEFORE the final ``exec "$@"`` handoff.

Test strategy
-------------
The test mirrors ``tests/test_entrypoint_vec0_boot_gate.py``: parse the
production ``entrypoint.sh`` and assert the W48.x402 block is present,
correctly ordered, and structurally safe. A live execution test creates a
tmp autonomath.db with the ``am_x402_endpoint_config`` schema baked in,
runs ``seed_x402_endpoints.py`` directly twice, and verifies idempotency
(no-op on the second invocation). This exercises the script the entrypoint
calls without forcing a 9 GB R2 download in CI.
"""
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ENTRYPOINT = REPO_ROOT / "entrypoint.sh"
SEED_SCRIPT = REPO_ROOT / "scripts/etl/seed_x402_endpoints.py"
MIGRATION = REPO_ROOT / "scripts/migrations/282_x402_payment.sql"


def _entrypoint_text() -> str:
    return ENTRYPOINT.read_text(encoding="utf-8")


def test_entrypoint_invokes_seed_x402_endpoints_after_schema_guard() -> None:
    text = _entrypoint_text()
    assert "[W48.x402]" in text, "W48.x402 banner missing"
    invocation = "python /app/scripts/etl/seed_x402_endpoints.py"
    assert invocation in text, f"missing {invocation!r}"
    # Must run AFTER schema_guard on autonomath.db AND BEFORE final exec.
    guard_marker = 'python /app/scripts/schema_guard.py "$DB_PATH" autonomath'
    exec_marker = 'exec "$@"'
    assert guard_marker in text
    assert exec_marker in text
    assert text.index(guard_marker) < text.index(invocation)
    assert text.index(invocation) < text.index(exec_marker)


def test_entrypoint_seed_block_is_best_effort_not_boot_fatal() -> None:
    """A seed failure must not exit 1 — boot continues; /v1/* gated stays 404."""
    runtime = _block_runtime_lines(_entrypoint_text())
    assert "exit 1" not in runtime, "W48.x402 block must not exit-1 on seed failure"
    assert "err " in runtime or "err\t" in runtime, "block must err-log on failure"
    # The narrative phrasing lives in the comment header; runtime line must
    # explicitly chain the seeder with `|| err` so a non-zero exit becomes
    # a logged error rather than a propagated failure.
    assert "|| \\" in runtime or "|| err" in runtime or "|| log" in runtime


def test_entrypoint_seed_block_skips_when_db_absent() -> None:
    runtime = _block_runtime_lines(_entrypoint_text())
    # Skip path when $DB_PATH absent.
    assert '[ -s "$DB_PATH" ]' in runtime, "must guard on autonomath.db presence"
    assert "x402 endpoint seed skipped" in runtime or "DB absent" in runtime


def _block_runtime_lines(text: str) -> str:
    """Slice the W48.x402 block and strip leading-`#` comment lines.

    The block contains a multi-paragraph comment header that references
    `PRAGMA quick_check` deliberately (memory invariant); we must not match
    on those documentation lines, only on executable shell.
    """
    start = text.index("# 4.x. W48.x402")
    end = text.index("# 5. Hand off to CMD", start)
    block = text[start:end]
    runtime = "\n".join(
        line for line in block.splitlines() if not line.lstrip().startswith("#")
    )
    return runtime


def test_entrypoint_seed_block_omits_pragma_quick_check() -> None:
    """`feedback_no_quick_check_on_huge_sqlite`: zero PRAGMA probes in EXECUTED shell."""
    runtime = _block_runtime_lines(_entrypoint_text())
    assert "PRAGMA quick_check" not in runtime
    assert "PRAGMA integrity_check" not in runtime
    assert "sqlite3 " not in runtime, "no inline sqlite3 calls — let the python seeder do all DB work"


def test_entrypoint_seed_block_does_not_pass_force_flag() -> None:
    """Per `feedback_destruction_free_organization`: idempotent additive seed only,
    never --force at boot (which would clobber operator-set repricing)."""
    runtime = _block_runtime_lines(_entrypoint_text())
    assert "--force" not in runtime


def test_seed_script_idempotent_against_fresh_schema(tmp_path: Path) -> None:
    """Live exec: seed an empty am_x402_endpoint_config twice, assert 2nd is all-noop."""
    db = tmp_path / "autonomath.db"
    # Confirm the canonical migration declares the schema we mirror inline
    # below (so a future schema change forces an intentional test update).
    mig_text = MIGRATION.read_text(encoding="utf-8")
    assert (
        "CREATE TABLE IF NOT EXISTS am_x402_endpoint_config" in mig_text
    ), "migration 282 must define am_x402_endpoint_config"
    # Minimal schema the seeder needs. Keep this in sync with 282_x402_payment.sql.
    create_stmt = """
    CREATE TABLE IF NOT EXISTS am_x402_endpoint_config (
        endpoint_path          TEXT PRIMARY KEY,
        required_amount_usdc   REAL NOT NULL,
        expires_after_seconds  INTEGER NOT NULL DEFAULT 3600,
        enabled                INTEGER NOT NULL DEFAULT 1,
        created_at             TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
        updated_at             TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
    );
    """
    conn = sqlite3.connect(str(db))
    try:
        conn.executescript(create_stmt)
        conn.commit()
    finally:
        conn.close()

    def _run() -> dict:
        proc = subprocess.run(
            [sys.executable, str(SEED_SCRIPT), "--db", str(db)],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        assert proc.returncode == 0, f"seed exited rc={proc.returncode}\n{proc.stderr}"
        last_line = proc.stdout.strip().splitlines()[-1]
        return json.loads(last_line)

    first = _run()
    assert first["dim"] == "V" and first["wave"] == 47
    assert len(first["endpoints"]) == 5
    assert {ep["action"] for ep in first["endpoints"]} == {"inserted"}

    second = _run()
    assert len(second["endpoints"]) == 5
    assert {ep["action"] for ep in second["endpoints"]} == {"noop"}, (
        "re-run must be all-noop for true idempotency"
    )

    conn = sqlite3.connect(str(db))
    try:
        row_count = conn.execute(
            "SELECT COUNT(*) FROM am_x402_endpoint_config"
        ).fetchone()[0]
        paths = sorted(
            r[0]
            for r in conn.execute("SELECT endpoint_path FROM am_x402_endpoint_config")
        )
    finally:
        conn.close()
    assert row_count == 5
    assert paths == [
        "/v1/audit_workpaper",
        "/v1/cases",
        "/v1/programs",
        "/v1/search",
        "/v1/semantic_search",
    ]
