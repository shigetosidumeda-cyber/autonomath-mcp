#!/usr/bin/env python3
"""Daily amendment alert fan-out (Tier 3 P5-ι++ / dd_v8_08 H/I).

What it does:
  1. Reads new rows from autonomath.db `am_amendment_snapshot` (observed_at
     since last successful run, default = last 24h).
  2. For each amendment, infers severity (critical / important / info) from
     the diff against the previous version (effective_until newly set =>
     critical; amount/rate/target changed => important; else info).
  3. Loads matching subscriptions from jpintel.db `alert_subscriptions`
     (active=1, severity rank >= row.min_severity, filter matches the
     amendment).
  4. Posts to webhook_url via httpx.post (HTTPS-only, RFC1918 hosts blocked,
     30s timeout, 1 retry on 5xx / network error).
  5. Sends email via Postmark (template alias: 'amendment-alert') when set.
  6. Updates `last_triggered` on every subscription that fired.

Constraints:
  * No Anthropic / claude / SDK calls — pure SQL + httpx.
  * Rate limit: same webhook_url is capped at 60 req/minute (in-memory
    sliding window inside the run; cross-run cap is implicit because the
    cron itself runs once per day).
  * Cost: subscription is FREE (no usage_event / Stripe usage record on
    fan-out). project_autonomath_business_model keeps ¥3/req immutable.

Usage:
    python scripts/cron/amendment_alert.py            # real run
    python scripts/cron/amendment_alert.py --dry-run  # no webhook / no email
    python scripts/cron/amendment_alert.py --since 2026-04-20T00:00:00+00:00
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import logging
import socket
import sqlite3
import sys
import time
from collections import defaultdict, deque
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

# Allow running as a script without `pip install -e .`.
_REPO = Path(__file__).resolve().parent.parent.parent
_SRC = _REPO / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from jpintel_mcp.api.alerts import SEVERITY_RANK  # noqa: E402
from jpintel_mcp.config import settings  # noqa: E402
from jpintel_mcp.db.session import connect  # noqa: E402
from jpintel_mcp.observability import heartbeat  # noqa: E402

logger = logging.getLogger("autonomath.cron.amendment_alert")


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_HTTPX_TIMEOUT = httpx.Timeout(30.0, connect=10.0)
_WEBHOOK_RATE_WINDOW_SECONDS = 60
_WEBHOOK_RATE_MAX = 60  # 60 req/min cap per webhook_url


# ---------------------------------------------------------------------------
# Severity inference
# ---------------------------------------------------------------------------


def _infer_severity(curr: sqlite3.Row, prev: sqlite3.Row | None) -> str:
    """Return 'critical' / 'important' / 'info' for an amendment row.

    Heuristics (deterministic, no ML):
      * critical:
          - effective_until newly populated (制度終了)
          - eligibility_hash flipped AND prev had no effective_until
            (i.e. the gate text just changed under callers' feet)
      * important:
          - amount_max_yen changed (any direction)
          - subsidy_rate_max changed
          - target_set_json changed
      * info:
          - everything else (notes / source URL re-fetch / cosmetic)
    """
    if prev is None:
        # First-ever snapshot of this entity. We have no diff baseline, so
        # treat it as 'info' — a brand-new program is not an amendment of
        # any existing customer's book unless a separate ingest path
        # promotes it elsewhere.
        return "info"

    curr_until = curr["effective_until"]
    prev_until = prev["effective_until"]
    if curr_until and not prev_until:
        return "critical"

    curr_elig = curr["eligibility_hash"]
    prev_elig = prev["eligibility_hash"]
    if curr_elig != prev_elig and not prev_until:
        return "critical"

    if curr["amount_max_yen"] != prev["amount_max_yen"]:
        return "important"
    if curr["subsidy_rate_max"] != prev["subsidy_rate_max"]:
        return "important"
    if curr["target_set_json"] != prev["target_set_json"]:
        return "important"

    return "info"


# ---------------------------------------------------------------------------
# Webhook URL re-validation (DNS rebinding / late-blind)
# ---------------------------------------------------------------------------


def _is_safe_webhook(url: str) -> tuple[bool, str | None]:
    """Re-check at fire-time. Returns (ok, reason_if_not_ok)."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return False, "url_unparseable"
    if parsed.scheme.lower() != "https":
        return False, "scheme_not_https"
    host = (parsed.hostname or "").strip("[]").lower()
    if not host:
        return False, "no_host"
    # Literal-IP check first.
    try:
        ip = ipaddress.ip_address(host)
        if (
            ip.is_loopback
            or ip.is_private
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            return False, "internal_ip_literal"
        return True, None
    except ValueError:
        pass
    # DNS resolution check — block if the hostname maps to a private IP.
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False, "dns_failed"
    for info in infos:
        sockaddr = info[4]
        addr = sockaddr[0]
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            continue
        if (
            ip.is_loopback
            or ip.is_private
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            return False, "internal_ip_resolved"
    return True, None


# ---------------------------------------------------------------------------
# Per-webhook-URL rate limiter (in-memory, single run)
# ---------------------------------------------------------------------------


class _WebhookRateLimiter:
    """60 req / 60s sliding window keyed by webhook_url.

    A single cron invocation might have many subscriptions pointing at the
    same webhook. Limiter sleeps to stay under the cap rather than dropping
    events — these are real change notifications, not spam.
    """

    def __init__(
        self,
        max_per_window: int = _WEBHOOK_RATE_MAX,
        window_seconds: int = _WEBHOOK_RATE_WINDOW_SECONDS,
    ) -> None:
        self._max = max_per_window
        self._window = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def acquire(self, url: str) -> None:
        now = time.monotonic()
        cutoff = now - self._window
        bucket = self._hits[url]
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        if len(bucket) >= self._max:
            sleep_for = self._window - (now - bucket[0])
            if sleep_for > 0:
                logger.info(
                    "webhook_rate_limit_sleep url_host=%s sleep_s=%.2f",
                    urlparse(url).hostname,
                    sleep_for,
                )
                time.sleep(sleep_for)
                now = time.monotonic()
                cutoff = now - self._window
                while bucket and bucket[0] < cutoff:
                    bucket.popleft()
        bucket.append(now)


# ---------------------------------------------------------------------------
# Webhook + email send
# ---------------------------------------------------------------------------


def _post_webhook(
    *,
    client: httpx.Client,
    url: str,
    payload: dict[str, Any],
    dry_run: bool,
) -> dict[str, Any]:
    """POST JSON to the webhook with 1 retry on 5xx / network error.

    Returns a structured outcome dict (`ok`, optional `status` / `error`).
    NEVER raises — webhook failure is logged but does not abort the cron.
    """
    if dry_run:
        logger.info(
            "webhook.dry_run url_host=%s entity=%s",
            urlparse(url).hostname,
            payload.get("entity_id"),
        )
        return {"ok": True, "skipped": "dry_run"}

    safe, reason = _is_safe_webhook(url)
    if not safe:
        logger.warning("webhook.unsafe url_host=%s reason=%s", urlparse(url).hostname, reason)
        return {"ok": False, "error": "unsafe_target", "reason": reason}

    last_exc: Exception | None = None
    for attempt in (1, 2):
        try:
            r = client.post(url, json=payload, timeout=_HTTPX_TIMEOUT)
            if r.status_code < 500:
                return {"ok": r.is_success, "status": r.status_code}
            # 5xx — retry once.
            logger.info(
                "webhook.5xx url_host=%s status=%d attempt=%d",
                urlparse(url).hostname,
                r.status_code,
                attempt,
            )
        except httpx.HTTPError as exc:
            last_exc = exc
            logger.info(
                "webhook.transport_error url_host=%s err=%s attempt=%d",
                urlparse(url).hostname,
                exc,
                attempt,
            )
        if attempt == 1:
            time.sleep(2.0)  # brief backoff before retry
    return {
        "ok": False,
        "error": "exhausted",
        "detail": str(last_exc) if last_exc else "5xx after retry",
    }


def _send_alert_email(
    *,
    to: str,
    payload: dict[str, Any],
    dry_run: bool,
) -> dict[str, Any]:
    if dry_run:
        logger.info(
            "email.dry_run to_domain=%s entity=%s",
            to.split("@", 1)[-1] if "@" in to else "***",
            payload.get("entity_id"),
        )
        return {"skipped": True, "reason": "dry_run"}
    try:
        from jpintel_mcp.email import get_client  # local import
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("email.unavailable err=%s", exc)
        return {"skipped": True, "reason": "email_module_unavailable"}
    try:
        client = get_client()
        return client._send(  # type: ignore[attr-defined]
            to=to,
            template_alias="amendment-alert",
            template_model=payload,
            tag="amendment-alert",
        )
    except Exception as exc:
        logger.warning("email.send_failed err=%s", exc)
        return {"skipped": True, "reason": "send_failed", "error": str(exc)}


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------


def _amendment_matches(amendment: dict[str, Any], sub: sqlite3.Row) -> bool:
    """Return True when this subscription should fire on this amendment.

    Severity gating is enforced in the caller; this fn is structural-match
    only (filter_type / filter_value).
    """
    ftype = sub["filter_type"]
    fvalue = sub["filter_value"]
    if ftype == "all":
        return True
    if ftype == "program_id":
        return amendment.get("entity_id") == fvalue
    if ftype == "law_id":
        return amendment.get("law_id") == fvalue or fvalue in (amendment.get("law_refs") or [])
    if ftype == "tool":
        return fvalue in (amendment.get("tools") or [])
    if ftype == "industry_jsic":
        return fvalue in (amendment.get("industries") or [])
    return False


# ---------------------------------------------------------------------------
# Snapshot enrichment (best effort: pull tools/industries/laws from raw_json)
# ---------------------------------------------------------------------------


def _enrich_amendment(
    am_conn: sqlite3.Connection,
    snapshot: sqlite3.Row,
) -> dict[str, Any]:
    """Return a dict suitable for matcher + webhook payload.

    Pulls the entity's record_kind + raw_json so the matcher can see law /
    industry tags. Falls back to empty lists when the entity row is missing
    (defensive — am_amendment_snapshot has a FK but we don't trust it).
    """
    base: dict[str, Any] = {
        "snapshot_id": snapshot["snapshot_id"],
        "entity_id": snapshot["entity_id"],
        "version_seq": snapshot["version_seq"],
        "observed_at": snapshot["observed_at"],
        "effective_from": snapshot["effective_from"],
        "effective_until": snapshot["effective_until"],
        "amount_max_yen": snapshot["amount_max_yen"],
        "subsidy_rate_max": snapshot["subsidy_rate_max"],
        "source_url": snapshot["source_url"],
    }
    row = am_conn.execute(
        "SELECT record_kind, raw_json FROM am_entities WHERE canonical_id = ?",
        (snapshot["entity_id"],),
    ).fetchone()
    if row is None:
        base["record_kind"] = None
        base["law_refs"] = []
        base["industries"] = []
        base["tools"] = []
        base["law_id"] = None
        return base
    base["record_kind"] = row["record_kind"]
    try:
        raw = json.loads(row["raw_json"]) if row["raw_json"] else {}
    except (TypeError, ValueError):
        raw = {}
    base["law_id"] = raw.get("law_id") or raw.get("statute_id")
    base["law_refs"] = raw.get("law_refs") or raw.get("related_laws") or []
    base["industries"] = raw.get("jsic_codes") or raw.get("industries") or []
    base["tools"] = raw.get("tools") or []
    return base


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------


def _previous_snapshot(
    am_conn: sqlite3.Connection,
    entity_id: str,
    version_seq: int,
) -> sqlite3.Row | None:
    return am_conn.execute(
        """SELECT * FROM am_amendment_snapshot
            WHERE entity_id = ? AND version_seq < ?
         ORDER BY version_seq DESC LIMIT 1""",
        (entity_id, version_seq),
    ).fetchone()


def run(
    *,
    since_iso: str | None = None,
    dry_run: bool = False,
    autonomath_db: Path | None = None,
    jpintel_db: Path | None = None,
) -> dict[str, Any]:
    """Daily fan-out. Returns a summary dict for cron capture."""
    am_path = autonomath_db or settings.autonomath_db_path
    if not Path(am_path).is_file():
        logger.warning("autonomath_db_missing path=%s", am_path)
        return {
            "ran_at": datetime.now(UTC).isoformat(),
            "skipped": True,
            "reason": "autonomath_db_missing",
        }

    if since_iso is None:
        since_iso = (datetime.now(UTC) - timedelta(days=1)).isoformat()

    am_conn = sqlite3.connect(str(am_path))
    am_conn.row_factory = sqlite3.Row
    jp_conn = connect(jpintel_db) if jpintel_db else connect()

    try:
        new_snapshots = am_conn.execute(
            """SELECT * FROM am_amendment_snapshot
                WHERE observed_at >= ?
             ORDER BY observed_at ASC""",
            (since_iso,),
        ).fetchall()
        amendments_scanned = len(new_snapshots)

        # Active subscriptions (small fan-out at MVP scale: tens to hundreds).
        # We materialise them upfront so the per-amendment matcher loop
        # doesn't hit the DB N times per row.
        subs = jp_conn.execute(
            """SELECT id, api_key_hash, filter_type, filter_value, min_severity,
                      webhook_url, email
                 FROM alert_subscriptions
                WHERE active = 1"""
        ).fetchall()

        rate_limiter = _WebhookRateLimiter()
        http_client = httpx.Client(timeout=_HTTPX_TIMEOUT)
        try:
            webhook_fires = 0
            email_fires = 0
            sub_fires: dict[int, str] = {}

            now_iso = datetime.now(UTC).isoformat()
            for snap in new_snapshots:
                prev = _previous_snapshot(
                    am_conn,
                    snap["entity_id"],
                    snap["version_seq"],
                )
                severity = _infer_severity(snap, prev)
                amendment = _enrich_amendment(am_conn, snap)
                amendment["severity"] = severity

                payload_base = {
                    "schema": "autonomath.amendment.v1",
                    "ts": now_iso,
                    **amendment,
                }

                for sub in subs:
                    # Severity gate.
                    if SEVERITY_RANK[severity] < SEVERITY_RANK[sub["min_severity"]]:
                        continue
                    if not _amendment_matches(amendment, sub):
                        continue

                    # Build per-sub payload (small, no PII).
                    payload = dict(payload_base)
                    payload["subscription_id"] = sub["id"]

                    if sub["webhook_url"]:
                        rate_limiter.acquire(sub["webhook_url"])
                        outcome = _post_webhook(
                            client=http_client,
                            url=sub["webhook_url"],
                            payload=payload,
                            dry_run=dry_run,
                        )
                        if outcome.get("ok"):
                            webhook_fires += 1
                    if sub["email"]:
                        em_out = _send_alert_email(
                            to=sub["email"],
                            payload=payload,
                            dry_run=dry_run,
                        )
                        if not em_out.get("skipped") or em_out.get("reason") == "dry_run":
                            email_fires += 1
                    sub_fires[sub["id"]] = now_iso
        finally:
            http_client.close()

        # Update last_triggered for every sub that fired.
        if not dry_run and sub_fires:
            for sub_id, ts in sub_fires.items():
                jp_conn.execute(
                    "UPDATE alert_subscriptions SET last_triggered = ? WHERE id = ?",
                    (ts, sub_id),
                )

        summary = {
            "ran_at": datetime.now(UTC).isoformat(),
            "since": since_iso,
            "amendments_scanned": amendments_scanned,
            "subscriptions_active": len(subs),
            "subscriptions_fired": len(sub_fires),
            "webhook_fires": webhook_fires,
            "email_fires": email_fires,
            "dry_run": dry_run,
        }
        logger.info("amendment_alert.summary %s", json.dumps(summary, ensure_ascii=False))
        return summary
    finally:
        am_conn.close()
        jp_conn.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Daily amendment alert cron")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--since", default=None, help="ISO datetime (default: now-24h)")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    with heartbeat("amendment_alert") as hb:
        summary = run(since_iso=args.since, dry_run=args.dry_run)
        if isinstance(summary, dict):
            hb["rows_processed"] = int(
                summary.get("alerts_sent", summary.get("emails_sent", 0)) or 0
            )
            hb["rows_skipped"] = int(summary.get("skipped", 0) or 0)
            hb["metadata"] = {
                k: summary.get(k)
                for k in ("scanned", "amendments", "errors", "dry_run")
                if k in summary
            }
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
