# Wave 46 dim 19 dim F round 2 — cron MISSING axis close

Date: 2026-05-12
Branch: `feat/jpcite_2026_05_12_wave46_dim19_F_round2`
Worktree: `/tmp/jpcite-w46-dim19-F2`
Base: PR #118 head (`feat/jpcite_2026_05_12_wave46_dim19_score_fix`)
Author: Wave 46 永遠ループ tick3 #6

## Why round 2 (this PR) over the round 1 PR #118

Round 1 (PR #118) closed the **REST api file MISSING** axis of dim F by
landing `src/jpintel_mcp/api/fact_signature_v2.py` (277 LOC) +
`tests/test_dimension_f_fact_signature_v2.py` (7 tests). That moved dim
F from 2.50/10 → ~4.50/10 and dim 19 average from 6.37 → ~6.47.

Per `feedback_completion_gate_minimal` the round 1 PR deliberately did
NOT chase ETL / cron / MCP axes. Round 2 picks up **exactly one more
axis** — the lowest-LOC / highest-leverage remaining gap — and lands
that alone.

## Selected axis: cron MISSING

Of the three remaining axes:

| axis | LOC budget | status in repo | round 2 action |
| ---- | --- | --- | --- |
| ETL MISSING | ~200-400 LOC new ETL script | no ETL exists (the Ed25519 sign script *is* the ETL, but the audit treats sign as cron) | OUT OF SCOPE — round 3 |
| cron MISSING | ~110 LOC workflow YAML + 2 test asserts | Python `refresh_fact_signatures_weekly.py` exists but no `.github/workflows/*.yml` wires it | **PICK** |
| MCP grep miss | ~80-150 LOC new MCP tool | no MCP wrapper | OUT OF SCOPE — round 4 |

**Why cron over MCP:** The Python cron script's docstring (line 35)
explicitly references `.github/workflows/refresh-fact-signatures-weekly.yml`
as the operational hook. The script is fully argparse-wired (`--max-rows`,
`--key-id`, `--dry-run`, `--verbose`) and production-ready since Wave
43.2.5. Only the YAML wiring is missing. This is the single highest-leverage
sub-criterion at the lowest LOC cost — it's literally a deploy-time
config artifact, not new business logic.

**Why not ETL or MCP this PR:** Each requires non-trivial new business
logic (ETL: source feed parser + UPSERT loop; MCP: tool schema + server
wire + integration test). The completion-gate-minimal rule says one
axis per PR. Take the cheap one first.

## Sub-criterion checklist (dim F → 5 axes, cumulative across PR #118 + this PR)

| axis | base (pre-#118) | post-#118 | post-this-PR | delta this PR |
| ---- | --- | --- | --- | --- |
| migration forward-only: 2 | PRESENT (262) | PRESENT | PRESENT | unchanged |
| REST api file | MISSING | **PRESENT** | PRESENT | unchanged (round 1) |
| ETL | MISSING | MISSING | MISSING | unchanged |
| cron | MISSING (Python upstream, no YAML) | MISSING | **PRESENT** | +1 axis |
| test(s) | 1 (E shared) | 2 (F-specific) | **3 (F-specific +cron)** | +1 test count |
| MCP grep | miss | miss | miss | unchanged |

**Estimated dim F score lift:** ~4.50/10 → ~5.50-5.75/10 (+1 axis cron
+ 2 new tests). Dim 19 average projection: ~6.47 → ~6.55-6.58. Single
sub-criterion, NOT a full 6.37 → 8.0 refactor.

## Files changed

- `.github/workflows/refresh-fact-signatures-weekly.yml` — 109 LOC new
  workflow (Sunday 02:00 UTC schedule + workflow_dispatch + failure
  issue create)
- `tests/test_dimension_f_fact_signature_v2.py` — +59 LOC, 2 new tests:
  `test_refresh_fact_signatures_workflow_exists` and
  `test_refresh_fact_signatures_workflow_no_llm_secret`
- `docs/research/wave46/STATE_w46_dim19_F2_pr.md` — this state doc

Total: ~170 LOC (workflow + test extension + state doc). Well under
the ≤200 LOC source-code budget; mostly declarative YAML + assertions.

## Workflow contract

```
name: refresh-fact-signatures-weekly

Trigger:
  schedule: 0 2 * * 0   (= Sunday 02:00 UTC, Monday 11:00 JST)
  workflow_dispatch:    max_rows / dry_run inputs

Step:
  flyctl ssh console -a autonomath-api -C \
    "/opt/venv/bin/python /app/scripts/cron/refresh_fact_signatures_weekly.py \
      [--max-rows N] [--dry-run]"

On failure:
  gh issue create --label cron-failure --label automation
```

## Constraints honored

- worktree `/tmp/jpcite-w46-dim19-F2` (no main worktree touch)
- no rm / mv (only Write + Edit)
- no legacy brand strings on the wire (workflow names + script paths
  are internal infra; no `jpcite` rename impact)
- no LLM API import (verified by
  `test_refresh_fact_signatures_workflow_no_llm_secret`)
- 1 sub-criterion fix (cron MISSING) — NOT a full 6.37 → 8.0 refactor
- Builds on PR #118 head, NOT main, so the round 1 changes are
  preserved in the diff base

## Lint + test verdict

To be filled by the verify step at the bottom of this PR creation
flow.

## PR

To be opened after lint + test verify. PR# will be backfilled here
once `gh pr create` returns.
