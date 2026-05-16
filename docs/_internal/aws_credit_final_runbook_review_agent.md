# AWS credit final runbook structure review

Date: 2026-05-15  
Reviewer lane: final Markdown structure review for the AWS operator CLI / terminal pasteback  
Scope: review only. No AWS execution, no implementation, no resource creation.

## 0. 結論

現状の `aws_credit_cli_runbook_agent.md` は、全体として「守りを先に置く」構成になっているが、このまま最終RunbookとしてAWS担当CLIに貼るにはまだ危ない。主な理由は、支出上限の数値が文書間で揺れていること、Budgetsを実質的な停止装置のように読める箇所があること、Batch/S3/IAM/KMSの前提が未確定のままコマンド化されていること、そして「jpcite価値に残る成果物が増えているか」で止める条件が弱いこと。

最終Runbookは、実行コマンド集ではなく、次の順序に再構成するべき。

- `Operator contract`: 目的、禁止事項、停止ライン、成果物定義を最初に固定する。
- `Manual console gate`: credit対象サービス、期限、通知先、Organizations/management account、Cost Allocation Tag有効化をCLI前に確認する。
- `Read-only audit`: 既存支出、既存リソース、既存budget、リージョン、quotaを確認する。
- `Guardrail creation`: Budgets、SNS/email確認、deny policy/SCP、bucket baseline、log retention、Batch queueだけを作る。
- `Stop drill`: 空queueで停止スクリプトをテストし、止められることを確認してからsmokeへ進む。
- `USD 100-300 smoke`: tag/cost/service mix/artifact manifestを確認する。
- `Scaled run`: 明示manifestを持つjobだけを投入し、hourly ledgerで続行判定する。
- `Drain/cleanup`: queue停止、transient resource削除、S3成果物とledger保存。

## 1. 最終Runbookへ必ず入れる修正

- 支出ラインを一つに統一する。現在は `18,300-18,700 target`, `18,900 stop`, `19,000 upper`, `800-1,200 buffer`, `493.94 buffer` が混在している。最終Runbookでは `USD 18,300 slowdown`, `USD 18,700 no-new-work`, `USD 18,900 emergency stop`, `USD 19,493.94は絶対に使い切らない` に統一する。
- `18,900` は目標ではなく緊急停止線と明記する。`19,493.94 - 18,900 = 593.94` しか残らず、当初の `800-1,200 buffer` と矛盾する。
- Budget構成を一本化する。`jpcite-credit-run-watch-*` の単純monthly budgetsと、`gross burn / paid exposure` のcustom period budgetsが競合している。最終Runbookでは `gross burn custom budget` と `paid exposure custom budget` を正とし、account-level monthly budgetは補助にする。
- 月初からのCost Explorer集計と、credit run開始日からの集計を分ける。現状の `Start=$(date -u +%Y-%m-01)` は、2026-05-15以前の既存支出があるとrun消化額と混ざる。
- `date -u -v+1d` はmacOS専用なので、AWS担当CLIのOSを確定するか、`START_DATE=2026-05-15` / `END_DATE=2026-05-30` のように固定変数へ置き換える。
- `ap-northeast-1` をworkload regionにするなら、SCP/region guardrail側の許可リージョンも `ap-northeast-1` と `us-east-1` に揃える。現状のguardrail案には `us-west-2` があり、本文と不一致。
- Budgets/Budget Actionsはhard capではない、と各実行フェーズの冒頭に再掲する。Budgets更新は遅延するため、queue disable/cancel/terminateを主停止手段にする。
- Forecast alertは短期・新規利用では弱い補助指標として扱う。停止条件は `actual`, `service mix`, `untagged spend`, `paid exposure`, `artifact value` を主にする。
- SNS/email通知は「作成」ではなく「購読確認完了」までをgateにする。確認メール未承認ならrun禁止。
- Cost allocation tagは有効化直後に過去コストへ効かないため、tag-filtered costだけで支出判断しない。unfiltered account/service costを必ず並走させる。

## 2. AWS担当CLIへ貼る構成上の危険

