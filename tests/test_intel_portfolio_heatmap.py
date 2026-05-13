from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from jpintel_mcp.api.deps import get_db, hash_api_key
from jpintel_mcp.api.intel_portfolio_heatmap import (
    PortfolioHeatmapRequest,
    _build_envelope,
)

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture()
def portfolio_heatmap_client(
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

    from jpintel_mcp.api import intel_portfolio_heatmap as heatmap_mod

    app = FastAPI()
    app.include_router(heatmap_mod.router)

    def override_db():
        conn = sqlite3.connect(seeded_db, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    app.dependency_overrides[get_db] = override_db
    return TestClient(app)


def test_portfolio_heatmap_paid_final_cap_failure_returns_503_without_usage_event(
    portfolio_heatmap_client: TestClient,
    seeded_db: Path,
    paid_key: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    endpoint = "intel.portfolio_heatmap"
    key_hash = hash_api_key(paid_key)

    def usage_count() -> int:
        conn = sqlite3.connect(seeded_db)
        try:
            (count,) = conn.execute(
                "SELECT COUNT(*) FROM usage_events WHERE key_hash = ? AND endpoint = ?",
                (key_hash, endpoint),
            ).fetchone()
            return int(count)
        finally:
            conn.close()

    from jpintel_mcp.api import intel_portfolio_heatmap as heatmap_mod

    def _rejecting_log_usage(*_args: object, **_kwargs: object) -> None:
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

    before = usage_count()
    monkeypatch.setattr(heatmap_mod, "log_usage", _rejecting_log_usage)

    res = portfolio_heatmap_client.post(
        "/v1/intel/portfolio_heatmap",
        json={"program_ids": ["UNI-test-s-1", "UNI-test-b-1"]},
        headers={"X-API-Key": paid_key},
    )

    assert res.status_code == 503, res.text
    assert res.json()["detail"]["code"] == "billing_cap_final_check_failed"
    assert usage_count() == before


def _heatmap_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE jpi_programs (
            unified_id TEXT PRIMARY KEY,
            primary_name TEXT,
            tier TEXT,
            program_kind TEXT,
            amount_max_man_yen REAL
        );
        """
    )
    conn.executemany(
        """INSERT INTO jpi_programs
           (unified_id, primary_name, tier, program_kind, amount_max_man_yen)
           VALUES (?, ?, ?, ?, ?)""",
        [
            ("P1", "検証済み金額制度", "A", "補助金", None),
            ("P2", "テンプレ既定値のみ制度", "B", "補助金", None),
            ("P3", "プログラム金額ヒント制度", "A", "補助金", 250.0),
        ],
    )
    return conn


def test_portfolio_heatmap_filters_template_default_amounts() -> None:
    conn = _heatmap_conn()
    conn.executescript(
        """
        CREATE TABLE am_amount_condition (
            program_id TEXT,
            amount_max_yen INTEGER,
            quality_tier TEXT,
            template_default INTEGER,
            is_authoritative INTEGER
        );
        """
    )
    conn.executemany(
        """INSERT INTO am_amount_condition
           (program_id, amount_max_yen, quality_tier, template_default, is_authoritative)
           VALUES (?, ?, ?, ?, ?)""",
        [
            ("P1", 123456, "verified", 0, 1),
            ("P1", 90000000, "template_default", 1, 0),
            ("P2", 500000, "template_default", 1, 0),
        ],
    )

    body = _build_envelope(conn, PortfolioHeatmapRequest(program_ids=["P1", "P2"]))

    rows = {row["program_id"]: row for row in body["heatmap_rows"]}
    assert rows["P1"]["amount"]["max_yen"] == 123456
    assert rows["P1"]["amount"]["quality"]["quality_tier"] == "verified"
    assert rows["P1"]["amount"]["quality"]["template_default"] is False
    assert rows["P2"]["amount"]["max_yen"] is None
    assert rows["P2"]["amount"]["quality"]["source"] == "none"
    assert "verified/authoritative" in rows["P2"]["amount"]["quality"]["limitation"]
    assert body["summary"]["total_amount_max_yen"] == 123456
    assert body["summary"]["total_verified_amount_max_yen"] == 123456
    assert "program_amount_hint" in body["summary"]["amount_total_limitation"]
    assert body["summary"]["omitted_amount_condition_count"] == 2
    assert any("omitted 2" in gap for gap in body["known_gaps"])


def test_portfolio_heatmap_omits_legacy_amounts_without_quality_metadata() -> None:
    conn = _heatmap_conn()
    conn.executescript(
        """
        CREATE TABLE am_amount_condition (
            program_id TEXT,
            amount_max_yen INTEGER
        );
        INSERT INTO am_amount_condition (program_id, amount_max_yen)
        VALUES ('P1', 777777);
        """
    )

    body = _build_envelope(conn, PortfolioHeatmapRequest(program_ids=["P1"]))

    row = body["heatmap_rows"][0]
    assert row["amount"]["max_yen"] is None
    assert row["amount"]["quality"]["source"] == "none"
    assert "quality metadata is unavailable" in row["amount"]["quality"]["limitation"]
    assert any("quality metadata unavailable" in gap for gap in body["known_gaps"])
    assert "verified/authoritative" in body["data_quality"]["amount_policy"]


def test_portfolio_heatmap_does_not_total_program_amount_hints() -> None:
    conn = _heatmap_conn()
    conn.executescript(
        """
        CREATE TABLE am_amount_condition (
            program_id TEXT,
            amount_max_yen INTEGER,
            quality_tier TEXT,
            template_default INTEGER,
            is_authoritative INTEGER
        );
        INSERT INTO am_amount_condition
            (program_id, amount_max_yen, quality_tier, template_default, is_authoritative)
        VALUES ('P1', 123456, 'verified', 0, 1);
        """
    )

    body = _build_envelope(conn, PortfolioHeatmapRequest(program_ids=["P1", "P3"]))

    rows = {row["program_id"]: row for row in body["heatmap_rows"]}
    assert rows["P3"]["amount"]["max_yen"] == 2_500_000
    assert rows["P3"]["amount"]["verified_max_yen"] is None
    assert rows["P3"]["amount"]["counts_toward_total"] is False
    assert rows["P3"]["amount"]["quality"]["source"] == "program_amount_hint"
    assert body["summary"]["total_amount_max_yen"] == 123456
    assert body["summary"]["total_verified_amount_max_yen"] == 123456
    assert "template_default" in body["data_quality"]["amount_total_limitation"]


def test_portfolio_heatmap_exposes_compatibility_advisory_quality() -> None:
    conn = _heatmap_conn()
    conn.executescript(
        """
        CREATE TABLE am_compat_matrix (
            program_a_id TEXT,
            program_b_id TEXT,
            compat_status TEXT,
            rationale_short TEXT,
            source_url TEXT,
            confidence REAL,
            inferred_only INTEGER
        );
        INSERT INTO am_compat_matrix
            (program_a_id, program_b_id, compat_status, rationale_short,
             source_url, confidence, inferred_only)
        VALUES ('P1', 'P2', 'case_by_case', 'heuristic row', NULL, 0.4, 1);
        """
    )

    body = _build_envelope(conn, PortfolioHeatmapRequest(program_ids=["P1", "P2"]))

    pair = body["compatibility_pairs"][0]
    assert pair["status"] == "case_by_case"
    assert pair["advisory_quality"] == "heuristic_advisory"
    assert pair["inferred_only"] is True
    assert pair["source_url_present"] is False
    assert "advisory matrix signal" in pair["caveat"]
    row = body["heatmap_rows"][0]
    assert row["compatibility"]["status"] == "requires_review"
    assert row["compatibility"]["advisory_quality"] == "mixed_advisory"
    assert "primary sources" in row["compatibility"]["caveat"]
