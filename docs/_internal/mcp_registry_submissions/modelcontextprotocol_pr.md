# modelcontextprotocol/servers PR draft

**STATUS (2026-04-23): NOT APPLICABLE — DO NOT SUBMIT.**

Confirmed via `CONTRIBUTING.md` of `github.com/modelcontextprotocol/servers`
(fetched 2026-04-23): the repository retired its third-party server list in
favor of the **Official MCP Registry** (`registry.modelcontextprotocol.io`).

> The README no longer contains a list of third-party MCP servers — that list
> has been retired in favor of the MCP Server Registry.
> The repository accepts bug fixes, usability improvements, and enhancements
> demonstrating MCP protocol features, but explicitly does NOT accept new
> server implementations.

Submitting a PR that adds a new entry will be closed. The correct path is
below.

---

## Replacement: Official MCP Registry (registry.modelcontextprotocol.io)

### Artifact

- `mcp-server.json` at repo root (already drafted).
  - Namespace we plan to use (placeholder): `io.github.shigetoumeda/autonomath-mcp`.
    GitHub-owned namespaces do not require DNS verification; ownership is proved
    by pushing from the same GitHub account.

### Authentication

Two options, whichever is cheaper on launch day:

1. **Interactive**: `mcp-publisher login github` (OAuth device flow in browser).
2. **CI** (preferred after W2): GitHub Actions OIDC. Add a workflow
   `.github/workflows/mcp-publish.yml` that calls `mcp-publisher publish` with
   `id-token: write` permission so no long-lived secret is stored.

### CLI steps (D-0)

```bash
# Once:
curl -L https://github.com/modelcontextprotocol/registry/releases/latest/download/mcp-publisher_$(uname -s)_$(uname -m).tar.gz | tar -xz
sudo mv mcp-publisher /usr/local/bin/

# Per release:
mcp-publisher login github
mcp-publisher publish --file mcp-server.json
```

Review: automatic, near-instant (schema validation + namespace check).

### PR body (only relevant if we ever decide to contribute a REFERENCE example
### back to the repo — not our listing submission)

Template kept for completeness. Use ONLY if we build a minimal reference
implementation demonstrating a non-obvious protocol feature (we currently do
not plan to).

```markdown
## Summary
<!-- what this adds and why it demonstrates MCP protocol X / Y feature -->

## Test plan
- [ ] FastMCP server boots on stdio
- [ ] `search_programs` returns correct shape with fields=minimal|default|full
- [ ] `check_exclusions` triggers on UNI-71f6029070 ∩ koyo-shuno-shikin
- [ ] Protocol version negotiation: 2024-11-05 / 2025-03-26 / 2025-06-18

## Notes
Built on FastMCP SDK >=1.2. Protocol 2025-06-18 is the declared floor.
```

## Placeholders to finalize

| Placeholder | Source |
|---|---|
| `autonomath-mcp` | PyPI package name after rebrand |
| `jpcite.com` | Production landing page domain after rebrand |
| `shigetoumeda` | GitHub org/user after rebrand |
| `autonomath-mcp` | GitHub repo slug after rebrand |
| `Bookyou 株式会社` | Publisher display name |

Run `scripts/rebrand_mcp_entries.sh --apply` once decided.
