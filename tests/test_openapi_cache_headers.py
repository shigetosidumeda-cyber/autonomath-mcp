"""Cache-Control + /v1/mcp-server.json regression tests (R8 perf, 2026-05-07).

Locks two perf-baseline fixes in place so a future refactor cannot silently
regress them:

* The three deploy-stamp manifests (``/v1/openapi.json``,
  ``/v1/openapi.agent.json``, ``/v1/mcp-server.json``) carry
  ``Cache-Control: public, max-age=300, s-maxage=600`` so Cloudflare
  edges + browsers + SDK introspectors do not re-fetch a 539 KB blob
  on every page load.
* ``/v1/mcp-server.json`` answers 200 with the registry manifest body
  (the URL referenced by ``manifest_url`` in the file itself). Prior
  to this change R8_PERF_BASELINE_2026-05-07 reported a 404 for the
  same path.

Tests use the standard ``client`` fixture from ``conftest.py`` so the
seeded jpintel.db + autonomath.db wiring is identical to the rest of
the suite. No fan-out into Stripe / DB write paths — these are pure
read GETs.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from fastapi.testclient import TestClient
    from pytest import MonkeyPatch


_EXPECTED_CACHE_CONTROL = "public, max-age=300, s-maxage=600"
_STATIC_MANIFEST_PATHS = (
    "/v1/openapi.json",
    "/v1/openapi.agent.json",
    "/v1/mcp-server.json",
)


def test_static_manifests_carry_cache_control(client: TestClient) -> None:
    """Every deploy-stamp manifest emits the canonical Cache-Control value."""
    for path in _STATIC_MANIFEST_PATHS:
        response = client.get(path)
        assert response.status_code == 200, (
            f"{path} -> {response.status_code}: {response.text[:200]}"
        )
        cache_control = response.headers.get("Cache-Control")
        assert cache_control == _EXPECTED_CACHE_CONTROL, (
            f"{path} Cache-Control={cache_control!r} (expected {_EXPECTED_CACHE_CONTROL!r})"
        )


def test_mcp_server_manifest_returns_registry_payload(client: TestClient) -> None:
    """/v1/mcp-server.json serves the JSON registry manifest body."""
    response = client.get("/v1/mcp-server.json")
    assert response.status_code == 200, response.text
    body = response.json()
    # Sanity-check the canonical fields without pinning the version (which
    # bumps every release). `name` + `protocol` + `manifest_url` are stable
    # across the manifest's lifetime.
    assert body.get("name") == "autonomath-mcp"
    assert isinstance(body.get("protocol"), str)
    assert body["protocol"].startswith("mcp-")
    # The very URL we are serving from must round-trip in the body.
    assert "/mcp-server.json" in body.get("manifest_url", "")


def test_mcp_server_manifest_honors_runtime_path_override(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """Docker can place the registry manifest outside the Python package tree."""
    manifest_path = tmp_path / "mcp-server.json"
    manifest_path.write_text(
        json.dumps(
            {
                "name": "autonomath-mcp-runtime",
                "protocol": "mcp-2025-06-18",
                "manifest_url": "https://jpcite.com/mcp-server.json",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("MCP_SERVER_MANIFEST_PATH", str(manifest_path))

    response = client.get("/v1/mcp-server.json")

    assert response.status_code == 200, response.text
    assert response.json()["name"] == "autonomath-mcp-runtime"


def test_non_manifest_paths_do_not_get_cache_control_from_middleware(
    client: TestClient,
) -> None:
    """Confirm middleware path-match is exact (no false positives).

    /v1/meta is the closest neighbouring public path that should NOT
    pick up the static-manifest Cache-Control. Anonymous calls return
    a non-2xx (rate-limit / metadata envelope) on the seeded test
    client, but either way the response must not carry the manifest
    Cache-Control value.
    """
    response = client.get("/v1/meta")
    cache_control = response.headers.get("Cache-Control", "")
    assert cache_control != _EXPECTED_CACHE_CONTROL


def test_legacy_openapi_redirect_does_not_gain_cache_control(client: TestClient) -> None:
    """The 308 redirect at /openapi.json must not be cached as a manifest.

    Caching a 308 for 10 minutes would pin clients to the redirect even
    after we change the canonical URL. Path-match is intentionally on
    /v1/* prefixed paths only.
    """
    response = client.get("/openapi.json", follow_redirects=False)
    assert response.status_code in (301, 307, 308), response.status_code
    cache_control = response.headers.get("Cache-Control", "")
    assert cache_control != _EXPECTED_CACHE_CONTROL
