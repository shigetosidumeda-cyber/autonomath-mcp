# AWS smart methods round 2 integrated review

Date: 2026-05-15  
Status: integrated method review, no AWS execution  
Input: `aws_smart_methods_round2_01-06`, master plan, final 12-agent smart-method review

## 0. Verdict

Round 2 did produce additional smart methods beyond the previous plan.

The new ideas are not "more sources" or "different order." The better design is to make jpcite more like a set of compilers, capsules, and control systems:

- product economics compiler
- official evidence knowledge graph
- proof-quality compiler
- AWS artifact factory kernel
- release capsule runtime
- policy/trust firewall

No fatal contradiction was found if these are kept within the existing constraints:

- no request-time LLM for facts
- no real private CSV in AWS
- no Playwright bypass
- no exact `USD 19,493.94` target
- production must not depend on AWS
- zero-bill teardown remains mandatory

## 1. Adopted product methods

Adopt:

- `agent_task_intake`: normalize the end user's real task before selecting a packet.
- `outcome_ladder`: show small/medium/full output tiers by outcome, not by internal packet names.
- `coverage_ladder_quote`: explain what extra source coverage each higher tier adds.
- `freshness_buyup`: let the agent decide whether a fresher paid refresh is worth it.
- `buyer_policy_profile`: encode user/org preferences such as max spend, no vendor risk output, no CSV, only official APIs.
- `watch_delta_product`: recurring delta output for grants, regulations, permits, vendors, tax/labor changes.
- `portfolio_batch_packet`: cheaper batch checks for many companies/vendors/programs.

Why this is smarter:

AI agents should not only say "buy this packet." They should say:

> For this task, the cheapest sufficient route is X. Paying more adds Y coverage. Skipping is also acceptable if Z gaps are tolerable.

## 2. Adopted data and graph methods

Adopt:

- `Official Evidence Knowledge Graph`: not a global truth graph; a graph of official observations, receipts, claims, gaps, conflicts, and valid time.
- `Bitemporal Claim Graph`: separate observed time from legal/effective/business validity time.
- `Source Twin Registry`: model each official source's behavior, formats, update rhythm, capture methods, quality, and terms.
- `Semantic Delta Compressor`: compress raw changes into meaningful deltas that can become actions.
- `Update Frontier Planner`: decide what to refresh next based on value, freshness, source volatility, and packet gaps.
- `Claim Derivation DAG`: track how normalized facts become packet claims.
- `Conflict-Aware Truth Maintenance`: keep conflicts visible instead of overwriting them.
- `Schema Evolution Firewall`: block incompatible source schema changes from silently reaching production.
- `Reversible Entity Resolution Graph`: entity joins remain reversible and explainable.
- `Source Quality Learning Engine`: learn source reliability patterns without turning them into generic trust scores.
- `No-Hit Lease Ledger`: no-hit expires and is scoped; it is never permanent absence.
- `Two-Layer Archive`: public packet asset bundle plus separate evidence replay bundle.
- `Evidence Graph Compiler`: compiles internal graph into public-safe packet inputs.

Reject:

- one global truth graph
- no-hit permanent cache
- screenshot-first corpus
- ML/LLM deciding source trust directly
- automatic production schema changes

## 3. Adopted algorithm and math methods

Adopt:

- `support_state` and `support_trace[]`
- evidence support lattice
- uncertainty propagation as support/coverage state, not public probability
- coverage optimization
- budgeted set cover for selecting sources under cost/cap
- value-of-information decision, with anti-upsell gate
- contradiction calculus
- temporal validity calculus
- interval arithmetic for amounts, dates, thresholds, and deadlines
- monotonic decision logic for no-hit and gaps
- proof minimality so outputs cite enough evidence but not noisy evidence
- active learning without private data
- abstention/defer logic

Reject:

- public eligibility probability
- LLM-as-judge as final truth
- revenue-only optimization
- generic confidence score

## 4. Adopted AWS infrastructure methods

Adopt:

- `AWS Artifact Factory Kernel`: single control kernel for run state, budget leases, jobs, artifacts, and teardown readiness.
- `Probabilistic Budget Leasing`: budget tokens are expiring leases with P95/P99 risk margin, reclaim, refund, and escrow.
- `Canary Economics`: scale a source/capture method only after accepted artifact per dollar is measured.
- `Spot-interruption-tolerant MapReduce`: small shards, checkpoint, idempotency, and reduce jobs.
- `Checkpoint Compaction`: continuously convert partial work into accepted artifacts.
- `Service-Mix Firewall`: service-level caps and automatic quarantine for NAT, OpenSearch, Textract, CloudWatch, Athena, and unknown services.
- `Teardown Simulation`: do not create resources unless deletion path and verification are known.
- `Rolling External Exit Bundle`: export accepted artifacts outside AWS continuously, not only at the end.
- `Panic Snapshot`: emergency export of ledgers/manifests/accepted artifacts before hard teardown.
- `Delta-first corpus acquisition`: prefer hash/delta checks before expensive full fetch/render/OCR.
- conservative auction between job classes, not unconstrained multi-armed bandit.
- source-aware capture economics.
- failure-value ledger: failed source attempts become useful skip/gap/terms evidence.
- cost-to-release critical path multiplier.
- teardown-first resource architecture.

Important correction:

The AWS plan should be thought of as an artifact factory kernel, not merely Batch jobs plus stoplines.

## 5. Adopted production/runtime methods

Adopt:

- `Release Capsule`: immutable unit of production activation.
- `Dual Pointer Runtime`: separate contract pointer and asset bundle pointer.
- `Capability Matrix Manifest`: what is recommendable, executable, billable, preview-only, or blocked.
- `Agent Surface Compiler`: generate `llms.txt`, `.well-known`, MCP, OpenAPI, proof pages, examples, pricing, and no-hit policy from the same capsule.
- `Hot/Cold Static DB Split`: keep runtime small; keep audit/archive separate.
- `Evidence Capsule Cache`: reuse common proof-carrying assets.
- `Golden Agent Session Replay`: replay representative AI-agent sessions before release.
- `Runtime Dependency Firewall`: block AWS URLs, SDK/env dependencies, S3 references, raw artifacts, and private data in runtime.
- `Progressive Exposure Lanes`: discovery, free decision, limited paid, and full paid can roll out independently.
- `Drift-Free Catalog Hash Mesh`: all public surfaces carry matching catalog/version hashes.
- `Privacy-Preserving Product Telemetry`: packet-level funnel events only, no raw queries/CSV/private content.
- `Zero-AWS Posture Attestation Pack`: after teardown, produce a non-AWS evidence bundle that AWS runtime is gone.

Reject:

- live AWS lookup fallback
- S3 final public archive
- full paid output on proof pages
- raw analytics logging
- schema-breaking release via pointer switch alone

## 6. Adopted trust and policy methods

Adopt:

- `Policy Decision Firewall`: one policy engine deciding data class, terms, visibility, proof, and packet eligibility.
- data class / taint tracking from ingest through proof/API/MCP.
- source terms revocation graph.
- public proof minimizer.
- no-hit scope compiler / no-hit lease ledger.
- agent trust manifest.
- trust receipt.
- abuse prevention gate.

Reject:

- CAPTCHA/stealth/proxy bypass
- raw CSV in AWS
- public raw screenshot archive
- generic trust score
- LLM-only terms approval
- permanent AWS archive

## 7. Master-plan changes to carry forward

Add these concepts to the master plan:

1. `Release Capsule` becomes the production activation unit.
2. `Official Evidence Knowledge Graph` becomes the internal evidence model.
3. `Bitemporal Claim Graph` becomes required for claims with validity periods.
4. `No-Hit Lease Ledger` replaces any no-hit permanent cache.
5. `Probabilistic Budget Leasing` refines Budget Token Market v2.
6. `Canary Economics` gates source/method scale-up.
7. `Rolling External Exit Bundle` reduces data-loss risk before teardown.
8. `Policy Decision Firewall` becomes mandatory before public proof/API/MCP output.
9. `Capability Matrix Manifest` tells agents what is currently safe to recommend and buy.
10. `Golden Agent Session Replay` becomes a GEO release gate.

## 8. Final conclusion

After round 2, the smartest version of the plan is:

> jpcite should operate as an official-evidence compiler with an AWS artifact factory kernel. AWS creates evidence and candidate assets under probabilistic budget leases. Source discovery is driven by output gaps. Claims live in a bitemporal evidence graph. Public outputs are compiled through support-state and policy firewalls. Production activates immutable release capsules, exposes agent decision surfaces, and proves zero-AWS posture after teardown.

This is a real improvement over the previous version.
