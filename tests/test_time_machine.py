"""DEEP-22 Regulatory Time Machine — 5-case unit suite.

Covers `_query_at_snapshot_impl` and `_query_program_evolution_impl` from
`jpintel_mcp.mcp.autonomath_tools.time_machine_tools`.

Five cases per the DEEP-22 §7 spec:

  1. definitive          — effective_from set, returns quality_flag='definitive'
  2. inferred            — effective_from NULL, hash matches v(n-1) → quality_flag='inferred',
                           known_gaps includes 'eligibility_text_diff_unverified'
  3. template_default    — am_amount_condition.template_default=1 → amount=null,
                           quality_flag='template_default', known_gaps includes
                           'amount_not_captured_at_date'
  4. not_found           — program_id absent → seed_not_found error envelope
  5. before_first_capture — as_of < min(effective_from) → as_of_resolved=null

Plus 1 happy-path case for the 12-month evolution variant.

Uses a tmp sqlite DB fixture (no mocks per CLAUDE.md L203) so the suite
is deterministic across machines and does not depend on production
autonomath.db row values.
"""

from __future__ import annotations

import os
import sqlite3
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

# ---------------------------------------------------------------------------
# Tmp DB fixture — minimal am_amendment_snapshot + am_amount_condition
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def tmp_autonomath_db(tmp_path_factory) -> Path:
    """Build a minimal autonomath.db with the rows our 5 cases need."""
    db_path = tmp_path_factory.mktemp("time_machine") / "autonomath.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript(
        """
        CREATE TABLE am_amendment_snapshot (
            snapshot_id        INTEGER PRIMARY KEY AUTOINCREMENT,
            entity_id          TEXT NOT NULL,
            version_seq        INTEGER NOT NULL,
            observed_at        TEXT NOT NULL,
            effective_from     TEXT,
            effective_until    TEXT,
            amount_max_yen     INTEGER,
            subsidy_rate_max   REAL,
            target_set_json    TEXT,
            eligibility_hash   TEXT,
            summary_hash       TEXT,
            source_url         TEXT,
            source_fetched_at  TEXT,
            raw_snapshot_json  TEXT,
            UNIQUE (entity_id, version_seq)
        );

        CREATE INDEX ix_am_amendment_snapshot_entity_effective
            ON am_amendment_snapshot(entity_id, effective_from);
        CREATE INDEX ix_am_amendment_snapshot_entity_version
            ON am_amendment_snapshot(entity_id, version_seq DESC);

        CREATE TABLE am_amount_condition (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            entity_id           TEXT NOT NULL,
            condition_label     TEXT NOT NULL,
            fixed_yen           INTEGER,
            percentage          REAL,
            source_field        TEXT NOT NULL,
            promoted_at         TEXT NOT NULL DEFAULT (datetime('now')),
            template_default    INTEGER NOT NULL DEFAULT 0
        );

        -- programs / laws / tax_rulesets / court_decisions / am_entities
        -- needed for snapshot_helper.attach_corpus_snapshot. Keep empty.
        CREATE TABLE programs (id INTEGER PRIMARY KEY, source_fetched_at TEXT);
        CREATE TABLE laws (id INTEGER PRIMARY KEY, fetched_at TEXT);
        CREATE TABLE tax_rulesets (id INTEGER PRIMARY KEY, fetched_at TEXT);
        CREATE TABLE court_decisions (id INTEGER PRIMARY KEY, fetched_at TEXT);
        CREATE TABLE am_entities (canonical_id TEXT PRIMARY KEY, fetched_at TEXT);
        CREATE TABLE am_amendment_diff (id INTEGER PRIMARY KEY, detected_at TEXT);
        """
    )

    # --- Case 1: definitive (effective_from set) ---
    conn.execute(
        """
        INSERT INTO am_amendment_snapshot (
            entity_id, version_seq, observed_at, effective_from,
            amount_max_yen, subsidy_rate_max, eligibility_hash,
            source_url, source_fetched_at, raw_snapshot_json
        ) VALUES (?,?,?,?,?,?,?,?,?,?)
        """,
        (
            "program:DEFINITIVE",
            1,
            "2024-04-01T00:00:00Z",
            "2024-04-01",
            4_500_000,
            0.5,
            "f3c1abcdef12",
            "https://www.it-hojo.jp/r6/",
            "2024-04-15T03:21:08Z",
            '{"eligibility": {"sme_only": true}, "deadline": "2024-09-30"}',
        ),
    )

    # --- Case 2: inferred (effective_from NULL, hash matches v(n-1)) ---
    # Both v=1 and v=2 have NULL effective_from with the SAME eligibility_hash.
    # Per DEEP-22 §4: matched row's effective_from IS NULL → quality_flag='inferred'.
    # And since hash matches v(n-1), known_gaps gets 'eligibility_text_diff_unverified'.
    conn.execute(
        """
        INSERT INTO am_amendment_snapshot (
            entity_id, version_seq, observed_at, effective_from,
            amount_max_yen, subsidy_rate_max, eligibility_hash,
            source_url, source_fetched_at, raw_snapshot_json
        ) VALUES (?,?,?,?,?,?,?,?,?,?)
        """,
        (
            "program:INFERRED",
            1,
            "2023-04-01T00:00:00Z",
            None,  # NULL effective_from
            3_000_000,
            0.5,
            "samehashv1v2",
            "https://www.example.go.jp/inf",
            "2023-04-15T00:00:00Z",
            '{"eligibility": {"sme_only": true}}',
        ),
    )
    conn.execute(
        """
        INSERT INTO am_amendment_snapshot (
            entity_id, version_seq, observed_at, effective_from,
            amount_max_yen, subsidy_rate_max, eligibility_hash,
            source_url, source_fetched_at, raw_snapshot_json
        ) VALUES (?,?,?,?,?,?,?,?,?,?)
        """,
        (
            "program:INFERRED",
            2,
            "2024-04-01T00:00:00Z",
            None,  # NULL effective_from
            3_000_000,
            0.5,
            "samehashv1v2",  # same hash as v1 → known_gap surfaces
            "https://www.example.go.jp/inf2",
            "2024-04-15T00:00:00Z",
            '{"eligibility": {"sme_only": true}}',
        ),
    )

    # --- Case 3: template_default (am_amount_condition.template_default=1) ---
    conn.execute(
        """
        INSERT INTO am_amendment_snapshot (
            entity_id, version_seq, observed_at, effective_from,
            amount_max_yen, subsidy_rate_max, eligibility_hash,
            source_url, source_fetched_at, raw_snapshot_json
        ) VALUES (?,?,?,?,?,?,?,?,?,?)
        """,
        (
            "program:TEMPLATE",
            1,
            "2024-04-01T00:00:00Z",
            "2024-04-01",
            500_000,  # broken-ETL placeholder
            None,
            "templatehash01",
            "https://www.example.go.jp/tmpl",
            "2024-04-15T00:00:00Z",
            '{"eligibility": {"sme_only": true}}',
        ),
    )
    conn.execute(
        """
        INSERT INTO am_amount_condition (
            entity_id, condition_label, fixed_yen, percentage,
            source_field, template_default
        ) VALUES (?,?,?,?,?,?)
        """,
        (
            "program:TEMPLATE",
            "sme",
            500_000,
            None,
            "raw.amount_yen",
            1,  # template_default = 1
        ),
    )

    conn.commit()
    conn.close()

    return db_path


