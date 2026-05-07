"""Tests for the Postmark email layer + /v1/email/webhook receiver.

Mock strategy
-------------
`pytest-httpx` / `respx` are NOT installed — see pyproject.toml. We use
`httpx.MockTransport` instead, which is in the standard httpx distribution
(no new dependency). The transport receives each outbound Request and
returns a canned Response; tests assert on `captured.append(request)` to
verify what we would have sent.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import sqlite3
from typing import TYPE_CHECKING

import httpx
import pytest

from jpintel_mcp.email import postmark as pm_mod
from jpintel_mcp.email.postmark import (
    POSTMARK_BASE_URL,
    SEND_WITH_TEMPLATE_PATH,
    PostmarkClient,
)

if TYPE_CHECKING:
    from pathlib import Path

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_http(
    captured: list[httpx.Request], status_code: int = 200, body: dict | None = None
) -> httpx.Client:
    """Build an httpx.Client that records every request into `captured`."""

    def _handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            status_code,
            json=body if body is not None else {"MessageID": "stub-1", "ErrorCode": 0},
        )

    return httpx.Client(
        base_url=POSTMARK_BASE_URL,
        transport=httpx.MockTransport(_handler),
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-Postmark-Server-Token": "test-token",
        },
    )


# ---------------------------------------------------------------------------
# send_welcome
# ---------------------------------------------------------------------------


def test_send_welcome_posts_expected_payload():
    """send_welcome hits /email/withTemplate with the right TemplateModel."""
    captured: list[httpx.Request] = []
    client = PostmarkClient(
        api_token="test-token",
        from_transactional="no-reply@example.test",
        from_reply="hello@example.test",
        env="prod",  # force real-send path past the test-mode gate
        _http=_mock_http(captured),
    )

    resp = client.send_welcome(to="alice@example.com", key_last4="abcd", tier="paid")

    assert resp.get("MessageID") == "stub-1"
    assert len(captured) == 1
    req = captured[0]
    assert req.method == "POST"
    assert req.url.path == SEND_WITH_TEMPLATE_PATH
    body = json.loads(req.content)
    assert body["From"] == "no-reply@example.test"
    assert body["ReplyTo"] == "hello@example.test"
    assert body["To"] == "alice@example.com"
    assert body["TemplateAlias"] == "welcome"
    assert body["TemplateModel"] == {"key_last4": "abcd", "tier": "paid"}
    assert body["MessageStream"] == "outbound"
    assert body["Tag"] == "welcome"


def test_send_digest_uses_broadcast_stream():
    captured: list[httpx.Request] = []
    client = PostmarkClient(
        api_token="test-token",
        from_transactional="no-reply@example.test",
        from_reply="hello@example.test",
        env="prod",
        _http=_mock_http(captured),
    )

    client.send_digest(
        to="bob@example.com",
        programs=[{"unified_id": "UNI-x", "name": "X"}],
        unsub_token="hmactoken",
    )

    body = json.loads(captured[0].content)
    assert body["TemplateAlias"] == "weekly-digest"
    assert body["MessageStream"] == "broadcast"
    assert body["TemplateModel"]["unsub_token"] == "hmactoken"
    assert body["TemplateModel"]["email"] == "bob@example.com"
    assert body["Tag"] == "digest"


def test_send_receipt_forwards_invoice_url():
    captured: list[httpx.Request] = []
    client = PostmarkClient(
        api_token="test-token",
        from_transactional="no-reply@example.test",
        from_reply="hello@example.test",
        env="prod",
        _http=_mock_http(captured),
    )
    client.send_receipt(to="c@example.com", invoice_url="https://stripe.test/i/123")

    body = json.loads(captured[0].content)
    assert body["TemplateAlias"] == "receipt"
    assert body["TemplateModel"] == {"invoice_url": "https://stripe.test/i/123"}


def test_send_key_rotated_posts_expected_payload():
    """send_key_rotated hits /email/withTemplate with the rotation TemplateModel.

    P1 from key-rotation audit a4298e454aab2aa43: rotation MUST trigger an
    out-of-band notice carrying old/new key suffixes, caller IP, User-Agent,
    and JST timestamp so the customer can detect a rogue rotation.
    """
    captured: list[httpx.Request] = []
    client = PostmarkClient(
        api_token="test-token",
        from_transactional="no-reply@example.test",
        from_reply="hello@example.test",
        env="prod",
        _http=_mock_http(captured),
    )

    resp = client.send_key_rotated(
        to="alice@example.com",
        old_suffix="abcd",
        new_suffix="wxyz",
        ip="203.0.113.7",
        user_agent="Mozilla/5.0 (test)",
        ts_jst="2026-04-25 12:34 JST",
    )

    assert resp.get("MessageID") == "stub-1"
    assert len(captured) == 1
    body = json.loads(captured[0].content)
    assert body["TemplateAlias"] == "key-rotated"
    assert body["MessageStream"] == "outbound"
    assert body["Tag"] == "key-rotated"
    assert body["TemplateModel"] == {
        "old_suffix": "abcd",
        "new_suffix": "wxyz",
        "ip": "203.0.113.7",
        "user_agent": "Mozilla/5.0 (test)",
        "ts_jst": "2026-04-25 12:34 JST",
    }


def test_key_rotated_render_includes_all_fields():
    """Reference template at templates/key_rotated.{html,txt} carries every
    placeholder the Postmark UI alias is expected to render.

    These on-disk files are the canonical mirror of the Postmark template
    (see templates/README.md). A drift here means a Postmark UI edit will
    silently disagree with the Python TemplateModel and customers receive
    a partially-blank notice.
    """
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[1]
    tpl_dir = repo_root / "src" / "jpintel_mcp" / "email" / "templates"
    html = (tpl_dir / "key_rotated.html").read_text(encoding="utf-8")
    txt = (tpl_dir / "key_rotated.txt").read_text(encoding="utf-8")

    for placeholder in (
        "{{old_suffix}}",
        "{{new_suffix}}",
        "{{ip}}",
        "{{user_agent}}",
        "{{ts_jst}}",
    ):
        assert placeholder in html, f"missing {placeholder} in key_rotated.html"
        assert placeholder in txt, f"missing {placeholder} in key_rotated.txt"

    # Subject line copy + operator entity ID must be present so the
    # rendered email survives a Postmark UI overwrite from the canonical
    # source.
    assert "API キーがローテーションされました" in html
    assert "API キーがローテーションされました" in txt
    assert "T8010001213708" in html
    assert "T8010001213708" in txt
    assert "info@bookyou.net" in html
    assert "info@bookyou.net" in txt


# ---------------------------------------------------------------------------
# Test-mode short-circuit
# ---------------------------------------------------------------------------


def test_test_mode_env_skips_http():
    """env == 'test' blocks the send even when a token is set."""
    captured: list[httpx.Request] = []
    client = PostmarkClient(
        api_token="test-token",
        from_transactional="no-reply@example.test",
        from_reply="hello@example.test",
        env="test",
        _http=_mock_http(captured),
    )
    resp = client.send_welcome(to="x@example.com", key_last4="0000", tier="paid")
    assert resp == {"skipped": True, "reason": "test_mode"}
    assert captured == []


def test_empty_token_skips_http():
    """An empty Postmark token no-ops even in prod env."""
    captured: list[httpx.Request] = []
    client = PostmarkClient(
        api_token="",
        from_transactional="no-reply@example.test",
        from_reply="hello@example.test",
        env="prod",
        _http=_mock_http(captured),
    )
    resp = client.send_welcome(to="x@example.com", key_last4="0000", tier="paid")
    assert resp == {"skipped": True, "reason": "test_mode"}
    assert captured == []


def test_api_error_does_not_raise():
    """Postmark 422 → structured error dict, no exception."""
    captured: list[httpx.Request] = []
    client = PostmarkClient(
        api_token="test-token",
        from_transactional="no-reply@example.test",
        from_reply="hello@example.test",
        env="prod",
        _http=_mock_http(captured, status_code=422, body={"ErrorCode": 406, "Message": "invalid"}),
    )
    resp = client.send_welcome(to="x@example.com", key_last4="9999", tier="paid")
    assert resp["error"] == "api"
    assert resp["status"] == 422
    # call was attempted
    assert len(captured) == 1


# ---------------------------------------------------------------------------
# get_client / reset_client
# ---------------------------------------------------------------------------


def test_get_client_is_singleton():
    pm_mod.reset_client()
    a = pm_mod.get_client()
    b = pm_mod.get_client()
    assert a is b
    pm_mod.reset_client()
    c = pm_mod.get_client()
    assert c is not a


# ---------------------------------------------------------------------------
# Webhook signature verification + suppression
# ---------------------------------------------------------------------------


WEBHOOK_SECRET = "test-webhook-secret-32chars-xxxx"


def _sign(body: bytes, secret: str = WEBHOOK_SECRET) -> str:
    mac = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()
    return base64.b64encode(mac).decode("ascii")


@pytest.fixture()
def webhook_client(client, monkeypatch):
    """Force the webhook secret on so the endpoint doesn't 503."""
    from jpintel_mcp.api import email_webhook as email_webhook_mod
    from jpintel_mcp.config import settings as _s

    for target in (_s, email_webhook_mod.settings):
        monkeypatch.setattr(target, "postmark_webhook_secret", WEBHOOK_SECRET, raising=False)
    return client


