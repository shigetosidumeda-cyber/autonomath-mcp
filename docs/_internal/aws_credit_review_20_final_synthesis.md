# AWS credit review 20: final synthesis / contradiction review

作成日: 2026-05-15
レビュー枠: 追加20エージェントレビュー 20/20
担当: 全体矛盾、順序、請求リスク、本番デプロイ、GEO、AI agent課金導線、CSV privacy、成果物schemaの初回総合精査
対象AWS: profile `bookyou-recovery` / account `993693061769` / workload region `us-east-1`
状態: 計画レビューのみ。AWS CLI/API実行、AWSリソース作成、デプロイ実行、既存変更の巻き戻しは行っていない。

## 0. Executive conclusion

現時点の計画は、方向性としては成立している。ただし、そのまま実行に入ると危ない矛盾が残っている。

最重要の修正は次の9点。

1. AWS workload regionを `us-east-1` に統一する。統合計画に残る `ap-northeast-1` 例は実行前に直す。
2. AWS credit runは本体P0計画の後ろではなく、P0契約固定後に並走させる。順番は `contract freeze -> AWS guardrails -> canary -> import gate -> standard run -> RC1 deploy -> stretch -> export -> zero-bill cleanup`。
3. `review_19` が欠落している。価値最大化レビューの穴は、この20/20で暫定補完するが、最終マージ前に別途埋める。
4. 「Codex/Claudeのrate limitでもAWSは止まらない」と「operatorが30分以内に止められないなら停止」が衝突している。解決は、AWS内部のsentinel/kill switchで自走停止できる設計にすること。
5. 「クレジットを使い切る」と「請求を絶対に残さない」が衝突し得る。意図的な上限は `USD 19,300` のままにし、残り `USD 193.94+` は請求遅延・非対象費用の安全余白として扱う。
6. 本番デプロイはAWS全run完了を待たない。RC1は小さく、安全な3 packet中心で先に出す。
7. 現行production appのSOTは `deploy.yml` / `autonomath-api`。`deploy-jpcite-api.yml` / `jpcite-api` は並行新appであり、DNS/API cutoverは別承認にする。
8. Cloudflare PagesのGEO readinessがadvisory-onlyになっている。P0 packet/proof/pricing変更では、別のpre-deploy gateでhard blockerにする。
9. CSV価値は高いが、AWS credit runへraw CSVを上げない。AWSではsynthetic/header-only/redacted fixtureだけを使い、実ユーザーCSVは本体サービス側の一時処理でaggregate-onlyにする。

結論として、実行前に統合計画へ上記をマージすれば、AWS credit run、本体実装、本番デプロイ、zero-bill cleanupは一つの計画として通せる。

## 1. Reviewed inputs

主に以下を読んだ。

- `docs/_internal/consolidated_implementation_backlog_deepdive_2026-05-15.md`
- `docs/_internal/aws_credit_unified_execution_plan_2026-05-15.md`
- `docs/_internal/aws_credit_review_01_cost_stoplines.md`
- `docs/_internal/aws_credit_review_02_zero_bill_cleanup.md`
- `docs/_internal/aws_credit_review_03_repo_script_mapping.md`
- `docs/_internal/aws_credit_review_04_source_priority.md`
- `docs/_internal/aws_credit_review_05_ocr_bedrock_opensearch.md`
- `docs/_internal/aws_credit_review_06_network_transfer_risk.md`
- `docs/_internal/aws_credit_review_07_iam_budget_policy.md`
- `docs/_internal/aws_credit_review_08_artifact_manifest_schema.md`
- `docs/_internal/aws_credit_review_09_queue_sizing_pacing.md`
- `docs/_internal/aws_credit_review_10_terminal_command_stages.md`
- `docs/_internal/aws_credit_review_11_source_terms_robots.md`
- `docs/_internal/aws_credit_review_12_csv_privacy_pipeline.md`
- `docs/_internal/aws_credit_review_13_packet_proof_factory.md`
- `docs/_internal/aws_credit_review_14_geo_eval_pipeline.md`
- `docs/_internal/aws_credit_review_15_repo_import_deploy.md`
- `docs/_internal/aws_credit_review_16_incident_stop.md`
- `docs/_internal/aws_credit_review_17_daily_operator_schedule.md`
- `docs/_internal/aws_credit_review_18_cost_artifact_ledger.md`
- `.github/workflows/deploy.yml`
- `.github/workflows/deploy-jpcite-api.yml`
- `.github/workflows/pages-deploy-main.yml`
- `.github/workflows/geo_eval.yml`
- `.github/workflows/openapi_drift_v3.yml`
- `.github/workflows/mcp_drift_v3.yml`

