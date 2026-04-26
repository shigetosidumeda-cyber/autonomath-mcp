"""Loop H: Zipf analysis -> top-query pre-compute (L4 cache warming).

Cadence: daily (03:30 JST — off-peak)
Inputs:
    * `usage_events` (last 7 days) — production endpoint hits, joined on
      `(endpoint, params_digest)` to identify the Zipf head. The digest is
      a 16-char SHA-256 prefix written by `compute_params_digest` for the
      whitelist-only endpoints (deps.py::_PARAMS_DIGEST_WHITELIST). We
      DO NOT read raw query text — INV-21 PII boundary stays intact: the
      digest gives us "two requests were identical" without telling us
      what they were. The latest matching `l4_query_cache.params_json`
      row carries the canonical params payload we need to fire a fresh
      compute.
    * `l4_query_cache` — the on-disk L4 store. We probe each candidate
      digest's params here to (a) skip rows that are already fresh and
      (b) recover the canonical params blob for warming.
Outputs:
    * In-place upserts into `l4_query_cache` — same path as
      `cache.l4.get_or_compute`, with a longer TTL (default 2x the
      live-call TTL — 24h base for warm rows, vs. the per-tool live
      defaults of 5min..1h). Warmed rows survive the off-peak window so
      the next day's prime-time hits land on a hot cache.
    * `data/cache_warming_report.json` — per-tool breakdown of warmed /
      already-fresh / skipped counts plus the projected hit-rate lift
      (miss_before / hit_after) for the operator dashboard.

Cost ceiling: ~10 CPU minutes / day, ≤ 1M usage_events row scans,
              0 external API calls, 0 LLM calls (CONSTITUTION 13.2).

Method (T+30d, plain SQL + internal compute):
  1. SELECT endpoint, params_digest, COUNT(*) FROM usage_events
     WHERE ts >= now-7d AND endpoint IN (warmable_endpoints)
       AND params_digest IS NOT NULL
     GROUP BY endpoint, params_digest
     ORDER BY 3 DESC LIMIT N (default 100).
  2. For each (endpoint, digest):
       a. Look up the L4 tool name via `_ENDPOINT_TO_L4_TOOL`.
       b. Find the most recent `l4_query_cache` row whose params_json
          would digest back to the same digest. If none, the digest
          predates L4 wiring — skip (we can't reconstruct params from
          the digest alone, by design).
       c. Check freshness: if the row is still fresh, count as
          `already_fresh` and move on (no work needed).
       d. Otherwise, decode `params_json`, run `compute()` via the
          per-endpoint compute factory, and `INSERT OR REPLACE` with
          ttl = 2x the per-endpoint live default (so warmed rows survive
          longer than naturally-cached ones; this is the warming budget).
  3. Emit `data/cache_warming_report.json`:
        {
          "generated_at": ISO,
          "window_days": 7,
          "top_n": 100,
          "warmed_count": int,
          "already_fresh_count": int,
          "skipped_count": int,
          "miss_before": float,    -- baseline cache-miss rate prior to warming
          "hit_after": float,      -- projected hit rate after warming
          "by_tool": {tool_name: {warmed, already_fresh, skipped}, ...}
        }

LLM use: NONE. Pure SQLite + internal compute callbacks.

Cost / billing posture (project_autonomath_business_model):
    * ¥3/req metered pricing applies to LIVE customer requests only.
    * Warming runs internally (cron), so it does NOT increment
      `usage_events` and is NOT billed back to anyone. The cache hits
      it produces ARE still ¥3 each when the customer next calls — the
      ¥3 is for the *response*, not the compute, and the cache-hit
      response IS the response. No double-bill, no zero-bill.
    * No Anthropic / claude / SDK calls anywhere — see CONSTITUTION 13.2
      and the explicit memory `feedback_autonomath_no_api_use`.

Launch v1 (this module):
    The compute callbacks (`compute_factories`) are injected by the
    orchestrator at call time so this module stays decoupled from the
    FastAPI app graph (avoids circular imports + lets unit tests pass
    in stubbed computes that don't hit FTS5). When `compute_factories`
    is empty (pre-launch / fresh deploy / orchestrator stub), `run()`
    returns the zeroed scaffold dict — same posture as loop_a / loop_e
    / loop_g.

Cron wiring is intentionally out-of-scope here (handled by
`scripts/self_improve_orchestrator.py` + a separate cron entry — P3.1.5).
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

from jpintel_mcp.cache.l4 import (
    canonical_cache_key,
    canonical_params,
)

if TYPE_CHECKING:
    from collections.abc import Callable

# Repo layout: src/jpintel_mcp/self_improve/loop_h_cache_warming.py
# climb four parents to reach the repo root.
REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DB_PATH = Path(
    os.environ.get("JPINTEL_DB_PATH", str(REPO_ROOT / "data" / "jpintel.db"))
)
REPORT_PATH = REPO_ROOT / "data" / "cache_warming_report.json"

# Default: scan 7d of usage_events, take top 100 (endpoint, digest) pairs.
DEFAULT_WINDOW_DAYS = 7
DEFAULT_TOP_N = 100

# Map usage_events.endpoint (short name written by log_usage) to the L4 tool
# name (api.<router>.<verb>) used by canonical_cache_key. Only the three
# endpoints wired through L4 in P1.7 are warmable; everything else is a
# silent skip.
_ENDPOINT_TO_L4_TOOL: dict[str, str] = {
    "programs.search": "api.programs.search",
    "programs.get": "api.programs.get",
    # autonomath router uses the longer endpoint label in log_usage()
    # ("am.tax_incentives.search") — see api/autonomath.py:336.
    "am.tax_incentives.search": "api.am.tax_incentives",
}

# Warming budget: warmed rows get 2x the live TTL so they outlive a single
# day's prime-time window. The live TTLs come from the routers themselves;
# duplicating them here is a deliberate trade-off (no cross-import) — they
# are constants so drift is operator-visible (this module + the router).
_WARM_TTL_BY_TOOL: dict[str, int] = {
    "api.programs.search": 600,    # 2x 300s (live)
    "api.programs.get": 7200,      # 2x 3600s (live)
    "api.am.tax_incentives": 3600, # 2x 1800s (live)
}


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    ).fetchone()
    return row is not None


def select_hot_queries(
    conn: sqlite3.Connection,
    *,
    window_days: int = DEFAULT_WINDOW_DAYS,
    top_n: int = DEFAULT_TOP_N,
    endpoints: tuple[str, ...] | None = None,
) -> list[dict[str, Any]]:
    """Return the top-N (endpoint, params_digest) pairs by hit count.

    Only includes endpoints in `_ENDPOINT_TO_L4_TOOL` (the L4-wired set).
    Rows with NULL params_digest are skipped — they cannot be re-keyed.

    Pure read: no UPDATEs, no INSERTs. Safe to call from a read-only
    DB connection if the caller wants extra paranoia.
    """
    if not _table_exists(conn, "usage_events"):
        return []
    targets = endpoints if endpoints is not None else tuple(_ENDPOINT_TO_L4_TOOL)
    if not targets:
        return []
    placeholders = ",".join("?" for _ in targets)
    cutoff_iso = (datetime.now(UTC) - timedelta(days=window_days)).isoformat()
    sql = (
        f"SELECT endpoint, params_digest, COUNT(*) AS hit_count "  # noqa: S608
        f"FROM usage_events "
        f"WHERE ts >= ? AND params_digest IS NOT NULL "
        f"  AND endpoint IN ({placeholders}) "
        f"GROUP BY endpoint, params_digest "
        f"ORDER BY hit_count DESC LIMIT ?"
    )
    rows = conn.execute(sql, (cutoff_iso, *targets, top_n)).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        # row_factory may or may not be set — handle tuple + Row both.
        if isinstance(r, sqlite3.Row):
            out.append(
                {
                    "endpoint": r["endpoint"],
                    "params_digest": r["params_digest"],
                    "hit_count": int(r["hit_count"]),
                }
            )
        else:
            ep, dg, n = r
            out.append(
                {"endpoint": ep, "params_digest": dg, "hit_count": int(n)}
            )
    return out


def _params_digest_of(params_json: str) -> str | None:
    """Re-compute the 16-char digest from a stored l4_query_cache.params_json.

    Mirrors `api/deps.py::compute_params_digest` exactly: 16-char SHA-256
    prefix over canonical JSON of params with None values dropped. Returns
    None if the row's params_json is unparseable.

    NOTE: l4_query_cache.params_json is already in canonical form (see
    `cache.l4.canonical_params`) so we re-canonicalize through the same
    helper to stay drift-proof.
    """
    import hashlib

    try:
        parsed = json.loads(params_json)
    except (TypeError, ValueError):
        return None
    if not isinstance(parsed, dict) or not parsed:
        return None
    cleaned = {k: v for k, v in parsed.items() if v is not None}
    if not cleaned:
        return None
    canonical = json.dumps(
        cleaned, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def find_l4_params_for_digest(
    conn: sqlite3.Connection,
    *,
    endpoint: str,
    params_digest: str,
) -> dict[str, Any] | None:
    """Find the most recent l4_query_cache row whose params hash to `digest`.

    Returns the parsed params dict, or None if no match. Used to recover
    the canonical params blob without ever crossing the PII boundary
    (we only ever held the digest from usage_events; the full params
    must come from a row we previously cached for a real customer call).

    The L4 tool_name partitions the search space, so we only walk rows
    for the matching tool.
    """
    if not _table_exists(conn, "l4_query_cache"):
        return None
    tool = _ENDPOINT_TO_L4_TOOL.get(endpoint)
    if tool is None:
        return None
    cur = conn.execute(
        "SELECT params_json FROM l4_query_cache "
        "WHERE tool_name = ? "
        "ORDER BY COALESCE(last_hit_at, created_at) DESC",
        (tool,),
    )
    for (params_json,) in cur:
        if _params_digest_of(params_json) == params_digest:
            try:
                return json.loads(params_json)
            except (TypeError, ValueError):
                return None
    return None


def _is_fresh_in_db(
    conn: sqlite3.Connection, *, cache_key: str
) -> bool:
    """True iff the L4 row for `cache_key` exists and isn't past its TTL."""
    row = conn.execute(
        "SELECT created_at, ttl_seconds FROM l4_query_cache "
        "WHERE cache_key = ?",
        (cache_key,),
    ).fetchone()
    if row is None:
        return False
    if isinstance(row, sqlite3.Row):
        created_at, ttl_seconds = row["created_at"], int(row["ttl_seconds"])
    else:
        created_at, ttl_seconds = row[0], int(row[1])
    try:
        created = datetime.fromisoformat(created_at)
    except ValueError:
        return False
    if created.tzinfo is None:
        created = created.replace(tzinfo=UTC)
    age = (datetime.now(UTC) - created).total_seconds()
    return age < ttl_seconds


