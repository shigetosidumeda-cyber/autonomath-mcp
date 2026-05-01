# Search Console + Bing Webmaster + Yandex Setup Runbook -- jpcite

**Owner**: 梅田茂利 (info@bookyou.net) -- solo zero-touch
**Last reviewed**: 2026-04-29
**Domain**: `jpcite.com`
**Related**: `docs/seo_strategy.md`, `docs/_internal/seo_technical_audit.md`, `monitoring/seo_metrics.md`

The site has ~13k indexable URLs across 9 sitemap shards. Without webmaster
tool registration + IndexNow pinging, Google's discovery crawler converges
on only ~1-3 % of those in the first month (long-tail subsidy pages get
deprioritised vs. authority sites). This runbook is the single-operator
playbook for getting the full corpus indexed in week 1-4 instead of
month 6.

Ten-second summary:

1. Verify domain at Google + Bing + Yandex via DNS TXT records (5 min).
2. Submit `sitemap-index.xml` once per tool (3 min).
3. Upload IndexNow key file to site root (1 min).
4. Push the IndexNow cron secret to GitHub Actions (1 min).
5. Watch `monitoring/seo_metrics.md` weekly. Done.

---

## 1. Indexable corpus -- what we are submitting

| Sitemap shard | URLs | Contents |
|---|---:|---|
| `sitemap.xml` | 77 | About / pricing / docs / EN mirror / hand-maintained |
| `sitemap-programs.xml` | 1,413 | High-signal per-program HTML (`/programs/{slug}.html`) |
| `sitemap-prefectures.xml` | 48 | 47 都道府県 + index |
| `sitemap-audiences.xml` | 16 | Audience landing pages |
| `sitemap-cross.xml` | 47 | Cross-topic landing pages |
| `sitemap-industries.xml` | 22 | Industry landing pages |
| `sitemap-qa.xml` | 104 | Long-tail QA pages |
| `sitemap-pages.xml` | 1 | News index |
| `sitemap-structured.xml` | 1,413 | JSON-LD shards for structured-data discovery |
| `docs/sitemap.xml` | 36 | MkDocs documentation pages |
| **Total submitted** | **3,177** | includes structured shard while below Pages file budget |

`site/sitemap-index.xml` references the public shards including
`sitemap-structured.xml`. Keep the structured shard in the index while it is
below the Cloudflare Pages file budget; move it to R2 only if corpus growth
requires it.

Verified 2026-05-01: the sitemap index references only shards present on disk,
including `sitemap-cross.xml` and `sitemap-structured.xml`.

---

## 2. Required environment + GitHub secrets

Add these to **GitHub repository secrets** (Settings → Secrets and variables →
Actions → New repository secret) -- the IndexNow cron is the only one that
needs them at runtime. Webmaster tool dashboards are read-only operator
surfaces, no programmatic access required for v1.

```
INDEXNOW_KEY             <output of `python -c "import secrets; print(secrets.token_urlsafe(32))"`>
                         Pre-generated: xqb3GHUXXtVxaLjNldSqFyxGgMITszJ_akOrgDTsDG4
                         (replace with your own; this one is committed to docs)
INDEXNOW_HOST            jpcite.com
```

Optional (advanced -- only if you later want programmatic Search Console
API access; v1 does NOT require these):

```
GOOGLE_SEARCH_CONSOLE_PROPERTY    sc-domain:jpcite.com
GSC_SERVICE_ACCOUNT_JSON          <base64 of service-account JSON>
```

---

## 3. Google Search Console -- domain property

### 3.1 Why domain (not URL prefix) property

