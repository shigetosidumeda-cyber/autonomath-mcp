"""get_provenance / get_provenance_for_fact — V4 Phase 4 universal MCP tools.

Single window for "where did this entity / fact come from?". Backed by the
2026-04-25 V4 license columns:

  - ``am_source.license`` (migration 049, 99.17% filled — see CLAUDE.md):
    ``pdl_v1.0`` (87,251) / ``gov_standard_v2.0`` (7,457) /
    ``public_domain`` (953) / ``proprietary`` (618) / ``cc_by_4.0`` (186) /
    ``unknown`` (805) / NULL (2). Trigger-enforced closed enum.
  - ``am_entity_facts.source_id`` (per-fact provenance, NULL on legacy rows
    pre-2026-04-25; new ingest fills it). Falls back to the entity-level
    sources via ``am_entity_source`` when NULL.

Why a generic tool, not per-domain
----------------------------------
LLM agents and API callers regularly need to attribute a claim back to a
URL + license before quoting it (景表法 / 著作権法 redistribution rules).
The 16 domain tools each return ``source_url`` on the row, but they do
not surface the license, the role (primary vs. pdf vs. application form),
or the per-fact splits. This generic tool standardizes that surface.

Tools
-----
- ``get_provenance(entity_id, include_facts=False)`` — entity-level: all
  rows in ``am_entity_source`` for the entity, JOINed to ``am_source`` for
  url/license/domain/type/fetched_at. ``include_facts=True`` adds per-fact
  provenance via ``am_entity_facts.source_id`` (when non-NULL).
- ``get_provenance_for_fact(fact_id)`` — single fact: returns the source
  row pointed to by ``am_entity_facts.source_id``. When NULL, falls back
  to the entity-level candidate list so the caller still has *something*
  to cite.

Returned envelope shape (per CLAUDE.md spec):
::

    {
      "entity_id": "<canonical_id>",
      "sources": [
        {role, source_url, domain, license, source_type, fetched_at,
         source_id, content_hash, first_seen, last_verified}, ...
      ],
      "license_summary": {"pdl_v1.0": 3, "gov_standard_v2.0": 1, ...},
      "facts": [optional, when include_facts=True],
      "total_sources": int,
      "total_facts": int  # only when include_facts=True
    }

License taxonomy (closed enum, validated by SQLite trigger):
  pdl_v1.0 / cc_by_4.0 / gov_standard_v2.0 / public_domain /
  proprietary / unknown.
"""

from __future__ import annotations

import logging
import sqlite3
from typing import Annotated, Any

from pydantic import Field

from jpintel_mcp.mcp.server import _READ_ONLY, _with_mcp_telemetry, mcp

from .db import connect_autonomath
from .error_envelope import make_error

logger = logging.getLogger("jpintel.mcp.autonomath.provenance")


# Columns we surface from am_source to the agent. Kept explicit (no
# SELECT *) so that schema additions on am_source don't leak into the
# public envelope without an audit.
_SOURCE_COLUMNS_SQL = (
    "s.id            AS source_id, "
    "s.source_url    AS source_url, "
    "s.source_type   AS source_type, "
    "s.domain        AS domain, "
    "s.license       AS license, "
    "s.is_pdf        AS is_pdf, "
    "s.content_hash  AS content_hash, "
    "s.first_seen    AS first_seen, "
    "s.last_verified AS last_verified, "
    "s.canonical_status AS canonical_status"
)


def _row_to_source(row: sqlite3.Row, role: str | None = None,
                   fetched_at: str | None = None) -> dict[str, Any]:
    """Convert a JOINed (am_entity_source × am_source) row to the public dict.

    ``role`` and ``fetched_at`` come from the entity_source side and are
    only present when the row is keyed off an entity (not a bare fact).
    ``is_pdf`` is preserved as 0/1 (SQLite-boolean) to match the column
    semantic — callers that want a Python ``bool`` should cast.
    """
    out: dict[str, Any] = {
        "source_id": row["source_id"],
        "source_url": row["source_url"],
        "source_type": row["source_type"],
        "domain": row["domain"],
        "license": row["license"],
        "is_pdf": row["is_pdf"],
        "content_hash": row["content_hash"],
        "first_seen": row["first_seen"],
        "last_verified": row["last_verified"],
        "canonical_status": row["canonical_status"],
    }
    if role is not None:
        out["role"] = role
    if fetched_at is not None:
        out["fetched_at"] = fetched_at
    return out


