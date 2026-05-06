"""
conftest.py — pytest shared fixtures for DEEP-46/47/48 delivery strict test stubs.

Provides in-memory SQLite (autonomath + jpintel split), mocked Stripe / Postmark /
R2 clients, a synthetic event factory, and a CI guard fixture that confirms zero
LLM API imports in the test surface.

These fixtures are intentionally pure-Python — no real network, no real LLM.
The session A lane writes draft tests; codex lane integrates them under
src/jpintel_mcp/tests/billing/ at v0.3.4 cut.
"""

from __future__ import annotations

import hashlib
import sqlite3
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# In-memory SQLite (autonomath + jpintel split, no ATTACH cross-DB JOIN)
# ---------------------------------------------------------------------------

_JPINTEL_DDL = [
    """
    CREATE TABLE IF NOT EXISTS api_keys (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        key_hash TEXT NOT NULL UNIQUE,
        parent_key_hash TEXT,
        client_tag TEXT,
        active INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS usage_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        api_key_id TEXT NOT NULL,
        endpoint TEXT NOT NULL,
        status_code INTEGER NOT NULL,
        amount_yen INTEGER NOT NULL DEFAULT 3,
        client_tag TEXT,
        created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS idempotency_cache (
        cache_key TEXT PRIMARY KEY,
        endpoint TEXT NOT NULL,
        status_code INTEGER NOT NULL,
        response_body TEXT,
        ttl_seconds INTEGER NOT NULL DEFAULT 86400,
        created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
    )
    """,
    # DEEP-46: courses_billing_saga (jpintel)
    """
    CREATE TABLE IF NOT EXISTS courses_billing_saga (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        course_subscription_id INTEGER NOT NULL,
        api_key_id TEXT NOT NULL,
        day_n INTEGER NOT NULL,
        started_at TEXT NOT NULL,
        charge_at TEXT,
        email_at TEXT,
        subscription_update_at TEXT,
        status TEXT NOT NULL CHECK (status IN (
            'success','charge_failed','partial_email_only',
            'partial_no_charge','reconciled'
        )),
        reconcile_run_at TEXT,
        error_class TEXT,
        error_msg TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS course_subscriptions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        api_key_id TEXT NOT NULL,
        course_slug TEXT NOT NULL,
        notify_email TEXT NOT NULL,
        current_day INTEGER NOT NULL DEFAULT 0,
        last_sent_at TEXT,
        created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
    )
    """,
    # DEEP-47: recurring_pdf_billing (jpintel)
    """
    CREATE TABLE IF NOT EXISTS recurring_pdf_billing (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_api_key_hash TEXT NOT NULL,
        quarter_label TEXT NOT NULL,
        charge_at TEXT,
        pdf_generated_at TEXT,
        r2_uploaded_at TEXT,
        signed_url_expires_at TEXT,
        status TEXT NOT NULL CHECK (status IN (
            'success','charge_failed','pdf_failed','r2_failed','cleaned'
        )),
        reconcile_run_at TEXT,
        created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
        UNIQUE(user_api_key_hash, quarter_label)
    )
    """,
    # DEEP-48: delivery_idempotent_log (jpintel)
    """
    CREATE TABLE IF NOT EXISTS delivery_idempotent_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        event_hash TEXT NOT NULL,
        delivery_url_hash TEXT NOT NULL,
        kind TEXT NOT NULL,
        status TEXT NOT NULL CHECK (status IN ('success','send_failed','charge_failed')),
        charge_at TEXT,
        sent_at TEXT,
        ttl_expires_at TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
        UNIQUE(event_hash, delivery_url_hash)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS saved_searches (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        api_key_id TEXT NOT NULL,
        query_text TEXT NOT NULL,
        profile_ids_json TEXT,
        last_run_at TEXT,
        created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS webhook_deliveries (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        webhook_id TEXT NOT NULL,
        event_type TEXT NOT NULL,
        event_id TEXT NOT NULL,
        status_code INTEGER,
        delivered_at TEXT,
        UNIQUE(webhook_id, event_type, event_id)
    )
    """,
]

_AUTONOMATH_DDL = [
    """
    CREATE TABLE IF NOT EXISTS am_amendment_diff (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        program_id TEXT NOT NULL,
        diff_kind TEXT NOT NULL,
        detected_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS am_source (
        source_id TEXT PRIMARY KEY,
        license TEXT,
        url TEXT
    )
    """,
]


def _apply_ddl(conn: sqlite3.Connection, statements: list[str]) -> None:
    for stmt in statements:
        conn.execute(stmt)
    conn.commit()


@pytest.fixture
def jpintel_conn() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    _apply_ddl(conn, _JPINTEL_DDL)
    yield conn
    conn.close()


@pytest.fixture
def autonomath_conn() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    _apply_ddl(conn, _AUTONOMATH_DDL)
    yield conn
    conn.close()


@pytest.fixture
def in_memory_sqlite(jpintel_conn, autonomath_conn) -> dict[str, sqlite3.Connection]:
    """Combined fixture exposing both DBs through a dict."""
    return {"jpintel": jpintel_conn, "autonomath": autonomath_conn}


# ---------------------------------------------------------------------------
# Mock Stripe client (record_metered_delivery surrogate)
# ---------------------------------------------------------------------------


@dataclass
class StripeCall:
    api_key_hash: str
    endpoint: str
    status_code: int
    idempotency_key: str | None = None
    amount_yen: int = 3


