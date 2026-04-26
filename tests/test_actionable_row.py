"""Tests for the 'actionable row' fields on Program / ProgramDetail.

These are the fields a caller needs to act on a search hit without a second
round-trip:

  - next_deadline: next open-window ISO date (past-filtered at serialize time)
  - application_url: where to send the applicant (aliases official_url for now)
  - required_documents: document-name list (detail-only; heavy enriched parse)
"""
from __future__ import annotations

import json
import sqlite3
from datetime import date, timedelta
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

from jpintel_mcp.api.programs import (
    _extract_next_deadline,
    _extract_required_documents,
    _post_cache_next_deadline,
)

if TYPE_CHECKING:
    from pathlib import Path

# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def test_extract_next_deadline_future_iso() -> None:
    future = (date.today() + timedelta(days=30)).isoformat()
    window = {"end_date": future, "cycle": "annual"}
    assert _extract_next_deadline(window) == future


def test_extract_next_deadline_past_iso_not_filtered_here() -> None:
    """Pure helper does NOT filter past; _post_cache_next_deadline does."""
    past = "2022-08-07"
    assert _extract_next_deadline({"end_date": past}) == past


def test_post_cache_next_deadline_drops_past() -> None:
    assert _post_cache_next_deadline("2022-08-07") is None


def test_post_cache_next_deadline_keeps_future() -> None:
    future = (date.today() + timedelta(days=5)).isoformat()
    assert _post_cache_next_deadline(future) == future


def test_post_cache_next_deadline_none_passthrough() -> None:
    assert _post_cache_next_deadline(None) is None


@pytest.mark.parametrize(
    "window",
    [
        None,
        {},
        {"end_date": None},
        {"end_date": ""},
        {"end_date": "not-a-date"},
        {"end_date": "2026-13-45"},  # valid-looking ISO but invalid date
        [],  # wrong shape
    ],
)
def test_extract_next_deadline_malformed(window) -> None:
    assert _extract_next_deadline(window) is None


def test_extract_required_documents_from_extraction_procedure() -> None:
    enriched = {
        "extraction": {
            "procedure": {
                "required_documents": [
                    {"name": "申請書", "format": "PDF"},
                    {"name": "事業計画書", "required": True},
                    "チェックリスト",  # plain string allowed
                ],
            },
        },
    }
    assert _extract_required_documents(enriched) == [
        "申請書",
        "事業計画書",
        "チェックリスト",
    ]


def test_extract_required_documents_deduplicates_order_preserving() -> None:
    enriched = {
        "extraction": {"documents": [{"name": "A"}, {"name": "B"}]},
        "documents": [{"name": "B"}, {"name": "C"}],
    }
    assert _extract_required_documents(enriched) == ["A", "B", "C"]


def test_extract_required_documents_malformed() -> None:
    assert _extract_required_documents(None) == []
    assert _extract_required_documents({}) == []
    assert _extract_required_documents({"documents": "not a list"}) == []


# ---------------------------------------------------------------------------
# REST — search + detail surface the new fields
# ---------------------------------------------------------------------------


def test_search_row_has_application_url(client: TestClient) -> None:
    r = client.get("/v1/programs/search", params={"limit": 5})
    assert r.status_code == 200
    body = r.json()
    assert body["results"], "search should return seeded rows"
    for row in body["results"]:
        assert "application_url" in row
        assert "next_deadline" in row
        # required_documents is detail-only; it must NOT appear at fields=default
        assert "required_documents" not in row


def test_search_minimal_strips_actionable_fields(client: TestClient) -> None:
    """fields=minimal keeps only the 7-key whitelist."""
    r = client.get(
        "/v1/programs/search", params={"limit": 5, "fields": "minimal"}
    )
    assert r.status_code == 200
    for row in r.json()["results"]:
        assert "next_deadline" not in row
        assert "application_url" not in row
        assert "required_documents" not in row


