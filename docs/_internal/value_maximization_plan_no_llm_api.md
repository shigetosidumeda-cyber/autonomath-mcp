# JPCite / AutonoMath 価値最大化計画（LLM API不使用版）

作成日: 2026-04-30  
対象: `/Users/shigetoumeda/jpcite`  
位置づけ: 売上を作るための提案書兼実行計画

## 0. 絶対前提

この計画では、外部LLM APIを一切使わない。

- サーバー、cron、ingest、評価、改善ループから OpenAI / Anthropic / Gemini 等の外部LLM APIを呼ばない。
- ファインチューニング、RAG生成、embedding API、外部推論APIを商品価値の前提にしない。
- 価値は、公式データ収集、正規化、SQLite/FTS、決定的ルール、名寄せ、差分検知、監査ログ、CSV/ZIP/API/MCP配布で作る。
- Codex/エージェントによる調査、データ収集、コード化、品質点検は開発・運用プロセスとして使うが、プロダクトの実行時コストにLLM APIを入れない。
- 「採択確率をAIが断定する」「法務・税務判断を生成する」商品にはしない。出すのは根拠付きの候補、照合結果、除外理由、unknown、監査可能な出典である。

## 1. エグゼクティブサマリー

このプロジェクトの勝ち筋は、外部LLMを載せることではない。すでにある公的データ、法人データ、採択データ、税務・法令データ、MCP/REST、CSV/ZIP出力を、買い手の業務単位に束ねることが最短で売上につながる。

最初のゴールは「すごいAI」ではなく、税理士、補助金コンサル、M&A仲介、VC、金融機関、自治体支援会社が毎週使う「根拠付き業務データ基盤」にすること。買い手が払うのは自然文の賢さではなく、次の4つである。

1. 顧客や投資先を一括で調べられること。
2. 公式URL、取得日時、checksum、根拠行が残ること。
3. 制度、採択、法人、インボイス、行政処分、法令、調達を横断できること。
4. CSV、XLSX、ZIP、Slack、Sheets、kintone、Webhook、MCPで既存業務に流せること。

したがって、価値最大化の一つの計画は以下になる。

1. 30日でP0ブロッカーを解除する。
2. 60日で「補助金一括診断」「M&A/与信DD ZIP」「保存検索・週次Digest」「監査ワークペーパー」を商品化する。
3. 90日で公式データ拡張、採択金額・制度join、出典検証、ルールエンジン、評価セットを固定する。
4. 180日でデータライセンス、業種別パック、代理店運用、継続監視へ拡張する。

## 2. 現状認識

### 強い資産

- REST/MCP、公開サイト、課金、Dashboard、Saved Search、DD batch、CSV/ZIP、Webhook設計、Digest設計の土台がある。
- `jpi_*` 系テーブルには制度、採択、法人、インボイス、行政処分、調達、法令データがある。
- `docs/self_improve_loops.md` は zero LLM の自己改善方針を明記しており、今回の前提と一致する。
- `docs/_internal/ingest_automation.md` は公式ソースをtier別に更新する運用思想を持っている。
- `docs/_internal/customer_webhooks_design.md` と `docs/_internal/retention_digest.md` は継続利用を作る構想として使える。
- `docs/_internal/capacity_plan.md` によると、SQLite FTS自体は律速ではなく、低コスト従量モデルと相性がよい。

### 重大な弱点

- 実体リポジトリ `/Users/shigetoumeda/jpcite` では、現時点の `autonomath.db` の `programs` / `adoption_records` / `houjin_master` 等が0件で、`jpi_programs` / `jpi_adoption_records` / `jpi_houjin_master` 側にデータがある。APIや静的生成がどちらを正とするかを即確認しないと、空データ出荷の危険がある。
- Desktopの `/Users/shigetoumeda/Desktop/jpintel-mcp` は `/Users/shigetoumeda/jpintel-mcp` へのリンクだが、現環境ではリンク先が存在しない。作業・デプロイ・ドキュメントの正本パスを統一する必要がある。
- `site/pricing.html`、`site/success.html`、`site/trial.html`、`site/go.html`、`site/dashboard.html` などで、未呼び出しIIFEやインラインJS不具合があり、購入、trial、key reveal、保存検索、Webhook登録が止まる可能性が高い。
- API host、CORS、CSP、SDK、OpenAPI、Stripe return URL、公開ドメインが `jpcite.com` / `zeimu-kaikei.ai` / `autonomath.ai` / `autonomath.jp` 系で揺れている。
- `am_` / `ak_live` / `sk_`、ツール数、制度件数、税務ルール数、データ件数の表示が揺れている。
- `usage_events` は現DBで0件。保存検索、Digest、Funnel、課金分析を売るには、まず計測を生かす必要がある。
- 採択データは件数が大きいが、採択金額、制度ID join、採択者の品質表示が弱い。ここが強化されると売上に直結する。

## 3. 戦略ポジション

このプロジェクトは「AIチャット」ではなく「日本の公的制度・法人活動・根拠データの業務API」に寄せるべきである。

### 勝てる言い方

- 税務・補助金・法人DDの根拠付きAPI
- 公式URLと取得日時が残る制度検索
- 顧問先別に使える補助金・融資・税制の一括照合
- M&A/与信のための法人DD ZIP
- 公募・法改正・採択・インボイス・処分の継続監視
- CSV/Sheets/kintone/Slack/Webhookに流せる業務データ

### 避ける言い方

- AIが申請可否を判定
- 採択確率を予測
- 法律・税務アドバイスを自動生成
- LLMで根拠を読む
- RAGで制度を要約
- 外部AI APIで処理

顧客側がMCPクライアントや自社エージェントからこのAPIを呼ぶことはあり得る。しかし、このプロダクト自身はLLM APIを呼ばず、構造化された根拠データを返す。

## 4. 売上を作る商品

### 4.1 Developer API Pack

対象: SaaS開発者、自社業務システム、士業事務所の内製担当  
価値: REST/MCPで制度、法人、法令、インボイス、採択、処分、調達を引ける  
課金: `¥3/request` を基本に、月capを `¥3,300` / `¥33,000` / `¥110,000` のように提示する  
実装要点:

- API hostを1つに固定する。
- key reveal、curl、初回API成功までを3分以内にする。
- Dashboardに「今月利用額」「endpoint別利用」「client_tag別CSV」を出す。
- `fields=full` は有料・サイズ制限・byte capを必須にする。

### 4.2 Agency / Advisor Pack

対象: 税理士、行政書士、認定支援機関、補助金コンサル  
価値: 顧問先や見込み客リストをCSVで一括照合し、候補制度、締切、除外理由、根拠URLを返す  
課金: `¥3/request` + 顧問先別cap。月商目標は1社あたり `¥10,000-¥30,000`  
実装要点:

- `X-Client-Tag` を顧問先IDとして明示利用する。
- CSV upload -> bulk evaluate -> ZIP/CSV/XLSX export を1導線にする。
- 「顧問先別月次レポート」をPDF/ZIPで出す。
- まずRBACを作らず、Slack/Sheets/メール複数宛先で共有を成立させる。

### 4.3 M&A / 与信DD Pack

対象: M&A仲介、VC、金融機関、事業会社の投資・審査部門  
価値: 法人番号を起点に、インボイス、法人基本情報、採択、行政処分、入札、法令リンクを横断し、監査可能なZIPを出す  
課金: 現行の `¥3/法人 + ZIP固定¥30` は安すぎる。P1で最低 `¥1,000/export`、案件向けは `¥3,000-¥10,000/deal ZIP` を検証する  
実装要点:

- `ma_dd.py` のDD batch/exportを商品導線の中心にする。
- ZIPに `manifest.json`、`sha256.manifest`、`cite_chain.json`、法人別JSONL、CSV summaryを入れる。
- R2署名URL、期限、再取得、監査ログを堅くする。
- 行政処分は誤結合リスクがあるため、法人番号確定と名称・住所推定を分けて表示する。

### 4.4 Saved Search / Alerts / Webhook

対象: 士業、金融、自治体支援、SaaS運営会社  
価値: 新規公募、更新、締切、採択、インボイス変更、処分、法令改正を週次またはイベントで受け取る  
課金: 保存は無料または低額、配信・Webhook・exportを `¥3/delivery` / `¥3/event` で従量  
実装要点:

- Playground検索成功後に「この条件を保存」「週次Digest」「締切カレンダー」を出す。
- 週次Digestをデフォルトにする。リアルタイムWebhookは有料の高頻度顧客向け。
- WebhookはHMAC署名、at-least-once、retry、dead-letter、SSRF防止を実装する。
- AlertとSaved Searchを重複商品にせず、Alertは「構造的変更通知」と位置づける。

### 4.5 Consultant Workpaper / Audit Pack

対象: 会計事務所、内部監査、補助金申請支援会社  
価値: 顧問先ごとに、候補制度、除外理由、必要書類、締切、根拠URL、取得日時を1ファイル化する  
課金: `¥3/request` + ZIP/PDF export最低料金  
実装要点:

- `bulk_evaluate`、`calendar/deadlines`、`exclusions/check`、`program_documents` を束ねる。
- 「unknown」を明示し、出典なしの断定をしない。
- 税務・法務助言ではなく、調査記録・作業メモ・根拠集として売る。

### 4.6 Data Export / Annual License

