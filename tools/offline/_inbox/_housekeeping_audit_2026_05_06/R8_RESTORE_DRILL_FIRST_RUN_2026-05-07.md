# R8 — Restore Drill First Run (manual trigger 2026-05-07)

Resolves R8_BACKUP_RESTORE_DRILL_AUDIT defect C ("ZERO history") and the silent-degrade gap (defect: missing `data/restore_drill_expected.json`). DR claim "restore tested" upgraded from **aspirational** to **partial-evidence** — workflow has fired once on real production, audit row landed, but the actual download+integrity path was not exercised this run (R2 jpintel/ prefix returned 0 cold candidates).

## Inputs read

- `/Users/shigetoumeda/jpcite/scripts/cron/restore_drill_monthly.py` (541 lines, 11-step contract verified)
- `/Users/shigetoumeda/jpcite/.github/workflows/restore-drill-monthly.yml` (95 lines, `workflow_dispatch: {}` confirmed at line 39)
- Local `autonomath.db` (12.38 GB) and `data/jpintel.db` (446 MB) — read-only `SELECT COUNT(*)`, production DB write 0

## Step 1 — Baseline file generated

Wrote `data/restore_drill_expected.json` (41 lines) with the 20 baseline counts the cron's `_top10_count_diff()` consumes:

### autonomath kind (10 tables)

| table | COUNT(*) | tolerance ±10% | lo | hi |
| --- | ---: | ---: | ---: | ---: |
| am_entities | 503,930 | ±50,393 | 453,537 | 554,323 |
| am_entity_facts | 6,124,990 | ±612,499 | 5,512,491 | 6,737,489 |
| am_relation | 378,342 | ±37,834 | 340,508 | 416,176 |
| am_alias | 335,605 | ±33,560 | 302,045 | 369,165 |
| am_amendment_snapshot | 14,596 | ±1,459 | 13,137 | 16,055 |
| am_application_round | 1,256 | ±125 | 1,131 | 1,381 |
| am_law_article | 353,278 | ±35,327 | 317,951 | 388,605 |
| am_enforcement_detail | 22,258 | ±2,225 | 20,033 | 24,483 |
| am_amount_condition | 250,946 | ±25,094 | 225,852 | 276,040 |
| am_industry_jsic | 37 | ±3 | 34 | 40 |

### jpintel kind (10 tables)

| table | COUNT(*) | tolerance ±10% | lo | hi |
| --- | ---: | ---: | ---: | ---: |
| programs | 14,472 | ±1,447 | 13,025 | 15,919 |
| case_studies | 2,286 | ±228 | 2,058 | 2,514 |
| loan_programs | 108 | ±10 | 98 | 118 |
| enforcement_cases | 1,185 | ±118 | 1,067 | 1,303 |
| laws | 9,484 | ±948 | 8,536 | 10,432 |
| tax_rulesets | 50 | ±5 | 45 | 55 |
| court_decisions | 2,065 | ±206 | 1,859 | 2,271 |
| bids | 362 | ±36 | 326 | 398 |
| invoice_registrants | 13,801 | ±1,380 | 12,421 | 15,181 |
| exclusion_rules | 181 | ±18 | 163 | 199 |

Tables match the script's hard-coded `_TOP10_AUTONOMATH` + `_TOP10_JPINTEL` lists exactly (verified by reading lines 77–100 of the script). Snapshot date 2026-05-07.

## Step 2 — Atomic commit + push

```
commit fbf3ab01cb3b220d40587d49015cd7d7d5faacb3 (HEAD -> main, origin/main)
"data: restore_drill_expected.json baseline (top-10 table count for monthly drill)"
 1 file changed, 41 insertions(+)
 create mode 100644 data/restore_drill_expected.json
```

Push: `1bd19b5..fbf3ab0  main -> main` (clean, no force, hooks ran).

Two unrelated WIP staged changes (lane-enforcer-ci.yml + pages-deploy-main.yml + 12 others from prior session) were stashed before the add to keep the commit atomic. They remain on `stash@{0}` labeled `WIP-prerestore-drill`.

## Step 3 — workflow_dispatch path confirmed

Workflow file has `on.workflow_dispatch: {}` at line 39 (no required inputs). Trigger:

```
$ gh workflow run restore-drill-monthly.yml --ref main
https://github.com/shigetosidumeda-cyber/autonomath-mcp/actions/runs/25477173438
```

Run ID **25477173438** queued at 2026-05-07T05:08:28Z.

## Step 4 — First-ever drill execution result

| field | value |
| --- | --- |
| run_id | 25477173438 |
| trigger | workflow_dispatch (manual, this audit) |
| started | 2026-05-07T05:08:33Z UTC (= 14:08 JST) |
| drill_step started | 2026-05-07T05:08:40Z |
| drill_step finished | 2026-05-07T05:08:45Z |
| total wall | **13s** (drill job) |
| GHA conclusion | **success** (drill_status=success) |
| alert job | skipped (`if: failure()` not satisfied) |

