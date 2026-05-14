"""Render + scheduler-wiring tests for the D+0 and D+1 onboarding templates.

These tests exist because the D+0 / D+1 templates were added after the
D+3 / D+7 / D+14 / D+30 sequence (audit flagged the gap). They guard:

  * On-disk template files render with sample context (no unresolved
    `{{...}}` placeholders, all required variables substituted).
  * The scheduler enqueues D+1 at key-issue time — D+0 is fired
    synchronously from `api/billing.py::_send_welcome_safe` and must NOT
    appear in the cron queue.
  * The D+1 template carries a machine-readable unsubscribe URL (APPI /
    CAN-SPAM equivalent) — the only CRM mail in the pair; D+0 is a
    transactional receipt and is exempt.

The template files we render here are Postmark-server-side templates
using Handlebars-ish syntax (`{{var}}`, `{{#if}}`, `{{{pm:unsubscribe}}}`).
We approximate Postmark's substitution locally with a regex-based
renderer that only replaces `{{simple_var}}` references and leaves the
`{{#if}}` / `{{{pm:...}}}` markup in place — that is enough to verify
that EVERY variable the code-side helpers hand in actually has a
matching placeholder in the file.
"""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from jpintel_mcp.db.session import init_db
from jpintel_mcp.email.onboarding import (
    TEMPLATE_DAY0,
    TEMPLATE_DAY1,
    send_day0_welcome,
    send_day1_quick_win,
)
from jpintel_mcp.email.postmark import POSTMARK_BASE_URL, PostmarkClient
from jpintel_mcp.email.scheduler import (
    ALL_KINDS,
    enqueue_onboarding_sequence,
)

TEMPLATES_DIR = (
    Path(__file__).resolve().parent.parent / "src" / "jpintel_mcp" / "email" / "templates"
)

_STALE_USER_FACING_COPY = (
    "AutonoMath",
    "税務会計AI",
    "50 req/月",
    "50/月",
    "69 MCP",
    "AUTONOMATH_API_KEY",
    "@autonomath/mcp",
    "npx -y",
    "Free 枠 (1日 100 リクエスト上限)",
    "1日 100 リクエスト上限",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_SIMPLE_VAR = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")


def _render(template: str, context: dict[str, object]) -> str:
    """Replace `{{simple_var}}` occurrences with the context value.

    Leaves `{{#if ...}}`, `{{/if}}`, `{{{pm:unsubscribe}}}` etc. alone —
    those are Postmark-server-side directives that a local smoke test
    should NOT try to resolve. Unknown simple vars are left untouched so
    the test assertion about "no un-substituted placeholders" catches
    drift between template markup and code-side TemplateModel keys.
    """

    def _sub(m: re.Match[str]) -> str:
        name = m.group(1)
        if name in context:
            return str(context[name])
        return m.group(0)

    return _SIMPLE_VAR.sub(_sub, template)


def _read(name: str) -> str:
    return (TEMPLATES_DIR / name).read_text(encoding="utf-8")


def _mock_client(captured: list[httpx.Request]) -> PostmarkClient:
    def _handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"MessageID": "stub-1", "ErrorCode": 0})

    http = httpx.Client(
        base_url=POSTMARK_BASE_URL,
        transport=httpx.MockTransport(_handler),
        headers={"X-Postmark-Server-Token": "test-token"},
    )
    return PostmarkClient(
        api_token="test-token",
        from_transactional="no-reply@example.test",
        from_reply="hello@example.test",
        env="prod",
        _http=http,
    )


def test_email_templates_use_current_public_copy() -> None:
    """Outbound emails must not regress to old brand/quota/MCP install copy."""
    failures: list[str] = []
    for path in sorted(TEMPLATES_DIR.iterdir()):
        if not path.is_file():
            continue
        body = path.read_text(encoding="utf-8")
        for needle in _STALE_USER_FACING_COPY:
            if needle in body:
                failures.append(f"{path.name}: {needle}")

    assert failures == []


@pytest.fixture()
def conn(tmp_path: Path) -> sqlite3.Connection:
    db_path = tmp_path / "templates.db"
    init_db(db_path)
    c = sqlite3.connect(db_path, isolation_level=None)
    c.row_factory = sqlite3.Row
    c.execute(
        """INSERT INTO api_keys(key_hash, customer_id, tier, stripe_subscription_id, created_at)
           VALUES (?, ?, ?, ?, ?)""",
        ("hash_abcd1234", "cus_test", "paid", "sub_t", "2026-04-23T00:00:00+00:00"),
    )
    try:
        yield c
    finally:
        c.close()


# ---------------------------------------------------------------------------
# Template-render smoke tests
# ---------------------------------------------------------------------------


def test_day0_template_renders():
    """D+0 HTML + TXT render with {email, api_key, tier, key_last4} context."""
    ctx = {
        "email": "alice@example.com",
        "api_key": "am_live_abcdefg1234567890",
        "tier": "paid",
        "key_last4": "7890",
    }
    for fname in ("onboarding_day0.html", "onboarding_day0.txt"):
        rendered = _render(_read(fname), ctx)
        # Required substitutions present.
        assert ctx["email"] in rendered, f"{fname}: email missing"
        assert ctx["api_key"] in rendered, f"{fname}: api_key missing"
        assert ctx["tier"] in rendered, f"{fname}: tier missing"
        # No un-substituted simple-variable placeholders left behind.
        leftovers = _SIMPLE_VAR.findall(rendered)
        assert leftovers == [], f"{fname}: unresolved placeholders {leftovers}"
        # Legal-entity footer is load-bearing for non-marketing compliance.
        assert "Bookyou" in rendered
        assert "T8010001213708" in rendered


