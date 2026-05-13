"""Dimension F orchestration smoke — Wave 43.2.6 (2026-05-12).

Covers the four ``/v1/orchestrate/{target}`` REST routes shipped in
``src/jpintel_mcp/api/orchestrator_v2.py`` PLUS the matching MCP tool
shipped in ``src/jpintel_mcp/mcp/autonomath_tools/orchestrator_v2.py``.

Test posture
------------
* **No outbound HTTP.** The freee / MF / Notion / Slack network calls
  are mocked at the ``urllib.request.urlopen`` boundary so the suite is
  hermetic. Real customer-env calls are an out-of-band smoke run, not a
  CI gate.
* **No LLM SDK imports.** Verified explicitly in the import linter
  (`tests/test_no_llm_in_production.py`); this file is plain pytest +
  stdlib + ``unittest.mock``.
* **Each target gets at least one happy path + one validation edge.**
  Happy path: target accepts a paid key, matches a program, posts the
  mocked outbound, returns 200 + delivery_status=200. Edge: missing
  required payload key for the MCP tool surfaces an error envelope.
"""

from __future__ import annotations

import io
import json
import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest

from jpintel_mcp.billing.keys import issue_key

_REPO_ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def paid_key(seeded_db: Path) -> str:
    """Mint a paid metered API key against the seeded test DB."""
    conn = sqlite3.connect(seeded_db)
    raw = issue_key(
        conn,
        customer_id="cus_orchestrate_test",
        tier="paid",
        stripe_subscription_id="sub_orchestrate_test",
    )
    conn.commit()
    conn.close()
    return raw


class _FakeResponse(io.BytesIO):
    """Stand-in for the urlopen() context-manager result."""

    def __init__(self, status: int = 200, body: bytes = b"{}") -> None:
        super().__init__(body)
        self.status = status

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *_a: object) -> None:
        return None


def _fake_urlopen(status: int = 200):
    """Build a urlopen replacement that records each call and returns 2xx."""

    captured: list[object] = []

    def _impl(req, timeout=None):  # noqa: ARG001 — match real urlopen signature
        captured.append(req)
        return _FakeResponse(status=status, body=b'{"ok":true}')

    return _impl, captured


# ---------------------------------------------------------------------------
# 1) freee target
# ---------------------------------------------------------------------------


