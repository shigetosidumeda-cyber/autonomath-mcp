# SEO Metrics -- What to Track Weekly

**Owner**: 梅田茂利 (info@bookyou.net) -- solo zero-touch
**Cadence**: 15 min Monday morning over coffee. No real-time dashboard.
**Related**: `docs/runbook/search_console_setup.md`, `docs/seo_strategy.md`,
`monitoring/sla_targets.md`

The whole acquisition funnel is organic + zero ads, so SEO surface health
**is** the growth metric. This document lists the 8 numbers worth
checking weekly and the 3 alarm thresholds that warrant action.

Five rules:

1. Look at it weekly, not daily. Search Console smooths over 16-day
   windows; daily noise is meaningless.
2. Pull the data **from the source UI**. We do not run a Search Console
   API extraction yet (rate-limited, low ROI for solo ops).
3. Numbers without trend are useless. Compare week-N to week-N-1.
4. If a metric crosses an alarm threshold below, follow the linked
   diagnostic step. Do NOT panic-edit pages.
5. Publish the rolling 4-week numbers internally only -- they belong
   in `analytics/seo_weekly.tsv` (manual paste OK), not on the public
   site.

---

## 1. The 8 weekly numbers

Pull these from **Google Search Console** (GSC) and **Bing Webmaster
Tools** (BWT) every Monday. Time range = "Last 7 days" unless noted.

| # | Metric | Source | Where in UI | Why it matters |
|---|---|---|---|---|
| M1 | **Total impressions** | GSC | Performance → Search results → "Total impressions" | Top of funnel. Are we showing up at all? |
| M2 | **Total clicks** | GSC | Performance → "Total clicks" | Mid funnel. Are SERP titles + meta compelling? |
| M3 | **Avg CTR** | GSC | Performance → "Average CTR" | Click yield per impression. Below 1.5% = title rewrite candidate. |
| M4 | **Avg position** | GSC | Performance → "Average position" | Where we rank. Position 11-20 = page 2; aim sub-10. |
| M5 | **Indexed pages** | GSC | Pages → "Indexed" tab count | Discovery progress. Should grow weekly until plateau ~12k. |
| M6 | **"Crawled - currently not indexed"** | GSC | Pages → "Why pages aren't indexed" → that bucket | Quality signal. Spike = thin-content cluster found. |
| M7 | **Bing impressions** | BWT | Reports & data → Search performance | Cross-check vs Google -- if Bing >> Google, IndexNow is paying off. |
| M8 | **IndexNow submissions accepted** | BWT | Sitemaps → IndexNow tab | Confirms the cron is working (should show daily activity). |

Alternative cross-checks (already collected automatically):

- `analytics/cf_daily.jsonl` -- Cloudflare unique visitors. Independent
  proxy for organic traffic; should track GSC clicks within ±20%.
- `analytics/indexnow_log.jsonl` -- raw cron output (status codes per
  batch). If M8 is zero in BWT but this log shows status=200, the key
  file at `/<key>.txt` may be missing.

---

## 2. Top queries (the qualitative signal)

Each Monday, also screenshot the **Top 25 queries by impression** from
GSC Performance → Queries tab. Look for:

- New head-term queries (`<制度名> 申請`, `<制度名> 対象`) appearing.
- Queries we want to rank for but don't (e.g. `補助金 検索 API`).
- Branded query trend (`税務会計AI`, `zeimu-kaikei`) -- proxy for
  word-of-mouth + LLM citation rate.
- Aggregator-style queries (`補助金 一覧`, `助成金 まとめ`) -- if we
  rank 50+ that's signal we are gaining authority.

Save the screenshot to `analytics/seo_screenshots/<YYYY-MM-DD>.png` if
you want longitudinal evidence. Optional.

---

## 3. Alarm thresholds (the only 3 that matter)

### A1 -- Indexed pages (M5) drops week over week

Threshold: `M5_this_week < 0.95 * M5_last_week`.

Diagnostic:

1. GSC → Pages → "Why pages aren't indexed" → look for new buckets that
   grew sharply.
2. Common causes:
   - Sitemap shard 404 (e.g. `sitemap-cross.xml` if not generated).
   - Cloudflare Pages deploy stripped or renamed pages.
   - `robots.txt` accidentally added `Disallow:` for a dir.
   - A new generator script wrote `<meta name="robots" content="noindex">`
     onto pages that should be indexable.

