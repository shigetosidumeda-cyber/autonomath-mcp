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
def _override_paths(fixture_db: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Point both REST + MCP composers at the fixture autonomath.db, and
    reset their module-level singletons + cache.
    """
    monkeypatch.setenv("AUTONOMATH_DB_PATH", str(fixture_db))
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
        "verification_status": "verified",
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


def test_rest_get_evidence_packet_json(client: TestClient) -> None:
    """GET /v1/evidence/packets/program/{id} returns the JSON envelope."""
    r = client.get("/v1/evidence/packets/program/UNI-evp-p1")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["api_version"] == "v1"
    assert body["records"][0]["primary_name"] == "EVP テスト P1 補助金"


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
    compression = r.json()["compression"]
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
    compression = r.json()["compression"]
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
    for k in ("packet_id", "generated_at", "_meta"):
        rest_env.pop(k, None)
        mcp_env.pop(k, None)
    assert rest_env == mcp_env, (
        f"MCP and REST envelope drift (rest={list(rest_env.keys())}, mcp={list(mcp_env.keys())})"
    )


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
