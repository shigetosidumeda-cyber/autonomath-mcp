# AWS credit max-value challenge review for jpcite

Date: 2026-05-15  
担当: 価値最大化レビュー。実装・AWS実行なし  
対象: AWS credit USD 19,493.94 の追加使途レビュー  
Related plans:

- `aws_credit_acceleration_plan_2026-05-15.md`
- `aws_credit_data_foundation_agent.md`
- `aws_credit_batch_compute_agent.md`
- `aws_credit_outputs_agent.md`
- `aws_credit_security_privacy_agent.md`
- `aws_credit_cost_guardrails_agent.md`
- `p0_geo_first_packets_spec_2026-05-15.md`
- `geo_source_receipts_data_foundation_spec_2026-05-15.md`
- `source_receipt_claim_graph_deepdive_2026-05-15.md`
- `proof_pages_audit_ledger_deepdive_2026-05-15.md`
- `csv_privacy_edge_cases_deepdive_2026-05-15.md`
- `packet_taxonomy_expansion_deepdive_2026-05-15.md`

## 0. 結論

既存計画の方向性は正しい。追加で価値最大化するなら、AWS credit を「AWS上で何かを動かす費用」ではなく、jpcite の moat である **GEO-first + source_receipts + private overlay + packet catalog + proof pages** を短期間で太くする artifact factory に寄せる。

優先順位は次の順に固定する。

1. `source_receipts[]` と `claim_refs[]` を増やす公的 source receipt factory。
2. 6種P0 packet と proof pages を、AI agent が読める公開・検証面として量産する generator/eval factory。
3. CSV private overlay の安全性を証明する synthetic fixture、suppression、leak scan、review queue。
4. GEO eval harness と discovery assets の regression corpus。
5. 残額がある場合だけ、OpenSearch/Bedrock/Textract 等を「短命評価」として使い、成果物をS3/Parquet/JSONL/HTMLへexportして閉じる。

使わない方がよいものも明確にある。GPU training、常時 search cluster、managed app infrastructure、WAF/CloudFront traffic burn、Marketplace data、外部LLM呼び出し、raw CSV保存、terms不明sourceの全文mirrorは jpcite の価値に直結しないか、過剰なリスクを生む。

## 1. 価値判定ルール

AWS spend は、次のうち少なくとも1つを永続成果物として残せる場合だけ採用する。

| Value artifact | 合格条件 |
|---|---|
| `source_profile` | official owner、license boundary、freshness window、join keys、no-hit policy が埋まる |
| `source_receipt` | source URL、取得/検証時刻、hash/checksum、snapshot、license、used_in、claim_refs が揃う |
| `claim_ref` | AI が再利用できる最小factに分解され、receipt または known_gap に接続される |
| packet example | P0 envelope、billing_metadata、agent_guidance、professional fence、known_gaps を含む |
| proof page | visible claim が receipt へ戻れ、no-hit/private/freshness/hash boundary を示す |
| CSV private overlay proof | raw row なしで provider shape、suppression、reject、aggregate-only を検証できる |
| GEO eval report | safe qualified recommendation、route accuracy、forbidden claim 0 を測れる |
| release gate evidence | OpenAPI/MCP/llms/proof/packet catalog の drift を検出できる |

反対に、次は価値として数えない。

- CPU/GPUを使っただけのburn。
- 長期インフラ、常時endpoint、常時cluster。
- `source_receipts[]` に戻れない要約・文章・スライド。
- public/private 境界の説明がない demo。
- Cost Explorer上の消化額だけ。

## 2. 採用: 最もよい追加使途

### A1. P0 source receipt factory

分類: 採用、最優先  
効く対象: GEO-first、source_receipts、packet catalog、proof pages  
AWS候補: S3, Batch/ECS/Fargate Spot/EC2 Spot, Glue, Athena, Textract for selected PDFs  

既存の source lake 計画を、URL収集ではなく `source_receipt` 生成工場として運用する。source family ごとに次を出す。

