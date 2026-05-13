"""Rate-limit timezone reset gotcha test (CLAUDE.md L230).

Pins the CLAUDE.md "Common gotchas" line:

  "Anonymous quota resets at JST midnight; authenticated API-key quota
   resets at UTC midnight."

Concretely:
  - Anon bucket key = `_jst_day_bucket()` in `api/anon_limit.py` — rolls
    over at UTC 15:00 (JST 00:00, +9 hours).
  - API-key bucket key = `_day_bucket()` in `api/deps.py` — rolls over at
    UTC 00:00 (no timezone offset; uses `datetime.now(UTC)`).

We don't have `freezegun` in the dev deps (verified via `uv pip list`),
so we feed crafted `datetime` instances directly into the two functions
via their public `now`/`ts` parameter. Both production callers invoke
the helpers with no argument, but the test injection point is built
into the implementation (`_jst_day_bucket(now: datetime | None = None)`)
— this is a property of the read-only API, NOT a new test hook.

Read-only scope: this test does NOT edit `anon_limit.py` or `billing.py`
/ `deps.py`. It only reads the bucket strings the helpers return at
chosen `datetime` instants and asserts the rollover boundary.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone


def _jst_day_bucket():
    """Lazy import so module load doesn't depend on FastAPI app boot."""
    from jpintel_mcp.api.anon_limit import _jst_day_bucket

    return _jst_day_bucket


def _api_key_day_bucket():
    """The UTC bucket used by `_daily_quota_used` in `api/deps.py`."""
    from jpintel_mcp.api.deps import _day_bucket

    return _day_bucket


# ---------------------------------------------------------------------------
# Test 1 — anonymous quota resets at JST midnight (UTC+9)
# ---------------------------------------------------------------------------
#
# JST 00:00 == UTC 15:00. So:
#   - At 14:59 UTC the JST clock reads 23:59 of day N. Bucket = "YYYY-MM-DD"
#     of day N.
#   - One minute later at 15:00 UTC the JST clock reads 00:00 of day N+1.
#     Bucket flips to "YYYY-MM-(DD+1)".
# We pick a day comfortably away from month-end so we can assert N+1 by
# string equality without worrying about month rollover semantics
# (those are a separate concern, covered by `test_anon_rate_limit.py`).


def test_anon_quota_resets_at_jst_midnight_boundary():
    """At 14:59 UTC anon bucket is day N; at 15:00 UTC it flips to day N+1."""
    jst_bucket = _jst_day_bucket()

    # Anchor: 2026-06-15 14:59 UTC  ==  2026-06-15 23:59 JST (day N).
    pre_rollover_utc = datetime(2026, 6, 15, 14, 59, 0, tzinfo=UTC)
    # Anchor: 2026-06-15 15:00 UTC  ==  2026-06-16 00:00 JST (day N+1).
    post_rollover_utc = datetime(2026, 6, 15, 15, 0, 0, tzinfo=UTC)

    bucket_pre = jst_bucket(pre_rollover_utc)
    bucket_post = jst_bucket(post_rollover_utc)

    assert bucket_pre == "2026-06-15", (
        f"Expected JST day = 2026-06-15 at 14:59 UTC, got {bucket_pre!r}"
    )
    assert bucket_post == "2026-06-16", (
        f"Expected JST day = 2026-06-16 at 15:00 UTC, got {bucket_post!r}"
    )
    assert bucket_pre != bucket_post, "JST midnight rollover must change the bucket key"


def test_anon_quota_jst_midnight_is_exact_boundary():
    """One second before vs one second after JST 00:00 must differ exactly."""
    jst_bucket = _jst_day_bucket()

    # 14:59:59 UTC == 23:59:59 JST (still day N).
    one_sec_before = datetime(2026, 6, 15, 14, 59, 59, tzinfo=UTC)
    # 15:00:00 UTC == 00:00:00 JST (day N+1).
    at_midnight = datetime(2026, 6, 15, 15, 0, 0, tzinfo=UTC)

    assert jst_bucket(one_sec_before) == "2026-06-15"
    assert jst_bucket(at_midnight) == "2026-06-16"


def test_anon_quota_uses_utc_plus_9_not_utc():
    """At 00:00 UTC the JST clock is already 09:00 of the SAME UTC date.

    This pins the gotcha against a naive UTC-midnight implementation: if
    someone "simplified" the anon bucket to use UTC, the bucket at
    00:00 UTC would change from N-1 to N; with the correct JST+9 offset
    it stays on day N (because JST has been ticking that day since 09:00
    of the previous UTC day).
    """
    jst_bucket = _jst_day_bucket()

    # 2026-06-15 00:00 UTC == 2026-06-15 09:00 JST (still mid-day in JST).
    midday_jst = datetime(2026, 6, 15, 0, 0, 0, tzinfo=UTC)
    # 2026-06-14 23:59 UTC == 2026-06-15 08:59 JST (still mid-day in JST).
    jst_morning = datetime(2026, 6, 14, 23, 59, 0, tzinfo=UTC)

    assert jst_bucket(midday_jst) == "2026-06-15"
    assert jst_bucket(jst_morning) == "2026-06-15", (
        "23:59 UTC the previous calendar day is still JST 08:59 of the SAME "
        "JST date — bucket must not roll yet"
    )


# ---------------------------------------------------------------------------
# Test 2 — authenticated API-key quota resets at UTC midnight
# ---------------------------------------------------------------------------
#
# `_day_bucket` formats `datetime.now(UTC)` as "YYYY-MM-DD". So:
#   - At 23:59 UTC the bucket is day N.
#   - At 00:00 UTC the bucket flips to day N+1.


