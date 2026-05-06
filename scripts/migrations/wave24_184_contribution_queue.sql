-- target_db: autonomath
-- migration: wave24_184_contribution_queue
-- generated_at: 2026-05-07
-- author: DEEP-28 customer-contributed eligibility corpus + DEEP-31 form
-- idempotent: every CREATE uses IF NOT EXISTS; first-line target_db hint
--             routes this file to autonomath.db via entrypoint.sh §4.
--
-- Purpose
-- -------
-- Spec: tools/offline/_inbox/value_growth_dual/_deep_plan/DEEP_28_customer_contribution.md
--       tools/offline/_inbox/value_growth_dual/_deep_plan/DEEP_31_contribution_form_static.md
--
-- DEEP-28 community-verified eligibility observation queue. Stores
-- pre-review submissions from `POST /v1/contribute/eligibility_observation`
-- (税理士 / 公認会計士 / 司法書士 / 補助金 consultant / anonymous).
-- Operator review (`tools/offline/operator_review/review_contribution_queue.py`)
-- promotes approved rows into `am_amount_condition` with
-- `quality_flag='community_verified'`.
--
-- Field semantics
-- ---------------
-- id                          INTEGER PK AUTOINCREMENT.
-- contributor_api_key_id      Optional jpintel.db api_keys.id (cross-file FK
--                             cannot be enforced; declared INTEGER NULL).
--                             NULL = anonymous submission.
-- program_id                  programs.unified_id (autonomath programs mirror).
-- observed_year               1-year granularity, [2015, current_year].
-- observed_eligibility_text   50-2000 chars post client+server PII scrub.
-- observed_amount_yen         Optional integer; NULL allowed.
-- observed_outcome            CHECK in {'採択','不採択','継続中'}.
-- houjin_bangou_hash          Hex SHA-256 produced client-side; per APPI
--                             fence the server NEVER computes this hash.
--                             Pattern ^[a-f0-9]{64}$.
-- source_urls                 JSON array (>=1 entry, allowlist-checked
--                             server-side, aggregator banlist rejected).
-- tax_pro_credit_name         Optional opt-in credit string (requires
--                             public_credit_consent on the request body).
-- status                      CHECK in {'pending','approved','rejected'};
--                             DEEP-28 §4 also reserves 'superseded_pointer'
--                             for promotion lineage but the form-side queue
--                             only writes 'pending' on submit; reviewer
--                             writes 'approved' / 'rejected'.
-- reviewer_notes              Free-text reviewer rationale.
-- submitted_at                ISO 8601 UTC server-clock at insert.
-- reviewed_at                 ISO 8601 UTC server-clock at review write.
--
-- Indexes:
--   * (status, program_id)             — review queue hot path.
--   * (submitted_at)                   — chronological inbox sort.
--   * (houjin_bangou_hash)             — dedup probe per houjin.
--   * (contributor_api_key_id)         — per-contributor history rollup.

PRAGMA foreign_keys = ON;

-- ============================================================================
-- contribution_queue -- one row per submitted eligibility observation
-- ============================================================================

CREATE TABLE IF NOT EXISTS contribution_queue (
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    contributor_api_key_id      INTEGER,
    program_id                  TEXT NOT NULL,
    observed_year               INTEGER NOT NULL
                                CHECK (observed_year >= 2015
                                       AND observed_year <= 2099),
    observed_eligibility_text   TEXT NOT NULL
                                CHECK (length(observed_eligibility_text) >= 50
                                       AND length(observed_eligibility_text) <= 2000),
    observed_amount_yen         INTEGER
                                CHECK (observed_amount_yen IS NULL
                                       OR observed_amount_yen >= 0),
    observed_outcome            TEXT NOT NULL CHECK (observed_outcome IN (
        '採択',
        '不採択',
        '継続中'
    )),
    houjin_bangou_hash          TEXT NOT NULL
                                CHECK (length(houjin_bangou_hash) = 64),
    source_urls                 TEXT NOT NULL,
    tax_pro_credit_name         TEXT,
    status                      TEXT NOT NULL DEFAULT 'pending'
                                CHECK (status IN (
                                    'pending',
                                    'approved',
                                    'rejected',
                                    'superseded_pointer'
                                )),
    reviewer_notes              TEXT,
    submitted_at                TEXT NOT NULL
                                DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    reviewed_at                 TEXT
);

CREATE INDEX IF NOT EXISTS idx_contribution_queue_status_program
    ON contribution_queue (status, program_id);

CREATE INDEX IF NOT EXISTS idx_contribution_queue_submitted_at
    ON contribution_queue (submitted_at);

CREATE INDEX IF NOT EXISTS idx_contribution_queue_houjin_hash
    ON contribution_queue (houjin_bangou_hash);

CREATE INDEX IF NOT EXISTS idx_contribution_queue_api_key
    ON contribution_queue (contributor_api_key_id);

-- ============================================================================
-- View: pending count rollup (operator dashboard hot path)
-- ============================================================================
CREATE VIEW IF NOT EXISTS v_contribution_queue_pending_count AS
SELECT COUNT(*) AS pending_count
  FROM contribution_queue
 WHERE status = 'pending';

-- View: per-program rollup (community-verified row count by program_id)
CREATE VIEW IF NOT EXISTS v_contribution_queue_per_program AS
SELECT program_id,
       SUM(CASE WHEN status = 'approved'  THEN 1 ELSE 0 END) AS approved_count,
       SUM(CASE WHEN status = 'pending'   THEN 1 ELSE 0 END) AS pending_count,
       SUM(CASE WHEN status = 'rejected'  THEN 1 ELSE 0 END) AS rejected_count,
       MAX(submitted_at)                                     AS last_submitted_at
  FROM contribution_queue
 GROUP BY program_id;

-- Bookkeeping is recorded by entrypoint.sh §4 / scripts/migrate.py.
-- Do NOT INSERT into schema_migrations here — that is the runner's job.
