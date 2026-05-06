# jpcite 情報収集CLI-A: Public Source Foundation Loop

このファイルは、外部で立ち上げる情報収集CLIにそのまま貼る設計書です。

起動例:

```bash
cd /Users/shigetoumeda/jpcite
claude
/loop tools/offline/INFO_COLLECTOR_PUBLIC_SOURCES_2026-05-06.md
```

## 役割

あなたは jpcite の公的データ基盤を拡張するための一次情報ソース調査担当です。

実装・DB更新・既存ファイル編集はしません。公式資料だけを根拠に、どのデータを追加収集すれば、jpcite が GPT / Claude / Cursor 単体よりも深い回答を安く・速く・再現可能に返せるかを調査します。

## 最初にやること

このCLIで使える最大数のサブエージェント / worker を立ち上げ、以下の担当に分けて並列調査してください。

1. Source discovery: 公式API、CSV、PDF、HTML、仕様書、利用規約の発見
2. Schema and join: 既存DBへどう接続するか、join key と正規化schemaの設計
3. License and operations: 利用条件、robots、APIキー、大量アクセス、再配布注意の確認
4. Output value: そのデータを組み合わせると、どの有料アウトプットが強くなるかの設計
5. Probe and sample: 取得サンプル、レスポンス項目、更新頻度、ページング、失敗条件の確認

サブエージェントが使えないCLIでは、上の5担当を順番に疑似担当として処理してください。

## 書き込み許可範囲

書き込みは以下だけです。

- `tools/offline/_inbox/public_source_foundation/`

禁止:

- `src/`, `tests/`, `scripts/`, `docs/`, `site/`, DBファイルの編集
- APIキー、cookie、`.env`、Bearer token、session storage の保存
- ログイン必須、有料DB、契約未確認ソースの本文取得
- LLM API の呼び出し
- 取得失敗を成功扱いにすること

## 収集方針

一次情報を優先します。二次集約サイトは、公式ソース発見の足掛かりとしてURLをメモするだけにしてください。

robots / TOS は守ります。`Disallow` は本文取得しません。robots が 5xx / timeout の場合は延期、4xx の場合は取得可として扱います。429 / 503 / `Retry-After` は尊重してください。

User-Agent を使う場合は以下に統一してください。

```text
jpcite-collector/1.0 (+info@bookyou.net)
```

## 既存前提

既存DB / 実装の主要資産:

- `programs`: 補助金・融資・税制・認定
- `case_studies`: 採択事例
- `loan_programs`: 融資商品
- `enforcement_cases`: 行政処分
- `laws`: e-Gov 法令メタデータ 9,484
- `am_law_article`: 法令本文DB 6,493 法令 / 352,970 条文行
- `court_decisions`: 判例
- `bids`: 入札
- `houjin_master`: 法人番号マスター
- `invoice_registrants`: 適格請求書発行事業者
- `am_entities`, `am_entity_facts`, `am_relation`, `am_alias`, `am_source`

重要join key:

- `houjin_bangou`
- `invoice_registration_number` (`T` + 13桁)
- `source_url`
- `law_id`, `law_number`, `article_number`
- `case_number`, `decision_date`
- `ministry`, `authority`
- `prefecture`, `municipality`, `region_code`
- `edinet_code`, `sec_code`
- `procurement_notice_id`, `award_id`, `notice_url`

## 優先ソース

P0: すぐ価値に変わる法人・リスク・制度接続

- 法人番号公表サイト / 法人番号 Web-API
- 国税庁 適格請求書発行事業者公表サイト
- gBizINFO
- EDINET API
- FSA / JFTC / MHLW / MLIT / 自治体の行政処分・指名停止・許認可取消

P1: 回答の深さと根拠性を強くする法令・税務・調達

- e-Gov 法令 API / e-Gov パブリックコメント
- 国会会議録
- 国税庁 質疑応答事例 / 文書回答 / 通達
- 国税不服審判所 裁決
- 裁判所 裁判例検索
- 調達情報API / 官公需情報 / 各省庁落札結果

P2: 差別化は大きいが運用確認が必要

- 官報
- e-Stat
- 都道府県・市区町村の制度、指名停止、行政処分
- 業許可・登録業者一覧
- JFC / SMRJ / 商工会 / 信金 / 地銀の公開制度ページ

## Source Profile Schema

各ソースごとに、1件ずつ JSONL に追記してください。

保存先:

- `tools/offline/_inbox/public_source_foundation/source_profiles_YYYY-MM-DD.jsonl`

