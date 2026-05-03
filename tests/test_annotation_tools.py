"""Smoke + envelope-shape tests for the V4 Phase 4 annotation MCP tool.

Covers ``get_annotations`` exposed at:

  - MCP: ``jpintel_mcp.mcp.autonomath_tools.annotation_tools.get_annotations``
  - REST: ``GET /v1/am/annotations/{entity_id}``  (api/autonomath.py)

The public tool never returns ``visibility='internal'`` or ``visibility='private'``
rows. The currently ingested annotation rows are internal, so an entity that has
rows in the table still returns an empty public envelope.

Skips module-wide if autonomath.db / graph.sqlite are missing — same convention
as test_autonomath_tools.py.
"""

from __future__ import annotations

import os
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
        "not present; skipping annotation tool suite.",
        allow_module_level=True,
    )

os.environ["AUTONOMATH_DB_PATH"] = str(_DB_PATH)
os.environ["AUTONOMATH_GRAPH_DB_PATH"] = str(_GRAPH_PATH)
os.environ.setdefault("AUTONOMATH_ENABLED", "1")

# server import first to break the autonomath_tools<->server circular import.
from jpintel_mcp.mcp import server  # noqa: F401, E402
from jpintel_mcp.mcp.autonomath_tools.annotation_tools import (  # noqa: E402
    _PUBLIC_KIND_LABELS,
    get_annotations,
)

# ---------------------------------------------------------------------------
# Fixtures: pluck a real entity_id that has annotation rows.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def annotated_entity_id() -> str:
    """A canonical_id that has at least one row in am_entity_annotation."""
    con = sqlite3.connect(_DB_PATH)
    try:
        row = con.execute("SELECT entity_id FROM am_entity_annotation LIMIT 1").fetchone()
        if not row:
            pytest.skip("am_entity_annotation is empty — cannot test happy path")
        return row[0]
    finally:
        con.close()


@pytest.fixture(scope="module")
def known_kind_in_db() -> tuple[str, str]:
    """A public annotation kind whose backing internal kind has rows."""
    con = sqlite3.connect(_DB_PATH)
    try:
        row = con.execute(
            "SELECT kind FROM am_entity_annotation GROUP BY kind ORDER BY COUNT(*) DESC LIMIT 1"
        ).fetchone()
        if not row:
            pytest.skip("no annotation kinds present")
        internal_kind = row[0]
        return internal_kind, _PUBLIC_KIND_LABELS[internal_kind]
    finally:
        con.close()


# ---------------------------------------------------------------------------
# Envelope-shape helpers (mirrors test_autonomath_tools.py).
# ---------------------------------------------------------------------------


def _has_nested_error(res: dict, code: str) -> bool:
    err = res.get("error")
    return isinstance(err, dict) and err.get("code") == code


def _assert_paginated_envelope(res: dict) -> None:
    assert isinstance(res, dict)
    assert "total" in res
    assert "results" in res
    assert isinstance(res["results"], list)
    assert "limit" in res
    assert "offset" in res
    assert "entity_id" in res
    assert "filters" in res


# ---------------------------------------------------------------------------
# 1. Public visibility — internal rows never surface.
# ---------------------------------------------------------------------------


def test_get_annotations_default_visibility_is_public_only(annotated_entity_id: str):
    """Public surface returns 0 for entities whose annotations are internal."""
    res = get_annotations(entity_id=annotated_entity_id)
    _assert_paginated_envelope(res)
    assert res["entity_id"] == annotated_entity_id
    assert res["total"] == 0
    assert res["results"] == []
    assert res["filters"]["visibility"] == "public"


# ---------------------------------------------------------------------------
# 2. Internal rows stay hidden even when the entity has table rows.
# ---------------------------------------------------------------------------


def test_get_annotations_never_returns_internal_rows(annotated_entity_id: str):
    res = get_annotations(entity_id=annotated_entity_id)
    _assert_paginated_envelope(res)
    assert res["results"] == []
    assert res["total"] == 0


# ---------------------------------------------------------------------------
# 3. kind filter — single known kind returns only that kind.
# ---------------------------------------------------------------------------


def test_get_annotations_kind_filter_single(
    annotated_entity_id: str, known_kind_in_db: tuple[str, str]
):
    _internal_kind, public_kind = known_kind_in_db
    res = get_annotations(
        entity_id=annotated_entity_id,
        kinds=[public_kind],
    )
    _assert_paginated_envelope(res)
    for r in res["results"]:
        assert r["kind"] == public_kind
    assert res["filters"]["kinds"] == [public_kind]