@pytest.fixture(autouse=True)
def _wire_env_to_tmp_db(tmp_autonomath_db: Path, _reset_anon_rate_limit: None):
    """Point AUTONOMATH_DB_PATH at the tmp DB BEFORE each test runs.

    Function-scoped + autouse so this overrides the conftest
    ``_restore_autonomath_paths`` autouse that runs before every test
    and resets env vars to the production path. Pytest does not guarantee
    autouse fixture order across same-scope fixtures, so we must do all
    the env+state mutation here per test (cheap — fixture body is
    ~20 lines of os.environ assignments + cache resets).
    """
    prev = os.environ.get("AUTONOMATH_DB_PATH")
    prev_jpcite = os.environ.get("JPCITE_AUTONOMATH_DB_PATH")
    os.environ["AUTONOMATH_DB_PATH"] = str(tmp_autonomath_db)
    os.environ["JPCITE_AUTONOMATH_DB_PATH"] = str(tmp_autonomath_db)
    os.environ["AUTONOMATH_SNAPSHOT_ENABLED"] = "1"
    os.environ["JPCITE_SNAPSHOT_ENABLED"] = "1"
    os.environ["AUTONOMATH_ENABLED"] = "1"
    os.environ["JPCITE_AUTONOMATH_ENABLED"] = "1"
    prev_settings_path = None

    # Override settings.autonomath_db_path on the live singleton so
    # consumers that did `from jpintel_mcp.config import settings` see
    # the tmp path on this test's invocation.
    try:
        from jpintel_mcp.config import settings as _live_settings

        prev_settings_path = _live_settings.autonomath_db_path
        _live_settings.autonomath_db_path = tmp_autonomath_db
    except Exception:
        pass

    # Reset snapshot_helper cache so corpus_snapshot_id reflects the tmp DB.
    try:
        from jpintel_mcp.mcp.autonomath_tools import snapshot_helper

        snapshot_helper._reset_cache_for_tests()
    except Exception:
        pass

    # Reset the per-thread connection in db.py so connect_autonomath()
    # opens a fresh handle to the tmp DB rather than reusing the cached
    # production handle.
    try:
        from jpintel_mcp.mcp.autonomath_tools import db as _autonomath_db_module

        _autonomath_db_module.close_all()
    except Exception:
        pass

    yield

    if prev is None:
        os.environ.pop("AUTONOMATH_DB_PATH", None)
    else:
        os.environ["AUTONOMATH_DB_PATH"] = prev
    if prev_jpcite is None:
        os.environ.pop("JPCITE_AUTONOMATH_DB_PATH", None)
    else:
        os.environ["JPCITE_AUTONOMATH_DB_PATH"] = prev_jpcite
    if prev_settings_path is not None:
        try:
            from jpintel_mcp.config import settings as _live_settings

            _live_settings.autonomath_db_path = prev_settings_path
        except Exception:
            pass
    try:
        from jpintel_mcp.mcp.autonomath_tools import db as _autonomath_db_module

        _autonomath_db_module.close_all()
    except Exception:
        pass


