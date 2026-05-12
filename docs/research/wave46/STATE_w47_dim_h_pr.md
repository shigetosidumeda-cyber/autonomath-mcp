# Wave 47 — Dim H (personalization preference storage) migration PR — STATE

- **Date**: 2026-05-12 (Wave 47 Phase 2 永遠ループ tick#8)
- **Dim**: H — personalization preference storage (customer-controlled preference blob + recommendation audit log)
- **Branch**: `feat/jpcite_2026_05_12_wave47_dim_h_migration`
- **Worktree**: `/tmp/jpcite-w47-dim-h-mig` (lane claim: `/tmp/jpcite-w47-dim-h-mig.lane`)
- **Base**: `origin/main` @ `cd5b7bbfb` (Wave 47 Dim T `(#171)` HEAD)
- **PR**: filled at push time

## Purpose

Storage substrate + nightly ETL for the Dim H "personalization
preference storage" surface. Complements migration 264
(`am_personalization_score` from Wave 43.2.8 — derived per-program
scores) by adding the **upstream preference inputs** and **downstream
audit trail** that 264 does NOT capture:

- `am_personalization_profile` — customer-controlled preference blob
  keyed by `user_token_hash` sha256 hex (the raw API key is NEVER
  stored; auth middleware discards it post-hash). `preference_json`
  holds the customer's OWN declared preferences (industry pack, risk
  tolerance, deadline horizon). Strict CHECK on length (2..16384) +
  hash length (=64).
- `am_personalization_recommendation_log` — append-only audit of
  every recommendation served (one row per (profile, recommendation_type,
  served_at)). Drives both billing reconciliation (¥3/req on
  delivery) AND forensic replay ("why did we recommend X?").

The two layers (264 score table + 287 preference + audit) are
intentionally decoupled. Rolling back 287 does NOT drop 264.

## Privacy posture (Dim H critical)

**ZERO PII** at the storage layer (per
`feedback_anonymized_query_pii_redact` /
`feedback_explainable_fact_design`):

- The only identifier in `am_personalization_profile` is
  `user_token_hash` (sha256 hex of the API key). Raw key NEVER stored.
- `preference_json` holds ONLY declared preference data (industry,
  deadline horizon, risk tolerance). No email, no IP, no 法人番号, no
  name, no phone.
- `am_personalization_recommendation_log` columns: `rec_id`,
  `profile_id` FK, `recommendation_type` enum, `score` int 0..100,
  `served_at`. No payload column → no risk of accidental PII leak.
- CI guard `test_schema_no_pii_columns` greps the PRAGMA table_info
  output for `email`/`mail_addr`/`ip_addr`/`houjin_bangou`/
  `corporate_number`/`user_name`/`full_name`/`phone` → must be empty.
- CI guard `test_schema_uses_token_hash_only` asserts the profile
  table uses `user_token_hash` as the only identifier.

**LLM-0 by construction** (per `feedback_no_operator_llm_api`): the
nightly scoring ETL is purely deterministic (industry match * 50 +
deadline proximity * 30 + risk tolerance * 20, all configurable
constants). No Anthropic / OpenAI SDK is imported. CI guard
`test_etl_llm_zero` grep-asserts no `import anthropic` / `from
anthropic` / `import openai` / `from openai` line in the ETL source.

## Files (4 new + 2 manifest edits)

| Path | LOC | Role |
| ---- | --- | ---- |
| `scripts/migrations/287_personalization.sql` | 116 | schema (profile + rec log + view) |
| `scripts/migrations/287_personalization_rollback.sql` | 29 | rollback (drops only Dim H surface; 264 untouched) |
| `scripts/etl/build_personalization_recommendations.py` | 261 | nightly deterministic scoring + audit insert |
| `tests/test_dim_h_personalization.py` | 439 | 17 cases (mig + CHECK + FK + UNIQUE + ETL + privacy + LLM-0 + brand) |
| `scripts/migrations/jpcite_boot_manifest.txt` | +24 | register 287 |
| `scripts/migrations/autonomath_boot_manifest.txt` | +24 | register 287 mirror |

## Schema (migration 287)

- `am_personalization_profile` (PK=`profile_id` INTEGER AUTOINCREMENT)
  - `user_token_hash` TEXT NOT NULL UNIQUE — sha256 hex (CHECK length=64)
  - `preference_json` TEXT NOT NULL DEFAULT '{}' — declared prefs only (CHECK length 2..16384)
  - `created_at`, `last_updated_at` — CHECK last_updated_at >= created_at
  - Index: `idx_am_personalization_profile_token` on (user_token_hash) — single-row lookup hot path
- `am_personalization_recommendation_log` (PK=`rec_id` INTEGER AUTOINCREMENT)
  - `profile_id` FK -> `am_personalization_profile(profile_id)`
  - `recommendation_type` ENUM CHECK IN ('program','industry_pack','saved_search','amendment')
  - `score` INTEGER CHECK BETWEEN 0..100
  - `served_at` TEXT NOT NULL (default now)
  - Indexes:
    - `idx_am_pers_rec_profile_served` on (profile_id, served_at DESC) — "my recommendations, most recent first"
    - `idx_am_pers_rec_type_score` on (recommendation_type, score DESC, served_at DESC) — forensic by-type
- `v_personalization_recent_recs` helper view — joins log to profile, exposes user_token_hash + score DESC

## ETL contract (build_personalization_recommendations.py)

