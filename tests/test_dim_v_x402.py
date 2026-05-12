"""Integration tests for Dim V x402 protocol micropayment surface (Wave 47).

Closes the Wave 46 dim V storage gap: migration 282 adds
``am_x402_endpoint_config`` (config table, 1 row per x402-gated endpoint)
and ``am_x402_payment_log`` (append-only on-chain audit) per
``feedback_agent_x402_protocol.md``. Pairs with
``scripts/etl/seed_x402_endpoints.py`` (5-endpoint seed: search /
programs / cases / audit_workpaper / semantic_search). The existing
inline-CREATE ``x402_tx_bind`` table in ``src/jpintel_mcp/api/billing_v2.py``
is NOT modified by this migration; the Dim V additions are purely
additive.

Case bundles
------------
  1. Migration 282 applies cleanly on a fresh SQLite db (idempotent re-apply).
  2. Migration 282 rollback drops every artefact created.
  3. CHECK constraints reject malformed rows (endpoint_path missing leading
     slash, required_amount_usdc <= 0, amount > 100 cap, expires TTL out of
     range, payer_address not 0x..., txn_hash wrong length, 402 id length).
  4. Seeder upserts 5 canonical endpoints and is idempotent across re-runs.
  5. Helper view ``v_x402_endpoint_enabled`` excludes disabled rows.
  6. ``--force`` upserts repriced amount; ``noop`` when unchanged.
  7. Boot manifest registration (jpcite + autonomath mirror).
  8. **LLM-0 verify** — grep -E "anthropic|openai" in new files = 0.
  9. Brand discipline — no 税務会計AI / zeimu-kaikei.ai in new files.
 10. Existing x402_tx_bind table is untouched (additive-only invariant).

Hard constraints exercised
--------------------------
  * No LLM SDK import in any new file (x402 is on-chain only).
  * Schema is config + audit only; no prompt / response / completion column.
  * Brand: only jpcite. No legacy ``税務会計AI`` / ``zeimu-kaikei.ai``.
  * USDC amount > 0 and capped at 100 (sanity).
"""

from __future__ import annotations

import json
import pathlib
import sqlite3
import subprocess
import sys

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
MIG_282 = REPO_ROOT / "scripts" / "migrations" / "282_x402_payment.sql"
MIG_282_RB = REPO_ROOT / "scripts" / "migrations" / "282_x402_payment_rollback.sql"
ETL_SEED = REPO_ROOT / "scripts" / "etl" / "seed_x402_endpoints.py"
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
    db = tmp_path / "dim_v.db"
    _apply(db, MIG_282)
    return db


# ---------------------------------------------------------------------------
# 1. Migration applies + is idempotent
# ---------------------------------------------------------------------------


def test_mig_282_applies_clean(tmp_path: pathlib.Path) -> None:
    db = _fresh_db(tmp_path)
    conn = sqlite3.connect(str(db))
    try:
        names = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type IN ('table','view') "
                "AND (name LIKE 'am_x402_%' OR name LIKE 'v_x402_%')"
            )
        }
        assert "am_x402_endpoint_config" in names
        assert "am_x402_payment_log" in names
        assert "v_x402_endpoint_enabled" in names
    finally:
        conn.close()


def test_mig_282_is_idempotent(tmp_path: pathlib.Path) -> None:
    db = _fresh_db(tmp_path)
    _apply(db, MIG_282)  # re-apply must not raise


# ---------------------------------------------------------------------------
# 2. Rollback drops every artefact
# ---------------------------------------------------------------------------


def test_mig_282_rollback_drops_all(tmp_path: pathlib.Path) -> None:
    db = _fresh_db(tmp_path)
    _apply(db, MIG_282_RB)
    conn = sqlite3.connect(str(db))
    try:
        rows = conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type IN ('table','view','index') "
            "AND (name LIKE 'am_x402_%' OR name LIKE 'v_x402_%' "
            "  OR name LIKE 'idx_am_x402_%')"
        ).fetchall()
        assert rows == []
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 3. CHECK constraints reject malformed rows
# ---------------------------------------------------------------------------


