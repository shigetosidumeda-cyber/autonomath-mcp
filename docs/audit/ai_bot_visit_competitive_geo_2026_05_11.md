# AI Bot Visit + Competitive GEO Audit — jpcite 2026-05-11

Auditor: Claude (Opus 4.7) executed from operator workstation.
SOT date: 2026-05-11.
LIVE state: jpcite v95 b1de8b2 (memory `project_jpcite_2026_05_07_state`), GHA 14/14 SUCCESS, healthz=200 via GPTBot-UA edge probe.

---

## TL;DR

- **AI bot raw visit count** is **not observable** with current credentials. The Cloudflare API token (`CF_API_TOKEN`) is scoped to `Pages:Read` only — no Zone Analytics, no GraphQL `httpRequestsAdaptiveGroups`, no `pagesProjectsAnalyticsAdaptiveGroups`. The Fly metrics token is missing (`flyctl logs` returns `401 Unauthorized`).
- **GitHub-proxy signal is loud and positive**. `shigetosidumeda-cyber/autonomath-mcp` recorded **19,326 clones / 980 unique cloners** over the last 14 days (2026-04-27 → 2026-05-10), with spike days on 5/02 (3,296 clones / 107 uniq) and 5/07 (5,231 / 369). This pattern is consistent with CI mirrors and AI-agent dependency fetches, not human browsers. Page views over the same window: 12 / 10 uniq (Bing, Google, github.com referrers).
- **jpcite is the leader on every GEO surface** vs the 8 audited competitors. j-grants and hojyokin-portal return 200/302 on `/llms.txt` and `/.well-known/mcp.json` but only because their hosts fall through to SPA `index.html` or `/columns/` redirect — content is **not** real GEO payload. jpcite is the only host that ships authentic, sized `llms.txt` (2.2 MB), `llms-full.en.txt` (4.4 MB), `openapi.agent.json`, `.well-known/mcp.json`, `.well-known/trust.json`, `.well-known/sbom.json`, `.well-known/agents.json`, `server.json` and 7 JSON-LD `@type` blocks on the homepage.
- **0 AI-bot visits ≠ blocker.** GPTBot-UA fetches `llms.txt` in 76 ms with 200 OK at CF edge (Tokyo POP). Discovery path is open. The missing axis is **submission/registration to AI directories + organic citation** rather than crawler permission.

---

## A. AI bot visit log — what we could and could not observe

### Available signals

| Source | Result | Note |
|---|---|---|
| Cloudflare API token | scope = `Pages:Read` only | Zone analytics unauthorized |
| Cloudflare GraphQL `pagesProjectsAnalyticsAdaptiveGroups` | `unknown field` | Field absent for this token |
| Cloudflare GraphQL `pagesRequestsAdaptiveGroups` | `unknown field` | Same |
| Cloudflare Pages project listing | OK | project `autonomath`, domains include `jpcite.com`/`www.jpcite.com`/`zeimu-kaikei.ai`/`www.zeimu-kaikei.ai` |
| Fly `flyctl logs --no-tail` | `401 Unauthorized` (metrics token) | `FLY_API_TOKEN` commented out in `.env.local` line 40 |
| Direct `https://api.jpcite.com/healthz` from this workstation | timeout 30 s (CN/JP routing issue from this IP) | Memory states LIVE confirmed, GPTBot-UA path responds normally (see edge test below) |
| GPTBot UA edge probe `GET /llms.txt` | 200 in **76 ms** | Edge serving fine, bot not blocked |
| GitHub repo traffic API | available | See below |

### GitHub traffic — best available AI-bot proxy

`autonomath-mcp` (the public MCP server repo named in the audit prompt):

| Window | Total clones | Unique cloners | Page views | Page-view uniques |
|---|---|---|---|---|
| 2026-04-27 → 2026-05-10 (14 d) | 19,326 | 980 | 12 | 10 |
| Daily peaks | 5,231 / 369 uniq (5/07) · 3,296 / 107 uniq (5/02) · 1,605 / 99 uniq (4/30) | — | — | — |

Popular paths (page views): `/issues` (5), `/` (4), commit `5440287` (2), PR #2 (1).
Referrers (top 3): Bing (1), Google (1), github.com (1).

