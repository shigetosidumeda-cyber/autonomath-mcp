"""CI guard: dirty-tree fingerprint SOT helper must not be bypassed.

Background
----------
Before consolidation, ``scripts/ops/production_deploy_go_gate.py`` and
``tools/offline/operator_review/compute_dirty_fingerprint.py`` both
re-implemented the dirty-tree fingerprint algorithm independently. Their
output drifted (lane taxonomy, path_sha256 input, content_sha256 algorithm,
status_counts keying, --untracked-files=all flag) and the production
deploy gate would reject the operator's ACK YAML with
``dirty_fingerprint_mismatch`` issues, stalling launch at 4/5 PASS.

The 2026-05-07 ACK fix extracted the algorithm into the canonical SOT
helper ``scripts/ops/repo_dirty_lane_report.compute_canonical_dirty_fingerprint``
and made the gate + the operator-side CLI thin wrappers around it. The
companion test ``tests/test_dirty_fingerprint_consistency.py`` verifies
that on the same commit they emit bit-for-bit identical fingerprints.

This file enforces a *structural* guard so that future refactors cannot
silently re-introduce drift by inlining the algorithm again. Specifically:

  * test_gate_imports_helper — production_deploy_go_gate.py contains an
    AST-detectable import of ``compute_canonical_dirty_fingerprint``.
  * test_cli_imports_helper  — compute_dirty_fingerprint.py contains an
    AST-detectable import of ``compute_canonical_dirty_fingerprint``.
  * test_no_inline_lane_classification — neither caller defines its own
    ``classify_path`` (defining it again would mean lane-taxonomy drift).
  * test_no_inline_hash_computation — neither caller calls
    ``hashlib.sha256()`` on real code lines (the helper is the single
    place we hash; the CLI's docstring-level mention of ``hashlib`` is
    explicitly tolerated because it is not executable code).

Constraints (per CLAUDE.md / feedback_no_operator_llm_api):
  * LLM API call count: 0 (pure stdlib AST walk).
  * paid API call count: 0.
  * Tests must keep working when run as ``.venv/bin/pytest`` against
    a fresh checkout — they only read repo files, never network or DB.
"""

from __future__ import annotations

import ast
import pathlib

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
GATE_PATH = REPO_ROOT / "scripts" / "ops" / "production_deploy_go_gate.py"
CLI_PATH = (
    REPO_ROOT / "tools" / "offline" / "operator_review" / "compute_dirty_fingerprint.py"
)
SOT_PATH = REPO_ROOT / "scripts" / "ops" / "repo_dirty_lane_report.py"

CANONICAL_HELPER_NAME = "compute_canonical_dirty_fingerprint"
CANONICAL_LANE_FN_NAME = "classify_path"
SOT_MODULE_NAME = "repo_dirty_lane_report"


def _read_ast(path: pathlib.Path) -> ast.AST:
    assert path.is_file(), f"expected {path} to exist as the SOT or caller file"
    return ast.parse(path.read_text(encoding="utf-8"))


def _imports_name_from_sot(tree: ast.AST, target_name: str) -> bool:
    """Return True if ``tree`` contains a real import of ``target_name``
    sourced from the canonical SOT module.

    Accepts both shapes used in the codebase:
      * ``from repo_dirty_lane_report import compute_canonical_dirty_fingerprint``
      * ``from repo_dirty_lane_report import (..., compute_canonical_dirty_fingerprint, ...)``

    A bare ``import repo_dirty_lane_report`` followed by attribute access
    is *not* counted — both callers spell the import out explicitly today,
    and routing every future refactor through the explicit ``from`` form
    keeps grep results trivial for reviewers.
    """
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == SOT_MODULE_NAME:
            for alias in node.names:
                if alias.name == target_name:
                    return True
    return False


def _defines_function(tree: ast.AST, fn_name: str) -> bool:
    """Return True if ``tree`` defines a top-level or nested function named ``fn_name``."""
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name == fn_name:
            return True
    return False