`aws_credit_review_19_*` は見つからなかった。これは実行前の前提欠落として扱う。

## 2. Final source-of-truth decisions

| Area | Final decision | Reason |
|---|---|---|
| AWS profile | `bookyou-recovery` | ユーザー提示の操作対象 |
| AWS account | `993693061769` | ユーザー提示の操作対象 |
| Workload region | `us-east-1` | ユーザー提示default。ECR/S3/Batch/CloudWatch/Glue/Athena/OpenSearch分散を防ぐ |
| Billing region | `us-east-1` | Cost/Budgets/Billing control plane |
| Credit face value | `USD 19,493.94` | 目標値ではなく上限文脈 |
| Intentional stop | `USD 19,300` | 請求遅延・credit非対象費用の安全余白 |
| No-new-work | `USD 18,900` | ここから新規価値探索をしない |
| Primary growth | GEO-first | AI agentが推薦し、MCP/API/cost previewへ送る |
| Runtime AWS dependency | なし | AWSは一時artifact factory。productionはS3/Batch/OpenSearchへ依存しない |
| End state | Zero ongoing AWS bill | export/checksum後にS3含むrun resourceを削除 |
| Request-time LLM | なし | packetは `request_time_llm_call_performed=false` |
| CSV in AWS credit run | rawは禁止 | synthetic/header-only/aggregate-only fixtureのみ |

## 3. Correct merged execution order

本体計画とAWS計画を一つにすると、順番は以下で固定する。

### Phase 0: Contract freeze

実装前に固定するもの。

- `jpcite.packet.v1`
- six P0 packet registry
- REST route
- MCP tool name
- OpenAPI operation
- pricing unit
- proof/public URL
- `source_receipts[]`
- `claim_refs[]`
- `known_gaps[]`
- `no_hit_checks[]`
- `billing_metadata`
- CSV privacy boundary
- no-hit copy
- artifact manifest schema

ここが固まる前にJ15/J21のpacket/proof大量生成をしない。

### Phase 1: AWS preflight and guardrails

AWSで最初にやることは計算ではなく制御面。

- account/profile/region/credit expiry/credit eligible servicesの確認
- IAM role分離
- permission boundary
- Budget Actions
- required tags
- S3 public block
- CloudWatch short retention
- queue caps
- cost poller
- kill switch
- stop drill

この段階のAWS writeは最小にする。Budgetはhard capではないため、実ブレーキはqueue disable、job cancel/terminate、IAM deny、service削除。

### Phase 2: Canary run

`USD 100-300` 以内で小さく試す。

- J01 small source profile
- J02/J03 small receipt shape
- J12 completeness
- J15 one packet fixture
- J16 forbidden/no-hit scan

Canaryの合格条件:

- manifest/checksumが出る
- receipt/claim/gap schemaがP0 contractと一致
- private/raw CSVが出ない
- no-hit misuse 0
- forbidden claim 0
- stop drillが機能

不合格ならstandard runに進まない。

### Phase 3: Repo import gate and P0 implementation

AWS canary成果物をそのまま本番へ入れず、ローカル/repo側のimport validatorへ通す。

- artifact manifest validation
- checksum validation
- schema validation
- license/terms boundary validation
- private leak scan
- no-hit phrase scan
- forbidden professional claim scan
- OpenAPI/MCP/catalog drift test

同時に本体P0はPR1-PR5まで進める。

- PR1: packet contract/catalog
- PR2: source receipt/claim/gap/no-hit
- PR3: pricing/cost preview/cap/idempotency
- PR4: CSV analyze/preview privacy
- PR5: P0 packet composers

