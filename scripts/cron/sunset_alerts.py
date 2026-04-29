#!/usr/bin/env python3
"""Sunset alert cron — hourly fan-out to customers with sunset/amended programs.

Runs every hour at :15 (15-min stagger from other crons).

For every `am_amendment_diff` row detected in the last 60 minutes whose
new_value indicates a `sunset` or `amended` status change, fans out to
every customer whose `client_profiles.last_active_program_ids_json`
contains the affected entity_id.

Delivery channel:
    * If the customer has a saved_search with channel_format='slack' AND
      that saved_search references the program (best-effort, broadest
      possible match), POST to that Slack webhook.
    * Otherwise email via Postmark template `sunset_alert`.

Cost posture:
    * ¥3 per alert delivered (1 row in am_amendment_diff that triggers
      5 customers = ¥15 total).
    * 0-fan-out runs (no customers watch the affected program) DO NOT
      bill — the row goes ignored, no usage_events insert.

CLI:
    python scripts/cron/sunset_alerts.py
    python scripts/cron/sunset_alerts.py --dry-run
"""
from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parent.parent.parent
_SRC = _REPO / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from jpintel_mcp.config import settings  # noqa: E402
from jpintel_mcp.db.session import connect  # noqa: E402
from jpintel_mcp.observability import heartbeat  # noqa: E402

logger = logging.getLogger("autonomath.cron.sunset_alerts")

_PUBLIC_ORIGIN = "https://zeimu-kaikei.ai"
_LOOKBACK_MINUTES = 60


def _recent_sunset_diffs(
    am_conn: sqlite3.Connection,
) -> list[dict[str, Any]]:
    """Pull sunset/amended diffs from the last 60 minutes.

    am_amendment_diff has no canonical `status` column — the diff stream
    records a per-(entity_id, field_name) trail. We treat:
        * field_name='status'   AND new_value IN ('sunset','amended') → sunset alert
        * field_name='deadline' AND new_value IS NULL                 → likely sunset
    These are the broadest interpretations that map cleanly to the
    project_autonomath_business_model retention surface.
    """
    cutoff = (datetime.now(UTC) - timedelta(minutes=_LOOKBACK_MINUTES)).isoformat()
    try:
        rows = am_conn.execute(
            """SELECT diff_id, entity_id, field_name, prev_value, new_value,
                      detected_at
                 FROM am_amendment_diff
                WHERE detected_at >= ?
                  AND (
                       (field_name = 'status'
                        AND new_value IN ('sunset','amended'))
                       OR
                       (field_name = 'deadline' AND new_value IS NULL)
                       OR
                       (field_name = 'eligibility_text'
                        AND prev_value IS NOT NULL AND new_value IS NULL)
                  )
                ORDER BY detected_at ASC""",
            (cutoff,),
        ).fetchall()
    except sqlite3.OperationalError as exc:
        if "no such table" in str(exc).lower():
            logger.info("am_amendment_diff_missing — nothing to alert")
            return []
        raise
    return [dict(r) for r in rows]


def _customers_watching(
    jp_conn: sqlite3.Connection, entity_id: str
) -> list[dict[str, Any]]:
    """Return distinct (api_key_hash, notify_email, channel_format,
    channel_url) for every customer with `entity_id` in their
    last_active_program_ids_json across any client_profile.
    """
    pattern = f'%"{entity_id}"%'
    rows = jp_conn.execute(
        """SELECT DISTINCT
                  cp.api_key_hash,
                  ak.notify_email,
                  ak.tier,
                  ak.stripe_subscription_id
             FROM client_profiles cp
             JOIN api_keys ak ON ak.key_hash = cp.api_key_hash
            WHERE cp.last_active_program_ids_json LIKE ?
              AND ak.tier = 'paid'""",
        (pattern,),
    ).fetchall()
    return [dict(r) for r in rows]


def _preferred_channel(
    jp_conn: sqlite3.Connection, key_hash: str
) -> tuple[str, str | None]:
    """Look up the customer's most-recently-created Slack channel binding.

    Returns ('slack', channel_url) when a Slack-format saved_search exists,
    otherwise ('email', None). Does NOT scope by program — sunset alerts
    are urgent, we fan out to whichever Slack channel the customer wired up.
    """
    try:
        row = jp_conn.execute(
            """SELECT channel_url
                 FROM saved_searches
                WHERE api_key_hash = ?
                  AND channel_format = 'slack'
                  AND channel_url IS NOT NULL
                ORDER BY id DESC LIMIT 1""",
            (key_hash,),
        ).fetchone()
    except sqlite3.OperationalError as exc:
        if "no such column" in str(exc).lower():
            return "email", None
        raise
    if row and row["channel_url"]:
        return "slack", row["channel_url"]
    return "email", None


def _resolve_program_name(
    jp_conn: sqlite3.Connection, entity_id: str
) -> str:
    """Best-effort lookup of a human-readable name for the affected program."""
    row = jp_conn.execute(
        "SELECT primary_name FROM programs WHERE unified_id = ? LIMIT 1",
        (entity_id,),
    ).fetchone()
    if row is None:
        return entity_id
    return row["primary_name"] or entity_id


