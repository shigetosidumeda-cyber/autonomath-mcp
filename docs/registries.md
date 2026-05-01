# jpcite — Registry & Distribution Surface

> **Operator**: Bookyou株式会社 (T8010001213708) / info@bookyou.net
> **Product**: jpcite (PyPI: `autonomath-mcp` / npm: `@autonomath/sdk`)
> **Launch target**: 2026-05-06
> **Last audited**: 2026-04-25

This document is the **single source of truth** for every public registry / marketplace
where jpcite is published. Detailed runbook for the MCP-server-specific registries
(submission ordering, manual-form fields, rollback) lives in
`scripts/mcp_registries.md`. This file is the higher-level audience-facing list.

12 distribution surfaces are listed below in priority order.

---

## 1. PyPI (`autonomath-mcp`)

- **URL**: <https://pypi.org/project/autonomath-mcp/>
- **Distributable**: sdist (`autonomath-mcp-0.3.2.tar.gz`) + wheel (`autonomath_mcp-0.3.2-py3-none-any.whl`)
- **Auth**: API token (`PYPI_TOKEN`, scoped to project)
- **Publish command**:
  ```bash
  python -m build
  TWINE_USERNAME=__token__ TWINE_PASSWORD="$PYPI_TOKEN" twine upload dist/*
  ```
- **Smoke validation**: `twine check dist/*`
- **Rollback**: `pip yank autonomath-mcp==0.3.2` (irreversible delete is impossible — yank is the only safe rollback)

## 2. npm (`@autonomath/sdk`)

- **URL**: <https://www.npmjs.com/package/@autonomath/sdk>
- **Distributable**: TypeScript wrapper around the REST API (sdk/typescript/)
- **Auth**: `NPM_TOKEN` (publish-scoped automation token)
- **Publish command**:
  ```bash
  cd sdk/typescript && npm publish --access public
  ```
- **Smoke validation**: `npm pack --dry-run`
- **Rollback**: `npm deprecate @autonomath/sdk@0.3.2 "deprecated, use 0.3.3+"` within 72 h, otherwise versioned forward only.

## 3. MCP Official Registry

- **URL**: <https://registry.modelcontextprotocol.io/>
- **Source repo**: <https://github.com/modelcontextprotocol/registry>
- **Manifest**: `server.json` (root), schema `https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json`
- **Auth**: `MCP_REGISTRY_TOKEN` (GitHub OAuth or PAT, `repo:read` on `jpcite/autonomath-mcp`)
- **Publish command**:
  ```bash
  mcp publish server.json
  ```
- **Smoke validation**: schema check + `mcp validate server.json` (when CLI ships) — interim: `python -m json.tool server.json` + manual schema diff
- **Rollback**: `mcp publish` with corrected `server.json` (no unpublish endpoint; fix-forward only)
- **Propagates to**: PulseMCP, mcp.so, several downstream 集約 registries within ~1 week

## 4. DXT — Anthropic Claude Desktop Extension

- **URL**: distribution via direct download <https://jpcite.com/downloads/autonomath-mcp.mcpb>
- **Manifest**: `dxt/manifest.json`
- **Bundle**: `autonomath-mcp.mcpb` (zip with manifest + Python entry shim)
- **Build**: `bash scripts/build_mcpb.sh`
- **Auth**: none (self-distributed); Claude Desktop double-click installs locally
- **Submit registry entry**: Claude Desktop → Settings → Extensions → Submit
- **Rollback**: re-host an older `.mcpb` URL; users on the old version stay on the old version

## 5. Smithery (`smithery.ai`)

- **URL**: <https://smithery.ai/server/autonomath-mcp>
- **Manifest**: `smithery.yaml` (root)
- **Auth**: GitHub repo public + Smithery dashboard claim (no API token typically required)
- **Publish path**: auto-indexed daily on push to `main`; claim listing via <https://dashboard.smithery.ai>
- **Smoke validation**: YAML schema + `python -c "import yaml; yaml.safe_load(open('smithery.yaml'))"`
- **Rollback**: amend `smithery.yaml` and push; index updates on next crawl

## 6. Glama (`glama.ai`)

- **URL**: <https://glama.ai/mcp/servers>
- **Listing path**: fully auto-indexed from public GitHub repo + README + MCP manifest
- **Auth**: none (no submission form)
- **Smoke validation**: confirm public repo + README renders, listing appears within 24 h crawl
- **Badge**: `https://glama.ai/mcp/servers/jpcite/autonomath-mcp/badges/score.svg`