def test_get_annotations_kind_filter_multiple_known():
    """OR-combined kind filter accepts the closed enum."""
    # Use a fresh entity that has at least one populated kind. Pull the entity
    # off the DB to avoid cross-test fixture coupling.
    con = sqlite3.connect(_DB_PATH)
    try:
        row = con.execute(
            "SELECT entity_id FROM am_entity_annotation "
            "WHERE kind IN ('examiner_warning', 'quality_score') LIMIT 1"
        ).fetchone()
    finally:
        con.close()
    if not row:
        pytest.skip("no entity with examiner_warning|quality_score rows")
    res = get_annotations(
        entity_id=row[0],
        kinds=["warning", "quality_score"],
    )
    _assert_paginated_envelope(res)
    for r in res["results"]:
        assert r["kind"] in ("warning", "quality_score")


# ---------------------------------------------------------------------------
# 4. Negative cases — bad input → canonical error envelope.
# ---------------------------------------------------------------------------


def test_get_annotations_empty_entity_id_returns_missing_required_arg():
    res = get_annotations(entity_id="   ")
    assert _has_nested_error(res, "missing_required_arg")


def test_get_annotations_unknown_kind_returns_invalid_enum(annotated_entity_id: str):
    res = get_annotations(
        entity_id=annotated_entity_id,
        kinds=["totally_made_up_kind"],
    )
    assert _has_nested_error(res, "invalid_enum")
    # Hint must list the valid set so the caller can self-correct.
    err = res["error"]
    assert "Valid kinds" in err.get("hint", "")


def test_get_annotations_unknown_entity_id_returns_empty_envelope():
    """Valid-shape but non-existent canonical_id → empty results, not an error.

    The tool intentionally does not 404 on unknown entities — annotation
    surface returns "0 rows for this id" so the caller can chain calls without
    branching. Mirrors how search_* tools surface no-match results.
    """
    res = get_annotations(
        entity_id="program:does_not_exist:9999999999",
    )
    _assert_paginated_envelope(res)
    assert res["total"] == 0
    assert res["results"] == []


# ---------------------------------------------------------------------------
# 5. include_superseded toggle — default filters live-only.
# ---------------------------------------------------------------------------


def test_get_annotations_include_superseded_does_not_crash(annotated_entity_id: str):
    """include_superseded=True is a no-op on rows where superseded_at is NULL,
    but the SQL branch must execute cleanly."""
    res = get_annotations(
        entity_id=annotated_entity_id,
        include_superseded=True,
    )
    _assert_paginated_envelope(res)
    # Without supersede chains in the corpus today, the count is at least the
    # default-include_superseded=False count for the same entity.
    res_default = get_annotations(
        entity_id=annotated_entity_id,
    )
    assert res["total"] >= res_default["total"]
    assert res["filters"]["include_superseded"] is True


# ---------------------------------------------------------------------------
# 6. Public kind mapping sanity — public labels should not expose the backing
#    annotation taxonomy.
# ---------------------------------------------------------------------------


def test_public_kind_labels_match_documented_set():
    expected = {
        "warning",
        "correction",
        "quality_score",
        "validation_issue",
        "model_signal",
        "note",
    }
    assert expected == set(_PUBLIC_KIND_LABELS.values())


# ---------------------------------------------------------------------------
# 7. REST endpoint — GET /v1/am/annotations/{entity_id} returns 200.
# ---------------------------------------------------------------------------


def test_rest_get_annotations_unknown_entity(client):
    """REST surface must mirror the MCP envelope (no 404 on unknown entity)."""
    r = client.get("/v1/am/annotations/program:bogus:9999999999")
    assert r.status_code == 200
    body = r.json()
    assert body.get("entity_id") == "program:bogus:9999999999"
    assert body.get("total") == 0
    assert body.get("results") == []


def test_rest_get_annotations_invalid_kind_param(client, annotated_entity_id: str):
    """REST surface returns the canonical invalid_enum envelope on bad kind."""
    r = client.get(
        f"/v1/am/annotations/{annotated_entity_id}",
        params={"kinds": ["totally_bogus_kind"]},
    )
    assert r.status_code == 200
    body = r.json()
    err = body.get("error")
    assert isinstance(err, dict)
    assert err.get("code") == "invalid_enum"
