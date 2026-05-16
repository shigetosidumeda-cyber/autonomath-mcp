# Public Example Packets Deep Dive

Date: 2026-05-15  
Owner lane: Public example packets / sample outputs  
Status: implementation-planning only. Do not implement from this file without schema/API review.  
Scope: public sample input/output design for GEO-first P0 packets and CSV-derived packets.  
Boundary: no raw CSV rows, no transaction descriptions, no personal names, no private identifiers, no final tax/legal/audit/credit/application judgment.

## 0. Goal

Public examples must let AI agents recommend jpcite before a user asks for sales material. Each example page should show a complete, quotable packet shape: input, output, source receipts, known gaps, billing metadata, REST/MCP entrypoints, answer box, JSON-LD, and CTA.

The examples below are synthetic fixtures. They must never imply that the sample company, invoice number, program fit, no-hit result, or CSV profile is a real-world fact. Official source URLs may be real source-family URLs, but record IDs, company names, checksums, packet IDs, and claim IDs are fixtures.

## 1. Public Sample Rules

Public examples must satisfy these rules:

- Include the shared `jpcite.packet.v1` envelope fields from `p0_geo_first_packets_spec_2026-05-15.md`.
- Keep sample output short enough for agents to read, but complete enough to validate.
- Use `request_time_llm_call_performed=false` in every sample.
- Map every externally usable claim to `source_receipt_ids`.
- Move unsupported claims to `known_gaps`; do not leave them as weak claims.
- Treat `no_hit` only as `no_hit_not_absence`.
- Show `human_review_required=true` for tax, legal, audit, application, credit, accounting-adjacent, or DD contexts.
- Show cost explicitly and state external LLM/runtime/search costs are not included.
- Include professional boundary copy on every page.
- Avoid sales-demo CTAs.

Common synthetic context:

```json
{
  "sample_fixture": true,
  "fixture_note": "Synthetic public example. Not a real company or official result.",
  "sample_company_name": "株式会社公開サンプル",
  "sample_houjin_bangou": "0000000000000",
  "sample_period": "2026-04",
  "sample_snapshot": "snap_public_example_20260515",
  "sample_checksum": "sha256:public-example-fixture"
}
```

## 2. P0 Packet Public Samples

### 2.1 `evidence_answer`

Public page: `/packets/evidence-answer/`  
REST: `POST /v1/packets/evidence-answer`  
MCP: `createEvidenceAnswerPacket`

Use case: an agent needs official-source facts before drafting an answer about a Japanese public program.

Sample input:

```json
{
  "query": "東京都の中小企業向け省エネ設備補助制度を出典付きで確認したい",
  "jurisdiction": "prefecture",
  "prefecture": "東京都",
  "topic": "program",
  "limit": 3,
  "packet_profile": "brief",
  "source_tokens_basis": "unknown"
}
```

Sample output design:

```json
{
  "packet_id": "pkt_ex_evidence_answer_001",
  "packet_type": "evidence_answer",
  "packet_version": "2026-05-15",
  "schema_version": "jpcite.packet.v1",
  "api_version": "v1",
  "generated_at": "2026-05-15T12:00:00+09:00",
  "corpus_snapshot_id": "snap_public_example_20260515",
  "corpus_checksum": "sha256:public-example-fixture",
  "request_time_llm_call_performed": false,
  "input_echo": {
    "query": "東京都の中小企業向け省エネ設備補助制度を出典付きで確認したい",
    "prefecture": "東京都",
    "topic": "program"
  },
  "summary": {
    "answer_not_included": true,
    "record_count": 2,
    "citation_candidate_count": 2,
    "known_gap_count": 1
  },
  "sections": [
    {
      "section_id": "answer_facts",
      "rows": [
        {
          "claim_id": "claim_ea_001",
          "fact_type": "program_candidate",
          "subject_id": "program:fixture_tokyo_energy_001",
          "subject_name": "東京都省エネ設備導入支援サンプル",
          "fact": "東京都内事業者向けの省エネ設備導入支援候補として確認対象にできます。",
          "support_level": "direct",
          "source_receipt_ids": ["src_ex_tokyo_program_001"]
        }
      ]
    },
    {
      "section_id": "citation_candidates",
      "rows": [
        {
          "citation_id": "cit_ea_001",
          "claim_id": "claim_ea_001",
          "source_url": "https://www.tokyo.lg.jp/",
          "source_fetched_at": "2026-05-15T09:00:00+09:00",
          "quote_safe_summary": "制度名、対象地域、募集状態の確認候補。",
          "verification_status": "verified"
        }
      ]
    }
  ],
  "claims": [
    {
      "claim_id": "claim_ea_001",
      "text": "省エネ設備導入支援の候補レコードがあります。",
      "source_receipt_ids": ["src_ex_tokyo_program_001"]
    }
  ],
  "records": [],
  "source_receipts": ["see section 4.1"],
  "known_gaps": ["see section 4.2 gap_ex_deadline_unparsed"],
  "quality": {
    "coverage_score": 0.72,
    "freshness_bucket": "fresh",
    "source_receipt_completion": {"complete": 1, "total": 1},
    "human_review_required": true,
    "human_review_reasons": ["application_candidate_review_required"]
  },
  "billing_metadata": "see section 4.3 single_packet",
  "agent_guidance": "preserve source_url, source_fetched_at, known_gaps, and do not draft final eligibility"
}
```

Answer box:

```text
jpcite evidence_answer は、AIが日本の公的制度について回答する前に使う根拠パケットです。回答文そのものではなく、出典URL、取得時刻、claim-to-source対応、known gapsを返します。補助金・制度・法令・法人情報を断定する前に、確認済み範囲と未確認範囲を分けられます。
```

### 2.2 `company_public_baseline`

Public page: `/packets/company-public-baseline/`  
REST: `POST /v1/packets/company-public-baseline`  
MCP: `createCompanyPublicBaselinePacket`

Use case: an agent checks public records for a Japanese company before DD, CRM note, or client folder work.

Sample input:

```json
{
  "houjin_bangou": "0000000000000",
  "company_name": "株式会社公開サンプル",
  "prefecture": "東京都",
  "include_sections": [
    "identity",
    "invoice_status",
    "enforcement",
    "adoption_history",
    "watch_status"
  ],
  "max_per_section": 5
}
```

