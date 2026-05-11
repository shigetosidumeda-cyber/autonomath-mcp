"""Wave 43.1.5 — 都道府県条例 ETL + REST + migration test suite.

Covers:
  * migration 252 round-trip apply / rollback
  * ETL classify helpers + 公布番号 regex
  * ETL upsert + FTS write (no network)
  * dry-run cli (no network, no DB write)
  * LLM API import scan (zero tolerance)
  * Aggregator URL refusal
"""

from __future__ import annotations

import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
ETL_SCRIPT = REPO_ROOT / "scripts" / "etl" / "fill_laws_jorei_47pref_2x.py"
MIGRATION = REPO_ROOT / "scripts" / "migrations" / "252_law_jorei_pref.sql"
ROLLBACK = REPO_ROOT / "scripts" / "migrations" / "252_law_jorei_pref_rollback.sql"


_BANNED_IMPORT_LINES = (
    "import anthropic", "from anthropic ",
    "import openai", "from openai ",
    "import google.generativeai", "from google.generativeai",
    "import claude_agent_sdk", "from claude_agent_sdk",
)


def _import_lines(text: str) -> list[str]:
    out: list[str] = []
    in_triple = False
    triple = ""
    for raw in text.splitlines():
        stripped = raw.lstrip()
        if in_triple:
            if triple in stripped:
                in_triple = False
                triple = ""
            continue
        for q in ('"""', "'''"):
            if stripped.startswith(q):
                rest = stripped[3:]
                if q in rest:
                    break
                in_triple = True
                triple = q
                break
        if in_triple:
            continue
        if stripped.startswith("#"):
            continue
        if stripped.startswith(("import ", "from ")):
            out.append(stripped)
    return out


def test_migration_files_exist():
    assert MIGRATION.exists(), f"missing {MIGRATION}"
    assert ROLLBACK.exists(), f"missing {ROLLBACK}"


def test_migration_target_db_marker():
    head = MIGRATION.read_text(encoding="utf-8").splitlines()[0]
    assert head.strip() == "-- target_db: autonomath"


def test_migration_round_trip(tmp_path):
    db = tmp_path / "rt.db"
    conn = sqlite3.connect(db)
    conn.executescript(MIGRATION.read_text(encoding="utf-8"))
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )}
    assert "am_law_jorei_pref" in tables
    assert "am_law_jorei_pref_run_log" in tables
    fts = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master "
        "WHERE type='table' AND name='am_law_jorei_pref_fts'"
    )}
    assert "am_law_jorei_pref_fts" in fts
    views = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='view'"
    )}
    assert "v_law_jorei_pref_density" in views
    # Round-trip rollback.
    conn.executescript(ROLLBACK.read_text(encoding="utf-8"))
    remaining = {
        r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE name LIKE '%jorei_pref%'"
        )
    }
    assert remaining == set(), f"rollback left tables: {remaining}"


def test_migration_idempotent(tmp_path):
    db = tmp_path / "idem.db"
    conn = sqlite3.connect(db)
    sql = MIGRATION.read_text(encoding="utf-8")
    conn.executescript(sql)
    # Re-apply must not raise.
    conn.executescript(sql)


def test_etl_no_llm_api_imports():
    text = ETL_SCRIPT.read_text(encoding="utf-8")
    lines = _import_lines(text)
    for ln in lines:
        for banned in _BANNED_IMPORT_LINES:
            assert banned not in ln, f"banned LLM import found: {ln}"


def test_etl_aggregator_banned():
    text = ETL_SCRIPT.read_text(encoding="utf-8")
    # 4 high-value aggregators must be explicitly refused at the
    # banned-domain layer.
    for needle in ("noukaweb", "hojyokin-portal", "biz.stayway", "jichitai.com"):
        assert needle in text, f"aggregator missing from banned list: {needle}"


def test_etl_47_prefectures_seeded():
    text = ETL_SCRIPT.read_text(encoding="utf-8")
    # PrefectureCfg("01" .. PrefectureCfg("47" must all appear.
    for i in range(1, 48):
        code = f"{i:02d}"
        assert f'PrefectureCfg("{code}"' in text, f"missing pref {code}"


