"""POST /v1/intel/path — 5-hop graph reasoning path between two entities.

Wave 31-2 composite: returns the shortest reasoning chain between
``from_entity`` and ``to_entity`` over the heterogeneous KG (programs ↔
laws ↔ judgments ↔ tsutatsu) plus up to 3 alternative paths so a
customer LLM can visualise the citation chain in 1 RPC instead of
fan-out N graph_traverse calls.

Substrates joined
-----------------
* ``am_5hop_graph`` (Wave 24 §152) — pre-computed entity → entity walks
  with edge_kinds JSON. Hop=1..5 keyed on canonical_id.
* ``am_citation_network`` (Wave 24 §163) — law ↔ law / judgment → law /
  tsutatsu → law citation edges, with citation_count weight.
* ``am_id_bridge`` (159) — UNI ↔ canonical bridge for input normalisation
  (lets the caller pass either form).
* ``programs`` / ``houjin_master`` / ``am_law_article`` for node names.

Algorithm
---------
Bidirectional BFS over the union edge graph (5hop + citation_network).
Frontiers expand one hop at a time from both endpoints; once a meet-in-
the-middle vertex appears in both frontiers we stitch the two halves
into a path. The first stitched path is the shortest; we then continue
until we have collected up to 3 alternates of the same or +1 length.

NO LLM, pure SQLite + Python. ¥3 / call (`_billing_unit: 1`).

Output is wrapped via the ``compact_envelope`` projection so a customer
LLM that pipes the response straight into its own context window pays
30-50% fewer tokens (`?compact=true` opt-in; default still verbose).
"""

from __future__ import annotations

import contextlib
import json
import logging
import sqlite3
import time
from collections import defaultdict, deque
from typing import TYPE_CHECKING, Annotated, Any

from fastapi import APIRouter, Body, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from jpintel_mcp.api._audit_seal import attach_seal_to_body, get_corpus_snapshot_id
from jpintel_mcp.api._compact_envelope import to_compact, wants_compact
from jpintel_mcp.api._corpus_snapshot import attach_corpus_snapshot
from jpintel_mcp.api.deps import ApiContextDep, DbDep, log_usage
from jpintel_mcp.config import settings

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger("jpintel.api.intel_path")

router = APIRouter(prefix="/v1/intel", tags=["intel"])


_DEFAULT_MAX_HOPS = 5
_MIN_MAX_HOPS = 1
_MAX_MAX_HOPS = 7

# Hard cap on alternative paths returned beyond the shortest path.
_ALTERNATE_PATH_CAP = 3

# Hard cap on per-vertex outgoing edges visited during BFS expansion.
# Defends against hub-vertex blow-up (e.g. 措置法42-4 cites 600+ rulings).
_PER_VERTEX_EXPANSION_CAP = 200

# Hard cap on total vertices visited per side of the bidirectional BFS.
# At max_hops=7 with branching 50, naive BFS could touch ~5e8 vertices —
# this cap keeps p99 latency bounded (<<200ms) on the 9.4 GB autonomath.db.
_TOTAL_VISIT_CAP = 5_000


_DISCLAIMER = (
    "本 path response は am_5hop_graph (Wave 24 §152) + am_citation_network "
    "(Wave 24 §163) + am_id_bridge を BFS で結合した **citation chain "
    "visualisation** であり、各 edge は事前に登録された関係 (cites / amends / "
    "applies_to 等) の機械的提示に過ぎません。法令・税務・申請可否判断 "
    "(税理士法 §52 / 弁護士法 §72 / 行政書士法 §1の2) の代替ではなく、"
    "確定判断は資格を有する士業へ。一次資料 (source_url) も必ずご確認ください。"
)


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class PathEntity(BaseModel):
    """Single endpoint of the path query."""

    type: str = Field(
        ...,
        min_length=1,
        max_length=40,
        description=(
            "Entity record_kind ('program' / 'law' / 'court_decision' / "
            "'tsutatsu' / 'corporate_entity' / etc.). Used as a hint when "
            "resolving the id; the BFS itself is type-agnostic."
        ),
    )
    id: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description=(
            "Entity id — accepts either an ``UNI-...`` jpintel unified_id "
            "or a canonical id (``program:...`` / ``law:...`` / "
            "``court_decision:...`` / etc.). The endpoint normalises "
            "both forms via am_id_bridge."
        ),
    )


