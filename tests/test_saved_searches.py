"""Smoke tests for /v1/me/saved_searches CRUD + Slack channel validation.

Coverage focus is the gap-fix surface added by migration 099:
    * channel_format / channel_url accepted on create + update
    * Slack URL must start with https://hooks.slack.com/services/ (SSRF)
    * email channel must NOT carry a channel_url
    * row read survives the legacy-shape branch (channel_format absent)
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from fastapi.responses import Response

from jpintel_mcp.billing.keys import issue_key


@pytest.fixture()
def saved_search_key(seeded_db: Path) -> str:
    c = sqlite3.connect(seeded_db)
    c.row_factory = sqlite3.Row
    raw = issue_key(
        c,
        customer_id="cus_saved_test",
        tier="paid",
        stripe_subscription_id="sub_saved_test",
    )
    c.commit()
    c.close()
    return raw


@pytest.fixture(autouse=True)
def _ensure_saved_searches_table(seeded_db: Path):
    """Apply 079 (base) + 099 (channel_format/url) migrations onto test DB."""
    repo = Path(__file__).resolve().parent.parent
    base = repo / "scripts" / "migrations" / "079_saved_searches.sql"

    c = sqlite3.connect(seeded_db)
    try:
        c.executescript(base.read_text(encoding="utf-8"))
        # 099 has multiple statements; ALTER TABLE ADD COLUMN is not
        # idempotent in SQLite so guard via PRAGMA table_info.
        cols = {row[1] for row in c.execute("PRAGMA table_info(saved_searches)")}
        if "channel_format" not in cols:
            c.execute(
                "ALTER TABLE saved_searches ADD COLUMN channel_format TEXT NOT NULL DEFAULT 'email'"
            )
        if "channel_url" not in cols:
            c.execute("ALTER TABLE saved_searches ADD COLUMN channel_url TEXT")
        c.execute("DELETE FROM saved_searches")
        c.commit()
    finally:
        c.close()
    yield


def test_create_email_channel_default(client, saved_search_key):
    r = client.post(
        "/v1/me/saved_searches",
        headers={"X-API-Key": saved_search_key},
        json={
            "name": "東京都の補助金",
            "query": {"prefecture": "東京都"},
            "frequency": "daily",
            "notify_email": "test@example.com",
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["channel_format"] == "email"
    assert body["channel_url"] is None


def test_create_slack_requires_slack_prefix(client, saved_search_key):
    r = client.post(
        "/v1/me/saved_searches",
        headers={"X-API-Key": saved_search_key},
        json={
            "name": "Slack 配信",
            "query": {"prefecture": "東京都"},
            "frequency": "daily",
            "notify_email": "test@example.com",
            "channel_format": "slack",
            "channel_url": "https://attacker.example.com/webhook",
        },
    )
    assert r.status_code == 422, r.text
    assert "hooks.slack.com" in r.text


def test_create_slack_with_valid_url(client, saved_search_key):
    r = client.post(
        "/v1/me/saved_searches",
        headers={"X-API-Key": saved_search_key},
        json={
            "name": "Slack OK",
            "query": {"prefecture": "東京都"},
            "frequency": "daily",
            "notify_email": "test@example.com",
            "channel_format": "slack",
            "channel_url": "https://hooks.slack.com/services/T0/B0/XYZ",
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["channel_format"] == "slack"
    assert body["channel_url"].startswith("https://hooks.slack.com/services/")


def test_create_email_rejects_url(client, saved_search_key):
    r = client.post(
        "/v1/me/saved_searches",
        headers={"X-API-Key": saved_search_key},
        json={
            "name": "Bad email shape",
            "query": {"prefecture": "東京都"},
            "frequency": "daily",
            "notify_email": "test@example.com",
            "channel_format": "email",
            "channel_url": "https://hooks.slack.com/services/X",
        },
    )
    assert r.status_code == 422, r.text


def _usage_count(db: Path, endpoint: str) -> int:
    c = sqlite3.connect(db)
    try:
        return c.execute(
            "SELECT COUNT(*) FROM usage_events WHERE endpoint = ?",
            (endpoint,),
        ).fetchone()[0]
    finally:
        c.close()


def test_results_xlsx_replays_saved_filters_before_billing(
    client, saved_search_key, seeded_db: Path, monkeypatch
):
    captured: dict[str, object] = {}

    def _fake_build_search_response(**kwargs):
        captured["build_kwargs"] = kwargs
        return {"total": 12, "results": [{"unified_id": "UNI-saved-filter"}]}

    def _fake_render_xlsx(rows, meta):
        captured["rows"] = rows
        captured["meta"] = meta
        return Response(
            b"xlsx-ok",
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    from jpintel_mcp.api import programs as programs_mod
    from jpintel_mcp.api.formats import xlsx as xlsx_mod

    monkeypatch.setattr(programs_mod, "_build_search_response", _fake_build_search_response)
    monkeypatch.setattr(xlsx_mod, "render_xlsx", _fake_render_xlsx)

    r0 = client.post(
        "/v1/me/saved_searches",
        headers={"X-API-Key": saved_search_key},
        json={
            "name": "filtered export",
            "query": {
                "q": "太陽光",
                "prefecture": "東京都",
                "authority_level": "national",
                "target_types": ["sme"],
                "funding_purpose": ["設備投資"],
                "amount_min": 1000,
                "amount_max": 2000,
                "tier": ["A"],
            },
            "frequency": "daily",
            "notify_email": "test@example.com",
        },
    )
    assert r0.status_code == 201, r0.text
    saved_id = r0.json()["id"]

    before = _usage_count(seeded_db, "saved_searches.results_xlsx")
    r = client.get(
        f"/v1/me/saved_searches/{saved_id}/results.xlsx",
        headers={"X-API-Key": saved_search_key},
    )
    assert r.status_code == 200, r.text
    assert r.content == b"xlsx-ok"

    kwargs = captured["build_kwargs"]
    assert kwargs["q"] == "太陽光"
    assert kwargs["tier"] == ["A"]
    assert kwargs["prefecture"] == "東京都"
    assert kwargs["authority_level"] == "national"
    assert kwargs["target_type"] == ["sme"]
    assert kwargs["funding_purpose"] == ["設備投資"]
    assert kwargs["amount_min"] == 1000
    assert kwargs["amount_max"] == 2000
    assert kwargs["include_excluded"] is False
    assert captured["rows"][0]["evidence_packet_endpoint"].endswith(
        "/v1/evidence/packets/program/UNI-saved-filter"
    )
    assert captured["meta"]["license"] == "jpcite evidence export"
    assert _usage_count(seeded_db, "saved_searches.results_xlsx") == before + 1


def test_results_xlsx_renderer_failure_charges_first_per_pattern_a(
    client, saved_search_key, seeded_db: Path, monkeypatch
):
    """DEEP-48 Pattern A — charge BEFORE render.

    Replaces the legacy "render-fail = no bill" path: under the charge-first
    fence, a renderer crash AFTER successful billing leaves a +1 usage row
    behind. The cap-exceeded path (final_cap_failure test below) is the
    correct fail-closed branch; this test pins the charge-first invariant
    so a future refactor that re-orders charge after render is caught.
    """

    def _fake_build_search_response(**kwargs):
        return {"total": 1, "results": [{"unified_id": "UNI-render-fails"}]}

    def _boom(rows, meta):
        raise RuntimeError("xlsx renderer failed")

    from jpintel_mcp.api import programs as programs_mod
    from jpintel_mcp.api.formats import xlsx as xlsx_mod

    monkeypatch.setattr(programs_mod, "_build_search_response", _fake_build_search_response)
    monkeypatch.setattr(xlsx_mod, "render_xlsx", _boom)

    r0 = client.post(
        "/v1/me/saved_searches",
        headers={"X-API-Key": saved_search_key},
        json={
            "name": "failed export",
            "query": {"prefecture": "東京都"},
            "frequency": "daily",
            "notify_email": "test@example.com",
        },
    )
    assert r0.status_code == 201, r0.text
    saved_id = r0.json()["id"]

    before = _usage_count(seeded_db, "saved_searches.results_xlsx")
    with pytest.raises(RuntimeError, match="xlsx renderer failed"):
        client.get(
            f"/v1/me/saved_searches/{saved_id}/results.xlsx",
            headers={"X-API-Key": saved_search_key},
        )
    # Pattern A: charge happened pre-render, so the renderer crash leaves
    # a usage row behind. Reconcile cron handles the rare refund path.
    assert _usage_count(seeded_db, "saved_searches.results_xlsx") == before + 1


def test_results_paid_final_cap_failure_returns_503_without_usage_event(
    client, saved_search_key, seeded_db: Path, monkeypatch
):
    import jpintel_mcp.api.deps as deps
    from jpintel_mcp.api.deps import hash_api_key

    def _fake_build_search_response(**kwargs):
        return {"total": 1, "results": [{"unified_id": "UNI-final-cap"}]}

    def _reject_final_cap(*_args, **_kwargs):
        return False, False

    from jpintel_mcp.api import programs as programs_mod

    monkeypatch.setattr(programs_mod, "_build_search_response", _fake_build_search_response)

    r0 = client.post(
        "/v1/me/saved_searches",
        headers={"X-API-Key": saved_search_key},
        json={
            "name": "final cap check",
            "query": {"prefecture": "東京都"},
            "frequency": "daily",
            "notify_email": "test@example.com",
        },
    )
    assert r0.status_code == 201, r0.text
    saved_id = r0.json()["id"]

    key_hash = hash_api_key(saved_search_key)
    c = sqlite3.connect(seeded_db)
    try:
        before = c.execute(
            "SELECT COUNT(*) FROM usage_events WHERE key_hash = ? AND endpoint = ?",
            (key_hash, "saved_searches.results"),
        ).fetchone()[0]
    finally:
        c.close()

    monkeypatch.setattr(deps, "_metered_cap_final_check", _reject_final_cap)

    r = client.get(
        f"/v1/me/saved_searches/{saved_id}/results",
        headers={"X-API-Key": saved_search_key},
    )
    assert r.status_code == 503, r.text
    assert r.json()["detail"]["code"] == "billing_cap_final_check_failed"

    c = sqlite3.connect(seeded_db)
    try:
        after = c.execute(
            "SELECT COUNT(*) FROM usage_events WHERE key_hash = ? AND endpoint = ?",
            (key_hash, "saved_searches.results"),
        ).fetchone()[0]
    finally:
        c.close()
    assert after == before
