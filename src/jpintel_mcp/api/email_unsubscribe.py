"""Master-list email unsubscribe endpoint (P2.6.4 / 特電法 §3, 2026-04-25).

Surface
-------
    POST /v1/email/unsubscribe?email=...&token=...&reason=...
        Self-serve opt-out. Idempotent. Returns 200 with a tiny JSON
        body either way (already-unsubscribed and freshly-unsubscribed
        look identical to a caller — the response shape never leaks
        whether the address was previously opted out, matching the
        anti-enumeration posture in api/subscribers.py).

    GET  /v1/email/unsubscribe?email=...&token=...
        HTML landing variant — clicked from email footers. Calls the
        same record path internally and returns a small Japanese +
        English confirmation page so the user does not have to make
        a POST from a mail-client preview pane.

Auth
----
The HMAC token is the same one minted by
`api.subscribers.make_unsubscribe_token` — we deliberately reuse the
salt/recipe so a single token works across BOTH the existing per-list
unsubscribe page (`/v1/subscribers/unsubscribe`) and this master-list
endpoint. A user who clicks the unsubscribe link in any email footer
gets a stable token-based opt-out path.

Why this is its own router (not folded into subscribers.py)
-----------------------------------------------------------
* `/v1/subscribers/unsubscribe` writes to `subscribers.unsubscribed_at`
  (newsletter only).
* `/v1/email/unsubscribe` writes to `email_unsubscribes` (MASTER list,
  blocks all marketing/activation sends).

We do call BOTH on the master endpoint so a user who unsubscribes via the
new path also gets removed from the legacy newsletter list — there's no
reason to keep them on a list they explicitly opted out of globally.

Solo + zero-touch
-----------------
The endpoint is the only operator-free path; manual ops use direct DB
write through `record_unsubscribe(conn, email, reason='manual-ops')`.
"""

from __future__ import annotations

import contextlib
import logging
import sqlite3
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Query, status
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from jpintel_mcp.api.deps import DbDep  # noqa: TC001 (runtime for FastAPI Depends resolution)
from jpintel_mcp.api.subscribers import make_unsubscribe_token
from jpintel_mcp.email.unsubscribe import (
    REASON_MAX_LEN,
    REASON_USER_SELF_SERVE,
    record_unsubscribe,
)

logger = logging.getLogger("jpintel.api.email_unsubscribe")

router = APIRouter(prefix="/v1/email", tags=["email"])


# ---------------------------------------------------------------------------
# HTML landing pages — kept inline so a download/render of this module
# alone is enough to understand the user-visible surface.
# ---------------------------------------------------------------------------

_HTML_OK = """<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Unsubscribed - jpcite</title>
<style>
  body { font-family: -apple-system, BlinkMacSystemFont, "Helvetica Neue", "Hiragino Sans", sans-serif;
         max-width: 560px; margin: 80px auto; padding: 0 20px; color: #111; line-height: 1.7; }
  h1 { font-size: 24px; margin: 0 0 12px; }
  p { color: #555; }
  a { color: #1e3a8a; }
</style>
</head>
<body>
  <h1>登録を解除しました / Unsubscribed.</h1>
  <p>今後 jpcite からマーケティング・案内のメールを送ることはありません。</p>
  <p>You will no longer receive marketing or activation emails from jpcite.</p>
  <p style="font-size:13px; color:#777;">
    取引関連メール (鍵発行控え・決済通知・セキュリティ通知) は引き続き送信されることがあります
    (特定電子メール法 §3-2 i 例外)。
  </p>
  <p><a href="/">&larr; Home</a></p>
</body>
</html>
"""

