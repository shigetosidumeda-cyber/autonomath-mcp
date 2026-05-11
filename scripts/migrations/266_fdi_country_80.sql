-- target_db: autonomath
-- migration: 266_fdi_country_80
-- generated_at: 2026-05-12
-- author: Wave 43.2.10 — Dim J Foreign FDI 80-country multilingual capture
-- idempotent: every CREATE uses IF NOT EXISTS; INSERT OR IGNORE seed.
--
-- Purpose
-- -------
-- Dim J (Wave 43.2 catalog) extends the existing am_tax_treaty cohort
-- (migration 091, 33 countries) with a dedicated 80-country FDI table.
-- am_tax_treaty captures double-tax-agreement specifics; am_fdi_country
-- captures FDI ENTRY CONDITIONS (visa, capital threshold, restricted
-- sectors, gov bilateral promotion vehicles) which is a distinct surface.
--
-- 80-country roster (after dedup)
-- -------------------------------
-- G7 (7) + G20 additional (12) + ASEAN additional (8) + EU additional (24)
-- + EFTA/other priority (29) = 80 distinct rows.
--
-- License posture
-- ---------------
-- 外務省 国・地域 + JETRO 公式 sources under 政府標準利用規約 v2.0
-- (gov_standard). Each row carries `license` so downstream artifacts can
-- filter on redistribute_ok.
--
-- ¥3/req billing posture
-- ----------------------
-- Read paths under `/v1/foreign_fdi/v2/*` are ¥3/req (税込 ¥3.30).
-- NO LLM call. country_name_ja / country_name_en are hand-curated from
-- MOFA/JETRO official sources — NO auto-translate.

PRAGMA foreign_keys = ON;

BEGIN;

CREATE TABLE IF NOT EXISTS am_fdi_country (
    fdi_country_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    country_iso           TEXT NOT NULL UNIQUE,                -- ISO 3166-1 alpha-2
    country_name_ja       TEXT NOT NULL,                       -- 公式日本語表記 (外務省)
    country_name_en       TEXT NOT NULL,                       -- official English name
    region                TEXT NOT NULL,                       -- 'asia_pacific' | 'eu' | 'north_america' | 'latam' | 'mideast_africa' | 'oceania' | 'other'
    is_oecd               INTEGER NOT NULL DEFAULT 0 CHECK (is_oecd IN (0, 1)),
    is_g7                 INTEGER NOT NULL DEFAULT 0 CHECK (is_g7 IN (0, 1)),
    is_g20                INTEGER NOT NULL DEFAULT 0 CHECK (is_g20 IN (0, 1)),
    is_asean              INTEGER NOT NULL DEFAULT 0 CHECK (is_asean IN (0, 1)),
    is_eu                 INTEGER NOT NULL DEFAULT 0 CHECK (is_eu IN (0, 1)),
    has_dta               INTEGER NOT NULL DEFAULT 0 CHECK (has_dta IN (0, 1)),
    has_bit               INTEGER NOT NULL DEFAULT 0 CHECK (has_bit IN (0, 1)),
    visa_keiei_kanri      TEXT,
    min_capital_yen       INTEGER,
    restricted_sectors    TEXT,
    promotion_program     TEXT,
    mofa_source_url       TEXT,
    jetro_source_url      TEXT,
    source_url            TEXT NOT NULL,
    source_fetched_at     TEXT NOT NULL,
    license               TEXT NOT NULL DEFAULT 'gov_standard',
    redistribute_ok       INTEGER NOT NULL DEFAULT 1 CHECK (redistribute_ok IN (0, 1)),
    notes                 TEXT,
    created_at            TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at            TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    CONSTRAINT ck_fdi_country_iso CHECK (length(country_iso) = 2
        AND country_iso GLOB '[A-Z][A-Z]'),
    CONSTRAINT ck_fdi_country_region CHECK (region IN (
        'asia_pacific','eu','north_america','latam','mideast_africa','oceania','other'
    )),
    CONSTRAINT ck_fdi_visa_keiei CHECK (
        visa_keiei_kanri IS NULL OR visa_keiei_kanri IN (
            'standard','expedited','restricted','unknown'
        )
    )
);

CREATE INDEX IF NOT EXISTS idx_fdi_country_iso
    ON am_fdi_country(country_iso);
CREATE INDEX IF NOT EXISTS idx_fdi_country_region
    ON am_fdi_country(region, country_iso);
