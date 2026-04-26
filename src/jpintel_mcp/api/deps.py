import hashlib
import hmac
import json
import secrets
import sqlite3
from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import BackgroundTasks, Depends, Header, HTTPException, Request, status

from jpintel_mcp.config import settings
from jpintel_mcp.db.session import connect

# Endpoints whose query params are safe to hash into a digest. Anything not
# listed here stores `params_digest = NULL` (PII-carrying endpoints like
# /v1/me/*, /v1/billing/*, /v1/feedback, /v1/subscribers must stay NULL).
# Keys are the short endpoint names used by log_usage(), not URL paths.
_PARAMS_DIGEST_WHITELIST: frozenset[str] = frozenset(
    {
        "programs.search",
        "programs.get",
        "programs.prescreen",
        "exclusions.check",
        "exclusions.rules",
        "enforcement.search",
        "enforcement.get",
        "case_studies.search",
        "case_studies.get",
        "loan_programs.search",
        "loan_programs.get",
        "laws.search",
        "laws.get",
        "laws.related_programs",
        "court_decisions.search",
        "court_decisions.get",
        "court_decisions.by_statute",
        "bids.search",
        "bids.get",
        "tax_rulesets.search",
        "tax_rulesets.get",
        "tax_rulesets.evaluate",
        "invoice_registrants.search",
        "invoice_registrants.get",
        "calendar.deadlines",
        "meta",
        "ping",
    }
)


def get_db() -> Generator[sqlite3.Connection, None, None]:
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()


