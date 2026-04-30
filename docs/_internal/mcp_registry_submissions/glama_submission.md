# glama.ai submission

**Method**: automatic crawl from public GitHub. No form.

**Confirmed 2026-04-23** via `scripts/mcp_registries.md` (Task #29 research) and
`glama.ai/blog/2026-01-24-official-mcp-registry-serverjson-requirements`:
Glama indexes every public repo that has a valid MCP manifest, schema, and
README. A score badge is minted at
`https://glama.ai/mcp/servers/shigetoumeda/autonomath-mcp/badges/score.svg` within one
crawl cycle (daily).

## Action checklist

- [ ] Repo is public at `github.com/shigetosidumeda-cyber/autonomath-mcp`
- [ ] Root `mcp-server.json` is valid (already drafted, post-rebrand required)
- [ ] Root `README.md` has badges row, install command, tools list, link to
      docs (done — post-rebrand replacement only)
- [ ] Root `smithery.yaml` present (drafted)
- [ ] License file present (LICENSE, MIT — verify exists before launch)
- [ ] First signed release tag `v0.3.2` pushed
- [ ] Allow 24-48 h after repo goes public for first crawl
- [ ] After index: visit Glama listing, click "Claim" if available, link to
      our verified GitHub account

## "Claim listing" fields (verbatim, fill post-rebrand)

| Field | Value |
|---|---|
| Server name | `autonomath-mcp` |
| Short description (EN) | MCP server for Japanese institutional programs — 13,578 subsidies / loans / tax / certifications + 2,286 case studies + 108 三軸分解融資 + 1,185 enforcement cases, 181-rule exclusion checker, primary-source lineage. |
| Short description (JA) | 日本の公的制度 (補助金・融資・税制・認定) 13,578 件 + 採択事例 2,286 + 融資 108 (三軸分解) + 行政処分 1,185 を横断検索・排他チェックする MCP サーバ (93 tools)。 |
| GitHub repo URL | `https://github.com/shigetosidumeda-cyber/autonomath-mcp` |
| Homepage URL | `https://jpcite.com` |
| Install command | `uvx autonomath-mcp` |
| Alternate install | `pip install autonomath-mcp` / Claude Desktop: `autonomath-mcp.mcpb` |
| Author GitHub username | `AutonoMath` (organization) |
| Contact email | `info@bookyou.net` |
| Categories | finance, government, data-platforms |
| Tags | japan, japanese, subsidies, grants, loans, tax-incentives, certifications, enforcement, case-studies, exclusion-rules, mcp-server, stdio, python |

## README additions Glama parses

Glama's crawler reads these sections; keep canonical forms:

1. **Tools table** — matches the 93 tools in `src/jpintel_mcp/mcp/server.py`
   (search/get × programs + case_studies + loan_programs + enforcement_cases,
   batch_get_programs, check_exclusions, list_exclusion_rules, get_meta).
2. **Install** — a clearly labeled `## Install` or `## Quickstart` section
   with `uvx autonomath-mcp` (primary) / `pip install autonomath-mcp` (alt) /
   `.mcpb` bundle (Claude Desktop 1-click).
3. **Screenshot / demo** — `site/assets/demo.svg` (6.4 KB, animated) linked
   from README; Glama embeds it in the listing tile.

## Expected review / indexing

- Crawl: daily.
- Listing live: 24-48 h after repo made public.
- Badge URL live after listing appears.

## Terms of service flag

Glama ToS does **not** require an agreement to be signed for free auto-indexed
listing. Premium "MCP Gateway" is paid — we do **not** opt in; free tier only.

## Placeholders

See `rebrand_mcp_entries.sh`.
