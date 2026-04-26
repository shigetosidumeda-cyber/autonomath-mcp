-- target_db: autonomath
-- migration 049: provenance 層強化 (license + fact source + feedback entity link)
--
-- 目的:
--   1. am_source.license — 出典の利用許諾を分類 (PDL/CC-BY/政府標準/etc.)
--   2. am_entity_facts.source_id — fact 単位で am_source への正規 FK
--      (既存 source_url は free-text、URL 表記揺れで join 不可)
--   3. jpi_feedback.entity_canonical_id — feedback を am_entities へ束ねる
--
-- SQLite ALTER 制約:
--   * CHECK 制約は ALTER TABLE で追加不可 → BEFORE INSERT/UPDATE trigger で代替
--   * UNIQUE も同様 → 必要なら CREATE UNIQUE INDEX で代替 (本 migration では不要)
--   * NOT NULL も追加不可 → 全行 NULL 開始でアプリ側 backfill (scripts/fill_license.py)
--
-- 実 schema 確認 (2026-04-25):
--   am_source PK = id INTEGER (NOT source_id) → FK は am_source(id)
--   am_entity_facts には既に source_url TEXT あり (per-fact provenance) — 共存
--   jpi_feedback 存在確認済み (key_hash / customer_id / endpoint 等の列あり)

------------------------------------------------------------
-- 1. am_source.license
------------------------------------------------------------
ALTER TABLE am_source ADD COLUMN license TEXT;
-- 許容値: pdl_v1.0 / cc_by_4.0 / gov_standard_v2.0 / public_domain / proprietary / unknown
-- 全 NULL 開始。enforcement は scripts/fill_license.py + 下記 trigger で管理。

CREATE INDEX IF NOT EXISTS idx_am_source_license ON am_source(license);

CREATE TRIGGER IF NOT EXISTS am_source_license_check
BEFORE INSERT ON am_source
FOR EACH ROW WHEN NEW.license IS NOT NULL
  AND NEW.license NOT IN ('pdl_v1.0', 'cc_by_4.0', 'gov_standard_v2.0', 'public_domain', 'proprietary', 'unknown')
BEGIN
  SELECT RAISE(ABORT, 'invalid license value');
END;

CREATE TRIGGER IF NOT EXISTS am_source_license_check_update
BEFORE UPDATE OF license ON am_source
FOR EACH ROW WHEN NEW.license IS NOT NULL
  AND NEW.license NOT IN ('pdl_v1.0', 'cc_by_4.0', 'gov_standard_v2.0', 'public_domain', 'proprietary', 'unknown')
BEGIN
  SELECT RAISE(ABORT, 'invalid license value');
END;

------------------------------------------------------------
-- 2. am_entity_facts.source_id (per-fact source FK)
------------------------------------------------------------
-- 既存 source_url TEXT 列はそのまま残す (history / アプリ後方互換)。
-- 新しい source_id は am_source への正規参照を提供し、license / domain join を可能にする。
ALTER TABLE am_entity_facts ADD COLUMN source_id INTEGER REFERENCES am_source(id);
CREATE INDEX IF NOT EXISTS idx_am_efacts_source ON am_entity_facts(source_id);

------------------------------------------------------------
-- 3. jpi_feedback.entity_canonical_id (feedback → entity link)
------------------------------------------------------------
-- am_entities.canonical_id は TEXT。FK 宣言は migration 032 で
-- jpi_* mirror 経由の cross-table 参照は付けない方針なので index のみ。
ALTER TABLE jpi_feedback ADD COLUMN entity_canonical_id TEXT;
CREATE INDEX IF NOT EXISTS idx_jpi_feedback_entity ON jpi_feedback(entity_canonical_id);