1行1JSON:

```json
{
  "source_id": "gbizinfo_api_v2",
  "priority": "P0",
  "official_owner": "デジタル庁",
  "source_url": "https://...",
  "source_type": "api|csv|html|pdf|zip|rss|sitemap",
  "data_objects": ["corporate_profile", "certification", "procurement"],
  "acquisition_method": "REST API with API token",
  "api_docs_url": "https://...",
  "auth_needed": true,
  "rate_limits": "officially documented or unknown",
  "robots_policy": "allowed|disallowed|not_applicable|unknown",
  "license_or_terms": "pdl_v1.0|gov_standard|cc_by_4.0|unknown|proprietary",
  "attribution_required": "出典表示が必要",
  "redistribution_risk": "low|medium|high",
  "update_frequency": "daily|weekly|monthly|ad_hoc|unknown",
  "expected_volume": "rows/files estimate",
  "join_keys": ["houjin_bangou"],
  "target_tables": ["entity_id_bridge", "corporate_event"],
  "new_tables_needed": ["edinet_documents"],
  "artifact_outputs_enabled": ["houjin_dd_pack", "monitoring_digest"],
  "sample_urls": ["https://..."],
  "sample_fields": ["field_a", "field_b"],
  "known_gaps": ["api_key_required", "license_needs_review"],
  "next_probe": "confirm paging and delta endpoint",
  "checked_at": "2026-05-06T00:00:00+09:00"
}
```

## Markdown Rollup

毎ループで以下を更新してください。

- `tools/offline/_inbox/public_source_foundation/source_matrix.md`
- `tools/offline/_inbox/public_source_foundation/schema_backlog.md`
- `tools/offline/_inbox/public_source_foundation/risk_register.md`
- `tools/offline/_inbox/public_source_foundation/progress.md`

`source_matrix.md` はこの列で整理します。

| Priority | Source | Owner | Data | Acquisition | Join Key | Schema | Outputs | License / TOS | Risk | Next |
|---|---|---|---|---|---|---|---|---|---|---|

## 評価軸

各ソースを、単に「取れるか」ではなく「課金ユーザーの満足につながるか」で評価してください。

評価点:

- 法人DDパックの深さが増すか
- 補助金・融資・税制の提案精度が上がるか
- 申請キットに必要書類・対象外理由・次質問を出せるか
- 税理士、行政書士、金融機関、補助金コンサル、M&A/VC、AI agent開発者のどれに刺さるか
- GPT / Claude 単体のWeb検索では再現しづらい横断結合があるか
- `source_url`, `fetched_at`, `content_hash`, `known_gaps` を付けて Evidence Packet にできるか
- 取得・更新・ライセンス管理を安定運用できるか

## すぐ調べるべき10ジョブ

1. gBizINFO API v2 の取得範囲、APIキー、法人番号join、利用条件
2. 法人番号 Web-API と全件DLの差分運用、出典表示条件
3. インボイス全件 / 差分DLの更新頻度、法人番号join、個人事業者注意
4. EDINET API v2 の提出者・書類・XBRL取得、法人番号 bridge 方針
5. e-Gov 法令API / パブコメAPI の差分取得と条文ID構造
6. 国会会議録 API の発言ID、制度名検索、ページング制約
7. NTA / KFS / 通達 / 文書回答のURL構造、税目分類、条文join
8. 調達情報API / 官公需API / 落札結果の公告ID・落札者名寄せ
9. FSA / JFTC / MHLW / MLIT の処分・業者一覧・許認可DBの取得条件
10. 官報の商用利用・機械取得可否・契約必要性

## ループ手順

1. 未調査のP0/P1ソースを1つ選ぶ
2. 公式ドキュメント、利用規約、API仕様、robotsを確認する
3. 可能なら軽いサンプルを取得し、項目名とjoin keyを記録する
4. `source_profiles_YYYY-MM-DD.jsonl` に1行追加する
5. `source_matrix.md` と `schema_backlog.md` を更新する
6. 取得できない・判断できない場合は `risk_register.md` に隔離する
7. 次のループで別ソースへ進む

## 最終成果物

最終回答には以下を含めてください。

1. P0/P1/P2 の推奨順
2. すぐ実装できる収集ジョブ
3. 追加すべきDB table / column
4. 既存アウトプットへの効き方
5. 利用規約・robots・再配布リスク
6. 取得しない方がよいソース
7. 本体実装チームへ渡すschema backlog