def test_api_key_quota_resets_at_utc_midnight_boundary():
    """At 23:59 UTC API-key bucket is day N; at 00:00 UTC it flips to N+1."""
    utc_bucket = _api_key_day_bucket()

    pre_rollover = datetime(2026, 6, 15, 23, 59, 0, tzinfo=UTC)
    post_rollover = datetime(2026, 6, 16, 0, 0, 0, tzinfo=UTC)

    bucket_pre = utc_bucket(pre_rollover)
    bucket_post = utc_bucket(post_rollover)

    assert bucket_pre == "2026-06-15", (
        f"Expected UTC day = 2026-06-15 at 23:59 UTC, got {bucket_pre!r}"
    )
    assert bucket_post == "2026-06-16", (
        f"Expected UTC day = 2026-06-16 at 00:00 UTC, got {bucket_post!r}"
    )
    assert bucket_pre != bucket_post, "UTC midnight rollover must change the bucket key"


def test_api_key_quota_utc_midnight_is_exact_boundary():
    """One second before vs one second after UTC 00:00 must differ exactly."""
    utc_bucket = _api_key_day_bucket()

    one_sec_before = datetime(2026, 6, 15, 23, 59, 59, tzinfo=UTC)
    at_midnight = datetime(2026, 6, 16, 0, 0, 0, tzinfo=UTC)

    assert utc_bucket(one_sec_before) == "2026-06-15"
    assert utc_bucket(at_midnight) == "2026-06-16"


def test_api_key_quota_does_not_use_jst():
    """At 15:00 UTC (JST 00:00) the UTC-key bucket must NOT roll.

    This pins the inverse of the anon test: if someone "unified" both
    quotas to JST, this test would fail at 15:00 UTC because the bucket
    would advance one day early.
    """
    utc_bucket = _api_key_day_bucket()

    # 2026-06-15 14:59 UTC and 15:00 UTC are both still UTC day = 2026-06-15.
    jst_pre = datetime(2026, 6, 15, 14, 59, 0, tzinfo=UTC)
    jst_post = datetime(2026, 6, 15, 15, 0, 0, tzinfo=UTC)

    assert utc_bucket(jst_pre) == "2026-06-15"
    assert utc_bucket(jst_post) == "2026-06-15", (
        "API-key UTC bucket must not roll over at JST midnight (15:00 UTC); "
        "only at UTC midnight."
    )


# ---------------------------------------------------------------------------
# Cross-check: the two buckets disagree by exactly one day during the
# overlap window between UTC 15:00 and UTC 24:00 (JST 00:00..09:00 of the
# next day). This is the operationally important window — a customer
# whose anon quota just reset (JST midnight) might still see their
# API-key quota tick because UTC is N hours behind.
# ---------------------------------------------------------------------------


def test_buckets_diverge_during_jst_morning_overlap_window():
    """Between UTC 15:00 (JST 00:00) and UTC 24:00, the two buckets differ."""
    jst_bucket = _jst_day_bucket()
    utc_bucket = _api_key_day_bucket()

    # 18:00 UTC on 2026-06-15 == 03:00 JST on 2026-06-16.
    inside_window = datetime(2026, 6, 15, 18, 0, 0, tzinfo=UTC)
    assert utc_bucket(inside_window) == "2026-06-15"  # UTC still day N
    assert jst_bucket(inside_window) == "2026-06-16"  # JST already day N+1
    assert utc_bucket(inside_window) != jst_bucket(inside_window)


def test_buckets_align_outside_overlap_window():
    """At UTC 13:00 (JST 22:00 same UTC date) the two buckets match."""
    jst_bucket = _jst_day_bucket()
    utc_bucket = _api_key_day_bucket()

    # 13:00 UTC on 2026-06-15 == 22:00 JST on 2026-06-15 (same calendar day).
    aligned_instant = datetime(2026, 6, 15, 13, 0, 0, tzinfo=UTC)
    assert utc_bucket(aligned_instant) == "2026-06-15"
    assert jst_bucket(aligned_instant) == "2026-06-15"


# ---------------------------------------------------------------------------
# Naive-datetime hardening: `_jst_day_bucket` documents that a naive
# datetime is treated as UTC. Make sure that contract still holds — a
# silent regression here would silently corrupt quota accounting.
# ---------------------------------------------------------------------------


def test_anon_naive_datetime_treated_as_utc():
    """Naive datetime input is interpreted as UTC, then converted to JST."""
    jst_bucket = _jst_day_bucket()

    # No tzinfo. Per the docstring, this is treated as UTC.
    naive = datetime(2026, 6, 15, 14, 59, 0)  # noqa: DTZ001 — intentional
    assert jst_bucket(naive) == "2026-06-15"

    naive_post = datetime(2026, 6, 15, 15, 0, 0)  # noqa: DTZ001 — intentional
    assert jst_bucket(naive_post) == "2026-06-16"


def test_anon_non_utc_input_normalised_to_jst():
    """An input in a non-UTC timezone is converted to JST, not used as-is."""
    jst_bucket = _jst_day_bucket()

    # 10:00 in Pacific/Auckland (UTC+12 in winter, UTC+13 in DST window).
    # Use a fixed offset to avoid DST flakiness.
    nzst = timezone(timedelta(hours=12))
    # 2026-06-16 03:00 NZST == 2026-06-15 15:00 UTC == 2026-06-16 00:00 JST.
    instant = datetime(2026, 6, 16, 3, 0, 0, tzinfo=nzst)
    assert jst_bucket(instant) == "2026-06-16", (
        "Non-UTC tz-aware input must be converted to JST before bucketing"
    )
