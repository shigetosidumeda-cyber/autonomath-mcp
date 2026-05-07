# R8 — `am_law_article.body_en` partial ETL kickstart (2026-05-07)

## Scope & verdict

R8_I18N_DEEP_AUDIT (Wave 24) flagged a single-row `body_en` population
across the 353,278 `am_law_article` corpus (1 / 353,278 = 0.0003%). The
foreign-FDI cohort (mig 092 `foreign_capital_eligibility` flag,
mig 091 `am_tax_treaty`, mig 090 `body_en` columns) is wired but the
EN corpus surface is empty in practice. This audit closes that gap by
**(a)** verifying the existing JLT ETL is complete, healthy, and
disciplined; **(b)** designing + landing a weekly cron to lift coverage
on the Fly production volume; **(c)** documenting the honest pace +
saturation timeline.

**No production DB writes were performed in this session.** The cron
runs on Fly post-merge.

## What we found

### 1. The ETL exists and is honestly built

The script the brief referred to as `scripts/etl/batch_translate_corpus.py`
is, in reality, **`scripts/etl/ingest_egov_law_translation.py`**. The
"batch_translate_corpus.py" name appears in CLAUDE.md and the Wave 21-22
changelog as a stale reference; the live, wired script is the one above.
Honest re-label is recorded here so future audits don't chase the
phantom name.

The live script (873 lines) implements:

- **Pure stdlib parser.** `urllib` + `html.parser` + regex + `sqlite3`.
  Zero LLM imports (verified by reading every `import` line). Complies
  with the CLAUDE.md "no LLM under `scripts/etl/`" rule and
  `tests/test_no_llm_in_production.py` CI guard.
- **Primary source only.** Fetches `https://www.japaneselawtranslation.go.jp/ja/laws/view/<view_id>`
  detail pages directly, follows 302 redirects to canonical view_ids,
  records the resolved URL into `body_en_source_url`. CC-BY 4.0
  attribution preserved via the migration-090 default
  `body_en_license = 'cc_by_4.0'`.
- **Polite walk.** 3.0s per-request sleep, 30s timeout, 2 retries on
  5xx, `User-Agent: jpcite-research/1.0 (+https://jpcite.com/about)`.
  Well within JLT's published rate budget.
- **Resumable.** `tools/offline/_inbox/egov_law_translation/_progress.json`
  records `next_view_id` + `completed_view_ids` + per-view stats. Re-runs
  pick up where the last run stopped — solo + zero-touch friendly.
- **Match key.** `(law_canonical_id, article_number)`. Articles whose
  parent JP row does not exist in `am_law_article` are **skipped** (we
  do not synthesize new rows from translation alone — the JP-side
  `text_full` from `ingest_law_articles_egov.py` is the legally
  authoritative parent).
- **Article number canonicalisation.** Defensive 漢数字 → arabic mapping
  for `第十三条の二` → `13_2`, with anchor-id fallback (`je_chXatY` →
  `Y`). Matches the `am_law_article.article_number` shape regardless of
  JLT renderer choice.
- **Auto-resolve.** `--auto-resolve` resolves `am_law.canonical_id` by
  exact `canonical_name` match on the JLT page title. No fuzzy match —
  honest miss returns `no_canonical` and skips, never guesses.

### 2. Source of EN translations

