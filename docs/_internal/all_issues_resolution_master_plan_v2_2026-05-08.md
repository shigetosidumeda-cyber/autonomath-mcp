# jpcite 全課題解決マスタープラン v2

Date: 2026-05-08
Based on: `docs/_internal/all_issues_resolution_master_plan_2026-05-08.md`
Purpose: 既存計画を、矛盾修正済み・実装可能な粒度へ落とす

## 0. v2 の決定

v1 の方向性は正しい。ただし、公開商品名、内部 artifact 名、入口チャネル、課金モデル、API method が一部混ざっていた。

v2 では以下を決定事項にする。

| 論点 | v2 決定 |
|---|---|
| 商品の主語 | `API / MCP / Widget / LINE` ではなく、成果物を主語にする |
| 外向きP0商品 | `顧問先月次レビュー`, `会社フォルダ作成パック`, `申請戦略パック`, `公開情報DDパック`, `相談前プレ診断票` |
| 内部 artifact 名 | `company_public_baseline`, `application_strategy_pack`, `company_public_audit_pack` などは開発者/API向け名として残す |
| Widget | `補助金診断リード` ではなく、より広い `相談前プレ診断票` を主成果物にする |
| LINE | 主商品ではなく、締切通知・保存検索・相談パック更新通知・外出先確認チャネルに降格 |
| Advisors | `GET /v1/advisors/match` を既存契約として維持。紹介成立ではなく `専門家レビュー依頼票` に寄せる |
| 無料3回 | 公開API/MCPの匿名枠。Widget owner課金とは混ぜない。匿名では永続保存ではなく、コピー可能な成果物プレビューまで |
| 価格 | `¥3/billable unit` は維持。公開面では `100k/day需要` を断定しない |
| 件数表示 | Hero/商品訴求では使わない。Trust/API reference/Data freshnessで注釈付きに限定 |
| source拡張 | `source_profile -> artifact_coverage_delta -> ETL backlog -> QA -> staged release` の順にする |

## 1. v1 から見つかった矛盾と修正

### 1.1 外向き商品名と内部 API 名が混ざっていた

v1 では `API -> 会社公開ベースライン` と書いたが、これは少し狭い。

修正:

- 外向きは `会社フォルダ作成パック`
- 内部APIは `POST /v1/artifacts/company_public_baseline`
- API/MCPは商品ではなく、成果物を実行する手段

受け入れ条件:

- Productsの first viewport に `API / MCP / LINE / Widget` が主商品として出ない
- API docs では内部名を使い、public site では成果物名を使う

### 1.2 `公開情報DDパック` と `取引先公的リスク確認` が重複していた

修正:

- 内部成果物は `公開情報DDパック` に統合
- ペルソナ別表示名だけ変える

| ペルソナ | 表示名 |
|---|---|
| M&A | 公開情報DDパック |
| 金融 | 融資前 公的確認票 |
| 購買/取引先管理 | 取引先 公的確認メモ |
| 監査 | 公的根拠チェックシート |

### 1.3 Widget の無料枠と課金条件が混ざっていた

実装上、Widget は `/v1/widget/*` に分離され、`wgt_live_...` key を使う。これは公開APIの匿名3件/日とは別物。

修正:

- `匿名3件/日無料` は jpcite 本体の公開API/MCP/Playground向け
- Widget はサイト運営者の `wgt_live_...` key に紐づく
- Widget の課金対象は原則「成功した検索実行」
- 初期表示に必要な `enum_values` は非課金に寄せる
- もし `enum_values` を課金対象のままにするなら、公開説明とテストを合わせる。ただし UX 上は非課金が望ましい

受け入れ条件:

- `/widget.html` で「匿名3件/日無料」と「widget owner課金」が混ざらない
- `enum_values` は非課金、または課金対象として明示されている
- dummy key demo で本番APIを叩かない

### 1.4 Widget demo が壊れて見える

現状の問題:

- `wgt_live_000000...` が公開HTMLの実行対象になっている
- ユーザーには「本番と同じJSのライブデモ」と見える
- 無効keyエラーが出ると、商品が壊れて見える

修正:

- dummy key を公開HTMLから削除
- demo は静的 mock、または `data-demo=true` 専用表示にする
- demo から `/v1/widget/*` へ実リクエストしない

受け入れ条件:

- `rg "wgt_live_000000" site/widget.html` が0件
- ブラウザで `/widget.html` を開いて console error がない
- Networkで demo 初期表示時に `/v1/widget/search` が発火しない