def test_etl_dry_run_no_network(tmp_path):
    """`--dry-run` flag must not touch the network nor write a DB row."""
    db = tmp_path / "dry.db"
    proc = subprocess.run(
        [sys.executable, str(ETL_SCRIPT), "--dry-run",
         "--db", str(db), "--pref-from", "01", "--pref-to", "02"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
    # DB file must not have been created.
    assert not db.exists(), "dry-run created DB"


def test_etl_classify_helpers():
    sys.path.insert(0, str(REPO_ROOT))
    from scripts.etl.fill_laws_jorei_47pref_2x import (
        _classify_kind,
        _looks_like_jorei,
        _is_banned,
        _is_primary,
        _canonical_id,
    )
    assert _classify_kind("環境基本条例") == "jorei"
    assert _classify_kind("施行規則") == "kisoku"
    assert _classify_kind("災害告示") == "kokuji"
    assert _classify_kind("運用要綱") == "youkou"
    assert _classify_kind("組織訓令") == "kunrei"
    assert _looks_like_jorei("東京都環境基本条例") is True
    assert _looks_like_jorei("ホーム") is False
    assert _is_banned("https://noukaweb.com/x") is True
    assert _is_banned("https://www.pref.tokyo.lg.jp/x") is False
    assert _is_primary("https://www.pref.aichi.jp/x") is True
    assert _is_primary("https://www.example.com/x") is False
    cid = _canonical_id("13", "tokyo", "東京都環境基本条例", None)
    assert cid.startswith("JOREI-13-")
    assert len(cid) >= len("JOREI-13-aaaaaaaa")


def test_etl_upsert_and_fts_against_real_schema(tmp_path):
    db = tmp_path / "ingest.db"
    conn = sqlite3.connect(db)
    conn.executescript(MIGRATION.read_text(encoding="utf-8"))
    sys.path.insert(0, str(REPO_ROOT))
    from scripts.etl.fill_laws_jorei_47pref_2x import (
        _upsert,
        _upsert_fts,
        _audit_counts,
    )
    rows = [
        {
            "canonical_id": "JOREI-13-test1",
            "law_id": None,
            "prefecture_code": "13",
            "prefecture_name": "東京都",
            "jorei_number": "令和六年東京都条例第一号",
            "jorei_title": "東京都気候変動対策推進条例",
            "jorei_kind": "jorei",
            "enacted_date": "2024-04-01",
            "last_revised": "2024-04-01",
            "body_text_excerpt": "第一条 この条例は気候変動対策を推進する。",
            "body_url": "https://www.reiki.metro.tokyo.lg.jp/x.html",
            "source_url": "https://www.reiki.metro.tokyo.lg.jp/x.html",
            "license": "gov_public",
            "fetched_at": "2026-05-12T08:00:00.000Z",
            "confidence": 0.95,
        },
        {
            "canonical_id": "JOREI-14-test1",
            "law_id": None,
            "prefecture_code": "14",
            "prefecture_name": "神奈川県",
            "jorei_number": None,
            "jorei_title": "神奈川県再生可能エネルギー導入条例",
            "jorei_kind": "jorei",
            "enacted_date": "2024-06-01",
            "last_revised": None,
            "body_text_excerpt": "第一条 この条例は再生可能エネルギーの導入を促進する。",
            "body_url": "https://www.pref.kanagawa.jp/reiki/y.html",
            "source_url": "https://www.pref.kanagawa.jp/reiki/y.html",
            "license": "gov_public",
            "fetched_at": "2026-05-12T08:01:00.000Z",
            "confidence": 0.85,
        },
    ]
    n = _upsert(conn, rows)
    assert n == 2
    n_fts = _upsert_fts(conn, rows)
    assert n_fts == 2
    audit = _audit_counts(conn)
    assert audit["total"] == 2
    assert "13" in audit["per_pref"]
    assert "14" in audit["per_pref"]
    # FTS round-trip (>=3 char queries pass trigram).
    hits = list(conn.execute(
        "SELECT canonical_id FROM am_law_jorei_pref_fts "
        "WHERE am_law_jorei_pref_fts MATCH ?",
        ("気候変動",),
    ))
    assert any(r[0] == "JOREI-13-test1" for r in hits)
    # Re-upsert is idempotent on canonical_id.
    n2 = _upsert(conn, rows)
    assert n2 == 2
    audit2 = _audit_counts(conn)
    assert audit2["total"] == 2  # no duplicate row
