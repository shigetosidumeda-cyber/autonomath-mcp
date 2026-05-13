# 5-minute dev quickstart — localhost → Cloudflare Pages preview

> Target: a developer who has just cloned the jpcite repo and wants the API + static site running locally, plus a one-shot Cloudflare Pages preview URL they can share.
> Budget: ≤5 minutes wall-clock on a Mac with `pip`, `node`, `wrangler` already installed.
> If anything fails, read `CLAUDE.md` → "Common gotchas" before opening an issue.

## 0. Prerequisites (check, don't install)

```bash
python --version       # ≥ 3.12
node --version         # ≥ 20
wrangler --version     # ≥ 3.0 (only needed for §4 preview)
sqlite3 --version      # ≥ 3.40
```

Anything below those? Stop here, upgrade, retry. The codebase will not work on Python 3.11.

## 1. Install (≤90 seconds)

```bash
git clone https://github.com/shigetosidumeda-cyber/autonomath-mcp.git jpcite
cd jpcite
python -m venv .venv
.venv/bin/pip install -e ".[dev,site]"
```

Skip `playwright install chromium` unless you need to run `tests/e2e/`. Heavy.

## 2. Boot the API locally (≤30 seconds)

```bash
.venv/bin/uvicorn jpintel_mcp.api.main:app --reload --port 8080
```

Sanity-curl in a second terminal:

```bash
curl http://localhost:8080/healthz
# → {"status":"ok"}

curl "http://localhost:8080/v1/programs/search?q=中小企業&limit=3"
# → {"items":[...], "total":N, "..."}

curl http://localhost:8080/openapi.json | jq '.paths | length'
# → 219 (at 2026-05-07 snapshot)
```

If `programs/search` returns 0 hits, your local DB is the 1.3 MB dev fixture, not the production seed. That is fine for ergonomics work; for realistic results, fetch the volume seed:

```bash
flyctl ssh sftp get /data/jpintel.db ./data/jpintel.db.prod
mv ./data/jpintel.db ./data/jpintel.db.devfixture
mv ./data/jpintel.db.prod ./data/jpintel.db
```

(Requires Fly app access. The hydrate workflow in CI does the same with `rm -f` because `flyctl ssh sftp get` refuses to overwrite — see `feedback_post_deploy_smoke_propagation` and CLAUDE.md gotcha #5.)

## 3. Boot the MCP server (≤10 seconds)

```bash
# stdio mode (for Claude Desktop / Cursor / Continue / Windsurf)
.venv/bin/autonomath-mcp

# Streamable HTTP mode (2025-06-18 spec)
.venv/bin/uvicorn jpintel_mcp.api.main:app --port 8081 \
  && curl -N -H 'Accept: text/event-stream' \
          -X POST http://localhost:8081/mcp \
          -d '{"jsonrpc":"2.0","method":"tools/list","id":1}'
```

`tools/list` should return 151 tools by default (146 with all post-manifest tools landed; verify with `len(await mcp.list_tools())`).

## 4. Cloudflare Pages preview (≤90 seconds)

The `site/` directory is the entire static deploy target. To get a sharable preview URL:

```bash
# 1. Build static doc HTML (if you've changed mkdocs.yml or docs/*.md)
.venv/bin/mkdocs build --strict

# 2. Push to a personal preview branch on the existing autonomath Pages project
wrangler pages deploy site/ \
  --project-name=autonomath \
  --branch=dev-preview-$(whoami)
```

Wrangler prints a URL like `https://dev-preview-yourname.autonomath.pages.dev`. Production custom domains (`jpcite.com`, `www.jpcite.com`) stay pinned to `main`; your preview is isolated.

To clean up later:

```bash
wrangler pages deployment list --project-name=autonomath
wrangler pages deployment delete --project-name=autonomath <deployment-id>
```

## 5. Verify (≤30 seconds)

```bash
# Lint targets defined in scripts/distribution_manifest.yml
.venv/bin/ruff check scripts/generate_program_pages.py

# Fast slice of the test suite
.venv/bin/pytest tests/test_health.py tests/test_openapi.py -x

# Brand grep — should print nothing in user-facing files
grep -RIn "jpintel" site/ docs/ README.md \
  --include="*.md" --include="*.html" \
  | grep -v "^Binary file" \
  | grep -v "src/jpintel_mcp" \
  | grep -v "^Binary"
```

If the brand grep returns hits in `site/` or `docs/*.md` outside of historical-state markers, you have introduced a regression — see CLAUDE.md constraint 8.

## What you have now

- API @ `http://localhost:8080` (FastAPI, hot reload, 219 paths).
- MCP server @ `stdio` or `http://localhost:8081/mcp` (151 tools).
- A personal Cloudflare Pages preview URL.
- Lint + fast tests green.

Next steps depend on what you're shipping:

| Goal | Read next |
|------|-----------|
| Add a new MCP tool | `src/jpintel_mcp/mcp/server.py` + `mcp/autonomath_tools/` package + `CLAUDE.md` §"Key files" |
| Add a new REST route | `src/jpintel_mcp/api/main.py` + `scripts/export_openapi.py` |
| Add a new SEO page family | `scripts/generate_program_pages.py` as template + `site/_templates/` |
| Add a new SQLite migration | `scripts/migrations/` + `entrypoint.sh` §4 invariant (target_db comment, idempotent) |
| Tune billing | `src/jpintel_mcp/billing/` + Stripe webhook (read CLAUDE.md gotcha about `consent_collection`) |
| Publish a recipe | `docs/recipes/` + `docs/cookbook/` |

## See also

- `CLAUDE.md` — full SOT
- `.agent.md` — vendor-neutral AI-agent briefing
- `docs/agents.md` — Anthropic / OpenAI / Cursor / Continue / GPT Actions sample code
- `docs/integrations/` — per-platform integration guides
- `JPCITE_SETUP.md` — operator-side Cloudflare + Fly setup (one-shot, not for devs)
