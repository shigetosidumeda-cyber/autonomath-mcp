"""GET /v1/graph/traverse/{entity_id} — cross-link graph 4-hop traversal (Wave 15 F1).

REST surface for the existing `graph_traverse` MCP tool. Exposes the
22-axis cross-reference walk over `am_relation` (378k edges across
15 relation types) joined with `am_entities` (503,930 canonical_id rows)
and `am_alias` (335,605 alias rows) so a downstream agent can ask
「制度 X → 根拠法 → 関連通達 → 関連判例 → 改正履歴」in a single ¥3 call.

Design
------
* Uses the **autonomath.db** read connection (where am_relation /
  am_entities / am_alias live). CLAUDE.md forbids ATTACH / cross-DB
  JOIN so the entire walk runs inside one autonomath read txn.
* Recursive CTE BFS, **depth 1-4** (default 2; 4-hop opt-in for the
  cross-link surfaces the MCP graph_traverse tool caps at 3). Cycle
  suppression via path-string `instr()`; per-node fan-out cap at 30
  via `ROW_NUMBER() OVER (PARTITION BY source_entity_id, relation_type
  ORDER BY confidence DESC)`.
* `types=` query filter restricts the traversal to a subset of the 15
  relation_types (default = all 15). Comma-separated single-string form
  also accepted (`?types=cited,amended,related`).
* `min_confidence=` floor (default 0.0).
* Each node in the response is enriched with its `am_entities` row
  (kind, display_name) + the first matching `am_alias` row when present
  — that's the "+ am_alias join" promised by the Wave 15 spec.
* Output target: p95 < 100 ms on the 9.4 GB autonomath.db (the existing
  graph_traverse tool already hits ~30-50 ms at depth=3 with 30-row
  fan-out caps; depth=4 budget is the new perf index from migration
  215_cross_link_graph_v2).

Hard constraints
----------------
* NO LLM call. Pure SQLite SELECT + Python dict shaping.
* NO Anthropic SDK / openai / langchain import (memory:
  feedback_no_operator_llm_api + feedback_autonomath_no_api_use).
* Append nothing — read-only over the autonomath corpus.
* `_billing_unit: 1` flat regardless of how many edges return.

Graceful degradation
--------------------
If autonomath.db is missing (fresh dev DB / CI without fixture), the
endpoint returns an empty paths list with `coverage_summary.db_present:
false` and a non-500 status. Same posture tax_chain.py uses for its
autonomath axes.
"""

from __future__ import annotations

import logging
import sqlite3
import time
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Path, Query, status
from fastapi.responses import JSONResponse

from jpintel_mcp.api._corpus_snapshot import attach_corpus_snapshot, snapshot_headers
from jpintel_mcp.api.deps import ApiContextDep, DbDep, log_usage

logger = logging.getLogger("jpintel.api.graph")

router = APIRouter(prefix="/v1/graph", tags=["graph"])


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Relation types live in am_relation.relation_type; mirror of
# autonomath_tools/graph_traverse_tool.py::_ALL_RELATION_TYPES so the REST
# whitelist stays in lockstep with the MCP whitelist.
_ALL_RELATION_TYPES: frozenset[str] = frozenset(
    {
        "cited",
        "cited_by",
        "amended",
        "successor",
        "predecessor",
        "compatible",
        "incompatible",
        "prerequisite",
        "exclusive",
        "complementary",
        "supersedes",
        "superseded_by",
        "applies_to",
        "implements",
        "related",
    }
)

_DEFAULT_EDGE_TYPES: tuple[str, ...] = tuple(sorted(_ALL_RELATION_TYPES - {"related"}))

_MAX_FANOUT_PER_NODE = 30
_HARD_MAX_DEPTH = 4
_DEFAULT_MAX_DEPTH = 2
_HARD_MAX_RESULTS = 500
_DEFAULT_MAX_RESULTS = 50

