#!/usr/bin/env python3
"""PERF-42 CI runtime budget gate.

Pulls every job in the current GitHub Actions workflow run via the REST API
and fails (exit 1) if the wall-clock duration (max completed_at minus min
started_at, excluding this gate's own job) exceeds
``JPCITE_CI_BUDGET_MINUTES`` (default 15).

Wall clock is the right metric because the dev waiting on a green check
experiences max-critical-path latency including queue time, not the sum of
billable minutes. The per-job durations are still printed for triage so the
operator can see which job is the longest pole.

The analyzer also exposes a ``--local-summary`` mode that simply prints the
budget without invoking the GH API — useful as a sanity probe from a
developer shell or from ``make ci-budget-check``.

No external dependencies; uses ``urllib`` + stdlib JSON only so the gate's
own runtime stays under 30 seconds with zero install overhead.

Honoured env:

* ``GH_TOKEN`` or ``GITHUB_TOKEN`` — auth for the REST API.
* ``GITHUB_REPOSITORY`` — owner/repo (set automatically in GH Actions).
* ``GITHUB_RUN_ID`` — workflow run id (set automatically in GH Actions).
* ``JPCITE_CI_BUDGET_MINUTES`` — wall-clock cap. Default 15.
* ``JPCITE_CI_BUDGET_EXCLUDE`` — comma-separated job-name substrings to
  exclude from the calculation. Defaults to ``ci-budget`` so this job
  doesn't self-account.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import UTC, datetime
from typing import Any

API_VERSION = "2022-11-28"
DEFAULT_BUDGET_MINUTES = 15
DEFAULT_EXCLUDES = "ci-budget"


def _parse_iso(ts: str | None) -> datetime | None:
    """Parse the GH REST API ISO-8601 timestamp ('Z' suffix) to UTC datetime."""
    if not ts:
        return None
    # GH API uses '2026-05-17T01:23:45Z'; fromisoformat needs +00:00 in 3.10.
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(UTC)


def _gh_get(url: str, token: str) -> dict[str, Any]:
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": API_VERSION,
            "User-Agent": "jpcite-ci-budget/1.0",
        },
    )
    # Hard-coded api.github.com only — no user-controlled scheme, file://, or
    # http:// can reach this call site. Silenced both ruff S310 and bandit B310
    # because the input is constructed from GH-provided GITHUB_REPOSITORY +
    # GITHUB_RUN_ID env vars (set by the runner, not the workflow author).
    with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310  # nosec B310
        data: dict[str, Any] = json.loads(resp.read().decode("utf-8"))
        return data


def _list_jobs(repo: str, run_id: str, token: str) -> list[dict[str, Any]]:
    """Page through /actions/runs/{run_id}/jobs (max 100 per page, follows next)."""
    jobs: list[dict[str, Any]] = []
    page = 1
    while True:
        url = f"https://api.github.com/repos/{repo}/actions/runs/{run_id}/jobs?per_page=100&page={page}"
        body = _gh_get(url, token)
        page_jobs = body.get("jobs", [])
        if not page_jobs:
            break
        jobs.extend(page_jobs)
        if len(page_jobs) < 100:
            break
        page += 1
    return jobs


def evaluate(
    jobs: list[dict[str, Any]], budget_minutes: float, excludes: list[str]
) -> tuple[bool, dict[str, Any]]:
    """Return (within_budget, summary_dict) for a list of GH job dicts.

    A job is excluded if any substring in ``excludes`` matches its ``name``
    (case-insensitive) — typically to drop the gate's own job from the
    accounting so the gate doesn't fight itself.
    """
    rows: list[dict[str, Any]] = []
    earliest_start: datetime | None = None
    latest_end: datetime | None = None
    for j in jobs:
        name = j.get("name") or "<unnamed>"
        if any(ex.lower() in name.lower() for ex in excludes if ex):
            rows.append({"name": name, "duration_sec": None, "excluded": True})
            continue
        start = _parse_iso(j.get("started_at"))
        end = _parse_iso(j.get("completed_at"))
        if start and end:
            dur = (end - start).total_seconds()
            rows.append(
                {
                    "name": name,
                    "duration_sec": round(dur, 1),
                    "status": j.get("conclusion") or j.get("status"),
                    "excluded": False,
                }
            )
            if earliest_start is None or start < earliest_start:
                earliest_start = start
            if latest_end is None or end > latest_end:
                latest_end = end
        else:
            rows.append({"name": name, "duration_sec": None, "in_flight": True})

    wall_seconds = 0.0
    if earliest_start and latest_end:
        wall_seconds = (latest_end - earliest_start).total_seconds()

    budget_seconds = budget_minutes * 60.0
    within_budget = wall_seconds <= budget_seconds
    summary = {
        "wall_clock_seconds": round(wall_seconds, 1),
        "wall_clock_minutes": round(wall_seconds / 60.0, 2),
        "budget_minutes": budget_minutes,
        "within_budget": within_budget,
        "earliest_start": earliest_start.isoformat() if earliest_start else None,
        "latest_end": latest_end.isoformat() if latest_end else None,
        "jobs": sorted(
            rows,
            key=lambda r: r.get("duration_sec") or 0,
            reverse=True,
        ),
    }
    return within_budget, summary


def _print_summary(summary: dict[str, Any]) -> None:
    print("=" * 70)
    print("PERF-42 CI runtime budget gate")
    print("=" * 70)
    print(f"  budget: {summary['budget_minutes']:.1f} min")
    print(
        f"  wall clock: {summary['wall_clock_minutes']:.2f} min "
        f"({summary['wall_clock_seconds']:.1f}s)"
    )
    print(f"  verdict: {'WITHIN BUDGET' if summary['within_budget'] else 'OVER BUDGET'}")
    print()
    print("  Per-job durations (longest first):")
    for row in summary["jobs"]:
        flags = []
        if row.get("excluded"):
            flags.append("excluded")
        if row.get("in_flight"):
            flags.append("in-flight")
        flag_str = f" [{', '.join(flags)}]" if flags else ""
        dur = row.get("duration_sec")
        dur_str = f"{dur:>7.1f}s" if dur is not None else "      n/a"
        status = row.get("status") or "?"
        print(f"    {dur_str}  {status:>10s}  {row['name']}{flag_str}")
    print("=" * 70)


def main() -> int:
    budget_minutes = float(os.environ.get("JPCITE_CI_BUDGET_MINUTES", DEFAULT_BUDGET_MINUTES))
    excludes = [
        s.strip()
        for s in os.environ.get("JPCITE_CI_BUDGET_EXCLUDE", DEFAULT_EXCLUDES).split(",")
        if s.strip()
    ]

    if "--local-summary" in sys.argv:
        print(f"[ci-budget] local summary: budget={budget_minutes:.1f} min, excludes={excludes!r}")
        print("[ci-budget] (no GH API call; use inside GH Actions for live job data)")
        return 0

    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY")
    run_id = os.environ.get("GITHUB_RUN_ID")
    if not (token and repo and run_id):
        print(
            "[ci-budget] ERROR: GH_TOKEN/GITHUB_TOKEN + GITHUB_REPOSITORY + "
            "GITHUB_RUN_ID required (run inside GH Actions or pass --local-summary).",
            file=sys.stderr,
        )
        return 2

    try:
        jobs = _list_jobs(repo, run_id, token)
    except urllib.error.HTTPError as exc:
        print(f"[ci-budget] ERROR: GH API HTTP {exc.code}: {exc.reason}", file=sys.stderr)
        return 2
    except urllib.error.URLError as exc:
        print(f"[ci-budget] ERROR: GH API URL error: {exc.reason}", file=sys.stderr)
        return 2

    within_budget, summary = evaluate(jobs, budget_minutes, excludes)
    _print_summary(summary)

    if not within_budget:
        print(
            f"[ci-budget] FAIL: wall clock {summary['wall_clock_minutes']:.2f} min > "
            f"budget {budget_minutes:.1f} min. Pick the longest pole and shrink it "
            "or push JPCITE_CI_BUDGET_MINUTES (do NOT delete this gate).",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
