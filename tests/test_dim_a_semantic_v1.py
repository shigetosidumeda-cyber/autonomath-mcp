"""Tests for Dim A semantic search legacy v1 (Wave 47).

Covers:
  * migration 284 schema integrity (am_semantic_search_v1_cache +
    am_semantic_search_v1_log + indexes + CHECK constraints).
  * cache row write-rare-read-many semantics: cache_id PK, idempotent
    re-runs of the ETL skip duplicates instead of failing.
  * log row append-only semantics: search_id AUTOINCREMENT, cache_hit
    is 0|1, latency_ms >= 0, hit_count >= 0.
  * embedding integrity: length(BLOB) == embedding_dim * 4 (float32).
  * top_k_results is valid JSON array of {entity_id, score}.
  * LLM API import 0 in the ETL + migration namespace.
  * Disjoint from migration 260 (semantic_search_v2): the two table
    families are name-distinct (am_semantic_search_v1_* vs
    am_entities_vec_e5 / am_entities_vec_reranker_score).
"""

from __future__ import annotations

import json
import pathlib
import re
import sqlite3
import struct
import sys
import tempfile

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
MIG_PATH = REPO_ROOT / "scripts" / "migrations" / "284_semantic_search_v1.sql"
ROLLBACK_PATH = REPO_ROOT / "scripts" / "migrations" / "284_semantic_search_v1_rollback.sql"
ETL_PATH = REPO_ROOT / "scripts" / "etl" / "build_semantic_search_v1_cache.py"

# Ensure src/ on path for the ETL import.
_SRC = REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


@pytest.fixture
def db():
    path = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
    conn = sqlite3.connect(path)
    with MIG_PATH.open() as f:
        conn.executescript(f.read())
    yield conn
    conn.close()
    pathlib.Path(path).unlink(missing_ok=True)


def test_mig_284_creates_two_tables(db):
    tables = {
        r[0]
        for r in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name LIKE 'am_semantic_search_v1%'"
        )
    }
    assert tables == {"am_semantic_search_v1_cache", "am_semantic_search_v1_log"}


def test_mig_284_creates_three_indexes(db):
    indexes = {
        r[0]
        for r in db.execute(
            "SELECT name FROM sqlite_master WHERE type='index' "
            "AND name LIKE 'idx_am_semantic_search_v1%'"
        )
    }
    assert indexes == {
        "idx_am_semantic_search_v1_cache_cached_at",
        "idx_am_semantic_search_v1_log_query_hash",
        "idx_am_semantic_search_v1_log_searched_at",
    }


def test_cache_id_is_primary_key(db):
    cur = db.cursor()
    emb = struct.pack("<384f", *([0.1] * 384))
    cur.execute(
        "INSERT INTO am_semantic_search_v1_cache "
        "(cache_id, query_text, embedding, top_k_results) VALUES (?,?,?,?)",
        ("a" * 64, "test", emb, json.dumps([{"entity_id": 1, "score": 1.0}])),
    )
    with pytest.raises(sqlite3.IntegrityError):
        cur.execute(
            "INSERT INTO am_semantic_search_v1_cache "
            "(cache_id, query_text, embedding, top_k_results) VALUES (?,?,?,?)",
            ("a" * 64, "test", emb, "[]"),
        )


def test_top_k_check_constraint(db):
    cur = db.cursor()
    emb = struct.pack("<384f", *([0.1] * 384))
    with pytest.raises(sqlite3.IntegrityError):
        cur.execute(
            "INSERT INTO am_semantic_search_v1_cache "
            "(cache_id, query_text, embedding, top_k_results, top_k) VALUES (?,?,?,?,?)",
            ("b" * 64, "test", emb, "[]", 0),
        )


def test_log_cache_hit_boolean(db):
    cur = db.cursor()
    with pytest.raises(sqlite3.IntegrityError):
        cur.execute(
            "INSERT INTO am_semantic_search_v1_log "
            "(query_hash, latency_ms, cache_hit) VALUES (?,?,?)",
            ("hash", 10, 2),
        )


def test_log_latency_nonneg(db):
    cur = db.cursor()
    with pytest.raises(sqlite3.IntegrityError):
        cur.execute(
            "INSERT INTO am_semantic_search_v1_log "
            "(query_hash, latency_ms) VALUES (?,?)",
            ("hash", -1),
        )