def _license_summary(rows: list[dict[str, Any]]) -> dict[str, int]:
    """Per-license source-count rollup. NULL/empty bucket as ``unknown_null``
    so the agent can distinguish "license=unknown" (explicit) from
    "license column NULL" (un-classified) — the trigger allows NULL but not
    invalid string. CLAUDE.md tracks the 2 NULL rows.
    """
    summary: dict[str, int] = {}
    for r in rows:
        key = r.get("license") or "unknown_null"
        summary[key] = summary.get(key, 0) + 1
    return summary


# ---------------------------------------------------------------------------
# 1. get_provenance — entity-level (with optional per-fact drilldown)
# ---------------------------------------------------------------------------


@mcp.tool(annotations=_READ_ONLY)
@_with_mcp_telemetry
def get_provenance(
    entity_id: Annotated[
        str,
        Field(
            min_length=1,
            max_length=200,
            description=(
                "am_entities.canonical_id (e.g. 'program:04_program_documents:000000:23_xxx', "
                "'corporate_entity:houjin:1234567890123', 'law:e-gov:xxx'). "
                "See enum_values_am or search_* for resolution."
            ),
        ),
    ],
    include_facts: Annotated[
        bool,
        Field(
            description=(
                "If True, also return per-fact provenance via am_entity_facts.source_id "
                "(NULL on legacy rows pre-2026-04-25 — those facts are skipped here; "
                "use entity-level `sources` as fallback citation)."
            ),
        ),
    ] = False,
    fact_limit: Annotated[
        int,
        Field(
            ge=1,
            le=1000,
            description="Max facts returned when include_facts=True (default 200, max 1000).",
        ),
    ] = 200,
) -> dict[str, Any]:
    """[PROVENANCE] entity_id に紐づく全 source を一括返却 — どの URL から / どの license で 取得したかを 1 コールで列挙 (am_entity_source × am_source JOIN, license_summary 同梱, include_facts=True で 個別 fact 単位の出典も).

    WHAT: 1) am_entity_source × am_source で entity に紐づく全 source rows
    (role, source_url, domain, license, source_type, fetched_at). 2) per-license
    rollup ``license_summary``. 3) ``include_facts=True`` のとき am_entity_facts
    × am_source via source_id で fact-level provenance も返却 (source_id NULL の
    fact は skip — entity-level sources を引用すること).

    WHEN:
      - 「この補助金の出典 URL 一覧と license は?」(再配布前の確認)
      - 「どの primary_source / pdf_url / application_url が紐付いているか」
      - 「この entity の facts は どの source から取得したか」(include_facts=True)

    WHEN NOT:
      - 単一 fact_id の出典 → get_provenance_for_fact
      - search 系 (entity 検索) → search_programs / search_certifications / etc.

    RETURN:
      {entity_id, total_sources, sources[{role, source_url, domain, license,
       source_type, fetched_at, source_id, ...}], license_summary{license: count},
       facts? (when include_facts=True), total_facts? (same)}.
      seed_not_found / no_matching_records は canonical envelope を返却。
    """
    eid = (entity_id or "").strip()
    if not eid:
        return make_error(
            code="missing_required_arg",
            message="entity_id is required.",
            hint="Pass am_entities.canonical_id. Use search_* tools to resolve a name.",
            field="entity_id",
            retry_with=["search_programs", "search_certifications"],
        )

    try:
        conn = connect_autonomath()
    except (sqlite3.Error, FileNotFoundError) as exc:
        logger.exception("get_provenance: connect_autonomath failed")
        return make_error(
            code="db_unavailable",
            message=str(exc),
            hint="autonomath.db unreachable; retry later.",
        )

    # Step 1: confirm the entity exists. We separate this from the JOIN so
    # that "entity exists but has zero sources" is distinguishable from
    # "unknown canonical_id" (different LLM strategy: search vs. accept-empty).
    try:
        ent = conn.execute(
            "SELECT canonical_id, primary_name, record_kind, fetched_at "
            "FROM am_entities WHERE canonical_id = ? LIMIT 1",
            (eid,),
        ).fetchone()
    except sqlite3.OperationalError as exc:
        logger.exception("get_provenance: entity lookup failed")
        return make_error(
            code="db_locked" if "locked" in str(exc).lower() else "internal",
            message=str(exc),
        )

    if ent is None:
        return make_error(
            code="seed_not_found",
            message=f"unknown canonical_id: {eid!r}",
            hint=(
                "Resolve via search_programs / search_certifications / "
                "search_loans_am etc., then call get_provenance with the "
                "returned canonical_id."
            ),
            suggested_tools=["search_programs", "search_certifications", "search_loans_am"],
            field="entity_id",
        )

    # Step 2: entity-level sources (am_entity_source × am_source).
    sql_entity_sources = (
        f"SELECT es.role AS role, es.promoted_at AS fetched_at, {_SOURCE_COLUMNS_SQL} "
        "FROM am_entity_source es "
        "JOIN am_source s ON s.id = es.source_id "
        "WHERE es.entity_id = ? "
        "ORDER BY es.role ASC, s.first_seen ASC"
    )
    try:
        src_rows = conn.execute(sql_entity_sources, (eid,)).fetchall()
    except sqlite3.OperationalError as exc:
        logger.exception("get_provenance: entity_source JOIN failed")
        return make_error(
            code="db_locked" if "locked" in str(exc).lower() else "internal",
            message=str(exc),
        )

    sources: list[dict[str, Any]] = [
        _row_to_source(r, role=r["role"], fetched_at=r["fetched_at"])
        for r in src_rows
    ]
    summary = _license_summary(sources)

    out: dict[str, Any] = {
        "entity_id": eid,
        "entity": {
            "canonical_id": ent["canonical_id"],
            "primary_name": ent["primary_name"],
            "record_kind": ent["record_kind"],
            "fetched_at": ent["fetched_at"],
        },
        "total_sources": len(sources),
        "sources": sources,
        "license_summary": summary,
    }

    # Step 3 (optional): per-fact provenance when include_facts=True.
    if include_facts:
        sql_facts = (
            "SELECT f.id AS fact_id, f.field_name, f.field_value_text, "
            "f.field_value_numeric, f.field_kind, f.unit, f.source_url AS fact_source_url, "
            f"{_SOURCE_COLUMNS_SQL} "
            "FROM am_entity_facts f "
            "JOIN am_source s ON s.id = f.source_id "
            "WHERE f.entity_id = ? AND f.source_id IS NOT NULL "
            "ORDER BY f.field_name ASC, f.id ASC "
            "LIMIT ?"
        )
        try:
            fact_rows = conn.execute(sql_facts, (eid, fact_limit)).fetchall()
        except sqlite3.OperationalError as exc:
            logger.exception("get_provenance: fact JOIN failed")
            # Non-fatal: degrade and return entity-level sources only.
            out["facts_error"] = {
                "code": "internal",
                "message": str(exc),
                "hint": "fact-level provenance unavailable; rely on entity-level `sources`.",
            }
            out["facts"] = []
            out["total_facts"] = 0
            return out

        facts: list[dict[str, Any]] = []
        for r in fact_rows:
            facts.append({
                "fact_id": r["fact_id"],
                "field_name": r["field_name"],
                "field_value_text": r["field_value_text"],
                "field_value_numeric": r["field_value_numeric"],
                "field_kind": r["field_kind"],
                "unit": r["unit"],
                "fact_source_url": r["fact_source_url"],
                "source": _row_to_source(r),
            })
        out["facts"] = facts
        out["total_facts"] = len(facts)
        # Note: am_entity_facts.source_id is sparsely populated pre-2026-04-25
        # bulk fill. When zero facts have it set, surface a hint so callers
        # know to fall back to entity-level `sources` for citation.
        if not facts:
            out["facts_hint"] = (
                "0 facts have source_id populated (pre-2026-04-25 ingest). "
                "Use entity-level `sources` as the citation fallback."
            )

    return out


