# AWS final 12 review 11/12: smarter production, assetization, and zero-bill functions

作成日: 2026-05-15  
担当: 最終追加検証 11/12 / もっとスマートな本番・資産化・zero-bill機能  
対象: transactional import, shadow release, pointer rollback, assetization tiers, static DB manifest, zero-bill guarantee ledger, external export gate, production smoke without AWS, post-teardown cost attestations  
AWS前提: profile `bookyou-recovery` / account `993693061769` / region `us-east-1`  
実行状態: AWS CLI/APIコマンド、AWSリソース作成、削除、本番デプロイ、収集ジョブ実行は行っていない。ローカル計画検証のみ。  
出力制約: 本レビューではこのMarkdownだけを作成する。

## 0. 結論

判定: **条件付きPASS。ただし、よりスマートな機能改善を本体計画へ入れるべき。**

現行の正本は大筋で正しい。

- AWSは一時的なartifact factory。
- productionはAWS runtimeに依存しない。
- AWS終了前に外部exportする。
- 最後はS3も含めてAWS run resourceを削除する。
- 本番はRC1を早く出し、AWS full runを待たない。

ただし、今の計画のままだと「順番」は整理されているが、「本番へ安全に資産を入れ替える機能」がまだ弱い。

もっとスマートにする核心は、次の発想へ変えること。

```text
deployで本番を変えるのではなく、
検証済みasset bundleへのpointerを切り替えて本番を変える。
```

そのために、以下の9機能を採用する。

1. `Transactional Artifact Import`
2. `Shadow Release`
3. `Pointer Rollback`
4. `Assetization Tiers`
5. `Static DB Manifest`
6. `Zero-Bill Guarantee Ledger`
7. `External Export Gate`
8. `Production Smoke Without AWS`
9. `Post-Teardown Cost Attestations`

この9つを入れると、AWSが大量に成果物を作っても、productionには「通ったものだけ」が入り、問題があればAWSなしで即rollbackでき、S3削除後も本番と証跡が壊れない。

最終採用すべき本番像:

```text
AWS temporary factory
  -> exported artifact bundle
  -> quarantine validation
  -> accepted static DB bundle
  -> shadow release
  -> active pointer switch
  -> production smoke without AWS
  -> external archive verified
  -> AWS teardown
  -> post-teardown cost attestations
```

## 1. 最終的に解くべき問題

この計画で一番怖いのは、AWSコストでも収集量でもない。

本当に怖いのは、以下の状態になること。

1. AWSで大量に集めたが、どれを本番に出してよいか分からない。
2. 本番に出したあと、問題が見つかっても戻し方が重い。
3. S3を消したら、本番または証跡が壊れる。
4. zero-billにしたいのに、どこかにAWS依存URLやAWS archiveが残る。
5. コスト確認や後日証明のためにAWSを残す、という矛盾が出る。
6. `site/`、`data/`、`docs/`、local archiveのどこが正本か曖昧になる。
7. 大量assetを丸ごとstatic配信して、デプロイサイズ・権利・表示速度が壊れる。

したがって、賢くする対象は「収集順」ではなく、次の機能である。

- importの取引性
- releaseの影化
- rollbackの軽量化
- assetの層分け
- manifestによる静的DB制御
- AWS削除後の証明

## 2. 採用機能1: Transactional Artifact Import

### 2.1 目的

AWS成果物を本番へ直結しない。

AWS成果物は必ず候補として扱い、次の取引的importを通す。

```text
candidate export
  -> quarantine
  -> validation
  -> accepted bundle
  -> staging bundle
  -> production eligible bundle
```

### 2.2 必須状態

import対象は必ず4状態のどれかに置く。

| State | 意味 | production露出 |
|---|---|---|
| `quarantined` | AWSから来た未検証候補 | 不可 |
| `rejected` | schema/terms/quality/漏洩/禁止表現で落ちた | 不可 |
| `accepted_not_active` | 本番に出せるが未公開 | shadowのみ可 |
| `active` | pointerが指している本番正本 | 可 |

### 2.3 Transaction manifest

各importは `import_transaction.json` を持つ。

