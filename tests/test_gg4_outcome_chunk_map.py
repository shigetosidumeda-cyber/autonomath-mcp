"""GG4 — Tests for the pre-mapped outcome → top-100 chunk surface.

Covers four surfaces in lock-step so the 432 × 100 = 43,200 row
contract holds end-to-end:

1. Migration SQL — table schema + idempotent re-apply.
2. Pre-mapper pipeline — 432 outcomes × 100 chunks written, valid
   ranks, deterministic order.
3. MCP tool ``get_outcome_chunks`` — pre-mapped reads, envelope
   shape, disclaimer, empty fallback paths.
4. Benchmark — pre-mapped p95 < 20 ms vs simulated live p95 ~ 150 ms
   = 7-8x speedup.

Every test runs against an isolated on-disk ``autonomath.db`` fixture
so the suite does not depend on the production 9.4 GB store.
"""

from __future__ import annotations

import importlib
import sqlite3
from pathlib import Path
from typing import Any

import pytest

# Modules under test (imported lazily through fixtures so the env
# overrides land before any module-level state initialises).
_PIPELINE = "scripts.aws_credit_ops.pre_map_outcomes_to_top_chunks_2026_05_17"
_TOOL = "jpintel_mcp.mcp.moat_lane_tools.get_outcome_with_chunks"
_BENCH = "scripts.bench.bench_outcome_chunks_2026_05_17"
_FRAGMENT_LOADER = "jpintel_mcp.mcp.moat_lane_tools._fragments"

REPO_ROOT = Path(__file__).resolve().parents[1]
MIGRATION_SQL = (
    REPO_ROOT / "scripts" / "migrations" / "wave24_220_am_outcome_chunk_map.sql"
)
ROLLBACK_SQL = (
    REPO_ROOT / "scripts" / "migrations" / "wave24_220_am_outcome_chunk_map_rollback.sql"
)
FRAGMENT_YAML = (
    REPO_ROOT
    / "src"
    / "jpintel_mcp"
    / "mcp"
    / "moat_lane_tools"
    / "_register_fragments.yaml"
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def empty_db(tmp_path: Path) -> Path:
    """Empty autonomath.db with the GG4 migration applied."""
    db_path = tmp_path / "autonomath.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(MIGRATION_SQL.read_text(encoding="utf-8"))
        conn.commit()
    finally:
        conn.close()
    return db_path


@pytest.fixture
def seeded_db(tmp_path: Path) -> Path:
    """autonomath.db with migration + a small seed (3 outcomes × 100 rows).

    Used for benchmark + MCP tool tests that need rows to read but don't
    require the full 43,200-row pre-mapper sweep.
    """
    db_path = tmp_path / "autonomath.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(MIGRATION_SQL.read_text(encoding="utf-8"))
        rows = []
        for oid in (1, 2, 3):
            for rank in range(1, 101):
                score = max(0.0, 1.0 - (rank - 1) / 100.0)
                rows.append((oid, rank, 1000 + rank, score, "2026-05-17T00:00:00Z"))
        conn.executemany(
            "INSERT INTO am_outcome_chunk_map "
            "(outcome_id, rank, chunk_id, score, mapped_at) VALUES (?, ?, ?, ?, ?)",
            rows,
        )
        conn.commit()
    finally:
        conn.close()
    return db_path


@pytest.fixture
def full_db(tmp_path: Path) -> Path:
    """autonomath.db with migration + the full 432 × 100 pre-mapper run."""
    db_path = tmp_path / "autonomath.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(MIGRATION_SQL.read_text(encoding="utf-8"))
        conn.commit()
    finally:
        conn.close()
    pipeline = importlib.import_module(_PIPELINE)
    summary = pipeline.run_premap(db_path, commit=True, chunks_limit=500)
    assert summary["rows_written"] >= 100
    return db_path


@pytest.fixture
def mcp_tool_module(monkeypatch: pytest.MonkeyPatch, seeded_db: Path) -> Any:
    """Reload the MCP tool module with the fixture DB pinned via env."""
    monkeypatch.setenv("JPCITE_AUTONOMATH_DB_PATH", str(seeded_db))
    monkeypatch.setenv("AUTONOMATH_DB_PATH", str(seeded_db))
    mod = importlib.import_module(_TOOL)
    return importlib.reload(mod)


def _impl(tool: Any) -> Any:
    for attr in ("fn", "func", "_fn"):
        inner = getattr(tool, attr, None)
        if callable(inner):
            return inner
    return tool


# ---------------------------------------------------------------------------
# (1) Migration tests
# ---------------------------------------------------------------------------


def test_migration_creates_expected_table_and_indexes(empty_db: Path) -> None:
    conn = sqlite3.connect(empty_db)
    try:
        tbl = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='am_outcome_chunk_map'"
        ).fetchone()
        assert tbl is not None, "GG4 migration did not create am_outcome_chunk_map"
        idxs = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='index' AND tbl_name='am_outcome_chunk_map'"
            ).fetchall()
        }
        assert "ix_am_outcome_chunk_map_outcome_id" in idxs
        assert "ix_am_outcome_chunk_map_chunk_id" in idxs
    finally:
        conn.close()


