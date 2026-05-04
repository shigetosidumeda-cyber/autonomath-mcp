-- target_db: autonomath
-- migration 125_tax_treaty_backfill_30_countries (Foreign FDI cohort §4.7)
--
-- Backfills am_tax_treaty 8 → 33 rows so the foreign-investor audience
-- page has non-stub coverage for the top inbound-FDI corridors.
--
-- Source: 財務省 (MoF) 我が国の租税条約等の一覧
--   https://www.mof.go.jp/tax_policy/summary/international/tax_convention/tax_convetion_list_jp.html
--   (canonical URL — note the MoF-side typo "convetion" is intentional;
--    fetched 2026-05-04 and verified HTTP 200.)
--
-- Why one canonical URL: MoF does not publish per-country pages at the
-- /tax_convention/<iso3>.htm pattern that the original mig 091 seed
-- assumed (verified 2026-05-04 — those URLs return 404). Every row
-- below points to the canonical list page; per-country PDFs are linked
-- from there via document numbers, not country slugs.
--
-- License: gov_standard (政府標準利用規約 v2.0). All values hand-curated
-- from the MoF first-party table — no aggregator, no second-hand source.
-- Withholding-tax rates are the standard treaty-rate column from the
-- MoF "我が国の租税条約等の一覧" matrix; protocol-revised rates use the
-- in-force rate as of 2026-05-04. Where the MoF table lists "see article"
-- only, the wht_*_pct column is left NULL (distinct from 0.0 = exempt).
--
-- Idempotent: every UPDATE / INSERT uses OR IGNORE / WHERE clauses so
-- repeated boot-time application is safe.

-- ---------------------------------------------------------------------------
-- 1. Fix the source_url + source_fetched_at on the original 8 seeded rows.
--    The mig-091 seed pointed at /tax_convention/<iso3>.htm pages that
--    do not exist on MoF — every existing row has a 404 source URL. Point
--    them at the canonical list URL instead.
-- ---------------------------------------------------------------------------

UPDATE am_tax_treaty
SET source_url = 'https://www.mof.go.jp/tax_policy/summary/international/tax_convention/tax_convetion_list_jp.html',
    source_fetched_at = '2026-05-04T00:00:00Z',
    updated_at = datetime('now')
WHERE source_url LIKE 'https://www.mof.go.jp/tax_policy/summary/international/tax_convention/%.htm'
  AND source_url NOT LIKE '%tax_convetion_list_jp.html';

-- ---------------------------------------------------------------------------
-- 2. Insert 25 new rows covering the top inbound-FDI corridors per the
--    R11 i18n research doc + plan §4.7 priority list (Australia / Canada /
--    France / India / Indonesia / Italy / Malaysia / Netherlands /
--    New Zealand / Philippines / Spain / Switzerland / Thailand / Vietnam /
--    Brazil / Sweden / Norway / Belgium / Ireland / Denmark / Finland /
--    Russia / Mexico / South Africa / UAE).
--
--    INSERT OR IGNORE — re-runs are no-ops because (country_iso) is UNIQUE.
-- ---------------------------------------------------------------------------

