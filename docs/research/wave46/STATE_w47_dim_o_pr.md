# STATE — Wave 47 Dim O explainable_fact migration PR

Generated 2026-05-12, lane `/tmp/jpcite-w47-dim-o-mig.lane`, worktree
`/tmp/jpcite-w47-dim-o-mig`, branch
`feat/jpcite_2026_05_12_wave47_dim_o_migration` (off `origin/main`
@ `7f4ceb9f4`).

## Scope

Closes the Dim O (`feedback_explainable_fact_design`) substrate gap:
every fact gets a 4-axis explainability metadata tuple
(`source_doc` / `extracted_at` / `verified_by` / confidence band) +
an append-only Ed25519 attestation chain, sitting alongside (NOT
replacing) the byte-tamper Ed25519 signature from Wave 43.2.5
migration 262.

## Deliverables

| Path | LOC | Purpose |
| --- | --- | --- |
| `scripts/migrations/275_explainable_fact.sql` | 193 | `am_fact_metadata` + `am_fact_attestation_log` + 2 helper views |
| `scripts/migrations/275_explainable_fact_rollback.sql` | 30 | Idempotent rollback |
| `scripts/etl/build_explainable_fact_metadata.py` | 351 | Daily ETL: enrich + sign + append attestation |
| `tests/test_dim_o_explainable_fact.py` | 487 | 15 tests (migration / CHECK / sign-verify / tamper / idempotent / boot manifest) |
| `scripts/migrations/jpcite_boot_manifest.txt` | +11 | Registers `275_explainable_fact.sql` |
| `scripts/migrations/autonomath_boot_manifest.txt` | +11 | Registers `275_explainable_fact.sql` |

Total approx 1,083 LOC across migration (193) + rollback (30) + ETL
(351) + tests (487) + manifests (22). Migration body itself
(stripping ~140 lines of header comments) is approximately **50
LOC of SQL DDL** as the task brief targeted.

## Schema highlights (migration 275)

- `am_fact_metadata`
  - `fact_id TEXT PRIMARY KEY`
  - `source_doc TEXT` (nullable)
  - `extracted_at TEXT NOT NULL` (UTC ISO-8601, default now)
  - `verified_by TEXT` (nullable, extractor pipeline identifier)
  - `confidence_lower REAL` / `confidence_upper REAL` with CHECK
    constraints: each in `[0.0, 1.0]`, `lower <= upper`
  - `ed25519_sig BLOB NOT NULL` (64-96 bytes, signs the 4-axis tuple
    independently of `am_fact_signature.ed25519_sig`)
- `am_fact_attestation_log`
  - `attestation_id INTEGER PRIMARY KEY AUTOINCREMENT`
  - `fact_id TEXT NOT NULL`, `attester TEXT NOT NULL`,
    `signed_at TEXT NOT NULL` (now default), `signature_hex TEXT NOT NULL`
    (128-256 hex chars CHECK)
- Views: `v_am_fact_attestation_latest`, `v_am_fact_explainability`
- Indexes: `(extracted_at DESC)`, `(verified_by)`, `(source_doc)`,
  `(fact_id, signed_at DESC)`, `(attester)`

## Hard constraint verification

- **Migration is idempotent**: `IF NOT EXISTS` on all CREATE; 2nd
  apply is a no-op (`test_migration_275_idempotent` PASS).
- **`am_fact_signature` NEVER mutated**: ETL is read-only against
  migration 262 (`test_etl_never_touches_am_fact_signature` PASS).
- **Append-only attestation log**: changes APPEND new rows; same
  metadata = zero log writes (`test_attestation_log_appends_on_change`
  + `test_etl_idempotent_on_unchanged` PASS).
- **Ed25519 sign/verify roundtrip + tamper**: honest verify accepts
  signature; tampered payload raises `InvalidSignature`
  (`test_ed25519_sign_verify_roundtrip` PASS).
- **CHECK constraints**: confidence band order + unit interval +
  64-byte sig minimum all enforced
  (`test_confidence_band_check_lower_le_upper` /
  `test_confidence_band_check_in_unit_interval` /
  `test_sig_size_check_min` all PASS).
- **No LLM SDK in ETL**: regex grep for `anthropic` / `openai` /
  `google.generativeai` / `claude_agent_sdk`
  (`test_etl_no_llm_imports` PASS).
- **No legacy brand**: `税務会計AI` / `zeimu-kaikei.ai` absent in
  ETL (`test_etl_no_legacy_brand_in_user_facing` PASS).
- **Boot manifest registration**: both `autonomath_boot_manifest.txt`
  and `jpcite_boot_manifest.txt` carry the migration filename
  (`test_boot_manifest_*` PASS).

## pytest result

```
============================== 15 passed in 1.07s ==============================
```

## Forbidden surfaces

- No modification to `am_fact_signature` (migration 262 untouched).
- No Ed25519 private key committed (sign key resolved from Fly
  secret `AUTONOMATH_FACT_SIGN_PRIVATE_KEY` only).
- No work on the `main` worktree (worktree at `/tmp/jpcite-w47-dim-o-mig`).
- No `rm` / `mv` operations.
- No legacy brand (`AutonoMath` / `税務会計AI` / `zeimu-kaikei.ai`)
  in user-facing copy.
- No LLM API call (production constraint `feedback_autonomath_no_api_use`
  + `feedback_no_operator_llm_api`).

## PR

- **PR**: #163 — https://github.com/shigetosidumeda-cyber/autonomath-mcp/pull/163
- **branch**: `feat/jpcite_2026_05_12_wave47_dim_o_migration`
- **base**: `main` @ `7f4ceb9f4`
- **commit**: `38a309d2d` (single commit, no fixups)

## Migration LOC summary

- SQL DDL (pure body, comments stripped): ~50 LOC
- SQL file w/ header comments: 193 LOC
- ETL: 351 LOC
- test: 487 LOC
- **Total migration scope (mig + rollback + ETL + test): approximately 1,061 LOC**

Pure migration body matches the ~50 LOC target in the task brief.
