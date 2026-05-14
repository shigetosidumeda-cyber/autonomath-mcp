"""Integration tests for Dim U Agent Credit Wallet (Wave 47).

Closes the Wave 47 Dim U storage gap: migration 281 adds
``am_credit_wallet`` (pre-paid balance + auto-topup config),
``am_credit_transaction_log`` (append-only topup/charge/refund ledger),
and ``am_credit_spending_alert`` (50/80/100 pct threshold firing log)
per ``feedback_agent_credit_wallet_design.md``. Pairs with
``scripts/etl/process_credit_wallet_alerts.py`` (hourly cron).

Case bundles
------------
  1. Migration 281 applies cleanly on a fresh SQLite db (idempotent re-apply).
  2. Migration 281 rollback drops every artefact created.
  3. CHECK constraints reject malformed rows (token_hash length, negative
     balance, txn_type enum, txn sign rule, threshold_pct enum,
     billing_cycle length).
  4. UNIQUE(owner_token_hash) on wallet, UNIQUE(wallet,threshold,cycle)
     on alert.
  5. ETL alert processor: 3 thresholds (50/80/100) fire in order,
     each only once per cycle, idempotent re-run.
  6. ``v_credit_wallet_topup_due`` view exposes only wallets due for
     auto-topup (balance below threshold + enabled).
  7. Boot manifest registration (jpcite + autonomath mirror).
  8. **LLM-0 verify** — no LLM SDK import in any new file.
"""

from __future__ import annotations

import json
import pathlib
import sqlite3
import subprocess
import sys

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from jpintel_mcp.api.credit_wallet import router as wallet_router
from jpintel_mcp.api.deps import get_db, hash_api_key

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
MIG_281 = REPO_ROOT / "scripts" / "migrations" / "281_credit_wallet.sql"
MIG_281_RB = REPO_ROOT / "scripts" / "migrations" / "281_credit_wallet_rollback.sql"
ETL = REPO_ROOT / "scripts" / "etl" / "process_credit_wallet_alerts.py"
MANIFEST_JPCITE = REPO_ROOT / "scripts" / "migrations" / "jpcite_boot_manifest.txt"
MANIFEST_AM = REPO_ROOT / "scripts" / "migrations" / "autonomath_boot_manifest.txt"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _apply(db_path: pathlib.Path, sql_path: pathlib.Path) -> None:
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(sql_path.read_text(encoding="utf-8"))
    finally:
        conn.close()


def _fresh_db(tmp_path: pathlib.Path) -> pathlib.Path:
    db = tmp_path / "dim_u.db"
    _apply(db, MIG_281)
    return db


def _make_wallet(
    conn: sqlite3.Connection,
    *,
    owner_seed: str = "a",
    balance: int = 10_000,
    monthly_budget: int = 0,
    auto_topup_threshold: int = 0,
    auto_topup_amount: int = 0,
) -> int:
    """Insert a wallet and return wallet_id. owner_seed -> 64-char hex."""
    token_hash = (owner_seed * 64)[:64]
    cur = conn.execute(
        "INSERT INTO am_credit_wallet "
        "(owner_token_hash, balance_yen, monthly_budget_yen, "
        " auto_topup_threshold, auto_topup_amount) "
        "VALUES (?, ?, ?, ?, ?)",
        (token_hash, balance, monthly_budget, auto_topup_threshold, auto_topup_amount),
    )
    conn.commit()
    return int(cur.lastrowid)


def _charge(conn: sqlite3.Connection, wallet_id: int, amount: int, cycle: str) -> None:
    """Record a charge (negative amount) at `<cycle>-15T12:00:00Z`."""
    conn.execute(
        "INSERT INTO am_credit_transaction_log "
        "(wallet_id, amount_yen, txn_type, occurred_at) VALUES (?, ?, 'charge', ?)",
        (wallet_id, -amount, f"{cycle}-15T12:00:00Z"),
    )
    conn.commit()


