# AWS final consistency 06/10: release train and production deployment review

作成日: 2026-05-15
担当: 最終矛盾チェック 6/10 / 本番デプロイ・release train
対象: RC1/RC2/RC3, feature flags, static proof pages, minimal MCP/API, AWS成果物import, CI, staging, production, rollback, monitoring, AWS zero-bill teardown
AWS前提: profile `bookyou-recovery` / account `993693061769` / default region `us-east-1`
状態: 計画レビューのみ。AWS CLI/APIコマンド、AWSリソース作成、デプロイ実行はしない。
出力制約: このMarkdownのみ。

## 0. 結論

既存計画の大方針は矛盾していない。

ただし、そのまま実行すると本番デプロイで詰まる可能性がある箇所がある。特に危ないのは、次の5点。

1. RC1に入れる範囲がやや広い。最速productionには `RC1a static proof + free controls` と `RC1b limited paid` を分けるべき。
2. `autonomath-api` と `jpcite-api` の扱いを混同すると、AWS成果物importとAPI cutoverが同時事故になる。
3. GEO surfaceは早く出したいが、`llms.txt` / `.well-known` / MCP manifestを誤った状態で公開するとAI agentに誤学習される。
4. AWSが自走することと、本番importが人間/CI gateを通ることは分離しないと危ない。
5. zero-bill teardown後もrollbackできるよう、rollback assetsをAWS外へ退避してからAWSを削除する必要がある。

改善後の最速production順は以下で固定する。

```text
contract freeze
-> feature flags
-> static proof renderer
-> import validator
-> AWS guardrails/canary in parallel
-> RC1a static proof pages + pricing + docs + free preview
-> RC1b minimal MCP/API + 3 paid packets with low cap
-> RC2 high-revenue vertical packets in small slices
-> RC3 broad corpus + CSV overlay limited
-> final export outside AWS
-> zero-bill teardown
```

最重要ルールは、productionがAWS S3/Batch/OpenSearch/Glue/Athenaをruntimeで読まないこと。AWSは短期のartifact factoryであり、本番実行基盤ではない。

## 1. Reviewed inputs

主に以下を確認した。

- `docs/_internal/aws_scope_expansion_28_production_release_train.md`
- `docs/_internal/aws_credit_review_15_repo_import_deploy.md`
- `docs/_internal/aws_credit_unified_execution_plan_2026-05-15.md`
- `docs/_internal/aws_scope_expansion_25_fast_spend_scheduler.md`
- `docs/_internal/aws_scope_expansion_26_data_quality_gates.md`
- `docs/_internal/aws_scope_expansion_29_post_aws_assetization.md`
- `docs/_internal/aws_scope_expansion_30_synthesis.md`
- `docs/_internal/aws_credit_review_20_final_synthesis.md`
- `.github/workflows/deploy.yml`
- `.github/workflows/deploy-jpcite-api.yml`
- `.github/workflows/pages-deploy-main.yml`
- `.github/workflows/release-readiness-ci.yml`
- `.github/workflows/geo_eval.yml`

確認したworkflow上の重要事実:

- `deploy.yml` は現在のproduction SOTとして `autonomath-api` を扱う。
- `deploy-jpcite-api.yml` は新app `jpcite-api` のparallel laneであり、`api.jpcite.com` cutoverは別判断。
- `deploy-jpcite-api.yml` のdefault smoke base URLは `https://jpcite-api.fly.dev`。
- `deploy.yml` は `PRODUCTION_DEPLOY_OPERATOR_ACK_YAML` を要求する。
- `deploy.yml` のpost-deploy smoke base URLは `https://api.jpcite.com`。
- Pages側はproof/docs/discovery surfaceを扱うが、AWS importを直接本番runtimeへ接続するものではない。

## 2. Final verdict

### 2.1 GO / NO-GO

| Area | Verdict | 条件 |
|---|---|---|
| RC1 static proof pages | GO | fixture生成、leak scan、no-hit scan、render checkが通ること |
| RC1 free controls | GO | route/catalog/cost previewがAPI/MCPで一致すること |
| RC1 limited paid | CONDITIONAL GO | billing cap、idempotency、source receipt presence、rollback flagが通ること |
| RC2 vertical packets | CONDITIONAL GO | packetごとにproof page、algorithm_trace、known_gapsがあること |
| RC3 CSV overlay | DELAY | raw CSV非保存、suppression、formula injection、public/private境界gate後 |
| API cutover to `jpcite-api` | NO-GO for RC1 | RC1安定後の別承認にする |
| AWS zero-bill teardown | MANDATORY | final export、rollback assets退避、resource inventory後 |

