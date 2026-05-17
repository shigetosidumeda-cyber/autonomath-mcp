---
title: "連結手続書 jpcite call sequence (公認会計士)"
segment: audit
recipe: recipe_audit_consolidation
cost_estimate_jpy: 54
billable_units: 18
parallel: true
duration_seconds: 120
---

<!-- structured data -->
<script type="application/ld+json">
{"@context": "https://schema.org", "@type": "HowTo", "name": "連結手続書 jpcite call sequence (公認会計士)", "description": "§47条の2 (公認会計士法) — 連結監査意見表明は会計士独占。", "estimatedCost": {"@type": "MonetaryAmount", "currency": "JPY", "value": 54}, "totalTime": "PT120S", "step": [{"@type": "HowToStep", "name": "deep_health_am", "text": "snapshot pin", "position": 1}, {"@type": "HowToStep", "name": "get_houjin_360_am", "text": "親法人 360", "position": 2}, {"@type": "HowToStep", "name": "get_houjin_360_am", "text": "子法人 360", "position": 3}, {"@type": "HowToStep", "name": "cross_check_jurisdiction", "text": "親子 jurisdiction", "position": 4}, {"@type": "HowToStep", "name": "check_enforcement_am", "text": "親子 履歴", "position": 5}, {"@type": "HowToStep", "name": "get_tax_treaty", "text": "treaty matrix", "position": 6}, {"@type": "HowToStep", "name": "check_foreign_capital_eligibility", "text": "外資要件", "position": 7}, {"@type": "HowToStep", "name": "get_law_article_am", "text": "会計基準/J-SOX 引用", "position": 8}, {"@type": "HowToStep", "name": "track_amendment_lineage_am", "text": "連結会計 改正", "position": 9}, {"@type": "HowToStep", "name": "search_acceptance_stats_am", "text": "ベンチマーク", "position": 10}, {"@type": "HowToStep", "name": "match_due_diligence_questions", "text": "DD 連結軸", "position": 11}, {"@type": "HowToStep", "name": "check_exclusions", "text": "親子 排他", "position": 12}, {"@type": "HowToStep", "name": "prepare_kessan_briefing", "text": "連結決算 briefing", "position": 13}, {"@type": "HowToStep", "name": "get_provenance", "text": "出典", "position": 14}, {"@type": "HowToStep", "name": "compose_audit_workpaper", "text": "連結調書 PDF", "position": 15}, {"@type": "HowToStep", "name": "dispatch_audit_seal_webhook", "text": "audit_seal 配信", "position": 16}, {"@type": "HowToStep", "name": "jpcite_route", "text": "outcome route", "position": 17}, {"@type": "HowToStep", "name": "jpcite_preview_cost", "text": "cost preview", "position": 18}]}
</script>

# 連結手続書 jpcite call sequence (公認会計士)

> **Cost**: ¥54 (18 billable units, ¥3/req) ·
> **Duration**: 120s ·
> **Parallel-safe**: True ·
> **Disclaimer**: §47条の2 (公認会計士法) — 連結監査意見表明は会計士独占。

## Preconditions

- `audit_firm_id`
- `parent_houjin_bangou`
- `subsidiary_houjin_bangou (array)`
- `audit_period`
- `consolidation_scope`

## Steps

1. **deep_health_am** — snapshot pin
2. **get_houjin_360_am** — 親法人 360
3. **get_houjin_360_am** — 子法人 360
4. **cross_check_jurisdiction** — 親子 jurisdiction
5. **check_enforcement_am** — 親子 履歴
6. **get_tax_treaty** — treaty matrix
7. **check_foreign_capital_eligibility** — 外資要件
8. **get_law_article_am** — 会計基準/J-SOX 引用
9. **track_amendment_lineage_am** — 連結会計 改正
10. **search_acceptance_stats_am** — ベンチマーク
11. **match_due_diligence_questions** — DD 連結軸
12. **check_exclusions** — 親子 排他
13. **prepare_kessan_briefing** — 連結決算 briefing
14. **get_provenance** — 出典
15. **compose_audit_workpaper** — 連結調書 PDF
16. **dispatch_audit_seal_webhook** — audit_seal 配信
17. **jpcite_route** — outcome route
18. **jpcite_preview_cost** — cost preview

## Output artifact

- Type: `consolidation_evidence_packet`
- Format: JSON (mirrored to PDF on `artifact_pack` package_kind)

## SDK invocation

```python
import httpx, os
JPCITE = "https://api.jpcite.com"
key = os.environ["JPCITE_API_KEY"]
resp = httpx.post(
    f"{JPCITE}/v1/jpcite/route",
    headers={"X-API-Key": key},
    json={"intent": "recipe_audit_consolidation"},
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