対象: 金融、自治体、M&A会社、大規模SaaS  
価値: APIではなく、月次/週次CSV、DB snapshot、監査ログ、差分データとして受け取れる  
課金: `¥50,000-¥300,000/月`、大口は `¥1,000,000-¥6,000,000/年` を検証  
実装要点:

- 出典、ライセンス、checksum、取得日時、parser versionを同梱する。
- 公式データの利用条件に反する再配布はしない。可能な範囲、参照リンク、派生指標、監査ログとして設計する。
- 請求書契約・SLA・サポート範囲を別紙化する。

## 5. 人がもっと使う導線

### 初回利用

1. Playgroundで匿名検索する。
2. 結果に公式URL、締切、金額、対象、除外注意を表示する。
3. 「この条件を保存」「CSVで出す」「締切をカレンダーに入れる」を表示する。
4. Trial登録後、同じ条件をDashboardに引き継ぐ。
5. key reveal画面でcurlを1つ実行できるようにする。

### 2回目利用

- Dashboard checklistを「key copy」「初回API」「保存検索1件」「週次Digest」「Deadline Calendar」「Sheets/Slack接続」にする。
- Onboarding emailは日数だけでなく、未実行行動で分岐する。
- 週次Digestは「先週増えた制度」「保存条件に合う制度」「締切間近」「除外ルール」を短く返す。

### 継続利用

- 顧問先別client_tagで利用明細を出す。
- Sheets/kintone/Slackに流す。
- Webhookで顧客側システムに接続する。
- 月末に「今月の候補制度」「採択事例」「期限」「処分・インボイス変化」をZIP化する。

人が払うのは、毎回検索するためではなく、「毎週勝手に業務に流れてくる」「監査で説明できる」「顧客別に請求・報告できる」状態である。

## 6. P0ブロッカー解除計画

P0は新機能より先。ここを越えない限り、有料GAはNo-Goである。

| ID | ブロッカー | 対応 | 完了条件 |
|---|---|---|---|
| P0-1 | 正本パス不一致 | `/Users/shigetoumeda/jpcite` を実体、Desktopリンクを再確認 | README/運用手順/デプロイが同じパスを指す |
| P0-2 | DB正本不一致 | `programs` と `jpi_programs` のどちらをAPI正本にするか決める | APIが空テーブルを読まない。data healthで0件を検知する |
| P0-3 | API host/CORS混在 | canonical API hostを1つ決定 | site/SDK/OpenAPI/CSP/CORS/Stripe return URLが一致 |
| P0-4 | 購入・trial JS不具合 | pricing/success/trial/go/dashboardの未呼び出しJSを修正 | Playwrightでcheckout mock -> key reveal -> first APIが通る |
| P0-5 | Stripe key二重発行 | webhookとsuccess endpointをtransactional helperへ集約 | 同時実行でもactive parent keyは1件 |
| P0-6 | Billing portal認証 | customer_idだけのpublic portal作成を廃止または認証必須化 | 未認証は401/404/410、Dashboard経由はCSRF/session必須 |
| P0-7 | 公開表示ドリフト | domain、key prefix、tool count、制度件数、税務ルール数を生成値に統一 | `rg`で古い表記が残らない |
| P0-8 | LLM表現ドリフト | 「AI自然文検索」「RAG」「ChatGPT前提」を商品説明から外す | 外部LLM APIなしの説明に統一 |
| P0-9 | S/A tier出典品質 | source_url、source_fetched_at、checksum、404を監査 | S/A tierの欠損・broken URLがしきい値以下 |
| P0-10 | 計測ゼロ | `usage_events` / `jpi_usage_events` を本番導線で記録 | endpoint別、key別、client_tag別の利用が見える |

## 7. データ拡張計画

### 7.1 最優先: 採択金額・採択者・制度join

売上に直結する質問は、「この法人はいくら採択されたか」「類似企業はいくらもらったか」「この制度で誰が採択されたか」である。

現状の最大課題:

- 採択件数は大きいが、採択金額coverageと制度joinが弱い。
- `program_id_hint` と制度IDが一致しないケースがある。
- 金額が実額なのか、上限額なのか、テンプレート由来なのかを分けないと信用を壊す。

追加するべき構造:

```sql
program_alias_map(source_system, source_program_key, program_id,
                  alias, match_method, score, verified_at)

adoption_amount_observations(adoption_id, amount_yen, amount_basis,
                             unknown_reason, source_id, page_no, confidence)

adoption_program_map(adoption_id, program_id, method, score,
                     evidence_json, verified_at)
```

`amount_basis` は `actual` / `ceiling` / `template_default` / `not_in_source` / `not_parsed` / `redacted` / `not_applicable` を必須にする。

### 7.2 法人マスター強化

NTA法人番号を主キーにし、gBizINFO、インボイス、採択、調達、行政処分をぶら下げる。

優先項目:

- 法人番号、名称、名称履歴、所在地、閉鎖状態
- gBizINFOの法人基本情報、届出・認定、表彰、財務、特許、調達、補助金、職場情報
- インボイス登録状態、登録日、失効日、差分更新
- 名称ゆれ、旧社名、住所断片による決定的名寄せ

追加するべき構造:

```sql
houjin_name_alias(houjin_bangou, alias, alias_type, source_id, confidence)
houjin_source_fact(houjin_bangou, fact_type, fact_json, source_id, observed_at)
entity_resolution_edges(left_kind, left_id, right_kind, right_id,
                        method, score, evidence_json, verified)
```

### 7.3 申請期限・申請URL・必要書類

補助金コンサルと士業が毎週見るのは、制度名よりも「今出せるか」「いつまでか」「何が必要か」である。

優先項目:

- `program_rounds`: 回次、開始日、終了日、事業完了期限、ステータス
- `program_documents_v2`: 公募要領、交付要綱、申請様式、必要書類、形式、URL
- `application_url`: JGrantsや事務局ページへの申請URL
- `deadline_confidence`: 公式API、PDF表、HTML本文、手入力、推定を分ける

JGrants APIは補助金一覧、詳細、受付期間、申請様式等の取得に使える。採択者一覧はJGrants APIだけに期待せず、省庁・事務局PDFから収集する。

### 7.4 行政処分・返還情報

M&A/与信DDでは、行政処分・返還・不正受給の有無が高単価価値になる。

方針:

- 法人番号が公表されないケースを前提にする。
- 法人名、所在地、省庁、制度名、金額、日付で決定的スコアリングする。
- 自動確定、要確認、unknownを分ける。
- 誤結合は信用を壊すため、`verified=false` を明示して人手確認キューに送る。

追加するべき構造:

```sql
enforcement_party_map(case_id, houjin_bangou, method, score,
                      evidence_json, verified)

enforcement_program_refs(case_id, program_id, method, score,
                         evidence_json, verified)
```

### 7.5 法令・裁判所リンク

`laws` と `am_law_article` / `am_law_reference` の資産を、制度・処分・裁判例に接続する。

方針:

- e-Gov法令APIから法令ID、本文XML、条文、更新法令一覧を取り込む。
- `program_law_refs` を0件から増やす。
- 制度、行政処分、裁判例に `law_id + article` を張る。
- 生成要約ではなく、条文ID、条見出し、URL、引用位置を返す。

### 7.6 調達・落札

金融・M&A・自治体営業にとって、落札者と落札額は価値がある。

優先項目:

- `winner_houjin_bangou`
- `awarded_amount_yen`
- `bid_result_url`
- `agency`
- `procurement_category`
- `source_id`

GEPS/調達ポータルや省庁公表資料から、利用条件と出典表記を保持して取り込む。

### 7.7 Source Manifest / Raw Documents

全データ拡張の前提として、source lineageを統一する。

```sql
source_manifest(source_id, source_url, source_type, license, etag,
                last_modified, content_hash, fetched_at,
                parser_version, status)

raw_documents(document_id, source_id, mime, bytes_hash, text_hash,
              page_count, parse_status)
```

これにより、出典検証、再パース、差分検知、監査、顧客向け説明が成立する。

## 8. LLMなしの知能化

ここで言う知能化は、外部LLM APIや生成ではない。検索品質、ルール、名寄せ、抽出、検証、評価をコード化すること。

### 8.1 Search Ranking

- SQLite FTS5 + BM25/rankを主軸にする。
- literal name match、tier、source freshness、deadline availability、amount availabilityを分離してスコア説明を返す。
- 2文字以下のクエリ、略称、かな揺れ、英字略称は辞書と正規化で扱う。
- 空検索ログから辞書候補を出すが、production反映は人手承認にする。

### 8.2 Citation Verifier

すべての有料向け応答に、出典完全性を持たせる。

検証項目:

- `source_url` がある
- `source_fetched_at` がある
- `source_checksum` が一致する
- 取得済みraw documentがある
- 引用対象フィールドがsourceから抽出されたものか、人手補完か、unknownかが分かる

### 8.3 Rule Engine

- `deny > caution > info > unknown` の順で返す。
- `hits: []` を「リスクなし」「併用可能」と扱わない。
- coverage外は `unknown` に落とす。
- 補助金の併用禁止、前提条件、対象外経費、対象者条件、締切、重複受給をルール化する。

### 8.4 Funding Stack Checker

複数制度の併用可否を返す新商品にする。

返却例:

- `ok`: 併用禁止根拠なし。ただしcoverageを表示。
- `review`: 併用注意。人手確認が必要。
- `deny`: 明確な併用禁止根拠あり。
- `unknown`: ルール未収集または出典不足。

