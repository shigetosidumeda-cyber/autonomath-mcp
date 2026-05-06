"""Regression tests for the customer-facing amount-condition gate."""

from __future__ import annotations

import importlib.util
import json
import sqlite3
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "cron" / "precompute_actionable_cache.py"


def _load_precompute_module():
    spec = importlib.util.spec_from_file_location(
        "precompute_actionable_cache_amount_gate", SCRIPT_PATH
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _create_program_table(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE jpi_programs (
            unified_id TEXT PRIMARY KEY,
            primary_name TEXT,
            tier TEXT,
            authority_level TEXT,
            authority_name TEXT,
            prefecture TEXT,
            municipality TEXT,
            program_kind TEXT,
            official_url TEXT,
            amount_max_man_yen INTEGER,
            amount_min_man_yen INTEGER,
            subsidy_rate REAL,
            subsidy_rate_text TEXT,
            trust_level TEXT,
            coverage_score REAL,
            target_types_json TEXT,
            funding_purpose_json TEXT,
            amount_band TEXT,
            application_window_json TEXT,
            enriched_json TEXT,
            source_mentions_json TEXT,
            source_url TEXT,
            source_fetched_at TEXT,
            source_checksum TEXT,
            updated_at TEXT
        );
        """
    )
    conn.execute(
        """INSERT INTO jpi_programs
           (unified_id, primary_name, tier, authority_level, authority_name,
            prefecture, municipality, program_kind, official_url,
            amount_max_man_yen, amount_min_man_yen, subsidy_rate,
            subsidy_rate_text, trust_level, coverage_score, target_types_json,
            funding_purpose_json, amount_band, application_window_json,
            enriched_json, source_mentions_json, source_url, source_fetched_at,
            source_checksum, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            "P1",
            "Program One",
            "S",
            "national",
            "Agency",
            "Tokyo",
            None,
            "subsidy",
            "https://example.test/p1",
            100,
            None,
            0.5,
            "1/2",
            "high",
            1.0,
            json.dumps([]),
            json.dumps([]),
            "small",
            json.dumps({}),
            json.dumps({}),
            json.dumps({}),
            "https://example.test/source",
            "2026-05-06T00:00:00Z",
            "sha256:test",
            "2026-05-06T00:00:00Z",
        ),
    )


def _open_fixture_db(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    _create_program_table(conn)
    return conn


def test_precompute_program_amount_conditions_only_include_verified(
    tmp_path: Path,
) -> None:
    mod = _load_precompute_module()
    conn = _open_fixture_db(tmp_path / "amount_gate.db")
    conn.executescript(
        """
        CREATE TABLE am_amount_condition (
            entity_id TEXT,
            condition_label TEXT,
            percentage REAL,
            fixed_yen INTEGER,
            rate_range_low REAL,
            rate_range_high REAL,
            quality_tier TEXT
        );
        """
    )
    conn.executemany(
        """INSERT INTO am_amount_condition
           (entity_id, condition_label, percentage, fixed_yen,
            rate_range_low, rate_range_high, quality_tier)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        [
            ("program:P1", "verified cap", None, 123_456, None, None, "verified"),
            (
                "program:P1",
                "template cap",
                None,
                500_000,
                None,
                None,
                "template_default",
            ),
            ("program:P1", "unknown cap", None, 999_999, None, None, "unknown"),
        ],
    )

    try:
        body = mod._build_program_envelope(conn, "P1", "snapshot-1")
    finally:
        conn.close()

    assert body is not None
    conditions = body["amounts"]["conditions"]
    assert [condition["fixed_yen"] for condition in conditions] == [123_456]
    assert body["quality"]["known_gaps"] == [mod._AMOUNT_CONDITION_UNVERIFIED_GAP]


def test_precompute_program_amount_conditions_omit_all_when_tier_missing(
    tmp_path: Path,
) -> None:
    mod = _load_precompute_module()
    conn = _open_fixture_db(tmp_path / "amount_gate_legacy.db")
    conn.executescript(
        """
        CREATE TABLE am_amount_condition (
            entity_id TEXT,
            condition_label TEXT,
            percentage REAL,
            fixed_yen INTEGER,
            rate_range_low REAL,
            rate_range_high REAL
        );
        """
    )
    conn.execute(
        """INSERT INTO am_amount_condition
           (entity_id, condition_label, percentage, fixed_yen,
            rate_range_low, rate_range_high)
           VALUES (?, ?, ?, ?, ?, ?)""",
        ("program:P1", "legacy cap", None, 777_777, None, None),
    )

    try:
        body = mod._build_program_envelope(conn, "P1", "snapshot-legacy")
    finally:
        conn.close()

    assert body is not None
    assert body["amounts"]["conditions"] == []
    assert body["quality"]["known_gaps"] == [mod._AMOUNT_CONDITION_TIER_MISSING_GAP]
