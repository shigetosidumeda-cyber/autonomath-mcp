"""
test_acceptance_criteria.py
============================

DEEP-59 acceptance criteria CI guard, jpcite v0.3.4.

Drives the 258 acceptance criteria distilled from the 33 DEEP specs
(R8_ACCEPTANCE_CRITERIA_CI_GUARD.md) through pytest parametrization.

Each criterion declares a `check_kind` (one of 12 verifiers) plus inputs;
this module dispatches to the matching verifier and asserts the expected
outcome. Designed for local dev runs, GHA pull_request gating and the weekly
schedule defined in `acceptance_criteria_ci.yml`.

Constraints honoured:
- LLM API call count = 0 (no `anthropic` / `openai` import; pure static checks).
- Stdlib + pytest + sqlglot + jsonschema + PyYAML only.
- Network calls limited to gh CLI subprocess (`check_gh_api`); skipped when
  `JPCITE_OFFLINE=1` (CI sets this for hermetic mode).
- jpcite scope only - paths assume repo root.

Author: session A lane (Wave 17 draft).
"""

from __future__ import annotations

import json
import os
import py_compile
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
import yaml

if TYPE_CHECKING:
    from collections.abc import Callable

# ---------------------------------------------------------------------------
# Constants & paths
# ---------------------------------------------------------------------------

REPO_ROOT = Path(os.environ.get("JPCITE_REPO_ROOT", Path(__file__).resolve().parents[1]))
CRITERIA_FILE = Path(
    os.environ.get(
        "JPCITE_ACCEPTANCE_YAML",
        Path(__file__).resolve().parent / "acceptance_criteria.yaml",
    )
)
OFFLINE = os.environ.get("JPCITE_OFFLINE", "0") == "1"

# Forbidden phrases inherited from DEEP-38 (business law disclaimer guard).
# These represent regulated-advice surface area that must NEVER ship.
BUSINESS_LAW_FORBIDDEN_PHRASES: tuple[str, ...] = (
    "確実に勝訴",
    "100%還付",
    "脱税",
    "節税スキーム保証",
    "弁護士法を逸脱",
    "税理士法を逸脱",
)

# Disclaimer markers tracked by DEEP-38 (must be PRESENT in shipped HTML).
REQUIRED_DISCLAIMER_MARKERS: tuple[str, ...] = (
    "_disclaimer_legal_advice",
    "_disclaimer_tax_advice",
    "_disclaimer_general_information",
)

# LLM SDK import patterns (forbidden in operator + API runtime).
LLM_API_IMPORT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^\s*import\s+anthropic", re.MULTILINE),
    re.compile(r"^\s*from\s+anthropic\s+import", re.MULTILINE),
    re.compile(r"^\s*import\s+openai", re.MULTILINE),
    re.compile(r"^\s*from\s+openai\s+import", re.MULTILINE),
    re.compile(r"^\s*from\s+anthropic_bedrock\s+import", re.MULTILINE),
)


# ---------------------------------------------------------------------------
# Verifier result type
# ---------------------------------------------------------------------------


@dataclass
class CheckResult:
    """Outcome of a single acceptance check."""

    ok: bool
    detail: str
    automated: bool = True

    def __bool__(self) -> bool:  # pragma: no cover - convenience
        return self.ok


# ---------------------------------------------------------------------------
# 12 check_kind verifier functions
# ---------------------------------------------------------------------------


def check_file_existence(path: str | Path) -> CheckResult:
    """1) Verify a path exists and is non-empty (file or directory)."""
    p = (REPO_ROOT / path).resolve() if not Path(path).is_absolute() else Path(path)
    if not p.exists():
        return CheckResult(False, f"missing: {p}")
    if p.is_file() and p.stat().st_size == 0:
        return CheckResult(False, f"empty file: {p}")
    return CheckResult(True, f"present: {p}")


