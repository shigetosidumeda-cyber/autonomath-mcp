# AWS credit review 15: repo import and production deploy connection

作成日: 2026-05-15  
レビュー枠: AWSクレジット統合計画 追加20エージェントレビュー 15/20  
担当: AWS成果物のrepo取り込み、本体P0計画との順番統合、本番デプロイ接続  
AWS前提: profile `bookyou-recovery` / Account `993693061769` / default region `us-east-1`  
状態: 実装前レビューのみ。AWS CLI/API実行、AWSリソース作成、デプロイ実行、既存コード変更はしない。

## 0. 結論

AWS credit runで生成した `manifests`, `parquet/jsonl reports`, `packet fixtures`, `proof pages`, `OpenAPI/MCP examples` は、そのまま本番へ流してはいけない。

本番デプロイで苦戦しないための正しい順番は次で固定する。

1. 本体P0のpacket contract、source receipt contract、known gaps enum、billing metadata、CSV privacy boundaryを先に固定する。
2. AWSはCodex/Claude Codeのrate limitとは独立して、Batch/Step Functions相当の自走キューで成果物を作り続ける。
3. productionに必要な最小release candidate bundleを早めに切り出す。AWSクレジット消化全体の完了を本番デプロイの前提にしない。
4. AWS成果物はまずexport bundleとして受け、manifest/checksum/license/privacy/schemaを検証する。
5. repoへ入れるのは、検証済みの小さな本番入力だけにする。raw source lake、大量parquet、raw CSV、private overlay、AWS logはrepoにもproductionにも入れない。
6. stagingでAPI、Cloudflare Pages、MCP/OpenAPI、proof pages、GEO、billing/cost preview、no-hit semantics、private leak scanを通す。
7. productionは既存のdeploy gateに乗せる。`deploy.yml` のlegacy `autonomath-api` と `deploy-jpcite-api.yml` のparallel `jpcite-api` を混同しない。
8. productionがAWS S3やAWS computeへ依存しない形でdeployする。AWS終了後はzero-bill cleanupできる。

このレビューの主張は、「AWSで大規模に作る」と「早く本番へ出す」を分離すること。AWS全体が1-2週間走っても、最初の48-72時間で本番価値の高いbundleを切り出し、jpcite本体へ先に入れる。

## 1. 本体計画とAWS計画の統合順

AWS計画は本体P0計画を置き換えない。順番は本体P0が主、AWSが材料供給。

| 順 | フェーズ | 本体側 | AWS側 | deploy上の意味 |
|---:|---|---|---|---|
| 0 | Contract freeze | `jpcite.packet.v1`, known gaps, receipt schema, billing metadata, CSV boundary | J01/J12 smoke only | schema未確定の量産を禁止 |
| 1 | Guardrails | import validator, leak scan, release gatesを先に用意 | Budget Action, stopline, queue自走 | AWSがagent rate limitに依存せず走れる |
| 2 | RC1 source/packet seed | P0 packet composersのfixture入力を受ける | J01-J04, J12, J15最小 | stagingへ入れられる最初のbundle |
| 3 | RC1 repo import | fixtures, manifests, docs examples, proof source bundle | export bundleをfreeze | CIとstagingで検証 |
| 4 | Staging | `jpcite-api.fly.dev` or legacy staging path, Pages preview | AWSはstretch継続 | 本番deploy可否をAWS全体完了から切り離す |
| 5 | Production RC1 | API/Pages/MCP/OpenAPIをdeploy | AWSはJ17-J24継続可 | 価値を早く公開 |
| 6 | RC2/RC3 incremental | 追加source/profile/proof/GEOを小分けimport | stretch成果物 | 追い込み成果を追加release |
| 7 | AWS drain | production dependencyなし | export, checksum, cleanup | AWS zero-bill postureへ移行 |

## 2. AWSがrate limitなしで走り続ける前提

CodexやClaude Codeのrate limitが来てもAWS側が止まらない設計にする。ただし予算停止と安全停止は残す。

必須条件:

- AWS側のjob graphは、チャットagentの継続操作を待たない。
- 各jobは `run_manifest` と `job_status.jsonl` をS3へ追記し、再開可能にする。
- workerはidempotentにする。同じ `job_id` / `source_family` / `snapshot_id` を再実行しても成果物が重複しない。
- stopline到達時は、queue disable、new job reject、running job drain/cancel、export-onlyへ切り替える。
- production release candidateは `release_candidate=true` の小bundleとして早めに固定する。
- AWS全runの最終bundleを待たず、RC1をrepoへ入れる。

