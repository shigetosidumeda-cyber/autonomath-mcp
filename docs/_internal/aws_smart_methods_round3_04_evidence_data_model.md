# AWS smart methods round3 04: evidence graph / data model

作成日: 2026-05-15
担当: Round3 追加スマート化 4/20 / Evidence graph, data model, source evolution
対象: jpcite master execution plan, Official Evidence Knowledge Graph, Bitemporal Claim Graph, No-Hit Lease Ledger, Claim Derivation DAG, Conflict-Aware Truth Maintenance
制約: AWS CLI/API実行なし。AWSリソース作成なし。既存コード変更なし。
出力: `/Users/shigetoumeda/jpcite/docs/_internal/aws_smart_methods_round3_04_evidence_data_model.md` のみ。

---

## 0. 結論

判定: **追加価値あり。Round2の証拠グラフ案は正しいが、まだ「概念」として大きい。Round3では、実行可能なデータモデル、query、storage、asset化、source evolution管理へ落とすべき。**

一番スマートな修正はこれである。

> jpciteの証拠グラフを、常時稼働する巨大DBではなく、event-sourcedな `Official Evidence Ledger` から、packet別の小さな `Evidence Lens` をコンパイルする仕組みにする。

これにより、以下を同時に満たせる。

- AWS終了後にruntime DBを残さない。
- zero-bill teardownと矛盾しない。
- Release Capsuleに軽量な証拠viewを入れられる。
- 内部再検証用にはreplay bundleを残せる。
- no-hit、schema drift、source evolution、conflictを時点つきで管理できる。
- AIエージェントには「必要十分な証拠」だけを見せられる。

今回採用すべき追加機能は次の12個。

1. `Official Evidence Ledger`: graphの正本をappend-only ledgerにする。
2. `Evidence Lens`: packet / proof / agent decisionごとの投影viewを作る。
3. `Claim Stable Key`: source変更や再取得を跨いでclaimを追跡する安定キー。
4. `Temporal Envelope`: observed / valid / published / compiled / retired を分離する時点モデル。
5. `EvidenceQL`: graph queryをCypher依存にせず、JSON/Datalog風の移植可能queryとして定義する。
6. `Source Evolution Ledger`: sourceのschema、terms、URL、capture method、adapterの進化をledger化する。
7. `Schema Contract ABI`: source adapterとpacket compilerの間に互換contractを置く。
8. `Proof Set Optimizer`: packetに必要十分な最小証拠集合を選ぶ。
9. `Conflict Bundle`: 矛盾を単なるエラーではなく、packetで表示可能な構造にする。
10. `No-Hit Lease Index`: no-hit leaseをsource/subject/scope/expiryで高速に検索する。
11. `Replayable Derivation Runtime`: Claim Derivation DAGを再実行可能な変換ledgerにする。
12. `Graph Integrity Gate`: Release Capsule前の必須gateにする。

この設計は既存正本と矛盾しない。ただし、正本計画へマージする際に以下の表現は修正すべき。

| 現在の危険な解釈 | 修正後 |
|---|---|
| Knowledge Graphを真実DBとして扱う | Evidence Ledger + Evidence Lensとして扱う |
| no-hitをcacheとして扱う | lease付き観測として扱う |
| source qualityを信頼スコアとして扱う | operational metric / support metricとして扱う |
| graphをproduction runtimeのDBとして扱う | Release Capsule内の静的viewとして扱う |
| screenshot/OCRを直接claim根拠にする | support_stateに応じて候補/補助に落とす |
| schema drift後も同じpacket schemaへ自動投入する | Schema Evolution Firewallでquarantineし、adapter contractを通す |

---

## 1. 既存計画との整合

### 1.1 維持する前提

今回の提案は、次の前提を変更しない。

- GEO-first。
- AIエージェントがエンドユーザーに推薦する。
- paid packetは `source_receipts[]`、`claim_refs[]`、`known_gaps[]`、`gap_coverage_matrix[]`、`billing_metadata` を持つ。
- `agent_routing_decision` は無料control。
- request-time LLMで事実claimを作らない。
- real private CSVはAWSに入れない。
- no-hitは `no_hit_not_absence`。
- AWSは一時的なartifact factoryであり、本番runtimeではない。
- S3を含めAWS resourcesは最終削除する。

### 1.2 Round2案から深掘りする対象

Round2で採用済みの次を、今回さらに具体化する。

- `Official Evidence Knowledge Graph`
- `Bitemporal Claim Graph`
- `Source Twin Registry`
- `Semantic Delta Compressor`
- `Update Frontier Planner`
- `Claim Derivation DAG`
- `Conflict-Aware Truth Maintenance`
- `Schema Evolution Firewall`
- `Reversible Entity Resolution Graph`
- `No-Hit Lease Ledger`
- `Two-Layer Archive`
- `Evidence Graph Compiler`

### 1.3 今回の追加視点

Round2は「何を持つべきか」は正しい。

不足しているのは、実装境界である。

特に以下を明確化する必要がある。

- graphの正本は何か。
- graph queryをどこで実行するか。
- Release Capsuleには何を入れるか。
- AWS teardown後、何が残るか。
- source schemaやtermsが変わった時、過去packetをどう守るか。
- no-hit leaseの再利用可否をどう判定するか。
- conflictをpacketへどう出すか。

---

## 2. 中核設計: `Official Evidence Ledger + Evidence Lens`

### 2.1 なぜ巨大knowledge graphでは弱いか

「Knowledge Graph」という名前だけで設計すると、次の方向へ滑りやすい。

- すべての公的情報を1つの真実DBへ正規化する。
- production runtimeがgraph DBに依存する。
- entity mergeを不可逆にする。
- no-hitを永続的な不存在情報にする。
- source schema変更を上書き更新で吸収する。

これはjpciteの制約と合わない。

jpciteが必要なのは、真実DBではなく、証跡のledgerである。

### 2.2 正しい構成

```text
Official Evidence Ledger
  append-only events, receipts, claims, gaps, conflicts, derivation steps
  no destructive overwrite
  internal replay and audit

Evidence Lens
  packet-specific compiled view
  public/private/metadata-only filtered
  minimal proof set
  Release Capsuleへ入る
```

### 2.3 データの流れ