Sample output design:

```json
{
  "packet_id": "pkt_ex_company_public_baseline_001",
  "packet_type": "company_public_baseline",
  "packet_version": "2026-05-15",
  "schema_version": "jpcite.packet.v1",
  "api_version": "v1",
  "generated_at": "2026-05-15T12:00:00+09:00",
  "corpus_snapshot_id": "snap_public_example_20260515",
  "corpus_checksum": "sha256:public-example-fixture",
  "request_time_llm_call_performed": false,
  "input_echo": {
    "houjin_bangou": "0000000000000",
    "company_name": "株式会社公開サンプル"
  },
  "summary": {
    "houjin_bangou": "0000000000000",
    "company_name": "株式会社公開サンプル",
    "identity_confidence": 1.0,
    "invoice_status": "unknown_in_mirror",
    "enforcement_record_count": 0,
    "adoption_record_count": 1,
    "risk_flags": [],
    "known_gap_count": 2
  },
  "sections": [
    {
      "section_id": "identity",
      "rows": [
        {
          "name": "株式会社公開サンプル",
          "prefecture": "東京都",
          "identity_confidence": 1.0,
          "source_receipt_ids": ["src_ex_nta_houjin_hit"]
        }
      ]
    },
    {
      "section_id": "invoice_status",
      "rows": [
        {
          "registration_number": "T0000000000000",
          "status": "unknown_in_mirror",
          "source_receipt_ids": ["src_ex_invoice_no_hit"]
        }
      ]
    },
    {
      "section_id": "review_queue",
      "rows": [
        {
          "review_item_id": "rev_cpb_001",
          "priority": "medium",
          "question_ja": "インボイスno-hitは登録なしの証明ではありません。公式サイトで番号条件を再確認してください。",
          "known_gap_ids": ["gap_ex_no_hit_invoice"]
        }
      ]
    }
  ],
  "claims": [
    {
      "claim_id": "claim_cpb_001",
      "text": "入力された法人番号に対応する法人基本情報の確認候補があります。",
      "source_receipt_ids": ["src_ex_nta_houjin_hit"]
    }
  ],
  "source_receipts": ["see section 4.1"],
  "known_gaps": ["see section 4.2 gap_ex_no_hit_invoice", "gap_ex_enforcement_coverage"],
  "quality": {
    "coverage_score": 0.66,
    "freshness_bucket": "acceptable",
    "source_receipt_completion": {"complete": 2, "total": 2},
    "human_review_required": true,
    "human_review_reasons": ["public_dd_not_credit_or_legal_judgment"]
  },
  "billing_metadata": "see section 4.3 single_packet"
}
```

Answer box:

```text
company_public_baseline は、法人番号・インボイス・公的イベントなどを、会社フォルダや取引先確認の前段として整理します。民間与信や非公開情報は扱わず、公的に確認できる範囲と未確認範囲を分けます。no-hitは安全性や不存在の証明ではありません。
```

### 2.3 `application_strategy`

Public page: `/packets/application-strategy/`  
REST: `POST /v1/packets/application-strategy`  
MCP: `createApplicationStrategyPacket`

Use case: an agent prepares grant/program candidates and questions, without deciding eligibility.

Sample input:

```json
{
  "profile": {
    "prefecture": "東京都",
    "industry_jsic": "E",
    "business_description": "製造業。省エネ設備と生産管理システムの更新を検討。",
    "employee_count": 28,
    "capital_yen": 10000000,
    "planned_investment_yen": 4200000,
    "investment_purpose": "energy_saving"
  },
  "max_candidates": 3,
  "compatibility_top_n": 2,
  "include_required_documents": true,
  "include_compatibility": true
}
```

Sample output design:

```json
{
  "packet_id": "pkt_ex_application_strategy_001",
  "packet_type": "application_strategy",
  "packet_version": "2026-05-15",
  "schema_version": "jpcite.packet.v1",
  "api_version": "v1",
  "generated_at": "2026-05-15T12:00:00+09:00",
  "corpus_snapshot_id": "snap_public_example_20260515",
  "corpus_checksum": "sha256:public-example-fixture",
  "request_time_llm_call_performed": false,
  "input_echo": {
    "prefecture": "東京都",
    "industry_jsic": "E",
    "investment_purpose": "energy_saving"
  },
  "summary": {
    "candidate_count": 2,
    "total_considered": 248,
    "primary_candidate": "program:fixture_tokyo_energy_001",
    "compatibility_status": "unknown",
    "eligibility_decision_included": false
  },
  "sections": [
    {
      "section_id": "ranked_candidates",
      "rows": [
        {
          "program_id": "program:fixture_tokyo_energy_001",
          "program_name": "東京都省エネ設備導入支援サンプル",
          "rank": 1,
          "fit_score": 0.74,
          "fit_signal": "candidate_for_review",
          "match_reasons": ["prefecture_match", "purpose_match"],
          "caveats": ["deadline_missing"],
          "amount_max_yen": 1000000,
          "subsidy_rate": "1/2",
          "deadline": null,
          "required_documents": ["見積書", "設備仕様書", "事業計画の確認資料"],
          "source_receipt_ids": ["src_ex_tokyo_program_001"]
        }
      ]
    },
    {
      "section_id": "application_questions",
      "rows": [
        {
          "question_id": "q_as_001",
          "question_ja": "対象設備の型番、取得予定日、設置場所を確認してください。",
          "reason": "required_document_and_expense_scope_review"
        }
      ]
    }
  ],
  "claims": [
    {
      "claim_id": "claim_as_001",
      "text": "省エネ設備投資と地域条件が一致する候補制度があります。",
      "source_receipt_ids": ["src_ex_tokyo_program_001"]
    }
  ],
  "source_receipts": ["see section 4.1"],
  "known_gaps": ["see section 4.2 gap_ex_deadline_unparsed", "gap_ex_compatibility_unknown"],
  "quality": {
    "coverage_score": 0.61,
    "freshness_bucket": "fresh",
    "source_receipt_completion": {"complete": 1, "total": 1},
    "human_review_required": true,
    "human_review_reasons": ["eligibility_and_application_judgment_out_of_scope"]
  },
  "billing_metadata": "see section 4.3 single_packet"
}
```

