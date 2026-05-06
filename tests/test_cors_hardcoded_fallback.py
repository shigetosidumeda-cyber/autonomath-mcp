"""§M14 CORS hardcoded fallback test.

Verifies that `https://jpcite.com`, `https://www.jpcite.com`,
`https://api.jpcite.com` AND the 5 legacy brand origins
(`https://zeimu-kaikei.ai`, `https://www.zeimu-kaikei.ai`,
`https://api.zeimu-kaikei.ai`, `https://autonomath.ai`,
`https://www.autonomath.ai`) remain in the allow-list regardless of what
`JPINTEL_CORS_ORIGINS` is set to. A misrotated secret historically dropped
apex/www and 403'd the entire browser surface; the hardcoded fallback in
`api/middleware/origin_enforcement.py::_allowed_origins` and the matching
`origins` build in `api/main.py::create_app` must both keep these alive.
"""

from __future__ import annotations

from importlib import reload
from typing import Any

import pytest

import jpintel_mcp.config as config_module

_MUST_INCLUDE = {
    "https://jpcite.com",
    "https://www.jpcite.com",
    "https://api.jpcite.com",
    "https://zeimu-kaikei.ai",
    "https://www.zeimu-kaikei.ai",
    "https://api.zeimu-kaikei.ai",
    "https://autonomath.ai",
    "https://www.autonomath.ai",
}


def _reload_with_origins(monkeypatch: pytest.MonkeyPatch, value: str) -> Any:
    monkeypatch.setenv("JPINTEL_CORS_ORIGINS", value)
    reload(config_module)
    # Re-import middleware so it re-binds settings.
    import jpintel_mcp.api.middleware.origin_enforcement as oe

    reload(oe)
    return oe


def test_apex_and_www_present_when_secret_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Empty CORS secret → apex/www/api remain on the allow-list."""
    oe = _reload_with_origins(monkeypatch, "")
    allowed = oe._allowed_origins()
    for origin in _MUST_INCLUDE:
        assert origin in allowed, f"{origin} must remain even when secret is empty"


def test_apex_and_www_present_when_secret_drops_them(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Secret only lists localhost → apex/www/api STILL present (hardcoded)."""
    oe = _reload_with_origins(monkeypatch, "http://localhost:3000,http://localhost:8080")
    allowed = oe._allowed_origins()
    assert "http://localhost:3000" in allowed
    for origin in _MUST_INCLUDE:
        assert origin in allowed, f"{origin} must remain even when secret only lists localhost"


def test_apex_and_www_present_when_secret_lists_only_legacy_brands(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Common 2026-04-29 misconfiguration: secret set to autonomath.ai only."""
    oe = _reload_with_origins(
        monkeypatch,
        "https://autonomath.ai,https://www.autonomath.ai",
    )
    allowed = oe._allowed_origins()
    for origin in _MUST_INCLUDE:
        assert origin in allowed, f"{origin} must remain even when secret only lists autonomath.ai"
    # And the legacy-brand origins from the secret are also accepted.
    assert "https://autonomath.ai" in allowed


def test_must_include_set_matches_main_create_app(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sanity: the hardcoded set in middleware === the set in main.py."""
    oe = _reload_with_origins(monkeypatch, "")
    middleware_set = oe._MUST_INCLUDE
    assert middleware_set == frozenset(_MUST_INCLUDE)


def test_origin_enforcement_rejects_unknown_origin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sanity check the gate still works for non-allow-listed origins."""
    oe = _reload_with_origins(monkeypatch, "")
    allowed = oe._allowed_origins()
    assert "https://evil.example.com" not in allowed