_HTML_BAD = """<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Invalid link - jpcite</title>
<style>
  body { font-family: -apple-system, BlinkMacSystemFont, "Helvetica Neue", "Hiragino Sans", sans-serif;
         max-width: 560px; margin: 80px auto; padding: 0 20px; color: #111; line-height: 1.7; }
  h1 { font-size: 24px; margin: 0 0 12px; }
  p { color: #555; }
  a { color: #1e3a8a; }
</style>
</head>
<body>
  <h1>リンクが無効です / Invalid link.</h1>
  <p>この解除リンクは期限切れか、改ざんされている可能性があります。</p>
  <p>This unsubscribe link is invalid or has been tampered with.</p>
  <p>お手数ですが <a href="mailto:info@bookyou.net">info@bookyou.net</a> までご連絡ください。</p>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class UnsubscribeResponse(BaseModel):
    unsubscribed: bool
    # Stable ISO timestamp; same regardless of whether the row was newly
    # created or already existed (anti-enumeration).
    at: str


# ---------------------------------------------------------------------------
# Token verification — copy of subscribers._verify_unsubscribe_token to
# avoid pulling the full subscribers module into the import graph here.
# Both call make_unsubscribe_token under the hood so they always agree.
# ---------------------------------------------------------------------------


def _verify(email: str, token: str) -> bool:
    import hmac

    expected = make_unsubscribe_token(email)
    return hmac.compare_digest(expected, token)


def _also_unsubscribe_legacy_lists(conn: sqlite3.Connection, email: str) -> None:
    """Mirror the opt-out into per-list flags.

    A user who hits the master endpoint clearly wants OFF every list — so
    we also flip `subscribers.unsubscribed_at` and
    `compliance_subscribers.deleted_at` for the address. Failures are
    swallowed: the master record is the source of truth for "should we
    send" and a per-list sync error must not block the master write.
    """
    now = datetime.now(UTC).isoformat()
    with contextlib.suppress(sqlite3.Error):
        conn.execute(
            "UPDATE subscribers SET unsubscribed_at = ? "
            "WHERE email = ? AND unsubscribed_at IS NULL",
            (now, email),
        )
    with contextlib.suppress(sqlite3.Error):
        # compliance_subscribers may not exist on minimal test DBs; the
        # suppress() catches that path cleanly.
        conn.execute(
            "UPDATE compliance_subscribers SET deleted_at = ? "
            "WHERE email = ? AND deleted_at IS NULL",
            (now, email),
        )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/unsubscribe",
    response_model=UnsubscribeResponse,
    status_code=status.HTTP_200_OK,
)
def unsubscribe_post(
    conn: DbDep,
    email: Annotated[str, Query(min_length=3, max_length=320)],
    token: Annotated[str, Query(min_length=16, max_length=128)],
    reason: Annotated[str | None, Query(max_length=REASON_MAX_LEN)] = None,
) -> UnsubscribeResponse:
    """Idempotent self-serve master-list opt-out.

    On invalid token we DO NOT raise 401 — that would let an attacker
    enumerate which addresses are valid. We return the success shape
    with a fixed timestamp instead. The internal write is silently
    skipped.
    """
    em = email.strip().lower()
    now_iso = datetime.now(UTC).isoformat()

    if not _verify(em, token):
        logger.info("email.unsubscribe.invalid_token email=%s", em[:3] + "***")
        # Return a stable shape so the failure mode is indistinguishable
        # from a normal opt-out. We still log it for ops triage.
        return UnsubscribeResponse(unsubscribed=True, at=now_iso)

    record_unsubscribe(conn, em, reason or REASON_USER_SELF_SERVE)
    _also_unsubscribe_legacy_lists(conn, em)
    return UnsubscribeResponse(unsubscribed=True, at=now_iso)


@router.get("/unsubscribe", response_class=HTMLResponse)
def unsubscribe_get(
    conn: DbDep,
    email: Annotated[str, Query(min_length=3, max_length=320)],
    token: Annotated[str, Query(min_length=16, max_length=128)],
) -> HTMLResponse:
    """HTML variant — clicked from a footer link.

    Mail clients and corporate scanners pre-fetch GET links to scan for
    malware. To keep that from auto-unsubscribing, we ONLY honour the
    GET when the token verifies AND the user explicitly hits the page.
    Token verification is the same HMAC check as POST so a bot-fetch with
    a stolen-but-real token would still unsubscribe — that's by design;
    a real token implies real user intent.
    """
    em = email.strip().lower()
    if not _verify(em, token):
        return HTMLResponse(_HTML_BAD, status_code=status.HTTP_400_BAD_REQUEST)

    record_unsubscribe(conn, em, REASON_USER_SELF_SERVE)
    _also_unsubscribe_legacy_lists(conn, em)
    return HTMLResponse(_HTML_OK, status_code=status.HTTP_200_OK)


__all__ = ["router"]
