# MCP Registry Submission Runbook (operator-only, auto-generated)

_Generated: 2026-04-25 by `scripts/publish_to_mcp_registries.py`._

Companion to `scripts/mcp_registries.md` (canonical D-0 walkthrough)
and `scripts/publish_to_registries.py` (smoke validator).
This file records the **outcome of automated LIVE submission attempts**
and lists every step that still requires a human (web form, GitHub PR,
Claude Desktop UI). For each surface, the script either:

- `live` — the registry now hosts our manifest (rollback steps below)
- `skipped` — no automatable endpoint or credential missing; manual step recorded
- `fail` — automation tried and a remote / schema error surfaced

## Per-surface outcome

### MCP Official Registry

- **Status**: `fail` [FAIL]
- **Detail**: POST /v0/publish HTTP 403: {'title': 'Forbidden', 'status': 403, 'detail': "You do not have permission to publish this server. You have permission to publish: io.github.shigetosidumeda-cyber/*. Attempting to publish: io.github.AutonoMath/autonomath-mcp. If you're trying to publish to a GitHub organi
- **Manual step**: Re-run with valid GH_TOKEN scoped to the AutonoMath org.

## Credential matrix

| Env var | Used by | Notes |
|---|---|---|
| `GH_TOKEN` / `GITHUB_TOKEN` | MCP Official Registry (#1) | Must be a GH OAuth/PAT for an account with publish rights on the `AutonoMath` org. Without it, validation runs but LIVE publish is skipped. |
| `SMITHERY_TOKEN` | (reserved) | Smithery has no documented submission API as of 2026-04-25; reserved name for future use. |
| (none) | Glama, PulseMCP, DXT | Crawl-driven or self-distributing. |

## Rollback

| Surface | Rollback |
|---|---|
| MCP Official Registry | `POST /v0/publish` again with `version_metadata.status=deprecated` (no full delete). |
| Smithery | dashboard.smithery.ai → Unclaim listing (does not delete; just removes ownership). |
| Glama | No unpublish; remove repo public visibility to drop from index next crawl. |
| DXT (.mcpb) | Remove file from `site/downloads/`; Cloudflare Pages redeploys without it. Already-installed clients keep the old bundle. |
| PulseMCP / mcp.so / Awesome MCP | Open issue / PR to remove entry. |

## Re-run

```bash
# Dry-run (validate-only; never POST publish)
.venv/bin/python scripts/publish_to_mcp_registries.py --dry-run

# Live MCP-Registry publish (requires GH_TOKEN scoped to AutonoMath org)
GH_TOKEN=<token> .venv/bin/python scripts/publish_to_mcp_registries.py --only mcp_registry

# Result JSON is also written to scripts/mcp_publish_result.json
```
