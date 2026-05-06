# Production Deploy Packet Manifest 2026-05-07

Status: draft / NO-GO.

この文書は、本番deployへ進む前に dirty tree を packet 化するための整理表である。
ここに列挙しても、commit、deploy、secret変更、production DB migration適用、
cron有効化、operator ACK true化は承認しない。

## 現在の機械ゲート

- 2026-05-07 07:14 JST:
  `pre_deploy_verify.py --preflight-db autonomath.db`: GO相当、
  `3 pass / 0 fail / 3`。
- 2026-05-07 07:14 JST:
  `production_deploy_go_gate.py --warn-only`: NO-GO、
  `3 pass / 2 fail / 5`。残りは `dirty_tree_present:1347` と
  `operator_ack:not_provided_or_unreadable`。
- A packet workflow pytest targets: `420 passed, 2 warnings`。
- A packet Ruff targets: `16 files`、`ruff check` / `ruff format --check` pass。
- workflow YAML safe-load: `test.yml`, `release.yml`, `deploy.yml` pass。

最新 dirty fingerprint:

- current_head: `29d214b8fda6fa61459288aaf57b24964d8d9db6`
- status_counts: `{"??": 468, "A": 16, "D": 1, "M": 862}`
- path_sha256: `309d86cf29f387a17a4048dc2c645653a7e1ba3cc4cbf12a154a69baf9ad88c0`
- content_sha256: `7b1ae3a8a69124a51aa69c20bda17f8efac956c8eccada64d00c246fed0a5463`
- critical lanes:
  `billing_auth_security`, `cron_etl_ops`, `migrations`, `root_release_files`,
  `runtime_code`

## Packet A: 本番安全 hardening

目的: 現在の公開本番を壊しにくくする fail-closed / boot / deploy gate 修正。
experimental value surface は default-off のままにする。

含める候補:

- `src/jpintel_mcp/api/main.py`
- `src/jpintel_mcp/mcp/autonomath_tools/__init__.py`
- `src/jpintel_mcp/api/customer_webhooks.py`
- `src/jpintel_mcp/api/courses.py`
- `src/jpintel_mcp/api/recurring_quarterly.py`
- `src/jpintel_mcp/billing/delivery.py`
- `scripts/cron/dispatch_webhooks.py`
- `scripts/cron/generate_quarterly_reports.py`
- `scripts/cron/run_saved_searches.py`
- `tests/test_metered_delivery.py`
- `tests/test_courses.py`
- `tests/test_recurring_engagement.py`
- `tests/test_run_saved_searches.py`
- `tests/test_customer_webhooks.py`
- `tests/test_dispatch_webhooks.py`
- `tests/test_customer_webhooks_test_rate_persisted.py`
- `tests/test_autonomath_billing.py`
- `tests/test_autonomath_static_billing.py`
- `tests/test_audit_seal_static_guard.py`
- `scripts/migrations/wave24_143_customer_webhooks_test_hits.sql`
- `scripts/migrations/wave24_143_customer_webhooks_test_hits_rollback.sql`

確認済み:

- focused integration suite: `104 passed, 2 warnings`。
- boot/main subset: `34 passed`。
- 課金/配信/recurring/course regression:
  `55 passed, 1 warning`。
- boot/secret/Fly regression:
  `44 passed`。
- A packet workflow pytest targets: `420 passed, 2 warnings`。
- Ruff check / Ruff format check / `git diff --check`: pass。
- `create_app()` default-off: `217` routes。

注意:

- `wave24_143_customer_webhooks_test_hits.sql` は additive だが、
  production DB apply は operator承認が必要。
- `AUTONOMATH_EXPERIMENTAL_API_ENABLED` と
  `AUTONOMATH_EXPERIMENTAL_MCP_ENABLED` は default-off 維持。
- experimental flag-on を本番で使うなら Packet B と migration/schema を同時に扱う。
- Webhookは2xx配送後だけ課金する。失敗HTTP配信は課金しない。
- Recurring quarterly PDFはrender成功後に課金し、課金成功後だけcacheへpromoteする。
- Course subscriptionは課金失敗時にactive rowを残さない。
- production boot gateは `sk_test_...` Stripe key を拒否する。

## Packet A2: deploy gate / workflow target追跡

目的: `workflow_targets_git_tracked` を false green なしで解消する。
workflowに載せた target は、CI checkout上にも存在しなければならない。

