"""Tests for the Source Manifest endpoint + MCP tool.

Exercises the Evidence Graph 90-day deliverable surfaces:

  - REST: ``GET /v1/source_manifest/{program_id}`` (mounted via
    ``api/main.py`` with ``AnonIpLimitDep``).
  - MCP:  ``jpintel_mcp.mcp.autonomath_tools.source_manifest_tools.get_source_manifest``.

Fixture posture
---------------
The endpoint reads exclusively from autonomath.db. We construct a
miniature autonomath.db inside the test's ``tmp_path`` (the live 10 GB
DB is unsuitable as a per-test fixture), seeded with three programs:

  * ``P1`` — 5 facts, each with a populated ``source_id`` (full
    fact-level provenance, coverage 100%).
  * ``P2`` — 1 fact with source_id, plus 1 fact without (sparse mix).
  * ``P3`` — 0 facts with source_id; only ``primary_source_url`` from
    the program-row mirror (jpi_programs).

The autonomath path is overridden via the ``AUTONOMATH_DB_PATH``
environment variable. Per-test ``monkeypatch`` (NOT ``monkeypatch.setenv``
inside a fixture that re-imports modules) keeps the swap local.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from jpintel_mcp.api.deps import hash_api_key

if TYPE_CHECKING:
    from collections.abc import Iterator

    from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Fixture autonomath.db builder
# ---------------------------------------------------------------------------


_PROGRAM_FACT_FIELDS = [
    "amount_max_yen",
    "amount_min_yen",
    "deadline",
    "subsidy_rate",
    "eligibility_summary",
]


def _build_fixture_autonomath_db(path: Path) -> None:
    """Write the minimum-schema autonomath.db needed to exercise the
    source_manifest endpoint + MCP tool.

    Tables created:
      * am_source         — 4 source rows across 3 publishers + 3 licenses.
      * am_entities       — 3 program entities (P1/P2/P3).
      * am_entity_facts   — fact rows with mixed source_id population
        per the docstring posture.
      * am_entity_source  — entity-level rollup so the summary block has
        non-zero source_count even on programs with sparse facts.
      * jpi_programs      — primary_name / source_url mirror.
      * entity_id_map     — UNI- ↔ canonical_id link table (one row per
        program so we exercise the unified_id resolution path).

    The view (migration 115) is created at the end so the endpoint sees
    it. We DO NOT apply schema_migrations bookkeeping — the test does not
    reuse the production migration runner.
    """
    if path.exists():
        path.unlink()
    con = sqlite3.connect(path)
    try:
        con.executescript(
            """
            CREATE TABLE am_source (
                id                   INTEGER PRIMARY KEY AUTOINCREMENT,
                source_url           TEXT NOT NULL UNIQUE,
                source_type          TEXT NOT NULL DEFAULT 'primary',
                domain               TEXT,
                is_pdf               INTEGER NOT NULL DEFAULT 0,
                content_hash         TEXT,
                first_seen           TEXT NOT NULL DEFAULT (datetime('now')),
                last_verified        TEXT,
                promoted_at          TEXT NOT NULL DEFAULT (datetime('now')),
                canonical_status     TEXT NOT NULL DEFAULT 'active',
                license              TEXT
            );
            CREATE TABLE am_entities (
                canonical_id         TEXT PRIMARY KEY,
                primary_name         TEXT NOT NULL,
                record_kind          TEXT,
                source_url           TEXT,
                fetched_at           TEXT,
                confidence           REAL
            );
            CREATE TABLE am_entity_facts (
                id                   INTEGER PRIMARY KEY AUTOINCREMENT,
                entity_id            TEXT NOT NULL,
                field_name           TEXT NOT NULL,
                field_value_text     TEXT,
                field_value_json     TEXT,
                field_value_numeric  REAL,
                field_kind           TEXT NOT NULL DEFAULT 'text',
                unit                 TEXT,
                source_url           TEXT,
                created_at           TEXT NOT NULL DEFAULT (datetime('now')),
                source_id            INTEGER REFERENCES am_source(id),
                valid_from           TEXT,
                valid_until          TEXT,
                confirming_source_count INTEGER DEFAULT 1
            );
            CREATE TABLE am_entity_source (
                entity_id            TEXT NOT NULL,
                source_id            INTEGER NOT NULL,
                role                 TEXT NOT NULL DEFAULT '',
                source_field         TEXT,
                promoted_at          TEXT NOT NULL DEFAULT (datetime('now')),
                PRIMARY KEY (entity_id, source_id, role)
            );
            CREATE TABLE jpi_programs (
                unified_id           TEXT PRIMARY KEY,
                primary_name         TEXT NOT NULL,
                authority_name       TEXT,
                prefecture           TEXT,
                tier                 TEXT,
                source_url           TEXT,
                source_fetched_at    TEXT,
                updated_at           TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE TABLE entity_id_map (
                jpi_unified_id       TEXT NOT NULL,
                am_canonical_id      TEXT NOT NULL,
                match_method         TEXT NOT NULL,
                confidence           REAL NOT NULL,
                matched_at           TEXT NOT NULL DEFAULT (datetime('now')),
                PRIMARY KEY (jpi_unified_id, am_canonical_id)
            );
            """
        )

        # 4 source rows: 3 publishers, mix of licenses.
        sources: list[tuple[str, str, str, str, str]] = [
            # url, type, domain, license, content_hash
            (
                "https://www.maff.go.jp/policy/p1.html",
                "primary",
                "www.maff.go.jp",
                "gov_standard_v2.0",
                "sha256:p1aaa",
            ),
            (
                "https://www.meti.go.jp/policy/p1.pdf",
                "secondary",
                "www.meti.go.jp",
                "gov_standard_v2.0",
                "sha256:p1bbb",
            ),
            (
                "https://www.jfc.go.jp/p2.html",
                "primary",
                "www.jfc.go.jp",
                "pdl_v1.0",
                "sha256:p2ccc",
            ),
            (
                "https://hojyokin-portal.jp/p3-aggregator.html",
                "reference",
                "hojyokin-portal.jp",
                "proprietary",
                "sha256:p3ddd",
            ),
            (
                "https://aggregator.example/p4-primary.html",
                "primary",
                "aggregator.example",
                "proprietary",
                "sha256:p4eee",
            ),
            (
                "https://www.meti.go.jp/policy/p4.pdf",
                "reference",
                "www.meti.go.jp",
                "gov_standard_v2.0",
                "sha256:p4fff",
            ),
            (
                "https://aggregator.example/p5-primary.html",
                "primary",
                "aggregator.example",
                "proprietary",
                "sha256:p5ggg",
            ),
        ]
        con.executemany(
            "INSERT INTO am_source(source_url, source_type, domain, license, "
            "content_hash, first_seen) VALUES (?,?,?,?,?,?)",
            [
                (
                    *row,
                    f"2026-04-{20 + idx:02d}T00:00:00",
                )
                for idx, row in enumerate(sources)
            ],
        )

        # Program entities. Canonical IDs use the production-shaped
        # 'program:<topic>:<...>' form so the resolver path 2 fires.
        entities = [
            (
                "program:test:p1",
                "テスト P1 補助金",
                "program",
                "https://www.maff.go.jp/policy/p1.html",
                "2026-04-20T00:00:00",
                1.0,
            ),
            (
                "program:test:p2",
                "テスト P2 補助金",
                "program",
                "https://www.jfc.go.jp/p2.html",
                "2026-04-22T00:00:00",
                1.0,
            ),
            (
                "program:test:p3",
                "テスト P3 補助金",
                "program",
                "https://www.example.go.jp/p3.html",
                "2026-04-23T00:00:00",
                1.0,
            ),
            (
                "program:test:p4",
                "テスト P4 補助金",
                "program",
                "https://aggregator.example/p4-primary.html",
                "2026-04-24T00:00:00",
                1.0,
            ),
            (
                "program:test:p5",
                "テスト P5 補助金",
                "program",
                "https://aggregator.example/p5-primary.html",
                "2026-04-26T00:00:00",
                1.0,
            ),
        ]
        con.executemany(
            "INSERT INTO am_entities("
            "  canonical_id, primary_name, record_kind, source_url, "
            "  fetched_at, confidence"
            ") VALUES (?,?,?,?,?,?)",
            entities,
        )

        # P1 — 5 facts, all with source_id populated (5 fields = 5 facts).
        # source_id alternates between 1 and 2 to exercise the cross-source
        # license_set rollup.
        for i, fname in enumerate(_PROGRAM_FACT_FIELDS):
            con.execute(
                "INSERT INTO am_entity_facts("
                "  entity_id, field_name, field_value_text, field_kind, source_id"
                ") VALUES (?,?,?,?,?)",
                ("program:test:p1", fname, f"P1-value-{i}", "text", (i % 2) + 1),
            )

        # P2 — 1 fact with source_id (sparse) + 1 fact WITHOUT source_id
        # so coverage_pct is 0.5.
        con.execute(
            "INSERT INTO am_entity_facts("
            "  entity_id, field_name, field_value_text, field_kind, source_id"
            ") VALUES (?,?,?,?,?)",
            ("program:test:p2", "amount_max_yen", "P2-pinned", "text", 3),
        )
        con.execute(
            "INSERT INTO am_entity_facts("
            "  entity_id, field_name, field_value_text, field_kind, source_id"
            ") VALUES (?,?,?,?,?)",
            ("program:test:p2", "deadline", "P2-loose", "text", None),
        )

        # P4 — primary URL is proprietary, but another linked fact/source is
        # redistributable. The manifest must redact the primary URL based on
        # the exact primary-source license, not the entity-wide license set.
        con.execute(
            "INSERT INTO am_entity_facts("
            "  entity_id, field_name, field_value_text, field_kind, source_id"
            ") VALUES (?,?,?,?,?)",
            ("program:test:p4", "amount_max_yen", "P4-pinned", "text", 6),
        )

        # P5 — primary URL is proprietary but is not present in the entity
        # rollup. A separate redistributable fact source must not make the
        # manifest claim the whole primary record is redistributable.
        con.execute(
            "INSERT INTO am_entity_facts("
            "  entity_id, field_name, field_value_text, field_kind, source_id"
            ") VALUES (?,?,?,?,?)",
            ("program:test:p5", "amount_max_yen", "P5-pinned", "text", 6),
        )

        # P3 — zero facts. Endpoint must degrade to primary_source_url
        # from jpi_programs. We do NOT add an am_entity_source row for
        # P3 either — the summary block stays at zero.

        # am_entity_source rollup. P1 gets 2 entity-level sources, P2 gets
        # 1, P3 gets 0. This is the dense signal that exists in production
        # (~280k rows) so the summary block is non-empty even when facts
        # are sparse.
        con.executemany(
            "INSERT INTO am_entity_source(entity_id, source_id, role, "
            "promoted_at) VALUES (?,?,?,?)",
            [
                ("program:test:p1", 1, "primary_source", "2026-04-20T00:00:00"),
                ("program:test:p1", 2, "pdf_url", "2026-04-21T00:00:00"),
                ("program:test:p2", 3, "primary_source", "2026-04-22T00:00:00"),
                ("program:test:p2", 4, "reference", "2026-04-23T00:00:00"),
                ("program:test:p4", 5, "primary_source", "2026-04-24T00:00:00"),
                ("program:test:p4", 6, "reference", "2026-04-25T00:00:00"),
            ],
        )

        # jpi_programs mirror — used for the primary_name / primary_source
        # _url fallback when callers pass a UNI-... id.
        con.executemany(
            "INSERT INTO jpi_programs(unified_id, primary_name, "
            "authority_name, prefecture, tier, source_url, "
            "source_fetched_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
            [
                (
                    "UNI-test-p1",
                    "テスト P1 補助金",
                    "農林水産省",
                    "東京都",
                    "S",
                    "https://www.maff.go.jp/policy/p1.html",
                    "2026-04-20T00:00:00",
                    "2026-04-20T00:00:00",
                ),
                (
                    "UNI-test-p2",
                    "テスト P2 補助金",
                    "日本政策金融公庫",
                    "大阪府",
                    "A",
                    "https://www.jfc.go.jp/p2.html",
                    "2026-04-22T00:00:00",
                    "2026-04-22T00:00:00",
                ),
                (
                    "UNI-test-p3",
                    "テスト P3 補助金",
                    "経済産業省",
                    "京都府",
                    "B",
                    "https://www.example.go.jp/p3.html",
                    "2026-04-23T00:00:00",
                    "2026-04-23T00:00:00",
                ),
                (
                    "UNI-test-p4",
                    "テスト P4 補助金",
                    "経済産業省",
                    "福岡県",
                    "A",
                    "https://aggregator.example/p4-primary.html",
                    "2026-04-24T00:00:00",
                    "2026-04-24T00:00:00",
                ),
                (
                    "NO-LINK-P4",
                    "テスト No Link 補助金",
                    "経済産業省",
                    "北海道",
                    "C",
                    "https://www.example.go.jp/no-link.html",
                    "2026-04-25T00:00:00",
                    "2026-04-25T00:00:00",
                ),
                (
                    "UNI-test-p5",
                    "テスト P5 補助金",
                    "経済産業省",
                    "愛知県",
                    "A",
                    "https://aggregator.example/p5-primary.html",
                    "2026-04-26T00:00:00",
                    "2026-04-26T00:00:00",
                ),
            ],
        )
        con.executemany(
            "INSERT INTO entity_id_map(jpi_unified_id, am_canonical_id, "
            "match_method, confidence) VALUES (?,?,?,?)",
            [
                ("UNI-test-p1", "program:test:p1", "exact_name", 1.0),
                ("UNI-test-p2", "program:test:p2", "exact_name", 1.0),
                ("UNI-test-p3", "program:test:p3", "exact_name", 1.0),
                ("UNI-test-p4", "program:test:p4", "exact_name", 1.0),
                ("UNI-test-p5", "program:test:p5", "exact_name", 1.0),
            ],
        )

        # Apply migration 115 (the view) to this fixture DB.
        repo_root = Path(__file__).resolve().parents[1]
        sql = (repo_root / "scripts" / "migrations" / "115_source_manifest_view.sql").read_text(
            encoding="utf-8"
        )
        con.executescript(sql)
        con.commit()
    finally:
        con.close()


# ---------------------------------------------------------------------------
# Pytest fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def fixture_db(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Build the miniature autonomath.db once per test module."""
    p = tmp_path_factory.mktemp("source_manifest") / "autonomath.db"
    _build_fixture_autonomath_db(p)
    return p


@pytest.fixture(autouse=True)
def _override_autonomath_path(fixture_db: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Point both the REST handler and the MCP tool's connection helper
    at the fixture autonomath.db.

    The REST handler reads ``AUTONOMATH_DB_PATH`` lazily (per-request) so
    setenv is sufficient there. The MCP ``connect_autonomath`` helper
    caches the path module-level via ``AUTONOMATH_DB_PATH`` AND keeps a
    thread-local connection — we must reset both.
    """
    monkeypatch.setenv("AUTONOMATH_DB_PATH", str(fixture_db))

    # Reset the MCP per-thread cached connection (different DB this
    # session). We close the prior conn so the next call re-opens against
    # the fixture DB.
    if "jpintel_mcp.mcp.autonomath_tools.db" in sys.modules:
        from jpintel_mcp.mcp.autonomath_tools import db as _am_db

        _am_db.close_all()
        monkeypatch.setattr(_am_db, "AUTONOMATH_DB_PATH", fixture_db)
    yield
    if "jpintel_mcp.mcp.autonomath_tools.db" in sys.modules:
        from jpintel_mcp.mcp.autonomath_tools import db as _am_db

        _am_db.close_all()


# ---------------------------------------------------------------------------
# Test 1: Full per-fact provenance (P1)
# ---------------------------------------------------------------------------


def test_get_source_manifest_full_provenance(client: TestClient) -> None:
    """P1 has 5 facts each with source_id populated → coverage = 1.0,
    fact_provenance returns 5 entries.
    """
    r = client.get("/v1/source_manifest/program:test:p1")
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["program_id"] == "program:test:p1"
    assert body["primary_name"] == "テスト P1 補助金"
    assert isinstance(body["fact_provenance"], list)
    assert len(body["fact_provenance"]) == 5, (
        f"expected 5 fact_provenance rows, got {len(body['fact_provenance'])}"
    )
    # All five known field names round-trip.
    fnames = {row["field_name"] for row in body["fact_provenance"]}
    assert fnames == set(_PROGRAM_FACT_FIELDS)

    # coverage_pct == 1.0 because every fact has source_id set.
    assert body["fact_provenance_coverage_pct"] == 1.0

    # Each entry carries the contracted shape.
    for row in body["fact_provenance"]:
        assert "field_name" in row
        assert "source_id" in row
        assert "source_url" in row
        assert "publisher" in row
        assert "fetched_at" in row
        assert "license" in row
        assert "checksum" in row

    # Summary block reflects the entity-level rollup AS WELL AS the
    # per-fact links — distinct sources collapse so source_count is the
    # union (sources 1 + 2 referenced by both layers = 2 distinct).
    summary = body["summary"]
    assert summary["source_count"] == 2
    assert summary["unique_publishers"] == 2
    assert "gov_standard_v2.0" in summary["license_set"]
    assert sorted(summary["field_paths_covered"]) == sorted(_PROGRAM_FACT_FIELDS)

    # Primary license short-form maps gov_standard_v2.0 → gov_standard.
    assert body["primary_license"] == "gov_standard"
    assert body["license_posture"] == "redistributable"
    assert body["redistribution_allowed"] is True


# ---------------------------------------------------------------------------
# Test 2: Sparse / no per-fact provenance (P3)
# ---------------------------------------------------------------------------


def test_get_source_manifest_no_provenance_p3(client: TestClient) -> None:
    """P3 has zero facts. fact_provenance is empty, coverage_pct is 0.0,
    and primary_source_url remains visible as metadata while redistribution
    license is marked unverified.
    """
    r = client.get("/v1/source_manifest/UNI-test-p3")
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["program_id"] == "UNI-test-p3"
    assert body["primary_name"] == "テスト P3 補助金"
    assert body["primary_source_url"] == "https://www.example.go.jp/p3.html"
    assert body["primary_source_url_license_unverified"] is True
    assert body["fact_provenance"] == []
    assert body["fact_provenance_coverage_pct"] == 0.0

    # Summary stays empty since P3 has no am_entity_source rollup either.
    summary = body["summary"]
    assert summary["source_count"] == 0
    assert summary["unique_publishers"] == 0
    assert summary["field_paths_covered"] == []

    # Even on an empty manifest the disclaimer is required.
    assert "_disclaimer" in body


# ---------------------------------------------------------------------------
# Test 3: Unknown program_id returns 404
# ---------------------------------------------------------------------------


def test_get_source_manifest_unknown_returns_404(client: TestClient) -> None:
    r = client.get("/v1/source_manifest/UNI-does-not-exist")
    assert r.status_code == 404
    body = r.json()
    assert body["program_id"] == "UNI-does-not-exist"
    # 404 body still carries the disclaimer envelope.
    assert "_disclaimer" in body


def test_paid_final_cap_failure_returns_503_without_usage_event(
    client: TestClient,
    seeded_db: Path,
    paid_key: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    key_hash = hash_api_key(paid_key)
    endpoint = "source_manifest.get"

    def _reject_final_cap(*_args: object, **_kwargs: object) -> tuple[bool, bool]:
        return False, False

    import jpintel_mcp.api.deps as deps

    monkeypatch.setattr(deps, "_metered_cap_final_check", _reject_final_cap)

    conn = sqlite3.connect(seeded_db)
    try:
        (before,) = conn.execute(
            "SELECT COUNT(*) FROM usage_events WHERE key_hash = ? AND endpoint = ?",
            (key_hash, endpoint),
        ).fetchone()
    finally:
        conn.close()

    r = client.get(
        "/v1/source_manifest/program:test:p1",
        headers={"X-API-Key": paid_key},
    )

    assert r.status_code == 503, r.text
    assert r.json()["detail"]["code"] == "billing_cap_final_check_failed"

    conn = sqlite3.connect(seeded_db)
    try:
        (after,) = conn.execute(
            "SELECT COUNT(*) FROM usage_events WHERE key_hash = ? AND endpoint = ?",
            (key_hash, endpoint),
        ).fetchone()
    finally:
        conn.close()
    assert after == before


# ---------------------------------------------------------------------------
# Test 4: Disclaimer is always present
# ---------------------------------------------------------------------------


def test_response_includes_disclaimer(client: TestClient) -> None:
    """All three programs (full / sparse / empty) must carry _disclaimer."""
    for pid in ("program:test:p1", "program:test:p2", "UNI-test-p3"):
        r = client.get(f"/v1/source_manifest/{pid}")
        assert r.status_code == 200, r.text
        body = r.json()
        assert "_disclaimer" in body, f"missing _disclaimer on {pid}"
        assert "manifest reflects per-fact provenance" in body["_disclaimer"]


# ---------------------------------------------------------------------------
# Test 5: Anonymous quota gate (using existing AnonIpLimitDep wiring)
# ---------------------------------------------------------------------------


def test_anon_within_quota_returns_200(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Anonymous caller within the cap gets 200 + remaining-quota header."""
    from jpintel_mcp.config import settings

    monkeypatch.setattr(settings, "anon_rate_limit_per_day", 5)
    r = client.get(
        "/v1/source_manifest/program:test:p1",
        headers={"x-forwarded-for": "198.51.100.91"},
    )
    assert r.status_code == 200, r.text
    assert r.headers.get("X-Anon-Quota-Remaining") is not None


def test_anon_over_quota_returns_429(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Second anon hit on a 1/month cap MUST 429."""
    from jpintel_mcp.api import anon_limit as _anon_limit
    from jpintel_mcp.config import settings

    monkeypatch.setattr(settings, "anon_rate_limit_per_day", 1)
    monkeypatch.setattr(_anon_limit.settings, "anon_rate_limit_per_day", 1)
    ip = "198.51.100.92"
    r1 = client.get(
        "/v1/source_manifest/program:test:p1",
        headers={"x-forwarded-for": ip},
    )
    assert r1.status_code == 200, r1.text
    r2 = client.get(
        "/v1/source_manifest/program:test:p1",
        headers={"x-forwarded-for": ip},
    )
    assert r2.status_code == 429


# ---------------------------------------------------------------------------
# Test 6: MCP tool returns the same envelope as REST
# ---------------------------------------------------------------------------


def test_mcp_tool_returns_same_envelope_as_rest(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """MCP and REST surfaces share the composer; the same program_id
    should yield identical envelopes (modulo HTTP-only metadata).
    """
    # Set the MCP gate so the autonomath tool import path is loaded once.
    monkeypatch.setenv("AUTONOMATH_ENABLED", "1")

    # Lazy import after env is set so the tool registers under the right
    # AUTONOMATH_DB_PATH (the autouse fixture already pointed it at the
    # fixture DB).
    from jpintel_mcp.mcp.autonomath_tools.source_manifest_tools import (
        get_source_manifest as mcp_get_source_manifest,
    )

    pid = "program:test:p1"
    rest = client.get(f"/v1/source_manifest/{pid}").json()
    mcp = mcp_get_source_manifest(program_id=pid)

    # Field-by-field comparison on the contracted envelope keys. Skip
    # auxiliary annotations (_total_facts is identical between paths
    # but defensive-equal is robust to future divergences).
    for key in (
        "program_id",
        "primary_name",
        "primary_source_url",
        "primary_license",
        "fact_provenance_coverage_pct",
        "fact_provenance",
        "summary",
    ):
        assert mcp.get(key) == rest.get(key), (
            f"MCP/REST divergence on {key!r}: mcp={mcp.get(key)!r} rest={rest.get(key)!r}"
        )
    assert "_disclaimer" in mcp


# ---------------------------------------------------------------------------
# Aux: P2 sparse coverage path is covered implicitly above; explicit assert.
# ---------------------------------------------------------------------------


def test_p2_sparse_coverage(client: TestClient) -> None:
    """P2 has 2 facts and only redistributable fact provenance is surfaced.

    Not in the headline 6 tests but cheap to assert and pins a regression
    in the coverage_pct calculation.
    """
    r = client.get("/v1/source_manifest/program:test:p2")
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["fact_provenance"]) == 1
    assert body["fact_provenance_coverage_pct"] == 0.5
    assert body["primary_license"] == "pdl_v1.0"
    assert body["license_posture"] == "mixed_restricted"
    assert body["redistribution_allowed"] is False
    assert body["primary_source_url"] == "https://www.jfc.go.jp/p2.html"
    assert body["license_gate"]["blocked_entity_source_licenses"] == ["proprietary"]


def test_primary_source_redaction_uses_exact_primary_license(client: TestClient) -> None:
    """Entity-wide redistributable sources must not keep a proprietary primary URL."""
    r = client.get("/v1/source_manifest/UNI-test-p4")
    assert r.status_code == 200, r.text
    body = r.json()

    assert "primary_source_url" not in body
    assert body["primary_source_url_redacted"] is True
    assert body["primary_license"] == "proprietary"
    assert body["license_posture"] == "mixed_restricted"
    assert body["redistribution_allowed"] is False
    assert len(body["fact_provenance"]) == 1
    assert body["fact_provenance"][0]["source_url"] == "https://www.meti.go.jp/policy/p4.pdf"
    assert body["license_gate"]["blocked_entity_source_licenses"] == ["proprietary"]


def test_primary_source_license_affects_posture_when_missing_from_rollup(
    client: TestClient,
) -> None:
    """A proprietary primary URL must not be masked by redistributable fact links."""
    r = client.get("/v1/source_manifest/UNI-test-p5")
    assert r.status_code == 200, r.text
    body = r.json()

    assert "primary_source_url" not in body
    assert body["primary_source_url_redacted"] is True
    assert body["primary_license"] == "proprietary"
    assert body["license_posture"] == "mixed_restricted"
    assert body["redistribution_allowed"] is False
    assert body["summary"]["license_set"] == ["gov_standard_v2.0"]


def test_no_entity_link_redacts_unknown_primary_source(client: TestClient) -> None:
    """Metadata-only fallback keeps URL visible but marks license unverified."""
    r = client.get("/v1/source_manifest/NO-LINK-P4")
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["program_id"] == "NO-LINK-P4"
    assert body["primary_source_url"] == "https://www.example.go.jp/no-link.html"
    assert body["primary_source_url_license_unverified"] is True
    assert body["primary_license"] == "unknown"
    assert body["fact_provenance"] == []
    assert body["summary"]["source_count"] == 0
