# #40 Packet Taxonomy / Common Schema / Output Contract Pack

Date: 2026-05-15  
Scope: Evidence Packet, precomputed intelligence bundle, compatibility / application / houjin / company public artifacts, advisor handoff packets.

## 1. 現状分析

既存成果物 packet は 2 系統に分かれている。

1. Evidence Packet 系
   - 実装: `src/jpintel_mcp/services/evidence_packet.py`
   - 目的: LLM/agent が回答を書く前に渡す根拠 bundle。
   - 主要フィールド: `packet_id`, `api_version`, `corpus_snapshot_id`, `records[]`, `quality`, `verification`, `evidence_value`, `compression`, `agent_recommendation`, `known_gaps`, `source_count`, `jpcite_cost_jpy`, `estimated_tokens_saved`
   - 特徴: `answer_not_included=true`, no LLM, no live web search, fail-open `quality.known_gaps`.

2. ArtifactResponse 系
   - 実装: `src/jpintel_mcp/api/artifacts.py`
   - 目的: 稟議、DD、会社フォルダ、申請戦略へ貼れる完成物。
   - 主要フィールド: `artifact_id`, `artifact_type`, `artifact_version`, `schema_version`, `packet_id`, `summary`, `sections[]`, `sources[]`, `source_receipts[]`, `known_gaps[]`, `_evidence`, `copy_paste_parts`, `recommended_followup`, `agent_routing`, `human_review_required`, `audit_seal`
   - 特徴: source receipt quality gate、structured known gaps、copy-paste outputs、paid key では audit seal。

統合方針は、既存トップレベルを壊さず、全 packet 共通の envelope を追加すること。既存 field は v1 互換 alias として残し、新規 client は `packet.*` / `metrics.*` / `quality.*` / `exports.*` を読む。

## 2. Taxonomy

共通 taxonomy は `packet_kind` と `packet_type` を分ける。

`packet_kind` は wire contract の大分類:

| packet_kind | 用途 | 既存該当 |
|---|---|---|
| `evidence_packet` | 回答前の根拠 bundle | `/v1/evidence/packets/*`, MCP `get_evidence_packet` |
| `precomputed_bundle` | 事前計算済み context prefetch | `/v1/intelligence/precomputed/query` |
| `artifact_packet` | 人間へ貼る成果物 | `/v1/artifacts/*` |
| `handoff_packet` | 専門家/後続 workflow へ渡す引継ぎ | advisors evidence handoff |
| `batch_packet` | 複数 packet の実行結果 envelope | evidence batch / export |

`packet_type` は業務別の具体型:

| packet_type | packet_kind | 主キー |
|---|---|---|
| `program_evidence` | `evidence_packet` | `program_id` / `canonical_id` |
| `houjin_evidence` | `evidence_packet` | `houjin_bangou` / `canonical_id` |
| `query_evidence` | `evidence_packet` | query hash |
| `compatibility_table` | `artifact_packet` | sorted program pair hash |
| `application_strategy_pack` | `artifact_packet` | normalized profile hash |
| `houjin_dd_pack` | `artifact_packet` | `houjin_bangou` |
| `company_public_baseline` | `artifact_packet` | `houjin_bangou` |
| `company_folder_brief` | `artifact_packet` | source artifact / `houjin_bangou` |
| `company_public_audit_pack` | `artifact_packet` | `houjin_bangou` |
| `advisor_handoff` | `handoff_packet` | source packet/artifact id |

Subject taxonomy:

| subject_kind | examples | normalized id |
|---|---|---|
| `program` | 補助金、助成金、融資、税制 | `program:<id>` or `UNI-*` |
| `houjin` | 法人番号/T番号 | `corporate_entity:<13digits>` |
| `law` | 法令条文 | `law:<jurisdiction>:<article>` |
| `source` | 官公庁URL/PDF | `source:<sha256_url>` |
| `query` | 検索意図 | `query:<sha256_normalized_query>` |
| `profile` | 申請者 profile | `profile:<sha256_normalized_profile>` |

