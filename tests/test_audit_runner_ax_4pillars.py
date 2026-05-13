"""Tests for ``scripts/ops/audit_runner_ax_4pillars.py`` Access pillar.

Born from E12: the Access pillar's ``scoped_api_token`` cell originally
grep-counted ``X-API-Key`` / ``jc_`` string occurrences and awarded 12/12
even when the ``require_scope()`` helper had zero external callers.

These tests synthesize fake source trees so the audit logic can be
exercised in isolation:

  - 0 callers   -> cell WARN (score 0)
  - 4 callers   -> cell OK   (score 2.0 toward Access pillar)
  - 3 callers   -> cell WARN (below the 4-scope threshold)

They guard the helper directly (``_count_require_scope_callers``) so the
test is hermetic — no dependency on the real repo's evolving route layout.
A separate ``--dry-run`` smoke test exercises the new CLI surface.
"""

from __future__ import annotations

import importlib
import importlib.util
import pathlib
import subprocess
import sys
import textwrap

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
AUDIT_SCRIPT = REPO_ROOT / "scripts" / "ops" / "audit_runner_ax_4pillars.py"


def _load_audit_module():
    """Load the audit script as a module for direct helper testing."""
    mod_name = "audit_runner_ax_4pillars_undertest"
    spec = importlib.util.spec_from_file_location(mod_name, AUDIT_SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


def _write_api_keys_helper(api_root: pathlib.Path) -> None:
    """Synthesize the defining module that should be excluded from callers."""
    me_dir = api_root / "me"
    me_dir.mkdir(parents=True, exist_ok=True)
    (me_dir / "__init__.py").write_text("", encoding="utf-8")
    # The defining module — must NOT be counted as a caller even though
    # it both "imports" the name (it defines it) and uses Depends(...)
    # in its own docstring example.
    (me_dir / "api_keys.py").write_text(
        textwrap.dedent(
            '''
            """Scope helper home module."""
            from fastapi import Depends

            def require_scope(scope):
                def _check():
                    pass
                # Docstring example: Depends(require_scope("write:webhooks"))
                return Depends(_check)
            '''
        ).strip()
        + "\n",
        encoding="utf-8",
    )


def _write_caller(api_root: pathlib.Path, name: str, scope: str) -> None:
    """Synthesize a route file that imports + applies ``require_scope``."""
    (api_root / f"{name}.py").write_text(
        textwrap.dedent(
            f'''
            """Synthesized route file: {name}."""
            from fastapi import APIRouter, Depends
            from .me.api_keys import require_scope

            router = APIRouter()

            @router.get(
                "/v1/{name}",
                dependencies=[Depends(require_scope("{scope}"))],
            )
            def handler() -> dict:
                return {{"ok": True}}
            '''
        ).strip()
        + "\n",
        encoding="utf-8",
    )


def _write_red_herring(api_root: pathlib.Path) -> None:
    """A file that mentions the literals but does NOT call the helper.

    Mirrors the E12 root cause — strings like ``X-API-Key`` / ``jc_`` /
    ``require_scope`` appear in comments, docstrings, or unrelated code
    but no ``Depends(require_scope(...))`` is actually wired. The audit
    must NOT count these as callers.
    """
    (api_root / "red_herring.py").write_text(
        textwrap.dedent(
            '''
            """A file mentioning the literals but not wiring the helper.

            X-API-Key with the jc_ prefix is the scope-bearing token.
            See `require_scope` in api.me.api_keys for the helper.
            """
            from fastapi import APIRouter
            router = APIRouter()

            @router.get("/v1/info")
            def info() -> dict:
                return {"prefix": "jc_", "header": "X-API-Key"}
            '''
        ).strip()
        + "\n",
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# _count_require_scope_callers — direct helper tests
# ---------------------------------------------------------------------------


def test_zero_callers_warns(tmp_path: pathlib.Path) -> None:
    """0 external callers — cell must WARN."""
    mod = _load_audit_module()
    api_root = tmp_path / "api"
    api_root.mkdir()
    _write_api_keys_helper(api_root)
    _write_red_herring(api_root)
    count, paths = mod._count_require_scope_callers(api_root)
    assert count == 0, f"expected 0 callers, got {count} ({paths})"
    assert paths == []


def test_four_callers_ok(tmp_path: pathlib.Path) -> None:
    """4 callers (one per CANONICAL_SCOPES entry) — cell must OK."""
    mod = _load_audit_module()
    api_root = tmp_path / "api"
    api_root.mkdir()
    _write_api_keys_helper(api_root)
    _write_caller(api_root, "programs", "read:programs")
    _write_caller(api_root, "cases", "read:cases")
    _write_caller(api_root, "webhooks", "write:webhooks")
    _write_caller(api_root, "billing", "admin:billing")
    count, paths = mod._count_require_scope_callers(api_root)
    assert count == mod.REQUIRE_SCOPE_MIN_CALLERS, (
        f"expected {mod.REQUIRE_SCOPE_MIN_CALLERS} callers, got {count} ({paths})"
    )
    # The defining module must not appear in the caller list.
    assert all("me/api_keys.py" not in p for p in paths), paths


def test_three_callers_below_threshold(tmp_path: pathlib.Path) -> None:
    """3 callers — below the 4-scope threshold, cell still WARNs."""
    mod = _load_audit_module()
    api_root = tmp_path / "api"
    api_root.mkdir()
    _write_api_keys_helper(api_root)
    _write_caller(api_root, "programs", "read:programs")
    _write_caller(api_root, "cases", "read:cases")
    _write_caller(api_root, "webhooks", "write:webhooks")
    count, _ = mod._count_require_scope_callers(api_root)
    assert count == 3
    assert count < mod.REQUIRE_SCOPE_MIN_CALLERS


def test_import_only_not_counted(tmp_path: pathlib.Path) -> None:
    """A file that imports but never wires Depends(require_scope(...))
    must NOT count.

    Mirrors a refactor footgun where a route stops applying the helper
    but leaves the import line in place — the original grep would still
    pass, but the AST check requires both halves of the contract.
    """
    mod = _load_audit_module()
    api_root = tmp_path / "api"
    api_root.mkdir()
    _write_api_keys_helper(api_root)
    (api_root / "imports_but_does_not_apply.py").write_text(
        textwrap.dedent(
            '''
            """Imports require_scope but never wires it."""
            from .me.api_keys import require_scope  # noqa: F401
            from fastapi import APIRouter
            router = APIRouter()

            @router.get("/v1/imports_only")
            def handler() -> dict:
                return {"ok": True}
            '''
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    count, paths = mod._count_require_scope_callers(api_root)
    assert count == 0, f"import-only file leaked into callers: {paths}"


# ---------------------------------------------------------------------------
# CLI surface tests
# ---------------------------------------------------------------------------


def test_dry_run_writes_no_files(tmp_path: pathlib.Path) -> None:
    """--dry-run prints summary but creates NO output files."""
    out_md = tmp_path / "should_not_exist.md"
    out_json = tmp_path / "should_not_exist.json"
    out_site_json = tmp_path / "should_not_exist_site.json"
    result = subprocess.run(
        [
            sys.executable,
            str(AUDIT_SCRIPT),
            "--dry-run",
            "--out",
            str(out_md),
            "--out-json",
            str(out_json),
            "--out-site-json",
            str(out_site_json),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "AX 4 Pillars total=" in result.stdout, result.stdout
    assert not out_md.exists(), f"--dry-run created {out_md}"
    assert not out_json.exists(), f"--dry-run created {out_json}"
    assert not out_site_json.exists(), f"--dry-run created {out_site_json}"


def test_missing_live_captcha_probe_fails_closed(monkeypatch) -> None:
    """The CAPTCHA cell must not pass when live probe data is missing."""
    mod = _load_audit_module()
    monkeypatch.setattr(mod, "_http_probe", lambda _url: (False, "probe-error: timeout"))

    access = mod.access_pillar()
    captcha = next(check for check in access.checks if check.name == "no_captcha_on_api")

    assert captcha.passed is False
    assert "live probe unavailable" in captcha.missing


def test_out_required_without_dry_run() -> None:
    """Omitting both --out and --dry-run is an argparse error."""
    result = subprocess.run(
        [sys.executable, str(AUDIT_SCRIPT)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "--out" in result.stderr or "--out" in result.stdout


# ---------------------------------------------------------------------------
# Real-repo integration — pins the post-E12 expected state.
# ---------------------------------------------------------------------------


def test_real_repo_access_pillar_passes_after_callers_land(tmp_path: pathlib.Path) -> None:
    """Against the live repo, scoped_api_token must be route-wired.

    This regression test keeps the E12 guard honest after the W17/H1 fix:
    Access may score 12/12 only when at least four real route files import
    and apply ``Depends(require_scope(...))``.
    """
    import json

    json_path = tmp_path / "audit.json"
    md_path = tmp_path / "audit.md"
    site_json_path = tmp_path / "site_audit.json"
    subprocess.run(
        [
            sys.executable,
            str(AUDIT_SCRIPT),
            "--out",
            str(md_path),
            "--out-json",
            str(json_path),
            "--out-site-json",
            str(site_json_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    audit = json.loads(json_path.read_text(encoding="utf-8"))
    access = audit["pillars"]["Access"]
    assert access["score"] == 12.0
    assert not any("scoped_api_token" in m for m in access["missing_items"])
    assert any("scoped_api_token" in e for e in access["evidence"])
    caller_count, paths = _load_audit_module()._count_require_scope_callers(
        REPO_ROOT / "src" / "jpintel_mcp" / "api"
    )
    assert caller_count >= 4, paths
