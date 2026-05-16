"""Coverage tests for `jpintel_mcp.billing.stripe_usage` (lane #5).

Stripe is an external system boundary — mocking Stripe API responses is
explicitly allowed by the lane #5 charter. We never touch the real network.
The local DB-mark path opens its own short-lived connection inside the
worker, so we exercise it via a temp jpintel.db with the canonical schema.
"""

from __future__ import annotations

import contextlib
import os
import sqlite3
import tempfile
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest

from jpintel_mcp.billing import stripe_usage as su
from jpintel_mcp.config import settings as live_settings
from jpintel_mcp.db.session import init_db

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path
else:
    from pathlib import Path

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_lru_cache() -> Iterator[None]:
    """Each test starts with a clean subscription-item lookup cache."""
    su._clear_subscription_item_cache()
    yield
    su._clear_subscription_item_cache()


@pytest.fixture()
def db_path(monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    fd, raw = tempfile.mkstemp(prefix="jpintel-usage-", suffix=".db")
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


# ---------------------------------------------------------------------------
# _stripe_value / _stripe_path / _is_metered_item
# ---------------------------------------------------------------------------


def test_stripe_value_dict_lookup() -> None:
    assert su._stripe_value({"a": 1}, "a") == 1
    assert su._stripe_value({"a": 1}, "missing", default=99) == 99


def test_stripe_value_object_attr() -> None:
    obj = SimpleNamespace(field=42)
    assert su._stripe_value(obj, "field") == 42


def test_stripe_path_walks_nested_dict() -> None:
    obj = {"items": {"data": [{"id": "x"}]}}
    assert su._stripe_path(obj, "items", "data") == [{"id": "x"}]


def test_stripe_path_returns_none_on_missing_intermediate() -> None:
    assert su._stripe_path({}, "items", "data") is None


def test_is_metered_item_via_price_recurring() -> None:
    item = {"price": {"recurring": {"usage_type": "metered"}}}
    assert su._is_metered_item(item) is True


def test_is_metered_item_via_legacy_plan() -> None:
    item = {"plan": {"usage_type": "metered"}}
    assert su._is_metered_item(item) is True


def test_is_metered_item_false_when_licensed() -> None:
    item = {"price": {"recurring": {"usage_type": "licensed"}}}
    assert su._is_metered_item(item) is False


# ---------------------------------------------------------------------------
# _select_subscription_item
# ---------------------------------------------------------------------------


def test_select_subscription_item_single_metered() -> None:
    items: list[Any] = [{"id": "si_1", "price": {"recurring": {"usage_type": "metered"}}}]
    selected = su._select_subscription_item(items)
    assert selected is not None
    assert selected["id"] == "si_1"


def test_select_subscription_item_picks_overage_metered() -> None:
    items: list[Any] = [
        {"id": "si_base", "price": {"recurring": {"usage_type": "metered"}}},
        {
            "id": "si_overage",
            "price": {"recurring": {"usage_type": "metered"}, "lookup_key": "overage_per_req"},
        },
    ]
    selected = su._select_subscription_item(items)
    assert selected is not None
    assert selected["id"] == "si_overage"


def test_select_subscription_item_single_unknown_item_kept_for_legacy() -> None:
    # Legacy single-item test double with no usage_type → keep old single-item
    # behavior so existing test doubles do not break.
    items: list[Any] = [{"id": "si_legacy"}]
    selected = su._select_subscription_item(items)
    assert selected is not None
    assert selected["id"] == "si_legacy"


def test_select_subscription_item_fail_closed_on_ambiguous_multi() -> None:
    items = [{"id": "si_a"}, {"id": "si_b"}]
    assert su._select_subscription_item(items) is None


def test_looks_like_overage_item_metadata_match() -> None:
    item = {"id": "si_1", "price": {"metadata": {"role": "overage"}}}
    assert su._looks_like_overage_item(item) is True


def test_metadata_text_handles_none() -> None:
    assert su._metadata_text(None) == ""
    assert su._metadata_text({}) == ""


def test_metadata_text_serializes_dict() -> None:
    out = su._metadata_text({"role": "overage", "tier": "paid"})
    assert "overage" in out
    assert "paid" in out


# ---------------------------------------------------------------------------
# _get_subscription_item_id behavior via patched stripe.Subscription
# ---------------------------------------------------------------------------


def test_get_subscription_item_id_returns_none_for_empty_id() -> None:
    assert su._get_subscription_item_id("") is None


def _force_eager_stripe_import() -> Any:
    """Trigger the PEP 562 lazy loader so `su.stripe` is bound."""
    import stripe as _stripe

    # Bind into the module so subsequent patches resolve correctly even when
    # the module body referenced `stripe` only via __getattr__.
    su.stripe = _stripe  # type: ignore[attr-defined]
    return _stripe


def test_get_subscription_item_id_returns_metered(monkeypatch: pytest.MonkeyPatch) -> None:
    stripe = _force_eager_stripe_import()

    fake_sub = {
        "id": "sub_test",
        "items": {
            "data": [
                {
                    "id": "si_metered_1",
                    "price": {"recurring": {"usage_type": "metered"}},
                }
            ]
        },
    }
    monkeypatch.setattr(stripe.Subscription, "retrieve", staticmethod(lambda sid: fake_sub))
    monkeypatch.setattr(
        live_settings,
        "stripe_secret_key",
        "sk_test_mock",
        raising=False,
    )
    su._clear_subscription_item_cache()
    assert su._get_subscription_item_id("sub_test") == "si_metered_1"


def test_get_subscription_item_id_returns_none_when_no_items(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stripe = _force_eager_stripe_import()

    monkeypatch.setattr(
        stripe.Subscription,
        "retrieve",
        staticmethod(lambda sid: {"items": {"data": []}}),
    )
    monkeypatch.setattr(live_settings, "stripe_secret_key", "sk_test_mock", raising=False)
    su._clear_subscription_item_cache()
    assert su._get_subscription_item_id("sub_empty") is None


def test_get_subscription_item_id_handles_stripe_error(monkeypatch: pytest.MonkeyPatch) -> None:
    stripe = _force_eager_stripe_import()

    def _boom(sid: str) -> Any:
        raise RuntimeError("network error")

    monkeypatch.setattr(stripe.Subscription, "retrieve", staticmethod(_boom))
    monkeypatch.setattr(live_settings, "stripe_secret_key", "sk_test_mock", raising=False)
    su._clear_subscription_item_cache()
    assert su._get_subscription_item_id("sub_boom") is None


# ---------------------------------------------------------------------------
# _report_sync — synchronous body (always called from daemon thread)
# ---------------------------------------------------------------------------


def test_report_sync_skips_without_secret_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(live_settings, "stripe_secret_key", "", raising=False)
    assert su._report_sync("sub_x", quantity=1) is False


def test_report_sync_raises_when_strict_and_no_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(live_settings, "stripe_secret_key", "", raising=False)
    with pytest.raises(su.UsageReportError):
        su._report_sync("sub_x", quantity=1, raise_on_failure=True)


def test_report_sync_returns_false_when_item_lookup_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(live_settings, "stripe_secret_key", "sk_test", raising=False)
    monkeypatch.setattr(su, "_get_subscription_item_id", staticmethod(lambda sid: None))
    assert su._report_sync("sub_x", quantity=1) is False


def test_report_sync_raises_when_strict_and_item_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(live_settings, "stripe_secret_key", "sk_test", raising=False)
    monkeypatch.setattr(su, "_get_subscription_item_id", staticmethod(lambda sid: None))
    with pytest.raises(su.UsageReportError):
        su._report_sync("sub_x", quantity=1, raise_on_failure=True)


def test_report_sync_uses_explicit_idempotency_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stripe = _force_eager_stripe_import()

    captured: dict[str, Any] = {}

    def _fake_create(si_id: str, **kwargs: Any) -> dict[str, str]:
        captured["si_id"] = si_id
        captured["kwargs"] = kwargs
        return {"id": "usage_rec_1"}

    monkeypatch.setattr(live_settings, "stripe_secret_key", "sk_test", raising=False)
    monkeypatch.setattr(su, "_get_subscription_item_id", staticmethod(lambda sid: "si_test"))
    monkeypatch.setattr(
        stripe.SubscriptionItem,
        "create_usage_record",
        staticmethod(_fake_create),
        raising=False,
    )
    ok = su._report_sync("sub_x", quantity=2, idempotency_key="custom-key-1")
    # No usage_event_id -> returns True after Stripe POST.
    assert ok is True
    assert captured["kwargs"]["idempotency_key"] == "custom-key-1"
    assert captured["kwargs"]["quantity"] == 2
    assert captured["kwargs"]["action"] == "increment"


def test_report_sync_returns_false_and_clears_cache_on_post_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stripe = _force_eager_stripe_import()

    cleared: list[bool] = []
    real_clear = su._clear_subscription_item_cache

    def _track_clear() -> None:
        cleared.append(True)
        real_clear()

    monkeypatch.setattr(su, "_clear_subscription_item_cache", _track_clear)
    monkeypatch.setattr(live_settings, "stripe_secret_key", "sk_test", raising=False)
    monkeypatch.setattr(su, "_get_subscription_item_id", staticmethod(lambda sid: "si_test"))

    def _boom(si_id: str, **kwargs: Any) -> Any:
        raise RuntimeError("Stripe 500")

    monkeypatch.setattr(
        stripe.SubscriptionItem,
        "create_usage_record",
        staticmethod(_boom),
        raising=False,
    )
    assert su._report_sync("sub_x", quantity=1) is False
    assert cleared, "cache should clear when POST fails so stale ids can heal"


def test_mark_synced_writes_stripe_record_id(
    db_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # `_mark_synced` opens its own short-lived connection via
    # `jpintel_mcp.db.session.connect()` which reads `settings.db_path`.
    # Re-route the live settings object so the worker writes to our per-test DB.
    monkeypatch.setattr(live_settings, "db_path", db_path, raising=False)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """INSERT INTO usage_events(
                   key_hash, endpoint, ts, status, metered, latency_ms, result_count
               ) VALUES ('khash','/v1/x', datetime('now'), 200, 1, 5, 1)"""
        )
        conn.commit()
        row_id = conn.execute("SELECT id FROM usage_events LIMIT 1").fetchone()[0]
    finally:
        conn.close()

    assert su._mark_synced(row_id, "sr_test_1") is True

    conn = sqlite3.connect(db_path)
    try:
        marked = conn.execute(
            "SELECT stripe_record_id, stripe_synced_at FROM usage_events WHERE id = ?",
            (row_id,),
        ).fetchone()
    finally:
        conn.close()
    assert marked[0] == "sr_test_1"
    assert marked[1] is not None


def test_mark_synced_returns_false_on_db_error(monkeypatch: pytest.MonkeyPatch) -> None:
    # Force an exception inside the connect() so we hit the broad except.
    def _boom(*a: Any, **kw: Any) -> Any:
        raise RuntimeError("db open failed")

    monkeypatch.setattr("jpintel_mcp.db.session.connect", _boom)
    assert su._mark_synced(123, "sr_x") is False


# ---------------------------------------------------------------------------
# report_usage_async — must never raise, never block
# ---------------------------------------------------------------------------


def test_report_usage_async_noop_when_subscription_id_none() -> None:
    # No exception, no thread.
    su.report_usage_async(None, quantity=1)


def test_report_usage_async_spawns_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[tuple[str, int]] = []

    def _fake_inner(sid: str, qty: int = 1, uid: int | None = None, **kw: Any) -> bool:
        seen.append((sid, qty))
        return True

    monkeypatch.setattr(su, "_report_sync", _fake_inner)
    su.report_usage_async("sub_async", quantity=3)
    # Threads are daemonised; give the scheduler a beat to run.
    import time

    for _ in range(20):
        if seen:
            break
        time.sleep(0.01)
    assert seen and seen[0] == ("sub_async", 3)


# ---------------------------------------------------------------------------
# Module surface invariants
# ---------------------------------------------------------------------------


def test_module_exports_canonical_names() -> None:
    assert "report_usage_async" in su.__all__
    assert "UsageReportError" in su.__all__


def test_usage_report_error_is_runtime_error_subclass() -> None:
    assert issubclass(su.UsageReportError, RuntimeError)
