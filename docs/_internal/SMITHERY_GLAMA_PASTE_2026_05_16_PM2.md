---
wave: 49
stream: G2
tick: 7 (PM2 refresh)
prepared: 2026-05-16 (PM2)
status: PASTE-READY — operator paste only (Discord)
target_registries: [smithery_ai, glama_ai]
supersedes: docs/_internal/WAVE49_G2_REGISTRY_PASTE_READY_2026_05_16.md (additive; original retained as historical state marker)
upstream_verified_2026-05-16_PM2:
  anthropic_official_registry: LIVE v0.3.2 / v0.3.3 / v0.3.4 / v0.3.5 / v0.4.0 (5 versions returned)
  pypi: autonomath-mcp v0.4.0 published
  discord_invites:
    smithery: https://discord.gg/smithery → 301 → https://discord.com/invite/smithery (live)
    glama: https://glama.ai/discord → 302 → https://discord.gg/C3eCXhYWtJ (live)
  target_listings:
    smithery: HTTP 308 (still redirect → 404, listing not surfaced)
    glama: HTTP 404 (still not crawled)
  live_site: https://jpcite.com → HTTP 200 (apex live), /healthz → HTTP 200
operator_action_required: yes
constraint: do_not_submit_self
---

# Wave 49 G2 — Smithery + Glama Discord Paste-Ready (2026-05-16 PM2 refresh)

This is the **PM2 refresh** of the Wave 49 G2 Smithery + Glama Discord escalation
paste-ready content. The original `WAVE49_G2_REGISTRY_PASTE_READY_2026_05_16.md`
(AM tick 6) remains the historical state marker. This PM2 doc carries the latest
state of the day for both registries.

**Constraint (HONEST)**: Discord paste IS user-only. Neither Smithery nor Glama
exposes an anonymous webhook / API / CLI path that Claude can call to submit a
support escalation. The user (梅田) must join each Discord server (one-time per
server) and paste the body below verbatim. See §3 below for the verification log
that confirms no automation path exists.

**Refresh delta vs AM tick 6 doc**:

| Field | AM tick 6 value | PM2 refresh value |
|---|---|---|
| Tool count (current state) | 155 (v0.4.0 PyPI) | **179** (Wave 59 Stream B top-10 outcome wrappers landed: 169 → 179) |
| Outcome catalog | n/a | **152** (Wave 65 financial markets cross packets landed; Wave 66 PII compliance pending → 162) |
| Release capsule SHA256 | n/a | **78b24c633b06660acc3ca1200084ab0c88769498fdfd3961d91d97029e36871c** (`site/releases/rc1-p0-bootstrap/release_capsule_manifest.json`, capsule_id `rc1-p0-bootstrap-2026-05-15`) |
| Live URL | https://jpcite.com (claim) | **https://jpcite.com → HTTP 200 verified 2026-05-16 PM2**, `/healthz` → HTTP 200 |
| PyPI version | 0.4.0 | 0.4.0 (no bump since AM tick 6) |
| Anthropic Registry | LIVE v0.4.0 | LIVE v0.4.0 (no version drift) |
| Target listing status | Smithery 308 → 404, Glama 404 | **Smithery 308 (still 404 via redirect), Glama 404 (still uncrawled)** |

The PM2 refresh keeps the verbatim Discord paste bodies but updates the **tool
count** to 179 + outcome catalog count to 152 + adds the release capsule SHA256
+ explicit `jpcite.com` HTTP 200 verification timestamp.

---

## §1. Smithery — Discord escalation paste (PM2 refresh)

### 1.1 Where to paste

- **Primary**: https://discord.com/invite/smithery → join (one-time) → `#support`
- **Fallback channel**: `#mcp-servers` (same Discord server)
- **Verified 2026-05-16 PM2**: `https://discord.gg/smithery` → 301 →
  `https://discord.com/invite/smithery` (live, resolves)

### 1.2 Paste body (verbatim — PM2 refresh)

