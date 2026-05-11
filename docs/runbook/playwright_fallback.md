# Playwright fallback wire — runbook

Wave 36 horizontal data-collection hardening. Every ETL / cron ingest
script under `scripts/etl/` and `scripts/cron/` now layers a Playwright
fallback on top of its static `httpx.get()` / `urllib.urlopen()`
fetch. When a static request returns 4xx / 5xx / times out / returns
an empty body, the helper renders the page via headless chromium and
extracts the structural DOM through Playwright's accessibility tree.

This runbook covers: when the fallback fires, how to debug it from
the operator session, and the known-good knobs.

## Strategy

```
caller
  └─ fetch_with_fallback(url, static_fetcher=...)
       ├─ static path (3 retries × exp backoff 1.5s, 3s, 6s)
       │    └─ caller's httpx.AsyncClient or urllib
       └─ Playwright path (only on static exhaustion)
            ├─ chromium headless, viewport 1280 × 1600
            ├─ accessibility tree → innerText → textContent
            ├─ screenshot → /tmp/etl_screenshots/{etl}_{ts}.png
            └─ sips/Pillow resize ≤ 1600 px
```

Static-first means rate-limit budgets stay attributed to the caller's
existing user-agent + per-host throttle. Playwright only fires on
hard failure so the budget multiplier stays bounded.

## When the fallback triggers

* JS-heavy 1次資料 pages that respond 200 but render the substantive
  body client-side (J-PlatPat gazette index, 裁判所 hanrei_jp search).
* Government CGI endpoints with intermittent 504 (国税庁 通達, 衆議院
  議案, 厚労省 press feeds during batch windows).
* RSS feed maintenance windows where the static `Content-Type` flips
  from `application/rss+xml` to `text/html` for a 503 page.
* Bot-fence walls (`elaws.e-gov.go.jp` rare 503, `mirasapo` rate-limit).

## Wired ETL surface (11 scripts)

| Script | Axis | Static lib | Fallback trigger |
| --- | --- | --- | --- |
| `scripts/etl/ingest_jpo_patents.py` | 1b | httpx async | J-PlatPat gazette index empty body |
| `scripts/cron/ingest_edinet_daily.py` | 1c | httpx async | EDINET documents.json 5xx |
| `scripts/etl/ingest_court_decisions_extended.py` | 1d | urllib | 裁判所 SPA empty body |
| `scripts/etl/ingest_industry_guidelines.py` | 1e | urllib | 省庁 PDF list 504 |
| `scripts/etl/ingest_nta_tsutatsu_extended.py` | 1f | urllib | NTA tsutatsu CGI 504 |
| `scripts/cron/poll_adoption_rss_daily.py` | 3a | httpx sync | mirasapo / j-grants 5xx |
| `scripts/cron/poll_egov_amendment_daily.py` | 3b | httpx sync | elaws RSS 503 |
| `scripts/cron/poll_enforcement_daily.py` | 3c | httpx sync | ministry press 5xx |
| `scripts/cron/detect_budget_to_subsidy_chain.py` | 3d | httpx sync | 衆/参 議案ページ 504 |
| `scripts/cron/diff_invoice_registrants_daily.py` | 3e | httpx sync | NTA invoice API rare 5xx |
| `scripts/cron/ingest_municipality_subsidy_weekly.py` | DEEP-44 | httpx async | 自治体 site 5xx |

## Operator debug from Claude Code

The Playwright fallback writes a screenshot to
`/tmp/etl_screenshots/{etl_name}_{timestamp}.png` (≤ 1600 px wide so
`Read` does not crash the CLI — memory `feedback_image_resize`).

```bash
# List recent captures
python tools/offline/visual_audit.py list

# Verify every PNG is CLI-safe (auto-resize oversize)
python tools/offline/visual_audit.py audit --fix

# Drive a one-shot capture for debug
python tools/offline/visual_audit.py capture https://www.j-platpat.inpit.go.jp/

# Prune captures older than 7 days
python tools/offline/visual_audit.py prune --days 7
```

Then `Read /tmp/etl_screenshots/<file>.png` from Claude Code to view
the rendered page.

## GHA workflow wires

Each of the 9 cron / weekly workflows now inlines:

1. `actions/cache@v4` keyed on `pyproject.toml` → `~/.cache/ms-playwright`.
2. Cache miss → `python -m playwright install --with-deps chromium`.
3. Cache hit → `python -m playwright install-deps chromium` (OS libs only).
4. `pip install -e ".[dev,e2e]"` (the `e2e` extra pulls Playwright).

Wired workflows:

* `jpo-patents-daily.yml`
* `edinet-daily.yml`
* `extended-corpus-weekly.yml` (Fly-side probe, see below)
* `adoption-rss-daily.yml`
* `egov-amendment-daily.yml`
* `enforcement-press-daily.yml`
* `budget-subsidy-chain-daily.yml`
* `invoice-diff-daily.yml`
* `municipality-subsidy-weekly.yml`

The reusable workflow `.github/workflows/playwright-install.yml` holds
the canonical recipe and runs as a smoke test on PRs that touch the
helper.

### Fly-side ETLs (`extended-corpus-weekly.yml`)

This workflow runs ETL inside `flyctl ssh console -C` on the Fly
production machine. Playwright must be present in `/opt/venv` on the
Fly image. The workflow now runs a `Probe Playwright availability on
Fly` step that surfaces a clear `::warning::` if chromium is missing;
the ETL then falls back to static-only and skips 4xx/5xx rows. To
permanently fix, add the Playwright install to the Dockerfile (out of
scope for this runbook).

## Troubleshooting

### Screenshot is > 1600 px and `Read` crashes

* Run `python tools/offline/visual_audit.py audit --fix`. The helper
  invokes `sips` (macOS) or Pillow (Linux/CI) to resize in-place.
* If neither is installed, install Pillow: `pip install Pillow`.

### Playwright launches but never finishes

* Check `JPCITE_PLAYWRIGHT_TIMEOUT_SEC` (default 60s).
* On crowded GHA runners, raise to 120 for the offending workflow.
* `--disable-gpu --no-sandbox --disable-dev-shm-usage` are baked into
  the launch args; do not strip them.

### Aggregator URL accidentally reached the helper

* The helper refuses `noukaweb`, `hojyokin-portal`, `biz.stayway`,
  `hojo-navi`, `mirai-joho`, `hojyokin-info`, `hojokin-portal`,
  `subsidy-port.jp` with `AggregatorRefusedError`.
* CLAUDE.md "Data hygiene" — never widen the deny-list to allow an
  aggregator citation; if a primary source is needed, walk the
  upstream `.go.jp` / `.lg.jp` page through Playwright directly.

### Static path keeps succeeding but body is wrong

* The fallback chains on **empty body** as well as exceptions. If the
  static body is wrong but non-empty, callers must add their own
  semantic validation (regex non-match → raise → fallback fires).

### LLM API import slipped in

* Forbidden. `tests/test_no_llm_in_production.py` enforces this.
* The Playwright helper uses Playwright's accessibility tree + DOM
  `innerText` — zero LLM inference. Operator-side debug via `Read`
  drives the Vision LLM separately (memory
  `feedback_no_operator_llm_api` covers that boundary).
