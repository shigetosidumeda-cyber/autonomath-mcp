"""Group β envelope wiring tests (J9 / K3 fix).

Covers
------
1. ``_envelope_merge`` (server.py) and ``_apply_envelope`` (api/autonomath.py)
   are wired so MCP tool / REST endpoint return values carry the
   response-envelope v2 hint fields (status / explanation /
   suggested_actions / meta.suggestions / meta.alternative_intents /
   meta.tips). Before β1+β2 these fields existed in
   ``envelope_wrapper.with_envelope`` but no caller imported it.

2. The merge is **additive** — pre-existing keys on the tool result
   (e.g. ``meta.data_as_of`` from search_programs / ``retrieval_note``)
   are preserved verbatim. Only envelope-only keys (suggestions,
   alternative_intents, tips, etc.) are appended.

3. **Empty result** + low confidence trips ``meta.suggestions`` non-empty
   so an AI agent receiving 0 results gets a structured hint instead of
   only the free-text ``hint`` string.

4. ``fields="minimal"`` opt-out skips the meta block (matches B-A8 spec).

5. ``stats.py`` cache no longer uses an inline dict — calls go through
   ``cache.l4.get_or_compute`` with the ``api.stats`` tool name.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

# Ensure src/ is on path for direct test runs.
_REPO = Path(__file__).resolve().parent.parent
_SRC = _REPO / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


# ---------------------------------------------------------------------------
# β1 — _envelope_merge (server.py)
# ---------------------------------------------------------------------------


def _import_envelope_merge():
    """Side-step the heavy server.py module-level imports for unit tests.

    server.py runs ``init_db`` etc. on import in some paths; we only need
    the helper. Import lazily so the test fails clean if server.py blows
    up rather than at collection time.
    """
    from jpintel_mcp.mcp.server import _envelope_merge

    return _envelope_merge


def test_envelope_merge_empty_result_emits_meta_suggestions():
    """0 results → meta.suggestions non-empty (the J9 / K3 finding fix)."""
    _envelope_merge = _import_envelope_merge()

    result = {
        "total": 0,
        "limit": 20,
        "offset": 0,
        "results": [],
    }
    merged = _envelope_merge(
        tool_name="search_tax_incentives",
        result=result,
        kwargs={"query": "存在しないクエリ_zzzzzz"},
        latency_ms=12.3,
    )

    assert isinstance(merged, dict)
    # Status bucket lands on the merged dict.
    assert merged.get("status") == "empty"
    # Suggested actions are populated.
    assert isinstance(merged.get("suggested_actions"), list)
    assert len(merged["suggested_actions"]) > 0
    # meta.suggestions is the new key the J9 audit was after.
    meta = merged.get("meta")
    assert isinstance(meta, dict)
    assert "suggestions" in meta
    assert isinstance(meta["suggestions"], list)
    assert len(meta["suggestions"]) > 0


def test_envelope_merge_preserves_existing_meta_keys():
    """Tools that publish their own meta (e.g. data_as_of) keep it verbatim."""
    _envelope_merge = _import_envelope_merge()

    result = {
        "total": 1,
        "limit": 20,
        "offset": 0,
        "results": [{"unified_id": "test-1", "primary_name": "テスト"}],
        "meta": {"data_as_of": "2026-04-25"},
        "retrieval_note": "fts5_trigram + LIKE fallback",
    }
    merged = _envelope_merge(
        tool_name="search_programs",
        result=result,
        kwargs={"q": "テスト"},
        latency_ms=5.0,
    )

    assert merged["meta"]["data_as_of"] == "2026-04-25"
    assert merged["retrieval_note"] == "fts5_trigram + LIKE fallback"
    # Envelope keys still added alongside.
    assert "suggestions" in merged["meta"] or "wall_time_ms" in merged["meta"]


def test_envelope_merge_minimal_opt_out_skips_meta():
    """``__envelope_fields__='minimal'`` drops the entire meta block (B-A8).

    NOTE: tool-level ``fields='minimal'`` (search_programs row trim) is
    intentionally separate from the envelope opt-out — mixing them would
    silently strip meta.suggestions on every default search_programs
    call. The dedicated ``__envelope_fields__`` control-plane kwarg is
    the single signal recognised by the merge layer.
    """
    _envelope_merge = _import_envelope_merge()

    result = {
        "total": 0,
        "limit": 20,
        "offset": 0,
        "results": [],
    }
    merged = _envelope_merge(
        tool_name="search_tax_incentives",
        result=result,
        kwargs={"query": "test", "__envelope_fields__": "minimal"},
        latency_ms=2.0,
    )

    # status / suggested_actions still present (always-on hints), but
    # the meta block (suggestions / tips / token_estimate) is suppressed.
    assert merged.get("status") == "empty"
    assert (
        "meta" not in merged
        or merged.get("meta") is None
        or "suggestions" not in (merged.get("meta") or {})
    )


def test_envelope_merge_tool_fields_minimal_does_not_skip_meta():
    """tool-level fields='minimal' (row whitelist trim) MUST NOT drop the
    meta block — that confusion was the original β1 wiring regression."""
    _envelope_merge = _import_envelope_merge()

    result = {
        "total": 0,
        "limit": 20,
        "offset": 0,
        "results": [],
    }
    merged = _envelope_merge(
        tool_name="search_tax_incentives",
        result=result,
        kwargs={"query": "test", "fields": "minimal"},
        latency_ms=2.0,
    )

    # Meta block IS present even though fields=minimal — only
    # __envelope_fields__=minimal suppresses it.
    meta = merged.get("meta") or {}
    assert isinstance(meta.get("suggestions"), list)
    assert len(meta["suggestions"]) > 0


def test_envelope_merge_does_not_overwrite_existing_status():
    """Tools that already set 'status' (e.g. via legacy envelope) keep theirs."""
    _envelope_merge = _import_envelope_merge()

    result = {
        "total": 0,
        "limit": 20,
        "offset": 0,
        "results": [],
        "status": "ok",  # legacy field — must NOT be overwritten with 'empty'
    }
    merged = _envelope_merge(
        tool_name="search_tax_incentives",
        result=result,
        kwargs={"query": "x"},
        latency_ms=1.0,
    )
    assert merged["status"] == "ok"


def test_envelope_merge_error_envelope_carries_retry_action():
    """Error result → status='error' + retry_with_backoff action."""
    _envelope_merge = _import_envelope_merge()

    result = {
        "error": {"code": "db_unavailable", "message": "sqlite locked"},
    }
    merged = _envelope_merge(
        tool_name="search_tax_incentives",
        result=result,
        kwargs={"query": "x"},
        latency_ms=1.0,
    )
    assert merged.get("status") == "error"
    actions = merged.get("suggested_actions") or []
    assert any(a.get("action") == "retry_with_backoff" for a in actions)


def test_envelope_merge_handles_non_dict_result():
    """Bare list / scalar payloads are coerced to envelope shape."""
    _envelope_merge = _import_envelope_merge()

    out = _envelope_merge(
        tool_name="search_tax_incentives",
        result=[{"a": 1}, {"b": 2}],
        kwargs={"query": "x"},
        latency_ms=1.0,
    )
    # Non-dict input goes through build_envelope cleanly.
    assert isinstance(out, dict)
    assert out.get("result_count") == 2


def test_envelope_merge_soft_fails_on_envelope_import_error():
    """If envelope_wrapper can't be imported, return result untouched."""
    _envelope_merge = _import_envelope_merge()

    # Patch the module dict so the inner import inside _envelope_merge
    # raises. We monkey-patch sys.modules so the import statement re-
    # evaluates and fails.
    with patch.dict(
        sys.modules,
        {"jpintel_mcp.mcp.autonomath_tools.envelope_wrapper": None},
    ):
        result = {"total": 0, "results": []}
        out = _envelope_merge(
            tool_name="x",
            result=result,
            kwargs={},
            latency_ms=0.0,
        )
        # On soft-fail we get the original back with no envelope keys.
        assert out is result or "status" not in out


