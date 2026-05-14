#!/usr/bin/env python3
"""Morning briefing cron — per-customer 5-line daily summary.

Runs daily at 06:05 JST (5 min after saved-searches sweep so the two
crons do not contend for the same Fly machine SSH session).

For every paid api_keys row with at least one client_profile, emits ONE
Postmark email per customer summarising:

    1. New programs in their industry/prefecture from the last 24h
    2. Deadlines this week (next 7d)
    3. Recent amendments touching their watch list

Cost posture:
    * ¥3 per customer per day. Mirrors saved_searches.digest billing
      shape — one row in usage_events per delivered email.
    * 0-content runs (no new programs / no deadlines / no amendments)
      do NOT bill — empty body would be spam, we skip the send.

CLI:
    python scripts/cron/morning_briefing.py
    python scripts/cron/morning_briefing.py --dry-run

The Postmark template `morning_briefing` MUST exist before the cron
will deliver content; see docs/email/templates.md for the create steps.
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

_REPO = Path(__file__).resolve().parent.parent.parent
_SRC = _REPO / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from jpintel_mcp.billing.delivery import record_metered_delivery  # noqa: E402
from jpintel_mcp.config import settings  # noqa: E402
from jpintel_mcp.db.session import connect  # noqa: E402
from jpintel_mcp.observability import heartbeat  # noqa: E402
from jpintel_mcp.utils.slug import program_static_url  # noqa: E402

logger = logging.getLogger("autonomath.cron.morning_briefing")

_PUBLIC_ORIGIN = "https://jpcite.com"


def _program_public_url(primary_name: str | None, unified_id: str | None) -> str:
    """Return a safe public program link for briefing template payloads."""
    if primary_name and unified_id:
        return f"{_PUBLIC_ORIGIN}{program_static_url(primary_name, unified_id)}"
    return f"{_PUBLIC_ORIGIN}/dashboard.html"


def _new_programs_24h(conn: sqlite3.Connection, prefectures: set[str]) -> list[dict[str, Any]]:
    """Programs whose `updated_at` lies in the last 24h, scoped to the
    customer's covered prefectures (or 全国 when unscoped).
    """
    cutoff = (datetime.now(UTC) - timedelta(hours=24)).isoformat()
    where = [
        "(excluded = 0 OR excluded IS NULL)",
        "tier IN ('S','A','B','C')",
        "updated_at >= ?",
    ]
    params: list[Any] = [cutoff]
    if prefectures:
        placeholders = ",".join("?" for _ in prefectures)
        where.append(f"(prefecture IN ({placeholders}) OR prefecture IS NULL)")
        params.extend(prefectures)
    sql = (
        "SELECT unified_id, primary_name, prefecture, authority_name "
        f"FROM programs WHERE {' AND '.join(where)} "
        "ORDER BY updated_at DESC LIMIT 5"
    )
    rows = conn.execute(sql, params).fetchall()
    return [
        {
            "name": r["primary_name"],
            "prefecture": r["prefecture"] or "全国",
            "authority": r["authority_name"] or "",
            "url": _program_public_url(r["primary_name"], r["unified_id"]),
        }
        for r in rows
    ]


def _deadlines_this_week(conn: sqlite3.Connection, prefectures: set[str]) -> list[dict[str, Any]]:
    """Programs whose deadline_date sits in the next 7 days."""
    today = datetime.now(UTC).date().isoformat()
    cutoff = (datetime.now(UTC).date() + timedelta(days=7)).isoformat()
    # programs.deadline_date is the canonical column on jpintel.db; if a
    # given build does not carry it (test schema variants), the SQL fails
    # OperationalError and we return empty — preserving "honest empty".
    try:
        rows = conn.execute(
            "SELECT unified_id, primary_name, deadline_date, prefecture "
            "  FROM programs "
            " WHERE deadline_date BETWEEN ? AND ? "
            "   AND (excluded = 0 OR excluded IS NULL) "
            "   AND tier IN ('S','A','B','C') "
            f" {('AND prefecture IN (' + ','.join('?' for _ in prefectures) + ')') if prefectures else ''} "
            " ORDER BY deadline_date ASC LIMIT 5",
            [today, cutoff, *prefectures],
        ).fetchall()
    except sqlite3.OperationalError as exc:
        if "no such column" in str(exc).lower():
            return []
        raise
    return [
        {
            "name": r["primary_name"],
            "deadline": r["deadline_date"],
            "prefecture": r["prefecture"] or "全国",
            "url": _program_public_url(r["primary_name"], r["unified_id"]),
        }
        for r in rows
    ]


def _recent_amendments(
    am_conn: sqlite3.Connection | None, watched_ids: set[str]
) -> list[dict[str, Any]]:
    """Amendments to watched programs in the last 24h."""
    if am_conn is None or not watched_ids:
        return []
    cutoff = (datetime.now(UTC) - timedelta(hours=24)).isoformat()
    placeholders = ",".join("?" for _ in watched_ids)
    try:
        rows = am_conn.execute(
            f"SELECT entity_id, field_name, detected_at "
            f"  FROM am_amendment_diff "
            f" WHERE entity_id IN ({placeholders}) "
            f"   AND detected_at >= ? "
            f" ORDER BY detected_at DESC LIMIT 5",
            [*watched_ids, cutoff],
        ).fetchall()
    except sqlite3.OperationalError as exc:
        if "no such table" in str(exc).lower():
            return []
        raise
    return [
        {
            "entity_id": r["entity_id"],
            "field_name": r["field_name"],
            "detected_at": r["detected_at"],
        }
        for r in rows
    ]


def _send_briefing(*, to: str, payload: dict[str, Any], dry_run: bool) -> dict[str, Any]:
    if dry_run:
        logger.info(
            "morning_briefing.dry_run to_domain=%s programs=%d deadlines=%d amendments=%d",
            to.split("@", 1)[-1] if "@" in to else "***",
            len(payload.get("new_programs", [])),
            len(payload.get("deadlines", [])),
            len(payload.get("amendments", [])),
        )
        return {"skipped": True, "reason": "dry_run"}
    try:
        from jpintel_mcp.email import get_client
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("briefing.email_unavailable err=%s", exc)
        return {"skipped": True, "reason": "email_module_unavailable"}
    try:
        client = get_client()
        return client._send(  # type: ignore[attr-defined]
            to=to,
            template_alias="morning_briefing",
            template_model=payload,
            tag="morning-briefing",
        )
    except Exception as exc:
        logger.warning("briefing.send_failed err=%s", exc)
        return {"skipped": True, "reason": "send_failed", "error": str(exc)}


def _record_metered_delivery(*, jp_conn: sqlite3.Connection, key_hash: str, dry_run: bool) -> None:
    if dry_run:
        return
    ok = record_metered_delivery(
        jp_conn,
        key_hash=key_hash,
        endpoint="morning_briefing.delivery",
    )
    if not ok:
        logger.warning("briefing.delivery_billing_skipped")


def run(*, dry_run: bool = False) -> dict[str, Any]:
    am_path = settings.autonomath_db_path
    am_present = Path(am_path).is_file()

    jp_conn = connect()
    am_conn: sqlite3.Connection | None = None
    if am_present:
        am_conn = sqlite3.connect(str(am_path))
        am_conn.row_factory = sqlite3.Row

    scanned = 0
    sent = 0
    billed = 0
    skipped_empty = 0
    try:
        # Group profiles per api_key. We only brief paid keys (anonymous
        # tier never has a profile row anyway).
        rows = jp_conn.execute(
            "SELECT api_key_hash, "
            "       GROUP_CONCAT(prefecture) AS prefs, "
            "       GROUP_CONCAT(last_active_program_ids_json, '||') AS pids, "
            "       MAX(name_label) AS any_label "
            "  FROM client_profiles "
            " GROUP BY api_key_hash"
        ).fetchall()
        for r in rows:
            scanned += 1
            key_hash = r["api_key_hash"]
            prefectures = {p.strip() for p in (r["prefs"] or "").split(",") if p and p.strip()}
            watched: set[str] = set()
            for chunk in (r["pids"] or "").split("||"):
                try:
                    for pid in json.loads(chunk or "[]"):
                        watched.add(str(pid))
                except (TypeError, ValueError):
                    continue

            # Resolve the customer's notification email from api_keys.
            ak = jp_conn.execute(
                "SELECT notify_email, tier FROM api_keys WHERE key_hash = ?",
                (key_hash,),
            ).fetchone()
            if ak is None or not ak["notify_email"]:
                continue
            if ak["tier"] != "paid":
                continue

            new_programs = _new_programs_24h(jp_conn, prefectures)
            deadlines = _deadlines_this_week(jp_conn, prefectures)
            amendments = _recent_amendments(am_conn, watched)

            if not new_programs and not deadlines and not amendments:
                skipped_empty += 1
                continue

            payload = {
                "new_programs": new_programs,
                "deadlines": deadlines,
                "amendments": amendments,
                "manage_url": f"{_PUBLIC_ORIGIN}/dashboard.html",
                "disclaimer": (
                    "本通知はjpciteによる公開情報の検索結果です。"
                    "個別具体的な税務助言・法律判断は税理士法 §52 / 弁護士法 §72 に基づき"
                    "資格者にご確認ください。"
                ),
            }
            outcome = _send_briefing(to=ak["notify_email"], payload=payload, dry_run=dry_run)
            ok = outcome.get("skipped") is None or outcome.get("reason") == "dry_run"
            if ok:
                sent += 1
                _record_metered_delivery(jp_conn=jp_conn, key_hash=key_hash, dry_run=dry_run)
                if not dry_run:
                    billed += 1
        summary = {
            "ran_at": datetime.now(UTC).isoformat(),
            "scanned": scanned,
            "sent": sent,
            "billed": billed,
            "skipped_empty": skipped_empty,
            "dry_run": dry_run,
        }
        logger.info(
            "morning_briefing.summary %s",
            json.dumps(summary, ensure_ascii=False),
        )
        return summary
    finally:
        if am_conn is not None:
            am_conn.close()
        jp_conn.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Daily morning briefing cron")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    with heartbeat("morning_briefing") as hb:
        summary = run(dry_run=args.dry_run)
        if isinstance(summary, dict):
            hb["rows_processed"] = int(summary.get("emails_sent", summary.get("delivered", 0)) or 0)
            hb["rows_skipped"] = int(summary.get("skipped", 0) or 0)
            hb["metadata"] = {
                k: summary.get(k)
                for k in ("scanned", "amendments", "alerts", "dry_run")
                if k in summary
            }
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
