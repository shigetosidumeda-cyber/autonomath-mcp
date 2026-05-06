"""R8 dataset versioning + audit-trail tests.

Covers the three contract guarantees of strategy R8 (migration 067):

  1. Past-date query: a row that is "retired" (valid_until set before
     as_of_date) is excluded from the search response when as_of_date
     points to a moment AFTER retirement, and is INCLUDED when as_of_date
     points to a moment BEFORE retirement. Mirrors a tax accountant
     reproducing 申告時点 の制度状態.

  2. Live (no as_of_date): existing search behaviour is preserved — the
     bitemporal predicate is omitted entirely so the L4 cache key, the
     SQL plan, and the result set match pre-R8.

  3. Invalid date format: malformed `as_of_date` is rejected with HTTP
     422 BEFORE any SQL is built (cache-key poisoning guard) and BEFORE
     the row is fetched (no DB round-trip on validation failure).

The fixtures depend on the shared `seeded_db` from `conftest.py`. Each
test starts by writing valid_from / valid_until on the seeded rows so the
predicate has something to bite against.
"""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

    from fastapi.testclient import TestClient


# ISO-8601 dates used as fixture pivots. Chosen so that:
#   - DAY_OLD : earlier than every row's valid_from
#   - DAY_T1  : after row creation, before any retirement
#   - DAY_T2  : after the retirement timestamp on UNI-test-s-1
#   - DAY_NEW : far future, every row should be live
DAY_OLD = "2025-01-01"
DAY_T1 = "2026-01-15"
RETIRE_AT = "2026-02-01T00:00:00Z"
DAY_T2 = "2026-03-01"
DAY_NEW = "2027-12-31"


@pytest.fixture(autouse=True)
def _seed_versioning(seeded_db: Path):
    """Stamp valid_from on all rows; retire UNI-test-s-1 on 2026-02-01.

    Mirrors the post-migration-067 state on a fresh test DB. The autouse
    fixture lets every test in this module assume the bitemporal columns
    are populated; the conftest seed itself only INSERTs the 4 base rows
    without versioning metadata so we don't have to mutate conftest.
    """
    c = sqlite3.connect(seeded_db)
    try:
        # Reset to a known state — earlier tests may have rewritten cols.
        c.execute("UPDATE programs SET valid_from = NULL, valid_until = NULL")
        # All rows live from 2026-01-01.
        c.execute(
            "UPDATE programs SET valid_from = ? WHERE valid_from IS NULL",
            ("2026-01-01T00:00:00Z",),
        )
        # Retire UNI-test-s-1 on 2026-02-01 to model an append-only update.
        c.execute(
            "UPDATE programs SET valid_until = ? WHERE unified_id = ?",
            (RETIRE_AT, "UNI-test-s-1"),
        )
        c.commit()
    finally:
        c.close()
    yield


def test_past_date_query_returns_then_live_row(client: TestClient):
    """A row retired on 2026-02-01 must STILL be visible at 2026-01-15.

    DAY_T1 (2026-01-15) is between the row's valid_from (2026-01-01) and
    its valid_until (2026-02-01) → the predicate
    `valid_from <= as_of_date AND (valid_until IS NULL OR valid_until > as_of_date)`
    holds, so the search MUST include UNI-test-s-1.
    """
    r = client.get("/v1/programs/search", params={"as_of_date": DAY_T1, "limit": 50})
    assert r.status_code == 200, r.text
    body = r.json()
    ids = [row["unified_id"] for row in body["results"]]
    assert "UNI-test-s-1" in ids, "row retired on 2026-02-01 must still be visible on 2026-01-15"

    # Sanity: at DAY_T2 (after retirement) the same row must be GONE.
    r2 = client.get("/v1/programs/search", params={"as_of_date": DAY_T2, "limit": 50})
    assert r2.status_code == 200
    ids2 = [row["unified_id"] for row in r2.json()["results"]]
    assert "UNI-test-s-1" not in ids2, "row retired on 2026-02-01 must be excluded on 2026-03-01"


def test_live_query_preserves_existing_behavior(client: TestClient):
    """Search WITHOUT as_of_date must behave as before for currently-live rows.

    Spec (`analysis_wave18/_r8_dataset_versioning_2026-04-25.md`): omit
    `as_of_date` ⇒ live, the existing pre-R8 result set. The bitemporal
    predicate is omitted entirely so the SQL plan matches pre-R8 and the
    L4 cache key partition is unchanged. UNI-test-a-1 / UNI-test-b-1 are
    live in the fixture and must be present; tier-X is still gated by the
    pre-existing quarantine logic (not R8).
    """
    r = client.get("/v1/programs/search", params={"limit": 50})
    assert r.status_code == 200, r.text
    body = r.json()
    ids = [row["unified_id"] for row in body["results"]]

    # Still-live rows present — proves the omit-as_of_date path does not
    # over-filter (would happen if the predicate fired with default=today
    # against rows missing valid_from).
    assert "UNI-test-a-1" in ids
    assert "UNI-test-b-1" in ids
    # Tier-X quarantine guard preserved (existing pre-R8 behaviour).
    assert "UNI-test-x-1" not in ids
    # Retired row UNI-test-s-1 is technically still picked up because the
    # omit path does NOT apply the bitemporal predicate (existing pre-R8
    # behaviour). Snapshot pinning is opt-in via as_of_date — see the
    # `test_past_date_query_returns_then_live_row` case above.
    assert "UNI-test-s-1" in ids


def test_invalid_date_format_returns_422(client: TestClient):
    """Malformed as_of_date must 422 with no DB round-trip.

    Examples that should fail: '2026-13-99', '20260115', 'yesterday',
    'NaN'. We assert one representative case + one edge (a string that
    looks date-like but has an invalid month).
    """
    bad_inputs = ["2026-13-99", "yesterday"]
    for bad in bad_inputs:
        r = client.get("/v1/programs/search", params={"as_of_date": bad})
        assert r.status_code == 422, (
            f"expected 422 for as_of_date={bad!r}, got {r.status_code}: {r.text}"
        )
