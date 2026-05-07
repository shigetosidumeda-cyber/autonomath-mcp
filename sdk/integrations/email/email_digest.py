"""jpcite email digest cron.

A small, dependency-light job that:

  1. Loads each customer's saved searches (jpcite REST
     ``GET /v1/me/saved_searches``).
  2. Executes each saved search against the live jpcite REST API
     (``GET /v1/programs/search`` or whichever endpoint the search
     declares).
  3. Renders the aggregated results into an HTML + plain-text email
     using a Jinja2 template, then hands it off to a transport stub
     (SendGrid / Mailchimp / SES) for actual delivery.

The transport stubs are *real* HTTP request constructors but **never**
issue the request from this module. They return the prepared payload
plus the URL + headers so the customer can wire them into their own
provider via a one-line ``httpx.post(prepared.url, json=prepared.body, headers=prepared.headers)``.
This keeps the cron deterministic + auditable, lets the customer run
it locally for QA, and avoids us holding the customer's transport
secrets.

Operator: Bookyou株式会社 (適格請求書発行事業者番号 T8010001213708)
Brand:    jpcite (https://jpcite.com)
API:      https://api.jpcite.com (X-API-Key, ¥3/req metered)

Cost note
---------
Each saved search execution = 1 jpcite REST call = ¥3 (税込 ¥3.30).
A customer with 12 saved searches running monthly = ¥36/month.
A consultant fanning to 100 顧問先 × 4 saved searches monthly =
¥1,200/month. The transport stub itself adds zero markup; the
SendGrid / SES costs for the actual send are the customer's
responsibility on their plan.
"""

from __future__ import annotations

import dataclasses
import datetime as _dt
import logging
import os
import re
from collections.abc import Iterable, Mapping, MutableMapping, Sequence
from pathlib import Path
from typing import Any

import httpx
from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

logger = logging.getLogger("jpcite.email_digest")

# ---- module constants ------------------------------------------------------

JPCITE_API_BASE = os.environ.get("JPCITE_API_BASE", "https://api.jpcite.com")
USER_AGENT = "jpcite-email-digest/0.3.2"
TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
DEFAULT_TEMPLATE_HTML = "email_digest.html"
DEFAULT_TEMPLATE_TXT = "email_digest.txt"

# Public footer (one line — keeps the digest short for B2B inboxes).
FOOTER_TEXT = (
    "提供: Bookyou株式会社 (適格請求書発行事業者番号 T8010001213708) "
    "・ https://jpcite.com ・ ¥3/req metered (税込 ¥3.30)"
)


# ---- public dataclasses ----------------------------------------------------


@dataclasses.dataclass(frozen=True)
class SavedSearch:
    """One row out of `GET /v1/me/saved_searches` reduced to the columns
    this digest cares about."""

    id: str
    name: str
    endpoint: str
    params: Mapping[str, Any]


@dataclasses.dataclass(frozen=True)
class DigestSection:
    """Rendered block for one saved search."""

    saved_search: SavedSearch
    items: Sequence[Mapping[str, Any]]
    error_code: str | None = None


@dataclasses.dataclass(frozen=True)
class RenderedDigest:
    """A ready-to-send digest. Both HTML + plain-text bodies are produced."""

    subject: str
    html_body: str
    text_body: str
    sections: Sequence[DigestSection]


@dataclasses.dataclass(frozen=True)
class PreparedSend:
    """Result of a transport-stub call. The caller (or the customer's
    cron wrapper) issues the actual HTTPS POST."""

    transport: str
    url: str
    method: str
    headers: Mapping[str, str]
    body: Mapping[str, Any]


# ---- helpers ---------------------------------------------------------------


def _http_client(client: httpx.Client | None) -> tuple[httpx.Client, bool]:
    """Return ``(client, owned)``. If we own the client, the caller is
    responsible for closing it via ``with``-style usage."""
    if client is not None:
        return client, False
    return httpx.Client(), True


def _api_get(
    path: str,
    *,
    api_key: str,
    params: Mapping[str, Any] | None = None,
    client: httpx.Client | None = None,
    timeout_s: float = 15.0,
) -> Any:
    """Issue a single jpcite GET request. Returns parsed JSON or raises
    ``httpx.HTTPStatusError`` for non-2xx responses."""
    headers = {
        "X-API-Key": api_key,
        "Accept": "application/json",
        "User-Agent": USER_AGENT,
    }
    base = JPCITE_API_BASE.rstrip("/")
    url = f"{base}/{path.lstrip('/')}"
    cli, owned = _http_client(client)
    try:
        # Drop empty params for cleaner URLs in tests.
        clean = {k: v for k, v in (params or {}).items() if v not in (None, "")} or None
        res = cli.get(url, headers=headers, params=clean, timeout=timeout_s)
        res.raise_for_status()
        return res.json()
    finally:
        if owned:
            cli.close()


