# AWS credit review 19/20: final value maximization challenge

作成日: 2026-05-15  
担当: 最終価値最大化チャレンジ  
対象: jpcite P0計画、AWS credit unified plan、review 01-18  
AWS account context: `bookyou-recovery` / `993693061769` / `us-east-1`  
実行状態: 計画レビューのみ。AWS CLI/API、AWSリソース作成、デプロイ、既存コード変更は行っていない。

## 0. 結論

現時点の計画は、方向性としては成立している。AWS credit を「本番インフラ」ではなく「短期 artifact factory」として使い、成果物を jpcite 本体へ戻してから zero-bill cleanup する設計は正しい。

ただし、USD 19,493.94 を1-2週間でほぼ使い切り、かつ本番デプロイを早めるなら、既存計画へ次の4点を追加・強化するべきである。

1. **AWS成果物を本体P0へ戻す順番を、Day単位ではなくRC単位に固定する。**
   - AWS全体完了を待たず、RC1/RC2/RC3として小さく本番へ近づける。
   - 最初のproductionは3 packetだけでよいが、contract、receipt、pricing、MCP/API、proof、GEO gateは必須。

2. **credit消費は「高速」だが、「source lake偏重」ではなく productization reserve を先に確保する。**
   - 大量source receiptだけでは、AI agentが推薦する理由になりにくい。
   - `packet`, `proof`, `geo_eval`, `deploy_artifact` を早い段階で増やす。

3. **AWS自走設計は採用するが、rate limit非依存と暴走停止を同時に満たす。**
   - Codex/Claude Codeが止まってもAWSは進む。
   - ただし `control_spend`, `paid_exposure`, `untagged_spend`, `private_leak`, `no_hit_misuse`, `accepted_artifact_density` で自動減速・停止する。

4. **追加で作るべき価値は「データを集める」より「AI agentが推薦しやすい完成済み成果物」に寄せる。**
   - source coverage heatmap
   - agent route cards
   - no-hit adversarial corpus
   - CSV private overlay synthetic matrix
   - proof diversity pack
   - source-to-packet coverage frontier
   - deploy-ready RC bundle

最終判断:

```text
GO: AWS credit runを計画へ入れる。
GO: fast-lane productionをAWS全体完了前に狙う。
GO: 自走Batch/Step Functions/EventBridge/Lambda kill switch設計を入れる。
NO-GO: raw CSV保存、request-time LLM、常設AWS検索基盤、CPU burn、source lakeだけで終わる実行。
NO-GO: AWS上のS3/ECR/Batch/OpenSearch/Glue/Athena/CloudWatchを残したまま「完了」と言うこと。
```

## 1. このレビューで見たもの

主な入力:

- `consolidated_implementation_backlog_deepdive_2026-05-15.md`
- `aws_credit_unified_execution_plan_2026-05-15.md`
- `aws_credit_review_01_cost_stoplines.md`
- `aws_credit_review_02_zero_bill_cleanup.md`
- `aws_credit_review_03_repo_script_mapping.md`
- `aws_credit_review_04_source_priority.md`
- `aws_credit_review_05_ocr_bedrock_opensearch.md`
- `aws_credit_review_06_network_transfer_risk.md`
- `aws_credit_review_07_iam_budget_policy.md`
- `aws_credit_review_08_artifact_manifest_schema.md`
- `aws_credit_review_09_queue_sizing_pacing.md`
- `aws_credit_review_10_terminal_command_stages.md`
- `aws_credit_review_11_source_terms_robots.md`
- `aws_credit_review_12_csv_privacy_pipeline.md`
- `aws_credit_review_13_packet_proof_factory.md`
- `aws_credit_review_14_geo_eval_pipeline.md`
- `aws_credit_review_15_repo_import_deploy.md`
- `aws_credit_review_16_incident_stop.md`
- `aws_credit_review_17_daily_operator_schedule.md`
- `aws_credit_review_18_cost_artifact_ledger.md`

