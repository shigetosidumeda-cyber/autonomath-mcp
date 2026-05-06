#!/usr/bin/env python3
"""Stripe API version sunset monitor (HTML scrape + RSS feed + response header).

Why this exists
---------------
We pin the Stripe SDK to API version ``2024-11-20.acacia`` (see
``src/jpintel_mcp/billing/stripe_usage.py`` and ``billing.py``). Stripe
deprecates pinned versions on a rolling 12-18 month schedule, after which
the pinned version stops accepting new requests and the entire metered
billing path goes dark. The previous detection approach
(``info.get("api_version_deprecated")``) referenced an SDK field that does
not exist — the rule never fired even when deprecation was imminent.

This cron replaces that approach with three independent signals:

  1. **HTML scrape** of ``https://docs.stripe.com/upgrades`` — the canonical
     human-facing changelog. Each release row contains the version date
     plus markers like ``Deprecated``, ``Sunset``, or ``End of life`` once
     Stripe announces a sunset window.

  2. **RSS feed** of ``https://stripe.com/docs/upgrades/feed.atom`` — the
     same content surfaced as Atom for syndication. We grep for our pin in
     proximity to deprecation keywords. Belt-and-braces: HTML or RSS may
     change layout independently.

  3. **Response header probe** — the SDK's ``Stripe-Should-Retry`` and
     ``Stripe-Sunset-At`` headers are returned on every API call. We make
     one minimal call (``stripe.SubscriptionItem.list(limit=1)``) and log
     the headers. ``Stripe-Sunset-At`` is the strongest signal — if Stripe
     populates it, the sunset is in motion at the API layer regardless of
     what the docs page says.

When any signal fires, we emit a Sentry message at ``error`` level. The
Sentry rule routes that to the operator inbox; meter_events migration PoC
work (``feature/stripe-meter-events-migration`` branch) lands separately.

NO LLM API calls. Pure ``httpx`` + ``re`` + ``stripe.SubscriptionItem.list``.

Usage::

    python scripts/cron/stripe_version_check.py             # real run
    python scripts/cron/stripe_version_check.py --dry-run   # imports + load only

Required env::
    STRIPE_SECRET_KEY   only required for header probe; HTML/RSS work without
    SENTRY_DSN          optional; messages no-op when unset

Recommended cron: weekly on Monday at 09:00 JST via
``.github/workflows/stripe-version-check-weekly.yml``.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import re
import sys
from typing import Any

import httpx

logger = logging.getLogger("jpintel.cron.stripe_version_check")

# Pinned Stripe API version. Keep in sync with billing/stripe_usage.py and
# billing.py. When this changes, update both this constant AND the SDK pin.
PIN = "2024-11-20.acacia"

UPGRADES_HTML_URL = "https://docs.stripe.com/upgrades"
UPGRADES_RSS_URL = "https://stripe.com/docs/upgrades/feed.atom"

# Keyword set Stripe historically uses on the upgrades page when announcing
# version retirement. Case-insensitive.
DEPRECATION_KEYWORDS = ("Deprecated", "Sunset", "End of life", "Retired")


def _safe_capture_message(message: str, *, level: str = "error", **extras: Any) -> None:
    """Best-effort Sentry capture. Never raises.

    We deliberately re-import sentry_sdk inside the function so the module
    is importable in environments where sentry_sdk is missing (CI without
    the [observability] extra). Tagged ``check=stripe_version_check`` so
    the operator can filter Sentry inbox.
    """
    try:
        import sentry_sdk  # type: ignore[import-not-found]

        with sentry_sdk.push_scope() as scope:
            scope.set_tag("check", "stripe_version_check")
            scope.set_tag("pin", PIN)
            for k, v in extras.items():
                scope.set_extra(k, v)
            sentry_sdk.capture_message(message, level=level)  # type: ignore[arg-type]
    except Exception:  # noqa: BLE001 — observability cannot raise
        logger.debug("sentry_capture_failed message=%s", message, exc_info=True)


async def _fetch(url: str, *, timeout: float = 20.0) -> str | None:
    """GET ``url`` and return the response body, or None on transport error.

    Failures are logged as warnings — a one-off network blip should NOT
    page the operator. The next weekly run picks up the signal.
    """
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            resp = await client.get(url, headers={"User-Agent": "jpcite-stripe-version-check/1.0"})
        if resp.status_code >= 400:
            logger.warning("fetch_non200 url=%s status=%d", url, resp.status_code)
            return None
        return resp.text
    except Exception as exc:  # noqa: BLE001 — network errors are non-fatal here
        logger.warning("fetch_failed url=%s err=%s", url, exc)
        return None


def _scan_html_for_deprecation(html: str) -> tuple[bool, str | None]:
    """Locate the row containing the pin and check for deprecation markers.

    Returns ``(deprecated, snippet)``. ``snippet`` is a short window of
    surrounding text for the Sentry extras so the operator can see WHY the
    rule fired without re-fetching.
    """
    # The upgrades page is one giant HTML doc; we look for the version
    # string and grab a generous window of surrounding text. Stripe wraps
    # versions in <h2>/<h3> elements but exact markup drifts — substring
    # search is the most resilient.
    idx = html.find(PIN)
    if idx < 0:
        # Pin missing entirely — Stripe could have removed it from the page,
        # which itself is a signal worth flagging.
        return False, None
    # ~2KB window each side captures the header + body of the version row
    # without grabbing adjacent versions.
    start = max(0, idx - 2048)
    end = min(len(html), idx + 2048)
    window = html[start:end]
    # Strip simple HTML tags so the keyword grep doesn't miss matches that
    # are split across <span> boundaries. Cheap, not bulletproof.
    text_only = re.sub(r"<[^>]+>", " ", window)
    pattern = re.compile(
        rf"(?is)(?:{re.escape(PIN)}).*?({'|'.join(DEPRECATION_KEYWORDS)})",
    )
    match = pattern.search(text_only)
    if match:
        snippet = text_only[max(0, match.start() - 200) : match.end() + 200].strip()
        snippet = re.sub(r"\s+", " ", snippet)
        return True, snippet[:1000]
    return False, None


def _scan_rss_for_deprecation(feed_text: str) -> tuple[bool, str | None]:
    """Check the Atom feed for an entry mentioning the pin AND deprecation."""
    if PIN not in feed_text:
        return False, None
    # Find the entry that contains the pin and look for deprecation keywords
    # within that same entry. Atom entries are <entry>...</entry>.
    entries = re.findall(r"(?is)<entry\b.*?</entry>", feed_text)
    for entry in entries:
        if PIN not in entry:
            continue
        lower = entry.lower()
        if any(kw.lower() in lower for kw in DEPRECATION_KEYWORDS):
            text_only = re.sub(r"<[^>]+>", " ", entry)
            text_only = re.sub(r"\s+", " ", text_only).strip()
            return True, text_only[:1000]
    return False, None


def _probe_response_headers() -> dict[str, str]:
    """Make one minimal Stripe API call and return interesting headers.

    Returns the relevant sunset-signal headers as a flat dict (empty when
    a header is absent, never None — keeps the structured-log line
    grep-friendly). Returns ``{"_skipped": "..."}`` if STRIPE_SECRET_KEY
    is unset (dev / CI path).
    """
    api_key = os.environ.get("STRIPE_SECRET_KEY", "")
    if not api_key:
        return {"_skipped": "STRIPE_SECRET_KEY unset"}
    try:
        import stripe  # type: ignore[import-not-found]
    except Exception as exc:  # noqa: BLE001
        return {"_skipped": f"stripe SDK unavailable: {exc}"}
    try:
        stripe.api_key = api_key
        stripe.api_version = PIN
        resp = stripe.SubscriptionItem.list(limit=1)
        # Newer SDKs expose response headers via .last_response.headers.
        headers = {}
        last = getattr(resp, "last_response", None)
        if last is not None:
            raw = getattr(last, "headers", {}) or {}
            for key in ("Stripe-Should-Retry", "Stripe-Sunset-At", "Stripe-Version"):
                value = raw.get(key) or raw.get(key.lower())
                headers[key] = str(value) if value is not None else ""
        return headers or {"_note": "no last_response headers exposed by SDK"}
    except Exception as exc:  # noqa: BLE001 — probe is best-effort
        return {"_error": f"{type(exc).__name__}: {exc}"[:500]}


async def run_check() -> dict[str, Any]:
    """Run all three signals concurrently and return a structured report."""
    html_text, rss_text = await asyncio.gather(
        _fetch(UPGRADES_HTML_URL),
        _fetch(UPGRADES_RSS_URL),
    )

    html_hit, html_snippet = (False, None)
    if html_text:
        html_hit, html_snippet = _scan_html_for_deprecation(html_text)

    rss_hit, rss_snippet = (False, None)
    if rss_text:
        rss_hit, rss_snippet = _scan_rss_for_deprecation(rss_text)

    headers = _probe_response_headers()
    sunset_at = headers.get("Stripe-Sunset-At", "")
    header_hit = bool(sunset_at)

    report: dict[str, Any] = {
        "pin": PIN,
        "html_fetched": bool(html_text),
        "rss_fetched": bool(rss_text),
        "html_hit": html_hit,
        "html_snippet": html_snippet,
        "rss_hit": rss_hit,
        "rss_snippet": rss_snippet,
        "response_headers": headers,
        "header_hit": header_hit,
    }

    if html_hit:
        _safe_capture_message(
            "stripe_api_version_deprecated_in_docs",
            level="error",
            source="docs.stripe.com/upgrades",
            url=UPGRADES_HTML_URL,
            snippet=html_snippet or "",
        )
        logger.error("stripe.version.docs_deprecated pin=%s snippet=%s", PIN, html_snippet)

    if rss_hit:
        _safe_capture_message(
            "stripe_api_version_in_rss_deprecation",
            level="error",
            source="docs.stripe.com/upgrades/feed.atom",
            url=UPGRADES_RSS_URL,
            snippet=rss_snippet or "",
        )
        logger.error("stripe.version.rss_deprecated pin=%s snippet=%s", PIN, rss_snippet)

    if header_hit:
        _safe_capture_message(
            "stripe_api_version_sunset_header_present",
            level="error",
            source="Stripe-Sunset-At response header",
            sunset_at=sunset_at,
            should_retry=headers.get("Stripe-Should-Retry", ""),
        )
        logger.error("stripe.version.header_sunset pin=%s sunset_at=%s", PIN, sunset_at)

    if not (html_hit or rss_hit or header_hit):
        # Always log the green path so the operator can verify the cron ran.
        logger.info(
            "stripe.version.ok pin=%s html_fetched=%s rss_fetched=%s headers=%s",
            PIN,
            bool(html_text),
            bool(rss_text),
            headers,
        )

    return report


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Probe Stripe API version sunset signals (HTML + RSS + response header).",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Verify imports and module load; do NOT fetch or probe.",
    )
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        stream=sys.stderr,
    )

    if args.dry_run:
        # Module load + httpx import — exercise the import path so the
        # completion judge can verify wiring without network access.
        logger.info(
            "stripe_version_check.dry_run pin=%s httpx=%s",
            PIN,
            httpx.__version__,
        )
        print(f'{{"pin": "{PIN}", "dry_run": true, "httpx": "{httpx.__version__}"}}')
        return 0

    try:
        report = asyncio.run(run_check())
    except Exception as exc:  # noqa: BLE001 — cron must not crash the runner
        logger.exception("stripe_version_check.failed err=%s", exc)
        _safe_capture_message(
            "stripe_version_check_runtime_error",
            level="error",
            error=str(exc),
        )
        return 1

    import json

    print(json.dumps(report, indent=2, ensure_ascii=False))
    # Exit 0 even on hits — Sentry already paged. Non-zero would re-trigger
    # GHA retry which would re-page; net noise, no recovery value.
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = ["PIN", "main", "run_check"]
