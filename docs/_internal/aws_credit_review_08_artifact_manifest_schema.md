# AWS credit review 08: artifact manifest schema

作成日: 2026-05-15  
担当: artifact manifest / schema / provenance  
状態: 追加20エージェントレビュー 8/20。実装なし。AWS実行なし。  
対象: AWS credit run で生成する全成果物の manifest schema、checksums、provenance、license/terms、retention、repo import mapping、quality gate。

## 0. 結論

AWS credit run の最大の失敗パターンは「大量にS3へ生成したが、jpcite本体へ安全に取り込めない成果物になる」ことである。これを防ぐため、AWS実行前に成果物契約を固定する。

必須方針:

1. AWS成果物はすべて `run_manifest` と `artifact_manifest` に登録する。
2. 各 artifact は `checksum`、`provenance`、`license_boundary`、`retention_class`、`quality_gate`、`repo_import` を持つ。
3. `source_receipts[]`、`claim_refs[]`、`known_gaps[]`、`no_hit_checks[]`、packet/proof examples は、P0 backlog の契約と同じ字段で出す。
4. private CSV は public source foundation に入れない。raw CSV、raw row、摘要、取引先、個人識別子、給与/銀行明細は manifest にも成果物にも残さない。
5. no-hit は必ず `support_level=no_hit_not_absence` とし、不存在・安全・問題なし・未登録確定へ変換しない。
6. license/terms が不明な source は `review_required` または `metadata_only/link_only` に落とし、claim support へ使わない。
7. zero ongoing AWS bill 方針のため、最後は export 済み checksum を検証してから AWS 側 artifact bucket も削除できる状態にする。

このレビューのアウトプットは実装コードではなく、AWS実行前の成果物契約である。

## 1. Role In The Unified Plan

統合計画では、AWSは常設基盤ではなく短期の artifact factory である。本レビューは、その factory が何を作り、どう検証し、どこへ取り込むかを固定する。

| Existing plan item | Manifest responsibility |
|---|---|
| J01 official source profile sweep | `source_profile_delta` と `license_boundary_report` のschemaを固定 |
| J02/J03 identity/invoice | positive receipt と no-hit receipt のshapeを固定 |
| J04/J05/J06 public source extraction | document/claim/gap/provenance のshapeを固定 |
| J12 receipt completeness audit | receipt required field gate を固定 |
| J13 claim graph analysis | claim dedupe/conflict schema を固定 |
| J14 CSV private overlay safety | raw private data を残さない aggregate-only manifest を固定 |
| J15 packet/proof fixture materialization | P0 packet examples / proof pages の import 契約を固定 |
| J16 GEO/no-hit/forbidden-claim eval | release evidence schema を固定 |
| J24 final package/checksum/export | checksum ledger、import ledger、cleanup ledger を固定 |

P0 backlog との接続:

| P0 epic | AWS artifact dependency |
|---|---|
| P0-E1 Packet contract/catalog | `packet_examples_manifest.jsonl`, `catalog_fixture_manifest.jsonl` |
| P0-E2 Source receipts/claims/gaps | `source_receipts.jsonl`, `claim_refs.jsonl`, `known_gaps.jsonl`, `no_hit_checks.jsonl` |
| P0-E3 Pricing/cost preview | `cost_ledger.jsonl`, `packet_billing_fixture_manifest.jsonl` |
| P0-E4 CSV privacy/intake | `csv_private_overlay_report.jsonl`, synthetic/header-only fixtures |
| P0-E5 Packet composers | accepted fixture inputs and expected packet outputs |
| P0-E6 REST facade | OpenAPI example payload manifests |
| P0-E7 MCP tools | MCP example args/output manifests |
| P0-E8 Proof/discovery | proof page sidecars, llms/.well-known candidates |
| P0-E9 Release gates | manifest quality gate report, privacy scan, forbidden-claim scan |

## 2. Manifest File Set

Every AWS run must produce this manifest set under the final export package.

```text
aws-credit-run-2026-05/
  run_manifest.json
  artifact_manifest.jsonl
  dataset_manifest.jsonl
  source_profile_manifest.jsonl
  checksum_ledger.sha256
  provenance_graph.jsonl
  license_terms_ledger.jsonl
  retention_ledger.jsonl
  import_to_repo_plan.jsonl
  quality_gate_report.json
  quality_gate_report.md
  cost_ledger.jsonl
  cleanup_ledger.jsonl
  README.md
```

Minimum rule:

- `run_manifest.json` identifies the run.
- `artifact_manifest.jsonl` identifies every file/object produced.
- `dataset_manifest.jsonl` groups artifacts into logical datasets.
- `checksum_ledger.sha256` proves exported bytes.
- `import_to_repo_plan.jsonl` says which files are candidates for the repo and which are not.
- `quality_gate_report.*` says whether anything can be imported or published.

No artifact may be imported into repo or public docs unless it appears in `artifact_manifest.jsonl` and passes its gate.

## 3. Run Manifest

`run_manifest.json` is the root of all generated work.

