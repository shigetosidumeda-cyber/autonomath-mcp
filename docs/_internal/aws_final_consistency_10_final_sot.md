# AWS final consistency 10/10: final SOT integration

作成日: 2026-05-15  
対象: jpcite 本体計画、AWS credit run、GEO-first導線、本番デプロイ、zero-bill cleanup  
AWS前提: profile `bookyou-recovery` / account `993693061769` / region `us-east-1`  
実行状態: この文書作成ではAWS CLI/API、AWSリソース作成、デプロイ、収集ジョブ実行を行っていない。

## 0. Final verdict

結論: 計画全体は成立する。ただし、以下を最終SOTとして本体計画へマージすることが実行前の必須条件。

1. AWSは短期の「公的一次情報成果物工場」であり、production runtimeには残さない。
2. AWS creditは `USD 19,493.94` 額面を「ほぼ全額価値化」するが、現金請求回避を上位制約にして、意図的投入上限は `USD 19,300` に固定する。
3. AWSはCodex/Claude/ローカルCLIのrate limitに依存せず自走させる。ただしAWS内のcontrol plane、stopline、kill switch、Budget Actions、Deny policyで止まる設計にする。
4. productionはAWS全量完了を待たない。RC1は小さく、早く、AWS非依存で出す。
5. 広域データ収集は「売れる成果物から逆算」したsourceだけを優先し、全公的情報をP0扱いしない。
6. raw CSVはAWS、repo、static assets、logs、proof pagesへ入れない。CSV価値はprivate overlayの派生aggregate factsで出す。
7. request-time LLMなしを維持する。Bedrock/LLMは公開一次情報のoffline候補抽出に限定し、claim昇格にはreceipt/spanを必須にする。
8. no-hitは常に `no_hit_not_absence`。不存在、安全、問題なし、許可不要、信用できる、という断定に使わない。
9. 最後はfinal export、checksum、repo/static/local import validation、rollback asset確認を終えてから、S3を含めてAWS run resourceを削除する。

判定:

| 対象 | 最終判定 |
| --- | --- |
| AWS credit run | 条件付きGO。guardrail/canary/export gate通過後にfull-speedへ進める |
| RC1 production | 条件付きGO。AWS全量を待たず、static proof + minimal MCP/API + limited paidで出す |
| API/DNS cutover to `jpcite-api` | RC1ではNO-GO。既存production workflowを使い、切替はRC1安定後の別承認 |
| zero-bill cleanup | GO。ただし外部export確認前にS3削除してはいけない |
| exact credit face value consumption | NO-GO。`USD 19,493.94` ぴったりは狙わない |

## 1. Input coverage note

横断対象:

- `aws_credit_review_01-20`: 存在する20本を対象。
- `aws_scope_expansion_01-30`: 存在する30本を対象。
- `aws_final_consistency_01-06`: 現在のローカルtreeで確認できた最終整合レビュー。

`aws_final_consistency_07-09` は、この統合時点のローカルtreeでは見つからなかった。したがって、この10/10は `01-06` と全credit/scope文書を正本入力として扱う。後から `07-09` が追加された場合も、この文書の非交渉条件と矛盾する内容は採用しない。

## 2. Final SOT decisions

### 2.1 AWS account and region

正本:

```text
AWS CLI profile: bookyou-recovery
AWS Account ID: 993693061769
Workload region: us-east-1
Billing/control region: us-east-1
Credit face value: USD 19,493.94
Intentional absolute spend line: USD 19,300
```

削るべき矛盾:

- `ap-northeast-1` を今回runの標準regionとして扱う記述。
- 複数regionをまたぐBatch/S3/ECR/CloudWatch/Glue/Athena/OpenSearch構成。
- `USD 19,493.94` を可視使用額としてぴったり狙う表現。

### 2.2 AWS role

AWSは次だけを行う。

- 公的sourceのsource_profile化。
- license/terms/robots/source boundaryの判定。
- 公的一次情報のsnapshot、DOM/PDF/text、Playwright observation receipt、OCR inputの生成。
- `source_receipts[]`、`claim_refs[]`、`known_gaps[]`、`no_hit_checks[]`、`gap_coverage_matrix[]` の候補生成。
- packet examples、proof sidecars、GEO eval、pricing examples、manifest、checksum、quality gate reportの生成。
- 最終exportと削除可能なartifact bundleの作成。

