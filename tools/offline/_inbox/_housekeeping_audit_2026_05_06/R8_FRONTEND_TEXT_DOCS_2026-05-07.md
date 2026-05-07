# R8 — Frontend Text Audit: site/docs/* documentation pages

**Session**: jpcite housekeeping audit, R8 sweep
**Date**: 2026-05-07
**Scope**: `site/docs/**/*.html` (43 rendered HTML pages produced from `docs/*.md` via `mkdocs build`)
**State**: jpcite v0.3.4, manifest 139 tools (runtime cohort 146), 11,601 searchable / 14,472 total programs

## 1. Inventory

`find site/docs -type f \( -name '*.html' -o -name '*.md' \) | wc -l` → **43 files**.
Top-level cohorts walked:

- `getting-started/` (1)
- `api-reference/` + `api-reference/response_envelope/` (2)
- `mcp-tools/` (1)
- `integrations/{ai-recommendation-template, bookmarklet}/` (2)
- `cookbook/` index + r01 / r02 / r03 / r09 / r10 / r11 / r16 / r17 / r18 / r19 / r20 / r21 (13)
- `compliance/` (7: tokushoho, terms_of_service, privacy_policy, data_governance, data_subject_rights, landing_disclaimer, INDEX)
- methodology / capability docs (`hallucination_guard_methodology`, `confidence_methodology`, `honest_capabilities`, `exclusions`, `error_handling`, `dashboard_guide`, `alerts_guide`, `recommendation-scenarios`, `prompt_cookbook`, `examples`, `faq`, `pricing`, `sla`, `webhooks`)
- `sdks/typescript/`
- `index.html` + `404.html`

(The MkDocs build is pinned by `mkdocs.yml`; `site/docs/` is git-ignored — fixes propagate via the source `docs/*.md`. Verified `.venv/bin/mkdocs build --strict` succeeds in 2.43s.)

## 2. Audit dimensions walked

For each page I grepped against the SOT (CLAUDE.md 2026-05-07 + manifests):

| Dimension | Expected SOT | Observed | Verdict |
|---|---|---|---|
| Endpoint base | `https://api.jpcite.com` | All curl/JS/python samples use `https://api.jpcite.com` (no `localhost`, no `autonomath.ai`, no `jpintel.com`, no `zeimu-kaikei.ai`) | OK |
| Search param name | `q` (FastAPI query) | All examples use `q=...&limit=...&tier=...&fields=minimal` | OK (post `q` standardization) |
| Tool count | 139 (manifest) | `MCP ツール - 139 個`, `139 tools`, `(default で 139 tools)` consistently | OK |
| Program counts | 11,601 searchable / 14,472 total / 2,286 採択 / 108 融資 / 1,185 行政処分 | All match in meta description, og:description, table cells, JSON-LD | OK |
| MCP install | `uvx autonomath-mcp` (PyPI legacy distribution name preserved per CLAUDE.md non-negotiable) | r16 + r17 + r20 + getting-started + mcp-tools + sdks all use `uvx autonomath-mcp` with `mcpServers.jpcite = {...}` key. DXT bundle URL `https://jpcite.com/downloads/autonomath-mcp.mcpb` reachable in r16 | OK |
| Cursor mcp.json | `~/.cursor/mcp.json` + project-local `.cursor/mcp.json` | r17 explicit and correct | OK |
| Claude Desktop config path | `~/Library/Application Support/Claude/claude_desktop_config.json` (mac), `~/.config/Claude/...` (Linux), `%APPDATA%\Claude\...` (Windows) | r16 lists all three | OK |
| OpenAPI agent variant | `https://api.jpcite.com/v1/openapi.agent.json` | r18 ChatGPT Custom GPT and r19 Gemini both use it correctly | OK |
| Brand drift | Should not see `AutonoMath`, `jpintel.com`, `autonomath.ai`, `zeimu-kaikei.ai` | grep returned 0 user-facing hits in `site/docs/` (only `compare_matrix.csv` carries `jpintel.com` as a comparator label, intentional) | OK |
| Tier-pricing regression | No `Free tier`, `Pro plan`, `Starter plan`, `tier-badge` | grep returned 0 hits in HTML pages | OK |
| Stale tool counts | Should not see legacy `55 / 59 / 66 / 74 (個 / tools / MCP)` | grep returned 0 hits | OK |
| Stale entity counts | Should not see `416,375` / `424,054` / `11,547` | grep returned 0 hits | OK |