## 3. Common Schema v1.1

全 packet に次の共通ブロックを持たせる。既存 field は移行期間中トップレベルにも残す。

```json
{
  "packet": {
    "id": "pkt_or_evp_or_art_...",
    "kind": "evidence_packet",
    "type": "program_evidence",
    "schema_version": "1.1",
    "api_version": "v1",
    "generated_at": "2026-05-15T12:00:00+09:00",
    "generator": {
      "service": "jpcite",
      "endpoint": "/v1/evidence/packets/program/UNI-...",
      "tool": "get_evidence_packet",
      "request_time_llm_call_performed": false,
      "web_search_performed_by_jpcite": false
    },
    "corpus": {
      "snapshot_id": "corpus-2026-05-15",
      "checksum": "sha256:...",
      "freshness_endpoint": "/v1/meta/freshness"
    },
    "subject": {
      "kind": "program",
      "id": "program:...",
      "display_name": "...",
      "input_id": "UNI-...",
      "identity_confidence": 1.0
    }
  },
  "metadata": {
    "query": {
      "user_intent": "東京都 製造業 設備投資 補助金",
      "normalized_filters": {}
    },
    "locale": "ja-JP",
    "timezone": "Asia/Tokyo",
    "profile": "full",
    "answer_not_included": true,
    "tags": []
  },
  "records": [],
  "sections": [],
  "sources": [],
  "source_receipts": [],
  "entity_resolution": [],
  "quality": {
    "freshness_bucket": "within_30d",
    "coverage_score": 0.73,
    "known_gaps": [],
    "known_gaps_inventory": [],
    "human_review_required": false,
    "confidence": {
      "overall": 0.73,
      "basis": "source_coverage_and_rule_verdicts"
    }
  },
  "metrics": {
    "jpcite_cost_jpy": 3,
    "estimated_tokens_saved": null,
    "source_count": 2,
    "known_gaps": []
  },
  "fence": {
    "type": "information_only",
    "not_legal_or_tax_advice": true,
    "not_application_advice": true,
    "requires_professional_review_for": ["legal", "tax", "grant_application", "audit"],
    "message_ja": "公開根拠の整理であり、法務・税務・申請可否の最終判断ではありません。"
  },
  "exports": {
    "json": {"available": true},
    "markdown": {"available": true, "field": "markdown_display"},
    "csv": {"available": false},
    "copy_paste_parts": []
  },
  "versioning": {
    "schema_version": "1.1",
    "min_reader_version": "1.0",
    "compatibility": "additive",
    "deprecated_fields": []
  }
}
```

Required in MVP:

- `packet.id`, `packet.kind`, `packet.type`, `packet.schema_version`, `packet.generated_at`
- `packet.corpus.snapshot_id`
- `quality.known_gaps`
- `metrics.jpcite_cost_jpy`, `metrics.estimated_tokens_saved`, `metrics.source_count`, `metrics.known_gaps`
- `fence`
- at least one of `records[]` or `sections[]`

## 4. Common Fields

| field | required | notes |
|---|---:|---|
| `packet.id` | yes | Existing `packet_id` / `artifact_id` を正規化。 |
| `packet.kind` | yes | closed enum。 |
| `packet.type` | yes | closed enum、API operation と一致。 |
| `packet.schema_version` | yes | common schema。初期値 `1.1`。 |
| `packet.api_version` | yes | public API major。既存 `v1` を維持。 |
| `packet.generated_at` | yes | JST ISO。 |
| `packet.generator.endpoint` | no | REST route。MCP は tool name も入れる。 |
| `packet.corpus.snapshot_id` | yes | 既存 `corpus_snapshot_id` alias。 |
| `packet.corpus.checksum` | no | artifact は既存 `corpus_checksum` を移す。 |
| `packet.subject` | no | query/batch では複数 subject のため optional。 |
| `metadata.query` | no | Evidence 系は必須、Artifact 系は request profile を入れる。 |
| `records[]` | no | record-oriented packet。 |
| `sections[]` | no | artifact-oriented packet。 |
| `sources[]` | no | source registry 表示。 |
| `source_receipts[]` | no | audit/workpaper 用 source receipts。 |
| `quality` | yes | freshness/coverage/gaps/review。 |
| `metrics` | yes | agent が最初に読む small fields。 |
| `fence` | yes | 法務・税務・申請判断の境界。 |
| `exports` | yes | JSON/Markdown/CSV/copy-paste contract。 |
| `versioning` | yes | compatibility と deprecation。 |

