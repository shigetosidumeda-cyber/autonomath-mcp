# AWS scope expansion 25/30: fast spend and value-maximization scheduler

作成日: 2026-05-15  
対象AWS profile: `bookyou-recovery`  
対象AWS account: `993693061769`  
対象region: `us-east-1`  
実行方針: この文書ではAWS CLI/API/リソース作成を行わない。実行前のスケジューラ設計だけを確定する。

## 0. 結論

USD 19,493.94のAWSクレジットは、jpciteの価値を上げるために「日本の公的一次情報を広く取り、証跡付き成果物に変換する一回限りの工場」として使う。

ただし、現金請求は絶対に避ける。したがって、実行上の目標は「ほぼ全額を使う」だが、スケジューラ上の新規投入停止線はUSD 19,300とする。残り約USD 193.94は、Cost Explorer反映遅延、非クレジット対象、通信/ログ/ストレージの遅延請求、削除タイミングのずれに対する安全余白として扱う。

本番デプロイを早くするため、AWS計画は2レーンに分ける。

1. Day 0-3 fast production lane  
   本番に載せる最小価値を最短で作る。広域収集を待たず、P0のpacket contract、source_receipts、claim_refs、known_gaps、cost preview、MCP/API/GEO導線を先に通す。

2. Day 4-14 full corpus build lane  
   AWSがCodex/Claudeのrate limitに依存せず自走し、J01-J52相当を広域に処理する。Playwright/1600px以下スクリーンショット/OCR/Textract/Bedrock batch/temporary OpenSearch/Athena/Glueを、価値がある範囲で並列投入する。

AWSは、クレジットを使い切るためだけに動かさない。必ず次のどれかに変換する。

- `source_profile`候補
- `source_document`台帳
- `source_receipts[]`
- `claim_refs[]`
- `known_gaps[]`
- `no_hit`台帳
- `algorithm_trace`
- packet/proofサンプル
- GEO/agent discovery素材
- 本番投入可能なfixture
- 収集不能・利用不可・terms制約の台帳

## 1. Non-Negotiables

### 1.1 課金停止

絶対ルール:

- USD 17,000: Watch line。価値が低いjobを止め、残りを高価値jobへ寄せる。
- USD 18,300: Slowdown line。新規大規模array投入を止める。未完了jobはROIで継続/停止を決める。
- USD 18,900: No-new-work line。新しい収集jobは投入しない。検証、集約、export、cleanupへ移る。
- USD 19,100-19,300: Manual stretch only。明確な成果物増分がある小型stretchのみ。
- USD 19,300: Absolute safety line。全computeを停止し、drain/export/cleanupへ移る。

USD 19,493.94ちょうどを狙わない。AWSの請求反映は遅れるため、19,300を超えて走らせる設計は現金請求リスクを増やす。

### 1.2 AWS自走

Codex/Claudeがrate limitになってもAWSが止まらないようにする。

- 実行前にjob registryを固定する。
- 各jobにmax spend、max runtime、max items、max retryを持たせる。
- Batch/Step Functions相当の依存関係で、次jobが自動で起動できる状態にする。
- cost watcherがstoplineを見て、queueごとに新規投入を止める。
- すべてのjobがmanifest、checksum、cost ledgerを出す。
- オペレーター不在でも、19,300線、quality stop、terms stop、network drift stopで止まる。

### 1.3 本番デプロイはAWS完了待ちにしない

本番はDay 0-3で出す。Day 4-14の大規模AWS成果物は、本番後に段階的にimportする。

理由:

- GEO/agent discoveryは早く公開した方が学習・引用されやすい。
- AIエージェント向けサービスの価値は、MCP/API/llms/proof pagesが実際に外から見えることで初めて立つ。
- 完全なcorpusを待つと、AWS成果物ができても販売導線が未整備になる。

### 1.4 raw CSVをAWSへ送らない

CSV private overlayはjpciteの強い価値だが、AWSクレジット消費の対象にしない。

- raw CSVは保存しない。
- raw CSVはAWSへ上げない。
- AWSではsynthetic/header-only/redacted fixtureだけを扱う。
- 成果物生成ではderived factsのみを扱う。
- small group suppression、formula injection対策、leak scanを必須にする。

## 2. Scheduler Objectives

このスケジューラの目的は、単に広く収集することではない。売れる成果物から逆算して、取り返しがつきにくい公的一次情報を優先して集める。