- 変数未置換のまま実行できる箇所が多い。`BATCH_SUBNET_IDS`, `BATCH_SECURITY_GROUP_IDS`, `BUDGET_ACTION_ROLE_ARN`, `TARGET_OPERATOR_ROLE_NAME`, `DENY_POLICY_ARN` は、未置換なら即停止するpreflightを入れる。
- `aws budgets create-budget` は既存budgetがあると失敗する。最終Runbookは `describe -> create or update -> verify` の形にし、途中で `set -e` により半端に止まる状態を避ける。
- Fargate/Batch queue作成だけではjob実行の安全性は保証されない。job definition側に `executionRoleArn`, `jobRoleArn`, `timeout.attemptDurationSeconds`, log retention, network egress方針、readonly/rootfs方針が必要。
- Batch queue名が文書間で揺れている。`jpcite-source-crawl` 系と `jpcite-credit-fargate-spot-short` 系のどちらを使うか最終Runbookで一つに統一する。
- Batch停止スクリプトはBatch外のECS task、Step Functions、CodeBuild、OpenSearch、Glue crawler、NAT Gatewayを止めない。これらを使うなら、作成セクションと対になる停止/削除セクションを必ず入れる。
- `update-compute-environment --compute-resources maxvCpus=0` は環境種別や状態で失敗する可能性がある。最終Runbookでは「queue disable + job cancel/terminate」を第一停止手段にし、compute environment更新はbest-effort扱いにする。
- SCP/IAM deny policyで `ecs:UpdateService` や `autoscaling:UpdateAutoScalingGroup` を全面Denyすると、desired countを0にする停止操作まで巻き込む恐れがある。denyは「新規作成・スケールアップ」を止め、「スケールダウン・停止・Cost/Billing確認」は許可する形にする。
- `CreateFunction` や `UpdateFunctionConfiguration` のDenyも、停止用Lambdaやscheduler無効化を妨げないか確認する。
- `Object Ownership bucket-owner-enforced`, TLS-only bucket policy, KMS必須PutObject, delete権限分離がCLI runbookに不足している。security/privacy文書の要件をS3作成セクションへ昇格する。
- CLI runbookのS3暗号化は `AES256` だが、security/privacy文書はSSE-KMSを要求している。最終RunbookではKMS keyを用意しないなら「KMSなしの理由」と「private overlayを扱わない」制限を明記する。

## 3. 危険な出費・請求リスク

- NAT Gatewayが最大の見落とし候補。private subnetでFargate/Batchを動かすならNAT hourly + data processingが発生する。`NAT Gatewayを使う/使わない`, `public IP assignment`, `VPC endpoint`, `S3 gateway endpoint` の方針を開始前gateにする。
- Textract/OCRはページ数と失敗率で急に高くなる。PDF/OCRは全量投入禁止にし、`page_count cap`, `per-source cap`, `accepted extraction rate`, `manual review backlog cap` を満たす場合だけ増やす。
- OpenSearchは短期検証でも消し忘れが高額化しやすい。最終Runbookでは原則 `OpenSearch禁止`、使う場合だけ `domain spec`, `max hours`, `export path`, `delete command`, `post-delete verify` を揃える。
- Glue/Athenaはraw JSON/HTML/PDFを直接scanすると無駄な費用になりやすい。Parquet化とpartition確認が終わるまでAthena探索queryを制限する。
- CloudWatch Logsは大量stdoutで費用化する。log group retention、payload禁止、stdout size cap、error sample上限をjob投入gateにする。
- S3 versioningは有用だが、raw大量更新と組み合わさると残存費用になる。noncurrent version expirationだけでなく、temporary/raw/hash_only prefixのcurrent object lifecycleも決める。
- Cost Explorer hourly/resource-level設定は有料・反映遅延がある。最終Runbookでは「使うなら理由を書く」、通常停止判断には使わない。
- Marketplace、Support upgrade、Route 53 domain、Savings Plans、Reserved Instances upfront、Professional Services、Training/Certificationはcredit対象外または不向きとして禁止リストに固定する。
- Bedrock/外部LLMは原則禁止。jpciteの価値は `request_time_llm_call_performed=false` の事前証跡であり、credit消化のための生成AI推論は目的とずれる。

## 4. 足りない停止条件

- `accepted artifact` が増えない時の停止条件を入れる。例: 2時間連続で `source_receipt`, `proof page`, `packet example`, `eval report` のaccepted件数が増えない場合、新規job投入停止。
- `failure rate` 条件を入れる。例: job failure率10%、retry率15%、parse failure率が事前閾値を超えたらscale up禁止。
- `review backlog` 条件を入れる。OCR/抽出候補が人間レビュー待ちに積み上がるだけなら、追加抽出を止める。
- `private leak scan` が失敗したら公開候補生成を止める。CSV/tenant/private overlayが混ざる可能性がある成果物はAWS内に閉じる。
- `no_hit` 誤用条件を入れる。`source_unavailable`, `parse_failed`, `snapshot_stale`, `permission_limited` を `no_hit` に変換する出力が出たら該当job familyを止める。
- `forbidden claim` 条件を入れる。`eligible`, `approved`, `safe`, `audit complete`, `creditworthy`, `tax correct`, `legal conclusion` 相当がproof/packet/GEO出力に出たら該当生成を止める。
- `paid exposure` を入れる。credit控除後の現金請求がUSD 1で調査、USD 25で新規停止、USD 100でabsolute stop。
- `untagged spend` は金額に関係なく停止候補にする。タグ漏れは帰属不能な支出なので、原因が分かるまでscale禁止。
- `service mix drift` を入れる。想定外サービスがUSD 100を超える前に停止し、Marketplace/Support/commitment系は金額ゼロで即停止。
- `night/weekend unattended` 条件を入れる。人間が30分以内に停止できない時間帯は、新規大規模job投入を禁止する。

