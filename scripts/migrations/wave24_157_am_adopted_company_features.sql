-- target_db: autonomath
-- migration wave24_157_am_adopted_company_features
--
-- Why this exists:
--   Customer-LLM rule-based access path to "adopted_company_signature":
--   for a given houjin_bangou, return adoption_count, distinct_program_count,
--   first/last adoption timestamps, dominant JSIC major + prefecture,
--   enforcement_count, invoice_registered flag, loan_count, and a
--   credibility_score (0..1, reverse-weighted by enforcement_count).
--
--   Backs `score_application_probability` precision uplift and the
--   `find_adopted_company_signature` rule chain. Pre-aggregated so the
--   read path is a single PRIMARY-KEY lookup per houjin.
--
-- Schema:
--   * houjin_bangou TEXT PRIMARY KEY
--   * adoption_count INTEGER
--   * distinct_program_count INTEGER
--   * first_adoption_at TEXT
--   * last_adoption_at TEXT
--   * dominant_jsic_major TEXT     -- single letter A..T (NULL when unknown)
--   * dominant_prefecture TEXT     -- 都道府県 normalized name
--   * enforcement_count INTEGER    -- joined via recipient_name = normalized_name
--   * invoice_registered INTEGER   -- 0/1, T-number presence
--   * loan_count INTEGER           -- per-company loan corpus not yet ingested → 0
--   * credibility_score REAL       -- 0..1
--   * computed_at TEXT NOT NULL DEFAULT (datetime('now'))
--
-- Indexes:
--   * (credibility_score DESC) — top-N high-credibility lookups
--   * (adoption_count DESC) — heavy-adopter rankings
--   * (enforcement_count) WHERE enforcement_count > 0 — yellow-flag scan
--
-- Idempotency:
--   CREATE * IF NOT EXISTS. Populator uses INSERT OR REPLACE keyed on
--   houjin_bangou. Safe to re-apply on every container boot.
--
-- DOWN:
--   See companion `wave24_157_am_adopted_company_features_rollback.sql`.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS am_adopted_company_features (
    houjin_bangou           TEXT PRIMARY KEY,
    adoption_count          INTEGER NOT NULL DEFAULT 0,
    distinct_program_count  INTEGER NOT NULL DEFAULT 0,
    first_adoption_at       TEXT,
    last_adoption_at        TEXT,
    dominant_jsic_major     TEXT,
    dominant_prefecture     TEXT,
    enforcement_count       INTEGER NOT NULL DEFAULT 0,
    invoice_registered      INTEGER NOT NULL DEFAULT 0
                            CHECK (invoice_registered IN (0, 1)),
    loan_count              INTEGER NOT NULL DEFAULT 0,
    credibility_score       REAL CHECK (credibility_score IS NULL OR
                                        (credibility_score >= 0.0 AND
                                         credibility_score <= 1.0)),
    computed_at             TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_aacf_credibility
    ON am_adopted_company_features(credibility_score DESC)
    WHERE credibility_score IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_aacf_adoption
    ON am_adopted_company_features(adoption_count DESC);

CREATE INDEX IF NOT EXISTS idx_aacf_enforcement
    ON am_adopted_company_features(enforcement_count)
    WHERE enforcement_count > 0;
