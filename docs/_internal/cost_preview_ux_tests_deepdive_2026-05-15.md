# Cost preview UX / API / test detail deep dive

Date: 2026-05-15  
Owner lane: Cost preview UX / API / test detail  
Status: pre-implementation planning only. Do not treat this as shipped behavior until accepted.  
Scope: free cost preview request/response contract, CSV/packet/API/MCP estimate examples, UI and AI-agent wording, billing-safety test cases.  
Non-scope: runtime implementation, production code edits, Stripe implementation, final pricing approval.

## 0. Executive contract

AIエージェント推薦で課金に進むには、jpcite は「使う前に無料で費用が読める」「実行時に上限で止まる」「再送で二重課金しない」「jpcite費用と外部LLM費用が別」と機械可読に示す必要がある。

この文書のP0契約:

- `POST /v1/cost/preview` は無料で、匿名3 req/day/IPの実行枠を消費しない。
- previewは usage event、invoice item、billable execution record を作らない。
- paid broad execution は API key、hard cap、`Idempotency-Key` がそろうまで billable work を開始しない。
- cap判定は税込 `jpy_inc_tax_max` を基準にし、実行前の最大見積もりがcapを超える場合は課金前に拒否する。
- retry-sensitive POST は同一 `Idempotency-Key` + 同一 normalized payload なら同じ結果を返し、二重課金しない。
- 同一 `Idempotency-Key` + 異なる normalized payload は `409 idempotency_conflict` で、追加課金しない。
- external LLM、agent runtime、web search、MCP client、cloud、SaaS連携費用は jpcite 価格に含めない。
- previewレスポンスは UI と AI agent がそのまま使える `user_message_*` と `agent_message_*` を持つ。

Agentがユーザーへ言える最小文:

> jpcite の見積もりは無料です。この操作は最大 N units、税込 M 円の見込みです。外部LLMやエージェント実行環境の費用は含まれません。実行する場合は税込 cap を設定し、Idempotency-Key で再送時の二重課金を防ぎます。

## 1. State model

### 1.1 Flow states

| State | User-visible meaning | Billing effect | Required controls |
|---|---|---|---|
| `preview_requested` | 無料見積もりを作成中 | no charge | none; optional API key for account context |
| `preview_returned` | 最大費用と単位数が表示済み | no charge | preview id and TTL |
| `execution_requested` | 有料実行要求を受領 | no charge until gates pass | API key, cap, idempotency for paid broad execution |
| `preflight_rejected` | 入力/auth/quota/cap/idempotencyで実行前停止 | no charge | structured error |
| `billable_work_started` | すべての課金前gateを通過 | potential charge | execution lock and idempotency record |
| `billable_output_created` | billable output が確定 | charge allowed | usage event created once |
| `reconciled` | previewとactualを突合済み | final charge known | billing reconciliation in response |

### 1.2 Free preview vs anonymous free execution

| Surface | Free? | Consumes anonymous 3/day/IP? | API key required? | Records usage? | Notes |
|---|---:|---:|---:|---:|---|
| `POST /v1/cost/preview` | yes | no | no | no | Separate abuse throttle only. |
| `POST /v1/packets/preview` | yes | no | no | no | Packet-specific alias can call the same preview engine. |
| `decideAgentRouteForJpcite` | yes | no or control quota only | no | no billable usage | Routing/control surface. |
| anonymous small search/detail | yes within trial | yes | no | free execution counter only | 3 req/day/IP, JST reset. |
| paid packet/batch/CSV/watchlist/export | no | n/a | yes | yes after successful output | cap and idempotency required for retry-sensitive/broad paths. |

Do not use the phrase `無料で3回見積もり`. Correct phrase is:

> 匿名実行は3 req/日/IPです。cost preview は別枠で無料です。

## 2. Cost preview API contract

### 2.1 Endpoint

```http
POST /v1/cost/preview
Content-Type: application/json
X-API-Key: optional
X-Client-Tag: optional
```

Optional API key lets preview include account cap state. Absence of API key must not block preview. If an API key is invalid, the endpoint should either reject with `401 invalid_api_key` and no billing effect, or allow anonymous preview only when no key is supplied. Do not silently ignore an invalid key, because agents may otherwise believe a paid account cap was checked.

### 2.2 Request schema