```json
{
  "transaction_id": "imp_20260515_001",
  "run_id": "aws_credit_run_20260515",
  "source_bundle_id": "bundle_candidate_001",
  "target_bundle_id": "bundle_accepted_001",
  "status": "accepted_not_active",
  "started_at": "2026-05-15T00:00:00+09:00",
  "completed_at": "2026-05-15T00:15:00+09:00",
  "input_artifact_count": 120000,
  "accepted_artifact_count": 84000,
  "rejected_artifact_count": 36000,
  "checks": {
    "schema": "pass",
    "checksum": "pass",
    "source_profile": "pass",
    "terms_robots": "pass_or_review_marked",
    "claim_receipt_linkage": "pass",
    "no_hit_wording": "pass",
    "forbidden_phrase": "pass",
    "csv_leak": "pass",
    "aws_url_absence": "pass",
    "billing_catalog_drift": "pass"
  },
  "activation_allowed": true,
  "activation_blockers": []
}
```

### 2.4 賢い改善点

importを1回の巨大処理にしない。

source family、packet family、dataset slice単位で小さくcommitできるようにする。

```text
bundle/
  corporate_identity/
  invoice_registry/
  grant_program/
  permit_registry/
  enforcement_disposition/
  tax_labor_social/
  proof_pages/
  packet_examples/
```

利点:

- 一部sourceが落ちても全体releaseを止めない。
- `company_public_baseline` だけ先に出せる。
- 問題のあるsource familyだけpointer対象から外せる。
- AWS teardown前に価値あるsliceだけ確実に救える。

### 2.5 Release blocker

以下が1つでもあれば `accepted_not_active` に上げない。

- `source_receipts[]` がclaimに紐づかない。
- `known_gaps[]` が空なのにcoverage不足がある。
- `no_hit_not_absence` が欠けている。
- raw CSV、row-level CSV、private aggregate、CSV由来hashらしきものが混入している。
- S3 URL、Athena result URL、CloudWatch log URL、AWS account ARNがruntime outputへ混入している。
- screenshot rawやOCR全文をpublic proofへ出そうとしている。
- `eligible`、`safe`、`no issue`、`permission not required`、`credit score`、`trustworthy` などの禁止表現が外部出力にある。

## 3. 採用機能2: Shadow Release

### 3.1 目的

本番に見せる前に、本番相当のルートで新bundleを試す。

Shadow releaseは「順番」ではなく、本番安全性を上げる機能である。

```text
active bundle: users and agents see this
shadow bundle: production code can read this, but users and agents do not see it
```

### 3.2 Shadow対象

shadowで確認するもの:

- static proof render
- packet catalog
- price/cap/approval token
- MCP tool response shape
- OpenAPI examples
- `llms.txt` and `.well-known` references
- no-hit wording
- source receipt links
- known gaps
- artifact size
- static asset load time
- AWS URL absence

shadowで確認しないもの:

- request-time LLM生成
- 本番課金
- 実ユーザーCSV
- AWS runtime fetch
- 直接S3読込

### 3.3 Shadow query replay

RC1で使う代表queryを固定し、新bundleに対してshadow replayする。

```json
{
  "shadow_replay_id": "shadow_20260515_001",
  "active_bundle_id": "bundle_active_001",
  "candidate_bundle_id": "bundle_accepted_002",
  "queries": [
    "法人番号とインボイスを確認したい",
    "この会社の公的情報ベースラインを見たい",
    "この補助金に応募できそうか確認したい",
    "許認可の確認に必要な公的情報を出したい",
    "行政処分の公表情報を確認したい"
  ],
  "diff_policy": {
    "schema_break": "block",
    "forbidden_wording": "block",
    "missing_receipt": "block",
    "higher_known_gap_visibility": "allow",
    "price_increase": "block_unless_catalog_approved"
  }
}
```

### 3.4 Shadow releaseの合格条件

- activeとcandidateでAPI schemaが壊れていない。
- candidateのclaimはすべてreceiptへ辿れる。
- candidateに新しいsource gapがある場合、隠さず `known_gaps[]` に出る。
- candidateの価格/capがcatalog正本と一致する。
- candidateのproof pageにAWS URLがない。
- candidateのstatic assetをAWS network遮断下で読める。

## 4. 採用機能3: Pointer Rollback

### 4.1 目的

rollbackをdeployやAWS復旧にしない。

rollbackは、active pointerを前bundleへ戻すだけにする。

```text
active_dataset_pointer.json
  current: bundle_20260515_003
  previous: bundle_20260515_002
```

