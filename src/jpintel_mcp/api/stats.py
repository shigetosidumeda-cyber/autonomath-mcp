"""Public stats endpoint (P5-ι, brand 5-pillar transparent + anti-aggregator).

GET /v1/stats/coverage   — dataset row counts (jpintel.db only)
GET /v1/stats/freshness  — per-source min / max / avg fetch interval
GET /v1/stats/usage      — past-30-day anonymous request count (cumulative)

No auth, no anon-quota gating (same posture as /v1/meta/freshness — these
are first-class transparency surfaces, not internal debug views). Results
are cached for 5 minutes so a launch-traffic spike on the landing page
doesn't issue 1k SQL plans/sec for the same numbers.

PII posture (INV-21):
  * coverage exposes only COUNT(*) — no row content.
  * freshness exposes only MIN/MAX/AVG of `*_fetched_at` — no source URLs.
  * usage exposes only daily aggregate request counts; key_hash is never
    looked at and never returned.
"""
from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter
from fastapi.responses import RedirectResponse

from jpintel_mcp.api._response_models import (
    CoverageResponse,
    DataQualityResponse,
    FreshnessResponse,
    UsageResponse,
)
from jpintel_mcp.api.deps import DbDep  # noqa: TC001 (FastAPI Depends resolution)
from jpintel_mcp.api.uncertainty import score_fact
from jpintel_mcp.cache.l4 import canonical_cache_key, get_or_compute, invalidate_tool

if TYPE_CHECKING:
    from collections.abc import Callable

router = APIRouter(prefix="/v1/stats", tags=["stats", "transparency"])


# ---------------------------------------------------------------------------
# 5-minute cache via the unified L4 store (β3 wiring).
# ---------------------------------------------------------------------------
#
# Previously a per-process inline ``_cache: dict[str, tuple[float, dict]]`` —
# C3 audit flagged it as a duplicate implementation of the L4 query-cache
# helper (``jpintel_mcp.cache.l4.get_or_compute``). Routing through the
# unified helper:
#   * survives uvicorn worker restarts (sqlite-backed, not in-memory),
#   * gives every stats endpoint the same TTL semantics as the rest of
#     the tool surface, so debugging cache hits is a single grep,
#   * cuts the duplicated `(expires_at, payload)` tuple plumbing.
# Tool name 'api.stats' partitions the rows so ``invalidate_tool`` here
# only nukes the stats family — never the broader L4 query cache.

_CACHE_TTL_SECONDS = 300  # 5 minutes
_STATS_TOOL_NAME = "api.stats"


_L4_SCHEMA_DDL = """
CREATE TABLE IF NOT EXISTS l4_query_cache (
    cache_key   TEXT PRIMARY KEY,
    tool_name   TEXT NOT NULL,
    params_json TEXT NOT NULL,
    result_json TEXT NOT NULL,
    hit_count   INTEGER NOT NULL DEFAULT 0,
    last_hit_at TEXT,
    ttl_seconds INTEGER NOT NULL DEFAULT 86400,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_l4_cache_tool ON l4_query_cache(tool_name);
CREATE INDEX IF NOT EXISTS idx_l4_cache_lru ON l4_query_cache(last_hit_at);
CREATE INDEX IF NOT EXISTS idx_l4_cache_ttl
    ON l4_query_cache(created_at, ttl_seconds);
"""


def _ensure_l4_table() -> None:
    """Idempotently create the L4 cache table when missing.

    Production carries the table via ``scripts/migrations/043_l4_cache.sql``
    applied by ``scripts/migrate.py``. Test fixtures only run schema.sql,
    so the cache helper has to self-heal on first call. The DDL block is
    a verbatim copy of the migration body (sans bookkeeping comments) so
    the runtime shape stays in sync — every CREATE is IF NOT EXISTS, so
    re-applying is a no-op if the migration ran first.
    """
    from jpintel_mcp.db.session import connect

    conn = connect()
    try:
        conn.executescript(_L4_SCHEMA_DDL)
    finally:
        conn.close()


