"""DEEP-45 pubcomment test suite — 5 cases.

Coverage map (acceptance criteria from DEEP_45_egov_pubcomment_follow.md §8):

  1. test_pubcomment_migration_applies_idempotently — schema acceptance #1
  2. test_egov_mock_fetch                            — fetch path with mocked httpx
  3. test_keyword_match_classifier                   — keyword detection
  4. test_jpcite_relevant_auto_classifier            — relevance + cohort rollup
  5. test_no_llm_imports_in_deep45_files             — acceptance #5 (LLM 0 guard)
"""

from __future__ import annotations

import ast
import json
import sqlite3
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
_MIGRATION = _REPO_ROOT / "scripts" / "migrations" / "wave24_192_pubcomment_announcement.sql"
_ROLLBACK = (
    _REPO_ROOT / "scripts" / "migrations" / "wave24_192_pubcomment_announcement_rollback.sql"
)
_PUBCOMMENT_CRON = _REPO_ROOT / "scripts" / "cron" / "ingest_egov_pubcomment_daily.py"
_WORKFLOW = _REPO_ROOT / ".github" / "workflows" / "egov-pubcomment-daily.yml"
_TOOL_MODULE = (
    _REPO_ROOT / "src" / "jpintel_mcp" / "mcp" / "autonomath_tools" / "pubcomment_tools.py"
)


# ---------------------------------------------------------------------------
# 1. Migration applies idempotently and creates pubcomment_announcement table.
# ---------------------------------------------------------------------------


def test_pubcomment_migration_applies_idempotently(tmp_path) -> None:
    """Acceptance #1: pubcomment_announcement table + 3 indexes exist."""
    db_path = tmp_path / "test_autonomath.db"
    sql = _MIGRATION.read_text(encoding="utf-8")
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(sql)
        conn.commit()
        # Re-apply — must be idempotent.
        conn.executescript(sql)
        conn.commit()
        # Verify table exists.
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='pubcomment_announcement'"
        ).fetchall()
        assert {r[0] for r in rows} == {"pubcomment_announcement"}
        # Verify indexes.
        idx = conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='index' AND tbl_name='pubcomment_announcement' "
            "ORDER BY name"
        ).fetchall()
        idx_names = {r[0] for r in idx}
        assert "ix_pubcomment_announce_date" in idx_names
        assert "ix_pubcomment_deadline" in idx_names
        assert "ix_pubcomment_law_relevant" in idx_names
        # CHECK constraint enforced on jpcite_relevant.
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO pubcomment_announcement "
                "(id, ministry, target_law, announcement_date, comment_deadline, "
                " summary_text, full_text_url, retrieved_at, sha256, jpcite_relevant) "
                "VALUES ('x','財務省','税理士法','2026-05-01','2026-06-01',"
                "'summary','https://x','2026-05-01T00:00:00Z','abc',2)"
            )
        # Rollback applies cleanly.
        conn.executescript(_ROLLBACK.read_text(encoding="utf-8"))
        conn.commit()
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='pubcomment_announcement'"
        ).fetchall()
        assert rows == []
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 2. e-Gov API mock fetch — exercises fetcher with mocked httpx.
# ---------------------------------------------------------------------------


def test_egov_mock_fetch(tmp_path) -> None:
    """Acceptance: fetcher returns parsed records when the API is mocked."""
    import asyncio
    import importlib.util

    spec = importlib.util.spec_from_file_location("egov_cron", _PUBCOMMENT_CRON)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    page_1 = {
        "results": [
            {
                "id": "egov-001",
                "ministry": "財務省",
                "target_law": "税理士法",
                "announcement_date": "2026-04-01",
                "comment_deadline": "2026-05-01",
                "summary": "税理士法の改正案",
                "url": "https://search.e-gov.go.jp/case/001",
            },
            {
                "id": "egov-002",
                "ministry": "国税庁",
                "target_law": "適格請求書発行事業者公表サイト省令",
                "announcement_date": "2026-04-05",
                "comment_deadline": "2026-05-05",
                "summary": "適格請求書 制度の見直し",
                "url": "https://search.e-gov.go.jp/case/002",
            },
        ],
        "total": 2,
    }
    page_empty = {"results": [], "total": 2}

    responses = [
        MagicMock(status_code=200, json=lambda: page_1),
        MagicMock(status_code=200, json=lambda: page_empty),
    ]

    async def _runner() -> list[dict]:
        client = MagicMock()
        client.get = AsyncMock(side_effect=responses)
        sem = asyncio.Semaphore(1)
        return await mod._fetch_announcements(client, sem, "税理士法", "2026-01-01", max_records=10)

    out = asyncio.run(_runner())
    assert len(out) == 2
    assert out[0]["id"] == "egov-001"
    assert out[1]["target_law"] == "適格請求書発行事業者公表サイト省令"

    # Parser produces canonical row.
    row = mod.parse_announcement_record(out[0])
    assert row is not None
    assert row["id"] == "egov-001"
    assert row["ministry"] == "財務省"
    assert row["target_law"] == "税理士法"
    assert row["announcement_date"] == "2026-04-01"
    assert row["comment_deadline"] == "2026-05-01"
    assert row["sha256"] and len(row["sha256"]) == 64
    assert row["retrieved_at"].endswith("Z")

    # Missing required field returns None.
    bad = dict(out[0])
    bad.pop("id")
    assert mod.parse_announcement_record(bad) is None


