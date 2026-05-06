-- target_db: autonomath
-- migration wave24_148_am_credit_pack_purchase
--
-- Stripe credit pack prepay (¥300K / ¥1M / ¥3M one-time top-up). Customer pays
-- a lump sum, Stripe applies it as a negative customer_balance, subsequent
-- ¥3/req metered usage is consumed from the balance. Tier-less — built so
-- enterprise procurement signs ONE 稟議 instead of N invoices/month.
--
-- Idempotent (CREATE TABLE / INDEX IF NOT EXISTS). Safe to re-run on every
-- Fly boot via entrypoint.sh §4.
--
-- Schema notes
-- ------------
-- * `amount_jpy` CHECK enforces the three published packs (no arbitrary
--   amounts via API forgery / typo). New tier amounts require a migration
--   update + product copy refresh in lockstep.
-- * `stripe_invoice_id` UNIQUE prevents double-recording the same Stripe
--   Invoice (webhook redelivery + retry safety).
-- * `stripe_balance_txn_id` is filled when the webhook applies the
--   balance adjustment; stays NULL while invoice is `pending`.
-- * `status` is the local lifecycle: `pending` (invoice created, awaiting
--   payment) → `paid` (webhook applied balance) → `expired` (operator
--   manual close) / `refunded` (operator manual; ¥0 expected per §19の4
--   non-refundable policy).
-- * `customer_id` index supports balance-history listing per customer.

CREATE TABLE IF NOT EXISTS am_credit_pack_purchase (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id TEXT NOT NULL,
    amount_jpy INTEGER NOT NULL CHECK (amount_jpy IN (300000, 1000000, 3000000)),
    stripe_invoice_id TEXT UNIQUE,
    stripe_balance_txn_id TEXT,
    status TEXT NOT NULL CHECK (status IN ('pending','paid','expired','refunded')),
    created_at TEXT DEFAULT (datetime('now')),
    paid_at TEXT
);

CREATE INDEX IF NOT EXISTS ix_credit_pack_customer
    ON am_credit_pack_purchase(customer_id);
