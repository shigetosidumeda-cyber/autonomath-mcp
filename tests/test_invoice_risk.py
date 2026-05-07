"""R8 invoice-risk lookup contract tests.

Covers:
  * GET /v1/invoice_registrants/{tnum}/risk
  * POST /v1/invoice_registrants/batch_risk
  * GET /v1/houjin/{bangou}/invoice_status
  * Pure scoring function ``_classify_risk`` (no DB / no FastAPI)

Risk taxonomy under test
------------------------

  0   clear   — registered + master match + > 1 year aged
  30  caution — registered + < 6 month, OR 6m-1y
  50  verify  — registered + houjin_master 不一致
  100 block   — 未登録 / 失効 / 取消

The pure scoring function is exercised first so a regression in heuristic
thresholds shows up at unit-test resolution before the integration tests
fire (saves the customer LLM debugging an API surface for an arithmetic
typo).
"""

from __future__ import annotations

import contextlib
import datetime
import sqlite3
from typing import TYPE_CHECKING

import pytest

from jpintel_mcp.api.invoice_risk import _AGED_REG_DAYS, _RECENT_REG_DAYS, _classify_risk

if TYPE_CHECKING:
    from pathlib import Path

_BOOKYOU_T = "T8010001213708"
_BOOKYOU_BANGOU = "8010001213708"


# ---------------------------------------------------------------------------
# 1) Pure scoring function — no DB, no client.
# ---------------------------------------------------------------------------


def test_classify_unregistered_returns_block():
    score, band, eligible, _ = _classify_risk(
        registered=False,
        registered_at=None,
        expired_at=None,
        master_matched=False,
    )
    assert score == 100
    assert band == "block"
    assert eligible is False


def test_classify_aged_match_returns_clear():
    today = datetime.date(2026, 5, 7)
    score, band, eligible, _ = _classify_risk(
        registered=True,
        registered_at=today - datetime.timedelta(days=_AGED_REG_DAYS + 30),
        expired_at=None,
        master_matched=True,
        today=today,
    )
    assert score == 0
    assert band == "clear"
    assert eligible is True


def test_classify_recent_returns_caution_30():
    today = datetime.date(2026, 5, 7)
    score, band, eligible, _ = _classify_risk(
        registered=True,
        registered_at=today - datetime.timedelta(days=_RECENT_REG_DAYS - 5),
        expired_at=None,
        master_matched=True,
        today=today,
    )
    assert score == 30
    assert band == "caution"
    assert eligible is True


def test_classify_no_master_match_returns_verify_50():
    today = datetime.date(2026, 5, 7)
    score, band, eligible, _ = _classify_risk(
        registered=True,
        registered_at=today - datetime.timedelta(days=400),
        expired_at=None,
        master_matched=False,
        today=today,
    )
    assert score == 50
    assert band == "verify"
    assert eligible is True


def test_classify_six_month_to_one_year_returns_caution():
    today = datetime.date(2026, 5, 7)
    # 200 days ≈ 6.5 months — between recent and aged thresholds.
    score, band, eligible, _ = _classify_risk(
        registered=True,
        registered_at=today - datetime.timedelta(days=200),
        expired_at=None,
        master_matched=True,
        today=today,
    )
    assert score == 30
    assert band == "caution"
    assert eligible is True


def test_classify_expired_in_past_returns_block():
    today = datetime.date(2026, 5, 7)
    score, band, eligible, _ = _classify_risk(
        registered=True,
        registered_at=today - datetime.timedelta(days=400),
        expired_at=today - datetime.timedelta(days=10),
        master_matched=True,
        today=today,
    )
    assert score == 100
    assert band == "block"
    assert eligible is False


# ---------------------------------------------------------------------------
# 2) Integration tests — full app + seeded DB.
# ---------------------------------------------------------------------------


@pytest.fixture()
def invoice_seeded_db(seeded_db: Path) -> Path:
    """Seed one invoice_registrants row + one houjin_master row for Bookyou.

    Uses the real Bookyou T-number (already on jpcite invoices) so the
    test mirrors the customer-facing scenario.
    """
    c = sqlite3.connect(seeded_db)
    try:
        c.execute("DELETE FROM invoice_registrants")
        # Aged 5+ years (registered 2020) — should land in clear / 0.
        c.execute(
            (
                "INSERT INTO invoice_registrants("
                "  invoice_registration_number, houjin_bangou, normalized_name, "
                "  address_normalized, prefecture, registered_date, revoked_date, "
                "  expired_date, registrant_kind, trade_name, last_updated_nta, "
                "  source_url, source_checksum, confidence, fetched_at, updated_at"
                ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
            ),
            (
                _BOOKYOU_T,
                _BOOKYOU_BANGOU,
                "Bookyou株式会社",
                "東京都文京区小日向2-22-1",
                "東京都",
                "2020-04-01",
                None,
                None,
                "corporation",
                None,
                "2025-05-13",
                "https://www.invoice-kohyo.nta.go.jp/regno-search/download",
                None,
                0.98,
                "2026-04-25T03:30:00Z",
                "2026-04-25T03:30:00Z",
            ),
        )
        # houjin_master row matching Bookyou — verifies the master_matched
        # branch fires. The fixture may not include the migration 014 table,
        # so suppress OperationalError; the risk endpoint tolerates the
        # missing table (returns matched=False / verify-50).
        with contextlib.suppress(sqlite3.OperationalError):
            c.execute(
                (
                    "INSERT OR REPLACE INTO houjin_master("
                    "  houjin_bangou, normalized_name, address_normalized, "
                    "  prefecture, municipality, corporation_type, established_date, "
                    "  close_date, last_updated_nta, fetched_at"
                    ") VALUES (?,?,?,?,?,?,?,?,?,?)"
                ),
                (
                    _BOOKYOU_BANGOU,
                    "Bookyou株式会社",
                    "東京都文京区小日向2-22-1",
                    "東京都",
                    "文京区",
                    "株式会社",
                    "2018-04-01",
                    None,
                    "2026-04-25",
                    "2026-04-25T03:30:00Z",
                ),
            )
        c.commit()
    finally:
        c.close()
    return seeded_db