### 8.5 Prescreen強化

`prescreen` は採択確率ではなく、申請前の適合・不足・注意を出す。

追加軸:

- 対象地域
- 業種
- 法人/個人/組合
- 従業員数
- 金額帯
- 申請期間
- 必要書類
- 前提認定
- 併用禁止
- source freshness

### 8.6 Document Parser標準化

HTML/PDFから、タイトル、金額、補助率、期限、申請URL、必要書類、問い合わせ先、対象者、対象経費を抽出する。

方針:

- 正規表現、表抽出、PDF text extraction、HTML semantic extractionを組み合わせる。
- OCRは初期スコープ外。必要になったら別途費用対効果を見る。
- 抽出結果には `parser_version`、`confidence`、`page_no`、`unknown_reason` を持たせる。

### 8.7 Self-Improvement Loops

既存の `docs/self_improve_loops.md` を本計画の改善基盤にする。ただし、production writeは必ずreview後にする。

優先するloop:

- doc freshness re-fetch priority
- alias expansion
- gold set expansion
- cache warming
- invariant expansion
- channel ROI

外部LLM APIは使わない。候補提案、クラスタリング、SQL集計、評価セット生成、人手承認で改善する。

## 9. 事前学習・ファインチューニングについて

売上最大化の観点では、今は事前学習やファインチューニングに投資しない。

理由:

- 外部LLM APIを使わない前提では、モデル運用・評価・説明責任・コストが重くなる。
- 買い手が直ちに払うのは、生成能力ではなく、採択金額、制度join、締切、必要書類、出典、監査ログである。
- データ品質が不十分なままモデルを作ると、もっとも重要な信用を壊す。

代わりにやること:

- 公式データの収集・正規化
- 辞書、同義語、名称ゆれ、法人名寄せ
- gold evaluation set
- ルールセット
- source_manifest / raw_documents
- deterministic scoring
- regression tests

「学習」はプロダクト内モデルではなく、データとルールと評価セットを育てることとして扱う。

## 10. コード化バックログ

### P0: 売上導線と信用の復旧

| ID | 実装 | 対象 |
|---|---|---|
| T-001 | DB正本監査: `programs` vs `jpi_programs`、API参照先、静的生成参照先を一覧化 | DB/API/scripts |
| T-002 | `data_health` endpoint: 正本テーブル0件、FTS不一致、source欠損、usage未記録を検知 | API |
| T-003 | API base resolverを作り、siteの相対 `/v1` fetchを統一 | site |
| T-004 | pricing/success/trial/go/dashboardのJSを外部`.src.js`化して `node --check` | site |
| T-005 | Playwright smoke: pricing -> checkout mock -> success key reveal -> first API | tests/e2e |
| T-006 | Stripe key issuanceをtransactional helperへ集約 | billing |
| T-007 | billing portalを認証必須化 | billing/me |
| T-008 | 公開claim generator: tool count、program count、tax rule count、domain、key prefixを生成 | docs/site |
| T-009 | LLM API表現監査: `AI自然文` / `RAG` / `ChatGPT前提` を言い換え | site/docs |
| T-010 | `usage_events` / `jpi_usage_events` の実記録とDashboard集計 | API/Dashboard |

### P1: 商品化

| ID | 実装 | 対象 |
|---|---|---|
| T-101 | Bulk eligibility CSV -> result CSV/XLSX/ZIP | API/site |
| T-102 | DD Export repricingと最低料金 | billing/ma_dd/docs |
| T-103 | DD ZIP manifest / cite_chain / signed URLの堅牢化 | ma_dd/R2 |
| T-104 | Saved Search作成をPlayground結果から1クリック化 | site/API |
| T-105 | Deadline Calendar UI + ICS export | calendar/site |
| T-106 | Weekly Digestを保存検索ベースで有効化 | digest/cron |
| T-107 | Slack/Sheets/kintone接続のテスト導線 | integrations |
| T-108 | Webhook subscription実装 | API/cron |
| T-109 | Consultant Workpaper ZIP | bulk/report |
| T-110 | source freshness dashboard | admin/site |

### P2: データ拡張

| ID | 実装 | 対象 |
|---|---|---|
| T-201 | `source_manifest` / `raw_documents` migration | DB |
| T-202 | JGrants detail ingest: 受付期間、申請URL、書類 | ingest |
| T-203 | `program_rounds` / `program_documents_v2` | DB/API |
| T-204 | 採択金額observationとbasis分類 | ingest/DB |
| T-205 | adoption -> program join map | ingest/DB |
| T-206 | NTA法人番号 + gBizINFO + invoice統合 | ingest/DB |
| T-207 | enforcement party map | ingest/DB |
| T-208 | e-Gov law article importとprogram_law_refs | ingest/DB |
| T-209 | procurement winner/amount ingest | ingest/DB |
| T-210 | daily data quality report | scripts/docs |

### P3: 品質・差別化

| ID | 実装 | 対象 |
|---|---|---|
| T-301 | Citation verifier service | services/API |
| T-302 | Ranking explanation | programs API |
| T-303 | Funding stack checker | API/MCP |
| T-304 | Prescreen強化 | API |
| T-305 | rule coverage dashboard | admin |
| T-306 | alias dictionary review workflow | self_improve |
| T-307 | gold evaluation expansion | evals |
| T-308 | parser benchmark | tests/data |
| T-309 | P95/egress/fields=full gate | middleware |
| T-310 | annual data license export job | export/billing |

## 11. 30 / 60 / 90 / 180日ロードマップ

基準日: 2026-04-30

### 0-30日: 2026-04-30から2026-05-30

目的: 有料導線と信用を壊すP0を解除する。

成果物:

- 正本パスとDB正本の決定
- API host/CORS/CSP/SDK/OpenAPI/Stripe URLの統一
- pricing/success/trial/go/dashboardのJS修復
- checkout mockからkey revealまでのE2E
- key二重発行防止
- billing portal認証
- 公開表示ドリフト修正
- LLM APIなし表現への統一
- data health / usage health の最低限ダッシュボード

No-Go:

- APIが空テーブルを読む
- key revealが壊れている
- 未認証billing portalが残る
- 外部LLM API前提の訴求が残る
- S/A tierの出典欠損を検知できない

### 31-60日: 2026-05-31から2026-06-29

目的: 売れる4商品を出す。

成果物:

- Developer API PackのDashboard整備
- Agency PackのCSV一括診断
- M&A/与信DD ZIPの有料導線
- Saved Search / Weekly Digest
- Deadline Calendar / ICS
- Sheets/Slack/kintone接続
- export最低料金の導入
- 顧問先別client_tag利用明細

KPI:

- checkout完了から初回API成功率
- 初回APIまでの中央値
- 保存検索作成率
- 週次Digest有効化率
- DD ZIP export数
- endpoint別billable requests

### 61-90日: 2026-06-30から2026-07-29

目的: データ品質を売上の堀にする。

成果物:

- source_manifest / raw_documents
- JGrants detail ingest
- program_rounds / documents_v2
- adoption amount observations
- adoption -> program join
- e-Gov law article import
- citation verifier
- funding stack checker
- prescreen強化
- gold eval set

KPI:

- 採択金額実額coverage
- 制度join率
- 申請期限coverage
- 必要書類coverage
- source_url coverage
- checksum一致率
- `unknown` 明示率
- false allow 0

### 91-180日: 2026-07-30から2026-10-27

目的: 高単価化と継続収益を作る。

成果物:

- Data Export Subscription
- Annual Data License
- 業種別パック: 建設、製造、医療、飲食、不動産、金融
- Consultant Workpaperテンプレート
- Compliance Monitoring Network
- Webhook beta -> GA
- 代理店/士業パートナー運用
- 請求書契約とSLA

KPI:

- 月商
- paid customers
- ARPA
- DD/export売上
- Data license商談数
- saved searches/key
- active webhooks
- monthly retained revenue
- churn

## 12. 価格と売上仮説

### 基本方針

`¥3/request` は裏側の課金メーターとして残す。ただし、表の商品は「1リクエスト」ではなく「業務成果物」で見せる。

### 初期価格

| 商品 | 価格案 |
|---|---:|
| REST/MCP API | `¥3/request` |
| 月cap preset | `¥3,300` / `¥33,000` / `¥110,000` |
| Agency Pack | 顧問先別cap、月 `¥10,000-¥30,000` 目標 |
| Saved Search delivery | `¥3/delivery` |
| Webhook event | `¥3/event` |
| DD batch | `¥3/法人` |
| DD ZIP | P1で最低 `¥1,000/export`、案件は `¥3,000-¥10,000` 検証 |
| Workpaper ZIP | 最低料金 + 従量 |
| Data Export | `¥50,000-¥300,000/月` |
| Annual License | `¥1,000,000-¥6,000,000/年` |

### 売上仮説

- P0解除後: 30社が月 `¥10,000-¥30,000` cap運用、5社が高頻度API利用で月商 `¥600,000-¥1,500,000` を狙う。
- P1: DD/export最低料金でARPAを上げる。M&A/与信は `¥3/request` だけでは価値を取り切れない。
- P2: Saved Search、Digest、Webhookで継続利用を作る。
- P3: Data Licenseと代理店運用で、従量だけでは届かない大口契約を作る。

## 13. KPI

### Activation