最適化目的:

1. 本番デプロイをDay 3までに可能にする。
2. USD 19,300までに最大量の再利用可能な公的一次情報を収集する。
3. 収集データを証跡付きの成果物へ変換する。
4. GEOでAIエージェントが推薦しやすい公開surfaceを増やす。
5. no-hitを安全証明にしない。
6. request-time LLMなしで動く決定表/スコア/差分/証拠グラフを増やす。
7. AWS終了後に請求が継続しない状態へ確実に戻す。

## 3. Priority Formula

各jobの優先度は、以下の加重スコアで決める。

```
priority_score =
  0.24 * revenue_output_unlock
+ 0.20 * source_foundation_value
+ 0.16 * agent_recommendability
+ 0.14 * hard_to_collect_later
+ 0.10 * production_readiness
+ 0.08 * algorithm_unlock
+ 0.05 * cost_efficiency
+ 0.03 * freshness_value
- 0.20 * legal_terms_risk
- 0.12 * privacy_risk
- 0.10 * false_claim_risk
- 0.08 * operational_cost_drift
```

意味:

- `revenue_output_unlock`: そのsourceで有料packetが増えるか。
- `source_foundation_value`: 他sourceの同定や結合に使えるか。
- `agent_recommendability`: AIエージェントが「これを買うべき」と説明しやすいか。
- `hard_to_collect_later`: AWSクレジットがある今まとめて処理する価値が高いか。
- `production_readiness`: Day 0-3の本番価値に直結するか。
- `algorithm_unlock`: 決定表、差分、スコア、証拠グラフを増やすか。
- `cost_efficiency`: 1ドルあたりの有効receipt数が多いか。
- `freshness_value`: 更新監視/差分検出の価値が高いか。

この式により、GPUや意味の薄い高額処理ではなく、Playwright/OCR/大規模正規化/差分/証跡化のような、後からjpciteの売上に変わる処理へ寄せる。

## 4. Job Bands

### Band A: deploy-critical backbone

Day 0-3で必ず通す。

- J01 Official source profile sweep
- J02 NTA法人番号 mirror/diff
- J03 NTAインボイス registrant/no-hit
- J04 e-Gov法令 snapshot
- J12 Source receipt completeness audit
- J13 Claim graph dedupe/conflict analysis
- J15 Packet/proof fixture materialization
- J16 GEO/no-hit/forbidden-claim evaluation
- J24 Final artifact packaging/checksum/export

価値:

- 本番API/MCP/proof pagesの最小価値になる。
- AIエージェントが推薦できる説明材料になる。
- no-hit、source_receipt、claim_refsの契約を固定できる。

### Band B: revenue-first product sources

Day 1-6で優先投入。

- J05 J-Grants/public program acquisition
- J06 Ministry/local PDF extraction
- J07 gBizINFO public business signal join
- J08 EDINET metadata snapshot
- J09 Procurement/tender acquisition
- J10 Enforcement/sanction/public notice sweep
- J11 e-Stat regional statistics enrichment
- J25 Law/gazette/notices expansion
- J26 Public comment and policy process
- J27 Permit/procedure/industry registry expansion
- J28 Subsidy and public program expansion
- J29 Procurement and awards expansion
- J30 Administrative disposition and recall expansion

価値:

- 補助金候補、許認可チェック、取引先確認、行政処分調査、入札探索に直結する。
- 有料packetの種類と説得力を増やす。
- GEOで「公的証跡付きでこの成果物を安く取れる」と言いやすい。

### Band C: wide public corpus expansion

Day 4-10で広げる。

- J31 Courts/disputes/appeals expansion
- J32 Standards/certifications/technical compliance
- J33 Tax/labor/social insurance corpus
- J34 Local government corpus
- J35 Statistics/geospatial/land/real estate
- J36 Consumer/privacy/fair trade/legal compliance
- J37 Industry regulation map by vertical
- J38 International trade/export/import public sources
- J39 Environmental/safety/product incident sources
- J40 Corpus map coverage and source-to-output matrix

価値:

- AWSクレジットがある今、広く取る価値が高い。
- 後から作れる成果物の幅を大きくする。
- 直接の本番最小価値より、将来のpacket拡張と継続収集設計に効く。

### Band D: difficult-source render/OCR lanes

Day 4-12で、費用を使いながら価値も出す。

