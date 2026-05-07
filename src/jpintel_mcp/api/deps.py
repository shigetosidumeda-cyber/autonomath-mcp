import contextlib
import hashlib
import hmac
import json
import logging
import secrets
import sqlite3
from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, NoReturn

from fastapi import BackgroundTasks, Depends, Header, HTTPException, Request, status

from jpintel_mcp.api.token_savings import estimate_tokens_saved
from jpintel_mcp.config import settings
from jpintel_mcp.db.session import connect

logger = logging.getLogger("jpintel.usage")

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
        "tax_rules.full_chain",
        "invoice_registrants.search",
        "invoice_registrants.get",
        "houjin.get",
        "calendar.deadlines",
        "disaster.active_programs",
        "disaster.match",
        "disaster.catalog",
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

    return str(bcrypt.hashpw(raw_key.encode("utf-8"), bcrypt.gensalt(_BCRYPT_COST)).decode("ascii"))


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

        return bool(bcrypt.checkpw(raw_key.encode("utf-8"), stored_bcrypt_hash.encode("ascii")))
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
# Three tiers exist at runtime on an authenticated key:
#   "free"  — DUNNING DEMOTE state (customer whose card is failing). Short
#             daily cap via RATE_LIMIT_FREE_PER_DAY (default 100). NOT the
#             public anonymous Free tier (that lives in anon_rate_limit,
#             3/day per IP, applied via AnonIpLimitDep).
#   "paid"  — metered via Stripe usage_records at ¥3/req, no 429 enforcement.
#   "trial" — email-only 14d / 200 req hard cap, no Stripe. The cap is
#             enforced synchronously in _enforce_quota against the
#             api_keys.trial_requests_used counter (see TRIAL_REQUEST_CAP
#             below) — the daily cron sweep is belt-and-suspenders only.
#             The 'trial_request_cap' settings attr is sentinel-only; the
#             actual cap is the TRIAL_REQUEST_CAP module-level constant.
TIER_LIMITS = {
    "free": ("rate_limit_free_per_day", False),
    "paid": (None, True),
    "trial": ("trial_request_cap", False),
}

# Hard cap on a trial key's lifetime request count. Mirrors
# api/signup.py::TRIAL_REQUEST_CAP — duplicated here so the request hot
# path (deps.require_key → _enforce_quota) does NOT pull api/signup into
# the import graph (signup.py depends on api.deps; importing back the
# other way would cycle).
TRIAL_REQUEST_CAP = 200

# Per-call quantity hard cap for log_usage. Defends against a typo turning
# a single ¥3 request into ¥30M of metered billing — bulk_evaluate, dd_export
# bundle fees, and any future N-weighted tool all flow through log_usage,
# so a bad caller passing `quantity=10_000_000` would otherwise punch
# straight through to Stripe usage_records. 100,000 units = ¥300,000 per
# call which is generous enough for legitimate large-bundle exports while
# still imposing a sane ceiling. The clamp is applied in BOTH the inline
# log_usage path and the deferred _record_usage_async path so neither can
# be bypassed.
_QUANTITY_MAX: int = 100_000

# Public landing page that 429-ing trial keys are pointed at. Same string
# the day-11 nudge + day-14 expired email use, so a user who hits the cap
# and a user who runs out the clock see the same destination.
TRIAL_UPGRADE_URL = "https://jpcite.com/pricing.html?from=trial#api-paid"