# Import the impls AFTER the env fixture has run so the module-level
# constants pick up the right gate. Import at module top would also work
# (impls don't read env at import time) but this matches the pattern of
# test_industry_packs.py / test_wave22_tools.py.
from jpintel_mcp.mcp.autonomath_tools.time_machine_tools import (  # noqa: E402
    _query_at_snapshot_impl,
    _query_program_evolution_impl,
)

# ---------------------------------------------------------------------------
# Shared envelope assertions
# ---------------------------------------------------------------------------


def _assert_canonical_keys(out: dict) -> None:
    """Every successful response must hold this shape."""
    assert isinstance(out, dict)
    for key in (
        "program_id",
        "as_of_resolved",
        "eligibility",
        "amount",
        "deadline",
        "source_url",
        "source_fetched_at",
        "source_sha256",
        "quality_flag",
        "known_gaps",
        "_disclaimer",
        "_billing_unit",
    ):
        assert key in out, f"missing top-level key {key!r}; got {list(out)[:12]}"
    assert out["_billing_unit"] == 1
    assert isinstance(out["_disclaimer"], str)
    assert "税理士法" in out["_disclaimer"] or "§52" in out["_disclaimer"]
    assert isinstance(out["known_gaps"], list)


# ---------------------------------------------------------------------------
# Case 1 — definitive
# ---------------------------------------------------------------------------


def test_definitive_dated_query_returns_definitive_quality_flag() -> None:
    out = _query_at_snapshot_impl(program_id="program:DEFINITIVE", as_of="2024-06-01")
    _assert_canonical_keys(out)
    assert "error" not in out
    assert out["quality_flag"] == "definitive"
    assert out["as_of_resolved"] == "2024-04-01"
    assert out["known_gaps"] == [], f"expected empty known_gaps, got {out['known_gaps']!r}"
    assert out["amount"] == {"max_yen": 4_500_000, "rate": 0.5}
    assert out["source_url"] == "https://www.it-hojo.jp/r6/"
    assert out["source_fetched_at"] == "2024-04-15T03:21:08Z"
    assert out["source_sha256"] == "f3c1abcdef12"
    assert out["deadline"] == "2024-09-30"
    assert out["eligibility"] == {"sme_only": True}