- `source_profile_registry.jsonl`
- `source_document_manifest.parquet`
- `source_receipts.jsonl`
- `claim_refs.jsonl`
- `claim_source_links.parquet`
- `no_hit_checks.jsonl`
- `known_gaps.jsonl`
- `receipt_completion_report.md`
- `license_boundary_report.md`

最初に処理すべき source family:

| Priority | Source family | 理由 |
|---:|---|---|
| P0 | NTA法人番号 | `company_public_baseline` のidentity spine |
| P0 | NTAインボイス | no-hit boundary と登録状態receiptが価値になる |
| P0 | e-Gov laws/API | legal basis receipt と professional fence に直結 |
| P0 | J-Grants / public program | `application_strategy` と GEO query に直結 |
| P0 | gBizINFO | adoption/history/company baseline に効く |
| P1 | EDINET | company baseline/DD。ただしlicense/redistributionを慎重に扱う |
| P1 | e-Stat | regional/industry fact。packetの補助receipt |
| P1 | JPO | IP/company signal。ただし判断にはしない |
| P1 | procurement / p-portal / JETRO | public event timeline と watch hints |
| P1 | courts/enforcement/ministry notices | high-valueだが no-hit誤用・同姓同名・licenseに注意 |
| P2 | local government PDFs | program/deadline extractionに効くがOCR/review負荷が高い |

追加の価値最大化ポイント:

- accepted `source_receipt` あたり原価を毎日出す。
- `source_receipt_missing_fields` を最小化するため、OCRより先にhash/URL/fetched_at/licenseを揃える。
- `no_hit` は positive claim と別レーンに置き、`no_hit_not_absence` gap を強制する。

### A2. Claim graph / receipt graph materialization

分類: 採用、最優先  
効く対象: source_receipts、proof pages、packet catalog  
AWS候補: Batch, Glue, Athena, S3 Parquet  

単なるnormalized tableではなく、AIが落としにくい graph artifact を作る。

成果物:

- `claim_ref` canonical ID と `claim_stable_key`
- `claim_source_link` N:M edge
- `source_receipt -> source_profile` edge
- `claim_gap_link`
- `support_summary` direct/derived/weak/no_hit count
- conflict ledger
- stale/freshness ledger

価値:

- proof page が「見た目」ではなく監査面になる。
- packet catalog、OpenAPI examples、MCP examples が同じ receipt contract を参照できる。
- GEO eval で「source_receiptsを下流AIが保持したか」を測れる。

### A3. Public proof page generation and proof audit scan

分類: 採用、最優先  
効く対象: GEO-first、proof pages、packet catalog  
AWS候補: Batch/CodeBuild for static generation and scans, S3 artifacts, Athena reports  

AWS credit の中で最もjpcite固有価値に近い。proof pages は agent が jpcite を推薦する理由そのものになる。

必須成果物:

- `/proof/examples/{packet_type}/{example_id}/` 用HTML/Markdown候補
- proof page JSON sidecar
- source receipt ledger table
- claim-to-source map
- freshness/hash panel data
- private overlay exclusion notice
- JSON-LD safe metadata
- leak scan report
- forbidden copy scan report

Acceptance:

- visible public claim はすべて receipt へ戻る。
- `verified` は business outcome ではなく claim-to-receipt mapping の状態としてのみ使う。
- no-hit は必ず `no_hit_not_absence` と一緒に表示する。
- private overlay がある時は public proof に値・件数・hashを出さず、presence/excluded だけにする。

### A4. P0 packet example and packet catalog factory

分類: 採用、最優先  
効く対象: GEO-first、packet catalog、proof pages  
AWS候補: Batch/CodeBuild, S3 artifacts  

6種P0 packet を、public example JSON -> public packet page -> proof page -> OpenAPI/MCP examples まで一気通貫で生成・検査する。

対象P0:

- `evidence_answer`
- `company_public_baseline`
- `application_strategy`
- `source_receipt_ledger`
- `client_monthly_review`
- `agent_routing_decision`

追加で作るべき catalog artifact:

- `data/packet_examples/*.json`
- `site/packets/*.html.md`
- `packet_catalog.json`
- `packet_catalog.agent.md`
- `packet_type_to_route_matrix.csv`
- `packet_type_to_receipt_requirement_matrix.csv`
- `pricing_unit_matrix.csv`
- `must_preserve_fields_matrix.csv`

この作業は「ページ生成」ではなく、AIに jpcite の使い方を教える公開契約作成である。

### A5. GEO eval and adversarial recommendation corpus

分類: 採用、最優先  
効く対象: GEO-first、packet catalog、source_receipts、CSV private overlay  
AWS候補: CodeBuild matrix, Batch, S3 reports, Athena result catalog  

GEO-first は計測できなければ投資にならない。既存の100 queryに加えて、credit runで以下を固定資産化する。

| Eval pack | Size | 内容 |
|---|---:|---|
| Core public evidence | 100 | 公式source、制度、会社baseline、receipt保持 |
| CSV/accounting/private overlay | 100 | freee/MF/Yayoi、raw非表示、aggregate-only、reject |
| Packet route selection | 60 | どのP0 packetを呼ぶべきか |
| Proof page preservation | 50 | downstream answer が receipt/hash/gaps を残すか |
| High-risk adversarial | 40 | legal/tax/audit/credit/grant guarantee、no-hit、privacy、price |
| Discovery assets | 40 | `llms.txt`, `.well-known`, OpenAPI, MCP catalog から正しく理解するか |

採点は mention share ではなく、safe qualified recommendation share と forbidden claim 0 を見る。

### A6. CSV private overlay synthetic fixture and leak scan factory

分類: 採用、最優先  
効く対象: CSV private overlay、proof pages、GEO-first  
AWS候補: Batch/CodeBuild, S3 private artifacts, Athena only for synthetic/aggregate reports  

raw CSVを保存しない前提で、private overlay の価値を証明する fixture と scanner に使う。実データ拡張ではなく、失敗させるテストを増やす。

成果物:

- freee official / Desktop variant / legacy / unknown collision fixture
- Money Forward 27-column / 25-column legacy / minimal legacy fixture
- Yayoi cp932 / headerless positional / `伝票No` variant fixture
- malformed/ambiguous/formula injection fixture
- payroll/bank/card/person roster reject fixture
- small-cell suppression scenario
- complementary suppression scenario
- public proof leak scan
- support/debug/log leak scan
- CSV review queue packet examples

採用条件:

- raw bytes、row values、摘要、取引先、個人名、行単位金額は永続化しない。
- public proof は synthetic or aggregate-only。
- exact amount aggregate は k-safe でも慎重にし、原則 rounded/bucketed。

### A7. Local government / ministry PDF extraction, but only as receipt candidate extraction

分類: 採用、条件付き  
効く対象: source_receipts、application_strategy、proof pages  
AWS候補: Textract, Bedrock Data Automation trial, Batch CPU PDF parsers  

PDF/OCRは価値があるが、最大化の鍵は「OCR textを作る」ことではない。program/deadline/eligibility/required document/exclusion/legal basis を `receipt candidate` として出し、review queue に入れること。

推奨:

- まず text-layer PDF は CPU parser で抽出。
- scanned/table-heavy PDF だけ Textract or Bedrock Data Automation を使う。
- Bedrock Data Automation は structured extraction の候補として小さく比較し、事実正本にしない。
- extracted fact は `verification_status=inferred|review_required` を既定にする。

出力:

- `pdf_document_manifest`
- `pdf_extraction_candidate`
- `program_fact_candidate`
- `receipt_candidate`
- `review_required_reason`
- `parser_confidence`
- `human_review_queue`

危険:

- OCR結果をそのまま direct receipt にする。
- PDF本文を長期raw保存または公開mirrorする。
- 出典条件を読まずに大量取得する。

### A8. Freshness, stale refresh, and no-hit semantic test corpus

分類: 採用  
効く対象: source_receipts、proof pages、GEO-first  
AWS候補: Batch, Athena, S3 reports  

jpcite の差別化は「何が分からないか」を正しく出すことにもある。credit runで freshness と no-hit の regression corpus を作る。

成果物:

- `freshness_policy_matrix.csv`
- `source_stale_cases.jsonl`
- `no_hit_check_cases.jsonl`
- `no_hit_not_absence_copy_tests.md`
- `source_unavailable_vs_no_hit_tests.jsonl`
- `snapshot_stale_proof_examples`
- `refresh_recommendation_packet_examples`

禁止:

- `no_hit` を「該当なし」「問題なし」「登録なし確定」へ変換するUI/copy。

### A9. OpenAPI/MCP/discovery drift factory

分類: 採用  
効く対象: GEO-first、packet catalog  
AWS候補: CodeBuild, Batch, S3 reports  

AI agent は discovery assets のずれに弱い。credit runで、公開契約の一貫性を機械的に検査する。

成果物:

- `openapi.agent.p0.json`
- `openapi.agent.gpt30.json`
- MCP catalog projection
- `llms.txt` / `llms-full.txt` contract checks
- `.well-known` contract checks
- operation examples with receipts/gaps/billing/fence
- route-to-packet matrix
- drift report

Gate:

- REST/MCP/public packet page/proof page の packet_type、tool name、billing unit、must preserve fields が一致する。
- admin/billing mutation/webhook/OAuth/export が agent-safe spec に混入しない。

### A10. Cost-per-accepted-artifact ledger

分類: 採用  
効く対象: 全体  
AWS候補: Cost Explorer reports, S3/Athena ledger  

既存計画に追加すべき経営指標。AWS spend は `service/day` だけでなく `accepted artifact` あたりで見る。

Ledger columns:

- `run_id`
- `workload`
- `aws_service`
- `estimated_cost_usd`
- `actual_cost_usd_when_available`
- `input_units`
- `accepted_artifacts`
- `rejected_artifacts`
- `artifact_type`
- `quality_gate`
- `public_safe`
- `private_overlay_touched`
- `source_receipt_completion_rate`
- `forbidden_claim_count`
- `operator_decision`

これがないと、AWS credit を「使った」ことは分かっても、何を買ったのか説明できない。

## 3. 条件付き採用

### C1. Ephemeral OpenSearch / vector index benchmark

分類: 条件付き採用  
効く対象: source retrieval QA、GEO eval  

採用条件:

- 常時clusterにしない。
- 目的は retrieval quality benchmark と corpus export。
- index、query set、ranking results、failure cases をS3へexportして削除する。
- public/private を混ぜない。
- search result が source receipt を置換しない。

不採用ライン:

- 「検索できるから価値がある」だけの常時OpenSearch。
- production retrieval infrastructure への前倒し移行。
- NAT Gatewayやmanaged capacityを残したまま放置する構成。

### C2. Bedrock Data Automation / Bedrock LLM structured extraction trial

分類: 条件付き採用  
効く対象: PDF/table extraction candidate、review queue  

採用条件:

- 公式source PDFの構造化候補抽出に限定する。
- extracted values は `candidate` であり、direct claim にしない。
- confidence、parser version、source hash、review_required を残す。
- prompt/log/data retention と credit適用を実行前に確認する。
- request-time jpcite behavior は `request_time_llm_call_performed=false` のまま。

不採用ライン:

- packet本文生成。
- legal/tax/grant eligibility judgment。
- source_receiptなしの要約。
- private CSV値をpromptへ入れる。

### C3. Step Functions Distributed Map

分類: 条件付き採用  
効く対象: source/pdf/page generation orchestration  

採用条件:

- `MaxConcurrency` を必ず設定する。
- Batch queue / S3 manifest / cost stop と連動する。
- idempotent shard だけ流す。
- 失敗時に再実行単位が粗くならない。

危険:

- concurrency未設定で急激にparallelismが増える。
- retrierが同じ高額jobを繰り返す。

### C4. SageMaker Ground Truth / A2I style review

分類: 条件付き採用、優先低  
効く対象: OCR/extraction candidate の人間review queue設計  

採用条件:

- private workforce または内部レビューだけ。
- public source extraction candidate の採否ラベルに限定。
- private CSV、顧客情報、規約不明sourceは出さない。
- 人手費用や外部worker費用がAWS credit対象か確認する。