def _cache_get_or_compute(
    key: str, compute: Callable[[], dict[str, Any]]
) -> dict[str, Any]:
    """Thin shim over ``cache.l4.get_or_compute`` for the stats endpoints.

    `key` is a short endpoint label (coverage / freshness / usage). It is
    canonicalised through ``canonical_cache_key`` together with the tool
    name so cross-endpoint collisions are impossible.

    Self-heals against missing L4 table by running the migration DDL
    once on first OperationalError, then retrying. Production hits the
    happy path on every call; tests only pay the create-table cost the
    first time.
    """
    params = {"key": key}
    cache_key = canonical_cache_key(_STATS_TOOL_NAME, params)
    try:
        return get_or_compute(
            cache_key=cache_key,
            tool=_STATS_TOOL_NAME,
            params=params,
            compute=compute,
            ttl=_CACHE_TTL_SECONDS,
        )
    except sqlite3.OperationalError as exc:
        if "no such table" not in str(exc):
            raise
        _ensure_l4_table()
        return get_or_compute(
            cache_key=cache_key,
            tool=_STATS_TOOL_NAME,
            params=params,
            compute=compute,
            ttl=_CACHE_TTL_SECONDS,
        )


def _reset_stats_cache() -> None:
    """Test hook — clear all stats rows from the L4 cache between scenarios.

    Self-heals against a missing l4_query_cache table by creating it
    first. Idempotent — production has the table, tests don't, both
    paths converge cleanly."""
    try:
        invalidate_tool(_STATS_TOOL_NAME)
    except sqlite3.OperationalError as exc:
        if "no such table" not in str(exc):
            raise
        _ensure_l4_table()
        invalidate_tool(_STATS_TOOL_NAME)


# ---------------------------------------------------------------------------
# /v1/stats/coverage — dataset row counts
# ---------------------------------------------------------------------------
#
# Returns one COUNT(*) per top-level table. Tables that don't exist on a
# given volume (e.g. fresh test DB without expansion migrations applied)
# return 0 rather than raising — the endpoint must be live even before the
# expansion data lands.

# Table → output key. Order matches v8 plan brand-pillar copy (programs first).
_COVERAGE_TABLES: list[tuple[str, str]] = [
    ("programs", "programs"),
    ("case_studies", "case_studies"),
    ("loan_programs", "loan_programs"),
    ("enforcement_cases", "enforcement_cases"),
    ("exclusion_rules", "exclusion_rules"),
    ("laws", "laws_jpintel"),
    ("tax_rulesets", "tax_rulesets"),
    ("court_decisions", "court_decisions"),
    ("bids", "bids"),
    ("invoice_registrants", "invoice_registrants"),
]


def _safe_count(conn: sqlite3.Connection, table: str) -> int:
    try:
        (n,) = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()  # noqa: S608
        return int(n)
    except sqlite3.OperationalError:
        # Table missing on this volume — surface 0, never crash.
        return 0


@router.get("/coverage", response_model=CoverageResponse)
def stats_coverage(conn: DbDep) -> dict[str, Any]:
    def _compute() -> dict[str, Any]:
        out: dict[str, Any] = {}
        for table, key in _COVERAGE_TABLES:
            out[key] = _safe_count(conn, table)
        out["generated_at"] = (
            datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        )
        return out

    return _cache_get_or_compute("coverage", _compute)


# ---------------------------------------------------------------------------
# /v1/stats/freshness — per-source min/max/avg fetched_at
# ---------------------------------------------------------------------------
#
# Each table that carries a `*_fetched_at` column reports min, max, and a
# rough avg-interval estimate (= (max - min) / max(1, count - 1)). Tables
# with no rows or no fetched_at column return null. AVG-interval is in
# whole days — sub-day variation isn't actionable for an anti-staleness
# brand signal.

# (table, fetched_at_column, output_key). When the table has no fetched_at
# column at all, set the second element to None — the endpoint will skip
# the AVG calc and report only count.
_FRESHNESS_SOURCES: list[tuple[str, str | None, str]] = [
    ("programs", "source_fetched_at", "programs"),
    ("case_studies", "fetched_at", "case_studies"),
    ("loan_programs", "fetched_at", "loan_programs"),
    ("enforcement_cases", "fetched_at", "enforcement_cases"),
    ("laws", "fetched_at", "laws"),
    ("tax_rulesets", "fetched_at", "tax_rulesets"),
    ("court_decisions", "fetched_at", "court_decisions"),
    ("bids", "fetched_at", "bids"),
    ("invoice_registrants", "fetched_at", "invoice_registrants"),
]


