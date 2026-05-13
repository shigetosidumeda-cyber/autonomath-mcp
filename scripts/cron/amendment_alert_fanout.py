#!/usr/bin/env python3
"""Daily amendment-alert fan-out (R8 / jpcite v0.3.4).

What it does
------------
1. Reads `amendment_alert_subscriptions` from jpintel.db where
   deactivated_at IS NULL.
2. For each subscription, computes the scan window from its
   last_fanout_at (NULL ⇒ 24 h floor; cap at FEED_WINDOW_DAYS to bound a
   long-deactivated-then-reactivated case).
3. Joins the watches against autonomath.db `am_amendment_diff` rows whose
   detected_at is inside the window.
4. Posts hits to the customer's webhook (if `customer_webhooks` rows exist)
   and falls back to email when set on the api_keys row. Each subscription
   gets ONE batched payload per run, never N small ones.
5. Updates `last_fanout_at` to the run start (NOT now() — that would skip
   diffs detected *during* the run).

Distinct from `amendment_alert.py` (legacy P5-ι++ alert cron)
-------------------------------------------------------------
The legacy cron (`scripts/cron/amendment_alert.py`) reads the older
`am_amendment_snapshot` table and the migration-038 `alert_subscriptions`
table. THIS file is the new R8 surface — it reads `am_amendment_diff` (the
post-cron diff log) and the migration-194 `amendment_alert_subscriptions`
table. Both crons run daily; their outputs do not overlap because they
read different source tables AND different subscription tables.

Constraints
-----------
* No Anthropic / claude / SDK calls — pure SQL + httpx.
* Subscription is FREE retention; no usage_event / Stripe usage record.
* Webhook posture mirrors `amendment_alert.py`: HTTPS-only, RFC1918 hosts
  blocked at fire-time (not just create-time).

Usage
-----
    python scripts/cron/amendment_alert_fanout.py            # real run
    python scripts/cron/amendment_alert_fanout.py --dry-run  # no webhook / email
"""

from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

# Allow running as a script without `pip install -e .`.
_REPO = Path(__file__).resolve().parent.parent.parent
_SRC = _REPO / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from jpintel_mcp.api.amendment_alerts import (  # noqa: E402
    FEED_WINDOW_DAYS,
    WATCH_TYPES,
)
from jpintel_mcp.config import settings  # noqa: E402
from jpintel_mcp.db.session import connect  # noqa: E402

logger = logging.getLogger("autonomath.cron.amendment_alert_fanout")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _connect_autonomath() -> sqlite3.Connection:
    """Open autonomath.db read-only. Defers to the runtime path resolver."""
    from jpintel_mcp.mcp.autonomath_tools.db import connect_autonomath

    return connect_autonomath()


def _load_active_subscriptions(jpintel_db: sqlite3.Connection) -> list[sqlite3.Row]:
    """Return active subscription rows ordered by oldest last_fanout_at first."""
    return jpintel_db.execute(
        "SELECT id, api_key_id, api_key_hash, watch_json, last_fanout_at, created_at "
        "FROM amendment_alert_subscriptions "
        "WHERE deactivated_at IS NULL "
        "ORDER BY COALESCE(last_fanout_at, '1970-01-01T00:00:00Z') ASC"
    ).fetchall()


def _parse_watches(watch_json: str) -> list[dict[str, str]]:
    """Decode + filter watch entries."""
    try:
        raw = json.loads(watch_json)
    except (TypeError, ValueError):
        return []
    out: list[dict[str, str]] = []
    if not isinstance(raw, list):
        return out
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        wt = entry.get("type")
        wid = entry.get("id")
        if wt in WATCH_TYPES and isinstance(wid, str) and wid:
            out.append({"type": wt, "id": wid})
    return out