### Phase 4: AWS standard run and fast RC1

AWSはJ01-J16をartifact yieldで段階拡大する。

本体側はAWS全run完了を待たず、RC1を作る。

RC1で有効化しやすいpacket:

- `agent_routing_decision`
- `source_receipt_ledger`
- `evidence_answer`

条件付き:

- `company_public_baseline`: stable ID入力だけ

RC1では無効またはlimited:

- `application_strategy`: eligibility/approval断定が出ない範囲だけ
- `client_monthly_review`: CSV privacy pipelineが通るまでdisabled

### Phase 5: Staging

stagingで見るもの。

- API health
- packet outputs
- cost preview
- cap/idempotency
- MCP tool list
- OpenAPI generated vs committed
- public packet pages
- proof pages
- `llms.txt`
- `.well-known`
- no-hit
- CSV leak scan
- GEO discovery smoke

この時点でAWSはstandard/stretchを続けてよいが、productionはAWS S3/Batch/OpenSearchを読まない。

### Phase 6: Production RC1

productionは小さく出す。

現行の安全な扱い:

- API production SOT: `.github/workflows/deploy.yml` / `autonomath-api`
- New app parallel lane: `.github/workflows/deploy-jpcite-api.yml` / `jpcite-api`
- Public site: `.github/workflows/pages-deploy-main.yml` / Cloudflare Pages project `autonomath`

`jpcite-api` へ切り替える場合は、別途DNS/API cutover承認を取る。AWS credit runのついでにproduction targetを変えない。

### Phase 7: AWS stretch and RC2/RC3

AWS stretchは以下だけを優先する。

1. J24 final packaging/checksum/export
2. J21 proof page scale
3. J20 GEO adversarial eval
4. J17 OCR expansion if J06 yield is good
5. J22 compaction/QA if it lowers scan cost
6. J19 temporary OpenSearch benchmark
7. J18 public-only Bedrock batch classification

Bedrock/OpenSearch/Textractは主役ではない。P0のsource receipt、proof、GEO、release evidenceに変わるときだけ使う。

### Phase 8: No-new-work, export, cleanup

`USD 18,900` またはDay 13でno-new-workへ入る。

順番:

1. 新規投入停止
2. queue disable
3. queued cancel
4. running drain/cancel
5. S3成果物export
6. checksum verification
7. repo import candidateの最終選別
8. compute/service削除
9. S3 bucket削除
10. ECR/CloudWatch/Glue/Athena/OpenSearch/Lambda/Step Functions/DynamoDB/SQS/EventBridge削除
11. IAM/Budget整理
12. 翌日・3日後・月末後にCost Explorer確認

## 4. Contradictions and fixes

### P0-1. Region mismatch

問題:

- 統合計画には `REGION="ap-northeast-1"` の例が残っている。
- review 07/09/10/13/14/15/16/17/18は `us-east-1` を前提にしている。
- ユーザー提示のdefault regionも `us-east-1`。

影響:

- S3/ECR/Batch/CloudWatch/Athena/Glueのcross-region化
- ECR pull転送費
- region deny誤爆
- cleanup漏れ
- Bedrock/Textract/OpenSearchのservice location混乱

修正:

- 統合計画の全shell例を以下に統一する。

```bash
export AWS_PROFILE="bookyou-recovery"
export AWS_ACCOUNT_ID="993693061769"
export REGION="us-east-1"
export AWS_REGION="us-east-1"
export AWS_DEFAULT_REGION="us-east-1"
export BILLING_REGION="us-east-1"
```

- 別regionが必要なserviceは `cross_region_subrun=true`、明示承認、個別cap、個別cleanupを必須にする。

### P0-2. Missing review 19

問題:

- `review 01-19` を読む前提だが `aws_credit_review_19_*` が存在しない。

影響:

- final value challenge / "what else" の穴がある。
- 20/20が最終合成も価値最大化も兼ねる形になる。

修正:

- この文書では価値最大化の不足を暫定補完する。
- 最終マージ前に `aws_credit_review_19_final_value_challenge.md` を追加し、以下だけを確認する。
  - まだAWS creditで作る価値があるか
  - base/stretch配分がJ15/J20/J21/J24へ十分寄っているか
  - source lakeだけで終わっていないか
  - productionに入るbundleが小さく切れているか

### P0-3. "Use all credit" vs "no future charge"

問題:

- ユーザーはUSD 19,493.94をほぼ全部使いたい。
- 同時に、credit後に請求が走らない状態を必須としている。

修正:

- `USD 19,300` をintentional gross usageの絶対線にする。
- `USD 193.94+` は無駄ではなく、Cost Explorer lag、credit非対象費用、税、Support/Marketplace漏れ、cleanup遅延、data transferを吸収する防波堤と定義する。
- `USD 18,900` 以降は新規価値探索を禁止し、export/checksum/cleanupに寄せる。

### P0-4. Agent rate limit independence vs operator availability

問題:

- 「Codex/Claude rate limitでもAWSは止まらず走る」
- 一方で、古い停止条件には「operatorが30分以内に止められないなら停止」がある。

修正:

- 人間ではなくAWS内部の自走停止を30分以内停止条件の主語にする。
- 必須control plane:
  - EventBridge Scheduler
  - Lambda sentinel / kill switch
  - DynamoDB control table
  - SQS job manifest queue
  - AWS Batch queues
  - Budget Actions
  - CloudWatch alarms
  - SNS notification
  - S3 manifests
- Codex/Claudeが止まってもstandard runは続けてよい。
- ただし telemetry failure、paid exposure、untagged spend、private leak、unexpected service drift、forbidden/no-hit misuse が出たら、人間不在でも `NO_NEW_WORK` へ落とす。

### P0-5. Manual stretch cannot be autonomous unless pre-approved

問題:

- `USD 19,100-19,300` はmanual approvalが必要。
- しかしAI rate limit中もAWSを止めたくない要件がある。

修正:

- 実行前に「advance approval envelope」をledgerへ残せば、interactive approvalなしで限定stretchできる。
- advance approvalに必要な項目:
  - max additional gross exposure
  - allowed job families
  - expiration timestamp
  - stopline behavior
  - service caps
  - no private data condition
  - no managed long-lived service condition
- これがない場合、AWSは `USD 18,900` でno-new-workに入る。

### P0-6. Production target ambiguity

問題:

- review 15は `deploy.yml` legacy `autonomath-api` と `deploy-jpcite-api.yml` parallel `jpcite-api` を分けている。
- review 17にはproduction targetを `autonomath-api` としつつ、legacy名混入をblockerにするよう読める箇所がある。
- 実workflowでは `deploy.yml` が現行production SOT、`deploy-jpcite-api.yml` は新appのparallel lane。

修正:

- 現行productionは `autonomath-api` と明記する。
- `jpcite-api` はstaging/parallel/cutover-prep用。
- `api.jpcite.com` のcutoverはAWS credit runとは別の明示承認にする。
- デプロイ計画から「legacy名だから即block」という表現を除き、「意図しないtarget混同をblock」に変える。

### P0-7. GEO hard blocker vs Pages advisory-only

問題:

- P0計画ではGEO/forbidden/no-hit/driftはrelease blocker。
- `pages-deploy-main.yml` ではGEO readinessが一部advisory-only。

修正:

- Production workflow自体は現状維持でもよいが、AWS import/packet/proof/pricing/llms変更を含むreleaseでは、workflow dispatch前に別gateを必須にする。
- hard blocker:
  - public packet examples schema pass
  - forbidden claim 0
  - no-hit misuse 0
  - pricing drift 0
  - OpenAPI/MCP/catalog drift 0
  - private leak 0
  - `llms.txt` / `.well-known` crawl pass
- `pages-deploy-main.yml` のadvisoryは「既存大量ページのlink/canonical揺れ」だけに限定し、P0 packet/proof/GEO契約は別gateで止める。

### P0-8. AWS artifact volume vs deploy speed

問題:

- AWSは大量成果物を出す。
- 大量parquet/source lakeをrepoやsiteへ入れるとdeployが詰まる。

