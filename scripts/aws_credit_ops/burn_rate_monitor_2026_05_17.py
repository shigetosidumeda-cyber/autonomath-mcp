#!/usr/bin/env python3
"""Lane J — Real-time burn rate monitor for jpcite credit run.

Pulls Cost Explorer Usage + Credit (RECORD_TYPE filter), computes 24h-rolling
burn rate vs previous ledger tick, projects credit-exhaust day via linear
projection, and emits alerts if burn drifts off the $2,000-$3,000/day band.

Append-only ledger at:
    docs/_internal/AWS_BURN_LEDGER_2026_05_17.md

Read-only against AWS — never submits jobs, never mutates budgets.
The $19,490 Never-Reach line is enforced by Budget Action ($18,900) +
4-line CloudWatch alarms; this monitor is the watchdog cadence layer.

Usage:
    .venv/bin/python scripts/aws_credit_ops/burn_rate_monitor_2026_05_17.py --now
    .venv/bin/python scripts/aws_credit_ops/burn_rate_monitor_2026_05_17.py --json-only

Constraints:
  * AWS profile: bookyou-recovery (override with AWS_PROFILE env).
  * Cost Explorer region: us-east-1 (CE is global, but billing endpoint).
  * Credit envelope: $19,490 hard ceiling, $18,900 hard-stop, target burn
    $2,000-$3,000/day × 7 days (= $14K-$21K window, centered on $19,490).
  * NO LLM. Co-Authored-By: Claude Opus 4.7. [lane:solo].
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
LEDGER_PATH = REPO_ROOT / "docs" / "_internal" / "AWS_BURN_LEDGER_2026_05_17.md"

AWS_PROFILE = os.environ.get("AWS_PROFILE", "bookyou-recovery")
CE_REGION = "us-east-1"

# Burn band per operator explicit instruction.
TARGET_BURN_LO_USD_PER_DAY = 2000.0
TARGET_BURN_HI_USD_PER_DAY = 3000.0
ALERT_BURN_LO_USD_PER_DAY = 1500.0  # under this -> not on pace
ALERT_BURN_HI_USD_PER_DAY = 3500.0  # over this  -> over-spending
CREDIT_NEVER_REACH_USD = 19490.0
CREDIT_HARD_STOP_USD = 18900.0


def _run_ce(args: list[str]) -> dict[str, Any]:
    """Wrap a Cost Explorer call. Returns parsed JSON or {} on failure."""
    cmd = ["aws", "ce", *args, "--region", CE_REGION, "--output", "json"]
    env = {**os.environ, "AWS_PROFILE": AWS_PROFILE}
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, check=True, env=env)
        return json.loads(out.stdout or "{}")
    except subprocess.CalledProcessError as exc:
        print(
            f"[burn-monitor] CE call failed: {exc.stderr.strip()[:200]}",
            file=sys.stderr,
        )
        return {}
    except Exception as exc:
        print(f"[burn-monitor] CE call exception: {exc}", file=sys.stderr)
        return {}


def fetch_usage_window(start: str, end: str, granularity: str = "DAILY") -> float:
    """Fetch sum of Usage records (excludes credits/refunds) for [start, end)."""
    payload = _run_ce(
        [
            "get-cost-and-usage",
            "--time-period",
            f"Start={start},End={end}",
            "--granularity",
            granularity,
            "--metrics",
            "UnblendedCost",
            "--filter",
            '{"Dimensions":{"Key":"RECORD_TYPE","Values":["Usage"]}}',
        ]
    )
    total = 0.0
    for row in payload.get("ResultsByTime", []):
        amt = row.get("Total", {}).get("UnblendedCost", {}).get("Amount", "0")
        try:
            total += float(amt)
        except (TypeError, ValueError):
            continue
    return total


def fetch_credit_applied(start: str, end: str) -> float:
    """Fetch sum of Credit records (negative = credits applied) for [start, end)."""
    payload = _run_ce(
        [
            "get-cost-and-usage",
            "--time-period",
            f"Start={start},End={end}",
            "--granularity",
            "MONTHLY",
            "--metrics",
            "UnblendedCost",
            "--filter",
            '{"Dimensions":{"Key":"RECORD_TYPE","Values":["Credit"]}}',
        ]
    )
    total = 0.0
    for row in payload.get("ResultsByTime", []):
        amt = row.get("Total", {}).get("UnblendedCost", {}).get("Amount", "0")
        try:
            total += float(amt)
        except (TypeError, ValueError):
            continue
    # Credits are negative; flip sign so "credit applied" is a positive number.
    return -total


def previous_ledger_tick() -> dict[str, Any] | None:
    """Parse the most recent ledger JSON block. Returns None if no prior tick."""
    if not LEDGER_PATH.exists():
        return None
    text = LEDGER_PATH.read_text(encoding="utf-8")
    blocks = re.findall(r"```json\n(.*?)\n```", text, flags=re.DOTALL)
    if not blocks:
        return None
    try:
        return json.loads(blocks[-1])
    except json.JSONDecodeError:
        return None


def classify_burn(burn_per_day: float) -> tuple[str, str]:
    """Return (state, reason) for the current 24h burn rate."""
    if burn_per_day > ALERT_BURN_HI_USD_PER_DAY:
        return "OVER_BUDGET", (
            f"burn ${burn_per_day:,.2f}/day > ${ALERT_BURN_HI_USD_PER_DAY:,.0f}/day"
            " (slow down ramp)"
        )
    if burn_per_day < ALERT_BURN_LO_USD_PER_DAY:
        return "UNDER_PACE", (
            f"burn ${burn_per_day:,.2f}/day < ${ALERT_BURN_LO_USD_PER_DAY:,.0f}/day"
            " (credit will not exhaust)"
        )
    if burn_per_day > TARGET_BURN_HI_USD_PER_DAY or burn_per_day < TARGET_BURN_LO_USD_PER_DAY:
        return "OFF_TARGET", (
            f"burn ${burn_per_day:,.2f}/day outside target band "
            f"${TARGET_BURN_LO_USD_PER_DAY:,.0f}-${TARGET_BURN_HI_USD_PER_DAY:,.0f}/day"
        )
    return "ON_TARGET", (
        f"burn ${burn_per_day:,.2f}/day inside target band "
        f"${TARGET_BURN_LO_USD_PER_DAY:,.0f}-${TARGET_BURN_HI_USD_PER_DAY:,.0f}/day"
    )


def project_exhaust(burn_per_day: float, credit_remaining_usd: float) -> str:
    """Linear projection of credit exhaust calendar date."""
    if burn_per_day <= 0.0 or credit_remaining_usd <= 0.0:
        return "never (zero burn or zero credit)"
    days = credit_remaining_usd / burn_per_day
    exhaust = dt.datetime.now(dt.UTC) + dt.timedelta(days=days)
    return f"{exhaust.strftime('%Y-%m-%d')} ({days:,.1f} days from now)"


def build_tick(now: dt.datetime) -> dict[str, Any]:
    """Compute one monitor tick. All amounts in USD."""
    today = now.strftime("%Y-%m-%d")
    yesterday = (now - dt.timedelta(days=1)).strftime("%Y-%m-%d")
    month_start = now.strftime("%Y-%m-01")
    tomorrow = (now + dt.timedelta(days=1)).strftime("%Y-%m-%d")

    usage_24h = fetch_usage_window(yesterday, today)
    usage_today_partial = fetch_usage_window(today, tomorrow)
    usage_mtd = fetch_usage_window(month_start, tomorrow)
    credit_applied_mtd = fetch_credit_applied(month_start, tomorrow)

    credit_remaining = max(CREDIT_NEVER_REACH_USD - credit_applied_mtd, 0.0)
    state, reason = classify_burn(usage_24h)
    exhaust = project_exhaust(usage_24h, credit_remaining)

    prev = previous_ledger_tick()
    burn_delta_per_hour: float | None = None
    if prev is not None:
        try:
            prev_usage_mtd = float(prev.get("usage_mtd_usd", 0.0))
            prev_ts = dt.datetime.fromisoformat(prev["ts"].replace("Z", "+00:00"))
            now_ts = now.replace(tzinfo=dt.UTC) if now.tzinfo is None else now
            hours = max((now_ts - prev_ts).total_seconds() / 3600.0, 1e-6)
            burn_delta_per_hour = (usage_mtd - prev_usage_mtd) / hours
        except (KeyError, ValueError, TypeError):
            burn_delta_per_hour = None

    tick: dict[str, Any] = {
        "ts": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "window_24h": {"start": yesterday, "end": today},
        "usage_24h_usd": round(usage_24h, 2),
        "usage_today_partial_usd": round(usage_today_partial, 2),
        "usage_mtd_usd": round(usage_mtd, 2),
        "credit_applied_mtd_usd": round(credit_applied_mtd, 2),
        "credit_remaining_usd": round(credit_remaining, 2),
        "burn_per_day_usd": round(usage_24h, 2),
        "burn_band_target": {
            "lo": TARGET_BURN_LO_USD_PER_DAY,
            "hi": TARGET_BURN_HI_USD_PER_DAY,
        },
        "burn_band_alert": {
            "lo": ALERT_BURN_LO_USD_PER_DAY,
            "hi": ALERT_BURN_HI_USD_PER_DAY,
        },
        "state": state,
        "reason": reason,
        "projection_exhaust": exhaust,
        "credit_never_reach_usd": CREDIT_NEVER_REACH_USD,
        "credit_hard_stop_usd": CREDIT_HARD_STOP_USD,
        "delta_vs_prev_tick_usd_per_hour": (
            round(burn_delta_per_hour, 4) if burn_delta_per_hour is not None else None
        ),
        "ce_lag_disclaimer": (
            "Cost Explorer carries 24-48h lag; today's partial figure"
            " under-represents real spend. Trust 24h rolling band only."
        ),
    }
    return tick


def append_to_ledger(tick: dict[str, Any]) -> None:
    """Append-only markdown ledger. Never rewrites prior ticks."""
    LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not LEDGER_PATH.exists():
        header = (
            "# AWS Burn Ledger — Lane J (2026-05-17)\n\n"
            "Append-only burn-rate ticks for jpcite credit run. Read-only against AWS.\n"
            "Cadence: 1 tick / hour via EventBridge `jpcite-credit-burn-monitor-hourly`.\n"
            "Target band: $2,000-$3,000/day × 7 days. Hard-stop $18,900 / Never-reach $19,490.\n\n"
            "Each entry: JSON block + state markers (OVER_BUDGET / UNDER_PACE /"
            " OFF_TARGET / ON_TARGET).\n\n"
            "---\n\n"
        )
        LEDGER_PATH.write_text(header, encoding="utf-8")

    state = tick.get("state", "?")
    ts = tick.get("ts", "?")
    burn = tick.get("burn_per_day_usd", 0.0)
    proj = tick.get("projection_exhaust", "?")
    block = (
        f"## tick {ts} — {state}\n\n"
        f"- burn 24h: ${burn:,.2f}/day\n"
        f"- credit remaining: ${tick.get('credit_remaining_usd', 0.0):,.2f}"
        f" / ${CREDIT_NEVER_REACH_USD:,.0f} never-reach\n"
        f"- projection: exhaust {proj}\n"
        f"- reason: {tick.get('reason', '')}\n\n"
        "```json\n"
        f"{json.dumps(tick, indent=2, ensure_ascii=False)}\n"
        "```\n\n"
    )
    with LEDGER_PATH.open("a", encoding="utf-8") as fh:
        fh.write(block)


def main() -> int:
    parser = argparse.ArgumentParser(description="jpcite Lane J burn rate monitor")
    parser.add_argument(
        "--now",
        action="store_true",
        help="Run one tick immediately and append to ledger",
    )
    parser.add_argument(
        "--json-only",
        action="store_true",
        help="Emit JSON tick to stdout, do NOT append to ledger",
    )
    args = parser.parse_args()

    now = dt.datetime.now(dt.UTC)
    tick = build_tick(now)

    if args.json_only:
        print(json.dumps(tick, indent=2, ensure_ascii=False))
        return 0

    append_to_ledger(tick)
    print(
        f"[burn-monitor] tick {tick['ts']} state={tick['state']}"
        f" burn=${tick['burn_per_day_usd']:,.2f}/day"
        f" credit_remaining=${tick['credit_remaining_usd']:,.2f}"
        f" exhaust={tick['projection_exhaust']}"
    )
    # Non-zero exit on alert states so EventBridge can surface failure.
    if tick["state"] in {"OVER_BUDGET", "UNDER_PACE"}:
        return 2
    if tick["state"] == "OFF_TARGET":
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
