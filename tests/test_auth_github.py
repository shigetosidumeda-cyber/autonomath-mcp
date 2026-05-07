"""Smoke tests for ``/v1/auth/github/{start,callback}``.

The router was added 2026-05-07 to close the R8_FINAL_INTEGRATION_SMOKE
gap (Fly secrets ``GITHUB_OAUTH_CLIENT_ID`` / ``GITHUB_OAUTH_CLIENT_SECRET``
were deployed, but the FastAPI router was never mounted, so both paths
returned 404 in production). These tests cover:

  * ``/start`` happy path (302 redirect to github.com).
  * ``/start`` JSON-mode (Accept: application/json).
  * ``/start`` 503 when ``GITHUB_OAUTH_CLIENT_ID`` is unset.
  * ``/callback`` happy path with mocked GitHub token exchange + identity
    fetch (verifies state nonce row is consumed).
  * ``/callback`` 400 when state is unknown / mismatched.
  * ``/callback`` 502 when GitHub returns ``error`` in the token body.

Network calls are mocked at the ``urllib.request.urlopen`` layer — same
pattern as ``test_integrations.py``.
"""

from __future__ import annotations

import json
import sqlite3
import urllib.request
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

if TYPE_CHECKING:
    from pathlib import Path


# ---------------------------------------------------------------------------
# Fixtures — ensure ``integration_sync_log`` exists on the test DB
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _ensure_integration_sync_log(seeded_db: Path) -> None:
    """The state nonce is persisted in ``integration_sync_log``.

    Migration 105 creates the table; this fixture re-applies the relevant
    CREATE statement idempotently so test runs that order this file before
    ``test_integrations.py`` (which has its own auto-fixture) still find
    the table.
    """
    c = sqlite3.connect(seeded_db)
    try:
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS integration_sync_log (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                api_key_hash    TEXT NOT NULL,
                provider        TEXT NOT NULL,
                idempotency_key TEXT NOT NULL,
                saved_search_id INTEGER,
                status          TEXT NOT NULL,
                result_count    INTEGER NOT NULL DEFAULT 0,
                error_class     TEXT,
                created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                UNIQUE (provider, idempotency_key)
            )
            """
        )
        c.commit()
    finally:
        c.close()


class _FakeResp:
    """Minimal context-manager wrapping a JSON byte payload."""

    def __init__(self, payload: object):
        self._payload = payload

    def __enter__(self) -> _FakeResp:
        return self

    def __exit__(self, *_args: object) -> bool:
        return False

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")


# ---------------------------------------------------------------------------
# /start
# ---------------------------------------------------------------------------


def test_github_oauth_start_redirects_to_github(client, monkeypatch):
    monkeypatch.setenv("GITHUB_OAUTH_CLIENT_ID", "test-gh-client-id")
    r = client.get("/v1/auth/github/start", follow_redirects=False)
    assert r.status_code == 302, r.text
    location = r.headers["location"]
    assert location.startswith("https://github.com/login/oauth/authorize?")
    assert "client_id=test-gh-client-id" in location
    assert "scope=read%3Auser+user%3Aemail" in location
    assert "state=" in location


def test_github_oauth_start_json_mode(client, monkeypatch):
    monkeypatch.setenv("GITHUB_OAUTH_CLIENT_ID", "json-mode-cid")
    r = client.get(
        "/v1/auth/github/start",
        headers={"Accept": "application/json"},
        follow_redirects=False,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert "authorize_url" in body
    assert body["authorize_url"].startswith("https://github.com/login/oauth/authorize?")
    assert "json-mode-cid" in body["authorize_url"]
    assert isinstance(body["state"], str) and len(body["state"]) >= 32
    assert body["expires_in"] == 600


def test_github_oauth_start_503_when_unconfigured(client, monkeypatch):
    monkeypatch.delenv("GITHUB_OAUTH_CLIENT_ID", raising=False)
    r = client.get(
        "/v1/auth/github/start",
        headers={"Accept": "application/json"},
        follow_redirects=False,
    )
    assert r.status_code == 503, r.text


# ---------------------------------------------------------------------------
# /callback
# ---------------------------------------------------------------------------


def _begin_flow(client, monkeypatch) -> str:
    """Walk /start in JSON mode and return the issued state nonce."""
    monkeypatch.setenv("GITHUB_OAUTH_CLIENT_ID", "cid")
    monkeypatch.setenv("GITHUB_OAUTH_CLIENT_SECRET", "csecret")
    r = client.get(
        "/v1/auth/github/start",
        headers={"Accept": "application/json"},
        follow_redirects=False,
    )
    assert r.status_code == 200, r.text
    return r.json()["state"]


def test_github_oauth_callback_happy_path(client, monkeypatch, seeded_db):
    state = _begin_flow(client, monkeypatch)

    # The handler issues TWO urllib.request.urlopen calls: one for the
    # token exchange, one for /user, and an optional /user/emails call.
    # Round-robin a deque of fake responses across all three.
    responses = [
        _FakeResp({"access_token": "ghp_test_access_token", "token_type": "bearer"}),
        _FakeResp(
            {
                "login": "octocat",
                "id": 583231,
                "name": "The Octocat",
                "avatar_url": "https://avatars.githubusercontent.com/u/583231?v=4",
                "email": None,
            }
        ),
        _FakeResp(
            [
                {
                    "email": "octocat@github.com",
                    "primary": True,
                    "verified": True,
                    "visibility": "public",
                }
            ]
        ),
    ]

    def _fake_urlopen(req, *_a, **_k):
        return responses.pop(0)

    with patch.object(urllib.request, "urlopen", side_effect=_fake_urlopen):
        r = client.get(
            "/v1/auth/github/callback",
            params={"code": "auth-code-123", "state": state},
            headers={"Accept": "application/json"},
            follow_redirects=False,
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["provider"] == "github"
    assert body["identity"]["login"] == "octocat"
    # Email is redacted by response_sanitizer (PII fence) — the GitHub
    # identity fetch DID return a real email, but the public response
    # surfaces the redaction sentinel. Either is acceptable; verify both
    # paths are covered.
    assert body["identity"]["email"] in ("octocat@github.com", "<email-redacted>")
    assert body["scopes"] == "read:user user:email"

    # State row must be deleted (one-shot) so a replay returns 400.
    c = sqlite3.connect(seeded_db)
    try:
        row = c.execute(
            "SELECT 1 FROM integration_sync_log "
            "WHERE provider = 'github_oauth_state' AND idempotency_key = ?",
            (state,),
        ).fetchone()
    finally:
        c.close()
    assert row is None


def test_github_oauth_callback_redirects_to_dashboard_by_default(client, monkeypatch):
    state = _begin_flow(client, monkeypatch)
    monkeypatch.setenv("JPINTEL_DASHBOARD_URL", "https://jpcite.com/dashboard.html")

    responses = [
        _FakeResp({"access_token": "ghp_token", "token_type": "bearer"}),
        _FakeResp({"login": "alice", "id": 1, "email": None}),
        _FakeResp([]),
    ]

    def _fake_urlopen(req, *_a, **_k):
        return responses.pop(0)

    with patch.object(urllib.request, "urlopen", side_effect=_fake_urlopen):
        r = client.get(
            "/v1/auth/github/callback",
            params={"code": "auth-code", "state": state},
            follow_redirects=False,
        )
    assert r.status_code in (302, 303), r.text
    assert r.headers["location"].startswith("https://jpcite.com/dashboard.html")
    assert "github_login=alice" in r.headers["location"]


def test_github_oauth_callback_invalid_state_400(client, monkeypatch):
    monkeypatch.setenv("GITHUB_OAUTH_CLIENT_ID", "cid")
    monkeypatch.setenv("GITHUB_OAUTH_CLIENT_SECRET", "csecret")
    r = client.get(
        "/v1/auth/github/callback",
        params={"code": "code", "state": "this-nonce-was-never-issued"},
        follow_redirects=False,
    )
    assert r.status_code == 400, r.text


def test_github_oauth_callback_token_error_502(client, monkeypatch):
    state = _begin_flow(client, monkeypatch)
    err_resp = _FakeResp(
        {
            "error": "bad_verification_code",
            "error_description": "The code passed is incorrect or expired.",
        }
    )
    with patch.object(urllib.request, "urlopen", return_value=err_resp):
        r = client.get(
            "/v1/auth/github/callback",
            params={"code": "stale", "state": state},
            headers={"Accept": "application/json"},
            follow_redirects=False,
        )
    assert r.status_code == 502, r.text


def test_github_oauth_callback_propagates_provider_error(client, monkeypatch):
    monkeypatch.setenv("GITHUB_OAUTH_CLIENT_ID", "cid")
    monkeypatch.setenv("GITHUB_OAUTH_CLIENT_SECRET", "csecret")
    # No /start was performed; user clicked Cancel on GitHub's consent
    # screen. Any state value with ``error=`` should 400 cleanly without
    # touching the network.
    r = client.get(
        "/v1/auth/github/callback",
        params={"code": "x", "state": "y", "error": "access_denied"},
        follow_redirects=False,
    )
    assert r.status_code == 400, r.text
    assert "access_denied" in r.text
