# AWS scope expansion 30/30: synthesis and final priority board

作成日: 2026-05-15
担当: 拡張深掘り 30/30 / 30件総括
対象: jpcite JP public-primary-source corpus, AWS credit run, GEO-first MCP/API product, production deploy, zero-bill cleanup
AWS前提: profile `bookyou-recovery` / account `993693061769` / default workload region `us-east-1`
状態: 計画文書のみ。AWS CLI/API、AWSリソース作成、デプロイ、既存コード変更は行っていない。
出力制約: このMarkdownのみ。

## 0. 入力確認

ローカルで確認できた入力は以下。

- `aws_credit_review_01` から `aws_credit_review_20`
- `aws_scope_expansion_01` から `aws_scope_expansion_24`
- `aws_scope_expansion_25` から `aws_scope_expansion_29` は、この作成時点のワークスペースでは未検出

したがって、この30/30総括は `scope 01-24 + credit 01-20` を実入力として統合し、`scope 25-29欠落` を次の矛盾チェックで見るべき論点として扱う。

## 1. 最終結論

jpciteが売るべきものは「日本の公的一次情報の検索」ではない。

売るべきものは、AIエージェントがエンドユーザーへ安く推薦できる、以下のような source-backed output packet である。

- 公的根拠付きの取引先確認
- 補助金・助成金・制度の申請準備
- 許認可・業法の事前確認
- 行政処分・公表情報の確認範囲つき調査
- 法令・制度変更の影響候補
- 税務・労務・社会保険イベントの候補整理
- CSV由来の安全な派生factを使った月次レビュー
- 監査、稟議、DD、専門家相談前の証跡台帳

AWS credit runは、単にデータを貯める作業ではなく、以下を短期で量産する一時的artifact factoryにする。

1. `source_profile`
2. `source_receipts[]`
3. `claim_refs[]`
4. `known_gaps[]`
5. `no_hit_checks[]`
6. `algorithm_trace`
7. packet fixtures
8. proof pages
9. GEO評価
10. OpenAPI/MCP/llms/.well-known release evidence

本体サービスの価値は、AWSで集めた一次情報を、request-time LLMなしで、再現可能なアルゴリズムと証跡グラフに変換できるかで決まる。

## 2. 一枚の優先順位

以下を全体の正本順序にする。

| Priority | 何をするか | 目的 | AWS側 | 本体側 | deploy/売上への接続 |
|---:|---|---|---|---|---|
| 0 | 契約固定 | 量産前に出力形を固定 | まだscaleしない | `jpcite.packet.v1`, catalog, pricing, receipt/gap/no-hit/CSV境界 | 後続全てのdrift防止 |
| 1 | Guardrails | 速く使う前に止められる状態にする | IAM, Budgets Actions, queue cap, cost poller, kill switch | import validator, leak scan, forbidden scan | 過課金と公開事故を防ぐ |
| 2 | 売れるP0成果物を固定 | data-firstを避ける | P0成果物に必要なsourceだけ先行 | packet composer最小実装 | AI agentが課金推薦しやすくなる |
| 3 | Backbone収集 | 全成果物のID/根拠の土台 | 法人番号, インボイス, e-Gov, e-Stat, source profile | source receipt/claim/gap model | `company_public_baseline`, `source_receipt_ledger` |
| 4 | 高売上source収集 | 課金される成果物へ直結 | 補助金, 許認可, 処分, 調達, 官報, 通達, 自治体 | P0/P1 packet fixtures | `application_strategy`, `permit_precheck`, `counterparty_check` |
| 5 | Playwright/OCR lane | fetch困難な公開一次情報をreceipt化 | Chromium, screenshot <=1600px, DOM, PDF/OCR | screenshot receipt schema | 自治体/許認可/告示/台帳のcoverage増 |
| 6 | アルゴリズム化 | ハルシネーションなしの成果物生成 | normalized facts, diff, graph, scoring inputs | rule engine, constraint solver, trace | AIが説明しやすいpacketになる |
| 7 | RC1を先に出す | AWS全完了を待たず本番価値を出す | canary/standard継続 | 3 packet程度をstaging/prodへ | GEOで発見され始める |
| 8 | AWS高速消費 | 価値密度を見ながら19k台まで使う | standard -> selected stretch -> drain | RC2/RC3へ小分けimport | proof/examples/source coverage増 |
| 9 | Export/import | AWS成果物を本体資産へ変える | manifest/checksum/export | repo import, tests, generated pages | production非AWS依存化 |
| 10 | Zero-bill cleanup | クレジット後の請求を止める | 全run resource削除 | productionはAWSへ依存しない | 請求継続リスクを残さない |