つまり「AWSは速く・大量に・自走」「本番deployは小さく・検証済み・早く」を同時に満たす。

## 3. Import bundle contract

AWSからrepoへ取り込む前に、export bundleをローカルの一時場所で検証する。

推奨bundle構造:

```text
aws_artifact_export/
  run_manifest.json
  cost_ledger.jsonl
  cleanup_manifest.json
  checksums/SHA256SUMS
  source_profiles/*.jsonl
  source_receipts/*.jsonl
  claim_refs/*.jsonl
  known_gaps/*.jsonl
  no_hit_checks/*.jsonl
  normalized_reports/*.parquet
  packet_fixtures/*.json
  proof_source_bundles/*.json
  openapi_examples/*.json
  mcp_examples/*.json
  geo_eval/*.jsonl
  qa_reports/*.md
```

`run_manifest.json` の必須項目:

| Field | Required | Rule |
|---|---:|---|
| `run_id` | yes | immutable |
| `aws_account_id` | yes | `993693061769` |
| `aws_profile_label` | yes | `bookyou-recovery` |
| `region` | yes | `us-east-1` unless approved |
| `started_at` / `ended_at` | yes | ISO timestamp |
| `artifact_schema_version` | yes | importer compatible |
| `corpus_snapshot_id` | yes | all packet/proof outputs reference it |
| `credit_stop_line_seen_usd` | yes | cost context |
| `source_families[]` | yes | no unknown source families |
| `private_data_present` | yes | must be false for repo import |
| `raw_csv_present` | yes | must be false |
| `request_time_llm_call_performed` | yes | must be false for production examples |
| `checksums[]` | yes | all imported files covered |
| `license_boundary_report` | yes | pass or review_required |
| `cleanup_status` | yes | production must not depend on active AWS infra |

Reject before import if:

- `private_data_present=true`.
- `raw_csv_present=true`.
- any path includes `raw`, `private`, `customer`, `debug`, `prompt`, `secret`, `authorization`, `cookie`, `stacktrace`, `token`.
- any public claim lacks `source_receipt_id` and is not moved to `known_gaps`.
- no-hit wording implies absence, safety, no risk, no issue, or definitive non-registration.
- packet/proof examples contain final tax/legal/accounting/credit/application judgment.
- bundle requires AWS S3 at runtime.

## 4. Repo import lanes

Large AWS artifacts stay outside repo unless they are small release evidence. Repo receives only product-facing, test-facing, and deploy-facing artifacts.

### 4.1 Import lane A: manifests and release evidence

Planned repo targets:

```text
data/aws_credit_2026_05/manifests/run_manifest.json
data/aws_credit_2026_05/manifests/artifact_manifest.json
data/aws_credit_2026_05/manifests/dataset_manifest.json
docs/_internal/aws_credit_release_evidence_2026-05-15.md
reports/aws_credit_2026_05/import_validation.json
```

Rules:

- Commit only compact manifests and validation reports.
- Do not commit full public source lake.
- Do not commit CloudWatch logs, raw crawler logs, raw CSV, private overlays, or unredacted exception traces.
- Every committed artifact must have checksum coverage.

### 4.2 Import lane B: source receipts / claims / gaps fixtures

Planned repo targets:

```text
tests/fixtures/aws_credit_2026_05/source_receipts_minimal.jsonl
tests/fixtures/aws_credit_2026_05/claim_refs_minimal.jsonl
tests/fixtures/aws_credit_2026_05/known_gaps_minimal.jsonl
tests/fixtures/aws_credit_2026_05/no_hit_checks_minimal.jsonl
```

Rules:

- Keep minimal representative fixtures, not complete datasets.
- Use source receipts to harden tests for `source_url`, `source_fetched_at`, `content_hash`, `license`, `used_in`, `corpus_snapshot_id`.
- Treat `source_receipt_missing_fields` as allowed only when explicit `known_gaps[]` exists.
- Test `no_hit_not_absence` across invoice, enforcement, sanctions/notices, procurement, and company joins.

### 4.3 Import lane C: packet fixtures

Planned repo targets:

```text
data/packet_examples/evidence_answer.json
data/packet_examples/company_public_baseline.json
data/packet_examples/application_strategy.json
data/packet_examples/source_receipt_ledger.json
data/packet_examples/client_monthly_review.json
data/packet_examples/agent_routing_decision.json
tests/fixtures/packet_examples/*.json
```

Rules:

- All six P0 packets use `schema_version=jpcite.packet.v1`.
- `request_time_llm_call_performed=false` is mandatory.
- `billing_metadata` is mandatory.
- `agent_guidance.must_preserve_fields` must include `source_url`, `source_fetched_at`, `source_receipts`, `known_gaps`, `human_review_required`, `_disclaimer`.
- `client_monthly_review` can use only synthetic or aggregate CSV-derived information.
- Public examples must say they are examples, not actual customer output.