守る制約:

- AWS credit face value: USD 19,493.94
- 意図的な上限: USD 19,300
- `USD 18,900` 以降は no-new-work
- `USD 19,100-19,300` は manual stretch のみ
- AWS Budgets は hard cap ではない
- raw CSV 非保存
- request-time LLM なし
- private CSV をS3、OpenSearch、Bedrock、Textract、CloudWatch、Athena result、public proof、OpenAPI examples、MCP examplesへ入れない
- no-hit は `no_hit_not_absence`
- AWS終了後は zero-bill posture
- production runtime はAWS成果物S3やAWS computeへ依存しない

## 2. 最大の残課題

### 2.1 AWSで価値を作ることと本番に出すことが、まだ少し別文書に分かれている

review 15/17/18でかなり統合されているが、実行時に迷う危険が残る。

危険な運用:

- AWSでJ01-J24を全部走らせる
- その後に巨大なexport bundleができる
- そこから本体へ何を入れるか考える
- deploy直前にschema drift、leak、terms不明、proof薄さが見つかる

採用すべき運用:

- AWSの各waveは、最初から `RC1`, `RC2`, `RC3`, `internal-only`, `do-not-import` に分類する
- productionに入れるものは小さく、検証済みに限定する
- AWS側はproductionを待たずに自走する
- productionはAWSを待たずにRC1を出す

### 2.2 「クレジットを速く使う」要求と「安全に止める」要求が衝突しやすい

ユーザー要求は「なるべく速く使い切りたい」。これは妥当。ただし高速消費は、次の3種類に分けなければ危険。

| 消費 | 判定 | 理由 |
|---|---|---|
| 高密度artifact生産 | 採用 | source_receipt/proof/GEO/deploy artifactが増える |
| 低密度探索 | 条件付き | source familyの未知性を減らすなら短く許容 |
| burn目的burn | 禁止 | AWS billは増えるがjpcite価値が増えない |

高速消費の正しい形は、1つの巨大queueではなく、複数の小さなcapped queueを15-30分窓で回し、低密度queueを自動で降格すること。

### 2.3 Source lakeだけではGEO価値にならない

jpciteの主戦場は SEO ではなく GEO。つまり、人間が検索するLPより、AI agentが「この用途ならjpcite MCP/APIを使う」と判断できる材料が重要である。

そのため、AWS runの成功指標は raw record count ではない。少なくとも次を並行して作る必要がある。

- agentが読める packet examples
- proof pages
- cost preview examples
- MCP tool examples
- OpenAPI examples
- `llms.txt` / `.well-known` discovery artifacts
- no-hit caveat examples
- known gaps examples
- when-to-use / when-not-to-use route cards
- failure taxonomy

### 2.4 CSV価値は高いが、AWSにraw CSVを入れない設計を徹底する必要がある

CSVによる価値拡張は強い。freee/MoneyForward/Yayoiをユーザーがdropするだけで、AI agentが有用な成果物を返せる流れは課金理由になる。

ただし、AWS credit runで作るべきものは raw CSV処理基盤ではなく、次である。

- provider fingerprint
- header alias map
- synthetic fixture
- redaction/suppression rules
- k-safe aggregate rule
- private overlay schema
- public source join candidate rule
- leak scan corpus
- unsupported/rejected reason catalog

## 3. 最終採用すべき追加AWS活用案

既存J01-J24へ、実装上は「追加job」として入れるか、既存jobのsub-laneとして入れる。

### A1. Source-to-packet coverage frontier

目的:

どのsource familyを処理すると、どのpacket/proof/GEO成果物が増えるかを数理的に可視化する。

作るもの:

- `source_packet_coverage_matrix.parquet`
- `coverage_frontier_report.md`
- `packet_blocker_by_source.jsonl`
- `marginal_value_by_source_family.jsonl`

アルゴリズム:

```text
value(source_family) =
  packet_unlock_score
  + proof_unlock_score
  + geo_route_score
  + source_uniqueness_score
  - terms_risk_penalty
  - privacy_risk_penalty
  - expected_cost_penalty
```

使い道:

- J05/J06/J09/J10/J17の優先順位を機械的に並べる
- 低価値source lake作成を止める
- 「このsourceを取ると、どの成果物が増えるか」を説明できる

採用理由:

現在の計画はsource優先度とROIが分かれている。このmatrixで、source収集とproductizationを直接つなげられる。

### A2. Agent route cards

目的:

AI agentがjpciteを推薦する条件、推薦しない条件、MCP/API/cost previewへの案内文を機械可読にする。

作るもの:

- `agent_route_cards/*.json`
- `agent_route_cards.md`
- `when_to_use_jpcite.jsonl`
- `when_not_to_use_jpcite.jsonl`
- `recommendation_copy_safe_examples.jsonl`
- `recommendation_copy_forbidden_examples.jsonl`

例:

```json
{
  "route_id": "csv_monthly_review_with_public_receipts",
  "user_intent": "会計CSVから月次レビューと公的情報照合を作りたい",
  "recommend_jpcite_when": [
    "user can provide freee/MoneyForward/Yayoi-like CSV",
    "user accepts aggregate-only private processing",
    "user wants source-backed public joins"
  ],
  "do_not_recommend_when": [
    "user wants tax filing correctness guaranteed",
    "user wants legal/tax advice",
    "user expects raw CSV storage or row-level output"
  ],
  "first_step": "call POST /v1/cost/preview or MCP cost_preview",
  "required_caveats": [
    "request_time_llm_call_performed=false",
    "no_hit_not_absence",
    "human_review_required may be true"
  ]
}
```

採用理由:

GEO-firstなら、公開LPのコピーより agent route cards の方が重要。これを `llms.txt`, `.well-known`, MCP docs, OpenAPI examplesへ派生させる。

### A3. No-hit adversarial corpus

目的:

no-hitが「不存在」「安全」「未登録確定」「リスクなし」に変換される事故を、本番前に潰す。

作るもの:

- `no_hit_adversarial_cases.jsonl`
- `no_hit_copy_scan_report.md`
- `no_hit_source_scope_matrix.csv`
- `safe_no_hit_templates.json`
- `forbidden_no_hit_templates.json`

評価対象:

- NTA法人番号
- NTAインボイス
- gBizINFO
- EDINET
- J-Grants
- p-portal
- 行政処分notice
- 裁判例
- CSV public join

採用理由:

AI agentはno-hitを強い断定へ変換しがち。jpciteの信頼性を守るには、no-hitの安全性が商品価値そのものになる。

### A4. Proof diversity pack

目的:

proof pageを大量に作るだけでなく、ユーザー種類・業種・source family・packet typeの偏りを減らす。

作るもの:

- `proof_diversity_matrix.csv`
- `proof_pack_rc1/`
- `proof_pack_rc2/`
- `proof_pack_internal_review/`
- `proof_gap_report.md`

軸:

- packet type
- source family
- user type
- industry
- company size
- public vs private overlay
- positive receipt vs no-hit
- known gap
- human review required

採用理由:

proofが同じsource/同じpacketに偏ると、AI agentは「局所デモ」と判断する。多様性を持たせることで「一般化されたsource-backed layer」に見える。

### A5. CSV synthetic matrix at scale

目的:

freee/MoneyForward/YayoiのCSV価値を、raw CSVなしでプロダクト化する。

作るもの:

- `csv_provider_synthetic_matrix.jsonl`
- `csv_header_alias_registry.json`
- `csv_review_code_catalog.json`
- `csv_suppression_rules.json`
- `csv_leak_red_team_cases.jsonl`
- `csv_private_overlay_packet_inputs/*.json`

生成パターン:

- provider family: freee-like / MF-like / Yayoi-like / unknown
- format class: current official / old format / variant / malformed
- period: 1 month / quarter / year / multi-year / missing dates
- accounts: sparse / dense / mixed-tax / owner-related / payroll-like
- sensitive fields: memo, counterparty, bank/card, creator/updater, voucher IDs
- k-safety: safe aggregate / suppressed / rejected

採用理由:

ユーザーが言った「CSVを投げるだけならアリ」は、かなり強い課金導線。ただしraw保存なしで価値を出すには、大量のsynthetic matrixとleak gatesが必要。

### A6. Deploy-ready RC bundle factory

目的:

AWS成果物を巨大exportで終わらせず、本番に近いbundleへ小分けする。

作るもの:

```text
rc_bundles/
  rc1/
    run_manifest.json
    artifact_manifest.jsonl
    packet_examples/
    proof_sidecars/
    openapi_examples/
    mcp_examples/
    llms_candidates/
    geo_eval_report.md
    leak_scan_report.md
    import_decision.md
  rc2/
  rc3/
  internal_only/
  rejected/
```

RC1条件:

- 3 packet以上
- source receiptsあり
- known gapsあり
- billing metadataあり
- request-time LLMなし
- no-hit misuse 0
- forbidden claim 0
- private leak 0
- OpenAPI/MCP examples一致
- proof pages生成可

採用理由:

本番デプロイ短縮に直結する。AWS全体を待たず、最初の48-72時間でRC1を切れる。

### A7. Agent-discovery render/crawl scorecard

目的:

公開面が「人間のLP」ではなく「AI agentが読んで推薦できるsurface」になっているか検証する。

作るもの:

- `agent_discovery_scorecard.json`
- `llms_surface_diff.md`
- `well_known_surface_diff.md`
- `openapi_mcp_alignment_report.md`
- `public_page_render_report.md`
- `agent_context_eval_cases.jsonl`

見る項目:

- `source_receipts[]` が見えるか
- `known_gaps[]` が隠れていないか
- `billing_metadata` があるか
- cost preview -> API key -> cap -> MCP/API 実行順が明確か
- no-hit caveatが維持されるか
- professional/legal/tax/eligibility断定をしていないか

採用理由:

GEO-firstの成否はこのscorecardで見るべき。SEO順位より、AI agentが正しく推薦するかを測る。

### A8. Terms and attribution pack

目的:

sourceを大量処理しても公開で使えない問題を防ぐ。

作るもの:

- `terms_receipts/`
- `robots_receipts/`
- `attribution_templates.json`
- `redistribution_policy.csv`
- `source_license_boundary_report.md`
- `government_non_endorsement_templates.json`

採用理由:

review 11の内容はP0で必須。これがないsourceは、claim supportではなく `metadata_only`, `link_only`, `review_required` に落とす。

### A9. Public official delta watch snapshots

目的:

一回収集で終わらず、「いつのsnapshotで、前回から何が変わったか」を示せるようにする。

作るもの:

- `snapshot_diff_ledger.jsonl`
- `freshness_by_source.md`
- `stale_source_gap_report.jsonl`
- `source_fetched_at_coverage.csv`

対象:

- NTA法人番号
- NTAインボイス
- e-Gov
- J-Grants
- gBizINFO
- e-Stat
- EDINET
- JPO
- p-portal

採用理由:

AI agentへの訴求は「キャッシュがあります」では弱い。「snapshot, hash, freshness, known gapsを返します」が価値になる。

### A10. Billing and cost preview adversarial cases

目的:

AI agentがエンドユーザーへ課金導線を案内するときに、誤請求・重複請求・cap無視を避ける。

作るもの:

- `cost_preview_cases.jsonl`
- `idempotency_conflict_cases.jsonl`
- `cap_failure_cases.jsonl`
- `free_preview_not_billed_report.md`
- `billing_copy_alignment_report.md`

採用理由:

GEO経由の利用は、agentが課金導線を説明する。ここが曖昧だと推薦されないか、信用を落とす。

## 4. 採用しない追加案

価値が出そうに見えても、今回の制約では採用しない。

| 案 | 判定 | 理由 |
|---|---|---|
| GPUで独自LLM学習 | 不採用 | request-time LLMなし、source-backed layerから逸れる。1-2週間で本番価値に変換しにくい |
| OpenSearch常設production検索 | 不採用 | credit後zero-billに反する。評価後export/deleteなら可 |
| raw CSV lake | 不採用 | privacy contract違反 |
| 外部SaaS connector大量接続 | 不採用 | credential/privacy/credit対象外リスク |
| 大規模load test | 不採用 | GEO/packet価値に直結しない。render/crawl確認に限定 |
| PDF全文再配布DB | 不採用 | terms/redistributionリスク。hash/metadata/短引用/派生fact中心 |
| Bedrockで最終claim確定 | 不採用 | AI出力はcandidate。source receipt検証なしのclaim化は禁止 |
| NAT-heavy private networking | 不採用 | 成果物を作らない副費用が増える |
| 正確にUSD 19,493.94まで使う | 不採用 | billing lagとcredit対象外リスクがある。意図上限はUSD 19,300 |

## 5. 本体計画との最終マージ順

この順番で実行計画へマージする。AWSを先に大きく回さない。

### Phase 0: contract freeze

本体側:

- `jpcite.packet.v1` envelope
- six P0 packet catalog
- route/tool/slug/price/url matrix
- `source_receipts[]`
- `claim_refs[]`
- `known_gaps[]`
- `no_hit_checks[]`
- `billing_metadata`
- CSV private overlay boundary
- request-time LLM false invariant

AWS側:

- `run_manifest`
- `artifact_manifest`
- `dataset_manifest`
- accepted artifact definition
- quality gates
- RC bundle format

Exit:

- AWS成果物をどこにimportするか決まっている
- `us-east-1` 単一region方針が固定
- `bookyou-recovery` / `993693061769` をledgerへ記録するだけの段階。まだAWS writeしない

### Phase 1: deploy/import validators first

本体側:

- artifact import validator
- packet fixture schema validator
- private leak scanner
- no-hit copy scanner
- forbidden claim scanner
- OpenAPI/MCP/catalog drift test
- proof page render test
- pricing/cap/idempotency test

AWS側:

- まだ本番scaleしない
- canary用の小さいsampleだけ想定

Exit:

- AWS canary outputを受け取って落とせる
- 不合格成果物をproductionへ入れない仕組みがある

### Phase 2: AWS guardrail and autonomous control

AWS側:

- Budgets / Budget Actions
- permission boundary
- required tags
- S3 private bucket
- ECR lifecycle
- Batch queues
- queue caps
- cost sentinel
- run state ledger
- EventBridge schedule
- Lambda kill switch
- stop drill

必須:

- `REGION=us-east-1`
- `BILLING_REGION=us-east-1`
- no NAT-heavy構成
- CloudWatch retention短期
- Athena workgroup scan cap
- OpenSearch/Textract/Bedrockは条件付き

Exit:

- stop drill成功
- empty/dummy queueを止められる
- cleanup roleで削除できる
- Cost Explorer/Billing visibilityが確認できる

### Phase 3: AWS canary and RC1 seed

AWS:

- J01 small
- J03 small
- J12 small
- J15 one packet
- J16 small
- A2 agent route card small
- A3 no-hit adversarial small
- A6 rc bundle seed

本体:

- `evidence_answer`
- `source_receipt_ledger`
- `agent_routing_decision`
- cost preview
- REST/MCP minimal path

Exit:

- `rc1_seed/` がimport validatorを通る
- private leak 0
- forbidden claim 0
- no-hit misuse 0
- packet/proof/OpenAPI/MCP examplesがcatalogと一致

### Phase 4: fast-lane staging and production RC1