AWSは次をしない。

- production runtimeとして稼働し続ける。
- productionからS3/OpenSearch/Athena/Glue/Batchを直接読ませる。
- raw CSVを受け取る、保存する、ログに出す。
- request-time LLMで公的事実を生成する。
- source terms、robots、access controlを回避する。
- CAPTCHA、login、paywall、明示rate limitを突破する。

### 2.3 Production role

productionはAWSから取り込んだ検証済みbundleだけを読む。runtimeに残してよいのはrepo/static DB/既存production storageにasset化された小さな正規化データであり、AWS endpointではない。

`runtime.aws_dependency.allowed=false` をproduction hard gateにする。

### 2.4 Commercial route

主戦はSEOではなくGEO。

正しい販売導線:

1. AI agentが `llms.txt`、`.well-known`、agent-safe OpenAPI、MCP manifest、proof pagesを発見する。
2. AI agentが無料のcatalog / routing / cost previewで「このpacketを買うべきか」を判断する。
3. エンドユーザーに費用、根拠、known gaps、no-hit caveatを説明する。
4. ユーザー承認後、API key / MCP / capped paid executionへ進む。
5. packet outputはsource-backedで返し、billing metadataを明示する。

営業デモ主導、SEO記事量産主導、広告依存は本計画の主戦ではない。

## 3. Single merged execution order

この順番を本体計画へマージする。

### Phase 0: Final SOT freeze

目的: 実行前に計画の矛盾を消す。

必須作業:

1. 本文書を最終SOTとして参照する。
2. 古い `ap-northeast-1` 記述を今回runでは不採用にする。
3. `USD 19,493.94` ぴったり消化を狙う記述を削除する。
4. `S3を残してzero-bill` という表現を削除する。
5. `eligible`、`safe`、`risk score`、`credit score`、`許可不要`、`問題なし`、`違反なし` の断定表現をrelease blockerへ入れる。
6. full OpenAPI/MCPを初回導線に出す記述を削り、agent-safe subsetを正本にする。

### Phase 1: Product contract freeze

本体P0-E1/E2/E3を先に固める。

必須contract:

- packet catalog
- packet envelope
- pricing catalog
- MCP tool naming
- agent-safe OpenAPI subset
- `source_profile`
- `source_receipts[]`
- `claim_refs[]`
- `known_gaps[]`
- `gap_coverage_matrix[]`
- `no_hit_checks[]`
- `quality_gate_report`
- `billing_metadata`
- `algorithm_trace`
- `request_time_llm_call_performed=false`

このphaseが終わるまで、AWS full-speed runに入らない。canaryだけは許可。

### Phase 2: Production skeleton and import gate

AWSを動かす前または並行で、本体側に以下を作る。

1. static proof renderer。
2. AWS artifact import validator。
3. bundle manifest validator。
4. checksum verification。
5. catalog drift test。
6. API/MCP/proof/pricing/llms/.well-known同一SOT生成またはdrift gate。
7. raw CSV leak scan。
8. forbidden phrase scan。
9. rollback assets directory。

このphaseの目的は、AWSが大量成果物を作っても本番投入で詰まらない状態にすること。

### Phase 3: AWS guardrails and autonomous control plane

AWS full-speed前に必須。

構成:

- EventBridge Scheduler: sentinel/orchestrator/cleanup tick。
- Step Functions Standard: run state machine。
- AWS Batch: worker execution。
- SQS: job handoff / backpressure。
- DynamoDB control table: run state、budget line、approval、kill switch。
- CloudWatch alarms/log metrics: telemetry。
- Budgets Actions: DenyNewWork / EmergencyDenyCreates。
- Lambda kill switch: stop/drain/deny trigger。
- IAM roles and permission boundaries: setup/operator/batch/budget/cleanup/read-only audit分離。
- S3 temporary artifact bucket: export前の一時置き場。

重要:

- Budgetsはhard capではない。
- IAM Denyは新規作成を止めるが、cleanup roleの停止/削除権限は奪わない。
- すべてのrun resourceに `Project=jpcite`、`Run=aws-credit-2026-05`、`Owner=bookyou`、`ZeroBillRequired=true` 相当のtagを付ける。
- local CLIやCodex/Claudeのheartbeatをrun継続条件にしない。