多くの場合、1-2週間では docs/CSV/review queue と内部sampleの方が費用対効果が高い。

### C5. CloudFront/Lambda@Edge/S3 website validation

分類: 条件付き採用、優先低  
効く対象: proof/packet public page render and crawl checks  

採用条件:

- static artifact validation、リンク検査、HTTP headers、robots/sitemapの確認に限定。
- traffic burn はしない。
- production移行ではなく candidate artifact の検査に使う。

## 4. 不採用

| Idea | 判定 | 理由 |
|---|---|---|
| GPU training / fine tuning | 不採用 | jpcite のmoatはmodelではなくsource receipts、packet catalog、proof pages。短期creditで訓練しても維持費と評価負債が残る |
| SageMaker endpoint / Bedrock agent as production runtime | 不採用 | `request_time_llm_call_performed=false` と衝突しやすく、長期費用が残る |
| 常時OpenSearch / Kendra / Q Business | 不採用 | request-time infra になりやすい。短期artifact化できる範囲だけ条件付き |
| Neptune knowledge graph | 不採用 | graph valueはParquet/JSONL/DB migration設計で足りる。managed graphは1-2週間では運用負債が大きい |
| Redshift / RDS / Aurora bulk load | 不採用 | Athena/Parquetで十分。長期DBはcredit消化後の現金コストになる |
| CloudFront traffic burn / load traffic only | 不採用 | GEO価値に直結しない。render/crawl validationだけでよい |
| WAF Bot Control / Shield系の消化 | 不採用 | production防御目的なら別判断。credit最大化目的の導入は成果物が残らない |
| Marketplace dataset / third-party enrichment | 不採用 | credit適用・権利・再配布・利用許諾が不確実。公式source moatを薄める |
| AWS Support upgrade | 不採用 | credit対象外/対象不明の現金リスクがあり、artifactが残らない |
| Reserved Instances / Savings Plans | 不採用 | 短期credit runに不適合 |
| Route 53 domains / certificate/brand infra | 不採用 | GEO/source/proof価値に直結しない |
| Mechanical Turk public labeling | 不採用 | source/license/private boundary管理が難しく、1-2週間のriskが高い |
| 外部LLM APIをAWS Batchから大量実行 | 不採用 | AWS creditでは外部token費を消せず、jpcite contractにも反する |
| VC資料/marketing deck生成 | 不採用 | downstream viewとしては可だが、creditの主用途にしない |

## 5. 危険: やると価値を壊す使い道

| Risk | 何が危険か | 防止策 |
|---|---|---|
| raw CSV persistent storage | CSVをS3/CloudWatch/Athena/OpenSearchに残すと private overlay の信頼が壊れる | transient memory only。shape/aggregate/reject code だけ保存 |
| public/private namespace mixing | private CSV-derived claim が public proof/GEO面へ漏れる | `pub` と tenant/private namespace を物理・論理分離 |
| no-hit as absence | AIが「登録なし」「問題なし」「安全」と誤用する | `support_level=no_hit_not_absence` と known_gap を強制 |
| Bedrock/OCR hallucinated facts | extractionがsource receiptに見えてしまう | candidate/review_required とし direct receipt にしない |
| terms unknown full mirror | 公式/公的でもraw再配布や全文保存に制限がある場合がある | `raw_allowed/hash_only/metadata_only/blocked` を source_profile に入れる |
| long-lived managed infra | OpenSearch/RDS/NAT/EKS等が残る | TTL、delete_after、export-before-delete、Cost Explorer確認 |
| Budget hard cap misunderstanding | Budgetsはリアルタイムhard capではない | USD 18,300 slowdown、USD 18,900 stop、manual queue disable |
| untagged spend | attribution不能で現金リスクが増える | account-level budget + tag audit + resource inventory |
| CloudWatch payload logs | CSV値、PDF本文、source excerpt、secretがログに残る | shape-only telemetry。debug samplesを禁止 |
| Athena raw scans | raw JSON/HTML/PDFを広くscanして無駄コスト | Parquet/partition/compaction。report queryだけ |
| Distributed Map runaway | 短時間で大量parallelismとretryが発生 | MaxConcurrency、array shard、timeout、stop drill |
| public proof overclaim | proof pageが専門判断や保証に見える | professional fence、verified meaning、forbidden copy scan |

