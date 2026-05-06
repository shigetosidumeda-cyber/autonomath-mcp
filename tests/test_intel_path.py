"""Tests for POST /v1/intel/path — 5-hop graph reasoning path endpoint.

Plan reference: Wave 31-2 composite ``POST /v1/intel/path`` returning
the bidirectional-BFS shortest reasoning chain between two entities
over am_5hop_graph + am_citation_network + am_id_bridge.

Fixture posture
---------------

We build a miniature autonomath.db inside ``tmp_path`` carrying:

  * ``am_entities`` — 5 entities representing a (program → law →
    judgment) chain plus an unrelated standalone entity for the
    not_found case.
  * ``am_id_bridge`` — UNI ↔ canonical_id rows for the program node
    so the resolver can normalise either input form.
  * ``am_5hop_graph`` — hop=1 edges program → law and law → judgment
    + a direct program → law alternative path so the test can assert
    on the alternative_paths list.
  * ``am_citation_network`` — the law cites a sibling judgment to
    exercise the second substrate harvester.
  * ``am_law_article`` — title for the law node so name resolution
    can fall through to the law-specific table.
  * ``am_source`` — one row so corpus_snapshot_id derives from a real
    MAX(last_verified) instead of the sentinel fallback.
"""

from __future__ import annotations

import sqlite3
import sys
from typing import TYPE_CHECKING

import pytest

from jpintel_mcp.api.deps import hash_api_key

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Fixture autonomath.db builder
# ---------------------------------------------------------------------------