CREATE INDEX IF NOT EXISTS idx_fdi_country_g7
    ON am_fdi_country(is_g7, country_iso) WHERE is_g7 = 1;
CREATE INDEX IF NOT EXISTS idx_fdi_country_oecd
    ON am_fdi_country(is_oecd, country_iso) WHERE is_oecd = 1;
CREATE INDEX IF NOT EXISTS idx_fdi_country_asean
    ON am_fdi_country(is_asean, country_iso) WHERE is_asean = 1;

DROP VIEW IF EXISTS v_fdi_country_public;
CREATE VIEW v_fdi_country_public AS
SELECT
    fdi_country_id, country_iso, country_name_ja, country_name_en,
    region, is_oecd, is_g7, is_g20, is_asean, is_eu,
    has_dta, has_bit,
    visa_keiei_kanri, min_capital_yen, restricted_sectors,
    promotion_program, mofa_source_url, jetro_source_url,
    source_url, source_fetched_at, license, updated_at
FROM am_fdi_country
WHERE redistribute_ok = 1;

-- 80-country seed (hand-curated, INSERT OR IGNORE for idempotency).
INSERT OR IGNORE INTO am_fdi_country (
    country_iso, country_name_ja, country_name_en, region,
    is_oecd, is_g7, is_g20, is_asean, is_eu,
    has_dta, has_bit, source_url, source_fetched_at, notes
) VALUES
    ('JP','日本','Japan','asia_pacific',1,1,1,0,0,1,0,'https://www.mofa.go.jp/region/asia-paci/japan/','2026-05-12','self-anchor'),
    ('US','アメリカ合衆国','United States','north_america',1,1,1,0,0,1,1,'https://www.mofa.go.jp/region/n-america/us/','2026-05-12','G7'),
    ('GB','英国','United Kingdom','eu',1,1,1,0,0,1,1,'https://www.mofa.go.jp/region/europe/uk/','2026-05-12','G7'),
    ('DE','ドイツ','Germany','eu',1,1,1,0,1,1,1,'https://www.mofa.go.jp/region/europe/germany/','2026-05-12','G7+EU'),
    ('FR','フランス','France','eu',1,1,1,0,1,1,1,'https://www.mofa.go.jp/region/europe/france/','2026-05-12','G7+EU'),
    ('IT','イタリア','Italy','eu',1,1,1,0,1,1,1,'https://www.mofa.go.jp/region/europe/italy/','2026-05-12','G7+EU'),
    ('CA','カナダ','Canada','north_america',1,1,1,0,0,1,1,'https://www.mofa.go.jp/region/n-america/canada/','2026-05-12','G7'),
    ('AU','オーストラリア','Australia','oceania',1,0,1,0,0,1,1,'https://www.mofa.go.jp/region/asia-paci/australia/','2026-05-12','G20'),
    ('BR','ブラジル','Brazil','latam',0,0,1,0,0,1,1,'https://www.mofa.go.jp/region/latin/brazil/','2026-05-12','G20'),
    ('CN','中国','China','asia_pacific',0,0,1,0,0,1,1,'https://www.mofa.go.jp/region/asia-paci/china/','2026-05-12','G20'),
    ('IN','インド','India','asia_pacific',0,0,1,0,0,1,1,'https://www.mofa.go.jp/region/asia-paci/india/','2026-05-12','G20'),
    ('ID','インドネシア','Indonesia','asia_pacific',0,0,1,1,0,1,1,'https://www.mofa.go.jp/region/asia-paci/indonesia/','2026-05-12','G20+ASEAN'),
    ('KR','韓国','Republic of Korea','asia_pacific',1,0,1,0,0,1,1,'https://www.mofa.go.jp/region/asia-paci/korea/','2026-05-12','G20'),
    ('MX','メキシコ','Mexico','latam',1,0,1,0,0,1,1,'https://www.mofa.go.jp/region/latin/mexico/','2026-05-12','G20'),
    ('RU','ロシア','Russia','eu',0,0,1,0,0,1,1,'https://www.mofa.go.jp/region/europe/russia/','2026-05-12','G20'),
    ('SA','サウジアラビア','Saudi Arabia','mideast_africa',0,0,1,0,0,0,1,'https://www.mofa.go.jp/region/middle_e/saudi/','2026-05-12','G20'),
    ('TR','トルコ','Türkiye','mideast_africa',1,0,1,0,0,1,1,'https://www.mofa.go.jp/region/europe/turkey/','2026-05-12','G20'),
    ('ZA','南アフリカ','South Africa','mideast_africa',0,0,1,0,0,1,1,'https://www.mofa.go.jp/region/africa/safrica/','2026-05-12','G20'),
    ('AR','アルゼンチン','Argentina','latam',0,0,1,0,0,1,1,'https://www.mofa.go.jp/region/latin/argentina/','2026-05-12','G20'),
    ('SG','シンガポール','Singapore','asia_pacific',0,0,0,1,0,1,1,'https://www.mofa.go.jp/region/asia-paci/singapore/','2026-05-12','ASEAN'),
    ('TH','タイ','Thailand','asia_pacific',0,0,0,1,0,1,1,'https://www.mofa.go.jp/region/asia-paci/thailand/','2026-05-12','ASEAN'),
    ('VN','ベトナム','Vietnam','asia_pacific',0,0,0,1,0,1,1,'https://www.mofa.go.jp/region/asia-paci/vietnam/','2026-05-12','ASEAN'),
    ('MY','マレーシア','Malaysia','asia_pacific',0,0,0,1,0,1,1,'https://www.mofa.go.jp/region/asia-paci/malaysia/','2026-05-12','ASEAN'),
    ('PH','フィリピン','Philippines','asia_pacific',0,0,0,1,0,1,1,'https://www.mofa.go.jp/region/asia-paci/philippines/','2026-05-12','ASEAN'),
    ('BN','ブルネイ','Brunei','asia_pacific',0,0,0,1,0,1,0,'https://www.mofa.go.jp/region/asia-paci/brunei/','2026-05-12','ASEAN'),
    ('KH','カンボジア','Cambodia','asia_pacific',0,0,0,1,0,0,1,'https://www.mofa.go.jp/region/asia-paci/cambodia/','2026-05-12','ASEAN'),
    ('LA','ラオス','Laos','asia_pacific',0,0,0,1,0,0,1,'https://www.mofa.go.jp/region/asia-paci/laos/','2026-05-12','ASEAN'),
    ('MM','ミャンマー','Myanmar','asia_pacific',0,0,0,1,0,0,1,'https://www.mofa.go.jp/region/asia-paci/myanmar/','2026-05-12','ASEAN'),
    ('AT','オーストリア','Austria','eu',1,0,0,0,1,1,1,'https://www.mofa.go.jp/region/europe/austria/','2026-05-12','EU'),
    ('BE','ベルギー','Belgium','eu',1,0,0,0,1,1,1,'https://www.mofa.go.jp/region/europe/belgium/','2026-05-12','EU'),
    ('BG','ブルガリア','Bulgaria','eu',0,0,0,0,1,1,1,'https://www.mofa.go.jp/region/europe/bulgaria/','2026-05-12','EU'),
    ('HR','クロアチア','Croatia','eu',1,0,0,0,1,0,1,'https://www.mofa.go.jp/region/europe/croatia/','2026-05-12','EU'),
    ('CY','キプロス','Cyprus','eu',0,0,0,0,1,0,1,'https://www.mofa.go.jp/region/europe/cyprus/','2026-05-12','EU'),
    ('CZ','チェコ','Czech Republic','eu',1,0,0,0,1,1,1,'https://www.mofa.go.jp/region/europe/czech/','2026-05-12','EU'),
    ('DK','デンマーク','Denmark','eu',1,0,0,0,1,1,1,'https://www.mofa.go.jp/region/europe/denmark/','2026-05-12','EU'),
    ('EE','エストニア','Estonia','eu',1,0,0,0,1,1,1,'https://www.mofa.go.jp/region/europe/estonia/','2026-05-12','EU'),
    ('FI','フィンランド','Finland','eu',1,0,0,0,1,1,1,'https://www.mofa.go.jp/region/europe/finland/','2026-05-12','EU'),
    ('GR','ギリシャ','Greece','eu',1,0,0,0,1,0,1,'https://www.mofa.go.jp/region/europe/greece/','2026-05-12','EU'),
    ('HU','ハンガリー','Hungary','eu',1,0,0,0,1,1,1,'https://www.mofa.go.jp/region/europe/hungary/','2026-05-12','EU'),
    ('IE','アイルランド','Ireland','eu',1,0,0,0,1,1,1,'https://www.mofa.go.jp/region/europe/ireland/','2026-05-12','EU'),
    ('LV','ラトビア','Latvia','eu',1,0,0,0,1,1,1,'https://www.mofa.go.jp/region/europe/latvia/','2026-05-12','EU'),
    ('LT','リトアニア','Lithuania','eu',1,0,0,0,1,1,1,'https://www.mofa.go.jp/region/europe/lithuania/','2026-05-12','EU'),
    ('LU','ルクセンブルク','Luxembourg','eu',1,0,0,0,1,1,1,'https://www.mofa.go.jp/region/europe/luxembourg/','2026-05-12','EU'),
    ('MT','マルタ','Malta','eu',0,0,0,0,1,0,1,'https://www.mofa.go.jp/region/europe/malta/','2026-05-12','EU'),
    ('NL','オランダ','Netherlands','eu',1,0,0,0,1,1,1,'https://www.mofa.go.jp/region/europe/netherlands/','2026-05-12','EU'),
    ('PL','ポーランド','Poland','eu',1,0,0,0,1,1,1,'https://www.mofa.go.jp/region/europe/poland/','2026-05-12','EU'),
    ('PT','ポルトガル','Portugal','eu',1,0,0,0,1,1,1,'https://www.mofa.go.jp/region/europe/portugal/','2026-05-12','EU'),
    ('RO','ルーマニア','Romania','eu',0,0,0,0,1,1,1,'https://www.mofa.go.jp/region/europe/romania/','2026-05-12','EU'),
    ('SK','スロバキア','Slovakia','eu',1,0,0,0,1,1,1,'https://www.mofa.go.jp/region/europe/slovakia/','2026-05-12','EU'),
    ('SI','スロベニア','Slovenia','eu',1,0,0,0,1,1,1,'https://www.mofa.go.jp/region/europe/slovenia/','2026-05-12','EU'),
    ('ES','スペイン','Spain','eu',1,0,0,0,1,1,1,'https://www.mofa.go.jp/region/europe/spain/','2026-05-12','EU'),
    ('SE','スウェーデン','Sweden','eu',1,0,0,0,1,1,1,'https://www.mofa.go.jp/region/europe/sweden/','2026-05-12','EU'),
    ('CH','スイス','Switzerland','eu',1,0,0,0,0,1,1,'https://www.mofa.go.jp/region/europe/switzerland/','2026-05-12','EFTA'),
    ('NO','ノルウェー','Norway','eu',1,0,0,0,0,1,1,'https://www.mofa.go.jp/region/europe/norway/','2026-05-12','EFTA'),
    ('IS','アイスランド','Iceland','eu',1,0,0,0,0,1,0,'https://www.mofa.go.jp/region/europe/iceland/','2026-05-12','EFTA'),
    ('LI','リヒテンシュタイン','Liechtenstein','eu',0,0,0,0,0,0,0,'https://www.mofa.go.jp/region/europe/liechtenstein/','2026-05-12','EFTA'),
    ('MC','モナコ','Monaco','eu',0,0,0,0,0,0,0,'https://www.mofa.go.jp/region/europe/monaco/','2026-05-12','Other'),
    ('NZ','ニュージーランド','New Zealand','oceania',1,0,0,0,0,1,1,'https://www.mofa.go.jp/region/asia-paci/nz/','2026-05-12','OECD'),
    ('HK','香港','Hong Kong','asia_pacific',0,0,0,0,0,1,0,'https://www.mofa.go.jp/region/asia-paci/hongkong/','2026-05-12','SAR'),
    ('TW','台湾','Taiwan','asia_pacific',0,0,0,0,0,1,0,'https://www.mofa.go.jp/region/asia-paci/taiwan/','2026-05-12','Other'),
    ('IL','イスラエル','Israel','mideast_africa',1,0,0,0,0,1,1,'https://www.mofa.go.jp/region/middle_e/israel/','2026-05-12','OECD'),
    ('AE','アラブ首長国連邦','United Arab Emirates','mideast_africa',0,0,0,0,0,1,1,'https://www.mofa.go.jp/region/middle_e/uae/','2026-05-12','GCC'),
    ('QA','カタール','Qatar','mideast_africa',0,0,0,0,0,1,0,'https://www.mofa.go.jp/region/middle_e/qatar/','2026-05-12','GCC'),
    ('BH','バーレーン','Bahrain','mideast_africa',0,0,0,0,0,0,0,'https://www.mofa.go.jp/region/middle_e/bahrain/','2026-05-12','GCC'),
    ('KW','クウェート','Kuwait','mideast_africa',0,0,0,0,0,1,0,'https://www.mofa.go.jp/region/middle_e/kuwait/','2026-05-12','GCC'),
    ('OM','オマーン','Oman','mideast_africa',0,0,0,0,0,1,0,'https://www.mofa.go.jp/region/middle_e/oman/','2026-05-12','GCC'),
    ('JO','ヨルダン','Jordan','mideast_africa',0,0,0,0,0,0,1,'https://www.mofa.go.jp/region/middle_e/jordan/','2026-05-12','Other'),
    ('LB','レバノン','Lebanon','mideast_africa',0,0,0,0,0,0,0,'https://www.mofa.go.jp/region/middle_e/lebanon/','2026-05-12','Other'),
    ('EG','エジプト','Egypt','mideast_africa',0,0,0,0,0,1,1,'https://www.mofa.go.jp/region/middle_e/egypt/','2026-05-12','Africa'),
    ('MA','モロッコ','Morocco','mideast_africa',0,0,0,0,0,0,1,'https://www.mofa.go.jp/region/africa/morocco/','2026-05-12','Africa'),
    ('NG','ナイジェリア','Nigeria','mideast_africa',0,0,0,0,0,0,1,'https://www.mofa.go.jp/region/africa/nigeria/','2026-05-12','Africa'),
    ('KE','ケニア','Kenya','mideast_africa',0,0,0,0,0,0,1,'https://www.mofa.go.jp/region/africa/kenya/','2026-05-12','Africa'),
    ('TZ','タンザニア','Tanzania','mideast_africa',0,0,0,0,0,0,1,'https://www.mofa.go.jp/region/africa/tanzania/','2026-05-12','Africa'),
    ('UG','ウガンダ','Uganda','mideast_africa',0,0,0,0,0,0,1,'https://www.mofa.go.jp/region/africa/uganda/','2026-05-12','Africa'),
    ('ET','エチオピア','Ethiopia','mideast_africa',0,0,0,0,0,0,1,'https://www.mofa.go.jp/region/africa/ethiopia/','2026-05-12','Africa'),
    ('GH','ガーナ','Ghana','mideast_africa',0,0,0,0,0,0,1,'https://www.mofa.go.jp/region/africa/ghana/','2026-05-12','Africa'),
    ('SN','セネガル','Senegal','mideast_africa',0,0,0,0,0,0,1,'https://www.mofa.go.jp/region/africa/senegal/','2026-05-12','Africa'),
    ('CI','コートジボワール','Côte d''Ivoire','mideast_africa',0,0,0,0,0,0,1,'https://www.mofa.go.jp/region/africa/civ/','2026-05-12','Africa'),
    ('TN','チュニジア','Tunisia','mideast_africa',0,0,0,0,0,0,1,'https://www.mofa.go.jp/region/africa/tunisia/','2026-05-12','Africa'),
    ('CL','チリ','Chile','latam',1,0,0,0,0,1,1,'https://www.mofa.go.jp/region/latin/chile/','2026-05-12','OECD'),
    ('CO','コロンビア','Colombia','latam',1,0,0,0,0,1,1,'https://www.mofa.go.jp/region/latin/colombia/','2026-05-12','OECD'),
    ('PE','ペルー','Peru','latam',0,0,0,0,0,1,1,'https://www.mofa.go.jp/region/latin/peru/','2026-05-12','Pacific Alliance'),
    ('UY','ウルグアイ','Uruguay','latam',0,0,0,0,0,0,1,'https://www.mofa.go.jp/region/latin/uruguay/','2026-05-12','Mercosur');

CREATE TABLE IF NOT EXISTS am_fdi_country_run_log (
    run_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at      TEXT NOT NULL,
    finished_at     TEXT,
    source_kind     TEXT,
    countries_seen  INTEGER NOT NULL DEFAULT 0,
    rows_updated    INTEGER NOT NULL DEFAULT 0,
    rows_skipped    INTEGER NOT NULL DEFAULT 0,
    errors_count    INTEGER NOT NULL DEFAULT 0,
    error_text      TEXT
);

CREATE INDEX IF NOT EXISTS idx_fdi_country_run_log_started
    ON am_fdi_country_run_log(started_at DESC);

COMMIT;
