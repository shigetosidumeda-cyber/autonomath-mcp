# Agent runtime

Documentation for the agent-facing runtime contracts, packet schemas, and discovery
artifacts that AI agents consume when calling jpcite.

This area is the human-readable companion to the machine-readable artifacts under
`site/.well-known/` and `site/releases/rc1-p0-bootstrap/`.

## Navigation

- [Outcome → Packet → Athena crosswalk](outcome_packet_athena_crosswalk.md) — 92 outcomes mapped to packet generators, S3 paths, Glue tables, and Athena query templates.

## Related machine-readable artifacts

- `site/.well-known/jpcite-outcome-catalog.json` — public catalog of 92 purchasable outcomes (`schema_version: jpcite.outcome_catalog.public.v1`).
- `site/.well-known/jpcite-outcome-packet-crosswalk.json` — outcome → packet → Athena crosswalk (`schema_version: jpcite.outcome_packet_athena_crosswalk.v1`).
- `site/releases/rc1-p0-bootstrap/outcome_contract_catalog.json` — 62-entry RC1 contract catalog (subset of public 92).
- `site/releases/rc1-p0-bootstrap/outcome_source_crosswalk.json` — 14-deliverable source-family crosswalk.
- `src/jpintel_mcp/agent_runtime/contracts.py` — 19 Pydantic models defining the canonical JPCIR envelope.
