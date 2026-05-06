"""DEEP-44 自治体 補助金 weekly diff cron test suite — 5 cases.

Coverage map (acceptance criteria from DEEP_44_municipality_subsidy_weekly_diff.md):

  1. test_migration_applies_idempotently        — schema + idempotency
  2. test_67_seed_url_parse                     — 1st pass seed list integrity
  3. test_aggregator_url_reject                 — 1次資料 only guard
  4. test_sha256_diff_detection                 — diff detection on re-run
  5. test_no_llm_imports_in_deep44_files        — LLM 0 guard (acceptance #4)
"""

from __future__ import annotations

import ast
import importlib.util
import json
import sqlite3
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
_MIGRATION = _REPO_ROOT / "scripts" / "migrations" / "wave24_191_municipality_subsidy.sql"
_ROLLBACK = _REPO_ROOT / "scripts" / "migrations" / "wave24_191_municipality_subsidy_rollback.sql"
_CRON = _REPO_ROOT / "scripts" / "cron" / "ingest_municipality_subsidy_weekly.py"
_SEED = _REPO_ROOT / "data" / "municipality_seed_urls.json"
_TOOL_MODULE = (
    _REPO_ROOT / "src" / "jpintel_mcp" / "mcp" / "autonomath_tools" / "municipality_tools.py"
)


def _load_cron_module():
    spec = importlib.util.spec_from_file_location("deep44_cron", _CRON)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# 1. Migration applies idempotently and creates 1 table + indexes.
# ---------------------------------------------------------------------------


def test_migration_applies_idempotently(tmp_path) -> None:
    """Acceptance: municipality_subsidy table + 3 indexes after migration apply (twice)."""
    db_path = tmp_path / "test_jpintel.db"
    sql = _MIGRATION.read_text(encoding="utf-8")
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(sql)
        conn.commit()
        # Re-apply — must be idempotent (IF NOT EXISTS everywhere).
        conn.executescript(sql)
        conn.commit()

        # Verify table.
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='municipality_subsidy'"
        ).fetchall()
        assert {r[0] for r in rows} == {"municipality_subsidy"}

        # Verify indexes.
        idx = conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='index' AND tbl_name='municipality_subsidy' "
            "AND name LIKE 'ix_%' "
            "ORDER BY name"
        ).fetchall()
        idx_names = {r[0] for r in idx}
        assert "ix_ms_pref_muni" in idx_names
        assert "ix_ms_sha256" in idx_names
        assert "ix_ms_status_retrieved" in idx_names

        # Verify CHECK enums on muni_type + page_status.
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO municipality_subsidy "
                "(pref, muni_code, muni_name, muni_type, subsidy_url, "
                " sha256, page_status) "
                "VALUES ('東京都','130001','東京都','bogus','https://x',"
                "        'a'*64,'active')"
            )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO municipality_subsidy "
                "(pref, muni_code, muni_name, muni_type, subsidy_url, "
                " sha256, page_status) "
                "VALUES ('東京都','130001','東京都','prefecture','https://x',"
                "        'a'*64,'500')"
            )

        # Valid insert + UNIQUE constraint enforcement.
        conn.execute(
            "INSERT INTO municipality_subsidy "
            "(pref, muni_code, muni_name, muni_type, subsidy_url, "
            " sha256, page_status) "
            "VALUES ('東京都','130001','東京都','prefecture','https://x','h1','active')"
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO municipality_subsidy "
                "(pref, muni_code, muni_name, muni_type, subsidy_url, "
                " sha256, page_status) "
                "VALUES ('東京都','130001','東京都','prefecture','https://x','h2','active')"
            )

        # Rollback applies cleanly.
        conn.executescript(_ROLLBACK.read_text(encoding="utf-8"))
        conn.commit()
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='municipality_subsidy'"
        ).fetchall()
        assert rows == []
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 2. 67 seed URL parse — 1st pass integrity (47 都道府県 + 20 政令市).
# ---------------------------------------------------------------------------


def test_67_seed_url_parse() -> None:
    """Acceptance: 67 seed rows = 47 prefecture + 20 seirei, all .lg.jp / metro."""
    assert _SEED.exists()
    data = json.loads(_SEED.read_text(encoding="utf-8"))
    assert isinstance(data, list)
    assert len(data) == 67, f"expected 67 seed rows, got {len(data)}"

    types = {row["muni_type"] for row in data}
    assert types == {"prefecture", "seirei"}

    pref_rows = [r for r in data if r["muni_type"] == "prefecture"]
    seirei_rows = [r for r in data if r["muni_type"] == "seirei"]
    assert len(pref_rows) == 47
    assert len(seirei_rows) == 20

    # Each row carries the required keys.
    for row in data:
        for key in ("pref", "muni_code", "muni_name", "muni_type", "subsidy_url"):
            assert key in row, f"missing {key} in {row}"
        assert row["muni_code"].isdigit()
        assert len(row["muni_code"]) == 6
        # All 1次資料 URLs must be on government / municipality domains.
        # 自治体 patterns: .lg.jp / .go.jp / pref.*.jp / city.*.jp / metro.tokyo.
        url_lower = row["subsidy_url"].lower()
        is_govt = (
            ".lg.jp" in url_lower
            or ".go.jp" in url_lower
            or "metro.tokyo" in url_lower
            or ("pref." in url_lower and url_lower.endswith(".jp") or "pref." in url_lower)
            or ("city." in url_lower)
        )
        assert is_govt, f"non-1次資料 URL in seed: {row['subsidy_url']}"

    # No duplicate muni_code.
    codes = [r["muni_code"] for r in data]
    assert len(codes) == len(set(codes)), "duplicate muni_code in seed"


