"""Tests for Moat N3 — Legal reasoning chain (migration wave24_202 + MCP tools).

Covers:
  * migration ``wave24_202_am_legal_reasoning_chain.sql`` applies cleanly
  * ``am_legal_reasoning_chain`` table accepts a representative chain row
  * ``CHECK`` constraints fire on malformed chain_id / tax_category / confidence
  * deterministic ``LRC-<10 hex>`` id derivation in
    ``scripts.build_legal_reasoning_chain``
  * ``get_reasoning_chain`` returns 5 viewpoint slices for a topic_id
  * ``get_reasoning_chain`` returns exactly 1 row for an LRC-* id lookup
  * ``walk_reasoning_chain`` filters by keyword + category + min_confidence
  * both MCP wrappers carry the canonical disclaimer + billing_unit=1
  * both MCP wrappers route through am_legal_reasoning_chain (no LLM call)

The test uses a tmp_path sqlite DB created from the migration SQL — it does
NOT mutate the real ``autonomath.db``. Production DB is exercised indirectly
through ``build_legal_reasoning_chain`` chain-id derivation (pure-Python).
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
MIGRATION_PATH = REPO_ROOT / "scripts" / "migrations" / "wave24_202_am_legal_reasoning_chain.sql"
ROLLBACK_PATH = (
    REPO_ROOT / "scripts" / "migrations" / "wave24_202_am_legal_reasoning_chain_rollback.sql"
)

if str(REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _apply_migration(conn: sqlite3.Connection, path: Path) -> None:
    sql = path.read_text(encoding="utf-8")
    conn.executescript(sql)
    conn.commit()


@pytest.fixture
def am_conn(tmp_path: Path) -> sqlite3.Connection:
    """Fresh autonomath.db skeleton with the N3 migration applied."""
    db_path = tmp_path / "autonomath.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    _apply_migration(conn, MIGRATION_PATH)
    return conn


def _insert_chain(
    conn: sqlite3.Connection,
    *,
    chain_id: str = "LRC-0123456789",
    topic_id: str = "corporate_tax:yakuin_hosyu",
    topic_label: str = "役員報酬の損金算入 — 原則的取扱い",
    tax_category: str = "corporate_tax",
    premise_law_article_ids: list[int] | None = None,
    premise_tsutatsu_ids: list[int] | None = None,
    minor_premise_judgment_ids: list[str] | None = None,
    conclusion_text: str = "[原則的取扱い] 役員給与の損金算入は法人税法34条が定型給与等3類型に限定。",
    confidence: float = 0.85,
    opposing_view_text: str
    | None = "形式要件を満たさない場合でも合理性が認められる余地ありとの見解あり。",
    citations: dict[str, list[dict]] | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO am_legal_reasoning_chain (
            chain_id, topic_id, topic_label, tax_category,
            premise_law_article_ids, premise_tsutatsu_ids,
            minor_premise_judgment_ids,
            conclusion_text, confidence, opposing_view_text,
            citations, computed_by_model, computed_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            chain_id,
            topic_id,
            topic_label,
            tax_category,
            json.dumps(premise_law_article_ids or [101, 102]),
            json.dumps(premise_tsutatsu_ids or [201]),
            json.dumps(minor_premise_judgment_ids or ["HAN-001", "NTA-SAI-000001"]),
            conclusion_text,
            confidence,
            opposing_view_text,
            json.dumps(citations or {"law": [], "tsutatsu": [], "hanrei": [], "saiketsu": []}),
            "rule_engine_v1",
            "2026-05-17T00:00:00.000Z",
        ),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Migration / schema tests
# ---------------------------------------------------------------------------


def test_migration_files_exist() -> None:
    assert MIGRATION_PATH.exists(), MIGRATION_PATH
    assert ROLLBACK_PATH.exists(), ROLLBACK_PATH


def test_migration_target_db_header() -> None:
    """The forward migration must be a target_db: autonomath migration so the
    entrypoint.sh §4 boot loop picks it up.
    """
    first_line = MIGRATION_PATH.read_text(encoding="utf-8").splitlines()[0]
    assert first_line.strip() == "-- target_db: autonomath", first_line


def test_table_created(am_conn: sqlite3.Connection) -> None:
    cur = am_conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        ("am_legal_reasoning_chain",),
    )
    assert cur.fetchone() is not None


def test_view_created(am_conn: sqlite3.Connection) -> None:
    cur = am_conn.execute(
        "SELECT name FROM sqlite_master WHERE type='view' AND name=?",
        ("v_am_legal_reasoning_chain_confident",),
    )
    assert cur.fetchone() is not None


def test_chain_insert_roundtrip(am_conn: sqlite3.Connection) -> None:
    _insert_chain(am_conn)
    cur = am_conn.execute("SELECT chain_id, topic_id, confidence FROM am_legal_reasoning_chain")
    rows = cur.fetchall()
    assert len(rows) == 1
    assert rows[0]["chain_id"] == "LRC-0123456789"
    assert rows[0]["topic_id"] == "corporate_tax:yakuin_hosyu"
    assert rows[0]["confidence"] == pytest.approx(0.85)


def test_chain_id_check_constraint(am_conn: sqlite3.Connection) -> None:
    """chain_id MUST match ``LRC-<10 hex>``."""
    with pytest.raises(sqlite3.IntegrityError):
        _insert_chain(am_conn, chain_id="BAD-shape")


def test_category_check_constraint(am_conn: sqlite3.Connection) -> None:
    """tax_category MUST be one of the closed taxonomy values."""
    with pytest.raises(sqlite3.IntegrityError):
        _insert_chain(am_conn, tax_category="not_a_category")


def test_confidence_bound_constraint(am_conn: sqlite3.Connection) -> None:
    """confidence MUST be in [0.0, 1.0]."""
    with pytest.raises(sqlite3.IntegrityError):
        _insert_chain(am_conn, confidence=1.5)


def test_confident_view_filter(am_conn: sqlite3.Connection) -> None:
    """``v_am_legal_reasoning_chain_confident`` MUST drop chains < 0.6."""
    _insert_chain(am_conn, chain_id="LRC-aaaaaaaaaa", confidence=0.5)
    _insert_chain(am_conn, chain_id="LRC-bbbbbbbbbb", confidence=0.7)
    cur = am_conn.execute("SELECT chain_id FROM v_am_legal_reasoning_chain_confident")
    rows = [r["chain_id"] for r in cur.fetchall()]
    assert rows == ["LRC-bbbbbbbbbb"]


# ---------------------------------------------------------------------------
# Builder script tests (pure-Python, no DB)
# ---------------------------------------------------------------------------


def test_chain_id_derivation_deterministic() -> None:
    import build_legal_reasoning_chain as b

    assert b._chain_id_for("foo:bar", "原則的取扱い") == b._chain_id_for("foo:bar", "原則的取扱い")
    # Different inputs → different ids.
    assert b._chain_id_for("foo:bar", "原則的取扱い") != b._chain_id_for("foo:bar", "判例の傾向")


def test_chain_id_shape() -> None:
    import build_legal_reasoning_chain as b

    cid = b._chain_id_for("corporate_tax:yakuin_hosyu", "原則的取扱い")
    assert cid.startswith("LRC-")
    assert len(cid) == 14
    assert all(c in "0123456789abcdef" for c in cid[4:])


def test_topic_count_160() -> None:
    import build_legal_reasoning_chain as b

    topics = b.all_topics()
    assert len(topics) == 160, len(topics)
    # Every topic produces 5 viewpoint slices → 800 chains.
    chain_total = sum(len(t.viewpoint_slices) for t in topics)
    assert chain_total == 800, chain_total


def test_topic_id_namespace_uniqueness() -> None:
    import build_legal_reasoning_chain as b

    ids = [t.topic_id for t in b.all_topics()]
    assert len(set(ids)) == len(ids), "topic_id must be unique"


def test_topic_category_taxonomy_distribution() -> None:
    """Verify the cohort distribution matches the spec ledger."""
    from collections import Counter

    import build_legal_reasoning_chain as b

    counts = Counter(t.tax_category for t in b.all_topics())
    assert counts["corporate_tax"] == 50
    assert counts["consumption_tax"] == 30
    assert counts["subsidy"] == 30
    assert counts["labor"] == 20
    assert counts["commerce"] == 30


def test_compose_chain_confidence_rubric() -> None:
    """Confidence baseline 0.50, +0.15/laws +0.10/tsutatsu +0.10/judgments
    +0.05/regular_slice, capped at 0.85 for opposing-view topics.
    """
    import build_legal_reasoning_chain as b

    topic = b.Topic(
        topic_id="test:foo",
        label="Test foo",
        tax_category="corporate_tax",
        law_canonical_id="law:test",
        article_numbers=("1",),
        tsutatsu_law_id="law:test-tt",
        tsutatsu_article_prefix=("1-",),
        keywords=("test",),
        conclusion_text="Test conclusion.",
        opposing_view_text=None,
        viewpoint_slices=("原則的取扱い",),
    )
    row = b._compose_chain(
        topic,
        "原則的取扱い",
        laws=[
            b.LawArticleRef(
                article_id=1,
                law_canonical_id="law:test",
                article_number="1",
                title="x",
                source_url=None,
            )
        ],
        tsutatsu=[
            b.LawArticleRef(
                article_id=2,
                law_canonical_id="law:test-tt",
                article_number="1-1",
                title="y",
                source_url=None,
            )
        ],
        judgments=[
            b.JudgmentRef(
                unified_id="HAN-001",
                court="最高裁",
                decision_date="2020-01-01",
                precedent_weight="binding",
                key_ruling_excerpt="...",
            )
        ],
        saiketsu=[],
    )
    # 0.50 + 0.15 + 0.10 + 0.10 + 0.05 = 0.90; no opposing-view cap.
    assert row.confidence == pytest.approx(0.90), row.confidence

    # Opposing-view topic caps at 0.85.
    topic_op = b.Topic(
        topic_id="test:bar",
        label="Test bar",
        tax_category="corporate_tax",
        law_canonical_id="law:test",
        article_numbers=("1",),
        tsutatsu_law_id="law:test-tt",
        tsutatsu_article_prefix=("1-",),
        keywords=("test",),
        conclusion_text="Test conclusion.",
        opposing_view_text="反対説あり",
        viewpoint_slices=("原則的取扱い",),
    )
    row_op = b._compose_chain(
        topic_op,
        "原則的取扱い",
        laws=[
            b.LawArticleRef(
                article_id=1,
                law_canonical_id="law:test",
                article_number="1",
                title="x",
                source_url=None,
            )
        ],
        tsutatsu=[
            b.LawArticleRef(
                article_id=2,
                law_canonical_id="law:test-tt",
                article_number="1-1",
                title="y",
                source_url=None,
            )
        ],
        judgments=[
            b.JudgmentRef(
                unified_id="HAN-001",
                court="最高裁",
                decision_date="2020-01-01",
                precedent_weight="binding",
                key_ruling_excerpt="...",
            )
        ],
        saiketsu=[],
    )
    assert row_op.confidence == pytest.approx(0.85), row_op.confidence


def test_compose_chain_minor_premise_aggregation() -> None:
    """``minor_premise_judgment_ids`` aggregates both court_decisions
    (HAN-*) + nta_saiketsu (NTA-SAI-*) ids.
    """
    import build_legal_reasoning_chain as b

    topic = b.Topic(
        topic_id="test:agg",
        label="Test agg",
        tax_category="corporate_tax",
        law_canonical_id="law:test",
        article_numbers=("1",),
        tsutatsu_law_id="law:test-tt",
        tsutatsu_article_prefix=("1-",),
        keywords=("test",),
        conclusion_text="x",
        viewpoint_slices=("原則的取扱い",),
    )
    row = b._compose_chain(
        topic,
        "原則的取扱い",
        laws=[],
        tsutatsu=[],
        judgments=[
            b.JudgmentRef(
                unified_id="HAN-001",
                court="x",
                decision_date=None,
                precedent_weight="binding",
                key_ruling_excerpt="",
            )
        ],
        saiketsu=[
            b.SaiketsuRef(
                saiketsu_id="NTA-SAI-000001",
                decision_date=None,
                tax_type=None,
                title=None,
                decision_summary=None,
            )
        ],
    )
    assert row.minor_premise_judgment_ids == ["HAN-001", "NTA-SAI-000001"]


# ---------------------------------------------------------------------------
# MCP tool tests (DB-backed)
# ---------------------------------------------------------------------------


@pytest.fixture
def patched_n3_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Build a tmp autonomath.db with the migration + seed rows and route the
    N3 module's ``_autonomath_db_path`` at it.
    """
    db_path = tmp_path / "autonomath.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    _apply_migration(conn, MIGRATION_PATH)
    # Seed 6 chains across 2 topics.
    for i in range(5):
        _insert_chain(
            conn,
            chain_id=f"LRC-{i:010x}",
            topic_id="corporate_tax:yakuin_hosyu",
            topic_label=f"役員報酬の損金算入 — slice{i}",
            tax_category="corporate_tax",
            confidence=0.85 - i * 0.05,
        )
    _insert_chain(
        conn,
        chain_id="LRC-bbbbbbbbbb",
        topic_id="consumption_tax:invoice_seido",
        topic_label="インボイス制度の登録要件 — 原則的取扱い",
        tax_category="consumption_tax",
        confidence=0.8,
        opposing_view_text=None,
    )
    conn.close()

    from jpintel_mcp.mcp.moat_lane_tools import moat_n3_reasoning as m

    monkeypatch.setattr(m, "_autonomath_db_path", lambda: db_path, raising=True)
    return m


