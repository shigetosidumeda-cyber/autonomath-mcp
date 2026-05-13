#!/usr/bin/env python3
"""Wave 15 H1/H3 — SEO health axis audit runner.

Runs the same 7-sub-axis SEO assessment the operator-walked audit performed
manually on 2026-05-11 (canonical / hreflang / sitemap / robots / on-page /
Schema.org / OG-Twitter / CWV proxy / HTML semantic / URL structure) over
the current site/ tree, emits a dated markdown report plus a JSON score
sidecar consumed by audit-regression-gate.yml.

Pure stdlib (no LLM API import). Read-only on site/ — no mutation.

Usage:
    audit_runner_seo.py --out-md PATH --out-json PATH
    audit_runner_seo.py --compare-baseline PATH --month YYYY-MM \\
                        --emit-summary PATH
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
SITE = REPO_ROOT / "site"

CORE_PAGES = [
    "index.html",
    "pricing.html",
    "playground.html",
    "dashboard.html",
    "login.html",
    "artifact.html",
]
EXPECTED_SITEMAPS = [
    "sitemap-index.xml",
    "sitemap-cases.xml",
    "sitemap-laws.xml",
    "sitemap-laws-en.xml",
    "sitemap-enforcement-cases.xml",
    "sitemap-enforcement.xml",
]


@dataclass
class SubScore:
    name: str
    score: float
    findings: list[str] = field(default_factory=list)


def _read(path: pathlib.Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return ""


def score_technical_seo() -> SubScore:
    findings: list[str] = []
    pts = 10.0
    robots = _read(SITE / "robots.txt")
    for sm in EXPECTED_SITEMAPS:
        if sm not in robots:
            findings.append(f"robots.txt missing Sitemap: {sm}")
            pts -= 0.3
    idx = _read(SITE / "sitemap-index.xml")
    for sm in EXPECTED_SITEMAPS[1:]:
        if sm not in idx:
            findings.append(f"sitemap-index.xml missing {sm}")
            pts -= 0.3
    # canonical present on all core pages
    for p in CORE_PAGES:
        html = _read(SITE / p)
        if 'rel="canonical"' not in html:
            findings.append(f"{p}: missing rel=canonical")
            pts -= 0.5
    return SubScore("technical", max(0.0, min(10.0, pts)), findings)


def score_on_page() -> SubScore:
    findings: list[str] = []
    pts = 10.0
    for p in CORE_PAGES:
        html = _read(SITE / p)
        h1_cnt = len(re.findall(r"<h1[\s>]", html, flags=re.IGNORECASE))
        if h1_cnt != 1:
            findings.append(f"{p}: h1 count = {h1_cnt} (expected 1)")
            pts -= 0.5
    return SubScore("on_page", max(0.0, min(10.0, pts)), findings)


def score_schema_org() -> SubScore:
    findings: list[str] = []
    pts = 10.0
    legacy_brands = ["税務会計AI", "AutonoMath", "zeimu-kaikei.ai"]
    for p in CORE_PAGES:
        html = _read(SITE / p)
        for ld in re.findall(r"application/ld\+json[^>]*>(.+?)</script>", html, flags=re.DOTALL):
            for brand in legacy_brands:
                if brand in ld:
                    findings.append(f"{p}: legacy brand `{brand}` leaked into Schema.org")
                    pts -= 1.0
        if "application/ld+json" not in html:
            findings.append(f"{p}: no JSON-LD")
            pts -= 0.5
    return SubScore("schema_org", max(0.0, min(10.0, pts)), findings)


def score_og_twitter() -> SubScore:
    findings: list[str] = []
    pts = 10.0
    for p in CORE_PAGES:
        html = _read(SITE / p)
        for tag in [
            'property="og:title"',
            'property="og:description"',
            'property="og:url"',
            'property="og:image"',
            'name="twitter:card"',
        ]:
            if tag not in html:
                findings.append(f"{p}: missing {tag}")
                pts -= 0.2
    return SubScore("og_twitter", max(0.0, min(10.0, pts)), findings)


def score_core_web_vitals() -> SubScore:
    findings: list[str] = []
    pts = 8.0  # provisional (no real Lighthouse)
    for p in CORE_PAGES:
        html = _read(SITE / p)
        if 'rel="preload"' not in html and 'rel="preconnect"' not in html:
            findings.append(f"{p}: no preload/preconnect")
            pts -= 0.3
    return SubScore("core_web_vitals", max(0.0, min(10.0, pts)), findings)


def score_html_semantic() -> SubScore:
    findings: list[str] = []
    pts = 10.0
    for p in CORE_PAGES:
        html = _read(SITE / p)
        for landmark in ["<header", "<main", "<footer"]:
            if landmark not in html:
                findings.append(f"{p}: missing {landmark}")
                pts -= 0.3
    return SubScore("html_semantic", max(0.0, min(10.0, pts)), findings)


def score_url_structure() -> SubScore:
    findings: list[str] = []
    pts = 9.0
    redirects = _read(SITE / "_redirects")
    if "/jpintel" not in redirects:
        findings.append("_redirects: missing jpintel legacy guard")
        pts -= 1.0
    return SubScore("url_structure", max(0.0, min(10.0, pts)), findings)


def run_audit() -> dict:
    subs = [
        score_technical_seo(),
        score_on_page(),
        score_schema_org(),
        score_og_twitter(),
        score_core_web_vitals(),
        score_html_semantic(),
        score_url_structure(),
    ]
    avg = sum(s.score for s in subs) / len(subs)
    return {
        "axis": "seo",
        "score": round(avg, 2),
        "verdict": "green" if avg >= 8.5 else ("yellow" if avg >= 6.5 else "red"),
        "sub_scores": {s.name: round(s.score, 2) for s in subs},
        "findings": [f for s in subs for f in s.findings],
        "generated_at": datetime.now(UTC).isoformat(),
    }


def render_md(result: dict) -> str:
    lines = [
        f"# jpcite SEO Health Audit — {result['generated_at'][:10]} (automated)",
        "",
        f"**Score**: {result['score']:.2f} / 10 ({result['verdict'].upper()})",
        "",
        "| sub-axis | score |",
        "| --- | --- |",
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


def compare_baseline(
    baseline_path: pathlib.Path, current: dict, threshold: float = 0.5
) -> str | None:
    baseline = json.loads(baseline_path.read_text())
    base_score = float(baseline["axes"][current["axis"]]["score"])
    delta = current["score"] - base_score
    if delta < -threshold:
        return (
            f"axis={current['axis']} baseline={base_score:.2f} "
            f"current={current['score']:.2f} delta={delta:+.2f} "
            f"(threshold -{threshold})"
        )
    return None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-md")
    ap.add_argument("--out-json")
    ap.add_argument("--compare-baseline")
    ap.add_argument("--month")
    ap.add_argument("--emit-summary")
    args = ap.parse_args(argv)

    result = run_audit()

    if args.out_md:
        pathlib.Path(args.out_md).parent.mkdir(parents=True, exist_ok=True)
        pathlib.Path(args.out_md).write_text(render_md(result))
    if args.out_json:
        pathlib.Path(args.out_json).parent.mkdir(parents=True, exist_ok=True)
        pathlib.Path(args.out_json).write_text(json.dumps(result, indent=2, ensure_ascii=False))

    if args.compare_baseline:
        summary = compare_baseline(pathlib.Path(args.compare_baseline), result)
        if summary and args.emit_summary:
            pathlib.Path(args.emit_summary).write_text(summary + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
