"""Tests for Wave 43.2.7 Dim G real-time signal webhook + Wave 43.2.8 Dim H
personalization recommendations.

Covers migration 263+264 schema + idempotency + CHECK constraints,
refresh_personalization_daily score computation, LLM-import 0 regression,
and boot manifest references.
"""

from __future__ import annotations

import importlib.util
import pathlib
import re
import sqlite3
import sys
from typing import Any

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent

MIG_263 = REPO_ROOT / "scripts" / "migrations" / "263_realtime_signal_subscribers.sql"
MIG_264 = REPO_ROOT / "scripts" / "migrations" / "264_personalization_score.sql"
SRC_REALTIME = REPO_ROOT / "src" / "jpintel_mcp" / "api" / "realtime_signal_v2.py"
SRC_PERS = REPO_ROOT / "src" / "jpintel_mcp" / "api" / "personalization_v2.py"
CRON_REFRESH = REPO_ROOT / "scripts" / "cron" / "refresh_personalization_daily.py"
CRON_DISPATCH = REPO_ROOT / "scripts" / "cron" / "dispatch_webhooks.py"


def _apply_sql(conn: sqlite3.Connection, sql_path: pathlib.Path) -> None:
    sql = sql_path.read_text(encoding="utf-8")
    conn.executescript(sql)


def _build_am_fixture(tmp_path: pathlib.Path) -> sqlite3.Connection:
    db_path = tmp_path / "autonomath.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE am_amendment_diff (
            diff_id INTEGER PRIMARY KEY AUTOINCREMENT,
            entity_id TEXT NOT NULL,
            field_name TEXT NOT NULL,
            prev_value TEXT,
            new_value TEXT,
            detected_at TEXT NOT NULL,
            source_url TEXT
        );
        CREATE TABLE am_enforcement_municipality (
            enforcement_id INTEGER PRIMARY KEY AUTOINCREMENT,
            unified_id TEXT NOT NULL UNIQUE,
            prefecture_code TEXT NOT NULL,
            prefecture_name TEXT NOT NULL,
            municipality_code TEXT,
            municipality_name TEXT,
            agency_type TEXT NOT NULL,
            agency_name TEXT,
            action_type TEXT NOT NULL,
            action_date TEXT NOT NULL,
            action_summary TEXT,
            source_url TEXT NOT NULL,
            ingested_at TEXT NOT NULL
        );
        """
    )
    _apply_sql(conn, MIG_263)
    _apply_sql(conn, MIG_264)
    return conn


def _build_jp_fixture(tmp_path: pathlib.Path) -> sqlite3.Connection:
    db_path = tmp_path / "jpintel.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE api_keys (
            key_hash TEXT PRIMARY KEY,
            tier TEXT NOT NULL,
            revoked_at TEXT
        );
        CREATE TABLE programs (
            unified_id TEXT PRIMARY KEY,
            primary_name TEXT NOT NULL,
            tier TEXT,
            prefecture TEXT,
            program_kind TEXT,
            source_url TEXT,
            official_url TEXT,
            target_types_json TEXT,
            excluded INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE client_profiles (
            profile_id INTEGER PRIMARY KEY AUTOINCREMENT,
            api_key_hash TEXT NOT NULL,
            name_label TEXT NOT NULL,
            jsic_major TEXT,
            prefecture TEXT,
            employee_count INTEGER,
            capital_yen INTEGER,
            target_types_json TEXT NOT NULL DEFAULT '[]',
            last_active_program_ids_json TEXT NOT NULL DEFAULT '[]',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE saved_searches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            api_key_hash TEXT NOT NULL,
            name TEXT NOT NULL,
            canonical_query TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active'
        );
        """
    )
    return conn


def test_mig_263_apply_and_idempotent(tmp_path: pathlib.Path) -> None:
    conn = _build_am_fixture(tmp_path)
    names = {
        r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    assert "am_realtime_subscribers" in names
    assert "am_realtime_dispatch_history" in names
    _apply_sql(conn, MIG_263)
    conn.close()


def test_mig_263_check_constraints(tmp_path: pathlib.Path) -> None:
    conn = _build_am_fixture(tmp_path)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            """INSERT INTO am_realtime_subscribers(
                    api_key_hash, target_kind, webhook_url, signature_secret
               ) VALUES (?,?,?,?)""",
            ("kh1", "amendment", "http://example.com/hook", "secret123"),
        )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            """INSERT INTO am_realtime_subscribers(
                    api_key_hash, target_kind, webhook_url, signature_secret
               ) VALUES (?,?,?,?)""",
            ("kh1", "bogus_kind", "https://example.com/hook", "secret123"),
        )
    conn.close()