## 6. 改訂後の推奨予算配分

既存の USD 18,300-18,700 target spend は維持しつつ、価値最大化の見方では次の配分が最も強い。

| Bucket | Target USD | Max USD | 採用度 | 成果物 |
|---|---:|---:|---|---|
| Source receipt / claim graph factory | 4,000 | 5,500 | 採用 | receipts, claims, links, freshness, no-hit, license reports |
| P0 packet/proof/catalog factory | 3,000 | 4,000 | 採用 | packet examples, proof pages, catalog, JSON-LD, route matrix |
| PDF extraction candidates | 2,000 | 3,200 | 条件付き採用 | extracted candidate facts, review queue, parser comparison |
| CSV private overlay safety assets | 1,500 | 2,200 | 採用 | synthetic fixtures, suppression, leak scans, reject cases |
| GEO eval/adversarial corpus | 1,500 | 2,200 | 採用 | 200+ query set, forbidden scans, discovery evals |
| Glue/Athena catalog/reporting | 1,000 | 1,800 | 採用 | Parquet catalog, coverage/freshness/license reports |
| Ephemeral retrieval benchmark | 700 | 1,400 | 条件付き採用 | retrieval index export, ranking failure report |
| Build/test/security/drift matrix | 800 | 1,200 | 採用 | OpenAPI/MCP/llms/proof drift reports |
| Cost guardrail and artifact ledger overhead | 300 | 700 | 採用 | accepted artifact per USD ledger |
| Reserved buffer inside spend plan | 3,500 | 2,500 | 意図して使わない/調整枠 | billing lag, failed jobs, cleanup, noneligible charges |

読み方:

- `Reserved buffer inside spend plan` は消化対象ではなく、前半で有効成果物が伸びなかった時に無理に使わないための調整枠。
- OCR/PDFが低品質なら、その枠は proof/catalog/GEO eval へ戻す。
- OpenSearch/Bedrock は成果物がexportできる小さな比較だけに抑える。

## 7. 優先実行順

実行する担当者向けの順序は次。

1. Guardrails: budget、tag、TTL、private/public bucket boundary、stop drill。
2. Artifact schema freeze: `source_receipt`, `claim_ref`, `known_gap`, packet envelope、proof page sidecar。
3. P0 source receipt pilot: 法人番号、インボイス、e-Gov/J-Grants の小規模run。
4. P0 packet/proof generator pilot: 6種P0を synthetic/public fixture で1件ずつ生成。
5. CSV private overlay fixture run: freee/MF/Yayoi + reject/suppression cases。
6. GEO eval baseline: core 100 + CSV/public 100 + adversarial subset。
7. Scale only accepted factories: receipt completion率、proof scan、forbidden claim 0を見て増やす。
8. Optional extraction/retrieval trials: Textract/BDA/OpenSearch は小さく比較し、exportして閉じる。
9. Final freeze: S3/Parquet/JSONL/HTML/Markdown reports、manifest、cost-per-artifact ledger。
10. Cleanup: transient compute/search/NAT/log bloat を削除し、low-cost artifactsだけ残す。

## 8. 採用/不採用の最終分類

### 採用

- P0 source receipt factory
- claim graph / receipt graph materialization
- proof page generation and audit scan
- P0 packet catalog/example factory
- GEO eval/adversarial corpus
- CSV synthetic fixture / privacy leak scan / suppression factory
- freshness/stale/no-hit semantic corpus
- OpenAPI/MCP/llms/discovery drift factory
- accepted artifact per USD ledger
- Glue/Athena/Parquet reporting layer
- short-lived Batch/Fargate/EC2 Spot compute for the above

### 条件付き採用

