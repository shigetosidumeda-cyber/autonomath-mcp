"""Test that no external LLM API imports leak into production code.

Enforces the No-LLM invariant from the launch plan §19.3 and operator
memory `feedback_autonomath_no_api_use` + `feedback_no_operator_llm_api`:
jpcite bills ¥3/request fully metered and cannot absorb per-request LLM
provider costs. A single LLM call costs ¥0.5–¥5; one slipped import on
the request path bankrupts the unit economics.

Any `import anthropic`, `import openai`, `import google.generativeai`, or
`import claude_agent_sdk` under `src/`, `scripts/`, or `tests/` is a
regression that fails CI. Operator-only offline scripts that legitimately
call LLM APIs live under `tools/offline/` (which is NOT scanned here).
See `tools/offline/README.md`.

Five-axis detection strategy (all axes must stay green):

  * **Axis 1 — Imports** (AST-based, `test_no_llm_imports_in_production`):
    Only flags actual `import X` / `from X import ...` statements. String
    literals containing the same phrase (e.g. existing meta-tests in
    `tests/test_self_improve_loops.py` that check for the forbidden
    strings inline) are NOT flagged.
  * **Axis 2 — Env var refs** (regex on non-string AST spans,
    `test_no_llm_imports_in_production`): Flags actual references to
    `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` / `GEMINI_API_KEY` /
    `GOOGLE_API_KEY` while permitting comments + docstrings that mention
    the names in invariant-enforcement context (e.g. "NO
    ANTHROPIC_API_KEY").
  * **Axis 3 — Hardcoded provider secrets**
    (`test_no_hardcoded_llm_secrets_in_production`): Regex over file
    contents for `sk-ant-...`, `sk-<20+chars>`, and `AIzaSy...` literal
    patterns. Real secrets live in `.env.local` (chmod 600, git-ignored)
    and Fly secrets, never the repo. Meta-test files are excluded — they
    intentionally name the patterns as the content of the rule they
    enforce.
  * **Axis 4 — `# noqa` allowlist boundary**
    (`test_noqa_llm_marker_only_in_offline`): A `# noqa: F401  #
    LLM_IMPORT_TOLERATED` (or any `# noqa.*LLM_IMPORT_TOLERATED`) marker
    may appear only in files under `tools/offline/`. Same marker in
    `src/` / `scripts/` / `tests/` is itself a violation, preventing the
    pattern "add an import + add a noqa to silence the test".
  * **Axis 5 — GitHub Actions workflow YAML inline-python**
    (`test_no_llm_in_workflow_inline_python`): Regex extraction of
    `python -c "..."` and `python <<'PY' ... PY` heredoc blocks in
    `.github/workflows/*.yml`. Flags forbidden imports / env-var refs
    that would execute on the runner, while tolerating shell
    `grep`/`!grep` invariant-enforcement lines (matched outside Python
    contexts).

`tools/offline/` is excluded from axes 1, 2, 3 by path filter
(operator-only offline tools may legitimately import LLM SDKs and read
API keys per CLAUDE.md). Axis 4 enforces that `tools/offline/` is the
**only** path that may carry the `LLM_IMPORT_TOLERATED` marker — so the
exclusion cannot be smuggled into production code.

Pre-commit / CI integration: pytest exits with rc=1 on assertion
failure, which `pre-commit` / GHA `pytest -x` treat as fail-closed.
Do **not** wrap the assertions in try/except — fail-closed is the
contract.
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
# Production python scan scope. Note: full `scripts/` is now scanned,
# which subsumes `scripts/cron` + `scripts/etl` + `scripts/ops` +
# `scripts/migrations` + `scripts/audits` + every `scripts/ingest_*.py`.
# `scripts/_archive/` is excluded by the loop below (legacy quarantine,
# not deployed). `tools/offline/` is also excluded by name (operator-only
# offline tools may legitimately import LLM SDKs per CLAUDE.md).
PRODUCTION_DIRS = ("src", "scripts", "tests")
EXCLUDED_PATH_FRAGMENTS = (
    "scripts/_archive/",
    "scripts/__pycache__/",
    "tools/offline/",
)
# Workflow YAML scope. Flags forbidden imports + env vars that appear
# inside Python heredocs / `python -c` blocks executed on CI runners.
WORKFLOW_DIR = ".github/workflows"

# Files allowed to mention the forbidden tokens inline because they exist
# precisely to enforce the invariant (meta-tests / negative-assertion code).
# These files are still scanned for actual imports, but their string-literal
# hits on env-var names + secret patterns are tolerated.
META_TEST_ALLOWLIST = {
    "tests/test_no_llm_in_production.py",
    "tests/test_self_improve_loops.py",
    "tests/test_precompute_schemas.py",
}

# Marker that the `# noqa` axis recognizes as an explicit LLM-tolerated
# import. Allowed only in files under `tools/offline/`.
NOQA_LLM_MARKER = "LLM_IMPORT_TOLERATED"

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


def _module_is_forbidden(module_name: str | None) -> bool:
    """Return True if a `module_name` like 'anthropic.types' or 'openai' is forbidden."""
    if not module_name:
        return False
    head = module_name.split(".")[0]
    if head in {"anthropic", "openai", "claude_agent_sdk"}:
        return True
    # google.generativeai must match the dotted prefix.
    return bool(
        module_name == "google.generativeai" or module_name.startswith("google.generativeai.")
    )


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
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and hasattr(node, "lineno")
            and hasattr(node, "end_lineno")
        ):
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


def _is_excluded(rel_posix: str) -> bool:
    return any(frag in rel_posix for frag in EXCLUDED_PATH_FRAGMENTS)


def test_no_llm_imports_in_production() -> None:
    """Axis 1 + Axis 2: actual imports + env-var refs on real code lines."""
    violations: list[str] = []
    for prod_dir in PRODUCTION_DIRS:
        base = REPO_ROOT / prod_dir
        if not base.exists():
            continue
        for py_file in base.rglob("*.py"):
            rel = py_file.relative_to(REPO_ROOT).as_posix()
            if rel == "tests/test_no_llm_in_production.py":
                continue
            if _is_excluded(rel):
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
    """Symmetric guard: nothing under src/ scripts/ tests/ (excluding
    `scripts/_archive/` and `tools/offline/` itself) may `import` from
    `tools.offline` either directly or via path tricks.
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
            if _is_excluded(rel):
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
                elif (
                    isinstance(node, ast.ImportFrom)
                    and node.module
                    and any(s in node.module for s in forbidden_substrings)
                ):
                    violations.append(f"{rel}: from {node.module} import ...")
    assert not violations, "Production code imports from tools/offline/:\n  - " + "\n  - ".join(
        violations
    )


