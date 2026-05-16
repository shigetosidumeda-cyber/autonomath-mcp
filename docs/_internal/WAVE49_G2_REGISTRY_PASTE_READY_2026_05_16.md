---
wave: 49
stream: G2
tick: 6
prepared: 2026-05-16
status: PASTE-READY — operator paste only (Discord + web form)
target_registries: [smithery_ai, glama_ai, pulsemcp]
upstream_verified: 2026-05-16T01:24:31Z (Anthropic Official Registry LIVE v0.3.2/0.3.3/0.3.4/0.3.5/0.4.0; PyPI autonomath-mcp v0.4.0)
target_listings: 2026-05-16 status = Smithery 308, Glama 404
operator_action_required: yes
constraint: do_not_submit_self
---

# Wave 49 G2 — Smithery + Glama + PulseMCP Paste-Ready Pack

This is the operator paste-ready successor to `WAVE49_G2_REGISTRY_ESCALATION_DRAFT.md`.
All JSON / message bodies / URLs / Discord channels are pre-built so the operator
(梅田) can complete all 3 registry submissions in under 5 minutes total.

**Constraint**: Discord paste + web form submission are **operator-only** actions.
Claude does NOT submit on behalf of the operator (memory: `feedback_zero_touch_solo`).

---

## Operator action list (5-minute checklist)

| # | Action | Time | URL / Channel |
|---|---|---|---|
| 1 | Smithery Discord paste (escalation) | 1 min | https://discord.com/invite/smithery → `#support` |
| 2 | Glama Discord paste (escalation) | 1 min | https://discord.gg/C3eCXhYWtJ → `#support` |
| 3 | PulseMCP web-form submit | 2 min | https://www.pulsemcp.com/submit |
| 4 | Record paste timestamps to `analytics/registry_status_w49.json` | 1 min | (file-local, no URL) |

**Total wall-clock: ~5 minutes.**
Auto-crawl ETAs after paste: Smithery 24-72h, Glama 24-48h, PulseMCP 7d.

---

## §1. Smithery — Discord escalation paste

### 1.1 Where to paste

- **Primary**: https://discord.com/invite/smithery → join (one-time) → `#support`
  channel
- **Fallback channel**: `#mcp-servers` (same Discord server)
- **Verified 2026-05-16**: `https://discord.gg/smithery` → 301 →
  `https://discord.com/invite/smithery` (live, resolves)

### 1.2 Paste body (verbatim)

```
Hello Smithery team,

jpcite (PyPI: autonomath-mcp) — Japanese public-program evidence MCP —
has been submitted with smithery.yaml at repo root since 2026-04-23
(23 days ago), with v0.4.0 (155 tools) landed at Anthropic Official
Registry on 2026-05-15. However the Smithery listing is still 404 at
all expected slugs:

- https://smithery.ai/server/@bookyou/jpcite (308 redirect → 404)
- https://smithery.ai/server/jpcite (404)
- https://smithery.ai/server/bookyou/jpcite (404)

Repo: https://github.com/shigetosidumeda-cyber/autonomath-mcp
smithery.yaml id: "@bookyou/jpcite"
Anthropic Official Registry: LIVE v0.4.0 (verifiable via
https://registry.modelcontextprotocol.io/v0/servers?search=autonomath
— returns v0.3.2/0.3.3/0.3.4/0.3.5/0.4.0 entries today)
PyPI: autonomath-mcp v0.4.0 published (pip install autonomath-mcp==0.4.0)
GitHub: public, all canonical signals shipped (server.json + smithery.yaml
+ Dockerfile + LICENSE + README + topics, 155 tools declared, ¥3/billable
unit ¥3.30 tax-inclusive metered, 3 req/day per IP anonymous tier)

Could you check why our listing is returning 404 even after 16 days
since v0.3.2 + 1 day since v0.4.0? Specifically:
1. Is the smithery.yaml id "@bookyou/jpcite" being recognized as a valid
   namespace, or is the @ prefix tripping the parser?
2. Is there a claim flow pending that we missed (no claim email received
   at info@bookyou.net)?
3. Is the Anthropic Official Registry → Smithery auto-sync currently
   active for our entry?

Operator: Bookyou株式会社 (T8010001213708), contact info@bookyou.net.
Happy to provide additional metadata or run a re-submission flow.

Thank you for the directory work.
— Shigetoumi Umeda
```

