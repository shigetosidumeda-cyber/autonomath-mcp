"""REST endpoint for the multi-axis Discover Related composer (no LLM).

``GET /v1/discover/related/{entity_id}?k=20`` returns one Evidence Packet
shaped envelope containing 5 axes of related entities so an agent (the
customer LLM) can reach "everything related to this entity" in a single
fetch — instead of orchestrating 5 separate tool calls (related_programs
+ vec k-NN + funding stack + density neighbours + 5-hop graph).

Axes
----

Each axis surfaces UP TO 5 rows; the envelope therefore caps at ~25 rows
even when ``k`` is larger. The cap is intentional — the discover surface
exists to give the agent a starting set; deeper exploration happens by
following one of the per-row IDs back into the dedicated tool (e.g.
``graph_traverse`` / ``check_funding_stack_am`` / ``related_programs``).

  * ``via_law_ref`` — programs that share at least one law reference with
    the seed (``program_law_refs`` join in jpintel.db). Useful for
    "this 補助金 と同じ根拠法に基づく他制度".
  * ``via_vector`` — k-NN over ``am_entities_vec_*`` (sqlite-vec). Best
    for "似たコンセプトの制度" when the seed is in a vec tier (S/L/C/T/K/J/A).
  * ``via_co_adoption`` — ``am_funding_stack_empirical`` co-adoption
    pairs (>=5 distinct houjin co-adopted in practice). Empirical signal
    that beats rule-only matrix lookups.
  * ``via_density_neighbors`` — neighbours by ``am_entity_density_score``
    rank (entities of the same record_kind close in graph density).
    Surfaces "similarly well-wired" peers — proxy for popularity / hub
    status.
  * ``via_5hop`` — pre-computed 5-hop walks from
    ``am_5hop_graph`` (Wave 24 §152). Returns hop=2 / hop=3 destinations
    so the agent can see medium-range connections without re-walking
    the recursive CTE itself.

Pure SQL — NO LLM call. Pure SQLite + sqlite-vec. Each upstream axis is
independently fail-open: if its table is missing or empty, the axis is
returned with an empty list rather than failing the whole call.

Envelope
--------

``audit_seal`` + ``corpus_snapshot_id`` + ``_disclaimer`` + ``_billing_unit``
are present on every 2xx response — same Evidence Packet contract used by
``/v1/evidence/packets/...``.

Pricing: ¥3/req metered (1 unit total, regardless of how many axes
populate). Anonymous tier shares the 3/日 IP cap via AnonIpLimitDep on
the router mount in ``api/main.py``.
"""

from __future__ import annotations

import logging
import sqlite3
import time
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, status
from fastapi import Path as PathParam

from jpintel_mcp.api._audit_seal import attach_seal_to_body, get_corpus_snapshot_id
from jpintel_mcp.api.deps import ApiContextDep, DbDep, log_usage
from jpintel_mcp.config import settings

logger = logging.getLogger("jpintel.api.discover")

router = APIRouter(prefix="/v1/discover", tags=["discover"])


# Per-axis cap. Discover is a starter surface; deeper exploration goes
# through the dedicated per-axis tools. 5 keeps the envelope bounded.
_PER_AXIS_CAP = 5

# Vec k-NN — match rerank-friendly behaviour. We pull a slightly larger
# candidate set then trim to _PER_AXIS_CAP. 32 is a balance between recall
# and the per-call sqlite-vec scan cost on tier tables.
_VEC_CANDIDATES = 32

_DISCLAIMER = (
    "discover/related は am_5hop_graph / am_funding_stack_empirical / "
    "am_entity_density_score / am_entities_vec_* / program_law_refs を 5 軸で "
    "走査した starter set です。axis ごとに上位 5 件、合計最大 25 件。"
    "深掘りは per-axis tool (graph_traverse / check_funding_stack_am / "
    "related_programs) に委ねること。最終判断は一次資料 (source_url) と "
    "専門家確認を必ず経てください。"
)


# ---------------------------------------------------------------------------
# DB connection helpers
# ---------------------------------------------------------------------------