### Phase 4: AWS canary

予算: `USD 100-300`。

canary対象:

- J01 source profile sweep sample。
- J02/J03 法人番号またはインボイスreceipt shape。
- J12 receipt completeness audit。
- J15 one packet fixture。
- J16 forbidden-claim/no-hit scan。
- Playwright screenshot canaryはsource_profile gate済みsourceだけ。

canary GO条件:

- Cost Explorer / budget telemetryが見える。
- run manifestとartifact manifestが出る。
- source receiptがcontractに合う。
- no-hitが `no_hit_not_absence` として表現される。
- screenshot width <= 1600px。
- screenshotはclaim supportではなくobservation receipt扱い。
- cleanup dry-runで対象resourceを列挙できる。

### Phase 5: AWS standard self-running lane

Codex/Claudeが止まってもAWS内で進むlane。

優先:

1. P0-A backbone source。
2. P0-B revenue-direct source。
3. packet/proof/product bridge。
4. GEO eval and forbidden-claim eval。
5. accepted artifactだけをexport候補にする。

P0-A source:

- NTA法人番号。
- NTAインボイス。
- e-Gov法令。
- source_profile / license / terms / robots。
- core public identifiers。
- gBizINFO。
- e-Stat base。

P0-B source:

- J-Grants / public grants。
- 自治体の選定済み補助金/制度ページ。
- 調達/入札/落札。
- 行政処分/監督処分/ネガティブ情報。
- 業法/許認可/標準処理期間。
- 税/労務/社会保険の公的カレンダー・制度情報。
- EDINET metadata / key facts。
- 金融庁、国交省、厚労省、消費者庁、公取委など高価値公表情報。

P1 source:

- 官報/告示/公告/公示。
- パブコメ結果。
- 広域自治体。
- 裁判所/審決/紛争。
- 統計/地理/区域。
- 標準/認証/製品安全。
- 技適/PSE/食品表示/PMDA等。

P2/P3 caution:

- 政治・個人寄りの公開情報。
- 匿名化や名誉・プライバシー配慮が難しい情報。
- full XBRLなどlaunch blockerになりやすい重い処理。
- access controlやtermsが曖昧なsource。

### Phase 6: RC1 implementation lane

AWS standard runと並行して本体を進める。

RC1はAWS全量を待たない。狙いはAI agentが推薦可能な最小有料導線。

RC1 free controls:

- `agent_routing_decision`
- `cost_preview_quote`
- packet catalog
- no-hit explanation
- source/coverage explanation

RC1 limited paid:

- `company_public_baseline`
- `source_receipt_ledger`
- `evidence_answer`

RC1では入れない:

- raw CSV upload production execution。
- vendor risk scoreの本番断定。
- full source lake。
- broad local government corpus。
- AWS-hosted runtime dependency。
- API/DNS cutover to `jpcite-api`。

### Phase 7: RC1 staging and production

順番:

1. contract tests。
2. import validator。
3. static proof renderer。
4. staging deploy。
5. smoke tests。
6. public static proof pages production。
7. free controls production。
8. limited paid production with low cap。
9. MCP discovery production。
10. GEO index surfaces production。

RC1 target:

- 既存production workflowを使う。
- `autonomath-api` / existing production targetが現行SOTなら、RC1ではそこを前提にする。
- `jpcite-api` cutoverはRC1 stable 24-48h後の別承認。

rollback:

- AWS accessなしで戻せること。
- rollback bundleとstatic assetsはAWS外にあること。

### Phase 8: AWS revenue-first expansion

RC1と並行または直後に、売上に直結する成果物へAWS成果物を寄せる。

優先packet:

1. `invoice_vendor_public_check`
2. `counterparty_public_dd_packet`
3. `administrative_disposition_radar_packet`
4. `grant_candidate_shortlist_packet`
5. `application_readiness_checklist_packet`
6. `permit_scope_checklist_packet`
7. `regulation_change_impact_packet`
8. `tax_labor_event_radar_packet`
9. `procurement_opportunity_radar_packet`
10. `csv_monthly_public_review_packet`

このphaseで広げるsourceは、必ず `primary_paid_output_ids[]` を持つ。売れるpacketに紐づかない広域収集は後回し。

