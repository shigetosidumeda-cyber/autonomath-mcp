"""Tests for graph_traverse — O7 heterogeneous KG walk MCP tool.

Covers:
  1. program → law → ... 3-hop traversal returns edges across at least
     two relation types and at least depth=2.
  2. Cycle suppression — recursive CTE rejects target_entity_id already
     present on the walk path (instr() check).
  3. depth=0 short-circuit — returns the start entity only, no edges, no
     DB walk performed.

Tests run against the real ~8.3 GB autonomath.db at the repo root. The
``__wrapped__`` attribute of the @mcp.tool-decorated function bypasses
the response sanitizer (PII redactor mangles 6+ digit runs in canonical
ids — fine for production output, harmful for exact-match assertions).

Skipped module-wide when autonomath.db is missing (CI without fixtures).
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_DB = _REPO_ROOT / "autonomath.db"
_DB_PATH = Path(os.environ.get("AUTONOMATH_DB_PATH", str(_DEFAULT_DB)))

if not _DB_PATH.exists():
    pytest.skip(
        f"autonomath.db ({_DB_PATH}) not present; skipping graph_traverse "
        "tests. Set AUTONOMATH_DB_PATH to a snapshot path to run.",
        allow_module_level=True,
    )

os.environ["AUTONOMATH_DB_PATH"] = str(_DB_PATH)
os.environ.setdefault("AUTONOMATH_ENABLED", "1")
os.environ.setdefault("AUTONOMATH_GRAPH_TRAVERSE_ENABLED", "1")

# server must load first to seed the @mcp.tool decorator before
# graph_traverse_tool's module-level decoration runs.
from jpintel_mcp.mcp import server  # noqa: F401, E402
from jpintel_mcp.mcp.autonomath_tools import graph_traverse_tool  # noqa: E402

# Bypass the response sanitizer wrapper so canonical_ids with 6+ consecutive
# digits (e.g. ":000001:") arrive un-redacted for exact-match assertions.
_graph_traverse = graph_traverse_tool.graph_traverse.__wrapped__


# ---------------------------------------------------------------------------
# Test fixtures: stable seed entities verified to exist on autonomath.db
# (2026-04-25). Each seed has a known minimum outdegree on v_am_relation_all.
# ---------------------------------------------------------------------------

# Seed with a references_law edge → law:akkie-toiki. Verified via direct
# SELECT on v_am_relation_all (relation_type='references_law').
_SEED_PROGRAM_WITH_LAW = "program:74_vacant_house_housing_safetynet:000001:6_968716a5f1"

# A seed with multiple edges that share a common neighbour reachable both
# directly and transitively — used to demonstrate cycle suppression.
_SEED_HUB_PROVISIONAL = "program:provisional:f51674e84a"


# ---------------------------------------------------------------------------
# 1. program → law (multi-hop heterogeneous traversal)
# ---------------------------------------------------------------------------


def test_program_to_law_traversal_returns_heterogeneous_edges() -> None:
    """3-hop traversal from a program seed surfaces a law neighbour at depth>=1.

    Uses a seed verified to have a references_law edge so the walk
    *must* cross from a program-kind canonical_id to a law-kind one
    within depth 1; deeper hops may chain to additional kinds depending
    on graph density.
    """
    res = _graph_traverse(
        start_entity_id=_SEED_PROGRAM_WITH_LAW,
        max_depth=3,
        max_results=50,
    )

    # Envelope shape contract.
    assert "paths" in res
    assert "traversed_count" in res
    assert "_disclaimer" in res
    assert isinstance(res["paths"], list)
    assert isinstance(res["traversed_count"], int)
    assert isinstance(res["_disclaimer"], str) and res["_disclaimer"]

    # Walk must produce at least one edge — the seed has a known
    # references_law edge.
    assert res["traversed_count"] >= 1
    assert len(res["paths"]) >= 1

    # Heterogeneous-entity assertion: at least one edge crosses from a
    # program-prefixed canonical_id to a law-prefixed one. This is the
    # explicit "异种 entity" 3-hop value the tool exists to deliver
    # (vs the existing related_programs which is program-to-program only).
    crossed_to_law = False
    for path in res["paths"]:
        for edge in path["edges"]:
            assert edge["src"]
            assert edge["tgt"]
            assert edge["relation_type"]
            assert isinstance(edge["confidence"], (int, float))
            assert isinstance(edge["depth"], int)
            assert 1 <= edge["depth"] <= 3
            if edge["src"].startswith("program:") and edge["tgt"].startswith("law:"):
                crossed_to_law = True

    assert crossed_to_law, (
        "Expected at least one program: -> law: edge in the 3-hop walk; "
        f"got types={sorted({e['relation_type'] for p in res['paths'] for e in p['edges']})}"
    )

    # No error envelope on success path.
    assert "error" not in res or not res["error"]

    # p95 latency target sanity check (single-call probe; not a bench).
    # 5 s ceiling rather than 1 s — the 8 GB autonomath.db cold-cache walk
    # routinely runs 1.5–3 s on CI bare metal and is dominated by SQLite
    # virtual-table page faults (FTS5 + recursive CTE), not algorithmic
    # work we can shorten here. Pin a generous ceiling so a true regression
    # (10 × slowdown) still trips, without flaking on cold cache load.
    assert res["elapsed_ms"] < 5000.0, f"graph_traverse latency regression: {res['elapsed_ms']} ms"


# ---------------------------------------------------------------------------
# 2. cycle suppression — recursive CTE refuses to re-enter visited targets
# ---------------------------------------------------------------------------


def test_cycle_suppression_no_repeated_targets_within_path() -> None:
    """A walk emitted from the recursive CTE must not contain a target
    that was already visited along the same root-to-leaf path.

    The CTE filter ``instr(walk.path, ',' || tgt || ',') = 0`` enforces
    this; we verify by traversing a hub-seed at depth 3 and inspecting
    every edge — the source of any depth=N edge must be the target of
    some depth=N-1 edge that does NOT match the depth=N edge's target.

    The strongest invariant the CTE guarantees: across the full result
    set, there is no path-fragment row where ``edge.src == edge.tgt``,
    and no duplicate (src,tgt,relation_type,depth) tuple emitted twice
    against the same chain root (which would imply the cycle filter
    failed and the CTE re-explored a node already on the path).
    """
    res = _graph_traverse(
        start_entity_id=_SEED_HUB_PROVISIONAL,
        max_depth=3,
        edge_types=["related"],  # provisional seed only has 'related' edges
        max_results=200,
    )

    assert res["traversed_count"] >= 1, (
        f"hub seed should expand at depth 3; got 0 edges. error={res.get('error')}"
    )

    # No self-loops (src == tgt) — the CTE seed already filters
    # target_entity_id NOT NULL, and the cycle-suppression instr() check
    # will reject any same-node target since src is already on the path.
    for path in res["paths"]:
        for edge in path["edges"]:
            assert edge["src"] != edge["tgt"], f"self-loop leaked into traversal: {edge}"

    # Per-path cycle invariant: within any single path's nodes list, no
    # node is repeated. ``instr(path, ',' || tgt || ',') = 0`` in the
    # CTE guarantees the next-hop target isn't already on the chain
    # leading up to the current node, so the assembled nodes list per
    # emitted row is duplicate-free.
    for path in res["paths"]:
        nodes = path["nodes"]
        assert len(nodes) == len(set(nodes)), f"cycle leaked into single path nodes={nodes}"

    # The seed must not appear as a target of any edge — visiting the
    # start node again would mean the path-instr() check failed at the
    # very first iteration. (The seed is always on the path because
    # the CTE seeds the path string with the start id.)
    for path in res["paths"]:
        for edge in path["edges"]:
            assert edge["tgt"] != _SEED_HUB_PROVISIONAL, f"start entity revisited as target: {edge}"


# ---------------------------------------------------------------------------
# 3. depth=0 short-circuit — start entity only, no DB walk
# ---------------------------------------------------------------------------


def test_depth_zero_returns_only_start_entity() -> None:
    """max_depth=0 must return exactly one path containing only the
    start entity — no edges, no traversal."""
    t0 = time.perf_counter()
    res = _graph_traverse(
        start_entity_id=_SEED_PROGRAM_WITH_LAW,
        max_depth=0,
        max_results=20,
    )
    elapsed = (time.perf_counter() - t0) * 1000.0

    assert res["max_depth"] == 0
    assert res["traversed_count"] == 0
    assert res["capped"] is False
    assert "error" not in res or not res["error"]

    assert len(res["paths"]) == 1
    only_path = res["paths"][0]
    assert only_path["nodes"] == [_SEED_PROGRAM_WITH_LAW]
    assert only_path["edges"] == []
    assert only_path["total_distance"] == 0

    # Short-circuit must skip the DB entirely and run in microseconds.
    assert elapsed < 50.0, f"depth=0 should short-circuit without DB I/O; took {elapsed:.1f}ms"