```text
source_profile
-> source_twin
-> capture_run
-> source_document / observation
-> source_receipt
-> extraction_event
-> claim_candidate
-> derivation_step
-> claim_ref
-> no_hit_lease / conflict_case / known_gap
-> evidence_lens
-> public_packet_compiler
-> Release Capsule
```

### 2.4 重要な設計原則

- append-onlyで保存し、修正は `SUPERSEDES` eventで表現する。
- packetへ出すのはgraph全体ではなく、compiled lensだけ。
- source receiptとclaim refは常に逆参照可能にする。
- graph storageはAWS runtimeを必要としない形式で残す。
- query engineは開発/生成時だけ使い、本番は静的indexを読む。

---

## 3. Canonical data model

### 3.1 object families

| family | object | 役割 |
|---|---|---|
| source | `source_profile` | publisher, domain, terms, license, public use boundary |
| source | `source_twin` | capture behavior, schema behavior, volatility, failure pattern |
| source | `source_evolution_event` | schema/terms/URL/capture methodの変化 |
| capture | `capture_run` | 取得run単位。AWS job, local job, manual reviewを区別 |
| capture | `source_document` | 取得したdocumentのcanonical record |
| capture | `render_observation` | Playwright等のrendered observation |
| evidence | `source_receipt` | sourceから得た証跡の最小単位 |
| evidence | `extraction_event` | receiptからfield/sectionを取り出したevent |
| claim | `claim_candidate` | まだpublic claimではない候補 |
| claim | `claim_ref` | packetに使える検証済みclaim参照 |
| claim | `claim_stable_key` | source evolutionを跨ぐclaim追跡key |
| derivation | `derivation_step` | 正規化、entity解決、rule適用等のDAG node |
| temporality | `temporal_envelope` | observed/valid/published/compiled/retired time |
| gap | `known_gap` | 未取得、blocked、stale、manual review、scope不足 |
| no-hit | `no_hit_lease` | scope/expiryつきno-hit観測 |
| conflict | `conflict_case` | claim同士の矛盾 |
| entity | `entity_candidate` | 法人、制度、source subject候補 |
| entity | `entity_resolution_edge` | reversible merge / alias / negative evidence |
| compiler | `evidence_lens` | packet別のcompiled graph view |
| compiler | `proof_set` | 必要十分な証拠集合 |
| release | `graph_manifest` | bundle内graph assetsのmanifest |

### 3.2 common object header

すべてのobjectに共通headerを持たせる。

```json
{
  "object_type": "claim_ref",
  "object_id": "claim_...",
  "schema_id": "jpcite.claim_ref.v2",
  "schema_version": "2026-05-15.1",
  "run_id": "run_20260515_001",
  "created_at": "2026-05-15T12:00:00+09:00",
  "created_by": "deterministic_pipeline",
  "request_time_llm_call_performed": false,
  "visibility_class": "internal_or_public_safe",
  "data_class": "public_official_metadata",
  "taint_labels": [],
  "source_profile_ids": ["sp_..."],
  "checksum": "sha256:..."
}
```

### 3.3 `claim_ref.v2`

`claim_ref` はpacket claimの根拠となるが、真実そのものではない。

```json
{
  "object_type": "claim_ref",
  "object_id": "claim_001",
  "schema_id": "jpcite.claim_ref.v2",
  "claim_stable_key": "company.registration.invoice_status:jp:houjin_1234567890123:invoice_registry",
  "subject": {
    "subject_kind": "company",
    "subject_entity_id": "ent_...",
    "entity_resolution_state": "strong_id_match"
  },
  "predicate": "invoice_registration_observed",
  "value": {
    "kind": "structured",
    "normalized_value": "registered",
    "display_value": "登録あり"
  },
  "support_state": "api_observed",
  "support_trace_ids": ["sr_001", "drv_004"],
  "temporal_envelope_id": "tmp_001",
  "source_receipt_ids": ["sr_001"],
  "derivation_step_ids": ["drv_001", "drv_004"],
  "conflict_case_ids": [],
  "known_gap_ids": [],
  "public_statement_policy": {
    "allowed": true,
    "max_statement_strength": "observed_in_declared_source",
    "forbidden_strengths": ["absence", "safety", "legal_conclusion"]
  }
}
```

### 3.4 `temporal_envelope.v1`

Round2のbitemporalをさらに拡張し、5つの時点を分ける。

| time | 意味 |
|---|---|
| `observed_time` | jpciteが観測した時点 |
| `source_publication_time` | source側の公表/更新時点 |
| `valid_time` | 法令・制度・登録・募集などの有効時点 |
| `compiled_time` | jpciteがpacket/lensへcompileした時点 |
| `retired_time` | supersede, stale, terms change等で使わなくなった時点 |

```json
{
  "object_type": "temporal_envelope",
  "object_id": "tmp_001",
  "schema_id": "jpcite.temporal_envelope.v1",
  "observed_time": {
    "first_observed_at": "2026-05-15T10:00:00+09:00",
    "last_observed_at": "2026-05-15T10:00:00+09:00"
  },
  "source_publication_time": {
    "published_at": "2026-04-30",
    "updated_at": null,
    "source_declared": true,
    "known_gap_id": null
  },
  "valid_time": {
    "kind": "point_or_interval",
    "valid_from": null,
    "valid_until": null,
    "date_role": "registry_status_observation",
    "precision": "date"
  },
  "compiled_time": {
    "compiled_at": "2026-05-15T12:00:00+09:00",
    "compiler_version": "evidence_lens_compiler.2026-05-15.1"
  },
  "retired_time": {
    "retired_at": null,
    "retired_reason": null,
    "superseded_by_object_id": null
  },
  "staleness_policy": {
    "ttl_days": 7,
    "expires_for_packet_use_at": "2026-05-22T12:00:00+09:00",
    "after_expiry_action": "known_gap_requires_refresh"
  }
}
```

### 3.5 `source_evolution_event.v1`

sourceの変化はclaimと同じくらい重要な資産にする。

