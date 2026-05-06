# Public Source Foundation Reingest Plan 2026-05-06

この文書は、Public Source Foundation normalizer 導入後に投入する source family の順序を実装者向けに固定する。所有範囲はこの文書のみ。

## 最新前提

- `tools/offline/_inbox/public_source_foundation/`: 249 files / 22MB
- `tools/offline/_quarantine/public_source_foundation/`: quarantine 352
- `tools/offline/_inbox/public_source_foundation/_backlog/`: 154 rows
  - `schema_backlog.jsonl`: 76 rows
  - `source_document_backlog.jsonl`: 45 rows
  - `source_review_backlog.jsonl`: 33 rows
- source profile 実ファイル: 508 rows
- `source_matrix.md` rollup: Iteration 6 反映後、約652 rows
- 判断の正本: Iteration 6 の `schema_backlog.md` と `risk_register.md`

## normalizer後の現状

- 実行日時: 2026-05-06 12:32 JST
- 指定コマンド: `scripts/cron/ingest_offline_inbox.py --tool public_source_foundation --dry-run`
- 実行環境メモ: 指定コマンドの直接実行は実行ビットなしで `permission denied`。この端末では `python` が未導入、`python3` は3.9で `datetime.UTC` 非対応、`.venv312` は `pydantic` 未導入だったため、最終的に `PYTHONPATH=src .venv/bin/python scripts/cron/ingest_offline_inbox.py --tool public_source_foundation --dry-run` で測定した。
- dry-run結果: total 617 rows / valid 19 / quarantine 598
- validになった主な入力:
  - `source_profiles_2026-05-06_iter2_addenda.jsonl`: valid 1 / quarantine 1
  - `source_profiles_2026-05-06_prefecture_iter2.jsonl`: valid 18 / quarantine 15
- dry-runの終了コードは quarantine が残るため `1`。最終ログは `done. started=2026-05-06T03:32:26.491526+00:00 applied=19 quarantined=598`。

## まだ落ちる形状

- `startup_hub_constituents_2026-05-06.jsonl`: 135 rows。`hub_slug` / `org_name` / constituent系の行で、`source_id`、`priority`、`official_owner`、`source_url`、`source_type`、`target_tables`、`checked_at` など SourceProfileRow の必須項目にまだ展開されていない。
- `source_profiles_2026-05-06_kanko_sports_kodomo_iter6.jsonl` など: 102 rows。日本語の `name` からは `source_id` を作れず、`priority`、`source_type`、`data_objects`、`acquisition_method`、`robots_policy` なども不足する。
- `source_profiles_2026-05-06_boj_tdb_tsr_iter4.jsonl` など: 59 rows。`name` / `url` / `owner` 系の簡易profileで、`priority` と source profile必須メタデータが薄い。
- `source_profiles_2026-05-06_kokka_shikaku_iter6.jsonl` など: 57 rows。`source_id` はあるが `priority`、`official_owner`、`source_url`、`source_type`、`data_objects` などの標準列が不足する。
- `source_profiles_2026-05-06_chukaku_cities_iter3.jsonl` など: 55 rows。自治体IDはあるが `official_owner`、`source_url`、`source_type`、`data_objects`、`acquisition_method` への補完が足りない。

## 次の実装

- `startup_hub_constituents` 専用normalizerを追加し、`hub_slug` と constituent名から安定した `source_id`、`official_owner`、`source_url`、`source_type=directory`、`target_tables`、`checked_at` を生成する。source URL が推定できない行は引き続き quarantine に残す。
- 日本語 `name` だけのprofile向けに、URLまたは `source_id` 候補がない場合の派生ルールを足す。ただし読み仮名なしの日本語名だけでIDを作る場合は衝突しやすいため、owner/domain/prefixを必須にする。
- `owner` / `authority` / `operator` / `official_owner`、`url` / `root_url` / `listing_url`、`license` / `terms`、`robots` 系aliasの適用範囲を広げる。
- source family別の既定値を小さく入れる。例: 自治体directoryは `source_type=directory`、`acquisition_method=html_or_api_probe_required`、`redistribution_risk=medium_review_required`、`update_frequency=unknown` とし、公開可能判定は `source_review_backlog` 側へ逃がす。
- `dry-run` でも `quarantine_line()` が既存 quarantine path を書く挙動があるため、次回計測前に「完全read-only dry-run」を別途実装または一時出力先指定にする。

## Normalizer 後の固定投入順

### 1. KFS reset / backfill

- ユーザーに出せるアウトプット: 税務争点メモ、裁決根拠付きの顧問先説明、既存 `nta_saiketsu` を使った根拠引用パック。
- join key: `vol`, `case`, 裁決番号、裁決日、税目、通達番号、`law_id`、article。
- risk: backfill ETL errors=2 の原因未確定。KFS専用の新規 canonical table を作らず、既存 `nta_saiketsu` に寄せる前提を崩すと重複SOTになる。
- 最初のテスト: errors=2 の再現fixtureを固定し、同一 `vol/case` の upsert idempotency、文字コード正規化、`source_document` と `extracted_fact` の件数一致を確認する。

### 2. CAA 食品リコール

