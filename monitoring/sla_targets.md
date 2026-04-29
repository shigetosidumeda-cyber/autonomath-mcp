# SLA Targets — AutonoMath / jpintel-mcp

> **Status**: Operator-internal targets, not contractual guarantees. The
> public-facing SLA in `docs/sla.md` is intentionally weaker (99.0% availability)
> to leave headroom; this document is the *internal SLO* the operator manages
> against. See `docs/observability.md` for the 2-tier rationale (公開 SLA 99.0% /
> 内部 SLO 99.5%).
>
> **Owner**: 梅田茂利 / info@bookyou.net (solo, zero-touch)
> **Last reviewed**: 2026-04-29

## Why "best effort" not "guaranteed"

The product is solo-operated under a ¥3/req metered model. We have no on-call
rotation, no support team, and no DPA negotiation surface. Guaranteeing
sub-minute response times under those constraints would be dishonest. Instead
we publish *operationally realistic* targets that the operator can defend on
a normal day, and we treat breaches as inputs to the weekly improvement loop
rather than as customer-credit events.

This file is the source of truth for monitoring thresholds. Every alert rule
in `monitoring/sentry_alert_rules.yml` should map back to one of these targets.

## Targets

### 1. Uptime — 99.5% (7-day rolling)

| | Value |
|--|--|
| Target | 99.5% over a 7-day rolling window |
| Allowed downtime | 50.4 min / 7 days = 7.2 min / day |
| Measured by | UptimeRobot 1-min HTTP probe of `GET /healthz` + Fly machine running count |
| Excluded from breach math | (a) Cloudflare / Fly platform-wide outages with public status-page entry, (b) planned maintenance announced ≥48h in advance via `zeimu-kaikei.ai/status` |
| Linked alert rule | `api_5xx_rate` (high), backstopped by Fly's own machine-down alert (set up at `flyctl monitoring`, separate from Sentry) |

Why 99.5% not 99.9%: a 99.9% target would budget 4.32 min/month, which is
shorter than a Fly cold-start under load + DB integrity check. We can't
defend 99.9% with a single machine; raising it would either require active-active
multi-region (cost) or be a lie (reputation risk).

### 2. p95 latency — < 1.5 s

| | Value |
|--|--|
| Target | p95 of `GET /v1/programs/search` < 1500 ms |
| Window | rolling 1 hour |
| Measured by | Sentry transaction p95 (widget #6 in `sentry_dashboard.json`) |
| Linked alert rule | not direct; widget visualization + manual SLO review |

Why 1.5s not 800ms: the operator-internal observability doc cites < 800ms p95
as a *stretch* goal. The launchable target is 1.5s because (a) cold-start adds
~400ms, (b) FTS5 trigram queries on the larger autonomath.db corpus already
hit 600-800ms baseline, and (c) Anthropic / OpenAI agents typically have their
own 30-60s top-level budget so 1.5s is well within their tolerance. We track
to 800ms in the dashboard but do not page on it.

### 3. 5xx error rate — < 0.5%

| | Value |
|--|--|
| Target | server-side 5xx rate < 0.5% |
| Window | rolling 10 minutes |
| Measured by | Sentry transaction failure rate (widget #4) |
| Linked alert rule | `api_5xx_rate` (alert at 1.0%, page at 2.0%) |

Why 0.5% not 0.1%: a 0.1% target on a low-traffic launch (target 1k req/day
month 1) means a single 5xx in a 10-minute window blows the SLO. Below 1k
req/day, the SLO is dominated by sample-size variance, not real signal. We'll
tighten as traffic scales.

### 4. Webhook delivery — 99% within 60s

| | Value |
|--|--|
| Target | 99% of inbound Stripe webhook events processed (200 OK back to Stripe) within 60s of `Stripe-Signature` timestamp |
| Window | rolling 24 hours |
| Measured by | `scripts/cron/webhook_health.py` (existing) — emits a daily Sentry message with the percentile |
| Linked alert rule | `webhook_handler_exception_rate` (critical, exception-side); + `subscription_created_anomaly` (medium, volume-side) |

Why 99% not 99.9%: Stripe's own retry budget is 3 days with exponential backoff,
so a 1% miss rate is recoverable as long as our handler is idempotent (which
it is — see `src/jpintel_mcp/billing/stripe_edge_cases.py`). 99.9% would
require zero cold-starts during webhook bursts, which we don't have.

## Latency budget breakdown (informational)

For the < 1.5s p95 target, here is the rough budget allocation:

| Layer | Budget | Notes |
|--|--|--|
| Cloudflare → Fly Tokyo | 80 ms | TLS handshake amortized over connection reuse |
| Fly proxy + machine routing | 50 ms | |
| FastAPI middleware stack | 100 ms | auth + anon-quota + Sentry instrumentation + scrubbing |
| FTS5 query + ORM hydration | 900 ms | dominant; see CLAUDE.md `gotcha` on trigram tokenizer |
| Response render (JSON serialize) | 100 ms | |
| Cloudflare egress + buffer | 270 ms | |
| **Total** | **1500 ms** | |

The dominant term is the DB query. If that exceeds 900ms p95, the SLO
dies. Mitigation has historically been: (a) the `tier IN (...)` index, (b)
FTS5 phrase quoting on 2+ kanji compounds, (c) the L4 query cache
(`scripts/cron/l4_cache_warm.py`).

## Breach handling

Per `feedback_zero_touch_solo`: SLO breaches are NOT customer-credit events.
The operator is solo and credits would create a billing-flow nightmare we
can't sustain. Instead:

1. SLO breach detected via Sentry alert (one of the rules in `sentry_alert_rules.yml`)
2. Incident logged in `docs/_internal/incidents/YYYY-MM-DD-<slug>.md`
3. Postmortem within 24 hours of resolution
4. Public status page (`zeimu-kaikei.ai/status`) updated only for breaches
   exceeding 30 min user-visible

If a customer asks for credit explicitly (rare but possible at the ¥3/req
scale), the operator can issue a one-shot Stripe refund manually. We do not
publish a refund SLA because volume doesn't warrant the policy surface.

## Out of scope for SLA

Per project memory, these are *deliberately not* SLO/SLA-tracked:

- MCP stdio availability (passive — surfaced via GitHub issues, not metrics)
- Static site (`zeimu-kaikei.ai/docs/`) — Cloudflare Pages SLA inherits from CF
- LLM crawler citation rate (best-effort GEO; widget #11 in dashboard)
- Per-program data freshness (warn at 90d via `_health_deep`, not a hard SLO)

## Reviewing this file

This document is reviewed quarterly or whenever a target needs updating.
Trigger criteria for revision:

- Sustained breach > 1 quarter (e.g., latency target consistently violated)
- Major architecture change (multi-region, new DB engine, etc.)
- Customer-facing SLA change (`docs/sla.md`)
- Sentry quota change affecting alert fidelity

Last revision rationale: 2026-04-29 — initial publication aligned with launch
prep (target 2026-05-06).
