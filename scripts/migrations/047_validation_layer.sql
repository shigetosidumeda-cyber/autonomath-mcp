-- target_db: autonomath
-- migration 047: 汎用検証ルールレイヤー (validation rule + result)
--
-- Business context:
--   Autonomath の intake_consistency_rules.py から 6 個の汎用述語
--   (例: 個人保証なら担保不要 / 売上要件と従業員数の整合 等) を
--   jpintel-mcp 側に移植する受け皿。Python ハードコードでなく
--   メタデータとして DB に持ち、effective_from/until で時系列を扱う。
--
-- Two tables:
--   * am_validation_rule    — ルール定義 (述語の参照と severity)
--   * am_validation_result  — 評価結果 (entity または applicant_hash 単位)
--
-- predicate_kind:
--   * python_dispatch — predicate_ref はモジュール:関数名 (例: am.rules.r1:check_collateral)
--   * sql_expr        — predicate_ref は WHERE 句として評価する SQL 式
--   * json_logic      — predicate_ref は JSONLogic 式 (将来用)
--
-- FK 注意 (実 DB スキーマに合わせ調整済み):
--   * am_entities の PK は canonical_id TEXT (NOT INTEGER, NOT entity_id)
--   * am_source   の PK は id          INTEGER (NOT source_id)
--   依頼テンプレ上の `entity_id INTEGER REFERENCES am_entities(entity_id)`
--   と `source_id INTEGER REFERENCES am_source(source_id)` を実列名/型に修正。

PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------------------
-- am_validation_rule
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS am_validation_rule (
  rule_id          INTEGER PRIMARY KEY AUTOINCREMENT,
  applies_to       TEXT NOT NULL,                          -- e.g. 'program', 'loan', 'applicant', 'adoption'
  scope            TEXT NOT NULL,                          -- e.g. 'global', 'authority', 'prefecture', 'entity'
  predicate_kind   TEXT NOT NULL CHECK(predicate_kind IN ('python_dispatch', 'sql_expr', 'json_logic')),
  predicate_ref    TEXT NOT NULL,                          -- module:func / SQL expr / JSONLogic blob
  severity         TEXT NOT NULL CHECK(severity IN ('info', 'warning', 'critical')),
  message_ja       TEXT NOT NULL,
  scope_entity_id  TEXT REFERENCES am_entities(canonical_id),  -- nullable; pin to one entity when scope='entity'
  effective_from   DATE,
  effective_until  DATE,
  active           INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0, 1)),
  source_id        INTEGER REFERENCES am_source(id),       -- nullable; primary-source provenance
  created_at       TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_am_valrule_applies ON am_validation_rule(applies_to, active);
CREATE INDEX IF NOT EXISTS idx_am_valrule_scope   ON am_validation_rule(scope_entity_id, active);

-- ---------------------------------------------------------------------------
-- am_validation_result
-- ---------------------------------------------------------------------------
-- entity_id か applicant_hash のどちらか (もしくは両方) で結果を一意化。
-- entity_id は am_entities.canonical_id (TEXT)。
-- applicant_hash は無記名 applicant の安定ハッシュ (sha256, hex, lower)。
CREATE TABLE IF NOT EXISTS am_validation_result (
  result_id        INTEGER PRIMARY KEY AUTOINCREMENT,
  rule_id          INTEGER NOT NULL REFERENCES am_validation_rule(rule_id),
  entity_id        TEXT REFERENCES am_entities(canonical_id),
  applicant_hash   TEXT,
  passed           INTEGER NOT NULL CHECK(passed IN (0, 1)),
  message_ja       TEXT,
  evaluated_at     TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(rule_id, entity_id, applicant_hash)
);

CREATE INDEX IF NOT EXISTS idx_am_valres_rule_time ON am_validation_result(rule_id, evaluated_at DESC);
CREATE INDEX IF NOT EXISTS idx_am_valres_entity   ON am_validation_result(entity_id, passed);