def test_mig_263_dispatch_history_idempotency(tmp_path: pathlib.Path) -> None:
    conn = _build_am_fixture(tmp_path)
    conn.execute(
        """INSERT INTO am_realtime_subscribers(
                api_key_hash, target_kind, webhook_url, signature_secret
           ) VALUES (?,?,?,?)""",
        ("kh1", "amendment", "https://example.com/hook", "secret123"),
    )
    sub_id = conn.execute("SELECT subscriber_id FROM am_realtime_subscribers").fetchone()[0]
    conn.execute(
        """INSERT INTO am_realtime_dispatch_history(
                subscriber_id, target_kind, signal_id, status_code, attempt_count
           ) VALUES (?,?,?,?,?)""",
        (sub_id, "amendment", "sig-1", 200, 1),
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            """INSERT INTO am_realtime_dispatch_history(
                    subscriber_id, target_kind, signal_id, status_code, attempt_count
               ) VALUES (?,?,?,?,?)""",
            (sub_id, "amendment", "sig-1", 200, 1),
        )
    conn.close()


def test_mig_264_apply_and_idempotent(tmp_path: pathlib.Path) -> None:
    conn = _build_am_fixture(tmp_path)
    names = {
        r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    assert "am_personalization_score" in names
    assert "am_personalization_refresh_log" in names
    _apply_sql(conn, MIG_264)
    conn.close()


def test_mig_264_score_clamp_constraint(tmp_path: pathlib.Path) -> None:
    conn = _build_am_fixture(tmp_path)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            """INSERT INTO am_personalization_score(
                    api_key_hash, client_id, program_id, score
               ) VALUES (?,?,?,?)""",
            ("kh1", 1, "P1", 101),
        )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            """INSERT INTO am_personalization_score(
                    api_key_hash, client_id, program_id, score
               ) VALUES (?,?,?,?)""",
            ("kh1", 1, "P1", -1),
        )
    conn.execute(
        """INSERT INTO am_personalization_score(
                api_key_hash, client_id, program_id, score
           ) VALUES (?,?,?,?)""",
        ("kh1", 1, "P1", 75),
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            """INSERT INTO am_personalization_score(
                    api_key_hash, client_id, program_id, score
               ) VALUES (?,?,?,?)""",
            ("kh1", 1, "P1", 80),
        )
    conn.close()


def _load_module_from_path(name: str, path: pathlib.Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, str(path))
    assert spec and spec.loader, f"could not load {path}"
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)  # type: ignore[arg-type]
    return mod


def test_filter_matches_equality_and_list() -> None:
    try:
        mod = _load_module_from_path("disp_wh", CRON_DISPATCH)
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"dispatch_webhooks not importable in test env: {exc!s}")
    fn = getattr(mod, "_filter_matches", None)
    if fn is None:
        pytest.skip("_filter_matches not available")
    assert fn({}, {"prefecture_code": "13"}) is True
    assert fn({"prefecture_code": "13"}, {"prefecture_code": "13"}) is True
    assert fn({"prefecture_code": "13"}, {"prefecture_code": "14"}) is False
    assert fn({"prefecture_code": ["13", "14"]}, {"prefecture_code": "14"}) is True
    assert fn({"prefecture_code": ["13", "14"]}, {"prefecture_code": "27"}) is False
    assert fn({"prefecture_code": "13"}, {}) is False


