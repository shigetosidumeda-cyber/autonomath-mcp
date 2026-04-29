-- target_db: jpintel
-- migration 086_api_keys_parent_child (Sub-API-key parent/child fan-out)
--
-- Why this exists:
--   SaaS partners wiring AutonoMath as a back-end for their own customer
--   base (e.g. 1,000 small-business accounting tools) need to issue a
--   distinct api_keys row per downstream tenant for revocation isolation,
--   debug separation, and per-tenant usage telemetry — without paying for
--   a separate Stripe subscription per tenant.
--
--   The parent/child model:
--     * parent api_keys row carries the Stripe `stripe_subscription_id`
--       and `monthly_cap_yen`. ONE Stripe subscription, ONE Price
--       (`autonomath/per_request_v3`).
--     * Each child api_keys row points at the parent via `parent_key_id`,
--       carries a free-text `label` (≤64 chars) for human disambiguation
--       (`prod`, `staging`, `customer_a`), inherits the parent's `tier`
--       and `monthly_cap_yen` semantically (cap is ENFORCED at parent
--       scope: see deps._enforce_quota for the aggregation across the
--       sibling tree), and uses the SAME `stripe_subscription_id` so
--       Stripe billing aggregates to the parent.
--     * Stripe sees ONE customer + ONE subscription. Children are
--       INVISIBLE to Stripe — `report_usage_async` reports against the
--       parent's subscription regardless of which child key billed it.
--
-- Schema:
--   parent_key_id INTEGER REFERENCES api_keys(id)
--     NULL for parent keys (the 99% case). Non-NULL on child keys —
--     points at the rowid of the parent api_keys row. Note: api_keys.id
--     is NOT the existing PRIMARY KEY (which is `key_hash` TEXT). We
--     reference SQLite's implicit `rowid` exposed as the column `id`.
--     For tables with a TEXT primary key, `rowid` is still available;
--     we add an explicit `id INTEGER` column that mirrors rowid for
--     foreign-key clarity.
--   label TEXT
--     Free-text human-readable identifier for the child key. Max 64
--     chars (validated server-side at issuance, not in SQL — SQLite
--     does not enforce length CHECK reliably across versions). NULL on
--     parent keys; required (non-empty) on child keys at issuance time.
--
-- Constraints (server-side, NOT in SQL):
--   * One parent key may have at most 1,000 children (anti-abuse).
--     Enforced in billing.keys.issue_child_key().
--   * Child keys cannot themselves spawn grandchildren. Enforced by
--     refusing to issue a child whose parent already has parent_key_id
--     non-NULL.
--   * Child keys carry the parent's tier and stripe_subscription_id
--     verbatim at issuance (same Stripe subscription, same Price).
--
-- Idempotency:
--   ALTER TABLE ADD COLUMN is a no-op on the second run. CREATE INDEX
--   uses IF NOT EXISTS. Re-applying this migration on every Fly boot
--   is safe.
--
-- DOWN:
--   SQLite < 3.35 cannot DROP COLUMN. Nullable columns + unindexed
--   on the parent path means leaving them on rollback is harmless.

-- IMPORTANT: do NOT enable PRAGMA foreign_keys in this script. SQLite
-- evaluates `REFERENCES api_keys(id)` against the parent column's
-- uniqueness *at ALTER TABLE time*. Because we cannot add an INTEGER
-- PRIMARY KEY via ALTER TABLE, we instead create a UNIQUE INDEX on `id`
-- BEFORE adding the FK column — that satisfies SQLite's "referenced
-- column must be PRIMARY KEY or UNIQUE" rule. The FK is enforced on the
-- live connection (which sets `PRAGMA foreign_keys=ON` at deps.py).

-- Add an explicit `id INTEGER` column that mirrors SQLite's implicit
-- rowid for parent-child FK clarity. We populate it via a trigger-free
-- approach: the trigger semantics in idempotent migrations are fragile,
-- so we set the value explicitly at issuance time using last_insert_rowid().
-- For existing rows this column will be NULL until the next rotation;
-- the parent_key_id column we add below references rowid via SQLite's
-- "INTEGER PRIMARY KEY" alias semantics, which means a SELECT on rowid
-- still works on legacy rows.
--
-- Note: SQLite does not allow adding a NOT NULL column without a default,
-- and INTEGER PRIMARY KEY can only be specified at table-creation time.
-- Practical posture: `id` is nullable here; the issue_child_key code path
-- writes `last_insert_rowid()` into it on every new parent / child INSERT.

ALTER TABLE api_keys ADD COLUMN id INTEGER;

-- Backfill the `id` column for existing rows so the parent->child FK
-- has a referent. SQLite exposes rowid implicitly; this UPDATE is
-- idempotent (subsequent runs are no-op for rows that already have
-- id = rowid). MUST run BEFORE the UNIQUE index below — otherwise
-- the index would be built over a NULL column on legacy rows (NULL
-- is not unique-distinct in SQLite, so this is fine, but ordering
-- avoids any future audit confusion).
UPDATE api_keys SET id = rowid WHERE id IS NULL;

-- UNIQUE index on `id` is required so the next ALTER TABLE's FOREIGN KEY
-- clause resolves. Without this SQLite emits
-- "foreign key mismatch — api_keys referencing api_keys" because `id` is
-- a regular INTEGER column (the table's PK is `key_hash` TEXT).
--
-- IMPORTANT: SQLite only accepts a NON-partial UNIQUE INDEX as a FK
-- referent. The original migration used `WHERE id IS NOT NULL`, which
-- is a partial index and SQLite rejects it at the first INSERT.
-- A non-partial UNIQUE INDEX is still safe with NULL legacy rows
-- because SQLite treats every NULL as distinct under UNIQUE.
CREATE UNIQUE INDEX IF NOT EXISTS uniq_api_keys_id
    ON api_keys(id);

ALTER TABLE api_keys ADD COLUMN parent_key_id INTEGER REFERENCES api_keys(id);
ALTER TABLE api_keys ADD COLUMN label TEXT;

-- Index for "list children of parent X" — both for /v1/me/keys/children
-- and for the deps._enforce_quota aggregation across siblings.
-- Partial index on parent_key_id IS NOT NULL keeps the footprint trivial
-- (parent rows skipped).
CREATE INDEX IF NOT EXISTS idx_api_keys_parent_key_id
    ON api_keys(parent_key_id)
    WHERE parent_key_id IS NOT NULL;

-- Bookkeeping is recorded by scripts/migrate.py into schema_migrations(id, checksum, applied_at).
-- Do NOT INSERT here.
