"""Tests for /v1/billing/client_tag_breakdown — 顧問先別 client_tag 利用明細.

Covers the 60-day deliverable spec from
docs/_internal/value_maximization_plan_no_llm_api.md §28.1 + §28.7:

  * Aggregation: COUNT(*), SUM(quantity), ¥3/req unit price.
  * Tax math: ×1.10 with 切り捨て (Python int() truncation).
  * Sort: by_client_tag DESC by yen_excl_tax.
  * NULL client_tag surfaced as the "untagged" bucket — never dropped.
  * Period filter (JST calendar inclusive).
  * Cross-account isolation: account A cannot see account B's events.
  * CSV format with proper header + RFC 4180 escapes.
"""
from __future__ import annotations

import sqlite3
import uuid
from datetime import UTC, date, datetime, timedelta, timezone
from typing import TYPE_CHECKING

import pytest

from jpintel_mcp.api.deps import hash_api_key
from jpintel_mcp.billing.keys import issue_child_key, issue_key

if TYPE_CHECKING:
    from pathlib import Path

# JST = UTC+9 — match the constant in api/billing_breakdown.py so test
# fixtures land on the same calendar boundary the endpoint uses.
_JST = timezone(timedelta(hours=9))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def breakdown_key(seeded_db: Path) -> str:
    """A metered API key used by all breakdown tests.

    Each test instantiates its own key (uuid-suffixed sub_id) to keep
    usage_events fixtures isolated from the shared paid_key fixture
    other tests rely on.
    """
    c = sqlite3.connect(seeded_db)
    c.row_factory = sqlite3.Row
    sub_id = f"sub_breakdown_{uuid.uuid4().hex[:8]}"
    raw = issue_key(
        c,
        customer_id="cus_breakdown_acct_a",
        tier="paid",
        stripe_subscription_id=sub_id,
    )
    c.commit()
    c.close()
    return raw


def _ts_jst(d: date, hour: int = 12) -> str:
    """Return an ISO8601 JST-anchored timestamp on date `d`.

    The breakdown endpoint converts its half-open SQL bound to JST so
    fixtures must store JST-anchored timestamps to be picked up by the
    period filter. UTC-anchored ones would slide into the wrong day for
    the last 9 hours of every JST day.
    """
    return datetime(d.year, d.month, d.day, hour, 0, 0, tzinfo=_JST).isoformat()


def _seed_events(
    seeded_db: Path,
    *,
    key_hash: str,
    rows: list[tuple[str | None, date, int]],  # (client_tag, ts_date, quantity)
) -> None:
    """Insert usage_events rows for the test fixture.

    Each row is (client_tag, ts_date, quantity). status=200, metered=1.
    """
    c = sqlite3.connect(seeded_db)
    try:
        c.executemany(
            "INSERT INTO usage_events("
            "  key_hash, endpoint, ts, status, metered, client_tag, quantity"
            ") VALUES (?,?,?,?,?,?,?)",
            [
                (key_hash, "test", _ts_jst(d), 200, 1, tag, qty)
                for (tag, d, qty) in rows
            ],
        )
        c.commit()
    finally:
        c.close()


def _seed_raw_usage_events(
    seeded_db: Path,
    rows: list[tuple[str, str, int | None, int | None, str | None, int | None]],
) -> None:
    c = sqlite3.connect(seeded_db)
    try:
        c.executemany(
            "INSERT INTO usage_events("
            "  key_hash, endpoint, ts, status, metered, client_tag, quantity"
            ") VALUES (?,?,?,?,?,?,?)",
            rows,
        )
        c.commit()
    finally:
        c.close()


def _today_jst() -> date:
    return datetime.now(_JST).date()


# ---------------------------------------------------------------------------
# Test 1: response totals match COUNT/SUM
# ---------------------------------------------------------------------------


