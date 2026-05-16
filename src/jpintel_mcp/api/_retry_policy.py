"""Retry-After + exponential backoff helper (Wave 43.3.2 — AX Resilience cell 2).

Companion to ``_degradation.py`` / ``_idempotency.py`` / ``_failover.py``.
This module gives MCP tools, cron jobs, ETL workers, and resilience smoke
walks a SINGLE, dep-free way to compute how long to wait before the next
attempt — with jitter, a Retry-After ceiling, and a deterministic upper
bound on total wall time.

Why not just ``time.sleep(2 ** n)``: naive exponential backoff causes
thundering-herd effects when 100 clients all retry at the same exponent.
We add full-jitter (AWS Architecture Blog 2015) by default; the policy
also honours an explicit Retry-After header (RFC 7231 §7.1.3) if the
server speaks one.

Pure stdlib. No third-party imports. Importable from anywhere under
``src/``. NO LLM call.

Contract::

    from jpintel_mcp.api._retry_policy import (
        RetryPolicy, parse_retry_after, sleep_for_retry,
    )

    policy = RetryPolicy.default()
    for attempt in range(policy.max_attempts):
        try:
            return call()
        except TransientError as exc:
            delay = policy.next_delay(attempt, retry_after_header=exc.retry_after)
            if delay is None:
                raise
            sleep_for_retry(delay)
"""

from __future__ import annotations

import email.utils
import logging
import random
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

logger = logging.getLogger(__name__)

# Defaults — tuned for Fly p99 25s machine swap + Stripe 30s service
# windows. Override per-callsite via ``RetryPolicy(...)``.
DEFAULT_MAX_ATTEMPTS: int = 5
DEFAULT_BASE_DELAY_SECONDS: float = 0.5
DEFAULT_MAX_DELAY_SECONDS: float = 30.0
DEFAULT_TOTAL_DEADLINE_SECONDS: float = 120.0

# Hard ceiling on Retry-After we will honour. A server can advertise
# 30 days and we should refuse — that's a client-side timeout, not a
# retry hint. RFC 7231 leaves this to client policy.
_RETRY_AFTER_CEILING_SECONDS: float = 600.0  # 10 minutes

JitterMode = Literal["none", "full", "equal", "decorrelated"]


@dataclass(frozen=True)
class RetryPolicy:
    """Pure-data retry plan. Construct once, ask for delays N times.

    Attributes:
        max_attempts: Including the initial call. ``5`` → up to 4 retries.
        base_delay_seconds: First retry delay before jitter / exponent.
        max_delay_seconds: Cap on any single delay (post jitter, pre Retry-After).
        total_deadline_seconds: Hard ceiling on cumulative sleep across all
            retries — once we cross it, ``next_delay`` returns ``None``.
        jitter: ``full`` (default) = uniform [0, delay], ``equal`` = delay/2 +
            uniform [0, delay/2], ``decorrelated`` = AWS decorrelated jitter,
            ``none`` = strict exponential (debug / smoke only).
        respect_retry_after: If True, a Retry-After header value (when
            <= ``_RETRY_AFTER_CEILING_SECONDS``) overrides the computed
            backoff for that attempt.
    """

    max_attempts: int = DEFAULT_MAX_ATTEMPTS
    base_delay_seconds: float = DEFAULT_BASE_DELAY_SECONDS
    max_delay_seconds: float = DEFAULT_MAX_DELAY_SECONDS
    total_deadline_seconds: float = DEFAULT_TOTAL_DEADLINE_SECONDS
    jitter: JitterMode = "full"
    respect_retry_after: bool = True

    @classmethod
    def default(cls) -> RetryPolicy:
        """Convenience factory using the module defaults."""
        return cls()

    @classmethod
    def aggressive(cls) -> RetryPolicy:
        """Smoke / chaos walk profile — short backoff, more attempts."""
        return cls(
            max_attempts=8,
            base_delay_seconds=0.1,
            max_delay_seconds=5.0,
            total_deadline_seconds=30.0,
            jitter="full",
        )

    @classmethod
    def conservative(cls) -> RetryPolicy:
        """Stripe / billing profile — long backoff, few attempts."""
        return cls(
            max_attempts=4,
            base_delay_seconds=2.0,
            max_delay_seconds=60.0,
            total_deadline_seconds=300.0,
            jitter="equal",
        )

    def next_delay(
        self,
        attempt: int,
        *,
        retry_after_header: str | float | None = None,
        elapsed_seconds: float = 0.0,
        prev_delay: float | None = None,
    ) -> float | None:
        """Return the next sleep duration, or None if we should give up.

        ``attempt`` is 0-indexed — pass 0 for the very first retry after
        the initial call failed.
        """
        if attempt < 0:
            raise ValueError(f"attempt must be >= 0, got {attempt}")
        if attempt >= self.max_attempts - 1:
            return None
        if elapsed_seconds >= self.total_deadline_seconds:
            return None

        # 1. Server-supplied Retry-After takes precedence (if sane).
        if self.respect_retry_after and retry_after_header is not None:
            parsed = parse_retry_after(retry_after_header)
            if parsed is not None and 0 <= parsed <= _RETRY_AFTER_CEILING_SECONDS:
                # Still respect the global deadline.
                remaining = self.total_deadline_seconds - elapsed_seconds
                return float(min(parsed, max(remaining, 0.0)))

        # 2. Otherwise, compute exponential backoff + jitter.
        raw = self.base_delay_seconds * (2**attempt)
        capped = min(raw, self.max_delay_seconds)
        jittered = _apply_jitter(
            capped,
            mode=self.jitter,
            base=self.base_delay_seconds,
            prev=prev_delay,
        )
        remaining = self.total_deadline_seconds - elapsed_seconds
        return float(max(0.0, min(jittered, remaining)))


