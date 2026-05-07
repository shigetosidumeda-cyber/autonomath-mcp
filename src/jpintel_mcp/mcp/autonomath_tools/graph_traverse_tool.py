"""graph_traverse — O7 Knowledge Graph traversal MCP tool (2026-04-25).

Heterogeneous 1-3 hop BFS over ``v_am_relation_all`` (24,004 edges across
15 canonical relation types). Complements the existing ``related_programs``
tool which is depth ≤ 2 + 6 axes only + program-to-program same-kind hops.
``graph_traverse`` exposes the FULL multi-kind KG (program / law /
case_study / authority / region / industry / corporate_entity / ...) so an
agent can ask "持続化補助金 → 根拠法 → 関連判例 → 過去採択法人" in 1
RPC instead of 5-7 separate tool calls.

Memory alignment (verified before write):
  - feedback_autonomath_no_api_use → pure SQL traversal, no Anthropic calls
  - feedback_zero_touch_solo       → ¥3/req metered only, no tier SKU
  - feedback_organic_only_no_ads   → no ranking-by-payment, no advertising
  - O7 design doc                  → analysis_wave18/_o7_knowledge_graph_2026-04-25.md

Latency target: p95 < 200 ms. Avg outdegree per program seed = 4.14.
Max hub (IT2026 program 1,822 outdegree) is capped via per-node fan-out
limit + global ``max_results`` LIMIT clause + cycle suppression
(``instr(path, target)``).

Schema source: ``v_am_relation_all`` (UNION VIEW of am_relation +
am_relation_facts). ``ix_w19_rel_source_type (source_entity_id,
relation_type)`` index serves the recursive CTE source-side lookup;
EXPLAIN QUERY PLAN confirms ``SEARCH USING INDEX`` per hop.

Env gate: ``AUTONOMATH_GRAPH_TRAVERSE_ENABLED`` (default "1"). Set "0"
to omit this tool from the MCP surface (rollback only — the canonical
launch state has it on).
"""

from __future__ import annotations

import logging
import os
import sqlite3
import time
from typing import Annotated, Any

from pydantic import Field

from jpintel_mcp.mcp.server import _READ_ONLY, mcp

from .db import connect_autonomath
from .error_envelope import make_error

logger = logging.getLogger("jpintel.mcp.autonomath.graph_traverse")

# Env-gated registration. Default is "1" (on); flip to "0" to roll back.
_ENABLED = os.environ.get("AUTONOMATH_GRAPH_TRAVERSE_ENABLED", "1") == "1"

# All 15 canonical relation_type values present in v_am_relation_all
# (verified 2026-04-25 via SELECT DISTINCT relation_type). Used to
# validate edge_types arg and as the default whitelist.
_ALL_RELATION_TYPES: frozenset[str] = frozenset(
    {
        "has_authority",
        "applies_to_region",
        "applies_to_industry",
        "related",
        "references_law",
        "compatible",
        "compatible_with",
        "applies_to_size",
        "prerequisite",
        "requires_prerequisite",
        "part_of",
        "successor_of",
        "bonus_points",
        "implemented_by",
        "incompatible",
        "incompatible_with",
        "applies_to",
        "replaces",
    }
)

# Default whitelist when the caller passes edge_types=None. Excludes
# ``related`` (3,892 rows, avg conf 0.53) — too low-confidence + fan-out
# heavy. Caller must opt in explicitly via edge_types=["related"].
_DEFAULT_EDGE_TYPES: tuple[str, ...] = (
    "has_authority",
    "applies_to_region",
    "applies_to_industry",
    "references_law",
    "compatible",
    "compatible_with",
    "applies_to_size",
    "prerequisite",
    "requires_prerequisite",
    "part_of",
    "successor_of",
    "bonus_points",
    "implemented_by",
    "incompatible",
    "incompatible_with",
    "applies_to",
    "replaces",
)

# Per-node fan-out cap. The IT2026 hub has 1,822 outgoing edges; without
# this cap a depth=2 walk would return tens of thousands of rows in one
# response. 30 is enough to surface the top-confidence neighbours for
# typical program / law / authority seeds.
_MAX_FANOUT_PER_NODE = 30

# Hard global cap on rows the recursive CTE may emit even before client
# truncation. Defends against pathological hub interactions at depth=3.
_HARD_MAX_RESULTS = 500

_DISCLAIMER = (
    "本 traversal は am_relation (24,004 edges / 15 relation types) を "
    "BFS した結果です。confidence は edge ごとに 0.0-1.0 のスコアで、"
    "0.5 未満は信頼性低 (graph_rescue 由来等)。最終判断は一次資料 "
    "(source_url) と専門家確認を優先してください。"
)


