# CL28 — PR #245 Option A Cherry-Pick Prep (2026-05-17)

> Operator action prep doc. **Cherry-pick is NOT executed by this lane.**
> Operator must paste the Section 3 commands explicitly to merge.
> Follow-up lane will execute only when the operator says "go".

## Status header

| field | value |
| --- | --- |
| PR | #245 (state OPEN, isDraft true, mergeable UNKNOWN) |
| Head branch | `origin/worktree-agent-ac0ac5fdd0bcff29c` |
| Head SHA | `fa3c80a47` |
| Merge-base | `8076edaf9` (harness-H6 part 3) |
| Worktree ahead | 1 commit (fa3c80a47, the A5+A6+P4+P5 packet) |
| Main ahead | 42 commits (Pricing V3, GG1/7/10, M1/3/7, FF1/2, AA1/3/4, CC4, DD1/2, EE1) |
| CL1 audit doc | `docs/_internal/CL1_A5_A6_PR_MERGE_2026_05_17.md` (commit c54d86322) |
| Recommended | **Option A** — cherry-pick A5 + P4 + P5 only; **SKIP A6** (pricing_v2 superseded by V3 on main) |

## Section 1 — File list (Option A scope)

### A5 — 会社設立一式 Pack (¥800)

| path | type | size | on main? |
| --- | --- | --- | --- |
| `src/jpintel_mcp/mcp/products/product_a5_kaisha_setsuritsu.py` | NEW | 778 L | MISSING |
| `tests/test_product_a5_kaisha_setsuritsu.py` | NEW | 19 tests | MISSING |
| `src/jpintel_mcp/mcp/products/__init__.py` | EDIT | +2 L | clean append after `product_a4_shuugyou_kisoku` |

### P4 — Answer freshness tracking

| path | type | size | on main? |
| --- | --- | --- | --- |
| `src/jpintel_mcp/mcp/autonomath_tools/answer_freshness_tool.py` | NEW | 146 L | MISSING |
| `scripts/cron/answer_freshness_check_2026_05_17.py` | NEW | 451 L | MISSING |
| `scripts/migrations/291_am_precomputed_answer_freshness.sql` | NEW | 84 L | MISSING |
| `scripts/migrations/291_am_precomputed_answer_freshness_rollback.sql` | NEW | 12 L | MISSING |
| `.github/workflows/answer-freshness-hourly.yml` | NEW | 79 L | MISSING |
| `src/jpintel_mcp/mcp/autonomath_tools/__init__.py` | EDIT | +1 L | clean insert between `annotation_tools` and `audit_workpaper_v2` |

### P5 — Quality benchmark

| path | type | size | on main? |
| --- | --- | --- | --- |
| `scripts/quality/__init__.py` | NEW | 5 L | MISSING (parent dir absent) |
| `scripts/quality/benchmark_precomputed_answers_2026_05_17.py` | NEW | 854 L | MISSING |

### Pricing-v2 surface boilerplate (cherry-pick TARGETS only if A6 is later approved)

| path | type | note |
| --- | --- | --- |
| `pyproject.toml` | EDIT | +5 L (N806 ignore for `tests/test_billing_pricing_v2.py`) — **SKIP if A6 skipped** |
| `docs/pricing.html` | NEW | 122 L (V2 public landing page) — **SKIP if A6 skipped** |
| `scripts/distribution_manifest.yml` | EDIT | +13 L (mcp-server.full/core/composition excludes) — **already absorbed on main, hunk drops to no-op** |
| `src/jpintel_mcp/billing/pricing_v2.py` | NEW | — **SKIP, V3 supersedes** |
| `tests/test_billing_pricing_v2.py` | NEW | 30 tests — **SKIP, supersedes** |

## Section 2 — Conflict prediction

**Strict Option A (A5 + P4 + P5 only): predicted 0 conflicts.**

