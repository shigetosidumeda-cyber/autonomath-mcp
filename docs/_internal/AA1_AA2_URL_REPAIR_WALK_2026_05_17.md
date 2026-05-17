# AA1 + AA2 URL Repair Walk — 2026-05-17

Lane: `[lane:solo]`. Operator: Bookyou株式会社 (T8010001213708, info@bookyou.net).

## Mission

Both AA1 (税理士 / NTA / KFS / 47 pref) and AA2 (会計士 / ASBJ / JICPA / FSA /
EDINET) source URLs had drifted stale. AA2 follow-up Textract live OCR
returned 0 PDFs across all 5 sources, costing $0 burn but stalling the moat
depth enable. AA1 endpoints showed the same pattern in independent probing.

This document records the URL re-probe walk and the manifest + crawler
refresh that makes bounded canary validation possible. Full wet-run
re-dispatch remains blocked until the canaries produce non-zero rows/PDFs.

## Stale → current path table

### AA1 (税理士 / NTA / KFS / 47 都道府県)

| Gap | Source | Old endpoint | New endpoint (probed 2026-05-17 08:45 UTC) | HTTP |
|-----|--------|--------------|--------------------------------------------|------|
| G1  | NTA 質疑応答 法人税 | `https://www.nta.go.jp/law/shitsugi/hojin/` | `https://www.nta.go.jp/law/shitsugi/hojin/01.htm` | 200 |
| G2  | NTA 質疑応答 消費税 | `https://www.nta.go.jp/law/shitsugi/shohi/` | `https://www.nta.go.jp/law/shitsugi/shohi/01.htm` | 200 |
| G3  | NTA 質疑応答 相続税 | `https://www.nta.go.jp/law/shitsugi/sozoku/` | `https://www.nta.go.jp/law/shitsugi/sozoku/01.htm` | 200 |
| G4  | NTA 質疑応答 評価 | `https://www.nta.go.jp/law/shitsugi/hyoka/` | `https://www.nta.go.jp/law/shitsugi/hyoka/01.htm` | 200 |
| G5  | NTA 質疑応答 印紙/法定/譲渡 | `https://www.nta.go.jp/law/shitsugi/{inshi,hotei,joto}/` | `https://www.nta.go.jp/law/shitsugi/{inshi\|hotei\|joto}/01.htm` (3 paths, all 200) | 200 |
| G6  | NTA 裁決 vol | `https://www.kfs.go.jp/service/JP/idx/{vol_no}.html` (vol 1-120) | `https://www.kfs.go.jp/service/JP/idx/{vol_no}.html` (vol 43-140) | 200 |
| G7  | NTA 裁決 incremental | `https://www.kfs.go.jp/service/JP/idx/` (403) | `https://www.kfs.go.jp/service/JP/index.html` (parse hyperlinks) | 200 |
| G8  | am_tax_amendment_history | `https://www.nta.go.jp/law/joho-zeikaishaku/` (302 → 404) | `https://www.nta.go.jp/law/joho-zeikaishaku/sonota/sonota.htm` + 12 sub-indices | 200 |
| G9  | nta_bunsho_kaitou backfill | `https://www.nta.go.jp/law/bunshokaito/` (302 → 404) | `https://www.nta.go.jp/law/bunshokaito/01.htm` + 10 per-category numbered paths | 200 |
| G10 | 地方税 47 都道府県 | `https://www.pref.{kenmei}.lg.jp/zeimu/` (44/47 fail allowlist) | `https://www.pref.{kenmei}.lg.jp/` + 3 overrides (tokyo=tax.metro, aichi=.jp, kanagawa=.jp) | 200 |

**Cause**: NTA migrated their entire `/law/shitsugi/{category}/` directory pattern from
2018-era trailing-slash index pages to a numbered `01.htm` (and per-bunsho
sub-category numbered) scheme. The old paths now 302-redirect to
`/error/404.htm`. KFS retired the lowest saiketsu volumes 1-42 (likely off
public site); current online range is 43..140. Joho-zeikaishaku migrated to
per-tax sub-index files (houzin.htm, syouhi.htm, …).

**Crawler bug**: the host allowlist regex required `pref\.[a-z-]+\.jp` which
fails to match the canonical `pref\.{romaji}\.lg\.jp` form (two dots before
`.jp`). Plus the prefecture URL pattern used `/zeimu/` which 404s on most
prefectures. Both fixed in this commit.