# --- Axis 3: hardcoded provider secrets ---------------------------------
# Detects literal API keys checked into the repo. These patterns are the
# documented prefix shapes for Anthropic / OpenAI / Google AI Studio
# tokens. We intentionally do not try to match every provider — these
# three cover the four FORBIDDEN_IMPORT_MODULES surface and catch the
# common "I'll paste my key for testing and remove it later" footgun.
#
# Pattern notes:
#   * `sk-ant-` — Anthropic API key prefix; followed by the random body.
#   * `sk-[A-Za-z0-9]{20,}` — OpenAI legacy `sk-...` prefix and
#     OpenAI-compatible providers. We require ≥20 trailing chars to
#     avoid matching shell-style `sk-` prose in docstrings.
#   * `AIzaSy[A-Za-z0-9_-]{30,}` — Google API key shape (Gemini /
#     generativeai / Cloud APIs). The trailing length floor avoids
#     matching prose like "AIzaSy is the Google prefix" in docstrings.

_SECRET_PATTERNS = (
    re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}"),
    re.compile(r"\bsk-[A-Za-z0-9]{20,}"),
    re.compile(r"\bAIzaSy[A-Za-z0-9_-]{30,}"),
)


def _scan_secret_literals(py_file: pathlib.Path) -> list[str]:
    """Return list of forbidden secret literal hits on any line."""
    try:
        src = py_file.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return []
    hits: list[str] = []
    for lineno, line in enumerate(src.splitlines(), start=1):
        for pat in _SECRET_PATTERNS:
            m = pat.search(line)
            if m:
                # Show prefix only — never echo the suspected full secret
                # back into the failure message (CI logs are not safe
                # for secret payloads even when fake).
                hits.append(f"line {lineno}: matches {pat.pattern!r} (prefix shown: {m.group(0)[:10]}...)")
    return hits