### 4.2 Pointer file

```json
{
  "schema_version": "1.0",
  "active_bundle_id": "bundle_20260515_003",
  "previous_bundle_id": "bundle_20260515_002",
  "activated_at": "2026-05-15T10:00:00+09:00",
  "activated_by": "release_control_plane",
  "rollback_allowed": true,
  "runtime_aws_dependency_allowed": false,
  "static_db_manifest_path": "/static/assets/db/bundle_20260515_003/static_db_manifest.json",
  "rollback_manifest_path": "/static/assets/db/bundle_20260515_002/rollback_manifest.json"
}
```

### 4.3 Rollback時に戻すもの

Pointer rollbackでは次をまとめて戻す。

- packet catalog
- source profile index
- pricing/cap catalog
- static DB manifest
- proof page sidecar
- MCP/OpenAPI examples
- `llms.txt` recommended packet references
- `.well-known` discovery references

### 4.4 Rollback時に戻さないもの

以下はrollback対象にしない。

- AWS S3
- AWS Batch
- AWS Athena
- AWS OpenSearch
- CloudWatch Logs
- raw exported archive
- raw public screenshots
- OCR intermediates

理由:

productionはAWS削除後にもrollbackできる必要がある。

### 4.5 矛盾修正

現行計画の一部では「AWS成果物を本番へimportしたあと、問題があれば戻す」という表現がある。

これは正しいが、戻し方を明確にしないと危険。

最終方針:

```text
rollback = pointer switch + flag disable
not rollback = AWS re-fetch or S3 restore
```

## 5. 採用機能4: Assetization Tiers

### 5.1 目的

AWSで作ったものを全部同じ場所に置かない。

assetは4層へ分ける。

| Tier | 名前 | 目的 | 本番配信 | git | AWS teardown後 |
|---|---|---|---|---|---|
| T0 | Runtime static DB | 本番API/proofが読む最小index | 可 | 小さければ可 | 必須 |
| T1 | Product proof assets | proof page, examples, agent cards | 可 | 可 | 必須 |
| T2 | Local audit archive | full export, screenshot, OCR, large snapshot | 不可 | 不可 | 必須 |
| T3 | Rejected/excluded | terms/quality/leakで落ちたもの | 不可 | 不可 | 不要または隔離 |

### 5.2 T0 Runtime static DB

T0に入れてよいもの:

- normalized source profile index
- source receipt index
- claim reference index
- no-hit policy table
- known gap matrix
- packet catalog
- pricing/cap catalog
- small examples
- lookup keys
- content hashes

T0に入れてはいけないもの:

- raw screenshots
- raw PDFs
- OCR全文
- HAR body
- CloudWatch logs
- Athena outputs
- raw public snapshot bulk
- private CSV由来情報

### 5.3 T1 Product proof assets

T1はAI agentとエンドユーザーへ見せる販売素材。

含めるもの:

- proof page markdown/html sidecars
- packet examples
- `agent_recommendation_card`
- free preview examples
- price/cap examples
- safe no-hit examples
- known gap examples

### 5.4 T2 Local audit archive

T2はAWS外に置くが、public配信しない。

推奨path:

```text
/Users/shigetoumeda/jpcite_artifacts/aws-runs/{run_id}/
```

含めるもの:

- full `run_manifest.json`
- `artifact_manifest.jsonl`
- `dataset_manifest.jsonl`
- `checksum_ledger.sha256`
- allowed raw public snapshots
- screenshot receipts
- OCR intermediates
- rejection ledgers
- cleanup evidence
- post-teardown attestation files

T2はgitに入れない。配信しない。

### 5.5 T3 Rejected/excluded

T3は使わないもの。

例:

- terms不明で再配布不可
- robots/termsで収集または利用が不明
- CAPTCHA/login/403/429由来
- OCR confidence不足
- source profileが未承認
- PII抑制で外部利用不可
- 禁止表現を生成するpacket fixture

T3は本番に絶対出さない。

## 6. 採用機能5: Static DB Manifest

### 6.1 目的

productionが読む静的DBをmanifestで完全制御する。

本番コードはディレクトリを探索しない。

必ず `static_db_manifest.json` を読む。

### 6.2 Static DB manifest例

