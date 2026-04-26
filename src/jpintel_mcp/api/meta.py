import time
from datetime import UTC, datetime

from fastapi import APIRouter
from fastapi.responses import RedirectResponse
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
