# CC4-NARROW — PDF watch 1h → 6h cron (sustained burn drop) (2026-05-17)

**[lane:solo]** — doc only / 実装は FF5.

## 1. Motive

元 CC4 (1h cron × 100 PDF/d × Textract sustained $4,500/月) ROI = **1.78x** (¥1.2M/月 ÷ ¥675k = 1.78x) → 5x threshold 未達.

FF4 narrow: 6h cron → 1/3.75 burn drop, 平均 3h stale (acceptable, 法令公開頻度 << 24h).

## 2. Cost recalc

| Metric | 元 1h cron | NARROW 6h cron | 比率 |
|---|---:|---:|---:|
| Cron interval | 1h | 6h | 1/6 |
| PDF /d | 100 | 25 (重複 dedupe up) | 1/4 |
| Page /d (Textract LAYOUT) | 2,400 | 640 | 1/3.75 |
| **$/月 sustained** | **4,500** | **1,200** | **1/3.75** |
| **$/月 saved** | — | **−3,300** | |
| Mean stale | 30 min | 3 h | acceptable |
| Worst stale | 1 h | 6 h | acceptable (gov PDF publish < 24h cadence) |

## 3. Spike trigger

- 年度末 NTA 大量改正発表 / G-MIS deadline (3月末 / 9月末) → 手動 trigger で 1h cron に 1-2 week temporary swap
- Normal day: 6h cron 固定

## 4. ROI

¥1.2M/月 × 12 = ¥14.4M/y
¥1.2M/月 × 12 / ¥1.44M/y ($1,200 × 12 × 150 = ¥2.16M) = **6.67x** → GO

修正: ¥14.4M / ¥2.16M = **6.67x** → GO threshold pass

## 5. Implementation

- `scripts/cron/pdf_watch_detect_2026_05_17.py` の `INTERVAL_HOURS=6` override (元 1)
- spike override flag: `CC4_SPIKE_MODE=1` 時 INTERVAL_HOURS=1 fallback
- GitHub Actions cron `0 */6 * * *` 設定

## 6. Smoke + gate

- 6h cron で 1 week dry-run (no Textract spend, log only) → coverage 確認
- mypy strict 0 / ruff 0
- safe_commit.sh

## 7. Risk

- 法令 publish の midnight burst (e.g., 4/1 0:00) → 1h cron に 4/1 only 手動 swap
- new PDF detect 漏れ → existing detection logic 維持 (hash-based dedupe)

## 8. Rollback

- INTERVAL_HOURS=1 戻し (1 line revert)
- 元 burn rate 復帰 ($4,500/月)

## 9. Linkage

- AA1 NTA crawl (one-shot $5,000) は完了 → CC4 は incremental watch
- DD2-NARROW と並行で gyousei + 補助金 cohort 需要 cover
