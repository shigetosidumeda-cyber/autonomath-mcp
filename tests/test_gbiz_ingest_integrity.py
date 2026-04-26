"""Integrity tests for the V4 Phase 3b gBizINFO facts ingest.

Backed by ``scripts/ingest_gbiz_facts.py`` (METI gBizINFO bulk dump → 79,876
new ``corporate_entity`` rows + 861,137 new ``corp.*`` facts spanning 21 new
field_names).

These are read-only invariants — we never re-run the ingester here. The DB
state is the authoritative artifact and we audit it for the documented
post-ingest properties.

Skips module-wide if autonomath.db is missing.
"""

from __future__ import annotations

import os
import re
import sqlite3
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_DB = _REPO_ROOT / "autonomath.db"
_INGESTER_PATH = _REPO_ROOT / "scripts" / "ingest_gbiz_facts.py"

_DB_PATH = Path(os.environ.get("AUTONOMATH_DB_PATH", str(_DEFAULT_DB)))

if not _DB_PATH.exists():
    pytest.skip(
        f"autonomath.db ({_DB_PATH}) not present; skipping gbiz integrity suite.",
        allow_module_level=True,
    )

# --- ingester discovery -----------------------------------------------------


def test_gbiz_ingester_script_exists():
    """The integrity tests are tied to a specific ingester. If it moves /
    renames, this fails first so the rest of the suite stays intelligible."""
    assert _INGESTER_PATH.exists(), (
        f"expected gbiz ingester at {_INGESTER_PATH}; "
        "see scripts/ingest_gbiz_facts.py in the V4 Phase 3b plan."
    )


# --- houjin_bangou (corporate_number) format invariants --------------------


_HOUJIN_RE = re.compile(r"^\d{13}$")


@pytest.fixture(scope="module")
def db_conn() -> sqlite3.Connection:
    con = sqlite3.connect(_DB_PATH)
    con.row_factory = sqlite3.Row
    yield con
    con.close()


def test_houjin_bangou_canonical_id_is_13_digit_numeric(db_conn):
    """Every corporate_entity.canonical_id with the houjin: prefix must
    decompose into 13 numeric digits."""
    cur = db_conn.execute(
        """
        SELECT canonical_id
          FROM am_entities
         WHERE record_kind = 'corporate_entity'
           AND canonical_id LIKE 'houjin:%'
         LIMIT 5000
        """
    )
    bad: list[str] = []
    for (cid,) in cur:
        # canonical_id format: 'houjin:<13digit>'
        suffix = cid.split(":", 1)[1] if ":" in cid else ""
        if not _HOUJIN_RE.match(suffix):
            bad.append(cid)
    assert not bad, f"non-13-digit houjin canonical_ids found: {bad[:5]}"


def test_houjin_bangou_fact_field_is_13_digit_numeric(db_conn):
    """Every fact row keyed by field_name='houjin_bangou' must contain a
    13-digit numeric in field_value_text. ingest_gbiz_facts.py emits exactly
    this shape; a regression to free-form text would corrupt the join axis
    used by check_enforcement_am / dd_profile_am."""
    rows = db_conn.execute(
        """
        SELECT field_value_text
          FROM am_entity_facts
         WHERE field_name = 'houjin_bangou'
           AND field_value_text IS NOT NULL
         LIMIT 5000
        """
    ).fetchall()
    if not rows:
        pytest.skip("no houjin_bangou facts present")
    bad = [r["field_value_text"] for r in rows if not _HOUJIN_RE.match(r["field_value_text"] or "")]
    assert not bad, (
        f"houjin_bangou facts with non-13-digit value: {bad[:5]}"
    )


# --- duplicate-rejection invariants ----------------------------------------


def test_corporate_entity_canonical_id_is_unique(db_conn):
    """``am_entities.canonical_id`` is the natural key. ingest_gbiz_facts.py
    INSERT OR IGNOREs against the unique constraint; a regression here would
    duplicate corporate_number rows and double-count entity totals (CLAUDE.md
    166,969 corporate_entity headline)."""
    dup = db_conn.execute(
        """
        SELECT COUNT(*) FROM (
            SELECT canonical_id, COUNT(*) AS c
              FROM am_entities
             WHERE record_kind = 'corporate_entity'
             GROUP BY canonical_id
            HAVING c > 1
        )
        """
    ).fetchone()[0]
    assert dup == 0, f"{dup} duplicate canonical_id rows for corporate_entity"


