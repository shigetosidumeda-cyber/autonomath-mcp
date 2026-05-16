# AWS credit review 09: queue sizing / pacing

作成日: 2026-05-15  
レビュー枠: AWSクレジット統合計画 追加20エージェントレビュー 9/20  
担当: キュー設計、ペーシング、並列度、Spot比率、リトライ、ジョブ優先度  
AWS前提: CLI profile `bookyou-recovery` / Account `993693061769` / default region `us-east-1`  
対象クレジット: USD 19,493.94  
状態: Markdown追加レビューのみ。AWS CLI/API実行、AWSリソース作成、ジョブ投入はしない。

## 0. 結論

このAWS credit runは、最初から大きく回すのではなく、**成果物契約を固定してから、source receiptの生産量に応じて段階的に並列度を上げる**べきである。

最終方針:

1. Workload regionは、ユーザー提示のdefaultに合わせて原則 `us-east-1` に固定する。S3/ECR/Batch/CloudWatch/Glue/Athena/Textract/Bedrock/OpenSearchを分散させない。
2. J01-J04を最初の本線にして、会社同定・インボイス・法令・統計のreceipt backboneを作る。
3. J05-J11は、source条件とparse成功率が確認できたものから並列投入する。
4. J12/J13/J16は最後だけではなく、各waveの後に必ず挟む。receipt completeness、claim conflict、forbidden/no-hit misuseを早く検出する。
5. J15のpacket/proof fixtureは、J01-J13の出力が揃い始めた時点で小さく先行生成し、P0実装計画へ戻す。
6. J17-J24 stretchは、USD 17,000到達前に準備だけ終え、実行はaccepted artifact yieldが良い場合だけにする。
7. USD 18,900以降は新しい価値探索をしない。export、checksum、最終report、cleanupに集中する。

重要な制約:

- AWS Budgetsはhard capではない。キュー無効化、ジョブcancel/terminate、compute cap縮小が実際のブレーキである。
- Cost Explorer、Budgets、tag反映は遅れる。`control_spend` は見えている費用だけでなく、running/queuedの最大追加露出を足して判断する。
- 「クレジットを使い切る」ためのCPU burn、広いload test、長期OpenSearch、NAT-heavy構成は禁止する。
- private CSV、raw会計row、顧客固有データはAWS成果物、ログ、index、promptへ入れない。

## 1. 本体計画とのマージ順

キュー設計は単独のAWS運用計画ではなく、本体P0計画の実装順へ戻す。

| 実行順 | 本体P0側 | AWS側 | 完了条件 |
|---:|---|---|---|
| 1 | P0-E1 packet contract / catalog freeze | J01のsource profile contract、J12のreceipt completeness schemaを小さく生成 | envelope、packet registry、receipt/gap enum、billing metadataが固定される |
| 2 | P0-E2 source receipts / claim refs / known gaps | J01-J04を先行実行 | identity、invoice、law、statのreceipt backboneができる |
| 3 | P0-E5 packet composers | J05/J07/J10/J11の一部とJ15 small fixture | `evidence_answer`、`company_public_baseline`、`source_receipt_ledger`のfixtureができる |
| 4 | P0-E4 CSV privacy / private overlay | J14 synthetic/header-only/privacy leak matrix | CSVはraw保存なし、derived factsだけでpacketへ入る |
| 5 | P0-E6 REST / P0-E7 MCP | J15のexample payload、error/no-hit/cap examples | API/MCPがagentに推薦しやすい形になる |
| 6 | P0-E8 proof/discovery | J15/J21 proof pages、llms/.well-known candidates | GEO-first discovery surfaceが生成される |
| 7 | P0-E9 release gates | J12/J13/J16/J20/J23/J24 | forbidden claim 0、no-hit misuse 0、checksum/export/cleanup ledgerあり |

この順序により、AWSで作った成果物が単なるsource lakeで終わらず、jpcite本体の「AIエージェントが推薦できる成果物」へ接続される。

## 2. Region and account assumptions

ユーザー提示値をこのレビューの前提にする。

```text
AWS CLI profile: bookyou-recovery
AWS Account ID: 993693061769
Region default: us-east-1
```

実行時の扱い:

