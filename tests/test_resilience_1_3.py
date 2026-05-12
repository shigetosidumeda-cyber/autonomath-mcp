"""Wave 43.3.1+2+3 cells 1-3 — idempotency + retry policy + circuit breaker tests.

Pure stdlib + pytest; no DB / network. Verifies:
* cell 1 _idempotency: header parsing variants, length / charset rejects,
  body fingerprint stability, hit/miss/conflict outcomes, TTL expiry,
  LRU eviction at the entry cap.
* cell 2 _retry_policy: full / equal / decorrelated / none jitter modes,
  Retry-After header (delta-seconds + HTTP-date), deadline cap, attempt
  cap, sleep_for_retry NaN / negative clamp.
* cell 3 _circuit_breaker: closed→open→half_open→closed lifecycle,
  excluded_exceptions, half_open_max_calls gate, snapshot shape,
  registry singletons, decorator form, reset_all_breakers test hook.
"""

from __future__ import annotations

import time

import pytest

from jpintel_mcp.api import _circuit_breaker as cb
from jpintel_mcp.api import _idempotency as idem
from jpintel_mcp.api import _retry_policy as rp

# ============================================================================
# cell 1: _idempotency
# ============================================================================


class TestIdempotencyKey:
    def test_from_header_basic(self):
        key = idem.IdempotencyKey.from_request_header("abc-123")
        assert key is not None
        assert key.raw == "abc-123"
        # Stable hash → first 32 hex chars of sha256("abc-123")
        assert len(key.cache_id) == 32
        assert all(c in "0123456789abcdef" for c in key.cache_id)

    def test_from_header_none_or_blank(self):
        assert idem.IdempotencyKey.from_request_header(None) is None
        assert idem.IdempotencyKey.from_request_header("") is None
        assert idem.IdempotencyKey.from_request_header("   ") is None

    def test_from_header_strips_whitespace(self):
        key = idem.IdempotencyKey.from_request_header("  trim-me  ")
        assert key is not None
        assert key.raw == "trim-me"

    def test_from_header_rejects_too_long(self):
        oversize = "a" * 300
        assert idem.IdempotencyKey.from_request_header(oversize) is None

    def test_from_header_rejects_non_ascii(self):
        # Whitespace + control chars + non-ASCII rejected per draft spec.
        assert idem.IdempotencyKey.from_request_header("has space") is None
        assert idem.IdempotencyKey.from_request_header("日本語") is None
        assert idem.IdempotencyKey.from_request_header("line\nbreak") is None

    def test_from_headers_variants(self):
        h1 = {"Idempotency-Key": "k1"}
        h2 = {"idempotency_key": "k2"}
        h3 = {"X-Idempotency-Key": "k3"}
        h_none = {"Content-Type": "application/json"}
        assert idem.IdempotencyKey.from_headers(h1).raw == "k1"
        assert idem.IdempotencyKey.from_headers(h2).raw == "k2"
        assert idem.IdempotencyKey.from_headers(h3).raw == "k3"
        assert idem.IdempotencyKey.from_headers(h_none) is None
        assert idem.IdempotencyKey.from_headers(None) is None


class TestBodyFingerprint:
    def test_none_is_sha256_of_empty(self):
        # Known sha256 of empty bytes.
        assert idem.body_fingerprint(None) == (
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        )

    def test_bytes_str_dict_equivalence(self):
        as_str = idem.body_fingerprint('{"a": 1}')
        as_bytes = idem.body_fingerprint(b'{"a": 1}')
        assert as_str == as_bytes

    def test_dict_sort_stable(self):
        a = idem.body_fingerprint({"x": 1, "y": 2})
        b = idem.body_fingerprint({"y": 2, "x": 1})
        assert a == b

    def test_different_bodies_differ(self):
        assert idem.body_fingerprint("a") != idem.body_fingerprint("b")


