# R25 (P0) — Evidence + ClaimRef + SourceReceipt + KnownGap

> AI agent 向け recipe。jpcite の artifact body は **claim** (主張) と **evidence** (証拠) を分離して持ち、各 evidence は **source_receipt** (一次資料の検証可能 receipt) と chain される。1 つの claim に evidence が無い場合は **known_gap** artifact として gap_artifact_only policy で出力。agent は `support_state` の 4 値を見て、user に「裏付け強度」を伝えるべき。

- **Audience**: AI agent builder + 監査要件のある cohort (税理士 / 会計士 / financial_institution / 司法書士)
- **Cost**: evidence/receipt 自体は packet 内 inline、追加課金なし
- **Sensitive**: §52 / §72 / §1 / §47条の2 すべての sensitive surface で evidence の `source_url` + `extracted_at` が必須

## TL;DR

```
claim ─→ evidence(N) ─→ source_receipt ─→ primary source URL
   │       │
   │       └─ support_state: supported / partial / contested / absent
   │
   └─ evidence 0 件 → known_gap artifact (policy_state=gap_artifact_only)
```

4 元構造 (claim / evidence / source_receipt / known_gap) は `schemas/jpcir/` に schema 化され、agent_runtime/contracts.py の Pydantic envelope と round-trip 整合。

## 4 元の役割

### 1. ClaimRef

artifact が主張する 1 つの命題への参照。

```json
{
  "claim_id": "claim_app_strategy_aichi_mfg_001",
  "claim_text": "愛知県のものづくり補助金 14次公募は 2026-06-30 締切",
  "claim_kind": "factual_deadline",  // factual_deadline / eligibility / amount_range / regulatory_obligation / ...
  "claim_locator": {
    "outcome_contract_id": "application_strategy",
    "artifact_path": "$.programs[0].deadline_text"
  }
}
```

schema: `schemas/jpcir/claim_ref.schema.json`

### 2. Evidence

claim を支える 1 件の証拠。

```json
{
  "evidence_id": "ev_aichi_mfg_14ko_url_001",
  "claim_id": "claim_app_strategy_aichi_mfg_001",
  "evidence_type": "primary_source_url",   // 6 値 (下記)
  "source_receipt_id": "rcp_aichi_mfg_14ko_001",
  "support_state": "supported",            // 4 値 (下記)
  "confidence": "high",
  "extracted_at": "2026-05-16T10:00:00+09:00",
  "extracted_by": "scripts/cron/refresh_sources.py"
}
```

schema: `schemas/jpcir/evidence.schema.json` (Wave 50 で追加された新規 Pydantic model)

### 3. SourceReceipt

evidence の出元一次資料を一意特定する receipt。

```json
{
  "receipt_id": "rcp_aichi_mfg_14ko_001",
  "source_url": "https://www.pref.aichi.jp/.../monodzukuri-14ko.pdf",
  "source_authority": "愛知県 産業労働部",
  "source_kind": "prefecture_official_pdf",
  "fetched_at": "2026-05-16T03:14:22+09:00",
  "content_sha256": "sha256:abc...",
  "http_status": 200,
  "license": "gov_standard",          // gov_standard / pdl_v1.0 / cc_by_4.0 / e-gov / proprietary 等
  "snapshot_ref": "r2://jpcite-snapshots/2026-05-16/.../monodzukuri-14ko.pdf"
}
```

schema: `schemas/jpcir/source_receipt.schema.json`

### 4. KnownGap

evidence 0 件 (corpus 未対応 / 一次資料 dead URL) の claim を **明示的に gap として出す** artifact。

```json
{
  "gap_id": "gap_app_strategy_aichi_mfg_amount_001",
  "claim_id": "claim_app_strategy_aichi_mfg_amount_001",
  "gap_kind": "primary_source_dead_url",  // missing / dead_url / corpus_lag / aggregator_only / ...
  "policy_state": "gap_artifact_only",     // R20 17 PolicyState のうち gap 系
  "last_attempt_at": "2026-05-16T03:14:22+09:00",
  "next_retry_at": "2026-05-17T03:14:22+09:00",
  "user_facing_text": "現在 jpcite で愛知県製造業向け補助上限の一次資料を取得できていません"
}
```

schema: `schemas/jpcir/known_gap.schema.json`

## evidence_type 6 値