```
Hello Smithery team,

jpcite (PyPI: autonomath-mcp) — Japanese public-program evidence MCP — has been
submitted with smithery.yaml at repo root since 2026-04-23 (23 days ago), with
v0.4.0 (179 MCP tools at default gates today after Wave 59 Stream B outcome
wrappers) landed at Anthropic Official Registry on 2026-05-15. However the
Smithery listing is still 404 at all expected slugs:

- https://smithery.ai/server/@bookyou/jpcite (308 redirect → 404)
- https://smithery.ai/server/jpcite (404)
- https://smithery.ai/server/bookyou/jpcite (404)

Verifiable state (re-checked 2026-05-16 PM2):
- Anthropic Official Registry: LIVE v0.3.2 / v0.3.3 / v0.3.4 / v0.3.5 / v0.4.0
  (5 versions returned)
  https://registry.modelcontextprotocol.io/v0/servers?search=autonomath
- PyPI: autonomath-mcp v0.4.0 (pip install autonomath-mcp==0.4.0)
- Live site: https://jpcite.com → HTTP 200 verified 2026-05-16 PM2,
  /healthz → HTTP 200
- Repo: https://github.com/shigetosidumeda-cyber/autonomath-mcp (public)
- smithery.yaml id: "@bookyou/jpcite"
- Release capsule: rc1-p0-bootstrap (capsule_id rc1-p0-bootstrap-2026-05-15;
  release_capsule_manifest.json SHA256:
  78b24c633b06660acc3ca1200084ab0c88769498fdfd3961d91d97029e36871c)
- Tool count today: 179 MCP tools at default gates (Wave 59 Stream B
  top-10 outcome wrappers landed since v0.4.0 manifest)
- Outcome catalog: 152 outcomes (Wave 65 financial markets cross packets
  landed; Wave 66 PII compliance series in progress → 162 target)
- Pricing: ¥3/billable unit tax-exclusive (¥3.30 tax-inclusive) fully metered,
  3 req/day per IP anonymous tier (JST next-day reset)

Could you check why our listing is returning 404 even after ~23 days since
v0.3.2 + 1 day since v0.4.0? Specifically:

1. Is the smithery.yaml id "@bookyou/jpcite" being recognized as a valid
   namespace, or is the @ prefix tripping the parser?
2. Is there a claim flow pending that we missed (no claim email received
   at info@bookyou.net)?
3. Is the Anthropic Official Registry → Smithery auto-sync currently active
   for our entry?

Operator: Bookyou株式会社 (T8010001213708), contact info@bookyou.net.
Happy to provide additional metadata or run a re-submission flow.

Thank you for the directory work.
— Shigetoumi Umeda
```

### 1.3 URLs to share with reviewer (paste in follow-up if asked)

- Repo: `https://github.com/shigetosidumeda-cyber/autonomath-mcp`
- smithery.yaml: `https://github.com/shigetosidumeda-cyber/autonomath-mcp/blob/main/smithery.yaml`
- server.json: `https://jpcite.com/server.json`
- Anthropic Registry verify: `https://registry.modelcontextprotocol.io/v0/servers?search=autonomath`
- PyPI: `https://pypi.org/project/autonomath-mcp/0.4.0/`
- Release capsule: `https://jpcite.com/releases/rc1-p0-bootstrap/release_capsule_manifest.json`

---

## §2. Glama — Discord escalation paste (PM2 refresh)

### 2.1 Where to paste

- **Primary**: https://discord.gg/C3eCXhYWtJ → join (one-time, may already be
  joined from W23 / W41) → `#support` channel
- **Fallback channel**: `#mcp-servers`
- **Verified 2026-05-16 PM2**: `https://glama.ai/discord` → 302 →
  `https://discord.gg/C3eCXhYWtJ` (live, resolves)

### 2.2 Paste body (verbatim — PM2 refresh)

```
Hello Glama team,

This is a follow-up to my earlier escalation (W23 2026-05-11 + W49 G2 AM tick 6
on 2026-05-16). Our MCP server submitted via Anthropic Official Registry still
isn't appearing on Glama after 10+ days from v0.3.4 LIVE_CONFIRMED, and v0.4.0
landed on the Anthropic Registry on 2026-05-15 with 179 MCP tools at default
gates today (Wave 59 Stream B top-10 outcome wrappers landed since v0.4.0).

Server: io.github.shigetosidumeda-cyber/autonomath-mcp (brand: jpcite)
Anthropic Official Registry: LIVE v0.4.0 since 2026-05-15
  (verifiable via https://registry.modelcontextprotocol.io/v0/servers?search=autonomath
   — returns v0.3.2 / v0.3.3 / v0.3.4 / v0.3.5 / v0.4.0 entries, re-checked
   2026-05-16 PM2)

Glama listing expected at:
  https://glama.ai/mcp/servers/shigetosidumeda-cyber/autonomath-mcp
    (re-checked 2026-05-16 PM2 → still HTTP 404)
  https://glama.ai/mcp/servers/io.github.shigetosidumeda-cyber/autonomath-mcp
    (re-checked 2026-05-16 PM2 → still HTTP 404)

Verifiable state (re-checked 2026-05-16 PM2):
- Repo: https://github.com/shigetosidumeda-cyber/autonomath-mcp (public)
- PyPI: autonomath-mcp v0.4.0 (uvx autonomath-mcp)
- Live site: https://jpcite.com → HTTP 200, /healthz → HTTP 200
- Canonical signals at repo root:
  - server.json (MCP schema 2025-12-11 compliant, 179 tools at default gates)
  - mcp-server.json (Glama-specific manifest)
  - smithery.yaml (id: "@bookyou/jpcite")
  - Dockerfile, LICENSE (MIT), README with install command + tools list
  - GitHub topics: mcp-server, model-context-protocol, claude-mcp, smithery,
    glama, ai-agent-tools
- Release capsule: rc1-p0-bootstrap (capsule_id rc1-p0-bootstrap-2026-05-15;
  release_capsule_manifest.json SHA256:
  78b24c633b06660acc3ca1200084ab0c88769498fdfd3961d91d97029e36871c)
- Outcome catalog: 152 outcomes today (Wave 65 financial markets cross packets
  landed; Wave 66 PII compliance series in progress → 162 target)

Could you check whether something on our side is blocking discovery, or
trigger a manual re-crawl? PR #6192 on punkpeye/awesome-mcp-servers remains
blocked on the glama-bot score badge which depends on the Glama listing
being live.

Operator: Bookyou株式会社 (T8010001213708), contact info@bookyou.net.
Pricing: ¥3/billable unit (¥3.30 tax-incl) metered + 3 req/day per IP
anonymous tier.

Thank you.
— Shigetoumi Umeda
```