```json
{
  "request_id": "req_client_01HV...",
  "input_mode": "csv|packet|api|mcp",
  "operation": {
    "channel": "rest|mcp|ui|cli|batch",
    "method": "POST",
    "endpoint": "/v1/packets/client-monthly-review",
    "mcp_tool": "createClientMonthlyReviewPacket",
    "packet_type": "client_monthly_review",
    "operation_id": "createClientMonthlyReviewPacket"
  },
  "pricing_context": {
    "pricing_version": "2026-05-15",
    "currency": "JPY",
    "tax_mode": "include_and_exclude",
    "locale": "ja-JP"
  },
  "scope": {
    "quantity": 12,
    "limit": 50,
    "subject_kind": "corporate_entity",
    "dedupe_scope": "single_request",
    "include_exports": false,
    "include_source_receipt_ledger": true
  },
  "csv": {
    "file_manifest": [
      {
        "client_file_id": "file_1",
        "filename": "clients.csv",
        "content_hash_sha256": "sha256:...",
        "row_count": 128,
        "header_profile": ["houjin_bangou", "client_name", "prefecture"]
      }
    ],
    "rows_sample": [
      {
        "row_number": 2,
        "houjin_bangou": "1234567890123",
        "client_name": "Example K.K."
      }
    ],
    "privacy_mode": "metadata_only|server_parse|client_declared_counts"
  },
  "subjects": [
    {
      "client_subject_id": "row-2",
      "subject_kind": "corporate_entity",
      "houjin_bangou": "1234567890123",
      "name": "Example K.K."
    }
  ],
  "cap": {
    "max_jpy_inc_tax": 300,
    "reject_if_estimate_exceeds_cap": true
  },
  "execution_intent": {
    "will_execute_after_preview": false,
    "requires_idempotency_key": true,
    "idempotency_key_planned": true
  },
  "agent_context": {
    "agent_name": "customer_support_agent",
    "user_visible": true,
    "external_llm_provider": "caller_managed",
    "external_llm_costs_included": false
  }
}
```

### 2.3 Required request fields by mode

| Mode | Required | Optional | Reject when |
|---|---|---|---|
| `csv` | `operation`, `csv.file_manifest` or server-parse upload reference, `scope.subject_kind` | `rows_sample`, `cap`, `client_declared_counts` | no row count/header info, unsupported privacy mode, executable paid request disguised as preview |
| `packet` | `operation.packet_type`, packet input summary or full packet input | `scope.quantity`, `cap` | unknown packet type, final judgment request, missing required packet discriminators |
| `api` | `operation.endpoint`, `operation.method`, `scope.quantity` or endpoint-specific input | `cap`, `include_exports` | endpoint not public/billable, admin/internal endpoint, unsupported method |
| `mcp` | `operation.mcp_tool`, tool input summary | `operation.rest_equivalent`, `cap` | unknown tool, tool disabled/gated, tool cannot be estimated |

### 2.4 Preview response schema

```json
{
  "preview_id": "cpv_01JY...",
  "created_at": "2026-05-15T07:00:00Z",
  "expires_at": "2026-05-15T07:15:00Z",
  "free_preview": true,
  "preview_consumes_anonymous_quota": false,
  "preview_records_billable_usage": false,
  "operation": {
    "input_mode": "csv",
    "channel": "rest",
    "endpoint": "/v1/packets/client-monthly-review",
    "mcp_tool": "createClientMonthlyReviewPacket",
    "packet_type": "client_monthly_review"
  },
  "pricing": {
    "pricing_version": "2026-05-15",
    "pricing_model": "metered_units",
    "currency": "JPY",
    "unit_price_ex_tax_jpy": 3,
    "unit_price_inc_tax_jpy": 3.3,
    "tax_note": "Stripe invoice/tax calculation is final."
  },
  "estimate": {
    "confidence": "exact_after_csv_preview",
    "billable_unit_type": "billable_subject",
    "unit_formula": "count(unique accepted resolved subjects)",
    "predicted_units_min": 81,
    "predicted_units_max": 84,
    "predicted_units_display": "81-84",
    "jpy_ex_tax_min": 243,
    "jpy_ex_tax_max": 252,
    "jpy_inc_tax_min": 267.3,
    "jpy_inc_tax_max": 277.2,
    "rounding_policy": "display rounds up to whole JPY; billing stores decimal precision"
  },
  "breakdown": [
    {
      "label": "client_monthly_review",
      "billable_unit_type": "billable_subject",
      "predicted_units": 81,
      "jpy_inc_tax": 267.3,
      "billable_when": "accepted resolved subject returns a review packet",
      "not_billed_when": ["duplicate row", "invalid row", "unresolved identity", "no billable output"]
    },
    {
      "label": "source_receipt_ledger",
      "billable_unit_type": "source_receipt_set",
      "predicted_units_max": 3,
      "jpy_inc_tax_max": 9.9,
      "billable_when": "requested ledger artifact is created"
    }
  ],
  "input_reconciliation": {
    "uploaded_rows": 128,
    "accepted_rows": 96,
    "duplicate_rows": 15,
    "invalid_rows": 7,
    "unresolved_rows": 10,
    "unique_billable_subjects": 81,
    "preview_parse_complete": true
  },
  "cap_check": {
    "cap_required_for_paid_execution": true,
    "provided_cap_jpy_inc_tax": 300,
    "would_execute_under_cap": true,
    "cap_basis": "estimate.jpy_inc_tax_max",
    "recommended_cap_jpy_inc_tax": 278,
    "monthly_cap_status": {
      "api_key_supplied": true,
      "monthly_cap_jpy_inc_tax": 5000,
      "monthly_spent_jpy_inc_tax": 1210.5,
      "monthly_remaining_jpy_inc_tax": 3789.5,
      "would_fit_monthly_cap": true
    }
  },
  "execution_requirements": {
    "api_key_required": true,
    "idempotency_key_required": true,
    "cost_cap_required": true,
    "required_headers": ["X-API-Key", "Idempotency-Key", "X-Cost-Cap-JPY"],
    "required_body_fields": []
  },
  "quota_relationship": {
    "anonymous_execution_quota": {
      "limit": 3,
      "window": "day",
      "reset_timezone": "Asia/Tokyo",
      "applies_to_preview": false
    },
    "preview_abuse_throttle": {
      "applies": true,
      "billable": false
    }
  },
  "not_included": [
    "external LLM input/output/reasoning/cache costs",
    "agent runtime or MCP client costs",
    "external web search costs",
    "customer cloud, storage, queue, or SaaS integration costs",
    "professional review or filing fees"
  ],
  "billing_safety": {
    "no_charge_for_preview": true,
    "no_charge_before_successful_billable_output": true,
    "no_charge_for_validation_error": true,
    "no_charge_for_auth_error": true,
    "no_charge_for_cap_reject": true,
    "idempotency_prevents_double_charge": true
  },
  "messages": {
    "ui_summary_ja": "見積もりは無料です。最大84 units、税込278円の見込みです。実行にはAPI key、税込cap、Idempotency-Keyが必要です。",
    "ui_summary_en": "This preview is free. Estimated maximum: 84 units, JPY 278 including tax. Execution requires an API key, tax-included cap, and Idempotency-Key.",
    "agent_message_ja": "jpcite費用は最大税込278円です。外部LLMやエージェント実行環境の費用は含まれません。税込300円cap内で実行できます。",
    "agent_message_en": "Estimated jpcite cost is up to JPY 278 including tax. External LLM and agent runtime costs are not included. This can run under the JPY 300 cap."
  },
  "agent_recommendation": {
    "decision": "can_execute_under_cap",
    "safe_to_recommend_paid_execution": true,
    "explain_to_user": [
      "Preview was free and did not consume anonymous execution quota.",
      "The request cap is above the maximum estimate.",
      "Idempotency is required to prevent duplicate charges on retry.",
      "External LLM costs are separate."
    ]
  }
}
```

