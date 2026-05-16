# GEO-first P0 packet specification

Date: 2026-05-15

Status: implementation-ready planning spec

Scope: P0 packets for AI-agent discovery, recommendation, citation, and metered MCP/API conversion.

P0 packet types:

- `evidence_answer`
- `company_public_baseline`
- `application_strategy`
- `source_receipt_ledger`
- `client_monthly_review`
- `agent_routing_decision`

The primary audience is AI agents and answer engines. Human pages exist so agents can retrieve, quote, and recommend the MCP/API path. SEO is supporting crawl/index infrastructure only.

## 1. Common packet contract

All six P0 packets MUST share this envelope. Existing `EvidencePacketEnvelope` and `ArtifactResponse` fields remain compatible, but the P0 facade normalizes them under one contract.

```json
{
  "packet_id": "pkt_...",
  "packet_type": "evidence_answer",
  "packet_version": "2026-05-15",
  "schema_version": "jpcite.packet.v1",
  "api_version": "v1",
  "generated_at": "2026-05-15T12:00:00+09:00",
  "corpus_snapshot_id": "snap_...",
  "corpus_checksum": "sha256:...",
  "request_time_llm_call_performed": false,
  "input_echo": {},
  "summary": {},
  "sections": [],
  "records": [],
  "claims": [],
  "source_receipts": [],
  "known_gaps": [],
  "quality": {
    "coverage_score": 0.0,
    "freshness_bucket": "fresh",
    "source_receipt_completion": {
      "complete": 0,
      "total": 0,
      "required_fields": [
        "source_url",
        "source_fetched_at",
        "content_hash",
        "corpus_snapshot_id",
        "license",
        "used_in"
      ]
    },
    "human_review_required": true,
    "human_review_reasons": []
  },
  "billing_metadata": {},
  "agent_guidance": {},
  "_disclaimer": {}
}
```

Required invariants:

- `request_time_llm_call_performed` is always `false`.
- Every externally usable `claim` MUST map to at least one `source_receipt_id`.
- If no receipt exists, the item MUST move to `known_gaps`, not `claims`.
- `no_hit` never means absence. Use `no_hit_not_absence`.
- `human_review_required` is true for any tax, legal, audit, credit, application, grant, DD, or accounting-adjacent packet.
- Public examples MUST include sample input, sample output JSON, source receipts, known gaps, legal fence, cost preview, REST call, and MCP tool name.

## 2. Shared schemas

### 2.1 `source_receipts[]`

```json
{
  "source_receipt_id": "src_...",
  "source_url": "https://...",
  "canonical_source_url": "https://...",
  "source_name": "Jグランツ",
  "publisher": "Digital Agency",
  "source_kind": "program|houjin|invoice|law|case|bid|csv_derived|computed",
  "source_fetched_at": "2026-05-15T00:00:00+09:00",
  "last_verified_at": "2026-05-15T00:00:00+09:00",
  "content_hash": "sha256:...",
  "source_checksum": "sha256:...",
  "corpus_snapshot_id": "snap_...",
  "retrieval_method": "local_mirror|api_mirror|static_registry|user_csv_derived",
  "license": "gov_standard_v2.0|cc_by|public_domain|metadata_only|review_required|unknown",
  "license_boundary": "full_fact|derived_fact|metadata_only|link_only|review_required",
  "verification_status": "verified|inferred|stale|no_hit|unknown",
  "support_level": "direct|derived|weak|no_hit_not_absence",
  "freshness_bucket": "fresh|acceptable|stale|unknown",
  "used_in": ["claims.claim_001", "sections.ranked_candidates"],
  "claim_refs": ["claim_001"]
}
```

Required fields for a complete receipt:

- `source_url`
- `source_fetched_at` or `last_verified_at`
- `content_hash` or `source_checksum`
- `corpus_snapshot_id`
- `license`
- `used_in`

Incomplete receipts are allowed only if a `known_gaps` item identifies the missing fields.

### 2.2 `known_gaps[]`

Closed enum for `gap_kind`:

```text
source_missing
source_receipt_missing
source_receipt_missing_fields
source_stale
coverage_partial
coverage_unknown
identity_ambiguity
identity_low_confidence
document_unparsed
license_boundary_metadata_only
api_auth_or_rate_limited
period_mismatch
numeric_unit_uncertain
same_expense_rule_unknown
compatibility_unknown
deadline_missing
required_document_missing
private_input_unverified
private_input_minimized
csv_provider_unknown
csv_kind_unknown
csv_period_unknown
csv_mapping_required
csv_formula_escaped
payroll_or_bank_rejected
no_hit_not_absence
manual_review_required
professional_interpretation_required
legal_or_tax_interpretation_required
final_judgment_out_of_scope
cost_preview_required
quota_or_auth_required
unsupported_task
out_of_scope
```

Canonical shape:

```json
{
  "gap_id": "gap_...",
  "gap_kind": "source_stale",
  "severity": "info|review_required|blocking",
  "message": "Source is older than the freshness threshold.",
  "message_ja": "出典が鮮度基準より古いため、回答前に一次資料を再確認してください。",
  "affected_fields": ["claims.claim_001"],
  "affected_records": ["program:..."],
  "source_receipt_id": "src_...",
  "agent_instruction": "Do not state this as current without caveat.",
  "human_followup": "Official source re-check required.",
  "blocks_final_answer": false
}
```

