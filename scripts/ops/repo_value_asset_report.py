#!/usr/bin/env python3
"""Find repository assets that can become customer value.

This is a non-destructive companion to the hygiene reports. It inventories
source files, docs, benchmarks, prompts, and distribution artifacts that are
likely to become product surfaces, trust proof, or internal data foundation.
"""

from __future__ import annotations

import argparse
import fnmatch
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT = REPO_ROOT / "docs" / "_internal" / "repo_value_assets_latest.md"
JST = timezone(timedelta(hours=9))


@dataclass(frozen=True)
class ValueCategory:
    key: str
    title: str
    value: str
    action: str
    risk: str
    patterns: tuple[str, ...]


@dataclass(frozen=True)
class ValueAsset:
    path: str
    status: str
    category: str


CATEGORIES = (
    ValueCategory(
        key="internal_sensitive_only",
        title="Internal Sensitive Only",
        value="Operator control material that may protect the business but should not be marketed directly.",
        action="Keep internal, inspect before publishing, and summarize only safe conclusions.",
        risk="Secrets, legal drafts, and marketplace applications can leak strategy or credentials.",
        patterns=(
            "docs/_internal/SECRETS*",
            "docs/_internal/*legal*",
            "docs/_internal/*lawyer*",
            "docs/_internal/marketplace_application/*",
            "tools/offline/_inbox*",
            "tools/offline/_quarantine*",
        ),
    ),
    ValueCategory(
        key="ai_first_hop_distribution",
        title="AI First-Hop Distribution",
        value="Assets that help ChatGPT, Claude, Cursor, MCP clients, and agents discover or call jpcite first.",
        action="Keep manifests synchronized and turn integration docs into copy-paste onboarding paths.",
        risk="Version drift or broken manifests make agents stop trusting the endpoint.",
        patterns=(
            "server.json",
            "mcp-server*.json",
            "smithery.yaml",
            "dxt/*",
            "sdk/*",
            "site/downloads/*",
            "site/mcp-server*.json",
            "site/server.json",
            "site/llms*.txt",
            "site/en/llms.txt",
            "docs/integrations/*",
            "site/integrations/*",
        ),
    ),
    ValueCategory(
        key="customer_output_surfaces",
        title="Customer Output Surfaces",
        value="API/MCP/doc assets that can return concrete practitioner outputs instead of generic LLM advice.",
        action="Bundle by persona and prove each surface with acceptance queries.",
        risk="Public/paywalled boundaries, citation quality, and quota behavior must be checked before promotion.",
        patterns=(
            "src/jpintel_mcp/api/intel*.py",
            "src/jpintel_mcp/api/artifacts.py",
            "src/jpintel_mcp/api/evidence*.py",
            "src/jpintel_mcp/api/funding_stack.py",
            "src/jpintel_mcp/api/eligibility_predicate.py",
            "src/jpintel_mcp/api/calculator.py",
            "src/jpintel_mcp/api/narrative*.py",
            "src/jpintel_mcp/api/wave24_endpoints.py",
            "src/jpintel_mcp/mcp/autonomath_tools/intel*.py",
            "src/jpintel_mcp/mcp/autonomath_tools/*evidence*",
            "src/jpintel_mcp/mcp/autonomath_tools/*eligibility*",
            "src/jpintel_mcp/mcp/autonomath_tools/wave24*.py",
            "docs/api-reference.md",
            "docs/mcp-tools.md",
        ),
    ),
    ValueCategory(
        key="data_foundation",
        title="Data Foundation",
        value="Tables, ETL, and cron jobs that make jpcite cheaper and more useful than ad-hoc web research.",
        action="Convert raw joins into stable derived tables and documented refresh jobs.",
        risk="Migrations, destructive rebuilds, and source-license constraints need review before production runs.",
        patterns=(
            "scripts/migrations/*.sql",
            "scripts/etl/*.py",
            "scripts/cron/precompute*.py",
            "scripts/cron/populate*.py",
            "scripts/cron/refresh*.py",
            "scripts/cron/ingest*.py",
            "scripts/cron/meta_analysis_daily.py",
            "src/jpintel_mcp/ingest/*",
            "src/jpintel_mcp/ingest/**/*",
            "data/autonomath_static/*",
            "data/hallucination_guard.yaml",
        ),
    ),
    ValueCategory(
        key="trust_quality_proof",
        title="Trust And Quality Proof",
        value="Benchmarks, smoke tests, evals, monitoring, and release gates that can prove reliability.",
        action="Publish only conservative summaries; keep raw fixtures and internal gates as support.",
        risk="Overclaiming token savings, speedups, or success rates can create marketing and trust risk.",
        patterns=(
            "benchmarks/*",
            "benchmarks/**/*",
            "monitoring/*",
            "tests/eval/*",
            "tests/smoke/*",
            "tests/test_production*.py",
            "tests/test_release_readiness.py",
            "tests/test_pre_deploy_verify.py",
            "tests/test_practitioner_output_acceptance_queries.py",
        ),
    ),
    ValueCategory(
        key="operator_research_to_product",
        title="Operator Research To Product",
        value="Large research loops that can become roadmaps, packs, source matrices, and internal playbooks.",
        action="Promote compact rollups and repeatable prompts; keep raw run output ignored.",
        risk="Raw research may contain unverified claims, duplicated findings, or third-party rights constraints.",
        patterns=(
            "tools/offline/INFO_COLLECTOR*.md",
            "tools/offline/*_audit.json",
            "docs/_internal/*value*",
            "docs/_internal/*source*",
            "docs/_internal/*practitioner*",
            "docs/_internal/*bpo*",
            "docs/_internal/*public_layer*",
            "docs/_internal/*implementation*",
            "docs/_internal/*plan*",
            "docs/_internal/*roadmap*",
        ),
    ),
    ValueCategory(
        key="public_conversion_copy",
        title="Public Conversion Copy",
        value="Docs, pages, examples, and launch collateral that can turn discovered value into paid usage.",
        action="Tie each page to one concrete artifact, benchmark, or first-hop integration path.",
        risk="Copy must avoid unsupported superiority, speed, savings, or legal-advice claims.",
        patterns=(
            "README.md",
            "docs/index.md",
            "docs/getting-started.md",
            "docs/pricing.md",
            "docs/blog/*",
            "docs/launch/*",
            "docs/launch_assets/*",
            "docs/press_kit.md",
            "docs/roadmap.md",
            "site/index.html",
            "site/pricing.html",
            "site/trial.html",
            "site/qa/**/*",
            "site/blog/**/*",
            "site/benchmark/**/*",
            "site/audiences/*.html",
            "site/en/**/*",
        ),
    ),
)


