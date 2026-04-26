"""Transactional email layer (Postmark).

Entry points:
    - `PostmarkClient`: thin httpx wrapper around Postmark's REST API.
    - `get_client()`: process-wide singleton used by routers so tests can
      `monkeypatch.setattr(jpintel_mcp.email, "_client", fake)` without
      reaching into route modules.

Design notes:
    - No SDK. Postmark's Python SDK pulls in `requests` + extras we do not
      want in the runtime image; the REST surface is small enough for httpx.
    - The layer NEVER raises on send failure. Email is best-effort — a down
      Postmark must not take the /v1/billing/webhook endpoint with it.
    - Test-mode gating (empty token or `settings.env == "test"`) is checked
      inside `PostmarkClient._send`, so every send method benefits without
      duplicated guards.

See `docs/email_setup.md` for DNS / sender signature / suppression-list
wiring.
"""

from __future__ import annotations

from jpintel_mcp.email.onboarding import (
    send_day0_welcome,
    send_day1_quick_win,
    send_day3_activation,
    send_day7_value,
    send_day14_inactive_reminder,
    send_day30_feedback,
)
from jpintel_mcp.email.postmark import PostmarkClient, get_client

__all__ = [
    "PostmarkClient",
    "get_client",
    "send_day0_welcome",
    "send_day1_quick_win",
    "send_day3_activation",
    "send_day7_value",
    "send_day14_inactive_reminder",
    "send_day30_feedback",
]