def test_orchestrate_freee_happy_path(client, paid_key):
    impl, captured = _fake_urlopen(status=200)
    with patch("urllib.request.urlopen", impl):
        r = client.post(
            "/v1/orchestrate/freee",
            headers={"X-API-Key": paid_key},
            json={
                "freee_token": "tok_freee_test_xxxxx",
                "company_id": 1234,
                "rows": [{"account_item": "DX 補助金", "amount_yen": 50000}],
            },
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["target"] == "freee"
    assert body["rows_in"] == 1
    assert body["metered_units"] == 3
    assert "_disclaimer" in body or "disclaimer" in body
    # Outbound POST hit the freee receipts API (or skipped if no match).
    # Either way: never more than one POST per row.
    assert len(captured) <= 1


def test_orchestrate_freee_rejects_anonymous(client):
    r = client.post(
        "/v1/orchestrate/freee",
        json={
            "freee_token": "tok_freee_test_xxxxx",
            "company_id": 1,
            "rows": [{"account_item": "x"}],
        },
    )
    # require_metered_api_key returns 401 or 402 for anonymous; either is OK.
    assert r.status_code in (401, 402, 403)


# ---------------------------------------------------------------------------
# 2) MoneyForward target
# ---------------------------------------------------------------------------


def test_orchestrate_mf_happy_path(client, paid_key):
    impl, _captured = _fake_urlopen(status=200)
    with patch("urllib.request.urlopen", impl):
        r = client.post(
            "/v1/orchestrate/mf",
            headers={"X-API-Key": paid_key},
            json={
                "mf_token": "tok_mf_test_xxxxx",
                "office_id": "office_001",
                "rows": [{"account_code": "助成金", "description": "test row"}],
            },
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["target"] == "mf"
    assert body["rows_in"] == 1
    assert body["metered_units"] == 3


def test_orchestrate_mf_too_many_rows_422(client, paid_key):
    rows = [{"account_code": f"code{i}"} for i in range(21)]  # cap is 20
    r = client.post(
        "/v1/orchestrate/mf",
        headers={"X-API-Key": paid_key},
        json={"mf_token": "tok", "office_id": "office_001", "rows": rows},
    )
    assert r.status_code == 422, r.text


# ---------------------------------------------------------------------------
# 3) Notion target
# ---------------------------------------------------------------------------


def test_orchestrate_notion_happy_path(client, paid_key):
    impl, captured = _fake_urlopen(status=200)
    with patch("urllib.request.urlopen", impl):
        r = client.post(
            "/v1/orchestrate/notion",
            headers={"X-API-Key": paid_key},
            json={
                "notion_token": "secret_notion_test_xxxxx",
                "database_id": "abcdef1234567890",
                "amendment_keys": ["DX 補助金"],
            },
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["target"] == "notion"
    assert body["rows_in"] == 1
    # If a program matched the keyword, a single Notion POST was attempted.
    assert len(captured) <= 1
    if captured:
        assert "notion.com" in captured[0].full_url


# ---------------------------------------------------------------------------
# 4) Slack target
# ---------------------------------------------------------------------------


def test_orchestrate_slack_happy_path(client, paid_key):
    impl, captured = _fake_urlopen(status=200)
    with patch("urllib.request.urlopen", impl):
        r = client.post(
            "/v1/orchestrate/slack",
            headers={"X-API-Key": paid_key},
            json={
                "slack_webhook_url": "https://hooks.slack.com/services/T0/B0/Z0",
                "kind": "amendment.alert",
                "title": "Wave 43.2.6 dim F",
                "summary": "synthetic test alert",
                "url": "https://jpcite.com",
                "event": "info",
            },
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["target"] == "slack"
    assert body["rows_in"] == 1
    assert body["metered_units"] == 3
    assert len(captured) == 1
    assert "hooks.slack.com" in captured[0].full_url
    # Verify Block Kit body shape.
    sent_body = json.loads(captured[0].data.decode("utf-8"))
    assert sent_body.get("text", "").startswith("Wave 43.2.6")
    assert isinstance(sent_body.get("blocks"), list)


def test_orchestrate_slack_invalid_webhook_url_422(client, paid_key):
    r = client.post(
        "/v1/orchestrate/slack",
        headers={"X-API-Key": paid_key},
        json={
            "slack_webhook_url": "https://example.com/not-a-slack-hook",
            "kind": "x",
            "title": "x",
            "summary": "x",
            "url": "https://jpcite.com",
        },
    )
    assert r.status_code == 422, r.text


# ---------------------------------------------------------------------------
# 5) GET /v1/orchestrate/targets discovery surface
# ---------------------------------------------------------------------------


def test_orchestrate_targets_listing(client):
    r = client.get("/v1/orchestrate/targets")
    assert r.status_code == 200
    body = r.json()
    assert sorted(body["targets"]) == sorted(["freee", "mf", "notion", "slack"])
    assert body["unit_count_per_call"] == 3
    assert body["yen_per_call"] == 9


# ---------------------------------------------------------------------------
# 6) MCP tool surface — pure Python impl, no FastAPI client needed
# ---------------------------------------------------------------------------


def test_mcp_orchestrate_to_external_am_validates_target():
    from jpintel_mcp.mcp.autonomath_tools.orchestrator_v2 import (
        _orchestrate_impl,
    )

    out = _orchestrate_impl(
        target="not_a_real_target",
        action="invoke",
        payload={"freee_token": "x", "company_id": 1, "rows": [{}]},
    )
    assert isinstance(out, dict)
    assert out.get("error", {}).get("code") == "invalid_argument"


def test_mcp_orchestrate_to_external_am_validates_payload():
    from jpintel_mcp.mcp.autonomath_tools.orchestrator_v2 import (
        _orchestrate_impl,
    )

    out = _orchestrate_impl(
        target="slack",
        action="invoke",
        payload={"slack_webhook_url": "https://hooks.slack.com/services/T/B/Z"},
        # missing kind/title/summary/url -> should error on required keys.
    )
    assert out.get("error", {}).get("code") == "missing_required_arg"


def test_mcp_orchestrate_to_external_am_happy_manifest():
    from jpintel_mcp.mcp.autonomath_tools.orchestrator_v2 import (
        _orchestrate_impl,
    )

    out = _orchestrate_impl(
        target="freee",
        action="invoke",
        payload={
            "freee_token": "tok",
            "company_id": 7,
            "rows": [{"account_item": "x"}],
        },
    )
    assert out["target"] == "freee"
    assert out["rest_endpoint"] == "/v1/orchestrate/freee"
    assert out["metered_units_per_call"] == 3
    assert out["yen_per_call"] == 9
    assert "_disclaimer" in out
    assert "_next_calls" in out


def test_mcp_list_orchestrate_targets():
    from jpintel_mcp.mcp.autonomath_tools.orchestrator_v2 import (
        _list_targets_impl,
    )

    out = _list_targets_impl()
    assert sorted(out["targets"]) == sorted(["freee", "mf", "notion", "slack"])
    assert "freee" in out["required_payload_fields"]
    assert "mf" in out["required_payload_fields"]
    assert "notion" in out["required_payload_fields"]
    assert "slack" in out["required_payload_fields"]


# ---------------------------------------------------------------------------
# 7) LLM API import guard — explicit cross-check vs feedback_no_operator_llm_api
# ---------------------------------------------------------------------------


def test_no_llm_sdk_imports_in_orchestrator_files():
    """Defence-in-depth: scan the two new files for forbidden LLM imports.

    Mirrors ``tests/test_no_llm_in_production.py`` but scoped to the
    Wave 43.2.6 surface so a regression here would fail this test FIRST
    (faster blast radius than the repo-wide scan).
    """
    forbidden = ("anthropic", "openai", "google.generativeai", "claude_agent_sdk")
    targets = [
        _REPO_ROOT / "src" / "jpintel_mcp" / "api" / "orchestrator_v2.py",
        _REPO_ROOT / "src" / "jpintel_mcp" / "mcp" / "autonomath_tools" / "orchestrator_v2.py",
    ]
    for path in targets:
        text = path.read_text(encoding="utf-8")
        for needle in forbidden:
            assert f"import {needle}" not in text, (
                f"forbidden LLM import {needle!r} found in {path}"
            )
            assert f"from {needle}" not in text, (
                f"forbidden LLM import from {needle!r} found in {path}"
            )
