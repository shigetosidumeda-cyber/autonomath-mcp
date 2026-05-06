"""Smoke tests for `_get_program_narrative_impl` (Wave24 #107).

W3-12 launch blocker (UC3/UC4/UC7): the impl previously SELECTed
`content_md / content_hash / computed_at`, none of which exist on
`am_program_narrative` (real cols: `body_text / source_url_json /
generated_at`). Every call returned
``db_unavailable: no such column: content_md``.

These tests pin the schema contract so the regression cannot recur:

  1. Missing `program_id`        -> `missing_required_arg` envelope.
  2. Invalid `section`           -> `invalid_enum` envelope.
  3. Empty table                 -> empty envelope, NO `db_unavailable`.
  4. Real rows + section='all'   -> 4-row pull ordered overview→pitfalls,
                                    `is_active=0` rows filtered out,
                                    `source_url_json` JSON-decoded.
  5. Real rows + specific section -> 1 active row.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest


# ----- helpers --------------------------------------------------------------


def _create_narrative_schema(conn: sqlite3.Connection) -> None:
    """Mirror migrations wave24_136 + wave24_141 (post-ALTER shape)."""
    conn.executescript(
        """
        CREATE TABLE am_program_narrative (
            narrative_id                INTEGER PRIMARY KEY AUTOINCREMENT,
            program_id                  INTEGER NOT NULL,
            lang                        TEXT NOT NULL CHECK (lang IN ('ja','en')),
            section                     TEXT NOT NULL CHECK (section IN (
                                            'overview','eligibility',
                                            'application_flow','pitfalls'
                                        )),
            body_text                   TEXT NOT NULL,
            source_url_json             TEXT,
            model_id                    TEXT,
            generated_at                TEXT NOT NULL DEFAULT (datetime('now')),
            literal_quote_check_passed  INTEGER NOT NULL DEFAULT 0
                                         CHECK (literal_quote_check_passed IN (0, 1)),
            is_active                   INTEGER NOT NULL DEFAULT 1
                                         CHECK (is_active IN (0, 1)),
            quarantine_id               INTEGER,
            content_hash                TEXT,
            UNIQUE (program_id, lang, section)
        );
        """
    )


def _seed_program_42(conn: sqlite3.Connection) -> None:
    conn.executemany(
        """
        INSERT INTO am_program_narrative
          (program_id, lang, section, body_text, source_url_json,
           model_id, generated_at, literal_quote_check_passed,
           is_active, content_hash)
        VALUES (?,?,?,?,?,?,?,?,?,?)
        """,
        [
            (
                42,
                "ja",
                "overview",
                "本制度は…",
                '["https://example.gov/x"]',
                "claude-opus-4-7",
                "2026-05-01T00:00:00Z",
                1,
                1,
                "sha256:abc",
            ),
            (
                42,
                "ja",
                "eligibility",
                "対象は…",
                '["https://example.gov/y"]',
                "claude-opus-4-7",
                "2026-05-01T00:00:00Z",
                1,
                1,
                "sha256:def",
            ),
            (
                42,
                "ja",
                "application_flow",
                "手続は…",
                None,
                None,
                "2026-05-01T00:00:00Z",
                0,
                1,
                None,
            ),
            # Inactive — must NOT appear in any result set.
            (42, "ja", "pitfalls", "注意点…", None, None, "2026-05-01T00:00:00Z", 0, 0, None),
        ],
    )
    conn.commit()


@pytest.fixture()
def narrative_empty_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """autonomath.db with the narrative schema but no rows."""
    db_path = tmp_path / "autonomath.db"
    conn = sqlite3.connect(db_path)
    try:
        _create_narrative_schema(conn)
    finally:
        conn.close()
    monkeypatch.setenv("AUTONOMATH_DB_PATH", str(db_path))
    return db_path


@pytest.fixture()
def narrative_seeded_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """autonomath.db preloaded with 4 rows for program_id=42 (3 active)."""
    db_path = tmp_path / "autonomath.db"
    conn = sqlite3.connect(db_path)
    try:
        _create_narrative_schema(conn)
        _seed_program_42(conn)
    finally:
        conn.close()
    monkeypatch.setenv("AUTONOMATH_DB_PATH", str(db_path))
    return db_path


def _impl():
    """Late-bind the impl AFTER AUTONOMATH_DB_PATH is set so the per-thread
    autonomath connection rebinds to the temp DB.
    """
    from jpintel_mcp.mcp.autonomath_tools.wave24_tools_first_half import (
        _get_program_narrative_impl,
    )

    return _get_program_narrative_impl


# ----- tests ----------------------------------------------------------------


def test_missing_program_id_returns_validation_error(narrative_empty_db: Path) -> None:
    out = _impl()(program_id="", section="all", lang="ja")
    assert out["error"]["code"] == "missing_required_arg"
    assert out["error"]["field"] == "program_id"


def test_invalid_section_returns_invalid_enum(narrative_empty_db: Path) -> None:
    out = _impl()(program_id="42", section="garbage", lang="ja")
    assert out["error"]["code"] == "invalid_enum"
    assert out["error"]["field"] == "section"


def test_empty_table_returns_empty_envelope_not_db_unavailable(
    narrative_empty_db: Path,
) -> None:
    """Regression guard for W3-12 — must NOT emit `db_unavailable: no such column`."""
    out = _impl()(program_id="999", section="all", lang="ja")
    # Success-shape envelope; no error block.
    assert "error" not in out, f"unexpected error envelope: {out}"
    assert out["total"] == 0
    assert out["results"] == []
    assert out["program_id"] == "999"
    assert out["section"] == "all"
    assert out["lang"] == "ja"


def test_section_all_returns_active_rows_in_canonical_order(
    narrative_seeded_db: Path,
) -> None:
    out = _impl()(program_id="42", section="all", lang="ja")
    assert "error" not in out
    # 3 active rows (pitfalls is is_active=0 → excluded).
    assert out["total"] == 3
    sections = [r["section"] for r in out["results"]]
    assert sections == ["overview", "eligibility", "application_flow"]
    # Schema-shape: load-bearing column rename guards.
    first = out["results"][0]
    for k in (
        "section",
        "lang",
        "body_text",
        "content_hash",
        "is_active",
        "source_url_json",
        "generated_at",
        "model_id",
        "literal_quote_check_passed",
    ):
        assert k in first, f"missing key {k!r} in result row"
    # source_url_json must be JSON-decoded (list, not raw string).
    assert first["source_url_json"] == ["https://example.gov/x"]
    assert first["body_text"] == "本制度は…"
    assert first["literal_quote_check_passed"] is True


def test_specific_section_returns_single_active_row(narrative_seeded_db: Path) -> None:
    out = _impl()(program_id="42", section="overview", lang="ja")
    assert "error" not in out
    assert out["total"] == 1
    assert out["results"][0]["section"] == "overview"
    assert out["results"][0]["body_text"] == "本制度は…"


def test_inactive_row_is_filtered_for_specific_section(narrative_seeded_db: Path) -> None:
    """`pitfalls` row was seeded with is_active=0 → must yield 0 results."""
    out = _impl()(program_id="42", section="pitfalls", lang="ja")
    assert "error" not in out
    assert out["total"] == 0
    assert out["results"] == []
