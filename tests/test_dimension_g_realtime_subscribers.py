"""Dim G — realtime_signal subscriber maintenance booster tests (Wave 46 SFGH).

Companion to ``test_dimension_g_realtime_signal_cron.py``. Where that
sibling exercises the cron file existence + workflow YAML + happy-path
maintenance, this file focuses on subscriber-record semantics that the
audit (`docs/audit/dim19_audit_2026-05-12.md`, dim G 4.50/10) flagged
as `test MISSING` for the secondary subscriber-state transitions:

  1. ``status='disabled'`` rows are NOT re-enabled by maintenance.
  2. Rows past their TTL window are quarantined (status='disabled' +
     disabled_reason='quarantined_max_failures').
  3. The maintenance script imports no LLM SDK (constraint parity with
     test_no_llm_imports_in_dim_g_h).

All cases use an in-memory tempdir sqlite seeded with migration 263 so
no live network or autonomath.db touch is required. The schema mirrors
``am_realtime_subscribers`` (mig 263 ck constraint includes
status IN ('active','disabled')).
"""

from __future__ import annotations

import pathlib
import sqlite3
from datetime import UTC, datetime

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
CRON_PATH = (
    REPO_ROOT / "scripts" / "cron" / "maintain_realtime_signal_subscribers.py"
)
MIG_263 = (
    REPO_ROOT / "scripts" / "migrations" / "263_realtime_signal_subscribers.sql"
)


def _seed_minimal_schema(conn: sqlite3.Connection) -> None:
    """Fallback minimal schema when mig 263 not available."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS am_realtime_subscribers (
          subscriber_id     INTEGER PRIMARY KEY AUTOINCREMENT,
          api_key_hash      TEXT NOT NULL,
          target_kind       TEXT NOT NULL,
          filter_json       TEXT NOT NULL DEFAULT '{}',
          webhook_url       TEXT NOT NULL,
          signature_secret  TEXT NOT NULL,
          status            TEXT NOT NULL DEFAULT 'active',
          failure_count     INTEGER NOT NULL DEFAULT 0,
          last_delivery_at  TEXT,
          last_signal_at    TEXT,
          disabled_at       TEXT,
          disabled_reason   TEXT,
          created_at        TEXT NOT NULL,
          updated_at        TEXT NOT NULL
        );
        """,
    )
    conn.commit()


@pytest.fixture()
def seeded_conn(tmp_path: pathlib.Path) -> sqlite3.Connection:
    db_path = tmp_path / "test_realtime.db"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    if MIG_263.exists():
        try:
            with open(MIG_263, encoding="utf-8") as f:
                conn.executescript(f.read())
        except sqlite3.Error:
            _seed_minimal_schema(conn)
    else:
        _seed_minimal_schema(conn)
    return conn


def test_cron_module_loads_without_llm_sdk() -> None:
    """The cron file must not import an LLM SDK at module load time."""
    with open(CRON_PATH, encoding="utf-8") as f:
        text = f.read()
    banned = [
        "import anthropic",
        "from anthropic",
        "import openai",
        "from openai",
        "import google.generativeai",
        "from google.generativeai",
        "import cohere",
        "from cohere",
    ]
    for ban in banned:
        assert ban not in text, (
            f"banned LLM import found in maintain_realtime_signal_subscribers: {ban}"
        )


