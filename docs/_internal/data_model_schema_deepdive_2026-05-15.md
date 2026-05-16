# Data model / schemas / DB contracts deep dive

Date: 2026-05-15

担当: Data model / schemas / DB contracts

Status: pre-implementation planning only. 実装コードは触らない。

Scope: P0 packet envelope, `source_receipts`, `known_gaps`, `billing_metadata`, `csv_intake_profile`, `normalized_journal_row`, public example packet, DB migration candidates, deterministic ID/hash contract.

## 1. 結論

P0 のデータ契約は、公開一次資料ベースの fact ledger と、ユーザー持ち込み CSV から作る private aggregate overlay を分離して設計する。両者は packet envelope 上では同じ `claims[]`, `source_receipts[]`, `known_gaps[]` に載るが、DB の永続境界と ID namespace は分ける。

推奨する初期境界:

- Public source fact: `source_catalog`, `source_document`, `extracted_fact`, `claim_source_link` 相当を SOT にする。
- Private CSV-derived fact: raw CSV と row-level normalized record は永続保存しない。`csv_intake_profile`, `csv_aggregate_fact`, `csv_review_fact` の aggregate-only に限定する。
- Packet: 保存が必要な paid/replay/export 対象のみ `packet_run` と `packet_claim` へ保存する。stateless packet は envelope を組み立てるだけでよい。
- Receipt: public receipt と private CSV receipt は同じ JSON shape を返せるが、`receipt_kind`, `fact_visibility`, `source_kind`, `license_boundary`, `tenant_scope` で明確に分ける。

## 2. JSON Schema candidates

### 2.1 `jpcite.packet_envelope.v1`

全 P0 packet の最外 envelope。既存 `packet_id`, `artifact_id`, `schema_version`, `corpus_snapshot_id` は alias として残し、canonical は `packet.*` とする。

Required:

- `packet.id`
- `packet.type`
- `packet.schema_version`
- `packet.generated_at`
- `packet.generator.request_time_llm_call_performed`
- `packet.corpus.snapshot_id`
- `summary`
- `records` または `sections`
- `claims`
- `source_receipts`
- `known_gaps`
- `quality`
- `billing_metadata`
- `fence`
- `versioning`

Candidate shape:

```json
{
  "$id": "https://jpcite.com/schemas/jpcite.packet_envelope.v1.json",
  "type": "object",
  "required": [
    "packet",
    "summary",
    "claims",
    "source_receipts",
    "known_gaps",
    "quality",
    "billing_metadata",
    "fence",
    "versioning"
  ],
  "properties": {
    "packet": {
      "type": "object",
      "required": ["id", "type", "schema_version", "api_version", "generated_at", "generator", "corpus"],
      "properties": {
        "id": {"type": "string", "pattern": "^(pkt|evp|art)_[a-z0-9_\\-]+$"},
        "kind": {"type": "string", "enum": ["evidence_packet", "artifact_packet", "handoff_packet", "batch_packet"]},
        "type": {"type": "string"},
        "schema_version": {"type": "string", "const": "jpcite.packet.v1"},
        "api_version": {"type": "string", "const": "v1"},
        "generated_at": {"type": "string", "format": "date-time"},
        "generator": {
          "type": "object",
          "required": ["service", "request_time_llm_call_performed"],
          "properties": {
            "service": {"type": "string", "const": "jpcite"},
            "endpoint": {"type": ["string", "null"]},
            "mcp_tool": {"type": ["string", "null"]},
            "request_time_llm_call_performed": {"type": "boolean", "const": false},
            "web_search_performed_by_jpcite": {"type": "boolean", "default": false}
          }
        },
        "corpus": {
          "type": "object",
          "required": ["snapshot_id"],
          "properties": {
            "snapshot_id": {"type": "string"},
            "checksum": {"type": ["string", "null"], "pattern": "^sha256:[0-9a-f]{64}$"}
          }
        }
      }
    },
    "input_echo": {"type": "object"},
    "summary": {"type": "object"},
    "sections": {"type": "array"},
    "records": {"type": "array"},
    "claims": {"type": "array", "items": {"$ref": "jpcite.claim_ref.v1.json"}},
    "source_receipts": {"type": "array", "items": {"$ref": "jpcite.source_receipt.v1.json"}},
    "known_gaps": {"type": "array", "items": {"$ref": "jpcite.known_gap.v1.json"}},
    "quality": {"$ref": "jpcite.quality.v1.json"},
    "billing_metadata": {"$ref": "jpcite.billing_metadata.v1.json"},
    "fence": {"$ref": "jpcite.fence.v1.json"},
    "versioning": {"$ref": "jpcite.versioning.v1.json"}
  }
}
```

