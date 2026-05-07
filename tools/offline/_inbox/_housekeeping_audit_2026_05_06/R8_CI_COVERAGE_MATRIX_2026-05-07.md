# R8 — CI Gate Coverage Matrix (2026-05-07)

**Scope**: audit `release.yml` + `test.yml` against the 2026-05-07 hardening
"Wave hardening" (CLAUDE.md §Wave hardening 2026-05-07) — verify each
hardening axis is gated by some workflow, identify true gaps, propose
additive steps where a CI gate is missing.

**Constraint**: LLM API calls = 0. Destructive overwrite = forbidden.
Edits to `test.yml` / `release.yml` are deferred to
`scripts/ops/sync_workflow_targets.py` regen — this audit produces only the
matrix + gap list.

---

## 1. Workflow inventory (post-hardening)

| Workflow file | Trigger | Gate kind | Hard-fail? |
|---|---|---|---|
| `.github/workflows/test.yml` | push/PR all branches | unit + lint + ruff format + pytest + pip-audit + mypy plain + mkdocs strict | mostly hard; mypy + pip-audit + codecov are `continue-on-error: true` |
| `.github/workflows/release.yml` | tag `v*` + workflow_dispatch | release-gate test job + build sdist/wheel + PyPI publish + GitHub release | hard (no continue-on-error on test/build/publish) |
| `.github/workflows/release-readiness-ci.yml` | PR/push main + tag `v*` | `scripts/ops/release_readiness.py` 9-check hard gate | hard (default exit-non-zero) |
| `.github/workflows/fingerprint-sot-guard.yml` | PR main + path filter on 5 paths | AST structural + runtime equality on dirty fingerprint helper | hard |
| `.github/workflows/acceptance_criteria_ci.yml` | PR main + weekly cron + dispatch | DEEP-59 acceptance criteria (286 row YAML) + automation ratio target | hard |

YAML `safe_load` verify: all 5 files parse cleanly.
Jobs surfaced: `pytest` / `[test, build, publish-pypi, github-release]` /
`release-readiness` / `fingerprint-sot-guard` / `acceptance-guard`.

---

## 2. Hardening axis × CI gate matrix

Source: CLAUDE.md "Wave hardening 2026-05-07" plus the 4 source-of-truth
artifacts (`R8_33_SPEC_RETROACTIVE_VERIFY.md`,
`R8_BILLING_FAIL_CLOSED_VERIFY.md`,
`R8_DRY_RUN_VALIDATION_REPORT.md`,
`R8_SMOKE_FULL_GATE_2026-05-07.md`).

