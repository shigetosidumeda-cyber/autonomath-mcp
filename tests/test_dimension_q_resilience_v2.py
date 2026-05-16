"""Tests for Dim Q Resilience v2 integration (Wave 46 dim 19 FPQO booster).

Covers the **end-to-end interaction** of the three Resilience primitives
that previously had only unit tests in isolation:

  * cell 1: ``_idempotency``        (Wave 43.3.1)
  * cell 2: ``_retry_policy``       (Wave 43.3.2)
  * cell 3: ``_circuit_breaker``    (Wave 43.3.3)

Why this file
-------------
``test_resilience_1_3.py`` validates each cell in isolation. ``test_idempotency_resilience.py``
exercises only the idempotency middleware. Neither one validates the
**combined behavior** of a failing upstream call wrapped in:

   ``idempotency replay <= retry policy <= circuit breaker``

That stack is what every cron / ETL / MCP tool we ship uses, so the
interaction matrix is the load-bearing surface. This file walks the
matrix.

Pure stdlib + pytest. NO DB / network. NO LLM. Each test resets the
breaker registry + idempotency store between runs to keep the suite
order-independent.

LOC budget: ~150 (per Wave 46 dim 19 FPQO booster spec).
"""

from __future__ import annotations

import time
from typing import Any

import pytest

from jpintel_mcp.api import _circuit_breaker as cb
from jpintel_mcp.api import _idempotency as idem
from jpintel_mcp.api import _retry_policy as rp

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_resilience_state():
    """Reset breaker registry + idempotency store before every test.

    Cells 1-3 share process-level state (registry / store). Without
    reset, prior tests' breakers / cached entries leak into the next
    test and produce false positives.
    """
    cb.reset_all_breakers()
    idem.reset_default_store()
    yield
    cb.reset_all_breakers()
    idem.reset_default_store()


# ---------------------------------------------------------------------------
# Interaction matrix
# ---------------------------------------------------------------------------


class TestRetryThenBreakerOpens:
    """When retries exhaust their attempt cap on a flaky upstream, the
    breaker must observe each failure and trip after threshold."""

    def test_retry_attempts_feed_failure_counter(self) -> None:
        breaker = cb.get_breaker("test_dimq_retry_then_open", failure_threshold=3)
        policy = rp.RetryPolicy(
            max_attempts=4,
            base_delay_seconds=0.0,
            max_delay_seconds=0.0,
            jitter="none",
        )

        def always_fail() -> None:
            raise RuntimeError("upstream 503")

        for _ in range(policy.max_attempts):
            try:
                with breaker:
                    always_fail()
            except (RuntimeError, cb.CircuitOpenError):
                pass

        # 3 consecutive failures open the breaker; the 4th short-circuits.
        snap = breaker.snapshot()
        assert snap.state == "open"
        assert snap.total_failures >= 3
        assert snap.total_short_circuits >= 1

    def test_breaker_short_circuit_skips_real_call(self) -> None:
        breaker = cb.get_breaker("test_dimq_short_circuit_skip", failure_threshold=2)

        def explode() -> None:
            raise RuntimeError("upstream down")

        # Drive breaker open.
        for _ in range(2):
            with pytest.raises(RuntimeError), breaker:
                explode()

        # Now the real call must NOT execute.
        real_called = {"n": 0}

        def should_not_run() -> None:
            real_called["n"] += 1

        with pytest.raises(cb.CircuitOpenError), breaker:
            should_not_run()

        assert real_called["n"] == 0, "breaker short-circuit failed; real fn ran"


class TestIdempotencyMasksRetry:
    """A retried request with the same Idempotency-Key + fingerprint
    must return the cached first-call value without invoking the
    underlying compute function again."""

    def test_replay_does_not_recompute(self) -> None:
        key = idem.IdempotencyKey.from_request_header("dimq-retry-once-1")
        assert key is not None
        compute_calls = {"n": 0}

        def compute() -> dict[str, Any]:
            compute_calls["n"] += 1
            return {"result": "ok", "ts": time.time()}

        res1 = idem.store_or_replay(key=key, body_fingerprint_value="fp-A", compute=compute)
        res2 = idem.store_or_replay(key=key, body_fingerprint_value="fp-A", compute=compute)

        assert res1.hit is False, "first call must be a miss"
        assert res2.hit is True, "second identical call must be a hit"
        assert res1.value == res2.value, "replay must return cached value"
        assert compute_calls["n"] == 1, "compute must not run twice"

    def test_fingerprint_mismatch_returns_conflict(self) -> None:
        key = idem.IdempotencyKey.from_request_header("dimq-conflict-1")
        assert key is not None

        idem.store_or_replay(
            key=key,
            body_fingerprint_value="fp-original",
            compute=lambda: {"v": 1},
        )

        # Same key but different body -> conflict flag set, prior value returned.
        res = idem.store_or_replay(
            key=key,
            body_fingerprint_value="fp-DIFFERENT",
            compute=lambda: {"v": 2},
        )
        assert res.conflict is True
        assert res.hit is False
        assert res.value == {"v": 1}, "prior payload must be returned on conflict"


