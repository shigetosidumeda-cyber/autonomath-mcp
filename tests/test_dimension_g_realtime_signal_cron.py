"""Wave 46 dim G — tests for the realtime_signal maintenance cron.

Closes the `cron MISSING` finding from `docs/audit/dim19_audit_2026-05-12.md`
(dim G 4.50/10) by:

  1. Asserting the cron script exists at the expected path so
     `scripts/ops/dimension_audit_v2.py` cron_globs hit lands.
  2. Asserting the workflow YAML exists at the expected path so the
     fallback workflow-folder check in the same audit also hits.
  3. Exercising the rule-based behavior end-to-end against a tiny fixture
     autonomath.db with migration 263 applied.
  4. Asserting no LLM API imports leaked into the cron file (constraint
     parity with `test_no_llm_imports_in_dim_g_h`).

NO LLM call, NO httpx, NO network — pure stdlib + sqlite3.
"""

from __future__ import annotations

import importlib.util
import pathlib
import re
import sqlite3
import sys
from datetime import UTC, datetime, timedelta

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
CRON_PATH = (
    REPO_ROOT / "scripts" / "cron" / "maintain_realtime_signal_subscribers.py"
)
WORKFLOW_PATH = (
    REPO_ROOT / ".github" / "workflows" / "realtime-signal-maintenance-daily.yml"
)
MIG_263 = (
    REPO_ROOT / "scripts" / "migrations" / "263_realtime_signal_subscribers.sql"
)


