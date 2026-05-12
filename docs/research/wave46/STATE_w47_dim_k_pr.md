# Wave 47 Dim K migration + storage PR (W46 tick#8 prequel)

date: 2026-05-12
branch: feat/jpcite_2026_05_12_wave47_dim_k_migration
PR#: #152 (https://github.com/shigetosidumeda-cyber/autonomath-mcp/pull/152)

## Scope

Land the **storage substrate** behind Dim K (`rule_tree_branching`,
PR #139's `/v1/rule_tree/evaluate` REST kernel). PR #139 evaluates trees
posted inline; production agents need a curated, versioned catalogue
of named trees + an audit trail. Wave 47 adds that catalogue + audit
log + a 5-tree seed without touching the kernel.

## Files added

| Path                                                  | LOC | Purpose                                       |
| ----------------------------------------------------- | --- | --------------------------------------------- |
| `scripts/migrations/271_rule_tree.sql`                | 107 | `am_rule_trees` + `am_rule_tree_eval_log` + view |
| `scripts/migrations/271_rule_tree_rollback.sql`       |  19 | rollback (drop indexes/view/tables)           |
| `scripts/etl/seed_rule_tree_definitions.py`           | 414 | 5 canonical tree seed ETL                     |
| `tests/test_dim_k_storage_integration.py`             | 409 | 13 integration tests (mig + ETL + kernel)     |
| `scripts/migrations/jpcite_boot_manifest.txt`         |  +9 | append `271_rule_tree.sql`                    |
| `scripts/migrations/autonomath_boot_manifest.txt`     |  +9 | append `271_rule_tree.sql`                    |

ETL seed 5 trees: `subsidy_eligibility_v1` / `gyouhou_fence_check_v1` /
`investment_condition_check_v1` / `adoption_score_threshold_v1` /
`due_diligence_v1`. ~150 LOC of tree DAGs (4 dicts each, ~30 LOC/tree),
~260 LOC of helpers + CLI.

## Verify

- `sqlite3 < 271_rule_tree.sql` clean (3 objects: 2 tables + 1 view).
- 2nd apply idempotent (every CREATE uses `IF NOT EXISTS`).
- Rollback drops table+view+indexes cleanly.
- ETL seed dry-run → 5 inserted plan, 0 rows actually written.
- ETL seed apply → 5 inserted; 2nd apply → 0 inserted, 5 skipped.
- Each of the 5 seeded trees feeds through PR #139's
  `evaluate_rule_tree` kernel and returns `result=pass` for a
  hand-picked positive input (rationale length matches path length).
- DD tree's `XOR(has_audit_opinion, exempt_from_audit)` branch
  correctly fails when both true or both false.
- Subsidy tree fails when `industry_code='Z'` (not in target set).
- Both boot manifests register `271_rule_tree.sql`.
- `pytest tests/test_dim_k_storage_integration.py` → **13/13 PASS**.
- `pytest tests/test_dimension_k_rule_tree.py` (PR #139 kernel) →
  **13/13 PASS** (zero regression).
- No `import anthropic|openai|google.generativeai` in any new file
  (Dim K is fully deterministic per `feedback_rule_tree_branching`).
- No legacy brand (`税務会計AI` / `zeimu-kaikei.ai`) in new files.

## Hard constraints honoured

- PR #139 REST kernel untouched (Wave 47 only adds the storage
  catalogue + audit log; the eval surface stays one-call ¥3/req).
- No `rm` / `mv` (destructive-free organization rule).
- No main worktree (atomic lane = `/tmp/jpcite-w47-dim-k-mig.lane`).
- No LLM API import in storage / ETL / migration layers.
- Migration number 271 (next free; 269 is the last main slot, 270
  reserved by an in-flight booster).
- Table names match the disclaimer string already shipped in
  `rule_tree_eval.py` (`am_rule_trees` / `am_rule_nodes` family —
  Wave 47 introduces `am_rule_trees` + `am_rule_tree_eval_log`; the
  full `am_rule_nodes` normalised table is deferred to a future
  migration if denormalisation pressure arises).
- jpcite brand discipline: jp brand-first comments, autonomath only
  as the historical SQLite filename (per
  `feedback_legacy_brand_marker`).
