"""Tests for the Wave 49 G4/G5 first-transaction observation watchdog.

Strategy
--------

* Build a tiny SQLite fixture with the two ledger tables
  (`am_x402_payment_log` + `am_credit_transaction_log`).
* Drive 0-row → 1-row transitions and assert the detection event
  file flips state exactly once per rail.
* Idempotent gate: re-running with the same fixture must NOT
  append a second history record on the sealed rail.
* Slack notification is monkey-patched away so the suite stays
  offline.

The script under test never writes to the ledger tables — these
tests only assert observation behaviour, never simulate a real
on-chain or Stripe transaction.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

import pytest

from scripts.cron import detect_first_g4_g5_txn as det


def _create_schema(db: Path) -> None:
    conn = sqlite3.connect(db)
    try:
        conn.executescript(
            """
            CREATE TABLE am_x402_payment_log (
                payment_id INTEGER PRIMARY KEY AUTOINCREMENT,
                http_status_402_id TEXT NOT NULL,
                endpoint_path TEXT NOT NULL,
                amount_usdc REAL NOT NULL,
                payer_address TEXT NOT NULL,
                txn_hash TEXT NOT NULL UNIQUE,
                occurred_at TEXT NOT NULL DEFAULT (
                    strftime('%Y-%m-%dT%H:%M:%fZ','now')
                )
            );

            CREATE TABLE am_credit_wallet (
                wallet_id INTEGER PRIMARY KEY AUTOINCREMENT,
                owner_token_hash TEXT NOT NULL
            );

            CREATE TABLE am_credit_transaction_log (
                txn_id INTEGER PRIMARY KEY AUTOINCREMENT,
                wallet_id INTEGER NOT NULL,
                amount_yen INTEGER NOT NULL,
                txn_type TEXT NOT NULL,
                occurred_at TEXT NOT NULL DEFAULT (
                    strftime('%Y-%m-%dT%H:%M:%fZ','now')
                ),
                note TEXT
            );
            """
        )
        conn.commit()
    finally:
        conn.close()


def _insert_x402_row(db: Path, *, endpoint: str = "/v1/case-studies/search") -> None:
    conn = sqlite3.connect(db)
    try:
        # Use distinct txn_hash per call so UNIQUE is satisfied.
        existing = conn.execute("SELECT COUNT(*) FROM am_x402_payment_log").fetchone()[0]
        suffix = f"{existing + 1:064x}"
        conn.execute(
            "INSERT INTO am_x402_payment_log "
            "(http_status_402_id, endpoint_path, amount_usdc, payer_address, txn_hash, occurred_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                "nonce-abcdef-" + suffix[:6],
                endpoint,
                0.002,
                "0x" + ("a" * 40),
                "0x" + suffix[:64],
                "2026-05-16T12:33:00.000Z",
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _insert_wallet_topup(db: Path, *, amount: int = 5000) -> None:
    conn = sqlite3.connect(db)
    try:
        cur = conn.execute(
            "INSERT INTO am_credit_wallet (owner_token_hash) VALUES (?)",
            ("a" * 64,),
        )
        wid = cur.lastrowid
        conn.execute(
            "INSERT INTO am_credit_transaction_log "
            "(wallet_id, amount_yen, txn_type, occurred_at, note) "
            "VALUES (?, ?, 'topup', ?, ?)",
            (wid, amount, "2026-05-16T12:40:00.000Z", "first topup"),
        )
        conn.commit()
    finally:
        conn.close()


def _make_args(db: Path, output: Path, *, dry_run: bool = False) -> argparse.Namespace:
    return argparse.Namespace(
        check=not dry_run,
        dry_run=dry_run,
        db=db,
        output=output,
        verbose=False,
    )


# ---------------------------------------------------------------------------
# Schema-absent / zero-row baseline
# ---------------------------------------------------------------------------


def test_zero_rows_writes_empty_state(tmp_path, monkeypatch):
    db = tmp_path / "autonomath.db"
    _create_schema(db)
    out = tmp_path / "first_txn_detected.json"
    monkeypatch.setattr(det, "post_slack_notification", lambda _t: False)

    rc = det.run(_make_args(db, out))
    assert rc == 0
    assert out.exists()
    state = json.loads(out.read_text(encoding="utf-8"))
    assert state["schema_version"] == det.SCHEMA_VERSION
    assert state["first_detected_at_utc"] is None
    assert state["rails"][det.RAIL_G4]["first_row_count"] == 0
    assert state["rails"][det.RAIL_G5]["first_row_count"] == 0
    assert state["history"] == []


def test_missing_db_dry_run_emits_zero_state(tmp_path, capsys):
    db = tmp_path / "ghost.db"
    out = tmp_path / "first_txn_detected.json"
    rc = det.run(_make_args(db, out, dry_run=True))
    assert rc == 0
    # No state file is written in dry-run.
    assert not out.exists()
    captured = capsys.readouterr().out
    report = json.loads(captured)
    assert report["dry_run"] is True
    assert report["g4_probe"]["row_count"] == 0
    assert report["g5_probe"]["row_count"] == 0
    assert report["transitions"] == []


def test_missing_db_check_returns_nonzero(tmp_path):
    db = tmp_path / "ghost.db"
    out = tmp_path / "first_txn_detected.json"
    rc = det.run(_make_args(db, out))
    assert rc == 2
    assert not out.exists()


# ---------------------------------------------------------------------------
# 0 → 1 transition (the load-bearing behaviour)
# ---------------------------------------------------------------------------


def test_g4_zero_to_one_fires_transition(tmp_path, monkeypatch):
    db = tmp_path / "autonomath.db"
    _create_schema(db)
    out = tmp_path / "first_txn_detected.json"
    calls: list[list[dict]] = []
    monkeypatch.setattr(det, "post_slack_notification", lambda t: (calls.append(t), True)[1])

    # First run: zero rows.
    det.run(_make_args(db, out))
    state0 = json.loads(out.read_text(encoding="utf-8"))
    assert state0["rails"][det.RAIL_G4]["first_row_count"] == 0
    assert state0["history"] == []
    assert calls == []  # no transition → no Slack

    # Insert one real (but synthetic for the fixture) x402 row.
    _insert_x402_row(db)

    # Second run: should fire the transition for G4 only.
    det.run(_make_args(db, out))
    state1 = json.loads(out.read_text(encoding="utf-8"))
    assert state1["rails"][det.RAIL_G4]["first_row_count"] == 1
    assert state1["rails"][det.RAIL_G4]["first_detected_at_utc"] is not None
    assert state1["rails"][det.RAIL_G4]["earliest_row_occurred_at"] == "2026-05-16T12:33:00.000Z"
    assert state1["rails"][det.RAIL_G4]["endpoint_path_sample"] == "/v1/case-studies/search"
    # G5 unchanged.
    assert state1["rails"][det.RAIL_G5]["first_row_count"] == 0
    # Exactly one history row appended.
    assert len(state1["history"]) == 1
    assert state1["history"][0]["rail"] == det.RAIL_G4
    assert state1["first_detected_at_utc"] is not None
    # Slack called once.
    assert len(calls) == 1
    assert calls[0][0]["rail"] == det.RAIL_G4


def test_g5_zero_to_one_fires_transition(tmp_path, monkeypatch):
    db = tmp_path / "autonomath.db"
    _create_schema(db)
    out = tmp_path / "first_txn_detected.json"
    monkeypatch.setattr(det, "post_slack_notification", lambda _t: False)

    det.run(_make_args(db, out))
    _insert_wallet_topup(db)
    det.run(_make_args(db, out))

    state = json.loads(out.read_text(encoding="utf-8"))
    assert state["rails"][det.RAIL_G5]["first_row_count"] == 1
    assert state["rails"][det.RAIL_G5]["earliest_row_occurred_at"] == "2026-05-16T12:40:00.000Z"
    assert state["rails"][det.RAIL_G4]["first_row_count"] == 0
    assert len(state["history"]) == 1
    assert state["history"][0]["rail"] == det.RAIL_G5


# ---------------------------------------------------------------------------
# Idempotency (load-bearing per spec)
# ---------------------------------------------------------------------------


def test_idempotent_second_run_does_not_double_fire(tmp_path, monkeypatch):
    """Two invocations after the transition fires must NOT add history."""
    db = tmp_path / "autonomath.db"
    _create_schema(db)
    out = tmp_path / "first_txn_detected.json"
    slack_calls: list[list[dict]] = []
    monkeypatch.setattr(
        det,
        "post_slack_notification",
        lambda t: (slack_calls.append(t), True)[1],
    )

    _insert_x402_row(db)
    det.run(_make_args(db, out))  # first transition
    snap1 = json.loads(out.read_text(encoding="utf-8"))

    # Mutate the underlying ledger further — still must not double-fire.
    _insert_x402_row(db, endpoint="/v1/programs/prescreen")
    det.run(_make_args(db, out))
    snap2 = json.loads(out.read_text(encoding="utf-8"))

    # G4 first_row_count + first_detected_at_utc are sealed at the
    # original (1, t0) values.
    assert (
        snap2["rails"][det.RAIL_G4]["first_row_count"]
        == snap1["rails"][det.RAIL_G4]["first_row_count"]
    )
    assert (
        snap2["rails"][det.RAIL_G4]["first_detected_at_utc"]
        == snap1["rails"][det.RAIL_G4]["first_detected_at_utc"]
    )
    assert snap2["rails"][det.RAIL_G4]["endpoint_path_sample"] == "/v1/case-studies/search"
    # History list is unchanged.
    assert len(snap2["history"]) == 1
    # Slack was called exactly once across both runs.
    assert len(slack_calls) == 1


def test_both_rails_independent(tmp_path, monkeypatch):
    """G4 firing first must not seal G5 — G5 can still fire on its own row."""
    db = tmp_path / "autonomath.db"
    _create_schema(db)
    out = tmp_path / "first_txn_detected.json"
    monkeypatch.setattr(det, "post_slack_notification", lambda _t: False)

    _insert_x402_row(db)
    det.run(_make_args(db, out))
    _insert_wallet_topup(db)
    det.run(_make_args(db, out))

    state = json.loads(out.read_text(encoding="utf-8"))
    assert state["rails"][det.RAIL_G4]["first_row_count"] == 1
    assert state["rails"][det.RAIL_G5]["first_row_count"] == 1
    rails_in_history = [h["rail"] for h in state["history"]]
    assert det.RAIL_G4 in rails_in_history
    assert det.RAIL_G5 in rails_in_history
    assert len(state["history"]) == 2


# ---------------------------------------------------------------------------
# Dry-run hygiene: never writes the state file
# ---------------------------------------------------------------------------


def test_dry_run_does_not_write_state(tmp_path, capsys, monkeypatch):
    db = tmp_path / "autonomath.db"
    _create_schema(db)
    _insert_x402_row(db)
    out = tmp_path / "first_txn_detected.json"
    monkeypatch.setattr(
        det,
        "post_slack_notification",
        lambda _t: pytest.fail("Slack must not be called during dry-run"),
    )

    rc = det.run(_make_args(db, out, dry_run=True))
    assert rc == 0
    assert not out.exists()  # state file untouched
    report = json.loads(capsys.readouterr().out)
    assert report["dry_run"] is True
    assert report["g4_probe"]["row_count"] == 1
    assert len(report["transitions"]) == 1


# ---------------------------------------------------------------------------
# compute_transitions pure function (no DB)
# ---------------------------------------------------------------------------


def test_compute_transitions_pure():
    prev = det._empty_state()
    g4 = {
        "table": det.TABLE_G4,
        "row_count": 3,
        "earliest_row_occurred_at": "2026-05-16T12:00:00.000Z",
        "endpoint_path_sample": "/v1/search/semantic",
        "schema_present": True,
    }
    g5 = {
        "table": det.TABLE_G5,
        "row_count": 0,
        "earliest_row_occurred_at": None,
        "txn_type_filter": det.G5_TXN_TYPE_FILTER,
        "schema_present": True,
    }
    new_state, transitions = det.compute_transitions(prev, g4, g5, "2026-05-16T12:34:56.789Z")
    assert len(transitions) == 1
    assert transitions[0]["rail"] == det.RAIL_G4
    assert transitions[0]["row_count"] == 3
    assert new_state["first_detected_at_utc"] == "2026-05-16T12:34:56.789Z"

    # Re-running with same prev=new_state must produce no transitions.
    _, transitions2 = det.compute_transitions(new_state, g4, g5, "2026-05-16T13:00:00.000Z")
    assert transitions2 == []
