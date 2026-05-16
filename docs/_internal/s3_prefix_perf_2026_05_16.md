# S3 Prefix Layout Audit + 4-Level Sharded Redesign — 2026-05-16

**Bucket**: `jpcite-credit-993693061769-202605-derived` (ap-northeast-1, profile `bookyou-recovery`)
**Scope**: PERF-5 audit + proposal (no `s3 cp`/`mv` executed)
**Status**: Proposal-only. Adopt via partition projection (zero migration cost) for top-10 hot tables first.

---

## 1. Headline numbers (live audit)

| Metric | Value |
|---|---|
| Top-level prefixes | **195** |
| Total objects | **1,961,320** |
| Total size | **263.52 GB** |
| Hot prefixes (>= 50K obj) | **19** |
| Hot-prefix share of objects | **86.9 %** (1,704,123 / 1,961,320) |
| Tiny prefixes (< 100 obj) | 145 |
| Empty top-level prefixes | 0 |

> Note — the brief stated "524,290 obj / 220 GB" which matches an older snapshot. Live count today is **1.96 M obj / 263 GB**: Wave 53-79 packet generators (catalog 282) added ~1.4 M objects since.

## 2. Top-20 prefixes by file count

| Rank | Prefix | Objects | Bytes |
|----:|---|---:|---:|
| 1 | `acceptance_probability/` | 225,600 | 504,588,000 |
| 2 | `entity_temporal_pulse_v1/` | 100,000 | 142,633,371 |
| 3 | `entity_succession_360_v1/` | 100,000 | 143,482,569 |
| 4 | `entity_subsidy_360_v1/` | 100,000 | 193,616,449 |
| 5 | `entity_risk_360_v1/` | 100,000 | 177,782,569 |
| 6 | `entity_partner_360_v1/` | 100,000 | 130,182,569 |
| 7 | `entity_court_360_v1/` | 100,000 | 132,600,453 |
| 8 | `entity_360_summary_v1/` | 100,000 | 162,678,074 |
| 9 | `houjin_360/` | 86,849 | 252,463,349 |
| 10 | `regional_industry_violation_density_v1/` | 75,301 | 119,845,741 |
| 11 | `regional_industry_export_intensity_v1/` | 75,301 | 115,930,089 |
| 12 | `prefecture_x_industry_density_v1/` | 75,301 | 123,309,587 |
| 13 | `prefecture_industry_inbound_v1/` | 75,301 | 113,746,360 |
| 14 | `prefecture_industry_court_overlay_v1/` | 75,301 | 111,788,534 |
| 15 | `industry_x_prefecture_houjin_v1/` | 75,301 | 130,312,580 |
| 16 | `regional_industry_subsidy_match_v1/` | 75,300 | 119,392,251 |
| 17 | `municipality_industry_directory_v1/` | 54,856 | 88,872,654 |
| 18 | `municipality_industry_cluster_v1/` | 54,856 | 85,855,574 |
| 19 | `city_industry_diversification_v1/` | 54,856 | 87,610,966 |
| 20 | `entity_certification_360_v1/` | 44,283 | 64,167,852 |

## 3. Hot path problem

Current shape:
```
s3://...-derived/<packet_kind>/<packet_kind>:<houjin>.json    (entity 360 family, ~100K each)
s3://...-derived/houjin_360/<houjin>.json                     (86K)
s3://...-derived/acceptance_probability/<pref>.<jsic>.<size>.<cert>.<year>.json   (225K)
```

Failure modes at current scale:
- **LIST throttling**: 75K-225K files under one prefix saturate the 1000-key page limit. `aws s3 ls --recursive` on `acceptance_probability/` requires 226 paged calls (~14 s wall + 226 RPS spike).
- **Athena partition pruning impossible**: Glue crawler infers a single non-partitioned table per prefix; every query is a full-prefix scan (paid bytes-scanned).
- **No fiscal-year evolution path**: `acceptance_probability/` already has fiscal year embedded in the **filename** (`2022...2026`), so re-listing 2026-only data still scans 2022-2025 keys.
- **S3 partition request limits**: AWS recommends >3,500 PUTs/sec or >5,500 GETs/sec per *prefix* — and a single 225 K-object prefix means all reads route to the same partition.

## 4. Proposed 4-level sharded layout

```
s3://jpcite-credit-993693061769-202605-derived/
   <packet_kind>=<name>/                  L1: packet_kind  (replaces top-level)
   fiscal_year=<YYYY>/                    L2: fiscal_year  (where applicable; else "all")
   shard=<hash00..hashff>/                L3: houjin/key shard (256 buckets, hex of sha256(houjin)[:2])
   <key>.json                             leaf
```

Worked examples (entity_360 family, houjin 1010001001697):
```
old: entity_subsidy_360_v1/entity_subsidy_360_v1:1010001001697.json
new: packet_kind=entity_subsidy_360_v1/fiscal_year=all/shard=a3/1010001001697.json
```