def check_jsonschema(file: str | Path, schema: dict[str, Any]) -> CheckResult:
    """2) Validate a JSON file against a JSON Schema."""
    try:
        import jsonschema  # type: ignore[import-untyped]
    except ImportError:  # pragma: no cover - hard dep in CI
        return CheckResult(False, "jsonschema not installed", automated=False)

    p = (REPO_ROOT / file) if not Path(file).is_absolute() else Path(file)
    if not p.exists():
        return CheckResult(False, f"missing: {p}")
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        jsonschema.validate(instance=data, schema=schema)
        return CheckResult(True, f"jsonschema ok: {p}")
    except jsonschema.ValidationError as exc:  # type: ignore[attr-defined]
        return CheckResult(False, f"schema fail {p}: {exc.message}")
    except json.JSONDecodeError as exc:
        return CheckResult(False, f"json parse fail {p}: {exc}")


def check_sql_syntax(file: str | Path) -> CheckResult:
    """3) Parse a SQL file with sqlglot (sqlite dialect)."""
    try:
        import sqlglot  # type: ignore[import-untyped]
    except ImportError:  # pragma: no cover
        return CheckResult(False, "sqlglot not installed", automated=False)

    p = (REPO_ROOT / file) if not Path(file).is_absolute() else Path(file)
    if not p.exists():
        return CheckResult(False, f"missing: {p}")
    try:
        text = p.read_text(encoding="utf-8")
        # sqlglot parses statement-by-statement; we accept either dialect.
        sqlglot.parse(text, read="sqlite")
        return CheckResult(True, f"sql parsed: {p.name}")
    except sqlglot.errors.ParseError as exc:  # type: ignore[attr-defined]
        return CheckResult(False, f"sql parse fail {p}: {exc}")


def check_python_compile(file: str | Path) -> CheckResult:
    """4) Compile a Python file via py_compile (syntax-level)."""
    p = (REPO_ROOT / file) if not Path(file).is_absolute() else Path(file)
    if not p.exists():
        return CheckResult(False, f"missing: {p}")
    try:
        py_compile.compile(str(p), doraise=True)
        return CheckResult(True, f"py compile ok: {p.name}")
    except py_compile.PyCompileError as exc:
        return CheckResult(False, f"py compile fail {p}: {exc}")


def check_llm_api_import_zero(file: str | Path) -> CheckResult:
    """5) Assert a Python file contains zero LLM SDK imports.

    Guards the `Operator-LLM API 呼出も全廃` rule (Wave 1-5).
    """
    p = (REPO_ROOT / file) if not Path(file).is_absolute() else Path(file)
    if not p.exists():
        return CheckResult(False, f"missing: {p}")
    text = p.read_text(encoding="utf-8")
    hits: list[str] = []
    for pat in LLM_API_IMPORT_PATTERNS:
        for m in pat.finditer(text):
            hits.append(m.group(0).strip())
    if hits:
        return CheckResult(False, f"LLM imports in {p}: {hits}")
    return CheckResult(True, f"LLM import-free: {p.name}")


def check_pytest_collect(test_file: str | Path) -> CheckResult:
    """6) Run `pytest --collect-only -q` on a target file (no execution)."""
    p = (REPO_ROOT / test_file) if not Path(test_file).is_absolute() else Path(test_file)
    if not p.exists():
        return CheckResult(False, f"missing: {p}")
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "--collect-only", "-q", str(p)],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=str(REPO_ROOT),
        )
    except subprocess.TimeoutExpired:
        return CheckResult(False, f"pytest collect timeout: {p}")
    if proc.returncode == 0:
        return CheckResult(True, f"pytest collected: {p.name}")
    return CheckResult(
        False,
        f"pytest collect rc={proc.returncode} stderr={proc.stderr[:200]}",
    )