def _run_etl(db: pathlib.Path, *extra: str) -> dict:
    proc = subprocess.run(
        [sys.executable, str(ETL), "--db", str(db), *extra],
        check=True,
        capture_output=True,
        text=True,
    )
    last_line = proc.stdout.strip().splitlines()[-1]
    return json.loads(last_line)


def _wallet_api_client(
    *,
    seeded_db: pathlib.Path,
    autonomath_db: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> TestClient:
    _apply(autonomath_db, MIG_281)
    monkeypatch.setenv("AUTONOMATH_DB_PATH", str(autonomath_db))
    monkeypatch.setenv("METERING_INTERNAL_TOKEN", "dim-u-internal-token")

    app = FastAPI()
    app.include_router(wallet_router)

    def override_db():
        conn = sqlite3.connect(seeded_db, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    app.dependency_overrides[get_db] = override_db
    return TestClient(app)


def _wallet_row(db: pathlib.Path, key_hash: str) -> sqlite3.Row | None:
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute(
            "SELECT wallet_id, balance_yen, auto_topup_threshold, "
            "       auto_topup_amount, monthly_budget_yen "
            "FROM am_credit_wallet WHERE owner_token_hash = ?",
            (key_hash,),
        ).fetchone()
    finally:
        conn.close()


def _usage_count(db: pathlib.Path, key_hash: str, endpoints: tuple[str, ...]) -> int:
    placeholders = ",".join("?" for _ in endpoints)
    conn = sqlite3.connect(str(db))
    try:
        row = conn.execute(
            f"SELECT COUNT(*) FROM usage_events WHERE key_hash = ? "
            f"AND endpoint IN ({placeholders})",
            (key_hash, *endpoints),
        ).fetchone()
        return int(row[0])
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 0. REST hardening — auth, idempotency, and no control-plane billing
# ---------------------------------------------------------------------------


def test_wallet_topup_requires_api_key_before_balance_mutation(
    tmp_path: pathlib.Path,
    seeded_db: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    am_db = tmp_path / "wallet-api.db"
    c = _wallet_api_client(
        seeded_db=seeded_db,
        autonomath_db=am_db,
        monkeypatch=monkeypatch,
    )

    res = c.post(
        "/v1/wallet/topup",
        json={
            "auto_topup_threshold": 1_000,
            "auto_topup_amount": 5_000,
            "monthly_budget_yen": 10_000,
            "immediate_amount": 5_000,
        },
    )

    assert res.status_code == 401
    conn = sqlite3.connect(str(am_db))
    try:
        (wallets,) = conn.execute("SELECT COUNT(*) FROM am_credit_wallet").fetchone()
        (txns,) = conn.execute("SELECT COUNT(*) FROM am_credit_transaction_log").fetchone()
    finally:
        conn.close()
    assert wallets == 0
    assert txns == 0


def test_wallet_topup_immediate_amount_rejects_paid_key_without_internal_token(
    tmp_path: pathlib.Path,
    seeded_db: pathlib.Path,
    paid_key: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    am_db = tmp_path / "wallet-api.db"
    c = _wallet_api_client(
        seeded_db=seeded_db,
        autonomath_db=am_db,
        monkeypatch=monkeypatch,
    )
    key_hash = hash_api_key(paid_key)

    res = c.post(
        "/v1/wallet/topup",
        headers={"X-API-Key": paid_key, "Idempotency-Key": "dim-u-topup-credit"},
        json={
            "auto_topup_threshold": 1_000,
            "auto_topup_amount": 5_000,
            "monthly_budget_yen": 10_000,
            "immediate_amount": 5_000,
            "note": "initial credit",
        },
    )

    assert res.status_code == 403, res.text
    assert res.json()["detail"] == "wallet_topup_forbidden"
    assert _wallet_row(am_db, key_hash) is None


def test_wallet_topup_immediate_amount_credits_once_for_internal_billing(
    tmp_path: pathlib.Path,
    seeded_db: pathlib.Path,
    paid_key: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    am_db = tmp_path / "wallet-api.db"
    c = _wallet_api_client(
        seeded_db=seeded_db,
        autonomath_db=am_db,
        monkeypatch=monkeypatch,
    )
    key_hash = hash_api_key(paid_key)

    res = c.post(
        "/v1/wallet/topup",
        headers={
            "X-API-Key": paid_key,
            "X-Internal-Token": "dim-u-internal-token",
            "Idempotency-Key": "dim-u-topup-credit",
        },
        json={
            "auto_topup_threshold": 1_000,
            "auto_topup_amount": 5_000,
            "monthly_budget_yen": 10_000,
            "immediate_amount": 5_000,
            "note": "initial credit",
        },
    )

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["balance_yen"] == 5_000
    assert body["topup_requested_yen"] == 5_000
    assert body["topup_recorded_yen"] == 5_000

    row = _wallet_row(am_db, key_hash)
    assert row is not None
    assert int(row["balance_yen"]) == 5_000
    assert int(row["auto_topup_threshold"]) == 1_000
    assert int(row["auto_topup_amount"]) == 5_000
    assert int(row["monthly_budget_yen"]) == 10_000

    conn = sqlite3.connect(str(am_db))
    try:
        (topups,) = conn.execute(
            "SELECT COUNT(*) FROM am_credit_transaction_log WHERE txn_type = 'topup'"
        ).fetchone()
    finally:
        conn.close()
    assert topups == 1
    assert _usage_count(seeded_db, key_hash, ("wallet_topup",)) == 0


def test_wallet_control_plane_reads_do_not_emit_paid_usage(
    tmp_path: pathlib.Path,
    seeded_db: pathlib.Path,
    paid_key: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    am_db = tmp_path / "wallet-api.db"
    c = _wallet_api_client(
        seeded_db=seeded_db,
        autonomath_db=am_db,
        monkeypatch=monkeypatch,
    )
    key_hash = hash_api_key(paid_key)
    endpoints = ("wallet_balance", "wallet_transactions", "wallet_alerts")
    before = _usage_count(seeded_db, key_hash, endpoints)

    for path in ("/v1/wallet/balance", "/v1/wallet/transactions", "/v1/wallet/alerts"):
        res = c.get(path, headers={"X-API-Key": paid_key})
        assert res.status_code == 200, res.text
        assert res.json()["_billing_unit"] == 0

    assert _usage_count(seeded_db, key_hash, endpoints) == before


# ---------------------------------------------------------------------------
# 1. Migration applies + is idempotent
# ---------------------------------------------------------------------------


def test_mig_281_applies_clean(tmp_path: pathlib.Path) -> None:
    db = _fresh_db(tmp_path)
    conn = sqlite3.connect(str(db))
    try:
        names = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type IN ('table','view') "
                "AND (name LIKE 'am_credit_%' OR name LIKE 'v_credit_%')"
            )
        }
        assert "am_credit_wallet" in names
        assert "am_credit_transaction_log" in names
        assert "am_credit_spending_alert" in names
        assert "v_credit_wallet_topup_due" in names
    finally:
        conn.close()


def test_mig_281_is_idempotent(tmp_path: pathlib.Path) -> None:
    db = _fresh_db(tmp_path)
    _apply(db, MIG_281)


# ---------------------------------------------------------------------------
# 2. Rollback drops every artefact
# ---------------------------------------------------------------------------


def test_mig_281_rollback_drops_all(tmp_path: pathlib.Path) -> None:
    db = _fresh_db(tmp_path)
    _apply(db, MIG_281_RB)
    conn = sqlite3.connect(str(db))
    try:
        rows = conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type IN ('table','view','index') "
            "AND (name LIKE 'am_credit_%' OR name LIKE 'v_credit_%' "
            "  OR name LIKE 'idx_am_credit_%')"
        ).fetchall()
        assert rows == []
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 3. CHECK constraints
# ---------------------------------------------------------------------------


def test_check_owner_token_hash_length(tmp_path: pathlib.Path) -> None:
    db = _fresh_db(tmp_path)
    conn = sqlite3.connect(str(db))
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO am_credit_wallet (owner_token_hash) VALUES (?)",
                ("short",),
            )
    finally:
        conn.close()


def test_check_balance_non_negative(tmp_path: pathlib.Path) -> None:
    db = _fresh_db(tmp_path)
    conn = sqlite3.connect(str(db))
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO am_credit_wallet (owner_token_hash, balance_yen) VALUES (?, ?)",
                ("b" * 64, -1),
            )
    finally:
        conn.close()


def test_check_txn_type_enum(tmp_path: pathlib.Path) -> None:
    db = _fresh_db(tmp_path)
    conn = sqlite3.connect(str(db))
    try:
        wid = _make_wallet(conn)
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO am_credit_transaction_log "
                "(wallet_id, amount_yen, txn_type) VALUES (?, ?, ?)",
                (wid, 100, "bogus"),
            )
    finally:
        conn.close()