# ---------------------------------------------------------------------------
# 3. Keyword match — KEYWORDS membership filter.
# ---------------------------------------------------------------------------


def test_keyword_match_classifier() -> None:
    """Acceptance: detect_keywords filters to KEYWORDS membership only."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("egov_cron2", _PUBCOMMENT_CRON)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    hits = mod.detect_keywords("税理士法 と 適格請求書 と 個人情報保護法 の議論")
    assert "税理士法" in hits
    assert "適格請求書" in hits
    assert "個人情報保護法" in hits
    assert mod.detect_keywords("関係ない 文章") == []
    # 10 keyword union confirmed.
    assert len(mod.KEYWORDS) == 10
    expected = {
        "税理士法",
        "弁護士法",
        "行政書士法",
        "司法書士法",
        "弁理士法",
        "社労士法",
        "公認会計士法",
        "補助金等適正化法",
        "適格請求書",
        "個人情報保護法",
    }
    assert set(mod.KEYWORDS) == expected


# ---------------------------------------------------------------------------
# 4. jpcite_relevant auto-classifier — relevance + cohort rollup.
# ---------------------------------------------------------------------------


def test_jpcite_relevant_auto_classifier() -> None:
    """Acceptance: classify_jpcite_relevance returns (flag, cohort JSON)."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("egov_cron3", _PUBCOMMENT_CRON)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    # No match -> 0, None.
    flag, impact = mod.classify_jpcite_relevance(summary="無関係 な 改正案", target_law="無関係法")
    assert flag == 0
    assert impact is None

    # 税理士法 hit -> sensitive 税理士 cohort.
    flag, impact = mod.classify_jpcite_relevance(
        summary="税理士法の改正に関する公示",
        target_law="税理士法",
    )
    assert flag == 1
    assert impact is not None
    parsed = json.loads(impact)
    assert "税理士法" in parsed["hit_keywords"]
    assert "税理士" in parsed["cohort_impact"]
    assert "税理士法" in parsed["cohort_impact"]["税理士"]

    # 補助金等適正化法 -> 補助金 consultant cohort.
    flag, impact = mod.classify_jpcite_relevance(
        summary="補助金等適正化法 の見直し",
        target_law="補助金等適正化法",
    )
    assert flag == 1
    parsed = json.loads(impact or "{}")
    assert "補助金 consultant" in parsed["cohort_impact"]

    # 適格請求書 -> 税理士 cohort.
    flag, impact = mod.classify_jpcite_relevance(
        summary="適格請求書 制度の改正",
        target_law="消費税法施行令",
    )
    assert flag == 1
    parsed = json.loads(impact or "{}")
    assert "適格請求書" in parsed["hit_keywords"]
    assert "税理士" in parsed["cohort_impact"]

    # Lead time heuristic.
    assert mod._lead_time_months("税理士法", "法律案 改正") == 2
    assert mod._lead_time_months("消費税法施行令", "省令の見直し") == 1


# ---------------------------------------------------------------------------
# 5. LLM-0 guard — DEEP-45 files must not import any LLM SDK.
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


def test_no_llm_imports_in_deep45_files() -> None:
    """Acceptance #5: DEEP-45 files must not import LLM SDKs."""
    targets = [_PUBCOMMENT_CRON, _TOOL_MODULE]
    for t in targets:
        hits = _has_forbidden_imports(t)
        assert not hits, f"{t.name}: forbidden LLM imports {hits}"
    # Workflow yaml exists.
    assert _WORKFLOW.exists(), f"missing workflow: {_WORKFLOW}"


def test_pubcomment_workflow_missing_db_dry_run_guard() -> None:
    """Scheduled CI runners do not mount production autonomath.db."""
    text = _WORKFLOW.read_text(encoding="utf-8")
    assert 'if [ ! -s "${AUTONOMATH_DB_PATH}" ]; then' in text
    assert "wave24_192_pubcomment_announcement.sql" in text
    assert 'DRY_FLAG="--dry-run"' in text