class IntelPathRequest(BaseModel):
    """POST body for ``/v1/intel/path``."""

    from_entity: PathEntity = Field(..., description="Path source entity (BFS expands outward).")
    to_entity: PathEntity = Field(..., description="Path destination entity (BFS expands inward).")
    max_hops: int = Field(
        _DEFAULT_MAX_HOPS,
        ge=_MIN_MAX_HOPS,
        le=_MAX_MAX_HOPS,
        description=(
            f"Maximum hops to explore from each side ({_MIN_MAX_HOPS}..."
            f"{_MAX_MAX_HOPS}). Path length cap = 2 * max_hops in the "
            "bidirectional walk."
        ),
    )
    relation_filter: list[str] = Field(
        default_factory=list,
        description=(
            "Optional list of edge relation_types to keep. Empty list "
            "(default) means accept all edges. Examples: "
            '["cites", "amends", "applies_to"].'
        ),
    )


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


def _open_autonomath_ro() -> sqlite3.Connection | None:
    """Open ``autonomath.db`` read-only. Return None when missing."""
    p: Path = settings.autonomath_db_path
    if not p.exists() or p.stat().st_size == 0:
        return None
    uri = f"file:{p}?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True, timeout=5.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        with contextlib.suppress(sqlite3.OperationalError):
            conn.execute("PRAGMA query_only=1")
            conn.execute("PRAGMA temp_store=MEMORY")
        return conn
    except sqlite3.OperationalError:
        return None


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    try:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name = ? LIMIT 1",
            (name,),
        ).fetchone()
        return row is not None
    except sqlite3.Error:
        return False


# ---------------------------------------------------------------------------
# ID resolution
# ---------------------------------------------------------------------------


def _resolve_canonical_id(am_conn: sqlite3.Connection | None, entity_id: str) -> str | None:
    """Resolve any input form to the canonical id used by am_5hop_graph.

    Accepts:
      * ``UNI-...`` → look up am_id_bridge / entity_id_map.
      * canonical id (``program:...`` / ``law:...`` / etc.) → returned
        as-is after a soft existence check.
      * Anything else (raw 法人番号 / law_number) → returned as-is so
        the BFS at least tries; missing edges yield the not_found path.
    """
    if not entity_id:
        return None
    eid = entity_id.strip()
    if not eid:
        return None
    if am_conn is None:
        return eid

    if eid.startswith("UNI-"):
        # First try am_id_bridge (159), then entity_id_map (legacy).
        for table, col_a, col_b in (
            ("am_id_bridge", "id_a", "id_b"),
            ("entity_id_map", "jpi_unified_id", "am_canonical_id"),
        ):
            if not _table_exists(am_conn, table):
                continue
            try:
                row = am_conn.execute(
                    f"SELECT {col_b} FROM {table} WHERE {col_a} = ? LIMIT 1",
                    (eid,),
                ).fetchone()
            except sqlite3.Error:
                continue
            if row and row[0]:
                return str(row[0])
        return eid  # Soft pass-through; BFS may still fire on partial corpora.

    # Already canonical (or unknown shape) — return as-is.
    return eid


def _node_name(
    am_conn: sqlite3.Connection | None,
    jpintel_conn: sqlite3.Connection,
    canonical_id: str,
) -> str | None:
    """Resolve a canonical_id to a human-readable name for the response.

    Order of fallback: am_entities.primary_name → am_law_article.title →
    programs.primary_name (via entity_id_map) → houjin_master.normalized_name.
    Returns None when nothing found — caller surfaces null in the node.
    """
    if not canonical_id or am_conn is None:
        return None
    try:
        row = am_conn.execute(
            "SELECT primary_name FROM am_entities WHERE canonical_id = ? LIMIT 1",
            (canonical_id,),
        ).fetchone()
        if row and row[0]:
            return str(row[0])
    except sqlite3.Error:
        pass

    if canonical_id.startswith("law:") and _table_exists(am_conn, "am_law_article"):
        try:
            row = am_conn.execute(
                "SELECT article_title FROM am_law_article "
                "WHERE law_canonical_id = ? AND article_title IS NOT NULL "
                "LIMIT 1",
                (canonical_id,),
            ).fetchone()
            if row and row[0]:
                return str(row[0])
        except sqlite3.Error:
            pass

    # programs / houjin lookup via entity_id_map → jpintel.db.
    if _table_exists(am_conn, "entity_id_map"):
        try:
            row = am_conn.execute(
                "SELECT jpi_unified_id FROM entity_id_map WHERE am_canonical_id = ? LIMIT 1",
                (canonical_id,),
            ).fetchone()
        except sqlite3.Error:
            row = None
        if row and row[0]:
            uni = str(row[0])
            try:
                p = jpintel_conn.execute(
                    "SELECT primary_name FROM programs WHERE unified_id = ? LIMIT 1",
                    (uni,),
                ).fetchone()
                if p and p[0]:
                    return str(p[0])
            except sqlite3.Error:
                pass
    return None


