# Official MCP Registry (registry.modelcontextprotocol.io) submission

**Priority: 1 (PRIMARY).** Propagates to PulseMCP, Glama (secondary signal),
mcp.so, and several downstream aggregators within one week.

## Artifact

`mcp-server.json` at repo root (drafted 2026-04-23).

Namespace: `io.github.shigetoumeda/autonomath-mcp` — GitHub-owned namespaces do NOT
require DNS verification; ownership is proved by publishing from the same
GitHub account.

## Schema checkpoints (per glama.ai/blog/2026-01-24-official-mcp-registry-serverjson-requirements)

- [x] `$schema` pinned to schemas/2025-12-11
- [x] `name`, `version`, `description` present
- [x] `packages[]` with:
  - `registryType: pypi`
  - `registryBaseUrl: https://pypi.org` (registry enforces this exact URL)
  - `identifier` (= PyPI package name, post-rebrand)
  - `version`
  - `runtimeHint: uvx`
  - `transport.type: stdio`
- [x] `_meta.io.modelcontextprotocol.registry/publisher-provided` ≤ 4 KB

## CLI steps (D-0)

```bash
# Once per machine:
curl -L https://github.com/modelcontextprotocol/registry/releases/latest/download/mcp-publisher_$(uname -s)_$(uname -m).tar.gz | tar -xz
sudo mv mcp-publisher /usr/local/bin/

# Per release:
mcp-publisher login github      # OAuth device flow
mcp-publisher publish --file mcp-server.json
```

## Verification

- After `publish`, the CLI returns a registry record URL:
  `https://registry.modelcontextprotocol.io/servers/io.github.shigetoumeda/autonomath-mcp`
- HTTP GET should return 200 with the same JSON.
- Within 1 week: PulseMCP ingest visible at
  `pulsemcp.com/servers/io.github.shigetoumeda/autonomath-mcp` (no manual submit).

## ToS note

Publishing to the Official Registry requires the publisher to agree to the
registry's Terms (https://registry.modelcontextprotocol.io/terms). Review
before D-0; standard open-source ToS. **Do not proceed if ToS changes to
require data-exclusivity or a revenue share.** As of 2026-04, the ToS is
permissive and we can accept.

## CI automation (defer to W2)

`.github/workflows/mcp-publish.yml`:

```yaml
name: Publish to MCP Registry
on:
  release:
    types: [published]
permissions:
  id-token: write   # OIDC, replaces long-lived token
  contents: read
jobs:
  publish:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v5
      - name: Install mcp-publisher
        run: |
          curl -L https://github.com/modelcontextprotocol/registry/releases/latest/download/mcp-publisher_Linux_x86_64.tar.gz | tar -xz
          sudo mv mcp-publisher /usr/local/bin/
      - name: Publish
        run: mcp-publisher publish --file mcp-server.json --auth-mode oidc
```

Defer until W2 (post-launch) to avoid surprise auto-publish during launch
rollback scenarios.

## Expected review

- Automatic schema + namespace validation: seconds.
- Listing visible: immediately on publish.
- Propagation to PulseMCP: ~24 h daily batch.

## Placeholders

`autonomath-mcp`, `zeimu-kaikei.ai`, `shigetoumeda`, `autonomath-mcp`, `Bookyou 株式会社` — rewritten
by `scripts/rebrand_mcp_entries.sh`.