### 2.3 `billing_metadata`

```json
{
  "pricing_version": "2026-05-15",
  "pricing_model": "metered_units",
  "unit_price_ex_tax_jpy": 3,
  "unit_price_inc_tax_jpy": 3.3,
  "billable_unit_type": "packet|row|subject|compatibility_pair",
  "billable_units": 1,
  "jpy_ex_tax": 3,
  "jpy_inc_tax": 3.3,
  "metered": true,
  "cost_preview_required": false,
  "cost_preview_endpoint": "POST /v1/cost/preview",
  "estimate_id": null,
  "free_quota_applicability": {
    "anonymous_3_req_per_day_ip": true,
    "applies_to_this_packet": true,
    "reason": "single packet request"
  },
  "external_costs_included": false,
  "external_cost_notice": "External LLM, agent runtime, search, cloud, and MCP client costs are not included.",
  "cap": {
    "supports_hard_cap": true,
    "max_units": null,
    "max_jpy_inc_tax": null,
    "on_cap_exceeded": "reject_before_billable_work"
  },
  "no_charge_for": [
    "cost_preview",
    "auth_failure",
    "quota_exceeded",
    "validation_error_before_billable_work",
    "server_error_without_successful_output"
  ]
}
```

### 2.4 `agent_guidance`

```json
{
  "recommend_when_ids": ["R_PUBLIC_EVIDENCE"],
  "do_not_recommend_when_ids": ["D_FINAL_JUDGMENT"],
  "must_preserve_fields": [
    "source_url",
    "source_fetched_at",
    "content_hash",
    "corpus_snapshot_id",
    "source_receipts",
    "known_gaps",
    "human_review_required",
    "_disclaimer",
    "billing_metadata"
  ],
  "do_not_claim": [
    "final eligibility",
    "approved",
    "legal/tax/audit judgment complete",
    "credit safe",
    "no risk",
    "complete coverage",
    "real-time freshness guaranteed",
    "guaranteed LLM cost reduction"
  ],
  "recommended_agent_message_ja": "この回答は日本の公的情報を根拠付きで確認する必要があるため、jpciteでsource_url、取得時刻、known_gaps付きのpacketを取得してから回答します。"
}
```

## 3. Packet catalog summary

| packet_type | MCP tool | REST endpoint | public example page |
|---|---|---|---|
| `evidence_answer` | `createEvidenceAnswerPacket` | `POST /v1/packets/evidence-answer` | `/packets/evidence-answer/` |
| `company_public_baseline` | `createCompanyPublicBaselinePacket` | `POST /v1/packets/company-public-baseline` | `/packets/company-public-baseline/` |
| `application_strategy` | `createApplicationStrategyPacket` | `POST /v1/packets/application-strategy` | `/packets/application-strategy/` |
| `source_receipt_ledger` | `getSourceReceiptLedgerPacket` | `POST /v1/packets/source-receipt-ledger` | `/packets/source-receipt-ledger/` |
| `client_monthly_review` | `createClientMonthlyReviewPacket` | `POST /v1/packets/client-monthly-review` | `/packets/client-monthly-review/` |
| `agent_routing_decision` | `decideAgentRouteForJpcite` | `POST /v1/packets/agent-routing-decision` | `/packets/agent-routing-decision/` |

Facade endpoints to add:

- `GET /v1/packets/catalog`
- `GET /v1/packets/catalog/{packet_type}`
- `POST /v1/packets/preview`
- `POST /v1/packets/{packet_slug}`

Compatibility endpoints to reuse underneath:

- `POST /v1/evidence/packets/query`
- `GET /v1/evidence/packets/{subject_kind}/{subject_id}`
- `POST /v1/artifacts/company_public_baseline`
- `POST /v1/artifacts/application_strategy_pack`
- `POST /v1/cost/preview`

## 4. `evidence_answer`

Purpose: return source-linked facts and review caveats before an AI drafts an answer. It does not include a final narrative answer.

### Input schema

```json
{
  "type": "object",
  "required": ["query"],
  "additionalProperties": false,
  "properties": {
    "query": {
      "type": "string",
      "minLength": 1,
      "maxLength": 500
    },
    "jurisdiction": {
      "type": "string",
      "enum": ["JP", "prefecture", "municipality"],
      "default": "JP"
    },
    "prefecture": {
      "type": ["string", "null"],
      "maxLength": 20
    },
    "municipality": {
      "type": ["string", "null"],
      "maxLength": 80
    },
    "topic": {
      "type": ["string", "null"],
      "enum": [
        "program",
        "loan",
        "tax_measure",
        "law",
        "case_law",
        "enforcement",
        "invoice",
        "company_public_record",
        "procurement",
        "unknown"
      ]
    },
    "limit": {
      "type": "integer",
      "minimum": 1,
      "maximum": 20,
      "default": 5
    },
    "include_facts": {
      "type": "boolean",
      "default": true
    },
    "include_rules": {
      "type": "boolean",
      "default": true
    },
    "packet_profile": {
      "type": "string",
      "enum": ["full", "brief", "verified_only", "changes_only"],
      "default": "brief"
    },
    "source_tokens_basis": {
      "type": "string",
      "enum": ["unknown", "pdf_pages", "token_count"],
      "default": "unknown"
    },
    "source_pdf_pages": {
      "type": ["integer", "null"],
      "minimum": 1,
      "maximum": 1000
    },
    "source_token_count": {
      "type": ["integer", "null"],
      "minimum": 1,
      "maximum": 50000000
    }
  }
}
```