- J41 Playwright capture canary
- J42 Playwright public source crawl batches
- J43 1600px以下 screenshot receipt generation
- J44 DOM/PDF/HAR/console metadata capture
- J45 OCR/Textract for public PDFs and screenshots
- J46 Visual diff and page change detection
- J47 Hard-source source_profile generation
- J48 Render/OCR quality audit

価値:

- fetchだけでは取りにくい公的ページをreceipt化できる。
- スクリーンショットとDOMを組み合わせ、ハルシネーション抜きの証跡を増やせる。
- AWSクレジットを有効に使いやすい。

注意:

- CAPTCHA突破、認証回避、アクセス制限回避はしない。
- robots/terms/明示禁止がある場合はskip ledgerへ入れる。
- screenshotは1600px以下を標準にし、不要な高解像度や長期保存でコストを増やさない。

### Band E: productization and value proof

Day 2-14で継続投入。

- J49 Source-to-output coverage matrix
- J50 Packet/proof page generation at scale
- J51 Agent-facing OpenAPI/MCP/llms discovery fixtures
- J52 Final product readiness and contradiction audit

価値:

- 収集しただけのデータを、売れる成果物に変換する。
- AIエージェントが推薦できる公開説明を増やす。
- 本番デプロイ前後の矛盾を検出する。

## 5. Day 0-3 Fast Production Lane

### Day 0: guardrails, contracts, canary

目的:

- AWSを動かす前に止め方を完成させる。
- 本体P0のcontractを固定する。
- 本番に出す最小packetの形を確定する。

AWS側の準備:

- account/profile/regionを固定する。
- budget/action/permission boundary/role分離を固定する。
- job registryを作る。
- tag policyを固定する。
- cost ledger schemaを固定する。
- zero-bill cleanup checklistを固定する。
- small canaryのみ実行対象として設計する。

本体側の準備:

- packet contractを固定する。
- `source_receipts[]` schemaを固定する。
- `claim_refs[]` schemaを固定する。
- `known_gaps[]` schemaを固定する。
- `billing_metadata` schemaを固定する。
- `request_time_llm_call_performed=false`を固定する。
- no-hit文言を固定する。

Day 0のjob:

- J01 canary
- J12 canary
- J15 minimal fixture canary
- J16 forbidden-claim canary
- J41 Playwright canary

Day 0の成功条件:

- stoplineが機械的に働く設計になっている。
- jobごとのmax spend/max runtime/max itemがある。
- canary artifactがmanifest/checksum付きで出る。
- raw CSVやprivate dataをAWSへ送らない設計が明記されている。
- 本番の最小API/MCP/proof pagesに必要なschemaが揃っている。

Day 0で失敗したら:

- 大規模jobを投入しない。
- 本体P0だけをローカル/既存fixtureで進める。
- stopline/permissions/taggingの矛盾を先に潰す。

### Day 1: P0-A receipt backbone

目的:

- AIエージェントに推薦させるための最小公的証跡を作る。
- 本番デプロイに必要なsource_receipt/claim_ref/no-hitの実例を揃える。

優先job:

- J01 official source profile sweep
- J02 NTA法人番号
- J03 NTAインボイス
- J04 e-Gov法令
- J12 source receipt audit
- J13 claim graph dedupe
- J16 GEO/no-hit/forbidden-claim evaluation

投入しないもの:

- 大規模OCR
- 大規模OpenSearch
- 広域自治体Playwright
- 高額Bedrock分類

理由:

Day 1は本番の土台作りであり、クレジット消費を急ぐ前に「後から大量生成しても壊れない契約」を固める日である。

Day 1の成果物:

- source registry v0
- receipt ledger v0
- no-hit ledger v0
- claim graph v0
- P0 packet examples v0
- forbidden expression report v0

### Day 2: revenue-first data and packet bridge

目的:

- 本番に出す価値を「単なるデータ検索」から「売れる成果物」に変える。

優先job:

- J05 J-Grants/public programs
- J07 gBizINFO
- J08 EDINET metadata
- J09 procurement/tender
- J10 enforcement/public notice
- J11 e-Stat
- J15 packet/proof fixtures
- J49 source-to-output coverage matrix
- J51 agent-facing discovery fixtures

Day 2で作るpacket候補:

- `source_receipt_ledger`
- `evidence_answer`
- `agent_routing_decision`
- `grant_candidate_shortlist`
- `vendor_public_check`
- `invoice_vendor_public_check`
- `regulation_change_watch`
- `procurement_opportunity_radar`