Domain property covers `https://`, `www.`, all subdomains, and the EN
mirror (`/en/...` is same domain so it's automatic). URL-prefix would
require 4-5 separate verifications. Pick **Domain**.

### 3.2 Steps

1. Open <https://search.google.com/search-console> with the Google account
   you intend to use long-term (Bookyou株式会社 ops account, NOT a
   personal account that might be deleted).
2. Click **Add property** → **Domain**.
3. Enter `jpcite.com` (no scheme, no path, no `www`).
4. Google shows a TXT record like:

   ```
   Name:   @          (or jpcite.com depending on DNS provider UI)
   Type:   TXT
   Value:  google-site-verification=<RANDOM-44-CHAR-STRING>
   TTL:    3600
   ```

5. **OPERATOR ACTION**: log into Cloudflare DNS for `jpcite.com`.
   (Cloudflare → jpcite.com → DNS → Records → Add record.)
   Add the TXT record verbatim. Save.
6. Wait 1-5 min for DNS propagation. Verify with:

   ```bash
   dig +short TXT jpcite.com | grep google-site-verification
   ```

7. Back in Search Console, click **Verify**. Should succeed instantly.

### 3.3 Submit sitemap

1. In Search Console left nav: **Sitemaps**.
2. Enter `sitemap-index.xml` (full URL is auto-prefixed:
   `https://jpcite.com/sitemap-index.xml`).
3. Click **Submit**. Status should flip to **Success** within 24 h, then
   show URL counts per shard over the following 1-7 days.

### 3.4 Request indexing for cornerstone pages (one-time)

Submit these ~12 cornerstone URLs via **URL Inspection → Request Indexing**
(Search Console rate-limits to ~10/day per property; do them across 2
days). This forces Google to crawl them within 24 h instead of waiting
for sitemap-driven discovery.

```
https://jpcite.com/
https://jpcite.com/about.html
https://jpcite.com/pricing.html
https://jpcite.com/compare.html
https://jpcite.com/docs/
https://jpcite.com/prefectures/
https://jpcite.com/programs/
https://jpcite.com/qa/
https://jpcite.com/news/
https://jpcite.com/audiences/
https://jpcite.com/en/
https://jpcite.com/en/about.html
```

After these 12 are indexed, internal linking + sitemap shards do the rest
without manual nudging.

---

## 4. Bing Webmaster Tools

Bing powers DuckDuckGo + ChatGPT search results, so this is **not**
optional for organic LLM-era acquisition.

### 4.1 Steps

1. Open <https://www.bing.com/webmasters> with the same Bookyou ops
   Google account (Bing accepts Google sign-in; do NOT create a separate
   Microsoft account).
2. Click **Add a site**.
3. Pick the **Import from Google Search Console** option -- it copies
   the verification + sitemap in one step. (Skip steps 4.2 and 4.3 if
   import succeeds.)
4. If GSC import does not work, fall back to manual:

### 4.2 Manual verification (fallback only)

Bing accepts three methods. Use **DNS TXT record** to be consistent with
Google:

1. Bing shows a TXT value like `<RANDOM-32-CHAR>`.
2. **OPERATOR ACTION**: Cloudflare DNS → add TXT record:

   ```
   Name:   @
   Type:   TXT
   Value:  <BING-VERIFICATION-STRING>
   TTL:    3600
   ```

3. Wait + verify with `dig +short TXT jpcite.com`.
4. Click **Verify** in Bing.

Alternative (HTML file) only if you cannot edit DNS: place
`BingSiteAuth.xml` at site root. The site/ tree is read-only per project
constraints, so prefer DNS.

### 4.3 Submit sitemap

1. **Sitemaps** in left nav.
2. Submit `https://jpcite.com/sitemap-index.xml`.

### 4.4 IndexNow registration (gives the key away)

Bing is the host of IndexNow API (`api.indexnow.org` and
`bing.com/indexnow`). Once your IndexNow key file is uploaded to
`https://jpcite.com/<INDEXNOW_KEY>.txt` (see §7), Bing auto-discovers
it and you get a green "IndexNow enabled" badge. No manual step needed.

---

## 5. Yandex Webmaster (low priority, free)

Yandex serves ~0.3 % of JP search traffic but it is free, takes 5 min,
and surfaces hreflang issues that Google + Bing miss.

### 5.1 Steps

1. Open <https://webmaster.yandex.com>. Sign in with Google or create a
   Yandex account.
2. **Add site** → enter `https://jpcite.com`.
3. Pick **DNS verification** method.
4. **OPERATOR ACTION**: Cloudflare DNS → add TXT record:

   ```
   Name:   @
   Type:   TXT
   Value:  yandex-verification: <RANDOM-16-CHAR>
   TTL:    3600
   ```

5. Verify, then submit `sitemap-index.xml`.

### 5.2 Note on robots.txt

Our `site/robots.txt` blocks `YandexBot` (it is listed under "Aggressive /
low-value crawlers"). **Yandex Webmaster verification still works** -- the
verification fetcher uses a different user-agent. Search rankings will
NOT happen until you flip `YandexBot` from `Disallow: /` to `Allow: /` in
robots.txt. Decision deferred: low ROI vs. crawl-budget noise. If you
want Yandex SERP coverage, edit `site/robots.txt` (only file in `site/`
the runbook permits touching).

---

## 6. Baidu (skip for v1)

Decision: **not registered**. Reasons:

- Target market is Japanese SMB taxpayers; Baidu share in JP is
  effectively zero.
- Baidu requires a 中国大陆 ICP license for full indexing eligibility,
  which we do not have and will not pursue (out of scope for solo
  zero-touch ops).
- Reconsider only if we add a JP→中国 cross-border 補助金 product line.

---

## 7. IndexNow protocol (the actual fast lane)

### 7.1 What IndexNow does

POST a single URL or batch of URLs to `api.indexnow.org/indexnow`. Bing,
Yandex, Naver, Seznam, and Yep crawl them within minutes (Bing officially
within 10 min P95). Google does NOT consume IndexNow as of 2026-04 but
the protocol is still net-positive: Bing + DDG + ChatGPT search all run
on Bing's index.

Without IndexNow, Bing's discovery crawler takes 1-3 weeks to re-fetch a
sitemap and find newly added URLs. With IndexNow, it is the same day.

### 7.2 Key file -- one-time upload

Generate (already done above):

```
INDEXNOW_KEY = xqb3GHUXXtVxaLjNldSqFyxGgMITszJ_akOrgDTsDG4
```

**OPERATOR ACTION**: create a file at `site/<INDEXNOW_KEY>.txt`
containing exactly the key string (one line, no trailing whitespace), and
deploy. The file must be reachable at:

```
https://jpcite.com/xqb3GHUXXtVxaLjNldSqFyxGgMITszJ_akOrgDTsDG4.txt
```

Bing + Yandex fetch this file on first IndexNow submission to prove you
own the domain. If the file is not present, every submission returns 403
and IndexNow silently does nothing.

> The site/ tree is read-only per the runbook constraint, but this is
> a one-line config file -- the operator creates it manually post-deploy
> using:
>
> ```bash
> echo -n "xqb3GHUXXtVxaLjNldSqFyxGgMITszJ_akOrgDTsDG4" > \
>   site/xqb3GHUXXtVxaLjNldSqFyxGgMITszJ_akOrgDTsDG4.txt
> ```

### 7.3 Cron submission

`scripts/cron/index_now_ping.py` runs after each sitemap regeneration
(post-deploy hook + nightly cron). It diffs the current sitemap against
the previous run's snapshot and POSTs any new/changed URLs to IndexNow
in batches of 10,000. Idempotent -- already-submitted URLs are recorded
in `analytics/indexnow_log.jsonl` and skipped.

GitHub Actions schedule: `.github/workflows/index-now-cron.yml`
(see §8 for workflow file).

---

## 8. robots.txt schema directive

Confirmed (2026-05-01): `site/robots.txt` lists the sitemap index plus each
public shard inline, including `sitemap-structured.xml`. The index remains the
canonical entry point; inline shard URLs are a fallback for crawlers that do
not follow sitemap indexes reliably.

---

## 9. Estimated indexing timeline

Assumes: domain age ~3 months, low backlink profile (organic-only, no
paid acquisition), 3,177 URLs submitted, IndexNow cron active.

| Time | Google indexed | Bing indexed | Notes |
|---|---:|---:|---|
| Day 0 (verify) | 0 | 0 | Sitemap submitted, both still in queue |
| Day 1-3 | 8-12 | 30-100 | Cornerstone pages indexed first |
| Week 1 | 150-400 | 500-1,200 | Bing IndexNow boost obvious |
| Week 2 | 600-1,500 | 1,800-2,800 | First long-tail queries hit |
| Week 4 | 1,800-2,800 | 2,800-3,100 | Most of corpus discoverable |
| Week 8 | 2,500-3,000 | 3,000-3,177 | Approaching theoretical max |
| Week 12 | 2,800-3,177 | 3,100-3,177 | Steady-state; thin pages may be excluded |

Theoretical max = 3,177 (sitemap submitted total, including structured JSON-LD). Google typically
indexes 80-90 % of submitted URLs for a low-authority site; the
remaining 10-20 % are flagged as "Crawled - currently not indexed"
(thin / duplicate / low-value classifier). Bing is more permissive and
indexes ~95-100 %.

> If week-4 Google count is under 1,500: investigate **Page indexing
> report** in Search Console for "Discovered - currently not indexed"
> volume. Most likely cause: thin programs without enough distinct content
> or crawl-budget throttling; the sitemap shards are expected to resolve.

---

## 10. P0 actions for the operator

These are the remaining operator steps for faster indexing.

### P0-1 -- Set GitHub Actions secrets

```
gh secret set INDEXNOW_KEY  --body 'xqb3GHUXXtVxaLjNldSqFyxGgMITszJ_akOrgDTsDG4'
gh secret set INDEXNOW_HOST --body 'jpcite.com'
```

(Or via GitHub UI if `gh` is not authenticated.)

### P0-2 -- Add 3 DNS TXT records on Cloudflare

After verifying each tool below, copy the verification string Cloudflare
DNS:

```
Type=TXT  Name=@  Value=google-site-verification=<...>  TTL=3600
Type=TXT  Name=@  Value=<BING-VERIFICATION-STRING>      TTL=3600
Type=TXT  Name=@  Value=yandex-verification: <...>      TTL=3600
```

Multiple TXT records on `@` are allowed -- each verification provider
looks up its own prefix.

### P0-3 -- Verify sitemap shard fetches after deploy

After Cloudflare Pages deploy, confirm every shard listed in
`site/sitemap-index.xml` returns HTTP 200 on `https://jpcite.com/`.

### P0-4 -- Upload IndexNow key file to site root

```bash
echo -n "xqb3GHUXXtVxaLjNldSqFyxGgMITszJ_akOrgDTsDG4" > \
  site/xqb3GHUXXtVxaLjNldSqFyxGgMITszJ_akOrgDTsDG4.txt
git add site/xqb3GHUXXtVxaLjNldSqFyxGgMITszJ_akOrgDTsDG4.txt
git commit -m "chore(seo): add IndexNow key file"
git push
# Cloudflare Pages auto-deploys.
```

Verify with:

```bash
curl -fsS https://jpcite.com/xqb3GHUXXtVxaLjNldSqFyxGgMITszJ_akOrgDTsDG4.txt
# expects exactly: xqb3GHUXXtVxaLjNldSqFyxGgMITszJ_akOrgDTsDG4
```

### P0-5 -- Submit sitemap-index.xml in Google + Bing + Yandex consoles

After domain verification (P0-2), in each tool's left nav → Sitemaps →
submit:

```
sitemap-index.xml
```

That is the entire submission. Each tool then crawls the index and pulls
all 8 referenced shards.

---

## 11. Verification -- end-to-end smoke

Run this after the 5 P0 actions complete:

```bash
# 1. DNS verification persisted
for prefix in google-site-verification yandex-verification; do
  dig +short TXT jpcite.com | grep "$prefix" || echo "MISSING: $prefix"
done

# 2. Sitemap index reachable + parseable
curl -fsS https://jpcite.com/sitemap-index.xml | head -5

# 3. IndexNow key file deployed
curl -fsS https://jpcite.com/xqb3GHUXXtVxaLjNldSqFyxGgMITszJ_akOrgDTsDG4.txt

# 4. Trigger IndexNow cron once manually
.venv/bin/python scripts/cron/index_now_ping.py --dry-run

# 5. Real submission (only after dry-run passes)
.venv/bin/python scripts/cron/index_now_ping.py
```

Then check `analytics/indexnow_log.jsonl` -- one row per submission batch.

---

## 12. Rollback / kill-switch

If IndexNow starts triggering bot-flag false positives at Cloudflare WAF
(very unlikely; Bingbot is whitelisted by default):

1. Delete the GitHub Actions schedule: comment out the `schedule:` block
   in `.github/workflows/index-now-cron.yml`.
2. Or revoke the key by deleting `site/<KEY>.txt` from the deploy.
   IndexNow then 403s on every submission silently.

If a webmaster tool surfaces a wave of indexing errors:

1. Search Console → **Settings → Crawl stats** → look for spikes.
2. Most common cause: aggressive sitemap regen (more than once per hour).
   The sitemap regeneration cron should run nightly, not hourly.

---

## 13. Privacy posture -- what we did NOT add

Per project constraint (no Google Analytics or other tracking that
violates privacy posture), we are using:

- **Cloudflare Web Analytics** (already deployed, server-side, no JS
  beacon, captured by `scripts/cron/cf_analytics_export.py`).
- **Search Console first-party data** (no JS injection required;
  Google's crawler already fetches the site).
- **Bing Webmaster first-party data** (same).

We are NOT adding:

- `gtag.js` / GA4 (would require user-tracking JS).
- Google Tag Manager.
- Bing UET tag (UET is for paid ads, which we do not run).
- Hotjar / FullStory / etc.

This keeps the privacy disclosures in `site/privacy.html` honest --
no third-party trackers, just self-hosted analytics + first-party SC/BWT
dashboards.