def test_get_reasoning_chain_by_topic_id(patched_n3_db) -> None:
    out = patched_n3_db.get_reasoning_chain(topic="corporate_tax:yakuin_hosyu", limit=10)
    assert out["tool_name"] == "get_reasoning_chain"
    assert out["schema_version"] == "moat.n3.v1"
    assert out["_billing_unit"] == 1
    assert "§52" in out["_disclaimer"]
    assert out["total"] == 5
    assert out["limit"] == 5
    # Sorted by confidence DESC.
    confs = [c["confidence"] for c in out["results"]]
    assert confs == sorted(confs, reverse=True)


def test_get_reasoning_chain_by_chain_id(patched_n3_db) -> None:
    out = patched_n3_db.get_reasoning_chain(topic="LRC-bbbbbbbbbb")
    assert out["total"] == 1
    assert out["results"][0]["chain_id"] == "LRC-bbbbbbbbbb"
    assert out["results"][0]["tax_category"] == "consumption_tax"


def test_get_reasoning_chain_no_match(patched_n3_db) -> None:
    out = patched_n3_db.get_reasoning_chain(topic="nonexistent:topic")
    assert out["primary_result"]["status"] == "no_match"
    assert out["results"] == []
    assert out["total"] == 0


def test_walk_reasoning_chain_keyword(patched_n3_db) -> None:
    out = patched_n3_db.walk_reasoning_chain(
        query="役員報酬", category="all", min_confidence=0.0, limit=10
    )
    assert out["tool_name"] == "walk_reasoning_chain"
    # 5 yakuin_hosyu chains all match.
    assert out["total"] == 5
    for c in out["results"]:
        assert "役員報酬" in c["topic_label"]


