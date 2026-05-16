"""Test for Wave 34 Axis 4 5 precompute (18 file landing)."""

from __future__ import annotations

import json
import sqlite3
import struct
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
MIGRATIONS_DIR = REPO_ROOT / "scripts" / "migrations"
CRON_DIR = REPO_ROOT / "scripts" / "cron"

AXIS4_MIGRATIONS = [
    "235_am_portfolio_optimize",
    "236_am_houjin_risk_score",
    "237_am_subsidy_30yr_forecast",
    "238_am_alliance_opportunity",
    "239_am_knowledge_graph_vec_index",
]

_BANNED_IMPORT_LINES = (
    "import anthropic",
    "from anthropic",
    "import openai",
    "from openai ",
    "import google.generativeai",
    "from google.generativeai",
    "import claude_agent_sdk",
    "from claude_agent_sdk",
)


def _import_lines(text: str) -> list[str]:
    """Return only top-level import / from statements (skip docstrings/comments)."""
    lines: list[str] = []
    in_triple = False
    triple_quote = ""
    for raw in text.splitlines():
        stripped = raw.lstrip()
        if in_triple:
            if triple_quote in stripped:
                in_triple = False
                triple_quote = ""
            continue
        for q in ('"""', "'''"):
            if stripped.startswith(q):
                rest = stripped[3:]
                if q in rest:
                    break
                in_triple = True
                triple_quote = q
                break
        if in_triple:
            continue
        if stripped.startswith("#"):
            continue
        if stripped.startswith(("import ", "from ")):
            lines.append(stripped)
    return lines