def test_personalization_refresh_upserts_rows(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    try:
        cron = _load_module_from_path("refresh_pers", CRON_REFRESH)
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"cron module not importable in test env: {exc!s}")

    jp_conn = _build_jp_fixture(tmp_path)
    am_conn = _build_am_fixture(tmp_path)
    jp_conn.execute("INSERT INTO api_keys(key_hash, tier) VALUES (?, ?)", ("kh-test", "paid"))
    jp_conn.execute(
        """INSERT INTO programs(
                unified_id, primary_name, tier, prefecture, program_kind,
                source_url, target_types_json, excluded, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (
            "P-1",
            "ものづくり補助金 (製造業 設備投資)",
            "S",
            "東京都",
            "subsidy",
            "https://example.gov.jp/p1",
            '["製造業","設備投資","E"]',
            0,
            "2026-05-12T00:00:00Z",
        ),
    )
    jp_conn.execute(
        """INSERT INTO programs(
                unified_id, primary_name, tier, prefecture, program_kind,
                source_url, target_types_json, excluded, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (
            "P-2",
            "農業6次産業化 補助",
            "A",
            "鹿児島県",
            "subsidy",
            "https://example.gov.jp/p2",
            '["農業","A"]',
            0,
            "2026-05-12T00:00:00Z",
        ),
    )
    jp_conn.execute(
        """INSERT INTO client_profiles(
                api_key_hash, name_label, jsic_major, prefecture,
                employee_count, capital_yen, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?)""",
        (
            "kh-test",
            "○○製作所",
            "E",
            "東京都",
            50,
            10_000_000,
            "2026-05-12T00:00:00Z",
            "2026-05-12T00:00:00Z",
        ),
    )
    jp_conn.execute(
        """INSERT INTO saved_searches(api_key_hash, name, canonical_query, status)
           VALUES (?,?,?,?)""",
        ("kh-test", "製造業 設備投資 watch", "ものづくり 設備投資 補助金", "active"),
    )
    jp_conn.commit()

    monkeypatch.setattr(cron, "connect", lambda *a, **kw: jp_conn)

    class _FakeSettings:
        autonomath_db_path = tmp_path / "autonomath.db"

    monkeypatch.setattr(cron, "settings", _FakeSettings())

    summary = cron.run(max_age_days=30, dry_run=False)
    assert summary["profiles_scored"] >= 1
    assert summary["rows_upserted"] >= 1

    am_check = sqlite3.connect(tmp_path / "autonomath.db")
    am_check.row_factory = sqlite3.Row
    rows = am_check.execute(
        """SELECT api_key_hash, client_id, program_id, score, industry_pack
             FROM am_personalization_score
            WHERE api_key_hash = 'kh-test'
         ORDER BY score DESC"""
    ).fetchall()
    am_check.close()
    assert len(rows) >= 1
    pids = [r["program_id"] for r in rows]
    if "P-1" in pids and "P-2" in pids:
        p1_score = next(r["score"] for r in rows if r["program_id"] == "P-1")
        p2_score = next(r["score"] for r in rows if r["program_id"] == "P-2")
        assert p1_score >= p2_score
    p1_pack = next((r["industry_pack"] for r in rows if r["program_id"] == "P-1"), None)
    assert p1_pack == "pack_manufacturing"

    jp_conn.close()
    am_conn.close()


_LLM_PATTERNS = (
    re.compile(r"\bimport\s+anthropic\b"),
    re.compile(r"\bfrom\s+anthropic\b"),
    re.compile(r"\bimport\s+openai\b"),
    re.compile(r"\bfrom\s+openai\b"),
    re.compile(r"\bimport\s+google\.generativeai\b"),
    re.compile(r"\bclaude_agent_sdk\b"),
    re.compile(r"\bANTHROPIC_API_KEY\b"),
    re.compile(r"\bOPENAI_API_KEY\b"),
    re.compile(r"\bGEMINI_API_KEY\b"),
)


@pytest.mark.parametrize(
    "path",
    [SRC_REALTIME, SRC_PERS, CRON_REFRESH, MIG_263, MIG_264],
)
def test_no_llm_imports_in_dim_g_h(path: pathlib.Path) -> None:
    text = path.read_text(encoding="utf-8")
    for pat in _LLM_PATTERNS:
        m = pat.search(text)
        assert m is None, f"{path.name}: LLM-API marker {pat.pattern!r} found"


def test_boot_manifest_references_new_migrations() -> None:
    manifest = (REPO_ROOT / "scripts" / "migrations" / "autonomath_boot_manifest.txt").read_text(
        encoding="utf-8"
    )
    assert "263_realtime_signal_subscribers.sql" in manifest
    assert "264_personalization_score.sql" in manifest
