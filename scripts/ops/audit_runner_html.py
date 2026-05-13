#!/usr/bin/env python3
"""Wave 15 H1/H3 — HTML semantic + WCAG 2.2 AA axis audit runner.

8-sub-axis: landmarks / headings / a11y attrs / contrast (provisional) /
viewport / CWV proxy / perf hints / SEO meta. Walks site/*.html plus
site/audiences/*.html and site/connect/*.html.

Pure stdlib, no LLM. Read-only.
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
    "dashboard.html",
    "playground.html",
    "login.html",
    "artifact.html",
    "sources.html",
]
EXTENDED = [
    "audiences/tax-advisor.html",
    "audiences/admin-scrivener.html",
    "audiences/subsidy-consultant.html",
    "audiences/vc.html",
    "audiences/shinkin.html",
    "connect/claude-code.html",
    "connect/cursor.html",
    "connect/chatgpt.html",
    "connect/codex.html",
    "status/index.html",
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


def _pages() -> list[pathlib.Path]:
    return [SITE / p for p in CORE_PAGES + EXTENDED]


def score_landmarks() -> SubScore:
    findings: list[str] = []
    pts = 10.0
    for p in _pages():
        html = _read(p)
        if not html:
            continue
        for tag in ("<header", "<main", "<footer", "<nav"):
            if tag not in html:
                findings.append(f"{p.name}: missing {tag}")
                pts -= 0.1
    return SubScore("landmarks", max(0.0, min(10.0, pts)), findings)


def score_headings() -> SubScore:
    findings: list[str] = []
    pts = 10.0
    for p in _pages():
        html = _read(p)
        if not html:
            continue
        h1 = re.findall(r"<h1\b[^>]*>", html, flags=re.IGNORECASE)
        if len(h1) != 1:
            findings.append(f"{p.name}: h1 count = {len(h1)} (expected 1)")
            pts -= 0.5
        # heading-order check: first heading should be h1 (best-effort)
        first = re.search(r"<h([1-6])\b", html, flags=re.IGNORECASE)
        if first and first.group(1) != "1":
            findings.append(f"{p.name}: first heading is h{first.group(1)}, not h1")
            pts -= 0.5
    return SubScore("headings", max(0.0, min(10.0, pts)), findings)


def score_a11y() -> SubScore:
    findings: list[str] = []
    pts = 10.0
    for p in _pages():
        html = _read(p)
        if not html:
            continue
        if 'lang="ja"' not in html and 'lang="en"' not in html:
            findings.append(f"{p.name}: <html lang> missing")
            pts -= 0.5
        if 'charset="UTF-8"' not in html and "charset=utf-8" not in html.lower():
            findings.append(f"{p.name}: <meta charset> missing")
            pts -= 0.3
        if (
            p.name not in ("artifact.html",)
            and "skip-link" not in html
            and "Skip to main" not in html
        ):
            findings.append(f"{p.name}: skip-link not detected")
            pts -= 0.2
    return SubScore("a11y_wcag22", max(0.0, min(10.0, pts)), findings)


def score_contrast_provisional() -> SubScore:
    # Provisional — real ratio needs Playwright + axe-core. We just gate
    # on whether the brand variable definitions appear in critical.css.
    findings: list[str] = []
    pts = 8.5
    crit = _read(SITE / "_assets" / "critical.css")
    if not crit:
        crit = _read(SITE / "critical.css")
    if "--text" not in crit and "--accent" not in crit:
        findings.append("critical.css: brand color vars not found (cannot verify contrast static)")
        pts -= 2.0
    return SubScore("contrast_provisional", max(0.0, min(10.0, pts)), findings)


def score_viewport() -> SubScore:
    findings: list[str] = []
    pts = 10.0
    for p in _pages():
        html = _read(p)
        if not html:
            continue
        if 'name="viewport"' not in html:
            findings.append(f"{p.name}: viewport meta missing")
            pts -= 0.5
    return SubScore("viewport", max(0.0, min(10.0, pts)), findings)


def score_cwv_proxy() -> SubScore:
    findings: list[str] = []
    pts = 8.0  # provisional baseline
    for p in _pages():
        html = _read(p)
        if not html:
            continue
        if "preconnect" not in html and "preload" not in html:
            findings.append(f"{p.name}: no preconnect/preload hint")
            pts -= 0.2
    return SubScore("core_web_vitals", max(0.0, min(10.0, pts)), findings)


def score_perf() -> SubScore:
    findings: list[str] = []
    pts = 8.0
    for p in _pages():
        size = (SITE / p.name).stat().st_size if (SITE / p.name).exists() else 0
        if size > 200_000:
            findings.append(f"{p.name}: HTML payload {size:,} bytes (> 200 KB)")
            pts -= 0.3
    return SubScore("perf", max(0.0, min(10.0, pts)), findings)


def score_seo_meta() -> SubScore:
    findings: list[str] = []
    pts = 10.0
    for p in _pages():
        html = _read(p)
        if not html:
            continue
        if 'name="description"' not in html:
            findings.append(f"{p.name}: meta description missing")
            pts -= 0.3
        if 'rel="canonical"' not in html:
            findings.append(f"{p.name}: rel=canonical missing")
            pts -= 0.3
    return SubScore("seo", max(0.0, min(10.0, pts)), findings)


def run_audit() -> dict:
    subs = [
        score_landmarks(),
        score_headings(),
        score_a11y(),
        score_contrast_provisional(),
        score_viewport(),
        score_cwv_proxy(),
        score_perf(),
        score_seo_meta(),
    ]
    avg = sum(s.score for s in subs) / len(subs)
    return {
        "axis": "html",
        "score": round(avg, 2),
        "verdict": "green" if avg >= 8.5 else ("yellow" if avg >= 6.5 else "red"),
        "sub_scores": {s.name: round(s.score, 2) for s in subs},
        "findings": [f for s in subs for f in s.findings],
        "generated_at": datetime.now(UTC).isoformat(),
    }


def render_md(result: dict) -> str:
    lines = [
        f"# jpcite HTML Semantic + A11y Audit — {result['generated_at'][:10]} (automated)",
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
        for f in result["findings"][:200]:
            lines.append(f"- {f}")
        if len(result["findings"]) > 200:
            lines.append(f"- ... and {len(result['findings']) - 200} more")
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
        pathlib.Path(args.out_json).write_text(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
