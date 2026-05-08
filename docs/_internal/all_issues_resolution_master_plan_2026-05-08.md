# jpcite 全課題解決マスタープラン

Date: 2026-05-08
Scope: ここまで見つけた課題をすべて解決し、課金されやすいサービスへ寄せるための計画

## 0. 最重要結論

jpcite の課題は、機能不足だけではない。

本当の課題は、すでに持っている強い部品が、公開面では「検索API」「Widget」「LINE bot」「MCP tools」のような機能名で見えてしまい、ユーザーが「これで自分の仕事がどう楽になるのか」「なぜ払うのか」を30秒で理解しづらいこと。

解決方針は明確。

```text
機能名で売らない
成果物で売る

検索API            -> 会社公開ベースライン
Widget             -> 補助金診断リード / 相談前パック
LINE bot           -> 通知・締切・外出先確認チャネル
MCP / OpenAPI      -> AI agent が最初に叩く公的根拠レイヤー
Evidence Packet    -> 回答前の根拠パック
Advisors           -> 根拠付き相談前パックから専門家レビューへ渡す導線
```

ユーザーが払う理由は「検索できるから」ではなく、以下が出るから。

- 顧問先に送れる月次レビュー
- 申請前に使える制度候補・除外条件・必要書類・質問票
- 会社/取引先/DDで使える公的確認パック
- AI agent が回答前に使える source URL 付き evidence
- `known_gaps` による未確認範囲の明示
- `client_tag`、月次上限、cost preview による運用しやすさ

## 1. 全体課題一覧

| ID | 優先 | 課題 | 影響 | 解決テーマ |
|---|---|---|---|---|
| I-01 | P0 | 商品が機能名に見える | 課金理由が弱い | 成果物カタログ化 |
| I-02 | P0 | 無料3回が課金導線になっていない | 試して終わる | 3回で完成物を見せる |
| I-03 | P0 | Widget demo が dummy key で壊れて見える | 信頼を失う | demo と本番keyを分離 |
| I-04 | P0 | Widget の key/origin/課金条件が分かりにくい | 申し込み離脱・誤解 | 説明とruntimeを一致 |
| I-05 | P0 | docs search が動かない | 開発者/AI導線が壊れる | 実ブラウザ検証と修復 |
| I-06 | P0 | 内部件数・saturation 表現が公開面に出る | 未完成感・誤認 | 公開件数の出所統一 |
| I-07 | P0 | 追加source収集がartifact価値に接続しきっていない | 集めても売上化しにくい | `artifact_coverage_delta` |
| I-08 | P0 | entity/fact/event/receipt/watch の統一contractが弱い | DD/watchが深くならない | Canonical graph model |
| I-09 | P0 | license/PII/overclaim境界がsource別に揺れる | 法務・信頼リスク | 前置license gate |
| I-10 | P0 | AI agent が最初に叩く理由が公開面で弱い | GEO/AI流入が弱い | first-call guidance統一 |
| I-11 | P1 | LINE bot が誰向けか不明 | 安っぽい機能に見える | 通知/締切/外出先確認へ降格 |
| I-12 | P1 | Pricing が unit 単価中心 | 成果物原価が伝わらない | 成果物別費用例 |
| I-13 | P1 | Watch/digest が商品として弱い | 継続利用が伸びない | 月次レビュー/差分DD化 |
| I-14 | P1 | Advisors が紹介っぽく見える | 業法/期待値リスク | 相談前パック化 |
| I-15 | P2 | 旧名・コメント・内部用語の残存 | 内部混乱 | 表記整理 |

## 2. 商品設計の修正

### 2.1 外向き商品を成果物名にする

公開面の主語を、機能から成果物へ変更する。

| 現在見えがちな主語 | 新しい主語 | 対象 |
|---|---|---|
| API | 会社公開ベースライン | AI agent / BPO / 士業 |
| MCP tools | AI回答前の公的根拠パック | Claude / GPT / Cursor / agent |
| Widget | 補助金診断リード | 税理士事務所 / 商工会 / 支援サイト |
| LINE bot | 締切・保存検索・出先確認チャネル | 士業/BPO担当者 |
| Advisors | 相談前パック / 専門家レビュー依頼票 | 中小企業 / BPO / 士業 |
| Playground | 無料3回で成果物を見る場所 | 全員 |