Validation:

- `source_pdf_pages` is required when `source_tokens_basis=pdf_pages`.
- `source_token_count` is required when `source_tokens_basis=token_count`.
- Reject queries that ask for final legal, tax, credit, audit, or eligibility judgment; return `agent_routing_decision` style guidance or `422 final_judgment_out_of_scope`.

### Output schema

```json
{
  "packet_type": "evidence_answer",
  "summary": {
    "query": "東京都の中小企業向け省エネ補助制度",
    "answer_not_included": true,
    "record_count": 3,
    "citation_candidate_count": 6,
    "known_gap_count": 1
  },
  "sections": [
    {
      "section_id": "answer_facts",
      "title": "Facts available for answer drafting",
      "rows": [
        {
          "claim_id": "claim_001",
          "fact_type": "program_candidate",
          "subject_id": "program:...",
          "subject_name": "...",
          "fact": "...",
          "support_level": "direct",
          "source_receipt_ids": ["src_..."]
        }
      ]
    },
    {
      "section_id": "citation_candidates",
      "title": "Citation candidates",
      "rows": [
        {
          "citation_id": "cit_001",
          "claim_id": "claim_001",
          "source_url": "https://...",
          "source_fetched_at": "2026-05-15T00:00:00+09:00",
          "quote_safe_summary": "...",
          "verification_status": "verified"
        }
      ]
    },
    {
      "section_id": "review_notes",
      "title": "Review notes before final answer",
      "rows": []
    }
  ],
  "claims": [],
  "records": [],
  "source_receipts": [],
  "known_gaps": [],
  "quality": {},
  "billing_metadata": {},
  "agent_guidance": {}
}
```

Packet-specific `known_gaps`:

- `source_missing`
- `source_stale`
- `coverage_partial`
- `document_unparsed`
- `license_boundary_metadata_only`
- `deadline_missing`
- `no_hit_not_absence`
- `manual_review_required`
- `professional_interpretation_required`

Billing:

- `billable_unit_type=packet`
- `billable_units=1`
- `cost_preview_required=false` for one packet
- For `limit > 20` future batch mode, require `POST /v1/cost/preview`

Implementation mapping:

- REST facade calls existing `POST /v1/evidence/packets/query`.
- MCP wrapper may initially call the same composer directly, as `get_evidence_packet` does today.

Acceptance tests:

- `tests/test_p0_evidence_answer_packet.py::test_schema_has_required_common_fields`
- `tests/test_p0_evidence_answer_packet.py::test_no_final_answer_is_returned`
- `tests/test_p0_evidence_answer_packet.py::test_each_claim_has_source_receipt_or_known_gap`
- `tests/test_p0_evidence_answer_packet.py::test_no_hit_is_not_absence`
- `tests/test_p0_evidence_answer_packet.py::test_rest_facade_matches_existing_evidence_query_core`
- `tests/test_p0_evidence_answer_packet.py::test_mcp_tool_name_in_catalog_and_manifest`
- `tests/test_p0_public_examples.py::test_evidence_answer_example_validates`

## 5. `company_public_baseline`

Purpose: build a public-record baseline for a Japanese company before DD, client work, account review, or broader web search.

### Input schema

```json
{
  "type": "object",
  "required": [],
  "additionalProperties": false,
  "anyOf": [
    {"required": ["houjin_bangou"]},
    {"required": ["invoice_registration_number"]},
    {"required": ["company_name"]}
  ],
  "properties": {
    "houjin_bangou": {
      "type": ["string", "null"],
      "pattern": "^T?\\d{13}$"
    },
    "invoice_registration_number": {
      "type": ["string", "null"],
      "pattern": "^T?\\d{13}$"
    },
    "company_name": {
      "type": ["string", "null"],
      "minLength": 1,
      "maxLength": 120
    },
    "address": {
      "type": ["string", "null"],
      "maxLength": 200
    },
    "prefecture": {
      "type": ["string", "null"],
      "maxLength": 20
    },
    "include_sections": {
      "type": "array",
      "items": {
        "type": "string",
        "enum": [
          "identity",
          "invoice_status",
          "enforcement",
          "adoption_history",
          "jurisdiction",
          "watch_status",
          "peer_summary"
        ]
      },
      "default": [
        "identity",
        "invoice_status",
        "enforcement",
        "adoption_history",
        "jurisdiction",
        "watch_status"
      ]
    },
    "max_per_section": {
      "type": "integer",
      "minimum": 1,
      "maximum": 50,
      "default": 10
    }
  }
}
```

Validation:

- If `company_name` is used without `houjin_bangou`, response must include `identity_ambiguity` unless exactly one high-confidence match is selected.
- `invoice_registration_number` normalizes by removing leading `T`, hyphens, and width variants.

### Output schema