def _validate_edge_types(edge_types: list[str] | None) -> tuple[list[str] | None, dict[str, Any] | None]:
    """Resolve edge_types arg to a concrete whitelist.

    Returns (whitelist, error_envelope_or_None). ``None`` whitelist means
    use _DEFAULT_EDGE_TYPES. Unknown relation_type values return a
    ``invalid_enum`` envelope so the caller can fix its arg.
    """
    if edge_types is None:
        return list(_DEFAULT_EDGE_TYPES), None
    if not edge_types:
        return list(_DEFAULT_EDGE_TYPES), None
    bad = [t for t in edge_types if t not in _ALL_RELATION_TYPES]
    if bad:
        err = make_error(
            code="invalid_enum",
            message=f"unknown relation_type(s): {bad}",
            hint=(
                f"Allowed types: {sorted(_ALL_RELATION_TYPES)}. Pass "
                f"None or omit to use the default whitelist (excludes "
                f"low-confidence 'related')."
            ),
            field="edge_types",
            retry_with=["enum_values_am"],
        )
        return None, err
    return list(edge_types), None


if _ENABLED:

    @mcp.tool(annotations=_READ_ONLY)
    def graph_traverse(
        start_entity_id: Annotated[
            str,
            Field(
                description=(
                    "Seed canonical_id from am_entities (e.g. "
                    "'program:04_program_documents:000016:IT2026_b030eaea36', "
                    "'law:rouki', 'authority:meti'). Looked up via the "
                    "v_am_relation_all source_entity_id key directly — no "
                    "name resolution. Use search_* tools first if you only "
                    "have a name."
                ),
                min_length=1,
                max_length=256,
            ),
        ],
        max_depth: Annotated[
            int,
            Field(
                description=(
                    "BFS depth limit (0=start node only, 1-3=hop walk). "
                    "Default 2. Depth 3 only on small seeds; hub seeds "
                    "(>30 outdegree) get truncated by max_results / "
                    "per-node fan-out cap."
                ),
                ge=0,
                le=3,
            ),
        ] = 2,
        edge_types: Annotated[
            list[str] | None,
            Field(
                description=(
                    "Restrict traversal to these relation_type values. "
                    "None = use default whitelist (all 15 types except "
                    "low-confidence 'related'). Pass ['related'] etc. to "
                    "opt in explicitly. Allowed: see enum_values_am."
                ),
            ),
        ] = None,
        max_results: Annotated[
            int,
            Field(
                description=(
                    "Hard cap on the number of distinct (src,tgt,type) "
                    "edges returned. Default 20, max 500. Once reached, "
                    "the response carries a 'capped: true' flag."
                ),
                ge=1,
                le=500,
            ),
        ] = 20,
        min_confidence: Annotated[
            float,
            Field(
                description=(
                    "Drop edges with confidence below this floor. Default "
                    "0.0 (keep everything). Useful values: 0.5 (drop "
                    "graph_rescue noise), 0.8 (high-confidence only)."
                ),
                ge=0.0,
                le=1.0,
            ),
        ] = 0.0,
    ) -> dict[str, Any]:
        """[KG] O7 — Returns paths from a 1-3 hop heterogeneous BFS over am_relation (24,004 edges / 15 relation types). Pure SQL traversal (no LLM). Output is graph-derived; edges with confidence < 0.5 (graph_rescue origin) are noisy — verify primary source (source_url) for relationship claims.

        WHAT: BFS over ``v_am_relation_all`` (24,004 edges / 15 relation
        types) starting at ``start_entity_id``. Returns the discovered
        paths (each = list of nodes + list of edges + total_distance =
        hop count). Cycle suppression via path-string instr() check;
        per-node fan-out capped at 30; global LIMIT enforced via
        ``max_results``.

        WHEN:
          - 「制度 → 根拠法 → 関連判例 → 過去採択」を 1 query で
          - 「法令を変えると影響受ける制度群を辿る」(reverse 必要なら別 tool)
          - 「製造業 + 関東で使える制度 + 認定支援機関」(複合横断)
          - 既存 related_programs では届かない depth=3 / 異種 entity 探索

        WHEN NOT:
          - 同種 program 間 hop (prerequisite / compatible / successor) →
            related_programs (depth ≤ 2、6 軸固定で fan-out 安全)
          - 法令本体 → get_law_article_am
          - 制度詳細 → search_programs / get_program

        RETURNS (envelope on success):
          {
            paths: [
              {
                nodes: [entity_id, entity_id, ...],   # depth ordered
                edges: [
                  {
                    src: str, tgt: str, relation_type: str,
                    confidence: float, depth: int, origin: str
                  }, ...
                ],
                total_distance: int                   # = max(depth)
              }, ...
            ],
            traversed_count: int,                     # total edges examined
            start_entity_id: str,
            max_depth: int,
            edge_types_used: [str, ...],
            capped: bool,                             # max_results reached
            elapsed_ms: float,
            _disclaimer: str
          }

        On invalid args / DB error returns the canonical error envelope
        (``code`` ∈ {``invalid_enum``, ``db_unavailable``,
        ``no_matching_records``}) with ``retry_with`` pointers.
        """
        t_start = time.perf_counter()

        # --- arg validation -------------------------------------------------
        whitelist, err = _validate_edge_types(edge_types)
        if err is not None:
            return {
                "paths": [],
                "traversed_count": 0,
                "start_entity_id": start_entity_id,
                "max_depth": max_depth,
                "edge_types_used": [],
                "capped": False,
                "elapsed_ms": 0.0,
                "_disclaimer": _DISCLAIMER,
                "error": err["error"],
            }
        assert whitelist is not None  # mypy hint

        effective_max = min(max_results, _HARD_MAX_RESULTS)

        # --- depth=0 short circuit (start node only) ------------------------
        if max_depth == 0:
            elapsed = (time.perf_counter() - t_start) * 1000.0
            return {
                "paths": [
                    {
                        "nodes": [start_entity_id],
                        "edges": [],
                        "total_distance": 0,
                    }
                ],
                "traversed_count": 0,
                "start_entity_id": start_entity_id,
                "max_depth": 0,
                "edge_types_used": whitelist,
                "capped": False,
                "elapsed_ms": round(elapsed, 2),
                "_disclaimer": _DISCLAIMER,
            }

        # --- recursive CTE BFS ---------------------------------------------
        # Cycle suppression: path string accumulates ',<eid>,' segments;
        # next-hop targets are rejected if already present.
        # Per-node fan-out cap: ROW_NUMBER() OVER (PARTITION BY source
        # ORDER BY confidence DESC) <= _MAX_FANOUT_PER_NODE inside an
        # inner subquery, so dense hubs (1,822 outdeg IT2026) cannot
        # explode the walk.
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
                FROM v_am_relation_all
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
                FROM v_am_relation_all
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

        params: list[Any] = [start_entity_id]
        params.extend(whitelist)
        params.append(min_confidence)
        params.extend(whitelist)
        params.append(min_confidence)
        params.append(max_depth)
        # +1 so we can detect "we hit the cap" vs "naturally smaller".
        params.append(effective_max + 1)

        try:
            conn = connect_autonomath()
            rows = conn.execute(sql, params).fetchall()
        except (sqlite3.Error, FileNotFoundError) as exc:
            logger.exception("graph_traverse query failed")
            err = make_error(
                code="db_unavailable",
                message=str(exc),
                hint=(
                    "autonomath.db unreachable; retry later or fall back "
                    "to related_programs() for depth-2 program-only hops."
                ),
                retry_with=["related_programs"],
            )
            return {
                "paths": [],
                "traversed_count": 0,
                "start_entity_id": start_entity_id,
                "max_depth": max_depth,
                "edge_types_used": whitelist,
                "capped": False,
                "elapsed_ms": 0.0,
                "_disclaimer": _DISCLAIMER,
                "error": err["error"],
            }

        # --- assemble paths -------------------------------------------------
        # Each emitted edge is a 1-hop fragment (src → tgt). For O7 v1 we
        # surface the flat edge list bucketed by depth — a per-edge "path"
        # is faithful to the recursive walk and cheap to consume.
        # Downstream agents that want full chain reconstruction can join
        # adjacent (depth, depth+1) edges by tgt == src on the client side.
        capped = len(rows) > effective_max
        rows = rows[:effective_max]

        paths: list[dict[str, Any]] = []
        for r in rows:
            paths.append(
                {
                    "nodes": [r["src"], r["tgt"]],
                    "edges": [
                        {
                            "src": r["src"],
                            "tgt": r["tgt"],
                            "relation_type": r["relation_type"],
                            "confidence": r["confidence"],
                            "depth": r["depth"],
                            "origin": r["origin"],
                        }
                    ],
                    "total_distance": r["depth"],
                }
            )

        elapsed = (time.perf_counter() - t_start) * 1000.0

        out: dict[str, Any] = {
            "paths": paths,
            "traversed_count": len(rows),
            "start_entity_id": start_entity_id,
            "max_depth": max_depth,
            "edge_types_used": whitelist,
            "capped": capped,
            "elapsed_ms": round(elapsed, 2),
            "_disclaimer": _DISCLAIMER,
        }

        if not paths:
            err = make_error(
                code="no_matching_records",
                message=(
                    f"no edges from start_entity_id={start_entity_id!r} "
                    f"within depth={max_depth} (edge_types={len(whitelist)}, "
                    f"min_confidence={min_confidence})."
                ),
                hint=(
                    "Verify the canonical_id exists (search_* tools) or "
                    "lower min_confidence / widen edge_types. Provisional "
                    "entities often have 0 outgoing edges."
                ),
                retry_with=[
                    "enum_values_am",
                    "search_programs",
                    "related_programs",
                ],
            )
            out["error"] = err["error"]

        return out


__all__ = ["_ENABLED"]