## 5. Metrics Contract

`metrics` は全 packet 共通の小さい比較ブロック。既存トップレベル aliases (`jpcite_cost_jpy`, `estimated_tokens_saved`, `source_count`, `known_gaps`) は残すが、canonical は `metrics.*`。

```json
{
  "metrics": {
    "jpcite_cost_jpy": 3,
    "estimated_tokens_saved": 5200,
    "source_count": 7,
    "known_gaps": [
      {
        "gap_id": "source_receipt_missing_fields",
        "severity": "review",
        "message": "source receipt missing content_hash",
        "source_fields": ["source_receipts[0].content_hash"]
      }
    ],
    "record_count": 5,
    "section_count": 4,
    "source_receipt_count": 7,
    "human_review_required_count": 2
  }
}
```

Rules:

- `jpcite_cost_jpy`: jpcite 側の税抜 API/MCP 実行コスト。Evidence 単発は default `3`。batch/export は billing metadata の quantity から算出。
- `estimated_tokens_saved`: caller baseline がある場合のみ数値。ない場合は `null`。保証値ではない。
- `source_count`: dedupe された `source_url` 数。`sources[]` がある場合は原則 `len(unique sources[].source_url)`。
- `known_gaps`: canonical は structured list。旧 Evidence の `quality.known_gaps: list[str]` は bridge で `{gap_id, severity, message}` に昇格。
- `metrics.known_gaps` と `quality.known_gaps` は同じ情報を指す。MVP では `metrics.known_gaps = quality.known_gaps_structured` の copy でよい。

## 6. Fence

既存 `_disclaimer` を `fence` に昇格する。旧 `_disclaimer` は alias として残す。

```json
{
  "fence": {
    "type": "information_only",
    "not_legal_or_tax_advice": true,
    "not_financial_advice": true,
    "not_application_advice": true,
    "not_safety_clearance": true,
    "requires_professional_review_for": [
      "tax",
      "legal",
      "grant_application",
      "audit",
      "credit",
      "regulated_industry"
    ],
    "forbidden_interpretations": [
      "absence_of_record_is_not_proof_of_safety",
      "known_gaps_empty_is_not_guarantee",
      "estimated_tokens_saved_is_not_provider_billing_guarantee"
    ],
    "message_ja": "本 packet は公開情報と一次資料の整理であり、専門判断・保証・申請可否判定ではありません。"
  }
}
```

## 7. Source Receipts

全成果物で source の最低表現を統一する。

```json
{
  "source_receipt_id": "sr_<sha256_url_12>",
  "source_url": "https://...",
  "source_kind": "official_publication",
  "publisher": "中小企業庁",
  "official_owner": "中小企業庁",
  "source_fetched_at": "2026-05-15T00:00:00Z",
  "last_verified_at": "2026-05-15T00:00:00Z",
  "content_hash": "sha256:...",
  "license": "gov_standard_v2.0",
  "attribution_text": "出典: ...",
  "used_in": ["sections[0].rows[2]", "records[0].facts[3]"],
  "verification_status": "unknown",
  "verification_basis": "local_source_catalog",
  "redistribution": {
    "allowed": true,
    "basis": "REDISTRIBUTABLE_LICENSES"
  }
}
```

Required fields for audit-grade receipts:

- `source_receipt_id`
- `source_url`
- `used_in`
- `source_fetched_at` or `last_verified_at`
- `content_hash`
- `license`