- `us-east-1` をworkload regionの標準とする。
- Billing/Cost Explorer/Budgetsのcontrol planeも `us-east-1` 前提で確認する。
- 日本向けsourceだからといって、S3だけ東京、BatchだけVirginiaのような分散はしない。
- どうしても別regionのBedrock model/Textract機能等が必要な場合は、cross-region sub-runとして別承認にする。承認がなければ、そのstretch jobはskipする。
- ECR image、Batch compute、S3 artifact bucket、CloudWatch logs、Athena result bucket、Glue catalogは同一regionに置く。

## 3. Queue topology

AWS Batchは、ジョブの性質ごとにqueueを分ける。priorityはAWS Batch schedulerがqueue評価順に使う値であり、同一compute environmentを共有する場合は高priority queueが先に評価される。

| Queue | Priority | 主用途 | 対象job | Compute | 初期cap | 最大cap | Spot比率 | 停止線での扱い |
|---|---:|---|---|---|---:|---:|---:|---|
| `jpcite-control-q` | 1000 | inventory、manifest、stop/drain補助、軽いaudit | J12/J24の小粒、ledger | Fargate/On-Demand small | 4 vCPU | 16 vCPU | 0-50% | 最後まで残すが低cap |
| `jpcite-receipt-backbone-q` | 900 | high-trust receipt backbone | J01-J04 | EC2 Spot + small On-Demand fallback | 32 vCPU | 192 vCPU | 80-90% | USD 18,300で新規shard停止、near-completeだけ |
| `jpcite-source-expand-q` | 800 | public program/business/procurement/notice source | J05/J07/J08/J09/J10/J11 | EC2 Spot | 48 vCPU | 256 vCPU | 90-95% | USD 17,000で低yield source停止 |
| `jpcite-pdf-ocr-q` | 700 | PDF extraction、Textract feeder、CPU parser | J06/J17 | EC2 Spot + managed Textract caps | 32 vCPU | 160 vCPU | 85-95% | USD 18,300で拡張停止 |
| `jpcite-qa-graph-q` | 650 | completeness、dedupe、conflict、Athena QA | J12/J13/J22 | EC2 Spot / Athena limited | 16 vCPU | 128 vCPU | 80-90% | 停止線ごとにむしろ優先。ただしscan上限あり |
| `jpcite-product-artifact-q` | 600 | packet fixtures、proof pages、GEO eval | J15/J16/J20/J21/J23 | Fargate Spot / EC2 Spot / short On-Demand | 16 vCPU | 128 vCPU | 70-90% | USD 18,900以降はfinal/exportに限定 |
| `jpcite-stretch-q` | 300 | optional stretch only | J18/J19/J20/J21/J22/J23 | service-specific | 0 vCPU | manual | 70-95% | default disabled。手動承認時だけ |
| `jpcite-rerun-low-q` | 100 | low-priority rerun/backfill | failed low-value shards | EC2 Spot only | 0 vCPU | 64 vCPU | 95-100% | USD 17,000でdisabled |

設計意図:

- control/drainのqueueを最優先にする。高価なcompute queueが詰まっても、停止・棚卸し・exportを動かせるようにする。
- J12/J13/J16を低優先度にしない。品質gateが遅れると、費用だけ先に燃える。
- stretch queueは初期状態でdisabledにする。USD 18,900以降に誤投入しないためである。

## 4. Compute environment sizing

推奨compute environment:

| Compute environment | 用途 | Allocation | Min | Desired | Max | Notes |
|---|---|---|---:|---:|---:|---|
| `jpcite-spot-cpu-ce` | parse、join、normalization、proof generation | Spot price/capacity optimized | 0 | 0 | 512 vCPU | default worker。interrupt前提でcheckpoint必須 |
| `jpcite-ondemand-small-ce` | control、drain、near-complete finalization | On-Demand | 0 | 0 | 32 vCPU | Spot interruptionで最後が終わらない時の保険 |
| `jpcite-fargate-spot-short-ce` | short stateless tasks | Fargate Spot | 0 | 0 | 128 vCPU | small JSON/manifest/proof jobs向き |
| `jpcite-service-capped` | Textract/Bedrock/OpenSearch/Athena | service quota/budget controlled | n/a | n/a | per-job cap | Batch capでは止まらないので別ledgerで管理 |

