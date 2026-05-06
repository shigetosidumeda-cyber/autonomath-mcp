-- target_db: autonomath
-- Wave 19 §15b: sqlite-vec virtual tables for 7-corpus pre-embedding
-- model: intfloat/multilingual-e5-large (dim=1024)
-- 各 tier table は CORPUS_SPECS in tools/offline/embed_corpus_local.py に対応:
--   S=programs, L=laws (am_law_article), C=case_studies, T=tsutatsu (nta_tsutatsu_index),
--   K=saiketsu (nta_saiketsu), J=court_decisions, A=adoptions (jpi_adoption_records)
--
-- Idempotent: CREATE VIRTUAL TABLE IF NOT EXISTS で再実行安全。
-- entrypoint.sh §4 が boot 時に `-- target_db: autonomath` を picked up し
-- $AUTONOMATH_DB_PATH に対して適用する。
--
-- legacy `am_entities_vec` (suffix なし) は別物。tier suffix 付きが新規層。
-- INSERT OR REPLACE は embed_corpus_local.py 側で実施する。
--
-- 前提: sqlite-vec extension が load 済 (src/jpintel_mcp/db/session.py:104 で
-- runtime load 済、offline embed 経路は embed_corpus_local.py 側で対応)。

CREATE VIRTUAL TABLE IF NOT EXISTS am_entities_vec_S USING vec0(
  entity_id INTEGER PRIMARY KEY,
  embedding float[1024]
);
CREATE VIRTUAL TABLE IF NOT EXISTS am_entities_vec_L USING vec0(
  entity_id INTEGER PRIMARY KEY,
  embedding float[1024]
);
CREATE VIRTUAL TABLE IF NOT EXISTS am_entities_vec_C USING vec0(
  entity_id INTEGER PRIMARY KEY,
  embedding float[1024]
);
CREATE VIRTUAL TABLE IF NOT EXISTS am_entities_vec_T USING vec0(
  entity_id INTEGER PRIMARY KEY,
  embedding float[1024]
);
CREATE VIRTUAL TABLE IF NOT EXISTS am_entities_vec_K USING vec0(
  entity_id INTEGER PRIMARY KEY,
  embedding float[1024]
);
CREATE VIRTUAL TABLE IF NOT EXISTS am_entities_vec_J USING vec0(
  entity_id INTEGER PRIMARY KEY,
  embedding float[1024]
);
CREATE VIRTUAL TABLE IF NOT EXISTS am_entities_vec_A USING vec0(
  entity_id INTEGER PRIMARY KEY,
  embedding float[1024]
);