def fetch_saved_searches(
    *,
    api_key: str,
    client: httpx.Client | None = None,
) -> list[SavedSearch]:
    """Reduce `GET /v1/me/saved_searches` to ``SavedSearch`` rows."""
    payload = _api_get("/v1/me/saved_searches", api_key=api_key, client=client)
    if isinstance(payload, dict):
        rows = payload.get("results") or payload.get("items") or []
    elif isinstance(payload, list):
        rows = payload
    else:
        rows = []
    out: list[SavedSearch] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        sid = str(row.get("id") or row.get("saved_search_id") or "").strip()
        name = str(row.get("name") or row.get("title") or "").strip()
        endpoint = str(row.get("endpoint") or row.get("path") or "/v1/programs/search").strip()
        params = row.get("params") or row.get("query") or {}
        if not isinstance(params, Mapping):
            params = {}
        if not sid or not name:
            continue
        out.append(SavedSearch(id=sid, name=name, endpoint=endpoint, params=dict(params)))
    return out


def execute_saved_search(
    saved: SavedSearch,
    *,
    api_key: str,
    client: httpx.Client | None = None,
    limit: int = 10,
) -> DigestSection:
    """Run one saved search against jpcite REST and bundle the result."""
    params: MutableMapping[str, Any] = dict(saved.params)
    params.setdefault("limit", limit)
    try:
        payload = _api_get(saved.endpoint, api_key=api_key, params=params, client=client)
    except httpx.HTTPStatusError as e:
        status = e.response.status_code if e.response is not None else 0
        if status in (401, 403):
            return DigestSection(saved, [], "AUTH_ERROR")
        if status == 404:
            return DigestSection(saved, [], "NOT_FOUND")
        if status == 429:
            return DigestSection(saved, [], "RATE_LIMITED")
        return DigestSection(saved, [], f"HTTP_{status}")
    except httpx.HTTPError as e:
        logger.warning("jpcite digest: upstream HTTPError: %s", e)
        return DigestSection(saved, [], "NETWORK_ERROR")

    if isinstance(payload, dict):
        items = payload.get("results") or payload.get("items") or []
    elif isinstance(payload, list):
        items = payload
    else:
        items = []
    # Aggregator-ban defense: drop rows with neither source_url nor authority.
    cleaned = [
        row
        for row in items
        if isinstance(row, dict) and (row.get("source_url") or row.get("authority"))
    ]
    return DigestSection(saved, cleaned[:limit])


# ---- rendering -------------------------------------------------------------


def _build_jinja_env(template_dir: Path | None = None) -> Environment:
    return Environment(
        loader=FileSystemLoader(str(template_dir or TEMPLATE_DIR)),
        autoescape=select_autoescape(["html", "htm", "xml"]),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )


def render_digest(
    *,
    customer_name: str,
    sections: Sequence[DigestSection],
    generated_at: _dt.datetime | None = None,
    template_html: str = DEFAULT_TEMPLATE_HTML,
    template_txt: str = DEFAULT_TEMPLATE_TXT,
    template_dir: Path | None = None,
    unsubscribe_url: str = "https://jpcite.com/dashboard/saved-searches",
) -> RenderedDigest:
    env = _build_jinja_env(template_dir=template_dir)
    now = generated_at or _dt.datetime.now(_dt.UTC)
    context = {
        "customer_name": customer_name,
        "sections": sections,
        "generated_at": now,
        "footer_text": FOOTER_TEXT,
        "unsubscribe_url": unsubscribe_url,
        "summary_count": sum(len(s.items) for s in sections),
        "section_count": len(sections),
    }
    html_body = env.get_template(template_html).render(**context)
    text_body = env.get_template(template_txt).render(**context)
    subject = f"[jpcite] 月次サマリ — {now.strftime('%Y-%m')} ({customer_name})"
    return RenderedDigest(
        subject=subject,
        html_body=html_body,
        text_body=text_body,
        sections=sections,
    )


# ---- transport stubs -------------------------------------------------------


def _validate_email(addr: str) -> str:
    addr = (addr or "").strip()
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", addr):
        raise ValueError(f"invalid email: {addr!r}")
    return addr


