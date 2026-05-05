"""Tests for the multi-axis Discover Related endpoint + MCP tool.

Plan reference: ``GET /v1/discover/related/{entity_id}`` and MCP
``discover_related(entity_id, k)``.

Fixture posture
---------------

Both surfaces read from autonomath.db (5-axis composer) plus jpintel.db
(via_law_ref axis only). We construct a miniature autonomath.db inside
``tmp_path`` carrying:

  * ``am_entities`` — 1 seed program (UNI-disc-p1 → program:disc:p1) plus
    4 neighbour programs reachable along each axis.
  * ``entity_id_map`` — UNI- ↔ canonical link for the seed and the law-ref
    neighbour so axis builders can resolve either input form.
  * ``am_funding_stack_empirical`` — co-adoption pair (seed, p2) with
    co_adoption_count=12.
  * ``am_entity_density_score`` — 3 program rows with adjacent ranks.
  * ``am_5hop_graph`` — hop=2 walk seed → p4 → p5_via.
  * ``program_law_refs`` (jpintel.db, seeded by conftest seeded_db) — we
    inject 2 rows here for the via_law_ref axis.

The vector axis is asserted as ``[]`` rather than populated rows — the
fixture intentionally omits ``am_entities_vec_*`` virtual tables (vec0
extension is not loaded under pytest), and the implementation must
fail-open to an empty list, not 5xx.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator

    from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Fixture autonomath.db builder
# ---------------------------------------------------------------------------


def _build_fixture_autonomath_db(path: Path) -> None:
    """Build the miniature autonomath.db needed by the discover composer."""
    if path.exists():
        path.unlink()
    con = sqlite3.connect(path)
    try:
        con.executescript(
            """
            CREATE TABLE am_entities (
                canonical_id TEXT PRIMARY KEY,
                primary_name TEXT NOT NULL,
                record_kind  TEXT,
                source_url   TEXT,
                fetched_at   TEXT,
                confidence   REAL
            );
            CREATE TABLE entity_id_map (
                jpi_unified_id   TEXT NOT NULL,
                am_canonical_id  TEXT NOT NULL,
                match_method     TEXT NOT NULL,
                confidence       REAL NOT NULL,
                PRIMARY KEY (jpi_unified_id, am_canonical_id)
            );
            CREATE TABLE am_funding_stack_empirical (
                program_a_id        TEXT NOT NULL,
                program_b_id        TEXT NOT NULL,
                co_adoption_count   INTEGER NOT NULL DEFAULT 0,
                mean_days_between   INTEGER,
                compat_matrix_says  TEXT,
                conflict_flag       INTEGER NOT NULL DEFAULT 0,
                generated_at        TEXT NOT NULL DEFAULT (datetime('now')),
                PRIMARY KEY (program_a_id, program_b_id),
                CHECK (program_a_id < program_b_id)
            );
            CREATE TABLE am_entity_density_score (
                entity_id           TEXT PRIMARY KEY,
                record_kind         TEXT,
                verification_count  INTEGER DEFAULT 0,
                edge_count          INTEGER DEFAULT 0,
                fact_count          INTEGER DEFAULT 0,
                alias_count         INTEGER DEFAULT 0,
                adoption_count      INTEGER DEFAULT 0,
                enforcement_count   INTEGER DEFAULT 0,
                density_score       REAL,
                density_rank        INTEGER,
                last_updated        TEXT DEFAULT (datetime('now'))
            );
            CREATE TABLE am_5hop_graph (
                start_entity_id  TEXT NOT NULL,
                hop              INTEGER NOT NULL CHECK (hop BETWEEN 1 AND 5),
                end_entity_id    TEXT NOT NULL,
                path             TEXT NOT NULL,
                edge_kinds       TEXT,
                PRIMARY KEY (start_entity_id, end_entity_id, hop)
            );
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
            """
        )
        # Seed entities. Seed (p1) plus 4 neighbours that show up across
        # the various axes.
        con.executemany(
            "INSERT INTO am_entities("
            "canonical_id, primary_name, record_kind, source_url, fetched_at, confidence"
            ") VALUES (?,?,?,?,?,?)",
            [
                (
                    "program:disc:p1",
                    "Discover seed P1",
                    "program",
                    "https://www.example.go.jp/p1.html",
                    "2026-04-25T00:00:00",
                    1.0,
                ),
                (
                    "program:disc:p2",
                    "Discover P2 (co-adopt)",
                    "program",
                    "https://www.example.go.jp/p2.html",
                    "2026-04-25T00:00:00",
                    1.0,
                ),
                (
                    "program:disc:p3",
                    "Discover P3 (density-adj)",
                    "program",
                    "https://www.example.go.jp/p3.html",
                    "2026-04-25T00:00:00",
                    1.0,
                ),
                (
                    "program:disc:p4",
                    "Discover P4 (5hop)",
                    "program",
                    "https://www.example.go.jp/p4.html",
                    "2026-04-25T00:00:00",
                    1.0,
                ),
                (
                    "program:disc:p5_via",
                    "Discover P5 (5hop via)",
                    "program",
                    "https://www.example.go.jp/p5.html",
                    "2026-04-25T00:00:00",
                    1.0,
                ),
            ],
        )
        # entity_id_map — UNI- ↔ canonical for the seed plus its neighbour
        # so we can exercise either input shape.
        con.executemany(
            "INSERT INTO entity_id_map(jpi_unified_id, am_canonical_id, "
            "match_method, confidence) VALUES (?,?,?,?)",
            [
                ("UNI-disc-p1", "program:disc:p1", "exact_name", 1.0),
                ("UNI-disc-p2", "program:disc:p2", "exact_name", 1.0),
                ("UNI-disc-p3", "program:disc:p3", "exact_name", 1.0),
            ],
        )
        # am_funding_stack_empirical — one (seed, p2) co-adoption pair.
        # Normalize ordering per the CHECK constraint (a < b).
        con.execute(
            "INSERT INTO am_funding_stack_empirical("
            "program_a_id, program_b_id, co_adoption_count, "
            "mean_days_between, compat_matrix_says, conflict_flag) "
            "VALUES (?,?,?,?,?,?)",
            (
                "program:disc:p1",
                "program:disc:p2",
                12,
                30,
                "compatible",
                0,
            ),
        )
        # am_entity_density_score — three program rows with adjacent ranks.
        # Seed at rank 100; p3 at 99 (closest); p4 at 110 (further);
        # p5_via at 90 (further still).
        con.executemany(
            "INSERT INTO am_entity_density_score("
            "entity_id, record_kind, density_score, density_rank) "
            "VALUES (?,?,?,?)",
            [
                ("program:disc:p1", "program", 5.0, 100),
                ("program:disc:p3", "program", 4.9, 99),
                ("program:disc:p4", "program", 4.5, 110),
                ("program:disc:p5_via", "program", 5.5, 90),
            ],
        )
        # am_5hop_graph — hop=2 destination from the seed.
        con.executemany(
            "INSERT INTO am_5hop_graph("
            "start_entity_id, hop, end_entity_id, path, edge_kinds"
            ") VALUES (?,?,?,?,?)",
            [
                (
                    "program:disc:p1",
                    2,
                    "program:disc:p4",
                    '["program:disc:p1","program:disc:p5_via"]',
                    '["references_law","applies_to_law"]',
                ),
                (
                    "program:disc:p1",
                    1,
                    "program:disc:p5_via",
                    "[]",
                    '["references_law"]',
                ),
            ],
        )
        # am_source — populate so corpus_snapshot_id derives from a real
        # MAX(last_verified) instead of the today-fallback.
        con.execute(
            "INSERT INTO am_source(source_url, source_type, domain, "
            "content_hash, first_seen, last_verified, license) "
            "VALUES (?,?,?,?,?,?,?)",
            (
                "https://www.example.go.jp/p1.html",
                "primary",
                "www.example.go.jp",
                "sha256:disc",
                "2026-04-25T00:00:00",
                "2026-04-28T00:00:00",
                "gov_standard_v2.0",
            ),
        )
        con.commit()
    finally:
        con.close()


def _seed_program_law_refs(jpintel_db_path: Path) -> None:
    """Seed program_law_refs in jpintel.db so the via_law_ref axis fires.

    The conftest ``seeded_db`` fixture already created the schema; we add
    rows here. UNI-test-s-1 is the seed; we add another program (UNI-disc-
    plr2) so it shows up as a related row.
    """
    con = sqlite3.connect(jpintel_db_path)
    try:
        # First, add a partner program that doesn't exist yet — programs
        # has NOT NULL on primary_name and updated_at so include both.
        con.execute(
            "INSERT OR IGNORE INTO programs("
            "  unified_id, primary_name, tier, program_kind, excluded, updated_at"
            ") VALUES (?,?,?,?,?,?)",
            (
                "UNI-disc-plr2",
                "Discover law_ref partner",
                "S",
                "補助金",
                0,
                "2026-04-25T00:00:00",
            ),
        )
        # Both programs cite the same law via program_law_refs.
        # Add the law row first per the FK on laws.unified_id. Schema:
        # unified_id, law_number, law_title, law_type, revision_status,
        # source_url, fetched_at, updated_at are all NOT NULL.
        con.execute(
            "INSERT OR IGNORE INTO laws("
            "  unified_id, law_number, law_title, law_type, "
            "  revision_status, source_url, fetched_at, updated_at"
            ") VALUES (?,?,?,?,?,?,?,?)",
            (
                "LAW-disc-shared",
                "令和8年法律第99号",
                "Discover Shared Law",
                "act",
                "current",
                "https://laws.e-gov.go.jp/disc-shared",
                "2026-04-25T00:00:00",
                "2026-04-25T00:00:00",
            ),
        )
        con.executemany(
            "INSERT OR IGNORE INTO program_law_refs("
            "  program_unified_id, law_unified_id, ref_kind, "
            "  article_citation, source_url, fetched_at, confidence"
            ") VALUES (?,?,?,?,?,?,?)",
            [
                (
                    "UNI-test-s-1",
                    "LAW-disc-shared",
                    "authority",
                    "",
                    "https://www.example.go.jp/seed-ref",
                    "2026-04-25T00:00:00",
                    1.0,
                ),
                (
                    "UNI-disc-plr2",
                    "LAW-disc-shared",
                    "authority",
                    "",
                    "https://www.example.go.jp/partner-ref",
                    "2026-04-25T00:00:00",
                    1.0,
                ),
            ],
        )
        con.commit()
    finally:
        con.close()


# ---------------------------------------------------------------------------
# Pytest fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def fixture_db(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Build the miniature autonomath.db once per test module."""
    p = tmp_path_factory.mktemp("discover_related") / "autonomath.db"
    _build_fixture_autonomath_db(p)
    return p


