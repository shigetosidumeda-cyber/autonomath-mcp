"""Tests for the Evidence Packet composer + REST + MCP surfaces.

Plan reference: ``docs/_internal/llm_resilient_business_plan_2026-04-30.md`` §6.

Fixture posture
---------------

The composer reads exclusively from autonomath.db (read-only). We build
a miniature autonomath.db inside the test's tmp_path with three programs:

  * ``UNI-evp-p1`` — 4 facts each carrying a populated source_id
    (full per-fact provenance, plus partner pair → 1 rule entry).
  * ``UNI-evp-p2`` — sparse signal (1 fact, no source_id).
  * ``UNI-evp-pmissing`` — referenced in the cache miss / 404 test.

All assertions exercise the public composer entry points (the REST
endpoint, the MCP tool, and the underlying class). We do NOT mock the
DB — we build a real-shaped one.
"""

from __future__ import annotations

import contextlib
import sqlite3
import sys
from pathlib import Path  # noqa: TC003 — runtime fixture annotation
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator

    from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Fixture autonomath.db builder
# ---------------------------------------------------------------------------


_FIELDS = ["amount_max_yen", "amount_min_yen", "deadline", "subsidy_rate"]


def _build_fixture_autonomath_db(path: Path) -> None:
    """Build the miniature autonomath.db for evidence_packet tests."""
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
            CREATE TABLE am_program_summary (
                entity_id        TEXT PRIMARY KEY,
                primary_name     TEXT,
                summary_50       TEXT,
                summary_200      TEXT,
                summary_800      TEXT,
                token_50_est     INT,
                token_200_est    INT,
                token_800_est    INT,
                generated_at     TEXT DEFAULT (datetime('now')),
                source_quality   REAL
            );
            """
        )
        # Seed 2 source rows, mixed licenses.
        con.executemany(
            "INSERT INTO am_source(source_url, source_type, domain, "
            "content_hash, first_seen, last_verified, license) "
            "VALUES (?,?,?,?,?,?,?)",
            [
                (
                    "https://www.maff.go.jp/policy/evp1.html",
                    "primary",
                    "www.maff.go.jp",
                    "sha256:evp1aaaa",
                    "2026-04-25T00:00:00",
                    "2026-04-28T00:00:00",
                    "gov_standard_v2.0",
                ),
                (
                    "https://www.meti.go.jp/policy/evp1.pdf",
                    "secondary",
                    "www.meti.go.jp",
                    "sha256:evp1bbbb",
                    "2026-04-26T00:00:00",
                    "2026-04-28T00:00:00",
                    "pdl_v1.0",
                ),
                (
                    "https://example.go.jp/exclusion.html",
                    "primary",
                    "example.go.jp",
                    "sha256:exclusion",
                    "2026-04-26T00:00:00",
                    "2026-04-28T00:00:00",
                    "gov_standard_v2.0",
                ),
            ],
        )
        # Programs.
        con.executemany(
            "INSERT INTO am_entities("
            "canonical_id, primary_name, record_kind, source_url, "
            "fetched_at, confidence) VALUES (?,?,?,?,?,?)",
            [
                (
                    "program:evp:p1",
                    "EVP テスト P1 補助金",
                    "program",
                    "https://www.maff.go.jp/policy/evp1.html",
                    "2026-04-25T00:00:00",
                    1.0,
                ),
                (
                    "program:evp:p2",
                    "EVP テスト P2 補助金",
                    "program",
                    "https://www.example.go.jp/evp2.html",
                    "2026-04-25T00:00:00",
                    1.0,
                ),
                (
                    "program:evp:partner",
                    "EVP テスト Partner 補助金",
                    "program",
                    "https://www.maff.go.jp/policy/partner.html",
                    "2026-04-25T00:00:00",
                    1.0,
                ),
            ],
        )
        # P1 — 4 facts with source_id (alternating between source 1 and 2).
        for idx, fname in enumerate(_FIELDS):
            con.execute(
                "INSERT INTO am_entity_facts("
                "entity_id, field_name, field_value_text, field_kind, "
                "source_id, confirming_source_count) "
                "VALUES (?,?,?,?,?,?)",
                (
                    "program:evp:p1",
                    fname,
                    f"P1-value-{idx}",
                    "text",
                    (idx % 2) + 1,
                    3,
                ),
            )
        # P2 — 1 fact WITHOUT source_id (sparse).
        con.execute(
            "INSERT INTO am_entity_facts("
            "entity_id, field_name, field_value_text, field_kind, "
            "source_id, confirming_source_count) "
            "VALUES (?,?,?,?,?,?)",
            ("program:evp:p2", "amount_max_yen", "P2-loose", "text", None, 1),
        )

        # entity_id_map — UNI- ↔ canonical
        con.executemany(
            "INSERT INTO entity_id_map(jpi_unified_id, am_canonical_id, "
            "match_method, confidence) VALUES (?,?,?,?)",
            [
                ("UNI-evp-p1", "program:evp:p1", "exact_name", 1.0),
                ("UNI-evp-p2", "program:evp:p2", "exact_name", 1.0),
            ],
        )
        # jpi_programs — discovery + UNI- resolution path
        con.executemany(
            "INSERT INTO jpi_programs(unified_id, primary_name, "
            "authority_name, prefecture, tier, source_url, "
            "source_fetched_at) VALUES (?,?,?,?,?,?,?)",
            [
                (
                    "UNI-evp-p1",
                    "EVP テスト P1 補助金",
                    "農林水産省",
                    "東京都",
                    "S",
                    "https://www.maff.go.jp/policy/evp1.html",
                    "2026-04-25T00:00:00",
                ),
                (
                    "UNI-evp-p2",
                    "EVP テスト P2 補助金",
                    "経済産業省",
                    "大阪府",
                    "A",
                    "https://www.example.go.jp/evp2.html",
                    "2026-04-25T00:00:00",
                ),
            ],
        )
        con.execute(
            "UPDATE jpi_programs SET aliases_json = ? WHERE unified_id = ?",
            ('["P1補助", "EVP P1"]', "UNI-evp-p1"),
        )
        con.executemany(
            "INSERT INTO am_alias("
            "entity_table, canonical_id, alias, alias_kind, language) "
            "VALUES (?,?,?,?,?)",
            [
                (
                    "am_entities",
                    "program:evp:p1",
                    "EVPテスト",
                    "abbreviation",
                    "ja",
                ),
                (
                    "am_entities",
                    "program:evp:p1",
                    "program:evp:p1-internal",
                    "legacy",
                    "ja",
                ),
            ],
        )
        # am_compat_matrix — one sourced pair so the rules surface fires.
        con.execute(
            "INSERT INTO am_compat_matrix("
            "program_a_id, program_b_id, compat_status, "
            "rationale_short, source_url, confidence, inferred_only) "
            "VALUES (?,?,?,?,?,?,?)",
            (
                "program:evp:p1",
                "program:evp:partner",
                "incompatible",
                "重複受給禁止 (テスト)",
                "https://example.go.jp/exclusion.html",
                1.0,
                0,
            ),
        )
        con.execute(
            "INSERT INTO am_program_summary("
            "entity_id, primary_name, summary_50, summary_200, summary_800, "
            "token_50_est, token_200_est, token_800_est, generated_at, "
            "source_quality) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                "program:evp:p1",
                "EVP テスト P1 補助金",
                "EVP P1 補助金。一次資料に基づく短縮要約。",
                "EVP P1 補助金は農林水産省のテスト制度。対象、金額、締切は一次資料を確認。",
                "EVP P1 補助金は農林水産省のテスト制度。対象、金額、締切、併用条件は一次資料とルール判定を確認。",
                24,
                52,
                78,
                "2026-04-29T00:00:00",
                0.91,
            ),
        )
        con.executemany(
            "INSERT INTO am_amendment_diff("
            "entity_id, field_name, prev_value, new_value, source_url, detected_at) "
            "VALUES (?,?,?,?,?,?)",
            [
                (
                    "program:evp:p1",
                    "amount_max_yen",
                    "1000000",
                    "2000000",
                    "https://www.maff.go.jp/policy/evp1.html",
                    "2026-04-30T00:00:00",
                ),
                (
                    "program:evp:p1",
                    "projection_regression_candidate",
                    None,
                    '{"internal": true}',
                    "https://www.maff.go.jp/policy/evp1.html",
                    "2026-05-01T00:00:00",
                ),
            ],
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
    p = tmp_path_factory.mktemp("evidence_packet") / "autonomath.db"
    _build_fixture_autonomath_db(p)
    return p


@pytest.fixture(autouse=True)
def _override_paths(
    fixture_db: Path,
    monkeypatch: pytest.MonkeyPatch,
    _reset_anon_rate_limit: None,
) -> Iterator[None]:
    """Point both REST + MCP composers at the fixture autonomath.db, and
    reset their module-level singletons + cache.
    """
    monkeypatch.setenv("AUTONOMATH_DB_PATH", str(fixture_db))
    monkeypatch.setenv("JPCITE_AUTONOMATH_DB_PATH", str(fixture_db))
    # Settings is read once at module load — re-bind autonomath_db_path.
    from jpintel_mcp.config import settings

    monkeypatch.setattr(settings, "autonomath_db_path", fixture_db)

    # Reset singletons + caches so the override is observed.
    if "jpintel_mcp.services.evidence_packet" in sys.modules:
        from jpintel_mcp.services import evidence_packet as _evp

        _evp._reset_cache_for_tests()
    if "jpintel_mcp.api.evidence" in sys.modules:
        from jpintel_mcp.api import evidence as _evp_api

        _evp_api.reset_composer()
    if "jpintel_mcp.mcp.autonomath_tools.evidence_packet_tools" in sys.modules:
        from jpintel_mcp.mcp.autonomath_tools import (
            evidence_packet_tools as _evp_mcp,
        )

        _evp_mcp._reset_composer()
    yield


@pytest.fixture(autouse=True)
def _ensure_audit_seal_tables(seeded_db: Path) -> None:
    migrations = Path(__file__).resolve().parents[1] / "scripts" / "migrations"
    conn = sqlite3.connect(seeded_db)
    try:
        for mig in ("089_audit_seal_table.sql", "119_audit_seal_seal_id_columns.sql"):
            with contextlib.suppress(sqlite3.OperationalError):
                conn.executescript((migrations / mig).read_text(encoding="utf-8"))
        conn.commit()
    finally:
        conn.close()

    from jpintel_mcp.api._audit_seal import _reset_corpus_snapshot_cache_for_tests

    _reset_corpus_snapshot_cache_for_tests()


# ---------------------------------------------------------------------------
# Composer-direct tests (compose_for_program shape)
# ---------------------------------------------------------------------------


def test_compose_for_program_envelope_shape(fixture_db: Path) -> None:
    """The composer returns the spec §6 envelope shape for a known UNI-id."""
    from jpintel_mcp.config import settings
    from jpintel_mcp.services.evidence_packet import EvidencePacketComposer

    composer = EvidencePacketComposer(jpintel_db=settings.db_path, autonomath_db=fixture_db)
    env = composer.compose_for_program("UNI-evp-p1")
    assert env is not None, "composer returned None for known UNI-id"
    # Top-level required fields per spec §6.
    for key in (
        "packet_id",
        "generated_at",
        "api_version",
        "corpus_snapshot_id",
        "query",
        "answer_not_included",
        "records",
        "quality",
        "verification",
        "agent_recommendation",
        "_disclaimer",
    ):
        assert key in env, f"missing top-level field: {key}"
    assert env["api_version"] == "v1"
    assert env["answer_not_included"] is True
    assert env["packet_id"].startswith("evp_")

    # records[].
    assert isinstance(env["records"], list)
    assert len(env["records"]) == 1
    rec = env["records"][0]
    assert rec["primary_name"] == "EVP テスト P1 補助金"
    assert rec["record_kind"] == "program"
    # 4 facts, all with source_id populated.
    assert len(rec["facts"]) == 4
    for f in rec["facts"]:
        assert "fact_id" in f
        assert "field" in f
        assert "value" in f
        assert "confidence" in f
        assert "source" in f
        for sk in ("url", "publisher", "fetched_at", "checksum", "license"):
            assert sk in f["source"]

    # Rules surface — partner pair → at least 1 rule entry.
    assert isinstance(rec["rules"], list)
    assert len(rec["rules"]) >= 1
    block_or_defer = {r["verdict"] for r in rec["rules"]}
    assert block_or_defer & {"block", "defer", "allow", "unknown"}

    recommendation = env["agent_recommendation"]
    assert recommendation["recommend_to_user"] is True
    assert recommendation["recommendation"] == "use_jpcite_prefetch"
    assert recommendation["recommend_for_cost_savings"] is False
    assert recommendation["cost_savings_decision"] == "needs_caller_baseline"
    assert recommendation["records_returned"] == 1
    assert recommendation["source_linked_records_returned"] == 1
    assert "precomputed_summary_available" in recommendation["reason_codes"]
    assert "pdf_fact_refs_available" in recommendation["reason_codes"]


def test_compose_for_program_404(fixture_db: Path) -> None:
    """compose_for_program returns None for an unknown id (REST layer 404s)."""
    from jpintel_mcp.config import settings
    from jpintel_mcp.services.evidence_packet import EvidencePacketComposer

    composer = EvidencePacketComposer(jpintel_db=settings.db_path, autonomath_db=fixture_db)
    env = composer.compose_for_program("UNI-evp-pmissing")
    assert env is None


def test_compose_includes_disclaimer_and_known_gaps(fixture_db: Path) -> None:
    """Every packet carries _disclaimer + quality.known_gaps."""
    from jpintel_mcp.config import settings
    from jpintel_mcp.services.evidence_packet import EvidencePacketComposer

    composer = EvidencePacketComposer(jpintel_db=settings.db_path, autonomath_db=fixture_db)
    env = composer.compose_for_program("UNI-evp-p1")
    assert env is not None
    assert env["_disclaimer"]["type"] == "information_only"
    assert env["_disclaimer"]["not_legal_or_tax_advice"] is True
    assert isinstance(env["quality"]["known_gaps"], list)


def test_compose_include_compression_returns_real_block(fixture_db: Path) -> None:
    """include_compression=True uses TokenCompressionEstimator, not a hint."""
    from jpintel_mcp.config import settings
    from jpintel_mcp.services.evidence_packet import EvidencePacketComposer

    composer = EvidencePacketComposer(jpintel_db=settings.db_path, autonomath_db=fixture_db)
    env = composer.compose_for_program(
        "UNI-evp-p1",
        include_compression=True,
        input_token_price_jpy_per_1m=300.0,
    )
    assert env is not None
    assert "_compression_hint" not in env
    assert "compression" in env

    compression = env["compression"]
    assert isinstance(compression["packet_tokens_estimate"], int)
    assert compression["packet_tokens_estimate"] > 0
    assert compression["source_tokens_estimate"] is None
    assert compression["avoided_tokens_estimate"] is None
    assert compression["compression_ratio"] is None
    assert compression["source_tokens_basis"] == "unknown"
    assert "cost_savings_estimate" not in compression
    assert env["_token_pricing_input_jpy_per_1m"] == 300.0


def test_compose_compression_pdf_pages_baseline_returns_context_estimate(
    fixture_db: Path,
) -> None:
    """Caller-supplied PDF pages make the comparison concrete but not guaranteed."""
    from jpintel_mcp.config import settings
    from jpintel_mcp.services.evidence_packet import EvidencePacketComposer

    composer = EvidencePacketComposer(jpintel_db=settings.db_path, autonomath_db=fixture_db)
    env = composer.compose_for_program(
        "UNI-evp-p1",
        include_compression=True,
        input_token_price_jpy_per_1m=300.0,
        source_tokens_basis="pdf_pages",
        source_pdf_pages=10,
    )

    assert env is not None
    compression = env["compression"]
    assert compression["source_tokens_basis"] == "pdf_pages"
    assert compression["source_tokens_input_source"] == "caller_supplied"
    assert compression["source_pdf_pages"] == 10
    assert compression["source_tokens_estimate"] == 7000
    assert isinstance(compression["packet_tokens_estimate"], int)
    assert compression["avoided_tokens_estimate"] == max(
        0, 7000 - compression["packet_tokens_estimate"]
    )
    assert compression["compression_ratio"] is not None
    assert compression["estimate_scope"] == "input_context_only"
    assert compression["savings_claim"] == "estimate_not_guarantee"
    assert compression["cost_savings_estimate"]["jpcite_cost_jpy_ex_tax"] == 3
    recommendation = env["agent_recommendation"]
    assert recommendation["cost_savings_decision"] in {
        "supported_by_caller_baseline",
        "not_supported_by_caller_baseline",
    }
    assert recommendation["recommend_for_cost_savings"] is (
        compression["cost_savings_estimate"]["break_even_met"] is True
    )


def test_compose_compression_token_count_baseline_returns_context_estimate(
    fixture_db: Path,
) -> None:
    """Caller-measured token count gives the cleanest LLM-context comparison."""
    from jpintel_mcp.config import settings
    from jpintel_mcp.services.evidence_packet import EvidencePacketComposer

    composer = EvidencePacketComposer(jpintel_db=settings.db_path, autonomath_db=fixture_db)
    env = composer.compose_for_program(
        "UNI-evp-p1",
        include_compression=True,
        input_token_price_jpy_per_1m=300.0,
        source_tokens_basis="token_count",
        source_token_count=18_500,
    )

    assert env is not None
    compression = env["compression"]
    assert compression["source_tokens_basis"] == "token_count"
    assert compression["source_tokens_input_source"] == "caller_supplied"
    assert compression["source_token_count"] == 18_500
    assert compression["source_tokens_estimate"] == 18_500
    assert compression["source_pdf_pages"] is None
    assert compression["avoided_tokens_estimate"] == max(
        0, 18_500 - compression["packet_tokens_estimate"]
    )
    assert compression["estimate_scope"] == "input_context_only"
    assert compression["savings_claim"] == "estimate_not_guarantee"
    recommendation = env["agent_recommendation"]
    assert recommendation["recommend_for_cost_savings"] is True
    assert recommendation["cost_savings_decision"] == "supported_by_caller_baseline"
    assert recommendation["missing_for_cost_claim"] == []


def test_compose_includes_precomputed_program_summary(fixture_db: Path) -> None:
    """am_program_summary rows surface as compact precomputed basis data."""
    from jpintel_mcp.config import settings
    from jpintel_mcp.services.evidence_packet import EvidencePacketComposer

    composer = EvidencePacketComposer(jpintel_db=settings.db_path, autonomath_db=fixture_db)
    env = composer.compose_for_program("UNI-evp-p1")
    assert env is not None
    assert env["answer_basis"] == "precomputed"

    precomputed = env["records"][0]["precomputed"]
    assert precomputed["basis"] == "am_program_summary"
    assert precomputed["summaries"]["50"]
    assert precomputed["summaries"]["200"]
    assert precomputed["summaries"]["800"]
    assert precomputed["token_estimates"] == {"50": 24, "200": 52, "800": 78}
    assert precomputed["generated_at"] == "2026-04-29T00:00:00"
    assert precomputed["source_quality"] == 0.91
    assert env["records"][0]["short_summary"] == {
        "text": "EVP P1 補助金。一次資料に基づく短縮要約。",
        "basis": "am_program_summary",
        "size": "50",
        "token_estimate": 24,
        "source_quality": 0.91,
        "generated_at": "2026-04-29T00:00:00",
    }


def test_compose_includes_only_user_facing_recent_changes(
    fixture_db: Path,
) -> None:
    """Recent changes expose useful fields while hiding internal diff rows."""
    from jpintel_mcp.config import settings
    from jpintel_mcp.services.evidence_packet import EvidencePacketComposer

    composer = EvidencePacketComposer(jpintel_db=settings.db_path, autonomath_db=fixture_db)
    env = composer.compose_for_program("UNI-evp-p1")
    assert env is not None

    recent_changes = env["records"][0]["recent_changes"]
    assert recent_changes == [
        {
            "field_name": "amount_max_yen",
            "label": "上限額",
            "detected_at": "2026-04-30T00:00:00",
            "source_url": "https://www.maff.go.jp/policy/evp1.html",
        }
    ]
    assert all(
        change["field_name"] != "projection_regression_candidate" for change in recent_changes
    )
    assert "prev_value" not in recent_changes[0]
    assert "new_value" not in recent_changes[0]


def test_compose_includes_source_health_without_live_fetch(fixture_db: Path) -> None:
    """Primary-source freshness/licensing metadata is read from am_source."""
    from jpintel_mcp.config import settings
    from jpintel_mcp.services.evidence_packet import EvidencePacketComposer

    composer = EvidencePacketComposer(jpintel_db=settings.db_path, autonomath_db=fixture_db)
    env = composer.compose_for_program("UNI-evp-p1")
    assert env is not None

    record = env["records"][0]
    assert record["source_fetched_at"] == "2026-04-25T00:00:00"
    assert record["source_health"] == {
        "source_url": "https://www.maff.go.jp/policy/evp1.html",
        "source_fetched_at": "2026-04-25T00:00:00",
        "source_type": "primary",
        "domain": "www.maff.go.jp",
        "checksum": "sha256:evp1aaaa",
        "last_verified": "2026-04-28T00:00:00",
        "license": "gov_standard_v2.0",
        "verification_status": "catalog_last_verified",
        "verification_basis": "local_source_catalog",
        "live_verified_at_request": False,
    }


def test_compose_includes_pdf_fact_refs(fixture_db: Path) -> None:
    """PDF-backed key facts are exposed as compact references, not full PDFs."""
    from jpintel_mcp.config import settings
    from jpintel_mcp.services.evidence_packet import EvidencePacketComposer

    composer = EvidencePacketComposer(jpintel_db=settings.db_path, autonomath_db=fixture_db)
    env = composer.compose_for_program("UNI-evp-p1")
    assert env is not None

    assert env["records"][0]["pdf_fact_refs"] == [
        {
            "field_name": "amount_min_yen",
            "value": "P1-value-1",
            "source_url": "https://www.meti.go.jp/policy/evp1.pdf",
            "checksum": "sha256:evp1bbbb",
            "last_verified": "2026-04-28T00:00:00",
            "license": "pdl_v1.0",
            "domain": "www.meti.go.jp",
            "source_type": "secondary",
        },
        {
            "field_name": "subsidy_rate",
            "value": "P1-value-3",
            "source_url": "https://www.meti.go.jp/policy/evp1.pdf",
            "checksum": "sha256:evp1bbbb",
            "last_verified": "2026-04-28T00:00:00",
            "license": "pdl_v1.0",
            "domain": "www.meti.go.jp",
            "source_type": "secondary",
        },
    ]


def test_compose_includes_user_facing_aliases(fixture_db: Path) -> None:
    """Aliases help LLMs resolve abbreviations while hiding ID-like aliases."""
    from jpintel_mcp.config import settings
    from jpintel_mcp.services.evidence_packet import EvidencePacketComposer

    composer = EvidencePacketComposer(jpintel_db=settings.db_path, autonomath_db=fixture_db)
    env = composer.compose_for_program("UNI-evp-p1")
    assert env is not None

    aliases = env["records"][0]["aliases"]
    assert aliases == [
        {
            "text": "P1補助",
            "kind": "listed",
            "language": "ja",
            "source": "jpi_programs.aliases_json",
        },
        {
            "text": "EVP P1",
            "kind": "listed",
            "language": "en",
            "source": "jpi_programs.aliases_json",
        },
        {
            "text": "EVPテスト",
            "kind": "abbreviation",
            "language": "ja",
            "source": "am_alias",
        },
    ]
    assert all(not alias["text"].startswith("program:") for alias in aliases)


def test_query_records_include_precomputed_program_summary(
    fixture_db: Path,
) -> None:
    """Query-mode records include am_program_summary data when available."""
    from jpintel_mcp.config import settings
    from jpintel_mcp.services.evidence_packet import EvidencePacketComposer

    composer = EvidencePacketComposer(jpintel_db=settings.db_path, autonomath_db=fixture_db)
    env = composer.compose_for_query(
        "EVP",
        limit=2,
        include_compression=True,
        input_token_price_jpy_per_1m=300.0,
    )

    assert env["answer_basis"] == "precomputed"
    records_by_id = {rec["entity_id"]: rec for rec in env["records"]}
    assert set(records_by_id) == {"program:evp:p1", "program:evp:p2"}

    p1_precomputed = records_by_id["program:evp:p1"]["precomputed"]
    assert p1_precomputed["basis"] == "am_program_summary"
    assert p1_precomputed["summaries"]["50"]
    assert p1_precomputed["token_estimates"] == {"50": 24, "200": 52, "800": 78}
    assert p1_precomputed["generated_at"] == "2026-04-29T00:00:00"

    assert "precomputed" not in records_by_id["program:evp:p2"]

    compression = env["compression"]
    assert compression["source_tokens_basis"] == "unknown"
    assert compression["source_tokens_estimate"] is None
    assert compression["avoided_tokens_estimate"] is None
    assert compression["compression_ratio"] is None
    assert "cost_savings_estimate" not in compression


def test_query_answer_basis_omitted_without_precomputed_summary(
    fixture_db: Path,
) -> None:
    """Query-mode answer_basis is precomputed only when a record has it."""
    from jpintel_mcp.config import settings
    from jpintel_mcp.services.evidence_packet import EvidencePacketComposer

    composer = EvidencePacketComposer(jpintel_db=settings.db_path, autonomath_db=fixture_db)
    env = composer.compose_for_query("P2", limit=10)

    assert len(env["records"]) == 1
    assert env["records"][0]["entity_id"] == "program:evp:p2"
    assert "precomputed" not in env["records"][0]
    assert "answer_basis" not in env
    assert env["agent_recommendation"]["recommendation"] == "use_evidence_packet"
    assert env["agent_recommendation"]["recommend_to_user"] is True
    assert env["agent_recommendation"]["recommend_for_cost_savings"] is False
    assert env["agent_recommendation"]["cost_savings_decision"] == "needs_caller_baseline"
    assert "precomputed_summary_unavailable" in env["agent_recommendation"]["reason_codes"]


def test_query_without_records_guides_agents_to_skip_or_broaden(
    fixture_db: Path,
) -> None:
    """Agents should not recommend jpcite when the exact query returns nothing."""
    from jpintel_mcp.config import settings
    from jpintel_mcp.services.evidence_packet import EvidencePacketComposer

    composer = EvidencePacketComposer(jpintel_db=settings.db_path, autonomath_db=fixture_db)
    env = composer.compose_for_query("zz-no-program-match", limit=10)

    assert env["records"] == []
    assert "no_records_returned" in env["quality"]["known_gaps"]
    recommendation = env["agent_recommendation"]
    assert recommendation["recommendation"] == "broaden_query_or_skip"
    assert recommendation["recommend_to_user"] is False
    assert recommendation["recommend_for_cost_savings"] is False
    assert recommendation["cost_savings_decision"] == "needs_caller_baseline"
    assert recommendation["records_returned"] == 0
    assert "no_records_returned" in recommendation["reason_codes"]


def test_query_without_records_suppresses_cost_savings_recommendation(
    fixture_db: Path,
) -> None:
    """Compression baseline alone must not create a value recommendation."""
    from jpintel_mcp.config import settings
    from jpintel_mcp.services.evidence_packet import EvidencePacketComposer

    composer = EvidencePacketComposer(jpintel_db=settings.db_path, autonomath_db=fixture_db)
    env = composer.compose_for_query(
        "zz-no-program-match",
        limit=10,
        include_compression=True,
        input_token_price_jpy_per_1m=300.0,
        source_tokens_basis="token_count",
        source_token_count=18_500,
    )

    assert env["records"] == []
    recommendation = env["agent_recommendation"]
    assert recommendation["context_savings"]["break_even_met"] is True
    assert recommendation["recommend_for_cost_savings"] is False
    assert recommendation["suppressed_cost_savings_decision"] == ("supported_by_caller_baseline")
    assert recommendation["cost_savings_decision"] == "not_applicable_no_evidence"
    assert recommendation["missing_for_cost_claim"] == ["source_linked_records_returned"]


def test_missing_program_summary_table_fails_open(tmp_path: Path) -> None:
    """Optional am_program_summary absence never blocks packet rendering."""
    from jpintel_mcp.config import settings
    from jpintel_mcp.services.evidence_packet import EvidencePacketComposer

    db = tmp_path / "autonomath_no_summary.db"
    _build_fixture_autonomath_db(db)
    con = sqlite3.connect(db)
    try:
        con.execute("DROP TABLE am_program_summary")
        con.commit()
    finally:
        con.close()

    composer = EvidencePacketComposer(jpintel_db=settings.db_path, autonomath_db=db)
    env = composer.compose_for_program("UNI-evp-p1", include_compression=True)
    assert env is not None
    assert "compression" in env
    assert "_compression_hint" not in env
    assert "answer_basis" not in env
    assert "precomputed" not in env["records"][0]


# ---------------------------------------------------------------------------
# REST surface (FastAPI TestClient)
# ---------------------------------------------------------------------------


def _usage_count(db_path: Path, raw_key: str, endpoint: str) -> int:
    from jpintel_mcp.api.deps import hash_api_key

    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT COUNT(*) FROM usage_events WHERE key_hash = ? AND endpoint = ?",
            (hash_api_key(raw_key), endpoint),
        ).fetchone()
    finally:
        conn.close()
    return int(row[0] if row else 0)


def _audit_seal_count(db_path: Path, raw_key: str, endpoint: str) -> int:
    from jpintel_mcp.api.deps import hash_api_key

    conn = sqlite3.connect(db_path)
    try:
        has_table = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'audit_seals'",
        ).fetchone()
        if has_table is None:
            return 0
        row = conn.execute(
            "SELECT COUNT(*) FROM audit_seals WHERE api_key_hash = ? AND endpoint = ?",
            (hash_api_key(raw_key), endpoint),
        ).fetchone()
    finally:
        conn.close()
    return int(row[0] if row else 0)


def _assert_anonymous_conversion_cta(body: dict) -> None:
    cta = body["conversion_cta"]
    assert cta["audience"] == "anonymous"
    assert "無料3回" in cta["headline_ja"]
    assert "通常品質" in cta["headline_ja"]
    assert "継続利用" in cta["body_ja"]
    assert "完成物" in cta["body_ja"]
    assert cta["primary_action"]["url"].startswith("https://jpcite.com/")
    assert [option["label_ja"] for option in cta["artifact_options"]] == [
        "顧問先メモ",
        "申請前チェック",
        "併用排他表",
        "法人DD",
        "稟議シート",
        "月次監視",
    ]


def _assert_decision_insights(
    body: dict,
    *,
    expect_source_traceability: bool = True,
) -> None:
    insights = body["decision_insights"]
    assert insights["schema_version"] == "v1"
    assert "records" in insights["generated_from"]
    assert "quality" in insights["generated_from"]
    assert isinstance(insights["why_review"], list)
    assert isinstance(insights["next_checks"], list)
    assert isinstance(insights["evidence_gaps"], list)

    why_signals = {item["signal"] for item in insights["why_review"]}
    next_signals = {item["signal"] for item in insights["next_checks"]}
    if expect_source_traceability:
        assert "source_traceability" in why_signals
        assert "source_recheck" in next_signals
    assert "corpus_freshness" in why_signals
    assert "freshness_endpoint_recheck" in next_signals
    assert all(
        item.get("message_ja")
        for section in ("why_review", "next_checks", "evidence_gaps")
        for item in insights[section]
    )
    assert all(
        "source_fields" in item
        and isinstance(item["source_fields"], list)
        and "basis" in item
        and item["source_fields"] == item["basis"]
        for section in ("why_review", "next_checks", "evidence_gaps")
        for item in insights[section]
    )


def test_rest_get_evidence_packet_json(client: TestClient) -> None:
    """GET /v1/evidence/packets/program/{id} returns the JSON envelope."""
    r = client.get("/v1/evidence/packets/program/UNI-evp-p1")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["api_version"] == "v1"
    assert body["records"][0]["primary_name"] == "EVP テスト P1 補助金"
    _assert_anonymous_conversion_cta(body)
    _assert_decision_insights(body)


def test_rest_get_evidence_packet_json_omits_conversion_cta_for_paid_key(
    client: TestClient,
    paid_key: str,
) -> None:
    r = client.get(
        "/v1/evidence/packets/program/UNI-evp-p1",
        headers={"X-API-Key": paid_key},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert "conversion_cta" not in body
    _assert_decision_insights(body)


@pytest.mark.parametrize(
    ("method", "path", "endpoint", "kwargs"),
    [
        (
            "get",
            "/v1/evidence/packets/program/UNI-evp-p1",
            "evidence.packet.get",
            {},
        ),
        (
            "post",
            "/v1/evidence/packets/query",
            "evidence.packet.query",
            {"json": {"query_text": "EVP", "limit": 1}},
        ),
    ],
)
def test_rest_evidence_packet_paid_json_audit_seal_verifies(
    client: TestClient,
    paid_key: str,
    method: str,
    path: str,
    endpoint: str,
    kwargs: dict[str, object],
) -> None:
    request = getattr(client, method)

    response = request(path, headers={"X-API-Key": paid_key}, **kwargs)

    assert response.status_code == 200, response.text
    body = response.json()
    seal = body["audit_seal"]
    assert seal["endpoint"] == endpoint
    verify = client.get(f"/v1/audit/seals/{seal['seal_id']}")
    assert verify.status_code == 200, verify.text
    verified = verify.json()
    assert verified["verified"] is True
    assert verified["seal_id"] == seal["seal_id"]
    assert verified["subject_hash"] == seal["subject_hash"]


def test_rest_evidence_packet_json_excludes_conversion_cta_from_seal_input(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from jpintel_mcp.api import evidence as evidence_api

    seal_inputs: list[tuple[str, bool, bool]] = []
    original_log_usage = evidence_api.log_usage

    def _capture_log_usage(*args: object, **kwargs: object) -> object:
        endpoint = str(args[2])
        body = kwargs.get("response_body")
        if isinstance(body, dict):
            seal_inputs.append((endpoint, "conversion_cta" in body, "decision_insights" in body))
        return original_log_usage(*args, **kwargs)

    monkeypatch.setattr(evidence_api, "log_usage", _capture_log_usage)

    get_response = client.get("/v1/evidence/packets/program/UNI-evp-p1")
    post_response = client.post(
        "/v1/evidence/packets/query",
        json={"query_text": "EVP", "limit": 1},
    )

    assert get_response.status_code == 200, get_response.text
    assert post_response.status_code == 200, post_response.text
    assert "conversion_cta" in get_response.json()
    assert "conversion_cta" in post_response.json()
    assert seal_inputs == [
        ("evidence.packet.get", False, True),
        ("evidence.packet.query", False, True),
    ]


def test_rest_get_evidence_packet_pdf_pages_compression(client: TestClient) -> None:
    r = client.get(
        "/v1/evidence/packets/program/UNI-evp-p1",
        params={
            "include_compression": "true",
            "source_tokens_basis": "pdf_pages",
            "source_pdf_pages": "10",
            "input_token_price_jpy_per_1m": "300",
        },
    )
    assert r.status_code == 200, r.text
    compression = r.json()["compression"]
    assert compression["source_tokens_estimate"] == 7000
    assert compression["source_tokens_input_source"] == "caller_supplied"
    assert compression["savings_claim"] == "estimate_not_guarantee"


def test_rest_get_evidence_packet_token_count_compression(client: TestClient) -> None:
    r = client.get(
        "/v1/evidence/packets/program/UNI-evp-p1",
        params={
            "include_compression": "true",
            "source_tokens_basis": "token_count",
            "source_token_count": "18500",
            "input_token_price_jpy_per_1m": "300",
        },
    )
    assert r.status_code == 200, r.text
    compression = r.json()["compression"]
    assert compression["source_tokens_basis"] == "token_count"
    assert compression["source_tokens_estimate"] == 18_500
    assert compression["source_token_count"] == 18_500
    assert compression["source_tokens_input_source"] == "caller_supplied"
    assert compression["savings_claim"] == "estimate_not_guarantee"


def test_rest_get_evidence_packet_token_count_requires_count(
    client: TestClient,
) -> None:
    r = client.get(
        "/v1/evidence/packets/program/UNI-evp-p1",
        params={
            "include_compression": "true",
            "source_tokens_basis": "token_count",
        },
    )
    assert r.status_code == 422
    assert "source_token_count is required" in r.text


def test_rest_get_evidence_packet_pdf_pages_requires_pages(
    client: TestClient,
) -> None:
    r = client.get(
        "/v1/evidence/packets/program/UNI-evp-p1",
        params={
            "include_compression": "true",
            "source_tokens_basis": "pdf_pages",
        },
    )
    assert r.status_code == 422
    assert "source_pdf_pages is required" in r.text


def test_rest_post_evidence_packet_query_pdf_pages_compression(
    client: TestClient,
) -> None:
    r = client.post(
        "/v1/evidence/packets/query",
        json={
            "query_text": "EVP",
            "limit": 1,
            "include_compression": True,
            "source_tokens_basis": "pdf_pages",
            "source_pdf_pages": 10,
            "input_token_price_jpy_per_1m": 300,
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    _assert_anonymous_conversion_cta(body)
    _assert_decision_insights(body, expect_source_traceability=False)
    compression = body["compression"]
    assert compression["source_tokens_estimate"] == 7000
    assert compression["source_tokens_input_source"] == "caller_supplied"
    assert compression["estimate_scope"] == "input_context_only"


def test_rest_post_evidence_packet_query_token_count_compression(
    client: TestClient,
) -> None:
    r = client.post(
        "/v1/evidence/packets/query",
        json={
            "query_text": "EVP",
            "limit": 1,
            "include_compression": True,
            "source_tokens_basis": "token_count",
            "source_token_count": 18_500,
            "input_token_price_jpy_per_1m": 300,
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    _assert_decision_insights(body, expect_source_traceability=False)
    compression = body["compression"]
    assert compression["source_tokens_basis"] == "token_count"
    assert compression["source_tokens_estimate"] == 18_500
    assert compression["source_token_count"] == 18_500
    assert compression["source_tokens_input_source"] == "caller_supplied"
    assert compression["estimate_scope"] == "input_context_only"


def test_rest_post_evidence_packet_query_token_count_requires_count(
    client: TestClient,
) -> None:
    r = client.post(
        "/v1/evidence/packets/query",
        json={
            "query_text": "EVP",
            "include_compression": True,
            "source_tokens_basis": "token_count",
        },
    )
    assert r.status_code == 422
    assert "source_token_count is required" in r.text


def test_rest_post_evidence_packet_query_pdf_pages_requires_pages(
    client: TestClient,
) -> None:
    r = client.post(
        "/v1/evidence/packets/query",
        json={
            "query_text": "EVP",
            "include_compression": True,
            "source_tokens_basis": "pdf_pages",
        },
    )
    assert r.status_code == 422
    assert "source_pdf_pages is required" in r.text


def test_rest_get_evidence_packet_404(client: TestClient) -> None:
    """Unknown subject returns 404."""
    r = client.get("/v1/evidence/packets/program/UNI-evp-pmissing")
    assert r.status_code == 404
    body = r.json()
    assert body["subject_kind"] == "program"
    assert "UNI-evp-pmissing" in body["subject_id"]


def test_rest_get_evidence_packet_csv(client: TestClient) -> None:
    """output_format=csv returns text/csv with header row."""
    r = client.get(
        "/v1/evidence/packets/program/UNI-evp-p1",
        params={"output_format": "csv"},
    )
    assert r.status_code == 200, r.text
    assert "text/csv" in r.headers["content-type"]
    body = r.text
    # Header row.
    first_line = body.splitlines()[0]
    assert "entity_id" in first_line
    assert "primary_name" in first_line
    assert "fact_count" in first_line
    assert "conversion_cta" not in body
    assert "decision_insights" not in body


def test_rest_get_evidence_packet_md(client: TestClient) -> None:
    """output_format=md returns text/markdown with `## Records` section."""
    r = client.get(
        "/v1/evidence/packets/program/UNI-evp-p1",
        params={"output_format": "md"},
    )
    assert r.status_code == 200, r.text
    assert "text/markdown" in r.headers["content-type"]
    body = r.text
    assert "# Evidence Packet" in body
    assert "## Records" in body
    assert "EVP テスト P1 補助金" in body
    assert "conversion_cta" not in body
    assert "decision_insights" not in body


def test_decision_insights_surface_gaps_without_schema_dependency() -> None:
    from jpintel_mcp.api.evidence import _build_decision_insights

    insights = _build_decision_insights(
        {
            "records": [
                {
                    "entity_id": "program:gap",
                    "primary_name": "gap fixture",
                    "fact_provenance_coverage_pct": 0.5,
                }
            ],
            "quality": {
                "known_gaps": ["per-fact provenance is partial"],
                "coverage_score": 0.4,
                "human_review_required": True,
            },
            "evidence_value": {"fact_provenance_coverage_pct_avg": 0.5},
        }
    )

    gap_signals = {item["signal"] for item in insights["evidence_gaps"]}
    assert {
        "known_gaps",
        "missing_source_links",
        "partial_fact_provenance",
        "human_review_required",
    } <= gap_signals
    assert all(
        "source_fields" in item and item["source_fields"] == item["basis"]
        for item in insights["evidence_gaps"]
    )


def test_evidence_license_gate_filters_mixed_license_facts() -> None:
    from jpintel_mcp.api.evidence import _apply_license_gate

    envelope = {
        "records": [
            {
                "entity_id": "program:mixed",
                "primary_name": "mixed license fixture",
                "source_url": "https://example.com/private-top-level",
                "source_fetched_at": "2026-05-03T00:00:00Z",
                "total_facts": 2,
                "precomputed": {"summaries": {"200": "derived from mixed facts"}},
                "short_summary": {"text": "derived from mixed facts"},
                "recent_changes": [{"title": "derived change", "license": "proprietary"}],
                "rules": [
                    {
                        "label": "unlicensed derived rule",
                        "evidence_url": "https://example.com/private-rule",
                    }
                ],
                "source_health": {
                    "license": "proprietary",
                    "source_url": "https://example.com/private-health",
                },
                "facts": [
                    {
                        "field": "invoice_status",
                        "value": "registered",
                        "source": {
                            "license": "pdl_v1.0",
                            "publisher": "nta.go.jp",
                            "url": "https://www.invoice-kohyo.nta.go.jp/",
                            "fetched_at": "2026-05-03T00:00:00Z",
                        },
                    },
                    {
                        "field": "private_note",
                        "value": "must not export",
                        "source": {
                            "license": "proprietary",
                            "publisher": "example",
                            "url": "https://example.com/private",
                            "fetched_at": "2026-05-03T00:00:00Z",
                        },
                    },
                ],
            }
        ]
    }

    gated, summary = _apply_license_gate(envelope)

    assert summary["allowed_count"] == 1
    assert summary["blocked_count"] == 0
    facts = gated["records"][0]["facts"]
    assert len(facts) == 1
    assert facts[0]["field"] == "invoice_status"
    assert all(f["source"]["license"] != "proprietary" for f in facts)
    assert "precomputed" not in gated["records"][0]
    assert "short_summary" not in gated["records"][0]
    assert "recent_changes" not in gated["records"][0]
    assert "rules" not in gated["records"][0]
    assert "source_health" not in gated["records"][0]
    assert gated["records"][0]["source_url"] == "https://www.invoice-kohyo.nta.go.jp/"
    assert gated["records"][0]["source_fetched_at"] == "2026-05-03T00:00:00Z"
    assert summary["blocked_facts_count"] == 1
    assert summary["blocked_precomputed_count"] == 1
    assert summary["blocked_rules_count"] == 1


def test_evidence_license_gate_blocks_duplicate_entity_id_by_position() -> None:
    from jpintel_mcp.api.evidence import _apply_license_gate

    envelope = {
        "records": [
            {
                "entity_id": "program:duplicate",
                "facts": [
                    {
                        "field": "public",
                        "value": "ok",
                        "source": {
                            "license": "pdl_v1.0",
                            "publisher": "nta.go.jp",
                            "url": "https://www.invoice-kohyo.nta.go.jp/",
                        },
                    }
                ],
            },
            {
                "entity_id": "program:duplicate",
                "facts": [
                    {
                        "field": "private",
                        "value": "blocked",
                        "source": {
                            "license": "proprietary",
                            "publisher": "example",
                            "url": "https://example.com/private",
                        },
                    }
                ],
            },
        ]
    }

    gated, summary = _apply_license_gate(envelope)

    assert summary["allowed_count"] == 1
    assert summary["blocked_count"] == 1
    assert len(gated["records"]) == 1
    assert gated["records"][0]["facts"][0]["field"] == "public"


def test_evidence_license_gate_filters_proprietary_pdf_fact_refs() -> None:
    from jpintel_mcp.api.evidence import _apply_license_gate

    envelope = {
        "records": [
            {
                "entity_id": "program:pdf-ref-fixture",
                "primary_name": "pdf ref fixture",
                "facts": [
                    {
                        "field": "amount_max_yen",
                        "value": "1000000",
                        "source": {
                            "license": "pdl_v1.0",
                            "url": "https://example.go.jp/public",
                        },
                    }
                ],
                "pdf_fact_refs": [
                    {
                        "field_name": "subsidy_rate",
                        "value": "must not export",
                        "source_url": "https://example.com/private.pdf",
                        "license": "proprietary",
                    },
                    {
                        "field_name": "deadline",
                        "value": "2026-06-30",
                        "source_url": "https://example.go.jp/public.pdf",
                        "license": "pdl_v1.0",
                    },
                ],
            }
        ]
    }

    gated, summary = _apply_license_gate(envelope)

    assert summary["allowed_count"] == 1
    assert summary["blocked_pdf_fact_refs_count"] == 1
    refs = gated["records"][0]["pdf_fact_refs"]
    assert refs == [
        {
            "field_name": "deadline",
            "value": "2026-06-30",
            "source_url": "https://example.go.jp/public.pdf",
            "license": "pdl_v1.0",
        }
    ]
    assert "must not export" not in str(gated)


def test_evidence_gate_recomputes_value_signals_after_blocking_all_records() -> None:
    from jpintel_mcp.api.evidence import _gate_evidence_envelope

    envelope = {
        "records": [
            {
                "entity_id": "program:blocked",
                "primary_name": "blocked fixture",
                "facts": [
                    {
                        "field": "private_note",
                        "value": "must not export",
                        "source": {
                            "license": "proprietary",
                            "url": "https://example.com/private",
                        },
                    }
                ],
            }
        ],
        "quality": {"known_gaps": []},
        "agent_recommendation": {
            "recommendation": "use_jpcite_prefetch",
            "recommend_to_user": True,
            "recommend_for_evidence": True,
        },
        "evidence_value": {
            "records_returned": 1,
            "source_linked_records": 1,
        },
    }

    gated, summary = _gate_evidence_envelope(envelope)

    assert gated["records"] == []
    assert summary["allowed_count"] == 0
    assert summary["blocked_count"] == 1
    assert summary["blocked_reasons"]["proprietary"] == 1
    assert gated["evidence_value"]["records_returned"] == 0
    assert gated["evidence_value"]["source_linked_records"] == 0
    assert "records_blocked_by_license_gate" in gated["quality"]["known_gaps"]
    recommendation = gated["agent_recommendation"]
    assert recommendation["recommendation"] == "broaden_query_or_skip"
    assert recommendation["recommend_to_user"] is False
    assert recommendation["recommend_for_evidence"] is False
    assert recommendation["evidence_decision"] == "no_records_returned"
    from jpintel_mcp.api.evidence import _build_decision_insights

    insights = _build_decision_insights(gated)
    signals = {gap["signal"] for gap in insights["evidence_gaps"]}
    assert "records_blocked_by_license_gate" in signals
    assert "license_gate_follow_up" in {check["signal"] for check in insights["next_checks"]}


def test_evidence_license_gate_marks_fact_level_drop_reason() -> None:
    from jpintel_mcp.api.evidence import _gate_evidence_envelope

    envelope = {
        "records": [
            {
                "entity_id": "program:fact-level-blocked",
                "primary_name": "fact-level blocked fixture",
                "license": "pdl_v1.0",
                "source_url": "https://example.com/public",
                "facts": [
                    {
                        "field": "private_note",
                        "value": "must not export",
                        "source": {
                            "license": "proprietary",
                            "url": "https://example.com/private",
                        },
                    }
                ],
            }
        ],
        "quality": {"known_gaps": []},
    }

    gated, summary = _gate_evidence_envelope(envelope)

    assert gated["records"] == []
    assert summary["allowed_count"] == 0
    assert summary["blocked_count"] == 1
    assert summary["blocked_reasons"]["no_redistributable_facts"] == 1
    assert "records_blocked_by_license_gate" in gated["quality"]["known_gaps"]


def test_rest_json_license_gate_filters_mixed_license_facts(
    client: TestClient,
    fixture_db: Path,
) -> None:
    """JSON responses use the same fact-level license gate as CSV/MD."""
    con = sqlite3.connect(fixture_db)
    try:
        cur = con.execute(
            "INSERT INTO am_source(source_url, source_type, domain, content_hash, "
            "first_seen, last_verified, license) VALUES (?,?,?,?,?,?,?)",
            (
                "https://example.com/private-evidence",
                "secondary",
                "example.com",
                "sha256:private",
                "2026-05-03T00:00:00",
                "2026-05-03T00:00:00",
                "proprietary",
            ),
        )
        source_id = cur.lastrowid
        con.execute(
            "INSERT INTO am_entity_facts("
            "entity_id, field_name, field_value_text, field_kind, source_id, "
            "confirming_source_count) VALUES (?,?,?,?,?,?)",
            (
                "program:evp:p1",
                "private_note",
                "must not export",
                "text",
                source_id,
                1,
            ),
        )
        con.commit()

        r = client.get("/v1/evidence/packets/program/UNI-evp-p1")
        assert r.status_code == 200, r.text
        assert r.headers["X-License-Gate-Allowed"] == "1"
        assert r.headers["X-License-Gate-Blocked"] == "0"
        body = r.json()
        fields = {f["field"] for f in body["records"][0]["facts"]}
        assert "private_note" not in fields
        assert "must not export" not in r.text
        assert body["records"][0]["license"] in {"gov_standard_v2.0", "pdl_v1.0"}
        assert body["license_gate"]["allowed_count"] == 1
    finally:
        con.execute(
            "DELETE FROM am_entity_facts "
            "WHERE entity_id = 'program:evp:p1' AND field_name = 'private_note'"
        )
        con.execute(
            "DELETE FROM am_source WHERE source_url = ?", ("https://example.com/private-evidence",)
        )
        con.commit()
        con.close()


def test_evidence_license_gate_keeps_licensed_rules() -> None:
    from jpintel_mcp.api.evidence import _apply_license_gate

    envelope = {
        "records": [
            {
                "entity_id": "program:rules",
                "primary_name": "licensed rules fixture",
                "facts": [
                    {
                        "field": "name",
                        "value": "licensed rules fixture",
                        "source": {
                            "license": "gov_standard_v2.0",
                            "url": "https://example.go.jp/program",
                        },
                    }
                ],
                "rules": [
                    {
                        "rule_id": "keep",
                        "evidence_url": "https://example.go.jp/rule",
                        "license": "gov_standard_v2.0",
                    },
                    {
                        "rule_id": "drop",
                        "evidence_url": "https://example.com/private-rule",
                        "license": "proprietary",
                    },
                    {
                        "rule_id": "drop-mixed",
                        "evidence_url": "https://example.go.jp/mixed-rule",
                        "source_urls": [
                            "https://example.go.jp/mixed-rule",
                            "https://example.com/private-rule",
                        ],
                        "license_set": ["gov_standard_v2.0", "proprietary"],
                    },
                ],
            }
        ]
    }

    gated, summary = _apply_license_gate(envelope)

    assert gated["records"][0]["rules"] == [
        {
            "rule_id": "keep",
            "evidence_url": "https://example.go.jp/rule",
            "license": "gov_standard_v2.0",
        }
    ]
    assert summary["blocked_rules_count"] == 2


def test_rule_evidence_source_prefers_redistributable_url(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from jpintel_mcp.services.evidence_packet import EvidencePacketComposer

    composer = EvidencePacketComposer(
        jpintel_db=tmp_path / "jpintel.db",
        autonomath_db=tmp_path / "autonomath.db",
    )
    licenses = {
        "https://example.com/private-rule": "proprietary",
        "https://example.go.jp/public-rule": "gov_standard_v2.0",
    }
    monkeypatch.setattr(
        composer,
        "_source_license_for_url",
        lambda url: licenses.get(url),
    )

    evidence_url, license_name, allowed_urls = composer._rule_evidence_source(
        {
            "source_urls": [
                "https://example.com/private-rule",
                "https://example.go.jp/public-rule",
            ]
        }
    )

    assert evidence_url == "https://example.go.jp/public-rule"
    assert license_name == "gov_standard_v2.0"
    assert allowed_urls == ["https://example.go.jp/public-rule"]


def test_rest_get_evidence_packet_renderer_failure_does_not_bill(
    client: TestClient,
    paid_key: str,
    seeded_db: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed Evidence Packet export renderer must not create usage."""
    from fastapi.testclient import TestClient

    from jpintel_mcp.api import evidence as evidence_api

    def _boom(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("renderer boom")

    monkeypatch.setattr(evidence_api, "_dispatch_format", _boom)
    safe_client = TestClient(client.app, raise_server_exceptions=False)

    r = safe_client.get(
        "/v1/evidence/packets/program/UNI-evp-p1",
        params={"output_format": "csv"},
        headers={"X-API-Key": paid_key},
    )

    assert r.status_code == 500
    assert _usage_count(seeded_db, paid_key, "evidence.packet.get") == 0


def test_rest_post_evidence_packet_renderer_failure_does_not_bill(
    client: TestClient,
    paid_key: str,
    seeded_db: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed query export renderer must not create usage."""
    from fastapi.testclient import TestClient

    from jpintel_mcp.api import evidence as evidence_api

    def _boom(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("renderer boom")

    monkeypatch.setattr(evidence_api, "_dispatch_format", _boom)
    safe_client = TestClient(client.app, raise_server_exceptions=False)

    r = safe_client.post(
        "/v1/evidence/packets/query",
        params={"output_format": "md"},
        json={"query_text": "EVP", "limit": 1},
        headers={"X-API-Key": paid_key},
    )

    assert r.status_code == 500
    assert _usage_count(seeded_db, paid_key, "evidence.packet.query") == 0


@pytest.mark.parametrize(
    ("method", "path", "endpoint", "kwargs"),
    [
        (
            "get",
            "/v1/evidence/packets/program/UNI-evp-p1",
            "evidence.packet.get",
            {},
        ),
        (
            "get",
            "/v1/evidence/packets/program/UNI-evp-p1",
            "evidence.packet.get",
            {"params": {"output_format": "csv"}},
        ),
        (
            "get",
            "/v1/evidence/packets/program/UNI-evp-p1",
            "evidence.packet.get",
            {"params": {"output_format": "md"}},
        ),
        (
            "post",
            "/v1/evidence/packets/query",
            "evidence.packet.query",
            {"json": {"query_text": "EVP", "limit": 1}},
        ),
    ],
)
def test_rest_evidence_packet_final_metering_cap_failure_does_not_bill_or_seal(
    client: TestClient,
    paid_key: str,
    seeded_db: Path,
    monkeypatch: pytest.MonkeyPatch,
    method: str,
    path: str,
    endpoint: str,
    kwargs: dict[str, object],
) -> None:
    from jpintel_mcp.api.middleware import customer_cap

    monkeypatch.setattr(
        customer_cap,
        "metered_charge_within_cap",
        lambda *args, **kwargs: False,
    )
    request = getattr(client, method)

    r = request(path, headers={"X-API-Key": paid_key}, **kwargs)

    assert r.status_code == 503, r.text
    assert r.json()["detail"]["code"] == "billing_cap_final_check_failed"
    assert _usage_count(seeded_db, paid_key, endpoint) == 0
    assert _audit_seal_count(seeded_db, paid_key, endpoint) == 0


@pytest.mark.parametrize(
    ("method", "path", "endpoint", "kwargs"),
    [
        (
            "get",
            "/v1/evidence/packets/program/UNI-evp-p1",
            "evidence.packet.get",
            {},
        ),
        (
            "post",
            "/v1/evidence/packets/query",
            "evidence.packet.query",
            {"json": {"query_text": "EVP", "limit": 1}},
        ),
    ],
)
def test_rest_evidence_packet_audit_seal_persist_failure_does_not_bill_or_seal(
    client: TestClient,
    paid_key: str,
    seeded_db: Path,
    monkeypatch: pytest.MonkeyPatch,
    method: str,
    path: str,
    endpoint: str,
    kwargs: dict[str, object],
) -> None:
    import jpintel_mcp.api._audit_seal as seal_mod

    def _raise(*args: object, **kwargs: object) -> None:
        raise sqlite3.OperationalError("forced seal persist failure")

    monkeypatch.setattr(seal_mod, "persist_seal", _raise)
    request = getattr(client, method)

    response = request(path, headers={"X-API-Key": paid_key}, **kwargs)

    assert response.status_code == 503, response.text
    assert response.json()["detail"]["code"] == "audit_seal_persist_failed"
    assert _usage_count(seeded_db, paid_key, endpoint) == 0
    assert _audit_seal_count(seeded_db, paid_key, endpoint) == 0


# ---------------------------------------------------------------------------
# Cache hits (monkeypatch upstream count)
# ---------------------------------------------------------------------------


def test_compose_cache_hit_avoids_upstream_query(
    fixture_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A second identical call hits the cache instead of re-querying."""
    from jpintel_mcp.config import settings
    from jpintel_mcp.services import evidence_packet as _evp
    from jpintel_mcp.services.evidence_packet import EvidencePacketComposer

    _evp._reset_cache_for_tests()
    composer = EvidencePacketComposer(jpintel_db=settings.db_path, autonomath_db=fixture_db)

    # Counter wraps _fetch_facts_for_entity so we can assert it runs ONCE.
    call_count = {"n": 0}
    real_fetch = composer._fetch_facts_for_entity

    def _counting(*args, **kwargs):  # type: ignore[no-untyped-def]
        call_count["n"] += 1
        return real_fetch(*args, **kwargs)

    monkeypatch.setattr(composer, "_fetch_facts_for_entity", _counting)

    env1 = composer.compose_for_program("UNI-evp-p1")
    env2 = composer.compose_for_program("UNI-evp-p1")
    assert env1 is not None
    assert env2 is not None
    assert call_count["n"] == 1, f"expected single upstream call, got {call_count['n']}"
    # Cache hit yields identical envelope (same packet_id — cached object).
    assert env1["packet_id"] == env2["packet_id"]


# ---------------------------------------------------------------------------
# MCP-vs-REST envelope parity
# ---------------------------------------------------------------------------


def test_mcp_and_rest_emit_identical_envelopes(fixture_db: Path, client: TestClient) -> None:
    """The MCP tool and the REST endpoint emit identical packets for the
    same subject (modulo packet_id which is regenerated on the MCP side
    only when the cache is cold).
    """
    from jpintel_mcp.services import evidence_packet as _evp

    _evp._reset_cache_for_tests()

    rest_env = client.get("/v1/evidence/packets/program/UNI-evp-p1").json()

    from jpintel_mcp.mcp.autonomath_tools.evidence_packet_tools import (
        _impl_get_evidence_packet,
        _reset_composer,
    )

    _reset_composer()
    mcp_env = _impl_get_evidence_packet(subject_kind="program", subject_id="UNI-evp-p1")
    # Drop volatile fields + REST-only middleware decorations and compare
    # structure. `_meta` is appended by the AnonQuotaHeaderMiddleware /
    # ResponseSanitizer pipeline; the MCP tool returns the raw composer
    # envelope without those wrappings.
    for k in (
        "packet_id",
        "generated_at",
        "_meta",
        "conversion_cta",
        "decision_insights",
    ):
        rest_env.pop(k, None)
        mcp_env.pop(k, None)
    assert rest_env == mcp_env, (
        f"MCP and REST envelope drift (rest={list(rest_env.keys())}, mcp={list(mcp_env.keys())})"
    )


# ---------------------------------------------------------------------------
# Plan §4-A — API value signal acceptance tests (2026-05-03)
# ---------------------------------------------------------------------------


def test_evidence_value_block_present_and_shape(fixture_db: Path) -> None:
    """compose_for_program emits the plan §4-A `evidence_value` block."""
    from jpintel_mcp.config import settings
    from jpintel_mcp.services.evidence_packet import EvidencePacketComposer

    composer = EvidencePacketComposer(jpintel_db=settings.db_path, autonomath_db=fixture_db)
    env = composer.compose_for_program("UNI-evp-p1")
    assert env is not None
    ev = env.get("evidence_value")
    assert isinstance(ev, dict), "evidence_value block missing"
    for key in (
        "records_returned",
        "source_linked_records",
        "precomputed_records",
        "pdf_fact_refs",
        "known_gap_count",
        "fact_provenance_coverage_pct_avg",
        "web_search_performed_by_jpcite",
        "request_time_llm_call_performed",
    ):
        assert key in ev, f"evidence_value missing field: {key}"
    assert ev["records_returned"] == 1
    assert ev["source_linked_records"] == 1
    assert ev["precomputed_records"] >= 1
    assert ev["web_search_performed_by_jpcite"] is False
    assert ev["request_time_llm_call_performed"] is False


def test_pdf_pages_baseline_exposes_break_even_and_reduction_rate(fixture_db: Path) -> None:
    """pdf_pages baseline returns input_context_reduction_rate +
    break_even_source_tokens_estimate + provider_billing_not_guaranteed."""
    from jpintel_mcp.config import settings
    from jpintel_mcp.services.evidence_packet import EvidencePacketComposer

    composer = EvidencePacketComposer(jpintel_db=settings.db_path, autonomath_db=fixture_db)
    env = composer.compose_for_program(
        "UNI-evp-p1",
        include_compression=True,
        input_token_price_jpy_per_1m=300.0,
        source_tokens_basis="pdf_pages",
        source_pdf_pages=10,
    )
    assert env is not None
    compression = env["compression"]
    assert compression["provider_billing_not_guaranteed"] is True
    rate = compression["input_context_reduction_rate"]
    assert isinstance(rate, float) and 0.0 <= rate <= 1.0
    cost_savings = compression["cost_savings_estimate"]
    assert "break_even_source_tokens_estimate" in cost_savings
    assert isinstance(cost_savings["break_even_source_tokens_estimate"], int)
    assert (
        cost_savings["break_even_source_tokens_estimate"]
        == compression["packet_tokens_estimate"] + cost_savings["break_even_avoided_tokens"]
    )
    assert cost_savings["provider_billing_not_guaranteed"] is True
    assert cost_savings["jpcite_cost_jpy_ex_tax"] == 3


def test_no_baseline_recommends_evidence_but_not_cost(fixture_db: Path) -> None:
    """Plan §4-A acceptance: no baseline → recommend_for_evidence may be true,
    recommend_for_cost_savings=false, decision=needs_caller_baseline."""
    from jpintel_mcp.config import settings
    from jpintel_mcp.services.evidence_packet import EvidencePacketComposer

    composer = EvidencePacketComposer(jpintel_db=settings.db_path, autonomath_db=fixture_db)
    env = composer.compose_for_program("UNI-evp-p1")
    assert env is not None
    rec = env["agent_recommendation"]
    assert rec["recommend_for_evidence"] is True
    assert rec["evidence_decision"] == "supported_by_source_linked_records"
    assert rec["recommend_for_cost_savings"] is False
    assert rec["cost_savings_decision"] == "needs_caller_baseline"
    assert isinstance(rec["value_reasons"], list)
    assert "source_linked_records_returned" in rec["value_reasons"]


def test_zero_records_disables_all_recommendations(fixture_db: Path) -> None:
    """records_returned=0 → recommend_to_user, recommend_for_evidence,
    recommend_for_cost_savings all false."""
    from jpintel_mcp.config import settings
    from jpintel_mcp.services.evidence_packet import EvidencePacketComposer

    composer = EvidencePacketComposer(jpintel_db=settings.db_path, autonomath_db=fixture_db)
    env = composer.compose_for_query("zz-no-program-match", limit=10)
    assert env["records"] == []
    rec = env["agent_recommendation"]
    assert rec["recommend_to_user"] is False
    assert rec["recommend_for_evidence"] is False
    assert rec["evidence_decision"] == "no_records_returned"
    assert rec["recommend_for_cost_savings"] is False
    assert rec["value_reasons"] == []
    ev = env["evidence_value"]
    assert ev["records_returned"] == 0
    assert ev["source_linked_records"] == 0


# ---------------------------------------------------------------------------
# 0 LLM imports guard
# ---------------------------------------------------------------------------


def test_evidence_packet_module_has_zero_llm_imports() -> None:
    """The composer module must import nothing LLM-related.

    The repo-wide guard ``tests/test_no_llm_in_production.py`` already
    enforces this for src/, but we re-assert here so a regression breaks
    the targeted suite for fast feedback.
    """
    import ast
    from pathlib import Path

    repo = Path(__file__).resolve().parents[1]
    paths = [
        repo / "src" / "jpintel_mcp" / "services" / "evidence_packet.py",
        repo / "src" / "jpintel_mcp" / "api" / "evidence.py",
        repo / "src" / "jpintel_mcp" / "mcp" / "autonomath_tools" / "evidence_packet_tools.py",
    ]
    forbidden = {
        "anthropic",
        "openai",
        "claude_agent_sdk",
        "google.generativeai",
    }
    for p in paths:
        src = p.read_text(encoding="utf-8")
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    head = alias.name.split(".")[0]
                    assert head not in forbidden, f"forbidden LLM import in {p}: {alias.name}"
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                head = mod.split(".")[0]
                assert head not in forbidden, f"forbidden LLM import in {p}: {mod}"
                assert mod != "google.generativeai", f"forbidden LLM import in {p}: {mod}"