最大capの考え方:

- Smoke runでは全体32 vCPU以下。
- Standard run開始時は全体128-192 vCPU。
- accepted artifact yieldが良く、failure/retry/untagged/private leakが問題ない時だけ256-384 vCPUへ上げる。
- 512 vCPUは、J01-J13が安定し、J15/J16の評価も通っている場合の短時間burstに限定する。
- USD 18,300到達時点で全体capを128 vCPU以下へ戻す。
- USD 18,900到達時点で新規queue submissionを止め、control/drain以外は0へ落とす。

Spot比率:

| Workload | Spot比率 | On-Demandを混ぜる理由 |
|---|---:|---|
| deterministic fetch/parse | 80-95% | 429/timeout時の小粒control、manifest作成 |
| CPU-heavy normalization/join | 90-95% | shard checkpointがあるためSpot向き |
| PDF/OCR feeder | 85-95% | OCRはservice cap側が本体。feederはSpotでよい |
| QA/graph | 80-90% | final report生成は中断させたくない |
| packet/proof/GEO | 70-90% | 最終fixtureだけOn-Demand smallで完了保証 |
| drain/export/checksum | 0-50% | 最後は速度より確実な完了と停止が重要 |

## 5. J01-J24 execution order

### Wave 0: Preflight and contract freeze

実行しないと先へ進めない項目:

- packet envelope、receipt fields、known gap enum、billing metadata、privacy boundaryを固定する。
- source familyごとのaccepted artifact definitionを作る。
- output prefix、manifest schema、run ledger schema、cost ledger schemaを固定する。
- stop drillを先に行う。

AWS spend target: USD 0-50  
許可: read-only確認、ローカル生成、空のmanifest validation  
禁止: source全量取得、OCR、Bedrock、OpenSearch

### Wave 1: Smoke run

対象:

- J01 small source profile sweep
- J02またはJ03の小さいreceipt shape test
- J12 receipt completeness audit small
- J15 one packet fixture
- J16 forbidden/no-hit scan small

AWS spend target: USD 100-300  
max vCPU: 32  
成功条件:

- S3 output prefixにmanifest、success marker、checksumが出る。
- `source_receipts.jsonl`、`claim_refs.jsonl`、`known_gaps.jsonl` のshapeがP0 contractと一致する。
- private/raw CSVがどこにも出ない。
- no-hitがabsence/safe/eligibleへ変換されない。
- stop scriptまたはqueue disable/cancel手順が機能する。

失敗したらStandard runへ進まない。

### Wave 2: P0-A receipt backbone

対象:

- J01 Official source profile sweep
- J02 NTA法人番号 mirror/diff
- J03 NTA invoice registrants/no-hit
- J04 e-Gov law snapshot
- J11 e-Stat regional statistics enrichmentのcore subset
- J12 completeness audit after each family

AWS spend target: cumulative USD 2,500-4,500  
max vCPU: 128-192  
優先順位:

1. J01
2. J02
3. J03
4. J04
5. J11 core
6. J12

理由:

- ここがcompany/public/legal/stat backboneになる。
- 後続のPDF/補助金/調達/行政処分は、このbackboneにjoinして初めてpacket価値が出る。

### Wave 3: P0-B/P0-C source expansion

対象:

- J05 J-Grants/public program acquisition
- J07 gBizINFO public business signal join
- J08 EDINET metadata snapshot
- J09 procurement/tender acquisition
- J10 enforcement/sanction/public notice sweep
- J06 ministry/local PDF extractionのCPU/text-layer first
- J12/J13 after each source family

AWS spend target: cumulative USD 7,000-11,000  
max vCPU: 256-384  
優先順位:

1. J05, J07
2. J10, J09
3. J06 CPU/text-layer only
4. J08
5. J13
6. J12 rerun

PDF/OCRはこのwaveでは広げすぎない。まずCPU/text-layer抽出、hash、metadata、known gapsを作り、Textract投入対象だけを絞る。

### Wave 4: Product artifact bridge

対象:

- J14 CSV private overlay safety analysis
- J15 packet/proof fixture materialization
- J16 GEO/no-hit/forbidden-claim evaluation
- J13 claim graph dedupe/conflict rerun

