"""Guard against committing backup / venv / wrangler files into the tracked tree.

Enforces the `CLAUDE.md` invariant under "What NOT to do":

    Never commit `data/jpintel.db.bak.*` or `.wrangler/` or `.venv/` — if
    any slip through, add them to `.gitignore`.

Rationale: `data/jpintel.db.bak-*` and `data/jpintel.db.bak.*` are local
backup snapshots (dash and dot timestamp variants — both styles produced
by different backup scripts). `dist/` was once hit by the dot variant
and that blocked a PyPI publish. `.venv/` is a 1-2 GB virtualenv that
will balloon the repo. `.wrangler/` is a Cloudflare Wrangler cache that
holds per-developer state. None of these belong in version control.

The test has two halves:

  1. **Tracked-tree audit** — `git ls-files` MUST NOT contain any path
     matching the forbidden glob set. If it does, that path has slipped
     past `.gitignore` and needs to be `git rm --cached`'d in a follow-up.
  2. **`.gitignore` coverage** — the canonical patterns
     (`*.db.bak*`, `.venv/`, `.wrangler/`, plus the `.env` / `.env.*`
     family) MUST be present in `.gitignore` so future copies of the
     same files never reach the staging area in the first place.

Both halves are needed: half (1) catches the case where files were
committed before the ignore rule was added, half (2) catches the case
where someone deletes the ignore rule but the tree is incidentally clean
at the moment of the deletion.

If this test fails, the fix is:

  * For (1):  `git rm --cached <path>` + add to `.gitignore` if missing.
  * For (2):  add the missing pattern to `.gitignore`.

Do NOT relax this test by narrowing the forbidden globs — the CLAUDE.md
guidance is intentionally broad. See operator memory
`feedback_destruction_free_organization` for why we prefer ignore
additions over destructive removal.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# --- Forbidden patterns in tracked tree ------------------------------------
# These regexes are matched against every line of `git ls-files`. Any hit
# means a file slipped past .gitignore and is currently tracked.
#
# - `.bak`        : any backup-suffix file (covers .db.bak-20260423,
#                   .db.bak.20260423, pyproject.toml.bak, etc.)
# - `\.venv/`     : virtualenv directory (any depth)
# - `\.wrangler/` : Cloudflare Wrangler cache directory
#
# We do NOT flag generic `.env` because intentional non-secret config
# files like `scripts/rebrand_vars.env` exist; the CLAUDE.md NOT-list
# specifically calls out `.bak`, `.venv/`, `.wrangler/` and the runtime
# env files `.env` / `.env.local` (which are already covered by other
# guards + `.gitignore` lines 15 + 170).
FORBIDDEN_TRACKED_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\.bak(\.|-|$)", "backup file (.bak suffix)"),
    (r"\.db\.bak", "database backup (.db.bak)"),
    (r"(^|/)\.venv/", "virtualenv directory (.venv/)"),
    (r"(^|/)\.wrangler/", "Cloudflare Wrangler cache (.wrangler/)"),
)

# --- Required .gitignore patterns ------------------------------------------
# Each entry is a substring that MUST appear (verbatim) on some line of
# `.gitignore`. We use substring rather than regex to keep the test
# readable — `.gitignore` syntax is line-based and exact.
#
# `*.db.bak*` covers both `data/jpintel.db.bak-20260423` and
# `data/jpintel.db.bak.20260423` style backups at any depth.
REQUIRED_GITIGNORE_PATTERNS: tuple[str, ...] = (
    "*.db.bak*",  # any-depth .db.bak* backup
    ".venv/",  # virtualenv
    ".wrangler/",  # Cloudflare Wrangler cache
    ".env",  # root .env runtime file
    ".env.*",  # .env.local / .env.production / etc.
)


def _git_ls_files() -> list[str]:
    """Return the list of tracked files via `git ls-files`.

    Run from the repo root so that paths are repo-relative. We do NOT
    rely on the current working directory because pytest may invoke this
    test from anywhere.
    """
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return [line for line in result.stdout.splitlines() if line]


def test_no_backup_or_venv_or_wrangler_files_tracked() -> None:
    """No `.bak` / `.venv/` / `.wrangler/` paths in `git ls-files`."""
    tracked = _git_ls_files()
    offenders: list[tuple[str, str]] = []
    for path in tracked:
        for pattern, label in FORBIDDEN_TRACKED_PATTERNS:
            if re.search(pattern, path):
                offenders.append((path, label))
                break  # one label per path is enough

    assert not offenders, (
        "Forbidden files are tracked in git — `git rm --cached` them and "
        "verify `.gitignore` covers the pattern. See CLAUDE.md "
        "'What NOT to do' and operator memory "
        "`feedback_destruction_free_organization`.\n"
        + "\n".join(f"  - {p}  ({why})" for p, why in offenders)
    )


def test_gitignore_covers_required_patterns() -> None:
    """`.gitignore` MUST contain each required pattern verbatim."""
    gitignore_path = REPO_ROOT / ".gitignore"
    assert gitignore_path.is_file(), (
        f".gitignore not found at {gitignore_path} — the repo root is "
        "wrong, or the file was deleted."
    )
    text = gitignore_path.read_text(encoding="utf-8")
    lines = {line.strip() for line in text.splitlines()}

    missing = [pat for pat in REQUIRED_GITIGNORE_PATTERNS if pat not in lines]

    assert not missing, (
        "`.gitignore` is missing required patterns. CLAUDE.md "
        "'What NOT to do' requires these to be ignored so backup / "
        "venv / wrangler / .env files cannot slip into commits.\n"
        f"  missing: {missing}\n"
        f"  present (sample): {sorted(lines)[:10]}"
    )