def test_check_endpoint_path_requires_leading_slash(tmp_path: pathlib.Path) -> None:
    db = _fresh_db(tmp_path)
    conn = sqlite3.connect(str(db))
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO am_x402_endpoint_config "
                "(endpoint_path, required_amount_usdc) VALUES (?, ?)",
                ("no-leading-slash", 0.001),
            )
    finally:
        conn.close()


def test_check_amount_positive(tmp_path: pathlib.Path) -> None:
    db = _fresh_db(tmp_path)
    conn = sqlite3.connect(str(db))
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO am_x402_endpoint_config "
                "(endpoint_path, required_amount_usdc) VALUES (?, ?)",
                ("/v1/foo", 0.0),
            )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO am_x402_endpoint_config "
                "(endpoint_path, required_amount_usdc) VALUES (?, ?)",
                ("/v1/foo", -0.001),
            )
    finally:
        conn.close()


def test_check_amount_sanity_cap(tmp_path: pathlib.Path) -> None:
    db = _fresh_db(tmp_path)
    conn = sqlite3.connect(str(db))
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO am_x402_endpoint_config "
                "(endpoint_path, required_amount_usdc) VALUES (?, ?)",
                ("/v1/foo", 1000.0),  # >100 cap
            )
    finally:
        conn.close()


def test_check_ttl_range(tmp_path: pathlib.Path) -> None:
    db = _fresh_db(tmp_path)
    conn = sqlite3.connect(str(db))
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO am_x402_endpoint_config "
                "(endpoint_path, required_amount_usdc, expires_after_seconds) "
                "VALUES (?, ?, ?)",
                ("/v1/foo", 0.001, 30),  # < 60s
            )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO am_x402_endpoint_config "
                "(endpoint_path, required_amount_usdc, expires_after_seconds) "
                "VALUES (?, ?, ?)",
                ("/v1/foo", 0.001, 999999),  # > 86400 (24h)
            )
    finally:
        conn.close()


def test_check_payer_address_format(tmp_path: pathlib.Path) -> None:
    db = _fresh_db(tmp_path)
    conn = sqlite3.connect(str(db))
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO am_x402_payment_log "
                "(http_status_402_id, endpoint_path, amount_usdc, payer_address, txn_hash) "
                "VALUES (?, ?, ?, ?, ?)",
                ("nonce-abc-1234", "/v1/search", 0.001, "not-an-eth-addr", "0x" + "a" * 64),
            )
    finally:
        conn.close()


def test_check_txn_hash_format(tmp_path: pathlib.Path) -> None:
    db = _fresh_db(tmp_path)
    conn = sqlite3.connect(str(db))
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO am_x402_payment_log "
                "(http_status_402_id, endpoint_path, amount_usdc, payer_address, txn_hash) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    "nonce-abc-1234",
                    "/v1/search",
                    0.001,
                    "0x" + "1" * 40,
                    "0xshort",  # too short
                ),
            )
    finally:
        conn.close()


def test_check_status_id_length(tmp_path: pathlib.Path) -> None:
    db = _fresh_db(tmp_path)
    conn = sqlite3.connect(str(db))
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO am_x402_payment_log "
                "(http_status_402_id, endpoint_path, amount_usdc, payer_address, txn_hash) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    "abc",  # < 8 chars
                    "/v1/search",
                    0.001,
                    "0x" + "1" * 40,
                    "0x" + "a" * 64,
                ),
            )
    finally:
        conn.close()


