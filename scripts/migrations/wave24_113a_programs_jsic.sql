-- target_db: jpintel
-- migration wave24_113a_programs_jsic (MASTER_PLAN_v1 章 10.1.d —
-- programs 表 + houjin_master 表に JSIC 業種コード列を追加)
--
-- Why this exists:
--   `find_programs_by_jsic` (#109), `forecast_enforcement_risk` (#100),
--   `get_industry_program_density` (#117), `pack_construction` /
--   `pack_manufacturing` / `pack_real_estate` (Wave 23) all need
--   programs filterable by JSIC major (A-T) / middle (2 桁) / minor
--   (3 桁). Today the program-side filter is ad-hoc keyword union
--   which is brittle (see Wave 23 industry packs file for the
--   keyword fence). A first-class column lets us pre-join to
--   `am_industry_jsic` (50 rows, autonomath) and skip keyword
--   guesswork.
--
--   Same column shape on `houjin_master` so 法人 360° tools can
--   filter / cross-reference by JSIC consistently.
--
-- Schema additions (ALTER):
--   * programs.jsic_major  TEXT  CHECK (jsic_major IS NULL OR
--                                       jsic_major IN ('A','B','C','D','E','F','G','H','I',
--                                                      'J','K','L','M','N','O','P','Q','R','S','T'))
--   * programs.jsic_middle TEXT  CHECK (jsic_middle IS NULL OR
--                                       length(jsic_middle) = 2)
--   * programs.jsic_minor  TEXT  CHECK (jsic_minor IS NULL OR
--                                       length(jsic_minor) = 3)
--   * programs.jsic_assigned_at TEXT
--   * programs.jsic_assigned_method TEXT  ('manual'|'keyword'|'classifier')
--
--   Same 5 columns added to `houjin_master`.
--
-- Index posture:
--   Hot path: filter by jsic_major. Composite index (jsic_major, tier)
--   on programs makes "all tier S/A programs in JSIC E" cheap.
--
-- CHECK on ALTER ADD COLUMN is supported as of SQLite 3.37 (Fly is
-- on 3.46+, verified 2026-04). The constraint applies to all
-- existing rows lazily — INSERT / UPDATE will trip the check, but
-- the existing NULLs satisfy it (CHECK includes the NULL clause
-- explicitly).
--
-- Idempotency:
--   ALTER TABLE ADD COLUMN raises "duplicate column name" on
--   re-run; entrypoint.sh §4 swallows that case (lines 420-428)
--   when the message is exclusively "duplicate column". The CHECK
--   clause does NOT cause a re-add to succeed (SQLite enforces the
--   column-name uniqueness first), so the swallow path lands
--   correctly. CREATE INDEX uses IF NOT EXISTS.
--
-- DOWN:
--   See companion `wave24_113a_programs_jsic_rollback.sql`.

PRAGMA foreign_keys = ON;

-- programs JSIC columns.
ALTER TABLE programs ADD COLUMN jsic_major TEXT
    CHECK (jsic_major IS NULL OR jsic_major IN (
        'A','B','C','D','E','F','G','H','I','J',
        'K','L','M','N','O','P','Q','R','S','T'
    ));
ALTER TABLE programs ADD COLUMN jsic_middle TEXT
    CHECK (jsic_middle IS NULL OR length(jsic_middle) = 2);
ALTER TABLE programs ADD COLUMN jsic_minor TEXT
    CHECK (jsic_minor IS NULL OR length(jsic_minor) = 3);
ALTER TABLE programs ADD COLUMN jsic_assigned_at TEXT;
ALTER TABLE programs ADD COLUMN jsic_assigned_method TEXT
    CHECK (jsic_assigned_method IS NULL OR jsic_assigned_method IN
           ('manual','keyword','classifier'));

-- programs hot-path indexes.
CREATE INDEX IF NOT EXISTS idx_programs_jsic_major_tier
    ON programs(jsic_major, tier) WHERE jsic_major IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_programs_jsic_middle
    ON programs(jsic_middle) WHERE jsic_middle IS NOT NULL;

-- houjin_master JSIC columns. Same shape as programs.
ALTER TABLE houjin_master ADD COLUMN jsic_major TEXT
    CHECK (jsic_major IS NULL OR jsic_major IN (
        'A','B','C','D','E','F','G','H','I','J',
        'K','L','M','N','O','P','Q','R','S','T'
    ));
ALTER TABLE houjin_master ADD COLUMN jsic_middle TEXT
    CHECK (jsic_middle IS NULL OR length(jsic_middle) = 2);
ALTER TABLE houjin_master ADD COLUMN jsic_minor TEXT
    CHECK (jsic_minor IS NULL OR length(jsic_minor) = 3);
ALTER TABLE houjin_master ADD COLUMN jsic_assigned_at TEXT;
ALTER TABLE houjin_master ADD COLUMN jsic_assigned_method TEXT
    CHECK (jsic_assigned_method IS NULL OR jsic_assigned_method IN
           ('manual','keyword','classifier'));

CREATE INDEX IF NOT EXISTS idx_houjin_master_jsic_major
    ON houjin_master(jsic_major) WHERE jsic_major IS NOT NULL;