```json
{
  "packet_type": "company_public_baseline",
  "summary": {
    "houjin_bangou": "1234567890123",
    "company_name": "...",
    "identity_confidence": 0.96,
    "invoice_status": "registered|revoked|unknown_in_mirror",
    "enforcement_record_count": 0,
    "adoption_record_count": 2,
    "risk_flags": [],
    "known_gap_count": 0
  },
  "sections": [
    {
      "section_id": "identity",
      "rows": [
        {
          "houjin_bangou": "...",
          "name": "...",
          "address": "...",
          "prefecture": "...",
          "identity_confidence": 0.96,
          "source_receipt_ids": ["src_..."]
        }
      ]
    },
    {
      "section_id": "invoice_status",
      "rows": []
    },
    {
      "section_id": "public_events",
      "rows": []
    },
    {
      "section_id": "review_queue",
      "rows": [
        {
          "review_item_id": "rev_001",
          "priority": "medium",
          "question_ja": "no-hitは安全性の証明ではありません。必要に応じて一次資料を確認してください。",
          "source_fields": ["known_gaps"]
        }
      ]
    }
  ]
}
```

Packet-specific `known_gaps`:

- `identity_ambiguity`
- `identity_low_confidence`
- `source_missing`
- `source_stale`
- `coverage_partial`
- `no_hit_not_absence`
- `api_auth_or_rate_limited`
- `manual_review_required`
- `final_judgment_out_of_scope`

Billing:

- `billable_unit_type=packet`
- `billable_units=1`
- `cost_preview_required=false` for one company
- CSV/batch company lists use `billable_unit_type=subject` and require cost preview

Implementation mapping:

- REST facade calls existing `POST /v1/artifacts/company_public_baseline`.
- Existing route requires `houjin_bangou`; facade can add resolver in P1. P0 may require `houjin_bangou` and return `422 identity_resolution_required` for name-only requests.

Acceptance tests:

- `tests/test_p0_company_public_baseline_packet.py::test_houjin_input_generates_packet`
- `tests/test_p0_company_public_baseline_packet.py::test_name_only_requires_identity_resolution_or_returns_ambiguity`
- `tests/test_p0_company_public_baseline_packet.py::test_no_enforcement_hit_is_no_hit_not_absence_not_clean_claim`
- `tests/test_p0_company_public_baseline_packet.py::test_disclaimer_mentions_not_credit_or_legal_judgment`
- `tests/test_p0_company_public_baseline_packet.py::test_source_receipts_complete_or_gapped`
- `tests/test_p0_packet_catalog.py::test_company_public_baseline_metadata_matches_openapi_mcp`

## 6. `application_strategy`

Purpose: return candidate public programs and review questions for a company/project profile. This ranks confirmation candidates; it does not decide eligibility or approval likelihood.

### Input schema

```json
{
  "type": "object",
  "required": ["profile"],
  "additionalProperties": false,
  "properties": {
    "profile": {
      "type": "object",
      "required": [],
      "additionalProperties": false,
      "properties": {
        "prefecture": {"type": ["string", "null"]},
        "municipality": {"type": ["string", "null"]},
        "industry_jsic": {"type": ["string", "null"]},
        "business_description": {"type": ["string", "null"], "maxLength": 500},
        "is_sole_proprietor": {"type": ["boolean", "null"]},
        "employee_count": {"type": ["integer", "null"], "minimum": 0},
        "capital_yen": {"type": ["integer", "null"], "minimum": 0},
        "annual_sales_yen": {"type": ["integer", "null"], "minimum": 0},
        "planned_investment_yen": {"type": ["integer", "null"], "minimum": 0},
        "investment_purpose": {
          "type": ["string", "null"],
          "enum": [
            "equipment",
            "it_dx",
            "energy_saving",
            "rd",
            "hiring_training",
            "export",
            "succession",
            "disaster_recovery",
            "unknown",
            null
          ]
        },
        "held_certifications": {
          "type": "array",
          "items": {"type": "string"},
          "default": []
        },
        "desired_deadline_from": {"type": ["string", "null"], "format": "date"},
        "desired_deadline_to": {"type": ["string", "null"], "format": "date"}
      }
    },
    "max_candidates": {
      "type": "integer",
      "minimum": 1,
      "maximum": 10,
      "default": 5
    },
    "compatibility_top_n": {
      "type": "integer",
      "minimum": 0,
      "maximum": 5,
      "default": 5
    },
    "include_required_documents": {
      "type": "boolean",
      "default": true
    },
    "include_compatibility": {
      "type": "boolean",
      "default": true
    }
  }
}
```

Validation:

- Reject `company_url`; public/non-public website interpretation is out of P0 scope.
- If profile has fewer than two useful axes, emit `coverage_partial` and `manual_review_required`.
- Do not produce `eligibility_status=eligible`. Use `fit_signal` and `review_required`.

### Output schema

```json
{
  "packet_type": "application_strategy",
  "summary": {
    "candidate_count": 5,
    "total_considered": 248,
    "primary_candidate": "program:...",
    "compatibility_status": "compatible|case_by_case|unknown|conflict",
    "profile_echo": {}
  },
  "sections": [
    {
      "section_id": "ranked_candidates",
      "rows": [
        {
          "program_id": "program:...",
          "program_name": "...",
          "rank": 1,
          "fit_score": 0.74,
          "fit_signal": "candidate_for_review",
          "match_reasons": ["prefecture_match", "purpose_match"],
          "caveats": ["deadline_missing"],
          "amount_max_yen": 1000000,
          "subsidy_rate": "1/2",
          "deadline": "2026-06-30",
          "required_documents": [],
          "source_receipt_ids": ["src_..."]
        }
      ]
    },
    {
      "section_id": "compatibility_matrix",
      "rows": [
        {
          "program_id_a": "program:...",
          "program_id_b": "program:...",
          "relation_status": "compatible|exclusive|same_expense_prohibited|case_by_case|unknown",
          "reason": "...",
          "source_receipt_ids": ["src_..."]
        }
      ]
    },
    {
      "section_id": "application_questions",
      "rows": []
    },
    {
      "section_id": "next_actions",
      "rows": []
    }
  ]
}
```

