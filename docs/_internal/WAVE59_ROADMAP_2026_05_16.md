# Wave 59+ Roadmap & Phase 9 Plan (2026-05-16)

Comprehensive audit of Wave 50-58 deliverables plus 10 candidate Wave 59
streams + Phase 9 (drain/teardown/attestation) outline. Honest gap
audit: catalog tail is *not* fully landed, production wrapping of
outcomes is *not* started, public `/outcomes/` page is *missing*.

## 1. Audit — what is DONE vs OPEN

Cross-checked against `site/releases/rc1-p0-bootstrap/outcome_contract_catalog.json`,
`scripts/aws_credit_ops/generate_*.py`,
`docs/_internal/athena_wave55_mega_join_2026_05_16.md`, and the AWS
canary phase-by-phase memory.

### Wave-by-Wave catalog state

| Wave  | Scope                                          | Catalog range  | Status | Gap |
| ----- | ---------------------------------------------- | -------------- | ------ | --- |
| 50    | RC1 contract layer (937 files)                 | n/a            | DONE   | -   |
| 51    | dim K-S + L1/L2 + MCP 155 → 169 wrappers       | n/a            | DONE   | -   |
| 52    | hint doc only                                  | n/a            | DONE   | -   |
| 53.1  | 16 base packet generators                      | seed → ~32     | DONE   | -   |
| 53.2  | +11 packet generators                          | ~32 → ~42      | DONE   | catalog count not re-stamped |
| 53.3  | +10 cross-source generators                    | 42 → 52        | DONE (via catalog file) | catalog reflects 52 entries up to here |
| 54    | 10 cross-3-source packets                      | 52 → **62**    | DONE (catalog at 62) | - |
| 55    | 10 cross-3-source analytics packets            | claimed 52→62  | **CATALOG NOT BUMPED** | Wave 55 PRs landed packet generators + mega Athena join, but catalog JSON still ends at 62 — Wave 54/55 collapsed into the same 10 slots |
| 56-58 | 30 more (time-series / geographic / relations) | claimed 62→92  | **PENDING** | Three task IDs (#143/#144/#145) still `pending`. Generators not implemented, catalog still at 62. |

**Honest delta: catalog has 62 entries, not 92.**  Wave 55 generators
exist on disk and produce data but the public catalog file was not
re-incremented (Wave 54 already filled slots 52→62), and Waves 56-58
were never started.

### AWS canary phases

| Phase | Scope | Status |
| ----- | ----- | ------ |
| 1     | guardrail (Budgets/S3/IAM/ECR/Logs) | DONE |
| 2     | infra (2 CE / 2 queue / job def)    | DONE |
| 3     | smoke (7 succeeded)                  | DONE |
| 4     | deep + ultradeep                     | DONE |
| 5     | smart analysis (J08-J16 + packet pipelines) | DONE |
| 6     | SageMaker + EC2 GPU + Textract + CloudFront | DONE |
| 7     | 5-line hard-stop ($18.9K Budget Action) | ARMED |
| 8     | Wave 55 mega Athena + 6 GPU 20h × 6 + Wave 56-58 packet gen | **IN PROGRESS** — Athena/GPU done, Wave 56-58 generators pending |
| 9     | drain + teardown + attestation       | **NOT STARTED** |

### Production wrapping of outcomes

- **MCP tool count**: stable at **169** (`check-mcp-drift` band 130-200).
  No outcome-specific MCP wrappers added for the 62-entry catalog.
- **Top-10 outcomes**: no canonical "top 10" selection landed.
- **Public `/outcomes/` page**: **does not exist** under `site/`.
  `site/packets/sample` exists but not a catalog index.
- **x402 router**: `src/jpintel_mcp/x402_payment/` scaffold landed
  Wave 51, **not exercised** against the 62 outcomes.
- **Credit wallet**: `src/jpintel_mcp/credit_wallet/` (ledger + models)
  landed but no end-to-end paid request against an outcome.

### Documentation freshness

- `docs/_internal/athena_wave55_mega_join_2026_05_16.md` — covers Wave
  53.3 + 54 corpora (39 Glue tables); Wave 55 packets registered as
  tables but the "62 outcome" view is not stamped anywhere.
- `docs/_internal/AWS_CANARY_HARD_STOP_5_LINE_DEFENSE_2026_05_16.md` —
  current.
- `docs/_internal/AWS_CANARY_RECOVERY_PROCEDURE_2026_05_16.md` — current,
  used by Phase 9 drain.
- No Wave 56/57/58 closeout docs (intentional — those waves not started).

## 2. Wave 59+ candidate streams (10)

Ordered by value × dependency. Each stream has a single concrete
deliverable, an explicit cost band, and an explicit dependency.

### Stream 59-A: Land Wave 56-58 (catalog 62 → 92)

- **Deliverable**: 30 packet generators (time-series 10 + geographic
  10 + relationship 10) + catalog JSON bump to 92 entries + Glue
  catalog registration + Athena registration.
- **Cost**: S3 PUT + scan negligible (<$5). Athena scan adds ~$5-$15.
- **Dependencies**: AWS canary still ARMED (line 4 Lambda + line 5
  Budget Action). Must finish *before* Phase 9 teardown.
- **Why first**: This is the explicitly outstanding promise from
  Wave 55 closeout. Until catalog hits 92, "92 outcomes" is a lie.

### Stream 59-B: Outcome catalog production wrapping — top 10 MCP tools

- **Deliverable**: 10 MCP tool wrappers (one per chosen outcome) that
  hit S3-backed packet data, register in `tool_registry.py`, bumping
  MCP count 169 → 179. Selection from top-10 highest-value outcomes
  by `billable=true && cheapest_sufficient_route_required=true`.
- **Cost**: $0 AWS (registry-only); CI mypy/ruff time.
- **Dependencies**: catalog stable (Stream 59-A preferred, but 62-entry
  state is acceptable starting point).
- **Why**: This is the first time an outcome becomes *callable* by an
  agent — the bridge from "we produced packets" to "we serve packets".

### Stream 59-C: Public `/outcomes/` site catalog page

- **Deliverable**: `site/outcomes/index.html` + per-outcome HTML pages
  generated from `outcome_contract_catalog.json` + Cloudflare Pages
  deploy. Includes outcome ID, packet IDs, billable flag, sample
  packet preview link.
- **Cost**: $0 (Cloudflare Pages free tier).
- **Dependencies**: catalog file (already present at 62; 92 ideal).
- **Why**: AX 4 pillars — Access + Justifiability. Today an agent
  cannot discover what we offer without parsing the JSON.

### Stream 59-D: x402 payment end-to-end test against 5 outcomes

- **Deliverable**: 5 outcome endpoints behind x402 challenge, paid
  fixture flow (USDC on Base testnet), receipt verification, response
  return. Test in CI.
- **Cost**: USDC testnet faucet only.
- **Dependencies**: Stream 59-B (need callable wrappers first).
- **Why**: Validates the `x402` 402-protocol on real responses. We have
  scaffold + router but zero end-to-end run.

### Stream 59-E: Smithery + Glama paste-ready (Stream J close-out)

- **Deliverable**: Smithery `smithery.yaml` + Glama listing files
  emitted from the 169-tool registry, paste-ready commands documented
  in `docs/_internal/`. Stream J on the open list.
- **Cost**: $0.
- **Dependencies**: None.
- **Why**: One of the few Wave 49 organic-funnel items still listed
  `in_progress` (Stream J).

### Stream 59-F: Phase 9 drain + teardown + attestation

- **Deliverable**: graceful drain script (disable Step Functions
  schedule first, then drain Batch queues with N-minute cutoff, then
  detach Budget Action, then run AWS_CANARY_RECOVERY procedure),
  cost ledger frozen, `emit_canary_attestation.py` runs end-of-canary,
  $X final burn stamped.
- **Cost**: nothing added — pure ramp-down.
- **Dependencies**: Wave 56-58 done (Stream 59-A) so we don't tear
  down with promise unfulfilled. Hard-stop ARMED protects us during
  drain.
- **Why**: We are at Phase 8 with no defined exit. Phase 9 is the
  contractual end-state.

### Stream 59-G: Outcome → packet → Athena query crosswalk doc

- **Deliverable**: `docs/_internal/outcome_packet_athena_crosswalk_<date>.md`
  mapping 62 (→92) outcomes to packet IDs to S3 prefix to Glue table to
  canonical Athena query. Enables agents to plan workloads without
  reverse-engineering JSON files.
- **Cost**: $0.
- **Dependencies**: catalog stable.
- **Why**: AX Layer 5 — Justifiability. Today the agent has to
  reverse-engineer the relationship.

### Stream 59-H: Outcome verifier — assertion-level evidence checks

- **Deliverable**: per-outcome `assertions[]` list in catalog, plus
  Athena-backed verifier that runs once per ETL window and produces a
  signed evidence pass/fail packet. Stops "outcome exists in catalog
  but data does not back the claim".
- **Cost**: Athena scan ~$1-$5 per full sweep.
- **Dependencies**: Stream 59-G (need crosswalk before assertions).
- **Why**: We have the explainable_fact module (dim O) and time_machine
  (dim Q) but no canonical proof-of-correctness for outcomes.

### Stream 59-I: Credit Wallet end-to-end smoke against 1 outcome

- **Deliverable**: real `am_credit_wallet` row + paid request → tool
  invocation → ledger increment → 402 response on insufficient credit.
  Done as fixture test, no real money.
- **Cost**: $0.
- **Dependencies**: Stream 59-B (callable outcomes).
- **Why**: Wallet ledger + models exist; never been exercised against an
  outcome request.

### Stream 59-J: Wave 50-58 closeout + memory consolidation

- **Deliverable**: single SOT doc `docs/_internal/WAVE_50_58_CLOSEOUT_<date>.md`
  that supersedes 30+ wave-specific docs, with an INDEX entry and
  matching memory `project_jpcite_wave_50_58_closeout`. Existing wave
  docs banner-deprecated, not deleted (destruction-free).
- **Cost**: $0.
- **Dependencies**: Stream 59-A + Stream 59-F (so closeout is final).
- **Why**: 30+ Wave 5x docs in `docs/_internal/` is structural debt.
  One closeout per epoch.

## 3. Ordering + parallelism

```
[A] Land 56-58 ────┐
                   ├─► [G] crosswalk ─► [H] verifier ─┐
[E] Smithery (parallel)                                │
                                                       ├─► [J] closeout
[B] top-10 MCP ─► [C] /outcomes/ page ─► [D] x402 ─────┤
              └─► [I] wallet smoke ─────────────────────┘
                                                       │
                              [F] Phase 9 ─────────────┘
```

- Streams A + E run in parallel (independent).
- Stream B blocks D + I; both can run in parallel once B lands.
- Stream G blocks H.
- Stream F (Phase 9) waits for A + B/C/D so we don't tear down before
  the outcome contract is fully callable + paid.
- Stream J consolidates everything as the final write.

## 4. Cost band summary

| Stream | Cost band                              |
| ------ | -------------------------------------- |
| 59-A   | <$20 (S3 PUT + Athena registration)    |
| 59-B   | $0                                     |
| 59-C   | $0 (Cloudflare Pages free)             |
| 59-D   | $0 (Base testnet faucet)               |
| 59-E   | $0                                     |
| 59-F   | $0 (ramp-down)                         |
| 59-G   | $0                                     |
| 59-H   | $1-$5 per sweep (Athena)               |
| 59-I   | $0                                     |
| 59-J   | $0                                     |
| **Total**  | **<$30 AWS marginal** (Phase 8 ramp does the heavy spend; Wave 59 is value extraction, not burn) |

## 5. Phase 9 plan (folds into Stream 59-F)

Phase 9 is the *end of the AWS canary*. It runs *after* Wave 56-58
(Stream 59-A) lands but *before* Stream 59-J closeout.

### Phase 9 step list

1. **Drain — disable orchestration first.**
   - EventBridge schedule → DISABLED (already default).
   - Step Functions state machine → DISABLED.
   - GHA workflows touching AWS → manual-only.
2. **Drain — queue cutoff with N-minute grace.**
   - Stop accepting new jobs (queue → DISABLED).
   - Let in-flight jobs finish or hit their per-job timeout.
   - Cancel anything in `RUNNABLE` immediately.
3. **Cost freeze — final stamp.**
   - Snapshot Cost Explorer at drain start (T-0) and again at T+12h.
   - Stamp final $burn in `docs/_internal/AWS_CANARY_RUN_2026_05_16.md`.
4. **Recovery — execute existing procedure.**
   - Run `docs/_internal/AWS_CANARY_RECOVERY_PROCEDURE_2026_05_16.md`
     in order (CE disable → queue delete → job def deregister → S3
     lifecycle accelerate → Glue catalog drop → CW alarm disable →
     Budget Action detach → SNS topic delete → IAM canary roles
     detach).
   - Each step gated by `--unlock-live-aws-commands` 1-phase-1-opt-in,
     same gate as Phase 1-8.
5. **Attestation — emit_canary_attestation.**
   - Task #108 (`emit_canary_attestation.py + Lambda + tests`) is
     currently `in_progress`; Phase 9 forces completion.
   - Lambda + S3 evidence upload + GHA artifact attestation +
     sha256 manifest stamped against Sigstore (offline-OK fallback).
6. **5-line defense — keep ARMED during drain.**
   - Lines 1-5 remain ARMED for the duration of drain. They only get
     disarmed in step 4 (recovery), *after* burn is confirmed to be
     decreasing.
7. **Closeout — feeds Stream 59-J.**
   - Single doc lists final $burn, peak $burn, total packet count,
     total Athena scan TB, total GPU-hours, link to attestation
     evidence.

### Phase 9 gate

- Final burn ≤ $19,490 (absolute ceiling) — **must remain true**
  through entire drain. The 5-line defense protects this.
- All Phase 1-8 artifacts present in S3 + locally + memory.
- Attestation manifest sha256 stamped, recorded in
  `release_capsule_manifest.json`, and a separate copy in
  `site/releases/`.

### Phase 9 exit criterion

- Cost Explorer 12h rolling avg < $5/day (Phase 0 baseline reached).
- All Batch queues + CEs deleted or DISABLED.
- All canary-tagged IAM roles detached from operator principal.
- Attestation manifest signed + uploaded + referenced.
- Memory `project_jpcite_canary_burn_phase_by_phase_2026_05_16.md`
  updated with Phase 9 = DONE + final $burn.

### Phase 9 DRY_RUN corrections (2026-05-16 verified)

DRY_RUN executed against profile `bookyou-recovery`
(see `docs/_internal/phase9_dry_run_2026_05_16.md` for full step-by-step
results). 6/7 steps verified — the corrections below close the gaps:

- **Step 1 schedule discovery**: explicitly query both
  `aws scheduler list-schedules --name-prefix jpcite` (EventBridge Scheduler
  API) **and** `aws events list-rules --name-prefix jpcite` (EventBridge Rules
  API), since the canary schedule may live in either namespace. DRY_RUN
  showed Scheduler API empty; Rules API has not been independently confirmed.
- **Step 3 cost freeze**: call `aws ce get-cost-and-usage --region us-east-1
  ...` directly with explicit region pin, rather than depending on
  `burn_target.py` MTD aggregate (which reads $0 under cross-region token
  default).
- **Step 5 attestation**: prepend "deploy Lambda first
  (`bash scripts/aws_credit_ops/deploy_canary_attestation_lambda.sh`) before
  invoking attestation". Alternatively, allow CLI fallback via
  `.venv/bin/python scripts/aws_credit_ops/emit_canary_attestation.py` so
  Phase 9 is not blocked by task #108.

## 6. Out of scope

- LLM-side enrichment of outcomes (banned by
  `feedback_autonomath_no_api_use` / `feedback_no_operator_llm_api`).
- New AWS infra primitives beyond what already exists.
- Catalog growth beyond 92 (Wave 60+ territory).
- Cost ramp re-enablement after Phase 9 drain (separate decision).

## Why this roadmap exists

Phase 8 has no explicit end. Without writing down the exit, the canary
keeps burning (currently the 6 × 20h GPU jobs and continuous burn
monitor). Wave 59 is the *value-extraction wave* — it converts the
166K+ packet corpus + 39+ Glue tables + $XK burn into 10 callable
MCP outcomes + a public catalog page + paid-flow validation, then
hands off to Phase 9 for graceful teardown.

last_updated: 2026-05-16
