# AutonoMath — MCP Registry Submission Runbook

Product: **AutonoMath** (PyPI: `autonomath-mcp`). Operator: Bookyou株式会社 / info@bookyou.net.
Target launch: 2026-05-06. Last audited: 2026-04-24.

## Canonical submission data

| Field | Value |
|---|---|
| display_name | AutonoMath — 日本の制度 MCP (89 tools) |
| registry_id | `io.github.AutonoMath/autonomath-mcp` |
| repo | `https://github.com/shigetosidumeda-cyber/jpintel-mcp` |
| homepage | `https://jpcite.com` |
| pypi_package | `autonomath-mcp` |
| install | `uvx autonomath-mcp` / `pip install autonomath-mcp` |
| protocol | `2025-06-18` |
| tool_count | 66 (38 core: 15 base + 5 one-shot + 18 expansion; + 28 autonomath: 17 V1 + 4 V4 universal + 7 Phase A) |
| transport | stdio |
| license | MIT |
| language | Python >=3.11 |
| categories | government, legal, finance |

### Short description (≤160 chars)

```
AutonoMath: 66-tool MCP (38 core + 28 autonomath entity-fact DB) over Japanese primary-gov data — 13,578 programs + 503,930 entities + 6.12M facts + 23,805 relations, 181 exclusion rules, 3-axis loan risk. ¥3/req; 50/月 free.
```

### Long description (≤500 chars)

```
AutonoMath provides structured access to Japanese public-program data via 89 MCP tools (protocol
2025-06-18): 38 core (13,578 programs 補助金/融資/税制/認定 + 2,286 採択事例 + 108 融資
担保/個人保証人/第三者保証人 三軸分解 + 1,185 行政処分 + laws e-Gov CC-BY 9,484 rows + tax rulesets
インボイス/電帳法 35 rows + court_decisions 2,065 rows + bids 362 rows + invoice registrants 国税庁 PDL v1.0 13,801 rows delta) + 28 autonomath
(entity-fact DB: 503,930 entities + 6.12M facts + 23,805 relations + 335,605 aliases across
tax measures / certifications / laws / authorities / loans / mutual insurance).
181 structural exclusion/prerequisite rules; cross-dataset glue: trace_program_to_law /
find_cases_by_law / combined_compliance_check. 99%+ rows: source_url + fetched_at; no aggregators.
FTS5 trigram tokenizer (Japanese). ¥3/req tax-excl (¥3.30 incl); 50 req/月 per IP free
(JST 月初リセット, no key required). Bookyou株式会社 / info@bookyou.net.
```

## Launch-day publish command (MCP Official Registry)

> **Do NOT run before 2026-05-06 launch day.**

```bash
# Requires: GITHUB_TOKEN with repo:read scope (or GitHub OIDC from Actions)
# server.json must already be committed and version-tagged.
mcp publish server.json
```

Credentials / secrets required:
- `GITHUB_TOKEN` — GitHub OAuth token for `AutonoMath` org (or OIDC in CI)
- No additional secrets; the MCP publisher CLI authenticates via GitHub and resolves the `io.github.AutonoMath/` namespace automatically.

After publish: listing propagates to PulseMCP within ~1 week and to several downstream aggregators within 24 h.

---

## 1. Official MCP Registry  [PRIMARY]

- URL: https://registry.modelcontextprotocol.io/
- Source repo: https://github.com/modelcontextprotocol/registry
- Method: `mcp publish server.json` (CLI auth via GitHub OAuth or OIDC)
- Namespace: `io.github.AutonoMath/autonomath-mcp`
- Schema: `https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json`
- Required fields: `$schema`, `name`, `version`, `description`, `packages[]` with `registry_type: pypi`, `identifier: autonomath-mcp`, `version`, `transport.type: stdio`
- Review: automated, near-instant after CLI push
- Propagates to: PulseMCP, mcp.so, several downstream aggregators

## 2. Smithery  [YAML + AUTO-INDEX]

- URL: https://smithery.ai
- Method: `smithery.yaml` in repo root is auto-indexed when repo is public; claim listing via Smithery dashboard
- Manifest: `/smithery.yaml` (already configured)
- configSchema property names: `autonomathApiKey`, `autonomathApiBase`
- Review: daily crawl + optional manual claim

## 3. Glama  [AUTO]