def _apply_migrations(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    for slug in AXIS4_MIGRATIONS:
        sql_path = MIGRATIONS_DIR / f"{slug}.sql"
        assert sql_path.exists(), f"migration {slug}.sql missing"
        with sql_path.open(encoding="utf-8") as f:
            conn.executescript(f.read())
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS am_entities (
            canonical_id TEXT PRIMARY KEY, primary_name TEXT,
            record_kind TEXT, raw_json TEXT
        );
        CREATE TABLE IF NOT EXISTS jpi_programs (
            program_unified_id TEXT PRIMARY KEY, primary_name TEXT, tier TEXT,
            prefecture TEXT, jsic_major TEXT, jsic_middle TEXT,
            amount_min_yen INTEGER, amount_max_yen INTEGER, excluded INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS jpi_adoption_records (
            adoption_id TEXT PRIMARY KEY, houjin_bangou TEXT, program_unified_id TEXT,
            fiscal_year INTEGER, amount_yen INTEGER, adoption_status TEXT
        );
        CREATE TABLE IF NOT EXISTS jpi_houjin_master (
            houjin_bangou TEXT PRIMARY KEY, primary_name TEXT,
            jsic_major TEXT, jsic_middle TEXT, prefecture TEXT,
            employee_count INTEGER, established_year INTEGER
        );
        CREATE TABLE IF NOT EXISTS jpi_invoice_registrants (
            registrant_id TEXT PRIMARY KEY, houjin_bangou TEXT,
            status TEXT, status_at TEXT
        );
        CREATE TABLE IF NOT EXISTS am_enforcement_detail (
            enforcement_id TEXT PRIMARY KEY, houjin_bangou TEXT,
            record_kind TEXT, occurred_at TEXT, amount_yen INTEGER
        );
        CREATE TABLE IF NOT EXISTS am_program_eligibility_predicate (
            program_unified_id TEXT, houjin_bangou TEXT,
            gate_id TEXT, gate_outcome TEXT
        );
        CREATE TABLE IF NOT EXISTS am_compat_matrix (
            program_a_unified_id TEXT, program_b_unified_id TEXT, compat_status TEXT
        );
        CREATE TABLE IF NOT EXISTS am_application_round (
            program_unified_id TEXT, round_id TEXT,
            application_open_date TEXT, application_close_date TEXT
        );
        CREATE TABLE IF NOT EXISTS am_amendment_snapshot (
            entity_id TEXT, captured_at TEXT, eligibility_hash TEXT
        );
        CREATE TABLE IF NOT EXISTS am_amendment_diff (
            program_unified_id TEXT, diff_kind TEXT, diff_at TEXT
        );
        INSERT INTO am_entities VALUES ('h0000000000001','test_kk','corporate_entity','{}');
        INSERT INTO am_entities VALUES ('p_test_001','test_subsidy','program','{}');
        INSERT INTO am_entities VALUES ('law_001','test_law','law','{}');
        INSERT INTO jpi_programs VALUES ('p_test_001','test_subsidy','A','tokyo','E','E1',100000,5000000,0);
        INSERT INTO jpi_adoption_records VALUES ('a_001','h0000000000001','p_test_001',2024,1000000,'completed');
        INSERT INTO jpi_houjin_master VALUES ('h0000000000001','test_kk','E','E1','tokyo',50,2020);
        INSERT INTO am_application_round VALUES ('p_test_001','r_001','2026-01-01','2026-12-31');
        """
    )
    conn.commit()
    return conn


def test_axis4_migrations_apply(tmp_path: Path) -> None:
    db = tmp_path / "axis4.db"
    conn = _apply_migrations(db)
    expected = {
        "am_portfolio_optimize",
        "am_portfolio_optimize_refresh_log",
        "am_houjin_risk_score",
        "am_houjin_risk_score_refresh_log",
        "am_subsidy_30yr_forecast",
        "am_subsidy_30yr_forecast_refresh_log",
        "am_alliance_opportunity",
        "am_alliance_opportunity_refresh_log",
        "am_entities_vec_embed_log",
        "am_entities_vec_refresh_log",
    }
    rows = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    missing = expected - rows
    assert not missing, f"missing tables: {missing}"
    conn.close()


def test_axis4_rollbacks_exist() -> None:
    for slug in AXIS4_MIGRATIONS:
        path = MIGRATIONS_DIR / f"{slug}_rollback.sql"
        assert path.exists(), f"rollback missing: {path}"
        text = path.read_text(encoding="utf-8")
        assert "target_db: autonomath" in text


def test_axis4_migrations_carry_target_db_marker() -> None:
    for slug in AXIS4_MIGRATIONS:
        text = (MIGRATIONS_DIR / f"{slug}.sql").read_text(encoding="utf-8")
        assert text.splitlines()[0].strip() == "-- target_db: autonomath"


def _run_cron(script: str, db_path: Path, extra: list[str]) -> tuple[int, str, str]:
    p = subprocess.run(
        [
            sys.executable,
            str(CRON_DIR / script),
            "--autonomath-db",
            str(db_path),
            "--dry-run",
            *extra,
        ],
        cwd=str(REPO_ROOT),
        capture_output=True,
        timeout=120,
    )
    return (
        p.returncode,
        p.stdout.decode("utf-8", errors="replace"),
        p.stderr.decode("utf-8", errors="replace"),
    )


@pytest.mark.parametrize(
    "script,extra",
    [
        ("refresh_portfolio_optimize_daily.py", ["--max-houjin", "5", "--top-n", "8"]),
        ("refresh_houjin_risk_score_daily.py", ["--max-houjin", "5"]),
        ("forecast_30yr_subsidy_cycle.py", ["--max-programs", "5"]),
        ("precompute_alliance_opportunity.py", ["--max-houjin", "5", "--top-n", "10"]),
        ("embed_knowledge_graph_vec.py", ["--max-entities", "5", "--mode", "incremental"]),
    ],
)
def test_axis4_cron_dry_run(tmp_path: Path, script: str, extra: list[str]) -> None:
    db = tmp_path / "axis4.db"
    _apply_migrations(db).close()
    rc, out, err = _run_cron(script, db, extra)
    assert rc == 0, f"{script} rc={rc}\nstdout={out}\nstderr={err}"
    last = out.strip().splitlines()[-1] if out.strip() else "{}"
    payload = json.loads(last)
    assert isinstance(payload, dict)


def test_portfolio_optimize_empty_db_dry_run_does_not_crash(tmp_path: Path) -> None:
    db = tmp_path / "empty.db"
    rc, out, err = _run_cron(
        "refresh_portfolio_optimize_daily.py",
        db,
        ["--max-houjin", "5", "--top-n", "8"],
    )
    assert rc == 0, f"refresh_portfolio_optimize_daily.py rc={rc}\nstdout={out}\nstderr={err}"
    last = out.strip().splitlines()[-1] if out.strip() else "{}"
    payload = json.loads(last)
    assert isinstance(payload, dict)


def test_axis4_vec_embed_hash_fallback_dim() -> None:
    sys.path.insert(0, str(REPO_ROOT))
    from scripts.cron import embed_knowledge_graph_vec as mod

    vec = mod._hash_vector("test_kk", dim=mod.HASH_FALLBACK_DIM)
    assert len(vec) == mod.HASH_FALLBACK_DIM == 384
    vec2 = mod._hash_vector("test_kk", dim=mod.HASH_FALLBACK_DIM)
    assert vec == vec2
    assert all(-1.0 <= x <= 1.0 for x in vec)
    blob = struct.pack(f"{len(vec)}f", *vec)
    assert len(blob) == mod.HASH_FALLBACK_DIM * 4


def test_axis4_modules_no_llm_sdk_import() -> None:
    """REST + MCP modules must not import LLM SDKs (docstrings are exempt)."""
    rest_path = REPO_ROOT / "src" / "jpintel_mcp" / "api" / "precompute_axis4.py"
    mcp_path = (
        REPO_ROOT / "src" / "jpintel_mcp" / "mcp" / "autonomath_tools" / "precompute_axis4.py"
    )
    for path in (rest_path, mcp_path):
        assert path.exists()
        for line in _import_lines(path.read_text(encoding="utf-8")):
            for banned in _BANNED_IMPORT_LINES:
                assert banned not in line, f"{path.name}: forbidden import: {line!r}"


def test_axis4_cron_no_llm_sdk_import() -> None:
    """All 5 cron scripts must NOT import LLM SDKs (docstrings OK)."""
    for script in (
        "refresh_portfolio_optimize_daily.py",
        "refresh_houjin_risk_score_daily.py",
        "forecast_30yr_subsidy_cycle.py",
        "precompute_alliance_opportunity.py",
        "embed_knowledge_graph_vec.py",
    ):
        text = (CRON_DIR / script).read_text(encoding="utf-8")
        for line in _import_lines(text):
            for banned in _BANNED_IMPORT_LINES:
                assert banned not in line, f"{script}: forbidden import: {line!r}"


def test_axis4_workflows_present() -> None:
    wf_dir = REPO_ROOT / ".github" / "workflows"
    expected = {
        "portfolio-optimize-daily.yml",
        "houjin-risk-score-daily.yml",
        "subsidy-30yr-forecast-monthly.yml",
        "alliance-opportunity-weekly.yml",
        "knowledge-graph-vec-embed.yml",
    }
    present = {p.name for p in wf_dir.glob("*.yml")}
    missing = expected - present
    assert not missing, f"missing workflows: {missing}"


def test_axis4_insert_and_select_sample(tmp_path: Path) -> None:
    db = tmp_path / "axis4.db"
    conn = _apply_migrations(db)
    conn.execute(
        "INSERT INTO am_portfolio_optimize "
        "(houjin_bangou, rank, program_unified_id, program_primary_name, score_0_100) "
        "VALUES (?,?,?,?,?)",
        ("h0000000000001", 1, "p_test_001", "test_subsidy", 75),
    )
    conn.execute(
        "INSERT INTO am_houjin_risk_score "
        "(houjin_bangou, risk_score_0_100, risk_bucket) VALUES (?,?,?)",
        ("h0000000000001", 30, "medium"),
    )
    conn.execute(
        "INSERT INTO am_subsidy_30yr_forecast "
        "(program_unified_id, forecast_year_offset, horizon_month, state, "
        " p_active, p_paused, p_sunset, p_renewed) VALUES (?,?,?,?,?,?,?,?)",
        ("p_test_001", 0, 0, "active", 0.85, 0.10, 0.02, 0.03),
    )
    conn.execute(
        "INSERT INTO am_alliance_opportunity "
        "(houjin_bangou, rank, partner_houjin_bangou, alliance_score_0_100) "
        "VALUES (?,?,?,?)",
        ("h0000000000001", 1, "h0000000000002", 65),
    )
    conn.execute(
        "INSERT INTO am_entities_vec_embed_log "
        "(canonical_id, record_kind, embed_dim, model_name) VALUES (?,?,?,?)",
        ("h0000000000001", "corporate_entity", 384, "hash-fallback-v1"),
    )
    conn.commit()
    assert conn.execute("SELECT COUNT(*) FROM am_portfolio_optimize").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM am_houjin_risk_score").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM am_subsidy_30yr_forecast").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM am_alliance_opportunity").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM am_entities_vec_embed_log").fetchone()[0] == 1
    conn.close()
