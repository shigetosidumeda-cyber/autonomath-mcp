#!/usr/bin/env python3
"""DB boot failure watchdog — detects Wave 25 + Wave 40 + Wave 45 outage shapes.

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

Wave 40 (2026-05-11/12 14h+ outage / RC3 in v3 framing; RC4 in v2):
Wave 22 baked-seed deployments on fresh volumes produced
``autonomath.db`` without the 5 ``AM_REQUIRED_MIGRATIONS`` recorded in
``schema_migrations``. ``schema_guard`` exits non-zero with
``autonomath: required migrations missing from schema_migrations: [...]``
and Fly restart-loops the machine. The Wave 25 watchdog did NOT alert
because the boot pattern was different — schema_guard exits cleanly
(non-zero rc) rather than hanging. Wave 41 extended this watchdog to
detect both shapes.

Wave 45 (2026-05-12 18h+ outage / RC4 + RC5 in v3 framing): even after
Wave 18 + Wave 40 fixes landed, the deploy chain stayed broken for
~4 hours of partial degradation because (a) GHA ``workflow_run``
guards on subsidiary verify workflows mis-skipped under Strategy F
(``workflow_dispatch``) parent — the operator saw "verify: skipped"
in CI even though api was healthy (RC4 surface); and (b) Wave 42-43
parallel-agent branches generated merge conflicts on PRs #97 / #100 /
#102 that each took 20-40 min to clear, blocking the Strategy F retry
pipeline (RC5 surface). Wave 45 extends this watchdog to detect both
RC4 (GHA skipped post-deploy verify) and RC5 (open PR conflict during
deploy window) in addition to the existing RC1 + RC3.

This script is the daily watchdog. It tails ``flyctl logs`` + ``gh
run list`` + ``gh pr list`` and notifies via Telegram + Slack if ANY
of the 5 RC patterns fire:

1. **RC1 hang shape**: any canonical full-scan boot-op log line
   appears for more than 5 minutes without a follow-up ``ok`` /
   ``size-based skip`` / ``trusted stamp match`` line.
2. **RC2 deploy-infra shape**: ``flyctl deploy`` parent run in GHA
   shows ``in_progress`` for ≥30 min (depot builder stall signature).
   Detected via ``gh run list --workflow=deploy.yml -L 5`` looking
   for ``status=in_progress`` with ``createdAt`` older than 30 min.
3. **RC3 schema_guard FAIL shape**: a ``required migrations missing
   from schema_migrations`` line appears at any point in the recent
   log window. Unlike (1), FAIL is instant — there is no hang grace
   period; the entrypoint exits immediately. Also catches the broader
   ``schema_guard`` family of FAIL messages.
4. **RC4 CI chain skip shape**: post-deploy verify workflows show
   ``conclusion=skipped`` while ``deploy.yml`` shows ``success``.
   Detected via ``gh run list -L 20 --json``.
5. **RC5 PR conflict shape**: two or more open PRs marked
   ``mergeable=CONFLICTING`` during a deploy window (last 60 min).
   Detected via ``gh pr list --search 'is:open conflict'``.

Either shape gives the operator a 25+ min head-start over external
uptime detection.

Operator gating
---------------
- Telegram secrets: ``TG_BOT_TOKEN`` + ``TG_CHAT_ID``. Slack secret:
  ``SLACK_WEBHOOK_URL``. Missing secrets cause a structured warning
  and a clean exit code 0 (do not red-line cron). Operator inventory
  must mirror them via ``.env.local`` SOT.
- Read-only: this script NEVER mutates Fly or GitHub state. It only
  reads logs and PR/run metadata.
- Cron cadence: daily at 06:00 JST via ``.github/workflows/`` cron.

Why not Sentry?
---------------
Sentry catches Python exceptions inside the running app. The boot
failure fires BEFORE uvicorn binds, so Sentry never sees it. Also,
RC4/RC5 are GitHub-side signals — Sentry has no visibility into CI
chain skips or PR conflicts. We need a layer that watches these
boot-log + CI-meta shapes itself.
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
from datetime import datetime, timedelta, timezone

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

# RC3 (Wave 40 shape; v2 numbered this RC4): schema_guard FAIL messages.
# These are INSTANT fail signatures — no hang grace period. Any one
# match triggers an immediate alert. Patterns mirror the assertions in
# ``scripts/schema_guard.py`` (assert_jpintel_schema / assert_am_schema):
# the manifest superset gate catches the most common shape (RC3 proper)
# and broader checks cover schema drift.
SCHEMA_GUARD_FAIL_PATTERNS: tuple[str, ...] = (
    # RC3 proper: the canonical Wave 40 signature.
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

# Wave 45 thresholds for the new RC patterns.
# RC2: deploy.yml run stuck in_progress for ≥30 min → depot stall suspect.
DEPLOY_INPROGRESS_THRESHOLD_SEC: int = 1800
# RC4: post-deploy verify "skipped" while deploy.yml "success" → CI chain skip.
# Names of workflows we expect to run after deploy.yml. If any of these
# shows conclusion=skipped within 30 min of a successful deploy.yml,
# we suspect RC4.
POST_DEPLOY_VERIFY_WORKFLOWS: tuple[str, ...] = (
    "verify",
    "verify.yml",
    "acceptance",
    "acceptance-criteria",
    "smoke",
    "post-deploy-verify",
    "post-deploy-verify-v4",
    "static-drift-and-runtime-probe",
)
CI_SKIP_LOOKBACK_SEC: int = 1800
# RC5: open PR conflict during a deploy window. Deploy window = last
# 60 min of deploy.yml activity (in_progress or success).
PR_CONFLICT_DEPLOY_WINDOW_SEC: int = 3600
PR_CONFLICT_MIN_COUNT: int = 2

FLY_APP: str = os.environ.get("FLY_APP", "autonomath-api")
LOG_TAIL_LINES: int = int(os.environ.get("DB_BOOT_HANG_TAIL", "2000"))
DEPLOY_WORKFLOW_FILE: str = os.environ.get("DEPLOY_WORKFLOW", "deploy.yml")


@dataclass(frozen=True)
class FlyLogLine:
    """One parsed line of ``flyctl logs`` output."""

    ts: datetime
    message: str


@dataclass(frozen=True)
class GhRun:
    """One row from ``gh run list --json``."""

    db_id: int
    name: str
    status: str
    conclusion: str
    created_at: datetime


@dataclass(frozen=True)
class GhPr:
    """One row from ``gh pr list --json``."""

    number: int
    title: str
    mergeable: str


def _parse_fly_ts(token: str) -> datetime | None:
    """Parse Fly's ISO-8601 log timestamps; return ``None`` on failure."""
    try:
        # Fly logs use 2026-05-11T11:40:23.123Z; tolerate both forms.
        if token.endswith("Z"):
            token = token[:-1] + "+00:00"
        return datetime.fromisoformat(token)
    except ValueError:
        return None