### Phase 9: Controlled stretch

目的: 価値ある成果物に寄せながら `USD 19,300` 近くまで消化する。

stretch候補:

- Playwright/1600px screenshot receipt expansion。
- Textract/OCR for official PDFs。
- public-only Bedrock batch candidate classification。
- temporary OpenSearch retrieval benchmark。
- GEO adversarial eval expansion。
- proof page scale generation。
- Athena/Glue QA reruns and compaction。
- final artifact packaging/checksum/export。

stretch条件:

- Spend lineが `USD 18,900` を超えても、forecast + queued exposureが `USD 19,300` 未満。
- untagged spendがない。
- unexpected service spendが `USD 100` を超えない。
- source terms/robots gateがgreen。
- accepted artifact yieldが基準を満たす。
- cleanup pathが壊れていない。

### Phase 10: RC2 and RC3 production increments

RC2:

- high-revenue vertical packets。
- grants/procurement/vendor public check/permit/admin disposition。
- source familyはP0-B中心。

RC3:

- broad corpus。
- CSV private overlay。
- regulation change impact。
- tax/labor/social event radar。
- standards/certification/geospatial selected packets。

CSV overlayはRC3以降。理由はprivacy gateとleak scanが本体信頼性の中核だから。

### Phase 11: Final export and assetization

zero-bill cleanup前に必須。

export package:

- `run_manifest.json`
- `artifact_manifest.jsonl`
- `dataset_manifest.jsonl`
- `source_profiles.jsonl`
- `source_documents.jsonl`
- `source_receipts.jsonl`
- `claim_refs.jsonl`
- `known_gaps.jsonl`
- `gap_coverage_matrix.jsonl`
- `no_hit_checks.jsonl`
- `quality_gate_reports.jsonl`
- `license_terms_ledger.jsonl`
- `algorithm_traces.jsonl`
- `packet_examples/*.json`
- `proof_page_sidecars/*.json`
- `geo_eval_report.json`
- `cost_artifact_ledger.json`
- `checksum_manifest.txt`
- `cleanup_ledger.md`

assetization先:

- repo contract assets。
- static runtime DB assets。
- static proof assets。
- local/non-AWS archive。

禁止:

- raw downloaded filesをterms未確認のままpublic repoへ入れる。
- screenshotをclaim根拠として公開する。
- raw CSVに由来する行データや個人/取引先名をasset化する。

### Phase 12: Zero-bill teardown

zero-bill標準ではS3も削除する。

削除順:

1. EventBridge schedule/rule停止。
2. Step Functions新規分岐停止。
3. Batch queues disable。
4. queued/running Batch jobs cancel/terminate。
5. Batch compute environment cap 0。
6. ECS/Fargate tasks停止。
7. EC2/Spot/ASG停止削除。
8. OpenSearch削除。
9. NAT Gateway/EIP/ENI/LB削除。
10. EBS volumes/snapshots/AMI削除。
11. ECR images/repositories削除。
12. Glue databases/tables/crawlers/jobs削除。
13. Athena outputs/workgroups削除。
14. CloudWatch logs/metrics/dashboards/alarms削除。
15. Lambda/Step Functions/EventBridge/SQS/DynamoDB control resources削除。
16. S3 object versions/multipart uploads/buckets削除。
17. run専用Budgets Actions/IAM emergency policies/roles削除または無効化。
18. final resource inventory。
19. post-teardown billing checks。

### Phase 13: Post-teardown checks

1. teardown当日。
2. 翌日。
3. 3日後。
4. 月末後または請求確定後。

見るもの:

- Cost Explorer daily cost。
- untagged spend。
- paid exposure。
- run tagsの残存resource。
- S3/ECR/OpenSearch/NAT/EIP/EBS/CloudWatch/Glue/Athena/Batch/Step Functions/EventBridge/Lambda/DynamoDB。

## 4. AWS spend and stopline SOT

### 4.1 Stopline table