Day 2の成功条件:

- 無料previewと有料packetの違いが明確。
- agentが推薦できる「なぜ買うべきか」の説明がある。
- `known_gaps`が必ず出る。
- no-hitが安全証明になっていない。
- cost previewがある。

### Day 3: staging to fast production

目的:

- AWSの全完了を待たずに、最小価値で本番公開する。
- Day 4以降の大規模corpus buildを、本番後の価値増分として取り込める状態にする。

本番候補に含めるもの:

- P0 packet catalog
- 3-8個のpacket examples
- MCP tool descriptions
- agent-safe OpenAPI
- full OpenAPIへの導線
- `llms.txt`
- `.well-known` discovery
- pricing/cost preview
- proof pages
- no-hit説明
- CSV privacy説明

Day 3のAWS側:

- AWSはDay 4以降のfull corpus buildへ進む準備をする。
- 本番deployはAWS継続実行に依存しない。
- productionがAWS上の一時resourceを直接参照しないようにする。

Day 3のGo条件:

- request-time LLMなし。
- packet contractが固定されている。
- billing metadataがある。
- public proof pagesがある。
- CSV raw非保存が説明されている。
- no-hitの禁止表現が混ざっていない。
- rollbackできる。

Day 3のNo-Go条件:

- source_receiptがない主張が表示される。
- no-hitを「安全」「該当なし確定」「リスクなし」と言っている。
- AWS resourceが本番runtime dependencyになっている。
- billing/cost previewが矛盾している。
- agent-safe OpenAPIとMCPの説明がズレている。

## 6. Day 4-14 Full Corpus Build Lane

### Day 4: scale standard run

目的:

- Day 0-3で固定したcontractに従い、J01-J24を標準規模で増やす。
- 売れる成果物に直結するsourceから厚くする。

優先:

- J05-J11の本格化
- J12/J13/J16の継続audit
- J25/J26のlaw/gazette/public comment
- J27/J28のpermits/grants
- J49/J50のproduct bridge

Spend目安:

- 累計USD 2,000-4,000
- まだ高額stretchはしない

### Day 5: laws, regimes, permits

目的:

- 日本の法律、制度、業法、許認可を「成果物の判断材料」に変換する。

優先:

- J25 law/gazette/notices
- J26 public comment/process
- J27 permit/procedure/industry registry
- J37 industry regulation map
- J33 tax/labor/social insuranceのseed

成果物:

- `permit_rule_check`
- `regulatory_change_impact_packet`
- `industry_compliance_checklist`
- `tax_labor_event_radar`
- `public_comment_change_watch`

Spend目安:

- 累計USD 4,000-6,500

### Day 6: grants, procurement, vendor risk

目的:

- すぐ売上化しやすい「補助金」「入札」「取引先確認」を厚くする。

優先:

- J28 subsidy/public program expansion
- J29 procurement/awards
- J07 gBizINFO join
- J08 EDINET metadata
- J09 procurement
- J10 enforcement/public notice
- J49 source-to-output coverage
- J50 proof page generation

成果物:

- `grant_opportunity_radar`
- `csv_overlay_grant_match`
- `application_readiness_checklist`
- `procurement_opportunity_radar`
- `award_competitor_ledger`
- `counterparty_public_evidence_check`

Spend目安:

- 累計USD 6,500-8,500

### Day 7: local government and regional corpus

目的:

- 自治体・地方制度・地域補助金・地域許認可を広げる。
- 公的情報の広さで競合との差を作る。

優先:

- J34 local government corpus
- J35 statistics/geospatial/land/real estate
- J06 ministry/local PDF extraction
- J42 Playwright public source crawl batches
- J43 screenshot receipt generation
- J45 OCR/Textract for public PDFs/screenshots

成果物:

- `local_grant_radar`
- `local_permit_check`
- `site_location_public_risk_packet`
- `regional_business_environment_packet`
- `real_estate_public_context_packet`

Spend目安:

- 累計USD 8,500-10,500

### Day 8: enforcement, courts, disputes, safety

目的:

- 取引先審査・コンプラ・業法チェックの価値を上げる。

優先:

- J30 administrative disposition/recall
- J31 courts/disputes/appeals
- J36 consumer/privacy/fair trade/legal compliance
- J39 environmental/safety/product incident
- J41-J48 render/OCR lanes for difficult sources