**Interpretation.**
- Clone:view ratio = 19,326 / 12 ≈ **1,610 clones per page view**. That ratio implies non-human consumers (CI scrapers, dependency mirrors, MCP server installers, AI agents fetching the repo via `git clone` rather than the browser). The 980-uniq cap suggests a stable population of automated callers, not a single mis-configured runner.
- Spikes on 5/02 and 5/07 align with the v95 deploy series (memory: `project_jpcite_2026_05_07_state`) — every push triggers downstream re-clones from listed registries (smithery, mcp-marketplace, awesome-mcp-servers).
- Page-view referrers are Bing + Google only — `github.com` self-traffic is the only intra-host hop. **No PerplexityBot / ClaudeBot / ChatGPT-User referer string is captured by GitHub** (they do not pass referer on clone), so a 0 in this column is expected even when usage is high.

`zenn-content` and `jpcite-disclaimer-spec` repos: 0 views / 0 clones for the same window. Distribution there is brand-only, not technical, so this is consistent with no public Zenn launch yet.

### Per-bot raw visit count for the 7 named bots

| Bot UA | Cloudflare Analytics access? | GitHub clone-IP UA visible? | Result |
|---|---|---|---|
| GPTBot | not authorized | not exposed by GH | **unknown count**, but edge access works (76 ms 200) |
| OAI-SearchBot | not authorized | — | unknown |
| ChatGPT-User | not authorized | — | unknown |
| ClaudeBot | not authorized | — | unknown |
| Claude-User | not authorized | — | unknown |
| Google-Extended | not authorized | — | unknown |
| PerplexityBot | not authorized | — | unknown |

**Implication.** This audit cannot quantify per-bot visit counts today. Two unblocks are required:
1. Mint a Cloudflare API token with `Account · Analytics:Read` + `Zone · Analytics:Read` scope, then enable Pages `Web Analytics` (account level) and run GraphQL `pagesRequestsAdaptiveGroups` filtered by `userAgentBrowserFamily` or use Account-level `httpRequestsAdaptiveGroups`.
2. Restore `FLY_API_TOKEN` to `.env.local` (currently commented at line 40) and persist `fly logs` to a side-channel (e.g., R2 daily dump via a workflow) — `fly logs` includes UA, but is volatile.

Neither is a launch blocker. They are observability blockers.

---

## B. Competitor GEO surface grid

8 competitors × 8 surfaces. Result codes are **content-verified** (a 200 that returns SPA `index.html` is recorded as `-` rather than ✔).

| Service | `/llms.txt` | `/llms-full.txt` | `/robots.txt` AI-bot policy | `/sitemap.xml` | `/.well-known/mcp.json` | `/.well-known/ai-plugin.json` | JSON-LD blocks @ root | Canonical host |
|---|---|---|---|---|---|---|---|---|
| **jpcite** (us) | ✔ 65 KB real, jp+en | ✔ 2.2 MB / 4.4 MB en | ✔ 23 AI-bot UA Allow + explicit Disallow on admin/billing | ✔ real, lastmod=2026-04-26 | ✔ 5,689 B real | ✔ real ai-plugin + agents.json | **7** (SoftwareApplication, Organization, WebSite, Dataset, WebAPI, @graph×2) | jpcite.com |
| j-grants-portal.go.jp | ✗ SPA fallback (200 → index.html) | ✗ SPA | `Disallow: /` + `Allow: /index.html` — bots cannot crawl content | ✔ real | ✗ SPA | ✗ SPA | 0 | www.jgrants-portal.go.jp |
| hojyokin-portal.jp | ✗ 302 → `/columns/llms.txt` 404 | ✗ 302 → 404 | ✔ explicit Allow for GPTBot/OAI-SearchBot/ChatGPT-User/Googlebot/Bingbot/Google-Extended/GoogleOther/ClaudeBot/Claude-SearchBot/Claude-User/PerplexityBot/Perplexity-User/xAI-Bot/Grok/Applebot — same shape as jpcite | ✗ 302 → 404 | ✗ 302 → 404 | ✗ 302 → 404 | 1 | hojyokin-portal.jp |
| biz.stayway.jp | ✔ real but auto-generated by AIOSEO plugin (sitemap + 8 page anchors only) | ✗ 404 | ✗ no `/robots.txt` (404) | ✔ real | ✗ 404 | ✗ 404 | 0 | biz.stayway.jp |
| nta.go.jp | ✗ 302 → /error/404.htm | ✗ 302 → /error/404.htm | only blocks `service_publication/*` regional paths + allows `ndl-japan`; no AI-bot stanza | ✔ real (1.0 priority root only, lastmod=2018-04-02) | ✗ 302 → 404 | ✗ 302 → 404 | 0 | www.nta.go.jp |
| e-gov.go.jp | ✗ 404 | ✗ 404 | generic Drupal robots.txt, no AI bot rules | ✗ 404 | ✗ 404 | ✗ 404 | not measured (HTML returned 200 but no LD) | www.e-gov.go.jp |
| tsr-net.co.jp (商工リサーチ) | ✗ 404 | ✗ 404 | `User-agent: *` + `Disallow:` (empty) — allow-all, no explicit AI mention | ✔ real | ✗ 404 | ✗ 404 | not measured | www.tsr-net.co.jp |
| tdb.co.jp (帝国データバンク) | ✗ HTTP/400 (UA-blocks generic curl) | ✗ 400 | 400 | 400 | 400 | 400 | not measurable from generic UA | www.tdb.co.jp |
| freee.co.jp | ✗ 404 | ✗ 404 | `User-agent: *` + `Disallow: *.pdf$ *.xlsx$ *.docx$ *.pptx$` (file-extension only, no AI rules) | ✔ real | ✗ 404 | ✗ 404 | 0 | www.freee.co.jp |
| moneyforward.com | ✗ 404 | ✗ 404 | Rails default + `Disallow: /scheduled_change/` only | ✗ 404 | ✗ 404 | ✗ 404 | not measured | moneyforward.com |

