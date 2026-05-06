"""DEEP-41 brand mention dashboard - 6 acceptance test cases.

Spec: tools/offline/_inbox/value_growth_dual/_deep_plan/DEEP_41_brand_mention_dashboard.md
Migration: scripts/migrations/wave24_187_brand_mention.sql (target_db: autonomath)
Cron: scripts/cron/scrape_brand_signals.py (10 sources, weekly)

The 6 cases:
    1.  migration applies cleanly (idempotent re-run, indexes + views present)
    2.  10-source mock fetch round-trips through insert_rows
    3.  classify_kind: self vs other reaches >= 95% accuracy on labeled sample
    4.  dedup via UNIQUE (source, mention_url) — INSERT OR IGNORE pathway
    5.  LLM-import guard — no anthropic / openai / claude_agent_sdk in cron file
    6.  dashboard JSON validates structurally against expected schema
"""

from __future__ import annotations

import ast
import json
import pathlib
import sqlite3
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
MIG_SQL = REPO_ROOT / "scripts" / "migrations" / "wave24_187_brand_mention.sql"
ROLLBACK_SQL = REPO_ROOT / "scripts" / "migrations" / "wave24_187_brand_mention_rollback.sql"
CRON_PY = REPO_ROOT / "scripts" / "cron" / "scrape_brand_signals.py"
ALLOWLIST_JSON = REPO_ROOT / "data" / "brand_self_accounts.json"
DASHBOARD_JSON = REPO_ROOT / "analytics" / "brand_community_dashboard.json"
TRANSPARENCY_HTML = REPO_ROOT / "site" / "transparency" / "brand-health.html"

# Make scripts.cron importable (it is a normal package via __init__.py absence
# requires sys.path injection in some test layouts).
sys.path.insert(0, str(REPO_ROOT / "scripts" / "cron"))
import scrape_brand_signals as sbs  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _apply_migration(db_path: str) -> None:
    sql = MIG_SQL.read_text(encoding="utf-8")
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(sql)
        conn.commit()
    finally:
        conn.close()


def _conn(db_path: str) -> sqlite3.Connection:
    return sqlite3.connect(db_path)


# ---------------------------------------------------------------------------
# Case 1: migration applies cleanly + idempotent
# ---------------------------------------------------------------------------


def test_case_1_migration_applies_idempotent(tmp_path):
    db = tmp_path / "test_autonomath.db"
    _apply_migration(str(db))
    # Re-apply must not raise.
    _apply_migration(str(db))
    with _conn(str(db)) as c:
        # table exists
        names = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert "brand_mention" in names
        # 2 indexes + 1 unique
        idxs = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='index'")}
        assert "idx_brand_mention_source_date" in idxs
        assert "idx_brand_mention_kind_date" in idxs
        # 3 views
        views = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='view'")}
        assert "v_brand_mention_source_rollup" in views
        assert "v_brand_mention_monthly_trend" in views
        assert "v_brand_mention_root_kpi" in views


# ---------------------------------------------------------------------------
# Case 2: 10-source mock fetch round-trips (insert_rows accepts each source)
# ---------------------------------------------------------------------------


def test_case_2_ten_source_mock_insert(tmp_path):
    db = tmp_path / "test_autonomath.db"
    _apply_migration(str(db))
    allowlist = sbs.load_allowlist(ALLOWLIST_JSON)
    # 1 row per source = 10 rows
    rows = [
        {
            "source": "github",
            "mention_url": "https://github.com/owner/repo/issues/1",
            "author": "stranger1",
            "mention_date": "2026-05-01",
            "snippet": "uses jpcite for citation",
        },
        {
            "source": "pypi",
            "mention_url": "https://pypi.org/project/autonomath-mcp/",
            "author": "bookyou",
            "mention_date": "2026-05-01",
            "snippet": "downloads",
        },
        {
            "source": "npm",
            "mention_url": "https://www.npmjs.com/package/@jpcite/disclaimer-spec",
            "author": "@jpcite",
            "mention_date": "2026-05-01",
            "snippet": "downloads",
        },
        {
            "source": "zenn",
            "mention_url": "https://zenn.dev/some_user/articles/abc",
            "author": "some_user",
            "mention_date": "2026-05-01",
            "snippet": "jpcite を使ってみた",
        },
        {
            "source": "qiita",
            "mention_url": "https://qiita.com/foo/items/xyz",
            "author": "foo",
            "mention_date": "2026-05-01",
            "snippet": "autonomath で...",
        },
        {
            "source": "x",
            "mention_url": "https://twitter.com/random_dev/status/12345",
            "author": "random_dev",
            "mention_date": "2026-05-01",
            "snippet": "x post",
        },
        {
            "source": "hn",
            "mention_url": "https://news.ycombinator.com/item?id=98765",
            "author": "hnuser",
            "mention_date": "2026-05-01",
            "snippet": "Show HN: jpcite",
        },
        {
            "source": "lobsters",
            "mention_url": "https://lobste.rs/s/abc/jpcite_review",
            "author": "lobster_dev",
            "mention_date": "2026-05-01",
            "snippet": "RSS feed item",
        },
        {
            "source": "industry_journal",
            "mention_url": "https://example-tax-journal.example/article/1",
            "author": "税務通信",
            "mention_date": "2026-05-01",
            "snippet": "jpcite に言及",
        },
        {
            "source": "industry_assoc",
            "mention_url": "https://nichizeiren.example/report/2026.pdf",
            "author": "日税連 ICT 委員会",
            "mention_date": "2026-05-01",
            "snippet": "推奨ツール",
        },
    ]
    counts = sbs.insert_rows(str(db), rows, allowlist)
    # Each of the 10 sources got at least 1 insert.
    for src in sbs.ALL_SOURCES:
        assert counts[src] >= 1, f"missing insert for source={src}"
    with _conn(str(db)) as c:
        total = c.execute("SELECT COUNT(*) FROM brand_mention").fetchone()[0]
        assert total == 10
        sources = {r[0] for r in c.execute("SELECT DISTINCT source FROM brand_mention")}
        assert sources == set(sbs.ALL_SOURCES)