### 2.5 Error response contract

All preview and execution gate errors need `billing_effect`. Agents must not infer billing behavior from HTTP status alone.

```json
{
  "error": {
    "code": "cost_cap_exceeded",
    "message": "Predicted cost exceeds the provided cap.",
    "user_message_ja": "見積もり上限が指定capを超えたため、課金前に停止しました。",
    "agent_message_ja": "この実行はcap内に収まりません。範囲を減らすか、ユーザー承認後にcapを上げてください。",
    "retryable": false,
    "billing_effect": "not_billed",
    "usage_event_created": false,
    "invoice_item_created": false,
    "cap": {
      "provided_cap_jpy_inc_tax": 100,
      "predicted_jpy_inc_tax_max": 277.2
    },
    "documentation": "https://jpcite.com/docs/error_handling#cost_cap_exceeded"
  }
}
```

## 3. Estimate confidence levels

| Confidence | Meaning | Use cases | Agent wording |
|---|---|---|---|
| `exact_fixed` | Units are known before execution | single packet, simple API detail | `この操作は1 unitです` |
| `exact_after_csv_preview` | CSV was parsed/deduped; accepted subjects known | CSV monthly review, watchlist import | `CSV解析後の見積もりです` |
| `bounded_by_limit` | Caller limit caps maximum; actual may be lower | search with `limit`, funding records | `最大N件までの見積もりです` |
| `conservative_upper_bound` | Worst-case formula used for cap | pairwise compatibility, fanout | `実行前上限判定用の保守的見積もりです` |
| `requires_execution_reconciliation` | Actual billable units depend on no-hit/result quality | mixed subject batch | `実請求は成功したbillable outputで再計算されます` |
| `not_estimable` | Tool cannot be safely priced | internal/gated/unsupported | paid execution must be blocked until contract exists |

If confidence is `not_estimable`, `safe_to_recommend_paid_execution` must be false.

## 4. Examples by surface

### 4.1 CSV preview example

Scenario: advisor uploads a client CSV for monthly public review.

Request:

```json
{
  "input_mode": "csv",
  "operation": {
    "channel": "ui",
    "endpoint": "/v1/packets/client-monthly-review",
    "packet_type": "client_monthly_review"
  },
  "csv": {
    "file_manifest": [
      {
        "client_file_id": "upload_20260515_001",
        "filename": "clients_may.csv",
        "row_count": 128,
        "header_profile": ["client_id", "houjin_bangou", "invoice_number", "client_name"]
      }
    ],
    "privacy_mode": "server_parse"
  },
  "scope": {
    "subject_kind": "corporate_entity",
    "include_source_receipt_ledger": false
  },
  "cap": {
    "max_jpy_inc_tax": 300,
    "reject_if_estimate_exceeds_cap": true
  }
}
```

Preview result:

| Field | Value |
|---|---:|
| uploaded rows | 128 |
| accepted rows | 96 |
| duplicate rows | 15 |
| invalid rows | 7 |
| unresolved rows | 10 |
| unique billable subjects | 81 |
| unit price | 3 JPY ex-tax / 3.30 JPY inc-tax |
| predicted max | 81 units / 267.3 JPY inc-tax |
| display rounded | 税込268円 |
| cap check | pass under 300 JPY |
| charged now | 0 JPY |

UI copy:

> 見積もりは無料です。128行中、課金対象候補は81件です。実行時の最大見込みは81 units、税込268円です。重複15行、形式エラー7行、未解決10行は課金対象外です。

Agent copy:

> CSVは解析済みです。jpcite費用は最大税込268円で、指定cap 300円内に収まります。外部LLM費用は含まれません。実行する場合はAPI key、Idempotency-Key、税込capを付けます。

Execution reconciliation expectation:

```json
{
  "billing_reconciliation": {
    "preview_id": "cpv_...",
    "predicted_units_max": 81,
    "actual_billable_units": 76,
    "not_billed": {
      "no_hit_subjects": 4,
      "output_suppressed_by_validation": 1
    },
    "charged_jpy_inc_tax": 250.8,
    "external_costs_included": false
  }
}
```

### 4.2 Packet preview example

Scenario: AI agent wants a company public baseline packet.

Request:

```json
{
  "input_mode": "packet",
  "operation": {
    "channel": "rest",
    "endpoint": "/v1/packets/company-public-baseline",
    "packet_type": "company_public_baseline"
  },
  "subjects": [
    {
      "subject_kind": "corporate_entity",
      "houjin_bangou": "1234567890123"
    }
  ],
  "cap": {
    "max_jpy_inc_tax": 10,
    "reject_if_estimate_exceeds_cap": true
  }
}
```

Preview result:

```json
{
  "free_preview": true,
  "preview_consumes_anonymous_quota": false,
  "estimate": {
    "confidence": "exact_fixed",
    "billable_unit_type": "subject",
    "predicted_units_min": 1,
    "predicted_units_max": 1,
    "jpy_ex_tax_max": 3,
    "jpy_inc_tax_max": 3.3
  },
  "cap_check": {
    "provided_cap_jpy_inc_tax": 10,
    "would_execute_under_cap": true
  },
  "messages": {
    "ui_summary_ja": "見積もりは無料です。この会社確認は1 unit、税込4円以下の見込みです。",
    "agent_message_ja": "jpcite費用は1 unit、税込3.3円です。実行cap 10円内です。外部LLM費用は別です。"
  }
}
```

UI copy:

> この見積もりは無料です。法人が解決でき、packetが返った場合のみ1 unitです。no hit、入力エラー、cap超過、認証エラーは課金されません。

### 4.3 API preview example

Scenario: developer plans `POST /v1/programs/batch` for 40 program IDs, with possible duplicates.

Request:

```json
{
  "input_mode": "api",
  "operation": {
    "channel": "rest",
    "method": "POST",
    "endpoint": "/v1/programs/batch",
    "operation_id": "batchGetPrograms"
  },
  "scope": {
    "quantity": 40,
    "dedupe_scope": "single_request"
  },
  "subjects": [
    {"subject_kind": "program", "program_id": "UNI-TOKYO-001"},
    {"subject_kind": "program", "program_id": "UNI-TOKYO-001"}
  ],
  "cap": {
    "max_jpy_inc_tax": 120,
    "reject_if_estimate_exceeds_cap": true
  }
}
```

Preview result:

| Field | Value |
|---|---:|
| input IDs | 40 |
| duplicate IDs detected in supplied subjects | 1 |
| predicted max units | 39 |
| formula | returned program details after dedupe |
| estimated max inc-tax | 128.7 JPY |
| cap | 120 JPY |
| decision | reject if executed unchanged |

Error-like preview decision:

```json
{
  "agent_recommendation": {
    "decision": "reduce_scope_or_raise_cap",
    "safe_to_recommend_paid_execution": false
  },
  "cap_check": {
    "would_execute_under_cap": false,
    "provided_cap_jpy_inc_tax": 120,
    "recommended_cap_jpy_inc_tax": 129
  },
  "messages": {
    "ui_summary_ja": "最大見積もりが指定capを超えています。39 units、税込129円見込みに対し、capは120円です。",
    "agent_message_ja": "このままではcap超過で実行前に停止します。件数を減らすか、ユーザー承認後に税込129円以上のcapを設定してください。"
  }
}
```