def test_migration_is_idempotent(empty_db: Path) -> None:
    """Re-applying the migration must not raise (CREATE ... IF NOT EXISTS)."""
    conn = sqlite3.connect(empty_db)
    try:
        # Apply twice. If any CREATE forgot IF NOT EXISTS this raises.
        conn.executescript(MIGRATION_SQL.read_text(encoding="utf-8"))
        conn.executescript(MIGRATION_SQL.read_text(encoding="utf-8"))
        conn.commit()
    finally:
        conn.close()


def test_migration_rollback_drops_table(empty_db: Path) -> None:
    conn = sqlite3.connect(empty_db)
    try:
        conn.executescript(ROLLBACK_SQL.read_text(encoding="utf-8"))
        conn.commit()
        tbl = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='am_outcome_chunk_map'"
        ).fetchone()
        assert tbl is None, "rollback did not drop am_outcome_chunk_map"
    finally:
        conn.close()


def test_rank_constraint_rejects_out_of_range(empty_db: Path) -> None:
    """rank CHECK constraint enforces 1..100."""
    conn = sqlite3.connect(empty_db)
    try:
        for bad_rank in (0, 101, -1, 1000):
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(
                    "INSERT INTO am_outcome_chunk_map "
                    "(outcome_id, rank, chunk_id, score, mapped_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (1, bad_rank, 999, 0.5, "2026-05-17T00:00:00Z"),
                )
    finally:
        conn.close()


def test_score_constraint_rejects_out_of_range(empty_db: Path) -> None:
    """score CHECK constraint enforces 0.0..1.0."""
    conn = sqlite3.connect(empty_db)
    try:
        for bad_score in (-0.1, 1.1, 2.0, -1.0):
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(
                    "INSERT INTO am_outcome_chunk_map "
                    "(outcome_id, rank, chunk_id, score, mapped_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (1, 1, 999, bad_score, "2026-05-17T00:00:00Z"),
                )
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# (2) Pre-mapper pipeline tests
# ---------------------------------------------------------------------------


def test_pipeline_writes_432_x_100_rows(empty_db: Path) -> None:
    """432 outcomes × 100 chunks = 43,200 rows."""
    pipeline = importlib.import_module(_PIPELINE)
    summary = pipeline.run_premap(empty_db, commit=True, chunks_limit=500)
    assert summary["outcomes"] == pipeline.WAVE_60_94_OUTCOMES == 432
    assert summary["rows_written"] == 432 * 100
    conn = sqlite3.connect(empty_db)
    try:
        total = conn.execute("SELECT COUNT(*) FROM am_outcome_chunk_map").fetchone()[0]
        assert total == 43_200
    finally:
        conn.close()


def test_pipeline_rank_monotonic_within_outcome(full_db: Path) -> None:
    """rank must be a contiguous 1..100 sequence per outcome."""
    conn = sqlite3.connect(full_db)
    try:
        rows = conn.execute(
            "SELECT outcome_id, rank FROM am_outcome_chunk_map ORDER BY outcome_id, rank"
        ).fetchall()
        from collections import defaultdict

        by_outcome: dict[int, list[int]] = defaultdict(list)
        for oid, rank in rows:
            by_outcome[int(oid)].append(int(rank))
        for oid, ranks in by_outcome.items():
            assert ranks == list(range(1, 101)), f"outcome {oid} ranks not 1..100"
    finally:
        conn.close()