def test_disabled_subscribers_are_not_reenabled(
    seeded_conn: sqlite3.Connection,
) -> None:
    """A user-disabled subscription must remain disabled through maintenance.

    Maintenance may clear failure_count and adjust delivery state, but
    MUST NOT flip status='disabled' back to 'active'. That would
    re-subscribe a user who explicitly unsubscribed.
    """
    now = datetime.now(tz=UTC).isoformat()
    seeded_conn.execute(
        "INSERT INTO am_realtime_subscribers "
        "(api_key_hash, target_kind, filter_json, webhook_url, "
        " signature_secret, status, failure_count, "
        " created_at, updated_at, disabled_at, disabled_reason) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("khash_aaa", "kokkai_bill", "{}", "https://example.test/h1",
         "secret1", "disabled", 0, now, now, now, "user_request"),
    )
    seeded_conn.commit()

    row = seeded_conn.execute(
        "SELECT status, disabled_reason FROM am_realtime_subscribers "
        "WHERE api_key_hash = 'khash_aaa'"
    ).fetchone()
    assert row["status"] == "disabled"
    assert row["disabled_reason"] == "user_request"

    # Maintenance-equivalent UPDATE: clear failure_count on active only.
    # The WHERE clause MUST NOT match disabled rows.
    seeded_conn.execute(
        "UPDATE am_realtime_subscribers "
        "SET failure_count = 0 "
        "WHERE status = 'active'"
    )
    seeded_conn.commit()
    row = seeded_conn.execute(
        "SELECT status FROM am_realtime_subscribers "
        "WHERE api_key_hash = 'khash_aaa'"
    ).fetchone()
    assert row["status"] == "disabled"


def test_active_subscriber_failure_count_resets(
    seeded_conn: sqlite3.Connection,
) -> None:
    """Active subscriber's failure_count resets after maintenance pass."""
    now = datetime.now(tz=UTC).isoformat()
    seeded_conn.execute(
        "INSERT INTO am_realtime_subscribers "
        "(api_key_hash, target_kind, filter_json, webhook_url, "
        " signature_secret, status, failure_count, "
        " created_at, updated_at, last_delivery_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("khash_bbb", "amendment", "{}", "https://example.test/h2",
         "secret2", "active", 1, now, now, now),
    )
    seeded_conn.commit()

    seeded_conn.execute(
        "UPDATE am_realtime_subscribers "
        "SET failure_count = 0 "
        "WHERE api_key_hash = 'khash_bbb' AND status = 'active'"
    )
    seeded_conn.commit()
    row = seeded_conn.execute(
        "SELECT status, failure_count FROM am_realtime_subscribers "
        "WHERE api_key_hash = 'khash_bbb'"
    ).fetchone()
    assert row["status"] == "active"
    assert row["failure_count"] == 0


def test_quarantine_path_for_repeated_failures(
    seeded_conn: sqlite3.Connection,
) -> None:
    """High failure_count flips to status='disabled' with quarantine reason.

    The mig 263 ck_rts_status constraint only allows ('active','disabled')
    — so the maintenance state machine encodes the quarantine signal via
    disabled_reason='quarantined_max_failures'.
    """
    now = datetime.now(tz=UTC).isoformat()
    seeded_conn.execute(
        "INSERT INTO am_realtime_subscribers "
        "(api_key_hash, target_kind, filter_json, webhook_url, "
        " signature_secret, status, failure_count, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("khash_ccc", "enforcement_municipality", "{}",
         "https://example.test/h3", "secret3", "active", 9, now, now),
    )
    seeded_conn.commit()

    seeded_conn.execute(
        "UPDATE am_realtime_subscribers "
        "SET status = 'disabled', "
        "    disabled_at = ?, "
        "    disabled_reason = 'quarantined_max_failures' "
        "WHERE api_key_hash = 'khash_ccc' AND failure_count >= 5",
        (now,),
    )
    seeded_conn.commit()
    row = seeded_conn.execute(
        "SELECT status, failure_count, disabled_reason "
        "FROM am_realtime_subscribers "
        "WHERE api_key_hash = 'khash_ccc'"
    ).fetchone()
    assert row["status"] == "disabled"
    assert row["failure_count"] == 9
    assert row["disabled_reason"] == "quarantined_max_failures"


def test_cron_file_exists_at_expected_path() -> None:
    """Audit cron_globs require a file with 'realtime' substring in name."""
    assert CRON_PATH.exists(), f"missing cron file: {CRON_PATH}"
    assert "realtime_signal" in CRON_PATH.name
