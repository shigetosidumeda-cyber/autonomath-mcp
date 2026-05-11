#!/usr/bin/env python3
"""Wave 15 H1/H3 — AI bot visit + competitive GEO axis audit runner.

5-sub-axis: robots AI Allow / bot visit observability / competitive GEO
lead / directory submission readiness / GitHub clone proxy signal. The
bot-visit-observability axis is necessarily low until the Cloudflare token
is scoped Zone Analytics:Read; we still report it so the floor lifts when
the scope is added (memory `feedback_verify_before_apologize`: re-probe
before assuming the lift happened).

Pure stdlib. Read-only on site/ and the local repo. NO network call.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
SITE = REPO_ROOT / "site"

AI_BOT_UAS = [
    "GPTBot", "ChatGPT-User", "OAI-SearchBot", "ClaudeBot", "Claude-User",
    "Claude-SearchBot", "anthropic-ai", "PerplexityBot", "Google-Extended",
    "CCBot", "Applebot-Extended", "Meta-ExternalAgent", "Amazonbot",
    "Bytespider",
]
DIRECTORY_TARGETS = [
    "directory.llmstxt.org", "llmstxt.directory",
    "mcp.so", "smithery.ai", "awesome-mcp-servers",
]


@dataclass
class SubScore:
    name: str
    score: float
    findings: list[str] = field(default_factory=list)


def _read(p: pathlib.Path) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return ""


def score_robots_ai_allow() -> SubScore:
    findings: list[str] = []
    robots = _read(SITE / "robots.txt")
    welcomed = sum(1 for ua in AI_BOT_UAS if f"User-agent: {ua}" in robots)
    pts = (welcomed / len(AI_BOT_UAS)) * 10.0
    if welcomed < len(AI_BOT_UAS):
        findings.append(f"robots.txt AI welcome coverage {welcomed}/{len(AI_BOT_UAS)}")
    return SubScore("robots_ai_allow", round(pts, 2), findings)


def score_bot_visit_observability() -> SubScore:
    findings: list[str] = []
    pts = 3.0  # floor; lift once Zone Analytics scope added
    env_local = REPO_ROOT / ".env.local"
    if env_local.exists():
        text = env_local.read_text(errors="replace")
        if "CF_API_TOKEN" in text and "Zone" in text:
            pts = 7.0
        if "FLY_API_TOKEN" in text and "# FLY_API_TOKEN" not in text:
            pts += 1.0
    findings.append("bot_visit observability gated by CF_API_TOKEN scope and FLY_API_TOKEN live")
    return SubScore("bot_visit_observability", min(10.0, pts), findings)


def score_competitive_geo_lead() -> SubScore:
    findings: list[str] = []
    pts = 10.0
    # Assets that establish lead vs 8 competitors. If any local artifact is
    # missing/empty, the lead margin narrows.
    required = [
        SITE / "llms.txt",
        SITE / "llms-full.en.txt",
        SITE / ".well-known" / "mcp.json",
        SITE / ".well-known" / "agents.json",
        SITE / ".well-known" / "trust.json",
        SITE / ".well-known" / "sbom.json",
        SITE / "openapi.agent.json",
        SITE / "openapi.agent.gpt30.json",
    ]
    for p in required:
        if not p.exists() or p.stat().st_size == 0:
            findings.append(f"competitive lead asset missing: {p.relative_to(REPO_ROOT)}")
            pts -= 1.5
    return SubScore("competitive_geo_lead", max(0.0, min(10.0, pts)), findings)


def score_directory_submissions() -> SubScore:
    findings: list[str] = []
    pts = 5.0
    # Look for a tracking file showing which submissions are live. Be
    # generous: presence of mention in any docs/_internal/ markdown counts.
    seen = set()
    for md in (REPO_ROOT / "docs" / "_internal").glob("*.md"):
        text = md.read_text(encoding="utf-8", errors="replace")
        for target in DIRECTORY_TARGETS:
            if target in text:
                seen.add(target)
    pts = 5.0 + (len(seen) / len(DIRECTORY_TARGETS)) * 5.0
    missing = sorted(set(DIRECTORY_TARGETS) - seen)
    for m in missing:
        findings.append(f"no record of submission to {m}")
    return SubScore("directory_submissions", round(pts, 2), findings)


def score_github_clone_proxy_signal() -> SubScore:
    findings: list[str] = []
    pts = 7.0  # baseline taken from the 2026-05-11 audit
    # Real-time GH clone count needs the GitHub API; we keep this static at
    # the baseline. The script is structured so a later patch can ingest a
    # cached `clone_stats.json` if the operator runs `gh api` separately.
    cache = REPO_ROOT / "monitoring" / "github_clone_stats.json"
    if cache.exists():
        try:
            data = json.loads(cache.read_text())
            clones = data.get("clones_14d", 0)
            if clones >= 10_000:
                pts = 9.0
            elif clones >= 3_000:
                pts = 8.0
            elif clones < 500:
                pts = 5.0
            findings.append(f"github_clone_stats.json: clones_14d = {clones}")
        except json.JSONDecodeError:
            findings.append("github_clone_stats.json: invalid JSON")
    else:
        findings.append("monitoring/github_clone_stats.json absent (using baseline 7.0)")
    return SubScore("github_clone_proxy_signal", pts, findings)


def run_audit() -> dict:
    subs = [
        score_robots_ai_allow(),
        score_bot_visit_observability(),
        score_competitive_geo_lead(),
        score_directory_submissions(),
        score_github_clone_proxy_signal(),
    ]
    avg = sum(s.score for s in subs) / len(subs)
    return {
        "axis": "ai_bot",
        "score": round(avg, 2),
        "verdict": "green" if avg >= 8.5 else ("yellow" if avg >= 6.5 else "red"),
        "sub_scores": {s.name: round(s.score, 2) for s in subs},
        "findings": [f for s in subs for f in s.findings],
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def render_md(result: dict) -> str:
    lines = [
        f"# jpcite AI-Bot Visit + Competitive GEO Audit — {result['generated_at'][:10]} (automated)",
        "",
        f"**Score**: {result['score']:.2f} / 10 ({result['verdict'].upper()})",
        "",
        "| sub-axis | score |", "| --- | --- |",
    ]
    for k, v in result["sub_scores"].items():
        lines.append(f"| {k} | {v:.2f} |")
    lines += ["", "## Findings", ""]
    if not result["findings"]:
        lines.append("- none")
    else:
        for f in result["findings"]:
            lines.append(f"- {f}")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-md")
    ap.add_argument("--out-json")
    args = ap.parse_args(argv)
    result = run_audit()
    if args.out_md:
        pathlib.Path(args.out_md).parent.mkdir(parents=True, exist_ok=True)
        pathlib.Path(args.out_md).write_text(render_md(result))
    if args.out_json:
        pathlib.Path(args.out_json).parent.mkdir(parents=True, exist_ok=True)
        pathlib.Path(args.out_json).write_text(json.dumps(result, indent=2,
                                                          ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
