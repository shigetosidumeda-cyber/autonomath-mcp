"""Cross-source agreement math for the trust 8-pack (mig 101 #6).

When a fact about a program is asserted by 2+ distinct primary sources
(NTA + 中小企業庁, MAFF + 都道府県, etc.) we want to surface that to callers
as "✓ N sources agree" or "⚠ disagreement detected". The math here is
intentionally tiny — counts and a verdict — so the same logic powers:

  * The HTTP endpoint  GET /v1/cross_source/{entity_id}  (api/trust.py)
  * The hourly cron    scripts/cron/cross_source_check.py
  * Any future MCP tool that needs the same verdict envelope

Schema dependencies
-------------------
- `am_entity_facts(entity_id, field_name, value, source_id, ...)` — the EAV
  table where each fact carries its source_id.
- `am_source(source_id, source_url, ...)` — the table whose distinct count
  per (entity_id, field_name) is the agreement signal.
- `am_entity_facts.confirming_source_count` — column added by mig 101.
  Populated by the hourly cron; the endpoint also degrades to a live
  COUNT(DISTINCT source_id) when the column has not been backfilled yet.
"""
from __future__ import annotations

import sqlite3
from typing import Any


def _verdict(distinct_sources: int, value_sets: int) -> str:
    """Map (distinct source count, distinct value count) → verdict string.

    - 1 source     → "single_source"   (no cross-check possible yet)
    - 2+ sources, 1 value     → "agreement"     (✓)
    - 2+ sources, 2+ values   → "disagreement"  (⚠)
    - 0 sources               → "no_data"
    """
    if distinct_sources <= 0:
        return "no_data"
    if distinct_sources == 1:
        return "single_source"
    return "agreement" if value_sets <= 1 else "disagreement"


def compute_cross_source_agreement(
    conn: sqlite3.Connection,
    entity_id: str,
    field_name: str | None = None,
) -> dict[str, Any] | None:
    """Per-(entity, field) cross-source verdict.

    When *field_name* is None we aggregate across every field: the entity
    gets back a per-field breakdown plus a summary.

    Returns None if neither am_entity_facts nor a fallback jpi_programs row
    can be located for the requested entity_id (router maps that to 404).
    """
    # Cheap existence probe: am_entities_FACT row anywhere.
    try:
        exists = conn.execute(
            "SELECT 1 FROM am_entity_facts WHERE entity_id = ? LIMIT 1",
            (entity_id,),
        ).fetchone()
    except sqlite3.OperationalError:
        # autonomath schema not present (jpintel-only test harness).
        # Fall back to a synthetic verdict over jpi_programs so the router
        # contract remains useful in tests.
        return _jpi_programs_fallback(conn, entity_id)

    if exists is None:
        return _jpi_programs_fallback(conn, entity_id)

    where_field = " AND field_name = ?" if field_name is not None else ""
    args: tuple[Any, ...]
    args = (entity_id, field_name) if field_name is not None else (entity_id,)

    try:
        per_field = conn.execute(
            f"SELECT field_name, "
            f"       COUNT(DISTINCT source_id) AS sources, "
            f"       COUNT(DISTINCT value) AS values_, "
            f"       MAX(confirming_source_count) AS column_csc "
            f"FROM am_entity_facts "
            f"WHERE entity_id = ?{where_field} "
            f"GROUP BY field_name "
            f"ORDER BY sources DESC, field_name ASC LIMIT 200",
            args,
        ).fetchall()
    except sqlite3.OperationalError:
        # confirming_source_count not yet added — retry without that col.
        per_field = conn.execute(
            f"SELECT field_name, "
            f"       COUNT(DISTINCT source_id) AS sources, "
            f"       COUNT(DISTINCT value) AS values_, "
            f"       NULL AS column_csc "
            f"FROM am_entity_facts "
            f"WHERE entity_id = ?{where_field} "
            f"GROUP BY field_name "
            f"ORDER BY sources DESC, field_name ASC LIMIT 200",
            args,
        ).fetchall()

    fields_out: list[dict[str, Any]] = []
    for r in per_field:
        live_count = int(r["sources"] or 0)
        col_csc = r["column_csc"]
        fields_out.append(
            {
                "field": r["field_name"],
                "distinct_sources": live_count,
                "distinct_values": int(r["values_"] or 0),
                "confirming_source_count": (
                    int(col_csc) if col_csc is not None else live_count
                ),
                "verdict": _verdict(live_count, int(r["values_"] or 0)),
            }
        )

    if not fields_out:
        return None

    summary_sources = max(f["distinct_sources"] for f in fields_out)
    has_disagreement = any(f["verdict"] == "disagreement" for f in fields_out)
    return {
        "entity_id": entity_id,
        "filter": {"field": field_name},
        "fields": fields_out,
        "summary": {
            "max_distinct_sources": summary_sources,
            "any_disagreement": has_disagreement,
            "verdict": (
                "disagreement" if has_disagreement
                else ("agreement" if summary_sources >= 2 else "single_source")
            ),
            "human_label": (
                "⚠ disagreement detected" if has_disagreement
                else (f"✓ {summary_sources} sources agree"
                      if summary_sources >= 2 else "single source")
            ),
        },
    }


