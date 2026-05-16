# AWS final consistency check 09/10: post-AWS assetization, retention, and zero-bill runtime

作成日: 2026-05-15  
担当: 最終矛盾チェック 9/10 / AWS終了後の資産化・データ保持  
対象AWS profile: `bookyou-recovery`  
対象AWS account: `993693061769`  
対象region: `us-east-1`  
実行状態: 計画精査のみ。AWS CLI/APIコマンド、AWSリソース作成、ジョブ投入、削除、本番デプロイは行っていない。  
出力制約: この1ファイルのみを作成する。  

## 0. 結論

判定は **条件付きPASS**。

AWSを短期のartifact factoryとして使い、クレジット消化後にS3を含むAWSリソースを削除し、productionをAWS非依存で動かす設計は成立する。ただし、現行計画をそのまま実行すると、次の5点で最後に矛盾する可能性がある。

1. `public/assets/db` と書かれているが、このrepoの実体は `public/` ではない。現状の配信実体は `site/`、契約・内部データは `data/`、公開docs sourceは `docs/` である。実装前に static DB の正本パスを固定しないと、AWS export後に「どこへimportすべきか」がぶれる。
2. zero-bill要件ではS3も削除する必要がある。一方でAWS自走中の成果物は一時的にS3へ置かれるため、AWS外export確認ゲートなしにcleanupへ進むと成果物を失う。
3. 大量のsource snapshot、PDF、OCR、screenshot receiptをrepoやstatic配信へ丸ごと入れると、デプロイサイズ、公開権利、配信速度、GEO品質の問題が出る。large artifactは「runtime最小DB」「local/offline archive」「再生成可能メタデータ」に分ける必要がある。
4. productionがS3、OpenSearch、Athena、Glue、Batchをruntimeで読む設計が混ざると、zero-bill cleanup後に本番・rollback・GEO proofが壊れる。
5. AWS終了後の更新頻度と再生成方法を決めないと、1回だけ巨大データを作っても、制度・補助金・処分・登録情報の鮮度が落ちて売れるpacketの価値が落ちる。

修正後の正本方針は次で固定する。

```text
AWS is temporary.
S3 is temporary.
Production reads only repo/static/local DB assets.
All valuable artifacts are exported outside AWS before teardown.
Only small, validated, deployable artifacts go into static runtime.
Large/audit artifacts go to non-AWS local archive.
Raw private CSV never goes to AWS, repo, static, archive, logs, or examples.
```

## 1. 精査対象

主に以下を前提に確認した。

- `aws_credit_unified_execution_plan_2026-05-15.md`
- `aws_credit_review_02_zero_bill_cleanup.md`
- `aws_credit_review_08_artifact_manifest_schema.md`
- `aws_scope_expansion_25_fast_spend_scheduler.md`
- `aws_scope_expansion_26_data_quality_gates.md`
- `aws_scope_expansion_28_production_release_train.md`
- `aws_scope_expansion_29_post_aws_assetization.md`
- `aws_scope_expansion_30_synthesis.md`
- `aws_final_consistency_01_global.md`
- `aws_final_consistency_02_aws_autonomous_billing.md`
- `aws_final_consistency_06_release_train.md`

このレビューではAWSコマンドは実行していない。ローカルファイルの読取と本Markdown作成のみ。

## 2. 最終SOTとして採用する終了状態

### 2.1 End State A: zero ongoing AWS bill

標準終了状態はこれだけにする。

```text
End State A: Zero ongoing AWS bill
```

条件:

- S3 bucket/object/version/delete marker/multipart uploadが残っていない。
- ECR repository/imageが残っていない。
- Batch queue/compute environment/job definitionが残っていない。
- ECS/EC2/EBS/snapshot/AMI/NAT/EIP/ELB/OpenSearch/Glue/Athena/CloudWatch/Lambda/Step Functions/EventBridgeが残っていない。
- AWS上にjpcite credit run用の成果物保存先が残っていない。
- productionはAWS network accessを切っても動く。
- rollback assetsもAWS外にある。
- Cost Explorer/Billingの遅延を前提に、翌日・3日後・月末後の確認を行う。

