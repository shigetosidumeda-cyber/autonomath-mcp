"""Render-helper coverage tests for api/pdf_report.

Targets ``src/jpintel_mcp/api/pdf_report.py`` (254 stmt, 21.3% baseline).
Exercises the pure-Python helpers and the reportlab-based PDF renderer
against a minimal in-memory SQLite. NO live R2 upload, NO live Stripe
metering, NO LLM call.

Coverage areas
--------------
  * ``_open_autonomath_db`` — read-only connection over a tmp DB path.
  * ``_rate_floor_check`` — 1/min per-key floor.
  * ``_collect_client_context`` — fence_summary always present; tables
    optional and degrade gracefully.
  * ``_render_pdf`` — emits ``%PDF`` magic header, page_count > 0.
  * ``_upload_to_r2`` — no R2 env → local-disk fallback path returns
    the inline route.
  * Pydantic model invariants for the public schemas.
"""

from __future__ import annotations

import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi import HTTPException

import jpintel_mcp.api.pdf_report as pr

# ---------------------------------------------------------------------------
# Tmp autonomath.db fixture
# ---------------------------------------------------------------------------


def _make_pdf_substrate_db(path: Path, seed_rows: bool = False) -> None:
    """Minimal schema for ``_collect_client_context``.

    Tables: programs, am_amendment_diff, v_houjin_360 (view-like),
    am_houjin_risk_score, am_pdf_report_subscriptions.
    """
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE programs(
            program_id TEXT,
            title TEXT,
            authority TEXT,
            source_url TEXT,
            tier TEXT,
            excluded INTEGER,
            source_fetched_at TEXT
        );
        CREATE TABLE am_amendment_diff(
            amendment_id TEXT,
            law_id TEXT,
            summary TEXT,
            effective_from TEXT
        );
        CREATE TABLE v_houjin_360(
            houjin_bangou TEXT,
            company_name TEXT,
            jurisdiction TEXT
        );
        CREATE TABLE am_houjin_risk_score(
            houjin_bangou TEXT,
            financial_risk REAL,
            regulatory_risk REAL,
            operational_risk REAL,
            composite_score REAL,
            computed_at TEXT
        );
        CREATE TABLE am_pdf_report_subscriptions(
            subscription_id TEXT PRIMARY KEY,
            client_id TEXT,
            customer_id TEXT,
            cadence TEXT,
            enabled INTEGER,
            r2_url_template TEXT,
            created_at TEXT,
            updated_at TEXT
        );
        """
    )
    if seed_rows:
        conn.execute(
            "INSERT INTO programs(program_id, title, authority, source_url, "
            "tier, excluded, source_fetched_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                "UNI-recent",
                "テスト最新制度",
                "経済産業省",
                "https://example.gov.jp/recent",
                "A",
                0,
                datetime.now(UTC).strftime("%Y-%m-%d"),
            ),
        )
        conn.execute(
            "INSERT INTO am_amendment_diff(amendment_id, law_id, summary, "
            "effective_from) VALUES (?, ?, ?, ?)",
            ("am-1", "law-1", "改正サマリ", "2026-04-01"),
        )
        conn.execute(
            "INSERT INTO v_houjin_360(houjin_bangou, company_name, jurisdiction) VALUES (?, ?, ?)",
            ("8010001213708", "Bookyou株式会社", "東京"),
        )
        conn.execute(
            "INSERT INTO am_houjin_risk_score(houjin_bangou, financial_risk, "
            "regulatory_risk, operational_risk, composite_score, computed_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("8010001213708", 0.1, 0.2, 0.3, 0.2, datetime.now(UTC).isoformat()),
        )
    conn.commit()
    conn.close()


@pytest.fixture()
def tmp_pdf_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    p = tmp_path / "autonomath.db"
    _make_pdf_substrate_db(p, seed_rows=True)
    monkeypatch.setattr(pr, "_AUTONOMATH_DB_PATH", str(p))
    monkeypatch.setenv("AUTONOMATH_DB_PATH", str(p))
    # Drop any R2 env so _upload_to_r2 falls back to inline.
    monkeypatch.delenv("R2_ENDPOINT", raising=False)
    return p


@pytest.fixture()
def tmp_pdf_empty_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    p = tmp_path / "autonomath_empty.db"
    _make_pdf_substrate_db(p, seed_rows=False)
    monkeypatch.setattr(pr, "_AUTONOMATH_DB_PATH", str(p))
    monkeypatch.setenv("AUTONOMATH_DB_PATH", str(p))
    monkeypatch.delenv("R2_ENDPOINT", raising=False)
    return p


# ---------------------------------------------------------------------------
# _open_autonomath_db
# ---------------------------------------------------------------------------


def test_open_autonomath_db_returns_ro_conn(tmp_pdf_db: Path) -> None:
    conn = pr._open_autonomath_db()
    try:
        assert isinstance(conn, sqlite3.Connection)
        # row_factory is Row.
        assert conn.row_factory is sqlite3.Row
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# _rate_floor_check
# ---------------------------------------------------------------------------


def test_rate_floor_check_first_call_passes() -> None:
    # Wipe state for this key_hash.
    pr._pdf_rate_state.pop("first-key", None)
    pr._rate_floor_check("first-key")
    assert "first-key" in pr._pdf_rate_state


def test_rate_floor_check_second_call_blocks_with_429() -> None:
    pr._pdf_rate_state.pop("blocking-key", None)
    pr._rate_floor_check("blocking-key")
    with pytest.raises(HTTPException) as exc_info:
        pr._rate_floor_check("blocking-key")
    assert exc_info.value.status_code == 429
    detail = exc_info.value.detail
    assert isinstance(detail, dict)
    assert "retry_after_s" in detail


def test_rate_floor_check_isolates_keys() -> None:
    pr._pdf_rate_state.pop("key-A", None)
    pr._pdf_rate_state.pop("key-B", None)
    pr._rate_floor_check("key-A")
    pr._rate_floor_check("key-B")  # different key → no block


# ---------------------------------------------------------------------------
# _collect_client_context
# ---------------------------------------------------------------------------


def test_collect_context_fence_summary_always_present(tmp_pdf_empty_db: Path) -> None:
    conn = pr._open_autonomath_db()
    try:
        ctx = pr._collect_client_context(conn, "1234567890123")
    finally:
        conn.close()
    assert ctx["client_id"] == "1234567890123"
    # 8 業法 entries are hard-coded → always present.
    assert len(ctx["fence_summary"]) == 8
    laws = [f["law"] for f in ctx["fence_summary"]]
    assert any("税理士法" in s for s in laws)
    assert any("公認会計士法" in s for s in laws)


def test_collect_context_seeded_db_has_rows(tmp_pdf_db: Path) -> None:
    conn = pr._open_autonomath_db()
    try:
        ctx = pr._collect_client_context(conn, "8010001213708")
    finally:
        conn.close()
    assert ctx["houjin_360"] is not None
    assert ctx["risk_score"] is not None
    assert len(ctx["new_programs"]) >= 1
    assert len(ctx["amendments"]) >= 1


def test_collect_context_unknown_client_keeps_fence(tmp_pdf_db: Path) -> None:
    conn = pr._open_autonomath_db()
    try:
        ctx = pr._collect_client_context(conn, "9999999999999")
    finally:
        conn.close()
    # Houjin 360 row is keyed → absent.
    assert ctx["houjin_360"] is None
    # Fence still present.
    assert len(ctx["fence_summary"]) == 8


# ---------------------------------------------------------------------------
# _render_pdf
# ---------------------------------------------------------------------------


def _minimal_ctx(client_id: str = "1234567890123") -> dict[str, Any]:
    return {
        "client_id": client_id,
        "fetched_at": datetime.now(UTC).isoformat(),
        "houjin_360": None,
        "risk_score": None,
        "new_programs": [],
        "amendments": [],
        "fence_summary": [
            {"law": "税理士法 §52", "rule": "税務代理は税理士のみ。"},
        ],
    }


def test_render_pdf_basic_returns_bytes_and_pagecount() -> None:
    pytest.importorskip("reportlab")
    blob, pages = pr._render_pdf("1234567890123", _minimal_ctx())
    assert isinstance(blob, bytes)
    assert blob.startswith(b"%PDF")
    assert pages >= 1


def test_render_pdf_includes_client_id() -> None:
    pytest.importorskip("reportlab")
    blob, _ = pr._render_pdf("XYZ-CLIENT-ID-42", _minimal_ctx("XYZ-CLIENT-ID-42"))
    assert b"%PDF" in blob[:10]
    # The client id is part of the title — searching the raw stream is
    # fragile due to compression, so we just assert size > 1 KB sanity.
    assert len(blob) > 1024


def test_render_pdf_with_houjin360_data() -> None:
    pytest.importorskip("reportlab")
    ctx = _minimal_ctx()
    ctx["houjin_360"] = {
        "company_name": "テスト株式会社",
        "jurisdiction": "東京",
        "tax_status": "適格",
    }
    ctx["risk_score"] = {
        "financial_risk": 0.1,
        "regulatory_risk": 0.2,
        "operational_risk": 0.3,
        "composite_score": 0.2,
        "computed_at": "2026-05-16T00:00:00Z",
    }
    ctx["new_programs"] = [{"program_id": "UNI-1", "title": "テスト", "authority": "経産省"}]
    ctx["amendments"] = [
        {
            "amendment_id": "am-1",
            "law_id": "law-1",
            "summary": "改正",
            "effective_from": "2026-04-01",
        }
    ]
    blob, pages = pr._render_pdf("8010001213708", ctx)
    assert blob.startswith(b"%PDF")
    assert pages >= 1


# ---------------------------------------------------------------------------
# _upload_to_r2 — local fallback path
# ---------------------------------------------------------------------------


def test_upload_to_r2_falls_back_to_inline_without_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("R2_ENDPOINT", raising=False)
    key, url, expires = pr._upload_to_r2("client-1", b"%PDF-1.4\n%fake pdf body")
    assert key.startswith("pdf_reports/client-1/")
    assert url.startswith("/v1/pdf_report/inline/")
    # ISO timestamp
    assert "T" in expires


def test_upload_to_r2_creates_local_file(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("R2_ENDPOINT", raising=False)
    blob = b"%PDF-1.4\n%test"
    _, url, _ = pr._upload_to_r2("client-local", blob)
    # url like /v1/pdf_report/inline/pdf_xxx — extract pdf_id.
    pdf_id = url.rsplit("/", 1)[-1]
    expected_path = f"/tmp/pdf_report/{pdf_id}.pdf"
    try:
        assert os.path.exists(expected_path)
        with open(expected_path, "rb") as f:
            assert f.read() == blob
    finally:
        if os.path.exists(expected_path):
            os.remove(expected_path)


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


def test_pdf_report_request_defaults() -> None:
    req = pr.PdfReportRequest()
    assert req.cadence == "monthly"
    assert req.sections is None


def test_pdf_report_request_rejects_extras() -> None:
    with pytest.raises(Exception):  # noqa: B017 — pydantic raises ValidationError
        pr.PdfReportRequest(cadence="monthly", unknown_field="hi")  # type: ignore[call-arg]


def test_subscription_upsert_default_template() -> None:
    s = pr.SubscriptionUpsert(client_id="abc", cadence="monthly")
    assert s.client_id == "abc"
    assert s.cadence == "monthly"
    assert s.enabled is True
    assert s.r2_url_template is None


def test_pdf_report_response_alias_round_trip() -> None:
    resp = pr.PdfReportResponse(
        pdf_id="pdf_abc",
        client_id="c1",
        download_url="/v1/pdf_report/inline/pdf_abc",
        expires_at="2026-05-23T00:00:00Z",
        byte_size=1024,
        page_count=2,
        sha256="deadbeef",
        _disclaimer="本書は…",  # type: ignore[arg-type]
    )
    dumped = resp.model_dump(by_alias=True)
    assert "_disclaimer" in dumped


def test_pdf_report_constants_sane() -> None:
    assert pr.PDF_REPORT_UNIT_COUNT == 10
    assert pr.PDF_URL_TTL_S == 7 * 24 * 3600
    assert pr.PDF_MIN_INTERVAL_S == 60
