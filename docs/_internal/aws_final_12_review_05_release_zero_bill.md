# AWS final 12 review 05/12: production release train and zero-bill connection

作成日: 2026-05-15  
担当: 最終追加検証 5/12 / 本番デプロイ・release train・zero-bill接続  
対象: RC1/RC2/RC3、feature flags、static proof、minimal MCP/API、AWS artifact import、staging/production、rollback、production without AWS、assetization、zero-bill guarantee  
AWS前提: profile `bookyou-recovery` / account `993693061769` / region `us-east-1`  
実行状態: AWS CLI/APIコマンド、AWSリソース作成、削除、本番デプロイは行っていない。ローカル文書精査のみ。

## 0. 結論

判定: **条件付きPASS**。

現行の正本方針は成立する。特に以下は正しい。

- AWSは短期のartifact factoryであり、production runtimeではない。
- productionはAWS全量完了を待たず、RC1を小さく早く出す。
- `runtime.aws_dependency.allowed=false` をproduction hard gateにする。
- zero-billを守るため、外部export/checksum/rollback asset確認後にS3を含むAWS run resourceを削除する。
- `jpcite-api` へのAPI/DNS cutoverはRC1に混ぜず、既存production targetで先に価値を出す。

ただし、単に順番を整理するだけでは不十分。よりスマートにする核心は、**本番展開を「コードdeploy」ではなく、検証済みartifactをfeature flagとmanifestで安全に露出する仕組み**へ変えること。

採用すべき設計は次の6つ。

1. `release_manifest` と `active_dataset_pointer` を本番の正本にする。
2. Feature flagを `visible` / `executable` / `billable` の3層に分ける。
3. AWS artifactは `quarantine -> accepted bundle -> staging -> production` の取引的importにする。
4. RollbackはAWS/S3を使わず、manifest pointerとflagで戻せるようにする。
5. Production smokeはAWS endpoint遮断・S3 URL scan・catalog drift scanを含む自動gateにする。
6. Zero-billは「削除した」ではなく、`external_export_verified`、`production_without_AWS`、`resource_inventory_zero`、`post_teardown_billing_checks_scheduled` までを機械可読ledgerで証明する。

release段階としては、RC1を一つの塊ではなく、次の3段階に分ける。

```text
RC1a: static proof + pricing/docs + GEO discovery
RC1b: free controls + minimal MCP/API
RC1c: limited paid packets with low cap
```

これにより、AWS full runを待たずにproduction価値を出せる。AWSは裏側で走り続け、RC2/RC3候補を作る。productionは検証済みbundleだけをimportする。

本レビューの最終採用アーキテクチャ:

```text
artifact factory lane: AWS generates candidates only
acceptance lane: quarantine, validate, sign, version, bundle
release lane: manifest pointer, flags, static proof, MCP/API, paid caps
rollback lane: previous manifest and dataset pointer, no AWS access
zero-bill lane: external export, teardown ledger, residual checks
```

## 1. 精査した正本・関連文書

主に以下を参照した。

- `docs/_internal/aws_jpcite_master_execution_plan_2026-05-15.md`
- `docs/_internal/aws_final_consistency_10_final_sot.md`
- `docs/_internal/aws_final_consistency_06_release_train.md`
- `docs/_internal/aws_final_consistency_09_post_aws_assets.md`
- `docs/_internal/aws_final_consistency_02_aws_autonomous_billing.md`
- `docs/_internal/aws_final_consistency_04_revenue_packets_pricing.md`
- `docs/_internal/aws_final_consistency_08_playwright_terms.md`
- `docs/_internal/aws_scope_expansion_28_production_release_train.md`
- `docs/_internal/aws_scope_expansion_29_post_aws_assetization.md`
- `docs/_internal/aws_scope_expansion_25_fast_spend_scheduler.md`
- `docs/_internal/aws_credit_review_13_packet_proof_factory.md`
- `docs/_internal/aws_credit_review_15_repo_import_deploy.md`

## 2. 矛盾チェック結果

### C05-01: RC1を一括扱いすると最速productionと矛盾する

判定: **修正済み方針を採用すればPASS**。

問題:

- RC1に static proof、free controls、minimal MCP/API、paid packets、MCP discovery、GEO surface を全部同時に入れると、最小productionが遅くなる。
- paid executionのbilling/cap/idempotency gateで詰まると、static proofやGEO discoveryまで遅れる。
- AWS canary artifactのimport検証が遅れた場合、production全体が待たされる。

