"""Wave 46 Dim Q — idempotency_resilience integration regression test.

Smoke-tests the lightweight ``_idempotency`` helper landed in Wave 43.3.1
(``src/jpintel_mcp/api/_idempotency.py``). The heavyweight HTTP middleware
backed by ``am_idempotency_cache`` is exercised separately in
``test_billing_webhook_idempotency.py`` / ``test_stripe_webhook_idempotency.py``
/ ``test_credit_pack_idempotency.py``; this file lifts Dim Q's coverage on
the dep-free primitive that MCP tools, cron jobs, and ETL workers reuse to
deduplicate retries without booting FastAPI or SQLite.

Hits 3 sub-criteria from the Wave 46 dim19 audit:

* IdempotencyKey header normalisation (Stripe / RFC draft compatibility).
* store_or_replay replay-or-compute round-trip + body-fingerprint
  collision (409-class conflict) detection.
* TTL eviction + LRU cap behaviour so a runaway client cannot OOM Fly's
  1 GB machine size budget.

All pure stdlib. NO LLM call. NO network. NO SQLite.
"""

from __future__ import annotations

import time

import pytest

from jpintel_mcp.api._idempotency import (
    DEFAULT_TTL_SECONDS,
    IdempotencyKey,
    StoreResult,
    _InMemoryStore,
    body_fingerprint,
    idempotency_store,
    reset_default_store,
    store_or_replay,
)


@pytest.fixture(autouse=True)
def _reset_store() -> None:
    """Ensure the process-wide default store is clean for each test."""
    reset_default_store()
    yield
    reset_default_store()


# ---------------------------------------------------------------------------
# IdempotencyKey — header parsing + validation
# ---------------------------------------------------------------------------


def test_from_request_header_strips_and_hashes() -> None:
    key = IdempotencyKey.from_request_header("  abc-123  ")
    assert key is not None
    assert key.raw == "abc-123"
    # cache_id is sha256 prefix; should be hex, 32 chars.
    assert len(key.cache_id) == 32
    assert all(c in "0123456789abcdef" for c in key.cache_id)


def test_from_request_header_rejects_blank_and_too_long() -> None:
    assert IdempotencyKey.from_request_header(None) is None
    assert IdempotencyKey.from_request_header("") is None
    assert IdempotencyKey.from_request_header("   ") is None
    assert IdempotencyKey.from_request_header("A" * 256) is None


def test_from_request_header_rejects_non_printable() -> None:
    # whitespace inside the key violates the printable-ASCII regex.
    assert IdempotencyKey.from_request_header("abc def") is None
    assert IdempotencyKey.from_request_header("abc\tdef") is None


def test_from_headers_scans_known_variants() -> None:
    # Stripe-style header name.
    a = IdempotencyKey.from_headers({"Idempotency-Key": "k1"})
    assert a is not None and a.raw == "k1"
    # Snake-case variant.
    b = IdempotencyKey.from_headers({"idempotency_key": "k2"})
    assert b is not None and b.raw == "k2"
    # Vendor prefix.
    c = IdempotencyKey.from_headers({"X-Idempotency-Key": "k3"})
    assert c is not None and c.raw == "k3"
    # Unknown header → None.
    assert IdempotencyKey.from_headers({"X-Foo": "k4"}) is None


# ---------------------------------------------------------------------------
# body_fingerprint — stable digest semantics
# ---------------------------------------------------------------------------


def test_body_fingerprint_stable_across_dict_key_order() -> None:
    fp_a = body_fingerprint({"a": 1, "b": 2})
    fp_b = body_fingerprint({"b": 2, "a": 1})
    assert fp_a == fp_b
    assert len(fp_a) == 64  # full sha256 hex


def test_body_fingerprint_differs_for_different_payloads() -> None:
    assert body_fingerprint({"a": 1}) != body_fingerprint({"a": 2})
    assert body_fingerprint("x") != body_fingerprint("y")


def test_body_fingerprint_none_is_empty_sha() -> None:
    # sha256 of empty input is a well-known constant.
    assert body_fingerprint(None) == (
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    )


# ---------------------------------------------------------------------------
# store_or_replay — happy path + replay + conflict
# ---------------------------------------------------------------------------