def test_check_txn_sign_rule(tmp_path: pathlib.Path) -> None:
    """topup/refund must be positive, charge must be negative."""
    db = _fresh_db(tmp_path)
    conn = sqlite3.connect(str(db))
    try:
        wid = _make_wallet(conn)
        # topup with negative amount -> reject
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO am_credit_transaction_log "
                "(wallet_id, amount_yen, txn_type) VALUES (?, ?, 'topup')",
                (wid, -100),
            )
        # charge with positive amount -> reject
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO am_credit_transaction_log "
                "(wallet_id, amount_yen, txn_type) VALUES (?, ?, 'charge')",
                (wid, 100),
            )
    finally:
        conn.close()


def test_check_threshold_pct_enum(tmp_path: pathlib.Path) -> None:
    db = _fresh_db(tmp_path)
    conn = sqlite3.connect(str(db))
    try:
        wid = _make_wallet(conn)
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO am_credit_spending_alert "
                "(wallet_id, threshold_pct, billing_cycle, spent_yen, budget_yen) "
                "VALUES (?, ?, ?, ?, ?)",
                (wid, 25, "2026-05", 100, 1000),
            )
    finally:
        conn.close()


def test_check_billing_cycle_length(tmp_path: pathlib.Path) -> None:
    db = _fresh_db(tmp_path)
    conn = sqlite3.connect(str(db))
    try:
        wid = _make_wallet(conn)
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO am_credit_spending_alert "
                "(wallet_id, threshold_pct, billing_cycle, spent_yen, budget_yen) "
                "VALUES (?, ?, ?, ?, ?)",
                (wid, 50, "2026-5", 100, 1000),
            )
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 4. UNIQUE constraints
# ---------------------------------------------------------------------------