### 4.4 MCP preview example

Scenario: MCP client calls `previewCost` before `createApplicationStrategyPacket`.

MCP tool call:

```json
{
  "tool": "previewCost",
  "arguments": {
    "input_mode": "mcp",
    "operation": {
      "mcp_tool": "createApplicationStrategyPacket",
      "rest_equivalent": "POST /v1/packets/application-strategy",
      "packet_type": "application_strategy"
    },
    "scope": {
      "quantity": 1,
      "subject_kind": "applicant_profile"
    },
    "cap": {
      "max_jpy_inc_tax": 10
    },
    "agent_context": {
      "user_visible": true,
      "external_llm_provider": "caller_managed",
      "external_llm_costs_included": false
    }
  }
}
```

MCP result:

```json
{
  "content": [
    {
      "type": "text",
      "text": "見積もりは無料です。application_strategy は1 profile_packet、税込3.3円の見込みです。外部LLM費用は含まれません。"
    }
  ],
  "structuredContent": {
    "preview_id": "cpv_...",
    "free_preview": true,
    "preview_consumes_anonymous_quota": false,
    "estimate": {
      "billable_unit_type": "profile_packet",
      "predicted_units_max": 1,
      "jpy_inc_tax_max": 3.3
    },
    "execution_requirements": {
      "api_key_required": true,
      "idempotency_key_required": true,
      "cost_cap_required": true
    },
    "not_included": [
      "external LLM costs",
      "agent runtime costs",
      "MCP client/platform costs"
    ],
    "agent_recommendation": {
      "decision": "can_execute_under_cap",
      "safe_to_recommend_paid_execution": true
    }
  }
}
```

Agent should say:

> jpcite 側は税込3.3円見込みで、見積もりは無料でした。あなたが使っているLLM/エージェント環境の費用は別です。実行してよければ税込10円capで1回だけ呼びます。

## 5. UI wording

### 5.1 Primary labels

| Context | Japanese | English |
|---|---|---|
| Preview button | `無料で見積もる` | `Preview cost for free` |
| Execute button after pass | `cap内で実行` | `Run within cap` |
| Execute button after fail | `範囲を減らす` | `Reduce scope` |
| Cap input label | `実行cap（税込円）` | `Execution cap, JPY inc. tax` |
| Idempotency status | `再送時の二重課金防止: 有効` | `Duplicate-charge protection: on` |
| External cost note | `外部LLM・エージェント実行費用は含まれません` | `External LLM and agent runtime costs are not included` |
| Anonymous note | `匿名実行は3 req/日/IP。見積もりは別枠で無料です` | `Anonymous execution is 3 req/day/IP. Preview is free and separate.` |

### 5.2 Preview card copy

Pass:

> 見積もりは無料です。最大84 units、税込278円の見込みです。指定cap 300円内で実行できます。外部LLM・エージェント実行費用は含まれません。

Cap fail:

> 最大見積もりがcapを超えています。見込みは税込278円、指定capは100円です。このまま実行しても課金前に停止します。

No API key:

> 見積もりは無料で確認できます。有料実行にはAPI key、実行cap、Idempotency-Keyが必要です。

Anonymous confusion guard:

> 匿名実行は3 req/日/IPまでです。cost preview はこの実行枠を消費しません。

Retry safety:

> ネットワーク再送に備えて Idempotency-Key を使います。同じキーと同じ内容の再送では二重課金しません。

Actual lower than preview:

> 実行結果は見積もりより少ない76 unitsでした。no hit 4件と検証除外1件は課金対象外です。

### 5.3 UI anti-copy

| Do not say | Use instead |
|---|---|
| `無料で3回見積もれます` | `見積もりは無料です。匿名実行は3 req/日/IPです` |
| `AI費用込み` | `jpcite費用のみ。外部LLM費用は含まれません` |
| `最大100円まで課金します` | `税込cap 100円を超える場合は課金前に停止します` |
| `エラー時は課金されません` | `validation/auth/quota/cap/server failure/no billable output は課金されません` |
| `重複請求を保証します` | `同一Idempotency-Keyと同一payloadの再送では追加課金しません` |
| `no hitなので存在しません` | `no hit は不存在証明ではありません。課金対象外です` |

## 6. AI agent wording

### 6.1 Before preview

> 有料実行の前に、jpcite の無料 cost preview を呼びます。これは匿名実行3回/日の枠を消費せず、課金も発生しません。

### 6.2 Preview pass

> 見積もり結果: jpcite費用は最大84 units、税込278円です。指定cap 300円内に収まります。外部LLM、MCPクライアント、エージェント実行環境の費用は含まれません。実行時はAPI key、Idempotency-Key、税込capを付けます。

### 6.3 Preview over cap