class TestFullStackResilience:
    """The realistic call shape: idempotency check -> retry loop -> breaker.

    Validates that a transient failure followed by a success is masked
    by retry (1 success after 2 transient errors), the breaker does
    NOT trip below its threshold, and the second identical request is
    served from idempotency cache without touching the upstream."""

    def test_transient_then_success_then_replay(self) -> None:
        breaker = cb.get_breaker("test_dimq_full_stack", failure_threshold=5)
        policy = rp.RetryPolicy(
            max_attempts=3,
            base_delay_seconds=0.0,
            max_delay_seconds=0.0,
            jitter="none",
        )
        key = idem.IdempotencyKey.from_request_header("dimq-full-stack-1")
        assert key is not None

        state = {"call_count": 0}

        def flaky_upstream() -> dict[str, Any]:
            state["call_count"] += 1
            if state["call_count"] < 3:
                raise RuntimeError("transient 502")
            return {"result": "success", "attempts": state["call_count"]}

        def driver() -> dict[str, Any]:
            last_exc: BaseException | None = None
            for _attempt in range(policy.max_attempts):
                try:
                    with breaker:
                        return flaky_upstream()
                except RuntimeError as exc:
                    last_exc = exc
                    continue
            raise RuntimeError("retries exhausted") from last_exc

        res1 = idem.store_or_replay(key=key, body_fingerprint_value="fp-z", compute=driver)
        assert res1.hit is False
        assert res1.value["result"] == "success"
        assert res1.value["attempts"] == 3
        assert state["call_count"] == 3

        # Breaker observed 2 failures + 1 success -> still closed.
        assert breaker.snapshot().state == "closed"

        # Replay: idempotency hit, no further upstream calls.
        res2 = idem.store_or_replay(key=key, body_fingerprint_value="fp-z", compute=driver)
        assert res2.hit is True
        assert res2.value == res1.value
        assert state["call_count"] == 3, "replay must not invoke upstream again"


class TestContractShapes:
    """Defensive contract tests so the module shapes don't drift under
    future refactors (the integration tests above all assume these
    field names)."""

    def test_circuit_state_snapshot_shape(self) -> None:
        breaker = cb.get_breaker("dimq_snapshot_shape", failure_threshold=1)
        snap = breaker.snapshot()
        for field in (
            "name",
            "state",
            "failure_count",
            "success_count",
            "half_open_calls",
            "total_calls",
            "total_failures",
            "total_short_circuits",
        ):
            assert hasattr(snap, field), f"snapshot missing field: {field}"
        assert snap.state in ("closed", "open", "half_open")

    def test_retry_policy_jitter_modes(self) -> None:
        for mode in ("full", "equal", "decorrelated", "none"):
            policy = rp.RetryPolicy(
                max_attempts=2,
                base_delay_seconds=0.01,
                max_delay_seconds=0.02,
                jitter=mode,  # type: ignore[arg-type]
            )
            assert policy.max_attempts == 2

    def test_idempotency_key_validation_rejects_non_ascii(self) -> None:
        assert idem.IdempotencyKey.from_request_header("日本語") is None
        assert idem.IdempotencyKey.from_request_header("ok-ascii-1") is not None


def test_dim_q_v2_module_has_no_llm_import() -> None:
    """Sanity guard: this test file must not import any LLM SDK.

    Uses dynamic string construction so the forbidden tokens are not
    literal substrings of this file (which would self-match).
    """
    import pathlib

    src = pathlib.Path(__file__).resolve().read_text(encoding="utf-8")
    forbidden_prefixes = (
        "import " + "anthr" + "opic",
        "from " + "anthr" + "opic",
        "import " + "open" + "ai",
    )
    # Strip self-defining tuple from the source before scanning so the
    # forbidden-token literals composed above don't self-match.
    safe_src = src.replace("forbidden_prefixes", "").replace('"import " + "anthr" + "opic"', "")
    for forbidden in forbidden_prefixes:
        # Scan only non-comment / non-docstring source lines for the
        # canonical import statement form.
        for line in safe_src.splitlines():
            stripped = line.strip()
            if stripped.startswith("#") or stripped.startswith('"""'):
                continue
            assert forbidden not in stripped, f"dim Q v2 test file leaked LLM import: {forbidden}"