def _load_cron_module():
    spec = importlib.util.spec_from_file_location(
        "_maintain_realtime_signal_subscribers", CRON_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load cron module")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_cron_file_exists_at_expected_path() -> None:
    """Audit cron_globs require a file with 'realtime-signal' substring."""
    assert CRON_PATH.exists(), f"missing cron file: {CRON_PATH}"
    # Audit cron_glob substring match (`'realtime-signal' in filename`) is
    # actually satisfied by the workflow YAML, not this Python script. The
    # script keeps an underscore for Python import convention; the YAML
    # carries the hyphenated form. Both files must exist for the audit lift.
    assert "realtime_signal" in CRON_PATH.name


def test_workflow_file_exists_with_hyphenated_glob() -> None:
    """dimension_audit_v2.py cron_globs=('realtime-signal',) — needs hyphen."""
    assert WORKFLOW_PATH.exists(), f"missing workflow: {WORKFLOW_PATH}"
    assert "realtime-signal" in WORKFLOW_PATH.name


def test_no_llm_imports_in_cron() -> None:
    """Parity with feedback_no_operator_llm_api.

    Patterns deliberately scoped to ``import`` / ``from`` statements + the
    env-var literal references so docstring prose like
    ``feedback_no_operator_llm_api`` or ``claude_agent_sdk`` does not false-
    positive — same approach as ``tests/test_no_llm_in_production.py``.
    """
    patterns = (
        re.compile(r"^\s*import\s+anthropic\b", re.MULTILINE),
        re.compile(r"^\s*from\s+anthropic\b", re.MULTILINE),
        re.compile(r"^\s*import\s+openai\b", re.MULTILINE),
        re.compile(r"^\s*from\s+openai\b", re.MULTILINE),
        re.compile(r"^\s*import\s+google\.generativeai\b", re.MULTILINE),
        re.compile(r"^\s*from\s+google\.generativeai\b", re.MULTILINE),
        re.compile(r"^\s*import\s+claude_agent_sdk\b", re.MULTILINE),
        re.compile(r"^\s*from\s+claude_agent_sdk\b", re.MULTILINE),
        re.compile(r"os\.environ\[['\"]ANTHROPIC_API_KEY['\"]\]"),
        re.compile(r"os\.environ\[['\"]OPENAI_API_KEY['\"]\]"),
        re.compile(r"os\.environ\[['\"]GEMINI_API_KEY['\"]\]"),
    )
    text = CRON_PATH.read_text(encoding="utf-8")
    for pat in patterns:
        assert pat.search(text) is None, f"LLM marker {pat.pattern!r} in cron"


@pytest.fixture
def fixture_db(tmp_path: pathlib.Path) -> pathlib.Path:
    db_path = tmp_path / "autonomath.db"
    conn = sqlite3.connect(db_path)
    sql = MIG_263.read_text(encoding="utf-8")
    conn.executescript(sql)
    # 3 subscribers: one healthy, one stale (failure_count=5), one disabled.
    now = datetime.now(UTC).isoformat()
    old = (datetime.now(UTC) - timedelta(days=180)).isoformat()
    rows = [
        ("hash_healthy", "amendment", "{}", "https://example.com/ok",
         "secret_a", "active", 0, now),
        ("hash_stale", "amendment", "{}", "https://example.com/stale",
         "secret_b", "active", 5, now),
        ("hash_disabled", "amendment", "{}", "https://example.com/disabled",
         "secret_c", "disabled", 9, now),
    ]
    conn.executemany(
        """INSERT INTO am_realtime_subscribers
            (api_key_hash, target_kind, filter_json, webhook_url,
             signature_secret, status, failure_count, updated_at)
           VALUES (?,?,?,?,?,?,?,?)""",
        rows,
    )
    # 1 fresh dispatch row + 1 ancient row that should be pruned.
    conn.executemany(
        """INSERT INTO am_realtime_dispatch_history
            (subscriber_id, target_kind, signal_id, status_code,
             attempt_count, created_at)
           VALUES (?,?,?,?,?,?)""",
        [
            (1, "amendment", "sig_fresh", 200, 1, now),
            (1, "amendment", "sig_ancient", 500, 3, old),
        ],
    )
    conn.commit()
    conn.close()
    return db_path


def test_dry_run_does_not_mutate(fixture_db: pathlib.Path) -> None:
    mod = _load_cron_module()
    payload = mod.run(db_path=fixture_db, retention_days=90, dry_run=True)
    assert payload["skipped"] is False
    assert payload["dry_run"] is True
    assert payload["stale_disabled"] == 1
    assert payload["history_pruned"] == 1
    # Verify nothing actually changed.
    conn = sqlite3.connect(fixture_db)
    cur = conn.execute(
        "SELECT status FROM am_realtime_subscribers WHERE api_key_hash = 'hash_stale'",
    ).fetchone()
    assert cur[0] == "active"
    cnt = conn.execute(
        "SELECT COUNT(*) FROM am_realtime_dispatch_history",
    ).fetchone()
    assert cnt[0] == 2
    conn.close()


def test_real_run_disables_stale_and_prunes_history(
    fixture_db: pathlib.Path,
) -> None:
    mod = _load_cron_module()
    payload = mod.run(db_path=fixture_db, retention_days=90, dry_run=False)
    assert payload["stale_disabled"] == 1
    assert payload["history_pruned"] == 1
    conn = sqlite3.connect(fixture_db)
    conn.row_factory = sqlite3.Row
    stale_row = conn.execute(
        "SELECT status, disabled_reason FROM am_realtime_subscribers "
        "WHERE api_key_hash = 'hash_stale'",
    ).fetchone()
    assert stale_row["status"] == "disabled"
    assert stale_row["disabled_reason"] == "stale_failure_streak"
    healthy = conn.execute(
        "SELECT status FROM am_realtime_subscribers WHERE api_key_hash = 'hash_healthy'",
    ).fetchone()
    assert healthy["status"] == "active"
    rows = conn.execute(
        "SELECT signal_id FROM am_realtime_dispatch_history ORDER BY signal_id",
    ).fetchall()
    assert [r["signal_id"] for r in rows] == ["sig_fresh"]
    conn.close()


def test_skipped_when_db_missing(tmp_path: pathlib.Path) -> None:
    mod = _load_cron_module()
    missing = tmp_path / "absent.db"
    payload = mod.run(db_path=missing, retention_days=90, dry_run=False)
    assert payload["skipped"] is True
    assert payload["reason"] == "db_missing"
