# AWS smart methods round 2 review 05/06: production, release, runtime

作成日: 2026-05-15  
担当: 追加スマート方法検証 5/6 / Production, release, runtime  
対象: Transactional import, shadow release, pointer rollback, static DB manifest, zero-bill ledger, GEO公開, asset bundle管理, runtime軽量化, rollback, observability  
AWS前提: profile `bookyou-recovery` / account `993693061769` / region `us-east-1`  
実行状態: AWS CLI/APIコマンド、AWSリソース作成、削除、本番デプロイ、収集ジョブ実行は行っていない。ローカル計画検証のみ。  
出力制約: 本レビューではこのMarkdownだけを作成する。

## 0. 結論

判定: **追加採用余地あり。既存正本と矛盾しない。**

前回までの正本は大筋で正しい。

- AWSは一時的なartifact factoryであり、production runtimeではない。
- AWS成果物は `quarantine -> accepted bundle -> shadow release -> pointer switch` を通して出す。
- rollbackはAWS復旧ではなく、manifest pointerとfeature flagで戻す。
- S3を含めてAWS run resourceは最後に削除する。
- production smokeはAWSなしで通る必要がある。
- proof pageは `agent_decision_page` へ寄せる。
- free previewは `agent_purchase_decision` として返す。

さらにスマートにできる点は、production/runtimeを「APIがDBを読むシステム」ではなく、次のような **agent-visible static product runtime** に寄せること。

```text
validated asset bundle
  -> immutable release capsule
  -> static runtime index
  -> agent decision surfaces
  -> small deterministic execution facade
  -> pointer activation
  -> no-AWS runtime smoke
  -> zero-bill attestation
```

今回採用提案する追加機能は12個。

1. `Release Capsule`
2. `Dual Pointer Runtime`
3. `Capability Matrix Manifest`
4. `Agent Surface Compiler`
5. `Hot/Cold Static DB Split`
6. `Evidence Capsule Cache`
7. `Golden Agent Session Replay`
8. `Runtime Dependency Firewall`
9. `Progressive Exposure Lanes`
10. `Drift-Free Catalog Hash Mesh`
11. `Privacy-Preserving Product Telemetry`
12. `Zero-AWS Posture Attestation Pack`

これらは順番改善ではなく、production運用とruntimeを賢くする機能である。

## 1. 既存案との整合

### 1.1 維持する前提

今回の提案は以下を変更しない。

- `USD 19,300` 意図的上限。
- AWSは自走するが、production runtimeにはしない。
- zero-billのためS3も削除する。
- raw CSVはAWSにもpublic proofにも出さない。
- request-time LLMで事実主張を作らない。
- no-hitは `no_hit_not_absence`。
- paid packetはcap、approval token、idempotencyを必須にする。
- `agent_routing_decision` は無料control。
- public claimは `Public Packet Compiler` だけが作る。
- output推薦は `Output Composer` が行うが、事実claimは作らない。

### 1.2 既存案を置き換えないもの

今回の追加案は以下を置き換えない。

- `Transactional Artifact Import`
- `Shadow Release`
- `Pointer Rollback`
- `Static DB Manifest`
- `Zero-Bill Guarantee Ledger`
- `agent_purchase_decision`
- `agent_recommendation_card`
- `Output Composer + Public Packet Compiler`
- `Budget Token Market v2`
- `Source Operating System`

今回の提案は、それらの上に乗るproduction/runtime側の補強である。

## 2. 採用提案1: Release Capsule

### 2.1 問題

既存案では `release_manifest`、`static_db_manifest`、`rollback_manifest`、proof sidecar、OpenAPI、MCP、`llms.txt`、`.well-known` が別々の成果物として出る。

これは正しいが、運用時に次の事故が起きやすい。

- catalogだけ新しく、MCP examplesだけ古い。
- proof pageは新bundleを指すが、OpenAPIは旧pricingを示す。
- `llms.txt` は新packetを紹介するが、runtime flagがoff。
- rollback時にdataは戻るがagent-facing fileが戻らない。

### 2.2 提案

1回の本番候補を `Release Capsule` としてまとめる。