def _jpi_programs_fallback(
    conn: sqlite3.Connection, entity_id: str
) -> dict[str, Any] | None:
    """Best-effort cross-source verdict using jpi_programs.

    autonomath EAV not present → fall back to the (program × source_url)
    relation that *does* exist in jpintel-only test environments. We treat
    each non-null `source_url` on a row as one source. This keeps the
    router/endpoint contract usable without hard-failing.
    """
    try:
        row = conn.execute(
            "SELECT primary_name, source_url FROM jpi_programs "
            "WHERE unified_id = ? LIMIT 1",
            (entity_id,),
        ).fetchone()
    except sqlite3.OperationalError:
        try:
            row = conn.execute(
                "SELECT primary_name, source_url FROM programs "
                "WHERE unified_id = ? LIMIT 1",
                (entity_id,),
            ).fetchone()
        except sqlite3.OperationalError:
            return None
    if row is None:
        return None
    sources = 1 if row["source_url"] else 0
    return {
        "entity_id": entity_id,
        "filter": {"field": None},
        "fields": [],
        "summary": {
            "max_distinct_sources": sources,
            "any_disagreement": False,
            "verdict": "single_source" if sources == 1 else "no_data",
            "human_label": (
                "single source" if sources == 1 else "no source data"
            ),
        },
        "_meta": {
            "fallback": "jpi_programs (am_entity_facts not available on this DB)",
        },
    }


def refresh_confirming_source_counts(
    conn: sqlite3.Connection,
    *,
    limit_entities: int | None = None,
) -> dict[str, int]:
    """Recompute confirming_source_count for every (entity, field) row.

    Used by `scripts/cron/cross_source_check.py`. Writes back to
    am_entity_facts.confirming_source_count via UPDATE. Returns counts of
    rows updated / mismatches detected (rows whose new count differs from
    the previously-stored value — these are candidates for surfacing as a
    correction_log row when the disagreement is structural).

    The caller is expected to open a writable connection. We do not commit
    here — the caller controls the txn boundary so they can also write
    correction_log rows in the same transaction.
    """
    out = {"checked": 0, "updated": 0, "mismatches": 0}
    try:
        rows = conn.execute(
            "SELECT entity_id, field_name, "
            "       COUNT(DISTINCT source_id) AS sources, "
            "       MAX(confirming_source_count) AS prev "
            "FROM am_entity_facts "
            "GROUP BY entity_id, field_name"
            + (f" LIMIT {int(limit_entities)}" if limit_entities else "")
        ).fetchall()
    except sqlite3.OperationalError:
        return out

    for r in rows:
        out["checked"] += 1
        live = int(r["sources"] or 0)
        prev = r["prev"]
        if prev is not None and int(prev) != live:
            out["mismatches"] += 1
        # Upsert into the column for *every* fact row of (entity, field).
        try:
            cur = conn.execute(
                "UPDATE am_entity_facts SET confirming_source_count = ? "
                "WHERE entity_id = ? AND field_name = ?",
                (live, r["entity_id"], r["field_name"]),
            )
            out["updated"] += int(cur.rowcount or 0)
        except sqlite3.OperationalError:
            # confirming_source_count column missing → mig 101 not applied.
            break
    return out


__all__ = [
    "compute_cross_source_agreement",
    "refresh_confirming_source_counts",
]
