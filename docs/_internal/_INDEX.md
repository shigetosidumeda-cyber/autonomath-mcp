**Owner**: 梅田茂利 (info@bookyou.net)
**Last reviewed**: 2026-04-30

# `docs/_internal/_INDEX.md` — active vs archived overview

Lightweight curation layer over the comprehensive [`INDEX.md`](./INDEX.md). Use this file to quickly locate currently-active strategy docs vs point-in-time archives.

> Audit date: 2026-04-30. 9 files moved to `_archive/2026-04/`. Re-audit cadence: monthly (first Monday).
> 2026-05-06 note: current execution SOT is `CURRENT_SOT_2026-05-06.md`; the active-plan list below is a historical curation snapshot.

---

## Active plans (the ones you should care about today)

The 3 must-know strategy / operations entry points:

1. **`llm_resilient_business_plan_2026-04-30.md`** — Primary strategy doc. LLM-resilient Evidence-Layer execution plan, ¥3/req metered, 8-cohort revenue model. Updated 2026-04-30.
2. **`seo_geo_strategy.md`** — SEO + GEO posture under the `jpcite` brand (post 税務会計AI rename). 301 redirect strategy from `zeimu-kaikei.ai`.
3. **`INDEX.md`** — Comprehensive runbook directory (75+ files in 10 categories: incident, billing, data, deploy, observability, perf, growth, launch, UX, ops continuity).

Other active surfaces (curated, not exhaustive — consult `INDEX.md` for the full table):

- `operators_playbook.md` / `operator_absence_runbook.md` / `operator_succession_runbook.md` — solo + zero-touch operations.
- `incident_runbook.md` / `launch_kill_switch.md` / `launch_war_room.md` / `fallback_plan.md` — incident response.
- `breach_notification_sop.md` / `tokushoho_maintenance_runbook.md` / `launch_compliance_checklist.md` / `stripe_tax_setup.md` / `stripe_webhook_rotation_runbook.md` — billing & legal.
- `dr_backup_runbook.md` / `data_integrity.md` / `autonomath_db_sync_runbook.md` / `autonomath_com_dns_runbook.md` / `ingest_automation.md` / `invoice_registrants_bulk_runbook.md` — data & DB.
- `deploy_staging.md` / `deploy_gotchas.md` / `dev_setup.md` / `env_setup_guide.md` / `cloudflare_deploy_log.md` / `jpcite_cloudflare_setup.md` / `api_domain_migration.md` / `stripe_webhook_migration.md` / `sdk_republish_after_rename.md` — deployment & release.
- `mcp_registry_runbook.md` / `mcp_registry_secondary_runbook.md` / `npm_publish_runbook.md` / `pypi_publish_runbook.md` / `hf_publish_runbook.md` / `sdk_release.md` — release / publish.
- `observability_dashboard.md` / `health_monitoring_runbook.md` / `slo.md` / `slo_log.md` — observability.
- `perf_baseline_2026-04-25.md` / `perf_baseline_v15_2026-04-25.md` / `capacity_plan.md` — perf & capacity (kept active because `slo.md` references the v15 baseline).
- `customer_dev_w5.md` / `customer_webhooks_design.md` / `referral_program_design.md` / `retention_digest.md` / `content_flywheel.md` / `seo_technical_audit.md` / `json_ld_strategy.md` / `competitive_watch.md` — growth & customer.
- `launch_dday_matrix.md` / `launch_followon.md` / `launch_partner_outreach.md` / `COORDINATION_2026-04-25.md` / `POST_DEPLOY_PLAN_W5_W8.md` / `GENERALIZATION_ROADMAP.md` — launch coordination (`COORDINATION_2026-04-25.md` retained because CLAUDE.md and `scripts/setup_stripe_device_flow.py` + `scripts/migrations/065_*.sql` cite it).
- `accessibility_audit.md` / `ab_copy_variants.md` / `conversion_funnel.md` / `i18n_strategy.md` / `email_setup.md` / `admin_api.md` / `preview_endpoints.md` / `secrets_inventory.md` / `integrations_setup.md` / `line_bot_operator_setup.md` — UX & site & integrations.
- `legal_contacts.md` / `saburoku_kyotei_gate_decision_2026-04-25.md` — legal (saburoku decision retained because `src/jpintel_mcp/config.py` + `mcp/autonomath_tools/resources.py` cite it).
- `npm_publish_log.md` / `pypi_publish_log.md` / `hf_publish_log.md` — publish history (append-only).

## Archived (point-in-time records, do not edit)

`_archive/2026-04/` — 9 files (audit reports + completed-handoff snapshots; mtimes 2026-04-25..2026-04-30):

- `PHASE_A_AUDIT_BY_LAUNCH_CLI_2026-04-25.md` — launch-CLI's audit of the Phase A handoff. Completed.
- `PHASE_A_HANDOFF_2026-04-25.md` — Phase A absorption handoff (V4 + 36協定). Completed (CLAUDE.md captures the durable summary).
- `archive_inventory_2026-04-25.md` — M4/K3 dead-code archive inventory. One-shot.
- `competitive_baseline_2026-04-29.md` — competitive / organic-search baseline (re-test cadence is in the doc itself; not actively cross-referenced).
- `data_freshness_2026-04-26.md` — read-only `programs.source_fetched_at` audit. Listing only, no live refs.
- `en_coverage_audit_2026-04-29.md` — `site/en/` coverage audit. Read-only.
- `ministry_source_audit_2026-04-29.md` — MAFF/MIC/MOJ/MHLW scaffold investigation. Read-only.
- `sentry_audit_2026-04-25.md` — v13→v14→v15 deploy-cycle Sentry triage. Read-only, point-in-time.
- `value_maximization_plan_no_llm_api.md` — superseded by `llm_resilient_business_plan_2026-04-30.md` (already archived; relocated under YYYY-MM bucket on 2026-04-30).

`archive/launch_2026-04-23/` — 4 legacy-launch snapshot files (`LAUNCH_BLOCKERS.md`, `LAUNCH_GAPS_AUDIT.md`, `LAUNCH_READINESS.md`, `README.md`). Pre-existing archive directory; left in place — name kept for git-history continuity.

---

## Deletion log

None this audit. Per the constraint "for ambiguous files: MOVE to archive, do not delete", everything questionable was archived rather than deleted.

## Audit method (for the next reviewer)

```bash
# Inventory
find docs/_internal/ -maxdepth 1 -name "*.md" -type f | wc -l
git log --diff-filter=A --name-only --pretty=format:'%h %ad' --date=short -- 'docs/_internal/' | head -60

# For each candidate, check inbound references in live code
grep -rln "<filename>" docs/ src/ scripts/ site/ tests/ tools/ CLAUDE.md README.md .github 2>/dev/null

# If ONLY referenced from docs/_internal/INDEX.md (or other archived docs), it is archive-eligible.
# If referenced from src/, scripts/cron/, .github/workflows/, or CLAUDE.md → KEEP.
```

Conventions:

- Move with `git mv` (preserve history). Never delete files with potential historical value.
- Group archives by month based on the most-recent meaningful mtime (or filename date suffix).
- The comprehensive directory is in [`INDEX.md`](./INDEX.md) — that file remains the operator's primary entry point.