- URL: https://glama.ai/mcp/servers
- Method: fully auto-indexed from public GitHub repo; no form to fill
- Badge URL: `https://glama.ai/mcp/servers/AutonoMath/autonomath-mcp/badges/score.svg`
- Action: push complete public repo with README + MCP manifest; listing appears within daily crawl
- Review: automatic, daily

## 4. Anthropic DXT / Claude Desktop Extension  [MCPB BUNDLE]

- Distribution: `autonomath-mcp.mcpb` bundle at https://jpcite.com/downloads/autonomath-mcp.mcpb
- Manifest: `dxt/manifest.json` (already configured)
- Install: users download and double-click `.mcpb`; Claude Desktop installs automatically
- No registry submission needed; the DXT format is self-distributing

## 5. Cursor Marketplace  [MANUAL FORM]

- URL: https://cursor.com/marketplace (or via Cursor IDE plugin submission)
- Method: submit repo URL + description via web form
- Review: manual, typically days

## 6. PulseMCP  [AUTO-INGEST VIA OFFICIAL REGISTRY]

- URL: https://www.pulsemcp.com/
- Submit: https://www.pulsemcp.com/submit
- Mechanism: ingests the Official MCP Registry daily, processes weekly; if published to #1 above, listing appears within ~1 week
- Direct form exists for corrections / expedited listing
- Review: weekly batch, hand-reviewed by founder

## 7. Awesome MCP Servers (punkpeye)  [MANUAL PR]

- URL: https://github.com/punkpeye/awesome-mcp-servers
- Method: PR adding one line to `README.md` under `Finance & Fintech`, alphabetical order
- Entry draft:
  ```
  - [AutonoMath/autonomath-mcp](https://github.com/shigetosidumeda-cyber/jpintel-mcp) 🐍 ☁️ 🍎 🪟 🐧 — AutonoMath: 38-tool core (+28 autonomath = 66) MCP over 13,578 Japanese public programs, 181 exclusion rules, 3-axis loan risk, laws (9,484 rows, continually loading) + tax rulesets (35 rows) + court_decisions (2,065 rows) + bids (362 rows) + invoice registrants (13,801 rows delta-only) live. ¥3/req; 50/月 free. `uvx autonomath-mcp`
  ```
- Review: maintainer-gated, usually days

## 8. mcp.so  [FORM / GITHUB-ISSUE]

- URL: https://mcp.so/submit
- Method: GitHub issue or web form; large traffic directory
- Review: manual or semi-auto

## 9. MCP Hunt (mcphunt.com)  [DUAL URL CAUTION]

- `mcphunt.com` — listing directory; free submission via site form
- `mcp-hunt.com` — separate GitHub-analysis tool (auto-crawls public repos); no manual submit needed
- Review: community upvotes + curation; coordinate upvotes on 2026-05-06

## 10. MCP Market (mcpmarket.com)  [MANUAL FORM]

- URL: https://mcpmarket.com/submit
- Method: web form (repo URL + description + category)
- Review: manual, typically days

## 11. MCP Server Finder  [MANUAL EMAIL]

- URL: https://www.mcpserverfinder.com/
- Method: email to `info@mcpserverfinder.com`
- Review: manual, timing variable

## 12. Cline MCP Marketplace  [GITHUB PR]

- URL: https://github.com/cline/mcp-marketplace
- Method: PR; gets `autonomath-mcp` inside the Cline client directly
- Review: maintainer-gated

## 13. mcpservers.org  [WEB FORM]

- URL: https://mcpservers.org/submit
- Method: web form (Awesome MCP web mirror)
- Review: auto-mirrors punkpeye/awesome-mcp-servers

## Skipped / Ineligible

- **mcpt** — sunsetted April 2025 by Mintlify; redirect to Official MCP Registry
- **MACH Alliance MCP Registry** — commerce-vertical only, not a fit
- **Enterprise-only registries** (e.g., MCPJungle self-host) — self-host tools, not public listings

## Priority Order (launch day: 2026-05-06)

| Step | Registry | Method | Est. time |
|---|---|---|---|
| 1 | Official MCP Registry | `mcp publish server.json` | 15 min |
| 2 | Glama | auto; wait 24 h | 0 min |
| 3 | Smithery | verify auto-index + claim | 10 min |
| 4 | PulseMCP | verify ingest 24 h after #1; submit form if missing | 5 min |
| 5 | Awesome MCP Servers PR | GitHub PR | 20 min |
| 6 | mcp.so | form / issue | 10 min |
| 7 | Cursor Marketplace | web form | 10 min |
| 8 | MCP Market | web form | 10 min |
| 9 | MCP Hunt | form + coordinate upvotes | 15 min |
| 10 | Cline MCP Marketplace | GitHub PR | 15 min |
| 11 | MCP Server Finder | email | 5 min |
| 12 | mcpservers.org | web form | 5 min |