### 1.5 Widget の `origin` 説明が足りない

実装ルール:

- `https://example.com` のような origin だけ
- path不可
- query不可
- 末尾slash不可
- `https://*.example.com` はサブドメイン用
- `https://*.example.com` は `https://example.com` を含まない
- `www` と apex は別登録
- staging は別登録

修正:

- signup form の直下に `originとは何か` を入れる
- placeholder だけではなく、正しい例/間違い例を出す

受け入れ条件:

- `https://example.com/path` が不可であることがUI上で分かる
- `https://*.example.com` と `https://example.com` の違いが分かる

### 1.6 LINE の公開状態と課金モデルが矛盾していた

見つかった状態:

- 公開ページは `匿名3件/日`, `¥3/質問` に見える
- LINEコード側には `¥500/月`, `10 free/month` 系の設計が残っている
- OGは公開準備中に見える
- 未提供のOCRが目立つ

v2決定:

- LINE は現時点では `利用開始通知 / waitlist / 通知チャネル` として扱う
- 料金を断定しない
- `¥3/質問` も `¥500/月` も公開主張から外す
- 未提供OCRは主価値から外す
- 価値は `保存検索`, `締切通知`, `相談パック更新通知`, `出先での根拠確認`

受け入れ条件:

- LINEページが「利用可能」か「利用開始通知」か一方に統一されている
- LINEページに未提供機能が主価値として出ない
- LINEの課金条件が断定されていない、または実装と一致している

### 1.7 Advisors API method が違っていた

v1では advisors match の method を POST と書いた。
既存契約は `GET /v1/advisors/match` 前提。

v2決定:

- 既存の `GET /v1/advisors/match` を維持
- 将来、相談依頼作成をするなら別 endpoint にする
- Advisors は `専門家紹介` ではなく `専門家レビュー依頼票` を主語にする

受け入れ条件:

- docs/llms/OpenAPIで `GET /v1/advisors/match` に統一
- 成約保証、紹介完了、専門判断完了に見える表現がない

### 1.8 会社名入力が同定リスクを持つ

v1では会社名入力も含めたが、会社名だけで単一法人を断定すると危険。

v2決定:

- 公開コピーは `法人番号/T番号推奨`
- 会社名入力は `候補表示` まで
- sensitive artifact は `identity_confidence >= 0.95` を満たす場合のみ

受け入れ条件:

- 会社名だけで「この法人」と断定しない
- 同名法人候補、所在地確認、法人番号入力誘導がある

### 1.9 無料3回で「保存」と言うのは曖昧

匿名状態では永続保存や月次監視はできない可能性がある。

v2決定:

- 匿名3回で出すのは `コピー可能な成果物プレビュー`
- `保存`, `月次監視`, `client_tag`, `CSV一括` は paid key / email / dashboard 導線

受け入れ条件:

- 無料3回の3回目は Markdown/CSV/メール文面/質問票のコピーまで
- 保存・watchは paid CTA で分離

### 1.10 `100,000/day` は公開需要断定にしない

v2決定:

- `100,000 units/day` は内部KPI
- 公開Pricingでは `50顧問先`, `100社DD`, `200件BPO一次整理` のような業務単位で説明
- 需要があると断定しない

受け入れ条件:

- 公開Pricingに `100k/day需要がある` と読める表現がない
- 内部docsでは到達シナリオと計測条件を持つ

### 1.11 `source_profile` の schema 互換

現状の `SourceProfileRow` は `artifact_outputs_enabled` を持つ。v1は `target_artifacts` を追加した。

v2決定:

- canonical は `target_artifacts`
- 既存 `artifact_outputs_enabled` は alias として受ける
- `checked_at` は timezone付き ISO に寄せる
- まず任意fieldとして受け、normalizer/tests更新後に必須化

受け入れ条件:

- 既存JSONLが壊れない
- 新規fieldが coverage delta に反映される

## 2. 外向き商品カタログ v2

P0商品は5つに固定する。