def _run_git(args: list[str], cwd: Path) -> str:
    try:
        return subprocess.check_output(
            ["git", *args],
            cwd=cwd,
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return ""


def _matches(path: str, patterns: tuple[str, ...]) -> bool:
    return any(fnmatch.fnmatch(path, pattern) for pattern in patterns)


def classify_path(path: str) -> str | None:
    for category in CATEGORIES:
        if _matches(path, category.patterns):
            return category.key
    return None


def _status_label(status: str) -> str:
    if status == "??":
        return "untracked"
    if "D" in status:
        return "deleted"
    if "M" in status:
        return "modified"
    if "A" in status:
        return "added"
    if "R" in status:
        return "renamed"
    return status.strip() or "tracked"


def _dirty_status(repo: Path) -> dict[str, str]:
    out = _run_git(["status", "--short", "--untracked-files=all"], repo)
    statuses: dict[str, str] = {}
    for raw in out.splitlines():
        if not raw.strip():
            continue
        status = raw[:2]
        path = raw[3:].strip()
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        if path:
            statuses[path] = _status_label(status)
    return statuses


def _candidate_paths(repo: Path) -> dict[str, str]:
    statuses = _dirty_status(repo)
    paths = set(statuses)
    tracked = _run_git(["ls-files"], repo)
    for line in tracked.splitlines():
        if line:
            paths.add(line)
    return {path: statuses.get(path, "tracked") for path in sorted(paths)}


def collect_assets(repo: Path) -> list[ValueAsset]:
    assets: list[ValueAsset] = []
    for path, status in _candidate_paths(repo).items():
        category = classify_path(path)
        if category is None:
            continue
        assets.append(ValueAsset(path=path, status=status, category=category))
    return assets


def render_markdown(repo: Path) -> str:
    generated_at = datetime.now(UTC).astimezone(JST).isoformat(timespec="seconds")
    assets = collect_assets(repo)
    by_category: dict[str, list[ValueAsset]] = {}
    for asset in assets:
        by_category.setdefault(asset.category, []).append(asset)

    lines = [
        "# Repo Value Asset Report",
        "",
        f"- generated_at: `{generated_at}`",
        f"- repo: `{repo}`",
        f"- value_asset_entries: `{len(assets)}`",
        "",
        "## Summary",
        "",
        "| category | entries | untracked/modified/deleted | value | next action |",
        "|---|---:|---:|---|---|",
    ]

    for category in CATEGORIES:
        category_assets = by_category.get(category.key, [])
        risky_count = sum(1 for asset in category_assets if asset.status != "tracked")
        lines.append(
            f"| {category.key} | {len(category_assets)} | {risky_count} | "
            f"{category.value} | {category.action} |"
        )

    lines.extend(
        [
            "",
            "## Productization Ideas",
            "",
            "1. Turn `customer_output_surfaces` into persona packs: tax advisor, BPO/AI ops, M&A, finance, municipal, and foreign FDI.",
            "2. Turn `data_foundation` into derived answer tables: eligibility predicates, source verification, entity timelines, risk layers, and program combinations.",
            "3. Turn `ai_first_hop_distribution` into agent onboarding: MCP manifest, OpenAPI agent spec, SDK snippets, and `llms.txt` discovery paths.",
            "4. Turn `trust_quality_proof` into conservative proof pages: benchmark method, acceptance queries, source freshness, and uptime/SLA targets.",
            "5. Turn `operator_research_to_product` into compact public artifacts only after license, citation, and claim review.",
            "",
            "## Category Details",
            "",
        ]
    )

    for category in CATEGORIES:
        category_assets = by_category.get(category.key, [])
        lines.extend(
            [
                f"### {category.title}",
                "",
                f"- value: {category.value}",
                f"- action: {category.action}",
                f"- risk: {category.risk}",
                "",
            ]
        )
        for asset in category_assets[:60]:
            lines.append(f"- `{asset.status}` `{asset.path}`")
        overflow = len(category_assets) - 60
        if overflow > 0:
            lines.append(f"- ... `{overflow}` more")
        lines.append("")

    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=REPO_ROOT)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    text = render_markdown(args.repo)
    if args.dry_run:
        print(text)
        return 0
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(text + "\n", encoding="utf-8")
    print(args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