成果物:

- `public_enforcement_dd_packet`
- `counterparty_dispute_enforcement_check`
- `regulated_business_enforcement_watch`
- `competition_consumer_case_context`
- `labor_dispute_compliance_packet`
- `product_recall_public_check`

Spend目安:

- 累計USD 10,500-12,500

### Day 9: standards, certifications, technical compliance

目的:

- JIS/JISC、技適、PSE/PSC、食品表示、PMDA、個人情報、化学物質などを成果物化する。

優先:

- J32 standards/certifications
- J36 consumer/privacy/fair trade
- J39 environmental/safety/product incidents
- J45 OCR/Textract
- J47 hard-source source_profile
- J48 render/OCR quality audit

成果物:

- `product_compliance_public_check`
- `technical_standard_applicability_packet`
- `privacy_guideline_gap_packet`
- `food_labeling_public_rule_check`
- `device_regulatory_public_check`

Spend目安:

- 累計USD 12,500-14,000

### Day 10: algorithmic output factory

目的:

- 収集した情報を、LLM自由生成ではなく、決定表・スコア・差分・証拠グラフで成果物化する。

優先:

- J13 claim graph dedupe/conflict
- J17/J18/J19/J20 controlled stretch equivalents
- J46 visual/page change detection
- J49 source-to-output coverage matrix
- J50 packet/proof generation
- J51 agent-facing fixtures
- J52 contradiction audit

アルゴリズム:

- regulation diff algorithm
- grant matching algorithm
- permit rule algorithm
- vendor risk evidence scoring
- CSV derived-fact overlay algorithm
- public no-hit coverage scoring
- public evidence attention score
- coverage gap score

Spend目安:

- 累計USD 14,000-16,000

### Day 11: high-value stretch

目的:

- Watch lineに近づくまで、最も価値が残っているjobに寄せる。

Stretch候補:

- Playwright/OCRの未処理高価値source
- Bedrock batchによるpublic-only classification
- OpenSearch temporary benchmark
- Athena/Glue QA reruns and compaction
- GEO adversarial eval expansion
- proof page scale generation

入れてよい条件:

- private dataを含まない。
- 成果物に直結する。
- manifest/checksum/cost ledgerが出る。
- stoplineで止められる。
- 本番runtime dependencyにならない。

入れてはいけない条件:

- GPU training
- 意味の薄い高額LLM処理
- NAT Gateway常時稼働
- QuickSight常設
- Marketplace
- support plan変更
- 長期OpenSearch保持

Spend目安:

- 累計USD 16,000-17,500
- USD 17,000を超えたらWatch modeへ入る

### Day 12: slowdown and final value selection

目的:

- 18,300に向けて、価値の低い収集を止める。
- 収集よりも検証・成果物化・exportに寄せる。

継続するjob:

- J12 source receipt audit
- J13 claim graph conflict audit
- J16 forbidden-claim/no-hit evaluation
- J24 packaging/export
- J48 render/OCR quality audit
- J49 coverage matrix
- J50 proof page generation
- J51 discovery fixtures
- J52 contradiction audit

止めるjob:

- 新規広域crawl
- 新規自治体大量投入
- 新規OCR大規模投入
- 新規OpenSearch index増設
- yieldが悪いsource
- terms不明source

Spend目安:

- 累計USD 17,500-18,500
- USD 18,300以降はSlowdown

### Day 13: no-new-work, export, cleanup start

目的:

- 18,900前後で新規投入を止め、成果物の回収とcleanupに移る。

やること:

- 全jobをdrain modeへ。
- 成果物manifestを確定。
- checksumを確定。
- cost/artifact ROI ledgerを確定。
- high-value artifactsをrepo import候補へ変換。
- S3等からローカル/非AWS保存先へexport。
- cleanup順を開始。

Spend目安:

- 累計USD 18,500-19,100
- USD 18,900でNo-new-work

### Day 14: absolute safety, zero-bill cleanup, final import

目的:

- USD 19,300安全線を超えない。
- AWSに継続請求resourceを残さない。
- 本番へ取り込むべき成果物を確定する。

やること:

- 全compute停止。
- job queue停止。
- OpenSearch削除。
- ECR不要image削除。
- Batch/ECS/EC2/EBS/snapshot削除。
- Glue/Athena出力削除。
- CloudWatch logs/alarms/dashboards削除。
- S3 export後にbucket/object削除。
- NAT/EIP/ENI/LBがあれば削除。
- Step Functions/Lambda/EventBridge等があれば削除。
- tagged resource inventoryを空にする。
- untagged resource auditを行う。
- final spend/cost ledgerを出す。
- productionへ追加importする候補を確定する。