### 2.2 `jpcite.source_receipt.v1`

Public source と private CSV-derived source の共通 receipt。違いは `receipt_kind`, `fact_visibility`, `source_kind`, `tenant_scope` で表す。

Required:

- `source_receipt_id`
- `receipt_kind`
- `source_kind`
- `fact_visibility`
- `support_level`
- `used_in`
- `claim_refs`

Audit-grade required when `receipt_kind=positive_source`:

- `source_url`
- `source_fetched_at` or `last_verified_at`
- `content_hash` or `source_checksum`
- `corpus_snapshot_id`
- `license_boundary`
- `verification_status`

Candidate enum:

```json
{
  "receipt_kind": [
    "positive_source",
    "no_hit_check",
    "private_csv_derived",
    "computed",
    "metadata_only"
  ],
  "source_kind": [
    "program",
    "houjin",
    "invoice",
    "law",
    "case",
    "bid",
    "public_statistic",
    "accounting_csv",
    "csv_derived",
    "computed"
  ],
  "fact_visibility": [
    "public_fact",
    "private_derived_fact",
    "private_aggregate_only",
    "metadata_only"
  ],
  "support_level": [
    "direct",
    "derived",
    "weak",
    "no_hit_not_absence"
  ],
  "license_boundary": [
    "full_fact",
    "derived_fact",
    "metadata_only",
    "link_only",
    "review_required",
    "unknown"
  ],
  "retrieval_method": [
    "scheduled_etl",
    "local_mirror",
    "api_mirror",
    "static_registry",
    "user_csv_derived",
    "computed"
  ],
  "verification_status": [
    "verified",
    "inferred",
    "stale",
    "no_hit",
    "unknown"
  ]
}
```

CSV-derived receipt must not expose raw file hash publicly unless scoped to the tenant. Use `source_file_profile_hash` or `intake_profile_id`, not `payload_hash` of private bytes.

### 2.3 `jpcite.claim_ref.v1`

AI が回答に再利用しうる最小 fact。source support がないものは `claims[]` に載せず `known_gaps[]` へ落とす。

Required:

- `claim_id`
- `claim_kind`
- `subject_kind`
- `subject_id`
- `field_name`
- `value_hash`
- `support_level`
- `source_receipt_ids`
- `visibility`

Candidate shape:

```json
{
  "claim_id": "claim_6b2f1c5f2a4e9b10",
  "claim_kind": "public_source_fact",
  "subject_kind": "program",
  "subject_id": "program:UNI-...",
  "field_name": "deadline",
  "claim_path": "records[0].facts[2]",
  "value_hash": "sha256:...",
  "support_level": "direct",
  "source_receipt_ids": ["sr_..."],
  "visibility": "public",
  "value_display_policy": "normalized_fact_allowed",
  "known_gaps": []
}
```

Allowed `claim_kind`:

- `public_source_fact`
- `public_no_hit_check`
- `private_csv_profile_fact`
- `private_csv_aggregate_fact`
- `computed_summary_fact`

Allowed `visibility`:

- `public`
- `tenant_private`
- `ephemeral_only`
- `redacted`

### 2.4 `jpcite.known_gap.v1`

Closed enum を中心に、agent instruction と human follow-up を機械可読にする。

Required:

- `gap_id`
- `gap_kind`
- `severity`
- `message`
- `agent_instruction`
- `blocks_final_answer`

Recommended extra fields:

- `affected_fields`
- `affected_records`
- `source_receipt_ids`
- `claim_refs`
- `missing_fields`
- `human_followup`

Canonical gap kinds are the union of GEO source receipt, CSV privacy, and packet P0 gaps. P0 では enum addition を minor-compatible とし、unknown enum は `unknown` として読ませる。

### 2.5 `jpcite.billing_metadata.v1`

