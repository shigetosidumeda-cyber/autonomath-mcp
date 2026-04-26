"""Tests for L4 query-cache wiring on the top-3 read endpoints (Q4 perf
diff 4 — `analysis_wave18/_q4_perf_diffs_2026-04-25.md`).

Coverage
--------
1. ``GET /v1/programs/search`` — first call MISS, second within TTL HIT,
   row mutation after warming is invisible until the cache row goes stale.
2. ``GET /v1/programs/{unified_id}`` — same MISS / HIT / TTL-expire flow.
3. ``GET /v1/am/tax_incentives`` — same flow against the autonomath router.

Strategy
--------
Each test calls ``invalidate_tool`` to wipe its own L4 family between
phases (preserves cross-test isolation in the session-scoped seeded_db).
TTL expiry is simulated by directly UPDATE-ing ``created_at`` to push the
row past ``ttl_seconds`` rather than time.sleep — fast and deterministic.

The autonomath test skips at module load if ``autonomath.db`` is absent,
matching the convention of ``test_autonomath_tools.py`` so this file stays
green on a CI runner without the 8.29 GB snapshot.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from jpintel_mcp.api.programs import _L4_TOOL_GET, _L4_TOOL_SEARCH
from jpintel_mcp.cache.l4 import (
    canonical_cache_key,
    invalidate_tool,
)

if TYPE_CHECKING:
    from fastapi.testclient import TestClient


_REPO_ROOT = Path(__file__).resolve().parents[1]
_AUTONOMATH_DB = Path(
    os.environ.get("AUTONOMATH_DB_PATH", str(_REPO_ROOT / "autonomath.db"))
)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _force_expire_all(tool: str) -> None:
    """Push every L4 row for ``tool`` past its TTL.

    Uses the same connection helper the cache uses, so JPINTEL_DB_PATH set
    by conftest is honored. Idempotent — if the cache table doesn't exist
    yet (cold first call), the UPDATE silently no-ops.
    """
    from jpintel_mcp.db.session import connect

    conn = connect()
    try:
        try:
            conn.execute(
                # Backdate created_at so created_at + ttl_seconds is firmly
                # in the past (ttl_seconds may be 86400 for default rows;
                # 100 days back guarantees expiry regardless of TTL).
                "UPDATE l4_query_cache "
                "SET created_at = datetime('now', '-100 days') "
                "WHERE tool_name = ?",
                (tool,),
            )
        except sqlite3.OperationalError:
            # Table missing — nothing to expire. Fine.
            pass
    finally:
        conn.close()


def _row_count(tool: str) -> int:
    """Count L4 rows for ``tool``. Returns 0 if the table doesn't exist."""
    from jpintel_mcp.db.session import connect

    conn = connect()
    try:
        try:
            (n,) = conn.execute(
                "SELECT COUNT(*) FROM l4_query_cache WHERE tool_name = ?",
                (tool,),
            ).fetchone()
            return int(n)
        except sqlite3.OperationalError:
            return 0
    finally:
        conn.close()


def _hit_count(tool: str) -> int:
    """Sum hit_count across all L4 rows for ``tool``. 0 on missing table."""
    from jpintel_mcp.db.session import connect

    conn = connect()
    try:
        try:
            (n,) = conn.execute(
                "SELECT COALESCE(SUM(hit_count), 0) "
                "FROM l4_query_cache WHERE tool_name = ?",
                (tool,),
            ).fetchone()
            return int(n)
        except sqlite3.OperationalError:
            return 0
    finally:
        conn.close()


@pytest.fixture(autouse=True)
def _reset_l4_cache(seeded_db: Path):
    """Wipe the L4 families this file owns before/after each test.

    Other test modules don't touch these tool names, so cross-suite
    leakage is one-way (we leave them clean for the next run)."""
    for tool in (
        _L4_TOOL_SEARCH,
        _L4_TOOL_GET,
        "api.am.tax_incentives",
    ):
        try:
            invalidate_tool(tool)
        except sqlite3.OperationalError:
            # Table not yet created on this volume — fine, miss path will
            # self-heal via _l4_get_or_compute_safe.
            pass
    yield
    for tool in (
        _L4_TOOL_SEARCH,
        _L4_TOOL_GET,
        "api.am.tax_incentives",
    ):
        try:
            invalidate_tool(tool)
        except sqlite3.OperationalError:
            pass


