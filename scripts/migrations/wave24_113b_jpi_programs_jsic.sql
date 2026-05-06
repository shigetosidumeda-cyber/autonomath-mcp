-- target_db: autonomath
-- migration wave24_113b_jpi_programs_jsic (MASTER_PLAN_v1 章 10.1.d —
-- jpi_programs (autonomath 側ミラー) に JSIC 業種コード列を追加)
--
-- Why this exists:
--   `jpi_programs` is the autonomath-side mirror of `programs`
--   (78 jpi_* mirror tables landed in migration 032). The mirror
--   must carry the same jsic_* columns so the autonomath cross-DB
--   tools can filter without an ATTACH.
--
--   Companion to wave24_113a_programs_jsic.sql which adds the
--   identical columns on the jpintel side. The two files are
--   intentionally split so each can declare a single
--   `-- target_db:` marker.
--
-- Schema additions (ALTER, autonomath jpi_programs):
--   * jpi_programs.jsic_major TEXT             — 'A'..'T'
--   * jpi_programs.jsic_middle TEXT            — 2-char
--   * jpi_programs.jsic_minor TEXT             — 3-char
--   * jpi_programs.jsic_assigned_at TEXT
--   * jpi_programs.jsic_assigned_method TEXT   — manual|keyword|classifier
--
-- CHECK on ALTER ADD COLUMN is SQLite 3.37+; Fly 3.46+ confirmed.
--
-- Sync:
--   The jpi_programs mirror is rebuilt by `scripts/etl/mirror_jpi.py`
--   (manual run as needed). After rolling out wave24_113a, the
--   next mirror pass copies the new jsic_* columns into autonomath.
--
-- Idempotency:
--   ALTER ADD COLUMN raises "duplicate column name" on re-run;
--   entrypoint.sh §4 swallows that case when the message is
--   exclusively "duplicate column" (lines 420-428).
--
-- DOWN:
--   See companion `wave24_113b_jpi_programs_jsic_rollback.sql`.

PRAGMA foreign_keys = ON;

ALTER TABLE jpi_programs ADD COLUMN jsic_major TEXT
    CHECK (jsic_major IS NULL OR jsic_major IN (
        'A','B','C','D','E','F','G','H','I','J',
        'K','L','M','N','O','P','Q','R','S','T'
    ));
ALTER TABLE jpi_programs ADD COLUMN jsic_middle TEXT
    CHECK (jsic_middle IS NULL OR length(jsic_middle) = 2);
ALTER TABLE jpi_programs ADD COLUMN jsic_minor TEXT
    CHECK (jsic_minor IS NULL OR length(jsic_minor) = 3);
ALTER TABLE jpi_programs ADD COLUMN jsic_assigned_at TEXT;
ALTER TABLE jpi_programs ADD COLUMN jsic_assigned_method TEXT
    CHECK (jsic_assigned_method IS NULL OR jsic_assigned_method IN
           ('manual','keyword','classifier'));

CREATE INDEX IF NOT EXISTS idx_jpi_programs_jsic_major_tier
    ON jpi_programs(jsic_major, tier) WHERE jsic_major IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_jpi_programs_jsic_middle
    ON jpi_programs(jsic_middle) WHERE jsic_middle IS NOT NULL;