P0 packet response に必ず含める課金ブロック。`usage_events` へ保存する billing decision とは別に、ユーザー/agent が読める説明用 metadata とする。

Required:

- `pricing_version`
- `pricing_model`
- `billable_unit_type`
- `billable_units`
- `jpy_ex_tax`
- `jpy_inc_tax`
- `metered`
- `cost_preview_required`
- `no_charge_for`

Candidate additions:

- `usage_event_id`: persisted packet の場合のみ nullable
- `idempotency_key_required`: paid POST/batch/CSV/export では true
- `billing_decision`: `billable|not_billable|preview_only|replay_no_charge|rejected_before_billable_work`
- `not_billed_reason`: validation/auth/quota/cap/server_error/csv_rejected など
- `external_costs_included=false`

### 2.6 `jpcite.csv_intake_profile.v1`

CSV raw を保存せず、取り込み形状だけを残す profile。外部 packet には `private_aggregate_only` として出す。

Required:

- `intake_profile_id`
- `tenant_scope_hash`
- `vendor_family`
- `encoding_detected`
- `row_count`
- `column_count`
- `column_profile_hash`
- `date_min`
- `date_max`
- `raw_retention`
- `privacy_posture`

Candidate shape:

```json
{
  "intake_profile_id": "csvp_...",
  "tenant_scope_hash": "tenant_hmac:...",
  "vendor_family": "freee|mf|yayoi|unknown",
  "encoding_detected": "utf-8-sig|cp932|utf-8|unknown",
  "row_count": 0,
  "column_count": 0,
  "column_profile_hash": "sha256:...",
  "date_min": "YYYY-MM-DD",
  "date_max": "YYYY-MM-DD",
  "period_months_hash": "sha256:...",
  "raw_retention": "none",
  "privacy_posture": {
    "raw_bytes_persisted": false,
    "row_level_records_persisted": false,
    "free_text_values_persisted": false,
    "counterparty_values_persisted": false,
    "small_cell_suppression_k": 3
  },
  "review_required": true,
  "review_reason_codes": []
}
```

`column_names` は内部保存可だが public example では redacted/synthetic に寄せる。実 CSV 由来の header が PII を含む場合は `header_redacted_count` のみ返す。

### 2.7 `jpcite.normalized_journal_row.v1`

行単位の一時正規化 record。P0 では schema は定義するが、永続保存禁止。DB table ではなく transient processor contract として扱う。

Required:

- `entry_id`
- `source_file_ephemeral_id`
- `row_index`
- `entry_date`
- `period_month`
- `debit_account`
- `credit_account`
- `debit_amount`
- `credit_amount`
- presence flags

Storage rule:

- `retention_scope=memory_only`
- `voucher_id_hash` は tenant-scoped HMAC のみ。public output には出さない。
- `memo`, `counterparty`, `created_by`, `updated_by`, free text は value を持たず presence/redaction count のみ。

### 2.8 `jpcite.csv_aggregate_fact.v1`

保存可能な CSV-derived fact。raw row を再構成できない粒度に丸める。

Required:

- `aggregate_fact_id`
- `intake_profile_id`
- `aggregation_level`
- `entry_count`
- `suppression_status`
- `review_required`

Allowed `aggregation_level`:

- `file`
- `month`
- `account`
- `account_month`
- `account_pair`
- `vendor_meta`
- `industry_signal`

Suppression:

- `entry_count < 3` は amount を非表示または上位 bucket へ coarsen。
- `account_original` は保存可。ただし rare/private-looking account label は redacted bucket にする。

### 2.9 `jpcite.public_example_packet.v1`

public proof page に載せる example packet。実顧客データ・実 private CSV hash を含めない synthetic 固定 fixture。

Required:

- `sample_input`
- `sample_output`
- `source_receipts`
- `known_gaps`
- `legal_fence`
- `cost_preview`
- `rest_call`
- `mcp_tool_name`

Rules:

- `packet.packet.generator.request_time_llm_call_performed=false` を明示。
- public source receipt は実 URL 可。ただし license boundary を付ける。
- CSV example は synthetic source only。`source_kind=accounting_csv`, `fact_visibility=private_aggregate_only` とし、raw value や row を出さない。