---

## Launch-day publish runbook (2026-05-06)

> **Solo operator guide.** Run every step in order. Do NOT skip ahead. Do NOT run any publish command before all prerequisites are green.

### 1. Prerequisites checklist

Run all checks before touching any publish command. All must pass.

```bash
# 1a. Version parity: pyproject.toml == server.json
python3 -c "
import json, re
pv = re.search(r'version\s*=\s*\"(.+?)\"', open('pyproject.toml').read()).group(1)
sv = json.load(open('server.json'))['version']
assert pv == sv, f'VERSION MISMATCH: pyproject={pv} server.json={sv}'
print(f'OK versions match: {pv}')
"

# 1b. OpenAPI spec regenerated and diff is empty
.venv/bin/python scripts/export_openapi.py > /tmp/openapi_check.json
diff /tmp/openapi_check.json docs/openapi/v1.json && echo "OK openapi spec up to date" || echo "FAIL: regenerate openapi first"

# 1c. Full test suite (459+ tests)
.venv/bin/pytest --tb=short -q
# Must exit 0 with no failures or errors

# 1d. Docs build
.venv/bin/mkdocs build --strict
# Must exit 0 with no warnings

# 1e. Fly.io secrets present (requires fly CLI + auth)
fly secrets list | grep -E "STRIPE_SECRET_KEY|STRIPE_PRICE_PER_REQUEST|SENTRY_DSN|API_BASE_URL"
# Must show all 4 secret names (values are masked — that is expected)

# 1f. Cloudflare Pages: open dashboard and confirm latest commit on main is deployed
# URL: https://dash.cloudflare.com → Pages → autonomath-mcp → Deployments
# Verify: Status = "Success", commit SHA matches `git rev-parse HEAD`

# 1g. DNS + TLS
for host in jpcite.com api.jpcite.com docs.jpcite.com; do
  curl -sSo /dev/null -w "%{http_code} %{ssl_verify_result} $host\n" "https://$host/" || echo "FAIL $host"
done
# All must return HTTP 2xx and ssl_verify_result=0
```

**Gate:** Do not proceed past this checklist until every item above exits cleanly. Fix failures before continuing.

---

### 2. Required secrets — load before starting

Open a terminal and export all of the following. These must stay in your shell session for the entire runbook.

```bash
export PYPI_TOKEN="pypi-..."          # PyPI API token (scope: autonomath-mcp project)
export MCP_REGISTRY_TOKEN="..."       # MCP registry publish token (GitHub OAuth or PAT)
# SMITHERY_API_KEY — only needed if Smithery blocks push; usually not required for GitHub push
# Claude Desktop extension: no token. Only the .mcpb file is needed.
```

**Where to find them:**
- `PYPI_TOKEN`: https://pypi.org/manage/account/token/ → scope to `autonomath-mcp` project
- `MCP_REGISTRY_TOKEN`: GitHub → Settings → Developer settings → Personal access tokens → repo:read scope on `AutonoMath/autonomath-mcp`

---

### 3. Publish sequence — strict order, do not parallelise

#### Step 1 — PyPI

```bash
# Build sdist + wheel
python -m build

# Verify what is in dist/ before uploading
ls -lh dist/
# Expected: autonomath_mcp-0.3.0-py3-none-any.whl + autonomath-mcp-0.3.0.tar.gz

# Upload (uses PYPI_TOKEN env var set above)
TWINE_USERNAME=__token__ TWINE_PASSWORD="$PYPI_TOKEN" twine upload dist/*

# Verify: open https://pypi.org/project/autonomath-mcp/0.3.0/ in browser
# Confirm version 0.3.0 is listed and the description renders correctly
```

#### Step 2 — Fly.io

```bash
# Deploy latest image to Tokyo region
fly deploy

# Watch logs until you see "listening on" or "startup complete"
fly logs

# Smoke test the live API
curl -s https://api.jpcite.com/readyz | python3 -m json.tool
# Expected: {"status":"ok"}
```

#### Step 3 — Cloudflare Pages

