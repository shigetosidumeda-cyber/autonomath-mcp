-- target_db: jpintel
-- migration 116_usage_events_client_tag_index (顧問先別 client_tag 利用明細 hot path)
--
-- Why this exists:
--   GET /v1/billing/client_tag_breakdown (60-day deliverable per
--   docs/_internal/value_maximization_plan_no_llm_api.md §28.1 + §28.7)
--   aggregates usage_events grouped by client_tag for a JST calendar
--   month window so 税理士事務所 can see a per-顧問先 breakdown of
--   ¥3/req spend.
--
--   The pre-existing partial index (migration 085, idx_usage_events_client_tag)
--   only covers WHERE client_tag IS NOT NULL — that is correct for the
--   /v1/me/usage?group_by=client_tag use case which actively skips
--   un-tagged rows. The breakdown endpoint, however, MUST surface NULL
--   client_tag rows as the "untagged" bucket (otherwise the sum across
--   all buckets does not match Stripe's invoice). For that, the planner
--   needs an index whose leftmost columns are (key_hash, ts) so the
--   period filter is sargable across BOTH tagged and un-tagged rows in
--   one scan, with client_tag as a covering tail column.
--
--   `idx_usage_key_ts` already covers (key_hash, ts) but does NOT
--   include client_tag, so a non-index-only scan must hop to the heap
--   for every row to read client_tag + quantity. With ~10k events/month
--   per active advisor that is ~10k random reads per breakdown call.
--   This migration adds a non-partial composite covering index so the
--   breakdown query stays in the index and returns in <50ms.
--
--   The new index is intentionally separate from migration 085's
--   partial index — keeping both lets the planner pick the smaller
--   partial index for /v1/me/usage?group_by=client_tag (where un-tagged
--   rows are skipped) and the full covering index here for
--   /v1/billing/client_tag_breakdown.
--
-- Schema:
--   idx_usage_events_breakdown
--     (key_hash, ts, client_tag, quantity)
--     Covering index for the breakdown aggregate. Quantity in the
--     trailing position so SUM(quantity) reads from the index alone.
--
-- Idempotency:
--   CREATE INDEX IF NOT EXISTS — re-applying on every Fly boot is safe
--   (entrypoint.sh §4 may re-run jpintel migrations).
--
-- DOWN:
--   DROP INDEX IF EXISTS idx_usage_events_breakdown;
--   No data implications (covering index, not a uniqueness constraint).

PRAGMA foreign_keys = ON;

CREATE INDEX IF NOT EXISTS idx_usage_events_breakdown
    ON usage_events(key_hash, ts, client_tag, quantity);

-- Bookkeeping is recorded by scripts/migrate.py into schema_migrations(id, checksum, applied_at).
-- Do NOT INSERT here.