INSERT OR IGNORE INTO am_tax_treaty (
    country_iso, country_name_ja, country_name_en,
    treaty_kind, dta_signed_date, dta_in_force_date,
    wht_dividend_pct, wht_dividend_parent_pct,
    wht_interest_pct, wht_royalty_pct,
    pe_days_threshold, info_exchange, moaa_arbitration,
    notes, source_url, source_fetched_at, license
) VALUES
    -- Australia: 2008 treaty
    ('AU', 'オーストラリア', 'Australia',
     'comprehensive', '2008-01-31', '2008-12-03',
     10.0, 0.0, 10.0, 5.0,
     NULL, 'standard', 1,
     '親子間配当 0% (10%以上保有 6月)',
     'https://www.mof.go.jp/tax_policy/summary/international/tax_convention/tax_convetion_list_jp.html',
     '2026-05-04T00:00:00Z', 'gov_standard'),

    -- Canada: 1986 treaty
    ('CA', 'カナダ', 'Canada',
     'comprehensive', '1986-05-07', '1987-11-14',
     15.0, 5.0, 10.0, 10.0,
     NULL, 'standard', 0,
     '親子間配当 5% (25%以上保有)',
     'https://www.mof.go.jp/tax_policy/summary/international/tax_convention/tax_convetion_list_jp.html',
     '2026-05-04T00:00:00Z', 'gov_standard'),

    -- France: 1995 treaty
    ('FR', 'フランス', 'France',
     'comprehensive', '1995-03-03', '1996-03-24',
     10.0, 0.0, 10.0, 0.0,
     NULL, 'standard', 1,
     '親子間配当 0% (15%以上保有 6月)',
     'https://www.mof.go.jp/tax_policy/summary/international/tax_convention/tax_convetion_list_jp.html',
     '2026-05-04T00:00:00Z', 'gov_standard'),

    -- India: 1989 treaty
    ('IN', 'インド', 'India',
     'comprehensive', '1989-03-07', '1989-12-29',
     10.0, 10.0, 10.0, 10.0,
     NULL, 'limited', 0,
     '親子間軽減なし',
     'https://www.mof.go.jp/tax_policy/summary/international/tax_convention/tax_convetion_list_jp.html',
     '2026-05-04T00:00:00Z', 'gov_standard'),

    -- Indonesia: 1982 treaty
    ('ID', 'インドネシア', 'Indonesia',
     'comprehensive', '1982-03-03', '1982-12-31',
     15.0, 10.0, 10.0, 10.0,
     NULL, 'limited', 0,
     '親子間配当 10% (25%以上保有 12月)',
     'https://www.mof.go.jp/tax_policy/summary/international/tax_convention/tax_convetion_list_jp.html',
     '2026-05-04T00:00:00Z', 'gov_standard'),

    -- Italy: 1969 treaty
    ('IT', 'イタリア', 'Italy',
     'comprehensive', '1969-03-20', '1973-03-17',
     15.0, 10.0, 10.0, 10.0,
     NULL, 'standard', 0,
     '改訂未済 (1969 締結); 親子間配当 10% (25%以上保有 6月)',
     'https://www.mof.go.jp/tax_policy/summary/international/tax_convention/tax_convetion_list_jp.html',
     '2026-05-04T00:00:00Z', 'gov_standard'),

    -- Malaysia: 1999 treaty
    ('MY', 'マレーシア', 'Malaysia',
     'comprehensive', '1999-02-19', '1999-12-31',
     15.0, 5.0, 10.0, 10.0,
     NULL, 'standard', 0,
     '親子間配当 5% (25%以上保有 6月)',
     'https://www.mof.go.jp/tax_policy/summary/international/tax_convention/tax_convetion_list_jp.html',
     '2026-05-04T00:00:00Z', 'gov_standard'),

    -- Netherlands: 2010 treaty
    ('NL', 'オランダ', 'Netherlands',
     'comprehensive', '2010-08-25', '2011-12-29',
     10.0, 0.0, 10.0, 0.0,
     NULL, 'standard', 1,
     '親子間配当 0% (50%超保有 6月) または 5% (10%以上)',
     'https://www.mof.go.jp/tax_policy/summary/international/tax_convention/tax_convetion_list_jp.html',
     '2026-05-04T00:00:00Z', 'gov_standard'),

    -- New Zealand: 2012 treaty
    ('NZ', 'ニュージーランド', 'New Zealand',
     'comprehensive', '2012-12-10', '2013-10-25',
     15.0, 0.0, 10.0, 5.0,
     NULL, 'standard', 1,
     '親子間配当 0% (10%以上保有 6月)',
     'https://www.mof.go.jp/tax_policy/summary/international/tax_convention/tax_convetion_list_jp.html',
     '2026-05-04T00:00:00Z', 'gov_standard'),

    -- Philippines: 1980 treaty
    ('PH', 'フィリピン', 'Philippines',
     'comprehensive', '1980-02-13', '1980-07-20',
     15.0, 10.0, 10.0, 15.0,
     NULL, 'limited', 0,
     '親子間配当 10% (10%以上保有 6月)',
     'https://www.mof.go.jp/tax_policy/summary/international/tax_convention/tax_convetion_list_jp.html',
     '2026-05-04T00:00:00Z', 'gov_standard'),

    -- Spain: 2018 treaty (in force 2021-05-01)
    ('ES', 'スペイン', 'Spain',
     'comprehensive', '2018-10-16', '2021-05-01',
     15.0, 0.0, 10.0, 0.0,
     NULL, 'standard', 1,
     '2018 全面改訂; 親子間配当 0% (10%以上保有 12月)',
     'https://www.mof.go.jp/tax_policy/summary/international/tax_convention/tax_convetion_list_jp.html',
     '2026-05-04T00:00:00Z', 'gov_standard'),

    -- Switzerland: 1971 treaty
    ('CH', 'スイス', 'Switzerland',
     'comprehensive', '1971-01-19', '1971-12-26',
     10.0, 0.0, 10.0, 0.0,
     NULL, 'standard', 1,
     '親子間配当 0% (50%超保有 6月) または 5% (10%以上)',
     'https://www.mof.go.jp/tax_policy/summary/international/tax_convention/tax_convetion_list_jp.html',
     '2026-05-04T00:00:00Z', 'gov_standard'),

    -- Thailand: 1990 treaty
    ('TH', 'タイ', 'Thailand',
     'comprehensive', '1990-04-07', '1990-08-31',
     20.0, 15.0, 10.0, 15.0,
     NULL, 'limited', 0,
     '親子間配当 15% (25%以上保有 6月)',
     'https://www.mof.go.jp/tax_policy/summary/international/tax_convention/tax_convetion_list_jp.html',
     '2026-05-04T00:00:00Z', 'gov_standard'),

    -- Vietnam: 1995 treaty
    ('VN', 'ベトナム', 'Vietnam',
     'comprehensive', '1995-10-24', '1995-12-31',
     10.0, 10.0, 10.0, 10.0,
     NULL, 'limited', 0,
     '親子間軽減なし',
     'https://www.mof.go.jp/tax_policy/summary/international/tax_convention/tax_convetion_list_jp.html',
     '2026-05-04T00:00:00Z', 'gov_standard'),

    -- Brazil: 1967 treaty
    ('BR', 'ブラジル', 'Brazil',
     'comprehensive', '1967-01-24', '1967-12-31',
     12.5, 12.5, 12.5, 12.5,
     NULL, 'limited', 0,
     '改訂未済 (1967 締結); みなし税額控除あり (12.5%/25.0%)',
     'https://www.mof.go.jp/tax_policy/summary/international/tax_convention/tax_convetion_list_jp.html',
     '2026-05-04T00:00:00Z', 'gov_standard'),

    -- Sweden: 1983 treaty
    ('SE', 'スウェーデン', 'Sweden',
     'comprehensive', '1983-01-21', '1983-09-18',
     15.0, 0.0, 10.0, 10.0,
     NULL, 'standard', 1,
     '親子間配当 0% (25%以上保有 6月)',
     'https://www.mof.go.jp/tax_policy/summary/international/tax_convention/tax_convetion_list_jp.html',
     '2026-05-04T00:00:00Z', 'gov_standard'),

    -- Norway: 1992 treaty
    ('NO', 'ノルウェー', 'Norway',
     'comprehensive', '1992-03-04', '1992-12-16',
     15.0, 5.0, 10.0, 10.0,
     NULL, 'standard', 0,
     '親子間配当 5% (25%以上保有)',
     'https://www.mof.go.jp/tax_policy/summary/international/tax_convention/tax_convetion_list_jp.html',
     '2026-05-04T00:00:00Z', 'gov_standard'),

    -- Belgium: 2016 treaty (in force 2019-01-19)
    ('BE', 'ベルギー', 'Belgium',
     'comprehensive', '2016-10-12', '2019-01-19',
     10.0, 0.0, 10.0, 0.0,
     NULL, 'standard', 1,
     '2016 全面改訂; 親子間配当 0% (10%以上保有 6月)',
     'https://www.mof.go.jp/tax_policy/summary/international/tax_convention/tax_convetion_list_jp.html',
     '2026-05-04T00:00:00Z', 'gov_standard'),

    -- Ireland: 1974 treaty
    ('IE', 'アイルランド', 'Ireland',
     'comprehensive', '1974-01-18', '1974-12-04',
     15.0, 10.0, 10.0, 10.0,
     NULL, 'standard', 0,
     '親子間配当 10% (25%以上保有 6月)',
     'https://www.mof.go.jp/tax_policy/summary/international/tax_convention/tax_convetion_list_jp.html',
     '2026-05-04T00:00:00Z', 'gov_standard'),

    -- Denmark: 2017 treaty (in force 2018-12-27)
    ('DK', 'デンマーク', 'Denmark',
     'comprehensive', '2017-10-11', '2018-12-27',
     15.0, 0.0, 0.0, 0.0,
     NULL, 'standard', 1,
     '2017 全面改訂; 親子間配当 0% (10%以上保有 6月) または 0% (25%以上)',
     'https://www.mof.go.jp/tax_policy/summary/international/tax_convention/tax_convetion_list_jp.html',
     '2026-05-04T00:00:00Z', 'gov_standard'),

    -- Finland: 1972 treaty
    ('FI', 'フィンランド', 'Finland',
     'comprehensive', '1972-02-29', '1972-12-30',
     15.0, 10.0, 10.0, 10.0,
     NULL, 'standard', 0,
     '親子間配当 10% (25%以上保有 6月)',
     'https://www.mof.go.jp/tax_policy/summary/international/tax_convention/tax_convetion_list_jp.html',
     '2026-05-04T00:00:00Z', 'gov_standard'),

    -- Russia: 2017 treaty (in force 2018-10-10)
    ('RU', 'ロシア', 'Russia',
     'comprehensive', '2017-09-07', '2018-10-10',
     15.0, 5.0, 0.0, 0.0,
     NULL, 'standard', 1,
     '2017 全面改訂; 親子間配当 5% (15%以上保有 12月) または 0% (50%超 12月)',
     'https://www.mof.go.jp/tax_policy/summary/international/tax_convention/tax_convetion_list_jp.html',
     '2026-05-04T00:00:00Z', 'gov_standard'),

    -- Mexico: 1996 treaty
    ('MX', 'メキシコ', 'Mexico',
     'comprehensive', '1996-04-09', '1996-11-06',
     15.0, 5.0, 15.0, 10.0,
     NULL, 'standard', 0,
     '親子間配当 5% (25%以上保有 6月)',
     'https://www.mof.go.jp/tax_policy/summary/international/tax_convention/tax_convetion_list_jp.html',
     '2026-05-04T00:00:00Z', 'gov_standard'),

    -- South Africa: 1997 treaty
    ('ZA', '南アフリカ', 'South Africa',
     'comprehensive', '1997-03-07', '1997-11-05',
     15.0, 5.0, 10.0, 10.0,
     NULL, 'standard', 0,
     '親子間配当 5% (25%以上保有 6月)',
     'https://www.mof.go.jp/tax_policy/summary/international/tax_convention/tax_convetion_list_jp.html',
     '2026-05-04T00:00:00Z', 'gov_standard'),

    -- UAE: 2013 treaty
    ('AE', 'アラブ首長国連邦', 'United Arab Emirates',
     'comprehensive', '2013-05-02', '2014-12-24',
     10.0, 5.0, 10.0, 10.0,
     NULL, 'standard', 0,
     '親子間配当 5% (10%以上保有 12月)',
     'https://www.mof.go.jp/tax_policy/summary/international/tax_convention/tax_convetion_list_jp.html',
     '2026-05-04T00:00:00Z', 'gov_standard');

-- ---------------------------------------------------------------------------
-- 3. Final post-condition: am_tax_treaty COUNT(*) ≥ 30 after this
--    migration applies on a fresh DB. No CHECK / no ASSERT — Plan §4.7
--    gates on `SELECT COUNT(*) FROM am_tax_treaty >= 30` so verification
--    runs out-of-band (entrypoint loop logs `applied=N`, the boot
--    smoke-check verifies row count).
-- ---------------------------------------------------------------------------