def _insert_usage_event(
    conn: sqlite3.Connection,
    *,
    key_hash: str,
    endpoint: str,
    status_code: int,
    metered: bool,
    digest: str | None,
    latency_ms: int | None,
    result_count: int | None,
    client_tag: str | None,
    quantity: int,
    billing_idempotency_key: str | None,
    tokens_saved_estimated: int | None,
) -> tuple[int | None, bool]:
    """Insert usage_events, de-duping logical Idempotency-Key retries.

    Returns ``(usage_event_id, inserted)``. ``inserted=False`` means this
    logical request was already recorded; callers may retry Stripe sync with
    the same idempotency key, but must not advance local caps again.
    """
    ts = datetime.now(UTC).isoformat()

    def _execute_insert(*, include_billing_key: bool, include_tokens_saved: bool) -> sqlite3.Cursor:
        columns = [
            "key_hash",
            "endpoint",
            "ts",
            "status",
            "metered",
            "params_digest",
            "latency_ms",
            "result_count",
            "client_tag",
            "quantity",
        ]
        values: list[Any] = [
            key_hash,
            endpoint,
            ts,
            status_code,
            1 if metered else 0,
            digest,
            latency_ms,
            result_count,
            client_tag,
            quantity,
        ]
        if include_billing_key:
            columns.append("billing_idempotency_key")
            values.append(billing_idempotency_key)
        if include_tokens_saved:
            columns.append("tokens_saved_estimated")
            values.append(tokens_saved_estimated)
        placeholders = ",".join("?" for _ in columns)
        return conn.execute(
            f"INSERT INTO usage_events({','.join(columns)}) VALUES ({placeholders})",  # noqa: S608
            values,
        )

    include_billing_key = billing_idempotency_key is not None
    include_tokens_saved = tokens_saved_estimated is not None
    while True:
        try:
            cur = _execute_insert(
                include_billing_key=include_billing_key,
                include_tokens_saved=include_tokens_saved,
            )
            return cur.lastrowid, True
        except sqlite3.IntegrityError:
            if not include_billing_key:
                raise
            row = conn.execute(
                "SELECT id FROM usage_events "
                "WHERE key_hash = ? AND billing_idempotency_key = ? "
                "ORDER BY id ASC LIMIT 1",
                (key_hash, billing_idempotency_key),
            ).fetchone()
            return (int(row[0]) if row else None), False
        except sqlite3.OperationalError as exc:
            message = str(exc)
            if include_tokens_saved and "tokens_saved_estimated" in message:
                include_tokens_saved = False
                continue
            if include_billing_key and "billing_idempotency_key" in message:
                include_billing_key = False
                continue
            raise


def _existing_usage_event_for_billing_key(
    conn: sqlite3.Connection,
    *,
    key_hash: str | None,
    billing_idempotency_key: str | None,
) -> int | None:
    """Return an existing usage event for an idempotent retry, if any."""

    if not key_hash or not billing_idempotency_key:
        return None
    try:
        row = conn.execute(
            "SELECT id FROM usage_events "
            "WHERE key_hash = ? AND billing_idempotency_key = ? "
            "ORDER BY id ASC LIMIT 1",
            (key_hash, billing_idempotency_key),
        ).fetchone()
    except sqlite3.OperationalError as exc:
        if "billing_idempotency_key" not in str(exc):
            raise
        return None
    return int(row[0]) if row else None


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
        key_id: int | None = None,
        parent_key_id: int | None = None,
    ):
        self.key_hash = key_hash
        self.tier = tier
        self.customer_id = customer_id
        self.stripe_subscription_id = stripe_subscription_id
        # Migration 086 (parent/child fan-out): `key_id` mirrors the
        # api_keys.id column (rowid alias), `parent_key_id` is non-NULL
        # on child keys. _enforce_quota and CustomerCapMiddleware
        # aggregate metering at the TREE scope (parent + all siblings)
        # rather than per-row, so a SaaS partner's 1,000 child keys
        # share ONE Stripe subscription and ONE monthly_cap_yen.
        self.key_id = key_id
        self.parent_key_id = parent_key_id

    @property
    def metered(self) -> bool:
        return self.tier == "paid"

    @property
    def is_child(self) -> bool:
        """True iff this key is a sub-key of a parent (migration 086)."""
        return self.parent_key_id is not None

    @property
    def root_key_id(self) -> int | None:
        """Return the parent's id if this is a child, else this key's id.

        Used by `_enforce_quota` and `CustomerCapMiddleware` to scope the
        usage_events aggregation across the entire parent/child tree.
        Returns None for legacy rows where `id` was never backfilled
        (older keys created before migration 086 ran) — callers fall
        back to single-row scope in that case.
        """
        return self.parent_key_id if self.parent_key_id is not None else self.key_id