- Playground検索成功率
- trial作成率
- checkout完了率
- key reveal成功率
- key copy率
- 初回API成功率
- 初回APIまでの中央値

### Retention

- D1/D7/D30再訪率
- 保存検索作成率
- 週次Digest有効化率
- Digest open / click
- Deadline Calendar / ICS export
- Sheets/Slack/kintone接続率
- active webhook数

### Revenue

- billable requests
- endpoint別売上
- customer cap消化率
- client_tag数
- DD batch件数
- DD ZIP export数
- Workpaper ZIP数
- data export契約数
- ARPA
- churn

### Data Quality

- source_url coverage
- source_fetched_at coverage
- checksum一致率
- S/A tier broken URL数
- 採択金額実額coverage
- adoption -> program join率
- 法人番号join率
- 申請期限coverage
- 必要書類coverage
- `end_date < start_date` 件数
- `unknown` 明示率

### Reliability

- p95 latency
- 5xx rate
- checkout/key issue error率
- webhook delivery success率
- digest delivery success率
- parser failure率
- FTS syntax error率
- response-size cap violation数

## 14. 公式データソース方針

公式・一次情報を優先する。

- JGrants: 補助金一覧、詳細、受付期間、申請URL、書類情報。
- NTA法人番号: 法人番号、基本3情報、変更履歴、差分。
- インボイス公表情報: 全件データ、差分データ、OpenPGP署名検証。
- gBizINFO: 法人基本情報、届出・認定、表彰、財務、特許、調達、補助金、職場情報。
- e-Gov法令API: 法令名一覧、法令本文XML、条文、更新法令一覧。
- 裁判所: 判例検索、事件番号、裁判日、裁判所、PDF。
- 調達ポータル/省庁公表: 落札者、落札額、案件、出典。
- 自治体公式サイト: PDF、HTML、公募要領、申請様式。

参考:

- JGrants API: https://developers.digital.go.jp/documents/jgrants/api/
- NTA法人番号Web-API: https://www.houjin-bangou.nta.go.jp/webapi/index.html
- インボイス公表情報ダウンロード: https://www.invoice-kohyo.nta.go.jp/download/index.html
- gBizINFO API: https://content.info.gbiz.go.jp/api/index.html
- e-Gov法令API: https://laws.e-gov.go.jp/docs/law-data-basic/8529371-law-api-v1/
- MCP Tools spec: https://modelcontextprotocol.io/specification/2025-06-18/server/tools

## 15. 市場上の示唆

JGrantsのような無料の公的入口があっても、業務成果物、顧客管理、申請支援、監視、専門家運用には支払い余地がある。補助金クラウド for SMEs は月額3万円税別の価格を公式ページで提示しており、補助金探索・提案・申請支援の周辺業務には月額課金が成立している。

このプロジェクトは申請代行ではなく、API/データ/監査ログ/業務連携に寄せる。そのため、競合と正面衝突するより、士業・コンサル・SaaS・金融の裏側に入る方がよい。

参考:

- 補助金クラウド for SMEs: https://www.hojyokincloud.jp/smes/

## 16. やらないこと

- 外部LLM APIを呼ぶ機能。
- ファインチューニングや事前学習を短期の売上施策にすること。
- 出典なし自然文レポート。
- 採択確率の断定。
- 法務・税務アドバイスの断定。
- `hits: []` を安全判定として売ること。
- UX導線が壊れたまま新機能を積むこと。
- 空テーブルやドリフトした件数で公開すること。
- DD ZIPを安すぎる固定料金のまま放置すること。
- 代理店・大口契約より先に複雑なRBACを作り込むこと。

## 17. 最終提案

このプロジェクトで売上を作る一番短い道は、LLM APIを使わず、公式データと決定的な処理を業務成果物に変えることである。

最初にやるべきことは、P0解除である。特に、DB正本、API host、購入導線、key reveal、billing認証、公開表示ドリフト、LLM表現ドリフトを直さない限り、有料GAは危険である。

広義の商品群は次の4つである。ただし、極み版では最初の60日は `Agency / Advisor Pack` に絞り、顧問先一括診断、週次Digest、月次ZIPを先に検証する。

1. Developer API Pack
2. Agency / Advisor Pack
3. M&A / 与信DD Pack
4. Saved Search / Alerts / Webhook

そして、90日以内に採択金額、制度join、法人マスター、申請期限、必要書類、法令リンク、出典検証を強くする。ここが強くなるほど、単なる検索サイトではなく、会計・補助金・M&A・金融の実務データ基盤になる。

結論として、価値最大化の順番は次で固定する。

1. 信頼と購入導線を直す。
2. 既存機能を業務商品に束ねる。
3. 採択金額・制度join・法人名寄せを強化する。
4. 出典検証・ルール・評価セットをコード化する。
5. 継続監視とデータライセンスで高単価化する。

これが、LLM APIなしで人が使い続け、課金し続けるプロダクトにするための実行計画である。

## 18. 極み版追補: 勝ち筋を一度絞る

ここまでの計画は広い。極み版では、最初の60日は主戦場を一つに絞る。

最初に売るのは、士業・補助金コンサル・認定支援機関向けの **顧問先一括診断 + 月次監査ZIP + 週次Digest** である。

M&A/DD、金融、自治体、VC、データライセンスは後続展開にする。理由は明確である。

- 士業・補助金コンサルは顧問先リストを持っており、CSV一括診断と月次レポートの利用頻度が高い。
- 週次Digest、Slack/Sheets/kintone、顧問先別利用明細が継続課金に直結する。
- M&A/DDやData Licenseは単価が高いが、出典・ライセンス・採択金額・誤結合リスクの条件がより厳しい。
- まず「毎週使う業務ループ」を作らないと、単発検索APIで終わる。

したがって、商品優先順位を次に変更する。

| 優先 | 商品 | 位置づけ |
|---:|---|---|
| 1 | Advisor / Agency Pack | 最初の主戦場。顧問先CSV、bulk evaluate、saved search、Digest、月次ZIP |
| 2 | Developer Metered | 入口。`¥3/unit` の長尾利用。主力収益ではない |
| 3 | M&A / DD Deal Pack | 出典・誤結合・価格を整えてから高単価化 |
| 4 | Data Export / License | 再配布可能範囲とlicense gating確定後 |
| 5 | 自治体・金融・VC向け展開 | 実績と品質KPIを持ってから営業 |

## 19. 極み版P0: GA前に絶対通すゲート

P0は「購入導線を直す」だけでは足りない。DB正本、課金計測、No-LLM違反、法務表示、CORS、E2Eがすべて緑でない限り、有料GAはNo-Goである。

### 19.1 DB正本マトリクス

現状の問題は単なる空テーブルではない。REST、MCP、cron、静的生成、root DBで正本が分裂していることが問題である。

| 実行面 | 正本 | 禁止 |
|---|---|---|
| REST API / site検索 | `data/jpintel.db` の `programs` / `usage_events` | 空DB自動生成、root `autonomath.db` への暗黙fallback |
| MCP / AutonoMath拡張 | `autonomath.db` の `jpi_*` / `am_*` | `programs` / `programs_fts` の混入 |
| 静的ページ生成 | 明示された正本DBのみ | Desktopの壊れたsymlink参照 |
| cron / ingest | 実行対象DBを引数・envで明示 | 存在しないDBを作って成功扱い |
| analytics / billing | `usage_events.quantity` を含む本番schema | quantityなしDBで課金開始 |

GA条件:

- `/Users/shigetoumeda/Desktop/jpintel-mcp` の壊れたsymlinkを運用・手順・CIから排除する。
- `scripts/schema_guard.py data/jpintel.db jpintel` がPASSする。
- `scripts/schema_guard.py autonomath.db autonomath` がPASSする。
- `data/jpintel.db` は `programs > 10000`、`programs_fts > 10000`、`usage_events.quantity` 有り。
- `autonomath.db` は `am_entities > 500000`、`jpi_programs > 13000`、forbidden `programs` / `programs_fts` なし。
- 認証APIを1回呼ぶと `usage_events` が1件増え、`quantity`、`client_tag`、`metered` が記録される。

### 19.2 課金計測スキーマ

高単価バッチ、DD、監査ZIPを売る前に、課金計測が壊れていないことを証明する。

必須条件:

- `schema.sql`、migration、実DB、テストDBの `usage_events` が一致する。
- `quantity`、`client_tag`、`stripe_record_id`、`stripe_synced_at` の扱いが一致する。
- `bulk_evaluate`、`dd_export`、saved search delivery、webhook delivery、audit workpaperが二重課金しない。
- Stripe送信失敗時にローカルusageだけが増え続けない。
- 実送信・実生成に失敗した成果物はbillableにしない。

### 19.3 No-LLM例外の撤去

ユーザー前提では、外部LLM API禁止に例外はない。runtimeだけでなく、dev、ops、ETL、翻訳、評価、cron、backfillも対象である。

No-Go:

- `anthropic` / `openai` / `google.generativeai` / `gemini` importが残る。
- `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` / `GEMINI_API_KEY` を使うETLが残る。
- 「single sanctioned exception」のような例外文言が残る。
- CIで禁止import、禁止env、禁止egressを検出できない。

特に `scripts/etl/batch_translate_corpus.py` のような外部LLM API前提コードは、削除、隔離、またはCI禁止対象にする。

### 19.4 Host / CORS / CSP

購入導線より前に、API hostを1つに固定する。