def check_gha_yaml_syntax(file: str | Path) -> CheckResult:
    """7) Parse a GitHub Actions workflow YAML and assert minimal shape."""
    p = (REPO_ROOT / file) if not Path(file).is_absolute() else Path(file)
    if not p.exists():
        return CheckResult(False, f"missing: {p}")
    try:
        doc = yaml.safe_load(p.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        return CheckResult(False, f"yaml fail {p}: {exc}")
    # YAML coerces the bareword `on:` into Python True; accept either key.
    if not isinstance(doc, dict):
        return CheckResult(False, f"workflow root not mapping: {p}")
    has_on = "on" in doc or True in doc
    if not has_on or "jobs" not in doc:
        return CheckResult(False, f"workflow missing on/jobs: {p}")
    return CheckResult(True, f"gha yaml ok: {p.name}")


def check_html5_doctype_meta(file: str | Path) -> CheckResult:
    """8) Verify HTML5 doctype + UTF-8 meta + viewport are present."""
    p = (REPO_ROOT / file) if not Path(file).is_absolute() else Path(file)
    if not p.exists():
        return CheckResult(False, f"missing: {p}")
    text = p.read_text(encoding="utf-8", errors="replace")
    if not re.search(r"<!doctype\s+html\s*>", text, re.IGNORECASE):
        return CheckResult(False, f"missing <!doctype html>: {p}")
    if not re.search(r'<meta[^>]+charset=["\']?utf-8', text, re.IGNORECASE):
        return CheckResult(False, f"missing utf-8 meta: {p}")
    if not re.search(r'<meta[^>]+name=["\']viewport', text, re.IGNORECASE):
        return CheckResult(False, f"missing viewport meta: {p}")
    return CheckResult(True, f"html5 ok: {p.name}")


def check_schema_org_jsonld(html_file: str | Path) -> CheckResult:
    """9) Find at least one schema.org JSON-LD block in the HTML."""
    p = (REPO_ROOT / html_file) if not Path(html_file).is_absolute() else Path(html_file)
    if not p.exists():
        return CheckResult(False, f"missing: {p}")
    text = p.read_text(encoding="utf-8", errors="replace")
    blocks = re.findall(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        text,
        re.DOTALL | re.IGNORECASE,
    )
    if not blocks:
        return CheckResult(False, f"no JSON-LD: {p}")
    schema_org_seen = False
    for block in blocks:
        try:
            obj = json.loads(block.strip())
        except json.JSONDecodeError:
            continue
        ctx = obj.get("@context") if isinstance(obj, dict) else None
        if isinstance(ctx, str) and "schema.org" in ctx:
            schema_org_seen = True
            break
    if not schema_org_seen:
        return CheckResult(False, f"JSON-LD missing schema.org @context: {p}")
    return CheckResult(True, f"schema.org JSON-LD ok: {p.name}")


def check_regex_pattern_count(file: str | Path, pattern: str, min_count: int) -> CheckResult:
    """10) Assert `pattern` appears at least `min_count` times in `file`."""
    p = (REPO_ROOT / file) if not Path(file).is_absolute() else Path(file)
    if not p.exists():
        return CheckResult(False, f"missing: {p}")
    text = p.read_text(encoding="utf-8", errors="replace")
    n = len(re.findall(pattern, text))
    if n < min_count:
        return CheckResult(
            False,
            f"pattern /{pattern}/ found {n} < {min_count} in {p.name}",
        )
    return CheckResult(True, f"pattern /{pattern}/ x{n} in {p.name}")


def check_migration_first_line_marker(sql_file: str | Path) -> CheckResult:
    """11) Migrations MUST begin with `-- migration: NNN_<slug>` marker.

    Convention defined in DEEP-22 / DEEP-26.
    """
    p = (REPO_ROOT / sql_file) if not Path(sql_file).is_absolute() else Path(sql_file)
    if not p.exists():
        return CheckResult(False, f"missing: {p}")
    first = p.read_text(encoding="utf-8").splitlines()[:1]
    if not first:
        return CheckResult(False, f"empty migration: {p}")
    if not re.match(r"^--\s*migration:\s*\d{3,4}_[a-z0-9_]+", first[0]):
        return CheckResult(False, f"bad migration marker {p}: {first[0]!r}")
    return CheckResult(True, f"migration marker ok: {p.name}")


def check_business_law_forbidden_phrases(text_file: str | Path) -> CheckResult:
    """12) DEEP-38: assert NO forbidden regulated-advice phrase appears."""
    p = (REPO_ROOT / text_file) if not Path(text_file).is_absolute() else Path(text_file)
    if not p.exists():
        return CheckResult(False, f"missing: {p}")
    text = p.read_text(encoding="utf-8", errors="replace")
    found = [phrase for phrase in BUSINESS_LAW_FORBIDDEN_PHRASES if phrase in text]
    if found:
        return CheckResult(False, f"forbidden phrases in {p.name}: {found}")
    return CheckResult(True, f"business-law clean: {p.name}")


# ---------------------------------------------------------------------------
# Auxiliary check_kinds (non-core but referenced by acceptance_criteria.yaml)
# ---------------------------------------------------------------------------


def check_sql_count(query: str, expected: str, db_path: str | None = None) -> CheckResult:
    """Run a SELECT COUNT(*) and compare against an `expected` predicate.

    Skipped (semi-automated) when no DB is available - common in PR CI where
    the real SQLite snapshot is not packaged.
    """
    db = Path(db_path) if db_path else REPO_ROOT / "data" / "jpcite.db"
    if not db.exists():
        return CheckResult(True, f"db unavailable, skip count: {db}", automated=False)
    try:
        import sqlite3

        conn = sqlite3.connect(str(db))
        try:
            cur = conn.execute(query)
            row = cur.fetchone()
            n = int(row[0]) if row else 0
        finally:
            conn.close()
    except sqlite3.Error as exc:
        return CheckResult(False, f"sqlite error: {exc}")
    return _eval_predicate(n, expected)


def check_gh_api(command: str, expected: str) -> CheckResult:
    """Run a gh CLI command and string-compare stdout."""
    if OFFLINE:
        return CheckResult(True, "offline mode, skipped", automated=False)
    if shutil.which("gh") is None:
        return CheckResult(False, "gh CLI missing", automated=False)
    try:
        proc = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=30)
    except subprocess.TimeoutExpired:
        return CheckResult(False, "gh timeout")
    if proc.returncode != 0:
        return CheckResult(False, f"gh rc={proc.returncode}: {proc.stderr[:200]}")
    out = proc.stdout.strip().strip('"')
    if out != expected:
        return CheckResult(False, f"gh stdout {out!r} != {expected!r}")
    return CheckResult(True, f"gh ok: {expected}")


