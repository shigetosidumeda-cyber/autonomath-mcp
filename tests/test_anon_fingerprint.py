"""Anonymous quota fingerprint hardening tests.

The advertised anonymous cap is per origin IP. Behavioural fingerprint
fields such as User-Agent and Accept-Language are still useful telemetry,
but they are client-controlled and must not define the quota bucket.
"""

from __future__ import annotations

import importlib
import sqlite3
import sys
from typing import TYPE_CHECKING

import pytest  # noqa: TC002 (used at runtime for monkeypatch fixture type)

if TYPE_CHECKING:
    from pathlib import Path

    from fastapi.testclient import TestClient


def _anon_module():
    mod = sys.modules.get("jpintel_mcp.api.anon_limit")
    if mod is None:
        mod = importlib.import_module("jpintel_mcp.api.anon_limit")
    return mod


def _hash_for(ip: str) -> str:
    """Compute the authoritative per-IP digest the dep writes."""
    anon = _anon_module()
    return anon.hash_ip(ip)


def _row_count(db: Path, ip_hash: str, day_bucket: str) -> int:
    c = sqlite3.connect(db)
    try:
        row = c.execute(
            "SELECT call_count FROM anon_rate_limit WHERE ip_hash = ? AND date = ?",
            (ip_hash, day_bucket),
        ).fetchone()
    finally:
        c.close()
    return 0 if row is None else int(row[0])


def test_same_ip_different_accept_language_and_user_agent_share_bucket(
    client: TestClient,
    seeded_db: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Header rotation from one origin IP must not mint fresh anon quota."""
    from jpintel_mcp.config import settings

    monkeypatch.setattr(settings, "anon_rate_limit_per_day", 2)
    ip = "203.0.113.10"

    r1 = client.get(
        "/meta",
        headers={
            "fly-client-ip": ip,
            "user-agent": "Cursor/1.2.3 (electron; node)",
            "accept-language": "ja",
        },
    )
    r2 = client.get(
        "/meta",
        headers={
            "fly-client-ip": ip,
            "user-agent": "ChatGPT-User/1.0",
            "accept-language": "en-US,en;q=0.8",
        },
    )
    r3 = client.get(
        "/meta",
        headers={
            "fly-client-ip": ip,
            "user-agent": "curl/8.4.0",
            "accept-language": "fr",
        },
    )

    assert r1.status_code == 200, r1.text
    assert r2.status_code == 200, r2.text
    assert r3.status_code == 429, r3.text

    anon = _anon_module()
    day_bucket = anon._jst_day_bucket()
    assert _row_count(seeded_db, _hash_for(ip), day_bucket) == 3


def test_hash_ip_ignores_request_fingerprint_metadata() -> None:
    """Passing a request must not change the quota hash."""
    from starlette.datastructures import Headers
    from starlette.requests import Request

    anon = _anon_module()
    ip = "203.0.113.44"

    def req(headers: dict[str, str]) -> Request:
        return Request(
            {
                "type": "http",
                "method": "GET",
                "path": "/meta",
                "headers": Headers(headers).raw,
                "http_version": "1.1",
            }
        )

    request_a = req(
        {
            "user-agent": "Cursor/1.2.3 (electron; node)",
            "accept-language": "ja",
        }
    )
    request_b = req(
        {
            "user-agent": "curl/8.4.0",
            "accept-language": "en-US,en;q=0.8",
        }
    )

    assert anon._fingerprint_string(request_a) != anon._fingerprint_string(request_b)
    assert anon.hash_ip(ip, request_a) == anon.hash_ip(ip, request_b) == anon.hash_ip(ip)

    assert anon._fingerprint_metadata(request_a) == {
        "ua_class": "cursor",
        "accept_language": "ja",
        "http_version": "h1.1",
        "ja3": "?",
        "fingerprint": "cursor|ja|h1.1|?",
    }


def test_ua_version_rotation_does_not_reset_bucket(
    client: TestClient,
    seeded_db: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The naive "rotate UA between requests" bypass attempt must fail."""
    from jpintel_mcp.config import settings

    monkeypatch.setattr(settings, "anon_rate_limit_per_day", 3)

    ip = "203.0.113.20"

    r1 = client.get(
        "/meta",
        headers={
            "fly-client-ip": ip,
            "user-agent": "Cursor/1.2.3 (electron; node)",
            "accept-language": "ja",
        },
    )
    r2 = client.get(
        "/meta",
        headers={
            "fly-client-ip": ip,
            "user-agent": "Cursor/1.2.4 (electron; node)",
            "accept-language": "ja",
        },
    )
    assert r1.status_code == 200, r1.text
    assert r2.status_code == 200, r2.text

    anon = _anon_module()
    day_bucket = anon._jst_day_bucket()
    assert _row_count(seeded_db, _hash_for(ip), day_bucket) == 2

    assert anon._classify_user_agent("Cursor/1.2.3 (electron; node)") == "cursor"
    assert anon._classify_user_agent("Cursor/1.2.4 (electron; node)") == "cursor"