最低限含める候補:

- `scripts/ops/perf_smoke.py`
- `scripts/ops/pre_deploy_verify.py`
- `scripts/ops/preflight_production_improvement.py`
- `scripts/ops/production_deploy_go_gate.py`
- `scripts/ops/release_readiness.py`
- `scripts/ops/repo_dirty_lane_report.py`
- `tests/test_appi_turnstile.py`
- `tests/test_boot_gate.py`
- `tests/test_ci_workflows.py`
- `tests/test_entrypoint_vec0_boot_gate.py`
- `tests/test_fly_health_check.py`
- `tests/test_perf_smoke.py`
- `tests/test_pre_deploy_verify.py`
- `tests/test_production_deploy_go_gate.py`
- `tests/test_production_improvement_preflight.py`
- `tests/test_release_readiness.py`

注意:

- `tests/test_boot_gate.py` は、Packet A の default-off lazy import により、
  experimental API moduleを同時shipしなくても collection/実行可能に寄せた。
- `deploy.yml`, `test.yml`, `release.yml` の変更はこの packet と同時に扱う。
- この packet は本番deployを許可しない。ACKとdirty reviewが別に必要。
- 2026-05-07時点では A packet向けに 43 pytest targets / 16 Ruff targets
  へ整理済み。`artifact`, `gBiz`, `PSF`, `OpenAPI/distribution`, eval系は
  Packet B/C に分離する。
- A packet targetの未追跡ファイルは `git add -N` (intent-to-add) で
  tracking条件を検証済み。本commit時は通常の `git add` で内容をstageする。

## Packet B: experimental / value surface

目的: 課金価値を上げる composite API / artifact / source foundation 系の公開候補。
Packet A とは分ける。default-off で温存する場合は本番deployに不要。

候補:

- `src/jpintel_mcp/api/artifacts.py`
- `src/jpintel_mcp/api/_compact_envelope.py`
- `src/jpintel_mcp/api/_field_filter.py`
- `src/jpintel_mcp/api/audit_proof.py`
- `src/jpintel_mcp/api/calculator.py`
- `src/jpintel_mcp/api/eligibility_predicate.py`
- `src/jpintel_mcp/api/evidence_batch.py`
- `src/jpintel_mcp/api/intel*.py`
- `src/jpintel_mcp/api/narrative.py`
- `src/jpintel_mcp/api/wave24_endpoints.py`
- `src/jpintel_mcp/mcp/autonomath_tools/intel_wave31.py`
- `src/jpintel_mcp/mcp/autonomath_tools/wave24_tools_first_half.py`
- `src/jpintel_mcp/mcp/autonomath_tools/wave24_tools_second_half.py`
- `src/jpintel_mcp/billing/credit_pack.py`
- value / artifact / public-source tests and their schema/normalizer dependencies.
- `tests/test_distribution_manifest.py`
- `tests/test_funding_stack_checker.py`
- `tests/test_openapi_export.py`
- `tests/test_openapi_agent.py`

注意:

- Packet B は migration依存が広い。`172`-`176`, `wave24_17x`,
  artifact/source foundation/credit pack系を分離して review する。
- OpenAPI、site、SDK、DXT生成物は Packet B と同期させる。
- 本番flagは別承認。flag-on で clean checkout importが壊れないことを別途検証する。

## Packet C: docs / offline / generated

目的: 調査成果、運用メモ、public docs、offline inbox、generated site/SDKを整理する。
deploy blocker解消とは分ける。

候補:

- `docs/_internal/*` の計画書、handoff、監査メモ。
- `tools/offline/_inbox/*` の調査成果。
- `docs/openapi/*`, `site/*`, `sdk/*`, `dxt/*`, MCP registry submission。
- 新規 cron/workflow案のうち、本番 schedule をまだ有効化しないもの。

注意:

- generated public artifact は runtime/API と同期しないまま ship しない。
- offline / docs の大量変更で Packet A の安全修正を埋もれさせない。

## 次の自動作業順

1. Packet A と A2 の候補だけで diff / untracked dependency を再確認する。
2. `workflow_targets_git_tracked` が green になる最小 commit plan を作る。
3. Packet B/C を明示的に defer し、default-off / no-schedule を確認する。
4. `release_readiness`、`pre_deploy_verify`、`production_deploy_go_gate` を再実行する。
5. それでも残る `dirty_tree` と `operator_ack` は operator action として残す。
