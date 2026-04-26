-- 018_tax_rulesets.sql
-- Adds `tax_rulesets` table encoding 税務判定ルールセット (electronic
-- bookkeeping / invoice registration / tax credits / deductions) as
-- machine-readable decision trees. Fourth and final of the 2026-04-24
-- expansion migrations (015_laws → 016_court_decisions → 017_bids →
-- 018_tax_rulesets).
--
-- Coverage target: 130+ Q&A items sourced from:
--   * 国税庁 タックスアンサー (https://www.nta.go.jp/taxes/shiraberu/taxanswer/)
--   * 電子帳簿保存法 一問一答 (https://www.nta.go.jp/law/joho-zeikaishaku/sonota/jirei/)
--   * 消費税インボイス Q&A (https://www.nta.go.jp/taxes/shiraberu/zeimokubetsu/shohi/keigenzeiritsu/invoice_qa.htm)
-- Each Q&A item is re-encoded as a structured ruleset: narrative
-- `eligibility_conditions` for humans + `eligibility_conditions_json`
-- predicates the judgment engine evaluates.
--
-- Why `TAX-<10 hex>` unified_id pattern:
--   * Matches the existing UNI-/LAW-/HAN-/BID- 14-char conventions.
--   * Regex-disjoint from sibling prefixes — one router covers all four.
--   * Stable across ruleset revisions — superseded versions keep their
--     own unified_id; current rulesets set `effective_until = NULL`.
--
-- Cliff-date FLAGS (インボイス transitional measures — require review
-- when we cross the boundary):
--   * 2026-09-30  2割特例 (小規模事業者の消費税納税額軽減) 終了
--   * 2027-09-30  免税事業者からの仕入に係る経過措置 (80% 控除) 終了
--                 → 2029-09-30 まで段階的に 50% へ縮小後、廃止
--   * 2029-09-30  80%/50% 経過措置の完全廃止 / 少額特例 (¥1万円未満) 終了
-- Any ruleset row whose `effective_until` matches one of these three
-- cliff dates MUST be reviewed on / shortly before that date. The
-- judgment engine surfaces them via `idx_tax_effective` range scans;
-- scripts/audit_cliffs.py lists rows whose cliff is within 90 days.
--
-- Source whitelist (enforced by scripts/ingest/check_lineage.py):
--   * www.nta.go.jp          (国税庁 — タックスアンサー / 一問一答 / Q&A)
--   * www.mof.go.jp          (財務省 — 税制改正大綱 / 通達)
--   * elaws.e-gov.go.jp      (e-Gov 法令 — 根拠条文 cross-ref)
-- Any other primary source requires an explicit opt-in review. Ban list
-- (aggregator domains — noukaweb, hojyokin-portal, biz.stayway,
-- subsidymap, navit-j, plus 税理士事務所ブログ in general) stays in
-- effect — same rule as all upstream tables.
--
-- Foreign-key discipline: `related_law_ids_json` is JSON (not FK) by
-- design — rulesets commonly cite 10+ articles across 3-5 laws, and the
-- join-table approach used by program_law_refs would triple row count
-- here for marginal query benefit. Ingest validates each LAW-* exists in
-- `laws.unified_id` at write time.
--
-- Lineage discipline: every row carries source_url + fetched_at, plus
-- optional source_excerpt (raw Q&A text, ≤2,000 chars) and
-- source_checksum (SHA-256 of full source page body).
--
-- Idempotency: every CREATE is IF NOT EXISTS; re-applying this file is a
-- no-op. The runner (scripts/migrate.py) records this in schema_migrations.

PRAGMA foreign_keys = ON;

-- ============================================================================
-- tax_rulesets — canonical 税務判定ルールセット
-- ============================================================================

CREATE TABLE IF NOT EXISTS tax_rulesets (
    unified_id TEXT PRIMARY KEY,              -- TAX-<10 lowercase hex>
    ruleset_name TEXT NOT NULL,               -- '適格請求書発行事業者登録', '2割特例', '住宅ローン控除' ...
    tax_category TEXT NOT NULL,               -- 'consumption' | 'corporate' | 'income'
                                              -- | 'property' | 'local' | 'inheritance'
    ruleset_kind TEXT NOT NULL,               -- 'registration' | 'credit' | 'deduction'
                                              -- | 'special_depreciation' | 'exemption'
                                              -- | 'preservation' | 'other'
    effective_from TEXT NOT NULL,             -- ISO 8601 (施行日)
    effective_until TEXT,                     -- ISO 8601, NULL = 現行 (無期限)
                                              -- Cliff dates to flag:
                                              --   2026-09-30 (2割特例 終了)
                                              --   2027-09-30 (80% 経過措置 終了)
                                              --   2029-09-30 (50% 経過措置 / 少額特例 終了)
    related_law_ids_json TEXT,                -- JSON list[str]: ['LAW-xxxxxxxxxx', ...]
    eligibility_conditions TEXT,              -- narrative (for humans / LLM retrieval)
    eligibility_conditions_json TEXT,         -- structured predicates for judgment engine
                                              --   e.g. [{"op":"AND","terms":[
                                              --     {"field":"annual_revenue_yen","cmp":"<=","val":10000000},
                                              --     {"field":"business_type","cmp":"in","val":["sole_prop","corp"]}
                                              --   ]}]
    rate_or_amount TEXT,                      -- '10%' / '¥400,000 上限' / '控除率 2%' ...
    calculation_formula TEXT,                 -- '課税売上高 × 0.8 × 税率' etc.
    filing_requirements TEXT,                 -- 届出書式 / 提出先 / 期限 narrative
    authority TEXT NOT NULL,                  -- '国税庁' | '財務省' | '地方税' (e.g. 総務省 / 都道府県税事務所)
    authority_url TEXT,                       -- authority's landing page
    source_url TEXT NOT NULL,                 -- primary source (whitelist: nta/mof/e-Gov)
    source_excerpt TEXT,                      -- raw Q&A text / 通達抜粋 (≤2,000 chars)
    source_checksum TEXT,                     -- optional SHA-256 of raw fetch body
    confidence REAL NOT NULL DEFAULT 0.92,    -- 0..1, matches 011/014/015 convention
    fetched_at TEXT NOT NULL,                 -- ISO 8601 UTC of last successful fetch
    updated_at TEXT NOT NULL,                 -- ISO 8601 UTC of last row write
    CHECK(length(unified_id) = 14 AND substr(unified_id,1,4) = 'TAX-'),
    CHECK(tax_category IN ('consumption','corporate','income','property','local','inheritance')),
    CHECK(ruleset_kind IN ('registration','credit','deduction','special_depreciation','exemption','preservation','other'))
);

CREATE INDEX IF NOT EXISTS idx_tax_category_kind
    ON tax_rulesets(tax_category, ruleset_kind);
CREATE INDEX IF NOT EXISTS idx_tax_effective
    ON tax_rulesets(effective_from, effective_until);
CREATE INDEX IF NOT EXISTS idx_tax_authority
    ON tax_rulesets(authority);

-- ============================================================================
-- tax_rulesets_fts — trigram FTS mirror for search_tax_rulesets
-- ============================================================================
-- Same tokenizer as programs_fts / laws_fts (trigram). Single-kanji false
-- positives apply (see CLAUDE.md gotcha) — API handlers must use quoted
-- phrase queries for 2+ character kanji compounds. See
-- src/jpintel_mcp/api/programs.py for the reference workaround.

CREATE VIRTUAL TABLE IF NOT EXISTS tax_rulesets_fts USING fts5(
    unified_id UNINDEXED,
    ruleset_name,
    eligibility_conditions,
    calculation_formula,
    tokenize='trigram'
);

-- Bookkeeping is recorded by scripts/migrate.py into schema_migrations(id, checksum, applied_at).
-- Do NOT INSERT here — the schema is (id, checksum, applied_at), not (version, applied_at).
