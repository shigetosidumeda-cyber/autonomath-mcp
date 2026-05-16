from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from jpintel_mcp.api.deps import get_db, hash_api_key

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture()
def competitor_landscape_client(
    seeded_db: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> TestClient:
    missing_autonomath = tmp_path / "missing-autonomath.db"
    monkeypatch.setenv("AUTONOMATH_DB_PATH", str(missing_autonomath))

    from jpintel_mcp.config import settings
    from jpintel_mcp.mcp.autonomath_tools import db as autonomath_db

    monkeypatch.setattr(settings, "autonomath_db_path", missing_autonomath)
    monkeypatch.setattr(autonomath_db, "AUTONOMATH_DB_PATH", missing_autonomath)
    autonomath_db.close_all()

    import jpintel_mcp.api.intel_competitor_landscape as landscape_mod

    app = FastAPI()
    app.include_router(landscape_mod.router)

    def override_db():
        conn = sqlite3.connect(seeded_db, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    app.dependency_overrides[get_db] = override_db
    return TestClient(app)


def test_competitor_landscape_paid_final_cap_failure_returns_503_without_usage_event(
    competitor_landscape_client: TestClient,
    seeded_db: Path,
    paid_key: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import jpintel_mcp.api.intel_competitor_landscape as landscape_mod

    def _reject_log_usage(*_args: object, **kwargs: object) -> None:
        assert kwargs.get("strict_metering") is True
        raise HTTPException(
            status_code=503,
            detail={
                "code": "billing_cap_final_check_failed",
                "message": (
                    "This paid response was not delivered because the final "
                    "billing-cap check rejected the metered charge."
                ),
            },
        )

    endpoint = "intel.competitor_landscape"
    key_hash = hash_api_key(paid_key)
    monkeypatch.setattr(landscape_mod, "log_usage", _reject_log_usage)

    conn = sqlite3.connect(seeded_db)
    try:
        (before,) = conn.execute(
            "SELECT COUNT(*) FROM usage_events WHERE key_hash = ? AND endpoint = ?",
            (key_hash, endpoint),
        ).fetchone()
    finally:
        conn.close()

    res = competitor_landscape_client.post(
        "/v1/intel/competitor_landscape",
        json={"industry": "E", "peer_limit": 3},
        headers={"X-API-Key": paid_key},
    )

    assert res.status_code == 503, res.text
    assert res.json()["detail"]["code"] == "billing_cap_final_check_failed"

    conn = sqlite3.connect(seeded_db)
    try:
        (after,) = conn.execute(
            "SELECT COUNT(*) FROM usage_events WHERE key_hash = ? AND endpoint = ?",
            (key_hash, endpoint),
        ).fetchone()
    finally:
        conn.close()

    assert after == before


# ===========================================================================
# Pure-helper + envelope-builder coverage (Stream X, 2026-05-16)
# ===========================================================================
#
# Adds direct coverage for the small pure helpers in
# ``api/intel_competitor_landscape.py`` plus an in-memory autonomath stub
# that exercises ``_fetch_seed`` / ``_fetch_peers`` / ``_apply_adoption``
# / ``_apply_enforcement`` / ``_apply_invoice`` / ``_add_differentiators``
# / ``_build_envelope`` without going through TestClient. The existing
# 503-final-cap test above stays as the only HTTP-level case.

import jpintel_mcp.api.intel_competitor_landscape as cl


def test_normalize_houjin_strips_T_prefix_and_dashes() -> None:
    assert cl._normalize_houjin("T8010001213708") == "8010001213708"
    assert cl._normalize_houjin("8010-0012-13708") == "8010001213708"


def test_normalize_houjin_rejects_short_or_letters() -> None:
    assert cl._normalize_houjin("12345") is None
    assert cl._normalize_houjin("abcdefghijklm") is None
    assert cl._normalize_houjin(None) is None
    assert cl._normalize_houjin("") is None


def test_first_existing_returns_first_match() -> None:
    cols = {"name", "industry", "prefecture"}
    assert cl._first_existing(cols, ("normalized_name", "name")) == "name"
    assert cl._first_existing(cols, ("missing", "absent")) is None


def test_missing_appends_unique() -> None:
    out: list[str] = []
    cl._missing(out, "table_a")
    cl._missing(out, "table_a")
    cl._missing(out, "table_b")
    assert out == ["table_a", "table_b"]


def _make_landscape_db(path):
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE houjin_master(
            houjin_bangou TEXT PRIMARY KEY,
            normalized_name TEXT,
            jsic_major TEXT,
            prefecture TEXT
        );
        CREATE TABLE jpi_adoption_records(
            houjin_bangou TEXT,
            program_id TEXT,
            amount_granted_yen INTEGER
        );
        CREATE TABLE am_enforcement_detail(
            houjin_bangou TEXT,
            kind TEXT,
            action_date TEXT
        );
        CREATE TABLE invoice_registrants(
            houjin_bangou TEXT,
            status TEXT
        );
        """
    )
    conn.executemany(
        "INSERT INTO houjin_master(houjin_bangou, normalized_name, jsic_major, prefecture) "
        "VALUES (?, ?, ?, ?)",
        [
            ("8010001213708", "Bookyou株式会社", "M", "東京都"),
            ("9000000000001", "Peer 1", "M", "東京都"),
            ("9000000000002", "Peer 2", "M", "東京都"),
            ("9000000000003", "Peer 3", "M", "大阪府"),
        ],
    )
    conn.executemany(
        "INSERT INTO jpi_adoption_records(houjin_bangou, program_id, amount_granted_yen) "
        "VALUES (?, ?, ?)",
        [
            ("9000000000001", "P-1", 500000),
            ("9000000000001", "P-2", 700000),
            ("9000000000002", "P-1", 300000),
        ],
    )
    conn.executemany(
        "INSERT INTO am_enforcement_detail(houjin_bangou, kind, action_date) VALUES (?, ?, ?)",
        [("9000000000002", "業務改善命令", "2026-01-01")],
    )
    conn.executemany(
        "INSERT INTO invoice_registrants(houjin_bangou, status) VALUES (?, ?)",
        [
            ("9000000000001", "registered"),
            ("9000000000002", "revoked"),
        ],
    )
    conn.commit()
    conn.close()


def test_table_exists_true_and_false(tmp_path):
    p = tmp_path / "lc.db"
    _make_landscape_db(p)
    conn = sqlite3.connect(p)
    conn.row_factory = sqlite3.Row
    try:
        assert cl._table_exists(conn, "houjin_master") is True
        assert cl._table_exists(conn, "nonexistent_table_xyz") is False
    finally:
        conn.close()


def test_columns_returns_expected(tmp_path):
    p = tmp_path / "lc.db"
    _make_landscape_db(p)
    conn = sqlite3.connect(p)
    try:
        cols = cl._columns(conn, "houjin_master")
        assert "houjin_bangou" in cols
        assert "normalized_name" in cols
        assert cl._columns(conn, "nonexistent") == set()
    finally:
        conn.close()


def test_fetch_seed_resolves_from_houjin_master(tmp_path):
    p = tmp_path / "lc.db"
    _make_landscape_db(p)
    conn = sqlite3.connect(p)
    conn.row_factory = sqlite3.Row
    try:
        missing: list[str] = []
        seed = cl._fetch_seed(
            conn,
            houjin_id="8010001213708",
            industry=None,
            prefecture=None,
            missing_tables=missing,
        )
        assert seed["name"] == "Bookyou株式会社"
        assert seed["industry"] == "M"
        assert seed["prefecture"] == "東京都"
        assert missing == []
    finally:
        conn.close()


def test_fetch_seed_unknown_houjin_returns_empty(tmp_path):
    p = tmp_path / "lc.db"
    _make_landscape_db(p)
    conn = sqlite3.connect(p)
    conn.row_factory = sqlite3.Row
    try:
        missing: list[str] = []
        seed = cl._fetch_seed(
            conn,
            houjin_id="9999999999999",
            industry=None,
            prefecture=None,
            missing_tables=missing,
        )
        assert seed["name"] is None
    finally:
        conn.close()


def test_fetch_seed_missing_table(tmp_path):
    p = tmp_path / "lc_empty.db"
    conn = sqlite3.connect(p)
    conn.commit()
    conn.close()
    conn = sqlite3.connect(p)
    try:
        missing: list[str] = []
        seed = cl._fetch_seed(
            conn,
            houjin_id="8010001213708",
            industry=None,
            prefecture=None,
            missing_tables=missing,
        )
        assert "houjin_master" in missing
        assert seed["name"] is None
    finally:
        conn.close()


def test_fetch_peers_filters_by_industry(tmp_path):
    p = tmp_path / "lc.db"
    _make_landscape_db(p)
    conn = sqlite3.connect(p)
    conn.row_factory = sqlite3.Row
    try:
        missing: list[str] = []
        peers = cl._fetch_peers(
            conn,
            seed={
                "houjin_id": "8010001213708",
                "industry": "M",
                "prefecture": None,
            },
            limit=10,
            missing_tables=missing,
        )
        ids = {p["houjin_id"] for p in peers}
        # Seed itself is excluded
        assert "8010001213708" not in ids
        # M-industry peers included
        assert "9000000000001" in ids
    finally:
        conn.close()


def test_fetch_peers_no_filter_fallback(tmp_path):
    p = tmp_path / "lc.db"
    _make_landscape_db(p)
    conn = sqlite3.connect(p)
    conn.row_factory = sqlite3.Row
    try:
        missing: list[str] = []
        peers = cl._fetch_peers(
            conn,
            seed={"houjin_id": None, "industry": None, "prefecture": None},
            limit=10,
            missing_tables=missing,
        )
        assert len(peers) >= 1
    finally:
        conn.close()


def test_apply_adoption_populates_counts(tmp_path):
    p = tmp_path / "lc.db"
    _make_landscape_db(p)
    conn = sqlite3.connect(p)
    conn.row_factory = sqlite3.Row
    peers = [
        {
            "houjin_id": "9000000000001",
            "name": "Peer 1",
            "industry": "M",
            "prefecture": "東京都",
            "adoption": {"count": 0, "total_amount_yen": 0, "top_programs": []},
            "enforcement": {"count": 0, "latest_action_date": None, "kinds": []},
            "invoice": {"registered": None, "status": "unknown"},
            "differentiators": [],
        },
    ]
    try:
        cl._apply_adoption(conn, peers, [])
        assert peers[0]["adoption"]["count"] == 2
        assert peers[0]["adoption"]["total_amount_yen"] == 1200000
    finally:
        conn.close()


def test_apply_enforcement_populates(tmp_path):
    p = tmp_path / "lc.db"
    _make_landscape_db(p)
    conn = sqlite3.connect(p)
    conn.row_factory = sqlite3.Row
    peers = [
        {
            "houjin_id": "9000000000002",
            "name": "Peer 2",
            "industry": "M",
            "prefecture": "東京都",
            "adoption": {"count": 0, "total_amount_yen": 0, "top_programs": []},
            "enforcement": {"count": 0, "latest_action_date": None, "kinds": []},
            "invoice": {"registered": None, "status": "unknown"},
            "differentiators": [],
        },
    ]
    try:
        cl._apply_enforcement(conn, peers, [])
        assert peers[0]["enforcement"]["count"] == 1
        assert peers[0]["enforcement"]["latest_action_date"] == "2026-01-01"
    finally:
        conn.close()


def test_apply_invoice_handles_revoked(tmp_path):
    p = tmp_path / "lc.db"
    _make_landscape_db(p)
    conn = sqlite3.connect(p)
    conn.row_factory = sqlite3.Row
    peers = [
        {
            "houjin_id": "9000000000001",
            "name": "Peer 1",
            "industry": "M",
            "prefecture": "東京都",
            "adoption": {"count": 0, "total_amount_yen": 0, "top_programs": []},
            "enforcement": {"count": 0, "latest_action_date": None, "kinds": []},
            "invoice": {"registered": None, "status": "unknown"},
            "differentiators": [],
        },
        {
            "houjin_id": "9000000000002",
            "name": "Peer 2",
            "industry": "M",
            "prefecture": "東京都",
            "adoption": {"count": 0, "total_amount_yen": 0, "top_programs": []},
            "enforcement": {"count": 0, "latest_action_date": None, "kinds": []},
            "invoice": {"registered": None, "status": "unknown"},
            "differentiators": [],
        },
    ]
    try:
        cl._apply_invoice(conn, peers, [])
        # peer 1: registered
        assert peers[0]["invoice"]["registered"] is True
        # peer 2: revoked → registered=False
        assert peers[1]["invoice"]["registered"] is False
    finally:
        conn.close()


def test_add_differentiators_summarizes() -> None:
    peers = [
        {
            "houjin_id": "A",
            "adoption": {"count": 5, "total_amount_yen": 5_000_000, "top_programs": []},
            "enforcement": {"count": 0, "latest_action_date": None, "kinds": []},
            "invoice": {"registered": True, "status": "registered"},
            "differentiators": [],
        },
        {
            "houjin_id": "B",
            "adoption": {"count": 0, "total_amount_yen": 0, "top_programs": []},
            "enforcement": {"count": 1, "latest_action_date": "2026-01-01", "kinds": []},
            "invoice": {"registered": False, "status": "revoked"},
            "differentiators": [],
        },
    ]
    summary = cl._add_differentiators(peers)
    assert isinstance(summary, list)
    # Peer A is above average on adoption count + amount.
    assert "above_peer_average_adoption" in peers[0]["differentiators"]
    assert "above_peer_average_amount" in peers[0]["differentiators"]
    assert "invoice_registered" in peers[0]["differentiators"]
    # Peer B has enforcement footprint.
    assert "enforcement_footprint" in peers[1]["differentiators"]


def test_add_differentiators_empty_peers_returns_empty() -> None:
    out = cl._add_differentiators([])
    assert out == []


def test_build_envelope_no_db_path() -> None:
    payload = cl.CompetitorLandscapeRequest(
        houjin_id=None, industry="M", prefecture="東京都", peer_limit=3
    )
    body = cl._build_envelope(None, payload)
    assert body["peers"] == []
    assert "autonomath.db" in body["data_quality"]["missing_tables"]
    assert "_disclaimer" in body
    assert body["_billing_unit"] == 1


def test_build_envelope_with_db(tmp_path):
    p = tmp_path / "lc.db"
    _make_landscape_db(p)
    conn = sqlite3.connect(p)
    conn.row_factory = sqlite3.Row
    try:
        payload = cl.CompetitorLandscapeRequest(
            houjin_id="8010001213708", industry="M", prefecture="東京都", peer_limit=3
        )
        body = cl._build_envelope(conn, payload)
        assert body["seed"]["name"] == "Bookyou株式会社"
        assert len(body["peers"]) >= 1
        assert "_disclaimer" in body
        assert body["_billing_unit"] == 1
    finally:
        conn.close()


def test_disclaimer_keyword_fences() -> None:
    # 景表法 fence required for advertising/sales use.
    assert "景表法" in cl._DISCLAIMER


def test_request_schema_peer_limit_bounds() -> None:
    cl.CompetitorLandscapeRequest(industry="M", peer_limit=1)
    cl.CompetitorLandscapeRequest(industry="M", peer_limit=10)
    with pytest.raises(Exception):  # noqa: B017 — pydantic ValidationError
        cl.CompetitorLandscapeRequest(industry="M", peer_limit=11)
    with pytest.raises(Exception):  # noqa: B017
        cl.CompetitorLandscapeRequest(industry="M", peer_limit=0)


def test_request_schema_houjin_length() -> None:
    # 13 + leading T = 14 chars max
    cl.CompetitorLandscapeRequest(houjin_id="8010001213708")
    cl.CompetitorLandscapeRequest(houjin_id="T8010001213708")
    with pytest.raises(Exception):  # noqa: B017
        cl.CompetitorLandscapeRequest(houjin_id="abc")
