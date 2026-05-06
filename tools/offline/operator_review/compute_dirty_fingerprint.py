#!/usr/bin/env python3
"""
compute_dirty_fingerprint.py

DEEP-56 dirty tree fingerprint generator for jpcite v0.3.4 production deploy.

Generates the 7-field `dirty_tree_fingerprint` object required by the
operator ACK YAML when `--allow-dirty` is passed to
`production_deploy_go_gate.py`.

7 fields emitted (all required by gate):
  1. current_head                      (str, sha1 git commit)
  2. dirty_entries                     (int)
  3. status_counts                     (dict[str,int])
  4. lane_counts                       (dict[str,int], 7 lanes)
  5. path_sha256                       (str)
  6. content_sha256                    (str)
  7. content_hash_skipped_large_files  (list[str])

Constraints:
  - LLM API call count: 0 (no third-party AI SDK imports of any kind)
  - paid API call count: 0 (pure git + hashlib)
  - net call count: 0 (only subprocess git)
  - stdlib + PyYAML only

Usage:
    python compute_dirty_fingerprint.py [--repo PATH] [--format json|yaml]
                                        [--out FILE] [--skip-large BYTES]
                                        [--workers N]

Spec: tools/offline/_inbox/value_growth_dual/_deep_plan/
        DEEP_56_dirty_tree_fingerprint_generator.md
"""

from __future__ import annotations

import argparse
import asyncio
import concurrent.futures
import hashlib
import json
import subprocess
import sys
from collections import Counter
from collections.abc import Iterable
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants & configuration
# ---------------------------------------------------------------------------

DEFAULT_SKIP_LARGE_BYTES = 10 * 1024 * 1024  # 10 MB
DEFAULT_WORKERS = 8
CHUNK_SIZE = 64 * 1024  # 64 KB per read

# Lane mapping rules (path-prefix match).
# IMPORTANT: order matters — billing_auth_security must run BEFORE runtime_code
# because billing/auth/middleware paths are subset of src/jpintel_mcp/.
LANE_RULES: list[tuple[str, list[str]]] = [
    (
        "billing_auth_security",
        [
            "src/jpintel_mcp/billing/",
            "src/jpintel_mcp/api/auth/",
            "src/jpintel_mcp/middleware/",
        ],
    ),
    (
        "runtime_code",
        [
            "src/jpintel_mcp/api/",
            "src/jpintel_mcp/mcp/",
            "src/jpintel_mcp/tools/",
            "src/jpintel_mcp/ingest/",
            "src/jpintel_mcp/",  # catch-all under src/jpintel_mcp/
        ],
    ),
    ("migrations", ["scripts/migrations/"]),
    ("cron_etl_ops", ["scripts/cron/", "scripts/etl/"]),
    ("workflows", [".github/workflows/"]),
    (
        "root_release_files",
        [
            "pyproject.toml",
            "server.json",
            "smithery.yaml",
            "dxt/manifest.json",
            "mcp-server.json",
            "CHANGELOG.md",
            "uv.lock",
        ],
    ),
]

# All 7 lanes that must appear in lane_counts (other = fallback).
LANE_NAMES: list[str] = [name for name, _ in LANE_RULES] + ["other"]


# ---------------------------------------------------------------------------
# git helpers
# ---------------------------------------------------------------------------


def git_rev_parse_head(repo: Path) -> str:
    """Return current HEAD commit sha1 (full 40 char)."""
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(repo),
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def git_status_porcelain_z(repo: Path) -> list[tuple[str, str]]:
    """
    Run `git status --porcelain=v1 -z` and parse NUL-separated output.

    Returns list of (status_code, path) tuples.
    Status codes follow porcelain v1: 'M', 'D', 'A', 'R', 'C', 'U', '??'.
    For renames (R) the second path (origin) is consumed and discarded.
    """
    result = subprocess.run(
        ["git", "status", "--porcelain=v1", "-z"],
        cwd=str(repo),
        capture_output=True,
        check=True,
    )
    raw = result.stdout
    if not raw:
        return []

    entries: list[tuple[str, str]] = []
    # Split by NUL, drop trailing empty
    parts = raw.split(b"\x00")
    if parts and parts[-1] == b"":
        parts = parts[:-1]

    i = 0
    while i < len(parts):
        chunk = parts[i]
        if len(chunk) < 3:
            i += 1
            continue
        # First two bytes = XY status, then space, then path
        xy = chunk[:2].decode("ascii", errors="replace")
        path = chunk[3:].decode("utf-8", errors="replace")

        # Normalise status to a single canonical code for status_counts
        code = canonicalise_status(xy)
        entries.append((code, path))

        # Renames / copies (R / C) carry an additional path entry which we skip
        if xy[0] in ("R", "C") or xy[1] in ("R", "C"):
            i += 2
        else:
            i += 1

    return entries