### 2.2 成果物カタログ

P0で前面に出す成果物は以下。

| 成果物 | 入力 | 出力 | 課金理由 |
|---|---|---|---|
| 会社公開ベースライン | 法人番号/T番号/会社名 | 同定、インボイス、公開情報、known_gaps、質問票 | 会社フォルダ作成時に毎回必要 |
| 公開情報DDパック | 法人番号、目的 | 処分、調達、EDINET、許認可、補助金、未確認範囲 | M&A/金融/取引先確認で高価値 |
| 申請戦略パック | 地域、業種、投資額、資金使途 | 候補制度、除外条件、必要書類、質問票 | 補助金BPO/行政書士の初回確認 |
| 顧問先月次レビュー | 顧問先CSV、決算月、業種 | 税制/補助金/助成金/融資候補、メール文面 | 継続課金に直結 |
| 相談前パック | 相談内容、会社情報 | 根拠、未確認点、専門家に聞くべき質問 | advisors導線の健全化 |
| 取引先公的リスク確認 | 法人番号、取引目的 | インボイス/処分/許認可/調達/known_gaps | 与信・購買・監査前確認 |

### 2.3 成果物の標準形

すべての成果物は同じ読み味にする。

```text
30秒結論
確認済み事実
根拠URL
取得日時
confidence
known_gaps
human_review_required
次に聞く質問
コピーできる文面
推定 units / cost
次のCTA
```

受け入れ条件:

- 非開発者が30秒で「何に使えるか」を理解できる
- 1画面に `source_url`、`known_gaps`、`次に聞く質問` が出る
- CTA が `試す` ではなく `顧問先へ送る`、`CSVで50社実行`、`月次監視に追加` など実務行動になる

## 3. 無料3回の再設計

無料3回は「検索を3回できる」では弱い。

以下の固定フローにする。

| 回 | 体験 | 目的 |
|---:|---|---|
| 1 | 候補カード | jpcite が何を見つけられるかを見せる |
| 2 | Evidence Packet highlights | 公式URL、取得時刻、known_gaps を見せる |
| 3 | 完成物プレビュー | そのまま使えるレビュー/質問票/メモを見せる |

3回目のCTA:

- `残り50社を一括処理`
- `この会社を月次監視`
- `顧問先へ送る文面をコピー`
- `APIキーを発行して継続`
- `client_tag付きで運用`

受け入れ条件:

- 無料3回以内に保存可能な成果物が1つ出る
- JSONではなく、Markdown/CSV/メール文面/質問票のいずれかが出る
- paid CTA が成果物の直後にある

## 4. フロントエンドの具体課題と修正

### 4.1 Widget

現状課題:

- demo が `wgt_live_000...` の dummy key で動き、`widget key が無効です` のように壊れて見える
- `wgt_live_...` が何か分かりにくい
- `origin` が何か分かりにくい
- `API key` と `widget key` の違いが分かりにくい
- 「補助金検索を1行で」は価値として弱い

修正:

1. dummy key を実API初期化対象から外す
2. demo は静的mock、`data-demo=true`、または本番APIを叩かない専用表示にする
3. `wgt_live_...` はブラウザに置く origin 制限付き widget key と説明する
4. `am_...` API key とは別物と説明する
5. `origin` は `https://example.com` 形式、path不可、staging/wwwは別登録、wildcardはサブドメインのみと説明する
6. 商品名を `補助金診断リード` または `相談前パックを自社サイトで受け取る` に変更する
7. CTA を `自社サイトで診断リードを作る` に変える

受け入れ条件:

- `/widget.html` 初回表示でエラーが出ない
- dummy key から `/v1/widget/*` への実リクエストが発生しない
- 1回読めば key/origin/課金対象が分かる
- Widget の価値が「検索UI」ではなく「相談前リードの品質向上」になっている

### 4.2 LINE bot

現状課題:

- 誰が使うのか、なぜ払うのかが弱い
- `公開準備中` と課金説明が混在しやすい
- `写真で領収書OCR (後日)` など未提供機能が目立つ

修正:

1. LINE は主商品ではなく、保存検索・締切通知・出先確認チャネルとして位置付ける
2. first viewport で対象を明確化する
3. 未提供機能は下げるか削除する
4. `自然文検索` ではなく `気になる制度を保存して締切前に通知` を主価値にする
5. 料金発生条件を実提供状態に合わせる

