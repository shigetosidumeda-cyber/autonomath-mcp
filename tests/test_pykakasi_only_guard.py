"""Guard the CLAUDE.md gotcha: use `pykakasi`, not `cutlet`, for Hepburn slugs.

CLAUDE.md "Common gotchas" §229 states:

    Use `pykakasi`, not `cutlet` for Hepburn slug generation. `cutlet`
    pulls in `mojimoji` which fails to compile on macOS Rosetta.

Rationale (also captured here so the guard is self-documenting):

  * `cutlet` is a Japanese-to-romaji converter that depends on `mojimoji`
    for half-width / full-width normalization.
  * `mojimoji` ships a Cython extension that links against system libs
    not present on macOS running under Rosetta translation (x86_64
    binaries on Apple Silicon). `pip install mojimoji` fails at the
    compile step there, breaking `pip install -e ".[site]"` for any
    developer on an M-series Mac with a Rosetta-pinned interpreter.
  * `pykakasi` is pure Python (no native build), works on every host the
    repo targets, and is already the canonical slug generator used by
    `src/jpintel_mcp/utils/slug.py`, `scripts/cron/alias_dict_expansion.py`,
    `scripts/cron/generate_news_posts.py`, and
    `src/jpintel_mcp/self_improve/loop_e_alias_expansion.py`.

This test enforces three invariants:

  1. No source file under `src/`, `scripts/`, or `tests/` imports
     `cutlet` or `mojimoji` (any `import` / `from ... import` form).
  2. `pyproject.toml` does NOT list `cutlet` or `mojimoji` as a
     dependency — the only allowed occurrences are inside Python-style
     comments that document the gotcha (e.g. the existing comment above
     the `site = [...]` block that explains why we skip `cutlet`).
  3. The companion CLAUDE.md gotcha string remains present so the
     guard does not silently drift away from its documented source.

If a future developer reintroduces either dependency, this test fails
fast in CI and points at this docstring for the rationale. Do NOT
weaken the guard to "make it pass"; fix the cause by switching to
pykakasi.
"""

from __future__ import annotations

import ast
import pathlib
import re

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent

# Production python scan scope. Same shape as
# `tests/test_no_llm_in_production.py` so the two guards share
# operational mental model.
PRODUCTION_DIRS = ("src", "scripts", "tests")
EXCLUDED_PATH_FRAGMENTS = (
    "scripts/_archive/",
    "scripts/__pycache__/",
    "tools/offline/",
)

# Forbidden module head names. Any `import X` / `from X[...] import Y`
# whose dotted head matches one of these is a violation.
FORBIDDEN_HEAD_NAMES = frozenset({"cutlet", "mojimoji"})

# This file documents the forbidden names in its own docstring + code
# (as the content of the rule it enforces), so skip self when scanning.
SELF_REL = "tests/test_pykakasi_only_guard.py"


def _is_excluded(rel_posix: str) -> bool:
    return any(frag in rel_posix for frag in EXCLUDED_PATH_FRAGMENTS)


def _module_is_forbidden(module_name: str | None) -> bool:
    """Return True if `module_name` (e.g. 'cutlet' or 'mojimoji.something')
    matches one of the forbidden heads.
    """
    if not module_name:
        return False
    head = module_name.split(".")[0]
    return head in FORBIDDEN_HEAD_NAMES


def _scan_imports(py_file: pathlib.Path) -> list[str]:
    """Return list of forbidden import statement descriptions in py_file."""
    try:
        src = py_file.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return []
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return []
    hits: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _module_is_forbidden(alias.name):
                    hits.append(f"import {alias.name}")
        elif isinstance(node, ast.ImportFrom) and _module_is_forbidden(node.module):
            hits.append(f"from {node.module} import ...")
    return hits


def test_no_cutlet_or_mojimoji_imports_in_source() -> None:
    """Axis 1: no `import cutlet` / `import mojimoji` (or `from cutlet
    ...` / `from mojimoji ...`) anywhere under `src/`, `scripts/`, or
    `tests/`. AST-based so string-literal mentions in docstrings (like
    this one) are not flagged.
    """
    violations: list[str] = []
    for prod_dir in PRODUCTION_DIRS:
        base = REPO_ROOT / prod_dir
        if not base.exists():
            continue
        for py_file in base.rglob("*.py"):
            rel = py_file.relative_to(REPO_ROOT).as_posix()
            if rel == SELF_REL:
                continue
            if _is_excluded(rel):
                continue
            for hit in _scan_imports(py_file):
                violations.append(f"{rel}: {hit}")

    assert not violations, (
        "`cutlet` / `mojimoji` leaked into source tree:\n  - "
        + "\n  - ".join(violations)
        + "\n\nUse `pykakasi` for Hepburn slug generation. `cutlet`"
        " pulls in `mojimoji`, which fails to compile on macOS Rosetta."
        " See `src/jpintel_mcp/utils/slug.py` for the canonical pattern."
    )