### 1.3 Smithery `smithery.yaml` reference (for reviewer)

Located at repo root: https://github.com/shigetosidumeda-cyber/autonomath-mcp/blob/main/smithery.yaml

```yaml
id: "@bookyou/jpcite"
name: "jpcite"
qualifiedName: "@bookyou/jpcite"
startCommand:
  type: stdio
metadata:
  version: "0.4.0"
  displayName: "jpcite — Japanese public-program evidence MCP"
  repository: "https://github.com/shigetosidumeda-cyber/autonomath-mcp"
  license: "MIT"
  homepage: "https://jpcite.com"
```

### 1.4 URLs to share with reviewer (paste in follow-up if asked)

- Repo: `https://github.com/shigetosidumeda-cyber/autonomath-mcp`
- smithery.yaml: `https://github.com/shigetosidumeda-cyber/autonomath-mcp/blob/main/smithery.yaml`
- server.json: `https://jpcite.com/server.json`
- Anthropic Registry verify: `https://registry.modelcontextprotocol.io/v0/servers?search=autonomath`
- PyPI: `https://pypi.org/project/autonomath-mcp/0.4.0/`

---

## §2. Glama — Discord escalation paste

### 2.1 Where to paste

- **Primary**: https://discord.gg/C3eCXhYWtJ → join (one-time, may already
  be joined from W23 / W41) → `#support` channel
- **Fallback channel**: `#mcp-servers`
- **Verified 2026-05-16**: `https://glama.ai/discord` → 302 →
  `https://discord.gg/C3eCXhYWtJ` (live, resolves)

### 2.2 Paste body (verbatim — W49 G2 tick 6 current)

```
Hello Glama team,

This is a follow-up to my earlier escalation (W23 2026-05-11). Our MCP
server submitted via Anthropic Official Registry still isn't appearing
on Glama after 10+ days from v0.3.4 LIVE_CONFIRMED, and now v0.4.0
(155 tools) has just landed on the Anthropic Registry as well.

Server: io.github.shigetosidumeda-cyber/autonomath-mcp (brand: jpcite)
Anthropic Official Registry: LIVE v0.4.0 since 2026-05-15
  (verifiable via https://registry.modelcontextprotocol.io/v0/servers?search=autonomath
   — returns v0.3.2/0.3.3/0.3.4/0.3.5/0.4.0 entries today)
Glama listing expected at:
  https://glama.ai/mcp/servers/shigetosidumeda-cyber/autonomath-mcp (currently 404)
  https://glama.ai/mcp/servers/io.github.shigetosidumeda-cyber/autonomath-mcp (404)

Repo: https://github.com/shigetosidumeda-cyber/autonomath-mcp (public)
PyPI: autonomath-mcp v0.4.0 (published, installable via `uvx autonomath-mcp`)
Canonical signals at repo root:
  - server.json (MCP schema 2025-12-11 compliant, 155 tools declared)
  - mcp-server.json (Glama-specific manifest, 155 tools)
  - smithery.yaml (id: "@bookyou/jpcite")
  - Dockerfile, LICENSE (MIT), README with install command + tools list
  - GitHub topics: mcp-server, model-context-protocol, claude-mcp,
    smithery, glama, ai-agent-tools

Could you check whether something on our side is blocking discovery,
or trigger a manual re-crawl? PR #6192 on punkpeye/awesome-mcp-servers
remains blocked on the glama-bot score badge which depends on the Glama
listing being live.

Operator: Bookyou株式会社 (T8010001213708), contact info@bookyou.net.
¥3/billable unit (¥3.30 tax-incl) metered + 3 req/day per IP anonymous tier.

Thank you.
— Shigetoumi Umeda
```