### 2.2 End State B: Minimal AWS Archiveは不採用

`Minimal AWS Archive`、つまりS3にfinal artifact bucketだけ残す案は、今回のユーザー要件に反する。

理由:

- S3 storage/requestは小額でも請求が残り得る。
- lifecycleや予算アラームを入れてもzero-billではない。
- 「AWS終了後にこれ以上請求しない」という上位制約と衝突する。

したがって、S3残置は本計画の標準には入れない。必要になった場合は別途、明示承認つきの例外運用として扱う。

## 3. パス正本の矛盾と修正

### 3.1 既存計画の矛盾

`aws_scope_expansion_29_post_aws_assetization.md` は `public/assets/db/{dataset_version}` を例示している。

一方、このrepoの現在の構造では:

- `public/` は存在しない。
- `site/` がCloudflare Pages側の静的配信実体として扱われている。
- `docs/` はMkDocsの公開docs source。
- `site/docs/` はMkDocs build output。
- `data/` はrepo内の契約・DB・設定・生成済みデータの置き場。

このまま `public/assets/db` を正本にすると、実装時に以下が起きる。

- import scriptが存在しないpathへ書く。
- productionが参照するURLとrepo内配置がずれる。
- build後の `site/` が生成物なのか正本なのか曖昧になる。
- cleanup後にS3を消した時、runtime DBの正しい保管先が不明になる。

### 3.2 修正後の配置

実装前に次の4層へ分ける。

| Layer | 役割 | 推奨path | git扱い |
|---|---|---|---|
| Contract source | schema, catalog, source profile, pricing, release gate | `data/aws_credit/contracts/` | 小さいものだけcommit |
| Import staging | AWS exportを検証してrepoへ入れる中間 | `data/aws_credit/imports/{dataset_version}/` | manifest中心、largeは除外 |
| Static runtime | productionが読む最小DB/index | `site/static/assets/db/{dataset_version}/` または実装時の正本static path | deploy対象 |
| Local archive | full export, large snapshot, OCR, screenshot, cleanup evidence | `/Users/shigetoumeda/jpcite_artifacts/aws-runs/{run_id}/` | git外 |

重要: `site/` が生成物として扱われる最終判断は、実装時にCI/deploy定義で確認する。もし `site/` がdeploy source-of-truthであるなら `site/static/assets/db` に置く。もしMkDocs/source buildへ寄せるなら `docs/assets/db` などのsource pathからbuildで `site/static/assets/db` へコピーする。

本レビューで固定するのは「productionが読むURLは `/static/assets/db/{dataset_version}/...` か同等の静的URLにし、AWS URLを読まない」ことであり、最終source pathは実装直前にrepoのdeploy pipelineへ合わせて1つに固定する。

### 3.3 禁止path

以下には置かない。

- AWS S3 final bucket
- AWS Athena result bucket
- AWS CloudWatch export
- `docs/_internal/` の巨大実データ
- git root直下の巨大DB
- `site/docs/assets/` のMkDocs vendor bundle付近
- raw private CSVが混ざる可能性のある場所

## 4. Export確認ゲート

### 4.1 必須ゲート

full-speed AWS run前に、次のゲートを必須化する。

```text
G2.5 External Export Gate
```

GO条件:

- AWS外の退避先が確定している。
- 退避先はrepo内小型assetと、repo外local archiveに分離されている。
- `export_manifest.json`、`artifact_manifest.jsonl`、`dataset_manifest.jsonl`、`checksum_ledger.sha256`、`cleanup_ledger.jsonl` の保存先がAWS外にある。
- exportは2-4時間ごと、またはdataset sliceごとに小分けで実行される。
- export完了後に `artifact_count`、`byte_size`、`sha256` が一致する。
- `production_smoke_without_aws=true` を確認してからS3削除へ進む。

NO-GO条件:

- S3に置いたまま後で落とす、という状態。
- ローカル端末が戻るまで成果物がS3にしかない状態。
- checksumなしの成果物がある状態。
- import target pathが未確定の状態。
- large artifactをgit/staticへ丸ごと入れようとしている状態。

### 4.2 Exportの最小単位

exportは巨大な1ファイルにしない。dataset slice単位にする。

```text
run_id/
  manifests/
    run_manifest.json
    artifact_manifest.jsonl
    dataset_manifest.jsonl
    checksum_ledger.sha256
    import_to_repo_plan.jsonl
    quality_gate_report.json
    cleanup_ledger.jsonl
  datasets/
    nta_houjin/
    nta_invoice/
    egov_law/
    egov_public_comment/
    jgrants/
    gbizinfo/
    estat/
    p_portal/
    enforcement/
    local_government/
  product_assets/
    packet_fixtures/
    proof_pages/
    geo_assets/
    pricing_assets/
  archive_only/
    screenshot_receipts/
    ocr_intermediates/
    raw_public_snapshots_allowed/
```

利点:

- 途中でCodex/Claudeが止まってもAWS側がsliceごとに成果物を閉じられる。
- 一部sourceがterms/qualityで落ちても他datasetを救える。
- S3削除前に不足sliceを特定できる。
- productionへ入れる小型assetだけ先にimportできる。

## 5. Checksumと検証連鎖

### 5.1 必須checksum

全artifactに次を持たせる。

```json
{
  "artifact_id": "art_...",
  "dataset_id": "ds_...",
  "path": "relative/path/from/export/root",
  "size_bytes": 123456,
  "sha256": "sha256:...",
  "canonical_content_sha256": "sha256:...",
  "source_profile_ids": ["..."],
  "quality_gate_status": "pass|review_required|reject",
  "repo_import_decision": "runtime_static|repo_contract|local_archive|exclude"
}
```

`sha256` はbyte完全性、`canonical_content_sha256` はJSONL正規化後の論理的同一性を見る。圧縮方式やsharding変更後も、正規化checksumで差分を比較できるようにする。

### 5.2 Import前のblocking条件

以下はimport blocker。

- `artifact_manifest.jsonl` にないファイル。
- `checksum_ledger.sha256` にないファイル。
- checksum mismatch。
- `repo_import_decision` がない。
- `quality_gate_status=reject`。
- `license_boundary` が不明。
- raw private CSV、secret、cookie、credential、session token、full HARが含まれる。
- `no_hit_not_absence` 以外のno-hit表現。
- paid packet claimに `claim_refs[]` がない。
- `claim_ref` が `source_receipt` へ解決しない。

### 5.3 Cleanup前のblocking条件

以下が1つでも残る場合、S3削除へ進まない。

- `exported_artifact_count != accepted_artifact_count + archived_artifact_count + rejected_artifact_count`
- required datasetのchecksum未検証。
- `cleanup_precheck` が未出力。
- local archiveの空き容量不足。
- production smokeがAWSなしで通っていない。
- rollback bundleがAWS外にない。

ただし、USD 19,300安全線に近づいた場合は、新規workとcomputeを止め、export確認だけを優先する。未検証artifactのために新規収集を続けない。

## 6. Large Artifact管理

### 6.1 分類

大きい成果物は3つに分ける。

| Class | 例 | 保管先 | production使用 |
|---|---|---|---|
| Runtime-min | normalized records, indexes, packet fixtures, source coverage summary | static runtime DB | yes |
| Archive-full | public source snapshots, screenshots, OCR text, extraction logs | local archive outside AWS | no |
| Regeneratable | temporary parse chunks, browser cache, retry scratch | 削除 | no |

### 6.2 Static runtimeへ入れてよいもの

- 小型JSON/JSONL shards。
- 圧縮済みSQLite/DuckDB/Parquet。ただし本番runtimeが実際に読める形式に限る。
- source coverage summary。
- proof page sidecar。
- packet fixture。
- pricing/cost preview metadata。
- no-hit ledgerの要約。
- claim graphの必要部分。