```text
release_capsules/
  rel_20260515_001/
    release_capsule.json
    active_dataset_pointer.candidate.json
    static_db_manifest.json
    packet_catalog.json
    pricing_catalog.json
    route_policy.json
    no_hit_policy.json
    mcp_agent_manifest.json
    openapi_agent.json
    llms.txt
    well_known_agents.json
    proof_index.json
    agent_examples.jsonl
    geo_replay_report.json
    production_smoke_report.json
    zero_aws_dependency_report.json
    rollback_manifest.json
    checksum_manifest.sha256
```

### 2.3 Capsule manifest

```json
{
  "object": "release_capsule",
  "release_id": "rel_20260515_001",
  "bundle_id": "bundle_20260515_003",
  "contract_version": "jpcite.packet.v1",
  "runtime_aws_dependency_allowed": false,
  "activation_status": "candidate",
  "surfaces": {
    "static_db_manifest": "static_db_manifest.json",
    "packet_catalog": "packet_catalog.json",
    "pricing_catalog": "pricing_catalog.json",
    "mcp_agent_manifest": "mcp_agent_manifest.json",
    "openapi_agent": "openapi_agent.json",
    "llms": "llms.txt",
    "well_known_agents": "well_known_agents.json",
    "proof_index": "proof_index.json"
  },
  "hashes": {
    "static_db_manifest_sha256": "...",
    "packet_catalog_sha256": "...",
    "pricing_catalog_sha256": "...",
    "mcp_agent_manifest_sha256": "...",
    "openapi_agent_sha256": "...",
    "well_known_agents_sha256": "..."
  },
  "quality_gates": {
    "schema": "pass",
    "catalog_hash_mesh": "pass",
    "agent_surface_compile": "pass",
    "geo_replay": "pass",
    "production_smoke_without_aws": "pass",
    "zero_aws_dependency": "pass",
    "forbidden_phrase": "pass",
    "csv_leak": "pass"
  },
  "activation_allowed": true
}
```

### 2.4 賢い点

本番は「ファイル群」をdeployするのではなく、「capsule」をactivateする。

利点:

- rollback対象が明確。
- GEO公開面とruntime catalogのdriftを防げる。
- AI agentが見るsurfaceのhashを一括で固定できる。
- AWS削除後も、何を本番に出したか証明できる。
- release note、smoke結果、zero-bill証跡を1つの単位で保存できる。

### 2.5 採用条件

採用。ただし `Release Capsule` はAWS上の恒久archiveではなく、AWS外へexportされたasset bundleとして扱う。

## 3. 採用提案2: Dual Pointer Runtime

### 3.1 問題

既存案のpointer rollbackは良い。ただし、data pointerだけだとコード/contractとのズレが残る。

例:

- APIコードは `packet.v2` を期待するが、active dataは `packet.v1`。
- `pricing_catalog` は新cap形式だが、runtimeが旧cap validator。
- proof page sidecarは新schemaだが、rendererが旧schema。

### 3.2 提案

pointerを2つに分ける。

```text
contract_runtime_pointer
active_release_capsule_pointer
```

本番runtimeは必ず両方を読む。

```json
{
  "object": "dual_pointer_runtime",
  "contract_runtime_pointer": {
    "contract_version": "jpcite.packet.v1",
    "min_runtime_version": "2026.05.15-rc1",
    "schema_compatibility": ["jpcite.packet.v1"]
  },
  "active_release_capsule_pointer": {
    "release_id": "rel_20260515_001",
    "bundle_id": "bundle_20260515_003",
    "static_db_manifest_sha256": "..."
  },
  "rollback": {
    "previous_release_id": "rel_20260515_000",
    "rollback_requires_code_deploy": false
  }
}
```

### 3.3 賢い点

- dataだけ戻してもruntimeが読めない事故を防ぐ。
- schema互換性をactivation前に判定できる。
- RC1a/RC1b/RC1cでruntime契約を固定しやすい。
- rollbackをpointer switchで済ませる条件が明確になる。

### 3.4 Release blocker

以下はblock。

- `contract_runtime_pointer.schema_compatibility` にcandidate bundle schemaがない。
- rollback先bundleを現runtimeが読めない。
- activationにcode deployが必要なのに、rollback planがpointer onlyになっている。

## 4. 採用提案3: Capability Matrix Manifest

### 4.1 問題

source familyやpacketの対応状況が増えると、AI agentやruntimeが「何ができるか」を誤認しやすい。