AWS spend target: cumulative USD 12,000-15,500  
max vCPU: 192-256  
優先順位:

1. J14 leak/privacy/synthetic fixture
2. J15 six P0 packet fixtures
3. J16 no-hit/forbidden/GEO base eval
4. J13 conflict/dedupe rerun

このwaveで、AWS成果物を本体P0実装へ戻せる形にする。

必須出力:

- `packet_examples/evidence_answer.json`
- `packet_examples/company_public_baseline.json`
- `packet_examples/application_strategy.json`
- `packet_examples/source_receipt_ledger.json`
- `packet_examples/client_monthly_review.json`
- `packet_examples/agent_routing_decision.json`
- CSV privacy leak scan report
- no-hit misuse report
- forbidden-claim report

### Wave 5: Controlled stretch

対象:

- J17 Local government PDF OCR expansion
- J18 Public-only Bedrock batch classification
- J19 Temporary OpenSearch retrieval benchmark
- J20 GEO adversarial eval expansion
- J21 Proof page scale generation
- J22 Athena/Glue QA reruns and compaction
- J23 Static site crawl/render/load check
- J24 Final artifact packaging/checksum/export

AWS spend target: cumulative USD 17,000-18,900 before manual stretch  
max vCPU: 128-256  
初期状態: disabled

解放条件:

- accepted artifact countが2時間以上継続して増えている。
- failure rate < 10%。
- retry rate < 15%。
- private leak 0。
- no-hit misuse 0。
- forbidden claim 0。
- untagged spend説明済み。
- paid exposure 0または説明済み。
- operatorが30分以内にstopできる。

実行優先:

1. J24 packaging/checksum/export preparation
2. J21 proof page scale if J15 accepted
3. J20 GEO adversarial eval if J16 base passes
4. J17 OCR expansion only if J06 accepted candidate rate is good
5. J22 compaction if Parquet scan cost is high
6. J19 OpenSearch only for defined retrieval benchmark
7. J18 Bedrock only for public-only closed-schema classification

## 6. Daily pacing plan

2週間で使う標準ペース。Cost Explorer lagを前提に、visible spendではなく `control_spend` で判定する。

```text
control_spend = max(
  visible Cost Explorer gross usage,
  budget actual gross usage,
  operator ledger confirmed usage,
  previous confirmed usage + running_max_exposure + queued_max_exposure + service_cap_exposure
)
```

| Day | Cumulative target | Cumulative hard behavior | Main work | Queue cap |
|---:|---:|---|---|---:|
| 0 | USD 0-50 | spend-heavy禁止 | preflight、contract、stop drill | 0-16 vCPU |
| 1 | USD 100-300 | smoke以外禁止 | Wave 1 | 32 vCPU |
| 2 | USD 2,000-3,000 | 不安定なら停止 | J01-J04 core | 128 vCPU |
| 3 | USD 4,500-6,000 | failure/retry次第でcap維持 | J02/J03/J04/J11拡張 | 192 vCPU |
| 4 | USD 7,500-9,500 | output stagnationでsource停止 | J05/J07/J10/J09 | 256 vCPU |
| 5 | USD 10,500-12,500 | PDFはCPU first | J06/J13/J12 | 256-384 vCPU |
| 6 | USD 13,000-15,000 | product bridge優先 | J14/J15/J16 | 192-256 vCPU |
| 7 | USD 15,500-16,800 | Watch直前準備 | J15/J16/J13、stretch準備 | 192 vCPU |
| 8 | USD 17,000-17,800 | Watch発動 | high-yieldだけ継続 | 128-192 vCPU |
| 9 | USD 18,000-18,500 | Slowdown発動 | OCR/OpenSearch/大join停止 | 64-128 vCPU |
| 10 | USD 18,700-18,900 | No-new-work準備 | J24/export/checksum | 32-64 vCPU |
| 11 | USD 18,900 | No-new-work | new compute禁止、drain | 0-32 vCPU |
| 12 | USD 18,900-19,100 | manual approval only | checksum、small final reports | controlのみ |
| 13 | USD 19,100-19,300 max | absolute safety近傍 | cleanup、resource inventory | 0 |
| 14 | no new spend | verification | billing/resource再確認 | 0 |

1週間へ圧縮する場合:

- Day 0-1を同日にまとめる。
- Day 2-3でJ01-J04を終える。
- Day 4でJ05/J07/J10/J06 CPU first。
- Day 5でJ14/J15/J16。
- Day 6でJ20/J21/J24だけstretch。
- Day 7はNo-new-work、export、cleanupに固定する。

圧縮時でも、USD 18,900以降に新規価値探索を始めない。

## 7. Stopline behavior

### USD 17,000 Watch

即時変更:

- `jpcite-rerun-low-q` disable。
- `jpcite-stretch-q` は引き続きdisabled。
- source familyごとのartifact/USDを比較し、下位25%を停止。
- J06/J17のPDF expansionは新規投入停止。既に高yieldのdocument classだけ継続。
- max vCPUを全体192以下へ戻す。

継続できるもの:

- J12/J13/J15/J16/J24。
- high-yieldなJ01-J05/J07/J10のnear-complete shard。

### USD 18,300 Slowdown

即時変更:

- OCR expansion、OpenSearch、Bedrock、広いAthena scan、大規模joinを停止。
- queued jobのうち未開始かつ低優先度のものをcancel。
- 全体max vCPUを128以下にする。
- On-Demand fallbackをfinalization以外に使わない。
- 新しいsource familyを開始しない。

継続できるもの:

- source receipt completenessの穴埋め。
- six packet fixtureの未完了分。
- no-hit/forbidden/privacy scan。
- final export/checksum準備。

### USD 18,900 No-new-work

即時変更:

- 新規submit停止。
- stretch queue disable。
- source/ocr/bedrock/opensearch/qa expansion停止。
- RUNNABLE/SUBMITTEDの低価値job cancel。
- running jobは、30分以内に有用成果物を吐けるものだけ完走許可。
- J24、cost ledger、cleanup ledger、checksum、exportへ移る。

許可:

- export、checksum、manifest aggregation。
- small final report rendering。
- cleanup readiness inventory。

禁止:

- 新規crawler。
- 新規OCR batch。
- 新規OpenSearch domain/index拡張。
- 新規Bedrock batch。
- 新規Athena full scan。
- 新規proof page大量生成。

### USD 19,100-19,300 Manual stretch

明示承認がある場合だけ実行する。

許可するstretch:

- J24 final packaging/checksum。
- J21/J20の小さい未完了report補完。
- receipt coverageの明確な穴を埋める短時間shard。

禁止するstretch:

- 消化目的のcompute。
- PDF全量OCR。
- model比較。
- OpenSearch常駐延長。
- 大規模Athena scan。

### USD 19,300 Absolute safety line

即時:

- 全job queue disable。
- queued job cancel。
- nonessential running job terminate。
- managed service expansion停止。
- resource inventoryとcleanupへ移る。

ここから先は、クレジット消化ではなく請求防止が目的になる。

## 8. Retry strategy

リトライは費用を倍化させるため、job typeごとに分ける。

| Failure class | 例 | Retry | Action |
|---|---|---:|---|
| transient network | timeout、5xx、connection reset | 2-3 | exponential backoff、same shard id、dedupe |
| rate limit | 429、robots/terms境界、API quota | 0-1 | source familyをpauseし、rateを下げる |
| forbidden/auth | 401/403、token invalid、申請不足 | 0 | fail fast、manual review |
| parser/schema | unexpected HTML、field missing | 0-1 | quarantineへ出してrule修正待ち |
| Spot interruption | host termination、capacity reclaim | 2-4 | checkpointから再開。idempotency必須 |
| container/image | image pull、missing dependency | 0-1 | queue停止、image修正まで再投入しない |
| private leak suspicion | raw CSV、personal data、secret | 0 | emergency stop lane、artifact隔離 |
| no-hit misuse / forbidden claim | absence/safety/eligible変換 | 0 | job family停止、contract修正 |
| managed service expensive retry | Textract/Bedrock/OpenSearch | 0-1 | duplicate input hashで二重投入禁止 |

AWS Batchのretry attemptsは最大10まで設定できるが、このrunでは高くしない。推奨:

- standard deterministic job: attempts 2
- Spot-heavy parse job: attempts 3
- idempotent CPU join: attempts 2
- final export/checksum: attempts 2 with On-Demand fallback
- Textract/Bedrock submitter: attempts 1 by default