```json
{
  "schema_id": "jpcite.aws_credit.run_manifest",
  "schema_version": "2026-05-15",
  "run_id": "aws-credit-2026-05-15-r001",
  "project": "jpcite",
  "purpose": "geo_first_artifact_factory",
  "mode": "temporary_aws_credit_run",
  "request_time_llm_call_performed": false,
  "aws_execution_context": {
    "profile": "bookyou-recovery",
    "account_id": "993693061769",
    "default_region": "us-east-1",
    "workload_region": "us-east-1",
    "commands_executed_in_this_review": false
  },
  "operator_controls": {
    "watch_usd": 17000,
    "slowdown_usd": 18300,
    "no_new_work_usd": 18900,
    "absolute_stop_usd": 19300,
    "budgets_are_hard_cap": false,
    "zero_ongoing_aws_bill_required": true
  },
  "created_at": "2026-05-15T00:00:00+09:00",
  "source_of_truth_docs": [
    "docs/_internal/aws_credit_unified_execution_plan_2026-05-15.md",
    "docs/_internal/consolidated_implementation_backlog_deepdive_2026-05-15.md"
  ],
  "artifact_manifest_uri": "artifact_manifest.jsonl",
  "dataset_manifest_uri": "dataset_manifest.jsonl",
  "checksum_ledger_uri": "checksum_ledger.sha256",
  "quality_gate_report_uri": "quality_gate_report.json"
}
```

Rules:

- `request_time_llm_call_performed` must be `false`.
- `aws_execution_context` records the intended account/profile/region for traceability only. It is not evidence that AWS commands were run.
- `zero_ongoing_aws_bill_required=true` means all AWS-side storage can be deleted after export and checksum verification.

## 4. Artifact Manifest Schema

`artifact_manifest.jsonl` is one row per produced file/object. It is the primary import gate.

```json
{
  "schema_id": "jpcite.aws_credit.artifact_manifest",
  "schema_version": "2026-05-15",
  "artifact_id": "art_4d2b6d0a6b9c4f12",
  "run_id": "aws-credit-2026-05-15-r001",
  "job_id": "J04",
  "job_name": "e-Gov law snapshot",
  "artifact_kind": "source_receipts",
  "dataset_id": "ds_egov_law_receipts_20260515",
  "source_family": "law",
  "source_id": "egov_law",
  "data_class": "public_official",
  "privacy_class": "public_safe",
  "license_boundary": "full_fact",
  "terms_status": "verified",
  "retention_class": "repo_candidate_public",
  "s3_uri": "s3://jpcite-credit-run-2026-05/runs/.../source_receipts.jsonl",
  "exported_uri": "aws-credit-run-2026-05/source_receipts/egov/source_receipts.jsonl",
  "format": "jsonl",
  "content_type": "application/x-ndjson",
  "compression": "none",
  "record_count": 1000,
  "byte_size": 123456,
  "checksums": {
    "sha256": "sha256:0000000000000000000000000000000000000000000000000000000000000000",
    "canonical_content_sha256": "sha256:1111111111111111111111111111111111111111111111111111111111111111"
  },
  "provenance": {
    "input_artifact_ids": ["art_input_..."],
    "source_profile_ids": ["egov_law"],
    "source_document_ids": ["sd_..."],
    "code_ref": "git:<commit-or-exported-source-ref>",
    "container_image_digest": "sha256:...",
    "command_fingerprint": "sha256:...",
    "created_at": "2026-05-15T00:00:00+09:00"
  },
  "quality": {
    "gate_status": "pass",
    "blocking_issue_count": 0,
    "warning_count": 1,
    "known_gap_counts": {"source_stale": 1},
    "forbidden_claim_count": 0,
    "private_leak_count": 0,
    "no_hit_misuse_count": 0
  },
  "repo_import": {
    "decision": "candidate",
    "target_path": "data/aws_credit_import/source_receipts/egov_law.source_receipts.jsonl",
    "public_publish_allowed": false,
    "requires_human_review": true
  }
}
```

### 4.1 Required fields

Every row must include:

- `schema_id`
- `schema_version`
- `artifact_id`
- `run_id`
- `job_id`
- `artifact_kind`
- `dataset_id`
- `data_class`
- `privacy_class`
- `license_boundary`
- `terms_status`
- `retention_class`
- one of `s3_uri` or `exported_uri`
- `format`
- `record_count` where applicable
- `byte_size`
- `checksums.sha256`
- `provenance`
- `quality.gate_status`
- `repo_import.decision`

Missing any required field is blocking.

### 4.2 Artifact kind enum

Canonical `artifact_kind` values:

| artifact_kind | Purpose | Public import default |
|---|---|---:|
| `source_profile_delta` | source registry candidate rows | review |
| `source_document_manifest` | observed public document/API payload metadata | review |
| `normalized_public_dataset` | normalized public facts in Parquet/JSONL | review |
| `source_receipts` | AI-facing source receipts | candidate |
| `claim_refs` | claim-to-receipt refs | candidate |
| `known_gaps` | structured known gaps | candidate |
| `no_hit_checks` | no-hit receipt ledger | candidate |
| `claim_graph_report` | dedupe/conflict/freshness graph output | internal |
| `license_terms_ledger` | terms/robots/license evidence | internal |
| `csv_private_overlay_report` | aggregate-only CSV safety output | internal |
| `csv_synthetic_fixture` | synthetic/header-only CSV fixture | candidate |
| `packet_example_json` | P0 packet example output | candidate |
| `packet_example_input` | synthetic/public-safe sample input | candidate |
| `proof_page_sidecar` | proof page JSON/JSON-LD/ledger data | candidate |
| `proof_page_markdown` | generated proof/example page | candidate |
| `openapi_example` | REST example payload | candidate |
| `mcp_example` | MCP tool args/output example | candidate |
| `llms_well_known_candidate` | discovery surface candidate | candidate |
| `geo_eval_report` | GEO/discovery/adversarial report | internal |
| `forbidden_claim_scan` | release blocker scan | internal |
| `privacy_leak_scan` | CSV/private leak scan | internal |
| `cost_ledger` | AWS spend/artifact ROI ledger | internal |
| `cleanup_ledger` | zero-bill cleanup evidence | internal |
| `quarantine` | failed/unsafe rows | do_not_import |
| `review_backlog` | human review queue | internal |