# ---------------------------------------------------------------------------
# 1. /v1/programs/search — search Zipf hot path
# ---------------------------------------------------------------------------


def test_programs_search_l4_miss_then_hit(client: "TestClient"):
    """First call seeds the cache; the second call within TTL must HIT.

    We assert via two channels:
      * row_count grows from 0 → 1 after the first call (miss-path INSERT)
      * hit_count grows from 0 → 1 after the second call (hit-path UPDATE)
    """
    # Sanity baseline.
    assert _row_count(_L4_TOOL_SEARCH) == 0

    r1 = client.get("/v1/programs/search", params={"limit": 5})
    assert r1.status_code == 200, r1.text
    body1 = r1.json()
    # One miss recorded (row created, hit_count still 0).
    assert _row_count(_L4_TOOL_SEARCH) == 1
    assert _hit_count(_L4_TOOL_SEARCH) == 0

    r2 = client.get("/v1/programs/search", params={"limit": 5})
    assert r2.status_code == 200, r2.text
    body2 = r2.json()
    # Same payload (deterministic: cache hit returns identical JSON).
    assert body1 == body2
    assert _row_count(_L4_TOOL_SEARCH) == 1
    assert _hit_count(_L4_TOOL_SEARCH) == 1


def test_programs_search_l4_ttl_expire_refreshes(
    client: "TestClient", seeded_db: Path
):
    """After TTL expires, the next call refetches and overwrites the row.

    Concretely: warm the cache, mutate the underlying DB so the recompute
    would yield a different total, expire the row, fire one more request.
    The new response must reflect the mutation."""
    # Warm with a query that matches the seeded tier-S row.
    r1 = client.get(
        "/v1/programs/search", params={"q": "テスト", "limit": 20}
    )
    assert r1.status_code == 200, r1.text
    initial_total = r1.json()["total"]
    assert initial_total >= 1, f"baseline expected ≥1 result, got {initial_total}"
    assert _row_count(_L4_TOOL_SEARCH) == 1

    # Add another tier-S row that matches "テスト" so total goes up by 1.
    from datetime import UTC, datetime

    now_iso = datetime.now(UTC).isoformat()
    c = sqlite3.connect(seeded_db)
    try:
        c.execute(
            """INSERT INTO programs(
                unified_id, primary_name, tier, authority_level,
                program_kind, target_types_json, funding_purpose_json,
                excluded, updated_at
            ) VALUES (?, ?, 'S', '国', '補助金', '[]', '[]', 0, ?)""",
            ("UNI-test-l4-extra", "テスト L4 cache extra row", now_iso),
        )
        c.execute(
            "INSERT INTO programs_fts(unified_id, primary_name, aliases, "
            "enriched_text) VALUES (?, ?, '', ?)",
            ("UNI-test-l4-extra", "テスト L4 cache extra row",
             "テスト L4 cache extra row"),
        )
        c.commit()
    finally:
        c.close()

    try:
        # Within TTL → still see the cached total (cache hit, mutation hidden).
        r2 = client.get(
            "/v1/programs/search", params={"q": "テスト", "limit": 20}
        )
        assert r2.json()["total"] == initial_total
        assert _hit_count(_L4_TOOL_SEARCH) == 1

        # Expire the row → next call must MISS, recompute, and observe the
        # mutation.
        _force_expire_all(_L4_TOOL_SEARCH)
        r3 = client.get(
            "/v1/programs/search", params={"q": "テスト", "limit": 20}
        )
        assert r3.status_code == 200, r3.text
        assert r3.json()["total"] == initial_total + 1, (
            f"expected refresh after TTL expiry: "
            f"{initial_total} -> {initial_total + 1}, got {r3.json()['total']}"
        )
    finally:
        # Restore so other tests sharing the session DB don't observe the
        # extra row. Both the row and the FTS shadow must go.
        c = sqlite3.connect(seeded_db)
        try:
            c.execute(
                "DELETE FROM programs WHERE unified_id = 'UNI-test-l4-extra'"
            )
            c.execute(
                "DELETE FROM programs_fts WHERE unified_id = 'UNI-test-l4-extra'"
            )
            c.commit()
        finally:
            c.close()


