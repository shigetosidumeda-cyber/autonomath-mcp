#!/usr/bin/env python3
"""Wave 46 §G — lane-policy warn checker (non-blocking, PR-side companion).

Companion to scripts/ops/lane_policy_enforcer.py: that script *blocks* a
commit on path-set violations. This one *warns* (rc=0 always, write
GITHUB_STEP_SUMMARY) when the PR branch name advertises a lane that has
≥2 active lock records in AGENT_LEDGER.csv — i.e. another concurrent
agent claimed the same lane and the new PR is racing it. This catches
the dual-CLI lane-collision case before reviewers see it.

Branch convention (looked up first via $GITHUB_HEAD_REF, then --branch):
    feat/jpcite_<YYYY_MM_DD>_wave<NN>_<lane>_<slug>

Examples that resolve to lane='ams':
    feat/jpcite_2026_05_12_wave46_ams_w43_bench
    feat/jpcite_2026_05_12_wave43_5_ams_monthly_cron

LLM API calls = 0. stdlib + git only. Non-blocking by design.

Exit codes:
    0 = success (warn rows go to GITHUB_STEP_SUMMARY + stdout)
    2 = configuration error (ledger malformed, branch unparseable for
        --strict mode only; default mode swallows these as rc=0 + warn)
"""

from __future__ import annotations

import argparse
import csv
import os
import pathlib
import re
import sys
from collections import Counter

LEDGER_REL_DEFAULT = "tools/offline/_inbox/value_growth_dual/AGENT_LEDGER.csv"

# Wave-aware branch shape; lane = the token immediately after waveNN[_M]_.
# Anchored loose so historical branches (wave43_5, wave46) both parse.
_BRANCH_RE = re.compile(
    r"^feat/jpcite_(?P<date>\d{4}_\d{2}_\d{2})_wave(?P<wave>\d+(?:_\d+)?)_(?P<lane>[a-z][a-z0-9]*?)(?:_[A-Za-z0-9_]+)?$"
)


def parse_lane_from_branch(branch: str) -> str | None:
    """Return lane slug extracted from a branch name, or None if unparseable."""
    if not branch:
        return None
    m = _BRANCH_RE.match(branch.strip())
    if not m:
        return None
    return m.group("lane")


def read_ledger(ledger_path: pathlib.Path) -> list[dict[str, str]]:
    """Return AGENT_LEDGER.csv rows as dicts; empty list if missing."""
    if not ledger_path.is_file():
        return []
    with ledger_path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        return [dict(row) for row in reader]


def count_active_locks(rows: list[dict[str, str]], lane: str) -> int:
    """Count rows in AGENT_LEDGER for the given lane with violation_count == 0."""
    n = 0
    for row in rows:
        if row.get("lane") != lane:
            continue
        vc = row.get("violation_count", "0").strip()
        if vc == "0":
            n += 1
    return n


def summarize_lanes(rows: list[dict[str, str]]) -> Counter:
    """Return Counter of active (violation_count==0) locks keyed by lane."""
    c: Counter = Counter()
    for row in rows:
        if (row.get("violation_count", "0").strip()) == "0":
            lane = row.get("lane", "")
            if lane:
                c[lane] += 1
    return c


def write_summary(text: str) -> None:
    """Append to $GITHUB_STEP_SUMMARY if set; else print to stdout."""
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write(text + "\n")
    print(text)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Wave 46 §G lane-policy warn check")
    p.add_argument(
        "--branch",
        default=os.environ.get("GITHUB_HEAD_REF", ""),
        help="PR branch name (default: $GITHUB_HEAD_REF)",
    )
    p.add_argument(
        "--ledger",
        default=LEDGER_REL_DEFAULT,
        help=f"AGENT_LEDGER.csv path (default: {LEDGER_REL_DEFAULT})",
    )
    p.add_argument(
        "--strict",
        action="store_true",
        help="exit 2 on unparseable branch or missing ledger (default: rc=0 + warn)",
    )
    args = p.parse_args(argv)

    branch = args.branch
    lane = parse_lane_from_branch(branch)
    ledger_path = pathlib.Path(args.ledger)
    rows = read_ledger(ledger_path)

    lines: list[str] = ["## Wave 46 §G — lane-policy warn check"]
    lines.append("")
    lines.append(f"- branch: `{branch or '(unset)'}`")
    lines.append(f"- ledger: `{ledger_path}` (rows={len(rows)})")
    if lane is None:
        lines.append(
            "- lane: **(unparseable)** — branch does not match `feat/jpcite_<date>_wave<NN>_<lane>_*`"
        )
        write_summary("\n".join(lines))
        return 2 if args.strict else 0

    lines.append(f"- lane: `{lane}`")

    if not rows:
        lines.append("- ledger empty — nothing to check (first lane claim).")
        write_summary("\n".join(lines))
        return 0

    n = count_active_locks(rows, lane)
    lines.append(f"- active locks for `{lane}`: **{n}**")

    if n >= 2:
        lines.append("")
        lines.append(
            f"warn: lane `{lane}` has {n} active locks. concurrent agents may collide on the same lane. "
            "verify AGENT_LEDGER.csv before merge."
        )
        # full lane table for context
        summary = summarize_lanes(rows)
        lines.append("")
        lines.append("| lane | active_locks |")
        lines.append("|------|--------------|")
        for k, v in sorted(summary.items(), key=lambda kv: (-kv[1], kv[0])):
            mark = " <-- this PR" if k == lane else ""
            lines.append(f"| `{k}` | {v}{mark} |")
    else:
        lines.append(f"- ok: lane `{lane}` has {n} active lock(s), no collision.")

    write_summary("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