def test_unique_owner_token_hash(tmp_path: pathlib.Path) -> None:
    db = _fresh_db(tmp_path)
    conn = sqlite3.connect(str(db))
    try:
        _make_wallet(conn, owner_seed="a")
        with pytest.raises(sqlite3.IntegrityError):
            _make_wallet(conn, owner_seed="a")  # same token_hash
    finally:
        conn.close()


def test_unique_alert_per_wallet_threshold_cycle(tmp_path: pathlib.Path) -> None:
    db = _fresh_db(tmp_path)
    conn = sqlite3.connect(str(db))
    try:
        wid = _make_wallet(conn)
        conn.execute(
            "INSERT INTO am_credit_spending_alert "
            "(wallet_id, threshold_pct, billing_cycle, spent_yen, budget_yen) "
            "VALUES (?, ?, ?, ?, ?)",
            (wid, 50, "2026-05", 500, 1000),
        )
        conn.commit()
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO am_credit_spending_alert "
                "(wallet_id, threshold_pct, billing_cycle, spent_yen, budget_yen) "
                "VALUES (?, ?, ?, ?, ?)",
                (wid, 50, "2026-05", 600, 1000),
            )
            conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 5. ETL — 3 threshold firing semantics
# ---------------------------------------------------------------------------


def test_etl_fires_threshold_50_only(tmp_path: pathlib.Path) -> None:
    db = _fresh_db(tmp_path)
    conn = sqlite3.connect(str(db))
    try:
        wid = _make_wallet(conn, owner_seed="b", monthly_budget=10_000)
        _charge(conn, wid, 5_500, "2026-05")  # 55% -> only 50 fires
    finally:
        conn.close()
    rep = _run_etl(db, "--cycle", "2026-05")
    fired_pcts = sorted(a["threshold_pct"] for a in rep["alerts_fired"])
    assert fired_pcts == [50]