def test_day1_template_renders():
    """D+1 HTML + TXT render with code-side helper context."""
    ctx = {
        "key_last4": "wxyz",
        "tier": "paid",
        "usage_count": 0,
        # D+1 carries a machine unsubscribe URL. We substitute a concrete
        # value here to prove the placeholder is wired up; in production
        # Postmark's `{{{pm:unsubscribe}}}` is the default and is resolved
        # server-side.
        "unsubscribe_url": "https://autonomath.ai/u/t0k3n",
    }
    for fname in ("onboarding_day1.html", "onboarding_day1.txt"):
        rendered = _render(_read(fname), ctx)
        assert ctx["key_last4"] in rendered, f"{fname}: key_last4 missing"
        assert ctx["tier"] in rendered, f"{fname}: tier missing"
        assert ctx["unsubscribe_url"] in rendered, f"{fname}: unsubscribe_url missing"
        leftovers = _SIMPLE_VAR.findall(rendered)
        assert leftovers == [], f"{fname}: unresolved placeholders {leftovers}"
        assert "Bookyou" in rendered
        assert "T8010001213708" in rendered


def test_unsubscribe_url_present_in_day1():
    """APPI / CAN-SPAM compliance: D+1 MUST carry an unsubscribe path.

    The template must reference `{{unsubscribe_url}}` (code-driven token)
    so the scheduler can substitute Postmark's built-in
    `{{{pm:unsubscribe}}}` at send time. We check both the on-disk
    template and the payload the helper hands to Postmark.
    """
    # Template file references the placeholder.
    for fname in ("onboarding_day1.html", "onboarding_day1.txt"):
        raw = _read(fname)
        assert "{{unsubscribe_url}}" in raw, f"{fname}: unsubscribe_url placeholder missing"
        # Sanity: D+0 is transactional (receipt) and intentionally does NOT
        # include an unsubscribe placeholder. Guards against accidental copy.
    for fname in ("onboarding_day0.html", "onboarding_day0.txt"):
        raw = _read(fname)
        assert "{{unsubscribe_url}}" not in raw, (
            f"{fname}: transactional receipt should not have unsubscribe_url"
        )

    # Code-side helper includes unsubscribe_url in the TemplateModel so
    # the Postmark server-side render can resolve it.
    captured: list[httpx.Request] = []
    send_day1_quick_win(
        to="alice@example.com",
        api_key_last4="wxyz",
        tier="paid",
        usage_count=0,
        client=_mock_client(captured),
    )
    assert len(captured) == 1
    body = json.loads(captured[0].content)
    model = body["TemplateModel"]
    assert "unsubscribe_url" in model
    # Default is Postmark's built-in placeholder; callers may override.
    assert model["unsubscribe_url"] == "{{{pm:unsubscribe}}}"
    assert body["TemplateAlias"] == TEMPLATE_DAY1
    assert body["Tag"] == "onboarding-day1"


# ---------------------------------------------------------------------------
# Scheduler wiring — key_issued triggers both paths
# ---------------------------------------------------------------------------


def test_day0_and_day1_scheduled_after_key_issue(conn: sqlite3.Connection):
    """On `key_issued` (the synchronous path in billing.py), D+0 is sent
    immediately via `send_day0_welcome` and D+1 is enqueued into
    `email_schedule` for the cron. D+0 is NOT an email_schedule row.

    This test mocks both halves: the synchronous D+0 send (via the
    PostmarkClient mock transport) and the scheduler enqueue.
    """
    base = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)

    # 1) Synchronous D+0 path — simulates what billing._send_welcome_safe does.
    captured: list[httpx.Request] = []
    send_day0_welcome(
        to="alice@example.com",
        api_key="am_live_rawkey1234",
        tier="paid",
        client=_mock_client(captured),
    )
    assert len(captured) == 1
    d0_body = json.loads(captured[0].content)
    assert d0_body["TemplateAlias"] == TEMPLATE_DAY0
    assert d0_body["TemplateModel"]["api_key"] == "am_live_rawkey1234"
    assert d0_body["TemplateModel"]["email"] == "alice@example.com"

    # 2) Scheduler enqueue — D+1 goes into email_schedule, D+0 does NOT.
    inserted = enqueue_onboarding_sequence(
        conn,
        api_key_id="hash_abcd1234",
        email="alice@example.com",
        now=base,
    )
    assert "day1" in inserted
    assert "day0" not in inserted
    assert set(inserted) == set(ALL_KINDS)

    rows = conn.execute(
        "SELECT kind, send_at FROM email_schedule WHERE api_key_id = ?",
        ("hash_abcd1234",),
    ).fetchall()
    kinds = {r["kind"] for r in rows}
    assert "day1" in kinds, "D+1 row missing from email_schedule"
    assert "day0" not in kinds, (
        "D+0 must NOT be scheduled — it is delivered synchronously from billing"
    )

    # D+1 send_at is base + 1 day.
    day1_row = next(r for r in rows if r["kind"] == "day1")
    assert day1_row["send_at"] == (base + timedelta(days=1)).isoformat()
