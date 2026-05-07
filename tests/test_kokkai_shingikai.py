"""DEEP-39 kokkai_shingikai test suite — 6 cases.

Coverage map (acceptance criteria from DEEP_39_kokkai_shingikai_cron.md §6):

  1. test_migration_applies_idempotently         — schema acceptance #1
  2. test_speech_record_parser_regex_only        — LLM-0 parser surface
  3. test_kokkai_api_mock_fetch                  — fetch path with mocked httpx
  4. test_search_kokkai_utterance_tool_integration — MCP tool envelope contract
  5. test_no_llm_imports_in_deep39_files         — acceptance #5 (LLM 0 guard)
  6. test_kokkai_shingikai_workflow_yaml_valid   — GHA workflow yaml syntax
"""

from __future__ import annotations

import ast
import sqlite3
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
_MIGRATION = _REPO_ROOT / "scripts" / "migrations" / "wave24_185_kokkai_utterance.sql"
_ROLLBACK = _REPO_ROOT / "scripts" / "migrations" / "wave24_185_kokkai_utterance_rollback.sql"
_KOKKAI_CRON = _REPO_ROOT / "scripts" / "cron" / "ingest_kokkai_weekly.py"
_SHINGIKAI_CRON = _REPO_ROOT / "scripts" / "cron" / "ingest_shingikai_weekly.py"
_WORKFLOW = _REPO_ROOT / ".github" / "workflows" / "kokkai-shingikai-weekly.yml"
_TOOL_MODULE = _REPO_ROOT / "src" / "jpintel_mcp" / "mcp" / "autonomath_tools" / "kokkai_tools.py"


# ---------------------------------------------------------------------------
# 1. Migration applies idempotently and creates 3 tables + indexes.
# ---------------------------------------------------------------------------


def test_migration_applies_idempotently(tmp_path) -> None:
    """Acceptance #1: 3 tables exist + all indexes after migration apply (twice)."""
    db_path = tmp_path / "test_autonomath.db"
    sql = _MIGRATION.read_text(encoding="utf-8")
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(sql)
        conn.commit()
        # Re-apply — must be idempotent (IF NOT EXISTS everywhere).
        conn.executescript(sql)
        conn.commit()
        # Verify tables.
        rows = conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name IN "
            "('kokkai_utterance','shingikai_minutes','regulatory_signal') "
            "ORDER BY name"
        ).fetchall()
        assert {r[0] for r in rows} == {
            "kokkai_utterance",
            "regulatory_signal",
            "shingikai_minutes",
        }
        # Verify indexes.
        idx = conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='index' AND name LIKE 'ix_%' "
            "AND tbl_name IN ('kokkai_utterance','shingikai_minutes','regulatory_signal') "
            "ORDER BY name"
        ).fetchall()
        idx_names = {r[0] for r in idx}
        assert "ix_kokkai_date" in idx_names
        assert "ix_kokkai_committee_date" in idx_names
        assert "ix_shingikai_council_date" in idx_names
        assert "ix_signal_law_detected" in idx_names
        # CHECK constraint enforced on regulatory_signal.signal_kind.
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO regulatory_signal "
                "(id, signal_kind, law_target, lead_time_months, "
                " evidence_url, detected_at) "
                "VALUES ('x','bogus_kind','税理士法',6,'https://x','2026-01-01T00:00:00Z')"
            )
        # Rollback applies cleanly.
        conn.executescript(_ROLLBACK.read_text(encoding="utf-8"))
        conn.commit()
        rows = conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name IN "
            "('kokkai_utterance','shingikai_minutes','regulatory_signal')"
        ).fetchall()
        assert rows == []
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 2. Speech-record parser surface — pure regex / dict, NO LLM.
# ---------------------------------------------------------------------------