### 6.3 Static runtimeへ入れてはいけないもの

- full screenshot archive。
- full public HTML/PDF corpus。
- OCR intermediate。
- Playwright HAR。
- CloudWatch logs。
- raw source where redistribution is not clearly allowed。
- private CSV由来のrow、摘要、取引先名、銀行・給与・個人情報。
- 巨大DBを1枚で配信する設計。

### 6.4 Large artifactの上限方針

実装前に以下の上限を置く。

| Asset | 初期上限 | 超えた場合 |
|---|---:|---|
| one static JSON shard | 5-20 MB compressed | shard分割 |
| one static DB shard | 50-100 MB compressed | vertical/source単位に分割 |
| one proof page sidecar | 1 MB | summary化 |
| all RC1 runtime assets | 200 MB目安 | P0 packetに必要なもの以外をlocal archiveへ |
| local archive | disk容量に合わせる | external disk/non-AWS backupへ |

この数値は実装時のhosting制約で調整する。重要なのは、AWSで作った全量をそのままproduction assetにしないこと。

## 7. Production非AWS依存の確認

### 7.1 禁止runtime dependency

productionでは以下を禁止する。

- S3からruntime dataを読む。
- OpenSearchを検索backendにする。
- Athena/Glueをquery backendにする。
- Batch jobを同期実行する。
- CloudWatch Logsを証跡DBとして読む。
- AWS Secrets ManagerやParameter StoreをAWS credit run資産のために必須化する。
- AWS URLをproof pageやMCP responseに直接埋め込む。

### 7.2 許可されるtrace

AWSで作ったことのtraceは、manifest上の出自として残してよい。

```json
{
  "created_from": {
    "aws_account_id": "993693061769",
    "region": "us-east-1",
    "run_id": "aws-credit-2026-05-r001",
    "aws_resources_deleted_after_export": true
  },
  "runtime_dependency": {
    "aws_required": false
  }
}
```

これはruntime依存ではなく、監査上の出自である。

### 7.3 Smoke test

S3削除前に以下を通す。

```text
production_smoke_without_aws:
  - block network access to aws endpoints or run with AWS env vars absent
  - load homepage/proof pages
  - load /static/assets/db/current.json
  - render RC1 packet examples
  - call minimal MCP/API examples if local/staging runtime exists
  - verify no S3/OpenSearch/Athena/Glue URL is requested
  - verify rollback bundle exists outside AWS
```

AWSなしsmokeが通らない限り、zero-bill cleanupは始めない。

## 8. 再生成と更新頻度

### 8.1 1回限りのAWS全量run後の考え方

AWS credit runは初期巨大corpusを作るためのもの。AWS終了後は、毎回AWSを使わずに、差分更新・小型再生成・手動確認で運用する。

基本方針:

- full recrawlはしない。
- source familyごとに鮮度SLOを分ける。
- changed-only regenerationを標準にする。
- 期限が短い補助金・調達・公募は更新頻度を高くする。
- 法令・制度・許認可・処分は差分検知とstaleness表示を重視する。
- 更新できない範囲は `known_gaps[]` と `source_coverage` で明示する。

### 8.2 更新頻度案

| Source family | 更新頻度 | 理由 | AWS後の方法 |
|---|---:|---|---|
| NTA法人番号 | weekly/monthly | 安定ID、変更差分が重要 | local/offline script |
| NTAインボイス | weekly/monthly | 取引先確認で価値が高い | local/offline script |
| e-Gov法令 | weekly | 改正差分・施行日 | API/bulk差分 |
| e-Govパブコメ | daily/weekly | 募集・結果の鮮度 | RSS/API/HTML |
| J-Grants/補助金 | daily/weekly | 締切が売上に直結 | API/HTML差分 |
| 調達 | daily/weekly | 入札機会の鮮度 | portal差分 |
| 行政処分/ネガティブ情報 | weekly | DD/取引先確認 | official page diff |
| 官報/告示公告 | daily/weekly | 公示・公告・制度変更 | metadata + receipt |
| 自治体制度/条例 | monthly + canary | 範囲が広い | selected high-value自治体から |
| 統計/地理 | monthly/quarterly | 更新頻度低め | dataset release watch |
| standards/certification | monthly/quarterly | public metadata中心 | official index diff |

