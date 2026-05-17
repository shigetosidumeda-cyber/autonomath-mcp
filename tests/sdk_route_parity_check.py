"""SDK ↔ FastAPI route-parity check (Harness H6, 2026-05-17).

Parses the TypeScript reference-agent SDK at ``sdk/agents/src/`` for every
``/v1/...`` path it issues, and asserts each of those paths is a subset of
the live FastAPI route table.

Contract:
    SDK ⊆ FastAPI  (every path the SDK can call MUST exist on the server).

The check is regex-based so it does not require Node / tsc to be installed
on the runner. It tolerates template-literal interpolation
(``${encodeURIComponent(...)}``) by collapsing to a FastAPI-style
``{placeholder}`` segment before lookup.

Why this lives under ``tests/`` even though it's pytest-style:
    The H6 plan asked for ``tests/sdk_route_parity_check.py`` specifically.
    It's wired into the default pytest pickup via the ``tests/`` collection
    glob and runs in CI alongside the rest of the suite.

Run locally:
    .venv/bin/pytest tests/sdk_route_parity_check.py -v
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterable

REPO_ROOT = Path(__file__).resolve().parents[1]
SDK_ROOT = REPO_ROOT / "sdk" / "agents" / "src"

# Files we audit. The SDK is intentionally small, so an explicit list keeps the
# parity check honest: any new SDK surface must be added here, and that's where
# you should be looking when a 404 hits production.
SDK_FILES: tuple[Path, ...] = (
    SDK_ROOT / "lib" / "jpcite_client.ts",
    SDK_ROOT / "agents" / "subsidy_match.ts",
    SDK_ROOT / "agents" / "due_diligence.ts",
    SDK_ROOT / "agents" / "kessan_brief.ts",
    SDK_ROOT / "agents" / "invoice_check.ts",
    SDK_ROOT / "agents" / "law_amendment_watch.ts",
)

# Only lines that look like real fetch calls are interesting. Doc-block
# references (`* GET /v1/...`) and migration-comment references
# (`// Route migrated ... /v1/am/houjin/...`) are filtered out to avoid
# false positives when the comment mentions the legacy path it deprecates.
_FETCH_CALL_RE = re.compile(
    r"""
    (?P<prefix>
        # Inside a string/backtick literal preceded by a fetch-like context.
        fetch\s*<[^>]*>?\s*\(\s*\"(?:GET|POST|PUT|PATCH|DELETE)\"\s*,\s*  # client.fetch("METHOD", "path"...)
      | fetch\s*\(\s*\"(?:GET|POST|PUT|PATCH|DELETE)\"\s*,\s*               # rest.fetch("METHOD", "path"...)
      | const\s+path\s*=\s*                                                  # const path = `/v1/...`
    )
    [`\"]                                                                    # opening backtick or quote
    (?P<path>/v1/[^`\"\s\?]+)                                                # the path body up to ? or ` or "
    """,
    re.VERBOSE,
)

# FastAPI side. We don't import main.py at module-import time (it pulls the
# 9 GB autonomath.db on boot); instead we walk the api/ tree and scrape the
# router prefix + decorator suffix the same way the OpenAPI export does.
API_DIR = REPO_ROOT / "src" / "jpintel_mcp" / "api"

_PREFIX_RE = re.compile(
    r"""APIRouter\s*\(\s*prefix\s*=\s*['\"](?P<prefix>/[^'\"]+)['\"]""",
    re.VERBOSE,
)
_ROUTE_DECORATOR_RE = re.compile(
    r"""
    @(?:[A-Za-z_][A-Za-z0-9_]*_router|router|app)
    \.(?:get|post|put|patch|delete)
    \s*\(\s*       # decorator open paren, optional whitespace
    (?:\#[^\n]*\n\s*)*   # tolerate a stray comment line between ( and the path arg
    ['\"]
    (?P<suffix>[^'\"]*)
    ['\"]
    """,
    re.VERBOSE | re.DOTALL,
)


def _normalize(path: str) -> str:
    """Collapse JS template interpolation to a FastAPI-style ``{x}`` segment.

    Examples:
        ``/v1/houjin/${encodeURIComponent(houjinBangou)}/360`` →
            ``/v1/houjin/{x}/360``
        ``/v1/am/recommend`` → ``/v1/am/recommend``
    """

    # Replace ``${...}`` interpolation with a single placeholder.
    path = re.sub(r"\$\{[^}]+\}", "{x}", path)
    # Strip a trailing query-string placeholder that the SDK appends via
    # URLSearchParams (``?${qs.toString()}``) — the FastAPI route table is
    # keyed on the pre-query path.
    path = path.split("?", 1)[0]
    # FastAPI uses ``{bangou}``-style — normalize to a single placeholder name
    # so we can compare by structure, not name.
    path = re.sub(r"\{[^}]+\}", "{x}", path)
    return path.rstrip("/")


def _extract_sdk_paths(file: Path) -> set[str]:
    """Return every ``/v1/...`` path the SDK file calls into."""

    src = file.read_text(encoding="utf-8")
    found: set[str] = set()
    for line in src.splitlines():
        # Skip pure comment lines — they often mention legacy / deprecated paths.
        stripped = line.lstrip()
        if stripped.startswith(("//", "*", "/*")):
            continue
        for match in _FETCH_CALL_RE.finditer(line):
            found.add(_normalize(match.group("path")))
    return found


def _extract_fastapi_routes() -> set[str]:
    """Walk ``src/jpintel_mcp/api/*.py`` and collect ``{prefix}{suffix}`` paths.

    This deliberately does NOT import the FastAPI app — startup pulls the
    9 GB autonomath.db and would make the test untenable on CI. Instead we
    rely on the static router declarations, which is what the OpenAPI
    exporter uses too.
    """

    routes: set[str] = set()
    for py in API_DIR.glob("*.py"):
        src = py.read_text(encoding="utf-8")
        prefixes = [m.group("prefix").rstrip("/") for m in _PREFIX_RE.finditer(src)]
        if not prefixes:
            # Some files declare `app.get(...)` directly; fall back to ""
            prefixes = [""]
        suffixes = [m.group("suffix") for m in _ROUTE_DECORATOR_RE.finditer(src)]
        for prefix in prefixes:
            for suffix in suffixes:
                full = (prefix + ("/" + suffix.lstrip("/") if suffix else "")).rstrip("/")
                if full.startswith("/v1/"):
                    routes.add(_normalize(full))
    return routes


def _iter_sdk_paths() -> Iterable[tuple[Path, str]]:
    """Flatten (file, path) tuples for parametrization."""

    for f in SDK_FILES:
        if not f.exists():
            continue
        for p in _extract_sdk_paths(f):
            yield (f, p)


def test_fastapi_route_extraction_is_nonempty() -> None:
    """Sanity guard: if route extraction yields 0, the regex is broken."""

    routes = _extract_fastapi_routes()
    assert len(routes) > 50, (
        f"FastAPI route extraction collected only {len(routes)} routes; "
        f"the regex must be broken (production has 300+ /v1 paths)."
    )


def test_sdk_files_exist() -> None:
    """All audited SDK files must exist; missing files would silently pass."""

    missing = [str(f.relative_to(REPO_ROOT)) for f in SDK_FILES if not f.exists()]
    assert not missing, f"Missing SDK files: {missing}"


@pytest.mark.parametrize(
    ("sdk_file", "sdk_path"),
    list(_iter_sdk_paths()),
    ids=lambda x: x if isinstance(x, str) else str(x).rsplit("/", 1)[-1],
)
def test_sdk_path_in_fastapi(sdk_file: Path, sdk_path: str) -> None:
    """Every SDK path MUST be a subset of the FastAPI route table.

    Failure modes:
        - SDK references a legacy / removed path → fix the SDK.
        - FastAPI route was renamed → fix the SDK (the server is the SOT).
        - New SDK surface added without server-side route → land the route first.
    """

    routes = _extract_fastapi_routes()
    rel = sdk_file.relative_to(REPO_ROOT)
    assert sdk_path in routes, (
        f"SDK ({rel}) calls {sdk_path!r} but no matching FastAPI route exists.\n"
        f"FastAPI route count: {len(routes)}.\n"
        f"Sample routes (sorted, 10): "
        f"{sorted([r for r in routes if r.startswith(sdk_path[:12])])[:10]}"
    )