@pytest.fixture(autouse=True)
def _override_paths(
    fixture_db: Path, tmp_db_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[None]:
    """Point the discover composer at the fixture autonomath.db AND seed
    program_law_refs in the conftest jpintel.db so the via_law_ref axis
    has a non-empty path on the seed (UNI-test-s-1).
    """
    monkeypatch.setenv("AUTONOMATH_DB_PATH", str(fixture_db))
    from jpintel_mcp.config import settings

    monkeypatch.setattr(settings, "autonomath_db_path", fixture_db)

    # Reset the corpus_snapshot cache so the test sees the fixture's
    # MAX(last_verified) value, not whatever was cached from an earlier
    # test session.
    if "jpintel_mcp.api._audit_seal" in sys.modules:
        from jpintel_mcp.api import _audit_seal as _seal

        _seal._reset_corpus_snapshot_cache_for_tests()

    # Reset the MCP per-thread cached connection so tools see the fixture.
    if "jpintel_mcp.mcp.autonomath_tools.db" in sys.modules:
        from jpintel_mcp.mcp.autonomath_tools import db as _am_db

        _am_db.close_all()
        monkeypatch.setattr(_am_db, "AUTONOMATH_DB_PATH", fixture_db)

    _seed_program_law_refs(tmp_db_path)
    yield
    if "jpintel_mcp.mcp.autonomath_tools.db" in sys.modules:
        from jpintel_mcp.mcp.autonomath_tools import db as _am_db

        _am_db.close_all()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_returns_5_axis(client: TestClient) -> None:
    """REST endpoint surfaces all 5 axes (each may be empty but the keys
    must always be present so an LLM can deterministically destructure
    the response).
    """
    r = client.get("/v1/discover/related/UNI-test-s-1?k=20")
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["entity_id"] == "UNI-test-s-1"
    related = body["related"]
    expected_axes = {
        "via_law_ref",
        "via_vector",
        "via_co_adoption",
        "via_density_neighbors",
        "via_5hop",
    }
    assert set(related.keys()) == expected_axes
    for axis_name, rows in related.items():
        assert isinstance(rows, list), f"axis {axis_name} must be a list"
        for row in rows:
            assert isinstance(row, dict)
            assert row.get("axis") == axis_name

    # via_law_ref should populate from the seeded jpintel.db rows
    # (UNI-test-s-1 ↔ UNI-disc-plr2 via LAW-disc-shared).
    law_ref_ids = {r["entity_id"] for r in related["via_law_ref"]}
    assert "UNI-disc-plr2" in law_ref_ids, (
        "via_law_ref should include the partner program seeded in jpintel.db"
    )

    # Per-axis cap is hard at 5 even when k > 5.
    for axis_name, rows in related.items():
        assert len(rows) <= 5, f"axis {axis_name} exceeds per-axis cap"


def test_envelope_complies(client: TestClient, paid_key: str) -> None:
    """Every paid 2xx response carries audit_seal + corpus_snapshot_id +
    _disclaimer (Evidence Packet contract). The seal also exposes a
    ``corpus_snapshot_id`` that matches the top-level value.
    """
    r = client.get(
        "/v1/discover/related/UNI-test-s-1?k=10",
        headers={"X-API-Key": paid_key},
    )
    assert r.status_code == 200, r.text
    body = r.json()

    # Required envelope keys.
    assert body["_disclaimer"], "envelope must carry _disclaimer"
    assert body["_billing_unit"] == 1
    snapshot_id = body["corpus_snapshot_id"]
    assert isinstance(snapshot_id, str) and snapshot_id.startswith("corpus-")

    # audit_seal block (paid path only).
    seal = body.get("audit_seal")
    assert isinstance(seal, dict), "audit_seal must be present on paid responses"
    assert seal.get("seal_id", "").startswith("seal_")
    assert seal["corpus_snapshot_id"] == snapshot_id
    assert seal.get("hmac"), "audit_seal must carry hmac"
    assert seal.get("call_id"), "audit_seal must carry call_id"


def test_mcp_rest_parity(client: TestClient, fixture_db: Path) -> None:
    """The MCP tool and the REST endpoint emit structurally identical 5-axis
    related blocks for the same seed (modulo the audit_seal which is REST-
    only since the MCP path doesn't carry an api_key_hash).
    """
    rest_body = client.get("/v1/discover/related/UNI-test-s-1?k=20").json()

    from jpintel_mcp.mcp.autonomath_tools.discover import _impl_discover_related

    mcp_body = _impl_discover_related(entity_id="UNI-test-s-1", k=20)

    # Both must surface the same 5 axes with identical row counts on
    # every axis. (Vec axis is empty on both since vec0 is not loaded.)
    assert set(rest_body["related"].keys()) == set(mcp_body["related"].keys())
    for axis_name in rest_body["related"]:
        rest_rows = rest_body["related"][axis_name]
        mcp_rows = mcp_body["related"][axis_name]
        assert len(rest_rows) == len(mcp_rows), (
            f"axis {axis_name} drift: REST={len(rest_rows)} MCP={len(mcp_rows)}"
        )
        # Compare the entity_id sets — the row order is determined by SQL
        # ORDER BY which is identical between the two paths.
        rest_ids = [r.get("entity_id") for r in rest_rows]
        mcp_ids = [r.get("entity_id") for r in mcp_rows]
        assert rest_ids == mcp_ids, (
            f"axis {axis_name} entity_id ordering drift: "
            f"REST={rest_ids} MCP={mcp_ids}"
        )

    # Both share the same disclaimer + billing_unit + corpus_snapshot_id.
    assert rest_body["_disclaimer"] == mcp_body["_disclaimer"]
    assert rest_body["_billing_unit"] == mcp_body["_billing_unit"] == 1
    assert rest_body["corpus_snapshot_id"] == mcp_body["corpus_snapshot_id"]