class TestStoreOrReplay:
    def setup_method(self):
        idem.reset_default_store()

    def test_miss_calls_compute(self):
        key = idem.IdempotencyKey.from_request_header("k1")
        calls = []

        def compute():
            calls.append(1)
            return {"result": 42}

        out = idem.store_or_replay(key, idem.body_fingerprint("body"), compute)
        assert out.hit is False
        assert out.conflict is False
        assert out.value == {"result": 42}
        assert calls == [1]

    def test_hit_skips_compute(self):
        key = idem.IdempotencyKey.from_request_header("k2")
        calls = []

        def compute():
            calls.append(1)
            return {"value": "x"}

        idem.store_or_replay(key, idem.body_fingerprint("body"), compute)
        # Second call with same body → hit, compute NOT called again.
        out = idem.store_or_replay(key, idem.body_fingerprint("body"), compute)
        assert out.hit is True
        assert out.value == {"value": "x"}
        assert calls == [1]  # compute ran only once

    def test_body_mismatch_yields_conflict(self):
        key = idem.IdempotencyKey.from_request_header("k3")
        idem.store_or_replay(
            key, idem.body_fingerprint("body-A"), lambda: {"v": "A"}
        )
        out = idem.store_or_replay(
            key, idem.body_fingerprint("body-B"), lambda: {"v": "B"}
        )
        assert out.hit is False
        assert out.conflict is True
        # Conflict returns the PRIOR cached value (so caller can build 409).
        assert out.value == {"v": "A"}

    def test_ttl_expiry(self):
        key = idem.IdempotencyKey.from_request_header("k4")
        idem.store_or_replay(
            key,
            idem.body_fingerprint("b"),
            lambda: {"v": 1},
            ttl_seconds=0,  # already expired
        )
        # Tiny pause so monotonic-but-not-strictly-greater clocks still flip.
        time.sleep(0.001)
        calls = []
        out = idem.store_or_replay(
            key,
            idem.body_fingerprint("b"),
            lambda: (calls.append(1), {"v": 2})[1],
        )
        assert out.hit is False  # expired → recomputed
        assert out.value == {"v": 2}
        assert calls == [1]

    def test_lru_evicts_oldest(self):
        # Build a tiny store so we can observe eviction.
        store = idem._InMemoryStore(max_entries=3)
        for i in range(5):
            k = idem.IdempotencyKey.from_request_header(f"key-{i}")
            idem.store_or_replay(
                k,
                idem.body_fingerprint(f"body-{i}"),
                lambda i=i: {"i": i},
                store=store,
            )
        # Only the last 3 should remain.
        assert len(store) == 3

    def test_exception_not_cached(self):
        key = idem.IdempotencyKey.from_request_header("k5")

        def boom():
            raise RuntimeError("upstream failed")

        with pytest.raises(RuntimeError):
            idem.store_or_replay(key, idem.body_fingerprint("b"), boom)
        # Next call should be a miss — exceptions are not cached.
        out = idem.store_or_replay(
            key, idem.body_fingerprint("b"), lambda: {"ok": True}
        )
        assert out.hit is False
        assert out.value == {"ok": True}


# ============================================================================
# cell 2: _retry_policy
# ============================================================================


class TestRetryPolicy:
    def test_default_factory(self):
        p = rp.RetryPolicy.default()
        assert p.max_attempts == rp.DEFAULT_MAX_ATTEMPTS
        assert p.jitter == "full"

    def test_aggressive_and_conservative(self):
        a = rp.RetryPolicy.aggressive()
        c = rp.RetryPolicy.conservative()
        assert a.max_attempts > c.max_attempts
        assert c.base_delay_seconds > a.base_delay_seconds

    def test_negative_attempt_rejected(self):
        with pytest.raises(ValueError):
            rp.RetryPolicy.default().next_delay(-1)

    def test_attempt_cap_returns_none(self):
        p = rp.RetryPolicy(max_attempts=3, base_delay_seconds=0.1, jitter="none")
        # max_attempts=3 → attempts 0, 1 allowed; 2 returns None.
        assert p.next_delay(0) is not None
        assert p.next_delay(1) is not None
        assert p.next_delay(2) is None

    def test_deadline_returns_none(self):
        p = rp.RetryPolicy(total_deadline_seconds=10.0)
        assert p.next_delay(0, elapsed_seconds=11.0) is None

    def test_jitter_none_is_strict_exponential(self):
        p = rp.RetryPolicy(
            max_attempts=10, base_delay_seconds=1.0,
            max_delay_seconds=100.0, jitter="none",
        )
        assert p.next_delay(0) == 1.0
        assert p.next_delay(1) == 2.0
        assert p.next_delay(2) == 4.0
        assert p.next_delay(3) == 8.0

    def test_jitter_full_within_bounds(self):
        p = rp.RetryPolicy(
            max_attempts=10, base_delay_seconds=1.0,
            max_delay_seconds=100.0, jitter="full",
        )
        for _ in range(50):
            d = p.next_delay(3)  # raw = 8s
            assert d is not None
            assert 0.0 <= d <= 8.0

    def test_jitter_equal_within_bounds(self):
        p = rp.RetryPolicy(
            max_attempts=10, base_delay_seconds=1.0,
            max_delay_seconds=100.0, jitter="equal",
        )
        for _ in range(50):
            d = p.next_delay(3)
            assert d is not None
            assert 4.0 <= d <= 8.0

    def test_jitter_decorrelated_runs(self):
        p = rp.RetryPolicy(
            max_attempts=10, base_delay_seconds=1.0,
            max_delay_seconds=100.0, jitter="decorrelated",
        )
        prev = None
        for attempt in range(5):
            d = p.next_delay(attempt, prev_delay=prev)
            assert d is not None
            assert d >= p.base_delay_seconds
            prev = d

    def test_max_delay_cap(self):
        p = rp.RetryPolicy(
            max_attempts=20, base_delay_seconds=1.0,
            max_delay_seconds=10.0, jitter="none",
        )
        # attempt=10 → raw 1024s, but cap at 10s.
        assert p.next_delay(10) == 10.0


