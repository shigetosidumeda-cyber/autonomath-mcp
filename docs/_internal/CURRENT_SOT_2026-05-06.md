# Current SOT 2026-05-06

Generated: 2026-05-06 JST

Purpose: current source-of-truth pointer for operators and agents. This file is a non-destructive reconciliation layer; it does not delete or invalidate historical reports.

## Execution

Current execution control lives in:

1. `tools/offline/_inbox/value_growth_dual/SYNTHESIS_2026_05_06.md` sections 8.19 and 9.
2. `docs/_internal/REPO_HYGIENE_TRIAGE_2026-05-06.md`.

Operational reading:

- M00-D billing safety has local green coverage for customer cap fail-closed, Stripe webhook tolerance, credit-pack idempotency/stale-reservation recovery, and audit-seal persist fail-closed. Production deploy is still blocked until the full deploy packet, migration ownership, and external secret/live-ingest actions are reviewed.
- Company public artifacts are locally green for `company_public_baseline`, `company_folder_brief`, and `company_public_audit_pack`, including paid-key usage logging and persisted audit seals.
- M00-A distribution parity is locally green for static manifest drift, runtime route/tool probe, and tool-count consistency at 139 tools / 269 runtime routes / 227 OpenAPI paths. Generated release surfaces remain frozen unless regenerated as one reviewed packet.
- M01 gBiz is partially local-green for CLI, schema contract, attribution required keys, no double-wrapper raw JSON, rate-limit, dry-run contracts, corporate mirror `attribution_json`, and `/v1/houjin/{bangou}` public-response attribution/citation. Live gBiz ingest remains NO-GO until app name, secret placement, and production migration boundaries are resolved.
- Generated OpenAPI, MCP, DXT, site JSON, and SDK release surfaces should stay frozen until M00-D and M01 contracts settle.
- Production deploy, Fly secret mutation, live ingest, production migration apply, and bulk cleanup require an explicit deploy packet.

## Runtime Counts

These values are a 2026-05-06 local snapshot and must be re-probed before public copy or manifest bumps:

| surface | snapshot |
| --- | ---: |
| MCP tools in `mcp-server.full.json` | 139 |
| REST OpenAPI paths in `docs/openapi/v1.json` | 227 |
| Agent OpenAPI paths in `docs/openapi/agent.json` | 39 |

Rule: prose counts are historical unless they came from the current probe or manifest. Do not bulk-replace old counts inside archived reports.

## Canonical Pointers

| topic | current pointer |
| --- | --- |
| repo layout | `DIRECTORY.md`, plus this file for 2026-05-06 SOT overrides |
| repo hygiene / dirty lane handling | `docs/_internal/REPO_HYGIENE_TRIAGE_2026-05-06.md` |
| execution plan | `tools/offline/_inbox/value_growth_dual/SYNTHESIS_2026_05_06.md` sections 8.19 and 9 |
| operator architecture / gotchas | `CLAUDE.md` |
| secret names and storage boundaries | `docs/_internal/SECRETS_REGISTRY.md`, no literal secret values |
| migration inventory | `docs/_internal/MIGRATION_INDEX.md` plus runtime `schema_migrations` |
| generated artifact map | `docs/_internal/generated_artifacts_map_2026-05-06.md` |
| deploy packet / current NO-GO | `docs/_internal/PRODUCTION_DEPLOY_PACKET_2026-05-06.md` |

## Historical Index Files

These files are useful navigation or audit snapshots, but not current execution SOT:

- `docs/_internal/INDEX.md`
- `docs/_internal/INDEX_2026-05-05.md`
- `docs/_internal/_INDEX.md`
- `docs/_internal/W24_SOT_SYNC_AUDIT.md`

Read them as historical unless this file points to them for a specific topic.

## Brand And Naming

User-facing brand: `jpcite`.

Legacy or internal names that may remain in technical contexts:

- `autonomath-api`: Fly app / console script slug.
- `autonomath-mcp`: legacy package/distribution slug.
- `src/jpintel_mcp`: internal import path, intentionally not renamed.
- `jpintel.db`: legacy/local DB filename context.

Suspicious contexts requiring review:

- public copy that presents `AutonoMath` as the current product brand
- registry descriptions that expose `jpintel`
- generated manifests that disagree with runtime probes

## Secret Hygiene

Rules:

- document secret names, storage locations, owners, and rotation steps only
- never write literal values, partial values, screenshots, CLI output, or real mailbox/API responses into docs
- keep `.env.local`, staging snapshots, raw inbox material, DB files, and token-bearing exports out of git
- run a redacted secret scan before promoting ignored/raw material into tracked docs

## Next Packet

1. Treat `tools/offline/_inbox/value_growth_dual/HANDOFF_2026_05_06.md` as the planning/spec handoff and this file as the production-execution pointer layer.
2. Keep production deploy paused until `scripts/ops/pre_deploy_verify.py --preflight-db autonomath.db --warn-only` is rerun cleanly in the final deploy packet and the external app/secret/migration confirmations are complete.
3. Resolve Fly app naming and required production secret-name placement before any `fly secrets set`, live ingest, migration apply, or deploy.
4. Keep DA-01 `get_program_eligibility_predicate` MCP registration paused until the 139 -> 140 distribution packet is intentionally cut.
5. Next value packet: expose existing `company_folder_brief` as `client_company_folder_v1` only after M00-D/M01/deploy gates stay green and the route/OpenAPI/distribution packet is intentionally cut.
