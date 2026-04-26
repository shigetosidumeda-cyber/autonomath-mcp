# jpintel-mcp — Launch Readiness (updated 2026-04-22)

Public launch target: **2026-05-06** (14 days out).
Source of truth for what is DONE, IN FLIGHT, and TODO.

---

## 1. Gates

Launch is gated by these, in order. No skip-ahead.

- **Gate A — Code complete** (W1-W2): core API + MCP + ingest + billing + tests
- **Gate B — Staging live** (W2): deployed on Fly.io nrt, real API reachable, Sentry receiving, health green for 72h
- **Gate C — Prod live** (W3): domain + TLS + DNS, prod secrets, Stripe live keys, prod webhook
- **Gate D — Launch content ready** (W3-W4): landing polished, legal pages correct, blog posts drafted, HN/Zenn/X/PH copy, MCP registries submitted
- **Gate E — Launch day** (W4, 2026-05-06): post HN + Zenn + X thread + PH, monitor, respond

Each gate has a "must-pass" list below. Track progress by striking off.

---

## 2. Gate A — Code complete

Target: 2026-04-24 (2 days out)

- [x] FastAPI routers: /programs, /exclusions, /billing, /health
- [x] MCP tools: programs_search, programs_get, exclusions_list (parity with REST)
- [x] SQLite schema: programs, exclusion_rules, api_keys, usage_log, subscribers
- [x] FTS5 trigram tokenizer (JP-safe)
- [x] Ingest from Autonomath unified_registry.json + enriched/*.json (6,771 rows)
- [x] Tier scoring S/A/B/C/X (depends on enriched coverage)
- [x] Stripe: Checkout, Customer Portal, Webhook (2 events wired)
- [x] Stripe: 3 extra webhook events (invoice.paid, payment_failed, subscription.deleted) — **task #41 pending**
- [x] Rate-limit Free 100 req/day / Paid metered (no cap, ¥0.5/req usage-reported to Stripe)
- [x] API key: HMAC-SHA256 + salt, never store raw
- [x] Observability: structlog JSON, Sentry scrubbers, x-request-id propagation
- [x] Security headers middleware (X-Content-Type, X-Frame-Options, Referrer-Policy, HSTS)
- [x] CORS allowlist via env
- [x] Backup/restore scripts + lineage columns populated (6,669/6,771 with source_url)
- [ ] /v1 URL prefix on all public routes — **task #30 in progress**
- [x] Tests: 37 passing
- [x] Prefecture coverage: 64% null → 0.9% null (4,252 programs attached)
- [x] Exclusion rules: 22 agri — **task #36 in progress: 50+ non-agri**
- [ ] Admin dashboard (user self-serve) — **task: pending, W2 design phase in progress**

## 3. Gate B — Staging live

Target: 2026-04-28 (6 days out)

- [x] Dockerfile hardened (sentry-sdk pinned, scripts/ copied, release_command binding)
- [x] fly.toml: nrt region, volume mount /data, release_command, rolling deploy, concurrency
- [x] .dockerignore created
- [x] .env.example updated
- [x] Deploy playbook at `docs/deploy_staging.md`
- [x] Gotchas doc at `docs/deploy_gotchas.md`
- [ ] `flyctl launch --no-deploy` — **user runs**
- [ ] Volume `jpintel_data` 1GB created — **user runs**
- [ ] 9 Fly secrets set — **user runs**
- [ ] `flyctl deploy --strategy rolling` — **user runs**
- [ ] `/healthz` returns 200 from fly.dev
- [ ] Sentry receives dummy error from staging
- [ ] Real API key created via `scripts/create_key.py` on staging
- [ ] 10 real `/v1/programs/search` calls from laptop → log appears in `flyctl logs`
- [ ] 72h soak: no 5xx, memory stable, CPU <10%

## 4. Gate C — Prod live

Target: 2026-05-01 (9 days out)

- [ ] Domain purchased (task #26 completed — decision needed on which)
- [ ] DNS: A/AAAA to fly, CNAME for www
- [ ] TLS auto-cert via fly
- [ ] Landing site deployed (Cloudflare Pages OR GitHub Pages OR same fly app serving /site)
- [ ] Prod fly app created (separate from staging)
- [ ] Prod volume
- [ ] Stripe LIVE keys in prod secrets
- [ ] Stripe LIVE webhook endpoint created, `whsec_*` in prod secrets
- [ ] Stripe Tax enabled, T-号 set in `INVOICE_REGISTRATION_NUMBER`
- [ ] Stripe Customer Portal configured (plan switch, invoice history, payment method update)
- [ ] `INVOICE_FOOTER_JA` set with インボイス制度 compliant footer
- [ ] `JPINTEL_CORS_ORIGINS` prod value set
- [ ] Health check green for 24h on prod

## 5. Gate D — Launch content ready

Target: 2026-05-05 (13 days out; launch eve)

- [x] Brand assets: logo, mark, favicon, og.png, og-twitter.png, og-square.png
- [x] BRAND.md guidelines
- [x] Landing page `site/index.html` with newsletter capture
- [x] Pricing page
- [x] Legal pages: tokushoho / privacy / tos
- [ ] APPI 28条 越境移転 disclosure added to privacy.html — **task #43 pending**
- [ ] 消契法 8/8-2 guardrail added to tos.html L73-77 — **task #43 pending**
- [x] HN Show HN (EN) draft in `research/launch_content.md`
- [x] Zenn (JP) draft
- [x] Qiita (JP) draft
- [x] X thread JP + EN drafts
- [x] Product Hunt draft
- [x] Reddit draft
- [x] MCP registry submission copy
- [x] Email to early list draft
- [ ] `<DOMAIN>` placeholder resolved across all drafts — **blocked on Gate C decision**
- [ ] First 3 blog posts drafted — **task in progress (SEO content calendar agent)**
- [ ] MCP registry submissions sent (5 of 8 active sources)
- [ ] 商標 出願 — **task #35 in progress; Intel name-risk eval pending**
- [ ] Newsletter list: ≥ 30 signups before launch day
- [ ] Status page URL (uptimerobot.com public page) in footer

## 6. Gate E — Launch day checklist (2026-05-06)

In order, 09:00-18:00 JST:

- [ ] 08:30 — pre-flight: `flyctl status`, `curl https://<domain>/healthz`, Sentry clear, Plausible live
- [ ] 09:00 — HN Show HN submitted (EN post)
- [ ] 09:05 — X EN thread published
- [ ] 09:15 — Zenn JP published
- [ ] 09:30 — X JP thread published
- [ ] 10:00 — Product Hunt submitted (timed for US morning = PH peak)
- [ ] 10:30 — MCP registry submissions confirmed (manual registries)
- [ ] 11:00 — email to newsletter list
- [ ] throughout — respond to HN + X + PH comments within 15min
- [ ] 14:00 — Qiita JP published (post-lunch JP audience)
- [ ] 17:00 — LinkedIn + Reddit posted
- [ ] 18:00 — retrospective: signup count, top-of-funnel, incidents, first paid?

---

## 6.1 Gate F — post-launch (D+1 → D+7)

Post-launch babysit window. Numbers go public; surprises = credibility.

**D+1 (2026-05-07) — morning triage**
- [ ] 09:00 Sentry: group by release, triage `P0` errors first
- [ ] 09:15 レート制限 429 ヒット数 + top offender IP / key
- [ ] 09:30 Newsletter signups delta (launch day vs D+1)
- [ ] 09:45 Stripe Checkout funnel: visits → checkout.session → paid

**D+2-3 (2026-05-08/09) — stabilize**
- [ ] Reply to top 5 HN/Zenn/X issues; file GitHub issues for each
- [ ] Hotfix P0s from Sentry (deploy via rolling, monitor 30 min)
- [ ] Post "launch recap" X thread with 24h metrics (requests, 2xx率, signups)

**D+5 (2026-05-11) — first retro**
- [ ] Compile top 3 bugs + top 3 feature asks into `research/retro_week1.md`
- [ ] Prioritize for Week 2 sprint (pick 2 bugs + 1 feature max)
- [ ] Drop anything still red on Sentry dashboard

**D+7 (2026-05-13) — transparency post**
- [ ] Publish Zenn "Week 1 numbers" post: requests/day, 2xx/4xx/5xx 比, 401 rate, Free→Paid 転換数
- [ ] Cross-post EN summary on X
- [ ] Update `site/index.html` hero if metric is launch-worthy (else leave)

---

## 7. Current in-flight agents

| ID | Task | ETA |
|----|------|-----|
| a1735f05ac355478a | Non-agri exclusion rules (50+) | running |
| a8734d69ff309401a | /v1 prefix + rate-limit verify | running |
| add843f8b00344b66 | JP 商標 research + 願書 draft | running |
| a067761fafb8f40bf | Competitive landscape scan | running |
| a257799fed7271e83 | Admin dashboard design | running |
| ab11e54dc22ba617e | SEO content calendar + 3 posts | running |

---

## 8. What the user must do before launch

These cannot be delegated:

- [ ] Pick a domain. Candidates: autonomath.ai, jpintel.jp, jpintel.ai, jp-intel.com
- [ ] 弁理士 30min 無料相談 (商標 Intel-name risk)
- [ ] Stripe: create live account, verify business, enable Tax, get T-号
- [ ] Open Stripe Customer Portal config in dashboard (30 settings)
- [ ] Run `flyctl launch` + set secrets
- [ ] Resolve `<DOMAIN>` across drafts (one find-replace after domain bought)
- [ ] Fill `<会社名>` `<所在地>` in legal pages
- [ ] Sign off on landing copy + HN title

---

## 9. Known risks

- **"Intel" trademark — HIGH risk, potentially blocking**: `jpintel` decomposes to jp + intel; Intel Corp. 日本 第42類 著名商標, known to file 異議申立 aggressively. 商標調査 agent recommends **rebrand before launch**. Shortlist: **JPI Data** (top), jpinst, JGI. Decision required from user + 弁理士 相談 before any public post. See `research/trademark_jp.md`.
- **SQLite single-machine**: no horizontal scale on Fly without WAL sync setup. Acceptable for 1000 RPS launch volume; revisit if >10K rps.
- **Jグランツ could release bulk CSV**: would commoditize the data baseline. Differentiation has to live in exclusions + tier + MCP + lineage.
- **Namespace squatting**: 5+ jGrants MCP wrappers already on PulseMCP; agri-specific one overdue. After rebrand decision, claim npm / PyPI / GitHub / X handles for the chosen name THIS WEEK (competitive scan agent flagged). See `research/competitive_landscape.md`.
- **Free jGrants MCP alternatives**: differentiation must be visible in 3 seconds of landing — agri depth, tier scoring, exclusion rules, lineage. Generic positioning will lose to free.
- **Stripe JCT edge cases**: 非課税仕入 / 輸出売上 for non-JP B2B — configured but needs first-invoice verification.
- **Free-tier abuse**: 100 req/day × unlimited emails = easy abuse. Consider domain-verified signup in W3 if problem appears.
