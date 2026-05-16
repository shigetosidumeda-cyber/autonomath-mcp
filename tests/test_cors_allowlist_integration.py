"""CORS allowlist integration test enforcing the CLAUDE.md gotcha.

CLAUDE.md "Common gotchas":

> **CORS allowlist must include jpcite.com apex AND www.**
> ``JPINTEL_CORS_ORIGINS`` (Fly secret + ``config.py`` default) must list
> ``https://jpcite.com``, ``https://www.jpcite.com``, ``https://api.jpcite.com``
> at minimum (plus the legacy ``zeimu-kaikei.ai`` apex+www and
> ``autonomath.ai`` apex+www until those brands are fully retired).
> ``OriginEnforcementMiddleware`` 403s any unlisted origin **before** the
> route handler runs.

These tests use the live ``client`` fixture (no mocks — the real
``OriginEnforcementMiddleware`` is mounted on ``create_app()``) and rely on
the ``settings.cors_origins`` default value, not a monkeypatched override.
The point of the suite is to lock the **default** allowlist so a future
edit that drops jpcite apex/www or removes the legacy bridge would fail
these tests before deploy. Per the launch persona walk on 2026-04-29, the
production Fly secret was once set to the autonomath.ai brand only, and
every browser-side POST returned 403 ``origin_not_allowed`` — this file
exists so that regression can never silently re-land.

We probe ``GET /v1/meta`` (cheap, idempotent, no auth) — the assertion is
``status_code != 403`` for allowed origins (the handler itself may answer
200/404/etc., but we want to prove the middleware did **not** short-circuit
with the ``origin_not_allowed`` envelope). Disallowed origins are asserted
to be exactly 403 + ``error == "origin_not_allowed"``.
"""

from __future__ import annotations

import pytest

# Origins that must always be in the default allowlist per CLAUDE.md.
_JPCITE_CANONICAL = (
    "https://jpcite.com",
    "https://www.jpcite.com",
    "https://api.jpcite.com",
)

# Legacy bridge origins retained until those brands are fully retired.
_LEGACY_BRIDGE = (
    "https://zeimu-kaikei.ai",
    "https://autonomath.ai",
)


@pytest.mark.parametrize("origin", _JPCITE_CANONICAL)
def test_jpcite_canonical_origin_allowed(client, origin):
    """jpcite apex + www + api MUST all pass the OriginEnforcementMiddleware.

    Regression guard: the 2026-04-29 launch persona walk caught a Fly
    secret set to the autonomath.ai brand only, and the browser-side
    prescreen / saved searches / webhooks dashboard / audit log all
    broke simultaneously with 403 ``origin_not_allowed``. This test
    locks the apex + www + api triple into the default config.
    """
    r = client.get("/v1/meta", headers={"Origin": origin})
    assert r.status_code != 403, (
        f"jpcite canonical origin {origin!r} was 403'd by the CORS gate "
        f"(default allowlist regression): {r.text[:200]}"
    )


def test_unknown_origin_returns_403_origin_not_allowed(client):
    """A random attacker origin MUST be short-circuited with 403 + envelope.

    The middleware contract is: unlisted Origin -> JSONResponse 403 with
    ``{"error": "origin_not_allowed", ...}`` BEFORE the route handler
    runs. Anything else (200, silent allow, 500) is a regression.
    """
    r = client.get(
        "/v1/meta",
        headers={"Origin": "https://attacker.example.com"},
    )
    assert r.status_code == 403, (
        f"unlisted attacker origin not blocked; expected 403 got {r.status_code}: {r.text[:200]}"
    )
    body = r.json()
    assert body.get("error") == "origin_not_allowed", (
        f"403 envelope shape changed; expected error='origin_not_allowed', got {body!r}"
    )


@pytest.mark.parametrize("apex", _LEGACY_BRIDGE)
def test_legacy_bridge_origin_allowed(client, apex):
    """Legacy zeimu-kaikei.ai + autonomath.ai apex MUST stay allowed.

    Per CLAUDE.md the legacy brands are bridged until fully retired, so
    a 301 redirect from the legacy apex onto jpcite.com is in flight and
    customer bookmarks / external links continue to land on the legacy
    apex during the SEO authority transfer window. Removing either from
    the default allowlist would 403 those landings.
    """
    r = client.get("/v1/meta", headers={"Origin": apex})
    assert r.status_code != 403, (
        f"legacy bridge origin {apex!r} was 403'd by the CORS gate "
        f"(brand-retirement regression): {r.text[:200]}"
    )


def test_options_preflight_unknown_origin_blocked(client):
    """OPTIONS preflight from an unlisted origin MUST also 403.

    Returning 200/204 to a preflight from an unlisted origin would let
    the browser proceed with the subsequent fetch, defeating the entire
    purpose of running OriginEnforcementMiddleware *before* the router.
    """
    r = client.options(
        "/v1/meta",
        headers={
            "Origin": "https://attacker.example.com",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert r.status_code == 403, (
        f"OPTIONS preflight from unlisted Origin not blocked; got {r.status_code}: {r.text[:200]}"
    )
    body = r.json()
    assert body.get("error") == "origin_not_allowed"