# ---------------------------------------------------------------------------
# 2. /v1/programs/{unified_id} — single-row hot path
# ---------------------------------------------------------------------------


def test_programs_get_l4_miss_then_hit(client: "TestClient"):
    assert _row_count(_L4_TOOL_GET) == 0

    r1 = client.get("/v1/programs/UNI-test-s-1")
    assert r1.status_code == 200, r1.text
    body1 = r1.json()
    assert _row_count(_L4_TOOL_GET) == 1
    assert _hit_count(_L4_TOOL_GET) == 0

    r2 = client.get("/v1/programs/UNI-test-s-1")
    assert r2.status_code == 200, r2.text
    body2 = r2.json()
    assert body1 == body2
    assert _row_count(_L4_TOOL_GET) == 1
    assert _hit_count(_L4_TOOL_GET) == 1


def test_programs_get_l4_ttl_expire_refreshes(
    client: "TestClient", seeded_db: Path
):
    """After TTL expiry, a get-by-id picks up DB-side mutations.

    Note: the row→Program in-memory cache (``_PROGRAM_CACHE``) sits below
    L4 and is keyed by (unified_id, source_checksum). The seeded row has
    a NULL checksum, so a primary_name mutation without bumping the
    checksum stays masked unless we explicitly clear that cache too.
    """
    from jpintel_mcp.api.programs import _clear_program_cache

    r1 = client.get("/v1/programs/UNI-test-s-1")
    assert r1.status_code == 200, r1.text
    initial_name = r1.json()["primary_name"]

    # Snapshot for restoration.
    c = sqlite3.connect(seeded_db)
    try:
        c.execute(
            "UPDATE programs SET primary_name = ? WHERE unified_id = ?",
            ("テスト S-tier 補助金 (mutated)", "UNI-test-s-1"),
        )
        c.commit()
    finally:
        c.close()

    try:
        # Within TTL → cache returns the original.
        r2 = client.get("/v1/programs/UNI-test-s-1")
        assert r2.json()["primary_name"] == initial_name

        # Expire L4 AND drop the row-cache so the recompute hits the DB.
        _force_expire_all(_L4_TOOL_GET)
        _clear_program_cache()
        r3 = client.get("/v1/programs/UNI-test-s-1")
        assert r3.status_code == 200, r3.text
        assert r3.json()["primary_name"] == "テスト S-tier 補助金 (mutated)"
    finally:
        c = sqlite3.connect(seeded_db)
        try:
            c.execute(
                "UPDATE programs SET primary_name = ? WHERE unified_id = ?",
                (initial_name, "UNI-test-s-1"),
            )
            c.commit()
        finally:
            c.close()
        _clear_program_cache()


# ---------------------------------------------------------------------------
# 3. /v1/am/tax_incentives — autonomath router
# ---------------------------------------------------------------------------
#
# Skips at module level if autonomath.db is absent (CI without snapshot).
# The endpoint is wired identically to the programs routes; we only verify
# the cache row mechanics, not the SQL semantics (those are covered by
# test_autonomath_tools.py and test_endpoint_smoke.py).


_AUTONOMATH_AVAILABLE = _AUTONOMATH_DB.exists() and os.environ.get(
    "AUTONOMATH_ENABLED", "1"
) not in ("0", "false", "False")

_AM_TAX_TOOL = "api.am.tax_incentives"


@pytest.mark.skipif(
    not _AUTONOMATH_AVAILABLE,
    reason=(
        "autonomath.db not present or AUTONOMATH_ENABLED disabled — skipping "
        "the L4 wire test for /v1/am/tax_incentives."
    ),
)
def test_am_tax_incentives_l4_miss_then_hit(client: "TestClient"):
    """Same MISS → HIT contract on the autonomath router."""
    assert _row_count(_AM_TAX_TOOL) == 0

    r1 = client.get("/v1/am/tax_incentives", params={"limit": 5})
    assert r1.status_code == 200, r1.text
    body1 = r1.json()
    assert _row_count(_AM_TAX_TOOL) == 1
    assert _hit_count(_AM_TAX_TOOL) == 0

    r2 = client.get("/v1/am/tax_incentives", params={"limit": 5})
    assert r2.status_code == 200, r2.text
    body2 = r2.json()
    assert body1 == body2
    assert _row_count(_AM_TAX_TOOL) == 1
    assert _hit_count(_AM_TAX_TOOL) == 1


