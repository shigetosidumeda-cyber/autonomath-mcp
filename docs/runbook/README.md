---
title: jpcite runbook index
updated: 2026-05-04
operator_only: true
category: index
---

# jpcite Runbook Index

Operator-facing playbooks for the jpcite (Bookyou株式会社, T8010001213708)
production stack. Every runbook below is **manual / operator-only** unless
explicitly marked as automated cron — solo zero-touch policy means there
is no on-call, no CS team, and no delegated ops.

Each runbook carries a `metadata` block at the top
(`title / updated / operator_only / category`). To rebuild this index,
walk `docs/runbook/*.md` and group by `category`.

## Index by category

### secret — secret/credential management

| Runbook | 1-line description | Operator | Last updated |
|---|---|---|---|
| [secret_rotation.md](secret_rotation.md) | Rotate / provision the 5 boot-gated production secrets (API_KEY_SALT, audit-seal HMAC, Stripe). | operator only | 2026-05-04 |
| [cors_setup.md](cors_setup.md) | Maintain the `JPINTEL_CORS_ORIGINS` Fly secret + add/remove allowlisted hosts. | operator only | 2026-05-04 |
| [ghta_r2_secrets.md](ghta_r2_secrets.md) | Mirror the four `R2_*` secrets into the GitHub repository secret store (Fly secret store ≠ GHA secret store) so nightly-backup / weekly-backup-autonomath / restore-drill-monthly workflows can talk to R2. | operator only | 2026-05-07 |

### deploy — service deployment + marketplace publishes

| Runbook | 1-line description | Operator | Last updated |
|---|---|---|---|
| [npm_publish_jpcite_sdk.md](npm_publish_jpcite_sdk.md) | Build + 2FA publish `@jpcite/sdk` to npm under the Bookyou org. | operator only | 2026-05-04 |
| [freee_mf_marketplace_submit.md](freee_mf_marketplace_submit.md) | Submit the freee + MoneyForward plugin apps for marketplace review. | operator only | 2026-05-04 |
| [stripe_meter_events_migration.md](stripe_meter_events_migration.md) | Migrate metered billing from `usage_records` → `meter_events` when Stripe deprecates the legacy API. | operator only | 2026-05-04 |
| [pages_deploy_lanes.md](pages_deploy_lanes.md) | Choose fast cached Pages deploy vs full Fly-backed regeneration so public updates do not repeatedly pay the heavy generated-page cost. | operator only | 2026-05-15 |

### brand — brand/identity surfaces

| Runbook | 1-line description | Operator | Last updated |
|---|---|---|---|
| [github_rename.md](github_rename.md) | One-shot rename `autonomath-mcp` → `jpcite-mcp` on GitHub + post-rename verifications. | operator only | 2026-05-04 |
| [pypi_jpcite_meta.md](pypi_jpcite_meta.md) | Publish/re-pin the `jpcite` PyPI meta-package whose only job is to install the real `autonomath-mcp` distribution. | operator only | 2026-05-04 |
| [social_profile_setup.md](social_profile_setup.md) | Stand up LinkedIn / X / GitHub Org / (optional) Wikidata for `sameAs` Knowledge Graph entity-binding. | operator only | 2026-05-04 |

### monitoring — observability + SEO indexing

| Runbook | 1-line description | Operator | Last updated |
|---|---|---|---|
| [sentry_setup.md](sentry_setup.md) | Apply 8 Sentry alert rules + 12 dashboard widgets via UI; route fatal → iOS push, all → email. | operator only | 2026-05-04 |
| [search_console_setup.md](search_console_setup.md) | Verify domain at Google + Bing + Yandex, submit sitemap-index.xml, wire IndexNow cron. | operator (one-time) + 自動 cron `index-now-cron.yml` | 2026-05-04 |

### dr — disaster recovery + replication

| Runbook | 1-line description | Operator | Last updated |
|---|---|---|---|
| [disaster_recovery.md](disaster_recovery.md) | 5 recovery scenarios (volume crash / total infra loss / R2 compromise / human error / drill failure) + R2 bucket setup. | operator (incidents) + 自動 cron `backup_jpintel.py` hourly / `backup_jpcite.py` daily | 2026-05-04 |
| [litestream_setup.md](litestream_setup.md) | Wire continuous WAL replication to R2 for sub-second RPO + point-in-time restore. **DRAFT — sidecar not yet deployed.** | operator (one-time cutover) + 自動 sidecar | 2026-05-04 |

