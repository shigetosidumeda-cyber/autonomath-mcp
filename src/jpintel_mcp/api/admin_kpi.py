"""Operator KPI endpoint (`GET /v1/admin/kpi`).

Mirrors the JSON shape emitted by ``scripts/ops_quick_stats.py --json``.
Operator-only: gated behind ``ADMIN_API_KEY`` via ``AdminAuthDep``,
identical posture to ``/v1/admin/funnel`` and ``/v1/stats/funnel``.

Surfaces:

- Audience: MAU (anon + paid)
- Revenue: MRR month-to-date + WoW delta (rolling 7-day windows)
- Caps: number of capped keys + how many hit the cap
- Health:
  * paid-key churn over last 7d
  * past-due Stripe subscriptions
  * unsynced metered events older than 1h
  * latest reconcile drift % (read from
    ``analysis_wave18/stripe_reconcile_*.json``)
- Funnel:
  * trial signups in last 24h
  * 30d trial-to-paid conversion rate
- GEO: citation rate from latest
  ``analytics/geo_baseline_*.jsonl``
- External cache rows: Sentry / Stripe ops snapshot (read-only, never
  hits external APIs — see ``feedback_autonomath_no_api_use``).

A parallel ``severity`` dict classifies each metric as
``ok | warn | critical`` so the dashboard + email digest can color-code
without re-deriving the rules.

We deliberately re-use the helpers from
``scripts/ops_quick_stats.py`` so the CLI and the API never drift.
"""

from __future__ import annotations

import importlib.util
import sqlite3  # noqa: TC003 (runtime: cursor return type + ctor)
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict

from jpintel_mcp.api.admin import AdminAuthDep  # noqa: TC001 (FastAPI Depends)
from jpintel_mcp.api.deps import DbDep  # noqa: TC001 (FastAPI Depends)

if TYPE_CHECKING:
    from types import ModuleType


# ---------------------------------------------------------------------------
# Lazy import of scripts/ops_quick_stats.py.
#
# The CLI is intentionally outside the import path (operator scripts
# stay decoupled from the package).  We resolve the module by file
# location and load it once per process; subsequent calls reuse the
# already-imported namespace.
# ---------------------------------------------------------------------------

_OPS_MODULE: ModuleType | None = None


def _load_ops_module() -> ModuleType:
    global _OPS_MODULE
    if _OPS_MODULE is not None:
        return _OPS_MODULE
    repo_root = Path(__file__).resolve().parents[3]
    script_path = repo_root / "scripts" / "ops_quick_stats.py"
    if not script_path.is_file():
        raise FileNotFoundError(f"ops_quick_stats.py not found at {script_path}")
    spec = importlib.util.spec_from_file_location("_ops_quick_stats_kpi", script_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"could not load spec for {script_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _OPS_MODULE = module
    return module


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class KpiSeverity(BaseModel):
    """Per-metric ``ok | warn | critical`` classification.

    Keys mirror the field names in :class:`KpiResponse`.  Missing keys
    indicate the metric does not have an associated severity rule
    (e.g. ``mau_total`` is always informational).
    """

    model_config = ConfigDict(frozen=True, extra="allow")


class KpiResponse(BaseModel):
    """Operator KPI snapshot.

    All currency fields are integers in JPY (税抜 ¥3/req; tax is a
    Stripe Tax line, not surfaced here).  Percentages are float and
    range 0.0–100.0 unless otherwise stated.
    """

    model_config = ConfigDict(frozen=True)

    generated_at: str
    date_jst: str

    # Audience
    mau_total: int = 0
    mau_anon: int = 0
    mau_paid: int = 0

    # Revenue
    mrr_yen: int = 0
    mrr_per_customer_yen: int = 0
    mrr_wow_this_week_yen: int = 0
    mrr_wow_last_week_yen: int = 0
    mrr_wow_delta_yen: int = 0
    mrr_wow_pct: float = 0.0
    billable_units_24h: int = 0
    billable_keys_24h: int = 0
    daily_100k_goal_progress_pct: float = 0.0
    billable_units_30d: int = 0
    client_tagged_units_30d: int = 0
    client_tag_usage_rate_30d_pct: float = 0.0
    active_client_tag_pairs_30d: int = 0
    top_key_30d_billable_units_share_pct: float = 0.0
    cost_preview_requests_7d: int = 0
    cost_preview_to_billable_7d_pct: float = 0.0

    # Caps
    cap_set: int = 0
    cap_reached: int = 0

    # Health
    churn_7d: int = 0
    past_due_count: int = 0
    unsynced_metered_events: int = 0
    unsynced_metered_units: int = 0
    reconcile_drift_pct: float | None = None
    reconcile_source_file: str | None = None

    # Funnel
    trial_signups_24h: int = 0
    trial_to_paid_30d_pct: float = 0.0

    # GEO
    geo_citation_rate_pct: float | None = None
    geo_probes_total: int = 0
    geo_source_file: str | None = None

    # External cache rows
    sentry_row: str = ""
    stripe_row: str = ""

    # Per-metric severity classification
    severity: dict[str, str]


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter(
    prefix="/v1/admin",
    tags=["admin", "operator"],
    include_in_schema=False,  # admin surfaces never hit /openapi.json
)


@router.get("/kpi", response_model=KpiResponse)
def get_kpi(_admin: AdminAuthDep, conn: DbDep) -> KpiResponse:
    """Return today's operator KPI snapshot.

    Identical schema to ``scripts/ops_quick_stats.py --json``.  All
    numbers are computed off the local DB + local JSON / JSONL files
    that out-of-band crons write — this endpoint never calls the
    Stripe / Sentry HTTP APIs (see ``feedback_autonomath_no_api_use``).
    """
    ops = _load_ops_module()
    # `conn` is the API's writable handle.  The collector helpers in
    # ops_quick_stats only execute SELECT, so passing the API
    # connection through directly is safe and lets us reuse the
    # already-prepared statement cache.  We do not need a separate
    # read-only handle here.
    payload: dict[str, Any] = ops.collect_payload(_AdaptedConn(conn))
    return KpiResponse.model_validate(payload)


class _AdaptedConn:
    """Trivial pass-through for ``sqlite3.Connection`` so the helpers in
    ops_quick_stats can call ``conn.execute(...)`` without re-binding
    ``row_factory`` (the API connection already sets ``Row`` factory
    in ``db.session.connect``).
    """

    __slots__ = ("_inner",)

    def __init__(self, inner: sqlite3.Connection) -> None:
        self._inner = inner

    def execute(self, *args: Any, **kwargs: Any) -> sqlite3.Cursor:
        return self._inner.execute(*args, **kwargs)


__all__ = ["router", "KpiResponse"]