End State:

- AWSに継続請求resourceを残さない。
- productionはAWS一時resourceに依存しない。
- 追加AWS保管はしない。

## 7. Fast Spending Without Waste

クレジットを速く使うには、高いサービスを雑に使うのではなく、並列度と価値密度を上げる。

### 7.1 速く使ってよい領域

- EC2 Spot/Batchでの大量fetch/normalize/extract
- Fargate SpotでのPlaywright canary/fallback
- Textract/OCR for public PDFs/screenshots
- Bedrock batch for public-only classification
- temporary OpenSearch retrieval benchmark
- Glue/Athena transform, compaction, QA
- S3短期staging
- CloudWatch短期ログ。ただし保持短縮

### 7.2 速く使ってはいけない領域

- NAT Gateway常時稼働
- 高解像度スクショの無制限保存
- request-time LLM
- private CSV/個人情報処理
- 大量GPU学習
- production runtime dependencyになるAWS resource
- Support/Marketplace/RI/Savings Plans
- 削除しにくい長期管理サービス

### 7.3 Burn-rate target

1-2週間でほぼ使い切るための目安:

- Day 0-1: USD 0-1,000。安全確認優先。
- Day 2-3: USD 1,000-2,500。本番最小価値優先。
- Day 4-6: USD 2,500-8,500。標準corpus拡張。
- Day 7-9: USD 8,500-14,000。Playwright/OCR/地方/処分/標準を拡張。
- Day 10-11: USD 14,000-17,500。algorithm/proof/eval/stretch。
- Day 12: USD 17,500-18,500。slowdown。
- Day 13: USD 18,500-19,100。drain/export。
- Day 14: USD 19,100-19,300。cleanup後の小型manual stretchのみ、原則は停止。

## 8. Queue Design

### 8.1 Queue classes

`q-critical`:

- J01/J02/J03/J04/J12/J13/J15/J16/J24/J49/J51/J52
- 本番と品質に関わる
- 最後まで優先

`q-revenue`:

- J05/J07/J08/J09/J10/J11/J27/J28/J29/J30/J33/J36/J37
- 売れる成果物に直結

`q-corpus`:

- J25/J26/J31/J32/J34/J35/J38/J39/J40
- 広域情報基盤

`q-render`:

- J41-J48
- Playwright/screenshot/OCR

`q-stretch`:

- Bedrock batch
- OpenSearch benchmark
- proof scale
- adversarial eval
- compaction reruns

### 8.2 Queue behavior by spend line

Before USD 17,000:

- All queues allowed if quality gates pass.
- `q-render` and `q-corpus` can be wide.
- `q-stretch` starts only after Day 7 and only with ROI evidence.

USD 17,000-18,300:

- `q-critical`: continue.
- `q-revenue`: continue if yield good.
- `q-corpus`: reduce to high-yield source families.
- `q-render`: only high-value hard sources.
- `q-stretch`: manual selection.

USD 18,300-18,900:

- `q-critical`: continue.
- `q-revenue`: finish in-flight only.
- `q-corpus`: no new arrays.
- `q-render`: finish only if already >70% complete and high value.
- `q-stretch`: stop except proof/eval/export.

USD 18,900-19,300:

- `q-critical`: export/audit/cleanup only.
- All other queues: no new work.

At USD 19,300:

- All compute stop.
- Cleanup only.

## 9. Output-Backcast Priority

エンドユーザーがAIに頼んで欲しがる成果物から逆算すると、優先順位は以下になる。

### 9.1 Highest revenue likelihood

1. 補助金・助成金候補packet  
   必要source: J-Grants、自治体、厚労省助成金、制度ページ、業種ルール、CSV derived facts。

2. 許認可・業法チェックpacket  
   必要source: e-Gov、所管省庁、自治体、業法registry、行政処分、標準処理期間。

3. 取引先公的確認packet  
   必要source: 法人番号、インボイス、gBizINFO、EDINET、処分、調達、官報、許認可。

4. 行政処分・係争・リスク注意packet  
   必要source: 消費者庁、公取委、金融庁、国交省ネガティブ情報、裁判所、労基公表、中労委。

