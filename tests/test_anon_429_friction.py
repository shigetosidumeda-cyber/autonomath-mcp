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
    # On the 200 path the header points at /upgrade.html — the plain
    # conversion landing that explains the 50 req/月 cap and routes to
    # pricing. /go (device-flow activation) requires a user_code that an
    # anon caller doesn't have, so non-429 anon callers also land on
    # /upgrade.html (per /go/upgrade fix). The 429 envelope adds ?from=429
    # to the same URL for funnel-source attribution.
    assert "zeimu-kaikei.ai/upgrade.html" in upgrade


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

    # Body fields (S3 additions). The 429 envelope points at the dedicated
    # /upgrade.html landing — NOT /go (which is the device-flow page that
    # requires a user_code). See site/upgrade.html docstring.
    assert "upgrade_url" in body, f"missing upgrade_url; body keys={list(body)}"
    assert body["upgrade_url"].startswith("https://zeimu-kaikei.ai/upgrade.html")
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
        "https://zeimu-kaikei.ai/upgrade.html"
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


def test_soft_warning_body_injection_at_80pct(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CRO Fix 5a (2026-04-29): in-response upgrade_hint when remaining<=10.

    Many MCP hosts and curl scripts surface the response body to the
    user but swallow the X-Anon-Quota-Remaining header. So in addition
    to the headers we inject ``_meta.upgrade_hint`` into the JSON body
    when the caller is in the last 20% of their monthly runway.

    With ``anon_rate_limit_per_month=12``, the threshold is hit on the
    third call (remaining=12-3=9 <= 10). The first two calls (remaining
    11, 10) — note: 12-1=11 above threshold, 12-2=10 at threshold —
    must NOT carry the hint, and the third (remaining=9) MUST.
    """
    from jpintel_mcp.config import settings

    # 12 / month → first call remaining=11 (above threshold, no hint),
    # second call remaining=10 (at threshold, hint included), third call
    # remaining=9 (below threshold, hint included). The middleware fires
    # at remaining <= 10.
    monkeypatch.setattr(settings, "anon_rate_limit_per_month", 12)

    ip = "198.51.100.150"

    # Call 1 — remaining 11, no hint.
    r1 = client.get("/meta", headers={"x-forwarded-for": ip})
    assert r1.status_code == 200, r1.text
    assert r1.headers.get("X-Anon-Quota-Remaining") == "11"
    body1 = r1.json()
    assert (
        not isinstance(body1.get("_meta"), dict)
        or "upgrade_hint" not in body1.get("_meta", {})
    ), f"call 1 (remaining 11) should NOT carry upgrade_hint; body={body1}"

    # Call 2 — remaining 10, hint MUST be present.
    r2 = client.get("/meta", headers={"x-forwarded-for": ip})
    assert r2.status_code == 200, r2.text
    assert r2.headers.get("X-Anon-Quota-Remaining") == "10"
    body2 = r2.json()
    assert isinstance(body2.get("_meta"), dict), (
        f"call 2 (remaining 10) missing _meta; body keys={list(body2)}"
    )
    hint2 = body2["_meta"].get("upgrade_hint")
    assert isinstance(hint2, str) and hint2, (
        f"call 2 missing upgrade_hint string; _meta={body2['_meta']}"
    )
    assert "残 10 req" in hint2, f"hint missing remaining count; hint={hint2!r}"
    assert "zeimu-kaikei.ai/upgrade" in hint2, (
        f"hint missing upgrade URL; hint={hint2!r}"
    )
    assert "JST" in hint2 and "reset" in hint2, (
        f"hint missing JST reset cue; hint={hint2!r}"
    )

    # Call 3 — remaining 9, hint still present + count updated.
    r3 = client.get("/meta", headers={"x-forwarded-for": ip})
    assert r3.status_code == 200, r3.text
    assert r3.headers.get("X-Anon-Quota-Remaining") == "9"
    body3 = r3.json()
    hint3 = body3.get("_meta", {}).get("upgrade_hint")
    assert hint3 and "残 9 req" in hint3, (
        f"call 3 hint should reflect new remaining; hint={hint3!r}"
    )

    # Content-Length must match the rewritten body — TestClient asserts
    # this implicitly when r3.json() succeeds, but check the header is
    # at least a positive integer (proxy for "we did update it after
    # injecting").
    cl = r3.headers.get("content-length")
    assert cl is not None and int(cl) == len(r3.content), (
        f"content-length mismatch after injection: header={cl}, body={len(r3.content)}"
    )


def test_soft_warning_skipped_when_above_threshold(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Below the 80% threshold the headers are enough — no body mutation.

    With a generous quota (50/月 default) and one call, remaining=49 is
    well above the 10-call threshold, so the body must come back
    untouched.
    """
    from jpintel_mcp.config import settings

    monkeypatch.setattr(settings, "anon_rate_limit_per_month", 50)

    r = client.get("/meta", headers={"x-forwarded-for": "198.51.100.151"})
    assert r.status_code == 200, r.text
    assert r.headers.get("X-Anon-Quota-Remaining") == "49"

    body = r.json()
    # _meta may not exist at all, OR it may exist for unrelated reasons,
    # but it must NOT carry our upgrade_hint key.
    if isinstance(body.get("_meta"), dict):
        assert "upgrade_hint" not in body["_meta"], (
            f"upgrade_hint leaked at remaining=49; _meta={body['_meta']}"
        )


def test_soft_warning_body_omitted_for_authed(
    client: TestClient,
    seeded_db: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Authenticated callers never get the body-level upgrade hint —
    they already converted, the hint would be pure noise.

    Exhausts the anon bucket (small quota) but uses an API key, so the
    soft-warning code path must not fire.
    """
    from jpintel_mcp.billing.keys import issue_key
    from jpintel_mcp.config import settings

    monkeypatch.setattr(settings, "anon_rate_limit_per_month", 5)

    c = sqlite3.connect(seeded_db)
    c.row_factory = sqlite3.Row
    raw = issue_key(
        c,
        customer_id="cus_soft_warning_test",
        tier="paid",
        stripe_subscription_id="sub_soft_warning_test",
    )
    c.commit()
    c.close()

    r = client.get(
        "/meta",
        headers={
            "x-forwarded-for": "198.51.100.152",
            "X-API-Key": raw,
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    if isinstance(body.get("_meta"), dict):
        assert "upgrade_hint" not in body["_meta"], (
            f"authed response leaked upgrade_hint; _meta={body['_meta']}"
        )