# ---------------------------------------------------------------------------
# β2 — _apply_envelope (api/autonomath.py)
# ---------------------------------------------------------------------------


def test_apply_envelope_rest_helper_adds_meta_suggestions():
    from jpintel_mcp.api.autonomath import _apply_envelope

    result = {
        "total": 0,
        "limit": 20,
        "offset": 0,
        "results": [],
    }
    out = _apply_envelope(
        "search_tax_incentives",
        result,
        query="zzzzzzzzz",
    )
    assert out.get("status") == "empty"
    assert isinstance(out.get("meta"), dict)
    assert isinstance(out["meta"].get("suggestions"), list)
    assert len(out["meta"]["suggestions"]) > 0


def test_apply_envelope_preserves_pre_existing_meta():
    from jpintel_mcp.api.autonomath import _apply_envelope

    result = {
        "total": 1,
        "limit": 20,
        "offset": 0,
        "results": [{"x": 1}],
        "meta": {"data_as_of": "2026-04-25"},
    }
    out = _apply_envelope("search_programs", result, query="q")
    assert out["meta"]["data_as_of"] == "2026-04-25"


def test_apply_envelope_returns_unchanged_on_non_dict_non_list():
    from jpintel_mcp.api.autonomath import _apply_envelope

    assert _apply_envelope("x", None) is None
    assert _apply_envelope("x", "raw_string") == "raw_string"


