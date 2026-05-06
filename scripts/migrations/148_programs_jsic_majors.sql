-- target_db: jpintel
-- migration 148_programs_jsic_majors
--   programs に JSON 配列カラム jsic_majors を追加し、
--   industry pack の正確な multi-tag filter を可能にする。
--
-- Why this exists:
--   wave24_113a で programs.jsic_major (TEXT, 単数) を追加済だが、
--   現実の補助金は複数業種を横断するケースが多い (例: 「ものづくり補助金」
--   = 製造業 E + 情報通信業 G + サービス業 R)。単数列だと top-1 しか
--   表現できず、industry pack の "JSIC X に該当する全 program" が
--   keyword fence の精度に依存し続ける。
--
--   `auto_tag_program_jsic.py` (この migration の伴侶) が
--   am_industry_jsic (50 行) の jsic_name_ja + 派生 keyword を辞書化し、
--   各 program の primary_name + funding_purpose_json + target_types_json +
--   crop_categories_json + enriched_json text body に keyword match を行い、
--   top-2 JSIC major を JSON array (例: '["E","G"]') として bulk UPDATE する。
--
-- Schema additions (ALTER):
--   * programs.jsic_majors TEXT  -- JSON array of JSIC major codes (1-2 件)
--
-- Index posture:
--   jsic_majors は JSON array なので等値 index は意味を持たない (検索は
--   `LIKE '%"E"%'` で走らせる)。それでも jsic_majors IS NOT NULL の
--   partial index を貼っておけば「auto-tag 済 program 全件」を一発で
--   walk できる。
--
-- Idempotency:
--   ALTER TABLE ADD COLUMN は再実行で "duplicate column name" を投げる
--   が、entrypoint.sh / migrate.py の schema_migrations テーブルが
--   ファイル名 hash を記録しているので 1 回しか走らない。CREATE INDEX
--   は IF NOT EXISTS で安全。
--
-- DOWN:
--   See companion `148_programs_jsic_majors_rollback.sql`.

PRAGMA foreign_keys = ON;

ALTER TABLE programs ADD COLUMN jsic_majors TEXT;

CREATE INDEX IF NOT EXISTS ix_programs_jsic_majors
    ON programs(jsic_majors) WHERE jsic_majors IS NOT NULL;