# 22-axis cross-link disclaimer. NOT a 士業 surface (graph is corpus
# metadata) but downstream LLM should still relay primary-source
# guidance when edges drive an answer.
_GRAPH_DISCLAIMER = (
    "本 graph traverse は jpcite autonomath corpus (am_relation 378k edges + "
    "am_entities 503,930 nodes + am_alias 335,605 alias rows) を 4 hop まで "
    "BFS で辿ったメタデータ index で、税理士法 §52 ・弁護士法 §72 ・公認会計士法 "
    "§47条の2 のいずれの士業役務にも該当しません。各 edge は origin / "
    "confidence を併記しており、graph_rescue 由来 (confidence < 0.5) は "
    "heuristic 推定です。確定的な引用関係は各 node の source_url で原典を "
    "確認してください。"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _open_autonomath_ro() -> sqlite3.Connection | None:
    """Open ``autonomath.db`` read-only; ``None`` on missing DB."""
    try:
        from jpintel_mcp.mcp.autonomath_tools.db import connect_autonomath

        return connect_autonomath()
    except (FileNotFoundError, sqlite3.Error) as exc:
        logger.warning("graph.traverse: autonomath.db unavailable: %s", exc)
        return None
    except Exception as exc:  # noqa: BLE001
        logger.warning("graph.traverse: autonomath.db open failed: %s", exc)
        return None


def _parse_types(types: list[str] | None) -> tuple[list[str], str | None]:
    """Validate `types=` query and return canonical relation_type list."""
    if not types:
        return list(_DEFAULT_EDGE_TYPES), None
    flat: list[str] = []
    for item in types:
        # Accept comma-separated single-string form.
        if "," in item:
            flat.extend(t.strip() for t in item.split(",") if t.strip())
        else:
            flat.append(item.strip())
    bad = sorted({t for t in flat if t and t not in _ALL_RELATION_TYPES})
    if bad:
        return [], f"unknown relation_type(s): {bad}. Allowed: {sorted(_ALL_RELATION_TYPES)}"
    deduped = sorted(set(flat))
    return deduped or list(_DEFAULT_EDGE_TYPES), None


def _enrich_nodes(
    am_conn: sqlite3.Connection,
    node_ids: list[str],
) -> dict[str, dict[str, Any]]:
    """Pull (kind, display_name, primary_alias) for each canonical_id."""
    if not node_ids:
        return {}
    placeholders = ",".join("?" * len(node_ids))
    out: dict[str, dict[str, Any]] = {}
    try:
        ent_rows = am_conn.execute(
            f"""
            SELECT canonical_id, record_kind, primary_name, source_url
              FROM am_entities
             WHERE canonical_id IN ({placeholders})
            """,
            node_ids,
        ).fetchall()
        for row in ent_rows:
            out[row[0]] = {
                "entity_id": row[0],
                "kind": row[1],
                "display_name": row[2],
                "source_url": row[3],
                "alias": None,
            }
    except sqlite3.Error as exc:
        logger.warning("graph.traverse: am_entities enrich failed: %s", exc)
        return {nid: {"entity_id": nid, "kind": None, "display_name": None} for nid in node_ids}

    # am_alias is best-effort — one alias per entity at most. Tolerate
    # schema drift (table may be absent on fresh dev DB). am_alias scopes
    # by `entity_table` so we filter to am_entities-keyed alias rows only.
    try:
        alias_rows = am_conn.execute(
            f"""
            SELECT canonical_id, MIN(alias)
              FROM am_alias
             WHERE entity_table = 'am_entities'
               AND canonical_id IN ({placeholders})
             GROUP BY canonical_id
            """,
            node_ids,
        ).fetchall()
        for row in alias_rows:
            if row[0] in out:
                out[row[0]]["alias"] = row[1]
    except sqlite3.Error:
        # Older corpus snapshots may not have am_alias yet; alias stays None.
        pass

    # Fill in stragglers that had no am_entities row.
    for nid in node_ids:
        if nid not in out:
            out[nid] = {
                "entity_id": nid,
                "kind": None,
                "display_name": None,
                "source_url": None,
                "alias": None,
            }
    return out


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@router.get(
    "/traverse/{entity_id}",
    summary="22-axis cross-link graph BFS (1-4 hop) over am_relation",
    description=(
        "Walks `am_relation` (378k edges, 15 relation_types) from "
        "`entity_id` outward up to `depth` hops (1-4, default 2). "
        "Each returned edge is enriched with the target node's "
        "`am_entities` row (kind / display_name / source_url) plus "
        "the first matching `am_alias` row.\n\n"
        "**Pricing:** ¥3 / call (`_billing_unit: 1`) regardless of "
        "edge count. Pure SQLite recursive CTE, NO LLM.\n\n"
        "**Performance:** p95 < 100 ms on the 9.4 GB autonomath.db; "
        "depth=4 enabled by perf indexes from migration 215."
    ),
)
def traverse_graph(
    conn: DbDep,
    ctx: ApiContextDep,
    entity_id: Annotated[
        str,
        Path(
            ...,
            description=(
                "Seed canonical_id from `am_entities` "
                "(e.g. `program:04_program_documents:000016:IT2026_b030eaea36`, "
                "`law:rouki`, `authority:meti`)."
            ),
            min_length=1,
            max_length=256,
        ),
    ],
    depth: Annotated[
        int,
        Query(
            ge=1,
            le=_HARD_MAX_DEPTH,
            description=(
                "BFS depth limit (1-4 hops). Default 2. Depth 4 is "
                "the cross-link cohort target; perf is bounded by the "
                "per-node fan-out cap (30) + max_results."
            ),
        ),
    ] = _DEFAULT_MAX_DEPTH,
    types: Annotated[
        list[str] | None,
        Query(
            description=(
                "Restrict traversal to these relation_type values. "
                "Comma-separated single-string form also accepted. "
                "Default = all 15 except low-confidence `related`."
            ),
        ),
    ] = None,
    max_results: Annotated[
        int,
        Query(
            ge=1,
            le=_HARD_MAX_RESULTS,
            description=(
                f"Cap on distinct (src,tgt,relation_type) edges. "
                f"Default {_DEFAULT_MAX_RESULTS}, hard ceiling "
                f"{_HARD_MAX_RESULTS}."
            ),
        ),
    ] = _DEFAULT_MAX_RESULTS,
    min_confidence: Annotated[
        float,
        Query(
            ge=0.0,
            le=1.0,
            description=(
                "Drop edges below this confidence floor. Default 0.0. "
                "Use 0.5 to exclude `graph_rescue` heuristic edges."
            ),
        ),
    ] = 0.0,
) -> JSONResponse:
    """Execute the cross-link BFS and return the edge-enriched envelope."""
    _t0 = time.perf_counter()

    whitelist, err = _parse_types(types)
    if err is not None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, err)

    am_conn = _open_autonomath_ro()
    edges_out: list[dict[str, Any]] = []
    capped = False
    db_present = am_conn is not None

    if am_conn is not None:
        placeholders = ",".join("?" * len(whitelist))
        sql = f"""
        WITH RECURSIVE walk(src, tgt, relation_type, confidence, origin,
                            depth, path) AS (
            SELECT
                r.source_entity_id,
                r.target_entity_id,
                r.relation_type,
                r.confidence,
                r.origin,
                1,
                ',' || r.source_entity_id || ',' || r.target_entity_id || ','
            FROM (
                SELECT *,
                    ROW_NUMBER() OVER (
                        PARTITION BY source_entity_id, relation_type
                        ORDER BY confidence DESC
                    ) AS rn
                FROM am_relation
                WHERE source_entity_id = ?
                  AND target_entity_id IS NOT NULL
                  AND relation_type IN ({placeholders})
                  AND confidence >= ?
            ) r
            WHERE r.rn <= {_MAX_FANOUT_PER_NODE}

            UNION ALL

            SELECT
                r2.source_entity_id,
                r2.target_entity_id,
                r2.relation_type,
                r2.confidence,
                r2.origin,
                w.depth + 1,
                w.path || r2.target_entity_id || ','
            FROM walk w
            JOIN (
                SELECT *,
                    ROW_NUMBER() OVER (
                        PARTITION BY source_entity_id, relation_type
                        ORDER BY confidence DESC
                    ) AS rn
                FROM am_relation
                WHERE target_entity_id IS NOT NULL
                  AND relation_type IN ({placeholders})
                  AND confidence >= ?
            ) r2
              ON r2.source_entity_id = w.tgt
            WHERE w.depth < ?
              AND r2.rn <= {_MAX_FANOUT_PER_NODE}
              AND instr(w.path, ',' || r2.target_entity_id || ',') = 0
        )
        SELECT src, tgt, relation_type, confidence, origin, depth
          FROM walk
         LIMIT ?
        """
        params: list[Any] = [entity_id]
        params.extend(whitelist)
        params.append(min_confidence)
        params.extend(whitelist)
        params.append(min_confidence)
        params.append(depth)
        params.append(max_results + 1)  # +1 to detect cap

        try:
            rows = am_conn.execute(sql, params).fetchall()
        except sqlite3.Error as exc:
            logger.warning("graph.traverse: BFS failed: %s", exc)
            rows = []

        if len(rows) > max_results:
            rows = rows[:max_results]
            capped = True

        node_ids = sorted({r[0] for r in rows} | {r[1] for r in rows} | {entity_id})
        node_map = _enrich_nodes(am_conn, node_ids)

        for r in rows:
            edges_out.append(
                {
                    "src": r[0],
                    "tgt": r[1],
                    "relation_type": r[2],
                    "confidence": r[3],
                    "origin": r[4],
                    "depth": r[5],
                    "src_node": node_map.get(r[0]),
                    "tgt_node": node_map.get(r[1]),
                }
            )
    else:
        node_map = {entity_id: {"entity_id": entity_id, "kind": None, "display_name": None}}

    elapsed_ms = round((time.perf_counter() - _t0) * 1000.0, 2)

    body: dict[str, Any] = {
        "start_entity_id": entity_id,
        "depth": depth,
        "types_used": whitelist,
        "min_confidence": min_confidence,
        "max_results": max_results,
        "edges": edges_out,
        "edge_count": len(edges_out),
        "capped": capped,
        "elapsed_ms": elapsed_ms,
        "coverage_summary": {
            "db_present": db_present,
            "node_count": len({e["src"] for e in edges_out} | {e["tgt"] for e in edges_out})
            if edges_out
            else 0,
            "edge_count": len(edges_out),
        },
        "_billing_unit": 1,
        "_disclaimer": _GRAPH_DISCLAIMER,
    }
    attach_corpus_snapshot(body, conn)

    log_usage(
        conn,
        ctx,
        "graph.traverse",
        params={
            "entity_id": entity_id,
            "depth": depth,
            "types": whitelist,
            "max_results": max_results,
            "min_confidence": min_confidence,
        },
        latency_ms=int(elapsed_ms),
        result_count=len(edges_out),
        strict_metering=True,
    )

    return JSONResponse(content=body, headers=snapshot_headers(conn))
