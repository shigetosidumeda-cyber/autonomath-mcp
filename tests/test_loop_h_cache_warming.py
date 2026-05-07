"""Tests for loop_h_cache_warming.

Covers the launch-v1 happy path: a synthetic `usage_events` + seeded
`l4_query_cache` row demonstrate that a hot (endpoint, digest) pair
crosses into the L4 cache as a freshly-warmed row.

Posture: pure SQLite + injected compute closures. No FastAPI app graph,
no Anthropic API calls (per `feedback_autonomath_no_api_use`).
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from jpintel_mcp.cache.l4 import canonical_cache_key, canonical_params
from jpintel_mcp.self_improve import loop_h_cache_warming as loop_h

if TYPE_CHECKING:
    from pathlib import Path


def _short_digest(params: dict) -> str:
    """Mirror api/deps.py::compute_params_digest exactly (16-char prefix)."""
    cleaned = {k: v for k, v in params.items() if v is not None}
    canonical = json.dumps(cleaned, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def _seed_db(db_path: Path) -> None:
    """Build a minimal usage_events + l4_query_cache schema with one hot pair.

    Schema mirrors the production tables enough for `select_hot_queries`
    + `find_l4_params_for_digest` to succeed; we don't need the full FK
    surface.
    """
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(
            """
            CREATE TABLE usage_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key_hash TEXT NOT NULL,
                endpoint TEXT NOT NULL,
                ts TEXT NOT NULL,
                status INTEGER,
                metered INTEGER DEFAULT 0,
                params_digest TEXT,
                latency_ms INTEGER,
                result_count INTEGER
            );
            CREATE TABLE l4_query_cache (
                cache_key TEXT PRIMARY KEY,
                tool_name TEXT NOT NULL,
                params_json TEXT NOT NULL,
                result_json TEXT NOT NULL,
                hit_count INTEGER NOT NULL DEFAULT 0,
                last_hit_at TEXT,
                ttl_seconds INTEGER NOT NULL DEFAULT 86400,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            """
        )

        # Hot params: a programs.search query for "DX" with a tier filter.
        # The digest must be the exact same string log_usage() would produce
        # so select_hot_queries -> find_l4_params_for_digest can round-trip.
        hot_params = {
            "q": "DX",
            "tier": ["S", "A"],
            "prefecture": None,  # None values get dropped from the digest
            "limit": 20,
        }
        digest = _short_digest(hot_params)
        now_iso = datetime.now(UTC).isoformat()

        # Insert 50 hits for the hot digest in the last 24h, plus 1 cold hit
        # for a different digest to confirm we rank by count, not recency.
        for i in range(50):
            ts = (datetime.now(UTC) - timedelta(hours=i % 24)).isoformat()
            conn.execute(
                "INSERT INTO usage_events("
                "key_hash, endpoint, ts, status, metered, params_digest"
                ") VALUES (?, ?, ?, 200, 1, ?)",
                (f"k{i}", "programs.search", ts, digest),
            )
        cold_params = {"q": "GX", "limit": 5}
        cold_digest = _short_digest(cold_params)
        conn.execute(
            "INSERT INTO usage_events("
            "key_hash, endpoint, ts, status, metered, params_digest"
            ") VALUES (?, ?, ?, 200, 1, ?)",
            ("k99", "programs.search", now_iso, cold_digest),
        )

        # Seed l4_query_cache with one STALE row whose params digest matches
        # the hot pair — this is the row find_l4_params_for_digest must
        # locate so warming can recover the canonical params blob without
        # crossing the PII boundary into raw query text.
        tool = "api.programs.search"
        l4_params = dict(hot_params)
        cache_key = canonical_cache_key(tool, l4_params)
        # Backdate created_at by 100 days so _is_fresh_in_db returns False
        # and warm_top_queries runs the compute path.
        stale_iso = (datetime.now(UTC) - timedelta(days=100)).isoformat()
        conn.execute(
            "INSERT INTO l4_query_cache("
            "cache_key, tool_name, params_json, result_json, "
            "hit_count, last_hit_at, ttl_seconds, created_at"
            ") VALUES (?, ?, ?, ?, 0, NULL, 600, ?)",
            (
                cache_key,
                tool,
                canonical_params(l4_params),
                json.dumps({"stale": True}),
                stale_iso,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def test_loop_h_warms_hot_query_into_l4_cache(tmp_path: Path):
    """End-to-end: a hot (endpoint, digest) pair becomes a fresh L4 row.

    Asserts:
      * scanned counts the hot pair (and the cold one),
      * actions_executed >= 1 (the hot pair was warmed),
      * the L4 row's result_json reflects the injected compute output,
      * the warmed row's created_at is fresh (within last 60 seconds),
      * the cache_warming_report.json is written with the expected shape.
    """
    db_path = tmp_path / "jpintel.db"
    _seed_db(db_path)
    out_path = tmp_path / "cache_warming_report.json"

    # Compute closure stand-in: returns a deterministic dict that includes
    # the params so the test can assert the body actually came from compute
    # (not from the seeded stale row).
    def _stub_compute(params: dict) -> dict:
        return {"ok": True, "echoed_q": params.get("q"), "from": "warm"}

    factories = {"api.programs.search": _stub_compute}

    result = loop_h.run(
        dry_run=False,
        window_days=7,
        top_n=10,
        db_path=db_path,
        out_path=out_path,
        compute_factories=factories,
    )

    assert result["loop"] == "loop_h_cache_warming"
    # Two distinct (endpoint, digest) pairs were inserted.
    assert result["scanned"] == 2
    assert result["actions_executed"] >= 1, (
        f"expected at least one warmed row, got {result['actions_executed']}"
    )

    # Verify the warmed row is in the cache with the new payload.
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT result_json, ttl_seconds, created_at FROM l4_query_cache "
            "WHERE tool_name = 'api.programs.search'"
        ).fetchall()
        assert len(rows) >= 1
        # Find the row carrying the injected compute output.
        warmed = [r for r in rows if json.loads(r[0]).get("from") == "warm"]
        assert warmed, "compute output did not reach l4_query_cache"
        result_json, ttl_seconds, created_at = warmed[0]
        body = json.loads(result_json)
        assert body == {"ok": True, "echoed_q": "DX", "from": "warm"}
        # 2x live TTL for programs.search (300s live -> 600s warm).
        assert ttl_seconds == 600
        # created_at is fresh.
        created = datetime.fromisoformat(created_at)
        if created.tzinfo is None:
            created = created.replace(tzinfo=UTC)
        age = (datetime.now(UTC) - created).total_seconds()
        assert age < 60, f"warmed row not fresh: age={age}s"
    finally:
        conn.close()

    # Verify the report file shape.
    assert out_path.exists()
    report = json.loads(out_path.read_text(encoding="utf-8"))
    assert report["window_days"] == 7
    assert report["top_n"] == 10
    assert report["warmed_count"] >= 1
    assert "by_tool" in report
    assert "api.programs.search" in report["by_tool"]
    assert report["by_tool"]["api.programs.search"]["warmed"] >= 1
    # hit_after should be in [0, 1].
    assert 0.0 <= report["hit_after"] <= 1.0


def test_loop_h_dry_run_does_not_mutate(tmp_path: Path):
    """dry_run=True must not write to l4_query_cache or the report file."""
    db_path = tmp_path / "jpintel.db"
    _seed_db(db_path)
    out_path = tmp_path / "cache_warming_report.json"

    def _stub_compute(params: dict) -> dict:
        return {"should_not_be_called": True}

    # Snapshot the stale row's result_json — it must NOT change.
    conn = sqlite3.connect(db_path)
    try:
        (before,) = conn.execute(
            "SELECT result_json FROM l4_query_cache WHERE tool_name = 'api.programs.search'"
        ).fetchone()
    finally:
        conn.close()

    result = loop_h.run(
        dry_run=True,
        db_path=db_path,
        out_path=out_path,
        compute_factories={"api.programs.search": _stub_compute},
    )

    assert result["actions_executed"] == 0
    assert result["actions_proposed"] >= 1  # would warm at least one
    assert not out_path.exists(), "dry_run wrote the report file"

    conn = sqlite3.connect(db_path)
    try:
        (after,) = conn.execute(
            "SELECT result_json FROM l4_query_cache WHERE tool_name = 'api.programs.search'"
        ).fetchone()
    finally:
        conn.close()
    assert before == after, "dry_run mutated l4_query_cache"


def test_loop_h_empty_db_returns_scaffold(tmp_path: Path):
    """Pre-launch: missing DB -> orchestrator-friendly zero dict."""
    out = loop_h.run(
        dry_run=True,
        db_path=tmp_path / "does-not-exist.db",
    )
    assert out == {
        "loop": "loop_h_cache_warming",
        "scanned": 0,
        "actions_proposed": 0,
        "actions_executed": 0,
    }


def test_loop_h_no_factories_returns_scaffold(tmp_path: Path):
    """No compute callbacks injected -> nothing to warm, return zeros."""
    db_path = tmp_path / "jpintel.db"
    _seed_db(db_path)
    out = loop_h.run(
        dry_run=False,
        db_path=db_path,
        compute_factories=None,
    )
    assert out["loop"] == "loop_h_cache_warming"
    assert out["actions_executed"] == 0


def test_compute_factories_module_exposes_three_l4_tools():
    """Wire-up regression guard: the factory module MUST keep all three
    L4-wired tools wired (programs.search / programs.get / am.tax_incentives).

    If a future refactor drops one entry, the orchestrator silently stops
    warming that endpoint's cache, which is invisible until launch traffic
    arrives. Lock the contract here.
    """
    from jpintel_mcp.self_improve._compute_factories import (
        TOOL_AM_TAX_INCENTIVES,
        TOOL_PROGRAMS_GET,
        TOOL_PROGRAMS_SEARCH,
        build_compute_factories,
    )

    factories = build_compute_factories()
    assert set(factories.keys()) == {
        TOOL_PROGRAMS_SEARCH,
        TOOL_PROGRAMS_GET,
        TOOL_AM_TAX_INCENTIVES,
    }, (
        "compute_factories drift: every L4-wired endpoint in api/programs.py "
        "+ api/autonomath.py needs a matching factory here. Update "
        "_ENDPOINT_TO_L4_TOOL in loop_h_cache_warming.py in lockstep."
    )
    # Each entry must be a callable accepting one positional dict.
    for tool_name, factory in factories.items():
        assert callable(factory), f"factory for {tool_name} not callable"


def test_orchestrator_injects_compute_factories_into_loop_h(monkeypatch):
    """Lock-in: scripts/self_improve_orchestrator._run_one MUST pass
    compute_factories when the target is loop_h_cache_warming. Without
    this kwarg the loop short-circuits to scaffold zeros even when there
    is real traffic to warm against.
    """
    import importlib
    import sys
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[1]
    scripts_dir = repo_root / "scripts"
    monkeypatch.syspath_prepend(str(scripts_dir))
    if "self_improve_orchestrator" in sys.modules:
        del sys.modules["self_improve_orchestrator"]
    orch = importlib.import_module("self_improve_orchestrator")

    # Patch the loop_h module's run() to capture kwargs without doing real work.
    captured: dict = {}

    def _spy_run(*, dry_run: bool = True, **kwargs):
        captured["dry_run"] = dry_run
        captured["kwargs"] = kwargs
        return {
            "loop": "loop_h_cache_warming",
            "scanned": 0,
            "actions_proposed": 0,
            "actions_executed": 0,
        }

    loop_h_mod = importlib.import_module("jpintel_mcp.self_improve.loop_h_cache_warming")
    monkeypatch.setattr(loop_h_mod, "run", _spy_run)

    out = orch._run_one("loop_h_cache_warming", dry_run=True)

    assert out["loop"] == "loop_h_cache_warming"
    assert captured["dry_run"] is True
    assert "compute_factories" in captured["kwargs"], (
        "orchestrator._run_one did not inject compute_factories — Loop H "
        "will short-circuit to scaffold zeros even with live traffic"
    )
    factories = captured["kwargs"]["compute_factories"]
    assert isinstance(factories, dict) and len(factories) >= 3
    assert "api.programs.search" in factories
    assert "api.programs.get" in factories
    assert "api.am.tax_incentives" in factories