def _node_type(am_conn: sqlite3.Connection | None, canonical_id: str) -> str:
    """Best-effort entity_type label for the response.

    Falls back to the canonical_id prefix when am_entities row is missing.
    """
    if am_conn is not None:
        try:
            row = am_conn.execute(
                "SELECT record_kind FROM am_entities WHERE canonical_id = ? LIMIT 1",
                (canonical_id,),
            ).fetchone()
            if row and row[0]:
                return str(row[0])
        except sqlite3.Error:
            pass
    if ":" in canonical_id:
        return canonical_id.split(":", 1)[0]
    return "unknown"


# ---------------------------------------------------------------------------
# Edge harvesting
# ---------------------------------------------------------------------------


def _decode_edge_kinds(raw: Any) -> list[str]:
    """Parse the JSON edge_kinds column from am_5hop_graph (best-effort)."""
    if not raw:
        return []
    try:
        out = json.loads(raw)
    except (TypeError, ValueError):
        return []
    if not isinstance(out, list):
        return []
    return [str(x) for x in out if isinstance(x, (str, int, float))]


def _harvest_neighbors_5hop(
    am_conn: sqlite3.Connection,
    canonical_id: str,
    relation_filter: set[str],
    cap: int = _PER_VERTEX_EXPANSION_CAP,
) -> list[tuple[str, str, dict[str, Any]]]:
    """Harvest hop=1 neighbours from am_5hop_graph (with evidence)."""
    if not _table_exists(am_conn, "am_5hop_graph"):
        return []
    try:
        rows = am_conn.execute(
            "SELECT end_entity_id, edge_kinds FROM am_5hop_graph "
            "WHERE start_entity_id = ? AND hop = 1 LIMIT ?",
            (canonical_id, cap),
        ).fetchall()
    except sqlite3.Error:
        return []
    out: list[tuple[str, str, dict[str, Any]]] = []
    for r in rows:
        end_id = r["end_entity_id"]
        if not end_id or end_id == canonical_id:
            continue
        kinds = _decode_edge_kinds(r["edge_kinds"])
        relation = kinds[0] if kinds else "unknown"
        if relation_filter and relation not in relation_filter:
            # If filter specified and none of the edge_kinds match, skip.
            if not any(k in relation_filter for k in kinds):
                continue
            relation = next(k for k in kinds if k in relation_filter)
        out.append(
            (
                str(end_id),
                relation,
                {
                    "table": "am_5hop_graph",
                    "row_id": f"{canonical_id}|{end_id}|1",
                    "snippet": (f"edge_kinds={kinds[:3]}" if kinds else "edge_kinds=[]"),
                },
            )
        )
    return out


def _harvest_neighbors_citation(
    am_conn: sqlite3.Connection,
    canonical_id: str,
    relation_filter: set[str],
    cap: int = _PER_VERTEX_EXPANSION_CAP,
) -> list[tuple[str, str, dict[str, Any]]]:
    """Harvest cites edges from am_citation_network (both directions)."""
    if not _table_exists(am_conn, "am_citation_network"):
        return []
    if relation_filter and "cites" not in relation_filter:
        return []
    out: list[tuple[str, str, dict[str, Any]]] = []
    try:
        # Outbound: this entity cites X.
        rows = am_conn.execute(
            "SELECT cited_entity_id, citation_count FROM am_citation_network "
            "WHERE citing_entity_id = ? "
            "ORDER BY citation_count DESC LIMIT ?",
            (canonical_id, cap),
        ).fetchall()
        for r in rows:
            end_id = r["cited_entity_id"]
            if not end_id or end_id == canonical_id:
                continue
            out.append(
                (
                    str(end_id),
                    "cites",
                    {
                        "table": "am_citation_network",
                        "row_id": f"{canonical_id}->{end_id}",
                        "snippet": (f"citation_count={int(r['citation_count'] or 0)}"),
                    },
                )
            )
        # Inbound: X cites this entity (treat as 'cited_by' for traversal —
        # caller filter on 'cites' still passes since the graph is symmetric
        # for path-finding purposes).
        rows = am_conn.execute(
            "SELECT citing_entity_id, citation_count FROM am_citation_network "
            "WHERE cited_entity_id = ? "
            "ORDER BY citation_count DESC LIMIT ?",
            (canonical_id, cap),
        ).fetchall()
        for r in rows:
            end_id = r["citing_entity_id"]
            if not end_id or end_id == canonical_id:
                continue
            out.append(
                (
                    str(end_id),
                    "cites",
                    {
                        "table": "am_citation_network",
                        "row_id": f"{end_id}->{canonical_id}",
                        "snippet": (f"citation_count={int(r['citation_count'] or 0)}"),
                    },
                )
            )
    except sqlite3.Error:
        return out
    return out


