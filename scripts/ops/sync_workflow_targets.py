#!/usr/bin/env python3
"""sync_workflow_targets.py - DEEP-49 release_readiness gate fix.

Synchronises ``RUFF_TARGETS`` / ``PYTEST_TARGETS`` env blocks in
``.github/workflows/test.yml`` and ``.github/workflows/release.yml``
(plus the inline ``ruff check`` step in release.yml) with the actual
git-tracked file set under ``scripts/`` and ``tests/``.

Two modes:

* ``--check`` (default): print the diff between current env blocks and
  the desired list. Exit 0 if synced, exit 1 if any drift detected.
  No file writes. Suitable for the
  ``check-workflow-target-sync.yml`` CI guard described in
  DEEP-49 §4.

* ``--apply``: rewrite test.yml + release.yml in-place so the env
  blocks match the desired list exactly (alphabetical, LF-only,
  trailing-space-free). Idempotent.

Constraints (CLAUDE.md non-negotiables):

* Zero LLM API imports. stdlib + PyYAML (already a transitive dep
  of pre-commit + GitHub Actions tooling) only.
* No paid-plan calls. No network I/O. No subprocess outside
  ``git ls-files``.
* No mutation under ``--check``.

The script is intentionally small (~300 lines) so it can be reviewed
in one sitting and dropped into ``scripts/ops/`` by the codex lane
operator after acceptance. This draft lives in the session A lane
(``tools/offline/_inbox/value_growth_dual/_executable_artifacts_2026_05_07/``)
and does NOT touch ``src/`` or ``scripts/``.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

# --- repo layout ---------------------------------------------------------

# When dropped into ``scripts/ops/`` this resolves to the repo root
# (parents[2] from ``scripts/ops/foo.py``). When run from this draft
# location we expect the operator to pass ``--repo-root`` explicitly,
# so we accept that flag and only fall back to the parents[2] heuristic
# when no override is provided.
DEFAULT_REPO_ROOT = Path(__file__).resolve().parents[2]

TEST_WORKFLOW = Path(".github/workflows/test.yml")
RELEASE_WORKFLOW = Path(".github/workflows/release.yml")

# Glob roots that feed each env list. Kept narrow on purpose:
# release_readiness.py only inspects scripts/ + tests/ paths, and we
# do not want to accidentally drag site/_templates/*.py or src/ into
# the lint surface.
RUFF_GLOB_ROOTS: tuple[Path, ...] = (
    Path("scripts"),
    Path("scripts/etl"),
    Path("scripts/ops"),
)
PYTEST_GLOB_ROOTS: tuple[Path, ...] = (Path("tests"),)

# ``scripts/`` contains many subdirs we do NOT want in the ruff target
# (cron / migrations / etl have separate lanes). The operator-curated
# allow-list mirrors the existing release.yml step. We only ADD new
# scripts already on the list path; we never broaden the surface.
RUFF_ALLOW_PREFIXES: tuple[str, ...] = (
    "scripts/generate_",
    "scripts/regen_",
    "scripts/ops/",
    "scripts/etl/generate_program_rss_feeds.py",
)

# Pytest discovery is broader: any tests/test_*.py is a candidate.
PYTEST_FILENAME_RE = re.compile(r"^test_[A-Za-z0-9_]+\.py$")


# --- env block parsing / writing -----------------------------------------

# YAML folded scalar block, 2-space outer indent + 4-space body indent,
# matching the format release_readiness.py:80 already grep-anchors on.
ENV_BLOCK_RE = re.compile(
    r"^  (?P<name>RUFF_TARGETS|PYTEST_TARGETS): >-\n" r"(?P<body>(?:    .+\n)+)",
    re.MULTILINE,
)

# release.yml inline ruff check step:
#         run: |
#           ruff check \
#             scripts/foo.py \
#             ...
RELEASE_RUFF_LINT_RE = re.compile(
    r"^          ruff check \\\n(?P<body>(?:            .+\n)+)",
    re.MULTILINE,
)


def _git_tracked_paths(repo_root: Path) -> set[str]:
    result = subprocess.run(
        ["git", "-C", str(repo_root), "ls-files", "-z", "--"],
        check=True,
        capture_output=True,
        text=True,
    )
    return {p for p in result.stdout.split("\0") if p}


def _glob_real_paths(repo_root: Path, roots: Iterable[Path], pattern: str) -> set[str]:
    paths: set[str] = set()
    for root in roots:
        abs_root = repo_root / root
        if not abs_root.is_dir():
            continue
        for p in abs_root.glob(pattern):
            if p.is_file():
                paths.add(p.relative_to(repo_root).as_posix())
    return paths


def _desired_ruff_targets(repo_root: Path, tracked: set[str]) -> list[str]:
    candidates = _glob_real_paths(repo_root, RUFF_GLOB_ROOTS, "*.py") | _glob_real_paths(
        repo_root, RUFF_GLOB_ROOTS, "**/*.py"
    )
    selected = sorted(
        path
        for path in candidates
        if path in tracked and any(path.startswith(prefix) for prefix in RUFF_ALLOW_PREFIXES)
    )
    return selected


def _desired_pytest_targets(repo_root: Path, tracked: set[str]) -> list[str]:
    candidates = _glob_real_paths(repo_root, PYTEST_GLOB_ROOTS, "test_*.py")
    selected = sorted(
        path for path in candidates if path in tracked and PYTEST_FILENAME_RE.match(Path(path).name)
    )
    return selected


def _format_env_block(name: str, targets: list[str]) -> str:
    if not targets:
        # Preserve a stable empty block rather than leaving the YAML
        # invalid. release_readiness.py treats an empty list as a
        # parse failure and FAILs the gate, which is the correct
        # behaviour - we surface that explicitly here.
        return f"  {name}: >-\n    \n"
    body = "\n".join(f"    {t}" for t in targets)
    return f"  {name}: >-\n{body}\n"


def _format_release_ruff_lint_block(targets: list[str]) -> str:
    if not targets:
        return "          ruff check \\\n            .\n"
    lines = []
    for i, target in enumerate(targets):
        suffix = " \\" if i < len(targets) - 1 else ""
        lines.append(f"            {target}{suffix}")
    return "          ruff check \\\n" + "\n".join(lines) + "\n"


def _replace_env_block(text: str, name: str, targets: list[str]) -> str:
    new_block = _format_env_block(name, targets)

    def _sub(match: re.Match[str]) -> str:
        if match.group("name") != name:
            return match.group(0)
        return new_block

    return ENV_BLOCK_RE.sub(_sub, text, count=0)


def _replace_release_ruff_lint(text: str, targets: list[str]) -> str:
    new_block = _format_release_ruff_lint_block(targets)
    return RELEASE_RUFF_LINT_RE.sub(new_block, text, count=1)


# --- diff representation -------------------------------------------------


def _current_env_targets(text: str, name: str) -> list[str] | None:
    for match in ENV_BLOCK_RE.finditer(text):
        if match.group("name") == name:
            return [line.strip() for line in match.group("body").splitlines() if line.strip()]
    return None


def _current_release_ruff_lint(text: str) -> list[str] | None:
    match = RELEASE_RUFF_LINT_RE.search(text)
    if not match:
        return None
    targets: list[str] = []
    for line in match.group("body").splitlines():
        stripped = line.strip().removesuffix(" \\")
        if stripped:
            targets.append(stripped)
    return targets


def _diff_lists(label: str, current: list[str] | None, desired: list[str]) -> list[str]:
    if current is None:
        return [f"{label}: NOT FOUND in workflow file (regex did not match)"]
    cur_set, des_set = set(current), set(desired)
    missing = sorted(des_set - cur_set)
    extra = sorted(cur_set - des_set)
    out: list[str] = []
    if missing:
        out.append(f"{label}: +{len(missing)} missing -> {missing}")
    if extra:
        out.append(f"{label}: -{len(extra)} stale -> {extra}")
    return out


# --- top-level orchestration ---------------------------------------------


def run(repo_root: Path, apply: bool) -> int:
    tracked = _git_tracked_paths(repo_root)
    desired_ruff = _desired_ruff_targets(repo_root, tracked)
    desired_pytest = _desired_pytest_targets(repo_root, tracked)

    test_path = repo_root / TEST_WORKFLOW
    release_path = repo_root / RELEASE_WORKFLOW
    if not test_path.exists():
        print(f"[ERROR] {TEST_WORKFLOW} not found", file=sys.stderr)
        return 2
    if not release_path.exists():
        print(f"[ERROR] {RELEASE_WORKFLOW} not found", file=sys.stderr)
        return 2

    test_text = test_path.read_text(encoding="utf-8")
    release_text = release_path.read_text(encoding="utf-8")

    diffs: list[str] = []
    diffs.extend(
        _diff_lists(
            "test.yml RUFF_TARGETS",
            _current_env_targets(test_text, "RUFF_TARGETS"),
            desired_ruff,
        )
    )
    diffs.extend(
        _diff_lists(
            "test.yml PYTEST_TARGETS",
            _current_env_targets(test_text, "PYTEST_TARGETS"),
            desired_pytest,
        )
    )
    diffs.extend(
        _diff_lists(
            "release.yml RUFF_TARGETS",
            _current_env_targets(release_text, "RUFF_TARGETS"),
            desired_ruff,
        )
    )
    diffs.extend(
        _diff_lists(
            "release.yml PYTEST_TARGETS",
            _current_env_targets(release_text, "PYTEST_TARGETS"),
            desired_pytest,
        )
    )
    diffs.extend(
        _diff_lists(
            "release.yml Ruff lint step",
            _current_release_ruff_lint(release_text),
            desired_ruff,
        )
    )

    if not diffs:
        print(
            f"[OK] workflow targets in sync (ruff={len(desired_ruff)} pytest={len(desired_pytest)})"
        )
        return 0

    for line in diffs:
        print(line)
    print(f"[DRIFT] ruff_desired={len(desired_ruff)} pytest_desired={len(desired_pytest)}")

    if not apply:
        return 1

    new_test = _replace_env_block(test_text, "RUFF_TARGETS", desired_ruff)
    new_test = _replace_env_block(new_test, "PYTEST_TARGETS", desired_pytest)

    new_release = _replace_env_block(release_text, "RUFF_TARGETS", desired_ruff)
    new_release = _replace_env_block(new_release, "PYTEST_TARGETS", desired_pytest)
    new_release = _replace_release_ruff_lint(new_release, desired_ruff)

    if new_test != test_text:
        test_path.write_text(new_test, encoding="utf-8")
        print(f"[APPLY] wrote {TEST_WORKFLOW}")
    if new_release != release_text:
        release_path.write_text(new_release, encoding="utf-8")
        print(f"[APPLY] wrote {RELEASE_WORKFLOW}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--check",
        action="store_true",
        help="report drift only, exit 1 if env blocks differ from desired",
    )
    mode.add_argument(
        "--apply",
        action="store_true",
        help="rewrite env blocks in test.yml + release.yml in-place",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=DEFAULT_REPO_ROOT,
        help="repository root (default: parents[2] from this script path)",
    )
    args = parser.parse_args(argv)
    if not args.check and not args.apply:
        args.check = True
    return run(args.repo_root.resolve(), apply=args.apply)


if __name__ == "__main__":
    raise SystemExit(main())