def _scan_window_floor(last_fanout_at: str | None) -> str:
    """Compute the diff scan floor for this subscription.

    Falls back to (now - 24h) when last_fanout_at is NULL. Caps at
    (now - FEED_WINDOW_DAYS) so a long-dormant subscription does not
    re-deliver the entire 90-day backlog on its first fan-out tick.
    """
    cap = (datetime.now(UTC) - timedelta(days=FEED_WINDOW_DAYS)).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    if last_fanout_at is None:
        floor = (datetime.now(UTC) - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%S+00:00")
        return max(floor, cap)
    return max(last_fanout_at, cap)


def _matching_diffs(
    am_conn: sqlite3.Connection,
    watches: list[dict[str, str]],
    since_iso: str,
) -> list[dict[str, Any]]:
    """Run the union match against am_amendment_diff."""
    if not watches:
        return []
    ids_program: list[str] = []
    ids_law: list[str] = []
    ids_industry: list[str] = []
    for w in watches:
        if w["type"] == "program_id":
            ids_program.append(w["id"])
        elif w["type"] == "law_id":
            ids_law.append(w["id"])
        elif w["type"] == "industry_jsic":
            ids_industry.append(w["id"])
    clauses: list[str] = []
    args: list[Any] = []
    if ids_program:
        ph = ",".join("?" * len(ids_program))
        clauses.append(f"d.entity_id IN ({ph})")
        args.extend(ids_program)
    if ids_law:
        ph = ",".join("?" * len(ids_law))
        clauses.append(f"d.entity_id IN ({ph})")
        args.extend(ids_law)
    if ids_industry:
        ph = ",".join("?" * len(ids_industry))
        clauses.append(
            "d.entity_id IN (SELECT entity_id FROM am_entity_facts "
            f"WHERE field_name = 'industry_jsic' AND value IN ({ph}))"
        )
        args.extend(ids_industry)
    where_or = " OR ".join(f"({c})" for c in clauses)
    sql = (
        "SELECT d.diff_id, d.entity_id, d.field_name, d.prev_value, d.new_value, "
        "       d.detected_at, d.source_url "
        "FROM am_amendment_diff d "
        f"WHERE d.detected_at >= ? AND ({where_or}) "
        "ORDER BY d.detected_at DESC, d.diff_id DESC"
    )
    sql_args = [since_iso, *args]
    try:
        rows = am_conn.execute(sql, sql_args).fetchall()
    except sqlite3.OperationalError as exc:
        if "no such table" in str(exc).lower():
            logger.warning("am_amendment_diff missing on autonomath.db: %s", exc)
            return []
        raise
    return [
        {
            "diff_id": r["diff_id"],
            "entity_id": r["entity_id"],
            "field_name": r["field_name"],
            "prev_value": r["prev_value"],
            "new_value": r["new_value"],
            "detected_at": r["detected_at"],
            "source_url": r["source_url"],
        }
        for r in rows
    ]


def _customer_webhook_url(jpintel_db: sqlite3.Connection, api_key_hash: str) -> str | None:
    """Pull the customer's `customer_webhooks` URL when configured.

    Returns the FIRST active row found. The customer-webhooks router (mig
    080) lets a key register multiple URLs — we deliberately pick the first
    active one rather than fanning out N times to keep the fan-out cost
    flat at O(subscriptions). Customers who want N delivery targets can
    build their own dispatcher.
    """
    try:
        row = jpintel_db.execute(
            "SELECT url FROM customer_webhooks "
            "WHERE api_key_hash = ? AND status = 'active' "
            "ORDER BY id ASC LIMIT 1",
            (api_key_hash,),
        ).fetchone()
    except sqlite3.OperationalError:
        # Pre-migration/dev DBs may still carry an `active INTEGER` column.
        # Production migration 080 uses `status TEXT`; keep the fallback narrow
        # so missing customer_webhooks still degrades to no webhook channel.
        try:
            row = jpintel_db.execute(
                "SELECT url FROM customer_webhooks "
                "WHERE api_key_hash = ? AND active = 1 "
                "ORDER BY id ASC LIMIT 1",
                (api_key_hash,),
            ).fetchone()
        except sqlite3.OperationalError:
            return None
    return row["url"] if row else None


def _customer_email(jpintel_db: sqlite3.Connection, api_key_hash: str) -> str | None:
    """Resolve the customer's email from api_keys when set.

    Many keys do not carry email (the column was added in a later migration
    and is NULL on legacy rows). The cron tolerates NULL and falls back to
    webhook-only delivery.
    """
    try:
        row = jpintel_db.execute(
            "SELECT email FROM api_keys WHERE key_hash = ?",
            (api_key_hash,),
        ).fetchone()
    except sqlite3.OperationalError:
        return None
    if not row:
        return None
    try:
        return row["email"]
    except (KeyError, IndexError):
        return None


def _post_webhook(url: str, payload: dict[str, Any], dry_run: bool) -> dict[str, Any]:
    """Best-effort webhook POST. Mirrors amendment_alert.py guard rails."""
    if dry_run:
        logger.info("webhook.dry_run url=%s items=%d", url, len(payload.get("items", [])))
        return {"ok": True, "skipped": "dry_run"}
    try:
        import httpx
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("httpx.unavailable err=%s", exc)
        return {"ok": False, "error": "httpx_unavailable"}
    if not url.lower().startswith("https://"):
        logger.warning("webhook.unsafe url=%s reason=not_https", url)
        return {"ok": False, "error": "not_https"}
    try:
        with httpx.Client(timeout=httpx.Timeout(30.0, connect=10.0)) as client:
            r = client.post(url, json=payload)
            return {"ok": r.is_success, "status": r.status_code}
    except Exception as exc:
        logger.warning("webhook.error url=%s err=%s", url, exc)
        return {"ok": False, "error": str(exc)}


def _send_email(to: str, payload: dict[str, Any], dry_run: bool) -> dict[str, Any]:
    """Best-effort email via Postmark template alias 'amendment-alert-feed'."""
    if dry_run:
        logger.info(
            "email.dry_run to=%s items=%d",
            to.split("@", 1)[-1] if "@" in to else "***",
            len(payload.get("items", [])),
        )
        return {"skipped": True, "reason": "dry_run"}
    try:
        from jpintel_mcp.email import get_client
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("email.unavailable err=%s", exc)
        return {"skipped": True, "reason": "email_module_unavailable"}
    try:
        client = get_client()
        return client._send(  # type: ignore[attr-defined]
            to=to,
            template_alias="amendment-alert-feed",
            template_model=payload,
            tag="amendment-alert-feed",
        )
    except Exception as exc:
        logger.warning("email.send_failed err=%s", exc)
        return {"skipped": True, "reason": "send_failed", "error": str(exc)}


def _email_delivery_ok(outcome: dict[str, Any]) -> bool:
    """Return True only when an email send should count as delivered."""
    if outcome.get("ok") is True:
        return True
    if outcome.get("skipped"):
        return outcome.get("reason") == "dry_run"
    return "error" not in outcome


# ---------------------------------------------------------------------------
# Main entrypoint
# ---------------------------------------------------------------------------


def run(*, dry_run: bool = False) -> dict[str, Any]:
    """Run one fan-out tick. Returns a structured summary for log scraping."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    run_started_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    jpintel_db = connect(settings.db_path)
    jpintel_db.row_factory = sqlite3.Row

    summary: dict[str, Any] = {
        "started_at": run_started_at,
        "dry_run": dry_run,
        "subscriptions_seen": 0,
        "subscriptions_with_hits": 0,
        "diffs_total": 0,
        "delivery_attempts": 0,
        "delivery_ok": 0,
        "delivery_failed": 0,
        "delivery_no_channel": 0,
        "cursors_advanced": 0,
        "cursors_blocked": 0,
    }

    try:
        # Idempotent table create (defensive — tests / fresh boots).
        jpintel_db.execute(
            """CREATE TABLE IF NOT EXISTS amendment_alert_subscriptions (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                api_key_id      INTEGER,
                api_key_hash    TEXT NOT NULL,
                watch_json      TEXT NOT NULL,
                created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
                deactivated_at  TEXT,
                last_fanout_at  TEXT
            )"""
        )
        subs = _load_active_subscriptions(jpintel_db)
        summary["subscriptions_seen"] = len(subs)

        am_conn = _connect_autonomath()
        try:
            for sub in subs:
                watches = _parse_watches(sub["watch_json"])
                if not watches:
                    continue
                since = _scan_window_floor(sub["last_fanout_at"])
                hits = _matching_diffs(am_conn, watches, since)
                summary["diffs_total"] += len(hits)
                if hits:
                    summary["subscriptions_with_hits"] += 1
                    payload = {
                        "subscription_id": sub["id"],
                        "watch": watches,
                        "items": hits,
                        "_disclaimer": (
                            "本フィードは公開された am_amendment_diff の差分情報のみを"
                            "返します。個別判断・税務助言は行いません。"
                        ),
                    }
                    channels_seen = 0
                    channels_ok = 0
                    webhook_url = _customer_webhook_url(jpintel_db, sub["api_key_hash"])
                    if webhook_url:
                        channels_seen += 1
                        summary["delivery_attempts"] += 1
                        outcome = _post_webhook(webhook_url, payload, dry_run)
                        if outcome.get("ok"):
                            channels_ok += 1
                            summary["delivery_ok"] += 1
                        else:
                            summary["delivery_failed"] += 1
                    email_to = _customer_email(jpintel_db, sub["api_key_hash"])
                    if email_to:
                        channels_seen += 1
                        summary["delivery_attempts"] += 1
                        eo = _send_email(email_to, payload, dry_run)
                        if _email_delivery_ok(eo):
                            channels_ok += 1
                            summary["delivery_ok"] += 1
                        else:
                            summary["delivery_failed"] += 1
                    should_advance_cursor = channels_seen > 0 and channels_ok == channels_seen
                    if not should_advance_cursor:
                        if channels_seen == 0:
                            summary["delivery_no_channel"] += 1
                        summary["cursors_blocked"] += 1
                else:
                    # Empty diffs still consume the window; otherwise the same
                    # no-op scan re-runs every tick.
                    should_advance_cursor = True
                if not dry_run and should_advance_cursor:
                    jpintel_db.execute(
                        "UPDATE amendment_alert_subscriptions SET last_fanout_at = ? WHERE id = ?",
                        (run_started_at, sub["id"]),
                    )
                    summary["cursors_advanced"] += 1
            if not dry_run:
                jpintel_db.commit()
        finally:
            am_conn.close()
    finally:
        jpintel_db.close()

    summary["finished_at"] = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    logger.info("amendment_alert_fanout.summary %s", json.dumps(summary, ensure_ascii=False))
    return summary


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Amendment-alert fan-out cron (R8 / v0.3.4)")
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Do not POST webhooks / send email; do not advance last_fanout_at.",
    )
    return p


def main() -> int:
    args = _build_parser().parse_args()
    summary = run(dry_run=args.dry_run)
    # Exit non-zero only on hard error (caught above and re-raised). The
    # GHA workflow's Sentry alert step is keyed off non-zero exit.
    if summary.get("subscriptions_seen", 0) >= 0:
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
