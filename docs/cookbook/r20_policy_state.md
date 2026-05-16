# R20 (P0) — 17 PolicyState の解釈

> AI agent 向け recipe。jpcite の `policy_state` は **artifact が公開 surface (REST/MCP packet) に出てよいか** を判定する 17 値の Literal enum。agent は `policy_state` を見て次の挙動 (公開合成 / 内部のみ / 諦め) を決める。`public_compile_allowed` flag は policy_state と必ず整合する。

- **Audience**: AI agent builder (cohort: `agent_builder`)
- **Cost**: 判定自体は packet response に inline で 0 円
- **Sensitive**: 全 sensitive surface (§52 / §72 / §1 / §47条の2) は `allow_with_minimization` 以上の strict 側にしか出ない

## TL;DR

17 値は **3 群 (allow 系 5 / blocked 系 9 / 終端 2 + gap 1)** に分かれる。`allow*` だけが `public_compile_allowed=True` を許す。`blocked_*` / `quarantine` / `deny` は **公開合成禁止** (raise ValueError on attempt)。

## 17 PolicyState 一覧

| group | policy_state | public_compile_allowed | 意味 |
|---|---|---|---|
| allow | `allow` | ✅ | 制約なしで公開合成可 |
| allow | `allow_with_minimization` | ✅ | 個人情報 / 住所等を minimize して公開可 (sensitive cohort) |
| allow | `allow_internal_only` | ❌ | 顧客内部のみ、agent → user 渡しは可、3rd party 公開不可 |
| allow | `allow_paid_tenant_only` | ❌ | paid tenant のみ、anonymous には出さない |
| gap | `gap_artifact_only` | ❌ | gap artifact (known_gap.schema.json) としてのみ出力可 |
| blocked | `blocked_policy_unknown` | ❌ | policy 自体が未確定 — 上流の policy_decision_catalog 更新待ち |
| blocked | `blocked_terms_unknown` | ❌ | source 側 TOS が未取得 |
| blocked | `blocked_terms_changed` | ❌ | source TOS が変わった、要再評価 |
| blocked | `blocked_access_method` | ❌ | scraping 制約 (robots / CAPTCHA / auth) で取得不能 |
| blocked | `blocked_privacy_taint` | ❌ | private taint (CSV overlay 等) が混入、PII 漏洩リスク |
| blocked | `blocked_sensitive_context` | ❌ | sensitive context (医療診断 / 法律相談 等) で disclaimer 不足 |
| blocked | `blocked_mosaic_risk` | ❌ | 単独では公開可だが集合化で個人特定リスク (k<5) |
| blocked | `blocked_wording` | ❌ | 文言が §52 / §72 の業務独占に抵触 |
| blocked | `blocked_paid_leakage` | ❌ | paid tenant 限定 fact が anonymous へ漏れる risk |
| blocked | `blocked_no_hit_overclaim` | ❌ | "ヒットなし" を "存在しない" と過剰主張する risk |
| terminal | `quarantine` | ❌ | 隔離中 (要 review)、artifact 自体は残るが公開しない |
| terminal | `deny` | ❌ | 出力拒否、artifact 削除済 |

## public_compile_allowed の判定

```python
# contracts.py の振る舞い (simplified)
def to_policy_decision(self) -> PolicyDecision:
    if self.policy_state in {"quarantine", "deny"} and self.public_compile_allowed:
        raise ValueError("quarantine/deny cannot compile to public surfaces")
    if self.policy_state.startswith("blocked_") and self.public_compile_allowed:
        raise ValueError(f"{self.policy_state} cannot compile to public surfaces")
    return PolicyDecision(
        policy_state=self.policy_state,
        public_compile_allowed=self.public_compile_allowed,
        ...
    )
```

agent は `public_compile_allowed` を直接見るだけで判定可能。`policy_state` 文字列 prefix から推測する必要なし。

## no_hit_not_absence semantics

jpcite の全 packet response は `no_hit_caveat: "no_hit_not_absence"` を **固定値** で含む。これは「ヒット 0 件 = 存在しない」と agent に誤読させないための contract。

- ヒット 0 件 = **「jpcite の現 corpus には該当 row なし」** であって、「日本国 / 都道府県のどこにも存在しない」ではない
- agent は user に答えるとき、必ず `no_hit_not_absence` semantic を踏襲する文言を選ぶ (例: "現在 jpcite で確認できる中では該当なし")
- 違反すると `blocked_no_hit_overclaim` policy_state が trip して artifact 非公開

## Sample (packet response 抜粋)

```json
{
  "packet_id": "pkt_2026-05-16_application_strategy_7f3e9",
  "policy_decision": {
    "policy_state": "allow_with_minimization",
    "public_compile_allowed": true,
    "no_hit_caveat": "no_hit_not_absence",
    "blocked_reason_codes": []
  },
  "artifact_body": { ... },
  "_disclaimer": {
    "law_basis": ["税理士法 §52", "税理士法 §47条の2"],
    "text": "..."
  }
}
```

## agent 側の対処

| 受領 policy_state | agent の next action |
|---|---|
| `allow*` | そのまま user に提示 (minimization 系は住所等を抽象化) |
| `gap_artifact_only` | known_gap artifact として表示、user に「現状未対応」と伝える |
| `blocked_*` | reject、別 outcome を route で再選 (例: 自治体面なら `local_government_permit_obligation_map` へ escalate) |
| `quarantine` / `deny` | agent 側でも non-output、user に「現在 review 中 / 出力不可」と伝える |

## 関連

- [R17 — 4 P0 Facade Tools](r17_4_p0_facade_tools.md)
- [R18 — 14 Outcome Contract の選び方](r18_14_outcome_contracts.md)
- [R21 — Agent Purchase Decision](r21_agent_purchase_decision.md)
- contract: `schemas/jpcir/policy_decision.schema.json` / `schemas/jpcir/policy_decision_catalog.schema.json`
- implementation: `src/jpintel_mcp/agent_runtime/contracts.py` (PolicyState Literal)