def _open_autonomath_ro() -> sqlite3.Connection | None:
    """Open ``autonomath.db`` read-only with the sqlite-vec extension loaded
    when available. Returns ``None`` if the DB file is missing — the axis
    builders then degrade to empty lists.
    """
    p: Path = settings.autonomath_db_path
    if not p.exists() or p.stat().st_size == 0:
        return None
    uri = f"file:{p}?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True, timeout=5.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA query_only=1")
            conn.execute("PRAGMA temp_store=MEMORY")
        except sqlite3.OperationalError:
            pass
        # Best-effort vec0 extension load — required for via_vector axis.
        # Failure simply means via_vector returns []; we never raise.
        import os

        vec0 = os.environ.get("AUTONOMATH_VEC0_PATH")
        if vec0 and Path(vec0).exists():
            try:
                conn.enable_load_extension(True)
                conn.load_extension(vec0)
                conn.enable_load_extension(False)
            except (sqlite3.OperationalError, AttributeError):
                pass
        return conn
    except sqlite3.OperationalError:
        return None


# ---------------------------------------------------------------------------
# Entity resolution — accept UNI- (jpintel) or canonical (am_entities) ids.
# ---------------------------------------------------------------------------


def _resolve_entity(am_conn: sqlite3.Connection | None, entity_id: str) -> dict[str, str | None]:
    """Resolve ``entity_id`` to both its jpintel ``unified_id`` (when known)
    and its autonomath ``canonical_id`` (when known). Either may be None.

    Three input shapes:
      - ``UNI-xxx`` jpintel unified_id → look up ``entity_id_map``.
      - ``program:...`` / ``law:...`` / ``corporate_entity:...`` etc
        canonical_id → reverse-look up ``entity_id_map`` for the UNI id.
      - Anything else → return both as-is so axes can still try.
    """
    out: dict[str, str | None] = {"uni_id": None, "canonical_id": None}
    if not entity_id:
        return out
    eid = entity_id.strip()
    if eid.startswith("UNI-"):
        out["uni_id"] = eid
        if am_conn is not None:
            try:
                row = am_conn.execute(
                    "SELECT am_canonical_id FROM entity_id_map WHERE jpi_unified_id = ? LIMIT 1",
                    (eid,),
                ).fetchone()
                if row and row[0]:
                    out["canonical_id"] = row[0]
            except sqlite3.OperationalError:
                pass
    else:
        out["canonical_id"] = eid
        if am_conn is not None:
            try:
                row = am_conn.execute(
                    "SELECT jpi_unified_id FROM entity_id_map WHERE am_canonical_id = ? LIMIT 1",
                    (eid,),
                ).fetchone()
                if row and row[0]:
                    out["uni_id"] = row[0]
            except sqlite3.OperationalError:
                pass
    return out


# ---------------------------------------------------------------------------
# Axis builders — each returns a (possibly empty) list of dicts. None of
# them ever raises; on missing-table or schema-drift we return [] silently.
# Caller logs the absence via the envelope summary.
# ---------------------------------------------------------------------------