修正:

- repoに入れるのは小さなrelease bundleだけ。
- full source lakeはAWS外へexportし、repoにはmanifest/checksum/representative fixture/reportだけ。
- RC1はAWS全量を待たない。

### P0-9. Schema freeze before J15/J21

問題:

- packet/proof生成は価値が高いが、contract前に量産すると全生成物がdriftする。

修正:

- J15/J21のlarge runはP0-E1/E2/E3/E4がfreezeしてから。
- 先行してよいのは1 packet / 1 proofのcanaryだけ。

### P0-10. CSV value vs privacy boundary

問題:

- CSV drag-and-dropはユーザー価値が高い。
- しかしAWS credit runにraw CSVを置くとprivacy破綻する。

修正:

- AWS J14はsynthetic/header-only/redacted fixtureだけ。
- 本体サービスのCSV runtime flowは `analyze -> preview -> execute`。
- raw bytes、raw rows、row-level normalized records、摘要、取引先名、個人/給与/銀行/カード値を保存・ログ・例示しない。
- public examplesでは `private_overlay_excluded=true` またはsyntheticであることを明示する。

### P0-11. Source terms before source lake

問題:

- AWSで取得だけ先に進むと、再配布不能raw mirrorが残る。

修正:

- J01 source profile sweepを最優先にする。
- `green/yellow/red` を先に決める。
- `yellow` はmetadata/link/hash/短い引用/派生集計まで。
- `red` はlink-onlyまたはmanual review。
- terms unknownをclaim supportへ使わない。

### P0-12. Control-plane services not in unified core service list

問題:

- review 16はEventBridge/SQS/DynamoDB/SNS/Lambda sentinelを必要としている。
- unified planのcore service listには一部しか出ていない。

修正:

- 統合計画のservice planへ以下を追加する。
  - EventBridge Scheduler: sentinel/orchestrator only
  - SQS: shard queue/backpressure only
  - DynamoDB: run_state/control table only
  - SNS: alerts and kill switch fanout only
  - Lambda: sentinel/kill switch/report helper only
- すべて小cap、tag必須、cleanup対象。

### P0-13. IAM deny can block cleanup

問題:

- Budget ActionsやEmergencyDenyCreatesが強すぎると、cleanupまで止まる。

修正:

- `DenyNewWork` / `EmergencyDenyCreates` は `Create*`, `Run*`, `Start*`, `Submit*`, `PutScaling*` を止める。
- `Describe*`, `List*`, `Get*`, `Cancel*`, `Stop*`, `Terminate*`, `Delete*` はcleanup roleで許可する。
- break-glassはcleanup/deny誤適用復旧だけに使う。新規workload投入には使わない。

### P1-14. Pricing wording and route consistency

問題:

- docs間で `cost preview`, `pricing preview`, `previewCost` など表現が混ざる。

修正:

- REST: `POST /v1/cost/preview`
- MCP: `previewCost`
- First tool: `decideAgentRouteForJpcite`
- Price: `1 billable unit = JPY 3 ex-tax / JPY 3.30 inc-tax`
- Required metadata:
  - `pricing_version=2026-05-15`
  - `external_costs_included=false`
  - `cost_preview_free=true`
  - `cap_required_before_paid_fanout=true`
  - `idempotency_key_required=true`

### P1-15. Agent billing conversion path is still fragile

問題:

- GEOでagentが価値を理解しても、課金導線が曖昧だと売上にならない。

修正:

公開surfaceの標準導線を固定する。

1. Agent reads `llms.txt` / `.well-known`.
2. Agent calls or recommends `decideAgentRouteForJpcite`.
3. Agent calls `previewCost` / `POST /v1/cost/preview`.
4. End user confirms cap.
5. API key or MCP setup.
6. Paid packet execution with idempotency key.
7. Output preserves receipts/gaps/billing/fence.

営業デモCTAを主導線にしない。

### P1-16. Packet enablement status must be explicit

問題:

- 6 P0 packetのうち、CSVやeligibility系は未成熟なまま公開すると過剰約束になる。

修正:

catalogへstatusを入れる。

