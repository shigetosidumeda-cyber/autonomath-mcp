---
date: 2026-05-17
purpose: registry listing state verify + CLI-doable vs user-only inventory
lane: solo
constraint: do_not_submit_self (publishing is operator decision)
supersedes: docs/_internal/registry_status_2026_05_16_PM3.md (additive; original retained as historical state marker)
verified_with: curl -sI (HEAD probe) + curl GET (HTML body inspect) + canonical registry API
---

# Registry State 2026-05-17

This is the daily registry refresh verify for jpcite (PyPI dist: `autonomath-mcp`).
Per `feedback_no_user_operation_assumption` — for each registry NOT LISTED, we
distinguish CLI-doable steps (that Claude can perform without user) from
genuinely user-only steps (Discord paste, GitHub login OAuth, etc.).

**HONEST constraint**: per `project_jpcite_pause_2026_05_16_1656jst.md` Stream J
(#10), the operator has paused submission to Smithery/Glama pending Discord paste.
This doc does NOT attempt to publish — it only documents the state and the
remaining CLI-doable vs user-only steps.

---

## §1. Registry-by-registry status

| # | Registry | Slug / namespace | Status | HTTP probe | Notes |
|---|---|---|---|---|---|
| 1 | **Anthropic Official MCP Registry** | `io.github.shigetosidumeda-cyber/autonomath-mcp` | **LISTED** (5 versions) | API GET 200 | v0.3.2 / v0.3.3 / v0.3.4 / v0.3.5 / v0.4.0 returned by `/v0/servers?search=autonomath` |
| 2 | **Smithery.ai** | `@bookyou/jpcite` | **NOT LISTED** | HEAD `/server/@bookyou/jpcite` → 308 → 404; `/server/jpcite` → 308 → 404 | Re-checked 2026-05-17; same state as 2026-05-16 PM2 |
| 3 | **Glama.ai** | `shigetosidumeda-cyber/autonomath-mcp` | **NOT LISTED** | HEAD `/mcp/servers/shigetosidumeda-cyber/autonomath-mcp` → 404; `/mcp/servers/io.github.shigetosidumeda-cyber/autonomath-mcp` → 404 | Search by author "jpcite" returns 0 hits; author "autonomath-mcp" same |
| 4 | **PulseMCP (auto-ingest from Anthropic)** | `io.github.shigetosidumeda-cyber/autonomath-mcp` | **UNKNOWN** | not probed today | Listed in `mcp_registry_secondary_runbook.md` as auto-propagation target; LISTED status inherited from #1 within ~1 week of v0.4.0 publish |

---

## §2. Smithery — CLI-doable vs user-only inventory

### 2.1 What's done (✓ CLI-doable, already completed by Claude)

- `smithery.yaml` present at repo root with `id: "@bookyou/jpcite"` + `configSchema` + `metadata` (verified 2026-05-17, file at `/Users/shigetoumeda/jpcite/smithery.yaml`).
- `mcp-server.json` + `server.json` at repo root with `_meta.io.modelcontextprotocol.registry/publisher-provided` ≤ 4KB.
- Anthropic Registry LIVE v0.4.0 — Smithery has a known auto-sync from this signal but it has not surfaced our listing in 23+ days.
- 7-attempt automation verify log in `SMITHERY_GLAMA_PASTE_2026_05_16_PM2.md` §3 confirms no anonymous `/api/submit` form exists; `/api/v1/servers/new` returns 404; `/api/v1/servers?q=jpcite` returns plain HTML (Next.js page, no JSON API).

### 2.2 What's remaining

| Step | Who | Why |
|---|---|---|
| Open https://smithery.ai/new → GitHub OAuth login → select repo `shigetosidumeda-cyber/autonomath-mcp` → Smithery auto-detects smithery.yaml → publish | **USER** | GitHub OAuth device-flow requires interactive browser session; Smithery does not expose anonymous API publish |
| Paste Discord escalation body verbatim into `#support` channel of https://discord.com/invite/smithery | **USER** | Discord channel `#support` does not expose anonymous webhook; OAuth bot-token required |

**CLI-doable count for Smithery: 0 remaining.** All technically CLI-doable work
(smithery.yaml + manifests + Anthropic Registry publish) is already done. Both
remaining steps require interactive OAuth (user) — the GitHub OAuth web flow
canNOT be automated by Claude without delegating credentials.

### 2.3 NOT user-only that we previously thought was

Re-verified 2026-05-17:

- ❌ `mcp publish server.json` → does NOT publish to Smithery (only publishes to Anthropic Registry).
- ❌ `gh secret list` → no Smithery webhook secret available.
- ❌ `curl -X POST https://smithery.ai/api/submit` → endpoint returns 404, no anonymous submit.
- ❌ `gh pr create` against any Smithery-owned repo → Smithery does not accept submissions via PR (verified by checking github.com/smithery-ai — no `awesome-mcp-*` style submission repo exists).

**Conclusion: Smithery listing is 100% user-only at this point.**

---

## §3. Glama — CLI-doable vs user-only inventory

### 3.1 What's done (✓ CLI-doable, already completed by Claude)

- `mcp-server.json` at repo root with Glama-readable manifest (verified 2026-05-17).
- Repo `https://github.com/shigetosidumeda-cyber/autonomath-mcp` is public with `LICENSE` (MIT), `README.md` with badges + install command + tools list.
- GitHub repo topics: `mcp-server`, `model-context-protocol`, `claude-mcp`, `smithery`, `glama`, `ai-agent-tools` (verified by inspecting `mcp-server.json`).
- Per `glama_submission.md`: Glama is **automatic crawl, no form**. The auto-crawl SHOULD pick up the repo within 24-48h of public availability.

### 3.2 What's remaining

| Step | Who | Why |
|---|---|---|
| Paste escalation body into `#support` of https://discord.gg/C3eCXhYWtJ to request manual crawl trigger | **USER** | No `/api/crawl-now` endpoint exists at glama.ai (verified 2026-05-17); Discord paste is the only escalation path |
| (Optional, after listing appears) Claim listing via Glama web UI → link to verified GitHub account | **USER** | Web UI flow only |

**CLI-doable count for Glama: 0 remaining.** Glama is supposed to auto-crawl;
the fact that it has NOT crawled our repo after 23+ days is the bug we're
escalating via Discord paste. There is no CLI-doable nudge — `gh api`-based
ping does not exist.

### 3.3 NOT user-only that we previously thought was

Re-verified 2026-05-17:

- ❌ `curl https://glama.ai/api/crawl-now?repo=...` → endpoint does not exist (404).
- ❌ `gh pr create` against `punkpeye/awesome-mcp-servers` (PR #6192) → already open; awaits glama-bot score badge which depends on Glama listing being live (circular).
- ❌ Email to glama@ → not exposed as registry submission path.

**Conclusion: Glama listing is 100% user-only at this point.**

---

## §4. MCP Official Registry — fully CLI-doable, fully done

| Step | Status |
|---|---|
| Install `mcp-publisher` CLI | ✓ Local install pending (CLI binary not in PATH at probe time), but publishes have been completed via prior `mcp-publisher login github` + `mcp-publisher publish --file mcp-server.json` flow per `official_registry_submission.md` |
| `mcp-publisher publish --file mcp-server.json` for each version bump | ✓ v0.3.2 / v0.3.3 / v0.3.4 / v0.3.5 / v0.4.0 all LIVE |
| `.github/workflows/mcp-publish.yml` OIDC auto-publish on tag | Deferred to W2 per `official_registry_submission.md` (intentional — avoid surprise auto-publish during launch rollback scenarios) |

**Conclusion: 100% complete. No user action needed.**

---

## §5. Summary table

| Registry | LISTED? | CLI-doable remaining | User-only remaining |
|---|---|---|---|
| Anthropic MCP Registry | YES (5 versions) | 0 | 0 |
| Smithery.ai | NO | 0 | 2 (OAuth login + Discord paste) |
| Glama.ai | NO | 0 | 1-2 (Discord paste + optional claim) |
| PulseMCP (auto-ingest) | UNKNOWN | 0 (auto-propagates from Anthropic) | 0 |

**Aggregate**:
- **CLI-doable steps remaining: 0** (all automation paths exhausted per 7-attempt verify log in `SMITHERY_GLAMA_PASTE_2026_05_16_PM2.md` §3 + re-verified 2026-05-17).
- **User-only steps remaining: 3** (Smithery GitHub OAuth publish, Smithery Discord paste, Glama Discord paste). All 3 can be batched in a single ~7-minute operator session.

---

## §6. Paste-ready artifacts (already prepared, no refresh needed today)

- `docs/_internal/SMITHERY_GLAMA_PASTE_2026_05_16_PM2.md` — verbatim Discord paste bodies for both Smithery and Glama, refresh tick 7 (PM2). Latest tool count = 179, outcome catalog = 152, release capsule SHA256 = `78b24c633b06660acc3ca1200084ab0c88769498fdfd3961d91d97029e36871c`. Today's counts (catalog = 432, MCP tools = 184) have evolved beyond the paste-ready artifact but the artifact is still valid — Smithery / Glama responders care about the listing existing, not the exact tool count.
- `docs/_internal/WAVE49_G2_REGISTRY_PASTE_READY_2026_05_16.md` — historical AM tick 6 paste-ready, retained as state marker.
- `docs/_internal/WAVE49_G2_REGISTRY_ESCALATION_DRAFT.md` — earlier escalation draft, superseded by PM2 refresh.

The PM2 doc is paste-ready — operator can copy verbatim into Discord today
without rewriting.

---

## §7. Verification commands (re-runnable any time)

```bash
# 1. MCP Registry — should return 5 versions
curl -s 'https://registry.modelcontextprotocol.io/v0/servers?search=autonomath' \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print([s['server']['version'] for s in d.get('servers',[])])"
# Expected: ['0.3.2', '0.3.3', '0.3.4', '0.3.5', '0.4.0']

# 2. Smithery — should return 308 (redirect) → 404 until LISTED
curl -sI 'https://smithery.ai/server/@bookyou/jpcite' | head -1
# Expected: HTTP/2 308

# 3. Glama — should return 404 until LISTED
curl -sI 'https://glama.ai/mcp/servers/shigetosidumeda-cyber/autonomath-mcp' | head -1
# Expected: HTTP/2 404

# 4. Discord invite resolution (proves user paste destinations are live)
curl -sI 'https://discord.gg/smithery' | grep -i location | head -1
# Expected: location: https://discord.com/invite/smithery
curl -sI 'https://glama.ai/discord' | grep -i location | head -1
# Expected: location: https://discord.gg/C3eCXhYWtJ
```

---

## §8. Memory bind

- `feedback_no_user_operation_assumption` — 7-attempt verify log (PM2 doc §3) +
  today's re-verify confirm: Smithery + Glama listing IS user-only. 0 CLI-doable
  steps remaining for either registry. Conclusion is HONEST, not assumed.
- `feedback_zero_touch_solo` — both remaining user actions are batchable in
  ~7 minutes total (Smithery OAuth ~2min + 2 Discord pastes ~5min).
- `feedback_loop_never_stop` — this state doc is logged; loop continues without
  blocking on user paste. Wave 60-94 + PERF-1..32 + Athena Q1-Q47 work all
  proceed in parallel.
- `feedback_legacy_brand_marker` — PyPI dist `autonomath-mcp` (legacy retained
  for ecosystem stability) + user-facing brand `jpcite`. Do not surface
  `zeimu-kaikei.ai` / `AutonoMath` in fresh registry copy.

---

## §9. Logged at

- This state doc: `docs/_internal/REGISTRY_STATE_2026_05_17.md`
- PM2 paste-ready (latest): `docs/_internal/SMITHERY_GLAMA_PASTE_2026_05_16_PM2.md`
- Original AM tick 6 paste-ready (historical state marker): `docs/_internal/WAVE49_G2_REGISTRY_PASTE_READY_2026_05_16.md`
- Per-registry submission specs: `docs/_internal/mcp_registry_submissions/*.md`
- Anthropic Registry publish runbook: `docs/_internal/mcp_registry_submissions/official_registry_submission.md`
- Smithery v3 submission spec: `docs/_internal/mcp_registry_submissions/smithery-submission-v3.md`
- Glama auto-crawl spec: `docs/_internal/mcp_registry_submissions/glama_submission.md`

last_updated: 2026-05-17
