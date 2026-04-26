-- 016_court_decisions.sql
-- Adds `court_decisions` as a first-class 判例 table (supersets the existing
-- 012 `case_law` catalog), a trigram FTS mirror, and
-- `enforcement_decision_refs` to tie 会計検査院 / ministry enforcement findings
-- (011 `enforcement_cases`) back to the judicial rulings that cite or bind
-- them. Second of the four 2026-04-24 expansion migrations
-- (015_laws → 016_court_decisions → 017_bids → 018_tax_rulesets).
--
-- Why a new table instead of ALTER-ing `case_law`:
--   * 012 `case_law` uses an INTEGER surrogate PK and TEXT-bucketed
--     confidence. We need a `HAN-<10 hex>` unified_id + REAL confidence
--     to stay regex-disjoint and aligned with UNI-/LAW-/BID-/TAX-.
--   * Adding nullable lineage cols (source_checksum, updated_at, etc.) to a
--     pre-existing rows-present table is fiddly and the 012 table is small
--     enough that a future migration can copy-forward and drop.
--   * `case_law` is kept intact for backward compat; this migration adds a
--     view (`case_law_v2`) that projects `court_decisions` into the 012
--     column shape so consumers can migrate incrementally. The actual
--     drop + data migration lands in a follow-up (017+) once callers are
--     off `case_law`.
--
-- Coverage target: courts.go.jp hanrei_jp (裁判所判例検索) is the only
-- whitelisted primary source for this domain. Supreme, High, District,
-- Summary, Family. The D1 Law / Westlaw Japan / LEX/DB commercial
-- aggregators are **banned** (license + 再配布 blocks + no primary cite).
--
-- Why `HAN-<10 hex>` unified_id pattern:
--   * 14-char fixed width, same shape as UNI-/LAW-/BID-/TAX-.
--   * Regex-disjoint prefixes (`^(UNI|LAW|HAN|BID|TAX)-[0-9a-f]{10}$`).
--   * Natural-key UNIQUE(case_number, court) preserved below — case_number
--     alone collides across 最高裁 + 控訴審 on the same dispute, so we pin
--     both dimensions (same logic as 012).
--
-- Foreign-key discipline:
--   * `enforcement_decision_refs.enforcement_case_id` → `enforcement_cases`
--     CASCADE: if the enforcement case is purged its refs are noise.
--   * `enforcement_decision_refs.decision_unified_id` → `court_decisions`
--     RESTRICT: rulings are persistent; we don't delete jurisprudence.
--
-- Lineage discipline (non-negotiable):
--   * source_url NOT NULL + fetched_at NOT NULL + updated_at NOT NULL.
--   * Whitelisted domain: `www.courts.go.jp` (hanrei_jp UI + PDF mirrors
--     under /app/hanrei_jp/). Everything else requires opt-in through
--     scripts/ingest/check_lineage.py.
--   * Banned aggregators (noukaweb, hojyokin-portal, biz.stayway,
--     subsidymap, navit-j, D1 Law, Westlaw Japan, LEX/DB) are hard-rejected
--     at ingest.
--
-- FTS gotcha (same as 011/014/015):
--   * trigram tokenizer gives single-kanji false positives
--     (searching 控除 collides with rows that only mention 除外 because
--     both contain 除). API handlers must quote 2+ character compounds.
--     See src/jpintel_mcp/api/programs.py for the reference workaround.
--
-- Idempotency: every CREATE is IF NOT EXISTS; re-applying is a no-op.
-- Bookkeeping is recorded by scripts/migrate.py into schema_migrations.

PRAGMA foreign_keys = ON;

-- ============================================================================
-- court_decisions — canonical 判例 catalog (supersets 012 case_law)
-- ============================================================================