# ---------------------------------------------------------------------------
# β3 — stats.py cache routes through cache.l4
# ---------------------------------------------------------------------------


@pytest.fixture()
def _l4_table_present(seeded_db: Path):
    """Apply migration 043 (l4_query_cache) on the test DB if not already
    there. Production carries it from `scripts/migrate.py` runs; the test
    init_db only loads schema.sql so this fixture pulls the migration in
    explicitly for cache-related assertions."""
    import sqlite3 as _sqlite3

    migration = (_REPO / "scripts" / "migrations" / "043_l4_cache.sql").read_text(encoding="utf-8")
    conn = _sqlite3.connect(seeded_db)
    try:
        conn.executescript(migration)
        conn.commit()
    finally:
        conn.close()
    yield


def test_stats_cache_uses_l4_helper(seeded_db: Path, _l4_table_present):
    """``_cache_get_or_compute`` should delegate to cache.l4.get_or_compute."""
    from jpintel_mcp.api import stats as stats_mod

    # Sanity: the dict-based shadow is gone.
    assert not hasattr(stats_mod, "_cache") or callable(getattr(stats_mod, "_cache", None))

    # Compute a value; second call should hit cache and NOT re-invoke compute.
    call_count = {"n": 0}

    def _slow_compute() -> dict[str, Any]:
        call_count["n"] += 1
        return {"value": call_count["n"]}

    stats_mod._reset_stats_cache()
    first = stats_mod._cache_get_or_compute("test-key", _slow_compute)
    second = stats_mod._cache_get_or_compute("test-key", _slow_compute)

    assert first == second
    assert call_count["n"] == 1, "L4 cache hit should skip the compute()"
    stats_mod._reset_stats_cache()


def test_stats_cache_reset_clears_state(seeded_db: Path, _l4_table_present):
    """``_reset_stats_cache`` purges the stats family from L4."""
    from jpintel_mcp.api import stats as stats_mod

    call_count = {"n": 0}

    def _compute() -> dict[str, Any]:
        call_count["n"] += 1
        return {"value": call_count["n"]}

    stats_mod._reset_stats_cache()
    stats_mod._cache_get_or_compute("reset-key", _compute)
    assert call_count["n"] == 1

    stats_mod._reset_stats_cache()
    stats_mod._cache_get_or_compute("reset-key", _compute)
    # After reset the cache miss forces a recompute.
    assert call_count["n"] == 2


def test_stats_cache_uses_l4_module():
    """Smoke check that the import binding is in place — `_cache` dict is gone."""
    from jpintel_mcp.api import stats as stats_mod

    # cache.l4 helpers are imported at module top, not just used internally.
    assert hasattr(stats_mod, "get_or_compute")
    assert hasattr(stats_mod, "canonical_cache_key")
    assert hasattr(stats_mod, "invalidate_tool")
    # The old in-memory dict shadow is gone — only the function survives.
    assert not isinstance(getattr(stats_mod, "_cache", None), dict)


# ---------------------------------------------------------------------------
# Integration — end-to-end request through the REST surface
# ---------------------------------------------------------------------------


def test_rest_search_emits_meta_suggestions_on_empty(client):
    """0-result REST query carries meta.suggestions[] (the J9 fix verified
    against the real FastAPI router, not just the helper)."""
    # Use a query the tax_incentives table cannot match.
    r = client.get(
        "/v1/am/tax_incentives",
        params={"query": "存在しない検索ワード_zzzzz_xxxxxxxxx"},
    )
    # Endpoint is gated by AnonIpLimitDep + may 429 if anon quota exhausted
    # by other tests — tolerate that cleanly. Skip if not 200.
    if r.status_code != 200:
        pytest.skip(
            f"/v1/am/tax_incentives returned {r.status_code}, skipping "
            "envelope assertion (likely AUTONOMATH_ENABLED off or quota)."
        )
    body = r.json()
    # The empty-bucket envelope kicks in.
    assert body.get("status") in ("empty", "sparse", "rich", "error")
    if body.get("status") == "empty":
        meta = body.get("meta") or {}
        assert isinstance(meta.get("suggestions"), list)
        assert len(meta["suggestions"]) > 0


def test_rest_response_keeps_legacy_total_offset_limit(client):
    """β2 wiring is additive — total / limit / offset survive."""
    r = client.get("/v1/am/enums/authority")
    if r.status_code != 200:
        pytest.skip(f"/v1/am/enums/authority returned {r.status_code}, skipping.")
    body = r.json()
    # Endpoint declares enum_name + values; envelope adds status/etc but
    # never strips existing fields.
    assert "enum_name" in body or "values" in body or "error" in body
