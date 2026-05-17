# GG1 — Heavy Endpoint HE-5 + HE-6 cohort-differentiated (2026-05-17)

**[lane:solo]** — spec only, FF5 で実装.

## 1. Goal

5 cohort × HE-5 (D-tier deep-research bundle, 60-page report) × HE-6 (cohort-specific decision tree) → premium ¥30/req endpoint.

## 2. Investment

| Resource | Detail | $ |
|---|---|---:|
| SageMaker g4dn.xlarge | 2h × 5 cohort × build phase | $80 |
| Athena cross-corpus scan | 5 cohort × 100GB avg | $50 |
| S3 Parquet write | 60-page report × 5 cohort × 432 outcome | $30 |
| FAISS index build | cohort-specific PQ codebook | $20 |
| CW monitoring + smoke | sustained logs | $20 |
| **Total** | | **$200** |

JPY: $200 × 150 = **¥30,000**

## 3. Contribution model

- HE-5 D-tier bundle = ¥30/req (Enterprise tier)
- 5 cohort × 1,000 user (avg) × 1,000 query/y = 5M req/y potential
- Adoption lift conservative: 5%
- Revenue: ¥30 × 5M × 5% = **¥7.5M/y** (保守)
- Optimistic 10% adoption: ¥15M/y

## 4. ROI

¥7.5M / ¥30k = **250x** → STRONG GO

## 5. Cohort × Deep-research Matrix

| Cohort | Deep-research focus | HE-5 D-tier 60p output | HE-6 decision tree |
|---|---|---|---|
| 税理士 zeirishi | 顧問先 360 + tax amendment lineage | full 360 + ROI + tax saving annotated | filing scenario branch 7 |
| 会計士 kaikeishi | audit standard + IC case + 内部統制 | full audit + risk matrix + ASBJ ref | audit branch 5 |
| 行政書士 gyousei | subsidy lineage + municipality + permit | full subsidy timeline + municipality matched | application branch 12 |
| 社労士 sharoushi | 助成金 + labor law + 36 agreement | full subsidy + labor exposure timeline | filing branch 8 |
| SME founder | funding lineage + adoption cohort + pivot | full funding timeline + comparable success | next-step branch 10 |

## 6. Output table

```sql
CREATE TABLE jc_he5_d_tier_precomputed (
  cohort_id TEXT,          -- 5 enum
  outcome_id TEXT,         -- Wave 60-94 catalog 432 ref
  bundle_uri TEXT,         -- s3://jpcite-data/he5-d-tier/{cohort}/{outcome}.parquet
  decision_tree_json TEXT, -- HE-6 branch
  generated_at TIMESTAMP,
  faiss_codebook_uri TEXT, -- cohort-specific PQ
  hash_sha256 TEXT,
  PRIMARY KEY (cohort_id, outcome_id)
);
```

## 7. Smoke + gate

- mypy strict 0 / ruff 0
- safe_commit.sh
- aggregator ban
- 5 cohort × 100 outcome sample bundle (500 row) で smoke run、$10 cost

## 8. Risk

- g4dn quota 5 cohort 並列要否 (serial fallback 10h × $40 = $40 同等)
- bundle 内 PII redact (Dim N) hook 必須

## 9. Rollback

- bundle s3 prefix delete + table truncate (¥0 cost)
