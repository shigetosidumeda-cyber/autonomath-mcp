#!/usr/bin/env python3
"""Wave 15 H1/H3 — GEO (AI agent discovery) axis audit runner.

8-sub-axis: robots AI welcome / llms.txt format / mcp.json / agents.json /
openapi layers / sitemap-llms / Schema.org Dataset+Service / legacy bridge
marker discipline.

Pure stdlib. Read-only.
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
WELL_KNOWN = SITE / ".well-known"

AI_BOT_UAS = [
    "GPTBot", "ChatGPT-User", "OAI-SearchBot", "ClaudeBot", "Claude-User",
    "Claude-SearchBot", "anthropic-ai", "PerplexityBot", "Google-Extended",
    "CCBot", "Applebot-Extended", "Meta-ExternalAgent", "Amazonbot",
    "Bytespider",
]
EMERGING_AI_BOTS = ["cohere-ai", "Diffbot", "YouBot", "xAI-Crawler"]


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


def _exists(p: pathlib.Path) -> bool:
    return p.exists() and p.stat().st_size > 0


def score_robots_ai_welcome() -> SubScore:
    findings: list[str] = []
    robots = _read(SITE / "robots.txt")
    welcomed = sum(1 for ua in AI_BOT_UAS if f"User-agent: {ua}" in robots)
    pts = (welcomed / len(AI_BOT_UAS)) * 10.0
    if welcomed < len(AI_BOT_UAS):
        findings.append(f"AI bot welcome coverage {welcomed}/{len(AI_BOT_UAS)}")
    for ua in EMERGING_AI_BOTS:
        if f"User-agent: {ua}" not in robots:
            findings.append(f"emerging bot not explicitly welcomed: {ua}")
    return SubScore("robots_ai_welcome", round(pts, 2), findings)


def score_llms_txt() -> SubScore:
    findings: list[str] = []
    pts = 10.0
    for name in ["llms.txt", "llms.en.txt", "llms-full.txt", "llms-full.en.txt"]:
        if not _exists(SITE / name):
            findings.append(f"missing {name}")
            pts -= 2.5
    ja = _read(SITE / "llms.txt")
    if not ja.startswith("# jpcite"):
        findings.append("llms.txt: H1 != '# jpcite'")
        pts -= 1.0
    if "## Authentication" not in ja:
        findings.append("llms.txt: missing ## Authentication section header")
        pts -= 0.5
    return SubScore("llms_txt", max(0.0, min(10.0, pts)), findings)


def score_mcp_discovery() -> SubScore:
    findings: list[str] = []
    pts = 10.0
    mcp = WELL_KNOWN / "mcp.json"
    if not _exists(mcp):
        findings.append("missing /.well-known/mcp.json")
        pts -= 5.0
    else:
        try:
            data = json.loads(_read(mcp))
            for k in ("name", "version", "transport"):
                if k not in data and k not in (data.get("server", {}) or {}):
                    findings.append(f"mcp.json: key `{k}` missing")
                    pts -= 0.5
        except json.JSONDecodeError as e:
            findings.append(f"mcp.json: invalid JSON ({e})")
            pts -= 3.0
    return SubScore("mcp_discovery", max(0.0, min(10.0, pts)), findings)


def score_agents_plugin_json() -> SubScore:
    findings: list[str] = []
    pts = 10.0
    for fname in ("agents.json", "ai-plugin.json"):
        p = WELL_KNOWN / fname
        if not _exists(p):
            findings.append(f"missing /.well-known/{fname}")
            pts -= 2.5
            continue
        try:
            data = json.loads(_read(p))
            if fname == "ai-plugin.json":
                logo = data.get("logo_url", "")
                if logo and "/assets/" not in logo and "//" in logo:
                    findings.append(f"ai-plugin.json: logo_url may 404 ({logo})")
                    pts -= 1.0
        except json.JSONDecodeError as e:
            findings.append(f"{fname}: invalid JSON ({e})")
            pts -= 2.0
    return SubScore("agents_plugin_json", max(0.0, min(10.0, pts)), findings)


def score_openapi_layers() -> SubScore:
    findings: list[str] = []
    pts = 10.0
    for fname in ["openapi.agent.json", "openapi.agent.gpt30.json"]:
        if not _exists(SITE / fname):
            findings.append(f"missing site/{fname}")
            pts -= 3.0
    return SubScore("openapi_layers", max(0.0, min(10.0, pts)), findings)


def score_sitemap_llms() -> SubScore:
    findings: list[str] = []
    pts = 10.0
    if not _exists(SITE / "sitemap-llms.xml"):
        findings.append("sitemap-llms.xml missing (AI-only sitemap shard)")
        pts = 0.0
    return SubScore("sitemap_llms", pts, findings)


def score_schema_dataset_service() -> SubScore:
    findings: list[str] = []
    pts = 10.0
    index = _read(SITE / "index.html")
    needed = ["SoftwareApplication", "Organization", "WebSite", "Dataset",
              "WebAPI", "Service"]
    missing = [t for t in needed if f'"@type": "{t}"' not in index and f'"@type":"{t}"' not in index]
    for t in missing:
        findings.append(f"index.html: Schema.org @type {t} not detected")
        pts -= 1.0
    return SubScore("schema_dataset_service", max(0.0, min(10.0, pts)), findings)


def score_legacy_bridge_marker() -> SubScore:
    findings: list[str] = []
    pts = 10.0
    # Marker should appear ONCE in llms.txt and once in en. Leakage in HTML
    # body or JSON-LD is the regression.
    legacy = ["税務会計AI", "AutonoMath", "zeimu-kaikei.ai"]
    for p in ("index.html", "pricing.html", "dashboard.html"):
        html = _read(SITE / p)
        for brand in legacy:
            # Allow inside <!-- ... --> comments only.
            visible = re.sub(r"<!--.+?-->", "", html, flags=re.DOTALL)
            cnt = visible.count(brand)
            if cnt > 0:
                findings.append(f"{p}: legacy brand `{brand}` leak x{cnt}")
                pts -= 0.5
    return SubScore("legacy_bridge_marker", max(0.0, min(10.0, pts)), findings)


def run_audit() -> dict:
    subs = [
        score_robots_ai_welcome(),
        score_llms_txt(),
        score_mcp_discovery(),
        score_agents_plugin_json(),
        score_openapi_layers(),
        score_sitemap_llms(),
        score_schema_dataset_service(),
        score_legacy_bridge_marker(),
    ]
    avg = sum(s.score for s in subs) / len(subs)
    return {
        "axis": "geo",
        "score": round(avg, 2),
        "verdict": "green" if avg >= 8.5 else ("yellow" if avg >= 6.5 else "red"),
        "sub_scores": {s.name: round(s.score, 2) for s in subs},
        "findings": [f for s in subs for f in s.findings],
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def render_md(result: dict) -> str:
    lines = [
        f"# jpcite GEO Health Audit — {result['generated_at'][:10]} (automated)",
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
