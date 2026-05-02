"""Handler-level per-request cost-cap guard for paid fan-out endpoints."""

from __future__ import annotations

from fastapi import HTTPException, status

from jpintel_mcp.api.middleware.cost_cap import _parse_cap_header


def _cost_cap_required_detail(predicted_yen: int) -> dict[str, object]:
    return {
        "code": "cost_cap_required",
        "message": (
            "X-Cost-Cap-JPY header or max_cost_jpy body field is required "
            "before this paid fan-out endpoint can bill."
        ),
        "predicted_yen": predicted_yen,
        "unit_price_yen": 3,
    }


def _cost_cap_exceeded_detail(*, predicted_yen: int, cost_cap_yen: int) -> dict[str, object]:
    return {
        "code": "cost_cap_exceeded",
        "message": (
            f"Predicted cost ¥{predicted_yen} exceeds cap ¥{cost_cap_yen}. "
            "Lower batch size or raise X-Cost-Cap-JPY / max_cost_jpy."
        ),
        "predicted_yen": predicted_yen,
        "cost_cap_yen": cost_cap_yen,
        "unit_price_yen": 3,
    }


def require_cost_cap(
    *,
    predicted_yen: int,
    header_value: str | None,
    body_cap_yen: int | None = None,
) -> int:
    """Require and enforce a caller-supplied per-request cost cap.

    Returns the binding cap in JPY. Raises before any billing side effect.
    """
    header_cap = _parse_cap_header(header_value)
    caps = [cap for cap in (header_cap, body_cap_yen) if cap is not None]
    if not caps:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail=_cost_cap_required_detail(predicted_yen),
        )
    binding = min(caps)
    if predicted_yen > binding:
        raise HTTPException(
            status.HTTP_402_PAYMENT_REQUIRED,
            detail=_cost_cap_exceeded_detail(
                predicted_yen=predicted_yen,
                cost_cap_yen=binding,
            ),
        )
    return binding


__all__ = ["require_cost_cap"]
