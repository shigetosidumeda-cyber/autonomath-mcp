#!/usr/bin/env python3
"""Self-improve daily runner v2 (Wave 19 §H8, continuous learning loop).

Extension of ``scripts/ops/self_improve_runner.py`` (Wave 16 H6) to run
all 9 audit_runner_* surfaces daily (previously 5 axes weekly) and
post a Slack digest summary. Adds an "auto-patch generation" stage
that drafts a candidate diff for any axis that regressed > 0.5 vs
baseline, then opens a draft PR via ``gh pr create --draft`` (when
``--auto-pr`` is passed).

Why v2 (vs touching v1)
-----------------------
Wave 16 H6 cron landed as a weekly job. Wave 19 needs daily cadence
+ 4 new audit axes (a11y / ax_4pillars / ax_anti_patterns /
agent_journey) on top of the 5 original (seo / geo / html /
per_record / ai_bot). Doubling cadence + axis count would risk
regression on the existing v1 runner contract (workflow inputs,
sidecar shape, auto-merge gate). Keep v1 stable; v2 is the daily
runner with the wider axis set.

9-axis matrix
-------------
  1. seo          — Google / Bing crawl signal
  2. geo          — Generative-engine / answer-engine optimization
  3. per_record   — Schema / citation completeness per program row
  4. html         — HTML semantic / structured data
  5. a11y         — WCAG 2.2 AA compliance (NEW v2)
  6. ax_4pillars  — Agent eXperience 4 柱 (Access / Context / Tools / Orchestration) (NEW v2)
  7. ax_anti_patterns — 9 anti-pattern detector (NEW v2)
  8. agent_journey — 6-step journey audit (NEW v2)
  9. ai_bot_log   — robots.txt + AI bot acceptance log

Daily cadence runs them all; if regression is detected on any axis
the runner produces a draft PR with the rule-based patch suggestions
returned by the matching ``self_improve.loops`` module. The operator
reviews and merges. **NO LLM API call** — patch generation is
deterministic rule application from corpus state + audit deltas.

Slack digest
------------
If ``SLACK_WEBHOOK_URL`` is set in the env, posts a compact summary
to the configured channel. Format: 9 row table with axis / score /
delta / verdict, followed by the auto-PR URL (if opened).

Usage
-----
    python scripts/cron/self_improve_runner_v2.py \\
        --out-dir analytics/self_improve_runs_v2 \\
        --baseline tests/regression/audit_baseline.json \\
        --slack  # opt into Slack digest
        --auto-pr  # opt into draft PR creation on regression
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import pathlib
import subprocess
import sys
from datetime import UTC, datetime
from typing import Any
from urllib import error as urllib_error
from urllib import request as urllib_request

logger = logging.getLogger("jpintel.cron.self_improve_v2")

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
AXES_V2: tuple[str, ...] = (
    "seo",
    "geo",
    "per_record",
    "html",
    "a11y",
    "ax_4pillars",
    "ax_anti_patterns",
    "agent_journey",
    "ai_bot",
)
REGRESSION_THRESHOLD = 0.5
RUN_TIMEOUT_SEC = 900  # 15 min cap per axis runner


def _run(cmd: list[str], *, timeout: int = RUN_TIMEOUT_SEC) -> tuple[int, str, str]:
    """Run a subprocess; return (rc, stdout, stderr)."""
    proc = subprocess.run(  # noqa: S603
        cmd,
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        timeout=timeout,
        check=False,
    )
    return proc.returncode, proc.stdout, proc.stderr


def run_axis(axis: str, out_dir: pathlib.Path) -> dict[str, Any]:
    """Run a single audit_runner_<axis>.py and return parsed JSON."""
    out_json = out_dir / f"audit_{axis}.json"
    out_md = out_dir / f"audit_{axis}.md"
    runner = REPO_ROOT / "scripts" / "ops" / f"audit_runner_{axis}.py"
    if not runner.exists():
        return {
            "axis": axis,
            "score": 0.0,
            "error": f"runner not found at {runner}",
        }
    cmd = [
        sys.executable,
        str(runner),
        "--out-md",
        str(out_md),
        "--out-json",
        str(out_json),
    ]
    rc, _stdout, stderr = _run(cmd)
    if rc != 0 or not out_json.exists():
        return {
            "axis": axis,
            "score": 0.0,
            "error": f"axis {axis} rc={rc} stderr={stderr[-500:]}",
        }
    try:
        return json.loads(out_json.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return {"axis": axis, "score": 0.0, "error": f"json decode: {exc}"}


def compute_deltas(
    audits: list[dict[str, Any]], baseline_path: pathlib.Path
) -> tuple[list[dict[str, Any]], list[str]]:
    """Return (delta list, list of regressed axis ids)."""
    if not baseline_path.exists():
        return ([], [])
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    deltas: list[dict[str, Any]] = []
    regressed: list[str] = []
    for audit in audits:
        axis = audit.get("axis", "")
        cur = float(audit.get("score") or 0.0)
        base = float(baseline.get("axes", {}).get(axis, {}).get("score") or 0.0)
        delta = round(cur - base, 3)
        if delta < -REGRESSION_THRESHOLD:
            regressed.append(axis)
        deltas.append({"axis": axis, "baseline": base, "current": cur, "delta": delta})
    return (deltas, regressed)


def emit_patch_suggestions(
    regressed: list[str], audits: list[dict[str, Any]], out_dir: pathlib.Path
) -> pathlib.Path | None:
    """Write a markdown body of patch suggestions for each regressed axis.

    Rule-based — pulls per-axis recommendations from the audit JSON's
    ``recommendations`` key. Returns the path to the suggestions file
    (or None if no regressions).
    """
    if not regressed:
        return None
    by_axis = {a.get("axis", ""): a for a in audits}
    lines: list[str] = [
        "# Auto-patch suggestions (Wave 19 §H8)",
        "",
        f"Generated: {datetime.now(UTC).isoformat()}",
        f"Regressed axes: {', '.join(regressed)}",
        "",
    ]
    for axis in regressed:
        a = by_axis.get(axis, {})
        recs = a.get("recommendations") or []
        lines.append(f"## {axis} — score {a.get('score', 0.0):.2f}")
        lines.append("")
        if not recs:
            lines.append("(No rule-based recommendations available.)")
            lines.append("")
            continue
        for r in recs[:10]:
            if isinstance(r, dict):
                lines.append(
                    f"- **{r.get('id', '?')}** — {r.get('description', '?')} "
                    f"(severity: {r.get('severity', 'n/a')})"
                )
            else:
                lines.append(f"- {r}")
        lines.append("")
    path = out_dir / "auto_patch_suggestions.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def post_slack_digest(payload: dict[str, Any]) -> bool:
    """POST a compact summary to SLACK_WEBHOOK_URL. Return True on success."""
    webhook = os.environ.get("SLACK_WEBHOOK_URL")
    if not webhook:
        logger.info("slack_digest_skip: SLACK_WEBHOOK_URL unset")
        return False
    lines = [
        ":memo: *jpcite self-improve daily run v2*",
        f"Date: {payload.get('date')}",
        f"Regressed axes: {', '.join(payload.get('regressed_axes', [])) or 'none'}",
        "",
        "```",
        f"{'axis':<22} {'baseline':>8} {'current':>8} {'delta':>8}",
    ]
    for d in payload.get("deltas", []):
        lines.append(
            f"{d['axis']:<22} {d['baseline']:>8.2f} {d['current']:>8.2f} {d['delta']:>+8.2f}"
        )
    lines.append("```")
    if payload.get("auto_pr_url"):
        lines.append(f"Auto-PR: {payload['auto_pr_url']}")
    body = {"text": "\n".join(lines)}
    req = urllib_request.Request(  # noqa: S310
        webhook,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib_request.urlopen(req, timeout=15) as resp:  # noqa: S310
            return 200 <= resp.status < 300
    except (urllib_error.URLError, urllib_error.HTTPError) as exc:
        logger.warning("slack_digest_post_failed: %s", exc)
        return False


def open_draft_pr(suggestions_path: pathlib.Path, regressed: list[str]) -> str | None:
    """Open a draft PR via `gh pr create --draft` with the suggestions body.

    Returns the PR URL on success, None otherwise.
    """
    if not regressed:
        return None
    branch = f"bot/self-improve-v2-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}"
    rc, _stdout, _stderr = _run(["git", "checkout", "-b", branch], timeout=30)
    if rc != 0:
        logger.warning("draft_pr_checkout_failed")
        return None
    title = f"bot: self-improve v2 — {len(regressed)} axis regression(s)"
    body = suggestions_path.read_text(encoding="utf-8")
    rc, stdout, stderr = _run(
        ["gh", "pr", "create", "--draft", "--title", title, "--body", body],
        timeout=60,
    )
    if rc != 0:
        logger.warning("draft_pr_create_failed: %s", stderr[-500:])
        return None
    # gh pr create prints URL on stdout
    for line in stdout.splitlines():
        if line.startswith("https://"):
            return line.strip()
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out-dir",
        type=pathlib.Path,
        default=REPO_ROOT / "analytics" / "self_improve_runs_v2",
    )
    parser.add_argument(
        "--baseline",
        type=pathlib.Path,
        default=REPO_ROOT / "tests" / "regression" / "audit_baseline.json",
    )
    parser.add_argument(
        "--slack",
        action="store_true",
        help="Post Slack digest if SLACK_WEBHOOK_URL is set",
    )
    parser.add_argument(
        "--auto-pr",
        action="store_true",
        help="Open a draft PR on regression",
    )
    args = parser.parse_args(argv)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    date_part = datetime.now(UTC).strftime("%Y-%m-%d")

    # 1. Run all 9 axes
    audits: list[dict[str, Any]] = []
    for axis in AXES_V2:
        logger.info("axis_start: %s", axis)
        audits.append(run_axis(axis, args.out_dir))

    # 2. Compute deltas vs baseline
    deltas, regressed = compute_deltas(audits, args.baseline)

    # 3. Generate patch suggestions for any regression
    suggestions_path = emit_patch_suggestions(regressed, audits, args.out_dir)

    # 4. Optionally open a draft PR
    auto_pr_url: str | None = None
    if args.auto_pr and suggestions_path:
        auto_pr_url = open_draft_pr(suggestions_path, regressed)

    # 5. Emit combined sidecar
    combined = {
        "ts": datetime.now(UTC).isoformat(),
        "date": date_part,
        "audits": audits,
        "deltas": deltas,
        "regressed_axes": regressed,
        "auto_pr_url": auto_pr_url,
        "suggestions_path": str(suggestions_path) if suggestions_path else None,
    }
    sidecar_path = args.out_dir / f"self_improve_v2_{date_part}.json"
    sidecar_path.write_text(json.dumps(combined, ensure_ascii=False, indent=2), encoding="utf-8")

    # 6. Slack digest
    if args.slack:
        post_slack_digest(combined)

    print(f"[self_improve_v2] sidecar → {sidecar_path}")
    print(f"[self_improve_v2] regressed_axes={regressed}")
    if auto_pr_url:
        print(f"[self_improve_v2] auto_pr → {auto_pr_url}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