def canonicalise_status(xy: str) -> str:
    """
    Reduce porcelain v1 XY two-char status to a single canonical code used in
    status_counts.

    Untracked files are represented as `??` per gate spec.
    Otherwise prefer the worktree (Y) char if non-space, else the index (X).
    """
    if xy == "??":
        return "??"
    if xy == "!!":
        return "!!"  # ignored — surfaced for transparency
    x, y = xy[0], xy[1]
    if y != " ":
        return y
    if x != " ":
        return x
    return "?"


# ---------------------------------------------------------------------------
# Lane classification
# ---------------------------------------------------------------------------


def classify_lane(path: str) -> str:
    """Return lane name for a given dirty path. Falls back to 'other'."""
    for lane_name, prefixes in LANE_RULES:
        for prefix in prefixes:
            if prefix.endswith("/"):
                if path.startswith(prefix):
                    return lane_name
            else:
                # exact-file rule (e.g. pyproject.toml)
                if path == prefix:
                    return lane_name
    return "other"


# ---------------------------------------------------------------------------
# Hashing
# ---------------------------------------------------------------------------


def file_sha256(abs_path: Path, skip_large: int) -> tuple[str | None, bool]:
    """
    Compute sha256 of a file's content, chunked.

    Returns (hexdigest, skipped_flag).
    If file is missing -> (None, False).
    If file size > skip_large -> (None, True).
    """
    try:
        size = abs_path.stat().st_size
    except FileNotFoundError:
        return None, False
    except OSError:
        return None, False

    if size > skip_large:
        return None, True

    h = hashlib.sha256()
    try:
        with abs_path.open("rb") as fh:
            while True:
                chunk = fh.read(CHUNK_SIZE)
                if not chunk:
                    break
                h.update(chunk)
    except FileNotFoundError:
        return None, False
    except OSError:
        return None, False
    return h.hexdigest(), False


def parallel_hash(
    repo: Path,
    paths: list[str],
    statuses: dict[str, str],
    skip_large: int,
    workers: int,
) -> tuple[dict[str, str | None], list[str]]:
    """
    Hash every readable working-tree file in parallel.

    Skipped reasons:
      - size > skip_large -> recorded in skipped_large
      - status 'D' (deleted) -> no working tree content -> skipped silently
      - missing file (untracked + already removed) -> skipped silently

    Returns (path -> hexdigest|None mapping, list of skipped_large paths).
    """
    skipped_large: list[str] = []
    digests: dict[str, str | None] = {}

    def task(path: str) -> tuple[str, str | None, bool]:
        st = statuses.get(path, "")
        # Deleted files have no working tree content
        if st == "D":
            return path, None, False
        abs_path = repo / path
        digest, skipped = file_sha256(abs_path, skip_large)
        return path, digest, skipped

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        for path, digest, skipped in pool.map(task, paths):
            digests[path] = digest
            if skipped:
                skipped_large.append(path)

    return digests, skipped_large


