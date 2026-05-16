"""Wave 49 tick#2 — provenance backfill v2 ETL schema sanity tests.

The Dim O provenance backfill v2 ETL
(``scripts/etl/provenance_backfill_6M_facts_v2.py``) had a latent schema
mismatch shipped in Wave 49 tick#3 (the cron-workflow wiring tick):

  * The script's ``_walk()`` cursor SELECT used
    ``SELECT fact_id FROM am_entity_facts``, but the canonical
    ``am_entity_facts`` PK column is ``id`` (migration 049 + the
    canonical CREATE TABLE in ``tests/test_evidence_packet.py``).
  * That meant any non-dry-run invocation would crash with
    ``sqlite3.OperationalError: no such column: fact_id`` at the
    very first batch SELECT — backfill never advanced beyond row 0.
  * The dry-run trigger that landed in Wave 49 tick#3's workflow
    masked the bug because dry-run still issues the same cursor
    SELECT and would also have failed if the test corpus contained
    any row — but the workflow was only ever fired against the
    smoke-stub schema, so the prod-DB shape was never exercised
    in CI.

This Wave 49 tick#2 schema-shape test catches the regression class:

  1. ``am_entity_facts`` PK is ``id`` (NOT ``fact_id``); the ETL
     walker MUST SELECT/ORDER/WHERE on ``id``.
  2. ``am_fact_metadata.fact_id`` IS the canonical column
     (migration 275) — those references stay as-is.
  3. ``am_fact_attestation_log.fact_id`` is also the canonical FK
     column (migration 275).
  4. ``--dry-run`` gate: the walker must NOT INSERT/UPDATE when
     ``--dry-run`` is set, and the ``unchanged``/``upserted`` count
     must increment normally (so the workflow's smoke-tick still
     reports a non-zero touched-row count).

Hard constraints (memory):
  * no LLM call — pure sqlite3 + subprocess. ``feedback_no_operator_llm_api``.
  * no ``PRAGMA quick_check`` — synthetic in-memory DB only.
    ``feedback_no_quick_check_on_huge_sqlite``.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sqlite3

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
ETL_SCRIPT = REPO_ROOT / "scripts" / "etl" / "provenance_backfill_6M_facts_v2.py"


@pytest.fixture()
def _etl_module():
    """Load the ETL module from its file path (it lives under scripts/etl/)."""
    spec = importlib.util.spec_from_file_location("_prov_backfill_v2", ETL_SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def _seeded_conn() -> sqlite3.Connection:
    """In-memory DB with the canonical am_entity_facts + am_fact_metadata
    + am_fact_attestation_log + am_source schema, seeded with 3 facts."""
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE am_source (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            source_url   TEXT NOT NULL UNIQUE,
            license      TEXT
        );
        CREATE TABLE am_entity_facts (
            id                       INTEGER PRIMARY KEY AUTOINCREMENT,
            entity_id                TEXT NOT NULL,
            field_name               TEXT NOT NULL,
            field_value_text         TEXT,
            field_kind               TEXT NOT NULL DEFAULT 'text',
            source_id                INTEGER REFERENCES am_source(id),
            confidence               REAL,
            created_at               TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE am_fact_metadata (
            fact_id              TEXT PRIMARY KEY,
            source_doc           TEXT,
            extracted_at         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
            verified_by          TEXT,
            confidence_lower     REAL,
            confidence_upper     REAL,
            ed25519_sig          BLOB NOT NULL,
            notes                TEXT,
            created_at           TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
            updated_at           TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
            CONSTRAINT ck_am_fact_meta_sig_size_min CHECK (length(ed25519_sig) >= 64)
        );
        CREATE TABLE am_fact_attestation_log (
            attestation_id    INTEGER PRIMARY KEY AUTOINCREMENT,
            fact_id           TEXT NOT NULL,
            attester          TEXT NOT NULL,
            signed_at         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
            signature_hex     TEXT NOT NULL,
            notes             TEXT
        );
        """
    )
    conn.executemany(
        "INSERT INTO am_entity_facts(id, entity_id, field_name, "
        "field_value_text, source_id, confidence) VALUES (?,?,?,?,?,?)",
        [
            (1, "ent-a", "k1", "v1", None, 0.5),
            (2, "ent-a", "k2", "v2", None, 0.7),
            (3, "ent-b", "k1", "v3", None, None),
        ],
    )
    conn.commit()
    return conn