## 3. Defects found and fixed (1 typo, 4 sites)

**Defect**: `unified_id` example in `/v1/programs/search` `fields=minimal` JSON, plus `POST /v1/programs/batch` request/response bodies and curl example, contained the duplicated literal `"UNI-UNI-71f6029070"`. Real DB rows use a single `UNI-` prefix (verified `sqlite3 data/jpintel.db "SELECT unified_id FROM programs LIMIT 5"` → `UNI-000780f85e`, etc.). Every other reference on the same page (5 curl examples for `/v1/programs/UNI-71f6029070`, batch response example) used the correct `UNI-71f6029070` form, confirming the duplicated form is a regression typo not a documentation device.

**Source fix** in `docs/api-reference.md`:

1. line 495 — `fields=minimal` example: `UNI-UNI-71f6029070` → `UNI-71f6029070`
2. line 597 — batch request body: `["UNI-UNI-71f6029070", "UNI-71f6029070", "UNI-test-a-1"]` → `["UNI-71f6029070", "UNI-185c08e0c1", "UNI-test-a-1"]` (used a real second ID from the FastAPI source's openapi example, `UNI-185c08e0c1`, so the batch-of-2-or-more demonstration stays meaningful)
3. line 619 — batch response example: same `UNI-UNI-` → `UNI-` correction
4. line 663 — batch curl `-d` payload: `'{"unified_ids":["UNI-UNI-71f6029070","UNI-71f6029070"]}'` → `'{"unified_ids":["UNI-71f6029070","UNI-185c08e0c1"]}'`

Note `UNI-185c08e0c1` appears in `src/jpintel_mcp/api/programs.py:1058` as the actual openapi example for `/v1/programs/{unified_id}`, so batch + single endpoints now share the same ground-truth ID.

**Site rebuild**: `.venv/bin/mkdocs build --strict` completed in 2.43s, regenerating `site/docs/api-reference/index.html`. Post-rebuild grep confirms 0 occurrences of `UNI-UNI-71f6029070`, 7 occurrences of `UNI-71f6029070`, 2 occurrences of `UNI-185c08e0c1`. Search-index JSON regenerated from the source — typo has propagated out.

## 4. Defects considered, not fixed

- `docs/_internal/GENERALIZATION_ROADMAP.md:210` carries the same `UNI-UNI-71f6029070` curl example. Out of scope (not a public `site/docs/` page; internal roadmap walk dated W8). Left as-is to avoid widening the change set; flagged for a future internal-doc sweep.
- `compare_matrix.csv` retains `autonomath.com` / `jpintel.com` references in the comparator-table data rows — those are deliberate competitive comparison labels, not stale brand drift.
- Three `site/docs/index.html` JSON-LD blobs use `MCP ネイティブ (標準構成で 139 tools)` — that is the manifest count, not the runtime cohort 146. Per CLAUDE.md "manifest hold-at-139 (default-gate count)", surfacing 139 to public docs is correct; do **not** advertise 146 until the next intentional manifest bump.

## 5. Code-block syntax sanity

Spot-checked the curl / python / TS / json snippets that drive the most click-through:

- `getting-started` curl chain (`/healthz` → `/v1/meta` → `/v1/programs/search?q=IT導入&limit=5`): all 3 calls executable, params correct.
- `r16-claude-desktop-install` shell: `uv install` → `jq` mutate → restart Claude Desktop. `jq` patch correctly idempotent (replaces `mcpServers.jpcite` if already set).
- `r17-cursor-mcp` heredoc + Cursor restart procedure consistent with current Cursor MCP semantics (1.6+).
- `r18-chatgpt-custom-gpt` `.../openapi.agent.json` URL is the agent-trimmed variant served from `api.jpcite.com` — correct (full schema lives at `/v1/openapi.json`, agent-safe trimmed surface at `/v1/openapi.agent.json`).
- `r19-gemini-extension` Python `requests.get(f"{JPCITE}/v1/programs/search", ...)` syntax valid; `?src=cookbook_r19-gemini-extension` attribution param documented.
- `r20-openai-agents` `MCPServerStdio({"command":"uvx","args":["autonomath-mcp"]})` matches Agents SDK constructor signature.
- `sdks/typescript` fetch + `${baseUrl}/v1/programs/search?q=DX` template literal correct.

No syntax bugs found in the sampled code blocks.

## 6. Changelog / version coherence

`changelog/` directory at site/changelog (separate from docs/changelog) carries the version timeline; site/docs has no `changelog/` sub-tree. Within docs surfaces the only version-bearing strings are SOT-aligned: `139 tools`, `protocol 2025-06-18`, `v0.3.x` references appear nowhere stale. Coverage table in `index.html:1868` shows `11,601` correctly. No mismatched `v0.2.0` or pre-Wave counts remain.

## 7. Integration tutorial coherence

freee / マネーフォワード / kintone / Slack plugin pages **do not exist** in `site/docs/`. Per `sdk/{freee-plugin,mf-plugin,integrations/{email,excel,google-sheets,kintone,slack}}/`, those are SDK directories not yet promoted to public docs. No 404 risk — they aren't linked from any `site/docs/*` page. (CLAUDE.md "Wave 21-22 changelog" mentions them as SDK plugin surface area; surfacing is deferred.)

`site/docs/integrations/{ai-recommendation-template, bookmarklet}/` are the two live integration pages. Both verified API host + endpoint + tool name correct.

## 8. Dead-link sweep

Internal navigation links between docs pages all use relative paths through MkDocs' generated nav (`../mcp-tools/`, `../../api-reference/`, etc.). MkDocs `--strict` would have failed the build on a broken internal link — the build succeeded, so no broken internal references.

External links spot-checked: `https://jpcite.com/playground.html?flow=evidence3`, `https://jpcite.com/pricing.html`, `https://jpcite.com/downloads/autonomath-mcp.mcpb`, `https://pypi.org/project/autonomath-mcp/` — all consistent with current production routing.

## 9. Commit + push

Files changed:

- `docs/api-reference.md` (4 typo fixes)

(`site/docs/` is git-ignored per `.gitignore` line 4 — `# only the docs/ sub-tree produced by 'mkdocs build' is ignored.`)

Commit message: `fix(site/docs): documentation page text correctness audit (API + MCP install + integrations + changelog)`

Push: `git push origin main` after pre-commit hooks succeed.

## 10. Counts of audit verdicts

- Pages walked: 43
- Audit dimensions checked per page: 12
- Defects found: **1** (UNI-UNI- typo, 4 occurrences in 1 source file)
- Defects fixed: **1** (4/4 sites corrected, source MD updated, MkDocs rebuild verified clean)
- Defects deferred: 1 (`docs/_internal/GENERALIZATION_ROADMAP.md`, out of scope)
- Stale brand / count regressions: 0
- Tier-pricing regressions: 0
- Code-block syntax bugs: 0
- Broken internal links: 0 (mkdocs --strict gate)

## 11. Honest gaps

- I did not curl every documented endpoint live against `api.jpcite.com` to verify wire-level shape match. CI smoke (17/17 mandatory + 5-module surface, per CLAUDE.md Wave hardening 2026-05-07) gates that surface separately.
- The auto-generated `site/docs/search/search_index.json` carries a stale `UNI-UNI-71f6029070` token until next mkdocs build artifact ships; a real deploy will regenerate it (verified locally: post-rebuild count = 0).
- `freee` / `kintone` / `slack` / `mf` plugin tutorials are SDK directories without public docs surfaces — out of scope for this sweep.

## 12. Net result

`site/docs/*` documentation pages now have correct `unified_id` examples on all `/v1/programs/{unified_id}` and `/v1/programs/batch` surfaces. All other audited dimensions (endpoint base, parameter names, tool count, program counts, MCP install snippets, brand strings, tier-pricing prohibition, code-block syntax, internal links) were already SOT-aligned and required no changes.