def _row_for(db: Path, email: str) -> sqlite3.Row | None:
    c = sqlite3.connect(db)
    c.row_factory = sqlite3.Row
    try:
        return c.execute(
            "SELECT email, source, unsubscribed_at FROM subscribers WHERE email = ?",
            (email,),
        ).fetchone()
    finally:
        c.close()


def test_webhook_hard_bounce_suppresses(webhook_client, seeded_db: Path):
    body = json.dumps(
        {
            "RecordType": "Bounce",
            "Type": "HardBounce",
            "Email": "bounce@example.com",
            "MessageID": "msg-1",
        }
    ).encode("utf-8")
    r = webhook_client.post(
        "/v1/email/webhook",
        content=body,
        headers={
            "X-Postmark-Signature": _sign(body),
            "Content-Type": "application/json",
        },
    )
    assert r.status_code == 200, r.text
    assert r.json() == {"status": "suppressed", "reason": "bounce"}

    row = _row_for(seeded_db, "bounce@example.com")
    assert row is not None
    assert row["unsubscribed_at"] is not None
    assert row["source"] == "suppress:bounce"


def test_webhook_spam_complaint_suppresses(webhook_client, seeded_db: Path):
    body = json.dumps(
        {
            "RecordType": "SpamComplaint",
            "Email": "spammer@example.com",
            "MessageID": "msg-2",
        }
    ).encode("utf-8")
    r = webhook_client.post(
        "/v1/email/webhook",
        content=body,
        headers={
            "X-Postmark-Signature": _sign(body),
            "Content-Type": "application/json",
        },
    )
    assert r.status_code == 200, r.text
    assert r.json() == {"status": "suppressed", "reason": "spam-complaint"}
    row = _row_for(seeded_db, "spammer@example.com")
    assert row is not None
    assert row["source"] == "suppress:spam-complaint"


