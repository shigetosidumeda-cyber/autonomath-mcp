# Generated Artifacts Map 2026-05-06

このファイルは、repo内の「手編集するsource」と「生成・配布artifact」を混同しないための台帳です。

## Policy

- 生成物を追跡すること自体は許容する。Cloudflare Pages、OpenAPI import、MCP/LLM discoveryでは、配布artifactをrepoに置く価値がある。
- ただし、source変更と生成物変更はできる限りcommit laneを分ける。
- 生成物を直接手編集しない。修正は生成元、テンプレート、script、DB/seedへ入れる。
- 生成物の巨大backupはrootに置かない。`dist.bak*/` はlocal/archive扱い。

## Artifact Table

| path | type | source of truth | generator | tracked/deployed | manual edit |
|---|---|---|---|---|---|
| `docs/openapi/v1.json` | generated OpenAPI full spec | FastAPI app + route metadata | `uv run python scripts/export_openapi.py` | tracked, docs artifact | no |
| `site/docs/openapi/v1.json` | generated OpenAPI full public mirror | FastAPI app + route metadata | `uv run python scripts/export_openapi.py` | generated public mirror | no |
| `docs/openapi/agent.json` | generated agent-safe OpenAPI | FastAPI app + `src/jpintel_mcp/api/openapi_agent.py` | `uv run python scripts/export_agent_openapi.py` | tracked, AI importer artifact | no |
| `site/openapi.agent.json` | generated agent OpenAPI root mirror | same as above | `uv run python scripts/export_agent_openapi.py` | deployed public artifact | no |
| `site/docs/openapi/agent.json` | generated agent OpenAPI docs mirror | same as above | `uv run python scripts/export_agent_openapi.py` | deployed public artifact | no |
| `site/docs/` | MkDocs build output | `docs/`, `mkdocs.yml`, `overrides/` | `mkdocs build` | ignored/generated | no |
| `site/programs/*` | generated SEO pages | `data/jpintel.db`, templates/scripts | `scripts/generate_*` family | ignored except index/share | no |
| `site/prefectures/` | generated prefecture pages | data + templates | `scripts/generate_*` family | ignored/generated | no |
| `site/structured/` | generated JSON-LD shards | data + templates | retired/legacy generator path | ignored/generated | no |
| `site/llms-full.txt` | generated LLM crawler dump | DB + distribution metadata | `uv run python scripts/regen_llms_full.py` | ignored/generated | no |
| `site/llms-full.en.txt` | generated LLM crawler dump | DB + distribution metadata | `uv run python scripts/regen_llms_full_en.py` | ignored/generated | no |
| `site/llms.txt` | curated LLM short index | docs/distribution metadata/manual copy | manual + generator assistance | tracked/deployed | yes, carefully |
| `site/llms.en.txt` | curated English LLM short index | docs/distribution metadata/manual copy | manual + generator assistance | tracked/deployed | yes, carefully |
| `site/en/llms.txt` | curated English mirror | `site/llms.en.txt` intent | manual/sync | tracked/deployed | yes, carefully |
| `site/sitemap-*.xml` | generated sitemap shards | site pages + generator scripts | `scripts/sitemap_gen.py` and related | mixed | no |
| `site/_data/public_counts.json` | generated public count snapshot | DB + count scripts | `scripts/generate_public_counts.py` | tracked/deployed | no |
| `site/downloads/autonomath-mcp.mcpb` | packaged MCP bundle | package/dxt/build process | package build process | tracked/deployed binary | no |
| `dist/` | build output | package/site build commands | build scripts | ignored local output | no |
| `dist.bak*/` | local/archive build backup | previous build outputs | none/currently local | ignored local/archive | no |

## Commit Lanes

Use these lanes when organizing future changes.

1. Runtime code and tests: `src/`, focused `tests/`.
2. Migrations and DB bootstrap: `scripts/migrations/`, entrypoint DB logic.
3. Generated OpenAPI: `docs/openapi/*.json`, `site/openapi*.json`, `site/docs/openapi/*.json`.
4. Public docs/copy: `docs/*.md`, `README.md`, `site/*.html` hand-authored pages.
5. Site generated output: generated `site/` subtrees and sitemap/llms full outputs.
6. SDK/package surfaces: `sdk/`, `dxt/`, `server.json`, `mcp-server*.json`, `smithery.yaml`.
7. Operator research and prompts: `tools/offline/*.md`, `docs/_internal/*`, generated inbox reports.
8. Deploy/CI/Docker: `.github/workflows/`, `.dockerignore`, `Dockerfile`, `fly.toml`.

## Review Rules

- If an OpenAPI generator source changes, regenerate all mirrored OpenAPI outputs in the same generated-artifact commit.
- If only generated OpenAPI changed without source changes, verify the generator command and explain why.
- If a `site/` file is hand-authored, mention that in the commit or PR. If it is generated, include the generator command.
- Do not commit raw offline inbox data, WARC/PDF blobs, quarantine rows, or local DB side files.
- Do not treat `tools/offline/_inbox/` outputs as source. Promote only distilled markdown/specs that are intentionally reviewed.

## Current Gaps

- `site/` still mixes hand-authored public pages with generated output. A `site/README.md` would reduce ambiguity.
- `scripts/` has many top-level generators and one-off utilities. A `scripts/MANIFEST.md` would reduce ambiguity.
- `tools/offline/README.md` is older than the current offline loop/inbox reality.
- Full test coverage is much larger than the CI subset; test lane ownership should be explicit before broad refactors.