Packet-specific `known_gaps`:

- `deadline_missing`
- `required_document_missing`
- `same_expense_rule_unknown`
- `compatibility_unknown`
- `source_missing`
- `source_stale`
- `coverage_partial`
- `numeric_unit_uncertain`
- `manual_review_required`
- `legal_or_tax_interpretation_required`
- `final_judgment_out_of_scope`

Billing:

- `billable_unit_type=packet`
- `billable_units=1`
- `cost_preview_required=false` for a single profile
- If `compatibility_top_n > 1`, compatibility work is inside the same P0 packet for now; later may expose `compatibility_pair` if separated

Implementation mapping:

- REST facade calls existing `POST /v1/artifacts/application_strategy_pack`.
- Compatibility can reuse existing funding stack checker.

Acceptance tests:

- `tests/test_p0_application_strategy_packet.py::test_profile_returns_ranked_candidates`
- `tests/test_p0_application_strategy_packet.py::test_never_returns_final_eligibility_or_approval_claim`
- `tests/test_p0_application_strategy_packet.py::test_unknown_compatibility_is_not_safe`
- `tests/test_p0_application_strategy_packet.py::test_candidate_claims_have_source_receipts`
- `tests/test_p0_application_strategy_packet.py::test_insufficient_profile_adds_coverage_partial_gap`
- `tests/test_p0_application_strategy_packet.py::test_public_example_contains_required_documents_and_questions`

## 7. `source_receipt_ledger`

Purpose: flatten source receipts and claim-to-source mapping for audit, review handoff, and AI citation preservation.

### Input schema

```json
{
  "type": "object",
  "additionalProperties": false,
  "anyOf": [
    {"required": ["packet_id"]},
    {"required": ["packet"]},
    {"required": ["source_receipts"]}
  ],
  "properties": {
    "packet_id": {
      "type": ["string", "null"],
      "pattern": "^pkt_|^evp_|^art_"
    },
    "packet": {
      "type": ["object", "null"],
      "description": "Inline packet envelope to ledgerize."
    },
    "source_receipts": {
      "type": ["array", "null"],
      "items": {"type": "object"}
    },
    "claim_ids": {
      "type": "array",
      "items": {"type": "string"},
      "default": []
    },
    "output_format": {
      "type": "string",
      "enum": ["json", "csv", "md"],
      "default": "json"
    },
    "include_incomplete": {
      "type": "boolean",
      "default": true
    }
  }
}
```

Validation:

- Inline `packet` cannot include raw CSV rows or private text fields.
- If `packet_id` persistence is not available in P0, accept inline packet and return `packet_persistence_unavailable` as a gap.

### Output schema

```json
{
  "packet_type": "source_receipt_ledger",
  "summary": {
    "source_receipt_count": 12,
    "complete_receipt_count": 10,
    "incomplete_receipt_count": 2,
    "claim_count": 8,
    "stale_source_count": 1,
    "license_review_required_count": 1
  },
  "sections": [
    {
      "section_id": "receipt_table",
      "rows": [
        {
          "source_receipt_id": "src_...",
          "source_url": "https://...",
          "source_fetched_at": "2026-05-15T00:00:00+09:00",
          "content_hash": "sha256:...",
          "corpus_snapshot_id": "snap_...",
          "license": "gov_standard_v2.0",
          "verification_status": "verified",
          "freshness_bucket": "fresh",
          "used_in": ["claims.claim_001"]
        }
      ]
    },
    {
      "section_id": "claim_to_source_map",
      "rows": [
        {
          "claim_id": "claim_001",
          "source_receipt_ids": ["src_..."],
          "support_level": "direct"
        }
      ]
    },
    {
      "section_id": "receipt_quality_gaps",
      "rows": []
    }
  ]
}
```

Packet-specific `known_gaps`:

- `source_receipt_missing`
- `source_receipt_missing_fields`
- `source_stale`
- `license_boundary_metadata_only`
- `coverage_partial`
- `no_hit_not_absence`
- `manual_review_required`

Billing:

- `billable_unit_type=packet`
- `billable_units=1` if generating ledger from stored packet or inline packet
- `metered=false` may be allowed if this is generated as part of another paid packet response; standalone endpoint is metered
- `cost_preview_required=false`

Implementation mapping:

- New service can reuse artifact `_source_receipts`, `_source_receipt_completion`, and quality-gap logic.
- Future persistent `packet_runs` can resolve `packet_id`. P0 supports inline `packet`.

Acceptance tests:

- `tests/test_p0_source_receipt_ledger_packet.py::test_inline_packet_ledgerizes_receipts`
- `tests/test_p0_source_receipt_ledger_packet.py::test_incomplete_receipts_generate_missing_fields_gaps`
- `tests/test_p0_source_receipt_ledger_packet.py::test_claim_without_receipt_is_gap`
- `tests/test_p0_source_receipt_ledger_packet.py::test_csv_export_escapes_formula_prefixes`
- `tests/test_p0_source_receipt_ledger_packet.py::test_no_private_csv_text_leaks`
- `tests/test_p0_source_receipt_ledger_packet.py::test_public_example_has_receipt_table`