全jobは以下を満たす。

- `run_id`
- `job_family`
- `shard_id`
- `input_manifest_hash`
- `output_prefix`
- `attempt`
- `idempotency_key`
- success marker
- checksum

既にsuccess markerがあるshardは再実行しない。partial outputは`attempt=<n>` prefixへ隔離し、promoteはmanifest aggregatorだけが行う。

## 9. Priority and dependency matrix

| Job | Priority | Depends on | Blocks | Run style | Stop sensitivity |
|---|---:|---|---|---|---|
| J01 | 950 | contract freeze | all source families | small then full | continue until Watch if healthy |
| J02 | 930 | J01 source profile | company joins | full snapshot/diff | high priority |
| J03 | 920 | J01 source profile | invoice/no-hit/CSV join | full snapshot/diff | high priority |
| J04 | 910 | J01 source profile | legal basis | snapshot/article shard | high priority |
| J11 | 850 | J01 | regional/stat context | selected tables first | stop low-value tables at Watch |
| J05 | 830 | J01/J04 partial | application strategy | API snapshot + extraction | stop low-yield at Watch |
| J07 | 820 | J02 | public business signals | join shard | stop if token/terms issue |
| J10 | 790 | J02/J01 | DD/risk screen/no-hit | source allowlist | stop if ambiguity high |
| J09 | 760 | J01 | procurement opportunity | metadata first | stop if terms unclear |
| J08 | 720 | J02 | EDINET bridge | metadata only | optional before Stretch |
| J06 | 700 | J01/J05/J10 target list | PDF facts | CPU first, OCR gated | stop at Slowdown |
| J12 | 980 | each wave output | release gate | recurring audit | always high priority |
| J13 | 860 | J02-J11 partial | claim graph quality | recurring | continue if it reduces risk |
| J14 | 880 | CSV contract, J02/J03 derived | privacy gate | synthetic/header-only | high priority |
| J15 | 875 | J02-J14 partial | product fixtures | iterative small-first | high priority after backbone |
| J16 | 970 | J15 partial | release decision | recurring eval | always high priority |
| J17 | 500 | J06 accepted yield | local PDF depth | gated stretch | stop at Slowdown |
| J18 | 480 | deduped public spans | review priority | manual stretch | stop on any hallucination |
| J19 | 450 | query set, public corpus | retrieval eval | 2-3 day max | delete after export |
| J20 | 620 | J16 base pass | GEO robustness | controlled stretch | useful until No-new-work |
| J21 | 610 | J15 accepted fixtures | proof scale | controlled stretch | useful until No-new-work |
| J22 | 640 | Parquet exists | QA/cost reduction | compaction rerun | useful if scan cost drops |
| J23 | 600 | public pages generated | render/load evidence | small crawl | final only |
| J24 | 990 | every accepted output | export/checksum/cleanup | final | highest priority near end |

J12/J16/J24は高priorityに置く。これらは「成果物を増やすjob」ではなく「成果物を使える状態にするjob」であり、遅らせると本体計画へ戻せない。

## 10. Artifact yield gates

キュー拡張は、費用ではなくaccepted artifact yieldで決める。

| Lane | Continue condition | Stop / reduce condition |
|---|---|---|
| source profile | required fields coverage >= 95% | license/terms unknownが増える |
| identity/invoice | exact ID receipts and no-hit checks pass | identity ambiguity unresolvedが増える |
| law/stat | version/freshness/unit metadataあり | stale/version gapが未説明 |
| grants/program | deadline/amount/eligibility候補がreceipt/gapへ分類される | application possibilityを断定する出力が出る |
| PDF extraction | accepted candidate rate >= 25% for OCR expansion | accepted < 15% or review queue overflow |
| business/procurement/notice | source scope and no-hit wordingが明確 | no-hitを「実績なし/処分なし」へ変換 |
| CSV privacy | leak 0、header/synthetic only | raw row/摘要/個人名が出る |
| packet fixtures | all public claims have receipt or known gap | unsupported claimが残る |
| GEO eval | forbidden claim 0 | unsafe recommendation or overclaim |
| proof pages | private leak 0、JSON-LD safe | raw intermediate or unreviewed candidate exposure |

