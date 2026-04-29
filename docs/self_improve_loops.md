# 税務会計AI — 10 Self-Improvement Loops

**Owner:** 梅田茂利, info@bookyou.net (Bookyou株式会社)
**Status:** scaffolding (T+30d for real ML wiring); dry-run only at launch.
**Constraint:** zero LLM. Local e5-small + DBSCAN + SQL only. See operator memory `feedback_autonomath_no_api_use` — calling Anthropic / OpenAI / Gemini from these loops is a regression that breaks ¥3/req economics.

---

## Why ten loops, not one big rewrite

Each loop is a *single-purpose, small-blast-radius* feedback pipeline. All ten share the same shape:

```
read signal table -> cluster / score -> propose candidates -> operator approves -> production write
```

This makes the system safe-by-default (`dry_run=True` is the orchestrator default, and operator review is mandatory before any candidate is promoted). It also matches `feedback_completion_gate_minimal` — none of these loops are launch blockers; they ship dark and turn on individually as data accumulates.

---

## Cadence overview

| Loop | Name | Cadence | Trigger | Cost ceiling |
|------|------|---------|---------|--------------|
| A | hallucination_guard expansion | weekly | Mon 09:30 JST | 5 CPU min |
| B | testimonial -> SEO/GEO | monthly | 1st 10:00 JST | 2 CPU min |
| C | personalized cache | weekly | Sun 03:00 JST | 10 CPU min |
| D | forecast accuracy | monthly | 15th 09:00 JST | 3 CPU min |
| E | multi-language alias expansion | weekly | Wed 04:00 JST | 5 CPU min |
| F | channel ROI | weekly | Fri 16:00 JST | 1 CPU min |
| G | invariant expansion | monthly | 5th 11:00 JST | 3 CPU min |
| H | cache warming (Zipf) | daily | 03:30 JST | 10 CPU min |
| I | doc freshness re-fetch priority | weekly | Tue 02:00 JST | 2 CPU min |
| J | gold.yaml expansion | monthly | 20th 09:00 JST | 5 CPU min |

Total: ~6 hours of CPU per month — fits inside the Fly.io shared compute budget without any auto-scale.

---

## Loops in detail

### Loop A — hallucination_guard expansion
- **Inputs:** `customer_feedback`, `query_log` (zero-result + low-conf), `hallucination_guard` (504 rows at launch).
- **Output:** `hallucination_guard_candidates` rows with `status='pending_review'`. Operator promotes -> `hallucination_guard` (target 5,000+ within 6 months).
- **Method:** e5-small embed feedback text, DBSCAN cluster, take cluster medoid as candidate pattern.

### Loop B — customer success -> testimonial SEO/GEO
- **Inputs:** `customer_success_events` (consent_flag=1), `programs`, `prefectures`.
- **Output:** `seo_testimonial_candidates` rows + JSON-LD Review schema. Operator pastes into `site/blog/case-*.md`.
- **Method:** Pure SQL aggregation + Jinja template rendering. No LLM rewrite.

### Loop C — personalized cache
- **Inputs:** `query_log` (paid keys, 30 days), `api_keys`.
- **Output:** `personalized_cache(customer_id, query_hash, payload_json, computed_at)` upserts. TTL 7 days.
- **Method:** Top-K=20 query histogram per customer with ≥50 prior requests. Pre-execute 全文検索; cache.

### Loop D — forecast accuracy
- **Inputs:** 募集回 schedule (1,256 rows), `forecast_predictions`.
- **Output:** `forecast_calibration(program_id, coef_json, computed_at)`. Consumed by `subsidy_roadmap_3yr` MCP tool.
- **Method:** Closed-form Bayesian shrinkage estimator (numpy). No new predictions written; calibration only.

### Loop E — multi-language alias expansion (V4+)
- **Inputs:** `query_log` (14 days, all tiers), 別名・略称 index (335,605 rows).
- **Output:** `alias_candidates(entity_id, surface, lang, source, score, status)`. Operator promotes to the 別名・略称 index monthly.
- **Method:** Mine queries with conf<0.5 hitting a single program; e5-small cluster surface forms; lang detect via script heuristic.