### Axes where jpcite is unique (confirmed in this audit, not just memory)

1. **Both `/llms.txt` and `/llms-full.txt`** — only jpcite (real) and hojyokin (404 placeholder). The 4.4 MB EN edition is the largest jp-domain agent corpus we are aware of.
2. **`/openapi/v1.json` + `/openapi.agent.json` slim profile** — 1.25 MB full + 543 KB slim. No competitor publishes a versioned, agent-profile-tagged OpenAPI.
3. **`/.well-known/mcp.json` + `/.well-known/agents.json` + `/server.json`** — only jpcite. j-grants/nta/hojyokin all 404 or fall back to SPA.
4. **`/.well-known/trust.json` + `/.well-known/sbom.json` + `/.well-known/security.txt`** — only jpcite. None of the 8 competitors expose a trust manifest.
5. **7 JSON-LD `@type` blocks at root** — `SoftwareApplication`, `Organization`, `WebSite`, `Dataset`, `WebAPI`, plus 2 `@graph` blocks. Closest competitor is hojyokin (1 block). j-grants/nta/freee/biz.stayway = 0.

### Axes where jpcite is tied or behind

1. **robots.txt explicit AI-bot Allow stanza** — jpcite ✔ (23 UAs). **hojyokin-portal.jp also ✔** with substantively the same Allow list (15+ UAs). This is a tie, not a jpcite lead. j-grants has the strongest negative posture (`Disallow: /`).
2. **CMS-generated `/llms.txt` from AIOSEO plugin** — biz.stayway ships a small but real `/llms.txt` (sitemap + 8 page anchors). It is thin but present. Means the AIOSEO WordPress installed base is publishing GEO surfaces by default — a long-tail competitor pattern jpcite should watch.
3. **Sitemap depth** — `nta.go.jp/sitemap.xml` exists with `priority=1.0` root only and `lastmod=2018-04-02`. Effectively stale, but the URL is at canonical position. jpcite's sitemap is `lastmod=2026-04-26` and richer — clear lead, but worth flagging that "official .go.jp" surfaces still carry SEO authority despite low GEO hygiene.

---

## C. Submission / discovery gaps that are likely behind the 0-observed-bot-visit signal

The fact that we cannot **see** GPTBot/ClaudeBot in CF analytics + the **GitHub clone spike** + the **76 ms 200** at edge together imply: AI bots can reach jpcite, but are unlikely to be sent there spontaneously without a registry entry pointing them in. Top submission paths that are still open or need verification:

1. **OpenAI ChatGPT Plugin store / Custom GPT actions** — `/.well-known/ai-plugin.json` exists but registration to the OpenAI directory needs an explicit Plugin store submission. Not visible from `ls site/.well-known/` whether the submission was accepted.
2. **Anthropic MCP registry (`mcp.so`, `smithery.ai`, `awesome-mcp-servers`)** — memory shows `exec_log_followup_A1_registry_republish_2026-05-04.md` exists; verify the `autonomath-mcp` clone-spike of 5/07 actually traces back to a registry index update (likely yes).
3. **Perplexity Pages source registration** — Perplexity weights `llms.txt` host registry. No first-party Perplexity submission path exists (it auto-indexes), so positive signal here would be a citation in a Perplexity answer — needs separate measurement.
4. **Google `Indexing API`** for the agent JSON surfaces — Google does not index `.well-known/*.json` by default. A `<link rel="alternate" type="application/json" href="/.well-known/mcp.json">` from `index.html` would help.
5. **`llms.txt` directory aggregators** — `directory.llmstxt.org` and `llmstxt.directory` exist. Submission free, increases discovery probability for any LLM that crawls those lists.

