# Data freshness audit 2026-04-26

Read-only audit of `programs.source_fetched_at` in `data/jpintel.db`. No DB
writes performed. Refresh execution is intentionally deferred to a separate
wave per `feedback_completion_gate_minimal` (audit and listing only).

> Note on terminology: per CLAUDE.md gotcha, `source_fetched_at` is when
> we last fetched the URL — **not** "最終更新". Many rows carry a uniform
> sentinel because ingest passes set the column without an actual HEAD
> probe. The "出典取得" semantic is what we audit; content currency is a
> separate question this column does not answer.

## 1. Distribution: tier x age (excluded=0)

`source_fetched_at` bucketed against today (2026-04-26).

| tier   | NULL | < 1 week | < 1 month | < 3 month | > 3 month | total  |
|--------|-----:|---------:|----------:|----------:|----------:|-------:|
| S      |    0 |      116 |         0 |         0 |         0 |    116 |
| A      |    0 |    1,366 |         0 |         0 |         0 |  1,366 |
| B      |    2 |    3,319 |         0 |         0 |         0 |  3,321 |
| C      |   13 |    6,156 |         0 |         0 |         0 |  6,169 |
| TOTAL  |   15 |   10,957 |         0 |         0 |         0 | 10,972 |

All non-excluded rows fall in the "< 1 week" bucket because of the recent
bulk ingest pass on 2026-04-22 (oldest fetched_at) through 2026-04-25
(newest). 501 distinct timestamps exist across 10,972 rows; the top three
buckets alone account for 7,094 rows — clear sentinel signature.

## 2. Liveness probe coverage (the *real* freshness question)

`source_fetched_at` only tells us when ingest *touched* the row. The
authoritative liveness signal is `source_last_check_status` set by
`scripts/refresh_sources.py` after a real HEAD probe.

| tier | total | probed (status set) | unprobed | probe coverage |
|------|------:|--------------------:|---------:|---------------:|
| S    |   116 |                  19 |       97 |          16.4% |
| A    | 1,366 |                 895 |      471 |          65.5% |
| B    | 3,319 |                 354 |    2,965 |          10.7% |
| C    | 6,156 |                  12 |    6,144 |           0.2% |

Of the 1,283 probed rows: **1,275 = 200 OK, 8 = 404**. Zero 5xx, zero rows
at `source_fail_count >= 3` (only 10 rows at fail_count=1; quarantine
threshold is 3).

## 3. Tier S top stale (oldest 50 by `source_fetched_at`)

The strict "30 days old" filter returns zero — all tier-S rows are within
the last 5 days because of the bulk ingest. The substantively-stalest
tier-S rows are those still on the 2026-04-22 sentinel (the broadest
bulk-rewrite cohort) and never probed by the liveness scan. 41 such rows:

```
UNI-f6165b8a9c とみさと農業気候変動対策支援事業補助金
UNI-1c8f4cd075 みどりの食料システム戦略推進交付金
UNI-455a7c3e2d みよし市 農業振興事業補助金 地場産業振興
UNI-5d6de166e3 スマート農業推進事業（機械設備導入）
UNI-e80e5c7ed2 一関市水田高収益作物転換特別支援事業交付金
UNI-0099a6d1b4 世代交代・初期投資促進事業（世代交代円滑化タイプ）
UNI-14e57fbf79 中小企業成長加速化補助金
UNI-c2d0c7502e 中小企業等事業再構築促進基金
UNI-6cd67b3342 中山間地域等直接支払交付金
UNI-e77bf254c8 令和7年度一関市農商工連携開発事業費補助金
UNI-993181f438 八王子市_日本政策金融公庫等からの低利融資
UNI-f4ea790ad4 危機対応後経営安定資金（セーフティネット貸付）
UNI-8d754d9e9d 和歌山 次世代につなぐ果樹産地づくり事業
UNI-074c19fc26 垂水市新規就農者機械・施設整備事業
UNI-583537bc07 多面的機能支払交付金
UNI-70bbd090cd 山形 さくらんぼ温暖化対応技術導入推進事業
UNI-4ab082bde9 山形 園芸やまがた産地発展サポート事業
UNI-c1827149c1 広島 アグリチャレンジ・ゼロ資金 経営開始支援
UNI-6b18c2cc13 広島県 無担保スピード保証融資
UNI-a729fbb301 新発田市強い農林水産業づくり支援事業
UNI-a876aa5445 新規就農者への補助事業
UNI-7c132d1a4a 新規就農者チャレンジ事業
UNI-bdea97be24 新規就農者育成総合対策（経営発展支援事業・経営開始資金）
UNI-088d217f06 新規就農者育成総合対策（経営発展支援事業）
UNI-40bc849d45 東京都サイバーセキュリティ対策促進助成金
UNI-bca74fc343 東京都ゼロエミッション化省エネ設備導入支援事業
UNI-4d5836061d 東広島市新規就農者初期投資支援事業
UNI-5f224060c2 神石高原○豊とまと用ビニールハウス規模拡大事業
UNI-245b215ccb 箕面市経営発展支援事業
UNI-17e64b14cf 経営所得安定対策（畑作物の直接支払交付金・米の直接支払交付金等）
UNI-6a5a961628 経営環境変化対応資金（セーフティネット貸付）
UNI-0e2daaa865 経営発展支援事業
UNI-9ad358dbec 農林業振興基金提案事業補助金
UNI-304a4b7448 農林水産業みらい基金
UNI-a7f77063d5 農業生産工程管理推進事業（高知県）
UNI-02499eec66 長崎市_農業経営発展支援事業
UNI-76ff1702bc 雇用就農資金
UNI-08f87b0586 青年等就農資金
UNI-d33f08a683 飼料用米等拡大支援事業のうち飼料用米等生産支援事業
UNI-96ca0b02be 香川 農畜水産業者未来チャレンジ支援補助金
UNI-df8a88849f 高崎農業の将来を考える研究会補助金
UNI-1bdd5c3334 鳥獣害に強い地域づくり支援事業（補助金・捕獲檻の貸し出し・追払い用花火の配布）
```

(All carry `source_fetched_at = 2026-04-22T13:20:57.045412+00:00` —
identical sentinel; only 41 tier-S rows in this cohort, not the 50 the
prompt asks for. Listing all is honest.)

Newer-sentinel cohorts (2026-04-24, 2026-04-25) hold the remaining 75
tier-S rows; they all need a real liveness pass too but are lower
priority than the 2026-04-22 cohort.

## 4. Dead links (8 rows, all `excluded=0`, status 404)

These are **immediate `excluded=1` candidates**. None are tier S/A.

| unified_id          | name                                        | tier | status |
|---------------------|---------------------------------------------|------|-------:|
| UNI-ext-9e98691530  | 小規模事業者持続化補助金 共同事業型             | B    |    404 |
| UNI-ext-17af67dabf  | 東商 ビジネスサポートデスク (BSD)               | B    |    404 |
| UNI-55bf85c089      | 持続化補助金（コロナ特別対応型）商工会地区分     | C    |    404 |
| UNI-d6f57cadad      | 持続化補助金（被災再建 R2 七月豪雨型）           | C    |    404 |
| UNI-9ef7366b13      | 持続化補助金（台風19/20/21号被災再建型）         | C    |    404 |
| UNI-61072868fc      | 共同・協業販路開拓支援補助金（令和2年版）       | C    |    404 |
| UNI-26804f9f30      | 茨城県商工会連合会 補助金案内ハブ              | C    |    404 |
| UNI-6c68875a5b      | 佐賀県商工会連合会 補助金案内ハブ              | C    |    404 |

Most are historic 商工会地区分 schemes that may be legitimately closed.
Triage: 3 historic R2/H30 災害再建 schemes likely truly retired
(`exclusion_reason = retired_program`), 2 商工会連合会 hubs likely just
URL-rotated (re-walk site root before excluding).