Missing required fields must produce `known_gaps.gap_id=source_receipt_missing_fields` and `human_review_required=source_receipt_gap:<id>`.

## 8. Entity Resolution

`entity_resolution[]` は全 packet で、入力 ID と canonical ID の対応を明示する。

```json
{
  "entity_resolution": [
    {
      "input": "T1234567890123",
      "input_kind": "invoice_registration_number",
      "resolved_kind": "houjin",
      "canonical_id": "corporate_entity:1234567890123",
      "display_name": "株式会社テスト",
      "identity_confidence": 1.0,
      "match_method": "normalized_bangou_exact",
      "aliases": ["1234567890123"],
      "known_gaps": []
    }
  ]
}
```

Rules:

- 法人番号/T番号は 13 桁へ正規化し、T prefix は `input` に保持、canonical は T なし。
- 会社名だけで単一法人断定をしてはいけない。`identity_confidence < 0.8` または複数候補は `human_review_required`。
- program は `UNI-*` と `program:*` の両方を保持する。
- query packet は `entity_resolution[]` を返せる範囲だけ埋め、未解決は gap にする。

## 9. Quality

`quality` は旧 Evidence の bool/list と Artifact の structured gaps を吸収する。

```json
{
  "quality": {
    "freshness_bucket": "within_30d",
    "freshness_scope": "corpus_wide_max_not_record_level",
    "freshness_basis": "corpus_snapshot_id",
    "coverage_score": 0.73,
    "source_receipt_completion": {"total": 7, "complete": 5, "incomplete": 2},
    "known_gaps": [
      {
        "gap_id": "source_stale",
        "severity": "warning",
        "section": "source",
        "message": "last_verified is older than 90 days",
        "source_fields": ["records[0].source_fetched_at"],
        "affected_records": ["program:..."],
        "followup_action": "verify_cited_sources"
      }
    ],
    "known_gaps_inventory": [],
    "human_review_required": true,
    "human_review_reasons": ["source_receipt_gap:sr_...", "low_confidence:program:..."]
  }
}
```

MVP known gap enum:

| gap_id | severity | meaning |
|---|---|---|
| `provenance_unavailable` | warning | fact/source provenance unavailable |
| `compat_matrix_unavailable` | warning | compatibility rules unavailable |
| `compat_matrix_no_partner` | info | no partner rows for rule surface |
| `funding_stack_unavailable` | warning | rule engine unavailable |
| `amendment_diff_unavailable` | info | recent change substrate unavailable |
| `compression_unavailable` | info | token compression estimator failed |
| `no_records_returned` | info | no result records |
| `source_url_quality` | review | missing/non-HTTPS source URL |
| `source_stale` | warning | source timestamp older than threshold |
| `low_confidence` | review | record/fact confidence below floor |
| `source_receipts_missing` | review | audit-grade packet has no receipts |
| `source_receipt_missing_fields` | review | receipt missing hash/license/fetched_at/used_in |
| `claim_without_source_coverage` | review | claim row lacks source coverage |
| `identity_ambiguous` | blocking | entity resolution has multiple candidates |
| `identity_not_found` | blocking | subject not found in local mirror |
| `license_unknown` | review | source license not known |
| `license_redacted` | warning | source exists but hidden by license gate |

## 10. Exports

`exports` は出力形式の contract。既存 `copy_paste_parts` と `markdown_display` は残す。

```json
{
  "exports": {
    "json": {
      "available": true,
      "canonical_field": "$"
    },
    "markdown": {
      "available": true,
      "field": "markdown_display",
      "content_type": "text/markdown"
    },
    "csv": {
      "available": true,
      "endpoint": "/v1/packets/{packet_id}/exports.csv",
      "profiles": ["sources", "records", "known_gaps"]
    },
    "copy_paste_parts": [
      {
        "part_id": "summary",
        "title": "Summary",
        "text": "..."
      }
    ]
  }
}
```

Export profiles:

- `json_full`: canonical payload。
- `json_brief`: `facts`, large rows, verbose receipts を落とす。
- `markdown`: human-readable summary + evidence status + follow-up。
- `csv_sources`: `source_receipts[]` を flat table 化。
- `csv_known_gaps`: structured gaps を flat table 化。
- `csv_records`: records/sections rows の flat table。

## 11. Versioning

Use two versions:

- `packet.api_version`: public API major。既存 `v1`。
- `packet.schema_version`: common schema。初期 `1.1`。additive change は minor、breaking change は `2.0`。

Compatibility rules:

1. Additive fields only in `1.x`.
2. Existing top-level fields remain until `api_version=v2`.
3. Removing or changing type of public field requires new schema major.
4. Enum additions are minor-compatible, but clients must treat unknown enum as `unknown`.
5. `known_gaps` may be string list in legacy Evidence; common adapter must normalize to structured dicts.
6. `human_review_required` legacy bool and artifact list coexist:
   - common canonical: `quality.human_review_required: bool`
   - reasons: `quality.human_review_reasons: list[str]`
   - legacy artifact: top-level `human_review_required: list[Any]`

Backward-compatible aliases:

| legacy | canonical |
|---|---|
| `packet_id` | `packet.id` |
| `artifact_id` | `packet.id` plus `artifact_id` retained |
| `artifact_type` | `packet.type` |
| `artifact_version` | `versioning.artifact_version` |
| `api_version` | `packet.api_version` |
| `schema_version` | `packet.schema_version` |
| `generated_at` | `packet.generated_at` |
| `corpus_snapshot_id` | `packet.corpus.snapshot_id` |
| `corpus_checksum` | `packet.corpus.checksum` |
| `_disclaimer` | `fence` |
| `_evidence.source_count` | `metrics.source_count` |
| `evidence_value.source_count` | `metrics.source_count` |
| top-level `source_count` | `metrics.source_count` |
| top-level `known_gaps` | `metrics.known_gaps` / `quality.known_gaps` |
| `estimated_tokens_saved` | `metrics.estimated_tokens_saved` |
| `jpcite_cost_jpy` | `metrics.jpcite_cost_jpy` |
| `markdown_display` | `exports.markdown.field` |
| `copy_paste_parts` | `exports.copy_paste_parts` |

## 12. MVP Implementation Order

P0: Schema adapter, no endpoint breakage

1. Add `services/packet_contract.py`.
   - `normalize_packet_envelope(body, packet_kind, packet_type) -> dict`
   - Adds `packet`, `metadata`, `metrics`, `fence`, `exports`, `versioning`.
   - Preserves legacy fields.
2. Evidence Packet: call adapter at the end of `_compose_single_subject()` and `compose_for_query()`.
3. ArtifactResponse: call adapter inside `_attach_common_artifact_envelope()`.
4. Tests: assert legacy fields still exist and canonical fields are present.

P1: Known gaps normalization

1. Move artifact `_normalize_known_gap` logic into shared service.
2. Convert Evidence string gaps to structured dicts.
3. Keep `quality.known_gaps_legacy` or top-level alias for old string clients if needed.
4. Publish `/v1/meta/known-gaps` enum.

P2: Source receipts everywhere

1. Evidence Packet builds `source_receipts[]` from record primary source, fact sources, rule evidence URLs, pdf refs, recent changes.
2. Apply receipt quality gate to audit-grade artifact and evidence profiles.
3. Add `used_in` paths for every source.

P3: Entity resolution block

1. Evidence program/houjin composers emit `entity_resolution[]`.
2. Artifact company/houjin builders emit entity resolution from normalized input.
3. Ambiguous or low-confidence resolution maps to structured known gap.

P4: Export endpoints

1. `GET /v1/packets/{packet_id}` for stored/replayable paid artifacts only, or stateless regenerate where possible.
2. `GET /v1/packets/{packet_id}/exports/{format}` with `format=json|md|csv`.
3. Batch/export job returns `batch_packet` with child packet IDs.

P5: Strict version gate