def test_no_hardcoded_llm_secrets_in_production() -> None:
    """Axis 3: no `sk-ant-...`, `sk-...`, or `AIzaSy...` literals in the
    repo under the production trees. Real secrets live in `.env.local`
    (chmod 600, git-ignored) and Fly secrets only.
    """
    violations: list[str] = []
    for prod_dir in PRODUCTION_DIRS:
        base = REPO_ROOT / prod_dir
        if not base.exists():
            continue
        for py_file in base.rglob("*.py"):
            rel = py_file.relative_to(REPO_ROOT).as_posix()
            if rel == "tests/test_no_llm_in_production.py":
                continue
            if _is_excluded(rel):
                continue
            # Meta-tests intentionally name the patterns; tolerate but
            # still surface for review — actual hardcoded secrets would
            # land in non-meta paths.
            if rel in META_TEST_ALLOWLIST:
                continue
            for hit in _scan_secret_literals(py_file):
                violations.append(f"{rel}: {hit}")

    assert not violations, (
        "Hardcoded LLM provider secret(s) found in repo:\n  - "
        + "\n  - ".join(violations)
        + "\n\nReal secrets live in .env.local (chmod 600, git-ignored) and"
        " Fly secrets. Rotate the leaked credential immediately."
    )


# --- Axis 4: `# noqa LLM_IMPORT_TOLERATED` allowlist boundary -----------
# The pattern "add an LLM import + add a noqa to silence the test" must
# fail. The `LLM_IMPORT_TOLERATED` marker is allowed **only** in files
# under `tools/offline/`. This test asserts that no file outside
# `tools/offline/` carries the marker. Combined with axis 1 (which AST-
# scans imports regardless of comments), this closes the noqa-escape hatch.

_NOQA_LLM_RE = re.compile(r"#\s*noqa[^#\n]*\b" + re.escape(NOQA_LLM_MARKER) + r"\b", re.IGNORECASE)


def test_noqa_llm_marker_only_in_offline() -> None:
    """Axis 4: the `LLM_IMPORT_TOLERATED` noqa marker is allowed only
    under `tools/offline/`. Same marker anywhere in `src/` / `scripts/`
    / `tests/` is itself a violation (closes the noqa-escape hatch).
    """
    violations: list[str] = []
    for prod_dir in PRODUCTION_DIRS:
        base = REPO_ROOT / prod_dir
        if not base.exists():
            continue
        for py_file in base.rglob("*.py"):
            rel = py_file.relative_to(REPO_ROOT).as_posix()
            # The test file documents the marker in its own docstring,
            # which is fine because axis 1 still scans AST imports
            # regardless of noqa. Skip self.
            if rel == "tests/test_no_llm_in_production.py":
                continue
            if _is_excluded(rel):
                continue
            try:
                src = py_file.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            for lineno, line in enumerate(src.splitlines(), start=1):
                if _NOQA_LLM_RE.search(line):
                    violations.append(f"{rel}: line {lineno}: {line.strip()}")

    assert not violations, (
        f"`{NOQA_LLM_MARKER}` noqa marker present outside tools/offline/:\n  - "
        + "\n  - ".join(violations)
        + "\n\nThe marker is allowed only in tools/offline/. Adding it elsewhere"
        " would silence axis 1 of the LLM-isolation guard."
    )


