"""Tests for ``scripts/cron/ingest_industry_journal_mention.py`` (DEEP-40).

5 cases covering the contract:
  1. mig_apply: wave24_186 SQL applies cleanly + idempotently to a fresh
     SQLite file, table + 4 indexes + UNIQUE constraint exist.
  2. api_mock_fetch: CiNii / J-STAGE / publisher_toc fetchers parse a
     mocked HTTP response and return the expected list of records.
  3. keyword_grep: ``_grep_keywords`` finds all 6 keywords with case +
     half-width fold, snippet capped at 50 chars (著作権 fence).
  4. self_vs_other_ratio: ``_is_self_authored`` flags author strings
     containing 梅田茂利 / Bookyou; an end-to-end run on a stub-fetch
     scenario produces consistent self/other counters.
  5. llm_zero: AST scan asserts the cron module has zero forbidden
     LLM imports (anthropic / openai / google.generativeai /
     claude_agent_sdk) — same invariant as
     ``tests/test_no_llm_in_production.py``.
"""

from __future__ import annotations

import ast
import importlib.util
import sqlite3
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "cron" / "ingest_industry_journal_mention.py"
MIGRATION_PATH = REPO_ROOT / "scripts" / "migrations" / "wave24_186_industry_journal_mention.sql"
ROLLBACK_PATH = REPO_ROOT / "scripts" / "migrations" / "wave24_186_industry_journal_mention_rollback.sql"