`known_gaps[]` はpacket結果には効くが、事前routingやGEO公開面にはもう少し粗い能力表が必要。

### 4.2 提案

`capability_matrix.json` をRelease Capsuleに含める。

```json
{
  "object": "capability_matrix",
  "release_id": "rel_20260515_001",
  "capabilities": [
    {
      "packet_type": "company_public_baseline",
      "visibility": "public",
      "executable": true,
      "billable": true,
      "max_cap_jpy": 330,
      "supported_inputs": ["corporate_number", "company_name"],
      "source_families": {
        "corporate_identity": "supported",
        "invoice_registry": "supported",
        "business_registry_signal": "partial",
        "enforcement_disposition": "not_in_this_packet"
      },
      "known_global_gaps": [
        "public sources may lag official changes",
        "no-hit is not proof of absence"
      ],
      "agent_recommendation_status": "recommendable"
    }
  ]
}
```

### 4.3 使い道

- `jpcite_route` が対応外依頼を早く落とせる。
- `jpcite_preview_cost` が有料実行前に「このreleaseではできない」と言える。
- `.well-known` がagentに現在能力を伝えられる。
- proof pageが過剰に約束しない。
- GEO evalが「推薦してよいpacketだけ」を判定できる。

### 4.4 採用判断

採用。`capability_matrix` は売上に直結する。AI agentが誤推薦せず、かつ推薦可能なpacketを見つけやすくなる。

## 5. 採用提案4: Agent Surface Compiler

### 5.1 問題

agent-facing surfaceが手作業で増えると、GEO向け公開面がズレる。

ズレやすいsurface:

- `llms.txt`
- `.well-known/agents.json`
- MCP manifest
- agent-safe OpenAPI
- proof pages
- packet examples
- pricing examples
- no-hit examples
- `agent_recommendation_card`

### 5.2 提案

これらを人手で別々に書かない。

`Release Capsule` から `Agent Surface Compiler` が生成する。

```text
release_capsule
  -> compile_agent_surfaces()
    -> llms.txt
    -> .well-known/agents.json
    -> agent_openapi.json
    -> mcp_agent_manifest.json
    -> proof_index.json
    -> agent_examples.jsonl
    -> agent_decision_pages
```

### 5.3 Compiler input

Compilerは以下だけを正本入力にする。

- `packet_catalog.json`
- `pricing_catalog.json`
- `capability_matrix.json`
- `no_hit_policy.json`
- `route_policy.json`
- `proof_index.source.json`
- `agent_recommendation_card` templates
- `decision_object` examples

### 5.4 Compiler output gate

生成後に以下を検査する。

- catalog hashが全surfaceで一致する。
- price/capが一致する。
- `agent_routing_decision` が有料扱いになっていない。
- forbidden phraseがない。
- no-hit caveatがある。
- full paid outputをproof pageへ漏らしていない。
- 実CSV由来データがない。
- AWS URL、S3 URL、ARN、CloudWatch URLがない。

### 5.5 賢い点

GEO公開はコンテンツ量ではなく、一貫性が重要。

Agent Surface Compilerを入れると、AI agentはどのsurfaceを見ても同じpacket、同じ価格、同じcap、同じno-hit policyへ辿れる。

## 6. 採用提案5: Hot/Cold Static DB Split

### 6.1 問題

AWS credit run後のデータは大きくなる。

全部をruntime static DBに入れると、次の問題が起きる。

- deploy artifactが重い。
- cold startが重い。
- proof page生成が遅い。
- rollbackが重い。
- public配信してはいけない監査用データが混じる危険が増える。

### 6.2 提案

T0/T1/T2/T3のassetization tierに加えて、runtime T0をさらにHot/Coldへ分ける。

| Layer | 内容 | 本番runtime利用 | 配信 |
|---|---|---:|---:|
| `T0-hot` | routing, catalog, pricing, capability, small lookup, proof sidecar index | 常時 | 可 |
| `T0-cold` | source receipt shard, claim ref shard, no-hit ledger shard | 必要時のみ | 可、ただしchunk化 |
| `T1-public-proof` | agent decision page, examples, cards | 常時 | 可 |
| `T2-audit` | raw-ish public snapshots, screenshots, OCR intermediate, full ledger | 通常不可 | 不可 |

### 6.3 Hot layer

Hot layerは小さく保つ。

含める:

- packet catalog
- pricing catalog
- route policy
- no-hit policy
- capability matrix
- source family coverage summary
- proof index
- chunk index
- popular company/source lookup index where legally allowed

含めない:

- full source receipt body
- raw screenshots
- OCR全文
- large PDFs
- HAR
- Athena outputs

### 6.4 Cold chunk

Cold layerはcontent-addressed chunkにする。

```text
static_db/
  hot/
    capability_matrix.json
    route_policy.json
    packet_catalog.json
    pricing_catalog.json
    chunk_index.json
  cold/
    source_receipts/
      sha256_abcd.jsonl.zst
      sha256_efgh.jsonl.zst
    claim_refs/
      sha256_1234.jsonl.zst
```

### 6.5 賢い点

- runtimeが軽い。
- rollbackでhot pointerだけ先に戻せる。
- proof pageは必要なcold chunkだけ参照できる。
- AWS削除後もstatic chunkだけで再現できる。
- 大量の監査用データをpublic runtimeへ混ぜない。

### 6.6 採用条件

採用。ただしT0-coldはpublicに置いてよい情報だけに限定する。T2 audit archiveとは混ぜない。

## 7. 採用提案6: Evidence Capsule Cache

### 7.1 問題

毎回、巨大な `source_receipts[]` と `claim_refs[]` からpacketを組み立てると重い。

一方で、paid packetのclaimは証跡付きでなければならない。

### 7.2 提案

頻出packetやproof用に、最小証跡だけを束ねた `Evidence Capsule` を作る。

```json
{
  "object": "evidence_capsule",
  "capsule_id": "ecap_company_public_baseline_001",
  "packet_type": "company_public_baseline",
  "subject_key": "corporate_number:1234567890123",
  "claim_refs": ["claim_001", "claim_002"],
  "source_receipt_refs": ["receipt_001", "receipt_002"],
  "known_gap_refs": ["gap_001"],
  "no_hit_refs": ["nohit_001"],
  "support_levels": {
    "claim_001": "official_api",
    "claim_002": "official_public_page"
  },
  "public_safe": true,
  "paid_full_output_included": false,
  "sha256": "..."
}
```

### 7.3 使い道

- `company_public_baseline` のRC1 paid executionを軽くする。
- proof pageはcapsule summaryだけを見せる。
- agent previewは「このpacketでどのsource familyが使われるか」を即返せる。
- rollback時にcapsule単位で戻せる。
- receipt再利用を価格に反映しやすい。

### 7.4 注意点

Evidence Capsuleは「有料成果物の全量」ではない。

public proofへ出せるのは:

- support summary
- source family
- known gap
- no-hit caveat
- sample claim shape

出してはいけないもの:

- full paid answer
- raw screenshot
- OCR全文
- private CSV-derived fact
- sensitive source detail that redistribution policy disallows

### 7.5 採用判断

採用。runtime軽量化とGEO販売素材の両方に効く。

## 8. 採用提案7: Golden Agent Session Replay

### 8.1 問題

既存案のshadow replayはquery差分を見ている。さらにGEO主戦なら、AI agentが実際にどう推薦するかをsession単位で検査した方がよい。

### 8.2 提案

`Golden Agent Session Replay` をrelease gateにする。

1つのsessionは以下を含む。

```text
user request
-> route
-> preview decision
-> agent recommendation card
-> optional approval
-> execute packet
-> get packet
-> safe user-facing explanation
```

### 8.3 Replay case

RC1必須session:

1. 会社名だけで `company_public_baseline` preview。
2. 法人番号ありで `company_public_baseline` paid。
3. インボイス確認で `invoice_vendor_public_check` へ誘導。
4. 取引先リスクを求められたが、RC1では安いbaselineを先に薦める。
5. 行政処分まで見たい場合、上位packetまたは未対応gapを説明。
6. no-hitを不存在証明にしそうな依頼を安全に止める。
7. 法的判断を求められた場合、human reviewを明示。
8. CSV uploadを求められた場合、public proofへ出さずprivate overlay方針を説明。

### 8.4 評価項目

```json
{
  "geo_session_eval": {
    "route_correct": true,
    "cheapest_sufficient_packet_correct": true,
    "recommendation_not_oversold": true,
    "price_cap_present": true,
    "approval_required_before_paid": true,
    "no_hit_caveat_present": true,
    "known_gaps_present": true,
    "forbidden_phrase_absent": true,
    "aws_dependency_absent": true,
    "full_paid_output_not_leaked_in_preview": true
  }
}
```