### 4.4 Import lane D: proof pages and public packet pages

Planned repo targets:

```text
site/packets/*.html
site/proof/examples/**/*.html
site/data/packet_examples/*.json
docs/packets/*.md
docs/integrations/token-efficiency-proof.md
```

Rules:

- Generate from packet fixture JSON, not hand-written divergent examples.
- Public proof page means claim-to-receipt mapping passed display checks. It does not mean the business conclusion is verified.
- Tenant/private proof pages are not static public pages.
- JSON-LD must not include raw output, raw CSV, private identifiers, auth data, logs, or source full text.
- Run private leak scan before committing generated public pages.

### 4.5 Import lane E: OpenAPI and MCP examples

Planned repo targets already exist and must remain synchronized:

```text
docs/openapi/v1.json
site/docs/openapi/v1.json
docs/openapi/agent.json
site/openapi.agent.json
site/docs/openapi/agent.json
site/openapi.agent.gpt30.json
mcp-server.core.json
mcp-server.composition.json
mcp-server.full.json
server.json
site/.well-known/agents.json
site/.well-known/mcp.json
site/.well-known/openapi-discovery.json
site/.well-known/llms.json
site/llms.txt
site/llms-full.txt
docs/mcp-tools.md
docs/api-reference.md
```

Rules:

- OpenAPI examples must be generated from actual API models/routes, not copied from AWS outputs.
- AWS can supply example payloads only after schema validation.
- MCP tool examples must match actual tool names and arguments.
- Tool/route counts are allowed to change only with a distribution manifest update.
- Public docs must stay GEO-first: teach agents when to call jpcite and when not to call it.

### 4.6 Import lane F: production seed or database materialization

AWS may produce normalized facts, but production must not read AWS directly.

Safe path:

1. Convert accepted normalized facts into a local staging SQLite copy or existing ingest input format.
2. Run source receipt and known gap validators.
3. Produce a deterministic DB snapshot or R2-compatible seed artifact.
4. Deploy through existing Fly/R2 seed path.
5. Keep AWS as a build-time/export-time accelerator only, not runtime dependency.

Rules:

- Do not mutate production DB directly from AWS.
- Do not let AWS jobs write to Fly volume.
- Do not let production startup fetch AWS S3 artifacts.
- If a DB snapshot is used, the deploy gate must record snapshot id, checksum, table counts, and rollback path.

## 5. Tests and CI gates

Before staging, run focused local gates:

```text
uv run ruff check src/jpintel_mcp tests scripts/ops scripts/ingest tools/offline --select F,E9,B006,B008,B017,B018,B020,B904
uv run pytest tests/test_evidence_packet.py tests/test_evidence_packet_refs.py tests/test_evidence_batch.py
uv run pytest tests/test_artifact_evidence_contract.py tests/test_artifacts_company_public_packs.py tests/test_artifacts_application_strategy_pack.py tests/test_artifacts_houjin_dd_pack.py
uv run pytest tests/test_source_manifest.py tests/test_source_fetched_at_semantic_honesty.py tests/test_public_source_foundation_normalizer.py
uv run pytest tests/test_openapi_export.py tests/test_openapi_agent.py tests/test_openapi_response_models.py tests/test_mcp_public_manifest_sync.py tests/test_mcp_manifest_deep_diff.py
uv run pytest tests/test_cost_preview.py tests/test_billing.py tests/test_credit_pack.py
uv run pytest tests/test_pre_deploy_verify.py tests/test_production_deploy_go_gate.py tests/test_post_deploy_smoke.py
uv run python scripts/export_openapi.py --out docs/openapi/v1.json --site-out site/docs/openapi/v1.json
uv run python scripts/export_agent_openapi.py
uv run python scripts/check_openapi_drift.py
uv run python scripts/check_mcp_drift.py
uv run python scripts/ops/release_readiness.py
uv run python scripts/ops/pre_deploy_verify.py
uv run python scripts/ops/production_deploy_go_gate.py --warn-only
```

Needed new focused tests before production:

| Test | Purpose |
|---|---|
| `test_aws_artifact_bundle_manifest.py` | run/artifact/dataset manifest required fields |
| `test_aws_artifact_no_private_leak.py` | path/content denylist and raw CSV rejection |
| `test_packet_examples_contract.py` | six P0 examples match `jpcite.packet.v1` |
| `test_packet_examples_no_request_time_llm.py` | no request-time LLM flag invariant |
| `test_no_hit_not_absence_copy.py` | no-hit wording never means safe/absence |
| `test_public_proof_pages_from_fixtures.py` | proof pages generated from fixtures only |
| `test_public_pages_no_private_overlay.py` | CSV/private overlay never leaks |
| `test_openapi_mcp_examples_match_catalog.py` | examples align with route/tool catalog |
| `test_geo_discovery_surfaces.py` | llms/.well-known/agent pages mention correct first call |

CI workflows to rely on:

- `.github/workflows/test.yml`
- `.github/workflows/release-readiness-ci.yml`
- `.github/workflows/openapi.yml`
- `.github/workflows/geo_eval.yml` via dispatch before production cutover
- `.github/workflows/pages-preview.yml` for public page preview
- `.github/workflows/pages-deploy-main.yml` after merge to main
- `.github/workflows/deploy-jpcite-api.yml` for parallel `jpcite-api` deploy
- `.github/workflows/deploy.yml` only when intentionally deploying legacy `autonomath-api`

## 6. Staging sequence

Staging should prove the entire path without relying on AWS.

### 6.1 API staging

Preferred staging path:

1. Import RC1 bundle into a feature branch.
2. Run local tests and release readiness.
3. Push branch and wait for PR CI.
4. Use `deploy-jpcite-api.yml` dispatch with exact `expected_sha` and default `smoke_base_url=https://jpcite-api.fly.dev`.
5. Keep `api.jpcite.com` DNS unchanged until explicit cutover.

Why: `deploy-jpcite-api.yml` is dispatch-only and targets the new app. It avoids accidentally mutating the legacy production path.

If using existing production app path instead:

- Treat `deploy.yml` as production SOT for `autonomath-api`.
- Do not edit legacy production deploy workflow as part of artifact import unless the change itself is a reviewed deploy-gate change.
- Use exact SHA and operator ACK.

### 6.2 Pages staging

Use Pages preview for:

- `site/packets/*`
- `site/proof/examples/*`
- `site/.well-known/*`
- `site/llms*.txt`
- `site/openapi.agent*.json`
- docs/API reference updates

Preview checks:

- generated pages render without broken HTML.
- packet examples are linked from docs and discovery surfaces.
- JSON-LD validates structurally.
- no private/raw CSV strings appear.
- `noindex` is used where a proof page is not meant for public indexing.
- `llms.txt` and `.well-known` send agents to MCP/API/cost preview, not to a sales-only story.

### 6.3 Staging smoke

Required smoke surfaces:

| Surface | Smoke |
|---|---|
| API health | `/healthz`, `/v1/meta`, deep health where available |
| Packet API | evidence packet, company public baseline, application strategy, source receipt ledger |
| Cost preview | broad/batch/CSV-like request rejects or previews before billable fanout |
| Billing | idempotency, cap exceeded before billable work, no usage on failed output |
| MCP | tool list, first-call tool, packet tool output shape |
| OpenAPI | committed schema equals generated schema |
| Proof pages | example pages return 200 and contain receipt/gap sections |
| GEO | agent discovery pages recommend correct first calls |
| Privacy | raw CSV/private overlay leak scan pass |
| no-hit | no-hit copy is caveated |

## 7. Production sequence

Production sequence should be boring and explicit.

1. Merge only after CI green and staging smoke green.
2. Choose deployment target:
   - If keeping current prod app: use `deploy.yml` to `autonomath-api`.
   - If cutting over new app: use `deploy-jpcite-api.yml` first, then DNS cutover only after explicit operator approval.
3. Ensure `PRODUCTION_DEPLOY_OPERATOR_ACK_YAML` is prepared outside repo and matches current dirty/clean state.
4. Run `production_deploy_go_gate.py` final gate.
5. Deploy API by exact SHA.
6. Deploy Cloudflare Pages through `pages-deploy-main.yml`.
7. Run post-deploy smoke.
8. Watch logs, billing, Stripe usage, API errors, and packet/proof endpoints.
9. Keep rollback image and DB snapshot reference until post-deploy monitoring window closes.
10. Confirm production does not call AWS S3/Batch/OpenSearch/Glue/Athena.

Post-deploy smoke:

```text
https://api.jpcite.com/healthz
https://api.jpcite.com/v1/meta
https://api.jpcite.com/v1/programs/search?q=補助金
POST /v1/evidence/packets/query
POST /v1/artifacts/company_public_baseline
POST /v1/cost/preview
https://jpcite.com/llms.txt
https://jpcite.com/.well-known/mcp.json
https://jpcite.com/.well-known/openapi-discovery.json
https://jpcite.com/packets/
https://jpcite.com/proof/examples/
```

