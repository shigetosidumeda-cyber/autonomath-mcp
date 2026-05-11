"""Wave 35 Axis 5 — multilingual ETL test suite.

Covers migrations 240/241/242/243, 4 fill dry-runs, aggregator URL
refusal, LLM API import scan, translate_review_queue export round-trip.
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
MIGRATIONS_DIR = REPO_ROOT / "scripts" / "migrations"
CRON_DIR = REPO_ROOT / "scripts" / "cron"

AXIS5_MIGRATIONS_AUTONOMATH = [
    "240_law_en_full",
    "242_law_zh",
    "243_law_ko",
]
AXIS5_MIGRATIONS_JPINTEL = ["241_programs_en"]
ALL_AXIS5_MIGRATIONS = AXIS5_MIGRATIONS_AUTONOMATH + AXIS5_MIGRATIONS_JPINTEL

AXIS5_CRON_SCRIPTS = [
    "fill_laws_en_full.py",
    "fill_programs_en.py",
    "fill_laws_zh.py",
    "fill_laws_ko.py",
    "translate_review_queue.py",
]

_BANNED_IMPORT_LINES = (
    "import anthropic", "from anthropic",
    "import openai", "from openai ",
    "import google.generativeai", "from google.generativeai",
    "import claude_agent_sdk", "from claude_agent_sdk",
)


def _import_lines(text: str) -> list[str]:
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


def _seed_autonomath_db(db: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE am_law (canonical_id TEXT PRIMARY KEY, name TEXT);
        CREATE TABLE am_law_article (
            article_id INTEGER PRIMARY KEY,
            law_canonical_id TEXT,
            article_number TEXT,
            body_en TEXT
        );
        """
    )
    for i in range(10):
        conn.execute("INSERT INTO am_law VALUES (?, ?)",
                     (f"LAW-{i:010d}", f"test law {i}"))
    for slug in AXIS5_MIGRATIONS_AUTONOMATH:
        with (MIGRATIONS_DIR / f"{slug}.sql").open(encoding="utf-8") as f:
            conn.executescript(f.read())
    conn.commit()
    return conn