@pytest.fixture(scope="module")
def cron_module():
    """Side-load the cron script as a module."""
    spec = importlib.util.spec_from_file_location("ingest_industry_journal_mention", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["ingest_industry_journal_mention"] = module
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# 1. mig_apply
# ---------------------------------------------------------------------------


def test_migration_applies_cleanly(tmp_path):
    """wave24_186 SQL creates table + indexes + UNIQUE constraint, idempotent."""
    db_path = tmp_path / "test_autonomath.db"
    sql = MIGRATION_PATH.read_text(encoding="utf-8")

    conn = sqlite3.connect(db_path)
    try:
        # First apply
        conn.executescript(sql)
        conn.commit()

        # Verify table exists
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='industry_journal_mention'"
        ).fetchall()
        assert len(rows) == 1

        # Verify all 4 indexes
        idx_rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'ix_ijm_%' ORDER BY name"
        ).fetchall()
        idx_names = [r[0] for r in idx_rows]
        assert "ix_ijm_issue_cohort" in idx_names
        assert "ix_ijm_self_authored" in idx_names
        assert "ix_ijm_keyword" in idx_names
        assert "ix_ijm_journal" in idx_names

        # Verify UNIQUE constraint via insert-collision behavior
        conn.execute(
            "INSERT INTO industry_journal_mention(journal_name, cohort, issue_date, article_title, "
            "mention_keyword, source_url, source_layer, retrieved_at) VALUES (?,?,?,?,?,?,?,?)",
            ("税務通信", "税理士", "2026-04", "サンプル記事", "jpcite", "https://x", "cinii", "2026-05-07T00:00:00+00:00"),
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO industry_journal_mention(journal_name, cohort, issue_date, article_title, "
                "mention_keyword, source_url, source_layer, retrieved_at) VALUES (?,?,?,?,?,?,?,?)",
                ("税務通信", "税理士", "2026-04", "サンプル記事", "jpcite", "https://x", "cinii", "2026-05-07T00:00:00+00:00"),
            )

        # Idempotent re-apply (CREATE IF NOT EXISTS) — must not raise
        conn.executescript(sql)
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 2. api_mock_fetch
# ---------------------------------------------------------------------------


def test_api_mock_fetch_cinii_jstage_toc(cron_module):
    """All three fetchers parse a stubbed response into normalized records."""
    # CiNii: minimal valid JSON shape
    cinii_payload = (
        '{"@graph": [{"items": [{"title": "jpcite を活用した税務 DX",'
        ' "dc:creator": ["梅田 茂利"], "prism:publicationName": "税務通信",'
        ' "prism:publicationDate": "2026-04-15", "@id": "https://cir.nii.ac.jp/foo"}]}]}'
    )

    with patch.object(cron_module, "_safe_get", return_value=cinii_payload):
        cinii_records = cron_module.fetch_cinii("jpcite", year_from=2026, year_to=2026)
    assert len(cinii_records) == 1
    assert cinii_records[0]["article_title"].startswith("jpcite")
    assert cinii_records[0]["journal_name"] == "税務通信"
    assert cinii_records[0]["issue_date"] == "2026-04"

    # J-STAGE: minimal Atom payload
    jstage_payload = (
        '<feed><entry><title>jpcite と監査ガバナンス</title>'
        '<link href="https://www.jstage.jst.go.jp/foo"/>'
        "<name>佐藤 花子</name><published>2026-03-10</published>"
        "</entry></feed>"
    )
    with patch.object(cron_module, "_safe_get", return_value=jstage_payload):
        jstage_records = cron_module.fetch_jstage("monkan", "jpcite")
    assert len(jstage_records) == 1
    assert jstage_records[0]["article_title"] == "jpcite と監査ガバナンス"
    assert jstage_records[0]["issue_date"] == "2026-03"

    # publisher_toc: minimal HTML <a> tag with kanji content
    toc_payload = (
        '<html><body>'
        '<a href="https://www.zeiken.co.jp/article/2026/04/jpcite">jpcite で税務通信2026年4月号特集</a>'
        '</body></html>'
    )
    with patch.object(cron_module, "_safe_get", return_value=toc_payload):
        toc_records = cron_module.fetch_publisher_toc("https://www.zeiken.co.jp/news/")
    assert len(toc_records) >= 1
    assert any("jpcite" in r["article_title"] for r in toc_records)


# ---------------------------------------------------------------------------
# 3. keyword_grep — case + half-width fold, 50-char snippet cap
# ---------------------------------------------------------------------------


def test_keyword_grep_finds_all_keywords_and_caps_snippet(cron_module):
    """All 6 keywords detected case-insensitively; snippet ≤ 50 chars."""
    samples = [
        ("jpcite を活用した税務 DX 事例研究", "jpcite"),
        ("ジェイピーサイトを使った業務改善のすすめ", "ジェイピーサイト"),
        ("Bookyou株式会社が開発する API", "Bookyou"),
        ("旧 AutonoMath ブランドからの移行", "AutonoMath"),
        ("オートノマス時代の税理士", "オートノマス"),
        ("適格事業者 T8010001213708 の引用", "T8010001213708"),
    ]
    for text, expected_kw in samples:
        hits = cron_module._grep_keywords(text)
        assert any(kw == expected_kw for kw, _ in hits), f"missing {expected_kw} in {text!r}"
        for _, snippet in hits:
            assert len(snippet) <= 50, f"snippet too long: {snippet!r}"

    # Case-insensitive: lower-case keyword in upper-case text
    hits_upper = cron_module._grep_keywords("JPCITEを採用するメリット")
    assert any(kw == "jpcite" for kw, _ in hits_upper)

    # No keyword → empty
    assert cron_module._grep_keywords("関係のない記事タイトル") == []
    # Empty input
    assert cron_module._grep_keywords("") == []


# ---------------------------------------------------------------------------
# 4. self_vs_other ratio
# ---------------------------------------------------------------------------


def test_self_vs_other_ratio(cron_module, tmp_path):
    """is_self_authored flags 梅田茂利 / Bookyou; counters split correctly."""
    # Marker assertions
    assert cron_module._is_self_authored("梅田 茂利") == 1
    assert cron_module._is_self_authored("梅田茂利; 山田太郎") == 1
    assert cron_module._is_self_authored("Bookyou株式会社") == 1
    assert cron_module._is_self_authored("Umeda Shigetoshi") == 1
    assert cron_module._is_self_authored("山田 太郎") == 0
    assert cron_module._is_self_authored("") == 0
    assert cron_module._is_self_authored(None) == 0

    # End-to-end with stubbed CiNii returning 1 self + 1 other
    db_path = tmp_path / "test_autonomath.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(MIGRATION_PATH.read_text(encoding="utf-8"))
        conn.commit()
    finally:
        conn.close()

    cinii_payload = (
        '{"@graph": [{"items": ['
        '{"title": "jpcite を活用した実務 (自著)",'
        ' "dc:creator": ["梅田 茂利"], "prism:publicationName": "税務通信",'
        ' "prism:publicationDate": "2026-04-15", "@id": "https://cir.nii.ac.jp/self"},'
        '{"title": "jpcite の評価レポート",'
        ' "dc:creator": ["山田 太郎"], "prism:publicationName": "税務通信",'
        ' "prism:publicationDate": "2026-04-15", "@id": "https://cir.nii.ac.jp/other"}'
        ']}]}'
    )

    with patch.object(cron_module, "_safe_get", return_value=cinii_payload):
        with patch.object(cron_module.time, "sleep", return_value=None):
            counters = cron_module.run(db_path, months_back=1, sleep_sec=0.0, dry_run=False)

    # CiNii pass alone — TOC + jstage 経路は real network なので _safe_get patch で全 None
    assert counters["mentions_inserted"] >= 2
    assert counters["self_vs_other"]["self"] >= 1
    assert counters["self_vs_other"]["other"] >= 1


# ---------------------------------------------------------------------------
# 5. llm_zero — AST scan asserts no forbidden LLM imports
# ---------------------------------------------------------------------------


def test_no_llm_imports_in_cron_module():
    """Mirror of tests/test_no_llm_in_production.py invariant for this cron."""
    forbidden_heads = {"anthropic", "openai", "claude_agent_sdk"}
    src = SCRIPT_PATH.read_text(encoding="utf-8")
    tree = ast.parse(src)

    hits: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                head = (alias.name or "").split(".")[0]
                if head in forbidden_heads:
                    hits.append(f"import {alias.name}")
                if alias.name == "google.generativeai" or (alias.name or "").startswith("google.generativeai."):
                    hits.append(f"import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            head = module.split(".")[0]
            if head in forbidden_heads:
                hits.append(f"from {module} import ...")
            if module == "google.generativeai" or module.startswith("google.generativeai."):
                hits.append(f"from {module} import ...")

    assert hits == [], f"forbidden LLM imports detected: {hits}"

    # Belt-and-suspenders: no LLM API-key env-var lookups either.
    forbidden_envs = ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY")
    for env_name in forbidden_envs:
        assert env_name not in src, f"LLM API key env var leaked: {env_name}"