def test_webhook_soft_bounce_not_suppressed(webhook_client, seeded_db: Path):
    body = json.dumps(
        {
            "RecordType": "Bounce",
            "Type": "Transient",
            "Email": "soft@example.com",
        }
    ).encode("utf-8")
    r = webhook_client.post(
        "/v1/email/webhook",
        content=body,
        headers={"X-Postmark-Signature": _sign(body)},
    )
    assert r.status_code == 200
    assert r.json()["reason"] == "soft-bounce"
    assert _row_for(seeded_db, "soft@example.com") is None


def test_webhook_invalid_signature_401(webhook_client):
    body = json.dumps({"RecordType": "Bounce", "Type": "HardBounce"}).encode("utf-8")
    r = webhook_client.post(
        "/v1/email/webhook",
        content=body,
        headers={"X-Postmark-Signature": "AAAA" * 12},
    )
    assert r.status_code == 401
    assert "invalid signature" in r.json().get("detail", "").lower()


def test_webhook_missing_signature_401(webhook_client):
    body = json.dumps({"RecordType": "Bounce", "Type": "HardBounce"}).encode("utf-8")
    r = webhook_client.post("/v1/email/webhook", content=body)
    assert r.status_code == 401


def test_webhook_rejects_oversize_content_length(webhook_client):
    """DoS hardening: Content-Length > 100 KB → 413 BEFORE reading body."""
    r = webhook_client.post(
        "/v1/email/webhook",
        content=b"{}",
        headers={
            "X-Postmark-Signature": "AAAA" * 12,
            "content-length": "2000000",
        },
    )
    assert r.status_code == 413
    detail = r.json().get("detail", {})
    assert detail.get("error") == "out_of_range"


