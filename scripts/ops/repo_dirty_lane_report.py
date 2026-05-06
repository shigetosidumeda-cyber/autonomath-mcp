#!/usr/bin/env python3
"""Classify git dirty-tree entries into review lanes.

This report is intentionally non-destructive. It does not delete, move, stage,
or rewrite files. Its job is to turn a large mixed dirty tree into reviewable
lanes so release and cleanup work can happen without guessing.
"""

from __future__ import annotations

import argparse
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT = REPO_ROOT / "docs" / "_internal" / "repo_dirty_lanes_latest.md"
JST = timezone(timedelta(hours=9))


@dataclass(frozen=True)
class DirtyEntry:
    status: str
    path: str
    lane: str


LANE_ORDER = [
    "runtime_code",
    "billing_auth_security",
    "migrations",
    "cron_etl_ops",
    "tests",
    "workflows",
    "generated_public_site",
    "openapi_distribution",
    "sdk_distribution",
    "public_docs",
    "internal_docs",
    "operator_offline",
    "benchmarks_monitoring",
    "data_or_local_seed",
    "root_release_files",
    "misc_review",
]


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


def classify_path(path: str) -> str:
    if path.startswith("src/jpintel_mcp/api/") or path.startswith("src/jpintel_mcp/mcp/"):
        if any(
            part in path
            for part in (
                "billing",
                "anon_limit",
                "origin_enforcement",
                "idempotency",
                "cost_cap",
                "line_webhook",
                "appi_",
                "audit_proof",
                "audit_seal",
            )
        ):
            return "billing_auth_security"
        return "runtime_code"
    if path.startswith("src/"):
        return "runtime_code"
    if path.startswith("scripts/migrations/"):
        return "migrations"
    if path.startswith(("scripts/cron/", "scripts/etl/", "scripts/ops/")):
        return "cron_etl_ops"
    if path.startswith("tests/"):
        return "tests"
    if path.startswith(".github/workflows/"):
        return "workflows"
    if path.startswith(("site/", "overrides/")):
        if path.startswith(("site/openapi", "site/mcp-server", "site/server.json")):
            return "openapi_distribution"
        return "generated_public_site"
    if path.startswith("docs/openapi/"):
        return "openapi_distribution"
    if path.startswith(("sdk/", "dxt/")) or path in {
        "server.json",
        "smithery.yaml",
        "mcp-server.json",
        "mcp-server.core.json",
        "mcp-server.full.json",
        "mcp-server.composition.json",
    }:
        return "sdk_distribution"
    if path.startswith("docs/_internal/"):
        return "internal_docs"
    if path.startswith("docs/"):
        return "public_docs"
    if path.startswith("tools/offline/"):
        return "operator_offline"
    if path.startswith(("benchmarks/", "monitoring/", "analytics/", "evals/")):
        return "benchmarks_monitoring"
    if path.startswith("data/") or path.endswith((".db", ".sqlite", ".parquet", ".jsonl")):
        return "data_or_local_seed"
    if path in {
        ".dockerignore",
        ".gitignore",
        "CLAUDE.md",
        "DIRECTORY.md",
        "README.md",
        "MASTER_PLAN_v1.md",
        "entrypoint.sh",
        "mkdocs.yml",
        "pyproject.toml",
        "uv.lock",
    }:
        return "root_release_files"
    if path.startswith(("examples/", "pypi-jpcite-meta/", "docs/en/")):
        return "public_docs"
    return "misc_review"


def parse_status_lines(lines: list[str]) -> list[DirtyEntry]:
    entries: list[DirtyEntry] = []
    for raw in lines:
        if not raw.strip():
            continue
        status = raw[:2]
        path = raw[3:].strip()
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        if not path:
            continue
        entries.append(DirtyEntry(status=status, path=path, lane=classify_path(path)))
    return entries


def collect_entries(repo: Path) -> list[DirtyEntry]:
    out = _run_git(["status", "--short", "--untracked-files=all"], repo)
    return parse_status_lines(out.splitlines())


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
    return status.strip() or "changed"


def _lane_counts(entries: list[DirtyEntry]) -> dict[str, dict[str, int]]:
    counts: dict[str, dict[str, int]] = {}
    for entry in entries:
        lane = counts.setdefault(entry.lane, {})
        label = _status_label(entry.status)
        lane[label] = lane.get(label, 0) + 1
    return counts


def render_markdown(repo: Path) -> str:
    generated_at = datetime.now(UTC).astimezone(JST).isoformat(timespec="seconds")
    entries = collect_entries(repo)
    counts = _lane_counts(entries)

    lines = [
        "# Repo Dirty Lane Report",
        "",
        f"- generated_at: `{generated_at}`",
        f"- repo: `{repo}`",
        f"- dirty_entries: `{len(entries)}`",
        "",
        "## Lane Summary",
        "",
        "| lane | total | modified | untracked | deleted | added/renamed/other |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for lane in LANE_ORDER:
        lane_counts = counts.get(lane, {})
        total = sum(lane_counts.values())
        if total == 0:
            continue
        modified = lane_counts.get("modified", 0)
        untracked = lane_counts.get("untracked", 0)
        deleted = lane_counts.get("deleted", 0)
        other = total - modified - untracked - deleted
        lines.append(f"| {lane} | {total} | {modified} | {untracked} | {deleted} | {other} |")

    lines.extend(
        [
            "",
            "## Review Order",
            "",
            "1. Review `billing_auth_security`, `runtime_code`, `migrations`, and `workflows` before deployment.",
            "2. Regenerate and compare `openapi_distribution`, `sdk_distribution`, and `generated_public_site` as one bundle.",
            "3. Commit `internal_docs`, `operator_offline`, and `benchmarks_monitoring` only when they describe repeatable protocols or compact rollups.",
            "4. Keep bulky local data and raw run outputs ignored; commit source tables, migrations, and small manifests instead.",
            "",
            "## Entries By Lane",
            "",
        ]
    )

    by_lane: dict[str, list[DirtyEntry]] = {}
    for entry in entries:
        by_lane.setdefault(entry.lane, []).append(entry)

    for lane in LANE_ORDER:
        lane_entries = by_lane.get(lane)
        if not lane_entries:
            continue
        lines.extend([f"### {lane}", ""])
        for entry in lane_entries[:80]:
            lines.append(f"- `{_status_label(entry.status)}` `{entry.path}`")
        overflow = len(lane_entries) - 80
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
