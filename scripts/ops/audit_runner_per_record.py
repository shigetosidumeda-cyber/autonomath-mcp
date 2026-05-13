#!/usr/bin/env python3
"""Wave 15 H1/H3 — per-record SEO quality axis audit runner.

7-sub-axis sample audit over the 9,964 generated cases / laws / enforcement
pages. Samples ~30 pages per family to keep runtime bounded; emits the same
JSON envelope the regression gate consumes.

Pure stdlib. Read-only.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import random
import re
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
SITE = REPO_ROOT / "site"

SAMPLE_PER_FAMILY = 30
RNG = random.Random(20260511)


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


def _sample(folder: pathlib.Path, pattern: str = "*.html") -> list[pathlib.Path]:
    if not folder.exists():
        return []
    pages = sorted(folder.glob(pattern))
    if len(pages) <= SAMPLE_PER_FAMILY:
        return pages
    return RNG.sample(pages, SAMPLE_PER_FAMILY)


def score_canonical_extensionless() -> SubScore:
    findings: list[str] = []
    pts = 10.0
    cases = _sample(SITE / "cases")
    if cases:
        bad = 0
        for p in cases:
            html = _read(p)
            m = re.search(r'rel="canonical"\s+href="([^"]+)"', html)
            if m and m.group(1).endswith(".html"):
                bad += 1
        if bad:
            findings.append(f"cases: canonical includes .html in {bad}/{len(cases)} sample")
            pts -= 5.0
    # laws + enforcement assumed green by sample
    laws = _sample(SITE / "laws")
    if laws:
        bad = sum(1 for p in laws if re.search(r'rel="canonical"\s+href="[^"]+\.html"', _read(p)))
        if bad:
            findings.append(f"laws: canonical .html in {bad}/{len(laws)}")
            pts -= 1.0
    return SubScore("cases_canonical_extensionless", max(0.0, min(10.0, pts)), findings)


def score_schema_jsonld() -> SubScore:
    findings: list[str] = []
    pts = 10.0
    for fam, folder in [("cases", "cases"), ("laws", "laws"), ("enforcement", "enforcement")]:
        pages = _sample(SITE / folder)
        if not pages:
            continue
        missing_breadcrumb = 0
        for p in pages:
            html = _read(p)
            if "BreadcrumbList" not in html:
                missing_breadcrumb += 1
        if missing_breadcrumb:
            findings.append(
                f"{fam}: BreadcrumbList JSON-LD missing in {missing_breadcrumb}/{len(pages)}"
            )
            pts -= 1.0
    return SubScore("schema_jsonld", max(0.0, min(10.0, pts)), findings)


def score_internal_link_density() -> SubScore:
    findings: list[str] = []
    pts = 10.0
    for fam, folder in [("cases", "cases"), ("laws", "laws"), ("enforcement", "enforcement")]:
        pages = _sample(SITE / folder)
        if not pages:
            continue
        avg_links = 0
        for p in pages:
            html = _read(p)
            avg_links += len(re.findall(r'href="/', html))
        avg_links //= max(len(pages), 1)
        if avg_links < 5:
            findings.append(f"{fam}: avg internal link density {avg_links} (<5)")
            pts -= 1.5
    return SubScore("internal_link_density", max(0.0, min(10.0, pts)), findings)


def score_sitemap_health() -> SubScore:
    findings: list[str] = []
    pts = 10.0
    idx = _read(SITE / "sitemap-index.xml")
    for shard in (
        "sitemap-cases.xml",
        "sitemap-laws.xml",
        "sitemap-laws-en.xml",
        "sitemap-enforcement-cases.xml",
    ):
        if shard not in idx:
            findings.append(f"sitemap-index.xml missing {shard}")
            pts -= 2.0
    return SubScore("sitemap_health", max(0.0, min(10.0, pts)), findings)


def score_per_page_meta() -> SubScore:
    findings: list[str] = []
    pts = 10.0
    legacy = ["jpintel", "AutonoMath", "税務会計AI", "zeimu-kaikei.ai"]
    for fam, folder in [("cases", "cases"), ("laws", "laws"), ("enforcement", "enforcement")]:
        pages = _sample(SITE / folder)
        if not pages:
            continue
        for p in pages:
            html = _read(p)
            for brand in legacy:
                # Skip llms.txt comment bridge — these are pages, not docs.
                visible = re.sub(r"<!--.+?-->", "", html, flags=re.DOTALL)
                if brand in visible:
                    findings.append(f"{fam}/{p.name}: legacy brand `{brand}` leak")
                    pts -= 0.5
                    break
    return SubScore("per_page_meta", max(0.0, min(10.0, pts)), findings)


def score_cross_link_schema() -> SubScore:
    findings: list[str] = []
    pts = 10.0
    for fam, folder in [("cases", "cases"), ("laws", "laws"), ("enforcement", "enforcement")]:
        pages = _sample(SITE / folder)
        if not pages:
            continue
        without_mentions = sum(
            1 for p in pages if '"mentions"' not in _read(p) and '"citation"' not in _read(p)
        )
        if without_mentions == len(pages):
            findings.append(f"{fam}: 0/{len(pages)} JSON-LD carry mentions/citation")
            pts -= 1.5
    return SubScore("cross_link_schema", max(0.0, min(10.0, pts)), findings)


def score_a11y_cwv() -> SubScore:
    findings: list[str] = []
    pts = 9.0
    for fam, folder in [("cases", "cases"), ("laws", "laws"), ("enforcement", "enforcement")]:
        pages = _sample(SITE / folder)
        if not pages:
            continue
        no_skip = sum(
            1 for p in pages if "skip-link" not in _read(p) and "Skip to main" not in _read(p)
        )
        if no_skip > len(pages) * 0.5:
            findings.append(f"{fam}: {no_skip}/{len(pages)} missing skip-link")
            pts -= 0.5
    return SubScore("a11y_cwv", max(0.0, min(10.0, pts)), findings)


def run_audit() -> dict:
    subs = [
        score_canonical_extensionless(),
        score_schema_jsonld(),
        score_internal_link_density(),
        score_sitemap_health(),
        score_per_page_meta(),
        score_cross_link_schema(),
        score_a11y_cwv(),
    ]
    avg = sum(s.score for s in subs) / len(subs)
    page_count = 0
    for folder in ("cases", "laws", "enforcement"):
        page_count += len(list((SITE / folder).glob("*.html"))) if (SITE / folder).exists() else 0
    return {
        "axis": "per_record",
        "score": round(avg, 2),
        "verdict": "green" if avg >= 8.5 else ("yellow" if avg >= 6.5 else "red"),
        "sub_scores": {s.name: round(s.score, 2) for s in subs},
        "findings": [f for s in subs for f in s.findings],
        "page_count_total": page_count,
        "sample_per_family": SAMPLE_PER_FAMILY,
        "generated_at": datetime.now(UTC).isoformat(),
    }


def render_md(result: dict) -> str:
    lines = [
        f"# jpcite Per-Record SEO Quality Audit — {result['generated_at'][:10]} (automated)",
        "",
        f"**Score**: {result['score']:.2f} / 10 ({result['verdict'].upper()})",
        f"**Pages sampled**: {result['sample_per_family']} per family. Total page corpus: {result['page_count_total']:,}.",
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
