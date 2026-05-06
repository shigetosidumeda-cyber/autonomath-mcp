# 情報収集CLI向けプロンプト設計 2026-05-06

## 目的

これから大量に情報収集を行うため、現時点の公開サイトやREADMEの数字は先に直さない。まず、外部で2本の情報収集CLIを走らせ、以下を分担して調べる。

1. **CLI-A: Public Source Foundation**
   - 追加すべき一次情報ソース
   - 取得方式
   - 利用条件
   - join key
   - schema backlog
   - どの有料アウトプットに効くか

2. **CLI-B: Output and Market Validation**
   - 課金ユーザーが満足する完成物
   - persona別の価値
   - GPT / Claude 単体との差分
   - 初回3回無料で見せる体験
   - benchmark query

この文書は2本のCLIに貼る内容の親設計書。実際に `/loop` で使う個別ファイルは以下。

- `tools/offline/INFO_COLLECTOR_PUBLIC_SOURCES_2026-05-06.md`
- `tools/offline/INFO_COLLECTOR_OUTPUT_MARKET_2026-05-06.md`

## CLI-A 起動

```bash
cd /Users/shigetoumeda/jpcite
claude
/loop tools/offline/INFO_COLLECTOR_PUBLIC_SOURCES_2026-05-06.md
```

CLI-A の任務:

- gBizINFO、法人番号、インボイス、EDINET、e-Gov、国会会議録、NTA/KFS、裁判所、調達、FSA/JFTC/MHLW/MLIT、自治体処分、官報、e-Stat などを一次情報ベースで調査する
- 公式URL、API仕様、利用条件、robots、更新頻度、取得方式、join key、schema案を整理する
- `source_url`, `fetched_at`, `content_hash`, `known_gaps` 付きの Evidence Packet にできるかを評価する
- 法人DD、補助金戦略、申請キット、税務メモ、監視ダイジェストのどれに効くかを評価する

CLI-A の書き込み先:

- `tools/offline/_inbox/public_source_foundation/source_profiles_YYYY-MM-DD.jsonl`
- `tools/offline/_inbox/public_source_foundation/source_matrix.md`
- `tools/offline/_inbox/public_source_foundation/schema_backlog.md`
- `tools/offline/_inbox/public_source_foundation/risk_register.md`
- `tools/offline/_inbox/public_source_foundation/progress.md`

CLI-A の最終成果物:

1. P0/P1/P2 の推奨ソース
2. すぐ実装できる収集ジョブ
3. 追加すべきDB table / column
4. 既存アウトプットへの効き方
5. 利用規約・robots・再配布リスク
6. 取得しない方がよいソース
7. 本体実装チームへ渡すschema backlog

## CLI-B 起動

```bash
cd /Users/shigetoumeda/jpcite
claude
/loop tools/offline/INFO_COLLECTOR_OUTPUT_MARKET_2026-05-06.md
```

CLI-B の任務:

- ユーザーが「これは得だ」と感じる完成物をpersona別に設計する
- 単なる候補一覧ではなく、顧客メール、面談メモ、稟議、DD質問票、申請前チェックリストに転用できる形を定義する
- GPT / Claude / Perplexity / Google / JGrants / gBizINFO / 補助金検索SaaS / 会計SaaS / 自前RAGとの差分を整理する
- 初回3回無料で価値を見せるサンプル体験を定義する
- benchmark query と評価指標を作る

CLI-B の書き込み先:

- `tools/offline/_inbox/output_market_validation/persona_value_map.md`
- `tools/offline/_inbox/output_market_validation/artifact_catalog.md`
- `tools/offline/_inbox/output_market_validation/competitive_matrix.md`
- `tools/offline/_inbox/output_market_validation/benchmark_design.md`
- `tools/offline/_inbox/output_market_validation/interview_questions.md`
- `tools/offline/_inbox/output_market_validation/progress.md`

CLI-B の最終成果物:

1. 最初に売るべきpersona
2. Persona別価値マップ
3. GPT / Claude 単体との差分
4. 完成物カタログ
5. 初回3回無料で見せるべき体験
6. 満足条件 / 不満条件
7. サンプル回答構造
8. 競合比較表
9. persona別インタビュー質問
10. 検証ベンチ設計
11. 30日以内に検証すべき仮説
12. リスクと避けるべき表現

## 共通ルール

どちらのCLIも、使える最大サブエージェント数で並列に進める。

禁止:

- 既存コード、DB、公開サイト、docs本体の編集
- APIキー、cookie、`.env`、Bearer token、session storage の保存
- LLM API の呼び出し
- 取得失敗を成功扱いにすること
- 税務判断、法律判断、採択可否、融資可否の断定
- 外部LLM料金削減の保証表現

方針:

- 公式一次情報を優先する
- robots / TOS を守る
- 不明点は `known_gaps` として隠さない
- 競合が勝つ用途も書く
- 価格変更ではなく、内容の深さと完成物の価値に集中する

## 本体への渡し方

CLI-A の `schema_backlog.md` は、本体側で migration / ETL / source registry に分解する。

CLI-B の `artifact_catalog.md` と `benchmark_design.md` は、本体側で artifact API / response schema / eval harness に分解する。

公開サイトやREADMEの数字は、情報収集が進み、件数のSOTが固まった後でまとめて更新する。