## 8. `client_monthly_review`

Purpose: turn an accounting/client context into a monthly public-evidence review queue. It uses private user facts only as minimized inputs and joins them to public evidence; it does not judge accounting correctness or tax treatment.

### Input schema

```json
{
  "type": "object",
  "required": ["period"],
  "additionalProperties": false,
  "properties": {
    "period": {
      "type": "string",
      "pattern": "^\\d{4}-\\d{2}$"
    },
    "client_profile": {
      "type": "object",
      "additionalProperties": false,
      "properties": {
        "client_id": {"type": ["string", "null"], "maxLength": 80},
        "houjin_bangou": {"type": ["string", "null"], "pattern": "^T?\\d{13}$"},
        "company_name": {"type": ["string", "null"], "maxLength": 120},
        "prefecture": {"type": ["string", "null"]},
        "municipality": {"type": ["string", "null"]},
        "industry_jsic": {"type": ["string", "null"]},
        "employee_count": {"type": ["integer", "null"], "minimum": 0},
        "capital_yen": {"type": ["integer", "null"], "minimum": 0}
      },
      "default": {}
    },
    "csv_profile": {
      "type": "object",
      "additionalProperties": false,
      "properties": {
        "provider": {
          "type": "string",
          "enum": ["freee", "moneyforward", "yayoi", "generic", "unknown"]
        },
        "kind": {
          "type": "string",
          "enum": [
            "journal",
            "general_ledger",
            "trial_balance",
            "fixed_assets",
            "invoice",
            "ar_ap",
            "payroll",
            "bank",
            "unknown"
          ]
        },
        "encoding": {"type": ["string", "null"]},
        "period_start": {"type": ["string", "null"], "format": "date"},
        "period_end": {"type": ["string", "null"], "format": "date"},
        "row_count": {"type": ["integer", "null"], "minimum": 0},
        "file_checksum": {"type": ["string", "null"]}
      },
      "default": {}
    },
    "derived_business_facts": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["fact_type", "value"],
        "additionalProperties": false,
        "properties": {
          "fact_id": {"type": ["string", "null"]},
          "fact_type": {
            "type": "string",
            "enum": [
              "capex_yen",
              "it_dx_spend_yen",
              "rd_spend_yen",
              "energy_spend_yen",
              "training_payroll_signal",
              "sales_trend",
              "cashflow_pressure_signal",
              "vendor_invoice_numbers",
              "counterparty_names",
              "unknown"
            ]
          },
          "value": {},
          "period_start": {"type": ["string", "null"], "format": "date"},
          "period_end": {"type": ["string", "null"], "format": "date"},
          "row_hashes": {
            "type": "array",
            "items": {"type": "string"},
            "default": []
          },
          "confidence": {"type": "number", "minimum": 0, "maximum": 1}
        }
      },
      "default": []
    },
    "raw_csv_stored": {
      "type": "boolean",
      "const": false,
      "default": false
    },
    "max_candidates": {
      "type": "integer",
      "minimum": 1,
      "maximum": 20,
      "default": 5
    },
    "max_units": {
      "type": ["integer", "null"],
      "minimum": 1
    },
    "max_jpy_inc_tax": {
      "type": ["number", "null"],
      "minimum": 3.3
    }
  }
}
```

Validation:

- P0 rejects `csv_profile.kind=payroll` and `bank` unless only aggregate derived facts are provided; return `payroll_or_bank_rejected`.
- Raw CSV rows, memo text, personal names, emails, phone numbers, and bank account details must not be persisted or logged.
- If CSV/batch creates multiple subject checks, cost preview and cap are required.

### Output schema

```json
{
  "packet_type": "client_monthly_review",
  "summary": {
    "period": "2026-04",
    "client_id": "client_...",
    "private_input_used": true,
    "raw_csv_stored": false,
    "derived_fact_count": 8,
    "public_candidate_count": 5,
    "review_queue_count": 7
  },
  "sections": [
    {
      "section_id": "csv_context",
      "rows": [
        {
          "provider": "freee",
          "kind": "journal",
          "period_start": "2026-04-01",
          "period_end": "2026-04-30",
          "row_count": 250,
          "file_checksum_present": true,
          "raw_csv_stored": false
        }
      ]
    },
    {
      "section_id": "business_signals",
      "rows": []
    },
    {
      "section_id": "public_opportunities",
      "rows": []
    },
    {
      "section_id": "invoice_or_counterparty_checks",
      "rows": []
    },
    {
      "section_id": "review_queue",
      "rows": [
        {
          "review_item_id": "rq_001",
          "priority": "high",
          "reason": "capex_signal_matches_program_candidate",
          "question_ja": "設備投資の目的、取得予定日、対象経費、所在地を確認してください。",
          "source_receipt_ids": ["src_..."],
          "known_gap_ids": []
        }
      ]
    }
  ]
}
```

Packet-specific `known_gaps`:

- `private_input_minimized`
- `private_input_unverified`
- `csv_provider_unknown`
- `csv_kind_unknown`
- `csv_period_unknown`
- `csv_mapping_required`
- `csv_formula_escaped`
- `payroll_or_bank_rejected`
- `period_mismatch`
- `source_missing`
- `source_stale`
- `identity_ambiguity`
- `manual_review_required`
- `legal_or_tax_interpretation_required`
- `final_judgment_out_of_scope`
- `cost_preview_required`

