"""get_source_manifest — Evidence Graph per-program source manifest MCP tool.

Mirrors `GET /v1/source_manifest/{program_id}` so MCP clients can pull
the same envelope (per-fact provenance + entity-level rollup + license
distribution) without round-tripping through HTTP.

Backed by the `v_program_source_manifest` view (migration 115). The
implementation reuses the REST composer in `api.source_manifest` so the
shape stays in lock-step — any envelope drift between REST and MCP
becomes a single-call test failure rather than a silent divergence.
"""

from __future__ import annotations

import logging
import sqlite3
from typing import Annotated, Any

from pydantic import Field

from jpintel_mcp.api.source_manifest import _build_manifest, _resolve_program
from jpintel_mcp.mcp.server import _READ_ONLY, _with_mcp_telemetry, mcp

from .db import connect_autonomath
from .error_envelope import make_error

logger = logging.getLogger("jpintel.mcp.am.source_manifest")


@mcp.tool(annotations=_READ_ONLY)
@_with_mcp_telemetry
def get_source_manifest(
    program_id: Annotated[
        str,
        Field(
            min_length=1,
            max_length=200,
            description=(
                "Program identifier — either a public unified_id (UNI-...) "
                "or a stable legacy canonical id (program:...). The tool "
                "resolves both to the underlying record."
            ),
        ),
    ],
) -> dict[str, Any]:
    """[EVIDENCE-GRAPH] Returns the full source manifest for one program: per-fact provenance (where source_id is populated) + entity-level rollup (am_entity_source) + license set + publisher count + first/last fetched_at. Honest sparse signal — empty fact_provenance when source_id bulk fill has not reached the program cohort.

    WHAT: 1) per-fact provenance rows where available (sparse; many
    programs still have no field-level provenance). 2) entity-level
    rollup (source_count, license_set, latest/oldest fetched_at,
    unique_publishers). 3) public program metadata fallback when an entity
    has no fact-level provenance yet.

    WHEN:
      - 「この補助金の出典 URL を全部洗い出したい」(再配布前の license 確認)
      - 「per-field provenance ありますか?」(answer = mostly no, surfaced honestly)
      - Evidence Graph cite-chain audit / 90-day deliverable verification

    WHEN NOT:
      - Single-fact provenance → get_provenance_for_fact(fact_id)
      - Entity-level provenance only → get_provenance(entity_id)
      - Plain program lookup → search_programs / get_program (jpintel.db)

    RETURN:
      {program_id, primary_name, primary_source_url, primary_license,
       fact_provenance[{field_name, source_id, source_url, publisher,
       fetched_at, license, checksum}], fact_provenance_coverage_pct,
       summary{field_paths_covered, source_count, license_set,
       latest_fetched_at, oldest_fetched_at, unique_publishers},
       _disclaimer}.
      seed_not_found / db_unavailable は canonical envelope を返却。
    """
    pid = (program_id or "").strip()
    if not pid:
        return make_error(
            code="missing_required_arg",
            message="program_id is required.",
            hint=("Pass either a unified_id (UNI-...) or an am_canonical_id (program:...)."),
            field="program_id",
        )

    try:
        conn = connect_autonomath()
    except (sqlite3.Error, FileNotFoundError) as exc:
        logger.exception("get_source_manifest: connect_autonomath failed")
        return make_error(
            code="db_unavailable",
            message=str(exc),
            hint="autonomath.db unreachable; retry later.",
        )

    try:
        resolved = _resolve_program(conn, pid)
    except sqlite3.OperationalError as exc:
        logger.exception("get_source_manifest: resolve failed")
        return make_error(
            code="db_locked" if "locked" in str(exc).lower() else "internal",
            message=str(exc),
        )

    if resolved is None:
        return make_error(
            code="seed_not_found",
            message=f"unknown program_id: {pid!r}",
            hint=(
                "Pass a unified_id from jpi_programs (UNI-...) or an "
                "am_canonical_id from am_entities (program:...)."
            ),
            suggested_tools=["search_programs", "list_open_programs"],
            field="program_id",
        )

    canonical_id, base = resolved
    try:
        body = _build_manifest(conn, canonical_id, base)
    except sqlite3.OperationalError as exc:
        logger.exception("get_source_manifest: build failed")
        return make_error(
            code="db_locked" if "locked" in str(exc).lower() else "internal",
            message=str(exc),
        )

    return body


# ---------------------------------------------------------------------------
# Self-test harness (not part of MCP surface).
#
#   .venv/bin/python -m jpintel_mcp.mcp.autonomath_tools.source_manifest_tools
# ---------------------------------------------------------------------------
if __name__ == "__main__":  # pragma: no cover
    import json

    sample_canonical = "program:04_program_documents:000000:23_25d25bdfe8"
    print(f"=== get_source_manifest({sample_canonical!r}) ===")
    res = get_source_manifest(program_id=sample_canonical)
    print(
        json.dumps(
            {
                "program_id": res.get("program_id"),
                "primary_name": res.get("primary_name"),
                "primary_source_url": res.get("primary_source_url"),
                "primary_license": res.get("primary_license"),
                "fact_provenance_coverage_pct": res.get("fact_provenance_coverage_pct"),
                "summary": res.get("summary"),
                "fact_provenance_count": len(res.get("fact_provenance", [])),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
