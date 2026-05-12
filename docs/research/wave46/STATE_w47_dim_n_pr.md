# Wave 47 Dim N (anonymized_query) migration + storage PR

date: 2026-05-12
branch: feat/jpcite_2026_05_12_wave47_dim_n_migration
PR#: #159 (https://github.com/shigetosidumeda-cyber/autonomath-mcp/pull/159)

## Scope

Land the **persistence layer** behind Dim N (`anonymized_query_pii_redact`,
PR #139's `POST /v1/network/anonymized_outcomes` REST kernel). PR #139
ships an in-memory ring buffer (`_AUDIT_LOG: collections.deque(maxlen=1000)`)
+ a deterministic synthetic aggregator (`aggregate_cohort`). Wave 47 adds
two SQL tables + a nightly aggregator ETL so the audit trail survives
Fly machine swaps and the cohort outcomes view can be refreshed from the
real entity corpus — **without rewiring the live REST handler**.

This is the same shape as Wave 47 Dim K (PR #152) and Dim L (PR #155):
atomic storage layer + ETL + integration test + dual boot-manifest
registration, no new REST endpoints, no LLM API import.

## Files added

| Path                                                       | LOC | Purpose                                                              |
| ---------------------------------------------------------- | --- | -------------------------------------------------------------------- |
| `scripts/migrations/274_anonymized_query.sql`              | 119 | `am_anonymized_query_log` + `am_aggregated_outcome_view` + view      |
| `scripts/migrations/274_anonymized_query_rollback.sql`     |  19 | rollback (drop indexes/view/tables)                                  |
| `scripts/etl/aggregate_anonymized_outcomes.py`             | 206 | nightly cohort aggregator (k>=5 floor, single-snapshot rebuild)      |
| `tests/test_dim_n_storage_integration.py`                  | 464 | 17 integration tests (mig + ETL + REST kernel contract)              |
| `scripts/migrations/jpcite_boot_manifest.txt`              | +10 | append `274_anonymized_query.sql`                                    |
| `scripts/migrations/autonomath_boot_manifest.txt`          | +10 | append `274_anonymized_query.sql`                                    |

Migration LOC: **~138** (sql 119 + rollback 19).
Total touched: **~808** (sql 138 + etl 206 + tests 464).

## Schema (mig 274)

- `am_anonymized_query_log`
  - `query_id INTEGER PRIMARY KEY AUTOINCREMENT`
  - `query_hash TEXT NOT NULL` — sha256(industry|region|size)[:16]
  - `k_anonymity_value INTEGER NOT NULL` CHECK >= 0 (post-eval count)
  - `pii_stripped TEXT NOT NULL DEFAULT '{}'` — JSON {redact_policy_version, cohort_size}
  - `audit_token TEXT NOT NULL` — random hex for ops trace
  - `requested_at TEXT NOT NULL DEFAULT (strftime ...)`
  - Indexes: `(query_hash, requested_at DESC)`, `(requested_at DESC)`
- `am_aggregated_outcome_view`
  - `cluster_id INTEGER PRIMARY KEY AUTOINCREMENT`
  - `entity_cluster_id TEXT NOT NULL` — e.g. `industry=F|region=13101|size=sme`
  - `outcome_type TEXT NOT NULL` CHECK in (`adoption`,`enforcement`,`amendment`,`program_apply`)
  - `count INTEGER NOT NULL` **CHECK (count >= 5)** — k=5 hard cap
  - `k_value INTEGER NOT NULL` **CHECK (k_value >= 5)** — k=5 hard cap (mirror)
  - `mean_amount_yen INTEGER`, `median_amount_yen INTEGER`, `last_updated`
  - UNIQUE `(entity_cluster_id, outcome_type)`
  - Indexes: `entity_cluster_id`, `(outcome_type, last_updated DESC)`
- View `v_anon_cohort_outcomes_latest`: rows with `k_value >= 5`
  (defence-in-depth filter even though the table CHECK already enforces).

## ETL: `aggregate_anonymized_outcomes.py`

Pure-SQL nightly aggregator, idempotent, dry-run-able:

1. Read `am_entities` corporate_entity rows grouped by
   `(industry_jsic_major, region_code[:5], size_bucket)`.
2. Apply `HAVING COUNT(*) >= K_ANONYMITY_MIN` (5) at materialization
   time — sub-floor cohorts dropped entirely, never written.
3. Single-snapshot rebuild: `DELETE FROM am_aggregated_outcome_view`
   then `INSERT` the eligible cohort rows (one per outcome_type axis).
4. Tolerant of missing `am_entities` table (dev fixtures) — emits zero
   cohorts without raising.

Outputs JSON `{dim:"N", aggregate_stats:{inserted, skipped_below_k,
rebuilt}}`. Designed to be wired into the daily cron in a follow-up PR
(no new workflow added here — strict storage-only PR).

## Verify

- `sqlite3 < 274_anonymized_query.sql` clean (3 objects: 2 tables + 1 view).
- 2nd apply idempotent (every CREATE uses `IF NOT EXISTS`).
- Rollback drops all indexes + view + tables cleanly.
- CHECK constraints fire on `count < 5` and `k_value < 5` (live python
  probe confirmed for k in {0,1,2,3,4}; k=5 first accepted row).
- ETL dry-run → JSON plan with 4 cohort rows (1 eligible cohort × 4
  outcome_types), zero rows written to disk.
- ETL apply → identical counts, real rows inserted; sub-k=5 cohort
  (G/27100/large, k=3) dropped entirely.
- 17 pytest cases land green via `.venv/bin/python -m pytest
  tests/test_dim_n_storage_integration.py` → **17/17 PASS in 1.54s**.
- REST kernel guard: `_AUDIT_LOG: collections.deque` still present, no
  `am_anonymized_query_log` / `am_aggregated_outcome_view` reference in
  the REST kernel — Wave 47 is pure additive at the storage layer.
- Both boot manifests register `274_anonymized_query.sql`.
- No `import anthropic|openai|google.generativeai` in any new file (Dim
  N stays deterministic per `feedback_no_operator_llm_api`).
- No legacy brand (`税務会計AI` / `zeimu-kaikei.ai`) in new files.

## Hard constraints honoured

- PR #139 REST kernel **untouched** (Wave 47 only adds audit storage +
  aggregator; the in-memory `_AUDIT_LOG` ring buffer stays
  source-of-truth on each Fly machine, per
  `feedback_anonymized_query_pii_redact`).
- **k=5 hard cap enforced TWICE**: at the CHECK constraint level AND at
  the aggregator HAVING clause. A sub-floor cohort cannot land in the
  view even if a single layer is buggy.
- No `rm` / `mv` (destructive-free organization rule).
- No main worktree (atomic lane = `/tmp/jpcite-w47-dim-n-mig.lane`).
- No LLM API import in storage / ETL / migration layers.
- Migration number 274 (next free after 271 Dim K + 272 Dim L; 273
  intentionally reserved for the in-flight Dim M PR).
- Table names align with the disclaimer in `anonymized_query.py`
  (`am_anonymized_query_log` matches the inline schema marker
  `am_anon_query_log` in the REST docstring; the view name surfaces
  the same disclaimer's `am_anon_query_view`).
- jpcite brand discipline: jp brand-first comments, autonomath only as
  the historical SQLite filename (per `feedback_legacy_brand_marker`).
- `K_ANONYMITY_MIN = 5` mirrors the REST constant
  (`src/jpintel_mcp/api/anonymized_query.py`); test case asserts the
  REST surface pins `K_ANONYMITY_MIN == 5` to match the SQL CHECK.
- `_RESPONSE_WHITELIST` surface intersects the SQL view columns (test
  case verifies `cohort_size / industry_jsic_major / region_code /
  size_bucket` surface AND `houjin_bangou / company_name` do NOT).