def _harvest_neighbors(
    am_conn: sqlite3.Connection,
    canonical_id: str,
    relation_filter: set[str],
) -> list[tuple[str, str, dict[str, Any]]]:
    """Union of 5hop + citation_network hop=1 neighbours.

    Deduplicates on ``(end_id, relation)`` so the same edge is not
    counted twice when both substrates carry it.
    """
    seen: set[tuple[str, str]] = set()
    out: list[tuple[str, str, dict[str, Any]]] = []
    for end_id, relation, evidence in _harvest_neighbors_5hop(
        am_conn, canonical_id, relation_filter
    ):
        key = (end_id, relation)
        if key in seen:
            continue
        seen.add(key)
        out.append((end_id, relation, evidence))
    for end_id, relation, evidence in _harvest_neighbors_citation(
        am_conn, canonical_id, relation_filter
    ):
        key = (end_id, relation)
        if key in seen:
            continue
        seen.add(key)
        out.append((end_id, relation, evidence))
    return out


# ---------------------------------------------------------------------------
# Bidirectional BFS
# ---------------------------------------------------------------------------


def _bidirectional_bfs(
    am_conn: sqlite3.Connection,
    *,
    src: str,
    dst: str,
    max_hops: int,
    relation_filter: set[str],
) -> tuple[list[list[str]], dict[tuple[str, str], tuple[str, dict[str, Any]]]]:
    """Bidirectional BFS over the union of 5hop + citation edges.

    Returns ``(paths, edge_meta)``:
      * ``paths`` — up to ``_ALTERNATE_PATH_CAP + 1`` distinct vertex paths,
        each as a list of canonical_ids ordered ``src → ... → dst``. The
        first entry is the shortest path; alternates may be of the same
        length or +1 hop.
      * ``edge_meta`` — mapping ``(u, v) → (relation, evidence_dict)`` for
        every edge that appears on at least one returned path, so the
        caller can hydrate the response edges block.
    """
    if src == dst:
        return [[src]], {}

    # Forward state: parents[v] = list of (parent_u, relation, evidence)
    forward_parents: dict[str, list[tuple[str, str, dict[str, Any]]]] = defaultdict(list)
    forward_dist: dict[str, int] = {src: 0}
    backward_parents: dict[str, list[tuple[str, str, dict[str, Any]]]] = defaultdict(list)
    backward_dist: dict[str, int] = {dst: 0}

    forward_queue: deque[str] = deque([src])
    backward_queue: deque[str] = deque([dst])
    forward_visited = 1
    backward_visited = 1

    meeting_points: list[str] = []
    meeting_distance: int | None = None

    while forward_queue and backward_queue:
        # Always expand the smaller frontier (classical BBFS optimization).
        if len(forward_queue) <= len(backward_queue):
            cur = forward_queue.popleft()
            cur_dist = forward_dist[cur]
            if cur_dist >= max_hops:
                continue
            if forward_visited >= _TOTAL_VISIT_CAP:
                logger.warning("intel.path forward visit cap reached at %d", _TOTAL_VISIT_CAP)
                break
            for end_id, relation, evidence in _harvest_neighbors(am_conn, cur, relation_filter):
                if end_id in forward_dist and forward_dist[end_id] < cur_dist + 1:
                    continue
                if end_id not in forward_dist:
                    forward_dist[end_id] = cur_dist + 1
                    forward_queue.append(end_id)
                    forward_visited += 1
                forward_parents[end_id].append((cur, relation, evidence))
                # Meeting check.
                if end_id in backward_dist:
                    total = forward_dist[end_id] + backward_dist[end_id]
                    if meeting_distance is None or total < meeting_distance:
                        meeting_distance = total
                        meeting_points = [end_id]
                    elif total == meeting_distance and end_id not in meeting_points:
                        meeting_points.append(end_id)
        else:
            cur = backward_queue.popleft()
            cur_dist = backward_dist[cur]
            if cur_dist >= max_hops:
                continue
            if backward_visited >= _TOTAL_VISIT_CAP:
                logger.warning("intel.path backward visit cap reached at %d", _TOTAL_VISIT_CAP)
                break
            for end_id, relation, evidence in _harvest_neighbors(am_conn, cur, relation_filter):
                if end_id in backward_dist and backward_dist[end_id] < cur_dist + 1:
                    continue
                if end_id not in backward_dist:
                    backward_dist[end_id] = cur_dist + 1
                    backward_queue.append(end_id)
                    backward_visited += 1
                # The edge is (end_id -> cur) when consumed in reverse.
                backward_parents[end_id].append((cur, relation, evidence))
                if end_id in forward_dist:
                    total = forward_dist[end_id] + backward_dist[end_id]
                    if meeting_distance is None or total < meeting_distance:
                        meeting_distance = total
                        meeting_points = [end_id]
                    elif total == meeting_distance and end_id not in meeting_points:
                        meeting_points.append(end_id)
        # Early exit once we have at least one meeting point and the
        # current frontiers cannot improve on it.
        if meeting_distance is not None:
            min_remaining = forward_dist[forward_queue[0]] if forward_queue else max_hops
            min_back = backward_dist[backward_queue[0]] if backward_queue else max_hops
            if min_remaining + min_back > meeting_distance + 1:
                break

    if meeting_distance is None or not meeting_points:
        return [], {}

    # Reconstruct paths: for each meeting point, walk parents back to src
    # and forward to dst, then concatenate.
    edge_meta: dict[tuple[str, str], tuple[str, dict[str, Any]]] = {}
    paths: list[list[str]] = []
    seen_paths: set[tuple[str, ...]] = set()

    def _walk_back(
        node: str,
        parents: dict[str, list[tuple[str, str, dict[str, Any]]]],
        forward: bool,
    ) -> list[list[str]]:
        """Reconstruct one path from ``node`` back to its frontier root."""
        if not parents.get(node):
            return [[node]]
        results: list[list[str]] = []
        # Choose the parent on the shortest distance (just one for simplicity).
        for parent, _relation, _evidence in parents[node][:1]:
            for sub in _walk_back(parent, parents, forward):
                results.append(sub + [node] if forward else [node] + sub)
        return results or [[node]]

    for mp in meeting_points[: _ALTERNATE_PATH_CAP + 1]:
        # Forward half: src → mp.
        # Use forward_parents to walk back from mp; reverse to get src→mp.
        forward_half = _walk_back(mp, forward_parents, forward=True)
        # Backward half: mp → dst.
        backward_half = _walk_back(mp, backward_parents, forward=False)
        for fh in forward_half[:2]:
            for bh in backward_half[:2]:
                if not fh or not bh:
                    continue
                # fh ends at mp, bh starts at mp — splice without dup.
                full = fh + bh[1:]
                key = tuple(full)
                if key in seen_paths:
                    continue
                seen_paths.add(key)
                paths.append(full)
                if len(paths) >= _ALTERNATE_PATH_CAP + 1:
                    break
            if len(paths) >= _ALTERNATE_PATH_CAP + 1:
                break
        if len(paths) >= _ALTERNATE_PATH_CAP + 1:
            break

    # Hydrate edge_meta for every (u, v) pair that appears on a returned path.
    for p in paths:
        for u, v in zip(p, p[1:], strict=False):
            if (u, v) in edge_meta:
                continue
            # Find a forward parent record (u was the parent of v).
            picked: tuple[str, dict[str, Any]] | None = None
            for parent, relation, evidence in forward_parents.get(v, []):
                if parent == u:
                    picked = (relation, evidence)
                    break
            if picked is None:
                # Try the backward direction (v was the parent of u).
                for parent, relation, evidence in backward_parents.get(u, []):
                    if parent == v:
                        picked = (relation, evidence)
                        break
            if picked is None:
                # Last-resort lookup: re-harvest u's neighbours.
                for end_id, relation, evidence in _harvest_neighbors(am_conn, u, relation_filter):
                    if end_id == v:
                        picked = (relation, evidence)
                        break
            if picked is not None:
                edge_meta[(u, v)] = picked
            else:
                edge_meta[(u, v)] = (
                    "unknown",
                    {"table": "unknown", "row_id": "", "snippet": ""},
                )

    # Sort paths by length ASC then by lexicographic concat for determinism.
    paths.sort(key=lambda p: (len(p), "|".join(p)))
    return paths, edge_meta


