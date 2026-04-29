-- target_db: autonomath
-- migration 091_tax_treaty (Foreign FDI cohort capture, feature 5)
--
-- Adds a manually-curated Double Tax Agreement (DTA / 租税条約) matrix
-- so foreign investors / cross-border SMBs can look up withholding-tax
-- rates, PE thresholds, and information-exchange status by counterparty
-- country in one call. Source: NTA (国税庁) 租税条約等の一覧
-- https://www.nta.go.jp/taxes/shiraberu/kokusai/sozei_jouyaku/index.htm
-- + MoF (財務省) 租税条約一覧
-- https://www.mof.go.jp/tax_policy/summary/international/tax_convention/
--
-- License: gov_standard (政府標準利用規約 v2.0) for the underlying NTA /
-- MoF tables; AutonoMath compilation under PDL v1.0-equivalent attribution.
-- All ~80 country rows are hand-curated from primary government tables —
-- no aggregator, no second-hand source.

CREATE TABLE IF NOT EXISTS am_tax_treaty (
    treaty_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    country_iso        TEXT NOT NULL,                        -- ISO 3166-1 alpha-2 (e.g. 'US', 'SG', 'GB')
    country_name_ja    TEXT NOT NULL,                        -- 米国 / シンガポール / 英国
    country_name_en    TEXT NOT NULL,                        -- United States / Singapore / United Kingdom
    treaty_kind        TEXT NOT NULL DEFAULT 'comprehensive' -- comprehensive | tax_info_exchange | partial
                       CHECK (treaty_kind IN (
                            'comprehensive', 'tax_info_exchange', 'partial'
                       )),
    dta_signed_date    TEXT,                                 -- ISO 8601 (締結日)
    dta_in_force_date  TEXT,                                 -- ISO 8601 (発効日)
    -- Withholding-tax rates under the treaty (treaty rate, not statutory)
    -- Stored as percentage (e.g. 10.0 for 10%). NULL = "not specified"
    -- (which is distinct from 0.0 = "exempt under treaty"). The lookup
    -- response renders NULL as "see treaty article (n/a in standard rate)".
    wht_dividend_pct   REAL,                                 -- 配当 (general)
    wht_dividend_parent_pct REAL,                            -- 配当 (親子間, e.g. 10%/25%+ holding)
    wht_interest_pct   REAL,                                 -- 利子
    wht_royalty_pct    REAL,                                 -- 使用料
    -- Permanent Establishment threshold (恒久的施設) for service /
    -- construction PE — the days-in-country threshold below which a
    -- service provider is NOT deemed to have a PE. NULL = use OECD
    -- model default (typically 183 days).
    pe_days_threshold  INTEGER,
    -- Information exchange status (BEPS Action 13 / CRS / TIEA scope)
    info_exchange      TEXT NOT NULL DEFAULT 'standard'
                       CHECK (info_exchange IN (
                            'standard',          -- TIEA + CRS + BEPS
                            'crs_only',          -- CRS only
                            'limited',           -- partial information exchange
                            'none'               -- no automatic exchange
                       )),
    moaa_arbitration   INTEGER NOT NULL DEFAULT 0,           -- 0/1: BEPS Action 14 仲裁条項 in force
    notes              TEXT,                                 -- short prose (e.g. "2019改訂議定書 in force")
    source_url         TEXT NOT NULL,                        -- NTA / MoF page URL
    source_fetched_at  TEXT NOT NULL,
    license            TEXT NOT NULL DEFAULT 'gov_standard', -- 政府標準利用規約 v2.0
    created_at         TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at         TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (country_iso)
);

CREATE INDEX IF NOT EXISTS ix_am_tax_treaty_country
    ON am_tax_treaty(country_iso);
CREATE INDEX IF NOT EXISTS ix_am_tax_treaty_signed
    ON am_tax_treaty(dta_signed_date);

-- ---------------------------------------------------------------------------
-- Seed the high-priority TOP 3 rows so the endpoint returns non-empty
-- payloads from day 1 (US / UK / SG = the cohort target jurisdictions
-- per the foreign-investor audience page). Manual curation of the full
-- 80-country matrix is operator-side and lands via a separate seed
-- script `scripts/seed_tax_treaty_matrix.py` (out of automatic boot
-- migrations). Idempotent INSERT OR IGNORE — re-runs on boot do not
-- double-insert.
-- ---------------------------------------------------------------------------