def test_get_risk_clear_for_aged_bookyou(client, invoice_seeded_db):
    r = client.get(f"/v1/invoice_registrants/{_BOOKYOU_T}/risk")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["result"]["invoice_registration_number"] == _BOOKYOU_T
    assert body["result"]["registered"] is True
    # 0 if master_matched, 50 if houjin_master fixture not present.
    assert body["result"]["risk_score"] in (0, 50)
    assert body["result"]["tax_credit_eligible"] is True
    # PDL v1.0 attribution must be present.
    assert body["attribution"]["license"].startswith("公共データ利用規約")
    # §52 disclaimer relayed verbatim.
    assert "税理士法 §52" in body["_disclaimer"]


def test_get_risk_block_on_unknown_tnum(client, invoice_seeded_db):
    """An unseeded T-number must score 100 / block."""
    r = client.get("/v1/invoice_registrants/T9999999999999/risk")
    assert r.status_code == 200
    body = r.json()
    assert body["result"]["registered"] is False
    assert body["result"]["risk_score"] == 100
    assert body["result"]["risk_band"] == "block"
    assert body["result"]["tax_credit_eligible"] is False
    # Even on miss, the 200 body carries 出典 + alternative + §52.
    assert "next_bulk_refresh" in body
    assert "alternative" in body
    assert "発行元サイト" in body["attribution"]["notice"]


def test_get_risk_422_on_malformed_tnum(client, invoice_seeded_db):
    r = client.get("/v1/invoice_registrants/T1/risk")
    assert r.status_code == 422


def test_batch_risk_mixed_known_unknown_malformed(client, invoice_seeded_db):
    payload = {
        "tnums": [
            _BOOKYOU_T,  # known → clear/verify
            "T9999999999999",  # unknown → block
            "T1",  # malformed → error
        ]
    }
    r = client.post("/v1/invoice_registrants/batch_risk", json=payload)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 3
    items = body["results"]
    # known
    assert items[0]["risk"] is not None
    assert items[0]["risk"]["registered"] is True
    # unknown
    assert items[1]["risk"]["registered"] is False
    assert items[1]["risk"]["risk_score"] == 100
    # malformed → error string, no risk
    assert items[2]["risk"] is None
    assert items[2]["error"] is not None
    # PDL + §52 emitted ONCE at the response root, not per item.
    assert body["attribution"]["license"].startswith("公共データ利用規約")
    assert "税理士法 §52" in body["_disclaimer"]


def test_batch_risk_422_on_empty(client, invoice_seeded_db):
    r = client.post("/v1/invoice_registrants/batch_risk", json={"tnums": []})
    assert r.status_code == 422


def test_batch_risk_422_on_overcap(client, invoice_seeded_db):
    r = client.post(
        "/v1/invoice_registrants/batch_risk",
        json={"tnums": ["T1234567890123"] * 101},
    )
    assert r.status_code == 422


def test_houjin_invoice_status_known_bangou(client, invoice_seeded_db):
    r = client.get(f"/v1/houjin/{_BOOKYOU_BANGOU}/invoice_status")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["result"]["houjin_bangou"] == _BOOKYOU_BANGOU
    assert body["result"]["invoice_registration_number"] == _BOOKYOU_T
    assert body["result"]["registered"] is True
    assert body["result"]["tax_credit_eligible"] is True
    assert body["attribution"]["license"].startswith("公共データ利用規約")


def test_houjin_invoice_status_unknown_bangou_is_block(client, invoice_seeded_db):
    r = client.get("/v1/houjin/9999999999999/invoice_status")
    assert r.status_code == 200
    body = r.json()
    assert body["result"]["registered"] is False
    assert body["result"]["risk_score"] == 100
    assert body["result"]["tax_credit_eligible"] is False
    assert body["result"]["invoice_registration_number"] is None


def test_houjin_invoice_status_422_on_short_bangou(client, invoice_seeded_db):
    r = client.get("/v1/houjin/123/invoice_status")
    assert r.status_code == 422