| # | path | conflict risk | reason |
| --- | --- | --- | --- |
| 1 | `src/jpintel_mcp/mcp/products/__init__.py` | LOW | merge-base→fa3c80a47 adds A5 entry after A4; main has same A1-A4 list, append clean |
| 2 | `src/jpintel_mcp/mcp/autonomath_tools/__init__.py` | LOW | inserts `answer_freshness_tool` between `annotation_tools` (line 29 main) and `audit_workpaper_v2` (line 30 main); both anchors present, insert clean |
| 3 | all NEW files (A5 + P4 + P5 surface) | NONE | files missing on main, direct add |

**A6 stream (SKIPPED in Option A)** would add 2 medium-risk hunks:

- `pyproject.toml` line ~372 — clean append after `test_aggregate_run_ledger.py` block, but the ignore targets a SKIPPED test file (`test_billing_pricing_v2.py`); skip
- `scripts/distribution_manifest.yml` — main already lists `mcp-server.full/core/composition.json` in `forbidden_token_exclude_paths`, so the hunk is **already absorbed**; cherry-pick would be a near no-op

Estimated total conflicts for Option A: **0**.

## Section 3 — Operator-paste commands (1-line per step)

> Run these from repo root on a fresh **temporary branch** off `origin/main`, **not** directly on `main`.
> The follow-up lane will execute these only after the operator confirms "go".

```bash
# 0. Sanity — ensure clean tree on origin/main tip
git fetch origin && git checkout main && git pull --ff-only origin main

# 1. Create a temporary cherry-pick branch
git checkout -b chore/cl28-pr245-option-a-cherry-pick

# 2. A5 — 6 file ops (3 new + 1 init edit + 1 test file + 1 product file)
git checkout origin/worktree-agent-ac0ac5fdd0bcff29c -- src/jpintel_mcp/mcp/products/product_a5_kaisha_setsuritsu.py
git checkout origin/worktree-agent-ac0ac5fdd0bcff29c -- tests/test_product_a5_kaisha_setsuritsu.py
# products/__init__.py — manual single-line insert "product_a5_kaisha_setsuritsu" into _SUBMODULES tuple after product_a4_shuugyou_kisoku (line 51)

# 3. P4 — freshness (6 files)
git checkout origin/worktree-agent-ac0ac5fdd0bcff29c -- src/jpintel_mcp/mcp/autonomath_tools/answer_freshness_tool.py
git checkout origin/worktree-agent-ac0ac5fdd0bcff29c -- scripts/cron/answer_freshness_check_2026_05_17.py
git checkout origin/worktree-agent-ac0ac5fdd0bcff29c -- scripts/migrations/291_am_precomputed_answer_freshness.sql
git checkout origin/worktree-agent-ac0ac5fdd0bcff29c -- scripts/migrations/291_am_precomputed_answer_freshness_rollback.sql
git checkout origin/worktree-agent-ac0ac5fdd0bcff29c -- .github/workflows/answer-freshness-hourly.yml
# autonomath_tools/__init__.py — manual single-line insert "answer_freshness_tool," between annotation_tools (line 29) and audit_workpaper_v2 (line 30)

# 4. P5 — quality benchmark (2 files; mkdir parent first)
mkdir -p scripts/quality
git checkout origin/worktree-agent-ac0ac5fdd0bcff29c -- scripts/quality/__init__.py
git checkout origin/worktree-agent-ac0ac5fdd0bcff29c -- scripts/quality/benchmark_precomputed_answers_2026_05_17.py

# 5. Verify staged set (should be ~12 files; NO pricing_v2, NO test_billing_pricing_v2, NO docs/pricing.html)
git status --short

# 6. Run the canonical test slice (A5 only — P4/P5 ship NO new test files)
pytest -x tests/test_product_a5_kaisha_setsuritsu.py tests/test_no_llm_in_production.py

# 7. Mypy + ruff slice
mypy --strict src/jpintel_mcp/mcp/products/product_a5_kaisha_setsuritsu.py src/jpintel_mcp/mcp/autonomath_tools/answer_freshness_tool.py
ruff check src/jpintel_mcp/mcp/products/product_a5_kaisha_setsuritsu.py src/jpintel_mcp/mcp/autonomath_tools/ scripts/cron/answer_freshness_check_2026_05_17.py scripts/quality/

# 8. Commit via safe_commit (NEVER --no-verify)
scripts/safe_commit.sh -m "feat(A5+P4+P5): cherry-pick PR #245 Option A — Kaisha pack + Freshness + Quality benchmark [lane:solo]"

# 9. Push + open PR (do NOT direct-push to main)
git push -u origin chore/cl28-pr245-option-a-cherry-pick
gh pr create --base main --title "Option A cherry-pick from PR #245: A5 + P4 + P5" --body "Cherry-pick of fa3c80a47 minus A6 (pricing_v2 superseded by V3)."
```

