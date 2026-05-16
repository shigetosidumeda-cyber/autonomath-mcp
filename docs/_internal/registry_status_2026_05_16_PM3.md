# Registry Listing Status — 2026-05-16 PM3

Verification-only check (no paste, no submission) of whether `jpcite-mcp`
appears on the four public agent/MCP registries that matter for organic
discovery (Wave 49 G2 funnel).

Reference paste-ready doc: `docs/_internal/PM2_smithery_glama_paste_ready.md`
(commit `f2862bef4`). Discord paste / form submission was flagged there as
user-required action — this doc records the verifiable side-effect.

## Verification commands (reproducible)

```
curl -sL -o /dev/null -w "%{http_code} %{url_effective}\n" https://smithery.ai/server/jpcite-mcp
curl -sL -o /dev/null -w "%{http_code} %{url_effective}\n" https://glama.ai/mcp/servers/jpcite-mcp
curl -sL "https://glama.ai/api/mcp/v1/servers?query=jpcite-mcp"
curl -sL "https://registry.modelcontextprotocol.io/v0/servers?search=jpcite"
curl -s   "https://pypi.org/pypi/autonomath-mcp/json" | jq '.info.version'
```

## Per-platform state

| Platform | Endpoint probed | Final HTTP | State | Notes |
|---|---|---|---|---|
| **Smithery** | `https://smithery.ai/server/jpcite-mcp` → redirect `/servers/jpcite-mcp` | **404** | **NOT LISTED** | Body literally `# 404 — Server Not Found`. All slug variants (`jpcite`, `jpcite-mcp`, `shigetoumeda/jpcite-mcp`, `bookyou/jpcite-mcp`) return 308 → 404. |
| **Glama** | `https://glama.ai/mcp/servers/jpcite-mcp` → redirect `/mcp/servers?query=author%3Ajpcite-mcp` | 200 (search page) | **NOT LISTED** | Direct slug 301-redirects to author-search page; API `/api/mcp/v1/servers?query=jpcite-mcp` returns `"servers":[]`. The HTML title `MCP Servers by jpcite-mcp` is the generic search-results scaffold, not a server record. |
| **Anthropic Registry** | `https://registry.anthropic.com/v1/servers/jpcite-mcp` | 000 (DNS NXDOMAIN) | **N/A** | No such public endpoint exists. The canonical analogue is the official MCP registry below. |
| **Official MCP Registry** | `https://registry.modelcontextprotocol.io/v0/servers?search=jpcite` | 200 | **NOT LISTED** | Body `{"servers":[],"metadata":{"count":0}}`. Registry root has 30 total servers; `jpcite` matches zero. |
| **PyPI** | `https://pypi.org/pypi/autonomath-mcp/json` | 200 | **LISTED** | `info.version=0.4.0`, uploaded `2026-05-12T08:04:27.914926Z` (`autonomath_mcp-0.4.0-py3-none-any.whl`). 7 releases total; latest 5 = `['0.3.2','0.3.3','0.3.4','0.3.5','0.4.0']`. project_urls Homepage = `https://jpcite.com`, Repository = `https://github.com/shigetosidumeda-cyber/autonomath-mcp`. Tool count not exposed via PyPI metadata (would require importing the package). |

## Summary

- **PyPI**: LISTED — `autonomath-mcp 0.4.0` live since 2026-05-12.
- **Smithery**: NOT LISTED — server slug returns hard 404.
- **Glama**: NOT LISTED — no server record; only a search-results fallback page.
- **Official MCP Registry**: NOT LISTED — 0 hits for `jpcite`.
- **Anthropic Registry**: endpoint does not exist (the public catalog used by
  Claude/Anthropic Console is the official MCP Registry above).

Net: only the package-distribution lane (PyPI) is live. The three
agent-discovery surfaces (Smithery / Glama / MCP Registry) still require the
user-action paste / form submission documented in `PM2_smithery_glama_paste_ready.md`.

## Implication for Wave 49 G2 funnel

Discovery stage of the agent funnel (Discoverability → Justifiability →
Trustability → Accessibility → Payability → Retainability) still relies on the
PyPI surface alone. Until the three MCP-specific registries pick up the
listing, organic agent traffic from those surfaces is 0 by construction —
this is not a code defect but an unfilled human-action gate.

Honest status: 3/4 NOT LISTED, 1/4 LISTED, 1 endpoint does not exist.
