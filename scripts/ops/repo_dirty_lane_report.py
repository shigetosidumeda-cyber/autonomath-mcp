#!/usr/bin/env python3
"""Classify git dirty-tree entries into review lanes.

This report is intentionally non-destructive. It does not delete, move, stage,
or rewrite files. Its job is to turn a large mixed dirty tree into reviewable
lanes so release and cleanup work can happen without guessing.
"""

from __future__ import annotations

import argparse
import hashlib
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT = REPO_ROOT / "docs" / "_internal" / "repo_dirty_lanes_latest.md"
JST = timezone(timedelta(hours=9))

# Lanes that the production deploy gate flags as critical when dirty.
# Kept in this module (the canonical lane-classification SOT) so gate and
# operator-side CLIs share a single source.
CRITICAL_DIRTY_LANES = (
    "runtime_code",
    "billing_auth_security",
    "migrations",
    "cron_etl_ops",
    "workflows",
    "root_release_files",
)

# Threshold above which a single working-tree file is excluded from the
# rolling content_sha256 (its path is recorded in
# `content_hash_skipped_large_files` so the operator can see what was elided).
# The gate has historically used 64 MiB; we keep the gate value as the SOT.
LARGE_FILE_CONTENT_HASH_THRESHOLD_BYTES = 64 * 1024 * 1024


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


def collect_status_lines(repo_root: Path) -> list[str]:
    """Return raw `git status --porcelain=v1 --untracked-files=all` lines.

    Single SOT for the porcelain stream both gate and operator-side CLI ingest.
    Strips empty lines but preserves the porcelain XY status prefix and rename
    " -> " arrows so callers can drive identical lane / hash logic.
    """
    out = _run_git(["status", "--porcelain=v1", "--untracked-files=all"], repo_root)
    return [line for line in out.splitlines() if line.strip()]


def head_sha(repo_root: Path) -> str | None:
    """Return current HEAD commit sha (or ``None`` if git is unavailable)."""
    text = _run_git(["rev-parse", "HEAD"], repo_root).strip()
    return text or None


def compute_canonical_dirty_fingerprint(
    repo_root: Path,
    lines: list[str] | None = None,
) -> dict[str, Any]:
    """Canonical 7-field dirty tree fingerprint (SOT for gate + ACK CLI).

    Both ``scripts/ops/production_deploy_go_gate.py`` (consumer) and
    ``tools/offline/operator_review/compute_dirty_fingerprint.py`` (producer)
    must call into this helper so their output binds bit-for-bit. Drift
    between the two stalls the operator at 4/5 PASS and forces re-signing.

    Algorithm (kept identical to the gate's historical implementation):

    1. Source = sorted raw porcelain lines from
       ``git status --porcelain=v1 --untracked-files=all``.
    2. Per line: status = ``raw[:2].strip() or raw[:2]``, path = ``raw[3:].strip()``.
       Renames carry an ``old -> new`` arrow; both old and new contribute one
       lane count each, status_counts is keyed by the raw porcelain XY.
    3. Lane = :func:`classify_path` (16-lane SOT taxonomy).
    4. ``path_sha256`` = sha256 of ``"\\n".join(sorted_raw_lines)`` utf-8.
    5. ``content_sha256`` = streaming sha256 of, for each parsed entry in raw
       order, ``f"{status}\\t{path}\\n" + (per-file size + sha256 hex)``. Files
       above :data:`LARGE_FILE_CONTENT_HASH_THRESHOLD_BYTES` collapse to a
       ``<content-skipped-large-file>`` marker and are added to
       ``content_hash_skipped_large_files``. Deleted / unreadable files emit
       a ``<deleted-or-not-file>`` / ``<read-unavailable>`` marker.

    The returned dict carries ``critical_lanes_present`` for the gate's
    review gating; the ACK CLI ignores that field.
    """
    if lines is None:
        lines = collect_status_lines(repo_root)

    lane_counts: dict[str, int] = {}
    status_counts: dict[str, int] = {}
    content_hash = hashlib.sha256()
    content_hash_skipped_large_files: list[str] = []
    parsed_entries: list[tuple[str, str, str | None, str]] = []

    for raw in sorted(lines):
        status = raw[:2].strip() or raw[:2]
        path = raw[3:].strip()
        old_path: str | None = None
        if " -> " in path:
            old_path, path = path.split(" -> ", 1)
            old_lane = classify_path(old_path)
            lane_counts[old_lane] = lane_counts.get(old_lane, 0) + 1
        lane = classify_path(path)
        lane_counts[lane] = lane_counts.get(lane, 0) + 1
        status_counts[status] = status_counts.get(status, 0) + 1
        parsed_entries.append((status, path, old_path, raw))

    for status, path, _old_path, raw in parsed_entries:
        content_hash.update(f"{status}\t{path}\n".encode("utf-8", errors="replace"))
        disk_path = repo_root / path
        if "D" in raw[:2] or not disk_path.is_file():
            content_hash.update(b"<deleted-or-not-file>\n")
            continue
        try:
            size = disk_path.stat().st_size
        except OSError:
            content_hash.update(b"<stat-unavailable>\n")
            continue
        content_hash.update(f"size={size}\n".encode("ascii"))
        if size > LARGE_FILE_CONTENT_HASH_THRESHOLD_BYTES:
            content_hash_skipped_large_files.append(path)
            content_hash.update(b"<content-skipped-large-file>\n")
            continue
        file_hash = hashlib.sha256()
        try:
            with disk_path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    file_hash.update(chunk)
        except OSError:
            content_hash.update(b"<read-unavailable>\n")
            continue
        content_hash.update(file_hash.hexdigest().encode("ascii"))
        content_hash.update(b"\n")

    critical_lanes_present = sorted(
        lane for lane in CRITICAL_DIRTY_LANES if lane_counts.get(lane, 0) > 0
    )

    return {
        "current_head": head_sha(repo_root),
        "dirty_entries": len(lines),
        "status_counts": dict(sorted(status_counts.items())),
        "lane_counts": dict(sorted(lane_counts.items())),
        "critical_lanes_present": critical_lanes_present,
        "path_sha256": hashlib.sha256("\n".join(sorted(lines)).encode("utf-8")).hexdigest(),
        "content_sha256": content_hash.hexdigest(),
        "content_hash_skipped_large_files": content_hash_skipped_large_files,
    }


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
