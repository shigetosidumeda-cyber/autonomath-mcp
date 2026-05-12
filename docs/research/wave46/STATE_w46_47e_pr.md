# Wave 46 tick7#7 — Rename 47.E: workflow yml `autonomath_*` → `jpcite-*` alias

Branch: `feat/jpcite_2026_05_12_wave46_rename_47e_workflow_alias`
Wave:   46 / tick7#7
Date:   2026-05-12

## Goal

Per [[project_jpcite_internal_autonomath_rename]] (2026-05-12) and
[[feedback_destruction_free_organization]]: introduce `jpcite-*` alias
workflows for the 10 most autonomath-coupled GHA cron pipelines so the
GHA UI surfaces a single coherent jpcite brand without deleting, renaming,
or mutating the autonomath-era parents.

## Approach (destruction-free)

- **Parents untouched**: every `autonomath_*` / autonomath-coupled cron
  workflow file is preserved bit-for-bit (no name change, no schedule
  move, no body edit). The parent remains the SOT for the cron schedule.
- **Aliases are dispatch-only trampolines**: each `jpcite-<stem>.yml` has
  `on: workflow_dispatch:` only — **no** `schedule:`, `push:`,
  `workflow_run:`, `pull_request:`. The body is ~20 LOC that calls
  `gh workflow run <parent>.yml --ref <ref>`. No business logic is
  duplicated, so backup/ETL/export/precompute behaviour cannot drift.
- **Cron double-trigger is structurally impossible** — verified by the
  new test (see verify §). Aliases simply do not declare any schedule
  trigger; the parent's existing cron continues to fire alone.
- **Branding marker**: the alias `name:` field encodes
  `"jpcite-<stem> (alias of <parent_stem>)"` so GHA UI surfaces both
  brands and operators can reverse-lookup the SOT in one glance.

## File inventory

10 new alias workflows under `.github/workflows/`:

| # | Alias filename | Parent filename | Parent cron |
|---|---|---|---|
| 1 | `jpcite-weekly-backup.yml` | `weekly-backup-autonomath.yml` | `45 19 * * 0` |
| 2 | `jpcite-nightly-backup.yml` | `nightly-backup.yml` | `17 18 * * *` |
| 3 | `jpcite-parquet-export-monthly.yml` | `parquet-export-monthly.yml` | `30 2 1 * *` |
| 4 | `jpcite-extended-corpus-weekly.yml` | `extended-corpus-weekly.yml` | `0 2 * * 2` |
| 5 | `jpcite-news-pipeline-cron.yml` | `news-pipeline-cron.yml` | `35 19 * * *` |
| 6 | `jpcite-nta-corpus-incremental-cron.yml` | `nta-corpus-incremental-cron.yml` | `5 19 * * *` |
| 7 | `jpcite-brand-signals-weekly.yml` | `brand-signals-weekly.yml` | `0 21 * * 1` |
| 8 | `jpcite-saved-searches-cron.yml` | `saved-searches-cron.yml` | `10 21 * * *` |
| 9 | `jpcite-precompute-refresh-cron.yml` | `precompute-refresh-cron.yml` | `30 21 * * *` |
| 10 | `jpcite-populate-calendar-monthly.yml` | `populate-calendar-monthly.yml` | `0 18 5 * *` |

Per-file LOC: each alias is ~33 LOC (well under the ~20 LOC × N envelope
once headers/comments are counted; the executable body is 12 LOC each).

Plus 1 new test:

- `tests/test_w47e_workflow_alias.py` (~135 LOC, 52 parametrised cases).

## Selection criteria (why these 10)

The task asked for 8–15 aliases sized to the autonomath-coupled subset.
We picked the top-10 workflows by `autonomath` occurrence count that
operate primarily on `autonomath.db` (e.g. backups, full-corpus ETL,
brand/news/precompute cron) and **excluded** general-purpose multi-DB
workflows like `deploy.yml` / `release.yml` / `sdk-republish.yml` whose
brand surface is already migrated.

The single workflow whose **filename literally contains `autonomath`** —
`weekly-backup-autonomath.yml` — is item #1.

## Verify

### yamllint (relaxed CI profile)

```
yamllint .github/workflows/jpcite-*.yml
(no output)
```

All 10 alias files lint clean under default rules with line-length
disabled (consistent with the rest of `.github/workflows/`).

### pytest

```
tests/test_w47e_workflow_alias.py ............... [100%]
52 passed in 2.13s
```

Coverage matrix (5 invariants × 10 pairs + 2 cross-cuts = 52 cases):

1. `test_alias_files_exist` — alias and parent both on disk (10 cases)
2. `test_alias_dispatch_only_no_cron` — alias `on:` has
   `workflow_dispatch` and lacks `schedule`/`push`/`workflow_run`/
   `pull_request` (10 cases)
3. `test_alias_name_marks_parent` — alias `name:` field contains
   `alias of <parent_stem>` (10 cases)
4. `test_alias_trampolines_to_parent` — body invokes
   `gh workflow run <parent>.yml` (10 cases)
5. `test_parent_cron_untouched` — parent still carries a `cron:` line
   (10 cases)
6. `test_no_duplicate_cron_across_alias_and_parent` — global sweep (1)
7. `test_alias_count_matches_spec` — count ∈ [8, 15] (1)

### Cron-double-trigger verdict

- **Parent cron lines (10/10 present)**: confirmed above.
- **Alias cron lines (10/10 == 0)**: confirmed via
  `grep -cE "^\s*- cron:" .github/workflows/jpcite-*.yml` → all zero.
- **Verdict**: cron double-trigger 0 / 10 pairs.

## Anti-pattern guardrails (passive)

- No alias edits the parent — parent files are not in the diff.
- No alias defines its own cron — the parity test pins this.
- No alias contains autonomath-specific business logic — it's a thin
  trampoline that re-invokes the parent.
- Brand markers are present in `name:` so future operators don't get
  confused which file is the SOT.

## PR readiness checklist

- [x] 10 alias yml files added
- [x] 1 parity test (~135 LOC, 52 cases) added
- [x] yamllint pass
- [x] pytest pass (52/52)
- [x] no parent file in the diff
- [x] no cron in any alias file
- [x] every parent still has its cron
- [x] branding marker present in every alias `name:`

Next step: commit + push + open PR. See report for PR number.