### ETL — none currently

ETL runbooks live under `tools/offline/` (see `tools/offline/README.md`)
and `scripts/etl/` (no per-script runbook; each script is self-documenting
via `--help`). No file in `docs/runbook/` is ETL-categorised.

---

## Cross-runbook dependencies

```
secret_rotation ──▶ MASTER_PLAN_v1.md 付録 D (full Fly secret inventory; this runbook covers the 5 boot-gated only)
                ──▶ disaster_recovery §2 (R2 token quartet rotation — shared with litestream)
                ──▶ litestream_setup Step 2 (same R2 token quartet — single credential set)
                ──▶ cors_setup (JPINTEL_CORS_ORIGINS — non-boot-gated, separate runbook)
                ──▶ search_console_setup §2 (INDEXNOW_KEY — non-boot-gated, separate runbook)
                ──▶ stripe_meter_events_migration (STRIPE_SECRET_KEY / STRIPE_WEBHOOK_SECRET pin during cutover)

disaster_recovery ──▶ litestream_setup (PITR is the fast-path RTO tier; snapshot tier is the fallback beyond retention window)
                  ──▶ sentry_setup (`backup_integrity_failure` rule consumes the §3.5 drill output)
                  ──▶ stripe_meter_events_migration (§3.5 reconcile fallback if legacy path sunset mid-rollback)

litestream_setup ──▶ disaster_recovery §1 (RTO callout forward-references litestream Step 5/6 as fast path)
                 ──▶ secret_rotation (R2 token quartet — same credentials, do NOT mint a separate set)
                 ──▶ sentry_setup (`litestream_replication_lag` rule — added post-cutover per Operational notes)

github_rename ──▶ pypi_jpcite_meta (Repository URL pin must point at jpcite-mcp before re-publish)
              ──▶ npm_publish_jpcite_sdk (post-publish verify expects github.com/<org>/jpcite-mcp)
              ──▶ social_profile_setup §3.7-8 (sameAs URL backfill targets jpcite-mcp post-rename)

social_profile_setup ──▶ github_rename (rename source = autonomath-mcp → target = jpcite-mcp)
                     ──▶ npm_publish_jpcite_sdk (LinkedIn/X bios + sameAs link to npm scope @jpcite/sdk)

sentry_setup ──▶ stripe_meter_events_migration (`webhook_handler_exception_rate` rule guards cutover)
             ──▶ disaster_recovery (`backup_integrity_failure` rule)
             ──▶ litestream_setup (`litestream_replication_lag` rule, post-cutover)

cors_setup ──▶ secret_rotation (JPINTEL_CORS_ORIGINS rotation cadence = "永続" — modify on host changes only)

ghta_r2_secrets ──▶ disaster_recovery §2 (same R2 token quartet — Fly side; this runbook is the GHA side)
                ──▶ litestream_setup Step 2 (same R2 token quartet — single credential set across Fly + GHA)
                ──▶ secret_rotation (90-day rotation cadence; rotate Fly + GHA in lockstep)
```

---

## Audit findings (2026-05-04)

Cross-document gaps + inconsistencies surfaced while building this index.
None are blockers — the launch posture works as documented — but each is
worth a follow-up edit pass before production scaling.