## 5. jpcite価値に繋がらない作業

- credit消化だけを目的にしたCPU burn、広すぎる負荷試験、GPU学習、長期OpenSearch運用、VC/営業資料生成は削る。
- 「全PDFをOCRする」ではなく、「P0 packet/proof/GEOに必要なsource receiptが増えるPDFだけ」に限定する。
- 汎用的なsource lake拡張は、`source_receipt[]`, `known_gaps[]`, `proof pages`, `agent-safe OpenAPI/MCP`, `GEO eval` に接続しないものを後回しにする。
- load testは本番規模の夢ではなく、packet/proof/discovery pagesがcrawl/render/parseできることの確認に限定する。
- CSV private overlayはpublic proofを増やす材料ではない。使うならsynthetic/header-only/aggregateだけで、raw CSV由来の行・摘要・取引先・個人名をAWS成果物に残さない。
- Static page生成はSEOページの量産ではなく、agentが安全にjpciteを選べるproof surfaceに限定する。
- Search/retrieval index実験は、exportできる評価結果とsource receipt改善が残らないなら実行しない。

## 6. 最終Runbookの必須gate

- `Credit gate`: Billing console Creditsで、残高USD 19,493.94、期限、eligible services、account/organization scopeを確認し、AWS担当CLIの出力メモに残す。
- `Billing gate`: Cost Explorer/Budgets権限、management account要否、Organizations/SCP適用範囲を確認する。
- `Notification gate`: alert emailまたはSNS subscriber確認済み。
- `Region gate`: workload regionは原則 `ap-northeast-1`、billing/controlは `us-east-1`。例外は明示承認。
- `Network gate`: NAT Gatewayを使うなら日次上限と停止手順を持つ。なければS3 endpoint/public IP方針を明記する。
- `S3 gate`: private buckets, Block Public Access, Object Ownership, TLS-only, SSE-KMS or explicit no-private-data limitation, lifecycle, delete権限分離を確認する。
- `IAM gate`: stop操作をDenyしないsoft brake policy、break-glass role、Budget Action role trust/permissionsを確認する。
- `Batch gate`: queue caps、job timeout、retry cap、log retention、execution/job role、artifact manifest pathが揃うまでjob投入禁止。
- `Stop drill gate`: 空queueまたはdummy jobでdisable/cancel/terminate手順を検証し、結果をledgerへ残す。
- `Smoke gate`: USD 100-300以内で、cost tag、service mix、artifact manifest、leak scan、stop scriptを確認する。
- `Scale gate`: 直近hourly ledgerで支出、成果物、失敗率、レビュー待ち、forbidden claimがすべて許容内の時だけcapを上げる。
- `Publication gate`: S3内artifactは公開候補にすぎない。public syncは別のprivacy/claim review後に限定する。

## 7. CLI pastebackの文面修正案

最終Runbookの冒頭に、AWS担当CLIへ次の制約をそのまま渡す。

```text
You are the AWS operator for the jpcite credit run. This is not a spend-maximization task. Do not create workloads until credit eligibility, billing access, notifications, budgets, bucket controls, queue caps, and stop drill are confirmed.

Target: useful eligible gross usage up to USD 18,300-18,700. USD 18,700 means no new workload. USD 18,900 means emergency stop. Never target the full USD 19,493.94.

Allowed work must leave durable jpcite assets: source receipts, known gaps, proof pages, packet examples, GEO/eval reports, safe OpenAPI/MCP/discovery artifacts, and final ledgers. Do not run CPU burn, GPU training, long-lived search, Marketplace subscriptions, support upgrades, commitments, request-time LLM calls, or private CSV persistence.

Every workload job must have: owner, queue, max cost estimate, timeout, retry cap, input manifest, output S3 prefix, accepted artifact definition, privacy class, and stop condition.

If untagged spend, paid exposure, unexpected service spend, private leakage, forbidden claims, NAT/data-transfer drift, or artifact stagnation appears, stop new work first and report before continuing.
```

## 8. References checked

- AWS Budgets update timing: AWS docs state Budgets information is updated up to three times daily, typically 8-12 hours after the previous update.  
  https://docs.aws.amazon.com/cost-management/latest/userguide/budgets-managing-costs.html
- AWS Budgets Actions scope: Budget Actions can apply IAM policies, apply SCPs, or target specific EC2/RDS instances; they are not a universal hard cap for all services.  
  https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/budgets-controls.html
- AWS Batch Fargate CLI docs: compute environment creation requires explicit network resources such as subnets/security groups; job safety still depends on job definitions and roles.  
  https://docs.aws.amazon.com/cli/latest/reference/batch/create-compute-environment.html
- AWS Promotional Credit terms: credits apply only to eligible services and generally exclude Marketplace, ineligible Support, Route 53 domain registration/transfer, mining, and upfront fees for Savings Plans/Reserved Instances unless otherwise authorized.  
  https://aws.amazon.com/awscredits/