# ---------------------------------------------------------------------------
# Case 3: classify self vs other accuracy >= 95% on labeled sample
# ---------------------------------------------------------------------------


def test_case_3_classify_self_vs_other_accuracy_95(tmp_path):
    allowlist = sbs.load_allowlist(ALLOWLIST_JSON)
    # Hand-labeled 50-row sample (acceptance target: 95% = >= 48/50 correct).
    # 25 self + 25 other.
    labeled = [
        # ----- 25 self -----
        ("github", "bookyou", "self"),
        ("github", "umeda-shigetoshi", "self"),
        ("github", "jpcite", "self"),
        ("github", "jpcite-bot", "self"),
        ("pypi", "bookyou", "self"),
        ("pypi", "jpcite", "self"),
        ("npm", "@jpcite", "self"),
        ("npm", "jpcite", "self"),
        ("zenn", "umeda_shigetoshi", "self"),
        ("zenn", "bookyou", "self"),
        ("zenn", "jpcite", "self"),
        ("qiita", "umeda_shigetoshi", "self"),
        ("qiita", "bookyou", "self"),
        ("x", "umeda_shigetoshi", "self"),
        ("x", "jpcite_official", "self"),
        ("x", "bookyou_official", "self"),
        ("hn", "umeda_shigetoshi", "self"),
        ("hn", "jpcite", "self"),
        ("lobsters", "umeda_shigetoshi", "self"),
        ("lobsters", "jpcite", "self"),
        ("industry_journal", "Bookyou株式会社", "self"),
        ("industry_journal", "info@bookyou.net", "self"),
        ("industry_journal", "梅田茂利", "self"),
        ("industry_assoc", "Bookyou株式会社", "self"),
        ("industry_assoc", "梅田茂利", "self"),
        # ----- 25 other -----
        ("github", "stranger_dev", "other"),
        ("github", "alice123", "other"),
        ("github", "bob_codes", "other"),
        ("pypi", "random-pypi-user", "other"),
        ("npm", "@random/scope", "other"),
        ("zenn", "random_zenn_writer", "other"),
        ("zenn", "tech_writer_x", "other"),
        ("qiita", "qiita_user_42", "other"),
        ("qiita", "blogger_y", "other"),
        ("x", "random_handle", "other"),
        ("x", "another_user", "other"),
        ("hn", "hn_anon", "other"),
        ("hn", "another_hn_user", "other"),
        ("lobsters", "lobster_walker", "other"),
        ("lobsters", "rust_dev", "other"),
        ("industry_journal", "税務通信", "other"),
        ("industry_journal", "月報司法書士", "other"),
        ("industry_journal", "日経新聞", "other"),
        ("industry_assoc", "日税連 ICT 委員会", "other"),
        ("industry_assoc", "日司連 IT 部会", "other"),
        ("industry_assoc", "日弁連 ICT 戦略本部", "other"),
        ("github", "random_user_2", "other"),
        ("github", None, "other"),  # null author defaults other
        ("zenn", "", "other"),  # empty author defaults other
        ("qiita", "third_party_eng", "other"),
    ]
    correct = 0
    for src, author, expected in labeled:
        got = sbs.classify_kind(src, author, allowlist)
        if got == expected:
            correct += 1
    accuracy = correct / len(labeled)
    assert accuracy >= 0.95, (
        f"classify accuracy {accuracy:.2%} < 95% (correct={correct}/{len(labeled)})"
    )


# ---------------------------------------------------------------------------
# Case 4: dedup via UNIQUE constraint - duplicate URLs ignored
# ---------------------------------------------------------------------------


