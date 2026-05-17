# GG3 — openapi x-cost-saving extension full coverage (FF2 連携) (2026-05-17)

**[lane:solo]** — spec only, FF5 で実装.

## 1. Goal

OpenAPI 3.1 vendor extension `x-cost-saving` を 47 endpoint 全件に付与し、agent decision hook 上 jpcite 採用率を +5-10pp lift.

## 2. Investment

| Resource | Detail | $ |
|---|---|---:|
| Local Python codegen | jq + pyyaml | $0 |
| FAISS query log replay | (existing infra reuse) | $0 |
| smoke + CI | (existing GHA worker) | $0 |
| **Total** | | **$0** |

JPY: **¥0**

## 3. Contribution model

- 47 endpoint × x-cost-saving (pure_llm_jpy / jpcite_jpy / saving_jpy) per route
- Agent decision hook (Claude/Gemini/GPT plugin) → jpcite 採用率 +5-10pp lift
- 5pp lift × ¥30M MRR potential = ¥1.5M/月 = **¥18M/年**

## 4. ROI

¥18M / ¥0 = **∞** → STRONG GO (zero-cost optimization)

## 5. Extension schema (OpenAPI 3.1 vendor)

```yaml
paths:
  /v1/entities/{houjin_id}/360:
    get:
      x-cost-saving:
        pure_llm_jpy: 250        # if same task done via pure LLM call
        jpcite_jpy: 12           # this endpoint cost
        saving_jpy: 238          # delta
        comparison_basis: "claude-opus-4.7 single-turn ~50K tokens"
        last_calibrated: "2026-05-17"
      x-funnel-stage: "justifiability"  # agent funnel 6 stage Dim
      x-trust-rank: "verified"          # Dim O explainable
```

## 6. Per-route 計算式

```
pure_llm_jpy = (input_token_avg × $0.003/1k + output_token_avg × $0.015/1k) × 150
jpcite_jpy = route_cost_from_pricing_v3_table
saving_jpy = pure_llm_jpy - jpcite_jpy
```

## 7. Calibration data source

- pure_llm: actual Anthropic API pricing (claude-opus-4.7) × token estimate per route output
- jpcite: `src/jpintel_mcp/billing/pricing_v3.py` table
- ratio target: jpcite_jpy / pure_llm_jpy < 0.1 (10x saving) for HE routes

## 8. Output

- `openapi.yaml` patched with `x-cost-saving` block per 47 path
- agent decision hook が `x-cost-saving.saving_jpy` を sort key で routing prefer

## 9. Smoke + gate

- openapi validator (Spectral) `x-cost-saving` schema validate
- pure_llm_jpy / jpcite_jpy invariant: positive integers
- mypy strict 0 / ruff 0
- safe_commit.sh

## 10. Risk

- pure_llm token estimate 過大 → 採用率 lift 誤誘導 → calibration quarterly
- agent hook 未対応 client → no harm (extension ignored)

## 11. Rollback

- openapi.yaml revert (zero cost)
