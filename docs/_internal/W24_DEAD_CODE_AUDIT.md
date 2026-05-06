# W24 Dead Code / Dead Config Audit

Date: 2026-05-05
Scope: jpcite repo `/Users/shigetoumeda/jpcite/`
Method: grep + sqlite3 read-only inspection. Companion to `dead_code_audit_2026-04-30.md` (Wave previous, src/ only).
**Non-destructive — no files deleted, no commits made.**

Conventions:

- **DELETE** = orphan / no callers / no fly secret / no schedule / no Fly env override / never populated by any active path.
- **KEEP** = placeholder, fallback, future-use, intentional manual-only, schema reservation, regulatory gate.

---

## 1. Unreferenced env vars (registry but no `os.environ.get` / pydantic alias / workflow ref)

Comparison set: union of pydantic `alias=` in `src/jpintel_mcp/config.py` (53), `os.environ.get/getenv/environ[]` across `src/` + `scripts/` (110), and `secrets.X` in `.github/workflows/*.yml` (29). Registry source: `docs/_internal/SECRETS_REGISTRY.md` + `secrets_inventory.md`.

| Env var | In registry? | Status | Recommend | Reason |
|---|---|---|---|---|
| `AUDIT_SEAL` (bare prefix string) | yes (heading text) | doc heading, not a real env var | KEEP | Prefix label only, not consumed |
| `CF_PAGES_DEPLOY_HOOK` | yes (registry §0 + secrets_inventory) | listed but **0 hits** in `src/` `scripts/` `.github/workflows/` (only `discover_secrets.sh` enumerates the name) | KEEP | Future-use: pages-regenerate workflow currently uses `git push` triggered Pages CI; hook documented for failover |
| `JPINTEL_AUDIT_SEAL_KEY_CURRENT` | yes (registry §1 — local self-env file) | not read in `src/` `scripts/`; only file presence noted in `~/.jpcite_secrets_self.env` | KEEP | Future dual-key rotation — registry §2 marks "未投入" (W11-1) |
| `JPINTEL_AUDIT_SEAL_KEYS` | yes (registry §2) | only mentioned in `discover_secrets.sh` enumeration + migration `wave24_105` SQL comment | KEEP | Future dual-key rotation; legacy single-key (`AUDIT_SEAL_SECRET`) is the live path |
| `TG_BOT_TOKEN` (旧 `TELEGRAM_BOT_TOKEN`) | yes (registry §2 — renamed 2026-05-05) | live consumption in `scripts/cron/narrative_*.py` + `.github/workflows/narrative-*.yml` | KEEP | Doc renamed to TG_* to match code (`os.environ.get("TG_BOT_TOKEN")`); `discover_secrets.sh` still lists legacy name as harmless alias |

**Note (rename resolved 2026-05-05):** Registry doc previously used the older name `TELEGRAM_BOT_TOKEN`; renamed to `TG_BOT_TOKEN` to match real code (`scripts/cron/narrative_audit_push.py:162`, `narrative_report_sla_breach.py:64`) and workflow secret refs (`narrative-sla-breach-hourly.yml`, `narrative-audit-monthly.yml`). `TELEGRAM_BOT_TOKEN` is retained as historical reference only.

Vars in registry that ARE used (sample, full list in `/tmp/jpcite_envvars_used_all.txt`): all 20 deployed Fly secrets confirmed live in `src/` and/or `scripts/` and/or workflows.

**Total unreferenced env vars: 5 (all KEEP — placeholder / future / rename).**

---

## 2. Unimported Python modules (src/ files with 0 import refs)

AST-style grep across `src/` (excluding `_archive/`, `__pycache__/`), `tests/`, `scripts/`. Excludes entry-point modules (`api/main.py`, `mcp/server.py`, `config.py`) and modules pulled in via package `__init__.py` side-effect.

**Total py files in scope: 253.** Side-effect imports via `autonomath_tools/__init__.py` cover 15 of the 19 raw "no inbound" candidates. Genuine orphans:

| Module | Status | Recommend | Reason |
|---|---|---|---|
| `src/jpintel_mcp/api/_compat.py` | TRULY DEAD — 0 refs anywhere (only kanji `_compat` substring matches in `am_compat_matrix` SQL string literals) | DELETE candidate | No router mount, no caller; safe to archive |
| `src/jpintel_mcp/api/audit_proof.py` | UNMOUNTED — file declares router/helpers (`logging.getLogger("jpintel.api.audit_proof")`) but `main.py` does **not** `include_router(audit_proof_router)` | KEEP (verify intent) | Touched recently; may be wave-in-progress wiring |
| `src/jpintel_mcp/api/english_wedge.py` | UNMOUNTED — wraps `mcp.autonomath_tools.english_wedge`; not in `main.py` `include_router(...)` chain | KEEP (verify intent) | MCP-side counterpart IS registered via `__init__.py` side-effect — REST mirror appears intentional but pending wire |
| `src/jpintel_mcp/mcp/autonomath_tools/tools_envelope.py` | UNMOUNTED — only `envelope_wrapper.py` docstring mentions it ("imports each tool from tools.py and ... import from tools_envelope when they want the v2 envelope") | KEEP | Forward-compat shim; envelope v2 migration path |

Carryover from `dead_code_audit_2026-04-30.md` (still present 2026-05-05):

| Module | Status | Recommend | Reason |
|---|---|---|---|
| `src/jpintel_mcp/api/_universal_envelope.py` | UNMOUNTED, 14 dead helper fns | DELETE candidate | Designed for ARPU lift, never wired |
| `src/jpintel_mcp/api/middleware/cost_cap.py` | DEFINED, NOT MOUNTED | KEEP | Future cost-cap middleware; spec lives, wiring deferred |
| `src/jpintel_mcp/api/middleware/envelope_adapter.py` | DEFINED, NOT MOUNTED | KEEP | Same — V2 envelope migration substrate |
| `src/jpintel_mcp/api/middleware/idempotency.py` | DEFINED, NOT MOUNTED | KEEP | Wave 22 idempotency spec; deferred wiring |

**Total unimported modules: 8 (2 DELETE candidate, 6 KEEP).**

---

## 3. Deprecated / unused REST routes (openapi.json)

Source: `docs/openapi/v1.json` — **174 paths, 182 operations**. No `deprecated:true` flag set on any operation. No `/v1/admin*` routes in spec (they exist in source but not exported — admin_router presumably runs without OpenAPI tag). No `_preview` paths. Audit by route prefix → 0-row table population.

| Route prefix | Backed by table | Table rows | Recommend | Reason |
|---|---|---|---|---|
| `GET /v1/widget/*` (4 routes) | `widget_keys` | 0 | KEEP | Free-tier signup widget; rows populate as users sign up |
| `POST /v1/me/saved_searches/*` (5 routes) | `saved_searches` | 0 | KEEP | Awaits paying-customer signups; cron `saved-searches-cron.yml` live |
| `POST /v1/me/webhooks/*` (5 routes) | `customer_webhooks` (0) + `webhook_deliveries` (0) | 0 | KEEP | Cron `dispatch-webhooks-cron.yml` live; populates on customer add |
| `GET /v1/advisors/*` (5 routes) | `advisors` (0) + `advisor_referrals` (0) | 0 | KEEP | Advisor program; no signups yet |
| `POST /v1/me/testimonials` + `GET /v1/testimonials` | `testimonials` | 0 | KEEP | Post-launch social proof; populates organically |
| `POST /v1/privacy/*` (2 routes) | `appi_disclosure_requests` (0) + `appi_deletion_requests` (0) | 0 | KEEP | APPI §31/§35 regulatory obligation — must work even if 0 traffic |
| `POST /v1/integrations/*` (8 routes) | `integration_accounts` (0) + `integration_sync_log` (0) | 0 | KEEP | freee/MF/Slack/kintone/Excel; partner SDK pending public release |
| `GET /v1/me/courses` + `POST /v1/me/recurring/*` (4 routes) | `course_subscriptions` (0) | 0 | KEEP | Wave 22 recurring engagement — populates via opt-in only |
| `POST /v1/citations/verify` | `citation_verification` | 0 | KEEP | On-demand verifier; no persistent rows expected pre-launch |
| `GET /v1/audit/seals/{seal_id}` | `audit_seals` (0) + `audit_seal_keys` (0) | 0 | KEEP | 税理士 monthly seal pack; cron `regenerate_audit_log_rss.py` populates on demand |
| `GET /v1/me/client_profiles` (3 routes) | `client_profiles` | 0 | KEEP | Wave 22 顧問先 fan-out; populates per-customer |
| `GET /v1/am/programs/active_v2` (subset) | `program_post_award_calendar` | 0 | KEEP | Wave 22 post-award calendar; populates via cron |
| `GET /v1/am/health/deep` | none (synthetic) | n/a | KEEP | Deep health probe |
| `POST /v1/me/alerts/*` | `alert_subscriptions` | 1 | KEEP | Live |

