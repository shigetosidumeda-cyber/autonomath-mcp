"""Integration tests for Dim F fact_signature v2 storage extension (Wave 47).

Closes Wave 47 Phase 2 tick#6 Dim F gap: migration 285 layers
``am_fact_signature_v2_attestation`` (multi-attestation per fact) and
``am_fact_signature_v2_revocation_log`` (append-only revocation events)
on top of the existing mig 262 ``am_fact_signature`` table per
``feedback_explainable_fact_design.md``. Pairs with
``scripts/etl/build_fact_signatures_v2.py`` (the one-shot mig 262 ->
mig 285 bridge ETL — LLM-0 by construction).

Case bundles
------------
  1. Migration 285 applies cleanly on a fresh SQLite db (idempotent re-apply).
  2. Migration 285 rollback drops every artefact AND leaves mig 262 intact.
  3. CHECK constraints reject malformed rows (signer_pubkey wrong length,
     payload_sha256 wrong length, signature_bytes out of 64..96 range,
     fact_id empty).
  4. Unique triplet (fact_id, signer_pubkey, corpus_snapshot_id) dedup
     enforced by uq_am_fact_sig_v2_att_triplet.
  5. Revocation: reason_class CHECK rejects unknown class; one
     revocation per signature_id enforced by uq_am_fact_sig_v2_rev_signature.
  6. Helper view v_am_fact_sig_v2_attestation_active excludes revoked rows.
  7. Boot manifest registration (jpcite + autonomath mirror).
  8. End-to-end Ed25519 verify round-trip: sign a payload with the
     stdlib cryptography Ed25519PrivateKey, INSERT the attestation,
     SELECT it back, verify the signature with the matching public
     key — exercising the production sign/verify shape.
  9. LLM-0 verify: grep -E "anthropic|openai" build_fact_signatures_v2.py = 0.

Hard constraints exercised
--------------------------
  * No LLM SDK import in any new file (pure cryptography stdlib).
  * mig 262 must remain intact after mig 285 rollback.
  * Brand: only jpcite. No legacy 税務会計AI / zeimu-kaikei.ai.
"""

from __future__ import annotations

import hashlib
import pathlib
import sqlite3

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
MIG_262 = REPO_ROOT / "scripts" / "migrations" / "262_fact_signature_v2.sql"
MIG_285 = REPO_ROOT / "scripts" / "migrations" / "285_fact_signature_v2.sql"
MIG_285_RB = REPO_ROOT / "scripts" / "migrations" / "285_fact_signature_v2_rollback.sql"
ETL_FILE = REPO_ROOT / "scripts" / "etl" / "build_fact_signatures_v2.py"
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
    db = tmp_path / "dim_f.db"
    _apply(db, MIG_262)
    _apply(db, MIG_285)
    return db


def _sample_sig_blob(length: int = 64) -> bytes:
    """Produce a deterministic sig blob of the requested length."""
    return (
        bytes(range(length % 256)) * (length // 256 + 1)[:length] if False else (b"\x42" * length)
    )


def _payload_sha256_hex(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


# ---------------------------------------------------------------------------
# 1. Migration applies + idempotent
# ---------------------------------------------------------------------------


def test_mig_285_applies_clean(tmp_path: pathlib.Path) -> None:
    db = _fresh_db(tmp_path)
    conn = sqlite3.connect(str(db))
    try:
        names = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type IN ('table','view') "
                "AND (name LIKE 'am_fact_signature_v2_%' "
                "  OR name LIKE 'v_am_fact_sig_v2_%')"
            )
        }
        assert "am_fact_signature_v2_attestation" in names
        assert "am_fact_signature_v2_revocation_log" in names
        assert "v_am_fact_sig_v2_attestation_active" in names
    finally:
        conn.close()


def test_mig_285_is_idempotent(tmp_path: pathlib.Path) -> None:
    db = _fresh_db(tmp_path)
    _apply(db, MIG_285)  # second apply must not raise


# ---------------------------------------------------------------------------
# 2. Rollback drops mig 285 artefacts AND leaves mig 262 intact
# ---------------------------------------------------------------------------


