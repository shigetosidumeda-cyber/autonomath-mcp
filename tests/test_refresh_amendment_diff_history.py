"""Tests for `scripts/cron/refresh_amendment_diff_history.py` (W3-12 / W3-13).

Covers:
  * Two consecutive `am_program_eligibility_history` rows with drifted
    `eligibility_hash` produce diff rows in `am_amendment_diff`.
  * Identical `eligibility_hash` between consecutive rows produces no
    diff (idempotent skip).
  * Re-running on the same source corpus is idempotent (no duplicate
    inserts on second invocation).
  * `--dry-run` does not write any rows.
  * `--max-programs` caps the program scan.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import sqlite3
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator

# Allow importing scripts/cron/refresh_amendment_diff_history.py without
# needing `pip install -e .` to expose it.
_REPO = Path(__file__).resolve().parent.parent
_CRON_DIR = _REPO / "scripts" / "cron"
if str(_CRON_DIR) not in sys.path:
    sys.path.insert(0, str(_CRON_DIR))


@pytest.fixture
def cron_module():
    """Import the cron module fresh for each test (no cross-test state)."""
    if "refresh_amendment_diff_history" in sys.modules:
        del sys.modules["refresh_amendment_diff_history"]
    mod = importlib.import_module("refresh_amendment_diff_history")
    return mod


@pytest.fixture
def seeded_db(tmp_path: Path) -> Iterator[Path]:
    """Build an in-memory-style SQLite file with both source + sink tables.

    The cron's `connect()` helper opens the DB on disk; we materialize
    the schema on a temporary file path so the cron sees real I/O, not
    `:memory:` (the production code path uses a real Fly volume file).
    """
    db_path = tmp_path / "autonomath.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        -- Mirror migration wave24_106 (am_program_eligibility_history).
        CREATE TABLE am_program_eligibility_history (
            history_id           INTEGER PRIMARY KEY AUTOINCREMENT,
            program_id           TEXT NOT NULL,
            captured_at          TEXT NOT NULL,
            source_url           TEXT,
            source_fetched_at    TEXT,
            content_hash         TEXT NOT NULL,
            eligibility_hash     TEXT,
            eligibility_struct   TEXT,
            diff_from_prev       TEXT,
            diff_reason          TEXT,
            UNIQUE (program_id, content_hash)
        );

        -- Mirror migration 075 (am_amendment_diff).
        CREATE TABLE am_amendment_diff (
            diff_id        INTEGER PRIMARY KEY AUTOINCREMENT,
            entity_id      TEXT NOT NULL,
            field_name     TEXT NOT NULL,
            prev_value     TEXT,
            new_value      TEXT,
            prev_hash      TEXT,
            new_hash       TEXT,
            detected_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            source_url     TEXT
        );
        """
    )
    conn.commit()
    conn.close()
    yield db_path


def _eligibility_struct(eligibility: dict) -> str:
    """Wrap an eligibility dict in the body+eligibility envelope shape."""
    return json.dumps({"body": {}, "eligibility": eligibility}, sort_keys=True, ensure_ascii=False)


def _hash(payload: dict) -> str:
    canon = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