# --- Axis 5: GitHub Actions workflow YAML scan --------------------------
# We do NOT depend on PyYAML (test must run with stdlib only). Instead we
# do conservative regex extraction of inline-Python regions:
#   * `python -c "..."` / `python -c '...'` (single-line)
#   * `python <<'PY'` ... `PY` (heredoc; common idiom in this repo)
#   * `python <<EOF` ... `EOF`
#   * `python3 -c ...` / `python3 <<...` variants
# Whatever lies between the markers is treated as Python source and scanned
# for the forbidden import / env-var tokens. Anything OUTSIDE such regions
# is treated as shell text and is NOT scanned for env-var names — that is
# how lines like `! grep -E "(ANTHROPIC_API_KEY|...)" path` (which are the
# *enforcement* of the invariant) stay green.
_PY_HEREDOC_RE = re.compile(
    r"python3?\s*<<[-]?'?(?P<tag>[A-Z_][A-Z0-9_]*)'?\n(?P<body>.*?)\n\s*(?P=tag)\b",
    re.DOTALL,
)
_PY_DASHC_RE = re.compile(
    r"""python3?\s+-c\s+(?P<q>['"])(?P<body>.*?)(?<!\\)(?P=q)""",
    re.DOTALL,
)
_FORBIDDEN_IMPORT_RE = re.compile(
    r"""(?m)^\s*(?:from\s+(?P<from_mod>[A-Za-z_][\w.]*)\s+import\b|import\s+(?P<imp_mod>[A-Za-z_][\w.]*))"""
)
_ENV_TOKEN_RE = re.compile(r"\b(" + "|".join(re.escape(n) for n in FORBIDDEN_ENV) + r")\b")


def _scan_workflow_python_regions(yaml_text: str) -> list[str]:
    """Return list of forbidden-token descriptions inside Python regions
    of a workflow YAML body. Caller prepends the file path.
    """
    hits: list[str] = []
    regions: list[tuple[int, str]] = []  # (yaml_offset, py_source)
    for m in _PY_HEREDOC_RE.finditer(yaml_text):
        regions.append((m.start("body"), m.group("body")))
    for m in _PY_DASHC_RE.finditer(yaml_text):
        regions.append((m.start("body"), m.group("body")))

    for offset, body in regions:
        # Forbidden imports
        for im in _FORBIDDEN_IMPORT_RE.finditer(body):
            mod = im.group("from_mod") or im.group("imp_mod") or ""
            if _module_is_forbidden(mod):
                # Estimate line number in original YAML for error message.
                yaml_line = yaml_text.count("\n", 0, offset + im.start()) + 1
                hits.append(f"line {yaml_line}: import {mod} (inside python region)")
        # Forbidden env-var references (skip lines that are entirely
        # comments inside the python region — `#` to EOL).
        for lineno_in_body, line in enumerate(body.splitlines(), start=1):
            code_part = line.split("#", 1)[0]
            em = _ENV_TOKEN_RE.search(code_part)
            if em:
                # Map back to YAML line number.
                yaml_line = yaml_text.count("\n", 0, offset) + lineno_in_body
                hits.append(f"line {yaml_line}: {em.group(1)} (inside python region)")
    return hits


def test_no_llm_in_workflow_inline_python() -> None:
    """Axis 5: GitHub Actions runners execute `run:` shell bodies. Any
    inline Python (heredoc or `-c`) that imports an LLM SDK or reads an
    LLM API key is a regression — workflows ship to production CI/CD.
    """
    base = REPO_ROOT / WORKFLOW_DIR
    if not base.exists():
        return  # No workflows in this checkout — nothing to enforce.
    violations: list[str] = []
    for yml in sorted(base.glob("*.yml")):
        try:
            text = yml.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        rel = yml.relative_to(REPO_ROOT).as_posix()
        for hit in _scan_workflow_python_regions(text):
            violations.append(f"{rel}: {hit}")
    # Also scan `*.yaml` extension just in case.
    for yml in sorted(base.glob("*.yaml")):
        try:
            text = yml.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        rel = yml.relative_to(REPO_ROOT).as_posix()
        for hit in _scan_workflow_python_regions(text):
            violations.append(f"{rel}: {hit}")

    assert not violations, (
        "LLM API leaked into a GitHub Actions workflow inline-python block:\n  - "
        + "\n  - ".join(violations)
        + "\n\nMove operator-only LLM work to tools/offline/ (run locally, not on CI)."
    )