### 2.2 最速production案

本当に最速にするなら、RC1を3つに割る。

| Release | 目的 | 出すもの | Paid |
|---|---|---|---:|
| RC1a | AI agentに見つけさせる | static proof pages, pricing, docs, `llms.txt` draft, `.well-known` draft | off |
| RC1b | API/MCP導線を成立させる | route, catalog, cost preview, minimal OpenAPI, minimal MCP | off |
| RC1c | 最小課金を始める | 3 packet: `evidence_answer`, `source_receipt_ledger`, `agent_routing_decision` | low cap |

この分割により、AWS全run完了を待たず、Day 2-3にproductionへ価値を出せる。

## 3. Correct merged release order

本体計画とAWS計画をmergeした正しい順番は以下。

### Phase A: Contract freeze

最初に固定する。

- `jpcite.packet.v1`
- packet catalog
- `source_receipts[]`
- `claim_refs[]`
- `known_gaps[]`
- `no_hit_checks[]`
- `billing_metadata`
- `algorithm_trace`
- `request_time_llm_call_performed=false`
- CSV privacy boundary
- artifact manifest schema
- pricing/cost preview schema
- OpenAPI operation names
- MCP tool names
- proof page URL naming

この前にJ15/J21の大量packet/proof生成をしない。

### Phase B: Feature flags

production露出を段階化する。

必須flag:

- `runtime.aws_dependency.allowed=false`
- `proof_pages.static.enabled`
- `proof_pages.rc1.enabled`
- `api.packet.route.enabled`
- `api.packet.preview_cost.enabled`
- `api.packet.evidence_answer.enabled`
- `api.packet.source_receipt_ledger.enabled`
- `api.packet.agent_routing_decision.enabled`
- `mcp.agent_first.enabled`
- `mcp.full_catalog.visible`
- `billing.free_preview.enabled`
- `billing.paid_execution.enabled`
- `csv_overlay.preview.enabled`
- `csv_overlay.paid.enabled`
- `verticals.grants.enabled`
- `verticals.procurement.enabled`
- `verticals.vendor_risk.enabled`
- `verticals.permits.enabled`
- `verticals.reg_change.enabled`
- `verticals.tax_labor.enabled`

本番では `runtime.aws_dependency.allowed` を常にfalseにする。

### Phase C: Static proof renderer

AWS成果物やfixtureからpublic proof pagesを生成する。ただし、手書きでAPI/MCP例と乖離させない。

生成元:

- packet fixtures
- source receipt samples
- claim ref samples
- known gap samples
- no-hit examples
- pricing examples
- artifact manifest checksum

proof pageに必ず出す:

- packetの用途
- output example
- source family
- `source_receipts[]`
- `claim_refs[]`
- `known_gaps[]`
- no-hit caveat
- cost preview
- MCP tool
- OpenAPI operation
- catalog version
- generated timestamp

proof pageに出さない:

- raw CSV
- private user data
- AWS S3 URL
- raw crawler logs
- raw HAR
- unreviewed screenshot
- 「安全」「問題なし」「不存在証明」「許認可不要」「採択可能」などの断定

### Phase D: Import validator

AWS canary/export bundleをrepoに入れる前に必ず通す。

Reject条件:

- `run_manifest.json` がない
- checksumがない
- `aws_account_id != 993693061769`
- `region != us-east-1` かつ承認されたsubrunでない
- `raw_csv_present=true`
- `private_data_present=true`
- source URL / fetched_at / hashがない
- claimがsource_receiptに解決できない
- no-hitが安全/不存在/問題なしに見える
- `request_time_llm_call_performed=false` がない
- production runtimeがAWS URLを読む

### Phase E: AWS guardrails and canary in parallel

本体側でcontract/flags/renderer/validatorを作る間に、AWS側はguardrailsとcanaryだけ進める。

AWS canaryで許可するもの:

- J01 source profile small
- J02/J03 receipt shape small
- J04 e-Gov small
- J12 completeness small
- J15 one packet fixture
- J16 forbidden/no-hit scan
- J41 Playwright canary

AWS standard/stretchは、contractとimport validatorなしで始めない。

### Phase F: RC1a production static

最初にproductionへ出すのはstatic surface。

出すもの:

- `/proof/evidence-answer`
- `/proof/source-receipt-ledger`
- `/proof/agent-routing-decision`
- `/packets`
- `/pricing`
- `/docs/agents`
- `llms.txt`
- `.well-known` discovery files
- agent-safe OpenAPI preview link
- MCP setup docs

この時点ではpaidはoffでよい。

### Phase G: RC1b minimal MCP/API

次にfree controlsを出す。

REST:

- get packet catalog
- route packet
- preview cost
- get proof metadata
- explain no-hit

MCP:

- `jpcite_route` または既存命名に合わせたagent route tool
- `jpcite_preview_cost`
- `jpcite_get_packet_catalog`
- `jpcite_get_proof`
- `jpcite_explain_no_hit`

full 155 toolsはdefaultに出さない。agent-first facadeを主導線にする。

### Phase H: RC1c limited paid

最後に低capでpaidをonにする。

有効化するpacket:

- `evidence_answer`
- `source_receipt_ledger`
- `agent_routing_decision`

条件付きで後回し:

- `company_public_baseline`
- `application_strategy`
- `client_monthly_review`

paid前の必須条件:

- free cost preview first
- user cap required
- idempotency key required
- validation failureはno-charge
- source receipt presence rate gate pass
- billing metadata parity pass
- rollback flag ready

### Phase I: RC2 small slices

RC2は一括releaseにしない。

推奨slice:

1. `grant_candidate_shortlist`
2. `procurement_opportunity_radar`
3. `vendor_public_evidence_packet`
4. `permit_requirement_check`
5. `administrative_action_check`
6. `reg_change_impact_brief`

各sliceの順番:

```text
proof page
-> API preview
-> MCP preview
-> limited paid
-> GEO discovery update
-> pricing bundle update
```

### Phase J: RC3 broad corpus and CSV overlay

RC3では広域sourceとCSV overlayを入れる。ただしCSV paidは最後。

順番:

1. tax/labor public-source proof pages
2. local government proof pages
3. courts/enforcement proof pages
4. standards/certifications proof pages
5. geo/stat proof pages
6. API/MCP preview tools
7. CSV overlay preview local-only
8. CSV overlay paid limited
9. bundle pricing
10. agent recommendation examples

CSV overlayの絶対条件:

- raw CSVを保存しない
- raw CSVをAWSへ上げない
- raw CSVをログしない
- derived aggregate factsのみ
- small group suppression
- formula injection defense
- public/private boundary scan

### Phase K: Final export and zero-bill teardown

AWS credit runの最後。

teardown前に必ず完了:

- final artifact export
- checksum verification
- manifest archive outside AWS
- cost/artifact ledger outside AWS
- production RC bundles imported or explicitly deferred
- rollback assets outside AWS
- no production AWS dependency confirmed

teardown順:

1. no-new-work
2. disable queues
3. cancel queued jobs
4. drain/cancel running jobs
5. export S3 artifacts
6. verify checksums
7. delete OpenSearch domains
8. delete Batch compute environments and queues
9. stop/delete ECS/Fargate/EC2 resources
10. delete EBS volumes/snapshots
11. delete Glue/Athena outputs/workgroups/catalog created for run
12. delete ECR repos/images
13. delete CloudWatch logs/alarms/dashboards
14. delete Lambda/Step Functions/EventBridge/SQS/DynamoDB control resources created for run
15. delete NAT gateways/EIPs/load balancers/ENIs/security groups/VPC endpoints if created
16. delete S3 objects/buckets if zero ongoing bill is mandatory
17. remove temporary IAM roles/policies after cleanup verification
18. run immediate, next-day, 3-day, month-end billing/resource checks

## 4. Contradictions found and fixes

### C1. RC1 scope is too wide for fastest production

Problem:

RC1 docs include several source families and surfaces. If all are treated as mandatory, production waits for AWS outputs.

Fix:

Split RC1 into:

- RC1a static proof and docs
- RC1b free controls
- RC1c low-cap paid

Only the 3 core packets are required for RC1c.

### C2. Production target ambiguity

Problem:

`autonomath-api` and `jpcite-api` can be confused.

Fix:

- Current production API target remains `deploy.yml` / `autonomath-api`.
- `deploy-jpcite-api.yml` / `jpcite-api` is parallel staging/cutover prep.
- `api.jpcite.com` cutover is separate approval after RC1 stability.
- RC1 should not combine artifact import and DNS/API cutover.

### C3. GEO early exposure vs correction difficulty

Problem:

GEO-first requires early publication, but wrong `llms.txt`, `.well-known`, MCP, or pricing pages can be picked up by agents.

Fix:

Publish in this order:

1. hidden/internal proof preview
2. staging public-like proof
3. production static proof
4. production free controls
5. production limited paid
6. MCP discovery
7. GEO index surfaces

`llms.txt` and `.well-known` must be generated from the same catalog/spec used by MCP/API.

### C4. AWS self-running vs human-reviewed import

Problem:

User wants AWS to keep running even when Codex/Claude are rate-limited. But production import cannot be fully autonomous.

Fix:

- AWS job graph can self-run after guardrails.
- AWS exports checkpoint bundles daily or per slice.
- Production import remains gated by manifest/schema/privacy/no-hit/billing/parity tests.
- AWS can continue producing RC2/RC3 candidates while RC1 deploy is reviewed.

### C5. Credit fast-spend vs deploy safety

Problem:

Using credit fast could push large unreviewed artifact piles into release pressure.

Fix:

Two lanes:

- Fast deployment lane: RC1a/b/c, small verified bundle.
- Credit consumption lane: broad AWS standard/stretch jobs, sliced exports.

The lanes run concurrently, but only validated slices enter production.

### C6. Zero-bill teardown vs rollback

Problem:

If rollback depends on AWS S3 artifacts, teardown breaks rollback.

Fix:

Before teardown, preserve outside AWS:

- previous packet catalog
- previous OpenAPI
- previous MCP manifest
- previous `.well-known`
- previous `llms.txt`
- previous proof page set
- previous deploy image/release id
- DB snapshot/checksum if DB materialization changed
- imported RC bundle manifests

Rollback must not require AWS.

### C7. Pages advisory checks vs release blockers

Problem:

Some public-page/GEO checks may be advisory in workflow context, but for AWS-imported packet/proof/pricing releases they must block.

Fix:

Add a release-level hard gate before Pages/API production deploy:

- forbidden claim count = 0
- no-hit misuse count = 0
- private leak count = 0
- pricing drift = 0
- OpenAPI/MCP/catalog drift = 0
- proof page render = pass
- `llms.txt` / `.well-known` crawl = pass

### C8. MCP full catalog confuses first-call path

Problem:

Existing large MCP surface can overwhelm agents and weaken conversion.

Fix:

Default public MCP should expose agent-first minimal tools. Full catalog remains available through expert/discovery link, not first-call path.

### C9. Screenshot receipt can be overtrusted

Problem:

Playwright screenshots are useful, but screenshots alone should not support claims.

Fix:

Screenshot receipt is supporting evidence only. Claim support needs DOM/text/OCR span or structured field linked to `source_receipt`.

### C10. CSV overlay can accidentally leak or overpromise

Problem:

CSV overlay is high value but risky.

Fix:

RC3 only. Preview before paid. Raw CSV never enters AWS/repo/logs/proof pages. Public examples are synthetic or marked `private_overlay_excluded=true`.

## 5. RC detail

### 5.1 RC1a: static proof and agent discovery foundation

Goal:

AI agentがjpciteを発見し、何を買えるかを理解する。

Scope:

- 3 proof pages
- packet catalog
- pricing
- no-hit explanation
- agent docs
- static examples
- machine-readable discovery draft

Go gates:

- generated from fixtures
- no private data
- no raw CSV
- no unsafe no-hit
- no professional advice overclaim
- proof pages render 200
- links resolve
- catalog hash stable

Rollback:

- remove/revert new proof page set
- revert discovery files
- leave API untouched

### 5.2 RC1b: minimal free MCP/API

Goal:

Agentが「まず無料でroute/cost previewする」流れを実行できる。