## 3. DB migration candidates

### 3.1 `291_geo_source_receipts_foundation.sql`

Purpose: public source receipt foundation。既存 `geo_source_receipts_data_foundation_spec_2026-05-15.md` の候補を採用する。

Table responsibilities:

- `source_catalog`: source profile registry。license boundary, refresh policy, citation policy の SOT。
- `source_document`: observed public document/API payload。content hash, checksum, freshness, retrieval method を持つ。
- `extracted_fact`: public corpus fact ledger。claim の元になる正規化 fact。
- `claim_source_link` 新設候補: one claim to many receipts の link table。`extracted_fact.source_document_id` だけでは複数 source support と no-hit check を表しにくい。

Recommended additive columns:

- `source_catalog.license_boundary`
- `source_catalog.profile_hash`
- `source_catalog.geo_exposure_allowed`
- `source_catalog.citation_policy_json`
- `source_document.source_id`
- `source_document.source_checksum`
- `source_document.freshness_bucket`
- `source_document.verification_status`
- `extracted_fact.claim_hash`
- `extracted_fact.visibility`
- `extracted_fact.source_support_status`

`claim_source_link` candidate:

```sql
CREATE TABLE claim_source_link (
  claim_id TEXT NOT NULL,
  source_receipt_id TEXT NOT NULL,
  fact_id TEXT,
  source_document_id TEXT,
  support_level TEXT NOT NULL,
  used_in_json TEXT NOT NULL DEFAULT '[]',
  claim_path TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (claim_id, source_receipt_id)
);
```

### 3.2 `292_packet_run_contract.sql`

Purpose: paid/replay/export 対象 packet の envelope metadata を保存する。全 stateless packet を保存する必要はない。

Table responsibilities:

- `packet_run`: request hash, packet id, schema version, subject, corpus snapshot, billing decision, response pointer。
- `packet_claim`: packet 内 claim index。support coverage と known gaps の検査に使う。
- `packet_receipt`: packet に添付された receipt の public projection。source ledger への link または private CSV aggregate link を持つ。
- `packet_known_gap`: packet-level structured gaps。

Candidate columns:

```text
packet_run(
  packet_id pk,
  packet_type,
  packet_schema_version,
  api_version,
  tenant_scope_hash nullable,
  endpoint,
  mcp_tool,
  normalized_request_hash,
  corpus_snapshot_id,
  corpus_checksum,
  generated_at,
  request_time_llm_call_performed default 0,
  response_body_hash,
  response_storage_uri nullable,
  billing_decision,
  usage_event_id nullable,
  idempotency_cache_id nullable,
  created_at
)
```

Boundary:

- `packet_run` must not store raw CSV payload or private row values.
- `response_storage_uri` only for paid artifacts/export where retention policy allows.
- Public example packet should be fixture-managed, not generated from production `packet_run`.

### 3.3 `293_private_csv_intake_aggregate.sql`

Purpose: private CSV-derived aggregate facts。raw CSV/row values are forbidden.

Table responsibilities:

- `csv_intake_profile`: file shape, vendor inference, column hash, period, privacy posture。
- `csv_aggregate_fact`: k-thresholded aggregate facts only。
- `csv_review_fact`: future dates, parse failures, balance differences, mapping uncertainty 等の data quality facts。
- `csv_intake_rejection`: rejected files with reason code and shape only。

Candidate tables:

```text
csv_intake_profile(
  intake_profile_id pk,
  tenant_scope_hash not null,
  upload_session_hash nullable,
  vendor_family,
  encoding_detected,
  row_count,
  column_count,
  column_profile_hash,
  date_min,
  date_max,
  period_month_count,
  raw_retention default 'none',
  privacy_flags_json,
  review_required,
  review_reason_codes_json,
  created_at,
  expires_at nullable
)
```

```text
csv_aggregate_fact(
  aggregate_fact_id pk,
  intake_profile_id,
  tenant_scope_hash not null,
  aggregation_level,
  period_month nullable,
  account_label_hash nullable,
  account_original_redacted nullable,
  account_light_class,
  entry_count,
  debit_amount_sum nullable,
  credit_amount_sum nullable,
  tax_amount_sum nullable,
  distinct_subaccount_count nullable,
  distinct_department_count nullable,
  first_date nullable,
  last_date nullable,
  suppression_status,
  confidence,
  review_required,
  review_reasons_json,
  created_at
)
```

