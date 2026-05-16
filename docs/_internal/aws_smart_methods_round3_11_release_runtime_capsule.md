# AWS smart methods round 3 review 11/20: release runtime capsule

Date: 2026-05-15  
Owner: Round3 additional smart-method review 11/20  
Scope: Release Capsule, Dual Pointer Runtime, Capability Matrix Manifest, Agent Surface Compiler, Hot/Cold Static DB Split, production runtime, asset bundle, rollback, runtime lightweighting, zero-AWS posture  
AWS execution: not performed. No AWS CLI/API/resource operation was run.  
File output: this document only.

## 1. Executive conclusion

The existing plan is directionally correct:

- AWS is a temporary artifact factory.
- Production must not depend on AWS runtime services.
- Production should activate verified Release Capsules.
- Rollback should be pointer-based, not AWS restore or full redeploy.
- Agent-facing surfaces must be generated from one source of truth.
- Static runtime data must be small enough to serve cheaply and safely.
- Zero-bill posture must be proven, not assumed.

The smarter method is to make Release Capsule a first-class runtime product, not just a bundle of generated files.

Recommended upgrade:

> Treat production as a small `Capsule Runtime` that reads immutable, content-addressed Release Capsules through controlled pointers, exposes only currently valid capabilities through a Capability Matrix, and derives every agent-facing surface from the same capsule manifest.

This adds four important properties:

1. Production can be deployed early and stay stable while AWS keeps generating assets.
2. Capsule activation can be validated, partially exposed, rolled back, or expired without code changes.
3. AI agents always see a coherent view of price, packet availability, proof pages, MCP/OpenAPI tools, no-hit language, and billing state.
4. AWS can be fully torn down after export because runtime, rollback, and proof assets live outside AWS.

## 2. Current plan assumptions to preserve

Do not change these invariants:

- `runtime.aws_dependency.allowed=false` in production.
- AWS outputs are not production source of truth.
- S3 final archive is not allowed by default because it violates zero-bill.
- Rollback must not require AWS access.
- Raw CSV is never part of public Release Capsule assets.
- Request-time LLM is not allowed for factual claims.
- No-hit remains `no_hit_not_absence`.
- `agent_routing_decision` remains a free control, not a paid packet.
- Production should expose RC1 early with a small paid surface.
- Release Capsule activation requires production smoke without AWS.

## 3. Main added smart method: Capsule Runtime

### 3.1 Problem

The existing Release Capsule idea is strong, but it can still become a passive artifact archive. If the runtime only "serves files from a bundle", several problems remain:

- Capability availability can drift from OpenAPI/MCP/proof pages.
- A data bundle can be compatible with proof pages but incompatible with API code.
- One bad packet asset can force rollback of the whole release.
- Staleness and no-hit lease expiry may require a full deploy even when only capability state changed.
- Zero-AWS posture can be declared while hidden S3 URLs or AWS SDK imports remain.
- Large static assets can slow production and make rollback heavy.

### 3.2 Upgrade

Introduce `Capsule Runtime` as a minimal production layer:

```text
Production code
  -> active_runtime_pointer.json
  -> active_contract_pointer.json
  -> active_capability_pointer.json
  -> active_capsule_manifest.json
  -> hot_static_db_manifest.json
  -> agent surfaces generated from capsule
```

The runtime does not query AWS, does not rebuild evidence, and does not call LLMs for facts. It only:

1. loads active pointers,
2. verifies capsule compatibility,
3. serves hot assets,
4. gates capabilities,
5. returns free preview and paid packet responses,
6. exposes agent discovery surfaces,
7. records privacy-safe runtime telemetry,
8. supports pointer rollback.

### 3.3 Why this is smarter

The service becomes less like "deploy data files" and more like "activate a verified product capsule".

This makes production safer because every visible capability is derived from the active capsule state, not from scattered config, manually edited docs, and stale generated files.

## 4. Release Capsule v2

### 4.1 Capsule definition

A `Release Capsule` is an immutable, content-addressed, production-eligible bundle.

It should contain only policy-approved, runtime-safe, externally exported assets.

It must never contain:

- AWS-only paths as runtime dependencies
- raw source archives
- raw screenshots intended only for audit
- raw DOM/HAR body dumps
- raw or real user CSV data
- private overlay data
- unresolved terms/robots assets
- claim outputs without `source_receipts[]`
- no-hit outputs without no-hit scope and lease
- request-time LLM factual claims

### 4.2 Capsule manifest

Minimum manifest:

```json
{
  "capsule_id": "rc_20260515_001",
  "capsule_type": "production_release",
  "created_at": "2026-05-15T00:00:00Z",
  "schema_version": "release_capsule.v2",
  "contract_pointer": "contract_20260515_001",
  "capability_matrix_id": "capability_matrix_20260515_001",
  "hot_static_db_manifest": "hot_static_db_manifest.json",
  "cold_evidence_manifest": "cold_evidence_manifest.json",
  "agent_surface_manifest": "agent_surface_manifest.json",
  "rollback_manifest": "rollback_manifest.json",
  "zero_aws_posture_manifest": "zero_aws_posture_manifest.json",
  "checksums": {
    "algorithm": "sha256",
    "manifest_hash": "sha256:..."
  },
  "activation_gates": {
    "schema_compatibility": "pass",
    "surface_parity": "pass",
    "policy_decision_firewall": "pass",
    "production_smoke_without_aws": "pass",
    "aws_dependency_scan": "pass",
    "rollback_ready": "pass"
  },
  "runtime_requirements": {
    "aws_dependency_allowed": false,
    "request_time_llm_allowed_for_facts": false,
    "raw_csv_allowed": false,
    "pointer_rollback_allowed": true
  }
}
```

### 4.3 Capsule asset classes

Use explicit asset classes:

| Class | Runtime visibility | Purpose | AWS allowed after teardown |
| --- | --- | --- | --- |
| `T0_RUNTIME_HOT` | production reads directly | catalog, price, capability matrix, small indexes | no |
| `T1_AGENT_SURFACE` | public | llms, well-known, OpenAPI, MCP, proof pages, examples | no |
| `T2_PAID_PACKET_TEMPLATE` | runtime reads after approval | packet templates, evidence lens refs | no |
| `T3_COLD_EVIDENCE_LENS` | runtime may lazy-load, not fully public | minimal proof-carrying evidence views | no |
| `T4_AUDIT_ARCHIVE_LOCAL` | not production | full audit bundle outside AWS, local/non-AWS archive | no |
| `T5_REJECTED_OR_QUARANTINED` | not production | failed/blocked assets and reasons | no |

Important: `T4` can exist outside AWS for internal audit, but production should not require it.

## 5. Dual Pointer Runtime v2

### 5.1 Existing idea

The plan already separates contract pointer and asset bundle pointer.

### 5.2 Smarter upgrade

Use controlled pointers for different blast-radius domains:

```json
{
  "runtime_pointer_version": "dual_pointer_runtime.v2",
  "active_contract": "contract_20260515_001",
  "active_capsule": "rc_20260515_001",
  "active_capability_matrix": "capability_matrix_20260515_001",
  "active_agent_surface": "agent_surface_20260515_001",
  "active_hot_db": "hot_db_20260515_001",
  "rollback_target": "rc_20260514_003",
  "emergency_flags": {
    "paid_execution_enabled": true,
    "preview_enabled": true,
    "agent_discovery_enabled": true,
    "new_capability_activation_locked": false
  }
}
```

This is technically more than dual pointer, but keep the external name `Dual Pointer Runtime` to avoid terminology sprawl. Internally, it is a pointer set.

### 5.3 Pointer rules

Pointer changes must be atomic.

Activation must fail closed if:

- contract pointer and capsule contract hash do not match
- capability matrix refers to packet ids absent from capsule
- agent surface manifest was not generated from the same capsule
- hot DB manifest references missing files
- proof pages reference inactive capsule ids
- rollback target is missing or incompatible
- AWS dependency scan fails

### 5.4 Rollback scopes

Rollback should not always be whole-capsule rollback.

Use lane-level rollback:

| Rollback scope | Used when | Pointer action |
| --- | --- | --- |
| `capability_only` | packet should be hidden but assets are fine | switch capability matrix |
| `agent_surface_only` | llms/well-known/OpenAPI/MCP/proof mismatch | switch agent surface pointer |
| `hot_db_only` | preview/search index bad | switch hot DB pointer |
| `capsule_full` | data/contract/security issue | switch active capsule |
| `paid_disable` | billing or paid output risk | flag paid execution off |
| `discovery_disable` | agent-facing surface causes wrong recommendations | flag discovery or affected capability off |

This reduces downtime and makes rollback fast without AWS.

## 6. Capability Matrix Manifest v2

### 6.1 Role

The Capability Matrix is the runtime and agent contract for what jpcite can currently recommend, preview, sell, execute, or block.

It should be generated from the capsule, not edited manually.

### 6.2 Required fields

```json
{
  "capability_matrix_id": "capability_matrix_20260515_001",
  "capsule_id": "rc_20260515_001",
  "generated_from": {
    "contract_hash": "sha256:...",
    "pricing_hash": "sha256:...",
    "policy_hash": "sha256:...",
    "evidence_lens_hash": "sha256:..."
  },
  "capabilities": [
    {
      "capability_id": "company_public_baseline",
      "outcome_contract_id": "company_public_baseline.v1",
      "packet_ids": ["company_public_baseline"],
      "state": "recommendable",
      "preview_state": "enabled",
      "paid_execution_state": "enabled_limited",
      "billing_state": "cap_required",
      "agent_recommendation_state": "allowed",
      "public_proof_state": "available",
      "known_gap_state": "must_disclose",
      "no_hit_policy": "no_hit_not_absence",
      "freshness": {
        "source_lease_state": "valid",
        "expires_at": "2026-06-15T00:00:00Z"
      },
      "blockers": [],
      "fallback_capability_id": "source_receipt_ledger"
    }
  ]
}
```

### 6.3 Capability states

Use a fixed enum:

- `recommendable`
- `preview_only`
- `paid_disabled`
- `blocked_policy`
- `blocked_stale`
- `blocked_terms`
- `blocked_security`
- `blocked_billing`
- `experimental_internal`

Do not expose ambiguous states like `available` without recommendation and billing meaning.

### 6.4 Capability lease

Some capabilities depend on fresh sources, no-hit leases, or source terms.

Add `capability_lease`.

```json
{
  "capability_id": "invoice_vendor_public_check",
  "lease_type": "source_freshness_and_no_hit_scope",
  "valid_from": "2026-05-15T00:00:00Z",
  "expires_at": "2026-05-22T00:00:00Z",
  "on_expiry": "downgrade_to_preview_only"
}
```

This avoids a full code deploy when capability freshness expires. The runtime can downgrade recommendation state by pointer/capability update.

## 7. Agent Surface Compiler v2

### 7.1 Role

The Agent Surface Compiler must generate every agent-facing surface from the active Release Capsule:

- `llms.txt`
- `.well-known` decision bundle
- MCP tool manifest
- agent-safe OpenAPI
- full OpenAPI if needed
- proof pages
- pricing pages
- packet examples
- no-hit language pack
- known-gap explanations
- agent recommendation cards
- decision object examples
- changelog
- capability matrix public subset

### 7.2 Surface parity hash mesh

Each generated surface should carry the same source hashes:

```json
{
  "surface_id": "mcp_manifest",
  "capsule_id": "rc_20260515_001",
  "contract_hash": "sha256:...",
  "capability_matrix_hash": "sha256:...",
  "pricing_hash": "sha256:...",
  "no_hit_policy_hash": "sha256:...",
  "generated_at": "2026-05-15T00:00:00Z"
}
```

Activation blocker:

> If `llms.txt`, `.well-known`, MCP, OpenAPI, proof pages, and pricing page do not share the same capsule and capability hashes, the capsule cannot be activated.

### 7.3 Agent-facing public subset

Do not expose the full internal Capability Matrix.

Compile an agent-safe subset:

```json
{
  "service": "jpcite",
  "capsule_id": "rc_20260515_001",
  "capabilities": [
    {
      "task": "check a Japanese company using public official sources",
      "recommended_route": "company_public_baseline",
      "preview_tool": "jpcite_preview_cost",
      "execute_tool": "jpcite_execute_packet",
      "price_policy": "cap_required",
      "limitations": [
        "no-hit is not proof of absence",
        "known gaps are disclosed before purchase"
      ]
    }
  ]
}
```