GA条件:

- site、SDK、OpenAPI、CSP、CORS、Stripe return URLが同じcanonical hostを指す。
- `https://jpcite.com` から `https://api.jpcite.com` へのpreflightが200。
- 悪性Originは403。
- `api.jpcite.com`、`api.autonomath.ai`、`autonomath.jp` 系は、使わないなら公開面から消す。

### 19.5 購入・trial・success E2E

最低限のE2E:

- pricing -> Stripe checkout mock -> success key reveal -> 初回API -> usage row作成
- trial magic link -> key reveal -> 初回API -> trial counter +1
- `/v1/billing/portal` は未認証で成功しない
- portalは `/v1/me/billing-portal` のみ
- 同一checkout session / subscriptionへ20並列POSTしてactive keyは1つ
- JS inline scriptは `node` / `vm.Script` / Playwrightで構文エラーゼロ
- console error / pageerror はCI fail

### 19.6 GA Kill Switch

機能別に止められることをP0にする。

| 機能 | Kill条件 | 停止内容 |
|---|---|---|
| paid search | 有料APIが500、usage記録失敗 | 課金API停止、無料検索のみ |
| DD export | 誤結合、R2署名URL、license gating未達 | ZIP生成停止 |
| saved digest | 誤配送、unsubscribe不一致、実送信失敗 | digest停止 |
| webhook | retry暴走、SSRF懸念、署名不一致 | webhook dispatch停止 |
| fields=full | egress急増、PII漏れ、license不明 | full fields停止 |
| data license | license unknown/proprietary混入 | export停止 |

## 20. Revenue Packaging: `¥3/unit` を内部メーターにする

`¥3/request` は残す。ただし、公開主力価格ではなく内部消費単位として扱う。

公開パッケージは、最低料金、月額枠、年契約、成果物単位で設計する。

| SKU | 価格案 | 役割 |
|---|---:|---|
| Free | 50 req/月/IP | 検索・件数確認だけ。CSV/ZIP/Webhook/DD不可 |
| Developer Metered | `¥3/unit`、最低なし | 長尾開発者向け入口 |
| Starter | `¥9,800/月`、3,000 units込み、超過 `¥3/unit` | 最小有料枠 |
| Advisor | `¥49,800/月`、15,000 units込み | 顧問先CSV、bulk evaluate、saved search、Digest |
| Agency Pro | `¥148,000/月` または `¥1,500,000/年` | 500顧問先、Slack/Webhook、月次ZIP |
| M&A/DD Basic | `¥30,000/案件` | 監査可能な基本DD ZIP |
| M&A/DD Full | `¥100,000/案件` | group graph、処分、採択、調達、インボイス横断 |
| Portfolio DD | `¥300,000+` | 複数法人・複数案件 |
| Audit Firm Pack | `¥300,000/案件` または `¥1,200,000/年` 最低 | 監査ワークペーパー |
| Data License | `¥500,000/月` から | license gating後。派生factと差分中心 |

この価格にする理由:

- 補助金クラウド for SMEs は月額3万円税別を公式に提示しており、補助金周辺業務には月額課金余地がある。
- 企業情報・与信系データは1社単位の従量課金が成立している。DD ZIPを`¥30`固定で売るのは価値を取り逃がす。
- `¥3/unit` は安さの訴求ではなく、利用量の透明性として残す。

参考:

- 補助金クラウド for SMEs: https://www.hojyokincloud.jp/smes/
- G-Search 企業情報横断検索 料金一覧: https://db.g-search.or.jp/price_comp.html
- 帝国データバンク DataDrive: https://www.tdb.co.jp/services/lineup/datadrive/
- TDB企業サーチ: https://www.tdb.co.jp/services/lineup/tcs/

無料から有料へのゲート:

- 無料: 検索・件数確認・サンプルのみ
- Trial: 14日/200 req、成果物は透かしまたは制限付き
- 有料: CSV/XLSX/ZIP、saved search delivery、webhook、DD ZIP、audit workpaper、client_tag明細

## 21. Agency / Reseller Program

紹介制度と代理店制度を分ける。

| 制度 | 内容 |
|---|---|
| Referral | 10%紹介料。単発紹介。サポート義務なし |
| Reseller | 年60万-180万円の最低コミット、20%販売マージン、L1サポート義務、値引き禁止 |
| OEM / SaaS組込 | 親子APIキー、月額最低、利用枠前払い、再販先の利用明細 |

代理店は値引きではなく、前払い利用枠と再販マージンで設計する。親子APIキーはOEM/代理店管理の根拠になる。

## 22. UX / Retention Revenue Loop

継続課金の本丸は、検索ではなく業務ループである。

### 22.1 初回成功の定義

15分以内に次を完了できる状態を「初回成功」とする。

1. key発行・保存
2. 初回APIまたはノーコード検索成功
3. 検索条件の保存
4. 通知先テスト
5. 最初のCSV/ZIP/レポート生成

計測イベント:

- `first_api_success`
- `first_saved_search`
- `first_connector_test`
- `first_report_generated`
- `first_client_profile_imported`

### 22.2 週次業務の型

| 曜日 | 業務 | 出力 |
|---|---|---|
| 月曜 | 週次Digest | 新着制度、期限接近、除外注意 |
| 水曜 | saved search差分確認 | Slack/Sheets/kintone/Webhook |
| 金曜 | 顧問先・案件別レポート | ZIP/PDF/XLSX |

変更が0件でも、「新着0、期限接近N件、未対応N件、出典更新N件」として価値を返す。

### 22.3 顧問先運用

`client_profiles` を中心に、CSVインポート、saved searchひも付け、bulk evaluate、`X-Client-Tag` 別利用量、月次レポートまで一気通貫にする。

最初は重いRBACを作らない。共有メール、Slackチャンネル、Sheets/kintone、読み取り専用レポートリンクで実用化する。

### 22.4 Integrations Center

Slack、Sheets、kintone、Webhook、Email、LINEを1画面にまとめる。

各カードに出すもの:

- 接続状態
- 最終成功
- 最終失敗
- テスト送信
- 再接続
- 配信履歴
- billable / non-billable

### 22.5 Report Center

saved search XLSX/CSV/ICS、bulk evaluate ZIP、四半期PDF、顧問先月次レポート、DDパックを1画面に集約する。

状態:

- 生成中
- 失敗
- 再実行
- 請求済み
- manifest
- 共有
- 再ダウンロード

これが継続課金の実感値になる。

### 22.6 失敗時リカバリ

エラー文だけで終わらせない。すべて「次の行動」に変換する。

| 失敗 | 次の行動 |
|---|---|
| invalid key | key再入力、再発行、サポート |
| 0件ヒット | 条件緩和、サンプル検索、保存条件変更 |
| quota/cap | cap増額、当月停止、通知先変更 |
| 支払い失敗 | カード更新、請求書相談、読み取り専用維持 |
| Slack失敗 | 再接続、別channel、email fallback |
| Sheets/kintone認証切れ | 再OAuth、権限確認 |
| webhook auto-disable | テスト送信、secret rotate、delivery log |
| LINE無料枠超過 | Web dashboard誘導、有料化 |
| データ鮮度注意 | 出典確認、再取得予約、unknown表示 |

## 23. Official Source Evidence Graph

Data Moatは件数ではなく、公式ソースから再現可能な証拠付きfact graphで作る。

中核4層:

1. `source_manifest`: 公式URL、発行主体、license、robots/TOS確認、取得時刻、ETag、Last-Modified、hash、job、parser version
2. `raw_documents`: PDF/CSV/HTML/XML原本hash、本文hash、ページ数、OCR有無、保存場所、取得失敗理由
3. `extracted_observations`: 採択金額、採択法人、制度名、回次、落札金額、法令条文をページ・行・セル単位で保存
4. `resolved_edges`: 法人番号、インボイス番号、gBizINFO、JGrants制度、e-Gov法令、裁判例、調達案件へのjoinを保存

### 23.1 Unknown Taxonomy

`NULL` を放置しない。unknown理由を商品価値として扱う。

| 領域 | unknown_reason |
|---|---|
| 採択金額 | `not_published`, `pdf_not_parsed`, `redacted`, `aggregate_only`, `needs_review`, `source_conflict` |
| 法人join | `sole_proprietor_or_unresolved`, `name_ambiguous`, `address_missing`, `closed_or_merged`, `needs_review` |
| 制度join | `unmatched`, `ambiguous`, `round_missing`, `source_program_name_conflict` |
| 法令join | `article_not_parsed`, `law_id_missing`, `old_law_name`, `needs_review` |
| 調達 | `winner_not_published`, `amount_not_published`, `pdf_table_failed`, `needs_review` |

推定値は公式値と混ぜない。`estimated_*` は別列または別テーブルに隔離する。

### 23.2 Human Review Queue

曖昧・高価値・競合データは人手確認へ送る。

投入条件:

- 高額採択・高額落札
- 制度joinが複数候補
- 法人名が一致するが住所が違う
- source conflict
- S/A tierのsource broken
- license unknown/proprietary
- DD export対象に含まれる曖昧edge

キューには、対象ID、候補、根拠URL、raw document位置、diff、推奨アクション、期限を持たせる。

## 24. License / Redistribution Gate

Data LicenseやDB snapshot販売は、法的確認なしに断定しない。まず売るのは「派生fact + source URL + checksum + 監査ログ + 差分」である。

