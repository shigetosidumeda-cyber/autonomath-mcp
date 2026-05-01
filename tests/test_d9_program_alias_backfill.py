from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

_ETL = Path(__file__).resolve().parent.parent / "scripts" / "etl"
if str(_ETL) not in sys.path:
    sys.path.insert(0, str(_ETL))

import backfill_program_aliases_json as backfill  # noqa: E402


def _build_jp_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE programs (
            unified_id TEXT PRIMARY KEY,
            primary_name TEXT NOT NULL,
            aliases_json TEXT,
            tier TEXT,
            excluded INTEGER DEFAULT 0
        );
        CREATE VIRTUAL TABLE programs_fts USING fts5(
            unified_id UNINDEXED,
            primary_name,
            aliases,
            enriched_text,
            tokenize='trigram'
        );
        """
    )
    return conn


def _build_am_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE am_entities (
            canonical_id TEXT PRIMARY KEY,
            record_kind TEXT NOT NULL,
            primary_name TEXT NOT NULL
        );
        CREATE TABLE am_alias (
            id INTEGER PRIMARY KEY,
            entity_table TEXT NOT NULL,
            canonical_id TEXT NOT NULL,
            alias TEXT NOT NULL,
            alias_kind TEXT NOT NULL,
            language TEXT DEFAULT 'ja'
        );
        """
    )
    return conn


def test_generate_name_aliases_keeps_search_useful_variants() -> None:
    aliases = backfill.generate_name_aliases(
        "IT導入補助金 2026 (インボイス対応類型)"
    )

    assert "IT 導入補助金 2026 (インボイス対応類型)" in aliases
    assert "インボイス対応類型" in aliases
    assert "IT導入補助金" in aliases


def test_useful_alias_drops_ids_and_generic_english() -> None:
    assert backfill._useful_alias("program:abc", "IT導入補助金") is None
    assert backfill._useful_alias("grant", "IT導入補助金") is None
    assert backfill._useful_alias("IT補助金", "IT導入補助金") == "IT補助金"


def test_backfill_program_aliases_updates_programs_and_fts() -> None:
    jp = _build_jp_db()
    am = _build_am_db()
    jp.execute(
        "INSERT INTO programs(unified_id, primary_name, aliases_json, tier, excluded) "
        "VALUES (?, ?, ?, ?, 0)",
        ("UNI-1", "IT導入補助金 2026", None, "A"),
    )
    jp.execute(
        "INSERT INTO programs_fts(unified_id, primary_name, aliases, enriched_text) "
        "VALUES (?, ?, ?, ?)",
        ("UNI-1", "IT導入補助金 2026", "", "existing enriched"),
    )
    am.execute(
        "INSERT INTO am_entities(canonical_id, record_kind, primary_name) VALUES (?, ?, ?)",
        ("program:one", "program", "IT導入補助金 2026"),
    )
    am.executemany(
        "INSERT INTO am_alias(entity_table, canonical_id, alias, alias_kind) "
        "VALUES (?, ?, ?, ?)",
        [
            ("am_entities", "program:one", "IT補助金", "abbreviation"),
            ("am_entities", "program:one", "program:one", "legacy"),
            ("am_entities", "program:one", "grant", "english"),
        ],
    )

    result = backfill.backfill_program_aliases(
        jp,
        am,
        apply=True,
        tiers={"A"},
    )

    assert result["updated_rows"] == 1
    aliases = json.loads(
        jp.execute("SELECT aliases_json FROM programs WHERE unified_id='UNI-1'").fetchone()[0]
    )
    assert "IT補助金" in aliases
    assert "IT導入補助金" in aliases
    fts = jp.execute(
        "SELECT aliases, enriched_text FROM programs_fts WHERE unified_id='UNI-1'"
    ).fetchone()
    assert "IT補助金" in fts["aliases"]
    assert fts["enriched_text"] == "existing enriched"


def test_backfill_program_aliases_does_not_overwrite_excluded_or_other_tier() -> None:
    jp = _build_jp_db()
    am = _build_am_db()
    jp.executemany(
        "INSERT INTO programs(unified_id, primary_name, aliases_json, tier, excluded) "
        "VALUES (?, ?, ?, ?, ?)",
        [
            ("UNI-1", "IT導入補助金 2026", None, "A", 1),
            ("UNI-2", "IT導入補助金 2026", None, "X", 0),
        ],
    )
    am.execute(
        "INSERT INTO am_entities(canonical_id, record_kind, primary_name) VALUES (?, ?, ?)",
        ("program:one", "program", "IT導入補助金 2026"),
    )
    am.execute(
        "INSERT INTO am_alias(entity_table, canonical_id, alias, alias_kind) "
        "VALUES (?, ?, ?, ?)",
        ("am_entities", "program:one", "IT補助金", "abbreviation"),
    )

    result = backfill.backfill_program_aliases(
        jp,
        am,
        apply=True,
        tiers={"A"},
    )

    assert result["updated_rows"] == 0
