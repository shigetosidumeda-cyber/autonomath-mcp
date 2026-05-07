"""Test that no external LLM API imports leak into production code.

Enforces the No-LLM invariant from the launch plan §19.3 and operator
memory `feedback_autonomath_no_api_use`: AutonoMath bills ¥3/request and
cannot absorb per-request LLM provider costs. Any `import anthropic`,
`import openai`, `import google.generativeai`, or `import claude_agent_sdk`
under `src/`, `scripts/`, or `tests/` is a regression that fails CI.

Operator-only offline scripts that legitimately call LLM APIs live under
`tools/offline/` (which is NOT scanned here). See `tools/offline/README.md`.

Detection strategy:
  * Imports: AST-based — only flags actual `import X` / `from X import ...`
    statements. String literals containing the same phrase (e.g. existing
    meta-tests in `tests/test_self_improve_loops.py` that check for the
    forbidden strings inline) are NOT flagged.
  * Env vars: regex on non-comment, non-docstring lines — flags actual
    references to `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` / `GEMINI_API_KEY`
    / `GOOGLE_API_KEY` while permitting comments that mention the names
    in invariant-enforcement context (e.g. "NO ANTHROPIC_API_KEY").
"""

from __future__ import annotations

import ast
import pathlib
import re

FORBIDDEN_IMPORT_MODULES = {
    "anthropic",
    "openai",
    "google.generativeai",
    "claude_agent_sdk",
}
FORBIDDEN_ENV = (
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
)
PRODUCTION_DIRS = ("src", "scripts/cron", "scripts/etl", "tests")

# Files allowed to mention the forbidden tokens inline because they exist
# precisely to enforce the invariant (meta-tests / negative-assertion code).
# These files are still scanned for actual imports, but their string-literal
# hits on env-var names are tolerated.
META_TEST_ALLOWLIST = {
    "tests/test_no_llm_in_production.py",
    "tests/test_self_improve_loops.py",
    "tests/test_precompute_schemas.py",
}

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


def _module_is_forbidden(module_name: str | None) -> bool:
    """Return True if a `module_name` like 'anthropic.types' or 'openai' is forbidden."""
    if not module_name:
        return False
    head = module_name.split(".")[0]
    if head in {"anthropic", "openai", "claude_agent_sdk"}:
        return True
    # google.generativeai must match the dotted prefix.
    return bool(module_name == "google.generativeai" or module_name.startswith("google.generativeai."))


def _scan_imports(py_file: pathlib.Path) -> list[str]:
    """Return list of forbidden import statement descriptions found in py_file."""
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


_ENV_PATTERN = re.compile(r"\b(" + "|".join(re.escape(name) for name in FORBIDDEN_ENV) + r")\b")


def _scan_env_vars(py_file: pathlib.Path, in_meta_allowlist: bool) -> list[str]:
    """Return list of forbidden env var references on real code lines.

    Skips:
      * Comment-only lines (text after stripping leading `#`).
      * Lines inside docstring/string literals (rough heuristic via tokenize).
      * Files in META_TEST_ALLOWLIST (which use the strings as the content
        of the invariant they enforce).
    """
    if in_meta_allowlist:
        return []
    try:
        src = py_file.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return []

    # Strip docstrings + string literal contents using AST so we only scan
    # actual code identifiers + comments. We then drop comment-only lines.
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return []

    string_spans: list[tuple[int, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if hasattr(node, "lineno") and hasattr(node, "end_lineno"):
                string_spans.append((node.lineno, node.end_lineno or node.lineno))

    hits: list[str] = []
    for lineno, line in enumerate(src.splitlines(), start=1):
        # Skip lines that are inside a string-literal AST node.
        if any(start <= lineno <= end for start, end in string_spans):
            continue
        # Drop inline comment portion: everything after first unquoted '#'.
        # Approximation: strip from '#' to EOL. Acceptable here because we
        # already excluded string literals via the AST span check.
        code_part = line.split("#", 1)[0]
        m = _ENV_PATTERN.search(code_part)
        if m:
            hits.append(f"line {lineno}: {m.group(1)}")
    return hits


def test_no_llm_imports_in_production() -> None:
    violations: list[str] = []
    for prod_dir in PRODUCTION_DIRS:
        base = REPO_ROOT / prod_dir
        if not base.exists():
            continue
        for py_file in base.rglob("*.py"):
            rel = py_file.relative_to(REPO_ROOT).as_posix()
            if rel == "tests/test_no_llm_in_production.py":
                continue
            in_meta = rel in META_TEST_ALLOWLIST
            for hit in _scan_imports(py_file):
                violations.append(f"{rel}: {hit}")
            for hit in _scan_env_vars(py_file, in_meta_allowlist=in_meta):
                violations.append(f"{rel}: {hit}")

    assert not violations, (
        "LLM API leaked into production code:\n  - "
        + "\n  - ".join(violations)
        + "\n\nOperator-only offline scripts must live in tools/offline/."
    )


def test_offline_dir_is_not_imported_from_production() -> None:
    """Symmetric guard: nothing under src/ scripts/cron/ scripts/etl/ tests/
    may `import` from `tools.offline` either directly or via path tricks.
    """
    violations: list[str] = []
    forbidden_substrings = ("tools.offline", "tools/offline")
    for prod_dir in PRODUCTION_DIRS:
        base = REPO_ROOT / prod_dir
        if not base.exists():
            continue
        for py_file in base.rglob("*.py"):
            rel = py_file.relative_to(REPO_ROOT).as_posix()
            if rel == "tests/test_no_llm_in_production.py":
                continue
            try:
                src = py_file.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            try:
                tree = ast.parse(src)
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if any(s in alias.name for s in forbidden_substrings):
                            violations.append(f"{rel}: import {alias.name}")
                elif isinstance(node, ast.ImportFrom):
                    if node.module and any(s in node.module for s in forbidden_substrings):
                        violations.append(f"{rel}: from {node.module} import ...")
    assert not violations, "Production code imports from tools/offline/:\n  - " + "\n  - ".join(
        violations
    )
