"""Tests for the migration 165 ``tokens_saved_estimated`` metric.

Two assertions per CLAUDE.md "Common gotchas" + the spec:

  * ``test_field_present_in_usage_response`` — paid + free authed branches
    of GET /v1/usage MUST include the new fields with non-negative
    integer values (zero is fine for a freshly-issued key with no rows).
    Anonymous tier returns 0 because there is no per-key audit trail.

  * ``test_calculation_uses_estimated_baseline`` — the helper
    ``_estimate_tokens_saved`` must apply the
    ``baseline = question_tokens * 5`` formula, subtract response tokens
    (``chars / 2.5``), and clamp at 0. Also asserts the rollup from a
    seeded ``usage_events`` row surfaces in the /v1/usage envelope.

LLM 0: helper is pure char-count arithmetic; nothing under
``src/jpintel_mcp/`` imports a tokenizer.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Field surface — both authed branches return the new keys
# ---------------------------------------------------------------------------


def test_field_present_in_usage_response(client: TestClient, paid_key: str) -> None:
    """Paid /v1/usage MUST carry the migration 165 token-saved rollup."""
    r = client.get("/v1/usage", headers={"X-API-Key": paid_key})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["tier"] == "paid"
    # Both fields present, integer, non-negative. Fresh paid key has no
    # usage rows yet so both are 0 — that is the contract for an empty
    # rollup, NOT an error. The dashboard treats 0 as "no calls yet".
    assert "tokens_saved_estimated_total" in body, body
    assert "tokens_saved_estimated_per_call" in body, body
    assert isinstance(body["tokens_saved_estimated_total"], int)
    assert isinstance(body["tokens_saved_estimated_per_call"], int)
    assert body["tokens_saved_estimated_total"] == 0
    assert body["tokens_saved_estimated_per_call"] == 0


def test_field_present_in_anonymous_usage_response(
    client: TestClient,
) -> None:
    """Anonymous /v1/usage MUST carry the new fields with default 0.

    Anonymous tier has no per-key audit trail; surfacing 0 (not omitting
    the field) keeps the JSON shape stable across all three tiers so
    the dashboard front-end never branches on key existence.
    """
    r = client.get("/v1/usage", headers={"x-forwarded-for": "203.0.113.99"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["tier"] == "anonymous"
    assert body["tokens_saved_estimated_total"] == 0
    assert body["tokens_saved_estimated_per_call"] == 0


# ---------------------------------------------------------------------------
# Calculation — baseline formula + rollup wiring
# ---------------------------------------------------------------------------


def test_calculation_uses_estimated_baseline() -> None:
    """``_estimate_tokens_saved`` MUST apply the spec formula.

    Asserts three branches of the contract:
      * baseline = ``int(question_chars / 2.5) * 5``
      * subtract response tokens = ``int(response_chars / 2.5)``
      * clamp at 0 when the response substrate is larger than baseline
    """
    from jpintel_mcp.api.usage import _estimate_tokens, _estimate_tokens_saved

    # 100 ASCII chars / 2.5 = 40 question tokens; baseline = 40 * 5 = 200.
    question = "a" * 100
    response_short = "x" * 25  # 10 response tokens — saved = 200 - 10 = 190.
    saved = _estimate_tokens_saved(question, response_short)
    assert _estimate_tokens(question) == 40
    assert _estimate_tokens(response_short) == 10
    assert saved == 200 - 10

    # Degenerate "tiny question, huge bundle" must clamp at 0 (never negative).
    response_huge = "x" * 100_000
    assert _estimate_tokens_saved("hi", response_huge) == 0

    # No question = no baseline = 0 saved (cron-job case).
    assert _estimate_tokens_saved(None, response_short) == 0
    assert _estimate_tokens_saved("", response_short) == 0

    # Dict response (jpcite envelope) is JSON-serialised before counting.
    saved_dict = _estimate_tokens_saved(question, {"data": "short"})
    # The dict serialises to ~16 chars → ~6 tokens; saved ≈ 200 - 6 = 194.
    # We assert a tight lower-bound + upper-bound rather than equality so a
    # later json.dumps formatting tweak (separators, key ordering) does not
    # break the test.
    assert 150 < saved_dict <= 200


def test_rollup_surfaces_seeded_row_in_usage_envelope(
    client: TestClient, seeded_db: Path, paid_key: str
) -> None:
    """A seeded usage_events row with tokens_saved_estimated MUST roll up
    into the /v1/usage envelope's ``tokens_saved_estimated_*`` fields.
    """
    from jpintel_mcp.api.deps import hash_api_key

    key_hash = hash_api_key(paid_key)
    c = sqlite3.connect(seeded_db)
    c.row_factory = sqlite3.Row
    try:
        # Seed two metered, successful rows for the current month.
        # The rollup only counts status<400 + non-NULL tokens_saved_estimated.
        for saved in (1000, 500):
            c.execute(
                "INSERT INTO usage_events("
                "  key_hash, endpoint, ts, status, metered, quantity,"
                "  tokens_saved_estimated"
                ") VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    key_hash,
                    "test.endpoint",
                    datetime.now(UTC).isoformat(),
                    200,
                    1,
                    1,
                    saved,
                ),
            )
        c.commit()
    finally:
        c.close()

    r = client.get("/v1/usage", headers={"X-API-Key": paid_key})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["tier"] == "paid"
    assert body["tokens_saved_estimated_total"] == 1500
    # 2 calls → mean = floor(1500 / 2) = 750.
    assert body["tokens_saved_estimated_per_call"] == 750


def test_log_usage_persists_tokens_saved_estimate(seeded_db: Path, paid_key: str) -> None:
    """``log_usage`` must write the metric, not only expose seeded rows."""
    from jpintel_mcp.api.deps import ApiContext, hash_api_key, log_usage
    from jpintel_mcp.api.usage import _estimate_tokens_saved

    key_hash = hash_api_key(paid_key)
    params = {"q": "a" * 100}
    response_body = {"results": ["x" * 25]}
    expected = _estimate_tokens_saved(params, response_body)
    assert expected > 0

    c = sqlite3.connect(seeded_db)
    c.row_factory = sqlite3.Row
    try:
        log_usage(
            c,
            ApiContext(key_hash=key_hash, tier="paid", customer_id="cus_test_paid"),
            "programs.search",
            params=params,
            response_body=response_body,
        )
        c.commit()
        row = c.execute(
            "SELECT tokens_saved_estimated FROM usage_events "
            "WHERE key_hash = ? AND endpoint = ? "
            "ORDER BY id DESC LIMIT 1",
            (key_hash, "programs.search"),
        ).fetchone()
    finally:
        c.close()

    assert row is not None
    assert row[0] == expected
