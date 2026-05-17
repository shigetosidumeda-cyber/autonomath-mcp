# Codex Review: A5 + A6 + P4 + P5 PR

Date: 2026-05-17 JST
Reviewer: Codex Agent E
Scope: review only. No merge, no push, no live AWS.

## Branch / commit reviewed

- Branch: `worktree-agent-ac0ac5fdd0bcff29c`
- Local ref: present
- Remote ref: `origin/worktree-agent-ac0ac5fdd0bcff29c` present
- Reviewed HEAD: `fa3c80a47ffc9f7eac915e7da80c39e9a1f73ff8`
- Expected HEAD: `fa3c80a47`
- Current `origin/main`: `0f463d4991841680264e021dd6c66025e4a51b27`
- Merge base: `8076edaf9f9bb19ed789b0a5859e24c5f6cad5e0`
- PR URL: not found in the branch metadata or relevant docs during this review.

PR-style diff from merge base is one commit, 16 files, 3160 insertions:

- Adds A5 company-formation product pack.
- Adds A6 / F4 `pricing_v2`.
- Adds P4 freshness cron, MCP tool, migration 291, and hourly workflow.
- Adds P5 quality benchmark script.
- Adds `docs/pricing.html`, tests for A5 and `pricing_v2`, and manifest/registration edits.

`origin/main` has advanced substantially after the merge base. A double-dot comparison against current main shows many apparent deletions because this branch is behind current main, not because the PR itself deletes those files.

## Verification performed

- `git fetch origin main worktree-agent-ac0ac5fdd0bcff29c` succeeded.
- `git diff --check origin/main...origin/worktree-agent-ac0ac5fdd0bcff29c` passed.
- Syntax-only compile from Git objects passed for:
  - `src/jpintel_mcp/billing/pricing_v2.py`
  - `src/jpintel_mcp/mcp/products/product_a5_kaisha_setsuritsu.py`
  - `src/jpintel_mcp/mcp/autonomath_tools/answer_freshness_tool.py`
  - `scripts/cron/answer_freshness_check_2026_05_17.py`
  - `scripts/quality/benchmark_precomputed_answers_2026_05_17.py`
  - `tests/test_billing_pricing_v2.py`
  - `tests/test_product_a5_kaisha_setsuritsu.py`

I did not run pytest against the branch checkout. The branch is checked out in a separate locked worktree, and this review was constrained to write only this report file in `/Users/shigetoumeda/jpcite-codex-evening`. I therefore cannot honestly verify the claimed 49/49 runtime pass.

What I could verify from the Git tree:

- A5 + pricing v2 test count is 49 collected by source count:
  - `tests/test_product_a5_kaisha_setsuritsu.py`: 19 test functions
  - `tests/test_billing_pricing_v2.py`: 30 test functions
- The broader commit message claim does not exactly match current source counts:
  - `tests/test_p0_pricing_policy.py`: 3 test functions
  - `tests/test_product_a3_a4.py`: 17 test functions
  - Total across those four files is still 69, but the split is 19 + 30 + 3 + 17, not 19 + 30 + 4 + 16.

## Merge/conflict status

Not merge-safe as-is.

`git merge-tree origin/main origin/worktree-agent-ac0ac5fdd0bcff29c` exits non-zero with a content conflict:

- `scripts/distribution_manifest.yml`

Current `origin/main` already includes the branch's new `mcp-server.full.json`, `mcp-server.core.json`, and `mcp-server.composition.json` forbidden-token exclusions, plus later OpenAPI / justifiability exclusions added after this branch forked. Resolution should preserve the current `origin/main` section and only add anything genuinely missing from the branch. Taking the branch copy would drop newer manifest exclusions from main.

## Blocking findings

1. P4 freshness cron/tool does not match the current `am_precomputed_answer` schema.

   Branch code selects or writes columns that current main's P3 schema does not have:

   - Branch cron uses `intent_class`, `composed_from_json`, and `composed_answer_json` at `scripts/cron/answer_freshness_check_2026_05_17.py:229`, `:293`, `:344`, `:345`, `:367`.
   - Branch MCP tool selects `intent_class` at `src/jpintel_mcp/mcp/autonomath_tools/answer_freshness_tool.py:90` and returns it at `:141`.
   - Current main migration `wave24_207_am_precomputed_answer.sql` defines `composed_from`, `answer_text`, `answer_md`, `sections_jsonb`, `source_citations`, `corpus_snapshot_id`, and `version_seq`, but not `intent_class`, `composed_from_json`, or `composed_answer_json`.

   Expected result after merge: the hourly cron will fail with SQLite `OperationalError: no such column: intent_class` or `no such column: composed_from_json` once it runs against the real P3 table.

2. P4 introduces `expired`, but the existing table CHECK allows only `fresh`, `stale`, `unknown`.

   - Current main schema constraint is in `scripts/migrations/wave24_207_am_precomputed_answer.sql:85-87`.
   - Branch cron writes `freshness_state='expired'` at `scripts/cron/answer_freshness_check_2026_05_17.py:352`.
   - Branch migration 291 says `expired` is valid in comments, but because `freshness_state` already exists on the P3 table, `ALTER TABLE ... ADD COLUMN freshness_state` will be skipped/duplicate-column-handled, not change the CHECK constraint.

   Expected result after merge: any expired recomposition path will fail the table CHECK.