- ユーザーに出せるアウトプット: 食品事業者の回収履歴、取引先食品安全チェック、食品・小売・卸向けの monitoring digest。
- join key: `rcl_id`、`recall_date`、manufacturer name、`manufacturer_houjin_bangou`、product name、source URL。
- risk: メーカー名だけでは同名異法人が起きる。法人番号は NTA / invoice 側の fuzzy enrichment 依存で、信頼度の低い join を公開してはいけない。
- 最初のテスト: `recall.caa.go.jp/result/detail.php?rcl=00000035239` 形式の単票を1件取得し、`food_recall.rcl_id`、category、product、reason、source URL、content hash を保存する。続けてID範囲10件で欠番と404を quarantine へ分離する。

### 3. RS API

- ユーザーに出せるアウトプット: 補助金・委託費・支出先の上流根拠、法人別の公的資金受領シグナル、制度と予算事業IDの追跡。
- join key: `project_number`、`lineage_id`、`budget_project_id`、`ministry_id`、fiscal year、`recipient_houjin_bangou`。
- risk: 年度またぎの `lineage_id` と `project_number` を混同すると同一事業の時系列が壊れる。支出先法人番号がある行とない行を同じ信頼度で扱わない。
- 最初のテスト: `https://rssystem.go.jp/api/projects/` から1 ministry / 1 fiscal year を取得し、`project_number` 主キー、`lineage_id` index、`recipient_houjin_bangou` partial index を検証する。

### 4. 中労委

- ユーザーに出せるアウトプット: 労務リスクの公的根拠、会社DDの不当労働行為アラート、労務監査向けの事件メタデータ。
- join key: `m{NNNNN}` detail id、命令日、事件名、裁定区分、通称名から推定した `houjin_bangou`、respondent match confidence。
- risk: 当事者欄は匿名化されているため、通称名 fuzzy match の誤結合が名誉毀損リスクになる。`respondent_match_confidence < 0.95` は公開クエリから除外する。
- 最初のテスト: `m_index.html` を1回取得して直近5年512件の索引件数を再現し、詳細 `mei/m{NNNNN}.html` 3件だけで裁定 enum、事件名、匿名化当事者、公開除外gateを確認する。

### 5. e-Gov 95k edge

- ユーザーに出せるアウトプット: 法令改正差分、制度から根拠条文への cross reference、条文引用の接続理由。
- join key: `law_id`、`law_revision_id`、article、referenced `law_id`、referenced article、edge type。
- risk: 9,484法令から約95k edgeを作るため、添付PDFや第三者著作物を本文mirror扱いしない。既存 `laws` / `am_law` を直接破壊せず、`law_revisions` / `law_attachment` / edge table に閉じる。
- 最初のテスト: 信託法の訂正済み `law_id` を含む10法令だけで XML parse、article anchor、参照先 `law_id` 解決、edge重複排除を確認する。

### 6. WARC / Fly

- ユーザーに出せるアウトプット: 期限切れ別ドメイン制度ページの取得時点証跡、自治体制度の URL drift 監査、内部再現用の source snapshot metadata。
- join key: capture URL、canonical source URL、`content_hash`、capture timestamp、authority、region code、program id。
- risk: WARC snapshot は内部archiveであり、外部提供はしない。METI / enecho / MAFF などの WAF・Akamai・Wayback fallback は source別 fetch profile を必須にする。
- 最初のテスト: 既存 `_warc/2026-05-06` の2サイトだけを `source_document` 化し、HTML本体ではなく manifest、headers、hash、as_of timestamp だけが外部artifactへ流れることを確認する。

### 7. API key 申請待ち系

- ユーザーに出せるアウトプット: 法人番号spine、EDINET metadata、gBizINFO派生fact、e-Stat地域業種統計、J-PlatPat metadata など。ただし key 未取得中は申請状態と blocked reason を freshness ledger に出す。
- join key: `houjin_bangou`、`corporate_number`、`JCN`、`edinetCode`、`secCode`、`docID`、`stat_code`、`region_code`、`industry_code_jsic`、application / publication number。
- risk: key 未取得のまま ad-hoc scrape に逃げると規約・rate・再配布境界が崩れる。申請待ちの source は fetch job を disabled にし、schemaとbacklogだけ先に固定する。
- 最初のテスト: `api_key_applications_2026-05-06.md` の申請対象を `source_review_backlog` に反映し、key missing の source が fetch queue に入らず `blocking_reason=api_key_pending` で止まることを確認する。

## 実装者向けゲート

- normalizer 出力は本番DBへ直投入しない。`source_document_backlog.jsonl`、`schema_backlog.jsonl`、`source_review_backlog.jsonl` から review 済みだけを migration / fetch job / extractor へ渡す。
- 各 source family は `source_document`、`extracted_fact`、`known_gaps_json`、固定出典文、`fetched_at`、`content_hash` を最低条件にする。
- fuzzy join は `match_confidence` を保存し、公開レスポンスへ出す閾値を source family ごとに明示する。
- `risk_register.md` の high risk は fetch 実装より先に公開gateを作る。
- この順序を変える場合は、先にこの文書を更新して理由を1行で残す。