def test_breakdown_totals_match_count_and_sum(
    client, breakdown_key: str, seeded_db: Path
):
    """100 rows across 3 client_tags + 5 untagged. Totals reconcile.

    Layout:
      顧問先A: 30 rows × quantity=1 = 30 units → ¥90
      顧問先B: 40 rows × quantity=2 = 80 units → ¥240
      顧問先C: 25 rows × quantity=1 = 25 units → ¥75
      untagged: 5 rows × quantity=1 = 5 units → ¥15

    Total: 100 wall-clock requests, 140 billable units, ¥420 ex-tax.
    """
    kh = hash_api_key(breakdown_key)
    today = _today_jst()
    rows = (
        [("kogyosaki_a", today, 1)] * 30
        + [("kogyosaki_b", today, 2)] * 40
        + [("kogyosaki_c", today, 1)] * 25
        + [(None, today, 1)] * 5
    )
    _seed_events(seeded_db, key_hash=kh, rows=rows)

    r = client.get(
        "/v1/billing/client_tag_breakdown",
        headers={"X-API-Key": breakdown_key},
    )
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["total_requests"] == 100
    assert body["total_billable_units"] == 140
    assert body["total_billable_yen_excl_tax"] == 420
    # ¥420 × 1.10 = ¥462 (no rounding edge here).
    assert body["total_billable_yen_incl_tax"] == 462
    assert body["tax_rate"] == 0.10
    assert body["account_id"] == "cus_breakdown_acct_a"

    # By-tag sum reconciles to the totals.
    units_sum = sum(row["billable_units"] for row in body["by_client_tag"])
    yen_sum = sum(row["yen_excl_tax"] for row in body["by_client_tag"])
    assert units_sum == 140
    assert yen_sum == 420

    # 4 distinct buckets including the untagged one.
    assert len(body["by_client_tag"]) == 4

    # Untagged surfaced separately.
    assert body["untagged_requests"] == 5
    assert body["untagged_yen"] == 15


# ---------------------------------------------------------------------------
# Test 2: by_client_tag sorted by yen DESC
# ---------------------------------------------------------------------------


def test_breakdown_sorted_by_yen_desc(
    client, breakdown_key: str, seeded_db: Path
):
    kh = hash_api_key(breakdown_key)
    today = _today_jst()
    # tag_b has the highest yen (40 units) > tag_c (25) > tag_a (30 with q=1)
    rows = (
        [("tag_a", today, 1)] * 30   # 30 units → ¥90
        + [("tag_b", today, 4)] * 10  # 40 units → ¥120
        + [("tag_c", today, 1)] * 25  # 25 units → ¥75
    )
    _seed_events(seeded_db, key_hash=kh, rows=rows)

    r = client.get(
        "/v1/billing/client_tag_breakdown",
        headers={"X-API-Key": breakdown_key},
    )
    assert r.status_code == 200, r.text
    tags = [row["client_tag"] for row in r.json()["by_client_tag"]]
    assert tags == ["tag_b", "tag_a", "tag_c"]

    yen_values = [row["yen_excl_tax"] for row in r.json()["by_client_tag"]]
    assert yen_values == sorted(yen_values, reverse=True)


def test_breakdown_totals_include_rows_beyond_max_breakdown_rows(
    client, breakdown_key: str, seeded_db: Path
):
    """Grand totals reconcile even when the visible by-tag list is capped."""
    kh = hash_api_key(breakdown_key)
    today = _today_jst()
    _seed_events(
        seeded_db,
        key_hash=kh,
        rows=[(f"tag_{i:04d}", today, 1) for i in range(1001)],
    )

    r = client.get(
        "/v1/billing/client_tag_breakdown",
        headers={"X-API-Key": breakdown_key},
    )
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["capped_at_max_rows"] is True
    assert len(body["by_client_tag"]) == 1000
    assert body["total_requests"] == 1001
    assert body["total_billable_units"] == 1001
    assert body["total_billable_yen_excl_tax"] == 3003


# ---------------------------------------------------------------------------
# Test 3: tax calc — exact ¥100,000 → ¥110,000
# ---------------------------------------------------------------------------