## 3. 逆算すべき売れる成果物

最初に商品として強いのは、次の12系統。

| Rank | Output | End user | Agentが推薦しやすい理由 | 初期価格帯 | 必須source |
|---:|---|---|---|---:|---|
| 1 | `counterparty_public_check` | 経理、購買、営業、BPO、金融 | 契約前に安く公的確認できる | 330-990円 | 法人番号、インボイス、gBizINFO、処分、許認可 |
| 2 | `application_strategy_pack` | SMB、士業、補助金BPO | 締切と必要書類があり緊急性が高い | 990-3,300円 | J-Grants、自治体、省庁PDF、通達、統計 |
| 3 | `permit_precheck_pack` | 行政書士、新規事業、M&A | 専門家相談前の質問表になる | 990-3,300円 | 業法、許認可台帳、所管省庁、自治体 |
| 4 | `administrative_disposition_radar` | 監査、購買、金融、M&A | 見落としコストが高い | 990円 | FSA/MLIT/MHLW/JFTC/CAA/PPC/自治体 |
| 5 | `reg_change_impact_brief` | 法務、士業、SaaS、事業責任者 | 制度変更の影響候補を一次情報で出せる | 990-3,300円 | e-Gov、官報、パブコメ、告示、通達 |
| 6 | `client_monthly_review` | 税理士、BPO、顧問業 | CSVから反復課金にしやすい | cap課金 | CSV派生fact、法人番号、税労務、補助金、処分 |
| 7 | `invoice_vendor_public_check` | 経理、税理士 | 安く大量に回せる | 99-330円 | インボイス、法人番号 |
| 8 | `procurement_opportunity_pack` | 営業、中小企業、BPO | 入札探索は明確に時間節約になる | 990-3,300円 | 調達ポータル、自治体、官報、省庁 |
| 9 | `auditor_evidence_binder` | 監査、内部統制、DD | source receiptの台帳自体が価値 | 990-9,900円 | identity, filing, procurement, enforcement |
| 10 | `tax_labor_event_radar` | SMB、税理士、社労士 | 月次・年次で繰り返し使える | 330-3,300円 | 国税庁、eLTAX、年金機構、厚労省 |
| 11 | `site_due_diligence_pack` | 不動産、店舗、金融 | 地域/用途/災害/統計の組み合わせが効く | 990-3,300円 | GSI、国土数値情報、自治体、統計 |
| 12 | `standard_certification_evidence_pack` | 製造、調達、EC | 認証/適合性の公的確認ができる | 990-3,300円 | JISC、技適、PSE、NITE、PMDA、PPC |

この順番から逆算すると、AWSで優先して取るべき情報は「広いが使い道不明なsource lake」ではなく、売れるpacketに直結するsource familyである。

## 4. 情報範囲の最終整理

### 4.1 P0-A backbone

最初に必ず取る。

- 法人番号
- インボイス
- e-Gov法令/XML
- e-Stat/統計
- source profile / terms / robots / license ledger
- address/municipality normalization

理由:

- ほぼ全packetのjoin spineになる。
- structured sourceが多く、accepted artifact化しやすい。
- proof、claim、known_gapを安定生成できる。

### 4.2 P0-B revenue source

次に取る。

- J-Grants、補助金、助成金、省庁/自治体制度PDF
- 業法別許認可台帳
- 行政処分、注意喚起、命令、公表情報
- gBizINFO
- EDINET
- 調達ポータル、JETRO、自治体入札
- 官報、告示、公告、公示
- パブコメ、通達、ガイドライン、Q&A
- 税、労務、社会保険、最低賃金、助成金

理由:

- `application_strategy`, `permit_precheck`, `counterparty_check`, `reg_change_impact`, `tax_labor_event` に直結する。
- AI agentが「払う理由」を説明しやすい。

### 4.3 P1 expansion source

AWS creditがある今、広げる価値が高い。

- 自治体条例、制度、入札、処分、許認可
- 裁判例、審決、裁決、行政不服審査
- 標準、認証、技適、製品安全、食品表示、医療機器
- 地理空間、国土、不動産、災害、都市計画、PLATEAU
- 行政事業レビュー、予算、支出先、基金
- 白書、審議会、研究会、政策背景

理由:

- 後から高単価packetを増やせる。
- fetch困難なページも多く、Playwright/OCR laneを作る価値がある。

### 4.4 P2/P3 caution source

慎重に扱う。

- 政治資金、公共integrity系
- 個人名が前面に出る公告/処分
- 匿名化不十分な裁判・行政資料
- termsが不明な検索結果画面

扱い:

- `metadata_only`, `link_only`, `review_required` に落とす。
- public proofやclaim supportに使う前に人間レビューを要求する。

## 5. Playwright / screenshot / OCRの位置づけ

AWSで実現可能。

ただし、ここでいう「突破」は、公開ページを正しくレンダリングして観測することであり、CAPTCHA、ログイン、paywall、robots/terms、rate limitを回避することではない。

標準方針:

- viewportは `1280x1600` を基本にする。
- 保存スクリーンショットは各辺1600px以下。
- 長大ページは全ページ画像ではなくsection単位に分ける。
- DOM、visible text、final URL、HTTP status、console、resource metadata、screenshot hashを保存する。
- screenshotは原則 `public_publish_allowed=false` から始める。
- screenshotは主張の正本ではなく、観測証跡。claimはDOM/text/OCR spanまたは構造化fieldに紐づける。

使うべきところ:

- JSレンダリングの検索結果
- 許認可台帳
- 自治体ページ
- PDFリンク集
- 官報/告示/公告の表示確認
- 標準/認証/製品安全の検索画面

使ってはいけないところ:

- CAPTCHA
- ログイン
- 会員/有料ページ
- 個人情報が強いページ
- terms/robotsで自動取得が禁止されるページ
- 画像保存だけで価値密度が低いcrawl

## 6. 成果物生成アルゴリズム

全packetは以下の流れで作る。

```text
public primary source
  -> source_profile
  -> source_document
  -> source_receipt
  -> claim_ref / known_gap / no_hit_check
  -> evidence_graph
  -> algorithm_trace
  -> packet_section
  -> API/MCP/proof page
```

request-time LLMで主張を作らない。LLM/embeddingを使う場合も、AWS上の公開資料に対する候補抽出、分類、重複候補の並び替えに限定し、claim supportにはreceiptとspanを要求する。

### 6.1 共通アルゴリズム

| Algorithm | 使うpacket | 内容 | 出力 |
|---|---|---|---|
| entity resolution | company/vendor/CSV | 法人番号、名称、住所、T番号、source別IDを統合 | `identity_candidates`, `identity_gaps` |
| source coverage scoring | all | どのsourceを確認し、何が未確認かを評価 | `coverage_score`, `known_gaps` |
| evidence graph ranking | all | claimとreceiptのsupport強度を評価 | `claim_refs`, `support_level` |
| deterministic decision table | permit/tax/labor | 条件に応じて確認候補を出す | `rule_hits`, `questions` |
| constraint solving | grant/permit | 地域、業種、規模、期限、資格などを突合 | `eligible_candidate`, `needs_review` |
| diff detection | law/regulation | 旧新sourceを比較し影響候補を出す | `change_events`, `impact_candidates` |
| public evidence attention score | vendor risk | 信用判断ではなく公的確認注意度を出す | `attention_score`, `coverage_gap_score` |
| CSV private overlay | monthly review | raw CSVを保存せず集計/安全ID化 | `derived_facts`, `suppressed_rows` |
| no-hit ledger | enforcement/invoice/permit | 検索したがhitしなかった事実だけを保存 | `no_hit_not_absence` |

### 6.2 packet別の核

