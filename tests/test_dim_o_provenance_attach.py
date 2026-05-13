"""Wave 49 Dim O Phase 1 — provenance backfill v2 + attach middleware tests.

Exercises the additive 4-axis JSON-LD provenance envelope and the
``provenance_backfill_6M_facts_v2.py`` residual backfill against an
in-memory SQLite that mirrors migration 275 schema.

Hard contracts
--------------
* Migration 275 schema is honored (am_fact_metadata + am_fact_attestation_log +
  v_am_fact_explainability view).
* ``_provenance_attach.attach()`` adds a ``provenance`` block iff at least
  one fact_id resolves; otherwise the payload is returned unchanged.
* Soft-fail: missing DB / missing migration / unknown fact_id all return
  the payload unchanged (no exception).
* v2 backfill is idempotent (re-run on a converged sample writes 0 new rows).
* Append-only attestation log: every UPSERT appends one row (no UPDATE).
* No LLM SDK import in the new modules (regression guard).
"""

from __future__ import annotations

import importlib.util
import pathlib
import re
import sqlite3
import sys

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
MIG_275 = REPO_ROOT / "scripts" / "migrations" / "275_explainable_fact.sql"
ETL_V2 = (
    REPO_ROOT / "scripts" / "etl" / "provenance_backfill_6M_facts_v2.py"
)
MIDDLEWARE = (
    REPO_ROOT / "src" / "jpintel_mcp" / "api" / "_provenance_attach.py"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _bootstrap_db(db_path: str) -> None:
    """Apply migration 275 + minimal upstream schema for am_entity_facts."""
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS am_source (
                id         TEXT PRIMARY KEY,
                source_url TEXT
            );
            -- Canonical am_entity_facts PK column is `id` (NOT `fact_id`).
            -- Prod schema uses INTEGER PRIMARY KEY AUTOINCREMENT (migration
            -- 049 + test_evidence_packet). This stub uses TEXT to keep the
            -- pre-existing "F-test-001"-style identifier seeding ergonomic;
            -- the walker SELECTs `id` (column name) and passes the value
            -- through verbatim regardless of declared type, so the ETL
            -- code path under test is identical. The Wave 49 tick#2 fix
            -- only changed the column NAME (`fact_id` → `id`); the
            -- column TYPE is exercised in tests/test_provenance_etl_id_schema.py.
            CREATE TABLE IF NOT EXISTS am_entity_facts (
                id         TEXT PRIMARY KEY,
                source_url TEXT,
                source_id  TEXT,
                created_at TEXT
            );
            """
        )
        conn.executescript(MIG_275.read_text(encoding="utf-8"))
        conn.commit()
    finally:
        conn.close()


def _seed_one(
    db_path: str,
    fact_id: str,
    *,
    source_url: str = "https://elaws.e-gov.go.jp/test/anchor",
    fact_source_url: str | None = None,
    with_metadata: bool = False,
) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT OR REPLACE INTO am_source(id, source_url) VALUES (?, ?)",
            (f"src_{fact_id}", source_url),
        )
        # Stub PK column is `id` (matches canonical prod schema). The
        # textual fact_id ("F-test-001" etc.) is stored in the INTEGER id
        # via SQLite type affinity — PK still unique by content. The ETL
        # walker SELECTs `id` and feeds the value forward into
        # am_fact_metadata.fact_id (TEXT, mig 275) verbatim.
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
        if with_metadata:
            conn.execute(
                """
                INSERT INTO am_fact_metadata
                    (fact_id, source_doc, extracted_at, verified_by,
                     confidence_lower, confidence_upper, ed25519_sig)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    fact_id,
                    source_url,
                    "2026-05-12T00:00:00.000Z",
                    "preseed",
                    0.85,
                    0.95,
                    b"\x00" * 64,
                ),
            )
        conn.commit()
    finally:
        conn.close()