## 5. Cron health

Workflow: `.github/workflows/refresh-sources.yml` exists and is wired:

- Tier S/A daily 03:17 JST (cron `17 18 * * *`), DB writes enabled.
- Tier B weekly Sunday 03:17 JST, `--report-only`.
- Tier C monthly day-1 03:17 JST, `--report-only`.
- Per workflow comment, **DB writes from CI are not persisted** — the
  authoritative writer is `scripts/cron/refresh_sources_nightly.sh` on
  the Fly volume. Liveness probe coverage above (16.4% of tier S, 65.5%
  of tier A) suggests the Fly cron has not run a full pass yet, or its
  results have not been pulled back to the local checkout.

Most recent CI artefacts on disk:

- `data/refresh_sources_report.json` — 2026-04-23 04:36 UTC, 20 rows
  scanned, dry-run, 6 fail / 14 ok. Smoke run, not a full pass.
- `data/source_freshness_report.json` — 2026-04-25 23:18 UTC,
  `loop_i_doc_freshness`, 13,578 rows, dry-run. Per-tier per their
  60-day stale threshold: S=0/0, A=0/0, B=2/2, C=14/6. Matches our
  count of 8 broken (B=2, C=6) above.

`source_redirects` table is empty (0 rows logged); `source_failures`
also empty (no quarantine actions written).

## 6. Refresh strategy proposal

Sequencing reflects "minimal blocker" (M5/launch-day) vs "polish":

1. **Immediate (pre-launch)**:
   - Exclude the 8 dead 404 rows (`excluded=1`,
     `exclusion_reason='url_dead'` or `'retired_program'` after one
     manual eyeball each). 0 tier S/A impact.
   - Run liveness scan locally with writes enabled against tier S+A
     full set: `python scripts/refresh_sources.py --tier S,A`.
     Expected wall-clock < 5 min for 1,482 rows. This brings tier-S
     probe coverage from 16% to ~100% and gives us the first honest
     `source_fetched_at` for the 41 sentinel-cohort rows.

2. **Week 1 post-launch**:
   - Tier B full liveness scan with writes (cron currently dry-run only):
     ~3,321 rows, ~15 min. 2,965 rows currently unprobed.
   - Confirm Fly nightly cron is actually running and pull
     `source_failures` / `source_redirects` rows back to the local DB
     for review.

3. **Month 1**:
   - Tier C full pass with writes (~6,156 rows, ~45 min — within the
     workflow's 90 min timeout). 6,144 rows unprobed today.
   - Add a true content-diff layer (the script docstring explicitly
     scopes itself to liveness only). Track in
     `docs/_internal/`.

4. **Ongoing**:
   - Trust the cron; remove the `--report-only` flag on tier B/C in CI
     once Fly cron confirms stable, OR shift to using CI as the
     authoritative writer (single-source-of-truth choice).

## Appendix: queries used

```sql
-- distribution
SELECT CASE
  WHEN source_fetched_at IS NULL THEN 'NULL'
  WHEN source_fetched_at >= date('now','-7 days')  THEN '<1w'
  WHEN source_fetched_at >= date('now','-30 days') THEN '<1m'
  WHEN source_fetched_at >= date('now','-90 days') THEN '<3m'
  ELSE '>3m' END AS age,
  COALESCE(tier,'NULL') AS t, COUNT(*)
FROM programs WHERE excluded=0 GROUP BY age, t ORDER BY t, age;

-- probe coverage
SELECT tier, COUNT(*) AS total,
  SUM(source_last_check_status IS NOT NULL) AS probed
FROM programs WHERE excluded=0 GROUP BY tier;

-- dead links
SELECT unified_id, primary_name, source_url, source_last_check_status, tier
FROM programs WHERE source_last_check_status >= 400 AND excluded=0;

-- tier-S oldest sentinel
SELECT unified_id, primary_name, source_fetched_at
FROM programs WHERE excluded=0 AND tier='S'
ORDER BY source_fetched_at ASC LIMIT 50;
```