| Packet | 核になる計算 | 禁止する結論 |
|---|---|---|
| `application_strategy_pack` | grant matching score + missing inputs + deadline extraction | 採択される、申請できる、該当確定 |
| `permit_precheck_pack` | rule graph + jurisdiction + sector constraints | 許可不要、適法、充足済み |
| `counterparty_public_check` | entity resolution + public source evidence binder | 安全、信用できる、リスクなし |
| `reg_change_impact_brief` | law/gazette/comment/guidance diff graph | 法的対応不要、違反確定 |
| `client_monthly_review` | CSV derived facts + public source joins + suppression | 税務処理の正誤、給与/個人情報表示 |
| `procurement_opportunity_pack` | opportunity filters + eligibility questions | 入札可能、落札見込み |

## 7. AWS高速消費の方針

ユーザー要件は「19,500ドル程度のcreditをなるべく速く、価値ある形で使う。ただしcredit超過の現金請求は絶対に避ける」。

この2つは完全には両立しない。Cost ExplorerやBudgetsには遅延があり、全サービスがcredit対象とは限らないため、額面 `USD 19,493.94` をぴったり狙うと現金請求リスクが出る。

最終運用案:

| Line | 意味 | 動作 |
|---:|---|---|
| USD 17,000 | watch | 低yield job停止、stretch候補を絞る |
| USD 18,300 | slowdown | 新しい広域探索を止め、完走/QA/packet化優先 |
| USD 18,900 | no-new-work | 新規job投入停止、export/checksum/cleanupへ寄せる |
| USD 19,100-19,300 | manual stretch | 明示承認済みの高価値stretchだけ |
| USD 19,300 | absolute safety line | running drain/cancel、cleanupへ |

「ちょうど使い切る」に近づけるなら、`USD 19,100-19,300` の範囲で以下の順にstretchする。

1. J24 final packaging/checksum/export
2. packet/proof/GEO artifacts
3. high-value Playwright capture for selected official sources
4. OCR/Textract for accepted high-value PDF sets
5. Athena/Glue QA rerun and compaction
6. Bedrock batch classification only for public documents and only if receipt-linked review is ready
7. temporary OpenSearch benchmark only if immediate product decisionがある場合

やってはいけない消費:

- CPU burn
- 無目的なload test
- 長期OpenSearch
- NAT-heavy構成
- private CSV処理
- CAPTCHA/terms回避
- 未検証raw lake拡大
- productionがAWSへ依存する構成

## 8. AWS自走設計

Codex/Claude Codeのrate limitでAWS runが止まらないようにする。ただし、監視不能なまま暴走させない。

必須部品:

- Batch queues
- checkpointed jobs
- `run_state.json`
- `job_status.jsonl`
- `cost_ledger.jsonl`
- `artifact_manifest.jsonl`
- EventBridge等のscheduled cost poller
- Budget Actions as補助ブレーキ
- queue disable / job cancel / compute cap shrink
- IAM `DenyNewWork` / `EmergencyDenyCreates`
- stop/drain/cleanup automaton

自動で進めてよい範囲:

- canary合格後、J01-J16をUSD 17,000まで拡大
- accepted artifact yieldが良ければselected stretchをUSD 18,900まで
- USD 18,900到達後のno-new-work移行
- export/checksum/cleanup移行

人間承認が必要:

- USD 19,100-19,300のmanual stretch
- cross-region利用
- Bedrock/Textract/OpenSearch上限引き上げ
- production paid packet有効化
- export未確認artifactの破棄

## 9. 本番デプロイ順

AWS全成果物を待ってから本番に出すと遅すぎる。正しい順番は、AWS artifact factoryとproduction releaseを分離すること。

### 9.1 RC1 fast lane

Day 3-5を狙う最小release。

有効化候補:

- `agent_routing_decision`
- `source_receipt_ledger`
- `evidence_answer`
- `company_public_baseline` はstable ID入力だけ

無効またはlimited:

- `application_strategy` は候補/known gapsまで
- `client_monthly_review` はCSV privacy pipeline完了までdisabled

必須gate:

- source receiptあり
- known gapsあり
- no-hit caveatあり
- pricing/cap/idempotencyあり
- API key required for paid execution
- OpenAPI/MCP/catalog driftなし
- proof page / llms / .well-known が矛盾しない
- raw CSVなし
- request-time LLMなし