Answer box:

```text
application_strategy は、申請候補、確認理由、必要書類、併用ルールの不明点を整理するパケットです。採択可否や適格性を断定せず、候補と人間レビュー項目を返します。制度ページ、締切、対象経費、併用可否は source receipts と known gaps で確認できます。
```

### 2.4 `source_receipt_ledger`

Public page: `/packets/source-receipt-ledger/`  
REST: `POST /v1/packets/source-receipt-ledger`  
MCP: `getSourceReceiptLedgerPacket`

Use case: an agent or reviewer needs a flat evidence table for a prior packet.

Sample input:

```json
{
  "packet": {
    "packet_id": "pkt_ex_application_strategy_001",
    "packet_type": "application_strategy",
    "claims": [
      {
        "claim_id": "claim_as_001",
        "text": "省エネ設備投資と地域条件が一致する候補制度があります。",
        "source_receipt_ids": ["src_ex_tokyo_program_001"]
      }
    ],
    "source_receipts": [
      {
        "source_receipt_id": "src_ex_tokyo_program_001",
        "source_url": "https://www.tokyo.lg.jp/",
        "source_fetched_at": "2026-05-15T09:00:00+09:00",
        "content_hash": "sha256:tokyo-program-fixture",
        "corpus_snapshot_id": "snap_public_example_20260515",
        "license": "review_required",
        "used_in": ["claims.claim_as_001"]
      }
    ]
  },
  "output_format": "json",
  "include_incomplete": true
}
```

Sample output design:

```json
{
  "packet_id": "pkt_ex_source_receipt_ledger_001",
  "packet_type": "source_receipt_ledger",
  "packet_version": "2026-05-15",
  "schema_version": "jpcite.packet.v1",
  "api_version": "v1",
  "generated_at": "2026-05-15T12:00:00+09:00",
  "corpus_snapshot_id": "snap_public_example_20260515",
  "corpus_checksum": "sha256:public-example-fixture",
  "request_time_llm_call_performed": false,
  "summary": {
    "source_receipt_count": 1,
    "complete_receipt_count": 1,
    "incomplete_receipt_count": 0,
    "claim_count": 1,
    "stale_source_count": 0,
    "license_review_required_count": 1
  },
  "sections": [
    {
      "section_id": "receipt_table",
      "rows": [
        {
          "source_receipt_id": "src_ex_tokyo_program_001",
          "source_url": "https://www.tokyo.lg.jp/",
          "source_fetched_at": "2026-05-15T09:00:00+09:00",
          "content_hash": "sha256:tokyo-program-fixture",
          "corpus_snapshot_id": "snap_public_example_20260515",
          "license": "review_required",
          "verification_status": "verified",
          "freshness_bucket": "fresh",
          "used_in": ["claims.claim_as_001"]
        }
      ]
    },
    {
      "section_id": "claim_to_source_map",
      "rows": [
        {
          "claim_id": "claim_as_001",
          "source_receipt_ids": ["src_ex_tokyo_program_001"],
          "support_level": "direct"
        }
      ]
    }
  ],
  "claims": [],
  "source_receipts": ["see section 4.1"],
  "known_gaps": [],
  "quality": {
    "coverage_score": 1.0,
    "freshness_bucket": "fresh",
    "source_receipt_completion": {"complete": 1, "total": 1},
    "human_review_required": true,
    "human_review_reasons": ["ledger_is_evidence_map_not_professional_opinion"]
  },
  "billing_metadata": "see section 4.3 single_packet"
}
```

Answer box:

```text
source_receipt_ledger は、packet内の主張と出典を監査しやすい表にします。AI回答、稟議メモ、専門家レビューに渡す前に、source_url、取得時刻、hash、license、known gaps が揃っているか確認できます。
```

### 2.5 `client_monthly_review`

Public page: `/packets/client-monthly-review/`  
REST: `POST /v1/packets/client-monthly-review`  
MCP: `createClientMonthlyReviewPacket`

Use case: an accounting firm or BPO agent creates a public-evidence monthly review queue from minimized client and CSV-derived facts.

Sample input:

```json
{
  "period": "2026-04",
  "client_profile": {
    "client_id": "client_public_example_001",
    "houjin_bangou": "0000000000000",
    "company_name": "株式会社公開サンプル",
    "prefecture": "東京都",
    "industry_jsic": "E",
    "employee_count": 28,
    "capital_yen": 10000000
  },
  "csv_profile": {
    "provider": "freee",
    "kind": "journal",
    "encoding": "utf-8-sig",
    "period_start": "2026-04-01",
    "period_end": "2026-04-30",
    "row_count": 250,
    "file_checksum": "sha256:csv-profile-only-fixture"
  },
  "derived_business_facts": [
    {
      "fact_id": "csv_fact_capex_001",
      "fact_type": "capex_yen",
      "value": {"bucket": "1m_to_5m_jpy", "exact_amount_redacted": true},
      "period_start": "2026-04-01",
      "period_end": "2026-04-30",
      "row_hashes": ["sha256:row-hash-fixture-a", "sha256:row-hash-fixture-b"],
      "confidence": 0.82
    }
  ],
  "raw_csv_stored": false,
  "max_candidates": 5,
  "max_units": 20,
  "max_jpy_inc_tax": 66
}
```

Sample output design:

```json
{
  "packet_id": "pkt_ex_client_monthly_review_001",
  "packet_type": "client_monthly_review",
  "packet_version": "2026-05-15",
  "schema_version": "jpcite.packet.v1",
  "api_version": "v1",
  "generated_at": "2026-05-15T12:00:00+09:00",
  "corpus_snapshot_id": "snap_public_example_20260515",
  "corpus_checksum": "sha256:public-example-fixture",
  "request_time_llm_call_performed": false,
  "input_echo": {
    "period": "2026-04",
    "client_id": "client_public_example_001",
    "raw_csv_stored": false
  },
  "summary": {
    "period": "2026-04",
    "client_id": "client_public_example_001",
    "private_input_used": true,
    "raw_csv_stored": false,
    "derived_fact_count": 1,
    "public_candidate_count": 1,
    "review_queue_count": 3
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
      "rows": [
        {
          "signal_id": "sig_cmr_001",
          "signal_type": "capex_bucket",
          "value": "1m_to_5m_jpy",
          "source_kind": "csv_derived",
          "not_accounting_or_tax_opinion": true
        }
      ]
    },
    {
      "section_id": "public_opportunities",
      "rows": [
        {
          "program_id": "program:fixture_tokyo_energy_001",
          "reason": "capex_signal_matches_energy_saving_candidate",
          "source_receipt_ids": ["src_ex_tokyo_program_001"]
        }
      ]
    },
    {
      "section_id": "review_queue",
      "rows": [
        {
          "review_item_id": "rq_cmr_001",
          "priority": "high",
          "reason": "capex_signal_matches_program_candidate",
          "question_ja": "設備投資の目的、取得予定日、対象経費、所在地を確認してください。",
          "source_receipt_ids": ["src_ex_tokyo_program_001"],
          "known_gap_ids": ["gap_ex_private_input_unverified"]
        }
      ]
    }
  ],
  "claims": [
    {
      "claim_id": "claim_cmr_001",
      "text": "CSV由来の設備投資シグナルと一致する制度候補があります。",
      "source_receipt_ids": ["src_ex_csv_profile_001", "src_ex_tokyo_program_001"]
    }
  ],
  "source_receipts": ["see section 4.1"],
  "known_gaps": ["see section 4.2 gap_ex_private_input_unverified"],
  "quality": {
    "coverage_score": 0.58,
    "freshness_bucket": "acceptable",
    "source_receipt_completion": {"complete": 2, "total": 2},
    "human_review_required": true,
    "human_review_reasons": ["accounting_tax_application_review_required"]
  },
  "billing_metadata": "see section 4.3 capped_batch_ready"
}
```

Answer box:

```text
client_monthly_review は、raw CSVを出さずに、期間・件数・派生シグナル・公的候補・レビュー項目をまとめます。仕訳や税務処理の正否は判断せず、月次面談や専門家確認に渡す根拠整理として使います。
```

### 2.6 `agent_routing_decision`

Public page: `/packets/agent-routing-decision/`  
REST: `POST /v1/packets/agent-routing-decision`  
MCP: `decideAgentRouteForJpcite`

Use case: an agent decides whether jpcite should be recommended and which packet to call first.

Sample input:

```json
{
  "user_task": "この会社に使えそうな補助金を、出典付きで候補だけ確認して。採択可否は断定しないで。",
  "locale": "ja",
  "needed_evidence": [
    "source_url",
    "source_fetched_at",
    "known_gaps",
    "program_candidates"
  ],
  "domain_hints": ["subsidy", "company_public_record"],
  "has_private_csv": false,
  "is_batch": false,
  "will_preserve_required_fields": true,
  "requires_final_professional_judgment": false
}
```

Sample output design:

```json
{
  "packet_id": "pkt_ex_agent_routing_decision_001",
  "packet_type": "agent_routing_decision",
  "packet_version": "2026-05-15",
  "schema_version": "jpcite.packet.v1",
  "api_version": "v1",
  "generated_at": "2026-05-15T12:00:00+09:00",
  "corpus_snapshot_id": "snap_public_example_20260515",
  "corpus_checksum": "sha256:public-example-fixture",
  "request_time_llm_call_performed": false,
  "summary": {
    "should_use_jpcite": true,
    "confidence": 0.91,
    "route_reason": "The task needs Japanese public-record evidence with source receipts.",
    "first_call": {
      "packet_type": "application_strategy",
      "rest_endpoint": "POST /v1/packets/application-strategy",
      "mcp_tool": "createApplicationStrategyPacket"
    },
    "requires_cost_preview": false,
    "requires_api_key": false
  },
  "sections": [
    {
      "section_id": "decision",
      "rows": [
        {"rule_id": "R_PUBLIC_EVIDENCE", "matched": true, "weight": 0.3},
        {"rule_id": "R_PROGRAM_CANDIDATES", "matched": true, "weight": 0.15}
      ]
    },
    {
      "section_id": "do_not_use_checks",
      "rows": [
        {"rule_id": "D_FINAL_JUDGMENT", "matched": false},
        {"rule_id": "D_GENERAL_WRITING", "matched": false}
      ]
    },
    {
      "section_id": "recommended_message",
      "rows": [
        {
          "message_ja": "この質問は日本の公的情報を根拠付きで確認する必要があるため、jpciteでsource_url、取得時刻、known_gaps付きのpacketを取得してから回答します。匿名利用は1日3回までで、反復利用はAPIキーと月次上限の設定を推奨します。"
        }
      ]
    }
  ],
  "claims": [],
  "source_receipts": [],
  "known_gaps": [],
  "quality": {
    "coverage_score": 1.0,
    "freshness_bucket": "unknown",
    "source_receipt_completion": {"complete": 0, "total": 0},
    "human_review_required": false,
    "human_review_reasons": []
  },
  "billing_metadata": "see section 4.3 free_preflight"
}
```

Answer box:

```text
agent_routing_decision は、AIエージェントが jpcite を使うべきか、最初にどのpacketを呼ぶべきか、費用確認が必要かを判定する preflight です。一般作文や最終専門判断には推薦せず、出典付きの日本公的データが必要な場合にだけ案内します。
```

## 3. CSV-Derived Public Sample Designs

### 3.1 CSV Intake Quality Packet

Public page proposal: `/packets/csv-intake-quality/` or `/proof/csv-intake-quality/`  
REST proposal: `POST /v1/csv/intake/analyze` then `POST /v1/csv/intake/packet`  
MCP proposal: `createCsvIntakeQualityPacket`

Purpose: show what can be safely known from an accounting CSV before public joins, without exposing raw rows.

Sample input:

```json
{
  "csv_profile": {
    "provider": "yayoi",
    "kind": "journal",
    "encoding": "cp932",
    "period_start": "2026-04-01",
    "period_end": "2026-04-30",
    "row_count": 420,
    "column_count": 25,
    "column_profile_hash": "sha256:normalized-columns-fixture",
    "file_checksum": "sha256:file-fixture-redacted"
  },
  "raw_csv_stored": false,
  "publishable_output": true
}
```

Sample output sections:

```json
{
  "packet_type": "csv_intake_quality",
  "summary": {
    "provider": "yayoi",
    "kind": "journal",
    "row_count": 420,
    "period": "2026-04-01..2026-04-30",
    "raw_csv_stored": false,
    "review_required": true,
    "review_condition_count": 3
  },
  "sections": [
    {
      "section_id": "column_mapping",
      "rows": [
        {"canonical_field": "entry_date", "detected": true, "source_column_label": "取引日付"},
        {"canonical_field": "voucher_id", "detected": true, "source_column_label": "伝票No."},
        {"canonical_field": "debit_amount", "detected": true, "source_column_label": "借方金額"}
      ]
    },
    {
      "section_id": "quality_review_queue",
      "rows": [
        {
          "condition_code": "vendor_specific_columns_present",
          "severity": "info",
          "observed_count": 4,
          "human_message_ja": "決算、付箋、調整などのベンダー固有メタが存在します。判断ではなくレビュー材料として扱ってください。"
        },
        {
          "condition_code": "small_cell_suppression_applied",
          "severity": "info",
          "observed_scope": "account_month",
          "human_message_ja": "少数セルは公開出力で丸めています。個別取引は再構成できません。"
        }
      ]
    }
  ],
  "known_gaps": [
    {
      "gap_id": "gap_csv_mapping_review",
      "gap_kind": "csv_mapping_required",
      "severity": "review_required",
      "message_ja": "ベンダー固有列の意味はCSV出力元の設定に依存します。",
      "blocks_final_answer": false
    }
  ]
}
```

Must not show:

- Raw row values.
- 摘要, 取引先, 作成者, 伝票番号そのもの.
- Individual transaction amount when a small cell could identify it.
- Any statement that a journal entry is correct or tax-deductible.

### 3.2 Client Monthly Review Packet

This is the P0 `client_monthly_review` public example in section 2.5. The CSV-specific page should additionally show three provider variants:

| Provider variant | Safe sample signal | Required gap |
|---|---|---|
| freee journal | `capex_bucket`, `energy_spend_signal`, `memo_presence_rate` | `private_input_unverified` |
| Money Forward journal | `settlement_entry_flag_count`, `created_updated_meta_present` | `csv_mapping_required` |
| Yayoi journal | `adjustment_flag_count`, `sticky_note_present`, `cp932_detected` | `csv_provider_unknown` if profile mismatch |

Sample review queue rows:

```json
[
  {
    "review_item_id": "rq_public_001",
    "priority": "high",
    "reason": "public_program_candidate_from_csv_signal",
    "question_ja": "設備投資の目的、取得予定日、対象経費、事業所所在地を確認してください。",
    "not_a_tax_or_accounting_opinion": true
  },
  {
    "review_item_id": "rq_public_002",
    "priority": "medium",
    "reason": "invoice_status_no_hit_not_absence",
    "question_ja": "T番号の入力値、法人/個人区分、最新公表情報を公式サイトで確認してください。",
    "not_a_credit_or_legal_opinion": true
  }
]
```

### 3.3 Public Join Packet

Public page proposal: `/packets/public-join/` or folded into `/proof/public-source-join/`  
REST proposal: `POST /v1/packets/public-join`  
MCP proposal: `createPublicJoinPacket`

Purpose: show how minimized CSV or CRM hints connect to public sources. This packet must separate CSV-asserted facts from public-verified facts.

Sample input:

```json
{
  "entity_hints": [
    {
      "hint_id": "hint_001",
      "houjin_bangou": "0000000000000",
      "company_name": "株式会社公開サンプル",
      "prefecture": "東京都",
      "source_context": "client_csv_profile",
      "private_fields_minimized": true
    }
  ],
  "join_sources": [
    "nta_corporate_number",
    "nta_invoice_registrants",
    "p_portal_procurement_awards",
    "edinet_filings"
  ],
  "max_units": 12,
  "max_jpy_inc_tax": 39.6
}
```

Sample output sections:

```json
{
  "packet_type": "public_join",
  "summary": {
    "entity_hint_count": 1,
    "public_verified_fact_count": 1,
    "csv_asserted_fact_count": 1,
    "candidate_edge_count": 1,
    "no_hit_receipt_count": 2,
    "known_gap_count": 3
  },
  "sections": [
    {
      "section_id": "csv_asserted_facts",
      "rows": [
        {
          "fact_id": "csv_asserted_001",
          "fact_type": "houjin_bangou_provided",
          "value_redacted": false,
          "value": "0000000000000",
          "source_receipt_ids": ["src_ex_csv_profile_001"]
        }
      ]
    },
    {
      "section_id": "public_verified_facts",
      "rows": [
        {
          "fact_id": "public_verified_001",
          "fact_type": "corporate_identity_candidate",
          "join_decision": "exact_verified",
          "confidence": 1.0,
          "source_receipt_ids": ["src_ex_nta_houjin_hit"]
        }
      ]
    },
    {
      "section_id": "no_hit_receipts",
      "rows": [
        {
          "source_receipt_id": "src_ex_invoice_no_hit",
          "source_id": "nta_invoice_registrants",
          "result_state": "zero_result",
          "no_hit_interpretation": "absence_not_proven"
        }
      ]
    },
    {
      "section_id": "join_review_queue",
      "rows": [
        {
          "review_item_id": "join_rq_001",
          "reason": "no_hit_not_absence",
          "question_ja": "no-hit sourceは不存在の証明ではないため、必要に応じて公式検索条件を再確認してください。"
        }
      ]
    }
  ]
}
```

Public join page answer box:

```text
public_join は、CSVやCRMから渡された最小限の会社ヒントを、公的source receipt付きの確認結果へ分けるpacketです。入力CSVの主張、公的sourceで確認できた事実、候補止まりの結合、no-hit receiptを別々に返します。
```

## 4. Concrete Shared Examples

### 4.1 `source_receipts[]`

Use these fixtures across public pages so agents learn the stable shape.