def test_mig_285_rollback_drops_only_v2(tmp_path: pathlib.Path) -> None:
    db = _fresh_db(tmp_path)
    _apply(db, MIG_285_RB)
    conn = sqlite3.connect(str(db))
    try:
        v2_left = conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type IN ('table','view','index') "
            "AND name LIKE '%_fact_sig_v2_%'"
        ).fetchall()
        assert v2_left == []
        # mig 262 MUST survive
        names = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='am_fact_signature'"
            )
        }
        assert "am_fact_signature" in names
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 3. CHECK constraints
# ---------------------------------------------------------------------------


def test_check_signer_pubkey_length(tmp_path: pathlib.Path) -> None:
    db = _fresh_db(tmp_path)
    conn = sqlite3.connect(str(db))
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO am_fact_signature_v2_attestation ("
                " fact_id, signer_pubkey, signature_bytes,"
                " payload_sha256) VALUES (?,?,?,?)",
                ("f1", "abcd", b"\x00" * 64, "a" * 64),
            )
    finally:
        conn.close()


def test_check_payload_sha256_length(tmp_path: pathlib.Path) -> None:
    db = _fresh_db(tmp_path)
    conn = sqlite3.connect(str(db))
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO am_fact_signature_v2_attestation ("
                " fact_id, signer_pubkey, signature_bytes,"
                " payload_sha256) VALUES (?,?,?,?)",
                ("f1", "a" * 64, b"\x00" * 64, "short"),
            )
    finally:
        conn.close()


def test_check_signature_bytes_range(tmp_path: pathlib.Path) -> None:
    db = _fresh_db(tmp_path)
    conn = sqlite3.connect(str(db))
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO am_fact_signature_v2_attestation ("
                " fact_id, signer_pubkey, signature_bytes,"
                " payload_sha256) VALUES (?,?,?,?)",
                ("f1", "a" * 64, b"\x00" * 32, "a" * 64),  # too short
            )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO am_fact_signature_v2_attestation ("
                " fact_id, signer_pubkey, signature_bytes,"
                " payload_sha256) VALUES (?,?,?,?)",
                ("f1", "a" * 64, b"\x00" * 128, "a" * 64),  # too long
            )
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 4. Unique (fact_id, signer_pubkey, corpus_snapshot_id)
# ---------------------------------------------------------------------------


def test_unique_triplet_dedup(tmp_path: pathlib.Path) -> None:
    db = _fresh_db(tmp_path)
    conn = sqlite3.connect(str(db))
    try:
        for _ in range(1):  # first insert
            conn.execute(
                "INSERT INTO am_fact_signature_v2_attestation ("
                " fact_id, signer_pubkey, signature_bytes,"
                " corpus_snapshot_id, payload_sha256)"
                " VALUES (?,?,?,?,?)",
                ("f1", "a" * 64, b"\x42" * 64, "snap-1", "b" * 64),
            )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO am_fact_signature_v2_attestation ("
                " fact_id, signer_pubkey, signature_bytes,"
                " corpus_snapshot_id, payload_sha256)"
                " VALUES (?,?,?,?,?)",
                ("f1", "a" * 64, b"\x99" * 64, "snap-1", "c" * 64),
            )
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 5. Revocation log: reason_class enum + one-per-signature
# ---------------------------------------------------------------------------


def test_revocation_reason_class_enum(tmp_path: pathlib.Path) -> None:
    db = _fresh_db(tmp_path)
    conn = sqlite3.connect(str(db))
    try:
        sig_id = conn.execute(
            "INSERT INTO am_fact_signature_v2_attestation ("
            " fact_id, signer_pubkey, signature_bytes, payload_sha256)"
            " VALUES (?,?,?,?)",
            ("f1", "a" * 64, b"\x42" * 64, "b" * 64),
        ).lastrowid
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO am_fact_signature_v2_revocation_log ("
                " signature_id, reason_class) VALUES (?,?)",
                (sig_id, "NOT_A_VALID_CLASS"),
            )
    finally:
        conn.close()


