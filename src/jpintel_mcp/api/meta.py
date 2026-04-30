import sqlite3
import time
from datetime import UTC, datetime

from fastapi import APIRouter
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel

from jpintel_mcp.api.anon_limit import AnonIpLimitDep
from jpintel_mcp.api.deps import TIER_LIMITS, ApiContextDep, DbDep, log_usage
from jpintel_mcp.config import settings
from jpintel_mcp.models import DataLineage, Meta

router = APIRouter(tags=["meta"])

# /v1/meta does 4-5 full-table scans (GROUP BY tier/prefecture, COUNT(*),
# MAX/COUNT DISTINCT over source_fetched_at/source_checksum). Counts change
# at ingest cadence (hourly-ish), so a 60s TTL is weaker-consistency than
# the underlying data warrants and trims P95 by ~7x.
_META_CACHE_TTL_SEC = 60.0
_meta_cache: tuple[float, Meta] | None = None


def _reset_meta_cache() -> None:
    """Test hook — call from pytest fixtures that mutate programs/meta tables."""
    global _meta_cache
    _meta_cache = None


def _programs_has_column(conn, column: str) -> bool:
    return any(row["name"] == column for row in conn.execute("PRAGMA table_info(programs)"))


@router.get("/meta", include_in_schema=False)
async def meta_legacy_redirect() -> RedirectResponse:
    """Back-compat: old `/meta` path now 308-redirects to `/v1/meta`.

    Kept for one release cycle so existing clients that pinned the
    pre-/v1/ path don't break mid-deploy.
    """
    return RedirectResponse(url="/v1/meta", status_code=308)


@router.get("/v1/meta", response_model=Meta, dependencies=[AnonIpLimitDep])
def get_meta(conn: DbDep, ctx: ApiContextDep) -> Meta:
    global _meta_cache
    now = time.monotonic()
    if _meta_cache is not None and now - _meta_cache[0] < _META_CACHE_TTL_SEC:
        log_usage(conn, ctx, "meta")
        return _meta_cache[1]

    tier_counts: dict[str, int] = {}
    for row in conn.execute(
        "SELECT COALESCE(tier, 'unknown') AS tier, COUNT(*) AS c FROM programs GROUP BY tier"
    ):
        tier_counts[row["tier"]] = row["c"]

    pref_counts: dict[str, int] = {}
    for row in conn.execute(
        "SELECT COALESCE(prefecture, '_none') AS p, COUNT(*) AS c FROM programs GROUP BY prefecture"
    ):
        pref_counts[row["p"]] = row["c"]

    (rules_n,) = conn.execute("SELECT COUNT(*) FROM exclusion_rules").fetchone()
    (programs_n,) = conn.execute("SELECT COUNT(*) FROM programs").fetchone()

    last_ingested = None
    data_as_of = None
    for row in conn.execute("SELECT key, value FROM meta"):
        if row["key"] == "last_ingested_at":
            last_ingested = row["value"]
        elif row["key"] == "data_as_of":
            data_as_of = row["value"]

    lineage = DataLineage()
    if _programs_has_column(conn, "source_fetched_at") and _programs_has_column(
        conn, "source_checksum"
    ):
        row = conn.execute(
            "SELECT MAX(source_fetched_at) AS last_fetched, "
            "COUNT(DISTINCT source_checksum) AS uniq FROM programs"
        ).fetchone()
        lineage = DataLineage(
            last_fetched_at=row["last_fetched"],
            unique_checksums=row["uniq"] or 0,
        )

    result = Meta(
        total_programs=programs_n,
        tier_counts=tier_counts,
        prefecture_counts=pref_counts,
        exclusion_rules_count=rules_n,
        last_ingested_at=last_ingested,
        data_as_of=data_as_of,
        data_lineage=lineage,
    )
    _meta_cache = (now, result)
    log_usage(conn, ctx, "meta")
    return result


@router.get("/healthz")
def healthz(conn: DbDep) -> dict[str, str]:
    conn.execute("SELECT 1").fetchone()
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# /v1/ping — auth-aware probe, separate from /healthz (liveness only).
# ---------------------------------------------------------------------------


class PingResponse(BaseModel):
    ok: bool
    authenticated: bool
    tier: str
    server_time_utc: str
    server_version: str
    rate_limit_remaining: int | None


def _rate_limit_remaining(conn, ctx) -> int | None:
    """Return remaining daily allowance for this caller.

    - Authed metered tier (paid): None (no hard cap).
    - Authed free tier: free daily limit - today's usage_events for key_hash.
    - Anonymous: free-tier limit - today's anon IP can't be counted via
      usage_events (we don't log anon usage), so return the configured free
      limit as a ceiling without a used-count. Docs call out the caveat.
    """
    limit_key, metered = TIER_LIMITS.get(ctx.tier, (None, False))
    if metered:
        return None
    if limit_key is None:
        return None
    daily_limit = getattr(settings, limit_key)
    if ctx.key_hash is None:
        # Anonymous: no per-IP usage log to subtract against. Return the
        # ceiling — matches the spec intent ("computed from free-tier
        # counter") while being honest about what we know.
        return daily_limit
    bucket = datetime.now(UTC).strftime("%Y-%m-%d")
    (n,) = conn.execute(
        "SELECT COUNT(*) FROM usage_events WHERE key_hash = ? AND ts >= ?",
        (ctx.key_hash, bucket),
    ).fetchone()
    return max(0, daily_limit - n)


