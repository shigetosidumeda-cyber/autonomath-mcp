# Hallucination Guard Methodology

## Purpose

`hallucination_guard` flags high-frequency 補助金 / 税制 / 融資 / 認定 /
行政処分 / 法令 misconceptions in LLM-generated answers before they reach
the user. We never call an LLM ourselves (see `feedback_autonomath_no_api_use`);
this guard is the cheapest way to keep downstream Claude / Cursor / GPT
outputs honest when they cite our data.

## Data structure

Source of truth: `data/hallucination_guard.yaml` (launch v1 = **60 entries**).

```yaml
entries:
  - phrase: "..."         # verbatim misconception
    severity: high        # high | medium | low
    correction: "..."     # one-line correction
    law_basis: "..."      # optional 法律名 + 条
    audience: 税理士       # 税理士 | 行政書士 | SMB | VC | Dev
    vertical: 税制         # 補助金 | 税制 | 融資 | 認定 | 行政処分 | 法令
```

Grid: **5 audience × 6 vertical × 2 phrase = 60**. Every cell holds exactly
two phrases — broad coverage, no single-cell overfit pre-launch.

## Runtime

`src/jpintel_mcp/self_improve/loop_a_hallucination_guard.py` exposes:

- `match(text) -> list[dict]` — substring scan; pure, no DB / network.
- `summarize() -> dict` — counts by severity / audience / vertical.
- `run(dry_run)` — weekly orchestrator entry. **Never writes the DB at
  launch**; real candidate writes are gated to T+30d.

## Self-improve expansion (60 → 1,500+)

Loop A runs weekly post-launch:

1. Pull 7-day `customer_feedback` (wrong_answer / made_up_program) +
   low-confidence rows from `query_log_v2`.
2. Embed with **local e5-small** (no LLM API).
3. DBSCAN (eps 0.18, min 3). Medoid → candidate phrase.
4. Append to `hallucination_guard_candidates` with `status='pending_review'`.
5. Operator promotes manually. Target: 1,500+ rows within 6 months.

## Operator manual-add

1. Append to `data/hallucination_guard.yaml`. Required fields and enum
   values must match the schema; the loader silently drops malformed rows.
2. Run `pytest tests/test_hallucination_guard.py` — the schema test catches
   missing fields and bad enums.
3. Commit. `lru_cache` means API workers need a restart to pick up changes.
