# Repo Hygiene Packetization Addendum

- date: `2026-05-06`
- source snapshot: `docs/_internal/repo_dirty_lanes_latest.md`
- dirty entries: `850`
- scope: docs-only follow-up; no deletes, moves, reverts, code, workflow, migration, site, or SDK changes

## Purpose

Treat the dirty tree as service-improvement material, not cleanup waste. Each
lane should become a review packet with: owner, file list, intent, value asset,
release gate, and decision (`land`, `hold`, `internal-only`, or `ignore-local`).

## Packet Rules

1. Do not destroy or normalize first. Preserve the current dirty tree until a
   lane packet has an explicit decision.
2. Separate source changes from generated mirrors. Public site, OpenAPI, SDK,
   manifests, and package artifacts must name the generator or source-of-truth.
3. Promote value only through compact artifacts. Raw operator output, local DBs,
   and bulky captures stay local unless reduced to a manifest, benchmark
   summary, or repeatable runbook.
4. Security, billing, auth, APPI, cost caps, idempotency, workflows, and
   migrations are release gates before growth or conversion assets.

## Lane Next Actions

| lane | entries | next action | value to capture |
|---|---:|---|---|
| `billing_auth_security` | 10 | Review first as a blocked release packet; confirm fail-closed behavior, secrets posture, billing events, APPI/Turnstile, audit seal, and idempotency. | Trust boundary, paid usage safety, enterprise readiness. |
| `runtime_code` | 90 | Split by API/MCP surface and bind each group to focused tests before merge. | Practitioner-ready outputs, composite intelligence, evidence packets, lower-cost answer generation. |
| `migrations` | 153 | Build an applied-order packet with rollback pairing, target DB, destructive markers, and dry-run notes before any deploy. | Durable derived data layer: predicates, source verification, risk signals, timelines, artifacts. |
| `workflows` | 18 | Review permissions, schedules, production write targets, secrets, concurrency, and manual rollback path. | Safe automated refresh, publish, eval, trust-center, and ingest loops. |
| `cron_etl_ops` | 58 | Require dry-run behavior, idempotency notes, target tables, source attribution, and retry policy. | Fresh data foundation and precomputed answers that reduce LLM research cost. |
| `tests` | 127 | Attach tests to feature packets instead of landing as a bulk test dump; mark slow/DB/network gates. | Acceptance criteria for BPO, tax, M&A, finance, FDI, municipality, and AI-developer outputs. |
| `openapi_distribution` | 6 | Regenerate from runtime source and compare mirrors in one distribution packet. | Agent-callable contract and first-hop routing reliability. |
| `sdk_distribution` | 55 | Verify package names, versions, deleted tarball intent, examples, extension surfaces, and manifest parity. | Lower-friction adoption by agents, developers, browser users, and IDE users. |
| `generated_public_site` | 82 | Land only with generator command, source doc, and expected diff rationale. | Public proof pages, trust center, SEO, benchmark and conversion surfaces. |
| `public_docs` | 73 | Human copy review for claims, pricing, examples, launch posts, and integration paths. | Conversion copy tied to concrete artifacts, benchmarks, or first-hop integrations. |
| `internal_docs` | 79 | Keep operator-only; promote only redacted summaries to public docs. | Runbooks, SOT, handoffs, legal/security review memory, and service-improvement backlog. |
| `operator_offline` | 29 | Commit repeatable prompts/runners/contracts; keep raw outputs and inbox data out of source. | Research loops that become product specs, source matrices, and reusable prompt protocols. |
| `benchmarks_monitoring` | 28 | Version configs, questions, and compact summaries; keep bulky runs out of git. | Conservative proof for reliability, token savings, JCRB, SLOs, and regression detection. |
| `data_or_local_seed` | 1 | Confirm it is not a DB dump or private seed before any commit. | Small reproducible fixtures only. |
| `root_release_files` | 10 | Review as release metadata with Docker, env, manifest, and README implications. | Clear install/deploy contract and safer distribution. |
| `misc_review` | 31 | Classify into one of the lanes above before any merge. | Avoid hidden coupling and accidental release baggage. |

## Value Asset Packets

| asset packet | candidate material | service improvement |
|---|---|---|
| First-hop distribution | MCP/DXT manifests, OpenAPI agent specs, SDK docs, browser/IDE extensions, `llms.txt`. | Makes jpcite the tool an AI client chooses before generic web search. |
| Practitioner output surfaces | `artifacts`, `intel_*`, evidence batch, eligibility predicates, funding stack, company DD, citation packs. | Turns raw lookup into reusable deliverables for paid users. |
| Data foundation | migrations, ETL, source freshness, derived tables, cross-source verification, program calendars. | Reduces runtime cost and improves answer certainty. |
| Trust proof | eval queries, tests, benchmark summaries, monitoring/SLO configs, source freshness reports. | Converts reliability work into publishable proof without overclaiming. |
| Conversion copy | pricing, public docs, launch assets, examples, integration docs, trust-center pages. | Connects technical value to purchase and onboarding paths. |
| Operator knowledge | internal runbooks, SOT docs, marketplace applications, legal/security notes, offline prompts. | Keeps execution memory reusable while protecting sensitive material. |

## Packet Exit Criteria

Each lane packet is ready only when it names:

- source-of-truth files and generated mirrors, if any
- tests or manual checks required before merge
- public/private boundary and redaction needs
- value asset created or deliberately not created
- release decision and owner

