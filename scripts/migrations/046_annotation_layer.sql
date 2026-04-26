-- target_db: autonomath
-- 046_annotation_layer.sql
-- 汎用注釈レイヤー (annotation layer) — am_entities に対する examiner feedback /
-- quality score / validation failure / ML 推論 / manual note を一表で受ける。
--
-- Why one polymorphic table (not 5+ kind-specific tables):
--   * AutonoMath operator (frontend) emits "annotation events" for any am_entities
--     row — examiner warning, quality score, validation failure — and the
--     annotation kinds will keep growing post-launch. EAV-style storage with
--     `kind TEXT REFERENCES am_annotation_kind(kind)` lets us add new kinds by
--     INSERTing into the lookup table, no migration churn for each new event
--     type. This mirrors am_entity_facts' EAV posture (5.26M rows, single table).
--   * Visibility (public / internal / private) is per-row, not per-kind: the
--     same `manual_note` may be private for one entity and internal for another.
--     Lookup table seeds a default but the row column wins.
--
-- Effective period + supersede chain:
--   * `effective_from` / `effective_until` capture the *real-world* window the
--     annotation applies to (e.g. an examiner_correction valid only until the
--     program's next amendment).
--   * `supersedes_id` + `superseded_at` model the audit chain: a quality_score
--     re-emitted later does NOT delete the prior row, it links via
--     `supersedes_id` so we keep the trail. The partial index `idx_am_annot_live`
--     restricts hot reads to currently-live rows only.
--
-- FK target types (verified against autonomath.db schema):
--   * am_entities.canonical_id  TEXT PRIMARY KEY  → entity_id below is TEXT
--   * am_source.id              INTEGER PK AUTOINC → source_id below is INTEGER
--
-- Read posture:
--   * Customer-facing tools surface only `visibility = 'public'` rows.
--   * Internal dashboards may surface `internal`. `private` rows never leave
--     the operator boundary (manual notes by 梅田 etc.).

CREATE TABLE IF NOT EXISTS am_annotation_kind (
  kind TEXT PRIMARY KEY,
  description TEXT NOT NULL,
  default_visibility TEXT NOT NULL CHECK(default_visibility IN ('public', 'internal', 'private'))
);

INSERT OR IGNORE INTO am_annotation_kind(kind, description, default_visibility) VALUES
  ('examiner_warning',    '申請フォーム品質ログ - 警告',                'internal'),
  ('examiner_correction', '申請フォーム品質ログ - 自動修正提案',         'internal'),
  ('quality_score',       '申請フォーム品質スコア (0-1)',                'internal'),
  ('validation_failure',  '検証ルール違反',                              'internal'),
  ('ml_inference',        '機械学習推論結果',                            'internal'),
  ('manual_note',         '人手メモ',                                    'private');

CREATE TABLE IF NOT EXISTS am_entity_annotation (
  annotation_id   INTEGER PRIMARY KEY AUTOINCREMENT,
  entity_id       TEXT NOT NULL REFERENCES am_entities(canonical_id),
  kind            TEXT NOT NULL REFERENCES am_annotation_kind(kind),
  severity        TEXT NOT NULL CHECK(severity IN ('info', 'warning', 'critical')),
  text_ja         TEXT,
  score           REAL,
  meta_json       TEXT,
  visibility      TEXT NOT NULL CHECK(visibility IN ('public', 'internal', 'private')),
  source_id       INTEGER REFERENCES am_source(id),
  effective_from  DATE,
  effective_until DATE,
  supersedes_id   INTEGER REFERENCES am_entity_annotation(annotation_id),
  superseded_at   TIMESTAMP,
  observed_at     TIMESTAMP NOT NULL,
  created_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_am_annot_entity_kind ON am_entity_annotation(entity_id, kind);
CREATE INDEX IF NOT EXISTS idx_am_annot_kind_severity ON am_entity_annotation(kind, severity);
CREATE INDEX IF NOT EXISTS idx_am_annot_live ON am_entity_annotation(entity_id, kind) WHERE effective_until IS NULL AND superseded_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_am_annot_visibility ON am_entity_annotation(visibility, kind);
CREATE INDEX IF NOT EXISTS idx_am_annot_observed ON am_entity_annotation(observed_at DESC);
