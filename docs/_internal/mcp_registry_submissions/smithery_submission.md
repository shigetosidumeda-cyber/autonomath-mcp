# Smithery (smithery.ai) submission

**Method**: auto-index from public GitHub repos that contain a valid
`smithery.yaml` at root, plus optional "claim" flow to enable the install CLI.

**Confirmed 2026-04-23** via Smithery docs
(smithery.ai/docs/build/project-config/smithery-yaml) and sample repos:
- `github.com/XGenerationLab/xiyan_mcp_server/blob/main/smithery.yaml`
- `github.com/andybrandt/mcp-simple-pubmed/blob/master/smithery.yaml`

## Artifact

`smithery.yaml` at repo root (drafted 2026-04-23).

Key fields:
- `startCommand.type: stdio` — matches our FastMCP stdio transport in
  `src/jpintel_mcp/mcp/server.py`.
- `configSchema` — two optional strings (API key + API base URL).
- `commandFunction` — invokes `python -m jpintel_mcp.mcp.server` with env vars.
- `metadata` — displayName, description, icon, homepage, repository, license,
  categories, tags.

## Action checklist

- [ ] `smithery.yaml` validated against Smithery schema (use smithery CLI dry
      run post-rebrand: `smithery validate` or web validator at smithery.ai/new)
- [ ] Repo public on GitHub
- [ ] First release tag `v0.1.0` on GitHub + corresponding PyPI release
- [ ] Go to `smithery.ai/new` and paste repo URL (triggers immediate index)
- [ ] Wait for "Claim" email / button → confirm GitHub ownership
- [ ] Verify install command: `npx -y @smithery/cli install autonomath-mcp
      --client claude` works end-to-end

## ToS note

Smithery ToS does not require signing a license agreement to be indexed.
Hosting free tier allows stdio auto-run at discovery time. We do **not** enable
Smithery Hosted (their managed cloud execution) — we only want discovery /
install-command listing.

Flag if any of these appear during claim flow, do not accept:
- Exclusive-distribution clauses
- Required revenue share
- Mandatory cloud-hosted execution (would break our stdio-only / data-sovereign
  promise)

## Fields the Smithery listing pulls from smithery.yaml

| smithery.yaml key | Surface on smithery.ai |
|---|---|
| `metadata.displayName` | Listing title |
| `metadata.description` | Listing tagline |
| `metadata.icon` | Listing icon |
| `metadata.categories` | Category filters |
| `metadata.tags` | Search tags |
| `configSchema.properties` | "Configure before install" form |
| `commandFunction` | The install command the CLI copies |

## Expected review

- Auto-index on repo crawl: within hours.
- Claim flow: manual, 1-3 business days.
- Install CLI live: immediately after claim.

## Placeholders

`autonomath-mcp`, `zeimu-kaikei.ai`, `shigetoumeda`, `autonomath-mcp` — rewritten by
`scripts/rebrand_mcp_entries.sh`.