def test_store_or_replay_first_call_computes() -> None:
    key = IdempotencyKey.from_request_header("k-first")
    assert key is not None
    fp = body_fingerprint({"x": 1})
    calls = {"n": 0}

    def _compute() -> dict[str, int]:
        calls["n"] += 1
        return {"result": 42}

    result = store_or_replay(key=key, body_fingerprint_value=fp, compute=_compute)
    assert isinstance(result, StoreResult)
    assert result.hit is False
    assert result.value == {"result": 42}
    assert result.conflict is False
    assert calls["n"] == 1


def test_store_or_replay_replays_on_match() -> None:
    key = IdempotencyKey.from_request_header("k-replay")
    assert key is not None
    fp = body_fingerprint({"x": 1})
    calls = {"n": 0}

    def _compute() -> dict[str, int]:
        calls["n"] += 1
        return {"result": calls["n"]}

    a = store_or_replay(key=key, body_fingerprint_value=fp, compute=_compute)
    b = store_or_replay(key=key, body_fingerprint_value=fp, compute=_compute)
    assert a.hit is False and a.value == {"result": 1}
    assert b.hit is True and b.value == {"result": 1}
    assert calls["n"] == 1  # compute called exactly once across both attempts


def test_store_or_replay_flags_body_fingerprint_conflict() -> None:
    key = IdempotencyKey.from_request_header("k-conflict")
    assert key is not None

    a = store_or_replay(
        key=key, body_fingerprint_value=body_fingerprint({"x": 1}), compute=lambda: "A"
    )
    b = store_or_replay(
        key=key, body_fingerprint_value=body_fingerprint({"x": 2}), compute=lambda: "B"
    )
    assert a.hit is False and a.value == "A"
    # Same key, different fingerprint → conflict, prior value surfaced.
    assert b.hit is False
    assert b.conflict is True
    assert b.value == "A"


def test_store_or_replay_does_not_cache_exceptions() -> None:
    key = IdempotencyKey.from_request_header("k-exc")
    assert key is not None
    fp = body_fingerprint({"x": 1})

    class _TransientError(RuntimeError):
        pass

    def _boom() -> str:
        raise _TransientError("network blip")

    with pytest.raises(_TransientError):
        store_or_replay(key=key, body_fingerprint_value=fp, compute=_boom)

    # Second attempt should be a fresh compute, not a replayed exception.
    def _ok() -> str:
        return "ok"

    second = store_or_replay(key=key, body_fingerprint_value=fp, compute=_ok)
    assert second.hit is False and second.value == "ok"


# ---------------------------------------------------------------------------
# Store backend — TTL + LRU + custom store injection
# ---------------------------------------------------------------------------


def test_in_memory_store_evicts_expired() -> None:
    backend = _InMemoryStore(max_entries=8)
    key = IdempotencyKey.from_request_header("k-ttl")
    assert key is not None

    store_or_replay(
        key=key,
        body_fingerprint_value=body_fingerprint({"x": 1}),
        compute=lambda: "v",
        store=backend,
        ttl_seconds=1,
    )
    assert len(backend) == 1
    time.sleep(1.05)
    # evict_expired sweeps stale rows lazily.
    assert backend.evict_expired() == 1
    assert len(backend) == 0


def test_in_memory_store_respects_max_entries_cap() -> None:
    backend = _InMemoryStore(max_entries=3)
    for i in range(5):
        k = IdempotencyKey.from_request_header(f"k-cap-{i}")
        assert k is not None
        store_or_replay(
            key=k,
            body_fingerprint_value=body_fingerprint({"i": i}),
            compute=lambda i=i: i,
            store=backend,
        )
    # LRU cap should hold at exactly max_entries.
    assert len(backend) == 3


def test_idempotency_store_singleton_round_trip() -> None:
    # The default store and the public accessor must agree.
    store_a = idempotency_store()
    store_b = idempotency_store()
    assert store_a is store_b


def test_default_ttl_seconds_is_24h() -> None:
    # Sanity-check the resilience contract — Stripe / RFC draft both pin to 24h.
    assert DEFAULT_TTL_SECONDS == 24 * 3600