def _parse_iso(val: str | None) -> datetime | None:
    if not val:
        return None
    s = val.strip()
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt
    except ValueError:
        # Fallback: date-only string.
        try:
            return datetime.fromisoformat(s[:10]).replace(tzinfo=UTC)
        except ValueError:
            return None


def _source_freshness(
    conn: sqlite3.Connection, table: str, column: str | None
) -> dict[str, Any]:
    if column is None:
        return {"min": None, "max": None, "count": 0, "avg_interval_days": None}
    try:
        row = conn.execute(
            f"SELECT MIN({column}) AS mn, MAX({column}) AS mx, "  # noqa: S608
            f"COUNT({column}) AS cnt FROM {table}"
        ).fetchone()
    except sqlite3.OperationalError:
        return {"min": None, "max": None, "count": 0, "avg_interval_days": None}
    if row is None:
        return {"min": None, "max": None, "count": 0, "avg_interval_days": None}
    mn, mx, cnt = row[0], row[1], int(row[2] or 0)
    avg_days: float | None = None
    if cnt > 1:
        dt_min = _parse_iso(mn)
        dt_max = _parse_iso(mx)
        if dt_min and dt_max:
            span_days = max(0.0, (dt_max - dt_min).total_seconds() / 86400.0)
            avg_days = round(span_days / max(1, cnt - 1), 4)
    return {
        "min": mn,
        "max": mx,
        "count": cnt,
        "avg_interval_days": avg_days,
    }


@router.get("/freshness", response_model=FreshnessResponse)
def stats_freshness(conn: DbDep) -> dict[str, Any]:
    def _compute() -> dict[str, Any]:
        sources: dict[str, Any] = {}
        for table, column, key in _FRESHNESS_SOURCES:
            sources[key] = _source_freshness(conn, table, column)
        return {
            "sources": sources,
            "generated_at": (
                datetime.now(UTC)
                .replace(microsecond=0)
                .isoformat()
                .replace("+00:00", "Z")
            ),
        }

    return _cache_get_or_compute("freshness", _compute)


# ---------------------------------------------------------------------------
# /v1/stats/usage — past 30 days, anonymous, cumulative
# ---------------------------------------------------------------------------
#
# Aggregates `usage_events` by date (YYYY-MM-DD prefix of `ts`) for the
# last 30 days. PII posture: usage_events does carry key_hash, but we
# never read it here — only the date column is selected, then aggregated.
# Output is the daily count + the cumulative sum, suitable for a
# brand-transparency chart.

