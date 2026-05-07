#!/usr/bin/env python3
"""Inventory repository organization without mutating files.

This script is a lightweight hygiene report for a large mixed repo. It does not
delete, move, or rewrite anything. The goal is to make source/generated/data/
operator boundaries visible before cleanup or deployment decisions.
"""

from __future__ import annotations

import argparse
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT = REPO_ROOT / "docs" / "_internal" / "repo_hygiene_inventory_latest.md"
JST = timezone(timedelta(hours=9))

GENERATED_OR_OUTPUT_ROOTS = {
    "site",
    "dist",
    "dist.bak",
    "dist.bak2",
    "dist.bak3",
    "analysis_wave18",
    "analysis_value",
    "autonomath_staging",
}
LOCAL_HEAVY_PATTERNS = (
    "*.db",
    "*.db-shm",
    "*.db-wal",
    "*.sqlite",
    "*.sqlite-shm",
    "*.sqlite-wal",
)
ROOT_NOISE_NAMES = {
    "pyproject.toml.bak",
    "tmp_iter7_a3",
    "parts",
    ".venv312",
}


@dataclass(frozen=True)
class TopLevelItem:
    name: str
    kind: str
    size_bytes: int
    tracked_status: str


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


def _tracked_names(repo: Path) -> set[str]:
    out = _run_git(["ls-files"], repo)
    names: set[str] = set()
    for line in out.splitlines():
        if not line:
            continue
        names.add(line.split("/", 1)[0])
    return names


def _untracked_names(repo: Path) -> set[str]:
    out = _run_git(["status", "--short", "--untracked-files=all"], repo)
    names: set[str] = set()
    for line in out.splitlines():
        if not line.startswith("?? "):
            continue
        path = line[3:].strip()
        if path:
            names.add(path.split("/", 1)[0])
    return names


def _path_size(path: Path) -> int:
    if not path.exists():
        return 0
    if path.is_file() or path.is_symlink():
        try:
            return path.lstat().st_size
        except OSError:
            return 0
    total = 0
    for child in path.rglob("*"):
        try:
            if child.is_file() or child.is_symlink():
                total += child.lstat().st_size
        except OSError:
            continue
    return total


def _human_size(size: int) -> str:
    value = float(size)
    units = ["B", "KB", "MB", "GB", "TB"]
    for unit in units:
        if value < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(value)}B"
            return f"{value:.1f}{unit}"
        value /= 1024
    return f"{size}B"


def _classify(path: Path) -> str:
    name = path.name
    if name in {"src", "tests", "scripts", "docs", "sdk", "dxt", "examples"}:
        return "source_or_test"
    if name in GENERATED_OR_OUTPUT_ROOTS:
        return "generated_or_output"
    if name in {"data"}:
        return "data_mixed"
    if name in {"tools", "research", "docs_internal"}:
        return "operator_or_research"
    if name in ROOT_NOISE_NAMES or name.startswith(".venv"):
        return "local_noise"
    if path.is_file() and any(path.match(pattern) for pattern in LOCAL_HEAVY_PATTERNS):
        return "local_runtime_data"
    if name.startswith("."):
        return "tooling_or_cache"
    return "root_file_or_misc"


def collect_items(repo: Path) -> list[TopLevelItem]:
    tracked = _tracked_names(repo)
    untracked = _untracked_names(repo)
    items: list[TopLevelItem] = []
    for path in sorted(repo.iterdir(), key=lambda p: p.name):
        if path.name == ".git":
            continue
        if path.name in tracked and path.name in untracked:
            status = "tracked_and_untracked"
        elif path.name in tracked:
            status = "tracked"
        elif path.name in untracked:
            status = "untracked"
        else:
            status = "ignored_or_local"
        items.append(
            TopLevelItem(
                name=path.name,
                kind=_classify(path),
                size_bytes=_path_size(path),
                tracked_status=status,
            )
        )
    return items


def _git_status_counts(repo: Path) -> tuple[int, int, int]:
    out = _run_git(["status", "--short"], repo)
    modified = 0
    deleted = 0
    untracked = 0
    for line in out.splitlines():
        if line.startswith("?? "):
            untracked += 1
        elif "D" in line[:2]:
            deleted += 1
        else:
            modified += 1
    return modified, deleted, untracked


def render_markdown(repo: Path) -> str:
    generated_at = datetime.now(UTC).astimezone(JST).isoformat(timespec="seconds")
    items = collect_items(repo)
    modified, deleted, untracked = _git_status_counts(repo)
    largest = sorted(items, key=lambda item: item.size_bytes, reverse=True)[:20]
    by_kind: dict[str, tuple[int, int]] = {}
    for item in items:
        count, size = by_kind.get(item.kind, (0, 0))
        by_kind[item.kind] = (count + 1, size + item.size_bytes)

    lines = [
        "# Repo Hygiene Inventory",
        "",
        f"- generated_at: `{generated_at}`",
        f"- repo: `{repo}`",
        f"- git_modified_entries: `{modified}`",
        f"- git_deleted_entries: `{deleted}`",
        f"- git_untracked_entries: `{untracked}`",
        "",
        "## Summary By Kind",
        "",
        "| kind | top-level count | total size |",
        "|---|---:|---:|",
    ]
    for kind, (count, size) in sorted(by_kind.items()):
        lines.append(f"| {kind} | {count} | {_human_size(size)} |")

    lines.extend(
        [
            "",
            "## Largest Top-Level Items",
            "",
            "| item | kind | status | size |",
            "|---|---|---|---:|",
        ]
    )
    for item in largest:
        lines.append(
            f"| `{item.name}` | {item.kind} | {item.tracked_status} | "
            f"{_human_size(item.size_bytes)} |"
        )

    lines.extend(
        [
            "",
            "## Non-Destructive Recommendations",
            "",
            "1. Treat root-level DB/WAL/SHM files as local runtime data, not source.",
            "2. Keep generated public artifacts reviewable, but separate source changes from generated diffs.",
            "3. Move future offline loop outputs into a single ignored artifact root or keep them under `tools/offline/_inbox/` with a manifest.",
            "4. Keep `DIRECTORY.md` as the human navigation map and this report as the machine-generated inventory.",
            "5. Before deploy, inspect Docker context and git dirty tree by lane: runtime code, migrations, generated public, docs, SDK, operator research.",
            "",
        ]
    )
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