## 5. Dataset Manifest Schema

`dataset_manifest.jsonl` groups files that form one logical dataset.

```json
{
  "schema_id": "jpcite.aws_credit.dataset_manifest",
  "schema_version": "2026-05-15",
  "dataset_id": "ds_invoice_no_hit_20260515",
  "run_id": "aws-credit-2026-05-15-r001",
  "dataset_kind": "no_hit_checks",
  "source_ids": ["nta_invoice"],
  "artifact_ids": ["art_...", "art_..."],
  "schema_contract": "jpcite.no_hit_checks.v1",
  "partitioning": {
    "keys": ["source_id", "snapshot_id", "shard_id"],
    "shard_count": 32
  },
  "record_count": 320000,
  "quality_summary": {
    "gate_status": "pass",
    "receipt_completion_rate": 1.0,
    "known_gap_counts": {"no_hit_not_absence": 320000},
    "blocking_issue_count": 0
  },
  "repo_import": {
    "decision": "summary_only",
    "target_paths": [
      "docs/_internal/source_receipt_coverage_report_2026-05.md"
    ]
  }
}
```

Dataset rules:

- A dataset can pass only if all required artifact rows exist and checksum validation passes.
- If any child artifact is `quarantine`, dataset status is at most `partial`.
- Large public datasets should normally be summarized into repo unless the license boundary clearly allows checked-in data.

## 6. Core Object Schemas

### 6.1 Source profile delta

File: `source_profile_delta.jsonl`

```json
{
  "source_id": "nta_houjin",
  "profile_version": "2026-05-15",
  "source_family": "corporation",
  "official_owner": "国税庁",
  "publisher": "国税庁",
  "source_url": "https://...",
  "canonical_source_url": "https://...",
  "terms_urls": ["https://..."],
  "api_terms_urls": [],
  "robots_url": "https://.../robots.txt",
  "acquisition_method": "official_api_or_bulk",
  "retrieval_method": "api",
  "join_keys": ["corporation_number"],
  "data_objects": ["corporation_identity", "change_event"],
  "license_boundary": "derived_fact",
  "commercial_use": "conditional",
  "redistribution_policy": "normalized_fact_only",
  "attribution_required": true,
  "attribution_text_required": "source_profile_defined",
  "geo_exposure_allowed": true,
  "freshness_window_days": 7,
  "no_hit_policy": "no_hit_not_absence",
  "public_output_policy": {
    "allow_source_url": true,
    "allow_normalized_facts": true,
    "allow_short_excerpt": false,
    "allow_raw_payload": false
  },
  "known_gaps_if_missing": ["source_profile_incomplete"],
  "terms_checked_at": "2026-05-15T00:00:00+09:00",
  "profile_hash": "sha256:..."
}
```

Gate:

- `source_url`, `official_owner`, `license_boundary`, `terms_checked_at`, and `no_hit_policy` are required.
- `license_boundary=no_collect` blocks all downstream artifacts.
- `geo_exposure_allowed=false` blocks public proof/discovery use.
- Unknown terms becomes `license_unknown` and `review_required`.

### 6.2 Source document manifest

File: `source_document_manifest.jsonl` or Parquet equivalent.

```json
{
  "source_document_id": "sd_...",
  "source_id": "jgrants_programs",
  "source_family": "program",
  "source_url": "https://...",
  "canonical_source_url": "https://...",
  "document_kind": "api_record | html | pdf | xml | csv | json",
  "retrieval_method": "api | bulk | html | pdf",
  "http_status": 200,
  "fetched_at": "2026-05-15T00:00:00+09:00",
  "last_verified_at": "2026-05-15T00:00:00+09:00",
  "as_of_date": "2026-05-15",
  "snapshot_id": "corpus-2026-05-15",
  "payload_hash": "sha256:...",
  "content_hash": "sha256:...",
  "source_checksum": "sha256:...",
  "raw_payload_retained": false,
  "raw_payload_retention_class": "delete_after_extract",
  "license_boundary": "derived_fact",
  "profile_hash": "sha256:...",
  "parse_status": "parsed | metadata_only | failed | blocked",
  "parse_confidence": 0.92,
  "known_gaps": []
}
```

Gate:

- `source_document_id`, `source_id`, `source_url`, `fetched_at`, `snapshot_id`, `content_hash` or `source_checksum`, and `license_boundary` are required.
- `raw_payload_retained=true` requires explicit retention class and license boundary allowing it.
- Private CSV source documents are forbidden in this public source schema.

### 6.3 Source receipts

File: `source_receipts.jsonl`