def test_etl_fires_50_and_80(tmp_path: pathlib.Path) -> None:
    db = _fresh_db(tmp_path)
    conn = sqlite3.connect(str(db))
    try:
        wid = _make_wallet(conn, owner_seed="c", monthly_budget=10_000)
        _charge(conn, wid, 8_500, "2026-05")  # 85% -> 50 + 80 fire
    finally:
        conn.close()
    rep = _run_etl(db, "--cycle", "2026-05")
    fired_pcts = sorted(a["threshold_pct"] for a in rep["alerts_fired"])
    assert fired_pcts == [50, 80]


def test_etl_fires_all_three_thresholds(tmp_path: pathlib.Path) -> None:
    db = _fresh_db(tmp_path)
    conn = sqlite3.connect(str(db))
    try:
        wid = _make_wallet(conn, owner_seed="d", monthly_budget=10_000)
        _charge(conn, wid, 12_000, "2026-05")  # 120% -> all 3 fire
    finally:
        conn.close()
    rep = _run_etl(db, "--cycle", "2026-05")
    fired_pcts = sorted(a["threshold_pct"] for a in rep["alerts_fired"])
    assert fired_pcts == [50, 80, 100]


def test_etl_idempotent_within_cycle(tmp_path: pathlib.Path) -> None:
    db = _fresh_db(tmp_path)
    conn = sqlite3.connect(str(db))
    try:
        wid = _make_wallet(conn, owner_seed="e", monthly_budget=10_000)
        _charge(conn, wid, 12_000, "2026-05")
    finally:
        conn.close()
    rep1 = _run_etl(db, "--cycle", "2026-05")
    assert len(rep1["alerts_fired"]) == 3
    rep2 = _run_etl(db, "--cycle", "2026-05")
    assert rep2["alerts_fired"] == []  # all already fired this cycle


def test_etl_re_fires_in_next_cycle(tmp_path: pathlib.Path) -> None:
    db = _fresh_db(tmp_path)
    conn = sqlite3.connect(str(db))
    try:
        wid = _make_wallet(conn, owner_seed="f", monthly_budget=10_000)
        _charge(conn, wid, 5_500, "2026-05")
    finally:
        conn.close()
    rep_may = _run_etl(db, "--cycle", "2026-05")
    assert [a["threshold_pct"] for a in rep_may["alerts_fired"]] == [50]

    # Same wallet, June charge crosses 50% again.
    conn = sqlite3.connect(str(db))
    try:
        _charge(conn, _wallet_id_by_seed(conn, "f"), 5_500, "2026-06")
    finally:
        conn.close()
    rep_jun = _run_etl(db, "--cycle", "2026-06")
    assert [a["threshold_pct"] for a in rep_jun["alerts_fired"]] == [50]


def _wallet_id_by_seed(conn: sqlite3.Connection, seed: str) -> int:
    token = (seed * 64)[:64]
    row = conn.execute(
        "SELECT wallet_id FROM am_credit_wallet WHERE owner_token_hash = ?",
        (token,),
    ).fetchone()
    return int(row[0])


def test_etl_dry_run_writes_nothing(tmp_path: pathlib.Path) -> None:
    db = _fresh_db(tmp_path)
    conn = sqlite3.connect(str(db))
    try:
        wid = _make_wallet(conn, owner_seed="g", monthly_budget=10_000)
        _charge(conn, wid, 12_000, "2026-05")
    finally:
        conn.close()
    _run_etl(db, "--cycle", "2026-05", "--dry-run")
    conn = sqlite3.connect(str(db))
    try:
        n = conn.execute("SELECT COUNT(*) FROM am_credit_spending_alert").fetchone()[0]
    finally:
        conn.close()
    assert n == 0