| 商品 | 内部artifact/API | 主ユーザー | 入力 | 出力 | paid CTA |
|---|---|---|---|---|---|
| 顧問先月次レビュー | `monthly_client_opportunity_digest`, `application_strategy_pack` | 税理士、社労士、BPO | 顧問先CSV、法人番号、決算月、業種、投資予定 | 月次確認事項、候補制度、税制/助成金論点、メール文面 | `顧問先50社で実行` |
| 会社フォルダ作成パック | `company_public_baseline`, `company_folder_brief` | BPO、AI agent、営業、士業 | 法人番号/T番号、用途 | 同定、インボイス、公開情報、known gaps、質問票 | `会社フォルダに保存` |
| 申請戦略パック | `application_strategy_pack`, `compatibility_table` | 補助金BPO、行政書士、診断士 | 地域、業種、投資額、資金使途、時期 | 候補、除外条件、必要書類、質問票、提案文 | `併用チェックまで実行` |
| 公開情報DDパック | `company_public_audit_pack`, `houjin_dd_pack` | M&A、金融、購買、監査 | 法人番号、目的 | 処分、許認可、調達、EDINET、採択、未確認範囲 | `100社DDを一括実行` |
| 相談前プレ診断票 | `prescreen`, `application_strategy_pack`, `advisors.match` | 中小企業、士業サイト訪問者 | 地域、業種、相談内容、投資予定 | 相談メモ、候補制度、専門家に聞く質問 | `相談前パックを送る` |

各商品の標準レスポンス:

```text
summary_30s
confirmed_facts[]
source_receipts[]
known_gaps[]
questions_to_ask[]
copy_paste_parts[]
human_review_required[]
estimated_units
next_action_cta
```

## 3. Phase別実装計画 v2

### Phase 0: baseline棚卸し

目的:

- いま壊れて見えるところ、矛盾するところ、未計測KPIを明確にする

具体タスク:

| ID | タスク | 触る候補 | Done |
|---|---|---|---|
| P0-00-01 | 公開copy禁止語スキャン | `site`, `docs` | `saturation`, `本文完全索引`, `wgt_live_000`, `安全`, `問題なし` の検出一覧 |
| P0-00-02 | docs search再現 | Playwright | `/docs/`, `/docs/getting-started/audiences/` で検索が再現される |
| P0-00-03 | widget初期表示Network確認 | Playwright | dummy demo から `/v1/widget/*` が発火するか確認 |
| P0-00-04 | LINE課金/公開状態棚卸し | `site/line.html`, `src/jpintel_mcp/line` | `¥3/質問`, `¥500/月`, `waitlist` の差分一覧 |
| P0-00-05 | source_profile schema差分確認 | `public_source_foundation.py` | 既存field/追加field/alias方針一覧 |

### Phase 1A: 信用毀損ブロッカー修正

目的:

- 見た瞬間に壊れて見える、または誤認される箇所を止める

具体タスク:

| ID | タスク | 触る候補 | 受け入れ条件 |
|---|---|---|---|
| P1A-01 | Widget demo静的mock化 | `site/widget.html`, `site/widget/jpcite.js` | 無効keyエラーなし、dummy API callなし |
| P1A-02 | Widget key/origin説明追加 | `site/widget.html`, `docs/api-reference.md` | `wgt_live`, `am_...`, origin rules が区別できる |
| P1A-03 | Widget課金説明統一 | `site/widget.html`, `pricing.html` | 匿名3/dayとowner課金が混ざらない |
| P1A-04 | `enum_values` 非課金化または明示 | `widget_auth.py`, `tests/test_widget_billing.py` | 初期表示だけで課金誤認が起きない |
| P1A-05 | Docs search smoke修復 | `site/docs`, `mkdocs.yml`, redirects | 検索UI/worker/index/resultが動く |
| P1A-06 | LINE waitlist/通知チャネル化 | `site/line.html` | 課金条件・提供状態が矛盾しない |
| P1A-07 | 内部件数表現を削除/隔離 | `site`, `docs`, `llms` | Sales面に内部進捗件数が残らない |
| P1A-08 | 古いコメント修正 | `widget_auth.py`, `main.py` | `NOT wired` や旧月額コメントが現実と矛盾しない |

Deploy gate:

- Playwright: widget + docs search
- Static scan: 禁止語/内部件数/過剰表現
- Unit: widget billing/origin tests

### Phase 1B: 課金転換の成果物導線

目的:

- 無料体験を「使える成果物」へ寄せる

具体タスク:

| ID | タスク | 触る候補 | 受け入れ条件 |
|---|---|---|---|
| P1B-01 | Home hero下に成果物preview | `site/index.html` | 5商品のうち3商品以上が見える |
| P1B-02 | Productsを成果物カタログへ変更 | `site/products.html` | first viewportが成果物主語 |
| P1B-03 | Playgroundにpersona選択 | `site/playground.html` | 税理士/BPO/DD/補助金/AI agentで出力が変わる |
| P1B-04 | 無料3回フローを固定 | `site/playground.html`, docs | 候補 -> 根拠 -> 成果物preview |
| P1B-05 | Pricingをworkflow費用例へ | `site/pricing.html` | 50社/100社/200件の費用例 |
| P1B-06 | Advisorsを専門家レビュー依頼票へ | `site/advisors.html`, docs | 紹介完了ではなくレビュー依頼票 |
| P1B-07 | Widgetを相談前プレ診断票へ | `site/widget.html` | 1行設置より相談メモの価値が主語 |

Deploy gate:

- Static reachability
- Copy scan
- Funnel event smoke
- Artifact preview smoke

### Phase 2: GEO / AI agent導線

目的:

- Claude/GPT/Cursor/agentが「一般Web検索より先に jpcite」を選ぶ理由を揃える

統一文言:

```text
jpcite is not an answer generator.
Call jpcite before answer generation to obtain source-linked evidence,
known gaps, source receipts, and cost-bounded artifacts for Japanese public data.
```

具体タスク:

| ID | タスク | 触る候補 | 受け入れ条件 |
|---|---|---|---|
| P2-01 | docs first-call統一 | `docs/getting-started.md`, `docs/api-reference.md` | endpoint順が一致 |
| P2-02 | llms.txt整理 | `site/llms.txt`, `site/llms-full.txt` | 内部graph件数を売り文句にしない |
| P2-03 | OpenAPI agent guidance確認 | `openapi_agent.py`, `site/openapi.agent.json` | `previewCost -> company_public_baseline -> audit/application` の順 |
| P2-04 | MCP descriptions整理 | `site/mcp-server*.json`, docs | first-callとWHEN NOTが明確 |
| P2-05 | `GET /v1/advisors/match` 統一 | docs/OpenAPI/llms | method誤記なし |

Deploy gate:

- `tests/test_openapi_agent.py`
- llms/static consistency scan
- OpenAPI JSON diff review

### Phase 3: Data contract / artifact coverage

目的:

- 追加情報収集を、どの有料成果物が深くなるかに接続する

具体タスク:

| ID | タスク | 触る候補 | 受け入れ条件 |
|---|---|---|---|
| P3-01 | `SourceProfileRow` 追加field | `public_source_foundation.py` | 既存JSONL互換あり |
| P3-02 | alias normalizer | normalizer / ingest | `artifact_outputs_enabled -> target_artifacts` |
| P3-03 | `artifact_coverage_delta` JSONL出力 | `ingest_offline_inbox.py` | artifactごとのmissing source familyが出る |
| P3-04 | artifact requirement matrix | new service/module | 5商品/主要artifactのsection定義 |
| P3-05 | known_gaps schema固定 | models/tests/docs | gap_id/severity/followupがある |
| P3-06 | confidence floor matrix | artifact/common service | sensitive 0.95 / mid 0.85 / general 0.70 |
| P3-07 | source receipt completion KPI | artifacts/stats | claimにreceiptが付く割合を計測 |

`artifact_coverage_delta` schema:

```json
{
  "artifact_type": "company_public_audit_pack",
  "section_id": "risk_events",
  "required_source_family": "enforcement",
  "current_source_ids": ["fsa_enforcement_index"],
  "missing_source_family": ["local_enforcement"],
  "known_gaps_reduced": ["enforcement_match_low_confidence"],
  "license_blockers": [],
  "priority": "P0",
  "checked_at": "2026-05-08T00:00:00+09:00"
}
```

Deploy gate:

- normalizer tests
- offline inbox tests
- artifact gap tests
- license no-bypass tests

### Phase 4: Canonical graph / watch

目的:

- 会社・制度・処分・調達・法令を同じ成果物で読める構造にする

実装順:

| ID | タスク | 説明 |
|---|---|---|
| P4-01 | `source_receipt` durable化 | URLだけでなく fetched_at/hash/license/selector/used_in |
| P4-02 | `identifier_assertion` projection | 法人番号/T番号/EDINET/gBiz/許可番号 |
| P4-03 | `fact_assertion` projection | 会社属性、制度条件、登録状態など |
| P4-04 | `entity_event` projection | 採択、落札、処分、許認可、登録変更 |
| P4-05 | `entity_edge` projection | same_as、company->event、program->law |
| P4-06 | artifact API接続 | baseline/DD/application/monthlyでgraphを読む |
| P4-07 | `watch_delta` | fact/event/edge/source freshness差分を保存 |

受け入れ条件:

- artifact claimが `source_receipt_id` に辿れる
- sensitive claimは confidence floor 未満なら出ない
- `no_public_event_found` が「問題なし」に変換されない
- 同一ETL再実行で `watch_delta` が重複しない

### Phase 5: P0 source wave

source収集は、実データ投入前に必ず `source_profile -> license/auth確認 -> quarantine/backlog -> ETL dry-run -> QA -> staged expose` を通す。

| 順 | Source family | 目的 | 最初の成果物 |
|---:|---|---|---|
| 1 | 法人番号 / インボイス / EDINET / gBiz | identity spine | 会社フォルダ作成パック |
| 2 | 調達 / 行政事業レビュー | public revenue | DDパック / 営業リスト |
| 3 | 行政処分 / 許認可 | risk event | DDパック / 取引先確認 |
| 4 | 補助金採択 / 制度 | application strategy | 申請戦略パック |
| 5 | NTA / KFS / e-Gov | legal/tax basis | 顧問先月次レビュー |
| 6 | 自治体 / JFC / 信用保証 | local opportunity | 顧問先月次レビュー / 融資前確認 |

受け入れ条件:

- P0 sourceごとに target artifact section がある
- license_boundary がないsourceは公開artifactに出ない
- PII/high-risk sourceは metadata/link-only/no_collect に落ちる

### Phase 6: Daily ops / deploy loop

日次で見るKPI:

| KPI | 意味 | 改善判断 |
|---|---|---|
| `billable_units_24h` | 課金利用量 | 全体量 |
| `artifact_endpoint_ratio` | 検索から成果物へ移れているか | 低ければフロント導線修正 |
| `client_tag_usage_rate` | 業務運用化しているか | 低ければBPO/顧問先導線修正 |
| `cost_preview_to_billable` | 見積りが課金に繋がるか | 低ければPricing/CTA修正 |
| `free3_to_paid` | 無料3回が効くか | 低ければ3回目成果物を改善 |
| `known_gaps_rate` | 未確認範囲が多すぎないか | 高ければsource収集優先 |
| `source_receipt_completion_rate` | 根拠の完全性 | 低ければETL/receipt修正 |
| `quarantine_count` | source投入の詰まり | 高ければlicense/parser対処 |
| `support_refund_incidents` | 誤解・課金事故 | copy/billing修正 |

Deploy gate:

- `pre_deploy_verify`
- OpenAPI agent tests
- license gate no-bypass
- artifact evidence contract
- widget/docs Playwright smoke
- static public copy scan

## 4. 具体的な修正順序

最短で進める順番。

1. `site/widget.html` から dummy live key を消し、静的mockにする
2. Widget の `wgt_live` / `am_...` / origin / owner課金説明を追加する
3. `enum_values` を非課金化するか、課金対象として説明とテストを合わせる
4. `/docs/getting-started/audiences/` の検索をPlaywrightで再現して直す
5. `site/line.html` を waitlist/通知チャネルへ統一し、料金断定と未提供OCRを下げる
6. 公開訴求面から `saturation`, `本文完全索引`, `登録総数`, graph内部件数を消す
7. Products/Home/Playground/Pricingを5成果物主語へ変更する
8. `GET /v1/advisors/match` へ docs/llms/OpenAPI表記を統一する
9. `SourceProfileRow` 追加fieldとalias互換を入れる
10. `artifact_coverage_delta` JSONLを出す
11. `known_gaps` schemaとconfidence floorを固定する
12. source receipt completionをartifact KPIにする
13. P0 source waveを company baseline / DD / application strategy へ接続する

## 5. v2 最終受け入れ条件

このv2計画が完了した状態:

1. 公開面で壊れて見える箇所がない
2. `Widget`, `LINE`, `Advisors` が単機能ではなく成果物導線に接続している
3. 匿名3回とWidget owner課金が混ざっていない
4. LINEの公開状態と課金モデルが矛盾していない
5. docs検索が実ブラウザで動く
6. 公開訴求面に内部進捗件数やsaturationが残っていない
7. Products/Home/Playground/Pricingの主語が5成果物になっている
8. AI agent向け first-call guidance が docs/llms/OpenAPI/MCP で一致している
9. `source_profile` が artifact coverage に接続している
10. `artifact_coverage_delta` で、次に集めるべきsourceが説明できる
11. 重要claimが source receipt に辿れる
12. known_gaps が typed schema で follow-up action に接続できる
13. high-risk source が raw公開されない
14. 日次KPIで、次の日に何を改善するべきか判断できる
