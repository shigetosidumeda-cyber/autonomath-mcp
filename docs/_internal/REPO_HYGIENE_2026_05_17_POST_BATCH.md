# Repo hygiene — post-batch sweep — 2026-05-17

Post-cleanup attribution after a 12-parallel-agent batch lifted `main` from
~17 commits ahead to ~18 commits ahead of `origin/main` over the course of
roughly one hour. This doc is **attribution-only** — no reverts, no rewrites.

## Snapshot at hygiene-lane entry

- HEAD: `cae13cf87 docs(smoke): safe_commit.sh validation [lane:solo]`
- Branch: `main`
- Ahead of `origin/main`: 13 commits.
- Single untracked artifact at entry: `docs/_internal/SAFE_COMMIT_SMOKE_2026_05_17.md`.

During hygiene work, multiple parallel lanes continued to emit:

- Wave 99 lane (#256): `infra/aws/athena/big_queries/wave99/Q54..Q57.sql` + 4
  packet generators (`generate_outcome_chain_routing_packets.py` /
  `generate_outcome_cost_band_packets.py` /
  `generate_segment_pivot_routing_packets.py` /
  `generate_program_eligibility_chain_packets.py` /
  `generate_subsidy_combo_finder_packets.py` /
  `generate_corporate_360_snapshot_packets.py`)
- Wave 51 L4 lane (#262): `src/jpintel_mcp/predictive_merge/` (3 files —
  `__init__.py` / `models.py` / `merge.py`)
- CHANGELOG sync lane (#263): `CHANGELOG.md` v0.5.1 178-line addition
- FAISS rebuild lane: 4 `scripts/aws_credit_ops/build_faiss_*.py` modifications
- Tests lane: `tests/__init__.py` mutation
- Docs lane: `docs/_internal/ATHENA_QUERY_INDEX_2026_05_17.md` +
  `docs/_internal/PERF_40_FAISS_NPROBE_PROPOSAL.md`

## Lane drift events (attribution, NOT reverts)

### Lane drift A — `0d8470fb1` bundled 9 files outside its declared scope

| Field | Value |
| --- | --- |
| Commit SHA | `0d8470fb10d15ec30031e44d3ae41848122d5e71` |
| Declared subject | `docs(changelog): v0.5.1 entries (...) [lane:solo]` |
| Declared task | #263 — CHANGELOG sync v0.5.1 |
| File changes | 10 files, +1888 lines |

The commit's stated scope was the v0.5.1 CHANGELOG entry. Actual file
changes:

- `CHANGELOG.md` (declared scope — 178 lines) — **in scope**.
- `infra/aws/athena/big_queries/wave99/Q54_outcome_evidence_governance_chain.sql` — **out of scope, Wave 99 task #256**.
- `infra/aws/athena/big_queries/wave99/Q55_data_governance_x_program_eligibility.sql` — **out of scope, Wave 99 task #256**.
- `infra/aws/athena/big_queries/wave99/Q56_data_residency_x_program_offering.sql` — **out of scope, Wave 99 task #256**.
- `infra/aws/athena/big_queries/wave99/Q57_allwave_grand_aggregate_wave_95_97.sql` — **out of scope, Wave 99 task #256**.
- `scripts/aws_credit_ops/generate_outcome_chain_routing_packets.py` — **out of scope, Wave 99 task #256**.
- `scripts/aws_credit_ops/generate_outcome_cost_band_packets.py` — **out of scope, Wave 99 task #256**.
- `scripts/aws_credit_ops/generate_segment_pivot_routing_packets.py` — **out of scope, Wave 99 task #256**.
- `src/jpintel_mcp/predictive_merge/__init__.py` — **out of scope, Wave 51 L4 task #262**.
- `src/jpintel_mcp/predictive_merge/merge.py` — **out of scope, Wave 51 L4 task #262**.
- `src/jpintel_mcp/predictive_merge/models.py` — **out of scope, Wave 51 L4 task #262**.

Likely root cause: the CHANGELOG lane ran `git commit` while the hygiene lane
had Wave 99 + Wave 51 L4 source files staged. Pre-commit's auto-stash /
unstash cycle interacted with concurrent `git add` calls, and the
CHANGELOG-lane process consumed the index state at commit time. Result: 9
files attributed to the wrong commit.

Impact: **none on correctness** — every bundled file is real, intentional
source code and was already authored by its owning lane. Bundle just moves
attribution from (#256 / #262) to (#263). No revert is needed; the bundled
files are not in conflict with their owning lanes (the lanes' future
follow-up commits will simply observe the files already present in HEAD).

### Lane drift B — `cae13cf87` (declared scope), then re-edited

`cae13cf87 docs(smoke): safe_commit.sh validation` landed a thin stub
(18 lines). It was then upgraded by a parallel lane to a full 94-line
3-scenario validation in `fc58657dd docs(smoke): safe_commit.sh 3-scenario verify`.
Both commits stay on `main` — no rewrite. Honest delta = 18 → 94 lines
across two commits.

### Lane drift C — `23a77fec5` committed a fixture file

`23a77fec5 test(autofix): pre-commit hook collision smoke` committed
`docs/_internal/SAFE_COMMIT_AUTOFIX_TEST.md` — a 2-line fixture that
**intentionally violates** trailing-whitespace + EOF-newline rules. The
hygiene lane initially added it to `.gitignore` (line 252) under the
assumption it should never be tracked, but reverted that addition once it
became clear the lane intentionally tracked the fixture as Scenario C
proof that pre-commit's auto-fix path runs end-to-end. Honest: the file
is tracked on `main` and the pre-commit hooks will continue to auto-fix
it on every touch.

## Working tree after hygiene-lane exit

- HEAD: (this commit when landed)
- Modified-but-unstaged (left for owning lanes):
  - `CHANGELOG.md` — v0.5.1 follow-up edits, owner = task #263.
  - `scripts/aws_credit_ops/build_faiss_index_from_embeddings.py` — owner = FAISS lane.
  - `scripts/aws_credit_ops/build_faiss_v2_expand.py` — owner = FAISS lane.
  - `scripts/aws_credit_ops/build_faiss_v2_from_sagemaker.py` — owner = FAISS lane.
  - `scripts/aws_credit_ops/build_faiss_v3_expand.py` — owner = FAISS lane.
  - `tests/__init__.py` — owner = tests lane.
- Untracked-but-real-source (left for owning lanes to commit):
  - `docs/_internal/ATHENA_QUERY_INDEX_2026_05_17.md`
  - `docs/_internal/PERF_40_FAISS_NPROBE_PROPOSAL.md`
  - `scripts/aws_credit_ops/generate_corporate_360_snapshot_packets.py`
  - `scripts/aws_credit_ops/generate_program_eligibility_chain_packets.py`
  - `scripts/aws_credit_ops/generate_subsidy_combo_finder_packets.py`

## .gitignore polish

No net change. The hygiene lane briefly added
`docs/_internal/SAFE_COMMIT_AUTOFIX_TEST.md` to .gitignore but reverted
once it was confirmed the autofix-test lane intentionally tracks the
file as a smoke-test fixture. All other drift categories (`*.bak`,
`*.swp`, `.DS_Store`, `__pycache__/`, `coverage*`, `*.db.bak*`,
`autonomath.db-wal`, `autonomath.db-shm`, generator output dirs)
remain covered by existing rules.

## Security notes

- No secrets observed in untracked content.
- No agent-prompt-injection artifacts observed.
- No unauthorized binaries dropped under `dist/`, `build/`, or `.venv/`.
- All untracked Python sources carry expected `#!/usr/bin/env python3`
  shebangs and CLAUDE.md `[lane:solo]` markers in their docstrings.

last_updated: 2026-05-17