| evidence_type | 意味 | 採用ケース |
|---|---|---|
| `primary_source_url` | 政府 / 自治体 / 公庫 の一次資料 URL | 最強。programs / loans / laws の主軸 |
| `gazette_official` | 官報掲載 | 法令改正 / 通達 |
| `court_decision_record` | 裁判所 / 国税不服審判所 裁決 | court_decisions / saiketsu |
| `enforcement_record` | 行政処分公表 | enforcement_cases |
| `statistic_official` | e-Stat / 政府統計 | public_statistics_market_context |
| `corpus_derived_aggregate` | jpcite corpus の aggregate (NTA bulk 等) | invoice_registrants の delta 集計など |

`primary_source_url` が無く `corpus_derived_aggregate` だけの claim は **`support_state: partial` が上限** (`supported` に上がらない)。

## support_state 4 値

| support_state | 意味 | agent 側 user 通知 |
|---|---|---|
| `supported` | primary_source_url + 検証済 receipt あり | "一次資料あり" 表示 |
| `partial` | aggregate 系のみ / 一部条件で裏付け | "一部裏付け、要 user 確認" 表示 |
| `contested` | 複数 source で値が矛盾 | "出典間で矛盾あり" 表示 + 各 source URL 明示 |
| `absent` | evidence 0 件 | known_gap artifact に flip、claim を artifact から削除 |

agent は **`absent`** を受け取った時点で claim 表示を中止し、known_gap の `user_facing_text` を user に提示する (overclaim 防止)。

## claim → evidence → receipt の chain (artifact body 例)

```json
{
  "packet_id": "pkt_2026-05-16_application_strategy_7f3e9",
  "artifact_body": {
    "programs": [
      {
        "program_name": "愛知県ものづくり補助金 14次",
        "deadline_text": "2026-06-30",
        "_claims": ["claim_app_strategy_aichi_mfg_001"]
      }
    ]
  },
  "claims": [
    {"claim_id": "claim_app_strategy_aichi_mfg_001", "claim_text": "...", "claim_kind": "factual_deadline"}
  ],
  "evidence": [
    {"evidence_id": "ev_001", "claim_id": "claim_app_strategy_aichi_mfg_001",
     "evidence_type": "primary_source_url", "source_receipt_id": "rcp_001",
     "support_state": "supported", "confidence": "high"}
  ],
  "source_receipts": [
    {"receipt_id": "rcp_001", "source_url": "https://www.pref.aichi.jp/...",
     "source_authority": "愛知県 産業労働部", "content_sha256": "sha256:abc...",
     "license": "gov_standard"}
  ],
  "known_gaps": []
}
```

artifact 内で `_claims` → `claim_id` → `evidence_id` → `source_receipt_id` が **id 経由でのみ参照** されるので、agent 側で graph 解析が線形時間で可能。

## known_gap 出力 path (overclaim 防止)

```
evidence 0 件の claim 検出
  ↓
policy_decision.public_compile_allowed = False (一時 block)
  ↓
known_gap artifact 生成 (policy_state=gap_artifact_only)
  ↓
packet response の `known_gaps[]` に inline
  ↓
agent: "現状未対応" として user に提示 (該当 claim は body から削除)
```

`blocked_no_hit_overclaim` policy_state は **known_gap path 経由で防御** される。direct で `no result` を user に返すと overclaim risk なので、必ず known_gap 経由。

## Error handling

| 検出 | 意味 | agent 側 |
|---|---|---|
| claim_id が evidence + known_gap どちらにも無い | orphan claim | artifact reject (schema validator が弾く) |
| evidence の support_state=supported なのに source_receipt 欠 | 不整合 | artifact reject |
| source_receipt の license=unknown | TOS 未確定 source | `blocked_terms_unknown` 派生 |
| content_sha256 mismatch (re-fetch 時) | source 改変 | known_gap の `gap_kind=source_drift` で flip |

## 関連

- [R17 — 4 P0 Facade Tools](r17_4_p0_facade_tools.md) (artifact_body の citations + source_receipts は本 recipe 由来)
- [R20 — 17 PolicyState](r20_policy_state.md) (gap_artifact_only / blocked_no_hit_overclaim の発火点)
- [R22 — Release Capsule Manifest](r22_release_capsule_manifest.md)
- [R23 — 5 Preflight Gate](r23_5_preflight_gates.md)
- contract: `schemas/jpcir/{claim_ref,evidence,source_receipt,known_gap}.schema.json`
- implementation: `src/jpintel_mcp/agent_runtime/contracts.py` (Evidence / ClaimRef / SourceReceipt / KnownGap Pydantic)