### 2.3 Screenshot guidance (optional — if Glama asks for visual proof)

If a Glama maintainer requests visuals during the Discord thread, paste any
of these (all live and public, no auth required):

1. `https://github.com/shigetosidumeda-cyber/autonomath-mcp` — repo landing
   (shows smithery.yaml + server.json + mcp-server.json + README at root,
   topics include `mcp-server`/`model-context-protocol`/`smithery`/`glama`)
2. `https://jpcite.com/` — canonical site (shows ¥3/req pricing + 155 tools
   marker + Anthropic Registry badge)
3. `https://pypi.org/project/autonomath-mcp/0.4.0/` — PyPI listing for v0.4.0
4. `https://registry.modelcontextprotocol.io/v0/servers?search=autonomath`
   — JSON response showing v0.4.0 LIVE on Anthropic Official Registry

Capture screenshots with macOS `Cmd+Shift+4`, save to Desktop, drag-drop
into Discord. **DO NOT** upload screenshots containing internal secrets —
all 4 URLs above are public-safe.

---

## §3. PulseMCP — Web form submission

### 3.1 Where to submit

- **URL**: https://www.pulsemcp.com/submit
- **Method**: Web form (also auto-ingests Anthropic Registry — direct form
  is for corrections / expedited listing if auto-ingest hasn't propagated)
- **Verified 2026-05-16**: form live; only explicitly required field is
  the GitHub / canonical URL

### 3.2 Form values (paste verbatim into each field)

| Field | Paste value |
|---|---|
| Type | MCP Server |
| URL | `https://github.com/shigetosidumeda-cyber/autonomath-mcp` |
| Server name | `jpcite` |
| GitHub URL | `https://github.com/shigetosidumeda-cyber/autonomath-mcp` |
| Homepage URL | `https://jpcite.com` |
| Documentation URL | `https://jpcite.com/docs/` |
| License | `MIT` |
| Language | `Python` |
| Install command | `uvx autonomath-mcp` |
| Alternate install | `pip install autonomath-mcp` |
| Tool count | `155 at default gates` |
| Author / publisher | `Bookyou株式会社 (T8010001213708) — info@bookyou.net` |
| Contact email | `info@bookyou.net` |

### 3.3 Short description (one sentence, ~140 chars)

```
155 MCP tools over Japanese institutional data — subsidies, laws, court decisions, tax rulesets, invoice registrants — with primary-source URLs.
```

### 3.4 Long description (paragraph, paste verbatim)

```
jpcite (PyPI: autonomath-mcp) exposes Japanese institutional public data via 155 MCP tools at default gates (protocol 2025-06-18, stdio): 11,601 searchable programs (補助金 / 融資 / 税制 / 認定) + 2,286 採択事例 + 108 loan products with 3-axis guarantor decomposition (担保 / 個人保証人 / 第三者保証人) + 1,185 行政処分 + 6,493 laws full-text indexed + 9,484 law metadata records (e-Gov CC-BY) + 2,065 court decisions + 362 bids + 50 tax rulesets + 13,801 国税庁 qualified-invoice registrants (PDL v1.0) + 4,300 sourced compatibility pairs + 181 exclusion / prerequisite rules. Cross-dataset glue tools tie programs to statutes, statutes to court decisions, and stack tax / bid / law / case lookups in one call. Major public rows carry source_url + fetched_at. Pricing: ¥3/billable unit tax-exclusive (¥3.30 tax-inclusive) fully metered, first 3 requests/day per IP free (anonymous, JST next-day reset), no tier SKUs. Operator: Bookyou株式会社 (T8010001213708).

Disclaimer (税理士法 §52 fence): jpcite is information retrieval over published Japanese primary sources, not advice. It does not perform 税務代理 (税理士法 §52), 法律事務 (弁護士法 §72), 申請代理 (行政書士法 §1の2), or 労務判断 (社労士法). Verify primary-source URLs and consult licensed professionals for individual cases.
```

### 3.5 Categories / tags

```
Categories: Government, Legal, Finance, Compliance, Search
Tags: japan, japanese, government, subsidies, grants, loans, tax, laws, court-decisions, invoice, e-gov, primary-source, compliance, due-diligence, mcp-2025-06-18, stdio, python, 補助金, 助成金, 融資, 税制
```

### 3.6 Claude Desktop config (if asked)

```json
{
  "mcpServers": {
    "jpcite": {
      "command": "uvx",
      "args": ["autonomath-mcp"]
    }
  }
}
```

### 3.7 "Anything else?" / notes to reviewer

```
- Anthropic Official Registry LIVE v0.4.0 since 2026-05-15 (verifiable via https://registry.modelcontextprotocol.io/v0/servers?search=autonomath — returns 5 versions including 0.4.0).
- PyPI publication confirmed: https://pypi.org/project/autonomath-mcp/0.4.0/
- Honest tool count is 155 at default gates. Manifest bump landed 2026-05-15. The PyPI distribution name is autonomath-mcp (legacy distribution name retained); user-facing brand is jpcite.
- Major public rows carry source_url + fetched_at; aggregator domains (noukaweb / hojyokin-portal / biz.stayway) are banned from source_url to mitigate fraud risk on credit / DD use cases.
- Brand rename history: zeimu-kaikei.ai → AutonoMath → jpcite (2026-04-30 rename complete; canonical domain jpcite.com).
```

### 3.8 Screenshots (optional — PulseMCP rarely requires)

If asked, provide:
1. `search_programs` result for `q="東京都 農業 補助金"`
2. `trace_program_to_law` output with statutory basis
3. `dd_profile_am` output keyed by houjin_bangou

(All capturable from a local `uvx autonomath-mcp` session via Claude Desktop.)

---

## §4. After-paste — operator record-keeping

After completing §1-§3, append timestamps to `analytics/registry_status_w49.json`:

```json
{
  "platforms": [
    {
      "id": "smithery_ai",
      "escalation_log": [
        {"date": "2026-05-16", "channel": "discord", "result": "pasted_awaiting_reply"}
      ]
    },
    {
      "id": "glama_ai",
      "escalation_log_w49": [
        {"date": "2026-05-16", "channel": "discord", "result": "pasted_awaiting_reply"}
      ]
    },
    {
      "id": "pulsemcp",
      "submission_log": [
        {"date": "2026-05-16", "channel": "web_form", "result": "submitted_awaiting_ingest"}
      ]
    }
  ]
}
```

(Use `jq` or hand-edit; this file is git-tracked but only operator-edited.)

---

## §5. Expected response SLAs + escalation fallback

| Channel | Expected reply SLA | Fallback if no reply |
|---|---|---|
| Smithery Discord `#support` | 24-72h (W41 evidence: 24h) | GitHub Issue on smithery org repo |
| Glama Discord `#support` | 24-48h (W41 evidence: 144h no-reply) | PR #6192 comment on punkpeye/awesome-mcp-servers |
| PulseMCP web form | 7 days (weekly batch) | mailto: PulseMCP contact email |

**24h no-reply additional escalation paths**:
1. PR #6192 (punkpeye/awesome-mcp-servers) comment (Glama side)
2. X/Twitter DM `@glama_ai` / `@smithery_ai` (operator-only)
3. GitHub Issue on each registry's primary repo

**3 weeks no-reply abandon path**:
- Wave 50+ pivots to organic funnel via Anthropic Registry direct discovery
  + jpcite.com SEO/GEO (already 100% organic acquisition strategy)
- Smithery/Glama become optional discovery channels, not required ones

---

## §6. Verification commands (Claude / operator can run any time)

```bash
# 1. Confirm Anthropic Registry LIVE
curl -s 'https://registry.modelcontextprotocol.io/v0/servers?search=autonomath' \
  | python3 -c "import json,sys; d=json.load(sys.stdin); [print(s['server']['name'],'v',s['server']['version']) for s in d['servers'][:5]]"
# Expected: 5 entries 0.3.2 → 0.4.0

# 2. Confirm PyPI v0.4.0 published
curl -s 'https://pypi.org/pypi/autonomath-mcp/json' \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['info']['name'], d['info']['version'])"
# Expected: autonomath-mcp 0.4.0

# 3. Verify target listings still 404 / 308 (proves Discord paste is still needed)
curl -sI 'https://smithery.ai/server/@bookyou/jpcite' | head -1
# Expected: HTTP/2 308

curl -sI 'https://glama.ai/mcp/servers/shigetosidumeda-cyber/autonomath-mcp' | head -1
# Expected: HTTP/2 404

# 4. Verify Discord invite resolution
curl -sI 'https://discord.gg/smithery' | grep -i location | head -1
# Expected: location: https://discord.com/invite/smithery

curl -sI 'https://glama.ai/discord' | grep -i location | head -1
# Expected: location: https://discord.gg/C3eCXhYWtJ
```

---

## §7. Canonical facts (single source of truth — used in every submission)

| Field | Value |
|---|---|
| Product brand | jpcite |
| PyPI distribution | `autonomath-mcp` |
| Version | 0.4.0 |
| Repo | https://github.com/shigetosidumeda-cyber/autonomath-mcp |
| Homepage | https://jpcite.com |
| Docs | https://jpcite.com/docs/ |
| License | MIT |
| Language | Python ≥ 3.11 |
| MCP protocol | 2025-06-18 |
| Transport | stdio |
| Install | `uvx autonomath-mcp` |
| Tool count | 155 at default gates |
| OpenAPI paths | 307 |
| Pricing | ¥3/billable unit (¥3.30 tax-incl) fully metered |
| Free tier | 3 req/day per IP (anonymous, JST next-day reset) |
| Operator | Bookyou株式会社 (T8010001213708), 代表 梅田茂利, info@bookyou.net |

---

## §8. Logged at

- This paste-ready bundle: `docs/_internal/WAVE49_G2_REGISTRY_PASTE_READY_2026_05_16.md`
- Upstream escalation draft (superseded by this paste-ready bundle):
  `docs/_internal/WAVE49_G2_REGISTRY_ESCALATION_DRAFT.md`
- W23 escalation: `docs/_internal/mcp_registry_submissions/glama_discord_escalation.md`
- W41 attempt log: `docs/_internal/mcp_registry_submissions/glama_discord_attempt_w41.md`
- PulseMCP draft (canonical source): `scripts/registry_submissions/pulsemcp_submission.md`
- Smithery v3 submission spec: `docs/_internal/mcp_registry_submissions/smithery-submission-v3.md`
- W49 plan SOT: `docs/_internal/WAVE49_plan.md`

---

## §9. Memory bind

- `feedback_zero_touch_solo`: human-in-the-loop (Discord paste / web form) is
  minimized. This bundle is **operator one-shot paste** for all 3 registries.
- `feedback_no_user_operation_assumption`: gh CLI / curl / mcp publish are
  used wherever feasible (Anthropic Registry / PyPI / GitHub are all auto-publishable).
  Discord paste + PulseMCP web form remain the only **truly required** user
  actions (W23 + W41 + 2026-05-16 W49 G2 tick 6 verified no anonymous webhook
  exists for either Discord channel, and PulseMCP form has no API).
- `feedback_action_bias`: bundle ready immediately; operator paste does not
  block /loop continuation on parallel Wave 49 streams.
- `feedback_loop_never_stop`: this G2 deliverable is one tick in the eternal
  loop; Wave 49 G1/G3/G4/G5 + Wave 50 RC1 continue in parallel.