## 8. Hot/Cold Static DB Split v2

### 8.1 Existing idea

The current plan already separates runtime hot data from cold audit/proof assets.

### 8.2 Smarter split

Use four runtime layers:

| Layer | Purpose | Size target | Runtime use |
| --- | --- | --- | --- |
| `H0_POINTERS` | active pointers, flags, hashes | tiny | read on boot/request |
| `H1_DECISION_INDEX` | packet catalog, capability matrix, pricing, routes | small | free preview / agent discovery |
| `H2_OUTPUT_BLUEPRINTS` | packet templates, allowed fields, known gap schema | medium | paid execution |
| `C1_EVIDENCE_LENSES` | minimal evidence views per packet/source | bounded | proof, paid output |
| `C2_AUDIT_ARCHIVE` | full audit/export bundle | large | not production runtime |

### 8.3 Hot DB contents

Hot DB should contain:

- outcome contract ids
- packet ids
- capability states
- price/cap information
- proof page route map
- source family coverage summary
- no-hit policy summary
- stale/block status
- checksums for cold lens references

Hot DB should not contain:

- raw screenshots
- full DOM/HAR bodies
- full OCR text
- full source archive
- private CSV-derived facts
- sensitive logs
- AWS paths

### 8.4 Cold evidence lens

Cold evidence lens should be minimal:

- source receipt id
- claim refs
- temporal envelope
- no-hit lease
- known gaps
- source family
- content hash
- screenshot receipt metadata if allowed
- proof minimizer output

It should not be a full source archive.

## 9. Release Capsule activation gates

Add these gates before production activation:

| Gate | Blocks what |
| --- | --- |
| `capsule_schema_gate` | malformed manifest, missing pointers |
| `contract_compatibility_gate` | runtime cannot read capsule contract |
| `capability_matrix_gate` | exposed capabilities not supported by assets |
| `agent_surface_parity_gate` | llms/well-known/MCP/OpenAPI/proof drift |
| `policy_decision_firewall_gate` | private, terms, CSV, screenshot, no-hit issues |
| `hot_cold_boundary_gate` | cold/audit assets leaked into hot runtime |
| `aws_dependency_firewall_gate` | S3/AWS SDK/AWS URL/runtime env dependency |
| `rollback_readiness_gate` | rollback target missing or incompatible |
| `production_smoke_without_aws_gate` | service fails without AWS access |
| `zero_aws_posture_gate` | exported assets and teardown evidence missing |

These gates are better than only testing pages because they validate the release object itself.

## 10. Runtime lightweighting

### 10.1 Static-first serve model

Production should serve most agent and proof surfaces as static assets generated by Agent Surface Compiler.

Dynamic runtime should be limited to:

- preview decision object generation
- scoped cap token checks
- paid packet execution against capsule assets
- capability gating
- billing metadata
- error/no-hit/known-gap formatting

### 10.2 Avoid runtime graph queries

Runtime must not query the full Official Evidence Ledger.

Allowed:

- read static Evidence Lens
- read hot decision index
- read packet blueprint
- return compiled source receipts/claim refs

Not allowed:

- graph traversal against AWS/OpenSearch/Neptune/etc.
- source fetching
- OCR
- Playwright capture
- raw source parsing
- LLM factual synthesis

### 10.3 Evidence Capsule Cache

For common facts, create a small cache:

```text
evidence_capsule_cache/
  company_identity/
  invoice_registration/
  source_profile/
  public_notice_status/
```

The cache should store reusable evidence slices with checksums and expiry. It should reduce paid output latency without becoming a truth DB.

## 11. Rollback model

### 11.1 Rollback as pointer switch

Rollback action:

```text
active_capsule = previous_capsule_id
active_capability_matrix = previous_capability_matrix_id
active_agent_surface = previous_agent_surface_id
```

No AWS access.
No S3 restore.
No refetch.
No rebuild.

### 11.2 Forward-disable before rollback