def _send_slack_sunset(
    *,
    channel_url: str,
    program_name: str,
    entity_id: str,
    diff: dict[str, Any],
    dry_run: bool,
) -> bool:
    text = (
        f":warning: *終了 / 改正検出* — {program_name}\n"
        f"項目: {diff['field_name']}  /  検出: {diff['detected_at']}\n"
        f"<{_PUBLIC_ORIGIN}/programs/{entity_id}|詳細を確認>"
    )
    if dry_run:
        logger.info(
            "sunset.slack.dry_run program=%s entity=%s", program_name, entity_id
        )
        return True
    body = json.dumps({"text": text}).encode("utf-8")
    req = urllib.request.Request(
        channel_url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return 200 <= resp.status < 300
    except (urllib.error.HTTPError, Exception):  # noqa: BLE001
        logger.warning("sunset.slack.send_failed entity=%s", entity_id)
        return False


def _send_email_sunset(
    *,
    to: str,
    program_name: str,
    entity_id: str,
    diff: dict[str, Any],
    dry_run: bool,
) -> bool:
    if dry_run:
        logger.info(
            "sunset.email.dry_run to_domain=%s program=%s",
            to.split("@", 1)[-1] if "@" in to else "***",
            program_name,
        )
        return True
    try:
        from jpintel_mcp.email import get_client
    except Exception:  # noqa: BLE001
        return False
    try:
        client = get_client()
        outcome = client._send(  # type: ignore[attr-defined]
            to=to,
            template_alias="sunset_alert",
            template_model={
                "program_name": program_name,
                "entity_id": entity_id,
                "field_name": diff["field_name"],
                "prev_value": diff.get("prev_value") or "",
                "new_value": diff.get("new_value") or "",
                "detected_at": diff["detected_at"],
                "url": f"{_PUBLIC_ORIGIN}/programs/{entity_id}",
                "disclaimer": (
                    "本通知は税務会計AIによる公開情報の検索結果です。"
                    "個別具体的な税務助言・法律判断は税理士法 §52 / 弁護士法 §72 に基づき"
                    "資格者にご確認ください。"
                ),
            },
            tag="sunset-alert",
        )
        return outcome.get("skipped") is None
    except Exception:  # noqa: BLE001
        return False


def _record_metered_delivery(
    *, jp_conn: sqlite3.Connection, key_hash: str, entity_id: str, dry_run: bool
) -> None:
    if dry_run:
        return
    row = jp_conn.execute(
        "SELECT tier, stripe_subscription_id FROM api_keys WHERE key_hash = ?",
        (key_hash,),
    ).fetchone()
    if row is None:
        return
    tier = row["tier"]
    sub_id = row["stripe_subscription_id"]
    metered = tier == "paid"
    cur = jp_conn.execute(
        "INSERT INTO usage_events("
        "  key_hash, endpoint, ts, status, metered, params_digest,"
        "  latency_ms, result_count"
        ") VALUES (?,?,?,?,?,?,?,?)",
        (
            key_hash,
            "sunset_alerts.delivery",
            datetime.now(UTC).isoformat(),
            200,
            1 if metered else 0,
            entity_id[:64] if entity_id else None,
            None,
            None,
        ),
    )
    usage_event_id = cur.lastrowid
    if metered and sub_id:
        try:
            from jpintel_mcp.billing.stripe_usage import report_usage_async

            report_usage_async(sub_id, usage_event_id=usage_event_id)
        except Exception:  # noqa: BLE001
            logger.warning("sunset.stripe_push_failed", exc_info=True)


def run(*, dry_run: bool = False) -> dict[str, Any]:
    am_path = settings.autonomath_db_path
    am_present = Path(am_path).is_file()
    if not am_present:
        logger.warning("autonomath_db_missing path=%s — exiting", am_path)
        return {"scanned": 0, "delivered": 0, "billed": 0}

    jp_conn = connect()
    am_conn = sqlite3.connect(str(am_path))
    am_conn.row_factory = sqlite3.Row

    scanned = 0
    delivered = 0
    billed = 0
    try:
        diffs = _recent_sunset_diffs(am_conn)
        scanned = len(diffs)
        for d in diffs:
            entity_id = d["entity_id"]
            customers = _customers_watching(jp_conn, entity_id)
            if not customers:
                continue
            program_name = _resolve_program_name(jp_conn, entity_id)
            for c in customers:
                channel, url = _preferred_channel(jp_conn, c["api_key_hash"])
                ok = False
                if channel == "slack" and url:
                    ok = _send_slack_sunset(
                        channel_url=url,
                        program_name=program_name,
                        entity_id=entity_id,
                        diff=d,
                        dry_run=dry_run,
                    )
                else:
                    if not c["notify_email"]:
                        continue
                    ok = _send_email_sunset(
                        to=c["notify_email"],
                        program_name=program_name,
                        entity_id=entity_id,
                        diff=d,
                        dry_run=dry_run,
                    )
                if ok:
                    delivered += 1
                    _record_metered_delivery(
                        jp_conn=jp_conn,
                        key_hash=c["api_key_hash"],
                        entity_id=entity_id,
                        dry_run=dry_run,
                    )
                    if not dry_run:
                        billed += 1
        summary = {
            "ran_at": datetime.now(UTC).isoformat(),
            "scanned": scanned,
            "delivered": delivered,
            "billed": billed,
            "dry_run": dry_run,
        }
        logger.info(
            "sunset_alerts.summary %s",
            json.dumps(summary, ensure_ascii=False),
        )
        return summary
    finally:
        am_conn.close()
        jp_conn.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Hourly sunset alerts cron")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    with heartbeat("sunset_alerts") as hb:
        summary = run(dry_run=args.dry_run)
        if isinstance(summary, dict):
            hb["rows_processed"] = int(
                summary.get("alerts_sent", summary.get("emails_sent", 0)) or 0
            )
            hb["rows_skipped"] = int(summary.get("skipped", 0) or 0)
            hb["metadata"] = {
                k: summary.get(k)
                for k in ("sunsets", "warned", "dry_run")
                if k in summary
            }
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
