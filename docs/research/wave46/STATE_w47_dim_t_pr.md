# Wave 47 — Dim T (predictive service) migration PR — STATE

- **Date**: 2026-05-12 (Wave 47 Phase 2 永遠ループ tick#6)
- **Dim**: T — predictive service (pull -> push) per `feedback_predictive_service_design`
- **Branch**: `feat/jpcite_2026_05_12_wave47_dim_t_migration`
- **Worktree**: `/tmp/jpcite-w47-dim-t-mig` (lane claim: `/tmp/jpcite-w47-dim-t-mig.lane`)
- **Base**: `origin/main` @ `6141128b3`
- **PR**: filled at push time

## Purpose

Storage substrate + daily ETL for the Dim T "predictive service" surface
— the pull-to-push transition required by `feedback_predictive_service_design`.

Three watch sources are unified into a single predictive subscription
table + a single per-fire audit log:

- `houjin`    — watch a 法人番号; predictive fires from `am_amendment_diff` rows whose `entity_id` matches.
- `program`   — watch a `programs.unified_id`; predictive fires when an `am_amendment_diff` row lands AND the program deadline window is still actionable.
- `amendment` — watch a `laws.law_id`; predictive fires from any `am_amendment_diff` row whose `entity_id` is a sub-article under the watched law.

24h notification window (configurable 1..168h per subscription).
Stale pending alerts are flipped to `expired` by a TTL purge in the
same daily ETL pass.

**LLM-0 by construction** (per `feedback_no_operator_llm_api` +
`feedback_predictive_service_design`): we only RANK + ROUTE rows that
already exist in `am_amendment_diff`. No Anthropic / OpenAI SDK is
imported anywhere in the new code. Natural-language summarisation is
done by the customer's OWN agent on their side. Tests guard the
invariant (`test_no_llm_token_in_predictive_etl`,
`test_no_llm_import_in_migration`).

## Files (3 new + 2 manifest edits)

| Path | LOC | Role |
| ---- | --- | ---- |
| `scripts/migrations/280_predictive_service.sql` | 122 | schema (subscription + alert log + view) |
| `scripts/migrations/280_predictive_service_rollback.sql` | 24 | rollback (drops only Dim T surface) |
| `scripts/etl/build_predictive_watch_v2.py` | 219 | daily 3-type scan + 24h TTL purge |
| `tests/test_dim_t_predictive.py` | 359 | 18 cases (mig + ETL + 3 watch type + TTL + dedup + LLM-0 guard) |
| `scripts/migrations/jpcite_boot_manifest.txt` | +20 | register 280 |
| `scripts/migrations/autonomath_boot_manifest.txt` | +20 | register 280 mirror |

## Schema (migration 280)

- `am_predictive_watch_subscription` (PK=`watch_id` INTEGER AUTOINCREMENT)
  - `subscriber_token_hash` sha256 hex (CHECK length=64; raw token never stored)
  - `watch_type` ENUM CHECK IN ('houjin','program','amendment')
  - `watch_target` opaque per type (CHECK length 1..128)
  - `threshold` REAL DEFAULT 0.0 (CHECK >= 0.0; 0.0 = always fire)
  - `notify_window_hours` INTEGER DEFAULT 24 (CHECK 1..168; predictive push window)
  - `status` ENUM CHECK IN ('active','paused','cancelled')
  - `created_at`, `updated_at`, `last_fired_at` (NULL until first fire)
  - Indexes:
    - `idx_am_predictive_watch_target` on (watch_type, watch_target, status) — ETL daily scan hot path
    - `idx_am_predictive_watch_subscriber` on (subscriber_token_hash, status) — "list my subscriptions"
    - `uq_am_predictive_watch_active` UNIQUE on (subscriber_token_hash, watch_type, watch_target) WHERE status='active' — dedup
- `am_predictive_alert_log` (PK=`alert_id` INTEGER AUTOINCREMENT)
  - `watch_id` FK -> `am_predictive_watch_subscription(watch_id)`
  - `fired_at` (NOT NULL, default `now`)
  - `source_diff_id` (nullable — for program-window-only fires)
  - `payload` JSON (CHECK length 2..65536)
  - `delivery_status` ENUM CHECK IN ('pending','delivered','failed','expired') — only `delivered` bills ¥3/req
  - `delivered_at` (CHECK >= `fired_at`)
  - Indexes:
    - `idx_am_predictive_alert_watch` on (watch_id, fired_at DESC)
    - `idx_am_predictive_alert_status` on (delivery_status, fired_at)
    - `idx_am_predictive_alert_pending_age` partial on (fired_at) WHERE delivery_status='pending' — TTL scan hot path
    - `uq_am_predictive_alert_dedup` partial UNIQUE on (watch_id, source_diff_id) WHERE source_diff_id IS NOT NULL — prevents double-fire
- `v_predictive_watch_active` helper view (status='active' only, ordered by watch_type+target — driven by ETL collector)

## ETL contract (build_predictive_watch_v2.py)

Single pass evaluates all 3 watch types via a JOIN against
`am_amendment_diff` (gracefully no-op when the upstream table is
absent). For each candidate `(watch_id, source_diff_id)` tuple NOT
already in the alert log, INSERT one row with `delivery_status='pending'`
and a structural JSON payload (`watch_type`, `watch_target`,
`source_diff_id`, `detected_at`). Side-pass flips stale `pending` rows
older than `notify_window_hours` to `expired`.

- `--dry-run` plans only (returns counts, writes nothing).
- `--since-hours N` lets the cron backfill (default 24h).
- Final stdout line is JSON `{"dim":"T","wave":47,"dry_run":bool,"queued":int,"expired":int,"by_type":{...}}`.

## Tests (18 cases, all green)

```
tests/test_dim_t_predictive.py::test_mig_280_applies_clean PASSED
tests/test_dim_t_predictive.py::test_mig_280_is_idempotent PASSED
tests/test_dim_t_predictive.py::test_mig_280_rollback_drops_all PASSED
tests/test_dim_t_predictive.py::test_check_watch_type_enum PASSED
tests/test_dim_t_predictive.py::test_check_token_hash_length PASSED
tests/test_dim_t_predictive.py::test_check_threshold_non_negative PASSED
tests/test_dim_t_predictive.py::test_check_notify_window_range PASSED
tests/test_dim_t_predictive.py::test_check_delivered_at_after_fired_at PASSED
tests/test_dim_t_predictive.py::test_three_watch_types_fire_via_etl PASSED
tests/test_dim_t_predictive.py::test_etl_dry_run_writes_nothing PASSED
tests/test_dim_t_predictive.py::test_ttl_purge_marks_stale_pending_expired PASSED
tests/test_dim_t_predictive.py::test_dedup_prevents_double_fire PASSED
tests/test_dim_t_predictive.py::test_unique_active_partial_index PASSED
tests/test_dim_t_predictive.py::test_manifest_jpcite_lists_280 PASSED
tests/test_dim_t_predictive.py::test_manifest_autonomath_lists_280 PASSED
tests/test_dim_t_predictive.py::test_no_llm_token_in_predictive_etl PASSED
tests/test_dim_t_predictive.py::test_no_llm_import_in_migration PASSED
tests/test_dim_t_predictive.py::test_no_legacy_brand_in_new_files PASSED
========================== 18 passed in 1.53s ==========================
```

Coverage by case bundle:

1. Migration applies cleanly + idempotent re-apply.
2. Rollback drops every artefact.
3. CHECK constraints (watch_type enum, token_hash length=64, threshold>=0, notify_window 1..168, delivered_at>=fired_at, status enum).
4. Three watch types (houjin/program/amendment) fire via ETL in one pass.
5. Dry-run plans without writing.
6. 24h TTL purge flips stale `pending` -> `expired`.
7. Dedup partial unique index prevents double-fire on (watch_id, source_diff_id).
8. Unique-active partial index allows re-subscription after cancellation.
9. Boot manifest registration (jpcite + autonomath mirror).
10. LLM-0 verify (zero `anthropic`/`openai`/`google.generativeai` tokens in code).
11. No legacy brand (`税務会計AI` / `zeimu-kaikei.ai`) in new files.

## Constraints satisfied

- ✅ Migration 280 is pure additive (CREATE TABLE/INDEX/VIEW IF NOT EXISTS); no UPDATE/DELETE of existing rows.
- ✅ Idempotent on every boot (Fly entrypoint.sh §4 safe).
- ✅ Both boot manifests register 280 (jpcite + autonomath mirror).
- ✅ Rollback is dev-only and only drops Dim T surface — customer_watches (mig 088) is untouched.
- ✅ LLM-0 by construction — verified by `test_no_llm_token_in_predictive_etl` + `test_no_llm_import_in_migration`.
- ✅ Brand discipline — no legacy `税務会計AI` / `zeimu-kaikei.ai` references.
- ✅ ¥3/req billing posture preserved (only `delivered` rows trigger Stripe usage_record on the dispatcher side; this ETL only enqueues).
- ✅ No existing cron / workflow / source file was overwritten (only 2 boot manifests appended).
- ✅ Main worktree untouched (work done in `/tmp/jpcite-w47-dim-t-mig`).
- ✅ No `rm` / `mv` (banner+index style organisation per `feedback_destruction_free_organization`).
- ✅ Lane claim atomic via `mkdir /tmp/jpcite-w47-dim-t-mig.lane`.

## Post-PR

- Wire `scripts/cron/dispatch_predictive_alerts.py` (runtime layer) — pops `pending` rows, POSTs to subscriber webhooks, flips to `delivered` / `failed`. Out of scope here (this PR is the storage layer + ETL).
- Wire REST `GET/POST/DELETE /v1/me/predictive/watches/...` (customer-facing CRUD). Out of scope.
- Wire MCP tool `predictive.subscribe` / `predictive.list`. Out of scope.
- Schedule `build_predictive_watch_v2.py` in `.github/workflows/predictive-watch-daily.yml`. Out of scope (this PR keeps the daily cron wiring separate so the storage layer can land first).
