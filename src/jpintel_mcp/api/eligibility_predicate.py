"""REST surface for the per-program eligibility predicate cache (W26-6).

Mirrors :mod:`jpintel_mcp.mcp.autonomath_tools.eligibility_predicate_tool`
on the wire so a customer agent that uses HTTP (no MCP transport) can
fetch the same machine-readable predicate JSON the MCP tool returns.

Why a dedicated REST route
--------------------------
The customer e2e flow (`tests/test_customer_e2e.py`) walks::

    GET /v1/programs/search                         → candidates
    GET /v1/programs/{id}/eligibility_predicate     ← THIS ROUTE
    GET /v1/programs/{id}/narrative
    POST /v1/evidence/packets/batch
    GET /v1/audit/proof/{epid}

Step 2 was MCP-only after Wave 26 (W29-9 e2e finding), which broke
HTTP-only customer agents. We expose the same SELECT here so the chain
walks end-to-end.

Source of truth: ``am_program_eligibility_predicate_json`` (autonomath.db,
migration 164). Returned envelope carries the standard
``_disclaimer + corpus_snapshot_id + audit_seal`` trio so step 7 of the
e2e (envelope shape audit) is satisfied.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import sqlite3
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, status
from fastapi import Path as PathParam
from fastapi.responses import JSONResponse

from jpintel_mcp.api._audit_seal import attach_seal_to_body
from jpintel_mcp.api._corpus_snapshot import attach_corpus_snapshot, snapshot_headers
from jpintel_mcp.api._error_envelope import COMMON_ERROR_RESPONSES
from jpintel_mcp.api.deps import ApiContextDep, DbDep, log_usage
from jpintel_mcp.config import settings

_log = logging.getLogger("jpintel.api.eligibility_predicate")

router = APIRouter(prefix="/v1/programs", tags=["eligibility-predicate"])


# Predicate is search-derived and can be partial — fence the customer LLM
# against treating it as authoritative eligibility advice.
_PREDICATE_DISCLAIMER = (
    "本 predicate は jpi_programs corpus snapshot から rule-based 抽出されたものであり、"
    "missing axis = 'unknown' (no constraint ではない)。 最終的な受給可否判定は "
    "primary source (source_url) と税理士・行政書士の確認を必ず行ってください。 "
    "jpcite は税理士法 §52 に基づき個別具体的な税務判断・申請書作成代行は行いません。"
)


def _safe_json_loads(blob: str | None) -> Any:
    if not blob:
        return None
    try:
        return json.loads(blob)
    except (json.JSONDecodeError, TypeError):
        return None


def _open_autonomath_ro() -> sqlite3.Connection:
    """Read-only connection to autonomath.db without polluting the
    thread-local cache held by ``autonomath_tools.db.connect_autonomath``.

    The MCP-side cache is Wave-3-gated to read-only mode and pinned to
    one connection per thread; opening a second connection here keeps
    request threads from contending with cron writers and avoids the
    cache leaking into FastAPI workers.
    """
    path = os.environ.get("AUTONOMATH_DB_PATH", str(settings.autonomath_db_path))
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


@router.get(
    "/{program_id}/eligibility_predicate",
    summary="Per-program eligibility predicate JSON",
    description=(
        "Returns the structured eligibility predicate cached in "
        "``am_program_eligibility_predicate_json`` (autonomath.db, "
        "migration 164) for one program. Customer LLMs evaluate "
        "'does program X cover corp Y?' via boolean logic over the "
        "predicate object instead of re-reading 公募要領 prose every "
        "query — drops per-evaluation token cost.\n\n"
        "**Predicate axes** (all optional; missing key = unknown, NOT "
        "'no constraint'):\n\n"
        "- `industries_jsic`: JSIC major letters (e.g. `['A','D']`)\n"
        "- `prefectures` / `prefecture_jis` / `municipalities`\n"
        "- `capital_max_yen` / `employee_max` / `min_business_years`\n"
        "- `target_entity_types`, `crop_categories`, `funding_purposes`\n"
        "- `certifications_any_of`, `age`, `raw_constraints`\n\n"
        "Mirrors the MCP tool ``get_program_eligibility_predicate``."
    ),
    responses={
        **COMMON_ERROR_RESPONSES,
        200: {
            "description": (
                "Predicate envelope + `_disclaimer` + `corpus_snapshot_id` "
                "+ `audit_seal` (paid keys only)."
            ),
        },
        404: {
            "description": (
                "No predicate cached for this program_id. Either the id "
                "is unknown, or the corpus snapshot pre-dates migration 164."
            ),
        },
    },
)
def get_eligibility_predicate(
    program_id: Annotated[
        str,
        PathParam(
            description=(
                "jpi_programs.unified_id (例: 'UNI-75690a3d74'). Discover via /v1/programs/search."
            ),
            min_length=4,
            max_length=64,
        ),
    ],
    conn: DbDep,
    ctx: ApiContextDep,
    include_raw_constraints: Annotated[
        bool,
        Query(
            description=(
                "True で raw_constraints (regex 抽出失敗の生 text) を含める。"
                "False で軽量 envelope のみ返す (token 節約用)。"
            ),
        ),
    ] = True,
) -> JSONResponse:
    """Return the eligibility predicate envelope for ``program_id``."""

    sql = """
        SELECT pred.program_id,
               pred.predicate_json,
               pred.extraction_method,
               pred.confidence,
               pred.extracted_at,
               pred.source_program_corpus_snapshot_id,
               prog.primary_name
          FROM am_program_eligibility_predicate_json pred
          LEFT JOIN jpi_programs prog
            ON prog.unified_id = pred.program_id
         WHERE pred.program_id = ?
         LIMIT 1
    """

    am_conn = _open_autonomath_ro()
    try:
        try:
            row = am_conn.execute(sql, (program_id,)).fetchone()
        except sqlite3.OperationalError as exc:
            if "no such table" in str(exc).lower():
                _log.warning("am_program_eligibility_predicate_json missing: %s", exc)
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=(
                        "eligibility predicate cache not provisioned on this "
                        f"volume (migration 164 pending); program_id={program_id} "
                        "has no predicate available."
                    ),
                ) from exc
            raise
    finally:
        with contextlib.suppress(Exception):
            am_conn.close()

    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"no predicate cached for program_id={program_id!r}. "
                "Verify via /v1/programs/search; if the program exists "
                "but has no predicate row, the corpus snapshot may "
                "pre-date migration 164."
            ),
        )

    predicate = _safe_json_loads(row["predicate_json"]) or {}
    if not include_raw_constraints and "raw_constraints" in predicate:
        predicate = {k: v for k, v in predicate.items() if k != "raw_constraints"}

    notes = [
        "missing_axis_means_unknown — absent key does NOT mean no constraint",
        "verify_primary_source_before_filing — predicate is search-derived",
    ]
    method = row["extraction_method"]
    if method == "rule_based":
        notes.append(
            "rule_based extraction: regex over jpi_programs.enriched_json — "
            "expect partial coverage, confidence reflects axis density"
        )

    body: dict[str, Any] = {
        "program_id": row["program_id"],
        "program_name": row["primary_name"],
        "predicate": predicate,
        "extraction_method": method,
        "confidence": row["confidence"],
        "extracted_at": row["extracted_at"],
        "source_program_corpus_snapshot_id": row["source_program_corpus_snapshot_id"],
        "notes": notes,
        "_disclaimer": _PREDICATE_DISCLAIMER,
    }

    # Standard envelope trio: corpus_snapshot_id (jpintel-side, for the
    # auditor work-paper) + audit_seal (paid keys only).
    attach_corpus_snapshot(body, conn)
    log_usage(
        conn,
        ctx,
        "programs.eligibility_predicate",
        strict_metering=True,
    )
    attach_seal_to_body(
        body,
        endpoint="programs.eligibility_predicate",
        request_params={
            "program_id": program_id,
            "include_raw_constraints": include_raw_constraints,
        },
        api_key_hash=ctx.key_hash,
        conn=conn,
    )
    return JSONResponse(content=body, headers=snapshot_headers(conn))


__all__ = ["router"]