def test_payment_log_inserts_ok(tmp_path: pathlib.Path) -> None:
    """Happy path: well-formed payment_log row inserts cleanly."""
    db = _fresh_db(tmp_path)
    conn = sqlite3.connect(str(db))
    try:
        conn.execute(
            "INSERT INTO am_x402_endpoint_config "
            "(endpoint_path, required_amount_usdc) VALUES (?, ?)",
            ("/v1/search", 0.001),
        )
        conn.execute(
            "INSERT INTO am_x402_payment_log "
            "(http_status_402_id, endpoint_path, amount_usdc, payer_address, txn_hash) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                "nonce-abc-1234",
                "/v1/search",
                0.001,
                "0x" + "1" * 40,
                "0x" + "a" * 64,
            ),
        )
        conn.commit()
        n = conn.execute("SELECT COUNT(*) FROM am_x402_payment_log").fetchone()[0]
    finally:
        conn.close()
    assert n == 1


def test_txn_hash_is_unique(tmp_path: pathlib.Path) -> None:
    """Duplicate on-chain txn must not produce duplicate audit rows."""
    db = _fresh_db(tmp_path)
    conn = sqlite3.connect(str(db))
    try:
        conn.execute(
            "INSERT INTO am_x402_payment_log "
            "(http_status_402_id, endpoint_path, amount_usdc, payer_address, txn_hash) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                "nonce-abc-1234",
                "/v1/search",
                0.001,
                "0x" + "1" * 40,
                "0x" + "a" * 64,
            ),
        )
        conn.commit()
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO am_x402_payment_log "
                "(http_status_402_id, endpoint_path, amount_usdc, payer_address, txn_hash) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    "nonce-xyz-9999",
                    "/v1/search",
                    0.001,
                    "0x" + "2" * 40,
                    "0x" + "a" * 64,  # same txn_hash
                ),
            )
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 4. Seeder upserts 5 canonical endpoints + idempotency
# ---------------------------------------------------------------------------


def _run_seed(db: pathlib.Path, *extra: str) -> dict:
    proc = subprocess.run(
        [sys.executable, str(ETL_SEED), "--db", str(db), *extra],
        check=True,
        capture_output=True,
        text=True,
    )
    last_line = proc.stdout.strip().splitlines()[-1]
    return json.loads(last_line)


def test_seed_inserts_5_endpoints(tmp_path: pathlib.Path) -> None:
    db = _fresh_db(tmp_path)
    rep = _run_seed(db)
    actions = {e["endpoint_path"]: e["action"] for e in rep["endpoints"]}
    expected = {
        "/v1/audit_workpaper",
        "/v1/cases",
        "/v1/programs",
        "/v1/search",
        "/v1/semantic_search",
    }
    assert set(actions) == expected
    for path, act in actions.items():
        assert act == "inserted", f"{path} should be inserted on first run"

    conn = sqlite3.connect(str(db))
    try:
        n = conn.execute("SELECT COUNT(*) FROM am_x402_endpoint_config").fetchone()[0]
    finally:
        conn.close()
    assert n == 5


def test_seed_is_idempotent(tmp_path: pathlib.Path) -> None:
    db = _fresh_db(tmp_path)
    _run_seed(db)
    rep2 = _run_seed(db)
    for e in rep2["endpoints"]:
        assert e["action"] == "noop", f"{e['endpoint_path']} should be noop on re-run"


def test_seed_dry_run_writes_nothing(tmp_path: pathlib.Path) -> None:
    db = _fresh_db(tmp_path)
    rep = _run_seed(db, "--dry-run")
    assert rep["dry_run"] is True
    conn = sqlite3.connect(str(db))
    try:
        n = conn.execute("SELECT COUNT(*) FROM am_x402_endpoint_config").fetchone()[0]
    finally:
        conn.close()
    assert n == 0


# ---------------------------------------------------------------------------
# 5. Helper view excludes disabled rows
# ---------------------------------------------------------------------------


def test_view_excludes_disabled(tmp_path: pathlib.Path) -> None:
    db = _fresh_db(tmp_path)
    _run_seed(db)
    conn = sqlite3.connect(str(db))
    try:
        conn.execute(
            "UPDATE am_x402_endpoint_config SET enabled = 0 WHERE endpoint_path = ?",
            ("/v1/cases",),
        )
        conn.commit()
        paths = {r[0] for r in conn.execute("SELECT endpoint_path FROM v_x402_endpoint_enabled")}
    finally:
        conn.close()
    assert "/v1/cases" not in paths
    assert "/v1/search" in paths


