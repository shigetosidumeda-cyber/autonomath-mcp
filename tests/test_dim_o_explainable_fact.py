"""Integration tests for Dim O explainable fact knowledge graph (Wave 47).

Closes the Dim O explainable_fact_design gap:

* Migration 275 lands ``am_fact_metadata`` (4-axis: source_doc /
  extracted_at / verified_by / confidence_band) + ``am_fact_attestation
  _log`` (append-only audit trail with Ed25519 signatures).
* ETL ``scripts/etl/build_explainable_fact_metadata.py`` enriches
  signed facts with the 4-axis metadata and appends an attestation row
  every time the metadata tuple changes.
* Ed25519 sign/verify roundtrip with public key.
* Byte-tamper detection: flipped metadata fails verify.

Hard constraints exercised
--------------------------
* Migration is idempotent (re-apply is a no-op).
* No LLM SDK import in the ETL.
* ``am_fact_signature`` (migration 262) is NEVER mutated by the ETL.
* Append-only log: a second run on changed metadata APPENDS a new
  attestation row (does not UPDATE the old one).
* Confidence band CHECK constraints: lower <= upper, both in [0, 1].
* Boot manifests (jpcite + autonomath) register migration 275.
"""

from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import re
import sqlite3
import subprocess
import sys
import tempfile

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
MIG_262 = REPO_ROOT / "scripts" / "migrations" / "262_fact_signature_v2.sql"
MIG_275 = REPO_ROOT / "scripts" / "migrations" / "275_explainable_fact.sql"
MIG_275_RB = (
    REPO_ROOT / "scripts" / "migrations" / "275_explainable_fact_rollback.sql"
)
ETL_BUILD = (
    REPO_ROOT / "scripts" / "etl" / "build_explainable_fact_metadata.py"
)
MANIFEST_JPCITE = (
    REPO_ROOT / "scripts" / "migrations" / "jpcite_boot_manifest.txt"
)
MANIFEST_AM = (
    REPO_ROOT / "scripts" / "migrations" / "autonomath_boot_manifest.txt"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _apply_sql(db: pathlib.Path, sql_path: pathlib.Path) -> None:
    conn = sqlite3.connect(str(db))
    try:
        conn.executescript(sql_path.read_text(encoding="utf-8"))
    finally:
        conn.close()


def _fresh_db(tmp_path: pathlib.Path) -> pathlib.Path:
    db = tmp_path / "dim_o_test.db"
    _apply_sql(db, MIG_262)  # need am_fact_signature substrate
    _apply_sql(db, MIG_275)
    return db


def _seed_signed_fact(db: pathlib.Path, fact_id: str) -> None:
    """Seed a single am_fact_signature row so the ETL has something to walk."""
    conn = sqlite3.connect(str(db))
    try:
        conn.execute(
            """
            INSERT INTO am_fact_signature
                (fact_id, ed25519_sig, corpus_snapshot_id, key_id,
                 payload_sha256)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                fact_id,
                b"\x00" * 64,  # min-size BLOB to satisfy CHECK
                "snap_w47_a",
                "k20260512_a",
                "deadbeef" * 8,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _seed_current_eav_fact(
    db: pathlib.Path,
    fact_id: str,
    *,
    source_url: str = "https://example.test/source-row",
    fact_source_url: str | None = None,
) -> None:
    """Seed current am_entity_facts/am_source schema without confidence."""
    conn = sqlite3.connect(str(db))
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS am_source (
                id         TEXT PRIMARY KEY,
                source_url TEXT
            );
            CREATE TABLE IF NOT EXISTS am_entity_facts (
                id         TEXT PRIMARY KEY,
                source_url TEXT,
                source_id  TEXT,
                created_at TEXT
            );
            """
        )
        conn.execute(
            "INSERT OR REPLACE INTO am_source(id, source_url) VALUES (?, ?)",
            (f"src_{fact_id}", source_url),
        )
        conn.execute(
            """
            INSERT OR REPLACE INTO am_entity_facts
                (id, source_url, source_id, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (
                fact_id,
                fact_source_url,
                f"src_{fact_id}",
                "2026-05-12T00:00:00.000Z",
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _import_etl_module():
    spec = importlib.util.spec_from_file_location(
        "_dim_o_etl_mod", ETL_BUILD
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_dim_o_etl_mod"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def ed25519_keypair():
    """Generate a fresh Ed25519 keypair for the test session."""
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (
            Ed25519PrivateKey,
        )
    except ImportError:
        pytest.skip("cryptography not installed")
    priv = Ed25519PrivateKey.generate()
    seed = priv.private_bytes_raw()  # type: ignore[attr-defined]
    return (priv, priv.public_key(), seed.hex())


# ---------------------------------------------------------------------------
# Case 1 — Migration apply + idempotent + rollback
# ---------------------------------------------------------------------------


def test_migration_275_creates_tables(tmp_path: pathlib.Path) -> None:
    db = _fresh_db(tmp_path)
    conn = sqlite3.connect(str(db))
    try:
        names = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type IN ('table','view') ORDER BY name"
            ).fetchall()
        }
        assert "am_fact_metadata" in names
        assert "am_fact_attestation_log" in names
        assert "v_am_fact_attestation_latest" in names
        assert "v_am_fact_explainability" in names
    finally:
        conn.close()


def test_migration_275_idempotent(tmp_path: pathlib.Path) -> None:
    """A second migration apply is a no-op (no duplicate-create error)."""
    db = _fresh_db(tmp_path)
    _apply_sql(db, MIG_275)  # second apply
    conn = sqlite3.connect(str(db))
    try:
        cnt = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE name='am_fact_metadata'"
        ).fetchone()[0]
        assert cnt == 1
    finally:
        conn.close()


def test_migration_275_rollback(tmp_path: pathlib.Path) -> None:
    db = _fresh_db(tmp_path)
    _apply_sql(db, MIG_275_RB)
    conn = sqlite3.connect(str(db))
    try:
        names = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table','view')"
            ).fetchall()
        }
        assert "am_fact_metadata" not in names
        assert "am_fact_attestation_log" not in names
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Case 2 — 4-axis metadata schema enforcement
# ---------------------------------------------------------------------------


def test_confidence_band_check_lower_le_upper(tmp_path: pathlib.Path) -> None:
    """confidence_lower > confidence_upper is rejected by CHECK."""
    db = _fresh_db(tmp_path)
    conn = sqlite3.connect(str(db))
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO am_fact_metadata
                    (fact_id, source_doc, verified_by,
                     confidence_lower, confidence_upper, ed25519_sig)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                ("fact_bad", "https://example.jp/a", "test", 0.9, 0.5,
                 b"\x00" * 64),
            )
    finally:
        conn.close()


def test_confidence_band_check_in_unit_interval(tmp_path: pathlib.Path) -> None:
    """Confidence outside [0, 1] is rejected."""
    db = _fresh_db(tmp_path)
    conn = sqlite3.connect(str(db))
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO am_fact_metadata
                    (fact_id, verified_by, confidence_lower, confidence_upper,
                     ed25519_sig)
                VALUES (?, ?, ?, ?, ?)
                """,
                ("fact_oob", "test", -0.1, 0.5, b"\x00" * 64),
            )
    finally:
        conn.close()


def test_sig_size_check_min(tmp_path: pathlib.Path) -> None:
    """ed25519_sig < 64 bytes rejected."""
    db = _fresh_db(tmp_path)
    conn = sqlite3.connect(str(db))
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO am_fact_metadata (fact_id, verified_by, "
                "ed25519_sig) VALUES (?, ?, ?)",
                ("fact_short", "test", b"\x00" * 32),
            )
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Case 3 — ETL signs + appends to attestation log
# ---------------------------------------------------------------------------


def test_etl_helpers_read_current_eav_schema_without_confidence(
    tmp_path: pathlib.Path,
) -> None:
    """Current EAV uses id/source_url/source_id and may omit confidence."""
    db = _fresh_db(tmp_path)
    _seed_current_eav_fact(
        db,
        "fact_current_schema",
        source_url="https://example.test/source-table",
        fact_source_url=None,
    )
    etl = _import_etl_module()
    conn = sqlite3.connect(str(db))
    try:
        assert (
            etl._derive_source_doc("fact_current_schema", conn)
            == "https://example.test/source-table"
        )
        assert etl._derive_confidence("fact_current_schema", conn) == (None, None)
    finally:
        conn.close()


def test_etl_run_signs_and_appends(
    tmp_path: pathlib.Path, ed25519_keypair, monkeypatch
) -> None:
    """ETL produces an Ed25519 signature on am_fact_metadata + attestation log."""
    _priv, _pub, seed_hex = ed25519_keypair
    db = _fresh_db(tmp_path)
    _seed_signed_fact(db, "fact_alpha")
    _seed_current_eav_fact(
        db,
        "fact_alpha",
        source_url="https://example.test/source-table",
        fact_source_url="https://example.test/fact-row",
    )

    monkeypatch.setenv("AUTONOMATH_DB_PATH", str(db))
    monkeypatch.setenv("AUTONOMATH_FACT_SIGN_PRIVATE_KEY", seed_hex)

    etl = _import_etl_module()
    rc = etl.main([])
    assert rc == 0

    conn = sqlite3.connect(str(db))
    try:
        row = conn.execute(
            "SELECT fact_id, verified_by, length(ed25519_sig), "
            "source_doc, confidence_lower, confidence_upper "
            "FROM am_fact_metadata WHERE fact_id='fact_alpha'"
        ).fetchone()
        assert row is not None
        assert row[0] == "fact_alpha"
        assert row[1] == etl.DEFAULT_VERIFIED_BY
        # prefix(8) + raw(64) + suffix(8) = 80 bytes
        assert 64 <= row[2] <= 96
        assert row[3] == "https://example.test/fact-row"
        assert row[4] is None
        assert row[5] is None

        # Attestation log has exactly one row.
        log_count = conn.execute(
            "SELECT COUNT(*) FROM am_fact_attestation_log "
            "WHERE fact_id='fact_alpha'"
        ).fetchone()[0]
        assert log_count == 1
    finally:
        conn.close()


def test_etl_idempotent_on_unchanged(
    tmp_path: pathlib.Path, ed25519_keypair, monkeypatch
) -> None:
    """Running the ETL twice produces ONE attestation log row.

    The second tick must observe unchanged metadata and NOT append a
    duplicate attestation event.
    """
    _priv, _pub, seed_hex = ed25519_keypair
    db = _fresh_db(tmp_path)
    _seed_signed_fact(db, "fact_beta")

    monkeypatch.setenv("AUTONOMATH_DB_PATH", str(db))
    monkeypatch.setenv("AUTONOMATH_FACT_SIGN_PRIVATE_KEY", seed_hex)

    etl = _import_etl_module()
    assert etl.main([]) == 0
    assert etl.main([]) == 0  # second tick

    conn = sqlite3.connect(str(db))
    try:
        log_count = conn.execute(
            "SELECT COUNT(*) FROM am_fact_attestation_log "
            "WHERE fact_id='fact_beta'"
        ).fetchone()[0]
        assert log_count == 1, (
            "second ETL tick must NOT append a duplicate attestation row"
        )
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Case 4 — Ed25519 sign/verify roundtrip + tamper detection
# ---------------------------------------------------------------------------


def test_ed25519_sign_verify_roundtrip(
    tmp_path: pathlib.Path, ed25519_keypair, monkeypatch
) -> None:
    """An honest verifier with the public key accepts ETL signatures."""
    priv, pub, seed_hex = ed25519_keypair
    db = _fresh_db(tmp_path)
    _seed_signed_fact(db, "fact_gamma")

    monkeypatch.setenv("AUTONOMATH_DB_PATH", str(db))
    monkeypatch.setenv("AUTONOMATH_FACT_SIGN_PRIVATE_KEY", seed_hex)

    etl = _import_etl_module()
    assert etl.main([]) == 0

    conn = sqlite3.connect(str(db))
    try:
        row = conn.execute(
            "SELECT signature_hex FROM am_fact_attestation_log "
            "WHERE fact_id='fact_gamma'"
        ).fetchone()
        assert row is not None
        sig_bytes = bytes.fromhex(row[0])

        meta = conn.execute(
            "SELECT source_doc, extracted_at, verified_by, "
            "confidence_lower, confidence_upper "
            "FROM am_fact_metadata WHERE fact_id='fact_gamma'"
        ).fetchone()
        payload = etl._canonical_metadata_payload(
            "fact_gamma", meta[0], meta[1], meta[2], meta[3], meta[4]
        )

        # honest verify
        pub.verify(sig_bytes, payload)

        # tamper -> verify raises
        from cryptography.exceptions import InvalidSignature

        tampered = payload.replace(b"fact_gamma", b"fact_evil!")
        with pytest.raises(InvalidSignature):
            pub.verify(sig_bytes, tampered)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Case 5 — ETL does NOT mutate am_fact_signature (migration 262 substrate)
# ---------------------------------------------------------------------------


def test_etl_never_touches_am_fact_signature(
    tmp_path: pathlib.Path, ed25519_keypair, monkeypatch
) -> None:
    _priv, _pub, seed_hex = ed25519_keypair
    db = _fresh_db(tmp_path)
    _seed_signed_fact(db, "fact_delta")

    conn = sqlite3.connect(str(db))
    try:
        before = conn.execute(
            "SELECT ed25519_sig, payload_sha256 FROM am_fact_signature "
            "WHERE fact_id='fact_delta'"
        ).fetchone()
    finally:
        conn.close()

    monkeypatch.setenv("AUTONOMATH_DB_PATH", str(db))
    monkeypatch.setenv("AUTONOMATH_FACT_SIGN_PRIVATE_KEY", seed_hex)
    etl = _import_etl_module()
    assert etl.main([]) == 0

    conn = sqlite3.connect(str(db))
    try:
        after = conn.execute(
            "SELECT ed25519_sig, payload_sha256 FROM am_fact_signature "
            "WHERE fact_id='fact_delta'"
        ).fetchone()
    finally:
        conn.close()

    assert before == after, "ETL must never mutate am_fact_signature"


# ---------------------------------------------------------------------------
# Case 6 — Append-only log on metadata change
# ---------------------------------------------------------------------------


def test_attestation_log_appends_on_change(
    tmp_path: pathlib.Path, ed25519_keypair, monkeypatch
) -> None:
    """When metadata changes, a new attestation row appends (no UPDATE)."""
    _priv, _pub, seed_hex = ed25519_keypair
    db = _fresh_db(tmp_path)
    _seed_signed_fact(db, "fact_epsilon")

    monkeypatch.setenv("AUTONOMATH_DB_PATH", str(db))
    monkeypatch.setenv("AUTONOMATH_FACT_SIGN_PRIVATE_KEY", seed_hex)

    etl = _import_etl_module()
    assert etl.main([]) == 0

    # Mutate the signed_at to force a metadata change on second tick.
    conn = sqlite3.connect(str(db))
    try:
        conn.execute(
            "UPDATE am_fact_signature SET signed_at='2026-06-01T00:00:00Z' "
            "WHERE fact_id='fact_epsilon'"
        )
        conn.commit()
    finally:
        conn.close()

    assert etl.main([]) == 0  # second tick

    conn = sqlite3.connect(str(db))
    try:
        log_count = conn.execute(
            "SELECT COUNT(*) FROM am_fact_attestation_log "
            "WHERE fact_id='fact_epsilon'"
        ).fetchone()[0]
        assert log_count == 2, (
            "metadata change must APPEND a new attestation row "
            "(append-only audit log)"
        )
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Case 7 — Boot manifest integration
# ---------------------------------------------------------------------------


def test_boot_manifest_jpcite_registers_275() -> None:
    text = MANIFEST_JPCITE.read_text(encoding="utf-8")
    assert "275_explainable_fact.sql" in text, (
        "jpcite_boot_manifest.txt must register migration 275"
    )


def test_boot_manifest_autonomath_registers_275() -> None:
    text = MANIFEST_AM.read_text(encoding="utf-8")
    assert "275_explainable_fact.sql" in text, (
        "autonomath_boot_manifest.txt must register migration 275"
    )


# ---------------------------------------------------------------------------
# Case 8 — No LLM SDK in ETL
# ---------------------------------------------------------------------------


def test_etl_no_llm_imports() -> None:
    src = ETL_BUILD.read_text(encoding="utf-8")
    banned = ("anthropic", "openai", "google.generativeai", "claude_agent_sdk")
    for needle in banned:
        pattern = rf"^\s*(import|from)\s+{re.escape(needle)}\b"
        assert not re.search(pattern, src, re.MULTILINE), (
            f"LLM SDK import detected in ETL: {needle}"
        )


def test_etl_no_legacy_brand_in_user_facing() -> None:
    """Default verified_by string must not surface legacy brand."""
    src = ETL_BUILD.read_text(encoding="utf-8")
    # Allow autonomath in DB path env (operational) but NOT legacy brand.
    assert "税務会計AI" not in src
    assert "zeimu-kaikei.ai" not in src