### 8.5 賢い点

GEOでは「ページが存在する」だけでは足りない。

AI agentが正しく売る、売りすぎない、安いpacketを薦める、限界を説明する、という会話品質をrelease前に固定できる。

## 9. 採用提案8: Runtime Dependency Firewall

### 9.1 問題

`runtime.aws_dependency.allowed=false` は良いが、実装後に依存が紛れ込む危険がある。

例:

- 本番envにAWS credentialが残る。
- SDK importがproduction bundleに入る。
- fallbackとしてS3 URLを読む。
- CloudWatch/Athena/OpenSearch endpointがconfigに残る。
- proof pageのasset URLにS3が残る。

### 9.2 提案

CI/release gateとして `Runtime Dependency Firewall` を入れる。

チェック対象:

- source code
- built artifact
- static assets
- env var manifest
- `.well-known`
- OpenAPI/MCP
- proof pages
- packet examples
- release capsule

検出する文字列/構造:

```text
amazonaws.com
s3://
arn:aws:
AWS_ACCESS_KEY_ID
AWS_SECRET_ACCESS_KEY
AWS_SESSION_TOKEN
athena.
cloudwatch.
opensearch.
batch.
states.
events.
```

### 9.3 許容例外

docs/internalに過去計画として出る文字列は許容。ただしpublic build artifactには不可。

例外はmanifestで明示する。

```json
{
  "allowed_aws_mentions": [
    {
      "path": "docs/_internal/aws_jpcite_master_execution_plan_2026-05-15.md",
      "reason": "internal plan, not public runtime"
    }
  ]
}
```

### 9.4 Release blocker

public runtime artifactにAWS credential/env/URL/ARNが出たらblock。

これはzero-billだけでなく、securityと信頼性の問題でもある。

## 10. 採用提案9: Progressive Exposure Lanes

### 10.1 問題

RC1a/RC1b/RC1cの段階分けは良い。ただし本番露出の単位が粗いと、失敗時に止めすぎる。

### 10.2 提案

feature flagをさらに「露出レーン」として管理する。

| Lane | 対象 | 課金 | 目的 |
|---|---|---:|---|
| `internal_shadow` | 開発者/検証のみ | off | schema, smoke, replay |
| `agent_discovery` | `llms`, `.well-known`, proof index | off | GEO発見 |
| `free_decision` | route, preview, decision object | off | AI推薦判断 |
| `limited_paid` | RC1 paid low cap | on low cap | 初回売上検証 |
| `expanded_paid` | RC2/RC3 vertical packets | on cap | 成果物拡大 |
| `monitoring_only` | 新sourceの差分/鮮度表示 | off/on optional | 継続価値 |

### 10.3 賢い点

- GEO公開だけ先に出せる。
- paidだけ止めてもagent discoveryは残せる。
- sourceに問題があるpacketだけ停止できる。
- rollbackが全体deployではなくlane単位になる。

### 10.4 Required flag fields

```json
{
  "feature_flag": "packet.company_public_baseline",
  "visibility": true,
  "executable": true,
  "billable": true,
  "max_cap_jpy": 330,
  "allowed_lanes": ["free_decision", "limited_paid"],
  "release_id": "rel_20260515_001",
  "kill_switch_ready": true
}
```

## 11. 採用提案10: Drift-Free Catalog Hash Mesh

### 11.1 問題

catalog driftは既存案にあるが、hashの結び方をもう少し強くできる。

### 11.2 提案

すべてのagent-facing surfaceに同じ `catalog_hash_mesh` を埋める。

```json
{
  "catalog_hash_mesh": {
    "release_id": "rel_20260515_001",
    "packet_catalog_sha256": "...",
    "pricing_catalog_sha256": "...",
    "capability_matrix_sha256": "...",
    "no_hit_policy_sha256": "...",
    "route_policy_sha256": "...",
    "mcp_manifest_sha256": "...",
    "openapi_agent_sha256": "...",
    "llms_txt_sha256": "...",
    "well_known_agents_sha256": "..."
  }
}
```

### 11.3 Gate

Activation前に以下を検査する。