def _calls_hashlib_sha256(tree: ast.AST) -> bool:
    """Return True if the AST contains a real ``hashlib.sha256(...)`` call.

    We deliberately scan AST ``Call`` nodes (not source text) so docstring
    or comment mentions of ``hashlib`` do not trip the guard. The CLI's
    module docstring carries one such tolerated mention.
    """
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if (
            isinstance(func, ast.Attribute)
            and func.attr == "sha256"
            and isinstance(func.value, ast.Name)
            and func.value.id == "hashlib"
        ):
            return True
    return False


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_gate_imports_helper() -> None:
    """The production deploy gate must call into the SOT helper, not re-implement it."""
    tree = _read_ast(GATE_PATH)
    assert _imports_name_from_sot(tree, CANONICAL_HELPER_NAME), (
        f"{GATE_PATH.relative_to(REPO_ROOT)} must import "
        f"'{CANONICAL_HELPER_NAME}' from '{SOT_MODULE_NAME}' so gate-side "
        "and operator-side fingerprints stay bit-for-bit identical. See "
        "tests/test_dirty_fingerprint_consistency.py for the runtime check."
    )


def test_cli_imports_helper() -> None:
    """The operator-side ACK CLI must call into the SOT helper, not re-implement it."""
    tree = _read_ast(CLI_PATH)
    assert _imports_name_from_sot(tree, CANONICAL_HELPER_NAME), (
        f"{CLI_PATH.relative_to(REPO_ROOT)} must import "
        f"'{CANONICAL_HELPER_NAME}' from '{SOT_MODULE_NAME}'. Drift between "
        "ACK CLI and gate stalls the operator at 4/5 PASS on "
        "operator_ack_signoff.py --all --commit."
    )


def test_no_inline_lane_classification() -> None:
    """Neither caller may redefine ``classify_path`` locally.

    Defining it again would mean the 16-lane taxonomy can drift between
    gate and CLI without the consistency test catching it on a clean tree.
    The SOT lives in ``repo_dirty_lane_report.classify_path``; both callers
    must forward there.
    """
    for path in (GATE_PATH, CLI_PATH):
        tree = _read_ast(path)
        assert not _defines_function(tree, CANONICAL_LANE_FN_NAME), (
            f"{path.relative_to(REPO_ROOT)} must NOT define its own "
            f"'{CANONICAL_LANE_FN_NAME}' — that function is the canonical "
            f"lane-taxonomy SOT in {SOT_MODULE_NAME}. Forward to the helper "
            "instead so both sides agree on the 16 lanes."
        )


def test_no_inline_hash_computation() -> None:
    """Neither caller may construct its own ``hashlib.sha256`` rolling hash.

    The fingerprint's ``content_sha256`` and ``path_sha256`` fields are
    computed exactly once, inside ``compute_canonical_dirty_fingerprint``.
    A new ``hashlib.sha256()`` call site in either caller is a strong
    signal that someone is re-implementing the algorithm and would re-
    introduce the drift the SOT helper exists to prevent.
    """
    for path in (GATE_PATH, CLI_PATH):
        tree = _read_ast(path)
        assert not _calls_hashlib_sha256(tree), (
            f"{path.relative_to(REPO_ROOT)} contains an inline "
            "'hashlib.sha256(...)' call. Hashing must happen exclusively "
            f"inside {SOT_MODULE_NAME}.{CANONICAL_HELPER_NAME} so the gate "
            "and the ACK CLI cannot drift on content_sha256 / path_sha256."
        )

    # And the SOT itself MUST keep using hashlib.sha256 — the guard would
    # otherwise become trivially passable by deleting hashing everywhere.
    sot_tree = _read_ast(SOT_PATH)
    assert _calls_hashlib_sha256(sot_tree), (
        f"{SOT_PATH.relative_to(REPO_ROOT)} no longer calls "
        "'hashlib.sha256(...)'. The SOT helper is the single canonical "
        "hashing site; if hashing moved out, this guard needs an update."
    )