# ---------------------------------------------------------------------------
# Envelope assembly
# ---------------------------------------------------------------------------


def _build_path_envelope(
    *,
    payload: IntelPathRequest,
    am_conn: sqlite3.Connection | None,
    jpintel_conn: sqlite3.Connection,
) -> dict[str, Any]:
    """Compose the response body. Pure SQLite + Python, NO LLM."""
    src_id = _resolve_canonical_id(am_conn, payload.from_entity.id) or ""
    dst_id = _resolve_canonical_id(am_conn, payload.to_entity.id) or ""
    relation_filter = {r.strip() for r in payload.relation_filter if r.strip()}

    if am_conn is None or not src_id or not dst_id:
        return {
            "found": False,
            "shortest_path_length": None,
            "nodes": [],
            "edges": [],
            "alternative_paths": [],
            "from_entity": payload.from_entity.model_dump(),
            "to_entity": payload.to_entity.model_dump(),
            "max_hops": payload.max_hops,
            "relation_filter": sorted(relation_filter),
            "data_quality": {
                "missing_substrate": (["autonomath.db"] if am_conn is None else []),
                "resolved_from": src_id or None,
                "resolved_to": dst_id or None,
            },
            "_disclaimer": _DISCLAIMER,
            "_billing_unit": 1,
        }

    paths, edge_meta = _bidirectional_bfs(
        am_conn,
        src=src_id,
        dst=dst_id,
        max_hops=payload.max_hops,
        relation_filter=relation_filter,
    )

    if not paths:
        return {
            "found": False,
            "shortest_path_length": None,
            "nodes": [],
            "edges": [],
            "alternative_paths": [],
            "from_entity": payload.from_entity.model_dump(),
            "to_entity": payload.to_entity.model_dump(),
            "max_hops": payload.max_hops,
            "relation_filter": sorted(relation_filter),
            "data_quality": {
                "missing_substrate": [],
                "resolved_from": src_id,
                "resolved_to": dst_id,
            },
            "_disclaimer": _DISCLAIMER,
            "_billing_unit": 1,
        }

    shortest = paths[0]
    alternates = paths[1 : _ALTERNATE_PATH_CAP + 1]

    # Build the unique-vertex node list with stable indexes.
    node_index: dict[str, int] = {}
    nodes_out: list[dict[str, Any]] = []
    for p in paths:
        for v in p:
            if v in node_index:
                continue
            node_index[v] = len(nodes_out)
            nodes_out.append(
                {
                    "entity_type": _node_type(am_conn, v),
                    "entity_id": v,
                    "name": _node_name(am_conn, jpintel_conn, v),
                }
            )

    edges_out: list[dict[str, Any]] = []
    for u, v in zip(shortest, shortest[1:], strict=False):
        relation, evidence = edge_meta.get(
            (u, v),
            ("unknown", {"table": "unknown", "row_id": "", "snippet": ""}),
        )
        edges_out.append(
            {
                "from_idx": node_index[u],
                "to_idx": node_index[v],
                "relation": relation,
                "evidence": evidence,
            }
        )

    alternate_paths_out: list[list[int]] = []
    for ap in alternates:
        alternate_paths_out.append([node_index[v] for v in ap if v in node_index])

    return {
        "found": True,
        "shortest_path_length": len(shortest) - 1,
        "nodes": nodes_out,
        "edges": edges_out,
        "alternative_paths": alternate_paths_out,
        "from_entity": payload.from_entity.model_dump(),
        "to_entity": payload.to_entity.model_dump(),
        "max_hops": payload.max_hops,
        "relation_filter": sorted(relation_filter),
        "data_quality": {
            "missing_substrate": [],
            "resolved_from": src_id,
            "resolved_to": dst_id,
        },
        "_disclaimer": _DISCLAIMER,
        "_billing_unit": 1,
    }


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------