def test_case_4_dedup_unique_url_hash(tmp_path):
    db = tmp_path / "test_autonomath.db"
    _apply_migration(str(db))
    allowlist = sbs.load_allowlist(ALLOWLIST_JSON)
    rows = [
        {
            "source": "github",
            "mention_url": "https://github.com/x/y/issues/1",
            "author": "alice",
            "mention_date": "2026-05-01",
            "snippet": "first",
        },
        {
            "source": "github",
            "mention_url": "https://github.com/x/y/issues/1",  # dup
            "author": "alice",
            "mention_date": "2026-05-01",
            "snippet": "duplicate",
        },
        {
            "source": "zenn",
            "mention_url": "https://zenn.dev/a/articles/b",
            "author": "a",
            "mention_date": "2026-05-01",
            "snippet": "first",
        },
        {
            "source": "zenn",
            "mention_url": "https://zenn.dev/a/articles/b",  # dup
            "author": "a",
            "mention_date": "2026-05-01",
            "snippet": "duplicate",
        },
    ]
    sbs.insert_rows(str(db), rows, allowlist)
    # Re-run with the same payload — total must stay at 2.
    sbs.insert_rows(str(db), rows, allowlist)
    with _conn(str(db)) as c:
        total = c.execute("SELECT COUNT(*) FROM brand_mention").fetchone()[0]
        assert total == 2, f"dedup failed, total={total} (expected 2)"


# ---------------------------------------------------------------------------
# Case 5: LLM 0 — no forbidden imports anywhere in the cron file
# ---------------------------------------------------------------------------


def test_case_5_llm_zero_no_forbidden_imports():
    src = CRON_PY.read_text(encoding="utf-8")
    tree = ast.parse(src)
    forbidden = {"anthropic", "openai", "google.generativeai", "claude_agent_sdk"}
    bad_imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                head = alias.name.split(".")[0]
                if head in {"anthropic", "openai", "claude_agent_sdk"}:
                    bad_imports.append(f"import {alias.name}")
                if alias.name == "google.generativeai":
                    bad_imports.append(f"import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                head = node.module.split(".")[0]
                if head in {"anthropic", "openai", "claude_agent_sdk"}:
                    bad_imports.append(f"from {node.module}")
                if node.module == "google.generativeai" or node.module.startswith(
                    "google.generativeai."
                ):
                    bad_imports.append(f"from {node.module}")
    assert not bad_imports, f"forbidden LLM imports in cron: {bad_imports}"
    # Also assert no bare "anthropic"/"openai" string is wired as a real call
    # by checking the env vars list is not referenced as os.environ get.
    for env in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
        assert env not in src, f"forbidden env var {env} referenced in cron"


# ---------------------------------------------------------------------------
# Case 6: dashboard JSON validates against expected schema
# ---------------------------------------------------------------------------


def test_case_6_dashboard_json_schema_valid():
    assert DASHBOARD_JSON.exists(), "dashboard JSON template missing"
    payload = json.loads(DASHBOARD_JSON.read_text(encoding="utf-8"))
    # Required top-level keys
    required = {
        "generated_at",
        "source_counts",
        "self_vs_other_ratio",
        "top_mentioner_monthly",
        "sentiment_proxy",
        "monthly_trend",
    }
    assert required.issubset(payload.keys()), f"missing keys: {required - payload.keys()}"
    # Source counts must cover all 10 sources
    sc = payload["source_counts"]
    assert set(sc.keys()) >= set(sbs.ALL_SOURCES), (
        f"source_counts missing: {set(sbs.ALL_SOURCES) - set(sc.keys())}"
    )
    for src, count in sc.items():
        assert isinstance(count, int) and count >= 0, f"bad count for {src}: {count!r}"
    # self_vs_other shape
    sv = payload["self_vs_other_ratio"]
    for k in ("self_count", "other_count", "ratio_other_per_self", "organic_self_walking"):
        assert k in sv, f"missing self_vs_other_ratio.{k}"
    assert isinstance(sv["self_count"], int)
    assert isinstance(sv["other_count"], int)
    assert isinstance(sv["organic_self_walking"], bool)
    # sentiment proxy
    sp = payload["sentiment_proxy"]
    assert "kw_lists" in sp
    assert "positive" in sp["kw_lists"] and "negative" in sp["kw_lists"]
    assert isinstance(sp["positive_kw_count"], int)
    assert isinstance(sp["negative_kw_count"], int)
    # monthly_trend list
    assert isinstance(payload["monthly_trend"], list)


# ---------------------------------------------------------------------------
# Bonus: rollback companion drops everything cleanly (sanity)
# ---------------------------------------------------------------------------


def test_rollback_companion_drops_all(tmp_path):
    db = tmp_path / "test_autonomath.db"
    _apply_migration(str(db))
    rb = ROLLBACK_SQL.read_text(encoding="utf-8")
    conn = sqlite3.connect(str(db))
    try:
        conn.executescript(rb)
        conn.commit()
        names = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table','view','index') AND name LIKE '%brand_mention%'"
            )
        }
        assert names == set(), f"rollback left objects: {names}"
    finally:
        conn.close()