def _seed_two_history_rows(
    db_path: Path,
    program_id: str,
    prev_eligibility: dict,
    new_eligibility: dict,
) -> tuple[str, str]:
    """Insert two history rows and return (prev_hash, new_hash)."""
    prev_hash = _hash(prev_eligibility)
    new_hash = _hash(new_eligibility)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executemany(
        """INSERT INTO am_program_eligibility_history
           (program_id, captured_at, source_url, source_fetched_at,
            content_hash, eligibility_hash, eligibility_struct,
            diff_from_prev, diff_reason)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        [
            (
                program_id,
                "2026-05-01T00:00:00Z",
                "https://example.gov/v1",
                "2026-05-01T00:00:00Z",
                "content-hash-1",
                prev_hash,
                _eligibility_struct(prev_eligibility),
                None,
                "initial",
            ),
            (
                program_id,
                "2026-05-02T00:00:00Z",
                "https://example.gov/v2",
                "2026-05-02T00:00:00Z",
                "content-hash-2",
                new_hash,
                _eligibility_struct(new_eligibility),
                None,
                "eligibility_drift",
            ),
        ],
    )
    conn.commit()
    conn.close()
    return prev_hash, new_hash


def test_drifted_hash_inserts_diff_row(cron_module, seeded_db: Path) -> None:
    """Two history rows with different eligibility_hash → at least 1 diff row."""
    program_id = "UNI-test-1"
    prev_elig = {"target_types": ["sole_proprietor"], "funding_purpose": ["設備投資"]}
    new_elig = {
        "target_types": ["sole_proprietor", "corporation"],
        "funding_purpose": ["設備投資"],
    }
    prev_hash, new_hash = _seed_two_history_rows(seeded_db, program_id, prev_elig, new_elig)

    counters = cron_module.run(am_db_path=seeded_db, max_programs=None, dry_run=False)

    assert counters["programs_scanned"] == 1
    assert counters["programs_with_change"] == 1
    assert counters["diff_rows_inserted"] >= 1

    conn = sqlite3.connect(seeded_db)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT entity_id, field_name, prev_hash, new_hash, "
        "       prev_value, new_value, source_url "
        "  FROM am_amendment_diff ORDER BY diff_id"
    ).fetchall()
    conn.close()

    assert len(rows) >= 1
    # target_types is the only group that changed; expect exactly one
    # 'eligibility:changed' row referencing it.
    changed_rows = [r for r in rows if r["field_name"] == "eligibility:changed"]
    assert len(changed_rows) == 1
    r = changed_rows[0]
    assert r["entity_id"] == program_id
    assert r["prev_hash"] == prev_hash
    assert r["new_hash"] == new_hash
    assert r["source_url"] == "https://example.gov/v2"

    summary = json.loads(r["new_value"])
    assert summary["change_kind"] == "changed"
    assert summary["program_id"] == program_id
    assert "target_types" in summary["predicate_groups"]
    assert summary["details"]["target_types"]["new"] == new_elig["target_types"]


def test_identical_hash_inserts_nothing(cron_module, seeded_db: Path) -> None:
    """Same eligibility_hash on consecutive rows → 0 diff rows."""
    program_id = "UNI-test-2"
    elig = {"target_types": ["corporation"]}
    _seed_two_history_rows(seeded_db, program_id, elig, elig)

    counters = cron_module.run(am_db_path=seeded_db, max_programs=None, dry_run=False)

    assert counters["diff_rows_inserted"] == 0

    conn = sqlite3.connect(seeded_db)
    n = conn.execute("SELECT COUNT(*) FROM am_amendment_diff").fetchone()[0]
    conn.close()
    assert n == 0


def test_idempotent_rerun(cron_module, seeded_db: Path) -> None:
    """Running twice on the same corpus inserts the same row count, not double."""
    program_id = "UNI-test-3"
    prev_elig = {"target_types": ["sole_proprietor"]}
    new_elig = {"target_types": ["corporation"]}
    _seed_two_history_rows(seeded_db, program_id, prev_elig, new_elig)

    first = cron_module.run(am_db_path=seeded_db, max_programs=None, dry_run=False)
    second = cron_module.run(am_db_path=seeded_db, max_programs=None, dry_run=False)

    assert first["diff_rows_inserted"] >= 1
    assert second["diff_rows_inserted"] == 0

    conn = sqlite3.connect(seeded_db)
    n = conn.execute("SELECT COUNT(*) FROM am_amendment_diff").fetchone()[0]
    conn.close()
    assert n == first["diff_rows_inserted"]


def test_dry_run_writes_no_rows(cron_module, seeded_db: Path) -> None:
    """`--dry-run` reports inserts but does not write am_amendment_diff."""
    program_id = "UNI-test-4"
    prev_elig = {"funding_purpose": ["継承"]}
    new_elig = {"funding_purpose": ["継承", "設備投資"]}
    _seed_two_history_rows(seeded_db, program_id, prev_elig, new_elig)

    counters = cron_module.run(am_db_path=seeded_db, max_programs=None, dry_run=True)

    assert counters["diff_rows_inserted"] >= 1

    conn = sqlite3.connect(seeded_db)
    n = conn.execute("SELECT COUNT(*) FROM am_amendment_diff").fetchone()[0]
    conn.close()
    assert n == 0


def test_max_programs_caps_scan(cron_module, seeded_db: Path) -> None:
    """`--max-programs N` limits the program walk to N programs."""
    for i in range(3):
        _seed_two_history_rows(
            seeded_db,
            f"UNI-cap-{i}",
            {"target_types": ["sole_proprietor"]},
            {"target_types": ["corporation"]},
        )

    counters = cron_module.run(am_db_path=seeded_db, max_programs=1, dry_run=False)

    assert counters["programs_scanned"] == 1


def test_added_and_removed_predicate_groups(cron_module, seeded_db: Path) -> None:
    """A drift that removes one group and adds another lands distinct rows."""
    program_id = "UNI-test-5"
    prev_elig = {"target_types": ["sole_proprietor"]}
    new_elig = {"funding_purpose": ["設備投資"]}
    _seed_two_history_rows(seeded_db, program_id, prev_elig, new_elig)

    cron_module.run(am_db_path=seeded_db, max_programs=None, dry_run=False)

    conn = sqlite3.connect(seeded_db)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT field_name FROM am_amendment_diff WHERE entity_id = ?",
        (program_id,),
    ).fetchall()
    conn.close()

    field_names = {r["field_name"] for r in rows}
    assert "eligibility:added" in field_names
    assert "eligibility:removed" in field_names


def test_missing_source_table_returns_zero(cron_module, tmp_path: Path) -> None:
    """When am_program_eligibility_history is absent, run() no-ops + logs."""
    db_path = tmp_path / "empty.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE am_amendment_diff (
            diff_id INTEGER PRIMARY KEY AUTOINCREMENT,
            entity_id TEXT NOT NULL,
            field_name TEXT NOT NULL,
            prev_value TEXT, new_value TEXT,
            prev_hash TEXT, new_hash TEXT,
            detected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            source_url TEXT
        );
        """
    )
    conn.commit()
    conn.close()

    counters = cron_module.run(am_db_path=db_path, max_programs=None, dry_run=False)
    assert counters["programs_scanned"] == 0
    assert counters["diff_rows_inserted"] == 0