def _parse_iso8601(token: str) -> datetime | None:
    """Parse a generic ISO-8601 timestamp (gh CLI format); UTC return."""
    if not token:
        return None
    try:
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


def fetch_recent_gh_runs(limit: int = 30) -> list[GhRun]:
    """Return recent gh workflow runs across all workflows; empty on failure.

    Used for both RC2 (deploy.yml in_progress stall) and RC4 (post-deploy
    verify skipped). One shared fetch reduces gh API rate impact.
    """
    cmd = [
        "gh",
        "run",
        "list",
        "-L",
        str(limit),
        "--json",
        "databaseId,name,status,conclusion,createdAt,workflowName",
    ]
    try:
        proc = subprocess.run(  # noqa: S603 — gh is operator-trusted
            cmd, capture_output=True, text=True, timeout=60, check=False
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        print(f"[db_boot_hang_alert] gh runs invocation failed: {exc}", file=sys.stderr)
        return []
    if proc.returncode != 0:
        print(
            f"[db_boot_hang_alert] gh run list rc={proc.returncode} stderr={proc.stderr[:200]}",
            file=sys.stderr,
        )
        return []
    try:
        rows = json.loads(proc.stdout or "[]")
    except json.JSONDecodeError as exc:
        print(f"[db_boot_hang_alert] gh runs JSON parse failed: {exc}", file=sys.stderr)
        return []
    runs: list[GhRun] = []
    for row in rows:
        ts = _parse_iso8601(row.get("createdAt", ""))
        if ts is None:
            continue
        # gh returns either "name" (workflow display name) or "workflowName".
        # Normalize on the first non-empty.
        name = row.get("workflowName") or row.get("name") or ""
        runs.append(
            GhRun(
                db_id=int(row.get("databaseId", 0) or 0),
                name=str(name),
                status=str(row.get("status", "")),
                conclusion=str(row.get("conclusion", "") or ""),
                created_at=ts,
            )
        )
    return runs


def fetch_conflicting_prs() -> list[GhPr]:
    """Return open PRs flagged as CONFLICTING by GitHub; empty on failure."""
    cmd = [
        "gh",
        "pr",
        "list",
        "--search",
        "is:open",
        "-L",
        "50",
        "--json",
        "number,title,mergeable",
    ]
    try:
        proc = subprocess.run(  # noqa: S603 — gh is operator-trusted
            cmd, capture_output=True, text=True, timeout=60, check=False
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        print(f"[db_boot_hang_alert] gh prs invocation failed: {exc}", file=sys.stderr)
        return []
    if proc.returncode != 0:
        print(
            f"[db_boot_hang_alert] gh pr list rc={proc.returncode} stderr={proc.stderr[:200]}",
            file=sys.stderr,
        )
        return []
    try:
        rows = json.loads(proc.stdout or "[]")
    except json.JSONDecodeError as exc:
        print(f"[db_boot_hang_alert] gh prs JSON parse failed: {exc}", file=sys.stderr)
        return []
    conflicts: list[GhPr] = []
    for row in rows:
        mergeable = str(row.get("mergeable", ""))
        if mergeable != "CONFLICTING":
            continue
        conflicts.append(
            GhPr(
                number=int(row.get("number", 0) or 0),
                title=str(row.get("title", "")),
                mergeable=mergeable,
            )
        )
    return conflicts


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
    """Return the most-recent schema_guard FAIL line (RC3 shape).

    Wave 40 incident shape: ``autonomath: required migrations missing
    from schema_migrations: ['049_provenance_strengthen.sql', ...]``.
    This is an INSTANT fail — schema_guard exits non-zero immediately,
    Fly restart-loops the machine. No hang grace period; one match in
    the recent window is enough to page.

    Detection scope is broader than the RC3-proper shape — covers any
    schema_guard assertion that would block boot (forbidden table,
    required table missing, required column missing, row-count floor).
    """
    fail_re = re.compile("|".join(SCHEMA_GUARD_FAIL_PATTERNS))
    latest: FlyLogLine | None = None
    for line in lines:
        if fail_re.search(line.message):
            latest = line
    return latest


def find_deploy_stall(runs: list[GhRun], now: datetime) -> GhRun | None:
    """Return the deploy.yml run stuck in_progress beyond the threshold (RC2 shape).

    The Wave 25 RC2 incident shape: ``flyctl deploy`` (or GHA
    deploy.yml) hangs in build-context upload for 30-60 min. If gh
    shows the deploy.yml workflow ``status=in_progress`` and ``createdAt``
    older than ``DEPLOY_INPROGRESS_THRESHOLD_SEC``, that is a stall.
    """
    threshold = timedelta(seconds=DEPLOY_INPROGRESS_THRESHOLD_SEC)
    for run in runs:
        # The deploy workflow can be named "Deploy", "deploy.yml", etc.
        # Match loosely on the workflow file name fragment.
        if "deploy" not in run.name.lower():
            continue
        if run.status != "in_progress":
            continue
        if now - run.created_at < threshold:
            continue
        return run
    return None


def find_skipped_post_deploy_verify(runs: list[GhRun], now: datetime) -> list[GhRun]:
    """Return post-deploy verify workflows that were skipped right after a successful deploy (RC4 shape).

    Wave 45 RC4 incident shape: ``deploy.yml`` runs green via Strategy
    F (``workflow_dispatch``) but downstream chained workflows
    (verify / acceptance / smoke) show ``conclusion=skipped`` because
    their ``workflow_run`` guard mis-evaluates the dispatch parent.
    The operator sees "green deploy + skipped verify" and cannot
    confirm health from CI alone.

    Logic:
    - find a successful ``deploy.yml`` run within ``CI_SKIP_LOOKBACK_SEC``
    - among the SAME-window runs, list any post-deploy verify
      workflow with ``conclusion=skipped``
    - if any found, page (a single deploy → ≥1 skipped verify is
      enough to suspect RC4)
    """
    lookback = timedelta(seconds=CI_SKIP_LOOKBACK_SEC)
    recent_successful_deploy = False
    for run in runs:
        if "deploy" not in run.name.lower():
            continue
        if run.conclusion != "success":
            continue
        if now - run.created_at > lookback:
            continue
        recent_successful_deploy = True
        break
    if not recent_successful_deploy:
        return []
    skipped: list[GhRun] = []
    for run in runs:
        name_lower = run.name.lower()
        if not any(token.lower() in name_lower for token in POST_DEPLOY_VERIFY_WORKFLOWS):
            continue
        if run.conclusion != "skipped":
            continue
        if now - run.created_at > lookback:
            continue
        skipped.append(run)
    return skipped


def find_pr_conflict_storm(prs: list[GhPr], runs: list[GhRun], now: datetime) -> list[GhPr]:
    """Return open PR conflict list if ≥2 PRs are conflicting within a deploy window (RC5 shape).

    Wave 45 RC5 incident shape: 17+ subagents land branches in
    parallel; several touch the same shared file (boot manifest /
    deploy.yml / version files). PRs flip to ``mergeable=CONFLICTING``
    in a cluster, and the Strategy F retry pipeline stalls until
    ``main`` is linear.

    Heuristic:
    - ``deploy_window_open`` ⇔ deploy.yml has any run with status
      in_progress, OR a successful run within ``PR_CONFLICT_DEPLOY_WINDOW_SEC``
    - if deploy window open AND ≥ ``PR_CONFLICT_MIN_COUNT`` open
      PRs are CONFLICTING → RC5 suspect
    """
    window = timedelta(seconds=PR_CONFLICT_DEPLOY_WINDOW_SEC)
    deploy_window_open = False
    for run in runs:
        if "deploy" not in run.name.lower():
            continue
        if run.status == "in_progress":
            deploy_window_open = True
            break
        if run.conclusion == "success" and now - run.created_at < window:
            deploy_window_open = True
            break
    if not deploy_window_open:
        return []
    if len(prs) < PR_CONFLICT_MIN_COUNT:
        return []
    return prs


def send_telegram(text: str) -> bool:
    """Send a Telegram message via the bot API; return True on success."""
    token = os.environ.get("TG_BOT_TOKEN")
    chat_id = os.environ.get("TG_CHAT_ID")
    if not token or not chat_id:
        print(
            "[db_boot_hang_alert] TG_BOT_TOKEN / TG_CHAT_ID missing — telegram skipped",
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


def send_slack(text: str) -> bool:
    """Send a Slack message via the incoming webhook; return True on success.

    Wave 45 added Slack as a second alert channel so the operator does
    not depend on Telegram alone for SEV1 paging. Both channels fire on
    every alert; either one delivering is acceptable.
    """
    webhook = os.environ.get("SLACK_WEBHOOK_URL")
    if not webhook:
        print(
            "[db_boot_hang_alert] SLACK_WEBHOOK_URL missing — slack skipped",
            file=sys.stderr,
        )
        return False
    # Slack does not parse HTML; strip <b>/<code> for plaintext path.
    plain = re.sub(r"</?[^>]+>", "", text)
    payload = json.dumps({"text": plain}).encode("utf-8")
    req = urllib.request.Request(  # noqa: S310 — slack webhook host is fixed
        webhook, data=payload, method="POST", headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310
            return 200 <= resp.status < 300
    except (urllib.error.URLError, TimeoutError) as exc:
        print(f"[db_boot_hang_alert] slack send failed: {exc}", file=sys.stderr)
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true", help="Print result, do not send Telegram/Slack."
    )
    parser.add_argument(
        "--skip-gh",
        action="store_true",
        help="Skip gh-based checks (RC2/RC4/RC5). Useful if gh is unavailable.",
    )
    args = parser.parse_args()
    now = datetime.now(timezone.utc)
    lines = fetch_recent_lines()
    runs: list[GhRun] = []
    prs: list[GhPr] = []
    if not args.skip_gh:
        runs = fetch_recent_gh_runs()
        prs = fetch_conflicting_prs()
    if not lines and not runs and not prs:
        # Both fly and gh failed; do not page (avoid false positives on
        # transient outage of either CLI).
        print(json.dumps({"status": "noop", "reason": "no_signals", "ts": now.isoformat()}))
        return 0

    # RC1 — integrity_check hang shape (Wave 25 signature)
    rc1_suspect = find_hung_full_scan(lines, now) if lines else None
    # RC2 — deploy.yml in_progress stall (Wave 45 signature for depot stall)
    rc2_suspect = find_deploy_stall(runs, now) if runs else None
    # RC3 — schema_guard FAIL shape (Wave 40 signature; v2 keyed this as RC4)
    rc3_suspect = find_schema_guard_fail(lines) if lines else None
    # RC4 — GHA workflow_run skipped post-deploy verify (Wave 45 signature)
    rc4_skipped = find_skipped_post_deploy_verify(runs, now) if runs else []
    # RC5 — open PR conflict during deploy window (Wave 45 signature)
    rc5_conflicts = find_pr_conflict_storm(prs, runs, now) if (prs and runs) else []

    if (
        rc1_suspect is None
        and rc2_suspect is None
        and rc3_suspect is None
        and not rc4_skipped
        and not rc5_conflicts
    ):
        print(
            json.dumps(
                {
                    "status": "ok",
                    "scanned_lines": len(lines),
                    "scanned_runs": len(runs),
                    "scanned_prs": len(prs),
                    "ts": now.isoformat(),
                }
            )
        )
        return 0

    # Build alert text(s) — multiple RCs can fire in the same cron tick
    # if a cascade is in flight (Wave 22-44 was exactly this shape). We
    # page once with all signals so the operator sees the full chain.
    pieces: list[str] = []
    payload: dict[str, object] = {
        "status": "alert",
        "scanned_lines": len(lines),
        "scanned_runs": len(runs),
        "scanned_prs": len(prs),
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

    if rc2_suspect is not None:
        age_sec = int((now - rc2_suspect.created_at).total_seconds())
        pieces.append(
            f"<b>[jpcite SEV1] RC2 deploy stall suspected</b>\n"
            f"Workflow: <code>{rc2_suspect.name}</code> (run_id={rc2_suspect.db_id})\n"
            f"status=in_progress for {age_sec}s "
            f"(threshold {DEPLOY_INPROGRESS_THRESHOLD_SEC}s)"
        )
        payload["rc2"] = {
            "age_sec": age_sec,
            "run_id": rc2_suspect.db_id,
            "name": rc2_suspect.name,
        }

    if rc3_suspect is not None:
        rc3_age_sec = int((now - rc3_suspect.ts).total_seconds())
        pieces.append(
            f"<b>[jpcite SEV1] RC3 schema_guard FAIL detected</b>\n"
            f"App: <code>{FLY_APP}</code>\n"
            f"Log line ({rc3_age_sec}s old):\n<code>{rc3_suspect.message[:240]}</code>"
        )
        # v2-key alias retained for back-compat with downstream tooling
        # that parses payload["rc4"] from the Wave 41 detector.
        payload["rc3"] = {"age_sec": rc3_age_sec, "line": rc3_suspect.message}
        payload["rc4"] = payload["rc3"]  # noqa: B026 — intentional alias

    if rc4_skipped:
        skipped_names = ", ".join(sorted({r.name for r in rc4_skipped}))
        pieces.append(
            f"<b>[jpcite SEV1] RC4 CI chain skip detected</b>\n"
            f"deploy.yml ran green but post-deploy verify workflows show "
            f"<code>conclusion=skipped</code>:\n"
            f"<code>{skipped_names}</code>\n"
            "Likely workflow_run guard mis-skip under workflow_dispatch parent."
        )
        payload["rc4_skipped"] = [
            {"run_id": r.db_id, "name": r.name, "created_at": r.created_at.isoformat()}
            for r in rc4_skipped
        ]

    if rc5_conflicts:
        conflict_list = ", ".join(f"#{p.number}" for p in rc5_conflicts)
        pieces.append(
            f"<b>[jpcite SEV1] RC5 PR conflict storm detected</b>\n"
            f"{len(rc5_conflicts)} open PR(s) marked CONFLICTING during deploy window:\n"
            f"<code>{conflict_list}</code>\n"
            "Strategy W (worktree-isolate) required before Strategy F retry."
        )
        payload["rc5_conflicts"] = [
            {"number": p.number, "title": p.title} for p in rc5_conflicts
        ]

    text = "\n\n".join(pieces) + (
        "\n\nRunbook v3: docs/runbook/incident_response_v3_multi_root_cause.md\n"
        "Post-mortem v3: docs/postmortem/2026-05-11_18h_outage_v3.md\n"
        "Wave 18 §4 fix: 81922433f (RC1)\n"
        "Wave 40 PR #75 fix: 82df31bd8 (RC3)\n"
        "Wave 41 direct-dispatch pattern (RC4); Wave 44 worktree-isolation (RC5)."
    )
    print(json.dumps(payload))
    if args.dry_run:
        return 1
    tg_sent = send_telegram(text)
    slack_sent = send_slack(text)
    # Treat as success if EITHER channel delivered (no single point of failure).
    return 0 if (tg_sent or slack_sent) else 2


if __name__ == "__main__":
    sys.exit(main())