class MockStripeClient:
    """
    Surrogate for billing/delivery.py:record_metered_delivery.
    Default returns True (charge succeeded). Override `next_outcomes` to
    inject failures. Tracks every call for assertion.
    """

    def __init__(self) -> None:
        self.calls: list[StripeCall] = []
        self.next_outcomes: list[bool] = []
        self.cap_exceeded: bool = False
        self.transient_error: bool = False
        self.idempotency_collision: set[str] = set()

    def record_metered_delivery(
        self,
        *,
        api_key_hash: str,
        endpoint: str,
        status_code: int = 200,
        idempotency_key: str | None = None,
        amount_yen: int = 3,
    ) -> bool:
        call = StripeCall(
            api_key_hash=api_key_hash,
            endpoint=endpoint,
            status_code=status_code,
            idempotency_key=idempotency_key,
            amount_yen=amount_yen,
        )
        self.calls.append(call)
        if idempotency_key and idempotency_key in self.idempotency_collision:
            return False
        if self.cap_exceeded:
            return False
        if self.transient_error:
            return False
        if self.next_outcomes:
            return self.next_outcomes.pop(0)
        # strict_metering: only 2xx statuses charge
        return 200 <= status_code < 300


@pytest.fixture
def mock_stripe_client() -> MockStripeClient:
    return MockStripeClient()


# ---------------------------------------------------------------------------
# Mock Postmark client
# ---------------------------------------------------------------------------


@dataclass
class PostmarkSend:
    to: str
    template: str
    data: dict[str, Any] = field(default_factory=dict)


class MockPostmark:
    def __init__(self) -> None:
        self.sends: list[PostmarkSend] = []
        self.fail_next: int = 0

    def send_template(self, *, to: str, template: str, data: dict[str, Any] | None = None) -> bool:
        if self.fail_next > 0:
            self.fail_next -= 1
            return False
        self.sends.append(PostmarkSend(to=to, template=template, data=data or {}))
        return True


@pytest.fixture
def mock_postmark() -> MockPostmark:
    return MockPostmark()


# ---------------------------------------------------------------------------
# Mock R2 storage
# ---------------------------------------------------------------------------


@dataclass
class R2Object:
    bucket: str
    key: str
    body_bytes: int
    uploaded_at: float


class MockR2Storage:
    def __init__(self) -> None:
        self.objects: dict[str, R2Object] = {}
        self.fail_next: int = 0

    def put_object(self, *, bucket: str, key: str, body: bytes) -> bool:
        if self.fail_next > 0:
            self.fail_next -= 1
            return False
        self.objects[f"{bucket}/{key}"] = R2Object(
            bucket=bucket, key=key, body_bytes=len(body), uploaded_at=time.time()
        )
        return True

    def delete_object(self, *, bucket: str, key: str) -> bool:
        return self.objects.pop(f"{bucket}/{key}", None) is not None

    def signed_url(self, *, bucket: str, key: str, expires_in: int = 60 * 60 * 24 * 92) -> str:
        # 92 days ≈ one quarter window, matches DEEP-47 §6 cleanup rule.
        return f"https://r2.example/{bucket}/{key}?expires_in={expires_in}"


@pytest.fixture
def mock_r2_storage() -> MockR2Storage:
    return MockR2Storage()


# ---------------------------------------------------------------------------
# Synthetic event factory
# ---------------------------------------------------------------------------


@dataclass
class SyntheticEvent:
    event_id: str
    customer_id: str
    event_kind: str
    payload: dict[str, Any]

    @property
    def event_hash(self) -> str:
        body = (
            f"{self.event_id}|{self.customer_id}|{self.event_kind}|{sorted(self.payload.items())}"
        )
        return hashlib.sha256(body.encode("utf-8")).hexdigest()


class SyntheticEventFactory:
    def __init__(self) -> None:
        self._counter = 0

    def make(
        self,
        *,
        event_kind: str = "saved_search.match",
        customer_id: str = "cust_001",
        payload: dict[str, Any] | None = None,
    ) -> SyntheticEvent:
        self._counter += 1
        return SyntheticEvent(
            event_id=f"evt_{self._counter:06d}",
            customer_id=customer_id,
            event_kind=event_kind,
            payload=payload or {"program_id": f"prog_{self._counter:04d}"},
        )


@pytest.fixture
def synthetic_event_factory() -> SyntheticEventFactory:
    return SyntheticEventFactory()


# ---------------------------------------------------------------------------
# CI guard — no LLM imports at module import time
# ---------------------------------------------------------------------------

_FORBIDDEN_LLM_MODULES = (
    "anthropic",
    "openai",
    "google.generativeai",
    "claude_agent_sdk",
)


@pytest.fixture
def assert_no_llm_imports() -> Callable[[], None]:
    """Returns a callable that scans sys.modules and asserts no LLM modules loaded."""

    import sys

    def _check() -> None:
        loaded = [m for m in _FORBIDDEN_LLM_MODULES if m in sys.modules]
        assert loaded == [], (
            f"Forbidden LLM module(s) loaded in test session: {loaded}. "
            "DEEP-46/47/48 must run with zero LLM API surface."
        )

    return _check


# ---------------------------------------------------------------------------
# Helper: a "now" mock so tests can assert TTL boundaries
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_clock() -> MagicMock:
    clock = MagicMock()
    clock.now = 1746576000.0  # 2026-05-07 00:00 UTC, deterministic
    clock.advance = lambda secs: setattr(clock, "now", clock.now + secs)
    return clock
