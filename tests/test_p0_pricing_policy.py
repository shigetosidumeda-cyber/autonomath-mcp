from __future__ import annotations

from jpintel_mcp.agent_runtime.outcome_catalog import build_outcome_catalog
from jpintel_mcp.agent_runtime.pricing_policy import (
    PRICE_BY_PRICING_POSTURE,
    build_execute_input_hash,
    cap_passes,
    normalize_price_cap,
    price_for_pricing_posture,
    validate_pricing_policy_complete,
)
from jpintel_mcp.mcp.autonomath_tools.jpcite_facade import _execute_input_hash


def test_pricing_policy_covers_every_outcome_catalog_posture() -> None:
    postures = {entry.pricing_posture for entry in build_outcome_catalog()}

    validate_pricing_policy_complete(postures)

    assert postures <= set(PRICE_BY_PRICING_POSTURE)
    for posture in postures:
        price = price_for_pricing_posture(posture)
        assert isinstance(price, int)
        assert price >= 0


def test_zero_price_cap_is_not_unlimited() -> None:
    assert normalize_price_cap(None) is None
    assert normalize_price_cap(0) == 0
    assert cap_passes(600, None) is True
    assert cap_passes(600, 0) is False
    assert cap_passes(600, 600) is True


def test_execute_input_hash_is_shared_by_rest_and_mcp_contract() -> None:
    assert _execute_input_hash("company_public_baseline", 600) == build_execute_input_hash(
        "company_public_baseline",
        600,
    )
    assert _execute_input_hash("company_public_baseline", None) == build_execute_input_hash(
        "company_public_baseline",
        None,
    )
    assert _execute_input_hash("company_public_baseline", 0) != _execute_input_hash(
        "company_public_baseline",
        None,
    )
