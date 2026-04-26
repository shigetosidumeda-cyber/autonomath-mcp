"""Q4 perf-diff #2 — log_usage() deferred-write semantics (2026-04-25).

When ``log_usage`` is called with a ``BackgroundTasks`` instance, the
``usage_events`` INSERT + ``api_keys.last_used_at`` UPDATE + Stripe report
must be queued onto ``bg_tasks`` and **not** execute inline. They only run
when the FastAPI server later iterates ``bg_tasks`` after flushing the
response.

This file pins both halves of that contract:

1. Calling ``log_usage(..., background_tasks=bg)`` returns immediately with
   no row in ``usage_events`` yet (i.e. the write is deferred).
2. After the bg_tasks callable is executed (simulating FastAPI's
   post-response drain), the row exists exactly as the legacy inline path
   would have written it.

The legacy inline path (``background_tasks=None``) is also exercised as a
regression guard so the refactor cannot silently break cron / test
callers that drive ``log_usage`` directly.
"""
from __future__ import annotations

import asyncio
import sqlite3
from typing import TYPE_CHECKING

import pytest
from fastapi import BackgroundTasks

from jpintel_mcp.api.deps import ApiContext, hash_api_key, log_usage
from jpintel_mcp.billing.keys import issue_key
from jpintel_mcp.db.session import connect as project_connect

if TYPE_CHECKING:
    from pathlib import Path


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def paid_ctx(seeded_db: Path) -> tuple[ApiContext, str]:
    """Mint a fresh paid key, return (ctx, key_hash).

    A new key per test means the per-key usage counter is empty, so the
    deferred-vs-inline assertions don't have to worry about cross-test
    pollution from the shared seeded_db.
    """
    c = sqlite3.connect(seeded_db)
    c.row_factory = sqlite3.Row
    raw = issue_key(
        c,
        customer_id="cus_async_write_test",
        tier="paid",
        # No stripe_subscription_id: keep Stripe path inert in tests.
        stripe_subscription_id=None,
    )
    c.commit()
    c.close()
    kh = hash_api_key(raw)
    ctx = ApiContext(
        key_hash=kh,
        tier="paid",
        customer_id="cus_async_write_test",
        stripe_subscription_id=None,
    )
    return ctx, kh


def _count_usage(db_path: Path, key_hash: str) -> int:
    c = sqlite3.connect(db_path)
    try:
        (n,) = c.execute(
            "SELECT COUNT(*) FROM usage_events WHERE key_hash = ?",
            (key_hash,),
        ).fetchone()
        return int(n)
    finally:
        c.close()


def _drain(bg_tasks: BackgroundTasks) -> None:
    """Run every queued task, exactly the way Starlette does post-response.

    Starlette awaits each task in order; sync callables are run in a thread
    pool. Tests don't need that fidelity — invoking them on a fresh event
    loop is enough to assert "did this run" semantics. ``asyncio.run`` is
    used over ``get_event_loop`` because the latter is deprecated in 3.12+.
    """
    asyncio.run(bg_tasks())


# ---------------------------------------------------------------------------
# 1) deferred path — bg_tasks supplied
# ---------------------------------------------------------------------------


def test_log_usage_with_bg_tasks_does_not_write_inline(
    seeded_db: Path,
    paid_ctx: tuple[ApiContext, str],
):
    """Q4 invariant: when background_tasks is passed, the response path
    must return *before* the SQLite writes happen. Equivalent to "response
    200 returns earlier than the write completes" — observable here by
    asserting the row still doesn't exist after log_usage() returns."""
    ctx, kh = paid_ctx
    conn = sqlite3.connect(seeded_db)
    bg = BackgroundTasks()

    assert _count_usage(seeded_db, kh) == 0  # baseline

    log_usage(
        conn,
        ctx,
        "programs.search",
        params={"q": "rice"},
        background_tasks=bg,
    )

    # Critical assertion: the write has NOT happened yet. log_usage
    # returned, but the queued task has not been drained.
    assert _count_usage(seeded_db, kh) == 0, (
        "log_usage(..., background_tasks=bg) must defer the INSERT — "
        "it ran inline, defeating the perf optimisation."
    )
    # And the queue holds exactly the deferred work.
    assert len(bg.tasks) == 1

    conn.close()


def test_log_usage_with_bg_tasks_writes_after_drain(
    seeded_db: Path,
    paid_ctx: tuple[ApiContext, str],
):
    """The deferred write must actually run when FastAPI drains the
    BackgroundTasks queue post-response. Without this we'd silently
    drop usage tracking entirely."""
    ctx, kh = paid_ctx
    conn = sqlite3.connect(seeded_db)
    bg = BackgroundTasks()

    log_usage(
        conn,
        ctx,
        "programs.search",
        params={"q": "rice"},
        background_tasks=bg,
    )
    # Pre-drain: empty.
    assert _count_usage(seeded_db, kh) == 0

    # Simulate Starlette's post-response drain.
    _drain(bg)

    # Post-drain: exactly one row written by the background worker.
    assert _count_usage(seeded_db, kh) == 1

    # And the row carries the right shape (params_digest from the
    # whitelisted endpoint, metered=1 because tier="paid").
    c = sqlite3.connect(seeded_db)
    c.row_factory = sqlite3.Row
    try:
        row = c.execute(
            "SELECT endpoint, metered, params_digest, status "
            "FROM usage_events WHERE key_hash = ?",
            (kh,),
        ).fetchone()
    finally:
        c.close()
    assert row["endpoint"] == "programs.search"
    assert row["metered"] == 1
    assert row["status"] == 200
    assert row["params_digest"] is not None
    assert len(row["params_digest"]) == 16

    conn.close()


# ---------------------------------------------------------------------------
# 2) legacy inline path — bg_tasks omitted
# ---------------------------------------------------------------------------


def test_log_usage_without_bg_tasks_writes_inline(
    seeded_db: Path,
    paid_ctx: tuple[ApiContext, str],
):
    """Cron / direct callers (no BackgroundTasks) must keep working. This
    is the legacy contract — log_usage(conn, ctx, endpoint) with no
    background_tasks arg writes synchronously on the supplied conn.

    Uses ``project_connect`` (autocommit-on, ``isolation_level=None``) to
    match production wiring; a raw ``sqlite3.connect`` would buffer the
    write inside an implicit transaction and the assertion would race the
    cross-connection read."""
    ctx, kh = paid_ctx
    conn = project_connect()
    try:
        assert _count_usage(seeded_db, kh) == 0
        log_usage(conn, ctx, "programs.search", params={"q": "rice"})
        # Inline path: the row is there immediately, no drain needed.
        assert _count_usage(seeded_db, kh) == 1
    finally:
        conn.close()