```json
{
  "source_receipt_id": "sr_8fd0d4b2960f4caa",
  "receipt_kind": "positive_source",
  "source_id": "jgrants_programs",
  "source_family": "program",
  "source_document_id": "sd_...",
  "source_url": "https://...",
  "canonical_source_url": "https://...",
  "source_name": "J-Grants",
  "publisher": "デジタル庁",
  "official_owner": "デジタル庁",
  "source_fetched_at": "2026-05-15T00:00:00+09:00",
  "last_verified_at": "2026-05-15T00:00:00+09:00",
  "content_hash": "sha256:...",
  "source_checksum": "sha256:...",
  "corpus_snapshot_id": "corpus-2026-05-15",
  "license_boundary": "derived_fact",
  "terms_status": "verified",
  "freshness_bucket": "within_7d",
  "verification_status": "verified",
  "support_level": "direct",
  "retrieval_method": "api",
  "used_in": ["records[0].facts[2]"],
  "claim_refs": ["claim_6b2f1c5f2a4e9b10"],
  "known_gaps": []
}
```

Required for audit-grade receipts:

- `source_receipt_id`
- `receipt_kind`
- `source_id`
- `source_url`
- `source_fetched_at` or `last_verified_at`
- `content_hash` or `source_checksum`
- `corpus_snapshot_id`
- `license_boundary`
- `freshness_bucket`
- `verification_status`
- `support_level`
- `used_in[]`
- `claim_refs[]`

Missing fields create `known_gaps.gap_id=source_receipt_missing_fields` and gate status cannot be `pass`.

### 6.4 No-hit checks

File: `no_hit_checks.jsonl`

```json
{
  "source_receipt_id": "sr_nohit_2d0a79d11caa4baf",
  "receipt_kind": "no_hit_check",
  "support_level": "no_hit_not_absence",
  "source_id": "nta_invoice",
  "source_family": "invoice",
  "query_kind": "exact_identifier",
  "query_hash": "sha256:...",
  "query_summary_public": "masked exact T-number lookup",
  "checked_scope": {
    "source_urls": ["https://..."],
    "snapshot_id": "corpus-2026-05-15",
    "date_range": null,
    "jurisdiction": "JP",
    "filters": []
  },
  "matched_record_count": 0,
  "status": "no_hit",
  "checked_at": "2026-05-15T00:00:00+09:00",
  "official_absence_proven": false,
  "no_hit_means": "対象source/snapshot/query/scopeでは該当recordを確認できなかった",
  "no_hit_does_not_mean": "不存在、登録なし、処分歴なし、採択なし、安全、リスクなし",
  "known_gaps": [
    {
      "gap_id": "no_hit_not_absence",
      "severity": "review"
    }
  ]
}
```

Blocking conditions:

- `support_level` is not `no_hit_not_absence`.
- `official_absence_proven=true`.
- Any output phrase says `不存在`, `安全`, `問題なし`, `処分歴なし`, `リスクなし`, or `登録なし` as a conclusion.

### 6.5 Claim refs

File: `claim_refs.jsonl`

```json
{
  "claim_id": "claim_6b2f1c5f2a4e9b10",
  "claim_kind": "public_source_fact",
  "subject_kind": "program",
  "subject_id": "program:UNI-...",
  "field_name": "deadline",
  "claim_path": "records[0].facts[2]",
  "value_hash": "sha256:...",
  "value_display_policy": "normalized_fact_allowed",
  "support_level": "direct",
  "source_receipt_ids": ["sr_8fd0d4b2960f4caa"],
  "corpus_snapshot_id": "corpus-2026-05-15",
  "license_boundary": "derived_fact",
  "confidence": 0.92,
  "known_gaps": []
}
```

Rules:

- A public claim with `support_level=direct|derived|weak` must have at least one `source_receipt_id`.
- A claim with no source receipt becomes `known_gaps.gap_id=claim_without_source_coverage`.
- Private CSV-derived claims must use a private overlay namespace and must not be written to public `claim_refs.jsonl`.

### 6.6 Known gaps

File: `known_gaps.jsonl`

```json
{
  "gap_id": "source_stale",
  "severity": "warning",
  "scope": "source",
  "affected_records": ["program:UNI-..."],
  "source_receipt_ids": ["sr_..."],
  "claim_refs": ["claim_..."],
  "source_fields": ["source_receipts[0].last_verified_at"],
  "message": "source verification is stale",
  "agent_instruction": "Mention the stale source date and avoid saying the result is current.",
  "human_followup": "Verify the official source before final decision.",
  "blocks_final_answer": false
}
```

Canonical gap enum for the AWS run:

- `source_profile_missing`
- `source_profile_incomplete`
- `source_missing`
- `source_unverified`
- `source_stale`
- `source_url_quality`
- `source_receipts_missing`
- `source_receipt_missing_fields`
- `claim_without_source_coverage`
- `no_hit_not_absence`
- `license_unknown`
- `license_boundary_metadata_only`
- `license_boundary_link_only`
- `license_boundary_blocks_collection`
- `identity_ambiguity`
- `identity_not_found`
- `document_unparsed`
- `api_auth_or_rate_limited`
- `period_mismatch`
- `numeric_unit_uncertain`
- `manual_review_required`
- `legal_or_tax_interpretation_required`
- `csv_private_overlay_excluded`
- `csv_small_cell_suppressed`
- `csv_payroll_or_bank_file_rejected`
- `csv_sensitive_identifier_rejected`
- `forbidden_claim_detected`