受け入れ条件:

- 冒頭で `対象ユーザー`、`反復ワークフロー`、`公開状態`、`課金条件` が矛盾なく分かる
- LINEが「検索の別入口」ではなく「通知/リマインド/移動中確認」になっている

### 4.3 Docs search

現状課題:

- `/docs/getting-started/audiences/` で検索が動かない報告あり
- `site/docs/search/search_index.json` は存在するため、index欠落ではなくJS worker、base path、fetch path、CSP、build artifact、UI初期化の問題が疑わしい

修正:

1. Playwrightで `/docs/` と `/docs/getting-started/audiences/` を開く
2. 検索UIを開き、代表語句で検索する
3. `search_index.json` と worker JS の200確認
4. base path と相対パスを確認
5. CIに docs search smoke を追加する

受け入れ条件:

- `/docs/` と `/docs/getting-started/audiences/` の両方で検索結果が出る
- `search_index.json` と worker JS が200
- 検索エラーがconsoleに出ない

### 4.4 内部件数表示

現状課題:

- `9,484 法令メタデータ`、`本文完全索引`、`saturation` のような内部進捗に見える表現が公開面に出る
- Trust/Playground/docs/llms/launch assets に件数が点在
- 件数は価値になる場合もあるが、未完成感や不信感にもなる

修正:

1. 公開件数は `public_counts` のsource of truthへ一本化
2. Home/Products/Widget/LINE では内部件数を主張しない
3. Trust/Data freshness では注釈付きで出す
4. `本文完全索引` や `saturation` は公開訴求面から削除
5. `出典取得日` と `最終更新日` を厳密に分ける

受け入れ条件:

- `rg` で `saturation`、`154 件本文完全索引`、内部graph件数が公開訴求面に残らない
- 件数表示は Trust/Stats/Data freshness など検証ページに限定される
- `source_fetched_at` は `出典取得日` として表示され、`最新確認日` と誤読されない

## 5. データ基盤の修正計画

### 5.1 収集は artifact 起点にする

追加sourceは「集めたいから集める」ではなく、どの成果物のどのsectionを埋めるかで判断する。

`source_profile` に以下を追加/必須化する。

```json
{
  "source_id": "...",
  "source_family": "...",
  "official_owner": "...",
  "source_url": "...",
  "acquisition_method": "...",
  "join_keys": ["houjin_bangou"],
  "license_boundary": "full_fact|derived_fact|metadata_only|link_only|no_collect",
  "refresh_frequency": "...",
  "target_artifacts": ["company_public_baseline"],
  "artifact_sections_filled": ["identity", "risk_events"],
  "known_gaps_reduced": ["identifier_bridge_missing"],
  "new_known_gaps_created": ["source_license_unknown"],
  "parser_status": "none|prototype|stable|blocked",
  "checked_at": "2026-05-08"
}
```

### 5.2 P0 source family

| P | Source family | 主キー | 成果物 |
|---|---|---|---|
| P0 | 法人番号 / インボイス | 法人番号、T番号 | company baseline、取引先確認、月次watch |
| P0 | EDINET / gBizINFO | EDINETコード、法人番号 | DD、金融、会社フォルダ |
| P0 | 調達 / 行政事業レビュー | 法人番号、契約番号、発注機関 | public revenue、営業、DD |
| P0 | 補助金採択 / 制度情報 | 制度ID、採択ID、法人番号 | 申請戦略、月次レビュー |
| P0 | 行政処分 / 許認可 | 法人番号、名称住所、処分日、許可番号 | risk sheet、DD、watch |
| P0 | NTA / KFS / e-Gov | 法令ID、条文、通達ID、裁決番号 | 税務/法務根拠パック |
| P0 | 自治体制度 / JFC / 信用保証 | 自治体コード、制度ID、業種 | 顧問先提案、融資前確認 |

### 5.3 Canonical data model

source別tableだけではなく、成果物共通の読み方を作る。

```text
Entity      法人、制度、法令、許認可、調達案件、専門家
Identifier  法人番号、T番号、EDINET、gBiz、許可番号
Fact        source上で観測された属性
Event       採択、処分、登録、取消、提出、落札、改正
Edge        entity/fact/event間の関係
Receipt     URL、取得日時、hash、license、parser version
WatchDelta  前回からの変化
```

