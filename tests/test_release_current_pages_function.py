from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
FUNCTION_PATH = REPO_ROOT / "functions" / "release" / "[[path]].ts"
ROUTES_PATH = REPO_ROOT / "site" / "_routes.json"
HEADERS_PATH = REPO_ROOT / "site" / "_headers"


def test_release_current_pages_function_is_pointer_guarded() -> None:
    source = FUNCTION_PATH.read_text(encoding="utf-8")

    assert 'ACTIVE_POINTER_PATH = "/releases/current/runtime_pointer.json"' in source
    assert "live_aws_commands_allowed !== false" in source
    assert "aws_runtime_dependency_allowed !== false" in source
    assert "capsule_pointer_invalid" in source
    assert 'ACTIVE_CAPSULE_ID = "rc1-p0-bootstrap-2026-05-15"' in source
    assert 'ACTIVE_CAPSULE_DIR = "rc1-p0-bootstrap"' in source
    assert "capsuleId !== ACTIVE_CAPSULE_ID" in source
    assert "`/releases/${ACTIVE_CAPSULE_DIR}/release_capsule_manifest.json`" in source
    assert 'request.method !== "GET" && request.method !== "HEAD"' in source


def test_release_current_aliases_cover_p0_agent_assets() -> None:
    source = FUNCTION_PATH.read_text(encoding="utf-8")

    for alias in (
        "/release/current/capsule_manifest.json",
        "/release/current/capability_matrix.public.json",
        "/release/current/agent_surface/p0_facade.json",
        "/release/current/preflight_scorecard.json",
        "/release/current/noop_aws_command_plan.json",
        "/release/current/zero_aws_posture_manifest.json",
    ):
        assert alias in source


def test_release_pages_route_and_headers_are_registered() -> None:
    routes = json.loads(ROUTES_PATH.read_text(encoding="utf-8"))
    headers = HEADERS_PATH.read_text(encoding="utf-8")

    assert "/release/*" in routes["include"]
    assert "/.well-known/jpcite-release.json" in headers
    assert "/release/current/*" in headers
    assert "/release/rc1-p0-bootstrap/*" in headers
    assert "/releases/current/*" in headers
    assert "/releases/rc1-p0-bootstrap/*" in headers
    jpcite_release_headers = headers[
        headers.index("/.well-known/jpcite-release.json") : headers.index("/llms-meta.json")
    ]
    assert "Content-Type: application/json; charset=utf-8" in jpcite_release_headers
    assert "Access-Control-Allow-Origin: *" in jpcite_release_headers
    assert "Cross-Origin-Resource-Policy: cross-origin" in jpcite_release_headers
    assert "CDN-Cache-Control: public, max-age=600" in jpcite_release_headers
    immutable_release_headers = headers[
        headers.index("/release/rc1-p0-bootstrap/*") : headers.index("/releases/current/*")
    ]
    assert "CDN-Cache-Control: public, max-age=31536000" in immutable_release_headers