> 見積もり結果: 最大税込278円で、指定cap 100円を超えます。このままではjpciteが課金前に停止します。対象件数を減らすか、capを上げる承認が必要です。

### 6.4 Missing paid controls

> この操作は有料または広範囲実行に当たるため、API key、税込cap、Idempotency-Key が必要です。どれかが欠ける場合、jpciteは課金前に拒否します。

### 6.5 Retry

> 通信エラー時は同じ Idempotency-Key で再送します。同じ内容なら既存結果を返し、追加課金しません。内容を変える場合は新しいキーを使います。

### 6.6 External LLM separation

> この見積もりはjpciteのデータ取得・packet生成費用だけです。私が使うLLMのトークン、推論、検索、実行環境、クラウド費用は別です。

### 6.7 Anonymous user

> 匿名の小さな実行は3 req/日/IPまでです。ただしcost previewは別枠で無料です。継続利用やcap管理にはAPI keyが必要です。

### 6.8 No-hit

> no hit は「存在しない」証明ではありません。今回のjpcite課金対象にもなりません。必要なら条件を変えて再確認します。

## 7. Execution request after preview

Paid execution should accept a `preview_id`, but must not rely on it alone for billing safety. The server must recompute or validate the normalized payload against preview before billable work.

```http
POST /v1/packets/client-monthly-review
X-API-Key: sk_live_...
Idempotency-Key: 01JY-CLIENT-MONTHLY-MAY
X-Cost-Cap-JPY: 300
Content-Type: application/json
```

```json
{
  "preview_id": "cpv_01JY...",
  "preview_payload_hash": "sha256:...",
  "client_tag": "advisor-a/client-may-review",
  "input": {
    "csv_upload_id": "upl_..."
  },
  "cap": {
    "max_jpy_inc_tax": 300
  }
}
```

Preflight order:

1. Validate API key and account state.
2. Validate request shape and supported operation.
3. Validate idempotency key format and lookup existing record.
4. Normalize payload and compare with existing idempotency payload, if any.
5. Compute conservative max estimate or validate unexpired preview.
6. Check request cap using `estimate.jpy_inc_tax_max`.
7. Check monthly/customer cap using current remaining balance and max estimate.
8. Create execution lock/idempotency record.
9. Start billable work.
10. Create usage event only after successful billable output.
11. Reconcile actual billed units and release lock.

## 8. Billing-safety test cases

### 8.1 Preview is free

| ID | Case | Setup | Expected |
|---|---|---|---|
| CP-001 | Anonymous preview does not consume 3/day | IP has 0 anonymous executions; call preview 10 times | execution quota remains 0/3; preview may hit separate abuse throttle; no usage event |
| CP-002 | Preview with API key does not bill | valid API key; preview packet | invoice item count unchanged; usage event count unchanged |
| CP-003 | Preview over cap does not bill | cap 1 JPY, estimate 3.3 JPY | response says cannot execute; no usage/invoice |
| CP-004 | Preview parse validation error does not bill | malformed CSV metadata | `400 validation_error`; billing_effect `not_billed` |
| CP-005 | Preview returns external cost exclusion | any preview | `external_costs_included=false` and `not_included[]` present |
| CP-006 | Preview is not allowed to execute | preview request includes execute=true or side-effect instruction | reject or ignore execution intent; no billable output |

### 8.2 Anonymous quota separation

| ID | Case | Setup | Expected |
|---|---|---|---|
| AQ-001 | Preview after anonymous quota exhausted | IP has used 3/3 free executions | preview still allowed unless preview throttle hit; message distinguishes quotas |
| AQ-002 | Anonymous execution after previews | IP called preview 20 times, no execution | first anonymous execution still allowed |
| AQ-003 | Anonymous execution quota hit does not bill | IP calls 4th anonymous execution | `429 anonymous_quota_exceeded`; no usage invoice; preview remains separate |
| AQ-004 | UI does not combine quota text | render preview card for anonymous user | copy says `匿名実行は3 req/日/IP。見積もりは別枠で無料` |

### 8.3 Cap enforcement

| ID | Case | Setup | Expected |
|---|---|---|---|
| CAP-001 | Missing cap on paid broad execution | API key present, no `X-Cost-Cap-JPY` | `400 cost_cap_required`; no billable work |
| CAP-002 | Cap below estimate | estimate 277.2, cap 100 | `402 cost_cap_exceeded`; no usage/invoice |
| CAP-003 | Cap equal to estimate | estimate 277.2, cap 277.2 | pass preflight; actual charge cannot exceed cap |
| CAP-004 | Cap uses inc-tax basis | ex-tax 252, inc-tax 277.2, cap 260 | reject because inc-tax exceeds cap |
| CAP-005 | Monthly cap reached | account remaining 50, request max 60 | `402 cap_reached` or agreed enum; no work |
| CAP-006 | Actual lower than estimate | estimate 84 units, actual 76 | charge 76 units; reconciliation shows not-billed reasons |
| CAP-007 | Actual tries to exceed estimate | estimate 84 units, runtime finds 90 | stop at cap/estimate boundary or require new approval; never silently bill 90 |
| CAP-008 | Negative/zero cap | cap 0 or -1 | validation reject; no work |
| CAP-009 | Non-numeric cap header | `X-Cost-Cap-JPY: ten` | validation reject; no work |
| CAP-010 | Body/header cap mismatch | header 100, body 300 | deterministic rule: reject mismatch; no work |