| Line | USD | State | Automatic action |
| --- | ---: | --- | --- |
| Canary | 100-300 | `CANARY` | canary verification only |
| Watch | 17,000 | `RUNNING_STANDARD` | freeze scale-up, verify forecast |
| Slowdown | 18,300 | `SLOWDOWN` | stop render/OCR expansion unless high-yield, reduce queues |
| No-new-work | 18,900 | `NO_NEW_WORK` | no new source jobs, finish/export accepted work |
| Stretch | 19,100-19,300 | `RUNNING_STRETCH` or `DRAIN` | pre-approved short jobs only |
| Absolute safety | 19,300 | `TEARDOWN` | EmergencyDenyCreates, kill switch, export/cleanup |

### 4.2 Why not exact USD 19,493.94

`USD 19,493.94` ぴったり消化と、現金請求ゼロは両立しない。理由:

- Cost Explorer/Billing反映には遅延がある。
- AWS creditsの対象外費用が混ざる可能性がある。
- running/queued jobsの残りコストをリアルタイムで完全には読めない。
- cleanup遅延やログ/ストレージ/ネットワークの端数が残る。

したがって、最終表現は「`USD 19,300` までを意図的投入上限として、ほぼ全額を価値ある成果物に変える」。

### 4.3 One-week target

1週間以内に使い切る目標は成立する。ただし品質gateを捨てない。

| Day | Target |
| --- | --- |
| Day 0 | guardrails, canary, stop drill |
| Day 1-2 | P0-A backbone high parallel run |
| Day 3-4 | revenue-first P0-B expansion, RC1 staging/production |
| Day 5 | watch/slowdown evaluation, high-yield stretch selection |
| Day 6 | no-new-work approach, final stretch only if clean |
| Day 7 | final export, assetization, teardown start |

2週間fallback:

- source terms確認やrate limitsで遅れた場合、Day 8-14でP1 selected sources、proof generation、GEO eval、final assetizationを進める。
- ただし `USD 19,300` を超える新規投入はしない。

## 5. Autonomous AWS run SOT

### 5.1 Run states

```text
PLANNED
PREFLIGHT
GUARDRAIL_READY
CANARY
CANARY_PASSED
RUNNING_STANDARD
RUNNING_REVENUE
SLOWDOWN
NO_NEW_WORK
RUNNING_STRETCH
DRAIN
EXPORTING
TEARDOWN
COMPLETE_ZERO_BILL
HALTED_MANUAL_REVIEW
```

### 5.2 Queue classes

| Queue | Purpose | Stop behavior |
| --- | --- | --- |
| `jpcite-control-q` | sentinel/audit/export/cleanup | survives until teardown |
| `jpcite-core-source-q` | P0-A source receipts | stop new work at 18,900 |
| `jpcite-revenue-source-q` | P0-B source receipts | prefer until slowdown |
| `jpcite-render-ocr-q` | Playwright/Textract/OCR | reduce at 18,300 unless high-yield |
| `jpcite-algorithm-q` | claim graph, decision tables, packet candidates | continue accepted jobs |
| `jpcite-eval-proof-q` | proof/GEO/forbidden phrase eval | continue if cheap/high value |
| `jpcite-stretch-q` | pre-approved stretch only | disabled by default |

### 5.3 Kill conditions

Immediate halt / drain:

- actual + forecast >= `USD 19,300`。
- paid exposure >= `USD 100`。
- untagged spend appears and cannot be explained。
- unexpected service spend > `USD 100`。
- cleanup role cannot stop/delete resources。
- source terms/robots violation detected。
- raw CSV or private value detected in AWS artifact/log。
- no-hit becomes absence/safety/clean claim。
- request-time LLM public fact generation appears。
- production runtime points to AWS S3/OpenSearch/Athena/Glue。

## 6. Product and packet SOT

### 6.1 Free controls

These are not paid packets:

- `agent_routing_decision`
- `cost_preview_quote`
- catalog lookup
- no-hit explanation
- source coverage explanation

Reason: AI agents must be able to recommend jpcite before asking the end user to pay.

### 6.2 RC1 paid packets

RC1 paid scope:

- `company_public_baseline`
- `source_receipt_ledger`
- `evidence_answer`

These are enough to validate:

- source-backed output value。
- billing/cap/idempotency。
- MCP/API paid route。
- proof page to paid execution conversion。

### 6.3 RC2 paid packets

- `invoice_vendor_public_check`
- `counterparty_public_dd_packet`
- `administrative_disposition_radar_packet`
- `grant_candidate_shortlist_packet`
- `application_readiness_checklist_packet`
- `permit_scope_checklist_packet`
- `procurement_opportunity_radar_packet`

