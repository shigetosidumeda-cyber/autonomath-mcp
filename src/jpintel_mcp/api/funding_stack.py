"""REST endpoint for the Funding Stack Checker (no LLM rule engine).

Plan reference: ``docs/_internal/value_maximization_plan_no_llm_api.md`` §8.4.

Mounts ``POST /v1/funding_stack/check`` and answers the everyday consultant
question 「IT導入補助金 と 事業再構築補助金 を併用できるか?」 deterministically
against ``am_compat_matrix`` (autonomath.db) + ``exclusion_rules``
(data/jpintel.db).

Billing posture
---------------

One billable unit per **pair**. ``check_stack(["A","B","C"])`` evaluates 3
pairs (AB / AC / BC) and bills 3 units. At least two programs are required;
single-program requests are rejected before billing. The cap (``max_pairs=10``) caps
spend per call at ¥30 (税込 ¥33) — practical for a consultant building a
small portfolio matrix without runaway billing surfaces.

Input cap
---------

5 programs (C(5, 2) = 10 pairs) is the UX limit. 6+ programs returns 422 so
callers see a clear validation error rather than silently being charged for
a useless 15-pair matrix.
"""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from jpintel_mcp.api._audit_seal import attach_seal_to_body
from jpintel_mcp.api.deps import ApiContextDep, DbDep, log_usage
from jpintel_mcp.config import settings
from jpintel_mcp.services.funding_stack_checker import FundingStackChecker

logger = logging.getLogger("jpintel.api.funding_stack")

router = APIRouter(prefix="/v1/funding_stack", tags=["funding-stack"])

# Practical UX limit: C(5, 2) = 10 pairs.
_MAX_PROGRAMS = 5


class FundingStackCheckRequest(BaseModel):
    """POST body for ``/v1/funding_stack/check``.

    ``program_ids`` is a 2..5 item list. Each id should be a
    jpcite ``unified_id`` or a primary program name; the matcher also
    accepts legacy curated rule keys for backwards compatibility.
    """

    program_ids: Annotated[
        list[str],
        Field(
            ...,
            min_length=2,
            max_length=_MAX_PROGRAMS,
            description=(
                "List of program identifiers to evaluate as a stack. "
                "C(N, 2) pairs are evaluated (N=5 → 10 pairs). 1 billed "
                "unit per pair. At least two programs are required."
            ),
        ),
    ]


# ---------------------------------------------------------------------------
# Module-level singleton. The compat matrix has 43,966 rows and we don't
# want to re-load it on every request. Lazy-built on first call so import
# of this module never opens the DBs (keeps tests / smoke imports cheap).
# ---------------------------------------------------------------------------

_checker: FundingStackChecker | None = None


def _get_checker() -> FundingStackChecker:
    global _checker
    if _checker is None:
        try:
            _checker = FundingStackChecker(
                jpintel_db=settings.db_path,
                autonomath_db=settings.autonomath_db_path,
            )
        except FileNotFoundError as exc:
            # 503 — DB asset missing on the deployment. Caller-fixable
            # only by the operator.
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "code": "db_unavailable",
                    "message": (f"funding_stack checker のデータソースが見つかりません: {exc}"),
                },
            ) from exc
    return _checker


def reset_checker() -> None:
    """Drop the cached checker. Called by tests after monkeypatching DB paths."""

    global _checker
    _checker = None


@router.post(
    "/check",
    summary="制度併用可否判定 (Funding Stack Checker — no LLM)",
    description=(
        "複数の制度 (program_ids) を併用できるかを am_compat_matrix と "
        "exclusion_rules で判定し、pair 毎の verdict と全体集計を返す。\n\n"
        "* 1 unit = 1 pair なので、3 件 = 3 pair = 3 unit (¥9 / 税込 ¥9.90)\n"
        "* `incompatible` / `requires_review` の pair が 1 件でもあれば、"
        "all_pairs_status はその strictness にエスカレーションする\n"
        "* `_disclaimer` フィールドは必須 — 非 LLM rule engine は curate された "
        "コーパスに 100% 依拠するため、収録漏れや公募回ごとの細則差を取りこぼし得る。"
        "最終判断は必ず一次資料 + 専門家確認を経ること。"
    ),
)
def check_funding_stack(
    payload: FundingStackCheckRequest,
    conn: DbDep,
    ctx: ApiContextDep,
) -> dict[str, Any]:
    program_ids = payload.program_ids
    if len(program_ids) < 2:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "too_few_programs",
                "message": "program_ids は 2 件以上必要です。1 件のリクエストは課金されません。",
            },
        )
    if len(program_ids) > _MAX_PROGRAMS:
        # Pydantic Field max_length already enforces this, but keep an
        # explicit guard so a future schema relaxation doesn't silently
        # uncap spend.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "too_many_programs",
                "message": (
                    f"program_ids は最大 {_MAX_PROGRAMS} 件までです (received {len(program_ids)})。"
                ),
            },
        )

    checker = _get_checker()
    result = checker.check_stack(program_ids)
    body = result.to_dict()

    # ---- Billing: 1 unit per pair ----
    # check_stack already de-dupes program_ids; result.pairs reflects the
    # actual evaluated pair count (C(unique, 2)) which is what we bill.
    quantity = len(result.pairs)
    if quantity < 1:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "too_few_unique_programs",
                "message": (
                    "併用可否の判定には重複を除いて 2 件以上の program_ids が必要です。"
                    "このリクエストは課金されません。"
                ),
            },
        )

    log_usage(
        conn,
        ctx,
        "funding_stack.check",
        params={
            "program_count": len(result.program_ids),
            "pair_count": len(result.pairs),
        },
        quantity=quantity,
        result_count=len(result.pairs),
        strict_metering=True,
    )
    # §17.D audit seal on paid responses (no-op for anon).
    attach_seal_to_body(
        body,
        endpoint="funding_stack.check",
        request_params={
            "program_ids": list(result.program_ids),
        },
        api_key_hash=ctx.key_hash,
        conn=conn,
    )
    return body


__all__ = ["router", "FundingStackCheckRequest", "reset_checker"]