### AA2 (会計士 / ASBJ / JICPA / FSA / EDINET)

| Source | Old endpoint | New endpoint (probed 2026-05-17 08:45 UTC) | HTTP |
|--------|--------------|--------------------------------------------|------|
| ASBJ 企業会計基準 | `https://www.asb.or.jp/jp/accounting_standards/accounting_standards.html` | Same path but **TCP timeout** (119.243.75.27 unreachable from this lane) | TLS_CONNECTION_TIMEOUT |
| JICPA 監査基準委員会報告書 | `https://jicpa.or.jp/specialized_field/post-2.html` (404) | `https://jicpa.or.jp/specialized_field/publication/kansa/` + 4 companion paths | 200 |
| FSA 企業会計審議会 | `https://www.fsa.go.jp/singi/singi_kigyou/` (403) | `https://www.fsa.go.jp/singi/singi_kigyou/top.html` + top_tousin.html + top_gijiroku.html | 200 |
| EDINET 内部統制報告書 | `https://disclosure2dl.edinet-fsa.go.jp/searchdocument` (404) | `https://disclosure2.edinet-fsa.go.jp/weee0010.aspx` (search form) | 200 |
| EDINET API v2 | n/a (was implicit) | `https://api.edinet-fsa.go.jp/api/v2/documents.json` (requires Subscription-Key now) | 302 then 403 |
| JICPA 監査ツール | `https://jicpa.or.jp/specialized_field/files/` (404) | `https://jicpa.or.jp/specialized_field/download/audit/` + 6 sub-paths | 200 |

**Cause**: JICPA restructured `/specialized_field/` from a flat `post-N.html`
naming scheme to a content-typed taxonomy (`/publication/kansa/`, `/download/audit/`).
FSA `/singi/singi_kigyou/` directory listing disabled (403); current top
pages are `/top.html`, `/top_tousin.html`, `/top_gijiroku.html`. EDINET
migrated API from v1 to v2 and added Subscription-Key gate. ASBJ host
appears geo-blocked or down — both curl and Playwright TCP-timeout.

## Repair method

Per memory `feedback_fetch_fallback_chain_strict`, the probe walk used the
4-stage fallback chain:

1. **HTTP HEAD** (`curl -sI --max-time 15`) — preferred. 1 req / 3 sec / host.
2. **HTTP GET → HTML link extract** for endpoints that 302 but the redirect
   target itself was crawlable.
3. **Playwright headless** for hosts that refuse HTTP HEAD but accept browser
   navigation (used for ASBJ — still timed out, so flagged probe_failed).
4. **Operator-confirmed first-party fallback** — held in reserve; not needed
   for any AA1 source. ASBJ is deferred until it is reachable from the operator
   network or first-party PDFs are staged manually. No LLM API is used in this
   lane.

All probes respected `robots.txt` (NTA + KFS + FSA + JICPA + EDINET all
allow `/` for `*` UA). Total probe budget: ~80 HEAD/GET + 4 Playwright =
under 5 minutes wall-clock with the 3 sec / host rate limit.

## Manifest refresh

* `data/etl_g1_nta_manifest_2026_05_17.json` — gap_top_10.{1..10} now carry
  `endpoint` (new path), `previous_url` (stale path), `probed_at` (ISO),
  `http_status` (200) fields. G5 adds `probed_paths` for the 3-way inshi /
  hotei / joto fan-out. G6 adds `vol_range_note` explaining the 43..140
  truncation. G7 adds `probe_note` explaining the 403 directory-listing
  fallback. G8 adds `sub_indices` (12 paths). G9 adds `sub_categories`
  (10 paths). G10 adds `pref_url_overrides` (3 entries).

* `data/etl_g2_manifest_2026_05_17.json` — sources[] now carry
  `previous_url`, `probed_at`, `http_status`, and where applicable a
  `companion_index_urls` list. ASBJ entry adds `probe_status =
  TLS_CONNECTION_TIMEOUT` so the kaikeishi crawler emits `probe_failed`
  rather than crashing.

## Crawler fixes (lane:solo)

* `scripts/etl/crawl_nta_corpus_2026_05_17.py`
  * `PRIMARY_HOST_REGEX` extended to match `pref.{romaji}.lg.jp` (two-dot
    canonical form previously missing) + `tax.metro.tokyo.lg.jp` +
    `fsa.go.jp`.
  * `_crawl_chihouzei_pref` now reads from `pref_url_overrides` table for
    tokyo / aichi / kanagawa and uses the root host `https://www.pref.{romaji}.lg.jp/`
    instead of the (mostly 404) `/zeimu/` sub-path.

