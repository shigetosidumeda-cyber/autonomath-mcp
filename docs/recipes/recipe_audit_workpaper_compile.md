---
title: "監査調書編纂 jpcite call sequence (公認会計士)"
segment: audit
recipe: recipe_audit_workpaper_compile
cost_estimate_jpy: 42
billable_units: 14
parallel: true
duration_seconds: 90
---

<!-- structured data -->
<script type="application/ld+json">
{"@context": "https://schema.org", "@type": "HowTo", "name": "監査調書編纂 jpcite call sequence (公認会計士)", "description": "§47条の2 (公認会計士法) — 監査意見表明は会計士の独占業務。本レシピは調書補助のみ。", "estimatedCost": {"@type": "MonetaryAmount", "currency": "JPY", "value": 42}, "totalTime": "PT90S", "step": [{"@type": "HowToStep", "name": "deep_health_am", "text": "snapshot pin", "position": 1}, {"@type": "HowToStep", "name": "enum_values_am", "text": "vocab", "position": 2}, {"@type": "HowToStep", "name": "search_tax_incentives", "text": "適用候補", "position": 3}, {"@type": "HowToStep", "name": "get_am_tax_rule", "text": "rule 詳細", "position": 4}, {"@type": "HowToStep", "name": "evaluate_tax_applicability", "text": "profile x rule", "position": 5}, {"@type": "HowToStep", "name": "track_amendment_lineage_am", "text": "期間中 改正", "position": 6}, {"@type": "HowToStep", "name": "cross_check_jurisdiction", "text": "整合性", "position": 7}, {"@type": "HowToStep", "name": "check_enforcement_am", "text": "履歴", "position": 8}, {"@type": "HowToStep", "name": "match_due_diligence_questions", "text": "DD 質問 deck", "position": 9}, {"@type": "HowToStep", "name": "get_provenance", "text": "出典", "position": 10}, {"@type": "HowToStep", "name": "check_exclusions", "text": "排他", "position": 11}, {"@type": "HowToStep", "name": "compose_audit_workpaper", "text": "調書 PDF", "position": 12}, {"@type": "HowToStep", "name": "dispatch_audit_seal_webhook", "text": "audit_seal 配信", "position": 13}, {"@type": "HowToStep", "name": "jpcite_route", "text": "outcome route", "position": 14}]}
</script>

# 監査調書編纂 jpcite call sequence (公認会計士)

> **Cost**: ¥42 (14 billable units, ¥3/req) ·
> **Duration**: 90s ·
> **Parallel-safe**: True ·
> **Disclaimer**: §47条の2 (公認会計士法) — 監査意見表明は会計士の独占業務。本レシピは調書補助のみ。

## Preconditions

- `audit_firm_id`
- `client_id`
- `houjin_bangou`
- `audit_period (YYYY or YYYY-Q1..Q4)`

## Steps

1. **deep_health_am** — snapshot pin
2. **enum_values_am** — vocab
3. **search_tax_incentives** — 適用候補
4. **get_am_tax_rule** — rule 詳細
5. **evaluate_tax_applicability** — profile x rule
6. **track_amendment_lineage_am** — 期間中 改正
7. **cross_check_jurisdiction** — 整合性
8. **check_enforcement_am** — 履歴
9. **match_due_diligence_questions** — DD 質問 deck
10. **get_provenance** — 出典
11. **check_exclusions** — 排他
12. **compose_audit_workpaper** — 調書 PDF
13. **dispatch_audit_seal_webhook** — audit_seal 配信
14. **jpcite_route** — outcome route

## Output artifact

- Type: `audit_workpaper_pdf`
- Format: JSON (mirrored to PDF on `artifact_pack` package_kind)

## SDK invocation

```python
import httpx, os
JPCITE = "https://api.jpcite.com"
key = os.environ["JPCITE_API_KEY"]
resp = httpx.post(
    f"{JPCITE}/v1/jpcite/route",
    headers={"X-API-Key": key},
    json={"intent": "recipe_audit_workpaper_compile"},
).raise_for_status().json()
# returns recommended_tool, outcome_contract_id, deliverable_slug,
# estimated_price_jpy, execute_input_hash, next_action
```

## Related

- [Cookbook index](/docs/cookbook/)
- [API reference](/docs/api-reference/)
- [MCP tools](/docs/mcp-tools/)
- [Outcome catalog](https://jpcite.com/.well-known/jpcite-outcome-catalog.json)

---

*Operator: Bookyou株式会社 (T8010001213708) · Brand: jpcite · NO LLM inside · ¥3/req metered · 100% organic*