```bash
# Cloudflare Pages auto-deploys on push to main.
# This step is verification only — do NOT manually trigger.

# 1. Open: https://dash.cloudflare.com → Pages → autonomath-mcp → Deployments
# 2. Confirm the top deployment is "Success" and the commit SHA is current main.
# 3. Run a spot-check:
curl -sI https://jpcite.com/ | head -5
# Expected: HTTP/2 200, cf-ray header present

# Do NOT continue to Step 4 until this is confirmed green.
```

#### Step 4 — MCP Official Registry

```bash
# server.json must already be committed and version-tagged before this step.
# The CLI authenticates via MCP_REGISTRY_TOKEN (set above).

MCP_REGISTRY_TOKEN="$MCP_REGISTRY_TOKEN" mcp publish server.json

# Expected output: "Published io.github.AutonoMath/autonomath-mcp@0.3.0 successfully"
# Verify: https://registry.modelcontextprotocol.io/servers/io.github.AutonoMath/autonomath-mcp
```

#### Step 5 — Smithery

```bash
# Smithery auto-indexes when the repo is public and smithery.yaml is present.
# Push to main triggers the crawl (the deploy to Fly.io in Step 2 was already on main).
# Verify (wait up to 30 min after push):
# https://smithery.ai/server/autonomath-mcp
# Confirm: description, install command, and tool count render correctly.
# If not yet indexed after 1 hour: claim via Smithery dashboard (dashboard.smithery.ai).
```

#### Step 6 — DXT (Claude Desktop Extension)

```bash
# Verify the .mcpb bundle is current before submission.
ls -lh autonomath-mcp.mcpb
# If stale (bundle predates today's build), regenerate:
bash scripts/build_mcpb.sh

# Submit:
# 1. Open Claude Desktop → Settings → Extensions → Submit Extension
# 2. Upload autonomath-mcp.mcpb
# 3. Fill in display name "AutonoMath" and description (copy from mcp_registries.md § Short description)
# 4. Note the submission ID for follow-up
```

#### Step 7 — Manual directory submissions

Submit in order; each should take < 10 min.

| # | Registry | URL | Notes |
|---|----------|-----|-------|
| 7a | Cursor Marketplace | https://cursor.com/marketplace (plugin submission form) | Paste repo URL + short description |
| 7b | Cline MCP Marketplace | https://github.com/cline/mcp-marketplace — open a PR | Add one line to the JSON index; follow CONTRIBUTING.md |
| 7c | mcp.so | https://mcp.so/submit | GitHub issue or web form |
| 7d | mcp-get | Check https://github.com/mcp-get/community-servers — open PR | Add `autonomath-mcp` entry |
| 7e | Glama | https://glama.ai/mcp/servers — auto-indexed; verify listing after 24 h | No action if repo is public |
| 7f | mcpservers.org | https://mcpservers.org/submit | Mirrors punkpeye/awesome-mcp-servers — if PR #5a (below) merges, auto-appears |
| 7g | MCP Hunt | https://mcphunt.com (form) | Coordinate upvotes for 2026-05-06 |

#### Step 8 — Awesome MCP Servers PR

```bash
# Fork punkpeye/awesome-mcp-servers, add one line under Finance & Fintech:
# - [AutonoMath/autonomath-mcp](https://github.com/shigetosidumeda-cyber/jpintel-mcp) 🐍 ☁️ 🍎 🪟 🐧 —
#   AutonoMath: 66-tool MCP over 13,578 Japanese public programs, 181 exclusion rules,
#   3-axis loan risk, laws/court/bids/tax/invoice. ¥3/req; 50/月 free. `uvx autonomath-mcp`

gh repo fork punkpeye/awesome-mcp-servers --clone
# Edit README.md, then:
gh pr create --title "Add AutonoMath: 66-tool Japanese gov-data MCP" \
  --body "AutonoMath provides structured access to 13,578 Japanese public programs (補助金/融資/税制/認定) via 89 MCP tools (38 core + 28 autonomath entity-fact DB: 503,930 entities + 6.12M facts + 23,805 relations). Laws (9,484 rows, continually loading) + tax rulesets (35 rows) + court_decisions (2,065 rows) + bids (362 rows) + invoice registrants (13,801 rows delta-only mirror) live. 99%+ rows: primary-source lineage. 181 exclusion rules, 3-axis loan risk. ¥3/req metered; 50/月 free."
```

#### Step 9 — Zenn launch article

```bash
# Set published: true in the front-matter and push.
# File: content/zenn/launch_day_1_developer.md
# Change: published: false → published: true
# Push to main and verify at: https://zenn.dev/autonomath/articles/<slug>
```

