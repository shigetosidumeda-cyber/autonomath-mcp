# R18 (P0) — 14 Outcome Contract の選び方

> AI agent 向け recipe。jpcite の outcome_contract は agent が **何を artifact として受け取るか** を事前に static 宣言した契約集 (14 件)。user intent から outcome を 1 つ選び、`preview_cost` → `execute_packet` の 2 段で確定する。**14 全件の `estimated_price_jpy` は `¥300 / ¥600 / ¥900` の 3 段** (light lookup / standard / composed-cohort) に整合。

- **Audience**: AI agent builder + 顧客 segment (tax_advisor / accounting_firm / sme_operator / financial_institution / foreign_investor / healthcare_operator / judicial_scrivener / compliance_team / local_government_vendor)
- **Cost**: outcome ごとに `accepted_artifact_low (¥300)` / `accepted_artifact_standard (¥600)` / `accepted_artifact_premium / csv_overlay (¥900)`
- **Sensitive**: §52 / §72 / §1 / §47条の2 / 司法書士法 / 行政書士法 / 社労士法

## TL;DR

`jpcite_route` で **候補 outcome を最大 3 件得る** → flowchart で 1 件選ぶ → `preview_cost` で価格と必要 token を確認 → `execute_packet` で artifact 受領。outcome は 14 で固定、追加は次の RC で intentional に bump。

## 14 outcome 一覧 (table)

| outcome_contract_id | display_name | 価格 (JPY) | 主用途 |
|---|---|---|---|
| `company_public_baseline` | Company public baseline | 600 | 法人 360 公開 baseline (gBizINFO + invoice + EDINET) |
| `invoice_registrant_public_check` | Invoice registrant public check | 300 | T 番号 適格事業者 確認 (light lookup) |
| `application_strategy` | Subsidy and grant candidate pack | 900 | 補助金候補 + 適合度 + 一次資料 URL |
| `regulation_change_watch` | Law and regulation change watch | 600 | 法改正 watch (法令 + 通達 + パブコメ) |
| `local_government_permit_obligation_map` | Local government permit and obligation map | 900 | 自治体 許認可 / 義務 map |
| `court_enforcement_citation_pack` | Court and enforcement citation pack | 600 | 判例 + 行政処分 citation pack |
| `public_statistics_market_context` | Public statistics market context | 600 | e-Stat 公開統計 context |
| `client_monthly_review` | Client monthly public watchlist | 900 | 顧問先 monthly digest (税理士 fan-out) |
| `csv_overlay_public_check` | Accounting CSV public counterparty check | 900 | freee/MF/yayoi/TKC CSV × 公開取引先 整合 |
| `cashbook_csv_subsidy_fit_screen` | Cashbook CSV subsidy fit screen | 900 | 現金出納帳 CSV × 補助金適合 screen |
| `source_receipt_ledger` | Source receipt ledger | 600 | 出典 receipt ledger (audit purpose) |
| `evidence_answer` | Evidence answer citation pack | 600 | 質問 → citation pack (法令 + 判例 + 通達) |
| `foreign_investor_japan_public_entry_brief` | Foreign investor Japan public entry brief | 900 | 外資 FDI entry brief (英訳付) |
| `healthcare_regulatory_public_check` | Healthcare regulatory public check | 600 | 医療業界 規制 check |

## Flowchart: user intent → outcome 選択

```
user intent
  ├─ 「この会社どんな会社?」               → company_public_baseline (¥600)
  ├─ 「T番号って正しい?」                   → invoice_registrant_public_check (¥300)
  ├─ 「ウチに合う補助金 5 件」              → application_strategy (¥900)
  ├─ 「最近の法改正で何が変わった?」        → regulation_change_watch (¥600)
  ├─ 「県の許可ってどう取るの?」            → local_government_permit_obligation_map (¥900)
  ├─ 「過去の判例と処分を まとめて」        → court_enforcement_citation_pack (¥600)
  ├─ 「業界 marker stats」                   → public_statistics_market_context (¥600)
  ├─ 「顧問先 30 社の今月の動き」           → client_monthly_review (¥900)
  ├─ 「freee CSV 取引先の信用 確認」        → csv_overlay_public_check (¥900)
  ├─ 「現金出納帳 → 申請可な補助金」        → cashbook_csv_subsidy_fit_screen (¥900)
  ├─ 「出典どこから来た?」                  → source_receipt_ledger (¥600)
  ├─ 「Q&A に citation 付けて」              → evidence_answer (¥600)
  ├─ 「日本進出 企業 向け brief」            → foreign_investor_japan_public_entry_brief (¥900)
  └─ 「医療法人の規制 check」                → healthcare_regulatory_public_check (¥600)
```

## 3 つの典型 use case

**Case A — 補助金候補 (tax_advisor cohort)**:
顧問先「愛知の製造業」→ `application_strategy` (¥900) を選択 → preview_cost で `pricing_posture: accepted_artifact_premium` + `requires_user_csv: false` を確認 → execute_packet で programs + 採択事例 + 通達 を 1 packet で受領。

**Case B — 取引先信用 (financial_institution cohort)**:
新規取引先 T 番号 5 件 → `invoice_registrant_public_check` (¥300) を 5 並列 → 法人 360 が必要なら `company_public_baseline` (¥600) に escalate。

**Case C — 法改正監視 (compliance_team cohort)**:
顧問先業種 (建設 / 製造 / 不動産) ごとに `regulation_change_watch` (¥600) を weekly cron で発火 → diff があれば `evidence_answer` (¥600) で citation pack を agent に流す。

## Free inline packet の利用

`jpcite_route` の response には `outcome_catalog_summary` packet が **inline で 0 円** で付く。agent は LLM 呼び出し前に全 outcome を 1 call で把握できる。catalog_summary には `display_name` / `estimated_price_jpy` / `user_segments` / `cached_official_public_sources_sufficient` が含まれ、agent 側 prompt に直接 inline 可。

```json
{
  "outcome_catalog_summary": {
    "schema_version": "jpcite.outcome_catalog.p0.v1",
    "deliverables": [
      {"outcome_contract_id":"invoice_registrant_public_check","estimated_price_jpy":300,"user_segments":["tax_advisor","accounting_firm","sme_operator"]},
      {"outcome_contract_id":"application_strategy","estimated_price_jpy":900,"user_segments":["agent_builder","accounting_firm","sme_operator","tax_advisor"]}
    ]
  }
}
```

## 関連

- [R17 — 4 P0 Facade Tools](r17_4_p0_facade_tools.md)
- [R19 — CSV intake preview](r19_csv_intake_preview.md) (¥900 CSV overlay outcome 用)
- [R20 — 17 PolicyState の解釈](r20_policy_state.md)
- [R21 — Agent Purchase Decision](r21_agent_purchase_decision.md)
- catalog: `site/releases/rc1-p0-bootstrap/outcome_catalog.json`
- contract: `schemas/jpcir/outcome_contract.schema.json`
- implementation: `src/jpintel_mcp/agent_runtime/outcome_catalog.py`
