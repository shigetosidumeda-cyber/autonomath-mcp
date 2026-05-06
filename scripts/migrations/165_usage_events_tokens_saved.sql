-- target_db: jpintel
-- migration 165_usage_events_tokens_saved (customer dashboard "tokens saved" metric)
--
-- Why this exists:
--   Customer dashboards need a hard number to justify the ¥3/req spend:
--   "how many LLM tokens would I have burned answering this question
--   from a closed-book frontier model vs the citation jpcite returned?"
--
--   Per-call estimate is computed by `_estimate_tokens_saved` in
--   `api/usage.py` (LLM 0, char_count / 2.5 heuristic) and persisted by
--   the deferred `_record_usage_async` writer alongside latency_ms /
--   result_count. The /v1/usage envelope rolls up MTD per key_hash so
--   the dashboard can render a single "累計 token saved" headline
--   plus a per-call mean.
--
-- Schema:
--   tokens_saved_estimated INTEGER
--     Per-call delta (closed_book_baseline - jpcite_response_tokens).
--     NULL for pre-migration rows AND for endpoints that pass NULL
--     (cron jobs that have no question/response substrate). Always
--     non-negative when written; the helper clamps at 0 so a degenerate
--     short-question / long-response edge cannot turn the rollup
--     negative and confuse customers.
--
-- Idempotency:
--   ALTER TABLE ADD COLUMN is a no-op on the second run; the migrate.py
--   duplicate_column_skipping fallback also catches the legacy path. Re-
--   applying on every Fly boot is safe — entrypoint.sh §4 only auto-
--   applies autonomath-target migrations, but the human-run jpintel
--   release path also tolerates re-runs.
--
-- DOWN:
--   SQLite < 3.35 cannot DROP COLUMN. Leaving the column in place on
--   rollback is harmless because it is nullable and only read by the
--   /v1/usage rollup which falls back to 0 on NULL.

PRAGMA foreign_keys = ON;

ALTER TABLE usage_events ADD COLUMN tokens_saved_estimated INTEGER;

-- Bookkeeping is recorded by scripts/migrate.py into schema_migrations(id, checksum, applied_at).
-- Do NOT INSERT here.