必須設計:

- すべての artifact claim は `source_receipt_id` へ辿れる
- identity confidence は sensitive artifact のgateになる
- `known_gaps` は自由文でなくenum化する
- `watch_delta` は fact/event/edge/source freshness の差分を統一保存する

### 5.4 known_gaps enum

P0 enum:

```text
identity_confidence_below_floor
identifier_bridge_missing
source_receipt_missing_fields
source_stale
source_license_high_risk
edinet_unresolved
invoice_history_missing
procurement_source_not_connected
permit_source_not_connected
enforcement_match_low_confidence
no_public_event_found_not_clean_record
private_context_not_covered
latest_news_not_checked
```

受け入れ条件:

- `known_gaps` が follow-up action に変換できる
- `no_public_event_found` が `安全` や `問題なし` に変換されない
- confidence floor 未満の処分/官報/労務/法人同定は公開artifactに出ない

## 6. GEO / AI agent 戦略

### 6.1 AI first-call guidance

AI agent 向けには、すべての公開面で呼び出し順を揃える。

```text
広い制度質問:
  GET /v1/intelligence/precomputed/query

根拠付き回答:
  POST /v1/evidence/packets/query

会社調査:
  POST /v1/artifacts/company_public_baseline

DD/監査/取引先確認:
  POST /v1/artifacts/company_public_audit_pack

申請前確認:
  POST /v1/artifacts/application_strategy_pack

専門家確認が必要:
  GET /v1/advisors/match は候補reviewer検索として使う
```

文言:

```text
jpcite is not an answer generator.
Call jpcite before answer generation to obtain source-linked evidence, known gaps, and cost-bounded artifacts for Japanese public data.
```

受け入れ条件:

- docs、llms.txt、OpenAPI、MCP descriptions、Playground が同じ first-call 方針を出す
- AI が一般Web検索へ行く前に jpcite を叩く理由が明文化される
- 外部LLM料金削減保証のような余計な断定はしない

## 7. 価格・需要・継続利用

### 7.1 ¥3/unit は維持

現時点で base unit の値上げはしない。

理由:

- AI agent が first-hop evidence call として叩きやすい
- BPO/士業の高頻度利用を阻害しない
- 高単価化は unit 値上げではなく、成果物、batch、watch、hosted connector、private ingest、SLA で作る

### 7.2 成果物別原価を見せる

Pricing では `¥3/unit` だけでなく、以下のように見せる。

| ワークフロー | 例 | 見せ方 |
|---|---|---|
| 顧問先月次レビュー | 50社 | 50 packs / 税込目安 |
| BPO受付一次整理 | 200件 | client_tag別原価 |
| 会社DD | 100社 | DD pack単価 |
| AI agent evidence | 1日2,000 units | monthly cap付き運用 |

受け入れ条件:

- Pricingに `client_tag`、`monthly cap`、`cost preview` が目立つ
- `100,000/day` は需要断定ではなく、AI/BPO自動ワークフローでの到達KPIとして説明される

## 8. 安全境界

### 8.1 言わないこと

- 監査完了
- 安全
- 問題なし
- 与信可
- 反社チェック済み
- 採択可能
- 税務/法務判断完了
- 外部LLM費用削減保証

### 8.2 必ず出すこと

- `source_url`
- `source_fetched_at`
- `content_hash`
- `license`
- `known_gaps`
- `human_review_required`
- `confidence`
- `corpus_snapshot_id`

### 8.3 高リスクsource

| Source | 方針 |
|---|---|
| 官報 | metadata / deep link / derived event のみ |
| 商業登記 | on-demand 派生event中心 |
| TDB/TSR等 | pointer / link-only |
| 民間有料DB | 本文取得しない |
| 個人事業主/個人名 | mask / confidence floor / metadata-only |
| 労務・行政処分 | fuzzy低confidenceは公開しない |

## 9. 実装順

### Phase 1: 公開面の破綻を止める

1. Widget dummy key demo を止める
2. Widget key/origin/課金説明を直す
3. docs search を実ブラウザで直す
4. 内部件数/saturation表現を公開訴求面から消す
5. LINE bot の価値・公開状態・課金条件を整理する

Done:

- `/widget.html` に無効keyエラーが出ない
- `/docs/getting-started/audiences/` で検索できる
- `saturation` や `154件本文完全索引` が公開訴求面にない

### Phase 2: 成果物で売る

1. Home hero下に完成物サンプルを置く
2. Productsを成果物カタログへ再編
3. Playgroundを無料3回フローにする
4. Pricingを成果物別原価へ寄せる
5. Advisorsを相談前パックへ寄せる

Done:

- 非開発者が30秒で価値を理解できる
- 無料3回で完成物プレビューが出る
- CTAが実務行動に接続している

### Phase 3: データ基盤を成果物に接続する

1. `source_profile` をsource契約へ拡張
2. `artifact_coverage_delta` を作る
3. `known_gaps` enumを固定
4. `source_receipt` completion scoreをartifactに出す
5. entity/fact/event/edge/read projectionを作る

Done:

- source追加でどのartifact sectionが埋まるか分かる
- artifact claim から receipt へ辿れる
- P0 artifact に confidence と known_gaps が標準で出る

### Phase 4: P0 source収集

1. 法人番号/インボイス履歴
2. EDINET/gBiz
3. 調達/行政事業レビュー
4. 補助金採択/制度情報
5. 行政処分/許認可
6. NTA/KFS/e-Gov
7. 自治体制度/JFC/信用保証

Done:

- `company_public_baseline` と `company_public_audit_pack` が深くなる
- `application_strategy_pack` が除外条件/必要書類/質問票を返せる
- monthly watch/digest の差分理由が出る

### Phase 5: 反復利用と計測

1. `client_tag` 付きunits比率を日次で見る
2. artifact endpoint比率を日次で見る
3. `previewCost -> paid` 転換率を見る
4. watch/digest/exportを成果物として課金説明する
5. 支払い/返金/サポートの誤解を検知する

Done:

- `billable_units_24h`
- `client_tag_usage_rate`
- `artifact_endpoint_ratio`
- `cost_preview_to_billable`
- `watch_digest_conversion`
- `known_gaps_rate`

が日次で見られる。

## 10. テスト計画

| 領域 | テスト |
|---|---|
| Widget | dummy key が実APIを叩かない、origin validation、課金説明snapshot |
| Docs | Playwright docs search smoke |
| Static copy | `saturation`、内部件数、過剰表現の禁止 |
| Artifact | source_receipts、known_gaps、copy_paste_parts、disclaimer |
| License | export path は license gate 必須 |
| Entity | confidence floor 未満はsensitive artifactに出ない |
| Billing | cost preview、monthly cap、client_tag |
| GEO | docs/llms/OpenAPI/MCP の first-call guidance一致 |
| Deploy | pre_deploy_verify、release readiness、smoke |

## 11. 最終受け入れ条件

この計画が完了した状態は、以下。

1. 公開面で壊れて見える箇所がない
2. 無料3回で「使える成果物」が出る
3. Widget/LINE/Advisorsが安っぽい単機能ではなく、成果物導線に接続している
4. 内部進捗・内部件数が公開訴求面に出ていない
5. AI agent が最初に叩くべき endpoint が明確
6. 追加sourceが artifact coverage に紐付いている
7. すべての重要claimが source receipt に辿れる
8. known_gaps が標準化され、未確認範囲を正直に出せる
9. high-risk source は metadata/link-only/no_collect の境界が守られる
10. `client_tag`、cost preview、monthly cap、watch/digestで継続利用を説明できる

## 12. 次に着手する順番

最短の着手順はこれ。

1. `/widget.html` の dummy key demo を無効化し、相談前パック/補助金診断リードのmockに変える
2. `/docs/getting-started/audiences/` の検索をPlaywrightで再現して直す
3. `saturation`、本文完全索引、内部件数表現を公開訴求面から消す
4. Products/Home/Playground/Pricingを成果物主語に寄せる
5. `source_profile` に `target_artifacts` / `artifact_sections_filled` / `known_gaps_reduced` を追加する
6. `artifact_coverage_delta` を作る
7. `known_gaps` enumとconfidence floorを統一する
8. P0 source収集を company baseline / DD / application strategy に接続する

これで jpcite は「検索できるサイト」ではなく、**AI・士業・BPOが会社や案件について最初に叩く、公的根拠付き成果物レイヤー**として見えるようになる。
