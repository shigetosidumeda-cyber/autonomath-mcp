"""Signal compute + threshold tests for api/realtime_signal_v2.

Targets ``src/jpintel_mcp/api/realtime_signal_v2.py`` (179 stmt, 0%
baseline). Exercises:

  * ``_is_internal_host`` — loopback / private IP / link-local / multicast
    detection.
  * ``_validate_webhook_url`` — https-only + non-internal hosts.
  * Pydantic models: ``SubscribeRequest`` (target_kind literal + filter_json
    length cap), ``SubscriberResponse`` (round-trip + secret toggle).
  * ``_row_to_subscriber`` — sqlite3.Row → SubscriberResponse coercion +
    malformed filter_json fallback.
  * ``_ensure_under_cap`` — 50/key enforcement on tmp DB.

NO live ``am_realtime_subscribers`` row inserts via HTTP (those go through
FastAPI dependency injection — covered elsewhere). NO LLM call.
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import sqlite3
import sys
from pathlib import Path
from typing import Any

import pytest
from fastapi import HTTPException

# realtime_signal_v2 has a FastAPI route registration at module load that
# trips ``Invalid args for response field`` for the Annotated[Any, ...]
# dependencies on a vanilla `import`. The module is currently orphaned in
# `api/main.py` (not include_router'd), so we bypass route registration
# entirely by stubbing fastapi.APIRouter before the spec_from_file_location
# load. Once stubbed, the helper-level functions + Pydantic models that
# this test file targets are fully reachable.


def _load_rs_module() -> Any:
    import fastapi

    real_router = fastapi.APIRouter

    class _NoopRouter:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def post(self, *args: Any, **kwargs: Any):  # noqa: ANN201
            def _decorator(func):  # noqa: ANN001, ANN202
                return func

            return _decorator

        def get(self, *args: Any, **kwargs: Any):  # noqa: ANN201
            def _decorator(func):  # noqa: ANN001, ANN202
                return func

            return _decorator

        def delete(self, *args: Any, **kwargs: Any):  # noqa: ANN201
            def _decorator(func):  # noqa: ANN001, ANN202
                return func

            return _decorator

    fastapi.APIRouter = _NoopRouter  # type: ignore[misc]
    try:
        src_path = (
            pathlib.Path(__file__).resolve().parent.parent
            / "src"
            / "jpintel_mcp"
            / "api"
            / "realtime_signal_v2.py"
        )
        spec = importlib.util.spec_from_file_location("_rs_test_module", src_path)
        assert spec and spec.loader
        mod = importlib.util.module_from_spec(spec)
        sys.modules["_rs_test_module"] = mod
        spec.loader.exec_module(mod)
        return mod
    finally:
        fastapi.APIRouter = real_router  # type: ignore[misc]


rs = _load_rs_module()


# ---------------------------------------------------------------------------
# _is_internal_host
# ---------------------------------------------------------------------------


def test_is_internal_host_localhost() -> None:
    assert rs._is_internal_host("localhost") is True


def test_is_internal_host_empty() -> None:
    assert rs._is_internal_host("") is True


def test_is_internal_host_loopback_ipv4() -> None:
    assert rs._is_internal_host("127.0.0.1") is True


def test_is_internal_host_loopback_ipv6() -> None:
    assert rs._is_internal_host("::1") is True


def test_is_internal_host_private_10() -> None:
    assert rs._is_internal_host("10.0.0.1") is True


def test_is_internal_host_private_192() -> None:
    assert rs._is_internal_host("192.168.1.1") is True


def test_is_internal_host_private_172() -> None:
    assert rs._is_internal_host("172.16.0.1") is True


def test_is_internal_host_link_local() -> None:
    assert rs._is_internal_host("169.254.1.1") is True


def test_is_internal_host_public_ipv4() -> None:
    # Cloudflare DNS — public.
    assert rs._is_internal_host("1.1.1.1") is False


def test_is_internal_host_public_dns_name_treated_as_external() -> None:
    # Hostnames that don't parse as IP fall through to "not internal".
    assert rs._is_internal_host("example.com") is False


# ---------------------------------------------------------------------------
# _validate_webhook_url
# ---------------------------------------------------------------------------


def test_validate_webhook_url_https_external() -> None:
    url, host = rs._validate_webhook_url("https://example.com/webhook")
    assert url == "https://example.com/webhook"
    assert host == "example.com"


def test_validate_webhook_url_rejects_http() -> None:
    with pytest.raises(HTTPException) as exc:
        rs._validate_webhook_url("http://example.com/")
    assert exc.value.status_code == 400


def test_validate_webhook_url_rejects_internal_host() -> None:
    with pytest.raises(HTTPException) as exc:
        rs._validate_webhook_url("https://127.0.0.1/")
    assert exc.value.status_code == 400
    assert "internal" in str(exc.value.detail).lower()


def test_validate_webhook_url_rejects_localhost() -> None:
    with pytest.raises(HTTPException) as exc:
        rs._validate_webhook_url("https://localhost/x")
    assert exc.value.status_code == 400


def test_validate_webhook_url_rejects_empty() -> None:
    with pytest.raises(HTTPException):
        rs._validate_webhook_url("")


def test_validate_webhook_url_rejects_oversized() -> None:
    long_url = "https://example.com/" + ("x" * (rs._URL_MAX_LEN + 1))
    with pytest.raises(HTTPException) as exc:
        rs._validate_webhook_url(long_url)
    assert exc.value.status_code == 400


def test_validate_webhook_url_missing_host() -> None:
    with pytest.raises(HTTPException) as exc:
        rs._validate_webhook_url("https:///path-only")
    assert exc.value.status_code == 400


# ---------------------------------------------------------------------------
# SubscribeRequest / filter_json cap
# ---------------------------------------------------------------------------


def test_subscribe_request_target_kind_valid() -> None:
    body = rs.SubscribeRequest(
        target_kind="kokkai_bill",
        filter_json={"foo": "bar"},
        webhook_url="https://example.com/hook",
    )
    assert body.target_kind == "kokkai_bill"
    assert body.filter_json == {"foo": "bar"}


def test_subscribe_request_rejects_invalid_target_kind() -> None:
    with pytest.raises(Exception):  # noqa: B017 — pydantic ValidationError
        rs.SubscribeRequest(
            target_kind="not_a_kind",  # type: ignore[arg-type]
            filter_json={},
            webhook_url="https://example.com/hook",
        )


def test_subscribe_request_filter_json_default_empty() -> None:
    body = rs.SubscribeRequest(
        target_kind="amendment",
        webhook_url="https://example.com/hook",
    )
    assert body.filter_json == {}


def test_subscribe_request_filter_json_size_cap() -> None:
    huge = {"key": "x" * (rs._FILTER_JSON_MAX_LEN + 100)}
    with pytest.raises(Exception):  # noqa: B017
        rs.SubscribeRequest(
            target_kind="amendment",
            filter_json=huge,
            webhook_url="https://example.com/hook",
        )


# ---------------------------------------------------------------------------
# TARGET_KINDS + constants
# ---------------------------------------------------------------------------


def test_target_kinds_includes_expected_set() -> None:
    expected = {
        "kokkai_bill",
        "amendment",
        "enforcement_municipality",
        "program_created",
        "tax_treaty_amended",
        "court_decision_added",
        "pubcomment_announcement",
        "other",
    }
    assert set(rs.TARGET_KINDS) == expected


def test_max_subscriptions_per_key_positive() -> None:
    assert rs.MAX_SUBSCRIPTIONS_PER_KEY > 0
    assert rs.MAX_SUBSCRIPTIONS_PER_KEY == 50


def test_signature_secret_bytes_size() -> None:
    assert rs._SIGNATURE_SECRET_BYTES == 32


# ---------------------------------------------------------------------------
# _row_to_subscriber
# ---------------------------------------------------------------------------


def _row_factory_from_dict(d: dict[str, Any]) -> sqlite3.Row:
    """Wrap a dict in a sqlite3.Row by stuffing it through a tmp DB."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    cols = ", ".join(d.keys())
    placeholders = ", ".join(["?"] * len(d))
    conn.execute(f"CREATE TABLE t({cols})")
    conn.execute(f"INSERT INTO t VALUES ({placeholders})", tuple(d.values()))
    row = conn.execute("SELECT * FROM t").fetchone()
    conn.close()
    return row


