#!/usr/bin/env python3
"""Generate a read-only G5 staging separation readiness report.

This report intentionally does not move, delete, copy, or rewrite source files.
It reads local filesystem metadata, text line counts, and read-only git status
only, then emits operator dry-run commands as inert strings for owner review.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = REPO_ROOT / "analysis_wave18" / "staging_separation_plan_2026-05-01.json"
DEFAULT_MARKDOWN_OUTPUT = (
    REPO_ROOT / "analysis_wave18" / "staging_separation_plan_2026-05-01.md"
)

REPORT_DATE = "2026-05-01"
REPORT_ID = "G5_STAGING_SEPARATION"

PROTECTED_RELATIVE_PATHS = {
    Path("src/jpintel_mcp/api/intelligence.py"),
    Path("src/jpintel_mcp/services/evidence_packet.py"),
    Path("src/jpintel_mcp/api/main.py"),
    Path("src/jpintel_mcp/api/programs.py"),
    Path("research/loops/OTHER_CLI_AUTO_LOOP_PROMPT.md"),
    Path("research/loops/EXECUTION_LOG.md"),
}
SKIP_DIR_NAMES = {
    ".git",
    ".hg",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".venv",
    "__pycache__",
    "node_modules",
}
RAW_SKIP_DIR_NAMES = {".git", ".hg"}
STAGING_EXACT_DIR_NAMES = {
    "autonomath_staging",
    "stage",
    "staged",
    "staging",
    "staging_area",
}
STAGING_NAME_FRAGMENTS = ("staging", "salvage_from_tmp", "scratch")
BINARY_EXTENSIONS = {
    ".db",
    ".db-shm",
    ".db-wal",
    ".duckdb",
    ".gif",
    ".gz",
    ".ico",
    ".jpg",
    ".jpeg",
    ".pdf",
    ".png",
    ".pyc",
    ".sqlite",
    ".sqlite3",
    ".webp",
    ".zip",
}
LARGE_FILE_BYTES = 10 * 1024 * 1024


@dataclass
class FileSummary:
    path: str
    bytes: int
    loc: int
    text: bool
    binary_reason: str | None = None


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _rel(path: Path, repo_root: Path) -> str:
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _is_protected_path(path: Path, repo_root: Path) -> bool:
    rel = Path(_rel(path, repo_root))
    if rel in PROTECTED_RELATIVE_PATHS:
        return True
    return any(part == "_archive" or part.endswith("_archive") for part in rel.parts)


def _is_staging_like_dir(path: Path) -> bool:
    name = path.name.lower()
    if name in STAGING_EXACT_DIR_NAMES:
        return True
    return any(fragment in name for fragment in STAGING_NAME_FRAGMENTS)


def _is_probably_binary(path: Path, sample: bytes) -> tuple[bool, str | None]:
    suffixes = {suffix.lower() for suffix in path.suffixes}
    if suffixes & BINARY_EXTENSIONS or path.suffix.lower() in BINARY_EXTENSIONS:
        return True, "binary_extension"
    if b"\x00" in sample:
        return True, "nul_byte"
    try:
        sample.decode("utf-8")
    except UnicodeDecodeError:
        return True, "utf8_decode_error"
    return False, None


def _count_text_lines(path: Path) -> int:
    lines = 0
    last_byte = b""
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            lines += chunk.count(b"\n")
            last_byte = chunk[-1:]
    if last_byte and last_byte != b"\n":
        lines += 1
    return lines


def _summarize_file(path: Path, repo_root: Path) -> FileSummary:
    size = path.stat().st_size
    with path.open("rb") as handle:
        sample = handle.read(8192)
    is_binary, reason = _is_probably_binary(path, sample)
    if is_binary:
        return FileSummary(
            path=_rel(path, repo_root),
            bytes=size,
            loc=0,
            text=False,
            binary_reason=reason,
        )
    return FileSummary(
        path=_rel(path, repo_root),
        bytes=size,
        loc=_count_text_lines(path),
        text=True,
    )


def discover_staging_roots(repo_root: Path) -> list[Path]:
    roots: list[Path] = []
    for current, dirs, _files in os.walk(repo_root):
        current_path = Path(current)
        dirs[:] = sorted(
            d
            for d in dirs
            if d not in SKIP_DIR_NAMES and not _is_protected_path(current_path / d, repo_root)
        )
        if current_path == repo_root:
            continue
        if _is_protected_path(current_path, repo_root):
            dirs[:] = []
            continue
        if _is_staging_like_dir(current_path):
            roots.append(current_path)
            dirs[:] = []
    return sorted(roots, key=lambda path: _rel(path, repo_root))


def _git_lines(repo_root: Path, args: list[str]) -> list[str]:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), *args],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []
    if result.returncode != 0:
        return []
    return [line for line in result.stdout.splitlines() if line.strip()]


def _git_available(repo_root: Path) -> bool:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "--is-inside-work-tree"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0 and result.stdout.strip() == "true"


def _git_summary(repo_root: Path, staging_roots: list[Path]) -> dict[str, Any]:
    available = _git_available(repo_root)
    if not available:
        return {
            "available": False,
            "dirty_path_count": None,
            "ignored_staging_path_count": None,
            "status_sample": [],
            "staging_status": {},
        }

    status_lines = _git_lines(repo_root, ["status", "--short"])
    staging_status: dict[str, Any] = {}
    for root in staging_roots:
        rel = _rel(root, repo_root)
        tracked = _git_lines(repo_root, ["ls-files", "--", rel])
        untracked = _git_lines(repo_root, ["ls-files", "--others", "--exclude-standard", "--", rel])
        ignored = _git_lines(
            repo_root,
            ["ls-files", "--others", "--ignored", "--exclude-standard", "--", rel],
        )
        status = _git_lines(repo_root, ["status", "--short", "--ignored=matching", "--", rel])
        staging_status[rel] = {
            "tracked_file_count": len(tracked),
            "untracked_file_count": len(untracked),
            "ignored_file_count": len(ignored),
            "status_sample": status[:20],
        }

    ignored_count = sum(
        int(row["ignored_file_count"]) for row in staging_status.values() if row is not None
    )
    return {
        "available": True,
        "dirty_path_count": len(status_lines),
        "ignored_staging_path_count": ignored_count,
        "status_sample": status_lines[:50],
        "staging_status": staging_status,
    }


def _owner_area(top_level: str) -> dict[str, str]:
    normalized = top_level.lower()
    if normalized in {"api_meta", "mcp_tools"}:
        return {
            "owner_area": "api_mcp",
            "confidence": "medium",
            "reason": "API/MCP tool or metadata staging subtree",
        }
    if normalized in {"learning", "proactive", "eval"}:
        return {
            "owner_area": "quality_ml_eval",
            "confidence": "medium",
            "reason": "evaluation, learning, or proactive automation subtree",
        }
    if normalized in {"ci_cd", "infra", "launch", "release", "loadtest", "perf"}:
        return {
            "owner_area": "infra_release",
            "confidence": "medium",
            "reason": "deployment, release, performance, or load-test subtree",
        }
    if normalized in {"compliance", "docs_internal", "marketing"}:
        return {
            "owner_area": "docs_compliance_growth",
            "confidence": "medium",
            "reason": "documentation, compliance, or go-to-market subtree",
        }
    if normalized in {"migration", "scripts"}:
        return {
            "owner_area": "data_migration",
            "confidence": "medium",
            "reason": "migration or ETL script subtree",
        }
    if normalized in {"sdk", "sdk_sketch"}:
        return {
            "owner_area": "sdk",
            "confidence": "medium",
            "reason": "SDK staging subtree",
        }
    if normalized in {".", "_salvage_from_tmp"}:
        return {
            "owner_area": "mixed_or_unknown",
            "confidence": "low",
            "reason": "root-level or salvage staging content needs manual owner split",
        }
    return {
        "owner_area": "mixed_or_unknown",
        "confidence": "low",
        "reason": "no local ownership rule matched this top-level directory",
    }


def _top_level_for(root: Path, file_path: Path) -> str:
    rel = file_path.relative_to(root)
    if len(rel.parts) <= 1:
        return "."
    return rel.parts[0]


def _raw_tree_counts(root: Path, repo_root: Path) -> dict[str, Any]:
    file_count = 0
    dir_count = 0
    symlink_count = 0
    total_bytes = 0
    protected_count = 0
    top_level_counts: dict[str, Counter[str]] = {}
    for current, dirs, files in os.walk(root):
        current_path = Path(current)
        kept_dirs = []
        for dirname in sorted(dirs):
            dir_path = current_path / dirname
            if dirname in RAW_SKIP_DIR_NAMES:
                continue
            if _is_protected_path(dir_path, repo_root):
                protected_count += 1
                continue
            kept_dirs.append(dirname)
        dirs[:] = kept_dirs
        dir_count += len(kept_dirs)
        for filename in files:
            path = current_path / filename
            if _is_protected_path(path, repo_root):
                protected_count += 1
                continue
            if path.is_symlink():
                symlink_count += 1
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            file_count += 1
            total_bytes += stat.st_size
            top_level = _top_level_for(root, path)
            if top_level not in top_level_counts:
                top_level_counts[top_level] = Counter()
            top_level_counts[top_level]["files"] += 1
            top_level_counts[top_level]["bytes"] += stat.st_size
    return {
        "file_count": file_count,
        "dir_count": dir_count,
        "symlink_count": symlink_count,
        "total_bytes": total_bytes,
        "protected_path_count": protected_count,
        "top_level": {
            top_level: {"files": int(counts["files"]), "bytes": int(counts["bytes"])}
            for top_level, counts in top_level_counts.items()
        },
    }


def summarize_staging_root(root: Path, repo_root: Path) -> dict[str, Any]:
    raw_counts = _raw_tree_counts(root, repo_root)
    file_summaries: list[FileSummary] = []
    inventory_dir_count = 0
    inventory_symlink_count = 0
    skipped_protected_count = 0
    read_error_count = 0
    read_errors: list[dict[str, str]] = []

    top_level_counts: dict[str, Counter[str]] = {}
    extension_counts: Counter[str] = Counter()
    extension_bytes: Counter[str] = Counter()

    for current, dirs, files in os.walk(root):
        current_path = Path(current)
        dirs[:] = sorted(
            d
            for d in dirs
            if d not in SKIP_DIR_NAMES and not _is_protected_path(current_path / d, repo_root)
        )
        inventory_dir_count += len(dirs)
        for filename in sorted(files):
            path = current_path / filename
            if _is_protected_path(path, repo_root):
                skipped_protected_count += 1
                continue
            if path.is_symlink():
                inventory_symlink_count += 1
                continue
            try:
                summary = _summarize_file(path, repo_root)
            except OSError as exc:
                read_error_count += 1
                if len(read_errors) < 20:
                    read_errors.append({"path": _rel(path, repo_root), "error": str(exc)})
                continue
            file_summaries.append(summary)
            top_level = _top_level_for(root, path)
            if top_level not in top_level_counts:
                top_level_counts[top_level] = Counter()
            top_level_counts[top_level]["files"] += 1
            top_level_counts[top_level]["bytes"] += summary.bytes
            top_level_counts[top_level]["loc"] += summary.loc
            if summary.text:
                top_level_counts[top_level]["text_files"] += 1
            else:
                top_level_counts[top_level]["binary_files"] += 1
            extension = "".join(path.suffixes[-2:]).lower()
            if extension not in BINARY_EXTENSIONS:
                extension = path.suffix.lower() or "[no_extension]"
            extension_counts[extension] += 1
            extension_bytes[extension] += summary.bytes

    total_files = len(file_summaries)
    inventory_bytes = sum(summary.bytes for summary in file_summaries)
    total_loc = sum(summary.loc for summary in file_summaries)
    text_files = sum(1 for summary in file_summaries if summary.text)
    binary_files = total_files - text_files
    large_files = sorted(file_summaries, key=lambda item: item.bytes, reverse=True)[:20]
    db_like_files = [
        summary
        for summary in file_summaries
        if any(summary.path.lower().endswith(ext) for ext in (".db", ".sqlite", ".sqlite3"))
    ]

    ownership = []
    for top_level, counts in sorted(top_level_counts.items()):
        raw_top_level = raw_counts["top_level"].get(top_level, {"files": 0, "bytes": 0})
        ownership.append(
            {
                "top_level": top_level,
                "raw_files": int(raw_top_level["files"]),
                "raw_bytes": int(raw_top_level["bytes"]),
                "files": int(counts["files"]),
                "text_files": int(counts["text_files"]),
                "binary_files": int(counts["binary_files"]),
                "loc": int(counts["loc"]),
                "bytes": int(counts["bytes"]),
                "excluded_dependency_or_cache_files": max(
                    int(raw_top_level["files"]) - int(counts["files"]),
                    0,
                ),
                **_owner_area(top_level),
            }
        )

    return {
        "path": _rel(root, repo_root),
        "exists": root.exists(),
        "file_count": raw_counts["file_count"],
        "dir_count": raw_counts["dir_count"],
        "symlink_count": raw_counts["symlink_count"],
        "inventory_file_count": total_files,
        "inventory_dir_count": inventory_dir_count,
        "inventory_symlink_count": inventory_symlink_count,
        "excluded_dependency_or_cache_file_count": max(raw_counts["file_count"] - total_files, 0),
        "excluded_dependency_or_cache_dir_count": max(raw_counts["dir_count"] - inventory_dir_count, 0),
        "skipped_protected_path_count": skipped_protected_count,
        "raw_protected_path_count": raw_counts["protected_path_count"],
        "read_error_count": read_error_count,
        "read_errors_sample": read_errors,
        "total_bytes": raw_counts["total_bytes"],
        "inventory_bytes": inventory_bytes,
        "text_file_count": text_files,
        "binary_file_count": binary_files,
        "loc": total_loc,
        "top_extensions": [
            {
                "extension": extension,
                "files": count,
                "bytes": int(extension_bytes[extension]),
            }
            for extension, count in extension_counts.most_common(20)
        ],
        "largest_files": [
            {
                "path": summary.path,
                "bytes": summary.bytes,
                "text": summary.text,
                "binary_reason": summary.binary_reason,
            }
            for summary in large_files
        ],
        "large_file_count": sum(1 for summary in file_summaries if summary.bytes >= LARGE_FILE_BYTES),
        "db_like_file_count": len(db_like_files),
        "db_like_files_sample": [asdict(summary) for summary in db_like_files[:20]],
        "ownership_estimate": ownership,
    }


def _dry_run_commands(staging_roots: list[Path], repo_root: Path) -> list[str]:
    commands: list[str] = []
    for root in staging_roots:
        rel = _rel(root, repo_root)
        quoted_rel = shlex.quote(rel)
        target = shlex.quote(f"../jpcite-staging-extract/{rel}/")
        commands.append(f"rsync -a --dry-run --itemize-changes {quoted_rel}/ {target}")
    return commands


def _read_only_verification_commands(staging_roots: list[Path], repo_root: Path) -> list[str]:
    rels = " ".join(shlex.quote(_rel(root, repo_root)) for root in staging_roots)
    if not rels:
        rels = "autonomath_staging"
    return [
        f"git status --short --ignored=matching -- {rels}",
        f"git ls-files --others --ignored --exclude-standard -- {rels}",
        (
            "python scripts/etl/report_repo_staging_separation.py --repo-root . "
            "--output analysis_wave18/staging_separation_plan_2026-05-01.json "
            "--markdown-output analysis_wave18/staging_separation_plan_2026-05-01.md"
        ),
    ]


def _safe_extraction_steps() -> list[dict[str, Any]]:
    return [
        {
            "step": 1,
            "title": "Freeze and confirm ownership",
            "action": "Assign an owner for each top-level staging subtree and freeze concurrent writes.",
            "requires_owner_confirmation": True,
        },
        {
            "step": 2,
            "title": "Review read-only inventory",
            "action": "Compare file, LOC, binary artifact, and git ignored/tracked counts in this report.",
            "requires_owner_confirmation": False,
        },
        {
            "step": 3,
            "title": "Run extraction dry-run only",
            "action": "Use the dry-run command strings in this report to preview copy scope without moving or deleting files.",
            "requires_owner_confirmation": True,
        },
        {
            "step": 4,
            "title": "Resolve blockers before real extraction",
            "action": "Remove or re-home DB/runtime artifacts by owner decision, then document destination repo/package boundaries.",
            "requires_owner_confirmation": True,
        },
        {
            "step": 5,
            "title": "Defer real moves",
            "action": "Real moves/deletes are out of scope for G5 readiness and must happen in a separate owner-approved change.",
            "requires_owner_confirmation": True,
        },
    ]


def _blocker(code: str, message: str, *, severity: str = "blocker") -> dict[str, str]:
    return {"code": code, "severity": severity, "message": message}


def _build_blockers(
    staging_roots: list[dict[str, Any]],
    git: dict[str, Any],
) -> list[dict[str, str]]:
    blockers = [
        _blocker(
            "owner_confirmation_required",
            "G5 readiness requires explicit owner confirmation before any real extraction.",
        )
    ]
    if not staging_roots:
        blockers.append(
            _blocker(
                "staging_roots:not_found",
                "No autonomath_staging or staging-like directories were found locally.",
            )
        )
    if git.get("available") and int(git.get("dirty_path_count") or 0) > 0:
        blockers.append(
            _blocker(
                "worktree:dirty",
                "The worktree has concurrent modifications; extraction scope must be reviewed against current owner changes.",
            )
        )
    if git.get("available") and int(git.get("ignored_staging_path_count") or 0) > 0:
        blockers.append(
            _blocker(
                "staging_files:ignored_by_git",
                "Some staging files are git-ignored, so extraction cannot rely on tracked history alone.",
            )
        )
    for root in staging_roots:
        if int(root.get("db_like_file_count") or 0) > 0:
            blockers.append(
                _blocker(
                    f"runtime_artifacts:{root['path']}",
                    f"{root['path']} contains DB-like runtime artifacts that need owner disposition.",
                )
            )
        if int(root.get("large_file_count") or 0) > 0:
            blockers.append(
                _blocker(
                    f"large_files:{root['path']}",
                    f"{root['path']} contains files >= {LARGE_FILE_BYTES} bytes; storage boundary needs review.",
                    severity="warning",
                )
            )
        if int(root.get("read_error_count") or 0) > 0:
            blockers.append(
                _blocker(
                    f"read_errors:{root['path']}",
                    f"{root['path']} had filesystem read errors; inventory is incomplete.",
                )
            )
    return blockers


def build_report(repo_root: Path = REPO_ROOT) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    staging_root_paths = discover_staging_roots(repo_root)
    staging_roots = [summarize_staging_root(root, repo_root) for root in staging_root_paths]
    git = _git_summary(repo_root, staging_root_paths)
    totals = {
        "staging_root_count": len(staging_roots),
        "file_count": sum(int(root["file_count"]) for root in staging_roots),
        "inventory_file_count": sum(int(root["inventory_file_count"]) for root in staging_roots),
        "excluded_dependency_or_cache_file_count": sum(
            int(root["excluded_dependency_or_cache_file_count"]) for root in staging_roots
        ),
        "text_file_count": sum(int(root["text_file_count"]) for root in staging_roots),
        "binary_file_count": sum(int(root["binary_file_count"]) for root in staging_roots),
        "loc": sum(int(root["loc"]) for root in staging_roots),
        "bytes": sum(int(root["total_bytes"]) for root in staging_roots),
        "inventory_bytes": sum(int(root["inventory_bytes"]) for root in staging_roots),
        "db_like_file_count": sum(int(root["db_like_file_count"]) for root in staging_roots),
    }
    blockers = _build_blockers(staging_roots, git)
    return {
        "report_id": REPORT_ID,
        "report_date": REPORT_DATE,
        "generated_at": _utc_now(),
        "repo_root": str(repo_root),
        "read_mode": {
            "filesystem_read_only": True,
            "git_status_only": True,
            "network_access_performed": False,
            "llm_api_calls_performed": False,
            "moves_performed": False,
            "deletes_performed": False,
            "commands_are_strings_only": True,
        },
        "completion_status": {
            "G5": "readiness_only",
            "complete": False,
            "reason": "No staging extraction moves/deletes were performed.",
        },
        "requires_owner_confirmation": True,
        "ready_for_extraction": False,
        "totals": totals,
        "git": git,
        "staging_roots": staging_roots,
        "safe_extraction_steps": _safe_extraction_steps(),
        "dry_run_commands": _dry_run_commands(staging_root_paths, repo_root),
        "read_only_verification_commands": _read_only_verification_commands(
            staging_root_paths,
            repo_root,
        ),
        "blockers": blockers,
        "report_counts": {
            "staging_root_count": len(staging_roots),
            "blocker_count": len(blockers),
            "dry_run_command_count": len(staging_root_paths),
        },
        "ok": not any(blocker["severity"] == "blocker" for blocker in blockers),
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# G5 Staging Separation Readiness",
        "",
        f"- Generated: {report['generated_at']}",
        f"- G5 complete: {report['completion_status']['complete']} ({report['completion_status']['G5']})",
        f"- Requires owner confirmation: {report['requires_owner_confirmation']}",
        f"- Ready for extraction: {report['ready_for_extraction']}",
        "",
        "## Counts",
        "",
        f"- Staging roots: {report['totals']['staging_root_count']}",
        f"- Files: {report['totals']['file_count']}",
        f"- Inventory files counted for LOC: {report['totals']['inventory_file_count']}",
        (
            "- Excluded dependency/cache files: "
            f"{report['totals']['excluded_dependency_or_cache_file_count']}"
        ),
        f"- Text files: {report['totals']['text_file_count']}",
        f"- Binary files: {report['totals']['binary_file_count']}",
        f"- Text LOC: {report['totals']['loc']}",
        f"- Bytes: {report['totals']['bytes']}",
        f"- Inventory bytes counted for LOC: {report['totals']['inventory_bytes']}",
        f"- DB-like files: {report['totals']['db_like_file_count']}",
        "",
        "## Staging Roots",
        "",
    ]
    for root in report["staging_roots"]:
        lines.extend(
            [
                f"### {root['path']}",
                "",
                f"- Files: {root['file_count']}",
                f"- Inventory files counted for LOC: {root['inventory_file_count']}",
                (
                    "- Excluded dependency/cache files: "
                    f"{root['excluded_dependency_or_cache_file_count']}"
                ),
                f"- Text LOC: {root['loc']}",
                f"- Bytes: {root['total_bytes']}",
                f"- Inventory bytes counted for LOC: {root['inventory_bytes']}",
                f"- Binary files: {root['binary_file_count']}",
                f"- DB-like files: {root['db_like_file_count']}",
                "",
                (
                    "| Top level | Owner area | Confidence | Raw files | Inventory files | "
                    "Excluded deps/cache | LOC | Raw bytes |"
                ),
                "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |",
            ]
        )
        for owner in root["ownership_estimate"]:
            lines.append(
                (
                    "| {top_level} | {owner_area} | {confidence} | {raw_files} | {files} | "
                    "{excluded_dependency_or_cache_files} | {loc} | {raw_bytes} |"
                ).format(
                    **owner
                )
            )
        lines.append("")
    lines.extend(["## Dry-Run Commands", ""])
    for command in report["dry_run_commands"]:
        lines.append(f"- `{command}`")
    lines.extend(["", "## Blockers", ""])
    for blocker in report["blockers"]:
        lines.append(f"- `{blocker['code']}` ({blocker['severity']}): {blocker['message']}")
    lines.append("")
    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--markdown-output", type=Path, default=None)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_report(repo_root=args.repo_root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    markdown_output = args.markdown_output
    if markdown_output is not None:
        markdown_output.parent.mkdir(parents=True, exist_ok=True)
        markdown_output.write_text(render_markdown(report), encoding="utf-8")
    print(
        json.dumps(
            {
                "output": str(args.output),
                "markdown_output": str(markdown_output) if markdown_output else None,
                "staging_root_count": report["totals"]["staging_root_count"],
                "file_count": report["totals"]["file_count"],
                "loc": report["totals"]["loc"],
                "requires_owner_confirmation": report["requires_owner_confirmation"],
                "g5_complete": report["completion_status"]["complete"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
