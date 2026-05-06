"""Tests for the V4 Phase 4 provenance MCP tools.

Covers ``get_provenance`` + ``get_provenance_for_fact`` exposed at:

  - MCP: ``jpintel_mcp.mcp.autonomath_tools.provenance_tools``
  - REST: ``GET /v1/am/provenance/{entity_id}`` + ``GET /v1/am/provenance/fact/{fact_id}``

Required field checks per spec:
  - source_id present (when entity has any source)
  - license present (closed enum: pdl_v1.0 / cc_by_4.0 / gov_standard_v2.0 /
    public_domain / proprietary / unknown)
  - fetched_at format (ISO 8601 — date or timestamp)
"""

from __future__ import annotations

import os
import re
import sqlite3
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_DB = _REPO_ROOT / "autonomath.db"
_DEFAULT_GRAPH = _REPO_ROOT / "graph.sqlite"

_DB_PATH = Path(os.environ.get("AUTONOMATH_DB_PATH", str(_DEFAULT_DB)))
_GRAPH_PATH = Path(os.environ.get("AUTONOMATH_GRAPH_DB_PATH", str(_DEFAULT_GRAPH)))

if not _DB_PATH.exists() or not _GRAPH_PATH.exists():
    pytest.skip(
        f"autonomath.db ({_DB_PATH}) or graph.sqlite ({_GRAPH_PATH}) "
        "not present; skipping provenance suite.",
        allow_module_level=True,
    )

os.environ["AUTONOMATH_DB_PATH"] = str(_DB_PATH)
os.environ["AUTONOMATH_GRAPH_DB_PATH"] = str(_GRAPH_PATH)
os.environ.setdefault("AUTONOMATH_ENABLED", "1")

from jpintel_mcp.mcp import server  # noqa: F401, E402
from jpintel_mcp.mcp.autonomath_tools.provenance_tools import (  # noqa: E402
    get_provenance,
    get_provenance_for_fact,
)


# ---------------------------------------------------------------------------
# Fixtures: discover real entities + fact ids for happy-path tests.
# ---------------------------------------------------------------------------


# Closed license enum per migration 049 trigger.
_VALID_LICENSES = {
    "pdl_v1.0",
    "cc_by_4.0",
    "gov_standard_v2.0",
    "public_domain",
    "proprietary",
    "unknown",
    None,  # NULL allowed (2 rows currently NULL per CLAUDE.md)
}

# ISO-8601 — accept date-only or full timestamp variants the DB carries.
_ISO8601_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}"
    r"([ T]\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?)?$"
)


@pytest.fixture(scope="module")
def entity_with_sources() -> str:
    """A canonical_id that has at least one row in am_entity_source."""
    con = sqlite3.connect(_DB_PATH)
    try:
        row = con.execute("SELECT entity_id FROM am_entity_source LIMIT 1").fetchone()
        if not row:
            pytest.skip("am_entity_source is empty")
        return row[0]
    finally:
        con.close()


@pytest.fixture(scope="module")
def fact_with_source_id() -> int:
    """A fact id whose source_id is non-NULL (post-2026-04-25 ingest)."""
    con = sqlite3.connect(_DB_PATH)
    try:
        row = con.execute(
            "SELECT id FROM am_entity_facts WHERE source_id IS NOT NULL LIMIT 1"
        ).fetchone()
        if not row:
            pytest.skip("no facts with non-NULL source_id present")
        return int(row[0])
    finally:
        con.close()


@pytest.fixture(scope="module")
def fact_without_source_id() -> int:
    """A fact id with source_id=NULL — must trigger fallback path."""
    con = sqlite3.connect(_DB_PATH)
    try:
        row = con.execute(
            "SELECT id FROM am_entity_facts WHERE source_id IS NULL LIMIT 1"
        ).fetchone()
        if not row:
            pytest.skip("no facts with NULL source_id present")
        return int(row[0])
    finally:
        con.close()


def _has_nested_error(res: dict, code: str) -> bool:
    err = res.get("error")
    return isinstance(err, dict) and err.get("code") == code


# ---------------------------------------------------------------------------
# 1. get_provenance — entity-level
# ---------------------------------------------------------------------------


