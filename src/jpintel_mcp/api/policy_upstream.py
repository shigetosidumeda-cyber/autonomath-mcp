"""DEEP-46 政策 上流 signal 統合 REST surface.

Companion to ``mcp/autonomath_tools/policy_upstream_tools.py``. Two
endpoints that surface the same composition the MCP tools do:

  * ``POST /v1/policy_upstream/watch``
      body = ``{"keywords": ["DX","GX","事業承継"], "watch_period_days": 90}``
      → per-keyword rollup of kokkai count + shingikai count + ongoing-
        pubcomment count + most-recent evidence URL on each axis.

  * ``GET /v1/policy_upstream/{topic}/timeline?limit=50``
      → 国会 → 審議会 → パブコメ → 改正 → 制度 chain in chronological
        order for one topic.

Both routes delegate to the MCP tool ``_impl`` so SQL + envelope contract
stay identical between the MCP and REST surfaces. Mounted with
``AnonIpLimitDep`` in ``api/main.py`` so the anonymous 3 req/日 IP quota
applies; authenticated paid keys are metered ¥3/req via ``log_usage``.
NO LLM call inside the wrapper — pure SQLite over autonomath.db.
"""

from __future__ import annotations

import time
from typing import Annotated, Any

from fastapi import APIRouter, Body, Path, Query
from pydantic import BaseModel, Field

from jpintel_mcp.api.deps import ApiContextDep, DbDep, log_usage
from jpintel_mcp.mcp.autonomath_tools.policy_upstream_tools import (
    _policy_upstream_timeline_impl,
    _policy_upstream_watch_impl,
)

router = APIRouter(prefix="/v1/policy_upstream", tags=["policy-upstream"])


# R8_BUGHUNT_DISCLAIMER_R2 (2026-05-07): policy upstream は kokkai_utterance +
# shingikai_minutes + pubcomment_announcement + am_amendment_diff + programs を
# 機械的に keyword fence + JOIN した signal rollup。topic に「事業承継」「適格"
# 請求書」「AI規制」等の 制度・法令 改正に直結する keyword を渡せるため、
# 業法 fence (税理士法 §52 / 弁護士法 §72 / 行政書士法 §1) を明示する。
_DISCLAIMER_POLICY_UPSTREAM = (
    "本 policy upstream rollup は kokkai_utterance + shingikai_minutes + "
    "pubcomment_announcement + am_amendment_diff + programs を機械的に "
    "keyword fence で集計した **公開情報の signal rollup** であり、"
    "税理士法 §52 (税務代理) ・弁護士法 §72 (法律事務) ・行政書士法 §1 "
    "(申請代理) のいずれにも該当しません。signal_strength は 5 軸の加重和で "
    "あり、LLM 推論は含まれない。法令改正・制度変更の確定判断は各 source_url "
    "の一次資料 (国会・所管庁・e-Gov) を必ずご確認ください。"
)


class PolicyUpstreamWatchRequest(BaseModel):
    """POST body for ``/v1/policy_upstream/watch``.

    Mirrors the MCP ``policy_upstream_watch`` signature so the two
    surfaces stay schema-aligned. The ``watch_period_days`` upper bound
    is 365 (1 year); the keyword list cap is 20 entries.
    """

    keywords: list[str] = Field(
        ...,
        min_length=1,
        max_length=20,
        description=(
            "1..20 業法 / 制度 keyword (e.g. ['DX','GX','事業承継']). "
            "Substring match against kokkai_utterance.body / "
            "shingikai_minutes.{agenda,body_text} / "
            "pubcomment_announcement.{target_law,summary_text} / "
            "am_amendment_diff."
        ),
    )
    watch_period_days: int = Field(
        default=90,
        ge=1,
        le=365,
        description="Window length in days (1..365, default 90).",
    )


@router.post(
    "/watch",
    summary="Cross-axis upstream signal rollup over kokkai + shingikai + pubcomment",
)
def policy_upstream_watch(
    payload: Annotated[
        PolicyUpstreamWatchRequest,
        Body(
            ...,
            examples=[
                {
                    "keywords": ["DX", "GX", "事業承継"],
                    "watch_period_days": 90,
                },
            ],
        ),
    ],
    conn: DbDep,
    ctx: ApiContextDep,
) -> dict[str, Any]:
    """Per-keyword cross-axis upstream signal rollup.

    Returns one row per keyword with kokkai (国会) / shingikai (審議会) /
    pubcomment (パブコメ) / amendment (am_amendment_diff) / programs
    counts within the window, plus the most-recent evidence URL on
    each axis. Sort: signal_strength DESC. NO LLM, single ¥3/req
    billing event.
    """
    _t0 = time.perf_counter()
    body = _policy_upstream_watch_impl(
        keywords=list(payload.keywords),
        watch_period_days=int(payload.watch_period_days),
    )
    _latency_ms = int((time.perf_counter() - _t0) * 1000)
    result_count = int(body.get("total", 0)) if isinstance(body, dict) else 0
    log_usage(
        conn,
        ctx,
        "policy_upstream.watch",
        latency_ms=_latency_ms,
        result_count=result_count,
        strict_metering=True,
    )
    # R8_BUGHUNT_DISCLAIMER_R2 (2026-05-07): 業法 fence — additive only,
    # never overwrite an impl-supplied _disclaimer.
    if isinstance(body, dict) and "_disclaimer" not in body:
        body["_disclaimer"] = _DISCLAIMER_POLICY_UPSTREAM
    return body


@router.get(
    "/{topic}/timeline",
    summary="Single-topic timeline across kokkai → shingikai → pubcomment → 改正 → 制度",
)
def policy_upstream_timeline(
    topic: Annotated[
        str,
        Path(
            min_length=1,
            max_length=120,
            description=("Single 業法 / 制度 keyword (e.g. '事業承継' / '適格請求書' / 'AI規制')."),
        ),
    ],
    conn: DbDep,
    ctx: ApiContextDep,
    limit: Annotated[
        int,
        Query(
            ge=1,
            le=200,
            description="Max merged events (1..200, default 50).",
        ),
    ] = 50,
) -> dict[str, Any]:
    """Single-topic chain across 5 stages, ASC by date.

    Each event carries a ``stage`` literal (``kokkai`` / ``shingikai`` /
    ``pubcomment`` / ``law_amendment`` / ``program_launch``) plus
    3-axis citation when available (source_url + retrieved_at +
    sha256). NO LLM, single ¥3/req billing event.
    """
    _t0 = time.perf_counter()
    body = _policy_upstream_timeline_impl(
        topic=topic,
        limit=limit,
    )
    _latency_ms = int((time.perf_counter() - _t0) * 1000)
    result_count = int(body.get("total", 0)) if isinstance(body, dict) else 0
    log_usage(
        conn,
        ctx,
        "policy_upstream.timeline",
        latency_ms=_latency_ms,
        result_count=result_count,
        strict_metering=True,
    )
    # R8_BUGHUNT_DISCLAIMER_R2 (2026-05-07): 業法 fence — additive only,
    # never overwrite an impl-supplied _disclaimer.
    if isinstance(body, dict) and "_disclaimer" not in body:
        body["_disclaimer"] = _DISCLAIMER_POLICY_UPSTREAM
    return body