def test_pipeline_chunk_ids_are_valid_ints(full_db: Path) -> None:
    """chunk_id must be a positive integer (logical FK to M9 corpus)."""
    conn = sqlite3.connect(full_db)
    try:
        bad = conn.execute(
            "SELECT COUNT(*) FROM am_outcome_chunk_map WHERE chunk_id <= 0"
        ).fetchone()[0]
        assert bad == 0
    finally:
        conn.close()


def test_pipeline_idempotent_rerun(empty_db: Path) -> None:
    """Re-running the pipeline yields the same 43,200 rows (INSERT OR REPLACE)."""
    pipeline = importlib.import_module(_PIPELINE)
    pipeline.run_premap(empty_db, commit=True, chunks_limit=500)
    pipeline.run_premap(empty_db, commit=True, chunks_limit=500)
    conn = sqlite3.connect(empty_db)
    try:
        total = conn.execute("SELECT COUNT(*) FROM am_outcome_chunk_map").fetchone()[0]
        assert total == 43_200, "second run must not duplicate rows"
    finally:
        conn.close()


def test_pipeline_deterministic_score_order(empty_db: Path) -> None:
    """Two runs of the pipeline produce identical row sets."""
    pipeline = importlib.import_module(_PIPELINE)
    pipeline.run_premap(empty_db, commit=True, chunks_limit=200)
    conn = sqlite3.connect(empty_db)
    try:
        snap1 = conn.execute(
            "SELECT outcome_id, rank, chunk_id FROM am_outcome_chunk_map "
            "ORDER BY outcome_id, rank"
        ).fetchall()
        # Truncate and re-run.
        conn.execute("DELETE FROM am_outcome_chunk_map")
        conn.commit()
    finally:
        conn.close()
    pipeline.run_premap(empty_db, commit=True, chunks_limit=200)
    conn = sqlite3.connect(empty_db)
    try:
        snap2 = conn.execute(
            "SELECT outcome_id, rank, chunk_id FROM am_outcome_chunk_map "
            "ORDER BY outcome_id, rank"
        ).fetchall()
    finally:
        conn.close()
    assert snap1 == snap2


# ---------------------------------------------------------------------------
# (3) MCP tool tests
# ---------------------------------------------------------------------------


def test_tool_returns_pre_mapped_rows(mcp_tool_module: Any) -> None:
    fn = _impl(mcp_tool_module.get_outcome_chunks)
    out = fn(outcome_id=1, limit=10)
    assert out["tool_name"] == "get_outcome_chunks"
    assert out["primary_result"]["status"] == "ok"
    assert out["total"] == 10
    # Rank-sorted ascending.
    ranks = [r["rank"] for r in out["results"]]
    assert ranks == list(range(1, 11))


def test_tool_envelope_disclaimer_and_billing(mcp_tool_module: Any) -> None:
    fn = _impl(mcp_tool_module.get_outcome_chunks)
    out = fn(outcome_id=2, limit=5)
    assert out["_billing_unit"] == 1
    assert out["_pricing_tier"] == "A"
    d = out["_disclaimer"]
    assert "税理士法 §52" in d
    assert "公認会計士法 §47条の2" in d
    assert "弁護士法 §72" in d
    assert "行政書士法 §1" in d
    assert "司法書士法 §3" in d


def test_tool_provenance_marks_no_faiss_call(mcp_tool_module: Any) -> None:
    fn = _impl(mcp_tool_module.get_outcome_chunks)
    out = fn(outcome_id=3, limit=5)
    prov = out["provenance"]
    assert prov["lane_id"] == "GG4"
    assert prov["wrap_kind"] == "moat_lane_gg4_outcome_chunk_map_db"
    assert prov["premapped"] is True
    assert prov["faiss_called"] is False
    assert prov["rerank_called"] is False


def test_tool_cost_saving_note_present(mcp_tool_module: Any) -> None:
    fn = _impl(mcp_tool_module.get_outcome_chunks)
    out = fn(outcome_id=1, limit=1)
    note = out["_cost_saving_note"]
    assert "Pre-mapped" in note
    assert "¥3/req" in note
    assert "¥250" in note


