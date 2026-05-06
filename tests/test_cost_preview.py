from __future__ import annotations

import sqlite3

import pytest

from jpintel_mcp.api.cost import (
    CostPreviewArgsError,
    CostPreviewCall,
    compute_predicted_cost,
)


def _cost(*calls: CostPreviewCall) -> tuple[int, float]:
    predicted_yen, units, _breakdown, _has_tax = compute_predicted_cost(list(calls), 1)
    return predicted_yen, units


def test_batch_get_programs_preview_uses_deduped_id_quantity() -> None:
    yen, units = _cost(
        CostPreviewCall(
            tool="batch_get_programs",
            args={"unified_ids": ["UNI-a", "UNI-b", "UNI-a"]},
        )
    )

    assert units == 2
    assert yen == 6


def test_dd_batch_preview_uses_normalized_houjin_quantity() -> None:
    yen, units = _cost(
        CostPreviewCall(
            tool="am.dd_batch",
            args={
                "houjin_bangous": [
                    "T8010001213708",
                    "801-0001-213708",
                    "T8020001213708",
                ]
            },
        )
    )

    assert units == 2
    assert yen == 6


@pytest.mark.parametrize(
    ("bundle_class", "expected_units"),
    [("standard", 334), ("deal", 1001), ("case", 3334)],
)
def test_dd_export_preview_includes_bundle_quantity(bundle_class: str, expected_units: int) -> None:
    yen, units = _cost(
        CostPreviewCall(
            tool="/v1/am/dd_export",
            args={"houjin_bangous": ["8010001213708"], "bundle_class": bundle_class},
        )
    )

    assert units == expected_units
    assert yen == expected_units * 3


def test_audit_batch_preview_uses_fanout_quantity() -> None:
    yen, units = _cost(
        CostPreviewCall(
            tool="/v1/audit/batch_evaluate",
            args={
                "profiles": [{"client_id": f"c-{i}"} for i in range(25)],
                "target_ruleset_ids": ["TAX-a", "TAX-b", "TAX-a"],
            },
        )
    )

    assert units == 5
    assert yen == 15


def test_audit_snapshot_preview_uses_fixed_attestation_units() -> None:
    yen, units = _cost(CostPreviewCall(tool="audit.snapshot_attestation"))

    assert units == 10_000
    assert yen == 30_000


def test_canonical_tool_name_strips_method_query_and_absolute_url() -> None:
    yen, units = _cost(
        CostPreviewCall(
            tool="get https://api.jpcite.com/v1/audit/snapshot_attestation?year=2026",
        ),
        CostPreviewCall(
            tool="POST /v1/am/dd_export?download=1",
            args={"houjin_bangous": ["8010001213708"], "bundle_class": "standard"},
        ),
    )

    assert units == 10_000 + 334
    assert yen == (10_000 + 334) * 3


def test_funding_stack_preview_uses_pair_quantity() -> None:
    yen, units = _cost(
        CostPreviewCall(
            tool="/v1/funding_stack/check",
            args={"program_ids": ["A", "B", "C", "A"]},
        )
    )

    assert units == 3
    assert yen == 9


def test_known_fanout_preview_fails_closed_when_args_missing() -> None:
    with pytest.raises(CostPreviewArgsError, match="unified_ids list is required"):
        compute_predicted_cost([CostPreviewCall(tool="batch_get_programs")], 1)


def test_cost_preview_endpoint_returns_422_for_missing_fanout_args(client) -> None:
    response = client.post(
        "/v1/cost/preview",
        json={"stack_or_calls": [{"tool": "batch_get_programs"}]},
    )

    assert response.status_code == 422
    assert response.json()["detail"]["error"]["code"] == "cost_preview_requires_args"


def test_cost_preview_endpoint_does_not_consume_anon_quota(client, seeded_db) -> None:
    """The free estimator must not burn the anonymous 3/day discovery runway."""
    ip = "203.0.113.210"
    for _ in range(3):
        response = client.post(
            "/v1/cost/preview",
            json={"stack_or_calls": [{"tool": "/v1/programs/search"}]},
            headers={"x-forwarded-for": ip},
        )
        assert response.status_code == 200, response.text

    conn = sqlite3.connect(seeded_db)
    try:
        (count,) = conn.execute(
            "SELECT COUNT(*) FROM anon_rate_limit",
        ).fetchone()
    finally:
        conn.close()
    assert count == 0


def test_cost_preview_invalid_api_keys_share_ip_preview_throttle(client, seeded_db) -> None:
    """Bogus key rotation must not mint unlimited preview buckets."""
    from jpintel_mcp.api.cost import _reset_preview_rate_state

    _reset_preview_rate_state()
    ip = "203.0.113.211"
    last = None
    for i in range(51):
        last = client.post(
            "/v1/cost/preview",
            json={"stack_or_calls": [{"tool": "/v1/programs/search"}]},
            headers={
                "x-forwarded-for": ip,
                "X-API-Key": f"am_bogus_{i}",
            },
        )
    assert last is not None
    assert last.status_code == 429
    assert last.headers["Retry-After"]
    assert last.json()["detail"]["error"]["bucket"] == "cost_preview"


def test_openapi_operation_id_aliases_use_fanout_quantities() -> None:
    yen, units = _cost(
        CostPreviewCall(
            tool="post_dd_export_v1_am_dd_export_post",
            args={
                "houjin_bangous": ["8010001213708", "8020001213708"],
                "bundle_class": "standard",
            },
        ),
        CostPreviewCall(
            tool="snapshot_attestation_v1_audit_snapshot_attestation_get",
        ),
        CostPreviewCall(
            tool="batch_get_programs_v1_programs_batch_post",
            args={"unified_ids": ["UNI-a", "UNI-b", "UNI-a"]},
        ),
    )

    assert units == 335 + 10_000 + 2
    assert yen == int(units * 3)


def test_workpaper_operation_id_alias_uses_export_quantity() -> None:
    yen, units = _cost(
        CostPreviewCall(
            tool="render_workpaper_v1_audit_workpaper_post",
            args={"target_ruleset_ids": ["TAX-a", "TAX-b", "TAX-a"]},
        )
    )

    assert units == 12
    assert yen == 36


def test_bulk_evaluate_operation_id_alias_uses_row_count() -> None:
    yen, units = _cost(
        CostPreviewCall(
            tool="bulk_evaluate_clients_v1_me_clients_bulk_evaluate_post",
            args={"commit": True, "row_count": 25},
        )
    )

    assert units == 25
    assert yen == 75


def test_bulk_evaluate_preview_fails_closed_without_row_count() -> None:
    with pytest.raises(CostPreviewArgsError, match="row_count is required"):
        compute_predicted_cost(
            [
                CostPreviewCall(
                    tool="bulk_evaluate_clients_v1_me_clients_bulk_evaluate_post",
                    args={"commit": True},
                )
            ],
            1,
        )