def test_webhook_small_body_still_validates_signature(webhook_client):
    """Small body with content-length present passes guard, hits signature check."""
    body = json.dumps({"RecordType": "Bounce", "Type": "HardBounce"}).encode("utf-8")
    r = webhook_client.post(
        "/v1/email/webhook",
        content=body,
        headers={"X-Postmark-Signature": "AAAA" * 12},
    )
    # Small body (~50 bytes) far under 100 KB, bad signature → 401
    assert r.status_code == 401


def test_webhook_503_without_secret(client, monkeypatch):
    """With no secret configured, the endpoint refuses every request."""
    from jpintel_mcp.config import settings as _s

    monkeypatch.setattr(_s, "postmark_webhook_secret", "", raising=False)
    r = client.post(
        "/v1/email/webhook",
        content=b"{}",
        headers={"X-Postmark-Signature": "AAAA"},
    )
    assert r.status_code == 503


def test_webhook_idempotent_on_double_bounce(webhook_client, seeded_db: Path):
    """Same bounce arriving twice does not create duplicate subscribers rows."""
    body = json.dumps(
        {
            "RecordType": "Bounce",
            "Type": "HardBounce",
            "Email": "twice@example.com",
        }
    ).encode("utf-8")
    hdrs = {"X-Postmark-Signature": _sign(body)}
    r1 = webhook_client.post("/v1/email/webhook", content=body, headers=hdrs)
    r2 = webhook_client.post("/v1/email/webhook", content=body, headers=hdrs)
    assert r1.status_code == 200
    assert r2.status_code == 200

    c = sqlite3.connect(seeded_db)
    try:
        (n,) = c.execute(
            "SELECT COUNT(*) FROM subscribers WHERE email = ?", ("twice@example.com",)
        ).fetchone()
        assert n == 1
    finally:
        c.close()


def test_webhook_message_id_dedup(webhook_client, seeded_db: Path, monkeypatch):
    """Two webhook posts with the same MessageID: second short-circuits.

    Audit a9fd80e134b538a32 / migration 059. Postmark retries on transient
    failures and may even re-deliver after a 200 ack — without MessageID
    dedup, `_suppress` fires twice, which races against legitimate
    re-subscribes. We assert the dedup table holds exactly one row and the
    suppression side-effect (here counted via the `_suppress` call site)
    only ran once.
    """
    from jpintel_mcp.api import email_webhook as webhook_mod

    suppress_calls: list[tuple[str, str]] = []
    real_suppress = webhook_mod._suppress

    def _spy_suppress(conn, email, reason):  # type: ignore[no-untyped-def]
        suppress_calls.append((email, reason))
        real_suppress(conn, email, reason)

    monkeypatch.setattr(webhook_mod, "_suppress", _spy_suppress)

    body = json.dumps(
        {
            "RecordType": "Bounce",
            "Type": "HardBounce",
            "Email": "dedupe@example.com",
            "MessageID": "msg-dedupe-1",
        }
    ).encode("utf-8")
    hdrs = {"X-Postmark-Signature": _sign(body)}

    r1 = webhook_client.post("/v1/email/webhook", content=body, headers=hdrs)
    r2 = webhook_client.post("/v1/email/webhook", content=body, headers=hdrs)

    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r1.json() == {"status": "suppressed", "reason": "bounce"}
    assert r2.json() == {"status": "duplicate_ignored"}

    c = sqlite3.connect(seeded_db)
    try:
        (events_n,) = c.execute(
            "SELECT COUNT(*) FROM postmark_webhook_events WHERE message_id = ?",
            ("msg-dedupe-1",),
        ).fetchone()
        assert events_n == 1, f"expected 1 dedup row, got {events_n}"

        row = c.execute(
            "SELECT event_type, processed_at FROM postmark_webhook_events WHERE message_id = ?",
            ("msg-dedupe-1",),
        ).fetchone()
        assert row[0] == "Bounce"
        assert row[1] is not None  # processed_at filled by first call
    finally:
        c.close()

    # _suppress fired exactly once (second call short-circuited at the
    # IntegrityError dedup gate before reaching the suppression branch).
    assert suppress_calls == [("dedupe@example.com", "bounce")], suppress_calls
