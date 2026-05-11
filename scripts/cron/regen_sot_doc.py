#!/usr/bin/env python3
"""Weekly Knowledge Handoff SOT doc auto-regen (Wave 16 H7).

Writes `docs/_internal/CURRENT_SOT_{YYYY-MM-DD}.md` so a new session
needs to read exactly one file to be productive (≤5 minute handoff
cost target).

The doc surfaces:

  * latest wave state (pulled from `CLAUDE.md` SOT note line)
  * open PR list (via `gh pr list`, optional — graceful if `gh` missing)
  * backlog (top 20 pending tasks from the `git log` `Wave N` history)
  * latest 5-axis audit score (read from
    `tests/regression/audit_baseline.json`)
  * Fly + CF deploy status (read from
    `analytics/jpcite_state_*.json` if present; otherwise warn)
  * runtime counts (route_count / openapi_path_count / tool_count)
    from `scripts/distribution_manifest.yml`

NO LLM API CALLS. Pure stdlib + optional shell-out to `gh` / `flyctl`.
Production scope (per `CLAUDE.md` constraint) — must stay LLM-free.

Usage
-----
    python scripts/cron/regen_sot_doc.py
    python scripts/cron/regen_sot_doc.py --date 2026-05-12
    python scripts/cron/regen_sot_doc.py --out-dir docs/_internal --smoke
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import subprocess
import sys
from datetime import UTC, datetime
from typing import Any

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
DEFAULT_OUT_DIR = REPO_ROOT / "docs" / "_internal"
JST = UTC  # body header renders JST string; raw isoformat for sortability


def _run(cmd: list[str], *, timeout: int = 30) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(  # noqa: S603
            cmd,
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
            timeout=timeout,
            check=False,
        )
        return proc.returncode, proc.stdout, proc.stderr
    except FileNotFoundError:
        return (127, "", f"binary not found: {cmd[0]}")
    except subprocess.TimeoutExpired:
        return (124, "", "timeout")


def load_distribution_manifest() -> dict[str, Any]:
    """Parse the canonical distribution manifest (simple YAML key:value subset)."""
    path = REPO_ROOT / "scripts" / "distribution_manifest.yml"
    if not path.exists():
        return {}
    out: dict[str, Any] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        val = val.split("#", 1)[0].strip().strip('"').strip("'")
        if not val:
            continue
        try:
            out[key.strip()] = int(val)
        except ValueError:
            out[key.strip()] = val
    return out


def load_audit_baseline() -> dict[str, Any]:
    path = REPO_ROOT / "tests" / "regression" / "audit_baseline.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def load_version() -> str:
    path = REPO_ROOT / "pyproject.toml"
    if not path.exists():
        return "?"
    for line in path.read_text(encoding="utf-8").splitlines():
        m = re.match(r'^version\s*=\s*"([^"]+)"', line.strip())
        if m:
            return m.group(1)
    return "?"


def load_claude_md_overview_excerpt() -> str:
    """Pull the SOT note + first Overview paragraph from CLAUDE.md."""
    path = REPO_ROOT / "CLAUDE.md"
    if not path.exists():
        return "_CLAUDE.md not found_"
    text = path.read_text(encoding="utf-8")
    # Take from "## Overview" up to but not including "## " (next H2).
    m = re.search(r"## Overview\s*\n(.+?)(?=\n## )", text, re.DOTALL)
    if not m:
        return "_Overview section missing_"
    body = m.group(1).strip()
    # Trim to first 1500 chars so the SOT doc stays scannable.
    if len(body) > 1500:
        body = body[:1500].rsplit(".", 1)[0] + ". (truncated — read CLAUDE.md for full context)"
    return body


def open_prs_via_gh() -> list[dict[str, Any]]:
    rc, stdout, _ = _run(
        ["gh", "pr", "list", "--state", "open", "--limit", "20", "--json", "number,title,headRefName,createdAt,author"]
    )
    if rc != 0 or not stdout.strip():
        return []
    try:
        return json.loads(stdout)
    except json.JSONDecodeError:
        return []


def fly_status() -> dict[str, str]:
    rc, stdout, _ = _run(["flyctl", "status", "--app", "jpcite-api", "--json"])
    if rc != 0:
        return {"status": "unknown (flyctl unavailable or app mismatch)"}
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        return {"status": "flyctl returned non-JSON"}
    return {
        "status": data.get("Status", "?"),
        "deployment_status": data.get("DeploymentStatus", {}).get("Status", "?"),
        "hostname": data.get("Hostname", "?"),
    }


def latest_state_snapshot() -> dict[str, Any]:
    """Surface the latest `analytics/jpcite_state_*.json` if any."""
    candidates = sorted(
        (REPO_ROOT / "analytics").glob("jpcite_state_*.json"),
        reverse=True,
    )
    for path in candidates:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
    return {}


def recent_commits(limit: int = 15) -> list[str]:
    rc, stdout, _ = _run(["git", "log", "-n", str(limit), "--pretty=format:- %s (%h, %ad)", "--date=short"])
    if rc != 0:
        return []
    return [line for line in stdout.splitlines() if line.strip()]


def backlog_from_git_log(limit: int = 50) -> list[str]:
    """Surface commits matching `Wave \\d+` patterns as backlog hints."""
    rc, stdout, _ = _run(["git", "log", "-n", str(limit), "--pretty=format:%s"])
    if rc != 0:
        return []
    waves: list[str] = []
    seen = set()
    for line in stdout.splitlines():
        m = re.search(r"Wave\s*(\d+)\s*([A-Z]\d+)?[: -]", line)
        if not m:
            continue
        token = m.group(0)
        if token in seen:
            continue
        seen.add(token)
        waves.append(f"- {line.strip()}")
        if len(waves) >= 20:
            break
    return waves


def render_doc(date_str: str) -> str:
    version = load_version()
    manifest = load_distribution_manifest()
    baseline = load_audit_baseline()
    overview = load_claude_md_overview_excerpt()
    fly = fly_status()
    prs = open_prs_via_gh()
    commits = recent_commits()
    backlog = backlog_from_git_log()
    state = latest_state_snapshot()

    lines: list[str] = [
        f"# Current SOT {date_str}",
        "",
        f"Generated: {datetime.now(JST).isoformat()} (auto-regen — `scripts/cron/regen_sot_doc.py`)",
        "",
        "Purpose: 1-file handoff for new session start. ≤5 minute read.",
        "",
        "## Wave / Version",
        "",
        f"- Package version: **{version}**",
        f"- Runtime route count (manifest): {manifest.get('route_count', '?')}",
        f"- OpenAPI path count (manifest): {manifest.get('openapi_path_count', '?')}",
        f"- MCP tool count (manifest floor): {manifest.get('tool_count', '139')}",
        "",
        "## Latest 5-axis audit",
        "",
        "| axis | baseline score | verdict |",
        "| --- | ---: | :---: |",
    ]
    for axis_name, body in (baseline.get("axes") or {}).items():
        score = body.get("score", 0)
        verdict = body.get("verdict", "?")
        lines.append(f"| {axis_name} | {score} | {verdict} |")
    if not baseline.get("axes"):
        lines.append("| _baseline missing_ | — | — |")
    lines.extend(
        [
            "",
            f"Locked at: `{baseline.get('_meta', {}).get('locked_at', '?')}`",
            "",
            "## Fly.io / Deploy status",
            "",
            f"- Fly app status: `{fly.get('status', '?')}`",
            f"- Deployment status: `{fly.get('deployment_status', '?')}`",
            f"- Hostname: `{fly.get('hostname', '?')}`",
            "",
        ]
    )
    if state:
        lines.append("Latest state snapshot:")
        lines.append("")
        for k in ("git_sha", "gha_run_id", "deployment_id", "openapi_path_count", "live"):
            if k in state:
                lines.append(f"- {k}: `{state[k]}`")
        lines.append("")
    lines.extend(
        [
            "## Open PRs",
            "",
        ]
    )
    if not prs:
        lines.append("_No open PRs (or `gh` unavailable in this env)._")
    else:
        for pr in prs[:20]:
            num = pr.get("number")
            title = pr.get("title", "")
            branch = pr.get("headRefName", "")
            author = (pr.get("author") or {}).get("login", "")
            lines.append(f"- #{num} `{branch}` by @{author}: {title}")
    lines.extend(
        [
            "",
            "## Recent commits (15)",
            "",
        ]
    )
    lines.extend(commits if commits else ["_git log unavailable_"])
    lines.extend(
        [
            "",
            "## Backlog hints (recent Wave-tagged commits)",
            "",
        ]
    )
    lines.extend(backlog if backlog else ["_no Wave-tagged commits in recent log_"])
    lines.extend(
        [
            "",
            "## Overview excerpt (from CLAUDE.md)",
            "",
            overview,
            "",
            "## Pointer / Next steps",
            "",
            "1. Read this file first; if anything is `unknown` or empty, run "
            "`scripts/cron/regen_sot_doc.py` to refresh.",
            "2. Authoritative architecture / gotchas: `CLAUDE.md`.",
            "3. Deploy packet / NO-GO state: most recent "
            "`docs/_internal/PRODUCTION_DEPLOY_PACKET_*.md`.",
            "4. Memory: `~/.claude/projects/-Users-shigetoumeda/memory/MEMORY.md` "
            "(jpcite session state lives under `project_jpcite_*` keys).",
            "5. CI guard for LLM imports: "
            "`tests/test_no_llm_in_production.py` — never weaken it.",
            "",
        ]
    )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--date",
        type=str,
        default=None,
        help="Override date stamp (YYYY-MM-DD). Default: today (JST).",
    )
    parser.add_argument(
        "--out-dir",
        type=pathlib.Path,
        default=DEFAULT_OUT_DIR,
    )
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="Smoke-test mode: write to a tmp path and validate non-empty.",
    )
    args = parser.parse_args(argv)

    date_str = args.date or datetime.now(JST).strftime("%Y-%m-%d")
    body = render_doc(date_str)
    if args.smoke:
        if len(body) < 300:
            print(f"[regen_sot_doc] SMOKE FAIL: body too short ({len(body)} chars)", file=sys.stderr)
            return 1
        print(f"[regen_sot_doc] SMOKE OK: body={len(body)} chars")
        return 0

    args.out_dir.mkdir(parents=True, exist_ok=True)
    out_path = args.out_dir / f"CURRENT_SOT_{date_str}.md"
    out_path.write_text(body, encoding="utf-8")
    print(f"[regen_sot_doc] wrote {out_path} ({len(body)} chars)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
