"""CI gate — forbid git commit-time bypass flags in scripts and workflows.

Enforces the CLAUDE.md non-negotiable from §"What NOT to do":

    Never push with `--no-verify` or `--no-gpg-sign`. Fix the hook failure.

Plus the related general rule from the Claude Code git safety protocol that
``git rebase --no-edit`` is not a valid escape hatch either.

What this test prevents
-----------------------

A script or GitHub Actions workflow that wraps ``git commit --no-verify`` /
``git push --no-verify`` / ``git commit --no-gpg-sign`` / ``git rebase
--no-edit`` to silently bypass pre-commit hooks or GPG signing. The
operator's CLAUDE.md treats hook failures as signals to fix, not signals to
skip; a single tracked invocation that ships the bypass would normalize the
pattern across the codebase.

Why we tolerate three classes of "looks-like-bypass-but-isn't" matches
----------------------------------------------------------------------

1. **Enforcement comments.** ``pages-deploy-main.yml`` carries a comment
   that literally quotes ``--no-verify`` to remind contributors of the
   rule. Stripping the quote would weaken the file's self-documenting
   enforcement.
2. **Argparse flag declarations.** ``scripts/ingest/ingest_jst_programs.py``
   defines an argparse flag ``--no-verify`` that toggles URL HEAD-check
   skipping (network liveness, **not** git hook bypass). Same shape exists
   under ``--no-verify-urls`` in ``ingest_amed_jsps_jfc_programs.py``. The
   tokens collide with the git-bypass spelling but the semantics are
   unrelated — git is never invoked on those code paths.
3. **Git ``.sample`` hooks shipped by default.** ``.git/hooks/*.sample``
   files come from upstream git itself and are not executed (only the
   non-``.sample`` variants run). We do not edit upstream sample files.

Detection strategy
------------------

* **Phase 1 — scripts/ + .github/workflows/ scan.** For each line, extract
  the forbidden tokens (``--no-verify``, ``--no-gpg-sign``, ``--no-edit``).
  Only flag the line if it ALSO contains a git verb invocation
  (``git commit``, ``git push``, ``git rebase``, ``git merge``,
  ``git revert``, ``git cherry-pick``, ``git tag``, ``git am``,
  ``git apply``) on the same line — that's the only context in which the
  tokens actually bypass hooks/signing/editor. Argparse declarations and
  enforcement comments do not co-occur with a git verb on the same line,
  so they pass through.

* **Phase 2 — .git/hooks/ scan.** Inspect only NON-``.sample`` files (the
  active hook surface). The upstream ``.sample`` set ships with git and we
  do not touch it; flagging it would be a permanent false positive.

* **Phase 3 — .pre-commit-config.yaml presence.** The bypass ban only
  has teeth if pre-commit is actually configured. Assert the config file
  exists and references at least one hook.

The test is intentionally non-AST — shell / YAML / mixed embedded scripts
cannot be parsed by a single AST. Line-level co-occurrence with a git verb
is the smallest pattern that catches real bypass calls without producing
false positives on the three tolerated classes above.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

# Directories scanned for git-time bypasses. These are the surfaces that
# could ship a commit/push automation. Per the WRITE scope constraint,
# this test does NOT modify scripts/ or .github/workflows/ itself.
_COMMIT_TIME_SCAN_DIRS: tuple[str, ...] = ("scripts", ".github/workflows")

# Forbidden tokens. ``--no-verify`` and ``--no-gpg-sign`` are explicitly
# named in CLAUDE.md §"What NOT to do"; ``--no-edit`` is named in the
# Claude Code git safety protocol ("Do not use --no-edit with git rebase
# commands").
_FORBIDDEN_TOKENS: tuple[str, ...] = (
    "--no-verify",
    "--no-gpg-sign",
    "--no-edit",
)

# Git verbs that can carry the forbidden flags. Detection requires the
# forbidden token AND one of these verbs on the same line — this is what
# distinguishes a real bypass from an argparse flag with a colliding name.
_GIT_VERB_RE = re.compile(
    r"\bgit\s+("
    r"commit|push|rebase|merge|revert|cherry-pick|tag|am|apply"
    r")\b"
)

# File extensions that can carry executable git invocations. We do NOT
# scan binary blobs or vendored archives.
_SCANNABLE_SUFFIXES: frozenset[str] = frozenset(
    {
        ".py",
        ".sh",
        ".bash",
        ".zsh",
        ".yml",
        ".yaml",
        ".toml",
        ".cfg",
        ".ini",
        ".mk",
        ".make",
        ".dockerfile",
        ".env",
        ".txt",
        ".md",
    }
)


def _iter_scannable_files(root: Path) -> list[Path]:
    """Return every regular file under ``root`` whose suffix is scannable.

    Symlinks are skipped (avoids walking outside the tree). Hidden dirs
    inside the root are included because ``.github/workflows`` is itself
    behind a hidden parent.
    """
    if not root.is_dir():
        return []
    out: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        # Files without an extension (rare in scripts/) — include only if
        # the parent indicates a shell script home (e.g. cron/ or hooks).
        if path.suffix == "" and "hooks" not in path.parts:
            continue
        if path.suffix and path.suffix.lower() not in _SCANNABLE_SUFFIXES:
            continue
        out.append(path)
    return out


def _find_bypass_lines(path: Path) -> list[tuple[int, str, str]]:
    """Return list of ``(lineno, token, line)`` real-bypass hits in ``path``.

    A hit requires BOTH:
    * a forbidden token literal on the line, AND
    * a git verb invocation (``git commit`` / ``git push`` / ...) on the
      same line.

    Comments that quote the token to enforce the rule, and argparse flag
    declarations that re-use the spelling for a non-git purpose, do not
    pair with a git verb on the same line and are therefore not flagged.
    """
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except (OSError, UnicodeDecodeError):
        return []
    hits: list[tuple[int, str, str]] = []
    for lineno, raw in enumerate(text.splitlines(), start=1):
        if not _GIT_VERB_RE.search(raw):
            continue
        for token in _FORBIDDEN_TOKENS:
            # Use a left word boundary so ``--no-verify-urls`` is NOT
            # caught by ``--no-verify``. The right side is bounded by
            # whitespace, end-of-line, or a shell terminator.
            pattern = re.escape(token) + r"(?=\s|$|[;&|`'\")])"
            if re.search(pattern, raw):
                hits.append((lineno, token, raw.strip()))
                break
    return hits


def test_no_git_bypass_in_scripts_and_workflows() -> None:
    """Phase 1: scripts/ and .github/workflows/ must not invoke git with
    ``--no-verify`` / ``--no-gpg-sign`` / ``--no-edit``.

    Argparse flag declarations and enforcement comments are tolerated
    because they cannot co-occur with a git verb on the same line.
    """
    violations: list[str] = []
    for sub in _COMMIT_TIME_SCAN_DIRS:
        root = REPO_ROOT / sub
        for path in _iter_scannable_files(root):
            for lineno, token, line in _find_bypass_lines(path):
                rel = path.relative_to(REPO_ROOT)
                violations.append(f"{rel}:{lineno}: {token} -> {line}")
    assert not violations, (
        "CLAUDE.md non-negotiable violated: scripts/ and .github/workflows/ "
        "must not invoke git with hook/signing/editor bypass flags. "
        "Fix the underlying hook failure instead of bypassing.\n" + "\n".join(violations)
    )


def test_no_git_bypass_in_active_git_hooks() -> None:
    """Phase 2: ``.git/hooks/`` must not contain executable hooks that
    invoke git with bypass flags.

    ``.git/hooks/*.sample`` files are skipped — those ship with upstream
    git itself and we do not modify them. Only non-``.sample`` hooks run
    against contributor commits.
    """
    hooks_dir = REPO_ROOT / ".git" / "hooks"
    if not hooks_dir.is_dir():
        pytest.skip(".git/hooks/ not present (non-git checkout)")
    violations: list[str] = []
    for path in hooks_dir.iterdir():
        if not path.is_file() or path.is_symlink():
            continue
        # Tolerate the default upstream sample set.
        if path.name.endswith(".sample"):
            continue
        for lineno, token, line in _find_bypass_lines(path):
            violations.append(f".git/hooks/{path.name}:{lineno}: {token} -> {line}")
    assert not violations, (
        "Active git hooks in .git/hooks/ (non-.sample) must not bypass "
        "verification/signing/editor — that defeats the purpose of having "
        "hooks at all.\n" + "\n".join(violations)
    )


def test_pre_commit_config_present_and_populated() -> None:
    """Phase 3: ``.pre-commit-config.yaml`` must exist at repo root and
    declare at least one hook entry.

    The ``--no-verify`` ban is meaningless if pre-commit is not actually
    configured — bypassing nothing would be a no-op. CLAUDE.md §"Quality
    gates" explicitly references this file ("Pre-commit hooks are
    configured in `.pre-commit-config.yaml` — do not bypass with
    `--no-verify`").
    """
    cfg = REPO_ROOT / ".pre-commit-config.yaml"
    assert cfg.is_file(), (
        ".pre-commit-config.yaml is missing at repo root. The CLAUDE.md "
        "ban on --no-verify presupposes pre-commit is configured."
    )
    text = cfg.read_text(encoding="utf-8", errors="replace")
    # A minimally-populated config must declare a ``repos:`` block AND
    # at least one ``hooks:`` (or ``- id:``) line. We do not enforce
    # which hooks — only that the config is not an empty stub.
    assert re.search(r"^\s*repos\s*:", text, flags=re.MULTILINE), (
        ".pre-commit-config.yaml is present but does not declare a "
        "`repos:` block — bypass ban would be a no-op."
    )
    assert re.search(r"^\s*-\s*id\s*:", text, flags=re.MULTILINE) or re.search(
        r"^\s*hooks\s*:", text, flags=re.MULTILINE
    ), (
        ".pre-commit-config.yaml is present but declares no hook entries "
        "— bypass ban would be a no-op."
    )


def test_bypass_token_set_matches_claude_md() -> None:
    """Meta-axis: the forbidden-token set must include the two tokens
    that CLAUDE.md §"What NOT to do" names explicitly.

    If CLAUDE.md adds a new bypass flag in the future and this test
    drifts, the meta-assert below will fail fast and force the operator
    to expand `_FORBIDDEN_TOKENS` rather than silently letting a new
    bypass slip through.
    """
    claude_md = REPO_ROOT / "CLAUDE.md"
    assert claude_md.is_file(), "CLAUDE.md missing at repo root."
    text = claude_md.read_text(encoding="utf-8", errors="replace")
    # The exact phrase from CLAUDE.md §"What NOT to do".
    assert "--no-verify" in text and "--no-gpg-sign" in text, (
        "CLAUDE.md no longer names --no-verify / --no-gpg-sign — "
        "verify this test's _FORBIDDEN_TOKENS still matches policy."
    )
    for required in ("--no-verify", "--no-gpg-sign"):
        assert required in _FORBIDDEN_TOKENS, (
            f"{required} is named in CLAUDE.md but missing from "
            "_FORBIDDEN_TOKENS — extend the tuple."
        )
