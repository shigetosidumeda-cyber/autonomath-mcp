"""Targeted regression tests for the committed OpenAPI export."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_openapi_export_matches_committed_spec(tmp_path: Path) -> None:
    out = tmp_path / "openapi.json"
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"

    subprocess.run(
        [sys.executable, "scripts/export_openapi.py", "--out", str(out)],
        cwd=REPO_ROOT,
        env=env,
        check=True,
        text=True,
        capture_output=True,
    )

    assert out.read_text(encoding="utf-8") == (
        REPO_ROOT / "docs" / "openapi" / "v1.json"
    ).read_text(encoding="utf-8")


def test_openapi_version_matches_pyproject() -> None:
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    expected = pyproject["project"]["version"]
    schema = json.loads((REPO_ROOT / "docs" / "openapi" / "v1.json").read_text(encoding="utf-8"))

    assert schema["info"]["version"] == expected