def test_etl_skips_disabled_wallet(tmp_path: pathlib.Path) -> None:
    db = _fresh_db(tmp_path)
    conn = sqlite3.connect(str(db))
    try:
        wid = _make_wallet(conn, owner_seed="h", monthly_budget=10_000)
        _charge(conn, wid, 12_000, "2026-05")
        conn.execute("UPDATE am_credit_wallet SET enabled = 0 WHERE wallet_id = ?", (wid,))
        conn.commit()
    finally:
        conn.close()
    rep = _run_etl(db, "--cycle", "2026-05")
    assert rep["alerts_fired"] == []
    assert rep["wallets_scanned"] == 0


def test_etl_skips_wallet_without_budget(tmp_path: pathlib.Path) -> None:
    db = _fresh_db(tmp_path)
    conn = sqlite3.connect(str(db))
    try:
        wid = _make_wallet(conn, owner_seed="i", monthly_budget=0)
        _charge(conn, wid, 5_000, "2026-05")
    finally:
        conn.close()
    rep = _run_etl(db, "--cycle", "2026-05")
    assert rep["alerts_fired"] == []


# ---------------------------------------------------------------------------
# 6. Helper view: auto-topup-due
# ---------------------------------------------------------------------------


def test_view_topup_due_lists_low_balance(tmp_path: pathlib.Path) -> None:
    db = _fresh_db(tmp_path)
    conn = sqlite3.connect(str(db))
    try:
        # Wallet 1: below threshold, auto-topup configured -> due.
        wid_due = _make_wallet(
            conn,
            owner_seed="x",
            balance=100,
            auto_topup_threshold=1_000,
            auto_topup_amount=5_000,
        )
        # Wallet 2: above threshold -> not due.
        _make_wallet(
            conn,
            owner_seed="y",
            balance=2_000,
            auto_topup_threshold=1_000,
            auto_topup_amount=5_000,
        )
        # Wallet 3: auto-topup disabled (threshold=0) -> not due.
        _make_wallet(
            conn,
            owner_seed="z",
            balance=100,
            auto_topup_threshold=0,
            auto_topup_amount=0,
        )
        due_ids = [r[0] for r in conn.execute(
            "SELECT wallet_id FROM v_credit_wallet_topup_due"
        )]
    finally:
        conn.close()
    assert due_ids == [wid_due]


# ---------------------------------------------------------------------------
# 7. Boot-manifest integrity
# ---------------------------------------------------------------------------


def test_manifest_jpcite_lists_281() -> None:
    assert "281_credit_wallet.sql" in MANIFEST_JPCITE.read_text(encoding="utf-8")


def test_manifest_autonomath_lists_281() -> None:
    assert "281_credit_wallet.sql" in MANIFEST_AM.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 8. LLM-0 + brand discipline
# ---------------------------------------------------------------------------


_FORBIDDEN_LLM_TOKENS = ("anthropic", "openai", "google.generativeai")


def test_no_llm_import_in_etl_or_migration() -> None:
    """Dim U surface MUST stay LLM-free (feedback_no_operator_llm_api)."""
    sources = [
        ETL.read_text(encoding="utf-8"),
        MIG_281.read_text(encoding="utf-8"),
        MIG_281_RB.read_text(encoding="utf-8"),
    ]
    for src in sources:
        for bad in _FORBIDDEN_LLM_TOKENS:
            assert f"import {bad}" not in src
            assert f"from {bad}" not in src


def test_no_legacy_brand_in_new_files() -> None:
    legacy_phrases = ("税務会計AI", "zeimu-kaikei.ai")
    sources = [
        ETL.read_text(encoding="utf-8"),
        MIG_281.read_text(encoding="utf-8"),
        MIG_281_RB.read_text(encoding="utf-8"),
    ]
    for src in sources:
        for bad in legacy_phrases:
            assert bad not in src, f"legacy brand `{bad}` found in new file"