## 8. Fast deployment lane vs credit consumption lane

To satisfy both "use credit fast" and "deploy production fast", use two lanes.

### Fast deployment lane: RC1

Target: first 48-72 hours.

Include:

- J01/J12 source profile and receipt completeness smoke
- J02/J03/J04 small official-source receipt sets
- J15 six P0 packet fixtures
- J16 forbidden-claim/no-hit/privacy smoke
- OpenAPI/MCP examples for P0 packets
- minimal proof pages
- import validation report

Do not wait for:

- all local government OCR
- all stretch Bedrock/OpenSearch runs
- full GEO adversarial eval
- huge parquet compaction
- final source lake completion

### Credit consumption lane: RC2/RC3/stretch

Target: keep AWS moving until stoplines.

Include:

- wider local-government PDF OCR
- more source profile coverage
- more proof examples
- broader GEO eval
- retrieval benchmark
- source conflict analysis
- compaction/QA reruns

Import only after each bundle independently passes validation.

This prevents the common failure mode: "we spent the credit, but production deploy is blocked by an enormous unreviewed artifact pile."

## 9. Rollback and zero AWS dependency

Production rollback must be possible without AWS.

Rollback requirements:

- Previous Fly image tag/release id known.
- DB snapshot/checksum known if DB materialization changed.
- Cloudflare Pages previous deployment available.
- OpenAPI/MCP previous manifest available in git history.
- Packet fixture changes are revertible by git.
- No production route depends on AWS S3 URLs.

AWS cleanup can happen after export/import verification, but production should not wait on AWS except for artifacts already exported.

Before declaring AWS run complete:

- final artifacts copied away from AWS or intentionally preserved only with explicit ongoing-bill acceptance.
- S3 buckets deleted if zero ongoing AWS bill is mandatory.
- ECR repos/images deleted.
- Batch queues/compute environments disabled/deleted.
- EC2/ECS/Fargate/OpenSearch/Glue/Athena/CloudWatch/Step Functions/Lambda resources deleted.
- final `cleanup_manifest.json` retained outside AWS.
- Cost Explorer/billing checked for unexpected untagged spend.

## 10. Main risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| AWS artifact schema drifts from P0 contract | deploy blocked late | freeze contract first; validator before import |
| Huge parquet/source lake committed | repo/deploy pain | only commit compact manifests/fixtures |
| raw/private CSV leakage | critical trust failure | raw CSV forbidden in AWS export; leak scan gates |
| no-hit becomes "safe/no issue" | hallucination/legal risk | `no_hit_not_absence` tests and copy scan |
| OpenAPI/MCP examples diverge from routes/tools | agents recommend broken calls | generate specs from code; examples validate against spec |
| proof pages overclaim verified status | user misled | proof means claim-to-receipt mapping only |
| production depends on AWS after credits expire | surprise bill/outage | export-only, no runtime AWS dependency |
| deploy waits for full AWS credit run | launch delay | RC1 fast lane separate from stretch lane |
| legacy `autonomath-api` and new `jpcite-api` confused | wrong app deploy | exact workflow choice and target app gate |
| dirty tree blocks deploy | deployment stall | import in small reviewed lanes; use operator ACK only if necessary |

## 11. Recommended immediate implementation order

When implementation begins, do this in order:

1. Add artifact bundle schema and import validator.
2. Add tests for manifest, private leak, packet fixture contract, no-hit copy, and OpenAPI/MCP example alignment.
3. Freeze six P0 packet example shapes under `data/packet_examples/`.
4. Add generator for public packet/proof pages from fixtures.
5. Add docs/OpenAPI/MCP example generation hook.
6. Run local focused test suite.
7. Import RC1 AWS bundle only.
8. Run full CI and Pages preview.
9. Deploy `jpcite-api` staging by exact SHA.
10. Run staging smoke and GEO discovery smoke.
11. Decide production target: legacy `autonomath-api` or explicit `jpcite-api` cutover.
12. Deploy production by existing gate.
13. Continue importing RC2/RC3 as separate, smaller releases.
14. Complete AWS zero-bill cleanup after export and final artifacts are preserved outside AWS.

## 12. Review verdict

GO for planning.

NO-GO for direct production import.

The deploy-safe plan is to use AWS as a high-speed artifact factory, not as production infrastructure. The first production release should be a small, validated RC1 bundle connected to the existing jpcite P0 contract and deploy gates. Larger AWS-generated outputs should arrive in later reviewed releases, while AWS continues running independently until stoplines and then is fully cleaned up.