```json
[
  {
    "source_receipt_id": "src_ex_nta_houjin_hit",
    "source_id": "nta_corporate_number",
    "source_url": "https://www.houjin-bangou.nta.go.jp/",
    "canonical_source_url": "https://www.houjin-bangou.nta.go.jp/",
    "source_name": "国税庁 法人番号公表サイト",
    "publisher": "National Tax Agency",
    "source_kind": "houjin",
    "source_fetched_at": "2026-05-15T09:00:00+09:00",
    "last_verified_at": "2026-05-15T09:00:00+09:00",
    "content_hash": "sha256:nta-houjin-fixture",
    "source_checksum": "sha256:nta-houjin-fixture",
    "corpus_snapshot_id": "snap_public_example_20260515",
    "retrieval_method": "api_mirror",
    "license": "review_required",
    "license_boundary": "metadata_only",
    "verification_status": "verified",
    "support_level": "direct",
    "freshness_bucket": "fresh",
    "used_in": ["claims.claim_cpb_001", "sections.identity"],
    "claim_refs": ["claim_cpb_001"],
    "request_params_redacted": {
      "houjin_bangou": "0000000000000",
      "app_id": "hashed"
    }
  },
  {
    "source_receipt_id": "src_ex_invoice_no_hit",
    "source_id": "nta_invoice_registrants",
    "source_url": "https://www.invoice-kohyo.nta.go.jp/",
    "canonical_source_url": "https://www.invoice-kohyo.nta.go.jp/",
    "source_name": "国税庁 適格請求書発行事業者公表サイト",
    "publisher": "National Tax Agency",
    "source_kind": "invoice",
    "source_fetched_at": "2026-05-15T09:02:00+09:00",
    "last_verified_at": "2026-05-15T09:02:00+09:00",
    "content_hash": "sha256:invoice-zero-result-fixture",
    "source_checksum": "sha256:invoice-zero-result-fixture",
    "corpus_snapshot_id": "snap_public_example_20260515",
    "retrieval_method": "api_mirror",
    "license": "review_required",
    "license_boundary": "metadata_only",
    "verification_status": "no_hit",
    "support_level": "no_hit_not_absence",
    "freshness_bucket": "acceptable",
    "used_in": ["sections.invoice_status", "known_gaps.gap_ex_no_hit_invoice"],
    "claim_refs": [],
    "result_state": "zero_result",
    "result_count": 0,
    "no_hit_interpretation": "absence_not_proven"
  },
  {
    "source_receipt_id": "src_ex_tokyo_program_001",
    "source_id": "tokyo_program_public_page",
    "source_url": "https://www.tokyo.lg.jp/",
    "canonical_source_url": "https://www.tokyo.lg.jp/",
    "source_name": "東京都 公開制度ページ",
    "publisher": "Tokyo Metropolitan Government",
    "source_kind": "program",
    "source_fetched_at": "2026-05-15T09:05:00+09:00",
    "last_verified_at": "2026-05-15T09:05:00+09:00",
    "content_hash": "sha256:tokyo-program-fixture",
    "source_checksum": "sha256:tokyo-program-fixture",
    "corpus_snapshot_id": "snap_public_example_20260515",
    "retrieval_method": "local_mirror",
    "license": "review_required",
    "license_boundary": "link_only",
    "verification_status": "verified",
    "support_level": "direct",
    "freshness_bucket": "fresh",
    "used_in": ["claims.claim_ea_001", "claims.claim_as_001"],
    "claim_refs": ["claim_ea_001", "claim_as_001"]
  },
  {
    "source_receipt_id": "src_ex_csv_profile_001",
    "source_id": "user_csv_derived_profile",
    "source_url": "jpcite://user-upload/csv-profile-only",
    "canonical_source_url": "jpcite://user-upload/csv-profile-only",
    "source_name": "User-provided CSV derived profile",
    "publisher": "User provided",
    "source_kind": "csv_derived",
    "source_fetched_at": "2026-05-15T09:10:00+09:00",
    "last_verified_at": "2026-05-15T09:10:00+09:00",
    "content_hash": "sha256:csv-profile-only-fixture",
    "source_checksum": "sha256:csv-profile-only-fixture",
    "corpus_snapshot_id": "snap_public_example_20260515",
    "retrieval_method": "user_csv_derived",
    "license": "review_required",
    "license_boundary": "derived_fact",
    "verification_status": "inferred",
    "support_level": "derived",
    "freshness_bucket": "unknown",
    "used_in": ["claims.claim_cmr_001", "sections.csv_context"],
    "claim_refs": ["claim_cmr_001"],
    "privacy_boundary": {
      "raw_csv_stored": false,
      "raw_rows_exposed": false,
      "personal_fields_exposed": false,
      "small_cell_suppression": true
    }
  }
]
```

### 4.2 `known_gaps[]`

Concrete gap examples for public samples:

```json
[
  {
    "gap_id": "gap_ex_deadline_unparsed",
    "gap_kind": "deadline_missing",
    "severity": "review_required",
    "message": "The sample program deadline was not parsed from a verified source document.",
    "message_ja": "サンプル制度の締切は検証済み文書から抽出できていません。",
    "affected_fields": ["sections.ranked_candidates.rows[0].deadline"],
    "affected_records": ["program:fixture_tokyo_energy_001"],
    "source_receipt_id": "src_ex_tokyo_program_001",
    "agent_instruction": "Do not state the deadline as current. Ask the user to verify the official page.",
    "human_followup": "公式制度ページまたは募集要領で締切を確認してください。",
    "blocks_final_answer": false
  },
  {
    "gap_id": "gap_ex_no_hit_invoice",
    "gap_kind": "no_hit_not_absence",
    "severity": "review_required",
    "message": "The invoice source returned zero results for the sample number, but absence is not proven.",
    "message_ja": "インボイスsourceはサンプル番号で0件でしたが、登録なしの証明ではありません。",
    "affected_fields": ["sections.invoice_status"],
    "affected_records": ["invoice:T0000000000000"],
    "source_receipt_id": "src_ex_invoice_no_hit",
    "agent_instruction": "Say 'not confirmed in the checked source', not 'not registered'.",
    "human_followup": "T番号、法人/個人区分、最新公表情報を公式サイトで再確認してください。",
    "blocks_final_answer": false
  },
  {
    "gap_id": "gap_ex_enforcement_coverage",
    "gap_kind": "coverage_partial",
    "severity": "review_required",
    "message": "Connected enforcement sources are not comprehensive.",
    "message_ja": "接続済み行政処分sourceは網羅的ではありません。",
    "affected_fields": ["summary.enforcement_record_count"],
    "affected_records": ["houjin:0000000000000"],
    "source_receipt_id": null,
    "agent_instruction": "Do not say no enforcement or no risk.",
    "human_followup": "必要な所管庁・自治体・業法別sourceを追加確認してください。",
    "blocks_final_answer": false
  },
  {
    "gap_id": "gap_ex_compatibility_unknown",
    "gap_kind": "compatibility_unknown",
    "severity": "review_required",
    "message": "Combination rules between candidate programs are not verified.",
    "message_ja": "候補制度間の併用可否は確認できていません。",
    "affected_fields": ["sections.compatibility_matrix"],
    "affected_records": ["program:fixture_tokyo_energy_001"],
    "source_receipt_id": "src_ex_tokyo_program_001",
    "agent_instruction": "Do not call programs compatible unless a direct rule supports it.",
    "human_followup": "募集要領、交付要綱、窓口回答で同一経費併用可否を確認してください。",
    "blocks_final_answer": false
  },
  {
    "gap_id": "gap_ex_private_input_unverified",
    "gap_kind": "private_input_unverified",
    "severity": "review_required",
    "message": "CSV-derived business facts are user-provided derived facts and are not public-source verified.",
    "message_ja": "CSV由来の事業シグナルはユーザー提供データからの派生事実であり、公的sourceで検証されたものではありません。",
    "affected_fields": ["sections.business_signals"],
    "affected_records": ["csv_fact_capex_001"],
    "source_receipt_id": "src_ex_csv_profile_001",
    "agent_instruction": "Use this only as a review cue. Do not state accounting or tax correctness.",
    "human_followup": "元CSV、証憑、会計処理の確認は人間レビューで行ってください。",
    "blocks_final_answer": false
  },
  {
    "gap_id": "gap_ex_cost_preview_required",
    "gap_kind": "cost_preview_required",
    "severity": "blocking",
    "message": "Batch or CSV-derived processing requires cost preview before billable work.",
    "message_ja": "バッチまたはCSV由来処理は、課金作業前にcost previewが必要です。",
    "affected_fields": ["billing_metadata"],
    "affected_records": [],
    "source_receipt_id": null,
    "agent_instruction": "Call cost preview before executing billable packet generation.",
    "human_followup": "対象件数、max_units、max_jpy_inc_tax、monthly capを確認してください。",
    "blocks_final_answer": true
  }
]
```

### 4.3 `billing_metadata`

Single packet:

```json
{
  "pricing_version": "2026-05-15",
  "pricing_model": "metered_units",
  "unit_price_ex_tax_jpy": 3,
  "unit_price_inc_tax_jpy": 3.3,
  "billable_unit_type": "packet",
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
    "reason": "single public example packet"
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

Capped CSV/batch-ready packet:

```json
{
  "pricing_version": "2026-05-15",
  "pricing_model": "metered_units",
  "unit_price_ex_tax_jpy": 3,
  "unit_price_inc_tax_jpy": 3.3,
  "billable_unit_type": "subject",
  "billable_units": 6,
  "jpy_ex_tax": 18,
  "jpy_inc_tax": 19.8,
  "metered": true,
  "cost_preview_required": true,
  "cost_preview_endpoint": "POST /v1/cost/preview",
  "estimate_id": "est_public_example_batch_001",
  "free_quota_applicability": {
    "anonymous_3_req_per_day_ip": false,
    "applies_to_this_packet": false,
    "reason": "batch or CSV-derived work requires API key and cap"
  },
  "external_costs_included": false,
  "external_cost_notice": "External LLM, agent runtime, search, cloud, and MCP client costs are not included.",
  "cap": {
    "supports_hard_cap": true,
    "max_units": 20,
    "max_jpy_inc_tax": 66,
    "cap_remaining_jpy_inc_tax": 46.2,
    "on_cap_exceeded": "reject_before_billable_work"
  },
  "idempotency": {
    "idempotency_key_required": true,
    "reason": "batch retry should not double bill"
  },
  "no_charge_for": [
    "cost_preview",
    "auth_failure",
    "quota_exceeded",
    "cap_exceeded",
    "validation_error_before_billable_work",
    "server_error_without_successful_output"
  ]
}
```

Free preflight:

```json
{
  "pricing_version": "2026-05-15",
  "pricing_model": "free_preflight",
  "unit_price_ex_tax_jpy": 0,
  "unit_price_inc_tax_jpy": 0,
  "billable_unit_type": "preflight",
  "billable_units": 0,
  "jpy_ex_tax": 0,
  "jpy_inc_tax": 0,
  "metered": false,
  "cost_preview_required": false,
  "external_costs_included": false,
  "external_cost_notice": "External LLM, agent runtime, search, cloud, and MCP client costs are not included."
}
```

## 5. Public Page JSON-LD / Answer Box / CTA

### 5.1 JSON-LD Pattern

Each public packet page should include a single JSON-LD graph with `SoftwareApplication`, `Dataset`, `HowTo`, `FAQPage`, and `BreadcrumbList`. The page can also expose `mainEntity` as a `DefinedTerm` for the packet type.

Example for `application_strategy`:

```json
{
  "@context": "https://schema.org",
  "@graph": [
    {
      "@type": "SoftwareApplication",
      "@id": "https://jpcite.com/packets/application-strategy/#app",
      "name": "jpcite application_strategy packet",
      "applicationCategory": "DeveloperApplication",
      "operatingSystem": "MCP, REST API",
      "description": "Source-linked public program candidate packet for Japanese application planning. It does not decide eligibility or approval.",
      "offers": {
        "@type": "Offer",
        "price": "3.3",
        "priceCurrency": "JPY",
        "description": "Typical single packet unit price including tax. External LLM and runtime costs are not included."
      },
      "isAccessibleForFree": false,
      "featureList": [
        "source receipts",
        "known gaps",
        "cost preview",
        "MCP tool",
        "REST endpoint",
        "no request-time LLM call"
      ]
    },
    {
      "@type": "Dataset",
      "@id": "https://jpcite.com/packets/application-strategy/#sample-output",
      "name": "application_strategy public sample output",
      "description": "Synthetic JSON sample for an application strategy packet with source receipts and known gaps.",
      "license": "https://jpcite.com/legal/terms",
      "creator": {"@type": "Organization", "name": "jpcite"},
      "variableMeasured": [
        "packet_type",
        "source_receipts",
        "known_gaps",
        "billing_metadata",
        "human_review_required"
      ]
    },
    {
      "@type": "HowTo",
      "@id": "https://jpcite.com/packets/application-strategy/#howto",
      "name": "Use application_strategy from an AI agent",
      "step": [
        {"@type": "HowToStep", "name": "Preview cost for batch or CSV work"},
        {"@type": "HowToStep", "name": "Call createApplicationStrategyPacket or POST /v1/packets/application-strategy"},
        {"@type": "HowToStep", "name": "Preserve source_receipts, source_fetched_at, known_gaps, and billing_metadata"},
        {"@type": "HowToStep", "name": "Send final eligibility, tax, legal, audit, or credit judgment to human review"}
      ]
    },
    {
      "@type": "FAQPage",
      "@id": "https://jpcite.com/packets/application-strategy/#faq",
      "mainEntity": [
        {
          "@type": "Question",
          "name": "Does this packet decide grant eligibility?",
          "acceptedAnswer": {
            "@type": "Answer",
            "text": "No. It returns candidates, source receipts, and review questions. Final eligibility and approval judgment are out of scope."
          }
        },
        {
          "@type": "Question",
          "name": "What should an AI preserve when quoting this packet?",
          "acceptedAnswer": {
            "@type": "Answer",
            "text": "Preserve source_url, source_fetched_at, content_hash, corpus_snapshot_id, known_gaps, human_review_required, and billing_metadata."
          }
        }
      ]
    },
    {
      "@type": "BreadcrumbList",
      "@id": "https://jpcite.com/packets/application-strategy/#breadcrumbs",
      "itemListElement": [
        {"@type": "ListItem", "position": 1, "name": "Packets", "item": "https://jpcite.com/packets/"},
        {"@type": "ListItem", "position": 2, "name": "application_strategy", "item": "https://jpcite.com/packets/application-strategy/"}
      ]
    }
  ]
}
```

### 5.2 Answer Box Template

All packet pages should expose a short answer box near the top:

```text
Use jpcite [packet_type] when an AI agent needs Japanese public-data evidence before answering. The packet returns source receipts, source_fetched_at, content hashes, known gaps, billing metadata, and human-review boundaries. It does not perform request-time LLM reasoning and does not replace legal, tax, audit, application, credit, or professional judgment.
```

Japanese variant:

```text
jpcite [packet_type] は、AIが日本の公的データについて回答する前に使う根拠packetです。source receipts、取得時刻、content hash、known gaps、課金メタデータ、人間レビュー境界を返します。リクエスト時にLLM推論は行わず、税務・法務・監査・申請・与信などの最終判断は代替しません。
```

### 5.3 CTA Set

Primary CTAs for all packet pages:

| CTA label | Link target | Use when |
|---|---|---|
| `View sample JSON` | `#sample-output` | First proof action for agents and humans |
| `Preview units` | `/pricing/agent-cost/` or `POST /v1/cost/preview` docs | Any paid, batch, or CSV-adjacent action |
| `Connect MCP` | `/connect/` | Agent/dev top-level entry |
| `Use OpenAPI` | `/docs` or OpenAPI URL | REST/API implementation |
| `Issue API key` | `/dashboard/api-keys` | After cost/cap explanation |
| `Set spending cap` | `/dashboard/billing/cap` | After API key |
| `Try anonymous 3 req/day` | packet runner or docs | Single small proof call |

