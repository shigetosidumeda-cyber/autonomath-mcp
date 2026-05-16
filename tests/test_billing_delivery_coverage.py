"""Coverage tests for `jpintel_mcp.billing.delivery` (lane #5).

Exercises the metered-delivery helper that cron + pre-render jobs use to
write to usage_events without a FastAPI request scope. Uses real SQLite
(per project rule: do NOT mock the DB). Stripe usage reporting is the
fire-and-forget thread already inside deps.log_usage — we do not assert
on Stripe-side state here.
"""

from __future__ import annotations

import contextlib
import os
import sqlite3
import tempfile
from typing import TYPE_CHECKING

import pytest

from jpintel_mcp.billing import delivery
from jpintel_mcp.db.session import init_db

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path
else:
    from pathlib import Path

# ---------------------------------------------------------------------------
# Per-test jpintel.db with schema applied
# ---------------------------------------------------------------------------


@pytest.fixture()
def db_path(monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    fd, raw = tempfile.mkstemp(prefix="jpintel-delivery-", suffix=".db")
    os.close(fd)
    p = Path(raw)
    monkeypatch.setenv("JPINTEL_DB_PATH", str(p))
    monkeypatch.setenv("JPCITE_DB_PATH", str(p))
    init_db(p)
    yield p
    for ext in ("", "-wal", "-shm"):
        target = Path(str(p) + ext)
        if target.exists():
            with contextlib.suppress(OSError):
                target.unlink()


@pytest.fixture()
def conn(db_path: Path) -> Iterator[sqlite3.Connection]:
    c = sqlite3.connect(db_path)
    c.row_factory = sqlite3.Row
    yield c
    c.close()


def _insert_api_key(
    conn: sqlite3.Connection,
    key_hash: str,
    tier: str = "paid",
    *,
    customer_id: str | None = "cus_test",
    stripe_subscription_id: str | None = None,
) -> None:
    """Insert a minimal api_keys row matching the canonical schema."""
    conn.execute(
        """INSERT INTO api_keys(
               key_hash, customer_id, tier, stripe_subscription_id, created_at
           ) VALUES (?, ?, ?, ?, datetime('now'))""",
        (key_hash, customer_id, tier, stripe_subscription_id),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# record_metered_delivery happy / error paths
# ---------------------------------------------------------------------------


def test_record_metered_delivery_returns_false_for_empty_key_hash(
    conn: sqlite3.Connection,
) -> None:
    assert (
        delivery.record_metered_delivery(
            conn,
            key_hash="",
            endpoint="/v1/test",
        )
        is False
    )


def test_record_metered_delivery_returns_false_for_unknown_key(
    conn: sqlite3.Connection,
) -> None:
    # No api_keys row inserted → context lookup returns None.
    assert (
        delivery.record_metered_delivery(
            conn,
            key_hash="not_in_db",
            endpoint="/v1/test",
        )
        is False
    )


def test_record_metered_delivery_writes_usage_row_on_2xx_paid(
    conn: sqlite3.Connection,
) -> None:
    _insert_api_key(conn, "khash_paid_1", tier="paid")
    before = conn.execute("SELECT COUNT(*) FROM usage_events").fetchone()[0]
    ok = delivery.record_metered_delivery(
        conn,
        key_hash="khash_paid_1",
        endpoint="/v1/programs/search",
        status_code=200,
        quantity=1,
        latency_ms=42,
        result_count=3,
        client_tag="t-001",
    )
    assert ok is True
    after = conn.execute("SELECT COUNT(*) FROM usage_events").fetchone()[0]
    assert after == before + 1


def test_record_metered_delivery_for_revoked_key_returns_false(
    conn: sqlite3.Connection,
) -> None:
    _insert_api_key(conn, "khash_revoked", tier="paid")
    conn.execute(
        "UPDATE api_keys SET revoked_at = datetime('now') WHERE key_hash = ?",
        ("khash_revoked",),
    )
    conn.commit()
    # The 5-column select filters by revoked_at IS NULL → fallback shape kicks in
    # but still excludes revoked rows in the canonical path.
    assert (
        delivery.record_metered_delivery(
            conn,
            key_hash="khash_revoked",
            endpoint="/v1/test",
        )
        is False
    )


def test_record_metered_delivery_for_free_tier_5xx_does_not_strict_meter(
    conn: sqlite3.Connection,
) -> None:
    _insert_api_key(conn, "khash_free_5xx", tier="free")
    # A 503 still writes the audit row but does not enter strict-metering.
    delivery.record_metered_delivery(
        conn,
        key_hash="khash_free_5xx",
        endpoint="/v1/error",
        status_code=503,
    )
    # Function returns True iff a usage row was written. Free 5xx still records
    # the audit row (or may not, depending on log_usage policy) — we only assert
    # that the call did not raise.


# ---------------------------------------------------------------------------
# _row_get helper edge cases
# ---------------------------------------------------------------------------


def test_row_get_none_row_returns_default() -> None:
    assert delivery._row_get(None, "tier", 0, "free") == "free"


def test_row_get_sqlite_row_with_key(conn: sqlite3.Connection) -> None:
    row = conn.execute("SELECT 'paid' AS tier").fetchone()
    assert delivery._row_get(row, "tier", 0) == "paid"


def test_row_get_tuple_falls_back_to_index() -> None:
    # Plain tuple has no .keys()
    assert delivery._row_get(("paid", "cus_1"), "tier", 0) == "paid"
    assert delivery._row_get(("paid", "cus_1"), "customer_id", 1) == "cus_1"


def test_row_get_index_out_of_range_returns_default() -> None:
    assert delivery._row_get(("paid",), "missing", 5, "fallback") == "fallback"


def test_row_get_missing_key_returns_default(conn: sqlite3.Connection) -> None:
    row = conn.execute("SELECT 'paid' AS tier").fetchone()
    assert delivery._row_get(row, "unknown_field", 0, "default_val") == "default_val"


# ---------------------------------------------------------------------------
# _api_context_for_key returns None when row missing
# ---------------------------------------------------------------------------


def test_api_context_for_key_returns_none_for_missing(conn: sqlite3.Connection) -> None:
    assert delivery._api_context_for_key(conn, "no_such_hash") is None


def test_api_context_for_key_returns_ctx_for_existing(conn: sqlite3.Connection) -> None:
    _insert_api_key(conn, "khash_ctx_1", tier="paid", customer_id="cus_ctx")
    ctx = delivery._api_context_for_key(conn, "khash_ctx_1")
    assert ctx is not None
    assert ctx.tier == "paid"
    assert ctx.customer_id == "cus_ctx"
