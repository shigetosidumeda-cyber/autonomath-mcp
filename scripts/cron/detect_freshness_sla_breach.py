#!/usr/bin/env python3
"""SLA breach detector for cron freshness (Wave 37).

Reads the latest snapshot from ``rollup_freshness_daily.py`` (either
``analytics/freshness_rollup_latest.json`` or a ``--snapshot`` path) and
emits a Telegram alert for any cron whose:

  * ``last_run.created_at`` is older than ``sla_hours`` × 1.0, OR
  * ``last_run.conclusion`` is ``failure`` / ``cancelled`` / ``timed_out``, OR
  * ``success_rate_24h_pct`` is below 50 %.

Telegram credentials are optional: when ``TG_BOT_TOKEN`` /
``TELEGRAM_BOT_TOKEN`` and ``TG_CHAT_ID`` / ``TELEGRAM_CHAT_ID`` are
unset the script logs the breach payload and exits 0 — graceful no-op
matches every other cron in this repo.

Usage::

  python scripts/cron/detect_freshness_sla_breach.py
  python scripts/cron/detect_freshness_sla_breach.py --dry-run
  python scripts/cron/detect_freshness_sla_breach.py \
    --snapshot analytics/freshness_rollup_2026-05-12.json
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib import parse, request
from urllib.error import HTTPError, URLError

logger = logging.getLogger("detect_freshness_sla_breach")

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_SNAPSHOT = REPO_ROOT / "analytics" / "freshness_rollup_latest.json"

UTC = timezone.utc
JST = timezone(timedelta(hours=9))

FAIL_CONCLUSIONS = {"failure", "cancelled", "timed_out", "action_required"}
SUCCESS_RATE_FLOOR = 50.0  # below this is breach


@dataclass(frozen=True)
class Breach:
    workflow: str
    severity: str  # "stale" | "failed" | "low_success_rate" | "never_ran"
    detail: str
    sla_hours: int
    last_run_at: str | None
    success_rate_pct: float | None


def load_snapshot(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"snapshot not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def detect_breaches(snapshot: dict[str, Any], *, now: datetime | None = None) -> list[Breach]:
    now = now or datetime.now(UTC)
    out: list[Breach] = []
    for cron in snapshot.get("crons", []):
        wf = cron.get("workflow", "?")
        sla = int(cron.get("sla_hours", 24))
        last = cron.get("last_run") or {}
        last_ts = parse_iso(last.get("created_at"))
        rate = cron.get("success_rate_24h_pct")
        conclusion = (last.get("conclusion") or "").lower()

        if last_ts is None:
            out.append(
                Breach(
                    workflow=wf,
                    severity="never_ran",
                    detail="no run history visible to gh CLI",
                    sla_hours=sla,
                    last_run_at=None,
                    success_rate_pct=rate,
                )
            )
            continue

        staleness = now - last_ts
        if staleness > timedelta(hours=sla):
            out.append(
                Breach(
                    workflow=wf,
                    severity="stale",
                    detail=f"last run was {staleness.total_seconds() / 3600:.1f}h ago (SLA {sla}h)",
                    sla_hours=sla,
                    last_run_at=last.get("created_at"),
                    success_rate_pct=rate,
                )
            )
            continue

        if conclusion in FAIL_CONCLUSIONS:
            out.append(
                Breach(
                    workflow=wf,
                    severity="failed",
                    detail=f"latest run conclusion={conclusion}",
                    sla_hours=sla,
                    last_run_at=last.get("created_at"),
                    success_rate_pct=rate,
                )
            )
            continue

        if rate is not None and rate < SUCCESS_RATE_FLOOR:
            out.append(
                Breach(
                    workflow=wf,
                    severity="low_success_rate",
                    detail=f"success_rate_24h={rate}% < {SUCCESS_RATE_FLOOR}%",
                    sla_hours=sla,
                    last_run_at=last.get("created_at"),
                    success_rate_pct=rate,
                )
            )
    return out


def format_telegram_payload(breaches: list[Breach]) -> str:
    if not breaches:
        return "[jpcite cron freshness] all green"
    lines = [f"[jpcite cron freshness] {len(breaches)} breach(es)"]
    for b in breaches:
        lines.append(f"- {b.workflow} [{b.severity}] {b.detail}")
    return "\n".join(lines)


def post_telegram(token: str, chat_id: str, text: str) -> bool:
    """Send a plain-text Telegram message. Best-effort; returns True on 200."""
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = parse.urlencode({"chat_id": chat_id, "text": text}).encode("utf-8")
    req = request.Request(url, data=data, method="POST")  # noqa: S310 — trusted host
    try:
        with request.urlopen(req, timeout=15) as resp:  # noqa: S310
            return 200 <= resp.status < 300
    except (HTTPError, URLError, TimeoutError) as exc:
        logger.warning("telegram post failed: %s", exc)
        return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--snapshot",
        type=Path,
        default=DEFAULT_SNAPSHOT,
        help=f"path to rollup snapshot json (default {DEFAULT_SNAPSHOT})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print payload, never send telegram",
    )
    parser.add_argument(
        "--exit-nonzero-on-breach",
        action="store_true",
        help="set exit code to 1 when at least one breach is detected",
    )
    parser.add_argument("--log-level", default=os.environ.get("LOG_LEVEL", "INFO"))
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=args.log_level,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    try:
        snapshot = load_snapshot(args.snapshot)
    except FileNotFoundError as exc:
        logger.error("%s", exc)
        return 1

    breaches = detect_breaches(snapshot)
    payload = format_telegram_payload(breaches)

    logger.info(
        "breaches=%d snapshot=%s gh_available=%s",
        len(breaches),
        args.snapshot.name,
        snapshot.get("gh_available"),
    )
    print(payload)

    token = (
        os.environ.get("TG_BOT_TOKEN")
        or os.environ.get("TELEGRAM_BOT_TOKEN")
        or ""
    )
    chat_id = (
        os.environ.get("TG_CHAT_ID")
        or os.environ.get("TELEGRAM_CHAT_ID")
        or ""
    )

    if args.dry_run:
        logger.info("dry-run: skipping telegram post")
    elif breaches and token and chat_id:
        ok = post_telegram(token, chat_id, payload)
        logger.info("telegram_posted=%s", ok)
    elif breaches:
        logger.info("telegram credentials absent — graceful no-op")

    if args.exit_nonzero_on_breach and breaches:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