3. A5 / A6 pricing is stale relative to current `origin/main` Pricing V3.

   Branch A5 is priced as V2/F4:

   - `product_a5_kaisha_setsuritsu.py:61-63`: `_BILLING_UNITS = 267`
   - `product_a5_kaisha_setsuritsu.py:636-637`: 267 units, `JPY 801 ~= JPY 800`
   - `tests/test_product_a5_kaisha_setsuritsu.py:151-159`: tests lock 267 units / JPY 801
   - `docs/pricing.html:6`, `:83`, `:95`: V2 `JPY 100..JPY 1000` Tier D and A5 `JPY 800`

   Current `origin/main` has moved A1-A4 and the canonical billing model to Pricing V3:

   - `src/jpintel_mcp/billing/pricing_v3.py:28-34`: Tier D is 10 units / JPY 30, D band `JPY 30..JPY 120`, A5 expected `20..40 billable_units = JPY 60..JPY 120`
   - A1-A4 product modules in current main are already repriced to 10 units / JPY 30.

   Expected result after merge: A5 and `docs/pricing.html` will contradict the live Pricing V3 SOT and likely fail/rot the pricing narrative gates after the manifest conflict is resolved.

## Additional risks

- P5 benchmark file name and docstring say precomputed answers, but the script actually scores `am_actionable_answer_cache` at `scripts/quality/benchmark_precomputed_answers_2026_05_17.py:385`, not the P3 `am_precomputed_answer` table. If P5 is meant to benchmark the new 500 FAQ precomputed-answer cache, this is the wrong source table.
- The new hourly workflow connects to the live Fly app `autonomath-api` via `flyctl ssh console` at `.github/workflows/answer-freshness-hourly.yml:58-59`. This review did not run it. Merging would arm a live hourly production-adjacent cron immediately.
- Workflow `workflow_dispatch.inputs.since` is interpolated into the remote command via `FLAGS` at `.github/workflows/answer-freshness-hourly.yml:52`, `:57`, `:59`. Treat as operator-only input or quote/validate it before enabling manual dispatch.
- Branch adds `pricing_v2.py`, which current `pricing_v3.py` imports for `PricingTier`. That addition is useful, but the branch should be integrated as a compatibility enum/source only, not as the active A5 pricing SOT.

## Recommendation

Do not merge this branch as-is.

Minimum fixes before merge:

1. Resolve `scripts/distribution_manifest.yml` by preserving current `origin/main` additions.
2. Rebase or replay the branch onto current `origin/main`.
3. Rewrite P4 cron/tool to use the actual P3 columns:
   - `composed_from` instead of `composed_from_json`
   - no `intent_class` unless a migration adds it
   - update `answer_text` / `answer_md` / `sections_jsonb` or explicitly document that recomposition only flips freshness metadata
   - either avoid `expired` or rebuild the table constraint to allow it
4. Reconcile A5 with Pricing V3:
   - likely `pricing_version = "v3"`
   - A5 billable units within current V3 A5 range, not 267 units
   - update A5 tests and public pricing docs accordingly
5. Decide whether P5 is benchmarking `am_actionable_answer_cache` or `am_precomputed_answer`; rename or retarget the script.
6. Keep the workflow disabled or dry-run-only until P4 passes local DB fixture tests.

## Exact next commands for parent

Reproduce review state:

```bash
cd /Users/shigetoumeda/jpcite-codex-evening
git fetch origin main worktree-agent-ac0ac5fdd0bcff29c
git show --stat --oneline origin/main...origin/worktree-agent-ac0ac5fdd0bcff29c
git merge-tree origin/main origin/worktree-agent-ac0ac5fdd0bcff29c
```

Create an integration branch without committing the merge:

```bash
cd /Users/shigetoumeda/jpcite-codex-evening
git switch -c review/a5-a6-p4-p5-on-main origin/main
git merge --no-ff --no-commit origin/worktree-agent-ac0ac5fdd0bcff29c
```

If the merge is attempted, resolve the manifest conflict by keeping current main's `forbidden_token_exclude_paths` additions and adding only missing branch entries:

```bash
git status --short
git diff -- scripts/distribution_manifest.yml
```

After code fixes, run targeted local verification without live AWS:

```bash
PYTHONDONTWRITEBYTECODE=1 pytest -q -p no:cacheprovider \
  tests/test_billing_pricing_v2.py \
  tests/test_billing_pricing_v3.py \
  tests/test_product_a5_kaisha_setsuritsu.py \
  tests/test_product_a3_a4.py

PYTHONDONTWRITEBYTECODE=1 pytest -q -p no:cacheprovider \
  tests/test_no_llm_in_production.py

ruff check \
  src/jpintel_mcp/billing/pricing_v2.py \
  src/jpintel_mcp/mcp/products/product_a5_kaisha_setsuritsu.py \
  src/jpintel_mcp/mcp/autonomath_tools/answer_freshness_tool.py \
  scripts/cron/answer_freshness_check_2026_05_17.py \
  scripts/quality/benchmark_precomputed_answers_2026_05_17.py
```

Abort if choosing not to continue:

```bash
git merge --abort
git switch codex-evening-2026-05-17
```
