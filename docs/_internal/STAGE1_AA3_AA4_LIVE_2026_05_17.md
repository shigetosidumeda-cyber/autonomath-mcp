# Stage 1 — AA3 FDI + AA4 時系列 ETL LIVE landing (2026-05-17)

> Owner: 梅田茂利 (info@bookyou.net)
> Status: **LIVE** — production data landed; monthly cron registered.
> Authority: scorecard live_aws_commands_allowed=True (2026-05-17T03:11:48Z).

This memo records the Stage 1 AA3 (G7 FDI) and AA4 (G8 時系列) ETL
deltas. Both lanes addressed catastrophic coverage gaps surfaced by
the G7/G8 audits. Sources are primary government feeds only (no
aggregators, no LLM API).

---

## AA3 — G7 FDI ETL (foreign-direct-investment surface)

### Delta

| Metric | Before | After | Delta |
|---|---|---|---|
| `am_law_article.body_en` filled rows | **1** | **13,542** | +13,541 |
| `am_law_article.body_en` coverage | 0.0003 % | 3.833 % | +3.832 pp |
| `am_tax_treaty` distinct countries | **33** | **54** | +21 |
| MOF treaty rows upserted (this run) | — | 47 | — |

### Sources

- 日本法令外国語訳 (JLT, `https://www.japaneselawtranslation.go.jp/ja/laws/view/{view_id}`)
  License: CC-BY 4.0. Pulled via `scripts/etl/ingest_egov_law_translation.py --walk`
  over `view_id` 1..800. `am_law` canonical_id auto-resolved from JLT title.
  Total articles written this run: **15,292** (some are revisions of existing
  rows; net `body_en` non-null rows now 13,542).
- 財務省租税条約一覧 (`https://www.mof.go.jp/tax_policy/summary/international/tax_convention/`)
  License: 政府標準利用規約 v2.0. Per-country PDF parsed via `pypdf` +
  Article 5/10/11/12 regex extractors. ISO-3166-1 alpha-2 country
  resolution via URL-filename English token match (new) + Japanese
  anchor-text match (legacy).

### Code changes (this session)

- `scripts/etl/ingest_mof_tax_treaty.py` — `discover_country_pdfs` upgraded
  to resolve countries by PDF-filename English keyword tokens. The MOF
  index page no longer carries country names in anchor text; resolution
  was failing 100 %. Post-fix discovery: 48 countries → 47 successful
  PDF parses (one was already present).
- `scripts/etl/_MofLinkParser` — now also tracks `<th>` row-heading text
  (defence-in-depth for future MOF layout changes).
- `pypdf` was added as a runtime dependency in the working venv. The
  `etl-fdi-incremental.yml` workflow installs it explicitly.

### Walk telemetry

- Total JLT walk wall-clock: **~30 minutes** (800 view IDs × ~1.5s avg).
- Sleep budget: 1.0 s per JLT request (well above robots-friendly cadence).
- MOF treaty walk wall-clock: **~60 seconds** (47 PDFs × ~1.3 s avg).
- LLM call count: **0** on both walks.

### Remaining gap (out of scope this landing)

- `body_en` coverage 3.833 % vs the operator's 15 % stretch target. To
  close further, raise `--max-view-id` in `etl-fdi-incremental.yml` to
  `6000` (already the workflow default for the manual dispatch path),
  and let the monthly cron walk the long tail under `--resume`.

---

## AA4 — G8 時系列 (regulatory time-machine) ETL

### Delta

| Metric | Before | After | Delta |
|---|---|---|---|
| `am_monthly_snapshot_log` distinct `as_of_date` | **2** | **60** | +58 |
| `am_monthly_snapshot_log` date range | 2026-04..05 only | **2021-06-01..2026-05-01** | +60 months |
| `am_monthly_snapshot_log` rows total | 144 | **240** | +96 |
| `am_amendment_diff` rows | 16,116 | 16,116 | 0 (no new candidates) |

### Source

- Internal `autonomath.db` spine — `am_amendment_snapshot`,
  `am_cross_source_agreement`, `am_law_jorei`, `am_program_history`.
  Snapshot pipeline: `scripts/etl/build_monthly_snapshot.py --as-of YYYY-MM-01`
  invoked once per month across 60 months.

### Backfill telemetry

- 60-month range built sequentially (one sqlite transaction per month).
- One transient `database is locked` race against a separate read-only
  query (PID 90127) on 2023-05-01; resolved by retry. Final state: 60/60
  months landed.
- `backfill_amendment_diff_from_snapshots.py --apply` evaluated 7,819
  candidate diffs from snapshot pairs; **0 new diffs** (existing 16,116
  diff rows already cover the snapshot pairs — backfill is idempotent on
  the current spine).
- LLM call count: **0**. Deterministic sha256 + sqlite3 only.

### Per-table snapshot completeness (post-landing)

```
am_amendment_snapshot     60 months   2021-06-01..2026-05-01
am_cross_source_agreement 60 months   2021-06-01..2026-05-01
am_law_jorei              60 months   2021-06-01..2026-05-01
am_program_history        60 months   2021-06-01..2026-05-01
```

5-year rolling retention enforced by `--gc` in the cron workflow.

---

## Cron schedule registration

### `.github/workflows/etl-fdi-incremental.yml`

- Cadence: monthly on day 5, 21:00 UTC (06:00 JST day 6).
- Jobs: JLT `--resume` (sleep 1.0 s) → MOF treaty refresh (--limit 80).
- Failure → opens a GitHub issue with labels `ingest-failure / automation / stage1-aa3`.

### `.github/workflows/etl-monthly-snapshot.yml`

- Cadence: monthly on day 1, 21:00 UTC (06:00 JST day 1).
- Jobs: `build_monthly_snapshot.py` (default `--as-of` = 1st of UTC month)
  → `--gc` (5-year rolling retention) → `backfill_amendment_diff_from_snapshots.py --apply --json`.
- Failure → opens a GitHub issue with labels `ingest-failure / automation / stage1-aa4`.

Both workflows guard against missing DB (Stage 1 CI runners) via
`JPCITE_PREFLIGHT_ALLOW_MISSING_DB=1` and force `--dry-run` when
`autonomath.db` is absent from the checkout.

---

## Quality gates

- `ruff check scripts/etl/ingest_mof_tax_treaty.py` → **clean**.
- `mypy --strict scripts/etl/ingest_mof_tax_treaty.py` → 3 errors,
  all **pre-existing** (verified via `git stash` baseline comparison);
  no net regression from this landing.
- No new files outside `scripts/etl/`, `.github/workflows/`, and
  `docs/_internal/` were touched.

## Constraints honoured

- No LLM API call: JLT walk = HTTP + HTML parser; MOF walk = HTTP +
  pypdf + regex; snapshot batch = sha256 + sqlite3.
- No aggregator: every `source_url` points to the original
  `japaneselawtranslation.go.jp` or `mof.go.jp` document.
- Per-source TOS honoured: JLT CC-BY 4.0; MOF 政府標準利用規約 v2.0.
- `[lane:solo]` — single agent, no parallel edit contention on
  `ingest_mof_tax_treaty.py`.