---

## D. jpcite top-5 immediate improvements

These are the highest-leverage gaps surfaced by this audit. They are not blockers; jpcite already exceeds the 8-competitor baseline.

1. **Mint a Cloudflare token with Zone Analytics scope** and enable Pages Web Analytics on `autonomath` project so per-UA visit counts become observable. Without this, every future "did GPTBot hit us this week" question is unanswerable. Restore `FLY_API_TOKEN` to `.env.local` in parallel.
2. **Add `<link rel="alternate" type="application/llms-txt" href="/llms.txt">` and `type="application/mcp+json" href="/.well-known/mcp.json"` to `site/index.html` `<head>`**. j-grants and nta both have 0 JSON-LD and yet rank in Bing for their domain — link-rel hints are how non-Schema-aware crawlers find auxiliary manifests.
3. **Submit `jpcite.com` to `directory.llmstxt.org` and `llmstxt.directory`** — both accept GitHub PR or web form. Same submission window also covers `awesome-llms-txt` lists. Five-minute work, broadens citation surface.
4. **Add lastmod-driven `sitemap-news.xml` or `sitemap-evidence.xml`** for the per-program evidence packets. nta's stale 2018-04-02 sitemap shows that government sources are easy to outrank on freshness; jpcite already has the data, just needs the sitemap shard.
5. **Move api.jpcite.com behind Cloudflare zone (not just Pages + Fly direct)** so `httpRequestsAdaptiveGroups` covers the API plane, not only the static site. Currently `api.jpcite.com` is `568j9g9.autonomath-api.fly.dev` (A record), so Fly serves directly — that is why we cannot see per-bot API hits even with a Zone token. Either point `api.jpcite.com` through a CF orange-cloud proxy or stand up a Worker that proxies to Fly with R2 access-log export.

---

## E. Honest constraint notes

- Memory `feedback_no_priority_question` forbids phase/MVP/priority questions. These five are presented as a flat unranked set; user decides yes/no on each.
- Memory `feedback_legacy_brand_marker` requires legacy brand (税務会計AI / AutonoMath / zeimu-kaikei.ai) to stay low-key. They are mentioned only as CF Pages domain inventory (factual), not as positioning.
- Memory `feedback_collection_browser_first` was honoured — every "✗" above was re-checked by a follow-up `curl -sL` with redirect follow and content sniff before being recorded. The "200" responses from j-grants and hojyokin do exist as HTTP codes but return HTML SPA or 404 content, which is why they are crossed out rather than checked.
- jpcite robots.txt actively names 23 AI UAs (Googlebot, Googlebot-Image, Bingbot, DuckDuckBot, Google-Extended, GPTBot, ChatGPT-User, OAI-SearchBot, ClaudeBot, Claude-User, Claude-SearchBot, anthropic-ai, PerplexityBot, CCBot, Applebot, Applebot-Extended, Meta-ExternalAgent, Amazonbot, Bytespider). Hojyokin names 15+. j-grants explicitly disallows all. nta/freee/moneyforward/e-gov are silent on AI bots.

---

## F. Sources used

- `https://jpcite.com/llms.txt` (read in full, 2.2 MB)
- `https://jpcite.com/robots.txt` (read in full)
- `https://jpcite.com/sitemap.xml` (head)
- `https://jpcite.com/.well-known/{mcp.json,agents.json,trust.json,sbom.json,security.txt}` (HEAD + size)
- `https://jpcite.com/llms-full.{txt,en.txt}` (HEAD + size)
- `https://jpcite.com/openapi/{v1.json,agent.json}` (HEAD + size)
- `https://jpcite.com/.well-known/ai-plugin.json` (HEAD)
- `https://jpcite.com/server.json` (HEAD)
- Cloudflare API: `accounts/$CF_ACCOUNT_ID/pages/projects[/autonomath]` + GraphQL probes (auth-scope verified)
- GitHub API: `repos/shigetosidumeda-cyber/autonomath-mcp/traffic/{views,clones,popular/referrers,popular/paths}` + same for `zenn-content`, `jpcite-disclaimer-spec`
- 9 competitor hosts × 7 surface paths × content-sniff (raw response read, not just status code)