```json
{
  "schema_version": "1.0",
  "bundle_id": "bundle_20260515_003",
  "created_at": "2026-05-15T10:00:00+09:00",
  "runtime_aws_dependency_allowed": false,
  "source_families": [
    "corporate_identity",
    "invoice_registry",
    "business_registry_signal",
    "grant_program",
    "permit_registry",
    "enforcement_disposition"
  ],
  "indexes": {
    "source_profiles": {
      "path": "indexes/source_profiles.jsonl.zst",
      "sha256": "sha256:...",
      "records": 1200
    },
    "source_receipts": {
      "path": "indexes/source_receipts.jsonl.zst",
      "sha256": "sha256:...",
      "records": 500000
    },
    "claim_refs": {
      "path": "indexes/claim_refs.jsonl.zst",
      "sha256": "sha256:...",
      "records": 800000
    },
    "packet_catalog": {
      "path": "catalog/packet_catalog.json",
      "sha256": "sha256:..."
    },
    "pricing_catalog": {
      "path": "catalog/pricing_catalog.json",
      "sha256": "sha256:..."
    }
  },
  "forbidden": {
    "aws_url_present": false,
    "raw_csv_present": false,
    "raw_screenshot_public": false,
    "har_body_present": false
  },
  "quality_gates": {
    "schema": "pass",
    "checksum": "pass",
    "source_profile": "pass",
    "claim_receipt_linkage": "pass",
    "no_hit_wording": "pass",
    "forbidden_phrase": "pass",
    "production_smoke_without_aws": "pass"
  }
}
```

### 6.3 Manifestの賢い点

- deploy後に何を読んでいるか特定できる。
- pointer rollbackでbundle全体を戻せる。
- no AWS URL scanをmanifest単位でできる。
- datasetの部分更新ができる。
- `packet_catalog` と `pricing_catalog` のdriftを検出できる。
- static DBを大きくしすぎた場合、chunk単位で分割できる。

### 6.4 Content addressed chunk

巨大indexはcontent-addressed chunkにする。

```text
chunks/
  sha256_abcd....jsonl.zst
  sha256_efgh....jsonl.zst
indexes/
  source_receipts.index.json
```

利点:

- 同じchunkを再利用できる。
- rollback時に差分が小さい。
- デプロイ前にchecksum検証しやすい。
- AWS teardown後も再現性を持てる。

## 7. 採用機能6: Zero-Bill Guarantee Ledger

### 7.1 目的

zero-billは「削除したつもり」ではなく、機械可読ledgerで証明する。

### 7.2 Ledger構造

```json
{
  "ledger_id": "zero_bill_20260515_001",
  "aws_account_id": "993693061769",
  "region": "us-east-1",
  "run_id": "aws_credit_run_20260515",
  "target_state": "zero_ongoing_aws_bill",
  "external_export_verified": true,
  "production_smoke_without_aws": true,
  "runtime_aws_dependency_allowed": false,
  "resource_inventory_zero": true,
  "s3_remaining_buckets": 0,
  "ecr_remaining_repositories": 0,
  "batch_remaining_compute_environments": 0,
  "ecs_remaining_clusters": 0,
  "ec2_remaining_instances": 0,
  "ebs_remaining_volumes": 0,
  "snapshots_remaining": 0,
  "nat_gateways_remaining": 0,
  "elastic_ips_remaining": 0,
  "opensearch_domains_remaining": 0,
  "glue_jobs_remaining": 0,
  "athena_result_locations_remaining": 0,
  "cloudwatch_log_groups_remaining": 0,
  "step_functions_remaining": 0,
  "eventbridge_schedules_remaining": 0,
  "lambda_functions_remaining": 0,
  "post_teardown_attestations_scheduled_outside_aws": true,
  "exceptions": []
}
```

### 7.3 重要な矛盾修正

「post-teardown確認をAWS EventBridgeやLambdaで後日実行する」は、zero-bill要件と矛盾する。

最終方針:

```text
AWS teardown後の後日確認は、AWS内schedulerではなく、ローカル/非AWS/手動runbookで行う。
```

理由:

- EventBridge scheduleもLambdaも残せばAWS resourceが残る。
- CloudWatch Logsも残り得る。
- zero-bill ledgerが「resource inventory zero」と矛盾する。

AWS内部で自走してよいのは、teardown完了前まで。

teardown後はAWS内部制御面も削除する。

## 8. 採用機能7: External Export Gate

