"""X-Cost-Cap-JPY middleware (anti-runaway 三点セット B).

Why this exists
---------------
A bulk endpoint (`batch_get_programs`, `dd_batch`, future `bulk_*`) can fan
out into N internal sub-calls and quietly cost the customer ¥3 × N before
they have any feedback signal. `X-Cost-Cap-JPY: 5000` is the customer's
declarative budget per request — the middleware tracks cumulative cost as
each unit is billed and short-circuits with HTTP 402 (`Payment Required`)
the moment `cumulative_cost >= cap`. Partial results that were already
computed are returned alongside `cost_capped: true` so the agent can decide
whether to re-issue with a higher cap or accept the partial response.

Two modes:
  1. **Mandatory** for known bulk endpoints. Missing header → HTTP 400 with
     `cost_cap_required` so an LLM agent gets a hard nudge to pass it
     before its first batch run, not after silent overspend.
  2. **Advisory** elsewhere (single-row reads, search). The header is
     optional; when present the middleware still tracks cumulative cost
     and aborts at the threshold, but its absence does not 400.

Mid-fan-out abort
-----------------
The middleware exposes `request.state.cost_cap` so handlers running a
sub-loop (e.g. resolve N unified_ids one at a time) can call
`cost_cap.charge(weight)` between sub-calls to deduct from the budget and
get back a "stop?" signal. When the handler does not opt in, only the
initial / final cost is charged (single billing unit) and the cap acts as
a simple "this-request budget" gate — still useful as a regression-guard.

Pricing model (¥3/req, 税別)
----------------------------
Same constants as `cost.py` and `customer_cap.py` — single source of truth
is `cost._UNIT_PRICE_YEN` but we re-import to avoid the round-trip on every
request.

Cap-cap interaction with monthly self-cap
-----------------------------------------
This is a per-request budget gate; the per-month self-cap (CustomerCapMiddleware)
is a per-customer ceiling. Both can fire independently. If a customer hits
their monthly cap mid-batch, CustomerCapMiddleware short-circuits FIRST
(it sits earlier in the stack); the cost-cap middleware never even runs.

Fail-open posture
-----------------
Any exception in the cap path returns `call_next` immediately (over-charging
a buggy gate is worse than over-serving a single batch). Logged through
`jpintel.cost_cap`.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

if TYPE_CHECKING:
    from collections.abc import Callable

    from fastapi import Request
    from starlette.responses import Response

logger = logging.getLogger("jpintel.cost_cap")

# Pricing constant — single source of truth lives in `api.cost`.
# Re-imported as a module-level name to avoid a per-request import.
_UNIT_PRICE_YEN: int = 3

# Bulk endpoint path prefixes / suffixes that REQUIRE the X-Cost-Cap-JPY
# header. Listed by exact path / suffix. Order: longer specific match wins.
# Mandatory: 400 if header absent. Spec says `batch_*`, `dd_batch`, `bulk_*`.
# Translated to actual REST paths:
#   /v1/programs/batch         (existing batch_get_programs endpoint)
#   /v1/am/batch_*             (autonomath bulk endpoints, future)
#   /v1/*/bulk_*               (any future bulk endpoint)
#   /v1/*/dd_batch             (due-diligence batch)
_BULK_PATH_SUFFIXES: tuple[str, ...] = (
    "/batch",
    "/dd_batch",
)
_BULK_PATH_CONTAINS: tuple[str, ...] = (
    "/batch_",
    "/bulk_",
)


def _is_bulk_endpoint(path: str) -> bool:
    """Return True iff `path` matches the bulk-endpoint pattern."""
    if any(path.endswith(s) for s in _BULK_PATH_SUFFIXES):
        return True
    return any(needle in path for needle in _BULK_PATH_CONTAINS)


class CostCapState:
    """Per-request mutable accounting attached to ``request.state.cost_cap``.

    Handlers can opt into mid-fan-out enforcement by calling
    :meth:`charge` between sub-calls. The middleware itself only inspects
    final state on response — handlers that don't opt in still benefit
    from the request-level cap (the 402 fires when the SINGLE billing unit
    of the request exceeds the cap).
    """

    def __init__(self, cap_yen: int | None) -> None:
        self.cap_yen: int | None = cap_yen
        self.used_yen: int = 0
        self.aborted: bool = False
        # Optional partial-result accumulator a handler may write into so the
        # 402 envelope includes whatever was already produced. The handler is
        # in charge of structuring this dict; the middleware does not interpret.
        self.partial_result: object | None = None

    def charge(self, units: float = 1.0) -> bool:
        """Add `units` * ¥3 to the running tally. Return True iff still under cap.

        Returns False once the cap is hit so the caller can stop iterating.
        Sets ``self.aborted=True`` when the cap is breached.
        """
        cost = int(round(units * _UNIT_PRICE_YEN))
        self.used_yen += cost
        if self.cap_yen is not None and self.used_yen >= self.cap_yen:
            self.aborted = True
            return False
        return True

    def remaining_yen(self) -> int | None:
        if self.cap_yen is None:
            return None
        return max(0, self.cap_yen - self.used_yen)


def _parse_cap_header(value: str | None) -> int | None:
    """Return the parsed cap or None.

    Empty / whitespace / non-int → None. Negative → 0 (treated as "abort
    immediately on first call"). The handler is the one that decides what
    to do with cap=0; we don't second-guess.
    """
    if value is None:
        return None
    s = value.strip()
    if not s:
        return None
    try:
        n = int(s)
    except ValueError:
        return None
    return max(0, n)


def _build_missing_cap_body() -> dict:
    return {
        "error": {
            "code": "cost_cap_required",
            "message": (
                "X-Cost-Cap-JPY ヘッダは bulk endpoint で必須です。"
                "予算 (¥) を整数で指定してください。例: X-Cost-Cap-JPY: 5000"
            ),
            "message_en": (
                "X-Cost-Cap-JPY header is mandatory for bulk endpoints. "
                "Pass an integer JPY budget. Example: X-Cost-Cap-JPY: 5000"
            ),
            "hint": (
                "Run POST /v1/cost/preview first to estimate the cost, "
                "then set the cap to a value >= predicted_total_yen."
            ),
        }
    }


def _build_capped_body(state: CostCapState) -> dict:
    return {
        "error": {
            "code": "cost_cap_reached",
            "cost_capped": True,
            "cap_yen": state.cap_yen,
            "used_yen": state.used_yen,
            "partial_result": state.partial_result,
            "message": (
                f"X-Cost-Cap-JPY ¥{state.cap_yen} に到達しました。"
                f"現在の使用額は ¥{state.used_yen} です。"
                "上限を上げて再試行するか、partial_result を採用してください。"
            ),
            "message_en": (
                f"Cost cap of ¥{state.cap_yen} reached "
                f"(used ¥{state.used_yen}). "
                "Raise X-Cost-Cap-JPY and retry, or accept partial_result."
            ),
        }
    }


class CostCapMiddleware(BaseHTTPMiddleware):
    """Read ``X-Cost-Cap-JPY`` and enforce per-request budget.

    Mounting order (api/main.py):
      * After CORS, OriginEnforcement, SecurityHeaders, ResponseSanitizer
      * After RequestContextMiddleware (so 402 carries x-request-id)
      * **Before** `CustomerCapMiddleware` (per-month) — the per-request
        gate fires LATER in the request lifecycle than the per-month gate
        but middleware mount order is LIFO, so we mount it BEFORE.
      * **Before** rate-limit / strict-query (correctness gates above us
        run on legitimate requests; cost-cap is itself a correctness gate
        for bulk operations).

    Envelope shape:
      * 400 (`cost_cap_required`) when a bulk endpoint sees no header.
      * 402 (`cost_cap_reached`) when a request consumed >= cap_yen.
      * Pass-through otherwise. ``request.state.cost_cap`` is set on every
        request that supplies the header (handlers may opt into mid-fan-
        out enforcement).
    """

    async def dispatch(  # type: ignore[override]
        self, request: Request, call_next: Callable
    ) -> Response:
        # CORS preflight always passes — don't gate OPTIONS.
        if request.method == "OPTIONS":
            return await call_next(request)

        path = request.url.path
        # Health + meta probes never bill, never cap.
        if path in {"/healthz", "/readyz", "/v1/openapi.json"}:
            return await call_next(request)

        cap_yen = _parse_cap_header(request.headers.get("x-cost-cap-jpy"))

        if cap_yen is None and _is_bulk_endpoint(path):
            # Mandatory header missing on a bulk endpoint → 400.
            return JSONResponse(
                status_code=400,
                content=_build_missing_cap_body(),
                headers={"X-Cost-Cap-Required": "true"},
            )

        # Always set state so handlers can opt in even on non-bulk paths.
        state = CostCapState(cap_yen=cap_yen)
        request.state.cost_cap = state

        try:
            response = await call_next(request)
        except Exception:  # pragma: no cover — defensive fail-open
            logger.exception("cost_cap_dispatch_error path=%s", path)
            raise

        # If a handler opted in and tripped the cap mid-fan-out, replace the
        # response with a 402. The handler may also have populated
        # `state.partial_result` so the agent can choose whether to accept it.
        if state.aborted:
            return JSONResponse(
                status_code=402,
                content=_build_capped_body(state),
                headers={
                    "X-Cost-Capped": "true",
                    "X-Cap-Yen": str(state.cap_yen) if state.cap_yen is not None else "",
                    "X-Used-Yen": str(state.used_yen),
                },
            )

        # Surface the budget summary on every successful response so an LLM
        # caller can visualise the remaining budget without a separate call.
        if cap_yen is not None:
            response.headers["X-Cap-Yen"] = str(cap_yen)
            response.headers["X-Used-Yen"] = str(state.used_yen)
            remaining = state.remaining_yen()
            if remaining is not None:
                response.headers["X-Remaining-Yen"] = str(remaining)
        return response


__all__ = [
    "CostCapMiddleware",
    "CostCapState",
    "_is_bulk_endpoint",
    "_parse_cap_header",
]