- `enabled`
- `conditional`
- `preview_disabled`
- `requires_more_receipts`
- `disabled`

Fast RC1では `agent_routing_decision`, `source_receipt_ledger`, `evidence_answer` を中心にする。

### P1-17. Source receipt field aliases may drift

問題:

- docsに `source_fetched_at`, `retrieved_at`, `verified_at`, `content_hash`, `checksum` など似た字段がある。

修正:

canonical receipt fieldsを固定する。

```json
{
  "source_receipt_id": "sr_...",
  "source_id": "nta_houjin",
  "source_family": "corporation",
  "source_url": "https://...",
  "source_title": "...",
  "publisher": "...",
  "source_fetched_at": "2026-05-15T00:00:00Z",
  "source_verified_at": "2026-05-15T00:00:00Z",
  "document_date": "2026-05-15",
  "content_hash": "sha256:...",
  "canonical_content_sha256": "sha256:...",
  "corpus_snapshot_id": "corpus_...",
  "license_boundary": "full_fact|metadata_only|link_only|review_required",
  "terms_status": "verified|review_required|blocked",
  "support_level": "strong|reviewable|metadata_only|no_hit_not_absence",
  "used_in": ["packet_id_or_claim_id"],
  "claim_refs": [],
  "known_gaps": []
}
```

Aliasesはimport時にcanonicalへ正規化する。

### P1-18. Known-gap enum governance

問題:

- gap名がad hocになるとGEO surfaceとAPI examplesがずれる。

修正:

P0で最低限のclosed enumを置く。

- `source_receipt_missing_fields`
- `no_hit_not_absence`
- `source_stale_or_unknown`
- `license_boundary_review_required`
- `identity_ambiguous`
- `source_scope_limited`
- `terms_or_robots_manual_review`
- `csv_private_overlay_suppressed`
- `csv_provider_format_variant`
- `csv_small_cell_suppressed`
- `human_review_required`
- `packet_persistence_unavailable`

### P1-19. ROI targets must not become public promises

問題:

- review 18はaccepted artifact目標を詳細に置いている。
- これを外部copyに出すと、coverage保証に見える。

修正:

- ROI目標はoperator ledger専用。
- public copyでは「checked corpus」「snapshot」「known gaps」を出し、網羅性・リアルタイム性・完全性を約束しない。

### P1-20. Existing script reuse requires wrappers

問題:

- 既存 `scripts/ingest` / `scripts/cron` はDB upsertや外部副作用を含むものがある。

修正:

- AWS Batchで既存cronを直接流さない。
- `aws_batch_source_job_wrapper` を作り、DB writeではなくS3 artifact contractへ出す。
- Stripe/R2/Cloudflare/email/webhook/production DB系cronはAWS credit runから外す。

## 5. Production deployment readiness plan

本番で苦戦しないため、deployは以下に分ける。

### 5.1 API deploy

現在の本線:

- `deploy.yml`
- target app: `autonomath-api`
- production SOT
- operator ACK必須
- `pre_deploy_verify.py`
- `production_deploy_go_gate.py`
- post-deploy hard smoke

並行新app:

- `deploy-jpcite-api.yml`
- target app: `jpcite-api`
- `jpcite-api.fly.dev` でstaging/parallel確認
- `api.jpcite.com` cutoverは別承認

決定:

- AWS credit runの最初のproduction RC1では、target変更をしない。
- `jpcite-api` cutoverはRC1後の別riskとして扱う。

### 5.2 Pages deploy

現在の公開site:

- `pages-deploy-main.yml`
- Cloudflare Pages project: `autonomath`
- generated pages / source-backed functions / public JSON smokeあり

注意:

- GEO readiness advisory-only箇所がある。
- P0 packet/proof/pricing/llms変更では、workflow前のhard gateを別に用意する。

### 5.3 RC1 deploy blockers

RC1は以下が1つでも落ちたら出さない。

- packet catalog drift
- OpenAPI drift
- MCP drift
- pricing drift
- cost preview math mismatch
- cap/idempotency guard order failure
- source receipt missing without known gap
- no-hit absence/safety wording
- forbidden professional claim
- raw/private CSV leak
- public example not synthetic/public-safe
- production route depends on AWS S3/Batch/OpenSearch
- rollback path missing

