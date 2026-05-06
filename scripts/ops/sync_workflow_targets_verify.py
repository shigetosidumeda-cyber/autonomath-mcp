#!/usr/bin/env python3
"""sync_workflow_targets_verify.py - DEEP-57 release readiness CI guard.

Complement to DEEP-49's ``scripts/ops/sync_workflow_targets.py``.

DEEP-49 owns the **rewrite** path (``--apply``); this script owns the
**verify** path with row-per-diff reporting suitable for both the
``check-workflow-target-sync.yml`` PR check and the markdown body of
the monthly cross-repo sync PR opened by
``sync-workflow-targets-monthly.yml``.

Why a second script
-------------------
The DEEP-49 ``--check`` mode prints a flat list of missing/stale paths
which is fine for a pass/fail gate, but loses the per-file → per-block
mapping a reviewer needs to decide "is this drift real or did someone
add a script that should be excluded". This script:

* Parses both ``test.yml`` and ``release.yml`` env blocks.
* Parses the inline ``ruff check`` step in ``release.yml``.
* Cross-correlates each declared target against the git-tracked tree
  rebuilt via ``git ls-files``.
* Emits a row-per-diff table on stdout (``--check``) and a markdown
  blurb on stdout (``--report``) for PR bodies.

Constraints
-----------
* Zero LLM API imports. Stdlib only. (CLAUDE.md non-negotiable.)
* No network I/O. No subprocess outside ``git ls-files``.
* No mutation. ``--apply`` is intentionally NOT exposed here — that is
  DEEP-49's responsibility.
* Exit code: 0 if no drift, 1 if drift detected, 2 on missing inputs.

This file is a session-A draft and lives at::

    tools/offline/_inbox/value_growth_dual/
        _executable_artifacts_2026_05_07/release_readiness_ci/

The codex lane operator will copy it to ``scripts/ops/`` after acceptance.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

# --- repo layout ---------------------------------------------------------

# When this script is dropped into ``scripts/ops/`` the repo root sits at
# ``parents[2]``; when run from the draft inbox path we expect the
# operator to pass ``--repo-root`` explicitly. Same heuristic as
# DEEP-49's sync_workflow_targets.py.
DEFAULT_REPO_ROOT = Path(__file__).resolve().parents[2]

TEST_WORKFLOW = Path(".github/workflows/test.yml")
RELEASE_WORKFLOW = Path(".github/workflows/release.yml")

# Mirrors DEEP-49's tracked surface so the two scripts cannot drift on
# what counts as a "valid" lint/pytest target. Kept in sync by hand for
# now; a future iteration can `import` from sync_workflow_targets.
RUFF_GLOB_ROOTS: tuple[Path, ...] = (
    Path("scripts"),
    Path("scripts/etl"),
    Path("scripts/ops"),
)
PYTEST_GLOB_ROOTS: tuple[Path, ...] = (Path("tests"),)
RUFF_ALLOW_PREFIXES: tuple[str, ...] = (
    "scripts/generate_",
    "scripts/regen_",
    "scripts/ops/",
    "scripts/etl/generate_program_rss_feeds.py",
)
PYTEST_FILENAME_RE = re.compile(r"^test_[A-Za-z0-9_]+\.py$")

# Same regex shapes as DEEP-49 — anchored on the YAML folded scalar
# block format release_readiness.py also greps on.
ENV_BLOCK_RE = re.compile(
    r"^  (?P<name>RUFF_TARGETS|PYTEST_TARGETS): >-\n"
    r"(?P<body>(?:    .+\n)+)",
    re.MULTILINE,
)
RELEASE_RUFF_LINT_RE = re.compile(
    r"^          ruff check \\\n(?P<body>(?:            .+\n)+)",
    re.MULTILINE,
)


# --- data shapes ---------------------------------------------------------


@dataclass(frozen=True)
class DiffRow:
    """One line of drift, ready for table or markdown rendering."""

    workflow: str  # "test.yml" / "release.yml" / "release.yml (inline)"
    block: str  # "RUFF_TARGETS" / "PYTEST_TARGETS" / "ruff check"
    kind: str  # "missing" (in tree, not in env) / "stale" (in env, not in tree)
    path: str

    def as_row(self) -> tuple[str, str, str, str]:
        return (self.workflow, self.block, self.kind, self.path)


# --- helpers -------------------------------------------------------------


def _git_tracked_paths(repo_root: Path) -> set[str]:
    """Return git-tracked paths as POSIX strings."""
    result = subprocess.run(
        ["git", "-C", str(repo_root), "ls-files", "-z", "--"],
        check=True,
        capture_output=True,
        text=True,
    )
    return {p for p in result.stdout.split("\0") if p}


def _glob_real(repo_root: Path, roots: tuple[Path, ...], pattern: str) -> set[str]:
    out: set[str] = set()
    for root in roots:
        abs_root = repo_root / root
        if not abs_root.is_dir():
            continue
        for p in abs_root.glob(pattern):
            if p.is_file():
                out.add(p.relative_to(repo_root).as_posix())
    return out


def _desired_ruff_targets(repo_root: Path, tracked: set[str]) -> list[str]:
    candidates = _glob_real(repo_root, RUFF_GLOB_ROOTS, "*.py") | _glob_real(
        repo_root, RUFF_GLOB_ROOTS, "**/*.py"
    )
    return sorted(
        path
        for path in candidates
        if path in tracked
        and any(path.startswith(prefix) for prefix in RUFF_ALLOW_PREFIXES)
    )


def _desired_pytest_targets(repo_root: Path, tracked: set[str]) -> list[str]:
    candidates = _glob_real(repo_root, PYTEST_GLOB_ROOTS, "test_*.py")
    return sorted(
        path
        for path in candidates
        if path in tracked and PYTEST_FILENAME_RE.match(Path(path).name)
    )


def _parse_env_block(text: str, name: str) -> list[str] | None:
    for match in ENV_BLOCK_RE.finditer(text):
        if match.group("name") == name:
            return [
                line.strip() for line in match.group("body").splitlines() if line.strip()
            ]
    return None


def _parse_release_ruff_lint(text: str) -> list[str] | None:
    match = RELEASE_RUFF_LINT_RE.search(text)
    if not match:
        return None
    out: list[str] = []
    for line in match.group("body").splitlines():
        stripped = line.strip().removesuffix(" \\")
        if stripped:
            out.append(stripped)
    return out


def _diff_block(
    workflow: str, block: str, current: list[str] | None, desired: list[str]
) -> list[DiffRow]:
    if current is None:
        return [DiffRow(workflow, block, "parse_failure", "(regex did not match)")]
    cur_set, des_set = set(current), set(desired)
    rows: list[DiffRow] = []
    for path in sorted(des_set - cur_set):
        rows.append(DiffRow(workflow, block, "missing", path))
    for path in sorted(cur_set - des_set):
        rows.append(DiffRow(workflow, block, "stale", path))
    return rows


def _collect(repo_root: Path) -> list[DiffRow]:
    tracked = _git_tracked_paths(repo_root)
    desired_ruff = _desired_ruff_targets(repo_root, tracked)
    desired_pytest = _desired_pytest_targets(repo_root, tracked)

    test_path = repo_root / TEST_WORKFLOW
    release_path = repo_root / RELEASE_WORKFLOW
    if not test_path.exists() or not release_path.exists():
        # Caller distinguishes this via missing-file exit 2 in main().
        raise FileNotFoundError(
            f"required workflow file missing: "
            f"test={test_path.exists()} release={release_path.exists()}"
        )

    test_text = test_path.read_text(encoding="utf-8")
    release_text = release_path.read_text(encoding="utf-8")

    rows: list[DiffRow] = []
    rows.extend(_diff_block("test.yml", "RUFF_TARGETS",
                            _parse_env_block(test_text, "RUFF_TARGETS"), desired_ruff))
    rows.extend(_diff_block("test.yml", "PYTEST_TARGETS",
                            _parse_env_block(test_text, "PYTEST_TARGETS"), desired_pytest))
    rows.extend(_diff_block("release.yml", "RUFF_TARGETS",
                            _parse_env_block(release_text, "RUFF_TARGETS"), desired_ruff))
    rows.extend(_diff_block("release.yml", "PYTEST_TARGETS",
                            _parse_env_block(release_text, "PYTEST_TARGETS"), desired_pytest))
    rows.extend(_diff_block("release.yml (inline)", "ruff check",
                            _parse_release_ruff_lint(release_text), desired_ruff))
    return rows


# --- renderers -----------------------------------------------------------


def _render_table(rows: list[DiffRow]) -> str:
    if not rows:
        return "[OK] All workflow target lists match git-tracked tree.\n"
    headers = ("workflow", "block", "kind", "path")
    width = [len(h) for h in headers]
    for r in rows:
        for i, val in enumerate(r.as_row()):
            width[i] = max(width[i], len(val))
    fmt = "  ".join(f"{{:<{w}}}" for w in width)
    lines = [fmt.format(*headers), fmt.format(*("-" * w for w in width))]
    for r in rows:
        lines.append(fmt.format(*r.as_row()))
    lines.append("")
    lines.append(f"[FAIL] {len(rows)} drift row(s) detected.")
    return "\n".join(lines) + "\n"


def _render_markdown(rows: list[DiffRow]) -> str:
    if not rows:
        return (
            "## DEEP-57 sync verifier report\n\n"
            "All workflow target lists match the git-tracked tree. "
            "This PR is a no-op (steady state).\n"
        )
    out = [
        "## DEEP-57 sync verifier report",
        "",
        "Drift detected between `.github/workflows/{test,release}.yml` env "
        "blocks and the git-tracked source tree. The monthly cron rewrote "
        "the workflow files; review the diff and merge.",
        "",
        "| workflow | block | kind | path |",
        "|---|---|---|---|",
    ]
    for r in rows:
        out.append(f"| `{r.workflow}` | `{r.block}` | {r.kind} | `{r.path}` |")
    out.append("")
    out.append(f"Total drift rows: **{len(rows)}**.")
    out.append("")
    out.append("Pairs with DEEP-49 sync_workflow_targets.py (rewriter).")
    return "\n".join(out) + "\n"


# --- entry point ---------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--check",
        action="store_true",
        help="Print row-per-diff table; exit 1 on drift. Default mode.",
    )
    parser.add_argument(
        "--report",
        action="store_true",
        help="Print markdown blurb (PR-body friendly) instead of table.",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=DEFAULT_REPO_ROOT,
        help=f"Repo root (default: {DEFAULT_REPO_ROOT}).",
    )
    args = parser.parse_args(argv)

    if not args.check and not args.report:
        args.check = True  # default behaviour matches DEEP-49

    try:
        rows = _collect(args.repo_root)
    except FileNotFoundError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 2

    if args.report:
        sys.stdout.write(_render_markdown(rows))
    else:
        sys.stdout.write(_render_table(rows))

    return 1 if rows else 0


if __name__ == "__main__":
    raise SystemExit(main())