### 2.3 URLs to share with reviewer (paste in follow-up if asked)

- Repo: `https://github.com/shigetosidumeda-cyber/autonomath-mcp`
- mcp-server.json: `https://github.com/shigetosidumeda-cyber/autonomath-mcp/blob/main/mcp-server.json`
- server.json: `https://jpcite.com/server.json`
- Anthropic Registry verify: `https://registry.modelcontextprotocol.io/v0/servers?search=autonomath`
- PyPI: `https://pypi.org/project/autonomath-mcp/0.4.0/`
- Release capsule: `https://jpcite.com/releases/rc1-p0-bootstrap/release_capsule_manifest.json`
- Live site (HTTP 200 verified PM2): `https://jpcite.com`

---

## §3. Why this is user-only (verify log, HONEST)

Per memory `feedback_no_user_operation_assumption` — claim "user 操作必要" only
after Claude exhausts 5+ automation paths. Verify log for Smithery + Glama
Discord paste (re-verified 2026-05-16 PM2):

| # | Automation attempt | Result | Status |
|---|---|---|---|
| 1 | `gh secret list` (any Discord webhook secret?) | none for smithery / glama | **no** |
| 2 | `gh workflow run` (any workflow to post to Discord?) | none for these channels | **no** |
| 3 | `mcp publish` (Anthropic Registry CLI) | already published; doesn't post to Discord | **no** |
| 4 | `curl -X POST` (Discord channel webhook) | Smithery + Glama `#support` channels do NOT expose anonymous webhooks; OAuth-bot-token required | **no** |
| 5 | `gh pr create` on registry repos | only awesome-mcp-servers has PR flow (PR #6192 already open); Smithery + Glama don't accept submissions via PR | **no** |
| 6 | Smithery `/api/submit` form | requires authenticated session, no anonymous form | **no** |
| 7 | Glama `/api/crawl-now` endpoint | does not exist (verified 2026-05-16) | **no** |

**Conclusion**: Discord paste IS user-only. The user (梅田) must join each
Discord server (one-time) and paste the bodies above verbatim. No CLI / API /
gh / curl path exists today.

---

## §4. Operator instructions (5-minute total)

| # | Action | Time | URL |
|---|---|---|---|
| 1 | Open https://discord.com/invite/smithery, join the server (one-time if not joined), go to `#support` channel, paste §1.2 body verbatim | 2 min | https://discord.com/invite/smithery |
| 2 | Open https://discord.gg/C3eCXhYWtJ, join the server (one-time if not joined; may already be joined from W23 / W41), go to `#support` channel, paste §2.2 body verbatim | 2 min | https://discord.gg/C3eCXhYWtJ |
| 3 | Record the paste timestamps to `analytics/registry_status_w49.json` (operator-only; file-local) | 1 min | (no URL) |

**Total wall-clock**: ~5 minutes.
**Expected reply SLAs**: Smithery 24-72h, Glama 24-48h (W41 evidence: Glama
took 144h no-reply, may need PR #6192 fallback comment if no reply within 48h).

---

## §5. Verification commands (Claude / operator can run any time)

```bash
# 1. Confirm Anthropic Registry LIVE (5 versions returned)
curl -s 'https://registry.modelcontextprotocol.io/v0/servers?search=autonomath' \
  | python3 -c "import json,sys; d=json.load(sys.stdin); [print(s['server']['name'],'v',s['server']['version']) for s in d.get('servers',[])[:5]]"

# 2. Confirm PyPI v0.4.0
curl -s 'https://pypi.org/pypi/autonomath-mcp/json' \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['info']['name'], d['info']['version'])"

# 3. Confirm jpcite.com live (HTTP 200 expected)
curl -sI -o /dev/null -w "%{http_code}\n" --max-time 10 https://jpcite.com
curl -sI -o /dev/null -w "%{http_code}\n" --max-time 10 https://jpcite.com/healthz

# 4. Confirm release capsule SHA256
shasum -a 256 site/releases/rc1-p0-bootstrap/release_capsule_manifest.json
# Expected: 78b24c633b06660acc3ca1200084ab0c88769498fdfd3961d91d97029e36871c

# 5. Confirm target listings still 404 / 308 (proves Discord paste still needed)
curl -sI 'https://smithery.ai/server/@bookyou/jpcite' | head -1
# Expected: HTTP/2 308
curl -sI 'https://glama.ai/mcp/servers/shigetosidumeda-cyber/autonomath-mcp' | head -1
# Expected: HTTP/2 404

# 6. Confirm Discord invite resolution
curl -sI 'https://discord.gg/smithery' | grep -i location | head -1
# Expected: location: https://discord.com/invite/smithery
curl -sI 'https://glama.ai/discord' | grep -i location | head -1
# Expected: location: https://discord.gg/C3eCXhYWtJ
```

---

## §6. Canonical facts (single source of truth — PM2 refresh)

| Field | Value (2026-05-16 PM2) |
|---|---|
| Product brand | jpcite |
| PyPI distribution | `autonomath-mcp` |
| Version | 0.4.0 |
| Repo | https://github.com/shigetosidumeda-cyber/autonomath-mcp |
| Homepage | https://jpcite.com (HTTP 200 verified PM2) |
| Docs | https://jpcite.com/docs/ |
| License | MIT |
| Language | Python ≥ 3.11 |
| MCP protocol | 2025-06-18 |
| Transport | stdio |
| Install | `uvx autonomath-mcp` |
| **Tool count (default gates)** | **179** (Wave 59 Stream B top-10 outcome wrappers landed since v0.4.0 manifest) |
| **Outcome catalog** | **152** (Wave 65 financial markets cross packets landed; Wave 66 → 162 in progress) |
| **Release capsule** | rc1-p0-bootstrap (capsule_id `rc1-p0-bootstrap-2026-05-15`) |
| **Release capsule manifest SHA256** | `78b24c633b06660acc3ca1200084ab0c88769498fdfd3961d91d97029e36871c` |
| Pricing | ¥3/billable unit (¥3.30 tax-incl) fully metered |
| Free tier | 3 req/day per IP (anonymous, JST next-day reset) |
| Operator | Bookyou株式会社 (T8010001213708), 代表 梅田茂利, info@bookyou.net |

---

## §7. Memory bind

- `feedback_no_user_operation_assumption`: 7-attempt verify log in §3 confirms
  Discord paste IS user-only — no CLI / API / gh / curl / webhook automation
  path exists for Smithery `#support` or Glama `#support`. The memory entry
  itself updated to add Smithery/Glama Discord paste as a confirmed
  "真の user 操作" (Claude cannot automate) entry.
- `feedback_zero_touch_solo`: Discord paste is the only human-in-the-loop step
  for Wave 49 G2 — bundle ready for one-shot paste under 5 minutes.
- `feedback_loop_never_stop`: PM2 refresh continues the eternal loop on Wave
  49 G2 without blocking on operator paste — Wave 50 RC1 + Wave 59-67 packet
  streams continue in parallel.
- `feedback_legacy_brand_marker`: PM2 paste bodies keep brand history minimal
  (PyPI distribution `autonomath-mcp` retained, user-facing brand `jpcite`
  primary). 旧称 (AutonoMath / zeimu-kaikei.ai) intentionally not surfaced.

---

## §8. Logged at

- This PM2 refresh: `docs/_internal/SMITHERY_GLAMA_PASTE_2026_05_16_PM2.md`
- Original AM tick 6 paste-ready (historical state marker):
  `docs/_internal/WAVE49_G2_REGISTRY_PASTE_READY_2026_05_16.md`
- W23 escalation: `docs/_internal/mcp_registry_submissions/glama_discord_escalation.md`
- W41 attempt log: `docs/_internal/mcp_registry_submissions/glama_discord_attempt_w41.md`
- Smithery v3 submission spec: `docs/_internal/mcp_registry_submissions/smithery-submission-v3.md`
- W49 plan SOT: `docs/_internal/WAVE49_plan.md`
- Release capsule manifest: `site/releases/rc1-p0-bootstrap/release_capsule_manifest.json`

last_updated: 2026-05-16 PM2