def test_am_entity_facts_pk_is_id_not_fact_id(_seeded_conn) -> None:
    """Canonical am_entity_facts PK column is `id`, NOT `fact_id`.

    This is the schema axis the Wave 49 tick#2 fix encodes — the ETL
    walker MUST cursor-paginate on `id`, not `fact_id`.
    """
    cols = {row[1] for row in _seeded_conn.execute("PRAGMA table_info(am_entity_facts)")}
    assert "id" in cols, "am_entity_facts must have `id` column (PK)"
    assert "fact_id" not in cols, (
        "am_entity_facts must NOT have `fact_id` column (Wave 49 tick#2 regression-class guard)"
    )


def test_am_fact_metadata_has_fact_id_column(_seeded_conn) -> None:
    """am_fact_metadata.fact_id IS the canonical PK column (migration 275).
    The ETL must keep using `fact_id` when writing to this table."""
    cols = {row[1] for row in _seeded_conn.execute("PRAGMA table_info(am_fact_metadata)")}
    assert "fact_id" in cols
    assert "id" not in cols


def test_etl_script_uses_id_for_am_entity_facts(_etl_module) -> None:
    """The ETL source MUST NOT contain `am_entity_facts WHERE fact_id`
    or `SELECT fact_id FROM am_entity_facts` — both are schema-mismatch
    regressions."""
    src = ETL_SCRIPT.read_text(encoding="utf-8")
    forbidden = [
        "am_entity_facts WHERE fact_id",
        "SELECT fact_id FROM am_entity_facts",
        "ORDER BY fact_id ASC",  # tied to the walker cursor SELECT
    ]
    for needle in forbidden:
        assert needle not in src, f"forbidden schema-mismatch pattern present in ETL: {needle!r}"


def test_walker_dry_run_does_not_write(_etl_module, _seeded_conn) -> None:
    """`--dry-run` walker must NOT INSERT a row into am_fact_metadata
    or am_fact_attestation_log, but MUST still count touched rows."""
    counts = _etl_module._walk(
        _seeded_conn,
        priv_key=None,
        max_rows=0,
        chunk_size=10,
        dry_run=True,
    )
    # No commits, no rows persisted.
    meta_n = _seeded_conn.execute("SELECT COUNT(*) FROM am_fact_metadata").fetchone()[0]
    log_n = _seeded_conn.execute("SELECT COUNT(*) FROM am_fact_attestation_log").fetchone()[0]
    assert meta_n == 0
    assert log_n == 0
    # Walker MUST have visited every seeded fact (3 rows) and returned
    # a per-row outcome (upserted in dry-run mode).
    assert counts["upserted"] == 3
    assert counts["errors"] == 0


def test_walker_non_dry_run_writes_with_placeholder_sig(_etl_module, _seeded_conn) -> None:
    """Non-dry-run path with no priv_key MUST still write metadata rows
    using the 64-byte zero-pad placeholder signature (mig 275 CHECK
    >= 64 satisfied)."""
    counts = _etl_module._walk(
        _seeded_conn,
        priv_key=None,
        max_rows=0,
        chunk_size=10,
        dry_run=False,
    )
    meta_n = _seeded_conn.execute("SELECT COUNT(*) FROM am_fact_metadata").fetchone()[0]
    log_n = _seeded_conn.execute("SELECT COUNT(*) FROM am_fact_attestation_log").fetchone()[0]
    assert meta_n == 3
    assert log_n == 3
    assert counts["upserted"] == 3
    # Re-run must be idempotent: all rows now `unchanged` (source_doc
    # is NULL for synthetic seeds, so v2's COALESCE keeps NULL — but
    # the source_doc IS NULL gate is "fill if NULL", which means
    # second pass still tries to UPSERT — verify the row count stays
    # at 3 (no duplicates from ON CONFLICT).
    counts2 = _etl_module._walk(
        _seeded_conn,
        priv_key=None,
        max_rows=0,
        chunk_size=10,
        dry_run=False,
    )
    meta_n2 = _seeded_conn.execute("SELECT COUNT(*) FROM am_fact_metadata").fetchone()[0]
    assert meta_n2 == 3  # no duplicates
    # attestation_log is append-only by design (mig 275) — second pass
    # appends another 3 rows, so total grows.
    log_n2 = _seeded_conn.execute("SELECT COUNT(*) FROM am_fact_attestation_log").fetchone()[0]
    assert log_n2 >= log_n
    assert counts2["errors"] == 0