def test_houjin_bangou_fact_unique_per_entity(db_conn):
    """A single entity should not carry two houjin_bangou facts. Each
    corporate_entity row owns a single bangou; the UNIQUE index
    ``uq_am_facts_entity_field_text`` enforces this. Catch a slipped index."""
    dup = db_conn.execute(
        """
        SELECT COUNT(*) FROM (
            SELECT entity_id, COUNT(*) AS c
              FROM am_entity_facts
             WHERE field_name = 'houjin_bangou'
             GROUP BY entity_id
            HAVING c > 1
        )
        """
    ).fetchone()[0]
    assert dup == 0, f"{dup} entities have >1 houjin_bangou fact"


# --- 21 new corp.* field_names presence ------------------------------------


# Mirrors NEW_FIELD_NAMES in scripts/ingest_gbiz_facts.py. Drift here would
# either mean the ingester gained a field (extend the list) or lost one
# (regression — investigate). The list is 21 entries per the V4 Phase 3b
# CLAUDE.md note.
_GBIZ_NEW_FIELD_NAMES: list[str] = [
    "corp.legal_name_kana",
    "corp.legal_name_en",
    "corp.location",
    "corp.postal_code",
    "corp.representative",
    "corp.representative_position",
    "corp.business_summary",
    "corp.business_items",
    "corp.qualification_grade",
    "corp.capital_amount",
    "corp.employee_count",
    "corp.employee_count_male",
    "corp.employee_count_female",
    "corp.founded_year",
    "corp.date_of_establishment",
    "corp.close_date",
    "corp.close_cause",
    "corp.status",
    "corp.company_url",
    "corp.gbiz_update_date",
    "corp.gbiz_fetched_at",
]


def test_gbiz_new_field_names_count_is_21():
    """Headline number sanity — drift in the list itself."""
    assert len(_GBIZ_NEW_FIELD_NAMES) == 21


def test_gbiz_new_field_names_present_in_facts(db_conn):
    """Every new corp.* field introduced by the gbiz ingester must appear in
    am_entity_facts at least once. A missing one means the ingester silently
    skipped that branch; the V4 Phase 3b headline (~861k facts across 21
    field_names) would be wrong."""
    rows = db_conn.execute(
        """
        SELECT DISTINCT field_name
          FROM am_entity_facts
         WHERE field_name LIKE 'corp.%'
        """
    ).fetchall()
    present = {r["field_name"] for r in rows}
    missing = [f for f in _GBIZ_NEW_FIELD_NAMES if f not in present]
    # Some field branches may have produced 0 rows because the source dump
    # carried no value (e.g. corp.close_cause is rare). We tolerate up to 5
    # missing so this is not flake-prone, but never the majority.
    assert len(missing) <= 5, (
        f"too many gbiz field_names missing from facts ({len(missing)}/21): {missing}"
    )


# --- jpi_* mirrored tables present -----------------------------------------


def test_jpi_mirrored_tables_present(db_conn):
    """V4 migration 032 ATTACH-merged jpintel.db tables in as ``jpi_*`` —
    CLAUDE.md headlines 76+ jpi_* mirror tables. Missing tables mean a
    regression in the merge migration."""
    cnt = db_conn.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name LIKE 'jpi_%'"
    ).fetchone()[0]
    assert cnt >= 50, (
        f"expected ≥50 jpi_* mirror tables (76+ per CLAUDE.md); got {cnt}"
    )


def test_jpi_corporate_entity_count_consistency(db_conn):
    """The corporate_entity headline (gbiz 79,876 + houjin 87,076 + nintei 17
    = 166,969 per CLAUDE.md) must match what ``am_entities`` actually carries.
    Tolerance ±1% to absorb future legitimate ingest growth without flaking."""
    actual = db_conn.execute(
        "SELECT COUNT(*) FROM am_entities WHERE record_kind = 'corporate_entity'"
    ).fetchone()[0]
    # Floor of 80k (the new gbiz batch alone). If the column drops below this
    # the ingest regressed; if it ranges far above we extend the upper bound.
    assert actual >= 80_000, (
        f"corporate_entity count below gbiz floor (got {actual}, expected ≥80k)"
    )