| source | まず許容する形 | 禁止または要確認 |
|---|---|---|
| JGrants | 制度ID、公開URL、受付期間、派生index | APIレスポンス丸ごと再配布 |
| NTA法人番号 | 公開仕様に沿った基本情報・差分参照 | 利用条件外の大量再配布 |
| インボイス | 登録状態、番号照合、差分参照 | 個人事業主情報の過剰露出 |
| gBizINFO | 法人番号keyのfact参照 | 原データ丸ごと販売 |
| e-Gov法令 | law_id、条文参照、URL | 本文全文の無条件再配布 |
| 裁判所 | 事件番号、裁判日、裁判所、URL | PDF丸ごと二次配布 |
| 自治体PDF | URL、抽出fact、checksum | robots/TOS未確認のbulk export |

`license in ('unknown','proprietary')` は、契約で許諾確認済みの用途以外、bulk export、年間ライセンス、二次商用再配布から除外する。

## 25. Trust / Legal / Risk No-Go

有料化前のNo-Go:

- 外部LLM API禁止に違反するコード、env、CI、cron、ETLが残る。
- 公開法務文書に「AI生成物」「RAG」「hallucination」など、プロダクト本体が生成AI応答を返すように見える表現が残る。
- Privacyがcookieなし/localStorageなしと書きつつ、実装がAPI keyやemailをlocalStorage/sessionStorageに保存している。
- raw IP / UAを保存しているのにPrivacyへ明示していない。
- SLA、ToS、site版ToSでcredit、稼働率、返金条件が違う。
- `sample_count=0` なのに uptime 100%、品質100% のように表示する。
- `source_url/source_fetched_at/source_checksum/license` 欠損行を監査・DD・Data License・有料レポートに含める。
- `license unknown/proprietary` をexport eligibleにする。
- 代表者名・郵便番号・個人事業主インボイスなどの公開個人情報に、削除・抑止・異議申立て導線がない。

### Trust Dashboard

Trust Dashboardは宣伝ではなく、出荷判定の計器にする。

| 面 | 指標 |
|---|---|
| Source Health | source_url/fetched_at/checksum coverage、S/A checksum欠損、dead URL、staleness |
| License | public/gov/CC/unknown/proprietary件数、export eligible件数、quarantine |
| Quality | correction_log、pending corrections、quality_metrics_daily、cross-source agreement |
| Privacy/Security | PII redaction hits、raw IP保存状態、Sentry scrub、data subject request SLA |
| No-LLM Invariant | forbidden imports、forbidden env vars、external egress、LLM cost rows |
| Availability/Billing | uptime、p95、sample_count、Stripe webhook health、二重発行検知 |
| Audit/Reproducibility | corpus_snapshot_id、corpus_checksum、reproducibility_snapshots、amendment diff |

SLA数値はsample_countと計測条件を伴う場合のみ表示する。sample_count=0は「データ不足」であり、100%ではない。

## 26. 30日獲得実験

市場証明は仮説ではなく、30日で取る。

対象は士業・補助金コンサル・認定支援機関に絞る。

| 期間 | 実験 | 成功条件 |
|---|---|---|
| Week 1 | 20事務所へ個別接触 | 5件の課題ヒアリング |
| Week 2 | 顧問先CSVを預からず、匿名テンプレCSVでデモ | 3件のpilot同意 |
| Week 3 | 顧問先一括診断 + 週次Digest + 月次ZIPを試用 | 2件が実業務で利用 |
| Week 4 | `¥49,800/月` または年契約を提示 | 1-3件のpaid conversion |

追う指標:

- 初回CSV uploadまでの時間
- 初回ZIP生成までの時間
- 週次Digest開封
- 顧問先別client_tag数
- 1社あたり月間unit消費
- レポート共有回数
- paid conversion
- 解約理由・拒否理由

この実験で「顧問先一括診断 + 週次Digest + 月次ZIP」に支払い意欲が出なければ、M&A/DDやData Licenseへ拡張する前に商品設計を戻す。

## 27. 極み版の最終優先順位

既存計画をさらに絞ると、優先順位は次で固定する。

1. No-LLM違反コードと法務文言を撤去する。
2. DB正本、usage schema、host/CORS、billing portal、key raceをP0で潰す。
3. 士業・補助金コンサル向けに、顧問先一括診断 + 週次Digest + 月次ZIPを出す。
4. `¥3/unit` を内部メーターにし、公開価格はStarter/Advisor/Agency Proへ移す。
5. Official Source Evidence Graphを作り、source/raw/observation/edgeを中核にする。
6. unknown_reasonとhuman review queueで、不明を価値ある品質情報に変える。
7. Trust Dashboardを出荷判定の計器にする。
8. 30日で20事務所接触、5ヒアリング、3pilot、1-3paidを検証する。
9. M&A/DD高単価化は、誤結合・license・cite_chain・価格を整えてから出す。
10. Data Licenseは、再配布可能範囲が確定した派生factと差分から始める。

## 28. 10日思考版: Evidence-backed Advisor Loop

さらに突き詰めると、jpciteが勝てる道は「AIチャットを作ること」ではなく、「人間の業務と顧客側AI/agentの両方が、同じ根拠付きデータを毎週参照する状態」を作ることにある。

したがって、人に使われる導線、AIに使われる導線、オーガニックに伸びる導線を別々に設計しない。1つのループに統合する。

**Evidence-backed Advisor Loop**

`顧問先CSV -> bulk evaluate -> saved search -> 週次Digest -> 月次ZIP/監査ログ -> 実務記事/API/MCP事例化 -> 新規流入 -> 次の顧問先CSV`

このループでは、jpcite本体は外部LLM APIを呼ばない。返すものは、制度、法人、採択、締切、出典URL、取得日時、checksum、license、unknown_reason、除外理由、次に呼ぶべきendpoint、監査ログである。顧客側のAI/agentがそれをMCP/REST/OpenAPI経由で読む構成は許容するが、jpcite側のruntime、ETL、cron、CI、評価、翻訳、SDK、MCP serverは外部LLM APIを呼ばない。

### 28.1 何が人に使われるか

人間が継続利用するのは「検索API」ではなく、業務の締切、差分、顧問先への提案、請求根拠を毎週減らす仕組みである。

採用される機能:

- 顧問先CSV / 案件CSVの一括投入
- `bulk_evaluate` による顧問先別の制度候補、除外理由、根拠URL、月次ZIP
- `saved_searches` による週次Digest、締切差分、制度変更検知
- Slack / Sheets / kintone / email / webhookへの配信
- Report CenterでのCSV/XLSX/ICS/ZIP再生成、共有、manifest確認
- Integrations Centerでの接続状態、最終成功、最終失敗、再接続、テスト送信、配信履歴
- 0件、認証切れ、quota超過、webhook disable、Sheets/kintone失敗、支払い失敗を「次に押すボタン」へ変換する復旧UI

採用されにくい機能:

- 単発検索だけのDashboard
- MCP tool数だけを訴求するページ
- LINE単体の低単価課金
- 大量の抽象的なAI記事
- M&A/DDやData Licenseを、根拠graphとlicense gateなしで前面に出すこと

週次・月次の業務カレンダー:

| タイミング | 利用行動 | jpciteが出す成果物 |
|---|---|---|
| 月曜朝 | 顧問先別の新着・締切確認 | 週次Digest、上位候補、除外理由 |
| 水曜 | saved searchの差分確認 | 制度変更、締切変更、source更新 |
| 金曜 | 顧問先提案の下書き | 顧問先別CSV/XLSX、引用付き候補一覧 |
| 月末 | 顧問先報告・請求根拠確認 | 月次ZIP、manifest、client_tag別利用明細 |

主戦場は士業、補助金コンサル、認定支援機関に固定する。中小企業単体はLINE、email、kintone内表示の入口として扱い、最初の主収益にはしない。M&A/金融はDD ZIPの高単価余地があるが、採択金額coverage、法人名寄せ、行政処分、license、cite_chainが整うまで後段に置く。自治体支援は年契約余地があるが、稟議と調達が重いため、Advisor Packの実績後に広げる。

### 28.2 何がAI/agentに使われるか

AI/agentに使われる条件は、「jpciteがAI応答を生成すること」ではない。顧客側AI/agentが、迷わず、安全に、安定して、引用付き構造化データを呼べることである。

AI/agent向け入口:

- MCP: read-only toolsを主入口にし、`discovery`、`monitoring`、`due_diligence`、`tax_risk`、`integration` のtool pack manifestを用意する。
- REST/OpenAPI: Zapier、Make、RPA、Sheets、Slack向けに、検索、詳細、batch、saved search、webhook、health/metaのsubsetを切る。
- IDE/agent: Cursor、Cline、Continue、Claude Desktopなどの顧客側client向けに、`mcp.json`、API key設定、失敗時診断、最小tool chainを用意する。
- 社内bot: Slack/Teams botは要約文ではなく、引用URL、締切、根拠フィールド、追加確認リンクを返す。

全agent-facing endpoint/toolは、通常時も空振り時も同じ構造を返す。

```json
{
  "status": "rich | sparse | empty | partial | error",
  "query_echo": {
    "normalized_input": {},
    "applied_filters": {},
    "unparsed_terms": []
  },
  "results": [],
  "citations": [],
  "warnings": [],
  "suggested_actions": [],
  "meta": {
    "request_id": "...",
    "api_version": "...",
    "latency_ms": 0,
    "billable_units": 0,
    "client_tag": "..."
  }
}
```

