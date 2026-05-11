#!/usr/bin/env python3
"""DB boot failure watchdog — detects Wave 25 + Wave 40 outage shapes.

Background
----------
Wave 25 (2026-05-11 5h12m outage / RC1): ``autonomath-api`` boot ran
``PRAGMA integrity_check`` on the 9.7 GB ``autonomath.db`` volume. The
pragma hung for 30+ min, the Fly proxy could not find a "good
candidate within 40 attempts at load balancing", and ``api.jpcite.com``
served 5xx for 5h12m. Wave 18 §4 (commit ``81922433f``) landed a
size-based skip so future boots short-circuit the pragma — but if a
future image regresses, or if ``BOOT_ENFORCE_INTEGRITY_CHECK=1`` is
set by operator error, the same trap re-arms.

Wave 40 (2026-05-11/12 14h+ outage / RC4): Wave 22 baked-seed
deployments on fresh volumes produced ``autonomath.db`` without the 5
``AM_REQUIRED_MIGRATIONS`` recorded in ``schema_migrations``.
``schema_guard`` exits non-zero with
``autonomath: required migrations missing from schema_migrations: [...]``
and Fly restart-loops the machine. The Wave 25 watchdog did NOT alert
because the boot pattern was different — schema_guard exits cleanly
(non-zero rc) rather than hanging. Wave 41 extends this watchdog to
detect both shapes.

This script is the daily watchdog. It tails ``flyctl logs`` and
notifies via Telegram if EITHER pattern fires:

1. **RC1 hang shape**: any canonical full-scan boot-op log line
   appears for more than 5 minutes without a follow-up ``ok`` /
   ``size-based skip`` / ``trusted stamp match`` line.
2. **RC4 FAIL shape**: a ``required migrations missing from
   schema_migrations`` line appears at any point in the recent log
   window. Unlike (1), FAIL is instant — there is no hang grace
   period; the entrypoint exits immediately. Also catches the broader
   ``schema_guard`` family of FAIL messages (forbidden table found,
   required table missing, required column missing).

Either shape gives the operator a 25+ min head-start over external
uptime detection.

Operator gating
---------------
- Telegram secrets: ``TG_BOT_TOKEN`` + ``TG_CHAT_ID``. Missing secrets
  cause a structured warning and a clean exit code 0 (do not red-line
  cron). Operator inventory must mirror them via ``.env.local`` SOT.
- Read-only: this script NEVER mutates Fly state. It only reads logs.
- Cron cadence: daily at 06:00 JST via ``.github/workflows/`` cron.

Why not Sentry?
---------------
Sentry catches Python exceptions inside the running app. The boot
failure fires BEFORE uvicorn binds, so Sentry never sees it. We need
a layer that watches the boot-log shape itself.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone

# Canonical boot-time foot-gun ops on autonomath.db (per CLAUDE.md SOT +
# memory feedback_no_quick_check_on_huge_sqlite). Any of these lines
# appearing in flyctl logs without a follow-up "ok" / "size-based skip"
# is a Wave-25-shape (RC1) incident.
FULL_SCAN_PATTERNS: tuple[str, ...] = (
    r"running integrity_check on /data/autonomath\.db",
    r"PRAGMA quick_check",
    r"VACUUM",
    r"REINDEX",
    r"ANALYZE",
)

# Lines that confirm the boot path escaped the trap — pattern in the
# log line resolves the "hung" state.
ESCAPE_PATTERNS: tuple[str, ...] = (
    r"size-based integrity_check skip",
    r"trusted stamp match for /data/autonomath\.db",
    r"integrity_check.*\bok\b",
)

# RC4 (Wave 40 shape): schema_guard FAIL messages. These are INSTANT
# fail signatures — no hang grace period. Any one match triggers an
# immediate alert. Patterns mirror the assertions in
# ``scripts/schema_guard.py`` (assert_jpintel_schema / assert_am_schema):
# the manifest superset gate catches the most common shape (RC4 proper)
# and broader checks cover schema drift.
SCHEMA_GUARD_FAIL_PATTERNS: tuple[str, ...] = (
    # RC4 proper: the canonical Wave 40 signature.
    r"required migrations missing from schema_migrations",
    # Forbidden table mistakenly shipped (jpintel/autonomath swap).
    r"FORBIDDEN table.*found",
    r"forbidden table.*present",
    # Required table absent on a fresh / corrupted volume.
    r"required table.*missing",
    r"missing required table",
    # Required column dropped or never added.
    r"required column.*missing",
    r"missing required column",
    # Prod row-count floor breached (silent truncate).
    r"row count.*below.*floor",
    # Entrypoint exit signal (catch-all).
    r"schema_guard\.py.*exit.*[1-9]",
    r"schema_guard.*FAIL",
)

# Number of seconds the full-scan line is allowed to sit without an
# escape line before we declare incident (RC1 grace).
HANG_THRESHOLD_SEC: int = 300

FLY_APP: str = os.environ.get("FLY_APP", "autonomath-api")
LOG_TAIL_LINES: int = int(os.environ.get("DB_BOOT_HANG_TAIL", "2000"))


@dataclass(frozen=True)
class FlyLogLine:
    """One parsed line of ``flyctl logs`` output."""

    ts: datetime
    message: str


def _parse_fly_ts(token: str) -> datetime | None:
    """Parse Fly's ISO-8601 log timestamps; return ``None`` on failure."""
    try:
        # Fly logs use 2026-05-11T11:40:23.123Z; tolerate both forms.
        if token.endswith("Z"):
            token = token[:-1] + "+00:00"
        return datetime.fromisoformat(token)
    except ValueError:
        return None