acceptance_probability (already has fiscal year):
```
old: acceptance_probability/三重県.A.large.certification.2024.json
new: packet_kind=acceptance_probability/fiscal_year=2024/shard=三重県/A.large.certification.json
     (L3 prefecture shard for this family — 47 buckets, naturally bounded)
```

Math for 256-shard family (100K objects → 256 prefixes ≈ **391 obj/shard**):
- LIST cost: 1 paged call per shard (390 keys < 1000)
- Parallel LIST throughput: 256 shards × 5,500 GETs/sec = **1.4 M GETs/sec ceiling**
- Athena partition pruning: `WHERE packet_kind=... AND fiscal_year=... AND shard=...` reads 1/256 the keys
- Glue partition projection generates partitions virtually — no `MSCK REPAIR TABLE` cost

## 5. Glue partition projection (ZERO migration cost)

Existing data stays where it is. Only top-10 hot tables get partition projection — applied as table-level properties, no `s3 cp`/`mv`:

```sql
ALTER TABLE jpcite_credit_derived.acceptance_probability
SET TBLPROPERTIES (
  'projection.enabled' = 'true',
  'projection.prefecture.type' = 'enum',
  'projection.prefecture.values' = '北海道,青森県,...,沖縄県',
  'projection.fiscal_year.type' = 'integer',
  'projection.fiscal_year.range' = '2022,2030',
  'projection.size_class.type' = 'enum',
  'projection.size_class.values' = 'small,medium,large',
  'storage.location.template' =
    's3://jpcite-credit-993693061769-202605-derived/acceptance_probability/${prefecture}.${size_class}.certification.${fiscal_year}.json'
);
```

**Effect**: Athena resolves partitions from the path pattern, never calls Glue API to enumerate. Saves both Glue `GetPartitions` API throttling and S3 LIST.

For entity_360 family, partition projection on `shard` is not directly possible because the current keys do NOT contain a shard segment — but a **synthetic projection on `houjin_prefix` (first 4 digits)** works:
```sql
'projection.houjin_prefix.type' = 'integer',
'projection.houjin_prefix.range' = '1000,9999',
'storage.location.template' =
  's3://.../entity_subsidy_360_v1/entity_subsidy_360_v1:${houjin_prefix}*.json'
```
This requires no rewrite — projection just constrains the LIST window.

## 6. Migration plan (lazy, in-place for new, optional rewrite for old)

| Phase | Scope | Action | Risk |
|---|---|---|---|
| P0 | Top-10 hot tables | Add Glue partition projection (this PR). No file moves. | None — read-only metadata change |
| P1 | New packet writes (Wave 80+) | Generators emit sharded layout `packet_kind=X/fiscal_year=Y/shard=ZZ/key.json` | Generator code change; covered by tests |
| P2 | Existing entity_360 family | Lazy copy on first Athena partition projection failure (background `s3 sync` per shard, rate-limited) | Low — copy not move; rollback by deleting new keys |
| P3 | `acceptance_probability/` | Stays in-place; partition projection works without rewrite | None |
| P4 | Cold/tiny prefixes (145 prefixes < 100 obj) | No action. Cost of rewrite > benefit. | None |

## 7. Top-10 partition-projection priority

Apply projection to (in order):
1. `acceptance_probability/` — synthesizes `prefecture × size × fiscal_year` from existing key pattern (no rewrite)
2. `entity_subsidy_360_v1/` — synthesize `houjin_prefix` from first 4 digits
3. `entity_risk_360_v1/` — same shape
4. `entity_360_summary_v1/`
5. `entity_temporal_pulse_v1/`
6. `entity_succession_360_v1/`
7. `entity_partner_360_v1/`
8. `entity_court_360_v1/`
9. `houjin_360/` — projection on `houjin_prefix` (4-digit range)
10. `regional_industry_*_v1` family (6 tables sharing same shape) — projection on prefecture enum (47 values)

## 8. Cost & risk summary

- **Migration cost**: **$0** if partition projection only (no S3 PUT/GET for data copy).
- **Athena scan cost reduction**: expected 40-95 % depending on query selectivity (worst case: full-table aggregate = no change; common case: single-houjin or single-prefecture = ~99 % less bytes scanned).
- **S3 LIST cost**: drops from O(N/1000) paged calls to O(1) per partition projection hit.
- **Rollback**: `ALTER TABLE ... UNSET TBLPROPERTIES (...)` — instant, no data movement.
- **Risk**: Glue `storage.location.template` typos hide partitions silently. Mitigation: run `SELECT COUNT(*) FROM table WHERE partition_key=...` on 3 sample partitions before promote.

## 9. What is **not** in this proposal

- No file `s3 cp` or `s3 mv` (constraint).
- No change to `raw/` bucket layout (out of scope).
- No deletion of cold/tiny prefixes (cost > benefit).
- No re-key of `corpus_export`, `embeddings*`, `faiss_indexes`, `gpu_workload` (small file counts; binary blobs not Athena-scanned).

---

**SOT**: this doc.
**Next**: ship Glue projection DDL for top-10 hot tables in a follow-up PR (gated by a sample-3-partition probe).