# ---------------------------------------------------------------------------
# 2. get_provenance_for_fact — single fact lookup
# ---------------------------------------------------------------------------


@mcp.tool(annotations=_READ_ONLY)
@_with_mcp_telemetry
def get_provenance_for_fact(
    fact_id: Annotated[
        int,
        Field(
            ge=1,
            description="am_entity_facts.id (PRIMARY KEY AUTOINCREMENT integer).",
        ),
    ],
) -> dict[str, Any]:
    """[PROVENANCE-FACT] 単一 fact_id の出典を返す — am_entity_facts.source_id → am_source 1 件 (NULL のときは entity-level am_entity_source の候補 list に fallback).

    WHAT: am_entity_facts row → source_id → am_source 1 件返却.
    source_id が NULL の legacy fact は entity-level am_entity_source から
    候補 list を返す (``fallback=True``).

    Example:
        get_provenance_for_fact(fact_id=12345)
        → {"fact_id": 12345, "entity_id": "...", "field_name": "amount_max_yen",
           "field_value_text": "5000000", "source": {"source_id": 42,
           "source_url": "...", "license": "pdl_v1.0"}, "fallback": false}

    When NOT to call:
        - For entity-level provenance (all sources for an entity) → use get_provenance(entity_id).
        - For 補助金 program lineage (jpintel.db) → use get_program (carries source_url inline).
        - For 法令 / tax / 判例 detail → those tools embed source_url in their own response.
        - For bulk fact discovery → use search_* tools and read each row's source_url.

    RETURN:
      {fact_id, entity_id, field_name, field_value_text, source? (when source_id is set),
       fallback_sources?[…] (when source_id NULL — candidates from am_entity_source),
       fallback: bool, license_summary{}}
    """
    try:
        conn = connect_autonomath()
    except (sqlite3.Error, FileNotFoundError) as exc:
        logger.exception("get_provenance_for_fact: connect failed")
        return make_error(
            code="db_unavailable",
            message=str(exc),
            hint="autonomath.db unreachable; retry later.",
        )

    # Step 1: fetch the fact row. The fact carries its own source_url
    # (free-text per-row provenance) AS WELL AS the new source_id FK; both
    # are surfaced so callers can compare.
    try:
        f = conn.execute(
            "SELECT id, entity_id, field_name, field_value_text, field_value_numeric, "
            "field_kind, unit, source_url, source_id "
            "FROM am_entity_facts WHERE id = ? LIMIT 1",
            (fact_id,),
        ).fetchone()
    except sqlite3.OperationalError as exc:
        logger.exception("get_provenance_for_fact: fact lookup failed")
        return make_error(
            code="db_locked" if "locked" in str(exc).lower() else "internal",
            message=str(exc),
        )

    if f is None:
        return make_error(
            code="seed_not_found",
            message=f"unknown fact_id: {fact_id}",
            hint="Use search_* tools to find an entity first, then list its facts.",
            field="fact_id",
        )

    base: dict[str, Any] = {
        "fact_id": f["id"],
        "entity_id": f["entity_id"],
        "field_name": f["field_name"],
        "field_value_text": f["field_value_text"],
        "field_value_numeric": f["field_value_numeric"],
        "field_kind": f["field_kind"],
        "unit": f["unit"],
        "fact_source_url": f["source_url"],
    }

    # Step 2a: if source_id is set, JOIN am_source for the canonical record.
    if f["source_id"] is not None:
        try:
            srow = conn.execute(
                f"SELECT {_SOURCE_COLUMNS_SQL} FROM am_source s WHERE s.id = ? LIMIT 1",
                (f["source_id"],),
            ).fetchone()
        except sqlite3.OperationalError as exc:
            logger.exception("get_provenance_for_fact: source lookup failed")
            return make_error(
                code="db_locked" if "locked" in str(exc).lower() else "internal",
                message=str(exc),
            )
        if srow is None:
            # Defensive: source_id pointed at a missing row (FK should prevent
            # this, but ON DELETE CASCADE is on the entity FK only — not on
            # the source_id FK on am_entity_facts — so a manual delete could
            # race). Fall through to fallback.
            pass
        else:
            src = _row_to_source(srow)
            base["source"] = src
            base["fallback"] = False
            base["license_summary"] = _license_summary([src])
            return base

    # Step 2b: source_id NULL (or stale). Fall back to entity-level sources.
    sql_fallback = (
        f"SELECT es.role AS role, es.promoted_at AS fetched_at, {_SOURCE_COLUMNS_SQL} "
        "FROM am_entity_source es "
        "JOIN am_source s ON s.id = es.source_id "
        "WHERE es.entity_id = ? "
        "ORDER BY es.role ASC, s.first_seen ASC"
    )
    try:
        fallback_rows = conn.execute(sql_fallback, (f["entity_id"],)).fetchall()
    except sqlite3.OperationalError as exc:
        logger.exception("get_provenance_for_fact: fallback lookup failed")
        return make_error(
            code="db_locked" if "locked" in str(exc).lower() else "internal",
            message=str(exc),
        )

    fallback_sources = [
        _row_to_source(r, role=r["role"], fetched_at=r["fetched_at"])
        for r in fallback_rows
    ]
    base["fallback"] = True
    base["fallback_sources"] = fallback_sources
    base["license_summary"] = _license_summary(fallback_sources)
    base["fallback_hint"] = (
        "fact.source_id is NULL (legacy ingest pre-2026-04-25). Returning "
        "entity-level candidate sources from am_entity_source. Pick the role "
        "matching the field semantic (primary_source / pdf_url / application_url)."
    )
    return base


