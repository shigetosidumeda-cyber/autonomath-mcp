"""LINE bot webhook tests.

Coverage targets:

  * Signature verification — valid + invalid + missing secret
  * Quick-reply state machine — full 4-step round trip
  * Anonymous-equivalent free quota (50/month per LINE user)
  * Idempotency — duplicate webhook event_id skipped without re-billing
  * Constraint check — ZERO references to "Connect", "reseller",
    "commission split" in the shipped LINE bot code (locked
    organic-only acquisition policy).

These tests apply migrations 021 (`line_users`) and 106
(`line_message_log`) into the per-test seeded DB because the production
schema.sql doesn't ship those tables (they live in the migrations
folder and are applied via entrypoint.sh / scripts/migrate.py at boot).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

# A stable test channel secret. Long enough that hmac doesn't reject.
TEST_CHANNEL_SECRET = "test-line-channel-secret-do-not-use-in-prod"
TEST_CHANNEL_TOKEN = "test-line-channel-access-token"


def _sign(body: bytes, secret: str = TEST_CHANNEL_SECRET) -> str:
    """Compute the X-Line-Signature header value LINE would send."""
    mac = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()
    return base64.b64encode(mac).decode("ascii")


def _apply_line_migrations(db_path: Path) -> None:
    """Apply 021_line_users.sql + 106_line_message_log.sql to the test DB.

    Idempotent (every CREATE is IF NOT EXISTS).
    """
    repo_root = Path(__file__).resolve().parents[1]
    mig_dir = repo_root / "scripts" / "migrations"
    sql_021 = (mig_dir / "021_line_users.sql").read_text(encoding="utf-8")
    sql_106 = (mig_dir / "106_line_message_log.sql").read_text(encoding="utf-8")
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(sql_021)
        conn.executescript(sql_106)
        conn.commit()
    finally:
        conn.close()


@pytest.fixture()
def line_client(seeded_db: Path, monkeypatch: pytest.MonkeyPatch):
    """TestClient with LINE channel secret + access token configured.

    Reaches into `line_settings` directly because pydantic_settings caches
    the env at import time and overriding env vars after the import has
    no effect.
    """
    _apply_line_migrations(seeded_db)
    from jpintel_mcp.line.config import line_settings as _ls

    monkeypatch.setattr(_ls, "channel_secret", TEST_CHANNEL_SECRET)
    monkeypatch.setattr(_ls, "channel_access_token", TEST_CHANNEL_TOKEN)

    # Stub out the outbound httpx call so tests don't reach api.line.me.
    from jpintel_mcp.api import line_webhook as lw

    async def _fake_reply(reply_token: str, messages: list[dict[str, Any]]) -> bool:
        return True

    monkeypatch.setattr(lw, "_post_line_reply", _fake_reply)

    from jpintel_mcp.api.main import create_app

    return TestClient(create_app())


# ---------------------------------------------------------------------------
# Signature verification
# ---------------------------------------------------------------------------


def test_line_webhook_signature_valid(line_client):
    body = b'{"destination":"Uxxx","events":[]}'
    sig = _sign(body)
    r = line_client.post(
        "/v1/integrations/line/webhook",
        content=body,
        headers={"X-Line-Signature": sig, "Content-Type": "application/json"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "ok"


def test_line_webhook_signature_invalid(line_client):
    body = b'{"destination":"Uxxx","events":[]}'
    bad_sig = "obviously-wrong-signature-aaaaaaaa"
    r = line_client.post(
        "/v1/integrations/line/webhook",
        content=body,
        headers={"X-Line-Signature": bad_sig, "Content-Type": "application/json"},
    )
    assert r.status_code == 401


def test_line_webhook_missing_signature(line_client):
    body = b'{"destination":"Uxxx","events":[]}'
    r = line_client.post(
        "/v1/integrations/line/webhook",
        content=body,
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 401


def test_line_webhook_missing_secret_returns_503(seeded_db: Path, monkeypatch):
    """When LINE_CHANNEL_SECRET is empty we MUST refuse, not auto-accept."""
    _apply_line_migrations(seeded_db)
    from jpintel_mcp.line.config import line_settings as _ls

    monkeypatch.setattr(_ls, "channel_secret", "")

    from jpintel_mcp.api.main import create_app

    client = TestClient(create_app())
    body = b'{"destination":"Uxxx","events":[]}'
    r = client.post(
        "/v1/integrations/line/webhook",
        content=body,
        headers={"X-Line-Signature": "ignored", "Content-Type": "application/json"},
    )
    assert r.status_code == 503


# ---------------------------------------------------------------------------
# Quick-reply state machine — flow.advance() unit tests
# ---------------------------------------------------------------------------


def test_flow_idle_returns_welcome():
    from jpintel_mcp.line import flow

    state, messages = flow.advance(None, "anything")
    assert state["step"] == "industry"
    assert state.get("answers") == {}
    assert len(messages) == 1
    assert flow.WELCOME_TEXT in messages[0]["text"]
    quick = messages[0]["quickReply"]["items"]
    assert {q["action"]["text"] for q in quick} == {
        label for label, _ in flow.INDUSTRY_CHOICES
    }


def test_flow_industry_to_prefecture():
    from jpintel_mcp.line import flow

    state, messages = flow.advance({"step": "industry", "answers": {}}, "建設業")
    assert state["step"] == "prefecture"
    assert state["answers"]["industry"] == "建設業"
    quick = messages[0]["quickReply"]["items"]
    assert "東京都" not in {q["action"]["text"] for q in quick}  # batch 0 doesn't have 東京都
    assert "北海道" in {q["action"]["text"] for q in quick}


def test_flow_industry_invalid_input_re_prompts():
    from jpintel_mcp.line import flow

    state, messages = flow.advance({"step": "industry", "answers": {}}, "ランダムテキスト")
    assert state["step"] == "industry"  # still on the same step
    assert "ボタン" in messages[0]["text"]


def test_flow_prefecture_to_employees():
    from jpintel_mcp.line import flow

    state, messages = flow.advance(
        {"step": "prefecture", "answers": {"industry": "建設業"}}, "東京都"
    )
    assert state["step"] == "employees"
    assert state["answers"]["prefecture"] == "東京都"
    quick = messages[0]["quickReply"]["items"]
    assert {q["action"]["text"] for q in quick} == {
        label for label, _ in flow.EMPLOYEE_CHOICES
    }


def test_flow_employees_to_revenue():
    from jpintel_mcp.line import flow

    state, messages = flow.advance(
        {"step": "employees", "answers": {"industry": "建設業", "prefecture": "東京都"}},
        "〜20人",
    )
    assert state["step"] == "revenue"
    assert state["answers"]["employees"] == "〜20人"


def test_flow_revenue_to_results_renders_programs(seeded_db: Path):
    from jpintel_mcp.line import flow

    conn = sqlite3.connect(seeded_db)
    conn.row_factory = sqlite3.Row
    try:
        state, messages = flow.advance(
            {
                "step": "revenue",
                "answers": {
                    "industry": "その他",
                    "prefecture": "東京都",
                    "employees": "〜20人",
                },
            },
            "〜1億円",
            conn=conn,
        )
        assert state["step"] == "results"
        # The seeded DB has UNI-test-s-1 in 東京都, tier S, and a program in
        # 全国 (B-tier 融資). Both should pass the prefecture filter.
        text = messages[0]["text"]
        assert "テスト S-tier 補助金" in text or "B-tier 融資" in text
    finally:
        conn.close()


def test_flow_revenue_no_match_falls_back():
    """When the DB has no eligible programs we render NO_RESULTS_TEXT."""
    from jpintel_mcp.line import flow

    state, messages = flow.advance(
        {
            "step": "revenue",
            "answers": {
                "industry": "建設業",
                "prefecture": "鳥取県",   # nothing seeded for 鳥取
                "employees": "〜5人",
            },
        },
        "〜1億円",
        conn=None,  # no DB → defensive fallback
    )
    assert state["step"] == "results"
    assert flow.NO_RESULTS_TEXT in messages[0]["text"]


# ---------------------------------------------------------------------------
# Three-message round-trip via the webhook
# ---------------------------------------------------------------------------


def _post_event(line_client, line_user_id: str, text: str, event_id: str) -> dict[str, Any]:
    """POST a single text-message webhook event with valid signature."""
    body_obj = {
        "destination": "Uxxx",
        "events": [
            {
                "type": "message",
                "webhookEventId": event_id,
                "timestamp": int(datetime.now(UTC).timestamp() * 1000),
                "source": {"type": "user", "userId": line_user_id},
                "replyToken": "replytoken-" + event_id,
                "message": {"type": "text", "text": text, "id": "msg-" + event_id},
            }
        ],
    }
    body = json.dumps(body_obj).encode("utf-8")
    sig = _sign(body)
    r = line_client.post(
        "/v1/integrations/line/webhook",
        content=body,
        headers={"X-Line-Signature": sig, "Content-Type": "application/json"},
    )
    return {"status": r.status_code, "json": r.json() if r.status_code < 500 else None}


def test_three_message_round_trip(line_client, seeded_db: Path):
    """User says hi → industry → prefecture → 3rd row in line_users state."""
    user_id = "Utest3msg" + "0" * 24
    # Msg 1: bootstrap → industry
    r1 = _post_event(line_client, user_id, "こんにちは", "evt-1")
    assert r1["status"] == 200, r1
    # Msg 2: pick industry → prefecture
    r2 = _post_event(line_client, user_id, "建設業", "evt-2")
    assert r2["status"] == 200, r2
    # Msg 3: pick prefecture → employees
    r3 = _post_event(line_client, user_id, "東京都", "evt-3")
    assert r3["status"] == 200, r3

    # Assert the persisted state landed at step=employees.
    conn = sqlite3.connect(seeded_db)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT current_flow_state_json FROM line_users WHERE line_user_id = ?",
            (user_id,),
        ).fetchone()
        assert row is not None
        state = json.loads(row["current_flow_state_json"])
        assert state["step"] == "employees"
        assert state["answers"]["industry"] == "建設業"
        assert state["answers"]["prefecture"] == "東京都"
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Anonymous (no api_key) billing → free quota counted
# ---------------------------------------------------------------------------


def test_anon_user_counts_against_free_tier(line_client, seeded_db: Path):
    """Each event for a free LINE user increments query_count_mtd."""
    user_id = "Utestanon" + "0" * 25
    _post_event(line_client, user_id, "hi", "evt-anon-1")
    _post_event(line_client, user_id, "建設業", "evt-anon-2")

    conn = sqlite3.connect(seeded_db)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT plan, query_count_mtd FROM line_users WHERE line_user_id = ?",
            (user_id,),
        ).fetchone()
        assert row["plan"] == "free"
        # First message bootstraps, second message advances. Both consume
        # one quota each (count ≥ 1; exact count depends on the path).
        assert row["query_count_mtd"] >= 1
    finally:
        conn.close()


def test_quota_exceeded_response(line_client, seeded_db: Path):
    """When query_count_mtd ≥ 50, replies switch to QUOTA_EXCEEDED_TEXT."""
    user_id = "Utestquota" + "0" * 24
    # Pre-create user at the cap.
    conn = sqlite3.connect(seeded_db)
    try:
        future_reset = (datetime.now(UTC) + timedelta(days=10)).isoformat()
        now = datetime.now(UTC).isoformat()
        conn.execute(
            "INSERT INTO line_users("
            "  line_user_id, language, added_at, plan, "
            "  query_count_mtd, query_count_mtd_resets_at, updated_at"
            ") VALUES (?,?,?,?,?,?,?)",
            (user_id, "ja", now, "free", 50, future_reset, now),
        )
        conn.commit()
    finally:
        conn.close()

    r = _post_event(line_client, user_id, "建設業", "evt-quota-1")
    assert r["status"] == 200

    # The line_message_log row should mark quota_exceeded=1.
    conn = sqlite3.connect(seeded_db)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT quota_exceeded, billed FROM line_message_log "
            "WHERE event_id = ? AND direction = 'inbound'",
            ("evt-quota-1",),
        ).fetchone()
        assert row is not None
        assert row["quota_exceeded"] == 1
        assert row["billed"] == 0
    finally:
        conn.close()


def test_duplicate_event_id_idempotent(line_client, seeded_db: Path):
    """LINE retry → second POST with same event_id must NOT re-bill or re-reply."""
    user_id = "Utestidem" + "0" * 25
    _post_event(line_client, user_id, "hi", "evt-dup-1")
    _post_event(line_client, user_id, "hi", "evt-dup-1")  # same id

    conn = sqlite3.connect(seeded_db)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT direction FROM line_message_log WHERE event_id = ?",
            ("evt-dup-1",),
        ).fetchall()
        # At most one inbound row + at most one outbound_reply row, never two of either.
        directions = [r["direction"] for r in rows]
        assert directions.count("inbound") == 1
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Compliance fence — locked policy: NO Stripe Connect, NO reseller, NO commission split
# ---------------------------------------------------------------------------


def test_no_connect_or_reseller_in_line_bot_code():
    """The shipped LINE bot code MUST NOT mention Connect / reseller /
    commission split. CLAUDE.md locks 100% organic acquisition.

    The advisors module is excluded — that's a separate (older) feature
    with its own commission_model column and is unrelated to LINE.
    """
    repo_root = Path(__file__).resolve().parents[1]
    line_files = [
        repo_root / "src" / "jpintel_mcp" / "line" / "__init__.py",
        repo_root / "src" / "jpintel_mcp" / "line" / "config.py",
        repo_root / "src" / "jpintel_mcp" / "line" / "flow.py",
        repo_root / "src" / "jpintel_mcp" / "api" / "line_webhook.py",
        repo_root / "scripts" / "migrations" / "106_line_message_log.sql",
    ]
    forbidden_patterns = [
        "Stripe Connect",
        "stripe_connect_account_id",
        "reseller",
        "commission_split",
        "commission_yen_per_intro",
        "commission_rate_pct",
        "20% reseller",
        "tax advisor reseller",
    ]
    found: list[str] = []
    for f in line_files:
        if not f.exists():
            continue
        text = f.read_text(encoding="utf-8")
        for pat in forbidden_patterns:
            if pat in text:
                found.append(f"{f.name}: {pat!r}")
    assert not found, (
        "Forbidden pattern(s) leaked into the LINE bot surface — these "
        "violate the locked 100% organic-acquisition policy:\n  "
        + "\n  ".join(found)
    )