def _make_subscriber_row(**overrides: Any) -> sqlite3.Row:
    base = {
        "subscriber_id": 42,
        "target_kind": "amendment",
        "filter_json": json.dumps({"law_id": "law-1"}),
        "webhook_url": "https://example.com/hook",
        "status": "active",
        "failure_count": 0,
        "last_delivery_at": None,
        "last_signal_at": None,
        "created_at": "2026-05-16T00:00:00Z",
        "updated_at": "2026-05-16T00:00:00Z",
        "signature_secret": "deadbeef" * 8,
    }
    base.update(overrides)
    return _row_factory_from_dict(base)


def test_row_to_subscriber_basic() -> None:
    row = _make_subscriber_row()
    sub = rs._row_to_subscriber(row, include_secret=True)
    assert sub.subscriber_id == 42
    assert sub.target_kind == "amendment"
    assert sub.filter_json == {"law_id": "law-1"}
    assert sub.signature_secret is not None


def test_row_to_subscriber_hides_secret_by_default() -> None:
    row = _make_subscriber_row()
    sub = rs._row_to_subscriber(row, include_secret=False)
    assert sub.signature_secret is None


def test_row_to_subscriber_malformed_filter_json_fallback() -> None:
    row = _make_subscriber_row(filter_json="not valid json")
    sub = rs._row_to_subscriber(row)
    # Malformed JSON → empty dict (defensive fallback in source).
    assert sub.filter_json == {}


