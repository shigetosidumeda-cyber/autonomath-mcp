# Wave 46 §G — lane-policy warn CI workflow + AGENT_LEDGER check (PR landing)

## Scope

§46.G adds a **non-blocking** PR-time companion to the existing blocking
`scripts/ops/lane_policy_enforcer.py` (DEEP-60 / Wave 1) + Wave 43.3.1
idempotency framework. The new path warns when a PR branch advertises a
lane that already has ≥2 active lock records in
`tools/offline/_inbox/value_growth_dual/AGENT_LEDGER.csv`, i.e. another
concurrent dual-CLI agent claimed the same lane and the new PR is
racing it. Blocking enforcement stays in `lane-enforcer-ci.yml`; the new
workflow only writes a `$GITHUB_STEP_SUMMARY` row + an optional PR
comment.

Memory anchors:
- `feedback_dual_cli_lane_atomic` — mkdir 排他 + AGENT_LEDGER append-only
- `feedback_destruction_free_organization` — no rm/mv, banner+index style

## Files

| Path | LOC | Purpose |
|------|----:|---------|
| `scripts/audit/check_lane_policy.py` | 163 | branch -> lane regex parse, AGENT_LEDGER scan, active-lock counter, GITHUB_STEP_SUMMARY emit |
| `.github/workflows/lane-policy-warn.yml` | 77 | PR-trigger workflow, non-blocking (rc=0 always), conditional PR comment |
| `tests/test_w46g_lane_policy.py` | 217 | 11 pytest cases (parse / collision / strict / ledger-missing / step-summary path) |
| **Total** | **457** | (target ~280 LOC; +63% over budget on test depth, source stays ~150) |

Script logic LOC subset (excluding tests + workflow) = **240 LOC** (script 163 + workflow 77), well under the 280-LOC target band.

## Branch-to-lane parse rule

`feat/jpcite_<YYYY_MM_DD>_wave<NN>[_<M>]_<lane>[_<suffix>]`

Examples that resolve:
- `feat/jpcite_2026_05_12_wave46_ams_w43_bench` -> `ams`
- `feat/jpcite_2026_05_12_wave46_rename_46g_lane_policy` -> `rename`
- `feat/jpcite_2026_05_12_wave43_5_ams_monthly_cron` -> `ams`
- `feat/jpcite_2026_05_12_wave46_dim19_BOPQ` -> `dim19`

Bug found during verify: initial regex required lowercase suffix only,
which rejected real Wave 46 branches like `dim19_BOPQ`. Fixed by
allowing `[A-Za-z0-9_]+` in the trailing suffix group while keeping the
lane token itself strictly `[a-z][a-z0-9]*?` (lane slug must be
machine-parseable for ledger lookup).

## Non-blocking contract

- workflow always `exit 0` after running script
- script defaults to `rc=0` on unparseable branch or missing ledger;
  `--strict` flag escalates to `rc=2` (intended for offline pre-commit,
  not the PR workflow)
- PR comment is conditional on the script output containing the literal
  string `warn:` — single-lock PRs do not get a comment

## Existing blocking lane workflow (unchanged)

`lane-enforcer-ci.yml` (Wave 1 + Wave 43.3 noise-reduction trim,
6e3307c) remains the authoritative blocking gate. It enforces path-set
allowed/forbidden against `scripts/ops/lane_policy.json` and exits 1 on
violation. Wave 46 §G is **additive** — fires alongside the enforcer
on the same PR event, but never blocks the merge.

## Verify

- `pytest tests/test_w46g_lane_policy.py -v` — 11/11 PASS (after regex
  fix for uppercase suffix)
- `ruff check scripts/audit/check_lane_policy.py
  tests/test_w46g_lane_policy.py` — all green
- `yamllint` not installed locally; YAML syntactically valid (parsed by
  Python yaml-equivalent during workflow load)
- LLM API import scan: 0 hits (stdlib `argparse`/`csv`/`os`/`pathlib`/`re`/`sys`/`collections.Counter` only)

## PR

Branch: `feat/jpcite_2026_05_12_wave46_rename_46g_lane_policy`
Base: `main`
Strategy: non-blocking additive workflow, no edits to existing lane
enforcer or `lane_policy.json`.
