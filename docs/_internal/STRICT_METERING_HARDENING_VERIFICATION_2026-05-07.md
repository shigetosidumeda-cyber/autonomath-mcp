# Strict Metering Hardening Verification 2026-05-07

Purpose: strict metering hardening のローカル検証コマンドと、ここまでに実行済みまたは報告済みの合格結果を1か所に固定する。リリース担当はこのファイルを上から順に再実行し、結果差分が出た場合は「テスト追加による件数増減」か「回帰」かを切り分ける。

Scope: production deploy は行わない。外部課金、secret 更新、Fly deploy、DB migration apply、live ingest は含めない。対象はローカル pytest / ruff / git diff check / release gate の確認だけ。

## Target API Surfaces

- Core REST/API wiring: `tests/test_api.py`, `tests/test_main.py`, endpoint smoke, OpenAPI/response model/export alignment.
- Paid endpoint strict metering: houjin, citations, funding stack, kaikei workpaper, tax rulesets, loan/program/prescreen/discover/intelligence/bids style endpoint bundles.
- Invoice/laws/enforcement/case/calendar: invoice registrants, laws, enforcement, case studies, calendar, ICS.
- Court/source/saved: court decisions, source manifest, saved searches.
- AutonoMath/evidence/ping additions: AutonoMath paid endpoints, Evidence Batch/Packet paid-output behavior, `/ping` anonymous vs paid usage behavior.
- Release gates: `release_readiness`, `pre_deploy_verify`, `production_deploy_go_gate` are informational until dirty tree and operator ACK are resolved.

## Reported Green Test Bundles

These counts are the latest reported local results for this strict-metering-hardening pass. If a rerun collects a different number because tests were added, preserve the new output with the exact command and timestamp.

| bundle | reported result | command to rerun |
| --- | ---: | --- |
| major endpoint bundle | `166 passed` | `uv run pytest tests/test_endpoint_smoke.py tests/test_api.py tests/test_main.py tests/test_houjin_endpoint.py tests/test_citation_verifier.py tests/test_funding_stack_checker.py tests/test_kaikei_workpaper.py tests/test_tax_rulesets_billing.py tests/test_loan_programs.py tests/test_programs.py tests/test_prescreen.py tests/test_discover_related.py tests/test_intelligence_api.py tests/test_bids_billing.py` |
| core API bundle | `70 passed` | `uv run pytest tests/test_api.py tests/test_main.py tests/test_openapi_agent.py tests/test_openapi_export.py tests/test_openapi_response_models.py tests/test_audit_seal_wire.py tests/test_make_error_envelope.py tests/test_endpoint_smoke.py` |
| invoice/laws/enforcement/case/calendar bundle | `72 passed` | `uv run pytest tests/test_invoice_registrants_billing.py tests/test_laws_billing.py tests/test_enforcement.py tests/test_case_studies.py tests/test_calendar.py tests/test_calendar_ics.py` |
| court/source/saved bundle | `26 passed` | `uv run pytest tests/test_court_decisions_billing.py tests/test_source_manifest.py tests/test_saved_searches.py` |
| AutonoMath/evidence/ping added bundle | `18 passed` | `uv run pytest tests/test_autonomath_billing.py tests/test_evidence_batch.py tests/test_ping.py` |

## Individual Checks

Run these when narrowing a failure from the larger bundles.

```bash
uv run pytest tests/test_autonomath_billing.py
uv run pytest tests/test_ping.py
uv run pytest tests/test_ping.py::test_ping_paid_final_cap_failure_returns_503_without_usage_event
uv run pytest tests/test_evidence_batch.py::test_paid_batch_fails_closed_when_final_metering_cap_rejects
uv run ruff check src tests
git diff --check -- docs/_internal/STRICT_METERING_HARDENING_VERIFICATION_2026-05-07.md
```

Expected local result for this document pass:

- `tests/test_autonomath_billing.py`: reported green.
- `tests/test_ping.py`: reported green, including paid final-cap failure returning `503` without inserting a usage event.
- `ruff check`: reported green for the strict metering hardening patch scope.
- `git diff --check`: must be green for this file before handoff.

## Release担当の再実行順

1. Confirm the tree scope before running broad tests:

```bash
git status --short
git diff --check -- docs/_internal/STRICT_METERING_HARDENING_VERIFICATION_2026-05-07.md
```

2. Rerun the strict metering bundles:

```bash
uv run pytest tests/test_endpoint_smoke.py tests/test_api.py tests/test_main.py tests/test_houjin_endpoint.py tests/test_citation_verifier.py tests/test_funding_stack_checker.py tests/test_kaikei_workpaper.py tests/test_tax_rulesets_billing.py tests/test_loan_programs.py tests/test_programs.py tests/test_prescreen.py tests/test_discover_related.py tests/test_intelligence_api.py tests/test_bids_billing.py
uv run pytest tests/test_api.py tests/test_main.py tests/test_openapi_agent.py tests/test_openapi_export.py tests/test_openapi_response_models.py tests/test_audit_seal_wire.py tests/test_make_error_envelope.py tests/test_endpoint_smoke.py
uv run pytest tests/test_invoice_registrants_billing.py tests/test_laws_billing.py tests/test_enforcement.py tests/test_case_studies.py tests/test_calendar.py tests/test_calendar_ics.py
uv run pytest tests/test_court_decisions_billing.py tests/test_source_manifest.py tests/test_saved_searches.py
uv run pytest tests/test_autonomath_billing.py tests/test_evidence_batch.py tests/test_ping.py
```

3. Rerun lint and local release gates:

```bash
uv run ruff check src tests
uv run python scripts/ops/release_readiness.py --warn-only
uv run python scripts/ops/pre_deploy_verify.py --preflight-db autonomath.db --warn-only
uv run python scripts/ops/production_deploy_go_gate.py --warn-only
```

Expected gate interpretation: local test bundles can be green while deploy remains NO-GO. Do not convert local pytest success into deploy authorization.

## Known Residual Risks

- Dirty tree: the repository has broad modified/untracked content across runtime code, tests, docs, generated site/assets, workflows, migrations, SDKs, and operator/offline files. Do not use `git add .`; packetize by reviewed path lists only.
- `release_readiness`: known residual failure is `workflow_targets_git_tracked` while workflow/script/test targets are still dirty or untracked. Treat `--warn-only` output as evidence, not a GO signal.
- Operator ACK: `production_deploy_go_gate.py` remains blocked without an out-of-repo operator ACK containing all required confirmations. The ACK body must not be committed.
- Existing query mismatch: `tests/test_rest_search_tax_incentives.py` has a known pre-existing query mismatch risk outside this strict metering hardening pass. Do not hide it by broad `-k` filters in release evidence; either rerun and record the failure explicitly or fix it in a separate scoped packet.
- Live-system uncertainty: no command in this file proves Stripe live metering, Fly runtime health, production DB migration state, or third-party ingest behavior.

## Handoff Rule

For release evidence, paste the final command output summary beside the command that produced it. If a bundle count changes, record the collected count and whether the delta is due to newly added tests, skipped tests, or failures. The minimum acceptable handoff includes green `git diff --check` for this file plus fresh pytest output for the five bundles above.
