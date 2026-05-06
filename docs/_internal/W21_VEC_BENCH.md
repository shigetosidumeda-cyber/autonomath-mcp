# W21 sqlite-vec k-NN benchmark

- db: `/Users/shigetoumeda/jpcite/autonomath.db`
- sqlite: 3.50.4
- sqlite-vec: v0.1.9
- embedding dim: 1024
- iterations per table: 100 (3 untimed warmup)
- top-k: 10

## Latency by tier (ms)

| table | rows | p50 | p95 | p99 | min | max | mean |
|---|---:|---:|---:|---:|---:|---:|---:|
| am_entities_vec_C | 2016 | 3.621 | 7.292 | 11.379 | 2.889 | 12.167 | 4.211 |
| am_entities_vec_K | 137 | 1.102 | 4.052 | 4.561 | 0.708 | 4.994 | 1.508 |
| am_entities_vec_J | 2065 | 3.117 | 4.47 | 7.378 | 2.388 | 9.499 | 3.356 |

## Skipped tables

- `am_entities_vec_S` — rows<100 (rows=0)
- `am_entities_vec_L` — rows<100 (rows=0)
- `am_entities_vec_T` — rows<100 (rows=0)
- `am_entities_vec_A` — rows<100 (rows=0)

## Resume-safe embedding runs

`tools/offline/embed_corpus_local.py` and
`tools/offline/embed_canonical_entities.py` now default to resume-safe
behavior:

- Existing corpus vec rows are detected by `entity_id` in
  `am_entities_vec_<tier>` and skipped.
- Existing canonical vec rows are detected only when both sidecar map and
  vec rows exist (`map.synthetic_id` joined to `vec.synthetic_id`), then
  skipped.
- `--max-rows` caps newly embedded rows in resume mode, so a rerun does
  not waste an invocation on already embedded leading rows.
- Destructive regeneration requires explicit `--replace-existing`; that
  keeps the old DELETE+INSERT behavior for intentional refreshes.

Safe preflight examples that do not load the model or write vectors:

```bash
.venv312/bin/python tools/offline/embed_corpus_local.py --dry-run --corpus laws
.venv312/bin/python tools/offline/embed_corpus_local.py --dry-run --corpus tsutatsu
.venv312/bin/python tools/offline/embed_canonical_entities.py --dry-run --kind law
```

## HNSW availability

sqlite-vec **0.1.9 has no HNSW index**. Probed via:
`CREATE VIRTUAL TABLE ... USING vec0(embedding float[N], hnsw=1)` →
`vec0 constructor error: Unknown table option: hnsw`. Upstream
(github.com/asg017/sqlite-vec) carries IVF / IVF-kmeans / DiskANN
source files but no released build exposes them as a `vec0` option.

## Partition key option (available, recommended for vec_A)

vec0 **does** support `PARTITION KEY` columns. Probed in-memory:
`CREATE VIRTUAL TABLE __t USING vec0(prefecture_code TEXT PARTITION KEY, embedding float[1024])` → OK.
For `am_entities_vec_A` (201k row target), partitioning by
`prefecture_code` (47 buckets, ~4.3k rows / bucket) reduces
per-query candidate set by ~47×. Filtered queries take the form:
`WHERE prefecture_code = ? AND embedding MATCH ? ORDER BY distance LIMIT k`.

## HNSW migration decision

Largest measured tier: `am_entities_vec_J` (2065 rows) → p95 = 4.47 ms.
Linear extrapolation to 201,845 rows (`am_entities_vec_A` saturated) ≈ 436.9 ms p95.

**Decision**: HNSW is unavailable in the current sqlite-vec
build, so a migration 152 cannot adopt it today. The viable
near-term levers when `am_entities_vec_A` saturates:
1. Add `prefecture_code` (and/or `record_kind`) `PARTITION KEY`
   to the vec_A DDL. Most adoption queries are already
   prefecture-scoped — the 47× pruning likely keeps p95
   under 50 ms.
2. Pin sqlite-vec ≥ 0.1.10 once IVF/DiskANN ship as
   `vec0` options and re-evaluate.
3. Pre-filter via `entity_id IN (SELECT ... FROM am_entities WHERE ...)`
   then rank — vec0 honors candidate-restriction pushdown.