### 8.1 目的

S3削除前に、価値ある成果物がAWS外へ出ていることを証明する。

### 8.2 Gate名

```text
G2.5 External Export Gate
```

これはfull spend laneより前から有効化する。

### 8.3 GO条件

- export先がAWS外にある。
- T0/T1/T2/T3へ分類済み。
- T0/T1はproduction import可能なshape。
- T2はlocal archiveへ保存済み。
- `checksum_ledger.sha256` がAWS外で検証済み。
- `static_db_manifest.json` が生成済み。
- `active_dataset_pointer.json` の候補が生成済み。
- `rollback_manifest.json` が生成済み。
- S3にしかないartifactがない。
- `production_smoke_without_aws` がpassしている。

### 8.4 NO-GO条件

- 「あとでS3から落とす」状態。
- S3だけにあるmanifestがある。
- AWS URLがstatic DBに残っている。
- accepted bundleのchecksumをAWS外で検証していない。
- rollback bundleがAWS外にない。
- post-teardown evidenceをCloudWatch Logsだけに置いている。

### 8.5 Export単位

巨大tarball一発ではなく、dataset sliceごとにexportする。

```text
exports/
  manifests/
  runtime_static/
  product_assets/
  local_archive/
  rejected_ledgers/
  cleanup_evidence/
```

利点:

- AWS自走中に段階的に救える。
- 一部sourceだけ失敗しても他assetを守れる。
- AWS credit消化が速くても、成果物喪失リスクを抑えられる。

## 9. 採用機能8: Production Smoke Without AWS

### 9.1 目的

AWS削除前に、productionがAWSなしで動くことを証明する。

### 9.2 Smoke条件

production smokeでは次を強制する。

```text
AWS network access disabled or blocked
S3 URL scan enabled
AWS ARN scan enabled
CloudWatch/Athena/OpenSearch endpoint scan enabled
runtime_aws_dependency_allowed=false
```

### 9.3 Smoke項目

| Area | Smoke |
|---|---|
| Static pages | proof pages load without AWS |
| Catalog | packet catalog loads from static/local DB |
| Pricing | cap/price preview returns catalog values |
| MCP | minimal tools return schema-valid response |
| API | route/preview/free controls work |
| Paid packet | low-cap fixture execution works |
| Receipts | claim refs resolve to source receipt metadata |
| Gaps | `known_gaps[]` and `gap_coverage_matrix[]` present |
| No-hit | `no_hit_not_absence` appears where needed |
| Rollback | previous bundle pointer works |
| Discovery | `llms.txt` and `.well-known` reference active bundle |
| AWS leak | no S3/ARN/Athena/OpenSearch/CloudWatch runtime references |

### 9.4 Smokeで失敗したら

失敗時はAWS teardownへ進まない。

対応:

1. active pointerを前bundleへ戻す。
2. 問題bundleを `accepted_not_active` または `rejected` へ戻す。
3. static DB manifestのAWS URL漏れ、checksum、catalog driftを再検査する。
4. 再smokeがpassするまでS3削除不可。

## 10. 採用機能9: Post-Teardown Cost Attestations

### 10.1 目的

AWS削除後も、現金請求が発生していないかを後日確認する。

ただし、この確認のためにAWS resourceを残してはいけない。

### 10.2 Attestation時点

推奨時点:

```text
T+0h: teardown直後 inventory zero
T+24h: billing/cost reflection check
T+72h: delayed cost check
T+month close: final bill check
```

### 10.3 保存先

attestationはAWS外に保存する。

推奨:

```text
/Users/shigetoumeda/jpcite_artifacts/aws-runs/{run_id}/post_teardown_attestations/
```

### 10.4 Attestation内容

```json
{
  "attestation_id": "att_20260516_001",
  "run_id": "aws_credit_run_20260515",
  "checked_at": "2026-05-16T10:00:00+09:00",
  "check_type": "t_plus_24h",
  "resource_inventory_zero_confirmed": true,
  "new_non_credit_charge_detected": false,
  "unexpected_service_cost_detected": false,
  "notes": [],
  "stored_outside_aws": true
}
```

### 10.5 矛盾修正

Cost Explorer APIやBilling系APIの利用自体にも注意が必要。

最終方針:

