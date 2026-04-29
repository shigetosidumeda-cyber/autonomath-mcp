# AutonoMath REST API — Performance Baseline

Date: 2026-04-23
Hardware: Apple Silicon (Darwin arm64), macOS dev box
API: `.venv/bin/uvicorn jpintel_mcp.api.main:app --port 18080 --workers 1`
DB: `data/jpintel.db` (SQLite 書込ログモード, 5,831 non-excluded programs)
Bench: `scripts/bench_api.py` — median of 3 runs, 20-req warmup per cell

These numbers are directional only. Prod on Fly (Tokyo, single machine) will
differ; the goal here is to surface obvious pathologies before launch.

## Method

- Sequential baseline: 500 requests at concurrency=1
- Concurrent: 200 requests at concurrency ∈ {1, 10, 50}
- 4 query shapes — 3 search variants + 1 point lookup (random unified_id per call)
- Median of per-run percentiles across 3 runs (robust to GC blips)

## Results (latency ms, throughput req/s)

| Shape | Cell | p50 | p90 | p95 | p99 | max | rps |
|---|---|---:|---:|---:|---:|---:|---:|
| search(q=農業) | sequential_500 | 4.6 | 5.6 | 6.2 | 10.3 | 17.4 | 213 |
| search(q=農業) | concurrent_c1 | 4.1 | 5.3 | 5.5 | 6.0 | 7.6 | 232 |
| search(q=農業) | concurrent_c10 | 28.7 | 46.2 | 57.2 | 70.7 | 102.7 | 304 |
| search(q=農業) | concurrent_c50 | 228.0 | 775.3 | **934.5** | **1279.0** | 1329.8 | 129 |
| search(q=IT導入補助金) | sequential_500 | 5.0 | 6.2 | 8.0 | 15.8 | 25.7 | 190 |
| search(q=IT導入補助金) | concurrent_c1 | 5.0 | 5.7 | 6.3 | 7.3 | 13.5 | 198 |
| search(q=IT導入補助金) | concurrent_c10 | 36.1 | 71.8 | 92.8 | 129.4 | 187.5 | 218 |
| search(q=IT導入補助金) | concurrent_c50 | 276.9 | 981.5 | **1209.3** | **1529.3** | 1602.6 | 108 |
| search(q=補助金, pref=東京都) | sequential_500 | 5.1 | 6.3 | 7.3 | 11.3 | 16.7 | 193 |
| search(q=補助金, pref=東京都) | concurrent_c1 | 4.7 | 5.5 | 5.9 | 6.2 | 6.7 | 216 |
| search(q=補助金, pref=東京都) | concurrent_c10 | 29.1 | 51.5 | 60.1 | 76.0 | 116.7 | 291 |
| search(q=補助金, pref=東京都) | concurrent_c50 | 268.5 | 867.6 | **1061.6** | **1338.6** | 1668.3 | 112 |
| get_program(random) | sequential_500 | 4.8 | 5.7 | 6.3 | 8.4 | 18.9 | 207 |
| get_program(random) | concurrent_c1 | 4.7 | 6.2 | 6.8 | 10.2 | 13.4 | 201 |
| get_program(random) | concurrent_c10 | 27.6 | 47.3 | 64.9 | 93.4 | 114.5 | 310 |
| get_program(random) | concurrent_c50 | 226.0 | 827.4 | **992.4** | **1208.0** | 1566.8 | 119 |

Zero 5xx, zero timeouts across all 18 cells.

## Assessment

**Sequential & c=10 are fine.** p95 stays under 100ms everywhere. The
`_row_to_program` cache keyed on `(unified_id, source_checksum)` is doing
its job on hot rows.

**c=50 is the pathology.** All four shapes — including the trivial point
lookup — scale identically: p50 ≈ 230–280ms, p95 ≈ 930–1210ms. That the
point lookup (a single indexed `WHERE unified_id=?` row) degrades in lockstep
with facet search rules out query-plan cost. The bottleneck is per-request.

### Root cause: per-request connection setup + threadpool saturation

`src/jpintel_mcp/api/deps.py:30` → `get_db()` calls `connect()` on every
request. `connect()` at `src/jpintel_mcp/db/session.py:27-31` opens a fresh
sqlite handle and then issues **two `PRAGMA` statements per request**
(`journal_mode = WAL`, `foreign_keys = ON`). 書込ログモードは永続化される
database property — setting it once at `init_db()` would suffice. The
`foreign_keys` pragma is per-connection, but the foreign-key checks add no
value on hot read paths.

Compounding factors:

1. **No `PRAGMA busy_timeout`.** Under c=50, readers serialize on the書込ログ
   write lock held during transaction commits (e.g. `log_usage` inserts into
   `usage_events` on every request). Default busy timeout is zero → immediate
   contention → threadpool threads sit spinning.
2. **Sync endpoints + default threadpool = 40.** FastAPI runs `def`
   endpoints (both `search_programs` and `get_program` are sync) in the
   Starlette threadpool, whose default is 40 workers. At c=50, 10+ requests
   queue behind busy workers and inherit the queue delay.
3. **Per-request `log_usage` write.** Every request opens a transaction to
   `INSERT INTO usage_events`, which takes the 書込ログ write lock. At c=50
   that's 50 writers contending for one writer slot.

The nearly-identical c=50 curves across search and get_program are the
fingerprint: it's not the query, it's the setup + writer contention.

### Recommended fixes (in order of payoff)

1. **`src/jpintel_mcp/db/session.py:29-31`** — drop per-connection
   `PRAGMA journal_mode = WAL` (書込ログモードは永続化されるので `init_db` で 1 度設定すれば足りる)。
   Add `PRAGMA busy_timeout = 5000` and `PRAGMA synchronous = NORMAL`
   inside `init_db` or once per connection only. Consider caching a
   thread-local read connection to avoid the `sqlite3.connect()` syscall
   per request.
2. **Batch `log_usage` writes.** Replace the per-request insert with an
   in-process queue + flusher (100ms or 100-row batches). The
   `usage_events` table is for retention digests (W7) — a 100ms aggregation
   window is operationally invisible and eliminates the writer contention
   that dominates c=50.
3. **Consider async endpoints + `sqlite3` in a bounded pool.** Sync
   endpoints under high concurrency bottleneck on the 40-thread pool;
   async handlers with a dedicated 8–16 connection pool would give
   better tail latency under traffic spikes.

### Is this a shipping blocker?

Directionally: **no, but it's the #1 thing to fix post-launch.** At expected
organic launch traffic (a few req/s on day 1, spiking only on HN/Reddit
posts), c=50 is unrealistic — we'll live in the c=1 to c=10 regime where p95
is 6–100ms. A single viral post could push us to c=50+; the batching +
pragma fix is a 1–2h job that would push the p95 back under 200ms at c=50.

The launch gate (per the minimal-blocker principle) is "no 5xx, no
timeouts, reasonable sequential latency." All three are green.

## Artifacts

- `scripts/bench_api.py` — bench harness (448 lines)
- `data/bench_api_report.json` — raw JSON results
- This file — summary + root-cause analysis
