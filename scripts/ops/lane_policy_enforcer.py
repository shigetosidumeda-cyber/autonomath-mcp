#!/usr/bin/env python3
"""DEEP-60 lane policy enforcer for jpcite dual-CLI workflow.

Enforces lane discipline between session A (audit/inbox) and codex (code-side).
Reads lane_policy.json, inspects staged git diff, blocks violations, writes
AGENT_LEDGER.csv audit row. LLM API calls = 0. stdlib + subprocess + git only.

Usage:
    python lane_policy_enforcer.py --check --lane session_a
    python lane_policy_enforcer.py --check --lane codex
    python lane_policy_enforcer.py --report --lane session_a
    python lane_policy_enforcer.py --check --lane session_a \
        --bypass-with-reason "operator override: doc cross-reference fix" \
        --operator-signoff umeda

Exit codes:
    0 = no violations (or override accepted)
    1 = violations detected, commit must be rejected
    2 = configuration / IO error (policy missing, git unavailable)

DEEP-60 spec: dual-CLI lane policy enforcer (sketch -> draft).
"""
from __future__ import annotations

import argparse
import csv
import datetime as _dt
import json
import os
import pathlib
import subprocess
import sys
import uuid
from typing import Iterable

POLICY_FILENAME = "lane_policy.json"
LEDGER_REL_DEFAULT = "tools/offline/_inbox/value_growth_dual/AGENT_LEDGER.csv"
LEDGER_HEADER = [
    "agent_run_id",
    "timestamp_utc",
    "session",
    "lane",
    "write_paths",
    "violation_count",
    "override_reason",
    "operator_signoff",
]
MIN_REASON_CHARS = 24


def _utc_now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _run_git(args: list[str], cwd: pathlib.Path) -> str:
    """Run git, return stdout. Raises RuntimeError on non-zero."""
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as e:
        raise RuntimeError(f"git not found on PATH: {e}") from e
    except subprocess.CalledProcessError as e:
        raise RuntimeError(
            f"git {' '.join(args)} failed (rc={e.returncode}): {e.stderr.strip()}"
        ) from e
    return result.stdout


def find_repo_root(start: pathlib.Path) -> pathlib.Path:
    """Walk up to find a directory containing .git."""
    cur = start.resolve()
    for _ in range(64):
        if (cur / ".git").exists():
            return cur
        if cur.parent == cur:
            break
        cur = cur.parent
    raise RuntimeError(f"no .git ancestor found above {start}")


def load_policy(policy_path: pathlib.Path) -> dict:
    if not policy_path.is_file():
        raise RuntimeError(f"policy file missing: {policy_path}")
    with policy_path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    if "lanes" not in data:
        raise RuntimeError("policy malformed: 'lanes' key missing")
    return data


def staged_paths(repo_root: pathlib.Path) -> list[str]:
    """Return list of staged paths (added/modified/renamed)."""
    raw = _run_git(["diff", "--name-only", "--cached"], repo_root)
    return [line.strip() for line in raw.splitlines() if line.strip()]


def working_paths(repo_root: pathlib.Path) -> list[str]:
    """Return all changed paths vs HEAD (staged + unstaged) for --report."""
    raw = _run_git(["diff", "--name-only", "HEAD"], repo_root)
    return [line.strip() for line in raw.splitlines() if line.strip()]


def _path_matches(path: str, prefix: str) -> bool:
    """Path-prefix match. Treats trailing '/' as directory; bare files match exact."""
    if prefix.endswith("/"):
        return path.startswith(prefix) or path == prefix.rstrip("/")
    return path == prefix or path.startswith(prefix + "/")


def classify(path: str, lane_cfg: dict, shared: Iterable[str]) -> str:
    """Return 'shared' | 'allowed' | 'forbidden' | 'unknown'."""
    for s in shared:
        if _path_matches(path, s):
            return "shared"
    for f in lane_cfg.get("forbidden_paths", []):
        if _path_matches(path, f):
            return "forbidden"
    for a in lane_cfg.get("allowed_paths", []):
        if _path_matches(path, a):
            return "allowed"
    return "unknown"


def detect_violations(
    paths: list[str], lane: str, policy: dict
) -> tuple[list[tuple[str, str]], list[str]]:
    """Return (violations, allowed_writes). violations = [(path, reason), ...]."""
    if lane not in policy["lanes"]:
        raise RuntimeError(f"unknown lane: {lane}")
    lane_cfg = policy["lanes"][lane]
    shared = policy.get("shared_paths", {}).get("paths", [])
    violations: list[tuple[str, str]] = []
    allowed: list[str] = []
    for p in paths:
        kind = classify(p, lane_cfg, shared)
        if kind == "forbidden":
            violations.append((p, f"forbidden path for lane '{lane}'"))
        elif kind == "unknown":
            violations.append(
                (p, f"path not declared allowed for lane '{lane}' (unknown)")
            )
        else:
            allowed.append(p)
    return violations, allowed


