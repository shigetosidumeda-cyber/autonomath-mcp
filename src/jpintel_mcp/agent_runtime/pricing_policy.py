"""Deterministic P0 pricing and execute-scope helpers.

The facade uses these helpers before any live artifact execution exists. They
are pure: no clock, network, billing provider, database, or AWS dependency.
"""

from __future__ import annotations

import hashlib
import json
from types import MappingProxyType
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from jpintel_mcp.agent_runtime.outcome_catalog import PricingPosture

PRICE_BY_PRICING_POSTURE = MappingProxyType(
    {
        "free_preview": 0,
        "accepted_artifact_low": 300,
        "accepted_artifact_standard": 600,
        "accepted_artifact_premium": 900,
        "accepted_artifact_csv_overlay": 900,
    }
)


def price_for_pricing_posture(pricing_posture: str) -> int | None:
    """Return the deterministic JPY price for a catalog pricing posture."""

    return PRICE_BY_PRICING_POSTURE.get(pricing_posture)


def normalize_price_cap(max_price_jpy: int | None) -> int | None:
    """Normalize a user cap while preserving ``None`` as cap-not-specified."""

    if max_price_jpy is None:
        return None
    return max(0, int(max_price_jpy))


def cap_passes(price_jpy: int, max_price_jpy: int | None) -> bool:
    """Return whether a price is within the user's requested cap.

    ``None`` means the caller did not set a preview cap. A numeric ``0`` is a
    strict zero-yen cap and therefore blocks paid outcomes.
    """

    cap = normalize_price_cap(max_price_jpy)
    return cap is None or price_jpy <= cap


def build_execute_input_hash(outcome_contract_id: str, max_price_jpy: int | None) -> str:
    """Build the REST/MCP shared execute-scope hash for scoped cap tokens."""

    payload = {
        "max_price_jpy": normalize_price_cap(max_price_jpy),
        "outcome_contract_id": outcome_contract_id.strip(),
    }
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def validate_pricing_policy_complete(pricing_postures: set[PricingPosture]) -> None:
    """Fail if a catalog posture lacks a deterministic price."""

    missing = sorted(
        posture for posture in pricing_postures if posture not in PRICE_BY_PRICING_POSTURE
    )
    if missing:
        raise ValueError(f"missing pricing policy for: {', '.join(missing)}")


__all__ = [
    "PRICE_BY_PRICING_POSTURE",
    "build_execute_input_hash",
    "cap_passes",
    "normalize_price_cap",
    "price_for_pricing_posture",
    "validate_pricing_policy_complete",
]
