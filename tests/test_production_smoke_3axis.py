"""3-axis production smoke (CORS / API key / anon limit).

Single-file consolidation of the launch gate verifying the three
authorization axes that gate every public surface:

  Axis 1 — CORS / origin enforcement
    * jpcite.com apex/www/api          → 200 (current brand)
    * zeimu-kaikei.ai apex/www/api     → 200 (legacy brand, still live)
    * autonomath.ai apex/www           → 200 (legacy brand, still live)
    * evil.example.com                 → 403 origin_not_allowed
    * _MUST_INCLUDE survives a secret that only lists localhost or only
      lists a legacy brand (W1-18, W4-2 hardcoded fallback regression).

  Axis 2 — API key auth (X-API-Key + Bearer)
    * X-API-Key: am_xxx (valid)        → 200
    * Authorization: Bearer am_xxx     → 200
    * X-API-Key: am_bogus_not_real     → 401
    * X-API-Key on a revoked key       → 401

  Axis 3 — anon per-IP day quota
    * Anon req 1..3                    → 200
    * Anon req 4 (over quota)          → 429 + reset_at
    * DB error on _try_increment       → 429 fail-CLOSED with
      reason='rate_limit_unavailable' (W1-2 contract).

Each axis is asserted against the real FastAPI app via TestClient — no
mocks of the database layer (the only patch is `_try_increment` for the
fail-closed case, which we cannot exercise without inducing a DB error).
"""

from __future__ import annotations

import sqlite3
from importlib import reload
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

    from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Axis 1 — CORS / origin enforcement
# ---------------------------------------------------------------------------

CURRENT_BRAND_ORIGINS = (
    "https://jpcite.com",
    "https://www.jpcite.com",
    "https://api.jpcite.com",
)
LEGACY_BRAND_ORIGINS = (
    "https://zeimu-kaikei.ai",
    "https://www.zeimu-kaikei.ai",
    "https://api.zeimu-kaikei.ai",
    "https://autonomath.ai",
    "https://www.autonomath.ai",
)


@pytest.mark.parametrize("origin", CURRENT_BRAND_ORIGINS + LEGACY_BRAND_ORIGINS)
def test_axis1_cors_allowed_origin_returns_200(client: TestClient, origin: str) -> None:
    """Apex/www/api for jpcite.com (current) AND zeimu-kaikei.ai +
    autonomath.ai (legacy) all reach the route handler."""
    r = client.get("/meta", headers={"origin": origin})
    assert r.status_code == 200, f"allowed origin {origin} returned {r.status_code}: {r.text[:200]}"


def test_axis1_cors_unknown_origin_returns_403_origin_not_allowed(
    client: TestClient,
) -> None:
    """An origin not on the allow-list short-circuits with 403."""
    r = client.get("/meta", headers={"origin": "https://evil.example.com"})
    assert r.status_code == 403
    body = r.json()
    assert body.get("error") == "origin_not_allowed"
    assert body.get("origin") == "https://evil.example.com"


def test_axis1_cors_must_include_survives_localhost_only_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """W1-18: secret only lists localhost → jpcite.com apex/www/api STAY
    on the allow-list (hardcoded _MUST_INCLUDE fallback)."""
    monkeypatch.setenv("JPINTEL_CORS_ORIGINS", "http://localhost:3000")
    import jpintel_mcp.config as config_module

    reload(config_module)
    import jpintel_mcp.api.middleware.origin_enforcement as oe

    reload(oe)
    allowed = oe._allowed_origins()
    for origin in CURRENT_BRAND_ORIGINS:
        assert origin in allowed, f"{origin} dropped when secret=localhost"
    assert "http://localhost:3000" in allowed


def test_axis1_cors_must_include_survives_legacy_brand_only_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """W4-2: 2026-04-29 misconfig (secret = autonomath.ai only) must NOT
    drop jpcite.com apex/www/api — the hardcoded fallback rescues it."""
    monkeypatch.setenv(
        "JPINTEL_CORS_ORIGINS",
        "https://autonomath.ai,https://www.autonomath.ai",
    )
    import jpintel_mcp.config as config_module

    reload(config_module)
    import jpintel_mcp.api.middleware.origin_enforcement as oe

    reload(oe)
    allowed = oe._allowed_origins()
    for origin in CURRENT_BRAND_ORIGINS:
        assert origin in allowed, f"{origin} dropped when secret only lists autonomath.ai"
    assert "https://autonomath.ai" in allowed


# ---------------------------------------------------------------------------
# Axis 2 — API key auth
# ---------------------------------------------------------------------------