## Section 4 — Post-merge verify

A5 ships **19 tests**. P4 and P5 ship **0 new test files** (validation is the cron + benchmark scripts themselves). The earlier "P4 11 + P5 12 = 42 tests" in CL28 prompt was incorrect; commit message lists "4 + 16" as **p0_pricing_policy + a3_a4 regression checks**, which already pass on main.

| check | command | expected |
| --- | --- | --- |
| A5 tests | `pytest tests/test_product_a5_kaisha_setsuritsu.py -v` | **19 PASS** |
| LLM guard | `pytest tests/test_no_llm_in_production.py -v` | 10 PASS (no regression) |
| Product surface count | `python scripts/probe_runtime_distribution.py` | A1-A5 (5 products) |
| MCP tool count delta | `len(await mcp.list_tools())` | +1 (`check_answer_freshness`) |
| Migration 291 dry-run | `sqlite3 :memory: < scripts/migrations/291_am_precomputed_answer_freshness.sql` | exit 0 |
| Freshness cron syntax | `python -c "import ast; ast.parse(open('scripts/cron/answer_freshness_check_2026_05_17.py').read())"` | exit 0 |
| Quality benchmark syntax | `python -c "import ast; ast.parse(open('scripts/quality/benchmark_precomputed_answers_2026_05_17.py').read())"` | exit 0 |
| GHA workflow | `actionlint .github/workflows/answer-freshness-hourly.yml` | 0 issues |
| pytest full | `pytest -n 6 -q` | no regression vs main baseline (10,966 / 9.24s, PERF baseline) |

## Section 5 — Risk register

1. **`scripts/quality/` dir absent on main.** Step 4 creates parent before checkout (mkdir is idempotent).
2. **`mcp-server.{full,core,composition}.json` excludes already on main.** Skipping the manifest hunk is the safe choice; if accidentally pulled, the result is no-op duplicates which `distribution_manifest_drift` does not flag.
3. **Migration 291 number collision.** Verify with `ls scripts/migrations/291_*` before paste; if any file with `291_` prefix is present on main, rename to next free number (sequence continues monotonically).
4. **A6 leakage.** If the operator changes their mind on A6 later, **rebuild on Pricing V3**, not by reviving `pricing_v2.py`. Memory note `project_jpcite_perf_baseline_2026_05_16` confirms V3 is canonical.
5. **CodeX collision.** This doc is the only new file created; no source edits, no manifest edits. Safe against parallel lanes.

## Section 6 — When NOT to execute

Skip Option A entirely if any of the following:

- Pricing V3 is mid-revision (check `git log --oneline -5 src/jpintel_mcp/billing/`).
- Migration 290 has not yet landed on main (`ls scripts/migrations/29*.sql` should show a contiguous `285..290.sql` series).
- `am_precomputed_answer` table is absent in autonomath.db schema (migration 291 ALTER TABLE will fail).

## Provenance

- Source PR: https://github.com/shigetosidumeda-cyber/autonomath-mcp/pull/245
- CL1 audit (prior): `docs/_internal/CL1_A5_A6_PR_MERGE_2026_05_17.md` (commit c54d86322)
- This doc: CL28, lane:solo, 2026-05-17
- Constraint: READ-ONLY analysis, no actual cherry-pick, no main edits beyond this doc