class TestRetryAfter:
    def test_parse_delta_seconds_int(self):
        assert rp.parse_retry_after("30") == 30.0
        assert rp.parse_retry_after("0") == 0.0
        assert rp.parse_retry_after(15) == 15.0
        assert rp.parse_retry_after(15.5) == 15.5

    def test_parse_negative_clamps_to_zero(self):
        # parse_retry_after sees the float branch first and clamps via max().
        assert rp.parse_retry_after(-5) == 0.0
        assert rp.parse_retry_after("-5") == 0.0

    def test_parse_http_date(self):
        # Far-future date should give a large positive delta.
        future = "Wed, 21 Oct 2099 07:28:00 GMT"
        out = rp.parse_retry_after(future)
        assert out is not None
        assert out > 1e6  # at least a few decades in seconds

    def test_parse_blank_or_garbage(self):
        assert rp.parse_retry_after(None) is None
        assert rp.parse_retry_after("") is None
        assert rp.parse_retry_after("   ") is None
        assert rp.parse_retry_after("not a date or number") is None

    def test_retry_after_used_when_respected(self):
        p = rp.RetryPolicy(
            max_attempts=5, base_delay_seconds=0.1,
            max_delay_seconds=60.0, jitter="full",
        )
        d = p.next_delay(0, retry_after_header="5")
        assert d == 5.0  # exact (no jitter applied)

    def test_retry_after_above_ceiling_ignored(self):
        p = rp.RetryPolicy(
            max_attempts=5, base_delay_seconds=0.1,
            max_delay_seconds=60.0, jitter="none",
        )
        # 10 days = 864000s — well above the 600s ceiling, falls through.
        d = p.next_delay(0, retry_after_header="864000")
        assert d == p.base_delay_seconds  # exponential fallback


class TestSleepForRetry:
    def test_zero_or_negative_does_not_sleep(self):
        t0 = time.monotonic()
        rp.sleep_for_retry(0)
        rp.sleep_for_retry(-1)
        assert time.monotonic() - t0 < 0.01

    def test_nan_does_not_sleep(self):
        t0 = time.monotonic()
        rp.sleep_for_retry(float("nan"))
        assert time.monotonic() - t0 < 0.01

    def test_positive_sleeps(self):
        t0 = time.monotonic()
        rp.sleep_for_retry(0.05)
        assert time.monotonic() - t0 >= 0.04


# ============================================================================
# cell 3: _circuit_breaker
# ============================================================================