def _import_etl():
    spec = importlib.util.spec_from_file_location(
        "provenance_backfill_v2", ETL_V2
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _import_middleware():
    spec = importlib.util.spec_from_file_location(
        "_provenance_attach", MIDDLEWARE
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def tmp_db(tmp_path: pathlib.Path) -> str:
    db = tmp_path / "autonomath.db"
    _bootstrap_db(str(db))
    return str(db)


# ---------------------------------------------------------------------------
# Middleware: attach()
# ---------------------------------------------------------------------------


def test_attach_adds_4_axis_provenance(tmp_db: str) -> None:
    fact_id = "F-test-001"
    _seed_one(tmp_db, fact_id, with_metadata=True)
    mw = _import_middleware()
    payload = {"results": [{"fact_id": fact_id, "value": 42}]}
    out = mw.attach(payload, db_path=tmp_db)
    assert "provenance" in out
    prov = out["provenance"]
    assert prov["@context"] == "https://schema.org/"
    assert prov["@type"] == "Dataset"
    assert isinstance(prov["facts"], list) and len(prov["facts"]) == 1
    fact = prov["facts"][0]
    for axis in ("source_doc", "extracted_at", "verified_by"):
        assert axis in fact, f"missing 4-axis field: {axis}"
    assert fact["confidence"]["lower"] == pytest.approx(0.85)
    assert fact["confidence"]["upper"] == pytest.approx(0.95)
    assert fact["ed25519_sig_present"] is True
    # original payload not mutated
    assert "provenance" not in payload


def test_attach_returns_unchanged_when_no_fact_ids(tmp_db: str) -> None:
    mw = _import_middleware()
    payload = {"hello": "world"}
    out = mw.attach(payload, db_path=tmp_db)
    assert out == payload
    assert "provenance" not in out


def test_attach_soft_fails_on_unknown_fact_id(tmp_db: str) -> None:
    mw = _import_middleware()
    payload = {"fact_id": "F-does-not-exist"}
    out = mw.attach(payload, db_path=tmp_db)
    # no metadata row -> payload returned unchanged (no empty sidecar)
    assert out == payload


def test_attach_soft_fails_on_missing_db(tmp_path: pathlib.Path) -> None:
    mw = _import_middleware()
    payload = {"fact_id": "F-x"}
    bogus = tmp_path / "nope.db"
    out = mw.attach(payload, db_path=str(bogus))
    assert out == payload


def test_attach_extracts_top_level_and_list(tmp_db: str) -> None:
    _seed_one(tmp_db, "F-a", with_metadata=True)
    _seed_one(tmp_db, "F-b", with_metadata=True)
    mw = _import_middleware()
    payload = {
        "fact_id": "F-a",
        "fact_ids": ["F-b"],
        "results": [{"fact_id": "F-a"}, {"fact_id": "F-b"}],
    }
    out = mw.attach(payload, db_path=tmp_db)
    assert "provenance" in out
    ids = sorted(f["fact_id"] for f in out["provenance"]["facts"])
    assert ids == ["F-a", "F-b"]  # deduped


# ---------------------------------------------------------------------------
# ETL v2: provenance_backfill_6M_facts_v2.py
# ---------------------------------------------------------------------------


def test_etl_v2_backfills_missing_metadata(tmp_db: str, monkeypatch: pytest.MonkeyPatch) -> None:
    _seed_one(
        tmp_db,
        "F-1",
        with_metadata=False,
        fact_source_url="https://example.test/fact-row-source",
    )
    _seed_one(
        tmp_db,
        "F-2",
        with_metadata=False,
        source_url="https://example.test/source-table-source",
    )
    monkeypatch.setenv("AUTONOMATH_DB_PATH", tmp_db)
    monkeypatch.delenv("AUTONOMATH_FACT_SIGN_PRIVATE_KEY", raising=False)
    mod = _import_etl()
    rc = mod.main(["--chunk-size", "100"])
    assert rc == 0

    conn = sqlite3.connect(tmp_db)
    try:
        n = conn.execute(
            "SELECT COUNT(*) FROM am_fact_metadata WHERE fact_id IN ('F-1','F-2')"
        ).fetchone()[0]
        assert n == 2
        # Current EAV has no confidence column; ETL must store NULL bands cleanly.
        row = conn.execute(
            "SELECT source_doc, confidence_lower, confidence_upper "
            "FROM am_fact_metadata WHERE fact_id='F-1'"
        ).fetchone()
        assert row[0] == "https://example.test/fact-row-source"
        assert row[1] is None
        assert row[2] is None
        # When f.source_url is NULL, source_doc falls back to am_source.source_url.
        row = conn.execute(
            "SELECT source_doc FROM am_fact_metadata WHERE fact_id='F-2'"
        ).fetchone()
        assert row[0] == "https://example.test/source-table-source"
        # attestation log appended one row per UPSERT
        n_log = conn.execute(
            "SELECT COUNT(*) FROM am_fact_attestation_log WHERE fact_id IN ('F-1','F-2')"
        ).fetchone()[0]
        assert n_log == 2
    finally:
        conn.close()


def test_etl_v2_idempotent(tmp_db: str, monkeypatch: pytest.MonkeyPatch) -> None:
    _seed_one(tmp_db, "F-3", with_metadata=False)
    monkeypatch.setenv("AUTONOMATH_DB_PATH", tmp_db)
    monkeypatch.delenv("AUTONOMATH_FACT_SIGN_PRIVATE_KEY", raising=False)
    mod = _import_etl()
    assert mod.main(["--chunk-size", "10"]) == 0
    # second run should not append again (source_doc now set)
    n_before = sqlite3.connect(tmp_db).execute(
        "SELECT COUNT(*) FROM am_fact_attestation_log"
    ).fetchone()[0]
    assert mod.main(["--chunk-size", "10"]) == 0
    n_after = sqlite3.connect(tmp_db).execute(
        "SELECT COUNT(*) FROM am_fact_attestation_log"
    ).fetchone()[0]
    assert n_before == n_after, "v2 must be idempotent on converged corpus"


def test_etl_v2_dry_run_writes_nothing(tmp_db: str, monkeypatch: pytest.MonkeyPatch) -> None:
    _seed_one(tmp_db, "F-4", with_metadata=False)
    monkeypatch.setenv("AUTONOMATH_DB_PATH", tmp_db)
    mod = _import_etl()
    assert mod.main(["--dry-run", "--chunk-size", "10"]) == 0
    n = sqlite3.connect(tmp_db).execute(
        "SELECT COUNT(*) FROM am_fact_metadata"
    ).fetchone()[0]
    assert n == 0


def test_etl_v2_signature_optional(tmp_db: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """Without AUTONOMATH_FACT_SIGN_PRIVATE_KEY, placeholder sig still meets CHECK >= 64."""
    _seed_one(tmp_db, "F-5", with_metadata=False)
    monkeypatch.setenv("AUTONOMATH_DB_PATH", tmp_db)
    monkeypatch.delenv("AUTONOMATH_FACT_SIGN_PRIVATE_KEY", raising=False)
    mod = _import_etl()
    rc = mod.main(["--chunk-size", "10"])
    assert rc == 0
    sig_len = sqlite3.connect(tmp_db).execute(
        "SELECT length(ed25519_sig) FROM am_fact_metadata WHERE fact_id='F-5'"
    ).fetchone()[0]
    assert sig_len >= 64  # honors am_fact_metadata CHECK constraint


def test_etl_v2_with_real_ed25519_key(tmp_db: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """Optional: when cryptography is available, real Ed25519 sign produces 64-byte raw sig."""
    cryptography = pytest.importorskip("cryptography")
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey,
    )

    _ = cryptography
    priv = Ed25519PrivateKey.generate()
    seed_hex = priv.private_bytes_raw().hex() if hasattr(priv, "private_bytes_raw") else None
    if seed_hex is None:
        from cryptography.hazmat.primitives import serialization

        seed_hex = priv.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        ).hex()

    _seed_one(tmp_db, "F-6", with_metadata=False)
    monkeypatch.setenv("AUTONOMATH_DB_PATH", tmp_db)
    monkeypatch.setenv("AUTONOMATH_FACT_SIGN_PRIVATE_KEY", seed_hex)
    mod = _import_etl()
    assert mod.main(["--chunk-size", "10"]) == 0
    sig_len = sqlite3.connect(tmp_db).execute(
        "SELECT length(ed25519_sig) FROM am_fact_metadata WHERE fact_id='F-6'"
    ).fetchone()[0]
    # prefixed shape = 8 + 64 + 8 = 80 bytes; <= 96 CHECK
    assert 64 <= sig_len <= 96


# ---------------------------------------------------------------------------
# Regression guards
# ---------------------------------------------------------------------------


def test_no_llm_sdk_import_in_new_modules() -> None:
    """Wave 49 cost-guard: never import anthropic/openai/etc."""
    pattern = re.compile(
        r"^\s*(?:from|import)\s+(anthropic|openai|cohere|mistralai|google\.generativeai)",
        re.MULTILINE,
    )
    for path in (ETL_V2, MIDDLEWARE):
        body = path.read_text(encoding="utf-8")
        assert pattern.search(body) is None, (
            f"LLM SDK import found in {path}"
        )


def test_etl_v2_never_touches_am_fact_signature(tmp_db: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """Regression: backfill must not mutate the Wave 43.2.5 substrate."""
    # Create am_fact_signature table empty
    conn = sqlite3.connect(tmp_db)
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS am_fact_signature ("
            "fact_id TEXT PRIMARY KEY, ed25519_sig BLOB, signed_at TEXT)"
        )
        conn.execute(
            "INSERT INTO am_fact_signature(fact_id, ed25519_sig, signed_at) "
            "VALUES ('F-sig-1', X'00', '2026-01-01T00:00:00Z')"
        )
        conn.commit()
    finally:
        conn.close()
    _seed_one(tmp_db, "F-sig-1", with_metadata=False)
    monkeypatch.setenv("AUTONOMATH_DB_PATH", tmp_db)
    mod = _import_etl()
    assert mod.main(["--chunk-size", "10"]) == 0
    row = sqlite3.connect(tmp_db).execute(
        "SELECT signed_at FROM am_fact_signature WHERE fact_id='F-sig-1'"
    ).fetchone()
    assert row[0] == "2026-01-01T00:00:00Z"  # untouched


def test_middleware_lookup_helper(tmp_db: str) -> None:
    _seed_one(tmp_db, "F-look-1", with_metadata=True)
    mw = _import_middleware()
    rows = mw.lookup(["F-look-1", "F-missing"], db_path=tmp_db)
    assert len(rows) == 1
    assert rows[0]["fact_id"] == "F-look-1"


if __name__ == "__main__":  # pragma: no cover
    sys.exit(pytest.main([__file__, "-v"]))
