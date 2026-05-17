---
title: "内部統制評価 jpcite call sequence (公認会計士)"
segment: audit
recipe: recipe_audit_internal_control
cost_estimate_jpy: 36
billable_units: 12
parallel: true
duration_seconds: 90
---

<!-- structured data -->
<script type="application/ld+json">
{"@context": "https://schema.org", "@type": "HowTo", "name": "内部統制評価 jpcite call sequence (公認会計士)", "description": "§47条の2 (公認会計士法) + 金商法 J-SOX — IT/業務 統制評価補助のみ。", "estimatedCost": {"@type": "MonetaryAmount", "currency": "JPY", "value": 36}, "totalTime": "PT90S", "step": [{"@type": "HowToStep", "name": "deep_health_am", "text": "snapshot pin", "position": 1}, {"@type": "HowToStep", "name": "match_due_diligence_questions", "text": "DD 統制軸", "position": 2}, {"@type": "HowToStep", "name": "check_enforcement_am", "text": "履歴", "position": 3}, {"@type": "HowToStep", "name": "cross_check_jurisdiction", "text": "整合性", "position": 4}, {"@type": "HowToStep", "name": "search_invoice_registrants", "text": "適格 status", "position": 5}, {"@type": "HowToStep", "name": "search_acceptance_stats_am", "text": "ベンチマーク", "position": 6}, {"@type": "HowToStep", "name": "track_amendment_lineage_am", "text": "金商法/会社法 改正", "position": 7}, {"@type": "HowToStep", "name": "forecast_program_renewal", "text": "renewal cadence", "position": 8}, {"@type": "HowToStep", "name": "get_provenance", "text": "出典", "position": 9}, {"@type": "HowToStep", "name": "compose_audit_workpaper", "text": "統制評価 workpaper", "position": 10}, {"@type": "HowToStep", "name": "dispatch_audit_seal_webhook", "text": "audit_seal 配信", "position": 11}, {"@type": "HowToStep", "name": "jpcite_route", "text": "outcome route", "position": 12}]}
</script>

# 内部統制評価 jpcite call sequence (公認会計士)

> **Cost**: ¥36 (12 billable units, ¥3/req) ·
> **Duration**: 90s ·
> **Parallel-safe**: True ·
> **Disclaimer**: §47条の2 (公認会計士法) + 金商法 J-SOX — IT/業務 統制評価補助のみ。

## Preconditions

- `audit_firm_id`
- `client_id`
- `houjin_bangou`
- `audit_period`

## Steps

1. **deep_health_am** — snapshot pin
2. **match_due_diligence_questions** — DD 統制軸
3. **check_enforcement_am** — 履歴
4. **cross_check_jurisdiction** — 整合性
5. **search_invoice_registrants** — 適格 status
6. **search_acceptance_stats_am** — ベンチマーク
7. **track_amendment_lineage_am** — 金商法/会社法 改正
8. **forecast_program_renewal** — renewal cadence
9. **get_provenance** — 出典
10. **compose_audit_workpaper** — 統制評価 workpaper
11. **dispatch_audit_seal_webhook** — audit_seal 配信
12. **jpcite_route** — outcome route

## Output artifact

- Type: `internal_control_evaluation_packet`
- Format: JSON (mirrored to PDF on `artifact_pack` package_kind)

## SDK invocation

```python
import httpx, os
JPCITE = "https://api.jpcite.com"
key = os.environ["JPCITE_API_KEY"]
resp = httpx.post(
    f"{JPCITE}/v1/jpcite/route",
    headers={"X-API-Key": key},
    json={"intent": "recipe_audit_internal_control"},
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