採用修正:

RC1を3段階に分ける。

| Stage | 目的 | production露出 | paid execution |
|---|---|---|---|
| RC1a | AI agentに発見させる | static proof、pricing、docs、`llms.txt`、`.well-known` | off |
| RC1b | AI agentが推薦判断できる | route、catalog、cost preview、minimal OpenAPI/MCP | off |
| RC1c | 最小売上を検証する | 3 paid packets、low cap、approval token | on low cap |

RC1aは最も早く出す。RC1bはAPI/MCP drift gateが通ったら出す。RC1cはbilling gateとrollback flagが通ったら出す。

### C05-02: `agent_routing_decision` の有料扱いが一部文書に残る

判定: **矛盾あり。正本では無料controlに固定**。

最終決定:

- `agent_routing_decision` は有料packetではない。
- `jpcite_route` / `jpcite_preview_cost` / catalog は無料control。
- RC1c paid 3 packetsは次に固定する。

```text
company_public_baseline
source_receipt_ledger
evidence_answer
```

理由:

- AI agentが推薦前にroute/cost previewを使うため、入口を有料にするとGEO導線が弱くなる。
- 初回売上検証には `company_public_baseline` が最も自然。
- `source_receipt_ledger` と `evidence_answer` はjpciteの証跡価値を説明しやすい。

### C05-03: feature flagsはdeploy後ではなくdeploy前に必要

判定: **現行方針は概ねOK。ただし順番を強制する**。

問題:

- static proof、free controls、paid packets、MCP discoveryを同じdeployで入れると、障害時に切り分けできない。
- paid executionだけ止めたい場面で、API全体やproof pagesまでrollbackするのは遅い。

採用修正:

feature flagsはRC1aより前に実装する。

必須flag:

```text
proof_pages.static.enabled
api.packet.route.enabled
api.packet.preview_cost.enabled
api.packet.company_public_baseline.enabled
api.packet.source_receipt_ledger.enabled
api.packet.evidence_answer.enabled
mcp.agent_first.enabled
billing.free_preview.enabled
billing.paid_execution.enabled
runtime.aws_dependency.allowed
```

推奨するflag粒度:

| Flag type | 役割 | default |
|---|---|---|
| visibility flag | page/tool/catalogを見せるか | off |
| execution flag | 実行を受けるか | off |
| billing flag | 課金を有効にするか | off |
| cap flag | packet上限をどこまで許すか | lowest |
| kill flag | 問題packetだけ即停止するか | ready |

`runtime.aws_dependency.allowed` はproductionでは常に `false`。このflagをtrueにしないと動かない実装はrelease blocker。

### C05-04: static proofはAWS成果物全部を待つ必要がない

判定: **改善余地あり。RC1aはcanary/verified fixtureで出す**。

より速い案:

- RC1a static proofは、full AWS corpus完了を待たない。
- 既存fixtureまたはAWS canary exportの小さなvalidated bundleだけで出す。
- ただし、public claimに使うpageは `source_receipt`、`claim_refs`、`known_gaps`、`no_hit_not_absence` が揃うものだけにする。
- 不完全なsource familyはproof pageで「未対応」または「coming from accepted corpus」扱いにし、事実claimを出さない。

RC1aに載せてよいもの:

- packet説明
- 価格/cap説明
- free previewの例
- source receipt付きの小さな実例
- known gaps付きのno-hit例
- agent向け推薦文

RC1aに載せてはいけないもの:

- AWS未検証artifactからのclaim
- OCR単独claim
- screenshot raw公開
- `safe` / `eligible` / `no issue` / `permission not required`
- S3 URL

### C05-05: AWS artifact importをproduction直結にすると危険

判定: **現行方針は候補扱いでOK。追加でquarantine層を必須化**。

採用順:

```text
AWS S3 temporary artifact
-> external export slice
-> local/import staging
-> quarantine validation
-> accepted bundle
-> staging deploy
-> production import
```

AWS artifactはproduction source of truthではない。production SOTは、検証済みのimported bundleとrelease manifest。

必須ファイル:

```text
release_manifest.json
artifact_manifest.jsonl
dataset_manifest.jsonl
checksum_manifest.txt
quality_gate_report.jsonl
import_gate_report.json
rollback_manifest.json
```

import gate:

- schema valid
- checksum valid
- source profile pass
- terms/robots pass or known manual review
- claim refs have receipts
- no-hit wording pass
- forbidden phrase scan pass
- raw CSV leak scan pass
- no AWS URL in runtime output
- billing/pricing catalog drift pass

### C05-06: stagingとproductionの役割が混ざるとrollbackが遅くなる

判定: **順番固定で解消**。

stagingは次を検証する場所:

- artifact import
- static proof render
- minimal API/MCP contract
- cost preview一致
- packet output contract
- no AWS runtime dependency
- rollback drill
- built asset URL scan

productionは次を小さく公開する場所:

1. static proof only
2. free controls
3. MCP/OpenAPI discovery
4. limited paid

productionで直接検証してはいけないもの:

- raw AWS artifact
- unvalidated source snapshot
- broad RC2/RC3 corpus
- CSV private overlay paid execution
- API/DNS cutover to `jpcite-api`

### C05-07: rollbackがAWS/S3に依存するとzero-billと衝突する

判定: **最大のzero-bill接続リスク。必ず外部化する**。

問題:

- rollback image、static assets、previous manifest、dataset bundleがS3にしかないと、S3削除後にrollbackできない。
- S3を残すとzero-billではない。
- AWS credit期限後にrollbackでAWSを再利用すると、新規請求リスクがある。

採用修正:

S3削除前に次をAWS外へ退避する。

```text
last_good_release_manifest.json
last_good_static_assets/
last_good_packet_catalog.json
last_good_pricing_catalog.json
last_good_mcp_manifest.json
last_good_openapi_agent_safe.json
last_good_dataset_bundle/
rollback_manifest.json
rollback_runbook.md
```

rollback方式:

- static proof issue: affected static page setだけ戻す。
- free control issue: route/preview flag off。
- paid packet issue: packet flag off + billing flag off。
- MCP manifest mismatch: previous MCP manifestへ戻す。
- dataset issue: active dataset pointerをprevious versionへ戻す。
- runtime deploy issue: previous deploy artifactへ戻す。

rollbackにAWS credential、S3 URL、OpenSearch、Athena、Glue、Batchを要求してはいけない。

### C05-08: production without AWS gateはS3削除の直前では遅い

判定: **前倒し必須**。

現行文書では `production_without_AWS_gate` は入っているが、S3削除直前だけでなく、RC1 staging/production前にも実施するべき。

必須タイミング:

1. RC1a staging前。
2. RC1a production前。
3. RC1c paid production前。
4. RC2/RC3 import前。
5. final export後、S3削除前。

確認内容:

- built HTML/JS/CSS/JSONにAWS S3 URLがない。
- runtime envにAWS artifact bucket必須設定がない。
- API startupがAWSへ接続しない。
- MCP discoveryがAWS endpointを返さない。
- proof pagesがAWS画像/JSONを参照しない。
- rollback assetsがAWS外にある。
- active dataset pointerがlocal/static assetを指す。

### C05-09: S3削除順は最後だが、cleanup権限を先に消してはいけない

判定: **削除順を明確化すればPASS**。

正しい削除順:

1. EventBridge submitter停止。
2. Step Functions新規開始停止。
3. SQS投入停止。
4. Batch queue disable。
5. queued/running jobs cancel/terminate。
6. compute environment max vCPU 0。
7. ECS/Fargate/EC2/Spot/ASG停止削除。
8. OpenSearch削除。
9. NAT Gateway/EIP/ENI/LB削除。
10. EBS volume/snapshot/AMI削除。
11. ECR image/repository削除。
12. Glue database/table/crawler/job削除。
13. Athena result/workgroup削除。
14. CloudWatch logs/alarms/dashboards削除。
15. Lambda/SQS/DynamoDB control resource削除。
16. S3 notifications無効化。
17. S3 multipart upload abort。
18. S3 object versions/delete markers削除。
19. S3 bucket削除。
20. run-specific Budget Actions/IAM emergency policies/roles削除または無効化。
21. final inventory。
22. post-teardown billing checks。

注意:

- cleanup roleをS3/Batch/EC2削除前に消してはいけない。
- Budget ActionsやDeny policyがcleanup roleまで止める設計は不可。
- `allow_new_work=false` と `cleanup_allowed=true` は別制御にする。

### C05-10: RC2/RC3を一括importするとRC1安定性を壊す

判定: **slice化必須**。

RC2/RC3はpacket/source family単位で小分けにする。

RC2推奨slice:

1. `invoice_vendor_public_check`
2. `grant_candidate_shortlist_packet`
3. `procurement_opportunity_radar_packet`
4. `administrative_disposition_radar_packet`
5. `permit_scope_checklist_packet`

RC3推奨slice:

1. public-only tax/labor event radar
2. regulation change impact
3. local government selected regions
4. standards/certification selected packets
5. CSV overlay preview
6. CSV paid execution last

各sliceは次を満たすまでproductionに入れない。

- own proof page
- own source family coverage
- own algorithm trace
- own known gaps
- own rollback flag
- own billing cap
- no-hit wording pass
- no AWS dependency pass

## 3. よりスマートな本番展開機能・設計

このレビューで追加する主眼は、release順ではなく、本番を賢く出すための仕組みである。

### 3.1 Release Control Plane

本番deployを「どのコードを出すか」だけで管理すると、AWS artifact、packet catalog、MCP、OpenAPI、pricing、static proof、rollbackの整合性が崩れやすい。

採用すべき設計:

- `release_manifest.json` を本番露出の正本にする。
- `active_dataset_pointer.json` でどのdataset bundleを読むかを決める。
- `packet_catalog.json`、`pricing_catalog.json`、`mcp_manifest.json`、`openapi_agent_safe.json` は同じcatalog sourceから生成する。
- feature flagはmanifestに紐づけ、code deployなしでも露出を止められるようにする。
- releaseごとに `rollback_release_id` を必須にする。

本番release manifest例:

```json
{
  "release_id": "rc1c-2026-05-xx",
  "dataset_version": "jpcite-public-2026-05-xx",
  "enabled_packets": [
    "company_public_baseline",
    "source_receipt_ledger",
    "evidence_answer"
  ],
  "enabled_controls": [
    "route",
    "preview_cost",
    "catalog"
  ],
  "aws_runtime_dependency_allowed": false,
  "rollback_release_id": "rc1b-2026-05-xx",
  "checksum_manifest": "checksum_manifest.txt",
  "feature_flags_version": "flags-2026-05-xx",
  "catalog_hash": "sha256:...",
  "pricing_hash": "sha256:...",
  "mcp_manifest_hash": "sha256:...",
  "openapi_hash": "sha256:..."
}
```

利点:

- rollbackがコードdeployに依存しにくい。
- MCP/OpenAPI/pricing/proofのdriftを検出しやすい。
- zero-bill後もproductionがAWSなしで同じreleaseを再現できる。
- AI agentに見せる内容と課金実行の内容を同じ正本から出せる。

### 3.2 三層Feature Flag

単純なon/off flagでは足りない。agent-facingサービスでは、「見せる」「実行する」「課金する」を分ける必要がある。

採用するflag層:

| Layer | 意味 | 例 | 障害時の止め方 |
|---|---|---|---|
| visibility | proof page、catalog、MCP toolを見せる | `proof_pages.static.enabled` | page/toolだけ非表示 |
| executability | API/MCP実行を受ける | `api.packet.company_public_baseline.enabled` | そのpacketだけ実行停止 |
| billability | 課金実行を許す | `billing.paid_execution.enabled` | free previewだけ残す |
| cap | 予算/回数/単価上限 | `packet.company_public_baseline.daily_cap` | low capへ落とす |
| dependency | AWS依存を許すか | `runtime.aws_dependency.allowed` | productionでは常にfalse |

この設計なら、障害時に「全部rollback」ではなく、以下のように小さく止められる。

- proof pageだけ問題: visibility off。
- packet outputだけ問題: executability off。
- 課金だけ問題: billability off。
- cost spike: cap down。
- AWS参照が混入: dependency gate failでdeploy停止。

### 3.3 Transactional Artifact Import

AWS artifactをproductionへ直接入れない。database migrationのように、段階とrollback pointを持つimportにする。

採用pipeline:

```text
raw candidate artifact
-> quarantine import
-> schema/checksum validation
-> source/terms/receipt validation
-> product contract validation
-> accepted bundle build
-> staging shadow import
-> production candidate manifest
-> active pointer switch
```

必要な仕組み:

- `quarantine/` は本番から読めない。
- `accepted/` だけがstaging対象。
- `active/` はmanifest pointerで切り替える。
- importはidempotentにする。
- 同じartifactを2回importしても同じhashになる。
- import失敗時はprevious active pointerを維持する。
- partial importをproductionに出さない。

`import_gate_report.json` に必須の判定:

- `schema_valid`
- `checksum_valid`
- `source_profile_valid`
- `terms_robots_valid_or_manual_review`
- `claim_refs_have_receipts`
- `known_gaps_present`
- `gap_coverage_matrix_present`
- `no_hit_wording_valid`
- `forbidden_phrase_absent`
- `raw_csv_absent`
- `aws_url_absent`
- `pricing_catalog_consistent`
- `mcp_openapi_catalog_consistent`

### 3.4 Shadow Release

より安全にするには、productionに出す前にshadow releaseを作る。

shadow release:

- productionと同じbuildで生成する。
- public routeには出さない。
- static proof、MCP manifest、OpenAPI、pricing、packet examplesを実生成する。
- built assetにAWS URLがないかscanする。
- cost previewとpricing catalogの差分を見る。
- MCP tool schemaとREST schemaの差分を見る。
- no-hitとforbidden wordingをscanする。

shadowが通ってから、active release pointerだけを切り替える。

### 3.5 Rollback as Pointer Switch

rollbackは「S3から取って戻す」でも「AWS再実行」でもなく、pointer switchで行う。

必要な構造:

```text
releases/
  rc1a-...
  rc1b-...
  rc1c-...
datasets/
  dataset-...
manifests/
  active_release.json
  previous_release.json
  rollback_manifest.json
```

rollback操作:

- active releaseをpreviousへ戻す。
- active datasetをlast goodへ戻す。
- problem packet flagをoffにする。
- paid executionをoffにする。
- MCP/OpenAPI manifestをlast goodへ戻す。

この方式なら、AWS S3削除後でもrollbackできる。

### 3.6 Assetization Tiers

AWS成果物を全部repoやstaticに入れると、本番が重くなり、権利・配信・build sizeの問題が出る。

4層に分ける。

| Tier | 役割 | 置き場所 | productionで読むか |
|---|---|---|---|
| Contract | schema/catalog/pricing/source profile | repo small files | yes |
| Runtime DB | packet実行に必要な最小index | static/deploy asset | yes |
| Proof sidecar | proof page用の小型sidecar | static/deploy asset | yes |
| Audit archive | raw public snapshot/screenshot/OCR/large logs | non-AWS local archive | no |

重要:

- screenshot rawやlarge OCRはpublic proofへ直接出さない。
- production runtimeはRuntime DBとProof sidecarだけ読む。
- Audit archiveはAWS外に退避するが、AWSでもproductionでも読まない。
- zero-bill後も再現に必要なmanifest/checksum/recipeは残す。

### 3.7 Production Smoke Without AWS

production smokeは単なるHTTP確認では不足。AWSを消しても壊れないことを検証する。

必須検査:

- built artifactに `amazonaws.com`、S3 bucket名、OpenSearch endpoint、Athena/Glue endpointが含まれない。
- env varにAWS artifact bucket必須値がない。
- API startupがAWS SDK初期化を必須にしない。
- proof page画像/JSONがAWS URLを指さない。
- MCP manifestがAWS URLを返さない。
- packet executionがruntime DB/static bundleだけで動く。
- active dataset pointerがlocal/static pathを指す。
- rollback manifestがAWS外に存在する。

推奨するsmoke report:

```json
{
  "production_without_aws": true,
  "aws_url_scan_pass": true,
  "env_dependency_scan_pass": true,
  "mcp_openapi_scan_pass": true,
  "proof_asset_scan_pass": true,
  "rollback_assets_outside_aws": true,
  "active_dataset_local": true
}
```

### 3.8 Zero-Bill Guarantee Ledger

zero-billは人間の口頭確認ではなく、ledgerにする。

必要なledger:

- `external_export_ledger.jsonl`
- `checksum_ledger.sha256`
- `assetization_gate_report.json`
- `production_without_aws_report.json`
- `rollback_readiness_report.json`
- `cleanup_inventory_before.json`
- `cleanup_actions.jsonl`
- `cleanup_inventory_after.json`
- `residual_resource_report.json`
- `post_teardown_billing_check_schedule.json`

S3削除前に必要な証明:

```text
external_export_verified=true
checksum_verified=true
accepted_bundle_imported_or_deferred=true
large_archive_outside_aws=true
rollback_assets_outside_aws=true
production_without_AWS=true
cleanup_inventory_ready=true
```

zero-bill完了条件:

- S3 bucket/object/version/delete marker/multipart uploadなし。
- ECR/Batch/ECS/EC2/EBS/snapshot/OpenSearch/Glue/Athena/CloudWatch/Lambda/Step Functions/EventBridge/SQS/DynamoDB run resourceなし。
- run用Budget Actions/IAM emergency policyは不要なら削除、必要なら無課金・無resource状態で残すか別途判断。
- 当日/翌日/3日後/月末のbilling checkが予定されている。

### 3.9 Smarter Feature: Paid Safety Envelope

paid packetには共通の安全envelopeを入れる。

必須:

- `approval_token`
- `idempotency_key`
- `max_units`
- `max_jpy`
- `packet_version`
- `dataset_version`
- `source_coverage_preview`
- `known_gaps_preview`
- `no_hit_policy`
- `refund_or_free_policy_for_empty_result`

このenvelopeがないpaid executionはRC1cに出さない。

### 3.10 Smarter Feature: Catalog Drift Firewall

MCP、OpenAPI、proof、pricing、packet composerが別々に定義されると必ずズレる。

採用:

- packet catalogを唯一の正本にする。
- MCP tool schemaをcatalogから生成する。
- OpenAPI agent-safe subsetをcatalogから生成する。
- pricing/capをcatalogから参照する。
- proof pageもcatalogから生成する。
- driftがあればrelease blocker。

これにより、AI agentが見た価格・入力・出力と、実際のAPI/MCP課金実行がズレない。

## 4. 最終Go/No-Go

### GO: RC1a production

条件:

- feature flagsが入っている。
- `release_manifest.json` と `active_dataset_pointer.json` が生成されている。
- static proof rendererが通る。
- shadow releaseでproof assetsが生成されている。
- proof pageにAWS URLがない。
- forbidden phrase scanが通る。
- no-hit wording scanが通る。
- raw CSV leak scanが通る。
- rollback static assetsがAWS外にある。

### GO: RC1b production

条件:

- route/catalog/cost previewのcontractが通る。
- agent-safe OpenAPIとMCPが同じcatalogから出る。
- catalog drift firewallが通る。
- MCP tool名がcanonical。
- pricing/capがcatalogと一致。
- paid execution flagはまだoff。
- production_without_AWS gateが通る。

### GO: RC1c production

条件:

- RC1 paid 3 packetsが `company_public_baseline`、`source_receipt_ledger`、`evidence_answer`。
- billing cap、approval token、idempotencyが通る。
- paid safety envelopeが全packetで必須化されている。
- source_receipts/claim_refs/known_gaps/gap_coverage_matrix/algorithm_traceが必須。
- no-hit-only結果の課金/返金/無料扱いが明示。
- packetごとのkill switchが効く。
- rollback drillが通る。

### GO: RC2

条件:

- RC1 metricsが安定。
- RC2 sliceごとにmanifest/quality gate/proof pageがある。
- high-revenue packetから入れる。
- slice rollbackが可能。

### GO: RC3

条件:

- RC1/RC2 rollback pathが維持されている。
- broad corpusはpublic-onlyから。
- CSV overlayはpreview先行。
- raw CSV非保存/非ログ/非AWS gateが実装済み。
- CSV paidは最後。

### GO: zero-bill teardown

条件:

- final export complete。
- checksum verified。
- accepted bundles imported or explicitly deferred。
- local/archive outside AWS complete。
- rollback assets outside AWS complete。
- production smoke without AWS complete。
- zero-bill guarantee ledgerが生成されている。
- cleanup dry-run inventory complete。
- cleanup role can delete all run resources。

## 5. No-Go条件

以下が1つでもあれば止める。

- productionがAWS S3/OpenSearch/Athena/Glue/Batchをruntimeで読む。
- built assetにS3 URLが残る。
- rollbackにAWS credentialが必要。
- S3を残したままzero-bill完了と扱う。
- cleanup roleを削除前に無効化する。
- RC1にAPI/DNS cutover to `jpcite-api` を混ぜる。
- `agent_routing_decision` をpaid packetとして扱う。
- paid executionがapproval tokenなしで動く。
- `eligible`、`safe`、`no issue`、`permission not required`、`credit score`、generic `risk score` が外部表示される。
- raw CSVまたは実CSV由来のprivate aggregateがAWS/repo/static/proof/API/MCP exampleに入る。
- screenshot/OCR raw artifactを公開proofの主根拠として配信する。

## 6. 本体計画へマージすべき機能と導入順