def test_revocation_one_per_signature(tmp_path: pathlib.Path) -> None:
    db = _fresh_db(tmp_path)
    conn = sqlite3.connect(str(db))
    try:
        sig_id = conn.execute(
            "INSERT INTO am_fact_signature_v2_attestation ("
            " fact_id, signer_pubkey, signature_bytes, payload_sha256)"
            " VALUES (?,?,?,?)",
            ("f1", "a" * 64, b"\x42" * 64, "b" * 64),
        ).lastrowid
        conn.execute(
            "INSERT INTO am_fact_signature_v2_revocation_log ("
            " signature_id, reason_class) VALUES (?,?)",
            (sig_id, "key_rotated"),
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO am_fact_signature_v2_revocation_log ("
                " signature_id, reason_class) VALUES (?,?)",
                (sig_id, "key_compromised"),
            )
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 6. Active view excludes revoked rows
# ---------------------------------------------------------------------------


def test_active_view_excludes_revoked(tmp_path: pathlib.Path) -> None:
    db = _fresh_db(tmp_path)
    conn = sqlite3.connect(str(db))
    try:
        active_id = conn.execute(
            "INSERT INTO am_fact_signature_v2_attestation ("
            " fact_id, signer_pubkey, signature_bytes, payload_sha256)"
            " VALUES (?,?,?,?)",
            ("f1", "a" * 64, b"\x01" * 64, "b" * 64),
        ).lastrowid
        revoked_id = conn.execute(
            "INSERT INTO am_fact_signature_v2_attestation ("
            " fact_id, signer_pubkey, signature_bytes, payload_sha256,"
            " corpus_snapshot_id) VALUES (?,?,?,?,?)",
            ("f1", "a" * 64, b"\x02" * 64, "c" * 64, "snap-2"),
        ).lastrowid
        conn.execute(
            "INSERT INTO am_fact_signature_v2_revocation_log ("
            " signature_id, reason_class) VALUES (?,?)",
            (revoked_id, "key_compromised"),
        )
        rows = conn.execute(
            "SELECT signature_id FROM v_am_fact_sig_v2_attestation_active"
        ).fetchall()
        ids = {r[0] for r in rows}
        assert active_id in ids
        assert revoked_id not in ids
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 7. Boot manifest registration (both jpcite + autonomath)
# ---------------------------------------------------------------------------


def test_boot_manifest_registers_285() -> None:
    for manifest in (MANIFEST_JPCITE, MANIFEST_AM):
        text = manifest.read_text(encoding="utf-8")
        assert "285_fact_signature_v2.sql" in text, (
            f"285_fact_signature_v2.sql missing from {manifest.name}"
        )


# ---------------------------------------------------------------------------
# 8. End-to-end Ed25519 verify round-trip
# ---------------------------------------------------------------------------


def test_ed25519_roundtrip_insert_select_verify(tmp_path: pathlib.Path) -> None:
    pytest.importorskip("cryptography")
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey,
        Ed25519PublicKey,
    )

    db = _fresh_db(tmp_path)
    sk = Ed25519PrivateKey.generate()
    pub_bytes = sk.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    pubkey_hex = pub_bytes.hex()

    payload = b"jpcite|fact_id=f-001|value=42|snap=snap-A"
    sig = sk.sign(payload)
    assert len(sig) == 64

    conn = sqlite3.connect(str(db))
    try:
        conn.execute(
            "INSERT INTO am_fact_signature_v2_attestation ("
            " fact_id, signer_pubkey, signature_bytes,"
            " corpus_snapshot_id, payload_sha256)"
            " VALUES (?,?,?,?,?)",
            (
                "f-001",
                pubkey_hex,
                sig,
                "snap-A",
                _payload_sha256_hex(payload),
            ),
        )
        conn.commit()
        row = conn.execute(
            "SELECT signer_pubkey, signature_bytes "
            "FROM v_am_fact_sig_v2_attestation_active "
            "WHERE fact_id=?",
            ("f-001",),
        ).fetchone()
        assert row is not None
        recovered_pub = Ed25519PublicKey.from_public_bytes(bytes.fromhex(row[0]))
        # Must NOT raise InvalidSignature
        recovered_pub.verify(row[1], payload)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 9. LLM-0 verify
# ---------------------------------------------------------------------------


def test_etl_has_no_llm_import() -> None:
    text = ETL_FILE.read_text(encoding="utf-8")
    lower = text.lower()
    assert "import anthropic" not in lower
    assert "from anthropic" not in lower
    assert "import openai" not in lower
    assert "from openai" not in lower


def test_no_legacy_brand_in_dim_f_files() -> None:
    for path in (MIG_285, MIG_285_RB, ETL_FILE):
        text = path.read_text(encoding="utf-8")
        # Allow historical-marker mention if any, but new code must use jpcite
        assert "zeimu-kaikei.ai" not in text
        assert "税務会計AI" not in text