2時間連続でcompute spendが増え、accepted artifactが増えないjob familyは停止する。

## 11. Operator cadence

JST運用で見る。

| Time | Check | Decision |
|---|---|---|
| 09:00 | previous day cost, paid exposure, untagged spend, resource inventory | day cap決定 |
| 11:00 | first wave output, failure/retry, source terms issues | cap増減 |
| 14:00 | control spend, queued/running exposure, accepted artifact yield | stretch可否 |
| 17:00 | service mix, logs, Athena scan, data transfer, NAT/Public IPv4 | night cap |
| 21:00 | unattended safety, queue depth, stop readiness | low-risk jobだけ残す |
| before sleep | no managed service left accidentally scaling | expensive lanes disabled |

operatorが30分以内に止められない時間帯:

- stretch queue disabled。
- OCR/Bedrock/OpenSearch disabled。
- max vCPUを昼の25%以下へ下げる。
- no new source family。
- control/drain/short idempotent jobsだけ許可。

## 12. Exposure ledger

毎回のcap変更前にledgerへ書く。

| Field | Meaning |
|---|---|
| `time_jst` | 判断時刻 |
| `account_id` | `993693061769` |
| `profile` | `bookyou-recovery` |
| `region` | `us-east-1` |
| `control_spend_usd` | CE/Budget/operator/running exposureの最大 |
| `paid_exposure_usd` | credit後のcash-like exposure |
| `line` | below_watch / watch / slowdown / no_new_work / stretch / absolute_stop |
| `queue_caps` | queueごとのmax vCPU |
| `running_max_exposure_usd` | running jobの最大追加見積 |
| `queued_max_exposure_usd` | queued jobの最大追加見積 |
| `service_cap_exposure_usd` | Textract/Bedrock/OpenSearch/Athena等 |
| `accepted_artifacts_delta` | 前回から増えたaccepted artifact |
| `failure_rate` | failed / finished |
| `retry_rate` | retry attempts / attempts |
| `private_leak_count` | 0必須 |
| `forbidden_claim_count` | 0必須 |
| `no_hit_misuse_count` | 0必須 |
| `decision` | scale_up / hold / reduce / stop / cleanup |
| `operator_note` | 判断理由 |

## 13. Specific job caps

標準runでの上限目安。

| Job | Initial cap | Expansion cap | Absolute cap before manual stretch | Notes |
|---|---:|---:|---:|---|
| J01 | USD 100 | USD 600 | USD 900 | source profileは高価にしない |
| J02 | USD 200 | USD 900 | USD 1,300 | identity spineなので優先 |
| J03 | USD 150 | USD 700 | USD 1,100 | no-hit safety付き |
| J04 | USD 150 | USD 800 | USD 1,200 | article/version shard |
| J05 | USD 300 | USD 1,600 | USD 2,300 | accepted requirementsが出る場合だけ |
| J06 | USD 250 | USD 2,000 | USD 3,200 | OCR前にCPU/text-layer |
| J07 | USD 200 | USD 1,000 | USD 1,600 | API/terms/token境界で止める |
| J08 | USD 100 | USD 700 | USD 1,100 | metadata bridge中心 |
| J09 | USD 150 | USD 1,000 | USD 1,700 | public notice metadata first |
| J10 | USD 200 | USD 1,100 | USD 1,800 | no-hit誤用に注意 |
| J11 | USD 100 | USD 600 | USD 1,000 | selected tables only |
| J12 | USD 100 | USD 400 | USD 800 | recurring gate |
| J13 | USD 150 | USD 700 | USD 1,200 | conflictを減らすなら継続 |
| J14 | USD 100 | USD 600 | USD 1,000 | synthetic/header-only |
| J15 | USD 200 | USD 1,200 | USD 2,000 | product価値に直結 |
| J16 | USD 100 | USD 600 | USD 1,000 | release gate |
| J17 | USD 0 | USD 1,200 | USD 2,000 | stretch gated |
| J18 | USD 0 | USD 700 | USD 1,400 | public-only, closed schema |
| J19 | USD 0 | USD 700 | USD 1,200 | 2-3 days max, delete |
| J20 | USD 0 | USD 500 | USD 900 | GEO robustness |
| J21 | USD 0 | USD 600 | USD 1,000 | proof scale |
| J22 | USD 0 | USD 400 | USD 700 | compaction/QA |
| J23 | USD 0 | USD 300 | USD 700 | static validation |
| J24 | USD 100 | USD 300 | USD 600 | final packaging/export |

