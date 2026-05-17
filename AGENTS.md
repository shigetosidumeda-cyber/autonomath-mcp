# AGENTS.md — jpcite vendor-neutral agent SOT

> Source of truth for **every** coding / browsing / data agent that opens this repository (Claude Code, Cursor, Windsurf, Codex CLI, GPT, Gemini, local models, future systems).
> Vendor-specific shims (`CLAUDE.md` / `.agent.md` / `.cursorrules` / `.windsurfrules` / `.mcp.json`) point here. If any of those conflict with this file, **this file wins**.
> Last canonical edit: 2026-05-17 (Harness H3 — Agent Entry SOT landing).

## 1. Project identity

| Field | Value |
|---|---|
| Product | **jpcite** — Japanese public-program evidence database (補助金 / 融資 / 税制 / 認定 / 法令 / 法人 / 行政処分 / 採択事例) |
| Operator | **Bookyou株式会社** — 適格請求書発行事業者番号 **T8010001213708** — 代表 梅田茂利 — info@bookyou.net |
| Domain | https://jpcite.com (apex + www) + https://api.jpcite.com (API + MCP) |
| PyPI | `pip install autonomath-mcp` (legacy distribution name retained on purpose) |
| npm | `@bookyou/jpcite` (current) / `@autonomath/sdk` (legacy republish staged) |
| Repo | `shigetosidumeda-cyber/autonomath-mcp` |
| Pricing | **¥3 per billable unit** (税込 ¥3.30) metered via Stripe + anonymous **3 req/day per IP** free (JST 翌日 00:00 リセット) |
| Acquisition | **100% organic** (SEO + GEO + Agent-led Growth). No paid ads. No cold outreach. No sales calls. |
| Ops mode | **Solo + zero-touch**. No CS team. No onboarding calls. No DPA negotiation. No Slack Connect. |

## 2. Hard constraints (non-negotiable — treat as compile-time invariants)

These are **regression-class** rules. CI guards enforce most of them. Never weaken a guard to make a commit pass.