* `scripts/etl/crawl_kaikeishi_corpus_2026_05_17.py` (new)
  * Mirrors the AA1 NTA crawler design: source enumeration from manifest,
    primary-host allowlist, robots.txt parser, dry-run-by-default,
    `--max-pdfs` cap. Emits `probe_failed=true` when manifest source carries
    `probe_status != ok/blank`. NO LLM. mypy --strict clean. ruff clean.

## Test crawl results

Both crawl scripts ran with `--dry-run` and `--max-pdfs 10` on 2026-05-17 at
08:45-08:47 UTC.

### NTA crawl (all 10 gaps)

| gap_id                       | aggregator_rejected | http_errors |
|------------------------------|---------------------|-------------|
| shitsugi (×5: g1..g5)        |                   0 |           0 |
| saiketsu (×2: g6, g7)        |                   0 |           0 |
| g8_tax_amendment_history     |                   0 |           0 |
| bunsho (g9)                  |                   0 |           0 |
| g10_chihouzei_47pref         |                   0 |           0 |

Before the regex fix g10 reported `aggregator_rejected = 46` (all 47 minus
Tokyo). After the URL-REPAIR commit the allowlist passes all 47 prefectures
including the `aichi.jp`, `kanagawa.jp`, and `osaka.lg.jp` variants.

### Kaikeishi crawl (all 5 sources)

| source_id                              | staged_pdfs | aggregator_rejected | probe_failed |
|----------------------------------------|-------------|---------------------|--------------|
| asbj_kigyou_kaikei_kijun               |           0 |                   0 |         True |
| jicpa_kansa_iinkai_houkokusho          |          10 |                   0 |        False |
| kigyou_kaikei_shingikai_kansa_kijun    |          10 |                   0 |        False |
| edinet_naibu_tousei_houkokusho         |          10 |                   0 |        False |
| jicpa_kansa_tool_oukou                 |          10 |                   0 |        False |

4 of 5 sources report dry-run planning intent > 0. ASBJ flagged probe_failed
correctly; its wet-run is deferred until the host is reachable from a different
egress IP or first-party PDFs are staged manually.

## Live OCR re-enable condition

Before re-dispatching either AA1 follow-up or AA2 follow-up Textract live
OCR, the operator should confirm:

1. **AA1**: pick any 3 of `g1_shitsugi_hojin / g6_saiketsu_vol_43_to_140 /
   g10_chihouzei_47pref` and run `--commit` with `--max-minutes 5
   --max-pdfs 5`. Expect non-zero `fetched_pages` and `inserted_rows`.
2. **AA2**: pick any 3 of `jicpa_kansa_iinkai_houkokusho /
   kigyou_kaikei_shingikai_kansa_kijun / edinet_naibu_tousei_houkokusho` and
   confirm 5 PDFs land in `s3://jpcite-credit-993693061769-202605-derived/kaikeishi_pdf_raw/`.
3. **ASBJ-specific**: defer until the host comes back online or operator
   stages first-party PDFs manually.

Hard-stop budget remains $19,490 with EE1 burn monitor armed. The URL
repair itself is $0 burn (pure HTTP HEAD + local manifest rewrite).

## Re-dispatch trigger

This lane (URL-REPAIR) is the *enabling* lane. Re-dispatch of the AA1
follow-up + AA2 follow-up cohort-gap fillers is an **operator decision**
out of scope for this lane. Conditions to re-dispatch:

* Both manifests now carry `url_refresh_utc = 2026-05-17T08:45:00Z`.
* Both crawl scripts dry-run-PASS at the levels documented above.
* Co-Authored-By trailer present in the commit; safe_commit.sh wrapped.

The current crawl orchestrators are planning/runbook emitters. Do not use them
as proof of live PDF landing. For first canaries, prefer direct bounded
source-specific runs such as:

```
.venv/bin/python scripts/etl/ingest_nta_kfs_saiketsu.py \
    --vol-from 43 --vol-to 43 --max-minutes 5 --smoke

.venv/bin/python scripts/etl/ingest_nta_qa_to_db_2026_05_17.py \
    --category hojin --commit --crawl-run-id aa1_url_repair_canary_20260517
```

For AA2, do not start Textract/OCR until a first-party PDF staging script
exists or is located and a max-5 PDF canary lands non-zero S3 keys.