Forbidden CTAs:

- `Book a demo`
- `Talk to sales`
- `Request proposal`
- `Schedule consultation`
- `Enterprise inquiry`
- `Upgrade now`
- `Start saving money`

### 5.4 Public Page Layout Contract

Each packet page:

1. H1: exact packet name.
2. Answer box: 3-5 sentences, quotable by agents.
3. `When to use`.
4. `Do not use when`.
5. REST endpoint and MCP tool.
6. Sample input JSON.
7. Sample output JSON.
8. Source receipt table.
9. Known gaps table.
10. Billing metadata and cost preview.
11. Professional boundary.
12. CTA row.
13. JSON-LD graph.

Source receipt table columns:

| Column | Example |
|---|---|
| `source_receipt_id` | `src_ex_tokyo_program_001` |
| `source_name` | `東京都 公開制度ページ` |
| `source_url` | `https://www.tokyo.lg.jp/` |
| `source_fetched_at` | `2026-05-15T09:05:00+09:00` |
| `content_hash` | `sha256:tokyo-program-fixture` |
| `support_level` | `direct` |
| `used_in` | `claims.claim_as_001` |

Known gaps table columns:

| Column | Example |
|---|---|
| `gap_kind` | `deadline_missing` |
| `severity` | `review_required` |
| `message_ja` | `締切は検証済み文書から抽出できていません。` |
| `agent_instruction` | `Do not state the deadline as current.` |
| `blocks_final_answer` | `false` |

## 6. Implementation Acceptance Notes

Before implementation, align these with schema and tests:

- Six P0 samples validate against `jpcite.packet.v1`.
- CSV sample pages never expose raw CSV, transaction memo, counterparty, voucher ID, creator, bank, payroll, or personal information.
- `source_receipts` examples include hit, no-hit, public program, and CSV-derived receipts.
- `known_gaps` examples include `no_hit_not_absence`, `coverage_partial`, `private_input_unverified`, and `cost_preview_required`.
- Billing examples cover single packet, batch/cap, and free preflight.
- JSON-LD descriptions say "does not decide eligibility/approval" where relevant.
- Page CTA scan fails on sales-demo wording.
- Public examples are explicitly synthetic fixtures.

## 7. Open Questions for Adjacent Lanes

- Whether `csv_intake_quality` and `public_join` become first-class packet types or proof pages around `client_monthly_review`.
- Whether `source_url` for user CSV-derived receipts should use `jpcite://` internal URIs publicly, or a redacted HTTPS artifact URL.
- Whether `agent_routing_decision` remains free preflight in product pricing JSON.
- Whether sample fixture IDs should use schema-valid but impossible IDs, or explicit `fixture:` prefixes with schema exceptions for examples.
- Whether public examples should include downloadable JSON files under `data/packet_examples/` in addition to page-embedded snippets.