JLT (日本法令外国語訳DBシステム, https://www.japaneselawtranslation.go.jp)
publishes **hand-translated** bilingual law detail pages under CC-BY 4.0.
We do **not** generate translations ourselves (the LLM-zero rule + the
CC-BY attribution requirement both forbid it). Each detail page renders
alternating JP / EN ParagraphSentence + ItemSentence blocks; the parser
extracts both sides in document order and writes only the EN side to
`body_en` (the JP side is already canonical via e-Gov).

Coverage on the JLT side is heavy on the FDI-relevant corpus: 商法 /
会社法 / 金融商品取引法 / 外為法 / 法人税法 / 消費税法 / 関税法 /
独占禁止法 / 個人情報保護法 / etc. The catalog runs roughly view_id 1
to ~5,500 (verified 2026-05-05 per script docstring). Even the first few
hundred views cover the major commerce / corporate / FX / tax / antitrust
laws — exactly the foreign-FDI cohort target.

### 3. Existing run state

`tools/offline/_inbox/egov_law_translation/` exists. The progress journal
on the Fly volume is the SoT (`/data/egov_law_translation/_progress.json`);
the repo-side copy is a mirror committed by the cron PR.

### 4. Why coverage is currently 1 / 353,278

The script was wired and validated via smoke (the smoke test in the
docstring writes `view_id=4241` → `law:koju-ho`, individual personal
information protection act rows) but never run on a recurring cadence.
There is no cron / GitHub Actions workflow that invokes it. That is
the gap this R8 audit closes.

## What we landed

### A. New cron workflow

**`.github/workflows/incremental-law-en-translation-cron.yml`** (new file).

- **Schedule.** `cron: "10 20 * * 0"` = 20:10 UTC Sunday = 05:10 JST
  Monday. Staggered +20 min after `incremental-law-load.yml` (19:50 UTC)
  so JP `text_full` loads first, then EN `body_en` backfills against
  the freshly-loaded `am_law_article` rows. Same Sunday-idle pattern as
  the JP loader.
- **Slice.** Default `--resume --max-view-id (next_view_id + 50)` per
  run. 50 views × ~4.5 s/view ≈ 4 min wall-clock; workflow timeout 60
  min for safer headroom (matches the JP loader's safety multiplier).
- **DB write target.** Fly production volume `autonomath.db` via
  `flyctl ssh console`, identical to the JP loader pattern. No GHA
  runner DB write (the 9.7 GB `autonomath.db` does not fit on the
  ubuntu-latest runner; CLAUDE.md gotcha confirmed).
- **PR-based audit trail.** After each run, the cron pulls
  `/data/egov_law_translation/_progress.json` off the Fly volume,
  diffs against the in-repo copy, and opens a PR with labels
  `ingest`, `law`, `i18n`, `automation`. The PR body cites the
  CC-BY 4.0 attribution string verbatim.
- **Failure surface.** `gh issue create` on driver failure +
  optional Slack webhook on the same channel as the JP loader.
- **flyctl gotcha compliance.** The progress-pull step `rm -f`s the
  in-repo copy before `sftp get` (CLAUDE.md "flyctl ssh sftp get
  refuses to overwrite" gotcha). `flyctl ssh console` quoted
  with explicit `/opt/venv/bin/python` path matches the JP loader.

### B. Saturation timeline (honest)

- **50 views/week** baseline → ~110 weeks (~25 months) for the full
  ~5,500 catalog. **Most-valuable rows land in the first ~10 weeks**
  because JLT's view_id ordering is roughly chronological by
  enactment/translation date and the early IDs cover the major
  commerce / corporate / FX / tax / antitrust laws (FDI cohort
  target). After ~10 weeks (≈ 500 views) the FDI cohort surface
  reaches "honestly useful" (~hundreds of populated rows across
  20-50 major laws); after ~20 weeks (≈ 1000 views) we have the
  bulk of the FDI-relevant corpus.
- **Pace bumps will follow the JP loader playbook.** Once we observe
  3-4 stable runs without 5xx clusters or parse errors, raise to
  100 views/week (saturation ≈ 55 weeks), then 150-200 if JLT
  doesn't push back. This is the same pattern the JP loader used
  (100 → 300 → 600 over Wave 30+1 / B4).
- **The `1 / 353,278` ratio is the wrong denominator.** `am_law_article`
  carries 353,278 rows across **9,484 laws**, of which only ~50-200
  laws are translated by JLT (FDI-grade laws). A more honest target
  is "populated rows for the laws JLT actually publishes" — likely
  1,000-5,000 articles total across the JLT-covered corpus, not a
  fraction of 353,278. Marketing copy should follow this honest
  framing once we cross 100 / 1000 / 5000 milestones.

### C. Documentation (this file)

`tools/offline/_inbox/_housekeeping_audit_2026_05_06/R8_BODY_EN_ETL_KICKSTART_2026-05-07.md`
records the audit findings, the stale-name correction, the workflow
design, and the saturation timeline. Lives in the same housekeeping
audit folder as the rest of R3/R4/R5/R6/R7 docs.

## Constraint compliance

| Constraint | Status | Evidence |
|---|---|---|
| LLM 0 (no Anthropic / OpenAI / etc) | Pass | Script imports verified; CI guard `tests/test_no_llm_in_production.py` already covers `scripts/etl/`. |
| Production DB write 0 (this session) | Pass | No `--db` writes invoked by the audit author; cron will run on Fly post-merge. |
| Destructive overwrite forbidden | Pass | Workflow uses `INSERT OR REPLACE` only on rows whose parent JP exists; misses skip, do not synthesize. |
| Pre-commit hook | Pass | YAML + Markdown only, no Python touched, no manifest-count change. |
| Read-only audit + workflow design | Pass | Two new files: cron YAML + this doc. No edits to `ingest_egov_law_translation.py` or migration 090. |

## Verify path (manual run, post-merge)

```bash
# Manual smoke from the Fly machine (no DB write):
flyctl ssh console -a autonomath-api -C \
  "/opt/venv/bin/python /app/scripts/etl/ingest_egov_law_translation.py \
    --view-id 4241 --canonical-id law:koju-ho --dry-run"

# Manual incremental run via workflow_dispatch:
gh workflow run incremental-law-en-translation-cron.yml \
  -f max_view_id=60 -f dry_run=true

# Verify post-cron coverage on Fly:
flyctl ssh console -a autonomath-api -C \
  "sqlite3 /data/autonomath.db \
    'SELECT COUNT(*) FROM am_law_article WHERE body_en IS NOT NULL;'"
```

## Followups (deferred, non-blocking)

1. **Marketing copy update.** Once `body_en` populated rows cross 50,
   update CLAUDE.md "body_en populated row count" line and the foreign
   FDI cohort surface description.
2. **CLAUDE.md stale-name fix.** Replace the two CLAUDE.md references
   to `batch_translate_corpus.py` (Wave 21-22 changelog) with
   `ingest_egov_law_translation.py`. Pure docs edit; defer to next
   manifest-bump release to keep this audit additive-only.
3. **Pace bump cadence.** Add a 1-line note in `incremental-law-load.yml`
   docstring referencing the EN sister cron, so future audits find
   both workflows from a single grep.
4. **API/MCP body_en surface.** Verify `api/laws.py` returns body_en +
   the unofficial-translation disclaimer when the row carries a
   non-null body_en. Migration 090 docstring claims this, but the
   2026-05-07 R8 audit did not re-verify the route handler in this
   session. Add to the next API surface walk.

## Files touched this session

- `.github/workflows/incremental-law-en-translation-cron.yml` (NEW)
- `tools/offline/_inbox/_housekeeping_audit_2026_05_06/R8_BODY_EN_ETL_KICKSTART_2026-05-07.md` (NEW, this file)

No edits to existing scripts, migrations, manifests, or DB.
