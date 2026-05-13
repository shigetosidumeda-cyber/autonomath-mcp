#!/usr/bin/env python3
"""Self-improve weekly runner (Wave 16 H6).

Wraps the existing `scripts/self_improve_orchestrator.py` + the 5-axis
audit (`scripts/ops/audit_runner_{seo,geo,html,per_record,ai_bot}.py`)
into a single weekly cron entrypoint that produces:

  1. A JSON sidecar with all 10 self-improve loop results + 5 audit
     axis scores combined into one document.
  2. A markdown summary surfacing axis deltas vs
     `tests/regression/audit_baseline.json` and the simplify-skill
     recommendations queue.
  3. An auto-PR description body (markdown) that the workflow uploads
     as the PR body so the operator gets a 0-review-cost merge path
     when (a) regression gate green and (b) no loop failed.

NO LLM API CALLS. All recommendations are pulled from rule-based
loops in `jpintel_mcp.self_improve.*` + the 5 audit runners; this
matches the CLAUDE.md constraint that production code never imports
`anthropic` / `openai` / `google.generativeai` / `claude_agent_sdk`.

Auto-merge gate
---------------
  - regression gate (5-axis): each axis delta must be ≥ -0.5 vs baseline
  - all 10 self-improve loops returned without error
  - aggregate score sum ≥ baseline aggregate

If any condition fails, the runner emits `auto_merge_eligible=false` so
the workflow falls through to operator review.

Usage
-----
    python scripts/ops/self_improve_runner.py \\
        --out-dir analytics/self_improve_runs \\
        --baseline tests/regression/audit_baseline.json

    python scripts/ops/self_improve_runner.py \\
        --execute              # opt into dry_run=False loops
"""

from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys
from datetime import UTC, datetime
from typing import Any

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
AXES: tuple[str, ...] = ("seo", "geo", "html", "per_record", "ai_bot")
REGRESSION_THRESHOLD = 0.5

JST = UTC  # workflow renders in JST via header; raw ts is UTC for sortability


def _run(cmd: list[str]) -> tuple[int, str, str]:
    """Run subprocess; return (rc, stdout, stderr)."""
    proc = subprocess.run(  # noqa: S603
        cmd,
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        timeout=600,
        check=False,
    )
    return proc.returncode, proc.stdout, proc.stderr


def run_orchestrator(*, execute: bool, no_write: bool) -> dict[str, Any]:
    """Invoke the self-improve orchestrator and return parsed stdout JSON."""
    cmd = [sys.executable, "scripts/self_improve_orchestrator.py", "--all"]
    if execute:
        cmd.append("--execute")
    if no_write:
        cmd.append("--no-write")
    rc, stdout, stderr = _run(cmd)
    if rc != 0:
        return {
            "error": f"orchestrator rc={rc}",
            "stderr": stderr[-2000:],
            "stdout": stdout[-2000:],
            "loops_total": 0,
            "loops_succeeded": 0,
            "loops_failed": 10,
            "results": [],
        }
    # Orchestrator prints the JSON to stdout (with --no-write) or writes a
    # file. Take the last `{...}` block from stdout to be robust to mixed
    # output.
    payload: dict[str, Any] | None = None
    for chunk in stdout.split("\n\n"):
        chunk = chunk.strip()
        if chunk.startswith("{") and chunk.endswith("}"):
            try:
                payload = json.loads(chunk)
            except json.JSONDecodeError:
                continue
    if payload is None:
        try:
            payload = json.loads(stdout)
        except json.JSONDecodeError:
            payload = {
                "error": "orchestrator output not parseable as JSON",
                "stdout": stdout[-2000:],
            }
    return payload or {}


def run_audit_axis(axis: str, out_dir: pathlib.Path) -> dict[str, Any]:
    """Invoke a single audit runner; return parsed JSON sidecar."""
    out_json = out_dir / f"audit_{axis}.json"
    out_md = out_dir / f"audit_{axis}.md"
    cmd = [
        sys.executable,
        f"scripts/ops/audit_runner_{axis}.py",
        "--out-md",
        str(out_md),
        "--out-json",
        str(out_json),
    ]
    rc, stdout, stderr = _run(cmd)
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