### 8.3 再生成単位

更新はpacket単位ではなく依存graphで切る。

```text
source change
-> affected source_receipts
-> affected claim_refs
-> affected extracted_records
-> affected packet_dependencies
-> affected proof pages
-> affected GEO examples
-> affected eval cases
```

例:

- J-Grantsが変わったら、`grant_opportunity_radar` と `csv_overlay_grant_match` を再生成する。
- NTAインボイスが変わったら、`invoice_vendor_public_check` と `company_public_baseline` を再生成する。
- e-Gov法令が変わったら、`reg_change_watch` と `permit_rule_check` の差分だけ再生成する。

### 8.4 再生成manifest

AWS後の更新runも、AWS runと同じ思想のmanifestを出す。

```text
local-update-runs/{date}/
  update_manifest.json
  changed_sources.jsonl
  affected_artifacts.jsonl
  regenerated_packets.jsonl
  checksum_ledger.sha256
  quality_gate_report.json
```

これにより、AWS初期資産とAWS後の差分資産が同じ証跡モデルで扱える。

## 9. 請求ゼロ確認

### 9.1 Zero-bill cleanup前の順序

cleanupは「S3を消す」から始めない。

正しい順序:

1. 新規投入停止。
2. EventBridge/Step Functions/SQS submitter停止。
3. Batch queue disable。
4. queued jobs cancel。
5. running jobs bounded drain or terminate。
6. OpenSearch/NAT/EC2/Fargate/Glue/Athenaなど高額・常駐系停止。
7. final export。
8. checksum verification。
9. local archive/import validation。
10. production smoke without AWS。
11. ECR/EBS/snapshot/CloudWatch/Glue/Athena result cleanup。
12. S3 object/version/delete marker/multipart cleanup。
13. S3 bucket deletion。
14. IAM/Budgets/control resources整理。
15. resource inventory。
16. 翌日・3日後・月末後のBilling確認。

### 9.2 請求ゼロの定義

`Zero-Bill Cleanup Done` と呼べる条件:

- jpcite credit run用のtagged resourcesが0。
- tag漏れを想定して主要サービスをservice別に棚卸し済み。
- S3 bucketが0。少なくともrun用bucketは0。
- CloudWatch log groupが0、またはrun用log groupが0。
- ECR repositoryが0。
- Batch/ECS/EC2/EBS/snapshot/OpenSearch/Glue/Athena/Lambda/Step Functions/EventBridgeが0。
- NAT Gateway/EIP/unused public IPv4/ENIが0。
- AWS外にexport manifest、checksum、cleanup evidenceがある。
- production/rollbackがAWSなしで動く。
- Cost Explorer/Billingで新規日次費用増がないことを遅延込みで確認する。

### 9.3 請求が残る典型事故

| 事故 | 原因 | 対策 |
|---|---|---|
| S3課金が残る | versioning, delete marker, multipart upload, result bucket | version/delete marker/multipartまで消す |
| CloudWatch課金が残る | verbose logs, retention未設定, log group残置 | log要約だけ外部保存しlog group削除 |
| OpenSearch課金が残る | benchmark domain削除忘れ | stretch serviceは早期終了、cleanup高優先 |
| EBS/snapshot課金が残る | EC2/Batch後のvolume/snapshot | instance終了後にvolume/snapshot inventory |
| NAT/EIP課金が残る | network構成の残骸 | NAT Gateway/EIP/ENIを明示棚卸し |
| Athena resultが残る | query output S3 | Athena workgroup/result bucket cleanup |
| Budget/IAMを先に消して止められない | cleanup権限喪失 | IAM/Budgetsは最後に整理 |

