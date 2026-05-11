#!/usr/bin/env python3
"""Wave 20 standalone .md chunk push.

Pushes site/laws/*.md or site/enforcement/*.md in tiny chunks
(default 100 files / ~4MB per chunk) to dodge the HTTP 408 timeout
that 1,100-file 45 MB packs were hitting against GitHub HTTPS.

Strategy:
- Each chunk = 1 commit + 1 push (with 3-retry exponential backoff)
- First push uses --set-upstream
- 5s sleep between chunk pushes (rate limit dodge)
- HTTP/1.1 fallback on retry 2+ (HTTP/2 stream reset dodge)

Usage:
    python3 scripts/ops/wave20_md_chunk_push.py \
        --paths "site/laws/*.md" \
        --chunk-size 100 \
        --branch feat/jpcite_2026_05_11_wave20_laws_md_bulk

    python3 scripts/ops/wave20_md_chunk_push.py \
        --paths "site/enforcement/*.md" \
        --chunk-size 100 \
        --branch feat/jpcite_2026_05_11_wave20_enforcement_md_bulk
"""
from __future__ import annotations

import argparse
import glob
import os
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def run_git(args: list[str], *, check: bool = True, capture: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        check=check,
        text=True,
        capture_output=capture,
    )


def ensure_branch(branch: str) -> None:
    cur = run_git(["rev-parse", "--abbrev-ref", "HEAD"], check=False)
    cur_name = (cur.stdout or "").strip()
    if cur_name == branch:
        return
    exists = run_git(["rev-parse", "--verify", branch], check=False)
    if exists.returncode == 0:
        run_git(["checkout", branch])
    else:
        run_git(["checkout", "-b", branch])


def push_with_retry(*, set_upstream: bool, branch: str, attempts: int = 3, backoff_base: float = 5.0) -> bool:
    last_err = ""
    for attempt in range(1, attempts + 1):
        env = os.environ.copy()
        if attempt >= 2:
            env["GIT_HTTP_VERSION"] = "HTTP/1.1"
        cmd = ["git", "push"]
        if set_upstream:
            cmd.extend(["--set-upstream", "origin", branch])
        proc = subprocess.run(
            cmd, cwd=REPO_ROOT, text=True, capture_output=True, env=env,
        )
        if proc.returncode == 0:
            return True
        last_err = (proc.stdout or "") + (proc.stderr or "")
        sys.stderr.write(f"  push attempt {attempt}/{attempts} failed: {last_err[-300:]}\n")
        if attempt < attempts:
            wait = backoff_base * (2 ** (attempt - 1))
            sys.stderr.write(f"  sleeping {wait:.0f}s before retry\n")
            time.sleep(wait)
    raise RuntimeError(f"git push failed after {attempts} attempts: {last_err[-300:]}")


def resolve_glob(paths_glob: str) -> list[str]:
    if Path(paths_glob).is_absolute():
        matched = sorted(glob.glob(paths_glob, recursive=True))
    else:
        matched = sorted(glob.glob(str(REPO_ROOT / paths_glob), recursive=True))
    rels: list[str] = []
    for p in matched:
        ap = Path(p)
        if not ap.is_file():
            continue
        try:
            rels.append(str(ap.relative_to(REPO_ROOT)))
        except ValueError:
            continue
    return rels


def filter_actionable(rels: list[str]) -> list[str]:
    """Filter to untracked/modified paths via batched git status --porcelain."""
    actionable: list[str] = []
    seen: set[str] = set()
    for ix in range(0, len(rels), 500):
        batch = rels[ix:ix + 500]
        proc = subprocess.run(
            ["git", "status", "--porcelain", "--", *batch],
            cwd=REPO_ROOT, text=True, capture_output=True,
        )
        if proc.returncode != 0:
            sys.stderr.write(f"git status probe failed at batch {ix}: {proc.stderr[:200]}\n")
            continue
        for line in proc.stdout.splitlines():
            if len(line) < 4:
                continue
            path = line[3:].strip()
            if path.startswith('"') and path.endswith('"'):
                path = path[1:-1]
            if path in seen:
                continue
            seen.add(path)
            actionable.append(path)
    rels_set = set(rels)
    return [p for p in actionable if p in rels_set]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--paths", required=True, help="Glob pattern (REPO_ROOT-relative).")
    parser.add_argument("--chunk-size", type=int, default=100, help="Files per chunk.")
    parser.add_argument("--branch", required=True, help="Target branch.")
    parser.add_argument("--sleep-between", type=float, default=5.0, help="Sleep seconds between pushes.")
    parser.add_argument("--start-chunk", type=int, default=0)
    parser.add_argument("--end-chunk", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    rels = resolve_glob(args.paths)
    if not rels:
        sys.stderr.write(f"no files matched glob: {args.paths}\n")
        return 2

    actionable = filter_actionable(rels)
    total = len(actionable)
    if total == 0:
        print(f"wave20: no actionable paths from {args.paths} (all clean)")
        return 0

    chunks = [actionable[i:i + args.chunk_size] for i in range(0, total, args.chunk_size)]
    end = args.end_chunk if args.end_chunk is not None else len(chunks) - 1

    print(
        f"wave20 push: glob={args.paths} files={total} chunk_size={args.chunk_size} "
        f"chunks={len(chunks)} branch={args.branch} range=[{args.start_chunk}, {end}] "
        f"dry_run={args.dry_run}"
    )

    if not args.dry_run:
        ensure_branch(args.branch)

    is_first_push = True
    pushed_ok = 0
    for ix, chunk_paths in enumerate(chunks):
        if ix < args.start_chunk or ix > end:
            continue
        prefix = f"[{ix + 1}/{len(chunks)}]"
        msg = f"feat(wave20): companion .md chunk {ix + 1}/{len(chunks)} ({len(chunk_paths)} files)"
        if args.dry_run:
            print(f"  {prefix} would add {len(chunk_paths)} paths -> '{msg}'")
            continue
        for batch_ix in range(0, len(chunk_paths), 500):
            batch = chunk_paths[batch_ix:batch_ix + 500]
            subprocess.run(["git", "add", "--", *batch], cwd=REPO_ROOT,
                           check=True, text=True, capture_output=True)
        commit_proc = subprocess.run(
            ["git", "commit", "-m", msg],
            cwd=REPO_ROOT, text=True, capture_output=True,
        )
        if commit_proc.returncode != 0:
            out = (commit_proc.stdout + commit_proc.stderr).lower()
            if "nothing to commit" in out or "no changes added" in out:
                print(f"  {prefix} noop")
                continue
            sys.stderr.write(commit_proc.stdout + commit_proc.stderr)
            return 1
        try:
            push_with_retry(set_upstream=is_first_push, branch=args.branch,
                            attempts=3, backoff_base=args.sleep_between)
        except RuntimeError as exc:
            sys.stderr.write(f"  {prefix} PUSH FAILED: {exc}\n")
            return 1
        is_first_push = False
        pushed_ok += 1
        print(f"  {prefix} pushed {len(chunk_paths)} files (ok={pushed_ok})")
        if ix < end:
            time.sleep(args.sleep_between)
    print(f"wave20 done: {pushed_ok} chunks pushed to {args.branch}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