def test_log_autoincrement(db):
    cur = db.cursor()
    for i in range(3):
        cur.execute(
            "INSERT INTO am_semantic_search_v1_log "
            "(query_hash, latency_ms, hit_count, cache_hit) VALUES (?,?,?,?)",
            (f"h{i}", i * 10, i, i % 2),
        )
    ids = [r[0] for r in cur.execute("SELECT search_id FROM am_semantic_search_v1_log")]
    assert ids == [1, 2, 3]


def test_embedding_dim_check(db):
    cur = db.cursor()
    emb = struct.pack("<384f", *([0.0] * 384))
    with pytest.raises(sqlite3.IntegrityError):
        cur.execute(
            "INSERT INTO am_semantic_search_v1_cache "
            "(cache_id, query_text, embedding, embedding_dim, top_k_results) "
            "VALUES (?,?,?,?,?)",
            ("c" * 64, "test", emb, 0, "[]"),
        )


def test_etl_idempotent(db, monkeypatch, tmp_path):
    """Running ETL twice writes the same rows; second run all skipped."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("build_v1", ETL_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    db_path = tmp_path / "etl.db"
    s1 = mod.build(str(db_path), top_n_queries=10, top_k=5, dry_run=False)
    s2 = mod.build(str(db_path), top_n_queries=10, top_k=5, dry_run=False)
    assert s1["rows_written"] >= 1
    assert s2["rows_skipped_dup"] == s1["rows_seen" if False else "queries_seen"]
    # Verify embedding integrity on the actual disk.
    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT length(embedding), embedding_dim FROM am_semantic_search_v1_cache"
    ).fetchall()
    for emb_len, dim in rows:
        assert emb_len == dim * 4
    conn.close()


def test_etl_top_k_results_is_valid_json(db, tmp_path):
    import importlib.util

    spec = importlib.util.spec_from_file_location("build_v1", ETL_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    db_path = tmp_path / "json.db"
    mod.build(str(db_path), top_n_queries=5, top_k=5, dry_run=False)
    conn = sqlite3.connect(db_path)
    for (raw,) in conn.execute("SELECT top_k_results FROM am_semantic_search_v1_cache"):
        parsed = json.loads(raw)
        assert isinstance(parsed, list)
        for item in parsed:
            assert "entity_id" in item and "score" in item
    conn.close()


def test_rollback_drops_everything():
    path = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
    conn = sqlite3.connect(path)
    with MIG_PATH.open() as f:
        conn.executescript(f.read())
    with ROLLBACK_PATH.open() as f:
        conn.executescript(f.read())
    leftover = list(
        conn.execute(
            "SELECT name FROM sqlite_master WHERE name LIKE 'am_semantic_search_v1%' "
            "OR name LIKE 'idx_am_semantic_search_v1%'"
        )
    )
    conn.close()
    pathlib.Path(path).unlink(missing_ok=True)
    assert leftover == []


def test_no_llm_api_import_in_etl():
    """feedback_no_operator_llm_api 遵守 — no anthropic / openai / etc."""
    forbidden = ("anthropic", "openai", "google.generativeai", "claude_agent_sdk")
    txt = ETL_PATH.read_text(encoding="utf-8")
    for needle in forbidden:
        assert re.search(rf"^\s*import\s+{re.escape(needle)}", txt, re.MULTILINE) is None
        assert re.search(rf"^\s*from\s+{re.escape(needle)}\s+import", txt, re.MULTILINE) is None


def test_no_overlap_with_mig_260():
    """Disjoint from semantic_search v2 — DDL (not comments) must not collide.

    The comment text in mig 284 is allowed to mention v2 names for
    cross-reference context, but no CREATE/INSERT/UPDATE/DROP statement
    may reference the v2 table names.
    """
    mig260 = (REPO_ROOT / "scripts" / "migrations" / "260_vec_e5_small_384.sql").read_text()
    mig284 = MIG_PATH.read_text()
    for name in ("am_semantic_search_v1_cache", "am_semantic_search_v1_log"):
        assert name not in mig260
    # Strip comment lines from mig 284 before name-collision check.
    ddl_lines = [
        ln for ln in mig284.splitlines() if not ln.lstrip().startswith("--")
    ]
    ddl = "\n".join(ddl_lines)
    for name in ("am_entities_vec_e5", "am_entities_vec_reranker_score"):
        assert name not in ddl, f"DDL must not reference v2 table {name}"
