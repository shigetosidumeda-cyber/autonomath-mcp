from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
FUNCTIONS_TSCONFIG = REPO_ROOT / "functions" / "tsconfig.json"
FUNCTIONS_PACKAGE = REPO_ROOT / "functions" / "package.json"
FUNCTIONS_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "functions-typecheck.yml"


def test_functions_tsconfig_is_strict_and_covers_pages_functions() -> None:
    config = json.loads(FUNCTIONS_TSCONFIG.read_text(encoding="utf-8"))
    compiler_options = config["compilerOptions"]

    assert compiler_options["strict"] is True
    assert compiler_options["noEmit"] is True
    assert compiler_options["allowImportingTsExtensions"] is True
    assert compiler_options["moduleResolution"] == "Bundler"
    assert "@cloudflare/workers-types" in compiler_options["types"]
    assert "**/*.ts" in config["include"]
    assert "node_modules" in config["exclude"]


def test_functions_package_exposes_typecheck_script() -> None:
    package = json.loads(FUNCTIONS_PACKAGE.read_text(encoding="utf-8"))

    assert package["private"] is True
    assert package["scripts"]["typecheck"] == "tsc --noEmit -p tsconfig.json"
    assert "typescript" in package["devDependencies"]
    assert "@cloudflare/workers-types" in package["devDependencies"]


def test_functions_typecheck_workflow_runs_static_guard_and_tsc() -> None:
    workflow = FUNCTIONS_WORKFLOW.read_text(encoding="utf-8")

    assert "npm ci --prefix functions" in workflow
    assert "npm run --prefix functions typecheck" in workflow
    assert "python tests/test_functions_typecheck.py" in workflow
    assert "functions/package-lock.json" in workflow
    assert "functions/tsconfig.json" in workflow


def main() -> None:
    test_functions_tsconfig_is_strict_and_covers_pages_functions()
    test_functions_package_exposes_typecheck_script()
    test_functions_typecheck_workflow_runs_static_guard_and_tsc()


if __name__ == "__main__":
    main()
