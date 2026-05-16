# Current service delta after RC1 P0 bootstrap work

Date: 2026-05-15

## What changed

The service is moving from a generic API/MCP surface toward an agent-facing public-information artifact factory:

- The release capsule now publishes 14 deterministic deliverable definitions.
- Two deliverables are explicitly CSV-assisted and require user CSV consent.
- The CSV boundary is formalized for freee-style, Money Forward-style, and Yayoi-style accounting CSVs without claiming vendor certification.
- The official Japanese public-source collection scope now covers laws/regulations, tax, subsidies, local governments, statistics, procurement, and court/admin guidance.
- Artifact-generation algorithms are described as deterministic evidence operations: evidence join, time-window coverage, freshness, counterparty matching, triage without verdict, deadline ranking, and no-hit semantics.
- AWS spend planning now targets exactly USD 19,490, split into 8 staged batches, with live execution still blocked.

## What this means for end users

The target user experience is not "ask an AI and hope it fetches correctly." It is:

1. An AI agent sees a specific outcome catalog.
2. The agent recommends a cheap/free preview route first.
3. If the user needs a cited artifact, the agent requests a scoped accepted-artifact purchase.
4. The output is built from stored first-party receipts and known gaps.
5. Private CSV facts can rank/filter/prefill tenant-private outputs, but cannot become public source receipts.

## Current hard boundary

The system is still intentionally blocked before live AWS:

- `site/releases/rc1-p0-bootstrap/preflight_scorecard.json` remains `AWS_BLOCKED_PRE_FLIGHT`.
- `site/releases/rc1-p0-bootstrap/aws_spend_program.json` has `live_execution_allowed: false`.
- The read-only evidence helper only prints/parses read-only command outputs; it does not execute AWS.
- No mutating AWS, live billing, request-time LLM fact generation, or raw CSV public export is enabled.

## Next useful implementation step

The next value step is to make the P0 MCP/REST facade route directly against the 14-deliverable outcome catalog so AI agents can recommend concrete artifacts instead of only the older small outcome set.