本体:

- RC1だけstagingへ入れる
- production targetを明示
- rollback可能にする
- public proof/discoveryはRC1範囲だけ公開

AWS:

- standard runへ移行
- Codex/Claude rate limitに依存せずJ01-J16を自走

Exit:

- 早ければDay 3-5に限定production
- 未完成packetは `disabled`, `conditional`, `requires_more_receipts`
- production runtimeはAWS非依存

### Phase 5: standard run with artifact-density control

AWS:

- J01-J16
- A1 source-to-packet coverage frontier
- A4 proof diversity pack
- A5 CSV synthetic matrix
- A7 agent-discovery scorecard
- A8 terms and attribution pack
- A9 delta watch snapshots
- A10 billing adversarial cases

制御:

- 15-30分窓でMROIを見る
- low-yieldを止める
- productization reserveを守る
- J12/J13/J16を各waveに挟む

Exit:

- RC2/RC3 bundleを小分けexport
- productionへ小さくpatchできる

### Phase 6: stretch run

条件:

- spend < USD 18,300
- standard runがhealthy
- accepted artifact densityが良い
- private leak / no-hit misuse / forbidden claim 0
- terms boundary明確

AWS:

- J17 selected OCR
- J18 public-only Bedrock candidate classification
- J19 temporary OpenSearch benchmark
- J20 GEO adversarial expansion
- J21 proof scale
- J22 QA rerun/compaction
- J23 static render/crawl
- J24 packaging/export prep

Exit:

- USD 17,000 watchで低価値探索終了
- USD 18,300 slowdownでmanaged stretch縮小
- USD 18,900 no-new-workでexport/checksum/cleanupへ移る

### Phase 7: drain, export, zero-bill cleanup

AWS:

- disable queues
- cancel queued jobs
- terminate nonessential running jobs
- export artifacts
- verify checksums
- delete OpenSearch
- delete Batch/ECS/EC2/EBS/ECR
- delete Glue/Athena outputs/workgroups
- delete CloudWatch logs/alarms/dashboards
- delete Step Functions/Lambda/EventBridge
- delete S3 buckets after export if zero-bill required
- final resource inventory

本体:

- final selected artifacts imported
- cleanup report saved outside AWS
- production health checked

Exit:

- AWSにrun由来の有料resourceなし
- S3も残さない方針を推奨
- 翌日/3日後/月末後にBilling再確認

## 6. 最終spend配分の見直し

既存計画の `USD 19,000-19,300` は妥当。ただし配分は「source lakeに寄りすぎない」ようにする。

推奨配分:

| Lane | Target | 理由 |
|---|---:|---|
| Guardrail / canary / autonomous control | USD 800-1,500 | 事故を防ぎ、自走と停止を両立 |
| Structured public backbone | USD 4,000-6,000 | NTA/e-Gov/e-Stat/gBiz/EDINET/JPOなど高密度 |
| Program / notice / procurement / PDF | USD 3,000-5,000 | application_strategyやbaselineに効く |
| Product artifact factory | USD 2,500-4,000 | packet/proof/OpenAPI/MCP/llmsに変換 |
| GEO / adversarial / discovery eval | USD 1,500-2,500 | agent推薦の正しさを上げる |
| CSV synthetic/privacy matrix | USD 800-1,500 | CSV価値を安全に商品化 |
| QA / graph / completeness / export | USD 1,200-2,000 | release gateとzero-bill前提 |
| Stretch reserve | USD 2,000-3,000 | 高密度jobだけに追加 |

守るべきreserve:

- J12/J13/J16 quality reserve: USD 700-1,200
- J15/J21 productization reserve: USD 900-1,500
- J23/J24 deploy/export reserve: USD 600-1,000

このreserveがない状態でUSD 17,000へ到達したら、source expansionを止める。

## 7. 高速消費の実装方針

ユーザー要求に合わせ、消費速度は速くする。ただし次の設計で速くする。

