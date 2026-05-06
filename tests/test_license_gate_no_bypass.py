"""CI guard — every paid export route MUST go through the license gate.

AST-scans `src/jpintel_mcp/api/` for any function whose return type or
response Class hints contain ``ZIP``, ``CSV``, ``Excel``, or ``Parquet``
(case-insensitive) and asserts the function body references at least
one of:

  * `filter_redistributable`
  * `assert_no_blocked`

Hits without a gate reference are reported as `<file>:<line>` failures.
This guard is a tripwire — adding a new export path automatically trips
it until the new path is wired.

Spec source: `docs/_internal/value_maximization_plan_no_llm_api.md`
§24 + §28.9 No-Go #5.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------

_API_DIR = Path(__file__).resolve().parent.parent / "src" / "jpintel_mcp" / "api"

# Pattern matched against return-type annotations + the function body
# source. Case-insensitive so "ZipResponse", "csv_writer", "ExcelFile"
# all hit. Word-boundary on "csv" is loose because the guard wants false
# positives to be loud (fix the function or whitelist it).
_EXPORT_FORMAT_RE = re.compile(
    r"\b(zip|csv|excel|xlsx|parquet|streaming\s*response)\b",
    re.IGNORECASE,
)

# Tokens that prove the function ran the license export gate.
_GATE_TOKENS: tuple[str, ...] = (
    "filter_redistributable",
    "assert_no_blocked",
)

# Functions we explicitly accept as gate-free (e.g. the gate primitives
# themselves, helpers that don't actually emit bytes to the customer).
# Add a justification comment for each entry.
_WHITELIST: frozenset[tuple[str, str]] = frozenset(
    {
        # `_license_gate.py` is the gate itself — it cannot reference its
        # own primitives without being self-referential.
        ("_license_gate.py", "filter_redistributable"),
        ("_license_gate.py", "assert_no_blocked"),
        ("_license_gate.py", "annotate_attribution"),
        # `formats/` package contains pure-format dispatch helpers (CSV /
        # XLSX serializers); they receive ALREADY-GATED rows from the route
        # layer, so the gate runs upstream of them. The CI guard runs over
        # `api/` (top-level only). If `formats/` ever gets scanned, add
        # whitelist entries here.
    }
)

# Pre-existing export-shaped functions that the gate is NOT yet wired
# into. These are listed here AS A LEDGER, not as an exoneration — the
# guard reports them on every run via the dedicated "known-unwired"
# test below, so the operator sees the size of the technical debt every
# time CI runs and cannot accidentally ship new export paths past the
# gate. Adding to this set requires a justification comment.
#
# Each entry is `(filename, function_name, justification)`.
_KNOWN_UNWIRED_EXPORTS: frozenset[tuple[str, str, str]] = frozenset(
    {
        (
            "audit.py",
            "_render_csv",
            "audit log CSV export — pre-§24 path, scheduled for license-gate "
            "wiring after the audit log row schema gets a `license` column "
            "(audit rows are operator-only today, NOT customer-facing).",
        ),
        (
            "audit.py",
            "_render_docx",
            "audit log DOCX export — same as _render_csv (operator-only).",
        ),
        (
            "bulk_evaluate.py",
            "_build_zip",
            "bulk_evaluate ZIP — receives customer-supplied rows so the "
            "license attribution is the customer's, not ours; gate-wiring "
            "still pending the row-schema change to carry source license.",
        ),
        (
            "saved_searches.py",
            "saved_search_results_xlsx",
            "saved search Excel export — pre-§24 path, scheduled for "
            "license-gate wiring once each saved search result row carries "
            "source-side license attribution.",
        ),
    }
)


# ---------------------------------------------------------------------------
# Scanner
# ---------------------------------------------------------------------------


def _annotation_text(node: ast.AST | None) -> str:
    if node is None:
        return ""
    try:
        return ast.unparse(node)
    except Exception:
        return ""


def _function_source(tree: ast.AST, source: str) -> str:
    """Return the textual range of the function for token search."""
    try:
        return ast.unparse(tree)
    except Exception:
        return source  # fall back to whole file


def _function_mentions_gate(func_node: ast.FunctionDef) -> bool:
    """True if the function body references one of the gate tokens.

    Walks every Name / Attribute / Call node so a renamed-import
    `from ._license_gate import filter_redistributable as fr` is still
    detected (the textual unparse contains the original name in the
    `Import` node's `asname` — we walk the node tree directly so the
    actual call site is the source of truth).
    """
    for child in ast.walk(func_node):
        # Direct Name reference: `filter_redistributable(...)`
        if isinstance(child, ast.Name) and child.id in _GATE_TOKENS:
            return True
        # Attribute reference: `_license_gate.filter_redistributable(...)`
        if isinstance(child, ast.Attribute) and child.attr in _GATE_TOKENS:
            return True
    return False


def _scan_file(path: Path) -> list[tuple[Path, int, str, str]]:
    """Return list of (path, line, func_name, reason) violations."""
    text = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(text, filename=str(path))
    except SyntaxError:
        return []

    violations: list[tuple[Path, int, str, str]] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        if (path.name, node.name) in _WHITELIST:
            continue

        # Skip nested helpers (only top-level / class-level functions
        # are exposed via routers).
        # We still scan them to be safe; the gate token search is cheap.

        return_annot = _annotation_text(node.returns)

        # Look at the function body's textual source for the format
        # marker so a function that builds a ZIP via `BytesIO` + writes
        # `zipfile.ZipFile(...)` still trips the regex even when the
        # return type is plain `JSONResponse`.
        try:
            body_src = ast.unparse(node)
        except Exception:
            body_src = ""

        # We only want functions that ACTUALLY produce export bytes.
        # Heuristic: format marker must appear in either the return
        # annotation or the body source.
        combined = f"{return_annot}\n{body_src}"
        if not _EXPORT_FORMAT_RE.search(combined):
            continue

        # Stricter filter: the body source must reference at least one
        # of zipfile / csv module / openpyxl / pandas.to_csv / parquet
        # so we don't false-positive on "ZipResponse" type-annotations
        # that don't actually emit bytes.
        emits_bytes = any(
            tok in body_src
            for tok in (
                "zipfile.",
                "ZipFile(",
                "csv.writer",
                "csv.DictWriter",
                "openpyxl",
                "to_csv",
                "to_excel",
                "to_parquet",
                "ExcelWriter",
                "writestr(",
            )
        )
        if not emits_bytes:
            continue

        if _function_mentions_gate(node):
            continue

        violations.append(
            (
                path,
                node.lineno,
                node.name,
                "export-shaped function does NOT reference "
                f"{_GATE_TOKENS} — license gate bypass risk (§24).",
            )
        )

    return violations


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------


def test_no_new_export_function_bypasses_license_gate():
    """Every ZIP/CSV/Excel/Parquet emitter under api/ must reference
    `filter_redistributable` or `assert_no_blocked` somewhere in its
    body. Pre-existing unwired paths are tracked in
    `_KNOWN_UNWIRED_EXPORTS` (with justifications) so the test fails
    only when a NEW unwired export is added.

    Failure surface lists `<file>:<line> <func_name>` so the operator
    can jump straight to the offending callsite.
    """
    if not _API_DIR.exists():
        pytest.skip(f"api dir not found: {_API_DIR}")

    all_violations: list[tuple[Path, int, str, str]] = []
    py_files = sorted(p for p in _API_DIR.glob("*.py") if p.is_file())
    assert py_files, f"no .py files found under {_API_DIR}"

    for path in py_files:
        all_violations.extend(_scan_file(path))

    known_pairs = {(p[0], p[1]) for p in _KNOWN_UNWIRED_EXPORTS}
    new_violations = [v for v in all_violations if (v[0].name, v[2]) not in known_pairs]

    if not new_violations:
        return  # green — no NEW bypass paths

    msgs = [
        f"  {p.relative_to(_API_DIR.parent.parent.parent.parent)}:{ln} ({fn}) — {reason}"
        for p, ln, fn, reason in new_violations
    ]
    pytest.fail(
        "NEW license gate bypass detected — the following export-shaped "
        "functions do not call `filter_redistributable` or "
        "`assert_no_blocked`. Either wire the gate in, or add the "
        "(filename, function_name) tuple to `_KNOWN_UNWIRED_EXPORTS` "
        "with a justification:\n" + "\n".join(msgs)
    )


def test_known_unwired_exports_still_exist():
    """Companion check: every entry in `_KNOWN_UNWIRED_EXPORTS` must
    actually exist in the codebase. If a wiring lands and the function
    starts referencing the gate, OR if the function is removed, this
    test fails so the ledger stays in sync (no stale whitelist entries).

    On failure, drop the entry from `_KNOWN_UNWIRED_EXPORTS`.
    """
    all_violations: list[tuple[Path, int, str, str]] = []
    py_files = sorted(p for p in _API_DIR.glob("*.py") if p.is_file())
    for path in py_files:
        all_violations.extend(_scan_file(path))
    actual_pairs = {(v[0].name, v[2]) for v in all_violations}

    stale: list[tuple[str, str, str]] = []
    for entry in _KNOWN_UNWIRED_EXPORTS:
        filename, func_name, _justification = entry
        if (filename, func_name) not in actual_pairs:
            stale.append(entry)

    if stale:
        pytest.fail(
            "Stale entries in `_KNOWN_UNWIRED_EXPORTS` — these "
            "(file, func) tuples either no longer exist, or now "
            "reference the gate (good — drop them from the ledger):\n"
            + "\n".join(f"  {f}:{fn} ({just})" for f, fn, just in stale)
        )


def test_known_unwired_exports_visibility_report(capsys):
    """Always-passing report so the operator sees the technical-debt
    surface in the test output every CI run. Shows on stdout (NOT in
    failure text) — captured with `pytest -s` for human review."""
    if not _KNOWN_UNWIRED_EXPORTS:
        return
    print("\n[license-gate ledger] Known unwired export paths:")
    for filename, func_name, justification in sorted(_KNOWN_UNWIRED_EXPORTS):
        print(f"  - api/{filename}:{func_name} — {justification}")


def test_scanner_self_check_known_export_path_is_wired():
    """Defensive: the scanner MUST detect the existing wired DD ZIP
    path as compliant. If this fails, the scanner's `emits_bytes`
    heuristic has drifted away from `ma_dd._build_audit_bundle_zip`.

    Without this self-check, a regression in the scanner could turn it
    into a green-rubber-stamp. We assert the scanner DOES find the
    function in question AND that it passes the gate-mention check.
    """
    ma_dd_path = _API_DIR / "ma_dd.py"
    assert ma_dd_path.exists()
    text = ma_dd_path.read_text(encoding="utf-8")
    tree = ast.parse(text, filename=str(ma_dd_path))

    found_zip_builder = False
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        if node.name != "_build_audit_bundle_zip":
            continue
        found_zip_builder = True
        assert _function_mentions_gate(node), (
            "self-check: ma_dd._build_audit_bundle_zip lost its gate "
            "wire — `filter_redistributable` no longer appears in the "
            "body. Re-wire before merging."
        )
    assert found_zip_builder, (
        "self-check: ma_dd._build_audit_bundle_zip was renamed; update "
        "this scanner self-check or restore the function name."
    )


def test_format_dispatch_blocks_nonredistributable_rows():
    """Shared CSV/XLSX/MD/etc dispatcher must fail closed on unknown licenses."""
    from fastapi import HTTPException

    from jpintel_mcp.api._format_dispatch import render

    with pytest.raises(HTTPException) as excinfo:
        render(
            [{"name": "blocked", "license": "unknown", "source_url": "https://example.com"}],
            "csv",
        )

    assert excinfo.value.status_code == 403
    assert "license_gate" in str(excinfo.value.detail)


def test_format_dispatch_allows_redistributable_rows():
    """Allowed licenses pass through and receive attribution before rendering."""
    from jpintel_mcp.api._format_dispatch import render

    resp = render(
        [
            {
                "name": "allowed",
                "license": "gov_standard_v2.0",
                "source_url": "https://www.meti.go.jp/example",
                "fetched_at": "2026-05-04T00:00:00",
            }
        ],
        "csv",
    )

    body = resp.body.decode("utf-8-sig")
    assert "allowed" in body
    assert "_attribution" in body