def hash_api_key(raw_key: str) -> str:
    return hmac.new(
        settings.api_key_salt.encode("utf-8"),
        raw_key.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


# bcrypt dual-path (Wave 16 P1, migration 073). Cost factor 12 chosen so a
# single verify takes ~100ms on modern hardware — slow enough to make an
# offline brute-force against an exfiltrated DB economically irrelevant
# (≈10 attempts/sec/core), fast enough that the auth hot path stays under
# the 200ms p95 budget. Bumping to 13/14 doubles/quadruples per-attempt
# cost; revisit when CPU baseline shifts.
_BCRYPT_COST = 12


def hash_api_key_bcrypt(raw_key: str) -> str:
    """Return bcrypt(raw_key) at cost factor 12 (~100ms).

    Used at issuance time for new keys (migration 073). The result is
    stored in `api_keys.key_hash_bcrypt` alongside the legacy HMAC
    `key_hash` (which remains the PRIMARY KEY for O(log n) lookup).
    Verification is done by `verify_api_key_bcrypt` below.
    """
    import bcrypt

    return bcrypt.hashpw(
        raw_key.encode("utf-8"), bcrypt.gensalt(_BCRYPT_COST)
    ).decode("ascii")


def verify_api_key_bcrypt(raw_key: str, stored_bcrypt_hash: str) -> bool:
    """Constant-time verify a raw key against a stored bcrypt hash.

    Returns False on any error (malformed hash, etc.) so a corrupted
    `key_hash_bcrypt` cell never auths a request — the require_key path
    falls back to legacy HMAC verify when this returns False.
    """
    if not stored_bcrypt_hash:
        return False
    try:
        import bcrypt

        return bcrypt.checkpw(
            raw_key.encode("utf-8"), stored_bcrypt_hash.encode("ascii")
        )
    except (ValueError, TypeError):
        return False


def generate_api_key() -> tuple[str, str]:
    """Issue a new API key. Returns (raw_key, hmac_hash).

    For new bcrypt dual-path callers, also call `hash_api_key_bcrypt(raw)`
    and store the result in `api_keys.key_hash_bcrypt`. The HMAC return
    here remains the PRIMARY KEY column so existing lookups continue to
    work in O(log n).
    """
    raw = "am_" + secrets.token_urlsafe(32)
    return raw, hash_api_key(raw)


# tier => (settings_attr_for_daily_cap, is_metered)
# Post-2026-04-23 pricing pivot: AutonoMath is pure metered ¥3/req 税別.
# Only two tiers exist at runtime on an authenticated key:
#   "free" — DUNNING DEMOTE state (customer whose card is failing). Short
#            daily cap via RATE_LIMIT_FREE_PER_DAY (default 100). NOT the
#            public anonymous Free tier (that lives in anon_rate_limit,
#            50/month per IP, applied via AnonIpLimitDep).
#   "paid" — metered via Stripe usage_records at ¥3/req, no 429 enforcement.
TIER_LIMITS = {
    "free": ("rate_limit_free_per_day", False),
    "paid": (None, True),
}


def _day_bucket(ts: datetime | None = None) -> str:
    ts = ts or datetime.now(UTC)
    return ts.strftime("%Y-%m-%d")


class ApiContext:
    def __init__(
        self,
        key_hash: str | None,
        tier: str,
        customer_id: str | None,
        stripe_subscription_id: str | None = None,
    ):
        self.key_hash = key_hash
        self.tier = tier
        self.customer_id = customer_id
        self.stripe_subscription_id = stripe_subscription_id

    @property
    def metered(self) -> bool:
        return self.tier == "paid"


async def require_key(
    request: Request,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
    authorization: Annotated[str | None, Header()] = None,
) -> ApiContext:
    raw = x_api_key
    if not raw and authorization:
        parts = authorization.split(None, 1)
        if len(parts) == 2 and parts[0].lower() == "bearer":
            raw = parts[1].strip()

    if not raw:
        return ApiContext(key_hash=None, tier="free", customer_id=None)

    key_hash = hash_api_key(raw)
    # Lookup by HMAC PRIMARY KEY (O(log n)). bcrypt verify (when present)
    # runs as a defense-in-depth check AFTER row resolution — bcrypt
    # hashes are non-deterministic and cannot be used as a lookup index.
    # The HMAC match alone proves possession (HMAC is keyed on
    # api_key_salt); the bcrypt check is the dual-path migration target
    # so an attacker who exfiltrated an old DB without the live salt
    # still has to brute-force at ~100ms/attempt.
    row = conn.execute(
        "SELECT tier, customer_id, stripe_subscription_id, revoked_at, "
        "key_hash_bcrypt "
        "FROM api_keys WHERE key_hash = ?",
        (key_hash,),
    ).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid api key")
    if row["revoked_at"]:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "api key revoked")
    # Dual-path verify: when key_hash_bcrypt is non-NULL we MUST also
    # pass bcrypt.checkpw, otherwise an HMAC collision (cryptographically
    # implausible but defense-in-depth) cannot auth. Legacy rows have
    # NULL bcrypt and rely on HMAC PRIMARY KEY match alone (already
    # verified above by the row lookup succeeding).
    bcrypt_hash = row["key_hash_bcrypt"] if "key_hash_bcrypt" in row.keys() else None
    if bcrypt_hash and not verify_api_key_bcrypt(raw, bcrypt_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid api key")

    tier = row["tier"]
    ctx = ApiContext(
        key_hash=key_hash,
        tier=tier,
        customer_id=row["customer_id"],
        stripe_subscription_id=row["stripe_subscription_id"],
    )
    _enforce_quota(conn, ctx)
    return ctx


def _seconds_until_utc_midnight(now: datetime | None = None) -> int:
    """Seconds remaining until the next UTC 00:00 boundary (rate-limit reset)."""
    now = now or datetime.now(UTC)
    tomorrow = (now + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return max(1, int((tomorrow - now).total_seconds()))


def _enforce_quota(conn: sqlite3.Connection, ctx: ApiContext) -> None:
    if ctx.key_hash is None:
        return
    limit_key, metered = TIER_LIMITS.get(ctx.tier, (None, False))
    if metered:
        return
    if limit_key is None:
        return
    daily_limit = getattr(settings, limit_key)

    bucket = _day_bucket()
    (n,) = conn.execute(
        "SELECT COUNT(*) FROM usage_events WHERE key_hash = ? AND ts >= ?",
        (ctx.key_hash, bucket),
    ).fetchone()
    if n >= daily_limit:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"daily limit of {daily_limit} exceeded for tier={ctx.tier}",
            headers={"Retry-After": str(_seconds_until_utc_midnight())},
        )


def compute_params_digest(endpoint: str, params: dict[str, Any] | None) -> str | None:
    """Return a 16-char hex SHA-256 prefix over canonical JSON of `params`.

    - `None` / empty params → None (no digest worth grouping by).
    - Endpoint not in the whitelist → None (PII safety — see
      _PARAMS_DIGEST_WHITELIST above).
    - Canonical JSON = `json.dumps(params, sort_keys=True, separators=(',',':'))`
      with ensure_ascii=False so 日本語 prefecture names don't inflate the
      digest surface. Deterministic: same query → same digest → SQL GROUP BY
      works for the W7 digest cron.

    16 hex chars = 64 bits. Far more than enough for per-user weekly
    grouping (a single user issuing 2^32 distinct queries before collision
    is not a real workload).
    """
    if not params:
        return None
    if endpoint not in _PARAMS_DIGEST_WHITELIST:
        return None
    # Drop None values so `?q=foo` and `?q=foo&prefecture=` digest the same
    # way — FastAPI Optional params surface as None when absent.
    cleaned = {k: v for k, v in params.items() if v is not None}
    if not cleaned:
        return None
    payload = json.dumps(
        cleaned, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _record_usage_async(
    key_hash: str,
    endpoint: str,
    status_code: int,
    metered: bool,
    digest: str | None,
    latency_ms: int | None,
    result_count: int | None,
    stripe_subscription_id: str | None,
) -> None:
    """Deferred body of ``log_usage`` — runs after the response is flushed.

    Opens its own short-lived sqlite3 connection because the request-scoped
    one from ``get_db()`` is closed in its ``finally`` block before
    ``BackgroundTasks`` fire (mirrors the
    ``_refresh_subscription_status_from_stripe_bg`` pattern in
    ``api/billing.py``). All sqlite writes use WAL + autocommit; no explicit
    commit is required.

    **Failure semantics** (Q4 perf diff #2, 2026-04-25): worker SIGKILL
    between flush + commit = under-billing risk. If uvicorn is killed after
    the response is sent but before this function commits, the user is not
    billed for that request and dashboards under-count by ≤ in-flight count.
    This is the documented trade-off — billing under-count is acceptable,
    billing-induced 502s are not. Stripe ``report_usage_async`` already
    swallows exceptions; the local INSERT + UPDATE catch broadly so a
    transient SQLite lock can never crash a background worker.
    """
    usage_event_id: int | None = None
    try:
        conn = connect()
    except Exception:  # noqa: BLE001
        conn = None
    if conn is not None:
        try:
            cur = conn.execute(
                "INSERT INTO usage_events("
                "  key_hash, endpoint, ts, status, metered, params_digest,"
                "  latency_ms, result_count"
                ") VALUES (?,?,?,?,?,?,?,?)",
                (
                    key_hash,
                    endpoint,
                    datetime.now(UTC).isoformat(),
                    status_code,
                    1 if metered else 0,
                    digest,
                    latency_ms,
                    result_count,
                ),
            )
            usage_event_id = cur.lastrowid
            conn.execute(
                "UPDATE api_keys SET last_used_at = ? WHERE key_hash = ?",
                (datetime.now(UTC).isoformat(), key_hash),
            )
        except Exception:  # noqa: BLE001
            usage_event_id = None
        finally:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass

    # Fire-and-forget Stripe usage_records report for metered ("paid") tier.
    # 4xx/5xx are not billed. Local import prevents a hard dep on stripe
    # during tests that construct ApiContext directly without Stripe env.
    # The usage_event_id is passed so the worker can mark the row as
    # synced (stripe_record_id + stripe_synced_at) on success — required
    # for Fly volume DR replay-from-Stripe (audit a37f6226fe319dc40).
    if metered and status_code < 400 and stripe_subscription_id:
        try:
            from jpintel_mcp.billing.stripe_usage import report_usage_async

            report_usage_async(stripe_subscription_id, usage_event_id=usage_event_id)
        except Exception:  # noqa: BLE001
            pass


def log_usage(
    conn: sqlite3.Connection,
    ctx: ApiContext,
    endpoint: str,
    status_code: int = 200,
    params: dict[str, Any] | None = None,
    latency_ms: int | None = None,
    result_count: int | None = None,
    background_tasks: BackgroundTasks | None = None,
) -> None:
    """Insert one row into usage_events.

    Migration 061 added two nullable columns:
      * `latency_ms` — wall-clock latency in milliseconds. Pass when the
        caller measured `time.perf_counter()` at entry/exit. NULL is fine
        for non-search endpoints that don't care about the search-quality
        regression dashboard.
      * `result_count` — number of rows the endpoint returned. Only search
        endpoints set this; everything else passes NULL.

    Anonymous callers (key_hash=None) are NOT logged here — usage_events
    is keyed on api_keys. Empty searches by anonymous callers are captured
    by `log_empty_search` instead, which carries no key_hash dependency.

    When ``background_tasks`` is supplied (the hot-path case from FastAPI
    routes), the SQLite writes and the Stripe report are deferred via
    ``BackgroundTasks.add_task`` so they run **after** the HTTP response is
    flushed — removing two sqlite writes + one thread spawn from the
    critical path. This is the Q4 perf-diff #2 wiring (see
    ``analysis_wave18/_q4_perf_diffs_2026-04-25.md``). When omitted (cron
    jobs, tests that drive this helper directly without a request scope),
    the writes happen inline on the supplied ``conn`` — preserving the
    legacy contract.

    **Failure semantics change** when deferred: worker SIGKILL between
    response-send and the deferred commit = under-billing risk
    (Q4 documented). The deferred path opens its own sqlite connection
    (``_record_usage_async``) because the request-scoped ``conn`` is
    closed by ``get_db()``'s finally clause before BackgroundTasks fire.
    """
    if ctx.key_hash is None:
        return
    digest = compute_params_digest(endpoint, params)

    if background_tasks is not None:
        # Hot path: defer all writes until after response flush.
        background_tasks.add_task(
            _record_usage_async,
            ctx.key_hash,
            endpoint,
            status_code,
            ctx.metered,
            digest,
            latency_ms,
            result_count,
            ctx.stripe_subscription_id,
        )
        return

    # Legacy / non-request path: inline writes on the supplied conn.
    cur = conn.execute(
        "INSERT INTO usage_events("
        "  key_hash, endpoint, ts, status, metered, params_digest,"
        "  latency_ms, result_count"
        ") VALUES (?,?,?,?,?,?,?,?)",
        (
            ctx.key_hash,
            endpoint,
            datetime.now(UTC).isoformat(),
            status_code,
            1 if ctx.metered else 0,
            digest,
            latency_ms,
            result_count,
        ),
    )
    usage_event_id = cur.lastrowid
    conn.execute(
        "UPDATE api_keys SET last_used_at = ? WHERE key_hash = ?",
        (datetime.now(UTC).isoformat(), ctx.key_hash),
    )
    # Fire-and-forget Stripe usage_records report for metered ("paid") tier.
    # 4xx/5xx are not billed. Local import prevents a hard dep on stripe
    # during tests that construct ApiContext directly without Stripe env.
    # The usage_event_id is passed so the worker can mark the row as
    # synced (stripe_record_id + stripe_synced_at) on success — required
    # for Fly volume DR replay-from-Stripe (audit a37f6226fe319dc40).
    if ctx.metered and status_code < 400 and ctx.stripe_subscription_id:
        try:
            from jpintel_mcp.billing.stripe_usage import report_usage_async

            report_usage_async(ctx.stripe_subscription_id, usage_event_id=usage_event_id)
        except Exception:  # noqa: BLE001
            pass


def hash_ip_for_telemetry(ip: str | None, day: str | None = None) -> str | None:
    """Return sha256(ip || daily_salt) as a hex string, or None for empty ip.

    Used for `empty_search_log.ip_hash`. Migration 062 spec: store ONLY a
    salted hash, never the raw IP. The salt rotates daily so the column
    cannot serve as a long-term tracking surface — same row on day N+1
    hashes to a different value.

    `day` defaults to today UTC (YYYY-MM-DD). Tests pass an explicit value
    to make the hash deterministic.
    """
    if not ip:
        return None
    if day is None:
        day = datetime.now(UTC).strftime("%Y-%m-%d")
    salt = settings.api_key_salt or "ip-hash-fallback-salt"
    payload = f"{ip}|{day}|{salt}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def log_empty_search(
    conn: sqlite3.Connection,
    *,
    query: str,
    endpoint: str,
    filters: dict[str, Any] | None = None,
    ip: str | None = None,
) -> None:
    """Append a row to empty_search_log when a search returns 0 results.

    Triviality gate: callers must filter out queries that are <2 chars or
    pure whitespace BEFORE calling. We trust the caller because the gate
    differs per endpoint (some FTS5 paths reject single-char already, but
    the LIKE-fallback paths happily accept them).

    PII rule: the raw `query` IS stored — operator must triage missing-program
    signal from the actual user phrasing. `ip` is hashed via
    hash_ip_for_telemetry; raw IP never reaches the column.
    """
    if not query:
        return
    payload = (
        json.dumps(filters, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        if filters
        else None
    )
    try:
        conn.execute(
            "INSERT INTO empty_search_log("
            "  query, endpoint, filters_json, ip_hash, created_at"
            ") VALUES (?,?,?,?,?)",
            (
                query,
                endpoint,
                payload,
                hash_ip_for_telemetry(ip),
                datetime.now(UTC).isoformat(),
            ),
        )
    except sqlite3.OperationalError:
        # Migration 062 not applied yet — never block the response on
        # telemetry write failure. Same posture as _emit_query_log.
        pass


ApiContextDep = Annotated[ApiContext, Depends(require_key)]
DbDep = Annotated[sqlite3.Connection, Depends(get_db)]