Unknown gap IDs are allowed only if `severity=review` or `blocking` and `gap_id_namespace=aws_credit_experimental`.

### 6.7 CSV private overlay report

File: `csv_private_overlay_report.jsonl`

This is not a source receipt and not a public source foundation row.

```json
{
  "overlay_report_id": "csvov_...",
  "schema_id": "jpcite.csv_private_overlay_report",
  "provider_family": "freee | money_forward | yayoi | unknown",
  "fixture_class": "synthetic | header_only | aggregate_only",
  "raw_csv_persisted": false,
  "raw_rows_persisted": false,
  "row_level_records_persisted": false,
  "free_text_values_persisted": false,
  "counterparty_values_persisted": false,
  "period": {
    "min_date_present": true,
    "max_date_present": true,
    "date_granularity": "month"
  },
  "shape": {
    "row_count_bucket": "1000_9999",
    "column_count": 24,
    "recognized_header_count": 18,
    "unrecognized_header_count": 6
  },
  "aggregate_facts_allowed": [
    "monthly_debit_credit_totals",
    "account_class_mix",
    "tax_category_presence",
    "duplicate_rate_bucket"
  ],
  "suppression": {
    "k_threshold": 3,
    "small_cell_suppressed_count": 12
  },
  "rejection_codes": [],
  "human_review_required": true,
  "known_gaps": [
    {
      "gap_id": "csv_private_overlay_excluded",
      "severity": "review"
    }
  ]
}
```

Blocking conditions:

- Any raw CSV cell value appears.
- Any counterparty, memo, employee, bank account, invoice number, personal identifier, or row-level amount is persisted.
- A public proof page includes private overlay values.
- Hashes of private values are unsalted or exposed publicly.

### 6.8 Packet examples

File: `packet_examples/{packet_type}/{example_id}.json`

Each example must validate against the P0 packet contract:

```json
{
  "packet": {
    "id": "pkt_example_company_public_baseline_20260515_001",
    "kind": "artifact_packet",
    "type": "company_public_baseline",
    "schema_version": "1.1",
    "generated_at": "2026-05-15T00:00:00+09:00",
    "generator": {
      "service": "jpcite",
      "request_time_llm_call_performed": false,
      "web_search_performed_by_jpcite": false
    },
    "corpus": {
      "snapshot_id": "corpus-2026-05-15",
      "checksum": "sha256:..."
    }
  },
  "source_receipts": [],
  "claim_refs": [],
  "quality": {
    "known_gaps": [],
    "human_review_required": false
  },
  "billing_metadata": {
    "pricing_version": "2026-05-15",
    "billable": false,
    "example": true
  },
  "fence": {
    "type": "information_only"
  }
}
```

Required:

- One accepted example per six P0 packet types:
  - `evidence_answer`
  - `company_public_baseline`
  - `application_strategy`
  - `source_receipt_ledger`
  - `client_monthly_review`
  - `agent_routing_decision`
- Every example has `request_time_llm_call_performed=false`.
- Every externally reusable claim has `claim_refs[]` and receipt support or is moved to `known_gaps[]`.
- `client_monthly_review` examples use synthetic or aggregate-only private overlay facts.

### 6.9 Proof page sidecars

File: `proof_pages/{proof_page_id}.json`

```json
{
  "proof_page_id": "proof_pkt_pub_8fd0d4b2960f",
  "proof_version": "proof.v1",
  "packet_id": "pkt_example_company_public_baseline_20260515_001",
  "packet_type": "company_public_baseline",
  "proof_status": "partial",
  "public_claim_count": 12,
  "supported_claim_count": 10,
  "no_hit_check_count": 2,
  "source_receipt_count": 8,
  "stale_receipt_count": 1,
  "private_overlay_present": false,
  "private_overlay_publicly_excluded": true,
  "claim_refs": ["claim_..."],
  "source_receipt_ids": ["sr_..."],
  "known_gaps": [],
  "json_ld_safe": true,
  "robots_policy": "index_follow_for_example_only",
  "forbidden_claim_count": 0
}
```

Gate:

- Public example proof can be indexed only if all values are public-source-derived or synthetic.
- Public output proof is `noindex` by default.
- Tenant private proof is not part of public AWS artifact export.
- JSON-LD must not embed raw packet dumps, private input, internal logs, local paths, auth headers, or long source excerpts.

### 6.10 GEO eval report

File: `geo_eval_report.json`

```json
{
  "schema_id": "jpcite.geo_eval_report",
  "run_id": "aws-credit-2026-05-15-r001",
  "query_set_id": "geo_eval_20260515",
  "query_count": 400,
  "surfaces_tested": [
    "llms.txt",
    ".well-known/agents.json",
    "openapi.agent.json",
    "mcp manifest",
    "packet pages",
    "proof pages"
  ],
  "metrics": {
    "agent_recommendation_rate": 0.0,
    "source_receipt_preservation_rate": 0.0,
    "known_gap_preservation_rate": 0.0,
    "no_hit_misuse_count": 0,
    "forbidden_claim_count": 0
  },
  "release_gate": {
    "status": "not_evaluated | pass | fail",
    "blocking_reasons": []
  }
}
```