# ---------------------------------------------------------------------------
# 6. --force upserts repriced amount; noop when unchanged
# ---------------------------------------------------------------------------


def test_force_upserts_when_price_changes(tmp_path: pathlib.Path) -> None:
    db = _fresh_db(tmp_path)
    _run_seed(db)  # initial seed
    # Mutate one row to a different amount so the seeder will see drift.
    conn = sqlite3.connect(str(db))
    try:
        conn.execute(
            "UPDATE am_x402_endpoint_config SET required_amount_usdc = ? WHERE endpoint_path = ?",
            (0.999, "/v1/search"),
        )
        conn.commit()
    finally:
        conn.close()
    # Without --force, drift stays (noop).
    rep_noop = _run_seed(db)
    by_path = {e["endpoint_path"]: e["action"] for e in rep_noop["endpoints"]}
    assert by_path["/v1/search"] == "noop"
    # With --force, drift reverts to canonical 0.001 (updated).
    rep_force = _run_seed(db, "--force")
    by_path_force = {e["endpoint_path"]: e["action"] for e in rep_force["endpoints"]}
    assert by_path_force["/v1/search"] == "updated"


# ---------------------------------------------------------------------------
# 7. Boot-manifest integrity
# ---------------------------------------------------------------------------


def test_manifest_jpcite_lists_282() -> None:
    """jpcite boot manifest registers migration 282_x402_payment.sql."""
    assert "282_x402_payment.sql" in MANIFEST_JPCITE.read_text(encoding="utf-8")


def test_manifest_autonomath_lists_282() -> None:
    """autonomath boot manifest (mirror) registers migration 282."""
    assert "282_x402_payment.sql" in MANIFEST_AM.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 8/9. LLM-0 verify + brand discipline
# ---------------------------------------------------------------------------


_FORBIDDEN_LLM_TOKENS = ("anthropic", "openai", "google.generativeai")


def test_no_llm_import_in_etl_or_migration() -> None:
    """Dim V surface MUST stay LLM-free (feedback_no_operator_llm_api)."""
    sources = [
        ETL_SEED.read_text(encoding="utf-8"),
        MIG_282.read_text(encoding="utf-8"),
        MIG_282_RB.read_text(encoding="utf-8"),
    ]
    for src in sources:
        for bad in _FORBIDDEN_LLM_TOKENS:
            assert f"import {bad}" not in src
            assert f"from {bad}" not in src


def test_no_legacy_brand_in_new_files() -> None:
    """No 税務会計AI / zeimu-kaikei.ai legacy brand in new files."""
    legacy_phrases = ("税務会計AI", "zeimu-kaikei.ai")
    sources = [
        ETL_SEED.read_text(encoding="utf-8"),
        MIG_282.read_text(encoding="utf-8"),
        MIG_282_RB.read_text(encoding="utf-8"),
    ]
    for src in sources:
        for bad in legacy_phrases:
            assert bad not in src, f"legacy brand `{bad}` found in new file"


# ---------------------------------------------------------------------------
# 10. Existing x402_tx_bind table is untouched (additive-only invariant)
# ---------------------------------------------------------------------------


def test_migration_does_not_reference_x402_tx_bind(tmp_path: pathlib.Path) -> None:
    """Dim V migration must NOT redefine / drop the legacy x402_tx_bind
    table owned by ``src/jpintel_mcp/api/billing_v2.py``.
    """
    src = MIG_282.read_text(encoding="utf-8")
    rb = MIG_282_RB.read_text(encoding="utf-8")
    for hostile in ("DROP TABLE x402_tx_bind", "DELETE FROM x402_tx_bind"):
        assert hostile not in src
        assert hostile not in rb