空配列だけを返さない。`status=empty` のときは、`empty_reason` と `retry_with` を必ず返し、「本当に存在しない」「条件が狭すぎる」「source未取得」「license上返せない」を区別する。

共通citation model:

| フィールド | 目的 |
|---|---|
| `source_id` | source正本とのjoin |
| `source_url` | 一次資料への到達 |
| `publisher` | 発行主体 |
| `title` | 出典タイトル |
| `fetched_at` | 取得日時 |
| `checksum` | 再現性 |
| `license` | 再配布可否 |
| `field_paths` | どの値の根拠か |
| `excerpt` / `page_ref` | 短い確認材料 |
| `verification_status` | verified / inferred / stale / unknown |
| `citation_text_ja` | Slackや稟議書に貼る短文 |
| `citation_markdown` | docs/report用 |

REST、MCP、SDK、middlewareのエラーは単一envelopeに統一する。

```json
{
  "error": {
    "code": "RATE_LIMITED",
    "user_message": "...",
    "developer_message": "...",
    "retryable": true,
    "retry_after": 60,
    "documentation": "..."
  },
  "request_id": "..."
}
```

`message` / `user_message`、`rate_limited` / `rate_limit_exceeded`、host名、env名、tool名、引数名の揺れは、AI/agentの自動復旧を壊す。`api.jpcite.com`、`AUTONOMATH_API_KEY`、`AUTONOMATH_API_BASE`、実在tool名、実在引数を正本化し、旧名はdeprecation warningにする。

### 28.3 AI / Developer Distributionを成長導線にする

AIツールと開発者が自然に採用するには、機能より先に配布面の不整合をなくす必要がある。runtime上のtool数、README、`mcp-server.json`、DXT、Smithery、OpenAPI path数、PyPI/npm package、SDK名、ブランド名、canonical domainがずれると、AI crawler、MCP registry、開発者の全員が「どれが正か」を判断できない。

Canonical Distribution Manifestを1つ作り、これを配布の正本にする。

```yaml
product: jpcite
canonical_domains:
  site: https://jpcite.com
  api: https://api.jpcite.com
canonical_mcp_package: autonomath-mcp
canonical_api_env:
  key: AUTONOMATH_API_KEY
  base: AUTONOMATH_API_BASE
mcp:
  tool_count: <runtimeから生成>
  resource_count: <runtimeから生成>
  prompt_count: <runtimeから生成>
openapi:
  path_count: <docs/openapi/v1.jsonから生成>
trust:
  security_txt: https://jpcite.com/.well-known/security.txt
  status_json: https://jpcite.com/status.json
  health_sla: https://api.jpcite.com/v1/health/sla
```

このmanifestから、README、MCP Registry `server.json`、DXT、Smithery、SDK README、examples、`llms.txt`、API docsを生成または検証する。CIはdriftを検出したらfailする。

配布優先順位:

1. Official MCP Registry掲載を最優先にする。
2. PyPI `autonomath-mcp` のversion、README、`mcp-name`、GitHub namespaceを揃える。
3. DXT / Smithery / MCPBを同じmanifestから再生成する。
4. Python / TypeScript SDKは、公開済みpackageだけをpublic docsに載せる。未公開ならpreview扱いにする。
5. examplesは3分以内に成功する導線に絞る。

3分導入の最小セット:

- anonymous REST read
- API key付きREST read
- Python `requests`
- TypeScript `fetch`
- MCP client via `uvx autonomath-mcp`
- DXT install

Trust surfaceもAI-readableにする。

- `/.well-known/security.txt`
- `/v1/health/sla`
- `/v1/staleness`
- corrections feed
- OpenAPI JSON
- status JSON
- data source freshness
- known limitations

これらを `llms.txt` / `llms-full.txt` / docsから辿れるようにし、「何ができるか」「何ができないか」「根拠はどこか」「どのsourceが古いか」を機械的に読める状態にする。

### 28.4 Organic Growth / SEO / GEO

オーガニック成長は、ページを大量生成することではない。一次資料、更新履歴、比較、透明性、開発者導線、配布registry、実務事例を積み上げることで発生させる。

先に直す信頼ブロッカー:

1. 公開値の単一化
   `llms.txt`、README、比較ページ、SEO docs、sitemap、DB件数の数字を一致させる。総件数、indexable件数、静的HTML件数、Q&A件数、MCP tool数、OpenAPI path数を分けて表示する。

2. ブランド統一
   QA、比較、透明性、schema.org、security docsに残る旧名を `jpcite / AutonoMath` に統一する。旧名は必要な場合だけ `formerly` として扱う。

3. sitemap / robots / generator整合
   `/structured/` をGEO資産にするならrobots方針を変える。使わないならHTML埋め込みJSON-LDを正と明記する。

4. 退役URL導線
   削減済みQA、industry、cross、program URLは、topic hubや制度family hubへ関連リダイレクトする。単純な `/qa/` 返しは検索意図を失いやすい。

5. 比較ページのファクト更新
   jGrants、gBizINFO、ミラサポplus、Navit、補助金クラウドなどの比較ページは、公式URL、最終確認日、相手を使うべき場面、併用すべき場面、訂正受付導線を入れる。

狙う検索導線:

| クエリ群 | 例 | 到達先 |
|---|---|---|
| 制度名 | `ものづくり補助金 対象経費`、`IT導入補助金 締切` | 制度family / S/A制度 |
| 地域 | `東京都 補助金 製造業`、`大阪府 中小企業 補助金` | 都道府県 / 主要自治体 |
| 業種 | `飲食店 補助金`、`建設業 省人化補助金` | 業種hub |
| 比較 | `jGrants API`、`gBizINFO 補助金 データ` | compare |
| 更新 | `補助金 公募開始 変更`、`制度 改正 2026` | data freshness / update |
| 開発者 | `補助金 API`、`MCP 補助金`、`法人番号 インボイス API` | docs / OpenAPI / MCP |

すべてのindex対象ページに固定ブロックを持たせる。

- 冒頭の短い回答
- 根拠テーブル
- 一次資料リンク
- 更新日
- 著者・発行主体の一貫した `@id`
- Article / FAQPage / Dataset / GovernmentService / BreadcrumbListの適切なJSON-LD
- APIで同じデータを取得する例
- 訂正フォーム

プログラマティックSEOの品質ゲート:

| Tier | index方針 | 条件 |
|---|---|---|
| Tier 1 | index | S/A制度、都道府県、主要Q&A、比較、docs |
| Tier 2 | 条件付きindex | 主要自治体、制度family、prefecture x industry、source別、更新差分、case hub |
| Tier 3 | noindex / 非公開 | B/C個別、薄い掛け合わせ、検索結果ページ |

Tier 2は、一次資料URLが3件以上、有効S/A制度が5件以上、周辺根拠が3件以上、固有本文1,500字以上を満たしたものだけindex対象にする。

毎月出すべき自然被リンク資産:

- 月次データ品質レポート
- dataset別freshnessと差分RSS
- 公式資料リンク切れ一覧
- correction log
- source liveness
- 主要制度の変更履歴
- MCP/RESTのpaste-and-run examples
- GitHubのmanifest drift report

GoogleのAI Features向けには、特別なAI専用ファイルやschemaを作ることより、クロール可能な本文、内部リンク、構造化データと可視本文の一致、Search Console監視を重視する。OpenAI向けには、`OAI-SearchBot` と `GPTBot` をrobotsで分け、検索露出と学習利用の許可を明示的に管理する。これは外部LLM APIの利用ではなく、crawler policyである。

### 28.5 Product-Led Growth / Activation

PLGは「新しい大機能を足す」より、既存導線の破断を直して計測できるようにするところから始める。

P0で直す導線:

- `trial.html`: key reveal / quickstart JSが実行されること。
- `pricing.html`: checkout CTAが確実に起動し、source metadataを渡すこと。
- `success.html`: paid key revealと初回request導線が動くこと。
- `dashboard.html`: quickstart、saved search作成、usage、billing、tool recommendationが壊れていないこと。
- `line.html`: waitlist送信が動き、sourceが残ること。
- `stats_funnel`: trial signup、magic link verify、first request、saved search、digest、referral、partner、LINE、widgetまで入れること。
- `analytics.js`: env未設定no-opのまま本番判断しないこと。

30日で試すactivation実験:

| 実験 | 内容 | KPI |
|---|---|---|
| Anonymous -> trial | 成功3回目、10回目、残quota10以下、429でCTA出し分け | `anonymous_success_session_to_trial_signup`、`429_to_trial_signup` |
| Trial checklist | key revealed -> first request within 30min -> 5 req by D7 -> saved search -> digest enabled | `trial_first_request_24h`、`D7_5req_rate`、`trial_to_paid` |
| Playground -> saved search | 匿名検索条件をsignup後に復元し1 clickでsaved search化 | `successful_search_to_saved_search` |
| Weekly digest default | 初回saved searchでweekly digestを推奨 | `digest_enabled_rate`、`digest_open_or_click_72h_reactivation` |
| Dashboard first-run | curl-first / MCP-first / saved-search-firstを比較 | `time_to_first_api_call`、`second_session_D7` |
| Source-aware pricing | `from=playground|429|trial|line|widget|partner|referral` をcheckout/api_keys/usage_eventsへ保存 | `paid_WAU_by_source` |
| Widget loop | 埋め込み先にsource/partner codeとPowered by導線 | `widget_impression_to_search`、`widget_search_to_trial` |
| Partner self-serve | mailtoではなくpartner application idを発行 | `partner_activated`、`partner_paid_requests` |

