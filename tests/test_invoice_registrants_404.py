"""Contract tests for the enriched 404 on /v1/invoice_registrants/{T...}.

Background — H8 audience walk surfaced that a Bookyou self-lookup
(T8010001213708) returns 404 because production currently only mirrors a
~14k-row delta of the ~4M-row 適格事業者 universe (full bulk ingest is
post-launch monthly). A bare `{"detail": "..."}` 404 reads as "this
service is broken"; an enriched body reads as "your number isn't in our
partial mirror — here is the official lookup".

These tests pin the 404 body shape so a future refactor can't silently
regress to a bare `detail` string.
"""

import sqlite3
from pathlib import Path

import pytest

# Bookyou株式会社. Real T-number; safe to ship in tests because it is
# already published on国税庁公表サイト and on this project's invoice in
# `docs/_internal/`. Using a real T-number (vs. a synthetic one that
# happens to land in the test fixture) keeps the test honest about the
# user-visible scenario the endpoint exists to address.
_BOOKYOU_T = "T8010001213708"


@pytest.fixture()
def empty_invoice_db(seeded_db: Path) -> Path:
    """Force the invoice_registrants table to be empty for these tests.

    The session-scoped seeded_db fixture doesn't seed any registrants, but
    other tests in the suite (or future ones) might. We DELETE here so
    `snapshot_size` in the 404 body has a predictable value to assert on.
    """
    c = sqlite3.connect(seeded_db)
    try:
        c.execute("DELETE FROM invoice_registrants")
        c.commit()
    finally:
        c.close()
    return seeded_db


def test_get_404_body_shape(client, empty_invoice_db):
    """404 body MUST carry the enriched contract fields."""
    r = client.get(f"/v1/invoice_registrants/{_BOOKYOU_T}")
    assert r.status_code == 404
    body = r.json()

    # Required keys per the H8 audience-walk fix.
    for key in (
        "detail",
        "registration_number",
        "snapshot_size",
        "full_population_estimate",
        "snapshot_attribution",
        "next_bulk_refresh",
        "alternative",
        "attribution",
    ):
        assert key in body, f"missing key: {key}"

    # The detail string is intentionally user-facing English. Pin it so
    # copy changes go through review.
    assert body["detail"] == "Not found in current registrant snapshot."
    # Echo of the path param so callers can correlate without re-parsing
    # the request URL (handy for batched calls / agent context windows).
    assert body["registration_number"] == _BOOKYOU_T
    # Live count, not a hardcoded 13801 — see the COUNT(*) in the handler.
    # With the empty fixture this is exactly 0.
    assert body["snapshot_size"] == 0
    # Stable string (NOT a precise figure — see the comment on
    # _FULL_POPULATION_ESTIMATE).
    assert "4,000,000" in body["full_population_estimate"]
    # snapshot_attribution embeds both 出典 and license — string match
    # rather than equality so future copy nudges don't break the test.
    assert "国税庁" in body["snapshot_attribution"]
    assert "PDL v1.0" in body["snapshot_attribution"]
    # NTA's official lookup URL must appear in `alternative` so callers
    # have an immediate fallback path on miss.
    assert "invoice-kohyo.nta.go.jp/regno-search" in body["alternative"]


def test_get_404_attribution_block_intact(client, empty_invoice_db):
    """PDL v1.0 attribution must be present on 404, not just on 200.

    Migration 019's contract is "every surface that renders any
    invoice_registrants field". `snapshot_size` counts as a rendered
    field, so the block is required even when no row body is returned.
    """
    r = client.get(f"/v1/invoice_registrants/{_BOOKYOU_T}")
    assert r.status_code == 404
    attr = r.json()["attribution"]
    # Same shape the 2xx path uses — single source of truth in the module.
    assert attr["source"].startswith("国税庁")
    assert attr["license"] == "公共データ利用規約 第1.0版 (PDL v1.0)"
    assert attr["edited"] is True
    assert "発行元サイト" in attr["notice"]


def test_get_422_unchanged_for_malformed(client, empty_invoice_db):
    """Malformed T-numbers still 422 (not 404).

    The enriched-404 only fires for syntactically-valid registration
    numbers. A bad shape ("T1" / "garbage") still gets the regex 422 so
    callers can distinguish "you sent garbage" from "we don't have it".
    """
    r = client.get("/v1/invoice_registrants/T1")
    assert r.status_code == 422


def test_get_404_no_attribution_on_search_path(client, empty_invoice_db):
    """Sanity: search endpoint is unaffected by the 404 enrichment.

    Search returns an empty `results` array with attribution; it never
    404s. Pinning this here so a future "let's enrich search 404s too"
    refactor remembers there is no search 404 to enrich.
    """
    r = client.get("/v1/invoice_registrants/search", params={"limit": 5})
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 0
    assert body["results"] == []
    assert body["attribution"]["license"].startswith("公共データ利用規約")