CREATE TABLE IF NOT EXISTS court_decisions (
    unified_id TEXT PRIMARY KEY,              -- HAN-<10 lowercase hex>
    case_name TEXT NOT NULL,                  -- 事件名 (e.g., 所得税更正処分取消請求事件)
    case_number TEXT,                         -- 平成29年(行ヒ)第123号 / 令和5年(受)第456号
    court TEXT,                               -- 裁判所名 (最高裁判所第三小法廷 / 東京地方裁判所 etc.)
    court_level TEXT NOT NULL,                -- 'supreme' | 'high' | 'district' | 'summary' | 'family'
    decision_date TEXT,                       -- ISO 8601 (言渡日)
    decision_type TEXT NOT NULL,              -- '判決' | '決定' | '命令'
    subject_area TEXT,                        -- '租税' / '行政' / '補助金適正化法' / ...
    related_law_ids_json TEXT,                -- JSON list[str]: ['LAW-...','LAW-...']
    key_ruling TEXT,                          -- 判示事項の要約 (2-5 lines)
    parties_involved TEXT,                    -- 当事者 (概要・匿名化後)
    impact_on_business TEXT,                  -- 実務影響 (LLM retrieval-friendly summary)
    precedent_weight TEXT NOT NULL DEFAULT 'informational',
                                              -- 先例価値:
                                              --   'binding'       = 最高裁 or 大法廷
                                              --   'persuasive'    = 高裁・地裁のリーディングケース
                                              --   'informational' = 事例参考
    full_text_url TEXT,                       -- courts.go.jp hanrei_jp permalink
    pdf_url TEXT,                             -- 全文 PDF ミラー
    source_url TEXT NOT NULL,                 -- primary source (courts.go.jp required)
    source_excerpt TEXT,                      -- 原文抜粋 (引用根拠用)
    source_checksum TEXT,                     -- optional SHA-256 of raw fetch body
    confidence REAL NOT NULL DEFAULT 0.9,     -- 0..1, matches 014/015 convention
    fetched_at TEXT NOT NULL,                 -- ISO 8601 UTC of last successful fetch
    updated_at TEXT NOT NULL,                 -- ISO 8601 UTC of last row write
    CHECK(length(unified_id) = 14 AND substr(unified_id,1,4) = 'HAN-'),
    CHECK(court_level IN ('supreme','high','district','summary','family')),
    CHECK(decision_type IN ('判決','決定','命令')),
    CHECK(precedent_weight IN ('binding','persuasive','informational')),
    UNIQUE(case_number, court)
);

CREATE INDEX IF NOT EXISTS idx_court_decisions_court_level
    ON court_decisions(court_level);
CREATE INDEX IF NOT EXISTS idx_court_decisions_subject_area
    ON court_decisions(subject_area);
CREATE INDEX IF NOT EXISTS idx_court_decisions_decision_date
    ON court_decisions(decision_date);
CREATE INDEX IF NOT EXISTS idx_court_decisions_weight
    ON court_decisions(precedent_weight, court_level);
CREATE INDEX IF NOT EXISTS idx_court_decisions_type
    ON court_decisions(decision_type);
CREATE INDEX IF NOT EXISTS idx_court_decisions_binding
    ON court_decisions(subject_area) WHERE precedent_weight = 'binding';

-- ============================================================================
-- court_decisions_fts — trigram FTS mirror for search_court_decisions
-- ============================================================================
-- Same tokenizer choice as programs_fts / laws_fts (trigram). Single-kanji
-- false-positive gotcha applies — API handlers must quote 2+ character
-- kanji compounds. See src/jpintel_mcp/api/programs.py for the reference
-- workaround used across the search endpoints.

CREATE VIRTUAL TABLE IF NOT EXISTS court_decisions_fts USING fts5(
    unified_id UNINDEXED,
    case_name,
    subject_area,
    key_ruling,
    impact_on_business,
    tokenize='trigram'
);

