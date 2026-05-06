-- target_db: jpintel
-- migration wave24_166_credit_pack_reservation
--
-- Purpose
-- -------
-- Strict idempotency reservation row for Stripe credit-pack grants.
--
-- The legacy guard in `am_credit_pack_purchase` (migration wave24_148, target_db
-- autonomath) protects against re-grant of the SAME `stripe_invoice_id` ONLY
-- after the row has already been marked `status='paid'`. Three race windows
-- still allowed double-grant before this migration:
--
--   1. Two webhook deliveries arriving within milliseconds (Stripe at-least-once
--      semantics + Stripe's own retry on 5xx). The legacy SELECT-then-INSERT
--      pattern in `api/billing.py:1306-1352` is NOT atomic — both deliveries
--      can read `row.status='pending'`, both call `apply_credit_pack`, and the
--      Stripe `Customer.create_balance_transaction` API is itself NOT idempotent
--      so the customer ends up with -2x the intended balance. M00-D §8.16 P0.
--
--   2. A retried webhook where the first attempt hard-crashed AFTER calling
--      `apply_credit_pack` but BEFORE writing `status='paid'` (e.g. SIGTERM in
--      the Fly release between the Stripe call and the local INSERT). On retry
--      the legacy guard sees `status='pending'` (or no row at all if the first
--      attempt never reached the local INSERT) and re-applies the balance.
--
--   3. Operator-initiated replay (e.g. Stripe CLI `stripe trigger invoice.paid`
--      against a recovered DB) where the operator does not know the invoice was
--      already settled.
--
-- Required design (per DD-04 spec)
-- --------------------------------
-- A pre-grant `INSERT OR IGNORE` into a dedicated reservation table on the
-- idempotency key `f"credit_pack:{stripe_invoice_id}"` (or
-- `f"credit_pack:{payment_intent_id}"` when the routed event carries
-- `payment_intent` instead of `invoice`). The PRIMARY KEY constraint is what
-- serializes — SQLite's writer lock plus the unique key make the INSERT itself
-- the dedup point, with no SELECT-then-INSERT race window.
--
--   INSERT INTO credit_pack_reservation
--     (idempotency_key, customer_id, pack_size, status, reserved_at)
--   VALUES (?, ?, ?, 'reserved', datetime('now'))
--   ON CONFLICT(idempotency_key) DO NOTHING;
--
--   -- If rowcount==0 the key was already taken. Re-read status:
--   --   reserved   → another concurrent worker is mid-flight; return 200 idem
--   --   granted    → already applied; return 200 idem (no double grant)
--   --   failed     → first attempt errored after reservation; safe to retry
--
-- Post-grant (only the worker that successfully reserved the row reaches here):
--   UPDATE credit_pack_reservation
--     SET status='granted', granted_at=datetime('now'), stripe_balance_txn_id=?
--     WHERE idempotency_key=? AND status='reserved';
--
-- On grant failure (Stripe API raises, network blip, etc):
--   UPDATE credit_pack_reservation
--     SET status='failed', error_reason=?
--     WHERE idempotency_key=? AND status='reserved';
--
-- The local reservation is committed before the Stripe call. The same
-- idempotency key is then passed to Stripe, so a retry after a process crash can
-- reuse the same Stripe result instead of creating a second balance
-- transaction. Rows stuck in `reserved` longer than the safe retry window are
-- left for operator reconciliation before any new Stripe call is made.
--
-- target_db: jpintel
-- ------------------
-- This file's first line is `-- target_db: jpintel` so it is NOT picked up by
-- entrypoint.sh §4 (which only globs autonomath-target migrations). The
-- existing `scripts/migrate.py` pipeline does NOT filter by target_db either,
-- but the Fly `release_command` is intentionally commented out (per CLAUDE.md
-- "Common gotchas") because migrate.py would corrupt autonomath.db. As a
-- result this jpintel-target migration is applied via ONE of the two
-- documented paths:
--
--   (a) Operator runs manually after deploy:
--         sqlite3 data/jpintel.db < scripts/migrations/wave24_166_credit_pack_reservation.sql
--
--   (b) The CI/local migrate.py invocation:
--         .venv/bin/python scripts/migrate.py
--       (works because migrate.py operates on jpintel.db by default and the
--       schema_guard rejects only autonomath-default-table creates)
--
-- The migration is idempotent (`CREATE TABLE IF NOT EXISTS` +
-- `CREATE INDEX IF NOT EXISTS`) so re-running on a DB that already has the
-- table is a no-op.
--
-- Schema notes
-- ------------
-- * `idempotency_key` is the PRIMARY KEY — INSERT-on-existing returns the
--   existing row's status; the application layer dispatches on that status.
--   Format: `credit_pack:{stripe_invoice_id}` (preferred, present on
--   invoice.paid events) or `credit_pack:{payment_intent_id}` (used when the
--   routed event is a PaymentIntent instead of an Invoice). The credit_pack:
--   prefix prevents collision with other future idempotency consumers in the
--   same table.
-- * `status` CHECK enforces the three-state machine: reserved → granted (happy
--   path) or reserved → failed (Stripe call raised). Operator-side cleanup
--   may also UPDATE failed → reserved to allow the next retry to upgrade.
-- * `pack_size` mirrors the published 300K / 1M / 3M tiers. Stored as INTEGER
--   so the value can be read back by the webhook's amount-derivation path
--   without re-parsing metadata.
-- * `customer_id` indexed alongside `status` so the operator dashboard can
--   scan "all granted packs for cus_*" without a table scan.
-- * `error_reason` carries a short human-readable string when status='failed'
--   (Stripe SDK exception class + first 200 chars of message). NULL otherwise.
-- * `reserved_at` / `granted_at` are ISO-8601 strings (datetime('now'),
--   matches the rest of the schema).
-- * `stripe_balance_txn_id` stores the Stripe customer-balance transaction id
--   once known so webhook redelivery can repair `am_credit_pack_purchase`
--   without another Stripe mutation.
--
-- Idempotency
-- -----------
-- CREATE TABLE IF NOT EXISTS + CREATE INDEX IF NOT EXISTS — re-running on a
-- DB where the table already exists is a no-op. No ALTER TABLE clauses (those
-- would be rejected on re-run).

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS credit_pack_reservation (
    idempotency_key TEXT PRIMARY KEY,
    customer_id     TEXT NOT NULL,
    pack_size       INTEGER NOT NULL CHECK (pack_size IN (300000, 1000000, 3000000)),
    status          TEXT NOT NULL CHECK (status IN ('reserved', 'granted', 'failed')),
    reserved_at     TEXT NOT NULL DEFAULT (datetime('now')),
    granted_at      TEXT,
    stripe_balance_txn_id TEXT,
    error_reason    TEXT
);

-- Operator-side scan: "list all granted packs for customer X" / "find any
-- failed reservations awaiting triage". The (customer_id, status) compound
-- index covers both query shapes without a table scan.
CREATE INDEX IF NOT EXISTS idx_credit_pack_reservation_customer_status
    ON credit_pack_reservation(customer_id, status);

-- Operator-side scan: "find stale reserved rows older than 1h" — a reservation
-- row stuck in 'reserved' for >1h almost certainly indicates the worker
-- crashed between INSERT and grant. Cron sweeper checks this index.
CREATE INDEX IF NOT EXISTS idx_credit_pack_reservation_status_reserved_at
    ON credit_pack_reservation(status, reserved_at)
    WHERE status = 'reserved';
