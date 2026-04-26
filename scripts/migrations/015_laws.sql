-- 015_laws.sql
-- Adds `laws` table for e-Gov 法令 API ingestion, a trigram FTS mirror, and
-- a `program_law_refs` join table linking 7,990 programs to their 根拠法 /
-- 関連法令 chain. First of the four 2026-04-24 expansion migrations
-- (015_laws → 016_court_decisions → 017_bids → 018_tax_rulesets).
--
-- Coverage target: ~3,400 laws (憲法 + 法律 + 政令 + 勅令 + 府省令 + 規則).
-- Source: e-Gov 法令 API V2 (https://laws.e-gov.go.jp/api/2/), CC-BY 4.0,
-- no auth. Redistribution with attribution (出典: e-Gov) is permitted; the
-- commercial downstream API is allowed.
--
-- Why `LAW-<10 hex>` unified_id pattern:
--   * Matches the existing `UNI-<10 hex>` format for programs.unified_id.
--   * Regex-disjoint from UNI-/HAN-/BID-/TAX- prefixes (see 016-018).
--   * Stable across revision chains — superseded laws keep their own
--     unified_id and link forward via `superseded_by_law_id`.
--
-- Foreign-key discipline:
--   * `program_law_refs` hard-FKs both sides. Programs use CASCADE on
--     delete (if a program is purged, its law-refs are meaningless).
--     Laws use RESTRICT — laws are rarely deleted; revision goes through
--     `revision_status='superseded'` + chain, not deletion.
--   * `superseded_by_law_id` self-FK on laws is RESTRICT as well — we
--     should never orphan a chain.
--
-- Lineage discipline (non-negotiable):
--   * Every row carries source_url + fetched_at. `source_checksum` is
--     optional (SHA-256 of raw API response body).
--   * Whitelisted domains: elaws.e-gov.go.jp, laws.e-gov.go.jp,
--     www.shugiin.go.jp, www.sangiin.go.jp. Any other primary source
--     requires an explicit opt-in via scripts/ingest/check_lineage.py.
--   * Aggregators (noukaweb, hojyokin-portal, biz.stayway, subsidymap,
--     navit-j) are hard-banned — same rule as existing tables.
--
-- Idempotency: every CREATE is IF NOT EXISTS; re-applying this file is a
-- no-op. The runner (scripts/migrate.py) records this in schema_migrations.

PRAGMA foreign_keys = ON;

-- ============================================================================
-- laws — canonical 法令 catalog
-- ============================================================================

CREATE TABLE IF NOT EXISTS laws (
    unified_id TEXT PRIMARY KEY,              -- LAW-<10 lowercase hex>
    law_number TEXT NOT NULL,                 -- 昭和三十八年法律第百四十七号 / 令和六年政令第X号
    law_title TEXT NOT NULL,                  -- 正式名称
    law_short_title TEXT,                     -- 略称 / 略語
    law_type TEXT NOT NULL,                   -- 'constitution' | 'act' | 'cabinet_order'
                                              -- | 'imperial_order' | 'ministerial_ordinance'
                                              -- | 'rule' | 'notice' | 'guideline'
    ministry TEXT,                            -- 所管府省
    promulgated_date TEXT,                    -- ISO 8601 (公布日)
    enforced_date TEXT,                       -- ISO 8601 (施行日, may differ from promulgated)
    last_amended_date TEXT,                   -- ISO 8601
    revision_status TEXT NOT NULL DEFAULT 'current',  -- 'current' | 'superseded' | 'repealed'
    superseded_by_law_id TEXT,                -- self-FK (current 法令 that replaced this one)
    article_count INTEGER,                    -- 条文数
    full_text_url TEXT,                       -- e-Gov 法令検索 permalink (for humans)
    summary TEXT,                             -- 2-3 line abstract (for LLM retrieval)
    subject_areas_json TEXT,                  -- JSON list[str]: ['subsidy_clawback','tax_credit',...]
    source_url TEXT NOT NULL,                 -- primary source (e-Gov preferred)
    source_checksum TEXT,                     -- optional SHA-256 of raw fetch body
    confidence REAL NOT NULL DEFAULT 0.95,    -- 0..1, matches 011/014 convention
    fetched_at TEXT NOT NULL,                 -- ISO 8601 UTC of last successful fetch
    updated_at TEXT NOT NULL,                 -- ISO 8601 UTC of last row write
    CHECK(length(unified_id) = 14 AND substr(unified_id,1,4) = 'LAW-'),
    CHECK(revision_status IN ('current','superseded','repealed')),
    FOREIGN KEY(superseded_by_law_id) REFERENCES laws(unified_id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_laws_ministry ON laws(ministry);
CREATE INDEX IF NOT EXISTS idx_laws_type ON laws(law_type, revision_status);
CREATE INDEX IF NOT EXISTS idx_laws_enforced ON laws(enforced_date);
CREATE INDEX IF NOT EXISTS idx_laws_number ON laws(law_number);
CREATE INDEX IF NOT EXISTS idx_laws_current
    ON laws(law_type) WHERE revision_status = 'current';

-- ============================================================================
-- laws_fts — trigram FTS mirror for search_laws
-- ============================================================================
-- Same tokenizer as programs_fts (trigram). Single-kanji false positives
-- apply (see CLAUDE.md gotcha) — API handlers must use quoted phrase
-- queries for 2+ character kanji compounds. See src/jpintel_mcp/api/programs.py
-- for the reference workaround.

CREATE VIRTUAL TABLE IF NOT EXISTS laws_fts USING fts5(
    unified_id UNINDEXED,
    law_title,
    law_short_title,
    law_number,
    summary,
    tokenize='trigram'
);

-- ============================================================================
-- program_law_refs — N:M linkage programs ⇌ laws
-- ============================================================================
-- A program commonly cites multiple statutes (補助金適正化法 + 所轄省庁設置法
-- + 施行令). Externalizing to a join table avoids a painful
-- ALTER TABLE programs ADD COLUMN on the 7,990-row production table and
-- lets the 根拠法 chain be authored independently of the programs ingest.

CREATE TABLE IF NOT EXISTS program_law_refs (
    program_unified_id TEXT NOT NULL,         -- programs.unified_id (UNI-*)
    law_unified_id TEXT NOT NULL,             -- laws.unified_id (LAW-*)
    ref_kind TEXT NOT NULL,                   -- 'authority' (根拠) | 'eligibility'
                                              -- | 'exclusion' | 'reference' | 'penalty'
    article_citation TEXT,                    -- '第5条第2項' etc. — empty string if whole-law
    source_url TEXT NOT NULL,                 -- where we learned the ref (program page / 要綱 PDF)
    fetched_at TEXT NOT NULL,                 -- ISO 8601 UTC
    confidence REAL NOT NULL DEFAULT 0.9,
    PRIMARY KEY(program_unified_id, law_unified_id, ref_kind, article_citation),
    CHECK(ref_kind IN ('authority','eligibility','exclusion','reference','penalty')),
    FOREIGN KEY(program_unified_id) REFERENCES programs(unified_id) ON DELETE CASCADE,
    FOREIGN KEY(law_unified_id)     REFERENCES laws(unified_id)     ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_plr_law ON program_law_refs(law_unified_id);
CREATE INDEX IF NOT EXISTS idx_plr_kind ON program_law_refs(ref_kind);
CREATE INDEX IF NOT EXISTS idx_plr_fetched ON program_law_refs(fetched_at);