| # | Hardening axis | Expected gate | Actual gate | Status |
|---|---|---|---|---|
| 1 | mypy plain (best-effort) | test.yml mypy step | test.yml L512–520 (`continue-on-error: true`, py3.12 only) | COVERED — best-effort red signal only, intentional |
| 2 | mypy --strict (348→69) | future work | NOT GATED anywhere | GAP-1 (low) — post-launch; tracked in CLAUDE.md |
| 3 | ruff check on lint target | test.yml + release.yml | test.yml L497, release.yml L506–547 | COVERED |
| 4 | ruff format --check | test.yml + release.yml | test.yml L500, release.yml L549–550 | COVERED |
| 5 | pytest PYTEST_TARGETS suite | test.yml + release.yml (sync'd) | test.yml L502, release.yml L552–553 (env list mirrored) | COVERED |
| 6 | acceptance criteria 286 rows | dedicated workflow | acceptance_criteria_ci.yml | COVERED — separate hard-gate workflow |
| 7 | release readiness 9-check | dedicated workflow | release-readiness-ci.yml | COVERED |
| 8 | dirty fingerprint SOT | dedicated workflow | fingerprint-sot-guard.yml | COVERED — AST + runtime equality |
| 9 | smoke gate 17/17 | launch-time manual | NOT GATED (intentional, manual `scripts/ops/post_deploy_smoke.py` post-deploy) | INTENTIONAL — `tests/test_post_deploy_smoke.py` is in PYTEST_TARGETS so the wrapper is tested, the live-fly probe is manual |
| 10 | disclaimer envelope (11 sensitive tools) | pytest target | `tests/test_disclaimer_envelope.py` is in PYTEST_TARGETS (test.yml L186, release.yml L195) | COVERED |
| 11 | 33 DEEP spec (DEEP-22..65) retroactive | pytest + acceptance | covered in `tests/test_acceptance_criteria.py` + ad-hoc DEEP-prefixed unit tests (`test_business_law_corpus.py`, `test_business_law_detector.py`, `test_cohort_resources.py`, etc.) all in PYTEST_TARGETS | COVERED — retroactively |
| 12 | release readiness pytest pair | both | `tests/test_release_readiness.py` + `tests/test_release_readiness_ci.py` in PYTEST_TARGETS (test.yml L394–395, release.yml L403–404) | COVERED |
| 13 | LLM 0 in src/ guard | pytest target | `tests/test_no_llm_in_production.py` in PYTEST_TARGETS (test.yml L342, release.yml L351) | COVERED |
| 14 | distribution manifest sync | dedicated workflow | distribution-manifest-check.yml + `tests/test_distribution_manifest.py` in PYTEST_TARGETS | COVERED |
| 15 | env list sync test↔release | sync_workflow_targets | `tests/test_sync_workflow_targets.py` in PYTEST_TARGETS + check-workflow-target-sync.yml workflow | COVERED |
| 16 | pip-audit supply-chain | test.yml | test.yml L505–510 (`continue-on-error: true`) | PARTIAL — not blocking; intentional triage path |
| 17 | mkdocs --strict | test.yml | test.yml L526–528 (py3.12 only) | COVERED |

---

## 3. True gaps

### GAP-1 (low / accepted): mypy --strict not in CI

CLAUDE.md confirms residual = 69 errors, scoped to legacy
`models.py` Optional + Pydantic v1/v2 boundary. Adding `mypy --strict src/`
to test.yml would fail until the residuals are cleared. Decision: keep as
post-launch follow-up. Recorded in CLAUDE.md, NOT proposed as a CI gate
addition right now.

### GAP-2 (intentional / accepted): smoke 17/17 not in CI

Smoke gate is launch-time manual (`scripts/ops/post_deploy_smoke.py`
against the live Fly app). The Python wrapper itself
(`tests/test_post_deploy_smoke.py`) IS gated by PYTEST_TARGETS, so the
script's structure can't regress. Live-fly probe stays manual to avoid
spurious CI red on Fly transient noise.

### No additional GAPs found

Every other hardening axis listed in CLAUDE.md §"Wave hardening 2026-05-07"
maps to either a PYTEST_TARGETS entry (mirrored across `test.yml` and
`release.yml`) or a dedicated workflow (`acceptance_criteria_ci.yml`,
`release-readiness-ci.yml`, `fingerprint-sot-guard.yml`).

---

## 4. Additive step proposals

**None executed**. Per constraint ("既存 workflow への追記は 慎重 / sync_workflow_targets で再生成可能"),
no edits to `test.yml` / `release.yml` are made. Future bumps to
PYTEST_TARGETS / RUFF_TARGETS go through
`scripts/ops/sync_workflow_targets.py` so test.yml and release.yml stay in
lockstep.

For visibility, two **non-blocking** future considerations:

1. **mypy --strict ratchet** — once `models.py` Optional cleanup is done,
   add a second mypy step in test.yml gated to py3.12, `--strict src/`,
   non-`continue-on-error`. Skipped for v0.3.4.
2. **post-deploy smoke smoke shadow** — could add a `workflow_dispatch`-only
   job that runs `scripts/ops/post_deploy_smoke.py --base-url=staging`.
   Today there is no staging Fly app, so this is not actionable.

---

## 5. YAML lint summary (PyYAML safe_load)

```
test.yml:                     OK, jobs=['pytest']
release.yml:                  OK, jobs=['test','build','publish-pypi','github-release']
release-readiness-ci.yml:     OK, jobs=['release-readiness']
fingerprint-sot-guard.yml:    OK, jobs=['fingerprint-sot-guard']
acceptance_criteria_ci.yml:   OK, jobs=['acceptance-guard']
```

All 5 workflow files parse without error. No structural changes proposed.

---

## 6. Verdict

**Coverage = green for v0.3.4 launch.** All hardening axes called out in
CLAUDE.md §"Wave hardening 2026-05-07" are either gated by CI or
documented as intentional manual / post-launch (mypy --strict + smoke
17/17). No workflow edits required this session; this matrix exists as the
audit artifact for R8 closure.

Workflow files unchanged. Doc force-added under
`tools/offline/_inbox/_housekeeping_audit_2026_05_06/`.
