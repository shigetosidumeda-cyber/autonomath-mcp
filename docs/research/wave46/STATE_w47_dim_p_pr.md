# Wave 47 — Dim P (composable_tools) migration PR state

Generated 2026-05-12 (Wave 46 永遠ループ tick#4).

## PR scope

Closes the Dim P (composable_tools) storage gap left after the Wave 46
booster PR (which only landed the migration 269 rollback companion).
This PR introduces the actual catalogue + invocation-log substrate and
seeds the 4 canonical composed tools — moving Dim P from "REST-only
shim" to "first-class storage axis" alongside Dim K and Dim L.

## Wave 47 (Dim P) deliverables

| File                                                      | Kind        | LOC  |
| --------------------------------------------------------- | ----------- | ---- |
| `scripts/migrations/276_composable_tools.sql`             | Migration   | ~114 |
| `scripts/migrations/276_composable_tools_rollback.sql`    | Rollback    |  ~19 |
| `scripts/etl/seed_composed_tools.py`                      | ETL seed    | ~260 |
| `tests/test_dim_p_composable_tools.py`                    | Tests (13)  | ~346 |
| `scripts/migrations/jpcite_boot_manifest.txt`             | Manifest    | +11  |
| `scripts/migrations/autonomath_boot_manifest.txt`         | Manifest    | +11  |

Total: ~120 LOC across the migration pair (276 + rollback) and ~600 LOC
overall. Hard constraints honored: NO LLM, NO main worktree, NO rm/mv,
NO 旧 brand (税務会計AI / zeimu-kaikei.ai), NO atomic-tool overwrite.

## Storage schema

### `am_composed_tool_catalog`
- `row_id` PK (autoinc), `tool_id` TEXT NOT NULL, `version` INTEGER ≥ 1
  with UNIQUE (tool_id, version)
- `atomic_tool_chain` TEXT (canonical JSON chain) — keyed manifest of
  step / tool / phase for the dispatcher
- `source_doc_id` TEXT — Dim O citation anchor
- `description`, `domain`, `status` (committed / draft / retired)
- 2 indices: `(tool_id, version DESC)` and `(domain, status)`

### `am_composed_tool_invocation_log`
- `invocation_id` PK (autoinc), `tool_id`, `tool_version` (nullable for
  ad-hoc), `input_hash` (sha256), `output_hash` (sha256), `latency_ms`
- `result` CHECK in (ok / partial / error), `error_message` TEXT
- 2 indices: `(tool_id, created_at DESC)` and `(input_hash)`

### `v_composed_tools_latest` (helper view)
Exposes `(tool_id, latest_version, total_versions)` for committed rows
so the dispatcher picks the freshest committed version without a
self-join.

## Seeded composed tools (4)

| `tool_id`                       | domain          | atomic chain length | savings |
| ------------------------------- | --------------- | ------------------- | ------- |
| `ultimate_due_diligence_kit`    | due_diligence   | 7                   | 7×      |
| `construction_total_dd`         | construction    | 5                   | 5×      |
| `welfare_total_dd`              | welfare         | 4                   | 4×      |
| `tourism_total_dd`              | tourism         | 5                   | 5×      |

Each composed tool wraps a fixed sequence of already-shipped atomic
tools (`match_due_diligence_questions`, `cross_check_jurisdiction`,
`check_enforcement_am`, `get_annotations`, `get_provenance`,
`track_amendment_lineage_am`, `bundle_application_kit`,
`pack_construction`, `apply_eligibility_chain_am`,
`search_acceptance_stats_am`, `get_am_tax_rule`, `program_lifecycle`,
`search_mutual_plans_am`, `list_open_programs`, `search_gx_programs_am`,
`find_complementary_programs_am`). NO new atomic tools are introduced —
the seed is pure composition.

## Billing posture

¥3/req contract unchanged: one composed call = one metered unit even when
the dispatcher executes 4-7 atomic steps server-side. Atomic-tool
in-process dispatch invokes zero LLM API calls
(`feedback_no_operator_llm_api`); the seed and migration carry no LLM
SDK imports either (verified by `test_no_llm_import_in_etl_or_migration`).

## Verify

```
$ /Users/shigetoumeda/jpcite/.venv/bin/pytest \
    tests/test_dim_p_composable_tools.py -x -q
13 passed in 1.57s

$ python scripts/etl/seed_composed_tools.py --db /tmp/sample.db
{"dim": "P", "seed_stats": {"inserted": 4, "skipped": 0, "total": 4}}

$ python scripts/etl/seed_composed_tools.py --db /tmp/sample.db
{"dim": "P", "seed_stats": {"inserted": 0, "skipped": 4, "total": 4}}
```

Migration is idempotent (re-apply no-op), rollback drops cleanly, and
both boot manifests register `276_composable_tools.sql` with a Wave 47
header block.
