# Performance baseline (2026-04-24, pre-launch — refresh snapshot)

> **Refresh note (2026-04-24, later same day).** Re-run against the laws table
> as ingestion progressed from 6,850 → 8,704 rows (+27%). Methodology unchanged
> (same script at `tests/bench/baseline_2026_04_24.py`, same host, same warm-up
> + 500-request window). Delta section at bottom flags every endpoint where
> P95 shifted ≥ 2× vs the first run. The ASCII 2-char `q=IT` outlier remains
> and is being worked on in parallel — do not let the revised P95 mask that
> investigation.

## Methodology

- In-process `httpx.AsyncClient` via `ASGITransport` — measures app logic, zero network overhead
- 10 warm-up requests per endpoint (SQLite page cache heated), then 500 sequential requests
- Single process, single SQLite file, FTS5 trigram tokenizer
- Real `data/jpintel.db` (13,578 active programs tier S/A/B/C, 12,038 total rows incl. X-tier quarantine, 2,286 case studies, 8,704 laws — up from 6,850 in the morning snapshot, 35 tax rulesets)
- Host: macOS 25.3.0 (operator laptop, M-series Apple Silicon)
- **NOT a load test** — sequential baseline for alert-threshold derivation

## Results

| Endpoint | P50 | P95 | P99 | Max | Error% |
|---|---|---|---|---|---|
| GET /healthz | 8.6ms | 16.1ms | 22.6ms | 34.3ms | 0.0% |
| GET /v1/meta | 65.6ms | 340.3ms | 610.7ms | 1348.2ms | 0.0% |
| GET /v1/programs/search?q=IT | 330.1ms | 662.0ms | 1134.7ms | 9407.3ms | 0.0% |
| GET /v1/programs/search?q=スマート農業&tier=S,A | 15.7ms | 23.9ms | 45.1ms | 154.8ms | 0.0% |
| GET /v1/programs/UNI-00550acb43 | 5.3ms | 6.3ms | 7.1ms | 11.9ms | 0.0% |
| GET /v1/programs/UNI-00b2fc290b | 5.2ms | 6.9ms | 9.5ms | 11.6ms | 0.0% |
| GET /v1/programs/UNI-012c038dea | 5.3ms | 7.6ms | 11.0ms | 14.0ms | 0.0% |
| GET /v1/case-studies/search?q=IT | 19.1ms | 27.4ms | 34.2ms | 116.5ms | 0.0% |
| GET /v1/exclusions/rules | 8.9ms | 10.5ms | 12.5ms | 44.3ms | 0.0% |
| GET /v1/laws/search?q=補助金 | 7.2ms | 17.7ms | 29.7ms | 54.4ms | 0.0% |
| GET /v1/tax_rulesets/search?limit=35 | 7.5ms | 11.4ms | 15.8ms | 28.3ms | 0.0% |
| POST /v1/programs/prescreen | 34.8ms | 51.3ms | 78.4ms | 96.6ms | 0.0% |

## Top 3 slowest (by P95)

- `GET /v1/programs/search?q=IT`: P95 = 662.0ms
- `GET /v1/meta`: P95 = 340.3ms
- `POST /v1/programs/prescreen`: P95 = 51.3ms

## Flagged endpoints — investigate before launch

- `GET /v1/programs/search?q=IT`: P99 = 1,134.7ms, Max = 9,407.3ms. Root cause: short ASCII query "IT" matches 7,187 rows (FTS5 trigram returns all docs containing the 2-char sequence). The phrase-quoting workaround in `programs.py` applies only to 2+ char kanji; ASCII 2-char terms are not phrase-quoted. Consider a minimum-term-length guard or result-count cap for short ASCII queries. **Does not affect Japanese queries** — `スマート農業` with tier filter shows P95 = 23.9ms. A parallel agent is working this fix; this baseline intentionally leaves the outlier visible so the fix is observable. **Do not resolve this by dropping the test case.**

## Alert thresholds derived

Per `docs/monitoring.md` P1 thresholds — multiply measured P95 by 10× for alert:

| Endpoint group | Measured P95 | P1 alert threshold |
|---|---|---|
| `/v1/programs/search` | 662.0ms | 6620ms |
| `/v1/laws/search` | 17.7ms | 177ms |
| `/v1/programs/prescreen` | 51.3ms | 513ms |
| `/healthz` | 16.1ms | 161ms |

Error rate > 2% over 15 min → P1 alert (any endpoint).

## Capacity estimate

Hot path `/v1/programs/search` sequential P95: 662.0ms.

Concurrent capacity estimate (sequential throughput): ~1.5 RPS sustained on `/v1/programs/search` (1000ms / 662.0ms P95) in the worst-case ASCII-query path.

> IMPORTANT: `GET /v1/programs/search?q=IT` has P95 = 662ms and a Max spike of
> 9,407ms — the short ASCII term "IT" matches 7,187 rows (FTS5 returns all
> docs containing the 2-char trigram). This is the worst-case query. Japanese
> FTS (`スマート農業` with tier filter) is only 24ms P95 because the kanji
> trigrams narrow the result set dramatically. Published SLA should be based on
> typical Japanese queries (~25ms P95), not the degenerate ASCII-only case.
>
> At launch traffic (1-10 RPS, organic), single `shared-cpu-1x` is adequate.
> Above ~8 RPS sustained (ASCII search mix), queue depth will rise. Scale to
> `shared-cpu-2x` if P95 observed >600ms in Fly metrics. SQLite WAL mode is
> enabled (`db/session.py`).

## Delta vs morning snapshot (same day, 2026-04-24)

Laws table grew 6,850 → 8,704 rows (+27%) during the day's ingest. Below are
the endpoints whose measured P95 shifted materially between runs.

| Endpoint | Morning P95 | Refresh P95 | Δ | Notes |
|---|---|---|---|---|
| GET /healthz | 5.5ms | 16.1ms | +193% | Noise floor; absolute values still trivial |
| GET /v1/meta | 50.2ms | 340.3ms | +578% | `/v1/meta` aggregates row counts across all tables; the laws table growth touched this path — worth a follow-up before launch |
| GET /v1/programs/search?q=IT | 434.2ms | 662.0ms | +52% | Same FTS5 trigram outlier; fix in flight on parallel track |
| GET /v1/programs/search?q=スマート農業&tier=S,A | 16.8ms | 23.9ms | +42% | Within expected variance |
| GET /v1/case-studies/search?q=IT | 29.2ms | 27.4ms | −6% | Stable |
| GET /v1/exclusions/rules | 15.2ms | 10.5ms | −31% | Faster — fewer cold-cache stalls this run |
| GET /v1/laws/search?q=補助金 | 11.8ms | 17.7ms | +50% | Scales with table growth as expected; still well within budget |
| GET /v1/tax_rulesets/search?limit=35 | 10.6ms | 11.4ms | +8% | Stable |
| POST /v1/programs/prescreen | 46.9ms | 51.3ms | +9% | Stable |

Point-lookup (`GET /v1/programs/{id}`) P95 moved 6.2ms → 6.3-7.6ms across the
three sample IDs — noise-band.

**Biggest concerns to triage before the 2026-05-06 launch:**

1. `GET /v1/meta` P95 jumped 50ms → 340ms. Likely an un-indexed COUNT scan on the
   expanded laws table. Cache the meta response for 60s or precompute row counts.
2. `GET /v1/programs/search?q=IT` Max spike worsened (6s → 9.4s). The FTS5 fix
   on the parallel track should clamp this before rollout.

## Notes

- All measurements are sequential (not concurrent). Concurrent load will show
  higher latency due to SQLite write-lock contention on `usage_events` inserts.
- Anonymous callers bypass `usage_events` writes, so concurrency penalty is
  lower than authed callers for the same endpoint.
- FTS5 trigram searches on 13,578-row `programs` and 8,704-row `laws` tables
  are the bottleneck. Phrase-quoting workaround is active in `programs.py`
  for ≥2-char kanji queries.