# ---------------------------------------------------------------------------
# Self-test harness (not part of MCP surface).
#
#   .venv/bin/python -m jpintel_mcp.mcp.autonomath_tools.provenance_tools
# ---------------------------------------------------------------------------
if __name__ == "__main__":  # pragma: no cover
    import json

    sample_entity = "program:04_program_documents:000000:23_25d25bdfe8"
    print(f"=== get_provenance({sample_entity!r}) ===")
    res = get_provenance(entity_id=sample_entity, include_facts=False)
    print(json.dumps(
        {
            "entity_id": res.get("entity_id"),
            "total_sources": res.get("total_sources"),
            "license_summary": res.get("license_summary"),
            "first_3_sources": res.get("sources", [])[:3],
        },
        ensure_ascii=False,
        indent=2,
    ))

    print("\n=== get_provenance(include_facts=True) ===")
    res2 = get_provenance(entity_id=sample_entity, include_facts=True, fact_limit=5)
    print(json.dumps(
        {
            "total_sources": res2.get("total_sources"),
            "total_facts": res2.get("total_facts"),
            "facts_hint": res2.get("facts_hint"),
        },
        ensure_ascii=False,
        indent=2,
    ))

    print("\n=== get_provenance_for_fact(1) ===")
    res3 = get_provenance_for_fact(fact_id=1)
    print(json.dumps(
        {
            "fact_id": res3.get("fact_id"),
            "fallback": res3.get("fallback"),
            "fallback_count": len(res3.get("fallback_sources", []) or []),
            "license_summary": res3.get("license_summary"),
        },
        ensure_ascii=False,
        indent=2,
    ))