def test_get_program_detail_has_required_documents_key(
    client: TestClient, seeded_db: Path
) -> None:
    """required_documents is always keyed on detail (may be empty list)."""
    r = client.get("/v1/programs/UNI-test-s-1")
    assert r.status_code == 200
    body = r.json()
    assert "required_documents" in body
    assert body["required_documents"] == []  # seeded row has no enriched
    # application_url falls back to official_url (null in seed → null here)
    assert "application_url" in body
    # next_deadline is null (no application_window_json seeded)
    assert body["next_deadline"] is None


def test_search_row_application_url_matches_official_url(client: TestClient) -> None:
    r = client.get("/v1/programs/search", params={"limit": 5})
    for row in r.json()["results"]:
        assert row["application_url"] == row["official_url"]


# ---------------------------------------------------------------------------
# Live deadline — inject a future end_date on a seeded row and verify
# ---------------------------------------------------------------------------


@pytest.fixture()
def seed_future_deadline(seeded_db: Path):
    future = (date.today() + timedelta(days=30)).isoformat()
    conn = sqlite3.connect(seeded_db)
    try:
        conn.execute(
            "UPDATE programs SET application_window_json = ? WHERE unified_id = ?",
            (json.dumps({"end_date": future, "cycle": "annual"}), "UNI-test-s-1"),
        )
        # L4 cache (1h TTL) survives across requests in SQLite — the prior
        # test_get_program_detail_has_required_documents_key call cached the
        # null-deadline body, so without this DELETE the next read returns
        # stale JSON and next_deadline stays None. See Wave 24 diagnosis.
        try:
            conn.execute(
                "DELETE FROM l4_query_cache WHERE tool_name='api.programs.get'"
            )
        except sqlite3.OperationalError:
            # Table may not exist in minimal test schemas — defensive no-op.
            pass
        conn.commit()
    finally:
        conn.close()
    from jpintel_mcp.api.programs import _clear_program_cache

    _clear_program_cache()
    yield future

    # Teardown: null the column back out so later tests see the original state.
    conn = sqlite3.connect(seeded_db)
    try:
        conn.execute(
            "UPDATE programs SET application_window_json = NULL WHERE unified_id = ?",
            ("UNI-test-s-1",),
        )
        try:
            conn.execute(
                "DELETE FROM l4_query_cache WHERE tool_name='api.programs.get'"
            )
        except sqlite3.OperationalError:
            pass
        conn.commit()
    finally:
        conn.close()
    _clear_program_cache()


def test_search_row_emits_future_deadline(
    seed_future_deadline: str, seeded_db: Path
) -> None:
    from jpintel_mcp.api.main import create_app

    c = TestClient(create_app())
    r = c.get("/v1/programs/search", params={"limit": 10})
    assert r.status_code == 200, r.text
    s_row = next(m for m in r.json()["results"] if m["unified_id"] == "UNI-test-s-1")
    assert s_row["next_deadline"] == seed_future_deadline


def test_get_program_emits_future_deadline(
    seed_future_deadline: str, seeded_db: Path
) -> None:
    from jpintel_mcp.api.main import create_app

    c = TestClient(create_app())
    r = c.get("/v1/programs/UNI-test-s-1")
    assert r.status_code == 200, r.text
    assert r.json()["next_deadline"] == seed_future_deadline


# ---------------------------------------------------------------------------
# MCP parity
# ---------------------------------------------------------------------------


def test_mcp_get_program_has_actionable_fields(seeded_db: Path) -> None:
    from jpintel_mcp.mcp.server import get_program as mcp_get_program

    res = mcp_get_program("UNI-test-s-1", fields="default")
    assert "next_deadline" in res
    assert "application_url" in res
    assert "required_documents" in res


def test_mcp_search_programs_has_actionable_fields(seeded_db: Path) -> None:
    from jpintel_mcp.mcp.server import search_programs as mcp_search

    # search_programs default = "minimal" (token shaping, dd_v3_09 / v8 P3-K).
    # Pass fields="default" to verify actionable rows are still wired.
    res = mcp_search(limit=5, fields="default")
    for row in res["results"]:
        assert "next_deadline" in row
        assert "application_url" in row