def test_get_provenance_happy_returns_sources_with_required_fields(
    entity_with_sources: str,
):
    res = get_provenance(entity_id=entity_with_sources)
    assert res["entity_id"] == entity_with_sources
    assert isinstance(res.get("sources"), list)
    assert isinstance(res.get("license_summary"), dict)
    assert "total_sources" in res
    assert res["total_sources"] == len(res["sources"])

    assert res["sources"], "expected at least one source row for the fixture entity"
    src = res["sources"][0]

    # Required field shape per spec
    assert src.get("source_id") is not None
    assert "license" in src
    assert src["license"] in _VALID_LICENSES, f"license {src['license']!r} outside closed enum"
    # fetched_at (am_entity_source.promoted_at) — when present, must be ISO8601.
    fetched = src.get("fetched_at")
    if fetched is not None:
        assert _ISO8601_RE.match(str(fetched)), f"fetched_at not ISO 8601: {fetched!r}"
    # source_url + role + domain are also expected.
    assert "source_url" in src
    assert "role" in src
    assert "domain" in src


def test_get_provenance_unknown_entity_returns_seed_not_found():
    res = get_provenance(entity_id="program:bogus:9999999999")
    assert _has_nested_error(res, "seed_not_found")


def test_get_provenance_empty_entity_id_returns_missing_required_arg():
    res = get_provenance(entity_id="   ")
    assert _has_nested_error(res, "missing_required_arg")


def test_get_provenance_include_facts_returns_facts_array(entity_with_sources: str):
    res = get_provenance(
        entity_id=entity_with_sources,
        include_facts=True,
        fact_limit=5,
    )
    assert "facts" in res
    assert isinstance(res["facts"], list)
    assert "total_facts" in res
    # Either rows came back, or the documented hint surfaces a clear fallback.
    if not res["facts"]:
        assert "facts_hint" in res


def test_get_provenance_license_summary_only_contains_known_keys(
    entity_with_sources: str,
):
    res = get_provenance(entity_id=entity_with_sources)
    summary = res["license_summary"]
    # 'unknown_null' is the explicit bucket for NULL license rows.
    allowed = (_VALID_LICENSES - {None}) | {"unknown_null"}
    for key in summary:
        assert key in allowed, f"license_summary key {key!r} outside allowed enum"


# ---------------------------------------------------------------------------
# 2. get_provenance_for_fact — single fact
# ---------------------------------------------------------------------------


def test_get_provenance_for_fact_happy_with_source_id(fact_with_source_id: int):
    res = get_provenance_for_fact(fact_id=fact_with_source_id)
    assert res["fact_id"] == fact_with_source_id
    assert res["fallback"] is False
    src = res["source"]
    # All three required fields per spec
    assert src.get("source_id") is not None
    assert "license" in src
    assert src["license"] in _VALID_LICENSES
    assert "license_summary" in res
    # Optional fetched_at — usually only on entity-level. For per-fact, the
    # row inherits via JOIN. Still must satisfy ISO format if present.
    fetched = src.get("fetched_at")
    if fetched is not None:
        assert _ISO8601_RE.match(str(fetched))


def test_get_provenance_for_fact_fallback_when_source_id_null(
    fact_without_source_id: int,
):
    res = get_provenance_for_fact(fact_id=fact_without_source_id)
    assert res["fact_id"] == fact_without_source_id
    assert res["fallback"] is True
    # fallback_sources may be empty (entity has no sources either) but the key
    # must exist + the hint must be set.
    assert "fallback_sources" in res
    assert isinstance(res["fallback_sources"], list)
    assert "fallback_hint" in res
    assert "license_summary" in res


def test_get_provenance_for_fact_unknown_id_returns_seed_not_found():
    res = get_provenance_for_fact(fact_id=999999999999)
    assert _has_nested_error(res, "seed_not_found")


# ---------------------------------------------------------------------------
# 3. REST endpoint contracts
# ---------------------------------------------------------------------------


def test_rest_get_provenance_unknown_entity_returns_seed_not_found(client):
    r = client.get("/v1/am/provenance/program:bogus:9999")
    assert r.status_code == 200
    body = r.json()
    err = body.get("error")
    assert isinstance(err, dict)
    assert err.get("code") == "seed_not_found"


def test_rest_get_provenance_for_fact_unknown_id(client):
    r = client.get("/v1/am/provenance/fact/999999999999")
    assert r.status_code == 200
    body = r.json()
    err = body.get("error")
    assert isinstance(err, dict)
    assert err.get("code") == "seed_not_found"


def test_rest_get_provenance_happy(client, entity_with_sources: str):
    r = client.get(f"/v1/am/provenance/{entity_with_sources}")
    assert r.status_code == 200
    body = r.json()
    assert body.get("entity_id") == entity_with_sources
    assert "sources" in body
    assert "license_summary" in body
