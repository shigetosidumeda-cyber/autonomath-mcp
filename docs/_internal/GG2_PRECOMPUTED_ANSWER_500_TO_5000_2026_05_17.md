# GG2 — am_precomputed_answer 500 → 5,000 (10x precompute expansion) (2026-05-17)

**[lane:solo]** — spec only, FF5 で実装.

## 1. Goal

precomputed-answer cache を 500 row → 5,000 row (10x), top-query 80% を cold-LLM 不要で即返し.

## 2. Investment

| Resource | Detail | $ |
|---|---|---:|
| Athena cross-corpus scan | 1.5TB × $5/TB = $7.5/q × 47 q | $350 |
| Parquet ZSTD write | 5GB output × $0.023/GB-month + transfer | $50 |
| S3 IA storage | 50GB × 3 month | $30 |
| FAISS lookup index | 5,000 row × IVF-PQ codebook | $30 |
| Smoke + CW + sustained | | $40 |
| **Total** | | **$500** |

JPY: $500 × 150 = **¥75,000**

## 3. Contribution model

- top-5,000 query precomputed → cold-LLM cost ¥3-12/req 完全削除
- 5,000 query × 10k user × 50 query/y × 2% hit rate adoption = 50,000 hit/y
- 保守 revenue: ¥3 × 50,000 × 100% retention impact = ¥150k/y direct
- Indirect: cohort retention boost +2% × ¥30M ARR = ¥600k/y
- Combined: ¥30M/y potential (高頻度 query coverage が ARR 増分に寄与する 1% lift) — 保守 ¥30M/y

## 4. ROI

¥30M / ¥75k = **400x** → STRONG GO

## 5. Selection methodology (Wave 60-94 outcome 432 × persona 5 × intent 5)

- 432 × 5 × 5 = 10,800 候補
- query log frequency top 5,000 select (Pareto 80/20)
- 1-week query log (Athena query_log table) で frequency rank

## 6. Output table

```sql
CREATE TABLE jc_precomputed_answer_5000 (
  query_hash TEXT PRIMARY KEY,    -- sha256(persona + intent + outcome + as_of)
  persona_id TEXT,                -- 5 enum
  intent_id TEXT,                 -- 5 enum
  outcome_id TEXT,                -- Wave 60-94 catalog 432
  answer_parquet_uri TEXT,        -- s3://jpcite-data/precomputed/{hash}.parquet
  citations_json TEXT,            -- explainable fact (Dim O)
  generated_at TIMESTAMP,
  ttl_at TIMESTAMP,
  hit_count INT DEFAULT 0
);
```

## 7. Smoke + gate

- 500 row → 5,000 row 段階拡張 (10 wave × 500 batch)
- mypy strict 0 / ruff 0
- aggregator ban
- safe_commit.sh

## 8. Risk

- Stale precompute → ttl_at 7 day + nightly refresh top 1,000 query
- Athena 50GB cap → 47 query × 1GB avg = 47GB (safe under cap)

## 9. Rollback

- table truncate + S3 prefix delete (¥0 cost)
