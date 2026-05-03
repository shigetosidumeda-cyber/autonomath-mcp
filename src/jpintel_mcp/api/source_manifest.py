"""REST handler for /v1/source_manifest/{program_id} — Evidence-Graph
per-program source rollup (90-day deliverable, value_maximization plan
§7.7 + §28.1).

Surfaces every source citation linked to a program via two signals:

  * **Per-fact provenance** (sparse). `am_entity_facts.source_id` (mig 049)
    pins a single fact to a single am_source row. As of 2026-04-30 this is
    1.12M / 6.12M facts populated overall, but **0 program-fact rows have
    source_id set** — the bulk fill cron has not started for the program
    cohort yet. The endpoint surfaces this honestly: empty
    `fact_provenance[]` and `fact_provenance_coverage_pct=0.0`.
  * **Entity-level rollup** (dense for programs). `am_entity_source` maps
    every entity to its primary / pdf / application sources via role.
    Used for the `summary` block (`source_count`, `latest_fetched_at`,
    `unique_publishers`, `license_set`).

Provenance comes from the autonomath.db view `v_program_source_manifest`
(migration 115). The endpoint Python-resolves `program_id` (which may be
a `UNI-...` unified_id OR an `am_canonical_id` like `program:...`) to the
underlying entity, then reads the view + per-fact JOIN once.

Pricing: ¥3/req metered (1 unit). Anonymous tier shares the 3/日 IP cap
via AnonIpLimitDep on the router mount in `api/main.py`.

§52 / data-honesty envelope: every 2xx body carries a `_disclaimer`
explaining "manifest reflects per-fact provenance where source_id is
populated; unpopulated facts inherit the program's primary_source_url".

Read-only. The autonomath connection is opened in `mode=ro` so a
misconfigured deploy can never write to the 9.4 GB primary DB through
this surface.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import time
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, status
from fastapi import Path as PathParam
from fastapi.responses import JSONResponse

from jpintel_mcp.api._license_gate import REDISTRIBUTABLE_LICENSES
from jpintel_mcp.api.deps import ApiContextDep, DbDep, log_usage

logger = logging.getLogger("jpintel.api.source_manifest")

router = APIRouter(prefix="/v1/source_manifest", tags=["source_manifest"])


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Cap on per-fact provenance rows surfaced inline. The plan wants honest
# coverage signal; capping at 500 keeps the worst-case body well under the
# 50 KB target while leaving headroom for richly-cited programs once the
# cron lands. Truncation surfaces an explicit `_warning` so callers know
# they are seeing a truncated view.
_MAX_FACT_PROVENANCE = 500
_ALLOWED_LICENSES_SQL = ",".join("?" for _ in sorted(REDISTRIBUTABLE_LICENSES))

# Closed-vocab license enum (mirrors am_source.license trigger). The view
# emits 'unknown_null' for NULL license rows so the API can distinguish
# "explicitly unknown" from "NULL — not yet classified" downstream.
_LICENSE_VALUES: frozenset[str] = frozenset(
    {
        "pdl_v1.0",
        "cc_by_4.0",
        "gov_standard_v2.0",
        "public_domain",
        "proprietary",
        "unknown",
        "unknown_null",
    }
)

# Honest-data disclaimer (景表法 / 消費者契約法 fence — every 2xx response
# must carry this so an LLM relay never claims richer per-fact provenance
# than the corpus actually has).
_DISCLAIMER = (
    "manifest reflects per-fact provenance where source_id is populated; "
    "unpopulated facts inherit the program's primary_source_url."
)


# ---------------------------------------------------------------------------
# Autonomath read-only connection helper (pattern from api/houjin.py)
# ---------------------------------------------------------------------------


def _autonomath_db_path() -> Path:
    """Resolve the autonomath.db path. Mirrors api/houjin.py::_autonomath_db_path."""
    raw = os.environ.get("AUTONOMATH_DB_PATH")
    if raw:
        return Path(raw)
    return Path(__file__).resolve().parents[3] / "autonomath.db"


def _open_autonomath_ro() -> sqlite3.Connection | None:
    """Open a read-only connection to autonomath.db. Returns None when the
    file is missing — endpoint then returns the structured 503 below.
    """
    p = _autonomath_db_path()
    if not p.exists():
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
        return conn
    except sqlite3.OperationalError:
        return None


# ---------------------------------------------------------------------------
# program_id resolver
# ---------------------------------------------------------------------------


def _resolve_program(
    am_conn: sqlite3.Connection, program_id: str
) -> tuple[str, dict[str, Any]] | None:
    """Resolve `program_id` to (entity_canonical_id, primary_metadata) tuple.

    Three resolution paths, tried in order:

      1. **Unified id (`UNI-...`)** → `entity_id_map` (mig 032 / V4 link
         table) → `am_canonical_id`. The primary metadata comes from
         `jpi_programs` (the autonomath-mirrored copy of programs).
      2. **AM canonical id (`program:...`, `corporate_entity:...`, etc.)**
         → direct match on `am_entities.canonical_id`. The primary
         metadata is `am_entities.primary_name` + `am_entities.source_url`.
      3. **Plain unified_id without UNI- prefix** → fallback to
         `jpi_programs.unified_id` lookup; if found but no link, return
         a metadata-only resolution with empty entity_id (sparse path).

    Returns ``None`` when the program_id matches nothing on any path,
    triggering the 404 branch in the route.
    """
    pid = program_id.strip()
    if not pid:
        return None

    # Path 1: UNI- prefix → unified_id → entity_id_map → canonical_id
    if pid.startswith("UNI-"):
        # Look up the program metadata from jpi_programs first so we can
        # surface primary_name/source_url even when no link exists.
        prog = am_conn.execute(
            """SELECT unified_id, primary_name, source_url, source_fetched_at,
                      authority_name, prefecture, tier
                 FROM jpi_programs
                WHERE unified_id = ?
                LIMIT 1""",
            (pid,),
        ).fetchone()
        if prog is None:
            return None
        # Highest-confidence match in entity_id_map.
        link = am_conn.execute(
            """SELECT am_canonical_id
                 FROM entity_id_map
                WHERE jpi_unified_id = ?
                ORDER BY confidence DESC
                LIMIT 1""",
            (pid,),
        ).fetchone()
        canonical_id = link["am_canonical_id"] if link else ""
        return canonical_id, {
            "program_id": pid,
            "primary_name": prog["primary_name"],
            "primary_source_url": prog["source_url"],
            "source_fetched_at": prog["source_fetched_at"],
            "authority_name": prog["authority_name"],
            "prefecture": prog["prefecture"],
            "tier": prog["tier"],
            "resolution_path": "unified_id_via_entity_id_map",
        }

    # Path 2: AM canonical id (program:... / corporate_entity:... / etc.)
    # Match directly on am_entities.canonical_id.
    if ":" in pid:
        ent = am_conn.execute(
            """SELECT canonical_id, primary_name, source_url, fetched_at
                 FROM am_entities
                WHERE canonical_id = ?
                LIMIT 1""",
            (pid,),
        ).fetchone()
        if ent is None:
            return None
        return ent["canonical_id"], {
            "program_id": pid,
            "primary_name": ent["primary_name"],
            "primary_source_url": ent["source_url"],
            "source_fetched_at": ent["fetched_at"],
            "authority_name": None,
            "prefecture": None,
            "tier": None,
            "resolution_path": "am_canonical_id_direct",
        }

    # Path 3: bare unified_id without UNI- prefix (defensive — legacy
    # callers may pass the suffix only). Only matches when jpi_programs
    # has the unprefixed form (rare; current ingest writes `UNI-...`).
    prog = am_conn.execute(
        """SELECT unified_id, primary_name, source_url, source_fetched_at,
                  authority_name, prefecture, tier
             FROM jpi_programs
            WHERE unified_id = ?
            LIMIT 1""",
        (pid,),
    ).fetchone()
    if prog is None:
        return None
    return "", {
        "program_id": pid,
        "primary_name": prog["primary_name"],
        "primary_source_url": prog["source_url"],
        "source_fetched_at": prog["source_fetched_at"],
        "authority_name": prog["authority_name"],
        "prefecture": prog["prefecture"],
        "tier": prog["tier"],
        "resolution_path": "jpi_programs_unprefixed",
    }


# ---------------------------------------------------------------------------
# Manifest assembler
# ---------------------------------------------------------------------------


def _friendly_license(raw_license: str | None) -> str:
    return {
        "gov_standard_v2.0": "gov_standard",
        "gov_standard": "gov_standard",
        "pdl_v1.0": "pdl_v1.0",
        "cc_by_4.0": "cc_by_4.0",
        "public_domain": "public_domain",
        "proprietary": "proprietary",
    }.get(raw_license or "unknown", "unknown")


def _raw_license_for_source_url(am_conn: sqlite3.Connection, source_url: str | None) -> str:
    if not source_url:
        return "unknown"
    row = am_conn.execute(
        """SELECT COALESCE(license, 'unknown_null') AS license
             FROM am_source
            WHERE source_url = ?
            LIMIT 1""",
        (source_url,),
    ).fetchone()
    if row is None:
        return "unknown"
    value = row["license"]
    return value if isinstance(value, str) and value else "unknown"


def _license_posture(licenses: list[str]) -> tuple[str, bool]:
    if not licenses:
        return "unknown", False
    has_allowed = any(v in REDISTRIBUTABLE_LICENSES for v in licenses)
    has_blocked = any(v not in REDISTRIBUTABLE_LICENSES for v in licenses)
    if has_allowed and has_blocked:
        return "mixed_restricted", False
    if has_allowed:
        return "redistributable", True
    return "restricted", False


def _manifest_licenses_with_primary(
    licenses: list[str],
    *,
    primary_raw_license: str,
    primary_source_url: str | None,
) -> list[str]:
    """Include the exact primary URL license in redistribution posture."""
    out = [v for v in licenses if isinstance(v, str) and v]
    if primary_source_url and primary_raw_license not in out:
        out.append(primary_raw_license or "unknown")
    return out


def _redact_primary_source_if_restricted(out: dict[str, Any], raw_license: str) -> None:
    if raw_license in REDISTRIBUTABLE_LICENSES:
        return
    if raw_license == "unknown":
        out["primary_source_url_license_unverified"] = True
        out["primary_source_license_note"] = "source URL is listed as metadata; redistribution license is unverified"
        return
    out.pop("primary_source_url", None)
    out["primary_source_url_redacted"] = True
    out["primary_source_redaction_reason"] = "license_not_redistributable_or_unknown"


def _build_manifest(
    am_conn: sqlite3.Connection, canonical_id: str, base: dict[str, Any]
) -> dict[str, Any]:
    """Compose the manifest envelope for a resolved program.

    `canonical_id` may be empty when the program has no entity_id_map
    link — the manifest then degrades to primary_source_url-only with
    empty `fact_provenance` and zero summary counts.
    """
    out: dict[str, Any] = {
        "program_id": base["program_id"],
        "primary_name": base["primary_name"],
        "primary_source_url": base["primary_source_url"],
        "primary_license": "unknown",
        "license_posture": "unknown",
        "redistribution_allowed": False,
        "fact_provenance": [],
        "fact_provenance_coverage_pct": 0.0,
        "summary": {
            "field_paths_covered": [],
            "source_count": 0,
            "license_set": [],
            "latest_fetched_at": None,
            "oldest_fetched_at": None,
            "unique_publishers": 0,
        },
        "_disclaimer": _DISCLAIMER,
        "_resolution_path": base.get("resolution_path"),
    }

    # Surface useful program metadata so the caller doesn't need a second
    # round-trip to the program API.
    if base.get("authority_name") is not None:
        out["authority_name"] = base["authority_name"]
    if base.get("prefecture") is not None:
        out["prefecture"] = base["prefecture"]
    if base.get("tier") is not None:
        out["tier"] = base["tier"]

    primary_raw_license = _raw_license_for_source_url(am_conn, base.get("primary_source_url"))

    # No entity link → degrade gracefully. primary_source_url block + the
    # explicit empty arrays still tell the caller "I checked, nothing
    # else available".
    if not canonical_id:
        out["primary_license"] = _friendly_license(primary_raw_license)
        license_posture, redistribution_allowed = _license_posture(
            _manifest_licenses_with_primary(
                [],
                primary_raw_license=primary_raw_license,
                primary_source_url=base.get("primary_source_url"),
            )
        )
        out["license_posture"] = license_posture
        out["redistribution_allowed"] = redistribution_allowed
        _redact_primary_source_if_restricted(out, primary_raw_license)
        return out

    # Pull the rollup row from the view. Row may be missing when the
    # entity has zero source links at all (no facts AND no
    # am_entity_source rows — rare).
    summary_row = am_conn.execute(
        """SELECT entity_id, field_paths_covered, source_count,
                  latest_fetched_at, oldest_fetched_at, unique_publishers,
                  license_set
             FROM v_program_source_manifest
            WHERE entity_id = ?
            LIMIT 1""",
        (canonical_id,),
    ).fetchone()

    if summary_row is not None:
        try:
            field_paths = json.loads(
                summary_row["field_paths_covered"] or "[]"
            )
        except (TypeError, ValueError):
            field_paths = []
        try:
            license_list = json.loads(summary_row["license_set"] or "[]")
        except (TypeError, ValueError):
            license_list = []

        out["summary"] = {
            "field_paths_covered": field_paths,
            "source_count": int(summary_row["source_count"] or 0),
            "license_set": license_list,
            "latest_fetched_at": summary_row["latest_fetched_at"],
            "oldest_fetched_at": summary_row["oldest_fetched_at"],
            "unique_publishers": int(
                summary_row["unique_publishers"] or 0
            ),
        }
        out["primary_license"] = _friendly_license(primary_raw_license)
        license_posture, redistribution_allowed = _license_posture(
            _manifest_licenses_with_primary(
                license_list,
                primary_raw_license=primary_raw_license,
                primary_source_url=base.get("primary_source_url"),
            )
        )
        out["license_posture"] = license_posture
        out["redistribution_allowed"] = redistribution_allowed
        _redact_primary_source_if_restricted(out, primary_raw_license)
    else:
        out["primary_license"] = _friendly_license(primary_raw_license)
        license_posture, redistribution_allowed = _license_posture(
            _manifest_licenses_with_primary(
                [],
                primary_raw_license=primary_raw_license,
                primary_source_url=base.get("primary_source_url"),
            )
        )
        out["license_posture"] = license_posture
        out["redistribution_allowed"] = redistribution_allowed
        _redact_primary_source_if_restricted(out, primary_raw_license)

    # Per-fact provenance — JOIN am_entity_facts × am_source where
    # source_id is populated and redistributable. Blocked/unknown-license
    # rows are counted in license_gate but not surfaced with source_url.
    allowed_licenses = sorted(REDISTRIBUTABLE_LICENSES)
    fact_rows = am_conn.execute(
        f"""SELECT f.id            AS fact_id,
                  f.field_name    AS field_name,
                  f.source_id     AS source_id,
                  s.source_url    AS source_url,
                  s.domain        AS publisher,
                  s.first_seen    AS fetched_at,
                  s.license       AS license,
                  s.content_hash  AS checksum
             FROM am_entity_facts f
             JOIN am_source s ON s.id = f.source_id
            WHERE f.entity_id = ?
              AND f.source_id IS NOT NULL
              AND COALESCE(s.license, 'unknown_null') IN ({_ALLOWED_LICENSES_SQL})
            ORDER BY f.field_name ASC, f.id ASC
            LIMIT ?""",
        (canonical_id, *allowed_licenses, _MAX_FACT_PROVENANCE + 1),
    ).fetchall()
    blocked_license_rows = am_conn.execute(
        f"""SELECT COALESCE(s.license, 'unknown_null') AS license, COUNT(*) AS n
              FROM am_entity_facts f
              JOIN am_source s ON s.id = f.source_id
             WHERE f.entity_id = ?
               AND f.source_id IS NOT NULL
               AND COALESCE(s.license, 'unknown_null') NOT IN ({_ALLOWED_LICENSES_SQL})
             GROUP BY COALESCE(s.license, 'unknown_null')
             ORDER BY n DESC, license ASC""",
        (canonical_id, *allowed_licenses),
    ).fetchall()

    truncated = len(fact_rows) > _MAX_FACT_PROVENANCE
    if truncated:
        fact_rows = fact_rows[:_MAX_FACT_PROVENANCE]

    out["fact_provenance"] = [
        {
            "field_name": r["field_name"],
            "source_id": r["source_id"],
            "source_url": r["source_url"],
            "publisher": r["publisher"],
            "fetched_at": r["fetched_at"],
            "license": r["license"] or "unknown_null",
            "checksum": r["checksum"],
        }
        for r in fact_rows
    ]

    # Coverage percentage: distinct facts-with-source_id / total facts on
    # this entity. NOT distinct field_names — that would inflate when one
    # field has many duplicate fact rows. `total_facts` carries the
    # context for the percentage so callers don't have to recompute.
    coverage_row = am_conn.execute(
        f"""SELECT COUNT(*) AS total_facts,
                   COUNT(f.source_id) AS facts_with_source,
                   SUM(
                     CASE
                       WHEN f.source_id IS NOT NULL
                        AND COALESCE(s.license, 'unknown_null') IN ({_ALLOWED_LICENSES_SQL})
                       THEN 1 ELSE 0
                     END
                   ) AS facts_with_redistributable_source
              FROM am_entity_facts f
              LEFT JOIN am_source s ON s.id = f.source_id
             WHERE f.entity_id = ?""",
        (*allowed_licenses, canonical_id),
    ).fetchone()
    total_facts = int(coverage_row["total_facts"] or 0)
    facts_with_source = int(coverage_row["facts_with_source"] or 0)
    facts_with_redistributable_source = int(
        coverage_row["facts_with_redistributable_source"] or 0
    )
    coverage_pct = (
        round(facts_with_redistributable_source / total_facts, 4)
        if total_facts > 0
        else 0.0
    )
    out["fact_provenance_coverage_pct"] = coverage_pct
    out["_total_facts"] = total_facts
    out["_facts_with_source_id"] = facts_with_source
    out["_facts_with_redistributable_source_id"] = facts_with_redistributable_source
    blocked_summary_licenses = [
        v
        for v in out.get("summary", {}).get("license_set", [])
        if isinstance(v, str) and v not in REDISTRIBUTABLE_LICENSES
    ]
    if blocked_license_rows:
        out["license_gate"] = {
            "policy": "redistributable_sources_only",
            "blocked_fact_provenance_count": sum(
                int(r["n"] or 0) for r in blocked_license_rows
            ),
            "blocked_reasons": {
                str(r["license"] or "unknown"): int(r["n"] or 0)
                for r in blocked_license_rows
            },
            "redistributable_licenses": allowed_licenses,
        }
    elif blocked_summary_licenses:
        out["license_gate"] = {
            "policy": "redistributable_sources_only",
            "blocked_fact_provenance_count": 0,
            "blocked_entity_source_licenses": sorted(set(blocked_summary_licenses)),
            "redistributable_licenses": allowed_licenses,
        }

    if truncated:
        out["_warning"] = (
            f"fact_provenance truncated at {_MAX_FACT_PROVENANCE}"
        )

    return out


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------


@router.get(
    "/{program_id}",
    summary="Per-program source manifest (partial Evidence Graph)",
    description=(
        "Surface the available provenance manifest for one program: "
        "redistributable fact-level references plus an entity-level source "
        "rollup in one response.\n\n"
        "**Pricing:** ¥3/call (1 unit). Anonymous callers share the 3/日 "
        "per-IP cap (JST 翌日 00:00 リセット).\n\n"
        "**program_id** accepts:\n"
        "* a unified_id (`UNI-...`);\n"
        "* a stable program identifier (`program:...`).\n\n"
        "**Sparse-data honesty:** the per-fact provenance signal is "
        "currently partial for some program cohorts. "
        "The endpoint returns `fact_provenance=[]` and "
        "`fact_provenance_coverage_pct=0.0` rather than fabricating a "
        "richer view. The `_disclaimer` field is required reading for any "
        "downstream LLM relay."
    ),
    responses={
        200: {
            "description": (
                "Manifest envelope. `fact_provenance` is redistributable per-fact "
                "(field_name, source_url, publisher, fetched_at, license, "
                "checksum); `summary` is the entity-level rollup; "
                "`primary_*` carries the program-row authoritative URL."
            )
        },
        404: {
            "description": (
                "Unknown program_id in the current public corpus."
            )
        },
        503: {
            "description": (
                "Source manifest data is temporarily unavailable."
            ),
        },
    },
)
def get_source_manifest(
    program_id: Annotated[
        str,
        PathParam(
            min_length=1,
            max_length=200,
            description=(
                "Program identifier — either a unified_id (UNI-...) or an "
                "am_canonical_id (program:...)."
            ),
            examples=["UNI-00d62c90c3"],
        ),
    ],
    conn: DbDep,
    ctx: ApiContextDep,
) -> JSONResponse:
    """Return the source manifest envelope for the given program_id.

    Reads from autonomath.db (read-only). The Python side does the
    program_id → canonical_id resolution because cross-DB ATTACH is
    forbidden (see CLAUDE.md). The view `v_program_source_manifest`
    (migration 115) does the SQL-side per-entity rollup.
    """
    _t0 = time.perf_counter()

    am_conn = _open_autonomath_ro()
    if am_conn is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "autonomath.db unavailable",
        )

    try:
        resolved = _resolve_program(am_conn, program_id)
        if resolved is None:
            log_usage(
                conn,
                ctx,
                "source_manifest.get",
                status_code=status.HTTP_404_NOT_FOUND,
                params={"miss": True},
            )
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={
                    "detail": (
                        "Unknown program_id. Pass either a unified_id "
                        "(UNI-...) found in jpi_programs, or an "
                        "am_canonical_id (program:...) from am_entities."
                    ),
                    "program_id": program_id,
                    "_disclaimer": _DISCLAIMER,
                },
            )
        canonical_id, base = resolved
        body = _build_manifest(am_conn, canonical_id, base)
    finally:
        am_conn.close()

    _latency_ms = int((time.perf_counter() - _t0) * 1000)
    log_usage(
        conn,
        ctx,
        "source_manifest.get",
        latency_ms=_latency_ms,
        params={"program_id": program_id},
    )
    return JSONResponse(content=body)