def test_breakdown_tax_exact_round_number(
    client, breakdown_key: str, seeded_db: Path
):
    """Exactly ¥100,000 ex-tax → ¥110,000 inc-tax (no rounding edge)."""
    kh = hash_api_key(breakdown_key)
    today = _today_jst()
    # ¥100,000 / ¥3 per unit = 33,333.33 — use quantity to land exactly.
    # 1 row × quantity=33333 + 1 row × quantity=1/3 (impossible) — instead
    # use 100,000 / 3 doesn't divide evenly, so use 33,333 units + 1 unit
    # = ¥100,002 (close to ¥100,000 but exact). Cleaner: 10 rows × q=10,000
    # = 100,000 units × ¥3 = ¥300,000 — nope. We want yen_excl == 100000.
    # 100000 / 3 isn't integer, so pick yen_excl = 99,999 instead and
    # do separate rounding test below (Test 4 already covers truncation).
    # For this test: pick units such that yen_excl_tax * 1.10 has no
    # fractional yen. units * 3 * 1.10 = units * 3.30; for that to be
    # integer: units must be a multiple of 10. So pick 10,000 units →
    # yen_excl = ¥30,000, yen_inc = ¥33,000.
    rows = [(None, today, 10000)]  # 1 row, quantity=10000 → 10,000 units
    _seed_events(seeded_db, key_hash=kh, rows=rows)

    r = client.get(
        "/v1/billing/client_tag_breakdown",
        headers={"X-API-Key": breakdown_key},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total_billable_yen_excl_tax"] == 30000
    assert body["total_billable_yen_incl_tax"] == 33000  # 30000 × 1.10, exact


def test_breakdown_tax_100k_inclusive_110k(
    client, breakdown_key: str, seeded_db: Path
):
    """Direct ¥100,000 → ¥110,000 cross-check via _consumption_tax helper."""
    from jpintel_mcp.api.billing_breakdown import _consumption_tax_inclusive_yen

    assert _consumption_tax_inclusive_yen(100_000) == 110_000


# ---------------------------------------------------------------------------
# Test 4: tax rounding — ¥99 → ¥108 (切り捨て, NOT 109)
# ---------------------------------------------------------------------------


def test_breakdown_tax_truncates_kirisute(
    client, breakdown_key: str, seeded_db: Path
):
    """¥99 ex-tax → ¥108 inc-tax (¥99 × 1.10 = ¥108.9 → 切り捨て ¥108)."""
    from jpintel_mcp.api.billing_breakdown import _consumption_tax_inclusive_yen

    # Direct helper assertion (the spec's spotlight).
    assert _consumption_tax_inclusive_yen(99) == 108
    # Ensure we are NOT bankers'-rounding to 109.
    assert _consumption_tax_inclusive_yen(99) != 109

    # Also exercise via the endpoint: 33 units * ¥3 = ¥99.
    kh = hash_api_key(breakdown_key)
    today = _today_jst()
    _seed_events(seeded_db, key_hash=kh, rows=[(None, today, 33)])

    r = client.get(
        "/v1/billing/client_tag_breakdown",
        headers={"X-API-Key": breakdown_key},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total_billable_yen_excl_tax"] == 99
    assert body["total_billable_yen_incl_tax"] == 108


# ---------------------------------------------------------------------------
# Test 5: CSV format — text/csv with proper header
# ---------------------------------------------------------------------------


def test_breakdown_csv_format(
    client, breakdown_key: str, seeded_db: Path
):
    kh = hash_api_key(breakdown_key)
    today = _today_jst()
    rows = (
        [("tag_alpha", today, 2)] * 5
        + [("tag, with comma", today, 1)] * 3  # forces RFC 4180 quoting
        + [(None, today, 1)] * 2
    )
    _seed_events(seeded_db, key_hash=kh, rows=rows)

    r = client.get(
        "/v1/billing/client_tag_breakdown",
        params={"format": "csv"},
        headers={"X-API-Key": breakdown_key},
    )
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/csv")
    # UTF-8 BOM stripped during decode by httpx? Test the bytes.
    raw = r.content
    assert raw.startswith("﻿".encode())  # UTF-8 BOM (Excel-JP)

    # Header row matches spec.
    text = raw.decode("utf-8").lstrip("﻿")
    lines = text.strip().split("\r\n")
    assert lines[0] == (
        "period_start,period_end,client_tag,requests,billable_units,"
        "yen_excl_tax,first_seen,last_seen"
    )
    # Header + 3 data rows (2 tagged + 1 untagged).
    assert len(lines) == 1 + 3

    # The comma-bearing tag must be RFC 4180 quoted ("tag, with comma").
    quoted_row = next((line for line in lines[1:] if "tag, with comma" in line), None)
    assert quoted_row is not None, lines
    assert '"tag, with comma"' in quoted_row


# ---------------------------------------------------------------------------
# Test 6: period filter — rows outside the window not counted
# ---------------------------------------------------------------------------


def test_breakdown_period_filter_excludes_outside_rows(
    client, breakdown_key: str, seeded_db: Path
):
    """Period [today-2, today]: rows on today-5 must NOT appear."""
    kh = hash_api_key(breakdown_key)
    today = _today_jst()
    in_window = today - timedelta(days=1)
    out_window = today - timedelta(days=5)

    rows = (
        [("inside_tag", in_window, 1)] * 7   # in: 7 units ¥21
        + [("outside_tag", out_window, 1)] * 100  # out: must be excluded
    )
    _seed_events(seeded_db, key_hash=kh, rows=rows)

    r = client.get(
        "/v1/billing/client_tag_breakdown",
        params={
            "period_start": (today - timedelta(days=2)).isoformat(),
            "period_end": today.isoformat(),
        },
        headers={"X-API-Key": breakdown_key},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total_requests"] == 7
    assert body["total_billable_units"] == 7
    assert body["total_billable_yen_excl_tax"] == 21
    tags = [row["client_tag"] for row in body["by_client_tag"]]
    assert tags == ["inside_tag"]
    assert "outside_tag" not in tags


def test_breakdown_only_counts_billable_success_rows(
    client, breakdown_key: str, seeded_db: Path
):
    kh = hash_api_key(breakdown_key)
    today = _today_jst()
    ts = _ts_jst(today)
    _seed_raw_usage_events(
        seeded_db,
        [
            (kh, "billable.quantity_one", ts, 200, 1, "kept", 1),
            (kh, "billable.quantity_two", ts, 201, 1, "kept", 2),
            (kh, "failed", ts, 500, 1, "drop_failed", 9),
            (kh, "client_error", ts, 404, 1, "drop_4xx", 9),
            (kh, "unmetered", ts, 200, 0, "drop_unmetered", 9),
        ],
    )

    r = client.get(
        "/v1/billing/client_tag_breakdown",
        params={"period_start": today.isoformat(), "period_end": today.isoformat()},
        headers={"X-API-Key": breakdown_key},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total_requests"] == 2
    assert body["total_billable_units"] == 3
    assert body["total_billable_yen_excl_tax"] == 9
    assert [row["client_tag"] for row in body["by_client_tag"]] == ["kept"]


def test_breakdown_uses_jst_day_for_utc_stored_events(
    client, breakdown_key: str, seeded_db: Path
):
    kh = hash_api_key(breakdown_key)
    may_1_jst_start_utc = datetime(2026, 4, 30, 15, 0, 0, tzinfo=UTC).isoformat()
    april_30_jst_utc = datetime(2026, 4, 30, 14, 59, 59, tzinfo=UTC).isoformat()
    may_2_jst_start_utc = datetime(2026, 5, 1, 15, 0, 0, tzinfo=UTC).isoformat()
    _seed_raw_usage_events(
        seeded_db,
        [
            (kh, "april_jst", april_30_jst_utc, 200, 1, "drop_april", 5),
            (kh, "may_1_jst", may_1_jst_start_utc, 200, 1, "may_1", 2),
            (kh, "may_2_jst", may_2_jst_start_utc, 200, 1, "drop_may_2", 7),
        ],
    )

    r = client.get(
        "/v1/billing/client_tag_breakdown",
        params={"period_start": "2026-05-01", "period_end": "2026-05-01"},
        headers={"X-API-Key": breakdown_key},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total_requests"] == 1
    assert body["total_billable_units"] == 2
    assert body["by_client_tag"][0]["client_tag"] == "may_1"
    assert body["by_client_tag"][0]["first_seen"] == "2026-05-01"
    assert body["by_client_tag"][0]["last_seen"] == "2026-05-01"


# ---------------------------------------------------------------------------
# Test 7: cross-account isolation
# ---------------------------------------------------------------------------


def test_breakdown_cross_account_isolation(
    client, breakdown_key: str, seeded_db: Path
):
    """Account A's request must not see account B's usage_events."""
    # Set up account B's key + events.
    c = sqlite3.connect(seeded_db)
    c.row_factory = sqlite3.Row
    raw_b = issue_key(
        c,
        customer_id="cus_breakdown_acct_b",
        tier="paid",
        stripe_subscription_id=f"sub_b_{uuid.uuid4().hex[:8]}",
    )
    c.commit()
    c.close()

    kh_a = hash_api_key(breakdown_key)
    kh_b = hash_api_key(raw_b)
    today = _today_jst()
    _seed_events(
        seeded_db,
        key_hash=kh_a,
        rows=[("acct_a_tag", today, 1)] * 4,  # 4 units → ¥12
    )
    _seed_events(
        seeded_db,
        key_hash=kh_b,
        rows=[("acct_b_secret", today, 5)] * 100,  # 500 units → ¥1500 (B-only)
    )

    r = client.get(
        "/v1/billing/client_tag_breakdown",
        headers={"X-API-Key": breakdown_key},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    # A sees only its own ¥12.
    assert body["total_billable_yen_excl_tax"] == 12
    tags = [row["client_tag"] for row in body["by_client_tag"]]
    assert tags == ["acct_a_tag"]
    assert "acct_b_secret" not in tags

    # And vice versa — querying as B sees only B's data.
    r2 = client.get(
        "/v1/billing/client_tag_breakdown",
        headers={"X-API-Key": raw_b},
    )
    assert r2.status_code == 200, r2.text
    b_body = r2.json()
    assert b_body["total_billable_yen_excl_tax"] == 1500
    b_tags = [row["client_tag"] for row in b_body["by_client_tag"]]
    assert b_tags == ["acct_b_secret"]
    assert "acct_a_tag" not in b_tags


def test_child_key_breakdown_does_not_expose_sibling_usage(
    client, breakdown_key: str, seeded_db: Path
):
    """Child keys see only their own client_tag rows, not siblings."""
    parent_hash = hash_api_key(breakdown_key)
    c = sqlite3.connect(seeded_db)
    c.row_factory = sqlite3.Row
    try:
        child_a, child_a_hash = issue_child_key(
            c, parent_key_hash=parent_hash, label="child-a"
        )
        child_b, child_b_hash = issue_child_key(
            c, parent_key_hash=parent_hash, label="child-b"
        )
        c.commit()
    finally:
        c.close()

    today = _today_jst()
    _seed_events(
        seeded_db,
        key_hash=parent_hash,
        rows=[("parent_tag", today, 1)] * 2,
    )
    _seed_events(
        seeded_db,
        key_hash=child_a_hash,
        rows=[("child_a_tag", today, 1)] * 3,
    )
    _seed_events(
        seeded_db,
        key_hash=child_b_hash,
        rows=[("child_b_secret", today, 1)] * 5,
    )

    r = client.get(
        "/v1/billing/client_tag_breakdown",
        headers={"X-API-Key": child_a},
    )
    assert r.status_code == 200, r.text
    child_body = r.json()
    assert child_body["total_requests"] == 3
    assert [row["client_tag"] for row in child_body["by_client_tag"]] == [
        "child_a_tag"
    ]

    parent = client.get(
        "/v1/billing/client_tag_breakdown",
        headers={"X-API-Key": breakdown_key},
    )
    assert parent.status_code == 200, parent.text
    parent_tags = {row["client_tag"] for row in parent.json()["by_client_tag"]}
    assert {"parent_tag", "child_a_tag", "child_b_secret"} <= parent_tags


# ---------------------------------------------------------------------------
# Test 8: untagged rows surfaced as client_tag: null (NOT dropped)
# ---------------------------------------------------------------------------


def test_breakdown_surfaces_untagged_as_null(
    client, breakdown_key: str, seeded_db: Path
):
    """Rows with NULL client_tag MUST appear as a client_tag: null bucket."""
    kh = hash_api_key(breakdown_key)
    today = _today_jst()
    rows = (
        [("alpha", today, 1)] * 3
        + [(None, today, 1)] * 7  # 7 untagged → ¥21
    )
    _seed_events(seeded_db, key_hash=kh, rows=rows)

    r = client.get(
        "/v1/billing/client_tag_breakdown",
        headers={"X-API-Key": breakdown_key},
    )
    assert r.status_code == 200, r.text
    body = r.json()

    # The untagged bucket exists — and its tag is JSON null.
    untagged_buckets = [
        row for row in body["by_client_tag"] if row["client_tag"] is None
    ]
    assert len(untagged_buckets) == 1
    assert untagged_buckets[0]["requests"] == 7
    assert untagged_buckets[0]["billable_units"] == 7
    assert untagged_buckets[0]["yen_excl_tax"] == 21

    # And the top-level untagged_* totals match.
    assert body["untagged_requests"] == 7
    assert body["untagged_yen"] == 21


# ---------------------------------------------------------------------------
# Auth + period guards (defensive)
# ---------------------------------------------------------------------------


def test_breakdown_requires_api_key(client):
    r = client.get("/v1/billing/client_tag_breakdown")
    assert r.status_code == 401


def test_breakdown_unauthenticated_does_not_consume_anon_quota(
    client, seeded_db: Path
):
    r = client.get("/v1/billing/client_tag_breakdown")
    assert r.status_code == 401

    c = sqlite3.connect(seeded_db)
    try:
        count = c.execute("SELECT COUNT(*) FROM anon_rate_limit").fetchone()[0]
    finally:
        c.close()
    assert count == 0


def test_breakdown_rejects_inverted_period(client, breakdown_key: str):
    today = _today_jst()
    r = client.get(
        "/v1/billing/client_tag_breakdown",
        params={
            "period_start": today.isoformat(),
            "period_end": (today - timedelta(days=1)).isoformat(),
        },
        headers={"X-API-Key": breakdown_key},
    )
    assert r.status_code == 422


def test_breakdown_rejects_malformed_period(client, breakdown_key: str):
    r = client.get(
        "/v1/billing/client_tag_breakdown",
        params={"period_start": "not-a-date"},
        headers={"X-API-Key": breakdown_key},
    )
    assert r.status_code == 422