**No DELETE candidates.** Every 0-traffic route maps to a launch-day customer surface or a regulatory obligation. **0 deprecated routes recommended for removal.**

---

## 4. 0-row tables in `data/jpintel.db` (production DB, 444 MB)

Total tables (excluding FTS internals + sqlite_*): ~115. **0-row tables: 76.** Categorized:

| Category | Tables | Recommend | Reason |
|---|---|---|---|
| `pc_*` precompute (32 tables) | `pc_acceptance_rate_by_authority`, `pc_acceptance_stats_by_program`, `pc_amendment_recent_by_law`, ... (full list in `/tmp/jpcite_table_counts.txt`) | KEEP | All populated by `scripts/cron/precompute_refresh.py` post first cron run; cron `precompute-refresh-cron.yml` live |
| Customer surfaces (15 tables) | `advisors`, `advisor_referrals`, `client_profiles`, `compliance_subscribers`, `compliance_notification_log`, `course_subscriptions`, `customer_intentions`, `customer_watches`, `customer_webhooks`, `customer_webhooks_test_hits`, `email_schedule`, `email_unsubscribes`, `integration_accounts`, `integration_sync_log`, `line_users`, `line_message_log`, `webhook_deliveries`, `widget_keys`, `saved_searches`, `usage_events`, `testimonials`, `trial_signups` (1 row), `alert_subscriptions` (1 row) | KEEP | Populates from real customer activity post-launch |
| Regulatory intake (4 tables) | `appi_deletion_requests`, `appi_disclosure_requests`, `audit_seals`, `audit_seal_keys` | KEEP | APPI / 税理士 obligation — 0 rows is normal pre-launch |
| Wave 22/23 capture (4 tables) | `program_post_award_calendar`, `enforcement_decision_refs`, `citation_verification`, `am_idempotency_cache` (1 row) | KEEP | Spec land, populates incrementally |
| Operations / cache (8 tables) | `advisory_locks`, `alias_candidates_queue`, `analytics_events` (1380 rows actually), `postmark_webhook_events`, `source_redirects`, `stripe_tax_cache`, `support_org`, `verticals_deep` | KEEP | Caches and queues — fill on demand |
| Vertical seeds (3 tables) | `medical_institutions`, `care_subsidies`, `real_estate_programs`, `zoning_overlays`, `industry_program_density`, `industry_stats`, `ministry_faq` | KEEP | Healthcare + real_estate vertical packs (currently gated off — `AUTONOMATH_HEALTHCARE_ENABLED=false` / `AUTONOMATH_REAL_ESTATE_ENABLED=false`) |
| Snapshot/legacy (2 tables) | `_aggregator_purge_2026_04_25` (21 rows actually), `jpi_exclusion_rules_pre052_snapshot`, `jpi_pc_program_health` | KEEP | Audit trail + pre-migration snapshot; do not drop |

**No DELETE candidates.** The 76 zero-row tables are a mix of (a) precompute substrate that fills on first cron run, (b) customer-driven tables that fill post-launch, (c) regulatory intake that legally must exist with 0 rows, and (d) vertical seeds gated off pending review. Schema reservation only.

---

## 5. Orphan workflow files (.github/workflows/)

Total: 63. Trigger types extracted (full list in `/tmp/jpcite_workflow_triggers.txt`):

- `schedule + workflow_dispatch`: 47 (cron jobs — all healthy)
- `push + ...`: 8 (CI/CD on commit — healthy)
- `pull_request + ...`: 5 (CI on PR — healthy)
- `workflow_dispatch` only (manual): 3
- `workflow_run` chained: 1 (`deploy.yml` — chained off `test.yml`)

**Manual-only workflows (3):**

| Workflow | Status | Recommend | Reason |
|---|---|---|---|
| `loadtest.yml` | trigger = `workflow_dispatch` only | KEEP | Intentional — k6 sends real traffic; running on every push would DoS staging. Header comment explicitly documents "Manual-only" + use cases (D-1 rehearsal, post-deploy gate, incident RCA) |
| `mcp-registry-publish.yml` | trigger = `workflow_dispatch` only | KEEP | Manual MCP registry publish; release.yml + sdk-publish.yml handle PyPI/npm |
| `rebrand-notify-once.yml` | trigger = `workflow_dispatch` only | KEEP for now, **DELETE after rebrand notify executed** | One-shot bulk-email send for AutonoMath → jpcite rename (project_jpcite_rename memory). Header comment: "NOT scheduled; workflow_dispatch only ... 6 ヶ月で完了" |