1. **¥3/req is the only commercial path.** Anonymous 3 req/day is the only free path. No tier UI, no "Free tier", "Starter", "Pro", `tier-badge` CSS, seat counters, annual minimums.
2. **100% organic acquisition.** No ads, no cold mail, no sales calls, no Slack Connect, no onboarding calls.
3. **No LLM API in production code paths.** Banned imports under `src/`, `scripts/cron/`, `scripts/etl/`, `tests/`: `anthropic`, `openai`, `google.generativeai`, `claude_agent_sdk`. Banned env vars on real code lines: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY`, `GOOGLE_API_KEY`. CI guard: `tests/test_no_llm_in_production.py`. Operator-only offline tools that genuinely need an LLM live under `tools/offline/`.
4. **No mocked DB in integration tests.** A past incident had mocked tests pass while a production migration failed. Integration tests must hit a real SQLite fixture.
5. **First-party sources only.** Aggregators (noukaweb, hojyokin-portal, biz.stayway, etc.) are **banned** from `source_url`. Government ministry / prefecture / 政策金融公庫 / 中小機構 only. Past phantom-moat incidents created 詐欺 risk.
6. **No silent `source_url` refetch.** Never rewrite `source_fetched_at` without an actual fetch. The column's honesty is load-bearing under 景表法 / 消費者契約法.
7. **Don't revive the "jpintel" brand in user-facing copy.** It collides with Intel (著名商標濃厚). Internal imports / paths are fine; site, README, marketing strings are not. The user-facing product is **jpcite**; the operator is **Bookyou株式会社**.
8. **Never rename `src/jpintel_mcp/` → `src/autonomath_mcp/`.** PyPI is `autonomath-mcp`; the import path is the legacy `jpintel_mcp`. Renaming breaks every consumer.
9. **No `--no-verify` / `--no-gpg-sign` push.** Fix the hook instead. Use `scripts/safe_commit.sh` to detect silent commit aborts.
10. **`live_aws_commands_allowed: false` is absolute.** AWS canary lives under operator-token gate. Mock / dry-run is the default. Live flips happen only on explicit user instruction.

## 3. Architecture pointer

Package is published as `autonomath-mcp` on PyPI; the source dir is `src/jpintel_mcp/`. **Do not rename the source dir.**

```
src/jpintel_mcp/
  api/        FastAPI REST mounted at /v1/*
  mcp/        FastMCP stdio + Streamable HTTP server
  ingest/     Data ingestion + canonical tier scoring
  db/         SQLite migrations + query helpers
  billing/    Stripe metered billing
  email/      Transactional email
agent_runtime/  Pydantic contracts + JPCIR JSON schema + envelope guards

data/jpintel.db        ~352 MB primary jpintel-side DB (FTS5 trigram)
autonomath.db (root)   ~9.4 GB unified primary DB (post migration 032)

site/                  21,000+ generated HTML SEO pages → Cloudflare Pages
docs/                  mkdocs sources, runbooks, recipes, cookbook
sdk/                   TypeScript / Python / Chrome / VSCode / Agents bindings
scripts/               Generators, migrations (101+), cron, etl, ops
.github/workflows/     CI + nightly cron + deploy
fly.toml               Fly.io Tokyo deployment
schemas/jpcir/         20 JSON schemas (jpcir contract layer)
```

Indexes and stores: **FAISS** (IVF+PQ, `nprobe=8` floor), **OpenSearch** (full-text), **SQLite FTS5 trigram** (`programs_fts`, with the 単一漢字 false-positive caveat — phrase-quote 2+ character compounds).

## 4. Live counts — DO NOT HARDCODE IN AGENT ENTRY FILES

Tool / route / OpenAPI path counts drift on every wave. Hardcoding any number in this section or in any agent entry shim is forbidden. Always read from the **live** sources below.

- **MCP tool count (canonical published)** → `scripts/distribution_manifest.yml: tool_count_default_gates`
- **MCP tool count (runtime, live)** → `len(await mcp.list_tools())` from a Python REPL after `from jpintel_mcp.mcp.server import build_mcp`
- **REST route count (runtime)** → `len(app.routes)` after `from jpintel_mcp.api.main import app`
- **OpenAPI path count** → `jq '.paths | length' docs/openapi/v1.json`
- **Searchable programs / total programs / tier breakdown** → `scripts/distribution_manifest.yml` (`searchable_programs_total`, `total_programs`, `tier_c_count`, etc.)
- **Drift check** → `python scripts/check_distribution_manifest_drift.py` (run before bumping any manifest)
- **Runtime probe** → `python scripts/probe_runtime_distribution.py` (live tools + routes + openapi paths in one pass)

If you find a hardcoded count in any agent entry file (`AGENTS.md` / `CLAUDE.md` / `.agent.md` / `.cursorrules` / `.windsurfrules` / `.mcp.json`), that is a defect — replace with a pointer to the live source above. CI guard: `tests/test_agent_entry_sot.py`.

## 5. Key commands

```bash
# Install (dev + site extras; use .venv/bin/* below)
pip install -e ".[dev,site]"
playwright install chromium                # only needed for e2e suite

# Run API locally
.venv/bin/uvicorn jpintel_mcp.api.main:app --reload --port 8080

# Run MCP server (stdio)
.venv/bin/autonomath-mcp

# Regenerate per-program SEO pages
.venv/bin/python scripts/generate_program_pages.py

# Tests (full / e2e)
.venv/bin/pytest                            # unit + integration
.venv/bin/pytest tests/e2e/                 # Playwright e2e
.venv/bin/pytest -n 6                       # xdist sweet spot (NOT -n auto)

# DB inspection
sqlite3 data/jpintel.db "SELECT tier, COUNT(*) FROM programs WHERE excluded=0 GROUP BY tier;"

# OpenAPI regenerate + manifest drift check
.venv/bin/python scripts/export_openapi.py --out docs/openapi/v1.json
.venv/bin/python scripts/check_distribution_manifest_drift.py

# Make targets (see `make help`)
make mcp                                    # MCP static drift check
make ci-budget-check                        # AWS canary budget verification
```

**Commit**: use `scripts/safe_commit.sh -m "..."` (defends against pre-commit auto-fix silent-abort).

## 6. Quality gates (before deploying)

- **pre-commit** — `.pre-commit-config.yaml` runs ruff / mypy / hooks. Never `--no-verify`.
- **mypy strict 0 errors** — `mypy --strict src/`. Regression is red.
- **ruff 0 errors** — `ruff check`. Targets sync with `scripts/distribution_manifest.yml`.
- **pytest** — full suite green. `-n 6` for xdist parallelism.
- **OpenAPI regen** — `scripts/export_openapi.py --out docs/openapi/v1.json`. Drift check after.
- **mkdocs build --strict** — docs build clean.
- **production gate 7/7** — `scripts/ops/release_readiness.py --json` (or equivalent CI workflow).
- **Post-deploy smoke** — sleep ≥60s, `curl --max-time ≥30s` (Fly p99 swap latency).

## 7. What NOT to do

The full failure-mode list lives in §2. The shortest possible "do not" list:

1. **No LLM API in `src/` / `scripts/cron/` / `scripts/etl/` / `tests/`.** (constraint 3)
2. **No tier UI / paid ads / sales calls.** (constraints 1 + 2)
3. **No aggregator URLs in `source_url`.** (constraint 5)
4. **No mocked DB in integration tests.** (constraint 4)
5. **No `--no-verify` / `--no-gpg-sign`.** (constraint 9)
6. **No live AWS canary flip without explicit user instruction.** (constraint 10)

Additional repository-hygiene rules:

- Never commit `data/jpintel.db.bak.*`, `.wrangler/`, `.venv/`, secrets in `.env*` other than `.env.example`.
- Never hand-edit a generated `site/programs/{slug}.html` — it will be overwritten. Edit the generator under `scripts/generate_*_pages.py`.
- Never lower the post-deploy smoke `sleep` / `--max-time` to "speed up CI" — the Fly Tokyo p99 swap distribution leaves no headroom under 60s.
- Never re-enable full-scan ops (`sha256sum` / `PRAGMA integrity_check` / `PRAGMA quick_check`) on multi-GB DBs at boot.

## 8. Memory pointer

Daily operator state, project status, and cross-session feedback live at `memory/MEMORY.md` (operator-side, not in repo). For repo-side persistent reference docs see `docs/_internal/` (canonical SOT docs, runbooks, historical wave logs).

When you discover a new project rule that should persist across sessions, update `memory/MEMORY.md` first; copy the durable subset into this file (`AGENTS.md`) only after the operator confirms it is a repo-wide invariant.

## 9. Vendor-specific shim files

Each of these files defers to **this** file. They exist for vendor-specific harness quirks (auto-injection paths, IDE features). Hard rules and counts MUST NOT be duplicated in them.

- `CLAUDE.md` — Claude Code session-start shim (Anthropic-specific tone, memory hooks, skill list).
- `.agent.md` — vendor-neutral fallback shim for harnesses that look for it first.
- `.cursorrules` — Cursor IDE auto-injection (Cursor-specific behavior only).
- `.windsurfrules` — Windsurf IDE auto-injection (Windsurf-specific behavior only).
- `.mcp.json` — MCP client root config (stdio server entry, env vars, no counts).

## 10. Discovery surfaces (public)

For agents that consume jpcite **from outside** the repo:

- `https://jpcite.com/llms.txt` — site-wide AI ingestion index (llms.txt v2).
- `https://jpcite.com/openapi.json` — OpenAPI 3.1 spec.
- `https://jpcite.com/agent.json` — agent-friendly capability summary.
- `https://jpcite.com/openapi.agent.gpt30.json` — slim 30-tool subset for GPT Actions.
- `https://jpcite.com/.well-known/mcp.json` — MCP capability descriptor.
- `https://jpcite.com/agents.json` — typed agent registry.
- Static markdown companions: every `*.html` has a sibling `*.html.md` with frontmatter (`est_tokens`, `canonical`, `fetched_at`, `license`). Prefer the `.md` over the `.html` for ingestion.

## 11. See also

- `docs/_internal/historical/CLAUDE_WAVE_HISTORY_2026_05_06_2026_05_16.md` — Wave 17..51 / tick 1..150 historical log (archived 2026-05-17).
- `docs/_internal/AGENT_HARNESS_REMEDIATION_PLAN_2026_05_17.md` — full deep-dive remediation plan that motivated this SOT migration.
- `docs/_internal/HARNESS_H3_AGENTS_SOT_2026_05_17.md` — this migration's landing notes.
- `DIRECTORY.md` — directory map.
- `docs/quickstart/dev_5min.md` — 5-minute localhost → CF Pages preview deploy.
- `docs/agents.md` — sample integrations (Anthropic / OpenAI / Cursor / Continue / GPT Actions).