Referralはpaid顧客限定、opt-in、credit-onlyで小さく始める。現金紹介料を急がない。Widget、partner、LINE、saved search digestはすべてsource attributionを通す。

### 28.6 2026-04-30からの10日集中計画

10日でやることは、機能拡張ではなく、売れる状態、使える状態、測れる状態への圧縮である。

| 日付 | 集中テーマ | 完了条件 |
|---|---|---|
| 2026-04-30 | No-LLM boundary | product/runtime/ETL/cron/CIから外部LLM API呼び出し、env、docs誤表現を隔離または削除 |
| 2026-05-01 | DB正本 | 実DBとschema/migrationの差分を確認し、`usage_events.quantity`、integration migration、saved_searches拡張を反映 |
| 2026-05-02 | Billing/key P0 | checkout、success、key reveal、二重発行防止、billing portal、Stripe webhook healthをE2E確認 |
| 2026-05-03 | Host/CORS/env正本 | `api.jpcite.com`、CORS、SDK base URL、Smithery/DXT/env名を統一 |
| 2026-05-04 | Agent contract | response envelope、citation model、error enum、rate limit headers、MCP structuredContent方針を確定 |
| 2026-05-05 | Advisor demo kit | Advisor Pack 1枚提案、匿名テンプレCSV、週次Digest sample、月次ZIP sampleを作る |
| 2026-05-06 | Report/Integration Center最小版 | Report CenterとIntegrations Centerの画面/endpoint/失敗時復旧を最小で通す |
| 2026-05-07 | Organic trust cleanup | `llms.txt`、README、比較、透明性、sitemap、robots、旧ブランド名、公開件数を整合 |
| 2026-05-08 | Distribution manifest | runtimeからtool/resources/prompts/OpenAPI path/version/domainを生成し、README/DXT/Smithery/server.json検証 |
| 2026-05-09 | Pilot launch | 20事務所リスト、5ヒアリング台本、3pilot条件、paid提示資料、計測dashboardを固定 |

10日終了時のGo条件:

- 外部LLM API禁止のCIが緑。
- `usage_events.quantity` とunit課金が実DBで動く。
- trial -> key reveal -> first request -> saved search -> digest -> monthly ZIPの最短E2Eが通る。
- Advisor Pack資料が1枚で説明できる。
- 匿名CSV demoで個人情報なしに価値が伝わる。
- `llms.txt` / README / MCP manifest / DXT / Smithery / OpenAPI docsの数字が一致する。
- 20事務所へ送れる個別文面とdemo URLがある。

### 28.7 30 / 60 / 90日の成長順序

30日: 士業・補助金コンサルの支払い意欲を検証する。

- 20事務所に個別接触。
- 5件の課題ヒアリング。
- 3件のpilot。
- 1-3件のpaid conversion。
- 売る商品は `Advisor ¥49,800/月` に固定。
- Developer Meteredは入口、M&A/DDは見せるだけ、Data Licenseは売らない。

成功条件:

- 顧問先10件以上の登録。
- 2週連続のDigest閲覧。
- 月次ZIPを顧問先または社内に共有。
- saved searchが1つ以上残る。
- 初回paidまたは年契約の明確な稟議に進む。

60日: 継続ループを実装する。

- `client_profiles`
- CSV import
- saved search
- weekly digest
- monthly ZIP
- `client_tag`別利用明細
- Report Center最小版
- Integrations Center最小版
- source attribution付きPLG funnel
- pilot実例ベース記事6-8本

90日: Evidence Graphへ進む。

- `source_manifest`
- `raw_documents`
- `adoption_records`の金額coverage改善
- program / adoption / houjin / invoice / enforcement のjoin edge
- `unknown_reason`
- human review queue
- Trust Dashboard
- license export gate

90日終了時点で、M&A/DDとData LicenseのGo/No-Goを判定する。30日で3pilot未満、または1paid未満なら、拡張ではなくAdvisor商品の価値仮説を戻して再設計する。

### 28.8 North Starと計測

North Starは `weekly_evidence_loops` にする。

定義:

7日以内に同一accountで、次の3条件が成立した数。

1. `client_profile_imported` または `client_tag >= 5`
2. `saved_search_created >= 1`
3. `digest_delivered >= 1` または `report_generated >= 1`

補助KPI:

| 面 | KPI |
|---|---|
| Human | 初回CSV upload、初回ZIP生成、Digest open、Report再DL、client_tag数、2週連続Digest閲覧 |
| AI/Agent | MCP初回tool成功、agent user-agent別first call、OpenAPI/llms.txt経由流入、tool error率、enum correction率 |
| Organic | GSC clicks/impressions、indexed URL数、docs -> API key、RSS/saved search登録、自然被リンク、correction submissions |
| PLG | anonymous success -> trial、trial first request 24h、D7 5req、saved search化、trial to paid、paid WAU by source |
| Quality | source coverage、checksum一致率、unknown_reason付与率、adoption -> program join率、false allow 0 |
| Revenue | Advisor paid数、ARPA、月次report生成数、unit消費、解約理由、partner paid requests |

PVや記事本数はNorth Starにしない。売上に近いのは、毎週の根拠付き業務ループが成立した数である。

### 28.9 No-Goをさらに強める

以下に該当する場合、成長施策を止めてP0へ戻す。

- 外部LLM APIを呼ぶコード、env、CI、cron、ETL、翻訳、評価、研究スクリプトがproduct treeに残る。
- `scripts/etl/batch_translate_corpus.py` のような例外が隔離されず、通常運用から呼べる。
- DB正本、usage schema、billing E2E、key二重発行防止が緑でない。
- trial/pricing/success/dashboard/LINEのJSが壊れている。
- `source_url/source_fetched_at/source_checksum/license` 欠損行を有料ZIP、監査レポート、DD、Data Licenseに含める。
- `license in ('unknown','proprietary')` をexport eligibleにする。
- 採択金額coverageが弱いまま、M&A/DDを高額商品として前面に出す。
- 公開件数、tool数、OpenAPI path数、ブランド名、domain、SDK名が複数箇所で矛盾する。
- `message` / `user_message`、`rate_limited` / `rate_limit_exceeded` の揺れを放置する。
- 30日で3pilot未満、または1paid未満なのにM&A/DD、Data License、自治体、金融、VCへ広げる。
- Digest開封、CSV upload、ZIP生成、saved search作成が計測できない状態で記事数だけ増やす。
- 「AIが判定」「採択確率」「自動で根拠を読む」など、jpcite本体が生成AI応答をしているように見える訴求を使う。

### 28.10 最終優先順位の更新

ここまでを踏まえると、次の順序に固定する。

1. 外部LLM API不使用をCI、docs、manifest、運用手順まで貫通させる。
2. DB正本、usage schema、billing/key、host/CORS/env、JS破断を直す。
3. `Advisor ¥49,800/月` を、顧問先CSV + 週次Digest + 月次ZIPの商品として出す。
4. `weekly_evidence_loops` をNorth Starにし、PLG funnelとsource attributionを入れる。
5. Agent contract、citation model、error envelope、tool pack manifestを作る。
6. Distribution manifestでREADME、MCP Registry、DXT、Smithery、SDK、`llms.txt` のdriftを消す。
7. Organicは、実務pilotから生まれた6-8本の深い記事、比較更新、透明性、data freshness、docsに絞る。
8. Report Center / Integrations Centerで、継続利用と失敗復旧を商品化する。
9. Evidence Graph、license gate、Trust Dashboardを整え、M&A/DDとData LicenseのGo/No-Goを判定する。
10. 自治体、金融、VC、広域Data Licenseは、Advisor Packの実利用と品質指標が揃ってから広げる。

### 28.11 外部仕様メモ

- MCP Tools仕様は、toolの `inputSchema`、`outputSchema`、`structuredContent`、error handling、tool list changed notificationを定義している。jpciteのagent contractは、これに合わせてMCP tool resultへ構造化結果を返す。
  - https://modelcontextprotocol.io/specification/2025-06-18/server/tools
- MCP Schema Referenceのlatestは `2025-11-25` として公開されている。互換テストでは現行実装の互換性と、latest schemaへの追従可否を分けて見る。
  - https://modelcontextprotocol.io/specification/2025-11-25/schema
- Official MCP Registryは、`server.json`、package metadata、ownership verification、`mcp-publisher publish` の流れを要求する。jpciteの配布正本はこの流れに合わせる。
  - https://github.com/modelcontextprotocol/registry/blob/main/docs/modelcontextprotocol-io/quickstart.mdx
- Google Search Centralは、AI featuresへの露出について、通常のクロール、内部リンク、テキスト本文、構造化データと可視本文の一致、Search Console監視を重視している。AI専用の特別なschemaを前提にしない。
  - https://developers.google.com/search/docs/appearance/ai-features
- OpenAI crawlersは、検索露出向けの `OAI-SearchBot` と学習向けの `GPTBot` を分けて説明している。jpciteではrobotsで検索露出と学習利用の方針を分ける。これはAPI利用ではなくcrawler制御である。
  - https://developers.openai.com/api/docs/bots