@pytest.mark.skipif(
    not _AUTONOMATH_AVAILABLE,
    reason="autonomath.db not present — skipping",
)
def test_am_tax_incentives_l4_ttl_expire_refreshes(client: "TestClient"):
    """After TTL expiry the next call MISSes again (row gets overwritten).

    We don't mutate the autonomath.db (read-only artifact). Instead we
    assert the row-count stays 1 (overwrite, not duplicate) and hit_count
    resets to 0 after the expired-row replacement."""
    r1 = client.get("/v1/am/tax_incentives", params={"limit": 5})
    assert r1.status_code == 200, r1.text
    assert _row_count(_AM_TAX_TOOL) == 1

    r2 = client.get("/v1/am/tax_incentives", params={"limit": 5})
    assert r2.status_code == 200, r2.text
    assert _hit_count(_AM_TAX_TOOL) == 1

    _force_expire_all(_AM_TAX_TOOL)
    # The row still exists (sweep_expired isn't run on read), but is stale
    # — next request goes through the miss path and overwrites in place.
    r3 = client.get("/v1/am/tax_incentives", params={"limit": 5})
    assert r3.status_code == 200, r3.text
    assert _row_count(_AM_TAX_TOOL) == 1, (
        "expected INSERT OR REPLACE to overwrite, not duplicate"
    )
    # hit_count was reset by the INSERT OR REPLACE → 0 after the miss path.
    assert _hit_count(_AM_TAX_TOOL) == 0, (
        "INSERT OR REPLACE on stale row must reset hit_count to 0"
    )


# ---------------------------------------------------------------------------
# 4. cache-key includes ctx.tier (poisoning guard)
# ---------------------------------------------------------------------------
#
# Static check: the same (q, fields, …) tuple under two different tiers
# must yield distinct cache keys, otherwise an anon caller could be served
# a payload computed for `paid` and vice versa.


def test_cache_key_includes_ctx_tier_for_search():
    base = {
        "q": "DX",
        "tier": None,
        "prefecture": None,
        "authority_level": None,
        "funding_purpose": None,
        "target_type": None,
        "amount_min": None,
        "amount_max": None,
        "include_excluded": False,
        "limit": 20,
        "offset": 0,
        "fields": "default",
        "include_advisors": False,
    }
    free_key = canonical_cache_key(
        _L4_TOOL_SEARCH, {**base, "ctx_tier": "free"}
    )
    paid_key = canonical_cache_key(
        _L4_TOOL_SEARCH, {**base, "ctx_tier": "paid"}
    )
    assert free_key != paid_key, (
        "ctx.tier must partition the cache key — fields=full payloads "
        "differ between tiers and a shared key would poison both buckets."
    )


def test_cache_key_includes_ctx_tier_for_get():
    base = {"unified_id": "UNI-test-s-1", "fields": "default"}
    free_key = canonical_cache_key(
        _L4_TOOL_GET, {**base, "ctx_tier": "free"}
    )
    paid_key = canonical_cache_key(
        _L4_TOOL_GET, {**base, "ctx_tier": "paid"}
    )
    assert free_key != paid_key


def test_cache_key_includes_ctx_tier_for_am_tax():
    base = {
        "query": "DX",
        "authority": None,
        "industry": None,
        "target_year": None,
        "target_entity": None,
        "natural_query": None,
        "limit": 20,
        "offset": 0,
    }
    free_key = canonical_cache_key(
        _AM_TAX_TOOL, {**base, "ctx_tier": "free"}
    )
    paid_key = canonical_cache_key(
        _AM_TAX_TOOL, {**base, "ctx_tier": "paid"}
    )
    assert free_key != paid_key