# ---------------------------------------------------------------------------
# Case 2 — inferred (eligibility_hash v1 == v2)
# ---------------------------------------------------------------------------


def test_inferred_query_with_matching_hash_surfaces_known_gap() -> None:
    out = _query_at_snapshot_impl(program_id="program:INFERRED", as_of="2024-06-01")
    _assert_canonical_keys(out)
    assert "error" not in out
    assert out["quality_flag"] == "inferred"
    # The most-recent row at 2024-06-01 is v=2, which has NULL effective_from
    assert out["as_of_resolved"] is None
    assert "eligibility_text_diff_unverified" in out["known_gaps"]


# ---------------------------------------------------------------------------
# Case 3 — template_default
# ---------------------------------------------------------------------------


def test_template_default_amount_returns_null_amount_and_known_gap() -> None:
    out = _query_at_snapshot_impl(program_id="program:TEMPLATE", as_of="2024-06-01")
    _assert_canonical_keys(out)
    assert "error" not in out
    assert out["quality_flag"] == "template_default"
    assert out["amount"] is None
    assert "amount_not_captured_at_date" in out["known_gaps"]


# ---------------------------------------------------------------------------
# Case 4 — not_found
# ---------------------------------------------------------------------------


def test_unknown_program_returns_seed_not_found_error() -> None:
    out = _query_at_snapshot_impl(program_id="program:NONEXISTENT_W7", as_of="2024-06-01")
    assert isinstance(out, dict)
    assert "error" in out
    assert out["error"]["code"] == "seed_not_found"
    assert out["error"]["field"] == "program_id"
    # Error envelope still carries the standard pagination keys.
    assert out["total"] == 0
    assert out["results"] == []


# ---------------------------------------------------------------------------
# Case 5 — before_first_capture
# ---------------------------------------------------------------------------


def test_before_first_capture_returns_null_resolved() -> None:
    out = _query_at_snapshot_impl(program_id="program:DEFINITIVE", as_of="2010-01-01")
    _assert_canonical_keys(out)
    assert "error" not in out
    assert out["as_of_resolved"] is None
    assert out["eligibility"] is None
    assert out["amount"] is None
    assert out["source_url"] is None
    assert out["source_sha256"] is None
    assert "before_first_capture" in out["known_gaps"]
    assert out["total"] == 0


# ---------------------------------------------------------------------------
# Bonus — 12-month evolution grid (compound form)
# ---------------------------------------------------------------------------


def test_evolution_grid_returns_12_months_with_single_billing_unit() -> None:
    out = _query_program_evolution_impl(program_id="program:DEFINITIVE", year=2024)
    assert "error" not in out
    assert out["program_id"] == "program:DEFINITIVE"
    assert out["year"] == 2024
    assert isinstance(out["months"], list)
    assert len(out["months"]) == 12
    assert out["_billing_unit"] == 1, "12-month evolution must bill as a single ¥3 unit"
    assert isinstance(out["_disclaimer"], str)
    # First three months are pre-effective_from (2024-04-01), so as_of_resolved=null
    # April onward should resolve to "2024-04-01".
    apr_envelope = out["months"][3]
    assert apr_envelope["as_of_resolved"] == "2024-04-01"
    # change_months should mark the transition (March→April).
    assert isinstance(out["change_months"], list)


# ---------------------------------------------------------------------------
# Validation paths
# ---------------------------------------------------------------------------


def test_invalid_date_format_returns_invalid_date_format_error() -> None:
    out = _query_at_snapshot_impl(program_id="program:DEFINITIVE", as_of="not-a-date")
    assert "error" in out
    assert out["error"]["code"] == "invalid_date_format"


def test_missing_program_id_returns_missing_required_arg() -> None:
    out = _query_at_snapshot_impl(program_id="", as_of="2024-06-01")
    assert "error" in out
    assert out["error"]["code"] == "missing_required_arg"