def _warm_one(
    conn: sqlite3.Connection,
    *,
    tool: str,
    params: dict[str, Any],
    compute: Callable[[dict[str, Any]], Any],
    ttl: int,
) -> bool:
    """Run compute(params) and INSERT OR REPLACE into l4_query_cache.

    Returns True if the row was written (warmed), False if compute
    produced an unserializable value (defensive — same posture as
    `cache.l4.get_or_compute`).
    """
    cache_key = canonical_cache_key(tool, params)
    value = compute(params)
    try:
        payload = json.dumps(value, sort_keys=True, ensure_ascii=False)
    except TypeError:
        return False
    now = _now_iso()
    conn.execute(
        """
        INSERT OR REPLACE INTO l4_query_cache
            (cache_key, tool_name, params_json, result_json,
             hit_count, last_hit_at, ttl_seconds, created_at)
        VALUES (?, ?, ?, ?, 0, ?, ?, ?)
        """,
        (
            cache_key,
            tool,
            canonical_params(params),
            payload,
            now,
            int(ttl),
            now,
        ),
    )
    return True


def warm_top_queries(
    conn: sqlite3.Connection,
    *,
    hot: list[dict[str, Any]],
    compute_factories: dict[str, Callable[[dict[str, Any]], Any]],
    ttl_by_tool: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Warm the L4 cache for each (endpoint, digest) hot pair.

    Args:
        conn: open sqlite3 connection (will be written to).
        hot: output of `select_hot_queries`.
        compute_factories: `{l4_tool_name: callable(params)->value}` map.
            Caller injects the live FastAPI/MCP compute closures so this
            module stays decoupled from the app graph. Missing entries
            mean the corresponding tool is not warmable in this run.
        ttl_by_tool: override TTL per tool. Defaults to `_WARM_TTL_BY_TOOL`.

    Returns:
        report fragment with `warmed_count`, `already_fresh_count`,
        `skipped_count`, and `by_tool` breakdown.
    """
    ttls = ttl_by_tool if ttl_by_tool is not None else _WARM_TTL_BY_TOOL
    by_tool: dict[str, dict[str, int]] = {}
    warmed = 0
    already_fresh = 0
    skipped = 0

    for h in hot:
        endpoint = h["endpoint"]
        digest = h["params_digest"]
        tool = _ENDPOINT_TO_L4_TOOL.get(endpoint)
        if tool is None:
            skipped += 1
            continue
        bag = by_tool.setdefault(
            tool, {"warmed": 0, "already_fresh": 0, "skipped": 0}
        )
        compute = compute_factories.get(tool)
        if compute is None:
            bag["skipped"] += 1
            skipped += 1
            continue
        params = find_l4_params_for_digest(
            conn, endpoint=endpoint, params_digest=digest
        )
        if params is None:
            # Digest pre-dates L4 wiring or the cached row was evicted.
            # Nothing to reconstruct from — skip without crossing the PII
            # boundary into raw usage_events.params_json (which doesn't
            # exist anyway; only the digest is stored).
            bag["skipped"] += 1
            skipped += 1
            continue
        cache_key = canonical_cache_key(tool, params)
        if _is_fresh_in_db(conn, cache_key=cache_key):
            bag["already_fresh"] += 1
            already_fresh += 1
            continue
        ttl = ttls.get(tool, 86400)
        ok = _warm_one(
            conn, tool=tool, params=params, compute=compute, ttl=ttl,
        )
        if ok:
            bag["warmed"] += 1
            warmed += 1
        else:
            bag["skipped"] += 1
            skipped += 1

    return {
        "warmed_count": warmed,
        "already_fresh_count": already_fresh,
        "skipped_count": skipped,
        "by_tool": by_tool,
    }


def _project_hit_rate(
    hot: list[dict[str, Any]],
    warmed_digests: set[tuple[str, str]] | None,
) -> tuple[float, float]:
    """Return (miss_before, hit_after) projected for the warmed set.

    miss_before  = 1 - (rows already fresh / total hits in window)
    hit_after    = (rows fresh OR newly warmed) / total hits in window

    Both are upper-bound projections — they assume the customer mix in
    the next 24h matches the last 7d (Zipf is stable on that timescale).
    Returns (1.0, 1.0) when `hot` is empty so the dashboard can sentinel.
    """
    if not hot:
        return (1.0, 1.0)
    total = sum(h["hit_count"] for h in hot)
    if total <= 0:
        return (1.0, 1.0)
    if warmed_digests is None:
        warmed_digests = set()
    hit_after = sum(
        h["hit_count"]
        for h in hot
        if (h["endpoint"], h["params_digest"]) in warmed_digests
    )
    return (1.0, round(hit_after / total, 4))


def run(
    *,
    dry_run: bool = True,
    window_days: int = DEFAULT_WINDOW_DAYS,
    top_n: int = DEFAULT_TOP_N,
    db_path: Path | None = None,
    out_path: Path | None = None,
    compute_factories: dict[str, Callable[[dict[str, Any]], Any]] | None = None,
) -> dict[str, int]:
    """Pre-compute top-N global queries based on the last 7 days of usage.

    Args:
        dry_run: When True, do not INSERT OR REPLACE into l4_query_cache
            and do not write `cache_warming_report.json` — still scan
            and count, still report `actions_proposed`. Same contract as
            loop_a / loop_e / loop_g.
        window_days: Lookback window for `usage_events`. Default 7.
        top_n: Cap on (endpoint, digest) pairs to warm. Default 100.
        db_path: Override JPINTEL_DB_PATH. Defaults to repo `data/jpintel.db`.
        out_path: Override report path. Defaults to `data/cache_warming_report.json`.
        compute_factories: `{l4_tool_name: callable(params)->value}` map.
            Caller injects live compute closures (orchestrator wires the
            FastAPI tool functions). Missing or empty -> zeroed scaffold.

    Returns:
        Standard self-improve loop dict:
            {loop, scanned, actions_proposed, actions_executed}.
    """
    dbp = db_path if db_path is not None else DEFAULT_DB_PATH
    out_p = out_path if out_path is not None else REPORT_PATH

    if not dbp.exists():
        # Pre-launch / fresh deploy: no DB yet. Same posture as loop_a.
        return {
            "loop": "loop_h_cache_warming",
            "scanned": 0,
            "actions_proposed": 0,
            "actions_executed": 0,
        }

    factories = compute_factories or {}

    conn = sqlite3.connect(str(dbp))
    conn.row_factory = sqlite3.Row
    try:
        hot = select_hot_queries(
            conn, window_days=window_days, top_n=top_n,
        )
        if not hot or not factories:
            # No traffic yet OR no compute callbacks injected.
            return {
                "loop": "loop_h_cache_warming",
                "scanned": len(hot),
                "actions_proposed": 0,
                "actions_executed": 0,
            }

        if dry_run:
            # Count what we *would* warm without mutating the cache.
            already_fresh = 0
            warmable = 0
            for h in hot:
                tool = _ENDPOINT_TO_L4_TOOL.get(h["endpoint"])
                if tool is None or tool not in factories:
                    continue
                params = find_l4_params_for_digest(
                    conn,
                    endpoint=h["endpoint"],
                    params_digest=h["params_digest"],
                )
                if params is None:
                    continue
                cache_key = canonical_cache_key(tool, params)
                if _is_fresh_in_db(conn, cache_key=cache_key):
                    already_fresh += 1
                else:
                    warmable += 1
            return {
                "loop": "loop_h_cache_warming",
                "scanned": len(hot),
                "actions_proposed": warmable,
                "actions_executed": 0,
            }

        # Real run: warm + report.
        report = warm_top_queries(
            conn, hot=hot, compute_factories=factories,
        )
        conn.commit()

        # Recompute the (endpoint, digest) set we actually touched so
        # _project_hit_rate is honest about WHICH rows are now warm.
        warmed_pairs: set[tuple[str, str]] = set()
        for h in hot:
            tool = _ENDPOINT_TO_L4_TOOL.get(h["endpoint"])
            if tool is None or tool not in factories:
                continue
            params = find_l4_params_for_digest(
                conn,
                endpoint=h["endpoint"],
                params_digest=h["params_digest"],
            )
            if params is None:
                continue
            cache_key = canonical_cache_key(tool, params)
            if _is_fresh_in_db(conn, cache_key=cache_key):
                warmed_pairs.add((h["endpoint"], h["params_digest"]))

        miss_before, hit_after = _project_hit_rate(hot, warmed_pairs)

        full_report: dict[str, Any] = {
            "generated_at": _now_iso(),
            "window_days": window_days,
            "top_n": top_n,
            "warmed_count": report["warmed_count"],
            "already_fresh_count": report["already_fresh_count"],
            "skipped_count": report["skipped_count"],
            "miss_before": miss_before,
            "hit_after": hit_after,
            "by_tool": report["by_tool"],
        }
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_p.write_text(
            json.dumps(full_report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        return {
            "loop": "loop_h_cache_warming",
            "scanned": len(hot),
            "actions_proposed": report["warmed_count"]
            + report["already_fresh_count"],
            "actions_executed": report["warmed_count"],
        }
    finally:
        conn.close()


if __name__ == "__main__":
    print(json.dumps(run(dry_run=True)))