- teardown後確認は必要最小限にする。
- AWSに後日確認用scheduler/resourceを残さない。
- 確認結果はAWS外へ保存する。
- API利用にコストがある場合は、コンソール確認または最小回数の手動runbookにする。

## 11. 追加で採用したいスマート機能

### 11.1 Asset Value Acceptance Score

AWSで作ったassetを、本番投入価値で評価する。

```text
asset_value_acceptance_score =
  paid_output_coverage_gain
  + agent_recommendation_gain
  + evidence_reuse_gain
  + gap_reduction_gain
  - legal_terms_risk
  - public_exposure_risk
  - static_size_cost
```

用途:

- AWSで大量収集したあと、T0/T1へ入れるassetを選ぶ。
- 低価値large artifactをT2 archiveに落とす。
- accepted artifact率の低いsourceを次回抑制する。

### 11.2 Proof Page as Decision Page

proof pageは説明ページではなく、AI agentの購入判断ページにする。

必須要素:

- `what_this_packet_answers`
- `what_it_does_not_answer`
- `required_inputs`
- `public_sources_used`
- `known_gaps`
- `sample_output`
- `price_cap`
- `when_to_recommend`
- `when_not_to_recommend`
- `approval_token_flow`

これにより、GEOでAI agentが「買うべきか」を説明しやすくなる。

### 11.3 Receipt Reuse Cache

production runtimeでAWSに依存せず、source receiptを再利用する。

ただし「古いreceiptを真実として扱う」のではない。

```text
reuse allowed = same source_profile + same content_hash + within staleness_ttl + no superseding update known
```

効果:

- 安くなる。
- 速くなる。
- 同じ証跡を複数packetで使える。
- AI agentに「この出典は再利用済み」と説明しやすい。

### 11.4 Delta Bundle

AWS終了後の将来更新に備え、full bundleだけでなくdelta bundle形式も作る。

```text
base_bundle_20260515
delta_20260516
delta_20260517
```

今回のAWS runではdelta生成のschemaだけ作っておく。

これにより、将来AWSを使わず小さな更新でも運用できる。

### 11.5 Catalog Drift Firewall

packet catalog、pricing catalog、MCP tool schema、OpenAPI example、proof pageがずれたらrelease blockする。

```text
same packet_id
same input schema
same price cap
same free preview semantics
same no-hit caveat
same known gap policy
```

これを入れないと、AI agentが見ている説明とAPI実行結果がずれる。

## 12. 矛盾チェック

### C11-01: AWS自走とzero-billは矛盾しないか

判定: **条件付きPASS**。

矛盾しない条件:

- AWS自走制御面はteardown前まで。
- teardown後にEventBridge/Lambda/CloudWatchなどを残さない。
- 後日cost attestationはAWS外runbookで行う。

修正:

```text
AWS autonomous control plane is temporary.
Post-teardown verifier must not be AWS-hosted.
```

### C11-02: S3削除と成果物保持は矛盾しないか

判定: **External Export GateがあればPASS**。

S3を消す前に次が必要。

- T0/T1 runtime assets are outside AWS.
- T2 local archive is outside AWS.
- checksum verified.
- rollback bundle is outside AWS.
- production smoke without AWS passed.

### C11-03: Shadow releaseとGEO公開は矛盾しないか

判定: **分離すればPASS**。

shadow bundleはAI agentに見せない。

GEO向けに公開するのはactive bundleだけ。

shadow用のproof pageは公開index、`llms.txt`、`.well-known`、agent-safe OpenAPIから参照しない。

### C11-04: Pointer rollbackとstatic proof pageは矛盾しないか

判定: **proof page sidecarをbundle化すればPASS**。

proof pageがactive pointerとは別の古いassetを直参照すると壊れる。

修正:

```text
proof pages must resolve through active_dataset_pointer
or be generated per bundle with pointer-aware routing.
```

### C11-05: `site/static/assets/db` とrepo source pathは矛盾しないか

判定: **実装前固定が必要**。

現時点で固定すべきなのはURLとmanifest契約。

```text
runtime URL: /static/assets/db/{bundle_id}/static_db_manifest.json
source path: implementation-time decision based on current deploy pipeline
```

実装前に、Cloudflare/MkDocs/site生成の正本を確認して1つに固定する。

### C11-06: Post-teardown cost attestationとAPI課金は矛盾しないか

判定: **最小回数ならPASS**。

