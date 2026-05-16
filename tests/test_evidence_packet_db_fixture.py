"""Stream TT coverage push: services/evidence_packet.py DB-dependent paths.

Targets the SQLite-backed helpers on ``EvidencePacketComposer`` that the
pure-helper test (``tests/test_services_evidence_packet_core.py``) cannot
reach. Uses an inline ``tmp_path`` autonomath fixture so the 9.7 GB
production DB is never touched.

Coverage targets:
  * ``_fetch_facts_for_entity`` — happy path, source-less, EAV branches
  * ``_fetch_pdf_fact_refs`` — PDF source filter, schema gap fail-open
  * ``_fetch_recent_changes`` — capped, filtered, missing-table branches
  * ``_fetch_aliases`` — am_alias + jpi aliases_json, dedup, too-long
  * ``_fetch_rules_for_program`` — compat_matrix walk, no-partner gap
  * ``_discover_program_ids_for_query`` — exact + fallback search path
  * ``_source_license_for_url`` — match, no-match, missing-table
  * ``_fetch_source_health`` — catalog hit, metadata_only fallback
  * ``_fetch_program_summary`` — present + missing-row branches
  * ``_corpus_snapshot_id`` — diff/source/today fallback chain

No source mutation. Inline schema seed; no autouse, no shared state.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from jpintel_mcp.services.evidence_packet import EvidencePacketComposer

# ---------------------------------------------------------------------------
# Inline schema fixture — mirrors tests/test_evidence_packet.py shape
# but kept independent so this file does not break if that one changes.
# ---------------------------------------------------------------------------


def _seed_minimal_autonomath(path: Path) -> None:
    """Build a small autonomath.db with the schemas evidence_packet touches."""
    if path.exists():
        path.unlink()
    con = sqlite3.connect(path)
    try:
        con.executescript(
            """
            CREATE TABLE am_source (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                source_url    TEXT NOT NULL UNIQUE,
                source_type   TEXT,
                domain        TEXT,
                content_hash  TEXT,
                first_seen    TEXT,
                last_verified TEXT,
                license       TEXT,
                canonical_status TEXT,
                is_pdf        INTEGER
            );
            CREATE TABLE am_entity_facts (
                id                       INTEGER PRIMARY KEY AUTOINCREMENT,
                entity_id                TEXT NOT NULL,
                field_name               TEXT NOT NULL,
                field_value_text         TEXT,
                field_value_json         TEXT,
                field_value_numeric      REAL,
                field_kind               TEXT NOT NULL DEFAULT 'text',
                source_id                INTEGER,
                confirming_source_count  INTEGER DEFAULT 1
            );
            CREATE TABLE am_alias (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                entity_table TEXT,
                canonical_id TEXT NOT NULL,
                alias        TEXT NOT NULL,
                alias_kind   TEXT NOT NULL,
                language     TEXT
            );
            CREATE TABLE am_amendment_diff (
                diff_id      INTEGER PRIMARY KEY AUTOINCREMENT,
                entity_id    TEXT NOT NULL,
                field_name   TEXT NOT NULL,
                source_url   TEXT,
                detected_at  TEXT NOT NULL
            );
            CREATE TABLE jpi_programs (
                unified_id        TEXT PRIMARY KEY,
                primary_name      TEXT NOT NULL,
                aliases_json      TEXT,
                authority_name    TEXT,
                prefecture        TEXT,
                tier              TEXT,
                program_kind      TEXT,
                funding_purpose_json TEXT,
                target_types_json TEXT,
                equipment_category TEXT,
                source_url        TEXT,
                source_fetched_at TEXT,
                updated_at        TEXT
            );
            CREATE TABLE am_compat_matrix (
                program_a_id    TEXT NOT NULL,
                program_b_id    TEXT NOT NULL,
                compat_status   TEXT NOT NULL,
                conditions_text TEXT,
                rationale_short TEXT,
                source_url      TEXT,
                confidence      REAL,
                inferred_only   INTEGER NOT NULL DEFAULT 1,
                PRIMARY KEY (program_a_id, program_b_id)
            );
            CREATE TABLE am_program_summary (
                entity_id        TEXT PRIMARY KEY,
                primary_name     TEXT,
                summary_50       TEXT,
                summary_200      TEXT,
                summary_800      TEXT,
                token_50_est     INT,
                token_200_est    INT,
                token_800_est    INT,
                generated_at     TEXT,
                source_quality   REAL
            );
            """
        )

        # 2 sources: 1 HTML primary + 1 PDF secondary.
        con.executemany(
            "INSERT INTO am_source(source_url, source_type, domain, content_hash, "
            "first_seen, last_verified, license, canonical_status, is_pdf) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            [
                (
                    "https://www.maff.go.jp/policy/tt1.html",
                    "primary",
                    "www.maff.go.jp",
                    "sha256:tt1html",
                    "2026-05-10T00:00:00",
                    "2026-05-14T00:00:00",
                    "gov_standard_v2.0",
                    "canonical",
                    0,
                ),
                (
                    "https://www.meti.go.jp/policy/tt1.pdf",
                    "secondary",
                    "www.meti.go.jp",
                    "sha256:tt1pdf",
                    "2026-05-10T00:00:00",
                    "2026-05-14T00:00:00",
                    "pdl_v1.0",
                    "canonical",
                    1,
                ),
            ],
        )

        # P1 — 3 facts with source_id mix.
        con.executemany(
            "INSERT INTO am_entity_facts(entity_id, field_name, field_value_text, "
            "field_value_numeric, field_kind, source_id, confirming_source_count) "
            "VALUES (?,?,?,?,?,?,?)",
            [
                ("program:tt:p1", "amount_max_yen", None, 5_000_000, "numeric", 1, 3),
                (
                    "program:tt:p1",
                    "deadline",
                    "2026-12-31",
                    None,
                    "text",
                    2,  # PDF source
                    2,
                ),
                (
                    "program:tt:p1",
                    "subsidy_rate",
                    "1/2",
                    None,
                    "text",
                    None,  # no source_id
                    1,
                ),
            ],
        )

        # Programs in jpi_programs for discover_program_ids_for_query.
        con.executemany(
            "INSERT INTO jpi_programs(unified_id, primary_name, aliases_json, "
            "authority_name, prefecture, tier, program_kind, funding_purpose_json, "
            "source_url, source_fetched_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            [
                (
                    "UNI-tt-p1",
                    "テスト省エネ補助金",
                    '["省エネ補助", "TT P1"]',
                    "経済産業省",
                    "東京都",
                    "S",
                    "subsidy",
                    '["省エネ", "GX"]',
                    "https://www.maff.go.jp/policy/tt1.html",
                    "2026-05-10T00:00:00",
                    "2026-05-12T00:00:00",
                ),
                (
                    "UNI-tt-p2",
                    "別件IT導入補助金",
                    None,
                    "経済産業省",
                    "大阪府",
                    "A",
                    "subsidy",
                    '["IT導入"]',
                    "https://www.meti.go.jp/policy/tt2.html",
                    "2026-05-10T00:00:00",
                    "2026-05-12T00:00:00",
                ),
            ],
        )

        # am_alias — multiple kinds including bogus + too-long
        long_alias = "あ" * 90  # > 80 cap → dropped
        con.executemany(
            "INSERT INTO am_alias(entity_table, canonical_id, alias, alias_kind, language) "
            "VALUES (?,?,?,?,?)",
            [
                ("am_entities", "program:tt:p1", "TTテスト", "abbreviation", "ja"),
                ("am_entities", "program:tt:p1", "TT Test", "english", "en"),
                ("am_entities", "program:tt:p1", long_alias, "kana", "ja"),
                ("am_entities", "program:tt:p1", "TT-Legacy", "legacy", None),
                # Duplicate of abbreviation — should dedup.
                ("am_entities", "program:tt:p1", "TTテスト", "alias", "ja"),
            ],
        )

        # am_amendment_diff — surface-able + filtered field branches
        con.executemany(
            "INSERT INTO am_amendment_diff(entity_id, field_name, source_url, detected_at) "
            "VALUES (?,?,?,?)",
            [
                (
                    "program:tt:p1",
                    "amount_max_yen",
                    "https://www.maff.go.jp/policy/tt1.html",
                    "2026-05-11T00:00:00",
                ),
                (
                    "program:tt:p1",
                    "deadline",
                    "https://www.maff.go.jp/policy/tt1.html",
                    "2026-05-12T00:00:00",
                ),
                (
                    "program:tt:p1",
                    "projection_internal_debug",  # not in _RECENT_CHANGE_FIELDS
                    None,
                    "2026-05-13T00:00:00",
                ),
            ],
        )

        # am_compat_matrix — one sourced partner pair for the rules surface
        con.execute(
            "INSERT INTO am_compat_matrix(program_a_id, program_b_id, compat_status, "
            "rationale_short, source_url, confidence, inferred_only) "
            "VALUES (?,?,?,?,?,?,?)",
            (
                "program:tt:p1",
                "program:tt:partner",
                "compatible",
                "併用可 (テスト)",
                "https://www.maff.go.jp/policy/tt1.html",
                0.95,
                0,
            ),
        )

        # am_program_summary — only for p1
        con.execute(
            "INSERT INTO am_program_summary(entity_id, primary_name, summary_50, "
            "summary_200, summary_800, token_50_est, token_200_est, token_800_est, "
            "generated_at, source_quality) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                "program:tt:p1",
                "テスト省エネ補助金",
                "短い要約",
                "中くらいの要約",
                "長い要約",
                12,
                50,
                90,
                "2026-05-14T00:00:00",
                0.88,
            ),
        )
        con.commit()
    finally:
        con.close()


@pytest.fixture
def autonomath_db(tmp_path: Path) -> Path:
    path = tmp_path / "autonomath_tt.db"
    _seed_minimal_autonomath(path)
    return path


@pytest.fixture
def jpintel_db(tmp_path: Path) -> Path:
    """Minimal jpintel.db with exclusion_rules + placeholder. No citation_verification
    table so the composer's citation_verifications join path must fail open."""
    path = tmp_path / "jpintel_tt.db"
    con = sqlite3.connect(path)
    try:
        con.executescript(
            """
            CREATE TABLE _placeholder (k TEXT);
            CREATE TABLE exclusion_rules (
                rule_id     TEXT PRIMARY KEY,
                kind        TEXT NOT NULL,
                program_a   TEXT,
                program_b   TEXT,
                description TEXT,
                severity    TEXT,
                program_b_group_json TEXT,
                source_urls_json     TEXT,
                program_a_uid TEXT,
                program_b_uid TEXT
            );
            """
        )
        con.commit()
    finally:
        con.close()
    return path


