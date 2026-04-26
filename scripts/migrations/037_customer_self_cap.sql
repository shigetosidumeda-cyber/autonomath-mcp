-- 037_customer_self_cap.sql
-- Customer-controlled monthly spend cap on a `paid` API key.
--
-- Business context (analysis_wave18 P3-W / dd_v8_09):
--   * AutonoMath is pure metered ¥3/req 税別 — no tier SKUs, no bulk discounts
--     (memory: project_autonomath_business_model). The unit price is
--     **immutable** and this column does NOT change it.
--   * Some customers explicitly want predictability ("never charge me more
--     than ¥5,000 in a single calendar month"). Without a self-serve cap
--     they have to revoke the key by hand on the dashboard, which is exactly
--     the kind of toil zero-touch ops promised to eliminate.
--   * `monthly_cap_yen IS NULL` -> unlimited (default; preserves the
--     historical behaviour of every existing api_keys row).
--   * `monthly_cap_yen IS NOT NULL` -> middleware short-circuits the
--     request with 503 + `cap_reached: true` once month-to-date spend
--     reaches the cap. Stripe usage is **not** recorded for the rejected
--     request, so the cap is hard (not best-effort).
--
-- Why an INTEGER, not an INTEGER + currency code:
--   AutonoMath bills exclusively in JPY (Bookyou株式会社 T8010001213708 is a
--   domestic invoicer). Adding a currency column would imply we plan to
--   bill in USD/EUR, which we explicitly do not.
--
-- Why NOT a separate `customer_caps` table:
--   The cap is 1:1 with an api_keys row and is read on every authenticated
--   request. Putting it on the same row keeps the hot-path read to a single
--   PK lookup that already happens in require_key().
--
-- Idempotency: ALTER TABLE ADD COLUMN is a no-op on the second run (the
-- migrate runner records the duplicate-column error and proceeds). Re-applying
-- this migration is safe.

PRAGMA foreign_keys = ON;

-- Add the cap column. NULL == unlimited (the inherited default).
ALTER TABLE api_keys ADD COLUMN monthly_cap_yen INTEGER;

-- Bookkeeping is recorded by scripts/migrate.py into schema_migrations(id, checksum, applied_at).
-- Do NOT INSERT here.