For high-risk paid features, first disable capability:

```json
{
  "capability_id": "grant_candidate_shortlist",
  "state": "paid_disabled",
  "reason": "capability_hotfix",
  "preview_state": "enabled",
  "paid_execution_state": "disabled"
}
```

This is faster than full rollback and keeps free discovery alive.

### 11.3 Rollback bundle retention

Keep at least:

- current active capsule
- previous production capsule
- last known good RC1 capsule

All must be outside AWS.

If these are not outside AWS, teardown is blocked.

## 12. Zero-AWS posture

### 12.1 Definition

Zero-AWS posture means:

- production can boot without AWS credentials
- production can serve public pages without AWS
- production can run preview without AWS
- production can execute enabled packet types without AWS if their assets are in the active capsule
- rollback can happen without AWS
- agent surfaces contain no AWS URLs
- static DB manifests contain no AWS URLs
- audit references do not require AWS
- AWS resources used for the credit run have been deleted

### 12.2 Zero-AWS posture manifest

Add manifest:

```json
{
  "zero_aws_posture_manifest_id": "zero_aws_20260515_001",
  "capsule_id": "rc_20260515_001",
  "aws_dependency_scan": {
    "aws_sdk_imports": 0,
    "s3_urls": 0,
    "cloudfront_aws_origin_required": false,
    "aws_env_required": false
  },
  "external_export": {
    "release_capsule_exported": true,
    "rollback_capsule_exported": true,
    "checksums_verified": true
  },
  "production_smoke_without_aws": {
    "public_pages": "pass",
    "llms": "pass",
    "well_known": "pass",
    "mcp_manifest": "pass",
    "openapi": "pass",
    "preview": "pass",
    "paid_limited": "pass"
  },
  "teardown_dependency": {
    "s3_required_after_teardown": false,
    "batch_required_after_teardown": false,
    "opensearch_required_after_teardown": false,
    "glue_required_after_teardown": false,
    "athena_required_after_teardown": false
  }
}
```

### 12.3 Important contradiction

Do not schedule post-teardown checks using AWS Lambda/EventBridge if the goal is no further AWS billing.

Post-teardown checks should be:

- local CLI checks when needed,
- billing console checks if manually performed,
- non-AWS monitoring if already part of existing production,
- not a new AWS recurring workload.

## 13. Production operation model

### 13.1 Runtime states

Use explicit states:

| State | Meaning |
| --- | --- |
| `inactive` | capsule exists but not visible |
| `shadow` | runtime can load it, agents/users cannot see it |
| `canary_public` | public proof/discovery subset visible |
| `preview_enabled` | free preview enabled |
| `paid_limited` | paid execution enabled with low caps |
| `active` | normal production capsule |
| `degraded` | specific capabilities disabled |
| `rolled_back` | no longer active |
| `retired` | retained only for audit/rollback history |

### 13.2 Activation lanes

Capsule activation should be progressive:

1. `shadow`
2. `canary_public`
3. `preview_enabled`
4. `paid_limited`
5. `active`

This is not a slower sequence. It allows early production while containing risk.

### 13.3 Runtime telemetry

Collect privacy-preserving aggregate events:

- preview requested
- capability selected
- capability blocked reason
- paid cap accepted
- paid packet completed
- no-hit returned
- known gap disclosed
- agent surface fetched
- rollback/disable event

Do not log:

- raw CSV
- private CSV-derived facts
- sensitive company/user input beyond safe identifiers
- full packet payloads
- raw source text
- screenshots
- auth headers/cookies

## 14. Asset bundle layout

Recommended layout:

```text
release_capsules/
  rc_20260515_001/
    capsule_manifest.json
    runtime/
      active_pointer_candidate.json
      hot_static_db_manifest.json
      capability_matrix.json
      pricing_matrix.json
      outcome_contract_catalog.json
    surfaces/
      llms.txt
      well-known/
        jpcite-decision-bundle.json
      openapi/
        agent-safe-openapi.json
      mcp/
        mcp-manifest.json
      proof_pages/
      examples/
      no_hit_language_pack.json
      known_gap_language_pack.json
    packet_blueprints/
      company_public_baseline.json
      source_receipt_ledger.json
      evidence_answer.json
    evidence_lenses/
      company_public_baseline.jsonl
      source_receipt_ledger.jsonl
      evidence_answer.jsonl
    gates/
      policy_decision_firewall_report.json
      surface_parity_report.json
      aws_dependency_firewall_report.json
      production_smoke_without_aws.json
      rollback_readiness_report.json
    rollback/
      rollback_manifest.json
    attestations/
      zero_aws_posture_manifest.json
      external_export_manifest.json
      checksum_manifest.json
```

