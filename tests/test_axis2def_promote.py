"""Axis 2d/2e/2f promote ETL + Playwright fallback smoke tests."""

from __future__ import annotations

import importlib.util
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_ETL_DIR = _REPO / "scripts" / "etl"

ETL_SCRIPTS = (
    "promote_compat_matrix_v2",
    "verify_amount_conditions_v2",
    "datafill_amendment_snapshot_v2",
)


def _load_etl(name: str):
    path = _ETL_DIR / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, str(path))
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _load_helper():
    """Load _playwright_helper without tripping dataclass module lookup."""
    mod_name = "_playwright_helper"
    sys.path.insert(0, str(_ETL_DIR))
    if mod_name in sys.modules and getattr(sys.modules[mod_name], "RenderResult", None):
        return sys.modules[mod_name]
    spec = importlib.util.spec_from_file_location(
        mod_name, str(_ETL_DIR / "_playwright_helper.py")
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def empty_autonomath_db(tmp_path: Path) -> Path:
    db = tmp_path / "autonomath.db"
    conn = sqlite3.connect(str(db))
    try:
        cur = conn.cursor()
        cur.executescript(
            """
            CREATE TABLE IF NOT EXISTS am_compat_matrix (
                program_a_id TEXT NOT NULL,
                program_b_id TEXT NOT NULL,
                compat_status TEXT,
                source_url TEXT,
                confidence REAL,
                evidence_relation TEXT,
                inferred_only INTEGER DEFAULT 0,
                visibility TEXT DEFAULT 'internal',
                PRIMARY KEY (program_a_id, program_b_id)
            );
            CREATE TABLE IF NOT EXISTS am_amount_condition (
                id INTEGER PRIMARY KEY,
                entity_id TEXT,
                fixed_yen INTEGER,
                source_field TEXT,
                template_default INTEGER DEFAULT 1,
                quality_tier TEXT DEFAULT 'template'
            );
            CREATE TABLE IF NOT EXISTS am_amendment_snapshot (
                snapshot_id INTEGER PRIMARY KEY,
                entity_id TEXT,
                observed_at TEXT,
                source_url TEXT,
                raw_snapshot_json TEXT,
                effective_from TEXT
            );
            CREATE TABLE IF NOT EXISTS am_entity_facts (
                fact_id INTEGER PRIMARY KEY,
                entity_id TEXT,
                field_name TEXT,
                field_value_numeric REAL
            );
            CREATE TABLE IF NOT EXISTS am_entity_source (
                entity_id TEXT,
                source_url TEXT
            );
            CREATE TABLE IF NOT EXISTS am_source (
                source_url TEXT,
                last_verified TEXT
            );
            """
        )
        conn.commit()
    finally:
        conn.close()
    return db


@pytest.fixture
def seeded_autonomath_db(empty_autonomath_db: Path) -> Path:
    conn = sqlite3.connect(str(empty_autonomath_db))
    try:
        cur = conn.cursor()
        cur.executemany(
            "INSERT INTO am_compat_matrix VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                ("prog-A", "prog-B", "compatible",
                 "https://www.mhlw.go.jp/sample/page.html",
                 0.55, "synergistic", 0, "internal"),
                ("prog-C", "prog-D", "compatible",
                 "https://noukaweb.com/aggregator",
                 0.90, "synergistic", 0, "internal"),
                ("prog-E", "prog-F", "compatible",
                 "https://example.com/notgov",
                 0.55, None, 1, "internal"),
            ],
        )
        cur.executemany(
            "INSERT INTO am_amount_condition (entity_id, fixed_yen, source_field, template_default) "
            "VALUES (?, ?, ?, ?)",
            [
                ("ent-1", 1_500_000, "adoption.amount_granted_yen.repromoted_v2", 1),
                ("ent-2", 500_000, "adoption.amount_granted_yen.repromoted_v2", 1),
                ("ent-3", 7_000_000, "adoption.amount_granted_yen.repromoted_v2", 1),
            ],
        )
        cur.executemany(
            "INSERT INTO am_entity_facts (entity_id, field_name, field_value_numeric) "
            "VALUES (?, ?, ?)",
            [
                ("ent-1", "adoption.amount_granted_yen", 1_500_000),
                ("ent-2", "adoption.amount_granted_yen", 500_000),
            ],
        )
        cur.executemany(
            "INSERT INTO am_amendment_snapshot "
            "(entity_id, observed_at, source_url, raw_snapshot_json) "
            "VALUES (?, ?, ?, ?)",
            [
                ("ent-x", "2026-05-01T00:00:00Z",
                 "https://www.mhlw.go.jp/sample/v1",
                 '{"expected_start": "2026-04-01"}'),
                ("ent-y", "2026-05-01T00:00:00Z",
                 "https://www.maff.go.jp/sample/v2",
                 "令和8年4月施行"),
                ("ent-z", "2026-05-01T00:00:00Z",
                 "https://www.meti.go.jp/page",
                 None),
            ],
        )
        conn.commit()
    finally:
        conn.close()
    return empty_autonomath_db


@pytest.mark.parametrize("script", ETL_SCRIPTS)
def test_etl_imports_clean(script: str) -> None:
    mod = _load_etl(script)
    assert hasattr(mod, "main")


