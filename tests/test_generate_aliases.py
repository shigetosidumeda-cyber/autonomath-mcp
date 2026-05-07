"""Tests for `tools/offline/generate_aliases.py` (D9 backfill helper).

Operator-only offline script — runs read-only against `data/jpintel.db`
and emits a CSV under `analysis_wave18/`. These tests:

1.  Load the script as a module via `importlib.util` (it lives in
    `tools/offline/` outside the package tree, like
    `test_alias_expansion.py` loads its cron sibling).
2.  Build a tiny throwaway SQLite DB seeded with one program row whose
    `primary_name` exercises three different generation rules
    (kanji→hira, kanji→kata, ministry abbreviation expansion) — the
    happy-path required by the spec.
3.  Drive `main()` with `--dry-run --limit 1` against the fixture DB and
    assert exit code 0 + non-empty alias list.

We do NOT exercise pykakasi-less environments because pykakasi is a
hard dependency of the offline script (it `sys.exit(2)`s when missing,
matching the operator-tool contract documented in the script's module
docstring). Production runtime tolerance lives in
`src/jpintel_mcp/utils/slug.py` and is covered by other tests.
"""

from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "tools" / "offline" / "generate_aliases.py"


@pytest.fixture(scope="module")
def gen_aliases_mod():
    """Load `tools/offline/generate_aliases.py` as a module."""
    spec = importlib.util.spec_from_file_location("generate_aliases", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["generate_aliases"] = mod
    spec.loader.exec_module(mod)
    return mod


def _seed_jpintel(db_path: Path, rows: list[tuple[str, str]]) -> None:
    """Seed a minimal `programs` table matching the production schema's
    relevant columns (only what the script reads)."""
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(
            """
            CREATE TABLE programs (
                unified_id TEXT PRIMARY KEY,
                primary_name TEXT NOT NULL,
                aliases_json TEXT,
                tier TEXT,
                excluded INTEGER DEFAULT 0,
                updated_at TEXT
            );
            """
        )
        conn.executemany(
            "INSERT INTO programs (unified_id, primary_name, aliases_json, "
            "tier, excluded, updated_at) "
            "VALUES (?, ?, '', 'A', 0, '2026-04-30')",
            rows,
        )
        conn.commit()
    finally:
        conn.close()


def test_generate_for_name_emits_kana_variants(gen_aliases_mod):
    """Pure-function happy path — kanji name yields hiragana + katakana
    aliases at minimum, plus the abbrev rule fires when a long-form
    ministry name is present."""
    kks = gen_aliases_mod._load_kakasi()
    name = "経済産業省 中小企業庁の小規模事業者持続化補助金"
    aliases, methods = gen_aliases_mod.generate_for_name(name, kks)

    # Always emits at least the hira + kata forms for kanji-bearing input.
    assert len(aliases) >= 2, f"expected ≥2 aliases, got {aliases!r}"
    assert "hira" in methods
    assert "kata" in methods
    # Abbrev rule should fire on 経済産業省 → 経産省 OR
    # 中小企業庁 → 中企庁 OR 小規模事業者持続化補助金 → 持続化補助金.
    assert "abbrev" in methods, (
        f"expected abbrev rule to fire, methods={methods!r}, aliases={aliases!r}"
    )
    # Cap is honoured.
    assert len(aliases) <= gen_aliases_mod.MAX_ALIASES
    # Aliases are deduplicated.
    assert len(set(aliases)) == len(aliases)
    # No alias is identical to the input.
    assert name not in aliases


def test_generate_for_name_handles_empty(gen_aliases_mod):
    """Empty input yields empty output; never raises."""
    kks = gen_aliases_mod._load_kakasi()
    aliases, methods = gen_aliases_mod.generate_for_name("", kks)
    assert aliases == []
    assert methods == []


def test_bracket_strip_removes_leading_decoration(gen_aliases_mod):
    """`【…】` and `MUN-…_pref_` ID prefixes are stripped exactly once."""
    kks = gen_aliases_mod._load_kakasi()
    name = "MUN-462187-002_霧島市_担い手経営発展等支援"
    aliases, methods = gen_aliases_mod.generate_for_name(name, kks)
    assert "bracket_strip" in methods
    # The stripped form should appear in aliases.
    assert "担い手経営発展等支援" in aliases


def test_width_normalisation_emits_halfwidth(gen_aliases_mod):
    """Full-width Ｒ６ should produce a half-width R6 alias."""
    kks = gen_aliases_mod._load_kakasi()
    name = "令和Ｒ６補助金"
    aliases, methods = gen_aliases_mod.generate_for_name(name, kks)
    assert "width" in methods, f"expected width rule to fire on {name!r}, methods={methods!r}"
    assert any("R6" in a for a in aliases), f"expected half-width R6 in aliases, got {aliases!r}"


def test_dry_run_smoke(tmp_path, gen_aliases_mod, capsys):
    """End-to-end: build a fixture DB, run main() with --dry-run --limit 1,
    assert exit 0 + stdout contains the expected program row."""
    db = tmp_path / "fixture.db"
    _seed_jpintel(
        db,
        [
            ("UNI-test-0001", "経済産業省 中小企業庁の小規模事業者持続化補助金"),
            ("UNI-test-0002", "ものづくり・商業・サービス生産性向上促進補助金"),
        ],
    )
    rc = gen_aliases_mod.main(
        [
            "--jpintel-db",
            str(db),
            "--limit",
            "1",
            "--dry-run",
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    # Header + at least one data row.
    assert "program_id\tprimary_name\taliases_json" in out
    assert "UNI-test-0001" in out
    # The aliases_json column must be a parseable JSON array.
    data_line = [line for line in out.splitlines() if line.startswith("UNI-test-0001")][0]
    cols = data_line.split("\t")
    aliases = json.loads(cols[2])
    assert isinstance(aliases, list)
    assert len(aliases) >= 2  # hira + kata + abbrev expected


def test_csv_write_path(tmp_path, gen_aliases_mod):
    """End-to-end: --output writes a CSV + sidecar stats JSON, both
    parseable, with the expected schema."""
    db = tmp_path / "fixture.db"
    _seed_jpintel(
        db,
        [
            ("UNI-test-A", "中小企業庁 経営革新支援"),
            ("UNI-test-B", "農林水産省の補助金"),
        ],
    )
    out_csv = tmp_path / "aliases.csv"
    rc = gen_aliases_mod.main(
        [
            "--jpintel-db",
            str(db),
            "--output",
            str(out_csv),
        ]
    )
    assert rc == 0
    assert out_csv.exists()
    text = out_csv.read_text(encoding="utf-8-sig")
    lines = text.splitlines()
    # Header + 2 data rows.
    assert len(lines) == 3
    assert "program_id" in lines[0]
    # Stats sidecar exists and parses.
    stats_path = out_csv.with_suffix(".stats.json")
    assert stats_path.exists()
    stats = json.loads(stats_path.read_text(encoding="utf-8"))
    assert stats["total_programs"] == 2
    assert stats["with_at_least_one_alias"] >= 1
    assert "hira" in stats["method_fire_count"]


def test_only_empty_filters_existing_aliases(tmp_path, gen_aliases_mod):
    """`--only-empty` skips rows whose aliases_json is already populated."""
    db = tmp_path / "fixture.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE programs (
            unified_id TEXT PRIMARY KEY,
            primary_name TEXT NOT NULL,
            aliases_json TEXT,
            tier TEXT,
            excluded INTEGER DEFAULT 0,
            updated_at TEXT
        );
        """
    )
    conn.execute(
        "INSERT INTO programs VALUES ('UNI-empty', '中小企業庁支援', '', 'A', 0, '2026-04-30')"
    )
    conn.execute(
        "INSERT INTO programs VALUES "
        "('UNI-filled', '経済産業省支援', '[\"既存alias\"]', 'A', 0, '2026-04-30')"
    )
    conn.commit()
    conn.close()

    out_csv = tmp_path / "out.csv"
    rc = gen_aliases_mod.main(
        [
            "--jpintel-db",
            str(db),
            "--output",
            str(out_csv),
            "--only-empty",
        ]
    )
    assert rc == 0
    text = out_csv.read_text(encoding="utf-8-sig")
    assert "UNI-empty" in text
    assert "UNI-filled" not in text


def test_read_only_db_open(tmp_path, gen_aliases_mod):
    """The DB is opened via `?mode=ro` URI — confirm by trying to write
    after the script's iter_programs returns: a parallel writer
    attempting INSERT must still succeed (sanity check that the script
    didn't take an exclusive lock)."""
    db = tmp_path / "ro.db"
    _seed_jpintel(db, [("UNI-ro-1", "テスト補助金")])
    # Drain the iterator (this is what the script does internally).
    rows = list(gen_aliases_mod.iter_programs(db, only_empty=False, limit=None))
    assert len(rows) == 1
    # Now open R/W from a separate connection — should not be locked.
    rw = sqlite3.connect(db)
    try:
        rw.execute(
            "INSERT INTO programs (unified_id, primary_name, tier, excluded, "
            "updated_at) VALUES ('UNI-ro-2', 'X', 'A', 0, '2026-04-30')"
        )
        rw.commit()
    finally:
        rw.close()
    # Verify the second row landed.
    check = sqlite3.connect(db)
    n = check.execute("SELECT COUNT(*) FROM programs").fetchone()[0]
    check.close()
    assert n == 2