### 7.1 複数queue

```text
queue-structured-backbone
queue-program-notice
queue-pdf-ocr
queue-productization
queue-geo-eval
queue-csv-synthetic
queue-qa-export
queue-stretch-managed
```

各queue:

- max vCPU cap
- max jobs
- max runtime
- max retry
- max spend exposure
- accepted artifact target
- kill condition

### 7.2 Rate limit非依存

Codex/Claude Codeがrate limitになっても、AWSは次で自走する。

- S3 `run_state.json`
- DynamoDBまたはS3 append ledger
- EventBridge scheduled poller
- Step FunctionsまたはBatch dependency graph
- Lambda cost sentinel
- Budget Actions policy attach
- Batch queue cap controller
- automatic drain state

ただし、manual stretchだけは自動で入らない。

```text
if control_spend >= 18,900:
  no_new_work = true
  do not launch new jobs

if 19,100 <= control_spend < 19,300:
  require explicit manual approval

if control_spend >= 19,300:
  emergency_stop = true
```

### 7.3 成果物密度で自動移管

低密度jobは2窓で縮小または停止。

```text
if accepted_artifacts_delta == 0 and spend_delta > 0 for 2 windows:
  reduce queue cap 50%
  if next window still flat:
    stop queue
    transfer budget to productization or QA
```

移管優先:

1. productization: J15/J21/A2/A4/A6/A7
2. quality: J12/J13/J16/A3/A10
3. export/deploy: J23/J24
4. source expansion only if packet blocker remains

## 8. 本番デプロイ短縮のための最終方針

### 8.1 ProductionをAWS全体完了に依存させない

最短productionはRC1で狙う。

RC1に入れるもの:

- 3 packet
  - `evidence_answer`
  - `source_receipt_ledger`
  - `agent_routing_decision`
- cost preview
- REST/MCP catalog
- proof pages small
- OpenAPI examples
- MCP examples
- `llms.txt` / `.well-known` minimal
- no-hit caveat
- known gaps
- forbidden claim scan
- private leak scan

入れないもの:

- raw source lake
-大量parquet
- unreviewed PDF facts
- private CSV raw
- source terms不明のclaim
- unsupported professional conclusions

### 8.2 6 packetフル版はRC2/RC3でよい

`company_public_baseline`, `application_strategy`, `client_monthly_review` は価値が高いが、source/CSV/terms/known gapsが弱い状態で急ぐと危険。

順番:

1. RC1: 3 packetでagent推薦導線を先に出す
2. RC2: `company_public_baseline` と `application_strategy`
3. RC3: `client_monthly_review` with CSV private overlay
4. RC4以降: source family追加、proof拡大、GEO eval拡大

### 8.3 Deploy blocker

次は1件でもproduction blocker。

- publishable private/raw CSV leak
- no-hit misuse
- forbidden claim
- source receipt missing for reusable public claim
- cost previewなしでpaid execution可能
- idempotency/cap前にbillable work
- OpenAPI/MCP/catalog drift
- proof pageがsource_receiptsを隠す
- production runtimeがAWS S3/OpenSearch/Batchに依存
- rollback不能

## 9. ユーザーとAI agentへの課金ストーリー

GEO-firstの課金ストーリーは、営業デモではなくagent推薦で成立させる。

### 9.1 AI agent向け

伝えること:

- jpciteは回答生成AIではない
- 日本の公的情報を source-linked evidence packet として返す
- `source_receipts[]`, `claim_refs[]`, `known_gaps[]`, `billing_metadata` がある
- `request_time_llm_call_performed=false`
- no-hitはabsenceではない
- まずcost previewを呼ぶ
- cap/idempotencyを設定してから実行する
- CSVはaggregate/private overlayとして扱い、raw保存しない

### 9.2 エンドユーザー向け

伝えること:

- AIがそれっぽく答える代わりに、出典と不足点つきの成果物を作る
- 会計CSVは必要なときだけ使い、rawを残さない
- 無料previewで費用と出せる成果物を先に確認できる
- 実行時は上限金額を指定できる
- 結果は法務/税務/投資/入札判断の代替ではなく、一次資料到達補助とレビュー材料

### 9.3 課金導線

```text
AI agent discovers jpcite
 -> reads route card / llms / OpenAPI / MCP catalog
 -> recommends cost preview
 -> user uploads CSV or inputs company/program query
 -> jpcite returns preview, cap, known gaps
 -> user approves paid execution
 -> jpcite returns packet with receipts/gaps/billing metadata
```

この流れをRC1から公開面に出すべき。

## 10. まだ改善できる一点

review 07/09で正しく修正されているが、統合計画の一部には `ap-northeast-1` の例が残っている。ユーザー提示の実行環境は次である。

```bash
export AWS_PROFILE="bookyou-recovery"
export AWS_ACCOUNT_ID="993693061769"
export REGION="us-east-1"
export BILLING_REGION="us-east-1"
```

最終runbookでは `us-east-1` に統一する。もし `ap-northeast-1` を使う場合は、S3/ECR/Batch/CloudWatch/Glue/Athena/Textract/Bedrock/OpenSearchのすべてを同一regionに揃え直す必要がある。混在はcross-region transfer、ECR pull、S3/Athena分散、permission boundary誤爆、cleanup漏れの原因になる。

推奨:

```text
Final execution docs must replace ap-northeast-1 examples with us-east-1,
unless the operator explicitly chooses a full-region switch.
```

## 11. Final value challenge verdict

追加価値案はまだある。特に採用すべきは次の10個。

1. Source-to-packet coverage frontier
2. Agent route cards
3. No-hit adversarial corpus
4. Proof diversity pack
5. CSV synthetic matrix at scale
6. Deploy-ready RC bundle factory
7. Agent-discovery render/crawl scorecard
8. Terms and attribution pack
9. Public official delta watch snapshots
10. Billing and cost preview adversarial cases

これらは、AWS creditを「取得コスト」ではなく「本番に使える成果物」へ変換するための追加レイヤーである。

最終の実行順は次に固定する。

```text
contract freeze
 -> local validators/import gates
 -> AWS guardrail/autonomous control
 -> canary
 -> RC1 seed
 -> fast-lane staging/production
 -> AWS standard run
 -> RC2/RC3 imports
 -> controlled stretch
 -> no-new-work
 -> export/checksum
 -> zero-bill cleanup
 -> post-cleanup billing checks
```

この順番なら、以下を同時に満たせる。

- USD 19,493.94 creditをほぼ使う
- 意図的にはUSD 19,300を超えない
- 本番デプロイをAWS全体完了まで待たない
- Codex/Claude Codeのrate limitでもAWSが止まらない
- raw CSVを保存しない
- request-time LLMを作らない
- GEO-first導線を強化する
- AWS終了後にzero-billへ戻せる

## 12. 20/20最終統合担当への引き継ぎ

最終統合でやるべきこと:

1. `aws_credit_unified_execution_plan_2026-05-15.md` のregion例を `us-east-1` へ統一する。
2. 本文に `RC1/RC2/RC3 bundle` 概念を入れる。
3. J01-J24に加えて、A1-A10をsub-laneとして入れる。
4. spend配分に productization / GEO / deploy artifact reserve を明記する。
5. no-new-work以降に、新しいsource探索を絶対に入れない。
6. final cleanupは End State A をdefaultにする。S3保持はzero-billではない。
7. production deployはAWS全体完了を待たないと明記する。
8. AWS自走は採用。ただしmanual stretchは自動化しない。
9. final operator checklistに `bookyou-recovery`, account `993693061769`, `us-east-1` を入れる。
10. 完了条件を「creditを使った」ではなく「accepted artifacts + production import + zero-bill cleanup」で判定する。