@pytest.mark.parametrize("script", ETL_SCRIPTS)
def test_etl_help_smoke(script: str) -> None:
    path = _ETL_DIR / f"{script}.py"
    result = subprocess.run(
        [sys.executable, str(path), "--help"],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    assert "--dry-run" in result.stdout
    assert "--apply" in result.stdout


def test_promote_compat_matrix_v2_dry_run(seeded_autonomath_db: Path) -> None:
    path = _ETL_DIR / "promote_compat_matrix_v2.py"
    result = subprocess.run(
        [sys.executable, str(path), "--db", str(seeded_autonomath_db),
         "--dry-run", "--no-fetch", "--limit", "10"],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert "candidates scanned" in result.stdout
    assert "promote → public" in result.stdout
    assert "summary:" in result.stdout


def test_verify_amount_conditions_v2_dry_run(seeded_autonomath_db: Path) -> None:
    path = _ETL_DIR / "verify_amount_conditions_v2.py"
    result = subprocess.run(
        [sys.executable, str(path), "--db", str(seeded_autonomath_db),
         "--dry-run", "--limit", "10"],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert "verified (A: EAV)" in result.stdout
    assert "summary:" in result.stdout


def test_datafill_amendment_snapshot_v2_dry_run(seeded_autonomath_db: Path) -> None:
    path = _ETL_DIR / "datafill_amendment_snapshot_v2.py"
    result = subprocess.run(
        [sys.executable, str(path), "--db", str(seeded_autonomath_db),
         "--dry-run", "--limit", "10"],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert "NULL rows scanned" in result.stdout
    assert "by source" in result.stdout
    assert "summary:" in result.stdout


def test_playwright_helper_aggregator_refusal() -> None:
    helper = _load_helper()
    assert helper.is_banned_url("https://noukaweb.com/x") is True
    assert helper.is_banned_url("https://hojyokin-portal.jp/x") is True
    assert helper.is_banned_url("https://biz.stayway.jp/x") is True
    assert helper.is_banned_url("https://www.mhlw.go.jp/x") is False


def test_playwright_helper_render_aggregator_short_circuits() -> None:
    helper = _load_helper()
    result = helper.render_page("https://noukaweb.com/x")
    assert result.text == ""
    assert result.status == 0
    assert result.error is not None


def test_playwright_helper_viewport_caps_under_1600() -> None:
    helper = _load_helper()
    assert helper.VIEWPORT_WIDTH <= 1600
    assert helper.VIEWPORT_HEIGHT <= 1600
    assert helper.MAX_SCREENSHOT_EDGE <= 1600


def test_playwright_helper_screenshot_filename_stable() -> None:
    helper = _load_helper()
    a = helper.screenshot_filename("https://www.mhlw.go.jp/a")
    b = helper.screenshot_filename("https://www.mhlw.go.jp/a")
    assert a == b
    assert a.endswith(".png")
    c = helper.screenshot_filename("https://www.mhlw.go.jp/b")
    assert a != c


def test_playwright_helper_render_page_returns_empty_on_missing_dep(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    helper = _load_helper()
    monkeypatch.setitem(sys.modules, "playwright", None)
    monkeypatch.setitem(sys.modules, "playwright.async_api", None)
    result = helper.render_page("https://www.mhlw.go.jp/sample")
    assert result.text == ""
    assert result.error is not None


def test_amount_regex_extracts_man_pattern() -> None:
    mod = _load_etl("verify_amount_conditions_v2")
    found = mod.extract_amounts_from_text("補助金額の上限は500万円です。")
    assert 5_000_000 in found


def test_amount_regex_extracts_labelled_yen() -> None:
    mod = _load_etl("verify_amount_conditions_v2")
    found = mod.extract_amounts_from_text("上限額：2,000,000円")
    assert 2_000_000 in found


def test_amount_regex_extracts_raw_yen_mark() -> None:
    mod = _load_etl("verify_amount_conditions_v2")
    found = mod.extract_amounts_from_text("(上限)¥3,500,000")
    assert 3_500_000 in found


def test_amendment_parse_body_effective_wareki() -> None:
    mod = _load_etl("datafill_amendment_snapshot_v2")
    iso = mod.parse_body_effective("本制度の施行日：令和8年4月1日から適用されます。")
    assert iso == "2026-04-01"


def test_amendment_parse_body_effective_iso() -> None:
    mod = _load_etl("datafill_amendment_snapshot_v2")
    iso = mod.parse_body_effective("施行日: 2026/04/01")
    assert iso == "2026-04-01"


def test_amendment_5pass_extractor() -> None:
    mod = _load_etl("datafill_amendment_snapshot_v2")
    iso, src = mod.extract_effective_from('{"expected_start": "2026-04-01"}', None, None)
    assert iso == "2026-04-01"
    assert src == "json"
    iso, src = mod.extract_effective_from("令和8年4月施行", None, None)
    assert iso == "2026-04-01"
    assert src == "wareki"
    iso, src = mod.extract_effective_from(None, "https://x.go.jp/fy2026/", None)
    assert iso == "2026-04-01"
    assert src == "url"
    iso, src = mod.extract_effective_from(None, None, None, body="施行日：令和8年4月1日")
    assert iso == "2026-04-01"
    assert src == "body"


def test_compat_host_boost_authoritative() -> None:
    mod = _load_etl("promote_compat_matrix_v2")
    assert mod.host_boost("https://www.mhlw.go.jp/x") >= 0.28
    assert mod.host_boost("https://something.go.jp/x") >= 0.25
    assert mod.host_boost("https://www.pref.tokyo.lg.jp/x") >= 0.20
    assert mod.host_boost("https://example.com/x") == 0.0
    assert mod.host_boost(None) == 0.0
    assert mod.is_authoritative("https://www.mhlw.go.jp/x") is True
    assert mod.is_authoritative("https://example.com/x") is False