Nightly pass scans every row in `am_personalization_profile`. For each
(profile, recommendation_type) tuple, computes a deterministic
score 0..100 from the preference_json and INSERTs one audit row when
score > 0 (zero-score rows are skipped to save billing-reconciliation
noise). No randomness, no LLM, no external API.

- `--dry-run` plans only (counts, writes nothing).
- `--top-k N` caps fanout per (profile, recommendation_type) — default 10, currently produces 1 row per tuple per nightly run (top_k is the future fanout knob).
- Final stdout line is JSON `{"dim":"H","wave":47,"dry_run":bool,"profiles":int,"logged":int,"by_type":{...}}`.

## Tests (17 cases, all green)

```
tests/test_dim_h_personalization.py::test_migration_287_applies_cleanly PASSED
tests/test_dim_h_personalization.py::test_migration_287_idempotent PASSED
tests/test_dim_h_personalization.py::test_migration_287_rollback PASSED
tests/test_dim_h_personalization.py::test_user_token_hash_wrong_length_rejected PASSED
tests/test_dim_h_personalization.py::test_preference_json_too_small_rejected PASSED
tests/test_dim_h_personalization.py::test_score_out_of_range_rejected PASSED
tests/test_dim_h_personalization.py::test_recommendation_type_enum_rejected PASSED
tests/test_dim_h_personalization.py::test_unique_user_token_hash PASSED
tests/test_dim_h_personalization.py::test_fk_profile_id PASSED
tests/test_dim_h_personalization.py::test_etl_scores_active_profiles PASSED
tests/test_dim_h_personalization.py::test_etl_guard_rejects_missing_schema PASSED
tests/test_dim_h_personalization.py::test_schema_no_pii_columns PASSED
tests/test_dim_h_personalization.py::test_schema_uses_token_hash_only PASSED
tests/test_dim_h_personalization.py::test_jpcite_boot_manifest_includes_287 PASSED
tests/test_dim_h_personalization.py::test_autonomath_boot_manifest_includes_287 PASSED
tests/test_dim_h_personalization.py::test_etl_llm_zero PASSED
tests/test_dim_h_personalization.py::test_etl_no_legacy_brand PASSED
======================= 17 passed in 1.39s =======================
```

Coverage by case bundle:

1. Migration applies cleanly + idempotent re-apply.
2. Rollback drops every artefact (without touching mig 264).
3. CHECK constraints (token_hash length=64, preference_json length 2..16384, score 0..100, recommendation_type enum, last_updated_at >= created_at).
4. UNIQUE(user_token_hash) prevents duplicate profiles.
5. FK profile_id -> profile honored (PRAGMA foreign_keys = ON).
6. ETL deterministic scoring produces expected rows for active profiles.
7. ETL guard rejects empty database (no schema).
8. **PRIVACY** — schema MUST NOT contain any PII column name pattern (email/ip/houjin/name/phone) — directly grep'd from PRAGMA table_info.
9. Boot manifest registration (jpcite + autonomath mirror).
10. LLM-0 verify (zero `import anthropic` / `from anthropic` / `import openai` / `from openai` in ETL).
11. No legacy brand (`税務会計AI` / `zeimu-kaikei.ai` / `ZeimuKaikei`) in ETL source.

## Constraints satisfied

- ✅ Migration 287 is pure additive (CREATE TABLE/INDEX/VIEW IF NOT EXISTS); no UPDATE/DELETE of existing rows.
- ✅ Idempotent on every boot (Fly entrypoint.sh §4 safe).
- ✅ Both boot manifests register 287 (jpcite + autonomath mirror).
- ✅ Rollback is dev-only and only drops Dim H surface — `am_personalization_score` (mig 264) is untouched.
- ✅ **Privacy posture: ZERO PII columns** — verified by `test_schema_no_pii_columns` + `test_schema_uses_token_hash_only`.
- ✅ LLM-0 by construction — verified by `test_etl_llm_zero`.
- ✅ Brand discipline — no legacy `税務会計AI` / `zeimu-kaikei.ai` references — verified by `test_etl_no_legacy_brand`.
- ✅ ¥3/req billing posture preserved (only delivered recs trigger Stripe usage_record on the recommendation surface; this ETL only enqueues audit rows).
- ✅ Existing Wave 46 Dim H PR #125 was NOT overwritten (this is a new branch on a new mig number 287; the existing PR / migration 264 are complementary).
- ✅ No existing cron / workflow / source file was overwritten (only 2 boot manifests appended).
- ✅ Main worktree untouched (work done in `/tmp/jpcite-w47-dim-h-mig`).
- ✅ No `rm` / `mv` (banner+index style organisation per `feedback_destruction_free_organization`).
- ✅ Lane claim atomic via `mkdir /tmp/jpcite-w47-dim-h-mig.lane`.

## Post-PR

- Wire REST `GET/PUT /v1/me/personalization/profile` (customer-facing preference CRUD) — out of scope here.
- Wire REST `GET /v1/me/personalization/recommendations` (paginated served-recs read) — out of scope.
- Wire MCP tool `personalization.set_preference` / `personalization.list_recommendations` — out of scope.
- Schedule `build_personalization_recommendations.py` in `.github/workflows/personalization-recommendations-nightly.yml` — out of scope (this PR keeps the nightly cron wiring separate so the storage layer can land first).
- Wire `preference_json` jsonschema validator in `src/jpintel_mcp/personalization/validator.py` for stricter shape enforcement at write time (the SQL layer only enforces length bounds) — out of scope.
