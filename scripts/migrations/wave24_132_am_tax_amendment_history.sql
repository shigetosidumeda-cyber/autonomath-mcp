-- target_db: autonomath
-- migration wave24_132_am_tax_amendment_history (MASTER_PLAN_v1 章
-- 10.2.7 — 税制改正履歴 事前計算)
--
-- Why this exists:
--   `get_tax_amendment_cycle` (#103, sensitive=YES),
--   `predict_rd_tax_credit` (#108) and `simulate_tax_change_impact`
--   (#114) all need a frozen amendment history per ruleset so the
--   read path can answer "this ruleset was amended in 令和3, 令和5,
--   令和7 — next amendment expected 令和9". Computing this from
--   `am_amendment_diff` (currently 0 rows pending cron) joined
--   against `tax_rulesets` (50 rows) at request time is doable
--   but slow.
--
-- Schema:
--   * tax_ruleset_id INTEGER NOT NULL  — joins to tax_rulesets.id
--   * fiscal_year INTEGER NOT NULL     — 西暦 e.g. 2025
--   * amendment_kind TEXT NOT NULL     — 'create'|'extend'|'modify'|'sunset'
--   * effective_from TEXT              — ISO date the amendment took effect
--   * sunset_at TEXT                   — ISO date if applicable
--   * source_url TEXT                  — primary citation (NTA / METI)
--   * source_fetched_at TEXT
--   * diff_summary TEXT                — short prose
--   * amount_change_yen INTEGER        — delta in maximum 控除額 if numeric
--   * rate_change REAL                 — delta in % if numeric
--   * predicted_next_amendment_year INTEGER  — derived, may be NULL
--   * predicted_confidence REAL              — 0..1, NULL if not predicted
--   * computed_at TEXT NOT NULL DEFAULT (datetime('now'))
--   * UNIQUE(tax_ruleset_id, fiscal_year, amendment_kind)
--
-- Indexes:
--   * (tax_ruleset_id, fiscal_year DESC) — single ruleset history.
--   * (fiscal_year, amendment_kind) — "what changed in 令和7".
--
-- Idempotency:
--   CREATE * IF NOT EXISTS, INSERT OR REPLACE under UNIQUE.
--
-- DOWN:
--   See companion `wave24_132_am_tax_amendment_history_rollback.sql`.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS am_tax_amendment_history (
    history_id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    tax_ruleset_id               INTEGER NOT NULL,
    fiscal_year                  INTEGER NOT NULL,
    amendment_kind               TEXT NOT NULL CHECK (amendment_kind IN (
                                     'create','extend','modify','sunset'
                                 )),
    effective_from               TEXT,
    sunset_at                    TEXT,
    source_url                   TEXT,
    source_fetched_at            TEXT,
    diff_summary                 TEXT,
    amount_change_yen            INTEGER,
    rate_change                  REAL,
    predicted_next_amendment_year INTEGER,
    predicted_confidence         REAL CHECK (predicted_confidence IS NULL OR
                                             (predicted_confidence >= 0.0 AND
                                              predicted_confidence <= 1.0)),
    computed_at                  TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (tax_ruleset_id, fiscal_year, amendment_kind)
);

CREATE INDEX IF NOT EXISTS idx_atah_ruleset_year
    ON am_tax_amendment_history(tax_ruleset_id, fiscal_year DESC);

CREATE INDEX IF NOT EXISTS idx_atah_year_kind
    ON am_tax_amendment_history(fiscal_year, amendment_kind);