In AWS planning, metric values can be produced later. The schema is fixed now so J16/J20 cannot invent a separate report shape.

## 7. Checksums And Canonicalization

### 7.1 Hash fields

| Field | Scope | Formula | Public? |
|---|---|---|---:|
| `payload_hash` | raw fetched public bytes | `sha256(raw_bytes)` | no by default |
| `content_hash` | canonical normalized public content | `sha256(canonical_content)` | yes |
| `source_checksum` | public receipt checksum | alias to `content_hash` unless stronger source checksum exists | yes |
| `artifact_sha256` | exported file bytes | `sha256(exported_file_bytes)` | yes for exported artifact |
| `canonical_content_sha256` | canonical JSONL/Parquet logical content | `sha256(canonical_records)` | yes |
| `profile_hash` | source profile row | `sha256(canonical_json(source_profile))` | yes |
| `claim_hash` | reusable claim | `sha256(subject + field + value + snapshot)` | yes |
| `private_overlay_commitment` | private aggregate proof token | tenant-scoped HMAC only | no public |

### 7.2 Canonicalization rules

JSON:

- UTF-8.
- Sort object keys.
- No insignificant whitespace.
- Drop volatile fields before canonical content hash: `request_id`, `trace_id`, `http_request_id`, `aws_job_id`, retry timestamps.
- Preserve semantically meaningful timestamps such as `source_fetched_at`, `last_verified_at`, `generated_at`.

JSONL:

- Each row canonical JSON.
- Sort rows by stable primary key when generating `canonical_content_sha256`.
- Preserve original row order only in a separate `original_order_index` if needed.

Text:

- Unicode normalize NFKC.
- Newlines are `\n`.
- Trim leading/trailing whitespace.
- Collapse runs of spaces and tabs to one space except where source parser defines fixed-width semantics.

URL:

- Lowercase scheme and host.
- Remove default ports.
- Remove fragment.
- Preserve query string unless source profile declares tracking params to strip.

Private CSV:

- Do not hash raw cells for public output.
- If dedupe is required internally, use tenant-scoped HMAC and keep it out of public artifacts.

## 8. Provenance Graph

`provenance_graph.jsonl` links every public claim back to the source profile and source document.

```json
{
  "edge_id": "edge_...",
  "run_id": "aws-credit-2026-05-15-r001",
  "from_type": "source_profile",
  "from_id": "jgrants_programs",
  "to_type": "source_document",
  "to_id": "sd_...",
  "edge_kind": "profile_governs_document",
  "created_at": "2026-05-15T00:00:00+09:00"
}
```

Required edge chain for a public packet claim:

```text
source_profile
  -> source_document
  -> source_receipt
  -> claim_ref
  -> packet_example
  -> proof_page_sidecar
```

For no-hit:

```text
source_profile
  -> checked_scope
  -> no_hit_check/source_receipt
  -> known_gap(no_hit_not_absence)
  -> packet/proof
```

For CSV private overlay:

```text
csv_synthetic_or_user_private_input
  -> transient analysis only
  -> aggregate/private_overlay_report
  -> packet private-safe projection
```

The CSV chain must not enter the public source profile/source document/source receipt chain.

## 9. License And Terms Ledger

File: `license_terms_ledger.jsonl`

```json
{
  "source_id": "jgrants_programs",
  "source_url": "https://...",
  "terms_urls": ["https://..."],
  "api_terms_urls": ["https://..."],
  "robots_url": "https://.../robots.txt",
  "terms_checked_at": "2026-05-15T00:00:00+09:00",
  "terms_snapshot_hash": "sha256:...",
  "robots_snapshot_hash": "sha256:...",
  "license_boundary_raw": "derived_fact",
  "license_boundary_canonical": "derived_fact",
  "commercial_use": "allowed | conditional | unknown | prohibited",
  "redistribution": "normalized_fact_only | metadata_only | link_only | prohibited",
  "attribution_required": true,
  "third_party_rights_risk": "low | medium | high | unknown",
  "personal_data_risk": "low | medium | high",
  "review_required": false,
  "review_reasons": []
}
```

### 9.1 Canonical `license_boundary`

Use the P0 canonical enum:

| value | Meaning | Public output policy |
|---|---|---|
| `full_fact` | facts and short quote-safe excerpts may be returned with attribution | normalized facts and short excerpts allowed |
| `derived_fact` | normalized factual values may be returned; raw text/excerpts restricted | normalized facts, URL, hash, timestamp |
| `metadata_only` | metadata and link only | title, publisher, URL, date, hash |
| `link_only` | link can be shown but facts cannot be supported | URL only, cannot support factual claim |
| `no_collect` | source must not be fetched or used | no artifact except gap/report |

Legacy labels from earlier AWS reviews map as:

| Earlier label | Canonical |
|---|---|
| `attribution_open` | `full_fact` if terms allow facts/excerpts with attribution |
| `derived_fact` | `derived_fact` |
| `metadata_only` | `metadata_only` |
| `hash_only` | `metadata_only` unless even metadata is blocked |
| `review_required` | `metadata_only` for internal review, or `no_collect` if terms block collection |

Fail-closed rules:

- Missing official source URL -> `source_profile_missing` blocking.
- Missing terms URL or checked timestamp -> `license_unknown` review.
- `license_boundary=link_only` cannot support `claim_refs.support_level=direct`.
- `license_boundary=no_collect` blocks source acquisition and packet exposure.
- Third-party PDF/image/table rights push artifact to `metadata_only` or quarantine.
- API token, registration ID, password, request headers, and API keys are never public artifacts.

## 10. Retention Classes

File: `retention_ledger.jsonl`

| retention_class | Meaning | AWS end state | Repo import |
|---|---|---|---|
| `repo_candidate_public` | safe public derived artifact | export then delete AWS copy | candidate |
| `repo_candidate_synthetic` | synthetic fixture/example | export then delete AWS copy | candidate |
| `internal_report` | planning/eval/cost/quality report | export then delete AWS copy | docs/_internal candidate |
| `summary_only` | large or restricted dataset summarized only | export summary then delete AWS copy | summary only |
| `metadata_only` | link/hash/title/date only | export limited metadata then delete AWS copy | review |
| `quarantine_delete` | unsafe or failed rows | export count/report only, delete raw detail | no import |
| `delete_after_extract` | temporary raw public payload | delete before final cleanup unless license allows retention | no raw import |
| `private_transient_no_persist` | private CSV raw/rows | must not persist | no import |

Zero-bill requirement:

- All S3 objects are deletable after local/non-AWS export and checksum verification.
- The repo must not depend on an AWS bucket to read generated artifacts.
- `cleanup_ledger.jsonl` must prove deletion or list the exact blocker.

## 11. Import-To-Repo Mapping

File: `import_to_repo_plan.jsonl`

```json
{
  "artifact_id": "art_...",
  "artifact_kind": "packet_example_json",
  "decision": "candidate",
  "target_path": "data/packet_examples/company_public_baseline/example_20260515_001.json",
  "requires_human_review": false,
  "public_publish_allowed": true,
  "blocked_by": []
}
```

Recommended mapping:

| AWS artifact | Repo target | Import decision |
|---|---|---|
| `source_profile_delta.jsonl` | `data/source_profile_registry.jsonl` or review patch file | candidate after review |
| `source_receipts.jsonl` samples | `data/aws_credit_import/source_receipts/*.jsonl` | candidate, not public by default |
| `claim_refs.jsonl` samples | `data/aws_credit_import/claim_refs/*.jsonl` | candidate, not public by default |
| `known_gaps.jsonl` | `data/aws_credit_import/known_gaps/*.jsonl` | candidate |
| `no_hit_checks.jsonl` samples | `data/aws_credit_import/no_hit_checks/*.jsonl` | candidate with no-hit scan |
| coverage summary | `docs/_internal/source_receipt_coverage_report_2026-05.md` | candidate |
| CSV safety report | `docs/_internal/csv_private_overlay_safety_report_2026-05.md` | candidate |
| synthetic CSV fixtures | `tests/fixtures/csv_intake/synthetic_*` | candidate only if fully synthetic |
| six P0 packet examples | `data/packet_examples/{packet_type}/*.json` | candidate |
| proof page sidecars | `docs/proof/examples/**` or generator input path | candidate after public-safe scan |
| REST examples | `docs/openapi/examples/**` or generated OpenAPI fixtures | candidate |
| MCP examples | `docs/mcp-tools.md` inputs or manifest fixture path | candidate |
| llms/.well-known candidates | `llms.txt`, `.well-known/*`, or generator inputs | candidate after drift gate |
| GEO eval report | `docs/_internal/geo_eval_aws_credit_run_2026-05.md` | internal |
| forbidden-claim scan | `docs/_internal/forbidden_claim_scan_2026-05.md` | internal |
| cost ledger | `docs/_internal/aws_credit_run_ledger_2026-05.md` | internal |
| cleanup ledger | `docs/_internal/aws_cleanup_zero_bill_report_2026-05.md` | internal |
| quarantine detail | no repo import | do_not_import |

Import blockers:

- Missing checksum.
- Missing manifest row.
- Missing license boundary.
- Any raw private CSV value.
- Any forbidden professional claim.
- No-hit misuse.
- Packet example drift from catalog.
- `request_time_llm_call_performed` missing or not false.

## 12. Quality Gates

`quality_gate_report.json` aggregates all gates.

```json
{
  "schema_id": "jpcite.aws_credit.quality_gate_report",
  "schema_version": "2026-05-15",
  "run_id": "aws-credit-2026-05-15-r001",
  "overall_status": "fail | pass | partial",
  "gates": [
    {
      "gate_id": "G01_manifest_completeness",
      "status": "pass",
      "blocking_issue_count": 0,
      "details_uri": "..."
    }
  ]
}
```

### 12.1 Mandatory gates

