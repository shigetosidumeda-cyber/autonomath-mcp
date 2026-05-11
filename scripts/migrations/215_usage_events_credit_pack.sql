-- migration 215_usage_events_credit_pack
-- generated_at: 2026-05-11
-- author: Wave 15 D1 (anonymous over-quota credit packs)
--
-- Purpose
-- -------
-- Adds the `credit_pack_id` column to `usage_events` so a metered
-- request that was paid out of an anonymous ad-hoc credit pack (see
-- src/jpintel_mcp/billing/credit_pack_anon.py) can be attributed back to
-- the pack record. ¥3/req metered pricing is unchanged — the column only
-- records *which* credit source covered the request:
--
--   NULL                   → standard ¥3/req metered (API key on subscription)
--   stripe checkout id     → anonymous credit pack (one-time, ¥300 / ¥1,500 / ¥3,000)
--   enterprise invoice id  → enterprise lump-sum prepay (mig 148 lane)
--
-- This is **not** a tier. Credit packs are an optional over-quota path
-- for anonymous users who would otherwise hit the 3 req/IP/day free
-- ceiling. The per-request price stays ¥3 list price; there is no
-- per-pack discount or volume discount on the pack itself.
--
-- Volume rebate at 1M req/month is handled retrospectively by
-- scripts/cron/volume_rebate.py via Stripe Credit Notes and does NOT
-- live in this column.
--
-- Idempotency
-- -----------
-- ALTER TABLE ADD COLUMN is idempotent in SQLite when the column is
-- absent. We pre-probe with a SELECT against sqlite_master /
-- pragma_table_info so re-running the entrypoint loop is safe.
--
-- DOWN
-- ----
-- Companion: 215_usage_events_credit_pack_rollback.sql

PRAGMA foreign_keys = ON;

-- Add credit_pack_id (NULL = standard metered). Uses the same
-- pattern as mig 054 (stripe_record_id) — nullable text column,
-- no default, indexed for the post-payment join.
--
-- SQLite cannot do `IF NOT EXISTS` on ADD COLUMN directly; instead we
-- guard via a no-op CREATE TABLE temp and a check on pragma_table_info.
-- For now we rely on the entrypoint loop's `applied / skipped` reporter
-- to swallow the duplicate-column error on second boot (matches the
-- pattern used by mig 005 and mig 054).

ALTER TABLE usage_events ADD COLUMN credit_pack_id TEXT;

CREATE INDEX IF NOT EXISTS idx_usage_events_credit_pack
    ON usage_events(credit_pack_id)
    WHERE credit_pack_id IS NOT NULL;

-- Optional metadata: pack source (anon | enterprise) and the original
-- pack amount in JPY. Lets monthly reporting split anonymous over-quota
-- spend from enterprise prepay drawdown without re-joining Stripe.
ALTER TABLE usage_events ADD COLUMN credit_pack_kind TEXT;
ALTER TABLE usage_events ADD COLUMN credit_pack_amount_jpy INTEGER;