### 6.4 RC3 paid packets

- `regulation_change_impact_packet`
- `tax_labor_event_radar_packet`
- `csv_monthly_public_review_packet`
- `vendor_public_risk_attention_packet`
- `standards_certification_check_packet`
- `regional_stat_geo_context_packet`

### 6.5 Names to normalize

| Old or ambiguous name | Final treatment |
| --- | --- |
| `application_strategy` | split into `grant_candidate_shortlist_packet` and `application_readiness_checklist_packet` |
| `client_monthly_review` | replace with `csv_monthly_public_review_packet`; RC3 until CSV privacy gates pass |
| `vendor risk score` | replace with `vendor_public_risk_attention_packet`; never credit/safety score |
| `eligible` | do not expose; use candidate/likely-fit/needs-review style labels |
| `safety source` | rename to enforcement/compliance/product-safety source family as appropriate |

## 7. Algorithm SOT

### 7.1 Non-negotiable contract

Every public packet must include:

- `source_receipts[]`
- `claim_refs[]`
- `known_gaps[]`
- `gap_coverage_matrix[]`
- `no_hit_checks[]` when relevant
- `algorithm_trace`
- `billing_metadata`
- `human_review_required` when decision boundaries are uncertain
- `_disclaimer`
- `request_time_llm_call_performed=false`

### 7.2 Allowed algorithms

- deterministic rule tables。
- source graph traversal。
- evidence graph construction。
- claim dedupe/conflict resolution。
- date/deadline diff。
- typed score sets with explicit meaning。
- three-valued logic: true / false / unknown。
- constraint matching。
- coverage gap scoring。
- public evidence attention scoring。

### 7.3 Forbidden algorithm outputs

- generic `score` without type。
- `eligible` as a user-facing label。
- `safe` / `clean` / `問題なし` / `違反なし`。
- `許可不要` as a conclusion。
- creditworthiness score。
- legal/professional advice conclusion。
- no-hit as proof of absence。
- screenshot-only claim support。
- LLM output as claim support without receipt/span。

### 7.4 LLM/Bedrock boundary

Allowed:

- offline extraction candidate generation from public sources。
- classification candidates for review。
- summarization drafts that are not claim authority。

Not allowed:

- request-time public fact generation。
- private CSV ingestion。
- claim support without source receipt。
- legal/financial/tax advice conclusion。

## 8. Source acquisition SOT

### 8.1 Playwright and screenshot

Allowed:

- public official pages requiring rendering。
- search forms and JS tables where access is public。
- screenshot width <= 1600px。
- screenshot as observation receipt。
- DOM/PDF/text/HAR/console metadata as primary evidence where permitted。

Not allowed:

- CAPTCHA bypass。
- login/session requirement bypass。
- paywall bypass。
- explicit rate limit bypass。
- screenshot as sole claim support。
- broad redistribution when terms do not allow it。

### 8.2 Terms and robots

Every source must have:

- `source_profile`
- `license_boundary`
- `robots_receipt`
- `terms_receipt`
- allowed acquisition mode
- allowed retention mode
- allowed publication mode
- no-hit semantics
- staleness window

Scale only after `source_profile` gate passes。

### 8.3 Information scope

情報範囲は十分広い。問題は範囲不足ではなく、P0優先順位を広げすぎること。

Final priority:

| Rank | Source family | Reason |
| --- | --- | --- |
| P0-A | corporate/invoice/law/source profile/core identifiers/gBizINFO/base stats | nearly all packets need these |
| P0-B | grants/procurement/permits/admin dispositions/tax labor/EDINET metadata/industry regulation | direct revenue outputs |
| P1 | gazette/public comments/local gov/courts/standards/geospatial | valuable expansion, not RC1 blocker |
| P2/P3 | political/personal-sensitive/full XBRL/broad reports | only after strict review |

## 9. CSV SOT

### 9.1 Raw CSV boundary

raw CSV must not be:

- uploaded to AWS。
- persisted in repo。
- persisted in DB。
- logged。
- echoed in error messages。
- used in proof pages。
- included in fixtures with real values。
- sent to LLM/Bedrock。

### 9.2 Allowed CSV-derived facts

