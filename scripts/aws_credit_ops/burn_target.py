#!/usr/bin/env python3
"""Hourly burn target calculator for jpcite credit run.

Inputs:
  --total USD remaining target (default 18,300)
  --consumed USD already consumed gross (default queries Cost Explorer)
  --days remaining (default to 2026-05-29 - today)

Output: hourly burn rate target + slowdown/stop guidance.
"""
from __future__ import annotations
import argparse
import datetime as dt
import json
import subprocess
import sys


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--target", type=float, default=18300.0)
    p.add_argument("--deadline", default="2026-05-29")
    p.add_argument("--consumed", type=float, default=None)
    args = p.parse_args()

    if args.consumed is None:
        # Best-effort: query Cost Explorer month-to-date GROSS
        start = dt.datetime.utcnow().strftime("%Y-%m-01")
        end = (dt.datetime.utcnow() + dt.timedelta(days=1)).strftime("%Y-%m-%d")
        try:
            out = subprocess.run(
                ["aws", "ce", "get-cost-and-usage", "--region", "us-east-1",
                 "--time-period", f"Start={start},End={end}",
                 "--granularity", "MONTHLY", "--metrics", "UnblendedCost"],
                capture_output=True, text=True, check=True,
            )
            d = json.loads(out.stdout)
            args.consumed = float(d["ResultsByTime"][0]["Total"]["UnblendedCost"]["Amount"])
        except Exception as e:
            print(f"warn: could not query CE ({e}); using --consumed 0", file=sys.stderr)
            args.consumed = 0.0

    remaining = max(args.target - args.consumed, 0.0)
    deadline = dt.datetime.strptime(args.deadline, "%Y-%m-%d")
    now = dt.datetime.utcnow()
    days_left = max((deadline - now).days, 1)
    hours_left = max((deadline - now).total_seconds() / 3600, 1)

    daily_target = remaining / days_left if days_left else remaining
    hourly_target = remaining / hours_left

    print(f"target gross: USD {args.target:,.2f}")
    print(f"consumed gross MTD: USD {args.consumed:,.2f}")
    print(f"remaining: USD {remaining:,.2f}")
    print(f"days to deadline ({args.deadline}): {days_left}")
    print(f"daily burn target: USD {daily_target:,.2f}/day")
    print(f"hourly burn target: USD {hourly_target:,.2f}/hr")
    slowdown = 0.85 * args.target
    stop = 0.95 * args.target
    print(f"slowdown line: USD {slowdown:,.2f}")
    print(f"emergency stop line: USD {stop:,.2f}")
    if args.consumed >= stop:
        print("STATUS: STOP — emergency line crossed")
        return 1
    if args.consumed >= slowdown:
        print("STATUS: SLOWDOWN — no new ramp")
        return 2
    print("STATUS: RAMP — within budget")
    return 0


if __name__ == "__main__":
    sys.exit(main())