def append_ledger_row(
    ledger_path: pathlib.Path,
    *,
    session: str,
    lane: str,
    write_paths: list[str],
    violation_count: int,
    override_reason: str,
    operator_signoff: str,
) -> str:
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    is_new = not ledger_path.exists()
    run_id = uuid.uuid4().hex[:16]
    row = [
        run_id,
        _utc_now_iso(),
        session,
        lane,
        ";".join(write_paths),
        str(violation_count),
        override_reason,
        operator_signoff,
    ]
    with ledger_path.open("a", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        if is_new:
            writer.writerow(LEDGER_HEADER)
        writer.writerow(row)
    return run_id


def _print_violations(violations: list[tuple[str, str]], lane: str) -> None:
    print(f"[lane-enforcer] FAIL: {len(violations)} violation(s) for lane '{lane}'", file=sys.stderr)
    for p, reason in violations:
        print(f"  - {p}: {reason}", file=sys.stderr)
    print(
        "[lane-enforcer] hint: pass --bypass-with-reason "
        "\"...\" --operator-signoff <name> to override (recorded in AGENT_LEDGER.csv).",
        file=sys.stderr,
    )


def cmd_check(args: argparse.Namespace) -> int:
    policy_dir = pathlib.Path(args.policy).resolve().parent
    policy = load_policy(pathlib.Path(args.policy).resolve())
    repo_root = find_repo_root(policy_dir)
    paths = staged_paths(repo_root)
    if not paths:
        print("[lane-enforcer] no staged paths; nothing to check.")
        return 0
    violations, allowed = detect_violations(paths, args.lane, policy)
    ledger_rel = policy.get("ledger", {}).get("path_relative_repo_root", LEDGER_REL_DEFAULT)
    ledger_path = repo_root / ledger_rel
    override_reason = args.bypass_with_reason or ""
    operator = args.operator_signoff or ""
    if violations and override_reason:
        if len(override_reason.strip()) < MIN_REASON_CHARS:
            print(
                f"[lane-enforcer] override reason too short "
                f"(min {MIN_REASON_CHARS} chars): {override_reason!r}",
                file=sys.stderr,
            )
            return 1
        if not operator:
            print(
                "[lane-enforcer] --operator-signoff required when bypassing.",
                file=sys.stderr,
            )
            return 1
        run_id = append_ledger_row(
            ledger_path,
            session=args.session,
            lane=args.lane,
            write_paths=paths,
            violation_count=len(violations),
            override_reason=override_reason.strip(),
            operator_signoff=operator,
        )
        print(
            f"[lane-enforcer] OVERRIDE accepted (run_id={run_id}, "
            f"violations={len(violations)}). reason logged."
        )
        return 0
    if violations:
        _print_violations(violations, args.lane)
        append_ledger_row(
            ledger_path,
            session=args.session,
            lane=args.lane,
            write_paths=paths,
            violation_count=len(violations),
            override_reason="",
            operator_signoff="",
        )
        return 1
    append_ledger_row(
        ledger_path,
        session=args.session,
        lane=args.lane,
        write_paths=allowed,
        violation_count=0,
        override_reason="",
        operator_signoff="",
    )
    print(f"[lane-enforcer] OK: {len(allowed)} path(s) in lane '{args.lane}'.")
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    policy = load_policy(pathlib.Path(args.policy).resolve())
    repo_root = find_repo_root(pathlib.Path(args.policy).resolve().parent)
    paths = working_paths(repo_root)
    violations, allowed = detect_violations(paths, args.lane, policy)
    print(f"[lane-enforcer] report for lane '{args.lane}' "
          f"(repo={repo_root}, total_changed={len(paths)})")
    print(f"  allowed:    {len(allowed)}")
    print(f"  violations: {len(violations)}")
    for p in allowed:
        print(f"  + {p}")
    for p, reason in violations:
        print(f"  X {p}  ({reason})")
    return 0 if not violations else 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="lane_policy_enforcer",
        description="DEEP-60 dual-CLI lane policy enforcer (jpcite).",
    )
    p.add_argument(
        "--policy",
        default=str(pathlib.Path(__file__).resolve().parent / POLICY_FILENAME),
        help="path to lane_policy.json",
    )
    p.add_argument(
        "--lane",
        required=True,
        choices=("session_a", "codex"),
        help="which lane this run belongs to",
    )
    p.add_argument(
        "--session",
        default=os.environ.get("JPCITE_SESSION", "unspecified"),
        help="logical session id (recorded in ledger)",
    )
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="check staged diff")
    mode.add_argument("--report", action="store_true", help="report on working tree")
    p.add_argument(
        "--bypass-with-reason",
        default="",
        help="override violations with explicit reason (recorded in ledger)",
    )
    p.add_argument(
        "--operator-signoff",
        default="",
        help="operator name authorising override",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.check:
            return cmd_check(args)
        if args.report:
            return cmd_report(args)
    except RuntimeError as e:
        print(f"[lane-enforcer] error: {e}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    sys.exit(main())