def _axis_via_law_ref(
    jpintel_conn: sqlite3.Connection, uni_id: str | None, k: int
) -> list[dict[str, Any]]:
    """Programs that cite at least one law in common with the seed.

    Pure SQL self-join on ``program_law_refs`` (jpintel.db). Returns up to
    ``k`` other programs ordered by the count of shared laws DESC.
    """
    if not uni_id:
        return []
    try:
        rows = jpintel_conn.execute(
            """
            SELECT
                p2.program_unified_id AS entity_id,
                pr.primary_name       AS primary_name,
                pr.tier               AS tier,
                COUNT(DISTINCT p2.law_unified_id) AS shared_laws,
                MIN(p2.source_url)    AS source_url
              FROM program_law_refs p1
              JOIN program_law_refs p2
                ON p1.law_unified_id = p2.law_unified_id
               AND p2.program_unified_id != p1.program_unified_id
              LEFT JOIN programs pr
                ON pr.unified_id = p2.program_unified_id
             WHERE p1.program_unified_id = ?
             GROUP BY p2.program_unified_id
             ORDER BY shared_laws DESC, p2.program_unified_id ASC
             LIMIT ?
            """,
            (uni_id, k),
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    out: list[dict[str, Any]] = []
    for r in rows:
        d = dict(r)
        d["axis"] = "via_law_ref"
        out.append(d)
    return out


def _axis_via_vector(
    am_conn: sqlite3.Connection, canonical_id: str | None, k: int
) -> list[dict[str, Any]]:
    """k-NN over the appropriate ``am_entities_vec_*`` tier table.

    Uses the canonical ``record_kind`` of the seed to pick the tier:
      program → S, law → L, case_study → C, etc. (matches the corpus_specs
      convention in tools/offline/embed_corpus_local.py).

    We need the seed's row in the chosen tier to read its embedding; if
    the seed isn't embedded yet (typical for sparse cohorts) the axis is
    empty.
    """
    if not canonical_id:
        return []
    # Map seed canonical_id prefix → tier suffix.
    prefix_to_tier = {
        "program:": "S",
        "law:": "L",
        "case_study:": "C",
        # Some kinds map to NTA tiers via record_kind (set below).
    }
    tier: str | None = None
    for pref, t in prefix_to_tier.items():
        if canonical_id.startswith(pref):
            tier = t
            break
    if tier is None:
        # Try record_kind from am_entities (e.g. tsutatsu / saiketsu /
        # adoption / court_decision rows).
        try:
            row = am_conn.execute(
                "SELECT record_kind FROM am_entities WHERE canonical_id = ? LIMIT 1",
                (canonical_id,),
            ).fetchone()
        except sqlite3.OperationalError:
            return []
        if not row or not row[0]:
            return []
        record_kind = row[0]
        rk_to_tier = {
            "program": "S",
            "law": "L",
            "case_study": "C",
            "tsutatsu": "T",
            "saiketsu": "K",
            "court_decision": "J",
            "adoption": "A",
        }
        tier = rk_to_tier.get(record_kind)
        if tier is None:
            return []

    # vec0 needs an integer rowid; canonical_id is stored elsewhere so we
    # need the entity_id INT mapping. The vec tables key on the integer
    # rowid that matches am_entities.rowid. Read the seed's rowid first.
    try:
        seed = am_conn.execute(
            "SELECT rowid FROM am_entities WHERE canonical_id = ? LIMIT 1",
            (canonical_id,),
        ).fetchone()
    except sqlite3.OperationalError:
        return []
    if not seed:
        return []
    seed_rowid = seed[0]

    vec_table = f"am_entities_vec_{tier}"
    # 1. Read seed embedding from the tier table.
    try:
        emb_row = am_conn.execute(
            f"SELECT embedding FROM {vec_table} WHERE entity_id = ? LIMIT 1",
            (seed_rowid,),
        ).fetchone()
    except sqlite3.OperationalError:
        return []
    if not emb_row or emb_row[0] is None:
        return []
    seed_emb = emb_row[0]

    # 2. k-NN against the same tier table; skip the seed itself.
    try:
        rows = am_conn.execute(
            f"""
            SELECT
                v.entity_id   AS rowid,
                v.distance    AS distance,
                e.canonical_id AS entity_id,
                e.primary_name AS primary_name,
                e.record_kind  AS record_kind,
                e.source_url   AS source_url
              FROM {vec_table} v
              JOIN am_entities e ON e.rowid = v.entity_id
             WHERE v.embedding MATCH ?
               AND v.entity_id != ?
               AND k = ?
             ORDER BY v.distance ASC
            """,
            (seed_emb, seed_rowid, _VEC_CANDIDATES),
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    out: list[dict[str, Any]] = []
    for r in rows[:k]:
        d = dict(r)
        d["axis"] = "via_vector"
        d["tier"] = tier
        out.append(d)
    return out


def _axis_via_co_adoption(
    am_conn: sqlite3.Connection, canonical_id: str | None, uni_id: str | None, k: int
) -> list[dict[str, Any]]:
    """Co-adoption pairs from ``am_funding_stack_empirical``.

    The table stores normalized (program_a < program_b) pairs whose
    underlying program_id values come from ``jpi_adoption_records`` —
    those are typically ``UNI-...`` ids. We try both the UNI id and the
    canonical id when matching so the axis works regardless of input
    shape.
    """
    seed_ids = [v for v in (uni_id, canonical_id) if v]
    if not seed_ids:
        return []
    placeholders = ",".join("?" * len(seed_ids))
    try:
        rows = am_conn.execute(
            f"""
            SELECT
                CASE WHEN program_a_id IN ({placeholders})
                     THEN program_b_id ELSE program_a_id END AS entity_id,
                co_adoption_count,
                mean_days_between,
                compat_matrix_says,
                conflict_flag
              FROM am_funding_stack_empirical
             WHERE program_a_id IN ({placeholders})
                OR program_b_id IN ({placeholders})
             ORDER BY co_adoption_count DESC
             LIMIT ?
            """,
            (*seed_ids, *seed_ids, *seed_ids, k),
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    out: list[dict[str, Any]] = []
    for r in rows:
        d = dict(r)
        d["axis"] = "via_co_adoption"
        out.append(d)
    return out


def _axis_via_density_neighbors(
    am_conn: sqlite3.Connection, canonical_id: str | None, k: int
) -> list[dict[str, Any]]:
    """Entities of the same ``record_kind`` adjacent to the seed by
    ``density_rank``. Surfaces "similarly well-wired" peers — useful when
    "give me other big-hub programs" is the intent.
    """
    if not canonical_id:
        return []
    try:
        seed = am_conn.execute(
            "SELECT record_kind, density_rank FROM am_entity_density_score "
            "WHERE entity_id = ? LIMIT 1",
            (canonical_id,),
        ).fetchone()
    except sqlite3.OperationalError:
        return []
    if not seed or seed[1] is None:
        return []
    record_kind = seed[0]
    rank = int(seed[1])
    try:
        rows = am_conn.execute(
            """
            SELECT
                d.entity_id    AS entity_id,
                d.record_kind  AS record_kind,
                d.density_score,
                d.density_rank,
                e.primary_name AS primary_name,
                e.source_url   AS source_url
              FROM am_entity_density_score d
              LEFT JOIN am_entities e ON e.canonical_id = d.entity_id
             WHERE d.record_kind = ?
               AND d.entity_id != ?
               AND d.density_rank IS NOT NULL
             ORDER BY ABS(d.density_rank - ?) ASC
             LIMIT ?
            """,
            (record_kind, canonical_id, rank, k),
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    out: list[dict[str, Any]] = []
    for r in rows:
        d = dict(r)
        d["axis"] = "via_density_neighbors"
        out.append(d)
    return out


def _axis_via_5hop(
    am_conn: sqlite3.Connection, canonical_id: str | None, k: int
) -> list[dict[str, Any]]:
    """Pre-computed 5-hop walk destinations from ``am_5hop_graph``.

    We surface hop>=2 only (hop=1 would duplicate ``related_programs`` /
    ``via_law_ref``). Ordered by hop ASC so the closest non-trivial
    destinations come first.
    """
    if not canonical_id:
        return []
    try:
        rows = am_conn.execute(
            """
            SELECT
                end_entity_id AS entity_id,
                hop,
                path,
                edge_kinds
              FROM am_5hop_graph
             WHERE start_entity_id = ?
               AND hop >= 2
             ORDER BY hop ASC, end_entity_id ASC
             LIMIT ?
            """,
            (canonical_id, k),
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    out: list[dict[str, Any]] = []
    for r in rows:
        d = dict(r)
        d["axis"] = "via_5hop"
        out.append(d)
    return out


# ---------------------------------------------------------------------------
# Composer — orchestrates all 5 axes and assembles the envelope.
# ---------------------------------------------------------------------------


def _compose_discover_related(
    *,
    entity_id: str,
    k: int,
    jpintel_conn: sqlite3.Connection,
) -> dict[str, Any]:
    """Build the discover envelope for ``entity_id``. Each axis is fail-open;
    a missing/empty table simply yields an empty list for that axis.

    Returns the body dict WITHOUT ``audit_seal`` — the route handler
    attaches that via :func:`attach_seal_to_body`.
    """
    per_axis = max(1, min(_PER_AXIS_CAP, k))
    am_conn = _open_autonomath_ro()
    try:
        ids = _resolve_entity(am_conn, entity_id)
        uni_id = ids["uni_id"]
        canonical_id = ids["canonical_id"]

        # via_law_ref reads jpintel.db (program_law_refs lives there).
        via_law_ref = _axis_via_law_ref(jpintel_conn, uni_id, per_axis)

        if am_conn is not None:
            via_vector = _axis_via_vector(am_conn, canonical_id, per_axis)
            via_co_adoption = _axis_via_co_adoption(am_conn, canonical_id, uni_id, per_axis)
            via_density_neighbors = _axis_via_density_neighbors(am_conn, canonical_id, per_axis)
            via_5hop = _axis_via_5hop(am_conn, canonical_id, per_axis)
        else:
            via_vector = []
            via_co_adoption = []
            via_density_neighbors = []
            via_5hop = []
    finally:
        if am_conn is not None:
            am_conn.close()

    related: dict[str, list[dict[str, Any]]] = {
        "via_law_ref": via_law_ref,
        "via_vector": via_vector,
        "via_co_adoption": via_co_adoption,
        "via_density_neighbors": via_density_neighbors,
        "via_5hop": via_5hop,
    }
    total = sum(len(v) for v in related.values())
    body: dict[str, Any] = {
        "entity_id": entity_id,
        "resolved": {
            "uni_id": uni_id,
            "canonical_id": canonical_id,
        },
        "related": related,
        "total": total,
        "k": k,
        "per_axis_cap": _PER_AXIS_CAP,
        "corpus_snapshot_id": get_corpus_snapshot_id(),
        "_billing_unit": 1,
        "_disclaimer": _DISCLAIMER,
    }
    return body


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------


@router.get(
    "/related/{entity_id}",
    summary="Multi-axis related entities (5 axes, NO LLM)",
    description=(
        "Return up to 5 axes × 5 rows of related entities for the given "
        "entity in one call.\n\n"
        "**Pricing:** ¥3/call (1 unit total). Anonymous callers share the "
        "3/日 per-IP cap (JST 翌日 00:00 リセット).\n\n"
        "**entity_id** accepts a unified_id (`UNI-...`) or an autonomath "
        "canonical id (`program:...`, `law:...`, etc.).\n\n"
        "**Axes returned:**\n"
        "* `via_law_ref` — programs sharing 根拠法 (program_law_refs).\n"
        "* `via_vector` — k-NN over sqlite-vec embeddings (per-tier).\n"
        "* `via_co_adoption` — empirical co-adoption pairs from "
        "  am_funding_stack_empirical.\n"
        "* `via_density_neighbors` — same record_kind neighbours by "
        "  density_rank.\n"
        "* `via_5hop` — pre-computed 5-hop graph destinations.\n\n"
        "Each axis is fail-open: missing tables / empty corpora yield an "
        "empty axis list rather than a 5xx."
    ),
)
def discover_related(
    entity_id: Annotated[
        str,
        PathParam(
            min_length=1,
            max_length=200,
            description=(
                "Entity identifier — a unified_id (UNI-...) or a "
                "canonical_id (program:..., law:..., etc.)."
            ),
            examples=["UNI-00d62c90c3", "program:test:p1"],
        ),
    ],
    conn: DbDep,
    ctx: ApiContextDep,
    k: Annotated[
        int,
        Query(
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
    """Compose and return the 5-axis related envelope for ``entity_id``."""
    if not entity_id or not entity_id.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "missing_required_arg",
                "message": "entity_id is required.",
            },
        )

    t0 = time.perf_counter()
    body = _compose_discover_related(entity_id=entity_id, k=k, jpintel_conn=conn)
    latency_ms = int((time.perf_counter() - t0) * 1000)

    log_usage(
        conn,
        ctx,
        "discover.related",
        params={"entity_id": entity_id, "k": k},
        latency_ms=latency_ms,
        result_count=int(body["total"]),
        quantity=1,
        strict_metering=True,
    )

    # §17.D audit seal on paid responses (no-op for anon callers).
    attach_seal_to_body(
        body,
        endpoint="discover.related",
        request_params={"entity_id": entity_id, "k": k},
        api_key_hash=ctx.key_hash,
        conn=conn,
    )
    return body


__all__ = [
    "router",
    "_compose_discover_related",
    "_resolve_entity",
    "_open_autonomath_ro",
]