```json
{
  "object_type": "source_evolution_event",
  "object_id": "see_001",
  "schema_id": "jpcite.source_evolution_event.v1",
  "source_profile_id": "sp_...",
  "source_twin_id": "stw_...",
  "event_kind": "schema_drift",
  "detected_at": "2026-05-15T11:00:00+09:00",
  "previous_source_schema_hash": "sha256:old",
  "current_source_schema_hash": "sha256:new",
  "compatibility_level": "renamed_or_reordered",
  "affected_adapter_ids": ["adapter_invoice_csv.v1"],
  "affected_claim_stable_keys": ["company.registration.invoice_status:*"],
  "affected_packet_types": ["company_public_baseline", "invoice_vendor_public_check"],
  "production_policy": {
    "auto_promote_allowed": false,
    "quarantine_required": true,
    "manual_review_required": true
  },
  "recommended_action": "run_adapter_canary"
}
```

### 3.6 `no_hit_lease.v2`

No-hitはscopeとexpiryのある観測であり、absence claimではない。

```json
{
  "object_type": "no_hit_lease",
  "object_id": "nhl_001",
  "schema_id": "jpcite.no_hit_lease.v2",
  "subject": {
    "subject_kind": "company",
    "subject_entity_id": "ent_..."
  },
  "source_profile_id": "sp_enforcement_001",
  "query_scope": {
    "entrypoint_hash": "sha256:...",
    "normalized_query_hash": "sha256:...",
    "jurisdiction": "JP",
    "record_types_checked": ["administrative_disposition"],
    "date_range_checked": {
      "from": null,
      "to": "2026-05-15"
    },
    "capture_method": "official_html_search"
  },
  "observed_at": "2026-05-15T12:00:00+09:00",
  "lease_expires_at": "2026-05-22T12:00:00+09:00",
  "result_state": "no_hit_not_absence",
  "allowed_external_statement": "指定source、query、時点、正規化範囲では一致する公表情報を確認できませんでした。",
  "forbidden_external_statements": [
    "情報は存在しません",
    "問題ありません",
    "安全です",
    "違反はありません"
  ],
  "reuse_policy": {
    "reuse_allowed_until": "2026-05-22T12:00:00+09:00",
    "requires_same_subject_resolution": true,
    "requires_same_or_narrower_scope": true,
    "paid_packet_refresh_required_after_expiry": true
  }
}
```

### 3.7 `conflict_bundle.v1`

矛盾はエラーではなく、表示可能な構造にする。

```json
{
  "object_type": "conflict_bundle",
  "object_id": "confb_001",
  "schema_id": "jpcite.conflict_bundle.v1",
  "conflict_case_ids": ["conf_001"],
  "subject_entity_id": "ent_...",
  "field_or_predicate": "application_deadline",
  "claims": [
    {
      "claim_ref_id": "claim_a",
      "source_receipt_id": "sr_a",
      "normalized_value": "2026-06-30",
      "support_state": "pdf_observed"
    },
    {
      "claim_ref_id": "claim_b",
      "source_receipt_id": "sr_b",
      "normalized_value": "2026-07-15",
      "support_state": "html_observed"
    }
  ],
  "materiality": "material_for_packet",
  "packet_display_policy": "show_conflict_and_require_review",
  "single_value_output_allowed": false,
  "human_review_required": true,
  "known_gap_ids": ["gap_conflicting_deadline"]
}
```

### 3.8 `evidence_lens.v1`

Evidence Lensはpacketごとのgraph projectionである。

```json
{
  "object_type": "evidence_lens",
  "object_id": "lens_company_public_baseline_001",
  "schema_id": "jpcite.evidence_lens.v1",
  "packet_type": "company_public_baseline",
  "subject_entity_ids": ["ent_..."],
  "lens_scope": {
    "source_families": ["corporate_identity", "business_registry_signal"],
    "claim_predicates": ["corporate_identity_observed", "invoice_registration_observed"],
    "visibility": "public_packet_safe"
  },
  "included_claim_ref_ids": ["claim_001", "claim_002"],
  "included_source_receipt_ids": ["sr_001", "sr_002"],
  "included_no_hit_lease_ids": [],
  "included_conflict_bundle_ids": [],
  "known_gap_ids": ["gap_edinet_not_checked"],
  "gap_coverage_matrix_id": "gcm_001",
  "proof_set_id": "ps_001",
  "policy_decision_id": "polfw_001",
  "compiled_at": "2026-05-15T12:05:00+09:00",
  "public_export_allowed": true
}
```

---

## 4. Graph edge model

### 4.1 Required edge types

| edge | from | to | 意味 |
|---|---|---|---|
| `PROFILED_BY` | `source_profile` | `source_twin` | sourceの運用model |
| `CAPTURED_BY` | `source_document` | `capture_run` | どのrunで取得したか |
| `OBSERVED_IN` | `source_receipt` | `source_document` | receiptの観測元 |
| `EXTRACTED_FROM` | `extraction_event` | `source_receipt` | field抽出元 |
| `DERIVED_FROM` | `claim_candidate` | `derivation_step` | 候補claim生成 |
| `SUPPORTS` | `source_receipt` | `claim_ref` | claimを支える |
| `USES_STEP` | `claim_ref` | `derivation_step` | claim生成手順 |
| `HAS_TIME` | `claim_ref` | `temporal_envelope` | 時点model |
| `CONFLICTS_WITH` | `claim_ref` | `claim_ref` | 矛盾 |
| `SUPERSEDES` | `claim_ref` | `claim_ref` | 古いclaimを置換 |
| `LEASES_NO_HIT` | `no_hit_lease` | `source_profile` | source scope no-hit |
| `REDUCES_GAP` | `source_receipt` | `known_gap` | gap削減 |
| `BLOCKED_BY` | `claim_candidate` | `policy_decision` | 出力不可 |
| `PROJECTED_INTO` | `claim_ref` | `evidence_lens` | lensに採用 |
| `USED_IN_RELEASE` | `evidence_lens` | `release_capsule` | 本番候補に採用 |

### 4.2 edge schema

```json
{
  "object_type": "evidence_edge",
  "edge_id": "edge_001",
  "schema_id": "jpcite.evidence_edge.v1",
  "edge_type": "SUPPORTS",
  "from_object_id": "sr_001",
  "to_object_id": "claim_001",
  "created_at": "2026-05-15T12:00:00+09:00",
  "created_by": "claim_compiler",
  "edge_strength": "direct_api_support",
  "validity": {
    "active": true,
    "retired_at": null,
    "retired_reason": null
  },
  "checksum": "sha256:..."
}
```

