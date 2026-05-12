"""Integration tests for Dim S embedded copilot scaffold (Wave 47).

Closes the Wave 46 dim S storage gap: migration 279 adds
``am_copilot_widget_config`` (config table, 1 row per supported host SaaS)
and ``am_copilot_session_log`` (append-only OAuth-bridge audit) per
``feedback_copilot_scaffold_only_no_llm.md``. Pairs with
``scripts/etl/seed_copilot_widgets.py`` (4 widget seed: freee / MF /
Notion / Slack) and ``src/jpintel_mcp/api/copilot_scaffold.py`` (the
REST helper layer — LLM-0 by construction).

Case bundles
------------
  1. Migration 279 applies cleanly on a fresh SQLite db (idempotent re-apply).
  2. Migration 279 rollback drops every artefact created.
  3. CHECK constraints reject malformed rows (host_saas empty,
     embed_url non-https, mcp_proxy_url non-https, oauth_scope oversize,
     token_hash wrong length, ended_at < started_at).
  4. Seeder upserts 4 canonical widgets and is idempotent across re-runs.
  5. Helper view ``v_copilot_widget_enabled`` excludes disabled rows.
  6. ``copilot_scaffold.py`` open_session hashes the raw OAuth token
     (sha256, never stored raw) and ``close_session`` stamps ``ended_at``.
  7. Boot manifest registration (jpcite + autonomath mirror).
  8. **LLM-0 verify** — `grep -E "anthropic|openai" copilot_scaffold.py` = 0.

Hard constraints exercised
--------------------------
  * No LLM SDK import in any new file (scaffold is OAuth + MCP proxy only).
  * Schema is config + audit only; no prompt / response / completion column.
  * Brand: only jpcite. No legacy ``税務会計AI`` / ``zeimu-kaikei.ai``.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import sqlite3
import subprocess
import sys

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
MIG_279 = REPO_ROOT / "scripts" / "migrations" / "279_copilot_scaffold.sql"
MIG_279_RB = REPO_ROOT / "scripts" / "migrations" / "279_copilot_scaffold_rollback.sql"
ETL_SEED = REPO_ROOT / "scripts" / "etl" / "seed_copilot_widgets.py"
API_FILE = REPO_ROOT / "src" / "jpintel_mcp" / "api" / "copilot_scaffold.py"
MANIFEST_JPCITE = REPO_ROOT / "scripts" / "migrations" / "jpcite_boot_manifest.txt"
MANIFEST_AM = REPO_ROOT / "scripts" / "migrations" / "autonomath_boot_manifest.txt"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _apply(db_path: pathlib.Path, sql_path: pathlib.Path) -> None:
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(sql_path.read_text(encoding="utf-8"))
    finally:
        conn.close()


def _fresh_db(tmp_path: pathlib.Path) -> pathlib.Path:
    db = tmp_path / "dim_s.db"
    _apply(db, MIG_279)
    return db


# ---------------------------------------------------------------------------
# 1. Migration applies + is idempotent
# ---------------------------------------------------------------------------


def test_mig_279_applies_clean(tmp_path: pathlib.Path) -> None:
    db = _fresh_db(tmp_path)
    conn = sqlite3.connect(str(db))
    try:
        names = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type IN ('table','view') "
                "AND (name LIKE 'am_copilot_%' OR name LIKE 'v_copilot_%')"
            )
        }
        assert "am_copilot_widget_config" in names
        assert "am_copilot_session_log" in names
        assert "v_copilot_widget_enabled" in names
    finally:
        conn.close()


def test_mig_279_is_idempotent(tmp_path: pathlib.Path) -> None:
    db = _fresh_db(tmp_path)
    # Re-applying must not raise.
    _apply(db, MIG_279)


# ---------------------------------------------------------------------------
# 2. Rollback drops every artefact
# ---------------------------------------------------------------------------


def test_mig_279_rollback_drops_all(tmp_path: pathlib.Path) -> None:
    db = _fresh_db(tmp_path)
    _apply(db, MIG_279_RB)
    conn = sqlite3.connect(str(db))
    try:
        rows = conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type IN ('table','view','index') "
            "AND (name LIKE 'am_copilot_widget_config%' "
            "  OR name LIKE 'am_copilot_session_log%' "
            "  OR name LIKE 'v_copilot_widget_enabled%' "
            "  OR name LIKE 'idx_am_copilot_widget_config%' "
            "  OR name LIKE 'idx_am_copilot_session_log%')"
        ).fetchall()
        assert rows == []
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 3. CHECK constraints reject malformed rows
# ---------------------------------------------------------------------------


def test_check_host_saas_not_empty(tmp_path: pathlib.Path) -> None:
    db = _fresh_db(tmp_path)
    conn = sqlite3.connect(str(db))
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO am_copilot_widget_config "
                "(host_saas, embed_url, mcp_proxy_url) "
                "VALUES (?, ?, ?)",
                ("", "https://jpcite.ai/x", "https://jpcite.ai/y"),
            )
    finally:
        conn.close()


def test_check_embed_url_https_only(tmp_path: pathlib.Path) -> None:
    db = _fresh_db(tmp_path)
    conn = sqlite3.connect(str(db))
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO am_copilot_widget_config "
                "(host_saas, embed_url, mcp_proxy_url) "
                "VALUES (?, ?, ?)",
                ("freee", "http://insecure.example.com", "https://jpcite.ai/y"),
            )
    finally:
        conn.close()


def test_check_mcp_proxy_url_https_only(tmp_path: pathlib.Path) -> None:
    db = _fresh_db(tmp_path)
    conn = sqlite3.connect(str(db))
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO am_copilot_widget_config "
                "(host_saas, embed_url, mcp_proxy_url) "
                "VALUES (?, ?, ?)",
                ("freee", "https://jpcite.ai/x", "ftp://no/"),
            )
    finally:
        conn.close()


def test_check_token_hash_length(tmp_path: pathlib.Path) -> None:
    db = _fresh_db(tmp_path)
    conn = sqlite3.connect(str(db))
    try:
        conn.execute(
            "INSERT INTO am_copilot_widget_config "
            "(host_saas, embed_url, mcp_proxy_url) "
            "VALUES (?, ?, ?)",
            ("freee", "https://jpcite.ai/x", "https://jpcite.ai/y"),
        )
        conn.commit()
        widget_id = conn.execute(
            "SELECT widget_id FROM am_copilot_widget_config WHERE host_saas=?",
            ("freee",),
        ).fetchone()[0]
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO am_copilot_session_log (widget_id, user_token_hash) VALUES (?, ?)",
                (widget_id, "short"),
            )
    finally:
        conn.close()


def test_check_ended_at_after_started_at(tmp_path: pathlib.Path) -> None:
    db = _fresh_db(tmp_path)
    conn = sqlite3.connect(str(db))
    try:
        conn.execute(
            "INSERT INTO am_copilot_widget_config "
            "(host_saas, embed_url, mcp_proxy_url) "
            "VALUES (?, ?, ?)",
            ("freee", "https://jpcite.ai/x", "https://jpcite.ai/y"),
        )
        conn.commit()
        widget_id = conn.execute(
            "SELECT widget_id FROM am_copilot_widget_config WHERE host_saas=?",
            ("freee",),
        ).fetchone()[0]
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO am_copilot_session_log "
                "(widget_id, user_token_hash, started_at, ended_at) "
                "VALUES (?, ?, ?, ?)",
                (widget_id, "a" * 64, "2026-05-12T10:00:00Z", "2026-05-12T09:00:00Z"),
            )
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 4. Seeder upserts 4 canonical widgets + idempotency
# ---------------------------------------------------------------------------


def _run_seed(db: pathlib.Path, *extra: str) -> dict:
    proc = subprocess.run(
        [sys.executable, str(ETL_SEED), "--db", str(db), *extra],
        check=True,
        capture_output=True,
        text=True,
    )
    last_line = proc.stdout.strip().splitlines()[-1]
    return json.loads(last_line)


def test_seed_inserts_4_widgets(tmp_path: pathlib.Path) -> None:
    db = _fresh_db(tmp_path)
    rep = _run_seed(db)
    actions = {w["host_saas"]: w["action"] for w in rep["widgets"]}
    assert set(actions) == {"freee", "moneyforward", "notion", "slack"}
    for host, act in actions.items():
        assert act == "inserted", f"{host} should be inserted on first run"

    conn = sqlite3.connect(str(db))
    try:
        n = conn.execute("SELECT COUNT(*) FROM am_copilot_widget_config").fetchone()[0]
    finally:
        conn.close()
    assert n == 4


def test_seed_is_idempotent(tmp_path: pathlib.Path) -> None:
    db = _fresh_db(tmp_path)
    _run_seed(db)
    rep2 = _run_seed(db)
    for w in rep2["widgets"]:
        assert w["action"] == "noop", f"{w['host_saas']} should be noop on re-run"


def test_seed_dry_run_writes_nothing(tmp_path: pathlib.Path) -> None:
    db = _fresh_db(tmp_path)
    rep = _run_seed(db, "--dry-run")
    assert rep["dry_run"] is True
    conn = sqlite3.connect(str(db))
    try:
        n = conn.execute("SELECT COUNT(*) FROM am_copilot_widget_config").fetchone()[0]
    finally:
        conn.close()
    assert n == 0


# ---------------------------------------------------------------------------
# 5. Helper view excludes disabled rows
# ---------------------------------------------------------------------------


def test_view_excludes_disabled(tmp_path: pathlib.Path) -> None:
    db = _fresh_db(tmp_path)
    _run_seed(db)
    conn = sqlite3.connect(str(db))
    try:
        conn.execute(
            "UPDATE am_copilot_widget_config SET enabled = 0 WHERE host_saas = ?",
            ("slack",),
        )
        conn.commit()
        hosts = {r[0] for r in conn.execute("SELECT host_saas FROM v_copilot_widget_enabled")}
    finally:
        conn.close()
    assert "slack" not in hosts
    assert {"freee", "moneyforward", "notion"} <= hosts


# ---------------------------------------------------------------------------
# 6. copilot_scaffold.py token-hash + close_session
# ---------------------------------------------------------------------------


def _load_copilot_scaffold() -> object:
    """Import copilot_scaffold from THIS worktree (not site-packages)."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("_dim_s_copilot_scaffold", API_FILE)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_scaffold_open_close_session(tmp_path: pathlib.Path) -> None:
    cs = _load_copilot_scaffold()

    db = _fresh_db(tmp_path)
    _run_seed(db)

    desc = cs.get_proxy_descriptor("freee", db_path=db)
    assert desc is not None
    assert desc["host_saas"] == "freee"
    assert desc["mcp_proxy_url"].startswith("https://")

    raw_token = "ya29.abc-not-a-real-token"
    sid = cs.open_session(int(desc["widget_id"]), raw_token, db_path=db)
    assert sid > 0

    expected_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    conn = sqlite3.connect(str(db))
    try:
        row = conn.execute(
            "SELECT user_token_hash, ended_at FROM am_copilot_session_log WHERE session_id = ?",
            (sid,),
        ).fetchone()
    finally:
        conn.close()
    assert row[0] == expected_hash
    # Raw token must never appear anywhere in the table dump.
    conn = sqlite3.connect(str(db))
    try:
        for r in conn.execute("SELECT * FROM am_copilot_session_log"):
            for cell in r:
                if isinstance(cell, str):
                    assert raw_token not in cell, "raw OAuth token leaked into DB"
    finally:
        conn.close()
    assert row[1] is None  # not yet closed

    assert cs.close_session(sid, db_path=db) is True
    # Closing twice = noop.
    assert cs.close_session(sid, db_path=db) is False

    conn = sqlite3.connect(str(db))
    try:
        ended = conn.execute(
            "SELECT ended_at FROM am_copilot_session_log WHERE session_id = ?",
            (sid,),
        ).fetchone()[0]
    finally:
        conn.close()
    assert ended is not None