def _apply_jitter(
    delay: float,
    *,
    mode: JitterMode,
    base: float,
    prev: float | None,
) -> float:
    """Apply the selected jitter strategy to a raw exponential delay."""
    if delay <= 0:
        return 0.0
    if mode == "none":
        return delay
    if mode == "full":
        # AWS full jitter: uniform [0, delay]. Best for thundering-herd.
        return random.uniform(0.0, delay)
    if mode == "equal":
        # Half-fixed + half-jitter. Slightly tighter variance than full.
        half = delay / 2.0
        return half + random.uniform(0.0, half)
    if mode == "decorrelated":
        # AWS decorrelated: sleep = min(cap, uniform(base, prev * 3)).
        prev_val = prev if prev is not None else base
        upper = min(delay, max(base, prev_val * 3))
        if upper <= base:
            return base
        return random.uniform(base, upper)
    return delay  # unknown mode → fall through


def parse_retry_after(value: str | float | None) -> float | None:
    """Parse a Retry-After header value into seconds.

    RFC 7231 §7.1.3 allows either:
        * delta-seconds: an integer number of seconds, OR
        * HTTP-date: an absolute RFC 7231 date (parsed via email.utils).

    Returns None on unparseable / negative input.
    """
    if value is None:
        return None
    if isinstance(value, int | float):
        return max(0.0, float(value))
    text = str(value).strip()
    if not text:
        return None
    # Try delta-seconds first (most common).
    try:
        seconds = float(text)
        return max(0.0, seconds)
    except ValueError:
        pass
    # Fall back to HTTP-date.
    try:
        parsed_dt = email.utils.parsedate_to_datetime(text)
    except (TypeError, ValueError):
        return None
    if parsed_dt is None:
        return None
    if parsed_dt.tzinfo is None:
        parsed_dt = parsed_dt.replace(tzinfo=UTC)
    delta = (parsed_dt - datetime.now(UTC)).total_seconds()
    return max(0.0, delta)


def sleep_for_retry(seconds: float) -> None:
    """``time.sleep`` wrapper that clamps to a safe upper bound.

    Negative / NaN values become 0; values above the Retry-After ceiling
    are capped. Centralised so smoke tests can monkey-patch one symbol.
    """
    if seconds is None:
        return
    if seconds != seconds:  # NaN check
        return
    safe = max(0.0, min(float(seconds), _RETRY_AFTER_CEILING_SECONDS))
    if safe <= 0:
        return
    time.sleep(safe)


__all__ = [
    "DEFAULT_BASE_DELAY_SECONDS",
    "DEFAULT_MAX_ATTEMPTS",
    "DEFAULT_MAX_DELAY_SECONDS",
    "DEFAULT_TOTAL_DEADLINE_SECONDS",
    "JitterMode",
    "RetryPolicy",
    "parse_retry_after",
    "sleep_for_retry",
]