def _seed_jpintel_db(db: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE programs (
            unified_id TEXT PRIMARY KEY, primary_name TEXT, tier TEXT,
            excluded INTEGER DEFAULT 0, source_url TEXT
        );
        """
    )
    for i in range(10):
        conn.execute(
            "INSERT INTO programs VALUES (?, ?, ?, 0, ?)",
            (f"UNI-{i:04d}", f"test program {i}",
             "B" if i % 2 else "A",
             f"https://www.meti.go.jp/policy/test_{i}.html"),
        )
    for slug in AXIS5_MIGRATIONS_JPINTEL:
        with (MIGRATIONS_DIR / f"{slug}.sql").open(encoding="utf-8") as f:
            conn.executescript(f.read())
    conn.commit()
    return conn


def test_axis5_migrations_apply(tmp_path: Path) -> None:
    db = tmp_path / "axis5_am.db"
    conn = _seed_autonomath_db(db)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    expected = {
        "am_law_translation_progress",
        "am_law_translation_review_queue",
        "am_law_translation_refresh_log",
    }
    assert expected.issubset(tables)
    conn.close()
    db2 = tmp_path / "axis5_jpi.db"
    conn2 = _seed_jpintel_db(db2)
    tables2 = {r[0] for r in conn2.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "programs_translation_review_queue" in tables2
    assert "programs_translation_refresh_log" in tables2
    cols = {r[1] for r in conn2.execute("PRAGMA table_info(programs)")}
    for needed in ("title_en", "summary_en", "eligibility_en",
                   "source_url_en", "translation_status", "translation_fetched_at"):
        assert needed in cols, f"programs missing column: {needed}"
    conn2.close()


def test_axis5_rollbacks_exist() -> None:
    for slug in ALL_AXIS5_MIGRATIONS:
        path = MIGRATIONS_DIR / f"{slug}_rollback.sql"
        assert path.exists(), f"rollback missing: {path}"


def test_axis5_migrations_carry_target_db_marker() -> None:
    for slug in AXIS5_MIGRATIONS_AUTONOMATH:
        text = (MIGRATIONS_DIR / f"{slug}.sql").read_text(encoding="utf-8")
        assert text.splitlines()[0].strip() == "-- target_db: autonomath", slug
    for slug in AXIS5_MIGRATIONS_JPINTEL:
        text = (MIGRATIONS_DIR / f"{slug}.sql").read_text(encoding="utf-8")
        assert text.splitlines()[0].strip() == "-- target_db: jpintel", slug


def _run_cron(script: str, db_path: Path, db_flag: str, extra: list[str]) -> tuple[int, str, str]:
    p = subprocess.run(
        [sys.executable, str(CRON_DIR / script), db_flag, str(db_path), *extra],
        cwd=str(REPO_ROOT), capture_output=True, timeout=60)
    return p.returncode, p.stdout.decode("utf-8", errors="replace"), p.stderr.decode("utf-8", errors="replace")


@pytest.mark.parametrize(
    "script,db_flag,seed",
    [
        ("fill_laws_en_full.py", "--autonomath-db", "autonomath"),
        ("fill_laws_zh.py", "--autonomath-db", "autonomath"),
        ("fill_laws_ko.py", "--autonomath-db", "autonomath"),
        ("fill_programs_en.py", "--jpintel-db", "jpintel"),
    ],
)
def test_axis5_cron_dry_run(tmp_path: Path, script: str, db_flag: str, seed: str) -> None:
    db = tmp_path / f"axis5_{seed}.db"
    if seed == "autonomath":
        conn = _seed_autonomath_db(db)
    else:
        conn = _seed_jpintel_db(db)
    conn.close()
    extra = ["--max-laws", "10"] if "laws" in script else ["--max-programs", "10"]
    extra += ["--dry-run", "--no-network"]
    rc, out, err = _run_cron(script, db, db_flag, extra)
    assert rc == 0, f"{script} dry-run rc={rc} stderr={err[-400:]}"
    payload = json.loads(out.strip().splitlines()[-1])
    assert payload["ok"] is True


def test_aggregator_url_refused(tmp_path: Path) -> None:
    db = tmp_path / "axis5_jpi.db"
    conn = _seed_jpintel_db(db)
    conn.execute("DELETE FROM programs")
    conn.execute(
        "INSERT INTO programs (unified_id, primary_name, tier, excluded, source_url) "
        "VALUES (?, ?, 'A', 0, ?)",
        ("UNI-BAN-1", "noukaweb test", "https://noukaweb.com/test"))
    conn.commit()
    conn.close()
    rc, out, err = _run_cron(
        "fill_programs_en.py", db, "--jpintel-db",
        ["--max-programs", "1", "--dry-run", "--no-network"])
    assert rc == 0, f"rc={rc} err={err[-300:]}"
    payload = json.loads(out.strip().splitlines()[-1])
    assert payload["totals"]["refused_aggregator"] >= 1


def test_axis5_no_llm_imports() -> None:
    offenders: list[tuple[str, str]] = []
    for script in AXIS5_CRON_SCRIPTS:
        path = CRON_DIR / script
        assert path.exists(), f"cron script missing: {path}"
        text = path.read_text(encoding="utf-8")
        for line in _import_lines(text):
            for banned in _BANNED_IMPORT_LINES:
                if line.startswith(banned):
                    offenders.append((script, line))
    assert not offenders, f"LLM API imports detected: {offenders}"


def test_axis5_migrations_no_llm_refs() -> None:
    needles = ("anthropic_api_key", "openai_api_key", "claude_agent_sdk")
    for slug in ALL_AXIS5_MIGRATIONS:
        text = (MIGRATIONS_DIR / f"{slug}.sql").read_text(encoding="utf-8").lower()
        for needle in needles:
            assert needle not in text, f"{slug} mentions {needle}"


def test_translate_review_queue_export(tmp_path: Path) -> None:
    am_db = tmp_path / "axis5_am.db"
    jp_db = tmp_path / "axis5_jpi.db"
    _seed_autonomath_db(am_db).close()
    _seed_jpintel_db(jp_db).close()
    out_csv = tmp_path / "review.csv"
    p = subprocess.run(
        [sys.executable, str(CRON_DIR / "translate_review_queue.py"), "--export",
         "--autonomath-db", str(am_db), "--jpintel-db", str(jp_db),
         "--out", str(out_csv)],
        cwd=str(REPO_ROOT), capture_output=True, timeout=30)
    assert p.returncode == 0, p.stderr.decode()[-300:]
    payload = json.loads(p.stdout.decode().strip().splitlines()[-1])
    assert payload["ok"] is True
    assert out_csv.exists()