def test_scaffold_lists_enabled_widgets(tmp_path: pathlib.Path) -> None:
    cs = _load_copilot_scaffold()
    db = _fresh_db(tmp_path)
    _run_seed(db)
    widgets = cs.list_enabled_widgets(db_path=db)
    hosts = {w["host_saas"] for w in widgets}
    assert hosts == {"freee", "moneyforward", "notion", "slack"}
    for w in widgets:
        assert w["embed_url"].startswith("https://")
        assert w["mcp_proxy_url"].startswith("https://")


# ---------------------------------------------------------------------------
# 7. Boot-manifest integrity
# ---------------------------------------------------------------------------


def test_manifest_jpcite_lists_279() -> None:
    """jpcite boot manifest registers migration 279_copilot_scaffold.sql."""
    assert "279_copilot_scaffold.sql" in MANIFEST_JPCITE.read_text(encoding="utf-8")


def test_manifest_autonomath_lists_279() -> None:
    """autonomath boot manifest (mirror) registers migration 279."""
    assert "279_copilot_scaffold.sql" in MANIFEST_AM.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 8. LLM-0 verify + brand discipline
# ---------------------------------------------------------------------------


_FORBIDDEN_LLM_TOKENS = ("anthropic", "openai", "google.generativeai")


def test_no_llm_token_in_copilot_scaffold_api() -> None:
    """``grep -E "anthropic|openai" copilot_scaffold.py`` MUST be 0.

    Enforces ``feedback_copilot_scaffold_only_no_llm``: the embedded
    copilot widget is scaffold + MCP proxy + OAuth bridge ONLY.
    """
    src = API_FILE.read_text(encoding="utf-8")
    # Strip comments + docstrings before scanning by *intent*: we only
    # forbid actual code references. Comments may explain WHY we exclude
    # these tokens (and that explanation itself is allowed).
    code_lines = []
    in_doc = False
    for line in src.splitlines():
        stripped = line.lstrip()
        if stripped.startswith('"""') or stripped.startswith("'''"):
            in_doc = not in_doc
            continue
        if in_doc or stripped.startswith("#"):
            continue
        code_lines.append(line)
    code_only = "\n".join(code_lines)
    for bad in _FORBIDDEN_LLM_TOKENS:
        assert bad not in code_only.lower(), (
            f"LLM token `{bad}` leaked into copilot_scaffold.py code "
            f"(violates feedback_copilot_scaffold_only_no_llm)"
        )


def test_no_llm_import_in_etl_or_migration() -> None:
    """Dim S surface MUST stay LLM-free (feedback_no_operator_llm_api)."""
    sources = [
        ETL_SEED.read_text(encoding="utf-8"),
        MIG_279.read_text(encoding="utf-8"),
        MIG_279_RB.read_text(encoding="utf-8"),
        API_FILE.read_text(encoding="utf-8"),
    ]
    for src in sources:
        for bad in _FORBIDDEN_LLM_TOKENS:
            assert f"import {bad}" not in src
            assert f"from {bad}" not in src


def test_no_legacy_brand_in_new_files() -> None:
    """No 税務会計AI / zeimu-kaikei.ai legacy brand in new files."""
    legacy_phrases = ("税務会計AI", "zeimu-kaikei.ai")
    sources = [
        ETL_SEED.read_text(encoding="utf-8"),
        MIG_279.read_text(encoding="utf-8"),
        MIG_279_RB.read_text(encoding="utf-8"),
        API_FILE.read_text(encoding="utf-8"),
    ]
    for src in sources:
        for bad in legacy_phrases:
            assert bad not in src, f"legacy brand `{bad}` found in new file"