#### Step 10 — HN Show HN

```bash
# Post content is in: content/launch/hn_show.md
# Go to: https://news.ycombinator.com/submit
# Title must start with "Show HN:"
# URL: https://jpcite.com
# Text: copy from hn_show.md (plain text, no markdown)
# Note the HN item URL immediately — monitor for comments
```

#### Step 11 — Product Hunt Japan

```bash
# Post content is in: content/launch/ph_jp.md
# Go to: https://www.producthunt.com
# Use "Post a product" (Japan time 00:01 JST = best slot)
# Copy tagline, description, and media from ph_jp.md
```

---

### 4. Rollback procedure

| Component | Rollback command / action |
|-----------|--------------------------|
| PyPI | `pip yank autonomath-mcp==0.3.0` (yanked versions still installable with `--pre` but hidden from search). Irreversible to fully delete — yank is the only safe option. |
| Fly.io | `fly releases` to list image SHAs. `fly deploy --image <prev-image-sha>` to roll back. |
| Cloudflare Pages | Dashboard → Deployments → find previous successful deploy → click "Rollback to this deployment". |
| MCP registry | No unpublish endpoint. POST a PATCH to update the manifest to a known-good version: `mcp publish server.json` with corrected content. |
| Zenn article | Edit front-matter: `published: false`, push to main. Article disappears from public listing within minutes. |
| HN / PH | Cannot delete a submitted post. Add a comment "EDIT: issue found, see follow-up" and link to a corrected post if critical. |

---

### 5. Post-launch monitoring — first 6 hours

Run all of these in parallel from launch moment (T+0):

```bash
# Terminal 1: Fly.io live logs
fly logs --app autonomath-mcp

# Terminal 2: Structured log tail for 0-result queries and billing events
fly ssh console --app autonomath-mcp -C "tail -f /app/logs/structured.jsonl | grep -E 'result_count\":0|billing_event'"

# Terminal 3: Health check loop (every 5 min)
while true; do
  curl -sS https://api.jpcite.com/readyz && echo " OK $(date)" || echo "FAIL $(date)"
  sleep 300
done
```

**Sentry dashboard:** https://sentry.io/organizations/<your-org>/issues/
- Check every 30 minutes for new error groups.
- Any P0 error (5xx spike, DB lock, Stripe webhook failure) → rollback Fly.io immediately.

**HN thread:** https://news.ycombinator.com/item?id=<hn-item-id>
- Reply to every comment within 30 minutes of posting. Set a phone alarm.

**PH comments:** https://www.producthunt.com/products/autonomath
- Reply within 1 hour. Especially address any "does it cover X ministry?" questions with the specific tool name.

---

### 6. Human-input gaps (requires action before 2026-05-06)

The following items cannot be automated and require manual preparation:

1. **`PYPI_TOKEN`** — must be pre-created at https://pypi.org/manage/account/token/ scoped to `autonomath-mcp`. Confirm it is saved in your password manager before launch day.
2. **`MCP_REGISTRY_TOKEN`** — must be a GitHub PAT with `repo:read` on `AutonoMath/autonomath-mcp`. Confirm namespace `io.github.AutonoMath` is already claimed in the registry dashboard (https://registry.modelcontextprotocol.io) before launch day.
3. **`mcp publish` CLI availability** — the `mcp[cli]` package as of 2026-04-24 does **not** include a `publish` subcommand (only `version`, `dev`, `run`, `install`). Verify the CLI has grown a `publish` command before launch day: `uvx --from "mcp[cli]" mcp --help`. If absent, use the registry's REST API directly (`POST /v1/servers` with `MCP_REGISTRY_TOKEN`).
4. **Smithery API key** — check https://dashboard.smithery.ai before launch. If auto-index has not picked up the repo, you may need a key to trigger a manual crawl.
5. **`autonomath-mcp.mcpb` bundle** — regenerate the bundle close to launch (within 48 h) so it reflects the final tool list and version: `bash scripts/build_mcpb.sh`.
6. **Zenn slug** — confirm `content/zenn/launch_day_1_developer.md` has a stable slug set in front-matter. Zenn does not let you change the slug post-publish.
7. **DNS TTLs** — lower `jpcite.com`, `api.jpcite.com`, and `docs.jpcite.com` TTLs to 60 s at T-24 h so any last-minute DNS change propagates fast. Restore to 3600 at T+6 h.