5. 法令・制度変更影響packet  
   必要source: e-Gov法令、パブコメ、官報、告示、通達、ガイドライン。

6. 入札・公募探索packet  
   必要source: 調達ポータル、自治体調達、JETRO、入札公告、落札結果。

7. 税務・労務・社保イベントpacket  
   必要source: 国税庁、eLTAX、日本年金機構、厚労省、最低賃金、労働保険。

### 9.2 Scheduler implication

これにより、単純なsource網羅ではなく、次の順で処理する。

1. 企業同定とreceipt backbone。
2. 補助金・許認可・取引先確認に必要なsource。
3. 行政処分・係争・業法・法令変更。
4. 自治体・地域・統計・地理。
5. 標準・認証・製品安全。
6. Playwright/OCRでしか取れない難source。
7. proof/GEO/API/MCPへの変換。

## 10. Algorithms to Run After Collection

### 10.1 Regulation diff algorithm

Input:

- e-Gov law XML
- gazette/notices
- public comment
- ministry guidelines
- local procedure pages

Output:

- changed provisions
- affected industries
- effective date candidates
- action candidates
- known gaps
- source_receipts
- algorithm_trace

Use:

- `regulatory_change_impact_packet`
- `industry_compliance_checklist`

### 10.2 Grant matching algorithm

Input:

- public program eligibility
- area/industry/size constraints
- deadline
- required documents
- CSV derived facts if user provides CSV locally

Output:

- `eligible`
- `likely`
- `needs_review`
- `not_enough_info`
- score components
- missing facts
- source_receipts

Use:

- `grant_candidate_shortlist`
- `application_readiness_checklist`

### 10.3 Permit rule algorithm

Input:

- industry
- activity
- region
- scale
- staff/license/equipment conditions
- law/procedure source graph

Output:

- permit/procedure candidates
- required agency
- threshold rules
- additional questions
- known_gaps
- no-hit ledger

Use:

- `permit_rule_check`
- `local_permit_check`

### 10.4 Vendor public evidence algorithm

Input:

-法人番号
- invoice registration
- gBizINFO
- EDINET
- procurement awards
- enforcement events
- dispute/court public records
- permits/registries

Output:

- identity confidence
- public evidence attention score
- evidence quality score
- coverage gap score
- event ledger
- no-hit caveats

Use:

- `vendor_public_check`
- `counterparty_dispute_enforcement_check`

### 10.5 CSV private overlay algorithm

Input:

- local-only derived facts from freee/MF/Yayoi/generic CSV
- public source graph

Output:

- monthly review flags
- tax/labor event candidates
- grant matching hints
- vendor public checks
- unknown account/category warnings

Constraints:

- raw CSV非保存
- raw CSV非ログ
- raw CSV非AWS
- small group suppression
- formula injection対策

Use:

- `smb_monthly_review`
- `csv_overlay_grant_match`
- `invoice_vendor_public_check`

## 11. Production Merge Order

本体計画とAWS計画は、以下の順でマージする。

### Phase M0: contract freeze

入れるもの:

- packet contract
- source_receipt schema
- claim_ref schema
- known_gaps schema
- billing metadata
- no-hit wording
- CSV privacy rule

AWS依存:

- なし。Day 0に固定する。

### Phase M1: fast production minimum

入れるもの:

- `source_receipt_ledger`
- `evidence_answer`
- `agent_routing_decision`
- agent-safe OpenAPI
- MCP tool descriptions
- pricing/cost preview
- public proof pages
- `llms.txt`
- `.well-known`

AWS依存:

- J01-J04/J12/J15/J16 canary artifactsのみ。

### Phase M2: revenue packets

入れるもの:

- `grant_candidate_shortlist`
- `vendor_public_check`
- `permit_rule_check`
- `regulation_change_impact_packet`
- `procurement_opportunity_radar`

AWS依存:

- J05-J11/J25-J30/J49-J51。

### Phase M3: broad corpus packets

入れるもの:

- local government packets
- courts/enforcement packets
- standards/certification packets
- tax/labor/social packets
- geo/spatial packets

AWS依存:

- J31-J40/J41-J48/J50-J52。

### Phase M4: final import and cleanup

入れるもの:

- final source registry
- final artifact manifest
- final proof samples
- final GEO eval
- final contradiction audit
- release notes

AWS依存:

- J24/J52。
- cleanup完了後もproductionがAWSに依存していないこと。