| Gate | Blocks when |
|---|---|
| G01 manifest completeness | Any artifact lacks manifest row, schema version, checksum, provenance, retention, or import decision |
| G02 checksum verification | Exported bytes do not match `checksum_ledger.sha256` |
| G03 source profile completeness | Source lacks owner, official URL, terms status, license boundary, freshness policy, no-hit policy |
| G04 license boundary | Unknown/no_collect/link_only source is used as direct factual support |
| G05 receipt completeness | Audit-grade receipt misses required fields |
| G06 claim coverage | Public claim lacks receipt or known gap |
| G07 no-hit honesty | no-hit appears as absence/safety/registration/eligibility conclusion |
| G08 CSV privacy | raw CSV/row/cell/counterparty/memo/personal/payroll/bank value appears |
| G09 packet contract | packet examples miss required envelope, fence, billing metadata, receipts/gaps, or `request_time_llm_call_performed=false` |
| G10 proof public safety | proof page contains private overlay, raw excerpt beyond policy, internal path/log/header, or unsafe JSON-LD |
| G11 REST/MCP/OpenAPI drift | examples disagree on packet names, routes, tool names, pricing, required fields |
| G12 forbidden claims | output says approved, eligible, safe, no risk, audit complete, tax correct, legal conclusion, creditworthy |
| G13 retention and cleanup | artifact cannot be deleted/exported under zero-bill requirement |
| G14 cost ledger | cost/usage artifacts cannot be tied to run/job/tag or unexpected spend appears |

Overall status:

- `pass`: all blocking gates pass.
- `partial`: no private leak/no-hit misuse/forbidden claim, but some review warnings remain.
- `fail`: any blocking issue exists.

### 12.2 Artifact-specific acceptance

| Artifact | Must pass |
|---|---|
| `source_profile_delta` | G01, G03, G04 |
| `source_receipts` | G01, G02, G04, G05 |
| `claim_refs` | G01, G02, G06 |
| `known_gaps` | G01 and known enum validation |
| `no_hit_checks` | G01, G02, G07 |
| `csv_private_overlay_report` | G01, G08 |
| `packet_example_json` | G01, G02, G06, G07, G08, G09, G12 |
| `proof_page_sidecar` | G01, G02, G07, G08, G10, G12 |
| `openapi_example` / `mcp_example` | G09, G11, G12 |
| `geo_eval_report` | G07, G08, G11, G12 |
| `cleanup_ledger` | G13 |
| `cost_ledger` | G14 |

## 13. Forbidden Content Scans

All public/importable artifacts must be scanned before repo import.

Forbidden professional claims:

- `approved`
- `eligible` when used as final eligibility
- `safe`
- `no risk`
- `audit complete`
- `tax correct`
- `legal conclusion`
- `creditworthy`
- Japanese equivalents: `採択される`, `申請可能と断定`, `問題なし`, `安全`, `リスクなし`, `監査完了`, `税務上正しい`, `法的に問題ない`, `与信可能`

Forbidden private values:

- raw CSV rows
- memo/free-text values
- counterparty/customer/vendor/employee names
- bank branch/account/card identifiers
- payroll detail
- personal identifiers
- API keys/tokens/secrets
- local filesystem paths when public
- request headers/auth headers

Forbidden no-hit transforms:

- no-hit -> absence
- no-hit -> safety
- no-hit -> registration failure/confirmed unregistering
- no-hit -> no enforcement history
- no-hit -> no legal/accounting/tax risk

## 14. Execution Order With Main Plan

This manifest contract should be inserted before AWS-F2 smoke run.

Recommended combined sequence:

1. P0 contract freeze: packet envelope, receipt fields, known-gap enum, CSV privacy rules, pricing metadata.
2. Manifest freeze: this document becomes the schema used by AWS wrappers.
3. Wrapper dry design: existing ingest/cron scripts emit artifact files, not production DB writes.
4. AWS-F0/F1 guardrails: billing, budgets, stop scripts, tags, empty stop drill.
5. AWS-F2 smoke run: one source profile, one receipt, one packet fixture, one proof sidecar, one scan.
6. Gate smoke artifacts with G01-G14.
7. AWS-F3 standard run: J01-J16 only where manifests pass.
8. AWS-F4 stretch run: only expand datasets that still produce accepted manifest rows.
9. AWS-F5 drain: export, verify `checksum_ledger.sha256`, generate import plan, generate cleanup ledger.
10. Repo import PRs: source profile/receipt/gap first, packet examples second, proof/discovery third, eval reports fourth.
11. Zero-bill cleanup: delete AWS artifacts/resources after export verification.

Do not launch a large AWS job until its expected output can be represented by this manifest.

## 15. Operator Checklist Before AWS Execution

Before executing AWS commands later:

- Confirm `run_manifest.json` template is filled with the intended account/profile/region.
- Confirm every planned job has an `artifact_kind` and `dataset_kind`.
- Confirm every source has source profile terms and license boundary.
- Confirm private CSV is excluded from public source foundation.
- Confirm no-hit wording is fixed and scanable.
- Confirm `checksum_ledger.sha256` generation is part of final packaging.
- Confirm `import_to_repo_plan.jsonl` and `cleanup_ledger.jsonl` are planned outputs.
- Confirm zero-bill cleanup can delete all AWS buckets/resources after export.

## 16. Final Recommendation

The AWS credit should be spent only on jobs that emit manifest-compliant durable artifacts. The shortest useful implementation dependency is:

```text
source_profile_delta
  -> source_document_manifest
  -> source_receipts / claim_refs / known_gaps / no_hit_checks
  -> packet_examples
  -> proof_page_sidecars
  -> GEO and forbidden-claim reports
  -> import_to_repo_plan
  -> cleanup_ledger
```

Anything outside this chain is either temporary compute waste or a future P1/P2 candidate. The manifest schema makes AWS output usable by jpcite P0 instead of becoming an unreviewable S3 dump.