### 4.3 append-only rule

edgeもnodeも上書きしない。

変更時は次を作る。

```text
new object
new edge
old object retired_time
SUPERSEDES edge
source_evolution_event
```

これにより、過去Release Capsuleの再現性が保たれる。

---

## 5. EvidenceQL: graph query design

### 5.1 なぜ専用query表現が必要か

CypherやGremlinなどのgraph DB前提に寄せると、production runtimeがgraph DB依存に見える。

今回の計画では、queryはAWS run中またはoffline compile時に実行される。productionはquery結果の静的viewを読む。

そのためqueryは、次の形式で持つ。

- JSONで保存可能
- DuckDB / SQLite / Python / Rust / JSへ実装可能
- Release Capsuleにquery hashを入れられる
- 同じqueryをreplay bundleで再実行できる

### 5.2 EvidenceQLの基本形

```json
{
  "query_id": "q_company_baseline_claims_v1",
  "schema_id": "jpcite.evidenceql.v1",
  "purpose": "compile_evidence_lens",
  "inputs": {
    "subject_entity_id": "ent_...",
    "packet_type": "company_public_baseline",
    "as_of": "2026-05-15T12:00:00+09:00"
  },
  "where": [
    {"field": "claim_ref.subject.subject_entity_id", "op": "eq", "value_ref": "inputs.subject_entity_id"},
    {"field": "claim_ref.support_state", "op": "in", "value": ["api_observed", "single_source_supported", "multi_source_supported"]},
    {"field": "temporal_envelope.staleness_policy.expires_for_packet_use_at", "op": "gte", "value_ref": "inputs.as_of"},
    {"field": "policy_decision.public_export_allowed", "op": "eq", "value": true}
  ],
  "join": [
    {"from": "claim_ref.source_receipt_ids", "to": "source_receipt.object_id"},
    {"from": "claim_ref.temporal_envelope_id", "to": "temporal_envelope.object_id"}
  ],
  "select": [
    "claim_ref.object_id",
    "claim_ref.claim_stable_key",
    "claim_ref.predicate",
    "claim_ref.value",
    "claim_ref.support_state",
    "source_receipt.object_id",
    "temporal_envelope.object_id"
  ],
  "order_by": [
    {"field": "claim_ref.support_state", "order": "support_strength_desc"},
    {"field": "temporal_envelope.observed_time.last_observed_at", "order": "desc"}
  ]
}
```

### 5.3 Query: packetに使えるclaimだけ取る

```json
{
  "query_id": "q_public_claim_candidates_v1",
  "goal": "packet_safe_claims",
  "filters": [
    "public_statement_policy.allowed == true",
    "visibility_class in ['public_safe', 'public_packet_safe']",
    "support_state not in ['unsupported', 'candidate_only', 'ocr_candidate']",
    "conflict_case_ids is empty or conflict_display_policy != 'hide'",
    "retired_time.retired_at is null",
    "staleness_policy.expires_for_packet_use_at >= as_of"
  ],
  "required_joins": [
    "source_receipt",
    "temporal_envelope",
    "policy_decision"
  ]
}
```

### 5.4 Query: stale no-hit leaseを探す

```json
{
  "query_id": "q_expiring_no_hit_leases_v1",
  "goal": "refresh_or_gap",
  "filters": [
    "no_hit_lease.subject.subject_entity_id == subject_entity_id",
    "no_hit_lease.reuse_policy.requires_same_or_narrower_scope == true",
    "no_hit_lease.lease_expires_at < packet_as_of"
  ],
  "output": [
    "no_hit_lease_id",
    "source_profile_id",
    "query_scope",
    "after_expiry_action"
  ]
}
```

### 5.5 Query: source driftが影響するpacketを探す

```json
{
  "query_id": "q_schema_drift_packet_impact_v1",
  "goal": "release_blocker_detection",
  "filters": [
    "source_evolution_event.event_kind == 'schema_drift'",
    "source_evolution_event.production_policy.quarantine_required == true"
  ],
  "expand": [
    "affected_claim_stable_keys -> claim_ref",
    "claim_ref -> evidence_lens",
    "evidence_lens -> packet_type"
  ],
  "output": [
    "source_profile_id",
    "affected_packet_types",
    "affected_claim_ref_ids",
    "recommended_action"
  ]
}
```

### 5.6 Query: conflictをpacket表示可能なbundleへ変換

```json
{
  "query_id": "q_material_conflict_bundle_v1",
  "goal": "compile_conflict_bundle",
  "filters": [
    "conflict_case.materiality in ['material_for_packet', 'material_for_action']",
    "conflict_case.single_value_output_allowed == false"
  ],
  "join": [
    "conflict_case.claim_ids -> claim_ref",
    "claim_ref.source_receipt_ids -> source_receipt"
  ],
  "output_policy": "show_conflict_and_require_review"
}
```

### 5.7 Query: proof set最小化

```json
{
  "query_id": "q_minimal_proof_set_v1",
  "goal": "proof_set_optimization",
  "objective": "cover_required_claim_predicates_with_minimal_receipts",
  "constraints": [
    "each_public_claim_has_at_least_one_receipt",
    "receipt_visibility_class == public_safe_or_summary_safe",
    "support_state >= required_support_state_by_claim_type",
    "no conflict hidden",
    "all gaps represented in gap_coverage_matrix"
  ],
  "tie_breakers": [
    "prefer_api_or_bulk_receipts",
    "prefer_fresher_observation",
    "prefer_lower_redistribution_risk",
    "prefer_receipts_reused_across_packets"
  ]
}
```

---

## 6. Storage and assetization

### 6.1 Storage principle

AWS run中は処理効率のためにS3/Athena/Glue等を使ってよい。

ただし、zero-bill後に残る正本はAWS依存にしない。

残すべき形式は次。

```text
evidence_replay_bundle/
  manifest.json
  objects/*.jsonl.zst
  edges/*.jsonl.zst
  derivation_steps/*.jsonl.zst
  source_evolution/*.jsonl.zst
  schema_contracts/*.json
  query_library/*.json
  checksums.sha256

public_packet_asset_bundle/
  static_db_manifest.json
  evidence_lenses/*.jsonl
  packet_examples/*.json
  proof_sets/*.json
  proof_pages_sidecars/*.json
  capability_matrix_manifest.json
  catalog_hash_mesh.json
  checksums.sha256
```