async def parallel_hash_async(
    repo: Path,
    paths: list[str],
    statuses: dict[str, str],
    skip_large: int,
    workers: int,
) -> tuple[dict[str, str | None], list[str]]:
    """asyncio wrapper around parallel_hash for `asyncio.run` compatibility."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None,
        parallel_hash,
        repo,
        paths,
        statuses,
        skip_large,
        workers,
    )


# ---------------------------------------------------------------------------
# Fingerprint assembly
# ---------------------------------------------------------------------------


def compute_fingerprint(
    repo: Path,
    skip_large: int = DEFAULT_SKIP_LARGE_BYTES,
    workers: int = DEFAULT_WORKERS,
) -> dict:
    """Assemble all 7 fields and return as plain dict."""
    head = git_rev_parse_head(repo)
    raw_entries = git_status_porcelain_z(repo)

    # status_counts (deterministic key ordering = sort by code)
    status_counter: Counter[str] = Counter(code for code, _ in raw_entries)
    status_counts = dict(sorted(status_counter.items()))

    # Path list (sorted for path_sha256 + content_sha256 ordering)
    paths_sorted: list[str] = sorted({path for _, path in raw_entries})
    statuses: dict[str, str] = {}
    for code, path in raw_entries:
        # If a path appears twice (rare), the last wins; safe for hashing decisions
        statuses[path] = code

    # path_sha256 = sha256 of '\n'.join(sorted_paths) utf-8
    path_blob = "\n".join(paths_sorted).encode("utf-8")
    path_sha256 = hashlib.sha256(path_blob).hexdigest()

    # lane_counts
    lane_counter: Counter[str] = Counter()
    for path in paths_sorted:
        lane_counter[classify_lane(path)] += 1
    # Ensure all 7 lanes present, even if zero
    lane_counts = {lane: int(lane_counter.get(lane, 0)) for lane in LANE_NAMES}

    # parallel content hashing
    digests, skipped_large = asyncio.run(
        parallel_hash_async(repo, paths_sorted, statuses, skip_large, workers)
    )

    # content_sha256 = sequential merge of per-file digests in sorted-path order.
    # Each file contributes "<path>\0<sha256_or_skip_marker>\n" so paths and
    # contents are both bound into the rollup hash.
    rollup = hashlib.sha256()
    for path in paths_sorted:
        digest = digests.get(path)
        if digest is None:
            marker = "SKIP"  # deleted / missing / large all collapse here for content rollup
        else:
            marker = digest
        rollup.update(path.encode("utf-8"))
        rollup.update(b"\x00")
        rollup.update(marker.encode("ascii"))
        rollup.update(b"\n")
    content_sha256 = rollup.hexdigest()

    fingerprint = {
        "current_head": head,
        "dirty_entries": len(paths_sorted),
        "status_counts": status_counts,
        "lane_counts": lane_counts,
        "path_sha256": path_sha256,
        "content_sha256": content_sha256,
        "content_hash_skipped_large_files": sorted(skipped_large),
    }
    return fingerprint


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------


def dump_json(fp: dict) -> str:
    return json.dumps(fp, ensure_ascii=False, indent=2, sort_keys=False)


def dump_yaml(fp: dict) -> str:
    try:
        import yaml  # type: ignore
    except ImportError as exc:  # pragma: no cover
        raise SystemExit(
            "PyYAML required for --format yaml; install with `pip install pyyaml`"
        ) from exc
    return yaml.safe_dump(fp, sort_keys=False, default_flow_style=False, allow_unicode=True)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="compute_dirty_fingerprint",
        description="DEEP-56 dirty tree fingerprint generator for jpcite",
    )
    p.add_argument(
        "--repo",
        type=Path,
        default=Path.cwd(),
        help="Path to jpcite git repo (default: cwd)",
    )
    p.add_argument(
        "--format",
        choices=("json", "yaml"),
        default="json",
        help="Output format (default: json)",
    )
    p.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Output file (default: stdout)",
    )
    p.add_argument(
        "--skip-large",
        type=int,
        default=DEFAULT_SKIP_LARGE_BYTES,
        help=f"Skip content hash for files larger than this many bytes (default: {DEFAULT_SKIP_LARGE_BYTES})",
    )
    p.add_argument(
        "--workers",
        type=int,
        default=DEFAULT_WORKERS,
        help=f"Parallel hash worker count (default: {DEFAULT_WORKERS})",
    )
    return p.parse_args(list(argv) if argv is not None else None)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    repo = args.repo.resolve()
    if not (repo / ".git").exists():
        print(
            f"error: {repo} is not a git repository (no .git/ found)",
            file=sys.stderr,
        )
        return 2

    fp = compute_fingerprint(
        repo=repo,
        skip_large=args.skip_large,
        workers=args.workers,
    )

    if args.format == "json":
        out = dump_json(fp)
    else:
        out = dump_yaml(fp)

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(out, encoding="utf-8")
    else:
        sys.stdout.write(out)
        if not out.endswith("\n"):
            sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
