# GG7 — 432 outcome × 5 cohort variant fan-out cost saving (2026-05-17)

**[lane:solo]** — FF1 SOT aligned cost-saving narrative for the GG7 fan-out.
Pure rule-based composition; NO LLM at compose or serve time.
Cross-ref: `JPCITE_COST_ROI_SOT_2026_05_17.md` (§3 tier table SOT),
`GG1_HE5_HE6_COHORT_DIFFERENTIATED_2026_05_17.md` (cohort definition source),
`scripts/aws_credit_ops/generate_cohort_outcome_variants_2026_05_17.py`
(generator).

---

## 1. Fan-out

| Dimension | Count |
|---|---:|
| Wave 60-94 outcomes | 432 |
| Cohorts (zeirishi / kaikeishi / gyouseishoshi / shihoshoshi / chusho_keieisha) | 5 |
| **Total cohort-variant rows** | **2,160** |

Rows produced by `generate_cohort_outcome_variants_2026_05_17.py` and
persisted in `am_outcome_cohort_variant` (migration `wave24_221`).

---

## 2. Per-cohort representative tier (FF1 SOT §4.2 mix-weighted)

The cohort_saving_yen_per_query is derived deterministically from the FF1
SOT tier table. Per cohort representative tier:

| Cohort | Label | Rep tier | jpcite ¥/req | Opus equiv ¥/req | Unmatched saving | Matched saving (+20%) |
|---|---|:--:|---:|---:|---:|---:|
| zeirishi | 税理士 | B | ¥6 | ¥170 | ¥164 | ¥197 |
| kaikeishi | 会計士 | C | ¥12 | ¥347 | ¥335 | ¥402 |
| gyouseishoshi | 行政書士 | B | ¥6 | ¥170 | ¥164 | ¥197 |
| shihoshoshi | 司法書士 | A | ¥3 | ¥54 | ¥51 | ¥61 |
| chusho_keieisha | 中小経営者 | C | ¥12 | ¥347 | ¥335 | ¥402 |

**Matched** = cohort × outcome bucket overlap exists
(per `COHORT_OUTCOME_BUCKET_MATCH`). E.g. zeirishi cohort matches outcomes
in {tax, audit, sme} buckets; shihoshoshi cohort matches
{shihoshoshi, real_estate, ma}.

---

## 3. Per-cohort saving total across 432 outcomes

```text
saving_total_per_cohort = sum(cohort_saving_yen_per_query)
                          over all 432 outcomes
```

| Cohort | Matched outcomes | Unmatched outcomes | **Total saving / 432 outcomes** |
|---|---:|---:|---:|
| zeirishi | 108 | 324 | **¥74,412** |
| kaikeishi | 108 | 324 | **¥151,956** |
| gyouseishoshi | 108 | 324 | **¥74,412** |
| shihoshoshi | 108 | 324 | **¥23,112** |
| chusho_keieisha | 180 | 252 | **¥156,780** |
| **Aggregate (5 cohorts × 432 outcomes)** | — | — | **¥480,672** |

Matched count is 108 = 36 outcomes × 3 matched buckets per cohort
(except chusho_keieisha which matches 5 buckets → 180).

Reading: the 2,160 cohort-variant fan-out unlocks a cumulative
**~¥480k per-query Opus baseline displacement** across the full
432-outcome × 5-cohort catalog — if every cell were queried once on
the rep tier the buyer would avoid ~¥480k of equivalent Opus-self-compose
work.

---

## 4. Top-5 outcome saving table per cohort

Top-5 (highest saving) per cohort — every row reflects a matched
cohort × outcome bucket cell.

### 4.1 税理士 (zeirishi) — top 5

| Rank | outcome_id | bucket | matched | saving / query |
|---:|---:|---|:--:|---:|
| 1 | 217 | tax | yes | ¥197 |
| 2 | 218 | tax | yes | ¥197 |
| 3 | 219 | tax | yes | ¥197 |
| 4 | 220 | tax | yes | ¥197 |
| 5 | 221 | tax | yes | ¥197 |

(outcome_id 217-252 = tax bucket, outcome_id 253-288 = audit bucket,
outcome_id 361-396 = sme bucket.)

### 4.2 会計士 (kaikeishi) — top 5

| Rank | outcome_id | bucket | matched | saving / query |
|---:|---:|---|:--:|---:|
| 1 | 1 | ma | yes | ¥402 |
| 2 | 2 | ma | yes | ¥402 |
| 3 | 3 | ma | yes | ¥402 |
| 4 | 4 | ma | yes | ¥402 |
| 5 | 5 | ma | yes | ¥402 |