### 6.2 Hot / cold split

| layer | 内容 | 本番で読むか |
|---|---|---|
| hot static DB | packet catalog, pricing, capability matrix, evidence lens, minimal proof set | yes |
| warm internal bundle | source receipt summaries, no-hit lease index, conflict bundle summaries | limited |
| cold replay bundle | raw-ish internal receipts, derivation DAG, schema evolution events | no |

### 6.3 Release Capsuleに入れるもの

Release Capsuleへ入れる。

- `graph_manifest.json`
- `evidence_lens_manifest.json`
- `evidence_lenses/*.jsonl`
- `proof_set_manifest.json`
- `no_hit_lease_index.public_safe.json`
- `conflict_bundle_index.public_safe.json`
- `gap_coverage_matrix_index.json`
- `source_schema_contract_manifest.json`
- `catalog_hash_mesh.json`

Release Capsuleへ入れない。

- raw full screenshot
- raw DOM
- HAR body
- cookie/auth header
- full OCR text
- real private CSV
- terms不明source本文
- quarantined claim candidate本文

### 6.4 Graph manifest

```json
{
  "object": "graph_manifest",
  "schema_id": "jpcite.graph_manifest.v1",
  "graph_build_id": "graph_20260515_001",
  "source_runs": ["run_20260515_001"],
  "object_counts": {
    "source_receipt": 1200000,
    "claim_ref": 380000,
    "no_hit_lease": 90000,
    "conflict_bundle": 1200,
    "evidence_lens": 18000
  },
  "support_state_counts": {
    "api_observed": 240000,
    "html_observed": 80000,
    "pdf_observed": 50000,
    "ocr_candidate": 10000,
    "candidate_only": 25000
  },
  "public_export_policy": {
    "raw_screenshot_exported": false,
    "raw_dom_exported": false,
    "raw_har_exported": false,
    "private_csv_exported": false
  },
  "query_library_hash": "sha256:...",
  "schema_contract_hash": "sha256:...",
  "checksum_manifest": "checksums.sha256"
}
```

### 6.5 Why this is smarter

本番でgraph DBを動かすより、この方式が強い。

- AWS teardown後も動く。
- releaseとrollbackがファイルpointerで済む。
- AIエージェントに必要なviewだけ出せる。
- graph全体のprivate/terms riskをpublic runtimeへ持ち込まない。
- 再検証はcold replay bundleでできる。

---

## 7. Source evolution management

### 7.1 Source evolutionをfirst-class objectにする

sourceは変化する。

- API versionが変わる。
- CSV columnが増える。
- HTML tableの順序が変わる。
- PDF templateが変わる。
- URLが移動する。
- termsが変わる。
- robotsが変わる。
- public access policyが変わる。
- source内のID体系が変わる。

これを単なるfailure logにせず、`Source Evolution Ledger` として残す。

### 7.2 event kinds

```text
schema_drift
terms_change
robots_change
url_moved
source_deprecated
source_split
source_merged
capture_method_degraded
capture_method_improved
render_behavior_changed
no_hit_behavior_changed
identifier_format_changed
publication_cadence_changed
legal_precedence_changed
manual_review_policy_changed
```

### 7.3 Source adapter lifecycle

```text
observe_change
-> classify_evolution_event
-> quarantine_affected_adapter
-> run_source_contract_tests
-> compile_candidate_adapter
-> canary_extract
-> compare_claim_stable_keys
-> human_review_if_material
-> promote_adapter_version
-> backfill_or_mark_gap
-> release_capsule_candidate
```

### 7.4 `Schema Contract ABI`

source adapterはpacket schemaへ直接つながない。

間にcanonical contractを置く。

```json
{
  "object_type": "schema_contract",
  "schema_id": "jpcite.schema_contract.v1",
  "contract_id": "corporate_identity.invoice_registry.v1",
  "source_profile_id": "sp_invoice_001",
  "adapter_id": "adapter_invoice_api.v3",
  "canonical_fields": [
    {
      "field_name": "invoice_registration_status",
      "type": "enum",
      "required_for_claim": true,
      "allowed_values": ["registered", "not_observed", "unknown"],
      "public_claim_allowed_when": "source_receipt_direct_api"
    },
    {
      "field_name": "registration_number",
      "type": "string",
      "required_for_claim": true,
      "validation": "t_number_format"
    }
  ],
  "compatibility_policy": {
    "additive": "candidate_only_until_tested",
    "renamed_or_reordered": "quarantine_and_canary",
    "semantic_change": "manual_review_required",
    "breaking": "block_public_claims"
  }
}
```

### 7.5 Claim Stable Key

source evolutionでreceipt IDが変わっても、同じ意味のclaimを追える必要がある。

```text
claim_stable_key =
  subject_namespace
  + subject_stable_id
  + predicate
  + source_family
  + jurisdiction
  + validity_scope
```

例:

```text
company:houjin_1234567890123:invoice_registration_observed:corporate_identity:JP:current_registry_status
```

注意:

- stable keyはclaimそのものの真偽ではない。
- sourceが変わったら新claimを作り、stable keyで比較する。
- semantic_change時はstable keyのcompatibilityをmanual reviewに落とす。

### 7.6 Source evolutionがpacketへ与える影響

```text
if source evolution is compatible:
  continue compile, record source_evolution_event

if additive:
  old claims remain; new fields candidate_only

if renamed_or_reordered:
  quarantine affected adapter; use old accepted lens until TTL; mark gap if expired

if semantic_change:
  block public claim for affected predicates
  create known_gap
  require human review

if terms_change blocks redistribution:
  retire affected public lens
  keep metadata-only replay if allowed
  release new capsule without blocked content
```

---

## 8. Claim Derivation DAG as replayable runtime

### 8.1 DAGの要件

Claim Derivation DAGは説明用ではなく、再実行可能でなければならない。

各stepは次を持つ。

- deterministic operation ID
- operation version
- input object hashes
- output object hashes
- parameters hash
- schema contract ID
- policy decision ID
- quality checks
- support_state change

### 8.2 derivation step schema