## 10. 本体計画へのマージ順

post-AWS資産化の観点では、全体順序を次に固定する。

```text
1. Contract freeze
2. Static/runtime asset path decision
3. Manifest/checksum/import gate implementation
4. External export gate dry-run
5. AWS guardrails and autonomous control
6. AWS canary export
7. Canary import into repo/static/local archive
8. RC1 static proof + minimal MCP/API production
9. AWS standard run with slice exports
10. Daily import of accepted artifacts
11. RC2/RC3 packet expansion from accepted assets
12. No-new-work at USD 18,900
13. Final export/checksum/import validation
14. Production smoke without AWS
15. Rollback bundle verification outside AWS
16. Zero-bill teardown including S3 deletion
17. Billing quiet follow-up
18. AWS後のchanged-only regeneration運用
```

この順序なら、AWSクレジット消化、本番早期投入、成果物保持、S3削除、請求ゼロが同時に成立する。

## 11. 本レビューでの改善提案

### 11.1 `public/assets/db` を抽象名に格下げする

既存文書に出てくる `public/assets/db` は、実装上の正本pathではなく「public static DB concept」として扱う。

実装時の候補:

```text
data/aws_credit/contracts/
data/aws_credit/imports/{dataset_version}/
site/static/assets/db/{dataset_version}/
site/static/assets/db/current.json
/Users/shigetoumeda/jpcite_artifacts/aws-runs/{run_id}/
```

最終的にはdeploy pipelineに合わせて1つに固定する。

### 11.2 `assetization_gate_report.json` を追加する

AWS final exportとは別に、repo/import側で次を出す。

```json
{
  "schema_id": "jpcite.assetization_gate_report",
  "dataset_version": "2026-05-aws-credit-run-01",
  "source_export_manifest_sha256": "sha256:...",
  "checksum_verification": "pass",
  "large_artifact_policy": "pass",
  "static_runtime_import": "pass",
  "local_archive_import": "pass",
  "private_csv_leak_scan": "pass",
  "aws_runtime_dependency_scan": "pass",
  "production_smoke_without_aws": "pass",
  "rollback_assets_outside_aws": "pass",
  "s3_deletion_allowed": true
}
```

`s3_deletion_allowed=true` になるまでS3削除へ進まない。

### 11.3 `aws_runtime_dependency_scan` をrelease blockerにする

検索対象:

- `s3://`
- `amazonaws.com`
- `opensearch`
- `athena`
- `glue`
- `batch`
- `AWS_`
- `AWS_ACCESS_KEY`
- `AWS_SECRET`

ただし、内部runbookやmanifest上の出自情報は例外にする。production runtime、public proof、MCP/API response、frontend bundleにAWS runtime URLやcredential前提が入ったらblockする。

### 11.4 Rollback assetsをAWS外に固定する

zero-bill teardown後はS3から戻せない。したがってrollback bundleはAWS外に置く。

最低限:

- previous static DB version
- previous `current.json`
- previous proof pages
- previous packet catalog
- previous OpenAPI/MCP manifest
- previous pricing map
- checksum ledger

## 12. 最終判定

現計画は、以下の修正を本体SOTへ入れれば矛盾なく進められる。

必須修正:

1. `public/assets/db` を仮称とし、repo実体に合わせたstatic DB正本pathを実装前に固定する。
2. `G2.5 External Export Gate` をfull-speed AWS run前の必須gateにする。
3. S3削除前に `assetization_gate_report.json` と `production_smoke_without_aws` を必須にする。
4. large artifactを `runtime-min`、`archive-full`、`regeneratable` に分ける。
5. rollback bundleをAWS外へ置く。
6. zero-billではS3を残さない。
7. AWS後のchanged-only regenerationとsource family別更新頻度を運用計画に入れる。

これで、ユーザー要件である「AWSクレジットは短期で使い切るが、それ以上のAWS請求は絶対に走らせない」「成果物やデータはAWS外に残す」「productionはAWS非依存で動く」は、1つの計画として成立する。