Allowed after local/private analysis:

- period coverage。
- account category totals。
- month-level aggregates。
- count buckets。
- amount ranges。
- public identifier candidates only if explicitly confirmed/safe。
- redacted/suppressed join candidates。

Mandatory:

- small group suppression。
- formula injection prevention。
- provider template classification: freee/MoneyForward/Yayoi/generic/variant。
- aggregate-only allowlist。
- static leak scan。

### 9.3 CSV release position

CSV value is important, but production CSV packet execution should not block RC1. It enters RC3 after privacy and leak gates pass.

## 10. Pricing and billing SOT

### 10.1 Principles

- Free preview before paid execution。
- User approval before paid MCP/API call。
- usage cap / spend cap required。
- idempotency required。
- billing metadata returned in every response。
- no hidden billing from retries。

### 10.2 No-hit billing

No-hit-only result is not automatically billable.

Use:

- `no_charge_reason=no_supported_hit` when execution produces no paid artifact beyond safe caveat。
- paid only when user explicitly buys a coverage/no-hit ledger product。

### 10.3 Public copy

Use:

- "公的一次情報に基づく確認候補"
- "確認できた範囲"
- "未確認範囲"
- "source receipt付き"
- "no-hitは不存在証明ではありません"

Do not use:

- "安全"
- "問題なし"
- "違反なし"
- "許可不要"
- "確実に対象"
- "信用スコア"
- "審査済み"

## 11. Release blockers

Any one of these blocks release:

1. `request_time_llm_call_performed` is true or missing.
2. Public claim has no `claim_ref`.
3. `claim_ref` has no source receipt/span.
4. `known_gaps[]` missing.
5. `gap_coverage_matrix[]` missing for decision-like packet.
6. no-hit phrased as absence/safety/clean.
7. raw CSV/private value appears in output/log/docs/examples.
8. screenshot-only claim support.
9. source terms/robots unknown for scaled source.
10. license boundary does not permit planned retention/publication.
11. generic score exposed.
12. `eligible` exposed to user.
13. legal/tax/financial/professional advice conclusion.
14. API/MCP/proof/pricing/llms/.well-known drift.
15. pricing catalog mismatch.
16. missing cap token/approval token for paid execution.
17. production reads AWS S3/OpenSearch/Athena/Glue/Batch.
18. rollback requires AWS access.
19. external export not verified before teardown.
20. cleanup role blocked by Deny policy.
21. actual+forecast spend line exceeds allowed state.
22. untagged spend unexplained.
23. unexpected paid service > `USD 100`.
24. `ap-northeast-1` resource created for this run without explicit exception.
25. post-teardown residual spend resource remains.

## 12. Go/No-Go before execution

### 12.1 GO before canary

- AWS profile/account/region fixed: `bookyou-recovery` / `993693061769` / `us-east-1`。
- credit balance and expiry confirmed in console。
- eligible services understood。
- read-only billing visibility works。
- IAM roles/boundaries planned。
- cleanup role can stop/delete。
- external export destination decided。
- packet contract frozen enough for canary。
- no raw CSV path in AWS jobs。

### 12.2 GO before full-speed AWS

- canary passed。
- budget actions created and tested。
- kill switch tested。
- Batch queue caps set。
- DynamoDB control table/state machine working。
- cost telemetry and forecast visible。
- artifact manifests valid。
- source_profile gate active。
- terms/robots gate active。
- cleanup dry-run inventory works。
- import validator exists。
- production lane does not depend on AWS。

### 12.3 NO-GO

- exact `USD 19,493.94` consumption is treated as target。
- any production runtime dependency on AWS run resources。
- no external export target。
- cleanup permissions untested。
- Budgets treated as hard cap。
- source terms unchecked before scale。
- raw CSV included in AWS plan。
- public packet can be generated without receipts。
- no-hit copy not locked。
- free/paid packet boundary unclear。
- `agent_routing_decision` is paid。
- API/DNS cutover bundled into RC1。

## 13. Mandatory fixes to merge into main plan