```json
{
  "object_type": "derivation_step",
  "object_id": "drv_004",
  "schema_id": "jpcite.derivation_step.v2",
  "operation": "compile_invoice_registration_claim",
  "operation_version": "2026-05-15.1",
  "input_object_ids": ["sr_001", "schema_contract_invoice.v1"],
  "input_hashes": ["sha256:...", "sha256:..."],
  "output_object_ids": ["claim_001"],
  "output_hashes": ["sha256:..."],
  "deterministic": true,
  "request_time_llm_call_performed": false,
  "parameters_hash": "sha256:...",
  "quality_checks": [
    {"check_id": "required_field_present", "status": "pass"},
    {"check_id": "support_state_allowed", "status": "pass"},
    {"check_id": "forbidden_phrase_absent", "status": "pass"}
  ],
  "policy_decision_id": "polfw_001",
  "known_gap_ids": []
}
```

### 8.3 LLM candidateをDAGに入れる場合

LLMを使う場合は、DAG内でclaim生成stepにしない。

許可:

- schema adapter候補
- section classification候補
- OCR補助候補
- human review queueの要約

必須:

```text
llm_candidate_step
-> quarantine_object
-> deterministic_validator
-> human_review_or_discard
```

禁止:

- LLM candidateから直接 `claim_ref` を作る。
- LLMがsource trustを最終判定する。
- LLMがno-hitをabsenceへ言い換える。
- LLMが外部表示claimを自由生成する。

---

## 9. Conflict-aware evidence maintenance

### 9.1 名前の修正

Round2では `Conflict-Aware Truth Maintenance` と呼んでいる。

正本へマージするときは、外部説明では `Conflict-Aware Evidence Maintenance` に寄せた方が安全である。

理由:

- jpciteは真実を断定するサービスではない。
- 公的一次情報の観測と矛盾を管理するサービスである。
- 「Truth」という語はAIが強い断定をしている印象を与えやすい。

内部module名は維持してもよいが、product/API/proof copyではEvidence表現にする。

### 9.2 conflictの分類

```text
value_mismatch
time_mismatch
identifier_mismatch
source_status_mismatch
scope_mismatch
schema_mismatch
legal_precedence_unknown
entity_resolution_conflict
no_hit_vs_positive_hit
```

### 9.3 packet別の扱い

| conflict | packet action |
|---|---|
| immaterial | known_gapとして注記 |
| material but explainable | conflict_bundleを表示 |
| material and single value needed | `human_review_required=true` |
| legal precedence known | primary sourceを表示し、補助source conflictを注記 |
| legal precedence unknown | winnerを選ばない |

### 9.4 矛盾を価値に変える例

`grant_candidate_shortlist_packet`:

```text
一覧ページでは締切が2026-06-30、募集要領PDFでは2026-07-15と観測されました。
本packetでは単一締切を断定せず、申請前確認事項として表示します。
```

`counterparty_public_dd_packet`:

```text
法人番号sourceの所在地と別公的sourceの所在地に差異があります。
同一法人の可能性はありますが、住所更新時点差または同定差の可能性があります。
```

---

## 10. No-Hit Lease Ledger details

### 10.1 lease reuse rule

no-hit leaseは、次をすべて満たす場合だけ再利用できる。

```text
same subject resolution
same or narrower source scope
same or narrower date range
same or narrower record type
same capture method support or stronger
not expired
terms still allow use
source_twin says no-hit behavior unchanged
```

### 10.2 lease expiry policy

| source volatility | default lease |
|---|---:|
| high, e.g. grants/current notices | 1-3 days |
| medium, e.g. enforcement list | 7-14 days |
| low, e.g. static law XML snapshot | 30-90 days |
| unclear | short lease + known_gap |

### 10.3 no-hit index

```text
no_hit_lease_index/
  by_subject/{subject_entity_id}.jsonl
  by_source/{source_profile_id}.jsonl
  by_expiry/YYYY-MM-DD.jsonl
  by_record_type/{record_type}.jsonl
```

### 10.4 Release blocker

次はrelease blockerにする。

- expired no-hit leaseをpaid packetで再利用している。
- no-hit allowed statement以外の表現が出ている。
- no-hit scopeが空。
- no-hitがsource receiptなしで作られている。
- source_twinでno-hit page behaviorが変わったのに再利用している。

---

## 11. Proof Set Optimizer

### 11.1 目的

AIエージェントに証拠を全部見せる必要はない。

必要なのは、packet claimを支える最小十分な証拠集合である。

### 11.2 objective

```text
minimize:
  public proof noise
  redistribution risk
  screenshot/OCR reliance
  stale receipt count
  paid output leakage

subject to:
  every public claim has support
  every gap is represented
  every no-hit has scope and lease
  every conflict is shown or blocks claim
  policy firewall allows visibility
```

### 11.3 tie breakers

1. API/bulk official receipt
2. official HTML with stable selector
3. official PDF with text layer
4. bounded screenshot observation
5. OCR candidate only as non-final support

### 11.4 output

```json
{
  "object_type": "proof_set",
  "object_id": "ps_001",
  "schema_id": "jpcite.proof_set.v1",
  "packet_type": "company_public_baseline",
  "claim_ref_ids": ["claim_001", "claim_002"],
  "source_receipt_ids": ["sr_001", "sr_002"],
  "excluded_receipt_ids": [
    {
      "source_receipt_id": "sr_003",
      "reason": "redundant_lower_support_state"
    }
  ],
  "coverage": {
    "required_claim_predicates_covered": true,
    "known_gaps_included": true,
    "no_hit_scopes_included": true
  },
  "visibility": {
    "public_safe": true,
    "paid_output_leakage_risk": "low"
  }
}
```

---

## 12. Graph integrity gates

### 12.1 Gate list

Release Capsule前に次を必須gateにする。

