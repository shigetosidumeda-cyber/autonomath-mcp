#!/usr/bin/env python3
"""Daily revalidation of stored customer-webhook URLs (DNS-rebind defence).

R2 P1-4 follow-on: register-time validation (POST /v1/me/webhooks +
PATCH /v1/me/webhooks/{id}) now refuses URLs whose hostname resolves to a
private/internal address. That gate cannot, on its own, defend against
**DNS drift** — a customer-controlled hostname that resolved to a public IP
yesterday and an RFC1918 address today. The dispatcher cron's per-fire
``is_safe_webhook`` re-check (scripts/cron/dispatch_webhooks.py) catches
this on the next event, but until then the row sits as ``status='active'``
in the dashboard. This script closes the gap proactively:

  1. Walk every ``customer_webhooks`` row WHERE ``status='active'``.
  2. Re-resolve its URL through ``jpintel_mcp.utils.webhook_safety.is_safe_webhook``.
  3. If the re-resolution returns unsafe, flip:
       status         = 'disabled'
       disabled_at    = now()
       disabled_reason = 'dns_drift_unsafe: <reason>'
       updated_at     = now()
  4. Log a single summary line at INFO with counts:
       active_examined / flagged_unsafe / dns_failed / kept_active

Already-inactive rows (status='disabled') are SKIPPED — once the dispatcher
or this cron has flagged a row the customer must DELETE + re-register, which
runs the register-time gate fresh. Re-evaluating disabled rows would (a)
waste DNS look-ups and (b) clobber the original ``disabled_reason`` (eg.
``5 consecutive failures`` would be overwritten by ``dns_drift_unsafe`` if
the same hostname later happened to fail DNS).

Constraints (project_autonomath_no_api_use + no_operator_llm_api):
  * No Anthropic / claude / SDK calls. Pure SQLite + stdlib + the shared
    ``is_safe_webhook`` helper which uses ``socket.getaddrinfo`` only.
  * Idempotent — running twice in a row flags zero additional rows.

Cadence: daily, 03:30 JST (avoids dispatcher cron jitter at :05/:15/...).

Usage:
    python scripts/cron/revalidate_webhook_targets.py
    python scripts/cron/revalidate_webhook_targets.py --dry-run    # log only
    python scripts/cron/revalidate_webhook_targets.py --db /path/to/jpintel.db

Exit codes: 0 ok / 1 config (DB missing) / 2 SQL error.
"""

from __future__ import annotations

import argparse
import logging
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Allow running as a script without `pip install -e .`.
_REPO = Path(__file__).resolve().parent.parent.parent
_SRC = _REPO / "src"
if _SRC.exists() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from jpintel_mcp.utils.webhook_safety import is_safe_webhook  # noqa: E402

logger = logging.getLogger("jpintel.revalidate_webhook_targets")


def run(
    *,
    dry_run: bool = False,
    jpintel_db: Path | None = None,
) -> dict[str, Any]:
    """Single revalidation pass. Returns a summary dict for cron capture."""
    summary: dict[str, Any] = {
        "ran_at": datetime.now(UTC).isoformat(),
        "active_examined": 0,
        "flagged_unsafe": 0,
        "dns_failed": 0,
        "kept_active": 0,
        "dry_run": dry_run,
    }

    if jpintel_db is None:
        # Late import so this module remains importable in test envs where
        # the FastAPI settings module is not yet wired up.
        from jpintel_mcp.db.session import connect as _connect

        conn = _connect()
    else:
        conn = sqlite3.connect(jpintel_db)
        conn.row_factory = sqlite3.Row

    try:
        rows = conn.execute(
            "SELECT id, url FROM customer_webhooks WHERE status = 'active'"
        ).fetchall()
        summary["active_examined"] = len(rows)

        now_iso = datetime.now(UTC).isoformat()
        for row in rows:
            wid = row["id"]
            url = row["url"]
            safe, reason = is_safe_webhook(url)
            if safe:
                summary["kept_active"] += 1
                continue
            # Distinguish hard DNS failure from "resolved to private IP".
            # Hard failure (`dns_failed`) is a CANNOT-REACH not a security
            # problem — we still disable so we stop attempting deliveries,
            # but tag with `dns_failed` so customer support can see the
            # transient case separately from a real rebind.
            if reason == "dns_failed":
                summary["dns_failed"] += 1
                disabled_reason = "dns_drift_unsafe: dns_failed"
            else:
                summary["flagged_unsafe"] += 1
                disabled_reason = f"dns_drift_unsafe: {reason}"

            if dry_run:
                logger.info(
                    "would-disable webhook_id=%s reason=%s url_host=%s",
                    wid,
                    disabled_reason,
                    url,
                )
                continue

            conn.execute(
                "UPDATE customer_webhooks "
                "SET status = 'disabled', disabled_at = ?, "
                "disabled_reason = ?, updated_at = ? "
                "WHERE id = ? AND status = 'active'",
                (now_iso, disabled_reason, now_iso, wid),
            )
        if not dry_run:
            conn.commit()
    finally:
        conn.close()

    logger.info(
        "revalidate_webhook_targets summary "
        "examined=%s flagged_unsafe=%s dns_failed=%s kept_active=%s dry_run=%s",
        summary["active_examined"],
        summary["flagged_unsafe"],
        summary["dns_failed"],
        summary["kept_active"],
        summary["dry_run"],
    )
    return summary


def _parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Daily revalidation of customer_webhooks DNS targets.",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Log would-disable actions without mutating the DB.",
    )
    p.add_argument(
        "--db",
        type=Path,
        default=None,
        help="Override jpintel.db path (default: settings.jpintel_db_path).",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    args = _parse_args(argv or sys.argv[1:])
    try:
        run(dry_run=args.dry_run, jpintel_db=args.db)
    except sqlite3.Error as exc:
        logger.error("revalidate_webhook_targets sql_error %r", exc)
        return 2
    except FileNotFoundError as exc:
        logger.error("revalidate_webhook_targets db_missing %r", exc)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
