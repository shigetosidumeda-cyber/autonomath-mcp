from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
HEADERS_FILE = REPO_ROOT / "site" / "_headers"


def _headers_blocks() -> dict[str, dict[str, str]]:
    blocks: dict[str, dict[str, str]] = {}
    route: str | None = None

    for raw_line in HEADERS_FILE.read_text(encoding="utf-8").splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        if raw_line[0].isspace():
            assert route is not None, f"header without route: {raw_line!r}"
            name, sep, value = raw_line.strip().partition(":")
            assert sep == ":", f"malformed header line: {raw_line!r}"
            blocks.setdefault(route, {})[name] = value.strip()
            continue
        route = raw_line.strip()
        blocks.setdefault(route, {})

    return blocks


def test_global_static_security_headers_keep_baseline() -> None:
    headers = _headers_blocks().get("/*")

    assert headers is not None, "site/_headers must define the global /* block"
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["X-Frame-Options"] == "DENY"
    assert headers["Referrer-Policy"] == "strict-origin-when-cross-origin"

    hsts_directives = {
        directive.strip().lower() for directive in headers["Strict-Transport-Security"].split(";")
    }
    assert {"max-age=31536000", "includesubdomains", "preload"} <= hsts_directives

    csp = headers["Content-Security-Policy"]
    for directive in (
        "default-src 'self'",
        "frame-ancestors 'none'",
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'self'",
        "upgrade-insecure-requests",
    ):
        assert directive in csp

    permissions = headers["Permissions-Policy"]
    for feature in ("camera=()", "geolocation=()", "microphone=()", "payment=()"):
        assert feature in permissions

    assert headers["Cross-Origin-Opener-Policy"] == "same-origin"
    assert headers["Cross-Origin-Resource-Policy"] == "same-site"
    assert headers["X-Permitted-Cross-Domain-Policies"] == "none"