| gate | 内容 |
|---|---|
| `G-graph-01 receipt_backlink` | public claimからsource_receiptへ戻れる |
| `G-graph-02 temporal_complete` | observed/valid/compiled/stalenessが揃う |
| `G-graph-03 no_hit_scope` | no-hitにscope/expiry/allowed statementがある |
| `G-graph-04 conflict_visible` | material conflictが隠れていない |
| `G-graph-05 schema_contract` | claimがschema contractを通っている |
| `G-graph-06 source_evolution_clear` | active source evolution eventがquarantineを破っていない |
| `G-graph-07 entity_reversible` | merge decisionが可逆で根拠つき |
| `G-graph-08 support_state_allowed` | claim typeごとの最低support_stateを満たす |
| `G-graph-09 policy_firewall` | visibility/data class/termsが許可されている |
| `G-graph-10 replay_hash` | derivation DAGのinput/output hashが一致 |
| `G-graph-11 release_lens_minimal` | Release Capsuleにgraph全体が混入していない |
| `G-graph-12 stale_block` | stale claim/no-hitをpaid packetで使っていない |

### 12.2 Failure handling

```text
if gate failure affects public claim:
  block claim
  create known_gap
  update capability_matrix_manifest

if gate failure affects paid packet core claim:
  block packet execution
  free preview only

if gate failure is source evolution:
  quarantine adapter and affected claim stable keys

if gate failure is proof leakage:
  block Release Capsule activation
```

---

## 13. How this changes packet outputs

### 13.1 `company_public_baseline`

追加価値:

- 法人番号、インボイス、gBizINFO等のclaimをstable keyで追跡。
- 住所や名称の差異をconflict bundleとして表示。
- no-hit leaseにより「確認できなかった範囲」を明確にする。
- source evolutionでregistry schemaが変わっても旧packetを再現可能。

### 13.2 `grant_candidate_shortlist_packet`

追加価値:

- 締切、対象者、補助率、対象経費をtemporal envelopeで分離。
- 一覧/PDF/自治体ページの矛盾をconflict bundleにする。
- no-hit leaseで「この自治体sourceでは該当募集を確認できない」の期限を管理。
- Semantic deltaをclaim deltaに圧縮し、watch productへ使える。

### 13.3 `permit_scope_checklist_packet`

追加価値:

- 業法、許認可、自治体手続、標準処理期間のclaimをDAGでつなぐ。
- `permission not required` のような外部断定を禁止し、`needs_review` と追加質問へ落とす。
- source evolutionで自治体ページ構造が変わった場合、packetを自動停止できる。

### 13.4 `regulation_change_impact_packet`

追加価値:

- law XMLの公布/施行/改正/観測時点を分離。
- semantic deltaで条文差分をaction-level deltaへ変換。
- 古いclaimをSUPERSEDESし、過去releaseの説明可能性を保つ。

### 13.5 `counterparty_public_dd_packet`

追加価値:

- 行政処分sourceのno-hitをlease化。
- enforcement source間の名称/法人番号/住所の同定差をconflict化。
- public evidence attentionはtyped scoreとして出し、信用スコアにはしない。

---

## 14. Merge plan into master execution plan

### 14.1 Section 5 Algorithms への追記

正本の `## 5. Algorithms` に以下を追記する。

```text
Official Evidence Knowledge Graph is implemented as:
Official Evidence Ledger -> Evidence Lens -> Public Packet Compiler.
It is not a production truth database.
```

追加項目:

- `Official Evidence Ledger`
- `Evidence Lens`
- `Claim Stable Key`
- `Temporal Envelope`
- `EvidenceQL`
- `Proof Set Optimizer`
- `Graph Integrity Gate`

### 14.2 Section 8 / AWS artifact factory への追記

AWS成果物に以下を追加する。

- `evidence_replay_bundle`
- `public_packet_asset_bundle`
- `graph_manifest.json`
- `source_evolution_ledger.jsonl`
- `schema_contracts/*.json`
- `evidenceql_query_library/*.json`
- `no_hit_lease_index`
- `conflict_bundle_index`
- `proof_set_manifest`

### 14.3 Section 17 / 18 smart-method addendum への追記

Round2の `Official Evidence Knowledge Graph` の説明を以下に具体化する。

```text
The graph is not a live production DB. It is an append-only evidence ledger
compiled into packet-specific evidence lenses and release-capsule assets.
```

### 14.4 Release Capsuleへの追記

Release Capsule manifestに以下を追加する。

```json
{
  "graph_assets": {
    "graph_manifest": "graph_manifest.json",
    "evidence_lens_manifest": "evidence_lens_manifest.json",
    "proof_set_manifest": "proof_set_manifest.json",
    "no_hit_lease_index": "no_hit_lease_index.public_safe.json",
    "conflict_bundle_index": "conflict_bundle_index.public_safe.json",
    "source_schema_contract_manifest": "source_schema_contract_manifest.json"
  }
}
```

### 14.5 P0 implementationへのマージ

P0に追加する順番。

1. `schema_id` / common object header / checksum conventionを定義。
2. `claim_ref.v2`、`temporal_envelope.v1`、`source_receipt.v1`、`known_gap.v1` を先に固定。
3. `no_hit_lease.v2` を既存no-hit ledgerの正式形にする。
4. `source_evolution_event.v1` と `schema_contract.v1` をsource adapter前提にする。
5. `derivation_step.v2` をPublic Packet Compilerの入力にする。
6. `evidence_lens.v1` をOutput ComposerとPublic Packet Compilerの間に置く。
7. `graph_integrity_gate` をRelease Capsule gateへ追加。
8. `EvidenceQL` は最初はJSON query spec + offline runnerでよい。

### 14.6 P1/P2へ回すもの

P0に入れすぎると本番が遅くなる。

P1でよいもの:

- full graph visualization
- advanced graph query UI
- source quality learningの詳細dashboard
- full bitemporal analytics
- large-scale cross-source conflict mining

P2でよいもの:

- graph neural network
- automatic legal precedence inference
- public interactive evidence graph explorer
- dynamic graph DB runtime

---

## 15. Contradiction fixes

### 15.1 Knowledge graph vs zero-bill

矛盾リスク:

> Knowledge GraphをAWS NeptuneやOpenSearchのような常時DBとして残すと、zero-billと矛盾する。

修正:

> graph queryはAWS run/offline compile中だけ。productionはRelease Capsule内の静的Evidence Lensを読む。

### 15.2 Bitemporal claim vs simple packet schema

矛盾リスク:

> 既存packetが単一の`observed_at`だけを持つと、制度上の有効日と混ざる。

修正:

> packet claimは `temporal_envelope_id` を必須にする。外部表示では必要な時点だけ簡潔に見せる。

### 15.3 No-hit ledger vs no-hit lease

