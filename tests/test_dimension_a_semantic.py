"""Tests for Dim A semantic search v2 (Wave 43.2.1).

Covers:
  * migration 260 schema integrity (am_entities_vec_e5 vec0 + reranker_score
    cache + embed_log + refresh_log).
  * embed dimension == 384 (e5-small convention).
  * RRF fusion correctness (rank-reciprocal sum on synthetic FTS + vec).
  * reranker score persists as REAL with CHECK [-10, 10].
  * LLM API import 0 across the 4 new files.
  * sentence-transformers import is allowed (operator-local inference).
  * REST handler signature + MCP tool docstring shape.
"""

from __future__ import annotations

import ast
import pathlib
import re
import sqlite3
import sys

import pytest

# Ensure repo's src/ is on the path (works whether the test is run from
# the repo root or from a pytest CI runner under /tmp).
_REPO_SRC = pathlib.Path(__file__).resolve().parent.parent / "src"
if str(_REPO_SRC) not in sys.path:
    sys.path.insert(0, str(_REPO_SRC))

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
MIGRATION_PATH = REPO_ROOT / "scripts" / "migrations" / "260_vec_e5_small_384.sql"
ROLLBACK_PATH = (
    REPO_ROOT / "scripts" / "migrations" / "260_vec_e5_small_384_rollback.sql"
)
ETL_PATH = REPO_ROOT / "scripts" / "etl" / "build_e5_embeddings_v2.py"
REST_API_PATH = REPO_ROOT / "src" / "jpintel_mcp" / "api" / "semantic_search_v2.py"
MCP_TOOL_PATH = (
    REPO_ROOT / "src" / "jpintel_mcp" / "mcp" / "autonomath_tools" /
    "semantic_search_v2.py"
)
BOOT_MANIFEST = (
    REPO_ROOT / "scripts" / "migrations" / "autonomath_boot_manifest.txt"
)


@pytest.fixture
def vec_e5_schema(tmp_path):
    db = tmp_path / "am.db"
    conn = sqlite3.connect(str(db))
    try:
        conn.enable_load_extension(True)
        import sqlite_vec  # type: ignore[import-not-found]

        sqlite_vec.load(conn)
    except (ImportError, sqlite3.OperationalError, AttributeError):
        pass
    sql = MIGRATION_PATH.read_text(encoding="utf-8")
    try:
        conn.executescript(sql)
    except sqlite3.OperationalError:
        for stmt in sql.split(";"):
            s = stmt.strip()
            if not s or "USING vec0" in s:
                continue
            try:
                conn.execute(s)
            except sqlite3.OperationalError:
                pass
        conn.commit()
    yield conn
    conn.close()


def test_migration_260_exists():
    assert MIGRATION_PATH.exists(), f"missing {MIGRATION_PATH}"
    assert ROLLBACK_PATH.exists(), f"missing {ROLLBACK_PATH}"


def test_migration_260_target_db_marker():
    head = MIGRATION_PATH.read_text(encoding="utf-8").splitlines()[0]
    assert head.strip() == "-- target_db: autonomath"


def test_vec_table_declared_384_dim():
    text = MIGRATION_PATH.read_text(encoding="utf-8")
    assert "am_entities_vec_e5" in text
    assert "float[384]" in text
    assert "USING vec0" in text


def test_reranker_score_cache_table(vec_e5_schema):
    conn = vec_e5_schema
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name='am_entities_vec_reranker_score'"
    ).fetchone()
    assert row, "reranker score cache table missing"

    schema = conn.execute(
        "SELECT sql FROM sqlite_master WHERE name='am_entities_vec_reranker_score'"
    ).fetchone()[0]
    assert "score >= -10" in schema and "score <= 10" in schema


def test_embed_log_table(vec_e5_schema):
    conn = vec_e5_schema
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name='am_entities_vec_e5_embed_log'"
    ).fetchone()
    assert row
    schema = conn.execute(
        "SELECT sql FROM sqlite_master WHERE name='am_entities_vec_e5_embed_log'"
    ).fetchone()[0]
    # sqlite normalizes whitespace — just check the key tokens are present
    assert "embed_dim" in schema
    assert "DEFAULT 384" in schema
    assert "CHECK" in schema and "384" in schema


def test_refresh_log_table(vec_e5_schema):
    conn = vec_e5_schema
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name='am_entities_vec_e5_refresh_log'"
    ).fetchone()
    assert row