## 7. Cline MCP Marketplace

- **URL**: <https://github.com/cline/mcp-marketplace>
- **Listing path**: GitHub PR adding entry under marketplace JSON index
- **Auth**: GitHub user (any contributor with PR rights)
- **Publish command**: `gh repo fork cline/mcp-marketplace --clone && <edit JSON> && gh pr create`
- **Smoke validation**: validate JSON entry against schema in repo CONTRIBUTING.md
- **Review**: maintainer-gated, days

## 8. PulseMCP

- **URL**: <https://www.pulsemcp.com/>
- **Submit**: <https://www.pulsemcp.com/submit>
- **Listing path**: ingests Official MCP Registry daily, processes weekly. If #3 is published, listing auto-appears within ~1 week. Direct form for corrections / expedited.
- **Auth**: none (form submission)
- **Review**: weekly batch, hand-reviewed by founder

## 9. mcp.so

- **URL**: <https://mcp.so/submit>
- **Listing path**: GitHub issue or web form
- **Auth**: none
- **Review**: manual or semi-auto, days

## 10. Awesome MCP Servers (punkpeye)

- **URL**: <https://github.com/punkpeye/awesome-mcp-servers>
- **Listing path**: PR adding one line under `Finance & Fintech`, alphabetical order
- **Auth**: GitHub user
- **Publish command**: `gh repo fork punkpeye/awesome-mcp-servers --clone && <edit README.md> && gh pr create`
- **Review**: maintainer-gated, days
- **Mirror**: mcpservers.org auto-mirrors this repo (one PR covers two surfaces)

## 11. Cursor Marketplace

- **URL**: <https://cursor.com/marketplace> (plugin submission form)
- **Listing path**: web form (repo URL + short description + category)
- **Auth**: Cursor account
- **Review**: manual, typically days

## 12. mcpservers.org

- **URL**: <https://mcpservers.org/submit>
- **Listing path**: web form (Awesome MCP web mirror — auto-mirrors `punkpeye/awesome-mcp-servers`)
- **Auth**: none
- **Review**: auto on Awesome MCP merge

---

## Skipped / not eligible

- **mcpt** — sunsetted April 2025 by Mintlify; redirect is to the Official MCP Registry (#3)
- **MACH Alliance MCP Registry** — commerce-vertical only, not a fit
- **Continue.dev marketplace** — at launch time (2026-04-25) Continue.dev integrates MCP servers via local config; no central marketplace submission exists
- **Goose extensions** — at launch time Goose integrates MCP via direct config; no central registry
- **Zed assistant context servers** — Zed uses MCP via local config; no central registry
- **Cody MCP marketplace** — at launch time Sourcegraph Cody references MCP servers via documentation, not a marketplace submission
- **MCP Hunt / MCP Market / MCP Server Finder** — covered in `scripts/mcp_registries.md` (long-tail directories; submitted in priority order on launch day)

If any of the above five (Continue.dev, Goose, Zed, Cody) ship a marketplace post-launch, this list is amended.

---

## Auth env vars summary

| Registry | Env var | Where to obtain |
|---|---|---|
| PyPI (#1) | `PYPI_TOKEN` | <https://pypi.org/manage/account/token/> (scope: `autonomath-mcp`) |
| npm (#2) | `NPM_TOKEN` | <https://www.npmjs.com/settings/~/tokens> (Automation, publish scope) |
| MCP Registry (#3) | `MCP_REGISTRY_TOKEN` | GitHub PAT, `repo:read` on `jpcite/autonomath-mcp` |
| DXT (#4) | none | self-distributed `.mcpb` at <https://jpcite.com/downloads/autonomath-mcp.mcpb> |
| Smithery (#5) | none | dashboard claim only |
| Glama (#6) | none | auto-indexed |
| Cline (#7) | GitHub | any contributor |
| PulseMCP (#8) | none | form |
| mcp.so (#9) | none | form/issue |
| Awesome MCP (#10) | GitHub | any contributor |
| Cursor (#11) | Cursor account | form |
| mcpservers.org (#12) | none | form |

Operator launch day (2026-05-06) follows the order above. See `scripts/mcp_registries.md`
for the full step-by-step runbook (smoke gates, rollback per registry, post-launch monitoring).