```text
csv_review_fact(
  review_fact_id pk,
  intake_profile_id,
  tenant_scope_hash not null,
  condition_code,
  severity,
  observed_count,
  observed_scope,
  affected_bucket_hash nullable,
  human_message_ja,
  not_a_tax_or_accounting_opinion default 1,
  created_at
)
```

Forbidden columns:

- raw bytes
- raw row JSON
- memo/free-text values
- counterparty values
- voucher ID value
- creator/updater name
- bank/payroll/person identifiers

### 3.4 `294_packet_schema_registry.sql`

Purpose: schema publication and backwards compatibility guard。

Table responsibilities:

- `packet_schema_registry`: schema id, semantic version, JSON Schema hash, status。
- `packet_schema_compatibility`: reader/writer compatibility matrix。
- `packet_schema_deprecation`: legacy alias deprecation schedule。

This can be postponed if schemas live as files first, but DB registry helps `/v1/meta/packet-schemas` and public example validation.

### 3.5 `295_usage_packet_billing_bridge.sql`

Purpose: `billing_metadata` と durable usage/billing rows の bridge。既存 `usage_events` を SOT とし、packet-specific explanation を別 table にする。

Table responsibilities:

- `packet_billing_decision`: packet id, estimate id, billable units, no-charge reason, cap result。
- Existing `usage_events`: actual metered event SOT。二重課金防止は idempotency cache と usage event idempotency で担保。

Candidate columns:

```text
packet_billing_decision(
  packet_id pk,
  tenant_scope_hash nullable,
  pricing_version,
  pricing_model,
  billable_unit_type,
  billable_units,
  unit_price_ex_tax_jpy,
  jpy_ex_tax,
  jpy_inc_tax,
  metered,
  billing_decision,
  not_billed_reason nullable,
  cost_preview_required,
  estimate_id nullable,
  usage_event_id nullable,
  cap_json,
  no_charge_for_json,
  created_at
)
```

## 4. Public source fact vs private CSV-derived fact

### 4.1 Public source fact

Definition:

- Official/public source に由来し、source profile と source document で再検証可能な fact。
- Public packet, public example, proof page, agent-facing citations に出せる。

Storage:

- `source_catalog`
- `source_document`
- `extracted_fact`
- `claim_source_link`

Receipt:

- `receipt_kind=positive_source`
- `fact_visibility=public_fact`
- `license_boundary=full_fact|derived_fact|metadata_only|link_only`
- `source_url` is normally present

Allowed output:

- source URL
- publisher/owner
- fetched/verified timestamps
- normalized facts allowed by license boundary
- short quote-safe summary only if license permits

### 4.2 Private CSV-derived fact

Definition:

- User-provided accounting CSV から transient parse/normalize して作る aggregate-only fact。
- Public corpus には入れない。Source foundation の `source_document` に private CSV を保存しない。

Storage:

- `csv_intake_profile`
- `csv_aggregate_fact`
- `csv_review_fact`
- optional `packet_run` private pointer

Receipt:

- `receipt_kind=private_csv_derived`
- `source_kind=accounting_csv|csv_derived`
- `fact_visibility=private_aggregate_only`
- `retrieval_method=user_csv_derived`
- `license_boundary=review_required`
- `tenant_scope_hash` required

Allowed output:

- vendor family
- row/column counts
- date range
- column profile hash
- monthly/account aggregate with k-threshold
- review condition codes
- privacy posture

Forbidden output:

- raw CSV bytes
- normalized row values
- memo/free text
- counterparty
- voucher id value
- creator/updater names
- bank/payroll/person identifiers
- rare cells that reconstruct individual transactions

### 4.3 Join policy

Public source facts and private CSV-derived facts may be joined only at packet composition time, not in the public fact ledger.

Allowed joins:

- tenant-private packet compares CSV aggregate industry signals to public program categories.
- company public baseline can coexist with CSV intake profile when exact corporate ID is supplied by user.

Review-required joins:

- name-only company/counterparty matching.
- CSV account vocabulary to public subsidy eligibility.
- any tax/accounting/legal interpretation based on CSV data.