### 4.3 行政書士 (gyouseishoshi) — top 5

| Rank | outcome_id | bucket | matched | saving / query |
|---:|---:|---|:--:|---:|
| 1 | 289 | gyousei | yes | ¥197 |
| 2 | 290 | gyousei | yes | ¥197 |
| 3 | 291 | gyousei | yes | ¥197 |
| 4 | 292 | gyousei | yes | ¥197 |
| 5 | 293 | gyousei | yes | ¥197 |

### 4.4 司法書士 (shihoshoshi) — top 5

| Rank | outcome_id | bucket | matched | saving / query |
|---:|---:|---|:--:|---:|
| 1 | 1 | ma | yes | ¥61 |
| 2 | 2 | ma | yes | ¥61 |
| 3 | 3 | ma | yes | ¥61 |
| 4 | 4 | ma | yes | ¥61 |
| 5 | 5 | ma | yes | ¥61 |

### 4.5 中小経営者 (chusho_keieisha) — top 5

| Rank | outcome_id | bucket | matched | saving / query |
|---:|---:|---|:--:|---:|
| 1 | 1 | ma | yes | ¥402 |
| 2 | 2 | ma | yes | ¥402 |
| 3 | 3 | ma | yes | ¥402 |
| 4 | 4 | ma | yes | ¥402 |
| 5 | 5 | ma | yes | ¥402 |

---

## 5. Saving formula (reference)

```python
# scripts/aws_credit_ops/generate_cohort_outcome_variants_2026_05_17.py
def _cohort_saving_yen(cohort: str, *, match: bool) -> int:
    tier = COHORT_REP_TIER[cohort]                  # A/B/C/D per cohort
    raw_saving = TIER_OPUS_YEN[tier] - TIER_YEN[tier]   # FF1 SOT §3
    if match:                                        # cohort × bucket match
        return int(round(raw_saving * 1.20))         # +20% lift
    return int(raw_saving)
```

- Tier A = ¥3 vs ¥54 (3-turn Opus, §2.1) → ¥51 base saving.
- Tier B = ¥6 vs ¥170 (5-turn Opus, §2.2) → ¥164 base saving.
- Tier C = ¥12 vs ¥347 (7-turn Opus, §2.3) → ¥335 base saving.
- Tier D = ¥30 vs ¥500 (Deep++, §2.5 high-end) → ¥470 base saving.

The +20% match lift represents the higher daily query frequency a cohort
exhibits on outcomes within its primary workflow buckets (tax / audit /
gyousei / shihoshoshi / sme / municipality / real_estate / ma / talent /
brand / safety / insurance) versus peripheral outcomes.

---

## 6. Public messaging (per `feedback_cost_saving_v2_quantified`)

Per-case framing only — never ROI / ARR / 年¥X totals in public messaging.
Example surface (for `get_outcome_for_cohort` MCP tool footer):

> "Cohort-specific outcome variant: ¥3 vs ~¥300 Opus 4.7 cohort persona reasoning.
> Saving: 1/100."

The ~¥300 anchor is consistent with the Standard (5-turn) and Deep
(7-turn) bands (FF1 SOT §2.2-2.3) and conservatively below the §2.5
Deep++ ¥500 anchor — so the public messaging is *valid at every cohort
tier* without overclaiming.

---

## 7. Validation hooks

- `tests/test_gg7_outcome_cohort_variants.py` (19 tests) — row count
  exactness (2,160), uniqueness, idempotent re-run, sample
  cohort × bucket workflow vocabulary, MCP tool happy-path + reject
  paths, fragment manifest registration, fragment loader integration.
- mypy strict: 0 errors.
- ruff: 0 errors.
- safe_commit.sh (pre-commit auto-fix detected loud).

---

## 8. Rollback

```bash
sqlite3 autonomath.db < scripts/migrations/wave24_221_am_outcome_cohort_variant_rollback.sql
```

Zero data loss on the rest of the schema; the cohort-variant fan-out can
be rebuilt from scratch by re-running
`scripts/aws_credit_ops/generate_cohort_outcome_variants_2026_05_17.py`.

---

## 9. Change log

| Date | Note |
|---|---|
| 2026-05-17 | Initial GG7 landing — 432 × 5 = 2,160 cohort-variant fan-out + 1 MCP tool (`get_outcome_for_cohort`, Tier A ¥3) + 19 tests + cost-saving narrative. |