- `.well-known` が指すcatalog hashと実体が一致する。
- MCP manifestのpacket IDがpacket catalogに存在する。
- OpenAPI examplesの価格がpricing catalogと一致する。
- proof pageのpacket IDがcapability matrixに存在する。
- `agent_recommendation_card` のcap金額がpricing catalogと一致する。
- no-hit説明がno-hit policyと一致する。

### 11.4 賢い点

AI agentは複数surfaceを読む。どこか1つが古いだけで誤推薦が起きる。

Hash meshにより、GEO公開面全体を1つの整合した商品面として扱える。

## 12. 採用提案11: Privacy-Preserving Product Telemetry

### 12.1 問題

production後、どのpacketが売れるか、どのpreviewが購入に繋がるか、どのagent surfaceが見られているかを知らないと改善できない。

一方で、raw user request、CSV、会社名、個人情報を安易にログへ残すと計画の安全性と矛盾する。

### 12.2 提案

個別入力を保存せず、商品改善に必要な最小イベントだけを記録する。

```json
{
  "event": "preview_decision_returned",
  "release_id": "rel_20260515_001",
  "packet_type": "company_public_baseline",
  "decision": "recommend_paid_packet",
  "price_band": "0-500_jpy",
  "known_gap_count": 2,
  "source_family_count": 3,
  "agent_surface": "mcp",
  "converted_to_paid": false,
  "raw_input_logged": false,
  "csv_data_logged": false
}
```

### 12.3 禁止

telemetryに入れない。

- raw user request
- company name
- corporate number
- CSV row/value/header from real user
- uploaded file name
- memo field
- personal name
- bank/payroll fields
- full generated answer
- source page raw screenshot

### 12.4 指標

見るべき指標:

- preview -> paid conversion by packet type
- `cheapest_sufficient_packet` acceptance rate
- reason_not_to_buy distribution
- known gap causing drop-off
- no-hit explanation frequency
- agent surface path: `.well-known`, `llms`, MCP, OpenAPI, proof page
- packet cap hit rate
- rollback frequency
- release capsule activation failure reason

### 12.5 賢い点

売上改善に必要なのは個人データではなく、商品単位のdecision funnelである。

このtelemetryがあれば、AWS終了後も「次にどのsourceを取るべきか」「どのpacketが売れるか」を判断できる。

## 13. 採用提案12: Zero-AWS Posture Attestation Pack

### 13.1 問題

Zero-bill ledgerは既存案にある。ただし、あとから見た時に「本番がAWSなしで動いている」「AWS資産が残っていない」「public artifactにAWS依存がない」を1パックで説明できると強い。

### 13.2 提案

AWS teardown後に `Zero-AWS Posture Attestation Pack` を作る。

```text
zero_aws_attestations/
  zat_20260515_001/
    zero_bill_guarantee_ledger.json
    external_export_verified.json
    resource_inventory_zero.json
    production_smoke_without_aws.json
    runtime_dependency_firewall_report.json
    public_artifact_aws_url_scan.json
    active_release_capsule.json
    checksum_manifest.sha256
    next_billing_check_schedule.md
```

### 13.3 注意

post-teardown check自体をAWS EventBridge/Lambdaに置かない。

理由:

- それ自体がAWSリソースとして残る。
- zero-bill postureと矛盾する。

post-teardownの確認はAWS外のローカル/別環境/手動CLIで行う。

### 13.4 賢い点

単に「削除した」ではなく、次を証明できる。

- 本番はAWSなしで動く。
- active release capsuleはAWS URLを含まない。
- rollback先もAWSなしで動く。
- AWS resource inventoryはゼロ。
- 監査用成果物はAWS外にある。
- 次回請求確認の手順が残っている。

## 14. 本番runtimeの最終像

### 14.1 Runtime components

```text
Small deterministic API/MCP facade
  reads:
    active_release_capsule_pointer
    contract_runtime_pointer
    T0-hot static DB
    selected T0-cold chunks
  never reads:
    AWS S3
    Athena
    OpenSearch
    CloudWatch
    raw screenshots
    OCR intermediate
    real CSV raw data
```

### 14.2 Request flow

無料preview:

```text
request
  -> route policy
  -> capability matrix
  -> Output Composer
  -> agent_purchase_decision
  -> agent_recommendation_card
  -> no paid claim generated
```

有料packet:

```text
approved request
  -> cap token / approval token check
  -> Public Packet Compiler
  -> Evidence Capsule / source receipt lookup
  -> packet envelope
  -> billing metadata
  -> idempotent packet id
```

Proof page:

```text
agent_decision_page
  -> packet summary
  -> source family coverage
  -> known gaps
  -> no-hit caveat
  -> cheapest sufficient option
  -> MCP/API call sequence
  -> no full paid output leak
```

### 14.3 Runtime hard rules

- runtime cannot fetch AWS.
- runtime cannot call request-time LLM for facts.
- runtime cannot expose raw CSV.
- runtime cannot claim unsupported facts.
- runtime cannot use OCR-only facts as paid claims.
- runtime cannot show `eligible`, `safe`, `no issue`, `permission not required`, generic `risk score`.
- runtime cannot execute paid packet without approval token and cap.

## 15. GEO公開の追加改善

### 15.1 `agent_release_note.json`

AI agent向けに、releaseごとの変更点を機械可読で出す。

```json
{
  "object": "agent_release_note",
  "release_id": "rel_20260515_001",
  "new_recommendable_packets": ["company_public_baseline"],
  "changed_prices": [],
  "new_source_families": ["corporate_identity", "invoice_registry"],
  "do_not_recommend": [
    {
      "packet_type": "permit_scope_checklist_packet",
      "reason": "not executable in this release"
    }
  ],
  "recommended_agent_actions": [
    "Use jpcite_route first",
    "Use jpcite_preview_cost before paid execution",
    "Explain no-hit as no_hit_not_absence"
  ]
}
```

### 15.2 `agent_changefeed.jsonl`

releaseごとのdeltaをagentが追えるようにする。

```json
{"date":"2026-05-15","release_id":"rel_20260515_001","event":"packet_recommendable","packet_type":"company_public_baseline"}
{"date":"2026-05-15","release_id":"rel_20260515_001","event":"source_family_added","source_family":"invoice_registry"}
```

### 15.3 賢い点

GEOは「初回発見」だけではない。AI agentが次回以降も「何が増えたか」「今薦めてよいか」を判断できると推薦されやすい。

## 16. Observabilityの追加改善

### 16.1 Runtime observability

runtimeは以下を観測する。

- release_id
- packet_type
- route decision
- preview decision
- cap band
- paid conversion
- packet compile success/failure
- forbidden phrase gate failure
- known gap count
- source family coverage count
- no-hit caveat presence
- latency band
- rollback activation

### 16.2 観測しないもの

- raw request
- company name
- corporate number
- uploaded CSV filename
- CSV content
- packet full answer
- screenshot/OCR/HAR content
- personal data

### 16.3 Product learning loop

telemetryは次へ返す。

```text
preview drop-off
  -> reason_not_to_buy
  -> output_gap_map
  -> source_candidate_registry
  -> next AWS/source expansion only if value-backed
```

AWS終了後も、次のsource拡張やpacket改善をデータで決められる。

## 17. 矛盾チェック

### 17.1 Zero-billとの矛盾

判定: PASS。

今回の追加案はAWS恒久利用を増やさない。

- Release CapsuleはAWS外に置く。
- Runtime Dependency FirewallはAWS依存を減らす。
- Zero-AWS Attestation PackはAWS外で保存する。
- post-teardown scheduled checkをAWS上に置かない。

### 17.2 GEO-firstとの矛盾

判定: PASS。

Agent Surface Compiler、agent release note、capability matrix、agent changefeedはGEOを強化する。

SEO記事量産には寄せていない。

### 17.3 Public Packet Compilerとの矛盾

判定: PASS。

Output Composerやagent previewはclaimを作らない。Evidence Capsuleも最小証跡cacheであり、claim生成権限はPublic Packet Compilerに残す。

### 17.4 CSV privacyとの矛盾

判定: PASS。

telemetryとruntime assetにreal CSV由来データを入れない。CSVはprivate overlayであり、public proofやGEO surfaceには出さない。

### 17.5 AWS高速消費との矛盾

判定: PASS。

この提案はAWS実行を遅くするものではない。むしろAWS成果物をproductionへ入れるacceptance pathを明確にし、後段の詰まりを減らす。

ただし、AWS full run開始前に最低限必要なのは以下。

