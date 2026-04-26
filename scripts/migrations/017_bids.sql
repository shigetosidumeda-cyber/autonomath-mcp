-- 017_bids.sql
-- Adds `bids` table for 入札 (public procurement) ingestion and a trigram FTS
-- mirror. Third of the four 2026-04-24 expansion migrations
-- (015_laws → 016_court_decisions → 017_bids → 018_tax_rulesets).
--
-- Coverage target: ~1.5M+/年 国の調達 (GEPS) plus self-gov top-7 JV flows,
-- scoped to the latest 3 fiscal years at ingest time.
-- Primary sources (whitelisted):
--   * GEPS 政府電子調達 (https://www.p-portal.go.jp/) — national, CSV bulk,
--     CC-BY 4.0, no auth. Commercial redistribution with attribution
--     (出典: GEPS / 政府電子調達システム) is permitted.
--   * 自治体入札 top-7 JV: 神奈川県, 愛知県, 千葉県, 静岡県, e-Tokyo (東京都),
--     兵庫県, 福岡県 — all *.lg.jp.
--   * Ministry-direct procurement pages under *.go.jp (農林水産省 etc.).
-- Aggregators (NJSS, 入札情報サービス等) are NOT a primary source — they
-- are scraped secondaries. Ingest MUST re-fetch from the primary origin.
-- Banned aggregator domains inherited from 014 (noukaweb, hojyokin-portal,
-- biz.stayway, subsidymap, navit-j) also stay blocked here — this table
-- follows the same source_lineage_audit discipline.
--
-- Why `BID-<10 hex>` unified_id pattern:
--   * Matches the existing UNI- / LAW- / HAN- / TAX- families
--     (regex-disjoint by the 4-char prefix).
--   * 14 chars total (BID- + 10 lowercase hex) so a single CHECK covers both
--     length and prefix.
--   * Stable across GEPS revisions — if a bid notice is amended, the id stays;
--     the amendment writes a new row only when the 案件番号 itself changes.
--
-- Soft-FK hints (no hard FK, matches adoption_records / verticals_deep):
--   * `procuring_houjin_bangou` — the procuring entity's 13-digit 法人番号
--     where applicable (独立行政法人 etc.). Many procuring bodies are 国 or
--     地方公共団体 without a 法人番号 in houjin_master; a hard FK would force
--     NULL on the majority of rows. Resolved opportunistically during
--     analyze_fit / vendor history lookups.
--   * `program_id_hint` — programs.unified_id when a bid is the procurement
--     arm of a funded 補助事業 / 委託事業. Authored by ingest matchers; may
--     lag the programs catalog. Hard FK would block inserts when programs
--     row doesn't yet exist. Same pattern as adoption_records.program_id_hint
--     and verticals_deep.program_id_hint.
--
-- Lineage discipline (non-negotiable):
--   * Every row carries source_url + fetched_at. `source_excerpt` captures
--     the relevant passage (受注者名 / 落札金額 line etc.) for audit, and
--     `source_checksum` is optional (SHA-256 of raw fetch body).
--   * Ingest MUST fetch from the primary origin (p-portal.go.jp / *.go.jp /
--     *.lg.jp). Secondary aggregators are rejected at scripts/ingest/check_lineage.py.
--
-- FTS5 trigram gotcha (see CLAUDE.md "Common gotchas"):
--   Single-kanji false positives apply here too. Searching `工事` can match
--   rows containing only `事業` or `工場` because both share a single kanji.
--   API handlers must use quoted phrase queries (`"道路工事"`) for 2+ character
--   kanji compounds. See src/jpintel_mcp/api/programs.py for the reference
--   workaround; search_bids should mirror it.
--
-- Idempotency: every CREATE is IF NOT EXISTS; re-applying this file is a
-- no-op. The runner (scripts/migrate.py) records this in schema_migrations.

PRAGMA foreign_keys = ON;

-- ============================================================================
-- bids — canonical 入札 (public procurement) catalog
-- ============================================================================

CREATE TABLE IF NOT EXISTS bids (
    unified_id TEXT PRIMARY KEY,              -- BID-<10 lowercase hex>
    bid_title TEXT NOT NULL,                  -- 案件名
    bid_kind TEXT NOT NULL,                   -- 'open' (一般競争) | 'selective' (指名競争)
                                              -- | 'negotiated' (随意契約) | 'kobo_subsidy' (公募型補助)
    procuring_entity TEXT NOT NULL,           -- 発注機関名 (e.g. 国土交通省関東地方整備局)
    procuring_houjin_bangou TEXT,             -- 13-digit 法人番号 (soft ref; NO FK to houjin_master)
    ministry TEXT,                            -- 所管府省 (national procurements)
    prefecture TEXT,                          -- 都道府県 (self-gov procurements / 地方整備局)
    program_id_hint TEXT,                     -- programs.unified_id (soft ref; NO FK)
    announcement_date TEXT,                   -- ISO 8601 公告日
    question_deadline TEXT,                   -- ISO 8601 質問受付期限
    bid_deadline TEXT,                        -- ISO 8601 入札書提出期限
    decision_date TEXT,                       -- ISO 8601 落札決定日
    budget_ceiling_yen INTEGER,               -- 予定価格 / 契約限度額 (税込 if disclosed)
    awarded_amount_yen INTEGER,               -- 落札金額 (税込 if disclosed)
    winner_name TEXT,                         -- 落札者名 (as published)
    winner_houjin_bangou TEXT,                -- 落札者 法人番号 (soft ref; NO FK)
    participant_count INTEGER,                -- 入札参加者数
    bid_description TEXT,                     -- 調達概要 / 仕様要旨
    eligibility_conditions TEXT,              -- 参加資格要件 (等級 / 所在地 / 実績 etc.)
    classification_code TEXT,                 -- '役務' | '物品' | '工事' (or finer JGS code)
    source_url TEXT NOT NULL,                 -- primary source (GEPS / ministry / *.lg.jp)
    source_excerpt TEXT,                      -- relevant passage for audit
    source_checksum TEXT,                     -- optional SHA-256 of raw fetch body
    confidence REAL NOT NULL DEFAULT 0.9,     -- 0..1, matches 014/015 convention
    fetched_at TEXT NOT NULL,                 -- ISO 8601 UTC of last successful fetch
    updated_at TEXT NOT NULL,                 -- ISO 8601 UTC of last row write
    CHECK(length(unified_id) = 14 AND substr(unified_id,1,4) = 'BID-'),
    CHECK(bid_kind IN ('open','selective','negotiated','kobo_subsidy'))
);

CREATE INDEX IF NOT EXISTS idx_bids_procuring_entity
    ON bids(procuring_entity);
CREATE INDEX IF NOT EXISTS idx_bids_deadline
    ON bids(bid_deadline);
CREATE INDEX IF NOT EXISTS idx_bids_ministry_pref
    ON bids(ministry, prefecture);
CREATE INDEX IF NOT EXISTS idx_bids_winner_houjin
    ON bids(winner_houjin_bangou) WHERE winner_houjin_bangou IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_bids_program_hint
    ON bids(program_id_hint) WHERE program_id_hint IS NOT NULL;

-- ============================================================================
-- bids_fts — trigram FTS mirror for search_bids
-- ============================================================================
-- Same tokenizer as programs_fts / laws_fts (trigram). Single-kanji false
-- positives apply (see CLAUDE.md gotcha) — API handlers must use quoted
-- phrase queries for 2+ character kanji compounds. See
-- src/jpintel_mcp/api/programs.py for the reference workaround.

CREATE VIRTUAL TABLE IF NOT EXISTS bids_fts USING fts5(
    unified_id UNINDEXED,
    bid_title,
    bid_description,
    procuring_entity,
    winner_name,
    tokenize='trigram'
);

-- Bookkeeping is recorded by scripts/migrate.py into schema_migrations(id, checksum, applied_at).
-- Do NOT INSERT here — the schema is (id, checksum, applied_at), not (version, applied_at).