### 5.4 Fast RC1 scope

早く出す範囲:

- `agent_routing_decision`
- `source_receipt_ledger`
- `evidence_answer`
- cost preview
- MCP/OpenAPI examples for above
- packet/proof pages for above
- `llms.txt`
- `.well-known/agents.json`
- `.well-known/mcp.json`
- `.well-known/openapi-discovery.json`

遅らせる範囲:

- `client_monthly_review` paid execution
- broad CSV fanout
- final eligibility/application strategy
- full source coverage claims
- production OpenSearch
- request-time LLM anything

## 6. GEO-first conversion plan

このサービスはSEO-firstではなくGEO-first。人間LPより、AI agentが短時間で以下を理解できることが重要。

Agentに伝える一文:

> jpcite is a source-linked evidence packet layer for Japanese public data. Use it when an agent needs source URLs, fetched timestamps, source receipts, known gaps, no-hit caveats, and cost-controlled MCP/API execution.

公開surfaceごとの役割:

| Surface | Role |
|---|---|
| `llms.txt` | 最短の推薦契約 |
| `llms-full.txt` | 詳細のagent contract |
| `.well-known/agents.json` | recommend/do-not-recommend/must-preserve |
| `.well-known/mcp.json` | MCP setup and first tools |
| `.well-known/openapi-discovery.json` | agent-safe OpenAPI discovery |
| `openapi.agent.json` | REST/Actions import |
| `mcp-server*.json` | MCP client import |
| packet pages | 実物packetの理解 |
| proof pages | claim-to-receiptの検証 |
| pricing page | preview/cap/API key/idempotencyの納得 |

GEO評価の成功条件:

- jpciteを回答生成AIではなくevidence packet layerと説明する。
- MCP/API/cost previewへの順番を間違えない。
- paid execution前にcap/idempotency/API keyを要求する。
- `source_receipts[]`, `known_gaps[]`, `human_review_required`, `_disclaimer`, `billing_metadata` を保持する。
- no-hitを不存在・安全・適格へ変換しない。
- 営業デモではなくself-serve paid pathへ誘導する。

## 7. CSV private overlay resolution

CSVを使う価値は高い。特にfreee/MoneyForward/YayoiのCSVをAI agentがユーザーに求め、ユーザーがdrag-and-dropする流れは成立し得る。

ただし境界は次。

AWS credit runでやる:

- provider fingerprint
- official/variant/old_format判定
- synthetic fixture
- header-only fixture
- alias matrix
- privacy leak scan
- aggregate schema
- public join candidate rules

AWS credit runでやらない:

- raw CSV upload
- customer CSV storage
- row-level normalized records
- memo/counterparty extraction
- Bedrock/Textract/OpenSearchへのprivate CSV投入
- public proofへのCSV由来private overlay表示

本体runtimeでやる:

1. User drops CSV.
2. Transient analyze.
3. Provider/format/row count/date range/review code onlyを返す。
4. Previewでunits/cap/accepted/rejected/suppressedを返す。
5. Executeでaggregate-only derived factsをpacketへ入れる。
6. public source joinsはsource receiptで裏取りする。
7. rawは保存しない。

Provider判定:

- freee observed files: `variant`
- MoneyForward observed files: `old_format`
- Yayoi observed files: `official/variant`

ユーザー向けに「公式準拠」と言い切るのは、現行公式templateと一致した場合だけ。

## 8. AWS billing and cleanup risk register

