# cursor.directory MCP server submission — jpcite

**Draft 2026-05-11 (Wave 19 §G2 resubmit).** Operator submits via cursor.directory GitHub PR; this file is the canonical draft body claude prepared.

## Repository entry (cursor.directory/mcps.json fragment)

```json
{
  "id": "jpcite",
  "name": "jpcite",
  "publisher": "Bookyou株式会社",
  "publisher_url": "https://jpcite.com",
  "description": "Japanese public-program evidence API + MCP server. 11,601 補助金・融資・税制・認定 programs with source_url, fetched_at, known_gaps, and corpus_snapshot_id preserved on every row. Use before answer generation when citation accuracy matters.",
  "category": ["research", "compliance", "finance", "data"],
  "tags": ["japan", "subsidy", "tax", "law", "audit", "evidence", "citation"],
  "icon": "https://jpcite.com/assets/logo-128.png",
  "homepage": "https://jpcite.com",
  "documentation": "https://jpcite.com/docs/agents.md",
  "license": "Apache-2.0 (code); see https://jpcite.com/data-licensing.html for data",
  "languages": ["ja", "en"],
  "install": {
    "type": "stdio",
    "package": "autonomath-mcp",
    "registry": "pypi",
    "command": "uvx",
    "args": ["autonomath-mcp"],
    "env": {
      "JPCITE_API_KEY": "${USER_API_KEY:-}",
      "JPCITE_API_BASE": "https://api.jpcite.com"
    }
  },
  "alternative_transport": {
    "streamable_http": {
      "url": "https://api.jpcite.com/v1/mcp",
      "auth": "X-API-Key"
    }
  },
  "tool_count": 151,
  "first_party_only": true,
  "no_llm_inside": true,
  "schema_version": "mcp/2025-06-18",
  "registry_manifest": "https://jpcite.com/server.json",
  "tool_manifest": "https://jpcite.com/mcp-server.json",
  "discovery": "https://jpcite.com/.well-known/mcp.json"
}
```

## PR title

```
Add jpcite — Japanese public-program evidence API (151 MCP tools, first-party citation)
```

## PR body (operator pastes this on GitHub)

```markdown
## Summary

Adds **jpcite** — a Japanese public-program evidence API + MCP server — to cursor.directory.

- **151 MCP tools** at default gates (151 runtime, 7 in source pending manifest bump)
- **11,601 補助金・融資・税制・認定 programs** + 6,493 laws full-text + 2,065 court_decisions + 1,185 行政処分
- **First-party citations only** — every row carries `source_url`, `source_fetched_at`, `corpus_snapshot_id`, `known_gaps`. Aggregators are banned from the source pool.
- **No LLM inside.** Production code never imports anthropic / openai / google.generativeai / claude_agent_sdk. CI-enforced by `tests/test_no_llm_in_production.py`.
- **Anonymous 3 req/day free tier** (per IP, JST midnight reset). Paid `¥3/req` 完全従量 (税込 ¥3.30).
- **MCP install:** `uvx autonomath-mcp` (PyPI package name is `autonomath-mcp` for backward compatibility; user-facing brand is jpcite).
- **OAuth 2.1 Device Flow** supported for browser-less agent setups (Cursor headless / CI runner / Cline / smol-agents).

## Why Cursor users want this

Cursor agents working on Japanese SMB / compliance / 補助金申請 / 税務 / 法令調査 routinely need to cite Japanese government program data, but the public web is mostly aggregator-rewritten and lacks `source_url + fetched_at`. With jpcite as an MCP tool, the agent can answer "this 補助金 is administered by 経済産業省, source: <official URL>, fetched 2026-05-11" with full provenance preserved.

## Supported tool families

- **Search & evidence** — search_programs, get_evidence_packet, previewCost
- **Company baseline** — createCompanyPublicBaseline, createCompanyFolderBrief, createCompanyPublicAuditPack
- **Compatibility & composition** — apply_eligibility_chain, find_complementary_programs, compatibility_matrix
- **Amendment tracking** — track_amendment_lineage, policy_upstream
- **Industry packs** — pack_construction, pack_manufacturing, pack_real_estate
- **Tax surface** — tax_rule_full_chain, list_tax_sunset_alerts, prepare_kessan_briefing
- **DD / audit** — match_due_diligence_questions, cross_check_jurisdiction
- **Application kit** — bundle_application_kit, subsidy_roadmap_3yr, deadline_calendar

## Verification

- ✅ MCP manifest live at https://jpcite.com/mcp-server.json (151 tools)
- ✅ Registry manifest live at https://jpcite.com/server.json
- ✅ OpenAPI agent profile at https://jpcite.com/openapi.agent.json (34 paths)
- ✅ Streamable HTTP transport at https://api.jpcite.com/v1/mcp
- ✅ Discovery at https://jpcite.com/.well-known/mcp.json
- ✅ Federation discovery at https://api.jpcite.com/v1/meta/federation (Wave 19)
- ✅ OAuth device flow at https://api.jpcite.com/v1/oauth/device/code (Wave 19)

## Screenshots

(operator attaches 3 PNGs from `docs/marketplace/screenshots/`)

1. `jpcite_search_cursor.png` — Cursor sidebar showing search_programs result with citation row.
2. `jpcite_evidence_packet_cursor.png` — get_evidence_packet rendered with corpus_snapshot_id + known_gaps.
3. `jpcite_install_uvx.png` — terminal showing `uvx autonomath-mcp` install + MCP probe.

## Trust signals

- **Operator:** Bookyou株式会社 (適格請求書発行事業者番号 T8010001213708, JP)
- **Contact:** info@bookyou.net
- **License:** Apache-2.0 (code) + per-row data license at https://jpcite.com/data-licensing.html
- **Trust manifest:** https://jpcite.com/.well-known/trust.json
- **Security policy:** https://jpcite.com/.well-known/security.txt
- **SBOM:** https://jpcite.com/.well-known/sbom.json
- **Status page:** https://jpcite.com/status/

## Notes for reviewer

- The PyPI package is named `autonomath-mcp` for backward compatibility; please do not rename the install command. User-facing brand is `jpcite` and that's what should appear in the directory.
- This is a resubmit of an earlier draft; the previous submission was paused while we finished §B2 robots.txt + .well-known/openapi-discovery.json + OAuth device flow (all live as of Wave 19, 2026-05-11).

Closes #(prior submission issue if any).
```

## Screenshot pack (operator captures)

Save under `docs/marketplace/screenshots/`:

1. **jpcite_search_cursor.png** (1280×800)
   - Cursor sidebar with `search_programs(q="ものづくり補助金", prefecture="埼玉県")` running
   - Result panel showing tier S row with `source_url` + `source_fetched_at` highlighted
2. **jpcite_evidence_packet_cursor.png** (1280×800)
   - Cursor agent calling `get_evidence_packet(program_id="AID-xxx")`
   - JSON pane showing `corpus_snapshot_id`, `known_gaps`, `identity_confidence`
3. **jpcite_install_uvx.png** (1280×800)
   - Terminal showing `uvx autonomath-mcp` install followed by `claude mcp list` confirming registration

## Submit URL

```
https://github.com/cursor/directory  (or current cursor.directory PR target)
```

Operator pastes the JSON fragment into the appropriate `mcps.json` / `data/mcp-servers.json` file, attaches the 3 screenshots, and posts the PR body above. Claude does not have direct push permission to the cursor org, so this last step remains a user-side operation. (Same pattern as Wave 16 §G3.)