1. Update region from old examples to `us-east-1` everywhere in execution runbooks.
2. Replace "use all USD 19,493.94 exactly" with "maximize useful artifact generation up to USD 19,300 intentional cap".
3. Mark AWS as short-term artifact factory, not runtime.
4. Add EventBridge Scheduler / Step Functions Standard / SQS / DynamoDB / kill switch Lambda to control plane.
5. Add external export gate before full-speed and before teardown.
6. Add `COMPLETE_ZERO_BILL` definition that includes S3 deletion.
7. Move broad P1/P2 source collection out of RC1 blockers.
8. Add `primary_paid_output_ids[]` to each source family/job.
9. Add `accepted_artifact_target` to every AWS job.
10. Make `source_profile` gate mandatory before Playwright/OCR scale.
11. Make screenshot <= 1600px an observation receipt only.
12. Add `gap_coverage_matrix[]` to decision-like packet contract.
13. Ban public `eligible`, generic `score`, and safety/clean claims.
14. Make `agent_routing_decision` free.
15. Add `company_public_baseline` to RC1 limited paid.
16. Rename/split ambiguous packet names.
17. Keep CSV production packet to RC3 unless privacy gates are already implemented.
18. Make GEO/public page checks release blockers for packet/proof/pricing/agent-discovery releases.
19. Keep full OpenAPI/MCP out of first-call agent path.
20. Add post-teardown billing checks for next day, 3 days later, and month-end.

## 14. Contradictions to delete or override

| Contradiction | Final resolution |
| --- | --- |
| `ap-northeast-1` vs user default `us-east-1` | `us-east-1` only for this run |
| exact credit use vs no cash bill | cap intentional spend at `USD 19,300` |
| Budgets as hard cap | Budgets Actions are brake signals, not hard cap |
| AWS self-running vs uncontrolled spend | AWS control plane + stoplines + kill switch |
| S3 retained vs zero-bill | S3 deleted after external export |
| AWS artifact as production SOT | only validated imported assets become production SOT |
| full corpus before production | RC1 ships before full corpus |
| all public information P0 | only output-backed source is P0 |
| screenshot as proof | screenshot is observation receipt only |
| no-hit as absence | no-hit is not absence |
| request-time LLM | forbidden |
| raw CSV in AWS | forbidden |
| `agent_routing_decision` paid | free |
| `eligible` public label | forbidden |
| vendor risk score | evidence attention packet, not credit/safety score |
| API/DNS cutover in RC1 | separate approval after RC1 stable |

## 15. Final calendar

Fast path:

| Day | AWS lane | Product lane |
| --- | --- | --- |
| 0 | preflight, guardrails, canary | contract freeze, flags, import validator |
| 1 | P0-A core source run | static proof renderer, catalog/pricing |
| 2 | P0-A/P0-B revenue run | RC1 packet composers, staging prep |
| 3 | product bridge, GEO eval | RC1 staging, static production |
| 4 | standard run scale | free controls + limited paid production |
| 5 | watch/slowdown, high-yield stretch | RC1 monitoring, RC2 import prep |
| 6 | no-new-work or pre-approved stretch | RC2 selected packets |
| 7 | export, assetization, teardown start | production patch, rollback verification |

Fallback:

- Day 8-10: RC2/RC3 selected imports, proof/GEO patching。
- Day 11-14: final export, zero-bill cleanup, post-teardown report。

## 16. Final state

Successful final state:

1. AWS spend intentionally stops at or before `USD 19,300` actual+forecast control line.
2. Useful artifacts are exported outside AWS.
3. Production runs without AWS run resources.
4. RC1 is live with GEO discovery, free controls, limited paid packets, and proof pages.
5. RC2/RC3 have an import-ready backlog from accepted artifacts.
6. All AWS run resources are deleted or proven non-billable.
7. Post-teardown billing checks are scheduled.
8. The durable value is in source-backed datasets, packet examples, proof pages, manifests, algorithm traces, and product code, not in running AWS infrastructure.

最終SOTとして、本体計画へマージする順番は次で固定する。

```text
SOT freeze
-> product contract freeze
-> production skeleton/import gate
-> AWS guardrails/autonomous control plane
-> AWS canary
-> AWS standard self-running lane + RC1 implementation lane
-> RC1 staging/production
-> revenue-first AWS expansion
-> controlled stretch up to USD 19,300 cap
-> RC2/RC3 incremental imports
-> final export and assetization
-> zero-bill teardown
-> post-teardown billing checks
```