# ---------------------------------------------------------------------------
# 3. Aggregator URL reject — CLAUDE.md データ衛生規約.
# ---------------------------------------------------------------------------


def test_aggregator_url_reject() -> None:
    """Acceptance #3: aggregator URLs must be rejected before fetch."""
    mod = _load_cron_module()

    # Aggregator banlist hits.
    banned_urls = [
        "https://noukaweb.com/post/123",
        "https://hojyokin-portal.jp/list",
        "https://biz.stayway.jp/article/1",
        "https://stayway.jp/anything",
        "https://subsidies-japan.com/x",
        "https://jgrant-aggregator.example/x",
        "https://www.nikkei.com/article/x",
        "https://prtimes.jp/main/x",
        "https://ja.wikipedia.org/wiki/x",
    ]
    for url in banned_urls:
        assert mod.is_aggregator_url(url), f"should reject aggregator: {url}"
        assert not mod.is_allowed_municipality_url(url), f"aggregator slipped allowlist: {url}"

    # 1次資料 must pass.
    legit_urls = [
        "https://www.metro.tokyo.lg.jp/jigyo/index.html",
        "https://www.city.shinjuku.lg.jp/sangyo/josei/index.html",
        "https://www.pref.hokkaido.lg.jp/kz/kgi/sangyoshien.html",
        "https://www.city.sapporo.jp/keizai/index.html",
        "https://www.chusho.meti.go.jp/keiei/sapoin/index.html",
    ]
    for url in legit_urls:
        assert not mod.is_aggregator_url(url), f"false positive ban: {url}"
        assert mod.is_allowed_municipality_url(url), f"legit url rejected: {url}"


# ---------------------------------------------------------------------------
# 4. sha256 diff detection — re-run with same content -> skipped, content
#                            change -> updated.
# ---------------------------------------------------------------------------


def test_sha256_diff_detection(tmp_path) -> None:
    """Acceptance: re-ingest same payload returns 'skipped'; changed -> 'updated'."""
    db_path = tmp_path / "test_jpintel.db"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.executescript(_MIGRATION.read_text(encoding="utf-8"))

    mod = _load_cron_module()
    base_row = {
        "pref": "東京都",
        "muni_code": "130001",
        "muni_name": "東京都",
        "muni_type": "prefecture",
        "subsidy_url": "https://www.metro.tokyo.lg.jp/jigyo/x.html",
        "subsidy_name": "創業 補助金",
        "eligibility_text": "中小企業者",
        "amount_text": "上限 100万円",
        "deadline_text": "令和8年6月30日",
        "retrieved_at": "2026-05-07T03:00:00Z",
        "sha256": mod.compute_sha256(b"<html>v1</html>"),
        "page_status": "active",
    }

    status = mod._upsert_subsidy(conn, dict(base_row))
    assert status == "inserted"

    # Re-insert same sha256 — should be 'skipped'.
    skip_row = dict(base_row)
    skip_row["retrieved_at"] = "2026-05-14T03:00:00Z"
    status = mod._upsert_subsidy(conn, skip_row)
    assert status == "skipped"

    # New content (different sha256) — should be 'updated'.
    upd_row = dict(base_row)
    upd_row["sha256"] = mod.compute_sha256(b"<html>v2</html>")
    upd_row["retrieved_at"] = "2026-05-14T03:00:00Z"
    upd_row["amount_text"] = "上限 200万円"
    status = mod._upsert_subsidy(conn, upd_row)
    assert status == "updated"

    # Verify single row remains (UNIQUE constraint enforced) with new content.
    rows = conn.execute(
        "SELECT amount_text, sha256 FROM municipality_subsidy WHERE muni_code='130001'"
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["amount_text"] == "上限 200万円"
    assert rows[0]["sha256"] == upd_row["sha256"]

    conn.close()


# ---------------------------------------------------------------------------
# 5. LLM-0 guard — DEEP-44 files must not import any LLM SDK.
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
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                head = node.module.split(".")[0]
                if head in _FORBIDDEN_LLM_HEADS:
                    hits.append(node.module)
                if node.module.startswith("google.generativeai"):
                    hits.append(node.module)
    return hits


def test_no_llm_imports_in_deep44_files() -> None:
    """Acceptance #4: DEEP-44 files must not import LLM SDKs."""
    targets = [_CRON, _TOOL_MODULE]
    for t in targets:
        assert t.exists(), f"missing DEEP-44 file: {t}"
        hits = _has_forbidden_imports(t)
        assert hits == [], f"LLM imports detected in {t}: {hits}"
