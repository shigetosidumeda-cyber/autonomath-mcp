"""
CI: measure esbuild bundle sizes for Cloudflare Pages edge handlers.

CF Pages Functions enforce a 1 MiB compressed worker limit (1,000,000 bytes
plain budget here as a conservative pre-flight). Each non-helper file in
functions/ is bundled in isolation; helper modules prefixed with `_` are not
themselves Pages routes and are skipped (they are inlined via the bundler when
imported by route handlers).

Assertions:
  * size < 1_000_000  -> hard fail (exceeds CF Pages limit)
  * size > 500_000    -> soft warn via pytest.warns-style RuntimeWarning print
                         (50% canary threshold, does not fail the suite)
"""

from __future__ import annotations

import os
import shutil
import subprocess
import warnings
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
FUNCTIONS_DIR = REPO_ROOT / "functions"

CF_PAGES_BYTE_LIMIT = 1_000_000  # CF Pages worker hard ceiling
WARN_THRESHOLD = 500_000  # 50% canary

# Skip cache: discover esbuild availability once per session.
_NPX = shutil.which("npx")


def _esbuild_available() -> bool:
    if _NPX is None:
        return False
    try:
        out = subprocess.run(
            [_NPX, "--yes", "esbuild", "--version"],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=str(REPO_ROOT),
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return False
    return out.returncode == 0 and out.stdout.strip() != ""


def _enumerate_handlers() -> list[Path]:
    """Every functions/**/*.ts that is itself a Pages route.

    Excludes helper modules whose basename begins with `_` (no own bundle).
    """
    if not FUNCTIONS_DIR.exists():
        return []
    results: list[Path] = []
    for path in FUNCTIONS_DIR.rglob("*.ts"):
        if not path.is_file():
            continue
        if "node_modules" in path.parts:
            continue
        if path.name.startswith("_"):
            continue
        results.append(path)
    results.sort()
    return results


_HANDLERS = _enumerate_handlers()


# Parametrized so each handler shows up as its own test id; one failure does
# not mask others.
@pytest.mark.skipif(
    not _esbuild_available(), reason="esbuild / npx unavailable in this env"
)
@pytest.mark.skipif(not _HANDLERS, reason="no functions/*.ts handlers found")
@pytest.mark.parametrize(
    "handler",
    _HANDLERS,
    ids=[str(p.relative_to(REPO_ROOT)) for p in _HANDLERS],
)
def test_edge_handler_bundle_size_under_1mb(handler: Path, tmp_path: Path) -> None:
    rel = handler.relative_to(REPO_ROOT)
    # Sanitize output filename: replace path separators + special chars.
    slug = (
        str(rel)
        .replace(os.sep, "__")
        .replace("[", "_")
        .replace("]", "_")
        .replace(".ts", "")
    )
    outfile = tmp_path / f"edge_{slug}.js"
    cmd = [
        _NPX,
        "--yes",
        "esbuild",
        str(handler),
        "--bundle",
        "--format=esm",
        "--platform=browser",
        f"--outfile={outfile}",
        "--log-level=error",
    ]
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=180,
        cwd=str(REPO_ROOT),
    )
    assert proc.returncode == 0, (
        f"esbuild failed for {rel}:\nSTDOUT={proc.stdout}\nSTDERR={proc.stderr}"
    )
    assert outfile.exists(), f"esbuild produced no output for {rel}"

    size = outfile.stat().st_size

    if size > WARN_THRESHOLD:
        warnings.warn(
            f"edge bundle {rel} is {size:,} B (> {WARN_THRESHOLD:,} canary)",
            RuntimeWarning,
            stacklevel=2,
        )

    assert size < CF_PAGES_BYTE_LIMIT, (
        f"edge bundle {rel} = {size:,} B exceeds CF Pages limit "
        f"{CF_PAGES_BYTE_LIMIT:,} B"
    )
