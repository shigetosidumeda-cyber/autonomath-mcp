# Launch gaps audit — jpintel-mcp

Audited 2026-04-22 (T-14, launch 2026-05-06) against files under `src/`, `site/`, `docs/`, `scripts/`, `.github/`, `research/`, `fly.toml`, `Dockerfile`, `pyproject.toml`, `.env.example`.

## Executive summary

**31 gaps: 7 critical, 13 important, 11 nice.** Plan is unusually thorough. Gate A near-complete; Gate B is one flyctl session away. Dominant risk is the known Intel-rebrand + legal `[要確定]` — both flagged, neither fully scoped.

Real bug missed by the plan: **10x rate-limit mismatch** between README / LAUNCH_READINESS (Plus=1,000 / Pro=10,000) and `.env.example` (Plus=10,000 / Pro=100,000).

**Timeline: 14 days is tight but doable if rebrand lands in 48h.** If rebrand slips past 2026-05-01, postpone by 2 weeks.

---

## Gate A — code

| # | Title | Sev | h | Fix |
|---|---|---|---|---|
| A1 | `.env.example` quotas 10x off vs README / config defaults | crit | 0.2 | Set `PLUS=1000, PRO=10000` |
| A2 | No global `Exception` handler in `main.py` — raw tracebacks leak | crit | 1 | `app.add_exception_handler(Exception, ...)` → `{error, request_id}` |
| A3 | No lifespan / SIGTERM; in-flight Stripe webhooks can drop on rolling deploy | imp | 1 | FastAPI lifespan + uvicorn `--timeout-graceful-shutdown 30` |
| A4 | `docs/openapi/v1.json` empty — CI workflow never ran | imp | 0.5 | Trigger workflow, commit spec |
| A5 | Pre-`/v1` route policy undocumented | nice | 0.3 | Note in `api-reference.md` |
| A6 | MCP protocol version not pinned in docs | nice | 0.3 | State "MCP 2025-03-26" in `mcp-tools.md` |
| A7 | Admin dashboard marked "design phase" but `me.py` (370) + `test_me.py` (373) + `dashboard.html` are built, wired | credit | 0 | Update LAUNCH_READINESS |

## Gate B — staging

| # | Title | Sev | h | Fix |
|---|---|---|---|---|
| B1 | Backup cron **not scheduled** — `backup.py` is solid but the template in `backup.md` isn't a real workflow | crit | 1 | Commit `.github/workflows/nightly-backup.yml` |
| B2 | Backups land on same volume as DB → volume loss = backup loss | imp | 2 | Add `rclone copy` to R2 in nightly job |
| B3 | "37 tests passing" stale — 6 files / 1,015 lines exist | imp | 0.3 | `pytest -q`; update count |
| B4 | `/v1/subscribers` rate-limit is per-process memory — lost on restart / not shared | imp | 2 | Cloudflare in front + rate-limit rule |
| B5 | `min_machines_running=1` + rolling = replace-in-place → 30-60s outage on bad deploy | imp | 1 | 2 machines ($1-2/mo) |
| B6 | No DDoS / abuse runbook | nice | 0.5 | Add toggle steps to `deploy_gotchas.md` |
| B7 | No incident runbook — solo on-call has no step-by-step | imp | 1 | `docs/incident_runbook.md`: logs → releases → rollback |
| B8 | `SENTRY_RELEASE` not set at build — per-release error attribution impossible | nice | 0.5 | `flyctl secrets set SENTRY_RELEASE=${GITHUB_SHA::7}` in deploy.yml |

## Gate C — prod

| # | Title | Sev | h | Fix |
|---|---|---|---|---|
| C1 | DNS TTL not planned low pre-launch | imp | 0.1 | Set A/AAAA TTL=300 until T+72h |
| C2 | TLS auto-renewal silent failure monitoring absent | nice | 0.5 | Fly email alerts + openssl check in uptime robot |
| C3 | No secrets-rotation runbook (`API_KEY_SALT`, `whsec_*`) | nice | 0.5 | Append to `deploy_staging.md` |
| C4 | Prod DB bootstrap missing from Gate-C checklist — empty DB will ship | crit | 0.5 | Add item: `bootstrap_db.sh` on prod, verify `/meta.total_programs=6771` |
| C5 | No static fallback for landing if Fly is down launch morning | imp | 1 | Mirror `site/` to Cloudflare Pages (free); DNS flip in 60s |
| C6 | README advertises 99%/99.5% SLA; `tos.html` has no SLA clause (contradictory public claim) | imp | 0.5 | Either drop the numbers or write `docs/sla.md` + link from ToS |

## Gate D — content