@router.get("/v1/ping", response_model=PingResponse, dependencies=[AnonIpLimitDep])
def ping(conn: DbDep, ctx: ApiContextDep) -> PingResponse:
    from jpintel_mcp import __version__

    # Record the probe as a usage_event for authed keys only — discourages
    # burning it as a free heartbeat. Anonymous probes aren't counted (no
    # per-IP usage log exists).
    log_usage(conn, ctx, "ping")

    return PingResponse(
        ok=True,
        authenticated=ctx.key_hash is not None,
        tier=ctx.tier,
        server_time_utc=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        server_version=__version__,
        rate_limit_remaining=_rate_limit_remaining(conn, ctx),
    )


# ---------------------------------------------------------------------------
# /v1/health/data — table-level row-count probe (P0-2 completion criterion).
# Verifies that the canonical tables in jpintel.db (programs / case_studies /
# usage_events) and autonomath.db (jpi_programs / am_entities) carry the
# expected minimum rows. Catches the "DB正本不一致" failure mode where a
# deploy points the API at an empty placeholder DB. Unbilled, unrate-limited,
# read-only — same posture as /healthz and /v1/am/health/deep.
# ---------------------------------------------------------------------------


class _DataHealthCheck(BaseModel):
    table: str
    db: str
    expected_min_rows: int
    actual_rows: int | None
    status: str  # "ok" | "empty" | "below_threshold" | "missing"
    detail: str | None = None


class DataHealthResponse(BaseModel):
    status: str  # "ok" | "degraded" | "unhealthy"
    checks: list[_DataHealthCheck]
    timestamp_utc: str


# (table, db_path_attr, expected_min_rows). db_path_attr is the Settings
# attribute name so the production Fly volume paths (env-overridden via
# JPINTEL_DB_PATH / AUTONOMATH_DB_PATH) are honoured automatically.
_DATA_HEALTH_TABLES: tuple[tuple[str, str, int], ...] = (
    ("programs", "db_path", 10000),
    ("case_studies", "db_path", 2000),
    ("usage_events", "db_path", 0),  # 0 ok — table just may not have logged yet
    ("jpi_programs", "autonomath_db_path", 10000),
    ("am_entities", "autonomath_db_path", 500000),
)

# 30-second response cache: each probe is 5 cold COUNT(*) hits, no need
# to re-run on every uptime poll. Mirrors `_health_deep._CACHE_TTL`.
_DATA_HEALTH_CACHE: dict[str, object] = {"ts": 0.0, "doc": None}
_DATA_HEALTH_CACHE_TTL: float = 30.0


def _count_or_error(db_file_path, table: str) -> tuple[int | None, str | None]:
    """Return (row_count, error_detail). row_count=None when missing/error.

    Opens read-only via URI so a typo'd path can't accidentally create an
    empty file on disk. 2-second timeout matches `_health_deep._open_ro`.
    """
    if not db_file_path.exists():
        return None, f"db missing: {db_file_path}"
    try:
        uri = f"file:{db_file_path}?mode=ro"
        with sqlite3.connect(uri, uri=True, timeout=2.0) as con:
            row = con.execute(
                f"SELECT COUNT(*) FROM {table}"  # noqa: S608 — table from allowlist
            ).fetchone()
        return int(row[0] or 0), None
    except sqlite3.OperationalError as exc:
        # "no such table" → table missing (expected for usage_events on a
        # fresh install where no row has been logged yet — but the schema
        # ships the table, so this is genuinely a missing-table fault).
        return None, f"{type(exc).__name__}: {exc}"
    except Exception as exc:  # noqa: BLE001
        return None, f"{type(exc).__name__}: {exc}"


@router.get("/v1/health/data", response_model=DataHealthResponse)
def data_health() -> JSONResponse:
    """Row-count probe for the 5 canonical tables.

    Returns one entry per (table, db) pair. status:
    - "ok" — row count meets `expected_min_rows`
    - "below_threshold" — rows present but under the floor
    - "empty" — table reachable, 0 rows
    - "missing" — table or DB file unreachable

    Aggregate `status` rolls up:
    - "unhealthy" if any check is "missing" OR "empty" with floor > 0
    - "degraded" if any check is "below_threshold"
    - "ok" otherwise

    Unbilled / unlogged / no anonymous quota — heartbeat surface for uptime
    monitors. 30-second response cache.
    """
    now_mono = time.monotonic()
    cached_doc = _DATA_HEALTH_CACHE.get("doc")
    cached_ts = _DATA_HEALTH_CACHE.get("ts", 0.0)
    if (
        cached_doc is not None
        and isinstance(cached_ts, float)
        and (now_mono - cached_ts) < _DATA_HEALTH_CACHE_TTL
    ):
        return JSONResponse(content=cached_doc)  # type: ignore[arg-type]

    checks: list[dict[str, object]] = []
    has_unhealthy = False
    has_degraded = False
    for table, attr, floor in _DATA_HEALTH_TABLES:
        db_path = getattr(settings, attr)
        rows, err = _count_or_error(db_path, table)
        if err is not None or rows is None:
            status = "missing"
            has_unhealthy = True
            checks.append({
                "table": table,
                "db": db_path.name,
                "expected_min_rows": floor,
                "actual_rows": None,
                "status": status,
                "detail": err,
            })
            continue
        if rows == 0 and floor > 0:
            status = "empty"
            has_unhealthy = True
        elif rows < floor:
            status = "below_threshold"
            has_degraded = True
        else:
            status = "ok"
        checks.append({
            "table": table,
            "db": db_path.name,
            "expected_min_rows": floor,
            "actual_rows": rows,
            "status": status,
            "detail": None,
        })

    if has_unhealthy:
        agg = "unhealthy"
    elif has_degraded:
        agg = "degraded"
    else:
        agg = "ok"

    doc = {
        "status": agg,
        "checks": checks,
        "timestamp_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    _DATA_HEALTH_CACHE["ts"] = now_mono
    _DATA_HEALTH_CACHE["doc"] = doc
    return JSONResponse(content=doc)