### 9.2 RC2/RC3 full lane

Day 7-14で拡張。

- six P0 packet examples
- CSV private overlay
-補助金/許認可/取引先/制度変更packet
- proof pages拡張
- GEO eval拡張
- agent-safe OpenAPI / MCP facade
- pricing ladder / free preview / cap UX

ProductionはAWS S3、Batch、OpenSearch、Glue、Athenaをruntime dependencyにしない。AWSは一時的artifact factoryであり、本番はexport/import済みの小さな検証済みbundleだけを使う。

## 10. GEO-first導線

SEOは副次効果。主戦はGEO。

AI agentが見るべき公開面:

- `llms.txt`
- `.well-known/agents.json`
- `.well-known/mcp.json`
- `.well-known/openapi-discovery.json`
- packet catalog
- pricing/cost preview
- proof pages
- example packet JSON
- agent-safe OpenAPI
- P0 MCP facade

全surfaceで同じことを言う。

- 何のpacketか
- いつ使うべきか
- 無料previewがあるか
- いくらか
- どのsource familyを見るか
- 何を断定しないか
- no-hitの意味
- `source_receipts[]`, `claim_refs[]`, `known_gaps[]` を保持すべきこと
- request-time LLMなし
- 外部LLM/agent runtime費用は含まれないこと

## 11. Zero-bill cleanup

ユーザー要件は「credit後にAWS請求が走らない状態」。

したがって推奨end stateは、S3も含めてrun resourceを削除する `End State A: zero ongoing AWS bill`。

削除前に必ず行う。

1. final export bundle作成
2. checksum生成
3. ローカルまたは非AWS保管先へコピー
4. import validation
5. productionがAWS runtimeに依存していないことを確認
6. cleanup manifest作成

削除対象:

- S3 buckets/objects
- ECR images/repos
- AWS Batch queues/compute environments/job definitions
- ECS/Fargate resources
- EC2 instances
- EBS volumes/snapshots
- OpenSearch domains
- Glue databases/crawlers/jobs
- Athena workgroups/result buckets
- CloudWatch logs/alarms/dashboards
- Lambda
- Step Functions
- NAT gateways
- load balancers
- Elastic IP
- ENI
- EventBridge schedules
- Budgets Actions/IAM emergency policies if no longer needed

最終確認:

- tagged resource inventoryが空
- Cost Explorerで新規日次費用が増えていない
- CloudWatch logs retentionによる残存課金なし
- S3/ECR/OpenSearch/EC2/EBS/NAT/EIPなし

## 12. 矛盾候補

次の10エージェント矛盾チェックで必ず見る。