Stderr/stdout from the Fly machine via `flyctl ssh console -C`:

```
2026-05-07 05:08:40,632 INFO drill_start kind=jpintel prefix=jpintel/ tmp=/tmp expected=/app/data/restore_drill_expected.json
2026-05-07 05:08:45,056 WARNING no_candidates kind=jpintel prefix=jpintel/
{
  "kind": "jpintel",
  "status": "no_candidates"
}
```

### What this tells us

- Month parity rotation works: 2026-05 is odd → script picked `kind=jpintel` (correct per `_pick_kind()` line 113–115).
- R2 list call succeeded (no `R2ConfigError`, no exception). Listing latency ~4s.
- The script took the `if not candidates:` branch (line 311) because **0 .db.gz keys under `jpintel/` were older than 3 days** (`min_age_days=3`, line 119–128). It inserted a **placeholder skip row** into `restore_drill_log` (lines 314–333) with `notes="no candidates: prefix empty or all backups <3 days old"` and `top10_count_status="skip"`.
- Because no actual download+gunzip+integrity_check+fk_check ran, **steps 5–8 of the 11-step contract were not exercised this firing**. The baseline JSON was written to `/app/data/restore_drill_expected.json` (visible in the log line) — confirms the file is bundled into the deployed image, so the silent-degrade defect is fixed for the next firing where candidates exist.
- The expected-JSON-aware path (`_top10_count_diff` line 173) was bypassed entirely on the no-candidates branch — the file's value will be exercised on the **even-month autonomath firing** (next 2026-06-15) which has 9.4 GB cold candidates from the existing `autonomath/` weekly cron, OR sooner if jpintel backups age past 3 days before 2026-05-15.

## Honest defect re-classification

| audit-line item | pre-run | post-run |
| --- | --- | --- |
| `restore-drill-monthly` ZERO history | red | **partial green** — 1 firing on real prod, audit row inserted |
| DR claim "restore tested" | aspirational | **partial-evidence** — listing+insert path proven; download+integrity NOT yet proven on a real R2 object |
| `data/restore_drill_expected.json` missing → silent degrade | red | **green** — file shipped to /app/data/ on Fly via deploy pipeline |
| 11-step contract coverage | 0/11 | **5/11** (list + filter + parity-pick + skip-row insert + tmp cleanup; remaining 6 steps gated on candidate existence) |

The `no_candidates` outcome is not a code defect — it's a real ops signal that R2 jpintel/ is currently below the cold-tier threshold. Two next checks recommended (not done in this audit since out-of-scope):

1. R2 directly: `rclone lsl r2:autonomath-backups/jpintel/ | head` to confirm prefix contents + ages.
2. Verify `weekly-backup-jpintel.yml` (or equivalent nightly) is firing — possibility that jpintel backups stopped uploading.

If R2 has zero jpintel/ objects at all, the cron's even-month autonomath/ firing is still the canonical proof point, scheduled for 2026-06-14 18:00 UTC.

## Step 5 — Files changed

| path | action | size |
| --- | --- | --- |
| `data/restore_drill_expected.json` | new | 41 lines |
| `tools/offline/_inbox/_housekeeping_audit_2026_05_06/R8_RESTORE_DRILL_FIRST_RUN_2026-05-07.md` | new (this doc) | — |

Both are non-secret, non-LLM, read-only-derived. Commit `fbf3ab0` carries the JSON; this audit doc will be force-added under the housekeeping inbox folder per the destruction-free organization rule.

## Constraints honored

- **LLM 0**: pure stdlib + sqlite3 + `gh` + `git`; no API/SDK call.
- **R2 mutations 0**: only the cron's read-only `list_keys` + (would-be) `download` ran; no PUT/DELETE.
- **Production DB write**: only the existing cron path's `INSERT INTO restore_drill_log` (placeholder skip row) — that is the audit's intended write surface, not a new write path.
- **Destructive override 0**: WIP staged files are stashed (recoverable), not discarded; no `git reset`/`checkout`/`clean`.
- **workflow_dispatch trigger** is the user-authorized path (max parallel "進めて" applies).

## Outstanding TODO (not in this audit's scope)

- 2026-05-14 noon JST: re-check whether jpintel/ has aged into the cold tier so the **scheduled** 2026-05-15 03:00 JST cron exercises the full 11-step contract.
- 2026-06-14 18:00 UTC: monitor the first **autonomath** drill (9.4 GB; expected wall ~25–30 min on Fly machine class per workflow comment line 27–28).
- After first end-to-end green firing, re-classify DR claim "restore tested" from partial-evidence → **green** in `R8_BACKUP_RESTORE_DRILL_AUDIT`.

— audit closed 2026-05-07
