"""M15: webhook test rate-limit must persist across workers (SQLite-backed).

Pre-M15 the rate limit lived in `_test_hits: dict[int, list[float]]`
inside `customer_webhooks.py`. With N uvicorn workers each worker owned
its own dict and a customer could exceed the 5/min cap by spreading
test deliveries across workers. This test simulates 2 workers by
calling `_check_test_rate(webhook_id, conn)` directly with two distinct
sqlite3 connections (which is the same observable as two worker
processes — neither owns the other's in-process state, both share the
on-disk DB) and asserts the cap aggregates across both.

Coverage:
  1. wave24_143 migration creates `customer_webhooks_test_hits` table.
  2. `_check_test_rate` returns False on the 6th call when the previous
     5 came from a mix of "worker A" and "worker B" connections — the
     count must aggregate via SQLite, not per-connection bookkeeping.
  3. The fallback dict path (table missing) still works for backward
     compatibility (a partial-migration boot must not 500).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def hits_db(seeded_db: Path) -> Path:
    """Apply migration wave24_143 onto the shared seeded DB and clear rows."""
    repo = Path(__file__).resolve().parent.parent
    sql_path = repo / "scripts" / "migrations" / "wave24_143_customer_webhooks_test_hits.sql"
    sql = sql_path.read_text(encoding="utf-8")
    c = sqlite3.connect(seeded_db)
    try:
        c.executescript(sql)
        c.execute("DELETE FROM customer_webhooks_test_hits")
        c.commit()
    finally:
        c.close()
    yield seeded_db


@pytest.fixture(autouse=True)
def _reset_dict_fallback():
    """Clear the in-process dict so its state from prior tests doesn't bleed."""
    from jpintel_mcp.api import customer_webhooks as cw

    cw._test_hits.clear()
    yield
    cw._test_hits.clear()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_migration_creates_table(hits_db: Path):
    """Sanity floor: the migration must land the table + index."""
    c = sqlite3.connect(hits_db)
    try:
        rows = c.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table','index') "
            "AND name IN ('customer_webhooks_test_hits', "
            "'idx_customer_webhooks_test_hits_lookup')"
        ).fetchall()
    finally:
        c.close()
    names = {r[0] for r in rows}
    assert "customer_webhooks_test_hits" in names
    assert "idx_customer_webhooks_test_hits_lookup" in names


def test_rate_cap_aggregates_across_workers(hits_db: Path):
    """Simulate 2 workers by interleaving calls on 2 distinct connections.

    Each worker hits the limit-check 3 times (total 6) so neither worker
    alone would have triggered the in-process cap — the cap fires only
    if the SQLite row count aggregates across both connections.
    """
    from jpintel_mcp.api import customer_webhooks as cw

    webhook_id = 9999

    # Two separate sqlite3 connections == two separate worker processes
    # for the purposes of "do they share state?". The shared filesystem
    # DB is the only common ground. Autocommit (isolation_level=None) so
    # writes from worker A are visible to worker B without needing
    # explicit conn_a.commit() between calls — production worker
    # connections through `connect()` in db/session.py also use
    # isolation_level=None.
    conn_a = sqlite3.connect(hits_db, isolation_level=None)
    conn_b = sqlite3.connect(hits_db, isolation_level=None)
    try:
        # Worker A: 3 hits, all admitted.
        assert cw._check_test_rate(webhook_id, conn_a, ip="10.0.0.1") is True
        assert cw._check_test_rate(webhook_id, conn_a, ip="10.0.0.1") is True
        assert cw._check_test_rate(webhook_id, conn_a, ip="10.0.0.1") is True

        # Worker B: 2 hits, admitted (cap is 5 / min — A's 3 + B's 2 = 5).
        assert cw._check_test_rate(webhook_id, conn_b, ip="10.0.0.2") is True
        assert cw._check_test_rate(webhook_id, conn_b, ip="10.0.0.2") is True

        # 6th hit (any worker) MUST be rejected — 5/min cap honored
        # across workers. This is the M15 contract.
        assert cw._check_test_rate(webhook_id, conn_a, ip="10.0.0.1") is False, (
            "M15: rate limit must aggregate across workers via SQLite — "
            "got True (admitted) on the 6th call which means worker A's "
            "view did not see worker B's hits."
        )
        assert cw._check_test_rate(webhook_id, conn_b, ip="10.0.0.2") is False, (
            "M15: same contract from worker B's perspective — must not "
            "admit a 6th hit just because B locally only saw 2 of its own."
        )

        # The 5 successful inserts must be in the table (the 2 rejected
        # calls do NOT INSERT — once the cap is hit we early-return).
        (count,) = conn_a.execute(
            "SELECT COUNT(*) FROM customer_webhooks_test_hits WHERE webhook_id = ?",
            (webhook_id,),
        ).fetchone()
        assert count == 5, f"expected 5 admitted hits in DB; got {count}"
    finally:
        conn_a.close()
        conn_b.close()


def test_separate_webhook_ids_do_not_interfere(hits_db: Path):
    """The cap is per webhook_id, not global. Two webhooks share workers."""
    from jpintel_mcp.api import customer_webhooks as cw

    conn = sqlite3.connect(hits_db, isolation_level=None)
    try:
        # Saturate webhook 1.
        for _ in range(5):
            assert cw._check_test_rate(1001, conn) is True
        assert cw._check_test_rate(1001, conn) is False

        # webhook 2 must be unaffected.
        assert cw._check_test_rate(1002, conn) is True
    finally:
        conn.close()


def test_fallback_to_dict_when_table_missing(seeded_db: Path):
    """Partial-migration boot: the rate limit must still hold on a single
    worker via the legacy dict, not crash with OperationalError.

    We deliberately point at `seeded_db` BEFORE the wave24_143 migration is
    applied — the table is missing, so `_check_test_rate` must catch the
    `no such table` and degrade to the in-process bucket.
    """
    from jpintel_mcp.api import customer_webhooks as cw

    # Drop the table if a previous test in this session already created
    # it on the shared seeded_db (the hits_db fixture is per-function but
    # seeded_db is session-scoped).
    c = sqlite3.connect(seeded_db)
    c.execute("DROP TABLE IF EXISTS customer_webhooks_test_hits")
    c.commit()
    c.close()

    conn = sqlite3.connect(seeded_db, isolation_level=None)
    try:
        wid = 7777
        for _ in range(5):
            assert cw._check_test_rate(wid, conn) is True
        # 6th request rejected by the dict-bucket fallback path.
        assert cw._check_test_rate(wid, conn) is False
    finally:
        conn.close()