矛盾リスク:

> 既存の `no_hit_checks[]` が永久cacheに見える。

修正:

> `no_hit_checks[]` は外部packet view名として残してよいが、内部正本は `no_hit_lease` にする。

### 15.4 Conflict-Aware Truth Maintenance wording

矛盾リスク:

> `truth` という語が、jpciteが真実を断定する印象を与える。

修正:

> 外部/計画正本では `Conflict-Aware Evidence Maintenance` と呼ぶ。内部でtruth maintenanceの技術語を使う場合も外部表示には出さない。

### 15.5 Source quality score vs generic trust score

矛盾リスク:

> source qualityが「信頼スコア」「信用スコア」に見える。

修正:

> source qualityは `capture_reliability_score`、`schema_stability_score`、`claim_support_strength_score` 等のtyped operational metricsに限定する。

### 15.6 Screenshot/OCR receipts vs public proof

矛盾リスク:

> screenshotやOCR全文をpublic proofへ出すと、redistributionやPIIリスクが上がる。

修正:

> public proofにはbounded metadata、hash、anchor、summaryだけ。raw assetはlicense boundaryに応じてinternal replay bundleへ置くか、保存しない。

### 15.7 Source evolution vs automatic production update

矛盾リスク:

> source schema changeを自動適用するとpacketが壊れる。

修正:

> source evolution eventがmaterialならquarantine。adapter canaryとschema contract test通過までRelease Capsuleへ入れない。

### 15.8 Evidence Lens vs paid output leakage

矛盾リスク:

> agent decision pageにEvidence Lensを出しすぎると有料packetの内容が漏れる。

修正:

> public Evidence Lensはproof minimalityとpublic proof minimizerを通す。paid outputはclaim詳細や全receiptを含められるが、preview/proofは最小化する。

---

## 16. Implementation-ready backlog additions

### 16.1 P0 schema tasks

| ID | task | blocker |
|---|---|---|
| EG-P0-01 | common object headerを定義 | packet compiler |
| EG-P0-02 | `claim_ref.v2` schema | public claims |
| EG-P0-03 | `temporal_envelope.v1` schema | bitemporal safety |
| EG-P0-04 | `no_hit_lease.v2` schema | no-hit safety |
| EG-P0-05 | `derivation_step.v2` schema | replayability |
| EG-P0-06 | `source_evolution_event.v1` schema | schema drift gate |
| EG-P0-07 | `evidence_lens.v1` schema | Release Capsule |
| EG-P0-08 | `graph_manifest.v1` schema | zero-bill export |

### 16.2 P0 compiler tasks

| ID | task | output |
|---|---|---|
| EG-P0-09 | Evidence Lens Compiler minimal版 | `evidence_lenses/*.jsonl` |
| EG-P0-10 | No-Hit Lease Compiler | `no_hit_lease_index` |
| EG-P0-11 | Conflict Bundle Compiler | `conflict_bundle_index` |
| EG-P0-12 | Proof Set Optimizer minimal版 | `proof_sets/*.json` |
| EG-P0-13 | Graph Integrity Gate | release gate report |
| EG-P0-14 | EvidenceQL JSON query library | `query_library/*.json` |

### 16.3 P0 release tasks

| ID | task | output |
|---|---|---|
| EG-P0-15 | Release Capsuleにgraph assetsを追加 | capsule manifest |
| EG-P0-16 | Runtime Dependency FirewallにAWS graph URL禁止を追加 | smoke report |
| EG-P0-17 | Golden Agent Session ReplayでEvidence Lens確認 | replay report |
| EG-P0-18 | Zero-AWS Posture Attestationにgraph export確認を追加 | attestation |

### 16.4 P0 test fixtures

最低限のfixture。

- API receipt -> claim_ref -> evidence_lens
- HTML receipt -> claim_ref -> proof_set
- PDF receipt with conflict
- OCR candidate quarantined
- expired no-hit lease blocked
- schema drift event blocks adapter
- source terms change retires lens
- entity merge reversible
- stale temporal envelope creates known_gap

---

## 17. Recommended master-plan wording

正本計画へそのまま入れるなら、以下の短文がよい。

```text
The Official Evidence Knowledge Graph is implemented as an append-only
Official Evidence Ledger plus packet-specific Evidence Lenses. It is not a
live production truth database. AWS may build and query the ledger during the
credit run, but production activates only Release Capsule assets: graph
manifests, evidence lenses, proof sets, no-hit lease indexes, conflict bundle
indexes, and capability matrices. Every public claim must have a claim_ref,
temporal_envelope, source_receipt backlink, support_state, policy decision,
and gap/conflict/no-hit treatment. No-hit observations are lease-scoped and
expire. Source schema, terms, URL, and capture changes are tracked in a
Source Evolution Ledger and cannot silently update production packets.
```

日本語要約:

```text
jpciteの証拠グラフは、真実DBではなく、公的一次情報の観測・証跡・claim・gap・矛盾・時点をappend-onlyに管理するEvidence Ledgerである。本番にはグラフ全体を出さず、packetごとにEvidence LensへコンパイルしてRelease Capsuleへ入れる。no-hitは期限つきleaseであり、source変更はSource Evolution Ledgerで管理し、schema/terms/capture変化がある場合はquarantineとrelease gateを通す。
```

---

## 18. Final verdict

このRound3 4/20の結論は、次である。

> もっとスマートにするなら、証拠グラフを「大きく賢いDB」にするのではなく、「append-only ledger、packet-specific lens、source evolution ledger、proof set optimizer、graph integrity gate」に分解するべき。

これにより、既存計画の強みを崩さずに次を強化できる。

- no hallucination
- source-backed outputs
- GEO向けagent decision page
- paid packetの再現性
- AWS one-time artifact factory
- zero-bill teardown
- source schema/terms変化への耐性
- no-hitの安全な再利用
- conflictを隠さない成果物化

正本計画へのマージは必須だが、実装はP0最小版からでよい。

P0で必要なのは、graph DBではない。

P0で必要なのは、`claim_ref.v2`、`temporal_envelope.v1`、`no_hit_lease.v2`、`source_evolution_event.v1`、`evidence_lens.v1`、`graph_manifest.v1`、そしてRelease Capsule前の `Graph Integrity Gate` である。
