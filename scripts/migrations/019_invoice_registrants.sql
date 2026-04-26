-- 019_invoice_registrants.sql
-- Adds `invoice_registrants` table — 適格請求書発行事業者 (qualified invoice
-- issuer) master sourced from 国税庁 適格請求書発行事業者公表サイト bulk
-- download. Fifth of the 2026-04-24 dataset expansion migrations
-- (015_laws → 016_court_decisions → 017_bids → 018_tax_rulesets → 019_invoice_registrants).
--
-- Coverage target: ≈4,000,000 rows (corporations + sole proprietors, active
-- + revoked + expired). Bulk XML/CSV: monthly full snapshot + daily delta.
-- Source URL base: https://www.invoice-kohyo.nta.go.jp/download/
--
-- ============================================================================
-- LICENSE / ATTRIBUTION -- 公共データ利用規約 第1.0版 (PDL v1.0)
-- ============================================================================
-- NTA publishes this dataset under the 公共データ利用規約 第1.0版 (PDL 1.0).
-- Commercial redistribution and downstream API exposure are PERMITTED provided:
--
--   (a) 出典明記 (source attribution) on every surface that renders any
--       invoice_registrants field. Required attribution string:
--
--         出典: 国税庁適格請求書発行事業者公表サイト（国税庁）
--               (https://www.invoice-kohyo.nta.go.jp/)
--
--   (b) 編集・加工注記 (edit/transformation notice) whenever values have
--       been normalized, joined, or otherwise altered from the raw NTA
--       feed. Required notice (Japanese):
--
--         本データは国税庁適格請求書発行事業者公表サイトを
--         Bookyou株式会社が編集・加工したものです。
--
-- Enforcement in code:
--   * Every REST / MCP response that exposes any column from this table
--     MUST include both (a) and (b) in a top-level `attribution` field or
--     equivalent visible location. The response serializer is the
--     enforcement point — see src/jpintel_mcp/api/attribution.py.
--   * Static pages (per-registrant SEO pages) MUST carry the attribution
--     in a visible footer, not only meta tags.
--   * Bulk export (CSV / JSON dumps) MUST prepend a header comment block
--     containing the same two strings.
--
-- Source discipline:
--   * Bulk download ONLY. The public web UI (検索 form) is governed by a
--     separate TOS that explicitly bans scraping; do NOT use it as a
--     source. Authorized endpoints: invoice-kohyo.nta.go.jp/download/*
--     (monthly full, daily delta, archived snapshots).
--   * Banned aggregators (noukaweb, hojyokin-portal, biz.stayway,
--     subsidymap, navit-j) remain banned — same rule as 011/014/015.
--
-- ============================================================================
-- VOLUME & INGEST GUIDANCE (~4 million rows)
-- ============================================================================
-- * Use batched INSERT with `executemany()` in chunks of 10,000-50,000.
--   Wrap the whole monthly full-load in a single transaction, or commit
--   per chunk if memory is tight. Expect ~15-40 minutes end-to-end on an
--   M-series Mac; slower on Fly.io shared-cpu.
-- * BEFORE the full-load run:
--       PRAGMA journal_mode = WAL;
--       PRAGMA synchronous = NORMAL;
--       PRAGMA temp_store = MEMORY;
--       PRAGMA cache_size = -200000;   -- ~200MB page cache
-- * Defer index creation when rebuilding from scratch: DROP the non-PK
--   indexes, bulk-INSERT, then CREATE INDEX at the end. Saves ~40% wall
--   time on the first load. (IF NOT EXISTS here means reapplying the
--   migration is still a no-op, but a first-load optimizer script can
--   legitimately drop + recreate.)
-- * After full-load: `VACUUM;` and `ANALYZE invoice_registrants;`.
--   VACUUM on a 4M-row table is slow (~5-10 min) but reclaims space from
--   the monthly delta churn and keeps query plans stable.
-- * Daily delta: use UPSERT (INSERT ... ON CONFLICT(invoice_registration_number)
--   DO UPDATE ...) — typical delta is ~2-5K rows.
-- * Expected disk footprint: ~900MB-1.4GB table + ~400-600MB indexes.
--
-- Idempotency: every CREATE is IF NOT EXISTS; re-applying is a no-op. The
-- runner (scripts/migrate.py) records this in schema_migrations.

PRAGMA foreign_keys = ON;

-- ============================================================================
-- invoice_registrants -- 適格請求書発行事業者 master
-- ============================================================================
-- Design notes:
--   * PRIMARY KEY is invoice_registration_number (T + 13 digits, 14 chars).
--     Not houjin_bangou — a 法人 can in principle hold multiple registration
--     events over its lifetime, and (more importantly) individual
--     事業者 (sole proprietors) often lack a houjin_bangou at all.
--   * houjin_bangou is nullable and a SOFT reference only (no hard FK).
--     Rationale: individual 事業者 without a 法人番号 are a large slice of
--     the population; enforcing FK would force us to drop them. Matches
--     the 011 external-data precedent ("Intentionally NOT enforced to
--     programs(unified_id)"). The join to houjin_master is performed at
--     query time, filtered by `houjin_bangou IS NOT NULL`.
--   * revoked_date and expired_date NULL means "currently 有効". The
--     composite index (revoked_date, expired_date) supports the common
--     "active only" filter used by the public search tool.
--   * confidence defaults to 0.98 because the source is 一次公表 (primary
--     official data), matching the highest tier in 014/015.
--   * source_url is required even though the origin is fixed; this keeps
--     the column's semantics uniform across the schema and lets the
--     lineage audit (source_lineage_audit in 014) apply the same
--     banned-domain filter without special-casing this table.

CREATE TABLE IF NOT EXISTS invoice_registrants (
    invoice_registration_number TEXT PRIMARY KEY,  -- 'T' + 13 digits (14 chars total)
    houjin_bangou TEXT,                            -- 13 digits; NULL for sole proprietors / other
    normalized_name TEXT NOT NULL,                 -- 事業者名 (公表名称)
    address_normalized TEXT,                       -- 所在地 (normalized)
    prefecture TEXT,                               -- 都道府県
    registered_date TEXT NOT NULL,                 -- 登録日 (ISO 8601)
    revoked_date TEXT,                             -- 取消日 (NULL = 未取消)
    expired_date TEXT,                             -- 失効日 (NULL = 未失効)
    registrant_kind TEXT NOT NULL,                 -- 'corporation' | 'sole_proprietor' | 'other'
    trade_name TEXT,                               -- 屋号等 (nullable)
    last_updated_nta TEXT,                         -- NTA's timestamp on this record
    source_url TEXT NOT NULL,                      -- https://www.invoice-kohyo.nta.go.jp/download/...
    source_checksum TEXT,                          -- optional SHA-256 of raw bulk file
    confidence REAL NOT NULL DEFAULT 0.98,         -- 一次公表 → high
    fetched_at TEXT NOT NULL,                      -- ISO 8601 UTC of last successful fetch
    updated_at TEXT NOT NULL,                      -- ISO 8601 UTC of last row write
    CHECK(length(invoice_registration_number) = 14
          AND substr(invoice_registration_number, 1, 1) = 'T'),
    CHECK(registrant_kind IN ('corporation', 'sole_proprietor', 'other'))
    -- NOTE: No hard FOREIGN KEY on houjin_bangou. Soft reference only —
    -- individual sole_proprietors often have no houjin_bangou. The join
    -- to houjin_master (migration 014) is performed at query time.
);

-- ============================================================================
-- Indexes
-- ============================================================================
-- Partial index on houjin_bangou: large chunk of rows are NULL (sole props),
-- partial index keeps size down and still accelerates join to houjin_master.

CREATE INDEX IF NOT EXISTS idx_invoice_registrants_houjin
    ON invoice_registrants(houjin_bangou) WHERE houjin_bangou IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_invoice_registrants_name
    ON invoice_registrants(normalized_name);

CREATE INDEX IF NOT EXISTS idx_invoice_registrants_prefecture
    ON invoice_registrants(prefecture);

CREATE INDEX IF NOT EXISTS idx_invoice_registrants_registered
    ON invoice_registrants(registered_date);

-- "Currently active" queries: WHERE revoked_date IS NULL AND expired_date IS NULL.
-- Composite index supports both the filter and ordering by registration date.
CREATE INDEX IF NOT EXISTS idx_invoice_registrants_active
    ON invoice_registrants(revoked_date, expired_date);

CREATE INDEX IF NOT EXISTS idx_invoice_registrants_kind
    ON invoice_registrants(registrant_kind);

-- Bookkeeping is recorded by scripts/migrate.py into schema_migrations(id, checksum, applied_at).
-- Do NOT INSERT here — the schema is (id, checksum, applied_at), not (version, applied_at).
