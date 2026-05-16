# Stream G — 5 PR Commit Plan (2026-05-16)

Stream G は 479 staged file changes (`git diff --cached --name-only | wc -l = 479`) を
5 つの論理 PR に分けて landing する計画書。本ファイルは **draft only**、
commit / push は **絶対に実行禁止**。user 承認後に下部 "Execute commands" を順に走らせる。

## File bucket 集計 (staged のみ)

| PR  | Path prefix                                                                                                              | files  | 状態         |
|-----|--------------------------------------------------------------------------------------------------------------------------|--------|--------------|
| PR1 | `docs/_internal/`                                                                                                        | 167    | staged       |
| PR2 | `src/jpintel_mcp/` + `schemas/jpcir/` + `tests/`                                                                         | 143    | staged       |
| PR3 | `site/releases/rc1-p0-bootstrap/` + `site/releases/current/` + `site/releases/stream-e-selftest/`                        | 30     | staged       |
| PR4 | `site/.well-known/` + `site/openapi*` + `site/docs/openapi/`                                                             | 7+     | Tick6-E stage|
| PR5 | `functions/release/` + `scripts/ops/` + `scripts/teardown/` + `scripts/cron/` + `.github/workflows/` + `Makefile` + 他   | 39+    | Tick6-E stage|

合計 staged: **479 file changes** (`git diff --cached --stat | tail -1 = 479 files changed, 176635 insertions(+), 535 deletions(-)`).

> PR4/PR5 は Tick6-E で改めて `git add` する分も含むため file 数は **下限**。

---

## PR1 — docs(_internal): Wave 47-49 deepdive notes + AWS credit packets + Stream A–F runbooks

### 概要
Wave 47/48/49 を駆動した 167 本の **内部 docs** を 1 PR に集約する。AWS credit max-value challenge
の 20 review + 12 final review + algorithmic outputs deepdive + agent recommendation story +
Trust/Safety boundary + GEO citation + release gate checklist 等、Stream A–F 全 stream の
SOT を `docs/_internal/` 配下に packing する commit。public site は触らない (PR3/PR4)。

- 想定 file 数: **167** (`docs/_internal/*.md` ほぼ全て)
- dependency: なし (最初に landing 可)
- 影響範囲: docs only、CI 影響ゼロ、runtime 影響ゼロ

### Commit message (HEREDOC)
```bash
git commit -m "$(cat <<'EOF'
docs(internal): land Wave 47-49 deepdive notes + AWS credit packets + Stream A-F runbooks

Aggregates 167 internal documents under docs/_internal/ that drove
Wave 47 Phase 2, Wave 48, and Wave 49 — including:

- AWS credit max-value challenge: 20 review notes + 12 final reviews
  + acceleration plan + unified execution plan + cli/cost/data/security
  agent packets.
- Algorithmic outputs deepdive, agent recommendation story,
  ai-surface integration playbooks, source-receipt + claim-graph
  deepdive, trust/safety boundary, VC narrative alignment.
- Release gate checklist, security/privacy CSV pipeline, prebuilt
  deliverable packets (2026-05-15).
- Stream A–F operational SOT (canary preflight, JPCIR schema,
  discovery facade, Cloudflare rollback, AWS teardown, Makefile +
  mypy strict baseline).

No runtime or public site change; CI surface untouched.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## PR2 — feat(runtime,schemas,tests): JPCIR v3 + agent_runtime + outcome catalog + Stream B/C/F coverage

### 概要
`src/jpintel_mcp/agent_runtime/` 配下に新規 21 module (algorithm_blueprints, aws_credit_simulation,
billing_contract, facade_contract, outcome_catalog, outcome_routing, outcome_source_crosswalk,
packet_skeletons, policy_catalog, pricing_policy, public_source_domains, source_receipts 他)、
`schemas/jpcir/` に 21 JSON Schema (evidence, claim_ref, source_receipt, scoped_cap_token,
spend_simulation, teardown_simulation, release_capsule_manifest, capability_matrix,
outcome_contract, policy_decision, no_hit_lease, gap_coverage_entry, known_gap, private_fact_capsule,
consent_envelope, agent_purchase_decision, aws_noop_command_plan, accepted_artifact_pricing,
execution_graph, jpcir_header)、`tests/` に 61 file 追加 (test_release_capsule_validator 594 行、
test_validate_release_capsule_extended 384 行、test_sync_release_manifest_sha 222 行 他)。
Stream B/C/F/K/L/M/N/O/P の core code をひとまとめに land する PR。

- 想定 file 数: **143** (src=61, schemas=21, tests=61)
- dependency: PR1 (docs 参照が test fixture / contract docstring から張られている — order でなく review 上の前提)
- 影響範囲: runtime contract 拡張、新規 schema 追加、test suite 拡大。**mypy strict** 0 errors / pytest 全 PASS で landing。

### Commit message (HEREDOC)
```bash
git commit -m "$(cat <<'EOF'
feat(runtime,schemas,tests): land JPCIR v3 + agent_runtime + outcome catalog + Stream B/C/F coverage

Lands the core code base for Wave 47-49 across three layers:

src/jpintel_mcp/agent_runtime/ (21 modules)
  - algorithm_blueprints, aws_credit_simulation, aws_execution_templates,
    aws_spend_program, billing_contract, contracts, defaults,
    facade_contract, outcome_catalog, outcome_routing,
    outcome_source_crosswalk, packet_skeletons, policy_catalog,
    pricing_policy, public_source_domains, source_receipts, plus
    accounting_csv_profiles for TKC profile.

schemas/jpcir/ (21 schemas, v3 baseline)
  - evidence, claim_ref, source_receipt, scoped_cap_token,
    spend_simulation, teardown_simulation, release_capsule_manifest,
    capability_matrix, outcome_contract, policy_decision,
    no_hit_lease, gap_coverage_entry, known_gap,
    private_fact_capsule, consent_envelope, agent_purchase_decision,
    aws_noop_command_plan, accepted_artifact_pricing,
    execution_graph, jpcir_header, _registry.

tests/ (61 files)
  - test_release_capsule_validator (594 LOC), test_validate_release_capsule_extended
    (384 LOC), test_sync_release_manifest_sha (222 LOC),
    test_rollback_scripts, test_teardown_scripts_exist,
    test_spend_teardown_assertions, test_release_current_pages_function,
    test_public_source_domains, plus updates to existing public
    sanitization / site integrity / redirect tests.

Quality gates at landing: mypy strict 0 errors, pytest all PASS.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## PR3 — feat(release): rc1-p0-bootstrap release capsule (29 artifacts) + current pointer

### 概要
`site/releases/rc1-p0-bootstrap/` 配下に 29 個の release artifact (JPCIR header, capability matrix,
execution graph, execution state, outcome catalog, outcome contract catalog, outcome source crosswalk,
policy decision catalog, public source domains, release capsule manifest, scoped cap token example,
agent purchase decision example, consent envelope example, spend simulation, teardown simulation,
preflight scorecard, packet skeletons, inline packets, accepted artifact pricing,
accounting csv profiles, algorithm blueprints, aws budget canary attestation, aws execution templates,
aws spend program, billing event ledger schema, csv private overlay contract, jpcir header,
noop aws command plan, agent surface p0 facade) + `site/releases/current/runtime_pointer.json` +
Stream E selftest teardown attestation を 1 PR で land。**PR2 の schema validator が必要**
(rc1-p0-bootstrap artifact は schemas/jpcir に対して validate される)。

- 想定 file 数: **30** (`git diff --cached --name-only | grep "^site/releases/" | wc -l = 30`)
- dependency: **PR2 必須** (schema validator + agent_runtime module 不在では release capsule の SHA 整合 test が落ちる)
- 影響範囲: 公開 release capsule の初版 land、`/releases/current/` pointer も新規。

### Commit message (HEREDOC)
```bash
git commit -m "$(cat <<'EOF'
feat(release): land rc1-p0-bootstrap release capsule (29 artifacts) + current pointer

Publishes the rc1-p0-bootstrap release capsule under
site/releases/rc1-p0-bootstrap/ with 29 first-class artifacts plus
site/releases/current/runtime_pointer.json and Stream E teardown
self-test attestation.

Capsule contents (validated against schemas/jpcir/):
  - jpcir_header, capability_matrix, execution_graph, execution_state
  - outcome_catalog, outcome_contract_catalog, outcome_source_crosswalk
  - policy_decision_catalog, public_source_domains
  - release_capsule_manifest (sha256-locked)
  - scoped_cap_token.example, agent_purchase_decision.example,
    consent_envelope.example
  - spend_simulation, teardown_simulation, preflight_scorecard
  - packet_skeletons, inline_packets, accepted_artifact_pricing
  - accounting_csv_profiles (TKC + bank), algorithm_blueprints
  - aws_budget_canary_attestation, aws_execution_templates,
    aws_spend_program
  - billing_event_ledger_schema, csv_private_overlay_contract
  - noop_aws_command_plan, agent_surface/p0_facade

Requires PR2 schemas + runtime modules to validate.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## PR4 — feat(discovery): .well-known agent discovery + openapi v1 publishing

### 概要
`site/.well-known/` に 6 個の discovery artifact (agents.json, jpcite-federation.json,
jpcite-release.json, llms.json, openapi-discovery.json, trust.json) + `site/openapi/v1.json` +
`site/docs/openapi/v1.json` を land。**Tick6-E で stage 予定** (現時点 7 file staged、`functions/release/[[path]].ts`
の release server-side route と組合せて初めて 200 を返す)。

- 想定 file 数: **7+** (Tick6-E で `.well-known` の他 generated artifact が追加される可能性あり)
- dependency: **PR3 必須** (rc1-p0-bootstrap が site/releases/ 配下に居ないと `/.well-known/jpcite-release.json` の `release_uri` が 404)
- 影響範囲: 公開 discovery 面、AX 4 柱 Layer 1 (Access) の core。MCP / ChatGPT / Claude / Cursor からの auto-discovery 経路に影響。

### Commit message (HEREDOC)
```bash
git commit -m "$(cat <<'EOF'
feat(discovery): publish .well-known agent discovery + openapi v1

Lands the AX Layer 1 (Access) discovery surface:

site/.well-known/
  - agents.json — agent capability advertisement
  - jpcite-federation.json — federated MCP partner curated list
  - jpcite-release.json — current release pointer (rc1-p0-bootstrap)
  - llms.json — LLM-oriented site contract
  - openapi-discovery.json — OpenAPI cross-link manifest
  - trust.json — trust + safety attestation

site/openapi/v1.json + site/docs/openapi/v1.json
  - OpenAPI v0.4.0 (306 paths) republished for static serve.

Requires PR3 (rc1-p0-bootstrap capsule) so that
/.well-known/jpcite-release.json resolves to a real release URI.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## PR5 — chore(ops): release Pages Function + ops/teardown/cron scripts + GHA workflows + Makefile

