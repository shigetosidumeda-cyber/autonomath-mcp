-- target_db: autonomath
-- migration 216_am_program_substitute
-- generated_at: 2026-05-11
-- author: Wave 20 B5/C7 #1 (program substitute / 制度差し替え)
--
-- Purpose
-- -------
-- When a program is sunset, retired, or merged into another program,
-- we currently store the successor relation in `am_relation` with type
-- 'successor_of', but the surface contract has no first-class table for
-- the substitution event itself — which fact (sunset date / merge date
-- / replacement date / archive policy) was emitted, by which authority,
-- and with which evidence URL.
--
-- `am_program_substitute` is that capture surface. One row per
-- (predecessor_program_id, successor_program_id, substitute_kind)
-- triple, with provenance + effective date + announcement URL.
--
-- Surface contract
-- ----------------
-- - REST: `GET /v1/am/programs/{id}/substitute` returns the row + the
--   matching `am_relation(type='successor_of')` row joined.
-- - MCP: surfaced via `program_lifecycle` tool envelope `_substitute`
--   field (additive — does NOT bump tool count).
-- - cron: `scripts/cron/detect_program_substitutes.py` fans out from
--   `am_amendment_diff` watch detections.
--
-- Why not extend `programs.replaced_by_program_id`
-- ------------------------------------------------
-- programs.replaced_by_program_id is a 1:1 link. Some programs are
-- merged into a multi-program new umbrella (e.g. ものづくり補助金
-- 一般型 + グローバル展開型 → 統合型). 1:N + kind discrimination needs
-- its own table.
--
-- Idempotency: all CREATE * IF NOT EXISTS, safe to re-run on every boot.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS am_program_substitute (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    predecessor_pid    TEXT    NOT NULL,
    successor_pid      TEXT,                                 -- NULL = pure sunset (no successor)
    substitute_kind    TEXT    NOT NULL,                     -- enum: 'sunset' | 'merge' | 'replace' | 'rename'
    effective_from     TEXT,                                 -- ISO date (YYYY-MM-DD)
    announced_at       TEXT,                                 -- ISO date
    authority_id       INTEGER,                              -- FK am_authority.id
    announcement_url   TEXT,                                 -- evidence URL (primary source)
    notes              TEXT,                                 -- 1-3 sentence human note
    detected_at        TEXT    NOT NULL DEFAULT (datetime('now')),
    -- review_status discriminates auto-detected (cron) from manually-
    -- curated rows. 'pending' rows must NOT be surfaced via REST/MCP.
    review_status      TEXT    NOT NULL DEFAULT 'pending',
    reviewed_at        TEXT,
    reviewed_by        TEXT,
    CONSTRAINT ck_substitute_kind
        CHECK (substitute_kind IN ('sunset', 'merge', 'replace', 'rename')),
    CONSTRAINT ck_substitute_review
        CHECK (review_status IN ('pending', 'approved', 'rejected'))
);

-- Lookup by predecessor (the question "what replaced X?").
CREATE INDEX IF NOT EXISTS idx_am_program_substitute_pred
    ON am_program_substitute(predecessor_pid);

-- Lookup by successor (the question "what was rolled into Y?").
CREATE INDEX IF NOT EXISTS idx_am_program_substitute_succ
    ON am_program_substitute(successor_pid)
    WHERE successor_pid IS NOT NULL;

-- Surface-only filter index (REST/MCP serves only approved rows).
CREATE INDEX IF NOT EXISTS idx_am_program_substitute_approved
    ON am_program_substitute(predecessor_pid, effective_from)
    WHERE review_status = 'approved';

-- View: approved substitutions only, joined with am_relation when present.
-- Used by `GET /v1/am/programs/{id}/substitute` and the
-- `program_lifecycle` MCP tool. Re-create-able (DROP VIEW IF EXISTS first).
DROP VIEW IF EXISTS v_am_program_substitute_active;
CREATE VIEW v_am_program_substitute_active AS
SELECT
    s.id,
    s.predecessor_pid,
    s.successor_pid,
    s.substitute_kind,
    s.effective_from,
    s.announced_at,
    s.authority_id,
    s.announcement_url,
    s.notes
FROM am_program_substitute AS s
WHERE s.review_status = 'approved';