## 12. Quality Gates

### 12.1 Release blockers

本番に出してはいけない状態:

- source_receiptなしの断定がある。
- no-hitを安全証明にしている。
- `request_time_llm_call_performed=false`と矛盾する処理がある。
- raw CSVを保存/ログ/AWS投入している。
- billing/cost previewが表示とAPIで矛盾している。
- agent-safe OpenAPIとMCP tool説明が矛盾している。
- terms/robots/明示禁止を無視している。
- known_gapsが空であるべきでないpacketで空になる。
- AWS一時resourceがproduction runtime dependencyになっている。

### 12.2 Corpus acceptance

source familyごとに最低限必要:

- source URL
- source owner
- retrieval method
- terms/robots status
- collected_at
- checksum
- parser/capture version
- source_receipts
- known_gaps
- no-hit semantics
- license_boundary
- retention class

### 12.3 Algorithm acceptance

algorithmごとに最低限必要:

- deterministic inputs
- deterministic output schema
- scoring formula
- decision table or rule graph
- source refs for every claim
- known gap propagation
- no-hit caveat propagation
- test fixtures
- false positive examples
- forbidden claim tests

## 13. Spend Reallocation Rules

### 13.1 If spend is too slow

優先して増やす:

1. Playwright/OCR for high-value public sources.
2. Textract for public PDF/screenshot receipts.
3. Bedrock batch for public-only classification.
4. Temporary OpenSearch retrieval benchmark.
5. Proof page generation at scale.
6. Athena/Glue QA/compaction reruns.
7. GEO adversarial eval expansion.

増やさない:

- network egress
- NAT
- long-lived indexes
- unsupported source scraping
- private data processing

### 13.2 If spend is too fast

止める順:

1. low-yield Playwright crawl
2. low-confidence OCR
3. broad local government crawl outside revenue verticals
4. temporary OpenSearch scale
5. Bedrock classification beyond useful labels
6. corpus expansion not tied to outputs

残す順:

1. J12/J13/J16/J24/J49/J50/J51/J52
2. revenue packet sources
3. official backbone
4. export/cleanup

### 13.3 If a source is blocked

対応:

- bypassしない。
- skip ledgerへ入れる。
- source_profileにblocked reasonを残す。
- known_gapsに反映する。
- 代替の公式sourceを探す。
- no-hitの意味を弱める。

## 14. Zero-Bill Cleanup Schedule

cleanupは最後に一気にやるだけではなく、Day 12から始める。

### Day 12

- 新規大規模jobを止める。
- 不要なtemporary indexesを削除候補へ入れる。
- retention短縮を確認する。
- incomplete artifactsをmanifestで区別する。

### Day 13

- exportを開始する。
- checksumを確定する。
- in-flight computeをdrainする。
- failed/low-value artifactsを残さない判断をする。

### Day 14

- compute削除。
- network artifact削除。
- storage削除。
- logs削除。
- temporary service削除。
- tagged resource inventoryを空にする。
- untagged resource auditを完了する。

残してよいもの:

- 原則なし。

例外:

- ユーザーが明示的に「AWSにアーカイブを残す」と指示した場合のみ。ただし今回の前提は「今後AWSで追加課金しない」なので、推奨はゼロ残し。

## 15. Final Scheduler Recommendation

最終的な実行順は次に固定する。

1. Day 0: guardrails、contract、canary、stop drill。
2. Day 1: J01-J04/J12/J13/J16で公的証跡backbone。
3. Day 2: J05-J11/J15/J49/J51で売れるpacketの最小形。
4. Day 3: fast production deploy。AWS完了を待たない。
5. Day 4-6: grants、permits、procurement、vendor risk、law/gazetteを拡張。
6. Day 7-9: local government、courts/enforcement、standards、tax/labor、stats/geoを拡張。
7. Day 10-11: algorithms、proof pages、GEO eval、temporary retrieval benchmark、public-only classification。
8. Day 12: slowdown。収集より検証・成果物化・exportへ移る。
9. Day 13: no-new-work。drain/export/checksum/cleanup開始。
10. Day 14: 19,300安全線内で完全停止、zero-bill cleanup、本体への最終import。

この設計なら、AWSクレジットは「消費」ではなく、jpciteの資産になる。最初の3日で本番価値を出し、残り11日で日本の公的一次情報を広く証跡化し、最終的にAWSに継続請求resourceを残さない。