### 8.4 Idempotency and double charge

| ID | Case | Setup | Expected |
|---|---|---|---|
| IDEM-001 | Missing idempotency key | paid POST CSV execution | `428 idempotency_key_required`; no billable work |
| IDEM-002 | Same key same payload retry after success | first call billed 76 units; retry same normalized payload | same response or replay envelope; usage event count remains 1 |
| IDEM-003 | Same key same payload retry while running | duplicate request arrives before completion | wait/poll or `202 in_progress`; no second execution |
| IDEM-004 | Same key different payload | same key, changed CSV hash | `409 idempotency_conflict`; no new charge |
| IDEM-005 | Same key same semantic payload different field order | JSON keys reordered | normalized hash same; no conflict; no double charge |
| IDEM-006 | Same key same CSV filename but different hash | modified file content | conflict; no work |
| IDEM-007 | Network timeout after billing commit | client retries same key | returns committed result; no second usage event |
| IDEM-008 | Server error before billable output | fail before output; retry same key | either retry allowed with same key or previous failed state with no charge; never duplicate |
| IDEM-009 | Idempotency key reused after TTL with same payload | beyond retention policy | documented behavior; either replay if retained or require new key; no hidden duplicate without warning |
| IDEM-010 | Parallel identical requests with same key | two workers receive same request | one execution lock; one usage event |

### 8.5 Misbilling and no-charge cases

| ID | Case | Setup | Expected |
|---|---|---|---|
| BILL-001 | Auth failure | invalid API key on paid execution | `401`; no usage/invoice |
| BILL-002 | Validation failure | missing required packet input | `400`; no usage/invoice |
| BILL-003 | Unsupported final judgment request | asks for tax/legal/credit final decision | reject or safe packet only; no paid final-judgment charge |
| BILL-004 | No-hit subject | company/program not found | no billable unit unless explicit paid no-hit proof product exists |
| BILL-005 | Duplicate CSV rows | same corporate number appears 5 times | one predicted subject; one billable unit max |
| BILL-006 | Unresolved CSV identity | name-only below confidence | not billable; listed in rejected/unresolved rows |
| BILL-007 | Partial CSV success | 100 accepted, 10 no-hit | bill only successful billable outputs; reconcile no-hit |
| BILL-008 | Export creation fails after packets | packet charges only if packets succeeded; export unit not charged |
| BILL-009 | Source receipt ledger missing | requested ledger for missing artifact | no ledger charge |
| BILL-010 | Internal retry from worker | worker retries data fetch | customer sees one billable output and one usage event only |
| BILL-011 | Duplicate webhook/invoice event | billing event replayed | idempotent invoice/usage processing; no duplicate invoice item |
| BILL-012 | Decimal rounding | 3.3 * 81 = 267.3 | stored exact decimal; display rounds consistently; cap compares unrounded inc-tax decimal |

### 8.6 External cost separation

| ID | Case | Setup | Expected |
|---|---|---|---|
| EXT-001 | Preview contains external cost false | any preview | `external_costs_included=false` present |
| EXT-002 | Execution response contains external cost false | paid success | billing metadata repeats exclusion |
| EXT-003 | UI displays external cost note | preview card | note visible near estimate and execute button |
| EXT-004 | Agent text includes external cost note | MCP preview | agent message says LLM/runtime costs are separate |
| EXT-005 | Request-time LLM not performed | packet response | `request_time_llm_call_performed=false` where applicable |
| EXT-006 | Caller passes external LLM provider | agent_context has provider | response does not estimate or guarantee provider bill |

### 8.7 UI behavior tests

| ID | Case | Expected |
|---|---|---|
| UI-001 | Preview button before execute | execute disabled until preview for broad paid workflow |
| UI-002 | Cap input visible | label says `実行cap（税込円）` |
| UI-003 | Over-cap state | execute button disabled or changed to reduce-scope; copy says課金前停止 |
| UI-004 | Under-cap state | execute button says `cap内で実行` |
| UI-005 | Missing key state | preview allowed; paid execute prompts API key |
| UI-006 | Anonymous note | does not imply preview consumes anonymous trial |
| UI-007 | Reconciliation shown | actual units, not-billed counts, charged amount visible after execution |
| UI-008 | Retry message | duplicate-charge protection shown when idempotency is active |
| UI-009 | Long CSV counts | numbers remain readable and do not overflow preview card |
| UI-010 | Japanese/English parity | core safety statements exist in both locales |

