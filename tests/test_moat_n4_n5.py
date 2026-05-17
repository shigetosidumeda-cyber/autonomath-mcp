"""Smoke tests for MOAT N4 (window directory) + N5 (synonym dictionary).

Asserts:

* am_window_directory has >=4,000 primary-source rows post-load.
* am_alias has >=420,000 rows post-N5 ingest.
* 3 MCP tools registered: resolve_alias / find_filing_window / list_windows.

NO LLM. NO HTTP. Read-only over autonomath.db.
"""

from __future__ import annotations

import asyncio
import os
import sqlite3
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
AUTONOMATH_DB = REPO_ROOT / "autonomath.db"


def _connect_ro() -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{AUTONOMATH_DB}?mode=ro", uri=True, timeout=10.0)
    conn.row_factory = sqlite3.Row
    return conn


def _impl(tool: Any) -> Any:
    """Return the underlying function for an mcp.tool-decorated callable.

    FastMCP wraps functions; ``.fn`` / ``.func`` / ``._fn`` exposes the
    original. Fall back to the object itself if neither attribute exists.
    """
    for attr in ("fn", "func", "_fn"):
        inner = getattr(tool, attr, None)
        if callable(inner):
            return inner
    return tool


@pytest.fixture(scope="module")
def conn() -> sqlite3.Connection:
    if not AUTONOMATH_DB.exists():
        pytest.skip(f"autonomath.db not found at {AUTONOMATH_DB}")
    c = _connect_ro()
    yield c
    c.close()


def test_am_window_directory_row_count(conn: sqlite3.Connection) -> None:
    n = conn.execute("SELECT COUNT(*) FROM am_window_directory").fetchone()[0]
    assert n >= 4000, f"am_window_directory has only {n} rows, expected >=4000"


def test_am_window_directory_jurisdiction_breakdown(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        "SELECT jurisdiction_kind, COUNT(*) FROM am_window_directory GROUP BY jurisdiction_kind"
    ).fetchall()
    counts = {r[0]: r[1] for r in rows}
    assert counts.get("legal_affairs_bureau", 0) >= 40, counts
    assert counts.get("tax_office", 0) >= 400, counts
    assert counts.get("prefecture", 0) >= 47, counts
    assert counts.get("municipality", 0) >= 1500, counts
    assert counts.get("jfc_branch", 0) >= 100, counts
    assert counts.get("shinkin", 0) >= 50, counts


def test_am_window_directory_source_urls_primary_only(conn: sqlite3.Connection) -> None:
    aggregators = (
        "mapfan",
        "navitime",
        "itp.ne.jp",
        "tabelog",
        "townpages",
        "i-town",
        "ekiten",
        "biz.stayway",
        "hojyokin-portal",
        "noukaweb",
    )
    for agg in aggregators:
        n = conn.execute(
            "SELECT COUNT(*) FROM am_window_directory WHERE source_url LIKE ?",
            (f"%{agg}%",),
        ).fetchone()[0]
        assert n == 0, f"aggregator {agg!r} leaked ({n} rows)"


def test_am_window_directory_unique_window_ids(conn: sqlite3.Connection) -> None:
    n_total = conn.execute("SELECT COUNT(*) FROM am_window_directory").fetchone()[0]
    n_unique = conn.execute("SELECT COUNT(DISTINCT window_id) FROM am_window_directory").fetchone()[
        0
    ]
    assert n_total == n_unique, f"{n_total - n_unique} duplicate window_ids"


def test_am_alias_post_n5_row_count(conn: sqlite3.Connection) -> None:
    n = conn.execute("SELECT COUNT(*) FROM am_alias").fetchone()[0]
    assert n >= 420000, f"am_alias has only {n} rows, expected >=420K"


def test_am_alias_kind_distribution(conn: sqlite3.Connection) -> None:
    rows = conn.execute("SELECT alias_kind, COUNT(*) FROM am_alias GROUP BY alias_kind").fetchall()
    kinds = {r[0]: r[1] for r in rows}
    assert kinds.get("canonical", 0) > 0, kinds
    assert kinds.get("abbreviation", 0) > 0, kinds


def test_mcp_tools_registered() -> None:
    os.environ.setdefault("AUTONOMATH_ENABLED", "1")
    os.environ.setdefault("JPCITE_MOAT_LANES_ENABLED", "1")

    from jpintel_mcp.mcp import moat_lane_tools  # noqa: F401
    from jpintel_mcp.mcp.server import mcp

    async def _run() -> list[str]:
        tools = await mcp.list_tools()
        return [t.name for t in tools]

    names = asyncio.run(_run())
    for tool in ("resolve_alias", "find_filing_window", "list_windows"):
        assert tool in names, f"{tool!r} missing from mcp.list_tools()"


def test_resolve_alias_smoke() -> None:
    if not AUTONOMATH_DB.exists():
        pytest.skip("autonomath.db not present")
    from jpintel_mcp.mcp.moat_lane_tools.moat_n5_synonym import resolve_alias

    fn = _impl(resolve_alias)
    with _connect_ro() as c:
        row = c.execute(
            "SELECT alias FROM am_alias WHERE alias_kind='canonical' LIMIT 1"
        ).fetchone()
    if row is None:
        pytest.skip("no canonical alias rows yet")
    alias = row[0]
    result = fn(alias, "all")
    assert "results" in result
    assert isinstance(result["results"], list)
    assert result["no_llm"] is True
    assert "elapsed_ms" in result


def test_list_windows_smoke() -> None:
    if not AUTONOMATH_DB.exists():
        pytest.skip("autonomath.db not present")
    from jpintel_mcp.mcp.moat_lane_tools.moat_n4_window import list_windows

    fn = _impl(list_windows)
    out = fn(jurisdiction_kind="tax_office", limit=5)
    assert out.get("jurisdiction_kind") == "tax_office"
    assert out.get("returned", 0) > 0
    assert out.get("no_llm") is True


def test_list_windows_with_region_filter() -> None:
    if not AUTONOMATH_DB.exists():
        pytest.skip("autonomath.db not present")
    from jpintel_mcp.mcp.moat_lane_tools.moat_n4_window import list_windows

    fn = _impl(list_windows)
    out = fn(jurisdiction_kind="tax_office", region_code="13000", limit=10)
    assert out.get("region_code") == "13000"


def test_find_filing_window_unknown_houjin() -> None:
    if not AUTONOMATH_DB.exists():
        pytest.skip("autonomath.db not present")
    from jpintel_mcp.mcp.moat_lane_tools.moat_n4_window import find_filing_window

    fn = _impl(find_filing_window)
    out = fn(program_id="tax", houjin_bangou="9999999999999")
    assert "matches" in out
    assert out.get("no_llm") is True
    assert "_disclaimer" in out


def test_find_filing_window_invalid_kind() -> None:
    from jpintel_mcp.mcp.moat_lane_tools.moat_n4_window import find_filing_window

    fn = _impl(find_filing_window)
    out = fn(program_id="nonexistent_kind_xyz", houjin_bangou="1234567890123")
    assert "error" in out