# --- Axis 2: pyproject.toml dependency declaration scan -----------------
# We do NOT depend on tomllib semantics here (the toml shape may evolve);
# we instead do a conservative regex that flags any non-comment line
# mentioning `cutlet` or `mojimoji`. The existing site-extras comment
# block ("# API container never pulls in cutlet's mecab dependency.")
# is allowed because its line begins with `#` after leading whitespace.

_PYPROJECT = REPO_ROOT / "pyproject.toml"
_FORBIDDEN_DEP_RE = re.compile(r"\b(cutlet|mojimoji)\b")


def test_pyproject_does_not_declare_cutlet_or_mojimoji() -> None:
    """Axis 2: `pyproject.toml` must not list `cutlet` or `mojimoji` as
    a dependency. Comment lines documenting the gotcha are tolerated.
    """
    assert _PYPROJECT.exists(), f"pyproject.toml missing at {_PYPROJECT}"
    text = _PYPROJECT.read_text(encoding="utf-8")
    violations: list[str] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        stripped = line.lstrip()
        # Pure comment line — tolerate (this is how the gotcha is
        # documented inline next to the `site = [...]` block).
        if stripped.startswith("#"):
            continue
        # Code portion only (drop any trailing inline comment).
        code_part = line.split("#", 1)[0]
        m = _FORBIDDEN_DEP_RE.search(code_part)
        if m:
            violations.append(f"line {lineno}: {m.group(1)} -> {line.rstrip()}")

    assert not violations, (
        "`cutlet` / `mojimoji` declared in pyproject.toml:\n  - "
        + "\n  - ".join(violations)
        + "\n\n`pykakasi` is the only allowed Hepburn romaji backend"
        " (see CLAUDE.md 'Common gotchas'). `mojimoji` fails to compile"
        ' on macOS Rosetta and blocks `pip install -e ".[site]"`.'
    )


# --- Axis 3: CLAUDE.md anchor present -----------------------------------
# Ensures the guard does not silently outlive its documented source.
# If someone removes the gotcha line from CLAUDE.md, this test fails
# and forces a conscious decision: either the gotcha is still real (in
# which case re-add the line) or it has been resolved (in which case
# this test can be retired).

_CLAUDEMD = REPO_ROOT / "CLAUDE.md"
_CLAUDEMD_ANCHOR_RE = re.compile(
    r"`pykakasi`.*`cutlet`.*Hepburn",
    re.IGNORECASE | re.DOTALL,
)


def test_claudemd_anchor_for_pykakasi_gotcha_present() -> None:
    """Axis 3: the CLAUDE.md gotcha line that motivates this guard must
    remain present. Anchor: a sentence mentioning both `pykakasi` and
    `cutlet` in the context of Hepburn generation.
    """
    assert _CLAUDEMD.exists(), f"CLAUDE.md missing at {_CLAUDEMD}"
    text = _CLAUDEMD.read_text(encoding="utf-8")
    assert _CLAUDEMD_ANCHOR_RE.search(text), (
        "CLAUDE.md no longer documents the pykakasi-vs-cutlet gotcha."
        " Either restore the line under 'Common gotchas' or retire this"
        " guard intentionally."
    )


# --- Synthesized-leak detection -----------------------------------------
# Verifies that `_scan_imports` actually flags the patterns we claim to
# catch. Without this, a typo in `FORBIDDEN_HEAD_NAMES` would silently
# let real leaks through.

_LEAK_PATTERNS = (
    ("import cutlet", "import cutlet"),
    ("from cutlet import Katsu", "from cutlet"),
    ("import mojimoji", "import mojimoji"),
    ("from mojimoji import han_to_zen", "from mojimoji"),
)


def test_scan_imports_detects_synthesized_leaks(tmp_path: pathlib.Path) -> None:
    """Synthesized leak: each forbidden import variant must be flagged
    by `_scan_imports`. Guards the head-name set from silent drift.
    """
    misses: list[str] = []
    for stmt, expected in _LEAK_PATTERNS:
        leak_file = tmp_path / "synthesized_leak.py"
        leak_file.write_text(f"{stmt}\n", encoding="utf-8")
        hits = _scan_imports(leak_file)
        if not any(expected in h for h in hits):
            misses.append(f"`{stmt}` not detected (hits={hits!r})")
    assert not misses, "Forbidden import not flagged by _scan_imports:\n  - " + "\n  - ".join(
        misses
    )