Forbidden joins:

- counterparty names from CSV to public corporate records.
- raw memo/free text to public source search.
- private row-level journal facts into public search index.

## 5. Deterministic ID and hash design

### 5.1 Canonicalization

Use one canonicalization contract across schemas:

- Text: Unicode NFKC, normalize newlines to `\n`, trim, collapse spaces/tabs, no translation before hashing.
- JSON: UTF-8, sorted keys, no insignificant whitespace, drop volatile fields.
- URL: lowercase scheme/host, remove default ports and fragment, preserve meaningful query params.
- Date/time: ISO 8601 UTC for DB; packet may display JST but hash input uses UTC unless field is a business-local date.

Volatile fields excluded from request/content hashes:

- `generated_at`
- `request_id`
- `trace_id`
- `source_fetched_at`
- `last_verified_at`
- `billing_metadata`
- `quality.coverage_score` if computed from current corpus health

### 5.2 ID formulas

`packet_id`:

```text
pkt_ + base32_16(sha256(
  packet_type + "\x1f" +
  normalized_request_hash + "\x1f" +
  corpus_snapshot_id + "\x1f" +
  schema_version
))
```

For paid replay where duplicate requests must return the same result, include idempotency cache id or existing packet id mapping instead of generating a new random id.

`source_receipt_id` for public source:

```text
sr_ + sha256(
  receipt_kind + "\x1f" +
  source_id + "\x1f" +
  canonical_source_url + "\x1f" +
  source_checksum + "\x1f" +
  corpus_snapshot_id
)[0:16]
```

`source_receipt_id` for CSV-derived private fact:

```text
sr_csv_ + sha256(
  tenant_scope_hash + "\x1f" +
  intake_profile_id + "\x1f" +
  aggregate_fact_id + "\x1f" +
  schema_version
)[0:16]
```

`claim_id`:

```text
claim_ + sha256(
  visibility + "\x1f" +
  subject_kind + "\x1f" +
  subject_id + "\x1f" +
  field_name + "\x1f" +
  canonical_value_hash + "\x1f" +
  corpus_snapshot_id_or_intake_profile_id
)[0:16]
```

`csv_intake_profile_id`:

```text
csvp_ + sha256(
  tenant_scope_hash + "\x1f" +
  upload_session_hash + "\x1f" +
  column_profile_hash + "\x1f" +
  row_count + "\x1f" +
  date_min + "\x1f" +
  date_max
)[0:16]
```

Do not use unsalted raw file hash as public ID for private CSV. Use tenant-scoped HMAC where dedupe is needed.

`normalized_journal_row.entry_id`:

```text
entry_tmp_ + hmac_sha256(
  tenant_secret,
  intake_profile_id + "\x1f" +
  row_index + "\x1f" +
  entry_date + "\x1f" +
  debit_account_hash + "\x1f" +
  credit_account_hash + "\x1f" +
  debit_amount + "\x1f" +
  credit_amount
)[0:16]
```

This is transient only and must not be exposed in public examples.

### 5.3 Hash fields

Public:

- `profile_hash`: hash of source profile row.
- `content_hash`: hash of normalized public source content.
- `source_checksum`: public receipt checksum, usually alias to `content_hash`.
- `claim_hash`: hash of normalized public claim value.
- `response_body_hash`: hash of packet envelope after removing volatile fields.

Private:

- `tenant_scope_hash`: HMAC or salted hash of tenant/key id.
- `column_profile_hash`: hash of normalized header names after redaction rules.
- `voucher_id_hash`: HMAC only, never public.
- `account_label_hash`: HMAC or normalized hash if private vocabulary risk exists.
- `aggregate_fact_hash`: hash/HMAC over aggregate bucket and values.

Never expose:

- raw CSV byte hash
- memo/counterparty hash
- payroll/bank/person identifier hash
- unsalted hashes of private free text

## 6. Schema versioning and backwards compatibility

### 6.1 Version axes

Use four independent versions:

- `packet.api_version`: public API major, initial `v1`.
- `packet.schema_version`: envelope schema id, initial `jpcite.packet.v1`.
- `packet.packet_version`: packet family release date, e.g. `2026-05-15`.
- `source_profile.profile_version` / `pricing_version`: domain data contract dates.