def test_row_to_subscriber_null_filter_json() -> None:
    row = _make_subscriber_row(filter_json=None)
    sub = rs._row_to_subscriber(row)
    assert sub.filter_json == {}


# ---------------------------------------------------------------------------
# _ensure_under_cap — tmp DB
# ---------------------------------------------------------------------------


@pytest.fixture()
def tmp_subscribers_db(tmp_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(tmp_path / "rs.db")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE am_realtime_subscribers (
            subscriber_id INTEGER PRIMARY KEY AUTOINCREMENT,
            api_key_hash TEXT,
            target_kind TEXT,
            filter_json TEXT,
            webhook_url TEXT,
            signature_secret TEXT,
            status TEXT,
            failure_count INTEGER,
            last_delivery_at TEXT,
            last_signal_at TEXT,
            disabled_at TEXT,
            disabled_reason TEXT,
            created_at TEXT,
            updated_at TEXT
        );
        """
    )
    yield conn
    conn.close()


def test_ensure_under_cap_zero_rows(tmp_subscribers_db: sqlite3.Connection) -> None:
    # Should not raise.
    rs._ensure_under_cap(tmp_subscribers_db, "test-key")


def test_ensure_under_cap_at_threshold(tmp_subscribers_db: sqlite3.Connection) -> None:
    for i in range(rs.MAX_SUBSCRIPTIONS_PER_KEY):
        tmp_subscribers_db.execute(
            "INSERT INTO am_realtime_subscribers(api_key_hash, target_kind, "
            "filter_json, webhook_url, signature_secret, status, "
            "failure_count, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "saturated-key",
                "amendment",
                "{}",
                f"https://example.com/h{i}",
                "secret",
                "active",
                0,
                "2026-05-16T00:00:00Z",
                "2026-05-16T00:00:00Z",
            ),
        )
    tmp_subscribers_db.commit()
    with pytest.raises(HTTPException) as exc:
        rs._ensure_under_cap(tmp_subscribers_db, "saturated-key")
    assert exc.value.status_code == 409


def test_ensure_under_cap_disabled_rows_dont_count(tmp_subscribers_db: sqlite3.Connection) -> None:
    # Inserting 60 disabled rows should NOT block a fresh key.
    for i in range(60):
        tmp_subscribers_db.execute(
            "INSERT INTO am_realtime_subscribers(api_key_hash, target_kind, "
            "filter_json, webhook_url, signature_secret, status, "
            "failure_count, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "disabled-key",
                "amendment",
                "{}",
                f"https://example.com/h{i}",
                "secret",
                "disabled",
                0,
                "2026-05-16T00:00:00Z",
                "2026-05-16T00:00:00Z",
            ),
        )
    tmp_subscribers_db.commit()
    # Should pass — only 'active' rows count.
    rs._ensure_under_cap(tmp_subscribers_db, "disabled-key")
