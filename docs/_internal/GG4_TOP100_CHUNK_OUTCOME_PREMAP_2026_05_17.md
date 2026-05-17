# GG4 — Top 100 chunks pre-mapped to outcome catalog 432 (深堀 search 即返し) (2026-05-17)

**[lane:solo]** — spec only, FF5 で実装.

## 1. Goal

Wave 60-94 outcome catalog 432 件 × top 100 chunk pre-link 構築 → outcome hit 時 TTFB -50% → retention +20%.

## 2. Investment

| Resource | Detail | $ |
|---|---|---:|
| FAISS IVF-PQ recompute | 74,812 vec → outcome-grouped re-cluster | $50 |
| Index reorder + write | 5 cohort sidecar index | $30 |
| S3 upload (sidecar index) | 432 × 100 chunk pointer + small payload | $20 |
| Athena join verify | outcome × chunk join + top-100 select | $50 |
| Smoke + CW + sustained | | $50 |
| **Total** | | **$200** |

JPY: $200 × 150 = **¥30,000**

## 3. Contribution model

- TTFB -50% (現状 800ms → 400ms avg, outcome path で)
- Retention +20% (Dim Q time-machine cohort で観測)
- Retention +20% × ARR ¥30M = **¥6M/y**

## 4. ROI

¥6M / ¥30k = **200x** → STRONG GO

## 5. Schema

```sql
CREATE TABLE jc_outcome_chunk_top100 (
  outcome_id TEXT,           -- Wave 60-94 catalog 432
  rank INT,                  -- 1-100
  chunk_id TEXT,             -- FAISS sidecar key
  chunk_source TEXT,         -- corpus enum (NTA / ASBJ / FDI / SME / municipality)
  similarity_score REAL,     -- 0.0-1.0
  text_preview TEXT,         -- 256 char head for SSR instant render
  faiss_vector_offset INT,   -- direct FAISS ptr (skip query overhead)
  PRIMARY KEY (outcome_id, rank)
);
CREATE INDEX idx_outcome_rank ON jc_outcome_chunk_top100(outcome_id, rank);
```

Total row: 432 × 100 = **43,200 row**, size ~50MB Parquet ZSTD.

## 6. Build pipeline

1. Wave 60-94 outcome catalog 432 → `am_outcome_catalog` table 参照
2. 各 outcome について FAISS query (current IVF-PQ index, nprobe=8)
3. top 100 chunk select + similarity score 記録
4. Parquet ZSTD write
5. FAISS sidecar index build (outcome_id → vector offset map)

## 7. Smoke + gate

- 432 outcome × 100 chunk = 43,200 row written
- TTFB measure: A/B test 50/50 over 48h
- target: outcome path TTFB p50 < 500ms
- mypy strict 0 / ruff 0
- safe_commit.sh

## 8. Risk

- FAISS recompute window: nprobe=8 floor 維持 (PERF-feedback 反映)
- chunk_source 多様化 → cohort-specific filter で再 rank 可能
- Cache invalidation: outcome lineage update 時 selective rebuild (per-outcome row replace)

## 9. Rollback

- table truncate + sidecar index revert (FAISS main index 影響なし)
- ¥0 cost

## 10. Linkage

- BB1+BB2 ML v2 (SimCSE + rerank) → similarity_score 算出 backbone
- M3+M9 figure+law embed → corpus source coverage
- Wave 60-94 outcome catalog → outcome_id primary source
- GG2 precomputed answer → chunk_id 共有 (joinable cache key)