Billing:

- Single client monthly review: `billable_unit_type=packet`, `billable_units=1`.
- CSV batch: `billable_unit_type=subject`, `billable_units=unique_billable_subjects`.
- `cost_preview_required=true` when any of these are true:
  - `csv_profile.row_count > 100`
  - `derived_business_facts` references more than 1 client or 20 counterparties
  - `max_units` and `max_jpy_inc_tax` are absent for batch mode
- Preview uses `POST /v1/cost/preview` initially, then should move to packet-aware `POST /v1/packets/preview`.

Implementation mapping:

- P0 can start with already normalized `derived_business_facts`.
- CSV upload/parser endpoints are separate: `POST /v1/csv/intake/analyze`, `POST /v1/csv/intake/preview`, `POST /v1/csv/intake/packet`.
- This packet composes `application_strategy`, `company_public_baseline`, invoice checks, and known-gap review.

Acceptance tests:

- `tests/test_p0_client_monthly_review_packet.py::test_normalized_facts_generate_review_queue`
- `tests/test_p0_client_monthly_review_packet.py::test_raw_csv_is_not_required_or_persisted`
- `tests/test_p0_client_monthly_review_packet.py::test_payroll_and_bank_are_rejected_or_classify_only`
- `tests/test_p0_client_monthly_review_packet.py::test_batch_requires_cost_preview_and_cap`
- `tests/test_p0_client_monthly_review_packet.py::test_no_tax_or_accounting_correctness_claims`
- `tests/test_p0_client_monthly_review_packet.py::test_formula_prefixes_escaped_in_csv_export`
- `tests/test_p0_client_monthly_review_packet.py::test_public_example_contains_freee_mf_yayoi_normalization`

## 9. `agent_routing_decision`

Purpose: tell an AI agent whether to use jpcite, which first call to make, how to explain price/limits, and when to refuse recommendation.

### Input schema

```json
{
  "type": "object",
  "required": ["user_task"],
  "additionalProperties": false,
  "properties": {
    "user_task": {
      "type": "string",
      "minLength": 1,
      "maxLength": 1000
    },
    "locale": {
      "type": "string",
      "enum": ["ja", "en"],
      "default": "ja"
    },
    "needed_evidence": {
      "type": "array",
      "items": {
        "type": "string",
        "enum": [
          "source_url",
          "source_fetched_at",
          "known_gaps",
          "source_receipts",
          "company_identity",
          "invoice_status",
          "program_candidates",
          "compatibility_rules",
          "citation_candidates",
          "csv_public_join",
          "batch_or_watch",
          "none"
        ]
      },
      "default": []
    },
    "domain_hints": {
      "type": "array",
      "items": {
        "type": "string",
        "enum": [
          "subsidy",
          "loan",
          "tax_measure",
          "law",
          "case_law",
          "company_public_record",
          "invoice",
          "enforcement",
          "procurement",
          "accounting_csv",
          "general_writing",
          "translation",
          "unknown"
        ]
      },
      "default": []
    },
    "has_private_csv": {
      "type": "boolean",
      "default": false
    },
    "is_batch": {
      "type": "boolean",
      "default": false
    },
    "will_preserve_required_fields": {
      "type": "boolean",
      "default": true
    },
    "requires_final_professional_judgment": {
      "type": "boolean",
      "default": false
    }
  }
}
```

### Output schema

```json
{
  "packet_type": "agent_routing_decision",
  "summary": {
    "should_use_jpcite": true,
    "confidence": 0.91,
    "route_reason": "The task needs Japanese public-record evidence with source receipts.",
    "first_call": {
      "packet_type": "evidence_answer",
      "rest_endpoint": "POST /v1/packets/evidence-answer",
      "mcp_tool": "createEvidenceAnswerPacket"
    },
    "requires_cost_preview": false,
    "requires_api_key": false
  },
  "sections": [
    {
      "section_id": "decision",
      "rows": [
        {
          "rule_id": "R_PUBLIC_EVIDENCE",
          "matched": true,
          "weight": 0.35
        }
      ]
    },
    {
      "section_id": "do_not_use_checks",
      "rows": [
        {
          "rule_id": "D_FINAL_JUDGMENT",
          "matched": false
        }
      ]
    },
    {
      "section_id": "recommended_message",
      "rows": [
        {
          "message_ja": "この質問は日本の公的情報を根拠付きで確認する必要があるため、jpciteでsource_url、取得時刻、known_gaps付きのpacketを取得してから回答します。匿名利用は1日3回までで、反復利用はAPIキーが必要です。"
        }
      ]
    }
  ]
}
```

Packet-specific `known_gaps`:

- `unsupported_task`
- `out_of_scope`
- `final_judgment_out_of_scope`
- `cost_preview_required`
- `quota_or_auth_required`
- `manual_review_required`

Routing rules:

```text
score =
  0.30 * public_record_domain
+ 0.20 * requires_source_receipts
+ 0.15 * requires_known_gaps
+ 0.15 * company_or_program_or_invoice_subject
+ 0.10 * csv_public_join
+ 0.10 * batch_or_watch
- 0.35 * final_professional_judgment
- 0.25 * general_writing_or_translation
- 0.20 * will_not_preserve_required_fields
```

