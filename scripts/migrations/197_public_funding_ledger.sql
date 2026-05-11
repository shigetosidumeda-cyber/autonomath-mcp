-- target_db: autonomath
-- migration 197_public_funding_ledger
--
-- Public-funding event ledger (採択 / 交付決定 / 公費収入 / 落札) keyed by
-- houjin_bangou (when known) and by program_id / procurement_id. Each row is
-- one publicly-disclosed funding event with amount_yen, fund_source (METI /
-- MAFF / MHLW / local / etc.), source_document_id, and an observed_at stamp.
--
-- Why this exists:
--   turn5 §4 names public_funding_ledger as a corpus part that the artifact
--   subject_traceback / benefit_angles / procurement_public_revenue sections
--   already need. Today the same signal is scattered across jpi_adoption_
--   records / procurement_award / am_enforcement_detail.grant_refund. This
--   ledger gives one row-per-event spine that artifacts can quote.
--
-- Idempotency:
--   CREATE TABLE / INDEX IF NOT EXISTS. No seed data.
--
-- DOWN:
--   See companion `197_public_funding_ledger_rollback.sql`.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS public_funding_ledger (
    funding_event_id     TEXT PRIMARY KEY,
    event_kind           TEXT NOT NULL CHECK (event_kind IN (
                             'adoption',
                             'grant_decision',
                             'disbursement',
                             'procurement_award',
                             'subsidy_award',
                             'loan_decision',
                             'refund',
                             'other'
                         )),
    houjin_bangou        TEXT,
    program_id           TEXT,
    procurement_id       TEXT,
    fund_source          TEXT,
    issuing_authority    TEXT,
    fiscal_year          INTEGER CHECK (
                             fiscal_year IS NULL OR
                             (fiscal_year >= 1990 AND fiscal_year <= 2100)
                         ),
    amount_yen           INTEGER CHECK (amount_yen IS NULL OR amount_yen >= 0),
    currency             TEXT NOT NULL DEFAULT 'JPY' CHECK (currency = 'JPY'),
    decided_at           TEXT,
    disbursed_at         TEXT,
    bridge_id            TEXT,
    source_document_id   TEXT,
    confidence_score     REAL CHECK (
                             confidence_score IS NULL OR
                             (confidence_score >= 0.0 AND confidence_score <= 1.0)
                         ),
    known_gaps_json      TEXT NOT NULL DEFAULT '[]',
    observed_at          TEXT NOT NULL DEFAULT (datetime('now')),
    metadata_json        TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_public_funding_ledger_houjin
    ON public_funding_ledger(houjin_bangou, decided_at DESC)
    WHERE houjin_bangou IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_public_funding_ledger_program
    ON public_funding_ledger(program_id, decided_at DESC)
    WHERE program_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_public_funding_ledger_procurement
    ON public_funding_ledger(procurement_id)
    WHERE procurement_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_public_funding_ledger_kind_year
    ON public_funding_ledger(event_kind, fiscal_year);

CREATE INDEX IF NOT EXISTS idx_public_funding_ledger_authority
    ON public_funding_ledger(issuing_authority)
    WHERE issuing_authority IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_public_funding_ledger_bridge
    ON public_funding_ledger(bridge_id)
    WHERE bridge_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_public_funding_ledger_source
    ON public_funding_ledger(source_document_id)
    WHERE source_document_id IS NOT NULL;

-- Bookkeeping is recorded by entrypoint.sh §4 self-heal loop into
-- schema_migrations(id, checksum, applied_at). Do NOT INSERT here.