## 15. Merge diff into master execution plan

### 15.1 Section to add under smart methods

Add a subsection similar to:

```text
Adopt Capsule Runtime as the production serve model.
Production activates immutable Release Capsules through pointer sets and reads only
policy-approved hot assets and minimal Evidence Lenses. Runtime must not query AWS,
the full evidence graph, source sites, Playwright, OCR, or request-time factual LLMs.
```

### 15.2 Replace or refine existing terms

| Existing wording | Replace / refine with |
| --- | --- |
| `Release Capsule` | `Release Capsule v2: immutable, content-addressed activation unit` |
| `Dual Pointer Runtime` | keep name, define as controlled pointer set |
| `Capability Matrix Manifest` | generated runtime/agent capability contract |
| `Agent Surface Compiler` | single compiler for llms, well-known, MCP, OpenAPI, proof, pricing, examples |
| `Hot/Cold Static DB Split` | H0/H1/H2/C1/C2 layered split |
| `production smoke without AWS` | gate inside zero-AWS posture manifest |
| `rollback assets outside AWS` | current, previous, and last-known-good capsules outside AWS |

### 15.3 Add P0 implementation items

Add these implementation items before full AWS import:

| ID | Item | Output |
| --- | --- | --- |
| RC-P0-01 | Release Capsule v2 JSON schema | `release_capsule.schema.json` |
| RC-P0-02 | Pointer set schema | `runtime_pointer.schema.json` |
| RC-P0-03 | Capability Matrix v2 schema | `capability_matrix.schema.json` |
| RC-P0-04 | Agent Surface Compiler contract | generated surfaces + hash mesh |
| RC-P0-05 | Hot DB manifest schema | `hot_static_db_manifest.schema.json` |
| RC-P0-06 | Evidence Lens boundary check | no cold/archive leakage |
| RC-P0-07 | AWS dependency firewall | S3/AWS URL/SDK/env scanner |
| RC-P0-08 | Capsule activation gate runner | activation report |
| RC-P0-09 | Pointer rollback command | rollback without AWS |
| RC-P0-10 | Zero-AWS posture manifest | proof before teardown |

### 15.4 Adjust execution order without changing strategy

Do not reorder the entire plan. Insert these into the existing flow:

```text
contract freeze
  -> JPCIR schemas
  -> Release Capsule v2 schemas
  -> Capability Matrix v2
  -> Agent Surface Compiler minimal
  -> static proof renderer
  -> AWS canary import
  -> capsule candidate build
  -> capsule gates
  -> RC1 activation via pointer
  -> AWS full artifact factory continues
  -> RC2/RC3 capsule candidates
  -> external export
  -> zero-AWS posture gate
  -> zero-bill teardown
```

This preserves the existing "RC1 early production, AWS continues in parallel" strategy.

## 16. Contradiction review

### 16.1 Capsule Runtime vs zero-bill

Status: PASS.

Capsule Runtime strengthens zero-bill because production only reads exported, non-AWS assets.

Blocker:

- Any runtime path requiring S3, Athena, Glue, OpenSearch, Batch, Lambda, CloudWatch, or AWS credentials after teardown.

Resolution:

- `aws_dependency_firewall_gate`
- `zero_aws_posture_manifest`
- `production_smoke_without_aws`

### 16.2 Release Capsule vs full Evidence Graph

Status: PASS with boundary.

Release Capsule must not contain the full Official Evidence Ledger. It contains only compiled Evidence Lenses.

Blocker:

- capsule contains full graph, full archive, raw screenshot corpus, or raw source bodies.

Resolution:

- Hot/Cold boundary gate.
- Evidence Lens minimality gate.
- Public proof minimizer.