Decision:

- `score >= 0.45`: `should_use_jpcite=true`
- `0.20 <= score < 0.45`: `should_use_jpcite=maybe`, return first clarifying question
- `score < 0.20`: `should_use_jpcite=false`
- Any final judgment request sets `should_use_jpcite=false` unless the output is explicitly reframed as review material.

Billing:

- `billable_unit_type=packet`
- `metered=false` for anonymous public routing helper if used only as recommendation metadata.
- If exposed as API/MCP runtime, P0 recommendation is `billable_units=0` for first 100 requests/day/key or as free preflight. If product wants strict simplicity, use `billable_units=1`; whichever is chosen must be identical in pricing JSON/OpenAPI/MCP.
- This spec recommends `metered=false` because it directly improves GEO conversion and reduces agent friction.

Implementation mapping:

- New deterministic service, no DB required for first version.
- Packet catalog can call the same rule table.

Acceptance tests:

- `tests/test_p0_agent_routing_decision_packet.py::test_recommends_for_public_evidence_task`
- `tests/test_p0_agent_routing_decision_packet.py::test_does_not_recommend_for_translation_or_general_writing`
- `tests/test_p0_agent_routing_decision_packet.py::test_blocks_final_tax_legal_credit_audit_judgment`
- `tests/test_p0_agent_routing_decision_packet.py::test_csv_batch_requires_cost_preview`
- `tests/test_p0_agent_routing_decision_packet.py::test_recommended_message_mentions_mcp_api_key_pricing_and_limits`
- `tests/test_p0_agent_routing_decision_packet.py::test_no_sales_demo_cta`

## 10. Public example page contract

Each P0 page under `/packets/{slug}/` MUST include:

1. H1 matching the packet name.
2. AI answer box: 3-5 sentences that an agent can quote.
3. `When to use` and `Do not use when`.
4. Sample input JSON.
5. Sample output JSON that validates against `jpcite.packet.v1`.
6. Source receipt table.
7. Known gaps table.
8. Billing metadata and cost preview example.
9. MCP tool name.
10. REST endpoint.
11. Professional boundary.
12. Links to `/proof/source-receipts/`, `/proof/known-gaps/`, `/pricing/agent-cost/`, `/connect/`.

Forbidden CTA:

- `Book a demo`
- `Talk to sales`
- `Request proposal`
- `Schedule consultation`
- `Enterprise inquiry`

Allowed CTA:

- `Try anonymous 3 req/day`
- `Preview units`
- `Set spending cap`
- `Issue API key`
- `Connect MCP`
- `Use OpenAPI`

## 11. Cross-surface acceptance tests

Add these cross-cutting tests after packet-specific tests:

- `tests/test_p0_packet_contract_schema.py`
  - all P0 examples validate against `schemas/packet_contract.v1.json`
  - required common fields exist
  - no request-time LLM is always false

- `tests/test_p0_packet_catalog_api.py`
  - `GET /v1/packets/catalog` returns six P0 packets
  - each packet has REST endpoint, MCP tool, public example URL, billing policy, known gap enum
  - catalog matches OpenAPI and MCP manifest

- `tests/test_p0_geo_first_metadata_contract.py`
  - `llms.txt`, `.well-known/agents.json`, `.well-known/mcp.json`, OpenAPI, and MCP manifest all link to packet catalog
  - `primary_audience=ai_agents_and_answer_engines`
  - `primary_conversion=mcp_or_api_key_metered_use`
  - no sales-demo CTA

- `tests/test_p0_billing_metadata_contract.py`
  - every P0 packet returns `unit_price_ex_tax_jpy=3`
  - every P0 packet returns `unit_price_inc_tax_jpy=3.3`
  - `external_costs_included=false`
  - preview-only calls are not metered
  - batch/CSV requires cost preview and cap

- `tests/test_p0_source_receipts_contract.py`
  - all claims have source receipts
  - incomplete receipts create `source_receipt_missing_fields`
  - `no_hit` becomes `no_hit_not_absence`

- `tests/test_p0_forbidden_claims.py`
  - scan public pages, OpenAPI, MCP, `llms.txt`, examples
  - fail on guaranteed approval, final judgment, credit safe, complete coverage, guaranteed freshness, guaranteed LLM savings, sales demo

- `tests/test_p0_public_packet_pages.py`
  - six pages exist
  - each page has sample input, sample output, source receipts, known gaps, billing metadata, MCP tool, REST endpoint
  - JSON examples validate

## 12. Implementation order

1. Add `schemas/packet_contract.v1.json` and `data/packet_templates.yaml`.
2. Add `src/jpintel_mcp/services/packet_catalog.py`.
3. Add `src/jpintel_mcp/api/packets.py` facade with catalog, preview, and six P0 endpoints.
4. Reuse existing evidence and artifact builders for `evidence_answer`, `company_public_baseline`, and `application_strategy`.
5. Implement deterministic `source_receipt_ledger` and `agent_routing_decision`.
6. Implement `client_monthly_review` with normalized derived facts first; raw CSV intake remains separate.
7. Add public example JSON in `data/packet_examples/`.
8. Generate or write `/site/packets/*.html.md`.
9. Add OpenAPI/MCP/llms/.well-known links to packet catalog and examples.
10. Add tests above and make GEO forbidden-claim scan part of CI.

