-- target_db: jpintel
-- migration 119_audit_seal_seal_id_columns
--
-- Why this exists:
--   The §17.D plan (docs/_internal/llm_resilient_business_plan_2026-04-30.md
--   Section 17 step 5 + Section 18 row "audit seal") specifies an envelope
--   shape for paid-response audit seals:
--
--     "audit_seal": {
--       "seal_id": "seal_<uuid>",
--       "issued_at": "...",
--       "subject_hash": "sha256:<hex>",
--       "key_hash_prefix": "ABCD-1234 (first 8 chars only)",
--       "corpus_snapshot_id": "corpus-2026-04-30",
--       "verify_endpoint": "/v1/audit/seals/{seal_id}",
--       ...
--     }
--
--   The legacy ``audit_seals`` schema (migration 089) was keyed on
--   ``call_id`` (ULID-26 char) and lacked ``seal_id`` /
--   ``corpus_snapshot_id`` columns. The verify endpoint at
--   ``GET /v1/audit/seals/{seal_id}`` needs to look up by ``seal_id``,
--   so we add the column + a lookup index here.
--
--   Forward-only / idempotent: ALTER TABLE ADD COLUMN raises a
--   "duplicate column name" error on re-run which the entrypoint loop
--   swallows (same pattern as migration 049 / 101). The CREATE INDEX
--   uses IF NOT EXISTS.
--
--   No DROP — audit seals are statutory evidence (7-year retention per
--   税理士法 §41 / 法人税法 §150-2). Existing rows without ``seal_id``
--   are pre-§17.D — they remain queryable via the legacy ``call_id``
--   path (the verify endpoint accepts both formats with a leading-prefix
--   match — ``seal_*`` vs the legacy ULID).

PRAGMA foreign_keys = ON;

-- New §17.D customer-facing seal id. Format: ``seal_<32-hex>``. Distinct
-- from the legacy ``call_id`` (ULID-26) so the customer envelope and the
-- HMAC-binding identifier are independently rotatable.
ALTER TABLE audit_seals ADD COLUMN seal_id TEXT;

-- ``corpus-YYYY-MM-DD`` JST date label of MAX(am_source.last_verified)
-- at issue time. Cached process-locally and refreshed every 6 hours
-- (api/_audit_seal.py:get_corpus_snapshot_id). Persisting it onto the
-- row means re-verification can still surface the snapshot label even
-- if the corpus has rolled forward by then.
ALTER TABLE audit_seals ADD COLUMN corpus_snapshot_id TEXT;

-- Verify-endpoint hot path: ``GET /v1/audit/seals/{seal_id}``. Single-row
-- lookup, so a non-unique index suffices (a future UNIQUE upgrade can
-- come once the column has been backfilled across all rows).
CREATE INDEX IF NOT EXISTS idx_audit_seals_seal_id
    ON audit_seals(seal_id)
    WHERE seal_id IS NOT NULL;

-- Bookkeeping is recorded by scripts/migrate.py into schema_migrations.