def check_disclaimer_marker_present(file: str | Path) -> CheckResult:
    """DEEP-38 sibling: assert disclaimer markers exist in shipped HTML."""
    p = (REPO_ROOT / file) if not Path(file).is_absolute() else Path(file)
    if not p.exists():
        return CheckResult(False, f"missing: {p}")
    text = p.read_text(encoding="utf-8", errors="replace")
    missing = [m for m in REQUIRED_DISCLAIMER_MARKERS if m not in text]
    if missing:
        return CheckResult(False, f"missing markers in {p.name}: {missing}")
    return CheckResult(True, f"disclaimer markers ok: {p.name}")


def _eval_predicate(value: int, expected: str) -> CheckResult:
    """Compare an integer against an expected string predicate.

    Supported forms: `==N`, `>=N`, `<=N`, `>N`, `<N`, plain `N` (==).
    """
    s = expected.strip()
    m = re.match(r"^(==|>=|<=|>|<)\s*(-?\d+)$", s)
    if m:
        op, n_str = m.group(1), m.group(2)
        n = int(n_str)
    elif re.match(r"^-?\d+$", s):
        op, n = "==", int(s)
    else:
        return CheckResult(False, f"bad predicate: {expected!r}")
    ok = {
        "==": value == n,
        ">=": value >= n,
        "<=": value <= n,
        ">": value > n,
        "<": value < n,
    }[op]
    return CheckResult(ok, f"{value} {op} {n} -> {ok}")


# ---------------------------------------------------------------------------
# Dispatch table - 12 core + 3 aux check_kinds.
# ---------------------------------------------------------------------------

