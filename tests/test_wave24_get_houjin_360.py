"""Smoke tests for `_get_houjin_360_snapshot_history_impl` (Wave24 #102).

W5-5 NO-GO blocker #1: the impl previously SELECTed `snapshot_json`,
which does not exist on `am_houjin_360_snapshot` (real col per migration
wave24_131 is `payload_json`). Every call returned
``OperationalError: no such column: snapshot_json`` →
``db_unavailable`` envelope.

These tests pin the schema contract so the regression cannot recur.

  1. Missing `houjin_bangou`         -> `missing_required_arg` envelope.
  2. Empty table                     -> empty envelope, NO `db_unavailable`.
  3. Real rows                       -> N rows, latest first, JSON snapshot
                                        decoded, delta_from_prev populated.
"""

from __future__ import annotations

import json
import sqlite3
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

# ----- helpers --------------------------------------------------------------


def _create_snapshot_schema(conn: sqlite3.Connection) -> None:
    """Mirror migration wave24_131 — column = `payload_json`, NOT `snapshot_json`."""
    conn.executescript(
        """
        CREATE TABLE am_houjin_360_snapshot (
            snapshot_id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            houjin_bangou                TEXT NOT NULL,
            snapshot_month               TEXT NOT NULL,
            adoption_count               INTEGER,
            adoption_total_man_yen       REAL,
            enforcement_count            INTEGER,
            enforcement_amount_yen       INTEGER,
            invoice_registered           INTEGER,
            compliance_score             REAL,
            risk_score                   REAL,
            subsidy_eligibility_count    INTEGER,
            tax_credit_potential_man_yen REAL,
            payload_json                 TEXT,
            computed_at                  TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE (houjin_bangou, snapshot_month)
        );
        """
    )


def _seed_three_months(conn: sqlite3.Connection, hb: str = "4010001234567") -> None:
    rows = [
        (
            hb,
            "2026-01",
            json.dumps({"adoption_count": 1, "risk_score": 0.10}),
            "2026-02-01T00:00:00Z",
        ),
        (
            hb,
            "2026-02",
            json.dumps({"adoption_count": 3, "risk_score": 0.15}),
            "2026-03-01T00:00:00Z",
        ),
        (
            hb,
            "2026-03",
            json.dumps({"adoption_count": 5, "risk_score": 0.20}),
            "2026-04-01T00:00:00Z",
        ),
    ]
    conn.executemany(
        """
        INSERT INTO am_houjin_360_snapshot
          (houjin_bangou, snapshot_month, payload_json, computed_at)
        VALUES (?, ?, ?, ?)
        """,
        rows,
    )
    conn.commit()


@pytest.fixture()
def snapshot_empty_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """autonomath.db with the snapshot schema but no rows."""
    db_path = tmp_path / "autonomath.db"
    conn = sqlite3.connect(db_path)
    try:
        _create_snapshot_schema(conn)
    finally:
        conn.close()
    monkeypatch.setenv("AUTONOMATH_DB_PATH", str(db_path))
    monkeypatch.setenv("JPCITE_AUTONOMATH_DB_PATH", str(db_path))
    return db_path


@pytest.fixture()
def snapshot_seeded_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """autonomath.db preloaded with 3 monthly snapshots for one houjin_bangou."""
    db_path = tmp_path / "autonomath.db"
    conn = sqlite3.connect(db_path)
    try:
        _create_snapshot_schema(conn)
        _seed_three_months(conn)
    finally:
        conn.close()
    monkeypatch.setenv("AUTONOMATH_DB_PATH", str(db_path))
    monkeypatch.setenv("JPCITE_AUTONOMATH_DB_PATH", str(db_path))
    return db_path


def _impl():
    """Late-bind the impl AFTER AUTONOMATH_DB_PATH is set so the per-thread
    autonomath connection rebinds to the temp DB.
    """
    from jpintel_mcp.mcp.autonomath_tools.wave24_tools_first_half import (
        _get_houjin_360_snapshot_history_impl,
    )

    return _get_houjin_360_snapshot_history_impl


# ----- tests ----------------------------------------------------------------


def test_missing_houjin_bangou_returns_validation_error(
    snapshot_empty_db: Path,
) -> None:
    out = _impl()(houjin_bangou="", months=12)
    assert out["error"]["code"] == "missing_required_arg"
    assert out["error"]["field"] == "houjin_bangou"


def test_empty_table_returns_empty_envelope_not_db_unavailable(
    snapshot_empty_db: Path,
) -> None:
    """Regression guard for W5-5 — must NOT emit
    `db_unavailable: no such column: snapshot_json`.
    """
    out = _impl()(houjin_bangou="4010001234567", months=12)
    assert "error" not in out, f"unexpected error envelope: {out}"
    assert out["total"] == 0
    assert out["results"] == []
    assert out["houjin_bangou"] == "4010001234567"
    assert out["months"] == 12


def test_seeded_rows_return_latest_first_with_decoded_payload(
    snapshot_seeded_db: Path,
) -> None:
    out = _impl()(houjin_bangou="4010001234567", months=12)
    assert "error" not in out, f"unexpected error envelope: {out}"
    assert out["total"] == 3
    assert len(out["results"]) == 3
    # Newest first per impl contract (decoded.reverse()).
    months = [r["snapshot_month"] for r in out["results"]]
    assert months == ["2026-03", "2026-02", "2026-01"]
    # payload_json must be JSON-decoded into the `snapshot` field.
    latest = out["results"][0]
    assert latest["snapshot"]["adoption_count"] == 5
    assert latest["snapshot"]["risk_score"] == 0.20
    # Each row carries `delta_from_prev` (computed in Python).
    for r in out["results"]:
        assert "delta_from_prev" in r
        assert "computed_at" in r