def test_rrf_fusion_basic():
    """Hand-compute RRF on synthetic FTS + vec lists; verify ordering."""
    from jpintel_mcp.api.semantic_search_v2 import _rrf_fuse

    fts = [
        {"rid": 1, "primary_name": "A"},
        {"rid": 2, "primary_name": "B"},
        {"rid": 3, "primary_name": "C"},
    ]
    vec = [
        {"rid": 2, "primary_name": "B"},
        {"rid": 4, "primary_name": "D"},
        {"rid": 1, "primary_name": "A"},
    ]
    fused = _rrf_fuse(fts, vec, k=60)
    assert fused[0]["rid"] == 2, f"top-1 should be rid=2, got {fused[0]}"
    assert {r["rid"] for r in fused} == {1, 2, 3, 4}
    for r in fused:
        assert "rrf_score" in r
        assert r["rrf_score"] > 0


def test_rrf_empty_inputs():
    from jpintel_mcp.api.semantic_search_v2 import _rrf_fuse

    assert _rrf_fuse([], []) == []
    only_fts = _rrf_fuse([{"rid": 9}], [])
    assert len(only_fts) == 1 and only_fts[0]["rid"] == 9


def test_reranker_score_range_check(vec_e5_schema):
    conn = vec_e5_schema
    qh = "a" * 64
    conn.execute(
        "INSERT INTO am_entities_vec_reranker_score "
        "(query_hash, entity_id_a, entity_id_b, score) VALUES (?,?,?,?)",
        (qh, 1, 2, 0.7),
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO am_entities_vec_reranker_score "
            "(query_hash, entity_id_a, entity_id_b, score) VALUES (?,?,?,?)",
            (qh, 3, 4, 99.0),
        )


def test_query_hash_is_stable():
    from jpintel_mcp.api.semantic_search_v2 import _query_hash

    h1 = _query_hash("  Foo Bar ")
    h2 = _query_hash("foo bar")
    assert h1 == h2, "_query_hash should normalize whitespace + case"
    assert len(h1) == 64


def test_rest_router_prefix():
    from jpintel_mcp.api.semantic_search_v2 import router

    assert router.prefix == "/v1"
    paths = {r.path for r in router.routes}
    assert "/v1/search/semantic" in paths


def test_rest_billing_unit_2_when_rerank_true():
    src = REST_API_PATH.read_text(encoding="utf-8")
    assert "quantity = 2 if body.rerank else 1" in src
    assert "_billing_unit" in src


def test_mcp_tool_docstring_includes_use_input_output_error():
    src = MCP_TOOL_PATH.read_text(encoding="utf-8")
    assert "いつ使う" in src
    assert "入力" in src
    assert "出力" in src
    assert "エラー" in src
    m = re.search(r'def semantic_search_am.*?"""(.+?)"""', src, re.S)
    assert m
    assert len(m.group(1)) >= 50


BANNED_IMPORTS = (
    "anthropic",
    "openai",
    "google.generativeai",
    "claude_agent_sdk",
)


def _ast_imports(path: pathlib.Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    mods: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods.extend(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            mods.append(node.module)
    return mods


@pytest.mark.parametrize(
    "fname",
    [
        ETL_PATH,
        REST_API_PATH,
        MCP_TOOL_PATH,
    ],
)
def test_no_llm_api_imports(fname):
    mods = _ast_imports(fname)
    for banned in BANNED_IMPORTS:
        for mod in mods:
            assert not mod.startswith(banned), (
                f"{fname.name}: forbidden import `{mod}` (matches {banned})"
            )


def test_sentence_transformers_is_allowed():
    etl_src = ETL_PATH.read_text(encoding="utf-8")
    rest_src = REST_API_PATH.read_text(encoding="utf-8")
    assert "sentence_transformers" in etl_src
    assert "sentence_transformers" in rest_src


def test_boot_manifest_contains_migration_260():
    manifest = BOOT_MANIFEST.read_text(encoding="utf-8")
    assert "260_vec_e5_small_384.sql" in manifest


def test_etl_dry_run_handles_missing_model(tmp_path, monkeypatch):
    import importlib.util

    spec = importlib.util.spec_from_file_location("build_e5_v2", ETL_PATH)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)

    db = tmp_path / "am.db"
    conn = sqlite3.connect(str(db))
    conn.execute(
        "CREATE TABLE am_entities (canonical_id TEXT, primary_name TEXT, "
        "record_kind TEXT, raw_json TEXT, source_url TEXT)"
    )
    conn.execute(
        "INSERT INTO am_entities VALUES (?,?,?,?,?)",
        ("test:1", "Test Entity", "program", "{}", "https://example.com"),
    )
    conn.commit()
    conn.close()

    result = mod.refresh(
        str(db),
        mode="full",
        dry_run=True,
        max_entities=5,
        model_name=mod.HASH_FALLBACK_MODEL,
    )
    assert result["dim"] == 384
    assert result["mode"] == "full"
    assert result["model"] == mod.HASH_FALLBACK_MODEL