Scope:

- route
- catalog
- cost preview
- proof metadata
- no-hit explanation
- agent-safe OpenAPI
- minimal MCP manifest

Go gates:

- OpenAPI generated equals committed
- MCP manifest matches implemented tools
- pricing page/API/MCP parity
- validation failure no-charge
- full catalog not default

Rollback:

- turn off MCP discovery
- turn off route/cost preview flags
- revert OpenAPI/MCP manifest

### 5.3 RC1c: limited paid core

Goal:

最小の課金導線を成立させる。

Scope:

- `evidence_answer`
- `source_receipt_ledger`
- `agent_routing_decision`

Go gates:

- source receipts not empty
- known gaps present
- billing metadata present
- cap enforcement pass
- idempotency pass
- paid execution low cap
- post-deploy smoke ready

Rollback:

- paid flags off first
- MCP paid tools off
- API paid routes off
- keep free proof pages if accurate

### 5.4 RC2: high-revenue verticals

Goal:

AI agentが「この成果物は買う価値がある」と説明しやすいpacketを増やす。

Priority:

1. grants/procurement
2. vendor public evidence
3. permit requirement
4. administrative action
5. regulation change

Go gates:

- source family license/terms pass
- algorithm trace present
- no overclaim
- proof page first
- cost preview first
- known gaps visible

Rollback:

- packet group flag off
- proof page set revert if wrong
- MCP catalog rollback

### 5.5 RC3: broad corpus and CSV overlay

Goal:

継続利用・反復課金・高単価packetへ広げる。

Priority:

1. tax/labor
2. local government
3. courts/enforcement
4. standards/certification
5. geo/stat
6. CSV overlay preview
7. CSV overlay limited paid

Go gates:

- privacy gates pass
- formula injection pass
- suppression pass
- legal/tax/labor advice overclaim scan pass
- permit/risk outputs use coverage gaps

Rollback:

- CSV flags off
- vertical packet flags off
- proof pages revert by set

## 6. CI and staging plan

### 6.1 CI gates before staging

Required checks:

- lint/type/unit tests for changed packet/API/MCP/proof code
- artifact bundle manifest validation
- private/raw CSV leak scan
- packet example contract validation
- `request_time_llm_call_performed=false` invariant
- no-hit copy scan
- forbidden professional claim scan
- OpenAPI drift
- MCP drift
- pricing drift
- public proof render test
- `llms.txt` / `.well-known` structure check
- GEO smoke

New test names recommended:

- `test_aws_artifact_bundle_manifest.py`
- `test_aws_artifact_no_private_leak.py`
- `test_packet_examples_contract.py`
- `test_packet_examples_no_request_time_llm.py`
- `test_no_hit_not_absence_copy.py`
- `test_public_proof_pages_from_fixtures.py`
- `test_openapi_mcp_examples_match_catalog.py`
- `test_geo_discovery_surfaces.py`
- `test_runtime_aws_dependency_forbidden.py`

### 6.2 Staging order

Staging order:

1. import small RC bundle on feature branch
2. run local validators
3. PR CI
4. Pages preview for proof/docs/discovery
5. API staging/parallel deploy if needed
6. MCP/OpenAPI fetch test
7. cost preview and cap test
8. private leak and no-hit smoke
9. GEO smoke
10. rollback drill

Staging must prove production does not read AWS.

### 6.3 Production order

Production order:

1. merge only after CI/staging pass
2. deploy static proof/pages first
3. turn on free controls
4. publish minimal MCP/OpenAPI discovery
5. turn on limited paid packet flags
6. run post-deploy smoke
7. monitor 24h
8. import next RC slice

Do not combine these in RC1:

- AWS full corpus completion
- `jpcite-api` DNS cutover
- CSV paid launch
- full 155-tool MCP default exposure
- broad source lake runtime query

## 7. Monitoring

### 7.1 Release health

Monitor:

- deploy success
- 5xx
- 4xx validation rate
- p95 latency
- route success
- cost preview success
- paid packet success
- MCP manifest fetch
- OpenAPI fetch
- proof page 200/render
- broken links
- rollback readiness

### 7.2 Evidence health

Monitor:

- source receipt presence rate
- claim ref resolution rate
- known gap presence rate
- no-hit caveat presence rate
- checksum match
- source URL reachability
- fetched_at freshness
- screenshot validation
- OCR confidence distribution