-- ============================================================================
-- enforcement_decision_refs — N:M linkage enforcement_cases ⇌ court_decisions
-- ============================================================================
-- 会計検査院 / ministry enforcement cases (011 enforcement_cases) often
-- cite — or are later litigated up to — specific rulings. Externalizing
-- to a join table avoids widening enforcement_cases and keeps the
-- citation chain directional (an enforcement case can reference many
-- rulings; one ruling can be cited by many enforcement cases).
--
-- ref_kind:
--   'direct'    — the enforcement case was the subject of this ruling
--                 (e.g., 原告が処分取消を請求 → 判決確定)
--   'related'   — same 行政処分 chain, different 当事者
--   'precedent' — the enforcement case cites this ruling as authority

CREATE TABLE IF NOT EXISTS enforcement_decision_refs (
    enforcement_case_id TEXT NOT NULL,        -- enforcement_cases.case_id
    decision_unified_id TEXT NOT NULL,        -- court_decisions.unified_id (HAN-*)
    ref_kind TEXT NOT NULL,                   -- 'direct' | 'related' | 'precedent'
    source_url TEXT,                          -- where we learned the ref (judgment / 検査報告)
    fetched_at TEXT,                          -- ISO 8601 UTC
    PRIMARY KEY(enforcement_case_id, decision_unified_id, ref_kind),
    CHECK(ref_kind IN ('direct','related','precedent')),
    FOREIGN KEY(enforcement_case_id)
        REFERENCES enforcement_cases(case_id) ON DELETE CASCADE,
    FOREIGN KEY(decision_unified_id)
        REFERENCES court_decisions(unified_id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_edr_decision
    ON enforcement_decision_refs(decision_unified_id);
CREATE INDEX IF NOT EXISTS idx_edr_kind
    ON enforcement_decision_refs(ref_kind);
CREATE INDEX IF NOT EXISTS idx_edr_fetched
    ON enforcement_decision_refs(fetched_at);

-- ============================================================================
-- case_law_v2 — backward-compat projection over court_decisions
-- ============================================================================
-- DEPRECATION PATH for 012 `case_law`:
--   Phase 1 (this migration): `court_decisions` is the canonical table.
--     `case_law` (012) is untouched — existing readers keep working.
--     `case_law_v2` exposes `court_decisions` in the 012 column shape so
--     new readers can target the view and be no-op portable when the
--     physical `case_law` table is finally dropped.
--   Phase 2 (future migration, post-cutover): bulk-copy any residual
--     `case_law` rows into `court_decisions`, DROP the physical
--     `case_law` table, then DROP VIEW `case_law_v2` and optionally
--     recreate it as a rename-alias of `court_decisions` if consumers
--     still reference the legacy name.
--
-- Intentional gaps in the view (vs. 012):
--   * 012.id (INTEGER AUTOINCREMENT) is not reproducible from unified_id.
--     We expose `unified_id` in its place; pagination consumers should
--     migrate to `unified_id` before the physical drop.
--   * 012.category (freeform TEXT, sparsely populated) maps to
--     subject_area in the new schema — we project subject_area through.
--   * 012.confidence was TEXT ('high'/'medium'); new REAL confidence is
--     surfaced numerically. Callers doing string-compare need to adapt
--     before cutover.

CREATE VIEW IF NOT EXISTS case_law_v2 AS
SELECT
    unified_id            AS unified_id,
    case_name             AS case_name,
    court                 AS court,
    decision_date         AS decision_date,
    case_number           AS case_number,
    subject_area          AS subject_area,
    key_ruling            AS key_ruling,
    parties_involved      AS parties_involved,
    impact_on_business    AS impact_on_business,
    source_url            AS source_url,
    source_excerpt        AS source_excerpt,
    confidence            AS confidence,
    pdf_url               AS pdf_url,
    subject_area          AS category,
    fetched_at            AS fetched_at
FROM court_decisions;

-- Bookkeeping is recorded by scripts/migrate.py into schema_migrations(id, checksum, applied_at).
-- Do NOT INSERT here — the schema is (id, checksum, applied_at), not (version, applied_at).