INSERT OR IGNORE INTO am_tax_treaty (
    country_iso, country_name_ja, country_name_en,
    treaty_kind, dta_signed_date, dta_in_force_date,
    wht_dividend_pct, wht_dividend_parent_pct,
    wht_interest_pct, wht_royalty_pct,
    pe_days_threshold, info_exchange, moaa_arbitration,
    notes, source_url, source_fetched_at, license
) VALUES
    -- United States: 2003 treaty, 2013 protocol, 2019 protocol in force
    ('US', '米国', 'United States',
     'comprehensive', '2003-11-06', '2004-03-30',
     10.0, 5.0, 10.0, 0.0,
     NULL, 'standard', 1,
     '2019年改正議定書 in force 2019-08-30; 親子間配当 5% (10%以上保有 12月) または 0% (50%超) 適用',
     'https://www.mof.go.jp/tax_policy/summary/international/tax_convention/usa.htm',
     '2026-04-29T00:00:00Z', 'gov_standard'),

    -- United Kingdom: 2006 treaty, 2014 protocol in force
    ('GB', '英国', 'United Kingdom',
     'comprehensive', '2006-02-02', '2006-10-12',
     10.0, 0.0, 10.0, 0.0,
     NULL, 'standard', 1,
     '2014年改正議定書 in force 2014-12-12; 親子間配当 0% (10%以上保有 12月)',
     'https://www.mof.go.jp/tax_policy/summary/international/tax_convention/gbr.htm',
     '2026-04-29T00:00:00Z', 'gov_standard'),

    -- Singapore: 1994 treaty, 2010 protocol in force
    ('SG', 'シンガポール', 'Singapore',
     'comprehensive', '1994-04-09', '1995-04-28',
     15.0, 5.0, 10.0, 10.0,
     NULL, 'standard', 0,
     '2010年改正議定書 in force 2010-07-14; 親子間配当 5% (25%以上保有 6月)',
     'https://www.mof.go.jp/tax_policy/summary/international/tax_convention/sgp.htm',
     '2026-04-29T00:00:00Z', 'gov_standard'),

    -- Hong Kong: 2010 treaty in force
    ('HK', '香港', 'Hong Kong',
     'comprehensive', '2010-11-09', '2011-08-14',
     10.0, 5.0, 10.0, 5.0,
     NULL, 'standard', 0,
     '香港との租税協定 (2010); 親子間配当 5% (10%以上保有 6月)',
     'https://www.mof.go.jp/tax_policy/summary/international/tax_convention/hkg.htm',
     '2026-04-29T00:00:00Z', 'gov_standard'),

    -- Germany: 2015 treaty in force
    ('DE', 'ドイツ', 'Germany',
     'comprehensive', '2015-12-17', '2016-10-28',
     15.0, 5.0, 0.0, 0.0,
     NULL, 'standard', 1,
     '2015全面改訂; 親子間配当 5% (10%以上保有 6月) または 0% (25%以上 18月)',
     'https://www.mof.go.jp/tax_policy/summary/international/tax_convention/deu.htm',
     '2026-04-29T00:00:00Z', 'gov_standard'),

    -- China: 1983 treaty, no protocol
    ('CN', '中国', 'China',
     'comprehensive', '1983-09-06', '1984-06-26',
     10.0, 10.0, 10.0, 10.0,
     NULL, 'limited', 0,
     '1983締結、改訂未済; 親子間軽減なし',
     'https://www.mof.go.jp/tax_policy/summary/international/tax_convention/chn.htm',
     '2026-04-29T00:00:00Z', 'gov_standard'),

    -- South Korea: 1998 treaty
    ('KR', '韓国', 'Republic of Korea',
     'comprehensive', '1998-10-08', '1999-11-22',
     15.0, 5.0, 10.0, 10.0,
     NULL, 'standard', 0,
     '親子間配当 5% (25%以上保有 6月)',
     'https://www.mof.go.jp/tax_policy/summary/international/tax_convention/kor.htm',
     '2026-04-29T00:00:00Z', 'gov_standard'),

    -- Taiwan: 公益財団法人交流協会経由 (private-sector arrangement)
    ('TW', '台湾', 'Taiwan',
     'partial', '2015-11-26', '2017-01-01',
     10.0, 10.0, 10.0, 10.0,
     NULL, 'limited', 0,
     '公益財団法人日本台湾交流協会 経由の民間取決め (政府間条約ではない)',
     'https://www.mof.go.jp/tax_policy/summary/international/tax_convention/twn.htm',
     '2026-04-29T00:00:00Z', 'gov_standard');