### 7.3 Billing health

Monitor:

- free preview count
- paid execution count
- cap hit count
- no-charge validation failures
- duplicate idempotency prevention
- unexpected paid event count
- billing metadata parity
- refund/void candidates

### 7.4 Safety and GEO health

Monitor:

- private leak scan
- raw CSV persistence scan
- formula injection detection
- no-hit unsafe wording
- forbidden phrase detection
- `llms.txt` fetch
- `.well-known` fetch
- agent route accuracy
- agent no-hit caveat preservation
- agent pricing explanation accuracy

## 8. Fastest calendar

### Day 0

- Freeze contract.
- Add feature flags.
- Add static proof renderer.
- Add import validator.
- Prepare AWS guardrails and canary requirements.
- Do not start broad AWS run before stop/cleanup design is ready.

### Day 1

- Run or receive AWS canary bundle after guardrails.
- Validate canary bundle.
- Generate RC1a proof pages.
- Generate agent-safe OpenAPI/MCP draft.
- Run leak/no-hit/pricing/parity gates.
- Pages preview.

### Day 2

- Production RC1a static pages if gates pass.
- Turn on free route/catalog/cost preview if gates pass.
- Keep AWS standard lane moving independently.

### Day 3

- Enable RC1c low-cap paid 3 packets only if billing/cap/source gates pass.
- Publish MCP discovery after parity.
- Start RC2 import slices.
- Monitor RC1.

### Day 4-7

- AWS runs full high-value corpus lanes.
- RC2 grants/procurement/vendor/permit slices deploy one by one.
- GEO discovery updates after each successful slice.

### Day 8-10

- RC3 public-source packets.
- CSV overlay preview only if privacy gates pass.
- Continue AWS stretch only for accepted artifact yield.

### Day 11-14

- No-new-work.
- Final export.
- Import/reject final slices.
- Preserve rollback assets outside AWS.
- Zero-bill teardown.
- Post-teardown billing/resource checks.

## 9. Release blockers

Always block release if any of these occur:

- production reads AWS S3/Batch/OpenSearch/Glue/Athena at runtime
- raw CSV persisted, logged, committed, or sent to AWS
- private data appears in public proof/discovery
- paid output has empty `source_receipts[]`
- `known_gaps[]` omitted for incomplete source coverage
- no-hit implies absence/safety/no issue
- request-time LLM creates public facts
- billing metadata missing or inconsistent
- cost preview missing before paid fanout
- idempotency missing for paid execution
- OpenAPI/MCP/catalog drift
- proof page claim cannot resolve to receipt
- rollback assets unavailable outside AWS
- zero-bill teardown cannot be executed

## 10. Improved final sequence to merge into the master plan

The master implementation plan should use this exact order:

```text
1. Contract freeze
2. Feature flag skeleton
3. Static proof renderer
4. AWS import validator
5. AWS guardrails and canary
6. RC1a static proof pages
7. RC1b free MCP/API controls
8. RC1c limited paid 3 packets
9. AWS standard/stretch continues independently
10. RC2 high-revenue packet slices
11. RC3 broad corpus and CSV preview/limited paid
12. Final artifact export outside AWS
13. Production rollback assets verification
14. AWS zero-bill teardown
15. next-day / 3-day / month-end billing checks
```

This is the cleanest order because it satisfies all constraints at once:

- GEO-first publication starts early.
- AI agents get a simple recommendation path.
- End users can get cheap source-backed outputs.
- AWS can keep consuming credit without Codex/Claude being active.
- Production does not wait for the whole AWS run.
- Paid execution is capped and reversible.
- CSV stays private.
- zero-bill teardown remains possible.

## 11. Final recommendation

Adopt the improved sequence above.

The biggest practical change is to stop treating RC1 as one release. RC1 should be split into `static`, `free controls`, and `limited paid`. That gives the fastest safe production path while AWS continues as a high-speed artifact factory in the background.

The second biggest change is to treat `jpcite-api` cutover as out of scope for RC1. Use the current production target unless there is a separate explicit cutover decision.

The third biggest change is to make rollback independent from AWS before teardown. Without that, the zero-bill requirement conflicts with production recovery.