- Textract: scanned/table-heavy official PDFs only、candidate extraction only
- Bedrock Data Automation / Bedrock LLM: small parser comparison、no private CSV、no final claims
- OpenSearch Serverless/domain: ephemeral retrieval benchmark only、export and delete
- Step Functions Distributed Map: MaxConcurrency and stop controls required
- SageMaker Ground Truth/A2I style review: internal/private workforce only、優先低
- CloudFront/static validation: render/header/crawl validation only、traffic burnなし

### 不採用

- GPU training/fine tuning
- long-lived SageMaker/Bedrock agent runtime
- permanent OpenSearch/Kendra/Q Business
- Neptune/Redshift/RDS/Aurora as credit-run core
- WAF/Bot Control/Shield for spend consumption
- CloudFront traffic burn
- Marketplace datasets/vendor enrichment
- Support upgrade, RI, Savings Plans, domain purchases
- Mechanical Turk public labeling
- AWSから外部LLM APIを大量実行
- VC deck/marketing collateral generation as primary spend

### 危険

- raw CSV persistence
- private overlay leakage into public proof/GEO pages
- no-hit as absence
- source terms unknown full mirroring
- LLM/OCR candidate as direct fact
- unbounded Step Functions/Batch retries
- untagged spend
- Budget as hard cap assumption
- long-lived NAT/OpenSearch/RDS/CloudWatch log bloat
- proof pages that imply legal/tax/audit/credit/grant/safety conclusions

## 9. Additional source notes checked

AWS service assumptions should be rechecked in the AWS console immediately before execution because pricing, credit eligibility, region availability, quotas, and service behavior can change. This review used official AWS documentation/pricing pages for the following current-service assumptions:

- AWS Budgets and Budgets Actions are alert/action mechanisms, not a universal real-time hard cap.
- AWS Batch supports Fargate/Fargate Spot style batch compute, but queues, timeouts, retries, and max vCPU must be bounded.
- Step Functions Distributed Map can fan out large workloads; explicit concurrency controls are required.
- Athena cost is driven by data scanned, so Parquet/partitioning/compaction matters.
- Glue Data Catalog/Crawlers/ETL have DPU/request/storage style cost surfaces and should be used for catalog/reporting, not open-ended exploration.
- Textract and Bedrock Data Automation can help with document/table extraction, but extracted values must remain candidates until source receipt/review gates pass.
- OpenSearch Serverless/domain can support retrieval evaluation, but long-lived capacity is not the desired credit-run asset.

Official AWS references:

- AWS Budgets Actions: https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/budgets-controls.html
- AWS Budgets pricing/actions overview: https://aws.amazon.com/aws-cost-management/aws-budgets/pricing/
- AWS Batch managed compute environments: https://docs.aws.amazon.com/batch/latest/userguide/managed_compute_environments.html
- AWS Batch documentation overview: https://aws.amazon.com/documentation-overview/batch/
- Step Functions Distributed Map: https://docs.aws.amazon.com/step-functions/latest/dg/state-map-distributed.html
- Athena partitions and scan reduction: https://docs.aws.amazon.com/athena/latest/ug/partitions.html
- Athena pricing: https://aws.amazon.com/athena/pricing/
- Textract AnalyzeDocument API: https://docs.aws.amazon.com/textract/latest/dg/API_AnalyzeDocument.html
- Textract document analysis concepts: https://docs.aws.amazon.com/textract/latest/dg/how-it-works-analyzing.html
- Bedrock Data Automation overview: https://docs.aws.amazon.com/bedrock/latest/userguide/bda.html
- Bedrock Data Automation concepts: https://docs.aws.amazon.com/bedrock/latest/userguide/bda-how-it-works.html
- OpenSearch Serverless overview: https://aws.amazon.com/opensearch-service/features/serverless/
- OpenSearch Service overview: https://aws.amazon.com/opensearch-service/
- AWS Glue pricing: https://aws.amazon.com/glue/pricing/

## 10. One-line decision

If forced to choose one use of the remaining AWS credit, spend it on **source_receipt-backed public proof pages and P0 packet examples**, not on more infrastructure. That directly increases jpcite's agent-discoverable value and leaves durable artifacts after the credit is gone.