| # | Title | Sev | h | Fix |
|---|---|---|---|---|
| D1 | og:/twitter: on `index.html` only — pricing/privacy/tos/tokushoho/dashboard blank | imp | 1 | Copy og block per page |
| D2 | `/.well-known/security.txt` absent | nice | 0.3 | `Contact: security@<domain>` |
| D3 | humans.txt — skip | — | — | — |
| D4 | No demo asciinema / GIF on landing | nice | 2 | 15s curl→response; embed SVG |
| D5 | No press kit | nice | 1 | `site/press.zip`: assets + 200-word about |
| D6 | `hello@<domain>` not deliverable — 5 files link to it | crit | 0.5 | Set MX (Fastmail / ImprovMX) after domain; auto-responder |
| D7 | `<DOMAIN>` placeholders: 24 launch_content + 1 tos + 6 tokushoho (known) | crit | 0.5 | Find-replace post-domain |
| D8 | APPI 28条 disclosure **already in privacy.html L70-77** — LAUNCH L93 stale | credit | 0 | Check the box |
| D9 | 消契法 8/8-2 guardrail **already in tos.html L77** — LAUNCH L94 stale | credit | 0 | Check the box |
| D10 | Intel rebrand undecided — blocks domain + copy + registries + 商標 | crit | 10+ | 弁理士 Monday AM; **biggest risk** |

## Gate E — launch day

| # | Title | Sev | h | Fix |
|---|---|---|---|---|
| E1 | No war-room doc (rollback cmd, dashboard links, status cadence) | imp | 0.5 | `docs/launch_war_room.md` |
| E2 | Stripe live-account verification can take 24-48h; not scheduled earlier | crit | user | Apply **today**, not T-2 |
| E3 | Stripe reserves / holds for new accounts undocumented — cash-flow note | nice | 0 | Accept |
| E4 | Support inbox auto-responder absent (HN rush = 20-50 emails/6h) | imp | 0.3 | Fastmail auto-reply template |
| E5 | `.github/ISSUE_TEMPLATE/` **missing** despite plan claim (only CODEOWNERS, dependabot, PR template, workflows exist) | imp | 0.5 | Add `bug.yml` + `feature.yml` |
| E6 | No D+1 → D+7 post-launch checklist | nice | 0.3 | Add Gate-F |

## Business / legal

| # | Title | Sev | h | Fix |
|---|---|---|---|---|
| L1 | インボイス T-号 not filed — **2-week e-Tax lead time = too late for launch day** | crit | user | File today; fall-back: "T-号 申請中" in tokushoho |
| L2 | `[要確定]` × 6 in `tokushoho.html` (事業者名, 代表者, 所在地, 電話, T号, 運営責任者) | crit | 0.3 | Fill after 個人 vs 法人 decision |
| L3 | Cookie banner not needed (Plausible cookie-less) — plan correct | — | — | — |
| L4 | GDPR DPO unnecessary at this scale | — | — | — |
| L5 | APPI 72h breach-notification runbook absent | nice | 0.5 | 1-page playbook |
| L6 | PII inventory not written down | nice | 0.3 | Append to `deploy_staging.md` |

## Operational

| # | Title | Sev | h | Fix |
|---|---|---|---|---|
| O1 | Solo on-call — accepted | — | — | — |
| O2 | Logs retention: privacy.html already states "90 日" — no gap | credit | 0 | — |
| O3 | DSAR playbook absent (policy promises but no runbook) | nice | 0.5 | Extract/delete SQLite + Stripe + Sentry steps |

---

## Top 10 launch-blockers (ranked)

1. **Trademark rebrand** (D10, L2) — blocks domain, copy, legal, registry, 商標.
2. **Rate-limit config bug** (A1) — 10x quota if unfixed.
3. **Legal `[要確定]` placeholders** (L2) — 特商法 non-compliance without them.
4. **インボイス T-号 filing** (L1) — 2-week lead; file today or ship "申請中".
5. **Global exception handler** (A2) — 1h, high leverage.
6. **Backup cron + offsite** (B1, B2) — day-1 data-loss risk.
7. **Prod DB bootstrap** (C4) — empty prod = empty search.
8. **Support inbox on real domain** (D6) — email links broken.
9. **OG tags on non-index pages** (D1) — shared-link previews break → lost signups.
10. **Incident runbook** (B7) — needed before midnight D-0.

Total critical-item effort: **~20h user + ~8h agent**.

## Inverse-gap credit (done, plan doesn't mention)

- **APPI 28条** disclosure in `privacy.html` L70-77 — done.
- **消契法 8/8-2** guardrail in `tos.html` L77 — done.
- **Admin dashboard**: `me.py` (370 LOC) + `dashboard.html` + `test_me.py` (373 LOC) — built, wired, tested.
- **Structured logging + x-request-id + security headers + CSP + Sentry scrubbers** — all wired in `main.py`/`sentry_filters.py`.
- **Online SQLite backup** (`scripts/backup.py`) — atomic rename, sha256, gzip, prune; production-quality.
- **GH Actions**: test matrix (3.11/3.12/3.13), Fly deploy, OpenAPI PR, PyPI release.
- **Dependabot + pre-commit + ruff format check** — configured.
- **Tests: 6 files / 1,015 lines** — stated "37 passing" is stale.
- **Competitive landscape doc** — thorough.

Further along than the checklist reads. Fix the 7 criticals + rebrand; rest is polish.
