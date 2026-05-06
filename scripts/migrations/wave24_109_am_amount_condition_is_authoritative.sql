-- target_db: autonomath
-- migration wave24_109_am_amount_condition_is_authoritative
--   (MASTER_PLAN_v1 章 3 §M5 — am_amount_condition の 96.6% template_default
--    クリーンアップ第 1 段)
--
-- Why this exists:
--   `am_amount_condition` は 250,946 行を保持しているが、その大半は壊れた
--   ETL が ¥500K / ¥2M をテンプレ既定値として bulk INSERT した結果で、
--   `template_default = 1` フラグが立っている。そのまま検索・推奨ロジックに
--   流すと、当事者根拠 (公募要領 PDF / 通達 / 法令) を持たない数字を
--   さも authoritative であるかのように顧客へ surface してしまい、¥3/req
--   metered service として致命的な信頼毀損を起こす。
--
--   このマイグレーションは「authoritative とみなしてよい行」だけを
--   下流の検索 default が拾えるよう、3 列を追加し、既存データに対し
--   「evidence_fact_id が存在する」「extracted_text が空でない」
--   「template_default=0 (テンプレ既定ではない)」の 3 条件を AND で満たす
--   行を `is_authoritative=1` に昇格させる。
--
--   実際の authoritative 値の再抽出 (公募要領 PDF を operator-LLM で
--   構造化抽出 → INSERT/UPDATE して is_authoritative=1 を立てる) は別系統
--   (`tools/offline/`) で実行され、その結果はこの列を介して runtime に伝播
--   する。runtime コードはこの列を読むだけで API 呼び出しは行わない。
--
-- Idempotency:
--   ALTER TABLE ADD COLUMN は 2 回目以降「duplicate column name」を吐くが、
--   `entrypoint.sh` §4 のループは autonomath-target SQL を sqlite3 -bail で
--   流して duplicate column を継続可能 warning として扱う (mig 049 / 086 /
--   wave24_105 と同 pattern)。CREATE INDEX は IF NOT EXISTS。
--   UPDATE は冪等 — 同条件に再 hit しても `is_authoritative=1` が再代入
--   されるだけで副作用なし。
--
-- DOWN:
--   companion `wave24_109_am_amount_condition_is_authoritative_rollback.sql`
--   参照 (entrypoint.sh は *_rollback.sql を name match で除外する)。

PRAGMA foreign_keys = ON;

-- 1. authoritative フラグ。DEFAULT 0 で既存行は全て non-authoritative。
--    UPDATE 文 (下) で条件を満たす行のみ 1 に昇格する。
ALTER TABLE am_amount_condition ADD COLUMN is_authoritative INTEGER NOT NULL DEFAULT 0;

-- 2. authoritative 判定の根拠。
--    e.g. 'evidence_fact', 'pubreq_pdf:claude-sonnet-4-6:2026-05-04',
--         'official_url_html_extract', 'tsutatsu_table' など。
--    テンプレ既定値由来の昇格 (本マイグレーションでは行わないが、将来
--    operator-LLM パイプラインから差し込む場合) は authority_source を
--    必ず埋めてトレーサビリティを残す。
ALTER TABLE am_amount_condition ADD COLUMN authority_source TEXT;

-- 3. authoritative 判定がいつ行われたか (ISO8601 UTC)。
--    operator-LLM 再抽出パイプラインが UPDATE する時に datetime('now') を
--    入れる。本マイグレーションで昇格させる行については
--    UPDATE 句で datetime('now') を割り当てる。
ALTER TABLE am_amount_condition ADD COLUMN authority_evaluated_at TEXT;

-- 4. authoritative-only な検索 hot path 用 partial index。
--    runtime 検索 default は WHERE is_authoritative=1 で絞るので、
--    template_default=0 の方を index しても意味がなく、authoritative=1
--    だけを走査するこの index がコスト最適。
CREATE INDEX IF NOT EXISTS idx_amc_authoritative
    ON am_amount_condition(is_authoritative, condition_kind, numeric_value)
 WHERE is_authoritative = 1;

-- 5. 既存データの一次昇格。
--    AND 3 条件:
--      (a) evidence_fact_id IS NOT NULL  — am_entity_facts への trace あり
--      (b) extracted_text != ''         — 一次資料からの抽出文字列が残存
--      (c) template_default = 0         — broken-ETL のテンプレ既定でない
--
--    現時点 (2026-05-04 snapshot) のヒット件数は MASTER_PLAN §M5 の
--    target 50,000 行とは乖離する見込みだが、本マイグレーションは
--    「authoritative 判別の枠組み」だけを敷く責務であり、実数は後続の
--    operator-LLM 再抽出 (tools/offline/) が積み上げていく。
--
--    NOTE: extracted_text が NULL の行は `!= ''` で除外される (NULL の
--    比較結果が UNKNOWN になり WHERE が真にならない) ため、明示的な
--    NOT NULL チェックは不要。それで意図と合致する。
UPDATE am_amount_condition
   SET is_authoritative      = 1,
       authority_source       = COALESCE(authority_source, 'evidence_fact_id+extracted_text'),
       authority_evaluated_at = COALESCE(authority_evaluated_at, datetime('now'))
 WHERE evidence_fact_id IS NOT NULL
   AND extracted_text IS NOT NULL
   AND extracted_text != ''
   AND template_default = 0;

-- Bookkeeping recorded by scripts/migrate.py via schema_migrations
-- (autonomath-target migrations are tracked in the same registry the
--  jpintel-target ones are; entrypoint.sh §4 marks each apply with the
--  basename so re-runs short-circuit). Do NOT INSERT here.
