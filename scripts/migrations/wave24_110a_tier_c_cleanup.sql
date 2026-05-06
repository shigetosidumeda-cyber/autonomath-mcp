-- target_db: jpintel
-- migration wave24_110a_tier_c_cleanup
--   (MASTER_PLAN_v1 章 3 §M6 — tier C 6,044 行のうち重複名 668 とゴミ名を
--    一括 quarantine する)
--
-- Why this exists:
--   tier='C' は long-tail の地方自治体 program が大半で、ETL ノイズが
--   そのまま残存している。本マイグレーションは下記 2 種を tier='X'
--   (quarantine) に降格し、検索パスから除外する:
--
--   (a) 重複名 668 件
--       同一 primary_name で複数行ある tier='C' のうち、最古 unified_id
--       (= MIN(unified_id)) 1 行だけを残し、残りを tier='X', excluded=1,
--       exclusion_reason='dup_of_<keep_id>' でフラグする。
--
--   (b) ゴミ名 (PDF/HTML スクレイプ事故由来)
--       「摘 要」「企画調整G」「奈良県公式ホームページ」など、program 名
--       としては明らかに無意味な文字列 (テーブル見出し / 部署名 / サイト
--       表題など) を tier='X', excluded=1, exclusion_reason='garbage_name'
--       でフラグする。リストは MASTER_PLAN §M6(b) を出発点とし、運用
--       追加分は本ファイルを版管理して継ぎ足す方針。
--
--   amount_max NULL や app_window NULL の補完は別 cron
--   (`scripts/cron/refresh_sources.py --tier C --enrich`) の責務であり、
--   本マイグレーションは触らない (MASTER_PLAN §M6(c) 参照)。
--
-- Idempotency:
--   どちらの UPDATE も WHERE 句に「tier='C'」を含むので、再実行時には
--   既に tier='X' に降格済みの行は対象外となり no-op。CTE 内で MIN(id)
--   を再計算しても結果は決定的 (同 primary_name の中の最古 unified_id)。
--
--   primary_name の照合は完全一致 (LIKE ではなく =) なので、ゴミ名
--   一覧に新ノイズが見つかった場合は IN (...) リストに追記して
--   再 boot 適用する。
--
-- DOWN:
--   既存の tier='C' に戻す general-purpose な rollback は提供しない。
--   (a) は keep_id を残してその他を quarantine する設計上、戻す側は
--   exclusion_reason='dup_of_*' をパースして tier='C' に書き戻す
--   ad-hoc SQL を運用が手書きする。
--   (b) のゴミ名はリスト管理されているので、リスト除去 + tier='C' 直書き
--   で戻る。

PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------------
-- (0) exclusion_reason enum 拡張
--     `programs.exclusion_reason` は trigger
--     `trg_programs_exclusion_reason_enum_x{,_ins}` で
--     `exclusion_reason_codes` 表内の code に enum 制約されている。
--     本マイグレーションが使う 'garbage_name' を追加する
--     ('duplicate_of' は既存)。
--
--     INSERT OR IGNORE で冪等。
-- ---------------------------------------------------------------------
INSERT OR IGNORE INTO exclusion_reason_codes (code, description) VALUES
    ('garbage_name',
     'primary_name is a non-program string scraped from a table-header / department label / site title (e.g. tekiyo, 企画調整G, official homepage)');

-- ---------------------------------------------------------------------
-- (a) 重複名 dedup
--     同 primary_name のうち unified_id 辞書順で最古を keep、それ以外を
--     tier='X' に降格。CTE で keep_id を 1 回だけ計算し、UPDATE で
--     join し直す形にすることで、UPDATE 進行中に行が tier='X' に flip
--     して MIN が動くレースを避ける。
--
--     程度: 検出時点で tier='C' に約 668 重複セット。N 行重複 → N-1 行
--     を quarantine するので、影響行数は 668 × (avg_dup-1) のオーダー。
--
--     exclusion_reason は enum 制約上 'duplicate_of' (既存 code) を採用。
--     keep_unified_id への trace は merged_from 列に書き残す。
-- ---------------------------------------------------------------------
WITH dup_keep AS (
    SELECT primary_name,
           MIN(unified_id) AS keep_unified_id
      FROM programs
     WHERE tier = 'C'
       AND primary_name IS NOT NULL
       AND primary_name != ''
     GROUP BY primary_name
    HAVING COUNT(*) > 1
)
UPDATE programs
   SET tier             = 'X',
       excluded          = 1,
       exclusion_reason  = 'duplicate_of',
       merged_from       = COALESCE(merged_from, '') || (
           SELECT keep_unified_id FROM dup_keep
            WHERE dup_keep.primary_name = programs.primary_name
       )
 WHERE tier = 'C'
   AND primary_name IN (SELECT primary_name FROM dup_keep)
   AND unified_id NOT IN (SELECT keep_unified_id FROM dup_keep);

-- ---------------------------------------------------------------------
-- (b) ゴミ名 quarantine
--     リストは MASTER_PLAN §M6(b) seed + 運用観察追加。新ノイズを
--     見つけたら IN (...) に append して PR で版管理する。
--
--     完全一致のみを対象にする (ホワイトリスト方式)。LIKE / FTS で
--     部分一致を取ると正常な program 名まで誤って巻き込む事故が
--     起きるので採用しない。
-- ---------------------------------------------------------------------
UPDATE programs
   SET tier             = 'X',
       excluded          = 1,
       exclusion_reason  = 'garbage_name'
 WHERE tier = 'C'
   AND primary_name IN (
        '摘 要',
        '摘要',
        '企画調整G',
        '企画調整課',
        '奈良県公式ホームページ',
        'ホームページ',
        '公式ホームページ',
        'お知らせ',
        '新着情報',
        'トップページ',
        'サイトマップ',
        '担当課',
        '担当部署',
        '◎',
        '○',
        '※',
        '・',
        '－',
        '-',
        '関連リンク',
        '詳細はこちら',
        '詳しくはこちら',
        '【参考】',
        '【補足】',
        '備考',
        '注記',
        '注意事項'
   );

-- amount_max NULL 補完は本マイグレーションのスコープ外。
-- 担当: scripts/cron/refresh_sources.py --tier C --enrich (nightly)
--       補完不能と判定された行は同 cron が tier='X' に降格する。