ただし、Cost Explorer API等の利用にコストがある可能性を前提にする。

修正:

- 自動で頻繁に叩かない。
- AWSにschedulerを残さない。
- 必要な時点だけ手動または非AWS runbookで確認する。
- 結果をAWS外に保存する。

### C11-07: 大量スクリーンショットとpublic proofは矛盾しないか

判定: **T2 archiveとT1 proof separationでPASS**。

raw screenshotはpublic proofに直接出さない。

public proofには:

- screenshot receipt id
- captured_at
- source URL
- content hash
- extracted text snippetへのclaim ref
- manual review flag

を出す。

必要な場合のみ、権利・PII・サイズ確認済みの小さなcrop/thumbnailを使う。

### C11-08: accepted artifact課金とfree previewは矛盾しないか

判定: **課金対象を明確にすればPASS**。

free preview:

- route
- price/cap
- required inputs
- likely packet
- known gap preview
- no purchase recommendation card

paid execution:

- accepted artifact generated
- source receipt ledger created
- claim refs attached
- billing metadata attached

`agent_routing_decision` は無料controlのまま。

## 13. 本体計画へマージすべき変更

以下を正本へ追加する。

### M11-01: Production SOT

```text
Production SOT is active_dataset_pointer + static_db_manifest + release_manifest.
AWS export is never production SOT.
```

### M11-02: Import transaction gate

```text
No AWS artifact may become active without import_transaction.status=accepted_not_active and all hard gates passing.
```

### M11-03: Rollback rule

```text
Rollback must work as pointer switch without AWS.
```

### M11-04: Zero-bill rule

```text
Teardown is not complete until zero_bill_guarantee_ledger says external_export_verified=true, production_smoke_without_aws=true, and resource_inventory_zero=true.
```

### M11-05: Post-teardown rule

```text
Post-teardown attestations are scheduled outside AWS. No AWS scheduler/resource remains for checking AWS.
```

### M11-06: Asset tier rule

```text
T0/T1 may be deployed. T2 is local archive only. T3 is excluded.
```

### M11-07: Static DB manifest rule

```text
Runtime code reads static_db_manifest. It must not directory-scan, S3-scan, or infer active files.
```

## 14. Implementation-ready function list

実装時に作るべき機能単位は次。

| Function | Purpose | Must exist before |
|---|---|---|
| `import_transaction_validator` | AWS exportをquarantineからacceptedへ上げる | RC1c |
| `static_db_manifest_builder` | T0/T1 asset manifest生成 | RC1a |
| `active_dataset_pointer_loader` | 本番がactive bundleを読む | RC1a |
| `pointer_rollback_command` | AWSなしrollback | RC1b |
| `shadow_release_runner` | candidate bundleを本番相当で検証 | RC1c |
| `aws_url_leak_scanner` | S3/ARN/AWS endpoint混入検出 | RC1a |
| `production_smoke_without_aws` | AWS遮断で本番smoke | teardown前 |
| `external_export_gate_checker` | S3削除前のAWS外保存検証 | full run前 |
| `zero_bill_guarantee_ledger_builder` | teardown証明ledger生成 | teardown時 |
| `post_teardown_attestation_runner` | 後日確認をAWS外で記録 | teardown後 |

## 15. 最終判断

このレビューの結論は、単に「本番デプロイを慎重にする」ではない。

よりスマートな方法は、jpciteを次の形にすること。

```text
AWSで大量に作る。
ただし本番はAWSを読まない。
本番が読むのは検証済みstatic bundleだけ。
切り替えはdeployではなくpointer。
rollbackもpointer。
zero-billはresource削除だけでなくledgerで証明。
後日確認はAWS外で行う。
```

これにより、以下が同時に成立する。

- AWS creditを速く使える。
- Codex/Claudeが止まってもAWS側はteardown前まで自走できる。
- 本番は早く出せる。
- 問題bundleだけ止められる。
- AWS削除後も本番が壊れない。
- 追加課金を避けられる。
- AI agentに見せるGEO surfaceと実API/packetがずれにくくなる。

最終採用推奨: **採用**。

この11/12レビューの改善は、本体正本に入れる価値が高い。特に `Transactional Artifact Import`、`Static DB Manifest`、`Pointer Rollback`、`Zero-Bill Guarantee Ledger` は実装前に必須化すべき。