def _build_fixture_autonomath_db(path: Path) -> None:
    """Build the miniature autonomath.db needed by the path composer."""
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
            CREATE TABLE am_id_bridge (
                id_a         TEXT NOT NULL,
                id_b         TEXT NOT NULL,
                bridge_kind  TEXT NOT NULL DEFAULT 'exact',
                confidence   REAL NOT NULL DEFAULT 1.0,
                created_at   TEXT NOT NULL DEFAULT (datetime('now')),
                PRIMARY KEY (id_a, id_b)
            );
            CREATE TABLE entity_id_map (
                jpi_unified_id   TEXT NOT NULL,
                am_canonical_id  TEXT NOT NULL,
                match_method     TEXT NOT NULL,
                confidence       REAL NOT NULL,
                PRIMARY KEY (jpi_unified_id, am_canonical_id)
            );
            CREATE TABLE am_5hop_graph (
                start_entity_id  TEXT NOT NULL,
                hop              INTEGER NOT NULL CHECK (hop BETWEEN 1 AND 5),
                end_entity_id    TEXT NOT NULL,
                path             TEXT NOT NULL,
                edge_kinds       TEXT,
                PRIMARY KEY (start_entity_id, end_entity_id, hop)
            );
            CREATE TABLE am_citation_network (
                citing_entity_id TEXT NOT NULL,
                citing_kind      TEXT NOT NULL DEFAULT 'law',
                cited_entity_id  TEXT NOT NULL,
                cited_kind       TEXT NOT NULL DEFAULT 'law',
                citation_count   INTEGER NOT NULL DEFAULT 1,
                computed_at      TEXT NOT NULL DEFAULT (datetime('now')),
                PRIMARY KEY (citing_entity_id, cited_entity_id)
            );
            CREATE TABLE am_law_article (
                law_canonical_id TEXT NOT NULL,
                article_no       TEXT,
                article_title    TEXT,
                body             TEXT
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

        # Seed entities — 1 program → 1 law → 1 judgment chain plus a
        # parallel law to exercise alternative paths and an unrelated
        # corporate entity for the not_found case.
        con.executemany(
            "INSERT INTO am_entities("
            "canonical_id, primary_name, record_kind, source_url, "
            "fetched_at, confidence) VALUES (?,?,?,?,?,?)",
            [
                (
                    "program:path:p1",
                    "Path seed Program",
                    "program",
                    "https://www.example.go.jp/path/p1",
                    "2026-04-25T00:00:00",
                    1.0,
                ),
                (
                    "law:path:l1",
                    "Path Linking Law",
                    "law",
                    "https://laws.e-gov.go.jp/path/l1",
                    "2026-04-25T00:00:00",
                    1.0,
                ),
                (
                    "law:path:l2",
                    "Path Alt Law",
                    "law",
                    "https://laws.e-gov.go.jp/path/l2",
                    "2026-04-25T00:00:00",
                    1.0,
                ),
                (
                    "court_decision:path:j1",
                    "Path Judgment J1",
                    "court_decision",
                    "https://example.courts.go.jp/path/j1",
                    "2026-04-25T00:00:00",
                    1.0,
                ),
                (
                    "corporate_entity:path:isolated",
                    "Isolated Corp",
                    "corporate_entity",
                    None,
                    "2026-04-25T00:00:00",
                    1.0,
                ),
            ],
        )

        # am_id_bridge — UNI ↔ canonical for the program seed (covers the
        # UNI-prefix input shape).
        con.execute(
            "INSERT INTO am_id_bridge(id_a, id_b, bridge_kind, confidence) VALUES (?,?,?,?)",
            ("UNI-path-p1", "program:path:p1", "exact", 1.0),
        )

        # 5hop edges — symmetric so bidirectional BFS can stitch:
        #   program:p1 → law:l1, law:l1 → court:j1, plus alt program:p1 →
        #   law:l2 → court:j1 (alternate path of the same length).
        con.executemany(
            "INSERT INTO am_5hop_graph("
            "start_entity_id, hop, end_entity_id, path, edge_kinds"
            ") VALUES (?,?,?,?,?)",
            [
                (
                    "program:path:p1",
                    1,
                    "law:path:l1",
                    "[]",
                    '["applies_to"]',
                ),
                (
                    "law:path:l1",
                    1,
                    "program:path:p1",
                    "[]",
                    '["applies_to"]',
                ),
                (
                    "law:path:l1",
                    1,
                    "court_decision:path:j1",
                    "[]",
                    '["cites"]',
                ),
                (
                    "court_decision:path:j1",
                    1,
                    "law:path:l1",
                    "[]",
                    '["cites"]',
                ),
                (
                    "program:path:p1",
                    1,
                    "law:path:l2",
                    "[]",
                    '["applies_to"]',
                ),
                (
                    "law:path:l2",
                    1,
                    "program:path:p1",
                    "[]",
                    '["applies_to"]',
                ),
                (
                    "law:path:l2",
                    1,
                    "court_decision:path:j1",
                    "[]",
                    '["cites"]',
                ),
                (
                    "court_decision:path:j1",
                    1,
                    "law:path:l2",
                    "[]",
                    '["cites"]',
                ),
            ],
        )

        # am_citation_network — extra cite edge so the citation harvester
        # also has a row to surface (law cites another law).
        con.execute(
            "INSERT INTO am_citation_network("
            "citing_entity_id, citing_kind, cited_entity_id, cited_kind, "
            "citation_count) VALUES (?,?,?,?,?)",
            ("law:path:l1", "law", "law:path:l2", "law", 7),
        )

        # am_law_article — name fallback for law nodes.
        con.executemany(
            "INSERT INTO am_law_article("
            "law_canonical_id, article_no, article_title, body) VALUES (?,?,?,?)",
            [
                ("law:path:l1", "1", "Article 1 of Path Linking Law", "..."),
                ("law:path:l2", "1", "Article 1 of Path Alt Law", "..."),
            ],
        )

        # am_source — populate so corpus_snapshot_id derives from a real
        # MAX(last_verified) value.
        con.execute(
            "INSERT INTO am_source(source_url, source_type, domain, "
            "content_hash, first_seen, last_verified, license) "
            "VALUES (?,?,?,?,?,?,?)",
            (
                "https://www.example.go.jp/path/p1",
                "primary",
                "www.example.go.jp",
                "sha256:path",
                "2026-04-25T00:00:00",
                "2026-04-28T00:00:00",
                "gov_standard_v2.0",
            ),
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
    p = tmp_path_factory.mktemp("intel_path") / "autonomath.db"
    _build_fixture_autonomath_db(p)
    return p


@pytest.fixture(autouse=True)
def _override_paths(fixture_db: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Point the path composer at the fixture autonomath.db."""
    monkeypatch.setenv("AUTONOMATH_DB_PATH", str(fixture_db))
    from jpintel_mcp.config import settings

    monkeypatch.setattr(settings, "autonomath_db_path", fixture_db)

    if "jpintel_mcp.api._audit_seal" in sys.modules:
        from jpintel_mcp.api import _audit_seal as _seal

        if hasattr(_seal, "_reset_corpus_snapshot_cache_for_tests"):
            _seal._reset_corpus_snapshot_cache_for_tests()
    yield


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_direct_one_hop_path(client: TestClient) -> None:
    """Direct 1-hop path: program → law via am_5hop_graph."""
    r = client.post(
        "/v1/intel/path",
        json={
            "from_entity": {"type": "program", "id": "program:path:p1"},
            "to_entity": {"type": "law", "id": "law:path:l1"},
            "max_hops": 5,
            "relation_filter": [],
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["found"] is True, body
    assert body["shortest_path_length"] == 1
    # Two unique vertices on the shortest path; alternative paths may add more.
    assert {n["entity_id"] for n in body["nodes"]} >= {
        "program:path:p1",
        "law:path:l1",
    }
    assert len(body["edges"]) == 1
    edge = body["edges"][0]
    src_idx = edge["from_idx"]
    dst_idx = edge["to_idx"]
    assert body["nodes"][src_idx]["entity_id"] == "program:path:p1"
    assert body["nodes"][dst_idx]["entity_id"] == "law:path:l1"
    # Evidence carries the substrate.
    assert edge["evidence"]["table"] in {"am_5hop_graph", "am_citation_network"}
    # Disclaimer + billing are present.
    assert body["_disclaimer"]
    assert body["_billing_unit"] == 1


def test_two_hop_path_program_to_judgment(client: TestClient) -> None:
    """2-hop path program → law → judgment. The fixture has TWO laws that
    bridge program ↔ judgment so we should also see ≥1 alternative path.
    """
    r = client.post(
        "/v1/intel/path",
        json={
            "from_entity": {"type": "program", "id": "program:path:p1"},
            "to_entity": {
                "type": "court_decision",
                "id": "court_decision:path:j1",
            },
            "max_hops": 5,
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["found"] is True
    assert body["shortest_path_length"] == 2
    edge_count = len(body["edges"])
    assert edge_count == 2, body["edges"]
    # The alternative_paths list should surface the parallel law → judgment
    # route (program → law:l2 → judgment) when the primary chose law:l1.
    assert isinstance(body["alternative_paths"], list)
    # Alternates are stored as index-into-nodes lists.
    for ap in body["alternative_paths"]:
        assert isinstance(ap, list)
        assert all(isinstance(i, int) for i in ap)


def test_path_uni_id_resolution(client: TestClient) -> None:
    """UNI-prefix input for the program seed is normalised via am_id_bridge."""
    r = client.post(
        "/v1/intel/path",
        json={
            "from_entity": {"type": "program", "id": "UNI-path-p1"},
            "to_entity": {"type": "law", "id": "law:path:l1"},
            "max_hops": 3,
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["found"] is True
    assert body["data_quality"]["resolved_from"] == "program:path:p1"


def test_not_found_path(client: TestClient) -> None:
    """No edges connect the two entities → found=false envelope."""
    r = client.post(
        "/v1/intel/path",
        json={
            "from_entity": {"type": "program", "id": "program:path:p1"},
            "to_entity": {
                "type": "corporate_entity",
                "id": "corporate_entity:path:isolated",
            },
            "max_hops": 3,
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["found"] is False
    assert body["shortest_path_length"] is None
    assert body["nodes"] == []
    assert body["edges"] == []
    assert body["alternative_paths"] == []


def test_relation_filter_drops_path(client: TestClient) -> None:
    """relation_filter that excludes the only available relation yields
    found=false even though the entities are physically connected.
    """
    r = client.post(
        "/v1/intel/path",
        json={
            "from_entity": {"type": "program", "id": "program:path:p1"},
            "to_entity": {"type": "law", "id": "law:path:l1"},
            "max_hops": 5,
            # Only allow 'amends' edges — none exist in our fixture.
            "relation_filter": ["amends"],
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["found"] is False
    assert body["relation_filter"] == ["amends"]


def test_relation_filter_keeps_path(client: TestClient) -> None:
    """relation_filter that matches the actual edge (applies_to) preserves
    the 1-hop program → law path.
    """
    r = client.post(
        "/v1/intel/path",
        json={
            "from_entity": {"type": "program", "id": "program:path:p1"},
            "to_entity": {"type": "law", "id": "law:path:l1"},
            "max_hops": 5,
            "relation_filter": ["applies_to"],
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["found"] is True
    assert body["shortest_path_length"] == 1
    assert body["edges"][0]["relation"] == "applies_to"


def test_max_hops_validation(client: TestClient) -> None:
    """max_hops outside [1, 7] is rejected with 422."""
    bad = client.post(
        "/v1/intel/path",
        json={
            "from_entity": {"type": "program", "id": "program:path:p1"},
            "to_entity": {"type": "law", "id": "law:path:l1"},
            "max_hops": 0,
        },
    )
    assert bad.status_code == 422
    too_big = client.post(
        "/v1/intel/path",
        json={
            "from_entity": {"type": "program", "id": "program:path:p1"},
            "to_entity": {"type": "law", "id": "law:path:l1"},
            "max_hops": 8,
        },
    )
    assert too_big.status_code == 422


def test_paid_final_cap_failure_returns_503_without_usage_event(
    client: TestClient,
    seeded_db: Path,
    paid_key: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Final cap rejection must fail closed, not return unmetered 200."""
    key_hash = hash_api_key(paid_key)
    endpoint = "intel.path"

    def usage_count() -> int:
        conn = sqlite3.connect(seeded_db)
        try:
            (count,) = conn.execute(
                "SELECT COUNT(*) FROM usage_events WHERE key_hash = ? AND endpoint = ?",
                (key_hash, endpoint),
            ).fetchone()
            return int(count)
        finally:
            conn.close()

    def _reject_final_cap(*_args: object, **_kwargs: object) -> tuple[bool, bool]:
        return False, False

    import jpintel_mcp.api.deps as deps

    monkeypatch.setattr(deps, "_metered_cap_final_check", _reject_final_cap)

    before = usage_count()
    r = client.post(
        "/v1/intel/path",
        headers={"X-API-Key": paid_key},
        json={
            "from_entity": {"type": "program", "id": "program:path:p1"},
            "to_entity": {"type": "law", "id": "law:path:l1"},
            "max_hops": 5,
        },
    )

    assert r.status_code == 503, r.text
    assert r.json()["detail"]["code"] == "billing_cap_final_check_failed"
    assert usage_count() == before
