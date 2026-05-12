# Wave 47 — Dim A (semantic_search legacy v1) migration PR state

Generated 2026-05-12 (Wave 47 Phase 2 永遠ループ tick#5).

## PR scope

Closes the Dim A (semantic_search legacy v1) storage gap left after PR
\#144, which landed the REST wrap for the v1 hash-fallback path but
without a disk-backed substrate. Migration 260 already covers the
canonical v2 layer (e5-small 384-dim sqlite-vec + cross-encoder
reranker); this PR adds the parallel legacy v1 layer so the v1 wrap
becomes 100% boot-survivable instead of in-memory only.

The v1 layer is retained for two reasons:

1. **Graceful fallback** when sqlite-vec extension fails to load (Wave
   47 wires the v1 cache as the read-only fallback so cold-start traffic
   is not lost).
2. **Long-tail warm cache** — top 100 canonical queries baked offline
   so the ¥3/req micropayment still returns a useful top-K hit when
   the vec0 table is cold or absent.

## Wave 47 (Dim A) deliverables

| File                                                          | Kind          | LOC  |
| ------------------------------------------------------------- | ------------- | ---- |
| `scripts/migrations/284_semantic_search_v1.sql`               | Migration     |  ~85 |
| `scripts/migrations/284_semantic_search_v1_rollback.sql`      | Rollback      |  ~20 |
| `scripts/etl/build_semantic_search_v1_cache.py`               | ETL prebuild  | ~180 |
| `tests/test_dim_a_semantic_v1.py`                             | Tests (13)    | ~230 |
| `scripts/migrations/autonomath_boot_manifest.txt`             | Manifest      |  +14 |
| `scripts/migrations/jpcite_boot_manifest.txt`                 | Manifest      |  +14 |
| `docs/research/wave46/STATE_w47_dim_a_pr.md`                  | State doc     |  ~150 |

Total: ~150 LOC across the migration pair (284 + rollback) and ~700
LOC overall. Hard constraints honored: NO LLM API, NO main worktree
(used dual-CLI lane `mkdir /tmp/jpcite-w47-dim-a-mig.lane` per
`feedback_dual_cli_lane_atomic`), NO rm/mv (additive-only), NO 旧
brand (税務会計AI / zeimu-kaikei.ai / AutonoMath agri), NO mig 260
overwrite (DDL stays disjoint per `test_no_overlap_with_mig_260`).

## Storage schema

### `am_semantic_search_v1_cache`
- `cache_id` TEXT PRIMARY KEY (sha256 of normalized query)
- `query_text` TEXT — raw query, baked offline only
- `embedding` BLOB NOT NULL — float32 packed bytes (1536 = 384 × 4)
- `embedding_dim` INTEGER default 384 with CHECK > 0
- `top_k_results` TEXT NOT NULL — JSON array of `{entity_id, score}`,
  CHECK length > 0
- `top_k` INTEGER default 10 with CHECK 1..100
- `model_name` default `hash-fallback-e5-small-v1`
- `cached_at` ISO-8601 UTC
- 1 index: `(cached_at)` for sweep

### `am_semantic_search_v1_log`
- `search_id` PK AUTOINCREMENT
- `query_hash` TEXT NOT NULL — raw query NEVER stored on log path
- `latency_ms` INTEGER CHECK >= 0
- `hit_count` INTEGER CHECK >= 0
- `cache_hit` INTEGER CHECK IN (0, 1)
- `searched_at` ISO-8601 UTC
- 2 indices: `(query_hash)` and `(searched_at)` — hit-rate KPI + TTFP

## ETL semantics

`scripts/etl/build_semantic_search_v1_cache.py` pre-warms the top-N
(default 100) canonical queries deterministically:

- **Embedding** — `hashlib.sha512` chain expanded to 1536 bytes then
  unpacked as 384 float32 in [-1, 1]. NO LLM, NO network, NO
  sentence-transformers (the v1 layer is hash-fallback by design;
  the v2 layer keeps sentence-transformers).
- **Top-K results** — pure SQL `LIKE` scan over `am_entities`,
  graceful empty list if the table is absent (test fixtures).
- **Idempotent** — `cache_id` PK collision is skipped, not aborted;
  re-running the ETL after partial completion writes only the missing
  rows.

Smoke verify (Python 3.13, temp DB):
- 20 seed queries × dedup → 10 cache rows written, 10 skipped.
- Embedding integrity: `length(embedding) == embedding_dim * 4` = 1536.
- ETL elapsed: 9 ms / 20 queries (hash-fallback is cheap).

## Test matrix (13/13 green)

| Test                                          | Asserts                                                       |
| --------------------------------------------- | ------------------------------------------------------------- |
| `test_mig_284_creates_two_tables`             | exactly `cache` + `log`, no extras                            |
| `test_mig_284_creates_three_indexes`          | cache×1 + log×2 by name                                       |
| `test_cache_id_is_primary_key`                | duplicate insert → IntegrityError                             |
| `test_top_k_check_constraint`                 | top_k = 0 → IntegrityError                                    |
| `test_log_cache_hit_boolean`                  | cache_hit = 2 → IntegrityError                                |
| `test_log_latency_nonneg`                     | latency_ms = -1 → IntegrityError                              |
| `test_log_autoincrement`                      | search_id = 1, 2, 3 in order                                  |
| `test_embedding_dim_check`                    | embedding_dim = 0 → IntegrityError                            |
| `test_etl_idempotent`                         | 2× run = 1× rows + ≥10 skipped, embedding bytes = dim × 4     |
| `test_etl_top_k_results_is_valid_json`        | JSON parses to list of `{entity_id, score}`                   |
| `test_rollback_drops_everything`              | mig + rollback → 0 tables, 0 indexes                          |
| `test_no_llm_api_import_in_etl`               | 0 `anthropic` / `openai` / `google.generativeai` / `claude_agent_sdk` |
| `test_no_overlap_with_mig_260`                | DDL of mig 284 ≠ DDL of mig 260 (comments allowed)            |

## Constraint compliance summary

- `feedback_no_operator_llm_api`: 0 LLM imports in `scripts/etl/` +
  `tests/` + the SQL migration itself. Verified by `test_no_llm_api_import_in_etl`.
- `feedback_dual_cli_lane_atomic`: lane claimed via
  `mkdir /tmp/jpcite-w47-dim-a-mig.lane` (atomic) + worktree on
  separate branch — main worktree untouched.
- `feedback_destruction_free_organization`: no `rm` / `mv` / file
  rename. Pure additive across SQL, ETL, tests, manifest.
- `feedback_completion_gate_minimal`: PR-gate is the 13/13 pytest +
  SQL syntax verify, not a 40-item checklist. The v1 layer is opt-in
  for runtime callers; the canonical v2 path remains unchanged.

## PR

PR # will be filled by `gh pr create` immediately after the worktree
push. Branch `feat/jpcite_2026_05_12_wave47_dim_a_migration` against
`main`.