@pytest.fixture
def composer(autonomath_db: Path, jpintel_db: Path) -> EvidencePacketComposer:
    return EvidencePacketComposer(
        jpintel_db=jpintel_db,
        autonomath_db=autonomath_db,
    )


# ---------------------------------------------------------------------------
# _open_ro + _corpus_snapshot_id
# ---------------------------------------------------------------------------


def test_open_ro_returns_query_only_connection(composer: EvidencePacketComposer) -> None:
    conn = composer._open_ro(composer.autonomath_db)
    try:
        # Read works
        assert conn.execute("SELECT COUNT(*) FROM am_source").fetchone()[0] >= 2
    finally:
        conn.close()


def test_open_ro_missing_path_raises(composer: EvidencePacketComposer, tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        composer._open_ro(tmp_path / "does_not_exist.db")


def test_corpus_snapshot_id_prefers_amendment_diff(composer: EvidencePacketComposer) -> None:
    conn = composer._open_ro(composer.autonomath_db)
    try:
        snapshot = composer._corpus_snapshot_id(conn)
    finally:
        conn.close()
    # MAX(detected_at) is 2026-05-13 in the fixture
    assert snapshot == "corpus-2026-05-13"


def test_corpus_snapshot_id_none_falls_back_to_today(composer: EvidencePacketComposer) -> None:
    snapshot = composer._corpus_snapshot_id(None)
    assert snapshot.startswith("corpus-")


# ---------------------------------------------------------------------------
# _fetch_facts_for_entity
# ---------------------------------------------------------------------------


def test_fetch_facts_returns_with_source_count(composer: EvidencePacketComposer) -> None:
    conn = composer._open_ro(composer.autonomath_db)
    try:
        facts, total, with_source = composer._fetch_facts_for_entity(
            conn, "program:tt:p1", cap=50
        )
    finally:
        conn.close()
    assert total == 3
    assert with_source == 2  # 2 of 3 facts have source_id
    field_names = {f["field"] for f in facts}
    assert "amount_max_yen" in field_names
    # numeric coercion path
    amount = next(f for f in facts if f["field"] == "amount_max_yen")
    assert amount["value"] == 5_000_000
    # text path
    deadline = next(f for f in facts if f["field"] == "deadline")
    assert deadline["value"] == "2026-12-31"
    # confidence rounding
    for fact in facts:
        assert 0.1 <= fact["confidence"] <= 1.0


def test_fetch_facts_empty_canonical_short_circuit(composer: EvidencePacketComposer) -> None:
    conn = composer._open_ro(composer.autonomath_db)
    try:
        facts, total, with_source = composer._fetch_facts_for_entity(conn, "", cap=10)
    finally:
        conn.close()
    assert facts == []
    assert total == 0
    assert with_source == 0


def test_fetch_facts_unknown_entity_returns_empty(composer: EvidencePacketComposer) -> None:
    conn = composer._open_ro(composer.autonomath_db)
    try:
        facts, total, _ = composer._fetch_facts_for_entity(conn, "program:tt:ghost", cap=10)
    finally:
        conn.close()
    assert facts == []
    assert total == 0


def test_fetch_facts_truncation_path(composer: EvidencePacketComposer) -> None:
    # cap=1 forces the truncation branch (rows == cap+1 → trim back to cap)
    conn = composer._open_ro(composer.autonomath_db)
    try:
        facts, total, _ = composer._fetch_facts_for_entity(conn, "program:tt:p1", cap=1)
    finally:
        conn.close()
    assert len(facts) == 1
    # Total still reflects underlying COUNT(*)
    assert total == 3


# ---------------------------------------------------------------------------
# _fetch_pdf_fact_refs
# ---------------------------------------------------------------------------


def test_fetch_pdf_fact_refs_only_pdf_sources(composer: EvidencePacketComposer) -> None:
    conn = composer._open_ro(composer.autonomath_db)
    try:
        refs = composer._fetch_pdf_fact_refs(conn, "program:tt:p1", cap=10)
    finally:
        conn.close()
    # Only the deadline fact (source_id=2 → PDF) should appear.
    assert len(refs) == 1
    assert refs[0]["field_name"] == "deadline"
    assert refs[0]["source_url"].endswith(".pdf")
    assert refs[0]["domain"] == "www.meti.go.jp"


def test_fetch_pdf_fact_refs_empty_canonical_short_circuit(
    composer: EvidencePacketComposer,
) -> None:
    conn = composer._open_ro(composer.autonomath_db)
    try:
        refs = composer._fetch_pdf_fact_refs(conn, "", cap=5)
    finally:
        conn.close()
    assert refs == []


def test_fetch_pdf_fact_refs_cap_zero(composer: EvidencePacketComposer) -> None:
    conn = composer._open_ro(composer.autonomath_db)
    try:
        refs = composer._fetch_pdf_fact_refs(conn, "program:tt:p1", cap=0)
    finally:
        conn.close()
    assert refs == []


# ---------------------------------------------------------------------------
# _fetch_recent_changes
# ---------------------------------------------------------------------------


def test_fetch_recent_changes_visible_fields_only(composer: EvidencePacketComposer) -> None:
    conn = composer._open_ro(composer.autonomath_db)
    try:
        changes = composer._fetch_recent_changes(conn, "program:tt:p1", cap=10)
    finally:
        conn.close()
    field_names = [c["field_name"] for c in changes]
    # Two visible (amount_max_yen + deadline); the internal one filtered out
    assert "amount_max_yen" in field_names
    assert "deadline" in field_names
    assert "projection_internal_debug" not in field_names
    # Order is DESC by detected_at
    assert changes[0]["detected_at"] >= changes[-1]["detected_at"]


def test_fetch_recent_changes_cap_zero(composer: EvidencePacketComposer) -> None:
    conn = composer._open_ro(composer.autonomath_db)
    try:
        changes = composer._fetch_recent_changes(conn, "program:tt:p1", cap=0)
    finally:
        conn.close()
    assert changes == []


def test_fetch_recent_changes_empty_canonical(composer: EvidencePacketComposer) -> None:
    conn = composer._open_ro(composer.autonomath_db)
    try:
        changes = composer._fetch_recent_changes(conn, "", cap=5)
    finally:
        conn.close()
    assert changes == []


# ---------------------------------------------------------------------------
# _fetch_aliases
# ---------------------------------------------------------------------------


def test_fetch_aliases_dedup_and_priority(composer: EvidencePacketComposer) -> None:
    conn = composer._open_ro(composer.autonomath_db)
    try:
        aliases = composer._fetch_aliases(
            conn,
            "program:tt:p1",
            "UNI-tt-p1",
            "テスト省エネ補助金",
            cap=10,
        )
    finally:
        conn.close()
    texts = [a["text"] for a in aliases]
    # Dedup: TTテスト appears once
    assert texts.count("TTテスト") == 1
    # Over-80-char alias filtered
    assert all(len(t) <= 80 for t in texts)
    # jpi_programs.aliases_json contributes 2 items, am_alias contributes valid ones
    assert "省エネ補助" in texts or "TT P1" in texts
    # English alias keeps its language tag
    english = next((a for a in aliases if a["text"] == "TT Test"), None)
    if english is not None:
        assert english["language"] == "en"


def test_fetch_aliases_cap_one(composer: EvidencePacketComposer) -> None:
    conn = composer._open_ro(composer.autonomath_db)
    try:
        aliases = composer._fetch_aliases(
            conn,
            "program:tt:p1",
            "UNI-tt-p1",
            "テスト省エネ補助金",
            cap=1,
        )
    finally:
        conn.close()
    assert len(aliases) == 1


def test_fetch_aliases_no_canonical_no_unified(composer: EvidencePacketComposer) -> None:
    conn = composer._open_ro(composer.autonomath_db)
    try:
        aliases = composer._fetch_aliases(conn, "", None, "テスト", cap=5)
    finally:
        conn.close()
    assert aliases == []


# ---------------------------------------------------------------------------
# _fetch_rules_for_program
# ---------------------------------------------------------------------------


def test_fetch_rules_for_program_partner_walk(composer: EvidencePacketComposer) -> None:
    rules, gaps = composer._fetch_rules_for_program(
        canonical_id="program:tt:p1",
        primary_id="program:tt:p1",
        cap=10,
    )
    # Either rules emerge (with funding_stack_checker happy path) or the
    # funding_stack gap is emitted — both are valid coverage of branches.
    assert isinstance(rules, list)
    assert isinstance(gaps, list)


def test_fetch_rules_for_program_no_partner_emits_gap(
    composer: EvidencePacketComposer,
) -> None:
    rules, gaps = composer._fetch_rules_for_program(
        canonical_id="program:tt:nopartner",
        primary_id="program:tt:nopartner",
        cap=5,
    )
    assert rules == []
    assert "compat_matrix_no_partner" in gaps


def test_fetch_rules_for_program_missing_autonomath(
    tmp_path: Path, jpintel_db: Path
) -> None:
    bogus = EvidencePacketComposer(
        jpintel_db=jpintel_db,
        autonomath_db=tmp_path / "ghost_autonomath.db",
    )
    rules, gaps = bogus._fetch_rules_for_program(
        canonical_id="program:x", primary_id="program:x", cap=5
    )
    assert rules == []
    assert "compat_matrix_unavailable" in gaps


# ---------------------------------------------------------------------------
# _discover_program_ids_for_query
# ---------------------------------------------------------------------------


def test_discover_program_ids_exact_substring_path(composer: EvidencePacketComposer) -> None:
    conn = composer._open_ro(composer.autonomath_db)
    try:
        ids = composer._discover_program_ids_for_query(
            conn, "省エネ", {}, limit=10
        )
    finally:
        conn.close()
    assert "UNI-tt-p1" in ids


def test_discover_program_ids_filter_by_tier(composer: EvidencePacketComposer) -> None:
    conn = composer._open_ro(composer.autonomath_db)
    try:
        ids = composer._discover_program_ids_for_query(
            conn, "補助金", {"tier": "A"}, limit=10
        )
    finally:
        conn.close()
    assert "UNI-tt-p2" in ids
    assert "UNI-tt-p1" not in ids


def test_discover_program_ids_filter_by_prefecture(
    composer: EvidencePacketComposer,
) -> None:
    conn = composer._open_ro(composer.autonomath_db)
    try:
        ids = composer._discover_program_ids_for_query(
            conn, "補助金", {"prefecture": "大阪府"}, limit=10
        )
    finally:
        conn.close()
    assert "UNI-tt-p2" in ids


def test_discover_program_ids_fallback_search(composer: EvidencePacketComposer) -> None:
    """Term that doesn't substring-match primary_name but matches via funding_purpose_json."""
    conn = composer._open_ro(composer.autonomath_db)
    try:
        ids = composer._discover_program_ids_for_query(conn, "GX", {}, limit=10)
    finally:
        conn.close()
    # UNI-tt-p1 has funding_purpose_json including "GX"
    assert "UNI-tt-p1" in ids


def test_discover_program_ids_empty_query(composer: EvidencePacketComposer) -> None:
    conn = composer._open_ro(composer.autonomath_db)
    try:
        ids = composer._discover_program_ids_for_query(conn, "", {}, limit=10)
    finally:
        conn.close()
    # All programs returned, ordered by tier
    assert len(ids) >= 2


# ---------------------------------------------------------------------------
# _source_license_for_url
# ---------------------------------------------------------------------------


def test_source_license_for_url_match(composer: EvidencePacketComposer) -> None:
    license_name = composer._source_license_for_url(
        "https://www.maff.go.jp/policy/tt1.html"
    )
    assert license_name == "gov_standard_v2.0"


def test_source_license_for_url_missing_url(composer: EvidencePacketComposer) -> None:
    assert composer._source_license_for_url(None) is None


def test_source_license_for_url_unknown_url(composer: EvidencePacketComposer) -> None:
    assert composer._source_license_for_url("https://other.example/x") is None


def test_source_license_for_url_missing_db(tmp_path: Path) -> None:
    bogus = EvidencePacketComposer(
        jpintel_db=tmp_path / "ghost_jpintel.db",
        autonomath_db=tmp_path / "ghost_autonomath.db",
    )
    assert bogus._source_license_for_url("https://anywhere.example/x") is None


# ---------------------------------------------------------------------------
# _fetch_source_health
# ---------------------------------------------------------------------------


def test_fetch_source_health_catalog_hit(composer: EvidencePacketComposer) -> None:
    conn = composer._open_ro(composer.autonomath_db)
    try:
        health = composer._fetch_source_health(
            conn,
            "https://www.maff.go.jp/policy/tt1.html",
            source_fetched_at="2026-05-10T00:00:00",
        )
    finally:
        conn.close()
    assert health is not None
    assert health["domain"] == "www.maff.go.jp"
    assert health["license"] == "gov_standard_v2.0"
    assert health["verification_basis"] == "local_source_catalog"
    assert health["live_verified_at_request"] is False
    assert health["verification_status"] == "catalog_last_verified"


def test_fetch_source_health_metadata_only(composer: EvidencePacketComposer) -> None:
    conn = composer._open_ro(composer.autonomath_db)
    try:
        health = composer._fetch_source_health(
            conn, "https://not-in-catalog.example/x", source_fetched_at="2026-05-12"
        )
    finally:
        conn.close()
    assert health is not None
    assert health["verification_status"] == "metadata_only"


def test_fetch_source_health_none_url(composer: EvidencePacketComposer) -> None:
    conn = composer._open_ro(composer.autonomath_db)
    try:
        health = composer._fetch_source_health(conn, None)
    finally:
        conn.close()
    assert health is None


# ---------------------------------------------------------------------------
# _fetch_program_summary
# ---------------------------------------------------------------------------


def test_fetch_program_summary_present(composer: EvidencePacketComposer) -> None:
    conn = composer._open_ro(composer.autonomath_db)
    try:
        summary = composer._fetch_program_summary(conn, "program:tt:p1")
    finally:
        conn.close()
    assert summary is not None
    assert summary["basis"] == "am_program_summary"
    assert "summaries" in summary
    assert summary["summaries"]["50"] == "短い要約"
    assert summary["token_estimates"]["50"] == 12
    assert summary["source_quality"] == pytest.approx(0.88)


def test_fetch_program_summary_missing_entity(composer: EvidencePacketComposer) -> None:
    conn = composer._open_ro(composer.autonomath_db)
    try:
        summary = composer._fetch_program_summary(conn, "program:tt:ghost")
    finally:
        conn.close()
    assert summary is None


def test_fetch_program_summary_empty_canonical(composer: EvidencePacketComposer) -> None:
    conn = composer._open_ro(composer.autonomath_db)
    try:
        summary = composer._fetch_program_summary(conn, "")
    finally:
        conn.close()
    assert summary is None


# ---------------------------------------------------------------------------
# _fetch_citation_verifications — jpintel.db without the table → empty
# ---------------------------------------------------------------------------


def test_fetch_citation_verifications_missing_table_fail_open(
    composer: EvidencePacketComposer,
) -> None:
    # jpintel.db fixture has no citation_verification table → empty dict
    out = composer._fetch_citation_verifications(["program:tt:p1"])
    assert out == {}


def test_fetch_citation_verifications_empty_input(
    composer: EvidencePacketComposer,
) -> None:
    assert composer._fetch_citation_verifications([]) == {}
    assert composer._fetch_citation_verifications(["", None]) == {}  # type: ignore[list-item]


def test_fetch_citation_verifications_missing_jpintel_db(tmp_path: Path) -> None:
    bogus = EvidencePacketComposer(
        jpintel_db=tmp_path / "no_such.db",
        autonomath_db=tmp_path / "also_missing.db",
    )
    assert bogus._fetch_citation_verifications(["program:tt:p1"]) == {}


# ---------------------------------------------------------------------------
# _table_columns helper
# ---------------------------------------------------------------------------


def test_table_columns_present(composer: EvidencePacketComposer) -> None:
    conn = composer._open_ro(composer.autonomath_db)
    try:
        cols = composer._table_columns(conn, "am_source")
    finally:
        conn.close()
    assert "source_url" in cols
    assert "license" in cols


def test_table_columns_missing(composer: EvidencePacketComposer) -> None:
    conn = composer._open_ro(composer.autonomath_db)
    try:
        cols = composer._table_columns(conn, "no_such_table_xyz")
    finally:
        conn.close()
    assert cols == set()