def require_metered_api_key(ctx: ApiContext, feature: str) -> None:
    """Require an authenticated paid key before running a billable workflow."""
    if ctx.key_hash is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            f"{feature} requires an authenticated API key",
        )
    if not ctx.metered:
        raise HTTPException(
            status.HTTP_402_PAYMENT_REQUIRED,
            detail={
                "detail": f"{feature} requires a paid metered API key",
                "required_tier": "paid",
                "current_tier": ctx.tier,
                "upgrade_url": TRIAL_UPGRADE_URL,
            },
        )


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
    #
    # Migration 086: also fetch parent_key_id + id so _enforce_quota and
    # the cap middleware can aggregate across the parent/child tree. A
    # child key inherits the parent's tier, stripe_subscription_id, and
    # monthly_cap_yen — but the cap is enforced at TREE scope, not row
    # scope, so a child cannot escape its share of the parent's quota.
    row = conn.execute(
        "SELECT tier, customer_id, stripe_subscription_id, revoked_at, "
        "key_hash_bcrypt, id, parent_key_id "
        "FROM api_keys WHERE key_hash = ?",
        (key_hash,),
    ).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid api key")
    if row["revoked_at"]:
        # Trial-tier revokes carry a recovery hint so the caller's
        # tooling can surface "your trial ended → here's how to keep
        # going at ¥3.30/req" instead of a generic 401 (Bug 4 from the
        # 2026-04-29 funnel audit). Paid-tier revokes still 401 with a
        # bare detail; the customer already has dashboard access via
        # session cookie and doesn't need a CTA.
        if row["tier"] == "trial":
            raise HTTPException(
                status.HTTP_401_UNAUTHORIZED,
                detail={
                    "detail": ("トライアル期間または上限に達したため API キーは失効しています。"),
                    "upgrade_url": TRIAL_UPGRADE_URL,
                    "cta_text_ja": "API キー発行で続行 (¥3.30/req)",
                    "trial_expired": True,
                },
            )
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "api key revoked")
    # Dual-path verify: when key_hash_bcrypt is non-NULL we MUST also
    # pass bcrypt.checkpw, otherwise an HMAC collision (cryptographically
    # implausible but defense-in-depth) cannot auth. Legacy rows have
    # NULL bcrypt and rely on HMAC PRIMARY KEY match alone (already
    # verified above by the row lookup succeeding).
    row_keys = row.keys() if hasattr(row, "keys") else ()
    bcrypt_hash = row["key_hash_bcrypt"] if "key_hash_bcrypt" in row_keys else None
    if bcrypt_hash and not verify_api_key_bcrypt(raw, bcrypt_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid api key")

    tier = row["tier"]
    # Migration 086: read id + parent_key_id when present. The columns
    # exist on every row from that migration onward, but legacy DB
    # snapshots (used in some test fixtures) may pre-date the column —
    # guard the lookup so a missing column key surfaces as None rather
    # than KeyError.
    row_keys = row.keys() if hasattr(row, "keys") else []
    key_id = row["id"] if "id" in row_keys else None
    parent_key_id = row["parent_key_id"] if "parent_key_id" in row_keys else None
    ctx = ApiContext(
        key_hash=key_hash,
        tier=tier,
        customer_id=row["customer_id"],
        stripe_subscription_id=row["stripe_subscription_id"],
        key_id=key_id,
        parent_key_id=parent_key_id,
    )
    _enforce_quota(conn, ctx)
    return ctx


def _seconds_until_utc_midnight(now: datetime | None = None) -> int:
    """Seconds remaining until the next UTC 00:00 boundary (rate-limit reset)."""
    now = now or datetime.now(UTC)
    tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return max(1, int((tomorrow - now).total_seconds()))


def _collect_tree_key_hashes(conn: sqlite3.Connection, ctx: ApiContext) -> list[str]:
    """Return every key_hash in the parent/child tree containing ctx.

    Migration 086 semantics: a child key inherits the parent's tier,
    stripe_subscription_id, and monthly_cap_yen — but the cap is
    enforced at TREE scope (parent + all siblings + the calling child)
    so a SaaS partner's 1,000 child keys cannot collectively burst past
    the parent's quota.

    Resolution order:
      * Legacy row (no id column / pre-086 row): return [ctx.key_hash]
        only — single-row scope, same as the historical behaviour.
      * Parent row (parent_key_id IS NULL): return parent's key_hash
        plus every child whose parent_key_id == ctx.key_id.
      * Child row (parent_key_id IS NOT NULL): walk to parent first,
        then collect parent + all siblings.

    The list always includes ctx.key_hash. Returned hashes are NOT
    filtered by revoked_at — usage_events are immutable history; even
    a revoked sibling's past consumption still counts toward the
    parent's monthly cap (otherwise revoking would silently refund spend).
    """
    if ctx.key_hash is None:
        return []
    root = ctx.root_key_id
    if root is None:
        # Legacy / not-yet-migrated row — single-key scope.
        return [ctx.key_hash]
    rows = conn.execute(
        "SELECT key_hash FROM api_keys WHERE id = ? OR parent_key_id = ?",
        (root, root),
    ).fetchall()
    hashes = [r["key_hash"] if hasattr(r, "keys") else r[0] for r in rows]
    if ctx.key_hash not in hashes:
        # Defensive: in tests / dev where rowid != id, ensure caller's
        # own key_hash is always in the result.
        hashes.append(ctx.key_hash)
    return hashes


def _daily_quota_used(conn: sqlite3.Connection, ctx: ApiContext) -> int:
    tree_hashes = _collect_tree_key_hashes(conn, ctx)
    if not tree_hashes:
        return 0
    bucket = _day_bucket()
    if len(tree_hashes) == 1:
        (used,) = conn.execute(
            "SELECT COALESCE(SUM(COALESCE(quantity, 1)), 0) "
            "FROM usage_events WHERE key_hash = ? AND ts >= ?",
            (tree_hashes[0], bucket),
        ).fetchone()
    else:
        placeholders = ",".join("?" * len(tree_hashes))
        (used,) = conn.execute(
            f"SELECT COALESCE(SUM(COALESCE(quantity, 1)), 0) FROM usage_events WHERE key_hash IN ({placeholders}) AND ts >= ?",  # noqa: S608 — placeholders only
            (*tree_hashes, bucket),
        ).fetchone()
    return int(used or 0)


def _raise_daily_limit_exceeded(ctx: ApiContext, daily_limit: int) -> NoReturn:
    raise HTTPException(
        status.HTTP_429_TOO_MANY_REQUESTS,
        f"daily limit of {daily_limit} exceeded for tier={ctx.tier}",
        headers={"Retry-After": str(_seconds_until_utc_midnight())},
    )


def _enforce_quota(conn: sqlite3.Connection, ctx: ApiContext) -> None:
    if ctx.key_hash is None:
        return
    limit_key, metered = TIER_LIMITS.get(ctx.tier, (None, False))
    if metered:
        return

    # Trial-tier hard cap. Reserve one request before the router runs so
    # concurrent calls cannot all pass at 199/200 and overshoot the public
    # "14 days / 200 requests" promise.
    if ctx.tier == "trial":
        row = conn.execute(
            "SELECT trial_expires_at FROM api_keys WHERE key_hash = ?",
            (ctx.key_hash,),
        ).fetchone()
        expires_raw = row["trial_expires_at"] if row else None
        if expires_raw:
            try:
                expires_at = datetime.fromisoformat(str(expires_raw).replace("Z", "+00:00"))
            except ValueError:
                expires_at = None
            if expires_at is not None and expires_at <= datetime.now(UTC):
                now_iso = datetime.now(UTC).isoformat()
                conn.execute(
                    "UPDATE api_keys SET revoked_at = ? WHERE key_hash = ? AND revoked_at IS NULL",
                    (now_iso, ctx.key_hash),
                )
                raise HTTPException(
                    status.HTTP_401_UNAUTHORIZED,
                    detail={
                        "detail": (
                            "トライアル期間または上限に達したため API キーは失効しています。"
                        ),
                        "upgrade_url": TRIAL_UPGRADE_URL,
                        "cta_text_ja": "API キー発行で続行 (¥3.30/req)",
                        "trial_expired": True,
                    },
                )
        txn_started = False
        try:
            if not conn.in_transaction:
                conn.execute("BEGIN IMMEDIATE")
                txn_started = True
            cur = conn.execute(
                "UPDATE api_keys "
                "SET trial_requests_used = COALESCE(trial_requests_used, 0) + 1 "
                "WHERE key_hash = ? "
                "AND COALESCE(trial_requests_used, 0) < ?",
                (ctx.key_hash, TRIAL_REQUEST_CAP),
            )
            row = conn.execute(
                "SELECT trial_requests_used FROM api_keys WHERE key_hash = ?",
                (ctx.key_hash,),
            ).fetchone()
            used = int(row["trial_requests_used"] or 0) if row else 0
            if cur.rowcount:
                if txn_started:
                    conn.execute("COMMIT")
                    txn_started = False
                return
            if txn_started:
                conn.execute("ROLLBACK")
                txn_started = False
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "error": "trial_request_cap_reached",
                    "trial_request_cap": TRIAL_REQUEST_CAP,
                    "trial_requests_used": used,
                    "trial_terms": (
                        f"トライアルは 14 日間または {TRIAL_REQUEST_CAP} リクエストまで無料です。"
                    ),
                    "upgrade_url": TRIAL_UPGRADE_URL,
                    "cta_text_ja": "API キー発行で続行 (¥3.30/req)",
                    "message": (
                        f"トライアルの上限 {TRIAL_REQUEST_CAP} リクエストに"
                        "達しました。¥3.30/req (税込) で続行できます。"
                    ),
                },
            )
        except HTTPException:
            if txn_started:
                with contextlib.suppress(Exception):
                    conn.execute("ROLLBACK")
            raise
        except Exception:
            if txn_started:
                with contextlib.suppress(Exception):
                    conn.execute("ROLLBACK")
            raise

    if limit_key is None:
        return
    daily_limit = getattr(settings, limit_key)

    if _daily_quota_used(conn, ctx) >= daily_limit:
        _raise_daily_limit_exceeded(ctx, daily_limit)


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
    payload = json.dumps(cleaned, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _derive_billing_event_idempotency_key(
    request_key: str,
    *,
    event_index: int,
    endpoint: str,
    params: dict[str, Any] | None,
    quantity: int,
    status_code: int,
) -> str:
    """Derive a stable Stripe/local idempotency key for one usage event.

    The HTTP middleware owns one key per logical request, but some endpoints
    record multiple billable usage_events in one request. This suffix keeps
    those events distinct while preserving deterministic replay behavior.
    """
    payload = json.dumps(
        {
            "endpoint": endpoint,
            "event_index": event_index,
            "params": params or {},
            "quantity": quantity,
            "status": status_code,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )
    suffix = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]
    return f"{request_key}:u{event_index}:{suffix}"


def _metered_cap_final_check(
    conn: sqlite3.Connection,
    *,
    key_hash: str | None,
    metered: bool,
    status_code: int,
    quantity: int,
) -> tuple[bool, bool]:
    """Serialize final metered billing against the customer monthly cap.

    Returns `(allowed, transaction_started)`. For successful metered calls we
    start `BEGIN IMMEDIATE`, re-read spend from usage_events, and only then let
    the caller insert the billable row. This prevents concurrent workers from
    both seeing the same pre-request count and overbilling past the cap.
    Failures are fail-closed: the response may already be served, but billing
    is skipped.
    """
    if key_hash is None or not metered or status_code >= 400:
        return True, False
    txn_started = False
    try:
        if not conn.in_transaction:
            conn.execute("BEGIN IMMEDIATE")
            txn_started = True
        from jpintel_mcp.api.middleware.customer_cap import (
            metered_charge_within_cap,
        )

        if metered_charge_within_cap(conn, key_hash, quantity):
            return True, txn_started
        if txn_started:
            conn.execute("ROLLBACK")
            txn_started = False
        logger.info("usage_cap_final_check_blocked key_hash=%s", key_hash[:8])
        return False, False
    except Exception:  # noqa: BLE001
        if txn_started:
            with contextlib.suppress(Exception):
                conn.execute("ROLLBACK")
        logger.exception("usage_cap_final_check_failed")
        return False, False


def _daily_quota_final_check(
    conn: sqlite3.Connection,
    ctx: ApiContext,
    *,
    status_code: int,
    quantity: int,
) -> tuple[bool, bool]:
    """Reserve authenticated non-metered daily quota for the exact billable quantity."""
    if ctx.key_hash is None or status_code >= 400:
        return True, False
    limit_key, metered = TIER_LIMITS.get(ctx.tier, (None, False))
    if metered or limit_key is None or ctx.tier == "trial":
        return True, False
    daily_limit = getattr(settings, limit_key)
    txn_started = False
    try:
        if not conn.in_transaction:
            conn.execute("BEGIN IMMEDIATE")
            txn_started = True
        if _daily_quota_used(conn, ctx) + quantity <= daily_limit:
            return True, txn_started
        if txn_started:
            conn.execute("ROLLBACK")
            txn_started = False
        return False, False
    except Exception:  # noqa: BLE001
        if txn_started:
            with contextlib.suppress(Exception):
                conn.execute("ROLLBACK")
        logger.exception("daily_quota_final_check_failed")
        return False, False


def _record_usage_async(
    key_hash: str,
    endpoint: str,
    status_code: int,
    metered: bool,
    digest: str | None,
    latency_ms: int | None,
    result_count: int | None,
    stripe_subscription_id: str | None,
    tier: str | None = None,
    client_tag: str | None = None,
    quantity: int = 1,
    audit_seal: dict[str, Any] | None = None,
    billing_idempotency_key: str | None = None,
    tokens_saved_estimated: int | None = None,
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

    Migration 085: ``client_tag`` is the validated X-Client-Tag header
    forwarded from ``ClientTagMiddleware`` via ``request.state.client_tag``.
    NULL when the caller did not pass the header — the 90% case.

    ``quantity`` (default 1) is the per-request weight for Stripe metered
    billing. Bulk endpoints (``POST /v1/programs/batch``) pass
    ``quantity=len(unified_ids)`` so the Stripe ``usage_record`` is N
    units. Local ``usage_events`` rows still write a single audit row —
    Stripe-side weight + a single local row gives auditors a clean
    "1 batch request, N billed units" mapping. We coerce to >= 1
    defensively; an explicit 0 from a caller is treated as 1.

    Migration 089 (税理士事務所 bundle): when ``audit_seal`` is supplied
    (built by ``api._audit_seal.build_seal``), the deferred path also
    persists it to the ``audit_seals`` table for 7-year statutory
    retention per 税理士法 §41 / 法人税法 §150-2 / 所得税法 §148. The
    seal write is best-effort — a missing migration 089 never blocks
    the response or the usage_events INSERT.

    Upper bound: ``quantity`` is hard-clamped at ``_QUANTITY_MAX`` to
    defend against a typo turning ¥3 into ¥30M. The clamp is applied
    twice (inline ``log_usage`` AND the deferred path) so neither code
    path can be bypassed.
    """
    if quantity < 1:
        quantity = 1
    if quantity > _QUANTITY_MAX:
        quantity = _QUANTITY_MAX
    usage_event_id: int | None = None
    usage_event_inserted = False
    try:
        conn = connect()
    except Exception:  # noqa: BLE001
        conn = None
    if conn is not None:
        usage_txn_started = False
        try:
            usage_event_id = _existing_usage_event_for_billing_key(
                conn,
                key_hash=key_hash,
                billing_idempotency_key=billing_idempotency_key,
            )
            if usage_event_id is None:
                allowed, usage_txn_started = _metered_cap_final_check(
                    conn,
                    key_hash=key_hash,
                    metered=metered,
                    status_code=status_code,
                    quantity=quantity,
                )
                if not allowed:
                    return
                usage_event_id, usage_event_inserted = _insert_usage_event(
                    conn,
                    key_hash=key_hash,
                    endpoint=endpoint,
                    status_code=status_code,
                    metered=metered,
                    digest=digest,
                    latency_ms=latency_ms,
                    result_count=result_count,
                    client_tag=client_tag,
                    quantity=quantity,
                    billing_idempotency_key=billing_idempotency_key,
                    tokens_saved_estimated=tokens_saved_estimated,
                )
                if usage_event_inserted:
                    conn.execute(
                        "UPDATE api_keys SET last_used_at = ? WHERE key_hash = ?",
                        (datetime.now(UTC).isoformat(), key_hash),
                    )
                # Migration 089: persist audit_seal alongside usage_events for
                # 7-year statutory retention (税理士事務所 bundle). Best-effort
                # — a missing migration 089 is swallowed inside persist_seal.
                if audit_seal is not None and usage_event_inserted:
                    try:
                        from jpintel_mcp.api._audit_seal import persist_seal

                        persist_seal(conn, seal=audit_seal, api_key_hash=key_hash)
                    except Exception:  # noqa: BLE001
                        pass
                if usage_txn_started:
                    conn.execute("COMMIT")
                    usage_txn_started = False
        except Exception:  # noqa: BLE001
            if usage_txn_started:
                with contextlib.suppress(Exception):
                    conn.execute("ROLLBACK")
            usage_event_id = None
        finally:
            with contextlib.suppress(Exception):
                conn.close()

    # Fire-and-forget Stripe usage_records report for metered ("paid") tier.
    # 4xx/5xx are not billed. Local import prevents a hard dep on stripe
    # during tests that construct ApiContext directly without Stripe env.
    # The usage_event_id is passed so the worker can mark the row as
    # synced (stripe_record_id + stripe_synced_at) on success — required
    # for Fly volume DR replay-from-Stripe (audit a37f6226fe319dc40).
    if usage_event_id is not None and usage_event_inserted:
        _note_customer_cap_cache(
            key_hash,
            metered=metered,
            status_code=status_code,
            quantity=quantity,
        )
    if metered and status_code < 400 and stripe_subscription_id and usage_event_id is not None:
        try:
            from jpintel_mcp.billing.stripe_usage import report_usage_async

            stripe_kwargs: dict[str, Any] = {
                "quantity": quantity,
                "usage_event_id": usage_event_id,
            }
            if billing_idempotency_key is not None:
                stripe_kwargs["idempotency_key"] = billing_idempotency_key
            report_usage_async(stripe_subscription_id, **stripe_kwargs)
        except Exception:  # noqa: BLE001
            pass


def _note_customer_cap_cache(
    key_hash: str | None,
    *,
    metered: bool,
    status_code: int,
    quantity: int,
) -> None:
    """Advance the soft monthly-cap cache after a billable success."""
    if key_hash is None or not metered or status_code >= 400:
        return
    try:
        from jpintel_mcp.api.middleware.customer_cap import note_cap_usage

        note_cap_usage(key_hash, quantity)
    except Exception:
        logging.getLogger("jpintel.cap").warning(
            "cap_cache_increment_failed",
            exc_info=True,
        )


def log_usage(
    conn: sqlite3.Connection,
    ctx: ApiContext,
    endpoint: str,
    status_code: int = 200,
    params: dict[str, Any] | None = None,
    latency_ms: int | None = None,
    result_count: int | None = None,
    background_tasks: BackgroundTasks | None = None,
    request: Request | None = None,
    client_tag: str | None = None,
    quantity: int = 1,
    response_body: Any = None,
    issue_audit_seal: bool = False,
    strict_metering: bool = False,
    strict_audit_seal: bool = False,
) -> dict[str, Any] | None:
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

    Upper bound: ``quantity`` is hard-clamped at ``_QUANTITY_MAX`` (100,000)
    here AND inside ``_record_usage_async`` so a typo turning ¥3 into ¥30M
    cannot leak through either path.
    """
    if ctx.key_hash is None:
        return None
    if quantity < 1:
        quantity = 1
    if quantity > _QUANTITY_MAX:
        quantity = _QUANTITY_MAX
    digest = compute_params_digest(endpoint, params)

    # Migration 085: pull the validated X-Client-Tag stashed on
    # request.state by ClientTagMiddleware. Caller may also pass an
    # explicit client_tag (cron jobs, tests). When both are absent we
    # write NULL — the 90% case.
    if client_tag is None and request is not None:
        client_tag = getattr(request.state, "client_tag", None)

    try:
        from jpintel_mcp.api.idempotency_context import (
            billing_event_index,
            billing_idempotency_key,
        )

        request_billing_key = billing_idempotency_key.get()
        if request_billing_key is not None:
            event_index = billing_event_index.get()
            billing_event_index.set(event_index + 1)
            billing_key = _derive_billing_event_idempotency_key(
                request_billing_key,
                event_index=event_index,
                endpoint=endpoint,
                params=params,
                quantity=quantity,
                status_code=status_code,
            )
        else:
            billing_key = None
    except Exception:  # pragma: no cover - defensive import guard
        billing_key = None

    # Migration 089: build the audit_seal envelope for the response IFF the
    # caller opted in (issue_audit_seal=True). Sealing is opt-in because
    # most internal endpoints (dashboard reads, /healthz) carry no audit
    # value — only customer-facing data tools surface a seal. The seal is
    # built synchronously here so the caller can embed it in the response
    # body; the DB persist runs in the deferred path so it never blocks.
    audit_seal: dict[str, Any] | None = None
    if issue_audit_seal and status_code < 400:
        try:
            from jpintel_mcp.api._audit_seal import build_seal

            audit_seal = build_seal(
                endpoint=endpoint,
                request_params=params,
                response_body=response_body,
                client_tag=client_tag,
                api_key_hash=ctx.key_hash,
            )
        except Exception:  # noqa: BLE001
            audit_seal = None
            if strict_audit_seal and ctx.metered:
                raise HTTPException(
                    status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail={
                        "code": "audit_seal_persist_failed",
                        "message": (
                            "This paid response was not delivered because the "
                            "audit seal could not be created."
                        ),
                    },
                ) from None

    tokens_saved_estimated = (
        estimate_tokens_saved(params, response_body)
        if status_code < 400 and params is not None and response_body is not None
        else None
    )

    limit_key, ctx_metered = TIER_LIMITS.get(ctx.tier, (None, False))
    requires_inline_daily_quota = (
        ctx.key_hash is not None
        and status_code < 400
        and not ctx_metered
        and limit_key is not None
        and ctx.tier != "trial"
    )

    if (
        background_tasks is not None
        and billing_key is None
        and not strict_metering
        and not requires_inline_daily_quota
    ):
        # Hot path: defer all writes until after response flush. Requests
        # protected by HTTP Idempotency-Key write inline below so the usage row
        # is durable before the idempotency middleware caches a 2xx response.
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
            ctx.tier,
            client_tag,
            quantity,
            audit_seal,
            billing_key,
            tokens_saved_estimated,
        )
        return audit_seal

    # Legacy / non-request path: inline writes on the supplied conn.
    usage_event_id: int | None = None
    usage_event_inserted = False
    existing_usage_event_id = _existing_usage_event_for_billing_key(
        conn,
        key_hash=ctx.key_hash,
        billing_idempotency_key=billing_key,
    )
    if existing_usage_event_id is not None:
        usage_event_id = existing_usage_event_id
    else:
        usage_txn_started = False
        allowed, usage_txn_started = _metered_cap_final_check(
            conn,
            key_hash=ctx.key_hash,
            metered=ctx.metered,
            status_code=status_code,
            quantity=quantity,
        )
        if not allowed:
            if strict_metering and ctx.metered and status_code < 400:
                raise HTTPException(
                    status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail={
                        "code": "billing_cap_final_check_failed",
                        "message": (
                            "This paid response was not delivered because the "
                            "final billing-cap check rejected the metered charge."
                        ),
                    },
                )
            return audit_seal
        allowed, daily_quota_txn_started = _daily_quota_final_check(
            conn,
            ctx,
            status_code=status_code,
            quantity=quantity,
        )
        if daily_quota_txn_started:
            usage_txn_started = True
        if not allowed:
            limit_key, _ = TIER_LIMITS.get(ctx.tier, (None, False))
            daily_limit = getattr(settings, limit_key) if limit_key else 0
            _raise_daily_limit_exceeded(ctx, daily_limit)
        try:
            usage_event_id, usage_event_inserted = _insert_usage_event(
                conn,
                key_hash=ctx.key_hash,
                endpoint=endpoint,
                status_code=status_code,
                metered=ctx.metered,
                digest=digest,
                latency_ms=latency_ms,
                result_count=result_count,
                client_tag=client_tag,
                quantity=quantity,
                billing_idempotency_key=billing_key,
                tokens_saved_estimated=tokens_saved_estimated,
            )
            if usage_event_inserted:
                conn.execute(
                    "UPDATE api_keys SET last_used_at = ? WHERE key_hash = ?",
                    (datetime.now(UTC).isoformat(), ctx.key_hash),
                )
            # Migration 089: persist the seal alongside the inline usage_events row.
            if audit_seal is not None and usage_event_inserted:
                try:
                    from jpintel_mcp.api._audit_seal import persist_seal

                    persist_seal(conn, seal=audit_seal, api_key_hash=ctx.key_hash)
                except Exception:  # noqa: BLE001
                    audit_seal = None
                    if strict_audit_seal and ctx.metered and status_code < 400:
                        raise HTTPException(
                            status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail={
                                "code": "audit_seal_persist_failed",
                                "message": (
                                    "This paid response was not delivered because the "
                                    "audit seal could not be persisted."
                                ),
                            },
                        ) from None
            if usage_txn_started:
                conn.execute("COMMIT")
                usage_txn_started = False
        except Exception:
            if usage_txn_started:
                with contextlib.suppress(Exception):
                    conn.execute("ROLLBACK")
            raise
    if strict_metering and ctx.metered and status_code < 400 and usage_event_id is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "billing_audit_row_unavailable",
                "message": (
                    "This paid response was not delivered because the billing "
                    "audit row could not be confirmed."
                ),
            },
        )
    # Fire-and-forget Stripe usage_records report for metered ("paid") tier.
    # 4xx/5xx are not billed. Local import prevents a hard dep on stripe
    # during tests that construct ApiContext directly without Stripe env.
    # The usage_event_id is passed so the worker can mark the row as
    # synced (stripe_record_id + stripe_synced_at) on success — required
    # for Fly volume DR replay-from-Stripe (audit a37f6226fe319dc40).
    if (
        ctx.metered
        and status_code < 400
        and ctx.stripe_subscription_id
        and usage_event_id is not None
    ):
        try:
            from jpintel_mcp.billing.stripe_usage import report_usage_async

            stripe_kwargs: dict[str, Any] = {
                "quantity": quantity,
                "usage_event_id": usage_event_id,
            }
            if billing_key is not None:
                stripe_kwargs["idempotency_key"] = billing_key
            report_usage_async(ctx.stripe_subscription_id, **stripe_kwargs)
        except Exception:  # noqa: BLE001
            pass
    if usage_event_inserted:
        _note_customer_cap_cache(
            ctx.key_hash,
            metered=ctx.metered,
            status_code=status_code,
            quantity=quantity,
        )
    return audit_seal


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
    payload = f"{ip}|{day}|{salt}".encode()
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
    with contextlib.suppress(sqlite3.OperationalError):
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


ApiContextDep = Annotated[ApiContext, Depends(require_key)]
DbDep = Annotated[sqlite3.Connection, Depends(get_db)]