def _issue_paid_key(seeded_db: Path, customer: str = "cus_smoke3axis") -> str:
    from jpintel_mcp.billing.keys import issue_key

    c = sqlite3.connect(seeded_db)
    c.row_factory = sqlite3.Row
    import uuid

    sub_id = f"sub_smoke_{uuid.uuid4().hex[:8]}"
    raw = issue_key(c, customer_id=customer, tier="paid", stripe_subscription_id=sub_id)
    c.commit()
    c.close()
    return raw


def test_axis2_apikey_x_api_key_header_returns_200(client: TestClient, seeded_db: Path) -> None:
    """X-API-Key: jc_xxx is the canonical header form."""
    raw = _issue_paid_key(seeded_db)
    assert raw.startswith("jc_"), f"key prefix wrong: {raw[:8]}"

    r = client.get("/meta", headers={"X-API-Key": raw})
    assert r.status_code == 200, r.text


def test_axis2_apikey_bearer_authorization_header_returns_200(
    client: TestClient, seeded_db: Path
) -> None:
    """Authorization: Bearer jc_xxx is also accepted (deps.require_key)."""
    raw = _issue_paid_key(seeded_db, customer="cus_smoke_bearer")

    r = client.get("/meta", headers={"Authorization": f"Bearer {raw}"})
    assert r.status_code == 200, r.text


def test_axis2_apikey_invalid_key_returns_401(client: TestClient) -> None:
    """Unknown key (no row in api_keys) → 401, never falls through to anon."""
    r = client.get(
        "/v1/me",
        headers={"X-API-Key": "am_bogus_not_a_real_key_at_all"},
    )
    assert r.status_code == 401


def test_axis2_apikey_revoked_key_returns_401(client: TestClient, seeded_db: Path) -> None:
    """A key whose api_keys.revoked_at is set → 401 with revoked detail."""
    from jpintel_mcp.api.deps import hash_api_key
    from jpintel_mcp.billing.keys import revoke_key

    raw = _issue_paid_key(seeded_db, customer="cus_smoke_revoked")
    # Sanity: works pre-revoke.
    assert client.get("/v1/me", headers={"X-API-Key": raw}).status_code == 200

    c = sqlite3.connect(seeded_db)
    revoke_key(c, hash_api_key(raw))
    c.commit()
    c.close()

    r = client.get("/v1/me", headers={"X-API-Key": raw})
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# Axis 3 — anon per-IP day quota
# ---------------------------------------------------------------------------


def test_axis3_anon_under_quota_returns_200(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Anon req 1..3 (limit=3 default) all succeed."""
    from jpintel_mcp.config import settings

    monkeypatch.setattr(settings, "anon_rate_limit_per_day", 3)
    ip = "203.0.113.50"
    for i in range(3):
        r = client.get("/meta", headers={"x-forwarded-for": ip})
        assert r.status_code == 200, f"req #{i + 1}/3 failed: {r.text[:200]}"


def test_axis3_anon_over_quota_returns_429_with_reset_at(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Anon req 4 (limit=3) → 429 with reset_at_jst + resets_at + Retry-After."""
    from jpintel_mcp.config import settings

    monkeypatch.setattr(settings, "anon_rate_limit_per_day", 3)
    ip = "203.0.113.51"
    for _ in range(3):
        assert client.get("/meta", headers={"x-forwarded-for": ip}).status_code == 200

    r = client.get("/meta", headers={"x-forwarded-for": ip})
    assert r.status_code == 429
    body = r.json()
    assert body.get("code") == "rate_limit_exceeded"
    assert body.get("reason") == "rate_limit_exceeded"
    assert body.get("limit") == 3
    # Both fields must be present and ISO-prefixed.
    assert body["resets_at"].startswith(("20", "21"))
    assert body["reset_at_jst"].startswith(("20", "21"))
    retry_after = r.headers.get("Retry-After")
    assert retry_after is not None and int(retry_after) > 0


def test_axis3_anon_db_error_fails_closed_429(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """W1-2: _try_increment DB error → 429 reason=rate_limit_unavailable
    (NOT 200, NOT 500). Pre-2026-05-04 this failed OPEN — pin closed."""
    import jpintel_mcp.api.anon_limit as anon

    def _raise_locked(*_args, **_kwargs):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(anon, "_try_increment", _raise_locked)

    r = client.get("/meta", headers={"x-forwarded-for": "203.0.113.52"})
    assert r.status_code == 429, f"expected fail-CLOSED 429, got {r.status_code}: {r.text[:200]}"
    body = r.json()
    assert body.get("reason") == "rate_limit_unavailable"
    assert "limit" in body
    assert "resets_at" in body