| # | Finding | Severity | Files |
|---|---|---|---|
| A1 | **RESOLVED 2026-05-04** (W2-12). `MASTER_PLAN_v1.md` 付録 D updated to drop the aspirational `R2_BACKUP_SECRET` / `LITESTREAM_R2_KEY` pair and now lists the shared `R2_ENDPOINT` / `R2_ACCESS_KEY_ID` / `R2_SECRET_ACCESS_KEY` / `R2_BUCKET` set, matching `disaster_recovery.md` §2 + `litestream_setup.md` Step 2. | medium → fixed | `MASTER_PLAN_v1.md` 付録 D vs `disaster_recovery.md` §2 + `litestream_setup.md` Step 2 |
| A2 | **RESOLVED 2026-05-04** (W2-12). jpcite.db size unified to **9.5 GB** across `disaster_recovery.md` §1, `litestream_setup.md` "Why" + Step 4. `CLAUDE.md` snapshot is the source-of-truth (verify with `du -sh /data/jpcite.db` on Fly when refreshing). | low → fixed | `disaster_recovery.md` §1, `litestream_setup.md` |
| A3 | **RESOLVED 2026-05-04** (W2-12). `cors_setup.md` "Required origins (production)" now lists the actual legacy `zeimu-kaikei.ai` (apex/www/api) + `autonomath.ai` (apex/www) origins from `src/jpintel_mcp/config.py:236` default, with cross-reference to `_MUST_INCLUDE` in `src/jpintel_mcp/api/main.py:1107`. The Apply block + failure-mode commentary updated to match. | high → fixed | `cors_setup.md` "Required origins" vs `src/jpintel_mcp/config.py:236` + `src/jpintel_mcp/api/main.py:1107` |
| A4 | `secret_rotation.md` table lists 5 secrets (API_KEY_SALT, JPINTEL_AUDIT_SEAL_KEYS, AUDIT_SEAL_SECRET, STRIPE_WEBHOOK_SECRET, STRIPE_SECRET_KEY) — `MASTER_PLAN_v1.md` 付録 D adds `JPINTEL_CORS_ORIGINS` (covered by `cors_setup.md` instead, OK) and `INDEXNOW_KEY` (covered by `search_console_setup.md`, OK). **No gap** — the secret_rotation table is correctly scoped to boot-gated secrets only. | none (verified, re-verified W2-12 2026-05-04) | — |
| A5 | **RESOLVED 2026-05-04** (W2-12). `disaster_recovery.md` §1 now carries an explicit "Fast-path RTO via litestream PITR" callout that forward-references `docs/runbook/litestream_setup.md` Step 5 + Step 6 and notes the snapshot-tier path is the fallback for events older than the litestream retention window. | low → fixed | `disaster_recovery.md` §1 vs `litestream_setup.md` |
| A6 | **RESOLVED 2026-05-04** (W2-12). `social_profile_setup.md` step 3.7-8 now points the post-transfer rewrite at `github.com/<org>/jpcite-mcp` (post-rename target), and explicitly references `docs/runbook/github_rename.md` for the rename procedure (rename source = `autonomath-mcp` → rename target = `jpcite-mcp`). Per memory `feedback_no_trademark_registration`, brand alignment is rename-only. | medium → fixed | `social_profile_setup.md` §3 step 7-8 vs `github_rename.md` |
| A7 | **RESOLVED 2026-05-04** (W2-12). `npm_publish_jpcite_sdk.md` "Post-publish verification" now expects `https://github.com/<org>/jpcite-mcp` (post-rename target — see `docs/runbook/github_rename.md`). The pre-rename `autonomath-mcp` literal in this row is a historical / contextual reference to the rename source only. | low → fixed | `npm_publish_jpcite_sdk.md` "Post-publish verification" |

All seven 2026-05-04 audit findings are resolved as of W2-12 (2026-05-04).
A3 (CORS docs vs code) was the highest priority because it would mislead an
operator during an outage — that fix landed first.

**Re-audit 2026-05-04 (post Wave 1-4 runbook landing)**: all 7 W3-16 fixes
verified intact (grep checked: legacy `R2_BACKUP_SECRET` / `LITESTREAM_R2_KEY`
absent; jpcite.db size = 9.5 GB across both `disaster_recovery.md` + `litestream_setup.md`;
`cors_setup.md` "Required origins" still lists jpcite + zeimu-kaikei + autonomath
apex/www/api per `_MUST_INCLUDE`; fast-path PITR callout in `disaster_recovery.md` §1
intact; `social_profile_setup.md` §3.7-8 still targets jpcite-mcp; `npm_publish_jpcite_sdk.md`
post-publish row still expects jpcite-mcp). One minor drift fixed in this pass:
`secret_rotation.md` opening sentence said "four production secrets" while the table
listed five — corrected to "five" + added cross-ref to 付録 D.

---

## How to add a new runbook

1. Create `docs/runbook/<name>.md` with the metadata block:
   ```markdown
   ---
   title: <human-readable title>
   updated: YYYY-MM-DD
   operator_only: true
   category: secret|deploy|brand|monitoring|dr|ETL
   ---
   ```
2. Add a row to the appropriate "Index by category" table above.
3. Update the cross-runbook dependency graph if the new runbook is
   referenced by an existing one.
4. Re-run the audit grep:
   ```bash
   ls docs/runbook/*.md | wc -l   # must be ≥ 12
   grep -L "^---$" docs/runbook/*.md | grep -v README.md   # must be empty
   ```