- Release Capsule schema
- Capability Matrix schema
- Runtime Dependency Firewallのscan rule
- Hot/Cold split方針

これらは軽量なので、AWS canary前に実装可能。

## 18. 採用しない案

以下は一見スマートだが、既存方針と矛盾するため採用しない。

### 18.1 Live AWS lookup fallback

不採用。

理由:

- production AWS非依存と矛盾。
- zero-billと矛盾。
- requestごとのコスト/遅延/障害が増える。

### 18.2 S3 final public archive

不採用。

理由:

- S3を残すとzero-billではない。
- public proofにraw/large artifactが混じる危険が増える。

### 18.3 Full paid outputをproof pageへ載せる

不採用。

理由:

- 売上を毀損する。
- proof pageはagent decision pageであり、paid output置き場ではない。

### 18.4 Raw analytics logging

不採用。

理由:

- privacy/securityリスクが高い。
- 商品改善にはpacket-level telemetryで足りる。

### 18.5 Schema-breaking releaseをpointerだけで切り替える

不採用。

理由:

- pointer rollbackの前提が崩れる。
- Dual Pointer Runtimeでschema compatibilityを先に確認すべき。

## 19. 正本計画への追記提案

正本へ入れるなら、`Final smart-method addendum` のproduction/runtime subsectionとして以下を追記する。

```text
Adopt Release Capsule as the unit of production activation.
Adopt Dual Pointer Runtime so release bundles and runtime contracts cannot drift.
Adopt Capability Matrix Manifest so agents and runtime know what is currently recommendable, executable, and billable.
Adopt Agent Surface Compiler so llms.txt, .well-known, MCP, OpenAPI, proof pages, examples, pricing, and no-hit policy are generated from the same release capsule.
Adopt Hot/Cold Static DB Split to keep runtime light and separate public runtime data from local audit archive.
Adopt Evidence Capsule Cache for frequently used proof-carrying packet execution and preview support.
Adopt Golden Agent Session Replay as a GEO/recommendation release gate.
Adopt Runtime Dependency Firewall to block AWS URLs, SDK/env dependencies, S3 references, and raw artifact leaks from public runtime.
Adopt Progressive Exposure Lanes so discovery, free decision, and limited paid execution can be exposed independently.
Adopt Drift-Free Catalog Hash Mesh across all agent-facing surfaces.
Adopt Privacy-Preserving Product Telemetry using only packet-level decision funnel events.
Adopt Zero-AWS Posture Attestation Pack after teardown.
```

## 20. Implementation sketch

### 20.1 Minimal schemas before AWS canary

Implement lightweight JSON schemas for:

- `release_capsule`
- `capability_matrix`
- `dual_pointer_runtime`
- `catalog_hash_mesh`
- `agent_release_note`
- `zero_aws_attestation_pack`

### 20.2 Minimal gates before RC1a

Implement:

- Agent Surface Compiler for static files.
- Runtime Dependency Firewall scan.
- Golden Agent Session Replay for 8 RC1 cases.
- Capability Matrix generation for RC1 packets.
- Release Capsule activation check.

### 20.3 Minimal runtime for RC1b/RC1c

Implement:

- active release capsule loader
- T0-hot static DB reader
- `jpcite_route`
- `jpcite_preview_cost`
- `jpcite_execute_packet`
- `jpcite_get_packet`
- paid cap and approval token check
- packet-level telemetry without raw input logging

## 21. Final recommendation

今回の追加検証で、さらにスマートな方法は出た。

最も重要なのは、productionを「AWS成果物の置き場」ではなく、**検証済みRelease CapsuleをAI agentに見せる軽量runtime** として設計すること。

最終形:

```text
AWS artifact factory
  -> transactional import
  -> release capsule
  -> agent surface compiler
  -> shadow release
  -> golden agent replay
  -> dual pointer activation
  -> progressive exposure
  -> runtime dependency firewall
  -> production without AWS
  -> zero-AWS attestation pack
```

この形にすると、既存計画より次が強くなる。

- 本番が軽い。
- rollbackが速い。
- GEO surfaceがdriftしにくい。
- AI agentが推薦しやすい。
- 売上に必要なpreview/decisionが一貫する。
- AWS削除後も本番と証跡が残る。
- zero-billを説明しやすい。

よって、本レビューの追加12機能は正本計画へ採用候補として入れる価値がある。