### Loop F — channel ROI
- **Inputs:** `subscribers.utm_source`, `query_log`, `billing_events`.
- **Output:** `channel_roi(channel, signups_28d, paid_28d, revenue_28d_jpy, computed_at)`.
- **Method:** Pure SQL window aggregations. Informational only — `feedback_organic_only_no_ads` means we never optimize a paid channel.

### Loop G — invariant expansion
- **Inputs:** `error_log`, `customer_feedback` (wrong_answer flag), existing `tests/properties/`.
- **Output:** `tests/properties/_candidates/<failure_mode>.py` Hypothesis stubs. Operator polishes + moves to `tests/properties/`.
- **Method:** Cluster errors by stack-trace top-5 frames; template a Hypothesis property per cluster.

### Loop H — cache warming (Zipf)
- **Inputs:** `query_log` (24h, all tiers).
- **Output:** `query_cache(query_hash, payload_json, ttl_until)` for top-200 global queries.
- **Method:** Daily Zipf head; pre-execute live 全文検索; upsert with 24h TTL. Drops P95 from ~30 ms to ~2 ms on warm queries.

### Loop I — doc freshness re-fetch priority
- **Inputs:** `programs.source_url` / `source_fetched_at`, `source_change_signals` (HTTP 304 / Last-Modified from nightly liveness scan).
- **Output:** `source_refetch_queue(source_url, priority, reason, queued_at)`.
- **Method:** Score = 0.6 * staleness_days + 0.3 * tier_weight + 0.1 * change_signal. Top 500 written. Honest semantics — does NOT touch `source_fetched_at` (per CLAUDE.md gotchas) until an actual fetch runs.

### Loop J — gold.yaml expansion
- **Inputs:** `query_log` (30 days), `evals/gold.yaml`, `programs`.
- **Output:** `evals/_candidates/gold_proposed_<YYYY-MM>.yaml`. Operator hand-curates accept/reject.
- **Method:** High-confidence (>=0.85) stable (≥5 sessions, same top-1) queries become candidates. Skip rows already in gold. Mandatory operator review — gold rows are regression tests forever.

---

## Orchestrator

```bash
# Default: dry-run all 10 (safe)
.venv/bin/python scripts/self_improve_orchestrator.py

# Operator-approved real run
.venv/bin/python scripts/self_improve_orchestrator.py --execute

# Single loop
.venv/bin/python scripts/self_improve_orchestrator.py --only loop_h_cache_warming
```

Output goes to `analysis_wave18/self_improve_runs/<YYYY-MM-DD>.json` with this shape:

```json
{
  "ts": "2026-04-25T12:34:56+09:00",
  "dry_run": true,
  "loops_total": 10,
  "loops_succeeded": 10,
  "loops_failed": 0,
  "totals": {"scanned": 0, "actions_proposed": 0, "actions_executed": 0},
  "results": [
    {"loop": "loop_a_hallucination_guard", "scanned": 0, "actions_proposed": 0, "actions_executed": 0},
    ...
  ]
}
```

---

## Monitoring

Add a single line to the existing weekly digest (`scripts/weekly_digest.py`):

> "Self-improvement: 10/10 loops succeeded last 7 days, X candidates proposed, Y promoted."

If `loops_failed > 0` for two consecutive runs, the digest highlights it as a `PC2` data-gap signal under the existing `docs/improvement_loop.md` priority framework.

No paging, no external alerting — solo + zero-touch ops.

---

## Hard rules (do not break)

1. **No LLM calls.** Ever. Local e5-small + scikit-learn DBSCAN + SQL only. (`feedback_autonomath_no_api_use`)
2. **`dry_run=True` is default.** Production writes need `--execute`, which currently is a no-op anyway since loops are scaffolding.
3. **Operator review for every promotion.** Candidates go to `*_candidates` tables / `_candidates/` directories — never directly into the production tables.
4. **Honest semantics.** Loop I never silently rewrites `source_fetched_at` (matches CLAUDE.md "What NOT to do").
5. **Schedule is suggestive, not enforced.** Pre-launch the orchestrator runs all 10 loops on each invocation. Per-loop cadence checks land T+30d alongside the real implementations.