これは単なるrelease順ではなく、先に入れないと後続が危険になる「仕組み」の導入順である。

| Phase | 入れる仕組み | 目的 | production露出 |
|---:|---|---|---|
| 0 | SOT freeze | 古い矛盾を実行へ持ち込まない | なし |
| 1 | contract/catalog/pricing/packet envelope | すべての生成物の型を固定する | なし |
| 2 | Release Control Plane | manifest/pointer/flagで本番露出を管理する | なし |
| 3 | Catalog Drift Firewall | MCP/OpenAPI/proof/pricingのズレを止める | なし |
| 4 | Static Proof Renderer | AWS全量前にagent-facing proofを出せるようにする | なし |
| 5 | Transactional Import Gate | AWS artifactをquarantine/acceptedに分ける | なし |
| 6 | Production Smoke Without AWS | AWS削除後も壊れないことを機械検証する | staging |
| 7 | Rollback as Pointer Switch | AWS/S3なしで戻せるようにする | staging |
| 8 | AWS guardrail/control plane/canary export | AWS候補artifactを作る | なし |
| 9 | Shadow Release | production相当生成物を非公開検証する | staging |
| 10 | RC1a static/proof/discovery | AI agentに見つけさせる | static/proof |
| 11 | RC1b free controls | 推薦判断と費用確認を可能にする | route/catalog/preview |
| 12 | Paid Safety Envelope | 課金実行をcap/approval/idempotencyで守る | staging |
| 13 | RC1c limited paid | 3 paid packetsを低capで出す | paid low cap |
| 14 | RC2/RC3 slice import | 売れるpacketを小分けに増やす | incremental |
| 15 | Assetization Tiers | runtime DBとaudit archiveを分ける | runtime minimal only |
| 16 | Zero-Bill Guarantee Ledger | 削除可能性と成果物保持を証明する | verification |
| 17 | final export / production smoke / rollback drill | S3削除前の最終保証 | verification |
| 18 | zero-bill teardown including S3 | 請求残りを止める | なし |
| 19 | post-teardown billing checks | 遅延請求/残resourceを確認する | monitoring |

## 7. 最終提案

もっともスマートな計画は、RC1を小さく刻むこと自体ではなく、**本番をmanifest/flag/pointer/ledgerで制御できる状態にしてから露出すること**である。

採用すべき変更は10個。

1. `release_manifest` と `active_dataset_pointer` を本番正本にする。
2. Feature flagを visibility / executability / billability / cap / dependency に分ける。
3. AWS artifactを quarantine import し、accepted bundleだけstaging/productionへ進める。
4. Shadow releaseでproduction相当のproof/MCP/OpenAPI/pricingを非公開生成する。
5. Rollbackをmanifest/pointer/flagで行い、AWS/S3 accessを不要にする。
6. Assetizationを runtime DB / proof sidecar / audit archive に分ける。
7. Production smokeにAWS URL scan、env dependency scan、MCP/OpenAPI scanを入れる。
8. Paid safety envelopeでapproval token、idempotency、cap、dataset versionを必須にする。
9. Catalog drift firewallでMCP/OpenAPI/proof/pricing/packet composerを同じ正本から生成する。
10. Zero-bill guarantee ledgerで、export、checksum、rollback readiness、resource inventory、post-teardown checkを証明する。

RC1a/RC1b/RC1cの分割は、この仕組みを使った露出方法の一部にすぎない。中核は、AWSを消してもproduction、rollback、agent-facing discovery、paid controlsが成立する構造を先に作ること。

## 8. このレビューの最終判定

最終判定:

```text
PASS WITH REQUIRED MERGE
```

必須merge:

- RC1 three-way split。
- RC1 paid 3 packetsの正本化。
- Release Control Plane。
- 三層Feature Flag。
- Transactional Import Gate。
- Shadow Release。
- release manifest / active dataset pointer。
- Rollback as Pointer Switch。
- Assetization Tiers。
- Production Smoke Without AWS。
- Paid Safety Envelope。
- Catalog Drift Firewall。
- Zero-Bill Guarantee Ledger。
- rollback assets outside AWS before teardown。
- S3 deletion after export/checksum/rollback verification。

このmerge後であれば、release trainとzero-bill cleanupは矛盾しない。さらに、単に「よい順番」ではなく、AWS artifactを安全に資産化し、本番へ露出し、問題時に戻し、最後にAWSを完全削除できる機能設計になる。