def prepare_sendgrid_send(
    *,
    digest: RenderedDigest,
    to_email: str,
    from_email: str,
    api_key: str,
) -> PreparedSend:
    """Construct a SendGrid v3 ``/v3/mail/send`` payload. Does **not**
    issue the HTTPS POST."""
    to_email = _validate_email(to_email)
    from_email = _validate_email(from_email)
    if not api_key:
        raise ValueError("sendgrid api_key required")
    return PreparedSend(
        transport="sendgrid",
        url="https://api.sendgrid.com/v3/mail/send",
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        body={
            "personalizations": [{"to": [{"email": to_email}]}],
            "from": {"email": from_email, "name": "jpcite"},
            "subject": digest.subject,
            "content": [
                {"type": "text/plain", "value": digest.text_body},
                {"type": "text/html", "value": digest.html_body},
            ],
        },
    )


def prepare_ses_send(
    *,
    digest: RenderedDigest,
    to_email: str,
    from_email: str,
    region: str = "ap-northeast-1",
) -> PreparedSend:
    """Construct an SES v2 ``SendEmail`` payload (uses the data-plane
    JSON shape that ``aws-sigv4-requests`` / boto3 client.send_email
    expects). Does **not** issue the HTTPS POST."""
    to_email = _validate_email(to_email)
    from_email = _validate_email(from_email)
    return PreparedSend(
        transport="ses",
        url=f"https://email.{region}.amazonaws.com/v2/email/outbound-emails",
        method="POST",
        headers={
            "Content-Type": "application/json",
            # AWS SigV4 headers must be added by the customer's runtime.
            "X-Amz-Target": "SimpleEmailService_v2.SendEmail",
        },
        body={
            "FromEmailAddress": from_email,
            "Destination": {"ToAddresses": [to_email]},
            "Content": {
                "Simple": {
                    "Subject": {"Data": digest.subject, "Charset": "UTF-8"},
                    "Body": {
                        "Text": {"Data": digest.text_body, "Charset": "UTF-8"},
                        "Html": {"Data": digest.html_body, "Charset": "UTF-8"},
                    },
                }
            },
        },
    )


def prepare_mailchimp_send(
    *,
    digest: RenderedDigest,
    to_email: str,
    from_email: str,
    api_key: str,
) -> PreparedSend:
    """Construct a Mailchimp Transactional (Mandrill) ``/messages/send.json``
    payload. Does **not** issue the HTTPS POST."""
    to_email = _validate_email(to_email)
    from_email = _validate_email(from_email)
    if not api_key:
        raise ValueError("mailchimp api_key required")
    return PreparedSend(
        transport="mailchimp",
        url="https://mandrillapp.com/api/1.0/messages/send.json",
        method="POST",
        headers={"Content-Type": "application/json"},
        body={
            "key": api_key,
            "message": {
                "subject": digest.subject,
                "html": digest.html_body,
                "text": digest.text_body,
                "from_email": from_email,
                "from_name": "jpcite",
                "to": [{"email": to_email, "type": "to"}],
                "track_opens": False,
                "track_clicks": False,
            },
        },
    )


# ---- top-level cron entrypoint --------------------------------------------


def build_digest_for_customer(
    *,
    customer_name: str,
    api_key: str,
    client: httpx.Client | None = None,
    limit_per_search: int = 10,
    generated_at: _dt.datetime | None = None,
) -> RenderedDigest:
    """Single-call helper: list saved searches, run them, render."""
    saved_list = fetch_saved_searches(api_key=api_key, client=client)
    sections = [
        execute_saved_search(s, api_key=api_key, client=client, limit=limit_per_search)
        for s in saved_list
    ]
    return render_digest(
        customer_name=customer_name,
        sections=sections,
        generated_at=generated_at,
    )


def iter_recent_results(
    section: DigestSection,
    *,
    field: str = "name",
) -> Iterable[str]:
    """Convenience iterator used by simpler templates."""
    for row in section.items:
        v = row.get(field) or row.get("title") or row.get("primary_name")
        if isinstance(v, str) and v:
            yield v


if __name__ == "__main__":  # pragma: no cover
    logging.basicConfig(level=logging.INFO)
    api_key_env = os.environ.get("JPCITE_API_KEY", "")
    customer = os.environ.get("JPCITE_CUSTOMER_NAME", "テスト顧客")
    digest = build_digest_for_customer(customer_name=customer, api_key=api_key_env)
    # Print the prepared HTML body to stdout. The customer wraps this
    # script with their own SendGrid / SES / Mailchimp credentials.
    print(digest.subject)
    print()
    print(digest.text_body)
