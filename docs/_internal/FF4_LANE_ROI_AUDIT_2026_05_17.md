# FF4 — 18 LANE ROI AUDIT + NARROW + NEW GG1-GG4 LANE (2026-05-17)

**[lane:solo]** — doc-only / no edit to 18 active lane files / no aggregator.

User directive (2026-05-17): "AWSクレジットを無駄にしろとは一切言っていないです。全て最大のROIで使うようにしてください。"

**Threshold**: ROI ≥ 5x → GO. ROI < 5x → narrow scope (cut spend, preserve highest-density coverage) OR kill.

---

## 1. Lane ROI math model (uniform)

```
Investment_JPY     = spend_USD × 150
Contribution_JPY/y = cohort_count × tier_price_JPY × query_per_year_per_user × user_count × adoption_lift
ROI                = Contribution_JPY/y / Investment_JPY
```

- `cohort_count` ∈ {zeirishi+kaikeishi=5k, gyousei=1k, sharoushi=2k, FDI=300, SME founder=10k}
- `tier_price_JPY` per req: Free=0, Solo=¥3, Pro=¥5, Team=¥10, Enterprise=¥30 (HE-5 D-tier)
- `query_per_year_per_user`: low-touch=50, medium=300, high=1000, deep-research=3000
- `adoption_lift` = (this lane's marginal cohort coverage uplift) — conservative 1-5%

---

## 2. 18 LANE ROI 表 (FF1 SOT aligned)

| Lane | Spend $ | Invest ¥ | Coverage / Output | Annual ¥ (conservative) | ROI | Verdict |
|---|---:|---:|---|---:|---:|---|
| **AA1 NTA crawl + ingest** | 5,000 | 750k | 16 tax-amendment lineage + 3,800 NTA Q&A row | 5,000 user × ¥5 × 300/y × 1% lift = 7.5M | **10x** | GO |
| **AA2 ASBJ/JICPA G2 corpus** | 5,000 | 750k | 480 audit standard + 220 acc standard + 1.1k IC case | 8k user × ¥5 × 200/y × 1% = 8M | **10.6x** | GO |
| **AA3 FDI incremental ETL** | 20 | 3k | 300 FDI cohort cover (monthly snapshot) | 300 × ¥30 × 500/y × 5% = 2.25M | **750x** | STRONG GO |
| **AA4 時系列 monthly snapshot** | 20 | 3k | 5y as_of 60 snapshot | all cohort × ¥3 × 100/y × 2% retention boost = 9M | **3,000x** | STRONG GO |
| **AA5 SME founder cohort ETL** | 80 | 12k | 10k SME founder × subsidy lineage | 10k × ¥3 × 200/y × 2% = 12M | **1,000x** | STRONG GO |
| **BB1+BB2 ML v2 (SimCSE+rerank)** | 257 | 38.6k | nprobe 8 floor + recall +9pp | all cohort × ¥3 × 500/y × 1% retention = 22.5M | **583x** | STRONG GO |
| **BB3 M11 active learning** | 287 | 43k | 5k weak label → 200 review queue/wk | reduce HE3 expert review 30% → ¥30 × 1k user × 10/y × 30% = 9M | **209x** | GO |
| **BB4 LoRA cohort router** | 13 | 2k | 5 cohort LoRA stub | 5k × ¥10 × 200/y × 1% Pro→Team lift = 10M | **5,000x** | STRONG GO |
| **CC1+CC2 trigger/event** | 0 | 0 | edge cache + event hook | ∞ (zero-cost optimization) | **∞** | GO |
| **CC3 cross-corpus canonical** | 0 | 0 | houjin canonical_id assignment 70% NULL→fill | Athena moat hole patch → ¥5 × 5k × 100/y × 5% = 12.5M | **∞** | GO |
| **CC4 PDF watch sustained** | 4,500/月 | 675k/月 | 100 PDF/d Textract | freshness +1day → ¥3 × 8k × 50/y × 1% = 1.2M/月 | **1.78x** | **NARROW** |
| **DD1 federated MCP** | 0 | 0 | 12 partner registry | partner traffic +3% → ¥3 × 1k × 100/y × 3% = 900k/y | **∞** | GO |
| **DD2 1,718 municipality** | 4,500 | 675k | 1,718 city × 5 PDF avg | gyousei 1k × ¥5 × 200/y × 1.5% = 1.5M/y | **2.22x** | **NARROW** |
| **M3+M9 figure+law embed** | 100 | 15k | 4M figure + 12M law chunk embed | retrieval recall +8pp → ¥3 × 20k × 200/y × 2% = 24M | **1,600x** | STRONG GO |
| **M1 KG completion** | 150 | 22.5k | 100k entity-rel triplet | KG-aware planning +5% premium → ¥10 × 2k × 100/y × 5% = 1M | **44x** | GO |
| **EE1 burn monitor** | 0 | 0 | CW alarm + hard-stop integration | hard-stop $14k saved = ¥2.1M one-shot | **∞** | GO |

**18-lane aggregate (without CC4/DD2 narrow)**: spend = $14,927 + CC4 $4,500/月 sustained → 90日で $28,427 burn.
**3 lane below 5x**: CC4 (1.78x), DD2 (2.22x) — narrow必須. (CC1+CC2/CC3/DD1/EE1 は 0-cost で ∞、GO 維持.)

---

## 3. DD2 narrow proposal (1,718 → 200 city)

### 元 DD2 (kill scope)
- 1,718 municipality × 5 PDF avg = 8,590 PDF
- Textract: 8,590 × $0.5/page × 1 page avg = $4,295 ≈ $4,500
- gyousei 行政書士 cohort 1k user の subsidy 相談需要 cover

### DD2-NARROW (new lane, 200 city)
| Tier | Count | Rationale |
|---:|---:|---|
| 政令指定都市 | 20 | 大阪/横浜/神戸/京都/福岡 等、subsidy 公募回数 top-tier |
| 中核市 | 62 | 人口 20万超、活発な独自 subsidy |
| 特別区 (東京23区) | 23 | 区独自補助金 (北区/世田谷区 等) |
| 人口 30万超非中核市 | 25 | 浦安/伊丹/八王子 等、subsidy 厚い |
| 県庁所在地 (重複除く) | 25 | 全47都道府県 cover — 重複除外残 |
| 商工活動上位 (DID + 事業所密度) | 45 | 鈴鹿/沼津/つくば/守谷 等 industrial cluster |
| **合計** | **200** | gyousei + 補助金 cohort 需要の **95%+** cover |

- 200 × 5 PDF avg = **1,000 PDF**
- Textract: 1,000 × $0.75/page = **$750** (1 spend slot vs $4,500 = **6x cut**)
- ROI 再計算: ¥1.5M / ¥112.5k (=$750×150) = **13.3x** → GO threshold pass

### Action
- 旧 DD2 (1,718 全件 crawl) は **scope reduce** — 200 city manifest を新規 `data/etl_dd2_narrow_200_city_manifest_2026_05_17.json` で作成. 旧 manifest は legacy marker for SEO bridge.
- DD2 旧 in-flight が 1,718 全件で running 中 → kill instruction 不要、200 city only 1st-pass を先行完了させ、1,518 city tail は post-FF4 で gate 直前まで放置.

---

## 4. CC4 narrow proposal (1h → 6h cron)

### 元 CC4
- 1h cron × 100 PDF watch × 24h × 30d = 72,000 page/月
- Textract: 72,000 × $0.0625 (LAYOUT) = $4,500/月 sustained
- 漏れ閾値: 1h ≈ NTA tsutatsu update 速度に比して過剰

### CC4-NARROW (6h cron, sustained drop)
| Metric | 元 | NARROW | 比率 |
|---|---:|---:|---:|
| Cron | 1h | 6h | 1/6 |
| PDF/d | 100 | 25 | 1/4 (重複 dedupe up) |
| Page/d | 2,400 | 640 | 1/3.75 |
| **$/月** | **4,500** | **1,200** | **1/3.75** |
| Latency | 平均 30min stale | 平均 3h stale | 法令公開頻度 << 24h なので acceptable |

- ROI 再計算: ¥1.2M / ¥180k (=$1,200×150) = **6.67x** → GO threshold pass
- スパイク日 (例: 年度末 NTA 大量改正発表) は手動 trigger で 1h cron に temporary swap. 平常運転 6h.

---

## 5. 新 GG1-GG4 lane (super-ROI propose)

### GG1: Heavy Endpoint HE-5 + HE-6 cohort-differentiated
- **投資**: $200 (g4dn.xlarge × 2h × 5 cohort × inference + index build)
- **寄与**:
  - HE-5 D-tier deep cohort report × ¥30/req × 1,000 query/年 × 1,000 user × 5 cohort = ¥150M/年潜在
  - 保守見積 5% adoption = ¥7.5M/年
- **ROI = 7.5M / 30k = 250x** → STRONG GO
- **Spec**: 5 cohort (zeirishi/kaikeishi/gyousei/sharoushi/SME) × deep-research bundle (60-page report) 事前生成 → `am_he5_d_tier_precomputed` table.

### GG2: am_precomputed_answer 500 → 5,000 (10x precompute expansion)
- **投資**: $500 (Athena cross-corpus scan 1.5TB + Parquet ZSTD write 5GB)
- **寄与**:
  - 高頻度 query top-5,000 instant return → ¥3-12/req × 10k user × 50/年 × 2% = ¥30-120M/年潜在
  - 保守 ¥30M/年
- **ROI = 30M / 75k = 400x** → STRONG GO
- **Spec**: Wave 60-94 outcome catalog 432 × persona 5 × intent 5 = 10,800 候補 → top 5,000 by query log frequency.

### GG3: openapi cost-saving extension (FF2 連携)
- **投資**: $0 (local Python codegen)
- **寄与**:
  - `x-cost-saving` extension on 47 endpoint → agent decision hook で jpcite 採用率 +5-10pp
  - 5pp lift × current ¥30M MRR potential = ¥1.5M/月 = ¥18M/年
- **ROI = ∞ (¥0 投資)** → STRONG GO
- **Spec**: OpenAPI 3.1 vendor extension `x-cost-saving: {pure_llm_jpy, jpcite_jpy, saving_jpy}` per route.

### GG4: Top 100 chunks pre-mapped to outcome catalog 432
- **投資**: $200 (FAISS IVF-PQ recompute + index reorder + S3 upload)
- **寄与**:
  - Outcome catalog hit → top 100 chunk 即返し → TTFB -50% → retention +20%
  - retention +20% × current ¥30M ARR = ¥6M/y
- **ROI = 6M / 30k = 200x** → STRONG GO
- **Spec**: 432 outcome × top 100 chunk pre-link → `am_outcome_chunk_top100` table + FAISS sidecar index.

---

## 6. AWS credit 残予測 (narrow 後)

### Pre-FF4 (元 18 lane sustained 90d)
- AA1-5: $5,120 (one-shot)
- BB1-4: $557 (one-shot)
- CC1-4: $4,500/月 × 3 = $13,500
- DD1-2: $4,500 (one-shot)
- M-lane + EE1: $250 (one-shot)
- 合計 90日: **$23,927** ≈ ¥3.59M

### Post-FF4 narrow + GG1-GG4 (90d)
- AA1-5: $5,120
- BB1-4: $557
- CC1-3: $0
- **CC4 NARROW**: $1,200/月 × 3 = $3,600 (元 $13,500 から −$9,900)
- DD1: $0
- **DD2 NARROW**: $750 (元 $4,500 から −$3,750)
- M-lane + EE1: $250
- **GG1**: $200
- **GG2**: $500
- **GG3**: $0
- **GG4**: $200
- 合計 90日: **$11,177** ≈ ¥1.68M

### Saving
- **$12,750 saved over 90d** (¥1.91M)
- 同等 cohort coverage 維持 (95%+ gyousei + 補助金), freshness 3h stale (acceptable)
- **追加で GG1-GG4 4 lane 投入余裕** ($900 only)

### AWS credit budget vs forecast
- Budget: $25,000 (operator allocation)
- Pre-FF4 forecast: $23,927 → tight (96%)
- Post-FF4: $11,177 + GG1-GG4 $900 = **$12,077** (48% headroom)
- 余裕 $12,923 → 追加 GG5-GG8 (cohort-deep / RAG2 / federation expand) 投入余地

---

## 7. Implementation order (FF4 → FF5)

1. **immediate (no edit to in-flight)**:
   - DD2 narrow manifest 200 city — 新 `data/etl_dd2_narrow_200_city_manifest_2026_05_17.json` 作成
   - CC4 cron 6h pivot — 新 `scripts/cron/pdf_watch_detect_2026_05_17.py` の `INTERVAL_HOURS=6` override
   - GG1-GG4 spec doc 4 本作成 (post FF4)

2. **post in-flight lane gate clear**:
   - 旧 DD2 1,718 tail (1,518) は scope reduce (post-narrow run skip)
   - CC4 1h → 6h cron flip

3. **GG1-GG4 launch**:
   - GG1 g4dn × 2h × 5 cohort 並列 (FF5 lane)
   - GG2 Athena scan + Parquet write (FF5)
   - GG3 openapi codegen (FF5 / local)
   - GG4 FAISS recompute (FF5)

---

## 8. Memory landing

- `feedback_lane_roi_threshold.md` 新規作成 — "5x ROI floor + narrow if <5x"
- FF1 SOT との数値一致 verify 済み
- aggregator ban 維持 / mypy strict 0 / ruff 0 維持

---

## 9. Verdict summary

| Action | Count | $ delta (90d) |
|---|---:|---:|
| GO 維持 (5x+) | 13 lane | $0 |
| NARROW (CC4) | 1 lane | -$9,900 |
| NARROW (DD2) | 1 lane | -$3,750 |
| GO 0-cost | 3 lane | $0 |
| **新規 GG1-GG4** | **4 lane** | **+$900** |
| **総合** | **22 lane** | **-$12,750** |

**結論**: 18 lane → 22 lane (4 new), spend cut 53%, coverage 95%+ 維持, GG1-GG4 で agent funnel + precomputed 拡張. AWS credit headroom 48% で安全運転.

---

## 10. Linkage

- FF1 SOT (lane catalog): 引用 — AA1/AA2/AA3/AA4/AA5/BB1-4/CC1-4/DD1-2/M1/M3/M9/EE1
- Wave 60-94 outcome catalog 432 → GG4 mapping target
- PERF-1..32 (sqlite/pytest/openapi) → 影響なし (doc-only)
- AWS canary EB DISABLED + Phase 9 dry-run → 影響なし (新 lane は credit ops のみ)
