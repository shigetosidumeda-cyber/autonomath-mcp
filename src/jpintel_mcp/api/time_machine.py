"""Regulatory Time Machine REST endpoints.

Two routes that surface the `time_machine_tools` MCP wrappers as HTTP:

  GET /v1/programs/{program_id}/at?as_of=YYYY-MM-DD
  GET /v1/programs/{program_id}/evolution/{year}

Pricing: ¥3/req metered (1 unit per call). The evolution variant runs 12
internal pivots but bills as a single ¥3 unit. Anonymous callers share
the 3/日 per-IP cap via ``AnonIpLimitDep`` on the router mount in
``api/main.py``.

Sensitive (§52 / §47条の2 / §72 / §1) — NOT 採択 prediction. Each
response carries the ``_disclaimer`` envelope from
``time_machine_tools._DISCLAIMER`` and the canonical 3-axis citation
(``source_url`` + ``source_fetched_at`` + ``source_sha256``). Pure SQL +
Python — NO LLM call.
"""

from __future__ import annotations

import logging
import time
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, status
from fastapi import Path as PathParam

from jpintel_mcp.api._audit_seal import attach_seal_to_body
from jpintel_mcp.api.deps import ApiContextDep, DbDep, log_usage
from jpintel_mcp.mcp.autonomath_tools.time_machine_tools import (
    _query_at_snapshot_impl,
    _query_program_evolution_impl,
)

logger = logging.getLogger("jpintel.api.time_machine")

router = APIRouter(prefix="/v1/programs", tags=["time_machine"])


# R8 BUGHUNT (2026-05-07): canonical data_quality envelope for am_amendment_snapshot
# substrate. Numbers audited live on autonomath.db 2026-05-07. Re-probe on
# substrate rebuild — eligibility_hash invariant is the load-bearing caveat
# for any time-series interpretation.
_DATA_QUALITY_TIME_MACHINE: dict[str, Any] = {
    "substrate": "am_amendment_snapshot",
    "snapshot_total": 14_596,
    "with_effective_from": 140,
    "distinct_eligibility_hash": 1_141,
    "snapshot_source_legacy_v1_count": 14_596,
    "caveat": (
        "am_amendment_snapshot 14,596 行のうち effective_from 確定は 140 行のみ。"
        "残 14,456 行は observed_at スタンプのみで時系列の正確性は保証されない。"
        "eligibility_hash の distinct は 1,141/14,596 — v1 と v2 で hash が変わらない "
        "row が大量にあり、'時系列の差分が常に意味を持つ' という前提は成立しない。"
        "as_of 指定の replay は 'best-effort frozen view' であり、確定論的 eligibility "
        "判定ではない。"
    ),
}


@router.get(
    "/{program_id}/at",
    summary="Time Machine — frozen-at-date eligibility / amount / deadline",
    description=(
        "Replay the program's eligibility / amount / deadline as it was "
        "live on ``as_of``. Pivots off ``am_amendment_snapshot`` "
        "(14,596 captures + 144 definitive-dated rows) on the "
        "autonomath spine — NO jpintel-side dataset versioning required.\n\n"
        "**Pricing:** ¥3/call (1 unit). Anonymous tier shares the 3/日 IP "
        "cap.\n\n"
        "**SENSITIVE (§52 / §47条の2):** factual replay only — NOT 採択 "
        "prediction (use ``forecast_program_renewal`` for that)."
    ),
)
def query_at(
    program_id: Annotated[
        str,
        PathParam(
            min_length=1,
            max_length=200,
            description="Canonical jpcite program id (e.g. 'program:IT_DOUNYUU_HOJOKIN').",
            examples=["program:IT_DOUNYUU_HOJOKIN"],
        ),
    ],
    conn: DbDep,
    ctx: ApiContextDep,
    as_of: Annotated[
        str,
        Query(
            min_length=10,
            max_length=10,
            description=(
                "Snapshot pivot, ISO YYYY-MM-DD (JST). The version of the "
                "program live at that date is returned."
            ),
            examples=["2024-06-01"],
        ),
    ],
) -> dict[str, Any]:
    """Frozen-at-date eligibility replay."""
    if not program_id or not program_id.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "missing_required_arg",
                "message": "program_id is required.",
            },
        )

    t0 = time.perf_counter()
    body = _query_at_snapshot_impl(program_id=program_id, as_of=as_of)
    latency_ms = int((time.perf_counter() - t0) * 1000)

    if isinstance(body, dict):
        body.setdefault("data_quality", {}).update(_DATA_QUALITY_TIME_MACHINE)

    log_usage(
        conn,
        ctx,
        "time_machine.at",
        params={"program_id": program_id, "as_of": as_of},
        latency_ms=latency_ms,
        result_count=int(body.get("total", 0) or 0),
        quantity=1,
        strict_metering=True,
    )
    attach_seal_to_body(
        body,
        endpoint="time_machine.at",
        request_params={"program_id": program_id, "as_of": as_of},
        api_key_hash=ctx.key_hash,
        conn=conn,
    )
    return body


@router.get(
    "/{program_id}/evolution/{year}",
    summary="Time Machine — 12-month evolution grid",
    description=(
        "Run ``query_at_snapshot`` at every month-end of ``year`` in one "
        "call (single ¥3 metered event, 11 cached reads). Surfaces "
        "``change_months`` so a 12-month diligence walk takes ONE HTTP "
        "fetch instead of 12.\n\n"
        "**Pricing:** ¥3/call (1 unit total).\n\n"
        "**SENSITIVE (§52 / §47条の2):** factual replay only."
    ),
)
def query_evolution(
    program_id: Annotated[
        str,
        PathParam(
            min_length=1,
            max_length=200,
            description="Canonical jpcite program id.",
            examples=["program:IT_DOUNYUU_HOJOKIN"],
        ),
    ],
    year: Annotated[
        int,
        PathParam(
            ge=1900,
            le=2100,
            description="Calendar year (e.g. 2024). 12 month-end pivots returned.",
            examples=[2024],
        ),
    ],
    conn: DbDep,
    ctx: ApiContextDep,
) -> dict[str, Any]:
    """12-month evolution grid in a single billing event."""
    if not program_id or not program_id.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "missing_required_arg",
                "message": "program_id is required.",
            },
        )

    t0 = time.perf_counter()
    body = _query_program_evolution_impl(program_id=program_id, year=year)
    latency_ms = int((time.perf_counter() - t0) * 1000)

    if isinstance(body, dict):
        body.setdefault("data_quality", {}).update(_DATA_QUALITY_TIME_MACHINE)

    log_usage(
        conn,
        ctx,
        "time_machine.evolution",
        params={"program_id": program_id, "year": year},
        latency_ms=latency_ms,
        result_count=int(body.get("total", 0) or 0),
        quantity=1,
        strict_metering=True,
    )
    attach_seal_to_body(
        body,
        endpoint="time_machine.evolution",
        request_params={"program_id": program_id, "year": year},
        api_key_hash=ctx.key_hash,
        conn=conn,
    )
    return body


__all__ = ["router"]
