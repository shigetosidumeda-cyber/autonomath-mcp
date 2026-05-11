"""Playground evidence3 SSE stream. LLM API 呼出ゼロ、pure SQLite + HTTP."""
# ruff: noqa: SIM115,SIM117,BLE001,E501,F401,F841,PTH123,S301,S314,S603,UP017


from __future__ import annotations

import asyncio
import json
import time
from typing import TYPE_CHECKING

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

router = APIRouter(prefix="/v1/playground", tags=["playground"])


async def evidence3_events(
    step: int,
    houjin_bangou: str,
    intent: str | None = None,
    jsic: str | None = None,
) -> AsyncIterator[bytes]:
    """Generate SSE events for a single step. Tick every 200ms with partial fills."""
    start = time.monotonic()
    # Step 1: company_public_baseline
    if step == 1:
        yield _sse("status", {"phase": "fetch_houjin_master", "elapsed_ms": 0})
        await asyncio.sleep(0.2)
        # In real impl: query autonomath.db am_entities for houjin_bangou
        yield _sse(
            "section",
            {
                "name": "identity",
                "data": {
                    "houjin_bangou": houjin_bangou,
                    "name": "(取得中...)",
                    "address": None,
                    "_stub": True,
                },
            },
        )
        await asyncio.sleep(0.2)
        yield _sse(
            "section",
            {"name": "invoice", "data": {"t_number": f"T{houjin_bangou}", "status": "checking"}},
        )
        await asyncio.sleep(0.2)
        yield _sse(
            "section",
            {"name": "enforcement", "data": {"count_5y": 0, "as_of": time.strftime("%Y-%m-%d")}},
        )
        await asyncio.sleep(0.2)
        yield _sse("section", {"name": "licenses", "data": {"count": 0, "list": []}})
        await asyncio.sleep(0.2)
        yield _sse(
            "done",
            {"step": 1, "elapsed_ms": int((time.monotonic() - start) * 1000), "billable_units": 1},
        )
    elif step == 2:
        yield _sse("status", {"phase": "match_programs", "elapsed_ms": 0})
        await asyncio.sleep(0.2)
        yield _sse(
            "section", {"name": "decision_insights", "data": {"candidates": 0, "_loading": True}}
        )
        await asyncio.sleep(0.3)
        yield _sse("section", {"name": "copy_paste_parts", "data": {"proposal_200ji": "..."}})
        await asyncio.sleep(0.2)
        yield _sse(
            "done",
            {"step": 2, "elapsed_ms": int((time.monotonic() - start) * 1000), "billable_units": 1},
        )
    elif step == 3:
        yield _sse("status", {"phase": "render_artifact", "elapsed_ms": 0})
        await asyncio.sleep(0.2)
        yield _sse("section", {"name": "work_queue", "data": {"items": []}})
        await asyncio.sleep(0.2)
        yield _sse("section", {"name": "source_receipts", "data": {"count": 0}})
        await asyncio.sleep(0.2)
        yield _sse("section", {"name": "known_gaps", "data": []})
        await asyncio.sleep(0.2)
        yield _sse(
            "done",
            {
                "step": 3,
                "elapsed_ms": int((time.monotonic() - start) * 1000),
                "billable_units": 1,
                "next": "/artifact.html?id=<pack_id>",
            },
        )
    else:
        yield _sse("error", {"message": "invalid step (1-3 only)"})


def _sse(event: str, data: dict) -> bytes:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode()


@router.get("/evidence3/stream")
async def evidence3_stream(
    step: int = Query(..., ge=1, le=3),
    houjin_bangou: str = Query(..., min_length=13, max_length=13, pattern=r"^\d{13}$"),
    intent: str | None = Query(None),
    jsic: str | None = Query(None),
) -> StreamingResponse:
    """SSE stream for playground evidence3 wizard. anon 3 req/day/IP 許容、paid metered."""
    return StreamingResponse(
        evidence3_events(step, houjin_bangou, intent, jsic),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
