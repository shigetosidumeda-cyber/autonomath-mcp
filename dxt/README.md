# Claude Desktop Extension (.mcpb) — jpcite

This directory is the source for the Anthropic Desktop Extension bundle
(`.mcpb`, formerly `.dxt`). One-click install for Claude Desktop users:
Settings → Extensions → Install from file → pick `autonomath-mcp.mcpb`.

## Build

```bash
scripts/build_mcpb.sh
# -> writes site/downloads/autonomath-mcp.mcpb
# -> verified by `unzip -l site/downloads/autonomath-mcp.mcpb`
```

The bundle is a flat zip containing `manifest.json` at the root. The
runtime install uses `uvx autonomath-mcp` so the extension stays tiny
(~2 KB) and picks up every PyPI release without re-bundling.

## Version alignment

`manifest.json → version` must match:

- `pyproject.toml → version`
- `server.json → version`
- `server.json → packages[0].version`

Bump all four in lockstep per the release checklist.

## Manifest schema

`dxt_version: "0.1"` per Anthropic's Desktop Extension spec (late 2025
shipping format). Key invariants:

- `server.type`: `python` (we invoke uvx to resolve the PyPI package at
  install time)
- `server.mcp_config.command`: `uvx`
- `server.mcp_config.args`: `["autonomath-mcp"]`
- `tools[]`: list all 169 canonical MCP tools with short descriptions so
  the Claude Desktop Extension marketplace listing shows accurate
  capabilities before install.

## Distribution

1. Landing `/` hero CTA → `/downloads/autonomath-mcp.mcpb`
2. Docs `/docs/getting-started/` → same download link
3. Claude Desktop Extension marketplace submission (manual, post-launch)

See the registry submission checklist for the full submission list.
