-- target_db: autonomath
-- migration wave24_113c_autonomath_houjin_master_jsic
--
-- Why this exists:
--   wave24_113a added jsic_* columns to jpintel.db `houjin_master`. Post
--   V4 absorption (2026-04-25), an `houjin_master` table also lives in
--   autonomath.db. W3-7 finding: `run_houjin_360_narrative_batch.py`
--   and `run_invoice_buyer_seller_batch.py` SELECT
--   `autonomath.houjin_master.jsic_major` directly — without this
--   ALTER, those batches throw `no such column: jsic_major` against
--   the autonomath DB and the Wave 24 second_half tools that depend
--   on the precomputed narrative cache silently degrade.
--
--   Same 5 columns and same hot-path index as 113a, scoped to
--   autonomath.db so entrypoint.sh §4 picks this up automatically
--   (target_db: autonomath line 1).
--
-- Schema additions (ALTER):
--   * houjin_master.jsic_major          TEXT
--   * houjin_master.jsic_middle         TEXT
--   * houjin_master.jsic_minor          TEXT
--   * houjin_master.jsic_assigned_method TEXT
--   * houjin_master.jsic_assigned_at    TEXT
--
-- Note (intentional divergence from 113a):
--   No CHECK constraints on this autonomath copy. The autonomath
--   `houjin_master` is fed by both V4 ingest and gbiz absorption,
--   which historically carry rows with non-canonical industry coding
--   (e.g. JSIC majors not yet in A-T scope, middle/minor codes from
--   legacy 4-digit sources). Adding CHECKs here would block the next
--   bulk INSERT path; keep validation at the application layer.
--
-- Idempotency:
--   ALTER TABLE ADD COLUMN raises "duplicate column name" on re-run.
--   entrypoint.sh §4 swallows that case (lines 420-428) when the
--   message is exclusively "duplicate column". CREATE INDEX uses
--   IF NOT EXISTS. Safe to re-run on every Fly boot.
--
-- DOWN:
--   See companion `wave24_113c_autonomath_houjin_master_jsic_rollback.sql`.

PRAGMA foreign_keys = ON;

ALTER TABLE houjin_master ADD COLUMN jsic_major TEXT;
ALTER TABLE houjin_master ADD COLUMN jsic_middle TEXT;
ALTER TABLE houjin_master ADD COLUMN jsic_minor TEXT;
ALTER TABLE houjin_master ADD COLUMN jsic_assigned_method TEXT;
ALTER TABLE houjin_master ADD COLUMN jsic_assigned_at TEXT;

CREATE INDEX IF NOT EXISTS idx_houjin_master_jsic_major
    ON houjin_master(jsic_major) WHERE jsic_major IS NOT NULL;