Do not overload `api_version` to express packet JSON shape changes.

### 6.2 Compatibility rules

Minor-compatible changes:

- Add optional field.
- Add enum value if readers treat unknown as `unknown`.
- Add new `known_gap` code.
- Add new packet type to catalog.
- Add new `source_kind` or `aggregation_level` with fallback.

Breaking changes requiring new schema major:

- Remove required field.
- Change field type.
- Change ID/hash formula for existing IDs without alias.
- Change support semantics of `no_hit_not_absence`.
- Move private CSV-derived facts into public source tables.
- Make `request_time_llm_call_performed` optional or true for P0 packet.

### 6.3 Legacy aliases

Keep through API v1:

| Legacy | Canonical |
|---|---|
| `packet_id` | `packet.id` |
| `artifact_id` | `packet.id` plus retained `artifact_id` |
| `packet_type` / `artifact_type` | `packet.type` |
| `schema_version` | `packet.schema_version` |
| `api_version` | `packet.api_version` |
| `generated_at` | `packet.generated_at` |
| `corpus_snapshot_id` | `packet.corpus.snapshot_id` |
| `corpus_checksum` | `packet.corpus.checksum` |
| top-level `known_gaps` | canonical `known_gaps[]` and `quality.known_gaps[]` |
| `_disclaimer` | `fence` |
| `jpcite_cost_jpy` | `billing_metadata.jpy_ex_tax` or `metrics.jpcite_cost_jpy` |

### 6.4 Reader contract

Agents and client SDKs should:

- Ignore unknown fields.
- Treat unknown enum values as `unknown` and inspect `known_gaps`.
- Require every externally stated claim to have `source_receipt_ids[]` or a blocking/review `known_gap`.
- Never treat no-hit as absence.
- Preserve `source_url`, `source_fetched_at`, `content_hash`, `license_boundary`, `known_gaps`, `billing_metadata`, and `fence` when summarizing.

## 7. Public example packet contract

Public example packets must validate against the same schemas but use synthetic or public-safe data.

Minimum fixture set:

- `examples/packets/evidence_answer.public.json`
- `examples/packets/company_public_baseline.public.json`
- `examples/packets/client_monthly_review_csv.synthetic.json`

Each fixture must include:

- sample input
- sample output JSON
- at least one complete public `source_receipt`
- at least one `known_gap`
- legal/tax/application fence
- `billing_metadata`
- REST call
- MCP tool name
- `request_time_llm_call_performed=false`

CSV example requirements:

- synthetic CSV profile only.
- `fact_visibility=private_aggregate_only`.
- no row-level entries.
- `known_gaps` includes `private_input_unverified` or `csv_mapping_required` when applicable.

## 8. Open decisions before implementation

1. Whether `packet_run` stores full response JSON or only a content-addressed pointer. Recommendation: pointer or hash by default, full body only for paid export artifacts with retention policy.
2. Whether `claim_source_link` is a physical table in P0 or derived from `extracted_fact` plus packet composition. Recommendation: physical table if source receipt ledger is a P0 packet.
3. Whether `csv_intake_profile.column_names` is stored as redacted JSON or only hash/counts. Recommendation: store redacted names only after header PII scan; otherwise hash/counts.
4. Whether `packet.schema_version` should be `jpcite.packet.v1` or semver `1.1`. Recommendation: expose both: schema id for validation, `versioning.schema_semver` for compatibility.
5. Whether public examples live in docs only or are validation fixtures. Recommendation: validation fixtures first, docs render from fixture.

## 9. P0 acceptance checks

- Every P0 packet has `packet`, `claims`, `source_receipts`, `known_gaps`, `quality`, `billing_metadata`, `fence`, `versioning`.
- `request_time_llm_call_performed=false` is enforced.
- Every non-gap claim has at least one source receipt.
- Incomplete receipts emit `source_receipt_missing_fields`.
- `no_hit` only appears as `no_hit_not_absence` support plus known gap.
- Private CSV raw bytes and normalized rows are not persisted.
- CSV-derived packet facts use `private_aggregate_only`.
- Deterministic IDs are stable across identical normalized input and corpus/intake snapshot.
- Public example packets validate against schemas and contain no private-derived raw values.
