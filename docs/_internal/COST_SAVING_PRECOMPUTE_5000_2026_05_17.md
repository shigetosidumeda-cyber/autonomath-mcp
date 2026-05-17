# GG2 — Cost Saving (Precompute 5,000) (2026-05-17)

**Lane:** `lane:solo` · **Status:** LIVE
**Source of truth:** `am_precomputed_answer` (autonomath.db), 5,473 rows

## 1. Cost savings — per cohort, per query

Pre-compute model: rule-based composition, NO LLM at compose time, NO LLM at
serve time. Per-query serve cost = `¥3-12` (jpcite tier).

### Per-cohort breakdown

| Cohort | Rows | Opus baseline ¥/q (avg) | jpcite ¥/q | Reduction |
|---|---:|---:|---:|---:|
| 税理士 (tax) | 1,100 | ¥500 | ¥3-12 | 99.4% - 97.6% |
| 公認会計士 (audit) | 1,100 | ¥500 | ¥3-12 | 99.4% - 97.6% |
| 行政書士 (gyousei) | 1,097 | ¥500 | ¥3-12 | 99.4% - 97.6% |
| 司法書士 (shihoshoshi) | 1,076 | ¥500 | ¥3-12 | 99.4% - 97.6% |
| 中小経営者 (chusho_keieisha) | 1,100 | ¥500 | ¥3-12 | 99.4% - 97.6% |
| **Total** | **5,473** | | | **99.4% - 97.6%** |

### Lifetime savings per cohort (5,000 query × ¥500 Opus → ¥15K jpcite)

```
Opus cost per cohort   : 5,000 × ¥500 = ¥2,500,000
jpcite cost per cohort : 5,000 × ¥3   = ¥15,000   (¥3 tier)
                       : 5,000 × ¥12  = ¥60,000   (¥12 tier)
Savings per cohort     : ¥2,485,000 (¥3 tier) — 99.4% reduction
                       : ¥2,440,000 (¥12 tier) — 97.6% reduction

5 cohort total savings : ¥12,425,000 (¥3 tier)
                       : ¥12,200,000 (¥12 tier)
```

### Lifetime savings per repeated read cycle

Per 1,000 reads of the same 5,000 FAQ:

```
Opus rerun  : 5,000 × 1,000 × ¥500 = ¥2,500,000,000  (¥2.5B)
jpcite serve: 5,000 × 1,000 × ¥3   = ¥15,000,000     (¥15M)
Net savings : ¥2,485,000,000 per 1,000-read cycle
```

## 2. Quality gate (per row)

Defined in `scripts/aws_credit_ops/precompute_5000_quality_check_2026_05_17.py`:

- `len(answer_text) > 200` chars
- `citation_count >= 2`
- cohort vocabulary contained
- `sections_jsonb` non-empty
- `q_hash` not NULL
- `freshness_state` in {fresh, stale, unknown}

**Pass rate (post-recompose):** **97.55%** (5,339 / 5,473) — gate PASS.

Result: `data/precompute_5000_quality_2026_05_17.json`.

## 3. Constraints honoured

- NO Anthropic / OpenAI / Google SDK at compose or serve time
- Deterministic citation-anchored composition
- `is_scaffold_only = 1`, `requires_professional_review = 1`
- §52 / §47条の2 / §1 / §3 / 中小企業政策 disclaimer per response
- mypy strict 0 / ruff 0

## 4. FAISS v5 lookup

- Index: `data/faiss/am_precomputed_v5_2026_05_17.faiss`
- Meta:  `data/faiss/am_precomputed_v5_2026_05_17.meta.json`
- Dim: 384, nlist: 512 (auto-clipped per IVF training rule), nprobe: 8 (PERF-40 floor)
- Encoder: `hash_3gram_fallback_v0` (NO LLM, deterministic)
- ntotal: 5,473 (matches DB row count)

## 5. Honest framing

Pre-computed answers are **scaffold-only** rule-based summaries. They are NOT
legally binding opinions. Every response carries the §-aware disclaimer.