def test_speech_record_parser_regex_only() -> None:
    """Acceptance: parse_speech_record returns canonical row dict."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("kokkai_cron", _KOKKAI_CRON)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    rec = {
        "speechID": "abc-123",
        "session": "215",
        "nameOfHouse": "衆議院",
        "nameOfMeeting": "財務金融委員会",
        "date": "2026-04-15",
        "speaker": "山田太郎",
        "speakerPosition": "委員",
        "speech": "税理士法の改正について",
        "speechURL": "https://kokkai.ndl.go.jp/x",
    }
    row = mod.parse_speech_record(rec)
    assert row is not None
    assert row["id"] == "abc-123"
    assert row["session_no"] == 215
    assert row["house"] == "衆議院"
    assert row["committee"] == "財務金融委員会"
    assert row["date"] == "2026-04-15"
    assert row["speaker"] == "山田太郎"
    assert row["body"] == "税理士法の改正について"
    assert row["sha256"] and len(row["sha256"]) == 64
    assert row["retrieved_at"].endswith("Z")

    # Missing required field returns None.
    rec_bad = dict(rec)
    rec_bad.pop("speechID")
    assert mod.parse_speech_record(rec_bad) is None

    # detect_keywords filters to KEYWORDS membership.
    hits = mod.detect_keywords("適格請求書 と AI規制 と 税理士法 を議論")
    assert "適格請求書" in hits
    assert "AI規制" in hits
    assert "税理士法" in hits
    assert mod.detect_keywords("関係ない 文章") == []


# ---------------------------------------------------------------------------
# 3. Mock httpx fetch path — exercises pagination + insert.
# ---------------------------------------------------------------------------


def test_kokkai_api_mock_fetch(tmp_path) -> None:
    """Acceptance: fetcher returns parsed records when the API is mocked."""
    import asyncio
    import importlib.util

    spec = importlib.util.spec_from_file_location("kokkai_cron2", _KOKKAI_CRON)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    # Mock httpx.AsyncClient.get — returns 1 page of 2 records, then empty.
    page_1 = {
        "speechRecord": [
            {
                "speechID": "abc-1",
                "session": 215,
                "nameOfHouse": "衆議院",
                "nameOfMeeting": "財務金融",
                "date": "2026-04-01",
                "speaker": "甲",
                "speech": "税理士法 改正案",
                "speechURL": "https://x/1",
            },
            {
                "speechID": "abc-2",
                "session": 215,
                "nameOfHouse": "衆議院",
                "nameOfMeeting": "財務金融",
                "date": "2026-04-02",
                "speaker": "乙",
                "speech": "適格請求書 制度",
                "speechURL": "https://x/2",
            },
        ],
        "numberOfRecords": 2,
    }
    page_empty = {"speechRecord": [], "numberOfRecords": 2}

    responses = [
        MagicMock(status_code=200, json=lambda: page_1),
        MagicMock(status_code=200, json=lambda: page_empty),
    ]

    async def _runner() -> list[dict]:
        client = MagicMock()
        client.get = AsyncMock(side_effect=responses)
        sem = asyncio.Semaphore(1)
        result = await mod._fetch_speeches(client, sem, "税理士法", "2026-01-01", max_records=10)
        return result

    out = asyncio.run(_runner())
    assert len(out) == 2
    assert out[0]["speechID"] == "abc-1"


# ---------------------------------------------------------------------------
# 4. Tool integration — MCP impl returns the canonical envelope.
# ---------------------------------------------------------------------------


def test_search_kokkai_utterance_tool_integration(tmp_path, monkeypatch) -> None:
    """Acceptance: _search_kokkai_utterance_impl returns the documented envelope."""
    db_path = tmp_path / "test_autonomath.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript(_MIGRATION.read_text(encoding="utf-8"))
    conn.execute(
        """
        INSERT INTO kokkai_utterance
            (id, session_no, house, committee, date, speaker, speaker_role,
             body, source_url, retrieved_at, sha256)
        VALUES ('s1', 215, '衆議院', '財務金融', '2026-04-15', '山田',
                '委員', '税理士法 改正に関する答弁',
                'https://kokkai.ndl.go.jp/s1',
                '2026-04-16T00:00:00Z',
                'abc' || hex(randomblob(30)))
        """
    )
    conn.commit()
    conn.close()

    # Point the MCP layer at our test DB BEFORE any imports of the tool module.
    monkeypatch.setenv("AUTONOMATH_DB_PATH", str(db_path))
    monkeypatch.setenv("AUTONOMATH_KOKKAI_ENABLED", "1")
    # Ensure DB module re-reads the env var by killing thread-local state.
    from jpintel_mcp.mcp.autonomath_tools import db as _db_mod

    _db_mod.close_all()
    _db_mod.AUTONOMATH_DB_PATH = db_path  # type: ignore[assignment]
    from jpintel_mcp.mcp.autonomath_tools.kokkai_tools import (
        _search_kokkai_utterance_impl,
        _search_shingikai_minutes_impl,
    )

    res = _search_kokkai_utterance_impl(law_keyword="税理士法", limit=5)
    assert "results" in res
    assert "_disclaimer" in res
    assert "_next_calls" in res
    assert "corpus_snapshot_id" in res
    assert "corpus_checksum" in res
    assert res["_billing_unit"] == 1
    assert res["total"] >= 1
    assert "税理士法" in res["_disclaimer"]
    # 3-axis citation check on the first result.
    first = res["results"][0]
    for key in ("source_url", "retrieved_at", "sha256"):
        assert first.get(key)
    # Shingikai impl returns the canonical envelope on empty rows too.
    res2 = _search_shingikai_minutes_impl(council="税制調査会")
    assert "results" in res2
    assert "_disclaimer" in res2
    assert res2["total"] == 0


# ---------------------------------------------------------------------------
# 5. LLM-0 guard — DEEP-39 files must not import any LLM SDK.
# ---------------------------------------------------------------------------


_FORBIDDEN_LLM_HEADS = {"anthropic", "openai", "claude_agent_sdk"}


def _has_forbidden_imports(py_path: Path) -> list[str]:
    """Return forbidden module names imported in py_path (AST scan)."""
    src = py_path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    hits: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                head = alias.name.split(".")[0]
                if head in _FORBIDDEN_LLM_HEADS:
                    hits.append(alias.name)
                if alias.name.startswith("google.generativeai"):
                    hits.append(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            head = node.module.split(".")[0]
            if head in _FORBIDDEN_LLM_HEADS:
                hits.append(node.module)
            if node.module.startswith("google.generativeai"):
                hits.append(node.module)
    return hits


def test_no_llm_imports_in_deep39_files() -> None:
    """Acceptance #5: DEEP-39 files must not import LLM SDKs."""
    targets = [_KOKKAI_CRON, _SHINGIKAI_CRON, _TOOL_MODULE]
    for t in targets:
        hits = _has_forbidden_imports(t)
        assert not hits, f"{t.name}: forbidden LLM imports {hits}"


# ---------------------------------------------------------------------------
# 6. GHA workflow YAML must parse cleanly.
# ---------------------------------------------------------------------------


def test_kokkai_shingikai_workflow_yaml_valid() -> None:
    """Acceptance: workflow yaml parses, exposes weekly cron + 2 ingest steps."""
    yaml = pytest.importorskip("yaml")
    raw = _WORKFLOW.read_text(encoding="utf-8")
    data = yaml.safe_load(raw)
    assert data["name"] == "kokkai-shingikai-weekly"
    # YAML reserved word `on` becomes `True` after safe_load — handle both.
    on_block = data.get("on") or data.get(True)
    assert on_block is not None, "missing `on:` block in workflow"
    schedule = on_block["schedule"]
    assert any("0 21" in s["cron"] for s in schedule), "expected 06:00 JST cron"
    job = data["jobs"]["ingest"]
    step_names = [s.get("name", "") for s in job["steps"]]
    joined = " ".join(step_names).lower()
    assert "kokkai" in joined, f"missing kokkai ingest step in {step_names}"
    assert "shingikai" in joined, f"missing shingikai ingest step in {step_names}"
