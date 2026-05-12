"""discover_related — Multi-axis Discover Related MCP tool (no LLM).

Mirrors the REST surface at ``GET /v1/discover/related/{entity_id}`` so
MCP clients can pull the same 5-axis envelope without round-tripping
through HTTP. SAME composer is invoked on both sides — never a parallel
implementation.

Pure SQLite + sqlite-vec. NO LLM call.

Billing: 1 ¥3 unit per call (mirrors REST). Anonymous IPs share the 3/day
cap via the standard MCP gate.
"""

from __future__ import annotations

import contextlib
import logging
import sqlite3
from typing import Annotated, Any

from pydantic import Field

from jpintel_mcp._jpcite_env_bridge import get_flag
from jpintel_mcp.config import settings
from jpintel_mcp.mcp.autonomath_tools.error_envelope import make_error
from jpintel_mcp.mcp.server import _READ_ONLY, mcp

logger = logging.getLogger("jpintel.mcp.am.discover")

#: Env-gate. Default ON; flip "0" to disable without redeploy. Pairs with
#: the global AUTONOMATH_ENABLED gate at the package boundary.
_ENABLED = get_flag("JPCITE_DISCOVER_ENABLED", "AUTONOMATH_DISCOVER_ENABLED", "1") == "1"


def _impl_discover_related(entity_id: str, k: int = 20) -> dict[str, Any]:
    """Pure-Python core. Split out so tests can call it directly without
    going through the @mcp.tool wrapper.

    Opens a short-lived jpintel.db connection (the REST handler reuses
    its FastAPI dependency-injected ``conn`` instead). The composer in
    ``api/discover.py`` reads the autonomath.db side internally.
    """
    eid = (entity_id or "").strip()
    if not eid:
        return make_error(
            code="missing_required_arg",
            message="entity_id is required.",
            field="entity_id",
            hint=(
                "Pass a unified_id (UNI-...) or a canonical_id "
                "(program:..., law:..., etc.) from any search_* tool."
            ),
        )
    try:
        k_int = int(k)
    except (TypeError, ValueError):
        return make_error(
            code="out_of_range",
            message="k must be an integer.",
            field="k",
        )
    if k_int < 1 or k_int > 100:
        return make_error(
            code="out_of_range",
            message="k must be in [1, 100].",
            field="k",
        )

    # Open a read-only jpintel.db connection just for the via_law_ref
    # axis. Short-lived; closed in finally below.
    db_path = settings.db_path
    if not db_path.exists():
        return make_error(
            code="db_unavailable",
            message=(
                "discover_related の jpintel.db が見つかりません。"
                "JPINTEL_DB_PATH 環境変数を確認してください。"
            ),
            hint="JPINTEL_DB_PATH",
        )
    uri = f"file:{db_path}?mode=ro"
    try:
        jpintel_conn = sqlite3.connect(uri, uri=True, timeout=5.0, isolation_level=None)
        jpintel_conn.row_factory = sqlite3.Row
        with contextlib.suppress(sqlite3.OperationalError):
            jpintel_conn.execute("PRAGMA query_only=1")
    except sqlite3.OperationalError as exc:
        return make_error(
            code="db_unavailable",
            message=f"discover_related: jpintel.db open failed ({exc})",
        )

    try:
        # Late import to avoid circular import at MCP server bootstrap
        # time (api/discover imports api/_audit_seal which can pull in
        # autonomath_tools indirectly via cs_features).
        from jpintel_mcp.api.discover import _compose_discover_related

        body = _compose_discover_related(entity_id=eid, k=k_int, jpintel_conn=jpintel_conn)
    finally:
        with contextlib.suppress(sqlite3.Error):
            jpintel_conn.close()
    return body


# ---------------------------------------------------------------------------
# MCP tool registration. Gated by AUTONOMATH_DISCOVER_ENABLED + the global
# AUTONOMATH_ENABLED.
# ---------------------------------------------------------------------------

if _ENABLED and settings.autonomath_enabled:

    @mcp.tool(annotations=_READ_ONLY)
    def discover_related(
        entity_id: Annotated[
            str,
            Field(
                min_length=1,
                max_length=200,
                description=(
                    "Entity identifier. Accepts a jpintel unified_id "
                    "(UNI-...) or an autonomath canonical_id (program:..., "
                    "law:..., etc.) from any search_* tool."
                ),
            ),
        ],
        k: Annotated[
            int,
            Field(
                ge=1,
                le=100,
                description=(
                    "Total target row budget (also a soft hint to vec k-NN "
                    "candidate set). Per-axis cap is fixed at 5 — "
                    "increasing k does not raise the per-axis output."
                ),
            ),
        ] = 20,
    ) -> dict[str, Any]:
        """[DISCOVER-RELATED] Returns up to 5 axes × 5 rows of related entities for the given entity in one call. Pure SQL + sqlite-vec, NO LLM. 1 ¥3 unit per call. SAME composer as REST GET /v1/discover/related/{entity_id}.

        WHAT: Joins 5 already-shipped substrates into one envelope —
        ``program_law_refs`` (jpintel.db), ``am_entities_vec_*``
        (sqlite-vec k-NN), ``am_funding_stack_empirical`` (co-adoption),
        ``am_entity_density_score`` (graph-density neighbours), and
        ``am_5hop_graph`` (precomputed multi-hop graph). Each axis is fail-open:
        a missing/empty table yields an empty list, never a 5xx.

        WHEN:
          - "この補助金 / 制度の関連を一発で全部見たい" (LLM への入力前処理)
          - 5 つの per-axis tool を順番に叩く前の starter set
          - 監査再現用の corpus_snapshot_id 付き snapshot (audit_seal 同梱)

        WHEN NOT:
          - 単発の制度詳細 → get_program / search_programs
          - 単発の併用可否 → check_funding_stack_am
          - 深い graph walk (depth>=3 / 異種 entity) → graph_traverse
          - 1 軸のみで十分 → related_programs (depth ≤ 2、6 軸固定)

        RETURNS (envelope):
          {
            entity_id, resolved: { uni_id, canonical_id },
            related: {
              via_law_ref: [...],         // program_law_refs 経由
              via_vector:  [...],          // sqlite-vec k-NN
              via_co_adoption: [...],      // funding_stack_empirical
              via_density_neighbors: [...],// density_score の近傍
              via_5hop: [...]              // am_5hop_graph
            },
            total, k, per_axis_cap,
            corpus_snapshot_id,
            _disclaimer, _billing_unit
          }

        DATA QUALITY HONESTY: discover/related は starter set です。
        各 axis 上位 5 件、合計最大 25 件。深掘りは per-axis tool に委ねる
        こと。``_disclaimer`` は必須 — 最終判断は一次資料 (source_url) と
        専門家確認を必ず経てください。
        """
        return _impl_discover_related(entity_id=entity_id, k=k)


__all__ = ["_impl_discover_related"]