1. Add request header `X-JPCite-Packet-Schema: 1.1`.
2. Add response header `X-JPCite-Packet-Schema: 1.1`.
3. Add compact projection support: `?packet_profile=brief|full|verified_only|changes_only`.

## 13. API Naming

Canonical REST names:

| operation | route | notes |
|---|---|---|
| `createEvidencePacket` | `POST /v1/evidence/packets/query` | existing |
| `getEvidencePacket` | `GET /v1/evidence/packets/{subject_kind}/{subject_id}` | existing |
| `createEvidencePacketBatch` | `POST /v1/evidence/packets/batch` | existing/docs |
| `createCompatibilityTable` | `POST /v1/artifacts/compatibility_table` | existing |
| `createApplicationStrategyPack` | `POST /v1/artifacts/application_strategy_pack` | existing |
| `createHoujinDdPack` | `POST /v1/artifacts/houjin_dd_pack` | existing |
| `createCompanyPublicBaseline` | `POST /v1/artifacts/company_public_baseline` | existing |
| `createCompanyFolderBrief` | `POST /v1/artifacts/company_folder_brief` | existing |
| `createCompanyPublicAuditPack` | `POST /v1/artifacts/company_public_audit_pack` | existing |
| `getPacket` | `GET /v1/packets/{packet_id}` | new, replay/stored only |
| `exportPacket` | `GET /v1/packets/{packet_id}/exports/{format}` | new |
| `listPacketSchemas` | `GET /v1/meta/packet-schemas` | new |
| `listKnownGapTypes` | `GET /v1/meta/known-gaps` | new |

MCP naming:

| tool | status | notes |
|---|---|---|
| `get_evidence_packet` | keep | existing |
| `get_evidence_packet_batch` | keep | existing |
| `create_artifact_packet` | add later | generic wrapper with `packet_type` |
| `export_packet` | add later | markdown/csv/json |
| `list_packet_schemas` | add later | client discovery |

Do not rename existing endpoints in v1. New names should be operationId-level and metadata-level, not route-breaking.

## 14. Output Contract

Every packet response must satisfy:

1. It has a stable identity: `packet.id`.
2. It names its type: `packet.kind`, `packet.type`.
3. It names corpus state: `packet.corpus.snapshot_id`.
4. It exposes source accountability: `sources[]` and/or `source_receipts[]`.
5. It exposes gaps as data, not prose-only: `quality.known_gaps[]`.
6. It exposes routing/fence: `fence`, `quality.human_review_required`, `agent_routing` where applicable.
7. It exposes cost/context hints: `metrics.jpcite_cost_jpy`, `metrics.estimated_tokens_saved`, `metrics.source_count`, `metrics.known_gaps`.
8. It does not imply answer generation by jpcite unless explicitly a generated artifact. Evidence packets keep `metadata.answer_not_included=true`.
9. It never treats empty data as proof of safety/absence.
10. It remains v1 backward-compatible through aliases.

## 15. Concrete Acceptance Tests

Minimum tests:

- Evidence single program response contains both `packet.id` and legacy `packet_id`.
- Evidence query response contains `metrics.source_count == source_count`.
- Artifact response contains `packet.type == artifact_type`.
- Artifact response contains `metrics.source_count == _evidence.source_count`.
- Any string `known_gaps` input becomes structured `quality.known_gaps[]`.
- Legacy artifact `human_review_required: list` maps to `quality.human_review_required=true` when non-empty.
- `_disclaimer` and `fence` both exist and agree on `not_legal_or_tax_advice`.
- `source_receipts[]` missing required audit fields creates `source_receipt_missing_fields`.
- `schema_version=1.1` is additive: existing tests for v1 fields continue passing.

## 16. Decision

Adopt Common Packet Schema `1.1` as an additive overlay. Do not replace existing Evidence Packet or ArtifactResponse shapes in v1. Implement a shared adapter first, then migrate producers one by one. The value is immediate for agents: every output can be inspected through the same small contract (`packet`, `metrics`, `quality`, `fence`, `source_receipts`, `exports`) while old clients continue to read their existing fields.