def test_tool_empty_on_unknown_outcome(mcp_tool_module: Any) -> None:
    fn = _impl(mcp_tool_module.get_outcome_chunks)
    out = fn(outcome_id=9999, limit=10)
    assert out["primary_result"]["status"] == "empty"
    assert "no pre-mapped chunks" in out["primary_result"]["rationale"]
    assert "_disclaimer" in out


def test_tool_db_missing_returns_empty(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    missing = tmp_path / "does_not_exist.db"
    monkeypatch.setenv("JPCITE_AUTONOMATH_DB_PATH", str(missing))
    monkeypatch.setenv("AUTONOMATH_DB_PATH", str(missing))
    mod = importlib.import_module(_TOOL)
    mod = importlib.reload(mod)
    fn = _impl(mod.get_outcome_chunks)
    out = fn(outcome_id=1, limit=10)
    assert out["primary_result"]["status"] == "empty"
    assert "autonomath.db unreachable" in out["primary_result"]["rationale"]
    assert "_disclaimer" in out


def test_tool_table_missing_returns_empty(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db_path = tmp_path / "autonomath.db"
    sqlite3.connect(db_path).close()
    monkeypatch.setenv("JPCITE_AUTONOMATH_DB_PATH", str(db_path))
    monkeypatch.setenv("AUTONOMATH_DB_PATH", str(db_path))
    mod = importlib.import_module(_TOOL)
    mod = importlib.reload(mod)
    fn = _impl(mod.get_outcome_chunks)
    out = fn(outcome_id=1, limit=10)
    assert out["primary_result"]["status"] == "empty"
    assert "wave24_220 not applied" in out["primary_result"]["rationale"]


def test_tool_limit_param_capped_at_100(mcp_tool_module: Any) -> None:
    """The pre-mapper persists exactly 100 chunks per outcome."""
    fn = _impl(mcp_tool_module.get_outcome_chunks)
    out = fn(outcome_id=1, limit=100)
    assert out["total"] == 100
    assert out["limit"] == 100


def test_tool_does_not_call_faiss_or_llm(mcp_tool_module: Any) -> None:
    """Spot-check: the module body must not import faiss or any LLM SDK."""
    import inspect

    src = inspect.getsource(mcp_tool_module)
    assert "import faiss" not in src
    assert "anthropic" not in src.lower()
    assert "openai" not in src.lower()


# ---------------------------------------------------------------------------
# (4) Benchmark + fragment loader tests
# ---------------------------------------------------------------------------


def test_bench_premapped_p95_under_20ms(full_db: Path) -> None:
    """Pre-mapped p95 must be well under 20 ms even on a tmp_path SQLite."""
    bench = importlib.import_module(_BENCH)
    outcome_ids = bench.sample_outcome_ids(full_db, n=100, rng_seed=42)
    assert len(outcome_ids) >= 50
    pre = bench.bench_premapped(full_db, outcome_ids=outcome_ids, limit=10)
    assert pre.n == len(outcome_ids)
    assert pre.p95_ms < 20.0, f"p95={pre.p95_ms}ms exceeds 20ms budget"


def test_bench_speedup_7x_over_live_baseline(full_db: Path) -> None:
    """Pre-mapped must beat the live FAISS+rerank simulation by 7x at p95."""
    bench = importlib.import_module(_BENCH)
    outcome_ids = bench.sample_outcome_ids(full_db, n=100, rng_seed=42)
    pre = bench.bench_premapped(full_db, outcome_ids=outcome_ids, limit=10)
    live = bench.bench_live_simulation(n_samples=len(outcome_ids), rng_seed=42)
    speedup = bench.speedup(live, pre)
    assert speedup >= 7.0, f"speedup={speedup:.2f}x below 7x target"


def test_fragment_yaml_lists_get_outcome_with_chunks() -> None:
    """The fragment YAML is the registry SOT for the GG4 lane."""
    text = FRAGMENT_YAML.read_text(encoding="utf-8")
    assert "submodules:" in text
    assert "get_outcome_with_chunks" in text


def test_fragment_loader_parses_yaml_subset() -> None:
    """The minimal YAML parser must surface the listed submodule."""
    loader = importlib.import_module(_FRAGMENT_LOADER)
    sample = "submodules:\n  - get_outcome_with_chunks\n  - other_lane\n"
    names = loader._parse_submodules(sample)
    assert names == ["get_outcome_with_chunks", "other_lane"]