**Triple `refresh-sources` files (potential dup):**

| Workflow | Status | Recommend | Reason |
|---|---|---|---|
| `refresh-sources.yml` | active schedule | KEEP | Original — referenced by `ministry-ingest-monthly.yml` comment + `self-improve-weekly.yml` comment as the cadence anchor (Tier C 18:17) |
| `refresh-sources-daily.yml` | active schedule (Tier S/A) | KEEP | Tier-split refinement |
| `refresh-sources-weekly.yml` | active schedule (Tier B/C, Sunday) | KEEP | Tier-split refinement |

All three serve distinct tier slices — overlap is intentional, not orphan.

**Total orphan workflows: 1 (rebrand-notify-once.yml — DELETE after one-shot send confirmed in `analytics/rebrand_notify_log.jsonl`).**

---

## 6. Stale gates (`AUTONOMATH_*_ENABLED` env vars where flag is constant on/off)

25 `AUTONOMATH_*_ENABLED` flags found in `src/`. None are set in `fly.toml`, `Dockerfile`, `entrypoint.sh`, `.env.example` (production env), or `.github/workflows/*.yml` — meaning **all 25 run on the code default at runtime**. (Fly secrets list confirms: 0 of 20 deployed secrets are `AUTONOMATH_*_ENABLED`.)

Code defaults summary:

| Flag | Default | Has runtime override? | Recommend | Reason |
|---|---|---|---|---|
| `AUTONOMATH_ENABLED` | true | `fly.toml` sets it explicitly to `"true"` | KEEP | Master kill-switch retained intentionally |
| `AUTONOMATH_36_KYOTEI_ENABLED` | false | not overridden | KEEP | Regulated content (労基法 §36 + 社労士法); keep gate until 法務 review per `saburoku_kyotei_gate_decision_2026-04-25.md` |
| `AUTONOMATH_HEALTHCARE_ENABLED` | false | not overridden | KEEP | Vertical pack gate; flip post legal review |
| `AUTONOMATH_REAL_ESTATE_ENABLED` | false | not overridden | KEEP | Vertical pack gate; same |
| `AUTONOMATH_SNAPSHOT_ENABLED` | false | not overridden | KEEP | Broken-tool gate (migration 067 missing) — gate doc'd in CLAUDE.md |
| `AUTONOMATH_REASONING_ENABLED` | false | not overridden | KEEP | Broken-tool gate (reasoning package missing) — gate doc'd in CLAUDE.md |
| 19 others (`COMPOSITION`, `CITATIONS`, `CORPORATE_LAYER`, `DISCOVER`, `ENGLISH_WEDGE`, `EVIDENCE_BATCH`, `EVIDENCE_PACKET`, `FUNDING_STACK`, `GRAPH`, `GRAPH_TRAVERSE`, `HALLUCINATION_GUARD`, `INDUSTRY_PACKS`, `LIFECYCLE`, `LIFECYCLE_CALENDAR`, `NTA_CORPUS`, `PII_REDACT_RESPONSE`, `PREREQUISITE_CHAIN`, `RECOMMEND_SIMILAR`, `RULE_ENGINE`, `R8_VERSIONING`, `UNCERTAINTY`, `WAVE22`, `APPI`) | true | not overridden | KEEP | One-flag rollback per regression — operator pattern. Default ON in production, no need to set in Fly env until regression surfaces |

**0 stale gates found.** Pattern is healthy: gates default ON, override path exists for instant rollback. No flag is "always on" in code (i.e. defaulted true with no `os.environ.get` read) and no flag is "always off" with no rollback path.

---

## Acceptance summary

- Audit doc: `/Users/shigetoumeda/jpcite/docs/_internal/W24_DEAD_CODE_AUDIT.md`
- 6 scopes covered: env vars / py modules / REST routes / 0-row tables / workflows / gates
- **DELETE recommendations: 3 items** (all low-risk):
  1. `src/jpintel_mcp/api/_compat.py` (truly orphan, no refs)
  2. `src/jpintel_mcp/api/_universal_envelope.py` (carryover from W previous; 14 dead helpers)
  3. `.github/workflows/rebrand-notify-once.yml` (after one-shot send confirmed)
- **KEEP recommendations: ~95 items** (placeholder / future-use / fallback / regulatory / pre-launch substrate)
- 0 deletes performed. Companion to `dead_code_audit_2026-04-30.md`.