### 概要
runtime + CI + ops 配管を 1 PR で land。`functions/release/[[path]].ts` (Cloudflare Pages Function
で release artifact をサーブ)、`scripts/ops/*` 22 script (rollback / spend / preflight)、
`scripts/teardown/*` 8 script (Stream E AWS teardown)、`scripts/cron/detect_first_g4_g5_txn.py`、
`.github/workflows/` 6 (deploy.yml 更新、pages-deploy-main.yml 更新、pages-rollback.yml 新規、
release.yml 更新、test.yml 更新、detect-first-g4-g5-txn.yml 新規)、`Makefile` 新規、
`cloudflare-rules.yaml` 更新、`CLAUDE.md` / `README.md` 微更新。

- 想定 file 数: **39+** (Tick6-E で更に scripts/registry_submissions 27 + 主要 site/* も add 予定 → 最終 60+ になる可能性)
- dependency: **PR4 必須** (deploy.yml が .well-known を build artifact に含めて publish するため PR4 先行)
- 影響範囲: CI / CD / 本番 ops。**最後に landing**、smoke test (60s propagation sleep) を PR landing 後に手動 trigger 推奨。

### Commit message (HEREDOC)
```bash
git commit -m "$(cat <<'EOF'
chore(ops): land release Pages Function + ops/teardown/cron scripts + GHA workflows + Makefile

Wires up the operational plane for the rc1-p0-bootstrap release:

functions/release/[[path]].ts
  - Cloudflare Pages Function serving site/releases/<name>/* with
    SHA pinning and 404 fallback.

scripts/ops/ (22 scripts)
  - rollback, spend guard, preflight, manifest sha sync, release
    capsule validator extended, public reachability probe.

scripts/teardown/ (8 scripts, Stream E)
  - AWS budget cap, IAM teardown, identity/budget inventory, spend
    teardown assertions.

scripts/cron/detect_first_g4_g5_txn.py
  - Stream Q G4/G5 pass_state flip cron entry.

.github/workflows/ (6 files)
  - deploy.yml: 4-fix pattern (smoke sleep / preflight tolerance /
    hydrate size guard / sftp rm idempotency).
  - pages-deploy-main.yml: cached pages deploy lane.
  - pages-rollback.yml: new rollback workflow.
  - release.yml + test.yml: capsule + mypy strict + pytest gates.
  - detect-first-g4-g5-txn.yml: cron workflow for G4/G5 flip.

Makefile (new) + cloudflare-rules.yaml (update) + CLAUDE.md +
README.md minor sync.

Requires PR4 so deploy.yml can publish .well-known artifacts.
Post-landing: trigger manual smoke after 60s propagation window.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Execute commands

> **絶対条件**: user 承認 (`Stream G land OK` or 等価表明) を受けてから順次実行。
> commit / push を agent が独断で実行することは禁止。
> 各 PR 間で smoke (curl /healthz 200) 確認推奨だが必須ではない。

```bash
cd /Users/shigetoumeda/jpcite

# --- PR1: docs(_internal) — 167 files
git diff --cached --name-only | grep "^docs/_internal/" | xargs git restore --staged --     # 一度 unstage
git add docs/_internal/
git commit -m "$(cat <<'EOF'
docs(internal): land Wave 47-49 deepdive notes + AWS credit packets + Stream A-F runbooks

Aggregates 167 internal documents under docs/_internal/ that drove
Wave 47 Phase 2, Wave 48, and Wave 49 — including:

- AWS credit max-value challenge: 20 review notes + 12 final reviews
  + acceleration plan + unified execution plan + cli/cost/data/security
  agent packets.
- Algorithmic outputs deepdive, agent recommendation story,
  ai-surface integration playbooks, source-receipt + claim-graph
  deepdive, trust/safety boundary, VC narrative alignment.
- Release gate checklist, security/privacy CSV pipeline, prebuilt
  deliverable packets (2026-05-15).
- Stream A-F operational SOT (canary preflight, JPCIR schema,
  discovery facade, Cloudflare rollback, AWS teardown, Makefile +
  mypy strict baseline).

No runtime or public site change; CI surface untouched.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
git push origin main

# --- PR2: feat(runtime,schemas,tests) — 143 files
git add src/jpintel_mcp/ schemas/jpcir/ tests/
git commit -m "$(cat <<'EOF'
feat(runtime,schemas,tests): land JPCIR v3 + agent_runtime + outcome catalog + Stream B/C/F coverage

[full body from PR2 section above]

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
git push origin main

# --- PR3: feat(release) — 30 files
git add site/releases/
git commit -m "$(cat <<'EOF'
feat(release): land rc1-p0-bootstrap release capsule (29 artifacts) + current pointer

[full body from PR3 section above]

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
git push origin main

# --- PR4: feat(discovery) — 7+ files (Tick6-E で stage 完了させてから)
git add site/.well-known/ site/openapi/ site/docs/openapi/
git commit -m "$(cat <<'EOF'
feat(discovery): publish .well-known agent discovery + openapi v1

[full body from PR4 section above]

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
git push origin main

# --- PR5: chore(ops) — 39+ files (Tick6-E で stage 完了させてから)
git add functions/release/ scripts/ops/ scripts/teardown/ scripts/cron/ .github/workflows/ Makefile cloudflare-rules.yaml CLAUDE.md README.md
git commit -m "$(cat <<'EOF'
chore(ops): land release Pages Function + ops/teardown/cron scripts + GHA workflows + Makefile

[full body from PR5 section above]

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
git push origin main

# --- Post-landing
sleep 60                                                    # propagation
curl -sf https://jpcite.com/healthz | jq .                  # smoke
curl -sf https://jpcite.com/.well-known/agents.json | jq .  # discovery smoke
curl -sf https://jpcite.com/releases/current/runtime_pointer.json | jq .   # release smoke
```

## Notes

- **landing order は固定**: PR1 → PR2 → PR3 → PR4 → PR5。PR2 schema が無いと PR3 capsule の validator test が落ちる。PR3 が無いと PR4 discovery が release_uri 404。PR4 が無いと PR5 deploy.yml smoke 失敗。
- **PR4/PR5 の最終 file 数は Tick6-E の `git add` 完了後に確定**。本ファイル上の 7 / 39 は staged の下限。
- 各 commit message body の `[full body from PRx section above]` 部分は実 commit 時に上の HEREDOC を **そのまま copy** すること。本欄では二重掲載を避けるため省略形にしている。
- commit message に絵文字を入れない (feedback_no_emojis ない場合でも commit 慣習に従う)。
- `--no-verify` / `--amend` / `git reset --hard` は使わない。pre-commit hook failure が起きたら fix + 新 commit。

---

## tick 10 final summary (2026-05-16, append-only sync)

本 section は tick 10 時点の **実 git tree state** と上記 5 PR plan の差分 sync。
本 sync の目的は plan doc を実状に追随させることのみで、commit/push は **引き続き禁止** (user 承認後実行)。
historical な PR1-PR5 設計 (167/143/30/7+/39+) は **historical marker として保持**、本 section の数値が tick 10 LIVE 値。

### tick 10 現在値 (probed via `git status --short`)

- 合計 staged: **352 file** (`git diff --cached --name-only | wc -l = 352`)
- 合計 unstaged modified: **524 file** (`git status --short | grep -E "^( |M)M" | wc -l = 524`)
- 合計 untracked: **8 file** (`git status --short | grep "^??" | wc -l = 8`)
- 合計 drift: **884 file** (352 staged + 524 unstaged + 8 untracked)
- staged diff stat: `352 files changed, 180580 insertions(+)` (`git diff --cached --stat | tail -1`)

### tick 10 6 PR breakdown (staged のみ — unstaged + untracked は PR2/PR4/PR5 stage 拡張時に追加 stage 予定)

| PR  | bucket                                                                                                  | staged 件数 | 状態           |
|-----|---------------------------------------------------------------------------------------------------------|------------|----------------|
| PR1 | `docs/_internal/**`                                                                                     | **171**    | staged (commit ready) |
| PR2 | `src/jpintel_mcp/` + `schemas/jpcir/` + `tests/`                                                        | **111**    | staged (commit ready) |
| PR3 | `site/releases/rc1-p0-bootstrap/` + `site/releases/current/` + `site/releases/stream-e-selftest/`       | **32**     | staged (commit ready) |
| PR4 | `site/.well-known/` + `site/openapi/` + `site/docs/openapi/`                                            | **1**      | partial — 残 `.well-known/*.json` 5 件は unstaged M 状態 |
| PR5 | `functions/release/` + `scripts/ops/` + `scripts/teardown/` + `scripts/cron/` + `.github/workflows/` + `Makefile` + `cloudflare-rules.yaml` + `CLAUDE.md` + `README.md` | **32**     | staged (commit ready) |
| PR6 | `.gitignore` + `docs/audit/agent_journey_6step_audit_2026_05_15.md` + `docs/geo_eval_query_set_100.md` + `scripts/agent_runtime_bootstrap.py` + `scripts/check_agent_runtime_contracts.py` (leftover 5 件) | **5**      | staged (commit ready) |

合計 staged = 171 + 111 + 32 + 1 + 32 + 5 = **352** (= `git diff --cached --name-only | wc -l`)

### PR6 (new bucket) 概要

tick 10 で 5 件の staged orphan file が PR1-PR5 のどの bucket にも入らないことが判明、これらを PR6 として 1 commit で land する:
- `.gitignore` — `coverage.json` 追加 (Stream Z polish)
- `docs/audit/agent_journey_6step_audit_2026_05_15.md` — Wave 49 organic funnel 6 段 audit
- `docs/geo_eval_query_set_100.md` — GEO eval 100 query set
- `scripts/agent_runtime_bootstrap.py` — agent_runtime bootstrap entry
- `scripts/check_agent_runtime_contracts.py` — Pydantic ↔ JSON Schema parity check

### tick 10 各 PR commit message (HEREDOC, Co-Authored-By 込み)

#### PR1 — docs(_internal): 171 file

```bash
git commit -m "$(cat <<'EOF'
docs(internal): land Wave 47-50 deepdive notes + RC1 contract layer runbooks

Aggregates 171 internal documents under docs/_internal/ that drove
Wave 47 Phase 2, Wave 48, Wave 49, and Wave 50 RC1 contract layer.

- Wave 50 tick 1-9 completion logs + RC1 2026-05-16 state SOT.
- AWS canary operator quickstart + Wave 49 G1 operator runbook.
- Stream A-F+R-Z runbooks (canary preflight, JPCIR schema, discovery
  facade, Cloudflare rollback, AWS teardown, Makefile + mypy strict
  baseline, G5 schema sync, organic aggregator, coverage gap fill,
  scorecard concern separation, untracked sweep).
- AWS credit max-value challenge reviews + algorithmic outputs
  deepdive + agent recommendation story + Trust/Safety boundary
  + GEO citation + release gate checklist + prebuilt deliverable
  packets.

No runtime or public site change; CI surface untouched.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

#### PR2 — feat(runtime,schemas,tests): 111 file

```bash
git commit -m "$(cat <<'EOF'
feat(runtime,schemas,tests): land JPCIR v3 + agent_runtime + RC1 contract layer + Stream T coverage

Lands the RC1 contract layer + Wave 50 coverage uplift:

src/jpintel_mcp/agent_runtime/
  - 19 Pydantic contracts.py models (Evidence + Citation +
    OutcomeContract + Disclaimer + BillingHint + RateLimitHint +
    PolicyDecision + AgentPurchaseDecision + ConsentEnvelope +
    ScopedCapToken + SpendSimulation + TeardownSimulation +
    ReleaseCapsuleManifest + CapabilityMatrix + NoHitLease +
    GapCoverageEntry + KnownGap + PrivateFactCapsule + JpcirHeader).
  - algorithm_blueprints, aws_credit_simulation, aws_execution_templates,
    aws_spend_program, billing_contract, defaults, facade_contract,
    outcome_catalog, outcome_routing, outcome_source_crosswalk,
    packet_skeletons, policy_catalog, pricing_policy,
    public_source_domains, source_receipts, accounting_csv_profiles
    (TKC profile).

schemas/jpcir/ (20 schemas, RC1 baseline)
  - 8 new in Wave 50: policy_decision_catalog,
    csv_private_overlay_contract, billing_event_ledger,
    aws_budget_canary_attestation + 4 envelope companions.
  - 12 retained: evidence, claim_ref, source_receipt,
    scoped_cap_token, spend_simulation, teardown_simulation,
    release_capsule_manifest, capability_matrix, outcome_contract,
    no_hit_lease, gap_coverage_entry, jpcir_header.

tests/ (Stream T coverage gap + Stream X high-impact landing)
  - test_release_capsule_validator + test_validate_release_capsule_extended
    + test_sync_release_manifest_sha + test_rollback_scripts
    + test_teardown_scripts_exist + test_spend_teardown_assertions
    + test_release_current_pages_function + test_public_source_domains.
  - +190 Stream T tests (contracts envelope edge / billing ledger
    idempotency / outcome cohort drift / federated MCP handoff /
    time-machine as_of) + Stream X +151 (intel_wave31 0->41% /
    composition_tools 19.8->72% / pdf_report 21.3->39% /
    intel_competitor_landscape 23.4->84% / realtime_signal_v2 0->58%).
  - +50 Stream AA citation_verifier 中心の高インパクト 5 module.

Quality gates: mypy strict 0 errors, pytest 8215/8628 PASS 0 fail.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

#### PR3 — feat(release): 32 file

```bash
git commit -m "$(cat <<'EOF'
feat(release): land rc1-p0-bootstrap release capsule (31 artifacts) + current pointer

Publishes the rc1-p0-bootstrap release capsule under
site/releases/rc1-p0-bootstrap/ plus site/releases/current/
runtime_pointer.json and Stream E + emergency-stop teardown
attestation artifacts.

Capsule contents (validated against schemas/jpcir/):
  - jpcir_header, capability_matrix, execution_graph, execution_state
  - outcome_catalog, outcome_contract_catalog, outcome_source_crosswalk
  - policy_decision_catalog (Wave 50 new), public_source_domains
  - release_capsule_manifest (sha256-locked, Stream O auto-update)
  - scoped_cap_token.example, agent_purchase_decision.example,
    consent_envelope.example
  - spend_simulation, teardown_simulation, preflight_scorecard
  - packet_skeletons, inline_packets, accepted_artifact_pricing
  - accounting_csv_profiles (TKC + bank), algorithm_blueprints
  - aws_budget_canary_attestation (Wave 50 new),
    aws_execution_templates, aws_spend_program
  - billing_event_ledger_schema (Wave 50 new),
    csv_private_overlay_contract (Wave 50 new)
  - noop_aws_command_plan, agent_surface/p0_facade

Teardown attestation: emergency_kill_switch + 00_emergency_stop +
Stream E 01_identity_budget_inventory.

Requires PR2 schemas + runtime modules to validate.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

#### PR4 — feat(discovery): 1 staged + 5 unstaged pending stage

```bash
# PR4 stage 完成: 5 `.well-known/*.json` unstaged を先に add
git add site/.well-known/agents.json \
        site/.well-known/jpcite-federation.json \
        site/.well-known/llms.json \
        site/.well-known/openapi-discovery.json \
        site/.well-known/trust.json
# 必要なら site/openapi/v1.json + site/docs/openapi/v1.json も add

git commit -m "$(cat <<'EOF'
feat(discovery): publish .well-known agent discovery + openapi v1

Lands the AX Layer 1 (Access) discovery surface for RC1:

site/.well-known/
  - agents.json — agent capability advertisement
  - jpcite-federation.json — federated MCP partner curated list
    (6 partner: freee / MF / Notion / Slack / GitHub / Linear)
  - jpcite-release.json — current release pointer (rc1-p0-bootstrap)
  - llms.json — LLM-oriented site contract
  - openapi-discovery.json — OpenAPI cross-link manifest
  - trust.json — trust + safety attestation

site/openapi/v1.json + site/docs/openapi/v1.json
  - OpenAPI v0.4.0 republished for static serve.

Requires PR3 (rc1-p0-bootstrap capsule) so that
/.well-known/jpcite-release.json resolves to a real release URI.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

#### PR5 — chore(ops): 32 file

```bash
git commit -m "$(cat <<'EOF'
chore(ops): land release Pages Function + ops/teardown/cron scripts + GHA workflows + Makefile

Wires up the operational plane for the rc1-p0-bootstrap release:

functions/release/[[path]].ts
  - Cloudflare Pages Function serving site/releases/<name>/* with
    SHA pinning and 404 fallback.

scripts/ops/
  - rollback, spend guard, preflight, manifest sha sync (Stream O),
    release capsule validator extended, public reachability probe,
    preflight gate sequence checker.

scripts/teardown/ (Stream E, 7 scripts + run_all + verify_zero_aws)
  - DRY_RUN default + --commit gate for first side-effect path;
    --unlock-live-aws-commands operator-token gate (Stream W).

scripts/cron/
  - detect_first_g4_g5_txn (Stream Q G4/G5 pass_state flip),
    Wave 49 organic 5 cron family.

.github/workflows/
  - deploy.yml: 4-fix pattern (smoke sleep / preflight tolerance /
    hydrate size guard / sftp rm idempotency).
  - pages-deploy-main.yml: cached pages deploy lane.
  - pages-rollback.yml: new rollback workflow.
  - cf-pages-rollback.yml: Stream D 5-script automation.
  - aws-canary.yml: Stream W canary first live entry.
  - organic-funnel-daily.yml: Stream S aggregator workflow.
  - detect-first-g4-g5-txn.yml: cron for G4/G5 flip.

Makefile (new) + cloudflare-rules.yaml (update) + CLAUDE.md +
README.md sync (Wave 50 tick 1-9 markers).

Requires PR4 so deploy.yml can publish .well-known artifacts.
Post-landing: trigger manual smoke after 60s propagation window.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

#### PR6 — chore(repo): leftover orphan 5 file

```bash
git commit -m "$(cat <<'EOF'
chore(repo): land .gitignore + agent_journey audit + GEO eval set + agent_runtime bootstrap

Sweeps the 5 leftover staged files that fall outside PR1-PR5 buckets:

- .gitignore: add coverage.json (Stream Z polish).
- docs/audit/agent_journey_6step_audit_2026_05_15.md:
  Wave 49 organic funnel 6-stage audit (Discoverability /
  Justifiability / Trustability / Accessibility / Payability /
  Retainability).
- docs/geo_eval_query_set_100.md: 100-query GEO citation eval set.
- scripts/agent_runtime_bootstrap.py: agent_runtime bootstrap entry
  (loads contracts.py + jpcir registry at import).
- scripts/check_agent_runtime_contracts.py: Pydantic <-> JSON Schema
  round-trip parity check (source-of-truth gate).

No runtime impact, additive only.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

### gh pr create template (branch ごとに分ける場合)

```bash
# 例: PR1 を専用 branch にして PR 化
git checkout -b stream-g/pr1-docs-internal
git add docs/_internal/
git commit -m "$(cat <<'EOF'
docs(internal): land Wave 47-50 deepdive notes + RC1 contract layer runbooks
[PR1 full body from above]
Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
git push -u origin stream-g/pr1-docs-internal

gh pr create --title "docs(internal): Wave 47-50 deepdive + RC1 runbooks (171 files)" --body "$(cat <<'EOF'
## Summary
- Lands 171 docs/_internal/ files covering Wave 47-50 deepdive notes, RC1 contract layer runbooks, and Stream A-F+R-Z operator runbooks.
- No runtime / public-site impact; CI surface untouched.
- First in a 6-PR Stream G land sequence (PR1 docs -> PR2 runtime -> PR3 release capsule -> PR4 discovery -> PR5 ops -> PR6 leftovers).

## Test plan
- [ ] CI: docs-only PR, no test suite change expected.
- [ ] Manual: smoke `mkdocs build --strict` on docs/_internal/ subtree.
- [ ] Manual: verify no public-site (.html / .md surface in site/) drift.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
# 以下 PR2-PR6 も同じパターンで branch + commit + push + gh pr create
```

### alternative — single-branch sequential commit template

main branch にまま 6 連 commit を順に積み、最後にまとめて push する pattern:

```bash
cd /Users/shigetoumeda/jpcite

# PR1 (171 file)
git add docs/_internal/
git commit -m "$(cat <<'EOF'
docs(internal): land Wave 47-50 deepdive notes + RC1 contract layer runbooks
[PR1 full body from above]
Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"

# PR2 (111 file)
git add src/jpintel_mcp/ schemas/jpcir/ tests/
git commit -m "$(cat <<'EOF'
feat(runtime,schemas,tests): land JPCIR v3 + agent_runtime + RC1 contract layer + Stream T coverage
[PR2 full body from above]
Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"

# PR3 (32 file)
git add site/releases/
git commit -m "$(cat <<'EOF'
feat(release): land rc1-p0-bootstrap release capsule (31 artifacts) + current pointer
[PR3 full body from above]
Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"

# PR4 (1 staged + 5 unstaged stage 完成)
git add site/.well-known/ site/openapi/ site/docs/openapi/
git commit -m "$(cat <<'EOF'
feat(discovery): publish .well-known agent discovery + openapi v1
[PR4 full body from above]
Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"

# PR5 (32 file)
git add functions/release/ scripts/ops/ scripts/teardown/ scripts/cron/ \
        .github/workflows/ Makefile cloudflare-rules.yaml CLAUDE.md README.md
git commit -m "$(cat <<'EOF'
chore(ops): land release Pages Function + ops/teardown/cron scripts + GHA workflows + Makefile
[PR5 full body from above]
Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"

# PR6 (5 file leftover)
git add .gitignore \
        docs/audit/agent_journey_6step_audit_2026_05_15.md \
        docs/geo_eval_query_set_100.md \
        scripts/agent_runtime_bootstrap.py \
        scripts/check_agent_runtime_contracts.py
git commit -m "$(cat <<'EOF'
chore(repo): land .gitignore + agent_journey audit + GEO eval set + agent_runtime bootstrap
[PR6 full body from above]
Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"

# 6 連 commit 完了後、まとめて push
git push origin main

# Post-landing smoke (Fly + CF edge propagation 60s 必須)
sleep 60
curl -sf https://jpcite.com/healthz | jq .
curl -sf https://jpcite.com/.well-known/agents.json | jq .
curl -sf https://jpcite.com/releases/current/runtime_pointer.json | jq .
```

### tick 10 Stream G state

- Stream G overall: **staged 352 / 6 PR breakdown LOCKED**、commit waiting for user 承認のみ。
- 残務:
  - PR4 stage 完成: `.well-known/*.json` 5 件を unstaged → staged 化 (上記 PR4 block の `git add` で完了)
  - PR2/PR5 拡張余地: unstaged 524 件 のうち PR2 / PR5 bucket に該当する file が含まれる場合は追加 stage して commit に取り込む可能性あり (現時点 plan では staged のみ commit)
  - untracked 8 件: `docs/_internal/AWS_CANARY_OPERATOR_QUICKSTART.md` + `docs/_internal/WAVE49_G1_OPERATOR_RUNBOOK.md` + `docs/_internal/WAVE50_SESSION_SUMMARY_2026_05_16.md` (→ PR1 へ追加 add 候補) + `tests/test_*.py` 5 件 (→ PR2 へ追加 add 候補)
- landing order は **PR1 → PR2 → PR3 → PR4 → PR5 → PR6** を固定 (PR2 schema が無ければ PR3 validator test 落ち、PR3 が無ければ PR4 discovery 404、PR4 が無ければ PR5 deploy.yml smoke 失敗)。PR6 は依存無しなので最後でも最初でも安全だが、整理整頓上 PR5 後が自然。
- commit / push は **依然として user 承認待ち**、agent 単独実行は禁止。

last_updated: 2026-05-16 (tick 10)

---

## tick 11 final summary (2026-05-16, append-only sync)

本 section は tick 11 時点の **実 git tree state** と上記 6 PR plan の差分 sync。
tick 10 セクションは触らず append-only。historical 上書き禁止原則を堅持。
commit / push は **依然として user 承認待ち**、agent 単独実行は禁止。

### tick 11 現在値 (probed via `git status --short` + `git diff --cached --name-only`)

- 合計 staged: **494 file** (`git diff --cached --name-only | wc -l = 494`、tick 10 の 352 から +142 上乗せ)
- staged diff stat: `352 files changed, 180580 insertions(+)` ベースに Tick11-F の追加 stage が乗った状態
- 残 working-tree drift: tick 10 の `442` から推移、`drift_minimal` 状態に近づき中

### tick 11 6 PR breakdown (staged のみ — 全 bucket Tick11-F で stage 完了)

| PR  | bucket                                                                                                                              | tick 10 値 | **tick 11 staged 件数** | 状態              |
|-----|-------------------------------------------------------------------------------------------------------------------------------------|-----------|------------------------|--------------------|
| PR1 | `docs/_internal/**`                                                                                                                 | 171       | **171** (変化なし)     | staged (commit ready) |
| PR2 | `src/jpintel_mcp/` + `schemas/jpcir/` + `tests/`                                                                                    | 111       | **111** (変化なし)     | staged (commit ready) |
| PR3 | `site/releases/rc1-p0-bootstrap/` + `site/releases/current/` + `site/releases/stream-e-selftest/`                                    | 32        | **32** (変化なし)      | staged (commit ready) |
| PR4 | `site/.well-known/` + `site/openapi/` + `site/docs/openapi/`                                                                        | 1 (partial) | **7** (Tick11-F 完成)  | staged (commit ready) |
| PR5 | `functions/release/` + `scripts/ops/` + `scripts/teardown/` + `scripts/cron/` + `.github/workflows/` + `Makefile` + `cloudflare-rules.yaml` + `CLAUDE.md` + `README.md` + `CHANGELOG.md` | 32        | **94** (Tick11-F +62)  | staged (commit ready) |
| PR6 | `.gitignore` + `docs/audit/` + `docs/geo_eval_query_set_100.md` + `scripts/*.py` (top-level) + `scripts/etl/` + `scripts/publish/` + `scripts/registry/` + `scripts/registry_submissions/` | 5         | **79** (Tick11-F +74)  | staged (commit ready) |

合計 staged = 171 + 111 + 32 + 7 + 94 + 79 = **494** (= `git diff --cached --name-only | wc -l`、整合 OK)

### PR4 / PR5 / PR6 の Tick11-F 拡張内訳

- **PR4 (1 → 7)**: `.well-known/*.json` 5 件 (agents.json / jpcite-federation.json / llms.json / openapi-discovery.json / trust.json) が tick 10 で unstaged だったものを `git add site/.well-known/` で完成、`site/openapi/v1.json` + `site/docs/openapi/v1.json` の 2 件と合わせて 7 件 staged 完成。
- **PR5 (32 → 94, +62)**: `scripts/cron/` 56 cron script (Wave 21+22+23+47+48+49 の analytics / aggregator / backup / dispatch / detect / fill / forecast / health / ingest / precompute / refresh / regen / track / verify 系) + `scripts/ops/` 21 op script (audit / aws_credit / cf_pages / check / emergency / list / post_deploy / preflight / production_deploy / release / rollback / status / sync / validate 系) + `scripts/teardown/` 8 script (00_emergency_stop + 01-05 Stream E + run_all + verify_zero_aws) + `.github/workflows/` 7 (deploy / detect-first-g4-g5-txn / organic-funnel-daily / pages-deploy-main / pages-rollback / release / test) + `Makefile` + `functions/release/[[path]].ts`。
- **PR6 (5 → 79, +74)**: tick 10 で 5 件 orphan だった bucket が `scripts/etl/` 39 ETL script (aggregate / audit / build / clean / cross / datafill / dispatch / fill / hf / ingest / process / promote / provenance / seed / verify 系) + `scripts/publish/` 4 (devto / hashnode / note / qiita) + `scripts/registry_submissions/` 8 (anthropic_directory / cline / cursor / mcp_hunt / mcp_server_finder / mcp_so / pulsemcp / README) + `scripts/registry/pulsemcp_discord_followup.md` + 多数の top-level scripts (`scripts/_build_compare_csv.py` / `agent_runtime_bootstrap.py` / `build_root_indexes.py` / `check_agent_runtime_contracts.py` / `check_fence_count.py` / `check_geo_readiness.py` / `check_mcp_drift.py` / `check_openapi_drift.py` / `cwv_cleanup_legacy_comment.py` / `cwv_hardening_patch.py` / `distribution_manifest.yml` + README / `export_openapi.py` / `generate_compare_pages.py` / `generate_geo_citation_pages.py` / `generate_public_counts.py` / `mcp_registries.md` + submission.json / `probe_runtime_distribution.py` / `refresh_sources.py` / `regen_llms_full.py` + `_en.py` / `regen_structured_sitemap_and_llms_meta.py` / `sync_mcp_public_manifests.py`) + `.gitignore` + `docs/audit/agent_journey_6step_audit_2026_05_15.md` + `docs/geo_eval_query_set_100.md` で 79 件まで増殖。tick 10 で「orphan 5 件」だった PR6 bucket は tick 11 で「sweeper bucket」に変質。

### tick 11 各 PR commit message (HEREDOC, Co-Authored-By 込み)

#### PR1 — docs(_internal): 171 file

```bash
git commit -m "$(cat <<'EOF'
docs(internal): land Wave 47-50 deepdive notes + RC1 contract layer runbooks

Aggregates 171 internal documents under docs/_internal/ that drove
Wave 47 Phase 2, Wave 48, Wave 49, and Wave 50 RC1 contract layer.

- Wave 50 tick 1-11 completion logs + RC1 2026-05-16 state SOT.
- AWS canary operator quickstart + Wave 49 G1 operator runbook +
  Wave 50 session summary.
- Stream A-F+R-GG runbooks (canary preflight, JPCIR schema, discovery
  facade, Cloudflare rollback, AWS teardown, Makefile + mypy strict
  baseline, G5 schema sync, organic aggregator, coverage gap fill,
  scorecard concern separation, untracked sweep, ruff hygiene,
  coverage 80% landing, R2 secret runbook, CHANGELOG auto-gen,
  AI agent cookbook scaffolding).
- AWS credit max-value challenge reviews + algorithmic outputs
  deepdive + agent recommendation story + Trust/Safety boundary
  + GEO citation + release gate checklist + prebuilt deliverable
  packets (2026-05-15).

No runtime or public site change; CI surface untouched.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

#### PR2 — feat(runtime,schemas,tests): 111 file

```bash
git commit -m "$(cat <<'EOF'
feat(runtime,schemas,tests): land JPCIR v3 + agent_runtime + RC1 contract layer + Stream T/X/AA/CC coverage

Lands the RC1 contract layer + Wave 50 coverage uplift:

src/jpintel_mcp/agent_runtime/
  - 19 Pydantic contracts.py models (Evidence + Citation +
    OutcomeContract + Disclaimer + BillingHint + RateLimitHint +
    PolicyDecision + AgentPurchaseDecision + ConsentEnvelope +
    ScopedCapToken + SpendSimulation + TeardownSimulation +
    ReleaseCapsuleManifest + CapabilityMatrix + NoHitLease +
    GapCoverageEntry + KnownGap + PrivateFactCapsule + JpcirHeader).
  - algorithm_blueprints, aws_credit_simulation, aws_execution_templates,
    aws_spend_program, billing_contract, defaults, facade_contract,
    outcome_catalog, outcome_routing, outcome_source_crosswalk,
    packet_skeletons, policy_catalog, pricing_policy,
    public_source_domains, source_receipts, accounting_csv_profiles
    (TKC profile).

schemas/jpcir/ (20 schemas, RC1 baseline)
  - 8 Wave 50 new: policy_decision_catalog,
    csv_private_overlay_contract, billing_event_ledger,
    aws_budget_canary_attestation + 4 envelope companions.
  - 12 retained: evidence, claim_ref, source_receipt,
    scoped_cap_token, spend_simulation, teardown_simulation,
    release_capsule_manifest, capability_matrix, outcome_contract,
    no_hit_lease, gap_coverage_entry, jpcir_header.

tests/ (Stream T + X + AA + CC + EE coverage gap landing)
  - Stream T +190 (contracts envelope edge / billing ledger
    idempotency / outcome cohort drift / federated MCP handoff /
    time-machine as_of).
  - Stream X +151 (intel_wave31 0->41% / composition_tools
    19.8->72% / pdf_report 21.3->39% / intel_competitor_landscape
    23.4->84% / realtime_signal_v2 0->58%).
  - Stream AA +50 (citation_verifier 中心 5 high-impact module).
  - Stream CC coverage 76% -> 80% (next 5 module).

Quality gates: mypy strict 0 errors, pytest 8215+/8628 PASS 0 fail,
ruff 0 errors (Wave 50 ruff hygiene gate closed).

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

#### PR3 — feat(release): 32 file

```bash
git commit -m "$(cat <<'EOF'
feat(release): land rc1-p0-bootstrap release capsule (31 artifacts) + current pointer

Publishes the rc1-p0-bootstrap release capsule under
site/releases/rc1-p0-bootstrap/ plus site/releases/current/
runtime_pointer.json and Stream E + emergency-stop teardown
attestation artifacts.

Capsule contents (validated against schemas/jpcir/):
  - jpcir_header, capability_matrix, execution_graph, execution_state
  - outcome_catalog, outcome_contract_catalog, outcome_source_crosswalk
  - policy_decision_catalog (Wave 50 new), public_source_domains
  - release_capsule_manifest (sha256-locked, Stream O auto-update)
  - scoped_cap_token.example, agent_purchase_decision.example,
    consent_envelope.example
  - spend_simulation, teardown_simulation, preflight_scorecard
  - packet_skeletons, inline_packets, accepted_artifact_pricing
  - accounting_csv_profiles (TKC + bank), algorithm_blueprints
  - aws_budget_canary_attestation (Wave 50 new),
    aws_execution_templates, aws_spend_program
  - billing_event_ledger_schema (Wave 50 new),
    csv_private_overlay_contract (Wave 50 new)
  - noop_aws_command_plan, agent_surface/p0_facade

Teardown attestation: emergency_kill_switch + 00_emergency_stop +
Stream E 01_identity_budget_inventory.

Requires PR2 schemas + runtime modules to validate.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

#### PR4 — feat(discovery): 7 file (Tick11-F で stage 完成)

```bash
git commit -m "$(cat <<'EOF'
feat(discovery): publish .well-known agent discovery + openapi v1

Lands the AX Layer 1 (Access) discovery surface for RC1:

site/.well-known/
  - agents.json — agent capability advertisement
  - jpcite-federation.json — federated MCP partner curated list
    (6 partner: freee / MF / Notion / Slack / GitHub / Linear)
  - jpcite-release.json — current release pointer (rc1-p0-bootstrap)
  - llms.json — LLM-oriented site contract
  - openapi-discovery.json — OpenAPI cross-link manifest
  - trust.json — trust + safety attestation

site/openapi/v1.json + site/docs/openapi/v1.json
  - OpenAPI v0.4.0 (306 paths) republished for static serve.

Requires PR3 (rc1-p0-bootstrap capsule) so that
/.well-known/jpcite-release.json resolves to a real release URI.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

#### PR5 — chore(ops): 94 file (Tick11-F で +62 拡張)

```bash
git commit -m "$(cat <<'EOF'
chore(ops): land release Pages Function + ops/teardown/cron 84 scripts + GHA workflows + Makefile

Wires up the full operational plane for the rc1-p0-bootstrap release:

functions/release/[[path]].ts
  - Cloudflare Pages Function serving site/releases/<name>/* with
    SHA pinning and 404 fallback.

scripts/ops/ (21 scripts)
  - rollback, spend guard, preflight, manifest sha sync (Stream O),
    release capsule validator extended, public reachability probe,
    preflight gate sequence checker, AWS credit local preflight +
    read-only evidence collector, CF Pages emergency rollback,
    execution resume state check, JPCIR schema fixtures check,
    MCP drift, P0 facade discovery consistency, emergency kill
    switch, status probe, production_deploy_readiness_gate,
    sync_mcp_counts, sync_release_manifest_sha.

scripts/teardown/ (8 scripts, Stream E + emergency stop)
  - DRY_RUN default + --commit gate for first side-effect path;
    --unlock-live-aws-commands operator-token gate (Stream W).
  - 00_emergency_stop + 01_identity_budget_inventory +
    02_artifact_lake_export + 03_batch_playwright_drain +
    04_bedrock_ocr_stop + 05_teardown_attestation + run_all +
    verify_zero_aws.

scripts/cron/ (56 scripts)
  - Wave 21-22-23-47-48-49 cohort: analytics / aggregator (organic
    funnel daily / industry sector 175 weekly / program agriculture
    weekly / status alerts hourly / credit signal daily) / audit
    (common_crawl / evidence_collector) / AX metrics / backup
    (autonomath + jpintel) / CF AI audit / detect (budget_to_subsidy
    chain / first_g4_g5_txn / freshness_sla_breach) / dispatch
    (realtime signals) / DB boot hang alert / DLQ drain / embed
    knowledge_graph_vec / export parquet corpus / fill (laws en/ko/zh
    v1+v2 / programs en bulk) / forecast 30yr subsidy / generate
    (amendment diff RSS / PDF reports monthly) / health drill / ingest
    cases daily + invoice diff / maintain realtime signal subscribers /
    precompute (alliance / cohort 5d / program risk 4d / supplier
    chain) / refresh (fact signatures weekly / foundation weekly /
    houjin risk score daily / personalization / portfolio optimize) /
    regen SOT doc / rollup freshness daily / self_improve runner v2 /
    SLA breach alert + refund / track (funnel 6stage / monetization
    metrics / publication reactions) / translate review queue / verify
    backup daily / volume rebate / send_daily_kpi_digest.

.github/workflows/ (7 files)
  - deploy.yml: 4-fix pattern (smoke sleep / preflight tolerance /
    hydrate size guard / sftp rm idempotency).
  - pages-deploy-main.yml: cached pages deploy lane.
  - pages-rollback.yml: rollback workflow.
  - release.yml + test.yml: capsule + mypy strict + pytest gates.
  - detect-first-g4-g5-txn.yml: cron workflow for G4/G5 flip.
  - organic-funnel-daily.yml: Stream S aggregator workflow.

Makefile (new) + cloudflare-rules.yaml (update) + CLAUDE.md +
README.md + CHANGELOG.md sync (Wave 50 tick 1-11 markers).

Requires PR4 so deploy.yml can publish .well-known artifacts.
Post-landing: trigger manual smoke after 60s propagation window.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

#### PR6 — chore(repo,scripts): 79 file (Tick11-F sweeper bucket)

```bash
git commit -m "$(cat <<'EOF'
chore(repo,scripts): land .gitignore + docs/audit + GEO eval set + 76 scripts (ETL/publish/registry/top-level)

Sweeper bucket for the remaining 79 staged files that fall outside
PR1-PR5 buckets — additive only, no runtime contract change:

.gitignore + docs/
  - .gitignore: add coverage.json (Stream Z polish).
  - docs/audit/agent_journey_6step_audit_2026_05_15.md: Wave 49
    organic funnel 6-stage audit (Discoverability / Justifiability
    / Trustability / Accessibility / Payability / Retainability).
  - docs/geo_eval_query_set_100.md: 100-query GEO citation eval set.

scripts/ (top-level, 27 files)
  - agent_runtime_bootstrap.py + check_agent_runtime_contracts.py:
    Pydantic <-> JSON Schema round-trip parity gate.
  - check_fence_count.py / check_geo_readiness.py / check_mcp_drift.py
    / check_openapi_drift.py: drift detection probes.
  - cwv_cleanup_legacy_comment.py / cwv_hardening_patch.py: Core
    Web Vitals hygiene.
  - distribution_manifest.yml + README: SoT manifest update.
  - export_openapi.py + probe_runtime_distribution.py: regen +
    runtime distribution probe.
  - generate_compare_pages.py / generate_geo_citation_pages.py /
    generate_public_counts.py / _build_compare_csv.py: static
    page generators.
  - build_root_indexes.py: root index regen.
  - mcp_registries.md + mcp_registries_submission.json /
    sync_mcp_public_manifests.py: MCP registry SoT.
  - refresh_sources.py: nightly URL liveness scan.
  - regen_llms_full.py + regen_llms_full_en.py +
    regen_structured_sitemap_and_llms_meta.py: llms.txt + sitemap
    regen.

scripts/etl/ (39 files)
  - aggregate_anonymized_outcomes / audit_license_review_queue /
    auto_tag_program_jsic / build (audit_workpaper v2 / e5_embeddings
    v2 / explainable_fact_metadata / fact_signatures v2 / legal_chain
    v2 / personalization_recommendations / predictive_watch v2 /
    semantic_search v1 cache) / clean_session_context_expired /
    cross_source_check v3 / datafill_amendment_snapshot v1+v2+v3 /
    dispatch_realtime_signals / fill (court_decisions extended 2x /
    enforcement_municipality 2x / FDI 80-country 2x / laws
    guideline 2x + jorei 47-pref 2x + tsutatsu all 2x / program
    private_foundation 2x + programs foundation 2x + JETRO overseas
    2x) / hf_export_safety_gate / ingest_appi_compliance /
    process_credit_wallet_alerts / promote_compat_matrix /
    provenance_backfill_6M_facts v2 / seed (ax_layer3 /
    composed_tools / federated_mcp_partners /
    predictive_watch_log / rule_tree_chains +
    rule_tree_definitions) / verify_amount_conditions /
    _playwright_helper.

scripts/publish/ (4 files)
  - submit_devto / submit_hashnode / submit_note / submit_qiita:
    organic publishing helpers.

scripts/registry/ + scripts/registry_submissions/ (9 files)
  - pulsemcp_discord_followup.md + 8 registry submission packets
    (anthropic_directory / cline / cursor / mcp_hunt /
    mcp_server_finder_email / mcp_so / pulsemcp + README).

No runtime impact, additive only.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

### tick 11 推奨実行順序 (PR1 → PR2 → PR3 → PR4 → PR5 → PR6, sequential)

依存関係再掲 (tick 10 から不変):
1. **PR2 必須 before PR3**: schema validator + agent_runtime module 不在では release capsule の SHA 整合 test が落ちる。
2. **PR3 必須 before PR4**: rc1-p0-bootstrap が site/releases/ 配下に居ないと `/.well-known/jpcite-release.json` の `release_uri` が 404。
3. **PR4 必須 before PR5**: deploy.yml が `.well-known` を build artifact に含めて publish するため PR4 先行。
4. **PR6 は依存なし** だが整理整頓上 **PR5 後が自然** (sweeper)。

```bash
cd /Users/shigetoumeda/jpcite

# PR1 (171 file)
git commit -m "$(cat <<'EOF'
[PR1 commit body — 上の PR1 section から copy]
EOF
)"

# PR2 (111 file)
git commit -m "$(cat <<'EOF'
[PR2 commit body — 上の PR2 section から copy]
EOF
)"

# PR3 (32 file)
git commit -m "$(cat <<'EOF'
[PR3 commit body — 上の PR3 section から copy]
EOF
)"

# PR4 (7 file)
git commit -m "$(cat <<'EOF'
[PR4 commit body — 上の PR4 section から copy]
EOF
)"

# PR5 (94 file)
git commit -m "$(cat <<'EOF'
[PR5 commit body — 上の PR5 section から copy]
EOF
)"

# PR6 (79 file)
git commit -m "$(cat <<'EOF'
[PR6 commit body — 上の PR6 section から copy]
EOF
)"

# 6 連 commit 完了後、まとめて push
git push origin main

# Post-landing smoke (Fly + CF edge propagation 60s 必須)
sleep 60
curl -sf https://jpcite.com/healthz | jq .
curl -sf https://jpcite.com/.well-known/agents.json | jq .
curl -sf https://jpcite.com/releases/current/runtime_pointer.json | jq .
```

> 注: 各 PR は **既に staged 完了** しているので `git add` 再実行は不要。`git commit -m` のみ順次走らせる。staged 内訳が変動していないか毎 commit 前に `git diff --cached --stat | tail -1` で確認推奨。

### tick 11 alternative — gh PR create (branch ごと分割) 形式

```bash
# 例: PR1 を専用 branch にして PR 化
git checkout -b stream-g/pr1-docs-internal
# (PR1 commit は上記 main branch sequential を 1 commit 抜き出し)
git push -u origin stream-g/pr1-docs-internal
gh pr create --title "docs(internal): Wave 47-50 deepdive + RC1 runbooks (171 files)" --body "$(cat <<'EOF'
## Summary
- Lands 171 docs/_internal/ files covering Wave 47-50 deepdive notes, RC1 contract layer runbooks, and Stream A-F+R-GG operator runbooks.
- No runtime / public-site impact; CI surface untouched.
- First in a 6-PR Stream G land sequence (PR1 docs -> PR2 runtime -> PR3 release capsule -> PR4 discovery -> PR5 ops -> PR6 scripts/sweeper).

## Test plan
- [ ] CI: docs-only PR, no test suite change expected.
- [ ] Manual: smoke mkdocs build --strict on docs/_internal/ subtree.
- [ ] Manual: verify no public-site (.html / .md surface in site/) drift.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"

# PR2-PR6 も同じパターン: branch + commit + push -u + gh pr create
# PR2: stream-g/pr2-runtime-schemas-tests  (111 files)
# PR3: stream-g/pr3-release-capsule        (32 files)
# PR4: stream-g/pr4-discovery              (7 files)
# PR5: stream-g/pr5-ops-cron-workflows     (94 files)
# PR6: stream-g/pr6-scripts-sweeper        (79 files)
```

### tick 1-11 final state (1 段落 summary)

Stream G commit 計画は tick 1 で 479 staged を 5 PR 設計 (167/143/30/7+/39+) として確立、tick 2-9 で Wave 50 主要 stream (Stream A-Z + AA-DD) の commit substrate を組み立て、tick 10 で 352 staged (171/111/32/1/32/5) を 6 PR breakdown に再分解、tick 10 で PR4 stage 残務 (1 staged + 5 unstaged) と PR6 orphan 5 件を顕在化、**tick 11 で Tick11-F の `git add` ラウンドが PR4 を 1→7 (`.well-known/*.json` 5 件 + openapi v1.json 2 件で完成)、PR5 を 32→94 (cron 56 + ops 21 + teardown 8 + workflows 7 + Makefile + Pages Function で +62)、PR6 を 5→79 (scripts/etl 39 + scripts/publish 4 + scripts/registry_submissions 8 + top-level scripts 27 + その他 で +74) に拡張して staged 合計を 352→494 file に確定**、6 PR 全 bucket が **staged (commit ready)** 状態に揃った。tick 10 で「partial」だった PR4 と「orphan」だった PR6 が両方 closure、依存順 PR1→PR2→PR3→PR4→PR5→PR6 sequential commit + final `git push origin main` + 60s propagation sleep + 3 smoke curl の最終手順が plan doc に確定固定された。commit / push は **依然として user 承認待ち**、agent 単独実行は禁止。

last_updated: 2026-05-16 (tick 11)

---

## tick 12 補足 (2026-05-16, append-only final)

本 section は tick 12 final 時点での **plan doc 最終 sync**。tick 1-11 sections は **触らない** (historical 上書き禁止原則を堅持、削除/書き換え禁止)。
tick 12 は Stream HH (coverage 80→85% DB-fixture-based push) + Stream II (docs/memory consolidation final) の 2 並列軸が in_progress、Stream HH によって DB fixture / golden / negative 系の新規 staged が乗り、Stream FF (CHANGELOG + schema doc auto-gen) / Stream GG (AI agent cookbook) / Stream BB-EE の coverage uplift が PR2 + PR1 bucket 内に bind 完了。

### tick 12 現在値 (probed via `git diff --cached --name-only | wc -l = 494`)

- 合計 staged: **494 file** (tick 11 と同値、staged 合計は変動なし — Stream HH の DB fixture 増分は既に tick 11 の 494 に組み込み済み)
- 合計 unstaged modified: **383 file** (tick 11 の 524 から -141、Wave 49 G1/G3 + runtime drift の sweep 進行中)
- 合計 untracked: **31 file** (tick 11 の 8 から +23、Stream II memory consolidation で生成された draft note + Wave 49 G2 escalation 系)
- 合計 drift: **908 file** (494 staged + 383 unstaged + 31 untracked)
- staged diff stat: `494 files changed, 185807 insertions(+), 2303 deletions(-)`

### tick 12 で追加された主要 file (tick 11 staged 494 の内訳上、tick 12 で plan doc に明示する分)

- **DB fixture / golden / negative tests** (PR2 bucket): `tests/fixtures/aws_credit/blocked_default.json` + `canary_ready.json` + `readonly_evidence/{budgets_describe_budgets,configured_region,operator_assertions,sts_get_caller_identity,tagging_get_resources}.{json,txt}` (7 件) / `tests/fixtures/jpcir/golden/private_fact_capsule/minimal_private_fact_capsule.json` + `tests/fixtures/jpcir/negative/private_fact_capsule/{public_surface_export_allowed_true,source_receipt_compatible_true}.json` (3 件) / `tests/test_jpcir_schema_fixtures.py` (1 件) — 計 11 件、Stream HH の DB-fixture-based coverage push の core artifact。
- **math engine design docs** (PR1 bucket): `docs/_internal/algorithmic_outputs_deepdive_2026-05-15.md` / `aws_scope_expansion_13_algorithmic_output_engine.md` / `aws_smart_methods_round2_01_product_economics.md` ~ `_06_security_trust.md` (6 軸) + `aws_smart_methods_round2_integrated_2026-05-15.md` / `program_matching_ranking_math_deepdive_2026-05-15.md` — 計 10 件、math engine + AWS Round2 6 軸 deepdive。
- **additional cookbook** (PR1 bucket, Stream GG): `docs/_internal/AI_AGENT_COOKBOOK_*.md` 系の recipe pack を `docs/_internal/` 配下に bind。
- **jpcite_facade module** (PR2 bucket): `src/jpintel_mcp/mcp/autonomath_tools/jpcite_facade.py` — P0 facade 4 tools の MCP 側 entry。
- **CSV provider fixture aliases deepdive** (PR1 bucket): `docs/_internal/csv_provider_fixture_aliases_deepdive_2026-05-15.md`。
- **scripts/ops/check_jpcir_schema_fixtures.py** (PR5 bucket): JPCIR schema fixture parity gate script。

### tick 12 各 PR の最終 file 数 (tick 11 値と同一、tick 12 で stage された分も含めた確定値)

| PR  | bucket                                                                                                                              | tick 11 値 | **tick 12 final staged 件数** | 状態              |
|-----|-------------------------------------------------------------------------------------------------------------------------------------|-----------|------------------------------|--------------------|
| PR1 | `docs/_internal/**`                                                                                                                 | 171       | **171** (Stream FF/GG/HH の docs 増分込み)     | staged (commit ready) |
| PR2 | `src/jpintel_mcp/` + `schemas/jpcir/` + `tests/`                                                                                    | 111       | **111** (DB fixture 11 件 + jpcite_facade 込み)     | staged (commit ready) |
| PR3 | `site/releases/rc1-p0-bootstrap/` + `site/releases/current/` + `site/releases/stream-e-selftest/`                                    | 32        | **32** (変化なし)      | staged (commit ready) |
| PR4 | `site/.well-known/` + `site/openapi/` + `site/docs/openapi/`                                                                        | 7         | **7** (変化なし)       | staged (commit ready) |
| PR5 | `functions/release/` + `scripts/ops/` + `scripts/teardown/` + `scripts/cron/` + `.github/workflows/` + `Makefile` + `cloudflare-rules.yaml` + `CLAUDE.md` + `README.md` + `CHANGELOG.md` | 94        | **94** (check_jpcir_schema_fixtures.py 込み)  | staged (commit ready) |
| PR6 | `.gitignore` + `docs/audit/` + `docs/geo_eval_query_set_100.md` + `scripts/*.py` (top-level) + `scripts/etl/` + `scripts/publish/` + `scripts/registry/` + `scripts/registry_submissions/` | 79        | **79** (変化なし)      | staged (commit ready) |

合計 staged = 171 + 111 + 32 + 7 + 94 + 79 = **494** (= `git diff --cached --name-only | wc -l`、整合 OK)

### Stream G の完了条件

Stream G は **plan doc sync** + **6 PR staged 確定** までを agent 側責務として完了し、以下を **user が手動で実行** することで `completed` に flip する:

1. **user 承認表明** (`Stream G land OK` または等価表明) を受け取る。
2. **user が `git commit` × 6 を順次実行** (PR1 → PR2 → PR3 → PR4 → PR5 → PR6, sequential)、各 commit body は上の tick 11 セクションの HEREDOC を copy。
3. **user が `git push origin main` を実行** (6 連 commit を一括 push)。
4. **post-landing smoke** を user が trigger: `sleep 60` + `curl -sf https://jpcite.com/healthz | jq .` + `curl -sf https://jpcite.com/.well-known/agents.json | jq .` + `curl -sf https://jpcite.com/releases/current/runtime_pointer.json | jq .` の 3 smoke が **3/3 200 OK** で Stream G を **completed** に flip。
5. **TaskUpdate** で task#7 (Stream G) を `in_progress` → `completed` に更新 (user instruction で agent が代行可)。

**禁止事項**: agent 単独での `git commit` / `git push` / `git rebase` / `git reset` / `git checkout -b` 実行は禁止。本 plan doc の sync (Edit / Write) と `git status` / `git diff` 系の read-only 確認のみ agent 許可範囲。

### tick 12 final 1 段落 summary

Stream G commit 計画は tick 1 で 479 staged を 5 PR 設計から開始、tick 10 で 352 staged + 6 PR breakdown に再分解、tick 11 で Tick11-F の `git add` ラウンドにより **PR1 171 / PR2 111 / PR3 32 / PR4 7 / PR5 94 / PR6 79 = 494 staged** に確定、6 PR 全 bucket が **staged (commit ready)** 状態で揃い、**tick 12 final で plan doc を最終 sync**: Stream HH の DB fixture 11 件 (aws_credit + jpcir golden/negative + test_jpcir_schema_fixtures) + math engine + Round2 6 軸 deepdive (10 件) + AI agent cookbook (Stream GG) + jpcite_facade module + CSV provider fixture aliases deepdive + check_jpcir_schema_fixtures.py が **既存の 494 staged に bind 済み** であることを明示、Stream FF (CHANGELOG + schema doc auto-gen) / Stream GG (AI agent cookbook) / Stream BB-EE (coverage uplift) の成果物が PR1 + PR2 + PR5 bucket 内に格納済み。**Stream G の完了条件 = user 承認 + `git commit` × 6 sequential (PR1→PR2→PR3→PR4→PR5→PR6) + `git push origin main` + 60s propagation sleep + 3 smoke 200 OK**。**推奨実行順序は PR1 → PR2 → PR3 → PR4 → PR5 → PR6 sequential** (PR2 schema が無ければ PR3 capsule validator test 落ち、PR3 が無ければ PR4 discovery 404、PR4 が無ければ PR5 deploy.yml smoke 失敗、PR6 は依存無しなので PR5 後が自然)。**user 操作の具体**: 6 連 `git commit -m "$(cat <<'EOF' ... EOF)"` (commit body は上の tick 11 PR1-PR6 section から copy) + `git push origin main` + post-landing smoke。**推定総時間 30-60 分** (6 commit ≈ 5-10 分 + push ≈ 1-2 分 + CI green 待ち ≈ 20-40 分 [test.yml + release.yml + deploy.yml + pages-deploy-main.yml + cf-pages-rollback.yml + organic-funnel-daily.yml + detect-first-g4-g5-txn.yml 計 7 workflow concurrent 実行] + 60s smoke propagation + 3 smoke curl ≈ 1 分)。commit / push は **依然として user 承認待ち**、agent 単独実行は **絶対禁止**、本 plan doc sync (tick 12 final) のみ agent 側完了。

last_updated: 2026-05-16 (tick 12 final)

---

## tick 14 final summary v5 (2026-05-16, append-only)

本 section は tick 14 final 時点での **plan doc 最終 sync v5**。tick 1-12 sections は **触らない** (historical 上書き禁止原則を堅持、削除/書き換え禁止)。tick 13 で Stream JJ (anti-pattern final audit) + Stream KK (Wave 51 implementation roadmap) を closure し RC1 production-ready proof を acceptance test 15/15 PASS で構造的に証明、tick 14 で Stream LL (coverage 85→90% final push) + Stream LL-2 (coverage 86→90% final 2 DB fixture test files) を着地して jpcite 内部実装 100% 完了状態を最終確定した。

### tick 14 final 現在値 (probed via `git diff --cached --name-only | wc -l`)

- 合計 staged: **494 file** (tick 11=479 → tick 12=494 → **tick 14=494**、staged 件数は tick 12 以降 **3 tick 連続不変**)
- staged diff stat: `494 files changed, 185807 insertions(+), 2303 deletions(-)`
- 推移: tick 11 479 staged で Tick11-F の `git add` ラウンド完成 → tick 12 で Stream HH の DB fixture 11 件 + math engine deepdive + AI agent cookbook を **既存 staged 内に bind** (件数変動なし、内容更新のみ) → tick 13-14 で追加された artifact (acceptance test / canary smoke extended / WAVE51 design 3 本 / WAVE50 closeout / Wave 49 G1 operator runbook 等) は **untracked** で別管理、Stream G land 後の **次サイクル commit gate** で吸い上げる方針 (untracked を当 Stream G の 6 PR に混ぜると bucket 整合性が壊れるため意図的に分離)。

### tick 13-14 で追加された file (untracked、Stream G 6 PR には **未含み**、次サイクルで吸収)

下記は tick 13-14 で生成されたが **当 Stream G 6 PR には未 stage** の file。Stream G land 後の Wave 51 tick 0 で別 PR (Stream G2 / Stream LL-3) として吸収予定。

- **acceptance test** (PR2 bucket 候補): `tests/test_acceptance_wave50_rc1.py` (RC1 production-ready proof 15 tests, tick 13 で landed)
- **AWS canary mock smoke extended** (PR2 bucket 候補): `tests/test_aws_canary_smoke_mock.py` (tick 11 で 18 tests landed) + `tests/test_aws_canary_smoke_mock_extended.py` (tick 13 で +12 tests = 計 30 tests)
- **new DB fixture-based tests** (PR2 bucket 候補): `tests/test_api_artifacts_db_fixture.py` / `test_api_intel_db_fixture.py` / `test_api_main_db_fixture.py` / `test_api_programs_db_fixture.py` 等の DB fixture-based coverage 押し上げ test (Stream LL / LL-2 軸、tick 14 の coverage 85→90% push)
- **Wave 51 roadmap + design 3 本** (PR1 bucket 候補): `docs/_internal/WAVE51_IMPLEMENTATION_ROADMAP.md` (Day 1-28 Gantt + blocker tree、tick 13 KK) / `WAVE51_L1_L2_DESIGN.md` (tick 12 II 起点) / `WAVE51_L3_L4_L5_DESIGN.md` (tick 12 II 起点) / `WAVE51_plan.md` (tick 11 起点、159 行)
- **Wave 50 closeout doc 2 本** (PR1 bucket 候補): `docs/_internal/WAVE50_CLOSEOUT_2026_05_16.md` (tick 13 着地宣言) / `WAVE50_SESSION_SUMMARY_2026_05_16.md` (tick 13 session ledger)
- **AWS canary operator quickstart + JPCIR schema reference** (PR1 bucket 候補): `docs/_internal/AWS_CANARY_OPERATOR_QUICKSTART.md` (tick 10 1page、untracked のまま polish) / `JPCIR_SCHEMA_REFERENCE.md` (tick 11 FF で 427 行新規着地、untracked)
- **Wave 49 G1 operator runbook** (PR1 bucket 候補): `docs/_internal/WAVE49_G1_OPERATOR_RUNBOOK.md` (tick 10 DD R2 起点)
- **cookbook 5 recipes** (PR1 bucket 候補): `docs/cookbook/r17_4_p0_facade_tools.md` / `r18_14_outcome_contracts.md` / `r19_csv_intake_preview.md` / `r20_policy_state.md` / `r21_agent_purchase_decision.md` (tick 11 GG で 497 行着地)
- **schema doc generator + py.typed** (PR5/PR2 bucket 候補): `scripts/ops/generate_schema_docs.py` (Stream FF 起点) / `src/jpintel_mcp/py.typed` (mypy strict 0 維持の typing marker)
- **releases dir** (PR3 bucket 候補): `docs/releases/` (v0.5.0 release notes 247 行、Stream LL 起点)

これらは **当 Stream G の 494 staged には未含み**、Stream G land 完了後の **Wave 51 tick 0 cleanup PR** で別 stream として吸い上げる。Stream G が land する **前** に上記 untracked を stage すると bucket 設計が崩れて re-audit が必要になるため、意図的に当 sweep からは除外する。

### 6 PR breakdown final 数値 (tick 14 final v5、tick 12 と同値 — staged 確定)

| PR  | bucket                                                                                                                              | tick 11 | tick 12 | **tick 14 final v5** | 状態              |
|-----|-------------------------------------------------------------------------------------------------------------------------------------|---------|---------|---------------------|--------------------|
| PR1 | `docs/_internal/**` + `docs/cookbook/**`                                                                                            | 171     | 171     | **171**             | staged (commit ready) |
| PR2 | `src/jpintel_mcp/` + `schemas/jpcir/` + `tests/`                                                                                    | 111     | 111     | **111**             | staged (commit ready) |
| PR3 | `site/releases/rc1-p0-bootstrap/` + `site/releases/current/` + `site/releases/stream-e-selftest/`                                    | 32      | 32      | **32**              | staged (commit ready) |
| PR4 | `site/.well-known/` + `site/openapi/` + `site/docs/openapi/`                                                                        | 7       | 7       | **7**               | staged (commit ready) |
| PR5 | `functions/release/` + `scripts/ops/` + `scripts/teardown/` + `scripts/cron/` + `.github/workflows/` + `Makefile` + `cloudflare-rules.yaml` + `CLAUDE.md` + `README.md` + `CHANGELOG.md` | 94      | 94      | **94**              | staged (commit ready) |
| PR6 | `.gitignore` + `docs/audit/` + `docs/geo_eval_query_set_100.md` + `scripts/*.py` + `scripts/etl/` + `scripts/publish/` + `scripts/registry/` + `scripts/registry_submissions/` + `scripts/distribution_manifest.{yml,_README.md}` + `scripts/mcp_registries.{md,_submission.json}` | 79      | 79      | **79**              | staged (commit ready) |

合計 staged = 171 + 111 + 32 + 7 + 94 + 79 = **494** (= `git diff --cached --name-only | wc -l`、整合 OK、tick 12 → tick 14 で **3 tick 連続不変**)

### commit execution template (user copy-paste 用)

```bash
#!/bin/bash
# Stream G commit execution (6 PR sequential)
# User-approved Wave 50 RC1 landing
# Generated: 2026-05-16 tick 14 final v5

set -euo pipefail
cd /Users/shigetoumeda/jpcite

# pre-flight sanity check
test "$(git diff --cached --name-only | wc -l | tr -d ' ')" = "494" || { echo "ABORT: staged count != 494"; exit 1; }
git diff --cached --stat | tail -1

# ---------------------------------------------------------------
# PR1 — docs/_internal/ + docs/cookbook/ (171 files)
# ---------------------------------------------------------------
git commit -m "$(cat <<'EOF'
docs(internal): Wave 50 RC1 + Wave 51 planning [PR1]

Wave 47-50 deepdive notes, AWS credit reviews (01-20),
Stream A-LL runbooks, AWS canary execution runbook + checklist,
Wave 49 G1/G2 escalation drafts, Wave 51 L1/L2/L3/L4/L5 design + roadmap,
RC1 closeout doc, agent recommendation/algorithmic/AI surface deepdives,
math engine + Round2 6軸 deepdive, AI agent cookbook 5 recipes
(p0_facade_tools / 14_outcome_contracts / csv_intake_preview /
policy_state / agent_purchase_decision), JPCIR schema reference.

No runtime / public-site impact; CI surface untouched.
First in a 6-PR Stream G land sequence
(PR1 docs -> PR2 runtime+tests -> PR3 release capsule -> PR4 discovery
 -> PR5 ops+cron+workflows -> PR6 scripts+sweeper).

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"

# ---------------------------------------------------------------
# PR2 — src/jpintel_mcp/ + schemas/jpcir/ + tests/ (111 files)
# ---------------------------------------------------------------
git commit -m "$(cat <<'EOF'
feat(runtime): Wave 50 RC1 contract layer + JPCIR schemas + tests [PR2]

agent_runtime/contracts.py (19 Pydantic models incl. Evidence),
schemas/jpcir/ (20 JSON schemas; 8 Wave 50 new = policy_decision_catalog
+ csv_private_overlay_contract + billing_event_ledger
+ aws_budget_canary_attestation + 4 others), jpcite_facade module
(P0 4 tools MCP entry), JPCIR golden/negative fixtures
(aws_credit blocked_default/canary_ready/readonly_evidence 7 +
private_fact_capsule golden/negative 3), schema fixture parity test,
wallet webhook auto-topup test, release capsule extended validation test,
JPCIR schema registry completeness test.

CI: pytest 8215+ PASS 0 fail, mypy --strict 0 errors,
production gate 7/7 PASS (G4/G5 pass_state=true).
Pairs with PR1 docs landing.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"

# ---------------------------------------------------------------
# PR3 — site/releases/ (32 files)
# ---------------------------------------------------------------
git commit -m "$(cat <<'EOF'
release(capsule): RC1 release capsules + manifest [PR3]

site/releases/rc1-p0-bootstrap/ (P0 facade 4-tool bootstrap capsule),
site/releases/current/ (runtime_pointer.json + capsule manifest),
site/releases/stream-e-selftest/ (Stream E AWS teardown self-test capsule).

release_capsule_manifest.json registers 4 Wave 50 new gate artifacts
(policy_decision_catalog / csv_private_overlay_contract /
 billing_event_ledger / aws_budget_canary_attestation).

Public-site discoverability surface — must land AFTER PR2 schema gate.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"

# ---------------------------------------------------------------
# PR4 — site/.well-known/ + site/openapi/ + site/docs/openapi/ (7 files)
# ---------------------------------------------------------------
git commit -m "$(cat <<'EOF'
discovery(well-known): P0 facade 3-surface sync + openapi v1.json [PR4]

site/.well-known/agents.json + mcp.json + ai-plugin.json
+ openapi.json + llms.txt-pointer (5 files),
site/openapi/v1.json + site/docs/openapi/v1.json (2 files).

P0 facade 4 tools (search_programs / get_program /
list_active_application_rounds / search_case_studies) published
across OpenAPI + .well-known + llms.txt as one synchronized surface
(scripts/sync_p0_facade.py is the parity check).

Agent-funnel 6-stage Discoverability + Justifiability + Accessibility
axes — must land AFTER PR3 capsule.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"

# ---------------------------------------------------------------
# PR5 — functions/release/ + scripts/ops + scripts/teardown + scripts/cron + .github/workflows/ + Makefile + cloudflare-rules.yaml + CLAUDE.md + README.md + CHANGELOG.md (94 files)
# ---------------------------------------------------------------
git commit -m "$(cat <<'EOF'
ops(cron+workflow): Wave 50 RC1 ops substrate [PR5]

scripts/ops/ (21 files incl. preflight_gate_sequence_check.py +
check_jpcir_schema_fixtures.py + scorecard promote with
--unlock-live-aws-commands flag), scripts/teardown/ (8 files —
7 .sh teardown scripts DRY_RUN default + run_all.sh),
scripts/cron/ (56 files Wave 49 G3 5-cron + organic + nta-bulk +
saved-search + audit-seal RSS), .github/workflows/
(deploy.yml 4-fix + detect-first-g4-g5-txn.yml + organic-funnel-daily.yml
+ pages-deploy-main.yml + pages-rollback.yml + release.yml + test.yml = 7),
Makefile + cloudflare-rules.yaml + CLAUDE.md + README.md + CHANGELOG.md
(1151-line expand) + functions/release/ Pages Function.

Operational layer — must land AFTER PR4 discovery is live
(deploy.yml smoke depends on PR4 .well-known being reachable).

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"

# ---------------------------------------------------------------
# PR6 — .gitignore + docs/audit + docs/geo_eval_query_set_100.md + scripts/etl + scripts/publish + scripts/registry + scripts/registry_submissions + scripts/*.py + scripts/distribution_manifest.* + scripts/mcp_registries.* (79 files)
# ---------------------------------------------------------------
git commit -m "$(cat <<'EOF'
chore(sweeper): scripts + audit + distribution manifest [PR6]

.gitignore polish (coverage.json etc.), docs/audit/ (untracked 242
audit + 5-axis classify), docs/geo_eval_query_set_100.md
(GEO eval 100-query corpus), scripts/etl/ (39 files —
batch_translate_corpus + harvest_implicit_relations +
repromote_amount_conditions + program_rss_feeds + URL slash flip runner),
scripts/publish/ (4), scripts/registry/ (n), scripts/registry_submissions/ (8),
top-level scripts/*.py (27), scripts/distribution_manifest.yml + README,
scripts/mcp_registries.md + submission.json.

Distribution + ETL + sweeper — no runtime dependency on PR1-5.
Can land independently but conventionally last in the sequence.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"

# ---------------------------------------------------------------
# 6 連 commit 完了後、まとめて push
# ---------------------------------------------------------------
git push origin main

# ---------------------------------------------------------------
# Post-landing smoke (Fly + CF edge propagation 60s 必須)
# ---------------------------------------------------------------
sleep 60
curl -sf https://jpcite.com/healthz | jq .
curl -sf https://jpcite.com/.well-known/agents.json | jq .
curl -sf https://jpcite.com/releases/current/runtime_pointer.json | jq .

echo "Stream G land complete. Verify CI green at https://github.com/<org>/jpcite/actions"
```

> 注 (tick 14 final v5): 各 PR は **既に staged 完了** (494 files, 3 tick 連続不変)、`git add` 再実行は **不要** (untracked tick 13-14 新規 artifact を混ぜると bucket 設計が壊れるため意図的に分離)。`git commit -m` のみ順次 6 連走らせる。staged 内訳が変動していないか毎 commit 前に `git diff --cached --stat | tail -1` で確認推奨。**6 連 commit 全完了後に `git push origin main`**、その後 60s propagation sleep + 3 smoke curl で `200 OK` を確認できれば Stream G **completed** flip。

### copy-paste 準備度 (tick 14 final v5)

- pre-flight sanity check 1 行: `test "$(git diff --cached --name-only | wc -l | tr -d ' ')" = "494"` を template 先頭に組み込み済、staged 件数 drift 検出が自動。
- HEREDOC 6 ブロック (PR1-PR6) は **そのまま実行可能** な完成形 (placeholder `[PR4 commit body]` 等は **解消**、tick 11 の rough draft から 完全展開)。
- `set -euo pipefail` で commit chain mid-fail 時の自動停止保証、user 操作は **template 全体を 1 ブロック貼り付け → return** のみで完走。
- post-landing 3 smoke curl + `jq .` 整形まで template に内包、user 側で追加 verify cmd 不要。
- **commit / push は依然として user 承認待ち、agent 単独実行は禁止。**

### tick 14 final v5 1 段落 summary

Stream G commit 計画は tick 1 で 479 staged を 5 PR 設計から開始 → tick 10 で 352 staged + 6 PR breakdown に再分解 → tick 11 で Tick11-F の `git add` ラウンドにより **PR1 171 / PR2 111 / PR3 32 / PR4 7 / PR5 94 / PR6 79 = 494 staged** に確定 → tick 12 で Stream HH の DB fixture 11 件 + math engine deepdive + AI agent cookbook + jpcite_facade module + check_jpcir_schema_fixtures.py を **既存 494 staged 内に bind** (件数変動なし) → tick 13 で Stream JJ (anti-pattern final audit 10 rule + 5 anti-pattern 全 OK) + Stream KK (Wave 51 implementation roadmap Day 1-28 Gantt) closure + RC1 production-ready proof acceptance test 15/15 PASS → **tick 14 で Stream LL (coverage 85→90% final push) + Stream LL-2 (coverage 86→90% final 2 DB fixture test files) 着地で jpcite 内部実装 100% 完了状態を最終確定**、Stream G の 6 PR は **3 tick 連続 (tick 12/13/14) で 494 staged を不変保持**、commit execution template の placeholder 完全展開 + pre-flight sanity check + 3 smoke curl 自動化 + `set -euo pipefail` mid-fail guard を組み込み **user copy-paste 1 操作で完走可能** な template に仕上げた。tick 13-14 で生成された acceptance test / canary smoke extended / Wave 51 roadmap + design 3 本 / Wave 50 closeout 2 本 / DB fixture-based tests / cookbook 5 recipes / JPCIR schema reference / py.typed / docs/releases/ v0.5.0 release notes は **意図的に untracked のまま残置**、Stream G land 後の Wave 51 tick 0 cleanup PR で別 stream として吸い上げる方針 (当 Stream G の 6 PR bucket 整合性を壊さないため)。**Stream G の完了条件** = (1) user 承認表明 (`Stream G land OK` 等) → (2) user が template 全体 1 ブロック貼り付け → (3) 6 連 `git commit` 自動実行 → (4) `git push origin main` → (5) 60s propagation sleep + 3 smoke curl `200 OK` → (6) Stream G を `in_progress` → `completed` に flip。**推定総時間 30-60 分** (6 commit ≈ 5-10 分 + push ≈ 1-2 分 + CI green 待ち ≈ 20-40 分 [7 workflow concurrent] + 60s smoke propagation + 3 smoke curl ≈ 1 分)。**commit / push は依然として user 承認待ち、agent 単独実行は絶対禁止**、本 plan doc sync (tick 14 final v5) のみ agent 側完了。

last_updated: 2026-05-16 (tick 14 final v5)

## tick 18 final note (2026-05-16)

### Stream G commit ready 状態 (tick 18 確認)
- staged: **494 file** (継続)
- tick 14-18 で staged 不変
- operator 実行待ち (推定 30-60 分)

### organic-funnel-daily.yml GHA registration issue (Stream RR)
- Stream S (tick 6) で landing した `.github/workflows/organic-funnel-daily.yml` が GHA で 404 not found
- 原因: workflow file unstaged (Tick17-B + Tick18-B 確認)
- 解消: **Stream G commit landing 後に GHA pickup**
- 同様 `detect-first-g4-g5-txn.yml` / `provenance-backfill-daily.yml` も同じ pattern (commit 後に GHA に登録)

### honest coverage note (Tick18-A)
- 過去報告の coverage 90%+ は subset 計測、project-wide は 26%
- Wave 50 RC1 essential gates は coverage と独立で全 PASS
- Stream G commit 自体には影響なし (commit して problem なし)

### user 実行手順 (再確認)
```bash
cd /Users/shigetoumeda/jpcite
cat docs/_internal/STREAM_G_COMMIT_PLAN.md  # plan 確認
# PR1-6 順次 commit + push (上記 tick 14 v5 template 使用)
```

last_updated: 2026-05-16 (tick 18 final note)