CHECK_DISPATCH: dict[str, Callable[..., CheckResult]] = {
    "file_existence": lambda **kw: check_file_existence(kw["path"]),
    "jsonschema": lambda **kw: check_jsonschema(kw["file"], kw["schema"]),
    "sql_syntax": lambda **kw: check_sql_syntax(kw["file"]),
    "python_compile": lambda **kw: check_python_compile(kw["file"]),
    "llm_api_import_zero": lambda **kw: check_llm_api_import_zero(kw["file"]),
    "pytest_collect": lambda **kw: check_pytest_collect(kw["file"]),
    "gha_yaml_syntax": lambda **kw: check_gha_yaml_syntax(kw["file"]),
    "html5_doctype_meta": lambda **kw: check_html5_doctype_meta(kw["file"]),
    "schema_org_jsonld": lambda **kw: check_schema_org_jsonld(kw["file"]),
    "regex_pattern_count": lambda **kw: check_regex_pattern_count(
        kw["file"], kw["pattern"], int(kw.get("min_count", 1))
    ),
    "migration_first_line_marker": lambda **kw: check_migration_first_line_marker(kw["file"]),
    "business_law_forbidden_phrases": lambda **kw: check_business_law_forbidden_phrases(kw["file"]),
    # auxiliaries
    "sql_count": lambda **kw: check_sql_count(
        kw["query"], kw.get("expected", ">= 0"), kw.get("db_path")
    ),
    "gh_api": lambda **kw: check_gh_api(kw["command"], kw["expected"]),
    "disclaimer_marker_present": lambda **kw: check_disclaimer_marker_present(kw["file"]),
}

# Subset that counts toward the "12 core check_kind" automation ratio.
CORE_KINDS: frozenset[str] = frozenset(
    {
        "file_existence",
        "jsonschema",
        "sql_syntax",
        "python_compile",
        "llm_api_import_zero",
        "pytest_collect",
        "gha_yaml_syntax",
        "html5_doctype_meta",
        "schema_org_jsonld",
        "regex_pattern_count",
        "migration_first_line_marker",
        "business_law_forbidden_phrases",
    }
)


# ---------------------------------------------------------------------------
# YAML loader & parametrize
# ---------------------------------------------------------------------------


def load_criteria(path: Path = CRITERIA_FILE) -> list[dict[str, Any]]:
    """Load and lightly validate the YAML source-of-truth."""
    if not path.exists():
        return []
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError(f"{path} root must be a list")
    rows: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for entry in raw:
        if not isinstance(entry, dict):
            raise ValueError(f"non-mapping entry: {entry!r}")
        for key in ("id", "check_kind", "spec"):
            if key not in entry:
                raise ValueError(f"row {entry} missing {key}")
        if entry["id"] in seen_ids:
            raise ValueError(f"duplicate id: {entry['id']}")
        seen_ids.add(entry["id"])
        rows.append(entry)
    return rows


CRITERIA: list[dict[str, Any]] = load_criteria()


def _id_for(row: dict[str, Any]) -> str:
    """Pretty pytest id."""
    return f"{row['id']}-{row['check_kind']}"


# ---------------------------------------------------------------------------
# Pytest entry points
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("row", CRITERIA, ids=[_id_for(r) for r in CRITERIA] if CRITERIA else None)
def test_acceptance_criterion(row: dict[str, Any]) -> None:
    """Drive each criterion through its declared check_kind."""
    kind = row["check_kind"]
    fn = CHECK_DISPATCH.get(kind)
    if fn is None:
        pytest.fail(f"unknown check_kind: {kind} (id={row['id']})")
    inputs = {k: v for k, v in row.items() if k not in {"id", "check_kind", "spec", "automation"}}
    result = fn(**inputs)
    if not result.automated and not result.ok:
        pytest.skip(f"semi-automated skip: {result.detail}")
    assert result.ok, f"[{row['id']} / {row['spec']}] {result.detail}"


def test_yaml_present_and_nonempty() -> None:
    """The YAML source-of-truth must exist and contain >= 30 rows."""
    assert CRITERIA_FILE.exists(), f"missing {CRITERIA_FILE}"
    assert len(CRITERIA) >= 30, f"only {len(CRITERIA)} rows; need >= 30"


def test_check_kinds_within_known_set() -> None:
    """Every row's check_kind must be in the dispatch table."""
    unknown = sorted({r["check_kind"] for r in CRITERIA} - set(CHECK_DISPATCH))
    assert not unknown, f"unknown check_kind: {unknown}"


def test_no_llm_api_import_in_self() -> None:
    """This module itself must remain LLM-SDK-free."""
    me = Path(__file__)
    res = check_llm_api_import_zero(me)
    assert res.ok, res.detail
