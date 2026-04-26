"""Anon → paid friction removal (S3, 2026-04-25).

Validates that:

1. Every successful **anonymous** response carries the three quota
   headers — ``X-Anon-Quota-Remaining``, ``X-Anon-Quota-Reset``,
   ``X-Anon-Upgrade-Url`` — so an LLM caller / human-in-the-loop sees
   the 50/月 runway and the upgrade entry point *before* the ceiling.

2. The 429 response body now carries ``upgrade_url`` + ``cta_text_ja``
   + ``cta_text_en`` (no UI on our side; copy is shipped in JSON).

3. **Authenticated** responses do NOT carry the anon headers — those
   are pure friction-removal for the free tier.

Conftest already wipes the anon_rate_limit table between tests via
``_reset_anon_rate_limit`` (autouse), so each case starts at 0 calls.
"""
from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    import pytest
    from fastapi.testclient import TestClient


def test_200_anon_response_carries_quota_headers(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Anon GET /meta returns 200 + the three S3 friction headers.

    Asserts:
      - X-Anon-Quota-Remaining is the post-call remaining count (limit - 1).
      - X-Anon-Quota-Reset starts with an ISO year prefix.
      - X-Anon-Upgrade-Url points at /go (the conversion landing).
    """
    from jpintel_mcp.config import settings

    # Pin a small limit so remaining=4 is easy to assert without 50 hops.
    monkeypatch.setattr(settings, "anon_rate_limit_per_month", 5)

    r = client.get("/meta", headers={"x-forwarded-for": "198.51.100.101"})
    assert r.status_code == 200, r.text

    remaining = r.headers.get("X-Anon-Quota-Remaining")
    reset = r.headers.get("X-Anon-Quota-Reset")
    upgrade = r.headers.get("X-Anon-Upgrade-Url")

    assert remaining is not None, "missing X-Anon-Quota-Remaining"
    assert remaining == "4", f"expected 4 (5 - 1 just spent), got {remaining}"

    assert reset is not None, "missing X-Anon-Quota-Reset"
    # ISO year prefix — accepts either timezone or naive ISO.
    assert reset.startswith(("20", "21")), f"reset not ISO-ish: {reset}"

    assert upgrade is not None, "missing X-Anon-Upgrade-Url"
    assert "autonomath.ai/go" in upgrade


def test_429_body_includes_upgrade_url_and_bilingual_cta(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When anon hits the ceiling, the 429 body MUST surface the
    conversion path: upgrade_url + cta_text_ja + cta_text_en.

    Headers on the 429 are also asserted (X-Anon-Quota-Remaining=0,
    X-Anon-Upgrade-Url, X-Anon-Quota-Reset) so HTTP-only clients
    (curl scripts, monitoring) see the same hint.
    """
    from jpintel_mcp.config import settings

    monkeypatch.setattr(settings, "anon_rate_limit_per_month", 2)

    ip = "198.51.100.102"
    # Burn the bucket.
    for _ in range(2):
        r = client.get("/meta", headers={"x-forwarded-for": ip})
        assert r.status_code == 200

    # Next call -> 429 with friction-removal payload.
    r = client.get("/meta", headers={"x-forwarded-for": ip})
    assert r.status_code == 429
    body = r.json()

    # Body fields (S3 additions).
    assert "upgrade_url" in body, f"missing upgrade_url; body keys={list(body)}"
    assert body["upgrade_url"].startswith("https://autonomath.ai/go")
    assert "from=429" in body["upgrade_url"]

    assert body.get("cta_text_ja"), "missing cta_text_ja"
    assert body.get("cta_text_en"), "missing cta_text_en"
    # Sanity: JP CTA contains 制限/解除 cue, EN contains 'API key'.
    assert "API key" in body["cta_text_ja"] or "制限" in body["cta_text_ja"]
    assert "API key" in body["cta_text_en"]

    # Pre-existing 429 fields still present (back-compat).
    assert body.get("limit") == 2
    assert body.get("retry_after") and int(body["retry_after"]) > 0
    assert body.get("resets_at", "").startswith(("20", "21"))

    # Headers on 429 (parallel to the body).
    assert r.headers.get("X-Anon-Quota-Remaining") == "0"
    assert r.headers.get("X-Anon-Upgrade-Url", "").startswith(
        "https://autonomath.ai/go"
    )
    assert r.headers.get("X-Anon-Quota-Reset", "").startswith(("20", "21"))
    assert r.headers.get("Retry-After") is not None


def test_authenticated_response_omits_anon_headers(
    client: TestClient,
    seeded_db: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A request carrying X-API-Key must NOT receive the anon-quota
    headers. The S3 friction headers are pure conversion hints for the
    free tier — paid customers already converted, so emitting them on
    every authed response would be both noise and a leak of the anon
    bucket bookkeeping into authed observability.
    """
    from jpintel_mcp.billing.keys import issue_key
    from jpintel_mcp.config import settings

    # Even a tiny anon limit must not poison the authed path.
    monkeypatch.setattr(settings, "anon_rate_limit_per_month", 2)

    c = sqlite3.connect(seeded_db)
    c.row_factory = sqlite3.Row
    raw = issue_key(
        c,
        customer_id="cus_anon_friction_test",
        tier="paid",
        stripe_subscription_id="sub_anon_friction_test",
    )
    c.commit()
    c.close()

    r = client.get(
        "/meta",
        headers={
            "x-forwarded-for": "198.51.100.103",
            "X-API-Key": raw,
        },
    )
    assert r.status_code == 200, r.text

    # NONE of the anon-tier headers should appear on an authed response.
    assert "X-Anon-Quota-Remaining" not in r.headers, (
        f"authed response leaked anon header: {r.headers}"
    )
    assert "X-Anon-Quota-Reset" not in r.headers
    assert "X-Anon-Upgrade-Url" not in r.headers