この表はbudgetではなくjob-level guardrailである。全体stoplineの方が常に優先される。

## 14. What to do when pace is too slow

USD 19.5kに対して消化が遅い場合でも、価値の低いburnはしない。追加する順番は以下。

1. J21 proof page scale。既にaccepted fixtureがある場合、GEO価値が直接増える。
2. J20 GEO adversarial eval。agent推薦の弱点を潰せる。
3. J17 local PDF OCR expansion。J06で高yield document classが見えている場合だけ。
4. J22 compaction/QA rerun。将来のAthena/scan costを下げられる場合だけ。
5. J05/J10のhigh-value source family追加。termsとno-hit wordingが明確なものだけ。
6. J19 OpenSearch benchmark。query setとdelete planがある場合だけ。
7. J18 Bedrock classification。public-only、closed schema、false promotion 0のpilot後だけ。

追加してはいけないもの:

- GPU training。
- broad load test。
- no-purpose crawl。
- private CSV processing。
- production endpoint常駐。
- NAT Gatewayを前提にしたprivate network化。
- request-time LLM経路。

## 15. What to do when pace is too fast

control_spendが予定より速い場合:

1. 全queue capを50%へ下げる。
2. `jpcite-rerun-low-q` と `jpcite-stretch-q` をdisable。
3. J06/J17/J18/J19/J22を停止。
4. queued low-value jobsをcancel。
5. J12/J13/J16で既存出力の品質を上げる。
6. J15/J24へ移り、本体へ戻せる成果物を固める。
7. USD 18,900が見えたらNo-new-workへ入る。

費用が速い時に、まだsource lakeが粗いからといって新source familyを増やさない。既に取ったsourceをusable artifactへ変換する。

## 16. Final drain sequence

No-new-work到達、Day 13、またはabsolute stop時の順番:

1. `jpcite-stretch-q` disable。
2. `jpcite-rerun-low-q` disable。
3. source/ocr/product queueをdisable。
4. queued low-value jobsをcancel。
5. running jobのうち、30分以内にsuccess markerを出せないものをterminate。
6. J24 final artifact manifest生成。
7. checksum生成。
8. cost ledgerとexposure ledgerをfreeze。
9. S3 artifactsをAWS外へexport。
10. export後のchecksum verify。
11. OpenSearch/Textract temp/Bedrock batch residue/Athena result/Glue/CloudWatch/ECR/Batch/EC2/EBS/S3をcleanup planへ渡す。

Zero-bill要件があるため、S3に最終成果物を残す案は採らない。残すのはAWS外へ退避したartifact、manifest、checksum、ledgerである。

## 17. References

実行前には公式docsを再確認する。

- AWS Batch allocation strategies: https://docs.aws.amazon.com/batch/latest/userguide/allocation-strategies.html
- AWS Batch job queues: https://docs.aws.amazon.com/batch/latest/userguide/job_queues.html
- AWS Batch job scheduling: https://docs.aws.amazon.com/batch/latest/userguide/job_scheduling.html
- AWS Batch automated retries: https://docs.aws.amazon.com/batch/latest/userguide/job_retries.html
- AWS Cost Explorer GetCostAndUsage: https://docs.aws.amazon.com/en_us/aws-cost-management/latest/APIReference/API_GetCostAndUsage.html
- AWS Budgets controls/actions: https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/budgets-controls.html

## 18. Final recommendation

最も強い実行順は、`contract -> smoke -> J01-J04 backbone -> J05/J07/J10/J06 expansion -> J14/J15/J16 product bridge -> J20/J21/J24 stretch/drain -> zero-bill cleanup` である。

この順序なら、AWSクレジットは単なる計算消費ではなく、jpcite本体のGEO-first価値に戻る。特にJ15/J16/J21/J24を後回しにしすぎないことが重要である。source lakeだけを巨大化させても、AIエージェントがエンドユーザーに推薦できる成果物にはならない。