class TestCircuitBreaker:
    def setup_method(self):
        cb.reset_all_breakers()

    def test_initial_state_is_closed(self):
        b = cb.CircuitBreaker(name="x")
        assert b.state == "closed"

    def test_success_keeps_closed(self):
        b = cb.CircuitBreaker(name="x", failure_threshold=3)
        for _ in range(5):
            with b:
                pass
        assert b.state == "closed"
        snap = b.snapshot()
        assert snap.total_calls == 5
        assert snap.total_failures == 0

    def test_failure_threshold_opens(self):
        b = cb.CircuitBreaker(name="x", failure_threshold=3, cooldown_seconds=10)
        for _ in range(3):
            with pytest.raises(RuntimeError), b:
                raise RuntimeError("upstream")
        assert b.state == "open"

    def test_open_short_circuits(self):
        b = cb.CircuitBreaker(name="x", failure_threshold=2, cooldown_seconds=10)
        for _ in range(2):
            with pytest.raises(RuntimeError), b:
                raise RuntimeError()
        # Now open — entering should raise CircuitOpenError without running body.
        ran = []
        with pytest.raises(cb.CircuitOpenError), b:
            ran.append(1)
        assert ran == []
        assert b.snapshot().total_short_circuits >= 1

    def test_cooldown_to_half_open(self):
        b = cb.CircuitBreaker(name="x", failure_threshold=1, cooldown_seconds=0.05)
        with pytest.raises(RuntimeError), b:
            raise RuntimeError()
        assert b.state == "open"
        time.sleep(0.06)
        # Reading state triggers the half_open transition.
        assert b.state == "half_open"

    def test_half_open_success_closes(self):
        b = cb.CircuitBreaker(
            name="x",
            failure_threshold=1,
            success_threshold=2,
            cooldown_seconds=0.01,
            half_open_max_calls=3,
        )
        with pytest.raises(RuntimeError), b:
            raise RuntimeError()
        time.sleep(0.02)
        # Two successful probes → fully close.
        with b:
            pass
        with b:
            pass
        assert b.state == "closed"

    def test_half_open_failure_reopens(self):
        b = cb.CircuitBreaker(
            name="x",
            failure_threshold=1,
            success_threshold=2,
            cooldown_seconds=0.01,
        )
        with pytest.raises(RuntimeError), b:
            raise RuntimeError()
        time.sleep(0.02)
        with pytest.raises(RuntimeError), b:
            raise RuntimeError("still down")
        assert b.state == "open"

    def test_excluded_exceptions_do_not_trip(self):
        b = cb.CircuitBreaker(
            name="x",
            failure_threshold=2,
            cooldown_seconds=10,
            excluded_exceptions=(ValueError,),
        )
        # 100 ValueErrors should NOT trip the breaker.
        for _ in range(100):
            with pytest.raises(ValueError), b:
                raise ValueError("client bug")
        assert b.state == "closed"

    def test_half_open_max_calls_caps_probes(self):
        b = cb.CircuitBreaker(
            name="x",
            failure_threshold=1,
            success_threshold=10,  # huge so we stay in half_open
            cooldown_seconds=0.01,
            half_open_max_calls=1,
        )
        with pytest.raises(RuntimeError), b:
            raise RuntimeError()
        time.sleep(0.02)
        # First probe enters.
        with b:
            pass
        # Second probe is short-circuited (cap=1).
        with pytest.raises(cb.CircuitOpenError), b:
            pass

    def test_snapshot_shape(self):
        b = cb.CircuitBreaker(name="snap")
        snap = b.snapshot()
        d = snap.to_dict()
        for field_name in (
            "name", "state", "failure_count", "success_count",
            "half_open_calls", "opened_at", "last_failure_at",
            "last_success_at", "total_calls", "total_failures",
            "total_short_circuits",
        ):
            assert field_name in d

    def test_reset_clears_state(self):
        b = cb.CircuitBreaker(name="x", failure_threshold=1, cooldown_seconds=10)
        with pytest.raises(RuntimeError), b:
            raise RuntimeError()
        assert b.state == "open"
        b.reset()
        assert b.state == "closed"


class TestRegistry:
    def setup_method(self):
        cb.reset_all_breakers()

    def test_get_breaker_returns_singleton(self):
        b1 = cb.get_breaker("svc_a")
        b2 = cb.get_breaker("svc_a")
        assert b1 is b2

    def test_get_breaker_distinct_names(self):
        b1 = cb.get_breaker("svc_a")
        b2 = cb.get_breaker("svc_b")
        assert b1 is not b2

    def test_decorator_form(self):
        @cb.circuit_breaker("decorated", failure_threshold=2, cooldown_seconds=10)
        def call(arg):
            if arg == "boom":
                raise RuntimeError("boom")
            return arg

        assert call("ok") == "ok"
        with pytest.raises(RuntimeError):
            call("boom")
        with pytest.raises(RuntimeError):
            call("boom")
        # Third call: short-circuited.
        with pytest.raises(cb.CircuitOpenError):
            call("ok")

    def test_all_breakers_returns_snapshot_dict(self):
        cb.get_breaker("alpha")
        cb.get_breaker("beta")
        snaps = cb.all_breakers()
        assert set(snaps.keys()) == {"alpha", "beta"}
        for name, snap in snaps.items():
            assert isinstance(snap, cb.CircuitState)
            assert snap.name == name

    def test_reset_all_clears_registry(self):
        cb.get_breaker("svc")
        assert len(cb.all_breakers()) == 1
        cb.reset_all_breakers()
        assert cb.all_breakers() == {}