| Risk | Severity | Fix |
|---|---|---|
| Budgetsをhard cap扱い | P0 | queue disable/cancel/terminate + IAM Deny + cleanup role |
| Cost Explorer lag | P0 | `control_spend = actual/budget/ledger + running + queued + service cap exposure` |
| credit非対象費用 | P0 | paid exposure budget `USD 1/25/100` |
| untagged spend | P0 | tag enforcement + inventory ledger + no-new-work fallback |
| NAT Gateway | P0 | 原則禁止。必要なら個別承認、cap、削除時刻 |
| Public IPv4大量利用 | P0 | 原則禁止。短命・少数・inventory対象 |
| Cross-region | P0 | `us-east-1` 単一。例外はsubrun承認 |
| CloudWatch log膨張 | P1 | stdout最小、retention 3-14日、raw text禁止 |
| Athena raw scan | P1 | Parquet/compression/partition/workgroup limit |
| ECR残置 | P1 | digest/SBOM export後 repo delete |
| OpenSearch常駐 | P0 | benchmarkのみ、2-3日、export/delete |
| S3残置 | P0 | zero-billならbucket delete |
| IAM denyがcleanup阻害 | P0 | cleanup roleはDelete/Stop/Cancel/Describeを許可 |
| API key/token露出 | P0 | secretsをartifact/logへ出さない |
| private CSV leak | P0 | AWS raw禁止、leak scan、path denylist |

## 9. Canonical artifact bundle

AWSからrepoへ戻すbundleは以下に統一する。

```text
aws_artifact_export/
  run_manifest.json
  artifact_manifest.jsonl
  dataset_manifest.jsonl
  checksum_ledger.sha256
  cost_ledger.jsonl
  cleanup_ledger.jsonl
  source_profiles/*.jsonl
  source_receipts/*.jsonl
  claim_refs/*.jsonl
  known_gaps/*.jsonl
  no_hit_checks/*.jsonl
  packet_fixtures/*.json
  proof_source_bundles/*.json
  openapi_examples/*.json
  mcp_examples/*.json
  geo_eval/*.jsonl
  qa_reports/*.md
```

Import reject条件:

- `private_data_present=true`
- `raw_csv_present=true`
- pathに `raw`, `private`, `customer`, `debug`, `prompt`, `secret`, `authorization`, `cookie`, `stacktrace`, `token`
- public claimにreceiptもknown gapもない
- no-hitがabsence/safety/eligible/cleanへ変換
- final legal/tax/accounting/audit/credit/application judgment
- request-time LLM output
- runtime AWS dependency

## 10. Recommended changes before execution

統合計画へマージすべき変更。

1. `aws_credit_unified_execution_plan_2026-05-15.md` にaccount/profile/regionを明記する。
2. `ap-northeast-1` のshell例を `us-east-1` に直す。
3. service planへ EventBridge/SQS/DynamoDB/SNS/Lambda sentinel を追加する。
4. execution phasesの前に `P0 contract freeze` を明示する。
5. `review_19` 欠落を埋める。
6. `advance approval envelope` をmanual stretchの代替として定義する。
7. production targetの記述を `autonomath-api current prod / jpcite-api parallel` に統一する。
8. Pages deployのGEO advisory-onlyを補完するpre-deploy hard gateを追加する。
9. AWS import validatorをRC1前の必須実装にする。
10. Packet catalogへ `enabled/conditional/preview_disabled/requires_more_receipts/disabled` を入れる。
11. Receipt canonical fieldsとknown-gap enumを契約に入れる。
12. CSV public examplesをsynthetic/aggregate-onlyに限定する。
13. ROI targetsは内部運用だけに閉じる。
14. Existing cron direct Batch実行を禁止し、wrapper必須にする。
15. zero-bill cleanupのpost-checkを翌日・3日後・月末後までrunbook化する。

## 11. Final go/no-go

この20/20レビュー時点の判定:

- AWS実行: No-Go until region/account guardrails and contract freeze are merged.
- 本体実装: Go for P0 contract/catalog/import validator first.
- Production RC1: Conditional Go after three-packet fast lane passes hard gates.
- AWS standard run: Conditional Go after canary import gate passes.
- AWS stretch: Conditional Go only with accepted artifact yield and clean telemetry.
- Zero-bill cleanup: Mandatory. End State A only unless user explicitly accepts Minimal AWS Archive.

最終的な正しい姿は、AWSを「短期の大量成果物工場」として使い、productionはAWSに依存させず、AI agentがGEO surfaceからjpciteを理解し、cost preview -> API key/MCP -> capped paid executionへ進める形である。