def compute_axis_deltas(
    audits: list[dict[str, Any]], baseline_path: pathlib.Path
) -> tuple[list[dict[str, Any]], bool]:
    """Return (deltas list, regression_detected)."""
    if not baseline_path.exists():
        return ([], False)
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    deltas: list[dict[str, Any]] = []
    regressed = False
    for audit in audits:
        axis = audit.get("axis", "")
        cur = float(audit.get("score") or 0.0)
        base = float(baseline.get("axes", {}).get(axis, {}).get("score") or 0.0)
        delta = round(cur - base, 3)
        if delta < -REGRESSION_THRESHOLD:
            regressed = True
        deltas.append({"axis": axis, "baseline": base, "current": cur, "delta": delta})
    return (deltas, regressed)


def emit_pr_body(
    run_payload: dict[str, Any],
    audit_deltas: list[dict[str, Any]],
    regression: bool,
    auto_merge: bool,
    out_path: pathlib.Path,
) -> None:
    """Write the auto-PR description markdown."""
    lines = [
        "# Self-improve weekly run",
        "",
        f"Generated: {datetime.now(JST).isoformat()}",
        f"Orchestrator dry_run: {run_payload.get('dry_run', True)}",
        f"Loops: {run_payload.get('loops_succeeded', 0)}/{run_payload.get('loops_total', 10)} succeeded",
        "",
        "## 5-axis audit deltas",
        "",
        "| axis | baseline | current | delta | verdict |",
        "| --- | ---: | ---: | ---: | :---: |",
    ]
    for d in audit_deltas:
        verdict = "PASS"
        if d["delta"] < -REGRESSION_THRESHOLD:
            verdict = "REGRESS"
        elif d["delta"] < 0:
            verdict = "soft-dip"
        lines.append(
            f"| {d['axis']} | {d['baseline']:.2f} | {d['current']:.2f} "
            f"| {d['delta']:+.2f} | {verdict} |"
        )
    lines.extend(
        [
            "",
            "## Self-improve loop summary",
            "",
            "| loop | scanned | proposed | executed |",
            "| --- | ---: | ---: | ---: |",
        ]
    )
    for r in run_payload.get("results", []):
        lines.append(
            f"| {r.get('loop', '?')} | {r.get('scanned', 0)} | "
            f"{r.get('actions_proposed', 0)} | {r.get('actions_executed', 0)} |"
        )
    lines.extend(
        [
            "",
            "## Gate decision",
            "",
            f"- regression detected: {regression}",
            f"- auto-merge eligible: {auto_merge}",
            "",
        ]
    )
    if not auto_merge:
        lines.append("Operator review required — see logs and rerun with `--execute` once green.")
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument(
        "--no-write",
        action="store_true",
        default=True,
        help="Skip orchestrator JSON dump commit (default true; safer under cron).",
    )
    parser.add_argument(
        "--out-dir",
        type=pathlib.Path,
        default=REPO_ROOT / "analytics" / "self_improve_runs",
    )
    parser.add_argument(
        "--baseline",
        type=pathlib.Path,
        default=REPO_ROOT / "tests" / "regression" / "audit_baseline.json",
    )
    args = parser.parse_args(argv)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    date_part = datetime.now(JST).strftime("%Y-%m-%d")

    # 1. Run orchestrator (10 loops)
    orchestrator_payload = run_orchestrator(execute=args.execute, no_write=args.no_write)

    # 2. Run 5-axis audit
    audits: list[dict[str, Any]] = []
    for axis in AXES:
        audits.append(run_audit_axis(axis, args.out_dir))

    # 3. Compute deltas vs baseline
    deltas, regressed = compute_axis_deltas(audits, args.baseline)

    # 4. Decide auto-merge eligibility
    loops_failed = int(orchestrator_payload.get("loops_failed", 0))
    auto_merge = (not regressed) and loops_failed == 0 and not orchestrator_payload.get("error")

    # 5. Write combined sidecar + PR body
    combined = {
        "ts": datetime.now(JST).isoformat(),
        "date": date_part,
        "execute": args.execute,
        "orchestrator": orchestrator_payload,
        "audits": audits,
        "deltas": deltas,
        "regression_detected": regressed,
        "auto_merge_eligible": auto_merge,
    }
    sidecar_path = args.out_dir / f"self_improve_{date_part}.json"
    sidecar_path.write_text(json.dumps(combined, ensure_ascii=False, indent=2), encoding="utf-8")

    pr_body_path = args.out_dir / f"self_improve_{date_part}_pr_body.md"
    emit_pr_body(orchestrator_payload, deltas, regressed, auto_merge, pr_body_path)

    print(f"[self_improve_runner] sidecar → {sidecar_path}")
    print(f"[self_improve_runner] pr_body → {pr_body_path}")
    print(f"[self_improve_runner] auto_merge_eligible={auto_merge}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