def fetch_recent_lines() -> list[FlyLogLine]:
    """Return the most recent flyctl log lines, parsed; empty on failure."""
    cmd = ["flyctl", "logs", "-a", FLY_APP, "--no-tail", "-n", str(LOG_TAIL_LINES)]
    try:
        proc = subprocess.run(  # noqa: S603 — flyctl is operator-trusted
            cmd, capture_output=True, text=True, timeout=120, check=False
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        print(f"[db_boot_hang_alert] flyctl invocation failed: {exc}", file=sys.stderr)
        return []
    if proc.returncode != 0:
        print(
            f"[db_boot_hang_alert] flyctl rc={proc.returncode} stderr={proc.stderr[:200]}",
            file=sys.stderr,
        )
        return []
    lines: list[FlyLogLine] = []
    for raw in proc.stdout.splitlines():
        parts = raw.strip().split(maxsplit=1)
        if len(parts) != 2:
            continue
        ts = _parse_fly_ts(parts[0])
        if ts is None:
            continue
        lines.append(FlyLogLine(ts=ts, message=parts[1]))
    return lines


def find_hung_full_scan(lines: list[FlyLogLine], now: datetime) -> FlyLogLine | None:
    """Return the latest full-scan line older than ``HANG_THRESHOLD_SEC`` with no escape after it.

    The Wave 25 (RC1) incident shape: ``running integrity_check on
    /data/autonomath.db`` appears at T+0 and is *never* followed by an
    escape pattern. After ``HANG_THRESHOLD_SEC`` the boot is wedged and
    the proxy is about to open the 40-attempt rotation. We page Telegram
    before the rotation.
    """
    full_re = re.compile("|".join(FULL_SCAN_PATTERNS))
    escape_re = re.compile("|".join(ESCAPE_PATTERNS))
    suspect: FlyLogLine | None = None
    for line in lines:
        if full_re.search(line.message):
            suspect = line
            continue
        if suspect is not None and escape_re.search(line.message):
            # Escape line landed AFTER suspect — the boot recovered, reset.
            suspect = None
    if suspect is None:
        return None
    if (now - suspect.ts).total_seconds() < HANG_THRESHOLD_SEC:
        return None
    return suspect


def find_schema_guard_fail(lines: list[FlyLogLine]) -> FlyLogLine | None:
    """Return the most-recent schema_guard FAIL line (RC4 shape).

    Wave 40 incident shape: ``autonomath: required migrations missing
    from schema_migrations: ['049_provenance_strengthen.sql', ...]``.
    This is an INSTANT fail — schema_guard exits non-zero immediately,
    Fly restart-loops the machine. No hang grace period; one match in
    the recent window is enough to page.

    Detection scope is broader than the RC4-proper shape — covers any
    schema_guard assertion that would block boot (forbidden table,
    required table missing, required column missing, row-count floor).
    """
    fail_re = re.compile("|".join(SCHEMA_GUARD_FAIL_PATTERNS))
    latest: FlyLogLine | None = None
    for line in lines:
        if fail_re.search(line.message):
            latest = line
    return latest


def send_telegram(text: str) -> bool:
    """Send a Telegram message via the bot API; return True on success."""
    token = os.environ.get("TG_BOT_TOKEN")
    chat_id = os.environ.get("TG_CHAT_ID")
    if not token or not chat_id:
        print(
            "[db_boot_hang_alert] TG_BOT_TOKEN / TG_CHAT_ID missing — alert skipped",
            file=sys.stderr,
        )
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = urllib.parse.urlencode(
        {"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": "true"}
    ).encode("utf-8")
    req = urllib.request.Request(  # noqa: S310 — telegram API host is fixed
        url, data=payload, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310
            return resp.status == 200
    except (urllib.error.URLError, TimeoutError) as exc:
        print(f"[db_boot_hang_alert] telegram send failed: {exc}", file=sys.stderr)
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Print result, do not send Telegram.")
    args = parser.parse_args()
    now = datetime.now(timezone.utc)
    lines = fetch_recent_lines()
    if not lines:
        # flyctl failed; do not page (avoid false positives on transient flyctl).
        print(json.dumps({"status": "noop", "reason": "no_log_lines", "ts": now.isoformat()}))
        return 0

    # RC1 — integrity_check hang shape (Wave 25 signature)
    rc1_suspect = find_hung_full_scan(lines, now)
    # RC4 — schema_guard FAIL shape (Wave 40 signature)
    rc4_suspect = find_schema_guard_fail(lines)

    if rc1_suspect is None and rc4_suspect is None:
        print(json.dumps({"status": "ok", "scanned": len(lines), "ts": now.isoformat()}))
        return 0

    # Build alert text(s) — both can fire in the same cron tick if a
    # cascade is in flight. We page once with both signals, so the
    # operator sees the full shape.
    pieces: list[str] = []
    payload: dict[str, object] = {
        "status": "alert",
        "scanned": len(lines),
        "ts": now.isoformat(),
    }

    if rc1_suspect is not None:
        age_sec = int((now - rc1_suspect.ts).total_seconds())
        pieces.append(
            f"<b>[jpcite SEV1] RC1 DB boot hang suspected</b>\n"
            f"App: <code>{FLY_APP}</code>\n"
            f"Log line ({age_sec}s old):\n<code>{rc1_suspect.message[:240]}</code>"
        )
        payload["rc1"] = {"age_sec": age_sec, "line": rc1_suspect.message}

    if rc4_suspect is not None:
        rc4_age_sec = int((now - rc4_suspect.ts).total_seconds())
        pieces.append(
            f"<b>[jpcite SEV1] RC4 schema_guard FAIL detected</b>\n"
            f"App: <code>{FLY_APP}</code>\n"
            f"Log line ({rc4_age_sec}s old):\n<code>{rc4_suspect.message[:240]}</code>"
        )
        payload["rc4"] = {"age_sec": rc4_age_sec, "line": rc4_suspect.message}

    text = "\n\n".join(pieces) + (
        "\n\nRunbook v2: docs/runbook/incident_response_db_boot_hang_v2.md\n"
        "Wave 18 §4 fix: 81922433f (RC1)\n"
        "Wave 40 PR #75 fix: 82df31bd8 (RC4)"
    )
    print(json.dumps(payload))
    if args.dry_run:
        return 1
    sent = send_telegram(text)
    return 0 if sent else 2


if __name__ == "__main__":
    sys.exit(main())