def _date_buckets(today: datetime, days: int) -> list[str]:
    return [
        (today - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(days - 1, -1, -1)
    ]


@router.get("/usage", response_model=UsageResponse)
def stats_usage(conn: DbDep) -> dict[str, Any]:
    def _compute() -> dict[str, Any]:
        today = datetime.now(UTC)
        buckets = _date_buckets(today, 30)
        floor = buckets[0]
        try:
            rows = conn.execute(
                "SELECT substr(ts, 1, 10) AS day, COUNT(*) AS n "
                "FROM usage_events WHERE ts >= ? "
                "GROUP BY substr(ts, 1, 10)",
                (floor,),
            ).fetchall()
        except sqlite3.OperationalError:
            rows = []
        per_day = {r["day"]: int(r["n"]) for r in rows} if rows else {}
        daily = [{"date": d, "count": per_day.get(d, 0)} for d in buckets]
        cumulative = 0
        for entry in daily:
            cumulative += entry["count"]
            entry["cumulative"] = cumulative
        return {
            "window_days": 30,
            "since": floor,
            "until": today.strftime("%Y-%m-%d"),
            "daily": daily,
            "total": cumulative,
            "generated_at": (
                today.replace(microsecond=0).isoformat().replace("+00:00", "Z")
            ),
        }

    return _cache_get_or_compute("usage", _compute)


# ---------------------------------------------------------------------------
# /v1/stats/data_quality — per-fact Bayesian uncertainty rollup (O8)
# ---------------------------------------------------------------------------
#
# Aggregates the `am_uncertainty_view` SQL view (migration 069) into a
# launch-day transparency surface:
#   - mean score across all facts (with score-band histogram)
#   - source license distribution
#   - freshness bucket distribution
#   - per-field_kind mean score + count
#   - cross-source agreement facts vs total facts
#
# Cached 5 minutes (same TTL as coverage/freshness). Pure-math —
# never calls Anthropic. Honest disclosure: when the migration view
# is missing on the volume, every aggregate returns a zero/empty
# default and we still return 200; clients distinguish via the
# `fact_count_total` value.
#
# PII posture: aggregates only counts and means, never raw values.

# Freshness buckets in days. Tuples are (label, max_inclusive_days).
# `None` upper bound means "older than the last finite bucket"; `unknown`
# captures NULL days_since_fetch (source_id IS NULL).
_FRESHNESS_BUCKETS: list[tuple[str, int | None]] = [
    ("<=30d", 30),
    ("31-180d", 180),
    ("181-365d", 365),
    (">365d", None),
]


def _freshness_bucket_for(days: int | None) -> str:
    if days is None or days < 0:
        return "unknown"
    for label, upper in _FRESHNESS_BUCKETS:
        if upper is None:
            return label
        if days <= upper:
            return label
    return ">365d"


def _open_autonomath_conn() -> sqlite3.Connection | None:
    """Open a short-lived sqlite3 handle on autonomath.db.

    The O8 view (`am_uncertainty_view`) lives on autonomath.db; the
    request-scoped `DbDep` points at jpintel.db. We open + close
    inline to avoid bleeding a second handle into the request context.
    """
    try:
        from jpintel_mcp.config import settings
        path = settings.autonomath_db_path
        c = sqlite3.connect(str(path))
        c.row_factory = sqlite3.Row
        return c
    except Exception:
        return None


def _am_source_fallback_aggregates(
    am_conn: sqlite3.Connection,
) -> dict[str, Any] | None:
    """Honest-zero fallback: aggregate ``am_source`` directly when the
    O8 view returns 0 facts.

    Background (M&A advisor walk 2026-04-29): when ``am_uncertainty_view``
    is missing or empty on a given DB volume, the previous code returned
    100% zeros, which prospects read as "data quality is broken". That's
    a worse signal than the truth — we DO have license + freshness data
    on every am_source row (97,272 rows, 99.17% license-filled per
    migration 049). This fallback computes the same shape from the
    underlying am_source table so the rollup stays useful even before
    O8 lands. The trade-off: ``mean_score`` stays None (we can't compute
    a per-fact score without field_kind), but ``license_breakdown`` and
    ``freshness_buckets`` come back populated and honest.

    Returns ``None`` if the table is missing entirely; an empty
    dict if the table exists but holds 0 rows.
    """
    try:
        # license breakdown (NULL → "null_source" by spec)
        license_rows = am_conn.execute(
            "SELECT COALESCE(license, 'null_source') AS lic, "
            "       COUNT(*) AS n "
            "  FROM am_source "
            " GROUP BY COALESCE(license, 'null_source')"
        ).fetchall()
        license_hist = {
            (r["lic"] if "lic" in r.keys() else r[0]):
                int(r["n"] if "n" in r.keys() else r[1])
            for r in license_rows
        }
        total_sources = sum(license_hist.values())

        # freshness — bucket on days since first_seen
        fresh_hist: dict[str, int] = {
            label: 0 for label, _ in _FRESHNESS_BUCKETS
        }
        fresh_hist["unknown"] = 0
        today = datetime.now(UTC).date()
        fresh_cursor = am_conn.execute(
            "SELECT first_seen FROM am_source"
        )
        for row in fresh_cursor:
            try:
                first_seen = row["first_seen"]
            except (TypeError, IndexError):
                first_seen = row[0]
            days: int | None = None
            if first_seen:
                try:
                    seen_date = datetime.fromisoformat(
                        str(first_seen).replace("Z", "+00:00")
                    ).date()
                    days = (today - seen_date).days
                except (ValueError, TypeError):
                    days = None
            label = _freshness_bucket_for(days)
            fresh_hist[label] = fresh_hist.get(label, 0) + 1

        return {
            "license_breakdown": license_hist,
            "freshness_buckets": fresh_hist,
            "total_sources": total_sources,
        }
    except sqlite3.OperationalError:
        return None


# When the O8 view AND the am_source fallback BOTH yield zero rows on the
# current DB volume (production state pre-redeploy 2026-04-29), the previous
# response was 100% zeros, which prospects (M&A advisors, journalists,
# auditors) read as "data quality is broken" — even though the canonical
# trust-signal page /v1/am/data-freshness has full per-dataset numbers
# (programs / case_studies / loan_programs / enforcement_cases / laws /
# court_decisions / bids / invoice_registrants / tax_rulesets all populated
# with row counts + license + last_fetched_at). Rather than ship an
# all-zeros aggregate, redirect the caller to the working surface so
# they end up with meaningful data instead of a broken signal. The
# happy-path (view + facts populated) returns the full rollup as before.
def _data_quality_is_empty(out: dict[str, Any]) -> bool:
    """Return True when the rollup contains no useful aggregates.

    Defensive: a populated ``label_histogram`` with all-zero values, plus
    empty ``license_breakdown`` and ``field_kind_breakdown``, indicates
    neither the O8 view nor the am_source fallback produced rows. This
    is the signature of a pre-deploy production volume.
    """
    if int(out.get("fact_count_total") or 0) > 0:
        return False
    if out.get("license_breakdown"):
        return False
    if out.get("field_kind_breakdown"):
        return False
    # label_histogram is initialised with zeros; non-zero only if facts.
    label_hist = out.get("label_histogram") or {}
    if any(int(v or 0) > 0 for v in label_hist.values()):
        return False
    return True


@router.get("/data_quality", response_model=DataQualityResponse)
def stats_data_quality() -> Any:
    def _compute() -> dict[str, Any]:
        # Initialise every bucket so zero-row volumes still produce a
        # well-shaped JSON. Honest disclosure: missing view also lands
        # here via the OperationalError catch below.
        label_hist: dict[str, int] = {
            "high": 0, "medium": 0, "low": 0, "unknown": 0,
        }
        license_hist: dict[str, int] = {}
        fresh_hist: dict[str, int] = {
            label: 0 for label, _ in _FRESHNESS_BUCKETS
        }
        fresh_hist["unknown"] = 0
        kind_acc: dict[str, dict[str, float]] = {}

        fact_count = 0
        score_sum = 0.0
        n_pairs_multi = 0
        n_pairs_agree = 0
        fallback_reason: str | None = None
        fallback_total_sources: int | None = None

        am_conn = _open_autonomath_conn()
        if am_conn is None:
            return {
                "fact_count_total": 0,
                "mean_score": None,
                "label_histogram": label_hist,
                "license_breakdown": license_hist,
                "freshness_buckets": fresh_hist,
                "field_kind_breakdown": {},
                "cross_source_agreement": {
                    "facts_with_n_sources_>=2": 0,
                    "facts_with_consistent_value": 0,
                    "agreement_rate": 0.0,
                },
                "model": "beta_posterior_v1",
                "fallback_source": "autonomath_db_unavailable",
                "fallback_note": (
                    "autonomath.db could not be opened; license / "
                    "freshness aggregates unavailable. See "
                    "/v1/am/data-freshness for the per-dataset trust-"
                    "signal page."
                ),
                "generated_at": (
                    datetime.now(UTC)
                    .replace(microsecond=0)
                    .isoformat()
                    .replace("+00:00", "Z")
                ),
            }
        try:
            cursor = am_conn.execute(
                "SELECT field_kind, license, days_since_fetch, "
                "       n_sources, agreement "
                "  FROM am_uncertainty_view"
            )
            for row in cursor:
                try:
                    field_kind = row["field_kind"]
                    license_value = row["license"]
                    days_since_fetch = row["days_since_fetch"]
                    n_sources = row["n_sources"]
                    agreement = row["agreement"]
                except (TypeError, IndexError):
                    field_kind, license_value, days_since_fetch, \
                        n_sources, agreement = (
                            row[0], row[1], row[2], row[3], row[4]
                        )
                # Score the fact via the same pure-math helper used by
                # the envelope wrapper. This guarantees the rollup and
                # the per-fact `_uncertainty` field stay numerically
                # consistent.
                unc = score_fact(
                    field_kind=field_kind,
                    license_value=license_value,
                    days_since_fetch=(
                        int(days_since_fetch)
                        if days_since_fetch is not None
                        else None
                    ),
                    n_sources=int(n_sources or 0),
                    agreement=int(agreement or 0),
                )
                fact_count += 1
                score_sum += float(unc["score"])
                label_hist[unc["label"]] = label_hist.get(unc["label"], 0) + 1
                lic_key = license_value or "null_source"
                license_hist[lic_key] = license_hist.get(lic_key, 0) + 1
                fresh_label = _freshness_bucket_for(
                    int(days_since_fetch)
                    if days_since_fetch is not None
                    else None
                )
                fresh_hist[fresh_label] = fresh_hist.get(fresh_label, 0) + 1
                kk = field_kind or "unknown"
                bucket = kind_acc.setdefault(kk, {"count": 0.0, "sum": 0.0})
                bucket["count"] += 1
                bucket["sum"] += float(unc["score"])
                if int(n_sources or 0) >= 2:
                    n_pairs_multi += 1
                    if int(agreement or 0) == 1:
                        n_pairs_agree += 1
        except sqlite3.OperationalError:
            # View missing on this volume — fall through to the
            # am_source fallback below.
            fallback_reason = "am_uncertainty_view_missing"
        # Honest fallback: when the O8 view yielded 0 facts (either
        # because the view is missing OR because facts haven't been
        # joined to am_source yet), populate license_breakdown +
        # freshness_buckets directly from am_source so the dashboard
        # is not all-zeros. The ``fact_count_total`` stays at 0 to
        # truthfully signal "we have NO scored facts yet"; the
        # ``fallback_*`` keys disclose what's happening.
        if fact_count == 0:
            agg = _am_source_fallback_aggregates(am_conn)
            if agg is not None:
                license_hist = agg["license_breakdown"]
                fresh_hist = agg["freshness_buckets"]
                fallback_total_sources = int(agg["total_sources"])
                if fallback_reason is None:
                    fallback_reason = "am_uncertainty_view_empty"
            else:
                if fallback_reason is None:
                    fallback_reason = "am_source_missing"
        try:
            am_conn.close()
        except Exception:
            pass

        kind_breakdown: dict[str, dict[str, Any]] = {}
        for k, agg in kind_acc.items():
            count = int(agg["count"])
            mean = (agg["sum"] / count) if count > 0 else 0.0
            kind_breakdown[k] = {
                "count": count,
                "mean_score": round(mean, 4),
            }

        agreement_rate = (
            (n_pairs_agree / n_pairs_multi) if n_pairs_multi > 0 else 0.0
        )

        out: dict[str, Any] = {
            "fact_count_total": fact_count,
            "mean_score": (
                round(score_sum / fact_count, 4) if fact_count > 0 else None
            ),
            "label_histogram": label_hist,
            "license_breakdown": license_hist,
            "freshness_buckets": fresh_hist,
            "field_kind_breakdown": kind_breakdown,
            "cross_source_agreement": {
                "facts_with_n_sources_>=2": n_pairs_multi,
                "facts_with_consistent_value": n_pairs_agree,
                "agreement_rate": round(agreement_rate, 4),
            },
            "model": "beta_posterior_v1",
            "generated_at": (
                datetime.now(UTC)
                .replace(microsecond=0)
                .isoformat()
                .replace("+00:00", "Z")
            ),
        }
        if fallback_reason is not None:
            out["fallback_source"] = fallback_reason
            note = (
                "am_uncertainty_view did not yield per-fact rows on this "
                "DB volume; license_breakdown + freshness_buckets are "
                "computed directly from am_source as an honest fallback "
                "so trust-signal callers do not see all-zeros. "
                "mean_score / label_histogram / cross_source_agreement "
                "remain at 0 because per-fact scoring needs the view. "
                "See /v1/am/data-freshness for the per-dataset breakdown."
            )
            out["fallback_note"] = note
            if fallback_total_sources is not None:
                out["am_source_total_rows"] = fallback_total_sources
        return out

    out = _cache_get_or_compute("data_quality", _compute)
    # M&A advisor walk 2026-04-29 fix: when the O8 view AND the am_source
    # fallback both return empty (pre-redeploy production state), the
    # all-zeros payload reads as "data quality is broken". Redirect to
    # the per-dataset trust-signal page that DOES carry useful numbers.
    # 307 (temporary) so clients can return here once the underlying
    # view + fallback start producing rows.
    if _data_quality_is_empty(out):
        return RedirectResponse(url="/v1/am/data-freshness", status_code=307)
    return out