### A2 -- Avg CTR (M3) drops below 1.0% for 2 consecutive weeks

Diagnostic:

1. GSC Performance → Queries -- find the lowest-CTR queries we have
   visible impressions for.
2. Likely causes:
   - Generic / templated `<title>`. Per-program pages should embed the
     program name + amount, not "税務会計AI".
   - Meta description missing on a generator-created page.
3. Fix: regenerate the affected shard's `<title>` + meta strategy in the
   page generator script (not in the rendered HTML directly -- those get
   overwritten on next regen).

### A3 -- IndexNow daily submission accepted == 0 for 3 consecutive days

Threshold: `analytics/indexnow_log.jsonl` shows no `status=200`/`202`
rows for 3 days in a row.

Diagnostic:

1. `curl -fsS https://zeimu-kaikei.ai/<INDEXNOW_KEY>.txt` -- key file
   reachable? If 404, redeploy the file.
2. GitHub Actions → `index-now-cron` → last run logs. Look for "shard
   parse error" or "INDEXNOW_KEY unset".
3. If the cron itself succeeded but BWT shows zero, the key file may be
   stale (was rotated without updating `INDEXNOW_KEY` secret). Match
   the secret to the file content exactly.

---

## 4. Theoretical max + indexing trajectory

Tracked weekly against the indexing-timeline table in
`docs/runbook/search_console_setup.md §9`. Reproduced for reference:

| Week | Google indexed (target) | Bing indexed (target) |
|---|---:|---:|
| 1 | 200-500 | 800-1,500 |
| 2 | 1,000-2,500 | 3,000-6,000 |
| 4 | 3,500-7,000 | 8,000-11,000 |
| 8 | 7,000-10,000 | 11,000-12,000 |
| 12 | 10,500-12,000 | 12,000 |

Theoretical max: ~12,212 (sitemap submitted total). If at week 12 we are
under 7,000 indexed in Google, the bottleneck is not crawl rate -- it is
content quality classification ("thin / duplicate"). At that point the
fix is in the content generator, not in webmaster tools.

---

## 5. Per-shard indexing breakdown

Once GSC has 4+ weeks of data, GSC → Sitemaps → click each shard URL --
it shows "Submitted: N" and "Indexed: M" per shard. The healthy ratio:

| Shard | Submitted | Healthy indexed ratio |
|---|---:|---|
| sitemap.xml (cornerstone) | ~74 | 95-100% |
| sitemap-pages.xml (news) | varies | 80-100% |
| sitemap-prefectures.xml | 48 | 90-100% |
| sitemap-audiences.xml | 12 | 90-100% |
| sitemap-qa.xml | 99 | 70-95% |
| sitemap-industries.xml | 1,027 | 50-85% |
| sitemap-programs.xml | 10,951 | 40-80% |

Per-program is the lowest because long-tail subsidies have low search
volume; Google's quality classifier deprioritises pages with no
inbound links + thin distinct content. That is OK -- the moat is the
**LLM corpus** (GPTBot / ClaudeBot / OAI-SearchBot crawl all pages
regardless of Google indexing decisions).

---

## 6. What NOT to track

- **Domain Authority / Page Authority** (Moz/Ahrefs metrics). We block
  AhrefsBot + SemrushBot in `robots.txt`, so these scores will be
  artificially deflated. Ignore them.
- **Backlink count**. Same reason -- backlink crawlers are blocked.
- **Real-time GSC numbers**. GSC has a 16-day finalisation window;
  daily numbers fluctuate ±30% retroactively.
- **Bounce rate / time on page** -- we do not run JS analytics
  beacons, so we do not have this data, and we do not want it
  (privacy posture, see `site/privacy.html`).

---

## 7. Quarterly review

Once per quarter, look at the rolling 13-week trend on M1-M5 and answer:

1. Are we above or below the theoretical-max trajectory?
2. Top 50 queries -- which 5 are highest-impression but lowest-CTR?
   Rewrite those page titles.
3. "Crawled - currently not indexed" bucket -- which shard is filling
   it? That shard's content template is too thin; expand it.

If all three answers are "fine", do nothing. Solo zero-touch ops means
you don't tinker without signal.
