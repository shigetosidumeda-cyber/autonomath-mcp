"""Tests for `evidence_value.citations[]` + 4 packet profiles (§4.3 deliverable).

Plan reference: ``docs/_internal/jpcite_ai_discovery_paid_adoption_plan_2026-05-04.md`` §4.3
Migration: ``scripts/migrations/126_citation_verification.sql``

Fixture posture
---------------

The composer reads autonomath.db (corpus state, read-only) AND jpintel.db
(request-side state, including ``citation_verification`` after migration
126). We build BOTH fixture DBs in tmp_path so each verification status
(``verified`` / ``inferred`` / ``unknown`` / ``stale``) is exercised
end-to-end against the real composer.

We do NOT mock the DB — the test fixtures own the schema so a future
schema drift is caught immediately rather than silently passed.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path  # noqa: TC003 — runtime fixture annotation
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator


# ---------------------------------------------------------------------------
# Fixture autonomath.db builder (4 programs, distinct source URLs).
# ---------------------------------------------------------------------------


def _build_fixture_autonomath_db(path: Path) -> None:
    """Build a small autonomath.db with one program per verification status.

    Programs (canonical_id → primary source URL):
      * ``program:cv:verified``  — verified citation in jpintel.db
      * ``program:cv:inferred``  — inferred citation in jpintel.db
      * ``program:cv:stale``     — stale citation in jpintel.db
      * ``program:cv:unknown``   — NO row in jpintel.db (default)
    """
    if path.exists():
        path.unlink()
    con = sqlite3.connect(path)
    try:
        con.executescript(
            """
            CREATE TABLE am_source (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                source_url   TEXT NOT NULL UNIQUE,
                source_type  TEXT NOT NULL DEFAULT 'primary',
                domain       TEXT,
                content_hash TEXT,
                first_seen   TEXT NOT NULL DEFAULT (datetime('now')),
                last_verified TEXT,
                license      TEXT
            );
            CREATE TABLE am_entities (
                canonical_id  TEXT PRIMARY KEY,
                primary_name  TEXT NOT NULL,
                record_kind   TEXT,
                source_url    TEXT,
                fetched_at    TEXT,
                confidence    REAL
            );
            CREATE TABLE am_entity_facts (
                id                       INTEGER PRIMARY KEY AUTOINCREMENT,
                entity_id                TEXT NOT NULL,
                field_name               TEXT NOT NULL,
                field_value_text         TEXT,
                field_value_json         TEXT,
                field_value_numeric      REAL,
                field_kind               TEXT NOT NULL DEFAULT 'text',
                source_id                INTEGER REFERENCES am_source(id),
                confirming_source_count  INTEGER DEFAULT 1,
                created_at               TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE TABLE am_entity_source (
                entity_id    TEXT NOT NULL,
                source_id    INTEGER NOT NULL,
                role         TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (entity_id, source_id, role)
            );
            CREATE TABLE jpi_programs (
                unified_id        TEXT PRIMARY KEY,
                primary_name      TEXT NOT NULL,
                aliases_json      TEXT,
                authority_name    TEXT,
                prefecture        TEXT,
                tier              TEXT,
                source_url        TEXT,
                source_fetched_at TEXT,
                updated_at        TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE TABLE am_alias (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                entity_table TEXT,
                canonical_id TEXT NOT NULL,
                alias        TEXT NOT NULL,
                alias_kind   TEXT NOT NULL,
                created_at   TEXT NOT NULL DEFAULT (datetime('now')),
                language     TEXT NOT NULL DEFAULT 'ja'
            );
            CREATE TABLE entity_id_map (
                jpi_unified_id   TEXT NOT NULL,
                am_canonical_id  TEXT NOT NULL,
                match_method     TEXT NOT NULL,
                confidence       REAL NOT NULL,
                PRIMARY KEY (jpi_unified_id, am_canonical_id)
            );
            CREATE TABLE am_compat_matrix (
                program_a_id      TEXT NOT NULL,
                program_b_id      TEXT NOT NULL,
                compat_status     TEXT NOT NULL,
                conditions_text   TEXT,
                rationale_short   TEXT,
                source_url        TEXT,
                confidence        REAL,
                inferred_only     INTEGER NOT NULL DEFAULT 1,
                PRIMARY KEY (program_a_id, program_b_id)
            );
            CREATE TABLE am_amendment_diff (
                diff_id      INTEGER PRIMARY KEY AUTOINCREMENT,
                entity_id    TEXT NOT NULL,
                field_name   TEXT NOT NULL,
                prev_value   TEXT,
                new_value    TEXT,
                source_url   TEXT,
                detected_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        # Sources — one URL per program.
        sources = [
            (
                "https://www.maff.go.jp/cv-verified.html",
                "verified-domain.go.jp",
                "gov_standard_v2.0",
            ),
            (
                "https://www.meti.go.jp/cv-inferred.html",
                "inferred-domain.go.jp",
                "gov_standard_v2.0",
            ),
            ("https://www.cao.go.jp/cv-stale.html", "stale-domain.go.jp", "pdl_v1.0"),
            (
                "https://www.example.go.jp/cv-unknown.html",
                "unknown-domain.go.jp",
                "gov_standard_v2.0",
            ),
        ]
        con.executemany(
            "INSERT INTO am_source(source_url, domain, license) VALUES (?,?,?)",
            sources,
        )
        # 4 programs.
        progs = [
            ("program:cv:verified", "CV テスト 検証済", sources[0][0]),
            ("program:cv:inferred", "CV テスト 推測", sources[1][0]),
            ("program:cv:stale", "CV テスト 失効", sources[2][0]),
            ("program:cv:unknown", "CV テスト 未検証", sources[3][0]),
        ]
        con.executemany(
            "INSERT INTO am_entities("
            "canonical_id, primary_name, record_kind, source_url, "
            "fetched_at, confidence) VALUES (?,?,?,?,?,?)",
            [(p[0], p[1], "program", p[2], "2026-05-01T00:00:00", 1.0) for p in progs],
        )
        # 1 fact per program with source_id pointing to the same source.
        for sidx, (canonical_id, _name, _surl) in enumerate(progs, start=1):
            con.execute(
                "INSERT INTO am_entity_facts("
                "entity_id, field_name, field_value_text, field_kind, "
                "source_id, confirming_source_count) VALUES (?,?,?,?,?,?)",
                (canonical_id, "amount_max_yen", "1000000", "text", sidx, 2),
            )
        # entity_id_map for UNI- resolution.
        con.executemany(
            "INSERT INTO entity_id_map(jpi_unified_id, am_canonical_id, "
            "match_method, confidence) VALUES (?,?,?,?)",
            [
                ("UNI-cv-verified", "program:cv:verified", "exact_name", 1.0),
                ("UNI-cv-inferred", "program:cv:inferred", "exact_name", 1.0),
                ("UNI-cv-stale", "program:cv:stale", "exact_name", 1.0),
                ("UNI-cv-unknown", "program:cv:unknown", "exact_name", 1.0),
            ],
        )
        # jpi_programs entries.
        con.executemany(
            "INSERT INTO jpi_programs(unified_id, primary_name, "
            "authority_name, prefecture, tier, source_url, "
            "source_fetched_at) VALUES (?,?,?,?,?,?,?)",
            [
                (
                    "UNI-cv-verified",
                    "CV テスト 検証済",
                    "農水省",
                    "東京都",
                    "S",
                    sources[0][0],
                    "2026-05-01T00:00:00",
                ),
                (
                    "UNI-cv-inferred",
                    "CV テスト 推測",
                    "経産省",
                    "大阪府",
                    "A",
                    sources[1][0],
                    "2026-05-01T00:00:00",
                ),
                (
                    "UNI-cv-stale",
                    "CV テスト 失効",
                    "内閣府",
                    "京都府",
                    "A",
                    sources[2][0],
                    "2026-05-01T00:00:00",
                ),
                (
                    "UNI-cv-unknown",
                    "CV テスト 未検証",
                    "総務省",
                    "福岡県",
                    "B",
                    sources[3][0],
                    "2026-05-01T00:00:00",
                ),
            ],
        )
        # Add a recent_change to the verified program so changes_only profile
        # has something to keep.
        con.execute(
            "INSERT INTO am_amendment_diff("
            "entity_id, field_name, prev_value, new_value, source_url, detected_at) "
            "VALUES (?,?,?,?,?,?)",
            (
                "program:cv:verified",
                "amount_max_yen",
                "500000",
                "1000000",
                sources[0][0],
                "2026-05-02T00:00:00",
            ),
        )
        # Same entity, but intentionally no citation_verification row. The
        # verified_only profile must not let this change source reintroduce an
        # unknown citation after profile projection.
        con.execute(
            "INSERT INTO am_amendment_diff("
            "entity_id, field_name, prev_value, new_value, source_url, detected_at) "
            "VALUES (?,?,?,?,?,?)",
            (
                "program:cv:verified",
                "deadline",
                "2026-05-01",
                "2026-05-15",
                "https://www.maff.go.jp/cv-unverified-change.html",
                "2026-05-03T00:00:00",
            ),
        )
        con.commit()
    finally:
        con.close()


# ---------------------------------------------------------------------------
# Fixture jpintel.db builder — citation_verification table seeded with 3 rows.
# ---------------------------------------------------------------------------


def _build_fixture_jpintel_db(path: Path) -> None:
    """Build a jpintel.db with citation_verification rows for 3 statuses.

    The fourth program (``program:cv:unknown``) intentionally has NO row,
    so the composer falls back to the default ``'unknown'`` status.
    """
    if path.exists():
        path.unlink()
    con = sqlite3.connect(path)
    try:
        con.executescript(
            """
            CREATE TABLE citation_verification (
                id                    INTEGER PRIMARY KEY AUTOINCREMENT,
                entity_id             TEXT NOT NULL,
                source_url            TEXT NOT NULL,
                verification_status   TEXT NOT NULL CHECK (
                    verification_status IN ('verified', 'inferred', 'unknown', 'stale')
                ),
                matched_form          TEXT,
                source_checksum       TEXT,
                verified_at           TIMESTAMP NOT NULL,
                verification_basis    TEXT
            );
            CREATE INDEX idx_citation_verification_entity_source_verified_at
                ON citation_verification(entity_id, source_url, verified_at DESC, id DESC);
            """
        )
        # Seed 3 rows — verified / inferred / stale.
        rows = [
            (
                "program:cv:verified",
                "https://www.maff.go.jp/cv-verified.html",
                "verified",
                "1,000,000円",
                "sha256:verified-checksum",
                "2026-05-03T10:00:00",
                "excerpt_substring",
            ),
            (
                "program:cv:inferred",
                "https://www.meti.go.jp/cv-inferred.html",
                "inferred",
                None,
                "sha256:inferred-checksum",
                "2026-05-03T11:00:00",
                "excerpt_no_match",
            ),
            (
                "program:cv:stale",
                "https://www.cao.go.jp/cv-stale.html",
                "stale",
                None,
                "sha256:stale-checksum",
                "2026-05-03T12:00:00",
                "stale_checksum_drift",
            ),
        ]
        con.executemany(
            "INSERT INTO citation_verification("
            "entity_id, source_url, verification_status, matched_form, "
            "source_checksum, verified_at, verification_basis) "
            "VALUES (?,?,?,?,?,?,?)",
            rows,
        )
        con.commit()
    finally:
        con.close()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def fixture_db(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Build the miniature autonomath.db once per test module."""
    p = tmp_path_factory.mktemp("evp_citation_status") / "autonomath.db"
    _build_fixture_autonomath_db(p)
    return p


@pytest.fixture(scope="module")
def fixture_jpintel(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Build the miniature jpintel.db with citation_verification rows."""
    p = tmp_path_factory.mktemp("evp_citation_status_jpi") / "jpintel.db"
    _build_fixture_jpintel_db(p)
    return p


@pytest.fixture(autouse=True)
def _override_paths(
    fixture_db: Path,
    fixture_jpintel: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[None]:
    """Point composer at fixture DBs, reset caches."""
    monkeypatch.setenv("AUTONOMATH_DB_PATH", str(fixture_db))
    monkeypatch.setenv("JPINTEL_DB_PATH", str(fixture_jpintel))
    from jpintel_mcp.config import settings

    monkeypatch.setattr(settings, "autonomath_db_path", fixture_db)
    monkeypatch.setattr(settings, "db_path", fixture_jpintel)

    if "jpintel_mcp.services.evidence_packet" in sys.modules:
        from jpintel_mcp.services import evidence_packet as _evp

        _evp._reset_cache_for_tests()
    if "jpintel_mcp.api.evidence" in sys.modules:
        from jpintel_mcp.api import evidence as _evp_api

        _evp_api.reset_composer()
    yield


# ---------------------------------------------------------------------------
# Composer tests — citations[] surface
# ---------------------------------------------------------------------------


def _get_composer(jpintel_db: Path, autonomath_db: Path):
    from jpintel_mcp.services.evidence_packet import EvidencePacketComposer

    return EvidencePacketComposer(jpintel_db=jpintel_db, autonomath_db=autonomath_db)


def _find_citation(env: dict, source_url: str) -> dict | None:
    cits = env.get("evidence_value", {}).get("citations") or []
    for c in cits:
        if c.get("source_url") == source_url:
            return c
    return None


def test_citation_status_verified_case(fixture_db: Path, fixture_jpintel: Path) -> None:
    """A program whose primary URL has a verified row gets verification_status='verified'."""
    composer = _get_composer(fixture_jpintel, fixture_db)
    env = composer.compose_for_program("UNI-cv-verified")
    assert env is not None
    cit = _find_citation(env, "https://www.maff.go.jp/cv-verified.html")
    assert cit is not None, (
        f"missing citation row, citations={env['evidence_value'].get('citations')}"
    )
    assert cit["verification_status"] == "verified"
    assert cit["matched_form"] == "1,000,000円"
    assert cit["source_checksum"] == "sha256:verified-checksum"
    assert cit["verified_at"] == "2026-05-03T10:00:00"
    assert cit["verification_basis"] == "excerpt_substring"
    # Aggregate counters.
    ev = env["evidence_value"]
    assert ev["citation_verified_count"] >= 1
    assert ev["citation_count"] >= 1


def test_citation_status_inferred_case(fixture_db: Path, fixture_jpintel: Path) -> None:
    """A program with an inferred row reports verification_status='inferred'."""
    composer = _get_composer(fixture_jpintel, fixture_db)
    env = composer.compose_for_program("UNI-cv-inferred")
    assert env is not None
    cit = _find_citation(env, "https://www.meti.go.jp/cv-inferred.html")
    assert cit is not None
    assert cit["verification_status"] == "inferred"
    assert cit["matched_form"] is None
    assert cit["source_checksum"] == "sha256:inferred-checksum"
    assert cit["verified_at"] == "2026-05-03T11:00:00"
    assert cit["verification_basis"] == "excerpt_no_match"
    assert env["evidence_value"]["citation_inferred_count"] >= 1


def test_citation_status_stale_case(fixture_db: Path, fixture_jpintel: Path) -> None:
    """A program with a stale row reports verification_status='stale'."""
    composer = _get_composer(fixture_jpintel, fixture_db)
    env = composer.compose_for_program("UNI-cv-stale")
    assert env is not None
    cit = _find_citation(env, "https://www.cao.go.jp/cv-stale.html")
    assert cit is not None
    assert cit["verification_status"] == "stale"
    assert cit["source_checksum"] == "sha256:stale-checksum"
    assert cit["verified_at"] == "2026-05-03T12:00:00"
    assert cit["verification_basis"] == "stale_checksum_drift"
    assert env["evidence_value"]["citation_stale_count"] >= 1


def test_citation_status_unknown_default_when_no_join(
    fixture_db: Path, fixture_jpintel: Path
) -> None:
    """A program with NO citation_verification row defaults to 'unknown'."""
    composer = _get_composer(fixture_jpintel, fixture_db)
    env = composer.compose_for_program("UNI-cv-unknown")
    assert env is not None
    cit = _find_citation(env, "https://www.example.go.jp/cv-unknown.html")
    assert cit is not None
    assert cit["verification_status"] == "unknown"
    # Default-row fields must all be None — never invent verdict data.
    assert cit["matched_form"] is None
    assert cit["source_checksum"] is None
    assert cit["verified_at"] is None
    assert cit["verification_basis"] is None
    assert env["evidence_value"]["citation_unknown_count"] >= 1


def test_citations_block_is_always_present(fixture_db: Path, fixture_jpintel: Path) -> None:
    """Even when no jpintel.db join hits, evidence_value.citations[] is a list."""
    composer = _get_composer(fixture_jpintel, fixture_db)
    env = composer.compose_for_program("UNI-cv-unknown")
    assert env is not None
    cits = env["evidence_value"]["citations"]
    assert isinstance(cits, list)
    assert all(
        c["verification_status"] in {"verified", "inferred", "unknown", "stale"} for c in cits
    )


# ---------------------------------------------------------------------------
# Profile projection tests (full / brief / verified_only / changes_only).
# ---------------------------------------------------------------------------


def test_profile_full_is_default_and_keeps_all_blocks(
    fixture_db: Path, fixture_jpintel: Path
) -> None:
    """`profile='full'` (default) leaves every block intact."""
    composer = _get_composer(fixture_jpintel, fixture_db)
    env = composer.compose_for_program("UNI-cv-verified", profile="full")
    assert env is not None
    assert env.get("packet_profile") == "full"
    rec = env["records"][0]
    # facts retained at full.
    assert "facts" in rec and len(rec["facts"]) >= 1
    # citations[] still exposed.
    assert env["evidence_value"]["citation_count"] >= 1


def test_profile_brief_drops_facts_rules_aliases(fixture_db: Path, fixture_jpintel: Path) -> None:
    """`profile='brief'` drops facts/rules/precomputed/aliases on every record."""
    composer = _get_composer(fixture_jpintel, fixture_db)
    env = composer.compose_for_program("UNI-cv-verified", profile="brief")
    assert env is not None
    assert env["packet_profile"] == "brief"
    rec = env["records"][0]
    # facts, rules, precomputed must all be dropped.
    assert "facts" not in rec
    assert "rules" not in rec
    assert "precomputed" not in rec
    assert "aliases" not in rec
    assert "pdf_fact_refs" not in rec
    assert "fact_provenance_coverage_pct" not in rec
    # but the citations[] block survives.
    assert env["evidence_value"]["citation_count"] >= 1


def test_profile_verified_only_filters_records(fixture_db: Path, fixture_jpintel: Path) -> None:
    """`profile='verified_only'` keeps only verified-citation records.

    The query packet pulls all 4 programs; only `program:cv:verified` has
    a verified citation, so the verified_only projection drops the other 3.
    """
    composer = _get_composer(fixture_jpintel, fixture_db)
    env = composer.compose_for_query("CV テスト", limit=10, profile="verified_only")
    assert env is not None
    assert env["packet_profile"] == "verified_only"
    # The verified program's source_url must appear; inferred/stale/unknown drop.
    surls = {rec.get("source_url") for rec in env["records"]}
    assert "https://www.maff.go.jp/cv-verified.html" in surls
    # Inferred / stale / unknown source URLs should NOT survive.
    forbidden = {
        "https://www.meti.go.jp/cv-inferred.html",
        "https://www.cao.go.jp/cv-stale.html",
        "https://www.example.go.jp/cv-unknown.html",
    }
    assert not (surls & forbidden)
    ev = env["evidence_value"]
    assert ev["records_returned"] == len(env["records"])
    assert ev["citation_count"] == ev["citation_verified_count"]
    assert all(c["verification_status"] == "verified" for c in ev["citations"])
    assert "https://www.maff.go.jp/cv-unverified-change.html" not in {
        c["source_url"] for c in ev["citations"]
    }
    assert all(
        chg["source_url"] != "https://www.maff.go.jp/cv-unverified-change.html"
        for rec in env["records"]
        for chg in rec.get("recent_changes", [])
    )


def test_rest_license_gate_preserves_verified_citation_status(
    fixture_db: Path, fixture_jpintel: Path
) -> None:
    """REST/MCP license gate must not rebuild verified citations as unknown."""
    from jpintel_mcp.api.evidence import _gate_evidence_envelope

    composer = _get_composer(fixture_jpintel, fixture_db)
    env = composer.compose_for_program("UNI-cv-verified")
    assert env is not None
    gated, _summary = _gate_evidence_envelope(env)
    cit = _find_citation(gated, "https://www.maff.go.jp/cv-verified.html")
    assert cit is not None
    assert cit["verification_status"] == "verified"


def test_query_profile_does_not_mutate_cached_single_subject_full(
    fixture_db: Path, fixture_jpintel: Path
) -> None:
    """Query profiles must not strip blocks from a cached full subject packet."""
    composer = _get_composer(fixture_jpintel, fixture_db)
    full_before = composer.compose_for_program("UNI-cv-verified", profile="full")
    assert full_before is not None
    assert "facts" in full_before["records"][0]

    brief = composer.compose_for_query("CV テスト", limit=1, profile="brief")
    assert brief is not None
    assert "facts" not in brief["records"][0]

    full_after = composer.compose_for_program("UNI-cv-verified", profile="full")
    assert full_after is not None
    assert "facts" in full_after["records"][0]


def test_profile_changes_only_keeps_only_records_with_recent_changes(
    fixture_db: Path, fixture_jpintel: Path
) -> None:
    """`profile='changes_only'` drops records with no recent_changes block."""
    composer = _get_composer(fixture_jpintel, fixture_db)
    env = composer.compose_for_query("CV テスト", limit=10, profile="changes_only")
    assert env is not None
    assert env["packet_profile"] == "changes_only"
    # Only program:cv:verified seeded a recent_change row in the fixture.
    surls = {rec.get("source_url") for rec in env["records"]}
    assert "https://www.maff.go.jp/cv-verified.html" in surls
    # Records that DO survive should NOT carry facts/rules/precomputed.
    for rec in env["records"]:
        assert "facts" not in rec
        assert "rules" not in rec
        assert "precomputed" not in rec
        # but recent_changes must be present (that's what made them survive).
        assert rec.get("recent_changes")


def test_unknown_profile_falls_back_to_full(fixture_db: Path, fixture_jpintel: Path) -> None:
    """Unrecognised `profile` values fall through to full (forward-compat)."""
    composer = _get_composer(fixture_jpintel, fixture_db)
    env = composer.compose_for_program("UNI-cv-verified", profile="future_value")
    assert env is not None
    # Forward-compat: an unknown profile is recorded as 'full' in the envelope.
    assert env["packet_profile"] == "full"
    rec = env["records"][0]
    assert "facts" in rec  # still full fidelity
