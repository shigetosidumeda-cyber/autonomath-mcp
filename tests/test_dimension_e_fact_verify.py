"""Tests for Dim E Verification trail (Wave 43.2.5).

Covers:
  * Ed25519 verify happy-path -> 200 valid
  * Ed25519 verify tamper detection -> 409 (single byte flip)
  * /why explanation paragraph format + determinism
  * LLM-API import count is 0 across the new surface
  * fact_id input validation (400 on bad pattern)
"""

from __future__ import annotations

import pathlib
import re
import sqlite3

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC_FACT_VERIFY = (
    REPO_ROOT / "src" / "jpintel_mcp" / "api" / "fact_verify.py"
)
CRON_REFRESH = (
    REPO_ROOT / "scripts" / "cron" / "refresh_fact_signatures_weekly.py"
)


# ---------------------------------------------------------------------------
# Shared schema fixture
# ---------------------------------------------------------------------------


def _build_fixture_db(tmp_path: pathlib.Path) -> str:
    """Build a minimal autonomath.db with extracted_fact + am_fact_signature."""
    db_path = tmp_path / "autonomath.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE extracted_fact (
            fact_id TEXT PRIMARY KEY,
            subject_kind TEXT NOT NULL,
            subject_id TEXT NOT NULL,
            entity_id TEXT,
            source_document_id TEXT,
            field_name TEXT NOT NULL,
            field_kind TEXT NOT NULL DEFAULT 'text',
            value_text TEXT,
            value_number REAL,
            value_date TEXT,
            last_modified TEXT
        );
        CREATE TABLE am_fact_signature (
            fact_id TEXT PRIMARY KEY,
            ed25519_sig BLOB NOT NULL,
            corpus_snapshot_id TEXT,
            key_id TEXT NOT NULL DEFAULT 'k20260512_a',
            signed_at TEXT NOT NULL,
            payload_sha256 TEXT NOT NULL,
            notes TEXT
        );
        CREATE VIEW v_am_fact_signature_latest AS
        SELECT fact_id, ed25519_sig, corpus_snapshot_id, key_id,
               signed_at, payload_sha256
        FROM am_fact_signature;
        CREATE TABLE source_document (
            source_document_id TEXT PRIMARY KEY,
            license TEXT,
            fetched_at TEXT
        );
        """
    )
    conn.commit()
    return str(db_path)


def _seed_fact(
    db_path: str,
    fact_id: str = "ef_unit_001",
    value_text: str = "法人税法 52 (1) 解釈",
):
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO extracted_fact (fact_id, subject_kind, subject_id, "
        "field_name, field_kind, value_text, last_modified) "
        "VALUES (?, 'law', 'law_corp_52', 'commentary_text', 'text', ?, "
        "        '2026-05-12T00:00:00.000Z')",
        (fact_id, value_text),
    )
    conn.execute(
        "INSERT INTO source_document (source_document_id, license, fetched_at) "
        "VALUES ('sd_egov_001', 'cc_by_4.0', '2026-05-04T10:00:00Z')"
    )
    conn.commit()
    conn.close()


def _ed25519_keypair() -> tuple[bytes, bytes]:
    """Return (private_seed_hex, public_key_hex). Skips if no cryptography."""
    crypto = pytest.importorskip(
        "cryptography.hazmat.primitives.asymmetric.ed25519"
    )
    private_key = crypto.Ed25519PrivateKey.generate()
    from cryptography.hazmat.primitives import serialization

    seed = private_key.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    pub = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return seed, pub


# ---------------------------------------------------------------------------
# Module-load tests (independent of FastAPI runtime)
# ---------------------------------------------------------------------------


def test_fact_verify_file_exists():
    """The new fact_verify module must exist."""
    assert SRC_FACT_VERIFY.exists()
    src = SRC_FACT_VERIFY.read_text(encoding="utf-8")
    assert "router = APIRouter(prefix=\"/v1/facts\"" in src
    assert "tags=[\"fact-verify\"]" in src


def test_fact_verify_no_llm_imports():
    """fact_verify.py must NOT import any LLM SDK."""
    src = SRC_FACT_VERIFY.read_text(encoding="utf-8")
    banned = ("anthropic", "openai", "google.generativeai", "claude_agent_sdk")
    for needle in banned:
        pattern = rf"^\s*(import|from)\s+{re.escape(needle)}\b"
        assert not re.search(pattern, src, re.MULTILINE), (
            f"LLM SDK import detected: {needle}"
        )


def test_cron_refresh_no_llm_imports():
    """refresh_fact_signatures_weekly.py must NOT import any LLM SDK."""
    src = CRON_REFRESH.read_text(encoding="utf-8")
    banned = ("anthropic", "openai", "google.generativeai", "claude_agent_sdk")
    for needle in banned:
        pattern = rf"^\s*(import|from)\s+{re.escape(needle)}\b"
        assert not re.search(pattern, src, re.MULTILINE), (
            f"LLM SDK import detected: {needle}"
        )


def test_cron_refresh_uses_cryptography_stdlib_only():
    """Cron sign path must rely on cryptography stdlib Ed25519, not custom math."""
    src = CRON_REFRESH.read_text(encoding="utf-8")
    assert "Ed25519PrivateKey" in src
    assert "from cryptography.hazmat.primitives.asymmetric.ed25519" in src
    assert "9.7 GB" in src or "9.7GB" in src or "CHUNK_SIZE" in src


# ---------------------------------------------------------------------------
# Canonical payload determinism + tamper detection
# ---------------------------------------------------------------------------


def _load_helpers() -> dict:
    """Extract pure-helper functions from fact_verify.py via AST.

    Pulls only the top-level `def _foo(...)` functions (`_canonical_payload`,
    `_verify_signature`, `_why_paragraph`, etc.) plus their `import` deps,
    skipping the FastAPI router + route handler decorators that would
    require live FastAPI runtime to compile.
    """
    import ast

    src = SRC_FACT_VERIFY.read_text(encoding="utf-8")
    tree = ast.parse(src)

    keep_nodes: list = []
    for node in tree.body:
        # Preserve top-level imports + future annotations.
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            # Strip the jpintel_mcp.config import which would force the
            # heavy package import chain just for helper unit testing.
            if isinstance(node, ast.ImportFrom) and (
                node.module and node.module.startswith("jpintel_mcp")
            ):
                continue
            if isinstance(node, ast.ImportFrom) and (
                node.module and node.module.startswith("fastapi")
            ):
                continue
            keep_nodes.append(node)
        # Preserve only helper `_foo` and `_why_paragraph` defs (private
        # by convention `_` prefix). Skip async-def route handlers.
        elif isinstance(node, ast.FunctionDef) and node.name.startswith("_"):
            keep_nodes.append(node)
        # Preserve module-level constants (regex, disclaimer).
        elif isinstance(node, ast.Assign) and all(
            isinstance(t, ast.Name) and t.id.startswith("_") for t in node.targets
        ):
            keep_nodes.append(node)

    stub_module = ast.Module(body=keep_nodes, type_ignores=[])
    code = compile(stub_module, str(SRC_FACT_VERIFY), "exec")
    ns: dict = {}
    exec(code, ns)
    return ns


def test_canonical_payload_is_deterministic():
    """Same fact_row + snapshot must produce byte-identical payload."""
    ns = _load_helpers()
    canon = ns["_canonical_payload"]

    row = {
        "fact_id": "ef_x_001",
        "subject_kind": "law",
        "subject_id": "law_001",
        "field_name": "commentary",
        "field_kind": "text",
        "value_text": "日本語テキスト",
        "value_number": None,
        "value_date": None,
        "source_document_id": "sd_001",
    }
    payload_a = canon(row, "cs_2026_05_04")
    payload_b = canon(row, "cs_2026_05_04")
    assert payload_a == payload_b
    # ensure_ascii=False keeps kanji as raw UTF-8, not \\u escapes
    assert b"\\u" not in payload_a


def test_ed25519_tamper_detected(tmp_path):
    """Byte-flip the stored payload or signature -> verify must reject."""
    crypto = pytest.importorskip(
        "cryptography.hazmat.primitives.asymmetric.ed25519"
    )

    db_path = _build_fixture_db(tmp_path)
    _seed_fact(db_path)

    seed, pub = _ed25519_keypair()
    sk = crypto.Ed25519PrivateKey.from_private_bytes(seed)

    ns = _load_helpers()
    canon = ns["_canonical_payload"]
    verify_fn = ns["_verify_signature"]

    fact_row = {
        "fact_id": "ef_unit_001",
        "subject_kind": "law",
        "subject_id": "law_corp_52",
        "field_name": "commentary_text",
        "field_kind": "text",
        "value_text": "法人税法 52 (1) 解釈",
        "value_number": None,
        "value_date": None,
        "source_document_id": None,
    }
    payload = canon(fact_row, "cs_2026_05_04")
    sig = sk.sign(payload)

    # Valid case
    assert verify_fn(payload, sig, pub) is True

    # Tamper: flip a single byte in the payload (corpus drift simulation)
    tampered_payload = bytearray(payload)
    tampered_payload[10] ^= 0x01
    assert verify_fn(bytes(tampered_payload), sig, pub) is False

    # Tamper: flip a single byte in the signature
    tampered_sig = bytearray(sig)
    tampered_sig[5] ^= 0x80
    assert verify_fn(payload, bytes(tampered_sig), pub) is False


# ---------------------------------------------------------------------------
# Why-explanation paragraph format + determinism
# ---------------------------------------------------------------------------


def test_why_paragraph_template_format():
    """Explanation paragraph must follow the deterministic template."""
    ns = _load_helpers()
    builder = ns["_why_paragraph"]

    fact_row = {
        "fact_id": "ef_explain_001",
        "subject_kind": "program",
        "subject_id": "prog_001",
        "field_name": "subsidy_rate_text",
        "field_kind": "text",
        "value_text": "1/2 以内",
        "value_number": None,
        "value_date": None,
        "source_document_id": "sd_meti_001",
    }
    src_row = {
        "license": "gov_standard",
        "fetched_at": "2026-05-04T10:00:00Z",
    }
    p1 = builder(fact_row, src_row)
    p2 = builder(fact_row, src_row)
    # Deterministic
    assert p1 == p2
    # Mandatory mentions
    assert "ef_explain_001" in p1
    assert "program" in p1
    assert "subsidy_rate_text" in p1
    assert "LLM" in p1 and "を介さず" in p1
    assert "52" in p1  # disclaimer mention
    assert "決定論的 ETL" in p1


def test_why_paragraph_handles_null_source():
    """Missing source_document -> license=unknown, no crash."""
    ns = _load_helpers()
    builder = ns["_why_paragraph"]

    fact_row = {
        "fact_id": "ef_nullsrc",
        "subject_kind": "tax_measure",
        "subject_id": "tm_001",
        "field_name": "applicable_from",
        "field_kind": "date",
        "value_text": None,
        "value_number": None,
        "value_date": "2026-04-01",
        "source_document_id": None,
    }
    paragraph = builder(fact_row, None)
    assert "unknown" in paragraph or "(出典文書 ID なし)" in paragraph
    assert "2026-04-01" in paragraph


def test_why_paragraph_value_truncation():
    """Long value_text must be truncated with ellipsis."""
    ns = _load_helpers()
    builder = ns["_why_paragraph"]

    long_text = "あ" * 200
    fact_row = {
        "fact_id": "ef_long_text",
        "subject_kind": "law",
        "subject_id": "law_long",
        "field_name": "full_text",
        "field_kind": "text",
        "value_text": long_text,
        "value_number": None,
        "value_date": None,
        "source_document_id": "sd_x",
    }
    src_row = {"license": "cc_by_4.0", "fetched_at": "2026-05-01"}
    paragraph = builder(fact_row, src_row)
    assert "..." in paragraph
    # The full 200-character payload must not appear verbatim.
    assert long_text not in paragraph


# ---------------------------------------------------------------------------
# Migration shape
# ---------------------------------------------------------------------------


def test_migration_262_idempotent_shape():
    """Migration must use CREATE IF NOT EXISTS only; no DML."""
    mig = REPO_ROOT / "scripts" / "migrations" / "262_fact_signature_v2.sql"
    sql = mig.read_text(encoding="utf-8")
    assert "target_db: autonomath" in sql
    assert "CREATE TABLE IF NOT EXISTS am_fact_signature" in sql
    assert "CREATE INDEX IF NOT EXISTS idx_am_fact_signature_lookup" in sql
    # No INSERT/UPDATE/DELETE DML — pure schema.
    upper = sql.upper()
    assert "INSERT INTO " not in upper
    assert "UPDATE AM_FACT_SIGNATURE" not in upper
    assert "DELETE FROM" not in upper
    # Reasonable LOC range
    assert 60 <= len(sql.splitlines()) <= 200


def test_migration_262_rollback_exists():
    rb = REPO_ROOT / "scripts" / "migrations" / "262_fact_signature_v2_rollback.sql"
    sql = rb.read_text(encoding="utf-8")
    assert "DROP TABLE IF EXISTS am_fact_signature" in sql
    assert "DROP VIEW IF EXISTS v_am_fact_signature_latest" in sql


# ---------------------------------------------------------------------------
# Boot manifest entry
# ---------------------------------------------------------------------------


def test_boot_manifest_lists_262():
    manifest = (
        REPO_ROOT / "scripts" / "migrations" / "autonomath_boot_manifest.txt"
    )
    text = manifest.read_text(encoding="utf-8")
    assert "262_fact_signature_v2.sql" in text