@router.post(
    "/path",
    summary="5-hop graph reasoning path between two entities (citation chain)",
    description=(
        "Bidirectional BFS over am_5hop_graph + am_citation_network + "
        "am_id_bridge to surface the shortest reasoning chain between "
        "``from_entity`` and ``to_entity`` in 1 RPC. Returns the shortest "
        "path + up to 3 alternate paths so a customer LLM can visualise "
        "the citation chain.\n\n"
        "**Pricing:** ¥3 / call (1 unit total) regardless of `max_hops`.\n\n"
        "**Inputs:** ``from_entity`` / ``to_entity`` accept either a "
        "``UNI-...`` jpintel unified_id or a canonical id "
        "(``program:...`` / ``law:...`` / ``court_decision:...`` / etc.); "
        "the endpoint normalises both forms via am_id_bridge.\n\n"
        "**relation_filter:** optional list of edge relation_types "
        '(e.g. ``["cites", "amends", "applies_to"]``) — empty list '
        "accepts every edge type.\n\n"
        "Pure SQL + Python BFS. NO LLM call. Sensitive: §52 / §72 / §1 "
        "fence on the disclaimer envelope."
    ),
)
def post_intel_path(
    request: Request,
    payload: Annotated[IntelPathRequest, Body(...)],
    conn: DbDep,
    ctx: ApiContextDep,
) -> JSONResponse:
    _t0 = time.perf_counter()

    if payload.from_entity.id.strip() == payload.to_entity.id.strip():
        # Degenerate but legal — a single-vertex "path" of length 0.
        body: dict[str, Any] = {
            "found": True,
            "shortest_path_length": 0,
            "nodes": [
                {
                    "entity_type": payload.from_entity.type,
                    "entity_id": payload.from_entity.id,
                    "name": None,
                }
            ],
            "edges": [],
            "alternative_paths": [],
            "from_entity": payload.from_entity.model_dump(),
            "to_entity": payload.to_entity.model_dump(),
            "max_hops": payload.max_hops,
            "relation_filter": sorted({r.strip() for r in payload.relation_filter if r.strip()}),
            "data_quality": {
                "missing_substrate": [],
                "resolved_from": payload.from_entity.id,
                "resolved_to": payload.to_entity.id,
            },
            "_disclaimer": _DISCLAIMER,
            "_billing_unit": 1,
        }
    else:
        am_conn = _open_autonomath_ro()
        try:
            body = _build_path_envelope(
                payload=payload,
                am_conn=am_conn,
                jpintel_conn=conn,
            )
        finally:
            if am_conn is not None:
                with contextlib.suppress(sqlite3.Error):
                    am_conn.close()

    body["corpus_snapshot_id"] = get_corpus_snapshot_id()
    with contextlib.suppress(sqlite3.Error):
        # Soft-fail — body already carries get_corpus_snapshot_id() above.
        body = attach_corpus_snapshot(body, conn)

    latency_ms = int((time.perf_counter() - _t0) * 1000)
    log_usage(
        conn,
        ctx,
        "intel.path",
        latency_ms=latency_ms,
        result_count=int(body.get("shortest_path_length") or 0) if body.get("found") else 0,
        params={
            "from_type": payload.from_entity.type,
            "from_id_present": bool(payload.from_entity.id),
            "to_type": payload.to_entity.type,
            "to_id_present": bool(payload.to_entity.id),
            "max_hops": payload.max_hops,
            "relation_filter_count": len(payload.relation_filter),
        },
        quantity=1,
        strict_metering=True,
    )
    attach_seal_to_body(
        body,
        endpoint="intel.path",
        request_params={
            "from_entity": payload.from_entity.model_dump(),
            "to_entity": payload.to_entity.model_dump(),
            "max_hops": payload.max_hops,
            "relation_filter": sorted({r.strip() for r in payload.relation_filter if r.strip()}),
        },
        api_key_hash=ctx.key_hash,
        conn=conn,
    )

    if wants_compact(request):
        body = to_compact(body)

    return JSONResponse(content=body)


__all__ = ["router"]


# Defensive: ensure HTTPException is referenced so future error branches
# can raise without a missing import. (Currently the endpoint never raises;
# all error states surface as found=false envelopes.)
_ = HTTPException