def test_walk_reasoning_chain_category_filter(patched_n3_db) -> None:
    out = patched_n3_db.walk_reasoning_chain(
        query="制度", category="consumption_tax", min_confidence=0.0, limit=10
    )
    # Only the invoice_seido chain has 'consumption_tax' + 制度.
    assert out["total"] == 1
    assert out["results"][0]["chain_id"] == "LRC-bbbbbbbbbb"


def test_walk_reasoning_chain_min_confidence(patched_n3_db) -> None:
    out = patched_n3_db.walk_reasoning_chain(
        query="役員報酬",
        category="all",
        min_confidence=0.75,
        limit=10,
    )
    # confs are ~0.85, ~0.80, 0.75, ~0.70, ~0.65 → 3 pass >= 0.75 (after
    # 0.05-step floating point rounding the second row sits at 0.79999...).
    assert out["total"] == 3


def test_walk_reasoning_chain_disclaimer_envelope(patched_n3_db) -> None:
    out = patched_n3_db.walk_reasoning_chain(query="役員報酬")
    assert "_disclaimer" in out
    assert "§52" in out["_disclaimer"]
    assert out["_billing_unit"] == 1
    assert out["provenance"]["db_table"] == "am_legal_reasoning_chain"
    assert out["provenance"]["computed_by_model"] == "rule_engine_v1"


def test_no_llm_imports_in_module() -> None:
    """The N3 module must NOT import any LLM SDK (anthropic / openai / etc.)."""
    src = (
        REPO_ROOT / "src" / "jpintel_mcp" / "mcp" / "moat_lane_tools" / "moat_n3_reasoning.py"
    ).read_text(encoding="utf-8")
    for forbidden in (
        "import anthropic",
        "from anthropic",
        "import openai",
        "from openai",
        "import google.generativeai",
        "claude_agent_sdk",
    ):
        assert forbidden not in src, forbidden