### 8.8 Agent behavior tests

| ID | Case | Expected |
|---|---|---|
| AG-001 | Agent recommends preview before paid CSV | calls `previewCost` before execution |
| AG-002 | Agent does not call paid endpoint over cap | stops and asks user to reduce scope or approve higher cap |
| AG-003 | Agent includes external cost separation | user-facing response distinguishes jpcite vs LLM costs |
| AG-004 | Agent preserves no-hit nuance | no-hit not described as absence |
| AG-005 | Agent uses idempotency on retry | retry has same key and same payload |
| AG-006 | Agent changes key after payload change | modified request gets new idempotency key after user approval |
| AG-007 | Agent handles `idempotency_conflict` | does not retry unchanged; explains conflict |
| AG-008 | Agent handles monthly cap reached | suggests raising monthly cap or waiting, not repeated retries |
| AG-009 | Agent does not promise exact external LLM savings | may say context reduction can help, not guaranteed provider bill |
| AG-010 | Agent routes anonymous user correctly | says preview is free and execution trial is separate 3/day/IP |

## 9. Observability and audit fields

Every preview should be traceable without becoming a billable event.

Preview log:

```json
{
  "event_type": "cost_preview_created",
  "preview_id": "cpv_...",
  "created_at": "2026-05-15T07:00:00Z",
  "api_key_hash": "optional",
  "anonymous_ip_hash": "optional",
  "operation_id": "createClientMonthlyReviewPacket",
  "input_mode": "csv",
  "predicted_units_max": 84,
  "jpy_inc_tax_max": 277.2,
  "preview_consumes_anonymous_quota": false,
  "usage_event_created": false,
  "invoice_item_created": false
}
```

Execution usage event:

```json
{
  "event_type": "billable_usage_created",
  "usage_event_id": "use_...",
  "execution_id": "exe_...",
  "preview_id": "cpv_...",
  "idempotency_key_hash": "sha256:...",
  "normalized_payload_hash": "sha256:...",
  "billable_unit_type": "billable_subject",
  "actual_billable_units": 76,
  "unit_price_inc_tax_jpy": 3.3,
  "charged_jpy_inc_tax": 250.8,
  "external_costs_included": false
}
```

Audit invariant:

```text
count(usage_event where preview_id = cpv) can be 0 or 1 per execution id,
never >1 for the same idempotency key + normalized payload hash.
```

## 10. Acceptance checklist

- [ ] `POST /v1/cost/preview` is available in REST, OpenAPI agent spec, MCP `previewCost`, and UI.
- [ ] Preview response always states free/no anonymous quota/no billable usage.
- [ ] Preview includes ex-tax and inc-tax prices, unit formula, confidence, cap check, and external cost exclusion.
- [ ] Paid broad execution rejects missing API key, cap, and idempotency before work.
- [ ] Cap comparison uses `estimate.jpy_inc_tax_max`.
- [ ] Same idempotency key + same normalized payload cannot create a second usage event.
- [ ] Same idempotency key + different normalized payload returns `409 idempotency_conflict`.
- [ ] CSV preview shows uploaded rows, accepted rows, duplicates, invalid/unresolved rows, unique billable subjects, and exact formula.
- [ ] no-hit/not-found/validation/auth/quota/cap/server failure paths are marked not billed.
- [ ] UI and agent copy distinguish free preview from anonymous free execution.
- [ ] UI and agent copy repeat external LLM/runtime cost exclusion before paid execution.
- [ ] Execution response includes reconciliation from predicted to actual units.

## 11. Open decisions

| Decision | Recommendation | Reason |
|---|---|---|
| Preview TTL | 15 minutes | Long enough for user confirmation; short enough for cap/account drift. |
| Cap unit | JPY inc-tax | Users reason about final yen amount; response still includes ex-tax. |
| Display rounding | Round up to whole JPY for UI | Avoid under-displaying cost; store decimal precision. |
| Invalid API key on preview | Reject instead of anonymous fallback | Prevent false belief that account cap was checked. |
| Body/header cap mismatch | Reject | Avoid ambiguous enforcement. |
| Preview abuse throttle | Separate non-billing throttle | Protect service while preserving free preview promise. |
| Idempotency retention | At least 24h for paid POST; longer preferred for CSV/batch | Covers retries and job polling. |

## 12. Final P0 invariant

No AI agent should be able to move from recommendation to paid jpcite execution without being able to answer these five questions from structured fields:

1. Is this preview free and separate from anonymous execution quota?
2. What is the maximum jpcite cost in units and JPY inc-tax?
3. Does the request fit the user-approved cap and monthly cap?
4. Will retrying the request avoid duplicate charges?
5. Are external LLM/agent/runtime costs excluded from this estimate?

If any answer is missing, the agent should not recommend paid execution.