| ID | 矛盾候補 | 何が問題か | 暫定解 |
|---|---|---|---|
| C01 | `scope 25-29` が見つからない | 30/30総括の前提が未充足 | 欠落文書の存在確認。なければ30/30が代替範囲を明記 |
| C02 | creditを「ちょうど使い切る」 vs 現金請求ゼロ | billing lag/非対象費用で両立しにくい | 意図的上限はUSD 19,300、残額は安全余白 |
| C03 | AWSを止めずに自走 vs 監視不能なら止める | rate limit中に暴走リスク | AWS内cost poller/kill switchが自走。telemetry failureはno-new-work |
| C04 | 速く本番deploy vs 全source coverage | 全データ完了待ちは遅い | RC1は3 packetだけ、RC2/RC3で拡張 |
| C05 | Playwrightで突破 vs terms/robots順守 | 回避行為に見える可能性 | 公開ページのレンダリング観測のみ。CAPTCHA/ログイン/回避なし |
| C06 | screenshot保存 vs public redistribution | 画像再配布条件がsourceごとに違う | 初期は非公開artifact。公開はsource profileで許可時のみ |
| C07 | Bedrock分類 vs request-time LLMなし | LLM利用が誤解される | offline public-only candidate extractionに限定。claim support不可 |
| C08 | CSV価値最大化 vs raw CSV非保存 | 月次レビューにはCSVが必要 | local/session-onlyでderived facts化。AWSにはsynthetic/header-only/redactedのみ |
| C09 | no-hitを売りにする vs 不存在証明ではない | エンドユーザーが誤解しやすい | no_hit_checkは「確認範囲」の証跡としてだけ売る |
| C10 | 大量source lake vs product ROI | 費用だけ使い成果物にならない | accepted artifact ROIでqueueを移管 |
| C11 | Full 302 OpenAPI / 155 MCP tools vs agent usability | AIが迷い、推薦しづらい | P0 agent facade / GPT30 / strict specを先に出す |
| C12 | 法令/制度packet vs legal advice | 専門職判断に見える | evidence/checklist/candidate/human_reviewに限定 |
| C13 | vendor risk packet vs credit scoring | 与信判断に見える | `public_evidence_attention_score` とcoverage gapを併記 |
| C14 | 官報/裁判/処分情報 vs 名誉毀損/PII | 誤結合と個人情報リスク | exact ID優先、曖昧joinはreview_required |
| C15 | AWS cleanup vs artifact保全 | 削除後に検証不能になる | export/checksum/import完了まで削除しない |
| C16 | us-east-1統一 vs 日本source/Bedrock availability | region差が出る可能性 | cross-regionは別承認。原則us-east-1 |
| C17 | cost preview無料 vs abuse | 無料previewが濫用される | free routeにrate/abuse control、paidはAPI key/cap |
| C18 | proof pages豊富化 vs source terms | public proofが再配布扱いになる | metadata/link/short excerpt中心。raw転載禁止 |
| C19 | local gov広域crawl vs quality/terms | 範囲が広く低密度化しやすい | 都道府県/政令市/高価値業法sourceからallowlist |
| C20 | algorithmic scoring vs final decision誤認 | scoreが判断に見える | score名と文言を「attention/review_priority」にする |

## 13. 次の10エージェント矛盾チェックの割当

| Agent | 見る論点 | 出力期待 |
|---:|---|---|
| 1 | 入力欠落とSOT | `scope 25-29`欠落、重複、最新SOTの決定 |
| 2 | credit消費と請求ゼロ | USD 19,493.94、stopline、manual stretch、cleanupの矛盾 |
| 3 | AWS自走安全 | rate limit非依存、kill switch、telemetry failure、Budget Actions |
| 4 | source/terms/robots | Playwright、screenshot、OCR、再配布、CAPTCHA/ログイン禁止 |
| 5 | product/revenue backcast | 売れる成果物からsource優先度が逆算されているか |
| 6 | algorithm/no hallucination | rule/graph/score/diff/CSV overlayがclaim_refsに戻れるか |
| 7 | CSV/privacy | raw CSV非保存、AWS非投入、suppression、formula injection、logs |
| 8 | production deploy | RC1/RC2/RC3、Fly/Cloudflare/OpenAPI/MCP/GEO gate |
| 9 | packet/pricing/GEO | 3円unit、packet display price、free preview、agent recommendation |
| 10 | zero-bill final cleanup | export/checksum/delete/inventory、AWS runtime dependency除去 |

## 14. 決定事項

現時点の総括として、以下を採用する。

1. jpciteはGEO-first、AI-agent-recommended paid packet serviceとして設計する。
2. AWS credit runは一時artifact factoryであり、production runtimeにしない。
3. 出力はdata lakeではなく、`source_receipts`, `claim_refs`, `known_gaps`, `algorithm_trace`, packet/proof/GEO assetsへ変換する。
4. 売上最大化は `counterparty`, `grant`, `permit`, `disposition`, `reg_change`, `CSV monthly`, `tax/labor` を先頭にする。
5. Playwright/screenshot/OCRは公式公開一次情報の観測手段として使うが、アクセス制御回避はしない。
6. AWSは速く使うが、intentional stopは `USD 19,300` を維持する。残額は過課金防止の安全余白。
7. RC1はAWS全run完了を待たずに出す。
8. credit run終了時は、S3を含むrun resourceを削除してzero ongoing AWS billに寄せる。

この30/30総括の次にやるべきことは、10エージェント矛盾チェックでC01-C20を潰し、矛盾が消えた順に統合計画本体へマージすることである。