### 16.3 Pointer rollback vs generated surfaces

Status: PASS if surface pointer is included.

If proof pages or MCP manifest are generated separately from data bundle, rollback can drift.

Resolution:

- Agent Surface Compiler generates all surfaces from the capsule.
- Surface parity hash mesh is activation blocker.
- Rollback pointer includes agent surface pointer.

### 16.4 Capability Matrix vs paid billing

Status: PASS if billing state is explicit.

Capability Matrix must include billing state and cap requirements, not just feature availability.

Resolution:

- `billing_state`
- `paid_execution_state`
- `preview_state`
- `agent_recommendation_state`

### 16.5 Capability expiry vs production stability

Status: PASS with capability lease.

Stale source or no-hit lease expiry should not require immediate deploy.

Resolution:

- `capability_lease`
- downgrade to `preview_only` or `blocked_stale`
- agent surfaces regenerated or public capability subset updated from active matrix

### 16.6 Hot/Cold split vs user value

Status: PASS.

Hot runtime remains fast while cold Evidence Lens preserves proof.

Risk:

- If hot DB is too minimal, AI agents cannot decide what to recommend.

Resolution:

- include decision-level coverage summaries and known-gap summaries in H1.
- keep claim details in C1.

### 16.7 Zero-AWS posture vs rollback retention

Status: PASS only if rollback capsules are outside AWS.

Resolution:

- store current, previous, and last-known-good capsules outside AWS before teardown.
- teardown blocked if rollback bundle exists only in S3.

### 16.8 Runtime telemetry vs privacy

Status: PASS with aggregate-only telemetry.

Blocker:

- logging raw packet inputs, CSV content, source text, screenshot text, or user private facts.

Resolution:

- telemetry schema allowlist.
- privacy leak scanner.
- aggregate counters only for product decisions.

## 17. What not to adopt

Reject these:

- production graph database as runtime dependency
- permanent S3 archive to simplify rollback
- CloudFront/S3 origin that must remain after zero-bill teardown unless explicitly accepted as non-zero-bill
- runtime OpenSearch/Athena/Glue queries
- request-time factual LLM generation
- full screenshot archive in public proof pages
- generic "trust score" surfaced to agents
- manual editing of MCP/OpenAPI/proof/pricing after capsule compile
- rollback requiring AWS restore
- post-teardown recurring AWS monitors

## 18. Final recommendation

Adopt the Round3 release/runtime capsule upgrade.

The most important change is:

> Production should not merely host generated assets. It should run a small Capsule Runtime that activates verified Release Capsules through pointer sets, serves a generated Capability Matrix and agent surfaces, keeps hot assets tiny, loads only minimal Evidence Lenses, and proves zero-AWS posture before AWS teardown.

This is a smarter method than the current plan because it turns release, rollback, agent discovery, billing exposure, data freshness, and zero-bill safety into one controlled runtime contract.

## 19. Merge-ready summary

Merge the following into the master plan:

```text
Release/runtime will use Capsule Runtime.
Each production release is an immutable Release Capsule v2 with manifest,
capability matrix, agent surface manifest, hot DB manifest, evidence lens
manifest, rollback manifest, and zero-AWS posture manifest.

Production reads active pointer sets, not AWS resources.
Activation is blocked unless contract compatibility, capability matrix,
surface parity, policy firewall, hot/cold boundary, AWS dependency firewall,
rollback readiness, and production smoke without AWS all pass.

Capability Matrix v2 is the source of truth for whether an AI agent may
recommend, preview, sell, execute, or block each packet/outcome contract.

Agent Surface Compiler generates llms.txt, .well-known, MCP, OpenAPI, proof
pages, pricing, examples, no-hit language, known-gap language, and public
capability subset from the same capsule.

Rollback is pointer-based and can be scoped to capability, agent surface,
hot DB, or full capsule. It must never require AWS.

Zero-bill teardown is blocked until current, previous, and last-known-good
capsules are exported outside AWS, checksums pass, production smoke without
AWS passes, and runtime contains no AWS dependencies or URLs.
```

This has no contradiction with the current strategy. It strengthens the existing plan.
